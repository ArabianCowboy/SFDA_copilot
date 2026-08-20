"""One browser, two readers: the second must never inherit the first's chat.

The Flask session cookie outlives a Supabase sign-out. It carries `conv_id`,
which keys the server-side ConversationStore that both the streaming and
blocking routes feed straight back to the model. Nothing in the logout path
touched it — the client never called the Flask logout endpoint, and that
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
OWNER = "test-user-id"

# A genuinely different account, not the same one wearing a different cookie.
# See the note beside `_TESTING_IDENTITIES` for why the old trick — writing
# `flask_session["auth_identity"]` while the header still resolved to
# `test-user-id` — cannot prove isolation once rows are owned.
AUTH_B = {"Authorization": "Bearer fake_reader_b_token"}
OWNER_B = "test-reader-b-id"

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
    and anyone still holding the old cookie could reach it again.

    Rewritten for durable history, and the change is the point rather than an
    accommodation. This test used to assert that logout destroyed the reader's
    conversation, which was only ever true because there was nowhere else to
    keep it. Logout now clears the COOKIE AND THE CACHE and deletes nothing:
    the rows are the account's, not the browser's. The isolation guarantee it
    exists to protect is unchanged and asserted below — the cache entry is gone,
    so nobody holding the stale cookie can read it.
    """
    drain(client.post("/api/chat/stream", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        conversation_id = flask_session["conv_id"]

    store = app.config["conversations"]
    backend = app.config["_testing_chat_backend"]
    assert store.get(conversation_id, owner_id=OWNER), "precondition: the turn was cached"
    assert backend.load_session(OWNER, conversation_id), "precondition: the turn was stored"

    client.post("/auth/logout")

    assert store.get(conversation_id, owner_id=OWNER) == []
    assert backend.load_session(OWNER, conversation_id), (
        "logout clears the cookie and the cache, never the account's own history"
    )


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
    assert store.get(first_conversation, owner_id=OWNER), "precondition: history was recorded"

    # A different ACCOUNT picks up the same browser cookie.
    drain(client.post("/api/chat/stream", json={"query": "second"}, headers=AUTH_B))

    with client.session_transaction() as flask_session:
        assert flask_session["conv_id"] != first_conversation
    assert store.get(first_conversation, owner_id=OWNER) == []
    assert app.config["llm_history"][-1] == [], "B was handed A's conversation as context"


def test_a_different_reader_does_not_inherit_the_blocking_history(app, client):
    """The blocking route now reads its history from the same store-backed
    conv_id the streaming route uses, so it needs its own assertion too."""
    client.post("/api/chat", json={"query": "first"}, headers=AUTH)
    with client.session_transaction() as flask_session:
        assert flask_session.get("conv_id"), "precondition: a conversation exists"

    client.post("/api/chat", json={"query": "second"}, headers=AUTH_B)

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
    assert len(app.config["conversations"].get(first_conversation, owner_id=OWNER)) == 4


# ── The durable path: ownership is a column, not a cookie ───────────────────

def test_the_streaming_route_keys_history_by_owner(app, client):
    """The window must not be reachable by presenting the id alone.

    `owner_id` is keyword-only on ConversationStore and defaults to None, which
    keeps the store's own unit tests readable. This is the assertion that stops
    a request path quietly dropping it and filing every reader in one bucket.
    """
    drain(client.post("/api/chat/stream", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        conversation_id = flask_session["conv_id"]

    store = app.config["conversations"]
    assert store.get(conversation_id, owner_id=OWNER), "precondition: filed under the owner"
    assert store.get(conversation_id) == [], "the bare id must not reach the window"
    assert store.get(conversation_id, owner_id=OWNER_B) == []


def test_a_second_reader_cannot_load_the_first_readers_session(app, client):
    """The assertion isolation now actually rests on.

    Cookie rotation is no longer the guarantee — it is a convenience. What keeps
    one reader's regulatory questions out of another's is the owner filter
    inside the RPC, and nothing above this line tests it.
    """
    drain(client.post("/api/chat/stream", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        conversation_id = flask_session["conv_id"]

    backend = app.config["_testing_chat_backend"]
    assert backend.load_session(OWNER, conversation_id), "A can read their own session"
    assert backend.load_session(OWNER_B, conversation_id) == [], (
        "B read a session they do not own"
    )


def test_a_returning_reader_resumes_their_own_history(app, client):
    """The deliberate behaviour change, pinned so it cannot regress silently.

    Before durable history the purge was unconditional and a returning reader
    started empty. Account-keyed rows mean reader A signing back in SHOULD see
    their own conversation — that is the whole feature — and the thing that
    tells A from B is the verified user id, never browser state.

    Enabled explicitly, because it ships OFF: the visible transcript does not
    hydrate from these rows until step 6, and until it does this would resume a
    conversation into the model that the reader cannot see. The machinery is
    proven here so step 6 only has to flip the flag.
    """
    app.config["CHAT_RESUME_LATEST_SESSION"] = True
    drain(client.post("/api/chat/stream", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        original = flask_session["conv_id"]

    client.post("/auth/logout")
    with client.session_transaction() as flask_session:
        assert flask_session.get("conv_id") is None, "precondition: the cookie was purged"

    drain(client.post("/api/chat/stream", json={"query": "second"}, headers=AUTH))

    with client.session_transaction() as flask_session:
        assert flask_session["conv_id"] == original, "A did not get their conversation back"
    assert app.config["llm_history"][-1] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": ANSWER},
    ], "the resumed conversation was not rehydrated into the prompt window"


def test_a_returning_reader_resumes_nothing_that_belongs_to_someone_else(app, client):
    """The same fallback, from the other side: B signs in on A's browser."""
    app.config["CHAT_RESUME_LATEST_SESSION"] = True
    drain(client.post("/api/chat/stream", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        a_conversation = flask_session["conv_id"]

    client.post("/auth/logout")
    drain(client.post("/api/chat/stream", json={"query": "second"}, headers=AUTH_B))

    with client.session_transaction() as flask_session:
        assert flask_session["conv_id"] != a_conversation
    assert app.config["llm_history"][-1] == []


def test_the_resume_fallback_is_on_by_default(app, client):
    """Step 6 flipped it, and this is the assertion that proves the default.

    The sibling tests above set `CHAT_RESUME_LATEST_SESSION` explicitly, so they
    would keep passing if the shipped default silently reverted. This one sets
    nothing: it asks whether a returning reader gets their conversation back on
    the configuration this repository actually ships.

    It replaces `test_the_resume_fallback_is_off_by_default`, which asserted the
    inverse for a good reason at the time — while the transcript restored from
    per-tab `sessionStorage`, resuming put history into the prompt that the
    screen never showed. `GET /api/chat/history` removed that gap.
    """
    drain(client.post("/api/chat/stream", json={"query": "first"}, headers=AUTH))
    with client.session_transaction() as flask_session:
        original = flask_session["conv_id"]

    client.post("/auth/logout")
    drain(client.post("/api/chat/stream", json={"query": "second"}, headers=AUTH))

    with client.session_transaction() as flask_session:
        assert flask_session["conv_id"] == original, (
            "a returning reader did not get their own conversation back"
        )
    assert app.config["llm_history"][-1] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": ANSWER},
    ], "the resumed conversation never reached the prompt window"
