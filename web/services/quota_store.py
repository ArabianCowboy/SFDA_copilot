"""The reader's daily message allowance: the seam between a question and the counter.

Scope
-----
Three methods, the reader path only: claim, release, status. Tier CRUD and
``set_reader_quota`` live on ``AdminBackend`` (``admin_store.py``) instead,
because ``admin.py`` consumes ``admin_backend()`` exclusively and every audited,
actor-carrying mutation in this repo already lives there. Two protocols owning
tier management would be the kind of split that drifts.

Why not Flask-Limiter
---------------------
Its storage is ``memory://``, which does not survive a deploy — fine for a burst
limit, useless for a daily allowance. This is a durable row and one atomic
``insert … on conflict … where used < limit returning`` inside a
``security definer`` RPC. See ``docs/reader-quota-plan.md`` §2.

Failure posture, and the one place it is NOT fail-open
------------------------------------------------------
An allowance is not a credential, so a transport fault must not take the product
down: :meth:`claim` returns ``None`` and the caller streams the answer uncounted.
But a fault that is *permanent until a human acts* is a different thing. A
missing function, a missing grant, a stale PostgREST schema cache after a deploy
— under a blanket fail-open those convert a broken deploy into unmetered access
for every authenticated reader, indefinitely, with a log line as the only
evidence. Those raise :class:`QuotaUnavailable` and the route answers 503.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from web.utils.supabase_client import get_supabase_admin

logger = logging.getLogger(__name__)

# The day boundary. Owner decision, 2026-09-03: the reader's day, not UTC, so the
# allowance resets when their day does rather than at 03:00 local. The RPC owns
# the real arithmetic (one named constant in SQL); this mirror exists only for
# the in-memory double, and MUST agree with it.
QUOTA_TIMEZONE = "Asia/Riyadh"

# PostgREST / Postgres codes that mean "this deployment is broken", not "the
# database is briefly unwell". See the module docstring.
_CONFIGURATION_FAULTS = frozenset(
    {
        "PGRST202",  # no function matching the name/signature in the schema cache
        "PGRST203",  # ambiguous overload
        "PGRST301",  # JWT/role problem reaching the function
        "42883",  # undefined_function
        "42501",  # insufficient_privilege
    }
)


class QuotaUnavailable(RuntimeError):
    """A configuration-shaped fault. The route must fail CLOSED on this."""


@dataclass(frozen=True)
class QuotaClaim:
    """The result of trying to spend one message.

    ``day`` is carried rather than recomputed. A claim at 23:59:59 whose
    retrieval fails at 00:00:01 must refund the day it charged, not the new one —
    which would either decrement a different day's count or find no row at all.
    """

    allowed: bool
    used: int
    limit: int
    remaining: int
    resets_at: str
    tier_key: str | None
    day: str

    def as_frame(self) -> dict[str, Any]:
        """The shape the `done` frame, the blocking response and the 429 carry."""
        return {
            "used": self.used,
            "limit": self.limit,
            "remaining": self.remaining,
            "resets_at": self.resets_at,
        }


@dataclass(frozen=True)
class QuotaStatus:
    """What `/api/identity` reports, including the tier's bilingual labels."""

    used: int
    limit: int
    remaining: int
    resets_at: str
    tier_key: str | None
    tier_label_en: str | None
    tier_label_ar: str | None
    override_limit: int | None
    override_expires_at: str | None

    def as_identity_field(self) -> dict[str, Any]:
        return {
            "used": self.used,
            "limit": self.limit,
            "remaining": self.remaining,
            "resets_at": self.resets_at,
            "tier": {
                "key": self.tier_key,
                "label_en": self.tier_label_en,
                "label_ar": self.tier_label_ar,
            },
            "override": self.override_limit,
            "override_expires_at": self.override_expires_at,
        }


class QuotaBackend(Protocol):
    def claim(self, user_id: str, default_limit: int) -> QuotaClaim: ...

    def release(self, user_id: str, day: str) -> None: ...

    def status(self, user_id: str, default_limit: int) -> QuotaStatus: ...


def _fault_code(exc: Exception) -> str | None:
    """Best-effort SQLSTATE / PostgREST code off whatever the client raised."""
    for attr in ("code", "pgcode"):
        value = getattr(exc, attr, None)
        if isinstance(value, str) and value:
            return value
    details = getattr(exc, "args", None)
    if details and isinstance(details[0], dict):
        code = details[0].get("code")
        if isinstance(code, str):
            return code
    return None


