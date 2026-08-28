"""Realtime push for the Notification Center — a latency optimisation for
already-open tabs, never the source of truth.

``GET /api/notifications/active`` (web/api/app.py) is the guaranteed-delivery
path. This module's only job is telling an open tab "go refetch": every
payload carries no notification content at all, only
``{"notification_id": ..., "revision": ...}`` — REST alone decides what
actually renders. A Realtime message discloses nothing on its own if
intercepted, and it collapses "handle a push" and "handle a reconnect" into
the exact same client refetch code path.

**Request shape, verified via ctx7 against Supabase's own docs (2026-08-23),
closing the plan's own stated verification gate:** the batch broadcast
endpoint (``POST /realtime/v1/api/broadcast``) accepts a per-message
``private`` field — confirmed from
https://github.com/supabase/supabase/blob/master/apps/docs/content/guides/realtime/broadcast.mdx.
One batched request covers every recipient; no per-recipient fan-out is
needed, and none is done here.

**Failure isolation is the whole design.** Every call here is wrapped and
never raises past this module. An admin action must not fail because
Realtime hiccuped, and a broadcast that never arrives costs an open tab one
poll cycle of latency — not a wrong answer, not a dropped write.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Iterator
from itertools import islice

import httpx

logger = logging.getLogger(__name__)

# Short and non-configurable-by-default on purpose: this call sits in the
# response path of an admin mutation (POST /admin/api/notifications and the
# deactivate/delete routes), so a slow or hanging Realtime endpoint must not
# turn into a slow admin console.
_BROADCAST_TIMEOUT = httpx.Timeout(float(os.getenv("SUPABASE_REALTIME_TIMEOUT", "3")), connect=3.0)

# Defensive batching. This deployment's account count is small enough today
# that one request would always suffice, but chunking costs nothing and
# means a future larger 'all' broadcast degrades to "a few extra requests"
# rather than "one oversized request the endpoint rejects".
_CHUNK_SIZE = 500


def _broadcast_url() -> str | None:
    base = os.getenv("SUPABASE_URL")
    if not base:
        return None
    return f"{base.rstrip('/')}/realtime/v1/api/broadcast"


def _service_key() -> str | None:
    # Same both-names-accepted migration path as web/utils/supabase_client.py.
    return os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")


def publish_notification_event(
    recipient_ids: Iterable[str],
    *,
    notification_id: str,
    revision: str,
    event: str = "notify",
) -> None:
    """Best-effort push to every recipient's private channel.

    Fires on create, deactivate, AND delete alike (callers pass a distinct
    ``event`` name per case if the client ever needs to distinguish them;
    today the client treats every event identically — "go refetch active and
    history"). Publishing only on create would leave a deactivated modal
    blocking an already-open tab until its next reload or reconnect, which
    defeats the entire point of an early deactivation.

    ``recipient_ids`` is an ITERABLE, not a list, and that is load-bearing.
    ``recipients_for_publish`` streams the audience a page at a time; consuming
    it with ``islice`` means a broadcast to a hundred thousand accounts holds
    one chunk in memory rather than the whole audience. A ``len()`` or a
    ``list()`` anywhere on this path silently undoes that — which is exactly
    what the first version of this change did while claiming otherwise.
    """
    # Credentials first, and deliberately BEFORE the audience is touched. The
    # previous order tested `if not recipient_ids` first, which on a generator
    # is always truthy and would have pulled the first page out of the database
    # for a deployment that has nowhere to send it.
    url = _broadcast_url()
    key = _service_key()
    if not url or not key:
        # No admin credentials configured — TESTING, or a deployment running
        # without a service-role key. REST polling still delivers; there is
        # nothing here to log as an error, only as an absence.
        logger.debug(
            "Realtime broadcast skipped for notification %s: no service-role credentials.",
            notification_id,
        )
        return

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    try:
        recipients = iter(recipient_ids)
        first_chunk = list(islice(recipients, _CHUNK_SIZE))
        if not first_chunk:
            return

        with httpx.Client(timeout=_BROADCAST_TIMEOUT) as client:
            chunk = first_chunk
            while chunk:
                messages = [
                    {
                        "topic": f"notify:user:{user_id}",
                        "event": event,
                        "payload": {"notification_id": notification_id, "revision": revision},
                        "private": True,
                    }
                    for user_id in chunk
                ]
                response = client.post(url, json={"messages": messages}, headers=headers)
                if response.status_code >= 400:
                    logger.warning(
                        "Realtime broadcast for notification %s returned %s; "
                        "reader tabs fall back to their next poll.",
                        notification_id,
                        response.status_code,
                    )
                chunk = list(islice(recipients, _CHUNK_SIZE))
    except httpx.TransportError:
        # The same outage family web/api/app.py's _is_upstream_outage treats
        # as "could not reach the thing that knows" — here it just means the
        # push is skipped, not that anything failed for the admin or reader.
        logger.warning(
            "Realtime broadcast unreachable for notification %s; "
            "reader tabs fall back to their next poll.",
            notification_id,
            exc_info=True,
        )
    except Exception:
        logger.warning(
            "Unexpected error broadcasting notification %s over Realtime.",
            notification_id,
            exc_info=True,
        )


def recipients_for_publish(backend, notification: dict) -> Iterator[str]:
    """Resolve who to push to for one notification's create/deactivate/delete.

    'all' targets have no recipient snapshot (delivery stays dynamic — see
    notification_store.py), so the push list is every currently-enabled
    account; role/tier/user targets read back the snapshot taken at send
    time, which is what "who saw this modal" must agree with regardless of a
    later role change.

    Returns an ITERATOR, and both branches stream. `all_enabled_profile_ids`
    was the branch the plan named, but `recipient_ids_for` — the role, tier and
    user targets, which are the more common send — was on exactly the same
    unbounded path. The in-memory doubles return plain lists, which iterate
    fine; only the Supabase backend has pages to stream.
    """
    if notification.get("target_kind") == "all":
        return iter(backend.all_enabled_profile_ids())
    return iter(backend.recipient_ids_for(notification["id"]))
