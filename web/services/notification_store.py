"""Storage seam for the Notification Center: admin composer writes and
reader reads, through the same three service-role-only tables
(``notifications``, ``notification_recipients``, ``user_notification_reads``).

Kept as one seam rather than split across an admin store and a reader store:
an admin "send" and a reader "see it in the inbox" must observe the same
state within one process under ``FLASK_TESTING`` (the browser suite's own
plan asserts exactly this — composer submit -> history row appears -> bell
badge increments), and two independent in-memory doubles could drift out of
sync in a way the real database, with one source of truth, never can.

Mirrors ``web/services/admin_store.py``'s own shape: a ``Protocol``, a real
Supabase-backed implementation that calls the ``security definer`` RPCs, and
an in-memory double for ``TESTING``/``?testing=true``. The in-memory double
shares its ``_users`` list with ``InMemoryAdminBackend`` (constructed the same
way ``InMemoryAuthAdminDispatcher`` already shares it — see
``web/api/app.py``), so a role/tier targeting decision made here agrees with
whatever the seeded admin console fixtures say.

Realtime *publishing* is a distinct concern (HTTP calls to Supabase's
Realtime REST endpoint, not database storage) and lives in
``web/services/notification_service.py``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Protocol

from web.services.admin_store import AdminActionRefused
from web.utils.supabase_client import get_supabase_admin

logger = logging.getLogger(__name__)

# datetime.UTC is Python 3.11+; the VPS production floor is 3.10.
UTC = timezone.utc

# Postgres SQLSTATEs raised by the notification RPCs, mapped to the codes the
# console and the reader surface have strings for. Own namespace (AN0xx for
# admin-facing refusals, RN0xx for reader-facing ones) so it cannot collide
# with admin_store.py's AD0xx codes, which belong to a different RPC family.
_REFUSAL_CODES = {
    "AN001": "idempotency_conflict",
    "AN002": "no_matching_recipients",
    "AN003": "no_such_target_user",
    "AN004": "target_user_disabled",
    "AN005": "actor_no_longer_administrator",
    "AN006": "no_such_notification",
    "AN007": "already_deactivated",
    "AN008": "already_deleted",
    "AN009": "not_yet_deleted",
    "RN001": "not_a_recipient",
    "RN002": "action_type_mismatch",
    # Raised by notifications_mark_read when a reader dismisses or acknowledges
    # a notification the operator has since withdrawn or that has expired. It
    # must stay mapped: an unmapped SQLSTATE escapes _refusal_from as a raw
    # exception and the route falls through to a 503 "mark_read_failed", which
    # is a server-error shape for a deliberate refusal.
    "RN003": "notification_no_longer_active",
}

# One fetch page for the unbounded-audience queries below. Deliberately equal
# to notification_service._CHUNK_SIZE: the broadcast's memory bound is the
# chunk rather than the audience, and a page larger than the chunk would put
# that back. Note this is only the page SIZE REQUESTED — PostgREST's own
# `db-max-rows` can return fewer, which is why `_keyset_ids` walks until an
# empty page rather than until a short one.
_FETCH_PAGE = 500


def _refusal_from(exception: Exception) -> Exception:
    """Turn a PostgREST error carrying one of our SQLSTATEs into a refusal.

    Same shape as admin_store.py's own ``_refusal_from`` — matched on the
    structured code first, the message only as a bounded fallback, and never
    against the whole exception repr (a user id containing "AN001" must not
    be misread as a refusal code).
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


