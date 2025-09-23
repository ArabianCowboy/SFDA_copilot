import pytest
from playwright.sync_api import Page, expect
from unittest.mock import patch

@pytest.fixture(autouse=True)
def setup_supabase_env(monkeypatch):
    """Setup Supabase environment variables for testing"""
    monkeypatch.setenv('SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('SUPABASE_ANON_KEY', 'test-anon-key')

def test_theme_toggle_buttons_exist(page: Page):
    """Test that theme toggle buttons exist in the HTML"""
    page.goto('/')
    
    # Check that theme toggle buttons are present in the HTML
    expect(page.locator('#landing-theme-toggle')).to_be_visible()
    expect(page.locator('#sidebar-theme-toggle')).to_be_visible()
    expect(page.locator('#offcanvas-theme-toggle')).to_be_visible()
    
    # Check that all buttons have the correct class
    expect(page.locator('.theme-toggle-btn')).to_have_count(3)

def test_theme_toggle_initial_state(page: Page):
    """Test that theme toggle buttons have correct initial state"""
    page.goto('/')
    
    # Check initial icon (should be moon for light theme)
    landing_toggle = page.locator('#landing-theme-toggle')
    sidebar_toggle = page.locator('#sidebar-theme-toggle')
    offcanvas_toggle = page.locator('#offcanvas-theme-toggle')
    
    expect(landing_toggle.locator('i')).to_have_class('bi-moon-fill')
    expect(sidebar_toggle.locator('i')).to_have_class('bi-moon-fill')
    expect(offcanvas_toggle.locator('i')).to_have_class('bi-moon-fill')
    
    # Check initial title and aria-label
    expect(landing_toggle).to_have_attribute('title', 'Toggle theme between light and dark')
    expect(landing_toggle).to_have_attribute('aria-label', 'Toggle theme between light and dark')

def test_theme_toggle_click_functionality(page: Page):
    """Test that theme toggle buttons work correctly on click"""
    page.goto('/')
    
    # Get initial theme
    initial_theme = page.evaluate("document.documentElement.getAttribute('data-bs-theme')")
    assert initial_theme in ['light', 'dark']
    
    # Click landing theme toggle
    page.locator('#landing-theme-toggle').click()
    
    # Check that theme has changed
    new_theme = page.evaluate("document.documentElement.getAttribute('data-bs-theme')")
    assert new_theme != initial_theme
    
    # Check that icon has changed
    if initial_theme == 'light':
        expect(page.locator('#landing-theme-toggle i')).to_have_class('bi-sun-fill')
    else:
        expect(page.locator('#landing-theme-toggle i')).to_have_class('bi-moon-fill')

def test_theme_toggle_keyboard_accessibility(page: Page):
    """Test that theme toggle buttons work with keyboard navigation"""
    page.goto('/')
    
    # Focus on landing theme toggle
    landing_toggle = page.locator('#landing-theme-toggle')
    landing_toggle.focus()
    
    # Test Enter key
    landing_toggle.press('Enter')
    
    # Check that theme has changed
    new_theme = page.evaluate("document.documentElement.getAttribute('data-bs-theme')")
    assert new_theme in ['light', 'dark']
    
    # Test Space key
    landing_toggle.press(' ')
    
    # Check that theme has changed back
    final_theme = page.evaluate("document.documentElement.getAttribute('data-bs-theme')")
    assert final_theme != new_theme

def test_theme_persistence(page: Page):
    """Test that theme preference is persisted in localStorage"""
    page.goto('/')
    
    # Set theme to dark
    page.locator('#landing-theme-toggle').click()
    
    # Check that theme is saved to localStorage
    saved_theme = page.evaluate("localStorage.getItem('theme')")
    assert saved_theme == 'dark'
    
    # Refresh page
    page.reload()
    
    # Check that theme is still applied
    current_theme = page.evaluate("document.documentElement.getAttribute('data-bs-theme')")
    assert current_theme == 'dark'
    
    # Check that icon is correct
    expect(page.locator('#landing-theme-toggle i')).to_have_class('bi-sun-fill')

def test_theme_system_preference_fallback(page: Page):
    """Test that theme system preference is used as fallback"""
    # Mock system preference for dark theme
    with patch('window.matchMedia') as mock_match_media:
        mock_match_media.return_value.matches = True
        
        page.goto('/')
        
        # Check that dark theme is applied based on system preference
        current_theme = page.evaluate("document.documentElement.getAttribute('data-bs-theme')")
        assert current_theme == 'dark'

def test_theme_toggle_visual_feedback(page: Page):
    """Test that theme toggle buttons provide visual feedback"""
    page.goto('/')
    
    # Get initial transform value
    initial_transform = page.evaluate("document.querySelector('#landing-theme-toggle').style.transform")
    
    # Click theme toggle
    page.locator('#landing-theme-toggle').click()
    
    # Check that transform animation was applied
    page.wait_for_function("document.querySelector('#landing-theme-toggle').style.transform.includes('scale')")
    
    # Check that transform returns to normal after animation
    page.wait_for_timeout(200)
    final_transform = page.evaluate("document.querySelector('#landing-theme-toggle').style.transform")
    assert final_transform == 'scale(1)'

def test_theme_toggle_accessibility_announcement(page: Page):
    """Test that theme changes are announced to screen readers"""
    page.goto('/')
    
    # Mock screen reader announcement
    announcements = []
    page.evaluate("""
        const originalAppendChild = document.body.appendChild;
        document.body.appendChild = function(child) {
            if (child.getAttribute && child.getAttribute('role') === 'status') {
                window.__themeAnnouncements = window.__themeAnnouncements || [];
                window.__themeAnnouncements.push(child.textContent);
            }
            return originalAppendChild.call(this, child);
        };
    """)
    
    # Click theme toggle
    page.locator('#landing-theme-toggle').click()
    
    # Check that announcement was made
    announcement = page.evaluate("window.__themeAnnouncements && window.__themeAnnouncements[0]")
    assert announcement is not None
    assert 'Theme changed to' in announcement