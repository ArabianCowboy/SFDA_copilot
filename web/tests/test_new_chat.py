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

import base64
import copy
import hashlib
import json
import re

import pytest
from playwright.sync_api import expect

from web.api.app import create_app
from web.services.result_combiner import SearchResult


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


def test_reset_rotates_the_blocking_paths_conversation_id(client):
    """`/api/chat` now shares `conv_id`/`ConversationStore` with the streaming
    path, so a reset rotates it here exactly the same way."""
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        before = flask_session["conv_id"]

    response = client.post("/api/conversation/reset", json={}, headers=AUTH)

    assert response.status_code == 200
    with client.session_transaction() as flask_session:
        assert flask_session["conv_id"] != before
        assert flask_session["prev_conv_id"] == before


def test_the_blocking_path_model_gets_no_prior_context_after_a_reset(app, client):
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    client.post("/api/conversation/reset", json={}, headers=AUTH)
    drain(client.post("/api/chat", json={"query": "second"}, headers=AUTH))

    assert app.config["llm_history"][-1] == []


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
    # owner_id, because that is what the streaming generator passes. Without it
    # this writes to (None, stale) — a bucket production never uses — so the
    # simulated late append would not land where a real one does and the
    # assertion below would hold for the wrong reason.
    store.append_turn(stale, "late question", "late answer", 6, 8000, owner_id=OWNER)

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
    """The other half of the rotation, now that `/api/chat` shares the same
    store-backed `conv_id` mechanism the streaming path already used — it no
    longer has a separate cookie-resident history to restore in parallel."""
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        original = flask_session["conv_id"]

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    response = client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)

    assert response.status_code == 200
    assert response.get_json()["restored"] is True
    with client.session_transaction() as flask_session:
        assert flask_session["conv_id"] == original
        assert flask_session.get("prev_conv_id") is None


def test_the_model_gets_the_restored_history_on_the_blocking_path(app, client):
    """The session key is the mechanism; this is the thing it is for."""
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    client.post("/api/conversation/reset", json={}, headers=AUTH)
    client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)

    drain(client.post("/api/chat", json={"query": "second"}, headers=AUTH))
    assert app.config["llm_history"][-1], "undo restored the view but not the context"


def test_undo_survives_a_blocking_question_asked_after_the_reset(client):
    """Unlike the old cookie-bound design — where a blocking-path question
    used to force-end the undo, purely to keep two full histories from ever
    sharing one ~4KB cookie — asking again here no longer ends it. That
    reason is gone once history never touches the cookie at all, and keeping
    the old rule would have made the blocking path behave differently from
    the streaming path, which has never ended the undo on a new question.
    """
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    client.post("/api/conversation/reset", json={}, headers=AUTH)

    drain(client.post("/api/chat", json={"query": "second"}, headers=AUTH))

    response = client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)
    assert response.get_json()["restored"] is True


def test_undo_survives_a_blocking_question_after_resetting_a_streaming_conversation(app, client):
    """The cross-route case that mattered most: mixing routes must not behave
    differently from using one route throughout. `conv_id`/`prev_conv_id` are
    shared machinery now, not something either route owns on its own.

    Asserts more than `restored: True` — the old blocking path never touched
    `prev_conv_id` at all, so an intervening blocking question wouldn't have
    stopped the old code from reporting a restore either. What only the fix
    gets right is *what* gets restored: the streaming conversation's own
    context, not whatever the intervening blocking question happened to leave
    behind in a `chat_history` no longer being read from.
    """
    ask(client, "first")
    with client.session_transaction() as flask_session:
        original = flask_session["conv_id"]

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    drain(client.post("/api/chat", json={"query": "second"}, headers=AUTH))

    response = client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)
    assert response.get_json()["restored"] is True
    with client.session_transaction() as flask_session:
        assert flask_session["conv_id"] == original

    drain(client.post("/api/chat", json={"query": "third"}, headers=AUTH))
    history = app.config["llm_history"][-1]
    assert history and history[0]["content"] == "first"


def test_a_late_blocking_response_remains_reachable_by_undo(app, client):
    """Mirrors `test_a_late_append_cannot_resurrect_a_reset_conversation`'s
    companion for the streaming path — `test_undo_keeps_a_turn_the_server_already_recorded`
    in `test_chat_stream.py`: once the server has genuinely recorded a turn,
    undo restores it, even if a reset landed while a request was still in
    flight. Simulated the same deterministic way that streaming race is
    simulated: write directly to the now-stale id rather than relying on real
    request timing.
    """
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        stale = flask_session["conv_id"]

    client.post("/api/conversation/reset", json={}, headers=AUTH)

    store = app.config["conversations"]
    # owner_id, because that is what the streaming generator passes. Without it
    # this writes to (None, stale) — a bucket production never uses — so the
    # simulated late append would not land where a real one does and the
    # assertion below would hold for the wrong reason.
    store.append_turn(stale, "late question", "late answer", 6, 8000, owner_id=OWNER)

    response = client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)
    assert response.get_json()["restored"] is True
    assert any(m["content"] == "late question" for m in store.get(stale, owner_id=OWNER))


