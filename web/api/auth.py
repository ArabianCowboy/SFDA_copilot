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
        
        # Store additional user data in Supabase DB
        user = response.user
        supabase.table('users').insert({
            'id': user.id,
            'email': user.email,
            'created_at': user.created_at
        }).execute()
        
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
        
        return jsonify({
            'access_token': response.session.access_token,
            'refresh_token': response.session.refresh_token,
            'user': {
                'id': response.user.id,
                'email': response.user.email
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 401

@auth_bp.route('/logout', methods=['POST'])
def logout():
    supabase = get_supabase()
    supabase.auth.sign_out()
    return jsonify({'message': 'Logged out successfully'})
