"""End-to-end smoke check against the REAL index and the REAL model.

Deliberately NOT part of the pytest suite: it calls OpenAI and costs money.
Run it by hand after changing retrieval, the prompt, or the citation format —
those are the things the mocked tests cannot tell you about, because they
depend on how the actual model behaves against the actual corpus.

It exercises the full pipeline without needing a Supabase JWT:
  search -> build_source_payload -> streamed answer -> citation validation

Checks worth watching:
  * time to first token (the whole point of streaming)
  * "hallucinated" citations — indices outside 1..len(sources). The UI leaves
    these as literal text rather than linking them to nothing, so a non-zero
    count here means the prompt is drifting, not that the UI is broken.
  * "legacy prose citations remaining" — should be 0. Anything else means the
    model reverted to "[Source: Doc, Page: N]" and normalize_legacy_citations
    could not map it back.

Usage:
    python scripts/smoke_real.py
    python scripts/smoke_real.py "ما هي متطلبات تسجيل الأدوية؟" ar
"""

import contextlib
import os
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A Windows console defaults to cp1252, which cannot encode Arabic — so this
# script died on `print` before reaching any of the pipeline it exists to
# check, and the Arabic half of the product had no smoke test at all.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):  # pragma: no cover - non-standard stream
        _stream.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

from web.services.citations import build_source_payload, normalize_legacy_citations
from web.services.openai_app import OpenAIHandler
from web.services.search_engine import ImprovedSearchEngine

QUERY = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "What are the requirements for drug registration in Saudi Arabia?"
)
LANG = sys.argv[2] if len(sys.argv) > 2 else "en"

print(f"query: {QUERY!r}  lang={LANG}\n" + "-" * 70)

t0 = time.time()
engine = ImprovedSearchEngine()
if not engine.is_initialized():
    engine.initialize()
print(f"[{time.time() - t0:5.1f}s] search engine ready")

handler = OpenAIHandler()
print(
    f"[{time.time() - t0:5.1f}s] model={handler.model} max_context_results={handler.max_context_results}"
)

t1 = time.time()
results = engine.search(QUERY, "regulatory")
print(f"[{time.time() - t0:5.1f}s] retrieved {len(results)} passages in {time.time() - t1:.2f}s")

sources = build_source_payload(results, limit=handler.max_context_results)
print("\nSOURCES")
for s in sources:
    print(
        f"  [{s['index']}] {s['document'][:52]:<52} p.{s['page']!s:<5} "
        f"score={s['score']}  sem={s['semantic_score']}  lex={s['lexical_score']}"
    )

# JSON-serialisability is the thing that silently 500s in production.
import json

json.dumps(sources)
print("  -> payload is JSON-native OK")

llm_context = [
    {"text": r.text, "document": r.document, "category": r.category, "page": r.page}
    for r in results
]

print("\nSTREAMING")
t2 = time.time()
first = None
parts = []
for token in handler.stream_response(QUERY, llm_context, "regulatory", [], lang=LANG):
    if first is None:
        first = time.time() - t2
        print(f"  first token after {first:.2f}s")
    parts.append(token)
answer = normalize_legacy_citations("".join(parts).strip(), sources)
print(f"  {len(parts)} tokens, {len(answer)} chars, total {time.time() - t2:.2f}s")

print("\nANSWER\n" + "-" * 70)
print(answer[:1400])
print("-" * 70)

import re

# The same function the route uses, rather than a second copy of the marker
# grammar — two copies in one repo is how the JS and Python sides drift. This
# used to re-derive "hallucinated" by findall-ing every [n] a second time and
# diffing it against extract_cited_indices's output; extract_cited_indices
# was already computing that split internally and discarding it, so both
# copies are gone in favor of the one function that classifies markers once.
from web.services.citations import extract_citation_diagnostics

diagnostics = extract_citation_diagnostics(answer, sources)
valid = diagnostics.cited
bad = sorted(set(diagnostics.invalid))
seen = sorted(set(valid) | set(bad))
hallucinated_rate = (
    len(diagnostics.invalid) / diagnostics.total_markers if diagnostics.total_markers else 0.0
)
print(f"\nCITATIONS: {seen or 'NONE'}")
print(f"  valid (these become the answer's sources): {valid}")
print(f"  hallucinated (left as literal text by the UI): {bad or 'none'}")
print(
    f"  hallucinated_marker_rate: {hallucinated_rate:.1%} "
    f"({len(diagnostics.invalid)}/{diagnostics.total_markers} markers)"
)
legacy = len(re.findall(r"\[Source:", answer))
print(f"  legacy prose citations remaining: {legacy}")

# The whole point of the change: no citations means no source panel.
if valid:
    docs = {s["document"] for s in sources if s["index"] in valid}
    print(f"\n  → panel shows {len(valid)} passage(s) from {len(docs)} document(s)")
elif sources:
    print(
        f"\n  → no citations: NO source control rendered "
        f"({len(sources)} passage(s) retrieved, none offered as evidence)"
    )
else:
    print("\n  → nothing retrieved: NO source control rendered at all")

print("\nSUGGESTIONS")
for q in handler.generate_suggestions(QUERY, answer, lang=LANG):
    print("  -", q)


# ── The daily allowance, against the REAL database ──────────────────────────
# This is the deploy check that matters for the quota, and it belongs here
# rather than in pytest for the same reason the rest of this file does: the
# mocked suite cannot tell you whether the RPC exists, whether `service_role`
# may execute it, or whether PostgREST's schema cache has caught up after a
# migration. Those are exactly the faults that would otherwise hand every
# reader an uncounted allowance until somebody read the logs.
#
# It costs nothing — no model call — and cleans up after itself: the claim it
# makes is released before the script exits.
print("\nDAILY ALLOWANCE (real RPCs)")
try:
    from web.services.quota_store import get_quota_backend
    from web.utils.supabase_client import get_supabase_admin

    quota_backend = get_quota_backend()
    if quota_backend is None:
        print("  SKIPPED - no service-role key, so this deployment counts nothing.")
    else:
        client = get_supabase_admin()
        rows = client.table("profiles").select("id").limit(1).execute().data
        if not rows:
            print("  SKIPPED - no account to probe.")
        else:
            probe = rows[0]["id"]
            before = quota_backend.status(probe, 200)
            claim = quota_backend.claim(probe, 200)
            if not claim.allowed:
                print(f"  WARNING - probe account already exhausted ({claim.used}/{claim.limit}).")
            assert claim.day, "the claim returned no day; the refund cannot be day-safe"

            # Released against the day the CLAIM returned, never a recomputed
            # "today" — the whole reason `day` rides on the claim.
            quota_backend.release(probe, claim.day)
            after = quota_backend.status(probe, 200)
            assert after.used == before.used, (
                f"refund did not land: {before.used} -> {claim.used} -> {after.used}"
            )

            print(
                f"  tier={before.tier_key} "
                f"({before.tier_label_en}/{before.tier_label_ar}) "
                f"limit={before.limit} used={before.used}"
            )
            print(f"  resets_at={before.resets_at}  (midnight Asia/Riyadh)")
            print(f"  claim -> used={claim.used}, release -> used={after.used}")
            print(f"  consecutive backend faults: {quota_backend.fault_count}")
            print("  OK - claim, release and status reachable through service_role.")
except Exception as exc:
    print(f"  FAILED - {type(exc).__name__}: {exc}")
    print("  Check that the migrations applied and that service_role holds EXECUTE.")
