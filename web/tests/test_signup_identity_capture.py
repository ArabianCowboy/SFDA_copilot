"""Signup now asks for a name, and sends it to GoTrue as user metadata for
`handle_new_user` to read (docs/profile-refactor-plan.md §12.2, Step 4).

Registrations-pause migration (docs/registrations-pause-plan.md §9 Step 6):
`Services.signup` no longer calls the browser-side Supabase double directly —
it POSTs to our own `/auth/signup`, which is the only place an operator's
pause can actually be enforced. The live test server's `get_supabase()`
answers `None` under `FLASK_TESTING` (by design — see
`web/utils/supabase_client.py`), so a real round trip through that route
would always 503. These tests intercept the request itself instead, the same
way `test_password_recovery.py` already intercepts `/auth/recover`: it keeps
the assertion about what the CLIENT sends, drops any dependency on the Flask
double's provider behaviour, and guarantees no test ever sends real mail.
"""

import re

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture
def signup_capture(browser_page: Page):
    """Every body POSTed to `/auth/signup` in this test, fulfilled as a
    deterministic success so the form's own success path (`#signup-sent`)
    still runs exactly as it does against the real route."""
    sent = []

    def capture(route):
        sent.append(route.request.post_data_json)
        route.fulfill(
            status=201,
            content_type="application/json",
            body='{"message":"User created successfully",'
            '"user":{"id":"u1","email":"new@example.com"}}',
        )

    browser_page.context.route("**/auth/signup", capture)
    return sent


def test_first_name_is_required_by_the_form(browser_page: Page, signup_capture):
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#signup-tab").click()

    browser_page.locator("#signup-email").fill("new@example.com")
    browser_page.locator("#signup-password").fill("ValidPass1")
    browser_page.locator("#signup-form").evaluate("(f) => f.requestSubmit()")

    # Native validation blocks the submit — nothing was sent.
    assert signup_capture == []
    expect(browser_page.locator("#signup-first-name:invalid")).to_have_count(1)


def test_family_name_is_optional(browser_page: Page, signup_capture):
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
    assert len(signup_capture) == 1
    sent = signup_capture[0]
    assert sent["first_name"] == "Cher"
    assert sent["family_name"] == ""
    assert sent["marketing_consent"] is False
    assert "age" not in sent


def test_signup_sends_both_names_as_signup_metadata(browser_page: Page, signup_capture):
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
    assert len(signup_capture) == 1
    sent = signup_capture[0]
    assert sent["first_name"] == "Amina"
    assert sent["family_name"] == "Al-Otaibi"
    assert sent["marketing_consent"] is False
    assert sent["email"] == "amina@example.com"


def test_terms_acceptance_is_required_by_the_form(browser_page: Page, signup_capture):
    """A separate, required tick (docs/profile-refactor-plan.md §12.4) —
    never bundled with marketing consent, which stays optional."""
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#signup-tab").click()

    browser_page.locator("#signup-first-name").fill("Noura")
    browser_page.locator("#signup-email").fill("noura@example.com")
    browser_page.locator("#signup-password").fill("ValidPass1")
    browser_page.locator("#signup-form").evaluate("(f) => f.requestSubmit()")

    assert signup_capture == []
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


def test_signup_sends_consent_context_when_marketing_is_ticked(browser_page: Page, signup_capture):
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
    assert len(signup_capture) == 1
    sent = signup_capture[0]
    # `True`/`29`, not the strings "true"/"29" — `handle_new_user` tests
    # `jsonb_typeof(marketing_consent) = 'boolean'` and a stringified value
    # would silently become a declined consent for the whole account.
    assert sent["marketing_consent"] is True
    assert sent["age"] == 29
    assert sent["marketing_consent_language"] == "en"
    # The exact draft string is app.py's own concern (PRIVACY_POLICY_VERSION);
    # this only proves SOME version travelled with the grant, per the guard
    # trigger's own requirement that a grant without one is invalid.
    assert sent["marketing_consent_policy_version"]
