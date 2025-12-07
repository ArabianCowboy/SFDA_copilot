import logging
from flask import Blueprint, request, jsonify
from web.utils.supabase_client import get_supabase

auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)

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
    try:
        supabase = get_supabase()
        if not supabase:
            return jsonify({'error': 'Supabase client not available'}), 500
        
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
