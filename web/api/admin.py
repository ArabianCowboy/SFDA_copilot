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
from typing import Optional, Tuple

from flask import Blueprint, Response, current_app, g, jsonify, render_template, request

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# Endpoints that deliberately serve without a role. Default-deny: anything not
# named here is gated, so a new route is protected by omission rather than by
# somebody remembering to protect it.
#
# The console shell is the only member and must stay the only member. It renders
# no account data, no settings, and no counts — see the module docstring.
_UNGATED_ENDPOINTS = frozenset({"admin.console"})


def _bearer_token() -> Optional[str]:
    """The token from an explicit Authorization header, or None.

    Deliberately not ``_get_token_from_request``: that one falls back to a
    cookie and to the Flask session, and a privileged endpoint reachable by
    ambient credentials is a privileged endpoint reachable by cross-site
    request forgery.
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[len("Bearer "):].strip()
    return token or None


@admin_bp.before_request
def _gate() -> Optional[Response]:
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
        logger.warning(
            "Non-administrator %s attempted %s", identity.user_id, request.path
        )
        return jsonify({"error": "forbidden"}), 403

    return None


@admin_bp.route("/", strict_slashes=False)
def console() -> Response:
    """The console shell. Renders no privileged data — see the module docstring."""
    from web.api.app import ADMIN_MODULE_FILENAMES, MODULE_FILENAMES

    build_map = current_app.jinja_env.globals["_import_map"]

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
    return render_template("admin.html", **context, module_import_map=import_map)


@admin_bp.route("/api/settings", methods=["GET"])
def get_settings() -> Response:
    """The effective settings, plus what an operator is allowed to choose.

    `overrides` is sent alongside `settings` so the console can distinguish a
    value someone chose from a value that merely happens to be the deployed
    default — the two look identical and revert differently.
    """
    from web.services.settings_service import allowed_models, deployed_defaults

    service = current_app.config["settings_service"]
    return jsonify({
        "settings": service.snapshot(),
        "overrides": service.overrides(),
        # What each value reverts TO. An overridden field hides its own default
        # — the effective value *is* the override — so without this the console
        # cannot offer "revert" without guessing, and a guess that happens to
        # equal the default would pin it instead of restoring inheritance.
        "defaults": deployed_defaults(),
        "allowed_models": allowed_models(),
    })


@admin_bp.route("/api/settings", methods=["PUT"])
def put_settings() -> Response:
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

    errors = service.update(
        payload, actor=actor_from_request(g.identity), on_committed=apply_now
    )

    if errors:
        return jsonify({
            "error": "validation_failed",
            "errors": [error.as_dict() for error in errors],
        }), 422

    logger.info("Settings updated by %s: %s", g.identity.email, sorted(payload))

    # Reported rather than raised: the settings are already stored, so a handler
    # that would not build is a reason to tell the operator their change is not
    # live yet — not a reason to fail a write that succeeded, and certainly not
    # a reason to take the chatbot down.
    applied = outcome["applied"]
    if not applied:
        logger.error("Settings were stored but could not be applied to generation.")

    from web.services.settings_service import deployed_defaults

    return jsonify({
        "settings": service.snapshot(),
        "overrides": service.overrides(),
        "defaults": deployed_defaults(),
        "applied": applied,
    })


@admin_bp.route("/api/users")
def users() -> Response:
    """Accounts, newest first, with their standing."""
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_pagination"}), 400

    backend = current_app.config["admin_backend"]()
    if backend is None:
        return jsonify({"error": "storage_unavailable"}), 503

    rows, total = backend.list_users(
        limit=limit, offset=offset, search=request.args.get("q") or None
    )
    return jsonify({
        "users": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        # So the console can mark "you" in the list and grey out the controls it
        # knows the server will refuse. The refusal is still enforced server-side;
        # this only stops the operator discovering it by being told no.
        "self_id": g.identity.user_id,
    })


@admin_bp.route("/api/users/<user_id>", methods=["PATCH"])
def patch_user(user_id: str) -> Response:
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
            request.method, user_id, g.identity.email, refused.code,
        )
        return jsonify({"error": refused.code}), 409

    # Before returning, not after: the cache is a latency optimisation and an
    # operator must never watch their own change fail to take effect. Chat
    # requests re-read within the TTL; console requests never use the cache.
    current_app.config["identity_flags"].invalidate(user_id)

    logger.info(
        "%s changed %s (role=%s disabled=%s)",
        g.identity.email, user_id, role, is_disabled,
    )
    return jsonify({"user": {"id": user_id, **updated}})


@admin_bp.route("/api/audit")
def audit() -> Response:
    """Recorded actions, newest first.

    Reading the log is deliberately not itself recorded. Auditing reads of a
    surface only administrators can reach produces noise that buries the
    signal; the line is drawn at state changes, plus any access to a reader's
    own content.
    """
    from web.services.audit import list_entries

    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_pagination"}), 400

    backend = current_app.config["admin_backend"]()
    entries = list_entries(backend, limit=limit, offset=offset)
    return jsonify({
        "entries": [entry.as_dict() for entry in entries],
        "limit": limit,
        "offset": offset,
    })


@admin_bp.route("/api/identity")
def identity() -> Response:
    """Confirms the caller is an administrator.

    Reaching this at all is the answer; the body just names who. The console
    calls it before rendering anything privileged, so a reader who somehow
    loaded the shell is told nothing and shown nothing.
    """
    flags = g.identity
    return jsonify({
        "user_id": flags.user_id,
        "email": flags.email,
        "role": flags.role,
        "tier": flags.tier,
        "is_admin": flags.is_admin,
    })
