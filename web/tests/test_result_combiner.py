"""Pin the exact scores, penalty and ranking of ``ResultCombiner.combine``.

A batched rewrite of the per-candidate FAISS scoring must not change these
numbers, so they are recorded here from a small real index. No mocks: a real
``IndexFlatL2``, a fitted ``TfidfVectorizer``, production's 0.5/0.5 weights.
"""

from __future__ import annotations

import faiss
import numpy as np
import pandas as pd
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from web.services.result_combiner import ResultCombiner, SearchResult

QUERY_EMBEDDING = np.array([0.8, 0.6, 0.0], dtype=np.float32)
SEMANTIC_CANDIDATES = [{"index": 0}, {"index": 3}, {"index": 4}]
LEXICAL_CANDIDATES = [{"index": 1}, {"index": 2}, {"index": 0}]
LEXICAL_QUERY = "alpha beta"
REGISTRATION_QUERY = "registration of alpha"

# In rank order, one tuple per row: approx compares floats with tolerance
# and the rest exactly, and the list comparison pins order and length too.
# Unformatted: the long row exceeds 100 columns. Values stay inline literals.
# fmt: off
FIELDS = ("original_index", "text", "score", "page", "document", "chunk_id",
          "semantic_score", "lexical_score", "raw_hybrid_score", "penalty_reason")
EXPECTED = [dict(zip(FIELDS, row, strict=True), category="regulatory") for row in (
    (3, "alpha alpha beta", 0.976368, 4, "d.pdf", "c3", 0.9899495, 0.9627865, 0.976368, None),
    (0, "alpha beta", 0.9, 1, "a.pdf", "c0", 0.8, 1.0, 0.9, None),
    # Penalised: a registration query against a licensing guide scales the
    # hybrid by 0.80. Page "x" is not a digit, so it becomes None.
    (1, "beta gamma", 0.3524086, None, "drug_license_guide.pdf", "c1",
     0.6, 0.2810214, 0.4405107, "establishment_license_penalty"),
    # Zero semantic score (orthogonal to the query) but non-zero lexical:
    # the text shares "beta" with the lexical query.
    (2, "beta delta", 0.1638927, None, "c.pdf", "c2", 0.0, 0.3277855, 0.1638927, None),
    # Anti-parallel to the query, so the raw score is negative (-0.8) and the
    # max(0.0, ...) clamp makes it the lowest result.
    (4, "delta epsilon", 0.0, 2, "e.pdf", "c4", 0.0, 0.0, 0.0, None),
)]
# fmt: on


@pytest.fixture
def combiner() -> ResultCombiner:
    """Five rows with hand-computable semantic scores, real FAISS index and TF-IDF."""
    return _build_combiner(_build_index())


