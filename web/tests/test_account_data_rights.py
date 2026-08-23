"""Data-rights Flask routes: `GET /account/api/export`,
`DELETE /account/api/conversations` (web/api/account.py, Step 7 of
docs/profile-refactor-plan.md).

These test the ROUTE wiring — auth, scoping, response shape, the
in-flight refusal — not the pagination logic itself, which
test_chat_store_export.py already covers directly against the persistence
double.
"""

from __future__ import annotations

import json
import threading

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


def ask(client, query="What are the requirements?", headers=AUTH, **body):
    body.setdefault("query", query)
    response = client.post("/api/chat/stream", json=body, headers=headers)
    response.get_data()
    return response


def ndjson_lines(response):
    text = response.get_data(as_text=True).strip("\n")
    return [json.loads(line) for line in text.split("\n") if line]


# ── Export ─────────────────────────────────────────────────────────────────


def test_export_requires_a_bearer_token(client):
    response = client.get("/account/api/export")
    assert response.status_code == 401


def test_export_streams_ndjson_with_a_download_header(client, backend):
    ask(client, "How long does a variation review take?")

    response = client.get("/account/api/export", headers=AUTH)

    assert response.status_code == 200
    assert response.mimetype == "application/x-ndjson"
    assert "attachment" in response.headers["Content-Disposition"]
    assert response.headers["Cache-Control"] == "private, no-store"

    lines = ndjson_lines(response)
    header, session = lines[0], lines[1]
    assert header["export_version"] == 1
    assert header["user_id"] == OWNER
    assert session["session_id"]
    assert session["messages"][0]["content"] == "How long does a variation review take?"
    assert session["messages"][1]["role"] == "assistant"


def test_export_is_scoped_to_the_caller_never_another_reader(client, backend):
    ask(client, "Reader A's question", headers=AUTH)
    ask(client, "Reader B's question", headers=AUTH_B)

    lines = ndjson_lines(client.get("/account/api/export", headers=AUTH))
    sessions = lines[1:]

    assert len(sessions) == 1
    all_content = json.dumps(sessions)
    assert "Reader A's question" in all_content
    assert "Reader B's question" not in all_content


def test_export_with_no_history_is_the_header_line_alone(client, backend):
    lines = ndjson_lines(client.get("/account/api/export", headers=AUTH))
    assert len(lines) == 1
    assert lines[0]["export_version"] == 1


# ── Bulk conversation deletion ───────────────────────────────────────────────


def test_delete_all_conversations_requires_a_bearer_token(client):
    response = client.delete("/account/api/conversations")
    assert response.status_code == 401


def test_delete_all_conversations_removes_every_owned_session(client, backend):
    ask(client, "First conversation", headers=AUTH)
    ask(client, "Second conversation", headers=AUTH)
    ask(client, "Reader B's conversation", headers=AUTH_B)

    response = client.delete("/account/api/conversations", headers=AUTH)

    assert response.status_code == 200
    body = response.get_json()
    assert body == {"ok": True, "deleted_count": 2}
    assert backend.list_sessions(OWNER).sessions == []
    # Reader B's history is untouched — this must never be a
    # delete-everyone's-history route.
    assert len(backend.list_sessions(OWNER_B).sessions) == 1


def test_delete_all_conversations_on_an_empty_history_is_a_quiet_success(client, backend):
    response = client.delete("/account/api/conversations", headers=AUTH)
    assert response.get_json() == {"ok": True, "deleted_count": 0}


def test_delete_all_conversations_is_refused_while_any_answer_is_generating(app):
    """The bulk form of the single-delete route's own in-flight guard
    (test_chat_sessions.py) — a live `chat_append_turn` finishing after the
    delete would resurrect the row it lands on via
    `on conflict (id) do nothing`."""
    client = app.test_client()
    entered = threading.Event()
    release = threading.Event()

    def slow_stream(*args, **kwargs):
        entered.set()
        release.wait(5)
        return iter(ANSWER_TOKENS)

    app.config["openai_handler"].stream_response.side_effect = slow_stream

    streamed = []

    def run_stream():
        response = client.post(
            "/api/chat/stream",
            json={
                "query": "A slow question",
                "conversation_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            },
            headers=AUTH,
        )
        streamed.append(response.get_data())

    thread = threading.Thread(target=run_stream)
    thread.start()
    assert entered.wait(5), "the stream never started"

    try:
        racer = app.test_client()
        refused = racer.delete("/account/api/conversations", headers=AUTH)
    finally:
        release.set()
        thread.join(10)

    assert refused.status_code == 409
    assert refused.get_json()["code"] == "generation_in_flight"
