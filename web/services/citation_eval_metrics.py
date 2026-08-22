"""Pure metrics for the citation-fidelity harness (``scripts/eval_citations.py``).

**Layer 1 only.** Everything here measures whether the model *followed the
citation contract* — a marker exists, is valid, a refusal carries none,
history doesn't leak a marker across turns — never whether the cited passage
actually *supports* the claim. ``extract_cited_indices`` proves a marker was
emitted, not that source ``n`` backs the sentence it's attached to (see its
own docstring in ``web/services/citations.py``). Grounding is Layer 2
(``web/services/citation_fidelity.py``, NLI) and Layer 3 (a human judge).

Report these numbers as a **citation-format baseline**, never as "fidelity" —
a model can fabricate a claim and append a syntactically valid ``[1]``, and
every function below will count it as covered and non-hallucinated. That
distinction was the first thing an adversarial review of this harness's
design caught, and it is load-bearing on a product whose first principle is
that provenance is real, not merely present.

No network calls, no torch, no filesystem. Every function takes an
already-computed input (an answer string, a ``CitationDiagnostics``, a source
payload, provider usage) and returns a plain value, so this module is
entirely unit-testable against canned fixtures — see
``web/tests/test_citation_eval_metrics.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from web.services.citations import CitationDiagnostics, extract_cited_indices

# Best-effort EN/AR sentence split — the same posture citations.py's
# _UNCITABLE comment takes: a regex over markdown text, not a parser. Splits
# after EN terminal punctuation and the Arabic question mark (؟); does not
# try to special-case abbreviations or decimal points. Good enough for "is
# roughly this fraction of sentences carrying a marker", not for a claim
# precise below a few percentage points — compare_to_baseline's own minimum
# sample size accounts for exactly that imprecision.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?؟])\s+")

_MARKER = re.compile(r"\[[0-9]{1,2}\]")


def split_sentences(text: str) -> list[str]:
    """Best-effort EN/AR sentence split. See module docstring for caveats."""
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_BOUNDARY.split(text.strip()) if s.strip()]


def marker_coverage(answer: str, sources: list[dict[str, Any]]) -> Optional[float]:
    """Fraction of *answer*'s sentences carrying >=1 citation marker.

    Deliberately counts any ``[n]``-shaped marker, not only valid ones —
    coverage is "did the model attempt to cite this sentence", a different
    question from "was the attempt valid" (``hallucinated_marker_rate``
    below). Conflating the two would hide a model that cites everything with
    the wrong numbers behind a coverage score that looks perfect.

    Returns ``None`` — not ``0.0`` — when *answer* has no sentences at all.
    An empty or refusal answer has nothing to cover, which is a different
    case from "said something and cited none of it"; averaging the two
    together would understate coverage on exactly the turns where the metric
    doesn't apply.
    """
    sentences = split_sentences(answer)
    if not sentences:
        return None
    covered = sum(1 for sentence in sentences if _MARKER.search(sentence))
    return covered / len(sentences)


def hallucinated_marker_rate(diagnostics: CitationDiagnostics) -> Optional[float]:
    """Share of every emitted ``[n]`` marker that pointed outside the source set.

    Returns ``None`` when the answer emitted no markers at all. A
    hallucination *rate* is undefined at zero markers, not zero — reporting
    ``0.0`` would call an answer that never tried "clean", indistinguishable
    from one that tried on every sentence and got every marker right.
    """
    if diagnostics.total_markers == 0:
        return None
    return len(diagnostics.invalid) / diagnostics.total_markers


def refusal_is_clean(answer: str, sources: list[dict[str, Any]]) -> bool:
    """True iff a probe with ground-truth ``expected_refusal`` cited nothing.

    Deliberately NOT a general "zero markers means refusal" detector.
    ``extract_cited_indices``'s own docstring says counting markers is the
    entire signal for the refusal *it* recognizes — but that only holds
    because the probe already tells us this turn is expected to refuse. On
    unlabelled traffic, a confident, under-cited real answer looks identical
    to a clean refusal from the marker count alone; call this only against a
    probe whose ``expected_refusal`` you already have, never as a general
    refusal detector.
    """
    return extract_cited_indices(answer, sources) == []


def legacy_intervention_occurred(raw_answer: str, normalized_answer: str) -> bool:
    """Whether ``normalize_legacy_citations`` had to rewrite anything.

    A rising rate for one model relative to the baseline is a drift signal —
    that model is reverting to prose citations more than the current one —
    worth reporting. Never gated: ``normalize_legacy_citations`` already
    repairs it before the reader sees it, so this is telemetry, not a defect
    the reader is exposed to.
    """
    return raw_answer != normalized_answer


@dataclass(frozen=True)
class LeakageResult:
    """Whether a turn's outbound prompt still carries a marker from a prior turn."""

    leaked: bool
    markers_found: list[str]


