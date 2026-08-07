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

import json
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
from web.api.auth import auth_bp
from web.services.citations import build_source_payload, normalize_legacy_citations
from web.services.conversation_store import ConversationStore
from web.services.openai_app import OpenAIHandler
from web.services.sse import sse, sse_headers
from web.services.search_engine import ImprovedSearchEngine, SearchResult
from web.services.search_exceptions import ManifestValidationError
from web.utils.config_loader import config
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
ASSET_VERSION = "warm2"

# Product release, rendered in the landing footer. Kept as one constant so
# the number cannot drift between the page and the module headers.
APP_VERSION = "3.0"

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


def auth_required(view_func):
    """Decorator that enforces Supabase authentication for a route."""

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if current_app.config["TESTING"]:
            if "fake_token" in request.headers.get("Authorization", ""):
                session["user_email"] = "test@example.com"
                return view_func(*args, **kwargs)
            return jsonify({"error": "Invalid or missing test token"}), 401

        token = _get_token_from_request()
        is_page_request = request.method == "GET" and request.endpoint == "index"

        if not token:
            return _handle_unauthorized(is_page_request)

        try:
            supabase = get_supabase()
            response = supabase.auth.get_user(token)
            # Robustly get the user object, which might be nested differently
            user = getattr(response, "user", None) or getattr(getattr(response, "data", None), "user", None)

            if not user:
                logging.warning("Token validation failed for %s – no user found.", request.endpoint)
                return _handle_unauthorized(is_page_request)

            session.update({"supabase_access_token": token, "user_email": user.email})
            return view_func(*args, **kwargs)

        except Exception as exception:
            logging.error("Authentication error at endpoint %s: %s", request.endpoint, exception, exc_info=True)
            return _handle_unauthorized(is_page_request)

    return wrapper


def _truncate_chat_history(chat_history: List[Dict[str, str]], max_pairs: int, max_chars: int) -> List[Dict[str, str]]:
    """Trim chat history to max_pairs and max_chars JSON length for the session."""
    # 1. Truncate by message pair count first
    truncated_history = chat_history[-(max_pairs * 2) :]

    # 2. Truncate by character count if still too long, using walrus operator for efficiency
    while truncated_history and len((payload := json.dumps(truncated_history))) > max_chars:
        # Drop the oldest user-assistant pair
        truncated_history = truncated_history[2:]

    return truncated_history


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
        "resident in the Kingdom [3]."
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

    documents = [
        ("2022-10-19_Guidance_for_Submission.pdf", 14, "regulatory", 0.71, 0.63, 0.80),
        ("2021-03-02_GMP_Requirements.pdf", 7, "regulatory", 0.52, 0.59, 0.41),
        ("2023-01-11_Pharmacovigilance_Guideline.pdf", 31, "pharmacovigilance", 0.34, 0.30, 0.37),
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
        return {"asset_version": ASSET_VERSION, "app_version": APP_VERSION}

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
        return jsonify(selected)

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
                sources = build_source_payload(results, limit=handler.max_context_results)
                yield sse("sources", {"sources": sources})
                yield sse("stage", {"stage": "retrieved", "count": len(sources)})

                llm_context = [
                    {"text": r.text, "document": r.document, "category": r.category, "page": r.page}
                    for r in results
                ]

                yield sse("stage", {"stage": "drafting"})
                parts: List[str] = []
                for token in handler.stream_response(query, llm_context, category, history, lang=lang):
                    parts.append(token)
                    yield sse("delta", {"t": token})

                answer = normalize_legacy_citations("".join(parts).strip(), sources)

                yield sse("stage", {"stage": "finalizing"})
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
            # sources[i] must be the same passage as prompt block [i], so both
            # are cut to the same limit.
            sources = build_source_payload(search_results, limit=openai_handler.max_context_results)

            chat_history = session.get("chat_history", [])
            answer, suggested_questions = openai_handler.generate_response(query, llm_context, category, chat_history)
            answer = normalize_legacy_citations(answer, sources)

            chat_history.extend([{"role": "user", "content": query}, {"role": "assistant", "content": answer}])
            session["chat_history"] = _truncate_chat_history(chat_history, current_app.config["MAX_CHAT_HISTORY_MESSAGE_PAIRS"], MAX_SESSION_CHAT_HISTORY_CHARS)

            return jsonify(response=answer, suggested_questions=suggested_questions, sources=sources)

        except Exception as exception:
            logging.error("Unhandled error in /api/chat: %s", exception, exc_info=True)
            return jsonify(error="An internal server error occurred."), 500


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
