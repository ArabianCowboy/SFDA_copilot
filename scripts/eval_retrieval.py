"""Measure a relevance floor against a labelled probe set, before enabling it.

``search_engine.min_score`` ships at 0.00 — disabled — because a floor trades
one failure mode for another. Too low and an out-of-domain question still comes
back with eight passages the answer never used. Too high and a question the
corpus *can* answer becomes a confident refusal, which for a regulatory
assistant is much worse: the reader cannot tell "we have no guidance on this"
from "the retriever scored it 0.29".

So the threshold moves on evidence, not on eyeballing a score dump. This runs
the REAL pipeline over web/tests/data/retrieval_eval.yaml and reports, for each
candidate threshold:

  false refusals      in-domain questions reduced to zero passages. Want 0.
  OOD accepted        out-of-domain questions still returning passages. Want 0.
  document recall     in-domain questions whose expected document survived.
                      Only meaningful once the labels in the YAML are filled in.

If no threshold satisfies both, the report says so instead of recommending a
midpoint. That is a real finding: it means the score cannot separate these
populations, and the citation contract — not the floor — is what has to carry
the work.

Costs nothing: search and embedding only, never a completions call. Arabic
probes DO hit the translation endpoint; pass --no-ar to skip them.

Usage:
    python scripts/eval_retrieval.py
    python scripts/eval_retrieval.py --no-ar
    python scripts/eval_retrieval.py --category regulatory
"""

import argparse
import os
import sys

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
from dotenv import load_dotenv

load_dotenv()

from web.services.result_combiner import apply_relevance_floor
from web.services.search_engine import ImprovedSearchEngine

PROBES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "web", "tests", "data", "retrieval_eval.yaml",
)

# Every group except in_domain asserts "nothing here is relevant", so a floor
# is doing its job when it empties them.
SHOULD_BE_EMPTY = ("out_of_domain", "conversational", "near_miss")

THRESHOLDS = [round(0.05 + 0.025 * i, 3) for i in range(19)]   # 0.050 … 0.500


def load_probes(args):
    with open(PROBES, encoding="utf-8") as handle:
        groups = yaml.safe_load(handle)

    probes = []
    for group, entries in groups.items():
        for entry in entries or []:
            if args.no_ar and entry.get("lang") == "ar":
                continue
            if args.category and entry.get("category") not in (args.category, "all"):
                continue
            probes.append({**entry, "group": group})
    return probes


def run(engine, probes):
    """Retrieve once per probe; every threshold is then evaluated offline."""
    for probe in probes:
        try:
            results = engine.search(probe["query"], probe.get("category", "all"))
        except Exception as exc:                      # noqa: BLE001 - report, don't abort
            print(f"  !! {probe['query'][:50]!r} failed: {exc}")
            probe["results"] = []
            probe["error"] = str(exc)
            continue
        probe["results"] = results
        probe["top"] = results[0].score if results else 0.0
        print(
            f"  {probe['group']:<16} {probe['lang']}  top={probe['top']:.4f}  "
            f"n={len(results):<2} {probe['query'][:52]}"
        )
    return probes


def separation(probes):
    """The decisive comparison: can any single number split these apart?"""
    in_domain = [p for p in probes if p["group"] == "in_domain" and "error" not in p]
    others = [p for p in probes if p["group"] in SHOULD_BE_EMPTY and "error" not in p]
    if not in_domain or not others:
        return None

    weakest_real = min(p["top"] for p in in_domain)
    strongest_noise = max(p["top"] for p in others)

    print("\n" + "=" * 72)
    print("SEPARATION")
    print(f"  weakest in-domain top score   {weakest_real:.4f}")
    print(f"  strongest should-be-empty top {strongest_noise:.4f}")

    if strongest_noise >= weakest_real:
        print("\n  ** NO ABSOLUTE THRESHOLD SEPARATES THESE SETS **")
        print("  Every value admits noise or refuses a real question. Overlapping probes:")
        for p in sorted(others, key=lambda p: -p["top"]):
            if p["top"] >= weakest_real:
                print(f"    {p['top']:.4f}  [{p['group']}] {p['query'][:56]}")
        print("\n  Leave min_score at 0.00. The citation contract is what suppresses")
        print("  sources on an ungrounded answer; the floor cannot help here.")
    else:
        print(f"\n  A threshold exists in ({strongest_noise:.4f}, {weakest_real:.4f}].")
    return weakest_real, strongest_noise


