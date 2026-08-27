"""The operator console: a data-free shell, and an API that only bearers reach.

Two decisions here are load-bearing and neither is obvious.

**The page is not gated; the data is.** Supabase's session lives in the
browser's ``localStorage``, so a document navigation to ``/admin`` cannot carry
an ``Authorization`` header. Flask only learns the token after some *other*
authenticated request has already been through ``auth_required``. Gating the
page on a role would therefore turn away a valid administrator who bookmarked
the URL, refreshed, or simply signed in and came straight here — and
``is_admin_hint`` cannot rescue that, because on a first sign-in in a fresh
browser there is no hint yet. So ``GET /admin`` renders chrome, empty regions
and translated strings, and nothing privileged renders until the JS has asked
``/admin/api/identity`` with a token in hand.

**The API accepts a bearer header and nothing else.** ``_get_token_from_request``
also honours a cookie and the Flask session, which is right for the chat routes
and wrong here: a cookie-authenticated privileged mutation is CSRF-shaped, and
this app has no CSRF protection to answer it with. Requiring a header the
browser will not attach on its own removes the question instead of answering it.

The gate is a ``before_request`` rather than a per-route decorator so it covers
routes added later. A decorator can be forgotten on route nine, and the failure
is silent.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
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
)
from flask_limiter.util import get_remote_address

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# Endpoints that deliberately serve without a role. Default-deny: anything not
# named here is gated, so a new route is protected by omission rather than by
# somebody remembering to protect it.
#
# The console shell is the only member and must stay the only member. It renders
# no account data, no settings, and no counts — see the module docstring.
_UNGATED_ENDPOINTS = frozenset({"admin.console"})


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


def _admin_notification_rate_key() -> str:
    """Per-administrator, not per-IP, and not `g.identity.user_id` either.

    Flask-Limiter's own extension-level ``before_request`` runs BEFORE this
    blueprint's own (``_gate`` below) — the same ordering
    ``web/api/app.py``'s ``_account_rate_key`` documents and works around —
    so `g.identity` is not populated yet when a decorator-applied rate-limit
    key function evaluates. Hashing the bearer token itself gets the same
    per-administrator isolation `notification_broadcast_api` needs (a
    compromised admin account spamming via multiple IPs, or several admins
    behind one office NAT sharing one budget) without a second
    `supabase.auth.get_user` round trip just to compute a rate key.
    """
    from web.utils.hashing import sha256_hex

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return get_remote_address()
    token = header[len("Bearer ") :].strip()
    if not token:
        return get_remote_address()
    return sha256_hex(token)


@admin_bp.before_request
def _gate() -> Response | tuple[Response, int] | None:
    """Admit administrators presenting a bearer token; turn away everyone else."""
    if request.endpoint in _UNGATED_ENDPOINTS:
        return None

    if _bearer_token() is None:
        return jsonify({"error": "bearer_required"}), 401

    # Imported here rather than at module scope: app.py imports this blueprint
    # to register it, so a top-level import back into app.py would be a cycle.
    from web.api.app import _authenticate_request

    identity, early_response = _authenticate_request()
    if early_response is not None:
        return early_response
    assert identity is not None  # _authenticate_request's contract: exactly one is None

    # An outage is not a refusal, and saying "forbidden" when the truth is "we
    # could not check" tells an administrator they have lost access they still
    # have. Ordered before the role test because an unresolved identity always
    # reports role='user', so checking is_admin first would misclassify every
    # lookup failure as a denial.
    if not identity.is_resolved:
        logger.error(
            "Could not resolve identity for %s; refusing console access.", identity.user_id
        )
        return jsonify({"error": "identity_unavailable"}), 503

    if not identity.is_admin:
        logger.warning("Non-administrator %s attempted %s", identity.user_id, request.path)
        return jsonify({"error": "forbidden"}), 403

    return None


@admin_bp.route("/", strict_slashes=False)
def console() -> Response | tuple[Response, int]:
    """The console shell. Renders no privileged data — see the module docstring."""
    from web.api.app import ADMIN_MODULE_FILENAMES, MODULE_FILENAMES

    build_map = cast(
        "Callable[[str, Sequence[str]], dict[str, Any]]",
        current_app.jinja_env.globals["_import_map"],
    )

    # Both directories, because the console's modules import the shared ones —
    # i18n, theme, the icon helper, the Supabase transport. An unmapped import
    # resolves to a bare URL that no cache-buster reaches, which is the exact
    # staleness the map exists to prevent.
    #
    # This does not undo the reason the two directories are separate: what must
    # not carry an inventory of the console is the *anonymous landing page*, and
    # `index()` still maps only `modules/`. Naming the reader's modules here, on
    # a page an administrator is already looking at, costs nothing.
    import_map = build_map("modules", MODULE_FILENAMES)
    import_map["imports"].update(build_map("admin", ADMIN_MODULE_FILENAMES)["imports"])

    context = current_app.config["base_render_context"](admin=True)
    return make_response(render_template("admin.html", **context, module_import_map=import_map))


def _active_generation() -> dict[str, Any]:
    """What the handler that answers questions is ACTUALLY using, right now.

    Read off the live object, not off the store. Everything else in this
    response describes what is *configured*, and the two can disagree: the
    settings a request generates with are fixed when its handler is
    constructed, and a boot that could not reach the settings store builds that
    handler from the deployed defaults and never revisits the decision. Nothing
    reconciles them until the next save or restart.

    That gap is exactly the state this console was unable to describe — it
    reported Luna from the store while the process was generating with
    gpt-4o-mini, and the only place the disagreement was visible was a line in
    the server's terminal. An operator should not have to read the logs to find
    out whether the model they chose is the model answering.

    Per-process, and honestly so: it describes the worker that served this
    request. That is a real limit under WEB_CONCURRENCY > 1, which this app
    already warns against for the same reason.
    """
    handler = current_app.config.get("openai_handler")
    if handler is None:
        return {}
    return {
        "model": getattr(handler, "model", None),
        "max_tokens": getattr(handler, "max_tokens", None),
        "temperature": getattr(handler, "temperature", None),
        "max_context_results": getattr(handler, "max_context_results", None),
        "reasoning_effort": getattr(handler, "reasoning_effort", None),
    }


@admin_bp.route("/api/settings", methods=["GET"])
def get_settings() -> Response | tuple[Response, int]:
    """The effective settings, plus what an operator is allowed to choose.

    `overrides` is sent alongside `settings` so the console can distinguish a
    value someone chose from a value that merely happens to be the deployed
    default — the two look identical and revert differently.
    """
    from web.services.settings_service import allowed_models, deployed_defaults

    service = current_app.config["settings_service"]
    return jsonify(
        {
            "settings": service.snapshot(),
            "overrides": service.overrides(),
            # What each value reverts TO. An overridden field hides its own default
            # — the effective value *is* the override — so without this the console
            # cannot offer "revert" without guessing, and a guess that happens to
            # equal the default would pin it instead of restoring inheritance.
            "defaults": deployed_defaults(),
            "allowed_models": allowed_models(),
            # Configured is not the same fact as live; see _active_generation.
            "active": _active_generation(),
        }
    )


@admin_bp.route("/api/settings", methods=["PUT"])
def put_settings() -> Response | tuple[Response, int]:
    """Apply a patch. 422 with per-field codes, or 200 with the new state.

    A key set to null is removed, reverting to the deployed default. That is
    distinct from setting it to the default's current value, which would pin it
    against a future deploy — a difference worth having a gesture for.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_payload"}), 400

    from web.services.audit import actor_from_request

    service = current_app.config["settings_service"]
    apply_settings = current_app.config["apply_generation_settings"]

    # Applied inside the service's write lock, so store, publish, build and swap
    # are one serialized operation. Two overlapping saves would otherwise each
    # store then build then swap, and whichever build finished last would win —
    # leaving generation on the older settings while the store and both
    # responses reported the newer.
    outcome = {"applied": False}

    def apply_now() -> None:
        outcome["applied"] = apply_settings()

    errors = service.update(payload, actor=actor_from_request(g.identity), on_committed=apply_now)

    if errors:
        return jsonify(
            {
                "error": "validation_failed",
                "errors": [error.as_dict() for error in errors],
            }
        ), 422

    logger.info("Settings updated by %s: %s", g.identity.email, sorted(payload))

    # Reported rather than raised: the settings are already stored, so a handler
    # that would not build is a reason to tell the operator their change is not
    # live yet — not a reason to fail a write that succeeded, and certainly not
    # a reason to take the chatbot down.
    applied = outcome["applied"]
    if not applied:
        logger.error("Settings were stored but could not be applied to generation.")

    from web.services.settings_service import deployed_defaults

    return jsonify(
        {
            "settings": service.snapshot(),
            "overrides": service.overrides(),
            "defaults": deployed_defaults(),
            "applied": applied,
            # Read AFTER the swap, so `applied: false` is not the only way to learn
            # that answers are still coming from the previous settings — this says
            # which ones they are.
            "active": _active_generation(),
        }
    )


