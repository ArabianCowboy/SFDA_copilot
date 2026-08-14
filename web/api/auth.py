import logging
from flask import Blueprint, current_app, jsonify, request, session
from web.utils.supabase_client import get_supabase

auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)


# Session keys holding one reader's conversation. Named once so the purge below
# and the identity check in app.py cannot drift apart.
#
# `conv_id`/`prev_conv_id` key the server-side ConversationStore, where both
# the streaming and blocking chat routes now hold history — so the purge below
# has to clear the store entries these key, not just the cookie. `chat_history`
# and `prev_chat_history` are no longer written by either route; they stay
# here only as a defensive purge target for any pre-migration cookie still
# carrying them, so a reader who resets and then signs out (or hands the
# browser to someone else) does not leave old questions and answers sitting in
# the next reader's session.
CONVERSATION_SESSION_KEYS = (
    "conv_id",
    "prev_conv_id",
    "chat_history",
    "prev_chat_history",
)

# The subset of the above that keys a server-side ConversationStore entry.
CONVERSATION_ID_KEYS = ("conv_id", "prev_conv_id")

# Markers that describe *who* is holding this cookie rather than what they said.
#
# `is_admin_hint` is a render hint and nothing else — it decides whether the
# Admin link is drawn on a page the server renders without validating a token.
# Authorization is always a fresh server-side lookup; see `_authenticate_request`.
#
# It still rotates with the conversation, and for the same reason: an elevated
# marker that outlived its reader is exactly the leak `_bind_session_to_identity`
# exists to close. A hint is cheap to rebuild and expensive to leave lying around
# on a shared machine.
IDENTITY_MARKER_KEYS = ("is_admin_hint",)


def purge_conversation_state():
    """Drop this browser session's conversation, server side included.

    The Flask session cookie outlives a Supabase sign-out — nothing in the
    logout path used to touch it — so `conv_id` and `chat_history` survived
    into the next sign-in **in the same browser**. The streaming route keys the
    ConversationStore off that same `conv_id` and feeds whatever it finds to
    the model as context, so the next reader's first question arrived carrying
    the previous reader's conversation. On a regulatory assistant that is one
    person's queries becoming part of another person's prompt.

    Clearing the cookie key alone is not enough: the store entry is held
    server-side and would be re-reachable by anyone who still had the old
    cookie, so the entry itself goes too.
    """
    store = current_app.config.get("conversations")
    if store is not None:
        for key in CONVERSATION_ID_KEYS:
            conversation_id = session.get(key)
            if conversation_id:
                store.clear(conversation_id)

    for key in CONVERSATION_SESSION_KEYS:
        session.pop(key, None)


def rotate_session_for_new_identity() -> None:
    """Reset everything tied to the previous reader of this cookie.

    One call rather than two, so a marker added later cannot be wired into one
    purge and forgotten in the other — which is how `is_admin_hint` would
    otherwise have survived a change of reader on a shared machine.
    """
    purge_conversation_state()
    for key in IDENTITY_MARKER_KEYS:
        session.pop(key, None)


