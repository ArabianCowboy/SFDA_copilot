import logging
import os
import sys
from dotenv import load_dotenv # Import dotenv

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load environment variables from .env file in the project root
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path, override=True)

from flask import Flask, render_template, request, jsonify, current_app, session
from typing import List  # For type hints
from web.services.search_engine import SearchResult  # Import SearchResult for type hints
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman # Import Talisman
from flask_cors import CORS # Import CORS
from functools import wraps
from web.utils.config_loader import config # Import centralized config
from web.services.openai_app import OpenAIHandler
from web.services.search_engine import ImprovedSearchEngine
from web.api.auth import auth_bp
from web.utils.supabase_client import get_supabase

# --- Query Preprocessing Logic ---
def preprocess_query(query: str) -> str:
    """Expands query with relevant pharmaceutical terms."""
    # Comprehensive dictionary based on the improved example
    pharma_terms = {
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
        # Add more terms as needed
    }
    
    expanded_terms = []
    query_lower = query.lower()
    
    # Check for whole words/phrases to avoid partial matches (e.g., 'risk' in 'brisk')
    # This is a simple approach; more robust NLP might be needed for complex cases
    import re
    for term, related_terms in pharma_terms.items():
        # Use word boundaries to match whole words/phrases
        if re.search(r'\b' + re.escape(term) + r'\b', query_lower):
            expanded_terms.extend(related_terms)
            
    # Add unique expanded terms to the original query
    unique_expanded = " ".join(list(set(expanded_terms)))
    
    if unique_expanded:
        processed_query = f"{query} {unique_expanded}"
        # Log the expansion for debugging/analysis
        logging.info(f"Original Query: '{query}', Expanded Query: '{processed_query}'")
        return processed_query
    else:
        return query
# --- End Query Preprocessing Logic ---

def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'error': 'Authorization header is missing'}), 401

        # Extract token if header is in the format "Bearer <token>"
        token = auth_header
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

        try:
            supabase = get_supabase()
            user = supabase.auth.get_user(token)
            if not user:
                return jsonify({'error': 'Invalid or expired token'}), 401
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({'error': str(e)}), 401
    return decorated_function
# Explicitly set template and static folder paths relative to this file
app = Flask(__name__, template_folder='../templates', static_folder='../../static')

# --- Session Configuration ---
# Set a secret key for session management. Use environment variable or generate one.
# IMPORTANT: Keep this key secret in production!
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24))
if not os.getenv('FLASK_SECRET_KEY') and config.get("server", "debug", True):
    logging.warning("FLASK_SECRET_KEY not set, using a temporary key. Set this in your environment for production.")
# Define max chat history length
MAX_CHAT_HISTORY_LENGTH = config.get("server", "chat_history_length", 5) # Get from config, default 5
# --- End Session Configuration ---


# Configure logging - settings are loaded from config.yaml
logger = logging.getLogger(__name__)

# Initialize CORS - Allow all origins in development, restrict in production
is_debug_mode = config.get("server", "debug", True)
if is_debug_mode:
    CORS(app) # Allow all origins in debug mode
else:
    # Restrict origins in production - get allowed origins from config or env
    allowed_origins = config.get("server", "allowed_origins", []) # Example: ["http://localhost:3000", "https://yourdomain.com"]
    CORS(app, origins=allowed_origins, supports_credentials=True)

# Initialize Talisman for security headers and CSRF protection
# In development mode, we'll disable CSP to avoid authentication issues
# In production, a properly configured CSP should be implemented
is_debug_mode = config.get("server", "debug", True)

if is_debug_mode:
    # In development mode, disable CSP for easier debugging
    talisman = Talisman(
        app,
        content_security_policy=None, # Disable CSP in development
        force_https=False, # Don't enforce HTTPS in development
        session_cookie_secure=False,
        session_cookie_http_only=True, # Corrected parameter name
        frame_options='DENY',  # More secure default in development
        strict_transport_security=False
    )
