"""The reader's own account page: a data-free shell, and (from Step 5/7 on) an
API that only bearers reach.

Mirrors ``web/api/admin.py``'s two load-bearing decisions, for the same
reasons stated there:

**The page is not gated; the data is.** A document navigation to ``/account``
cannot carry an ``Authorization`` header — Supabase's session lives in
``localStorage``. So ``GET /account`` renders chrome and translated strings
only; nothing account-specific renders until the JS has asked
``/api/identity`` with a token in hand and read the reader's own profile
directly from Supabase (docs/ARCHITECTURE.md#account-page-and-profile;
reasoning in docs/archive/2026-08-23_profile-refactor.md, Decision 8): reads
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
import re
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any, cast

from flask import (
    Blueprint,
    Response,
    current_app,
    g,
    jsonify,
    make_response,
    render_template,
    request,
    session,
    stream_with_context,
)

from web.services.chat_store import PersistenceUnavailable, export_all_sessions
from web.services.conversation_store import ConversationStore
from web.utils.supabase_client import get_supabase_admin

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
    anything the caller supplies (docs/ARCHITECTURE.md#account-page-and-profile;
    reasoning in docs/archive/2026-08-23_profile-refactor.md §4: "scoped
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
    # Imported here, not at module scope: app.py imports this blueprint, so a
    # top-level import back would be a cycle (see `_gate`).
    from web.api.app import _persistence_preconditions

    owner_id, persistence, error = _persistence_preconditions("Your data could not be reached.")
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
    account deletion (docs/ARCHITECTURE.md#account-deletion-and-trust;
    reasoning in docs/archive/2026-08-23_profile-refactor.md, Spec 4, superseded)
    — this clears chat history; the account, its profile row and its
    auth identity are untouched.

    Refused outright while ANY of the owner's conversations is mid-generation
    — `is_live_for_owner`, the bulk form of the single-delete route's
    `is_live` check (app.py) — for the identical reason that route gives:
    a live stream's `chat_append_turn` finishing after the delete would
    resurrect the row it lands on via `on conflict (id) do nothing`.

    Deliberately NOT refused for an owner with a live deletion saga
    (docs/ARCHITECTURE.md#account-deletion-and-trust; reasoning in
    docs/archive/2026-09-18_account-and-trust.md §3-M4): the saga is going to purge these
    very transcripts at grace expiry anyway, so refusing their early removal
    protects nothing and strips the one agency — besides export and cancel —
    a reader still has during grace. The saga's own purge is unaffected by
    what this deletes first (it deletes by owner_id, idempotently).
    """
    from web.api.app import _generations, _persistence_preconditions

    owner_id, persistence, error = _persistence_preconditions("Your data could not be reached.")
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


