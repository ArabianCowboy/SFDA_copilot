"""Privileged reads about accounts, and the seam they go through.

Everything here runs **server-side with the service-role key**. The browser
never queries this data directly, which is deliberate and load-bearing:

* ``public.profiles`` grants the browser column-level write access to the four
  fields a reader owns and nothing else, so ``role``, ``tier`` and
  ``is_disabled`` are unwritable from a page. Reading them server-side keeps
  that asymmetry honest — the authority for "is this person an administrator"
  is never a value the page handed us.
* The browser Supabase mock in ``web/tests/conftest.py`` supports only
  ``select/eq/single/upsert`` and ignores the table name entirely, so any
  privileged query issued from JS would need that mock extended. Routing
  through Flask means it needs no changes at all.

The protocol exists so the console can be exercised without a database later;
today there is one implementation.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Optional, Protocol

from web.services.identity_cache import IdentityFlags
from web.utils.supabase_client import get_supabase_admin

logger = logging.getLogger(__name__)

# The columns that describe a reader's standing. Named once so the query and
# the dataclass cannot drift apart.
_IDENTITY_COLUMNS = "id, role, tier, is_disabled"


class AdminBackend(Protocol):
    """Privileged reads and writes. Implementations must not raise for "not found"."""

    def fetch_identity(self, user_id: str, email: Optional[str]) -> Optional[IdentityFlags]:
        """Return the reader's flags, or None when they have no profile row."""
        ...

    def get_settings(self) -> dict:
        """The stored override document. Empty when nothing has been changed."""
        ...

    def put_settings(self, settings: dict, *, actor_id: Optional[str]) -> None:
        """Replace the override document wholesale."""
        ...


class SupabaseAdminBackend:
    """The real one: ``public.profiles`` through the service-role client."""

    def __init__(self, client) -> None:
        self._client = client

    def fetch_identity(self, user_id: str, email: Optional[str]) -> Optional[IdentityFlags]:
        response = (
            self._client.table("profiles")
            .select(_IDENTITY_COLUMNS)
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        if not rows:
            return None

        row = rows[0]
        return IdentityFlags(
            user_id=user_id,
            email=email,
            # Defaults mirror the column defaults rather than the dataclass's,
            # so a row written before a column existed reads as unprivileged
            # instead of raising.
            role=row.get("role") or "user",
            tier=row.get("tier") or "free",
            is_disabled=bool(row.get("is_disabled")),
        )


    # ── Settings ──────────────────────────────────────────────────────────────

    def get_settings(self) -> dict:
        response = (
            self._client.table("app_settings")
            .select("settings")
            .eq("id", 1)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        return (rows[0].get("settings") if rows else {}) or {}

    def put_settings(self, settings: dict, *, actor_id: Optional[str]) -> None:
        # Upsert rather than update: the row is seeded by the migration, but a
        # restored or freshly provisioned project might not have it, and losing
        # a settings write to a missing row would be a silent no-op.
        self._client.table("app_settings").upsert(
            {
                "id": 1,
                "settings": settings,
                "updated_at": "now()",
                "updated_by": actor_id,
            },
            on_conflict="id",
        ).execute()


class InMemoryAdminBackend:
    """A backend with no database behind it.

    Serves ``?testing=true`` and the browser suite, where the console must work
    end to end without Supabase — PRODUCT.md treats the demo as a shipping
    surface, and a console that only exists against a live project cannot be
    shown or tested. Also what a deployment without a service-role key falls
    back to for reads.

    Deliberately mutable and per-process: a test that changes a setting sees the
    change, and nothing survives a restart.
    """

    def __init__(self, settings: Optional[dict] = None) -> None:
        self._settings = dict(settings or {})

    def fetch_identity(self, user_id: str, email: Optional[str]) -> Optional[IdentityFlags]:
        # Identity in TESTING comes from _TESTING_IDENTITIES before any backend
        # is consulted, so this is only reached by a caller that bypassed the
        # bypass. Unprivileged is the right answer for that.
        return None

    def get_settings(self) -> dict:
        return dict(self._settings)

    def put_settings(self, settings: dict, *, actor_id: Optional[str]) -> None:
        self._settings = dict(settings)


def get_admin_backend() -> Optional[AdminBackend]:
    """The configured backend, or None when privileged reads are unavailable.

    None is a normal state, not an error: it means TESTING, or no service-role
    key. Callers resolve it to "nobody is an administrator".
    """
    client = get_supabase_admin()
    if client is None:
        return None
    return SupabaseAdminBackend(client)


def _fallback(cache, user_id: str, email: Optional[str]) -> IdentityFlags:
    """What to serve when the lookup could not be made.

    Prefers the last answer we had, **specifically so that a disabled account
    stays disabled through an outage**. Mapping "we could not check" onto
    "ordinary enabled reader" is how a suspended account quietly gets back in
    the moment the database hiccups, and it is the same value, so nothing
    downstream could tell the two apart.

    Nothing here can grant privilege: a stale entry is republished with
    ``is_resolved=False``, and ``is_admin`` requires a resolved answer.
    """
    remembered = cache.last_known(user_id)
    if remembered is not None:
        return replace(remembered, email=email or remembered.email, is_resolved=False)
    return IdentityFlags.unknown(user_id, email)


def resolve_identity_flags(
    cache, user_id: str, email: Optional[str] = None, *, fresh: bool = False
) -> IdentityFlags:
    """Resolve a reader's standing, preferring the cache.

    ``fresh=True`` skips the cache entirely. Used for every console
    authorization decision: the TTL is a latency optimisation for chat, where
    being thirty seconds behind a demotion costs nothing, and it is exactly the
    wrong trade for the surface that can change a model or disable an account.
    Console requests are rare, so the round trip is free where it matters.

    **Fails open on access, closed on privilege.** If the lookup cannot be made
    — no service-role key, Supabase unreachable, a malformed row — the reader is
    treated as a signed-in non-administrator: they can still ask their question,
    and they are still not an operator. The alternative, failing closed on
    access, would turn a Supabase blip into a total outage of a product whose
    whole job is answering one question quickly.

    A failed lookup is deliberately **not** cached, so the next request retries
    rather than inheriting a 30-second-old failure. A genuinely missing row is
    cached, because that is a stable fact about the account.
    """
    if not fresh and (hit := cache.get(user_id)) is not None:
        return hit

    backend = get_admin_backend()
    if backend is None:
        # No service-role key. An expected, configured absence rather than a
        # failure — but still not an answer, so it cannot confer privilege.
        return _fallback(cache, user_id, email)

    # Taken before the lookup: publication is ordered by when a fetch started,
    # so a slow older SELECT cannot overwrite a newer one.
    started = cache.begin_fetch()

    try:
        flags = backend.fetch_identity(user_id, email)
    except Exception:
        logger.error(
            "Identity lookup failed for %s; falling back to the last known answer.",
            user_id,
            exc_info=True,
        )
        return _fallback(cache, user_id, email)

    if flags is None:
        # No profile row. The signup trigger should have made one, so this is
        # worth a log line — but it is not this request's problem to fix. It is
        # a resolved fact, so it caches.
        logger.warning("No profile row for authenticated user %s.", user_id)
        flags = IdentityFlags.unprivileged(user_id, email)

    cache.put(flags, fetched_at=started)
    return flags