def _build_index() -> faiss.IndexFlatL2:
    vectors = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0 / np.sqrt(2.0), 1.0 / np.sqrt(2.0), 0.0],
            [-1.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    faiss_index = faiss.IndexFlatL2(3)
    faiss_index.add(vectors)
    return faiss_index


def _build_combiner(faiss_index) -> ResultCombiner:
    """Same DataFrame and TF-IDF around any index, so the proxy test shares them."""
    dataframe = pd.DataFrame(
        {
            "text": ["alpha beta", "beta gamma", "beta delta", "alpha alpha beta", "delta epsilon"],
            "document": ["a.pdf", "drug_license_guide.pdf", "c.pdf", "d.pdf", "e.pdf"],
            "category": ["regulatory"] * 5,
            "page": ["1", "x", None, 4, "2"],
            "chunk_id": ["c0", "c1", "c2", "c3", "c4"],
        }
    )
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(dataframe["text"].tolist())
    return ResultCombiner(
        dataframe=dataframe,
        faiss_index=faiss_index,
        tfidf_vectorizer=vectorizer,
        tfidf_matrix=tfidf_matrix,
        semantic_weight=0.5,
        lexical_weight=0.5,
    )


class _BatchCountingIndex:
    """Wraps the real index: records batched calls, refuses per-index ones."""

    def __init__(self, real_index: faiss.IndexFlatL2) -> None:
        self._real_index = real_index
        self.batch_calls: list[list[int]] = []

    def reconstruct_batch(self, keys):
        self.batch_calls.append(list(keys))
        return self._real_index.reconstruct_batch(keys)

    def reconstruct(self, *args) -> None:
        raise AssertionError("combine must score candidates in one batch, not per index")


def _combine(combiner: ResultCombiner, query_text: str, final_k: int) -> list[SearchResult]:
    return combiner.combine(
        SEMANTIC_CANDIDATES,
        LEXICAL_CANDIDATES,
        QUERY_EMBEDDING,
        LEXICAL_QUERY,
        query_text,
        final_k,
    )


def test_combine_fuses_real_faiss_and_tfidf_scores_and_ranks_them(combiner: ResultCombiner):
    results = _combine(combiner, REGISTRATION_QUERY, 10)

    rows = [
        {
            "text": r.text,
            "score": r.score,
            "page": r.page,
            "document": r.document,
            "category": r.category,
            "chunk_id": r.chunk_id,
            **r.metadata,
        }
        for r in results
    ]
    assert rows == [pytest.approx(row, abs=1e-6, rel=0) for row in EXPECTED]


def test_final_k_keeps_the_top_of_the_same_ranking(combiner: ResultCombiner):
    full = _combine(combiner, REGISTRATION_QUERY, 10)

    assert _combine(combiner, REGISTRATION_QUERY, 4) == full[:4]


def test_a_registration_query_that_names_an_establishment_is_not_penalised(
    combiner: ResultCombiner,
):
    results = _combine(combiner, "registration of a manufacturer license", 10)

    row_1 = next(r for r in results if r.metadata["original_index"] == 1)
    assert row_1.score == pytest.approx(0.4405107, abs=1e-6, rel=0)
    assert row_1.metadata["penalty_reason"] is None


def test_combine_reconstructs_every_candidate_in_one_faiss_call():
    proxy = _BatchCountingIndex(_build_index())
    _combine(_build_combiner(proxy), REGISTRATION_QUERY, 10)

    assert proxy.batch_calls == [[0, 1, 2, 3, 4]]


def test_a_query_of_the_wrong_dimension_raises_instead_of_returning_nothing(
    combiner: ResultCombiner,
):
    bad_query = np.array([0.8, 0.6, 0.0, 0.0], dtype=np.float32)
    with pytest.raises(ValueError):
        combiner.combine(
            SEMANTIC_CANDIDATES,
            LEXICAL_CANDIDATES,
            bad_query,
            LEXICAL_QUERY,
            REGISTRATION_QUERY,
            10,
        )


def test_an_out_of_range_candidate_is_skipped_not_scored(
    combiner: ResultCombiner, caplog: pytest.LogCaptureFixture
):
    results = combiner.combine(
        [{"index": 0}],
        [{"index": 99}],
        QUERY_EMBEDDING,
        LEXICAL_QUERY,
        REGISTRATION_QUERY,
        10,
    )

    assert [r.metadata["original_index"] for r in results] == [0]
    assert "Invalid index 99" in caplog.text


def test_an_exact_tie_breaks_toward_the_lower_chunk_index():
    vectors = np.tile(np.array([[1.0, 0.0, 0.0]], dtype=np.float32), (10, 1))
    tie_index = faiss.IndexFlatL2(3)
    tie_index.add(vectors)
    dataframe = pd.DataFrame(
        {
            "text": ["alpha beta"] * 10,
            "document": ["a.pdf"] * 10,
            "category": ["regulatory"] * 10,
            "page": ["1"] * 10,
            "chunk_id": [f"c{i}" for i in range(10)],
        }
    )
    vectorizer = TfidfVectorizer()
    tie_combiner = ResultCombiner(
        dataframe=dataframe,
        faiss_index=tie_index,
        tfidf_vectorizer=vectorizer,
        tfidf_matrix=vectorizer.fit_transform(dataframe["text"].tolist()),
        semantic_weight=0.5,
        lexical_weight=0.5,
    )
    results = tie_combiner.combine(
        [{"index": 9}], [{"index": 1}], QUERY_EMBEDDING, LEXICAL_QUERY, "alpha beta", 10
    )

    assert [r.metadata["original_index"] for r in results] == [1, 9]
