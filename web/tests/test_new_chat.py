"""New chat: end a conversation without ending the session.

The control exists because `conv_id` in the Flask session keeps feeding prior
turns to the model, so a reader with an unrelated question used to have to log
out to ask it.

Two things here are worth stating up front, because both are the reason the
implementation looks the way it does rather than incidental detail.

**Reset rotates; it does not delete.** The streaming generator calls
`store.append_turn` before it yields its `done` frame, and `ConversationStore.clear`
is a keyed pop with no tombstone. A reset that deleted the entry would leave a
generator still winding down free to write the old turn straight back under the
same id — so whether the reset held would depend on whether the client's
disconnect beat one line of server code. Rotating means a late append lands on
an id nothing will read again. `test_a_late_append_cannot_resurrect_...` is that
race, made deterministic.

**Undo restores the conversation, not just the transcript.** Because the old
conversation is set aside rather than destroyed, undo puts back what the *model*
remembers too. A transcript that came back over a server which had forgotten it
would be a half-truth of exactly the kind this product's citations exist to
prevent.
"""

from __future__ import annotations

import copy
import re

import pytest
from playwright.sync_api import expect

from web.api.app import create_app
from web.services.result_combiner import SearchResult


AUTH = {"Authorization": "Bearer fake_token"}
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


def ask(client, query="first"):
    return drain(client.post("/api/chat/stream", json={"query": query}, headers=AUTH))


# ── Rotation ────────────────────────────────────────────────────────────────

def test_reset_rotates_the_conversation_id(client):
    ask(client)
    with client.session_transaction() as flask_session:
        before = flask_session["conv_id"]

    response = client.post("/api/conversation/reset", json={}, headers=AUTH)

    assert response.status_code == 200
    with client.session_transaction() as flask_session:
        assert flask_session["conv_id"] != before
        assert flask_session["prev_conv_id"] == before


def test_the_model_gets_no_prior_context_after_a_reset(app, client):
    ask(client, "first")
    client.post("/api/conversation/reset", json={}, headers=AUTH)
    ask(client, "second")

    # Two calls: the first with nothing behind it, the second likewise.
    assert app.config["llm_history"][-1] == []


def test_reset_clears_the_blocking_paths_history(client):
    """`/api/chat` keeps history in the session, not the store.

    A reset that only handled `conv_id` would leave the non-streaming fallback
    remembering everything — the path a browser without streaming bodies takes.
    """
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        assert flask_session.get("chat_history"), "precondition: history recorded"

    client.post("/api/conversation/reset", json={}, headers=AUTH)

    with client.session_transaction() as flask_session:
        assert flask_session.get("chat_history") is None
        # Set aside rather than destroyed, for the same reason `conv_id` is
        # rotated rather than deleted — see the undo tests below.
        assert flask_session.get("prev_chat_history")


def test_reset_keeps_the_reader_signed_in(client):
    ask(client)
    client.post("/api/conversation/reset", json={}, headers=AUTH)

    # The whole point of the route: a new conversation, same session.
    assert ask(client, "second").status_code == 200


def test_a_late_append_cannot_resurrect_a_reset_conversation(app, client):
    """The race the rotation exists for.

    `store.append_turn` runs before the generator's `done` frame, so a stream
    that was still winding down when the reset landed will write its turn
    afterwards. Under a delete-in-place reset that write lands on the *current*
    conversation and the reader's cleared history comes back on their next
    question. Under rotation it lands on an id nothing reads.
    """
    ask(client, "first")
    with client.session_transaction() as flask_session:
        stale = flask_session["conv_id"]

    client.post("/api/conversation/reset", json={}, headers=AUTH)

    store = app.config["conversations"]
    store.append_turn(stale, "late question", "late answer", 6, 8000)

    ask(client, "second")
    assert app.config["llm_history"][-1] == [], "the late turn leaked into the new conversation"


# ── Undo ────────────────────────────────────────────────────────────────────

def test_undo_restores_what_the_model_remembers(app, client):
    ask(client, "first")
    with client.session_transaction() as flask_session:
        original = flask_session["conv_id"]

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    response = client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)

    assert response.status_code == 200
    with client.session_transaction() as flask_session:
        assert flask_session["conv_id"] == original
        assert flask_session.get("prev_conv_id") is None

    ask(client, "second")
    assert app.config["llm_history"][-1], "undo restored the view but not the context"


