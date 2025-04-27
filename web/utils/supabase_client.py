from supabase import create_client
from web.utils.config_loader import config

class SupabaseClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            url = config.get("supabase", "url")
            key = config.get("supabase", "key")
            if not url or not key:
                raise ValueError("Supabase URL and key must be configured")
            cls._instance = create_client(url, key)
        return cls._instance

def get_supabase():
    return SupabaseClient()