@account_bp.route("/api/consent/grant", methods=["POST"], endpoint="consent_grant")
def consent_grant() -> Response | tuple[Response, int]:
    """Record a marketing-consent GRANT for the caller's own account.

    `/account/api/consent/grant` — the path convention is `export`'s
    (`/account/api/*`, not `/api/account/*`). The grant half of the consent
    carve-out (docs/ARCHITECTURE.md#account-page-and-profile and
    docs/ARCHITECTURE.md#account-deletion-and-trust; reasoning in
    docs/archive/2026-09-18_account-and-trust.md §3, D5): withdrawing
    stays browser-direct through `update_own_marketing_consent` so it keeps
    working while disabled, but granting is Flask-mediated so the version is
    stamped server-side and a disabled account never reaches it.

    A DISABLED ACCOUNT IS REFUSED BY `_gate` ABOVE, not by a check here:
    `_gate` runs `_authenticate_request`, which answers
    `account_disabled` before this view runs. Do not add a second disabled
    check — and do not weaken `_gate` without re-reading this docstring.

    The owner comes from `g.identity` (set by `_gate`), never from the
    request body. The policy version comes from `PRIVACY_POLICY_VERSION`
    (single source in `web/api/app.py`); the body may carry only `language`
    and `surface`, and a client-sent version or user id is not read at all.
    Rate-limited per reader in `app.py` beside `account_bulk_delete_api`.
    """
    # Imported here, not at module scope: app.py imports this blueprint, so a
    # top-level import back would be a cycle (see `_gate`).
    from web.api.app import PRIVACY_POLICY_VERSION

    identity = getattr(g, "identity", None)
    owner_id = getattr(identity, "user_id", None) if identity is not None else None
    if not owner_id:
        return jsonify({"error": "identity_unavailable"}), 503

    data = request.get_json(silent=True) or {}
    language = data.get("language")
    surface = data.get("surface", "account")

    if language not in ("en", "ar"):
        return jsonify({"error": "invalid_payload"}), 400
    if not isinstance(surface, str) or surface != surface.strip() or not 1 <= len(surface) <= 32:
        return jsonify({"error": "invalid_payload"}), 400

    client = get_supabase_admin()
    if client is None:
        return jsonify({"error": "consent_unavailable"}), 503

    try:
        client.rpc(
            "grant_marketing_consent",
            {
                "p_owner_id": owner_id,
                "p_policy_version": PRIVACY_POLICY_VERSION,
                "p_language": language,
                "p_surface": surface,
            },
        ).execute()
    except Exception as exc:
        # DL007 (supabase/pending/14): a live deletion saga refuses the grant
        # direction — collecting a fresh marketing permission from someone who
        # has asked to be erased. Answered as its own 409 with its own
        # reader-facing string, not as the generic outage below: the reader
        # should be told why, and withdrawing stays available throughout.
        if _saga_error_code(exc) == "DL007":
            logger.warning("Consent grant refused for %s: live deletion saga.", owner_id)
            return jsonify({"error": "deletion_pending"}), 409
        logger.warning("Consent grant failed for %s.", owner_id, exc_info=True)
        return jsonify({"error": "consent_unavailable"}), 503

    return jsonify(ok=True)


# ── Self-serve account deletion (docs/ARCHITECTURE.md#account-deletion-and-trust;
# reasoning in docs/archive/2026-09-18_account-and-trust.md §3-M4/M5) ──

_DL_CODE = re.compile(r"\bDL00[1-7]\b")


def _deletion_self_serve_enabled() -> bool:
    """The deploy switch for the whole deletion feature (config.yaml
    ``server.account_deletion_self_serve_enabled``, mirrored into app config
    by ``_configure_app``).

    Default OFF: the code deploys before the saga schema and the reconcile
    timer, and while either is missing the deletion UI and the privacy copy
    must not promise a feature that answers 503 — or accepts requests
    nothing drives. While off the three deletion routes below answer 404,
    the account page renders no deletion card, and /privacy renders the
    pre-self-serve retention wording. Read at request time (not import
    time) so tests can flip it per case.
    """
    return bool(current_app.config.get("DELETION_SELF_SERVE_ENABLED", False))


def _saga_error_code(exception: BaseException) -> str | None:
    """The DL-code a saga RPC raised with, or None.

    The contract lives in ``supabase/pending/07_account_deletions.sql``: every
    saga refusal raises a distinct ``DL001``–``DL007`` errcode, so the Flask
    side branches on the code, never on prose. Read ``.code`` first (the
    PostgREST error model carries it); fall back to scanning the message,
    because a future SDK may surface the code only there.
    """
    code = getattr(exception, "code", None)
    if isinstance(code, str) and code:
        return code
    raw = getattr(exception, "_raw_error", None)
    if isinstance(raw, dict) and isinstance(raw.get("code"), str) and raw["code"]:
        return str(raw["code"])
    try:
        match = _DL_CODE.search(str(exception))
    except Exception:
        return None
    return match.group(0) if match else None