@admin_bp.route("/api/registrations", methods=["GET"])
def get_registrations() -> Response | tuple[Response, int]:
    """Whether the signup form accepts new accounts, and what it reverts to.

    A separate endpoint from `/api/settings` rather than a field folded into
    it — see `docs/registrations-pause-plan.md` §2 for why: this value is not
    a generation setting, has no pairwise validation against a model, and
    must never trigger `apply_generation_settings`. Keeping it off that
    endpoint keeps `put_settings`'s tested response contract, and its
    `applied`/`active` semantics, unchanged.
    """
    from web.services.settings_service import deployed_non_generation_defaults

    service = current_app.config["settings_service"]
    enabled = service.signup_enabled()
    if enabled is None:
        return jsonify({"error": "storage_unavailable"}), 503
    return jsonify(
        {
            "signup_enabled": enabled,
            "default": bool(deployed_non_generation_defaults()["signup_enabled"]),
        }
    )


@admin_bp.route("/api/registrations", methods=["PUT"])
def put_registrations() -> Response | tuple[Response, int]:
    """Pause or resume the signup form. Audited the same way a generation
    settings change is: `admin_write_settings` writes the store and the
    audit row in one transaction, action `settings.update` — there is only
    the one RPC, and its action string is hardcoded, so this reuses it
    rather than adding a migration for a marginally more specific name.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or "signup_enabled" not in payload:
        return jsonify({"error": "invalid_payload"}), 400

    from web.services.audit import actor_from_request

    service = current_app.config["settings_service"]
    errors = service.set_signup_enabled(
        payload["signup_enabled"], actor=actor_from_request(g.identity)
    )
    if errors:
        # `errors[0].code` is always `not_a_boolean` or `storage_unavailable`
        # here — `set_signup_enabled` only ever validates the one
        # `signup_enabled` field this route sends, so `unknown_setting`
        # (which `put_settings`'s equivalent branch does have to handle,
        # since it accepts an arbitrary patch) can never appear. Simplified
        # 2026-08-26 after review found the filter for it was dead code.
        if errors[0].code == "storage_unavailable":
            return jsonify({"error": "storage_unavailable"}), 503
        return jsonify({"error": "invalid_signup_enabled"}), 422

    logger.info("Registrations pause updated by %s: %s", g.identity.email, payload)

    from web.services.settings_service import deployed_non_generation_defaults

    return jsonify(
        {
            "signup_enabled": service.signup_enabled(),
            "default": bool(deployed_non_generation_defaults()["signup_enabled"]),
        }
    )


def _parse_pagination_params(req: Any = None) -> tuple[int, int]:
    """Parse and clamp pagination query parameters from the request.

    Clamps limit to [1, 200] (default 50) and offset to [0, 1_000_000] (default 0).
    The 1,000,000 offset cap prevents Postgres int4 32-bit integer overflow
    (SQLSTATE 22003) on adversarial deep offsets. Raises TypeError or ValueError
    if either parameter cannot be parsed as an integer.
    """
    if req is None:
        req = request
    limit = min(max(int(req.args.get("limit", 50)), 1), 200)
    offset = min(max(int(req.args.get("offset", 0)), 0), 1_000_000)
    return limit, offset


@admin_bp.route("/api/users")
def users() -> Response | tuple[Response, int]:
    """Accounts, newest first, with their standing."""
    try:
        limit, offset = _parse_pagination_params(request)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_pagination"}), 400

    backend = current_app.config["admin_backend"]()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    rows, total = backend.list_users(
        limit=limit, offset=offset, search=request.args.get("q") or None
    )
    return jsonify(
        {
            "users": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
            # So the console can mark "you" in the list and grey out the controls it
            # knows the server will refuse. The refusal is still enforced server-side;
            # this only stops the operator discovering it by being told no.
            "self_id": g.identity.user_id,
        }
    )


@admin_bp.route("/api/users/<user_id>")
def user_detail(user_id: str) -> Response | tuple[Response, int]:
    """One account in full: identity, standing, profile.

    A **404** for an unknown account, unlike `PATCH`, which answers 409
    `no_such_account`. The difference is deliberate rather than an
    inconsistency: a refusal is something the server declined to do, and there
    is nothing to decline about reading a resource that is not there. The
    non-uuid case resolves to the same 404, because an id that cannot name an
    account names no account.
    """
    backend = current_app.config["admin_backend"]()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    account = backend.get_user(user_id)
    if account is None:
        return jsonify({"error": "no_such_account"}), 404

    return jsonify({"user": account, "self_id": g.identity.user_id})


# The profile fields an operator may rewrite, and nothing else. An exact key
# set rather than a filter: an unknown key is a mistake worth reporting, not
# something to quietly drop, and this is the route that pins the design position
# that the console can never send a password.
#
# full_name is no longer one of them: the identity cutover
# (supabase/migrations/20260822225415_profile_identity_atomic_cutover.sql)
# made it a stored generated column, so it can never appear in a write
# payload — only first_name and family_name are writable now.
_PROFILE_STRING_FIELDS = ("first_name", "family_name", "organization", "specialization")

# Bounded because every value is duplicated into `before` AND `after` of an
# append-only row that nothing can ever delete. Unbounded free text here is a
# way to grow a table that has no eviction story. Mirrors the DB CHECKs
# (profiles_first_name_chk/family_name_chk = 100, the two column-bound
# checks in profile_column_bounds.sql = 200) so a too-long value is reported
# by this route rather than surfacing as a raw constraint-violation error.
_PROFILE_STRING_MAX_LENGTH = {
    "first_name": 100,
    "family_name": 100,
    "organization": 200,
    "specialization": 200,
}

# Matches profiles_age_chk (age is null or age between 13 and 120).
_PROFILE_AGE_MIN, _PROFILE_AGE_MAX = 13, 120


@admin_bp.route("/api/users/<user_id>/reset-password", methods=["POST"])
def send_password_reset(user_id: str) -> Response | tuple[Response, int]:
    """Send this account a recovery link. Never return one.

    The console's whole thesis is that an operator helps without ever learning a
    credential, so this deliberately does not use ``auth.admin.generateLink``:
    that call's return value *is* a bearer credential — whoever holds the URL can
    set the password — and it would then exist in this process, in tracebacks,
    and one careless ``jsonify`` from an operator's screen. The same dispatcher
    the reader's own forgot-password uses sends the mail and returns nothing.

    **Two audit rows, correlated.** A database mutation and its audit row share a
    transaction; an outbound HTTP call cannot. So the intent is recorded first
    and the outcome after, which is what makes the failure this shape exists for
    — the process dying between the send and the record — visible as a dangling
    `requested` rather than as silence. `operation_id` pairs them, carried in
    `after` so no schema change is needed.

    The outcome is named `accepted`, not `sent`: the dispatcher establishes that
    GoTrue accepted the request, not that anything was delivered. Delivery lives
    in the provider's log, and claiming more than was observed on the one surface
    whose entire purpose is to be trustworthy later would be the wrong trade.
    """
    import uuid as _uuid

    from web.services.account_recovery import RecoveryRefused, recovery_redirect_url
    from web.services.audit import actor_from_request

    # This action takes no input at all: the account is in the path, and the
    # link is built server-side. Ignoring a body would be enough to make it
    # behave correctly, and is not enough to make the design position true — a
    # caller that sends `{"password": …}` here must be told no, not quietly
    # succeed. See test_no_console_route_accepts_a_password, which found exactly
    # this by sending one to every mutation route.
    payload = request.get_json(silent=True)
    if payload not in (None, {}):
        return jsonify(
            {
                "error": "unknown_field",
                "fields": sorted(payload) if isinstance(payload, dict) else [],
            }
        ), 422

    backend = current_app.config["admin_backend"]()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    account = backend.get_user(user_id)
    if account is None:
        return jsonify({"error": "no_such_account"}), 404
    if not account.get("email"):
        return jsonify({"error": "reset_no_email"}), 409

    actor = actor_from_request(g.identity)
    operation_id = str(_uuid.uuid4())
    backend.append_audit(
        action="user.password_reset_requested",
        target_type="user",
        target_id=user_id,
        actor=actor,
        after={"status": "requested", "operation_id": operation_id},
    )

    dispatcher = current_app.config.get("recovery_dispatcher")
    dispatcher = dispatcher() if callable(dispatcher) else dispatcher

    try:
        if dispatcher is None:
            raise RecoveryRefused("reset_not_configured", "no dispatcher available")
        dispatcher.send_recovery(account["email"], recovery_redirect_url())
    except RecoveryRefused as refusal:
        backend.append_audit(
            action="user.password_reset_failed",
            target_type="user",
            target_id=user_id,
            actor=actor,
            after={"status": "failed", "operation_id": operation_id},
            # The code, never the provider's message body and never a link.
            note=refusal.code,
        )
        status = 429 if refusal.code in ("reset_rate_limited", "reset_quota_exhausted") else 502
        return jsonify({"error": refusal.code}), status

    backend.append_audit(
        action="user.password_reset_accepted",
        target_type="user",
        target_id=user_id,
        actor=actor,
        after={"status": "accepted", "operation_id": operation_id},
    )
    # 200, not 202: nothing further happens on our side after this returns, and
    # 202 would imply queued work this application controls.
    return jsonify({"accepted": True, "operation_id": operation_id})


# A real email check, not "contains @": this is a login identifier, not free
# text, and a malformed one becomes a support ticket days later rather than an
# immediate, correctable 422.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_EMAIL_MAX_LENGTH = 254  # RFC 5321 4.5.3.1.3, not the profile-field 200 cap —
# this is a real email column, not free text.


def _actor_still_admin(backend) -> str | None:
    """None if the acting operator is still an enabled administrator right
    now; otherwise the refusal code.

    ``_gate()`` proves this at request start. Both new routes below call an
    external provider after that check, and re-check immediately before the
    call — mirroring what ``admin_update_profile``'s own RPC does inside its
    transaction — because an operator demoted mid-request should not be able
    to still complete an Auth Admin mutation on the strength of a role that
    no longer holds.
    """
    if not g.identity.user_id:
        return None
    acting = backend.get_user(g.identity.user_id)
    if acting is None or acting.get("role") != "admin" or acting.get("is_disabled"):
        return "actor_no_longer_administrator"
    return None


def _evict_token_cache(user_id: str) -> None:
    """Drop this reader's cached "GoTrue said this credential is good".

    Call after anything that ends or invalidates a session/credential
    without necessarily changing role, tier, disabled state, or email —
    revoking sessions is the case this exists for. A route that changes one
    of those other four wants `_evict_identity_caches` below instead, which
    covers this cache too.
    """
    current_app.config["token_verification"].invalidate_user(user_id)


def _evict_identity_caches(user_id: str) -> None:
    """Drop every cache this reader's identity feeds: the token-verification
    cache above, and the flags cache (role/tier/disabled — and the email
    `session["user_email"]` is actually drawn from; `_authenticate_request`
    reads it from `resolve_identity_flags`'s result, which returns a
    flags-cache HIT verbatim, ignoring whatever fresh email the token
    carried).

    Call after any admin action that changes role, disabled state, or
    email — anything the operator must not watch fail to take effect, or
    the reader must not keep seeing stale in their own session for up to
    the flags TTL. One chokepoint instead of two separate cache lookups
    repeated at every call site, so a future identity-mutating route
    cannot pass every test while silently forgetting one of the two caches.
    """
    _evict_token_cache(user_id)
    current_app.config["identity_flags"].invalidate(user_id)


@admin_bp.route("/api/users/<user_id>/revoke-sessions", methods=["POST"])
def revoke_sessions(user_id: str) -> Response | tuple[Response, int]:
    """End every session this account holds, right now.

    **The mechanism, and why it is this and not something more direct.**
    GoTrue's Admin API has no endpoint that revokes a user's sessions by id
    alone — confirmed against its Go source. The only thing that deletes every
    session/refresh-token row for a user is a password update with no session
    context, so that is what this calls, through
    :func:`web.services.auth_admin.SupabaseAuthAdminDispatcher.revoke_sessions`.
    The generated password is never seen by this route, this response, or the
    audit log — see that module's docstring.

    **What this does not do.** It does not touch ``is_disabled`` — chat access
    and session validity are a deliberately separate axis (see `TODO.md`). It
    does not chain a password-reset email automatically: incident containment
    and account recovery are two different decisions, and auto-sending mail to
    a possibly-compromised inbox as a side effect of a different action would
    be the wrong default. An operator who wants both clicks "send reset"
    separately, which already exists on this page.

    **The three-way audit outcome.** A transport failure (timeout, dropped
    connection) does not prove the mutation failed — GoTrue may have already
    committed it before this process learned the outcome. Recording that as an
    ordinary "failed" would be a false entry on the one surface whose purpose
    is to be trustworthy later, so it is recorded as `outcome_unknown` instead;
    only a structured, definitive provider rejection is ever `failed`.
    """
    import uuid as _uuid

    from web.services.audit import actor_from_request
    from web.services.auth_admin import AuthAdminRefused

    payload = request.get_json(silent=True)
    if payload not in (None, {}):
        return jsonify(
            {
                "error": "unknown_field",
                "fields": sorted(payload) if isinstance(payload, dict) else [],
            }
        ), 422

    backend = current_app.config["admin_backend"]()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    account = backend.get_user(user_id)
    if account is None:
        return jsonify({"error": "no_such_account"}), 404

    if (refusal_code := _actor_still_admin(backend)) is not None:
        return jsonify({"error": refusal_code}), 409

    actor = actor_from_request(g.identity)
    operation_id = str(_uuid.uuid4())
    backend.append_audit(
        action="user.sessions_revoke_requested",
        target_type="user",
        target_id=user_id,
        actor=actor,
        after={"status": "requested", "operation_id": operation_id},
    )

    dispatcher = current_app.config.get("auth_admin_dispatcher")
    dispatcher = dispatcher() if callable(dispatcher) else dispatcher

    try:
        if dispatcher is None:
            raise AuthAdminRefused("auth_admin_unavailable", "no dispatcher available")
        dispatcher.revoke_sessions(user_id)
    except AuthAdminRefused as refusal:
        outcome = "outcome_unknown" if refusal.ambiguous else "failed"
        if refusal.ambiguous:
            # GoTrue may already have committed the revocation despite the
            # transport failure — the whole reason this outcome is recorded
            # as "unknown" rather than "failed". The cache must resolve that
            # ambiguity in the safe direction: assume it happened.
            _evict_token_cache(user_id)
        backend.append_audit(
            action=f"user.sessions_revoke_{outcome}",
            target_type="user",
            target_id=user_id,
            actor=actor,
            after={"status": outcome, "operation_id": operation_id},
            # The code, never the provider's message body.
            note=refusal.code,
        )
        status = {
            "no_such_account": 404,
            "auth_admin_unavailable": 503,
        }.get(refusal.code, 502)
        return jsonify({"error": refusal.code, "outcome_unknown": refusal.ambiguous}), status

    # Unconditional and before the audit write: this is the one route whose
    # entire purpose is ending sessions right now, and the token cache is
    # exactly the thing that would otherwise let a revoked session keep
    # authenticating on reader routes for its TTL.
    _evict_token_cache(user_id)
    backend.append_audit(
        action="user.sessions_revoke_accepted",
        target_type="user",
        target_id=user_id,
        actor=actor,
        after={"status": "accepted", "operation_id": operation_id},
    )
    return jsonify({"accepted": True, "operation_id": operation_id})


@admin_bp.route("/api/users/<user_id>/change-email", methods=["POST"])
def change_email(user_id: str) -> Response | tuple[Response, int]:
    """Set this account's email immediately. No reader confirmation exists.

    **Why immediate, and why that is disclosed rather than hidden.** GoTrue's
    Admin API has no defer-until-confirmed flow — that only exists for a
    reader changing their own email through an authenticated session, which
    this console does not have. Live-verified against the real project (not
    assumed from documentation): passing ``email_confirm: False`` does *not*
    lock the account out — ``email_confirmed_at`` is left at its prior value,
    so a previously-confirmed account keeps signing in. What it actually
    leaves behind is an email identity marked unverified for the new address,
    which is why `admin_get_user` now returns `email_identity_verified`
    separately from `email_confirmed_at`, and why the account view must read
    that flag rather than treat the (now stale) confirmation timestamp as
    proof of the *current* address.

    **Why this refuses a self-target and `reset-password` does not.** Chained
    with the console's own existing "send password reset" button, an
    unconfirmed self-service email change is a complete account-impersonation
    primitive: change a victim's email, click reset, the reader never sees it
    coming. That risk is specific to *changing where the account's identity
    points*, not to resetting a credential or ending a session — which is why
    only this route, not `revoke-sessions` or the existing `reset-password`,
    guards against the operator targeting their own account.
    """
    import uuid as _uuid

    from web.services.audit import actor_from_request
    from web.services.auth_admin import AuthAdminRefused

    if g.identity.user_id and g.identity.user_id == user_id:
        return jsonify({"error": "cannot_change_own_email"}), 409

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_payload"}), 400

    unknown = set(payload) - {"email"}
    if unknown:
        return jsonify({"error": "unknown_field", "fields": sorted(unknown)}), 422

    new_email = payload.get("email")
    if not isinstance(new_email, str) or not new_email.strip():
        return jsonify({"error": "invalid_payload"}), 400
    new_email = new_email.strip()
    if len(new_email) > _EMAIL_MAX_LENGTH:
        return jsonify({"error": "too_long", "field": "email"}), 422
    if not _EMAIL_RE.match(new_email):
        return jsonify({"error": "invalid_email"}), 422

    backend = current_app.config["admin_backend"]()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    account = backend.get_user(user_id)
    if account is None:
        return jsonify({"error": "no_such_account"}), 404

    old_email = account.get("email")
    # Case-folded: retyping the same address with different casing is not a
    # change, and GoTrue treats addresses case-insensitively.
    if old_email and new_email.casefold() == old_email.casefold():
        return jsonify({"error": "same_email"}), 400

    if (refusal_code := _actor_still_admin(backend)) is not None:
        return jsonify({"error": refusal_code}), 409

    actor = actor_from_request(g.identity)
    operation_id = str(_uuid.uuid4())
    backend.append_audit(
        action="user.email_change_requested",
        target_type="user",
        target_id=user_id,
        actor=actor,
        before={"email": old_email},
        after={"status": "requested", "operation_id": operation_id, "email": new_email},
    )

    dispatcher = current_app.config.get("auth_admin_dispatcher")
    dispatcher = dispatcher() if callable(dispatcher) else dispatcher

    try:
        if dispatcher is None:
            raise AuthAdminRefused("auth_admin_unavailable", "no dispatcher available")
        dispatcher.change_email(user_id, new_email)
    except AuthAdminRefused as refusal:
        outcome = "outcome_unknown" if refusal.ambiguous else "failed"
        if refusal.ambiguous:
            # Same reasoning as revoke_sessions above: a transport failure
            # does not prove the mutation failed. Both caches, for the same
            # reason as the success path below — see `_evict_identity_caches`.
            _evict_identity_caches(user_id)
        backend.append_audit(
            action=f"user.email_change_{outcome}",
            target_type="user",
            target_id=user_id,
            actor=actor,
            before={"email": old_email},
            after={"status": outcome, "operation_id": operation_id, "email": new_email},
            note=refusal.code,
        )
        status = {
            "no_such_account": 404,
            "auth_admin_unavailable": 503,
            "email_already_registered": 409,
        }.get(refusal.code, 502)
        return jsonify({"error": refusal.code, "outcome_unknown": refusal.ambiguous}), status

    # Both caches — see `_evict_identity_caches`'s own docstring for why an
    # email change specifically needs the flags cache too, not just the
    # token cache.
    _evict_identity_caches(user_id)
    backend.append_audit(
        action="user.email_change_accepted",
        target_type="user",
        target_id=user_id,
        actor=actor,
        before={"email": old_email},
        after={"status": "accepted", "operation_id": operation_id, "email": new_email},
    )
    return jsonify({"accepted": True, "operation_id": operation_id})


@admin_bp.route("/api/users/<user_id>/profile", methods=["PATCH"])
def patch_profile(user_id: str) -> Response | tuple[Response, int]:
    """Rewrite a reader's own description of themselves, and record the diff.

    Its own route and its own RPC rather than a widening of `PATCH /users/<id>`.
    That one carries membership invariants — the advisory lock, the last-admin
    count — and profile text carries none of them; one endpoint whose refusal
    semantics differ per field is worse than two endpoints.
    """
    # Imported inside the view, matching the other handlers here: web.services
    # .audit is not needed to import this module, and the console is a surface
    # most deployments never open.
    from web.services.admin_store import AdminActionRefused
    from web.services.audit import actor_from_request

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_payload"}), 400

    unknown = set(payload) - set(_PROFILE_STRING_FIELDS) - {"age", "expected_updated_at"}
    if unknown:
        # Named explicitly. A console that sends `password` here should be told
        # so, not silently ignored — see test_no_console_route_accepts_a_password.
        return jsonify({"error": "unknown_field", "fields": sorted(unknown)}), 422

    values: dict[str, Any] = {}
    for field in _PROFILE_STRING_FIELDS:
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            return jsonify({"error": "invalid_payload"}), 400
        if isinstance(value, str) and len(value) > _PROFILE_STRING_MAX_LENGTH[field]:
            return jsonify({"error": "too_long", "field": field}), 422
        if field in ("first_name", "family_name") and isinstance(value, str):
            # Matches the DB's own normalisation (first_name = btrim(first_name)):
            # trimmed here so a padded value is reported as the value it becomes,
            # rather than reaching the CHECK and failing as a raw constraint error.
            value = value.strip() or None
        values[field] = value

    age = payload.get("age")
    if age is not None:
        # bool is a subclass of int in Python — reject it explicitly, or
        # {"age": true} would silently become age=1.
        if isinstance(age, bool) or not isinstance(age, int):
            return jsonify({"error": "invalid_payload"}), 400
        if not (_PROFILE_AGE_MIN <= age <= _PROFILE_AGE_MAX):
            return jsonify({"error": "out_of_range", "field": "age"}), 422
    values["age"] = age

    backend = current_app.config["admin_backend"]()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    try:
        updated = backend.update_profile(
            user_id,
            expected_updated_at=payload.get("expected_updated_at"),
            actor=actor_from_request(g.identity),
            **values,
        )
    except AdminActionRefused as refusal:
        return jsonify({"error": refusal.code}), 409

    return jsonify({"profile": updated})


@admin_bp.route("/api/users/<user_id>", methods=["PATCH"])
def patch_user(user_id: str) -> Response | tuple[Response, int]:
    """Change a role or chat access.

    "Chat access disabled" is named for what it actually does. The flag stops
    new requests through `auth_required`; it does NOT end a stream already
    running, revoke a Supabase refresh token, or prevent signing in. Calling it
    "account suspended" would promise all three.
    """
    from web.services.admin_store import AdminActionRefused
    from web.services.audit import actor_from_request

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_payload"}), 400

    role = payload.get("role")
    is_disabled = payload.get("is_disabled")
    reason = payload.get("reason")

    if role is not None and role not in ("user", "admin"):
        return jsonify({"error": "invalid_role"}), 422
    if is_disabled is not None and not isinstance(is_disabled, bool):
        return jsonify({"error": "invalid_payload"}), 400
    # Checked before `.strip()`, which raises on anything that is not a string —
    # a number here used to reach the client as a 500.
    if reason is not None and not isinstance(reason, str):
        return jsonify({"error": "invalid_payload"}), 400
    reason = (reason or "").strip() or None
    if role is None and is_disabled is None:
        return jsonify({"error": "nothing_to_change"}), 400

    # Required for a disable, and only for a disable. The console asks for one,
    # but asking is not enforcing: an empty prompt normalised to NULL, so the
    # accountability the reason exists for was optional in practice. Restoring
    # access needs no justification — the burden belongs on the restrictive act.
    if is_disabled is True and not reason:
        return jsonify({"error": "reason_required"}), 422

    backend = current_app.config["admin_backend"]()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    try:
        updated = backend.set_user_flags(
            user_id,
            role=role,
            is_disabled=is_disabled,
            reason=reason,
            actor=actor_from_request(g.identity),
        )
    except AdminActionRefused as refused:
        # Declined on principle rather than failed. 409: the request was
        # understood and is in conflict with a rule that exists to stop an
        # instance nobody can administer.
        logger.warning(
            "Refused %s on %s by %s: %s",
            request.method,
            user_id,
            g.identity.email,
            refused.code,
        )
        return jsonify({"error": refused.code}), 409

    # Before returning, not after: an operator must never watch their own
    # change fail to take effect. Chat requests re-read within the TTL;
    # console requests never use either cache.
    _evict_identity_caches(user_id)

    logger.info(
        "%s changed %s (role=%s disabled=%s)",
        g.identity.email,
        user_id,
        role,
        is_disabled,
    )
    return jsonify({"user": {"id": user_id, **updated}})


@admin_bp.route("/api/audit")
def audit() -> Response | tuple[Response, int]:
    """Recorded actions, newest first.

    Reading the log is deliberately not itself recorded. Auditing reads of a
    surface only administrators can reach produces noise that buries the
    signal; the line is drawn at state changes, plus any access to a reader's
    own content.
    """
    from web.services.audit import list_entries

    try:
        limit, offset = _parse_pagination_params(request)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_pagination"}), 400

    # Optional filter, so the account detail view can show one account's history
    # without a second route. Validated against a fixed set rather than passed
    # through: these reach a query, and `target_type` is a small closed
    # vocabulary that has no reason to grow from the client side.
    target_type = request.args.get("target_type") or None
    target_id = request.args.get("target_id") or None
    if target_type is not None and target_type not in ("user", "settings"):
        return jsonify({"error": "invalid_target"}), 422
    if target_id is not None and len(target_id) > 64:
        return jsonify({"error": "invalid_target"}), 422

    backend = current_app.config["admin_backend"]()
    entries = list_entries(
        backend,
        limit=limit,
        offset=offset,
        target_type=target_type,
        target_id=target_id,
    )
    return jsonify(
        {
            "entries": [entry.as_dict() for entry in entries],
            "limit": limit,
            "offset": offset,
        }
    )


_NOTIFICATION_TYPES = ("toast", "banner", "modal")
_NOTIFICATION_SEVERITIES = ("info", "success", "warning", "danger")
_NOTIFICATION_TARGET_KINDS = ("all", "role", "tier", "user")
_NOTIFICATION_TARGET_ROLES = ("user", "admin")
_NOTIFICATION_TITLE_MAX = 200
_NOTIFICATION_BODY_MAX = 2000


def _notification_backend():
    factory = current_app.config.get("notification_backend")
    return factory() if factory else None


def _validate_notification_targeting(payload: dict) -> tuple[dict, Response | tuple] | None:
    """``(fields, None)`` on success, or ``(None, error_response)``.

    Shared by the audience-preview and create routes so the two cannot
    silently drift about what a valid targeting payload looks like.

    Deliberately does NOT require ``target_user_id`` to parse as a uuid.
    Every real ``profiles.id`` is one, but the in-memory testing backend's
    seeded fixtures use human-readable ids ("test-user-id") — the same
    reason ``SupabaseAdminBackend.set_user_flags``/``update_profile`` do
    their own uuid validation at the backend layer instead of the route, so
    the check only ever fires against the real database. This mirrors that:
    format validation lives in ``SupabaseNotificationBackend``, not here.
    """
    target_kind = payload.get("target_kind")
    if target_kind not in _NOTIFICATION_TARGET_KINDS:
        return None, (jsonify({"error": "invalid_target_kind"}), 422)

    target_role = payload.get("target_role")
    target_tier = payload.get("target_tier")
    target_user_id = payload.get("target_user_id")

    if target_kind == "role":
        if target_role not in _NOTIFICATION_TARGET_ROLES:
            return None, (jsonify({"error": "invalid_target_role"}), 422)
        target_tier = None
        target_user_id = None
    elif target_kind == "tier":
        if not isinstance(target_tier, str) or not target_tier.strip():
            return None, (jsonify({"error": "invalid_target_tier"}), 422)
        target_tier = target_tier.strip()
        target_role = None
        target_user_id = None
    elif target_kind == "user":
        if not isinstance(target_user_id, str) or not target_user_id.strip():
            return None, (jsonify({"error": "invalid_target_user"}), 422)
        target_user_id = target_user_id.strip()
        target_role = None
        target_tier = None
    else:  # 'all'
        target_role = None
        target_tier = None
        target_user_id = None

    return (
        {
            "target_kind": target_kind,
            "target_role": target_role,
            "target_tier": target_tier,
            "target_user_id": target_user_id,
        },
        None,
    )


@admin_bp.route("/api/notifications/audience-preview", methods=["POST"])
def notifications_audience_preview() -> Response | tuple[Response, int]:
    """Dry run: how many accounts this targeting would currently reach.

    Persists nothing — the composer calls this on every targeting-field
    change, before any send. Excludes disabled accounts, matching what
    admin_create_notification actually snapshots/counts at send time.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_payload"}), 400

    fields, error = _validate_notification_targeting(payload)
    if error:
        return error

    backend = _notification_backend()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    count = backend.preview_audience(
        target_kind=fields["target_kind"],
        target_role=fields["target_role"],
        target_tier=fields["target_tier"],
        target_user_id=fields["target_user_id"],
    )
    return jsonify({"target_count": count})


