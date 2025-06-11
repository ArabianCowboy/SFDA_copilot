import os
from supabase import create_client, Client
from flask import current_app

class SupabaseClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            url = os.getenv('SUPABASE_URL')
            key = os.getenv('SUPABASE_ANON_KEY')
            
            if not url or not key:
                raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY environment variables are required")
            
            # Handle test environment
            if current_app and current_app.config.get('TESTING'):
                # In test environment, we don't actually create a Supabase client
                # The mock will be injected by the test fixtures
                return None
            
            cls._instance = create_client(url, key)
        return cls._instance

def get_supabase() -> Client:
    """Get the Supabase client instance."""
    return SupabaseClient()
