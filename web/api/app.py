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

import logging
import re
import sys
import uuid
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple, cast, Sequence, Callable # Added Callable
from logging.handlers import RotatingFileHandler # New import for logging
from werkzeug.middleware.proxy_fix import ProxyFix  # For reverse proxy support

import yaml
from dotenv import load_dotenv
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

# ──────────────────────────────────────────────────────────
# Project Path & Environment Setup
# ──────────────────────────────────────────────────────────
# Use pathlib for modern, object-oriented path handling
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DOTENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=DOTENV_PATH, override=True)
logging.info("Loaded .env from %s", DOTENV_PATH)

# ──────────────────────────────────────────────────────────
# Logging Configuration
# ──────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Configure a root logger if not already configured
# This ensures all logs, including those from openai_app, are handled
if not logging.getLogger().handlers:
    logging.basicConfig(level=LOG_LEVEL,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Explicitly set the level for the openai_app logger to INFO
logging.getLogger('web.services.openai_app').setLevel(logging.INFO)

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

# ──────────────────────────────────────────────────────────
# Application-Specific Imports (after logger setup)
# ──────────────────────────────────────────────────────────
from web.api.auth import (
    IDENTITY_MARKER_KEYS,
    auth_bp,
    purge_conversation_state,
    rotate_session_for_new_identity,
)
from web.services.admin_store import resolve_identity_flags
from web.services.identity_cache import IdentityFlags, IdentityFlagsCache
from web.services.citations import (
    build_source_payload,
    extract_cited_indices,
    normalize_legacy_citations,
)
from web.services.conversation_store import ConversationStore
from web.services.openai_app import OpenAIHandler
from web.services.sse import sse, sse_headers
from web.services.search_engine import ImprovedSearchEngine, SearchResult
from web.services.search_exceptions import ManifestValidationError, SearchEngineError
from web.utils.config_loader import config
from web.utils.icons import CATEGORY_ICONS, icon, runtime_icons
from web.utils.i18n import (
    load_catalog,
    make_translator,
    normalize_lang,
    pick_lang,
    runtime_subset,
    text_direction,
)
from web.utils.supabase_client import get_supabase

# ──────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────
MAX_SESSION_CHAT_HISTORY_CHARS = 3_500
DEFAULT_MAX_CHAT_MESSAGES_COUNT = 5
ALLOWED_CHAT_CATEGORIES = {"all", "regulatory", "pharmacovigilance", "veterinary", "biological"}
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
ASSET_VERSION = "warm15"

# Product release, rendered in the landing footer. Kept as one constant so
# the number cannot drift between the page and the module headers.
APP_VERSION = "3.0.0"

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
MODULE_FILENAMES: Tuple[str, ...] = tuple(
    sorted(p.name for p in (PROJECT_ROOT / "static" / "js" / "modules").glob("*.js"))
)

# ──────────────────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────────────────


def _get_token_from_request() -> Optional[str]:
    """Return a Supabase JWT from Bearer header, cookie, or session."""
    if auth_header := request.headers.get("Authorization"):
        return auth_header.split("Bearer ")[-1] if auth_header.startswith("Bearer ") else auth_header
    return request.cookies.get("sb-access-token") or session.get("supabase_access_token")


def _handle_unauthorized(is_page_request: bool) -> Union[Response, Tuple[Response, int]]:
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
    """Tie the conversation in this cookie to one authenticated reader.

    The belt to the logout route's braces. Logout is the *cooperative* path and
    plenty of real endings skip it: a closed tab, an expired refresh token, a
    revoked session, a client that never called it. Any of those leaves a valid
    Flask cookie carrying the previous reader's `conv_id`, and the next person
    to sign in on that browser would have inherited their history.

    So identity is checked on every authenticated request rather than trusted
    to have been cleaned up on the way out. A change means a different person
    is holding this cookie, and their conversation starts empty.
    """
    previous = session.get("auth_identity")
    if previous is not None and previous != identity:
        rotate_session_for_new_identity()
        logging.info("Authenticated identity changed for this session; conversation purged.")
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
_TESTING_IDENTITIES: Tuple[Tuple[str, IdentityFlags], ...] = (
    (
        "fake_admin_token",
        IdentityFlags("test-admin-id", "admin@example.com", "admin", "internal", False),
    ),
    (
        "fake_disabled_token",
        IdentityFlags("test-disabled-id", "disabled@example.com", "user", "free", True),
    ),
    (
        "fake_token",
        IdentityFlags("test-user-id", "test@example.com", "user", "free", False),
    ),
)


def _testing_identity() -> Optional[IdentityFlags]:
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
    return request.endpoint == "index" or request.blueprint == "admin"


def _account_disabled_response() -> Tuple[Response, int]:
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


def _authenticate_request() -> Tuple[Optional[IdentityFlags], Optional[Any]]:
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

        try:
            supabase = get_supabase()
            response = supabase.auth.get_user(token)
            # Robustly get the user object, which might be nested differently
            user = getattr(response, "user", None) or getattr(getattr(response, "data", None), "user", None)

            if not user:
                logging.warning("Token validation failed for %s – no user found.", request.endpoint)
                return None, _handle_unauthorized(_is_page_request())

            # The user id is the stable identity; email can be changed by the
            # account holder and is only a fallback for a provider that omits it.
            user_id = str(getattr(user, "id", None) or user.email)
            identity = resolve_identity_flags(
                current_app.config["identity_flags"], user_id, user.email
            )
        except Exception as exception:
            logging.error("Authentication error at endpoint %s: %s", request.endpoint, exception, exc_info=True)
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


def _resolve_and_adopt(
    store: ConversationStore, existing_id: Optional[str], legacy_history: Optional[List[Dict[str, str]]]
) -> Optional[str]:
    """Return the id this content lives under, adopting it into the store.

    Mints an id for cookie-only legacy content that predates `conv_id` (a
    reader who reset, or who used only the blocking chat path, before
    history moved server-side) so it isn't left stranded in the cookie.
    Returns None if there's neither an id nor legacy content to adopt.

    If `existing_id` already has its own store entry, `adopt_cookie_history`
    is a no-op — the store wins over orphaned cookie content rather than
    attempting a merge, since the two could only exist if a reader used both
    the blocking and streaming paths before this migration unified them, and
    there's no principled way to reconcile histories that were already
    inconsistent with each other.
    """
    resolved = existing_id or (uuid.uuid4().hex if legacy_history else None)
    if resolved:
        store.adopt_cookie_history(resolved, legacy_history)
    return resolved


def _migrate_legacy_undo_history(store: ConversationStore) -> None:
    """Move a pre-migration `prev_chat_history` out of the cookie on the next
    chat request, whichever route it lands on.

    `handle_conversation_reset`'s `undo` branch already adopts this, but only
    if the reader actually presses Undo. Without this, a reader who reset
    once on the old blocking implementation and then just kept asking
    questions — never touching Undo, Forget, or another reset — would have
    their old set-aside history keep riding the signed cookie on every
    request indefinitely, which is exactly the cookie-size failure this
    migration exists to close. Called at the top of both chat routes; a
    no-op for every session created after this migration shipped.
    """
    legacy = session.pop("prev_chat_history", None)
    if legacy is None:
        return
    if prev_id := _resolve_and_adopt(store, session.get("prev_conv_id"), legacy):
        session["prev_conv_id"] = prev_id


# ──────────────────────────────────────────────────────────
# Flask Application Factory Components
# ──────────────────────────────────────────────────────────
def _configure_app(app: Flask, testing: bool) -> None:
    """Apply basic configuration and secret key to the Flask app."""
    app.secret_key = config.flask_secret_key or os.urandom(24)
    if not config.flask_secret_key and not testing:
        logging.warning("Using a temporary secret key. Set FLASK_SECRET_KEY in .env for production.")

    app.config.update(
        TESTING=testing,
        RATELIMIT_ENABLED=not testing,
        MAX_CHAT_HISTORY_MESSAGE_PAIRS=config.get("server", "chat_history_length", DEFAULT_MAX_CHAT_MESSAGES_COUNT),
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
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=1,       # Trust X-Forwarded-For (1 proxy hop)
            x_proto=1,     # Trust X-Forwarded-Proto
            x_host=1,      # Trust X-Forwarded-Host
            x_prefix=1     # Trust X-Forwarded-Prefix
        )
        logging.info("ProxyFix middleware enabled for reverse proxy deployment.")
    
    # CORS
    is_debug_mode = config.is_debug() or testing
    if is_debug_mode:
        CORS(app, supports_credentials=True)
        logging.info("CORS initialized in debug mode (all origins allowed).")
    else:
        origins = config.get("server", "allowed_origins", [])
        CORS(app, origins=origins, supports_credentials=True)
        logging.info("CORS initialized for specific origins: %s", origins)

    # Talisman (Security Headers)
    # Build connect-src list for Supabase
    connect_src = ["'self'", "https://*.supabase.co", "https://cdn.lordicon.com", "https://cdn.jsdelivr.net"]
    
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
        "script-src": ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://cdn.lordicon.com", "https://cdnjs.cloudflare.com"] + impeccable_live_dev,
        "style-src": ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com", "https://fonts.googleapis.com"],
        "img-src": ["'self'", "data:", "https:"],
        "font-src": ["'self'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com", "data:", "https://fonts.gstatic.com", "https://r2cdn.perplexity.ai"],
        "connect-src": connect_src + impeccable_live_dev,
    }
    
    # In debug mode, be more permissive for development (allows browser extensions)
    if is_debug_mode:
        # Allow fonts from any HTTPS source (for browser extensions like Perplexity)
        csp["font-src"] = ["'self'", "https:", "data:"]
        # Allow connections to any HTTPS/WSS (for development and browser extensions)
        csp["connect-src"] = ["'self'", "https:", "wss:"] + impeccable_live_dev
        logging.info("CSP configured in permissive debug mode for development")
    
    # Disable force_https when:
    # 1. Debug mode (local development)
    # 2. Testing mode
    # 3. Behind a reverse proxy (Nginx handles SSL termination)
    should_force_https = not (is_debug_mode or testing or is_behind_proxy)
    
    Talisman(
        app,
        force_https=should_force_https,
        content_security_policy=csp
    )
    logging.info(
        "Talisman initialized. force_https=%s (debug=%s, testing=%s, behind_proxy=%s)",
        should_force_https, is_debug_mode, testing, is_behind_proxy
    )

    # Rate Limiter
    rate_limit_config = config.get("server", "rate_limit", {})
    default_limits: List[Union[str, Callable[[], str]]] = [
        f"{rate_limit_config.get('per_day', 200)} per day",
        f"{rate_limit_config.get('per_hour', 50)} per hour",
        f"{rate_limit_config.get('per_minute', 10)} per minute",
    ]
    limiter = Limiter(get_remote_address, app=app, default_limits=default_limits, storage_uri="memory://")
    logging.info("Flask-Limiter initialized with limits: %s", default_limits)
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
        for token in _re.findall(r"\S+\s*", demo_answer):
            yield token

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
            score=score, document=name, category=category, page=page,
            chunk_id=f"{name}_p{page}_1",
            metadata={"semantic_score": semantic, "lexical_score": lexical},
        )
        for name, page, category, score, semantic, lexical in documents
    ]

    search_engine = MagicMock(spec=ImprovedSearchEngine, is_initialized=lambda: True)
    search_engine.search.return_value = demo_results

    app.config["openai_handler"] = handler
    app.config["search_engine"] = search_engine
    logging.info("Mock services registered for testing.")


