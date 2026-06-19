"""Tests for the authoritative embedding provider factory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from web.services.search_engine import SearchEngine, SearchEngineConfig
from web.services.search_exceptions import EmbeddingError, SearchEngineError
from web.services.data_processing import DataProcessor
from web.utils.embedding_helpers import EmbeddingClientFactory, get_embedding_client
from web.utils.local_embedding_client import LocalEmbeddingClient
from web.utils.openai_client import OpenAIClientManager


class StubEmbeddingClient:
    embedding_dimension = 17

    def __init__(self, config=None):
        self.config = config or {}

    def get_embeddings(self, texts, batch_size=None):
        return []

    def get_embedding(self, text):
        return []


class BrokenEmbeddingClient:
    def __init__(self, config=None):
        raise OSError("model unavailable")


def test_factory_registers_supported_providers():
    assert EmbeddingClientFactory._clients["local"] is LocalEmbeddingClient
    assert EmbeddingClientFactory._clients["openai"] is OpenAIClientManager


def test_factory_selects_registered_provider():
    with patch.dict(
        EmbeddingClientFactory._clients,
        {"stub": StubEmbeddingClient},
        clear=True,
    ):
        client = get_embedding_client("stub", {"mode": "test"})

    assert isinstance(client, StubEmbeddingClient)
    assert client.config == {"mode": "test"}


def test_factory_rejects_unsupported_provider():
    with patch.dict(
        EmbeddingClientFactory._clients,
        {"stub": StubEmbeddingClient},
        clear=True,
    ):
        with pytest.raises(ValueError, match="Unsupported embedding type"):
            get_embedding_client("missing")


def test_factory_chains_provider_initialization_error():
    with patch.dict(
        EmbeddingClientFactory._clients,
        {"broken": BrokenEmbeddingClient},
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="Could not initialize") as exc_info:
            get_embedding_client("broken")

    assert isinstance(exc_info.value.__cause__, OSError)


def test_search_engine_chains_factory_failure():
    engine = SearchEngine.__new__(SearchEngine)
    engine._cfg = SearchEngineConfig(
        semantic_weight=0.7,
        lexical_weight=0.3,
        default_k=3,
        semantic_multiplier=3,
        lexical_multiplier=3,
        embedding_type="broken",
    )

    with patch(
        "web.services.search_engine.get_embedding_client",
        side_effect=RuntimeError("provider failed"),
    ):
        with pytest.raises(SearchEngineError, match="Failed to initialize") as exc_info:
            engine._build_embedding_client()

    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_data_processor_chains_factory_failure():
    with (
        patch(
            "web.services.data_processing.config.get",
            side_effect=lambda section, key, default=None: (
                "broken" if (section, key) == ("search_engine", "embedding_type") else default
            ),
        ),
        patch(
            "web.services.data_processing.get_embedding_client",
            side_effect=RuntimeError("provider failed"),
        ),
        pytest.raises(EmbeddingError, match="Failed to initialize") as exc_info,
    ):
        DataProcessor()

    assert isinstance(exc_info.value.__cause__, RuntimeError)
