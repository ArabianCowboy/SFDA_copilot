"""Signup now asks for a name, and sends it to GoTrue as user metadata for
`handle_new_user` to read (docs/profile-refactor-plan.md §12.2, Step 4)."""

import re

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
    # Required, but separate from marketing consent (docs/profile-refactor-
    # plan.md §12.4) — not ticked here on purpose, so this run also proves
    # signup succeeds with marketing consent declined.
    browser_page.locator("#signup-terms").check()
    browser_page.locator("#signup-form").evaluate("(f) => f.requestSubmit()")

    expect(browser_page.locator("#signup-sent")).to_be_visible()
    metadata = browser_page.evaluate("window.__supabaseState.lastSignUpMetadata")
    assert metadata == {"first_name": "Cher", "family_name": "", "marketing_consent": False}


def test_signup_sends_both_names_as_gotrue_metadata(browser_page: Page):
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#signup-tab").click()

    browser_page.locator("#signup-first-name").fill("Amina")
    browser_page.locator("#signup-family-name").fill("Al-Otaibi")
    browser_page.locator("#signup-email").fill("amina@example.com")
    browser_page.locator("#signup-password").fill("ValidPass1")
    browser_page.locator("#signup-terms").check()
    browser_page.locator("#signup-form").evaluate("(f) => f.requestSubmit()")

    expect(browser_page.locator("#signup-sent")).to_be_visible()
    metadata = browser_page.evaluate("window.__supabaseState.lastSignUpMetadata")
    assert metadata == {
        "first_name": "Amina",
        "family_name": "Al-Otaibi",
        "marketing_consent": False,
    }


def test_terms_acceptance_is_required_by_the_form(browser_page: Page):
    """A separate, required tick (docs/profile-refactor-plan.md §12.4) —
    never bundled with marketing consent, which stays optional."""
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#signup-tab").click()

    browser_page.locator("#signup-first-name").fill("Noura")
    browser_page.locator("#signup-email").fill("noura@example.com")
    browser_page.locator("#signup-password").fill("ValidPass1")
    browser_page.locator("#signup-form").evaluate("(f) => f.requestSubmit()")

    assert browser_page.evaluate("window.__supabaseState.lastSignUpMetadata") is None
    expect(browser_page.locator("#signup-terms:invalid")).to_have_count(1)


def test_the_terms_checkbox_links_to_the_privacy_policy(browser_page: Page):
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#signup-tab").click()

    link = browser_page.locator("#signup-form a[href='/privacy']")
    expect(link).to_have_count(1)


def test_marketing_consent_gates_the_age_field(browser_page: Page):
    """Age is asked only after consent is ticked (docs/profile-refactor-
    plan.md §12.3) — and clears again if the reader unticks it."""
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#signup-tab").click()

    reveal = browser_page.locator("#signup-age-reveal")
    expect(reveal).not_to_have_class(re.compile(r"\bis-open\b"))

    browser_page.locator("#signup-marketing-consent").check()
    expect(reveal).to_have_class(re.compile(r"\bis-open\b"))

    browser_page.locator("#signup-age").fill("34")
    browser_page.locator("#signup-marketing-consent").uncheck()
    expect(reveal).not_to_have_class(re.compile(r"\bis-open\b"))
    expect(browser_page.locator("#signup-age")).to_have_value("")


def test_signup_sends_consent_context_when_marketing_is_ticked(browser_page: Page):
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#signup-tab").click()

    browser_page.locator("#signup-first-name").fill("Sara")
    browser_page.locator("#signup-email").fill("sara@example.com")
    browser_page.locator("#signup-password").fill("ValidPass1")
    browser_page.locator("#signup-terms").check()
    browser_page.locator("#signup-marketing-consent").check()
    browser_page.locator("#signup-age").fill("29")
    browser_page.locator("#signup-form").evaluate("(f) => f.requestSubmit()")

    expect(browser_page.locator("#signup-sent")).to_be_visible()
    metadata = browser_page.evaluate("window.__supabaseState.lastSignUpMetadata")
    assert metadata["marketing_consent"] is True
    assert metadata["age"] == 29
    assert metadata["marketing_consent_language"] == "en"
    # The exact draft string is app.py's own concern (PRIVACY_POLICY_VERSION);
    # this only proves SOME version travelled with the grant, per the guard
    # trigger's own requirement that a grant without one is invalid.
    assert metadata["marketing_consent_policy_version"]
