"""
Enhanced embedding client helpers with factory pattern and abstract interfaces.
Inspired by ChromaDB and LangChain best practices while maintaining backward compatibility.
"""

from typing import Union, Optional, Dict, Any, List
from abc import ABC, abstractmethod
import numpy as np
import logging

# Import existing clients
from .openai_client import OpenAIClientManager
from .local_embedding_client import LocalEmbeddingClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmbeddingClient(ABC):
    """
    Abstract base class for embedding providers - ChromaDB inspired.
    Provides a standard interface for all embedding implementations.
    """
    
    @abstractmethod
    def get_embeddings(self, texts: List[str], batch_size: Optional[int] = None) -> np.ndarray:
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
    
    _clients = {
        "openai": OpenAIClientManager,
        "local": LocalEmbeddingClient,
        # Future providers can be added here:
        # "voyage": VoyageAIClient,
        # "cohere": CohereClient,
    }
    
    @classmethod
    def create_client(cls, embedding_type: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> EmbeddingClient:
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
        except Exception as e:
            logger.error(f"Failed to create {embedding_type} embedding client: {str(e)}")
            raise
    
    @classmethod
    def get_available_providers(cls) -> List[str]:
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
def get_embedding_client(embedding_type: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> EmbeddingClient:
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


def get_embedding_dimension(embedding_type: Optional[str] = None) -> int:
    """
    Get embedding dimension with centralized configuration.
    Falls back to sensible defaults if configuration is not available.
    
    Args:
        embedding_type: Type of embedding provider
        
    Returns:
        int: Embedding dimension for the specified provider
    """
    try:
        # Try to get configuration from the config loader
        from .config_loader import ConfigLoader
        
        config_loader = ConfigLoader()
        config = config_loader.config
        
        # Get dimensions from centralized configuration
        dimensions = config.get("embedding", {}).get("dimensions", {})
        embedding_type = embedding_type or config.get("search_engine", {}).get("embedding_type", "local")
        
        return dimensions.get(embedding_type, 768)  # Default to local dimension
        
    except Exception as e:
        logger.warning(f"Failed to get embedding dimension from config: {str(e)}")
        # Fallback to hardcoded values
        fallback_dimensions = {"openai": 1536, "local": 768, "voyage": 1024, "cohere": 768}
        embedding_type = embedding_type or "local"
        return fallback_dimensions.get(embedding_type, 768)


def get_available_embedding_providers() -> List[str]:
    """
    Get list of available embedding providers.
    
    Returns:
        List[str]: List of available provider names
    """
    return EmbeddingClientFactory.get_available_providers()


# Decorator for safe embedding operations
def safe_embedding_operation(operation_name: str):
    """
    Decorator for safe embedding operations with error handling.
    Provides consistent error handling and logging across all embedding operations.
    
    Args:
        operation_name: Name of the operation for logging purposes
        
    Returns:
        Decorator function
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                context = f"{operation_name} in {func.__name__}"
                logger.error(f"Error in {context}: {str(e)}")
                
                # Return fallback if provided
                fallback = kwargs.get('fallback')
                if fallback is not None:
                    logger.info(f"Using fallback for {context}")
                    return fallback
                
                # Re-raise the exception if no fallback provided
                raise
        return wrapper
    return decorator