"""bfcache restores of a signed-in page after the session ended (docs/ARCHITECTURE.md).

Playwright's default Chromium is the headless shell, which reports
BackForwardCacheDisabledForDelegate so every Back is a fresh load; a bfcache
test written against the default browser would pass vacuously. These tests
launch full Chromium with `--disable-back-forward-cache` removed from the
default arguments.

Each test proves a restore happened before asserting anything via a pageshow
recorder that lives outside the document (surviving reloads and navigations).
Scenarios cover:
- Restored chat page after the session ended elsewhere lands on fresh '/'
- Restored chat page for the same reader is revealed as it was (no reload)
- getSession error on restore reloads the same URL instead of signing out
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import (
    SSE_CHAT_MOCK,
    SUPABASE_BROWSER_MOCK,
    chat_history,
    chat_sessions,
    stored_answer,
    stored_session,
)

pytestmark = pytest.mark.browser

CONV = "c0ffee00-0000-4000-8000-000000000001"
AT_ROOT = re.compile(r"^[^?#]*://[^/]+/$")


@pytest.fixture
def bfcache_page(browser_type, base_url):
    if browser_type.name != "chromium":
        pytest.skip("bfcache restore is exercised on Chromium only")
    browser = browser_type.launch(
        channel="chromium", ignore_default_args=["--disable-back-forward-cache"]
    )
    context = browser.new_context(base_url=base_url)
    context.add_init_script("window.__mockSessionFromStorage = true;")
    shows = []
    context.expose_binding(
        "__recordPageshow",
        lambda source, persisted, path: shows.append({"persisted": persisted, "path": path}),
    )
    context.add_init_script(
        "window.addEventListener('pageshow', (e) => window.__recordPageshow(e.persisted, location.pathname));"
    )
    context.route(
        "**/@supabase/supabase-js@2.74.0/+esm",
        lambda r: r.fulfill(
            status=200, content_type="application/javascript", body=SUPABASE_BROWSER_MOCK
        ),
    )
    context.route(
        "**/api/chat/stream",
        lambda r: r.fulfill(status=200, content_type="text/event-stream", body=SSE_CHAT_MOCK),
    )
    context.route(
        "**/api/chat/history*",
        lambda r: r.fulfill(
            status=200,
            content_type="application/json",
            body=chat_history(
                stored_answer("Reader A's question", "Reader A's answer"),
                conversation_id=CONV,
            ),
        ),
    )
    context.route(
        "**/api/chat/sessions",
        lambda r: r.fulfill(
            status=200,
            content_type="application/json",
            body=chat_sessions([stored_session(CONV, "Reader A sidebar title")]),
        ),
    )
    page = context.new_page()
    page.shows = shows  # the recorder survives reloads; the page's own JS state does not
    yield page
    context.close()
    browser.close()


def _sign_in(page: Page) -> None:
    page.goto("/")
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill("reader-a@example.com")
    page.locator("#login-password").fill("password123")
    page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#authenticated-view").wait_for(state="visible")


def _sign_in_and_open(page: Page) -> None:
    _sign_in(page)
    page.goto(f"/c/{CONV}")
    expect(page.get_by_text("Reader A's answer")).to_be_visible()
    expect(page.locator("#history-sidebar-section .history-item")).to_have_count(1)


def _leave(page: Page) -> None:
    page.goto("/privacy")


def _come_back(page: Page) -> None:
    page.go_back(wait_until="commit")


def _assert_restored(page: Page) -> None:
    assert any(s["persisted"] and s["path"] == f"/c/{CONV}" for s in page.shows), (
        f"bfcache was not used — this test proves nothing. pageshow log: {page.shows}"
    )


def test_restored_chat_page_after_session_ended_elsewhere_lands_on_fresh_root(
    bfcache_page: Page,
) -> None:
    """Restored chat page after session ended elsewhere lands on a fresh '/' without reader A."""
    page = bfcache_page
    _sign_in_and_open(page)
    _leave(page)
    page.evaluate("() => localStorage.removeItem('__mock_supabase_user')")
    _come_back(page)
    expect(page.locator("#unauthenticated-view")).to_be_visible()
    _assert_restored(page)
    expect(page).to_have_url(AT_ROOT)
    assert "reader-a@example.com" not in page.locator("body").inner_text()
    expect(page.locator("#history-sidebar-section .history-item")).to_have_count(0)
    assert page.evaluate("() => document.body.hidden") is False


def test_restored_chat_page_for_same_reader_is_revealed_as_it_was(
    bfcache_page: Page,
) -> None:
    """Restored chat page for the same reader is revealed as it was (no reload)."""
    page = bfcache_page
    _sign_in_and_open(page)
    page.evaluate("() => { window.__noReload = true; }")
    _leave(page)
    _come_back(page)
    expect(page.get_by_text("Reader A's answer")).to_be_visible()
    _assert_restored(page)
    expect(page).to_have_url(re.compile(rf"/c/{CONV}$"))
    expect(page.locator("#authenticated-view")).to_be_visible()
    assert page.evaluate("() => window.__noReload === true")
    assert page.evaluate("() => document.body.hidden") is False


def test_get_session_error_on_restore_reloads_same_url(
    bfcache_page: Page,
) -> None:
    """A getSession error on restore reloads the same URL instead of signing the reader out."""
    page = bfcache_page
    _sign_in_and_open(page)
    page.evaluate("() => { window.__supabaseState.sessionError = 'storage unavailable'; }")
    _leave(page)
    _come_back(page)
    expect(page.locator("#authenticated-view")).to_be_visible()
    _assert_restored(page)
    expect(page).to_have_url(re.compile(rf"/c/{CONV}$"))
    assert page.evaluate("() => performance.getEntriesByType('navigation')[0].type") == "reload"
    assert page.shows[-1]["persisted"] is False


def test_restored_account_page_after_the_session_ended_elsewhere_shows_the_signed_out_state(
    bfcache_page: Page,
) -> None:
    """Restored /account page after session ended elsewhere reloads into signed-out state."""
    page = bfcache_page
    _sign_in(page)
    page.goto("/account")
    expect(page.locator("#account-email")).to_have_text("reader-a@example.com")
    _leave(page)
    page.evaluate("() => localStorage.removeItem('__mock_supabase_user')")
    _come_back(page)
    expect(page.locator("#account-signed-out")).to_be_visible()
    assert any(s["persisted"] and s["path"] == "/account" for s in page.shows), (
        f"bfcache was not used — this test proves nothing. pageshow log: {page.shows}"
    )
    assert "reader-a@example.com" not in page.locator("body").inner_text()
