"""New chat: end a conversation without ending the session.

Decision 2 of docs/per-tab-conversation-deep-linking-plan.md: "New chat" is a
client-side navigation from `/c/<id>` to `/`, not a server round trip. There
is no `/api/conversation/reset` any more — its entire job was rotating a
session-held `conv_id` and, on `undo`, restoring a set-aside `prev_conv_id`,
both cookie-keyed mechanisms §5.1 and §5.4 remove. Undo is the Back button
now: free, per-tab, and already understood, rather than a server-held pointer
one browser could hold at a time. `Handlers.handleNewChat`
(static/js/modules/handlers.js) confirms there is no remaining caller of the
deleted route.

What used to be exercised here as a direct HTTP round trip against the reset
route — rotation, undo, the pre-migration cookie-litter adoption — tested a
mechanism that no longer exists and has no replacement to test in its place:
under URL-as-truth, ending one conversation and starting another is just two
independent client-minted ids, which `test_chat_sessions.py` and
`test_multi_tab_conversations.py` already cover. What remains here are the
regressions that were never about the reset route in the first place, and the
browser-level control itself.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import re

import pytest
from playwright.sync_api import expect

from web.api.app import create_app
from web.services.result_combiner import SearchResult

from .conftest import chat_history, route_chat_history, stored_answer

AUTH = {"Authorization": "Bearer fake_token"}
# The owner the TESTING bypass resolves to. History is keyed by (owner,
# conversation), so a bare-id read would return [] and every assertion below
# that expects emptiness would pass without proving anything.
OWNER = "test-user-id"
ANSWER = "Applications must be submitted within 15 days [1]."


@pytest.fixture
def app():
    application = create_app(testing=True)
    application.config["search_engine"].search.return_value = [
        SearchResult(
            text="Chunk about registration requirements.",
            score=0.71,
            document="Guidance.pdf",
            category="regulatory",
            page=14,
            chunk_id="c1",
            metadata={"semantic_score": 0.6, "lexical_score": 0.8},
        )
    ]
    handler = application.config["openai_handler"]
    handler.model = "gpt-4o-mini"
    handler.generate_suggestions.return_value = []

    # What the model was actually handed as prior context, snapshotted at call
    # time: the blocking route extends the very list it was passed, so reading
    # mock.call_args afterwards would show the mutated version.
    history_seen: list[list[dict]] = []

    def record_blocking(query, llm_context, category, chat_history, lang="en"):
        history_seen.append(copy.deepcopy(chat_history or []))
        return ANSWER, []

    def record_streaming(query, llm_context, category=None, chat_history=None, lang="en"):
        history_seen.append(copy.deepcopy(chat_history or []))
        return iter([ANSWER])

    handler.generate_response.side_effect = record_blocking
    handler.stream_response.side_effect = record_streaming
    application.config["llm_history"] = history_seen
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def drain(response):
    """Streamed views do not execute until the body is read."""
    response.get_data()
    return response


def ask(client, query="first", headers=AUTH, **body):
    body.setdefault("query", query)
    return drain(client.post("/api/chat/stream", json=body, headers=headers))


def conversation_of(response) -> str:
    for block in response.get_data(as_text=True).split("\n\n"):
        if not block.strip():
            continue
        event, data = "message", None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:") :].strip())
        if event == "meta" and data is not None:
            return data["conversation_id"]
    raise AssertionError("no meta frame in the streamed response")


# ── Arabic and cookie-size regressions ──────────────────────────────────────
#
# TODO.md's two blocking-path bugs: json.dumps(..., ensure_ascii=True) — the
# default — escaped every non-ASCII character to a 6-char \uXXXX sequence, so
# an Arabic exchange was measured at several times its real size and trimmed
# to nothing; and the 3,500-char budget bounded JSON characters, not the
# actual serialized/compressed/signed session cookie bytes a browser
# receives, so incompressible content could survive the budget and still
# blow the ~4,093-byte cookie limit. Neither bug was about `conv_id` or the
# reset route — both survive its deletion unchanged.

ARABIC_PHRASE = "ما هي المتطلبات التنظيمية الكاملة لتسجيل منتج دوائي جديد في المملكة؟ "


def test_arabic_history_survives_the_blocking_path(app, client):
    """Regression for TODO.md's "Arabic readers get no chat history on the
    non-streaming path". Twelve repeats of the phrase above, stripped (as
    `handle_chat` strips the incoming query), are 827 real characters —
    4,428 chars escaped (over the 3,500 budget, the bug), 948 unescaped
    (under it, the fix) — measured against the mock's fixed answer text, so
    this fails today and passes after the ensure_ascii fix.
    """
    query = ARABIC_PHRASE * 12
    conversation_id = "aaaaaaaa-2222-3333-4444-555555555555"
    drain(
        client.post(
            "/api/chat",
            json={"query": query, "lang": "ar", "conversation_id": conversation_id},
            headers=AUTH,
        )
    )
    drain(
        client.post(
            "/api/chat",
            json={
                "query": "second question",
                "conversation_id": conversation_id,
                "allow_create": False,
            },
            headers=AUTH,
        )
    )

    history = app.config["llm_history"][-1]
    assert history, "the Arabic exchange was trimmed to nothing"
    # handle_chat strips the incoming query before recording it.
    assert history[0]["content"] == query.strip()


def _deterministic_high_entropy(seed: str, n_chunks: int) -> str:
    """Deterministic stand-in for a pasted table of batch numbers, signed
    URLs, or OCR output: high per-character entropy, so it does not compress
    the way prose does — but reproducible across test runs, unlike
    os.urandom."""
    chunks = []
    for i in range(n_chunks):
        digest = hashlib.sha256(f"{seed}-{i}".encode()).digest()
        chunks.append(base64.urlsafe_b64encode(digest).decode().rstrip("="))
    return "\n".join(chunks)


def test_the_session_cookie_stays_under_the_browsers_limit_with_incompressible_content(app, client):
    """Bug: the cap bounded JSON *characters*, not the serialized, compressed,
    signed cookie *bytes* a browser actually receives. Reproduced against the
    real app before this fix: this exact content survives the 3,500-char
    budget comfortably, but a realistic-size access token — which every real
    signed-in session carries (`auth_required`, app.py) but this test client
    must inject by hand, since TESTING mode's auth bypass never sets one —
    pushed the actual cookie past the limit and made Werkzeug log "the
    'session' cookie is too large". Moving history off the cookie (and, since,
    off the cookie's pointer entirely) removes the class of problem rather
    than tuning the budget.
    """
    incompressible = _deterministic_high_entropy("pasted-ids", 73)
    pair = [
        {"role": "user", "content": incompressible},
        {"role": "assistant", "content": ANSWER},
    ]
    # Self-assert the precondition: this content must survive the char-based
    # budget, or the test stops proving anything if the budget ever changes.
    # The budget is `server.chat_history_char_budget` now, resolved onto the
    # app — it used to be MAX_SESSION_CHAT_HISTORY_CHARS, a module constant
    # sized for this very cookie, which is why it outlived the cookie.
    assert len(json.dumps(pair, ensure_ascii=False)) <= app.config["MAX_CHAT_HISTORY_CHARS"]

    with client.session_transaction() as flask_session:
        # Every real signed-in session carries this; TESTING's bypass never
        # does, so without injecting one here the bug cannot reproduce.
        flask_session["supabase_access_token"] = _deterministic_high_entropy("fake-jwt", 15)

    response = client.post("/api/chat", json={"query": incompressible}, headers=AUTH)
    assert response.status_code == 200

    session_cookies = [
        c for c in response.headers.getlist("Set-Cookie") if c.startswith("session=")
    ]
    assert session_cookies, "precondition: a session cookie was actually set"
    max_size = app.config.get("MAX_COOKIE_SIZE", 4093)
    assert len(session_cookies[0]) <= max_size, f"cookie header is {len(session_cookies[0])} bytes"

    # Not just "the cookie stayed small" — prove the content actually made it
    # into the store, so an implementation that silently drops history can't
    # pass this test too.
    conv_id = response.get_json()["conversation_id"]
    history = app.config["conversations"].get(conv_id, owner_id=OWNER)
    assert history and history[0]["content"] == incompressible


# ── The control itself ──────────────────────────────────────────────────────

NEW_CHAT = "#new-chat-button"
OFFCANVAS_NEW_CHAT = "#new-chat-button-offcanvas"


def send(page, text="What are the registration requirements?"):
    page.locator("#query-input").fill(text)
    page.locator("#send-button").click()
    expect(page.locator(".chatbot-message")).to_have_count(1)


def test_the_button_ships_in_both_rails(authenticated_page):
    """One authoring site in the macro, so desktop and offcanvas cannot drift."""
    expect(authenticated_page.locator(f"{NEW_CHAT}, {OFFCANVAS_NEW_CHAT}")).to_have_count(2)


def test_the_button_is_absent_until_there_is_a_chat_to_end(authenticated_page):
    """Hidden rather than disabled.

    On a first visit this column's job is the FAQ rail — a session usually
    starts by clicking a question — and a greyed-out control offering to clear
    a conversation nobody has had yet would still be the first thing in it.
    """
    expect(authenticated_page.locator(NEW_CHAT)).to_be_hidden()
    expect(authenticated_page.locator(OFFCANVAS_NEW_CHAT)).to_have_attribute("hidden", "")

    send(authenticated_page)

    expect(authenticated_page.locator(NEW_CHAT)).to_be_visible()
    expect(authenticated_page.locator(OFFCANVAS_NEW_CHAT)).not_to_have_attribute("hidden", "")


def test_it_is_not_a_fourth_theme_toggle(authenticated_page):
    """test_theme_toggle.py asserts exactly three `.theme-toggle-btn`, and the
    shared icon-control styling is applied by selector list rather than by
    reusing that class. Stated here too so the reason survives next to the
    button that has to respect it."""
    expect(authenticated_page.locator(f"{NEW_CHAT}.theme-toggle-btn")).to_have_count(0)


def test_clicking_it_clears_the_transcript(authenticated_page):
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()

    expect(authenticated_page.locator(".chatbot-message")).to_have_count(0)
    expect(authenticated_page.locator(".user-message")).to_have_count(0)
    # The empty state is what remains: it was never a message.
    expect(authenticated_page.locator("[data-chat-intro]")).to_be_visible()
    expect(authenticated_page.locator(NEW_CHAT)).to_be_hidden()


def test_clearing_keeps_the_faq_rail(authenticated_page):
    """`clearSessionState` empties the FAQ list because a logout changes reader.
    A new chat does not, and the rail is what the sidebar is for."""
    before = authenticated_page.locator("#faq-sidebar-section .faq-button").count()
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()

    expect(authenticated_page.locator(".chatbot-message")).to_have_count(0)
    assert authenticated_page.locator("#faq-sidebar-section .faq-button").count() == before


def test_new_chat_navigates_to_the_root_url(authenticated_page):
    """Decision 2 (docs/per-tab-conversation-deep-linking-plan.md): "New chat"
    is a navigation from `/c/<id>` to `/`, not a server round trip."""
    send(authenticated_page)
    expect(authenticated_page).to_have_url(re.compile(r"/c/[0-9a-f-]{36}$"))

    authenticated_page.locator(NEW_CHAT).click()

    expect(authenticated_page).to_have_url(re.compile(r"/$"))


def test_new_chat_shows_a_plain_toast_with_no_undo_action(authenticated_page):
    """Undo is the Back button now — there is no action on this toast to
    replace it, unlike the toast the server-rotation design used to show."""
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()

    toast = authenticated_page.locator("#toast")
    expect(toast).to_contain_text("Conversation cleared")
    expect(toast.locator(".toast-action")).to_have_count(0)


def test_back_after_new_chat_restores_the_conversation(authenticated_page):
    """The undo, through the real mechanism (Decision 2): a Back navigation
    into a committed conversation re-hydrates it from the server, rather than
    restoring a client-held DOM fragment the way the toast's action used to."""
    route_chat_history(
        authenticated_page,
        chat_history(
            stored_answer("What are the registration requirements?", "Mock regulatory answer")
        ),
    )
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()
    expect(authenticated_page.locator(".chatbot-message")).to_have_count(0)

    authenticated_page.go_back()

    expect(authenticated_page.locator(".chatbot-message")).to_have_count(1)
    expect(authenticated_page.locator(".user-message")).to_have_count(1)
    expect(authenticated_page.locator(NEW_CHAT)).to_be_visible()


