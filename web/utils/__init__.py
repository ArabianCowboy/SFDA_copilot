"""
SFDA Copilot - Utils Module

Utility functions and helper modules for the SFDA Copilot application.

Modules:
    - config_loader.py: YAML configuration file loading and validation
    - embedding_helpers.py: Text embedding utilities and caching
    - local_embedding_client.py: Local sentence-transformers embedding generation
    - openai_client.py: OpenAI API client wrapper with rate limiting
    - supabase_client.py: Supabase authentication and database client
    - error_handlers.py: Centralized error handling and logging

Utilities Overview:

1. **Configuration**: 
   - Loads and validates config.yaml settings
   - Provides type-safe access to configuration values
   - Environment variable overrides

2. **Embeddings**:
   - Local embedding generation using sentence-transformers
   - Batch processing for efficiency
   - Caching to avoid redundant computations

3. **External Services**:
   - OpenAI API integration with retry logic
   - Supabase client initialization and authentication
   - Error handling and logging for all external calls

These utilities provide robust, reusable functionality across the application.
"""
