import os
import numpy as np
from sentence_transformers import SentenceTransformer
from ..utils.config_loader import config


class LocalEmbeddingClient:
    """
    Client for local sentence-transformers embeddings.
    Uses the 'all-mpnet-base-v2' model by default.
    """
    
    def __init__(self):
        """Initialize the local embedding client."""
        self.model_name = config.get("search_engine", "local_embedding_model", "all-mpnet-base-v2")
        self.embedding_dimension = 768  # Fixed for all-mpnet-base-v2
        self.batch_size = config.get("data_processing", "embedding_batch_size", 100)
        
        try:
            self.model = SentenceTransformer(self.model_name)
        except Exception as e:
            raise ValueError(f"Failed to load sentence-transformers model {self.model_name}: {str(e)}")
    
    def get_embeddings(self, texts, batch_size=None):
        """
        Get embeddings for a list of texts.
        
        Args:
            texts (list): List of texts to embed
            batch_size (int, optional): Batch size for processing
            
        Returns:
            numpy.ndarray: Array of embeddings (n_texts, 768)
        """
        if not texts:
            return np.empty((0, self.embedding_dimension), dtype=np.float32)
            
        batch_size = batch_size or self.batch_size
        
        try:
            embeddings = self.model.encode(
                texts,
                batch_size=batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True
            )
            return embeddings.astype(np.float32)
        except Exception as e:
            print(f"Error generating embeddings: {str(e)}")
            # Return zero vectors on error
            return np.zeros((len(texts), self.embedding_dimension), dtype=np.float32)
    
    def get_embedding(self, text):
        """
        Get embedding for a single text.
        
        Args:
            text (str): Text to embed
            
        Returns:
            numpy.ndarray: The embedding vector (1, 768)
        """
        if not text:
            return np.zeros((1, self.embedding_dimension), dtype=np.float32)
            
        return self.get_embeddings([text])
