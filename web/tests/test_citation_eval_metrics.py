"""Tests for the Layer-1 citation-format-baseline metrics.

Every function under test is pure — canned strings and dataclasses in,
a value out. No network, no torch, no model calls: that split is the whole
point of ``web/services/citation_eval_metrics.py``'s design (see its module
docstring), and these tests are what makes the split actually pay for itself
in CI, since ``scripts/eval_citations.py`` itself is not run there.
"""

from __future__ import annotations

import pytest

from web.services.citation_eval_metrics import (
    GateReport,
    HALLUCINATED_MARKER_RATE_FLOOR,
    MIN_SAMPLE_FOR_RELATIVE_COMPARISON,
    LeakageResult,
    MetricSummary,
    UsageEstimate,
    compare_to_baseline,
    estimate_cost,
    hallucinated_marker_rate,
    language_parity_gap,
    leakage_check,
    legacy_intervention_occurred,
    marker_coverage,
    refusal_is_clean,
    split_sentences,
)
from web.services.citations import CitationDiagnostics, build_source_payload
from web.services.result_combiner import SearchResult


def source(**overrides):
    defaults = dict(text="x", score=0.7, document="A.pdf", category="regulatory", page=1)
    defaults.update(overrides)
    return SearchResult(**defaults)


# ── split_sentences ─────────────────────────────────────────────────────────

def test_splits_on_terminal_punctuation():
    assert split_sentences("First. Second! Third?") == ["First.", "Second!", "Third?"]


def test_splits_on_arabic_question_mark():
    assert split_sentences("ما هي المتطلبات؟ التالي.") == ["ما هي المتطلبات؟", "التالي."]


def test_empty_text_has_no_sentences():
    assert split_sentences("") == []
    assert split_sentences(None) == []


# ── marker_coverage ──────────────────────────────────────────────────────────

def test_coverage_counts_sentences_with_a_marker():
    sources = build_source_payload([source(), source()])
    assert marker_coverage("Claim one [1]. Claim two [2]. Claim three.", sources) == 2 / 3


def test_coverage_is_full_when_every_sentence_cites():
    sources = build_source_payload([source()])
    assert marker_coverage("Claim [1]. Another [1].", sources) == 1.0


def test_coverage_is_none_for_an_empty_answer():
    assert marker_coverage("", build_source_payload([source()])) is None


# ── hallucinated_marker_rate ─────────────────────────────────────────────────

def test_hallucination_rate_from_diagnostics():
    diagnostics = CitationDiagnostics(cited=[1], invalid=[9], total_markers=2)
    assert hallucinated_marker_rate(diagnostics) == 0.5


def test_hallucination_rate_is_none_with_zero_markers():
    """Undefined, not clean — see the function's own docstring."""
    diagnostics = CitationDiagnostics(cited=[], invalid=[], total_markers=0)
    assert hallucinated_marker_rate(diagnostics) is None


def test_hallucination_rate_is_zero_when_every_marker_is_valid():
    diagnostics = CitationDiagnostics(cited=[1, 2], invalid=[], total_markers=2)
    assert hallucinated_marker_rate(diagnostics) == 0.0


# ── refusal_is_clean ─────────────────────────────────────────────────────────

def test_refusal_with_no_markers_is_clean():
    sources = build_source_payload([source()])
    assert refusal_is_clean("I cannot answer based on the given information.", sources) is True


def test_refusal_with_a_marker_is_not_clean():
    sources = build_source_payload([source()])
    assert refusal_is_clean("I cannot answer, but see [1] anyway.", sources) is False


# ── legacy_intervention_occurred ─────────────────────────────────────────────

def test_intervention_detected_when_text_changed():
    assert legacy_intervention_occurred("Claim [Source: A.pdf].", "Claim [1].") is True


def test_no_intervention_when_text_is_unchanged():
    assert legacy_intervention_occurred("Claim [1].", "Claim [1].") is False


# ── leakage_check ─────────────────────────────────────────────────────────

def test_leakage_detected_in_replayed_assistant_turn():
    messages = [
        {"role": "system", "content": "..."},
        {"role": "assistant", "content": "Submit within 15 days [1]."},
        {"role": "user", "content": "..."},
    ]
    result = leakage_check(messages)
    assert result == LeakageResult(leaked=True, markers_found=["[1]"])


def test_no_leakage_when_markers_were_stripped():
    messages = [
        {"role": "assistant", "content": "Submit within 15 days."},
        {"role": "user", "content": "..."},
    ]
    result = leakage_check(messages)
    assert result == LeakageResult(leaked=False, markers_found=[])


def test_leakage_check_ignores_non_assistant_roles():
    """A marker in the user's own message (e.g. "tell me more about [1]") is
    not a leak of THIS check's concern — _history_without_stale_markers
    strips both roles, but this metric is specifically about whether the
    model's own prior claim resurfaces with a stale number."""
    messages = [{"role": "user", "content": "tell me more about [1]"}]
    assert leakage_check(messages) == LeakageResult(leaked=False, markers_found=[])


# ── estimate_cost ─────────────────────────────────────────────────────────

PRICING = {"gpt-4o-mini": (0.15, 0.60)}  # $/1M tokens, prompt/completion


def test_cost_from_real_usage_is_exact():
    estimate = estimate_cost(
        {"prompt_tokens": 1000, "completion_tokens": 500}, PRICING, "gpt-4o-mini"
    )
    assert estimate.exact is True
    assert estimate.cost_usd == (1000 / 1_000_000) * 0.15 + (500 / 1_000_000) * 0.60


def test_cost_falls_back_to_tokenizer_estimate_when_usage_is_missing():
    estimate = estimate_cost(
        None, PRICING, "gpt-4o-mini", fallback_prompt_tokens=1000, fallback_completion_tokens=500
    )
    assert estimate.exact is False
    assert estimate.cost_usd is not None