@admin_bp.route("/api/notifications", methods=["POST"])
def create_notification() -> Response | tuple[Response, int]:
    """Send a broadcast notification: insert + recipient snapshot + audit
    row (one transaction, admin_create_notification) followed by a
    best-effort Realtime push to every targeted reader's private channel.

    The Realtime push happens AFTER the RPC commits and is never allowed to
    fail this response — REST is the guaranteed-delivery path
    (docs/notification-center-plan.md §2); Realtime only tells an
    already-open tab to refetch sooner than its next poll.
    """
    import uuid as _uuid

    from web.services.admin_store import AdminActionRefused
    from web.services.audit import actor_from_request
    from web.services.notification_service import (
        publish_notification_event,
        recipients_for_publish,
    )

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_payload"}), 400

    notification_type = payload.get("type")
    if notification_type not in _NOTIFICATION_TYPES:
        return jsonify({"error": "invalid_type"}), 422

    severity = payload.get("severity") or "info"
    if severity not in _NOTIFICATION_SEVERITIES:
        return jsonify({"error": "invalid_severity"}), 422

    texts: dict[str, str] = {}
    for field, limit in (
        ("title_en", _NOTIFICATION_TITLE_MAX),
        ("title_ar", _NOTIFICATION_TITLE_MAX),
        ("body_en", _NOTIFICATION_BODY_MAX),
        ("body_ar", _NOTIFICATION_BODY_MAX),
    ):
        value = payload.get(field)
        if not isinstance(value, str):
            return jsonify({"error": "invalid_payload"}), 400
        value = value.strip()
        if not value or len(value) > limit:
            return jsonify({"error": "invalid_field", "field": field}), 422
        texts[field] = value

    fields, error = _validate_notification_targeting(payload)
    if error:
        return error

    expires_at = payload.get("expires_at")
    if expires_at is not None and not isinstance(expires_at, str):
        return jsonify({"error": "invalid_payload"}), 400

    resend_of = payload.get("resend_of")
    if resend_of is not None:
        if not isinstance(resend_of, str):
            return jsonify({"error": "invalid_payload"}), 400
        try:
            _uuid.UUID(resend_of)
        except (ValueError, AttributeError, TypeError):
            return jsonify({"error": "invalid_payload"}), 400

    client_request_id = payload.get("client_request_id")
    if not isinstance(client_request_id, str):
        return jsonify({"error": "invalid_payload"}), 400
    try:
        _uuid.UUID(client_request_id)
    except (ValueError, AttributeError, TypeError):
        return jsonify({"error": "invalid_payload"}), 400

    backend = _notification_backend()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    try:
        created = backend.create(
            type=notification_type,
            severity=severity,
            title_en=texts["title_en"],
            title_ar=texts["title_ar"],
            body_en=texts["body_en"],
            body_ar=texts["body_ar"],
            target_kind=fields["target_kind"],
            target_role=fields["target_role"],
            target_tier=fields["target_tier"],
            target_user_id=fields["target_user_id"],
            expires_at=expires_at,
            resend_of=resend_of,
            client_request_id=client_request_id,
            actor=actor_from_request(g.identity),
        )
    except AdminActionRefused as refused:
        logger.warning("Refused notification send by %s: %s", g.identity.email, refused.code)
        return jsonify({"error": refused.code}), 409

    was_replay = created.pop("_replay", False)

    # Skipped under TESTING — see deactivate_notification's own comment.
    if not was_replay and not current_app.config.get("TESTING"):
        try:
            recipient_ids = recipients_for_publish(backend, created)
            publish_notification_event(
                recipient_ids,
                notification_id=created["id"],
                revision=created.get("created_at") or "",
                event="notify",
            )
        except Exception:
            # publish_notification_event already catches and logs its own
            # failures; this is a second line of defense so a bug in
            # resolving recipients cannot turn a successful send into a 500.
            logger.warning(
                "Could not resolve/publish Realtime recipients for notification %s.",
                created.get("id"),
                exc_info=True,
            )

    return jsonify({"notification": created}), (200 if was_replay else 201)


