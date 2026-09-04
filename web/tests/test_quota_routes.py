"""The allowance where it meets a request: exhaustion, the 429, and the refund.

The unit-level semantics live in `test_quota.py`. This file is about the things
only a real request can show — that exhaustion is refused BEFORE the model is
called, that a failure before the first token gives the message back, that a
failure after it does not, and that both chat routes spend one shared counter.
"""

from __future__ import annotations

import json
import uuid

import pytest

from web.api.app import create_app
from web.services.openai_app import GenerationFailed
from web.services.result_combiner import SearchResult
from web.services.search_exceptions import SearchEngineError

AUTH = {"Authorization": "Bearer fake_token"}
OWNER = "test-user-id"
ANSWER_TOKENS = ["Applications ", "must be filed ", "within 15 days [1]."]


def make_result(index: int = 1) -> SearchResult:
    """The shape ResultCombiner emits — `_retrieve_for_prompt` reads attributes."""
    return SearchResult(
        text=f"Chunk {index} body text about registration requirements.",
        score=0.7143,
        document=f"2022-10-19_Guidance_for_Submission_{index}.pdf",
        category="regulatory",
        page=14,
        chunk_id=f"guidance_{index}.pdf_p14_2",
        metadata={"semantic_score": 0.63, "lexical_score": 0.79, "original_index": index},
    )


@pytest.fixture
def app():
    application = create_app(testing=True)
    application.config["search_engine"].search.return_value = [make_result(i) for i in range(1, 9)]
    handler = application.config["openai_handler"]
    handler.generate_response.side_effect = lambda *a, **k: ("".join(ANSWER_TOKENS), [])
    handler.stream_response.side_effect = lambda *a, **k: iter(ANSWER_TOKENS)
    return application


@pytest.fixture
def quota(app):
    """The in-memory allowance this app's routes actually read."""
    backend = app.config["_testing_quota_backend"]
    backend.profile_tiers[OWNER] = "free"
    return backend


@pytest.fixture
def client(app):
    return app.test_client()


def payload():
    return {
        "query": "ما هي متطلبات تسجيل الأدوية؟",
        "category": "all",
        "lang": "ar",
        "client_request_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "allow_create": True,
    }


def post_stream(client, **kw):
    """POST to the streaming route AND CONSUME THE BODY.

    Not optional. A `stream_with_context` response whose body is never read is
    garbage-collected, which throws GeneratorExit into the generator before any
    token has been yielded — so `spent` is False and the claim is correctly
    refunded. That is right for a real client that disconnects instantly, and it
    silently zeroes the counter in any test that only looks at `status_code`.
    """
    response = client.post("/api/chat/stream", **kw)
    response.get_data()
    return response


def frames(response):
    out = []
    for block in response.get_data(as_text=True).split("\n\n"):
        event = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event:
            out.append((event, data))
    return out


# ── exhaustion ───────────────────────────────────────────────────────────────


def test_exhaustion_is_a_429_before_any_frame_and_no_model_call(app, client, quota):
    """A denial must be a clean 429, never a dying SSE stream."""
    quota.tiers["free"]["daily_message_limit"] = 1
    assert post_stream(client, json=payload(), headers=AUTH).status_code == 200
    app.config["openai_handler"].stream_response.reset_mock()

    refused = post_stream(client, json=payload(), headers=AUTH)
    assert refused.status_code == 429
    assert refused.mimetype == "application/json"  # not text/event-stream
    body = refused.get_json()
    assert body["error"] == "quota_exhausted"
    assert body["remaining"] == 0
    assert body["limit"] == 1
    assert body["resets_at"]
    assert int(refused.headers["Retry-After"]) > 0
    assert refused.headers["Cache-Control"] == "no-store"
    # The whole point: no money was spent proving the reader is out of allowance.
    assert app.config["openai_handler"].stream_response.call_count == 0


def test_the_blocking_route_refuses_the_same_way(app, client, quota):
    quota.tiers["free"]["daily_message_limit"] = 1
    assert client.post("/api/chat", json=payload(), headers=AUTH).status_code == 200
    app.config["openai_handler"].generate_response.reset_mock()

    refused = client.post("/api/chat", json=payload(), headers=AUTH)
    assert refused.status_code == 429
    assert refused.get_json()["error"] == "quota_exhausted"
    assert app.config["openai_handler"].generate_response.call_count == 0


def test_the_two_routes_share_one_allowance(client, quota):
    """Alternating endpoints must not double what a reader may ask."""
    quota.tiers["free"]["daily_message_limit"] = 2
    assert client.post("/api/chat", json=payload(), headers=AUTH).status_code == 200
    assert post_stream(client, json=payload(), headers=AUTH).status_code == 200
    assert client.post("/api/chat", json=payload(), headers=AUTH).status_code == 429


def test_a_zero_limit_refuses_the_first_question_of_the_day(app, client, quota):
    quota.tiers["free"]["daily_message_limit"] = 0
    refused = post_stream(client, json=payload(), headers=AUTH)
    assert refused.status_code == 429
    assert app.config["openai_handler"].stream_response.call_count == 0


# ── the counter rides the response ───────────────────────────────────────────