def test_cost_is_none_for_an_unpriced_model_not_zero():
    """Silently pricing an unknown model at $0 would make a genuinely free
    model and a not-yet-catalogued one indistinguishable in a report."""
    estimate = estimate_cost({"prompt_tokens": 100, "completion_tokens": 50}, PRICING, "unknown-model")
    assert estimate.cost_usd is None
    assert estimate == UsageEstimate(prompt_tokens=100, completion_tokens=50, cost_usd=None, exact=True)


# ── compare_to_baseline — the gate ──────────────────────────────────────────

def summary(value, n=MIN_SAMPLE_FOR_RELATIVE_COMPARISON):
    return MetricSummary(value=value, n=n)


def test_baseline_that_already_fails_the_floor_blocks_the_whole_comparison():
    """A bad baseline must never legitimize an equally bad challenger."""
    baseline = {"hallucinated_marker_rate": summary(HALLUCINATED_MARKER_RATE_FLOOR + 0.10)}
    challenger = {"hallucinated_marker_rate": summary(0.01)}
    report = compare_to_baseline(baseline, challenger, challenger_id="c", baseline_id="b")
    assert report.baseline_fails_floor is True
    assert report.passed is False


def test_challenger_over_the_absolute_floor_fails_regardless_of_baseline():
    baseline = {"hallucinated_marker_rate": summary(0.01)}
    challenger = {"hallucinated_marker_rate": summary(HALLUCINATED_MARKER_RATE_FLOOR + 0.01)}
    report = compare_to_baseline(baseline, challenger, challenger_id="c", baseline_id="b")
    verdict = report.verdicts[0]
    assert verdict.passed is False
    assert "floor" in verdict.reason


def test_small_sample_below_the_floor_still_passes_without_a_relative_claim():
    baseline = {"hallucinated_marker_rate": summary(0.0, n=5)}
    challenger = {"hallucinated_marker_rate": summary(0.01, n=5)}
    report = compare_to_baseline(baseline, challenger, challenger_id="c", baseline_id="b")
    assert report.verdicts[0].passed is True


def test_small_sample_relative_metric_is_inconclusive_not_passed():
    """A 10-probe run cannot support a percentage-point regression claim."""
    baseline = {"marker_coverage": summary(0.9, n=10)}
    challenger = {"marker_coverage": summary(0.5, n=10)}
    report = compare_to_baseline(baseline, challenger, challenger_id="c", baseline_id="b")
    verdict = report.verdicts[0]
    assert verdict.passed is None
    assert report.passed is False  # inconclusive is never a pass


def test_relative_regression_beyond_tolerance_fails_with_enough_samples():
    baseline = {"marker_coverage": summary(0.90)}
    challenger = {"marker_coverage": summary(0.80)}  # 10pp drop > 5pp tolerance
    report = compare_to_baseline(baseline, challenger, challenger_id="c", baseline_id="b")
    assert report.verdicts[0].passed is False


def test_relative_regression_within_tolerance_passes():
    baseline = {"marker_coverage": summary(0.90)}
    challenger = {"marker_coverage": summary(0.87)}  # 3pp drop < 5pp tolerance
    report = compare_to_baseline(baseline, challenger, challenger_id="c", baseline_id="b")
    assert report.verdicts[0].passed is True


def test_structural_metrics_require_exactly_100_percent():
    baseline = {"refusal_is_clean": summary(1.0)}
    challenger = {"refusal_is_clean": summary(0.99)}
    report = compare_to_baseline(baseline, challenger, challenger_id="c", baseline_id="b")
    assert report.verdicts[0].passed is False
    assert "100%" in report.verdicts[0].reason


def test_legacy_intervention_rate_is_reported_not_gated():
    baseline = {"legacy_intervention_rate": summary(0.0)}
    challenger = {"legacy_intervention_rate": summary(0.3)}  # much worse, but not gated
    report = compare_to_baseline(baseline, challenger, challenger_id="c", baseline_id="b")
    assert report.verdicts[0].passed is None
    assert "not gated" in report.verdicts[0].reason


def test_a_metric_missing_from_one_side_is_inconclusive_not_skipped():
    baseline = {"marker_coverage": summary(0.9)}
    challenger: dict = {}
    report = compare_to_baseline(baseline, challenger, challenger_id="c", baseline_id="b")
    assert len(report.verdicts) == 1
    assert report.verdicts[0].passed is None


def test_undefined_value_on_either_side_is_inconclusive():
    baseline = {"marker_coverage": MetricSummary(value=None, n=0)}
    challenger = {"marker_coverage": summary(0.9)}
    report = compare_to_baseline(baseline, challenger, challenger_id="c", baseline_id="b")
    assert report.verdicts[0].passed is None


def test_gate_report_passes_only_when_every_verdict_passes():
    baseline = {
        "hallucinated_marker_rate": summary(0.0),
        "marker_coverage": summary(0.9),
    }
    challenger = {
        "hallucinated_marker_rate": summary(0.0),
        "marker_coverage": summary(0.89),
    }
    report = compare_to_baseline(baseline, challenger, challenger_id="c", baseline_id="b")
    assert isinstance(report, GateReport)
    assert report.passed is True


# ── language_parity_gap ─────────────────────────────────────────────────────

def test_parity_gap_is_positive_when_english_scores_higher():
    en = MetricSummary(value=0.9, n=50)
    ar = MetricSummary(value=0.7, n=50)
    assert language_parity_gap(en, ar) == pytest.approx(0.2)


def test_parity_gap_is_none_when_either_side_is_undefined():
    en = MetricSummary(value=None, n=0)
    ar = MetricSummary(value=0.7, n=50)
    assert language_parity_gap(en, ar) is None
