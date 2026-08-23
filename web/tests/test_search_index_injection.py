"""Tests for SearchIndex embedding client injection, manifest validation, and local embedding client caching."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from huggingface_hub.utils import LocalEntryNotFoundError

from web.services import build_registry
from web.services.search_engine import SearchEngine, SearchEngineConfig
from web.services.search_exceptions import ManifestValidationError
from web.services.search_index import SearchIndex, SearchIndexConfig
from web.utils.local_embedding_client import LocalEmbeddingClient


class InjectedStubEmbeddingClient:
    """Stub embedding client for injection testing."""

    def __init__(self, dimension: int = 768, model_name: str = "all-mpnet-base-v2"):
        self.embedding_dimension = dimension
        self.model_name = model_name

    def get_embeddings(self, texts, batch_size=None):
        return []

    def get_embedding(self, text):
        return []


@pytest.fixture
def index_config(tmp_path: Path) -> SearchIndexConfig:
    return SearchIndexConfig(
        processed_data_dir=str(tmp_path),
        faiss_index_path=str(tmp_path / "faiss_index.bin"),
        dataframe_path=str(tmp_path / "chunks_data.csv"),
        tfidf_vectorizer_path=str(tmp_path / "tfidf_vectorizer.pkl"),
        tfidf_matrix_path=str(tmp_path / "tfidf_matrix.pkl"),
    )


@pytest.fixture
def build_dir_with_manifest(tmp_path: Path) -> Path:
    build_dir = tmp_path / "builds" / "test_build"
    build_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "build_id": "test_build",
        "embedding_dimension": 768,
        "embedding_model_name": "all-mpnet-base-v2",
        "embedding_type": "local",
        "extraction_chunking_version": "v1",
    }
    manifest_path = build_dir / build_registry.MANIFEST_NAME
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    return build_dir


# ──────────────────────────────────────────────────────────────────────────
# FIX 4a: SearchIndex embedding_client injection
# ──────────────────────────────────────────────────────────────────────────


def test_search_index_uses_injected_client_without_calling_factory(
    index_config: SearchIndexConfig,
    build_dir_with_manifest: Path,
):
    stub_client = InjectedStubEmbeddingClient(dimension=768, model_name="all-mpnet-base-v2")
    index = SearchIndex(index_config, embedding_client=stub_client)
    index._active_build_dir = build_dir_with_manifest

    with patch("web.services.search_index.get_embedding_client") as mock_get_client:
        index._validate_manifest()
        mock_get_client.assert_not_called()


def test_search_index_falls_back_to_factory_when_no_client_injected(
    index_config: SearchIndexConfig,
    build_dir_with_manifest: Path,
):
    stub_client = InjectedStubEmbeddingClient(dimension=768, model_name="all-mpnet-base-v2")
    index = SearchIndex(index_config, embedding_client=None)
    index._active_build_dir = build_dir_with_manifest

    with patch(
        "web.services.search_index.get_embedding_client", return_value=stub_client
    ) as mock_get_client:
        index._validate_manifest()
        mock_get_client.assert_called_once_with("local")


def test_search_engine_wires_embedding_client_to_search_index():
    cfg = SearchEngineConfig(
        semantic_weight=0.7,
        lexical_weight=0.3,
        default_k=3,
        semantic_multiplier=3,
        lexical_multiplier=3,
        embedding_type="stub",
    )
    stub_client = InjectedStubEmbeddingClient(dimension=768, model_name="all-mpnet-base-v2")

    with (
        patch.object(SearchEngineConfig, "from_yaml", return_value=cfg),
        patch.object(SearchEngine, "_build_translation_client", return_value=None),
        patch.object(SearchEngine, "_build_embedding_client", return_value=stub_client),
    ):
        engine = SearchEngine()
        assert engine._embedding_client is stub_client
        assert engine._index._injected_embedding_client is stub_client


# ──────────────────────────────────────────────────────────────────────────
# FIX 4b: Manifest mismatch detection with injected client
# ──────────────────────────────────────────────────────────────────────────


def test_manifest_dimension_mismatch_raises_validation_error(
    index_config: SearchIndexConfig,
    build_dir_with_manifest: Path,
):
    # Manifest has 768, stub client has 384
    stub_client = InjectedStubEmbeddingClient(dimension=384, model_name="all-mpnet-base-v2")
    index = SearchIndex(index_config, embedding_client=stub_client)
    index._active_build_dir = build_dir_with_manifest

    with pytest.raises(ManifestValidationError, match="embedding_dimension mismatch"):
        index._validate_manifest()


def test_manifest_model_name_mismatch_raises_validation_error(
    index_config: SearchIndexConfig,
    build_dir_with_manifest: Path,
):
    # Manifest has "all-mpnet-base-v2", stub client has "all-MiniLM-L6-v2"
    stub_client = InjectedStubEmbeddingClient(dimension=768, model_name="all-MiniLM-L6-v2")
    index = SearchIndex(index_config, embedding_client=stub_client)
    index._active_build_dir = build_dir_with_manifest

    with pytest.raises(ManifestValidationError, match="embedding_model_name mismatch"):
        index._validate_manifest()


def test_manifest_embedding_type_mismatch_raises_validation_error(
    index_config: SearchIndexConfig,
    tmp_path: Path,
):
    build_dir = tmp_path / "builds" / "openai_build"
    build_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "build_id": "openai_build",
        "embedding_dimension": 768,
        "embedding_model_name": "text-embedding-3-small",
        "embedding_type": "openai",
        "extraction_chunking_version": "v1",
    }
    with open(build_dir / build_registry.MANIFEST_NAME, "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    # Config is 'local', manifest is 'openai'
    stub_client = InjectedStubEmbeddingClient(dimension=768, model_name="text-embedding-3-small")
    index = SearchIndex(index_config, embedding_client=stub_client)
    index._active_build_dir = build_dir

    with (
        patch("web.services.search_index.config.get", return_value="local"),
        pytest.raises(ManifestValidationError, match="embedding_type mismatch"),
    ):
        index._validate_manifest()


def test_missing_dimension_on_injected_client_raises_validation_error(
    index_config: SearchIndexConfig,
    build_dir_with_manifest: Path,
):
    broken_client = object()
    index = SearchIndex(index_config, embedding_client=broken_client)
    index._active_build_dir = build_dir_with_manifest

    with pytest.raises(
        ManifestValidationError, match="does not expose a usable embedding_dimension"
    ):
        index._validate_manifest()


# ──────────────────────────────────────────────────────────────────────────
# FIX 4c: LocalEmbeddingClient caching & fallback
# ──────────────────────────────────────────────────────────────────────────


def test_local_embedding_client_cached_model_loads_successfully():
    with patch("web.utils.local_embedding_client.SentenceTransformer") as mock_st:
        mock_model = MagicMock()
        mock_model.get_embedding_dimension.return_value = 768
        mock_st.return_value = mock_model

        client = LocalEmbeddingClient()

        # Must attempt local_files_only=True first and succeed
        mock_st.assert_called_once_with(client.model_name, local_files_only=True)
        assert client.embedding_dimension == 768
        assert client.model is mock_model


def test_local_embedding_client_not_cached_falls_back_to_online():
    with patch("web.utils.local_embedding_client.SentenceTransformer") as mock_st:
        mock_model = MagicMock()
        mock_model.get_embedding_dimension.return_value = 768
        mock_st.side_effect = [
            LocalEntryNotFoundError("Model not found in cache"),
            mock_model,
        ]

        client = LocalEmbeddingClient()

        # Must call SentenceTransformer twice: first local_files_only=True, then default/online
        assert mock_st.call_count == 2
        assert mock_st.call_args_list[0] == ((client.model_name,), {"local_files_only": True})
        assert mock_st.call_args_list[1] == ((client.model_name,), {})
        assert client.embedding_dimension == 768
        assert client.model is mock_model


def test_local_embedding_client_corrupted_cache_does_not_silently_retry_online():
    with patch("web.utils.local_embedding_client.SentenceTransformer") as mock_st:
        mock_st.side_effect = OSError("Corrupted checkpoint or disk error")

        with pytest.raises(
            ValueError, match="Failed to load sentence-transformers model"
        ) as exc_info:
            LocalEmbeddingClient()

        # SentenceTransformer must be called ONLY once; no second/online attempt should occur
        assert mock_st.call_count == 1
        assert "Corrupted checkpoint or disk error" in str(exc_info.value)


def test_search_index_load_uses_injected_client_without_calling_factory(
    index_config: SearchIndexConfig,
    build_dir_with_manifest: Path,
):
    stub_client = InjectedStubEmbeddingClient(dimension=768, model_name="all-mpnet-base-v2")
    index = SearchIndex(index_config, embedding_client=stub_client)

    with (
        patch.object(index, "_resolve_paths", return_value=None),
        patch.object(index, "_check_files_exist", return_value=None),
        patch.object(index, "_load_faiss_index", return_value=None),
        patch.object(index, "_load_dataframe", return_value=None),
        patch.object(index, "_load_tfidf_vectorizer", return_value=None),
        patch.object(index, "_load_tfidf_matrix", return_value=None),
        patch.object(index, "_validate_dimensions", return_value=None),
        patch("web.services.search_index.get_embedding_client") as mock_get_client,
    ):
        index._active_build_dir = build_dir_with_manifest
        index.load()
        assert index.is_loaded is True
        mock_get_client.assert_not_called()


def test_noisy_third_party_loggers_configured_to_warning():
    import logging

    for name in ("httpx", "httpcore", "huggingface_hub"):
        assert logging.getLogger(name).level == logging.WARNING
