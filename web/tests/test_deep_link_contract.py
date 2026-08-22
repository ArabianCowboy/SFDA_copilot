"""The `/c/<id>` deep-linking contract: the server half.

docs/per-tab-conversation-deep-linking-plan.md §3. Client-side navigation
(route.js, the history.state lifecycle, the multi-tab proof) is tested in
`test_multi_tab_conversations.py` — this file is the request/response
contract a browser is not required to prove: a client-supplied
`conversation_id` is honoured and touches no cookie, an absent or malformed
one mints a fresh one and touches no cookie either (§8 step 6 removed the
cookie fallback), a stale or foreign id is refused before a token is
generated, and the new `GET /c/<uuid>` route is what §3.1 says it is.
"""

from __future__ import annotations

import re
import uuid

import pytest

from web.api.app import create_app
from web.services.chat_store import InMemoryChatBackend
from web.services.result_combiner import SearchResult


AUTH = {"Authorization": "Bearer fake_token"}
OWNER = "test-user-id"
AUTH_B = {"Authorization": "Bearer fake_reader_b_token"}
OWNER_B = "test-reader-b-id"

ANSWER_TOKENS = ["The answer ", "is here."]


def make_result(index: int) -> SearchResult:
    return SearchResult(
        text=f"Passage {index}",
        score=0.7,
        document=f"Doc_{index}.pdf",
        category="regulatory",
        page=index,
        chunk_id=f"c{index}",
        metadata={"semantic_score": 0.6, "lexical_score": 0.8},
    )


@pytest.fixture
def app():
    application = create_app(testing=True)
    application.config["search_engine"].search.return_value = [make_result(1)]
    handler = application.config["openai_handler"]
    handler.model = "gpt-4o-mini"
    handler.stream_response.side_effect = lambda *a, **k: iter(ANSWER_TOKENS)
    handler.generate_response.side_effect = lambda *a, **k: ("".join(ANSWER_TOKENS), [])
    handler.generate_suggestions.return_value = []
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def backend(app) -> InMemoryChatBackend:
    return app.config["_testing_chat_backend"]


def conversation_of(client) -> str | None:
    with client.session_transaction() as flask_session:
        return flask_session.get("conv_id")


def new_id() -> str:
    return str(uuid.uuid4())


def conversation_id_of(response) -> str:
    """The `conversation_id` a response carries, JSON or SSE alike.

    The streaming route echoes it on `meta`, `final` and `done`
    (app.py:2678, :2735, :2762); the blocking route and the history route
    carry it as an ordinary JSON field. Both are "what the server resolved
    this request's conversation to be", which is all these tests need.
    """
    if response.is_json:
        return response.get_json()["conversation_id"]
    match = re.search(r'"conversation_id":\s*"([^"]+)"', response.get_data(as_text=True))
    assert match, response.get_data(as_text=True)
    return match.group(1)


def ask_stream(client, *, conversation_id=None, allow_create=None, query="A question", headers=AUTH):
    body = {"query": query}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    if allow_create is not None:
        body["allow_create"] = allow_create
    response = client.post("/api/chat/stream", json=body, headers=headers)
    response.get_data()
    return response


def ask_blocking(client, *, conversation_id=None, allow_create=None, query="A question", headers=AUTH):
    body = {"query": query}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    if allow_create is not None:
        body["allow_create"] = allow_create
    return client.post("/api/chat", json=body, headers=headers)


# ── A client-supplied id is honoured and touches no cookie ──────────────────

@pytest.mark.parametrize("ask", [ask_stream, ask_blocking])
def test_a_client_supplied_conversation_id_is_honoured(client, backend, ask):
    minted = new_id()

    response = ask(client, conversation_id=minted, allow_create=True)

    assert response.status_code == 200
    assert backend.session_exists(OWNER, minted)


@pytest.mark.parametrize("ask", [ask_stream, ask_blocking])
def test_a_client_supplied_conversation_id_writes_no_cookie(client, ask):
    ask(client, conversation_id=new_id(), allow_create=True)

    # The URL is the pointer for a request that named one. Writing the cookie
    # here would be the exact collision §1.2 exists to remove — a second tab
    # that also supplies its own id must not have this one silently inherited.
    assert conversation_of(client) is None


@pytest.mark.parametrize("ask", [ask_stream, ask_blocking])
def test_an_absent_conversation_id_starts_a_new_conversation(client, ask):
    """§8 step 6: the cookie fallback is gone. ABSENT is no longer a signal
    that only a cookie could resolve — `/` is always a new conversation
    (Decision 1a of docs/per-tab-conversation-deep-linking-plan.md) — so it is
    minted right here, exactly like a malformed value, and touches no
    session state either."""
    response = ask(client)

    assert response.status_code == 200
    uuid.UUID(conversation_id_of(response))  # does not raise
    assert conversation_of(client) is None


@pytest.mark.parametrize("ask", [ask_stream, ask_blocking])
def test_a_malformed_conversation_id_mints_a_fresh_one_and_writes_no_cookie(client, ask):
    """PRESENT but malformed is not the same as absent — it is a client bug,
    tolerated the same way `client_request_id` already is, and it must not
    fall through to the cookie rule."""
    response = ask(client, conversation_id="not-a-uuid", allow_create=True)

    assert response.status_code == 200
    minted = conversation_id_of(response)
    assert minted != "not-a-uuid"
    uuid.UUID(minted)  # does not raise
    assert conversation_of(client) is None


# ── The preflight: a stale or foreign id is refused before generation ───────

