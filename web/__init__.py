"""
SFDA Copilot - Web Application Package

An AI-powered regulatory guidance system for pharmaceutical regulations in Saudi Arabia.

This package provides the core web application functionality for SFDA Copilot, including:

- **Flask Backend**: RESTful API endpoints for chat and authentication
- **AI-Powered Search**: Hybrid search combining FAISS (semantic) and TF-IDF (keyword) matching
- **Regulatory Knowledge Base**: Comprehensive coverage of SFDA regulations across:
  - Regulatory guidelines and drug registration
  - Pharmacovigilance and drug safety monitoring
  - Veterinary medicines requirements
  - Biological products and quality control
- **User Authentication**: Secure authentication via Supabase
- **Smart Query Processing**: Automatic expansion of pharmaceutical terminology
- **Context-Aware Responses**: OpenAI-powered responses with document citations

Key Components:
    - api/: API endpoints and authentication routes
    - services/: Business logic for search, data processing, and AI integration
    - utils/: Utility functions for configuration, embeddings, and external services
    - templates/: HTML templates for the web interface

For more information, see the project README and documentation in the memory-bank/ directory.
""" 