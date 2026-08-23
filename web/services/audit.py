"""The record of what operators did.

The console's whole claim is that administrative acts are accountable, and that
claim is only as good as the weakest moment in the write. Two separate
statements — change the thing, then log it — can half-succeed, and the half that
fails is always the one that mattered: a change nobody can attribute.

So a mutation and its audit row go through **one Postgres function**, whose body
is a single transaction. Either both rows land or neither does. That makes
"every change is recorded" a property of the database rather than a promise
about the application code, which is the difference between an audit trail and
a logging convention.

Reads of the log are not themselves audited. Auditing reads of a surface only
administrators can reach produces noise that buries the signal. The line is
drawn at *state changes*, plus any access to a reader's own content — which is
why the conversation work, when it lands, will be the exception.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from flask import request

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditActor:
    """Who is acting, and from where.

    ``email`` is carried alongside ``user_id`` and stored denormalised, because
    the account may later be deleted and a row that can no longer say who acted
    has lost the thing it exists to record.
    """

    user_id: str | None
    email: str | None
    request_ip: str | None = None
    user_agent: str | None = None


def actor_from_request(identity) -> AuditActor:
    """Build an actor from the resolved identity plus the request.

    ``request.remote_addr`` is ProxyFix-aware — the app installs it when
    deployed behind a reverse proxy — so this is the client address rather than
    the proxy's, where that is configured.
    """
    user_agent = request.headers.get("User-Agent")
    return AuditActor(
        user_id=getattr(identity, "user_id", None),
        email=getattr(identity, "email", None),
        request_ip=request.remote_addr,
        # Truncated: a header is attacker-controlled and unbounded, and nothing
        # reads more than the leading identification anyway.
        user_agent=user_agent[:400] if user_agent else None,
    )


def changed_keys(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The diff, as ``{key: {"from": x, "to": y}}`` — changed keys only.

    Storing whole documents makes the one field that actually moved impossible
    to find, which defeats the point of keeping the record at all.
    """
    keys = set(before) | set(after)
    return {
        key: {"from": before.get(key), "to": after.get(key)}
        for key in sorted(keys)
        if before.get(key) != after.get(key)
    }


@dataclass(frozen=True)
class AuditEntry:
    """One recorded action, as the console renders it."""

    id: int
    occurred_at: str
    actor_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    before: dict | None
    after: dict | None
    request_ip: str | None
    note: str | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> AuditEntry:
        return cls(
            id=row["id"],
            occurred_at=row["occurred_at"],
            actor_email=row.get("actor_email"),
            action=row["action"],
            target_type=row.get("target_type"),
            target_id=row.get("target_id"),
            before=row.get("before"),
            after=row.get("after"),
            request_ip=row.get("request_ip"),
            note=row.get("note"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "occurred_at": self.occurred_at,
            "actor_email": self.actor_email,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "before": self.before,
            "after": self.after,
            "request_ip": self.request_ip,
            "note": self.note,
        }


def list_entries(
    backend,
    *,
    limit: int = 50,
    offset: int = 0,
    target_type: str | None = None,
    target_id: str | None = None,
) -> list[AuditEntry]:
    """Most recent first. Paginated server-side.

    No client-side sorting: this is a window onto a larger table, and letting
    the browser reorder the page it happens to hold would present a false
    ordering of the whole.
    """
    if backend is None:
        return []
    rows = backend.list_audit(
        limit=min(limit, 200),
        offset=max(offset, 0),
        target_type=target_type,
        target_id=target_id,
    )
    return [AuditEntry.from_row(row) for row in rows]
