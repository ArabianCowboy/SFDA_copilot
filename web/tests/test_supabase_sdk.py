"""Real CDN SDK + application Services; only provider HTTP/WebSocket traffic is stubbed.

No live project, credentials, email, or AI calls. The normal browser suite mocks the
SDK itself, so it cannot establish compatibility with a newly pinned SDK.
"""

import base64
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

USER = {
    "id": "11111111-1111-4111-8111-111111111111",
    "aud": "authenticated",
    "role": "authenticated",
    "email": "sdk@example.com",
    "app_metadata": {"provider": "email"},
    "user_metadata": {},
    "created_at": "2026-01-01T00:00:00Z",
}


def session(label="login", expires_in=3600):
    """Synthetic JWT; the fake_token signature also selects Flask's TESTING identity."""
    now = int(time.time())
    claims = {"sub": USER["id"], "aud": "authenticated", "iat": now, "exp": now + expires_in}

    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    token = f"{encode({'alg': 'HS256', 'typ': 'JWT'})}.{encode(claims)}.fake_token_{label}"
    return {
        "access_token": token,
        "refresh_token": f"refresh-{label}",
        "token_type": "bearer",
        "expires_in": expires_in,
        "expires_at": now + expires_in,
        "user": USER,
    }


async_boot = """async () => {
  window.SUPABASE_URL = 'https://test.supabase.co';
  window.SUPABASE_ANON_KEY = 'test-anon-key';
  window.Services = (await import('/static/js/modules/services.js')).Services;
  Services.init();
  window.authEvents = [];
  Services.supabase.auth.onAuthStateChange(event => { authEvents.push(event); });
  await Services.supabase.auth.getSession();
}"""


def boot(page: Page, path="/privacy"):
    # This public page does not start the chat app: Services runs without a UI mock.
    page.goto(path)
    page.evaluate(async_boot)


@pytest.fixture
def provider(page: Page):
    requests = []

    def respond(route):
        request = route.request
        requests.append(request)
        url = urlparse(request.url)
        body = request.post_data_json or {}
        if url.path == "/auth/v1/token":
            if body.get("password") == "wrong":
                route.fulfill(
                    status=400,
                    json={"code": "invalid_credentials", "msg": "Invalid login credentials"},
                )
            else:
                grant = parse_qs(url.query)["grant_type"][0]
                route.fulfill(json=session(grant))
        elif url.path == "/auth/v1/user":
            route.fulfill(json=USER)
        elif url.path == "/auth/v1/logout":
            route.fulfill(status=204)
        elif url.path == "/rest/v1/profiles":
            route.fulfill(json={"id": USER["id"], "first_name": "SDK", "preferences": {}})
        else:
            raise AssertionError(f"Unexpected provider request: {request.method} {url.path}")

    page.context.route("https://test.supabase.co/**", respond)
    page.context.route_web_socket("wss://test.supabase.co/realtime/v1/**", lambda socket: None)
    return requests


def login(page: Page):
    return page.evaluate("Services.login('sdk@example.com', 'test-password')")


def test_real_sdk_drives_login_chat_and_logout_in_the_app(page: Page, provider):
    page.goto("/")
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill("sdk@example.com")
    page.locator("#login-password").fill("test-password")
    page.locator("#login-form").evaluate("form => form.requestSubmit()")
    expect(page.locator("#authenticated-view")).to_be_visible()
    expect(page.locator("#authModal")).to_be_hidden()
    page.locator("#query-input").fill("Requirements?")
    page.locator("#send-button").click()
    expect(page.locator(".chatbot-message").last.locator(".message-content")).not_to_be_empty()
    page.locator("#logout-button").locator("visible=true").first.click()
    expect(page.locator("#unauthenticated-view")).to_be_visible()
    assert page.evaluate("localStorage.getItem('sfda-supabase-auth')") is None


