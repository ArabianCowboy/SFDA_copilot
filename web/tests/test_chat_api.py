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
from web.services.search_exceptions import SearchEngineError


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

    # Tests that need a different answer set config["llm_answer"] rather than
    # replacing this side_effect, so the recording above survives the override.
    application.config["llm_answer"] = (ANSWER, SUGGESTIONS)

    def record(query, llm_context, category, chat_history, lang="en"):
        calls.append(
            {
                "query": query,
                "llm_context": copy.deepcopy(llm_context),
                "category": category,
                "history": copy.deepcopy(chat_history),
                "lang": lang,
            }
        )
        return application.config["llm_answer"]

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


def test_a_retrieval_failure_is_an_error_not_a_refusal(app, client):
    """An outage must not be served as a confident "I cannot answer".

    `search()` used to swallow embedding, translation and index failures into
    the same empty list a successful no-match search returns. Empty is
    load-bearing now — it makes `_prepare_context` tell the model no relevant
    information was found, so the model refuses — which meant an OpenAI
    translation outage would have rendered as a clean, sourceless refusal
    rather than as a fault. The reader could not tell "the corpus has no
    guidance on this" from "the retriever fell over".
    """
    app.config["search_engine"].search.side_effect = SearchEngineError("index unreadable")
    response = client.post("/api/chat", json={"query": "hello"}, headers=AUTH)

    assert response.status_code == 503
    assert "unavailable" in response.get_json()["error"].lower()
    # The model must never have been asked in the first place.
    assert app.config["llm_calls"] == []


def test_a_retrieval_failure_does_not_start_a_conversation(app, client):
    """Retrieval runs BEFORE conversation setup, and that ordering is load-bearing.

    A question that never reached the model must not leave a `conv_id` behind
    in the reader's cookie: the next successful question would then continue a
    conversation whose first turn does not exist. Pinning it because the
    ordering reads like an accident and a tidy-up would move it.
    """
    app.config["search_engine"].search.side_effect = SearchEngineError("index unreadable")
    assert client.post("/api/chat", json={"query": "hello"}, headers=AUTH).status_code == 503

    with client.session_transaction() as flask_session:
        assert "conv_id" not in flask_session


def test_a_malformed_body_is_a_400_not_a_500(app, client):
    """The client got its JSON wrong; that is not an internal server error.

    This route used to parse with `get_json(force=True)` and no `silent=True`,
    inside a broad `except Exception` that answered 500 — so a bad body was
    reported as our fault while the streaming route, sharing the contract,
    correctly called the same body a 400.
    """
    response = client.post(
        "/api/chat", data="{not json at all", content_type="application/json", headers=AUTH
    )

    assert response.status_code == 400
    assert app.config["llm_calls"] == []


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


# ── Sources ─────────────────────────────────────────────────────────────────

def test_sources_are_only_what_the_answer_cited(client):
    """The contract: `sources` is evidence, not retrieval output.

    Eight passages are retrieved and eight reach the prompt, but ANSWER cites
    only [1]. Shipping the other seven is what put a full deck of cards under
    answers that never used them.
    """
    body = client.post("/api/chat", json={"query": "hello"}, headers=AUTH).get_json()
    assert body["cited"] == [1]
    assert [s["index"] for s in body["sources"]] == [1]
    assert body["retrieved"] == 8
    assert set(body["sources"][0]) == {
        "index", "document", "page", "category",
        "score", "semantic_score", "lexical_score", "chunk_id", "snippet",
    }


def test_an_answer_citing_nothing_ships_no_sources(app, client):
    """A refusal must not look sourced.

    Eight passages were retrieved and reached the prompt, but the answer used
    none of them, so none of them are its evidence and NOTHING is shipped for
    the client to render. `retrieved` survives as a count for the stage line
    and the logs; the passages stay server-side.
    """
    app.config["llm_answer"] = ("I cannot answer based on the given information.", [])
    body = client.post("/api/chat", json={"query": "who is claude?"}, headers=AUTH).get_json()

    assert body["cited"] == []
    assert body["sources"] == []
    assert body["retrieved"] == 8


def test_source_indices_align_with_the_prompt_context(app, client):
    """A source's index must be the block number the model saw it as.

    Filtering to cited passages makes the indices sparse, so this is the
    invariant that keeps [3] pointing at the passage the model labelled 3
    rather than at the third surviving card.
    """
    app.config["llm_answer"] = ("First [1]. Third [3]. Last [8].", [])
    body = client.post("/api/chat", json={"query": "hello"}, headers=AUTH).get_json()
    llm_context = app.config["llm_calls"][-1]["llm_context"]

    assert body["cited"] == [1, 3, 8]
    assert [s["index"] for s in body["sources"]] == [1, 3, 8]
    for source in body["sources"]:
        context = llm_context[source["index"] - 1]
        assert source["document"] == context["document"]
        assert source["page"] == context["page"]


def test_out_of_range_citations_are_not_reported(app, client):
    """[9] against 8 passages is a hallucination, not a citation."""
    app.config["llm_answer"] = ("Supported [9].", [])
    body = client.post("/api/chat", json={"query": "hello"}, headers=AUTH).get_json()
    assert body["cited"] == []


def test_lang_is_forwarded_to_the_model(app, client):
    """The blocking route used to drop `lang`, so a reader on a browser
    without streaming bodies asked in Arabic and was answered in English."""
    client.post("/api/chat", json={"query": "مرحبا", "lang": "ar"}, headers=AUTH)
    assert app.config["llm_calls"][-1]["lang"] == "ar"


def test_an_unknown_lang_falls_back_to_english(app, client):
    client.post("/api/chat", json={"query": "hello", "lang": "fr"}, headers=AUTH)
    assert app.config["llm_calls"][-1]["lang"] == "en"


def test_sources_survive_numpy_scalars_from_the_search_layer(app, client):
    import numpy as np
    app.config["search_engine"].search.return_value = [
        SearchResult(
            text="chunk", score=np.float32(0.5), document="A.pdf", category="regulatory",
            page=np.int64(7), chunk_id="a_p7",
            metadata={"semantic_score": np.float64(0.4), "lexical_score": np.float32(0.6)},
        )
    ]
    response = client.post("/api/chat", json={"query": "hello"}, headers=AUTH)
    assert response.status_code == 200
    assert response.get_json()["sources"][0]["page"] == 7


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
