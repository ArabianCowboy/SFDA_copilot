import logging
import os
from typing import Optional

from supabase import create_client, Client
from flask import current_app

logger = logging.getLogger(__name__)


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


class SupabaseAdminClient:
    """Service-role client. SERVER-SIDE ONLY.

    This key bypasses every RLS policy on the project. It must never be
    rendered into a template, returned in a JSON response, or logged — the
    anon key above is the only one a browser is ever allowed to hold.

    Deliberately separate from ``SupabaseClient`` rather than a flag on it:
    five test files sit downstream of that singleton, and the two clients
    differ in more than a key. This one checks TESTING *before* reading the
    environment, because the anon client's ordering means it raises when the
    vars are unset — fine for a client the whole app needs, wrong for one that
    only the admin surface needs.
    """

    _instance: Optional[Client] = None
    _warned = False

    def __new__(cls) -> Optional[Client]:
        if current_app and current_app.config.get("TESTING"):
            return None

        if cls._instance is None:
            url = os.getenv("SUPABASE_URL")
            # Both names are accepted so the key can be migrated without a code
            # change. Supabase is replacing the long-lived JWT `service_role`
            # key with individually revocable `sb_secret_…` keys and removes the
            # legacy ones in late 2026; `create_client` does not inspect the
            # format, so the migration is a value swap. The new name wins when
            # both are present, which makes the cutover a rename rather than an
            # edit-in-place — and leaves the old value recoverable for a rollback.
            key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")

            if not url or not key:
                # Loud in the log, but not fatal. A missing admin key must not
                # stop the app serving chat: the reader-facing product does not
                # depend on it, and callers treat "no admin client" as "nobody
                # is an administrator", which fails in the safe direction.
                if not cls._warned:
                    logger.error(
                        "SUPABASE_SERVICE_ROLE_KEY is not set; every reader will "
                        "resolve as a non-administrator and the admin surface will "
                        "be unreachable. Set it in .env to enable it."
                    )
                    cls._warned = True
                return None

            cls._instance = create_client(url, key)

        return cls._instance


def get_supabase_admin() -> Optional[Client]:
    """Service-role Supabase client, or None when unavailable.

    None means one of: running under TESTING, or no service-role key is
    configured. Callers must treat it as "no privileged data available"
    rather than as an error.
    """
    return SupabaseAdminClient()
