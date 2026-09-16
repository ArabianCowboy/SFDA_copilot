"""Tests for the build pipeline's vector/row alignment probe.

The invariant under test is the one the product rests on: FAISS vector *i* is
the embedding of ``chunks_data.csv`` row *i*. Everything else the pipeline
checks compares artifacts to each other or counts rows, and a permuted index
passes all of it.

Fully offline — the stub client below returns a deterministic vector per string,
so nothing here downloads a model or touches the real corpus.
"""

from __future__ import annotations

import hashlib
import pickle
from pathlib import Path
from unittest.mock import patch

import faiss
import numpy as np
import pandas as pd
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from web.services.build_registry import (
    CHUNKS_CSV_NAME,
    FAISS_INDEX_NAME,
    TFIDF_MATRIX_NAME,
    TFIDF_VECTORIZER_NAME,
    validate_build_dir,
    write_manifest,
)
from web.services.data_processing import DataProcessingError, DataProcessor

DIM = 8
TEXTS = [f"Requirement {i} for the registration of a medicinal product." for i in range(40)]


def _vector(text: str) -> np.ndarray:
    """A deterministic unit vector per text, standing in for a real embedding."""
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big")
    vector = np.random.default_rng(seed).standard_normal(DIM).astype("float32")
    return vector / np.linalg.norm(vector)


class StubEmbeddingClient:
    embedding_dimension = DIM
    model_name = "stub-embedder"

    def get_embeddings(self, texts, batch_size=None):
        return np.stack([_vector(t) for t in texts])

    def get_embedding(self, text):
        return _vector(text)


@pytest.fixture
def processor(tmp_path: Path):
    with (
        patch(
            "web.services.data_processing.get_embedding_client",
            return_value=StubEmbeddingClient(),
        ),
        patch.object(DataProcessor, "PROCESSED_DATA_DIR", tmp_path),
    ):
        yield DataProcessor()


def _write_build(build_dir: Path, texts: list[str], vectors: np.ndarray) -> None:
    """Write a build whose CSV holds *texts* and whose index holds *vectors*."""
    build_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "text": texts,
            "category": "regulatory",
            "document": "guideline.pdf",
            "page": range(1, len(texts) + 1),
            "chunk_id": [f"guideline.pdf_p{i + 1}_0" for i in range(len(texts))],
        }
    ).to_csv(build_dir / CHUNKS_CSV_NAME, index=False)

    index = faiss.IndexFlatL2(DIM)
    index.add(vectors)
    faiss.write_index(index, str(build_dir / FAISS_INDEX_NAME))


def test_an_honestly_built_index_passes(processor: DataProcessor, tmp_path: Path):
    build = tmp_path / "build"
    _write_build(build, TEXTS, np.stack([_vector(t) for t in TEXTS]))

    processor._verify_vectors_match_their_rows(build)  # does not raise


@pytest.mark.parametrize(
    ("name", "permute"),
    [
        ("rotated by one", lambda v: np.roll(v, 1, axis=0)),
        ("reversed", lambda v: v[::-1].copy()),
        ("one pair swapped", lambda v: v[[1, 0, *range(2, len(TEXTS))]]),
        ("one row duplicated over its neighbour", lambda v: v[[0, 0, *range(2, len(TEXTS))]]),
    ],
)
def test_a_misaligned_index_is_refused(
    processor: DataProcessor, tmp_path: Path, name: str, permute
):
    # Row counts still agree in every one of these, which is exactly why
    # `rows_consistent` and the manifest's chunk_count cannot see them.
    build = tmp_path / "build"
    _write_build(build, TEXTS, permute(np.stack([_vector(t) for t in TEXTS])))

    with pytest.raises(DataProcessingError, match="does not match the vector stored"):
        processor._verify_vectors_match_their_rows(build)


def test_the_error_names_the_row_and_the_consequence(processor: DataProcessor, tmp_path: Path):
    # An operator reading this at 2am needs to know it must not be activated.
    build = tmp_path / "build"
    _write_build(build, TEXTS, np.roll(np.stack([_vector(t) for t in TEXTS]), 1, axis=0))

    with pytest.raises(DataProcessingError) as exc:
        processor._verify_vectors_match_their_rows(build)

    assert CHUNKS_CSV_NAME in str(exc.value)
    assert "Refusing to activate it." in str(exc.value)


def test_the_checks_that_already_existed_accept_a_misaligned_build(
    processor: DataProcessor, tmp_path: Path
):
    """The reason this probe exists, stated as a test.

    `validate_build_dir` reads every artifact back from disk and agrees the
    build is sound — because row counts match and the manifest's chunk_count
    matches — while every vector sits one row away from its own text. If this
    test ever fails because the older checks started catching it, this probe
    has become redundant and should be deleted rather than kept.
    """
    build = tmp_path / "builds" / "20260803T211733287685Z"
    vectors = np.roll(np.stack([_vector(t) for t in TEXTS]), 1, axis=0)
    _write_build(build, TEXTS, vectors)

    vectorizer = TfidfVectorizer()
    matrix = vectorizer.fit_transform(TEXTS)
    with open(build / TFIDF_VECTORIZER_NAME, "wb") as fh:
        pickle.dump(vectorizer, fh)
    with open(build / TFIDF_MATRIX_NAME, "wb") as fh:
        pickle.dump(matrix, fh)
    write_manifest(build, {"chunk_count": len(TEXTS), "embedding_dimension": DIM})

    validate_build_dir(build)  # passes, and that is the problem

    with pytest.raises(DataProcessingError, match="does not match the vector stored"):
        processor._verify_vectors_match_their_rows(build)


def test_a_build_smaller_than_the_sample_is_still_fully_checked(
    processor: DataProcessor, tmp_path: Path
):
    # `np.linspace` over fewer rows than the sample size must not index past the
    # end, and a tiny build should be checked exhaustively rather than skipped.
    build = tmp_path / "build"
    texts = TEXTS[:3]
    _write_build(build, texts, np.roll(np.stack([_vector(t) for t in texts]), 1, axis=0))

    with pytest.raises(DataProcessingError, match="does not match the vector stored"):
        processor._verify_vectors_match_their_rows(build)