def _expected_deletion_confirmations() -> tuple[str, ...]:
    """The typed-confirmation words the request route accepts, one per language.

    Read from the catalogues rather than hardcoded, so the word the UI shows
    (``page.account.deletionConfirmWord``) and the word the server checks
    cannot drift: a hardcoded copy here would accept yesterday's word after
    the copy changed, or reject today's.
    """
    from web.utils.i18n import load_catalog

    words: list[str] = []
    for lang in ("en", "ar"):
        try:
            word = load_catalog(lang)["page"]["account"].get("deletionConfirmWord")
        except Exception:
            word = None
        if isinstance(word, str) and word.strip():
            words.append(word.strip())
    return tuple(words)


def _verify_current_password(email: str | None, password: str) -> bool | None:
    """Step-up: is ``password`` the reader's CURRENT password? True/False/unknown.

    Verified by attempting a GoTrue password sign-in for the caller, through
    the anon client — the same ``signInWithPassword`` the browser's own login
    uses (``static/js/modules/services.js``), executed here so the answer is
    server-observed rather than client-asserted. A bearer token alone must not
    delete an account: on a shared machine the token is the ordinary case
    (``docs/ARCHITECTURE.md:378``).

    The password-change nonce is NOT reused here: it is consumed only by
    GoTrue's ``updateUser`` in the browser and is not server-verifiable.

    True means correct, False means GoTrue refused the credential, None means
    the check itself could not run (no client, transport failure) — which is
    an outage, not a wrong password, and must not answer 401.

    The password is NEVER logged and NEVER placed in an exception message or
    an audit row: only True/False/None leaves this function.
    """
    verifier = current_app.config.get("deletion_password_verifier")
    if verifier is not None:
        return verifier(email, password)

    from web.utils.supabase_client import get_supabase

    try:
        supabase = get_supabase()
    except Exception:
        # TESTING (where the factory returns None via assert) or a missing
        # client: the check cannot run.
        logger.warning("Deletion step-up unavailable: no Supabase client.")
        return None
    if supabase is None:  # pragma: no cover - get_supabase asserts non-None
        return None
    if not email:
        # No address to verify against (a provider that omits id AND email
        # leaves `_authenticate_request` with neither) — the check cannot run.
        logger.warning("Deletion step-up unavailable: no email on the identity.")
        return None

    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:
        # GoTrue answered with a refusal (wrong password, most likely) or the
        # transport failed. Classified by `classify_admin_failure` rather than
        # by a second hand-rolled rule here: it is the same three-shape split,
        # already verified against the vendored SDK, and a duplicate of it
        # would drift. `auth_admin_unreachable` is every shape where the
        # provider did not answer — that is an outage, and this repository's
        # contract is that an outage is a 503 and never a 401
        # (`docs/ARCHITECTURE.md`), because answering "wrong password" to a
        # provider blip tells the reader something false about their own
        # credential.
        from web.services.auth_admin import classify_admin_failure

        code, _ambiguous = classify_admin_failure(exc)
        if code != "auth_admin_unreachable":
            # The provider understood the credential and declined it: wrong
            # password. Logged with the owner id only — never the password,
            # never the provider's raw message.
            caller = getattr(g, "identity", None)
            logger.warning(
                "Deletion step-up refused for owner %s.",
                getattr(caller, "user_id", "unknown"),
            )
            return False
        logger.warning("Deletion step-up could not reach the provider.", exc_info=True)
        return None

    user = getattr(response, "user", None) or getattr(getattr(response, "data", None), "user", None)
    return user is not None


def _step_up_rpc(name: str, owner_id: str, default: Any) -> Any:
    """One step-up throttle RPC, service-role, failing OPEN to ``default``.

    Deliberately fails open rather than closed. This is a rate limit, not an
    authorization check: the password verification below is what actually
    guards the account, and a throttle that turns a database blip into "you
    cannot delete your account" would break the feature to protect a control.
    A refusal is logged so the failure is visible rather than silent.
    """
    client = get_supabase_admin()
    if client is None:
        logger.warning("Step-up throttle unavailable for %s: no admin client.", owner_id)
        return default
    try:
        response = client.rpc(name, {"p_owner_id": owner_id}).execute()
    except Exception:
        logger.warning("Step-up throttle call %s failed for %s.", name, owner_id, exc_info=True)
        return default
    data = getattr(response, "data", None)
    return default if data is None else data