def leakage_check(second_turn_messages: list[dict[str, Any]]) -> LeakageResult:
    """No ``[n]`` marker should survive into a replayed assistant turn.

    The end-to-end version of
    ``test_prompt_assembly_strips_markers_from_replayed_turns``
    (``web/tests/test_citations.py``) — run this against a live probe's
    actual second-turn ``_build_messages`` output, not a hand-built one. A
    hit here means ``_history_without_stale_markers``
    (``web/services/openai_app.py``) regressed for this model/provider.

    Args:
        second_turn_messages: The message list ``_build_messages`` produced
            for the SECOND turn of a cross-turn probe — i.e. after the first
            turn's answer has been folded into ``chat_history``.
    """
    found: list[str] = []
    for message in second_turn_messages:
        if message.get("role") != "assistant":
            continue
        found.extend(_MARKER.findall(message.get("content") or ""))
    return LeakageResult(leaked=bool(found), markers_found=found)


# ── Cost accounting ─────────────────────────────────────────────────────────
#
# The current generation path does not make this free to compute honestly:
# stream_response (openai_app.py) discards the stream's usage-only final
# chunk, and generate_response makes a SEPARATE, uncounted completion call
# for follow-up suggestions. The harness's run() step is responsible for
# requesting usage explicitly (e.g. stream_options={"include_usage": true})
# or falling back to a tokenizer estimate — this function only turns whatever
# it's handed into a labelled dollar figure; it does not fetch usage itself.


@dataclass(frozen=True)
class UsageEstimate:
    """One call's token/cost accounting, honestly labelled when it's a guess.

    ``exact`` is False whenever no provider usage was available and this
    fell back to a tokenizer count passed in by the caller.
    """

    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    cost_usd: Optional[float]
    exact: bool


def estimate_cost(
    usage: Optional[dict[str, int]],
    pricing_table: dict[str, tuple[float, float]],
    model_id: str,
    *,
    fallback_prompt_tokens: Optional[int] = None,
    fallback_completion_tokens: Optional[int] = None,
) -> UsageEstimate:
    """Turn provider usage (or a tokenizer fallback) into a dollar estimate.

    Args:
        usage: ``{"prompt_tokens": int, "completion_tokens": int}`` from the
            provider, or ``None`` if it wasn't available (in which case the
            two ``fallback_*`` arguments are used instead, and ``exact`` comes
            back ``False``).
        pricing_table: ``{model_id: (prompt_$_per_1M, completion_$_per_1M)}``.
            A harness-only constant, not ``config.yaml`` — pricing isn't a
            runtime setting an operator changes.
        model_id: Looked up in ``pricing_table``. An unknown id returns
            ``cost_usd=None`` rather than ``0.0`` or a guessed rate — pricing
            an unpriced model at $0 would make a genuinely free model and a
            not-yet-catalogued one look identical in a report.
    """
    if usage is not None:
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        exact = True
    else:
        prompt = fallback_prompt_tokens
        completion = fallback_completion_tokens
        exact = False

    rates = pricing_table.get(model_id)
    cost: Optional[float] = None
    if rates is not None and prompt is not None and completion is not None:
        prompt_rate, completion_rate = rates
        cost = (prompt / 1_000_000) * prompt_rate + (completion / 1_000_000) * completion_rate

    return UsageEstimate(prompt_tokens=prompt, completion_tokens=completion, cost_usd=cost, exact=exact)