def _payload_hash(*fields: object) -> str:
    """Content fingerprint for idempotency, computed server-side.

    Deliberately never accepted from the client: a caller-supplied hash could
    claim an arbitrary fingerprint for content it did not actually send,
    which would let a same-id-different-content replay slip past the
    conflict check instead of being caught by it.
    """
    canonical = json.dumps(list(fields), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_iso(value: object) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _require_uuid(value: str, refusal_code: str) -> None:
    """Same reasoning as ``SupabaseAdminBackend.set_user_flags``/
    ``update_profile``: a non-uuid identifies no real row, and that is a
    refusal the route maps to 404, not a 500 from a failed Postgres cast.
    Deliberately backend-only — the in-memory testing double's fixtures use
    non-uuid ids on purpose, and this check must never see them.
    """
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise AdminActionRefused(refusal_code) from None


class NotificationBackend(Protocol):
    """Admin writes and reader reads over the notification tables."""

    def preview_audience(
        self, *, target_kind: str, target_role, target_tier, target_user_id
    ) -> int:
        """How many accounts this targeting would currently reach. Persists nothing."""
        ...

    def create(
        self,
        *,
        type: str,
        severity: str,
        title_en: str,
        title_ar: str,
        body_en: str,
        body_ar: str,
        target_kind: str,
        target_role,
        target_tier,
        target_user_id,
        expires_at,
        resend_of,
        client_request_id: str,
        actor,
    ) -> dict:
        """Insert + recipient snapshot + audit row, one transaction.

        Raises :class:`AdminActionRefused` for ``idempotency_conflict``,
        ``no_matching_recipients``, ``no_such_target_user``,
        ``target_user_disabled``, ``actor_no_longer_administrator``.
        """
        ...

    def deactivate(self, notification_id: str, *, actor) -> dict:
        """Raises AdminActionRefused for no_such_notification/already_deactivated/already_deleted/actor_no_longer_administrator."""
        ...

    def delete(self, notification_id: str, *, actor) -> dict:
        """Soft delete. Same refusal set as deactivate (minus already_deactivated)."""
        ...

    def purge(self, notification_id: str, *, actor) -> dict:
        """Permanent erasure of an already soft-deleted row and its recipient/
        read-receipt rows. Raises AdminActionRefused for
        no_such_notification/not_yet_deleted/actor_no_longer_administrator.
        """
        ...

    def list_history(self, *, limit: int, offset: int, status: str) -> tuple:
        """``(rows, total)``, newest first, each row carrying engagement counts."""
        ...

    def list_active_for_reader(self, user_id: str) -> list:
        """Currently-visible, not-yet-dismissed/acknowledged notifications for this reader."""
        ...

    def list_history_for_reader(
        self, user_id: str, *, cursor_created_at, cursor_id, limit: int
    ) -> list:
        """Cursor/keyset page of every notification ever targeted to this reader."""
        ...

    def mark_read(self, notification_id: str, user_id: str, action: str) -> dict:
        """Raises AdminActionRefused for not_a_recipient/action_type_mismatch/no_such_notification."""
        ...

    def mark_all_read(self, user_id: str) -> int:
        """Count of previously-unread notifications just marked read."""
        ...

    def recipient_ids_for(self, notification_id: str) -> list:
        """Snapshotted recipients (role/tier/user targets). Empty for target_kind='all'."""
        ...

    def all_enabled_profile_ids(self) -> list:
        """Every enabled account id — used only to resolve a 'all'-target Realtime push."""
        ...


class SupabaseNotificationBackend:
    """The real one: the three notification tables through the service-role client."""

    def __init__(self, client) -> None:
        self._client = client

    def preview_audience(
        self, *, target_kind: str, target_role, target_tier, target_user_id
    ) -> int:
        if target_kind == "all":
            response = (
                self._client.table("profiles")
                .select("id", count="exact")
                .eq("is_disabled", False)
                .limit(1)
                .execute()
            )
            return getattr(response, "count", None) or 0
        if target_kind == "role":
            response = (
                self._client.table("profiles")
                .select("id", count="exact")
                .eq("role", target_role)
                .eq("is_disabled", False)
                .limit(1)
                .execute()
            )
            return getattr(response, "count", None) or 0
        if target_kind == "tier":
            response = (
                self._client.table("profiles")
                .select("id", count="exact")
                .eq("tier", target_tier)
                .eq("is_disabled", False)
                .limit(1)
                .execute()
            )
            return getattr(response, "count", None) or 0
        if target_kind == "user":
            response = (
                self._client.table("profiles")
                .select("id")
                .eq("id", target_user_id)
                .eq("is_disabled", False)
                .limit(1)
                .execute()
            )
            return 1 if (getattr(response, "data", None) or []) else 0
        return 0

    def create(
        self,
        *,
        type: str,
        severity: str,
        title_en: str,
        title_ar: str,
        body_en: str,
        body_ar: str,
        target_kind: str,
        target_role,
        target_tier,
        target_user_id,
        expires_at,
        resend_of,
        client_request_id: str,
        actor,
    ) -> dict:
        if target_kind == "user":
            _require_uuid(target_user_id, "no_such_target_user")

        payload_hash = _payload_hash(
            type,
            severity,
            title_en,
            title_ar,
            body_en,
            body_ar,
            target_kind,
            target_role,
            target_tier,
            target_user_id,
            expires_at,
        )
        try:
            response = self._client.rpc(
                "admin_create_notification",
                {
                    "p_type": type,
                    "p_severity": severity,
                    "p_title_en": title_en,
                    "p_title_ar": title_ar,
                    "p_body_en": body_en,
                    "p_body_ar": body_ar,
                    "p_target_kind": target_kind,
                    "p_target_role": target_role,
                    "p_target_tier": target_tier,
                    "p_target_user_id": target_user_id,
                    "p_expires_at": expires_at,
                    "p_resend_of": resend_of,
                    "p_client_request_id": client_request_id,
                    "p_request_payload_hash": payload_hash,
                    "p_actor_id": actor.user_id,
                    "p_actor_email": actor.email,
                    "p_request_ip": actor.request_ip,
                    "p_user_agent": actor.user_agent,
                },
            ).execute()
        except Exception as exception:
            raise _refusal_from(exception) from exception
        return getattr(response, "data", None) or {}

    def deactivate(self, notification_id: str, *, actor) -> dict:
        _require_uuid(notification_id, "no_such_notification")
        try:
            response = self._client.rpc(
                "admin_deactivate_notification",
                {
                    "p_notification_id": notification_id,
                    "p_actor_id": actor.user_id,
                    "p_actor_email": actor.email,
                    "p_request_ip": actor.request_ip,
                    "p_user_agent": actor.user_agent,
                },
            ).execute()
        except Exception as exception:
            raise _refusal_from(exception) from exception
        return getattr(response, "data", None) or {}

    def delete(self, notification_id: str, *, actor) -> dict:
        _require_uuid(notification_id, "no_such_notification")
        try:
            response = self._client.rpc(
                "admin_delete_notification",
                {
                    "p_notification_id": notification_id,
                    "p_actor_id": actor.user_id,
                    "p_actor_email": actor.email,
                    "p_request_ip": actor.request_ip,
                    "p_user_agent": actor.user_agent,
                },
            ).execute()
        except Exception as exception:
            raise _refusal_from(exception) from exception
        return getattr(response, "data", None) or {}

    def purge(self, notification_id: str, *, actor) -> dict:
        _require_uuid(notification_id, "no_such_notification")
        try:
            response = self._client.rpc(
                "admin_purge_notification",
                {
                    "p_notification_id": notification_id,
                    "p_actor_id": actor.user_id,
                    "p_actor_email": actor.email,
                    "p_request_ip": actor.request_ip,
                    "p_user_agent": actor.user_agent,
                },
            ).execute()
        except Exception as exception:
            raise _refusal_from(exception) from exception
        return getattr(response, "data", None) or {}

    def list_history(self, *, limit: int, offset: int, status: str) -> tuple:
        response = self._client.rpc(
            "admin_list_notification_history",
            {"p_limit": limit, "p_offset": offset, "p_status": status},
        ).execute()
        rows = getattr(response, "data", None) or []
        total = rows[0]["total_count"] if rows else 0
        return [{k: v for k, v in row.items() if k != "total_count"} for row in rows], total

    def list_active_for_reader(self, user_id: str) -> list:
        response = self._client.rpc(
            "notifications_list_active_for_reader", {"p_user_id": user_id}
        ).execute()
        return getattr(response, "data", None) or []

    def list_history_for_reader(
        self, user_id: str, *, cursor_created_at, cursor_id, limit: int
    ) -> list:
        response = self._client.rpc(
            "notifications_list_history_for_reader",
            {
                "p_user_id": user_id,
                "p_cursor_created_at": cursor_created_at,
                "p_cursor_id": cursor_id,
                "p_limit": limit,
            },
        ).execute()
        return getattr(response, "data", None) or []

    def mark_read(self, notification_id: str, user_id: str, action: str) -> dict:
        _require_uuid(notification_id, "no_such_notification")
        try:
            response = self._client.rpc(
                "notifications_mark_read",
                {"p_notification_id": notification_id, "p_user_id": user_id, "p_action": action},
            ).execute()
        except Exception as exception:
            raise _refusal_from(exception) from exception
        return getattr(response, "data", None) or {}

    def mark_all_read(self, user_id: str) -> int:
        response = self._client.rpc("notifications_mark_all_read", {"p_user_id": user_id}).execute()
        data = getattr(response, "data", None)
        return data if isinstance(data, int) else 0

    def _keyset_ids(self, build_query, column: str):
        """Stream a whole audience in pages, keyed on `column`.

        A generator, not a list, and that is the point: `publish_notification_event`
        consumes it with `islice`, so a broadcast to a hundred thousand accounts
        holds one `_CHUNK_SIZE` batch in memory rather than the whole audience.
        Returning a list here would bound the number of HTTP requests and leave
        peak memory at O(audience) — which is what the first version of this did
        while its own comment claimed otherwise.

        A keyset cursor rather than `.range()` offsets: both queries below are
        ordered by a column with a unique index, so `> last_seen` is exact and
        costs the same on page one thousand as on page one. An offset walk
        re-scans everything it has already returned.

        The reason this exists at all is that both branches of
        `recipients_for_publish` used to fetch the entire audience in one
        response. At four accounts that was optimal; at a hundred thousand it
        is a hundred-thousand-row fetch on a single operator action, and the
        only cap would have been whatever PostgREST's `db-max-rows` happens to
        be — which, if set, TRUNCATES the audience silently rather than
        erroring. Quietly sending to a fraction of the intended readers is the
        worse of the two failures.

        **Which is also why a short page does not end the walk.** `db-max-rows`
        caps a response server-side, so if it is set below `_FETCH_PAGE` then
        EVERY page comes back short and a `len(rows) < _FETCH_PAGE` termination
        would stop after the first one — reintroducing the exact silent
        truncation this method exists to remove, and doing it invisibly. The
        loop therefore continues until a page is genuinely empty. The cost of
        being wrong in this direction is one extra request per send; the cost of
        being wrong in the other direction is an audience quietly cut to the
        server cap.
        """
        cursor = None
        while True:
            query = build_query().order(column).limit(_FETCH_PAGE)
            if cursor is not None:
                query = query.gt(column, cursor)
            rows = getattr(query.execute(), "data", None) or []
            if not rows:
                return

            for row in rows:
                value = row.get(column)
                if value:
                    yield value

            # The cursor must advance or the same page is requested forever.
            # `notification_recipients.user_id` IS nullable — the FK is
            # `on delete set null` for reader anonymisation — so a null key is
            # reachable here, not merely defensive. A null in the last row of a
            # page means the walk cannot continue safely, and stopping is the
            # only correct option: continuing would loop, and skipping would
            # need an ordering that null keys do not have.
            cursor = rows[-1].get(column)
            if not cursor:
                return

    def recipient_ids_for(self, notification_id: str) -> list:
        return self._keyset_ids(
            lambda: (
                self._client.table("notification_recipients")
                .select("user_id")
                .eq("notification_id", notification_id)
            ),
            "user_id",
        )

    def all_enabled_profile_ids(self) -> list:
        return self._keyset_ids(
            lambda: self._client.table("profiles").select("id").eq("is_disabled", False),
            "id",
        )


class InMemoryNotificationBackend:
    """A backend with no database behind it.

    Serves ``?testing=true`` and the browser suite, mirroring every guard the
    real RPCs enforce: actor revalidation, idempotency (hash-matched replay
    vs. conflict), target-existence/disabled checks, recipient eligibility on
    mark-read, and the dismissed/acknowledged-hides-from-active rule.

    ``users`` is a *reference*, not a copy, to the same list
    ``InMemoryAdminBackend`` seeds and mutates — the same sharing pattern
    already used for ``InMemoryAuthAdminDispatcher`` (web/api/app.py) — so a
    role/tier decision made here always agrees with what the admin console
    fixtures say, including after a test disables or promotes a seeded user.
    """

    def __init__(self, users: list) -> None:
        self._users = users
        self._notifications: list[dict] = []
        self._recipients: dict[str, set] = {}
        self._reads: dict[tuple, dict] = {}

    def _actor_ok(self, actor) -> bool:
        # Was `if not actor.user_id: return True` — the double explicitly
        # reported "authorized" for an absent actor, mirroring the production
        # gap that the admin RPCs only checked p_actor_id when it was present.
        # The database now refuses a null actor outright (AD004/AN005), so
        # leaving this as it was would make the suite assert the opposite of
        # what production does.
        if not actor.user_id:
            return False
        acting = next((u for u in self._users if u["id"] == actor.user_id), None)
        return (
            acting is not None and acting.get("role") == "admin" and not acting.get("is_disabled")
        )

    def preview_audience(
        self, *, target_kind: str, target_role, target_tier, target_user_id
    ) -> int:
        if target_kind == "all":
            return sum(1 for u in self._users if not u.get("is_disabled"))
        if target_kind == "role":
            return sum(
                1 for u in self._users if u.get("role") == target_role and not u.get("is_disabled")
            )
        if target_kind == "tier":
            return sum(
                1 for u in self._users if u.get("tier") == target_tier and not u.get("is_disabled")
            )
        if target_kind == "user":
            u = next((u for u in self._users if u["id"] == target_user_id), None)
            return 1 if u and not u.get("is_disabled") else 0
        return 0

    def create(
        self,
        *,
        type: str,
        severity: str,
        title_en: str,
        title_ar: str,
        body_en: str,
        body_ar: str,
        target_kind: str,
        target_role,
        target_tier,
        target_user_id,
        expires_at,
        resend_of,
        client_request_id: str,
        actor,
    ) -> dict:
        if not self._actor_ok(actor):
            raise AdminActionRefused("actor_no_longer_administrator")

        payload_hash = _payload_hash(
            type,
            severity,
            title_en,
            title_ar,
            body_en,
            body_ar,
            target_kind,
            target_role,
            target_tier,
            target_user_id,
            expires_at,
        )

        existing = next(
            (
                n
                for n in self._notifications
                if n["created_by"] == actor.user_id and n["client_request_id"] == client_request_id
            ),
            None,
        )
        if existing is not None:
            if existing["request_payload_hash"] == payload_hash:
                return {**existing, "_replay": True}
            raise AdminActionRefused("idempotency_conflict")

        recipient_ids: set = set()
        if target_kind == "user":
            target = next((u for u in self._users if u["id"] == target_user_id), None)
            if target is None:
                raise AdminActionRefused("no_such_target_user")
            if target.get("is_disabled"):
                raise AdminActionRefused("target_user_disabled")
            target_count = 1
            recipient_ids = {target_user_id}
        elif target_kind == "role":
            recipient_ids = {
                u["id"]
                for u in self._users
                if u.get("role") == target_role and not u.get("is_disabled")
            }
            if not recipient_ids:
                raise AdminActionRefused("no_matching_recipients")
            target_count = len(recipient_ids)
        elif target_kind == "tier":
            recipient_ids = {
                u["id"]
                for u in self._users
                if u.get("tier") == target_tier and not u.get("is_disabled")
            }
            if not recipient_ids:
                raise AdminActionRefused("no_matching_recipients")
            target_count = len(recipient_ids)
        else:
            target_count = sum(1 for u in self._users if not u.get("is_disabled"))

        row = {
            "id": str(uuid.uuid4()),
            "type": type,
            "severity": severity,
            "title_en": title_en,
            "title_ar": title_ar,
            "body_en": body_en,
            "body_ar": body_ar,
            "target_kind": target_kind,
            "target_role": target_role,
            "target_tier": target_tier,
            "target_user_id": target_user_id,
            "target_count": target_count,
            "requires_ack": type == "modal",
            "created_by": actor.user_id,
            "created_by_email": actor.email,
            "client_request_id": client_request_id,
            "request_payload_hash": payload_hash,
            "resend_of": resend_of,
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": expires_at,
            "deactivated_at": None,
            "deactivated_by": None,
            "deleted_at": None,
            "deleted_by": None,
        }
        self._notifications.append(row)
        if recipient_ids:
            self._recipients[row["id"]] = recipient_ids
        return {**row, "_replay": False}

    def deactivate(self, notification_id: str, *, actor) -> dict:
        if not self._actor_ok(actor):
            raise AdminActionRefused("actor_no_longer_administrator")
        row = next((n for n in self._notifications if n["id"] == notification_id), None)
        if row is None:
            raise AdminActionRefused("no_such_notification")
        if row["deleted_at"] is not None:
            raise AdminActionRefused("already_deleted")
        if row["deactivated_at"] is not None:
            raise AdminActionRefused("already_deactivated")
        row["deactivated_at"] = datetime.now(UTC).isoformat()
        row["deactivated_by"] = actor.user_id
        return dict(row)

    def delete(self, notification_id: str, *, actor) -> dict:
        if not self._actor_ok(actor):
            raise AdminActionRefused("actor_no_longer_administrator")
        row = next((n for n in self._notifications if n["id"] == notification_id), None)
        if row is None:
            raise AdminActionRefused("no_such_notification")
        if row["deleted_at"] is not None:
            raise AdminActionRefused("already_deleted")
        row["deleted_at"] = datetime.now(UTC).isoformat()
        row["deleted_by"] = actor.user_id
        return dict(row)

    def purge(self, notification_id: str, *, actor) -> dict:
        if not self._actor_ok(actor):
            raise AdminActionRefused("actor_no_longer_administrator")
        row = next((n for n in self._notifications if n["id"] == notification_id), None)
        if row is None:
            raise AdminActionRefused("no_such_notification")
        if row["deleted_at"] is None:
            raise AdminActionRefused("not_yet_deleted")
        # Mirrors the real RPC: sever inbound "resent from" pointers before
        # removing the row, so purging a resend's source never touches the
        # resend itself (found in live use — the real Postgres FK on
        # notifications.resend_of rejected the delete outright without this).
        for other in self._notifications:
            if other.get("resend_of") == notification_id:
                other["resend_of"] = None
        self._notifications.remove(row)
        self._recipients.pop(notification_id, None)
        for key in [k for k in self._reads if k[0] == notification_id]:
            del self._reads[key]
        return {"id": notification_id, "purged": True}

    def list_history(self, *, limit: int, offset: int, status: str) -> tuple:
        rows = list(reversed(self._notifications))
        if status == "active":
            rows = [r for r in rows if r["deactivated_at"] is None and r["deleted_at"] is None]
        elif status == "deactivated":
            rows = [r for r in rows if r["deactivated_at"] is not None and r["deleted_at"] is None]
        elif status == "deleted":
            rows = [r for r in rows if r["deleted_at"] is not None]

        total = len(rows)
        page = rows[offset : offset + limit]
        out = []
        for r in page:
            reads = [v for k, v in self._reads.items() if k[0] == r["id"]]
            out.append(
                {
                    **r,
                    "served_count": sum(1 for x in reads if x.get("served_at")),
                    "read_count": sum(1 for x in reads if x.get("read_at")),
                    "dismissed_count": sum(1 for x in reads if x.get("dismissed_at")),
                    "acknowledged_count": sum(1 for x in reads if x.get("acknowledged_at")),
                }
            )
        return out, total

    def _eligible(self, notification: dict, user_id: str) -> bool:
        if notification["target_kind"] == "all":
            return True
        return user_id in self._recipients.get(notification["id"], set())

    @staticmethod
    def _reader_view(n: dict, read: dict) -> dict:
        return {
            "id": n["id"],
            "type": n["type"],
            "severity": n["severity"],
            "title_en": n["title_en"],
            "title_ar": n["title_ar"],
            "body_en": n["body_en"],
            "body_ar": n["body_ar"],
            "requires_ack": n["requires_ack"],
            "created_at": n["created_at"],
            "expires_at": n["expires_at"],
            "deactivated_at": n.get("deactivated_at"),
            "read_at": read.get("read_at"),
            "dismissed_at": read.get("dismissed_at"),
            "acknowledged_at": read.get("acknowledged_at"),
        }

    @staticmethod
    def _is_active(notification: dict) -> bool:
        """The three lifecycle conditions, in one place.

        Named because two callers now need them: the active list, which has
        always filtered on all three, and `mark_read`, which until the RN003
        migration checked none of them.
        """
        if notification["deactivated_at"] is not None or notification["deleted_at"] is not None:
            return False
        expires = _parse_iso(notification["expires_at"])
        return expires is None or expires > datetime.now(UTC)

    def list_active_for_reader(self, user_id: str) -> list:
        now_iso = datetime.now(UTC).isoformat()
        out = []
        for n in self._notifications:
            if not self._is_active(n):
                continue
            if not self._eligible(n, user_id):
                continue
            read = self._reads.setdefault((n["id"], user_id), {})
            if read.get("dismissed_at") or read.get("acknowledged_at"):
                continue
            read.setdefault("served_at", now_iso)
            out.append(self._reader_view(n, read))
        return out

    def list_history_for_reader(
        self, user_id: str, *, cursor_created_at, cursor_id, limit: int
    ) -> list:
        rows = [
            n for n in self._notifications if n["deleted_at"] is None and self._eligible(n, user_id)
        ]
        rows.sort(key=lambda n: (n["created_at"], n["id"]), reverse=True)
        if cursor_created_at:
            rows = [
                n for n in rows if (n["created_at"], n["id"]) < (cursor_created_at, cursor_id or "")
            ]
        page = rows[:limit]
        now_iso = datetime.now(UTC).isoformat()
        out = []
        for n in page:
            read = self._reads.setdefault((n["id"], user_id), {})
            read.setdefault("served_at", now_iso)
            out.append(self._reader_view(n, read))
        return out

    def mark_read(self, notification_id: str, user_id: str, action: str) -> dict:
        if action not in ("read", "dismissed", "acknowledged"):
            raise AdminActionRefused("action_type_mismatch")
        n = next((n for n in self._notifications if n["id"] == notification_id), None)
        if n is None:
            raise AdminActionRefused("no_such_notification")
        if action == "dismissed" and n["type"] not in ("toast", "banner"):
            raise AdminActionRefused("action_type_mismatch")
        if action == "acknowledged" and n["type"] != "modal":
            raise AdminActionRefused("action_type_mismatch")
        # Mirrors the RN003 lifecycle checks notifications_mark_read makes, and
        # the three conditions are NOT interchangeable — the difference is which
        # reader surface can still show the row.
        #
        # Deleted: no receipts of any kind. The history RPC filters
        # `deleted_at is null`, so a soft-deleted notification is in no reader
        # surface and any receipt is spurious by construction — yet it still
        # counts, because the purge audit row reports read/dismissed/acknowledged
        # totals before erasing everything.
        if n["deleted_at"] is not None:
            raise AdminActionRefused("notification_no_longer_active")
        # Deactivated or expired: still visible in history, so plain `read` stays
        # legal and only the two live-notice display actions are refused.
        if action in ("dismissed", "acknowledged") and not self._is_active(n):
            raise AdminActionRefused("notification_no_longer_active")
        if not self._eligible(n, user_id):
            raise AdminActionRefused("not_a_recipient")

        now_iso = datetime.now(UTC).isoformat()
        read = self._reads.setdefault((notification_id, user_id), {})
        read.setdefault("served_at", now_iso)
        key = {"read": "read_at", "dismissed": "dismissed_at", "acknowledged": "acknowledged_at"}[
            action
        ]
        read.setdefault(key, now_iso)
        # notification_id/user_id included, not just `dict(read)`: the real
        # RPC returns `to_jsonb(v_row)` over the full user_notification_reads
        # row, which carries its own notification_id column — a shape this
        # double must mirror (see the module docstring) or a Flask-side bug
        # that only collides against that extra column, as
        # handle_notifications_mark_read's did, passes every test here and
        # only shows up against the real database.
        return {"notification_id": notification_id, "user_id": user_id, **read}

    def mark_all_read(self, user_id: str) -> int:
        now_iso = datetime.now(UTC).isoformat()
        count = 0
        for n in self._notifications:
            if n["deleted_at"] is not None or not self._eligible(n, user_id):
                continue
            read = self._reads.setdefault((n["id"], user_id), {})
            read.setdefault("served_at", now_iso)
            if not read.get("read_at"):
                read["read_at"] = now_iso
                count += 1
        return count

    def recipient_ids_for(self, notification_id: str) -> list:
        return list(self._recipients.get(notification_id, set()))

    def all_enabled_profile_ids(self) -> list:
        return [u["id"] for u in self._users if not u.get("is_disabled")]


# ── Purge retention setting ──────────────────────────────────────────────
#
# Deliberately NOT routed through web/services/settings_service.py's
# SettingsService/GENERATION_KEYS — that machinery is purpose-built for the
# five LLM generation fields (model, temperature, ...) and its own
# validate() knows only about them. This is one unrelated integer, so it
# reuses the SAME underlying storage primitive instead (admin_store's
# get_settings/put_settings, backed by the admin_write_settings RPC and the
# single app_settings JSONB document — see supabase/migrations/
# 20260814022601_app_settings.sql's own "the set of settings will grow"
# rationale) without touching the generation-specific validation layer.
_PURGE_RETENTION_SETTINGS_KEY = "notifications_purge_retention_days"


def get_purge_retention_days(admin_backend) -> int:
    """The window, in days, the console's "Purge eligible" bulk action uses
    to decide which already-Deleted rows to include. Manual per-row/selected
    purge never consults this — see admin_purge_notification's own
    docstring for why that is deliberate, not an inconsistency.

    Tolerant of an unavailable backend (falls back to the deployed default,
    same "an outage costs an override, not an answer" reasoning as
    SettingsService's own lenient read) since this is consulted on every
    Notifications tab load, not just a settings save.
    """
    from web.utils.config_loader import config

    default = config.get("notifications", "purge_retention_days", 90)
    if admin_backend is None:
        return default
    try:
        stored = admin_backend.get_settings() or {}
    except Exception:
        logger.error(
            "Purge-retention setting read failed; using the deployed default.", exc_info=True
        )
        return default
    value = stored.get(_PURGE_RETENTION_SETTINGS_KEY)
    return (
        value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default
    )


def set_purge_retention_days(admin_backend, days: int, *, actor) -> int:
    """Raises ValueError for an out-of-range value; the route maps that to 422."""
    if not isinstance(days, int) or isinstance(days, bool) or not (1 <= days <= 3650):
        raise ValueError("purge_retention_days must be an integer between 1 and 3650")
    current = admin_backend.get_settings() or {}
    before = {_PURGE_RETENTION_SETTINGS_KEY: current.get(_PURGE_RETENTION_SETTINGS_KEY)}
    updated = dict(current)
    updated[_PURGE_RETENTION_SETTINGS_KEY] = days
    admin_backend.put_settings(
        updated, actor=actor, before=before, after={_PURGE_RETENTION_SETTINGS_KEY: days}
    )
    return days


def get_notification_backend() -> NotificationBackend | None:
    """The configured backend, or None when privileged reads are unavailable.

    Same contract as ``admin_store.get_admin_backend``: None means TESTING or
    no service-role key, never an error.
    """
    client = get_supabase_admin()
    if client is None:
        return None
    return SupabaseNotificationBackend(client)
