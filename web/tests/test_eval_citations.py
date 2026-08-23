"""Integration tests for scripts/eval_citations.py's own wiring.

eval_retrieval.py has no dedicated test file, and both adversarial reviews of
this harness's design plan flagged that as a real gap to not repeat: the
pure metrics in citation_eval_metrics.py are unit-tested against canned
fixtures, but nothing proved load_probes/run/evaluate/compare are actually
wired to each other correctly, or that a probe whose generation call raised
is tracked rather than silently dropped. These tests close that gap with a
fake handler/engine — no network, no API key, no cost.

Loaded via importlib rather than `import scripts.eval_citations`: scripts/
has no __init__.py, and the script itself does a few module-level side
effects (stdout/stderr reconfigure, sys.path insert, load_dotenv()) that are
harmless but easiest to reason about via one explicit, deliberate import.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_PATH = os.path.join(REPO_ROOT, "scripts", "eval_citations.py")

_spec = importlib.util.spec_from_file_location("eval_citations_under_test", SCRIPT_PATH)
ec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ec)


class FakeEngine:
    """engine.search(query, category) -> canned SearchResult list."""

    def __init__(self, results):
        self._results = results

    def search(self, query, category):
        return self._results


class FakeHandler:
    """A minimal stand-in for OpenAIHandler — no network, no API key.

    ``answer_tokens`` is what stream_response yields, joined; ``messages``
    is what _build_messages returns verbatim, letting a turn-probe test set
    up a specific leakage scenario without going through real prompt
    assembly.
    """

    def __init__(self, answer_tokens=("An answer [1].",), messages=None, raises=None):
        self.max_context_results = 8
        self._answer_tokens = answer_tokens
        self._messages = messages
        self._raises = raises

    def stream_response(self, query, search_results, category, chat_history, lang):
        if self._raises:
            raise self._raises
        yield from self._answer_tokens

    def _build_messages(self, query, search_results, category, chat_history=None, lang="en"):
        if self._messages is not None:
            return self._messages
        return [
            {"role": "system", "content": "sys"},
            *(chat_history or []),
            {"role": "user", "content": query},
        ]


def make_result(text="passage text", document="A.pdf", page=1):
    from web.services.result_combiner import SearchResult

    return SearchResult(text=text, score=0.7, document=document, category="regulatory", page=page)


def args(**overrides):
    defaults = {"limit": None, "group": None, "no_ar": False, "judge": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ── load_probes ──────────────────────────────────────────────────────────


def test_load_probes_loads_every_group_by_default():
    probes = ec.load_probes(args())
    groups = {p["group"] for p in probes}
    assert {"in_domain", "refusal", "cross_turn", "legacy_format"} <= groups


def test_load_probes_restricts_to_one_group():
    probes = ec.load_probes(args(group="refusal"))
    assert probes
    assert all(p["group"] == "refusal" for p in probes)


def test_load_probes_no_ar_skips_arabic_flat_probes():
    probes = ec.load_probes(args(group="in_domain", no_ar=True))
    assert probes
    assert all(p.get("lang") != "ar" for p in probes)


def test_load_probes_no_ar_skips_arabic_turn_probes_by_final_turn_language():
    probes = ec.load_probes(args(no_ar=True))
    for probe in probes:
        if probe["group"] in ec.TURN_GROUPS:
            assert probe["turns"][-1].get("lang") != "ar"


def test_load_probes_judge_keeps_only_tagged_probes():
    probes = ec.load_probes(args(judge=True))
    assert probes
    assert all(p.get("judge") for p in probes)


def test_load_probes_limit_caps_the_count():
    probes = ec.load_probes(args(limit=2))
    assert len(probes) == 2


# ── run() — flat probes ─────────────────────────────────────────────────


def test_run_flat_probe_records_normalized_answer_and_diagnostics():
    engine = FakeEngine([make_result()])
    handler = FakeHandler(answer_tokens=("Real ", "[1] ", "and ", "invented ", "[9]."))
    probes = [{"group": "in_domain", "query": "q", "lang": "en", "category": "regulatory"}]

    ec.run(handler, engine, probes)

    (probe,) = probes
    assert "error" not in probe
    answer = probe["answer"]
    assert answer["diagnostics"].cited == [1]
    assert answer["diagnostics"].invalid == [9]


def test_run_flat_probe_uses_synthetic_context_instead_of_real_search():
    engine = FakeEngine([make_result(document="SHOULD_NOT_BE_USED.pdf")])
    handler = FakeHandler(answer_tokens=("Cites [1].",))
    probes = [
        {
            "group": "adversarial",
            "query": "q",
            "lang": "en",
            "category": "regulatory",
            "synthetic_context": [
                {"text": "injected passage", "document": "Injected.pdf", "page": 1}
            ],
        }
    ]

    ec.run(handler, engine, probes)

    (probe,) = probes
    assert probe["answer"]["sources"][0]["document"] == "Injected.pdf"


def test_run_records_an_error_without_aborting_the_batch():
    engine = FakeEngine([make_result()])
    ok_handler = FakeHandler(answer_tokens=("Fine [1].",))
    failing_handler = FakeHandler(raises=RuntimeError("boom"))

    probes = [{"group": "in_domain", "query": "q1", "lang": "en", "category": "regulatory"}]
    ec.run(failing_handler, engine, probes)
    assert probes[0]["error"] == "boom"
    assert "answer" not in probes[0]

    probes2 = [{"group": "in_domain", "query": "q2", "lang": "en", "category": "regulatory"}]
    ec.run(ok_handler, engine, probes2)
    assert "answer" in probes2[0]


# ── run() — turn probes / leakage ───────────────────────────────────────


def test_turn_probe_detects_a_leaked_marker():
    engine = FakeEngine([make_result()])
    leaking_messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "Stale claim [1]."},  # should have been stripped
        {"role": "user", "content": "follow up"},
    ]
    handler = FakeHandler(answer_tokens=("New answer [1].",), messages=leaking_messages)
    probe = {
        "group": "cross_turn",
        "pair_id": "p1",
        "turns": [
            {"role": "user", "content": "first", "lang": "en", "category": "regulatory"},
            {"role": "assistant", "content": "Old claim [1]."},
            {"role": "user", "content": "second", "lang": "en", "category": "regulatory"},
        ],
    }

    ec.run(handler, engine, [probe])

    assert probe["leakage"].leaked is True
    assert probe["query"] == "second"
    assert probe["lang"] == "en"


def test_turn_probe_reports_clean_when_stripping_worked():
    engine = FakeEngine([make_result()])
    clean_messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "Old claim."},  # marker already stripped
        {"role": "user", "content": "follow up"},
    ]
    handler = FakeHandler(answer_tokens=("New answer [1].",), messages=clean_messages)
    probe = {
        "group": "legacy_format",
        "pair_id": "p2",
        "turns": [
            {"role": "user", "content": "first", "lang": "en", "category": "regulatory"},
            {"role": "assistant", "content": "[Source: A.pdf, Page: 1]"},
            {"role": "user", "content": "second", "lang": "en", "category": "regulatory"},
        ],
    }

    ec.run(handler, engine, [probe])

    assert probe["leakage"].leaked is False


# ── evaluate() ───────────────────────────────────────────────────────────


def test_evaluate_aggregates_across_ok_probes_and_tracks_errors():
    engine = FakeEngine([make_result()])
    ok_handler = FakeHandler(answer_tokens=("Cites [1].",))
    failing_handler = FakeHandler(raises=RuntimeError("boom"))

    probes = [
        {"group": "in_domain", "query": "q1", "lang": "en", "category": "regulatory"},
        {"group": "in_domain", "query": "q2", "lang": "en", "category": "regulatory"},
    ]
    ec.run(ok_handler, engine, [probes[0]])
    ec.run(failing_handler, engine, [probes[1]])

    result = ec.evaluate(probes)

    assert result["n_ok"] == 1
    assert result["n_total"] == 2
    assert len(result["errored"]) == 1
    assert result["metrics"]["marker_coverage"].n == 1


def test_evaluate_scores_refusal_only_against_expected_refusal_probes():
    engine = FakeEngine([make_result()])
    handler = FakeHandler(answer_tokens=("I cannot answer based on the given information.",))
    probes = [
        {
            "group": "refusal",
            "query": "who is claude?",
            "lang": "en",
            "category": "all",
            "expected_refusal": True,
        }
    ]
    ec.run(handler, engine, probes)

    result = ec.evaluate(probes)

    assert result["metrics"]["refusal_is_clean"].value == 1.0
    assert result["metrics"]["refusal_is_clean"].n == 1


def test_evaluate_computes_language_parity_gap_when_both_languages_present():
    engine = FakeEngine([make_result()])
    handler = FakeHandler(answer_tokens=("Full coverage [1].",))
    probes = [
        {"group": "in_domain", "query": "en q", "lang": "en", "category": "regulatory"},
        {"group": "in_domain", "query": "ar q", "lang": "ar", "category": "regulatory"},
    ]
    ec.run(handler, engine, probes)

    result = ec.evaluate(probes)

    # Identical handler behavior on both -> zero gap, but the field must exist.
    assert result["marker_coverage_parity_gap_en_minus_ar"] == pytest.approx(0.0)


# ── compare() ────────────────────────────────────────────────────────────


def test_compare_refuses_to_certify_when_either_side_errored():
    baseline = {
        "errored": [{"error": "x"}],
        "metrics": {},
        "n_ok": 0,
        "n_total": 1,
        "marker_coverage_parity_gap_en_minus_ar": None,
    }
    challenger = {
        "errored": [],
        "metrics": {},
        "n_ok": 1,
        "n_total": 1,
        "marker_coverage_parity_gap_en_minus_ar": None,
    }
    report = ec.compare(baseline, challenger, baseline_id="b", challenger_id="c")
    assert report is None


def test_compare_returns_a_gate_report_on_a_clean_run():
    from web.services.citation_eval_metrics import MetricSummary

    clean = {
        "errored": [],
        "n_ok": 40,
        "n_total": 40,
        "marker_coverage_parity_gap_en_minus_ar": None,
        "metrics": {
            "hallucinated_marker_rate": MetricSummary(value=0.0, n=40),
            "marker_coverage": MetricSummary(value=0.9, n=40),
        },
    }
    report = ec.compare(clean, clean, baseline_id="b", challenger_id="c")
    assert report is not None
    assert report.passed is True


# ── write_artifact() ─────────────────────────────────────────────────────


def test_write_artifact_writes_one_json_line_per_probe(tmp_path):
    engine = FakeEngine([make_result()])
    handler = FakeHandler(answer_tokens=("Cites [1].",))
    probes = [{"group": "in_domain", "query": "q", "lang": "en", "category": "regulatory"}]
    ec.run(handler, engine, probes)

    out = tmp_path / "artifact.jsonl"
    ec.write_artifact(str(out), "gpt-4o-mini", probes)

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["model"] == "gpt-4o-mini"
    assert record["cited_indices"] == [1]


def test_write_artifact_appends_across_multiple_calls(tmp_path):
    engine = FakeEngine([make_result()])
    handler = FakeHandler(answer_tokens=("Cites [1].",))
    probes = [{"group": "in_domain", "query": "q", "lang": "en", "category": "regulatory"}]
    ec.run(handler, engine, probes)

    out = tmp_path / "artifact.jsonl"
    ec.write_artifact(str(out), "model-a", probes)
    ec.write_artifact(str(out), "model-b", probes)

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
