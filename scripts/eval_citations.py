"""Citation-format baseline harness: does a model FOLLOW the citation contract?

Deliberately NOT part of the pytest suite: it calls a real completions API and
costs money, same posture as scripts/smoke_real.py. Run it by hand.

**Scope — read this before trusting a number out of this script.** Every
metric here is Layer 1: marker validity, coverage, refusal cleanliness,
cross-turn leakage. None of it proves a cited passage actually SUPPORTS the
claim it's attached to — extract_cited_indices (web/services/citations.py)
only proves the model emitted a marker. Report these numbers as a
"citation-format baseline", never as "fidelity" or "grounding". Grounding is
Layer 2 (web/services/citation_fidelity.py, an NLI model — English only
today) and Layer 3 (a human judge, see docs/citation-eval-judge-protocol.md).
This distinction is exactly what an adversarial review of this harness's
design plan caught before it shipped.

**Cost accounting is approximate.** stream_response (openai_app.py) does not
request provider usage on the stream, so this script counts tokens with the
handler's own tokenizer instead of asking the provider — the same estimate
smoke_real.py already logs. UsageEstimate.exact is always False here;
treat --out's cost figures as an order-of-magnitude guide, not a bill.

Mirrors scripts/eval_retrieval.py's shape: load_probes -> run (expensive, one
real call per probe, no caching) -> evaluate (cheap, offline over what run()
collected) -> compare (the gate). Unlike eval_retrieval.py this DOES call the
model — there is no free-as-in-retrieval-only variant of a citation check.

Usage:
    python scripts/eval_citations.py --limit 10
    python scripts/eval_citations.py --baseline gpt-4o-mini --model deepseek-v4-flash
    python scripts/eval_citations.py --group refusal --no-ar
    python scripts/eval_citations.py --group multi_source --judge --out judge_packet.jsonl
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# See scripts/smoke_real.py for why: a Windows console defaults to cp1252,
# which cannot encode Arabic, and this harness's probe set is bilingual.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, ValueError):  # pragma: no cover - non-standard stream
        _stream.reconfigure(encoding="utf-8", errors="replace")

import yaml
from dotenv import load_dotenv

load_dotenv()

from web.services.citation_eval_metrics import (
    MetricSummary,
    compare_to_baseline,
    language_parity_gap,
    leakage_check,
    legacy_intervention_occurred,
    marker_coverage,
    refusal_is_clean,
)
from web.services.citations import (
    build_source_payload,
    extract_citation_diagnostics,
    normalize_legacy_citations,
)
from web.services.openai_app import OpenAIHandler
from web.services.result_combiner import SearchResult
from web.services.search_engine import ImprovedSearchEngine
from web.services.settings_service import deployed_defaults

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "tests", "data"
)
PROBES = os.path.join(DATA_DIR, "citation_eval.yaml")
CANDIDATES = os.path.join(DATA_DIR, "citation_eval_candidates.yaml")

# Probes shaped as a fixed turn sequence rather than a single query — see
# citation_eval.yaml's module comment for why the assistant turn in these
# groups is hand-authored and fixed rather than generated live.
TURN_GROUPS = ("cross_turn", "legacy_format")


def load_probes(args) -> list[dict[str, Any]]:
    with open(PROBES, encoding="utf-8") as handle:
        groups = yaml.safe_load(handle)

    probes: list[dict[str, Any]] = []
    for group, entries in groups.items():
        if args.group and group != args.group:
            continue
        for entry in entries or []:
            lang = entry.get("lang") or (
                entry.get("turns", [{}])[-1].get("lang") if group in TURN_GROUPS else None
            )
            if args.no_ar and lang == "ar":
                continue
            if args.judge and not entry.get("judge"):
                continue
            probes.append({**entry, "group": group})

    if args.limit:
        probes = probes[: args.limit]
    return probes


def load_candidates() -> dict[str, dict[str, Any]]:
    with open(CANDIDATES, encoding="utf-8") as handle:
        return {c["id"]: c for c in yaml.safe_load(handle)}


def build_handler(model_id: str | None, candidates: dict[str, dict[str, Any]]) -> OpenAIHandler:
    """A handler for *model_id* — a harness candidate, or the live deployed default.

    A harness candidate (present in citation_eval_candidates.yaml) is built
    with an explicit model_contract override, since model_spec() has never
    heard of it — see OpenAIHandler._request_kwargs's docstring for why that
    matters. Anything else is built from the live deployed defaults
    (deployed_defaults(), the same values apply_generation_settings reads),
    with model_id substituted in if given — this is what makes --baseline
    default to "whatever's actually running" rather than a hardcoded id.
    """
    if model_id and model_id in candidates:
        candidate = candidates[model_id]
        settings = {
            "model": candidate["id"],
            "base_url": candidate.get("base_url"),
            "api_key_env": candidate.get("api_key_env"),
            "max_tokens": candidate.get("max_output_tokens"),
            "model_contract": {
                "token_param": candidate.get("token_param", "max_tokens"),
                "supports_temperature": candidate.get("supports_temperature", True),
                "reasoning_efforts": candidate.get("reasoning_efforts", []),
            },
        }
        return OpenAIHandler(settings)

    settings = dict(deployed_defaults())
    if model_id:
        settings["model"] = model_id
    return OpenAIHandler(settings)


def _search(
    engine: ImprovedSearchEngine, query: str, category: str, probe: dict[str, Any]
) -> list[SearchResult]:
    """Real retrieval, or the probe's own synthetic_context when it has one.

    synthetic_context (adversarial group) hand-crafts the retrieved passages
    directly instead of relying on the real corpus to happen to contain an
    adversarial one — full control, fully reproducible across every model
    under test.
    """
    if "synthetic_context" in probe:
        return [
            SearchResult(
                text=block["text"],
                score=1.0,
                document=block["document"],
                category=block.get("category", category),
                page=block.get("page"),
            )
            for block in probe["synthetic_context"]
        ]
    return engine.search(query, category)


def _answer(
    handler: OpenAIHandler,
    query: str,
    results: list[SearchResult],
    category: str,
    chat_history: list[dict[str, Any]],
    lang: str,
) -> dict[str, Any]:
    """The answer-ONLY path: no follow-up-suggestions call.

    generate_response makes a second, separate completions call for
    suggestions on every turn — skipping it here is the plan's cost fix, not
    an oversight: the harness measures citations, not suggestion quality, and
    doubling every probe's cost to compute a number nobody reads is not a
    trade worth making.
    """
    llm_context = [
        {"text": r.text, "document": r.document, "category": r.category, "page": r.page}
        for r in results
    ]
    sources = build_source_payload(results, limit=handler.max_context_results)
    raw = "".join(handler.stream_response(query, llm_context, category, chat_history, lang)).strip()

    # The SAME normalize -> extract sequence _finalize_answer (web/api/app.py)
    # applies — calling stream_response directly, as this harness does, skips
    # the route's finalization step, so that sequence is repeated here rather
    # than measuring a shortcut around it.
    normalized = normalize_legacy_citations(raw, sources)
    diagnostics = extract_citation_diagnostics(normalized, sources)
    cited_sources = [s for s in sources if s["index"] in diagnostics.cited]

    return {
        "raw": raw,
        "normalized": normalized,
        "sources": sources,
        "diagnostics": diagnostics,
        "cited_sources": cited_sources,
    }


def run(
    handler: OpenAIHandler, engine: ImprovedSearchEngine, probes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Run every probe through the REAL pipeline, once. Expensive; no caching."""
    for probe in probes:
        try:
            if probe["group"] in TURN_GROUPS:
                _run_turn_probe(handler, engine, probe)
            else:
                _run_flat_probe(handler, engine, probe)
        except Exception as exc:
            label = probe.get("query") or probe.get("pair_id") or "?"
            print(f"  !! {label[:50]!r} failed: {exc}")
            probe["error"] = str(exc)
            continue

        label = probe.get("query") or probe.get("pair_id") or "?"
        print(f"  {probe['group']:<20} {probe.get('lang', '?'):<3} ok  {label[:52]}")
    return probes


