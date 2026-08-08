"""Tests for the retrieval relevance floor.

The floor is what lets retrieval say "nothing here". Without it ``combine``
returns the top *k* unconditionally, so an out-of-domain query gets the
least-bad eight passages and the answer that follows looks sourced.

The invariant these tests exist to protect is the last one: the floor returns
a PREFIX of its input. ``sources[i]`` must stay the same passage as prompt
block ``[i]``, and any filter that reorders or re-indexes breaks every citation
in the answer.
"""

from __future__ import annotations

import pytest

from web.services.result_combiner import SearchResult, apply_relevance_floor


def make_results(*scores: float) -> list[SearchResult]:
    """Descending-score results, as ``combine`` returns them."""
    return [
        SearchResult(
            text=f"passage {i}",
            score=score,
            document=f"doc_{i}.pdf",
            category="regulatory",
            page=i,
            chunk_id=f"c{i}",
            metadata={"semantic_score": score, "lexical_score": score},
        )
        for i, score in enumerate(scores, start=1)
    ]


# ── Disabled path ──────────────────────────────────────────────────────────

def test_both_thresholds_zero_returns_the_input_untouched():
    results = make_results(0.9, 0.5, 0.02)
    assert apply_relevance_floor(results, 0.0, 0.0) is results


def test_default_arguments_are_disabled():
    results = make_results(0.9, 0.01)
    assert apply_relevance_floor(results) is results


def test_empty_input_is_empty_output():
    assert apply_relevance_floor([], 0.5, 0.5) == []
    assert apply_relevance_floor([], 0.0, 0.0) == []


# ── Absolute floor ─────────────────────────────────────────────────────────

def test_everything_above_the_floor_survives():
    results = make_results(0.9, 0.7, 0.6)
    assert apply_relevance_floor(results, 0.5) == results


def test_the_weak_tail_is_dropped():
    results = make_results(0.9, 0.7, 0.2, 0.05)
    kept = apply_relevance_floor(results, 0.5)
    assert [r.score for r in kept] == [0.9, 0.7]


def test_nothing_above_the_floor_returns_empty():
    """The out-of-domain case: every candidate is weak, so none survive."""
    results = make_results(0.06, 0.05, 0.04, 0.02)
    assert apply_relevance_floor(results, 0.35) == []


def test_the_floor_is_inclusive():
    results = make_results(0.5, 0.4)
    assert len(apply_relevance_floor(results, 0.5)) == 1


# ── Relative floor ─────────────────────────────────────────────────────────

def test_ratio_truncates_relative_to_the_top_hit():
    results = make_results(0.8, 0.6, 0.3, 0.1)
    kept = apply_relevance_floor(results, 0.0, 0.5)   # cutoff = 0.40
    assert [r.score for r in kept] == [0.8, 0.6]


def test_ratio_alone_cannot_empty_a_uniformly_weak_set():
    """Why min_score is the load-bearing knob.

    Every candidate for an out-of-domain query is weak, so a floor defined
    relative to the best of them still admits the best of them. It trims a
    tail (0.45 * 0.06 = 0.027 drops the 0.02) but can never reach zero, so a
    ratio-only configuration does not fix the reported bug — the answer still
    gets sources. Only the absolute floor empties the set.
    """
    results = make_results(0.06, 0.05, 0.04, 0.02)

    ratio_only = apply_relevance_floor(results, 0.0, 0.45)
    assert ratio_only, "a relative floor can never empty a uniformly weak set"
    assert ratio_only[0].score == 0.06

    assert apply_relevance_floor(results, 0.35, 0.45) == []


def test_the_stricter_of_the_two_gates_wins():
    results = make_results(0.8, 0.5, 0.3)
    # absolute 0.55 beats relative 0.8*0.5 = 0.40
    assert [r.score for r in apply_relevance_floor(results, 0.55, 0.5)] == [0.8]
    # relative 0.8*0.9 = 0.72 beats absolute 0.1
    assert [r.score for r in apply_relevance_floor(results, 0.1, 0.9)] == [0.8]


def test_a_zero_top_score_neither_divides_nor_over_filters():
    results = make_results(0.0, 0.0)
    assert apply_relevance_floor(results, 0.0, 0.5) == results


# ── The alignment invariant ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "min_score,min_ratio",
    [(0.0, 0.0), (0.3, 0.0), (0.0, 0.5), (0.3, 0.5), (0.95, 0.0), (0.01, 0.01)],
)
def test_the_result_is_always_a_prefix_of_the_input(min_score, min_ratio):
    """Positions never move.

    Downstream, ``sources[i]`` must be the same passage the model saw as
    prompt block ``[i]``. A filter that reordered or compacted would point
    every citation in the answer at the wrong document.
    """
    results = make_results(0.95, 0.71, 0.68, 0.4, 0.12, 0.03)
    kept = apply_relevance_floor(results, min_score, min_ratio)
    assert kept == results[:len(kept)]


def test_the_input_list_is_not_mutated():
    results = make_results(0.9, 0.1)
    before = list(results)
    apply_relevance_floor(results, 0.5)
    assert results == before
