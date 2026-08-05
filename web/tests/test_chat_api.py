"""Direct tests for the /api/chat route.

The Playwright suite intercepts ``**/api/chat`` with ``page.route(...)`` and
fulfils canned JSON, so the real Flask chat route has never actually executed
under test. These tests drive it through ``app.test_client()`` instead, with the
``MagicMock`` search engine and LLM handler configured to return real objects.

This is the harness the sources payload and the SSE stream both build on.
"""

from __future__ import annotations

import copy
import json

import pytest

from web.api.app import create_app
from web.services.result_combiner import SearchResult


AUTH = {"Authorization": "Bearer fake_token"}


def make_result(index: int = 1, page: int | None = 14) -> SearchResult:
    """A realistic SearchResult, shaped like what ResultCombiner emits."""
    return SearchResult(
        text=f"Chunk {index} body text about registration requirements.",
        score=0.7143,
        document=f"2022-10-19_Guidance_for_Submission_{index}.pdf",
        category="regulatory",
        page=page,
        chunk_id=f"guidance_{index}.pdf_p{page}_2",
        metadata={
            "semantic_score": 0.6312,
            "lexical_score": 0.7975,
            "original_index": index,
            "raw_hybrid_score": 0.7143,
            "penalty_reason": None,
        },
    )


ANSWER = "Applications must be submitted within 15 days [1]."
SUGGESTIONS = ["What documents are required?", "How long does review take?"]


@pytest.fixture
def app():
    """A testing app whose mocked services return real objects, not MagicMocks."""
    application = create_app(testing=True)
    application.config["search_engine"].search.return_value = [
        make_result(i) for i in range(1, 9)
    ]

    # handle_chat extends the very list it just passed to generate_response, so
    # mock.call_args would hand back the *mutated* list. Snapshot at call time.
    calls: list[dict] = []

    def record(query, llm_context, category, chat_history):
        calls.append(
            {
                "query": query,
                "llm_context": copy.deepcopy(llm_context),
                "category": category,
                "history": copy.deepcopy(chat_history),
            }
        )
        return ANSWER, SUGGESTIONS

    application.config["openai_handler"].generate_response.side_effect = record
    application.config["llm_calls"] = calls
    return application


@pytest.fixture
def client(app):
    return app.test_client()


# ── Auth ────────────────────────────────────────────────────────────────────

def test_chat_requires_a_token(client):
    response = client.post("/api/chat", json={"query": "hello"})
    assert response.status_code == 401
    assert response.get_json()["error"] == "Invalid or missing test token"


# ── Validation ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", ["", "   "])
def test_empty_query_is_rejected(client, query):
    response = client.post("/api/chat", json={"query": query}, headers=AUTH)
    assert response.status_code == 400
    assert response.get_json()["error"] == "Query cannot be empty"


def test_unknown_category_is_rejected(client):
    response = client.post(
        "/api/chat", json={"query": "hello", "category": "nuclear"}, headers=AUTH
    )
    assert response.status_code == 400
    assert "Invalid category" in response.get_json()["error"]


def test_search_engine_down_returns_503(app, client):
    app.config["search_engine"].is_initialized = lambda: False
    response = client.post("/api/chat", json={"query": "hello"}, headers=AUTH)
    assert response.status_code == 503


# ── Happy path ──────────────────────────────────────────────────────────────

def test_chat_returns_answer_and_suggestions(client):
    response = client.post(
        "/api/chat", json={"query": "What are the requirements?", "category": "regulatory"},
        headers=AUTH,
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["response"] == ANSWER
    assert body["suggested_questions"] == SUGGESTIONS


def test_llm_receives_only_the_context_fields_it_needs(app, client):
    client.post("/api/chat", json={"query": "hello"}, headers=AUTH)
    llm_context = app.config["llm_calls"][-1]["llm_context"]
    assert len(llm_context) == 8
    assert set(llm_context[0]) == {"text", "document", "category", "page"}


def test_response_is_json_serialisable_end_to_end(client):
    """Guards against numpy scalars leaking out of the search layer."""
    response = client.post("/api/chat", json={"query": "hello"}, headers=AUTH)
    json.dumps(response.get_json())


# ── Conversation history ────────────────────────────────────────────────────

def test_first_turn_sees_no_history(app, client):
    client.post("/api/chat", json={"query": "first question"}, headers=AUTH)
    assert app.config["llm_calls"][0]["history"] == []


def test_history_accumulates_across_turns(app, client):
    client.post("/api/chat", json={"query": "first question"}, headers=AUTH)
    client.post("/api/chat", json={"query": "second question"}, headers=AUTH)

    assert [m["content"] for m in app.config["llm_calls"][1]["history"]] == [
        "first question",
        ANSWER,
    ]


def test_history_is_capped_by_pair_count(app, client):
    max_pairs = app.config["MAX_CHAT_HISTORY_MESSAGE_PAIRS"]
    for i in range(max_pairs + 3):
        client.post("/api/chat", json={"query": f"question {i}"}, headers=AUTH)

    history = app.config["llm_calls"][-1]["history"]
    assert len(history) <= max_pairs * 2
    # Oldest pairs are dropped, not newest.
    assert history[-2]["content"] == f"question {max_pairs + 1}"