def _run_flat_probe(
    handler: OpenAIHandler, engine: ImprovedSearchEngine, probe: dict[str, Any]
) -> None:
    category = probe.get("category", "all")
    results = _search(engine, probe["query"], category, probe)
    probe["answer"] = _answer(
        handler, probe["query"], results, category, [], probe.get("lang", "en")
    )


def _run_turn_probe(
    handler: OpenAIHandler, engine: ImprovedSearchEngine, probe: dict[str, Any]
) -> None:
    """A fixed history + one live final turn — see citation_eval.yaml's note.

    Two things are checked: whether _history_without_stale_markers actually
    stripped the injected assistant marker before this turn's prompt was
    assembled (leakage_check, against the REAL _build_messages output — the
    same seam test_prompt_assembly_strips_markers_from_replayed_turns in
    web/tests/test_citations.py exercises, run here end-to-end against a
    live handler), and the final turn's own ordinary Layer-1 metrics.
    """
    *history_turns, last = probe["turns"]
    category = last.get("category", "all")
    lang = last.get("lang", "en")
    chat_history = [{"role": t["role"], "content": t["content"]} for t in history_turns]

    results = engine.search(last["content"], category)
    llm_context = [
        {"text": r.text, "document": r.document, "category": r.category, "page": r.page}
        for r in results
    ]

    messages = handler._build_messages(
        last["content"], llm_context, category, chat_history=chat_history, lang=lang
    )
    probe["leakage"] = leakage_check(messages)
    probe["answer"] = _answer(handler, last["content"], results, category, chat_history, lang)
    probe["query"] = last["content"]
    probe["lang"] = lang


