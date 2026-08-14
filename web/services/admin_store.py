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


class AdminActionRefused(Exception):
    """A change the database declined on principle, not on failure.

    Carries the machine code the console translates. These are not errors in
    the sense of something going wrong — they are the system refusing to let an
    operator do something they would regret, so they read as statements rather
    than faults.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# Postgres SQLSTATEs raised by admin_set_user_flags, mapped to the codes the
# console has strings for. Kept next to the exception so the two cannot drift.
_REFUSAL_CODES = {
    "AD001": "cannot_change_own_access",
    "AD002": "would_leave_no_administrator",
    "AD003": "no_such_account",
}

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

    def put_settings(self, settings: dict, *, actor, before: dict, after: dict) -> dict:
        """Replace the override document and record the change, atomically.

        Returns the committed document — what is actually stored, rather than
        what the caller hoped it stored.
        """
        ...

    def list_audit(self, *, limit: int, offset: int) -> list:
        """Recorded actions, most recent first."""
        ...

    def list_users(self, *, limit: int, offset: int, search: Optional[str]) -> tuple:
        """``(rows, total)``. Emails come from auth, standing from profiles."""
        ...

    def set_user_flags(
        self, user_id: str, *, role=None, is_disabled=None, reason=None, actor
    ) -> dict:
        """Change a role or chat access, recording it in the same transaction.

        Raises :class:`AdminActionRefused` for the guards that stop an operator
        locking everyone out.
        """
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

    def put_settings(self, settings: dict, *, actor, before: dict, after: dict) -> dict:
        """Through the RPC, so the change and its audit row share a transaction.

        The previous implementation upserted the row directly and would have
        needed a second statement for the audit entry — two statements that can
        half-succeed, and the half that fails is always the record. It also sent
        `updated_at: "now()"` as a JSON string, which Postgres happens to accept
        as a timestamp literal; the function calls `now()` server-side instead,
        so that is no longer a quirk anything depends on.
        """
        response = self._client.rpc(
            "admin_write_settings",
            {
                "p_settings": settings,
                "p_actor_id": actor.user_id,
                "p_actor_email": actor.email,
                "p_before": before,
                "p_after": after,
                "p_request_ip": actor.request_ip,
                "p_user_agent": actor.user_agent,
            },
        ).execute()
        return getattr(response, "data", None) or {}

    def list_audit(self, *, limit: int, offset: int) -> list:
        response = (
            self._client.table("audit_log")
            .select("*")
            .order("id", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return getattr(response, "data", None) or []

    # ── Accounts ──────────────────────────────────────────────────────────────

    def list_users(self, *, limit: int, offset: int, search: Optional[str]) -> tuple:
        response = self._client.rpc(
            "admin_list_users",
            {"p_limit": limit, "p_offset": offset, "p_search": search or None},
        ).execute()
        rows = getattr(response, "data", None) or []
        # `total` is carried on every row by the window in the function, so a
        # paginated view can say "12 of 400" without a second count query.
        total = rows[0]["total"] if rows else 0
        return [{k: v for k, v in row.items() if k != "total"} for row in rows], total

    def set_user_flags(
        self, user_id: str, *, role=None, is_disabled=None, reason=None, actor
    ) -> dict:
        try:
            response = self._client.rpc(
                "admin_set_user_flags",
                {
                    "p_user_id": user_id,
                    "p_role": role,
                    "p_is_disabled": is_disabled,
                    "p_reason": reason,
                    "p_actor_id": actor.user_id,
                    "p_actor_email": actor.email,
                    "p_request_ip": actor.request_ip,
                    "p_user_agent": actor.user_agent,
                },
            ).execute()
        except Exception as exception:
            # The guards come back as PostgREST errors carrying the SQLSTATE.
            # Matched on the code rather than the message, because the message
            # is prose and prose gets edited.
            text = str(exception)
            for sqlstate, code in _REFUSAL_CODES.items():
                if sqlstate in text:
                    raise AdminActionRefused(code) from exception
            raise

        return getattr(response, "data", None) or {}


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
        self._audit: list = []
        self._next_id = 1
        self._users = self._seed_users()

    def fetch_identity(self, user_id: str, email: Optional[str]) -> Optional[IdentityFlags]:
        # Identity in TESTING comes from _TESTING_IDENTITIES before any backend
        # is consulted, so this is only reached by a caller that bypassed the
        # bypass. Unprivileged is the right answer for that.
        return None

    def get_settings(self) -> dict:
        return dict(self._settings)

    def put_settings(self, settings: dict, *, actor, before: dict, after: dict) -> dict:
        # Both writes together, mirroring the RPC — so a test that asserts the
        # audit row exists is asserting the same property production relies on.
        self._settings = dict(settings)
        self._record(
            action="settings.update",
            target_type="settings",
            target_id="app_settings",
            actor=actor,
            before=before,
            after=after,
        )
        return dict(self._settings)

    def _record(self, *, action, target_type, target_id, actor, before=None, after=None, note=None):
        from datetime import datetime, timezone

        self._audit.append({
            "id": self._next_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "actor_id": actor.user_id,
            "actor_email": actor.email,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "before": before,
            "after": after,
            "request_ip": actor.request_ip,
            "user_agent": actor.user_agent,
            "note": note,
        })
        self._next_id += 1

    def list_audit(self, *, limit: int, offset: int) -> list:
        newest_first = list(reversed(self._audit))
        return newest_first[offset:offset + limit]

    # ── Accounts ──────────────────────────────────────────────────────────────
    #
    # Seeded with the same shapes the console has to handle: an administrator, an
    # ordinary reader, and one already disabled. The guards below mirror the
    # database function's, so a test that proves an operator cannot lock
    # themselves out is proving the same rule production enforces.

    def _seed_users(self) -> list:
        return [
            {"id": "test-admin-id", "email": "admin@example.com", "role": "admin",
             "tier": "internal", "is_disabled": False, "disabled_at": None,
             "disabled_reason": None, "created_at": "2026-01-01T00:00:00+00:00",
             "last_sign_in_at": "2026-08-14T00:00:00+00:00"},
            {"id": "test-user-id", "email": "test@example.com", "role": "user",
             "tier": "free", "is_disabled": False, "disabled_at": None,
             "disabled_reason": None, "created_at": "2026-02-01T00:00:00+00:00",
             "last_sign_in_at": "2026-08-13T00:00:00+00:00"},
            {"id": "test-disabled-id", "email": "disabled@example.com", "role": "user",
             "tier": "free", "is_disabled": True, "disabled_at": "2026-08-01T00:00:00+00:00",
             "disabled_reason": "seeded", "created_at": "2026-03-01T00:00:00+00:00",
             "last_sign_in_at": None},
        ]

    def list_users(self, *, limit: int, offset: int, search: Optional[str]) -> tuple:
        rows = self._users
        if search:
            needle = search.lower()
            rows = [r for r in rows if needle in r["email"].lower()]
        return rows[offset:offset + limit], len(rows)

    def set_user_flags(
        self, user_id: str, *, role=None, is_disabled=None, reason=None, actor
    ) -> dict:
        if actor.user_id and actor.user_id == user_id:
            raise AdminActionRefused("cannot_change_own_access")

        row = next((r for r in self._users if r["id"] == user_id), None)
        if row is None:
            raise AdminActionRefused("no_such_account")

        was_enabled_admin = row["role"] == "admin" and not row["is_disabled"]
        removing = (role is not None and role != "admin") or is_disabled is True
        if was_enabled_admin and removing:
            enabled_admins = sum(
                1 for r in self._users if r["role"] == "admin" and not r["is_disabled"]
            )
            if enabled_admins <= 1:
                raise AdminActionRefused("would_leave_no_administrator")

        if role is not None:
            row["role"] = role
        if is_disabled is not None:
            row["is_disabled"] = is_disabled
            row["disabled_reason"] = reason if is_disabled else None

        self._record(
            action=("user.disable" if is_disabled is True
                    else "user.enable" if is_disabled is False
                    else "user.role_change"),
            target_type="user",
            target_id=user_id,
            actor=actor,
            before=None,
            after={"role": row["role"], "is_disabled": row["is_disabled"]},
            note=reason,
        )
        return {"role": row["role"], "tier": row["tier"], "is_disabled": row["is_disabled"]}


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

    if not cache.put(flags, fetched_at=started):
        # The cache rejected this as stale — a newer lookup already published,
        # or the entry was invalidated after this fetch began. Returning the
        # rejected value anyway would let *this* request act on a role the cache
        # correctly refused to keep, which is the demotion arriving everywhere
        # except the request that needed to see it.
        current = cache.get(user_id)
        if current is not None:
            return current
        return _fallback(cache, user_id, email)

    return flags
