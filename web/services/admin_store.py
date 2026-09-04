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
from datetime import timezone
from typing import Protocol

from web.services.identity_cache import IdentityFlags
from web.utils.supabase_client import get_supabase_admin

logger = logging.getLogger(__name__)

# datetime.UTC is Python 3.11+; the VPS production floor is 3.10.
UTC = timezone.utc


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
    # The reader-quota family (docs/reader-quota-plan.md §1.5/§1.6). Mapped here
    # so the console meets a machine code it can translate, never a raw 23514 or
    # 23503 surfacing as a 500.
    "TQ001": "duplicate_key",
    "TQ002": "no_such_tier",
    "TQ003": "tier_in_use",
    "TQ004": "default_tier_protected",
    "TQ005": "invalid_limit",
    "TQ006": "invalid_labels",
    "TQ007": "invalid_window",
    "TQ008": "invalid_key",
}

# The columns that describe a reader's standing. Named once so the query and
# the dataclass cannot drift apart.
_IDENTITY_COLUMNS = "id, role, tier, is_disabled"


def _generated_full_name(first_name: str | None, family_name: str | None) -> str | None:
    """Mirror `profiles.full_name`'s generated-column expression exactly.

    Used only by the in-memory test double — the real backend reads
    `full_name` straight from the database, where it is a stored generated
    column (supabase/migrations/20260822225415_profile_identity_atomic_cutover.sql).
    Kept as one function so the two definitions cannot drift.
    """
    if first_name is None and family_name is None:
        return None
    if first_name is None:
        return family_name
    if family_name is None:
        return first_name
    return f"{first_name} {family_name}"


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
    sqlstate = getattr(exception, "code", None) or (
        exception.args[0].get("code")
        if exception.args and isinstance(exception.args[0], dict)
        else None
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

    def fetch_identity(self, user_id: str, email: str | None) -> IdentityFlags | None:
        """Return the reader's flags, or None when they have no profile row."""
        ...

    def get_standing_line_facts(self, user_id: str) -> dict | None:
        """``{"created_at": ..., "conversation_count": ...}`` for /account.

        Separate from `fetch_identity` deliberately: those flags are cached
        and re-read on the hot chat-request path
        (web/services/identity_cache.py), and a conversation-count subquery
        has no business running on every cached identity refresh. This is
        called once, only from GET /api/identity.
        """
        ...

    def touch_last_seen(self, user_id: str) -> None:
        """Record presence in ``profile_last_seen``. Best-effort.

        Throttled in the database (``touch_last_seen(uuid)``); callers do not
        need to. Must not raise for "not found" — an id that resolves to no
        account is simply nothing to touch.
        """
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
        self,
        *,
        limit: int,
        offset: int,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> list:
        """Recorded actions, most recent first, optionally for one target.

        Extended rather than given a sibling method: the audit surface stays at
        exactly ``{list_audit, append_audit}``, which is what makes the
        append-only assertion in the tests a tight statement instead of a
        growing list of exceptions.
        """
        ...

    def list_users(self, *, limit: int, offset: int, search: str | None) -> tuple:
        """``(rows, total)``. Emails come from auth, standing from profiles."""
        ...

    def get_user(self, user_id: str) -> dict | None:
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

    def list_tiers(self) -> list[dict]:
        """Every tier with its member count, for the console's Tiers tab."""
        ...

    def create_tier(self, *, key, label_en, label_ar, daily_message_limit, ordering, actor) -> dict:
        """Create a tier. Refuses TQ001/TQ005/TQ006/TQ008."""
        ...

    def update_tier(
        self, key: str, *, label_en, label_ar, daily_message_limit, ordering, actor
    ) -> dict:
        """Edit a tier's labels, limit and ordering. The key itself is immutable."""
        ...

    def delete_tier(self, key: str, *, actor) -> dict:
        """Delete an empty, non-structural tier. Refuses TQ002/TQ003/TQ004."""
        ...

    def set_reader_quota(
        self, user_id: str, *, tier, override, starts_at, expires_at, reason, actor
    ) -> dict:
        """Set an account's tier and/or its (optionally windowed) override.

        Both levels in one audited transaction, because the console saves them
        together. ``override=None`` CLEARS the override; ``tier=None`` leaves the
        tier alone. The asymmetry is why the route always sends every key.
        """
        ...

    def update_profile(
        self,
        user_id: str,
        *,
        first_name,
        family_name,
        age,
        organization,
        specialization,
        expected_updated_at,
        actor,
    ) -> dict:
        """Rewrite a reader's identity and profile text, recording the diff.

        Records nothing when nothing changed, and refuses rather than clobbers
        when the row has moved since the operator loaded it. full_name is not
        a parameter here — it is a generated column since the identity
        cutover and can never be written.
        """
        ...

    def append_audit(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str,
        actor,
        before: dict | None = None,
        after: dict | None = None,
        note: str | None = None,
    ) -> None:
        """Record one action that could not share a transaction with its effect.

        Every other audit row in this system is written by the Postgres function
        that performs the change, inside the same transaction — which is why the
        record cannot disagree with what happened. An outbound email has no such
        option: the send is an HTTP call to somebody else. So the intent is
        recorded, the call is made, and the outcome is recorded, and the pair is
        correlated by an ``operation_id`` carried in ``after``.

        ``before`` is optional and was unused until the email-change action:
        the reset-password action this was built for has no "before" worth
        recording, but a changed email does — the row otherwise cannot show
        what the account used to be. Optional rather than widening every
        existing call site.

        Appending is not the danger this system guards against. **Changing** a
        recorded entry is, and no implementation offers a way to.
        """
        ...


class SupabaseAdminBackend:
    """The real one: ``public.profiles`` through the service-role client."""

    def __init__(self, client) -> None:
        self._client = client

    def fetch_identity(self, user_id: str, email: str | None) -> IdentityFlags | None:
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

    def get_standing_line_facts(self, user_id: str) -> dict | None:
        response = self._client.rpc("get_identity_flags", {"p_user_id": user_id}).execute()
        rows = getattr(response, "data", None) or []
        if not rows:
            return None
        row = rows[0]
        return {
            "created_at": row.get("created_at"),
            "conversation_count": row.get("conversation_count") or 0,
        }

    def touch_last_seen(self, user_id: str) -> None:
        self._client.rpc("touch_last_seen", {"p_user_id": user_id}).execute()

    # ── Settings ──────────────────────────────────────────────────────────────

    def get_settings(self) -> dict:
        response = (
            self._client.table("app_settings").select("settings").eq("id", 1).limit(1).execute()
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
        try:
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
        except Exception as exception:
            # admin_write_settings had no refusal to raise until the migration
            # that made an enabled administrator mandatory, so this method was
            # the one writer with no `except` — the same shape update_profile
            # and set_user_flags have carried since they were written. Without
            # it a demoted or disabled administrator saving settings gets an
            # unconverted PostgREST exception on the generic error path
            # instead of the AD004 refusal, and it is not one surface but
            # three: the settings page, the registration pause control and the
            # notification purge-retention control all reach this method.
            raise _refusal_from(exception) from exception

        return getattr(response, "data", None) or {}

    def list_audit(
        self,
        *,
        limit: int,
        offset: int,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> list:
        query = self._client.table("audit_log").select("*")
        # `audit_log_target_idx (target_type, target_id, occurred_at desc)`
        # already exists for exactly this, so the per-account history needs no
        # new index — see 20260814032139_audit_log.sql.
        if target_type is not None:
            query = query.eq("target_type", target_type)
        if target_id is not None:
            query = query.eq("target_id", target_id)

        response = query.order("id", desc=True).range(offset, offset + limit - 1).execute()
        return getattr(response, "data", None) or []

    # ── Accounts ──────────────────────────────────────────────────────────────

    def list_users(self, *, limit: int, offset: int, search: str | None) -> tuple:
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
        self,
        user_id: str,
        *,
        first_name,
        family_name,
        age,
        organization,
        specialization,
        expected_updated_at,
        actor,
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
                    "p_first_name": first_name,
                    "p_family_name": family_name,
                    "p_age": age,
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
        self,
        *,
        action: str,
        target_type: str,
        target_id: str,
        actor,
        before: dict | None = None,
        after: dict | None = None,
        note: str | None = None,
    ) -> None:
        # A direct insert rather than an RPC: there is no accompanying mutation
        # to share a transaction with, which is the entire reason this exists.
        # `service_role` already holds insert on audit_log (20260814032139), so
        # this needs no new privilege.
        self._client.table("audit_log").insert(
            {
                "actor_id": actor.user_id,
                "actor_email": actor.email,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "before": before,
                "after": after,
                # None rather than "": the RPCs guard with `nullif(...)::inet` and a
                # direct insert has no such guard, so an empty string would fail the
                # cast instead of storing NULL.
                "request_ip": actor.request_ip or None,
                "user_agent": actor.user_agent,
                "note": note,
            }
        ).execute()

    def get_user(self, user_id: str) -> dict | None:
        # Same reasoning as `set_user_flags` below: a non-uuid identifies no
        # account, and that is a "not found", not a crash.
        try:
            uuid.UUID(str(user_id))
        except (ValueError, AttributeError, TypeError):
            return None

        response = self._client.rpc("admin_get_user", {"p_user_id": user_id}).execute()
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

    # -- tiers and the reader quota ------------------------------------------

    def _quota_rpc(self, name: str, args: dict):
        try:
            return self._client.rpc(name, args).execute()
        except Exception as exception:
            raise _refusal_from(exception) from exception

    def list_tiers(self) -> list[dict]:
        response = self._quota_rpc("admin_list_tiers", {})
        return list(getattr(response, "data", None) or [])

    def create_tier(self, *, key, label_en, label_ar, daily_message_limit, ordering, actor) -> dict:
        response = self._quota_rpc(
            "admin_create_tier",
            {
                "p_key": key,
                "p_label_en": label_en,
                "p_label_ar": label_ar,
                "p_daily_message_limit": daily_message_limit,
                "p_ordering": ordering,
                # No p_actor_email on any of these: the functions resolve the
                # email from the id they just validated, so a caller-supplied
                # address can never reach the audit trail. See the migration.
                "p_actor_id": actor.user_id,
                "p_request_ip": actor.request_ip,
                "p_user_agent": actor.user_agent,
            },
        )
        return getattr(response, "data", None) or {}

    def update_tier(
        self, key: str, *, label_en, label_ar, daily_message_limit, ordering, actor
    ) -> dict:
        response = self._quota_rpc(
            "admin_update_tier",
            {
                "p_key": key,
                "p_label_en": label_en,
                "p_label_ar": label_ar,
                "p_daily_message_limit": daily_message_limit,
                "p_ordering": ordering,
                "p_actor_id": actor.user_id,
                "p_request_ip": actor.request_ip,
                "p_user_agent": actor.user_agent,
            },
        )
        return getattr(response, "data", None) or {}

    def delete_tier(self, key: str, *, actor) -> dict:
        response = self._quota_rpc(
            "admin_delete_tier",
            {
                "p_key": key,
                "p_actor_id": actor.user_id,
                "p_request_ip": actor.request_ip,
                "p_user_agent": actor.user_agent,
            },
        )
        return getattr(response, "data", None) or {}

    def set_reader_quota(
        self, user_id: str, *, tier, override, starts_at, expires_at, reason, actor
    ) -> dict:
        try:
            uuid.UUID(str(user_id))
        except (ValueError, AttributeError, TypeError):
            raise AdminActionRefused("no_such_account") from None
        response = self._quota_rpc(
            "admin_set_reader_quota",
            {
                "p_user_id": user_id,
                "p_tier": tier,
                "p_daily_message_limit_override": override,
                "p_reason": reason,
                "p_actor_id": actor.user_id,
                "p_override_starts_at": starts_at,
                "p_override_expires_at": expires_at,
                "p_request_ip": actor.request_ip,
                "p_user_agent": actor.user_agent,
            },
        )
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

    def __init__(self, settings: dict | None = None, quota=None) -> None:
        self._settings = dict(settings or {})
        self._audit: list = []
        self._next_id = 1
        self._users = self._seed_users()
        # SHARED with InMemoryQuotaBackend by injection, not copied. A test that
        # assigns a tier or sets an override through the console must see the
        # changed limit on the very next claim -- two separate dicts would let
        # the console and the chat route disagree about the same account, which
        # is the bug this feature exists to prevent.
        self._quota = quota

    def _tiers(self) -> dict:
        """The tier catalogue this backend edits, or a local one under no quota."""
        if self._quota is not None:
            return self._quota.tiers
        if not hasattr(self, "_local_tiers"):
            self._local_tiers = {
                "free": {
                    "label_en": "Free",
                    "label_ar": "مجاني",
                    "daily_message_limit": 200,
                    "ordering": 0,
                },
                "staff": {
                    "label_en": "Staff",
                    "label_ar": "الإداريين",
                    "daily_message_limit": 200,
                    "ordering": 10,
                },
            }
        return self._local_tiers

    # -- tiers and the reader quota ------------------------------------------

    def list_tiers(self) -> list[dict]:
        tiers = self._tiers()
        rows = [
            {
                "key": key,
                **row,
                "member_count": sum(1 for u in self._users if u.get("tier") == key),
            }
            for key, row in tiers.items()
        ]
        return sorted(rows, key=lambda r: (r.get("ordering", 0), r["key"]))

    def create_tier(self, *, key, label_en, label_ar, daily_message_limit, ordering, actor) -> dict:
        import re as _re

        if not key or not _re.fullmatch(r"[a-z][a-z0-9_]{0,31}", str(key)):
            raise AdminActionRefused("invalid_key")
        if daily_message_limit is None or int(daily_message_limit) < 0:
            raise AdminActionRefused("invalid_limit")
        if not (1 <= len(label_en or "") <= 40) or not (1 <= len(label_ar or "") <= 40):
            raise AdminActionRefused("invalid_labels")
        tiers = self._tiers()
        if key in tiers:
            raise AdminActionRefused("duplicate_key")
        tiers[key] = {
            "label_en": label_en,
            "label_ar": label_ar,
            "daily_message_limit": int(daily_message_limit),
            "ordering": int(ordering or 0),
        }
        self._record(
            action="tier.create",
            target_type="tier",
            target_id=key,
            actor=actor,
            before=None,
            after=dict(tiers[key]),
        )
        return {"key": key, **tiers[key]}

    def update_tier(
        self, key: str, *, label_en, label_ar, daily_message_limit, ordering, actor
    ) -> dict:
        tiers = self._tiers()
        if key not in tiers:
            raise AdminActionRefused("no_such_tier")
        if daily_message_limit is not None and int(daily_message_limit) < 0:
            raise AdminActionRefused("invalid_limit")
        for label in (label_en, label_ar):
            if label is not None and not (1 <= len(label) <= 40):
                raise AdminActionRefused("invalid_labels")
        before = dict(tiers[key])
        if label_en is not None:
            tiers[key]["label_en"] = label_en
        if label_ar is not None:
            tiers[key]["label_ar"] = label_ar
        if daily_message_limit is not None:
            tiers[key]["daily_message_limit"] = int(daily_message_limit)
        if ordering is not None:
            tiers[key]["ordering"] = int(ordering)
        after = dict(tiers[key])
        # The diff rule: nothing changed, nothing recorded.
        if before != after:
            self._record(
                action="tier.update",
                target_type="tier",
                target_id=key,
                actor=actor,
                before=before,
                after=after,
            )
        return {"key": key, **after}

    def delete_tier(self, key: str, *, actor) -> dict:
        tiers = self._tiers()
        if key == "free":
            raise AdminActionRefused("default_tier_protected")
        if key not in tiers:
            raise AdminActionRefused("no_such_tier")
        if any(u.get("tier") == key for u in self._users):
            raise AdminActionRefused("tier_in_use")
        before = dict(tiers.pop(key))
        self._record(
            action="tier.delete",
            target_type="tier",
            target_id=key,
            actor=actor,
            before=before,
            after=None,
        )
        return {"key": key, **before}

    def set_reader_quota(
        self, user_id: str, *, tier, override, starts_at, expires_at, reason, actor
    ) -> dict:
        row = next((r for r in self._users if r["id"] == user_id), None)
        if row is None:
            raise AdminActionRefused("no_such_account")
        if override is not None and int(override) < 0:
            raise AdminActionRefused("invalid_limit")
        if override is not None and starts_at and expires_at and expires_at <= starts_at:
            raise AdminActionRefused("invalid_window")
        tiers = self._tiers()
        if tier is not None and tier not in tiers:
            raise AdminActionRefused("no_such_tier")

        if tier is not None and tier != row.get("tier"):
            self._record(
                action="user.tier_change",
                target_type="user",
                target_id=user_id,
                actor=actor,
                before={"tier": row.get("tier")},
                after={"tier": tier},
                note=reason,
            )
            row["tier"] = tier

        # Synced UNCONDITIONALLY, not only when the tier changed. The seeded
        # users already carry a tier, so a first save that leaves it alone would
        # otherwise never tell the quota double which tier this account is in --
        # and the very next claim would resolve through the `free` fallback
        # instead of the account's actual tier.
        if self._quota is not None and row.get("tier"):
            self._quota.profile_tiers[user_id] = row["tier"]

        if self._quota is not None:
            before = self._quota.overrides.get(user_id)
            if override is None:
                self._quota.overrides.pop(user_id, None)
                after = None
            else:
                after = {
                    "daily_message_limit": int(override),
                    "starts_at": starts_at,
                    "expires_at": expires_at,
                }
                self._quota.overrides[user_id] = after
            if before != after:
                self._record(
                    action="user.quota_override_change",
                    target_type="user",
                    target_id=user_id,
                    actor=actor,
                    before=before,
                    after=after,
                    note=reason,
                )
        return {"tier": row.get("tier"), "override": override}

    def fetch_identity(self, user_id: str, email: str | None) -> IdentityFlags | None:
        # Identity in TESTING comes from _TESTING_IDENTITIES before any backend
        # is consulted, so this is only reached by a caller that bypassed the
        # bypass. Unprivileged is the right answer for that.
        return None

    def get_standing_line_facts(self, user_id: str) -> dict | None:
        row = next((r for r in self._users if r["id"] == user_id), None)
        if row is None:
            return None
        return {
            "created_at": row.get("created_at"),
            "conversation_count": row.get("conversation_count", 0),
        }

    def _require_admin_actor(self, actor) -> None:
        """Mirror public.admin_actor_email, which every mutating RPC now calls.

        Three cases, one refusal, because the database makes no distinction
        between them either: no actor id at all, an id that matches no account,
        and an account that is not an enabled administrator.

        The absent case is the one this replaces. Every double here used to be
        written as ``if actor.user_id:`` — guarding only when an actor was
        supplied, and so reporting "authorized" for the one input the database
        now refuses outright. A double that accepts what production rejects is
        a green suite asserting the opposite of production.
        """
        if not actor.user_id:
            raise AdminActionRefused("actor_no_longer_administrator")
        acting = next((r for r in self._users if r["id"] == actor.user_id), None)
        # `has_profile` is part of the gate, not decoration. The SQL joins
        # public.profiles to auth.users, so an account that exists in auth with
        # no profile row matches nothing and is refused. Without this the double
        # would authorize the seeded orphan fixture — an actor production can
        # never produce.
        if acting is None or not acting.get("has_profile", True):
            raise AdminActionRefused("actor_no_longer_administrator")
        if acting.get("role") != "admin" or acting.get("is_disabled"):
            raise AdminActionRefused("actor_no_longer_administrator")

    def get_settings(self) -> dict:
        return dict(self._settings)

    def put_settings(self, settings: dict, *, actor, before: dict, after: dict) -> dict:
        # admin_write_settings had no actor check at all until the database
        # migration that added one, and this double faithfully mirrored that
        # absence. Both now check.
        self._require_admin_actor(actor)

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
        from datetime import datetime

        self._audit.append(
            {
                "id": self._next_id,
                "occurred_at": datetime.now(UTC).isoformat(),
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
            }
        )
        self._next_id += 1

    def list_audit(
        self,
        *,
        limit: int,
        offset: int,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> list:
        rows = list(reversed(self._audit))
        if target_type is not None:
            rows = [r for r in rows if r.get("target_type") == target_type]
        if target_id is not None:
            rows = [r for r in rows if r.get("target_id") == target_id]
        return rows[offset : offset + limit]

    # ── Accounts ──────────────────────────────────────────────────────────────
    #
    # Seeded with the same shapes the console has to handle: an administrator, an
    # ordinary reader, and one already disabled. The guards below mirror the
    # database function's, so a test that proves an operator cannot lock
    # themselves out is proving the same rule production enforces.

    def _seed_users(self) -> list:
        return [
            {
                "id": "test-admin-id",
                "email": "admin@example.com",
                "role": "admin",
                "tier": "staff",
                "is_disabled": False,
                "disabled_at": None,
                "disabled_reason": None,
                "created_at": "2026-01-01T00:00:00+00:00",
                "last_sign_in_at": "2026-08-14T00:00:00+00:00",
                "email_identity_verified": True,
            },
            {
                "id": "test-user-id",
                "email": "test@example.com",
                "role": "user",
                "tier": "free",
                "is_disabled": False,
                "disabled_at": None,
                "disabled_reason": None,
                "created_at": "2026-02-01T00:00:00+00:00",
                "last_sign_in_at": "2026-08-13T00:00:00+00:00",
                "email_identity_verified": True,
            },
            {
                "id": "test-disabled-id",
                "email": "disabled@example.com",
                "role": "user",
                "tier": "free",
                "is_disabled": True,
                "disabled_at": "2026-08-01T00:00:00+00:00",
                "disabled_reason": "seeded",
                "created_at": "2026-03-01T00:00:00+00:00",
                "last_sign_in_at": None,
                "email_identity_verified": True,
            },
            # An account in auth with no profile row. Rare in production now the
            # signup trigger is repaired, and seeded here precisely because it is
            # rare: it is the state the detail view exists to make visible, and
            # without a fixture nothing would ever exercise that path.
            {
                "id": "test-orphan-id",
                "email": "orphan@example.com",
                "role": "user",
                "tier": "free",
                "is_disabled": False,
                "disabled_at": None,
                "disabled_reason": None,
                "created_at": "2026-04-01T00:00:00+00:00",
                "last_sign_in_at": None,
                "has_profile": False,
            },
        ]

    def list_users(self, *, limit: int, offset: int, search: str | None) -> tuple:
        rows = self._users
        if search:
            needle = search.lower()
            rows = [r for r in rows if needle in r["email"].lower()]
        # `has_profile` is detail-only; the list deliberately does not carry it,
        # matching admin_list_users, which cannot distinguish the case at all.
        listed = [{k: v for k, v in r.items() if k != "has_profile"} for r in rows]
        return listed[offset : offset + limit], len(rows)

    def append_audit(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str,
        actor,
        before: dict | None = None,
        after: dict | None = None,
        note: str | None = None,
    ) -> None:
        self._record(
            action=action,
            target_type=target_type,
            target_id=target_id,
            actor=actor,
            before=before,
            after=after,
            note=note,
        )

    def update_profile(
        self,
        user_id: str,
        *,
        first_name,
        family_name,
        age,
        organization,
        specialization,
        expected_updated_at,
        actor,
    ) -> dict:
        # Mirrors admin_update_profile, including the parts that are easy to
        # leave out of a double and then never test: the actor revalidation, the
        # stale-write refusal, and writing NO audit row for an empty diff.
        self._require_admin_actor(actor)

        row = next((r for r in self._users if r["id"] == user_id), None)
        if row is None or not row.get("has_profile", True):
            raise AdminActionRefused("no_such_account")

        if expected_updated_at is not None and expected_updated_at != row.get(
            "updated_at", row["created_at"]
        ):
            raise AdminActionRefused("profile_changed_since_loaded")

        before = {
            k: row.get(k)
            for k in ("first_name", "family_name", "age", "organization", "specialization")
        }
        after = {
            "first_name": first_name,
            "family_name": family_name,
            "age": age,
            "organization": organization,
            "specialization": specialization,
        }
        if before == after:
            return after

        row.update(after)
        row["updated_at"] = f"{row.get('updated_at', row['created_at'])}+"
        self._record(
            action="user.profile_change",
            target_type="user",
            target_id=user_id,
            actor=actor,
            before=before,
            after=after,
        )
        return after

    def get_user(self, user_id: str) -> dict | None:
        row = next((r for r in self._users if r["id"] == user_id), None)
        if row is None:
            return None

        has_profile = row.get("has_profile", True)
        first_name = row.get("first_name")
        family_name = row.get("family_name")
        detail = {
            "id": row["id"],
            "email": row["email"],
            "created_at": row["created_at"],
            "last_sign_in_at": row["last_sign_in_at"],
            "email_confirmed_at": row.get("email_confirmed_at", row["created_at"]),
            "email_identity_verified": row.get("email_identity_verified", True),
            "banned_until": None,
            "has_profile": has_profile,
            "disabled_by_email": None,
            "first_name": first_name,
            "family_name": family_name,
            "age": row.get("age"),
            # Mirrors the real generated column (profiles.full_name), not a
            # stored field — first_name/family_name are the source of truth
            # here too, matching production after the identity cutover.
            "full_name": _generated_full_name(first_name, family_name),
            "organization": row.get("organization"),
            "specialization": row.get("specialization"),
            "last_seen_at": row.get("last_seen_at"),
            "updated_at": row.get("updated_at", row["created_at"]),
            # Read-only consent record (docs/profile-refactor-plan.md Step 6
            # checklist item "admin visibility ... of the consent record").
            # Mirrors admin_get_user's own field set exactly; false/None
            # defaults for a seeded row that never set them, matching a real
            # profile that has never granted consent.
            "marketing_consent": row.get("marketing_consent", False),
            "marketing_consent_granted_at": row.get("marketing_consent_granted_at"),
            "marketing_consent_withdrawn_at": row.get("marketing_consent_withdrawn_at"),
            "marketing_consent_policy_version": row.get("marketing_consent_policy_version"),
            "marketing_consent_language": row.get("marketing_consent_language"),
            "marketing_consent_surface": row.get("marketing_consent_surface"),
            "marketing_consent_granted_while_unconfirmed": row.get(
                "marketing_consent_granted_while_unconfirmed"
            ),
        }
        # Null, not a default, when there is no profile — the whole point of the
        # detail view is that it does not paint a healthy face on a broken row.
        for key in ("role", "tier", "is_disabled", "disabled_at", "disabled_reason"):
            detail[key] = row.get(key) if has_profile else None
        return detail

    def touch_last_seen(self, user_id: str) -> None:
        # Mirrors touch_last_seen(uuid)'s "not found" contract: silently does
        # nothing for an id that matches no seeded row, or one with no
        # profile — the same rule every other method on this Protocol
        # follows. Does NOT mirror its throttle, deliberately: this fake
        # always writes. A test that touches twice and asserts the second
        # timestamp moved would pass here and fail against the real RPC
        # (silent for an hour) — the throttle itself is proven only by
        # supabase/tests/rpc_behaviour.test.sql, against the live function,
        # not by anything routed through this fake.
        row = next((r for r in self._users if r["id"] == user_id), None)
        if row is None or not row.get("has_profile", True):
            return
        from datetime import datetime

        row["last_seen_at"] = datetime.now(UTC).isoformat()

    def set_user_flags(
        self, user_id: str, *, role=None, is_disabled=None, reason=None, actor
    ) -> dict:
        # Unconditional now, matching the function: the `actor.user_id and`
        # half was there only because a null actor was permitted.
        if actor.user_id == user_id:
            raise AdminActionRefused("cannot_change_own_access")

        # Mirrors the actor revalidation the database does inside its
        # serialized transaction: an actor demoted or disabled in the meantime
        # cannot act, and that is what actually catches two administrators
        # removing each other at the same moment.
        #
        # This was additionally `if acting is not None and (…)`, so an actor id
        # matching no account passed as well as an absent one. The database
        # joins profiles to auth.users and refuses when the join finds nothing,
        # which covers both.
        self._require_admin_actor(actor)

        row = next((r for r in self._users if r["id"] == user_id), None)
        # A profile-less account is `no_such_account` here too, matching
        # admin_set_user_flags: its `select ... from public.profiles where id =
        # p_user_id for update` finds nothing and raises AD003. update_profile
        # already checked this; set_user_flags did not, so the double would let
        # the orphan fixture be promoted to administrator.
        if row is None or not row.get("has_profile", True):
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


def get_admin_backend() -> AdminBackend | None:
    """The configured backend, or None when privileged reads are unavailable.

    None is a normal state, not an error: it means TESTING, or no service-role
    key. Callers resolve it to "nobody is an administrator".
    """
    client = get_supabase_admin()
    if client is None:
        return None
    return SupabaseAdminBackend(client)


def _fallback(cache, user_id: str, email: str | None) -> IdentityFlags:
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
    cache, user_id: str, email: str | None = None, *, fresh: bool = False
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
