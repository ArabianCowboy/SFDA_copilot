"""The reader's own account page: a data-free shell, and (from Step 5/7 on) an
API that only bearers reach.

Mirrors ``web/api/admin.py``'s two load-bearing decisions, for the same
reasons stated there:

**The page is not gated; the data is.** A document navigation to ``/account``
cannot carry an ``Authorization`` header — Supabase's session lives in
``localStorage``. So ``GET /account`` renders chrome and translated strings
only; nothing account-specific renders until the JS has asked
``/api/identity`` with a token in hand and read the reader's own profile
directly from Supabase (Decision 8 of docs/profile-refactor-plan.md: reads
and preference writes stay on the browser->PostgREST path under RLS).

**Any future ``/api/account/*`` route accepts a bearer header and nothing
else.** Same CSRF reasoning as the console: a cookie-authenticated mutation
here could change a password or delete an account, and this app has no CSRF
protection to answer that with. No such route exists yet — Security actions
(Step 5) and Data-rights actions (Step 7) add them later — but the gate is
built now so the blueprint is not the thing standing between "reads only"
and "the first mutation ships ungated by mistake".
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any, cast

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    make_response,
    render_template,
    request,
    stream_with_context,
)

from web.services.chat_store import ChatBackend, PersistenceUnavailable, export_all_sessions
from web.services.conversation_store import ConversationStore

# datetime.UTC is Python 3.11+; the VPS production floor is 3.10.
UTC = timezone.utc

logger = logging.getLogger(__name__)

account_bp = Blueprint("account", __name__, url_prefix="/account")


# The page shell is the only member and must stay the only member — see the
# module docstring. Default-deny: a route added later is protected by
# omission rather than by somebody remembering to protect it.
_UNGATED_ENDPOINTS = frozenset({"account.page"})


def _bearer_token() -> str | None:
    """The token from an explicit Authorization header, or None.

    Deliberately not ``_get_token_from_request``: that one falls back to a
    cookie and to the Flask session, and a privileged endpoint reachable by
    ambient credentials is a privileged endpoint reachable by cross-site
    request forgery.
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[len("Bearer ") :].strip()
    return token or None


@account_bp.before_request
def _gate() -> Response | tuple[Response, int] | None:
    """Admit any signed-in, non-disabled reader presenting a bearer token."""
    if request.endpoint in _UNGATED_ENDPOINTS:
        return None

    if _bearer_token() is None:
        return jsonify({"error": "bearer_required"}), 401

    # Imported here rather than at module scope: app.py imports this
    # blueprint to register it, so a top-level import back into app.py would
    # be a cycle — the same reason admin.py does this.
    from web.api.app import _authenticate_request

    _identity, early_response = _authenticate_request()
    if early_response is not None:
        return early_response

    # No role check: unlike the console, this surface is every reader's own
    # account. _authenticate_request already refuses a disabled account with
    # account_disabled before returning here.
    return None


@account_bp.route("/", strict_slashes=False, endpoint="page")
def page() -> Response:
    """The account page shell. Renders no account-specific data — see the
    module docstring."""
    from web.api.app import ACCOUNT_MODULE_FILENAMES, MODULE_FILENAMES

    build_map = cast(
        "Callable[[str, Sequence[str]], dict[str, Any]]",
        current_app.jinja_env.globals["_import_map"],
    )

    # Both directories: the account modules import the shared ones — i18n,
    # theme, the icon helper, the Supabase transport, exactly like the
    # console's own import map (admin.py:106-118).
    import_map = build_map("modules", MODULE_FILENAMES)
    import_map["imports"].update(build_map("account", ACCOUNT_MODULE_FILENAMES)["imports"])

    context = current_app.config["base_render_context"](admin=False)
    response = make_response(
        render_template("account.html", **context, module_import_map=import_map)
    )
    # This page is one reader's own record. A search index that surfaced it
    # would be surfacing a URL that only resolves to something real for
    # whoever is signed in when they follow it.
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _persistence_precondition() -> tuple[
    str | None, ChatBackend | None, tuple[Response, int] | None
]:
    """(owner_id, persistence, error) for both Data-rights routes below.

    Mirrors `app.py`'s own `_sidebar_preconditions`: persistence OFF is a
    deployment choice and stays quiet (owner_id/persistence come back falsy,
    no error); persistence ON with no backend reachable is a live
    misconfiguration and says so. Not imported from `app.py` — that
    function is a closure local to `create_app`, not a module-level name.
    """
    from web.api.app import _chat_persistence, _durable_owner

    owner_id = _durable_owner()
    persistence = _chat_persistence()

    if persistence is None and current_app.config.get("CHAT_PERSISTENCE_ENABLED", False):
        return (
            None,
            None,
            (
                jsonify(error="Your data could not be reached.", code="history_unavailable"),
                503,
            ),
        )
    return owner_id, persistence, None


