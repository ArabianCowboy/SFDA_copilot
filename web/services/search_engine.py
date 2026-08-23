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

from web.services.lexical_searcher import LexicalSearcher
from web.services.query_processor import QueryProcessor
from web.services.result_combiner import ResultCombiner, SearchResult, apply_relevance_floor
from web.services.search_exceptions import (
    DataLoadError,
    EmbeddingError,
    SearchEngineError,
    SearchEngineNotInitializedError,
)
from web.services.search_index import SearchIndex, SearchIndexConfig
from web.services.semantic_searcher import SemanticSearcher
from web.utils.config_loader import config, project_root
from web.utils.embedding_helpers import get_embedding_client

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
    # Default to disabled, so a config that never mentions a floor — and any
    # construction site that predates it — behaves exactly as before.
    min_score: float = 0.0
    min_score_ratio: float = 0.0

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
            min_score = float(config.get("search_engine", "min_score", 0.0))
            min_ratio = float(config.get("search_engine", "min_score_ratio", 0.0))
        except Exception as exc:
            raise SearchEngineError(f"Failed to read search engine config: {exc}") from exc

        if not np.isclose(sem_w + lex_w, 1.0):
            logger.warning(
                "Hybrid weights (semantic=%.2f, lexical=%.2f) do not sum to 1.",
                sem_w,
                lex_w,
            )

        # Out-of-range thresholds are clamped rather than raised on: scores are
        # in [0,1], so min_score=5 would silently refuse every query in
        # production. Clamping plus a loud warning fails visibly instead.
        for name, value in (("min_score", min_score), ("min_score_ratio", min_ratio)):
            if not 0.0 <= value <= 1.0:
                logger.warning(
                    "search_engine.%s = %s is outside [0, 1]; clamping. Scores are "
                    "cosine blends in [0,1], so this value would have filtered "
                    "everything or nothing.",
                    name,
                    value,
                )
        min_score = min(max(min_score, 0.0), 1.0)
        min_ratio = min(max(min_ratio, 0.0), 1.0)

        return cls(
            semantic_weight=sem_w,
            lexical_weight=lex_w,
            default_k=default_k,
            semantic_multiplier=sem_mult,
            lexical_multiplier=lex_mult,
            embedding_type=emb_type,
            min_score=min_score,
            min_score_ratio=min_ratio,
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
        self._index: SearchIndex = SearchIndex(
            self._index_config, embedding_client=self._embedding_client
        )
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
            hybrid score.  An empty list means the query genuinely matched
            nothing — it is a *result*, not an error.

        Raises:
            SearchEngineError: The index could not be loaded, or embedding,
                translation or ranking failed.

        A failure used to be swallowed into the same empty list a successful
        no-match search returns. That is load-bearing now: an empty list makes
        ``_prepare_context`` tell the model "No relevant information found",
        so the model refuses — and an OpenAI translation outage would have
        rendered as a clean, confident "I cannot answer based on the given
        information" instead of an error. Callers must be able to tell the two
        apart, so failures propagate.
        """
        if not self._ensure_initialized():
            raise SearchEngineNotInitializedError(
                "Search index could not be loaded; refusing to report this as an empty result set."
            )

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
            query_embedding_faiss = query_embedding.reshape(1, -1).astype("float32")

            # 4. Semantic search
            sem_results = self._semantic_searcher.search(
                query_embedding_faiss,
                category=category,
                k=sem_k,
            )

            # 5. Lexical search
            lex_results = self._lexical_searcher.search(
                lexical_query,
                category=category,
                k=lex_k,
            )

            # 6. Combine, score, rank
            combined = self._combiner.combine(
                semantic_results=sem_results,
                lexical_results=lex_results,
                query_embedding=query_embedding,
                lexical_query=lexical_query,
                query_text=retrieval_query,
                final_k=final_k,
            )

            # 7. Relevance floor. Applied HERE rather than in the routes,
            #    because search() returns the one list that forks into both the
            #    prompt context and the source payload — filtering upstream of
            #    that fork keeps them aligned structurally rather than by
            #    remembering to do it twice.
            results = apply_relevance_floor(
                combined,
                self._cfg.min_score,
                self._cfg.min_score_ratio,
            )

            if combined and not results:
                logger.warning(
                    "Relevance floor removed all %d results for query='%s…' (top score "
                    "%.4f < min_score %.4f). The model will be told no relevant "
                    "information was found and will refuse. If this fires on questions "
                    "the corpus can answer, min_score is too high.",
                    len(combined),
                    query[:60],
                    combined[0].score,
                    self._cfg.min_score,
                )

            logger.info("Search complete — %d results returned.", len(results))
            return results

        except EmbeddingError:
            query_preview = query[:200] if len(query) > 200 else query
            logger.exception("Query embedding/translation failed (query='%s')", query_preview)
            raise
        except SearchEngineError:
            query_preview = query[:200] if len(query) > 200 else query
            logger.exception("Search engine error (query='%s')", query_preview)
            raise
        except Exception as exc:
            # Wrapped so callers have one type to catch, but never silenced.
            query_preview = query[:200] if len(query) > 200 else query
            logger.exception("Unexpected error during search (query='%s')", query_preview)
            raise SearchEngineError(f"Unexpected search failure: {exc}") from exc

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

    @property
    def active_build_id(self) -> str | None:
        """The corpus build these answers are actually being drawn from.

        Delegates to the index, which is what resolved and loaded it. Read at
        startup into ``CORPUS_REVISION`` and stamped onto every stored answer,
        so a rehydrated citation can be compared against the corpus being served
        now and dated when the two differ.

        Deliberately NOT read from ``active_build.txt``: the pointer says what
        *should* be loaded, this says what *is*. They diverge when an activation
        lands between this engine initialising and the file being read, and when
        a dangling pointer names a build that no longer exists — where the index
        silently falls back to the legacy flat corpus while the file still names
        the missing build. Either way the pointer would record a revision the
        passages did not come from, and superseded evidence would render as
        current.
        """
        return self._index.active_build_id

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _ensure_initialized(self) -> bool:
        """Load data assets on first call; return ``True`` if ready."""
        if self._index.is_loaded:
            return True

        try:
            self._index.load()
        except (DataLoadError, SearchEngineError):
            logger.exception("Search index initialization failed")
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
        """Create the configured embedding client through the shared factory.

        Returns:
            An object satisfying :class:`QueryProcessor.EmbeddingClientProtocol`.

        Raises:
            SearchEngineError: If the configured provider cannot initialize.
        """
        try:
            client = get_embedding_client(self._cfg.embedding_type)
            logger.info(
                "Embedding client: %s",
                type(client).__name__,
            )
            return client
        except Exception as exc:
            # A FAISS index is tied to the embedding model/vector space used
            # to build it. Silently switching providers can return plausible
            # but incorrect search results, so initialization must fail loud.
            raise SearchEngineError(
                f"Failed to initialize '{self._cfg.embedding_type}' embedding provider."
            ) from exc


# ---------------------------------------------------------------------------
# Backward-compatible aliases
# ---------------------------------------------------------------------------

# Legacy class name kept for existing callers (app.py, tests).
ImprovedSearchEngine = SearchEngine
