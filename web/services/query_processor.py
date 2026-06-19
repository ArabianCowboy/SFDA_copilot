"""
Query processing — translation, term expansion, and embedding generation.

This module encapsulates all pre-processing that happens to a raw user query
before it enters the search pipeline: Arabic → English translation, pharma-
domain synonym expansion, and vector embedding.
"""

from __future__ import annotations

import logging
import re
from typing import Protocol

import numpy as np

from web.services.pharma_constants import PHARMA_TERMS_EXPANSION
from web.services.search_exceptions import EmbeddingError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embedding client protocol
# ---------------------------------------------------------------------------

class EmbeddingClientProtocol(Protocol):
    """Structural type for any embedding client.

    Any object exposing ``get_embedding(text) -> np.ndarray`` and an
    ``embedding_dimension: int`` attribute satisfies this protocol.
    """

    embedding_dimension: int

    def get_embedding(self, text: str) -> np.ndarray:
        """Return an embedding vector for *text*."""
        ...


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def expand_query(query: str) -> str:
    """Expand *query* with pharmaceutical synonyms based on exact word-boundary matches.

    The function scans the lower-cased query for every key in
    :data:`PHARMA_TERMS_EXPANSION`. When a match is found, the associated
    synonym list is appended to the query, broadening lexical coverage.

    Args:
        query: The original search query.

    Returns:
        The expanded query string.  If no terms matched, the original
        query is returned unchanged.
    """
    expanded_terms: set[str] = set()
    query_lower = query.lower()
    for term, related_terms in PHARMA_TERMS_EXPANSION.items():
        if re.search(rf"\b{re.escape(term)}\b", query_lower):
            expanded_terms.update(related_terms)

    if not expanded_terms:
        return query

    return f"{query} {' '.join(expanded_terms)}"


def contains_arabic(text: str) -> bool:
    """Return ``True`` if *text* contains at least one Arabic Unicode character."""
    return bool(re.search(r"[\u0600-\u06FF]", text))


# ---------------------------------------------------------------------------
# QueryProcessor
# ---------------------------------------------------------------------------

class QueryProcessor:
    """Pre-processes user queries for hybrid search.

    Responsibilities:
        1. Detect Arabic queries and translate them to English via the OpenAI
           chat API so that semantic & lexical search remain effective against
           the predominantly English corpus.
        2. Expand the (possibly translated) query with pharmaceutical synonyms
           for improved lexical recall.

    Args:
        embedding_client: A client that satisfies :class:`EmbeddingClientProtocol`.
        translation_client: An ``openai.OpenAI`` instance used for Arabic → English
            translation.  Pass ``None`` to disable translation.
    """

    # System prompt reused across translation calls.
    _TRANSLATION_SYSTEM_PROMPT: str = (
        "You are a professional regulatory translator. Translate the user's "
        "SFDA-related query from Arabic to English. Ensure you use correct "
        "English regulatory terminology (e.g., 'guidance', 'marketing "
        "authorization', 'SPC', 'PIL', 'packaging', etc.). Return only the "
        "direct English translation without any explanation, markdown, or "
        "extra text."
    )

    def __init__(
        self,
        embedding_client: EmbeddingClientProtocol,
        translation_client: object | None = None,
    ) -> None:
        self._embedding_client = embedding_client
        self._translation_client = translation_client

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def translate_query(self, query: str) -> str:
        """Translate an Arabic query to English.

        If the query does not contain Arabic characters or if no translation
        client was provided, the original query is returned unchanged.

        Args:
            query: The raw user query.

        Returns:
            The English translation (or the original query if untranslated).
        """
        if self._translation_client is None or not contains_arabic(query):
            return query

        try:
            response = self._translation_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": self._TRANSLATION_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                max_tokens=100,
                temperature=0.0,
            )
            translated: str = response.choices[0].message.content.strip()  # type: ignore[union-attr]
            logger.info("Translated query: '%s' → '%s'", query, translated)
            return translated
        except Exception as exc:
            logger.error("Translation failed for query '%s': %s", query, exc)
            return query  # fall back to the original

    # ------------------------------------------------------------------
    # Expansion
    # ------------------------------------------------------------------

    @staticmethod
    def expand_lexical_query(query: str) -> str:
        """Expand *query* with pharma-domain synonyms for lexical search.

        This is a thin wrapper around :func:`expand_query` provided as an
        instance method for API consistency.

        Args:
            query: The query to expand.

        Returns:
            The expanded query string.
        """
        return expand_query(query)

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def get_embedding(self, text: str) -> np.ndarray:
        """Generate a **unit-normalised** embedding vector for *text*.

        Normalisation ensures that cosine similarity and L2 distance in the
        FAISS index are directly comparable.

        Args:
            text: The text to embed.

        Returns:
            A normalised ``float32`` numpy array of shape ``(embedding_dim,)``.

        Raises:
            EmbeddingError: If *text* is empty or embedding generation fails.
        """
        if not text.strip():
            raise EmbeddingError("Cannot embed empty text.")

        try:
            raw_embedding = self._embedding_client.get_embedding(text)
        except Exception as exc:
            raise EmbeddingError(f"Embedding client failed: {exc}") from exc

        # --- Type coercion ---
        if not isinstance(raw_embedding, np.ndarray):
            if isinstance(raw_embedding, (list, tuple)):
                embedding = np.asarray(raw_embedding, dtype=np.float32)
            else:
                raise EmbeddingError(
                    f"Embedding client returned unexpected type: {type(raw_embedding)}"
                )
        else:
            embedding = raw_embedding.astype(np.float32)

        # --- L2 normalisation ---
        norm = float(np.linalg.norm(embedding))
        if norm == 0.0:
            logger.warning(
                "Embedding for '%s…' has zero norm; returning as-is.", text[:50],
            )
            return embedding

        return embedding / norm