@account_bp.route("/api/export", methods=["GET"], endpoint="export")
def export() -> Response | tuple[Response, int]:
    """Every owned conversation, streamed as NDJSON — one line of metadata,
    then one line per session with its full message history.

    `/account/api/export`, not `/api/account/export` — matching
    `web/api/admin.py`'s own `<prefix>/api/<thing>` convention
    (`/admin/api/settings`, `/admin/api/users`, …) rather than the plan
    prose's `/api/account/*` shorthand, so this surface's URLs stay
    consistent with the console's.

    Scoped by `owner_id` from `g.identity` (set by `_gate`, above), never by
    anything the caller supplies (docs/profile-refactor-plan.md §4: "scoped
    by owner_id = auth.uid(), never by a client-supplied id"). Rate-limited
    2/10min, keyed per reader rather than per IP — wired in `app.py`
    alongside the blueprint registration, because the limiter's own
    `before_request` runs before this blueprint's `_gate` and cannot yet
    read `g.identity` itself (see `_account_export_rate_key`'s docstring).

    A misconfigured deployment (persistence on, backend unreachable) is
    refused with 503 BEFORE the stream starts. A backend that fails PARTWAY
    through cannot get a status change any more — the 200 and the NDJSON
    mimetype are already on the wire — so that failure is reported as a
    trailing NDJSON line instead of a silently truncated file (the same
    "no quiet untruth" posture `/api/chat/history` already takes on a
    fetch failure, adapted to a response that cannot fail after it starts).
    """
    owner_id, persistence, error = _persistence_precondition()
    if error:
        return error

    generated_at = datetime.now(UTC).isoformat()

    def generate():
        yield (
            json.dumps(
                {"export_version": 1, "generated_at": generated_at, "user_id": owner_id},
                ensure_ascii=False,
            )
            + "\n"
        )
        if not owner_id or persistence is None:
            return
        try:
            for session in export_all_sessions(persistence, owner_id):
                yield json.dumps(session, ensure_ascii=False) + "\n"
        except PersistenceUnavailable:
            logger.warning(
                "Export for %s was truncated: history became unreachable mid-stream.",
                owner_id,
                exc_info=True,
            )
            yield (
                json.dumps(
                    {
                        "error": "history_unavailable",
                        "message": "Some conversations could not be read; this export is incomplete.",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    response = Response(stream_with_context(generate()), mimetype="application/x-ndjson")
    filename = f"sfda-copilot-conversations-{datetime.now(UTC):%Y%m%d}.ndjson"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    # This body is every conversation a reader has ever had. Never cached,
    # same reasoning `_no_store` (app.py) applies to a single transcript.
    response.headers["Cache-Control"] = "private, no-store"
    return response


@account_bp.route("/api/conversations", methods=["DELETE"], endpoint="delete_all_conversations")
def delete_all_conversations() -> Response | tuple[Response, int]:
    """Delete every owned conversation. `/account/api/conversations` — see
    `export`'s docstring for the path convention. Named distinctly from
    account deletion (Spec 4 of docs/profile-refactor-plan.md, not built
    here) — this clears chat history; the account, its profile row and its
    auth identity are untouched.

    Refused outright while ANY of the owner's conversations is mid-generation
    — `is_live_for_owner`, the bulk form of the single-delete route's
    `is_live` check (app.py) — for the identical reason that route gives:
    a live stream's `chat_append_turn` finishing after the delete would
    resurrect the row it lands on via `on conflict (id) do nothing`.
    """
    from web.api.app import _generations

    owner_id, persistence, error = _persistence_precondition()
    if error:
        return error

    if not owner_id or persistence is None:
        return jsonify(ok=True, deleted_count=0)

    if _generations().is_live_for_owner(owner_id):
        return jsonify(
            error="An answer is still being generated.",
            code="generation_in_flight",
        ), 409

    try:
        deleted_ids = persistence.delete_all_sessions(owner_id)
    except PersistenceUnavailable:
        logger.warning("Could not delete all conversations for %s.", owner_id, exc_info=True)
        return jsonify(error="Your conversations could not be deleted.", code="delete_failed"), 503

    store: ConversationStore = current_app.config["conversations"]
    for session_id in deleted_ids:
        store.clear(session_id)

    return jsonify(ok=True, deleted_count=len(deleted_ids))
