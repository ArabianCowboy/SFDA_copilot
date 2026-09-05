import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request, session
from supabase_auth.errors import AuthError

from web.services.account_recovery import (
    RecoveryRefused,
    recovery_redirect_url,
    signup_redirect_url,
)
from web.utils.supabase_client import get_supabase

auth_bp = Blueprint("auth", __name__)

# Both of these are their own blueprint purely so each can carry its own rate
# limit.
#
# Flask-Limiter registers a per-route limit through the decorator at definition
# time, and this blueprint's routes are defined at import — before the limiter
# for a given app exists. Applying the decorator afterwards to the resolved view
# function registers the limit nowhere and the endpoint answers unlimited, which
# is what happened here and is invisible until something exercises it. A
# blueprint-scoped limit is the mechanism the console already uses successfully,
# and it is applied in `_register_routes`.
#
# Scoped to one route each rather than all of `auth_bp` because a 5/minute
# ceiling on logout would be wrong.
recover_bp = Blueprint("recover", __name__)
# `/signup` used to live on `auth_bp` and inherit no limit at all — the same
# unlimited-decorator trap described above, just never noticed because nothing
# gated the route yet. Split out once a gate made the route worth protecting:
# signup sends mail, the same reasoning `recover_bp` already carries.
signup_bp = Blueprint("signup", __name__)
logger = logging.getLogger(__name__)

# The only fields `signup()` will ever forward into `raw_user_meta_data`, and
# copied BY PRESENCE, not truthiness — `False` and `0` must survive. Anything
# else in the request body is dropped rather than forwarded: this composes the
# object the client used to be trusted to send itself (see
# `static/js/modules/services.js`'s `signup` docstring), so an allow-list here
# is what makes "the server is prepared for this" true again.
SIGNUP_METADATA_KEYS = (
    "first_name",
    "family_name",
    "marketing_consent",
    "marketing_consent_policy_version",
    "marketing_consent_language",
    "age",
)


# Session keys holding one reader's legacy conversation litter. Named once so
# the purge below cannot drift from whatever else reads this list.
#
# NEITHER KEY IS WRITTEN BY EITHER CHAT ROUTE ANY MORE
# (docs/per-tab-conversation-deep-linking-plan.md §5.1, §5.4): the URL is the
# pointer now, not a cookie, and `ConversationStore` is keyed
# `(owner_id, conversation_id)` — a second reader on the same browser cannot
# reach the first reader's RAM window merely by signing in, because nothing
# hands them the first reader's conversation id to ask for. What these two
# keys still guard against is narrower and purely historical: a pre-migration
# cookie that predates `ConversationStore` entirely and is still carrying raw
# question/answer JSON. Purged here so a reader who signs out (or hands the
# browser to someone else) does not leave that old content sitting in the
# next reader's session.
CONVERSATION_SESSION_KEYS = (
    "chat_history",
    "prev_chat_history",
)

# Markers that describe *who* is holding this cookie rather than what they said.
#
# `is_admin_hint` is a render hint and nothing else — it decides whether the
# Admin link is drawn on a page the server renders without validating a token.
# Authorization is always a fresh server-side lookup; see `_authenticate_request`.
#
# It still rotates with the conversation, and for the same reason: an elevated
# marker that outlived its reader is exactly the leak `_bind_session_to_identity`
# exists to close. A hint is cheap to rebuild and expensive to leave lying around
# on a shared machine.
IDENTITY_MARKER_KEYS = ("is_admin_hint",)


def purge_conversation_state():
    """Drop this browser session's legacy conversation litter.

    The Flask session cookie outlives a Supabase sign-out — nothing in the
    logout path used to touch it — so a pre-migration `chat_history` used to
    survive into the next sign-in **in the same browser** and ride straight
    into the next reader's prompt. On a regulatory assistant that is one
    person's queries becoming part of another person's prompt.

    Nothing here clears a `ConversationStore` entry any more: the store is
    keyed `(owner_id, conversation_id)`, and this browser's next request
    carries the NEW reader's own owner id — it cannot land in the previous
    reader's bucket by construction, so there is no id here worth looking up
    to clear.
    """
    for key in CONVERSATION_SESSION_KEYS:
        session.pop(key, None)


