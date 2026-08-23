"""Signup now asks for a name, and sends it to GoTrue as user metadata for
`handle_new_user` to read (docs/profile-refactor-plan.md §12.2, Step 4)."""

from playwright.sync_api import Page, expect


def test_first_name_is_required_by_the_form(browser_page: Page):
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#signup-tab").click()

    browser_page.locator("#signup-email").fill("new@example.com")
    browser_page.locator("#signup-password").fill("ValidPass1")
    browser_page.locator("#signup-form").evaluate("(f) => f.requestSubmit()")

    # Native validation blocks the submit — nothing was sent to GoTrue.
    assert browser_page.evaluate("window.__supabaseState.lastSignUpMetadata") is None
    expect(browser_page.locator("#signup-first-name:invalid")).to_have_count(1)


def test_family_name_is_optional(browser_page: Page):
    """A mononym reader must not be forced to invent a second name."""
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#signup-tab").click()

    browser_page.locator("#signup-first-name").fill("Cher")
    browser_page.locator("#signup-email").fill("cher@example.com")
    browser_page.locator("#signup-password").fill("ValidPass1")
    browser_page.locator("#signup-form").evaluate("(f) => f.requestSubmit()")

    expect(browser_page.locator("#signup-sent")).to_be_visible()
    metadata = browser_page.evaluate("window.__supabaseState.lastSignUpMetadata")
    assert metadata == {"first_name": "Cher", "family_name": ""}


def test_signup_sends_both_names_as_gotrue_metadata(browser_page: Page):
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#signup-tab").click()

    browser_page.locator("#signup-first-name").fill("Amina")
    browser_page.locator("#signup-family-name").fill("Al-Otaibi")
    browser_page.locator("#signup-email").fill("amina@example.com")
    browser_page.locator("#signup-password").fill("ValidPass1")
    browser_page.locator("#signup-form").evaluate("(f) => f.requestSubmit()")

    expect(browser_page.locator("#signup-sent")).to_be_visible()
    metadata = browser_page.evaluate("window.__supabaseState.lastSignUpMetadata")
    assert metadata == {"first_name": "Amina", "family_name": "Al-Otaibi"}
