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
    from web.services.settings_service import allowed_models

    service = current_app.config["settings_service"]
    return jsonify({
        "settings": service.snapshot(),
        "overrides": service.overrides(),
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

    service = current_app.config["settings_service"]
    errors = service.update(payload, actor_id=g.identity.user_id)

    if errors:
        return jsonify({
            "error": "validation_failed",
            "errors": [error.as_dict() for error in errors],
        }), 422

    logger.info(
        "Settings updated by %s: %s", g.identity.email, sorted(payload)
    )
    return jsonify({
        "settings": service.snapshot(),
        "overrides": service.overrides(),
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
