"""Browser tests for theme behavior and accessibility."""

from playwright.sync_api import Page, expect


def test_theme_toggle_buttons_exist(browser_page: Page):
    browser_page.goto("/")

    expect(browser_page.locator("#landing-theme-toggle")).to_be_visible()
    expect(browser_page.locator(".theme-toggle-btn")).to_have_count(3)


def test_theme_toggle_click_and_persistence(browser_page: Page):
    browser_page.goto("/")
    browser_page.evaluate("localStorage.removeItem('theme')")
    browser_page.reload()

    expect(browser_page.locator("html")).to_have_attribute("data-bs-theme", "light")
    browser_page.locator("#landing-theme-toggle").click()
    expect(browser_page.locator("html")).to_have_attribute("data-bs-theme", "dark")
    assert browser_page.evaluate("localStorage.getItem('theme')") == "dark"

    browser_page.reload()
    expect(browser_page.locator("html")).to_have_attribute("data-bs-theme", "dark")
    # The glyph is inline SVG now, not a bootstrap-icons font class, so the
    # contract is the accessible state rather than a class name: in dark mode
    # the control offers the light theme and reports itself pressed.
    toggle = browser_page.locator("#landing-theme-toggle")
    expect(toggle).to_have_attribute("aria-label", "Switch to light theme")
    expect(toggle).to_have_attribute("aria-pressed", "true")
    expect(toggle.locator("svg.icon")).to_have_count(1)


def test_theme_toggle_keyboard_accessibility(browser_page: Page):
    browser_page.goto("/")
    toggle = browser_page.locator("#landing-theme-toggle")
    initial_theme = browser_page.locator("html").get_attribute("data-bs-theme")

    toggle.focus()
    toggle.press("Enter")
    assert browser_page.locator("html").get_attribute("data-bs-theme") != initial_theme


def test_theme_system_preference_fallback(browser_page: Page):
    browser_page.add_init_script(
        """
        localStorage.removeItem('theme');
        const original = window.matchMedia.bind(window);
        window.matchMedia = query => query === '(prefers-color-scheme: dark)'
          ? {
              matches: true,
              media: query,
              onchange: null,
              addListener() {},
              removeListener() {},
              addEventListener() {},
              removeEventListener() {},
              dispatchEvent() { return false; },
            }
          : original(query);
        """
    )
    browser_page.goto("/")

    expect(browser_page.locator("html")).to_have_attribute("data-bs-theme", "dark")


def test_theme_change_is_announced(browser_page: Page):
    browser_page.goto("/")
    browser_page.locator("#landing-theme-toggle").click()

    expect(browser_page.locator('.sr-only[role="status"]')).to_contain_text("Theme changed to")
