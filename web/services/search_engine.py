"""
Search engine facade — orchestrates the hybrid search pipeline.

This module provides :class:`SearchEngine`, a high-level entry point that
composes:

- :class:`~web.services.search_index.SearchIndex` for data loading.
- :class:`~web.services.query_processor.QueryProcessor` for translation,
  expansion, and embedding.
- :class:`~web.services.semantic_searcher.SemanticSearcher` for FAISS
  nearest-neighbour retrieval.
- :class:`~web.services.lexical_searcher.LexicalSearcher` for TF-IDF
  cosine similarity retrieval.
- :class:`~web.services.result_combiner.ResultCombiner` for weighted score
  fusion and ranking.

Public API
----------
``SearchEngine.search(query, category, k)``
    Perform a hybrid search and return a ranked list of
    :class:`~web.services.result_combiner.SearchResult` objects.

Example
-------
>>> engine = SearchEngine()
>>> results = engine.search("adverse events in biologicals", category="all")
>>> for r in results:
...     print(r.score, r.document)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..utils.config_loader import config, project_root
from ..utils.local_embedding_client import LocalEmbeddingClient
from ..utils.openai_client import OpenAIClientManager

from web.services.search_exceptions import (
    DataLoadError,
    EmbeddingError,
    SearchEngineError,
)
from web.services.search_index import SearchIndex, SearchIndexConfig
from web.services.query_processor import QueryProcessor
from web.services.semantic_searcher import SemanticSearcher
from web.services.lexical_searcher import LexicalSearcher
from web.services.result_combiner import ResultCombiner, SearchResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SearchEngine configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SearchEngineConfig:
    """Immutable runtime configuration for :class:`SearchEngine`.

    All values are read once from the central YAML config at construction time.
    """

    semantic_weight: float
    lexical_weight: float
    default_k: int
    semantic_multiplier: int
    lexical_multiplier: int
    embedding_type: str

    @classmethod
    def from_yaml(cls) -> SearchEngineConfig:
        """Build an instance from the central ``config.yaml``.

        Returns:
            A fully-populated ``SearchEngineConfig``.

        Raises:
            SearchEngineError: If required config keys are missing.
        """
        try:
            sem_w = float(config.get("search_engine", "semantic_weight", 0.7))
            lex_w = float(config.get("search_engine", "lexical_weight", 0.3))
            default_k = int(config.get("search_engine", "k", 3))
            sem_mult = int(config.get("search_engine", "semantic_multiplier", 3))
            lex_mult = int(config.get("search_engine", "lexical_multiplier", 3))
            emb_type = str(config.get("search_engine", "embedding_type", "local"))
        except Exception as exc:
            raise SearchEngineError(
                f"Failed to read search engine config: {exc}"
            ) from exc

        if not np.isclose(sem_w + lex_w, 1.0):
            logger.warning(
                "Hybrid weights (semantic=%.2f, lexical=%.2f) do not sum to 1.",
                sem_w,
                lex_w,
            )

        return cls(
            semantic_weight=sem_w,
            lexical_weight=lex_w,
            default_k=default_k,
            semantic_multiplier=sem_mult,
            lexical_multiplier=lex_mult,
            embedding_type=emb_type,
        )


# ---------------------------------------------------------------------------
# Public category map (reference / documentation)
# ---------------------------------------------------------------------------

CATEGORY_MAP: dict[str, str] = {
    "biological": "biological_products_and_quality_control",
    "veterinary": "veterinary_medicines",
    "pharmacovigilance": "pharmacovigilance",
    "regulatory": "regulatory",
    "all": "all",
}


# ---------------------------------------------------------------------------
# SearchEngine
# ---------------------------------------------------------------------------

class SearchEngine:
    """High-level hybrid search engine.

    The engine combines **semantic** (FAISS vector) search with **lexical**
    (TF-IDF) search, fuses the results with configurable weights, and
    supports filtering by document category.

    Lifecycle:
        1. Constructing an instance loads configuration and sets up the
           embedding / translation clients.
        2. Calling :meth:`search` triggers lazy initialisation of the
           underlying data index on the first call.

    Example::

        engine = SearchEngine()
        results = engine.search("marketing authorization requirements")
        for result in results:
            print(f"{result.score:.3f}  {result.document}  p{result.page}")
    """

    def __init__(self) -> None:
        logger.info("Constructing SearchEngine …")

        # --- Configuration ---
        self._cfg = SearchEngineConfig.from_yaml()

        # --- Paths ---
        processed_data_dir = os.path.join(
            project_root,
            config.get("paths", "processed_data", "web/processed_data"),
        )
        self._index_config = SearchIndexConfig(
            processed_data_dir=processed_data_dir,
            faiss_index_path=os.path.join(
                processed_data_dir,
                config.get("filenames", "faiss_index", "faiss_index.bin"),
            ),
            dataframe_path=os.path.join(
                processed_data_dir,
                config.get("filenames", "chunks_data", "chunks_data.csv"),
            ),
            tfidf_vectorizer_path=os.path.join(
                processed_data_dir,
                config.get("filenames", "tfidf_vectorizer", "tfidf_vectorizer.pkl"),
            ),
            tfidf_matrix_path=os.path.join(
                processed_data_dir,
                config.get("filenames", "tfidf_matrix", "tfidf_matrix.pkl"),
            ),
        )

        # --- Translation client (optional) ---
        self._translation_client: Any = self._build_translation_client()

        # --- Embedding client ---
        self._embedding_client = self._build_embedding_client()
        self._embedding_dimension: int = self._embedding_client.embedding_dimension

        # --- Lazy-loaded components (populated on first search) ---
        self._index: SearchIndex = SearchIndex(self._index_config)
        self._query_processor: QueryProcessor = QueryProcessor(
            embedding_client=self._embedding_client,
            translation_client=self._translation_client,
        )
        self._semantic_searcher: SemanticSearcher | None = None
        self._lexical_searcher: LexicalSearcher | None = None
        self._combiner: ResultCombiner | None = None

        logger.info("SearchEngine constructed.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        category: str = "all",
        k: int | None = None,
    ) -> list[SearchResult]:
        """Execute a hybrid search and return ranked results.

        On the first invocation the underlying data index is loaded from
        disk (lazy initialisation). Subsequent calls reuse the loaded data.

        Args:
            query: The raw user search query.
            category: Document category to filter by.  Use ``"all"`` for no
                filtering.  Valid values include ``"regulatory"``,
                ``"pharmacovigilance"``, ``"biological"``, ``"veterinary"``.
            k: Number of top results to return.  Defaults to the value in
                ``config.yaml`` (``search_engine.k``).

        Returns:
            A list of :class:`SearchResult` objects sorted by descending
            hybrid score.  Returns an empty list if the engine could not be
            initialised or an error occurred.
        """
        if not self._ensure_initialized():
            return []

        assert (
            self._semantic_searcher is not None
            and self._lexical_searcher is not None
            and self._combiner is not None
        ), "Component searchers must be initialised."

        logger.info(
            "Hybrid search: query='%s…', category=%s, k=%s",
            query[:80],
            category,
            k,
        )

        try:
            final_k = max(1, k if k is not None else self._cfg.default_k)
            sem_k = final_k * self._cfg.semantic_multiplier
            lex_k = final_k * self._cfg.lexical_multiplier

            # 1. Translate (Arabic → English if applicable)
            retrieval_query = self._query_processor.translate_query(query)

            # 2. Expand for lexical search
            lexical_query = self._query_processor.expand_lexical_query(
                retrieval_query,
            )

            # 3. Embed the query
            query_embedding = self._query_processor.get_embedding(retrieval_query)
            query_embedding_faiss = (
                query_embedding.reshape(1, -1).astype("float32")
            )

            # 4. Semantic search
            sem_results = self._semantic_searcher.search(
                query_embedding_faiss, category=category, k=sem_k,
            )

            # 5. Lexical search
            lex_results = self._lexical_searcher.search(
                lexical_query, category=category, k=lex_k,
            )

            # 6. Combine, score, rank
            results = self._combiner.combine(
                semantic_results=sem_results,
                lexical_results=lex_results,
                query_embedding=query_embedding,
                lexical_query=lexical_query,
                query_text=retrieval_query,
                final_k=final_k,
            )

            logger.info("Search complete — %d results returned.", len(results))
            return results

        except EmbeddingError as exc:
            logger.error("Embedding failed: %s", exc)
            return []
        except SearchEngineError as exc:
            logger.error("Search engine error: %s", exc)
            return []
        except Exception as exc:
            logger.exception("Unexpected error during search: %s", exc)
            return []

    def initialize(self) -> bool:
        """Load the search index eagerly.

        This is the public entry-point called by ``app.py`` after
        construction.  Delegates to :meth:`_ensure_initialized` and is
        safe to call multiple times (subsequent calls are no-ops).

        Returns:
            ``True`` if the index loaded successfully, ``False`` otherwise.
        """
        return self._ensure_initialized()

    def is_initialized(self) -> bool:
        """Return ``True`` when the data index has been successfully loaded."""
        return self._index.is_loaded

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _ensure_initialized(self) -> bool:
        """Load data assets on first call; return ``True`` if ready."""
        if self._index.is_loaded:
            return True

        try:
            self._index.load()
        except (DataLoadError, SearchEngineError) as exc:
            logger.error("Failed to initialise search index: %s", exc)
            return False

        # Build component searchers from the loaded data
        assert self._index.dataframe is not None
        assert self._index.faiss_index is not None
        assert self._index.tfidf_vectorizer is not None
        assert self._index.tfidf_matrix is not None

        self._semantic_searcher = SemanticSearcher(
            faiss_index=self._index.faiss_index,
            dataframe=self._index.dataframe,
        )
        self._lexical_searcher = LexicalSearcher(
            tfidf_vectorizer=self._index.tfidf_vectorizer,
            tfidf_matrix=self._index.tfidf_matrix,
            dataframe=self._index.dataframe,
        )
        self._combiner = ResultCombiner(
            dataframe=self._index.dataframe,
            faiss_index=self._index.faiss_index,
            tfidf_vectorizer=self._index.tfidf_vectorizer,
            tfidf_matrix=self._index.tfidf_matrix,
            embedding_dimension=self._embedding_dimension,
            semantic_weight=self._cfg.semantic_weight,
            lexical_weight=self._cfg.lexical_weight,
        )

        logger.info("SearchIndex components initialised.")
        return True

    # ------------------------------------------------------------------
    # Client factories
    # ------------------------------------------------------------------

    @staticmethod
    def _build_translation_client() -> Any:
        """Create an OpenAI client for Arabic → English translation.

        Returns:
            An ``openai.OpenAI`` instance, or ``None`` if no API key is set.
        """
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.info("No OPENAI_API_KEY — translation disabled.")
            return None
        try:
            from openai import OpenAI

            return OpenAI(api_key=api_key)
        except Exception as exc:
            logger.warning("Could not initialise translation client: %s", exc)
            return None

    def _build_embedding_client(self) -> Any:
        """Create the embedding client using the enhanced factory or fallback.

        Returns:
            An object satisfying :class:`QueryProcessor.EmbeddingClientProtocol`.

        Raises:
            SearchEngineError: If both the enhanced factory and fallback fail.
        """
        # Try the enhanced factory first
        try:
            from ..utils.embedding_helpers import (
                get_embedding_client,
            )

            client = get_embedding_client(self._cfg.embedding_type)
            logger.info(
                "Embedding client (enhanced): %s", type(client).__name__,
            )
            return client
        except Exception as exc:
            logger.warning(
                "Enhanced embedding client failed (%s); using fallback.", exc,
            )

        # Fallback to legacy clients
        if self._cfg.embedding_type == "openai":
            return OpenAIClientManager()
        return LocalEmbeddingClient()


# ---------------------------------------------------------------------------
# Backward-compatible aliases
# ---------------------------------------------------------------------------

# Legacy class name kept for existing callers (app.py, tests).
ImprovedSearchEngine = SearchEngine
