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

import json
import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import (
    chat_history,
    chat_sessions,
    route_chat_history,
    route_chat_sessions,
    stored_answer,
    stored_session,
)

pytestmark = pytest.mark.browser

CONV = "c0ffee00-0000-4000-8000-000000000001"
CONV2 = "c0ffee00-0000-4000-8000-000000000002"
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
    expect(
        page.locator("#query-input")
    ).to_be_enabled()  # the teardown, not the stale request, re-enabled the composer
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


def _notification(**overrides):
    row = {
        "id": "11111111-1111-4111-8111-111111111111",
        "type": "toast",
        "severity": "info",
        "title": "Scheduled maintenance",
        "body": "The service will be briefly unavailable tonight.",
        "requires_ack": False,
        "created_at": "2026-08-23T20:00:00+00:00",
        "expires_at": None,
        "deactivated_at": None,
        "read_at": None,
        "dismissed_at": None,
        "acknowledged_at": None,
    }
    row.update(overrides)
    return row


def _route_active(page: Page, notifications) -> None:
    page.context.route(
        "**/api/notifications/active*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"notifications": notifications}),
        ),
    )


def _route_history(page: Page, notifications, next_cursor=None) -> None:
    page.context.route(
        "**/api/notifications/history*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"notifications": notifications, "next_cursor": next_cursor}),
        ),
    )


def _route_mark_read(page: Page, calls: list) -> None:
    def handle(route):
        calls.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True}),
        )

    page.context.route("**/api/notifications/mark-read", handle)


def _snooze_keys(page: Page):
    return page.evaluate(
        "() => Object.keys(sessionStorage).filter((k) => k.startsWith('sfda-notif-snooze-'))"
    )


def test_notification_surfaces_do_not_survive_revocation_or_reach_reader_b(
    browser_page: Page,
) -> None:
    """Notification toasts, banner and modal do not survive revocation or reach reader B.

    Teardown removes active toasts, hides and empties the banner and modal without
    triggering dismissal or acknowledgement receipts, clears session-scoped snoozes,
    and ensures reader B sees no active surfaces.
    """
    page = browser_page
    calls = []
    _route_mark_read(page, calls)
    _route_active(
        page,
        [
            _notification(id="n-toast", type="toast", title="Reader A toast"),
            _notification(id="n-banner", type="banner", title="Reader A banner"),
            _notification(id="n-modal", type="modal", requires_ack=True, title="Reader A modal"),
        ],
    )
    page.goto("/")
    _sign_in(page)
    expect(page.locator(".broadcast-toast")).to_have_count(1)
    expect(page.locator("#notifications-banner")).to_have_class(
        re.compile(r"(?:^|\s)is-open(?:\s|$)")
    )
    modal = page.locator("#notifications-modal")
    expect(modal).to_be_visible()
    page.evaluate("() => sessionStorage.setItem('sfda-notif-snooze-older', '1')")
    _route_active(page, [])  # reader B will have no active notifications
    _revoke(page)
    expect(page.locator(".broadcast-toast")).to_have_count(0)
    expect(page.locator("#notifications-banner")).not_to_have_class(
        re.compile(r"(?:^|\s)is-open(?:\s|$)")
    )
    expect(page.locator("#notifications-banner")).to_have_text("")
    expect(modal).to_be_hidden()
    expect(modal.locator(".broadcast-modal-title")).to_have_text("")
    assert _snooze_keys(page) == []
    assert calls == []
    _switch_to_reader_b(page)
    expect(page.locator("#authenticated-view")).to_be_visible()
    expect(page.locator(".broadcast-toast")).to_have_count(0)
    expect(modal).to_be_hidden()
    assert calls == []


def test_inbox_modal_is_closed_and_emptied_by_revocation(browser_page: Page) -> None:
    """The notification inbox is closed and emptied by a revocation.

    When a session ends, the inbox modal is transition-safely hidden, its loading
    state is reset, and its rendered list is cleared so reader A's rows do not linger.
    """
    page = browser_page
    _route_active(page, [])
    _route_history(page, [_notification(id="h1", title="Reader A inbox row")])
    page.goto("/")
    _sign_in(page)
    page.locator("#notifications-bell-button").click()
    inbox = page.locator("#notifications-inbox-modal")
    expect(inbox).to_be_visible()
    expect(page.locator(".notifications-inbox-item")).to_have_count(1)
    _revoke(page)
    expect(inbox).to_be_hidden()
    expect(page.locator(".notifications-inbox-item")).to_have_count(0)