class SupabaseQuotaBackend:
    """The real backend. Three RPCs, service-role only."""

    def __init__(self, client: Any) -> None:
        self._client = client
        # Process-local, and deliberately not persisted: it means "consecutive
        # faults since this worker started", which is what the console label says.
        # The realistic failure is a stale schema cache right after a deploy, and
        # without a counter that window is invisible apart from a log line.
        self.fault_count = 0

    def _rpc(self, name: str, args: dict[str, Any]) -> Any:
        try:
            response = self._client.rpc(name, args).execute()
        except Exception as exc:
            self.fault_count += 1
            code = _fault_code(exc)
            if code in _CONFIGURATION_FAULTS:
                logger.error(
                    "Quota RPC %s is unreachable (%s) — this is a DEPLOYMENT fault, not an "
                    "outage, so the request fails closed. Check the migration applied and the "
                    "grant to service_role.",
                    name,
                    code,
                    exc_info=True,
                )
                raise QuotaUnavailable(name) from exc
            raise
        self.fault_count = 0
        return response.data

    def claim(self, user_id: str, default_limit: int) -> QuotaClaim:
        rows = self._rpc(
            "chat_claim_daily_message",
            {"p_user_id": user_id, "p_default_limit": default_limit},
        )
        row = rows[0] if rows else {}
        return QuotaClaim(
            allowed=bool(row.get("allowed")),
            used=int(row.get("used") or 0),
            limit=int(row.get("limit") or 0),
            remaining=int(row.get("remaining") or 0),
            resets_at=str(row.get("resets_at") or ""),
            tier_key=row.get("tier_key"),
            day=str(row.get("day") or ""),
        )

    def release(self, user_id: str, day: str) -> None:
        self._rpc("chat_release_daily_message", {"p_user_id": user_id, "p_day": day})

    def status(self, user_id: str, default_limit: int) -> QuotaStatus:
        rows = self._rpc(
            "get_reader_quota", {"p_user_id": user_id, "p_default_limit": default_limit}
        )
        row = rows[0] if rows else {}
        return QuotaStatus(
            used=int(row.get("used") or 0),
            limit=int(row.get("limit") or 0),
            remaining=int(row.get("remaining") or 0),
            resets_at=str(row.get("resets_at") or ""),
            tier_key=row.get("tier_key"),
            tier_label_en=row.get("tier_label_en"),
            tier_label_ar=row.get("tier_label_ar"),
            override_limit=row.get("override_limit"),
            override_expires_at=row.get("override_expires_at"),
        )