else:
    # In production, use a properly configured CSP
    supabase_url_env = os.getenv('SUPABASE_URL') # Get Supabase URL once
    
    csp = {
        'default-src': [
            '\'self\'',
            # Add Supabase URL if it exists
            supabase_url_env if supabase_url_env else None,
            # Allow Supabase authentication services
            'https://*.supabase.co',
            'https://*.supabase.in'
        ],
        'script-src': [
            '\'self\'',
            '\'unsafe-inline\'', # Needed for inline scripts in index.html
            # Add Supabase URL if it exists
            supabase_url_env if supabase_url_env else None,
            # Allow Supabase authentication services
            'https://*.supabase.co',
            'https://*.supabase.in'
        ],
        'connect-src': [
            '\'self\'',
            # Add Supabase URL if it exists
            supabase_url_env if supabase_url_env else None,
            # Allow Supabase authentication services
            'https://*.supabase.co',
            'https://*.supabase.in'
        ],
        'style-src': [
            '\'self\'',
            '\'unsafe-inline\'' # Needed for inline styles
        ],
        'img-src': [
            '\'self\'',
            'data:', # Allow data URIs (e.g., for embedded images)
            'https://*.supabase.co',
            'https://*.supabase.in'
        ],
        'frame-src': [
            '\'self\'',
            # Allow Supabase authentication services
            'https://*.supabase.co',
            'https://*.supabase.in'
        ]
    }
    
    # Filter out None values from CSP lists before passing to Talisman
    filtered_csp = {k: [v for v in val if v is not None] for k, val in csp.items()}
    
    talisman = Talisman(
        app,
        content_security_policy=filtered_csp, # Use the filtered CSP
        content_security_policy_nonce_in=['script-src'], # Add nonce for scripts if needed
        force_https=True, # Enforce HTTPS in production
        session_cookie_secure=True,
        session_cookie_http_only=True, # Corrected parameter name
        frame_options='SAMEORIGIN', # Allow frames from same origin for auth UI
        strict_transport_security=True
    )

# Initialize Rate Limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[
        f"{config.get_section('server', {}).get('rate_limit', {}).get('per_day', 200)} per day",
        f"{config.get_section('server', {}).get('rate_limit', {}).get('per_hour', 50)} per hour",
        f"{config.get_section('server', {}).get('rate_limit', {}).get('per_minute', 10)} per minute"
    ],
    storage_uri="memory://", # Use memory storage for simplicity, consider Redis for production
)

# Initialize search engine and OpenAI handler
search_engine = ImprovedSearchEngine()
openai_handler = OpenAIHandler()

# Register blueprints
app.register_blueprint(auth_bp, url_prefix='/auth')

# --- Frequent Questions Data (Example - Move to config/DB later) ---
FREQUENT_QUESTIONS = {
    "regulatory": [
        {"text": "What are the requirements for drug registration?", "short": "Drug Registration"},
        {"text": "Explain the process for clinical trial approval.", "short": "Clinical Trials"},
        {"text": "Where can I find GMP guidelines?", "short": "GMP Guidelines"}
    ],
    "pharmacovigilance": [
        {"text": "How to report an adverse drug reaction?", "short": "Report ADR"},
        {"text": "What are the GVP requirements?", "short": "GVP Requirements"},
        {"text": "Explain the PSUR submission process.", "short": "PSUR Submission"}
    ]
}
# --- End Frequent Questions Data ---

# Allowed categories for validation
ALLOWED_CATEGORIES = {"all", "regulatory", "pharmacovigilance"}

def get_frequent_questions(category='all'):
    """Retrieves frequent questions based on category."""
    if category == 'all':
        # Combine questions from all categories, avoiding duplicates if necessary
        all_questions = []
        seen_texts = set()
        for cat_questions in FREQUENT_QUESTIONS.values():
            for q in cat_questions:
                if q['text'] not in seen_texts:
                    all_questions.append(q)
                    seen_texts.add(q['text'])
        return all_questions
    else:
        return FREQUENT_QUESTIONS.get(category, [])

@app.route('/')
def index():
    """Render the main chat interface."""
    # Retrieve Supabase credentials from environment variables to pass to the template
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_anon_key = os.getenv('SUPABASE_ANON_KEY') # Anon key is public

    if not supabase_url or not supabase_anon_key:
        # Log a warning if keys are missing, but still render the page
        # The frontend JS should handle the case where these are not provided
        logging.warning("SUPABASE_URL or SUPABASE_ANON_KEY not found in environment variables.")

    return render_template(
        'index.html', 
        SUPABASE_URL=supabase_url, 
        SUPABASE_ANON_KEY=supabase_anon_key
    )

