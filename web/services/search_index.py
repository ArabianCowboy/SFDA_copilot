"""
Search index management — loads and validates FAISS, TF-IDF, and DataFrame assets.

This module owns the lifecycle of the on-disk search data: reading files from
``processed_data/``, validating that dimensions are consistent, and exposing
typed accessors for downstream search components.
"""

from __future__ import annotations

import os
import pickle
import logging
from dataclasses import dataclass, field
from typing import Any

import faiss
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

from web.services.search_exceptions import (
    DataDimensionMismatchError,
    DataLoadError,
    SearchEngineNotInitializedError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SearchIndexConfig:
    """Immutable configuration for ``SearchIndex`` paths.

    Attributes:
        processed_data_dir: Root directory containing all processed data.
        faiss_index_path: Path to the serialized FAISS index file.
        dataframe_path: Path to the CSV file with chunk metadata.
        tfidf_vectorizer_path: Path to the pickled TF-IDF vectorizer.
        tfidf_matrix_path: Path to the pickled TF-IDF sparse matrix.
    """

    processed_data_dir: str
    faiss_index_path: str
    dataframe_path: str
    tfidf_vectorizer_path: str
    tfidf_matrix_path: str

    # -- required columns inside the DataFrame --
    REQUIRED_COLUMNS: tuple[str, ...] = field(
        default=("text", "document", "category", "page", "chunk_id"),
        repr=False,
    )


# ---------------------------------------------------------------------------
# SearchIndex
# ---------------------------------------------------------------------------

class SearchIndex:
    """Loads, validates, and provides access to search data assets.

    The class eagerly loads all assets in :meth:`load` and performs
    dimension validation to guarantee that the FAISS index, TF-IDF matrix,
    and DataFrame rows are all aligned.

    Attributes:
        faiss_index: The loaded FAISS nearest-neighbour index.
        dataframe: Chunk metadata (text, document, category, page, …).
        tfidf_vectorizer: Fitted scikit-learn TF-IDF vectorizer.
        tfidf_matrix: Sparse TF-IDF document-term matrix.
        is_loaded: ``True`` after a successful :meth:`load` call.

    Raises:
        DataLoadError: If any required file is missing or unreadable.
        DataDimensionMismatchError: If row counts are inconsistent.
    """

    def __init__(self, config: SearchIndexConfig) -> None:
        self._config = config
        self.faiss_index: faiss.Index | None = None
        self.dataframe: pd.DataFrame | None = None
        self.tfidf_vectorizer: Any = None
        self.tfidf_matrix: csr_matrix | None = None
        self.is_loaded: bool = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load all data assets from disk and validate consistency.

        If the engine is already loaded this method is a no-op.

        Raises:
            DataLoadError: If any required file is missing or corrupt.
            DataDimensionMismatchError: If loaded dimensions don't match.
        """
        if self.is_loaded:
            logger.debug("SearchIndex already loaded — skipping.")
            return

        logger.info("Loading search index assets …")
        self._check_files_exist()
        self._load_faiss_index()
        self._load_dataframe()
        self._load_tfidf_vectorizer()
        self._load_tfidf_matrix()
        self._validate_dimensions()
        self.is_loaded = True
        logger.info("SearchIndex loaded successfully.")

    # ------------------------------------------------------------------
    # Private loaders
    # ------------------------------------------------------------------

    def _check_files_exist(self) -> None:
        """Verify that every required file is present on disk."""
        paths = [
            self._config.faiss_index_path,
            self._config.dataframe_path,
            self._config.tfidf_vectorizer_path,
            self._config.tfidf_matrix_path,
        ]
        missing = [p for p in paths if not os.path.exists(p)]
        if missing:
            raise DataLoadError(
                f"Processed data files missing: {missing}. "
                "Please run data processing first.",
                missing_files=missing,
            )

    def _load_faiss_index(self) -> None:
        """Deserialize the FAISS index from disk."""
        try:
            self.faiss_index = faiss.read_index(self._config.faiss_index_path)
            logger.info("FAISS index loaded (%d vectors).", self.faiss_index.ntotal)
        except Exception as exc:
            raise DataLoadError(
                f"Failed to load FAISS index: {exc}"
            ) from exc

    def _load_dataframe(self) -> None:
        """Load the chunk-metadata CSV and sanitize critical columns."""
        try:
            self.dataframe = pd.read_csv(self._config.dataframe_path)
            logger.info("DataFrame loaded (%d rows).", len(self.dataframe))
        except Exception as exc:
            raise DataLoadError(
                f"Failed to load DataFrame: {exc}"
            ) from exc

        # Validate required columns
        missing_cols = [
            c for c in self._config.REQUIRED_COLUMNS if c not in self.dataframe.columns
        ]
        if missing_cols:
            raise DataLoadError(
                f"DataFrame missing required columns: {missing_cols}"
            )

        # Fill NaN in text to avoid downstream errors
        self.dataframe["text"] = self.dataframe["text"].fillna("")

    def _load_tfidf_vectorizer(self) -> None:
        """Unpickle the fitted TF-IDF vectorizer."""
        try:
            with open(self._config.tfidf_vectorizer_path, "rb") as fh:
                self.tfidf_vectorizer = pickle.load(fh)  # noqa: S301
            logger.info("TF-IDF vectorizer loaded.")
        except Exception as exc:
            raise DataLoadError(
                f"Failed to load TF-IDF vectorizer: {exc}"
            ) from exc

    def _load_tfidf_matrix(self) -> None:
        """Unpickle the TF-IDF document-term matrix."""
        try:
            with open(self._config.tfidf_matrix_path, "rb") as fh:
                self.tfidf_matrix = pickle.load(fh)  # noqa: S301
            logger.info(
                "TF-IDF matrix loaded (shape=%s).", self.tfidf_matrix.shape,
            )
        except Exception as exc:
            raise DataLoadError(
                f"Failed to load TF-IDF matrix: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_dimensions(self) -> None:
        """Ensure all loaded assets describe the same number of chunks."""
        assert self.dataframe is not None, "DataFrame must be loaded before validation"
        assert self.tfidf_matrix is not None, "TF-IDF matrix must be loaded before validation"
        assert self.faiss_index is not None, "FAISS index must be loaded before validation"
        df_rows = len(self.dataframe)
        tfidf_rows = self.tfidf_matrix.shape[0]
        faiss_rows = self.faiss_index.ntotal

        if not (df_rows == tfidf_rows == faiss_rows):
            raise DataDimensionMismatchError(
                f"Dimension mismatch — DataFrame: {df_rows}, "
                f"TF-IDF: {tfidf_rows}, FAISS: {faiss_rows}.",
                dataframe_rows=df_rows,
                tfidf_rows=tfidf_rows,
                faiss_vectors=faiss_rows,
            )

        logger.info("All data dimensions verified (%d chunks).", df_rows)

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def embedding_dimension(self) -> int:
        """Return the vector dimensionality of the FAISS index."""
        if self.faiss_index is None:
            raise SearchEngineNotInitializedError("FAISS index is not loaded.")
        return self.faiss_index.d

    @property
    def total_chunks(self) -> int:
        """Return the total number of indexed chunks."""
        if self.faiss_index is None:
            return 0
        return self.faiss_index.ntotal