def _step_up_is_locked_out(owner_id: str) -> bool:
    """True while this account is inside a step-up lockout window.

    Compared with ``is True`` rather than coerced with ``bool()``: both RPCs
    return a plain boolean, and anything else is a contract the caller does not
    understand. Coercing would make a non-empty payload — ``{"ok": True}``, an
    error envelope — read as "locked", which fails CLOSED and contradicts the
    fail-open posture documented on ``_step_up_rpc``. The throttle refusing a
    legitimate deletion is the one outcome worse than the throttle missing.
    """
    return _step_up_rpc("step_up_is_locked_out", owner_id, False) is True


def _record_step_up_failure(owner_id: str) -> bool:
    """Record one wrong password. True if that attempt tripped the lockout.

    Strict for the same reason as above: an unrecognised payload must not
    escalate an ordinary wrong-password refusal into a lockout.
    """
    return _step_up_rpc("record_step_up_failure", owner_id, False) is True


def _clear_step_up_failures(owner_id: str) -> None:
    """Forget this account's failures after a correct password."""
    _step_up_rpc("clear_step_up_failures", owner_id, None)


def _saga_rpc(name: str, params: dict) -> Any:
    """Call one saga RPC through the service-role client, returning its data."""
    client = get_supabase_admin()
    if client is None:
        return None
    return client.rpc(name, params).execute()