def _initialize_services(app: Flask, testing: bool) -> None:
    """Attach search engine and LLM handlers to the app config."""
    if testing:
        _register_testing_doubles(app)
        return

    app.config["openai_handler"] = OpenAIHandler()
    try:
        search_engine = ImprovedSearchEngine()
        app.config["search_engine"] = search_engine
        if not search_engine.is_initialized():
            initialized = search_engine.initialize()
            if initialized:
                logging.info("Search engine initialized successfully.")
            else:
                logging.error(
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
        logging.critical(
            "FATAL: search index manifest validation failed — refusing to "
            "start with a mismatched index. %s", exc,
        )
        raise
    except Exception as e:
        app.config["search_engine"] = None
        logging.error("Search engine initialization failed: %s", e, exc_info=True)


def _load_faq_data() -> Dict[str, Any]:
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
        logging.error("faq.yaml not found. FAQ feature will be disabled.")
        return {}
    except Exception as e:
        logging.error("Error parsing faq.yaml: %s", e)
        return {}

    if not set(faq_data) & set(SUPPORTED_FAQ_LANGS):
        logging.info("faq.yaml is in the legacy flat shape; treating it as English.")
        faq_data = {"en": faq_data}

    logging.info(
        "FAQ data loaded for %s.", ", ".join(sorted(faq_data)) or "no languages"
    )
    return faq_data


def _register_routes(app: Flask, limiter: Limiter) -> None:
    """Register all application routes and blueprints."""
    app.config["FREQUENT_QUESTIONS"] = _load_faq_data()
    app.config["conversations"] = ConversationStore()
    # Process-local, same scope contract as ConversationStore above: a cache,
    # never the authority. The database decides who is an administrator.
    app.config["identity_flags"] = IdentityFlagsCache()
    app.register_blueprint(auth_bp, url_prefix="/auth")

    workers = os.getenv("WEB_CONCURRENCY", "1")
    if workers != "1":
        logging.warning(
            "WEB_CONCURRENCY=%s but ConversationStore is process-local — conversations "
            "will split across workers and users will randomly lose context. This app "
            "must run single-worker anyway (in-RAM FAISS index); use --workers 1 --threads 8.",
            workers,
        )

    @app.context_processor
    def inject_template_globals() -> Dict[str, Any]:
        # `icon` and `category_icon` are globals rather than a Jinja import so
        # partials get them without every caller remembering `with context`.
        return {
            "asset_version": ASSET_VERSION,
            "app_version": APP_VERSION,
            "icon": icon,
            "category_icon": lambda key: CATEGORY_ICONS.get(key, "globe"),
        }

    @app.route("/")
    def index():
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_anon_key = os.getenv("SUPABASE_ANON_KEY")

        # Validate Supabase configuration
        if not supabase_url or not supabase_anon_key:
            logging.warning(
                "Supabase configuration missing: URL=%s, Key=%s",
                "present" if supabase_url else "missing",
                "present" if supabase_anon_key else "missing"
            )

        # Rendering the page strings server-side means an Arabic reader never
        # sees a flash of English while the JS boots.
        lang = pick_lang(request)
        catalog = load_catalog(lang)

        response = make_response(render_template(
            "index.html",
            SUPABASE_URL=supabase_url or "",
            SUPABASE_ANON_KEY=supabase_anon_key or "",
            is_authenticated=bool(session.get("user_email")),
            user_email=session.get("user_email"),
            lang=lang,
            text_dir=text_direction(lang),
            t=make_translator(catalog),
            i18n_runtime=runtime_subset(catalog),
            icons_runtime=runtime_icons(),
            # The one category->glyph mapping, shared with the browser rather
            # than restated there. DESIGN.md: the same mapping written down
            # twice is the same mapping drifting eventually.
            category_icons=CATEGORY_ICONS,
            module_import_map={
                "imports": {
                    url_for("static", filename=f"js/modules/{name}"):
                    url_for("static", filename=f"js/modules/{name}", v=ASSET_VERSION)
                    for name in MODULE_FILENAMES
                }
            },
        ))
        # Persist an explicit ?lang= so the choice survives the next visit.
        if request.args.get("lang"):
            response.set_cookie(
                "lang", lang, max_age=31_536_000, samesite="Lax", path="/"
            )
        return response

    @app.route("/favicon.ico")
    def favicon() -> Response:
        return send_from_directory(app.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon")

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
        other accounts, no counts, no settings.
        """
        flags: IdentityFlags = g.identity
        return jsonify({
            "user_id": flags.user_id,
            "email": flags.email,
            "role": flags.role,
            "tier": flags.tier,
            "is_admin": flags.is_admin,
        })

    # Shared across both chat routes so a client cannot double its allowance by
    # alternating between the streaming and blocking endpoints.
    chat_limit = limiter.shared_limit(
        lambda: config.get("server", "rate_limit", {}).get("chat_api", "10 per minute"),
        scope="chat",
    )

    def _validate_chat_request() -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[Response, int]]]:
        """Parse and validate a chat payload. Returns (payload, error_response)."""
        body = request.get_json(force=True, silent=True) or {}
        query = (body.get("query") or "").strip()
        category = (body.get("category") or "all").lower()
        lang = (body.get("lang") or "en").lower()

        if not query:
            return None, (jsonify(error="Query cannot be empty"), 400)
        if category not in ALLOWED_CHAT_CATEGORIES:
            return None, (
                jsonify(error=f"Invalid category. Allowed: {', '.join(ALLOWED_CHAT_CATEGORIES)}"),
                400,
            )

        engine = current_app.config.get("search_engine")
        if not engine or not engine.is_initialized():
            logging.error("Search engine unavailable for chat request.")
            return None, (jsonify(error="Search service is currently unavailable."), 503)

        return {
            "query": query,
            "category": category,
            "lang": lang if lang in ("en", "ar") else "en",
            "engine": engine,
        }, None

    @app.route("/api/chat/stream", methods=["POST"])
    @auth_required
    @chat_limit
    def handle_chat_stream() -> Union[Response, Tuple[Response, int]]:
        payload, error = _validate_chat_request()
        if error:
            return error

        query, category, lang = payload["query"], payload["category"], payload["lang"]
        engine = payload["engine"]
        handler: OpenAIHandler = current_app.config["openai_handler"]
        store: ConversationStore = current_app.config["conversations"]
        max_pairs = current_app.config["MAX_CHAT_HISTORY_MESSAGE_PAIRS"]

        # ── Every session touch happens HERE, in the view body. ──
        # Flask writes Set-Cookie in finalize_request(), which runs after this
        # function returns but before the WSGI server iterates the generator
        # below, so a session write inside generate() would be silently dropped.
        _migrate_legacy_undo_history(store)
        conversation_id = session.get("conv_id")
        if not conversation_id:
            conversation_id = uuid.uuid4().hex
            session["conv_id"] = conversation_id
        store.adopt_cookie_history(conversation_id, session.pop("chat_history", None))
        history = store.get(conversation_id)

        def generate():
            try:
                yield sse("meta", {
                    "conversation_id": conversation_id,
                    "category": category,
                    "lang": lang,
                    "model": getattr(handler, "model", "unknown"),
                })
                yield sse("stage", {"stage": "searching"})

                results = engine.search(query, category)
                retrieved = build_source_payload(results, limit=handler.max_context_results)
                yield sse("stage", {"stage": "retrieved", "count": len(retrieved)})

                # No "sources" frame here any more. It used to be emitted at
                # this point — before the model had been called — so the deck
                # could not reflect what the answer did with the passages, and
                # a refusal arrived with eight source cards attached. What the
                # reader gets mid-stream is the count above; the passages
                # themselves ride on "final", once there is an answer to judge
                # them against.
                llm_context = [
                    {"text": r.text, "document": r.document, "category": r.category, "page": r.page}
                    for r in results
                ]

                yield sse("stage", {"stage": "drafting"})
                parts: List[str] = []
                for token in handler.stream_response(query, llm_context, category, history, lang=lang):
                    parts.append(token)
                    yield sse("delta", {"t": token})

                answer = normalize_legacy_citations("".join(parts).strip(), retrieved)
                cited = extract_cited_indices(answer, retrieved)
                sources = [s for s in retrieved if s["index"] in cited]

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
                yield sse("final", {
                    "response": answer,
                    "sources": sources,
                    "cited": cited,
                    "retrieved": len(retrieved),
                })

                yield sse("suggestions", {
                    "suggested_questions": handler.generate_suggestions(query, answer, lang=lang),
                })

                store.append_turn(conversation_id, query, answer, max_pairs, MAX_SESSION_CHAT_HISTORY_CHARS)
                yield sse("done", {"finish_reason": "stop", "chars": len(answer)})

            except GeneratorExit:
                # Client disconnected (cancelled or navigated away). Re-raising
                # lets stream_response's context manager close the upstream
                # connection, and skips append_turn so a cancelled turn is
                # correctly not recorded in history.
                logging.info("Client disconnected mid-stream (conv=%s)", conversation_id)
                raise
            except SearchEngineError:
                # Retrieval failed. Reported as its own code rather than folded
                # into "internal", because the alternative — treating it as an
                # empty result set — would render as a confident refusal.
                logging.error("Retrieval failed (conv=%s)", conversation_id, exc_info=True)
                yield sse("error", {
                    "error": "Search service is currently unavailable.",
                    "code": "search_unavailable",
                })
            except Exception:
                logging.error("Streaming chat failed (conv=%s)", conversation_id, exc_info=True)
                # The 200 status line is already sent, so failures after the
                # first yield can only be reported in-band.
                yield sse("error", {"error": "An internal server error occurred.", "code": "internal"})

        response = Response(stream_with_context(generate()), mimetype="text/event-stream")
        sse_headers(response)
        return response

    @app.route("/api/chat", methods=["POST"])
    @auth_required
    @chat_limit
    def handle_chat() -> Union[Response, Tuple[Response, int]]:
        try:
            payload = request.get_json(force=True)
            query = payload.get("query", "").strip()
            category = payload.get("category", "all").lower()
            # Was never read, so an Arabic reader on a browser without
            # streaming bodies got an English answer while the streaming path
            # answered in Arabic.
            lang = (payload.get("lang") or "en").lower()
            if lang not in ("en", "ar"):
                lang = "en"

            if not query:
                return jsonify(error="Query cannot be empty"), 400
            if category not in ALLOWED_CHAT_CATEGORIES:
                return jsonify(error=f"Invalid category. Allowed: {', '.join(ALLOWED_CHAT_CATEGORIES)}"), 400

            search_engine: ImprovedSearchEngine = current_app.config["search_engine"]
            if not search_engine or not search_engine.is_initialized():
                logging.error("Search engine unavailable for chat request.")
                return jsonify(error="Search service is currently unavailable."), 503

            search_results: List[SearchResult] = search_engine.search(query, category)
            llm_context = [{"text": r.text, "document": r.document, "category": r.category, "page": r.page} for r in search_results]

            openai_handler: OpenAIHandler = current_app.config["openai_handler"]
            # retrieved[i] must be the same passage as prompt block [i], so both
            # are cut to the same limit.
            retrieved = build_source_payload(search_results, limit=openai_handler.max_context_results)

            store: ConversationStore = current_app.config["conversations"]
            max_pairs = current_app.config["MAX_CHAT_HISTORY_MESSAGE_PAIRS"]

            # Same pattern the streaming route uses (see its comment there):
            # get/create conv_id up front, one-time-migrate any pre-deploy
            # cookie history into the store under it. No "asking ends the
            # undo" step here — that was a cookie-byte safety rule (a history
            # in the cookie could double the session's size against a ~4KB
            # limit), not a UX decision, and it doesn't apply once history
            # never touches the cookie. Keeping it would also diverge from
            # the streaming route, which has never ended the undo on a new
            # question — asking here now behaves the same way asking there
            # always has.
            _migrate_legacy_undo_history(store)
            conversation_id = session.get("conv_id")
            if not conversation_id:
                conversation_id = uuid.uuid4().hex
                session["conv_id"] = conversation_id
            store.adopt_cookie_history(conversation_id, session.pop("chat_history", None))

            chat_history = store.get(conversation_id)
            answer, suggested_questions = openai_handler.generate_response(
                query, llm_context, category, chat_history, lang=lang,
            )
            answer = normalize_legacy_citations(answer, retrieved)

            # Same contract as the streaming path's "final" frame — see the
            # comment there. `sources` is strictly what the answer cited.
            cited = extract_cited_indices(answer, retrieved)
            sources = [s for s in retrieved if s["index"] in cited]

            store.append_turn(conversation_id, query, answer, max_pairs, MAX_SESSION_CHAT_HISTORY_CHARS)

            return jsonify(
                response=answer,
                suggested_questions=suggested_questions,
                sources=sources,
                cited=cited,
                retrieved=len(retrieved),
            )

        except SearchEngineError:
            logging.error("Retrieval failed in /api/chat", exc_info=True)
            return jsonify(error="Search service is currently unavailable."), 503

        except Exception as exception:
            logging.error("Unhandled error in /api/chat: %s", exception, exc_info=True)
            return jsonify(error="An internal server error occurred."), 500

    @app.route("/api/conversation/reset", methods=["POST"])
    @auth_required
    @limiter.limit(
        lambda: config.get("server", "rate_limit", {}).get("reset_api", "30 per minute")
    )
    def handle_conversation_reset() -> Union[Response, Tuple[Response, int]]:
        """End the current conversation without ending the session.

        Reset **rotates** `conv_id` rather than deleting its store entry, and the
        distinction is load-bearing twice over.

        First, correctness. `store.append_turn` runs near the end of the streaming
        generator, before the "done" frame; `ConversationStore.clear` is a keyed
        pop with no tombstone. Deleting the entry here would leave a generator
        that is still winding down free to write the old turn straight back under
        the same id — so whether a reset held would depend on whether the client's
        disconnect beat one line of server code. Rotating means a late append
        lands on an id nothing will ever read again, and the reset holds
        regardless of timing.

        Second, undo. Because the old conversation is set aside rather than
        destroyed, undo can restore what the *model* remembers and not merely what
        the screen shows. A transcript that came back over a server that had
        forgotten it would be the kind of half-truth this product's own citations
        rule exists to prevent.

        The set-aside conversation is dropped on the next reset, on `forget`, on
        logout (`purge_conversation_state`), or by the store's TTL — whichever
        comes first.

        Both `/api/chat` and `/api/chat/stream` keep their history in the same
        `ConversationStore`, keyed by `conv_id`, so this rotation covers both
        paths uniformly — there is nothing path-specific left to rotate.
        `chat_history` / `prev_chat_history` are no longer written by either
        route; `_resolve_and_adopt` below only exists to adopt a pre-migration
        cookie's leftover history into the store under the id being restored
        or rotated away, so a session that predates this migration does not
        lose or strand content — it is a no-op for every session created
        after this migration shipped.
        """
        payload = request.get_json(silent=True) or {}
        store: ConversationStore = current_app.config["conversations"]

        if payload.get("undo"):
            restored = _resolve_and_adopt(
                store, session.pop("prev_conv_id", None), session.pop("prev_chat_history", None)
            )
            if restored:
                # The empty conversation the reset started. Nothing has read it
                # — undo is torn down client-side before a new question is sent
                # — but it is this session's litter either way.
                if current := session.get("conv_id"):
                    store.clear(current)
                session["conv_id"] = restored

            # Nothing set aside is a no-op, NOT an error: a reader whose first
            # question never reached the server has a transcript to restore and
            # no server history to go with it, and the two are still consistent
            # afterwards because there was nothing to be inconsistent about.
            # Reporting that as a failure would leave their turns discarded.
            return jsonify(
                ok=True,
                restored=bool(restored),
                conversation_id=session.get("conv_id"),
            )

        if payload.get("forget"):
            if stale := session.pop("prev_conv_id", None):
                store.clear(stale)
            session.pop("prev_chat_history", None)
            return jsonify(ok=True, conversation_id=session.get("conv_id"))

        # A reset while an earlier one is still undoable: that older conversation
        # is now unreachable by any route, so it goes now rather than waiting for
        # the TTL.
        if stale := session.pop("prev_conv_id", None):
            store.clear(stale)
        session.pop("prev_chat_history", None)

        # Usually just conv_id — but a pre-migration session may instead (or
        # also) be carrying its live history as session["chat_history"], with
        # no conv_id at all (a reader who only ever used the blocking path
        # before this migration). _resolve_and_adopt mints an id for that
        # legacy content so it rotates into prev_conv_id like everything
        # else, rather than sitting inert in the cookie until some later
        # request silently resurrects it under an unrelated conversation.
        previous = _resolve_and_adopt(store, session.get("conv_id"), session.pop("chat_history", None))
        if previous:
            session["prev_conv_id"] = previous

        conversation_id = uuid.uuid4().hex
        session["conv_id"] = conversation_id
        return jsonify(ok=True, conversation_id=conversation_id)


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
        logging.warning("Flask is running in DEBUG MODE. Not for production deployment.")
    else:
        logging.info("Flask is running in production configuration.")

    flask_app.run(debug=is_debug_mode, host=server_host, port=server_port)
