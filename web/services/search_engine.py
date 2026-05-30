import os
import re
import numpy as np
import pandas as pd
import faiss
import pickle
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
from sklearn.metrics.pairwise import cosine_similarity
# MinMaxScaler is available but not currently used for normalization in this implementation
# from sklearn.preprocessing import MinMaxScaler 

from ..utils.config_loader import config, project_root
from ..utils.openai_client import OpenAIClientManager
from ..utils.local_embedding_client import LocalEmbeddingClient

# Configure logger for this module
logger = logging.getLogger(__name__)

PHARMA_TERMS_EXPANSION: Dict[str, List[str]] = {
    "side effects": ["adverse events", "adverse reactions", "safety concerns", "undesirable effects"],
    "dosage": ["dose", "administration", "regimen", "dosing schedule", "posology"],
    "safety": ["toxicity", "contraindications", "warnings", "precautions", "safety profile"],
    "monitoring": ["surveillance", "observation", "follow-up", "patient monitoring", "safety monitoring"],
    "reporting": ["notification", "documentation", "submission", "adverse event reporting", "case reporting"],
    "signal": ["alert", "indication", "warning signal", "safety signal", "potential risk"],
    "risk": ["hazard", "danger", "exposure", "potential harm", "risk factor"],
    "risk management": ["risk mitigation", "risk assessment", "risk control", "risk evaluation", "RMP", "risk management plan"],
    "audit": ["compliance review", "internal audit", "regulatory audit", "process audit", "inspection readiness"],
    "inspection": ["site visit", "regulatory inspection", "compliance check", "audit review", "facility inspection"],
    "compliance": ["adherence", "conformity", "obedience", "compliance monitoring", "regulatory compliance"],
    "pv": ["pharmacovigilance", "drug safety", "medicine surveillance", "post-marketing safety"],
    "lack of efficacy": ["ineffectiveness", "insufficient response", "suboptimal efficacy", "treatment failure"],
    "quality": ["good manufacturing practices", "GMP", "quality control", "QC", "quality assurance", "QA", "product quality"],
    "adverse event": ["adverse reaction", "side effect", "negative reaction", "AE", "ADR", "undesired effect"],
    "clinical trial": ["clinical study", "clinical research", "clinical investigation", "interventional study", "trial protocol"],
    "drug interaction": ["medication interaction", "pharmaceutical interaction", "medicine interaction", "DDI"],
    "registration": ["marketing authorization", "MA", "drug approval", "product license", "registration process"],
    "labeling": ["SPC", "summary of product characteristics", "PIL", "patient information leaflet", "product label", "package insert"],
    "variation": ["post-approval change", "variation application", "label update", "manufacturing change"],
    "gmp": ["good manufacturing practices", "manufacturing standards", "quality systems", "facility compliance"],
    "gvp": ["good pharmacovigilance practices", "pv system", "pharmacovigilance guidelines", "drug safety standards"],
}

def preprocess_query(query: str) -> str:
    """Expand the query with pharmaceutical synonyms based on exact word boundaries."""
    expanded_terms = set()
    query_lower = query.lower()
    for term, related_terms in PHARMA_TERMS_EXPANSION.items():
        if re.search(rf"\b{re.escape(term)}\b", query_lower):
            expanded_terms.update(related_terms)

    if not expanded_terms:
        return query

    return f"{query} {' '.join(expanded_terms)}"


@dataclass(frozen=True) # Make immutable for safety
class SearchResult:
    """
    Represents a single search result item with content and metadata.
    
    Attributes:
        text (str): The text content of the search result chunk.
        score (float): The final combined hybrid score (higher is better).
        document (str): The source document name.
        category (str): The category of the source document.
        page (Optional[int]): The page number in the source document (if available).
        chunk_id (Optional[str]): A unique identifier for this text chunk.
        metadata (Dict[str, Any]): Additional metadata, e.g., individual semantic/lexical scores.
    """
    text: str
    score: float
    document: str
    category: str
    page: Optional[int] = None
    chunk_id: Optional[str] = None 
    metadata: Dict[str, Any] = field(default_factory=dict) 