def test_undo_with_nothing_set_aside_is_a_no_op_not_an_error(client):
    """A reader whose first question never reached the server still has turns
    on screen to restore, and no server history to contradict them. Failing
    here would throw those turns away to report a disagreement that does not
    exist."""
    ask(client)
    with client.session_transaction() as flask_session:
        unchanged = flask_session["conv_id"]

    response = client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)

    assert response.status_code == 200
    assert response.get_json()["restored"] is False
    with client.session_transaction() as flask_session:
        assert flask_session["conv_id"] == unchanged


def test_undo_restores_the_blocking_paths_history(client):
    """The other half of the rotation, for the path that has no store entry.

    `/api/chat` keeps its history in the session cookie, so clearing it and not
    putting it back made undo half a restore: the transcript and the streaming
    context came back while a browser without streaming bodies carried on as
    though the reset had stood — answering the conversation on screen with no
    memory of it.
    """
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        original = flask_session["chat_history"]

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    response = client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)

    assert response.status_code == 200
    assert response.get_json()["restored"] is True
    with client.session_transaction() as flask_session:
        assert flask_session["chat_history"] == original
        assert flask_session.get("prev_chat_history") is None


def test_the_model_gets_the_restored_history_on_the_blocking_path(app, client):
    """The session key is the mechanism; this is the thing it is for."""
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    client.post("/api/conversation/reset", json={}, headers=AUTH)
    client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)

    drain(client.post("/api/chat", json={"query": "second"}, headers=AUTH))
    assert app.config["llm_history"][-1], "undo restored the view but not the context"


def test_the_cookie_never_carries_two_histories(client):
    """The bound that makes setting a history aside safe at all.

    Each history is capped at 3,500 JSON *characters* — not serialized cookie
    bytes — against a browser limit of about 4,093 bytes, and content that
    compresses badly is not hypothetical on this product: a pasted table of
    batch numbers, a list of submission IDs, signed URLs, OCR output. One such
    history is already close to the edge; two would go over, and a dropped
    cookie costs the reader their session rather than their history.

    So the two are never both present. Asking a question ends the undo, and the
    server enforces that rather than trusting the client's `forget` request to
    land — which makes rotating the history exactly as cookie-expensive as
    clearing it was.
    """
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    client.post("/api/conversation/reset", json={}, headers=AUTH)

    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_chat_history"), "precondition: one set aside"
        assert flask_session.get("chat_history") is None

    # A new question on the blocking path, with no `forget` from the client.
    drain(client.post("/api/chat", json={"query": "second"}, headers=AUTH))

    with client.session_transaction() as flask_session:
        assert flask_session.get("chat_history"), "the new question was recorded"
        assert flask_session.get("prev_chat_history") is None, "two histories in one cookie"


def test_forget_drops_the_conversation_set_aside(app, client):
    ask(client)
    with client.session_transaction() as flask_session:
        original = flask_session["conv_id"]

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    client.post("/api/conversation/reset", json={"forget": True}, headers=AUTH)

    assert app.config["conversations"].get(original) == []
    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_conv_id") is None


def test_forget_drops_the_blocking_paths_set_aside_history(client):
    """`forget` fires when the reader asks their next question, so it has to
    reach every trace of the set-aside conversation — including the one that
    carries the actual text."""
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    client.post("/api/conversation/reset", json={}, headers=AUTH)
    client.post("/api/conversation/reset", json={"forget": True}, headers=AUTH)

    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_chat_history") is None

    # And an undo that arrives anyway finds nothing to put back, rather than
    # resurrecting a conversation the reader has already moved on from.
    response = client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)
    assert response.get_json()["restored"] is False
    with client.session_transaction() as flask_session:
        assert flask_session.get("chat_history") is None


def test_a_second_reset_drops_the_first_ones_leftover(app, client):
    """Only one conversation is ever undoable, so the older one goes at once
    rather than waiting for the store's TTL."""
    ask(client)
    with client.session_transaction() as flask_session:
        first = flask_session["conv_id"]

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    ask(client, "second")
    client.post("/api/conversation/reset", json={}, headers=AUTH)

    assert app.config["conversations"].get(first) == []


def test_logout_purges_the_conversation_set_aside(app, client):
    """A reader who resets and then signs out must leave nothing behind.

    `prev_conv_id` is unreachable by any route once the session is gone, so
    without the purge it would sit in memory until the TTL — one reader's
    questions outliving their session on a shared machine.
    """
    ask(client)
    with client.session_transaction() as flask_session:
        original = flask_session["conv_id"]

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    client.post("/auth/logout")

    assert app.config["conversations"].get(original) == []
    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_conv_id") is None


