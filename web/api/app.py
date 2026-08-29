"""
SFDA Copilot – Flask application entry-point
Final optimized version combining robust patterns, modern syntax, and maximum readability.
"""

from __future__ import annotations

import os

# Must be set before PyTorch/sentence-transformers loads to prevent
# segfault during interpreter shutdown on macOS arm64 (Python 3.14+).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import base64
import json
import logging
import math
import sys
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import (  # Added Callable
    Any,
    cast,
)
from urllib.parse import urlparse

import httpx
import yaml
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix  # For reverse proxy support
from werkzeug.wrappers import Response as WerkzeugResponse

# GoTrue's own "this one is worth retrying" signal. Imported defensively and
# behind two names because the package was renamed from `gotrue` to
# `supabase_auth` mid-2.x: a hard import would turn a dependency bump into a
# boot failure, and the classifier below degrades to the httpx check alone.
# Declared up front so mypy treats every branch below as assigning to one
# variable rather than redefining a name each import rebinds.
AuthError: type[Exception] | None
AuthRetryableError: type[Exception] | None
AuthUnknownError: type[Exception] | None
try:
    from supabase_auth.errors import AuthError, AuthRetryableError, AuthUnknownError
except ImportError:  # pragma: no cover - exercised only on older/newer pins
    try:
        from gotrue.errors import (  # type: ignore[no-redef]
            AuthError,
            AuthRetryableError,
            AuthUnknownError,
        )
    except ImportError:
        AuthError = None
        AuthRetryableError = None
        AuthUnknownError = None

from flask import (
    Flask,
    Response,
    current_app,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    stream_with_context,
    url_for,
)
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman

# This module's own logger, rather than the `logging.info(...)` module functions
# that used to be called throughout. Those route to the ROOT logger, and the
# root-logger functions call `basicConfig()` themselves when no handler is
# installed yet — so the very first one, at import time on the line below,
# configured the root logger with library defaults and left the deliberate
# `basicConfig(level=..., format=...)` a few lines further down guarded behind
# `if not logging.getLogger().handlers` — already false, never applied.
#
# A named logger does not do that. It also means these records carry
# "web.api.app" instead of "root", which is what LOG_LEVEL_* per-module tuning
# and every other module in this app already assume.
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────
# Project Path & Environment Setup
# ──────────────────────────────────────────────────────────
# Use pathlib for modern, object-oriented path handling
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DOTENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=DOTENV_PATH, override=True)
logger.info("Loaded .env from %s", DOTENV_PATH)

# ──────────────────────────────────────────────────────────
# Logging Configuration
# ──────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Configure a root logger if not already configured
# This ensures all logs, including those from openai_app, are handled
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=LOG_LEVEL, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

# Explicitly set the level for the openai_app logger to INFO
logging.getLogger("web.services.openai_app").setLevel(logging.INFO)

# Optional: Add a file handler for persistent logs
# handler = RotatingFileHandler('app.log', maxBytes=10000, backupCount=3)
# handler.setLevel(logging.INFO)
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# handler.setFormatter(formatter)
# logging.getLogger().addHandler(handler)

for module, default_level in [
    ("web.services.search_engine", "DEBUG"),
    ("web.utils.config_loader", "DEBUG"),
    ("web.utils.openai_client", "DEBUG"),
    ("web.utils.local_embedding_client", "DEBUG"),
]:
    env_var_name = f"LOG_LEVEL_{module.split('.')[-1].upper()}"
    level = os.getenv(env_var_name, default_level).upper()
    logging.getLogger(module).setLevel(level)

for _name in ("httpx", "httpcore", "huggingface_hub"):
    logging.getLogger(_name).setLevel(logging.WARNING)

# ──────────────────────────────────────────────────────────
# Application-Specific Imports (after logger setup)
# ──────────────────────────────────────────────────────────
from web.api.auth import (
    IDENTITY_MARKER_KEYS,
    auth_bp,
    recover_bp,
    rotate_session_for_new_identity,
    signup_bp,
)
from web.services.account_recovery import (
    InMemoryRecoveryDispatcher,
    RecoveryRefused,
    get_recovery_dispatcher,
    recovery_redirect_url,
)
from web.services.admin_store import (
    InMemoryAdminBackend,
    get_admin_backend,
    resolve_identity_flags,
)
from web.services.auth_admin import (
    InMemoryAuthAdminDispatcher,
    get_auth_admin_dispatcher,
)
from web.services.chat_store import (
    InMemoryChatBackend,
    PersistenceUnavailable,
    StoredMessage,
    archive_keys,
    canonical_uuid,
    clamp_list_limit,
    clamp_load_limit,
    clamp_title,
    get_chat_backend,
    new_conversation_id,
)
from web.services.citations import (
    build_source_payload,
    extract_cited_indices,
    normalize_legacy_citations,
)
from web.services.conversation_store import ConversationStore
from web.services.identity_cache import IdentityFlags, IdentityFlagsCache
from web.services.notification_store import (
    InMemoryNotificationBackend,
    get_notification_backend,
)
from web.services.openai_app import OpenAIHandler
from web.services.search_engine import ImprovedSearchEngine, SearchResult
from web.services.search_exceptions import ManifestValidationError, SearchEngineError
from web.services.settings_service import SettingsService
from web.services.sse import sse, sse_headers
from web.services.token_verification_cache import (
    TokenVerificationCache,
    TokenVerificationTimeout,
    VerifiedIdentity,
)
from web.utils.config_loader import config
from web.utils.hashing import sha256_hex
from web.utils.i18n import (
    load_catalog,
    make_translator,
    normalize_lang,
    pick_lang,
    runtime_subset,
    text_direction,
)
from web.utils.icons import CATEGORY_ICONS, icon, runtime_icons
from web.utils.supabase_client import _auth_timeout, get_supabase

# ──────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────
# Fallback for `server.chat_history_char_budget`. This was 3,500 and named
# MAX_SESSION_CHAT_HISTORY_CHARS, which was right when history rode the signed
# session cookie: the browser drops a cookie over ~4KB, so the budget was a
# hard external limit. Moving history into ConversationStore removed that
# limit but kept the number, and a bound sized for a cookie is punitive for
# RAM — a single ordinary answer here runs 3,000-9,000 characters, so the
# budget was routinely smaller than ONE exchange and the store spent its time
# deleting the conversation instead of holding it.
#
# What bounds it now is server memory: this ceiling times ConversationStore's
# 500 conversations, so ~12MB of history at worst. It is a soft budget — see
# _truncate, which will exceed it rather than drop the newest exchange.
DEFAULT_CHAT_HISTORY_CHAR_BUDGET = 60_000
DEFAULT_MAX_CHAT_MESSAGES_COUNT = 5
# A question, not an essay. `_validate_chat_request` had no length bound at all,
# so a 200KB body was accepted, embedded, sent to the model and — once questions
# became durable — stored forever. Set well above any real regulatory question
# and well below the point where one row is a problem.
MAX_CHAT_QUERY_CHARS = 8_000
# Ordered, because this tuple is also what the 400 for a bad category lists back
# to the caller. Joining the set below instead — which is what that message used
# to do — reordered the allowed categories on every process start, since set
# iteration order follows string hashes and PYTHONHASHSEED is random. An error
# message that reads differently each restart is one nobody can grep a log for.
CHAT_CATEGORIES = ("all", "regulatory", "pharmacovigilance", "veterinary", "biological")
ALLOWED_CHAT_CATEGORIES = frozenset(CHAT_CATEGORIES)
# The chat routes negotiate their own languages and the FAQ negotiates its own.
# They agree today; they are named separately because nothing requires them to.
SUPPORTED_CHAT_LANGS = frozenset(("en", "ar"))
SUPPORTED_FAQ_LANGS = ("en", "ar")

# Cache-buster appended to every static CSS/JS URL. Bump this in any commit that
# changes a stylesheet or module, otherwise returning users get a stale
# components.css against a fresh tokens.css and see a half-styled app.
#
# "every" is load-bearing and was not always true: the <script> tag carries the
# version for app.js, but a static `import './modules/ui.js'` inside it resolves
# to a bare, unversioned URL, so the modules were never busted at all. A page
# that mixes a fresh template with a stale module is worse than a stale page —
# post-icon-migration it would render an <i class="bi"> with no icon font behind
# it, or print a glyph NAME as text. MODULE_IMPORT_MAP below closes that.
ASSET_VERSION = "warm63"

# Product release, rendered in the landing footer. The single source — do not
# hand-type this value into a JS docstring or any other comment; that duplication
# is exactly what let static/js/app.js and admin.js drift out of step before both
# were cleaned up. See CLAUDE.md rule 9 for when a commit must bump this.
APP_VERSION = "0.7.0 (Beta)"

# The privacy policy's own version, recorded on every consent grant
# (docs/profile-refactor-plan.md §16·3, Spec 3) so a consent record stays
# attributable to the actual text it was given under. One constant, read by
# the signup form, the /account consent toggle and /privacy itself, so the
# three cannot drift the way three separately-typed literals would.
#
# DRAFT: written to unblock Step 6's engineering per the product owner's own
# instruction (2026-08-23) -- bump this string whenever /privacy's substance
# changes, including when the draft is replaced with reviewed content.
PRIVACY_POLICY_VERSION = "2026-08-23-draft-1"

# Every ES module under static/js/modules, mapped to its versioned URL. A
# browser-native import map is the only way to version static imports without a
# bundler, which this project deliberately does not have: the map rewrites the
# resolved URL of `./modules/ui.js` (and of the imports those modules make of
# each other) before the request goes out.
#
# Enumerated once at import: the set of modules is fixed at deploy time, so a
# per-request directory scan would buy nothing. Adding a module needs a restart,
# which shipping one needs anyway.
#
# A browser without import-map support simply loads the unversioned URLs — the
# behaviour before this existed — so this degrades rather than breaks.
MODULE_FILENAMES: tuple[str, ...] = tuple(
    sorted(p.name for p in (PROJECT_ROOT / "static" / "js" / "modules").glob("*.js"))
)

# The console's own modules live in static/js/admin/ rather than alongside the
# reader's, and the separation is not tidiness. `index()` inlines an import-map
# entry for *every* name in MODULE_FILENAMES, so a module dropped in beside the
# others would publish its filename on the anonymous landing page — an
# inventory of the operator surface, rendered for people who cannot reach it.
# A second directory and a second map keeps each page declaring only what it
# can actually load.
ADMIN_MODULE_FILENAMES: tuple[str, ...] = tuple(
    sorted(p.name for p in (PROJECT_ROOT / "static" / "js" / "admin").glob("*.js"))
)

# The account page's own modules, for the same reason ADMIN_MODULE_FILENAMES
# is separate from MODULE_FILENAMES: a module dropped in beside the others
# would publish its filename in the anonymous landing page's import map.
ACCOUNT_MODULE_FILENAMES: tuple[str, ...] = tuple(
    sorted(p.name for p in (PROJECT_ROOT / "static" / "js" / "account").glob("*.js"))
)

# ──────────────────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────────────────


def _get_token_from_request() -> str | None:
    """Return a Supabase JWT from Bearer header, cookie, or session."""
    if auth_header := request.headers.get("Authorization"):
        return (
            auth_header.split("Bearer ")[-1] if auth_header.startswith("Bearer ") else auth_header
        )
    return request.cookies.get("sb-access-token") or session.get("supabase_access_token")


def _handle_unauthorized(is_page_request: bool) -> Response | tuple[Response, int]:
    """Redirect for page requests or return a JSON error for API requests."""
    clear_auth_session()
    if is_page_request:
        return cast(Response, redirect(url_for("index")))
    return jsonify({"error": "Authorization required"}), 401


def clear_auth_session() -> None:
    """Purge authentication data from the Flask session."""
    session.pop("supabase_access_token", None)
    session.pop("user_email", None)
    # The admin render hint is authentication data too. Leaving it behind on the
    # 401 path would strand an elevated marker on a shared machine's cookie —
    # the precise leak the identity rotation exists to prevent, and no less real
    # for the marker being cosmetic.
    for key in IDENTITY_MARKER_KEYS:
        session.pop(key, None)


def _bind_session_to_identity(identity: str) -> None:
    """Tie this cookie's legacy conversation litter to one authenticated reader.

    The belt to the logout route's braces. Logout is the *cooperative* path and
    plenty of real endings skip it: a closed tab, an expired refresh token, a
    revoked session, a client that never called it. Any of those leaves a valid
    Flask cookie behind — and a pre-migration one could still be carrying raw
    `chat_history`/`prev_chat_history` (`CONVERSATION_SESSION_KEYS`, auth.py),
    which the next person to sign in on that browser would otherwise inherit.

    So identity is checked on every authenticated request rather than trusted
    to have been cleaned up on the way out. A change means a different person
    is holding this cookie, and their conversation starts empty.
    """
    previous = session.get("auth_identity")
    if previous is not None and previous != identity:
        rotate_session_for_new_identity()
        logger.info("Authenticated identity changed for this session; conversation purged.")
    session["auth_identity"] = identity


# Identities the TESTING bypass can present, most specific match first.
#
# ORDER IS LOAD-BEARING. Not because these three collide — "fake_token" is not a
# contiguous substring of "fake_admin_token" — but because a future marker such
# as `fake_token_admin` would contain it, and a plain-reader entry checked first
# would silently shadow the privileged one. Most privileged, most specific, first.
#
# The plain `fake_token` row is the literal five server test files send, and its
# resolution must not change: `user_email` stays "test@example.com" because that
# is what existing assertions read.
_TESTING_IDENTITIES: tuple[tuple[str, IdentityFlags], ...] = (
    (
        "fake_admin_token",
        IdentityFlags("test-admin-id", "admin@example.com", "admin", "internal", False),
    ),
    (
        "fake_disabled_token",
        IdentityFlags("test-disabled-id", "disabled@example.com", "user", "free", True),
    ),
    # A SECOND ORDINARY READER, added with durable history.
    #
    # Until now every isolation test faked its second reader by writing
    # `flask_session["auth_identity"]` directly while the Authorization header
    # still resolved to `test-user-id`. That was sufficient while history lived
    # only in RAM keyed by a cookie: the assertion was about the cookie
    # rotating, and one identity could stand in for two.
    #
    # It stops being sufficient the moment rows are owned. Both requests carried
    # the SAME owner into the database, so a test asking "does B see A's
    # history?" was really asking "does A see A's history?" — to which the
    # answer is yes, and must be. Proving isolation needs two owners that differ
    # where it counts, which is the owner column.
    (
        "fake_reader_b_token",
        IdentityFlags("test-reader-b-id", "reader-b@example.com", "user", "free", False),
    ),
    (
        "fake_token",
        IdentityFlags("test-user-id", "test@example.com", "user", "free", False),
    ),
)


def _testing_identity() -> IdentityFlags | None:
    """Resolve the TESTING bypass token to an identity, or None if absent."""
    header = request.headers.get("Authorization", "")
    return next((flags for marker, flags in _TESTING_IDENTITIES if marker in header), None)


def _is_page_request() -> bool:
    """True for a browser navigating to a page, false for an API call.

    Decides whether a rejection is a redirect or a JSON error. Previously this
    only ever matched `index`, which is not decorated with `@auth_required` —
    so the redirect branch was unreachable. The admin blueprint's page route is
    the first gated GET the app has had.
    """
    if request.method != "GET":
        return False
    # Endpoints, not the blueprint. `request.blueprint == "admin"` matched every
    # console route including /admin/api/*, so an invalid bearer on a JSON
    # endpoint answered with a 302 to `/`. `fetch()` follows redirects by
    # default, so the console received 200 OK and a page of HTML, parsed it as
    # null, and carried on as though identity had been confirmed.
    return request.endpoint in ("index", "admin.console")


def _account_disabled_response() -> tuple[Response, int]:
    """403, deliberately, rather than 401.

    401 means "your credentials are missing or invalid", and `_handle_unauthorized`
    acts on that by clearing the session. A disabled reader would then be logged
    out, log back in successfully, and be bounced again — a loop that reads as a
    bug in the product rather than a decision about their account.

    403 says the opposite and the true thing: we know exactly who you are, and
    the answer is still no. The body carries a machine code, not a sentence —
    the client already owns every reader-facing string, in both languages, and a
    localized message from the server would be a second translation path nothing
    else in this app has.
    """
    return jsonify({"error": "account_disabled"}), 403


def _identity_unavailable_response() -> tuple[Response, int]:
    """503, and — critically — the session is left alone.

    The counterpart to `_account_disabled_response`, for the opposite failure.
    That one says "we know who you are and the answer is no"; this one says "we
    could not find out". Neither is 401, because 401 means the credential was
    missing or bad, and `_handle_unauthorized` acts on that by destroying the
    session.

    `identity_unavailable` rather than a new code: the admin gate already
    answers exactly this way when the *profile* store cannot be read
    (`web/api/admin.py`). The same sentence should not arrive under two names
    depending on which hop failed.
    """
    return jsonify({"error": "identity_unavailable"}), 503


