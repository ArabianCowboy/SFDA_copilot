"""One browser, two readers: the second must never inherit the first's chat.

Before docs/per-tab-conversation-deep-linking-plan.md this rested partly on a
`conv_id` in the Flask session cookie, which keyed the server-side
`ConversationStore` that both the streaming and blocking routes feed straight
back to the model. That cookie is gone (§1, §5.1): every request now names its
conversation explicitly, and nothing is resolved from session state at all.

What the guarantee rests on now is narrower and stronger: `ConversationStore`
is keyed `(owner_id, conversation_id)`, and every durable read and write is
filtered by the verified owner id, never by the id alone. A second reader on
the same browser — even one still sitting on the first reader's `/c/<id>` URL,
which nothing above the client enforces server-side — cannot read or extend
the first reader's conversation, because their own request always carries
their own owner id and the store answers `[]` for any (id, owner) pair it
never wrote.

Two independent defences remain, tested separately because either alone
leaves a real gap:

* the logout route purges legacy per-cookie conversation litter, for the
  cooperative path;
* every authenticated request re-checks identity, for all the endings that
  skip logout entirely — a closed tab, an expired refresh token, a revoked
  session, a client that simply never calls it.
"""

from __future__ import annotations

import copy

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


def conversation_of(response) -> str:
    """The id a blocking chat response's turn landed under."""
    return response.get_json()["conversation_id"]


def conversation_of_stream(response) -> str:
    """The id a streaming chat response's turn landed under, off its `meta`
    frame."""
    import json

    for block in response.get_data(as_text=True).split("\n\n"):
        if not block.strip():
            continue
        event, data = "message", None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        if event == "meta" and data is not None:
            return data["conversation_id"]
    raise AssertionError("no meta frame in the streamed response")


# ── The cooperative path: logout ────────────────────────────────────────────

def test_logout_purges_legacy_conversation_litter(client):
    """`chat_history`/`prev_chat_history` are the only conversation-shaped
    keys logout still has to clear (`CONVERSATION_SESSION_KEYS`, auth.py) —
    both are pre-migration cookie content, never written by either route any
    more, kept purgeable so an old cookie cannot ride a fresh sign-in.
    """
    with client.session_transaction() as flask_session:
        flask_session["chat_history"] = [{"role": "user", "content": "pre-migration"}]

    client.post("/auth/logout")

    with client.session_transaction() as flask_session:
        assert flask_session.get("chat_history") is None
        assert flask_session.get("user_email") is None


def test_logout_succeeds_even_though_supabase_is_absent(client):
    """The purge runs before anything that can fail.

    Testing mode has no Supabase client at all; in production it may be
    unreachable. Neither may leave stale legacy content behind.
    """
    with client.session_transaction() as flask_session:
        flask_session["chat_history"] = [{"role": "user", "content": "pre-migration"}]

    response = client.post("/auth/logout")

    assert response.status_code == 200
    with client.session_transaction() as flask_session:
        assert flask_session.get("chat_history") is None


# ── The defensive path: identity rotation ───────────────────────────────────

def test_a_different_reader_does_not_inherit_the_streaming_conversation(app, client):
    """The leak this whole file exists to close, reproduced with no cookie
    left to carry it: B's request explicitly names A's conversation id — the
    sharpest version of "the same browser, still on A's URL" now that nothing
    is resolved from session state. The owner filter inside
    `ConversationStore` must refuse it regardless.

    B's own request still lands somewhere: `ConversationStore` is keyed
    `(owner_id, conversation_id)`, so naming A's id opens a SEPARATE bucket
    under B's own owner id rather than being refused outright — the RAM
    equivalent of `chat_append_turn`'s durable ownership check, which does
    refuse it (`PersistenceUnavailable`, logged below, and the reason
    `_persist_turn` reports `persisted: false` on this turn). What must not
    happen is B's bucket ever containing A's "first", or the model seeing it
    as prior context.
    """
    response = drain(client.post(
        "/api/chat/stream", json={"query": "first"}, headers=AUTH,
    ))
    conversation_id = conversation_of_stream(response)

    store = app.config["conversations"]
    assert store.get(conversation_id, owner_id=OWNER), "precondition: history was recorded"

    # A different ACCOUNT, naming A's conversation id on the same browser.
    drain(client.post(
        "/api/chat/stream",
        json={"query": "second", "conversation_id": conversation_id},
        headers=AUTH_B,
    ))

    b_saw = [m["content"] for m in store.get(conversation_id, owner_id=OWNER_B)]
    assert "first" not in b_saw, "B's window contains A's question"
    a_saw = [m["content"] for m in store.get(conversation_id, owner_id=OWNER)]
    assert "second" not in a_saw, "A's window absorbed B's question"
    assert app.config["llm_history"][-1] == [], "B was handed A's conversation as context"


