import pytest
from playwright.sync_api import Page, expect
from unittest.mock import patch

@pytest.fixture(autouse=True)
def setup_supabase_env(monkeypatch):
    """Setup Supabase environment variables for testing"""
    monkeypatch.setenv('SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('SUPABASE_ANON_KEY', 'test-anon-key')

def test_profile_form_theme_sync(page: Page):
    """Test that profile form correctly syncs with current theme"""
    page.goto('/')
    
    # Mock user profile data
    mock_profile = {
        'id': 'test-user-id',
        'full_name': 'Test User',
        'organization': 'Test Organization',
        'specialization': 'Test Specialization',
        'preferences': {
            'theme': 'dark'
        }
    }
    
    # Mock Supabase session
    with patch('web.services.Services.getProfile') as mock_get_profile:
        mock_get_profile.return_value = mock_profile
        
        # Open profile modal
        page.get_by_role('button', name='Profile').click()
        
        # Check that theme radio buttons are present
        expect(page.locator('input[name="theme-preference"]')).to_have_count(2)
        
        # Check that dark theme is selected based on profile
        dark_radio = page.locator('input[name="theme-preference"][value="dark"]')
        expect(dark_radio).to_be_checked()

def test_profile_form_theme_change(page: Page):
    """Test that changing theme in profile form applies immediately"""
    page.goto('/')
    
    # Set initial theme to light
    page.locator('#landing-theme-toggle').click()
    expect(page.locator('html')).to_have_attribute('data-bs-theme', 'light')
    
    # Mock user profile data
    mock_profile = {
        'id': 'test-user-id',
        'full_name': 'Test User',
        'organization': 'Test Organization',
        'specialization': 'Test Specialization',
        'preferences': {
            'theme': 'light'
        }
    }
    
    # Mock Supabase session
    with patch('web.services.Services.getProfile') as mock_get_profile:
        mock_get_profile.return_value = mock_profile
        
        # Open profile modal
        page.get_by_role('button', name='Profile').click()
        
        # Change theme to dark in profile form
        page.locator('input[name="theme-preference"][value="dark"]').check()
        
        # Close modal (this would normally trigger the theme change)
        page.get_by_role('button', name='Close').click()
        
        # Check that theme has changed to dark
        expect(page.locator('html')).to_have_attribute('data-bs-theme', 'dark')
        
        # Check that theme toggle icon has updated
        expect(page.locator('#landing-theme-toggle i')).to_have_class('bi-sun-fill')

def test_profile_form_theme_persistence(page: Page):
    """Test that theme preference from profile is persisted"""
    page.goto('/')
    
    # Mock user profile with dark theme preference
    mock_profile = {
        'id': 'test-user-id',
        'full_name': 'Test User',
        'organization': 'Test Organization',
        'specialization': 'Test Specialization',
        'preferences': {
            'theme': 'dark'
        }
    }
    
    # Mock Supabase session
    with patch('web.services.Services.getProfile') as mock_get_profile:
        mock_get_profile.return_value = mock_profile
        
        # Open profile modal
        page.get_by_role('button', name='Profile').click()
        
        # Verify dark theme is selected
        expect(page.locator('input[name="theme-preference"][value="dark"]')).to_be_checked()
        
        # Close modal
        page.get_by_role('button', name='Close').click()
        
        # Check that dark theme is applied
        expect(page.locator('html')).to_have_attribute('data-bs-theme', 'dark')
        
        # Check that localStorage has the correct theme
        saved_theme = page.evaluate("localStorage.getItem('theme')")
        assert saved_theme == 'dark'

def test_profile_form_theme_default_fallback(page: Page):
    """Test that theme defaults to light when no preference in profile"""
    page.goto('/')
    
    # Mock user profile without theme preference
    mock_profile = {
        'id': 'test-user-id',
        'full_name': 'Test User',
        'organization': 'Test Organization',
        'specialization': 'Test Specialization',
        'preferences': {}  # No theme preference
    }
    
    # Mock Supabase session
    with patch('web.services.Services.getProfile') as mock_get_profile:
        mock_get_profile.return_value = mock_profile
        
        # Open profile modal
        page.get_by_role('button', name='Profile').click()
        
        # Verify light theme is selected by default
        expect(page.locator('input[name="theme-preference"][value="light"]')).to_be_checked()
        
        # Close modal
        page.get_by_role('button', name='Close').click()
        
        # Check that light theme is applied
        expect(page.locator('html')).to_have_attribute('data-bs-theme', 'light')

def test_profile_form_theme_update_integration(page: Page):
    """Test that profile form update correctly saves theme preference"""
    page.goto('/')
    
    # Mock initial user profile
    initial_profile = {
        'id': 'test-user-id',
        'full_name': 'Test User',
        'organization': 'Test Organization',
        'specialization': 'Test Specialization',
        'preferences': {
            'theme': 'light'
        }
    }
    
    # Mock updated user profile
    updated_profile = {
        'id': 'test-user-id',
        'full_name': 'Test User Updated',
        'organization': 'Test Organization Updated',
        'specialization': 'Test Specialization Updated',
        'preferences': {
            'theme': 'dark'
        }
    }
    
    # Mock Supabase services
    with patch('web.services.Services.getProfile') as mock_get_profile, \
         patch('web.services.Services.updateProfile') as mock_update_profile:
        
        mock_get_profile.return_value = initial_profile
        mock_update_profile.return_value = True
        
        # Open profile modal
        page.get_by_role('button', name='Profile').click()
        
        # Change theme to dark
        page.locator('input[name="theme-preference"][value="dark"]').check()
        
        # Update other profile fields
        page.locator('#profile-full-name').fill('Test User Updated')
        page.locator('#profile-organization').fill('Test Organization Updated')
        page.locator('#profile-specialization').fill('Test Specialization Updated')
        
        # Submit form
        page.get_by_role('button', name='Save Changes').click()
        
        # Check that updateProfile was called with correct theme preference
        mock_update_profile.assert_called_once()
        call_args = mock_update_profile.call_args
        assert call_args[1]['updates']['preferences']['theme'] == 'dark'
        
        # Check that theme was applied immediately
        expect(page.locator('html')).to_have_attribute('data-bs-theme', 'dark')
        
        # Check that theme toggle icon has updated
        expect(page.locator('#landing-theme-toggle i')).to_have_class('bi-sun-fill')