def _is_upstream_outage(exception: BaseException) -> bool:
    """ "We could not reach the thing that knows" — as opposed to a bad token.

    The distinction was missing entirely: one bare `except Exception` answered
    both with 401, so a read timeout to GoTrue told a signed-in administrator
    they were signed out *and* cleared their session on the way. The repo had
    already written this rule down one layer lower — see the `is_resolved`
    branch in `web/api/admin.py` and
    `test_an_identity_outage_is_a_503_not_a_refusal` — and this is that rule
    applied to the hop above it.

    `httpx.TransportError` is the whole family: connect, read, write and pool
    timeouts, connection failures, protocol errors. `AuthRetryableError` is
    GoTrue's own name for "ask again". A 5xx from the auth service is its
    outage, not the caller's fault.

    **429 counts too**, which is not obvious. A rate limit is the provider
    declining to answer right now, not a verdict on the credential — and this
    app asks GoTrue to verify a token on *every* authenticated request, so
    opening the console costs four verifications before an operator has clicked
    anything. Landing that in the refusal branch would sign an administrator out
    for being busy. The cost of counting it here is that the console retries the
    GET once, which is a rounding error against the fan-out that provoked it.

    **`TokenVerificationTimeout` counts too.** It means a waiter gave up
    waiting for another thread's in-flight verification, not that anyone's
    credential was judged bad — see
    `web/services/token_verification_cache.py`. Treating it as anything but an
    outage would turn a busy process into a stream of reader sign-outs.
    """
    if isinstance(exception, TokenVerificationTimeout):
        return True
    if isinstance(exception, httpx.TransportError):
        return True
    if AuthRetryableError is not None and isinstance(exception, AuthRetryableError):
        return True
    status = getattr(exception, "status", None)
    return isinstance(status, int) and (status >= 500 or status == 429)


def _is_auth_refusal(exception: BaseException) -> bool:
    """A genuine "no": an expired JWT, a malformed one, a revoked session.

    Only GoTrue's own error family counts. This is deliberately not the default
    branch — the audit that found the timeout bug also found that a missing
    environment variable, a malformed provider response, and any bug in identity
    resolution all landed on the same 401. "Your credentials are bad" is exactly
    as untrue for a server fault as it is for a network one, and it carries the
    same cost: the session is cleared on the way out.
    """
    if AuthError is None:
        # No error family to test against. Answering "yes, a refusal" here would
        # be the safe-looking choice and is the wrong one: the only way this
        # branch is reached is that the auth library could not be imported at
        # all, which means `get_user` never works — so every request would 401
        # and clear its session, which is precisely the bug this function was
        # added to fix, restored in the degenerate case. A missing library is a
        # fault on our side, so say so.
        return False

    # `AuthUnknownError` is inside the family and is not a verdict. GoTrue's
    # `handle_exception` returns it when it could not parse the provider's error
    # body at all — its second argument is literally the parse failure. "We could
    # not understand why the call failed" is not "your credential is bad", and
    # answering 401 there would clear a valid session over a malformed response.
    if AuthUnknownError is not None and isinstance(exception, AuthUnknownError):
        return False

    if not isinstance(exception, AuthError):
        return False

    # A refusal is the strongest claim this function can make — it ends in a 401
    # and a destroyed session — so it has to rest on actual evidence. Every error
    # the library raises for a rejected credential carries an integer status
    # (`AuthInvalidJwtError`, `AuthSessionMissingError` and
    # `AuthInvalidCredentialsError` are all 400; `AuthApiError` is constructed
    # with `status_code or 500`). One arriving without a usable status has not
    # established anything, and "we cannot tell" is our failure, not the
    # reader's.
    return isinstance(getattr(exception, "status", None), int)


class _ProviderResponseUnusable(Exception):
    """GoTrue answered, but not in a shape this app understands.

    Not a refusal and not an outage — a response in a shape we do not
    understand. Raising a distinct type keeps it out of BOTH classifiers, so
    it lands on the 500 branch that already exists for our own faults rather
    than telling the reader their credential is bad.
    """


# The 60-second grace on `exp` below is for OUR clock, not the token's: a VPS
# with drifting NTP must not start refusing valid credentials, and being 60
# seconds generous about a bound GoTrue enforces itself costs nothing.
_CLOCK_LEEWAY_SECONDS = 60


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    """Best-effort, UNVERIFIED decode of a JWT's payload segment.

    The signature is never inspected — this cannot possibly confirm a token is
    good, only that it cannot possibly be. Every parse failure is swallowed
    and answered with None; this must never raise into the auth path.

    `RecursionError` is caught alongside the obvious parse errors, not just
    `ValueError`/`TypeError`/`UnicodeDecodeError`: `json.loads` recurses per
    nesting level, and a payload segment of a few thousand nested `[` — well
    within an ordinary header's size — raises it instead of `ValueError`.
    Without this, that one crafted (not even forged — no signature is ever
    checked here) token would propagate uncaught out of an unauthenticated
    call and past every classifier in `_authenticate_request`.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        return None
    return payload if isinstance(payload, dict) else None


def _valid_exp(payload: dict[str, Any]) -> float | None:
    """The payload's `exp` claim, or None if it is absent or unusable.

    Shared by both callers below so "what counts as a usable `exp`" has one
    definition. `math.isfinite` matters, not just the `isinstance` check:
    JSON's own grammar has no `Infinity`/`NaN` literals, but `json.loads`
    accepts them anyway (a de facto extension every stdlib implementation
    ships), and `float("inf") + _CLOCK_LEEWAY_SECONDS > time.time()` is
    trivially true. A payload of `{"exp": Infinity}` would otherwise be
    treated as "structurally live" by the fast-reject filter whose entire
    documented purpose is rejecting garbage in microseconds — defeating that
    optimisation for exactly the crafted input it exists to catch.
    """
    exp = payload.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    if not math.isfinite(exp):
        return None
    return float(exp)


def _is_structurally_live(token: str) -> bool:
    """Reject input that cannot possibly be a live token — before any network call.

    NOT authentication. A structural check that costs no network and can only
    ever say "this cannot possibly be live" — three segments,
    base64url-decodable, and an `exp` that has not already passed. A token
    that clears it is not thereby trusted; it still goes to GoTrue, which
    remains the only authority.

    It exists because the one attack a token-verification cache does NOT help
    with is a flood of DISTINCT invalid tokens: every one is a cache miss, and
    concurrent misses each hold a request thread for a network round trip.
    Garbage is rejected in microseconds instead.
    """
    payload = _decode_jwt_payload(token)
    if payload is None:
        return False
    exp = _valid_exp(payload)
    if exp is None:
        return False
    return exp + _CLOCK_LEEWAY_SECONDS > time.time()


def _token_exp(token: str) -> float | None:
    """The token's own (unverified) `exp` claim, or None if absent/malformed.

    Used only to cap how long a verified result may be cached — never to
    grant trust. See `TokenVerificationCache._publish`.
    """
    payload = _decode_jwt_payload(token)
    if payload is None:
        return None
    return _valid_exp(payload)


def _authenticate_request() -> tuple[IdentityFlags | None, Any | None]:
    """Resolve the caller. Returns (flags, early_response); exactly one is None.

    Extracted from `auth_required` so the admin blueprint's `before_request` can
    reuse it verbatim rather than reimplementing token handling next door to it.
    """
    if current_app.config["TESTING"]:
        identity = _testing_identity()
        if identity is None:
            return None, (jsonify({"error": "Invalid or missing test token"}), 401)
        token = None
    else:
        token = _get_token_from_request()
        if not token:
            return None, _handle_unauthorized(_is_page_request())

        if not _is_structurally_live(token):
            logger.warning("Malformed or expired token at %s.", request.endpoint)
            return None, _handle_unauthorized(_is_page_request())

        try:

            def _verify() -> VerifiedIdentity:
                supabase = get_supabase()
                response = supabase.auth.get_user(token)
                # Robustly get the user object, which might be nested differently
                user = getattr(response, "user", None) or getattr(
                    getattr(response, "data", None), "user", None
                )
                if not user:
                    raise _ProviderResponseUnusable(request.endpoint)
                # The user id is the stable identity; email can be changed by
                # the account holder and is only a fallback for a provider
                # that omits it.
                return VerifiedIdentity(
                    user_id=str(getattr(user, "id", None) or user.email),
                    email=getattr(user, "email", None),
                    token_exp=_token_exp(token),
                )

            # Single-flight always, on every route including the console.
            # Remembering the result only off the console — see
            # `web/services/token_verification_cache.py`'s module docstring
            # for why those are two decisions and not one.
            is_console = request.blueprint == "admin"
            verified = current_app.config["token_verification"].get_or_verify(
                token, _verify, use_cache=not is_console
            )
            user_id = verified.user_id
            identity = resolve_identity_flags(
                current_app.config["identity_flags"],
                user_id,
                verified.email,
                # Console requests re-read the database rather than trusting the
                # TTL. Being thirty seconds behind a demotion is free on the
                # chat path and unacceptable on the one that can change a model
                # or disable an account. Same predicate as the token cache
                # above, deliberately read from one variable rather than
                # recomputed: two expressions meant to agree eventually will
                # not.
                fresh=is_console,
            )
        except Exception as exception:
            if _is_upstream_outage(exception):
                # Not a refusal. Log it as the outage it is, leave the session
                # intact, and let the caller retry — the credential in the
                # reader's hands is still perfectly good.
                logger.error(
                    "Identity provider unreachable at endpoint %s: %s",
                    request.endpoint,
                    exception,
                    exc_info=True,
                )
                return None, _identity_unavailable_response()

            if not _is_auth_refusal(exception):
                # A fault on our side: a missing setting, a provider response
                # in a shape we did not expect, a bug in identity resolution.
                # It still denies the request — but it says so as our failure
                # rather than blaming the reader's credential, and it leaves
                # the session alone.
                logger.exception(
                    "Unexpected failure while authenticating at endpoint %s", request.endpoint
                )
                return None, (jsonify({"error": "identity_check_failed"}), 500)

            logger.error(
                "Authentication error at endpoint %s: %s",
                request.endpoint,
                exception,
                exc_info=True,
            )
            return None, _handle_unauthorized(_is_page_request())

    _bind_session_to_identity(identity.user_id)
    session["user_email"] = identity.email
    if token is not None:
        session["supabase_access_token"] = token
    # Render hint only. Never an authorization input — see IDENTITY_MARKER_KEYS.
    session["is_admin_hint"] = identity.is_admin
    g.identity = identity

    if identity.is_disabled:
        return None, _account_disabled_response()

    return identity, None


def auth_required(view_func):
    """Decorator that enforces Supabase authentication for a route."""

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        _, early_response = _authenticate_request()
        if early_response is not None:
            return early_response
        return view_func(*args, **kwargs)

    return wrapper


# ──────────────────────────────────────────────────────────
# Durable history
# ──────────────────────────────────────────────────────────


def _durable_owner() -> str | None:
    """The verified owner id in a form the backend will accept, or None.

    None means "file nothing durably, answer anyway". Two ways to get there,
    and neither is an error worth failing a question over:

    * No identity on `g` — unreachable through the chat routes, which are both
      `@auth_required`, but this is also called from the reset route.
    * A `user_id` that is not a uuid. `_authenticate_request` falls back to
      `user.email` when a provider omits `id`, and an email cannot key a `uuid`
      column. Degrading to cache-only history is the right trade; raising would
      turn a provider quirk into an outage.

    Under TESTING the id is returned verbatim, because the bypass identities are
    `test-user-id` and friends by deliberate design and the in-memory backend
    keys on strings.
    """
    identity = getattr(g, "identity", None)
    if identity is None:
        return None
    if current_app.config["TESTING"]:
        return identity.user_id

    owner = canonical_uuid(identity.user_id)
    if owner is None:
        logger.warning(
            "Reader id is not a uuid; durable chat history is disabled for this request."
        )
    return owner


def _chat_persistence() -> Any | None:
    """The durable backend for this request, or None when there is none."""
    factory = current_app.config.get("chat_backend")
    return factory() if factory else None


def _account_rate_key() -> str:
    """Per-reader, not per-IP (docs/profile-refactor-plan.md's R4 finding: an
    office behind one NAT must not share one budget for a Data-rights action).

    Flask-Limiter's own `before_request` hook runs BEFORE this app's
    blueprint-level ones — `account_bp`'s `_gate` included — so `g.identity`
    is not set yet when this key function runs; re-authenticating here to get
    it would be a second `supabase.auth.get_user` round trip on every rate
    key evaluation, on top of the one `_gate` already makes. Hashing the
    bearer token itself gets the same per-reader isolation without that cost:
    it is unique per session and stable for the reader across requests, which
    is all a rate-limit key needs to be. No header at all falls back to IP —
    `_gate` refuses the request anyway once this function returns, so the key
    only needs to be reasonable, not exact.
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return get_remote_address()
    token = header[len("Bearer ") :].strip()
    if not token:
        return get_remote_address()
    return sha256_hex(token)


def _load_history(
    store: ConversationStore,
    backend: Any | None,
    owner_id: str | None,
    conversation_id: str,
    max_pairs: int,
    max_chars: int,
) -> list[dict[str, str]]:
    """The prompt window, hydrated from durable rows only when RAM is cold.

    The plan priced persistence at one Postgres round trip per turn. It is
    cheaper than that: a conversation already in the store costs nothing, so the
    read happens once per process per conversation — on a new device, after a
    restart, or after the store's hour of inactivity — and never on the hot path
    of an ongoing exchange.

    A failure here returns an empty window rather than propagating. The reader
    loses prior context for this one question, which is bad; refusing to answer
    because the history service is down is worse.
    """
    history = store.get(conversation_id, owner_id=owner_id)
    if history or backend is None or not owner_id:
        return history

    try:
        rows = backend.load_session(
            owner_id, conversation_id, limit=current_app.config["CHAT_HYDRATION_LIMIT"]
        )
    except PersistenceUnavailable:
        logger.warning("Could not hydrate conversation %s.", conversation_id, exc_info=True)
        return []

    if not rows:
        return []
    return store.replace(
        conversation_id,
        [{"role": row.role, "content": row.content} for row in rows],
        max_pairs,
        max_chars,
        owner_id=owner_id,
    )


def _persistable_sources(retrieved: list[dict[str, Any]], cited: list[int]) -> list[dict[str, Any]]:
    """Every RETRIEVED passage, flagged with whether the answer cited it.

    Two things are happening here and both are deliberate.

    The remap: `build_source_payload` emits `index` and has no `cited` key,
    while the columns are `source_index` and `cited`. It happens once, at the
    persistence boundary, so the stored rows and any later export cannot
    disagree about the name of the field that carries the citation contract.

    The scope: `_finalize_answer` keeps only what the answer cited and reduces
    the rest to a count. That is right for the wire — an answer ships the
    evidence it used — and wrong for the record. What search offered and the
    model declined is as informative as what it took, and it is unrecoverable
    afterwards, because retrieval is not reproducible across a corpus rebuild.
    """
    cited_indices = set(cited)
    return [
        {
            "source_index": source["index"],
            "cited": source["index"] in cited_indices,
            "document": source.get("document"),
            "page": source.get("page"),
            "category": source.get("category"),
            "score": source.get("score"),
            "semantic_score": source.get("semantic_score"),
            "lexical_score": source.get("lexical_score"),
            "chunk_id": source.get("chunk_id"),
            "snippet": source.get("snippet"),
        }
        for source in retrieved
    ]


# Three states, and only two of them are visible to a reader.
#
# `verified` means the answer was drawn from the corpus build that is active
# right now. `stale` means the corpus was rebuilt under it. `unverifiable` means
# one side or the other has no build id at all — `read_active_build_id` returns
# None for the legacy flat layout, and a message written before this shipped has
# no `corpus_revision`. Both of the latter mean the same thing to a reader (we
# cannot confirm this passage is still in the live corpus) and are kept apart
# here because they mean different things in a log and in a test.
EVIDENCE_VERIFIED = "verified"
EVIDENCE_STALE = "stale"
EVIDENCE_UNVERIFIABLE = "unverifiable"


