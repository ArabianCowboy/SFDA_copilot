"""
Result combination and ranking — fuses semantic and lexical candidates.

This module takes raw candidate lists from the semantic and lexical searchers,
computes exact per-candidate scores, applies weighted fusion and domain-
specific heuristic penalties, deduplicates by chunk index, and returns a
ranked list of :class:`SearchResult` objects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchResult:
    """A single, final search result returned to the caller.

    Attributes:
        text: The text content of the chunk.
        score: Final hybrid score (higher = better).
        document: Source document name.
        category: Category of the source document.
        page: Page number in the source document, if available.
        chunk_id: Unique identifier for the text chunk.
        metadata: Auxiliary info such as individual semantic / lexical scores.
    """

    text: str
    score: float
    document: str
    category: str
    page: int | None = None
    chunk_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ResultCombiner
# ---------------------------------------------------------------------------


class ResultCombiner:
    """Merge, score, and rank candidates from semantic and lexical search.

    Args:
        dataframe: Chunk metadata DataFrame (must contain columns
            ``text``, ``document``, ``category``, ``page``, ``chunk_id``).
        faiss_index: Loaded FAISS index used to reconstruct chunk vectors.
        tfidf_vectorizer: Fitted TF-IDF vectorizer.
        tfidf_matrix: Sparse TF-IDF document-term matrix.
        embedding_dimension: Dimensionality of the embedding vectors.
        semantic_weight: Weight for the semantic component (0–1).
        lexical_weight: Weight for the lexical component (0–1).
    """

    def __init__(
        self,
        dataframe: pd.DataFrame,
        faiss_index: Any,
        tfidf_vectorizer: Any,
        tfidf_matrix: Any,
        embedding_dimension: int,
        semantic_weight: float,
        lexical_weight: float,
    ) -> None:
        self._df = dataframe
        self._faiss_index = faiss_index
        self._tfidf_vectorizer = tfidf_vectorizer
        self._tfidf_matrix = tfidf_matrix
        self._embedding_dim = embedding_dimension
        self._semantic_weight = semantic_weight
        self._lexical_weight = lexical_weight

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def combine(
        self,
        semantic_results: list[dict[str, Any]],
        lexical_results: list[dict[str, Any]],
        query_embedding: np.ndarray,
        lexical_query: str,
        query_text: str,
        final_k: int,
    ) -> list[SearchResult]:
        """Combine and rank candidates from both search pipelines.

        Steps:
            1. Compute the union of unique chunk indices from both pipelines.
            2. Re-calculate exact semantic cosine similarity (via FAISS
               ``reconstruct``) and exact lexical TF-IDF cosine similarity for
               every candidate.
            3. Apply weighted fusion: ``hybrid = w_s * sem + w_l * lex``.
            4. Apply domain-specific heuristic penalties (e.g. penalise
               establishment-licensing documents when the query is about
               product registration).
            5. Sort by descending hybrid score and return the top *final_k*.

        Args:
            semantic_results: Candidates from :class:`SemanticSearcher`.
            lexical_results: Candidates from :class:`LexicalSearcher`.
            query_embedding: Unit-normalised query vector ``(1, D)``.
            lexical_query: The expanded query used for TF-IDF scoring.
            query_text: The (possibly translated) query text for heuristic
                classification.
            final_k: Maximum number of results to return.

        Returns:
            A sorted list of :class:`SearchResult` objects.
        """
        union_indices: set[int] = {r["index"] for r in semantic_results} | {
            r["index"] for r in lexical_results
        }

        if not union_indices:
            return []

        # --- Vectorised lexical scores for all candidates at once ---
        lexical_scores = self._compute_lexical_scores(union_indices, lexical_query)

        # --- Heuristic flags derived from query text ---
        is_reg_query, asks_establishment = self._classify_query(query_text)

        q_emb = query_embedding.flatten()
        final_results: list[SearchResult] = []

        for idx in union_indices:
            try:
                sem_score = self._compute_semantic_score(idx, q_emb)
                lex_score = lexical_scores.get(idx, 0.0)
                hybrid = self._semantic_weight * sem_score + self._lexical_weight * lex_score

                # --- Build SearchResult ---
                if idx < 0 or idx >= len(self._df):
                    logger.warning("Invalid index %d — skipping.", idx)
                    continue

                chunk = self._df.iloc[idx]

                # --- Heuristic penalty ---
                doc_name: str = chunk.get("document", "")
                boosted_score, penalty = self._apply_penalty_for_chunk(
                    doc_name,
                    hybrid,
                    is_reg_query,
                    asks_establishment,
                )

                page_val = chunk.get("page")
                page: int | None = None
                if pd.notna(page_val):
                    page_str = str(page_val).strip()
                    if page_str.isdigit():
                        page = int(page_str)

                final_results.append(
                    SearchResult(
                        text=chunk.get("text", ""),
                        score=boosted_score,
                        document=chunk.get("document", ""),
                        category=chunk.get("category", "Unknown"),
                        page=page,
                        chunk_id=chunk.get("chunk_id"),
                        metadata={
                            "semantic_score": sem_score,
                            "lexical_score": lex_score,
                            "original_index": idx,
                            "raw_hybrid_score": hybrid,
                            "penalty_reason": penalty,
                        },
                    )
                )
            except Exception as exc:
                logger.exception(
                    "Error combining result for index %d: %s",
                    idx,
                    exc,
                )

        final_results.sort(key=lambda r: r.score, reverse=True)
        logger.debug(
            "Returning %d combined results (of %d candidates).",
            min(len(final_results), final_k),
            len(union_indices),
        )
        return final_results[:final_k]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_lexical_scores(
        self,
        indices: set[int],
        lexical_query: str,
    ) -> dict[int, float]:
        """Compute exact TF-IDF cosine similarity for every index in *indices*."""
        idx_list = list(indices)
        if not idx_list:
            return {}
        query_vec = self._tfidf_vectorizer.transform([lexical_query])
        candidate_matrix = self._tfidf_matrix[idx_list]
        sims = cosine_similarity(query_vec, candidate_matrix).flatten()
        return {idx: float(sim) for idx, sim in zip(idx_list, sims, strict=True)}

    def _compute_semantic_score(self, idx: int, query_vec: np.ndarray) -> float:
        """Reconstruct chunk vector from FAISS and compute cosine similarity."""
        chunk_vec = np.zeros(self._embedding_dim, dtype=np.float32)
        self._faiss_index.reconstruct(idx, chunk_vec)
        diff = query_vec - chunk_vec
        distance = float(np.dot(diff, diff))
        return max(0.0, min(1.0, 1.0 - distance / 2.0))

    @staticmethod
    def _classify_query(query_text: str) -> tuple[bool, bool]:
        """Determine heuristic flags from *query_text*.

        Returns:
            A tuple ``(is_registration_query, asks_about_establishment)``.
        """
        low = query_text.lower()
        is_registration = any(
            w in low
            for w in (
                "registration",
                "register",
                "submission",
                "dossier",
                "marketing authorization",
            )
        )
        asks_establishment = any(
            w in low
            for w in (
                "license",
                "licensing",
                "warehouse",
                "manufacturer",
                "establishment",
                "scientific office",
            )
        )
        return is_registration, asks_establishment

    def _apply_penalty_for_chunk(
        self,
        doc_name: str,
        hybrid_score: float,
        is_registration_query: bool,
        asks_establishment: bool,
    ) -> tuple[float, str | None]:
        """Apply domain heuristic penalties using the document name.

        This is the instance-level version that can inspect *doc_name*.

        Returns:
            ``(adjusted_score, penalty_reason_or_None)``
        """
        if not is_registration_query or asks_establishment:
            return hybrid_score, None

        low_name = doc_name.lower()
        is_license_doc = any(w in low_name for w in ("license", "licensing"))
        is_establishment_doc = any(
            w in low_name
            for w in ("warehouse", "manufacturer", "clinical_trials_centers", "scientific_office")
        )
        if is_license_doc or is_establishment_doc:
            return hybrid_score * 0.80, "establishment_license_penalty"
        return hybrid_score, None


# ---------------------------------------------------------------------------
# Relevance floor
# ---------------------------------------------------------------------------


def apply_relevance_floor(
    results: list[SearchResult],
    min_score: float = 0.0,
    min_ratio: float = 0.0,
) -> list[SearchResult]:
    """Drop results that are not plausibly about the query.

    ``combine`` returns the top *k* by score unconditionally, so a query the
    corpus has nothing to say about still yields *k* passages — they are simply
    the least-bad of a bad set. Retrieval cannot express "nothing here"; this
    is what lets it.

    The units are what make an absolute cutoff meaningful. ``semantic_score``
    is exactly cosine similarity (see ``_compute_semantic_score``: the query
    and chunk vectors are both L2-normalised, so ``1 - dist/2`` reduces to
    ``cos``), ``lexical_score`` is TF-IDF cosine, and ``score`` is their
    weighted blend — all in [0, 1].

    Two gates, both of which a result must clear:

    * *min_score* — an absolute floor. This is the load-bearing one: for a
      genuinely out-of-domain query every candidate is weak, so a floor
      relative to the best of them lets the whole set through.
    * *min_ratio* — a floor relative to the top hit, for trimming the tail of
      an otherwise good result set.

    *results* MUST already be sorted by descending score (``combine`` sorts
    before returning). Both gates are therefore prefix truncations, and the
    return value is a prefix of the input — positions never move, which is
    what keeps ``sources[i]`` aligned with prompt block ``[i]`` downstream.

    Returns:
        A prefix of *results*. An empty list is a legitimate answer meaning
        "nothing was relevant", not an error.
    """
    if not results:
        return []

    # Disabled: return the input untouched rather than rebuilding it.
    if min_score <= 0.0 and min_ratio <= 0.0:
        return results

    cutoff = max(min_score, min_ratio * results[0].score)
    kept = [r for r in results if r.score >= cutoff]

    if len(kept) < len(results):
        logger.debug(
            "Relevance floor kept %d/%d results (cutoff %.4f, top %.4f).",
            len(kept),
            len(results),
            cutoff,
            results[0].score,
        )

    return kept