class ImprovedSearchEngine:
    """
    Implements a hybrid search strategy combining semantic (vector-based) 
    and lexical (keyword-based) search methods over a corpus of text chunks.
    
    It uses FAISS for efficient semantic search and TF-IDF for lexical search.
    Results are combined using a weighted score, and filtering by category is supported.
    Configuration parameters (paths, weights, k) are loaded via the central config loader.
    """
    
    def __init__(self) -> None:
        """
        Initializes the ImprovedSearchEngine by setting up paths, loading configuration,
        and triggering the loading of data models (FAISS index, DataFrame, TF-IDF).
        """
        logger.info("Initializing ImprovedSearchEngine...")
        # Load paths from config with defaults
        self.processed_data_dir: str = os.path.join(project_root, config.get("paths", "processed_data", "web/processed_data"))
        logger.debug(f"Project root: {project_root}")
        logger.debug(f"Processed data directory: {self.processed_data_dir}")
        self.faiss_index_path: str = os.path.join(self.processed_data_dir, config.get("filenames", "faiss_index", "faiss_index.bin"))
        self.dataframe_path: str = os.path.join(self.processed_data_dir, config.get("filenames", "chunks_data", "chunks_data.csv"))
        self.tfidf_path: str = os.path.join(self.processed_data_dir, config.get("filenames", "tfidf_vectorizer", "tfidf_vectorizer.pkl"))
        self.tfidf_matrix_path: str = os.path.join(self.processed_data_dir, config.get("filenames", "tfidf_matrix", "tfidf_matrix.pkl"))
        logger.debug(f"FAISS index path: {self.faiss_index_path}")
        logger.debug(f"DataFrame path: {self.dataframe_path}")
        logger.debug(f"TF-IDF vectorizer path: {self.tfidf_path}")
        logger.debug(f"TF-IDF matrix path: {self.tfidf_matrix_path}")

        # Initialize translation client if API key is present
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            try:
                from openai import OpenAI
                self.translation_client = OpenAI(api_key=api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize translation client: {str(e)}")
                self.translation_client = None
        else:
            self.translation_client = None
        
        # --- Initialize Embedding Client ---
        # ENHANCED: Use factory pattern while preserving existing logic
        try:
            from ..utils.embedding_helpers import get_embedding_client, get_embedding_dimension
            
            self.embedding_client = get_embedding_client(
                config.get("search_engine", "embedding_type", "local")
            )
            self.embedding_dimension = get_embedding_dimension(
                config.get("search_engine", "embedding_type", "local")
            )
            
            logger.info(f"Using enhanced embedding client: {type(self.embedding_client).__name__}")
            
        except Exception as e:
            # FALLBACK: Maintain existing behavior for backward compatibility
            logger.warning(f"Enhanced embedding client initialization failed: {str(e)}. Falling back to legacy logic.")
            embedding_type: str = config.get("search_engine", "embedding_type", "local")
            logger.info(f"Using embedding type: {embedding_type}")
            if embedding_type == "openai":
                self.embedding_client = OpenAIClientManager()
                self.embedding_dimension = self.embedding_client.embedding_dimension
            else: # Default to local
                self.embedding_client = LocalEmbeddingClient()
                self.embedding_dimension = self.embedding_client.embedding_dimension

        # --- Category Mapping for Robust Matching ---
        # This map helps translate simplified frontend categories to their expected full names
        # found in the processed data (e.g., directory names).
        # This map is not strictly used for direct lookup in the current implementation,
        # but serves as a reference for expected category names and can be expanded
        # if more complex mapping logic is required in the future.
        self.category_map = {
            "biological": "biological_products_and_quality_control",
            "veterinary": "veterinary_medicines",
            "pharmacovigilance": "pharmacovigilance",
            "regulatory": "regulatory",
            "all": "all" # Special case for no category filtering
        }

        # --- Initialize Data Attributes ---
        # Type hints for clarity
        self.faiss_index: Optional[faiss.Index] = None 
        self.df: Optional[pd.DataFrame] = None
        self.tfidf_vectorizer: Optional[Any] = None # Type depends on sklearn version
        self.tfidf_matrix: Optional[Any] = None # Type depends on sklearn version (sparse matrix)
        self.initialized: bool = False
        
        # --- Load Hybrid Search Weights ---
        self.semantic_weight: float = config.get("search_engine", "semantic_weight", 0.7)
        self.lexical_weight: float = config.get("search_engine", "lexical_weight", 0.3)
        # Ensure weights sum roughly to 1 (or normalize if needed)
        if not np.isclose(self.semantic_weight + self.lexical_weight, 1.0):
             logger.warning(f"Hybrid search weights (semantic={self.semantic_weight}, lexical={self.lexical_weight}) do not sum to 1.")
        logger.info(f"Hybrid search weights: Semantic={self.semantic_weight}, Lexical={self.lexical_weight}")

        # --- Trigger Initialization ---
        self.initialize()

    def is_initialized(self) -> bool:
        """Checks if the search engine has successfully loaded its data models."""
        if not self.initialized:
             logger.warning("Search engine accessed before initialization.")
        return self.initialized

    def initialize(self) -> None:
        """
        Loads the necessary data models (FAISS index, DataFrame, TF-IDF vectorizer and matrix) 
        from disk. Sets the `initialized` flag upon successful loading and validation.
        Logs errors if loading fails or data inconsistencies are found.
        """
        if self.initialized:
            logger.debug("Search engine already initialized.") # Use debug level for repeated checks
            return
        try:
            logger.info("Starting search engine initialization...")
            # Check if all required processed data files exist
            required_files: List[str] = [self.faiss_index_path, self.dataframe_path, self.tfidf_path, self.tfidf_matrix_path]
            logger.debug(f"Checking for required files: {required_files}")
            if not all(os.path.exists(f) for f in required_files):
                missing = [f for f in required_files if not os.path.exists(f)]
                logger.error(f"Processed data files missing: {missing}. Cannot initialize search engine. Please run data processing first.")
                self.initialized = False
                return
            logger.info("All required processed data files found.")

            # --- Load FAISS Index ---
            logger.info(f"Attempting to load FAISS index from: {self.faiss_index_path}")
            try:
                self.faiss_index = faiss.read_index(self.faiss_index_path)
                if self.faiss_index: # Add check for None
                    logger.info(f"FAISS index loaded successfully with {self.faiss_index.ntotal} vectors.")
            except Exception as faiss_e:
                logger.error(f"Failed to load FAISS index from {self.faiss_index_path}: {faiss_e}")
                self.initialized = False
                return
            
            # --- Load DataFrame ---
            logger.info(f"Attempting to load DataFrame from: {self.dataframe_path}")
            try:
                self.df = pd.read_csv(self.dataframe_path)
                logger.info(f"DataFrame loaded successfully with {len(self.df)} rows.")
            except Exception as df_e:
                logger.error(f"Failed to load DataFrame from {self.dataframe_path}: {df_e}")
                self.initialized = False
                return

            # Ensure required columns exist
            required_cols: List[str] = ['text', 'document', 'category', 'page', 'chunk_id']
            logger.debug(f"Checking DataFrame for required columns: {required_cols}")
            if not all(col in self.df.columns for col in required_cols):
                 missing_cols = [col for col in required_cols if col not in self.df.columns]
                 logger.error(f"DataFrame missing required columns: {missing_cols}. Initialization failed.")
                 self.initialized = False
                 return
            logger.debug("DataFrame contains all required columns.")
            # Handle potential NaN values in critical text fields
            self.df['text'] = self.df['text'].fillna('')
            logger.debug("DataFrame text column NaN values filled.")
            
            # --- Load TF-IDF Vectorizer and Matrix ---
            logger.info(f"Attempting to load TF-IDF vectorizer from: {self.tfidf_path}")
            try:
                with open(self.tfidf_path, 'rb') as f:
                    self.tfidf_vectorizer = pickle.load(f)
                logger.info("TF-IDF vectorizer loaded successfully.")
            except Exception as tfidf_vec_e:
                logger.error(f"Failed to load TF-IDF vectorizer from {self.tfidf_path}: {tfidf_vec_e}")
                self.initialized = False
                return
            
            logger.info(f"Attempting to load TF-IDF matrix from: {self.tfidf_matrix_path}")
            try:
                with open(self.tfidf_matrix_path, 'rb') as f:
                    self.tfidf_matrix = pickle.load(f)
                if self.tfidf_matrix is not None: # Add check for None
                    logger.info(f"TF-IDF matrix loaded successfully with shape: {self.tfidf_matrix.shape}")
            except Exception as tfidf_mat_e:
                logger.error(f"Failed to load TF-IDF matrix from {self.tfidf_matrix_path}: {tfidf_mat_e}")
                self.initialized = False
                return
            
            # --- Verify Dimensions Match ---
            df_len = len(self.df) if self.df is not None else 0
            tfidf_rows = self.tfidf_matrix.shape[0] if self.tfidf_matrix is not None else 0
            faiss_vectors = self.faiss_index.ntotal if self.faiss_index is not None else 0
            
            logger.info(f"Verifying data dimensions: DataFrame rows={df_len}, TF-IDF matrix rows={tfidf_rows}, FAISS vectors={faiss_vectors}")
            if not (tfidf_rows == df_len and faiss_vectors == df_len):
                 logger.error(
                     f"Data dimension mismatch: DataFrame rows ({df_len}), "
                     f"TF-IDF matrix rows ({tfidf_rows}), "
                     f"FAISS index vectors ({faiss_vectors}). "
                     "Ensure all processed data corresponds to the same dataset. Initialization failed."
                 )
                 self.initialized = False
                 # Clear loaded data to prevent partial state
                 self.faiss_index = None
                 self.df = None
                 self.tfidf_vectorizer = None
                 self.tfidf_matrix = None
                 return
            logger.info("Data dimensions verified successfully.")

            # --- Set Initialized Flag ---
            self.initialized = True
            logger.info("Search engine initialized successfully.")
        
        except Exception as e:
            logger.exception(f"Critical error during search engine initialization: {str(e)}")
            self.initialized = False
            # Ensure potentially partially loaded data is cleared
            self.faiss_index = None
            self.df = None
            self.tfidf_vectorizer = None
            self.tfidf_matrix = None

    def get_embedding(self, text: str) -> Optional[np.ndarray]:
        """
        Generates a normalized embedding vector for the given text using the configured client.

        Normalization ensures that vector comparisons (like cosine similarity or L2 distance 
        in FAISS) are meaningful. It scales the vector to have a unit length (magnitude of 1).

        Args:
            text (str): The input text to embed.

        Returns:
            Optional[np.ndarray]: A normalized numpy array (float32) representing the embedding, 
                                  or None if embedding generation fails or text is empty.
        """
        if not text: # Handle empty input
             logger.warning("Attempted to get embedding for empty text.")
             return None
        try:
            # Call the embedding client (local or OpenAI)
            embedding = self.embedding_client.get_embedding(text)
            
            # --- Type Validation and Conversion ---
            # Ensure the result is a numpy array for consistent processing
            if not isinstance(embedding, np.ndarray):
                 if isinstance(embedding, (list, tuple)):
                      # Convert list/tuple to numpy array
                      embedding = np.array(embedding, dtype=np.float32) 
                 else:
                      # Log error if the type is unexpected
                      logger.error(f"Embedding client returned unexpected type: {type(embedding)}")
                      return None
                      
            # --- Vector Normalization ---
            # Calculate the L2 norm (magnitude) of the vector
            norm = np.linalg.norm(embedding)
            
            # Handle zero vectors: Avoid division by zero. 
            # A zero vector might indicate an issue or represent empty/padding content.
            if norm == 0:
                 logger.warning(f"Embedding for text '{text[:50]}...' resulted in zero norm. Returning zero vector.")
                 # Return the zero vector itself. Downstream processing should be aware of this possibility.
                 return embedding 
                 
            # Normalize by dividing the vector by its norm
            normalized_embedding: np.ndarray = embedding / norm
            logger.debug(f"Generated normalized embedding for text: '{text[:50]}...'")
            return normalized_embedding
            
        except Exception as e:
            # Log any exception during the embedding process
            logger.exception(f"Error getting embedding for text: '{text[:100]}...' - {str(e)}")
            return None # Return None to indicate failure

    def _translate_query(self, query: str) -> str:
        """Translate Arabic query to English to ensure maximum lexical & semantic compatibility with the English corpus."""
        if not hasattr(self, "translation_client") or not self.translation_client:
            return query
        
        # Check if the query contains Arabic characters
        if not re.search(r"[\u0600-\u06FF]", query):
            return query
            
        try:
            response = self.translation_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a professional regulatory translator. Translate the user's SFDA-related query from Arabic to English. "
                            "Ensure you use correct English regulatory terminology (e.g., 'guidance', 'marketing authorization', 'SPC', 'PIL', 'packaging', etc.). "
                            "Return only the direct English translation without any explanation, markdown, or extra text."
                        )
                    },
                    {"role": "user", "content": query}
                ],
                max_tokens=100,
                temperature=0.0
            )
            translated_query = response.choices[0].message.content.strip()
            logger.info(f"Translated query: '{query}' -> '{translated_query}'")
            return translated_query
        except Exception as e:
            logger.error(f"Error translating query in search engine: {str(e)}")
            return query

    def search(self, query: str, category: str = "all", k: Optional[int] = None) -> List[SearchResult]:
        """
        Performs a hybrid search combining semantic and lexical results, filtered by category.

        Args:
            query (str): The user's search query.
            category (str): The category to filter results by ('regulatory', 'pharmacovigilance', or 'all'). 
                            Defaults to 'all'.
            k (Optional[int]): The final number of top results to return. If None, uses the value 
                               from the configuration file ('search_engine.k', default 3).

        Returns:
            List[SearchResult]: A list of SearchResult objects, ranked by the combined hybrid score. 
                                Returns an empty list if the engine is not initialized or an error occurs.
        """
        if not self.is_initialized():
            logger.error("Search called but engine is not initialized.")
            return [] # Return empty list if not initialized

        logger.info(f"Performing hybrid search for query: '{query[:100]}...', category: {category}, k: {k}")

        try:
            # --- Parameter Setup ---
            # Use k from config if not specified in call, ensuring it's at least 1
            final_k: int = k if k is not None else config.get("search_engine", "k", 3)
            final_k = max(1, final_k) 

            # Get multipliers from config for fetching *initial* candidates
            semantic_multiplier: int = config.get("search_engine", "semantic_multiplier", 3) 
            lexical_multiplier: int = config.get("search_engine", "lexical_multiplier", 3) 
            semantic_k_candidates: int = max(final_k, 1) * semantic_multiplier
            lexical_k_candidates: int = max(final_k, 1) * lexical_multiplier

            # --- Translate Arabic Queries to English for Retrieval ---
            # Since the corpus is mostly in English, translating the query to English
            # ensures maximum semantic and lexical overlap during search.
            retrieval_query = self._translate_query(query)

            # --- Preprocess Query for Lexical Search ONLY ---
            lexical_query = preprocess_query(retrieval_query)
            logger.debug(f"Lexical query after expansion: '{lexical_query[:100]}...'")

            # --- Get Query Embedding using clean retrieval query ---
            query_embedding = self.get_embedding(retrieval_query)
            if query_embedding is None:
                 logger.error("Failed to get query embedding. Aborting search.")
                 return []
            # Reshape for FAISS search (expects a 2D array)
            query_embedding_faiss = query_embedding.reshape(1, -1).astype('float32')

            # --- Perform Semantic Search ---
            logger.debug(f"Fetching {semantic_k_candidates} semantic candidates...")
            semantic_results_raw: List[Dict] = self._semantic_search(query_embedding_faiss, category, k=semantic_k_candidates)
            
            # --- Perform Lexical Search ---
            logger.debug(f"Fetching {lexical_k_candidates} lexical candidates...")
            lexical_results_raw: List[Dict] = self._lexical_search(lexical_query, category, k=lexical_k_candidates)
            
            # --- Combine and Rank Results ---
            logger.debug("Combining and ranking results...")
            combined_results: List[SearchResult] = self._combine_results(
                semantic_results_raw, 
                lexical_results_raw, 
                query_embedding=query_embedding,
                lexical_query=lexical_query,
                query_text=retrieval_query,
                final_k=final_k
            )
            
            logger.info(f"Hybrid search completed. Returning {len(combined_results)} results.")
            return combined_results

        except Exception as e:
            # Catch any unexpected errors during the search process
            logger.exception(f"Unexpected error during search for query '{query[:100]}...': {str(e)}")
            return [] # Return empty list on error

    def _semantic_search(self, query_embedding: np.ndarray, category: str, k: int) -> List[Dict]:
        """
        Performs semantic search using the FAISS index and filters by category.

        Args:
            query_embedding (np.ndarray): The normalized query embedding vector (shape 1, D).
            category (str): The category to filter results by.
            k (int): The number of candidate results to fetch from FAISS.

        Returns:
            List[Dict]: A list of dictionaries, each containing the 'index' of the chunk in the 
                        DataFrame, the calculated semantic 'score' (similarity, 0-1), and 'chunk_id'.
        """
        results_raw: List[Dict] = []
        if self.faiss_index is None or self.df is None:
             logger.error("FAISS index or DataFrame not loaded during semantic search.")
             return results_raw
             
        try:
            # Search the FAISS index. 
            # For IndexFlatL2 (default), D contains squared L2 distances. Lower is better.
            # For IndexFlatIP (inner product), D contains inner products. Higher is better (if vectors normalized).
            # Assuming IndexFlatL2 here based on typical FAISS usage without explicit IP setting.
            distances, indices = self.faiss_index.search(query_embedding, k=k) 
            
            # Process the raw FAISS results
            for i, idx in enumerate(indices[0]):
                # FAISS can return -1 if fewer than k results are found or for invalid indices
                if idx < 0 or idx >= len(self.df):
                    # Log only if it's unexpected (not just fewer results than k)
                    if idx != -1: 
                         logger.warning(f"FAISS returned invalid index: {idx}")
                    continue 
                
                # Get the corresponding chunk data using the index
                # Using .iloc is generally safe if idx is within bounds
                chunk_data: Dict = self.df.iloc[idx].to_dict()
                
                # --- Category Filtering ---
                chunk_category_raw: str = chunk_data.get("category", "")
                # Apply filter only if a specific category (not 'all') is requested
                if category.lower() != "all":
                    query_cat_norm = self._normalize_category_for_comparison(category)
                    chunk_cat_norm = self._normalize_category_for_comparison(chunk_category_raw)
                    logger.debug(f"Semantic search: Query category (raw)='{category}', (norm)='{query_cat_norm}', Chunk category (raw)='{chunk_category_raw}', (norm)='{chunk_cat_norm}'")
                    # Check if the normalized query category is a substring of the normalized chunk category (or vice-versa)
                    is_match = (query_cat_norm in chunk_cat_norm) or (chunk_cat_norm in query_cat_norm)
                    logger.debug(f"Semantic search: Category match result: {is_match}")
                    if not is_match:
                        continue # Skip this result if category doesn't match

                # --- Score Calculation (Convert Distance to Similarity) ---
                # Assuming L2 distance from FAISS search. Lower distance means higher similarity.
                # Convert distance to a similarity score between 0 and 1.
                # Common method: 1 / (1 + distance). Add epsilon for numerical stability if distance can be 0.
                # Note: If using IndexFlatIP with normalized vectors, the score would directly be the cosine similarity.
                distance: float = float(distances[0][i])
                # Add small epsilon to prevent division by zero if distance is exactly 0
                semantic_score: float = 1.0 / (1.0 + distance + 1e-9) 

                results_raw.append({
                    'index': int(idx),          # Original index in the DataFrame
                    'score': semantic_score,    # Calculated similarity score (0-1)
                    'chunk_id': chunk_data.get('chunk_id') # For deduplication during combination
                })
                
        except Exception as e:
            logger.exception(f"Error during FAISS semantic search: {str(e)}")
            # Return potentially partial results collected so far
        
        logger.debug(f"Semantic search found {len(results_raw)} potential candidates matching category '{category}'.")
        return results_raw

    def _lexical_search(self, query: str, category: str, k: int) -> List[Dict]:
        """
        Performs lexical search using the TF-IDF matrix and filters by category.

        Args:
            query (str): The user's search query.
            category (str): The category to filter results by.
            k (int): The number of candidate results to fetch based on TF-IDF scores.

        Returns:
            List[Dict]: A list of dictionaries, each containing the 'index' of the chunk, 
                        the lexical 'score' (cosine similarity, 0-1), and 'chunk_id'.
        """
        results_raw: List[Dict] = []
        if self.tfidf_vectorizer is None or self.tfidf_matrix is None or self.df is None:
             logger.error("TF-IDF vectorizer, matrix, or DataFrame not loaded during lexical search.")
             return results_raw
             
        try:
            # Transform the query using the loaded TF-IDF vectorizer
            query_vec = self.tfidf_vectorizer.transform([query])
            
            # Calculate cosine similarity between the query vector and all document vectors in the matrix
            # The result is a dense numpy array of shape (1, num_documents)
            similarities: np.ndarray = cosine_similarity(query_vec, self.tfidf_matrix).flatten()
            
            # --- Category Filtering (Optimized) ---
            # Filter indices *before* sorting for efficiency if a specific category is needed
            if category.lower() != "all":
                query_cat_norm = self._normalize_category_for_comparison(category)
                # Apply normalization to the entire 'category' column for vectorized comparison
                normalized_df_categories = self.df["category"].apply(self._normalize_category_for_comparison)
                
                logger.debug(f"Lexical search: Query category (raw)='{category}', (norm)='{query_cat_norm}'")
                logger.debug(f"Lexical search: Sample normalized chunk categories: {normalized_df_categories.unique()[:5]}")
                
                # Check if the normalized query category is contained within the normalized chunk categories, or vice versa
                category_mask: pd.Series = (
                    normalized_df_categories.str.contains(query_cat_norm, na=False) |
                    normalized_df_categories.apply(lambda x: x in query_cat_norm)
                )
                logger.debug(f"Lexical search: Category mask generated. Number of matches: {category_mask.sum()}")
                
                # Get the original indices from the DataFrame where the category matches
                valid_indices: np.ndarray = np.where(category_mask)[0]
                # If no documents match the category, return early
                if len(valid_indices) == 0:
                     logger.debug(f"No documents found for category '{category.lower()}' in lexical search after normalization.")
                     return results_raw
                # Filter the similarity scores and keep only those for matching indices
                filtered_sims: np.ndarray = similarities[valid_indices]
                # Keep track of the original indices corresponding to the filtered scores
                original_indices_map: np.ndarray = valid_indices
            else:
                # No filtering needed, use all scores and their original indices (0 to N-1)
                filtered_sims = similarities
                original_indices_map = np.arange(len(similarities))

            # --- Get Top K Candidates from Filtered Set ---
            # Determine how many candidates to actually fetch (cannot exceed available filtered results)
            num_candidates_to_fetch: int = min(k, len(filtered_sims)) 
            
            if num_candidates_to_fetch > 0:
                 # Get the indices of the top N scores *within the filtered similarities array*
                 # `np.argsort` returns indices that would sort the array; slicing gets the top k largest.
                 top_filtered_indices: np.ndarray = np.argsort(filtered_sims)[-num_candidates_to_fetch:][::-1] # Descending order
                 
                 # Map these filtered indices back to their original indices in the full DataFrame
                 top_original_indices: np.ndarray = original_indices_map[top_filtered_indices]
                 # Get the corresponding scores
                 top_scores: np.ndarray = filtered_sims[top_filtered_indices]

                 # --- Create Result Dictionaries ---
                 for i, original_idx in enumerate(top_original_indices):
                      # Basic check, although filtering should ensure validity
                      if original_idx < 0 or original_idx >= len(self.df):
                           logger.warning(f"Lexical search produced invalid original index after filtering: {original_idx}")
                           continue
                      
                      # Retrieve chunk_id efficiently using the original index
                      chunk_id: Optional[str] = self.df.iloc[original_idx].get('chunk_id') 
                      
                      results_raw.append({
                           'index': int(original_idx),       # Original index in the DataFrame
                           'score': float(top_scores[i]),    # TF-IDF cosine similarity score (0-1)
                           'chunk_id': chunk_id              # For deduplication
                      })
            else:
                 # This case occurs if category filtering resulted in zero matches
                 logger.debug(f"No candidates found after filtering for category '{category}' in lexical search.")


        except Exception as e:
            logger.exception(f"Error during lexical search for query '{query[:100]}...': {str(e)}")
            # Return potentially partial results

        logger.debug(f"Lexical search found {len(results_raw)} potential candidates matching category '{category}'.")
        return results_raw

    def _combine_results(
        self, 
        semantic_results: List[Dict], 
        lexical_results: List[Dict], 
        query_embedding: np.ndarray,
        lexical_query: str,
        query_text: str,
        final_k: int
    ) -> List[SearchResult]:
        """
        Combines results from semantic and lexical searches using a weighted score.
        Calculates exact scores for the union of all candidates to ensure highly relevant 
        results from either search method are correctly scored and ranked.
        """
        # Get the union of indices from both searches
        union_indices = set()
        for res in semantic_results:
            union_indices.add(res['index'])
        for res in lexical_results:
            union_indices.add(res['index'])

        final_results: List[SearchResult] = []
        if self.df is None:
             logger.error("DataFrame is not loaded, cannot create final SearchResult objects.")
             return final_results

        # Prepare representations for exact score calculation
        q_emb = query_embedding.flatten()
        query_tfidf_vec = self.tfidf_vectorizer.transform([lexical_query])

        # Heuristic: check if query is about product registration and not establishment licensing
        query_lower = query_text.lower()
        is_registration_query = any(w in query_lower for w in ["registration", "register", "submission", "dossier", "marketing authorization"])
        asks_about_establishment = any(w in query_lower for w in ["license", "licensing", "warehouse", "manufacturer", "establishment", "scientific office"])

        # Vectorized calculation of exact lexical cosine similarities for all candidate indices
        union_indices_list = list(union_indices)
        if union_indices_list:
            candidate_tfidf = self.tfidf_matrix[union_indices_list]
            lexical_similarities = cosine_similarity(query_tfidf_vec, candidate_tfidf).flatten()
            lexical_scores = {idx: float(sim) for idx, sim in zip(union_indices_list, lexical_similarities)}
        else:
            lexical_scores = {}

        for idx in union_indices:
            try:
                # 1. Exact Semantic Cosine Similarity from unit vectors
                chunk_vector = np.zeros(self.embedding_dimension, dtype=np.float32)
                self.faiss_index.reconstruct(idx, chunk_vector)
                diff = q_emb - chunk_vector
                distance = np.dot(diff, diff)
                semantic_score = float(max(0.0, min(1.0, 1.0 - (distance / 2.0))))
                
                # 2. Exact Lexical Cosine Similarity
                lexical_score = lexical_scores.get(idx, 0.0)
                
                # Calculate hybrid score
                hybrid_score = (self.semantic_weight * semantic_score) + (self.lexical_weight * lexical_score)
                
                # Get the row data from the DataFrame
                if idx < 0 or idx >= len(self.df):
                     logger.warning(f"Invalid DataFrame index {idx} found during combining. Skipping.")
                     continue
                
                chunk_data = self.df.iloc[idx]
                doc_name = chunk_data.get('document', '')
                
                # Apply metadata-based routing / penalty
                boosted_score = hybrid_score
                penalty_reason = None
                
                if is_registration_query and not asks_about_establishment:
                    # Penalize establishment licensing documents if query is about registration/submission
                    is_license_doc = any(w in doc_name.lower() for w in ["license", "licensing"])
                    is_establishment_doc = any(w in doc_name.lower() for w in ["warehouse", "manufacturer", "clinical_trials_centers", "scientific_office"])
                    
                    if is_license_doc or is_establishment_doc:
                        boosted_score = hybrid_score * 0.80
                        penalty_reason = "establishment_license_penalty"

                # Create SearchResult Object
                final_results.append(SearchResult(
                    text=chunk_data.get('text', ''),
                    score=boosted_score,
                    document=doc_name,
                    category=chunk_data.get('category', 'Unknown'),
                    page=(
                        int(chunk_data['page'])
                        if pd.notna(chunk_data.get('page')) and str(chunk_data.get('page')).strip().isdigit()
                        else None
                    ),
                    chunk_id=chunk_data.get('chunk_id'),
                    metadata={
                        'semantic_score': semantic_score,
                        'lexical_score': lexical_score,
                        'original_index': idx,
                        'raw_hybrid_score': hybrid_score,
                        'penalty_reason': penalty_reason
                    }
                ))
            except Exception as e:
                 logger.exception(f"Error processing combined result for index {idx}: {str(e)}")

        # Sort Results by score (Descending)
        final_results.sort(key=lambda x: x.score, reverse=True)
        
        # Return Top 'final_k' Results
        logger.debug(f"Returning {min(len(final_results), final_k)} combined results after sorting.")
        return final_results[:final_k]

    def _normalize_category_for_comparison(self, category_name: str) -> str:
        """
        Helper method to normalize category names for consistent comparison.
        Converts to lowercase and removes underscores and spaces.
        """
        return category_name.lower().replace('_', '').replace(' ', '')