def test_logout_purges_the_set_aside_history(client):
    """End to end: nothing of the set-aside conversation survives a sign-out.

    The logout route's own `session.clear()` would deliver this on its own. The
    test below is the one that holds `CONVERSATION_SESSION_KEYS` honest.
    """
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    client.post("/api/conversation/reset", json={}, headers=AUTH)
    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_chat_history"), "precondition: set aside"

    client.post("/auth/logout")

    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_chat_history") is None


def test_a_change_of_reader_purges_the_set_aside_history(client):
    """The backstop for every ending that skips the logout route.

    A closed tab, an expired refresh token, a revoked session — any of them
    leaves a valid Flask cookie behind, and `_bind_session_to_identity` is what
    catches it on the next authenticated request. That purge works from a list
    of key names and nothing else, so a key missing from it survives: here, one
    reader's questions and answers riding the cookie into the next reader's
    session, one Undo press from being back on screen.
    """
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    client.post("/api/conversation/reset", json={}, headers=AUTH)

    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_chat_history"), "precondition: set aside"
        # Somebody else held this cookie first, so the request below is a
        # different reader picking it up.
        flask_session["auth_identity"] = "someone-else@example.com"

    client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)

    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_chat_history") is None
        assert flask_session.get("chat_history") is None, "the previous reader's turns came back"


def test_reset_requires_authentication(client):
    assert client.post("/api/conversation/reset", json={}).status_code == 401


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


def test_undo_puts_the_conversation_back(authenticated_page):
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()
    expect(authenticated_page.locator(".chatbot-message")).to_have_count(0)

    authenticated_page.locator("#toast .toast-action").click()

    expect(authenticated_page.locator(".chatbot-message")).to_have_count(1)
    expect(authenticated_page.locator(".user-message")).to_have_count(1)
    expect(authenticated_page.locator(NEW_CHAT)).to_be_visible()


def test_clearing_does_not_sign_the_reader_out(authenticated_page):
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()

    expect(authenticated_page.locator("#authenticated-view")).to_be_visible()
    expect(authenticated_page.locator("#logout-button")).to_be_visible()


# ── The undo countdown ──────────────────────────────────────────────────────

COUNTDOWN = "(el) => getComputedStyle(el, '::after').animationName"
# `width`, not `inline-size`: the logical property is what the stylesheet
# authors and what mirrors under RTL, but it does not resolve to a length in a
# pseudo-element's computed style. The toast is horizontal either way.
BAR_WIDTH = "(el) => parseFloat(getComputedStyle(el, '::after').width) || 0"

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


def test_the_undo_toast_carries_a_countdown(authenticated_page):
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()

    toast = authenticated_page.locator("#toast")
    expect(toast).to_have_class(re.compile(r"has-action"))
    assert toast.evaluate(COUNTDOWN) == "toastCountdown"


def test_the_countdown_drains(authenticated_page):
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()

    # The toast only appears once the server reset has resolved and the
    # transcript has played out, so reading before it exists measures nothing.
    expect(authenticated_page.locator("#toast .toast-action")).to_be_visible()

    toast = authenticated_page.locator("#toast")
    before = toast.evaluate(BAR_WIDTH)
    authenticated_page.wait_for_timeout(1200)
    after = toast.evaluate(BAR_WIDTH)

    assert before > 0, "the rule should start at full width"
    assert after < before, f"the rule did not drain ({before} -> {after})"


def test_a_plain_toast_leaves_no_countdown_behind(authenticated_page):
    """The singleton case, through a real path.

    There is one #toast and many callers. Undo is its own best example: it
    replaces the counting-down toast with a plain "restored" one through the
    same element. That message must not inherit the countdown, the paused
    state, or the ten-second lifetime that went with it.
    """
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()
    expect(authenticated_page.locator("#toast .toast-action")).to_be_visible()

    authenticated_page.locator("#toast .toast-action").click()

    toast = authenticated_page.locator("#toast")
    expect(toast).to_have_text("Conversation restored")
    expect(toast).not_to_have_class(re.compile(r"has-action"))
    expect(authenticated_page.locator("#toast .toast-action")).to_have_count(0)
    assert toast.evaluate(COUNTDOWN) == "none"
    assert toast.evaluate("(el) => el.style.getPropertyValue('--toast-duration')") == ""


