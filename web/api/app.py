import logging
import os
import sys
from dotenv import load_dotenv
import json
import re
from functools import wraps
from typing import List, Dict, Any, Tuple, Optional

from flask import Flask, render_template, request, jsonify, current_app, session, redirect, url_for
from flask_limiter import Limiter # Import Limiter class
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_cors import CORS

# --- Project Setup and Environment Loading ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DOTENV_PATH = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=DOTENV_PATH, override=True)
logging.info(f"Attempting to load .env file from: {DOTENV_PATH}")

# --- Logging Configuration ---
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.getLogger('web.services.search_engine').setLevel(os.getenv('LOG_LEVEL_SEARCH_ENGINE', 'DEBUG').upper())
logging.getLogger('web.utils.config_loader').setLevel(os.getenv('LOG_LEVEL_CONFIG_LOADER', 'DEBUG').upper())
logging.getLogger('web.utils.openai_client').setLevel(os.getenv('LOG_LEVEL_OPENAI_CLIENT', 'DEBUG').upper())
logging.getLogger('web.utils.local_embedding_client').setLevel(os.getenv('LOG_LEVEL_EMBEDDING_CLIENT', 'DEBUG').upper())

# --- Application-Specific Imports ---
from web.utils.config_loader import config
from web.services.openai_app import OpenAIHandler
from web.services.search_engine import ImprovedSearchEngine, SearchResult
from web.api.auth import auth_bp
from web.utils.supabase_client import get_supabase

# --- Constants ---
MAX_SESSION_CHAT_HISTORY_CHARS = 3500
DEFAULT_MAX_CHAT_MESSAGES_COUNT = 5
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
    "gvp": ["good pharmacovigilance practices", "pv system", "pharmacovigilance guidelines", "drug safety standards"]
}

# --- Helper Functions ---
def preprocess_query(query: str) -> str:
    """Expands query with relevant pharmaceutical terms using word boundaries."""
    expanded_terms = []
    query_lower = query.lower()
    for term, related_terms in PHARMA_TERMS_EXPANSION.items():
        if re.search(r'\b' + re.escape(term) + r'\b', query_lower):
            expanded_terms.extend(related_terms)
    unique_expanded_terms_str = " ".join(list(set(expanded_terms)))
    if unique_expanded_terms_str:
        processed_query = f"{query} {unique_expanded_terms_str}"
        logging.info(f"Original Query: '{query}', Expanded Query: '{processed_query}'")
        return processed_query
    return query

def _get_token_from_request() -> Optional[str]:
    """Extracts authentication token from request headers, cookies, or session."""
    auth_header = request.headers.get('Authorization')
    if auth_header:
        return auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else auth_header
    if 'sb-access-token' in request.cookies:
        return request.cookies.get('sb-access-token')
    return session.get('supabase_access_token')

def _handle_unauthorized(is_page_request: bool) -> Tuple[Any, int]:
    """Handles unauthorized access by redirecting or returning JSON error."""
    if is_page_request:
        return redirect(url_for('index'))
    return jsonify({'error': 'Authorization required'}), 401

def clear_auth_session():
    """Clears authentication-related data from the session."""
    session.pop('supabase_access_token', None)
    session.pop('user_email', None)