@app.route('/api/chat', methods=['POST'])
@auth_required # Re-enabled authentication
@limiter.limit("5 per minute") # Apply rate limit to this endpoint
def chat():
    """Process chat requests and return responses."""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'Request body must be JSON'}), 400
            
        query = data.get('query', '')
        category = data.get('category', 'all').lower() # Normalize category to lowercase
        
        if not query:
            return jsonify({'error': 'Query is required'}), 400
            
        # Validate category
        if category not in ALLOWED_CATEGORIES:
            return jsonify({'error': f'Invalid category. Allowed categories are: {", ".join(ALLOWED_CATEGORIES)}'}), 400
            
        # Preprocess the query for expansion
        processed_query = preprocess_query(query)
        
        # Search for relevant context based on the processed query and category
        # search_engine.search now returns List[SearchResult]
        search_results_objects: List[SearchResult] = search_engine.search(processed_query, category) 
        
        # Convert List[SearchResult] to List[Dict] expected by OpenAIHandler._prepare_context
        context_for_llm = [
            {
                "text": result.text,
                "document": result.document,
                "category": result.category,
                "page": result.page 
                # Add score or other metadata if needed by the prompt later
            } 
            for result in search_results_objects
        ]
        
        # Generate response using OpenAI (pass original query for context, but processed query was used for search)
        # Retrieve chat history from session
        chat_history = session.get('chat_history', [])
        
        # Generate response using OpenAI, passing the history and the converted context
        response_text = openai_handler.generate_response(query, context_for_llm, category, chat_history) 
        
        # Update chat history
        chat_history.append({"role": "user", "content": query})
        chat_history.append({"role": "assistant", "content": response_text})
        
        # Truncate history if it exceeds the maximum length
        if len(chat_history) > MAX_CHAT_HISTORY_LENGTH * 2: # Each turn adds 2 entries (user + bot)
             # Keep only the last MAX_CHAT_HISTORY_LENGTH turns (x2 for user/bot entries)
            chat_history = chat_history[-(MAX_CHAT_HISTORY_LENGTH * 2):]
            
        # Store updated history back in session
        session['chat_history'] = chat_history
        
        return jsonify({'response': response_text}) # Return the generated text

    except Exception as e:
        # Use configured logger
        logging.error(f"Error processing chat request: {str(e)}", exc_info=True) 
        return jsonify({'error': 'An internal error occurred processing your request'}), 500

@app.route('/api/frequent-questions', methods=['GET'])
@limiter.limit("10 per minute") # Apply a separate limit if desired
def frequent_questions():
    """Return a list of frequent questions based on category."""
    category = request.args.get('category', 'all').lower()
    if category not in ALLOWED_CATEGORIES:
         # Use current_app.logger for consistency
        current_app.logger.warning(f"Invalid category requested for frequent questions: {category}")
        # Return empty list or specific error? Returning empty for now.
        # return jsonify({'error': f'Invalid category. Allowed categories are: {", ".join(ALLOWED_CATEGORIES)}'}), 400
        questions = []
    else:
        questions = get_frequent_questions(category)
    return jsonify({'questions': questions})


if __name__ == '__main__':
    # Check if search engine is initialized
    if not search_engine.is_initialized():
        logging.info("Initializing search engine...")
        try:
            search_engine.initialize()
        except Exception as e:
            logging.error(f"Failed to initialize search engine: {str(e)}")
            sys.exit(1)

    # Get debug setting from config (already retrieved earlier for CORS/Talisman)
    if is_debug_mode:
        logging.warning("Flask is running in DEBUG MODE. Ensure this is disabled in production.")
    else:
        logging.info("Flask is running in PRODUCTION MODE.") # Log production mode

    # Run the Flask app using config values
    app.run(
        debug=is_debug_mode, 
        host=config.get("server", "host", '0.0.0.0'), # Get host from config
        port=config.get("server", "port", 5000)
    )
