import logging
import os
from typing import Optional

import httpx
from supabase import create_client, Client
# SyncClientOptions, not the base ClientOptions. Only the sync subclass carries
# `httpx_client`; the base accepts it as no keyword at all, so importing the
# wrong one is a TypeError at client construction — which is to say, at the
# first authenticated request in production, and nowhere in the test suite,
# because SupabaseClient returns None under TESTING and never builds one.
from supabase.lib.client_options import SyncClientOptions
from flask import current_app

logger = logging.getLogger(__name__)


def _auth_timeout() -> httpx.Timeout:
    """How long the token check may take before it is called an outage.

    Every authenticated request pays one `auth.get_user` round trip to GoTrue,
    and production runs `--workers 1 --threads 8` (README.md) — so a stalled
    auth call holds one of eight request threads for the whole stall, and eight
    concurrent ones exhaust the only worker's capacity for every reader. Opening
    one console account already costs two of them.

    Gunicorn's own `--timeout 300` does not bound this: it governs the worker,
    not an outbound call.

    5 seconds is not a new policy: it is httpx's own default, which this call
    has always been running on by accident. Stating it makes the bound a
    decision rather than a library detail that a future `supabase` bump could
    change underneath the one call that gates the whole app.
    """
    return httpx.Timeout(float(os.getenv("SUPABASE_AUTH_TIMEOUT", "5")), connect=5.0)


def _auth_http_client() -> httpx.Client:
    """The transport GoTrue will use.

    `follow_redirects` and `http2` are repeated deliberately. supabase-py only
    applies its own defaults when no client is injected, so an injected client
    that omitted them would quietly downgrade the connection — and the incident
    this bounds was observed on an HTTP/2 stream.
    """
    return httpx.Client(timeout=_auth_timeout(), follow_redirects=True, http2=True)


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

            # This client is only ever used for auth (token verification,
            # logout, the dead signup/login routes). Nothing reads PostgREST
            # through it, so one timeout tuned for GoTrue is safe to share.
            cls._instance = create_client(
                url, key, SyncClientOptions(httpx_client=_auth_http_client())
            )
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
