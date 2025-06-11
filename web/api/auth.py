from flask import Blueprint, request, jsonify
from web.utils.supabase_client import get_supabase

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400
    
    supabase = get_supabase()
    
    try:
        # Create user in Supabase Auth
        response = supabase.auth.sign_up({
            'email': email,
            'password': password,
        })
        
        if response.error:
            return jsonify({'error': response.error.message}), 400
            
        # Access user data from the response
        user = response.user if hasattr(response, 'user') else response.data.user
        
        # Return success response
        return jsonify({
            'message': 'User created successfully',
            'user': {
                'id': user.id,
                'email': user.email
            }
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400
    
    supabase = get_supabase()
    
    try:
        response = supabase.auth.sign_in_with_password({
            'email': email,
            'password': password
        })
        
        if response.error:
            return jsonify({'error': response.error.message}), 401
            
        # Access user and session data from the response
        user = response.user if hasattr(response, 'user') else response.data.user
        session = response.session if hasattr(response, 'session') else response.data.session
        
        return jsonify({
            'user': {
                'id': user.id,
                'email': user.email
            },
            'session': {
                'access_token': session.access_token,
                'refresh_token': session.refresh_token
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 401

@auth_bp.route('/logout', methods=['POST'])
def logout():
    supabase = get_supabase()
    try:
        response = supabase.auth.sign_out()
        if response.error:
            return jsonify({'error': response.error.message}), 400
        return jsonify({'message': 'Logged out successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
