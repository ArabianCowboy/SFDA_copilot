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
import uuid
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
    "AD004": "actor_no_longer_administrator",
    # Raised by admin_update_profile when the row moved under the operator's
    # feet. Not a failure — a refusal to overwrite somebody else's edit.
    "AD005": "profile_changed_since_loaded",
}

# The columns that describe a reader's standing. Named once so the query and
# the dataclass cannot drift apart.
_IDENTITY_COLUMNS = "id, role, tier, is_disabled"


def _refusal_from(exception: Exception) -> Exception:
    """Turn a PostgREST error carrying one of our SQLSTATEs into a refusal.

    Matched on the code rather than the message, because the message is prose
    and prose gets edited. Where the SDK exposes no structured code, the search
    is bounded to the message rather than the whole exception repr: searching
    the repr meant a user id containing "AD001" was reported as a self-change
    refusal — the target's own identifier deciding what the refusal was.

    Returns the exception to raise, so the caller keeps `raise ... from` and the
    original traceback when this is not a refusal at all.
    """
    sqlstate = (
        getattr(exception, "code", None)
        or (exception.args[0].get("code") if exception.args
            and isinstance(exception.args[0], dict) else None)
    )
    if sqlstate in _REFUSAL_CODES:
        return AdminActionRefused(_REFUSAL_CODES[sqlstate])

    message = ""
    if exception.args and isinstance(exception.args[0], dict):
        message = str(exception.args[0].get("message") or "")
    for state, code in _REFUSAL_CODES.items():
        if state in message:
            return AdminActionRefused(code)
    return exception


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

    def list_audit(
        self, *, limit: int, offset: int,
        target_type: Optional[str] = None, target_id: Optional[str] = None,
    ) -> list:
        """Recorded actions, most recent first, optionally for one target.

        Extended rather than given a sibling method: the audit surface stays at
        exactly ``{list_audit, append_audit}``, which is what makes the
        append-only assertion in the tests a tight statement instead of a
        growing list of exceptions.
        """
        ...

    def list_users(self, *, limit: int, offset: int, search: Optional[str]) -> tuple:
        """``(rows, total)``. Emails come from auth, standing from profiles."""
        ...

    def get_user(self, user_id: str) -> Optional[dict]:
        """One account in full, or None when there is no such account.

        Unlike the list, this does not invent defaults for a missing profile —
        it reports ``has_profile`` and leaves the columns null, so a broken
        account can be shown as broken rather than as an ordinary reader.
        """
        ...

    def set_user_flags(
        self, user_id: str, *, role=None, is_disabled=None, reason=None, actor
    ) -> dict:
        """Change a role or chat access, recording it in the same transaction.

        Raises :class:`AdminActionRefused` for the guards that stop an operator
        locking everyone out.
        """
        ...

    def update_profile(
        self, user_id: str, *, full_name, organization, specialization,
        expected_updated_at, actor,
    ) -> dict:
        """Rewrite a reader's profile text, recording the diff.

        Records nothing when nothing changed, and refuses rather than clobbers
        when the row has moved since the operator loaded it.
        """
        ...

    def append_audit(
        self, *, action: str, target_type: str, target_id: str, actor,
        after: Optional[dict] = None, note: Optional[str] = None,
    ) -> None:
        """Record one action that could not share a transaction with its effect.

        Every other audit row in this system is written by the Postgres function
        that performs the change, inside the same transaction — which is why the
        record cannot disagree with what happened. An outbound email has no such
        option: the send is an HTTP call to somebody else. So the intent is
        recorded, the call is made, and the outcome is recorded, and the pair is
        correlated by an ``operation_id`` carried in ``after``.

        Appending is not the danger this system guards against. **Changing** a
        recorded entry is, and no implementation offers a way to.
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
        half-succeed, and the half that fails is always the record.

        It also sent `updated_at: "now()"` as a JSON string. Postgres accepts
        that as a timestamp literal, so it worked — but a caller able to write
        any value it likes into a field whose job is to say when the row
        actually changed is a field that cannot be trusted. A BEFORE trigger
        now sets it, matching how public.profiles has always done it, and the
        column is not in any payload.
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

    def list_audit(
        self, *, limit: int, offset: int,
        target_type: Optional[str] = None, target_id: Optional[str] = None,
    ) -> list:
        query = self._client.table("audit_log").select("*")
        # `audit_log_target_idx (target_type, target_id, occurred_at desc)`
        # already exists for exactly this, so the per-account history needs no
        # new index — see 20260814032447_audit_log.sql.
        if target_type is not None:
            query = query.eq("target_type", target_type)
        if target_id is not None:
            query = query.eq("target_id", target_id)

        response = (
            query.order("id", desc=True)
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

    def update_profile(
        self, user_id: str, *, full_name, organization, specialization,
        expected_updated_at, actor,
    ) -> dict:
        try:
            uuid.UUID(str(user_id))
        except (ValueError, AttributeError, TypeError):
            raise AdminActionRefused("no_such_account") from None

        try:
            response = self._client.rpc(
                "admin_update_profile",
                {
                    "p_user_id": user_id,
                    "p_full_name": full_name,
                    "p_organization": organization,
                    "p_specialization": specialization,
                    "p_expected_updated_at": expected_updated_at,
                    "p_actor_id": actor.user_id,
                    "p_actor_email": actor.email,
                    "p_request_ip": actor.request_ip,
                    "p_user_agent": actor.user_agent,
                },
            ).execute()
        except Exception as exception:
            raise _refusal_from(exception) from exception

        return getattr(response, "data", None) or {}

    def append_audit(
        self, *, action: str, target_type: str, target_id: str, actor,
        after: Optional[dict] = None, note: Optional[str] = None,
    ) -> None:
        # A direct insert rather than an RPC: there is no accompanying mutation
        # to share a transaction with, which is the entire reason this exists.
        # `service_role` already holds insert on audit_log (20260814032447), so
        # this needs no new privilege.
        self._client.table("audit_log").insert({
            "actor_id": actor.user_id,
            "actor_email": actor.email,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "after": after,
            # None rather than "": the RPCs guard with `nullif(...)::inet` and a
            # direct insert has no such guard, so an empty string would fail the
            # cast instead of storing NULL.
            "request_ip": actor.request_ip or None,
            "user_agent": actor.user_agent,
            "note": note,
        }).execute()

    def get_user(self, user_id: str) -> Optional[dict]:
        # Same reasoning as `set_user_flags` below: a non-uuid identifies no
        # account, and that is a "not found", not a crash.
        try:
            uuid.UUID(str(user_id))
        except (ValueError, AttributeError, TypeError):
            return None

        response = self._client.rpc(
            "admin_get_user", {"p_user_id": user_id}
        ).execute()
        rows = getattr(response, "data", None) or []
        return rows[0] if rows else None

    def set_user_flags(
        self, user_id: str, *, role=None, is_disabled=None, reason=None, actor
    ) -> dict:
        # A uuid is what THIS storage requires, so it is checked here rather
        # than in the route — the route's contract is about the payload, and an
        # id that is not a uuid simply identifies no account. Left to the driver
        # it would surface as a 500 for what is really a 404-shaped mistake.
        try:
            uuid.UUID(str(user_id))
        except (ValueError, AttributeError, TypeError):
            raise AdminActionRefused("no_such_account") from None

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
            raise _refusal_from(exception) from exception

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

    def list_audit(
        self, *, limit: int, offset: int,
        target_type: Optional[str] = None, target_id: Optional[str] = None,
    ) -> list:
        rows = list(reversed(self._audit))
        if target_type is not None:
            rows = [r for r in rows if r.get("target_type") == target_type]
        if target_id is not None:
            rows = [r for r in rows if r.get("target_id") == target_id]
        return rows[offset:offset + limit]

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
            # An account in auth with no profile row. Rare in production now the
            # signup trigger is repaired, and seeded here precisely because it is
            # rare: it is the state the detail view exists to make visible, and
            # without a fixture nothing would ever exercise that path.
            {"id": "test-orphan-id", "email": "orphan@example.com", "role": "user",
             "tier": "free", "is_disabled": False, "disabled_at": None,
             "disabled_reason": None, "created_at": "2026-04-01T00:00:00+00:00",
             "last_sign_in_at": None, "has_profile": False},
        ]

    def list_users(self, *, limit: int, offset: int, search: Optional[str]) -> tuple:
        rows = self._users
        if search:
            needle = search.lower()
            rows = [r for r in rows if needle in r["email"].lower()]
        # `has_profile` is detail-only; the list deliberately does not carry it,
        # matching admin_list_users, which cannot distinguish the case at all.
        listed = [{k: v for k, v in r.items() if k != "has_profile"} for r in rows]
        return listed[offset:offset + limit], len(rows)

    def append_audit(
        self, *, action: str, target_type: str, target_id: str, actor,
        after: Optional[dict] = None, note: Optional[str] = None,
    ) -> None:
        self._record(action=action, target_type=target_type, target_id=target_id,
                     actor=actor, after=after, note=note)

    def update_profile(
        self, user_id: str, *, full_name, organization, specialization,
        expected_updated_at, actor,
    ) -> dict:
        # Mirrors admin_update_profile, including the parts that are easy to
        # leave out of a double and then never test: the actor revalidation, the
        # stale-write refusal, and writing NO audit row for an empty diff.
        if actor.user_id:
            acting = next((r for r in self._users if r["id"] == actor.user_id), None)
            if not acting or acting.get("role") != "admin" or acting.get("is_disabled"):
                raise AdminActionRefused("actor_no_longer_administrator")

        row = next((r for r in self._users if r["id"] == user_id), None)
        if row is None or not row.get("has_profile", True):
            raise AdminActionRefused("no_such_account")

        if (expected_updated_at is not None
                and expected_updated_at != row.get("updated_at", row["created_at"])):
            raise AdminActionRefused("profile_changed_since_loaded")

        before = {k: row.get(k) for k in ("full_name", "organization", "specialization")}
        after = {"full_name": full_name, "organization": organization,
                 "specialization": specialization}
        if before == after:
            return after

        row.update(after)
        row["updated_at"] = f"{row.get('updated_at', row['created_at'])}+"
        self._record(
            action="user.profile_change", target_type="user", target_id=user_id,
            actor=actor, before=before, after=after,
        )
        return after

    def get_user(self, user_id: str) -> Optional[dict]:
        row = next((r for r in self._users if r["id"] == user_id), None)
        if row is None:
            return None

        has_profile = row.get("has_profile", True)
        detail = {
            "id": row["id"],
            "email": row["email"],
            "created_at": row["created_at"],
            "last_sign_in_at": row["last_sign_in_at"],
            "email_confirmed_at": row.get("email_confirmed_at", row["created_at"]),
            "banned_until": None,
            "has_profile": has_profile,
            "disabled_by_email": None,
            "full_name": row.get("full_name"),
            "organization": row.get("organization"),
            "specialization": row.get("specialization"),
            "last_seen_at": row.get("last_seen_at"),
            "updated_at": row.get("updated_at", row["created_at"]),
        }
        # Null, not a default, when there is no profile — the whole point of the
        # detail view is that it does not paint a healthy face on a broken row.
        for key in ("role", "tier", "is_disabled", "disabled_at", "disabled_reason"):
            detail[key] = row.get(key) if has_profile else None
        return detail

    def set_user_flags(
        self, user_id: str, *, role=None, is_disabled=None, reason=None, actor
    ) -> dict:
        if actor.user_id and actor.user_id == user_id:
            raise AdminActionRefused("cannot_change_own_access")

        # Mirrors the actor revalidation the database does inside its
        # serialized transaction: an actor demoted or disabled in the meantime
        # cannot act, and that is what actually catches two administrators
        # removing each other at the same moment.
        if actor.user_id:
            acting = next((r for r in self._users if r["id"] == actor.user_id), None)
            if acting is not None and (acting["role"] != "admin" or acting["is_disabled"]):
                raise AdminActionRefused("actor_no_longer_administrator")

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

        before_role = row["role"]
        before_disabled = row["is_disabled"]

        if role is not None:
            row["role"] = role
        if is_disabled is not None:
            row["is_disabled"] = is_disabled
            row["disabled_reason"] = reason if is_disabled else None

        if role is not None and role != before_role:
            # `reason` is a general note on the call, not reserved for
            # disabling — the route only *requires* it when is_disabled is
            # true, it does not forbid sending it alongside a role-only
            # change. Attaching it here too means it is never silently
            # dropped, matching the SQL RPC this mirrors.
            self._record(
                action="user.role_change",
                target_type="user",
                target_id=user_id,
                actor=actor,
                before={"role": before_role},
                after={"role": row["role"]},
                note=reason,
            )

        if is_disabled is not None and is_disabled != before_disabled:
            self._record(
                action="user.disable" if row["is_disabled"] else "user.enable",
                target_type="user",
                target_id=user_id,
                actor=actor,
                before={"is_disabled": before_disabled},
                after={"is_disabled": row["is_disabled"]},
                note=reason if row["is_disabled"] else None,
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
