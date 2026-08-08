"""
Lexical search component — TF-IDF cosine similarity retrieval.

This module performs keyword-based search using a pre-fitted TF-IDF
vectorizer and sparse document-term matrix, with optional category filtering.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from scipy.sparse import csr_matrix

from web.services.search_exceptions import SearchEngineError

logger = logging.getLogger(__name__)


class LexicalSearcher:
    """Retrieve candidates via TF-IDF cosine similarity.

    Args:
        tfidf_vectorizer: A fitted scikit-learn ``TfidfVectorizer``.
        tfidf_matrix: Sparse document-term matrix aligned with *dataframe*.
        dataframe: Chunk metadata DataFrame aligned with *tfidf_matrix*.
    """

    def __init__(
        self,
        tfidf_vectorizer: Any,
        tfidf_matrix: csr_matrix,
        dataframe: pd.DataFrame,
    ) -> None:
        self._vectorizer = tfidf_vectorizer
        self._matrix = tfidf_matrix
        self._df = dataframe

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        category: str = "all",
        k: int = 10,
    ) -> list[dict[str, Any]]:
        """Return the top-*k* lexical candidates for *query*.

        Each candidate dictionary contains:

        - ``index`` (*int*): Row position in the DataFrame.
        - ``score`` (*float*): Cosine similarity in [0, 1] (higher = better).
        - ``chunk_id`` (*str | None*): Chunk identifier for deduplication.

        Args:
            query: The (possibly expanded) text query.
            category: Category label to filter on. ``"all"`` disables filtering.
            k: Maximum number of candidates to return.

        Returns:
            A list of candidate dictionaries sorted by descending score.
        """
        results: list[dict[str, Any]] = []

        try:
            query_vec = self._vectorizer.transform([query])
            similarities: np.ndarray = cosine_similarity(
                query_vec, self._matrix
            ).flatten()
        except Exception as exc:
            # Raised rather than returned as an empty candidate list — see the
            # matching note in semantic_searcher. Note the difference from the
            # category filter below, which returns empty legitimately: no
            # document in that category is a real answer, a broken vectorizer
            # is not.
            logger.exception("TF-IDF transformation failed: %s", exc)
            raise SearchEngineError(f"Lexical search failed: {exc}") from exc

        # --- Category filtering ---
        if category.lower() != "all":
            valid_indices = self._filter_by_category(category)
            if valid_indices is None or len(valid_indices) == 0:
                logger.debug(
                    "No documents matched category '%s' in lexical search.",
                    category,
                )
                return results
            filtered_sims = similarities[valid_indices]
            original_indices_map = valid_indices
        else:
            filtered_sims = similarities
            original_indices_map = np.arange(len(similarities))

        # --- Select top-k ---
        num_to_fetch = min(k, len(filtered_sims))
        if num_to_fetch == 0:
            return results

        # argsort returns ascending; [-N:] takes the largest; [::-1] reverses
        top_filtered_idx = np.argsort(filtered_sims)[-num_to_fetch:][::-1]
        top_original_idx = original_indices_map[top_filtered_idx]
        top_scores = filtered_sims[top_filtered_idx]

        for i, original_idx in enumerate(top_original_idx):
            if original_idx < 0 or original_idx >= len(self._df):
                continue
            chunk = self._df.iloc[original_idx]
            results.append(
                {
                    "index": int(original_idx),
                    "score": float(top_scores[i]),
                    "chunk_id": chunk.get("chunk_id"),
                }
            )

        logger.debug(
            "Lexical search returned %d candidates (category=%s).",
            len(results),
            category,
        )
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _filter_by_category(self, category: str) -> np.ndarray | None:
        """Return an array of DataFrame indices whose category matches *category*.

        Returns ``None`` (instead of an empty array) only on unexpected errors.
        """
        q_norm = self._normalize_category(category)
        norm_categories = self._df["category"].apply(self._normalize_category)

        mask = norm_categories.str.contains(q_norm, na=False) | norm_categories.apply(
            lambda x: x in q_norm
        )
        return np.where(mask)[0]

    @staticmethod
    def _normalize_category(name: str) -> str:
        """Lowercase and strip underscores / spaces for fuzzy comparison."""
        return name.lower().replace("_", "").replace(" ", "")