def test_forget_drops_the_conversation_set_aside(app, client):
    ask(client)
    with client.session_transaction() as flask_session:
        original = flask_session["conv_id"]

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    client.post("/api/conversation/reset", json={"forget": True}, headers=AUTH)

    assert app.config["conversations"].get(original, owner_id=OWNER) == []
    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_conv_id") is None


def test_forget_drops_the_blocking_paths_set_aside_history(app, client):
    """`forget` fires when the reader asks their next question, so it has to
    reach every trace of the set-aside conversation."""
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        original = flask_session["conv_id"]

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    client.post("/api/conversation/reset", json={"forget": True}, headers=AUTH)

    assert app.config["conversations"].get(original, owner_id=OWNER) == []
    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_conv_id") is None

    # And an undo that arrives anyway finds nothing to put back, rather than
    # resurrecting a conversation the reader has already moved on from.
    response = client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)
    assert response.get_json()["restored"] is False


def test_a_second_reset_drops_the_first_ones_leftover(app, client):
    """Only one conversation is ever undoable, so the older one goes at once
    rather than waiting for the store's TTL."""
    ask(client)
    with client.session_transaction() as flask_session:
        first = flask_session["conv_id"]

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    ask(client, "second")
    client.post("/api/conversation/reset", json={}, headers=AUTH)

    assert app.config["conversations"].get(first, owner_id=OWNER) == []


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

    assert app.config["conversations"].get(original, owner_id=OWNER) == []
    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_conv_id") is None


def test_a_change_of_reader_purges_the_set_aside_conversation(client):
    """The backstop for every ending that skips the logout route.

    A closed tab, an expired refresh token, a revoked session — any of them
    leaves a valid Flask cookie behind, and `_bind_session_to_identity` is what
    catches it on the next authenticated request. That purge works from a list
    of key names and nothing else, so a key missing from it survives: here, one
    reader's conversation riding the cookie into the next reader's session, one
    Undo press from being back on screen.
    """
    drain(client.post("/api/chat", json={"query": "first"}, headers=AUTH))
    client.post("/api/conversation/reset", json={}, headers=AUTH)

    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_conv_id"), "precondition: set aside"
        # Somebody else held this cookie first, so the request below is a
        # different reader picking it up.
        flask_session["auth_identity"] = "someone-else@example.com"

    response = client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)

    assert response.get_json()["restored"] is False
    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_conv_id") is None
        assert flask_session.get("conv_id") is None, "the previous reader's conversation came back"


def test_reset_requires_authentication(client):
    assert client.post("/api/conversation/reset", json={}).status_code == 401


# ── Migrating a pre-fix session ─────────────────────────────────────────────
#
# Before this fix, `/api/chat` kept its history as raw JSON in
# session["chat_history"] / session["prev_chat_history"] and never touched
# conv_id. A cookie that predates the fix can still be carrying that content
# when a request first reaches the new code, so New chat and Undo have to
# adopt it into the store rather than strand or silently drop it.

def test_reset_migrates_a_pre_migration_readers_active_history(app, client):
    """A reader whose session predates this fix may be carrying live history
    as session["chat_history"] with no conv_id at all — the blocking path
    never set one before. New chat must not leave that stranded in the
    cookie, where a later question would silently resurrect it under a
    conversation the reader believes is fresh.

    Follows through to a real question after undo, not just the `restored`
    flag and the store's raw contents — proving the exact legacy messages
    are what the model sees, not merely that *something* survived.
    """
    legacy = [
        {"role": "user", "content": "pre-migration question"},
        {"role": "assistant", "content": "pre-migration answer"},
    ]
    with client.session_transaction() as flask_session:
        flask_session["chat_history"] = list(legacy)

    client.post("/api/conversation/reset", json={}, headers=AUTH)

    with client.session_transaction() as flask_session:
        assert flask_session.get("chat_history") is None
        prev_id = flask_session.get("prev_conv_id")
        assert prev_id, "the legacy history must still be reachable, not dropped"
    assert app.config["conversations"].get(prev_id, owner_id=OWNER) == legacy

    response = client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)
    assert response.get_json()["restored"] is True
    with client.session_transaction() as flask_session:
        assert flask_session["conv_id"] == prev_id

    drain(client.post("/api/chat", json={"query": "follow-up"}, headers=AUTH))
    history = app.config["llm_history"][-1]
    assert history and history[0]["content"] == "pre-migration question"


