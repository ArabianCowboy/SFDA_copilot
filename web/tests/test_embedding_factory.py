"""Tests for the authoritative embedding provider factory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from web.services.data_processing import DataProcessor
from web.services.search_engine import SearchEngine, SearchEngineConfig
from web.services.search_exceptions import EmbeddingError, SearchEngineError
from web.utils.config_loader import ConfigLoader, config
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
    with (
        patch.dict(
            EmbeddingClientFactory._clients,
            {"stub": StubEmbeddingClient},
            clear=True,
        ),
        pytest.raises(ValueError, match="Unsupported embedding type"),
    ):
        get_embedding_client("missing")


def test_factory_chains_provider_initialization_error():
    with (
        patch.dict(
            EmbeddingClientFactory._clients,
            {"broken": BrokenEmbeddingClient},
            clear=True,
        ),
        pytest.raises(RuntimeError, match="Could not initialize") as exc_info,
    ):
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

    with (
        patch(
            "web.services.search_engine.get_embedding_client",
            side_effect=RuntimeError("provider failed"),
        ),
        pytest.raises(SearchEngineError, match="Failed to initialize") as exc_info,
    ):
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


# --- config.yaml owns these values; a fallback would be a second, silent opinion ---
#
# Until 2026-09-18 every key below also had an in-code default that disagreed with
# the shipped config.yaml. Deleting the key did not fail — it quietly swapped the
# fusion weights to 70/30, cut returned passages from 8 to 3, collapsed the
# candidate pool from 80 per arm to 9, and re-chunked the corpus at 7000/400
# instead of 5000/800. Same 200 OK, different answers. `from_yaml` had no test at
# all, which is why it went unnoticed.


@pytest.mark.parametrize(
    "key",
    ["semantic_weight", "lexical_weight", "k", "semantic_multiplier", "lexical_multiplier"],
)
def test_from_yaml_refuses_a_search_key_config_yaml_owns(monkeypatch, key):
    monkeypatch.delitem(config._config["search_engine"], key)
    with pytest.raises(SearchEngineError, match=key):
        SearchEngineConfig.from_yaml()


@pytest.mark.parametrize("key", ["chunk_size", "chunk_overlap"])
def test_data_processor_refuses_chunk_geometry_config_yaml_owns(monkeypatch, key):
    """Read before the embedding client, so this raises without loading a model."""
    monkeypatch.delitem(config._config["data_processing"], key)
    with pytest.raises(KeyError, match=key):
        DataProcessor()


@pytest.mark.parametrize(
    ("body", "kind"),
    [("", "NoneType"), ("just a string", "str"), ("- a\n- b", "list")],
)
def test_config_loader_refuses_a_config_that_is_not_a_mapping(tmp_path, body, kind):
    """Empty and stray-scalar files used to become `{}` and read as "all keys missing"."""
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    loader = ConfigLoader.__new__(ConfigLoader)  # bypass the singleton
    loader.config_path = path
    with pytest.raises(TypeError, match=kind):
        loader._load_config()


@pytest.mark.parametrize("key", ["embedding_model", "embedding_dimension"])
def test_openai_embedding_client_refuses_an_unstated_vector_space(monkeypatch, key):
    """The old fallbacks named ada-002/1536 against the configured mpnet/768."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    monkeypatch.delitem(config._config["search_engine"], key)
    with pytest.raises(KeyError, match=key):
        OpenAIClientManager()