def evaluate(probes: list[dict[str, Any]]) -> dict[str, Any]:
    """Layer 1 metrics, aggregated. Cheap: no network, offline over run()'s output.

    A probe whose run() call raised is excluded from every aggregate below
    AND tracked separately in ``errored`` — never silently dropped from the
    denominator, same discipline eval_retrieval.py already uses.
    """
    errored = [p for p in probes if "error" in p]
    ok = [p for p in probes if "error" not in p and "answer" in p]

    coverages: list[float] = []
    by_lang_coverage: dict[str, list[float]] = {}
    hallucinated_num = 0
    hallucinated_den = 0
    refusal_checks: list[bool] = []
    legacy_interventions: list[bool] = []
    leakage_results: list[bool] = []  # True = clean (no leak)

    for probe in ok:
        answer = probe["answer"]
        coverage = marker_coverage(answer["normalized"], answer["sources"])
        if coverage is not None:
            coverages.append(coverage)
            by_lang_coverage.setdefault(probe.get("lang", "en"), []).append(coverage)

        diagnostics = answer["diagnostics"]
        hallucinated_den += diagnostics.total_markers
        hallucinated_num += len(diagnostics.invalid)

        if probe.get("expected_refusal"):
            refusal_checks.append(refusal_is_clean(answer["normalized"], answer["sources"]))

        legacy_interventions.append(
            legacy_intervention_occurred(answer["raw"], answer["normalized"])
        )

        if "leakage" in probe:
            leakage_results.append(not probe["leakage"].leaked)

    def summarize(values: list[float]) -> MetricSummary:
        if not values:
            return MetricSummary(value=None, n=0)
        return MetricSummary(value=sum(values) / len(values), n=len(values))

    metrics = {
        "marker_coverage": summarize(coverages),
        "hallucinated_marker_rate": MetricSummary(
            value=(hallucinated_num / hallucinated_den) if hallucinated_den else None,
            n=hallucinated_den,
        ),
        "refusal_is_clean": summarize([1.0 if r else 0.0 for r in refusal_checks]),
        "leakage_check": summarize([1.0 if r else 0.0 for r in leakage_results]),
        "legacy_intervention_rate": summarize([1.0 if x else 0.0 for x in legacy_interventions]),
    }

    en_coverage = summarize(by_lang_coverage.get("en", []))
    ar_coverage = summarize(by_lang_coverage.get("ar", []))
    parity_gap = (
        language_parity_gap(en_coverage, ar_coverage)
        if en_coverage.value is not None and ar_coverage.value is not None
        else None
    )

    return {
        "metrics": metrics,
        "marker_coverage_parity_gap_en_minus_ar": parity_gap,
        "errored": errored,
        "n_ok": len(ok),
        "n_total": len(probes),
    }


def print_summary(model_id: str, result: dict[str, Any]) -> None:
    print(f"\n  {model_id}  ({result['n_ok']}/{result['n_total']} probes ok)")
    print(f"  {'metric':<28} {'value':>10}  n")
    for name, summary in result["metrics"].items():
        value = f"{summary.value:.1%}" if summary.value is not None else "n/a"
        print(f"  {name:<28} {value:>10}  {summary.n}")
    if result["marker_coverage_parity_gap_en_minus_ar"] is not None:
        print(
            f"  {'marker_coverage EN-AR gap':<28} "
            f"{result['marker_coverage_parity_gap_en_minus_ar']:>10.1%}"
        )
    if result["errored"]:
        print(f"  ** {len(result['errored'])} probe(s) errored — see the run log above **")


