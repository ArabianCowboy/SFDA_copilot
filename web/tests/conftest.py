"""Shared pytest configuration for SFDA Copilot."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from threading import Thread

import pytest
from werkzeug.serving import make_server


SUPABASE_BROWSER_MOCK = """
// The mock previously kept its session in a page-scoped object alone, so a
// second tab in the same browser context — or a reload of this one — came back
// signed out no matter what the first tab had done. `services.js` avoids that
// for the real client by persisting the session in `window.localStorage`,
// which every same-origin tab in a context actually shares; this double does
// the same, under its own key, so multi-tab tests see what a real second tab
// would see. `sessionStorage` is deliberately not used here for the same
// reason `services.js:131-149` keeps it per-tab for recovery: it does not
// survive a duplicated tab, which is exactly the sharing this needs.
const MOCK_SESSION_KEY = '__mock_supabase_user';

function readStoredUser() {
  try {
    const raw = window.localStorage.getItem(MOCK_SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeStoredUser(user) {
  try {
    if (user) window.localStorage.setItem(MOCK_SESSION_KEY, JSON.stringify(user));
    else window.localStorage.removeItem(MOCK_SESSION_KEY);
  } catch {
    // A private/locked-down context that throws on setItem behaves like a
    // tab that never persisted a session — the mock degrades the same way.
  }
}

export function createClient() {
  const state = window.__supabaseState = window.__supabaseState || {
    user: readStoredUser(),
    profile: {
      id: 'test-user-id',
      first_name: 'Test',
      family_name: 'User',
      age: null,
      // Mirrors the real generated column post-cutover
      // (20260822225415_profile_identity_atomic_cutover.sql): first_name
      // and family_name are the source of truth, full_name is derived.
      full_name: 'Test User',
      organization: 'Test Organization',
      specialization: 'Regulatory Affairs',
      preferences: { theme: 'light' },
      marketing_consent: false,
    },
    authCallback: null,
    lastProfileUpdate: null,
    lastPreferencesPatch: null,
    lastSignUpMetadata: null,
    sessionError: null,
    profileError: null,
    profileUpdateError: null,
    preferencesUpdateError: null,
    lastUserUpdate: null,
    updateUserError: null,
    lastSignOutScope: null,
    signUpError: null,
    // Password-change reauthentication (account/handlers.js). Off by
    // default — most tests exercise the plain updateUser({password}) path.
    requireReauthentication: false,
    reauthenticateSent: false,
    validNonce: '123456',
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
        writeStoredUser(state.user);
        const currentSession = session();
        queueMicrotask(() => state.authCallback?.('SIGNED_IN', currentSession));
        return { data: { user: state.user, session: currentSession }, error: null };
      },
      async signUp({ email, options }) {
        state.lastSignUpMetadata = options?.data ?? null;
        if (state.signUpError) {
          return { data: { user: null, session: null }, error: new Error(state.signUpError) };
        }
        return { data: { user: { id: 'test-user-id', email } }, error: null };
      },
      async signOut(options) {
        const scope = options?.scope ?? 'global';
        state.lastSignOutScope = scope;
        // 'others' ends every session but this one — the real GoTrue
        // behaviour account/handlers.js relies on ("Sign out everywhere
        // else" must not sign the reader out of the tab they clicked it
        // from). Only 'global'/'local' end THIS session in the mock.
        if (scope === 'others') return { error: null };
        state.user = null;
        writeStoredUser(null);
        queueMicrotask(() => state.authCallback?.('SIGNED_OUT', null));
        return { error: null };
      },
      /* Password-change reauthentication (account/handlers.js). Sets a flag
         the mocked updateUser() below checks, mirroring the server-side
         GOTRUE_SECURITY_UPDATE_PASSWORD_REQUIRE_REAUTHENTICATION setting. */
      async reauthenticate() {
        state.reauthenticateSent = true;
        return { error: null };
      },
      /* Recovery. The real client never sees `resetPasswordForEmail` any more —
         recovery mail is sent server-side — but `updateUser` is the call that
         actually changes the password, and it is the one worth pinning. */
      async updateUser(attributes) {
        if (state.updateUserError) {
          return { data: { user: null }, error: new Error(state.updateUserError) };
        }
        if (attributes?.password && state.requireReauthentication && !attributes?.nonce) {
          return {
            data: { user: null },
            error: new Error('Reauthentication is required to update your password.'),
          };
        }
        if (attributes?.password && attributes?.nonce && attributes.nonce !== state.validNonce) {
          return {
            data: { user: null },
            error: new Error('Reauthentication code is not valid.'),
          };
        }
        state.lastUserUpdate = attributes;
        return { data: { user: state.user ?? { id: 'test-user-id', email: 'test@example.com' } }, error: null };
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
    /* Only the one RPC the account page actually calls. Merges into
       state.profile.preferences, mirroring update_own_preferences'
       real semantics (profile_preferences_merge_rpc.sql) rather than the
       upsert's replace-the-whole-object behaviour. */
    async rpc(name, params) {
      if (name !== 'update_own_preferences') {
        return { data: null, error: new Error(`unmocked rpc: ${name}`) };
      }
      if (state.preferencesUpdateError) {
        return { data: null, error: new Error(state.preferencesUpdateError) };
      }
      state.lastPreferencesPatch = params?.p_patch ?? null;
      state.profile = {
        ...state.profile,
        preferences: { ...(state.profile.preferences || {}), ...(params?.p_patch || {}) },
      };
      return { data: state.profile.preferences, error: null };
    },
  };
}
"""


# One canned SSE exchange, in the order the real route emits.
# "Mock regulatory answer" is split across two delta frames so the tests
# exercise incremental assembly rather than a single-shot write.
#
# `conversation_id` is a real uuid, not the string "test" this used to carry:
# the client now reconciles `Route.current()` against `meta`'s id (§3.2 of
# the deep-linking plan) and replaces the URL with whatever it is told, so a
# non-uuid value here would send every test that sends a message to
# `/c/test` — a path `Route.current()` cannot even parse back out. Matches
# `chat_history()`'s default id so the two agree when a test routes both.
SSE_CHAT_MOCK = (
    'event: meta\ndata: {"conversation_id":"c0ffee00-0000-4000-8000-000000000001","category":"all","lang":"en","model":"mock"}\n\n'
    'event: stage\ndata: {"stage":"searching"}\n\n'
    'event: stage\ndata: {"stage":"retrieved","count":0}\n\n'
    'event: stage\ndata: {"stage":"drafting"}\n\n'
    'event: delta\ndata: {"t":"Mock regulatory "}\n\n'
    'event: delta\ndata: {"t":"answer"}\n\n'
    'event: stage\ndata: {"stage":"finalizing"}\n\n'
    'event: final\ndata: {"response":"Mock regulatory answer","sources":[],"cited":[],"retrieved":0}\n\n'
    'event: suggestions\ndata: {"suggested_questions":["Next question?"]}\n\n'
    'event: done\ndata: {"finish_reason":"stop","chars":22}\n\n'
)


# The exchange above ships no sources at all, so nothing in the suite ever
# rendered a source card — which is how a deck that resolved to zero by zero on
# wide screens, and a deck whose arrival stopped the transcript following the
# stream, both went unnoticed. These carry eight passages (the app's configured
# k) and a long answer, so the transcript actually overflows.
#
# Two of the eight share a document (1 and 5, 2 and 6, …), because the panel
# groups passages under their file and a fixture where every passage came from
# a different document would never exercise that.
_SSE_SOURCES = [
    {
        "index": i,
        "document": f"SFDA Guideline Document Number {(i - 1) % 4 + 1} — Long Official Title",
        "page": i * 10,
        "category": "Regulatory",
        "score": round(0.95 - i * 0.05, 2),
        "semantic_score": 0.88,
        "lexical_score": 0.9,
        "snippet": f"Passage {i} as retrieved from the guideline corpus.",
    }
    for i in range(1, 9)
]

# What the answer cites. Sparse on purpose: the payload the server ships is
# filtered to these, so the indices are 1 and 3 rather than 1 and 2, and
# anything assuming `1..len(sources)` breaks against it.
# 1 and 5 both map to "Document Number 1" under the formula above, so the
# cited set spans two documents across three passages — which is what makes
# grouping observable. A cited set of one passage per document would render
# identically whether grouping worked or not.
_SSE_CITED = [1, 3, 5]
_SSE_CITED_SOURCES = [s for s in _SSE_SOURCES if s["index"] in _SSE_CITED]


def _delta_sentence(i: int) -> str:
    """One sentence of the streamed answer; two of them carry markers.

    A bare "[1]" is safe from `marked`'s reference-link parsing, which needs
    "[label][1]" plus a link definition to consume the brackets.
    """
    marker = {2: " [1]", 4: " [3]", 6: " [5]"}.get(i, "")
    return (
        f"Sentence number {i} of the streamed regulatory answer, long enough "
        f"to add real height{marker}. "
    )


_SSE_ANSWER = "".join(_delta_sentence(i) for i in range(1, 26)).strip()

# The same length of answer with no citation markers at all — a refusal, or an
# answer the model simply did not cite. The previous "uncited" fixture reused
# the cited text, so it carried [1] and [3] and never actually exercised the
# marker-free path.
_SSE_UNCITED_ANSWER = (
    "I cannot answer based on the given information. " * 3
).strip()
_SSE_DELTAS = "".join(
    "event: delta\ndata: %s\n\n" % json.dumps({"t": _delta_sentence(i)})
    for i in range(1, 26)
)


def _sse_final(response: str, sources: list, cited: list, retrieved: int) -> str:
    """The terminal frame carrying the canonical answer and its evidence.

    Sources ride here rather than ahead of the first token. Before the answer
    exists there is no way to know which passages it used, and shipping all of
    them anyway is what put a full deck of cards under refusals.
    """
    return "event: final\ndata: %s\n\n" % json.dumps(
        {
            "response": response,
            "sources": sources,
            "cited": cited,
            "retrieved": retrieved,
        }
    )


def _sse_exchange(response: str, sources: list, cited: list, retrieved: int) -> str:
    # See SSE_CHAT_MOCK's comment: a real uuid, not "test" — the client
    # reconciles the URL against it.
    return (
        'event: meta\ndata: {"conversation_id":"c0ffee00-0000-4000-8000-000000000001","category":"all","lang":"en","model":"mock"}\n\n'
        'event: stage\ndata: {"stage":"searching"}\n\n'
        f'event: stage\ndata: {{"stage":"retrieved","count":{retrieved}}}\n\n'
        'event: stage\ndata: {"stage":"drafting"}\n\n'
        f"{_SSE_DELTAS}"
        'event: stage\ndata: {"stage":"finalizing"}\n\n'
        f"{_sse_final(response, sources, cited, retrieved)}"
        'event: suggestions\ndata: {"suggested_questions":["Next question?"]}\n\n'
        'event: done\ndata: {"finish_reason":"stop","chars":2000}\n\n'
    )


# An answer citing two of the eight retrieved passages.
SSE_CHAT_MOCK_WITH_SOURCES = _sse_exchange(
    _SSE_ANSWER, _SSE_CITED_SOURCES, _SSE_CITED, 8
)

# An answer that cites none of the eight passages retrieved for it. `sources`
# is empty because sources means evidence, and an answer that cited nothing has
# none — `retrieved: 8` is the only trace, and it drives the stage line, not a
# source control. This is the production shape of "who is claude?" while the
# relevance floor ships disabled.
SSE_CHAT_MOCK_UNCITED = _sse_exchange(_SSE_UNCITED_ANSWER, [], [], 8)

# Nothing cleared retrieval at all — the "who is claude?" case.
SSE_CHAT_MOCK_NO_SOURCES = _sse_exchange(_SSE_ANSWER, [], [], 0)

# The sparse case: one passage, one document. The state most likely to read as
# a bug rather than a deliberate answer, so it gets its own fixture. The page
# is null on purpose too — a chunk whose metadata carried no page.
_SSE_SPARSE = [{
    "index": 1,
    "document": "2022-10-19_Guidance_for_Submission_of_Registration_Dossiers.pdf",
    "page": None,
    "category": "Regulatory",
    "score": 0.71, "semantic_score": 0.63, "lexical_score": 0.8,
    "snippet": "A single retrieved passage, cited once, with no page recorded.",
}]
SSE_CHAT_MOCK_SPARSE = _sse_exchange(
    "One claim, one source [1].", _SSE_SPARSE, [1], 1
)


# Individual frames, for tests that release them one at a time.
SSE_FINAL_FRAME = _sse_final(_SSE_ANSWER, _SSE_CITED_SOURCES, _SSE_CITED, 8)
SSE_DONE_FRAME = 'event: done\ndata: {"finish_reason":"stop"}\n\n'


def sse_delta(text: str) -> str:
    """One `delta` frame carrying `text`."""
    return f"event: delta\ndata: {json.dumps({'t': text})}\n\n"


# route.fulfill() hands Playwright a complete body, which it delivers as a
# SINGLE chunk — so every fixture above is drained by the client before a test
# can touch the page. That is fine for asserting an end state and useless for
# asserting anything about the reader acting WHILE tokens arrive, which is
# exactly where "who controls scrolling" is decided.
#
# This replaces window.fetch with a stream whose controller the test holds, so
# frames are released explicitly and the page can be driven in between. No
# timing, no sleeps: the test is the clock.
CONTROLLABLE_CHAT_STREAM = """
window.__chat = {
  controller: null,
  push(frame) { this.controller.enqueue(new TextEncoder().encode(frame)); },
  close() { this.controller.close(); },
};
const passthrough = window.fetch;
window.fetch = (url, options = {}) => {
  if (!String(url).includes('/api/chat/stream')) return passthrough(url, options);
  const body = new ReadableStream({ start(c) { window.__chat.controller = c; } });
  return Promise.resolve(new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }));
};
"""


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


def chat_history(messages=(), *, conversation_id="c0ffee00-0000-4000-8000-000000000001"):
    """A `GET /api/chat/history` body.

    No `resumed` field — the fallback it described is deleted
    (docs/per-tab-conversation-deep-linking-plan.md §5.5, Decision 1a).

    The transcript is drawn from this endpoint on every sign-in since step 6, so
    a test that does not route it gets whatever the live test server holds —
    which is an empty in-memory backend, because the chat routes are themselves
    mocked and nothing was ever persisted. Empty is the right default (most
    tests are about one fresh answer), and it is stated here rather than left to
    coincidence.
    """
    return json.dumps({
        "conversation_id": conversation_id,
        "messages": list(messages),
    })


def stored_answer(question, answer, *, sources=(), cited=None, evidence_state="verified"):
    """One stored exchange, in the shape `_hydration_payload` emits.

    Note `index`, not `source_index`: the column is remapped at the Flask
    boundary precisely so the browser sees the same field name a live answer
    carries. A fixture that used the column name would pass while the product
    was broken.
    """
    return [
        {"message_id": "m1", "seq": 1, "role": "user", "content": question},
        {
            "message_id": "m2", "seq": 2, "role": "assistant", "content": answer,
            "evidence_state": evidence_state,
            "sources": list(sources),
            "cited": list(cited if cited is not None else [s["index"] for s in sources]),
            "retrieved": len(sources),
        },
    ]


def route_chat_history(page, body):
    """Point the transcript endpoint at a canned body.

    Registered on `page.context`, not `page` — Playwright matches the most
    recently added handler first regardless of which level registered it, so
    this still overrides `browser_page`'s default; routing it at the context
    level is what lets a sibling tab see the same override instead of hitting
    the real network.

    Trailing `*`, not a bare path: `getChatHistory(id)` appends `?c=<id>`
    once a conversation is named by the URL rather than the cookie (the
    deep-linking plan's Decision 4), and a glob with no wildcard after the
    path only matches a bare request with no query string at all — silently
    falling through to the real network otherwise, which is unreachable from
    a test and answers with a genuine 404.
    """
    page.context.route(
        "**/api/chat/history*",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=body
        ),
    )


def stored_session(session_id, title, *, updated_at=None, message_count=2):
    """One row of `GET /api/chat/sessions`.

    `updated_at` defaults to NOW rather than to a fixed date, and that is not
    laziness: the sidebar groups by calendar day, so a hardcoded 2026 timestamp
    would land every fixture under "Older" and a test asserting on the "Today"
    heading would pass or fail depending on when it was run. A test that wants a
    specific bucket passes an explicit offset.
    """
    when = updated_at or datetime.now(timezone.utc).isoformat()
    return {
        "id": session_id,
        "title": title,
        "created_at": when,
        "updated_at": when,
        "message_count": message_count,
    }


def chat_sessions(sessions=(), *, next_cursor=None):
    """A `GET /api/chat/sessions` body.

    No `active` field — the client knows its own current conversation from
    its own URL now (§5.3 of docs/per-tab-conversation-deep-linking-plan.md).

    Empty by default, which matters for every test that is NOT about the
    sidebar: the tab defaults to Chats when the list comes back with rows and to
    Explore when it does not, so an empty list is what keeps the FAQ rail
    visible for the suite that clicks it. The live test server produces the same
    empty list from its in-memory backend, so an unrouted test agrees with a
    routed one.
    """
    return json.dumps({
        "sessions": list(sessions),
        "next_cursor": next_cursor,
    })


def route_chat_sessions(page, body):
    """Point the conversation list at a canned body. Same override rule as above."""
    page.context.route(
        "**/api/chat/sessions",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=body
        ),
    )


@pytest.fixture
def browser_page(page):
    """A browser page with deterministic Supabase and chat responses.

    Every mock here is registered on `page.context`, not `page`. Playwright
    documents `BrowserContext.route()` as intercepting "network requests made
    by any page in the browser context" — which is what lets a test open a
    genuine second tab (`browser_page.context.new_page()`) and have it inherit
    the same mocks and, via the Supabase double's localStorage-backed session,
    the same signed-in identity, with no per-page repetition and no real
    network reachable from either tab.
    """
    context = page.context
    context.route(
        "**/@supabase/supabase-js@2.39.7/+esm",
        lambda route: route.fulfill(
            status=200,
            content_type="application/javascript",
            body=SUPABASE_BROWSER_MOCK,
        ),
    )
    context.route(
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
    context.route(
        "**/api/chat/stream",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=SSE_CHAT_MOCK,
        ),
    )
    # Every sign-in draws the transcript from here. Empty by default: these
    # tests mock the chat routes, so nothing was ever stored, and a test that
    # wants a stored conversation says so with `route_chat_history`.
    context.route(
        "**/api/chat/history*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=chat_history(),
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


@pytest.fixture
def sourced_page(authenticated_page):
    """Signed in, with a chat stream that returns eight real sources.

    Registered after login so it wins over the empty-sources route in
    ``browser_page`` — Playwright matches the most recently added handler first.
    """
    authenticated_page.context.route(
        "**/api/chat/stream",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=SSE_CHAT_MOCK_WITH_SOURCES,
        ),
    )
    return authenticated_page


def _stream_route(page, body: str):
    """Point the chat stream at a canned exchange.

    Registered after login so it wins over the empty-sources route in
    ``browser_page`` — Playwright matches the most recently added handler first.
    """
    page.context.route(
        "**/api/chat/stream",
        lambda route: route.fulfill(
            status=200, content_type="text/event-stream", body=body,
        ),
    )
    return page


@pytest.fixture
def uncited_page(authenticated_page):
    """Signed in, with an answer that cites none of what was retrieved."""
    return _stream_route(authenticated_page, SSE_CHAT_MOCK_UNCITED)


@pytest.fixture
def sparse_page(authenticated_page):
    """Signed in, with an answer resting on exactly one passage of one document."""
    return _stream_route(authenticated_page, SSE_CHAT_MOCK_SPARSE)


@pytest.fixture
def no_sources_page(authenticated_page):
    """Signed in, with a query nothing was retrieved for.

    The "who is claude?" reproduction: the model is told no relevant
    information was found, refuses, and there is no evidence to offer.
    """
    return _stream_route(authenticated_page, SSE_CHAT_MOCK_NO_SOURCES)


@pytest.fixture
def streaming_page(authenticated_page):
    """Signed in, with a chat stream the TEST releases frame by frame.

    Patched after load rather than via add_init_script: `fetch` is looked up
    at request time, so replacing it once the page is up is enough.
    """
    authenticated_page.evaluate(CONTROLLABLE_CHAT_STREAM)
    return authenticated_page


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Classify browser and artifact-dependent tests for selective runs."""
    for item in items:
        path = str(item.path).replace("\\", "/")
        if path.endswith(
            (
                "test_frontend.py",
                "test_theme_toggle.py",
                "test_profile_theme_integration.py",
                "test_source_panel.py",
                "test_composer.py",
                "test_new_chat.py",
                # Missed when this file shipped (Step 3 of docs/profile-refactor-
                # plan.md): every test in it takes `authenticated_page` or
                # `browser_page`, but with no marker of its own — and outside
                # this allowlist — it ran in the FAST, non-browser pass instead
                # of the dedicated one, and never under `-m browser` at all.
                "test_account_browser.py",
                # Same gap, same fix, found the same way (Step 4): every test
                # here takes `browser_page` too.
                "test_signup_identity_capture.py",
            )
        ):
            item.add_marker(pytest.mark.browser)