def test_the_done_frame_carries_the_counter(client, quota):
    quota.tiers["free"]["daily_message_limit"] = 10
    response = post_stream(client, json=payload(), headers=AUTH)
    done = dict(frames(response))["done"]
    assert done["quota"] == {
        "used": 1,
        "limit": 10,
        "remaining": 9,
        "resets_at": done["quota"]["resets_at"],
    }


def test_the_blocking_response_carries_the_same_shape(client, quota):
    quota.tiers["free"]["daily_message_limit"] = 10
    body = client.post("/api/chat", json=payload(), headers=AUTH).get_json()
    assert set(body["quota"]) == {"used", "limit", "remaining", "resets_at"}
    assert body["quota"]["used"] == 1


# ── the refund boundary ──────────────────────────────────────────────────────


def test_a_retrieval_failure_gives_the_message_back(app, client, quota):
    quota.tiers["free"]["daily_message_limit"] = 5
    app.config["search_engine"].search.side_effect = SearchEngineError("down")
    post_stream(client, json=payload(), headers=AUTH)
    assert quota.usage.get((OWNER, quota._today()), 0) == 0, "retrieval never reached the model"


def test_a_provider_failure_on_the_first_token_gives_the_message_back(app, client, quota):
    """The case a `spent` flag set before the loop would have silently charged.

    `stream_response` is a GENERATOR FUNCTION: calling it builds a generator and
    runs none of its body. `_build_messages` and the provider call both happen on
    the first next(), so a provider auth error, 429 or timeout raises INSIDE the
    loop — after the call that a naive implementation would have marked as spent.
    """
    quota.tiers["free"]["daily_message_limit"] = 5

    def explodes_on_first_next(*a, **k):
        raise RuntimeError("provider refused the connection")
        yield  # pragma: no cover - makes this a generator function

    app.config["openai_handler"].stream_response.side_effect = explodes_on_first_next
    post_stream(client, json=payload(), headers=AUTH)
    assert quota.usage.get((OWNER, quota._today()), 0) == 0, (
        "a provider failure before the first token must be refunded"
    )


def test_a_failure_after_the_first_token_is_NOT_refunded(app, client, quota):
    """The reader consumed a real model call; refunding it is the classic exploit."""
    quota.tiers["free"]["daily_message_limit"] = 5

    def dies_midway(*a, **k):
        yield "Applications "
        raise RuntimeError("connection dropped mid-answer")

    app.config["openai_handler"].stream_response.side_effect = dies_midway
    post_stream(client, json=payload(), headers=AUTH)
    assert quota.usage.get((OWNER, quota._today()), 0) == 1


def test_the_blocking_route_refunds_a_generation_failure(app, client, quota):
    """Only possible since `generate_response` stopped returning apology prose.

    It used to swallow every provider error and return "I'm sorry, I encountered
    an error…" as an answer, which the route then finalized, PERSISTED as a
    regulatory answer, returned 200 for — and, with a quota, would have charged.
    """
    quota.tiers["free"]["daily_message_limit"] = 5
    app.config["openai_handler"].generate_response.side_effect = GenerationFailed("no answer")
    response = client.post("/api/chat", json=payload(), headers=AUTH)
    assert response.status_code == 503
    assert response.get_json()["code"] == "generation_failed"
    assert quota.usage.get((OWNER, quota._today()), 0) == 0


def test_a_400_spends_nothing(client, quota):
    quota.tiers["free"]["daily_message_limit"] = 5
    bad = dict(payload())
    bad["query"] = ""
    assert post_stream(client, json=bad, headers=AUTH).status_code == 400
    assert quota.usage.get((OWNER, quota._today()), 0) == 0


def test_an_unknown_conversation_spends_nothing(client, quota):
    quota.tiers["free"]["daily_message_limit"] = 5
    body = dict(payload())
    body["allow_create"] = False
    assert post_stream(client, json=body, headers=AUTH).status_code == 404
    assert quota.usage.get((OWNER, quota._today()), 0) == 0


def test_one_request_refunds_at_most_once(app, client, quota):
    """The `released` guard.

    The RPC is deliberately not idempotent — `greatest(0, used - 1)` decrements
    on every call — so a second refund inside one request would hand back a
    message the reader actually spent.
    """
    quota.tiers["free"]["daily_message_limit"] = 5
    post_stream(client, json=payload(), headers=AUTH)  # used = 1
    day = quota._today()
    assert quota.usage[(OWNER, day)] == 1

    app.config["search_engine"].search.side_effect = SearchEngineError("down")
    post_stream(client, json=payload(), headers=AUTH)
    # The failed request claimed one (2) and refunded exactly one (1).
    assert quota.usage[(OWNER, day)] == 1


# ── degradation ──────────────────────────────────────────────────────────────


def test_a_backend_fault_streams_the_answer_uncounted(app, client, quota):
    """Fail OPEN on a transport fault: an allowance is not a credential."""

    def boom(*a, **k):
        raise RuntimeError("transport blip")

    app.config["_testing_quota_backend"].claim = boom
    response = post_stream(client, json=payload(), headers=AUTH)
    assert response.status_code == 200
    assert dict(frames(response))["done"]["quota"] is None