def test_clearing_does_not_sign_the_reader_out(authenticated_page):
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()

    expect(authenticated_page.locator("#authenticated-view")).to_be_visible()
    expect(authenticated_page.locator("#logout-button")).to_be_visible()


# `.is-arriving` is transient — added for the entrance and cleared when it
# finishes — so polling for it races the animation. Watch for it instead.
WATCH_ARRIVAL = """
(selector) => {
  window.__arrived = false;
  const button = document.querySelector(selector);
  new MutationObserver(() => {
    if (button.classList.contains('is-arriving')) window.__arrived = true;
  }).observe(button, { attributes: true, attributeFilter: ['class'] });
}
"""


def test_the_button_animates_in_when_it_first_appears(authenticated_page):
    """The other half of the same rule: it must still arrive on the way in."""
    expect(authenticated_page.locator(NEW_CHAT)).to_be_hidden()

    authenticated_page.evaluate(WATCH_ARRIVAL, NEW_CHAT)
    send(authenticated_page)

    assert authenticated_page.evaluate("() => window.__arrived") is True


# ── Surviving a reload ──────────────────────────────────────────────────────

# The Supabase double keeps its session in a page-scoped object, so a reload
# would otherwise come back signed out and restore nothing at all.
SEED_SESSION = (
    "window.__supabaseState = {"
    "  user: { id: 'test-user-id', email: 'test@example.com' },"
    "  profile: { id: 'test-user-id', full_name: 'Test User',"
    "             preferences: { theme: 'light' } },"
    "  authCallback: null, lastProfileUpdate: null,"
    "  sessionError: null, profileError: null, profileUpdateError: null };"
)