def test_login_persists_across_reload_and_tabs_and_chat_uses_its_token(page: Page, provider):
    boot(page)
    token = login(page)["session"]["access_token"]
    assert page.evaluate("Services.getSessionToken()") == token
    version = json.loads(Path("package.json").read_text())["dependencies"]["@supabase/supabase-js"]
    assert provider[0].headers["x-client-info"].split(";")[0] == f"supabase-js/{version}"
    boot(page)
    assert page.evaluate("Services.getSessionToken()") == token
    sibling = page.context.new_page()
    boot(sibling)
    assert sibling.evaluate("Services.getSessionToken()") == token
    with page.expect_request("**/api/chat") as sent:
        result = page.evaluate(
            "async () => Services.sendChatRequest('Requirements?', 'all', await Services.getSessionToken(), 'en')"
        )
    assert sent.value.headers["authorization"] == f"Bearer {token}"
    assert result["response"]


def test_invalid_login_surfaces_the_real_sdk_error_without_a_session(page: Page, provider):
    boot(page)
    result = page.evaluate("""async () => {
      try { await Services.login('sdk@example.com', 'wrong'); }
      catch (error) { return { message: error.message, status: error.status }; }
    }""")
    assert result == {"message": "Invalid login credentials", "status": 400}
    assert page.evaluate("Services.getSessionToken()") is None


@pytest.mark.parametrize("failure", [False, True])
def test_logout_clears_this_session_but_others_scope_preserves_it(page: Page, provider, failure):
    boot(page)
    token = login(page)["session"]["access_token"]
    page.evaluate("Services.signOutOtherSessions()")
    assert page.evaluate("Services.getSessionToken()") == token
    assert parse_qs(urlparse(provider[-1].url).query)["scope"] == ["others"]
    if failure:
        page.context.route(
            "**/auth/v1/logout*",
            lambda route: route.fulfill(status=503, json={"msg": "Unavailable"}),
        )
    result = page.evaluate("""async () => {
      try { await Services.logout(); return 'ok'; }
      catch (error) { return error.status; }
    }""")
    assert result == (503 if failure else "ok")
    assert page.evaluate("Services.getSessionToken()") is None
    assert page.evaluate("localStorage.getItem('sfda-supabase-auth')") is None
    assert "SIGNED_OUT" in page.evaluate("authEvents")


def test_refresh_rotates_the_token_used_by_services(page: Page, provider):
    boot(page)
    original = login(page)["session"]["access_token"]
    refreshed = page.evaluate("Services.supabase.auth.refreshSession()")
    assert refreshed["error"] is None
    token = refreshed["data"]["session"]["access_token"]
    assert token != original
    assert page.evaluate("Services.getSessionToken()") == token
    assert "TOKEN_REFRESHED" in page.evaluate("authEvents")


def test_expired_stored_session_refreshes_on_initialization(page: Page, provider):
    boot(page)
    expired = session("expired", expires_in=-60)
    page.evaluate(
        "value => localStorage.setItem('sfda-supabase-auth', JSON.stringify(value))", expired
    )
    boot(page)
    assert page.evaluate("Services.getSessionToken()") != expired["access_token"]
    assert page.evaluate("Services.getSessionToken()") is not None
    assert parse_qs(urlparse(provider[-1].url).query)["grant_type"] == ["refresh_token"]


def test_normal_pkce_callback_exchanges_and_removes_the_verifier(page: Page, provider):
    boot(page)
    page.evaluate(
        "localStorage.setItem('sfda-supabase-auth-code-verifier', JSON.stringify('test-verifier'))"
    )
    boot(page, "/privacy?code=test-code")
    assert provider[-1].post_data_json["auth_code"] == "test-code"
    assert provider[-1].post_data_json["code_verifier"] == "test-verifier"
    assert page.evaluate("Services.getSessionToken()") is not None
    assert page.evaluate("location.search") == ""
    assert page.evaluate("localStorage.getItem('sfda-supabase-auth-code-verifier')") is None


