"""Password change (via reauthenticate()/updateUser(), never a
current-password field — GoTrue has none) and "Sign out everywhere else"
(docs/profile-refactor-plan.md §14·B·7, ·9, ·10, Step 5)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


def test_changing_password_without_reauthentication_required(authenticated_page: Page):
    page = authenticated_page
    page.goto("/account")

    page.locator("#password-new").fill("NewValidPass1")
    page.locator("#password-form").evaluate("(f) => f.requestSubmit()")

    expect(page.locator("#password-saved-note")).to_be_visible()
    expect(page.locator("#password-reauth-step")).to_be_hidden()

    sent = page.evaluate("window.__supabaseState.lastUserUpdate")
    assert sent == {"password": "NewValidPass1"}


def test_password_change_revokes_other_sessions_but_not_this_one(
    authenticated_page: Page,
):
    """OWASP's guidance: every OTHER session ends on a password change. This
    tab is mid-use, changing its own password — it must stay signed in."""
    page = authenticated_page
    page.goto("/account")

    page.locator("#password-new").fill("NewValidPass1")
    page.locator("#password-form").evaluate("(f) => f.requestSubmit()")
    expect(page.locator("#password-saved-note")).to_be_visible()

    assert page.evaluate("window.__supabaseState.lastSignOutScope") == "others"
    # Still signed in: the record is visible, not the signed-out state.
    expect(page.locator("#account-record")).to_be_visible()


def test_reauthentication_flow_when_the_server_requires_it(authenticated_page: Page):
    page = authenticated_page
    page.goto("/account")
    page.evaluate("window.__supabaseState.requireReauthentication = true")

    page.locator("#password-new").fill("NewValidPass1")
    page.locator("#password-form").evaluate("(f) => f.requestSubmit()")

    expect(page.locator("#password-reauth-step")).to_be_visible()
    assert page.evaluate("window.__supabaseState.reauthenticateSent") is True
    # Not sent to GoTrue yet — only the reauthenticate() nonce request was.
    assert page.evaluate("window.__supabaseState.lastUserUpdate") is None

    page.locator("#password-nonce").fill("123456")
    page.locator("#password-form").evaluate("(f) => f.requestSubmit()")

    expect(page.locator("#password-saved-note")).to_be_visible()
    expect(page.locator("#password-reauth-step")).to_be_hidden()
    sent = page.evaluate("window.__supabaseState.lastUserUpdate")
    assert sent == {"password": "NewValidPass1", "nonce": "123456"}


def test_a_wrong_reauthentication_code_is_reported(authenticated_page: Page):
    page = authenticated_page
    page.goto("/account")
    page.evaluate("window.__supabaseState.requireReauthentication = true")

    page.locator("#password-new").fill("NewValidPass1")
    page.locator("#password-form").evaluate("(f) => f.requestSubmit()")
    expect(page.locator("#password-reauth-step")).to_be_visible()

    page.locator("#password-nonce").fill("000000")
    page.locator("#password-form").evaluate("(f) => f.requestSubmit()")

    expect(page.locator("#password-error")).to_be_visible()
    expect(page.locator("#password-saved-note")).to_be_hidden()


def test_sign_out_others_button_ends_other_sessions_only(authenticated_page: Page):
    page = authenticated_page
    page.goto("/account")

    page.locator("#sign-out-others").click()

    expect(page.locator("#sign-out-others-note")).to_be_visible()
    assert page.evaluate("window.__supabaseState.lastSignOutScope") == "others"
    expect(page.locator("#account-record")).to_be_visible()