def test_the_button_survives_a_language_switch(authenticated_page):
    """A hydrated transcript is still a conversation to end.

    The language toggle reloads the page, so the turns on screen afterwards come
    from `GET /api/chat/history` rather than from anything this tab remembered.
    They are written in by `UI.hydrateTranscript`, which has to keep the New chat
    button in step — otherwise the reader has a conversation on screen and no
    visible way to end it, which is the one state this control exists for.

    That was a real bug on the predecessor of this path: the markup restore
    wrote turns straight into the DOM and told the button nothing. It is worth
    pinning through hydration too, because the new path can fail the same way.
    """
    send(authenticated_page)
    expect(authenticated_page.locator(NEW_CHAT)).to_be_visible()

    authenticated_page.add_init_script(SEED_SESSION)
    route_chat_history(
        authenticated_page,
        chat_history(stored_answer("What must the PSSF contain?", "A stored answer.")),
    )
    # Several toggles exist across the chrome; only the one on screen is
    # clickable.
    authenticated_page.locator(".lang-toggle-btn").locator("visible=true").first.click()
    authenticated_page.wait_for_load_state("load")

    expect(authenticated_page.locator(".chatbot-message")).to_have_count(1)
    expect(authenticated_page.locator(NEW_CHAT)).to_be_visible()