def test_late_refresh_cannot_resurrect_a_signed_out_session(page: Page, provider):
    boot(page)
    login(page)
    pending = []
    page.context.route(
        "**/auth/v1/token?grant_type=refresh_token", lambda route: pending.append(route)
    )
    with page.expect_request("**/auth/v1/token?grant_type=refresh_token"):
        page.evaluate("() => { window.refreshing = Services.supabase.auth.refreshSession(); }")
    page.evaluate("Services.logout()")
    assert page.evaluate("Services.getSessionToken()") is None
    pending[0].fulfill(json=session("late"))
    page.evaluate("window.refreshing")
    assert page.evaluate("Services.getSessionToken()") is None
    assert page.evaluate("localStorage.getItem('sfda-supabase-auth')") is None


def test_recovery_uses_its_own_tab_storage_and_preserves_the_normal_session(page: Page, provider):
    boot(page)
    normal = login(page)["session"]["access_token"]
    recovery = session("recovery")
    sibling = page.context.new_page()
    fragment = f"access_token={recovery['access_token']}&refresh_token={recovery['refresh_token']}&expires_in=3600&token_type=bearer&type=recovery"
    boot(sibling, f"/privacy?recovery=1#{fragment}")
    sibling.wait_for_function("authEvents.includes('PASSWORD_RECOVERY')")
    assert sibling.evaluate("Services.getSessionToken()") == recovery["access_token"]
    assert sibling.evaluate("location.hash") == ""
    assert sibling.evaluate("sessionStorage.getItem('sfda-supabase-recovery')")
    assert page.evaluate("Services.getSessionToken()") == normal
    boot(sibling, "/privacy?recovery=1")
    assert sibling.evaluate("Services.getSessionToken()") == recovery["access_token"]
    sibling.evaluate("Services.updatePassword('new-test-password')")
    assert provider[-1].post_data_json["password"] == "new-test-password"
    assert provider[-1].post_data_json["code_challenge"] is None
    sibling.evaluate("Services.logout()")
    assert sibling.evaluate("sessionStorage.getItem('sfda-supabase-recovery')") is None
    assert page.evaluate("Services.getSessionToken()") == normal


def test_private_notification_channel_joins_receives_and_unsubscribes(page: Page, provider):
    joins = []
    sockets = []

    def websocket(socket):
        sockets.append(socket)

        def message(raw):
            join_ref, ref, topic, event, payload = json.loads(raw)
            if event == "phx_join":
                joins.append((topic, payload))
            socket.send(
                json.dumps(
                    [
                        join_ref,
                        ref,
                        topic,
                        "phx_reply",
                        {"status": "ok", "response": {"postgres_changes": []}},
                    ]
                )
            )

        socket.on_message(message)

    page.context.route_web_socket("wss://test.supabase.co/realtime/v1/**", websocket)
    boot(page)
    token = login(page)["session"]["access_token"]
    page.evaluate("""() => {
      window.statuses = []; window.notifications = [];
      Services.notifications.subscribe('reader', {
        onMessage: payload => notifications.push(payload),
        onStatusChange: status => statuses.push(status),
      });
    }""")
    page.wait_for_function("statuses.includes('SUBSCRIBED')")
    topic, payload = joins[0]
    assert topic == "realtime:notify:user:reader"
    assert payload["config"]["private"] is True
    assert payload["access_token"] == token
    sockets[0].send(
        json.dumps(
            [
                None,
                None,
                topic,
                "broadcast",
                {"event": "notify", "payload": {"notification_id": "notice", "revision": 1}},
            ]
        )
    )
    page.wait_for_function("notifications.length === 1")
    assert page.evaluate("notifications[0]") == {"notification_id": "notice", "revision": 1}
    page.evaluate("Services.notifications.unsubscribe()")
    page.wait_for_function("Services.supabase.getChannels().length === 0")