def test_undo_does_not_replay_the_arrival_animation(authenticated_page):
    """An undo should read as the clear never having happened.

    The button animating back in would announce that it did — and every route
    that touches the transcript runs through updateNewChatAvailability, including
    restoreTranscript, so this is exactly the call that has to opt out.
    """
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()
    expect(authenticated_page.locator(NEW_CHAT)).to_be_hidden()

    # Watch only the restore, not the first arrival.
    authenticated_page.evaluate(WATCH_ARRIVAL, NEW_CHAT)
    authenticated_page.locator("#toast .toast-action").click()
    expect(authenticated_page.locator(".chatbot-message")).to_have_count(1)

    assert authenticated_page.evaluate("() => window.__arrived") is False


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
    """A restored transcript is still a conversation to end.

    Every other route to a populated transcript goes through UI, which keeps the
    button in step. Transcript.restore() writes the turns straight in as markup
    and told it nothing — so after a language switch the reader had a
    conversation on screen and no visible way to end it, which is the one state
    this control exists for.
    """
    send(authenticated_page)
    expect(authenticated_page.locator(NEW_CHAT)).to_be_visible()

    authenticated_page.add_init_script(SEED_SESSION)
    # Saves the transcript, reloads, restores it. Several toggles exist across
    # the chrome; only the one on screen is clickable.
    authenticated_page.locator(".lang-toggle-btn").locator("visible=true").first.click()
    authenticated_page.wait_for_load_state("load")

    expect(authenticated_page.locator(".chatbot-message")).to_have_count(1)
    expect(authenticated_page.locator(NEW_CHAT)).to_be_visible()


# ── When the server says no ─────────────────────────────────────────────────

def fail_reset(page):
    """Make the next /api/conversation/reset fail, whatever it was asking for."""
    page.route(
        "**/api/conversation/reset",
        lambda route: route.fulfill(
            status=500, content_type="application/json", body='{"error":"unavailable"}'
        ),
    )


def hold_first_reset(page):
    """Park the first reset request and let every later one through.

    The tests below need a reset that is still in the air while the page is
    driven underneath it. Holding *every* reset would also swallow the `forget`
    and `undo` calls that come afterwards, which is a way to write a test that
    fails for a reason unrelated to the thing it is asserting.

    Returns a dict whose "route" key is the parked request, to fulfil when the
    test is ready.
    """
    held = {"route": None}

    def hold(route):
        if held["route"] is None:
            held["route"] = route
        else:
            route.fulfill(status=200, content_type="application/json", body='{"ok":true}')

    page.route("**/api/conversation/reset", hold)
    return held


def test_a_failed_reset_leaves_no_spinning_answer(streaming_page):
    """New chat aborts the stream *before* it calls the server.

    On the normal path streamChat is right to walk away from the bubble without
    closing it: it is a fraction of a second from leaving the transcript. When
    the server call fails the transcript stays put — and the bubble stayed with
    it, still aria-busy, spinning over an answer with no stream behind it and
    nothing coming back for it.
    """
    fail_reset(streaming_page)

    streaming_page.locator("#query-input").fill("What are the registration requirements?")
    streaming_page.locator("#send-button").click()
    streaming_page.evaluate(
        r"""() => window.__chat.push('event: delta\ndata: {"t":"A partial answer"}\n\n')"""
    )
    expect(streaming_page.locator('.chatbot-message[aria-busy="true"]')).to_have_count(1)

    streaming_page.locator(NEW_CHAT).click()

    # The reset failed, so the conversation is unchanged — which is exactly why
    # the bubble has to be closed out rather than left pretending to stream.
    expect(streaming_page.locator(".chatbot-message")).to_have_count(1)
    expect(streaming_page.locator('.chatbot-message[aria-busy="true"]')).to_have_count(0)
    expect(streaming_page.locator(".chatbot-message.is-cancelled")).to_have_count(1)
    expect(streaming_page.locator("#toast")).to_contain_text("Could not start a new chat")