@account_bp.route("/api/deletion", methods=["POST"], endpoint="deletion_request")
def deletion_request() -> Response | tuple[Response, int]:
    """Request self-serve deletion of the caller's OWN account.

    ``/account/api/deletion`` — the ``/account/api/*`` path convention (see
    ``export``). The owner comes from ``g.identity``, never from the body.
    Two gates before the saga RPC runs:

    1. Step-up: the body carries the reader's CURRENT password, verified
       server-side (see ``_verify_current_password``). A wrong password is a
       401 with its own code, on the same tight limit as the request itself.
    2. Typed confirmation: the body carries the localized confirmation word
       the UI shows; anything else is a 400.

    Then ``account_deletion_request`` (slice 2a, ``supabase/pending/10``),
    then ``sign_out_all`` with THIS session's JWT — global scope kills every
    refresh token of the account, including a thief's, WITHOUT touching the
    password, so the real owner signs back in with the password they still
    know and cancels — then the Flask session is cleared.

    The RPC refuses administrators itself (``DL003``); this route surfaces
    that refusal, it does not re-implement it. Rate-limited per reader in
    ``app.py`` beside ``account_consent_grant_api``.

    While the self-serve deploy switch is OFF this route answers 404: the
    feature is not live yet (schema and/or reconcile timer missing), and a
    503 would read as a transient outage of something that exists.
    """
    if not _deletion_self_serve_enabled():
        return jsonify({"error": "deletion_unavailable"}), 404

    identity = getattr(g, "identity", None)
    owner_id = getattr(identity, "user_id", None) if identity is not None else None
    email = getattr(identity, "email", None) if identity is not None else None
    if not owner_id:
        return jsonify({"error": "identity_unavailable"}), 503

    data = request.get_json(silent=True) or {}
    password = data.get("password")
    confirmation = data.get("confirmation")
    if not isinstance(password, str) or not password:
        return jsonify({"error": "invalid_payload"}), 400
    if (
        not isinstance(confirmation, str)
        or confirmation.strip() not in _expected_deletion_confirmations()
    ):
        return jsonify({"error": "invalid_payload"}), 400

    # The durable lockout is checked BEFORE the provider call, not after, and
    # that ordering is the point of it. The server-side sign-in below reaches
    # GoTrue from this host's single address, which blinds GoTrue's own per-IP
    # limiter to the guesser's real one — the reason `POST /auth/login` was
    # deleted (`docs/ARCHITECTURE.md:346-353`). The Flask limit in front of
    # this route is `memory://` and resets on every worker recycle, so it is
    # not the floor it looks like. A locked-out caller must produce no round
    # trip at all.
    if _step_up_is_locked_out(owner_id):
        return jsonify({"error": "step_up_locked_out"}), 429

    verified = _verify_current_password(email, password)
    if verified is None:
        # The provider could not be reached. An outage is not a wrong password,
        # so it costs the reader nothing: no failure is recorded, and the answer
        # is 503 rather than 401.
        return jsonify({"error": "deletion_unavailable"}), 503
    if not verified:
        now_locked = _record_step_up_failure(owner_id)
        if now_locked:
            return jsonify({"error": "step_up_locked_out"}), 429
        return jsonify({"error": "step_up_failed"}), 401

    # Correct password: the counter goes, so a reader who mistyped twice before
    # getting it right is not carrying a penalty into their next attempt.
    _clear_step_up_failures(owner_id)

    try:
        result = _saga_rpc("account_deletion_request", {"p_owner_id": owner_id})
    except Exception as exc:
        code = _saga_error_code(exc)
        if code == "DL003":
            logger.warning("Deletion refused for administrator %s.", owner_id)
            return jsonify({"error": "deletion_unavailable_for_admin"}), 403
        if code == "DL004":
            logger.warning("Deletion requested for an already-deleted account %s.", owner_id)
            return jsonify({"error": "already_deleted"}), 410
        logger.warning("Deletion request failed for %s (%s).", owner_id, code, exc_info=True)
        return jsonify({"error": "deletion_unavailable"}), 503
    if result is None:
        return jsonify({"error": "deletion_unavailable"}), 503

    row = getattr(result, "data", None)
    row_state = row.get("state") if isinstance(row, dict) else None
    is_replay = isinstance(row, dict) and row.get("_replay") is True

    if is_replay and row_state is not None and row_state != "pending":
        # A replay of an already-in-progress (frozen) saga: the saga row
        # already exists and the sessions were already ended when it was
        # first requested. Re-running the global sign-out here would sign
        # the reader out everywhere and — via the UI's requested toast —
        # tell them their account "stays usable for 30 days" when writes
        # are frozen, grace has passed and cancel is refused. Return the
        # row as-is; the status endpoint (and its in-progress view) is the
        # honest answer for this state.
        body = {"ok": True, "replay": True, "state": row_state}
        grace_until = row.get("grace_until") if isinstance(row, dict) else None
        if grace_until:
            body["grace_until"] = grace_until
        return jsonify(body)

    # The account is pending now; its sessions end here. Global scope, by the
    # REQUESTING session's JWT — never revoke_sessions (password rotation
    # would lock the owner out of the cancel path) and never a GoTrue ban
    # (same outcome). A sign-out failure does not roll the saga back: the
    # deletion is recorded, and the local session is cleared regardless.
    jwt = _bearer_token() or session.get("supabase_access_token")
    if jwt:
        try:
            dispatcher = current_app.config["auth_admin_dispatcher"]()
            if dispatcher is None:
                logger.warning("Deletion sign-out skipped for %s: no dispatcher.", owner_id)
            else:
                dispatcher.sign_out_all(jwt)
        except Exception:
            logger.warning("Deletion sign-out failed for %s.", owner_id, exc_info=True)
        try:
            current_app.config["token_verification"].invalidate_token(jwt)
        except Exception:
            logger.warning("Token cache eviction failed after deletion request.", exc_info=True)
    session.clear()

    grace_until = row.get("grace_until") if isinstance(row, dict) else None
    body = {"ok": True}
    if grace_until:
        body["grace_until"] = grace_until
    return jsonify(body)