def test_late_inbox_response_for_reader_a_is_discarded_after_teardown(
    browser_page: Page,
) -> None:
    """A late inbox page for reader A is discarded after teardown.

    readerGeneration guard drops an in-flight history fetch resolving after sign-out,
    leaving the inbox empty with reset cursor state.
    """
    page = browser_page
    page.goto("/")
    _sign_in(page)
    result = page.evaluate(
        """async () => {
      const { Handlers } = await import('/static/js/modules/handlers.js');
      const { Services } = await import('/static/js/modules/services.js');
      const { AppState } = await import('/static/js/modules/state.js');
      let release;
      Services.notifications.fetchHistory = () => new Promise((r) => { release = r; });
      const pending = Handlers.loadNotificationHistory({ reset: true });
      const s = window.__supabaseState;
      s.user = null; localStorage.removeItem('__mock_supabase_user');
      await s.authCallback('SIGNED_OUT', null);
      release({
        notifications: [{
          id: 'a1',
          type: 'toast',
          severity: 'info',
          title: "Reader A late row",
          body: 'x',
          created_at: '2026-09-11T00:00:00+00:00',
          read_at: null,
        }],
        next_cursor: 'cursor-a',
      });
      await pending;
      return {
        rows: document.querySelectorAll('.notifications-inbox-item').length,
        items: (AppState.get('notificationsHistoryItems') || []).length,
        cursor: AppState.get('notificationsHistoryCursor'),
      };
    }"""
    )
    assert result == {"rows": 0, "items": 0, "cursor": None}


def test_late_mark_read_failure_for_reader_a_shows_reader_b_no_error(
    browser_page: Page,
) -> None:
    """A late mark-read failure for reader A shows reader B no error toast.

    readerGeneration guard suppresses error handling for an in-flight mark-read
    request that fails after reader A has signed out.
    """
    page = browser_page
    page.goto("/")
    _sign_in(page)
    toast_text = page.evaluate(
        """async () => {
      const { Handlers } = await import('/static/js/modules/handlers.js');
      const { Services } = await import('/static/js/modules/services.js');
      let fail;
      Services.notifications.markRead = () => new Promise((_, reject) => { fail = reject; });
      const pending = Handlers.markNotificationRead('n1', 'dismissed');
      const s = window.__supabaseState;
      s.user = null; localStorage.removeItem('__mock_supabase_user');
      await s.authCallback('SIGNED_OUT', null);
      fail(Object.assign(new Error('boom'), { status: 500 }));
      await pending;
      return document.getElementById('toast')?.textContent || '';
    }"""
    )
    assert "Could not update that notification." not in toast_text


def test_back_between_conversations_clears_the_old_transcript_before_the_session_check(
    browser_page: Page,
) -> None:
    """Traversing Back between conversations clears the old transcript synchronously.

    The transcript is cleared before awaiting getSessionToken so a slow session
    check cannot leave conversation X's transcript visible under conversation Y's URL.
    """
    page = browser_page
    route_chat_sessions(
        page,
        chat_sessions(
            [
                stored_session(CONV, "Conversation one"),
                stored_session(CONV2, "Conversation two"),
            ]
        ),
    )

    def handle(route):
        which = CONV2 if CONV2 in route.request.url else CONV
        text = "Answer two" if which == CONV2 else "Answer one"
        route.fulfill(
            status=200,
            content_type="application/json",
            body=chat_history(stored_answer(f"Question for {text}", text), conversation_id=which),
        )

    page.context.route("**/api/chat/history*", handle)
    page.goto("/")
    _sign_in(page)
    row = "#history-sidebar-section .history-item"
    page.locator(f'{row}[data-session-id="{CONV}"] [data-history-action="open"]').click()
    expect(page.locator("#messages")).to_contain_text("Answer one")
    page.locator(f'{row}[data-session-id="{CONV2}"] [data-history-action="open"]').click()
    expect(page.locator("#messages")).to_contain_text("Answer two")
    page.evaluate(
        "() => { window.__supabaseState.getSessionGate = new Promise((r) => { window.__releaseGetSession = r; }); }"
    )
    page.go_back()
    expect(page).to_have_url(re.compile(rf"/c/{CONV}$"))
    expect(page.locator("#messages")).not_to_contain_text(
        "Answer two"
    )  # cleared while the session check is still parked
    page.evaluate(
        "() => { window.__supabaseState.getSessionGate = null; window.__releaseGetSession(); }"
    )
    expect(page.locator("#messages")).to_contain_text("Answer one")