def _evidence_state(corpus_revision: str | None) -> str:
    """What a stored answer's citations can still claim about the live corpus.

    One string comparison, deliberately. The plan for this once required a
    `chunk_sha256` over the full chunk text, which is unimplementable here — the
    payload carries a 320-char snippet and never the text — and nothing in this
    codebase resolves a `chunk_id` back to a passage anyway. Builds are immutable
    directories, so "a different build" is the only case that matters.

    Note what this is NOT used for. It does not gate whether a citation opens.
    The row it describes carries the document, page, category and snippet that
    the model actually read, frozen at write time, so opening it shows what was
    read rather than a guess about where that text lives now — a different act
    from re-resolving a `chunk_id` against a rebuilt index, which is the thing
    the fail-closed rule was written to forbid and which nothing here does. What
    the state drives is what the reader is TOLD, because a citation that quietly
    predates the current corpus is the one failure this product cannot afford.
    """
    active = current_app.config.get("CORPUS_REVISION")
    if not corpus_revision or not active:
        return EVIDENCE_UNVERIFIABLE
    return EVIDENCE_VERIFIED if corpus_revision == active else EVIDENCE_STALE


def _hydration_sources(stored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The exact inverse of `_persistable_sources`, and it must stay that way.

    The live wire ships `index` (`citations.py`), the client reads `s.index` in
    `bindCitations` and `_openPassage`, and the stored rows carry
    `source_index`. Miss this remap and every restored citation renders as a
    control that resolves to nothing — which is precisely the state hydration
    exists to end, arrived at by a different route.

    Keep this function and `_persistable_sources` adjacent and change them
    together. One projection of these rows already drifted from another once;
    that is why the write-side remap is a named function rather than a dict
    literal inside the route, and the read side gets the same treatment.
    """
    return [
        {
            "index": source.get("source_index"),
            "cited": bool(source.get("cited")),
            "document": source.get("document"),
            "page": source.get("page"),
            "category": source.get("category"),
            "score": source.get("score"),
            "semantic_score": source.get("semantic_score"),
            "lexical_score": source.get("lexical_score"),
            "chunk_id": source.get("chunk_id"),
            "snippet": source.get("snippet"),
        }
        for source in stored
    ]


def _hydration_payload(rows: list[StoredMessage]) -> list[dict[str, Any]]:
    """Stored rows as the transcript, in the shape a live answer already has.

    ONLY THE CITED PASSAGES SHIP. `_persistable_sources` stores every retrieved
    passage because what search offered and the model declined is unrecoverable
    later and is exactly the signal the archive wants. The reader's transcript is
    not that record: `_finalize_answer` ships the evidence the answer used and
    reduces the rest to a count, so hydration reproduces that or a restored
    answer grows sources it never displayed live.

    `retrieved` therefore still counts every stored row, which keeps the "N
    documents · M passages" line honest across a reload.
    """
    rows = list(rows)

    # A WINDOW MUST NOT START MID-EXCHANGE. `chat_load_session` takes the newest
    # N messages, so an odd limit slices between a question and its answer and
    # hands back an assistant row whose question is missing — an answer that
    # appears to have been given to nothing, with evidence attached. The store's
    # `replace()` already drops a leading assistant message for the prompt
    # window, on the same reasoning; the transcript deserves it at least as much,
    # because a reader can see this one.
    if rows and rows[0].role == "assistant":
        rows = rows[1:]

    payload: list[dict[str, Any]] = []
    for row in rows:
        # Only what the transcript actually renders. `message_id` and `seq` are
        # on the row and are deliberately NOT shipped: nothing on the client
        # reads them, and an unused field on a wire contract is surface that
        # drifts before it is ever tested. Phase 2's paging will want `seq` and
        # can add it with the code that uses it.
        message: dict[str, Any] = {
            "role": row.role,
            "content": row.content,
            "created_at": row.created_at,
        }
        if row.role == "assistant":
            stored = list(row.sources or [])
            cited_rows = [source for source in stored if source.get("cited")]
            message["evidence_state"] = _evidence_state(row.corpus_revision)
            message["sources"] = _hydration_sources(cited_rows)
            message["cited"] = [
                source["index"] for source in message["sources"] if source["index"] is not None
            ]
            message["retrieved"] = len(stored)
        payload.append(message)
    return payload


class _InFlightGenerations:
    """Which conversations currently have an answer being generated.

    THIS EXISTS TO CLOSE ONE RACE, and it is worth naming precisely because the
    fix looks like belt-and-braces until you read `chat_append_turn`.

    Both chat routes close over `conversation_id` before generating and write the
    turn at `final`, near the end. The sidebar's delete is a different request
    entirely. So: the reader asks a question in conversation A, deletes A while
    the answer is still streaming, and the generator's `chat_append_turn` lands
    afterwards — where it meets

        insert into public.chat_sessions (id, owner_id)
        values (p_session_id, p_owner_id)
        on conflict (id) do nothing;

    which finds no row and CREATES ONE. The conversation the reader deleted
    comes back, carrying the answer they thought they had discarded, on a
    regulatory product. There is no tombstone in that table to prevent it and
    adding one would mean a deleted-ids table that every append has to consult.

    The client refuses destructive sidebar actions while a stream is live, and
    that is the affordance. This is the guarantee: a delete or a rename that
    arrives anyway — a second tab, a replayed request, a client that skipped the
    check — is refused with 409 rather than racing.

    A plain dict under a lock is correct here because `conversation_store.py`
    already documents this app as single-worker (`--workers 1 --threads 8`), for
    reasons — FAISS and sentence-transformers in RAM — that outlive this. Should
    that ever change, this becomes per-worker and stops being a guarantee; the
    replacement is the tombstone, not a bigger dict.

    Counted rather than flagged: one reader can legitimately have two
    submissions in flight against one conversation (two tabs, or a retry), and a
    boolean would let the first to finish clear the second's protection.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, str], int] = {}

    @contextmanager
    def hold(self, owner_id: str | None, conversation_id: str | None):
        """Mark a generation live for as long as the block runs.

        A missing owner or conversation is not an error and takes no lock: an
        unidentified request has nothing durable to protect, which is the same
        reading `_durable_owner` already takes.
        """
        key = (str(owner_id), str(conversation_id)) if owner_id and conversation_id else None
        if key is not None:
            with self._lock:
                self._counts[key] = self._counts.get(key, 0) + 1
        try:
            yield
        finally:
            # In a `finally`, so a GeneratorExit from a client disconnect — the
            # ordinary way a stream ends early — releases the hold on its way
            # past. Without this a cancelled generation would lock its
            # conversation against deletion for the life of the process.
            if key is not None:
                with self._lock:
                    remaining = self._counts.get(key, 1) - 1
                    if remaining > 0:
                        self._counts[key] = remaining
                    else:
                        self._counts.pop(key, None)

    def is_live(self, owner_id: str | None, conversation_id: str | None) -> bool:
        if not owner_id or not conversation_id:
            return False
        with self._lock:
            return (str(owner_id), str(conversation_id)) in self._counts

    def is_live_for_owner(self, owner_id: str | None) -> bool:
        """Is ANY of this owner's conversations mid-generation?

        Bulk conversation deletion (docs/profile-refactor-plan.md Step 7)
        cannot name the one conversation to refuse the way the single-delete
        route does — it deletes every session in one RPC round trip, so there
        is no per-id check to run first. Refusing the whole bulk delete while
        any one of the owner's conversations is live is the same guarantee
        `is_live` gives one conversation, applied to the set: a live stream's
        `chat_append_turn` must never be able to resurrect a row this request
        just deleted.
        """
        if not owner_id:
            return False
        owner = str(owner_id)
        with self._lock:
            return any(key[0] == owner for key in self._counts)


def _generations() -> _InFlightGenerations:
    return current_app.config["generations"]


def _no_store(response: Response) -> Response:
    """Mark a response as one reader's private data.

    Every sidebar response carries conversation titles, which are the reader's
    own opening questions. On a shared machine a cached list is the previous
    reader's questions served to the next one — the same reasoning
    `/api/chat/history` already applies to the transcript, applied to the index
    of it.
    """
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _persist_turn(
    backend: Any | None,
    *,
    owner_id: str | None,
    conversation_id: str,
    client_request_id: str,
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
    lang: str,
    category: str,
    model: str,
    title: str | None = None,
    allow_create: bool = True,
) -> bool:
    """File one exchange durably. Returns False when it could not be filed.

    Never raises. The caller has already sent `final`, so the reader is looking
    at a complete, correctly cited answer; the only honest thing left to do
    about a storage failure is say so and carry on.
    """
    if not owner_id:
        # Already logged, per-request, by _durable_owner() when the reader's id
        # is not uuid-shaped. Nothing new to say here.
        return True

    if backend is None:
        # Two different reasons land here, and only one of them is silent.
        #
        # CHAT_PERSISTENCE_ENABLED off is a deployment choice — a Supabase-less
        # install, or the feature not turned on yet — and stays a quiet no-op,
        # exactly as before this branch existed.
        #
        # CHAT_PERSISTENCE_ENABLED on with backend still None means
        # get_chat_backend() could not build a client — SUPABASE_SERVICE_ROLE_KEY
        # missing or wrong, most likely. That is a live misconfiguration of a
        # feature this deployment has promised to run, and returning True here
        # would report `persisted: true` (blocking route) or send no error frame
        # at all (streaming route) while nothing was written to Postgres — the
        # exact silent-success shape this feature's own design record spends
        # several paragraphs refusing to allow elsewhere (missing archive
        # salts, a schema-less deploy defaulting the flag on). Fail the same
        # way: loud in the log, False to the caller, so the reader sees the
        # existing "could not be saved to your history" toast instead of a
        # false promise.
        if current_app.config.get("CHAT_PERSISTENCE_ENABLED", False):
            logger.error(
                "chat_persistence is enabled but no chat backend is available "
                "(conv=%s); this turn was NOT durably recorded.",
                conversation_id,
            )
            return False
        return True

    owner_key, session_key = archive_keys(owner_id, conversation_id)
    try:
        result = backend.append_turn(
            owner_id=owner_id,
            session_id=conversation_id,
            client_request_id=client_request_id,
            question=question,
            answer=answer,
            sources=sources,
            lang=lang,
            category=category,
            model=model,
            corpus_revision=current_app.config.get("CORPUS_REVISION"),
            owner_key=owner_key,
            session_key=session_key,
            # A missing salt skips the archive row and keeps the reader's own
            # history. Losing one archive row is a gap in a dataset; losing the
            # turn is losing the thing the reader is looking at.
            archive_opted_out=owner_key is None or session_key is None,
            # A CANDIDATE title, sent on every turn. The RPC applies it only when
            # the session has none, so this both names a new conversation and
            # leaves a renamed one alone — without this side needing to know
            # which case it is in, which it could only learn from a read it would
            # then be racing.
            title=title,
            # Defence in depth only — the real refusal already ran in
            # `_preflight_conversation`, before generation. See its docstring
            # and docs/per-tab-conversation-deep-linking-plan.md §3.4.
            allow_create=allow_create,
        )
    except PersistenceUnavailable:
        logger.error("Could not persist a turn (conv=%s).", conversation_id, exc_info=True)
        return False
    except Exception:
        # This function's contract is that it never raises, so it must catch
        # more than the one exception the backends promise. The blocking route
        # is why: an escape there is caught by the route's own `except
        # Exception` and answered as a 500, throwing away a complete, correctly
        # cited answer over a filing failure — the exact trade every other line
        # here refuses to make. The streaming route would merely report it late.
        logger.exception("Unexpected failure persisting a turn (conv=%s).", conversation_id)
        return False

    if result.replayed:
        # The idempotency key had already been recorded, so the database kept
        # the ORIGINAL answer and this request generated a different one. The
        # reader is looking at the new text while the stored turn holds the old.
        #
        # Not repaired here, deliberately: the answer is already on screen and
        # rewriting a durable regulatory answer to match a retry is worse than
        # the divergence. Closing it properly means checking for the replay
        # BEFORE generating, which is the reserve-shaped design §4.1 rejected.
        # Logged loudly so it is visible if it ever actually happens — the
        # browser mints a fresh id per submission, so today it should not.
        logger.warning(
            "Replayed client_request_id on conv=%s: the stored answer is the "
            "original, not the one just streamed.",
            conversation_id,
        )
    return True


def _preflight_conversation(
    persistence: Any | None, owner_id: str | None, conversation_id: str
) -> bool:
    """May this owner write into `conversation_id` right now?

    Called only for a request that named an existing conversation and said
    `allow_create: false` — the shape a `/c/<id>` deep link produces on turn 2
    onward. A stale or foreign id is refused HERE, before a token is
    generated, rather than discovered after the answer has already streamed:
    verified against the actual ordering (`yield sse("final")` precedes
    `store.append_turn`, which precedes `_persist_turn`), a stale-tab send
    against a deleted conversation would otherwise pay for a full generation,
    write the turn into the in-RAM prompt window unconditionally, and only
    THEN fail to persist — leaving the reader a complete answer for a
    conversation that no longer exists.
    See docs/per-tab-conversation-deep-linking-plan.md §3.4.

    An outage answers True — fails open, the same posture `_durable_owner`
    takes: refusing a legitimate question because the existence check itself
    could not be reached would be a worse failure than the resurrection this
    guards against, which `chat_append_turn`'s own `p_allow_create` still
    refuses at the database regardless.
    """
    if persistence is None or not owner_id:
        return True
    try:
        return persistence.session_exists(owner_id, conversation_id)
    except PersistenceUnavailable:
        logger.warning(
            "Could not preflight conversation %s; proceeding without the check.",
            conversation_id,
            exc_info=True,
        )
        return True


def _retrieve_for_prompt(
    engine: ImprovedSearchEngine,
    query: str,
    category: str,
    handler: OpenAIHandler,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Search once, and return the two shapes a chat request needs from it.

    `llm_context` is what the model is shown; `retrieved` is what the API can
    cite back. They come from ONE search call and are cut to the SAME limit on
    purpose: the citation scheme is positional, so prompt block [i] and
    retrieved[i] must be the same passage or a marker resolves to the wrong
    document. Both routes built this pair independently — the invariant is
    easier to hold in one place than to restate correctly in two.
    """
    results = engine.search(query, category)
    llm_context = [
        {"text": r.text, "document": r.document, "category": r.category, "page": r.page}
        for r in results
    ]
    return llm_context, build_source_payload(results, limit=handler.max_context_results)


def _finalize_answer(
    answer: str, retrieved: list[dict[str, Any]]
) -> tuple[str, list[int], list[dict[str, Any]]]:
    """Normalize the answer's citations, then keep only the passages it cited.

    `sources` is strictly what the answer cited and nothing else, so an answer
    that cited nothing ships an empty list and no source control renders at
    all. Both routes must agree on that, which is the argument for them sharing
    the three lines rather than each keeping a copy.
    """
    answer = normalize_legacy_citations(answer, retrieved)
    cited = extract_cited_indices(answer, retrieved)
    return answer, cited, [s for s in retrieved if s["index"] in cited]


# ──────────────────────────────────────────────────────────
# Flask Application Factory Components
# ──────────────────────────────────────────────────────────
def _warn_if_archive_is_undisclosed(app: Flask) -> bool:
    """Refuse to let the archive start collecting text nobody was told about.

    Step 7 shipped a durable-history notice and CUT the archive's controls — the
    opt-out toggle, the withdrawal column, the purge RPC, the retention CLI, the
    export. That was correct precisely because the archive is dormant: both
    salts are unset, `archive_keys()` returns ``(None, None)``, and
    `chat_append_turn` skips every archive insert. Controls for a collection
    process that is not collecting are worse than absent, because a toggle
    reading "Research archive: ON" asserts something false.

    But that reasoning has an expiry date, and it is the moment somebody sets a
    salt. At that instant the archive begins keeping question and answer text
    that the notice does not mention and the reader cannot opt out of — because
    the opt-out was cut on the grounds that there was nothing to opt out of.

    Left as a line in a design document, "revisit this before enabling the
    archive" is a promise. This is the mechanism instead: one loud error at
    startup, in the same loud-but-once shape as the missing-salt warning in
    `chat_store.archive_keys` and the missing-key warning in
    `SupabaseAdminClient`. It does not stop the process — a deployment that has
    genuinely decided to collect should not be held hostage by a config flag —
    but it makes the decision impossible to take by accident.

    Returns True when the mismatch is present, so a test can assert on the
    condition rather than on log plumbing.
    """
    salts_set = bool(os.getenv("ARCHIVE_OWNER_SALT")) or bool(os.getenv("ARCHIVE_SESSION_SALT"))
    if not salts_set or app.config.get("ARCHIVE_DISCLOSED", False):
        return False

    logger.error(
        "ARCHIVE_OWNER_SALT/ARCHIVE_SESSION_SALT is set while "
        "server.archive_disclosed is false. The research archive will begin "
        "keeping question and answer text that the reader-facing notice does "
        "not mention, and whose opt-out, purge and export paths were "
        "deliberately not built while the archive was dormant. Either unset "
        "the salts, or disclose the archive and restore its controls before "
        "collecting. See TODO.md, 'Save chat sessions per user'."
    )
    return True


def _configure_app(app: Flask, testing: bool) -> None:
    """Apply basic configuration and secret key to the Flask app."""
    app.secret_key = config.flask_secret_key or os.urandom(24)
    if not config.flask_secret_key and not testing:
        logger.warning("Using a temporary secret key. Set FLASK_SECRET_KEY in .env for production.")

    app.config.update(
        TESTING=testing,
        RATELIMIT_ENABLED=not testing,
        MAX_CHAT_HISTORY_MESSAGE_PAIRS=config.get(
            "server", "chat_history_length", DEFAULT_MAX_CHAT_MESSAGES_COUNT
        ),
        # Configurable because the constant it replaced was the one history
        # bound config.yaml could not see, and it silently overrode the one it
        # could: `chat_history_length: 10` never took effect, because a budget
        # narrower than a single exchange decided every conversation first.
        MAX_CHAT_HISTORY_CHARS=config.get(
            "server", "chat_history_char_budget", DEFAULT_CHAT_HISTORY_CHAR_BUDGET
        ),
        # A deploy switch, not a test switch. Off means chat still answers from
        # the in-RAM window exactly as it did before durable history existed —
        # which is what a deployment without a service-role key gets anyway.
        #
        # DEFAULT OFF UNTIL THE MIGRATION IS APPLIED, and the ordering is the
        # whole reason a bare code deploy without the schema would answer
        # "function does not exist" on every RPC call — a persistence_unavailable
        # frame and a "could not be saved to your history" toast under EVERY
        # answer the assistant gives. A feature defaulting on before its schema
        # exists is a feature that ships as a visible error.
        #
        # Applied 2026-08-20: supabase/migrations/20260820131914_chat_session_
        # persistence.sql is live (`list_migrations` confirms it), so
        # config.yaml now defaults this on. Turns are recorded and hydrated
        # from the URL the client names (docs/per-tab-conversation-deep-
        # linking-plan.md) — there is no separate "resume my last
        # conversation" fallback any more; see §1 and §5.5 for why the
        # cookie-keyed pointer this used to gate is gone rather than merely
        # turned off.
        CHAT_PERSISTENCE_ENABLED=config.get("server", "chat_persistence", False),
        # How much of a stored conversation comes back on hydration. Bounded
        # because an unbounded restore meets citations.js's 100-answer tracking
        # cap and drops the citation controls off the oldest answers without
        # saying so — on the product whose central claim is resolvable sources.
        CHAT_HYDRATION_LIMIT=config.get("server", "chat_hydration_limit", 50),
        # Whether the reader-facing notice mentions the research archive. False
        # today because the archive collects nothing — see
        # `_warn_if_archive_is_undisclosed`, which is what stops that pairing
        # from silently becoming untrue.
        ARCHIVE_DISCLOSED=config.get("server", "archive_disclosed", False),
    )
    if testing:
        app.config.update(SERVER_NAME="localhost")


def _init_extensions(app: Flask, testing: bool) -> Limiter:
    """Initialize all Flask extensions."""
    # Check if running behind a reverse proxy (e.g., Nginx with SSL termination)
    is_behind_proxy = config.is_behind_proxy()

    # Apply ProxyFix middleware when behind a reverse proxy
    # This trusts X-Forwarded-* headers from Nginx
    if is_behind_proxy:
        # Flask/Werkzeug's own documented way to install WSGI middleware — mypy
        # sees `wsgi_app` as a bound method, not the instance attribute Flask
        # actually treats it as.
        app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
            app.wsgi_app,
            x_for=1,  # Trust X-Forwarded-For (1 proxy hop)
            x_proto=1,  # Trust X-Forwarded-Proto
            x_host=1,  # Trust X-Forwarded-Host
            x_prefix=1,  # Trust X-Forwarded-Prefix
        )
        logger.info("ProxyFix middleware enabled for reverse proxy deployment.")

    # CORS
    is_debug_mode = config.is_debug() or testing
    if is_debug_mode:
        CORS(app, supports_credentials=True)
        logger.info("CORS initialized in debug mode (all origins allowed).")
    else:
        origins = config.get("server", "allowed_origins", [])
        CORS(app, origins=origins, supports_credentials=True)
        logger.info("CORS initialized for specific origins: %s", origins)

    # Talisman (Security Headers)
    # Build connect-src list for Supabase
    connect_src = [
        "'self'",
        "https://*.supabase.co",
        "https://cdn.lordicon.com",
        "https://cdn.jsdelivr.net",
    ]

    # Add WebSocket support for Supabase Realtime
    if project_ref := config.get_secret("SUPABASE_PROJECT_REF"):
        connect_src.append(f"wss://{project_ref}.supabase.co")
    connect_src.append("wss://*.supabase.co")  # Allow all Supabase WebSocket connections

    # Dev-only allowance for the Impeccable live-mode helper, which serves its
    # picker script and an SSE channel from http://localhost:8400. It needs both
    # script-src (to load) and connect-src (to poll).
    #
    # This CANNOT reach production: is_debug_mode is `config.is_debug() or testing`
    # (see above), so a deployed app with debug:false and testing off gets an empty
    # list and an unchanged policy. Note the origin is http, not https — the
    # permissive debug connect-src below allows `https:` and `wss:` only, so the
    # allowance has to be appended there too rather than being covered by it.
    impeccable_live_dev = ["http://localhost:8400"] if is_debug_mode else []

    csp = {
        "default-src": ["'self'"],
        "script-src": [
            "'self'",
            "'unsafe-inline'",
            "https://cdn.jsdelivr.net",
            "https://cdn.lordicon.com",
            "https://cdnjs.cloudflare.com",
            *impeccable_live_dev,
        ],
        "style-src": [
            "'self'",
            "'unsafe-inline'",
            "https://cdn.jsdelivr.net",
            "https://cdnjs.cloudflare.com",
            "https://fonts.googleapis.com",
        ],
        # No external image is loaded anywhere: favicons are same-origin, every
        # icon is inline SVG (web/utils/icons.py), and Bootstrap's control art is
        # data: URIs. The wildcard mattered because model output renders through a
        # DOMPurify profile that permits <img> (stream-render.js:24), which made a
        # markdown image in an answer an outbound beacon.
        "img-src": ["'self'", "data:"],
        "font-src": [
            "'self'",
            "https://cdn.jsdelivr.net",
            "https://cdnjs.cloudflare.com",
            "data:",
            "https://fonts.gstatic.com",
            "https://r2cdn.perplexity.ai",
        ],
        "connect-src": connect_src + impeccable_live_dev,
    }

    # In debug mode, be more permissive for development (allows browser extensions)
    if is_debug_mode:
        # Allow fonts from any HTTPS source (for browser extensions like Perplexity)
        csp["font-src"] = ["'self'", "https:", "data:"]
        # Allow connections to any HTTPS/WSS (for development and browser extensions)
        csp["connect-src"] = ["'self'", "https:", "wss:", *impeccable_live_dev]
        logger.info("CSP configured in permissive debug mode for development")

    # Disable force_https when:
    # 1. Debug mode (local development)
    # 2. Testing mode
    # 3. Behind a reverse proxy (Nginx handles SSL termination)
    should_force_https = not (is_debug_mode or testing or is_behind_proxy)

    Talisman(
        app,
        force_https=should_force_https,
        content_security_policy=csp,
        # Both of these already matched Talisman's own defaults and were
        # therefore silently inherited rather than stated — pinned explicitly
        # so a future flask-talisman upgrade, or a config refactor that drops
        # this call's defaults, cannot regress either one without the change
        # being visible here. See
        # docs/per-tab-conversation-deep-linking-plan.md §6.1 and §3.5.
        referrer_policy="strict-origin-when-cross-origin",
        session_cookie_samesite="Lax",
    )
    logger.info(
        "Talisman initialized. force_https=%s (debug=%s, testing=%s, behind_proxy=%s)",
        should_force_https,
        is_debug_mode,
        testing,
        is_behind_proxy,
    )

    # Rate Limiter
    rate_limit_config = config.get("server", "rate_limit", {})
    default_limits: list[str | Callable[[], str]] = [
        f"{rate_limit_config.get('per_day', 200)} per day",
        f"{rate_limit_config.get('per_hour', 50)} per hour",
        f"{rate_limit_config.get('per_minute', 10)} per minute",
    ]
    limiter = Limiter(
        get_remote_address,
        app=app,
        # flask_limiter's own stub types default_limits as list[... | Limit] —
        # a plain list of our str/Callable entries is a valid runtime value,
        # just not a subtype of that under list's invariance.
        default_limits=cast("list[Any]", default_limits),
        storage_uri="memory://",
    )
    logger.info("Flask-Limiter initialized with limits: %s", default_limits)
    return limiter


def _register_testing_doubles(app: Flask) -> None:
    """Wire up mock search and LLM services.

    These return real objects rather than bare MagicMocks, so ``?testing=true``
    is a working demo of the full pipeline — streaming, sources and citations —
    without an OpenAI key or a built index. Tests override the return values
    they care about.
    """
    from unittest.mock import MagicMock

    # max_context_results is assigned in OpenAIHandler.__init__, so spec= alone
    # does not expose it and any access raises AttributeError.
    handler = MagicMock(spec=OpenAIHandler)
    handler.max_context_results = config.get("openai", "max_context_results", 8)
    handler.model = config.get("openai", "model", "gpt-4o-mini")

    def build_testing_handler(settings=None):
        """The factory the settings swap uses under TESTING.

        A model change must be exercisable without an OpenAI key, and replacing
        the double with a real OpenAIHandler would break every test that leans
        on it. So the swap builds another double carrying the requested values —
        the mechanism under test is the atomic rebind, not what the handler
        talks to.
        """
        settings = settings or {}
        replacement = MagicMock(spec=OpenAIHandler)
        replacement.max_context_results = settings.get(
            "max_context_results", handler.max_context_results
        )
        replacement.model = settings.get("model", handler.model)
        replacement.max_tokens = settings.get("max_tokens")
        replacement.temperature = settings.get("temperature")
        replacement.tokenizer_exact = True
        # Carry the demo behaviour across, or a model switch would leave the
        # ?testing=true console answering with bare MagicMocks.
        replacement.stream_response.side_effect = handler.stream_response.side_effect
        replacement.generate_response.return_value = handler.generate_response.return_value
        replacement.generate_suggestions.return_value = handler.generate_suggestions.return_value
        return replacement

    app.config["openai_handler_factory"] = build_testing_handler

    demo_answer = (
        "Applications for drug registration must be submitted through the SFDA electronic "
        "portal [1]. The dossier follows the **eCTD** structure, and the manufacturing site "
        "must hold a valid GMP certificate issued by a recognised authority [2].\n\n"
        "| Stage | Timeline |\n| --- | --- |\n| Screening | 20 working days |\n"
        "| Scientific review | 180 working days |\n\n"
        "Marketing authorisation holders must additionally nominate a qualified person "
        "resident in the Kingdom [3]. Variations to an approved registration follow the "
        "same electronic route [4]."
    )

    def fake_stream(*_args, **_kwargs):
        # Chunked on word boundaries to exercise the incremental renderer the
        # way a real model would.
        import re as _re

        yield from _re.findall(r"\S+\s*", demo_answer)

    demo_suggestions = ["What documents are required?", "How long does review take?"]

    # stream_response needs side_effect because each call must yield a fresh
    # generator. The other two use return_value so a test can simply assign
    # its own return_value — side_effect would take precedence and silently
    # ignore it.
    handler.stream_response.side_effect = fake_stream
    handler.generate_response.return_value = (demo_answer, demo_suggestions)
    handler.generate_suggestions.return_value = demo_suggestions

    # Entries 1 and 4 share a document deliberately: the panel groups passages
    # under their file, and a demo where every passage came from a different
    # document would never show that. The scores are illustrative — if a
    # relevance floor is ever configured above 0.34, revisit them, or the demo
    # will show passages production would have dropped.
    documents = [
        ("2022-10-19_Guidance_for_Submission.pdf", 14, "regulatory", 0.71, 0.63, 0.80),
        ("2021-03-02_GMP_Requirements.pdf", 7, "regulatory", 0.52, 0.59, 0.41),
        ("2023-01-11_Pharmacovigilance_Guideline.pdf", 31, "pharmacovigilance", 0.34, 0.30, 0.37),
        ("2022-10-19_Guidance_for_Submission.pdf", 61, "regulatory", 0.48, 0.44, 0.51),
    ]
    demo_results = [
        SearchResult(
            text=(
                f"Extract from {name}: registration dossiers shall be submitted electronically "
                "and reviewed against the applicable SFDA guidance in force at the time of filing."
            ),
            score=score,
            document=name,
            category=category,
            page=page,
            chunk_id=f"{name}_p{page}_1",
            metadata={"semantic_score": semantic, "lexical_score": lexical},
        )
        for name, page, category, score, semantic, lexical in documents
    ]

    search_engine = MagicMock(spec=ImprovedSearchEngine, is_initialized=lambda: True)
    search_engine.search.return_value = demo_results

    # A real string, not the MagicMock a spec'd attribute would otherwise hand
    # back. `CORPUS_REVISION` is read from here and stamped onto every stored
    # answer, then compared on hydration — so an opaque object would make the
    # comparison pass for the wrong reason and prove nothing about the states
    # a reader is actually shown.
    search_engine.active_build_id = "test-build-0001"

    app.config["openai_handler"] = handler
    app.config["search_engine"] = search_engine
    logger.info("Mock services registered for testing.")


def _initialize_services(app: Flask, testing: bool) -> None:
    """Attach search engine and LLM handlers to the app config."""
    if testing:
        _register_testing_doubles(app)
        return

    app.config["openai_handler_factory"] = OpenAIHandler
    app.config["openai_handler"] = OpenAIHandler()
    try:
        search_engine = ImprovedSearchEngine()
        app.config["search_engine"] = search_engine
        if not search_engine.is_initialized():
            initialized = search_engine.initialize()
            if initialized:
                logger.info("Search engine initialized successfully.")
            else:
                logger.error(
                    "Search engine failed to initialize — chat requests will "
                    "return 503 until this is fixed. See the error logged "
                    "above from SearchEngine for the underlying cause."
                )
    except ManifestValidationError as exc:
        # The active search index's build manifest does not match the
        # embedding model/dimension the app is currently configured to use
        # (see SearchIndex._validate_manifest). Loading it anyway would
        # silently serve search results computed in the wrong vector space —
        # a stale or mismatched index must never degrade quietly, so this is
        # deliberately re-raised to crash application startup instead of
        # being caught by the broad `except Exception` below.
        logger.critical(
            "FATAL: search index manifest validation failed — refusing to "
            "start with a mismatched index. %s",
            exc,
        )
        raise
    except Exception as e:
        app.config["search_engine"] = None
        logger.error("Search engine initialization failed: %s", e, exc_info=True)


def _load_faq_data() -> dict[str, Any]:
    """Load FAQ data from YAML, keyed by language.

    Accepts both the language-keyed shape ({en: {...}, ar: {...}}) and the
    older flat shape, so the file can be rolled back without a code change.
    Always returns {lang: {category: {...}}}.
    """
    faq_path = PROJECT_ROOT / "faq.yaml"
    try:
        with faq_path.open("r", encoding="utf-8") as f:
            faq_data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("faq.yaml not found. FAQ feature will be disabled.")
        return {}
    except Exception as e:
        logger.error("Error parsing faq.yaml: %s", e)
        return {}

    if not set(faq_data) & set(SUPPORTED_FAQ_LANGS):
        logger.info("faq.yaml is in the legacy flat shape; treating it as English.")
        faq_data = {"en": faq_data}

    logger.info("FAQ data loaded for %s.", ", ".join(sorted(faq_data)) or "no languages")
    return faq_data


def _register_routes(app: Flask, limiter: Limiter) -> None:
    """Register all application routes and blueprints."""
    app.config["FREQUENT_QUESTIONS"] = _load_faq_data()
    app.config["conversations"] = ConversationStore()
    # Which conversations have an answer in flight right now. Process-local like
    # the store above, and correct for the same documented reason: one worker.
    # See the class for the race it closes.
    app.config["generations"] = _InFlightGenerations()
    # Process-local, same scope contract as ConversationStore above: a cache,
    # never the authority. The database decides who is an administrator.
    app.config["identity_flags"] = IdentityFlagsCache()
    # A SECOND, separate cache — see token_verification_cache's module
    # docstring for why merging it into the one above is not possible in the
    # direction that matters (this one is keyed by token digest, that one by
    # user id). `ttl_seconds` defaults to 0 — single-flight only, nothing
    # remembered. Raising it is the deliberate revocation-window trade
    # described in docs/archive/2026-08-27_token-verification-cache.md §1.4, and it must not be
    # done without the measurement that section requires.
    #
    # `wait_timeout_seconds` is derived from the SAME auth timeout the actual
    # GoTrue call runs under, rather than a second, independently chosen
    # number — a hardcoded literal here would silently drift from
    # `SUPABASE_AUTH_TIMEOUT` the moment someone changed that env var without
    # knowing this constant existed, turning a legitimate slow-but-successful
    # verification into a false 503 for every waiter.
    # `or 5.0` would be a falsy-zero bug here: `SUPABASE_AUTH_TIMEOUT=0` is a
    # degenerate config elsewhere (every GoTrue call would time out
    # instantly), but this specific line still owes it the actual configured
    # value rather than silently substituting a default — that substitution
    # is exactly the "drift" the comment above says this derivation exists to
    # prevent. `.read` is never `None` for a `Timeout` built the way
    # `_auth_timeout()` builds it (a single positional value sets every leg);
    # the `is None` check is defensive, not expected to trigger.
    _configured_read_timeout = _auth_timeout().read
    _auth_read_timeout = 5.0 if _configured_read_timeout is None else _configured_read_timeout
    app.config["token_verification"] = TokenVerificationCache(
        ttl_seconds=config.get("server", "auth_token_cache", {}).get("ttl_seconds", 0),
        wait_timeout_seconds=_auth_read_timeout + 0.5,
    )

    # One in-memory backend per process under TESTING, so a setting changed by
    # a request is visible to the next one within the same test — and nothing
    # survives the process, which is what makes tests independent.
    app.config["_testing_admin_backend"] = InMemoryAdminBackend()
    app.config["_testing_chat_backend"] = InMemoryChatBackend()
    # Shares the SAME _users list as _testing_admin_backend (not a copy) —
    # see InMemoryNotificationBackend's own docstring: a role/tier targeting
    # decision made here must agree with whatever the admin console fixtures
    # say, including after a test disables or promotes a seeded user.
    app.config["_testing_notification_backend"] = InMemoryNotificationBackend(
        users=app.config["_testing_admin_backend"]._users
    )

    # Resolved ONCE per process, not per turn, and taken FROM THE ENGINE rather
    # than from `active_build.txt`.
    #
    # This is what a stored citation is compared against on hydration: equal
    # means the answer came from the corpus now being served, different means
    # the corpus was rebuilt under it. It does not decide whether the passage
    # opens — the stored row holds the document, page and snippet frozen at
    # write time, so opening it shows what the model actually read. It decides
    # what the reader is TOLD. (An earlier draft made `stale` unopenable; that
    # was reversed, because one rebuild would then deaden every citation in
    # every stored conversation at once, and an answer stripped of its controls
    # is indistinguishable from one that cited nothing.)
    #
    # Reading the POINTER instead of the engine was a real hazard: the engine
    # initialises before this line runs, so an activation in between records a
    # revision the passages did not come from — and a dangling pointer is kept
    # verbatim by `read_active_build_id` while the engine silently falls back to
    # the legacy flat corpus. Either way a stored answer would later compare
    # equal and render as current evidence when it is not. `active_build_id` is
    # what was loaded, and it is `None` for the legacy layout, which resolves as
    # "unverifiable" — never as "verified".
    engine_for_revision = app.config.get("search_engine")
    app.config["CORPUS_REVISION"] = getattr(engine_for_revision, "active_build_id", None)

    _warn_if_archive_is_undisclosed(app)

    def chat_backend():
        """Durable chat history, or None when this deployment has no database.

        UNDER TESTING PERSISTENCE IS ON, backed by the in-memory double. A
        feature flag that turned it off in tests would mean none of the
        behaviour below — hydration, the current-session rule, idempotent
        replay, owner isolation on the durable path — was ever exercised, and
        those are precisely the parts that cannot be reasoned about by reading.

        `CHAT_PERSISTENCE_ENABLED` is a deploy switch for a Supabase-less
        deployment, not a test switch.
        """
        if app.config["TESTING"]:
            return app.config["_testing_chat_backend"]
        if not app.config.get("CHAT_PERSISTENCE_ENABLED", False):
            return None
        return get_chat_backend()

    app.config["chat_backend"] = chat_backend

    def admin_backend():
        """Resolved per call, never at startup.

        `get_admin_backend()` builds a Supabase client, and doing that here
        would put a network dependency in front of a process whose search index
        takes minutes to load — for a surface most deployments never open.
        """
        if app.config["TESTING"]:
            return app.config["_testing_admin_backend"]
        return get_admin_backend()

    app.config["admin_backend"] = admin_backend
    app.config["settings_service"] = SettingsService(admin_backend)

    def notification_backend():
        """Resolved per call, same reasoning as admin_backend above."""
        if app.config["TESTING"]:
            return app.config["_testing_notification_backend"]
        return get_notification_backend()

    app.config["notification_backend"] = notification_backend

    # Recovery mail, for the reader's forgot-password and the console's send-reset
    # alike. Same shape as `admin_backend` above and for the same reason: built
    # per call, not at startup, so a process whose index takes minutes to load
    # does not also wait on a network client for a path most requests never take.
    app.config["_testing_recovery_dispatcher"] = InMemoryRecoveryDispatcher()

    def recovery_dispatcher():
        if app.config["TESTING"]:
            return app.config["_testing_recovery_dispatcher"]
        return get_recovery_dispatcher()

    app.config["recovery_dispatcher"] = recovery_dispatcher

    # Session revocation and email change, both through Supabase Auth Admin.
    # Same per-call resolution shape as the two dispatchers above, and for the
    # same reason. The in-memory dispatcher is built with a *reference* to the
    # same list the in-memory admin backend mutates, so a demo "change email"
    # is visible on the very next account reload — see auth_admin.py's
    # InMemoryAuthAdminDispatcher docstring for why that wiring matters.
    app.config["_testing_auth_admin_dispatcher"] = InMemoryAuthAdminDispatcher(
        users=app.config["_testing_admin_backend"]._users
    )

    def auth_admin_dispatcher():
        if app.config["TESTING"]:
            return app.config["_testing_auth_admin_dispatcher"]
        return get_auth_admin_dispatcher()

    app.config["auth_admin_dispatcher"] = auth_admin_dispatcher

    # Said once at startup rather than discovered at the first reset attempt.
    #
    # `POST /auth/recover` answers a generic 202 whatever happens, deliberately —
    # a misconfiguration must not be distinguishable from an unknown address, or
    # the endpoint becomes an account-enumeration oracle. The cost of that choice
    # is that a missing PUBLIC_BASE_URL is invisible from the outside: the reader
    # is told a link is on its way and no link is ever sent. The operator's
    # channel is this log, and waiting until someone is already locked out to
    # write to it is too late.
    if not app.config.get("TESTING"):
        try:
            landing = recovery_redirect_url()
        except RecoveryRefused as refusal:
            logger.error(
                "PUBLIC_BASE_URL is not usable (%s); password recovery is DISABLED. "
                "Every reset request will answer 202 and send nothing. Set it to a "
                "bare origin (scheme + host + port) that is also on Supabase's "
                "redirect allow-list.",
                refusal.code,
            )
        else:
            # A recovery link that resolves to a port nothing is serving is the
            # most likely way this goes wrong, and it is invisible from both ends:
            # the send succeeds, the mail arrives, and the reader lands on a
            # connection error. The port here has to track `server.port`, which
            # comes from config.yaml and not from the PORT environment variable.
            served_port = str(config.get("server", "port", 5001))
            link_port = urlparse(landing).port
            if link_port is not None and str(link_port) != served_port:
                logger.warning(
                    "PUBLIC_BASE_URL points at port %s but this app serves on %s. "
                    "Recovery mail will be sent with a link nobody is listening on.",
                    link_port,
                    served_port,
                )

    def apply_generation_settings() -> bool:
        """Rebuild the OpenAI handler from current settings and swap it in.

        **Replacement, not mutation.** A handler is either wholly the old one or
        wholly the new one: the model, the token ceiling, the temperature and
        the tokenizer are established together in the constructor, and each
        request captures one reference at the top of its view and keeps it for
        its lifetime. So a request that is already streaming finishes on the
        handler it started with, and the next one gets the new handler — there
        is no moment at which any thread can observe a half-applied change.

        That property is why nothing in the request path needed changing for
        this feature. `handle_chat_stream` captures `handler` once and its
        generator closes over that local; the blocking route does the same.

        Returns False and leaves the running handler in place if construction
        fails — a bad setting must not be able to take the chatbot down. The
        caller reports that; it does not raise.
        """
        settings = app.config["settings_service"].snapshot()
        factory = app.config.get("openai_handler_factory")
        if factory is None:
            return False

        try:
            replacement = factory(settings)
        except Exception:
            logger.error(
                "Could not build an OpenAI handler from the stored settings; "
                "keeping the running one. Settings: %r",
                settings,
                exc_info=True,
            )
            return False

        # The whole swap: one attribute rebind, atomic under the GIL.
        app.config["openai_handler"] = replacement
        logger.info(
            "Generation settings applied: model=%s max_tokens=%s temperature=%s passages=%s",
            settings.get("model"),
            settings.get("max_tokens"),
            settings.get("temperature"),
            settings.get("max_context_results"),
        )
        return True

    app.config["apply_generation_settings"] = apply_generation_settings

    # Adopt any stored overrides at startup, so a model chosen in the console
    # survives a restart. Deliberately best-effort and after the handler already
    # exists: a settings-store outage during boot leaves the deployed defaults
    # running rather than preventing the app from serving at all.
    #
    # UNCONDITIONAL, and that is the point of it. Gating this on `overrides()`
    # being non-empty meant the only model a boot ever printed was the one from
    # the throwaway handler `_initialize_services` builds — "OpenAIHandler
    # initialized with model: gpt-4o-mini" — which is the deployed default
    # whatever the console shows, and is discarded seconds later on any instance
    # that has overrides. An operator reading the terminal had no way to tell
    # which of the two handlers was live. Applying always makes "Generation
    # settings applied" the single line that states what this process will
    # actually generate with, and it costs nothing when nothing is overridden
    # because `snapshot()` is then exactly the deployed defaults.
    try:
        stored = app.config["settings_service"].read_overrides()
    except Exception:
        # Said here rather than left to be inferred. `snapshot()` is lenient and
        # serves the deployed defaults when the store cannot be read — correct,
        # because a settings outage must not cost a reader their answer, but it
        # means this process will generate with defaults while /admin/api/settings
        # reports whatever is stored the moment the store comes back. Nothing
        # reconciles the two until the next save or restart, so the disagreement
        # has to be announced at the point it is created.
        logger.error(
            "The settings store could not be read at startup, so generation is "
            "running the DEPLOYED DEFAULTS from config.yaml. The console will "
            "show the stored overrides once the store recovers; the two will "
            "disagree until a save or a restart.",
            exc_info=True,
        )
    else:
        if stored:
            logger.info("Adopting stored settings overrides: %s", sorted(stored))

    apply_generation_settings()
    app.register_blueprint(auth_bp, url_prefix="/auth")
    # Recovery triggers an email from an unauthenticated endpoint, which is the
    # one shape on this origin that a script can turn into someone else's inbox
    # problem. GoTrue enforces its own ceilings behind this (60s per address,
    # 30/hour per project) — this limit is about not letting a caller burn the
    # project's whole allowance before GoTrue's per-address limiter even applies.
    app.register_blueprint(recover_bp, url_prefix="/auth")
    limiter.limit(
        lambda: config.get("server", "rate_limit", {}).get("recover_api", "5 per minute"),
    )(recover_bp)
    # Signup, server-mediated as of the registrations-pause work
    # (docs/registrations-pause-plan.md) — it used to live on `auth_bp` and
    # inherit no limit at all. Same reasoning as recover_api above: it is an
    # unauthenticated endpoint that sends mail, sitting in front of GoTrue's
    # own project-wide ceiling rather than replacing it.
    app.register_blueprint(signup_bp, url_prefix="/auth")
    limiter.limit(
        lambda: config.get("server", "rate_limit", {}).get("signup_api", "5 per minute"),
    )(signup_bp)
    # Imported here rather than at module scope: admin.py imports back into this
    # module for `_authenticate_request`, and a top-level import would be a cycle.
    from web.api.admin import admin_bp

    app.register_blueprint(admin_bp)
    # The console is chrome and a handful of JSON reads, but the global default
    # of 200/day would lock an operator out of their own instance after an
    # afternoon of refreshes. Exempting it entirely would let a loop hammer the
    # database instead.
    limiter.limit("60 per minute")(admin_bp)
    # These two can each end a reader's sessions or redirect their identity,
    # not merely change a flag — the blueprint's 60/minute is sized for an
    # operator's ordinary console use, not for what one compromised admin
    # token could do to many accounts through these two routes specifically.
    # Applied by endpoint name rather than at definition time in admin.py:
    # the limiter object does not exist yet when that module is imported.
    limiter.limit("10 per minute")(app.view_functions["admin.revoke_sessions"])
    limiter.limit("10 per minute")(app.view_functions["admin.change_email"])
    # Keyed per-administrator (admin.py's own _admin_notification_rate_key),
    # not per-IP or the blueprint's blanket 60/minute: a broadcast fans a
    # message out to every targeted reader at once, and the default IP key
    # would let a compromised admin account spam via multiple IPs or let
    # several admins behind one office NAT share one budget.
    from web.api.admin import _admin_notification_rate_key

    limiter.limit(
        lambda: config.get("server", "rate_limit", {}).get(
            "notification_broadcast_api", "10 per hour"
        ),
        key_func=_admin_notification_rate_key,
    )(app.view_functions["admin.create_notification"])

    # Imported here for the same reason admin_bp is: account.py imports back
    # into this module for _authenticate_request, and a top-level import
    # would be a cycle.
    from web.api.account import account_bp

    app.register_blueprint(account_bp)
    # Chrome and a profile read today; Step 5/7 add mutating routes here
    # later, each rate-limited on its own terms per docs/profile-refactor-
    # plan.md §4 ("email change 3/hr, password change 5/hr, export 2/10min,
    # deletion 3/hr"). This blanket limit is the same reasoning as the
    # console's: the global 200/day default would lock a reader out of their
    # own record after an afternoon of visits.
    limiter.limit("60 per minute")(account_bp)
    # Data rights (Step 7). Both stack on top of the blanket 60/minute above,
    # the same composition admin.py's revoke_sessions/change_email already
    # use — the specific limit is the one that actually binds. Keyed per
    # reader rather than per IP (_account_rate_key's own docstring: R4).
    limiter.limit(
        lambda: config.get("server", "rate_limit", {}).get("export_api", "2 per 10 minutes"),
        key_func=_account_rate_key,
    )(app.view_functions["account.export"])
    # A destructive, irreversible action on the reader's own history — tighter
    # than the ordinary sidebar single-delete (sessions_api, 60/minute), but
    # not as tight as export: it costs one RPC round trip, not a full scan
    # and stream of every stored message.
    limiter.limit(
        lambda: config.get("server", "rate_limit", {}).get(
            "account_bulk_delete_api", "10 per hour"
        ),
        key_func=_account_rate_key,
    )(app.view_functions["account.delete_all_conversations"])

    workers = os.getenv("WEB_CONCURRENCY", "1")
    if workers != "1":
        logger.warning(
            "WEB_CONCURRENCY=%s but ConversationStore, IdentityFlagsCache and "
            "TokenVerificationCache are all process-local — conversations will split "
            "across workers, users will randomly lose context, and an admin "
            "invalidation (disable, demote, revoke sessions) will only take effect on "
            "the worker that served it, leaving the others serving stale or revoked "
            "credentials for their full TTL. This app must run single-worker anyway "
            "(in-RAM FAISS index); use --workers 1 --threads 8.",
            workers,
        )

    @app.context_processor
    def inject_template_globals() -> dict[str, Any]:
        # `icon` and `category_icon` are globals rather than a Jinja import so
        # partials get them without every caller remembering `with context`.
        return {
            "asset_version": ASSET_VERSION,
            "app_version": APP_VERSION,
            "icon": icon,
            "category_icon": lambda key: CATEGORY_ICONS.get(key, "globe"),
        }

    def _import_map(subdir: str, filenames: Sequence[str]) -> dict[str, Any]:
        """Map each module's bare URL to its versioned one."""
        return {
            "imports": {
                url_for("static", filename=f"js/{subdir}/{name}"): url_for(
                    "static", filename=f"js/{subdir}/{name}", v=ASSET_VERSION
                )
                for name in filenames
            }
        }

    app.jinja_env.globals["_import_map"] = _import_map

    def base_render_context(lang: str | None = None, *, admin: bool = False) -> dict[str, Any]:
        """Everything any full page render needs, shared by / and /admin.

        Deliberately a function rather than a context processor. ``t`` and
        ``i18n_runtime`` depend on the language negotiated for *this* request,
        which a processor cannot see without redoing the negotiation, and the
        import map must not be built for a partial render that will never use
        it. Two callers, one definition.

        ``admin`` widens the inlined catalogue and glyph set. It defaults to
        False so the anonymous landing page keeps shipping exactly what it
        shipped before.
        """
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_anon_key = os.getenv("SUPABASE_ANON_KEY")

        if not supabase_url or not supabase_anon_key:
            logger.warning(
                "Supabase configuration missing: URL=%s, Key=%s",
                "present" if supabase_url else "missing",
                "present" if supabase_anon_key else "missing",
            )

        # Rendering the page strings server-side means an Arabic reader never
        # sees a flash of English while the JS boots.
        lang = lang or pick_lang(request)
        catalog = load_catalog(lang)

        # An undetermined flag (a cold process whose first read failed)
        # renders the signup form OPEN, never hidden — hiding it on every
        # blip would mean readers periodically cannot even see the tab, and
        # the `503` at submit time is the honest place to say "could not
        # check". Only a confirmed pause hides it here.
        signup_enabled = app.config["settings_service"].signup_enabled()

        return {
            "SUPABASE_URL": supabase_url or "",
            "SUPABASE_ANON_KEY": supabase_anon_key or "",
            "lang": lang,
            "text_dir": text_direction(lang),
            "t": make_translator(catalog),
            "i18n_runtime": runtime_subset(catalog, include_admin=admin),
            "icons_runtime": runtime_icons(include_admin=admin),
            # The one category->glyph mapping, shared with the browser rather
            # than restated there. DESIGN.md: the same mapping written down
            # twice is the same mapping drifting eventually.
            "category_icons": CATEGORY_ICONS,
            "policy_version": PRIVACY_POLICY_VERSION,
            "signup_paused": signup_enabled is False,
        }

    app.config["base_render_context"] = base_render_context

    def _render_shell() -> Response:
        """The one HTML shell both `/` and `/c/<uuid>` render.

        Identical either way: same `base_render_context`, same import map,
        same `?lang=` persistence. `/c/<uuid>` deliberately never reads the
        uuid to build this response — see that route's docstring for why that
        is the security property, not an oversight.
        """
        context = base_render_context()
        response = make_response(
            render_template(
                "index.html",
                **context,
                is_authenticated=bool(session.get("user_email")),
                user_email=session.get("user_email"),
                module_import_map=_import_map("modules", MODULE_FILENAMES),
            )
        )
        # Persist an explicit ?lang= so the choice survives the next visit.
        if request.args.get("lang"):
            response.set_cookie(
                "lang", context["lang"], max_age=31_536_000, samesite="Lax", path="/"
            )
        # Without this the document is heuristically cacheable, so a reader can
        # keep being served a pre-deploy page indefinitely. `no-cache` still lets
        # it be stored — it just forces revalidation, so this costs nothing today
        # and bounds the old-client window once the /c/<id> rollout begins.
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.route("/")
    def index():
        return _render_shell()

    @app.route("/privacy")
    def privacy_policy() -> Response:
        """سياسة الاستخدام والخصوصية / Usage and Privacy Policy.

        Public, ungated, no session or identity touched — the same reasoning
        `deep_link` gives for why a public page must be safe to open blind.

        Its `page.policy.version` string is the value the signup form and
        `handle_new_user` record as `marketing_consent_policy_version`
        (docs/profile-refactor-plan.md §16·3, Spec 3). Bump it whenever the
        policy's substance changes, so an old consent record stays
        attributable to the text it was actually given under.

        DRAFT CONTENT: written to unblock Step 6's engineering per the
        product owner's own instruction (2026-08-23) — generic, not
        reviewed as a legal document. `page.policy.draftNotice` says so on
        the page itself. Do not treat this as final copy.
        """
        context = current_app.config["base_render_context"]()
        response = make_response(
            render_template(
                "privacy.html",
                **context,
                module_import_map=_import_map("modules", MODULE_FILENAMES),
            )
        )
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.route("/c/<uuid:conversation_id>")
    def deep_link(conversation_id) -> Response | WerkzeugResponse:
        """A conversation's URL. Renders exactly what `/` renders.

        Three properties, each a decision — see
        docs/per-tab-conversation-deep-linking-plan.md §3.1 for the full
        argument, verified against this app's actual CSRF/oracle posture in
        the security review:

        NOT `@auth_required`. `/` is not either. A deep link opened by a
        signed-out reader must land on the landing page and KEEP ITS PATH, so
        signing in hydrates the conversation they clicked — the client reads
        `Route.current()` once identity resolves.

        NO OWNERSHIP CHECK, NO SESSION STATE TOUCHED. The response never
        varies with the id: for a fixed requester, no uuid produces an
        observable difference from any other. That is what makes this route
        safe to open blind — a link scanner, an unfurl bot, a forged link in
        an email — and what stops it from ever being a CSRF vector: unlike
        `GET /api/chat/history`, this route cannot repoint anything, because
        it has nothing to repoint. Enforcement lives entirely in the
        authenticated `GET /api/chat/history?c=<id>`.

        CANONICAL CASE. Werkzeug's `<uuid:>` converter accepts uppercase hex,
        so `/c/F47AC…` and `/c/f47ac…` would otherwise be two URLs for one
        conversation — two history entries, two log lines. Redirected to the
        lowercase canonical form, mirroring `canonical_uuid`'s own
        dash-normalisation.
        """
        canonical = str(conversation_id)
        raw = request.path[len("/c/") :]
        if raw != canonical:
            target = f"/c/{canonical}"
            if request.query_string:
                target = f"{target}?{request.query_string.decode()}"
            return redirect(target, code=301)

        response = _render_shell()
        # Never indexed, never followed — a conversation's URL is not a page
        # search should surface, even though it carries no content itself.
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.route("/favicon.ico")
    def favicon() -> Response:
        assert app.static_folder is not None  # this app always configures one
        return send_from_directory(
            app.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon"
        )

    @app.route("/api/frequent-questions")
    def get_frequent_questions() -> Response:
        """Return one language's FAQ block.

        The response shape is unchanged from before the i18n work, so the
        client and its tests need no changes.
        """
        catalogs = current_app.config["FREQUENT_QUESTIONS"]
        lang = normalize_lang(request.args.get("lang") or request.cookies.get("lang"))

        selected = dict(catalogs.get("en", {}))
        # Per-category fallback: a category missing from Arabic still renders,
        # in English, rather than vanishing from the sidebar.
        selected.update(catalogs.get(lang, {}))

        # The glyph is derived from the category key, not carried in faq.yaml.
        # It used to be spelled out there once per category per language — four
        # categories x two languages x one more place the composer's selector
        # also names, which is five chances for the same category to end up with
        # two different marks. One mapping, in web/utils/icons.py, now feeds
        # both the selector and these headings.
        selected = {
            key: {**block, "icon": CATEGORY_ICONS.get(key, "question")}
            for key, block in selected.items()
            if isinstance(block, dict)
        }
        return jsonify(selected)

    @app.route("/api/identity")
    @auth_required
    def identity() -> Response:
        """What the server believes about the caller.

        The authoritative answer to "am I an administrator", as opposed to the
        `is_admin_hint` cookie value, which only decides whether a link is drawn
        on a page rendered without validating a token. The client asks this once
        after sign-in and reveals admin chrome from the answer — which is also
        the only thing that works on a first sign-in in a fresh browser, where
        there is no hint yet because no authenticated request has been made.

        Deliberately says nothing a reader may not know about themselves: no
        other accounts, no counts of *other* accounts, no settings.

        `created_at`/`conversation_count` back the /account standing line and
        are fetched here rather than folded into the cached identity flags —
        see `AdminBackend.get_standing_line_facts`'s own docstring for why a
        conversation-count subquery does not belong on the hot chat-request
        path. A lookup failure degrades to `null` for both rather than
        failing the whole response: the role/tier/is_admin answer above is
        the one thing this endpoint must not fail to give.

        Also records presence via `touch_last_seen` — throttled to one write
        per account per hour in the database, so calling it here on every hit
        needs no in-process debounce. In its own `try`/`except`, deliberately
        separate from the standing-line-facts lookup below: a failed touch
        must never blank out facts that loaded fine, and a facts failure must
        not skip the touch.
        """
        from web.services.admin_store import get_admin_backend

        flags: IdentityFlags = g.identity
        created_at = None
        conversation_count = None
        backend = get_admin_backend()
        if backend is not None:
            try:
                backend.touch_last_seen(flags.user_id)
            except Exception:
                logger.exception("Could not touch last_seen for %s", flags.user_id)

            try:
                facts = backend.get_standing_line_facts(flags.user_id)
            except Exception:
                logger.exception("Could not load standing-line facts for %s", flags.user_id)
                facts = None
            if facts is not None:
                created_at = facts.get("created_at")
                conversation_count = facts.get("conversation_count")

        return jsonify(
            {
                "user_id": flags.user_id,
                "email": flags.email,
                "role": flags.role,
                "tier": flags.tier,
                "is_admin": flags.is_admin,
                "is_disabled": flags.is_disabled,
                "created_at": created_at,
                "conversation_count": conversation_count,
            }
        )

    # Shared across both chat routes so a client cannot double its allowance by
    # alternating between the streaming and blocking endpoints.
    chat_limit = limiter.shared_limit(
        lambda: config.get("server", "rate_limit", {}).get("chat_api", "10 per minute"),
        scope="chat",
    )

    def _validate_chat_request() -> tuple[dict[str, Any] | None, tuple[Response, int] | None]:
        """Parse and validate a chat payload. Returns (payload, error_response)."""
        # NOT `force=True`. That parsed the body regardless of Content-Type,
        # which made both chat POSTs reachable by a cross-site auto-submitting
        # form using `enctype="text/plain"` — a CORS-simple content type that
        # triggers no preflight — combined with this app having no CSRF
        # protection and `_get_token_from_request` accepting the session
        # cookie. The client always sends `Content-Type: application/json`
        # (services.js), so nothing legitimate depends on `force=True`; a
        # text/plain form cannot forge a real JSON content type past
        # `silent=True` alone. See
        # docs/per-tab-conversation-deep-linking-plan.md §3.5.
        body = request.get_json(silent=True) or {}
        query = (body.get("query") or "").strip()
        category = (body.get("category") or "all").lower()
        lang = (body.get("lang") or "en").lower()

        if not query:
            return None, (jsonify(error="Query cannot be empty"), 400)
        if len(query) > MAX_CHAT_QUERY_CHARS:
            # Bounded HERE rather than at the database, so an over-long question
            # is the 400 it is instead of a 500 raised from inside a SECURITY
            # DEFINER function. Before this, `content text` accepted a 200KB
            # question and the only limit was whatever the model refused.
            return None, (
                jsonify(error=f"Query is too long (limit {MAX_CHAT_QUERY_CHARS} characters)."),
                400,
            )
        if category not in ALLOWED_CHAT_CATEGORIES:
            return None, (
                jsonify(error=f"Invalid category. Allowed: {', '.join(CHAT_CATEGORIES)}"),
                400,
            )

        engine = current_app.config.get("search_engine")
        if not engine or not engine.is_initialized():
            logger.error("Search engine unavailable for chat request.")
            return None, (jsonify(error="Search service is currently unavailable."), 503)

        # `conversation_id`: missing or malformed mints a fresh id, the same
        # tolerance `client_request_id` gets — a 400 would turn a client bug
        # into a failed question. THE URL IS THE POINTER (§1), so there is no
        # cookie left to fall back to: an absent value is simply a fresh
        # conversation, exactly as if the client had minted one itself and
        # not yet told the server. §8's rollout window, during which "absent"
        # had to be told apart from "reset" and "resume" by a cookie, is over.
        conversation_id = canonical_uuid(body.get("conversation_id")) or new_conversation_id()

        return {
            "query": query,
            "category": category,
            "lang": lang if lang in SUPPORTED_CHAT_LANGS else "en",
            "engine": engine,
            # CLIENT-MINTED, one per logical submission and reused across
            # retries — that is the whole point, and it is why the server does
            # not mint it. A server-minted id would be fresh on every retry, so
            # the unique constraint it feeds would never fire and the
            # idempotency would be decorative.
            #
            # A missing or malformed value falls back to a fresh id rather than
            # a 400: an old client that has not been updated must keep working,
            # and it simply gets no replay protection.
            "client_request_id": canonical_uuid(body.get("client_request_id"))
            or new_conversation_id(),
            "conversation_id": conversation_id,
            # Default TRUE, not False. An old client never sends this key at
            # all, and the un-updated caller must keep lazily creating exactly
            # as it does today — the same "un-updated caller still resolves"
            # reasoning the `p_allow_create default true` migration comment
            # gives, applied one layer up. A new client sends it explicitly:
            # true on a brand-new conversation's first turn, false on every
            # turn to a conversation the URL already names.
            "allow_create": bool(body.get("allow_create", True)),
        }, None

    @app.route("/api/chat/history", methods=["GET"])
    @auth_required
    # An explicit limit REPLACES the global per_day/per_hour/per_minute
    # defaults rather than stacking with them — Flask-Limiter applies its
    # defaults only to "routes without explicit decorators", and this was also
    # measured against this app rather than taken on trust. That is the point:
    # this read fires on every
    # sign-in, reload and language toggle, so inheriting the 200/day default
    # would let ordinary navigation exhaust a budget an office behind one NAT
    # shares with chat itself.
    @limiter.limit(
        lambda: config.get("server", "rate_limit", {}).get("history_api", "30 per minute")
    )
    def handle_chat_history() -> Response | tuple[Response, int]:
        """One conversation's durable rows, named by `?c=<uuid>`.

        THE URL IS THE POINTER (§1 of
        docs/per-tab-conversation-deep-linking-plan.md). `?c=` absent means
        `/` — a new conversation, Decision 1(a) — and this route answers an
        empty transcript without touching the backend at all: there is
        nothing to look up, and no session state to read or write either way.

        A SUPPLIED id that does not exist for this owner answers 404, not an
        empty transcript. `chat_load_session` alone cannot tell "not yours,
        or not there" from "yours, but no turns have landed yet", which was
        harmless while every id was server-minted (yours by construction) but
        is not once an id can arrive from a URL — a hostile or stale deep
        link must not render as an ordinary empty conversation (§3.3).
        """
        requested_id = canonical_uuid(request.args.get("c"))
        if requested_id is None:
            return _no_store(jsonify(conversation_id=None, messages=[]))

        owner_id = _durable_owner()
        persistence = _chat_persistence()

        if not owner_id:
            # No durable owner: nothing was ever filed for this reader, so an
            # empty transcript is the truth rather than a shrug.
            return _no_store(jsonify(conversation_id=requested_id, messages=[]))

        if persistence is None:
            # Two different states, and only one of them is quiet. A deployment
            # with persistence switched off has no history by design; persistence
            # switched ON with no backend is a misconfiguration, and reporting it
            # as "you have no history" is the silent-success failure `_persist_turn`
            # was already fixed for.
            if current_app.config.get("CHAT_PERSISTENCE_ENABLED", False):
                logger.error(
                    "Chat persistence is enabled but no backend is configured; "
                    "the transcript cannot be loaded. Check SUPABASE_SERVICE_ROLE_KEY."
                )
                return (
                    jsonify(
                        error="Your conversation history could not be loaded.",
                        code="history_unavailable",
                    ),
                    503,
                )
            return _no_store(jsonify(conversation_id=requested_id, messages=[]))

        try:
            exists = persistence.session_exists(owner_id, requested_id)
        except PersistenceUnavailable:
            logger.warning(
                "Could not verify conversation %s exists.",
                requested_id,
                exc_info=True,
            )
            return (
                jsonify(
                    error="Your conversation history could not be loaded.",
                    code="history_unavailable",
                ),
                503,
            )
        if not exists:
            # Not yours, or not there. Deliberately one answer.
            return jsonify(error="Unknown conversation.", code="not_found"), 404

        requested = request.args.get("limit", type=int)
        limit = clamp_load_limit(
            requested if requested is not None else current_app.config["CHAT_HYDRATION_LIMIT"]
        )

        try:
            rows = persistence.load_session(owner_id, requested_id, limit=limit)
        except PersistenceUnavailable:
            # Told, not swallowed. `_load_history` degrades to an empty prompt
            # window because a reader would rather have an answer without prior
            # context than no answer — but an empty TRANSCRIPT is a claim that
            # they have no history, and making that claim while the store is
            # unreachable is the kind of quiet untruth this product's citations
            # exist to refuse.
            logger.warning(
                "Could not hydrate the transcript for conversation %s.",
                requested_id,
                exc_info=True,
            )
            return (
                jsonify(
                    error="Your conversation history could not be loaded.",
                    code="history_unavailable",
                ),
                503,
            )

        messages = _hydration_payload(rows)
        # This body is one reader's conversation. Nothing should hold a copy of
        # it — not a shared-machine browser cache, not an intermediary.
        return _no_store(jsonify(conversation_id=requested_id, messages=messages))

    # ── The sidebar: list, select, rename, delete ────────────────────────────
    #
    # ALL FOUR GO THROUGH FLASK, and the roadmap's §9 expected otherwise: it
    # described step 8 as "the first feature to call `chat_sessions_delete_own`
    # from a browser with no Flask route in between". That plan was retired, not
    # forgotten, for two reasons the navigation migration states in full.
    #
    # The one that decides it is not about privilege at all. A tab still
    # sitting on the deleted conversation's URL sends that id on its next
    # question, and `chat_append_turn`'s `on conflict (id) do nothing` would
    # recreate the row — the reader deletes a conversation and it comes back.
    # Clearing the `ConversationStore` window is Flask's to do (the model's
    # memory of the conversation, not something RLS reaches), so the delete
    # has to arrive here regardless of who is permitted to run the DELETE.
    #
    # RLS is unchanged and still the floor. It is defence in depth against a
    # leaked anon key, not the coordinator of a workflow spanning a cookie, a
    # process-local cache and three tables.

    def _sidebar_preconditions() -> tuple[str | None, Any | None, tuple[Response, int] | None]:
        """(owner, backend, error) for every session route.

        Factored out because the four routes below must agree about what
        "history is not available" means, and the failure this guards against is
        one of them quietly deciding an outage is an empty list. `/api/chat/history`
        already refuses to make that claim; a sidebar that renders "no
        conversations" over an unreachable store makes the same false statement
        in a louder place.
        """
        owner_id = _durable_owner()
        persistence = _chat_persistence()

        if persistence is None or not owner_id:
            # Persistence ON with no backend is a live misconfiguration and says
            # so; OFF is a deployment choice and stays quiet. The same split
            # `_persist_turn` and the transcript route already make.
            if persistence is None and current_app.config.get("CHAT_PERSISTENCE_ENABLED", False):
                logger.error(
                    "Chat persistence is enabled but no backend is configured; "
                    "the conversation list cannot be served."
                )
                return (
                    None,
                    None,
                    (
                        jsonify(
                            error="Your conversations could not be loaded.",
                            code="history_unavailable",
                        ),
                        503,
                    ),
                )
            return owner_id, None, None

        return owner_id, persistence, None

    def _owned_session_id(raw: str) -> str | None:
        """A canonical uuid, or None when this cannot name a session.

        Canonicalised for the same reason `canonical_uuid` exists at all:
        ids minted before the dashed form shipped are 32 hex characters, a
        `uuid` column returns them dashed, and an un-normalised comparison across
        that boundary silently never matches. Under TESTING the bypass
        identities are not uuids at all, but SESSION ids always are — they are
        minted by `new_conversation_id()` — so this is safe to require here in a
        way it is not for an owner id.
        """
        return canonical_uuid(raw)

    def _session_limit() -> str:
        return config.get("server", "rate_limit", {}).get("sessions_api", "60 per minute")

    @app.route("/api/chat/sessions", methods=["GET"])
    @auth_required
    @limiter.limit(_session_limit)
    def handle_chat_sessions() -> Response | tuple[Response, int]:
        """One page of the reader's conversations, newest activity first.

        No `active` field. The client knows exactly which conversation is
        current — it is its own URL (§5.3) — and the server has nothing to add
        to that; a cookie-derived answer would be wrong for every tab but one.

        NOTE this does NOT touch session state. Listing conversations is not
        starting one.
        """
        owner_id, persistence, error = _sidebar_preconditions()
        if error:
            return error

        if persistence is None:
            # No durable owner, or persistence deliberately off. An empty list is
            # the truth here rather than a shrug — nothing was ever filed.
            return _no_store(jsonify(sessions=[], next_cursor=None))

        cursor_updated_at = request.args.get("cursor_updated_at")
        cursor_id = request.args.get("cursor_id")
        # Both halves or neither, matching the RPC's own guard. A half cursor is
        # a client bug, and paging from the top is the recoverable reading of it.
        cursor = (
            (cursor_updated_at, cursor_id)
            if cursor_updated_at and _owned_session_id(cursor_id or "")
            else None
        )

        try:
            page = persistence.list_sessions(
                owner_id,
                limit=clamp_list_limit(request.args.get("limit", type=int)),
                cursor=cursor,
            )
        except PersistenceUnavailable:
            logger.warning("Could not list conversations.", exc_info=True)
            return (
                jsonify(
                    error="Your conversations could not be loaded.",
                    code="history_unavailable",
                ),
                503,
            )

        return _no_store(
            jsonify(
                sessions=[
                    {
                        "id": s.session_id,
                        # Null travels as null. The client renders a localised
                        # "Untitled conversation"; inventing one here would put
                        # English in an Arabic sidebar.
                        "title": s.title,
                        "created_at": s.created_at,
                        "updated_at": s.updated_at,
                        "message_count": s.message_count,
                    }
                    for s in page.sessions
                ],
                next_cursor=(
                    {"updated_at": page.next_cursor[0], "id": page.next_cursor[1]}
                    if page.next_cursor
                    else None
                ),
            )
        )

    # NO /select ROUTE. Its entire job was moving the cookie that named the
    # current conversation (docs/per-tab-conversation-deep-linking-plan.md
    # §5.2) — with no cookie, selecting a conversation is navigating to its
    # URL, which the client does directly. Deleting it also closes a live CSRF
    # hole incidentally: it parsed no body at all, so any cross-site
    # auto-submitting form could have repointed a victim's conversation.
    # `test_there_is_no_route_that_repoints_a_conversation_by_cookie` pins the
    # absence so a future refactor cannot reintroduce an equivalent endpoint.

    @app.route("/api/chat/sessions/<session_id>", methods=["PATCH"])
    @auth_required
    @limiter.limit(_session_limit)
    def handle_chat_session_rename(session_id: str) -> Response | tuple[Response, int]:
        """Rename one owned conversation.

        The title is clamped HERE, above the database, so an over-long or
        whitespace-only title is the client error it is rather than a CHECK
        violation raised inside a `security definer` function and surfacing as a
        500. `clamp_title` collapses whitespace, cuts on a word boundary at 120
        characters, and returns None for empty — which the RPC stores as null and
        the sidebar renders with its untitled fallback, so "clear the name" is a
        reachable, meaningful action rather than an error.
        """
        owner_id, persistence, error = _sidebar_preconditions()
        if error:
            return error

        canonical = _owned_session_id(session_id)
        if not canonical or persistence is None or not owner_id:
            return jsonify(error="Unknown conversation.", code="not_found"), 404

        payload = request.get_json(silent=True) or {}
        if "title" not in payload:
            return jsonify(error="A title is required.", code="invalid_request"), 400

        raw = payload.get("title")
        if raw is not None and not isinstance(raw, str):
            return jsonify(error="A title is required.", code="invalid_request"), 400

        title = clamp_title(raw)

        try:
            renamed = persistence.rename_session(owner_id, canonical, title)
        except PersistenceUnavailable:
            logger.warning("Could not rename conversation %s.", canonical, exc_info=True)
            return (
                jsonify(error="That conversation could not be renamed.", code="rename_failed"),
                503,
            )

        if not renamed:
            return jsonify(error="Unknown conversation.", code="not_found"), 404

        # The clamped value is echoed rather than the submitted one, so the
        # sidebar shows what was actually stored. A client that rendered its own
        # input would show an untruncated title until the next reload.
        return _no_store(jsonify(ok=True, id=canonical, title=title))

    @app.route("/api/chat/sessions/<session_id>", methods=["DELETE"])
    @auth_required
    @limiter.limit(_session_limit)
    def handle_chat_session_delete(session_id: str) -> Response | tuple[Response, int]:
        """Delete one owned conversation, and everything pointing at it.

        THE DELETE IS THE EASY HALF. The row goes and the cascade takes its
        messages and sources. What makes this a route rather than a browser
        call is the `ConversationStore` window it would otherwise outlive —
        the model's memory of the conversation. Left in place, the next
        answer is informed by a conversation the reader deleted, and
        `chat_append_turn`'s `on conflict (id) do nothing` would recreate the
        row the moment a stray write landed on it.

        No cookie to rotate any more (§5.1/§5.2): the client names the
        conversation it deletes by its URL, and if that is the route it is
        currently on, moving off it — to `/` — is the client's job (§4.4),
        not something this response hands back.

        A generation in flight is refused outright rather than any of this
        being attempted: the write is already committed to landing and would
        recreate the row after the delete. See `_InFlightGenerations`.
        """
        owner_id, persistence, error = _sidebar_preconditions()
        if error:
            return error

        canonical = _owned_session_id(session_id)
        if not canonical or persistence is None or not owner_id:
            return jsonify(error="Unknown conversation.", code="not_found"), 404

        if _generations().is_live(owner_id, canonical):
            return jsonify(
                error="An answer is still being generated.",
                code="generation_in_flight",
            ), 409

        try:
            deleted = persistence.delete_session(owner_id, canonical)
        except PersistenceUnavailable:
            logger.warning("Could not delete conversation %s.", canonical, exc_info=True)
            return (
                jsonify(error="That conversation could not be deleted.", code="delete_failed"),
                503,
            )

        if not deleted:
            return jsonify(error="Unknown conversation.", code="not_found"), 404

        store: ConversationStore = current_app.config["conversations"]
        store.clear(canonical)

        return _no_store(jsonify(ok=True, id=canonical))

    # ── Notification Center (reader) ────────────────────────────────────────
    #
    # docs/notification-center-plan.md. REST here is the guaranteed-delivery
    # path; a Realtime push (web/services/notification_service.py) only ever
    # tells an open tab "go call one of these again" — it carries no content
    # of its own. Every response is private, no-store: these are one
    # reader's targeted messages and read state, the same reasoning
    # `_no_store` already applies to conversation titles.

    def _notification_backend() -> Any | None:
        factory = current_app.config.get("notification_backend")
        return factory() if factory else None

    def _notifications_limit(name: str, default: str):
        return lambda: config.get("server", "rate_limit", {}).get(name, default)

    def _localized_notification(row: dict, lang: str) -> dict:
        title_key = "title_ar" if lang == "ar" else "title_en"
        body_key = "body_ar" if lang == "ar" else "body_en"
        return {
            "id": row["id"],
            "type": row["type"],
            "severity": row["severity"],
            "title": row.get(title_key) or row.get("title_en"),
            "body": row.get(body_key) or row.get("body_en"),
            "requires_ack": bool(row.get("requires_ack")),
            "created_at": row.get("created_at"),
            "expires_at": row.get("expires_at"),
            "deactivated_at": row.get("deactivated_at"),
            "read_at": row.get("read_at"),
            "dismissed_at": row.get("dismissed_at"),
            "acknowledged_at": row.get("acknowledged_at"),
        }

    @app.route("/api/notifications/active", methods=["GET"])
    @auth_required
    @limiter.limit(_notifications_limit("notifications_active_api", "30 per minute"))
    def handle_notifications_active() -> Response | tuple[Response, int]:
        backend = _notification_backend()
        if backend is None:
            # No service-role key configured for this deployment. An absent
            # notification is not a lie the way a false "no conversations"
            # would be — nothing durable is lost, unlike chat history.
            return _no_store(jsonify(notifications=[]))

        lang = (request.args.get("lang") or "en").lower()
        try:
            rows = backend.list_active_for_reader(g.identity.user_id)
        except Exception:
            logger.warning(
                "Could not load active notifications for %s.", g.identity.user_id, exc_info=True
            )
            return (
                jsonify(
                    error="Notifications could not be loaded.",
                    code="notifications_unavailable",
                ),
                503,
            )

        return _no_store(
            jsonify(notifications=[_localized_notification(row, lang) for row in rows])
        )

    @app.route("/api/notifications/history", methods=["GET"])
    @auth_required
    @limiter.limit(_notifications_limit("notifications_history_api", "20 per minute"))
    def handle_notifications_history() -> Response | tuple[Response, int]:
        """Cursor/keyset page of every notification ever targeted to this
        reader, matching /api/chat/sessions's own cursor_updated_at/cursor_id
        shape exactly — this app's actual reader-facing pagination precedent.
        """
        backend = _notification_backend()
        if backend is None:
            return _no_store(jsonify(notifications=[], next_cursor=None))

        lang = (request.args.get("lang") or "en").lower()
        cursor_created_at = request.args.get("cursor_created_at")
        cursor_id = request.args.get("cursor_id")
        # Both halves or neither, matching the RPC's own guard — a half
        # cursor is a client bug, and paging from the top is the recoverable
        # reading of it.
        if not cursor_created_at or not cursor_id:
            cursor_created_at = None
            cursor_id = None

        limit = clamp_list_limit(request.args.get("limit", type=int))

        try:
            rows = backend.list_history_for_reader(
                g.identity.user_id,
                cursor_created_at=cursor_created_at,
                cursor_id=cursor_id,
                limit=limit,
            )
        except Exception:
            logger.warning(
                "Could not load notification history for %s.", g.identity.user_id, exc_info=True
            )
            return (
                jsonify(
                    error="Notification history could not be loaded.",
                    code="notifications_unavailable",
                ),
                503,
            )

        next_cursor = (
            {"created_at": rows[-1]["created_at"], "id": rows[-1]["id"]}
            if len(rows) == limit
            else None
        )
        return _no_store(
            jsonify(
                notifications=[_localized_notification(row, lang) for row in rows],
                next_cursor=next_cursor,
            )
        )

    @app.route("/api/notifications/mark-read", methods=["POST"])
    @auth_required
    @limiter.limit(_notifications_limit("notifications_mark_api", "60 per minute"))
    def handle_notifications_mark_read() -> Response | tuple[Response, int]:
        backend = _notification_backend()
        if backend is None:
            return jsonify(error="storage_unavailable"), 503

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="invalid_payload"), 400

        notification_id = payload.get("notification_id")
        action = payload.get("action")
        if not isinstance(notification_id, str) or action not in (
            "read",
            "dismissed",
            "acknowledged",
        ):
            return jsonify(error="invalid_payload"), 400

        try:
            uuid.UUID(notification_id)
        except (ValueError, AttributeError, TypeError):
            return jsonify(error="no_such_notification"), 404

        from web.services.admin_store import AdminActionRefused

        try:
            row = backend.mark_read(notification_id, g.identity.user_id, action)
        except AdminActionRefused as refused:
            status = 404 if refused.code == "no_such_notification" else 409
            return jsonify(error=refused.code), status
        except Exception:
            logger.warning(
                "Could not record %s on %s for %s.",
                action,
                notification_id,
                g.identity.user_id,
                exc_info=True,
            )
            return jsonify(error="mark_read_failed"), 503

        # Not jsonify(ok=True, notification_id=notification_id, **row): the real
        # backend's `row` is notifications_mark_read's `to_jsonb(v_row)`, and
        # `public.user_notification_reads` has its own `notification_id` column
        # — that RPC's return shape is a superset of what the in-memory testing
        # double happened to return, so this collided (TypeError: got multiple
        # values for keyword argument 'notification_id') on every call against
        # the real database while every test, running against the double, saw
        # no collision at all and could not have caught it. Building the dict
        # explicitly makes `notification_id` always the requested one, whether
        # or not the backend's row already carries it.
        payload = dict(row)
        payload["notification_id"] = notification_id
        payload["ok"] = True
        return _no_store(jsonify(payload))

    @app.route("/api/notifications/mark-all-read", methods=["POST"])
    @auth_required
    @limiter.limit(_notifications_limit("notifications_mark_api", "60 per minute"))
    def handle_notifications_mark_all_read() -> Response | tuple[Response, int]:
        backend = _notification_backend()
        if backend is None:
            return jsonify(error="storage_unavailable"), 503

        try:
            count = backend.mark_all_read(g.identity.user_id)
        except Exception:
            logger.warning(
                "Could not mark all notifications read for %s.",
                g.identity.user_id,
                exc_info=True,
            )
            return jsonify(error="mark_read_failed"), 503

        return _no_store(jsonify(ok=True, marked=count))

    @app.route("/api/chat/stream", methods=["POST"])
    @auth_required
    @chat_limit
    def handle_chat_stream() -> Response | tuple[Response, int]:
        payload, error = _validate_chat_request()
        if error:
            return error
        assert payload is not None  # _validate_chat_request's contract: exactly one is None

        query, category, lang = payload["query"], payload["category"], payload["lang"]
        engine = payload["engine"]
        handler: OpenAIHandler = current_app.config["openai_handler"]
        store: ConversationStore = current_app.config["conversations"]
        max_pairs = current_app.config["MAX_CHAT_HISTORY_MESSAGE_PAIRS"]
        max_chars = current_app.config["MAX_CHAT_HISTORY_CHARS"]

        client_request_id = payload["client_request_id"]
        allow_create = payload["allow_create"]
        owner_id = _durable_owner()
        persistence = _chat_persistence()

        # THE URL IS THE POINTER (§1). No cookie touched at all, ever —
        # `_validate_chat_request` has already minted a fresh id for a
        # missing or malformed value, so this is never None.
        conversation_id = payload["conversation_id"]

        # Claimed in the VIEW BODY, not inside generate(). The generator does not
        # start running until the WSGI server iterates it, and the sidebar's
        # delete can arrive in that gap — on a threaded server it demonstrably
        # does. Holding from here means the protection covers the whole window in
        # which this conversation is committed to being written to. The
        # preflight below runs UNDER this same hold, for the same reason.
        generations = _generations()
        hold = generations.hold(owner_id, conversation_id)
        hold.__enter__()

        # `allow_create=false` says "this conversation already exists; do not
        # create it". Refused HERE — before retrieval, before a token is
        # generated, before any response frame — rather than discovered after
        # the answer has already streamed. See `_preflight_conversation` and
        # docs/per-tab-conversation-deep-linking-plan.md §3.4.
        if not allow_create and not _preflight_conversation(persistence, owner_id, conversation_id):
            hold.__exit__(None, None, None)
            return jsonify(error="Unknown conversation.", code="not_found"), 404

        store.adopt_cookie_history(
            conversation_id, session.pop("chat_history", None), owner_id=owner_id
        )
        history = _load_history(store, persistence, owner_id, conversation_id, max_pairs, max_chars)

        def generate():
            try:
                # `conversation_id` rides meta, final and done — never delta. A
                # delta frame is {"t": token}; a uuid on each one adds ~29KB to
                # an 800-token answer, and the client already discards a stale
                # stream with an AbortController and a generation stamp.
                yield sse(
                    "meta",
                    {
                        "conversation_id": conversation_id,
                        "client_request_id": client_request_id,
                        "category": category,
                        "lang": lang,
                        "model": getattr(handler, "model", "unknown"),
                    },
                )
                yield sse("stage", {"stage": "searching"})

                llm_context, retrieved = _retrieve_for_prompt(engine, query, category, handler)
                yield sse("stage", {"stage": "retrieved", "count": len(retrieved)})

                # No "sources" frame here any more. It used to be emitted at
                # this point — before the model had been called — so the deck
                # could not reflect what the answer did with the passages, and
                # a refusal arrived with eight source cards attached. What the
                # reader gets mid-stream is the count above; the passages
                # themselves ride on "final", once there is an answer to judge
                # them against.

                yield sse("stage", {"stage": "drafting"})
                parts: list[str] = []
                for token in handler.stream_response(
                    query, llm_context, category, history, lang=lang
                ):
                    parts.append(token)
                    yield sse("delta", {"t": token})

                answer, cited, sources = _finalize_answer("".join(parts).strip(), retrieved)

                yield sse("stage", {"stage": "finalizing"})

                # `sources` is what the answer CITED, and nothing else. An
                # answer that cited nothing ships an empty list, so no source
                # control renders at all.
                #
                # This used to ship the retrieval candidates in that case,
                # behind a muted "8 passages retrieved, not cited" control, on
                # the theory that a reader auditing the answer still wants to
                # see what search offered. In practice it read as a
                # contradiction — the label disclaims the passages in the same
                # breath as advertising eight of them — and on a refusal it is
                # still the surface putting evidence under an answer that has
                # none. `retrieved` below carries the count for the stage line
                # and the logs; the passages themselves stay server-side.
                #
                # The canonical result. `response` is the normalized answer,
                # which is NOT what the delta frames carried: those are raw
                # model tokens, so a model that reverts to "[Source: Guide.pdf,
                # Page: 14]" leaves the browser rendering prose while the
                # server holds "[1]". The client re-renders from this string,
                # so the marker the reader sees is the marker `cited` counted.
                yield sse(
                    "final",
                    {
                        "response": answer,
                        "sources": sources,
                        "cited": cited,
                        "retrieved": len(retrieved),
                        "conversation_id": conversation_id,
                        # Asserted, not computed, and the distinction matters. A
                        # live answer was just drawn from the active index, so its
                        # evidence is current by construction — there is nothing to
                        # infer. Computing it here would instead make every FRESH
                        # answer `unverifiable` on any deployment where
                        # `read_active_build_id` finds no pointer (the legacy flat
                        # layout), badging the one case that is beyond doubt. It
                        # ships on the wire so hydration and streaming hand the
                        # client one shape and it never grows two renderers.
                        "evidence_state": EVIDENCE_VERIFIED,
                    },
                )

                # Recorded HERE, before suggestions, and the order is the
                # point. `generate_suggestions` is a second blocking call to
                # OpenAI; running it first put a whole network round trip
                # between the reader receiving `final` — the complete,
                # normalized answer, which the client renders as authoritative
                # — and the turn existing in history. A tab closed or a
                # failure inside that window left the reader looking at an
                # answer the server had no record of, so the next question
                # could not refer to it. handlers.js says as much where it
                # handles `final` without `done`.
                #
                # `final` is the honest moment of completion: once it is sent
                # the answer is whole and the reader has it. Suggestions are a
                # garnish, and a garnish must not gate the record.
                store.append_turn(
                    conversation_id, query, answer, max_pairs, max_chars, owner_id=owner_id
                )

                # Durable immediately after the RAM window and still before
                # suggestions, for the same reason the ordering above exists:
                # `generate_suggestions` is a second blocking call to OpenAI, and
                # a garnish must not sit between the reader receiving a complete
                # answer and that answer being recorded.
                #
                # WRITTEN AT `final`, NOT RESERVED BEFORE THE STREAM. Reserving
                # in the view body would put a row in front of retrieval, so a
                # SearchEngineError would leave a durable session and an orphan
                # question — the blocking route retrieves first precisely to
                # avoid that, pinned by
                # test_a_retrieval_failure_does_not_start_a_conversation. The
                # cost is stated rather than hidden: a question whose answer is
                # aborted mid-stream leaves no durable trace at all, exactly as
                # it does today.
                if not _persist_turn(
                    persistence,
                    owner_id=owner_id,
                    conversation_id=conversation_id,
                    client_request_id=client_request_id,
                    question=query,
                    answer=answer,
                    sources=_persistable_sources(retrieved, cited),
                    lang=lang,
                    category=category,
                    model=getattr(handler, "model", "unknown"),
                    # The opening question names the conversation. Sent every
                    # turn; applied by the RPC only when there is no title yet.
                    title=query,
                    allow_create=allow_create,
                ):
                    # An `error` frame, NOT a new event name. services.js
                    # dispatches with `on[frame.event]?.()`, which silently drops
                    # an unregistered name — so a bespoke `persistence_error`
                    # event would vanish without a trace. As an `error` frame the
                    # existing handler picks it up, and its own comment already
                    # names "history persistence" as an auxiliary failure that
                    # must still render the answer.
                    yield sse(
                        "error",
                        {
                            "error": "This answer could not be saved to your history.",
                            "code": "persistence_unavailable",
                        },
                    )

                yield sse(
                    "suggestions",
                    {
                        "suggested_questions": handler.generate_suggestions(
                            query, answer, lang=lang
                        ),
                    },
                )

                yield sse(
                    "done",
                    {
                        "finish_reason": "stop",
                        "chars": len(answer),
                        "conversation_id": conversation_id,
                    },
                )

            except GeneratorExit:
                # Client disconnected (cancelled or navigated away). Re-raising
                # lets stream_response's context manager close the upstream
                # connection.
                #
                # Whether the turn was recorded depends on where the
                # disconnect landed, which is the correct dependency: a cancel
                # DURING drafting arrives before append_turn and is rightly
                # not recorded, because there is no complete answer and the
                # reader was not shown one. A cancel after `final` normally
                # finds the turn already recorded — also right, since by then
                # the reader has the whole answer on screen and their next
                # question may refer to it.
                #
                # "Normally", not "always", and the gap is worth stating rather
                # than leaving as a comfortable claim. `yield` SUSPENDS here: the
                # server writes the `final` chunk and only then calls next() to
                # resume past it, which is where the recording happens. If the
                # disconnect is detected on the write of `final` ITSELF, close()
                # throws GeneratorExit at that suspension point and neither the
                # RAM append nor the durable write ever runs — the reader has an
                # answer the server has no record of. Detection one frame later
                # finds it recorded. Verified against generator semantics, not
                # assumed.
                #
                # Left as is: it is the pre-existing behaviour, the window is one
                # socket write wide, and the plan accepts that an answer aborted
                # mid-stream leaves no durable trace. Recording before `final`
                # would close it, at the cost of putting a database round trip
                # in front of the frame the reader is waiting for.
                logger.info("Client disconnected mid-stream (conv=%s)", conversation_id)
                raise
            except SearchEngineError:
                # Retrieval failed. Reported as its own code rather than folded
                # into "internal", because the alternative — treating it as an
                # empty result set — would render as a confident refusal.
                logger.error("Retrieval failed (conv=%s)", conversation_id, exc_info=True)
                yield sse(
                    "error",
                    {
                        "error": "Search service is currently unavailable.",
                        "code": "search_unavailable",
                    },
                )
            except Exception:
                logger.error("Streaming chat failed (conv=%s)", conversation_id, exc_info=True)
                # The 200 status line is already sent, so failures after the
                # first yield can only be reported in-band.
                yield sse(
                    "error", {"error": "An internal server error occurred.", "code": "internal"}
                )
            finally:
                # Runs on every exit, GeneratorExit included — which is the one
                # that matters, because a client cancelling mid-stream is the
                # ORDINARY way this generator ends. Missing it would leave the
                # conversation marked live forever and undeletable for the life
                # of the process.
                hold.__exit__(None, None, None)

        try:
            response = Response(stream_with_context(generate()), mimetype="text/event-stream")
            sse_headers(response)
        except Exception:
            # The hold is released by the generator's own `finally`, and only
            # once it has started running. If constructing the response raises,
            # nothing ever iterates it, so nothing ever releases — release here
            # instead of leaking a permanent claim on this conversation.
            hold.__exit__(None, None, None)
            raise
        return response

    @app.route("/api/chat", methods=["POST"])
    @auth_required
    @chat_limit
    def handle_chat() -> Response | tuple[Response, int]:
        try:
            # The same validator the streaming route uses. This route used to
            # carry its own copy — same three rules, independently written, and
            # already drifting: it parsed with `get_json(force=True)` and no
            # `silent=True`, so a malformed body raised inside the `try` below
            # and was reported as a 500 "internal server error". A request whose
            # JSON the client got wrong is a 400, and the streaming route has
            # always said so. Two validators for one contract is how the two
            # endpoints came to disagree about what a bad request even is.
            payload, error = _validate_chat_request()
            if error:
                return error
            assert payload is not None  # _validate_chat_request's contract: exactly one is None

            query, category, lang = payload["query"], payload["category"], payload["lang"]
            search_engine: ImprovedSearchEngine = payload["engine"]

            # Captured BEFORE retrieval, not after. Search can block for a
            # noticeable time, and a settings change landing during it would
            # otherwise mean the request began under one model and generated
            # under another — coherent, but not the model that was current when
            # the reader asked. The streaming route already captured up front;
            # this makes the two agree, and makes the claim in the commit that
            # introduced the swap actually true.
            openai_handler: OpenAIHandler = current_app.config["openai_handler"]

            store: ConversationStore = current_app.config["conversations"]
            max_pairs = current_app.config["MAX_CHAT_HISTORY_MESSAGE_PAIRS"]
            max_chars = current_app.config["MAX_CHAT_HISTORY_CHARS"]

            owner_id = _durable_owner()
            persistence = _chat_persistence()
            generations = _generations()

            allow_create = payload["allow_create"]
            # THE URL IS THE POINTER (§1). `_validate_chat_request` has
            # already minted a fresh id for a missing or malformed value, so
            # this is never None.
            conversation_id = payload["conversation_id"]

            # Held and preflighted BEFORE retrieval, so a stale or foreign id
            # is refused before a token is generated. Taking the hold FIRST,
            # not after the check, is what makes a concurrent delete lose the
            # race rather than win it: a delete while a hold is live gets its
            # own 409 (`handle_chat_session_delete`), so the preflight's
            # answer cannot go stale underneath this request.
            hold = generations.hold(owner_id, conversation_id)
            hold.__enter__()
            if not allow_create and not _preflight_conversation(
                persistence, owner_id, conversation_id
            ):
                hold.__exit__(None, None, None)
                return jsonify(error="Unknown conversation.", code="not_found"), 404

            try:
                llm_context, retrieved = _retrieve_for_prompt(
                    search_engine, query, category, openai_handler
                )

                store.adopt_cookie_history(
                    conversation_id, session.pop("chat_history", None), owner_id=owner_id
                )
                chat_history = _load_history(
                    store, persistence, owner_id, conversation_id, max_pairs, max_chars
                )

                answer, suggested_questions = openai_handler.generate_response(
                    query,
                    llm_context,
                    category,
                    chat_history,
                    lang=lang,
                )
                # Same contract as the streaming path's "final" frame — both
                # routes go through `_finalize_answer`, so they cannot drift.
                answer, cited, sources = _finalize_answer(answer, retrieved)

                store.append_turn(
                    conversation_id, query, answer, max_pairs, max_chars, owner_id=owner_id
                )
                persisted = _persist_turn(
                    persistence,
                    owner_id=owner_id,
                    conversation_id=conversation_id,
                    client_request_id=payload["client_request_id"],
                    question=query,
                    answer=answer,
                    sources=_persistable_sources(retrieved, cited),
                    lang=lang,
                    category=category,
                    model=getattr(openai_handler, "model", "unknown"),
                    title=query,
                    allow_create=allow_create,
                )
            finally:
                hold.__exit__(None, None, None)

            return jsonify(
                response=answer,
                suggested_questions=suggested_questions,
                sources=sources,
                cited=cited,
                retrieved=len(retrieved),
                conversation_id=conversation_id,
                # Verified by construction — see the streaming route's `final`
                # frame for why this is asserted rather than compared.
                evidence_state=EVIDENCE_VERIFIED,
                # Reported, not raised. This route has not sent its status line
                # yet and could return a 5xx — but the answer is complete and
                # correctly cited, and throwing it away because the filing
                # cabinet is shut would be a strictly worse outcome for the
                # reader than telling them it was not filed.
                persisted=persisted,
            )

        except SearchEngineError:
            logger.error("Retrieval failed in /api/chat", exc_info=True)
            return jsonify(error="Search service is currently unavailable."), 503

        except Exception as exception:
            logger.error("Unhandled error in /api/chat: %s", exception, exc_info=True)
            return jsonify(error="An internal server error occurred."), 500

    # NO /api/conversation/reset ROUTE. It used to rotate the session cookie
    # that named the current conversation and, on `undo`, restore a set-aside
    # one — both cookie-keyed mechanisms §5.1 and §5.4 remove. Under
    # URL-as-truth, "New chat" is a client-side navigation from `/c/<id>` to
    # `/` (Decision 2 of docs/per-tab-conversation-deep-linking-plan.md) with
    # nothing for a server round trip to do, and undo is the Back button —
    # free, per-tab, already understood — rather than a server-held
    # `prev_conv_id`. `Handlers.handleNewChat` (static/js/modules/handlers.js)
    # confirms there is no remaining caller of this route.


# ──────────────────────────────────────────────────────────
# Application Factory
# ──────────────────────────────────────────────────────────
def create_app(testing: bool = False) -> Flask:
    """Create and configure the Flask application instance."""
    app = Flask(__name__, template_folder="../templates", static_folder="../../static")
    _configure_app(app, testing)
    limiter = _init_extensions(app, testing)
    # Flask-Limiter's disabled test wrapper keeps only a weak reference.
    # Retain the extension for the lifetime of the application factory result.
    app.config["_LIMITER_INSTANCE"] = limiter
    _initialize_services(app, testing)
    _register_routes(app, limiter)
    return app


# ──────────────────────────────────────────────────────────
# CLI Entry Point
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    is_testing_mode = os.getenv("FLASK_TESTING", "false").lower() == "true"
    flask_app = create_app(testing=is_testing_mode)

    is_debug_mode = config.is_debug() and not is_testing_mode
    server_host = config.get("server", "host", "0.0.0.0")
    server_port = int(config.get("server", "port", 5000))

    if is_debug_mode:
        logger.warning("Flask is running in DEBUG MODE. Not for production deployment.")
    else:
        logger.info("Flask is running in production configuration.")

    flask_app.run(debug=is_debug_mode, host=server_host, port=server_port)