def rotate_session_for_new_identity() -> None:
    """Reset everything tied to the previous reader of this cookie.

    One call rather than two, so a marker added later cannot be wired into one
    purge and forgotten in the other — which is how `is_admin_hint` would
    otherwise have survived a change of reader on a shared machine.
    """
    purge_conversation_state()
    for key in IDENTITY_MARKER_KEYS:
        session.pop(key, None)


def _signup_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """The allow-listed subset of the request body, unconverted.

    By presence, not truthiness: ``"marketing_consent": False`` must survive,
    which a plain ``data.get(key)`` filtered through ``if value`` would drop.
    Values are forwarded exactly as received — never stringified — because
    `handle_new_user` (`20260823014034_marketing_consent_record.sql:300`)
    tests `jsonb_typeof(... ) = 'boolean'` on `marketing_consent`, and a
    string there silently becomes a declined consent for every new account.
    """
    return {key: data[key] for key in SIGNUP_METADATA_KEYS if key in data}


@signup_bp.route("/signup", methods=["POST"])
def signup() -> Any:
    """Create an account — the one route the browser's signup form calls.

    Gated before anything else touches the provider: an operator-paused
    instance must never construct a Supabase client for this request, let
    alone spend a network call on it. See
    ``docs/registrations-pause-plan.md`` for the full contract, including why
    the gate reads three-valued (``True``/``False``/``None``) and answers a
    ``503`` rather than a ``403`` when it cannot tell which.

    Answers in machine codes, not sentences — this endpoint composes no
    English. ``static/js/modules/dom.js``'s ``formatAuthError`` owns every
    reader-facing string in both languages; a message composed here would be
    a second, untranslated path this app does not have.
    """
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")
    lang = data.get("lang")

    # Malformed before paused: a blank password is wrong whether or not
    # signups are open, it should not spend a settings read, and "paused" is
    # not an answer the reader could act on for a request this broken.
    #
    # `lang` is validated here too, not left to `signup_redirect_url` — a
    # non-string value (an int, a list) reached `quote()` unguarded and
    # raised, which the broad `except Exception` below turned into a
    # `503 provider_unavailable`: a malformed CLIENT request reported as an
    # upstream outage. `recover()` validates the same way for the same
    # reason.
    if not email or not password or not isinstance(lang, (str, type(None))):
        return jsonify({"error": "missing_fields"}), 400

    settings_service = current_app.config["settings_service"]
    enabled = settings_service.signup_enabled()
    if enabled is None:
        return jsonify({"error": "auth_unavailable"}), 503
    if not enabled:
        return jsonify({"error": "signup_disabled"}), 403

    try:
        supabase = get_supabase()
        if not supabase:
            return jsonify({"error": "provider_unavailable"}), 503

        options: dict[str, Any] = {"data": _signup_metadata(data)}
        redirect_to = signup_redirect_url(lang)
        if redirect_to:
            options["email_redirect_to"] = redirect_to

        # Re-read immediately before the network call, not just once at the
        # top of the view. The first check and the actual GoTrue round trip
        # are separated by metadata/redirect-URL construction and the request
        # itself; on the single-worker/multi-thread deployment an operator's
        # pause can land in that window. This does not close the window
        # entirely — the read here and the send below are still two steps,
        # not one atomic one, and closing it fully would need the BEFORE
        # INSERT trigger `docs/registrations-pause-plan.md` §4 explicitly
        # rejects (it would also block admin-created accounts). It narrows
        # the window from "the whole view" to "one network round trip",
        # which is the practical amount of narrowing available without that
        # trade-off. Found in review (/code-review, 2026-08-26).
        if settings_service.signup_enabled() is False:
            return jsonify({"error": "signup_disabled"}), 403

        response = supabase.auth.sign_up({"email": email, "password": password, "options": options})

        # Provably unreachable against the installed `supabase_auth` 2.31.0:
        # its `sign_up()` either returns a populated `AuthResponse` or RAISES
        # (see the `except AuthError` branch below) — it never returns an
        # object with a populated `.error`. Kept anyway, defensively, in case
        # a future SDK version changes that contract back; a branch that
        # never runs today costs nothing to leave in place, and removing it
        # is the thing that would need re-adding under pressure later.
        if hasattr(response, "error") and response.error:
            message = getattr(response.error, "message", str(response.error)) or ""
            logger.warning("Signup refused by provider: %s", message)
            code, status = _signup_error_response(None, message)
            return jsonify({"error": code}), status

        user = None
        if hasattr(response, "user") and response.user:
            user = response.user
        elif hasattr(response, "data") and hasattr(response.data, "user"):
            user = response.data.user

        if not user:
            logger.error("Signup response structure unexpected: %r", response)
            return jsonify({"error": "provider_unavailable"}), 503

        return jsonify(
            {"message": "User created successfully", "user": {"id": user.id, "email": user.email}}
        ), 201

    except AuthError as exc:
        # THIS is the branch every real refusal actually takes — a duplicate
        # email, a weak password, GoTrue's own per-address cooldown. `exc.code`
        # is GoTrue's own machine code (`email_exists`, `weak_password`,
        # `over_email_send_rate_limit`, even `signup_disabled` if an operator
        # used the dashboard hard-close from docs/OPERATIONS.md) — read that
        # first, and fall back to the English-prose heuristic only when a
        # future GoTrue error has no code we recognise yet.
        logger.warning("Signup refused by provider: %s (code=%s)", exc.message, exc.code)
        code, status = _signup_error_response(exc.code, exc.message)
        return jsonify({"error": code}), status
    except Exception:
        # Nothing above raised an AuthError — the provider itself did not
        # answer (network failure, malformed client, an SDK exception with no
        # GoTrue semantics at all). This is the one branch that is honestly an
        # outage.
        logger.error("Signup exception", exc_info=True)
        return jsonify({"error": "provider_unavailable"}), 503


