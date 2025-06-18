import logging
import os
import sys
import yaml
import json
import re
from functools import wraps
from typing import List, Dict, Any, Tuple, Optional

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, jsonify, 
    current_app, session, redirect, url_for
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_cors import CORS

# --- Project Setup and Environment Loading ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DOTENV_PATH = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=DOTENV_PATH, override=True)
logging.info(f"Loading .env file from: {DOTENV_PATH}")

# --- Logging Configuration ---
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Set logger levels
for logger_name, default_level in [
    ('web.services.search_engine', 'DEBUG'),
    ('web.utils.config_loader', 'DEBUG'),
    ('web.utils.openai_client', 'DEBUG'),
    ('web.utils.local_embedding_client', 'DEBUG')
]:
    logging.getLogger(logger_name).setLevel(
        os.getenv(f'LOG_LEVEL_{logger_name.split(".")[-1].upper()}', default_level).upper()
    )

# --- Application-Specific Imports ---
from web.utils.config_loader import config
from web.services.openai_app import OpenAIHandler
from web.services.search_engine import ImprovedSearchEngine, SearchResult
from web.api.auth import auth_bp
from web.utils.supabase_client import get_supabase

# --- Constants ---
MAX_SESSION_CHAT_HISTORY_CHARS = 3500
DEFAULT_MAX_CHAT_MESSAGES_COUNT = 5
PHARMA_TERMS_EXPANSION = {
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
    """Expand query with relevant pharmaceutical terms using word boundaries."""
    expanded_terms = []
    query_lower = query.lower()
    
    for term, related_terms in PHARMA_TERMS_EXPANSION.items():
        if re.search(r'\b' + re.escape(term) + r'\b', query_lower):
            expanded_terms.extend(related_terms)
    
    if expanded_terms:
        processed_query = f"{query} {' '.join(set(expanded_terms))}"
        logging.info(
            "Query expanded: '%s' -> '%s'", 
            query, processed_query
        )
        return processed_query
    return query

def _get_token_from_request() -> Optional[str]:
    """Extract authentication token from request headers, cookies, or session."""
    if auth_header := request.headers.get('Authorization'):
        return auth_header.split('Bearer ')[-1] if auth_header.startswith('Bearer ') else auth_header
    if 'sb-access-token' in request.cookies:
        return request.cookies.get('sb-access-token')
    return session.get('supabase_access_token')

def _handle_unauthorized(is_page_request: bool) -> Any:
    """Handle unauthorized access by redirecting or returning JSON error."""
    if is_page_request:
        return redirect(url_for('index'))
    return jsonify({'error': 'Authorization required'}), 401

def clear_auth_session():
    """Clear authentication-related data from session."""
    session.pop('supabase_access_token', None)
    session.pop('user_email', None)

def auth_required(f):
    """Decorator to enforce authentication for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Testing mode handling
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
            user = None
            if hasattr(response, 'user'):
                user = getattr(response, 'user', None)
            elif hasattr(response, 'data'):
                data = getattr(response, 'data')
                if hasattr(data, 'user'):
                    user = getattr(data, 'user', None)

            if not user:
                logging.warning(
                    "Token validation failed for endpoint %s: User not found",
                    request.endpoint
                )
                clear_auth_session()
                return _handle_unauthorized(is_page_request)
            
            # Update session with valid credentials
            session['supabase_access_token'] = token
            session['user_email'] = user.email
            return f(*args, **kwargs)
        
        except Exception as e:
            logging.error(
                "Authentication error for endpoint %s: %s",
                request.endpoint, str(e), exc_info=True
            )
            clear_auth_session()
            return _handle_unauthorized(is_page_request)
    return decorated_function

def _truncate_chat_history(
    chat_history: List[Dict[str, str]],
    max_messages_pairs: int,
    max_chars: int
) -> List[Dict[str, str]]:
    """Truncate chat history based on message count and total character length."""
    max_total_messages = max_messages_pairs * 2
    
    # Truncate by message count
    if len(chat_history) > max_total_messages:
        chat_history = chat_history[-max_total_messages:]
    
    # Truncate by character count
    current_json = json.dumps(chat_history)
    if len(current_json) <= max_chars:
        return chat_history

    # Remove oldest pairs until under limit
    while len(chat_history) > 1 and len(current_json) > max_chars:
        chat_history = chat_history[2:]
        current_json = json.dumps(chat_history)
    
    # Handle case where single message exceeds limit
    if len(current_json) > max_chars and chat_history:
        logging.warning(
            "Chat history still too long (%d chars) after truncation",
            len(current_json)
        )
        chat_history = chat_history[1:]
    
    return chat_history or []

# --- Flask App Factory Components ---
def _configure_app_settings(app: Flask, testing: bool):
    """Configure basic Flask app settings."""
    app.secret_key = os.getenv('FLASK_SECRET_KEY') or os.urandom(24)
    
    if not os.getenv('FLASK_SECRET_KEY') and not testing:
        logging.warning(
            "FLASK_SECRET_KEY not set. Using temporary key. "
            "Set in .env for production."
        )

    app.config.update({
        'TESTING': testing,
        'MAX_CHAT_HISTORY_MESSAGE_PAIRS': config.get(
            "server", "chat_history_length", DEFAULT_MAX_CHAT_MESSAGES_COUNT
        )
    })
    
    if testing:
        app.config.update({
            'SERVER_NAME': 'localhost',
            'PREFERRED_URL_SCHEME': 'http'
        })

def _initialize_extensions(app: Flask, testing: bool) -> Limiter:
    """Initialize Flask extensions and return Limiter instance."""
    is_debug_mode = config.get("server", "debug", True) or testing
    
    # Initialize CORS
    if is_debug_mode:
        CORS(app, supports_credentials=True)
        logging.info("CORS initialized in debug mode (all origins)")
    else:
        allowed_origins = config.get("server", "allowed_origins", [])
        CORS(app, origins=allowed_origins, supports_credentials=True)
        logging.info("CORS initialized for origins: %s", allowed_origins)

    # Initialize Talisman
    talisman_force_https = not testing
    csp = {
        'default-src': ["'self'"],
        'script-src': ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net"],
        'style-src': ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net"],
        'img-src': ["'self'", "data:", "https://cdn.jsdelivr.net"],
        'font-src': ["'self'", "https://cdn.jsdelivr.net"],
        'connect-src': ["'self'", "https://*.supabase.co"]
    }
    
    if project_ref := os.getenv('SUPABASE_PROJECT_REF'):
        csp['connect-src'].append(f"wss://{project_ref}.supabase.co")
    
    Talisman(app, force_https=talisman_force_https, content_security_policy=csp)
    logging.info("Talisman initialized. force_https=%s", talisman_force_https)

    # Initialize Rate Limiting
    rate_limit_config = config.get_section('server', {}).get('rate_limit', {})
    default_limits = [
        lambda: f"{rate_limit_config.get('per_day', 200)} per day",
        lambda: f"{rate_limit_config.get('per_hour', 50)} per hour",
        lambda: f"{rate_limit_config.get('per_minute', 10)} per minute"
    ]
    
    storage_uri = "memory://"
    limiter = Limiter(
        get_remote_address,
        default_limits=default_limits,  # type: ignore[arg-type]
        storage_uri=storage_uri
    )
    limiter.init_app(app)
    
    if not testing and storage_uri == "memory://":
        logging.warning(
            "Rate limiter using 'memory://' storage. "
            "Use persistent store for production."
        )
    
    logging.info("Flask-Limiter initialized with limits: %s", default_limits)
    return limiter

def _initialize_services(app: Flask, testing: bool):
    """Initialize application-specific services."""
    if testing:
        from unittest.mock import MagicMock
        app.config['openai_handler'] = MagicMock(spec=OpenAIHandler)
        app.config['openai_handler'].generate_response.return_value = "Mocked test response"
        
        app.config['search_engine'] = MagicMock(spec=ImprovedSearchEngine)
        app.config['search_engine'].search.return_value = []
        app.config['search_engine'].is_initialized.return_value = True
        
        logging.info("Using MOCK services for testing")
    else:
        if not os.getenv("OPENAI_API_KEY"):
            logging.error("OPENAI_API_KEY not set. OpenAIHandler may fail")
        
        app.config['openai_handler'] = OpenAIHandler()
        app.config['search_engine'] = ImprovedSearchEngine()
        logging.info("Initialized REAL services")
        
        if not app.config['search_engine'].is_initialized():
            try:
                app.config['search_engine'].initialize()
                logging.info("Search engine initialized successfully")
            except Exception as e:
                logging.error("Failed to initialize search engine: %s", str(e), exc_info=True)

def _register_routes(app: Flask, limiter: Limiter):
    """Register Flask routes and blueprints."""
    # --- Start of new code for FAQ loading and endpoint ---
    
    # Load frequent questions from the YAML file on startup
    try:
        faq_path = os.path.join(PROJECT_ROOT, 'faq.yaml') # Using PROJECT_ROOT for robustness
        with open(faq_path, 'r') as f:
            frequent_questions_data = yaml.safe_load(f)
        app.config['FREQUENT_QUESTIONS'] = frequent_questions_data
        print(f"DEBUG: Loaded FAQ Data: {frequent_questions_data}", file=sys.stdout) # Direct print for debugging
        logging.info("Successfully loaded frequent questions from faq.yaml. Data: %s", frequent_questions_data)
    except FileNotFoundError:
        app.config['FREQUENT_QUESTIONS'] = {}
        logging.error("faq.yaml not found. FAQs will not be available.")
    except Exception as e:
        app.config['FREQUENT_QUESTIONS'] = {}
        logging.error(f"Error loading faq.yaml: {e}")

    @app.route('/api/frequent-questions')
    def get_frequent_questions():
        """API endpoint to provide the list of frequent questions."""
        faqs = current_app.config.get('FREQUENT_QUESTIONS', {})
        print(f"DEBUG: FAQs being sent to frontend: {faqs}", file=sys.stdout) # Added for debugging
        return jsonify(faqs)

    # --- End of new code for FAQ loading and endpoint ---

    app.register_blueprint(auth_bp, url_prefix='/auth')
    logging.info("Registered auth_bp blueprint at /auth")
    
    ALLOWED_CHAT_CATEGORIES = {'all', 'regulatory', 'pharmacovigilance', 'veterinary', 'biological'}

    @app.route('/')
    def index():
        """Render landing page with authentication status."""
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_anon_key = os.getenv('SUPABASE_ANON_KEY')
        
        if not supabase_url or not supabase_anon_key:
            logging.warning("Supabase credentials missing in environment")
        
        # Check authentication
        token = _get_token_from_request()
        user_email = None
        is_authenticated = False
        
        if token and not current_app.config.get('TESTING'):
            try:
                supabase = get_supabase()
                response = supabase.auth.get_user(token)
                user = None
                if hasattr(response, 'user'):
                    user = getattr(response, 'user', None)
                elif hasattr(response, 'data'):
                    data = getattr(response, 'data')
                    if hasattr(data, 'user'):
                        user = getattr(data, 'user', None)
                
                if user:
                    is_authenticated = True
                    user_email = user.email
                    session.update({
                        'supabase_access_token': token,
                        'user_email': user_email
                    })
            except Exception as e:
                logging.error("Token validation error: %s", str(e))
                clear_auth_session()
        
        return render_template(
            'landing.html',
            SUPABASE_URL=supabase_url,
            SUPABASE_ANON_KEY=supabase_anon_key,
            is_authenticated=is_authenticated,
            user_email=user_email
        )

    @app.route('/chat')
    @auth_required
    def chat_page():
        """Render chat interface (authenticated only)."""
        return render_template(
            'index.html',
            SUPABASE_URL=os.getenv('SUPABASE_URL'),
            SUPABASE_ANON_KEY=os.getenv('SUPABASE_ANON_KEY'),
            user_email=session.get('user_email')
        )

    @app.route('/api/check-auth')
    @auth_required
    def check_auth():
        """Verify authentication status."""
        return jsonify({
            'authenticated': True, 
            'email': session.get('user_email')
        })

    @app.route('/api/chat', methods=['POST'])
    @auth_required
    @limiter.limit(
        config.get_section('server', {})
        .get('rate_limit', {})
        .get('chat_api', "10 per minute")
    )
    def handle_chat():
        """Process chat requests with search and LLM response generation."""
        try:
            data = request.get_json()
            logging.debug(f"Received JSON data: {data}") # New debug log
            if not data:
                return jsonify({'error': 'Request body must be JSON'}), 400
            
            # Validate input
            query = data.get('query', '').strip()
            category = data.get('category', 'all')
            logging.debug(f"Extracted category: '{category}'") # New debug log
            
            logging.debug(f"Received chat request with category: '{category}'") # Debug log
            
            if not query:
                return jsonify({'error': 'Query cannot be empty'}), 400
            
            # Ensure category is valid and handle potential casing issues
            if category.lower() not in [c.lower() for c in ALLOWED_CHAT_CATEGORIES]:
                logging.warning(f"Invalid category received: '{category}'. Allowed: {', '.join(ALLOWED_CHAT_CATEGORIES)}")
                return jsonify({
                    'error': f'Invalid category. Allowed: {", ".join(ALLOWED_CHAT_CATEGORIES)}'
                }), 400
            
            # Normalize category to match internal representation if needed
            category = next((c for c in ALLOWED_CHAT_CATEGORIES if c.lower() == category.lower()), category)

            # Process query and search
            processed_query = preprocess_query(query)
            
            if not (current_app.config.get('search_engine') and 
                    current_app.config['search_engine'].is_initialized()):
                logging.error("Search engine unavailable for /api/chat")
                return jsonify({
                    'error': 'Search service unavailable'
                }), 503

            search_results = current_app.config['search_engine'].search(
                processed_query, 
                category
            )
            context_for_llm = [
                {
                    "text": r.text, 
                    "document": r.document, 
                    "category": r.category, 
                    "page": r.page
                } for r in search_results
            ]
            
            # Generate LLM response
            chat_history = session.get('chat_history', [])
            
            if not current_app.config.get('openai_handler'):
                logging.error("OpenAI handler unavailable for /api/chat")
                return jsonify({
                    'error': 'Chat service unavailable'
                }), 503

            response_text = current_app.config['openai_handler'].generate_response(
                query, context_for_llm, category, chat_history
            )
            
            # Update and truncate chat history
            chat_history.extend([
                {"role": "user", "content": query},
                {"role": "assistant", "content": response_text}
            ])
            
            max_pairs = current_app.config.get(
                'MAX_CHAT_HISTORY_MESSAGE_PAIRS', 
                DEFAULT_MAX_CHAT_MESSAGES_COUNT
            )
            chat_history = _truncate_chat_history(
                chat_history, 
                max_pairs, 
                MAX_SESSION_CHAT_HISTORY_CHARS
            )
            session['chat_history'] = chat_history
            
            return jsonify({'response': response_text})

        except Exception as e:
            logging.error(
                "Chat processing error: %s", 
                str(e), exc_info=True
            )
            return jsonify({
                'error': 'Internal server error'
            }), 500

def create_app(testing: bool = False) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder='../templates',
        static_folder='../../static'
    )

    # Configure application
    _configure_app_settings(app, testing)
    limiter = _initialize_extensions(app, testing)
    _initialize_services(app, testing)

    # Register routes with the limiter instance
    _register_routes(app, limiter)

    # Request logging
    @app.before_request
    def log_request_info():
        if current_app.debug:
            logging.debug(
                "%s %s - Args: %s",
                request.method,
                request.path,
                request.args.to_dict()
            )

    @app.after_request
    def log_response_info(response):
        if current_app.debug:
            logging.debug(
                "%s %s - Status: %s",
                request.method,
                request.path,
                response.status
            )
        return response
        
    return app

# --- Application Entry Point ---
if __name__ == '__main__':
    app = create_app(testing=os.getenv('FLASK_TESTING', 'false').lower() == 'true')
    
    debug_mode = config.get("server", "debug", True)
    host = config.get("server", "host", '0.0.0.0')
    port = int(config.get("server", "port", 5000))
    
    if debug_mode and not app.config.get('TESTING'):
        logging.warning("Running in DEBUG MODE - Not suitable for production")
    else:
        logging.info("Running in PRODUCTION MODE")

    app.run(debug=debug_mode, host=host, port=port)
