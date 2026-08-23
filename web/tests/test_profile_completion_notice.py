"""The first-run completion strip: queued behind the history notice rather
than suppressed by it (docs/profile-refactor-plan.md §12.6), shown only for
a blank `first_name`, and reachable at all only after a profile read
resolves — the exact identity-guarded callback TODO.md's "A late profile
read has no identity guard" entry once named as missing it.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


HISTORY_NOTICE = "#history-notice"
PROFILE_NOTICE = "#profile-notice"


def _sign_in_with_blank_name(page: Page, email: str = "test@example.com") -> None:
    page.goto("/")
    page.evaluate("window.__supabaseState.profile.first_name = ''")
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill(email)
    page.locator("#login-password").fill("password123")
    page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#authenticated-view").wait_for(state="visible")


def test_the_strip_appears_after_the_history_notice_is_dismissed(browser_page: Page):
    """The bug the first design had: returning early while the history
    notice is on screen hides the strip from exactly the new readers it
    targets, because dismissing that notice does not re-run anything.
    Queuing means the strip draws right after."""
    page = browser_page
    _sign_in_with_blank_name(page)

    expect(page.locator(HISTORY_NOTICE)).to_be_visible()
    expect(page.locator(PROFILE_NOTICE)).to_have_count(0)

    page.locator(".history-notice-dismiss").click()
    expect(page.locator(PROFILE_NOTICE)).to_be_visible()
    expect(page.locator(PROFILE_NOTICE)).to_contain_text("Add your name")


def test_the_strip_draws_immediately_once_history_notice_is_already_acknowledged(
    browser_page: Page,
):
    """Second sign-in on the same device: the history notice was already
    dismissed in an earlier session, so nothing is queued behind — the
    strip just draws."""
    page = browser_page
    _sign_in_with_blank_name(page)
    page.locator(".history-notice-dismiss").click()
    page.locator("#logout-button").click()
    page.locator("#unauthenticated-view").wait_for(state="visible")

    page.evaluate("window.__supabaseState.profile.first_name = ''")
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill("test@example.com")
    page.locator("#login-password").fill("password123")
    page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#authenticated-view").wait_for(state="visible")

    expect(page.locator(HISTORY_NOTICE)).to_have_count(0)
    expect(page.locator(PROFILE_NOTICE)).to_be_visible()


def test_the_strip_is_not_shown_when_first_name_is_present(browser_page: Page):
    """The mocked profile (conftest.py) carries first_name: 'Test' by
    default — the ordinary case, and the strip must stay silent for it."""
    page = browser_page
    page.goto("/")
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill("test@example.com")
    page.locator("#login-password").fill("password123")
    page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#authenticated-view").wait_for(state="visible")

    page.locator(".history-notice-dismiss").click()
    expect(page.locator(PROFILE_NOTICE)).to_have_count(0)


def test_the_open_link_goes_to_account(browser_page: Page):
    page = browser_page
    _sign_in_with_blank_name(page)
    page.locator(".history-notice-dismiss").click()

    link = page.locator(".profile-notice-open")
    expect(link).to_be_visible()
    assert link.get_attribute("href") == "/account"


def test_dismissing_the_strip_survives_a_reload(browser_page: Page):
    page = browser_page
    _sign_in_with_blank_name(page)
    page.locator(".history-notice-dismiss").click()
    expect(page.locator(PROFILE_NOTICE)).to_be_visible()

    page.locator("#profile-notice .history-notice-dismiss").click()
    expect(page.locator(PROFILE_NOTICE)).to_have_count(0)

    page.reload()
    page.locator("#authenticated-view").wait_for(state="visible")
    expect(page.locator(PROFILE_NOTICE)).to_have_count(0)


def test_new_chat_does_not_sweep_the_strip_away(browser_page: Page):
    """The same non-turn contract the history notice already relies on
    (isTranscriptTurn), extended to cover a second notice via
    `data-non-turn` rather than a third hardcoded id."""
    page = browser_page
    _sign_in_with_blank_name(page)
    page.locator(".history-notice-dismiss").click()
    expect(page.locator(PROFILE_NOTICE)).to_be_visible()

    page.locator("#query-input").fill("What must the PSSF contain?")
    page.locator("#send-button").click()
    expect(page.locator(".chatbot-message")).to_have_count(1)

    page.locator(".new-chat-btn").locator("visible=true").first.click()
    expect(page.locator(".chatbot-message")).to_have_count(0)
    expect(page.locator(PROFILE_NOTICE)).to_be_visible()