@admin_bp.route("/api/notifications/history", methods=["GET"])
def notification_history() -> Response | tuple[Response, int]:
    """Offset/limit, matching the rest of the admin surface (list_users,
    list_audit) — only the reader-facing history uses cursor pagination."""
    try:
        limit, offset = _parse_pagination_params(request)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_pagination"}), 400

    status = request.args.get("status") or "all"
    if status not in ("all", "active", "deactivated", "deleted"):
        return jsonify({"error": "invalid_status"}), 422

    backend = _notification_backend()
    if backend is None:
        return jsonify({"notifications": [], "total": 0, "limit": limit, "offset": offset})

    rows, total = backend.list_history(limit=limit, offset=offset, status=status)
    return jsonify({"notifications": rows, "total": total, "limit": limit, "offset": offset})


@admin_bp.route("/api/notifications/<notification_id>/deactivate", methods=["POST"])
def deactivate_notification(notification_id: str) -> Response | tuple[Response, int]:
    """Format validation for ``notification_id`` deliberately lives in
    ``SupabaseNotificationBackend`` (a malformed id there is a "not found",
    the same reasoning as ``SupabaseAdminBackend.set_user_flags``), not
    here — the in-memory testing backend mints real uuids for every
    notification it creates, so there is nothing for a route-level check to
    catch except a client typo, which the backend already turns into 404.
    """
    from web.services.admin_store import AdminActionRefused
    from web.services.audit import actor_from_request
    from web.services.notification_service import (
        publish_notification_event,
        recipients_for_publish,
    )

    backend = _notification_backend()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    try:
        updated = backend.deactivate(notification_id, actor=actor_from_request(g.identity))
    except AdminActionRefused as refused:
        status = 404 if refused.code == "no_such_notification" else 409
        return jsonify({"error": refused.code}), status

    # Same content-free push as create — an open tab must stop showing a
    # modal the operator just pulled, not wait for its next reload. Skipped
    # under TESTING: there is no live Realtime endpoint behind the in-memory
    # backend, so attempting the HTTP call would just be a slow, pointless
    # DNS/connect failure on every test run rather than a meaningful check.
    if not current_app.config.get("TESTING"):
        try:
            recipient_ids = recipients_for_publish(backend, updated)
            publish_notification_event(
                recipient_ids,
                notification_id=notification_id,
                revision=updated.get("deactivated_at") or "",
                event="notify",
            )
        except Exception:
            logger.warning(
                "Could not publish deactivation for notification %s.",
                notification_id,
                exc_info=True,
            )

    return jsonify({"notification": updated})


