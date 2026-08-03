"""
Semantic search component — FAISS nearest-neighbour retrieval.

This module performs dense vector similarity search over a pre-built FAISS
index and applies optional category filtering.
"""

from __future__ import annotations

import logging
from typing import Any

import faiss
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class SemanticSearcher:
    """Retrieve candidates via FAISS approximate nearest-neighbour search.

    Args:
        faiss_index: A loaded FAISS index (e.g. ``IndexFlatL2``).
        dataframe: Chunk metadata DataFrame aligned with the index.
    """

    def __init__(self, faiss_index: faiss.Index, dataframe: pd.DataFrame) -> None:
        self._index = faiss_index
        self._df = dataframe

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query_embedding: np.ndarray,
        category: str = "all",
        k: int = 10,
    ) -> list[dict[str, Any]]:
        """Return the top-*k* semantic candidates for *query_embedding*.

        Each candidate dictionary contains:

        - ``index`` (*int*): Row position in the DataFrame.
        - ``score`` (*float*): Similarity score in [0, 1] (higher = better).
        - ``chunk_id`` (*str | None*): Chunk identifier for deduplication.

        Args:
            query_embedding: Normalised query vector of shape ``(1, D)``
                (as returned by FAISS-compatible searches).
            category: Category label to filter on. ``"all"`` disables filtering.
            k: Maximum number of candidates to return.

        Returns:
            A list of candidate dictionaries sorted by descending score.
        """
        results: list[dict[str, Any]] = []
        is_filtered = category.lower() != "all"

        # When a category filter is active, restricting FAISS to the small
        # windowed *k* first and filtering afterwards silently kills recall:
        # the true best matches for the category may not even be inside that
        # global top-k window, so they'd never get a chance to surface. The
        # index is a flat/exact IndexFlatL2 over a small corpus (a few
        # thousand vectors), so a full scan is cheap — search the *entire*
        # index, filter by category, then keep only the top-k of what
        # remains. Without a category filter there's no recall problem, so
        # we keep the cheaper windowed search.
        # NOTE: if the corpus grows dramatically (hundreds of thousands of
        # vectors), a full scan per filtered query will stop being cheap and
        # this approach should be revisited (e.g. per-category sub-indices).
        search_k = self._index.ntotal if is_filtered else k

        try:
            distances, indices = self._index.search(query_embedding, k=search_k)
        except Exception as exc:
            logger.exception("FAISS search failed: %s", exc)
            return results

        for position, row_idx in enumerate(indices[0]):
            # FAISS returns -1 when fewer than *search_k* results are available.
            if row_idx < 0 or row_idx >= len(self._df):
                continue

            # --- Category filtering ---
            if is_filtered:
                chunk_category: str = self._df.iloc[row_idx].get("category", "")
                if not self._categories_match(category, chunk_category):
                    continue

            # --- Convert L2 distance → similarity ∈ [0, 1] ---
            distance: float = float(distances[0][position])
            semantic_score: float = 1.0 / (1.0 + distance + 1e-9)

            chunk = self._df.iloc[row_idx]
            results.append(
                {
                    "index": int(row_idx),
                    "score": semantic_score,
                    "chunk_id": chunk.get("chunk_id"),
                }
            )

        # FAISS always returns neighbours sorted by ascending distance (i.e.
        # descending similarity), so when we searched the full index above,
        # `results` is already in descending-score order — truncating to the
        # originally-requested *k* is equivalent to taking the top-k by score.
        if is_filtered:
            results = results[:k]

        logger.debug(
            "Semantic search returned %d candidates (category=%s).",
            len(results),
            category,
        )
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_category(name: str) -> str:
        """Lowercase and strip underscores / spaces for fuzzy comparison."""
        return name.lower().replace("_", "").replace(" ", "")

    def _categories_match(self, query_category: str, chunk_category: str) -> bool:
        """Return ``True`` if *query_category* and *chunk_category* overlap.

        The comparison is symmetric and substring-based after normalisation,
        so ``"reg"`` matches ``"regulatory"`` and vice-versa.
        """
        q_norm = self._normalize_category(query_category)
        c_norm = self._normalize_category(chunk_category)
        return q_norm in c_norm or c_norm in q_norm