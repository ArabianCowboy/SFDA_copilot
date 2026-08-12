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


def test_forget_drops_the_conversation_set_aside(app, client):
    ask(client)
    with client.session_transaction() as flask_session:
        original = flask_session["conv_id"]

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    client.post("/api/conversation/reset", json={"forget": True}, headers=AUTH)

    assert app.config["conversations"].get(original) == []
    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_conv_id") is None


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
