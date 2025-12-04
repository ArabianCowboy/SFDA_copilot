"""
SFDA Copilot - API Module

This module contains the RESTful API endpoints for the SFDA Copilot application.

Modules:
    - app.py: Main Flask application with chat and FAQ endpoints
    - auth.py: Authentication routes and Supabase integration

The API provides:
    - User authentication and session management
    - Chat interface for regulatory queries
    - FAQ system for common questions
    - Rate limiting and security headers
    - CORS support for cross-origin requests

All API endpoints require proper authentication via Supabase JWT tokens,
except for the landing page and FAQ endpoints.
"""