@admin_bp.route("/api/notifications/<notification_id>", methods=["DELETE"])
def delete_notification(notification_id: str) -> Response | tuple[Response, int]:
    """Soft delete only. Preserves recipient/read history for audit review.

    Same "format validation lives in the Supabase backend" reasoning as
    ``deactivate_notification`` above.
    """
    from web.services.admin_store import AdminActionRefused
    from web.services.audit import actor_from_request
    from web.services.notification_service import (
        publish_notification_event,
        recipients_for_publish,
    )

    backend = _notification_backend()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    try:
        updated = backend.delete(notification_id, actor=actor_from_request(g.identity))
    except AdminActionRefused as refused:
        status = 404 if refused.code == "no_such_notification" else 409
        return jsonify({"error": refused.code}), status

    if not current_app.config.get("TESTING"):
        try:
            recipient_ids = recipients_for_publish(backend, updated)
            publish_notification_event(
                recipient_ids,
                notification_id=notification_id,
                revision=updated.get("deleted_at") or "",
                event="notify",
            )
        except Exception:
            logger.warning(
                "Could not publish deletion for notification %s.", notification_id, exc_info=True
            )

    return jsonify({"notification": updated})


@admin_bp.route("/api/notifications/<notification_id>/purge", methods=["POST"])
def purge_notification(notification_id: str) -> Response | tuple[Response, int]:
    """Permanent erasure of an already-Deleted notification and its
    recipient/read-receipt rows. See admin_purge_notification's own
    migration comment for why this never enforces the retention-days
    setting server-side — that setting only filters what the console's bulk
    "Purge eligible" action sends here, one id at a time; a manual purge (this
    route, called directly) is always the administrator's own call.

    No Realtime publish here, unlike deactivate/delete: by the time
    something is purge-eligible it has already been Deleted (and any
    Realtime invalidation for that already fired), so there is no open tab
    left that could still be showing it.
    """
    from web.services.admin_store import AdminActionRefused
    from web.services.audit import actor_from_request

    backend = _notification_backend()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    try:
        result = backend.purge(notification_id, actor=actor_from_request(g.identity))
    except AdminActionRefused as refused:
        status = 404 if refused.code == "no_such_notification" else 409
        return jsonify({"error": refused.code}), status

    return jsonify(result)