# GoTrue's own machine code (`AuthError.code`, from `supabase_auth.errors.ErrorCode`)
# mapped to ours, and to the status this app answers with — not always the
# status GoTrue itself used. `signup_disabled` is GoTrue's own: an operator
# who used the dashboard/Management-API hard close (docs/OPERATIONS.md) gets
# GoTrue refusing directly, and this maps that refusal onto the SAME code and
# status our own console-driven pause already answers with, so the reader
# sees one consistent "paused" rather than two different refusals depending
# on which layer closed signups.
_GOTRUE_CODE_MAP: dict[str, tuple[str, int]] = {
    "email_exists": ("already_registered", 400),
    "user_already_exists": ("already_registered", 400),
    "weak_password": ("weak_password", 400),
    "email_address_invalid": ("invalid_email", 400),
    "validation_failed": ("invalid_email", 400),
    "over_request_rate_limit": ("too_soon", 429),
    "over_email_send_rate_limit": ("email_unavailable", 429),
    "signup_disabled": ("signup_disabled", 403),
    "email_provider_disabled": ("signup_disabled", 403),
}


def _signup_error_response(gotrue_code: str | None, message: str) -> tuple[str, int]:
    """Our machine code and HTTP status for a refused signup.

    Reads GoTrue's OWN code first — an enum member, not prose, so it survives
    a wording change upstream — and falls back to English-substring matching
    on ``message`` only when ``gotrue_code`` is ``None`` or one this table
    does not recognise yet. See §7 of ``docs/registrations-pause-plan.md``
    for the table this mirrors.
    """
    if gotrue_code and gotrue_code in _GOTRUE_CODE_MAP:
        return _GOTRUE_CODE_MAP[gotrue_code]

    lowered = message.lower()
    if "already registered" in lowered or "already_registered" in lowered:
        return "already_registered", 400
    if "valid email" in lowered:
        return "invalid_email", 400
    if "password" in lowered:
        return "weak_password", 400
    if "for security purposes" in lowered or "only request this after" in lowered:
        return "too_soon", 429
    if "rate limit" in lowered or "over_email_send_rate_limit" in lowered:
        return "email_unavailable", 429
    # The provider answered — this is a refusal, not an outage — so it is
    # NOT `provider_unavailable`, which is reserved for the exception path
    # above where nothing answered at all.
    return "signup_refused", 400


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    try:
        supabase = get_supabase()
        if not supabase:
            return jsonify({"error": "Supabase client not available"}), 500

        response = supabase.auth.sign_in_with_password({"email": email, "password": password})

        # Handle response structure - check for error attribute first
        if hasattr(response, "error") and response.error:
            error_msg = getattr(response.error, "message", str(response.error))
            logger.warning(f"Login error: {error_msg}")
            return jsonify({"error": error_msg}), 401

        # Access user and session data from the response
        # Try different possible response structures
        user = None
        session_obj = None

        if hasattr(response, "user") and response.user:
            user = response.user
        elif hasattr(response, "data") and hasattr(response.data, "user"):
            user = response.data.user

        if hasattr(response, "session") and response.session:
            session_obj = response.session
        elif hasattr(response, "data") and hasattr(response.data, "session"):
            session_obj = response.data.session

        if not user:
            logger.error(
                f"Login response structure unexpected. Response attributes: {dir(response)}"
            )
            return jsonify({"error": "Unexpected response from authentication service"}), 500

        if not session_obj:
            logger.warning("Login successful but no session returned")
            return jsonify({"user": {"id": user.id, "email": user.email}, "session": None}), 200

        return jsonify(
            {
                "user": {"id": user.id, "email": user.email},
                "session": {
                    "access_token": session_obj.access_token,
                    "refresh_token": session_obj.refresh_token,
                },
            }
        )

    except Exception as e:
        logger.error(f"Login exception: {e!s}", exc_info=True)
        error_msg = str(e)
        # Extract more meaningful error messages from common exceptions
        if "Invalid login credentials" in error_msg or "invalid_credentials" in error_msg.lower():
            error_msg = "Invalid email or password"
        elif "Email not confirmed" in error_msg or "email_not_confirmed" in error_msg.lower():
            error_msg = "Please confirm your email address before logging in"
        return jsonify({"error": error_msg}), 401


