# SFDA Copilot - Technical Context

## Core Technologies

### Backend Stack
- **Framework**: Python Flask
- **Search**: FAISS + TF-IDF
- **Embeddings**: sentence-transformers/all-mpnet-base-v2
- **Authentication**: Supabase
- **AI Integration**: OpenAI API
- **Security**: Flask-Talisman, Flask-CORS

### Frontend Stack
- **Framework**: Bootstrap 5
- **Icons**: Bootstrap Icons
- **JavaScript**: ES Modules
- **Styling**: Custom CSS

### Development Tools
- **Package Management**: pip + requirements.txt
- **Configuration**: YAML (config.yaml)
- **Environment**: Python 3.9+
- **Testing**: unittest

## Development Setup

### Dependencies
```bash
pip install -r web/requirements.txt
```

### Configuration
- `config.yaml` contains:
  - Search parameters (weights, multipliers)
  - Server settings (host, port)
  - Rate limiting (per day, hour, minute)
  - Embedding settings (model, dimension)
  - Data processing parameters (chunk size, overlap)
- `.env` for secrets:
  - OPENAI_API_KEY
  - SUPABASE_URL
  - SUPABASE_ANON_KEY
  - FLASK_SECRET_KEY

### Data Processing
1. PDFs processed into chunks
2. Chunks embedded using local model
3. FAISS index built from embeddings
4. TF-IDF matrix generated from text

## Technical Constraints
- Local embeddings require ~420MB disk space
- FAISS index must match embedding dimensions
- TF-IDF vocabulary must remain consistent
- OpenAI API rate limits apply