def compare(baseline_result, challenger_result, *, baseline_id: str, challenger_id: str):
    """The gate. Refuses to certify on an errored run, same as eval_retrieval.py."""
    print("\n" + "=" * 72)
    print(f"GATE: {challenger_id}  vs baseline {baseline_id}")

    if baseline_result["errored"] or challenger_result["errored"]:
        side = "baseline" if baseline_result["errored"] else "challenger"
        count = len(baseline_result["errored"] or challenger_result["errored"])
        print(
            f"  RECOMMENDATION — none. {count} {side} probe(s) errored during the run; "
            f"this comparison is inconclusive. Fix the failures and re-run."
        )
        return None

    report = compare_to_baseline(
        baseline_result["metrics"],
        challenger_result["metrics"],
        challenger_id=challenger_id,
        baseline_id=baseline_id,
    )

    if report.baseline_fails_floor:
        print("  ** BASELINE ITSELF EXCEEDS THE HALLUCINATED-MARKER FLOOR **")
        print("  Every verdict below is reported for visibility only — a broken")
        print("  reference cannot certify anything it's compared against.")

    for verdict in report.verdicts:
        status = "PASS" if verdict.passed else ("FAIL" if verdict.passed is False else "n/a ")
        baseline_str = (
            f"{verdict.baseline:.1%}"
            if isinstance(verdict.baseline, float)
            else str(verdict.baseline)
        )
        challenger_str = (
            f"{verdict.challenger:.1%}"
            if isinstance(verdict.challenger, float)
            else str(verdict.challenger)
        )
        print(
            f"  [{status}] {verdict.metric:<26} baseline={baseline_str:<8} "
            f"challenger={challenger_str:<8}  {verdict.reason}"
        )

    print("\n  RESULT:", "PASS — clears the gate" if report.passed else "DOES NOT CLEAR THE GATE")
    print("  Layer 1 only — this is a citation-FORMAT verdict, not a grounding one.")
    print("  See docs/citation-eval-judge-protocol.md before treating this as")
    print("  sufficient evidence to unblock a provider switch on its own.")
    return report


def write_artifact(path: str, model_id: str, probes: list[dict[str, Any]]) -> None:
    """Append one JSONL record per probe — the raw trace a later investigation needs.

    Without this, a pass/fail number from today cannot be explained or
    reproduced against corpus or prompt drift six months from now — a gap an
    adversarial review of this harness's design explicitly flagged.
    """
    with open(path, "a", encoding="utf-8") as handle:
        for probe in probes:
            record: dict[str, Any] = {
                "timestamp": time.time(),
                "model": model_id,
                "group": probe.get("group"),
                "query": probe.get("query"),
                "lang": probe.get("lang"),
                "error": probe.get("error"),
            }
            if "answer" in probe:
                answer = probe["answer"]
                record["answer"] = answer["normalized"]
                record["cited_indices"] = answer["diagnostics"].cited
                record["invalid_markers"] = answer["diagnostics"].invalid
                record["note"] = probe.get("note")
            if "leakage" in probe:
                record["leaked"] = probe["leakage"].leaked
                record["leaked_markers"] = probe["leakage"].markers_found
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--limit", type=int, help="cap the number of probes (a cheap smoke run)")
    parser.add_argument("--group", help="restrict to one probe group")
    parser.add_argument("--no-ar", action="store_true", help="skip Arabic probes")
    parser.add_argument(
        "--judge",
        action="store_true",
        help="restrict to the judge:true subset — see docs/citation-eval-judge-protocol.md",
    )
    parser.add_argument(
        "--baseline", help="model id for the baseline (default: the live deployed default)"
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="challenger model id to compare against the baseline (repeatable)",
    )
    parser.add_argument("--out", help="append a JSONL run artifact to this path")
    args = parser.parse_args()

    probes_template = load_probes(args)
    candidates = load_candidates()
    print(f"Loaded {len(probes_template)} probe(s) from {os.path.relpath(PROBES)}\n")

    if args.judge and not args.models:
        print("--judge produces a review packet; it does not itself certify anything.")
        print("Read docs/citation-eval-judge-protocol.md before adjudicating the output.\n")

    engine = ImprovedSearchEngine()
    if not engine.is_initialized():
        engine.initialize()

    baseline_id = args.baseline or deployed_defaults()["model"]
    print(f"BASELINE: {baseline_id}")
    baseline_handler = build_handler(baseline_id, candidates)
    baseline_probes = [dict(p) for p in probes_template]
    run(baseline_handler, engine, baseline_probes)
    baseline_result = evaluate(baseline_probes)
    print_summary(baseline_id, baseline_result)
    if args.out:
        write_artifact(args.out, baseline_id, baseline_probes)

    for model_id in args.models or []:
        print(f"\nCHALLENGER: {model_id}")
        handler = build_handler(model_id, candidates)
        challenger_probes = [dict(p) for p in probes_template]
        run(handler, engine, challenger_probes)
        challenger_result = evaluate(challenger_probes)
        print_summary(model_id, challenger_result)
        if args.out:
            write_artifact(args.out, model_id, challenger_probes)
        compare(baseline_result, challenger_result, baseline_id=baseline_id, challenger_id=model_id)


if __name__ == "__main__":
    main()