@account_bp.route("/api/deletion/cancel", methods=["POST"], endpoint="deletion_cancel")
def deletion_cancel() -> Response | tuple[Response, int]:
    """Cancel the caller's OWN pending deletion.

    ``POST .../cancel``, not ``DELETE`` on the collection: ``DELETE
    /account/api/deletion`` reads as "delete my account now", which is the
    opposite of what this does, while ``cancel`` names the saga RPC it calls
    (``account_deletion_cancel``) exactly.

    Reachable by a pending reader with NO gate change: ``_gate`` refuses only
    ``is_disabled``, and the saga never sets that column, so a pending reader
    authenticates normally and arrives here untouched. No step-up: cancelling
    restores nothing and destroys nothing; the authenticated session is the
    authorization. Rate-limited per reader on the same tight limit as the
    request.

    While the self-serve deploy switch is OFF this route answers 404 (see
    ``deletion_request``).
    """
    if not _deletion_self_serve_enabled():
        return jsonify({"error": "deletion_unavailable"}), 404

    identity = getattr(g, "identity", None)
    owner_id = getattr(identity, "user_id", None) if identity is not None else None
    if not owner_id:
        return jsonify({"error": "identity_unavailable"}), 503

    try:
        result = _saga_rpc("account_deletion_cancel", {"p_owner_id": owner_id})
    except Exception as exc:
        code = _saga_error_code(exc)
        if code == "DL005":
            logger.warning("Deletion cancel refused for %s: past the purge.", owner_id)
            return jsonify({"error": "cancel_unavailable"}), 409
        logger.warning("Deletion cancel failed for %s (%s).", owner_id, code, exc_info=True)
        return jsonify({"error": "deletion_unavailable"}), 503
    if result is None:
        return jsonify({"error": "deletion_unavailable"}), 503

    return jsonify(ok=True)


@account_bp.route("/api/deletion", methods=["GET"], endpoint="deletion_status")
def deletion_status() -> Response | tuple[Response, int]:
    """The CALLER'S OWN deletion state, and nothing else's.

    There is no status RPC in the saga contract (``supabase/pending/10``
    holds only mutating steps), so this reads the ledger row directly
    through the service-role client — filtered by equality on the owner id
    from ``g.identity``. No request-supplied id is read at all, so it is
    impossible to reach another account's row through this route. Absence of
    a row is an answer (``pending: false``), not a 404.

    The ``state`` is returned alongside the ``pending`` boolean: for the
    frozen states (``purging``/``auth_delete_begun``/``failed``) ``pending``
    is false but the account page must render the deletion-in-progress view
    — no request form, no cancel button, no 30-day claim — rather than the
    request form again.

    While the self-serve deploy switch is OFF this route answers 404 (see
    ``deletion_request``).
    """
    if not _deletion_self_serve_enabled():
        return jsonify({"error": "deletion_unavailable"}), 404

    identity = getattr(g, "identity", None)
    owner_id = getattr(identity, "user_id", None) if identity is not None else None
    if not owner_id:
        return jsonify({"error": "identity_unavailable"}), 503

    client = get_supabase_admin()
    if client is None:
        return jsonify({"error": "deletion_unavailable"}), 503

    try:
        response = (
            client.table("account_deletions")
            .select("state,requested_at,grace_until,purge_after,completed_at")
            .eq("user_id", owner_id)
            .execute()
        )
    except Exception:
        logger.warning("Deletion status read failed for %s.", owner_id, exc_info=True)
        return jsonify({"error": "deletion_unavailable"}), 503

    rows = getattr(response, "data", None) or []
    if not rows:
        return jsonify({"pending": False, "state": "none"})
    row = rows[0]
    return jsonify(
        {
            "pending": row.get("state") == "pending",
            "state": row.get("state"),
            "requested_at": row.get("requested_at"),
            "grace_until": row.get("grace_until"),
            "purge_after": row.get("purge_after"),
            "completed_at": row.get("completed_at"),
        }
    )
