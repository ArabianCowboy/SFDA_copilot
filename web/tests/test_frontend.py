import pytest
from playwright.sync_api import Page, expect
from unittest.mock import patch

@pytest.fixture(autouse=True)
def setup_supabase_env(monkeypatch):
    """Setup Supabase environment variables for testing"""
    monkeypatch.setenv('SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('SUPABASE_ANON_KEY', 'test-anon-key')

def test_landing_page_layout(page: Page):
    """Test that landing page has correct layout and elements"""
    page.goto('/')
    
    # Check main elements
    expect(page.get_by_text('SFDA Copilot')).to_be_visible()
    expect(page.get_by_role('button', name='Login / Signup')).to_be_visible()
    
    # Auth modal should be hidden initially
    expect(page.locator('#authModal')).to_be_hidden()
    
    # Click login button should show modal
    page.get_by_role('button', name='Login / Signup').click()
    expect(page.locator('#authModal')).to_be_visible()
    
    # Check auth form elements
    expect(page.get_by_label('Email address')).to_be_visible()
    expect(page.get_by_label('Password')).to_be_visible()
    expect(page.get_by_role('button', name='Login')).to_be_visible()
    expect(page.get_by_role('button', name='Signup')).to_be_visible()

@pytest.mark.skip(reason="Requires Supabase mock implementation")
def test_auth_flow(page: Page):
    """Test complete authentication flow"""
    page.goto('/')
    
    # Start login process
    page.get_by_role('button', name='Login / Signup').click()
    
    # Fill login form
    page.get_by_label('Email address').fill('test@example.com')
    page.get_by_label('Password').fill('password123')
    page.get_by_role('button', name='Login').click()
    
    # Should show gateway after login
    expect(page.get_by_text('Enter Chatbot')).to_be_visible()
    expect(page.get_by_text('Logged in as: test@example.com')).to_be_visible()
    
    # Click gateway link
    page.get_by_role('link', name='Enter Chatbot').click()
    
    # Should be on chat page
    expect(page.url).to_end_with('/chat')
    expect(page.get_by_placeholder('Ask about SFDA regulations...')).to_be_visible()

def test_unauthenticated_chat_redirect(page: Page):
    """Test that accessing chat without auth redirects to landing"""
    # Try to access chat directly
    page.goto('/chat')
    
    # Should redirect to landing
    expect(page.url).to_end_with('/')
    expect(page.get_by_role('button', name='Login / Signup')).to_be_visible()

def test_responsive_layout(page: Page):
    """Test responsive behavior of landing page"""
    page.goto('/')
    
    # Test desktop layout
    page.set_viewport_size({'width': 1200, 'height': 800})
    expect(page.locator('.sidebar')).to_be_visible()
    expect(page.locator('.navbar-toggler')).to_be_hidden()
    
    # Test mobile layout
    page.set_viewport_size({'width': 375, 'height': 667})
    expect(page.locator('.sidebar')).to_be_hidden()
    expect(page.locator('.navbar-toggler')).to_be_visible()
    
    # Test mobile menu
    page.get_by_role('button', name='Toggle navigation').click()
    expect(page.locator('#sidebarOffcanvas')).to_be_visible()
    expect(page.locator('#auth-button-offcanvas')).to_be_visible() 