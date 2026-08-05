"""Shared pytest configuration for SFDA Copilot."""

from __future__ import annotations

import os
from threading import Thread

import pytest
from werkzeug.serving import make_server


SUPABASE_BROWSER_MOCK = """
export function createClient() {
  const state = window.__supabaseState = window.__supabaseState || {
    user: null,
    profile: {
      id: 'test-user-id',
      full_name: 'Test User',
      organization: 'Test Organization',
      specialization: 'Regulatory Affairs',
      preferences: { theme: 'light' },
    },
    authCallback: null,
    lastProfileUpdate: null,
    sessionError: null,
    profileError: null,
    profileUpdateError: null,
  };

  const session = () => state.user ? {
    user: state.user,
    access_token: 'fake_token',
  } : null;

  return {
    auth: {
      async getSession() {
        if (state.sessionError) {
          return { data: { session: null }, error: new Error(state.sessionError) };
        }
        return { data: { session: session() }, error: null };
      },
      onAuthStateChange(callback) {
        state.authCallback = callback;
        return { data: { subscription: { unsubscribe() {} } } };
      },
      async signInWithPassword({ email }) {
        if (email === 'fail@example.com') {
          return {
            data: { user: null, session: null },
            error: new Error('Invalid login credentials'),
          };
        }
        state.user = { id: 'test-user-id', email };
        const currentSession = session();
        queueMicrotask(() => state.authCallback?.('SIGNED_IN', currentSession));
        return { data: { user: state.user, session: currentSession }, error: null };
      },
      async signUp({ email }) {
        return { data: { user: { id: 'test-user-id', email } }, error: null };
      },
      async signOut() {
        state.user = null;
        queueMicrotask(() => state.authCallback?.('SIGNED_OUT', null));
        return { error: null };
      },
    },
    from() {
      const query = {
        select() { return query; },
        eq() { return query; },
        async single() {
          return {
            data: state.profileError ? null : state.profile,
            error: state.profileError,
          };
        },
        async upsert(payload) {
          if (state.profileUpdateError) {
            return { data: null, error: new Error(state.profileUpdateError) };
          }
          state.lastProfileUpdate = payload;
          state.profile = { ...state.profile, ...payload };
          return { data: state.profile, error: null };
        },
      };
      return query;
    },
  };
}
"""


# One canned SSE exchange, in the order the real route emits.
# "Mock regulatory answer" is split across two delta frames so the tests
# exercise incremental assembly rather than a single-shot write.
SSE_CHAT_MOCK = (
    'event: meta\ndata: {"conversation_id":"test","category":"all","lang":"en","model":"mock"}\n\n'
    'event: stage\ndata: {"stage":"searching"}\n\n'
    'event: sources\ndata: {"sources":[]}\n\n'
    'event: stage\ndata: {"stage":"retrieved","count":0}\n\n'
    'event: stage\ndata: {"stage":"drafting"}\n\n'
    'event: delta\ndata: {"t":"Mock regulatory "}\n\n'
    'event: delta\ndata: {"t":"answer"}\n\n'
    'event: stage\ndata: {"stage":"finalizing"}\n\n'
    'event: suggestions\ndata: {"suggested_questions":["Next question?"]}\n\n'
    'event: done\ndata: {"finish_reason":"stop","chars":22}\n\n'
)


@pytest.fixture(autouse=True)
def test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide deterministic application settings without real credentials."""
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-key")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("FLASK_TESTING", "true")


@pytest.fixture(scope="session")
def live_server_url():
    """Serve the testing app on an ephemeral local port for Playwright."""
    os.environ.update(
        {
            "FLASK_SECRET_KEY": "test-key",
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon-key",
            "FLASK_ENV": "testing",
            "FLASK_TESTING": "true",
        }
    )

    from web.api.app import create_app

    # threaded=True is required: a held-open SSE connection to /api/chat/stream
    # would otherwise monopolise the single serving thread and hang every other
    # request for the rest of the session.
    server = make_server("127.0.0.1", 0, create_app(testing=True), threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def base_url(live_server_url):
    """Override pytest-base-url with the ephemeral Flask server."""
    return live_server_url


@pytest.fixture
def browser_page(page):
    """A browser page with deterministic Supabase and chat responses."""
    page.route(
        "**/@supabase/supabase-js@2.39.7/+esm",
        lambda route: route.fulfill(
            status=200,
            content_type="application/javascript",
            body=SUPABASE_BROWSER_MOCK,
        ),
    )
    page.route(
        "**/api/chat",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"response":"Mock regulatory answer","suggested_questions":["Next question?"],"sources":[]}',
        ),
    )
    # The client prefers the streaming endpoint; /api/chat above stays mocked
    # for the fallback path. Playwright delivers this whole body as a single
    # chunk, which is a useful check in itself: the SSE reader must not assume
    # one frame per chunk.
    page.route(
        "**/api/chat/stream",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=SSE_CHAT_MOCK,
        ),
    )
    return page


@pytest.fixture
def authenticated_page(browser_page):
    """Log in through the real browser handlers using the Supabase mock."""
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#login-email").fill("test@example.com")
    browser_page.locator("#login-password").fill("password123")
    browser_page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    browser_page.locator("#authenticated-view").wait_for(state="visible")
    browser_page.locator("#authModal").wait_for(state="hidden")
    return browser_page


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Classify browser and artifact-dependent tests for selective runs."""
    for item in items:
        path = str(item.path).replace("\\", "/")
        if path.endswith(
            (
                "test_frontend.py",
                "test_theme_toggle.py",
                "test_profile_theme_integration.py",
            )
        ):
            item.add_marker(pytest.mark.browser)
