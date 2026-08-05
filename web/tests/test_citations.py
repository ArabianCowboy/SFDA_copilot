"""Tests for the citation payload and legacy-citation normalisation.

The numpy coercion tests are the important ones: ResultCombiner builds
SearchResult from pandas cells and numpy index arrays, so these fields arrive
as numpy scalars in production even though the dataclass annotates them as
plain Python types. Un-coerced, jsonify raises and the endpoint 500s.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from web.services.citations import (
    build_source_payload,
    normalize_legacy_citations,
)
from web.services.result_combiner import SearchResult


def result(**overrides):
    defaults = dict(
        text="Applications must be submitted within fifteen days of approval.",
        score=0.7143,
        document="Guidance_for_Submission.pdf",
        category="regulatory",
        page=14,
        chunk_id="guidance_p14_2",
        metadata={"semantic_score": 0.6312, "lexical_score": 0.7975},
    )
    defaults.update(overrides)
    return SearchResult(**defaults)


# ── Payload shape ───────────────────────────────────────────────────────────

def test_index_is_one_based_and_sequential():
    payload = build_source_payload([result(), result(), result()])
    assert [s["index"] for s in payload] == [1, 2, 3]


def test_payload_carries_the_fields_the_ui_needs():
    (source,) = build_source_payload([result()])
    assert source["document"] == "Guidance_for_Submission.pdf"
    assert source["page"] == 14
    assert source["category"] == "regulatory"
    assert source["score"] == 0.7143
    assert source["semantic_score"] == 0.6312
    assert source["lexical_score"] == 0.7975
    assert source["chunk_id"] == "guidance_p14_2"
    assert source["snippet"].startswith("Applications must be submitted")


def test_limit_keeps_sources_aligned_with_prompt_blocks():
    payload = build_source_payload([result() for _ in range(8)], limit=3)
    assert [s["index"] for s in payload] == [1, 2, 3]


# ── numpy / NaN coercion ────────────────────────────────────────────────────

def test_numpy_scalars_are_coerced_to_json_native_types():
    payload = build_source_payload([
        result(
            page=np.int64(14),
            score=np.float32(0.5),
            metadata={"semantic_score": np.float64(0.31), "lexical_score": np.float32(0.62)},
        )
    ])
    json.dumps(payload)  # would raise TypeError on numpy scalars

    (source,) = payload
    assert type(source["page"]) is int
    assert type(source["score"]) is float
    assert type(source["semantic_score"]) is float


def test_nan_becomes_none_rather_than_a_nan_literal():
    """json.dumps emits bare NaN for float('nan'), which is invalid JSON."""
    payload = build_source_payload([result(page=float("nan"), score=float("nan"))])
    (source,) = payload
    assert source["page"] is None
    assert source["score"] is None
    assert "NaN" not in json.dumps(payload)


def test_missing_metadata_scores_do_not_raise():
    (source,) = build_source_payload([result(metadata={})])
    assert source["semantic_score"] is None
    assert source["lexical_score"] is None


def test_missing_document_falls_back_to_a_label():
    (source,) = build_source_payload([result(document="")])
    assert source["document"] == "Unknown document"


def test_snippet_is_truncated_and_whitespace_collapsed():
    (source,) = build_source_payload([result(text="word  \n\n  spaced " + "x" * 500)])
    assert "\n" not in source["snippet"]
    assert source["snippet"].startswith("word spaced")
    assert len(source["snippet"]) <= 322


# ── Legacy citation normalisation ───────────────────────────────────────────

@pytest.fixture
def sources():
    return build_source_payload([
        result(document="A.pdf", page=3),
        result(document="B.pdf", page=14),
    ])


def test_prose_citation_becomes_a_numbered_marker(sources):
    text = "Submit within 15 days [Source: B.pdf, Page: 14]."
    assert normalize_legacy_citations(text, sources) == "Submit within 15 days [2]."


def test_matching_is_case_insensitive(sources):
    text = "See [source: a.pdf, page: 3]."
    assert normalize_legacy_citations(text, sources) == "See [1]."


def test_document_without_page_still_resolves(sources):
    assert normalize_legacy_citations("Text [Source: A.pdf].", sources) == "Text [1]."


def test_citation_naming_an_unretrieved_document_is_dropped(sources):
    """Better to lose the citation than to point it at the wrong source."""
    out = normalize_legacy_citations("Claim [Source: Hallucinated.pdf, Page: 9].", sources)
    assert "Hallucinated" not in out
    assert "[" not in out
    assert out == "Claim."


def test_existing_numbered_markers_are_untouched(sources):
    text = "Already numbered [1] and [2]."
    assert normalize_legacy_citations(text, sources) == text


def test_empty_sources_returns_text_unchanged():
    text = "Nothing [Source: A.pdf] here."
    assert normalize_legacy_citations(text, []) == text