@recover_bp.route("/recover", methods=["POST"])
def recover():
    """Send a password-recovery link. Unauthenticated, by necessity.

    This is the reader's *forgot password*. It is a POST to our own origin rather
    than a browser call to Supabase, and that is not stylistic: a link requested
    from the browser carries a PKCE `code_challenge` whose verifier lives in that
    browser's localStorage, so opening the mail on a phone cannot complete it.
    Originating the mail here produces an implicit link that any device can use.
    See `web/services/account_recovery.py` for the measurement behind that.

    **The response never says whether the address exists.** Same body, same
    status, whether the account is real, absent, or the provider refused for a
    reason the reader cannot act on. An endpoint that answers "no such account"
    is an account-enumeration oracle, and on a professional tool the membership
    list is itself worth something. The one thing that *is* reported honestly is
    a rate limit, because that one tells the reader to wait rather than to give
    up — and it reveals nothing, since it is reachable with any address at all.

    Deliberately not audited. `audit_log` records privileged acts by operators;
    writing a row every time a reader recovers their own account would quietly
    turn it into a reader-activity trail, which is exactly what TODO.md's
    identity-free question log exists to avoid.
    """
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    lang = data.get("lang")

    if not isinstance(email, str) or not email.strip():
        return jsonify({"error": "invalid_payload"}), 400
    if not isinstance(lang, (str, type(None))):
        return jsonify({"error": "invalid_payload"}), 400

    try:
        # Resolved inside the try, not above it. `get_recovery_dispatcher()`
        # constructs a Supabase client, and a malformed SUPABASE_URL makes that
        # raise — which outside this block became a 500 carrying whatever the
        # error handler chose to say. A misconfigured deployment must be
        # indistinguishable from an unknown address, or it is an oracle.
        dispatcher = current_app.config.get("recovery_dispatcher")
        dispatcher = dispatcher() if callable(dispatcher) else dispatcher

        if dispatcher is None:
            raise RecoveryRefused("reset_not_configured", "no dispatcher available")
        dispatcher.send_recovery(email.strip(), recovery_redirect_url(lang or None))
    except RecoveryRefused as refusal:
        # Rate limits are the reader's own doing and are worth saying out loud.
        # Everything else collapses into the generic success below: a
        # misconfigured project must not be distinguishable from an unknown
        # address by anyone probing this endpoint.
        if refusal.code in ("reset_rate_limited", "reset_quota_exhausted"):
            return jsonify({"error": refusal.code}), 429
        logging.getLogger(__name__).error("recovery unavailable (%s)", refusal.code)
        return jsonify({"sent": True}), 202
    except Exception:
        logging.getLogger(__name__).exception("recovery send failed")
        return jsonify({"sent": True}), 202

    return jsonify({"sent": True}), 202