@pytest.mark.parametrize("ask", [ask_stream, ask_blocking])
def test_a_stale_conversation_is_refused_before_the_answer_is_generated(client, app, backend, ask):
    never_existed = new_id()

    response = ask(client, conversation_id=never_existed, allow_create=False)

    assert response.status_code == 404
    assert response.get_json()["code"] == "not_found"
    # No token was ever generated, and nothing was written under the id — the
    # whole point of preflighting before retrieval rather than discovering
    # this after a complete answer has already streamed (§3.4).
    handler = app.config["openai_handler"]
    assert handler.stream_response.call_count == 0
    assert handler.generate_response.call_count == 0
    assert not backend.session_exists(OWNER, never_existed)


def test_a_foreign_conversation_is_refused_the_same_way(client, app):
    other = app.test_client()
    stranger = conversation_id_of(ask_stream(other, headers=AUTH_B))
    calls_before = app.config["openai_handler"].stream_response.call_count

    response = ask_stream(client, conversation_id=stranger, allow_create=False)

    assert response.status_code == 404
    assert response.get_json()["code"] == "not_found"
    assert app.config["openai_handler"].stream_response.call_count == calls_before


@pytest.mark.parametrize("ask", [ask_stream, ask_blocking])
def test_an_existing_owned_conversation_with_allow_create_false_succeeds(client, ask):
    """The ordinary turn-2-onward shape: the id already exists, and refusing
    creation is a no-op because nothing needed creating."""
    first = ask(client, conversation_id=new_id(), allow_create=True)
    mine = conversation_id_of(first)

    second = ask(client, conversation_id=mine, allow_create=False, query="A second question")

    assert second.status_code == 200
    assert conversation_id_of(second) == mine


# ── GET /api/chat/history?c=<id>: the 404 that did not exist before ─────────

def test_a_client_supplied_history_id_that_never_existed_is_not_found(client):
    response = client.get(
        "/api/chat/history", query_string={"c": new_id()}, headers=AUTH
    )

    assert response.status_code == 404
    assert response.get_json()["code"] == "not_found"


def test_a_conversation_id_the_reader_does_not_own_is_not_found(client, app):
    other = app.test_client()
    stranger = conversation_id_of(ask_stream(other, headers=AUTH_B))

    not_owned = client.get(
        "/api/chat/history", query_string={"c": stranger}, headers=AUTH
    )
    never_existed = client.get(
        "/api/chat/history", query_string={"c": new_id()}, headers=AUTH
    )

    # Not yours, or not there. Deliberately one answer — the same discipline
    # chat_load_session and chat_session_exists already take at the database.
    assert not_owned.status_code == never_existed.status_code == 404
    assert not_owned.get_json() == never_existed.get_json()


def test_an_absent_history_id_answers_empty_not_404(client):
    """`/` — no `?c=` at all — is a new conversation (Decision 1a), not an
    id to look up. Nothing here can be a stranger's, because nothing was
    asked for."""
    response = client.get("/api/chat/history", headers=AUTH)

    assert response.status_code == 200
    assert response.get_json() == {"conversation_id": None, "messages": []}


def test_an_owned_conversation_is_found_by_its_client_supplied_id(client):
    mine = conversation_id_of(ask_stream(client, conversation_id=new_id(), allow_create=True))

    response = client.get("/api/chat/history", query_string={"c": mine}, headers=AUTH)

    assert response.status_code == 200
    assert response.get_json()["conversation_id"] == mine


# ── GET /c/<uuid>: the deep-link shell ───────────────────────────────────────

def test_the_deep_link_route_requires_no_authentication(client):
    response = client.get(f"/c/{new_id()}")

    assert response.status_code == 200


def test_the_deep_link_route_writes_no_session_state(client):
    response = client.get(f"/c/{new_id()}")

    assert "Set-Cookie" not in response.headers


def test_the_deep_link_route_response_does_not_vary_with_the_conversation_id(client):
    """For a fixed requester, varying the uuid produces no observable
    difference — the no-existence-oracle property (§3.1), narrower than and
    correcting the round-1 draft's "byte-identical for any reader"."""
    first = client.get(f"/c/{new_id()}")
    second = client.get(f"/c/{new_id()}")

    assert first.data == second.data


def test_the_deep_link_route_redirects_uppercase_to_canonical_case(client):
    mixed = str(uuid.uuid4())
    upper = mixed.upper()

    response = client.get(f"/c/{upper}", follow_redirects=False)

    assert response.status_code == 301
    assert response.headers["Location"].rsplit("/", 1)[-1] == mixed


def test_the_deep_link_route_carries_a_robots_tag(client):
    response = client.get(f"/c/{new_id()}")

    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"


def test_the_deep_link_route_rejects_a_malformed_id(client):
    response = client.get("/c/not-a-uuid")

    assert response.status_code == 404


# ── §3.5: the force=True CSRF hole ───────────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/chat/stream", "/api/chat"])
def test_a_chat_request_without_a_json_content_type_is_refused(client, backend, path):
    """`get_json(force=True)` parsed the body regardless of Content-Type,
    which is what made a cross-site `enctype="text/plain"` form reachable.
    Without `force`, a non-JSON content type must be a 400, not a 500 and not
    a silently-accepted request."""
    response = client.post(
        path, data='{"query": "forged"}', content_type="text/plain", headers=AUTH,
    )

    # Not force-parsed into a valid query any more: `get_json(silent=True)`
    # without `force=True` returns None for a non-JSON content type, so this
    # is the ordinary "Query cannot be empty" 400 — not a 500, and not the
    # request quietly succeeding as it would have under `force=True`.
    assert response.status_code == 400
    assert backend.list_sessions(OWNER).sessions == []