class InMemoryQuotaBackend:
    """The offline double.

    IT MUST IMPLEMENT THE SAME RESOLUTION AS THE RPC, LEG FOR LEG, WINDOW
    INCLUDED. §10 drives every window and rollover case through this class, so a
    double that quietly ignored the window would let all of those tests pass
    against logic the database does not have — the failure mode CLAUDE.md names
    as "a test that mocks the function under test proves nothing".

    Where the two disagree, the DATABASE is right: `supabase/tests/quota_behaviour.test.sql`
    is the authority on resolution semantics and this is a convenience. Any change
    to the order or the window clause is made in the SQL first and here second, in
    the same commit.
    """

    def __init__(self, tiers: dict[str, dict[str, Any]] | None = None) -> None:
        self._lock = threading.Lock()
        # Shared with InMemoryAdminBackend by injection, so a test that assigns a
        # tier or sets a windowed override sees the changed limit on the next claim.
        self.tiers: dict[str, dict[str, Any]] = (
            tiers
            if tiers is not None
            else {
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
        )
        self.profile_tiers: dict[str, str] = {}
        self.overrides: dict[str, dict[str, Any]] = {}
        self.usage: dict[tuple[str, str], int] = {}
        self.fault_count = 0
        # Seam for rollover tests. Returns an aware datetime; tests replace it
        # rather than sleeping.
        self._now = lambda: datetime.now(timezone.utc)

    # -- the same four legs the RPC resolves, in the same order ----------------
    def _today(self) -> str:
        # +03:00 fixed. Riyadh has no daylight saving, which is why a fixed offset
        # is honest here and would not be for most zones.
        return (self._now().astimezone(timezone(timedelta(hours=3)))).date().isoformat()

    def _resets_at(self, day: str) -> str:
        tz = timezone(timedelta(hours=3))
        midnight = datetime.fromisoformat(day) + timedelta(days=1)
        return midnight.replace(tzinfo=tz).isoformat()

    @staticmethod
    def _as_instant(value: Any) -> datetime | None:
        """Accept a datetime OR an ISO string, because both reach this table.

        The admin route hands through whatever JSON carried (an ISO string), while
        a test constructing an override directly is likelier to pass a datetime.
        Comparing the two raises `TypeError` at claim time -- found by driving the
        console route end to end rather than by unit-testing the double alone.
        """
        if value is None or isinstance(value, datetime):
            return value
        try:
            text = str(value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
        except (TypeError, ValueError):
            logger.warning("quota: unparseable override window %r; treating as absent", value)
            return None
        # A naive stamp is read as UTC rather than compared against an aware one.
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _override_in_force(self, user_id: str) -> dict[str, Any] | None:
        row = self.overrides.get(user_id)
        if row is None:
            return None
        now = self._now()
        starts = self._as_instant(row.get("starts_at"))
        expires = self._as_instant(row.get("expires_at"))
        if starts is not None and now < starts:
            return None
        if expires is not None and now >= expires:
            return None
        return row

    def _resolve(self, user_id: str, default_limit: int) -> tuple[int, str | None]:
        override = self._override_in_force(user_id)
        tier_key = self.profile_tiers.get(user_id)
        tier = self.tiers.get(tier_key) if tier_key else None
        free = self.tiers.get("free")
        if override is not None:
            limit = override["daily_message_limit"]
        elif tier is not None:
            limit = tier["daily_message_limit"]
        elif free is not None:
            limit = free["daily_message_limit"]
        else:
            logger.warning("quota: no tier resolved for %s; using the shipped default", user_id)
            limit = default_limit
        return int(limit), (tier_key or ("free" if free is not None else None))

    def claim(self, user_id: str, default_limit: int) -> QuotaClaim:
        with self._lock:
            day = self._today()
            limit, tier_key = self._resolve(user_id, default_limit)
            used = self.usage.get((user_id, day), 0)
            # The zero guard: a limit of 0 must refuse the FIRST claim of the day,
            # which an upsert's INSERT branch would not.
            if limit >= 1 and used < limit:
                used += 1
                self.usage[(user_id, day)] = used
                allowed = True
            else:
                allowed = False
            return QuotaClaim(
                allowed=allowed,
                used=used,
                limit=limit,
                remaining=max(0, limit - used) if allowed else 0,
                resets_at=self._resets_at(day),
                tier_key=tier_key,
                day=day,
            )

    def release(self, user_id: str, day: str) -> None:
        with self._lock:
            key = (user_id, day)
            if key in self.usage:
                self.usage[key] = max(0, self.usage[key] - 1)

    def status(self, user_id: str, default_limit: int) -> QuotaStatus:
        with self._lock:
            day = self._today()
            limit, tier_key = self._resolve(user_id, default_limit)
            used = self.usage.get((user_id, day), 0)
            tier = self.tiers.get(tier_key) if tier_key else None
            override = self._override_in_force(user_id)
            expires = self._as_instant(override.get("expires_at")) if override else None
            return QuotaStatus(
                used=used,
                limit=limit,
                remaining=max(0, limit - used),
                resets_at=self._resets_at(day),
                tier_key=tier_key,
                tier_label_en=(tier or {}).get("label_en"),
                tier_label_ar=(tier or {}).get("label_ar"),
                override_limit=(override or {}).get("daily_message_limit"),
                override_expires_at=expires.isoformat() if expires else None,
            )


def get_quota_backend() -> SupabaseQuotaBackend | None:
    """The real backend, or None when this deployment has no database.

    None is not an error — the same posture `get_chat_backend` takes. A
    Supabase-less install answers questions without counting them.
    """
    client = get_supabase_admin()
    if client is None:
        return None
    return SupabaseQuotaBackend(client)


__all__ = [
    "QUOTA_TIMEZONE",
    "InMemoryQuotaBackend",
    "QuotaBackend",
    "QuotaClaim",
    "QuotaStatus",
    "QuotaUnavailable",
    "SupabaseQuotaBackend",
    "get_quota_backend",
]
