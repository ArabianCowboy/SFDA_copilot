"""An infrastructure failure must not read as "the corpus has nothing".

Each retrieval layer used to catch its own exceptions and return an empty
candidate list. That is indistinguishable from a successful search that
matched nothing — and empty is load-bearing: it makes ``_prepare_context``
tell the model no relevant information was found, so the model refuses.

The result was that a broken index, an unreadable vectorizer or a translation
outage reached the reader as a fluent, sourceless "I cannot answer based on
the given information" — the one message that should mean the corpus was
searched and had nothing to say.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from web.services.lexical_searcher import LexicalSearcher
from web.services.query_processor import QueryProcessor
from web.services.search_exceptions import QueryTranslationError, SearchEngineError
from web.services.semantic_searcher import SemanticSearcher


def frame(rows: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "category": ["regulatory"] * rows,
            "chunk_id": [f"c{i}" for i in range(rows)],
            "text": [f"passage {i}" for i in range(rows)],
        }
    )


# ── Semantic ────────────────────────────────────────────────────────────────

def test_a_failing_faiss_index_raises_rather_than_returning_nothing():
    index = MagicMock()
    index.ntotal = 3
    index.search.side_effect = RuntimeError("index corrupt")

    searcher = SemanticSearcher(index, frame())

    with pytest.raises(SearchEngineError, match="Semantic search failed"):
        searcher.search(np.zeros((1, 8), dtype="float32"), category="all", k=3)


# ── Lexical ─────────────────────────────────────────────────────────────────

def test_a_failing_vectorizer_raises_rather_than_returning_nothing():
    vectorizer = MagicMock()
    vectorizer.transform.side_effect = RuntimeError("vectorizer unreadable")

    searcher = LexicalSearcher(vectorizer, MagicMock(), frame())

    with pytest.raises(SearchEngineError, match="Lexical search failed"):
        searcher.search("registration requirements", category="all", k=3)


def test_an_empty_category_is_still_a_legitimate_empty_result():
    """The distinction the raise above must not blur.

    No document in a category is a real answer to the question asked. Only a
    broken component is an error.
    """
    vectorizer = MagicMock()
    vectorizer.transform.return_value = np.zeros((1, 4))

    data = frame()
    data["category"] = ["pharmacovigilance"] * len(data)
    searcher = LexicalSearcher(vectorizer, np.zeros((len(data), 4)), data)

    assert searcher.search("anything", category="veterinary", k=3) == []


# ── Translation ─────────────────────────────────────────────────────────────

def test_a_translation_outage_raises_rather_than_querying_in_arabic():
    """Falling back to the untranslated query is not a graceful degradation.

    The index is English. An Arabic query embedded as-is retrieves near-noise,
    which — with no relevance floor configured — still returns k passages the
    model can make nothing of, so it refuses. The reader is told their
    question has no answer in the corpus when the translator was simply down.
    """
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("upstream 503")

    processor = QueryProcessor(embedding_client=MagicMock(), translation_client=client)

    with pytest.raises(QueryTranslationError):
        processor.translate_query("ما هي متطلبات التسجيل")


def test_an_english_query_never_reaches_the_translator():
    """No Arabic, no translation, no way for its failure to matter."""
    client = MagicMock()
    client.chat.completions.create.side_effect = AssertionError("must not be called")

    processor = QueryProcessor(embedding_client=MagicMock(), translation_client=client)

    assert processor.translate_query("registration requirements") == (
        "registration requirements"
    )


def test_no_translation_client_leaves_the_query_untouched():
    """Deployments without a key are a configuration state, not a failure."""
    processor = QueryProcessor(embedding_client=MagicMock(), translation_client=None)
    assert processor.translate_query("ما هي متطلبات التسجيل") == "ما هي متطلبات التسجيل"


# ── The property all of the above exist to protect ──────────────────────────

def test_a_failure_is_distinguishable_from_an_empty_result():
    """Both layers now signal the difference the routes depend on."""
    index = MagicMock()
    index.ntotal = 0
    index.search.return_value = (np.array([[]]), np.array([[]]))

    # A search that genuinely matched nothing still returns an empty list...
    assert SemanticSearcher(index, frame()).search(
        np.zeros((1, 8), dtype="float32"), category="all", k=3
    ) == []

    # ...while a broken one raises.
    index.search.side_effect = RuntimeError("boom")
    with pytest.raises(SearchEngineError):
        SemanticSearcher(index, frame()).search(
            np.zeros((1, 8), dtype="float32"), category="all", k=3
        )