def sweep(probes):
    in_domain = [p for p in probes if p["group"] == "in_domain" and "error" not in p]
    others = [p for p in probes if p["group"] in SHOULD_BE_EMPTY and "error" not in p]

    # A probe whose retrieval raised was silently dropped from both lists
    # above, so a run where half the probes failed still looked complete and
    # could certify a threshold on whatever happened to succeed. Failures are
    # exactly when the numbers mean least, so they void the run.
    errored = [p for p in probes if "error" in p]

    print("\n" + "=" * 72)
    print("THRESHOLD SWEEP")
    if errored:
        print(f"  ** {len(errored)} probe(s) failed to retrieve — this run is "
              f"inconclusive **")
    print(f"  {'min_score':>9}  {'false refusals':>14}  {'OOD accepted':>13}  {'doc recall':>10}")

    # Recall is only meaningful over the WHOLE in-domain set. Measuring it on
    # the labelled subset would let one filled-in probe certify a threshold
    # while the other seven were never checked — the sweep would report
    # "1/1 recall" and mark a value safe on the strength of a single question.
    labelled = [p for p in in_domain if p.get("expected_documents")]
    fully_labelled = (
        bool(in_domain) and not errored and len(labelled) == len(in_domain)
    )
    safe = []
    # Thresholds that pass the two label-free checks. Reportable as context
    # even without labels, but never as a recommendation.
    separating = []

    for threshold in THRESHOLDS:
        refusals = ood = recalled = 0
        for p in in_domain:
            if not apply_relevance_floor(p["results"], threshold):
                refusals += 1
        for p in others:
            if apply_relevance_floor(p["results"], threshold):
                ood += 1
        for p in labelled:
            kept = apply_relevance_floor(p["results"], threshold)
            names = " ".join(r.document.lower() for r in kept)
            if any(e.lower() in names for e in p["expected_documents"]):
                recalled += 1

        recall = f"{recalled}/{len(in_domain)}" if labelled else "unlabelled"
        flag = ""
        if refusals == 0 and ood == 0:
            separating.append(threshold)
            if fully_labelled and recalled == len(in_domain):
                safe.append(threshold)
                flag = "  <-- safe"
        print(
            f"  {threshold:>9.3f}  {refusals:>4}/{len(in_domain):<9}  "
            f"{ood:>4}/{len(others):<8}  {recall:>10}{flag}"
        )

    print("\n" + "=" * 72)
    if not fully_labelled:
        # Without labels on EVERY in-domain probe there is no evidence that a
        # "safe" threshold keeps the RIGHT passages — only that it keeps some,
        # for the questions someone happened to annotate. A threshold adopted
        # on that basis could refuse nothing while quietly dropping the one
        # document that answers an unannotated question.
        if errored:
            print("RECOMMENDATION — none. Probes failed to retrieve.\n")
            print(f"  {len(errored)} probe(s) raised during retrieval, so the columns")
            print("  above describe only the queries that happened to work. Fix the")
            print("  failures and re-run before reading anything into them:\n")
            for probe in errored[:5]:
                print(f"    {probe['query'][:56]}  —  {probe['error'][:60]}")
            if len(errored) > 5:
                print(f"    … and {len(errored) - 5} more")
            print("\n  Keep min_score at 0.00.")
            return

        missing = len(in_domain) - len(labelled)
        print("RECOMMENDATION — none. The probe set is not fully labelled.\n")
        print(f"  {missing} of {len(in_domain)} in_domain probes in")
        print("  web/tests/data/retrieval_eval.yaml have no expected_documents, so")
        print("  document recall could not be measured across the set and no")
        print("  threshold can be certified here. The false-refusal and")
        print("  out-of-domain columns above are still valid — they need no")
        print("  labels — but they cannot tell you whether a surviving passage")
        print("  is the right one.\n")
        print("  Label every in_domain probe, then re-run. Keep min_score at 0.00.")
        if separating:
            print(f"\n  (For reference only, NOT a recommendation: {len(separating)} value(s) "
                  f"refused no in-domain probe and emptied every out-of-domain one, "
                  f"the largest being {max(separating):.3f}.)")
        return

    if safe:
        # One step below the largest safe value: the probe set is small, and
        # the cost of being slightly too low is far cheaper than a false refusal.
        recommended = safe[max(0, len(safe) - 2)] if len(safe) > 1 else safe[0]
        print("RECOMMENDATION — paste into web/config.yaml under search_engine:\n")
        print(f"  min_score: {recommended:.3f}")
        print(f"  min_score_ratio: 0.00\n")
        print(f"  (largest safe value was {max(safe):.3f}; backed off one step for margin)")
    else:
        print("RECOMMENDATION\n")
        print("  Keep min_score at 0.00. No swept value refuses zero real questions")
        print("  while emptying every out-of-domain one.")

    if not labelled:
        print("\n  NOTE: no in_domain probe has expected_documents filled in, so")
        print("  document recall was not measured. False-refusal and OOD-acceptance")
        print("  numbers above are still valid — they need no labels.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-ar", action="store_true", help="skip Arabic probes (no translation calls)")
    parser.add_argument("--category", help="restrict to one category")
    args = parser.parse_args()

    probes = load_probes(args)
    print(f"Loaded {len(probes)} probes from {os.path.relpath(PROBES)}\n")

    engine = ImprovedSearchEngine()
    if not engine.is_initialized():
        engine.initialize()

    if engine._translation_client is None:                     # noqa: SLF001
        print("!! No translation client (OPENAI_API_KEY unset).")
        print("!! Arabic queries embed untranslated and score low across the board,")
        print("!! so any threshold derived from this run would nuke Arabic retrieval.\n")

    print("RETRIEVAL")
    run(engine, probes)
    separation(probes)
    sweep(probes)


if __name__ == "__main__":
    main()