def test_a_failed_reset_does_not_kill_the_next_answer(streaming_page):
    """The reason the doomed bubble is captured before the abort, not read back
    afterwards.

    A reset releases the composer the moment it aborts, so the reader can start
    a new question while the server call is still in the air. If the failure
    path then reached for "whatever is streaming now", it would find that new
    answer and mark it cancelled — a live, correct answer killed by the failure
    of something else entirely.
    """
    # Hold the reset open so the second question starts inside its window.
    released = hold_first_reset(streaming_page)

    streaming_page.locator("#query-input").fill("First question")
    streaming_page.locator("#send-button").click()
    streaming_page.evaluate(
        r"""() => window.__chat.push('event: delta\ndata: {"t":"First answer"}\n\n')"""
    )
    streaming_page.locator(NEW_CHAT).click()

    # The reset is now in flight. Start a second answer inside that window.
    streaming_page.wait_for_function("() => !document.querySelector('#send-button').disabled")
    streaming_page.locator("#query-input").fill("Second question")
    streaming_page.locator("#send-button").click()
    streaming_page.evaluate(
        r"""() => window.__chat.push('event: delta\ndata: {"t":"Second answer"}\n\n')"""
    )

    # Now let the reset fail underneath it.
    released["route"].fulfill(status=500, content_type="application/json", body='{"error":"no"}')

    # The second answer belongs to nothing that just failed, so it keeps streaming.
    expect(streaming_page.locator("#toast")).to_contain_text("Could not start a new chat")
    expect(streaming_page.locator(".chatbot-message.is-cancelled")).to_have_count(1)
    second = streaming_page.locator(".chatbot-message").last
    expect(second).to_have_attribute("aria-busy", "true")
    expect(second).not_to_have_class(re.compile(r"is-cancelled"))


def test_undo_keeps_a_turn_the_server_already_recorded(streaming_page):
    """A stream that finished while the reset was resolving is part of the
    conversation being set aside, and an undo has to bring it back.

    `store.append_turn` runs before the generator's `done` frame, so a stream
    that delivered `done` is one the server has already written. The bubble was
    left carrying aria-busy on this path, and dropInFlightExchange drops
    whatever carries aria-busy — so the turn was deleted from the transcript
    while the model went on remembering it, which is the one thing the undo
    design exists to prevent.
    """
    # Hold the FIRST reset only. The undo and the forget that follow go through
    # to the real server, or the undo under test would never resolve.
    held = hold_first_reset(streaming_page)

    streaming_page.locator("#query-input").fill("A question")
    streaming_page.locator("#send-button").click()
    streaming_page.evaluate(
        r"""() => window.__chat.push('event: delta\ndata: {"t":"An answer"}\n\n')"""
    )

    # Reset first — this is what bumps the generation the stream will fail.
    streaming_page.locator(NEW_CHAT).click()

    # ...and only now does the stream run to completion, `done` and all.
    streaming_page.evaluate(
        r"""() => {
      window.__chat.push('event: final\ndata: {"response":"An answer","sources":[],"cited":[],"retrieved":0}\n\n');
      window.__chat.push('event: done\ndata: {"finish_reason":"stop","chars":9}\n\n');
      window.__chat.close();
    }"""
    )
    streaming_page.wait_for_function(
        "() => !document.querySelector('.chatbot-message[aria-busy=\"true\"]')"
    )

    held["route"].fulfill(status=200, content_type="application/json", body='{"ok":true}')
    expect(streaming_page.locator(".chatbot-message")).to_have_count(0)
    expect(streaming_page.locator("#toast .toast-action")).to_be_visible()

    streaming_page.locator("#toast .toast-action").click()

    expect(streaming_page.locator(".chatbot-message")).to_have_count(1)
    expect(streaming_page.locator(".user-message")).to_have_count(1)


def test_a_stream_cut_before_done_is_not_restored_by_an_undo(streaming_page):
    """The rule is: keep the turn only where `done` confirms the server stored it.

    `store.append_turn` runs between the `final` and `done` frames, so `done`
    arriving is the client's one piece of evidence that the turn is part of the
    conversation a reset sets aside. A stream cut after `final` but before
    `done` has no such evidence — the generator's GeneratorExit surfaces at the
    `suggestions` yield, which precedes the append — so the turn is dropped, and
    an undo must not bring it back. That is the same rule as
    `test_undo_keeps_a_turn_the_server_already_recorded`, not a different one.
    """
    held = hold_first_reset(streaming_page)

    streaming_page.locator("#query-input").fill("A question")
    streaming_page.locator("#send-button").click()
    streaming_page.evaluate(
        r"""() => window.__chat.push('event: delta\ndata: {"t":"An answer"}\n\n')"""
    )
    # Everything up to and including `final` — but never `done`.
    streaming_page.evaluate(
        r"""() => window.__chat.push('event: final\ndata: {"response":"An answer","sources":[],"cited":[],"retrieved":0}\n\n')"""
    )

    streaming_page.locator(NEW_CHAT).click()

    # Cut the connection under the reset. The fixture's fetch double ignores
    # the AbortController, so the abort is delivered by erroring the stream
    # itself — which is what puts streamChat on its catch path with `final`
    # already in hand and the generation moved on.
    streaming_page.evaluate(
        """() => window.__chat.controller.error(
             new DOMException('The user aborted a request.', 'AbortError'))"""
    )
    # That rejection settles on a microtask; releasing the reset is a round trip
    # through the browser, so the catch has run by the time the reset lands.
    held["route"].fulfill(status=200, content_type="application/json", body='{"ok":true}')

    expect(streaming_page.locator(".chatbot-message")).to_have_count(0)
    expect(streaming_page.locator("#toast .toast-action")).to_be_visible()

    streaming_page.locator("#toast .toast-action").click()

    # The transcript comes back without the unconfirmed exchange, so it still
    # shows exactly what the model remembers.
    expect(streaming_page.locator(".chatbot-message")).to_have_count(0)
    expect(streaming_page.locator(".user-message")).to_have_count(0)


