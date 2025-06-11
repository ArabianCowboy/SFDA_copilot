import pytest
from flask import url_for
from unittest.mock import patch, MagicMock
import os

@pytest.fixture(autouse=True)
def mock_env_vars():
    """Mock environment variables for testing."""
    with patch.dict(os.environ, {
        'FLASK_SECRET_KEY': 'test-key',
        'SUPABASE_URL': 'http://test.supabase.co',
        'SUPABASE_ANON_KEY': 'test-anon-key',
        'OPENAI_API_KEY': 'test-openai-key',
        'FLASK_ENV': 'testing',
        'TESTING': 'true'
    }):
        yield

@pytest.fixture
def app():
    """Create application for the tests."""
    from web.api.app import create_app
    app = create_app(testing=True)
    return app

@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()

@pytest.fixture(autouse=True)
def mock_supabase():
    """Mock Supabase client for testing."""
    with patch('web.utils.supabase_client.get_supabase') as mock:
        mock_client = MagicMock()
        
        # Configure mock user
        mock_user = MagicMock(
            id='123',
            email='test@example.com',
            created_at='2024-03-27T00:00:00Z'
        )
        
        # Configure mock session
        mock_session = MagicMock(
            access_token='fake_token',
            refresh_token='fake_refresh_token'
        )
        
        # Configure auth methods with better token handling
        def mock_get_user(token=None):
            if token == 'fake_token':
                return MagicMock(
                    user=mock_user,
                    data={'user': mock_user},
                    error=None
                )
            return MagicMock(
                user=None,
                data={'user': None},
                error={'message': 'Invalid token'}
            )
            
        mock_client.auth.get_user = mock_get_user
        
        # Configure sign up response
        mock_client.auth.sign_up.return_value = MagicMock(
            user=mock_user,
            data={'user': mock_user},
            error=None
        )
        
        # Configure sign in response
        mock_client.auth.sign_in_with_password.return_value = MagicMock(
            user=mock_user,
            session=mock_session,
            data={'user': mock_user, 'session': mock_session},
            error=None
        )
        
        # Configure sign out response
        mock_client.auth.sign_out.return_value = MagicMock(error=None)
        
        # Set the mock client as the return value
        mock.return_value = mock_client
        yield mock_client

def test_landing_page_unauthenticated(client):
    """Test that landing page shows auth UI when user is not logged in"""
    response = client.get('/')
    assert response.status_code == 200
    assert b'login-form' in response.data
    assert b'signup-form' in response.data
    assert b'auth-button-main' in response.data
    assert b'authenticated-view' not in response.data

def test_landing_page_authenticated(client, mock_supabase):
    """Test that landing page shows gateway when user is logged in"""
    response = client.get('/', headers={'Authorization': 'Bearer fake_token'})
    assert response.status_code == 200
    assert b'authenticated-view' in response.data
    assert b'Enter Chatbot' in response.data
    assert b'login-form' not in response.data

def test_chat_route_unauthenticated(client):
    """Test that chat route returns 401 when not authenticated"""
    response = client.get('/chat')
    assert response.status_code == 401
    assert b'Authorization header is missing' in response.data

def test_chat_route_authenticated(client, mock_supabase):
    """Test that chat route works when authenticated"""
    response = client.get('/chat', headers={'Authorization': 'Bearer fake_token'})
    assert response.status_code == 200
    assert b'chat' in response.data

def test_check_auth_endpoint(client, mock_supabase):
    """Test the check-auth endpoint"""
    # Test without auth header
    response = client.get('/api/check-auth')
    assert response.status_code == 401
    assert b'Authorization header is missing' in response.data
    
    # Test with invalid token
    response = client.get('/api/check-auth', headers={'Authorization': 'Bearer invalid_token'})
    assert response.status_code == 401
    assert b'Invalid test token' in response.data
    
    # Test with valid token
    response = client.get('/api/check-auth', headers={'Authorization': 'Bearer fake_token'})
    assert response.status_code == 200
    assert response.json == {'authenticated': True}

def test_auth_api_endpoints(client, mock_supabase):
    """Test that auth API endpoints work correctly"""
    # Test signup
    signup_data = {'email': 'test@example.com', 'password': 'Password123!'}
    response = client.post('/auth/signup', json=signup_data)
    assert response.status_code == 201
    assert 'user' in response.json
    assert response.json['user']['email'] == 'test@example.com'
    
    # Test login
    login_data = {'email': 'test@example.com', 'password': 'Password123!'}
    response = client.post('/auth/login', json=login_data)
    assert response.status_code == 200
    assert 'user' in response.json
    assert 'session' in response.json
    assert response.json['user']['email'] == 'test@example.com'
    
    # Test logout
    response = client.post('/auth/logout', headers={'Authorization': 'Bearer fake_token'})
    assert response.status_code == 200 