# ── The gate ─────────────────────────────────────────────────────────────
#
# Corrected from this harness's first draft, per an adversarial review of the
# plan: a purely relative gate (challenger vs. baseline only) lets an already
# broken baseline legitimize an equally broken challenger, and a
# percentage-point delta computed from a handful of probes is not evidence of
# anything. Both are fixed structurally below, not just documented as caveats.


@dataclass(frozen=True)
class MetricSummary:
    """One metric's aggregate over a probe run, with its sample size attached.

    The sample size travels WITH the value specifically so
    ``compare_to_baseline`` can refuse to trust a delta computed from too few
    observations — a bare float here is how this harness's first draft ended
    up treating a 10-probe smoke run as if it supported a 2-percentage-point
    claim.

    Attributes:
        value: The aggregate metric value, or ``None`` if undefined for this
            run (e.g. no markers were ever emitted, so a hallucination rate
            has no denominator).
        n: The number of OBSERVATIONS the value was computed over — not
            necessarily the probe count, since e.g. ``marker_coverage`` is
            computed over sentences, not probes.
    """

    value: Optional[float]
    n: int


@dataclass(frozen=True)
class GateVerdict:
    """One metric's pass/fail/inconclusive verdict for one challenger.

    ``passed`` is ``None`` for inconclusive, deliberately distinct from both
    ``True`` and ``False`` — the whole point of a three-state field is that
    "we don't know" can never be silently read as "yes".
    """

    metric: str
    baseline: Optional[float]
    challenger: Optional[float]
    passed: Optional[bool]
    reason: str


@dataclass(frozen=True)
class GateReport:
    """The full comparison for one challenger against one baseline."""

    challenger_id: str
    baseline_id: str
    baseline_fails_floor: bool
    verdicts: list[GateVerdict]

    @property
    def passed(self) -> bool:
        """True only if the baseline itself clears its own floor AND every
        verdict passed outright — an inconclusive verdict is not a pass."""
        if self.baseline_fails_floor:
            return False
        return all(v.passed for v in self.verdicts)


# Minimum observations before a RELATIVE (percentage-point) comparison is
# trusted. Below this, only the absolute-floor check applies for metrics that
# have one — a smoke run (--limit 10) can tell you a challenger blew past an
# absolute ceiling, but cannot tell you it "regressed 2pp", because one
# flipped observation on 10 probes already IS 10pp.
MIN_SAMPLE_FOR_RELATIVE_COMPARISON = 30

# Absolute ceiling for hallucinated_marker_rate, independent of the baseline.
# Deliberately conservative against Perplexity's third-party-audited 37%
# citation-error rate — a different metric (full citation-support failure,
# not marker validity), but the nearest public reference point this product
# has for "how bad this can get in production". Revisit once Phase 0/1 has
# produced enough real baseline runs to replace this with an evidenced
# number specific to this corpus and prompt.
HALLUCINATED_MARKER_RATE_FLOOR = 0.05

# Relative-regression tolerances, applied only once MIN_SAMPLE_FOR_RELATIVE_
# COMPARISON is met on both sides.
_HALLUCINATION_REGRESSION_TOLERANCE_PP = 0.02
_GENERAL_REGRESSION_TOLERANCE_PP = 0.05

# Metrics that are gated as an absolute 100% floor rather than compared
# relatively — refusal cleanliness and cross-turn leakage are structural
# (either a labelled probe passed or it didn't), not a statistical question.
_STRUCTURAL_METRICS = frozenset({"refusal_is_clean", "leakage_check"})

# Reported for visibility but never gated — see each metric's own docstring
# above for why.
_INFORMATIONAL_METRICS = frozenset({"legacy_intervention_rate"})


def compare_to_baseline(
    baseline: dict[str, MetricSummary],
    challenger: dict[str, MetricSummary],
    *,
    challenger_id: str,
    baseline_id: str,
) -> GateReport:
    """The gate: does *challenger* clear *baseline* on every tracked metric?

    Both dicts are keyed by metric name (``"hallucinated_marker_rate"``,
    ``"marker_coverage"``, ...) and hold a ``MetricSummary``. A metric absent
    from either side is reported inconclusive for that metric rather than
    silently skipped, so an incomplete run cannot pass a gate by omission.
    """
    baseline_hallucination = baseline.get("hallucinated_marker_rate")
    baseline_fails_floor = bool(
        baseline_hallucination is not None
        and baseline_hallucination.value is not None
        and baseline_hallucination.value > HALLUCINATED_MARKER_RATE_FLOOR
    )

    verdicts = [
        _verdict_for(metric, baseline.get(metric), challenger.get(metric))
        for metric in sorted(set(baseline) | set(challenger))
    ]

    return GateReport(
        challenger_id=challenger_id,
        baseline_id=baseline_id,
        baseline_fails_floor=baseline_fails_floor,
        verdicts=verdicts,
    )


