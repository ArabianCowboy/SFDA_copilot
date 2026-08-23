"""The recovery landing: a third view in a shell that had two.

Marked at module level rather than by the filename list in `conftest.py` — that
list is legacy, and a new browser file added to it is one someone has to remember
to edit in another file.

The properties here are mostly about a view *not* appearing. A recovery session
carries a real user, and Supabase emits SIGNED_IN before PASSWORD_RECOVERY
(supabase/auth-js#349), so the chat shell opening over this form is the natural
failure and the one worth pinning hardest.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


def test_the_recovery_marker_replaces_the_landing_with_the_recovery_view(browser_page: Page):
    browser_page.goto("/?testing=true&recovery=1")

    expect(browser_page.locator("#recovery-view")).to_be_visible()
    expect(browser_page.locator("#recovery-form")).to_be_visible()
    expect(browser_page.locator("#recovery-expired")).to_be_hidden()
    expect(browser_page.locator("#unauthenticated-view")).to_be_hidden()
    expect(browser_page.locator("#authenticated-view")).to_be_hidden()


def test_a_signed_in_event_during_recovery_does_not_open_the_chat(browser_page: Page):
    """The regression that matters most.

    Supabase fires SIGNED_IN first and a recovery session has a user, so without
    the `currentView === RECOVERY` guard in auth-view.js this event drops the
    reader into the chat shell holding a session they got from an emailed link.
    """
    browser_page.goto("/?testing=true&recovery=1")
    expect(browser_page.locator("#recovery-form")).to_be_visible()

    browser_page.evaluate(
        "window.__supabaseState.authCallback?.('SIGNED_IN',"
        " { user: { id: 'test-user-id', email: 'test@example.com' }, access_token: 'fake_token' })"
    )

    expect(browser_page.locator("#authenticated-view")).to_be_hidden()
    expect(browser_page.locator("#recovery-view")).to_be_visible()


def test_an_expired_link_explains_itself_instead_of_offering_a_dead_form(browser_page: Page):
    """A marker with no session means expired, already used, or forged. Accepting
    a password that can never be saved is the worse answer."""
    browser_page.goto("/?recovery=1")

    expect(browser_page.locator("#recovery-view")).to_be_visible()
    expect(browser_page.locator("#recovery-expired")).to_be_visible()
    expect(browser_page.locator("#recovery-form")).to_be_hidden()


def test_a_mismatched_confirmation_never_reaches_the_service(browser_page: Page):
    browser_page.goto("/?testing=true&recovery=1")
    browser_page.locator("#recovery-password").fill("ValidPass1")
    browser_page.locator("#recovery-password-confirm").fill("DifferentPass1")
    browser_page.locator("#recovery-form").evaluate("(f) => f.requestSubmit()")

    expect(browser_page.locator("#recovery-error")).to_be_visible()
    assert browser_page.evaluate("window.__supabaseState.lastUserUpdate") is None


def test_a_weak_password_never_reaches_the_service(browser_page: Page):
    """Same rule as signup, reused verbatim from the signup field's pattern."""
    browser_page.goto("/?testing=true&recovery=1")
    browser_page.locator("#recovery-password").fill("weak")
    browser_page.locator("#recovery-password-confirm").fill("weak")
    browser_page.locator("#recovery-form").evaluate("(f) => f.requestSubmit()")

    assert browser_page.evaluate("window.__supabaseState.lastUserUpdate") is None


def test_cancelling_leaves_recovery_and_ends_the_session(browser_page: Page):
    """Cancel must not merely change the view. Walking away while a valid token
    sits in storage is the whole problem restated.

    The recovery session is planted first, on purpose: asserting that a key is
    absent when nothing ever wrote it passes whether or not the teardown exists.
    """
    browser_page.goto("/?testing=true&recovery=1")
    browser_page.evaluate(
        "sessionStorage.setItem('sfda-supabase-recovery', '{\"access_token\":\"planted\"}')"
    )
    assert browser_page.evaluate("sessionStorage.getItem('sfda-supabase-recovery')")

    browser_page.locator("#recovery-cancel").click()

    expect(browser_page.locator("#unauthenticated-view")).to_be_visible()
    expect(browser_page.locator("#recovery-view")).to_be_hidden()
    assert browser_page.evaluate("sessionStorage.getItem('sfda-supabase-recovery')") is None


def test_a_recovery_session_is_kept_out_of_the_readers_own_storage(browser_page: Page):
    """Supabase shares a localStorage session across every open tab. A recovery
    session written there would hand an already-open tab a token from an inbox
    as an ordinary sign-in, and the view guards only cover the tab that followed
    the link."""
    browser_page.goto("/?testing=true&recovery=1")
    expect(browser_page.locator("#recovery-form")).to_be_visible()

    assert browser_page.evaluate("localStorage.getItem('sfda-supabase-auth')") is None


