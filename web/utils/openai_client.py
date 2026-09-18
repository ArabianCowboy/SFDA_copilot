import os

import numpy as np
from openai import OpenAI

from web.utils.config_loader import config as config_loader_module


class OpenAIClientManager:
    """
    Centralized manager for OpenAI client operations.
    Handles client initialization, configuration, and provides common methods.
    """

    def __init__(self, config=None):
        """Initialize the OpenAI client with configuration."""
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set.")

        # Use provided config or fall back to global config
        # config arg takes precedence if we ever want to inject it
        # The config argument is not currently used, but kept for future factory pattern integration.
        # Required, not defaulted: the old fallbacks named a different model
        # (text-embedding-ada-002) in a different dimension (1536) from the
        # configured all-mpnet-base-v2/768, so losing either key built the
        # corpus in the wrong vector space — an hour of embedding before
        # anything noticed.
        search_cfg = config_loader_module.get_section("search_engine")
        self.embedding_model = search_cfg["embedding_model"]
        self.embedding_dimension = search_cfg["embedding_dimension"]
        self.client = OpenAI()

    def get_embeddings(self, texts, batch_size=100):
        """
        Get embeddings for a list of texts in batches.

        Args:
            texts (list): List of texts to embed
            batch_size (int): Number of texts to process per batch

        Returns:
            list: List of embedding vectors
        """
        embeddings = np.empty((0, self.embedding_dimension), dtype=np.float32)

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]

            response = self.client.embeddings.create(model=self.embedding_model, input=batch_texts)
            batch_embeddings = np.array(
                [item.embedding for item in response.data], dtype=np.float32
            )
            embeddings = np.vstack([embeddings, batch_embeddings])

        return embeddings

    def get_embedding(self, text):
        """
        Get embedding for a single text.

        Args:
            text (str): Text to embed

        Returns:
            numpy.ndarray: The embedding vector
        """
        response = self.client.embeddings.create(model=self.embedding_model, input=text)
        embedding = response.data[0].embedding
        return np.array(embedding, dtype=np.float32).reshape(1, -1)
