"""Authoritative construction helpers for embedding providers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import numpy as np

from web.utils.local_embedding_client import LocalEmbeddingClient
from web.utils.openai_client import OpenAIClientManager

logger = logging.getLogger(__name__)


class EmbeddingClient(ABC):
    """
    Abstract base class for embedding providers - ChromaDB inspired.
    Provides a standard interface for all embedding implementations.
    """

    @abstractmethod
    def get_embeddings(
        self,
        texts: list[str],
        batch_size: int | None = None,
    ) -> np.ndarray:
        """
        Get embeddings for a list of texts.

        Args:
            texts: List of texts to embed
            batch_size: Optional batch size for processing

        Returns:
            numpy.ndarray: Array of embeddings (n_texts, embedding_dimension)
        """
        pass

    @abstractmethod
    def get_embedding(self, text: str) -> np.ndarray:
        """
        Get embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            numpy.ndarray: The embedding vector (1, embedding_dimension)
        """
        pass

    @property
    @abstractmethod
    def embedding_dimension(self) -> int:
        """
        Get the embedding dimension for this provider.

        Returns:
            int: Embedding dimension
        """
        pass


class EmbeddingClientFactory:
    """
    Factory pattern for embedding clients - Real Python inspired.
    Provides centralized creation and management of embedding clients.
    """

    _clients: ClassVar[dict[str, type]] = {
        "openai": OpenAIClientManager,
        "local": LocalEmbeddingClient,
        # Future providers can be added here:
        # "voyage": VoyageAIClient,
        # "cohere": CohereClient,
    }

    @classmethod
    def create_client(
        cls,
        embedding_type: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> EmbeddingClient:
        """
        Create embedding client with smart defaults and validation.

        Args:
            embedding_type: Type of embedding provider ('openai', 'local', etc.)
            config: Optional configuration dictionary

        Returns:
            EmbeddingClient: Instance of the requested embedding client

        Raises:
            ValueError: If embedding type is not supported
        """
        embedding_type = embedding_type or "local"

        if embedding_type not in cls._clients:
            available_providers = list(cls._clients.keys())
            raise ValueError(
                f"Unsupported embedding type: {embedding_type}. "
                f"Available providers: {available_providers}"
            )

        client_class = cls._clients[embedding_type]

        try:
            return client_class(config or {})
        except Exception as exc:
            logger.error(
                "Failed to create %s embedding client: %s",
                embedding_type,
                exc,
            )
            raise RuntimeError(
                f"Could not initialize '{embedding_type}' embedding provider."
            ) from exc

    @classmethod
    def get_available_providers(cls) -> list[str]:
        """
        Get list of available embedding providers.

        Returns:
            List[str]: List of available provider names
        """
        return list(cls._clients.keys())

    @classmethod
    def register_provider(cls, name: str, client_class: type) -> None:
        """
        Register a new embedding provider dynamically.

        Args:
            name: Name of the provider
            client_class: Class that implements EmbeddingClient interface
        """
        cls._clients[name] = client_class
        logger.info(f"Registered new embedding provider: {name}")


# Helper functions for backward compatibility
def get_embedding_client(
    embedding_type: str | None = None,
    config: dict[str, Any] | None = None,
) -> EmbeddingClient:
    """
    Legacy-compatible function with enhanced features.
    Provides the same interface as existing code while using new architecture.

    Args:
        embedding_type: Type of embedding provider
        config: Optional configuration dictionary

    Returns:
        EmbeddingClient: Instance of the embedding client
    """
    return EmbeddingClientFactory.create_client(embedding_type, config)


def get_available_embedding_providers() -> list[str]:
    """
    Get list of available embedding providers.

    Returns:
        List[str]: List of available provider names
    """
    return EmbeddingClientFactory.get_available_providers()