def test_the_forgot_link_swaps_the_login_pane_for_the_request_form(browser_page: Page):
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#forgot-password-link").click()

    expect(browser_page.locator("#reset-request-form")).to_be_visible()
    expect(browser_page.locator("#login-form")).to_be_hidden()

    browser_page.locator("#reset-back-to-login").click()
    expect(browser_page.locator("#login-form")).to_be_visible()
    expect(browser_page.locator("#reset-request-form")).to_be_hidden()


def test_the_request_says_nothing_about_whether_the_address_exists(browser_page: Page):
    """Anti-enumeration is a server property, but the surface must not undo it by
    branching on the response."""
    browser_page.route("**/auth/recover", lambda route: route.fulfill(
        status=202, content_type="application/json", body='{"sent": true}'))

    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#forgot-password-link").click()
    browser_page.locator("#reset-email").fill("nobody@example.com")
    browser_page.locator("#reset-request-form").evaluate("(f) => f.requestSubmit()")

    sent = browser_page.locator("#reset-sent")
    expect(sent).to_be_visible()
    expect(sent).to_contain_text("if that address has an account", ignore_case=True)
    # The dead end this closes: the copy cannot confirm the address, so it has to
    # offer somewhere else to go.
    expect(sent).to_contain_text("administrator", ignore_case=True)


def test_a_rate_limited_request_is_explained_rather_than_shown_in_english(browser_page: Page):
    browser_page.route("**/auth/recover", lambda route: route.fulfill(
        status=429, content_type="application/json",
        body='{"error": "reset_rate_limited"}'))

    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#forgot-password-link").click()
    browser_page.locator("#reset-email").fill("reader@example.com")
    browser_page.locator("#reset-request-form").evaluate("(f) => f.requestSubmit()")

    error = browser_page.locator("#auth-error")
    expect(error).to_be_visible()
    # The catalogue string, not GoTrue's "For security purposes, you can only
    # request this after N seconds".
    expect(error).not_to_contain_text("security purposes")


def test_the_recovery_view_adds_no_fourth_theme_toggle(browser_page: Page):
    """Three is the number on this page; test_theme_toggle.py and test_rtl.py
    both count them in the raw HTML, and the recovery view ships in the same
    document whether or not it is showing."""
    browser_page.goto("/?testing=true&recovery=1")
    expect(browser_page.locator(".theme-toggle-btn")).to_have_count(3)


def test_recovery_does_not_reveal_the_console_link(browser_page: Page):
    browser_page.goto("/?testing=true&recovery=1")
    expect(browser_page.locator("#admin-button")).to_be_hidden()


def test_the_recovery_view_carries_the_independence_notice(browser_page: Page):
    """DESIGN.md:342 asks every surface to carry it, and this one has no footer
    to inherit it from."""
    browser_page.goto("/?testing=true&recovery=1")
    expect(browser_page.locator("#recovery-view .landing-notice")).to_be_visible()


def test_switching_language_mid_recovery_stays_in_recovery(browser_page: Page):
    """`pick_lang` ranks `?lang=` above the cookie, so a naive reload would land
    back in the language just left — and a naive strip would lose `recovery=1`
    and drop the reader onto the landing page."""
    browser_page.goto("/?testing=true&recovery=1&lang=en")
    expect(browser_page.locator("#recovery-form")).to_be_visible()

    # `visible=true`: the landing and sidebar toggles are in the DOM but hidden
    # behind `d-none`, so this has to pick the recovery view's own.
    browser_page.locator(".lang-toggle-btn").locator("visible=true").first.click()
    browser_page.wait_for_url("**recovery=1**")

    assert "lang=ar" in browser_page.url
    assert "recovery=1" in browser_page.url
    expect(browser_page.locator("html")).to_have_attribute("dir", "rtl")
    expect(browser_page.locator("#recovery-view")).to_be_visible()


def test_a_rate_limited_signup_is_not_shown_in_raw_english(browser_page: Page):
    """The bug TODO.md records: GoTrue's limiter is reachable from signup too.

    Its message is English on a bilingual surface and phrased as though the
    reader had exceeded a limit rather than the service being busy — and because
    GoTrue rolls the account back when a send fails, they get no account and no
    email either. Recovery handles this as a status code from our own endpoint;
    signup only passes through `formatAuthError`, so it needs the mapping there.
    """
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#signup-tab").click()
    browser_page.evaluate(
        "window.__supabaseState.signUpError = 'Email rate limit exceeded'"
    )
    browser_page.locator("#signup-first-name").fill("New")
    browser_page.locator("#signup-email").fill("new@example.com")
    browser_page.locator("#signup-password").fill("ValidPass1")
    browser_page.locator("#signup-form").evaluate("(f) => f.requestSubmit()")

    error = browser_page.locator("#auth-error")
    expect(error).to_be_visible()
    expect(error).not_to_contain_text("rate limit exceeded")