def auth_required(f):
    """Decorator to enforce authentication for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_app.config.get('TESTING'):
            auth_header = request.headers.get('Authorization')
            if auth_header and 'fake_token' in auth_header:
                session['user_email'] = 'test@example.com'
                return f(*args, **kwargs)
            return jsonify({'error': 'Invalid or missing test token'}), 401

        token = _get_token_from_request()
        is_page_request = request.method == 'GET' and request.endpoint in ['chat_page', 'index'] 

        if not token:
            return _handle_unauthorized(is_page_request)

        try:
            supabase = get_supabase()
            response = supabase.auth.get_user(token)
            user = getattr(response, 'user', None) or getattr(getattr(response, 'data', None), 'user', None)

            if not user:
                logging.warning(f"Token validation failed for endpoint {request.endpoint}. User could not be retrieved from token.")
                clear_auth_session()
                return _handle_unauthorized(is_page_request)
            
            session['supabase_access_token'] = token
            session['user_email'] = user.email
            return f(*args, **kwargs)
        
        except Exception as e:
            logging.error(f"Authentication error for endpoint {request.endpoint}: {str(e)}", exc_info=True)
            clear_auth_session()
            return _handle_unauthorized(is_page_request)
    return decorated_function

def _truncate_chat_history(chat_history: List[Dict[str, str]], 
                           max_messages_pairs: int, 
                           max_chars: int) -> List[Dict[str, str]]:
    """Truncates chat history based on message count and total character length."""
    max_total_messages = max_messages_pairs * 2
    if len(chat_history) > max_total_messages:
        chat_history = chat_history[-max_total_messages:]
    
    current_history_json = json.dumps(chat_history)
    while len(current_history_json) > max_chars and len(chat_history) > 1:
        chat_history = chat_history[2:] 
        current_history_json = json.dumps(chat_history)
    
    if len(current_history_json) > max_chars and len(chat_history) > 0: 
        logging.warning(f"Chat history still too long ({len(current_history_json)} chars) after pair truncation, removing oldest entry.")
        chat_history = chat_history[1:] 
        if not chat_history:
             logging.warning("Chat history completely cleared due to size constraints.")
    return chat_history

# --- Flask App Factory Components ---
def _configure_app_settings(app: Flask, testing: bool):
    """Configures basic Flask app settings."""
    app.secret_key = os.getenv('FLASK_SECRET_KEY')
    if not app.secret_key:
        app.secret_key = os.urandom(24) 
        if not testing and config.get("server", "debug", True):
            logging.warning("FLASK_SECRET_KEY not set from environment, using a temporary key. Set this in .env for production.")

    app.config['TESTING'] = testing
    if testing:
        app.config['SERVER_NAME'] = 'localhost' 
        app.config['PREFERRED_URL_SCHEME'] = 'http'
    
    app.config['MAX_CHAT_HISTORY_MESSAGE_PAIRS'] = config.get("server", "chat_history_length", DEFAULT_MAX_CHAT_MESSAGES_COUNT)

def _initialize_extensions(app: Flask, testing: bool):
    """Initializes Flask extensions."""
    is_debug_mode = config.get("server", "debug", True) or testing
    if is_debug_mode:
        CORS(app, supports_credentials=True)
        logging.info("CORS initialized in debug mode (all origins).")
    else:
        allowed_origins = config.get("server", "allowed_origins", [])
        CORS(app, origins=allowed_origins, supports_credentials=True)
        logging.info(f"CORS initialized for origins: {allowed_origins}")

    talisman_force_https = not testing
    Talisman(app, force_https=talisman_force_https, content_security_policy={
        'default-src': ["'self'"],
        'script-src': ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net"],
        'style-src': ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net"],
        'img-src': ["'self'", "data:", "https://cdn.jsdelivr.net"],
        'font-src': ["'self'", "https://cdn.jsdelivr.net"],
        'connect-src': ["'self'", "https://*.supabase.co", f"wss://{os.getenv('SUPABASE_PROJECT_REF')}.supabase.co"] if os.getenv('SUPABASE_PROJECT_REF') else ["'self'", "https://*.supabase.co"]
    })
    logging.info(f"Talisman initialized. force_https={talisman_force_https}")

    rate_limit_config = config.get_section('server', {}).get('rate_limit', {})
    default_limits = [
        f"{rate_limit_config.get('per_day', 200)} per day",
        f"{rate_limit_config.get('per_hour', 50)} per hour",
        f"{rate_limit_config.get('per_minute', 10)} per minute"
    ]
    storage_uri = "memory://"
    if not testing and storage_uri == "memory://":
        logging.warning("Rate limiter using 'memory://' storage. Consider persistent store for production.")
    
    limiter = Limiter(
        get_remote_address,
        app=None, 
        default_limits=default_limits,
        storage_uri=storage_uri
    )
    limiter.init_app(app) 

    logging.info(f"Flask-Limiter initialized with limits: {default_limits}")
    # This log helps confirm what Limiter's init_app did.
    logging.debug(f"Type of app.extensions['limiter'] after init_app: {type(app.extensions.get('limiter'))}")
    logging.debug(f"Value of app.extensions['limiter'] after init_app: {str(app.extensions.get('limiter'))[:200]}")


def _initialize_services(app: Flask, testing: bool):
    """Initializes application-specific services."""
    if testing:
        from unittest.mock import MagicMock
        app.openai_handler = MagicMock(spec=OpenAIHandler)
        app.openai_handler.generate_response.return_value = "Mocked test response"
        app.search_engine = MagicMock(spec=ImprovedSearchEngine)
        app.search_engine.search.return_value = []
        app.search_engine.is_initialized.return_value = True
        logging.info("Using MOCK OpenAIHandler and SearchEngine for testing.")
    else:
        if not os.getenv("OPENAI_API_KEY"):
            logging.error("OPENAI_API_KEY not set. OpenAIHandler may not function correctly.")
        app.openai_handler = OpenAIHandler()
        app.search_engine = ImprovedSearchEngine()
        logging.info("Initialized REAL OpenAIHandler and SearchEngine.")
        if not app.search_engine.is_initialized():
            logging.info("Attempting to initialize search engine...")
            try:
                app.search_engine.initialize()
                logging.info("Search engine initialized successfully.")
            except Exception as e:
                logging.error(f"Failed to initialize search engine: {str(e)}", exc_info=True)

def _register_routes(app: Flask, limiter_to_use: Limiter): # Expect a Limiter instance
    """Registers Flask routes and blueprints, using the provided Limiter instance."""
    app.register_blueprint(auth_bp, url_prefix='/auth')
    logging.info("Registered auth_bp blueprint at /auth.")
    ALLOWED_CHAT_CATEGORIES = ['all', 'regulatory', 'pharmacovigilance']

    @app.route('/')
    def index():
        """Render the landing page. Authentication state determines UI."""
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_anon_key = os.getenv('SUPABASE_ANON_KEY')
        if not supabase_url or not supabase_anon_key:
            logging.warning("SUPABASE_URL or SUPABASE_ANON_KEY not found in environment variables.")
        
        is_authenticated = bool(session.get('supabase_access_token') and session.get('user_email'))
        user_email = session.get('user_email')

        if not is_authenticated and not current_app.config.get('TESTING'):
            token = _get_token_from_request()
            if token:
                try:
                    supabase = get_supabase()
                    response = supabase.auth.get_user(token)
                    user = getattr(response, 'user', None) or getattr(getattr(response, 'data', None), 'user', None)
                    if user:
                        is_authenticated = True
                        user_email = user.email
                        session['supabase_access_token'] = token
                        session['user_email'] = user_email
                except Exception as e:
                    logging.error(f"Error validating token for index page: {e}")
                    clear_auth_session()
        
        return render_template('landing.html',
                               SUPABASE_URL=supabase_url,
                               SUPABASE_ANON_KEY=supabase_anon_key,
                               is_authenticated=is_authenticated,
                               user_email=user_email)

    @app.route('/chat')
    @auth_required
    def chat_page():
        """Render the chat interface. Protected by auth_required."""
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_anon_key = os.getenv('SUPABASE_ANON_KEY')
        return render_template('index.html',
                               SUPABASE_URL=supabase_url,
                               SUPABASE_ANON_KEY=supabase_anon_key,
                               user_email=session.get('user_email'))

    @app.route('/api/check-auth')
    @auth_required
    def check_auth():
        """Endpoint to verify authentication status. Returns user email if authenticated."""
        return jsonify({'authenticated': True, 'email': session.get('user_email')})

    @app.route('/api/chat', methods=['POST'])
    @auth_required
    @limiter_to_use.limit(config.get_section('server', {}).get('rate_limit', {}).get('chat_api', "10 per minute")) 
    def handle_chat():
        """Processes chat requests, performs search, generates LLM response, and manages chat history."""
        try:
            data = request.json
            if not data: 
                return jsonify({'error': 'Request body must be JSON'}), 400
            
            query = data.get('query', '').strip()
            category = data.get('category', 'all').lower()

            if not query: 
                return jsonify({'error': 'Query cannot be empty'}), 400
            if category not in ALLOWED_CHAT_CATEGORIES:
                return jsonify({'error': f'Invalid category. Allowed: {", ".join(ALLOWED_CHAT_CATEGORIES)}'}), 400

            processed_query = preprocess_query(query)
            
            if not current_app.search_engine or not current_app.search_engine.is_initialized():
                logging.error("Search engine not available or not initialized for /api/chat.")
                return jsonify({'error': 'Search service is temporarily unavailable.'}), 503

            search_results: List[SearchResult] = current_app.search_engine.search(processed_query, category)
            context_for_llm = [
                {"text": r.text, "document": r.document, "category": r.category, "page": r.page} 
                for r in search_results
            ]
            chat_history: List[Dict[str, str]] = session.get('chat_history', [])
            
            if not current_app.openai_handler:
                logging.error("OpenAI handler not available for /api/chat.")
                return jsonify({'error': 'Chat generation service is temporarily unavailable.'}), 503

            response_text = current_app.openai_handler.generate_response(query, context_for_llm, category, chat_history)
            chat_history.append({"role": "user", "content": query})
            chat_history.append({"role": "assistant", "content": response_text})
            
            max_pairs = current_app.config.get('MAX_CHAT_HISTORY_MESSAGE_PAIRS', DEFAULT_MAX_CHAT_MESSAGES_COUNT)
            chat_history = _truncate_chat_history(chat_history, max_pairs, MAX_SESSION_CHAT_HISTORY_CHARS)
            
            session['chat_history'] = chat_history
            return jsonify({'response': response_text})

        except Exception as e:
            logging.error(f"Error processing chat request: {str(e)}", exc_info=True)
            return jsonify({'error': 'An internal error occurred. Please try again.'}), 500

def create_app(testing: bool = False) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__, template_folder='../templates', static_folder='../../static')

    _configure_app_settings(app, testing)
    _initialize_extensions(app, testing) 
    _initialize_services(app, testing)

    # Retrieve the Limiter instance, accommodating the observed 'set' behavior
    # This is the workaround for the unusual 'set' in app.extensions['limiter']
    retrieved_limiter_value = app.extensions.get('limiter')
    limiter_to_pass_to_routes: Optional[Limiter] = None

    if isinstance(retrieved_limiter_value, Limiter):
        limiter_to_pass_to_routes = retrieved_limiter_value
        logging.info("Successfully retrieved Limiter instance directly from app.extensions.")
    elif isinstance(retrieved_limiter_value, set):
        logging.warning(
            f"app.extensions['limiter'] is a set. Value: {str(retrieved_limiter_value)[:200]}. "
            "Attempting to extract Limiter instance from the set."
        )
        # Extract the first item if the set is not empty and it's a Limiter instance
        if retrieved_limiter_value: # Check if the set is not empty
            potential_limiter = next(iter(retrieved_limiter_value), None)
            if isinstance(potential_limiter, Limiter):
                limiter_to_pass_to_routes = potential_limiter
                logging.info("Successfully extracted Limiter instance from the set in app.extensions.")
            else:
                logging.error(
                    f"Object extracted from set in app.extensions['limiter'] is not a Limiter instance. "
                    f"Type: {type(potential_limiter).__name__}"
                )
        else:
            logging.error("app.extensions['limiter'] is an empty set.")
    else:
        logging.error(
            f"app.extensions['limiter'] is neither a Limiter instance nor a set. "
            f"Type: {type(retrieved_limiter_value).__name__}. Value: {str(retrieved_limiter_value)[:200]}"
        )

    # If after all attempts, we don't have a valid Limiter instance, raise an error.
    if not limiter_to_pass_to_routes:
        error_message = (
            "CRITICAL FAILURE: Could not obtain a valid Flask-Limiter instance. "
            "Application cannot proceed with rate limiting."
        )
        logging.error(error_message)
        raise TypeError(error_message)
    
    _register_routes(app, limiter_to_pass_to_routes) # Pass the verified/extracted Limiter instance

    @app.before_request
    def log_request_info():
        if current_app.debug:
            logging.debug(f"Request: {request.method} {request.path} Args: {request.args.to_dict()}")

    @app.after_request
    def log_response_info(response):
        if current_app.debug:
            logging.debug(f"Response: {response.status_code} Path: {request.path}")
        return response
        
    return app

# --- Application Entry Point ---
if __name__ == '__main__':
    flask_app_instance = create_app(testing=os.getenv('FLASK_TESTING', 'false').lower() == 'true')
    
    is_debug_mode = config.get("server", "debug", True)
    
    if is_debug_mode and not flask_app_instance.config.get('TESTING'):
        logging.warning("Flask is running in DEBUG MODE. Ensure this is disabled in production.")
    elif not is_debug_mode:
        logging.info("Flask is running in PRODUCTION MODE.")

    flask_app_instance.run(
        debug=is_debug_mode, 
        host=config.get("server", "host", '0.0.0.0'),
        port=int(config.get("server", "port", 5000)) 
    )