def test_a_stray_legacy_cookie_history_does_not_override_the_stores_own_entry(app, client):
    """A reader who used both routes before this migration unified them may
    carry both a real conv_id (with its own store entry) and leftover
    session["chat_history"] from the blocking path's old cookie-only days.
    The two were already inconsistent with each other before this fix, so
    the store — the more recently written side for either route — wins, and
    the orphaned cookie content is dropped rather than merged."""
    ask(client, "first")  # gives conv_id a real store entry
    with client.session_transaction() as flask_session:
        conv_id = flask_session["conv_id"]
        flask_session["chat_history"] = [{"role": "user", "content": "orphaned"}]

    client.post("/api/conversation/reset", json={}, headers=AUTH)

    with client.session_transaction() as flask_session:
        assert flask_session.get("prev_conv_id") == conv_id
        # Not just "not merged" — actually consumed, so it can't resurface
        # later (e.g. via a subsequent adopt_cookie_history call finding it
        # still sitting in the cookie).
        assert "chat_history" not in flask_session
        assert "prev_chat_history" not in flask_session
    history = app.config["conversations"].get(conv_id, owner_id=OWNER)
    assert all(m["content"] != "orphaned" for m in history)


@pytest.mark.parametrize("route", ["/api/chat", "/api/chat/stream"])
def test_an_ordinary_question_migrates_a_dangling_legacy_undo_history(app, client, route):
    """A reader who reset once on the pre-fix blocking implementation ends up
    with a fresh conv_id and a `prev_chat_history` set aside — often with no
    `prev_conv_id`, since the blocking path never touched that key before
    this migration. If they don't happen to press Undo next and just keep
    asking ordinary questions instead, that stray history has to stop riding
    the cookie on the very next request, on EITHER route — otherwise it
    keeps re-sending itself on every response indefinitely, which is exactly
    the cookie-size failure this migration exists to close.
    """
    legacy = [{"role": "user", "content": "set aside before the fix shipped"}]
    with client.session_transaction() as flask_session:
        flask_session["prev_chat_history"] = legacy
        # No prev_conv_id: this reader never used the streaming path before
        # resetting, so pre-fix code never set one.

    drain(client.post(route, json={"query": "second"}, headers=AUTH))

    with client.session_transaction() as flask_session:
        assert "prev_chat_history" not in flask_session, "still riding the cookie"
        prev_id = flask_session.get("prev_conv_id")
        assert prev_id, "the set-aside history must still be reachable, not dropped"
    assert app.config["conversations"].get(prev_id, owner_id=OWNER) == legacy

    # And it's still genuinely undoable, not merely evicted from the cookie.
    response = client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)
    assert response.get_json()["restored"] is True


# ── Arabic and cookie-size regressions ──────────────────────────────────────
#
# TODO.md's two blocking-path bugs: json.dumps(..., ensure_ascii=True) — the
# default — escaped every non-ASCII character to a 6-char \uXXXX sequence, so
# an Arabic exchange was measured at several times its real size and trimmed
# to nothing; and the 3,500-char budget bounded JSON characters, not the
# actual serialized/compressed/signed session cookie bytes a browser
# receives, so incompressible content could survive the budget and still
# blow the ~4,093-byte cookie limit.

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
    drain(client.post("/api/chat", json={"query": query, "lang": "ar"}, headers=AUTH))
    drain(client.post("/api/chat", json={"query": "second question"}, headers=AUTH))

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
    'session' cookie is too large". Moving history off the cookie entirely
    removes the class of problem rather than tuning the budget.
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

    session_cookies = [c for c in response.headers.getlist("Set-Cookie") if c.startswith("session=")]
    assert session_cookies, "precondition: a session cookie was actually set"
    max_size = app.config.get("MAX_COOKIE_SIZE", 4093)
    assert len(session_cookies[0]) <= max_size, f"cookie header is {len(session_cookies[0])} bytes"

    # Not just "the cookie stayed small" — prove the content actually made it
    # into the store, so an implementation that silently drops history can't
    # pass this test too.
    with client.session_transaction() as flask_session:
        conv_id = flask_session["conv_id"]
        assert "chat_history" not in flask_session
        assert "prev_chat_history" not in flask_session
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