def test_a_failed_undo_says_what_actually_failed(authenticated_page):
    """`chat.resetFailed` says the conversation is unchanged. By the time an
    undo can fail, the reset has already stood — so that message would report
    the opposite of what happened, to the reader least able to check."""
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()
    expect(authenticated_page.locator("#toast .toast-action")).to_be_visible()

    # Only the undo call fails; the reset that got us here already succeeded.
    fail_reset(authenticated_page)
    authenticated_page.locator("#toast .toast-action").click()

    toast = authenticated_page.locator("#toast")
    expect(toast).to_contain_text("Could not restore the previous conversation.")
    expect(toast).not_to_contain_text("unchanged")


# ── Letting go of the undo ──────────────────────────────────────────────────

def test_asking_again_takes_the_undo_toast_with_it(authenticated_page):
    """The toast is the only route to the undo, so it has to end when the undo
    does. Left up, it offered an Undo button that silently did nothing — at the
    moment the reader is least able to tell a dead control from a slow one."""
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()
    expect(authenticated_page.locator("#toast .toast-action")).to_be_visible()

    send(authenticated_page, "A different question entirely.")

    expect(authenticated_page.locator("#toast .toast-action")).to_be_hidden()


# ── The entrance, on the way back ───────────────────────────────────────────

ANIMATION_NAME = "(el) => getComputedStyle(el).animationName"


def test_undo_does_not_replay_the_message_entrances(authenticated_page):
    """An undo puts the SAME nodes back, and a re-appended element replays its
    entrance animation from the start — so the whole conversation slid in again,
    announcing a clear that is supposed to read as never having happened.

    Suppressed permanently on those turns rather than for a frame: an entrance
    restarts whenever animation-name goes from `none` back to a name, so
    anything that suppresses and then lets go is a delay, not a fix.
    """
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()
    expect(authenticated_page.locator("#toast .toast-action")).to_be_visible()

    authenticated_page.locator("#toast .toast-action").click()
    expect(authenticated_page.locator(".chatbot-message")).to_have_count(1)

    assert authenticated_page.locator(".chatbot-message").evaluate(ANIMATION_NAME) == "none"
    assert authenticated_page.locator(".user-message").evaluate(ANIMATION_NAME) == "none"


def test_a_new_answer_still_makes_its_entrance(authenticated_page):
    """The other half: suppression is for turns that have already arrived, and
    a blanket rule on the container would have caught every later message."""
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


def test_a_restored_turn_can_still_be_cleared_again(authenticated_page):
    """The suppression is permanent, so the exit has to out-rank it — stated in
    the selector (`:not(.is-clearing)`) rather than left to source order.

    The end state is not enough to assert on its own: playTranscriptExit backs
    `animationend` with a 400ms timeout, so a suppressed exit would still clear
    the transcript and pass a test that only looked at the result. This reads
    the animation while it is running.
    """
    send(authenticated_page)
    authenticated_page.locator(NEW_CHAT).click()
    expect(authenticated_page.locator("#toast .toast-action")).to_be_visible()
    authenticated_page.locator("#toast .toast-action").click()
    expect(authenticated_page.locator(".chatbot-message")).to_have_count(1)

    authenticated_page.evaluate(WATCH_CLEARING)
    authenticated_page.locator(NEW_CHAT).click()

    expect(authenticated_page.locator(".chatbot-message")).to_have_count(0)
    expect(authenticated_page.locator("[data-chat-intro]")).to_be_visible()
    assert authenticated_page.evaluate("() => window.__clearAnim") == "transcriptClear"
