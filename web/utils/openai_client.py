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
        self.embedding_model = config_loader_module.get("search_engine", "embedding_model", "text-embedding-ada-002")
        self.embedding_dimension = config_loader_module.get("search_engine", "embedding_dimension", 1536)
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
            batch_texts = texts[i:i+batch_size]
            
            try:
                response = self.client.embeddings.create(
                    model=self.embedding_model,
                    input=batch_texts
                )
                batch_embeddings = np.array([item.embedding for item in response.data], dtype=np.float32)
                embeddings = np.vstack([embeddings, batch_embeddings])
            except Exception as e:
                print(f"Error getting embeddings for batch: {str(e)}")
                # Fallback to zero vectors
                zero_vectors = np.zeros((len(batch_texts), self.embedding_dimension), dtype=np.float32)
                embeddings = np.vstack([embeddings, zero_vectors])
        
        return embeddings
    
    def get_embedding(self, text):
        """
        Get embedding for a single text.
        
        Args:
            text (str): Text to embed
            
        Returns:
            numpy.ndarray: The embedding vector
        """
        try:
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            embedding = response.data[0].embedding
            return np.array(embedding, dtype=np.float32).reshape(1, -1)
        except Exception as e:
            print(f"Error getting embedding: {str(e)}")
            return np.zeros((1, self.embedding_dimension), dtype=np.float32)
