"""URL reset and teardown when a reader signs out, expires, or changes.

When a reader's session ends at /c/<id>, the client resets the address bar
to "/" via Route.replace without reloading the page, empties the composer
draft, dismisses transient quota notices, and clears transcript messages.
History traversals (Back/Forward) into a conversation when confirmed signed-out
scrub the route to "/", while transient getSession errors do not bounce
signed-in readers. Direct switches between readers tear down reader A's
local state before hydrating reader B, and in-flight operations that outlive
a sign-out or reader switch are discarded.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import chat_history, route_chat_history, stored_answer

pytestmark = pytest.mark.browser

CONV = "c0ffee00-0000-4000-8000-000000000001"
AT_ROOT = re.compile(r"^[^?#]*://[^/]+/$")


def _sign_in(page: Page, email: str = "reader-a@example.com") -> None:
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill(email)
    page.locator("#login-password").fill("password123")
    page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#authenticated-view").wait_for(state="visible")
    page.locator("#authModal").wait_for(state="hidden")


def _revoke(page: Page) -> None:
    page.evaluate(
        "() => {"
        "  const s = window.__supabaseState;"
        "  s.user = null;"
        "  localStorage.removeItem('__mock_supabase_user');"
        "  return s.authCallback('SIGNED_OUT', null);"
        "}"
    )


def _switch_to_reader_b(page: Page) -> None:
    page.evaluate(
        "() => {"
        "  const s = window.__supabaseState;"
        "  const session = {"
        "    access_token: 'fake_token',"
        "    user: { id: 'reader-b-id', email: 'reader-b@example.com' },"
        "  };"
        "  s.user = session.user;"
        "  localStorage.setItem('__mock_supabase_user', JSON.stringify(session.user));"
        "  return s.authCallback('SIGNED_IN', session);"
        "}"
    )


def _open_conversation(page: Page, query: str = "") -> None:
    route_chat_history(
        page,
        chat_history(
            stored_answer("Reader A's question", "Reader A's answer"),
            conversation_id=CONV,
        ),
    )
    page.goto("/")
    _sign_in(page)
    page.goto(f"/c/{CONV}{query}")
    expect(page.locator("#authenticated-view")).to_be_visible()
    expect(page.get_by_text("Reader A's answer")).to_be_visible()


def _mark_no_reload(page: Page) -> None:
    page.evaluate("() => { window.__noReload = true; }")


def _still_same_document(page: Page) -> bool:
    return bool(page.evaluate("() => window.__noReload === true"))


def test_revocation_at_conversation_resets_url_without_reload(browser_page: Page) -> None:
    """Revocation at /c/<id> resets the URL to / without reloading the page.

    Route.replace replaces the path in-place, the unauthenticated landing view
    becomes visible, turns are emptied, history state convId is null, and the
    marker proves no reload occurred.
    """
    page = browser_page
    _open_conversation(page)
    _mark_no_reload(page)
    _revoke(page)

    expect(page).to_have_url(AT_ROOT)
    expect(page.locator("#unauthenticated-view")).to_be_visible()
    expect(page.locator(".chatbot-message")).to_have_count(0)
    expect(page.locator(".user-message")).to_have_count(0)
    assert page.evaluate("() => history.state && history.state.convId") is None
    assert _still_same_document(page)


def test_revocation_url_reset_preserves_query_params(browser_page: Page) -> None:
    """The URL reset preserves query parameters like ?lang=ar."""
    page = browser_page
    _open_conversation(page, "?lang=ar")
    _revoke(page)
    expect(page).to_have_url(re.compile(r"/\?lang=ar$"))


def test_signed_out_cold_deep_link_keeps_its_path(browser_page: Page) -> None:
    """A signed-out cold deep link keeps its path across INITIAL_SESSION.

    The auth listener's INITIAL_SESSION event reports no session during startup,
    which must not scrub the deep link URL or trigger a reset (§4.5).
    """
    page = browser_page
    page.goto(f"/c/{CONV}")
    expect(page.locator("#unauthenticated-view")).to_be_visible()
    page.evaluate("() => window.__supabaseState.authCallback('INITIAL_SESSION', null)")
    expect(page).to_have_url(re.compile(rf"/c/{CONV}$"))


def test_back_into_previous_reader_conversation_after_revocation_is_scrubbed(
    browser_page: Page,
) -> None:
    """Traversing Back into an earlier conversation after revocation is scrubbed.

    When getSession confirms no session, handlePopState replaces the URL to /
    and does not fetch history for the previous reader's conversation.
    """
    page = browser_page
    _open_conversation(page)
    page.locator(".new-chat-btn").locator("visible=true").first.click()
    expect(page).to_have_url(AT_ROOT)
    _revoke(page)

    history_requests: list[str] = []
    page.on(
        "request",
        lambda r: history_requests.append(r.url) if "/api/chat/history" in r.url else None,
    )
    page.go_back()
    expect(page).to_have_url(AT_ROOT)
    assert page.evaluate("() => history.state && history.state.convId") is None
    assert history_requests == []


def test_get_session_error_during_back_does_not_bounce_signed_in_reader(
    browser_page: Page,
) -> None:
    """A getSession error during Back does not bounce a signed-in reader.

    An error represents unknown session state, not absence, so the handler
    falls through to the normal hydration path rather than scrubbing to /.
    """
    page = browser_page
    _open_conversation(page)
    page.locator(".new-chat-btn").locator("visible=true").first.click()
    expect(page).to_have_url(AT_ROOT)

    page.evaluate("() => { window.__supabaseState.sessionErrorOnce = 'lock contention'; }")
    page.go_back()
    expect(page).to_have_url(re.compile(rf"/c/{CONV}$"))
    expect(page.get_by_text("Reader A's answer")).to_be_visible()
    assert page.evaluate("() => window.__supabaseState.sessionErrorOnce") is None


def test_composer_draft_and_quota_notice_do_not_survive_revocation_or_reach_reader_b(
    browser_page: Page,
) -> None:
    """The composer draft and quota notice do not survive revocation or reach reader B.

    Teardown clears #query-input and removes #quota-notice so reader A's unsent
    question and quota state do not leak to the landing view or to reader B.
    """
    page = browser_page
    page.goto("/")
    _sign_in(page)

    page.context.route(
        "**/api/chat/stream",
        lambda route: route.fulfill(
            status=429,
            content_type="application/json",
            body='{"error":"quota_exhausted","used":200,"limit":200,"remaining":0,"resets_at":"2026-09-12T00:00:00Z"}',
        ),
    )
    page.locator("#query-input").fill("Reader A's unsent question")
    page.locator("#send-button").click()
    expect(page.locator("#quota-notice")).to_be_visible()
    expect(page.locator("#query-input")).to_have_value("Reader A's unsent question")

    _revoke(page)
    expect(page.locator("#query-input")).to_have_value("")
    expect(page.locator("#quota-notice")).to_have_count(0)

    _switch_to_reader_b(page)
    expect(page.locator("#authenticated-view")).to_be_visible()
    expect(page.locator("#query-input")).to_have_value("")
    expect(page.locator("#quota-notice")).to_have_count(0)


def test_chat_request_whose_token_read_outlives_sign_out_writes_no_url_and_sends_nothing(
    browser_page: Page,
) -> None:
    """A chat request whose token read outlives sign-out writes no URL and sends nothing.

    If sign-out occurs while awaiting the session token, processChatRequestInternal
    detects the generation change and returns before minting an ID or calling Route.enter.
    """
    page = browser_page
    page.goto("/")
    _sign_in(page)
    expect(page.locator("#authenticated-view")).to_be_visible()

    stream_requests: list[str] = []
    page.on(
        "request",
        lambda r: stream_requests.append(r.url) if "/api/chat/stream" in r.url else None,
    )
    page.evaluate(
        "() => { window.__supabaseState.getSessionGate = new Promise((r) => { window.__releaseGetSession = r; }); }"
    )
    page.locator("#query-input").fill("Reader A's late question")
    page.locator("#send-button").click()
    expect(page.locator(".user-message")).to_have_count(1)

    _revoke(page)
    page.evaluate(
        "() => { window.__supabaseState.getSessionGate = null; window.__releaseGetSession(); }"
    )
    expect(page.locator("#query-input")).to_be_enabled()
    expect(page).to_have_url(AT_ROOT)
    assert stream_requests == []


def test_direct_reader_switch_at_conversation_resets_url_and_discards_stale_identity(
    browser_page: Page,
) -> None:
    """A direct reader switch at /c/<id> resets the URL, empties composer, and discards stale identity.

    Reader B lands on / without reader A's conversation, composer draft, or admin affordance.
    Reader B's identity call joins reader A's in-flight request and logs identityMismatch,
    while reader A's late answer is discarded without rendering the admin link.
    """
    page = browser_page
    route_chat_history(
        page,
        chat_history(
            stored_answer("Reader A's question", "Reader A's answer"),
            conversation_id=CONV,
        ),
    )
    held: list = []
    page.route("**/api/identity", lambda route: held.append(route))
    page.goto(f"/c/{CONV}")
    expect(page.locator("#unauthenticated-view")).to_be_visible()

    with page.expect_request("**/api/identity"):
        _sign_in(page)

    expect(page.get_by_text("Reader A's answer")).to_be_visible()
    assert held

    page.locator("#query-input").fill("Reader A's draft")
    _switch_to_reader_b(page)

    expect(page).to_have_url(AT_ROOT)
    expect(page.locator(".chatbot-message")).to_have_count(0)
    expect(page.locator(".user-message")).to_have_count(0)
    expect(page.locator("#query-input")).to_have_value("")

    with page.expect_console_message(lambda m: "identityMismatch" in m.text):
        for route in held:
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"user_id":"test-user-id","email":"reader-a@example.com","role":"admin","tier":"free","is_admin":true,"is_resolved":true}',
            )

    expect(page.locator("#admin-button")).to_have_class(re.compile(r"(?:^|\s)d-none(?:\s|$)"))