# ── The entrance ─────────────────────────────────────────────────────────────

ANIMATION_NAME = "(el) => getComputedStyle(el).animationName"


def test_a_new_answer_still_makes_its_entrance(authenticated_page):
    """A message still gets its arrival animation on an ordinary send."""
    send(authenticated_page)

    assert authenticated_page.locator(".chatbot-message").evaluate(ANIMATION_NAME) == "botMessageIn"
    assert authenticated_page.locator(".user-message").evaluate(ANIMATION_NAME) == "userMessageIn"


# `.is-clearing` lives for one animation, so its computed style has to be read
# while it is on the element rather than polled for afterwards.
WATCH_CLEARING = """
() => {
  window.__clearAnim = null;
  const container = document.querySelector('#messages');
  new MutationObserver(() => {
    const el = container.querySelector('.is-clearing');
    if (el && !window.__clearAnim) window.__clearAnim = getComputedStyle(el).animationName;
  }).observe(container, { subtree: true, attributes: true, attributeFilter: ['class'] });
}
"""


def test_new_chat_plays_the_exit_animation(authenticated_page):
    """The end state is not enough to assert on its own: playTranscriptExit
    backs `animationend` with a 400ms timeout, so a broken exit would still
    clear the transcript and pass a test that only looked at the result. This
    reads the animation while it is running."""
    send(authenticated_page)

    authenticated_page.evaluate(WATCH_CLEARING)
    authenticated_page.locator(NEW_CHAT).click()

    expect(authenticated_page.locator(".chatbot-message")).to_have_count(0)
    expect(authenticated_page.locator("[data-chat-intro]")).to_be_visible()
    assert authenticated_page.evaluate("() => window.__clearAnim") == "transcriptClear"