def _verdict_for(
    metric: str, baseline: Optional[MetricSummary], challenger: Optional[MetricSummary]
) -> GateVerdict:
    if baseline is None or challenger is None:
        return GateVerdict(metric, None, None, None, "missing on one side — cannot compare")

    if baseline.value is None or challenger.value is None:
        return GateVerdict(
            metric,
            baseline.value,
            challenger.value,
            None,
            "undefined for this probe set (e.g. no markers were ever emitted)",
        )

    if metric == "hallucinated_marker_rate":
        return _hallucination_verdict(baseline, challenger)

    if metric in _STRUCTURAL_METRICS:
        passed = challenger.value >= 1.0
        return GateVerdict(
            metric, baseline.value, challenger.value, passed,
            "must be 100% on labelled probes — structural, not a relative comparison",
        )

    if metric in _INFORMATIONAL_METRICS:
        return GateVerdict(metric, baseline.value, challenger.value, None, "reported only, not gated")

    return _relative_verdict(metric, baseline, challenger, tolerance=_GENERAL_REGRESSION_TOLERANCE_PP)


def _hallucination_verdict(baseline: MetricSummary, challenger: MetricSummary) -> GateVerdict:
    metric = "hallucinated_marker_rate"
    if challenger.value > HALLUCINATED_MARKER_RATE_FLOOR:
        return GateVerdict(
            metric, baseline.value, challenger.value, False,
            f"exceeds absolute floor {HALLUCINATED_MARKER_RATE_FLOOR:.0%}",
        )
    if challenger.n < MIN_SAMPLE_FOR_RELATIVE_COMPARISON:
        # Below the floor with no relative claim being made — a real pass,
        # not "inconclusive": the floor check itself needed no sample-size
        # minimum, since it's an absolute comparison, not a delta.
        return GateVerdict(metric, baseline.value, challenger.value, True, "within absolute floor")
    return _relative_verdict(
        metric, baseline, challenger, tolerance=_HALLUCINATION_REGRESSION_TOLERANCE_PP, higher_is_worse=True
    )


def _relative_verdict(
    metric: str,
    baseline: MetricSummary,
    challenger: MetricSummary,
    *,
    tolerance: float,
    higher_is_worse: bool = False,
) -> GateVerdict:
    if challenger.n < MIN_SAMPLE_FOR_RELATIVE_COMPARISON or baseline.n < MIN_SAMPLE_FOR_RELATIVE_COMPARISON:
        return GateVerdict(
            metric, baseline.value, challenger.value, None,
            f"fewer than {MIN_SAMPLE_FOR_RELATIVE_COMPARISON} observations — delta not trusted",
        )
    if higher_is_worse:
        regressed = challenger.value > baseline.value + tolerance
        reason = f"regressed beyond floor + {tolerance:.0%}"
    else:
        regressed = challenger.value < baseline.value - tolerance
        reason = f"regressed beyond baseline - {tolerance:.0%}"
    return GateVerdict(
        metric, baseline.value, challenger.value, not regressed,
        "no material regression" if not regressed else reason,
    )


def language_parity_gap(en_summary: MetricSummary, ar_summary: MetricSummary) -> Optional[float]:
    """EN-AR delta for a paired metric. Reported, never auto-gated.

    Positive means English scored higher. This is deliberately NOT folded
    into ``compare_to_baseline``: Arabic isn't part of the automated Layer-2
    (NLI) gate at all yet — see ``web/services/citation_fidelity.py``'s
    module docstring for why — so a parity number here is context for a
    human, not a pass/fail input.
    """
    if en_summary.value is None or ar_summary.value is None:
        return None
    return en_summary.value - ar_summary.value