def test_a_different_reader_does_not_inherit_the_blocking_history(app, client):
    """The blocking route shares the same owner-keyed store, so it needs its
    own assertion too."""
    first = client.post("/api/chat", json={"query": "first"}, headers=AUTH)
    conversation_id = conversation_of(first)

    client.post(
        "/api/chat",
        json={"query": "second", "conversation_id": conversation_id},
        headers=AUTH_B,
    )

    history = app.config["llm_history"][-1]
    assert history == [], f"second reader was handed {len(history)} prior message(s)"


def test_the_same_reader_keeps_their_conversation(app, client):
    """Naming the same id on both turns must behave exactly as a real client's
    would: the second turn sees the first."""
    conversation_id = "aaaaaaaa-2222-3333-4444-555555555555"
    drain(client.post(
        "/api/chat/stream",
        json={"query": "first", "conversation_id": conversation_id},
        headers=AUTH,
    ))
    drain(client.post(
        "/api/chat/stream",
        json={"query": "second", "conversation_id": conversation_id, "allow_create": False},
        headers=AUTH,
    ))

    assert len(app.config["conversations"].get(conversation_id, owner_id=OWNER)) == 4


# ── The durable path: ownership is a column, not a cookie ───────────────────

def test_the_streaming_route_keys_history_by_owner(app, client):
    """The window must not be reachable by presenting the id alone.

    `owner_id` is keyword-only on ConversationStore and defaults to None, which
    keeps the store's own unit tests readable. This is the assertion that stops
    a request path quietly dropping it and filing every reader in one bucket.
    """
    response = drain(client.post("/api/chat/stream", json={"query": "first"}, headers=AUTH))
    conversation_id = conversation_of_stream(response)

    store = app.config["conversations"]
    assert store.get(conversation_id, owner_id=OWNER), "precondition: filed under the owner"
    assert store.get(conversation_id) == [], "the bare id must not reach the window"
    assert store.get(conversation_id, owner_id=OWNER_B) == []


def test_a_second_reader_cannot_load_the_first_readers_session(app, client):
    """The assertion isolation now actually rests on.

    There is no cookie rotation to lean on any more — it never was the
    guarantee, only a convenience (docs/per-tab-conversation-deep-linking-
    plan.md §1). What keeps one reader's regulatory questions out of another's
    is the owner filter inside the RPC, and nothing above this line tests it.
    """
    response = drain(client.post("/api/chat/stream", json={"query": "first"}, headers=AUTH))
    conversation_id = conversation_of_stream(response)

    backend = app.config["_testing_chat_backend"]
    assert backend.load_session(OWNER, conversation_id), "A can read their own session"
    assert backend.load_session(OWNER_B, conversation_id) == [], (
        "B read a session they do not own"
    )


# NO MORE "resume" TESTS HERE. `_resolve_conversation_id`'s resume branch and
# `CHAT_RESUME_LATEST_SESSION` are deleted
# (docs/per-tab-conversation-deep-linking-plan.md §5.5, Decision 1a): `/` is
# always a new conversation, and there is no cookie-held "most recent
# session" for a returning reader — or a stranger on their browser — to pick
# up. What replaces it, a client-supplied id under the wrong owner being
# refused, is `test_a_different_reader_does_not_inherit_the_streaming_
# conversation` and its blocking sibling above.
