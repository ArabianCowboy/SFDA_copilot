# SFDA Copilot - System Patterns

## Architecture Overview
![System Architecture](system-architecture.png)

1. **Frontend**: Bootstrap 5 responsive web interface
2. **Backend**: Python Flask REST API
   - **API**: Core application logic and endpoints in 'web/api/'
   - **Services**: Modular components for data processing, search, and OpenAI integration in 'web/services/'
   - **Utilities**: Helper functions and clients for configuration, embeddings, and database access in 'web/utils/'
3. **Services**:
   - Search Engine (FAISS + TF-IDF)
   - OpenAI Integration
   - Authentication (Supabase)
4. **Data Layer**: 
   - Processed PDF documents
   - Chunked text and embeddings
   - FAISS indices and TF-IDF matrices

## Key Technical Decisions

### Hybrid Search Implementation
- **Semantic Search**: FAISS with 'all-mpnet-base-v2' embeddings
- **Lexical Search**: TF-IDF with cosine similarity
- **Weighted Combination**: Configurable weights in config.yaml

### Response Generation
- OpenAI GPT for contextual responses
- System prompts structured by:
  - Category (Regulatory/Pharmacovigilance/Veterinary_Medicines/Biological_Products_and_Quality_Control)
  - Response format requirements
  - Source document references

### Security Implementation
- Flask-Talisman for security headers
- CSP configuration based on environment
- Rate limiting via Flask-Limiter
- JWT authentication via Supabase

## Component Relationships
```mermaid
flowchart TD
    A[Frontend] -->|HTTP| B[Flask API]
    B --> C[Search Engine]
    C --> D[FAISS Index]
    C --> E[TF-IDF Matrix]
    B --> F[OpenAI Handler]
    B --> G[Auth Service]
    G --> H[Supabase]
