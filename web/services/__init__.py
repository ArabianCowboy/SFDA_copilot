"""
SFDA Copilot - Services Module

Business logic and core services for the SFDA Copilot application.

Modules:
    - search_engine.py: Hybrid search implementation combining FAISS and TF-IDF
    - data_processing.py: PDF processing and document chunking
    - openai_app.py: OpenAI integration for response generation

Services Overview:

1. **Search Engine** (ImprovedSearchEngine):
   - Semantic search using FAISS with sentence-transformers embeddings
   - Keyword search using TF-IDF vectorization
   - Hybrid scoring with configurable weights
   - Category-based filtering (regulatory, pharmacovigilance, veterinary, biological)

2. **Data Processing**:
   - PDF text extraction and preprocessing
   - Document chunking with configurable size and overlap
   - Embedding generation for semantic search
   - Index building and persistence

3. **OpenAI Integration** (OpenAIHandler):
   - Context-aware response generation
   - Conversation history management
   - Suggested question generation
   - Citation and source attribution

These services work together to provide accurate, contextual answers to
pharmaceutical regulatory questions based on SFDA documentation.
"""
