"""
SFDA Copilot – Flask application entry-point
Final optimized version combining robust patterns, modern syntax, and maximum readability.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
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
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

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
from web.services.openai_app import OpenAIHandler
from web.services.search_engine import ImprovedSearchEngine, SearchResult
from web.utils.config_loader import config
from web.utils.supabase_client import get_supabase

# ──────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────
MAX_SESSION_CHAT_HISTORY_CHARS = 3_500
DEFAULT_MAX_CHAT_MESSAGES_COUNT = 5
ALLOWED_CHAT_CATEGORIES = {"all", "regulatory", "pharmacovigilance", "veterinary", "biological"}

PHARMA_TERMS_EXPANSION: Dict[str, List[str]] = {
    "side effects": ["adverse events", "adverse reactions", "safety concerns", "undesirable effects"],
    "dosage": ["dose", "administration", "regimen", "dosing schedule", "posology"],
    "safety": ["toxicity", "contraindications", "warnings", "precautions", "safety profile"],
    "monitoring": ["surveillance", "observation", "follow-up", "patient monitoring", "safety monitoring"],
    "reporting": ["notification", "documentation", "submission", "adverse event reporting", "case reporting"],
    "signal": ["alert", "indication", "warning signal", "safety signal", "potential risk"],
    "risk": ["hazard", "danger", "exposure", "potential harm", "risk factor"],
    "risk management": ["risk mitigation", "risk assessment", "risk control", "risk evaluation", "RMP", "risk management plan"],
    "audit": ["compliance review", "internal audit", "regulatory audit", "process audit", "inspection readiness"],
    "inspection": ["site visit", "regulatory inspection", "compliance check", "audit review", "facility inspection"],
    "compliance": ["adherence", "conformity", "obedience", "compliance monitoring", "regulatory compliance"],
    "pv": ["pharmacovigilance", "drug safety", "medicine surveillance", "post-marketing safety"],
    "lack of efficacy": ["ineffectiveness", "insufficient response", "suboptimal efficacy", "treatment failure"],
    "quality": ["good manufacturing practices", "GMP", "quality control", "QC", "quality assurance", "QA", "product quality"],
    "adverse event": ["adverse reaction", "side effect", "negative reaction", "AE", "ADR", "undesired effect"],
    "clinical trial": ["clinical study", "clinical research", "clinical investigation", "interventional study", "trial protocol"],
    "drug interaction": ["medication interaction", "pharmaceutical interaction", "medicine interaction", "DDI"],
    "registration": ["marketing authorization", "MA", "drug approval", "product license", "registration process"],
    "labeling": ["SPC", "summary of product characteristics", "PIL", "patient information leaflet", "product label", "package insert"],
    "variation": ["post-approval change", "variation application", "label update", "manufacturing change"],
    "gmp": ["good manufacturing practices", "manufacturing standards", "quality systems", "facility compliance"],
    "gvp": ["good pharmacovigilance practices", "pv system", "pharmacovigilance guidelines", "drug safety standards"],
}

# ──────────────────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────────────────
def preprocess_query(query: str) -> str:
    """Expand the query with pharmaceutical synonyms based on exact word boundaries."""
    expanded_terms = set()
    query_lower = query.lower()
    for term, related_terms in PHARMA_TERMS_EXPANSION.items():
        if re.search(rf"\b{re.escape(term)}\b", query_lower):
            expanded_terms.update(related_terms)

    if not expanded_terms:
        return query

    processed_query = f"{query} {' '.join(expanded_terms)}"
    logging.info("Query expanded: %s -> %s", query, processed_query)
    return processed_query


def _get_token_from_request() -> Optional[str]:
    """Return a Supabase JWT from Bearer header, cookie, or session."""
    if auth_header := request.headers.get("Authorization"):
        return auth_header.split("Bearer ")[-1] if auth_header.startswith("Bearer ") else auth_header
    return request.cookies.get("sb-access-token") or session.get("supabase_access_token")


def _handle_unauthorized(is_page_request: bool) -> Response:
    """Redirect for page requests or return a JSON error for API requests."""
    clear_auth_session()
    if is_page_request:
        return redirect(url_for("index"))
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
        is_page_request = request.method == "GET" and request.endpoint in {"chat_page", "index"}

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
    app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.urandom(24)
    if not os.getenv("FLASK_SECRET_KEY") and not testing:
        logging.warning("Using a temporary secret key. Set FLASK_SECRET_KEY in .env for production.")

    app.config.update(
        TESTING=testing,
        MAX_CHAT_HISTORY_MESSAGE_PAIRS=config.get("server", "chat_history_length", DEFAULT_MAX_CHAT_MESSAGES_COUNT),
    )
    if testing:
        app.config.update(SERVER_NAME="localhost")


def _init_extensions(app: Flask, testing: bool) -> Limiter:
    """Initialize all Flask extensions."""
    # CORS
    is_debug_mode = config.get("server", "debug", True) or testing
    if is_debug_mode:
        CORS(app, supports_credentials=True)
        logging.info("CORS initialized in debug mode (all origins allowed).")
    else:
        origins = config.get("server", "allowed_origins", [])
        CORS(app, origins=origins, supports_credentials=True)
        logging.info("CORS initialized for specific origins: %s", origins)

    # Talisman (Security Headers)
    csp = {
        "default-src": ["'self'"],
        "script-src": ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://cdn.lordicon.com", "https://cdnjs.cloudflare.com"],
        "style-src": ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com"],
        "img-src": ["'self'", "data:"],
        "font-src": ["'self'", "https://cdn.jsdelivr.net"],
        "connect-src": ["'self'", "https://*.supabase.co", "https://cdn.lordicon.com"],
    }
    if project_ref := os.getenv("SUPABASE_PROJECT_REF"):
        csp["connect-src"].append(f"wss://{project_ref}.supabase.co")
    Talisman(app, force_https=not testing, content_security_policy=csp)
    logging.info("Talisman initialized. force_https=%s", not testing)

    # Rate Limiter
    rate_limit_config = config.get("server", "rate_limit", {})
    default_limits = [
        f"{rate_limit_config.get('per_day', 200)} per day",
        f"{rate_limit_config.get('per_hour', 50)} per hour",
        f"{rate_limit_config.get('per_minute', 10)} per minute",
    ]
    limiter = Limiter(get_remote_address, app=app, default_limits=default_limits, storage_uri="memory://")
    logging.info("Flask-Limiter initialized with limits: %s", default_limits)
    return limiter


def _initialize_services(app: Flask, testing: bool) -> None:
    """Attach search engine and LLM handlers to the app config."""
    if testing:
        from unittest.mock import MagicMock
        app.config["openai_handler"] = MagicMock(spec=OpenAIHandler)
        app.config["search_engine"] = MagicMock(spec=ImprovedSearchEngine, is_initialized=lambda: True)
        logging.info("Mock services registered for testing.")
        return

    app.config["openai_handler"] = OpenAIHandler()
    app.config["search_engine"] = ImprovedSearchEngine()
    if not app.config["search_engine"].is_initialized():
        try:
            app.config["search_engine"].initialize()
            logging.info("Search engine initialized successfully.")
        except Exception as e:
            logging.error("Search engine initialization failed: %s", e, exc_info=True)


def _load_faq_data() -> Dict[str, Any]:
    """Load FAQ data from YAML file."""
    faq_path = PROJECT_ROOT / "faq.yaml"
    try:
        with faq_path.open("r", encoding="utf-8") as f:
            faq_data = yaml.safe_load(f)
        logging.info("FAQ data loaded successfully with %d categories.", len(faq_data or {}))
        return faq_data or {}
    except FileNotFoundError:
        logging.error("faq.yaml not found. FAQ feature will be disabled.")
    except Exception as e:
        logging.error("Error parsing faq.yaml: %s", e)
    return {}


def _register_routes(app: Flask, limiter: Limiter) -> None:
    """Register all application routes and blueprints."""
    app.config["FREQUENT_QUESTIONS"] = _load_faq_data()
    app.register_blueprint(auth_bp, url_prefix="/auth")

    @app.route("/")
    def index():
        return render_template(
            "index.html",
            SUPABASE_URL=os.getenv("SUPABASE_URL"),
            SUPABASE_ANON_KEY=os.getenv("SUPABASE_ANON_KEY"),
            is_authenticated=bool(session.get("user_email")),
            user_email=session.get("user_email"),
        )

    @app.route("/api/frequent-questions")
    def get_frequent_questions() -> Response:
        return jsonify(current_app.config["FREQUENT_QUESTIONS"])

    @app.route("/api/chat", methods=["POST"])
    @auth_required
    @limiter.limit(lambda: config.get("server", "rate_limit", {}).get("chat_api", "10 per minute"))
    def handle_chat() -> Response:
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

            processed_query = preprocess_query(query)
            search_results: List[SearchResult] = search_engine.search(processed_query, category)
            llm_context = [{"text": r.text, "document": r.document, "category": r.category, "page": r.page} for r in search_results]

            openai_handler: OpenAIHandler = current_app.config["openai_handler"]
            chat_history = session.get("chat_history", [])
            answer = openai_handler.generate_response(query, llm_context, category, chat_history)

            chat_history.extend([{"role": "user", "content": query}, {"role": "assistant", "content": answer}])
            session["chat_history"] = _truncate_chat_history(chat_history, current_app.config["MAX_CHAT_HISTORY_MESSAGE_PAIRS"], MAX_SESSION_CHAT_HISTORY_CHARS)
            
            return jsonify(response=answer)

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
    _initialize_services(app, testing)
    _register_routes(app, limiter)
    return app


# ──────────────────────────────────────────────────────────
# CLI Entry Point
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    is_testing_mode = os.getenv("FLASK_TESTING", "false").lower() == "true"
    flask_app = create_app(testing=is_testing_mode)

    is_debug_mode = config.get("server", "debug", True) and not is_testing_mode
    server_host = config.get("server", "host", "0.0.0.0")
    server_port = int(config.get("server", "port", 5000))

    if is_debug_mode:
        logging.warning("Flask is running in DEBUG MODE. Not for production deployment.")
    else:
        logging.info("Flask is running in production configuration.")

    flask_app.run(debug=is_debug_mode, host=server_host, port=server_port)
