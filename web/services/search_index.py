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
from pathlib import Path
from typing import Any

import faiss
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

from web.services import build_registry
from web.services.search_exceptions import (
    DataDimensionMismatchError,
    DataLoadError,
    ManifestValidationError,
    SearchEngineNotInitializedError,
)
from web.utils.config_loader import config
from web.utils.embedding_helpers import get_embedding_client

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
        ManifestValidationError: If the active build's manifest.json doesn't
            match the currently-configured embedding client.
    """

    def __init__(self, config: SearchIndexConfig, embedding_client: Any = None) -> None:
        """
        Args:
            config: Path configuration (see :class:`SearchIndexConfig`).
            embedding_client: Optional, already-constructed embedding client
                to validate the build manifest against (see
                :meth:`_validate_manifest`). If omitted, one is constructed
                on demand from the global config during validation. Callers
                that already hold a client (e.g. ``SearchEngine``) should
                pass it here to avoid loading the embedding model twice.
        """
        self._config = config
        self._injected_embedding_client = embedding_client
        self.faiss_index: faiss.Index | None = None
        self.dataframe: pd.DataFrame | None = None
        self.tfidf_vectorizer: Any = None
        self.tfidf_matrix: csr_matrix | None = None
        self.is_loaded: bool = False

        # Populated by `_resolve_paths()` at the start of `load()`.
        self._active_build_dir: Path | None = None
        self._paths: dict[str, str] | None = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load all data assets from disk and validate consistency.

        If the engine is already loaded this method is a no-op.

        Raises:
            DataLoadError: If any required file is missing or corrupt.
            DataDimensionMismatchError: If loaded dimensions don't match.
            ManifestValidationError: If the active build's manifest.json
                doesn't match the currently-configured embedding client.
        """
        if self.is_loaded:
            logger.debug("SearchIndex already loaded — skipping.")
            return

        logger.info("Loading search index assets …")
        self._resolve_paths()
        self._check_files_exist()
        self._load_faiss_index()
        self._load_dataframe()
        self._load_tfidf_vectorizer()
        self._load_tfidf_matrix()
        self._validate_dimensions()
        self._validate_manifest()
        self.is_loaded = True
        logger.info("SearchIndex loaded successfully.")

    # ------------------------------------------------------------------
    # Path resolution — versioned builds vs. legacy flat layout
    # ------------------------------------------------------------------

    def _resolve_paths(self) -> None:
        """Determine which files to actually load from disk.

        If ``web/processed_data/active_build.txt`` names a valid, existing
        build directory (see :mod:`web.services.build_registry`), assets are
        loaded from *that* versioned build directory instead of the flat
        ``processed_data_dir`` paths in :class:`SearchIndexConfig`. This is
        what makes a newly-activated build actually take effect without
        requiring any change to how ``SearchEngine`` constructs its (fixed)
        ``SearchIndexConfig`` paths.

        Falls back to the legacy flat layout (files directly under
        ``processed_data_dir``) when no build has ever been activated, for
        backward compatibility with deployments that predate this system.
        """
        processed_data_dir = Path(self._config.processed_data_dir)
        active_dir = build_registry.resolve_active_build_dir(processed_data_dir)

        if active_dir is None:
            logger.info(
                "No active_build.txt found under %s — loading legacy flat "
                "layout directly from processed_data_dir. Run "
                "`python -m web.services.data_processing` to produce a "
                "versioned, manifest-backed build.",
                processed_data_dir,
            )
            self._active_build_dir = None
            self._paths = {
                "faiss": self._config.faiss_index_path,
                "dataframe": self._config.dataframe_path,
                "tfidf_vectorizer": self._config.tfidf_vectorizer_path,
                "tfidf_matrix": self._config.tfidf_matrix_path,
            }
            return

        logger.info("Loading active build '%s' from %s", active_dir.name, active_dir)
        self._active_build_dir = active_dir
        self._paths = {
            "faiss": str(active_dir / os.path.basename(self._config.faiss_index_path)),
            "dataframe": str(active_dir / os.path.basename(self._config.dataframe_path)),
            "tfidf_vectorizer": str(
                active_dir / os.path.basename(self._config.tfidf_vectorizer_path)
            ),
            "tfidf_matrix": str(active_dir / os.path.basename(self._config.tfidf_matrix_path)),
        }

    # ------------------------------------------------------------------
    # Private loaders
    # ------------------------------------------------------------------

    def _check_files_exist(self) -> None:
        """Verify that every required file is present on disk."""
        assert self._paths is not None, "_resolve_paths() must run before _check_files_exist()"
        paths = [
            self._paths["faiss"],
            self._paths["dataframe"],
            self._paths["tfidf_vectorizer"],
            self._paths["tfidf_matrix"],
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
        assert self._paths is not None
        try:
            self.faiss_index = faiss.read_index(self._paths["faiss"])
            logger.info("FAISS index loaded (%d vectors).", self.faiss_index.ntotal)
        except Exception as exc:
            raise DataLoadError(
                f"Failed to load FAISS index: {exc}"
            ) from exc

    def _load_dataframe(self) -> None:
        """Load the chunk-metadata CSV and sanitize critical columns."""
        assert self._paths is not None
        try:
            self.dataframe = pd.read_csv(self._paths["dataframe"])
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
        assert self._paths is not None
        try:
            with open(self._paths["tfidf_vectorizer"], "rb") as fh:
                self.tfidf_vectorizer = pickle.load(fh)  # noqa: S301
            logger.info("TF-IDF vectorizer loaded.")
        except Exception as exc:
            raise DataLoadError(
                f"Failed to load TF-IDF vectorizer: {exc}"
            ) from exc

    def _load_tfidf_matrix(self) -> None:
        """Unpickle the TF-IDF document-term matrix."""
        assert self._paths is not None
        try:
            with open(self._paths["tfidf_matrix"], "rb") as fh:
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

        if not build_registry.rows_consistent(df_rows, tfidf_rows, faiss_rows):
            raise DataDimensionMismatchError(
                f"Dimension mismatch — DataFrame: {df_rows}, "
                f"TF-IDF: {tfidf_rows}, FAISS: {faiss_rows}.",
                dataframe_rows=df_rows,
                tfidf_rows=tfidf_rows,
                faiss_vectors=faiss_rows,
            )

        logger.info("All data dimensions verified (%d chunks).", df_rows)

    def _validate_manifest(self) -> None:
        """Confirm the active build's manifest.json matches the currently
        configured embedding client (model name + vector dimension).

        This is what would have caught, automatically, the historical bug
        where ``config.yaml`` set ``embedding_model`` but
        ``local_embedding_client.py`` read a different (nonexistent) key and
        silently fell back to a hardcoded default: the index's declared
        embedding model now has to actually match what the app is
        configured to query with, or the app refuses to load it.

        If no build manifest is available at all (legacy flat layout, i.e.
        this index predates the build-manifest system), validation is
        skipped with a loud warning rather than a hard failure, so existing
        deployments aren't bricked by this change before they've ever run
        the new pipeline. Once a manifest *is* present, any mismatch is
        fatal.

        Raises:
            ManifestValidationError: If the manifest's recorded embedding
                model name and/or dimension don't match what the
                currently-configured embedding client actually produces.
        """
        if self._active_build_dir is None:
            logger.warning(
                "Loaded index has no build manifest (legacy flat layout) — "
                "cannot verify it matches the currently-configured embedding "
                "client. Rebuild with `python -m web.services.data_processing` "
                "to get a manifest-backed, validated build."
            )
            return

        try:
            manifest = build_registry.load_manifest(self._active_build_dir)
        except Exception as exc:
            raise ManifestValidationError(
                f"Active build '{self._active_build_dir.name}' is missing a "
                f"readable manifest.json: {exc}"
            ) from exc

        embedding_type = config.get("search_engine", "embedding_type", "local")
        client = self._injected_embedding_client
        if client is None:
            try:
                client = get_embedding_client(embedding_type)
            except Exception as exc:
                raise ManifestValidationError(
                    f"Could not construct the configured '{embedding_type}' "
                    f"embedding client to validate the active build's "
                    f"manifest: {exc}"
                ) from exc

        try:
            actual_dimension = client.embedding_dimension
        except Exception as exc:
            raise ManifestValidationError(
                f"Configured '{embedding_type}' embedding client does not "
                f"expose a usable embedding_dimension: {exc}"
            ) from exc

        actual_model_name = build_registry.extract_embedding_model_name(client)
        manifest_dimension = manifest.get("embedding_dimension")
        manifest_model_name = manifest.get("embedding_model_name")
        manifest_embedding_type = manifest.get("embedding_type")

        problems: list[str] = []

        if manifest_dimension != actual_dimension:
            problems.append(
                f"embedding_dimension mismatch — build '{self._active_build_dir.name}' "
                f"was created with dimension {manifest_dimension!r}, but the "
                f"currently-configured '{embedding_type}' embedding client "
                f"produces {actual_dimension}-dim vectors."
            )

        if manifest_model_name and actual_model_name and manifest_model_name != actual_model_name:
            problems.append(
                f"embedding_model_name mismatch — build "
                f"'{self._active_build_dir.name}' was created with model "
                f"{manifest_model_name!r}, but the currently-configured "
                f"'{embedding_type}' embedding client is "
                f"{actual_model_name!r}."
            )

        if manifest_embedding_type and manifest_embedding_type != embedding_type:
            problems.append(
                f"embedding_type mismatch — build "
                f"'{self._active_build_dir.name}' was created with provider "
                f"{manifest_embedding_type!r}, but the app is currently "
                f"configured to use {embedding_type!r}."
            )

        if problems:
            raise ManifestValidationError(
                "Refusing to load a search index whose build manifest does "
                "not match the currently-configured embedding client — "
                "loading it anyway would silently serve search results "
                "computed in the wrong vector space. " + " ".join(problems)
            )

        logger.info(
            "Build manifest verified: model=%r, dimension=%d, "
            "extraction_chunking_version=%r.",
            manifest_model_name,
            manifest_dimension,
            manifest.get("extraction_chunking_version"),
        )

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def active_build_id(self) -> str | None:
        """The build this engine actually loaded, or None for the legacy layout.

        DERIVED FROM WHAT WAS LOADED, never from the pointer file, and the
        distinction is the whole point. `read_active_build_id` reports what
        `active_build.txt` *says*; this reports what is in RAM. They disagree in
        two real cases: an activation flipping the pointer between this engine
        initialising and a later read of the file, and a dangling pointer naming
        a build that no longer exists — where `resolve_active_build_dir` falls
        back to the legacy flat corpus while the file still names the missing
        build.

        Both matter because this string is what a stored citation is compared
        against. Recording a revision the passages did not come from would let
        genuinely superseded evidence render as current, which is the one
        outcome this product cannot afford.
        """
        return self._active_build_dir.name if self._active_build_dir else None

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