@auth_bp.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400
    
    try:
        supabase = get_supabase()
        if not supabase:
            return jsonify({'error': 'Supabase client not available'}), 500
        
        # Create user in Supabase Auth
        response = supabase.auth.sign_up({
            'email': email,
            'password': password,
        })
        
        # Handle response structure - check for error attribute first
        if hasattr(response, 'error') and response.error:
            error_msg = getattr(response.error, 'message', str(response.error))
            logger.warning(f"Signup error: {error_msg}")
            return jsonify({'error': error_msg}), 400
        
        # Access user data from the response
        # Try different possible response structures
        user = None
        if hasattr(response, 'user') and response.user:
            user = response.user
        elif hasattr(response, 'data') and hasattr(response.data, 'user'):
            user = response.data.user
        elif hasattr(response, 'user'):
            user = response.user
        
        if not user:
            logger.error(f"Signup response structure unexpected: {dir(response)}")
            return jsonify({'error': 'Unexpected response from authentication service'}), 500
        
        # Return success response
        return jsonify({
            'message': 'User created successfully',
            'user': {
                'id': user.id,
                'email': user.email
            }
        }), 201
        
    except Exception as e:
        logger.error(f"Signup exception: {str(e)}", exc_info=True)
        error_msg = str(e)
        # Extract more meaningful error messages from common exceptions
        if 'Invalid login credentials' in error_msg or 'invalid_credentials' in error_msg.lower():
            error_msg = 'Invalid email or password'
        elif 'User already registered' in error_msg or 'already_registered' in error_msg.lower():
            error_msg = 'This email is already registered'
        return jsonify({'error': error_msg}), 400

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400
    
    try:
        supabase = get_supabase()
        if not supabase:
            return jsonify({'error': 'Supabase client not available'}), 500
        
        response = supabase.auth.sign_in_with_password({
            'email': email,
            'password': password
        })
        
        # Handle response structure - check for error attribute first
        if hasattr(response, 'error') and response.error:
            error_msg = getattr(response.error, 'message', str(response.error))
            logger.warning(f"Login error: {error_msg}")
            return jsonify({'error': error_msg}), 401
        
        # Access user and session data from the response
        # Try different possible response structures
        user = None
        session_obj = None
        
        if hasattr(response, 'user') and response.user:
            user = response.user
        elif hasattr(response, 'data') and hasattr(response.data, 'user'):
            user = response.data.user
        
        if hasattr(response, 'session') and response.session:
            session_obj = response.session
        elif hasattr(response, 'data') and hasattr(response.data, 'session'):
            session_obj = response.data.session
        
        if not user:
            logger.error(f"Login response structure unexpected. Response attributes: {dir(response)}")
            return jsonify({'error': 'Unexpected response from authentication service'}), 500
        
        if not session_obj:
            logger.warning("Login successful but no session returned")
            return jsonify({
                'user': {
                    'id': user.id,
                    'email': user.email
                },
                'session': None
            }), 200
        
        return jsonify({
            'user': {
                'id': user.id,
                'email': user.email
            },
            'session': {
                'access_token': session_obj.access_token,
                'refresh_token': session_obj.refresh_token
            }
        })
        
    except Exception as e:
        logger.error(f"Login exception: {str(e)}", exc_info=True)
        error_msg = str(e)
        # Extract more meaningful error messages from common exceptions
        if 'Invalid login credentials' in error_msg or 'invalid_credentials' in error_msg.lower():
            error_msg = 'Invalid email or password'
        elif 'Email not confirmed' in error_msg or 'email_not_confirmed' in error_msg.lower():
            error_msg = 'Please confirm your email address before logging in'
        return jsonify({'error': error_msg}), 401

@auth_bp.route('/logout', methods=['POST'])
def logout():
    # Before anything that can fail. Whether Supabase is reachable, whether the
    # token was already expired, whether sign_out raises — none of it may leave
    # this browser session still holding the previous reader's conversation.
    purge_conversation_state()
    session.clear()

    if current_app.config.get("TESTING"):
        return jsonify({'message': 'Logged out successfully'})

    try:
        supabase = get_supabase()
        if not supabase:
            # The server-side state is already gone, which is the part that
            # matters; the client drops its own token regardless.
            logger.warning("Logout: Supabase unavailable, session cleared anyway.")
            return jsonify({'message': 'Logged out (session cleared)'})

        response = supabase.auth.sign_out()
        
        # Check for error in response
        if hasattr(response, 'error') and response.error:
            error_msg = getattr(response.error, 'message', str(response.error))
            logger.warning(f"Logout error: {error_msg}")
            return jsonify({'error': error_msg}), 400
        
        return jsonify({'message': 'Logged out successfully'})
    except Exception as e:
        logger.error(f"Logout exception: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 400