@auth_bp.route("/logout", methods=["POST"])
def logout():
    # Read before the clear below: `_get_token_from_request` falls back to
    # `session["supabase_access_token"]`, so clearing the session first would
    # lose the only handle on the cache entry that needs dropping. Imported
    # inline — `web.api.app` imports this module's blueprint at load time, so
    # a top-level import here would be a cycle.
    from web.api.app import _get_token_from_request

    token = _get_token_from_request()

    # Before anything that can fail. Whether Supabase is reachable, whether the
    # token was already expired, whether sign_out raises — none of it may leave
    # this browser session still holding the previous reader's conversation.
    purge_conversation_state()
    session.clear()

    # Local and unconditional, deliberately before the GoTrue call below and
    # outside its try: whether the provider is reachable has no bearing on
    # whether this process should keep trusting this token.
    if token:
        current_app.config["token_verification"].invalidate_token(token)

    if current_app.config.get("TESTING"):
        return jsonify({"message": "Logged out successfully"})

    if not token:
        # Nothing to revoke upstream. The Flask-side teardown above is the whole
        # of what an anonymous caller is entitled to, and it has already run.
        return jsonify({"message": "Logged out (session cleared)"})

    try:
        supabase = get_supabase()
        if not supabase:
            # The server-side state is already gone, which is the part that
            # matters; the client drops its own token regardless.
            logger.warning("Logout: Supabase unavailable, session cleared anyway.")
            return jsonify({"message": "Logged out (session cleared)"})

        # THE CALLER'S OWN TOKEN, explicitly. This used to be a no-arg
        # `supabase.auth.sign_out()`, which reads the session stored on the
        # process-global client and revokes THAT reader everywhere — so once any
        # request had authenticated through the singleton, the next stranger's
        # logout signed out somebody else. The route already held the right
        # token (read above, for the cache eviction); it simply never passed it.
        #
        # `admin.sign_out` here is GoTrue's plain `/logout` with a bearer token,
        # not a service-role operation: the anon client is the correct caller
        # and the JWT is its own authorization. `global` is stated rather than
        # left to the default, matching the browser-direct revoke in
        # `services.js` — a logout that leaves other devices signed in is not
        # the property this endpoint is for.
        #
        # Typed loosely: sign_out() returns None on the currently installed
        # GoTrue client, but this guards defensively against a version that
        # returns an error-carrying response object instead.
        response: Any = supabase.auth.admin.sign_out(token, "global")  # type: ignore[func-returns-value]

        # Check for error in response
        if hasattr(response, "error") and response.error:
            error_msg = getattr(response.error, "message", str(response.error))
            logger.warning(f"Logout error: {error_msg}")
            return jsonify({"error": error_msg}), 400

        return jsonify({"message": "Logged out successfully"})
    except Exception as e:
        logger.error(f"Logout exception: {e!s}", exc_info=True)
        return jsonify({"error": str(e)}), 400
