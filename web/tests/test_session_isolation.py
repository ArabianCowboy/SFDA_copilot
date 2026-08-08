"""One browser, two readers: the second must never inherit the first's chat.

The Flask session cookie outlives a Supabase sign-out. It carries `conv_id`,
which keys the server-side ConversationStore, and `chat_history`, which the
blocking route feeds straight back to the model. Nothing in the logout path
touched either — the client never called the Flask logout endpoint, and that
endpoint never cleared the session — so on a shared machine the next reader's
first question arrived carrying the previous reader's conversation as context.

Two independent defences, tested separately because either alone leaves a real
gap:

* the logout route purges, for the cooperative path;
* every authenticated request re-checks identity, for all the endings that
  skip logout entirely — a closed tab, an expired refresh token, a revoked
  session, a client that simply never calls it.
"""

from __future__ import annotations

import pytest

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

    # What the model was actually handed as prior context. Snapshotted at call
    # time: the blocking route extends the very list it passed in, so reading
    # mock.call_args afterwards would show the mutated version.
    import copy
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


# ── The cooperative path: logout ────────────────────────────────────────────

def test_logout_clears_the_conversation_cookie(client):
    drain(client.post("/api/chat/stream", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        assert flask_session.get("conv_id"), "precondition: a conversation exists"

    client.post("/auth/logout")

    with client.session_transaction() as flask_session:
        assert flask_session.get("conv_id") is None
        assert flask_session.get("chat_history") is None
        assert flask_session.get("user_email") is None


def test_logout_clears_the_server_side_conversation_store(app, client):
    """Dropping the cookie key is not enough — the history is held server-side
    and anyone still holding the old cookie could reach it again."""
    drain(client.post("/api/chat/stream", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        conversation_id = flask_session["conv_id"]

    store = app.config["conversations"]
    assert store.get(conversation_id), "precondition: the turn was recorded"

    client.post("/auth/logout")
    assert store.get(conversation_id) == []


def test_logout_succeeds_even_though_supabase_is_absent(client):
    """The purge runs before anything that can fail.

    Testing mode has no Supabase client at all; in production it may be
    unreachable. Neither may leave the session holding a conversation.
    """
    drain(client.post("/api/chat/stream", json={"query": "first"}, headers=AUTH))
    response = client.post("/auth/logout")

    assert response.status_code == 200
    with client.session_transaction() as flask_session:
        assert flask_session.get("conv_id") is None


# ── The defensive path: identity rotation ───────────────────────────────────

def test_a_different_reader_does_not_inherit_the_streaming_conversation(app, client):
    """The leak, reproduced: logout never happens, the cookie survives.

    The store entry must be gone AND the new turn must start from a fresh
    conversation id, or the next prompt carries the previous reader's history.
    """
    drain(client.post("/api/chat/stream", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        first_conversation = flask_session["conv_id"]

    store = app.config["conversations"]
    assert store.get(first_conversation), "precondition: history was recorded"

    # A different account picks up the same browser cookie.
    with client.session_transaction() as flask_session:
        flask_session["auth_identity"] = "someone-else@example.com"

    drain(client.post("/api/chat/stream", json={"query": "second"}, headers=AUTH))

    with client.session_transaction() as flask_session:
        assert flask_session["conv_id"] != first_conversation
    assert store.get(first_conversation) == []


def test_a_different_reader_does_not_inherit_the_blocking_history(app, client):
    """The blocking route reads session["chat_history"] straight into the
    prompt, so it needs its own assertion."""
    client.post("/api/chat", json={"query": "first"}, headers=AUTH)
    with client.session_transaction() as flask_session:
        assert flask_session.get("chat_history"), "precondition: history recorded"
        flask_session["auth_identity"] = "someone-else@example.com"

    client.post("/api/chat", json={"query": "second"}, headers=AUTH)

    history = app.config["llm_history"][-1]
    assert history == [], f"second reader was handed {len(history)} prior message(s)"


def test_the_same_reader_keeps_their_conversation(app, client):
    """The rotation must not fire on every request, or nobody has a
    conversation at all and the history feature is silently dead."""
    drain(client.post("/api/chat/stream", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        first_conversation = flask_session["conv_id"]

    drain(client.post("/api/chat/stream", json={"query": "second"}, headers=AUTH))

    with client.session_transaction() as flask_session:
        assert flask_session["conv_id"] == first_conversation
    assert len(app.config["conversations"].get(first_conversation)) == 4