@admin_bp.route("/api/notifications/purge-settings", methods=["GET"])
def notifications_purge_settings() -> Response | tuple[Response, int]:
    """The retention window (days) the console's "Purge eligible" bulk
    action uses. See get_purge_retention_days's own docstring for why this
    is a small standalone setting rather than routed through the generation
    SettingsService."""
    from web.services.notification_store import get_purge_retention_days

    backend = current_app.config["admin_backend"]()
    return jsonify({"purge_retention_days": get_purge_retention_days(backend)})


@admin_bp.route("/api/notifications/purge-settings", methods=["PUT"])
def update_notifications_purge_settings() -> Response | tuple[Response, int]:
    from web.services.audit import actor_from_request
    from web.services.notification_store import set_purge_retention_days

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or "purge_retention_days" not in payload:
        return jsonify({"error": "invalid_payload"}), 400

    backend = current_app.config["admin_backend"]()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    try:
        days = set_purge_retention_days(
            backend, payload["purge_retention_days"], actor=actor_from_request(g.identity)
        )
    except ValueError:
        return jsonify({"error": "invalid_purge_retention_days"}), 422

    return jsonify({"purge_retention_days": days})


@admin_bp.route("/api/identity")
def identity() -> Response | tuple[Response, int]:
    """Confirms the caller is an administrator.

    Reaching this at all is the answer; the body just names who. The console
    calls it before rendering anything privileged, so a reader who somehow
    loaded the shell is told nothing and shown nothing.
    """
    flags = g.identity
    return jsonify(
        {
            "user_id": flags.user_id,
            "email": flags.email,
            "role": flags.role,
            "tier": flags.tier,
            "is_admin": flags.is_admin,
        }
    )
