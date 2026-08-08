"""Tests for POST /api/chat/stream and the conversation store.

The frame-order test is the important one. Sources used to be emitted BEFORE
the first token, which meant they could not reflect what the answer did with
them — a refusal shipped with eight source cards attached. They now ride on a
terminal `final` frame carrying the canonical, normalized answer.
"""

from __future__ import annotations

import json

import pytest

from web.api.app import create_app
from web.services.conversation_store import ConversationStore
from web.services.result_combiner import SearchResult
from web.services.search_exceptions import SearchEngineError


AUTH = {"Authorization": "Bearer fake_token"}
ANSWER_TOKENS = ["Applications ", "must be ", "submitted [1]."]


def make_result(index: int = 1) -> SearchResult:
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
    application.config["search_engine"].search.return_value = [make_result(i) for i in range(1, 9)]
    handler = application.config["openai_handler"]
    handler.model = "gpt-4o-mini"
    handler.stream_response.side_effect = lambda *a, **k: iter(ANSWER_TOKENS)
    handler.generate_suggestions.return_value = ["Follow up?"]
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def read_frames(response) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, data) pairs."""
    frames = []
    for block in response.get_data(as_text=True).split("\n\n"):
        if not block.strip():
            continue
        event, data = "message", None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        if data is not None:
            frames.append((event, data))
    return frames


def post(client, **body):
    """POST and fully consume the body.

    The Flask test client does not run a streamed generator until the body is
    read, so without get_data() the view's generator never executes and none
    of the handler calls happen.
    """
    body.setdefault("query", "What are the requirements?")
    response = client.post("/api/chat/stream", json=body, headers=AUTH)
    response.get_data()
    return response


# ── Transport ───────────────────────────────────────────────────────────────

def test_response_declares_a_non_buffering_event_stream(client):
    response = post(client)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/event-stream; charset=utf-8"
    # Without this nginx buffers the whole answer and the feature does nothing.
    assert response.headers["X-Accel-Buffering"] == "no"
    assert "no-cache" in response.headers["Cache-Control"]


def test_frames_are_bytes():
    """Regression: with direct_passthrough the WSGI server asserts
    'applications must write bytes'. Yielding str produces a 200 with correct
    headers and an EMPTY body — and the Flask test client does not reproduce it,
    because it encodes on the way out. Only a real server catches this."""
    from web.services.sse import ping, sse
    assert isinstance(sse("stage", {"stage": "searching"}), bytes)
    assert isinstance(ping(), bytes)


def test_view_yields_bytes_end_to_end(app):
    """Exercise the raw generator the way the WSGI server would."""
    with app.test_request_context(
        "/api/chat/stream", method="POST", headers=AUTH, json={"query": "hi"}
    ):
        response = app.view_functions["handle_chat_stream"]()
        for chunk in response.response:
            assert isinstance(chunk, bytes), f"generator yielded {type(chunk).__name__}"


def test_stream_requires_auth(client):
    assert client.post("/api/chat/stream", json={"query": "hi"}).status_code == 401


@pytest.mark.parametrize(
    "body,status",
    [({"query": "   "}, 400), ({"query": "hi", "category": "nuclear"}, 400)],
)
def test_validation_errors_are_plain_json_with_a_real_status(client, body, status):
    """Errors before the first frame must not be in-band, so response.ok works."""
    response = client.post("/api/chat/stream", json=body, headers=AUTH)
    assert response.status_code == status
    assert response.headers["Content-Type"].startswith("application/json")


def test_search_unavailable_returns_503_not_a_stream(app, client):
    app.config["search_engine"].is_initialized = lambda: False
    assert post(client).status_code == 503


def test_a_retrieval_failure_is_reported_as_an_error_not_a_refusal(app, client):
    """The 200 status line is already sent, so this can only arrive in-band.

    It carries its own code rather than folding into "internal": the
    alternative — treating a failure as an empty result set — produces a
    fluent, sourceless "I cannot answer based on the given information",
    which is indistinguishable from the corpus genuinely having nothing.
    """
    app.config["search_engine"].search.side_effect = SearchEngineError("index unreadable")
    frames = dict(read_frames(post(client)))

    assert frames["error"]["code"] == "search_unavailable"
    # No answer was drafted, so nothing can be mistaken for one.
    assert "final" not in frames
    assert "done" not in frames


# ── Frame ordering ──────────────────────────────────────────────────────────

def test_frame_sequence(client):
    events = [event for event, _ in read_frames(post(client))]
    assert events == [
        "meta",
        "stage",        # searching
        "stage",        # retrieved
        "stage",        # drafting
        *["delta"] * len(ANSWER_TOKENS),
        "stage",        # finalizing
        "final",
        "suggestions",
        "done",
    ]


def test_no_sources_frame_precedes_the_answer(client):
    """Retrieval count mid-stream, passages only at the end.

    There is no honest way to present passages as an answer's sources before
    the answer exists, and doing so is what put a full deck under refusals.
    """
    events = [event for event, _ in read_frames(post(client))]
    assert "sources" not in events
    assert events.index("final") > events.index("delta")


def test_stage_events_report_real_retrieval_counts(client):
    stages = {d["stage"]: d for e, d in read_frames(post(client)) if e == "stage"}
    assert set(stages) == {"searching", "retrieved", "drafting", "finalizing"}
    assert stages["retrieved"]["count"] == 8


def test_deltas_reassemble_into_the_answer(client):
    deltas = [d["t"] for e, d in read_frames(post(client)) if e == "delta"]
    assert "".join(deltas) == "".join(ANSWER_TOKENS)


def test_done_reports_the_final_length(client):
    frames = dict(read_frames(post(client)))
    assert frames["done"]["finish_reason"] == "stop"
    assert frames["done"]["chars"] == len("".join(ANSWER_TOKENS).strip())


def test_final_payload_is_json_native(client):
    """Guards against numpy scalars leaking out of the search layer."""
    frames = dict(read_frames(post(client)))
    json.dumps(frames["final"])


def test_final_reports_only_the_cited_passages(client):
    """ANSWER_TOKENS cite [1] only; the other seven were retrieved, not used."""
    final = dict(read_frames(post(client)))["final"]
    assert final["cited"] == [1]
    assert [s["index"] for s in final["sources"]] == [1]
    assert final["retrieved"] == 8


def test_an_answer_citing_nothing_reports_an_empty_cited(app, client):
    """The reported bug: a refusal must not arrive looking sourced."""
    app.config["openai_handler"].stream_response.side_effect = (
        lambda *a, **k: iter(["I cannot answer ", "based on the given information."])
    )
    final = dict(read_frames(post(client)))["final"]
    assert final["cited"] == []
    # Nothing to render: sources means evidence, and this answer has none.
    assert final["sources"] == []
    # The count survives for the stage line and the logs.
    assert final["retrieved"] == 8


def test_out_of_range_citations_are_not_reported(app, client):
    app.config["openai_handler"].stream_response.side_effect = (
        lambda *a, **k: iter(["Supported ", "[9]."])
    )
    assert dict(read_frames(post(client)))["final"]["cited"] == []


def test_final_response_is_normalized_not_the_raw_deltas(app, client):
    """The defect this restructure exists to close.

    Deltas carry raw model tokens. The server rewrites legacy
    "[Source: Doc, Page: N]" citations into "[n]" before deciding anything
    about them, so a client that kept the delta text would show prose while
    the API reported a citation of source 1 — a marker the reader is told
    exists and cannot click. `final.response` is what the client re-renders.
    """
    app.config["openai_handler"].stream_response.side_effect = (
        lambda *a, **k: iter(["Submit within 15 days ", "[Source: Doc_1.pdf, Page: 1]."])
    )
    frames = read_frames(post(client))
    deltas = "".join(d["t"] for e, d in frames if e == "delta")
    final = dict(frames)["final"]

    assert "[Source:" in deltas
    assert "[Source:" not in final["response"]
    assert final["response"] == "Submit within 15 days [1]."
    assert final["cited"] == [1]


def test_language_is_echoed_and_validated(client):
    assert dict(read_frames(post(client, lang="ar")))["meta"]["lang"] == "ar"
    assert dict(read_frames(post(client, lang="klingon")))["meta"]["lang"] == "en"


def test_lang_is_forwarded_to_the_model(app, client):
    post(client, lang="ar")
    assert app.config["openai_handler"].stream_response.call_args.kwargs["lang"] == "ar"


# ── Failure mid-stream ──────────────────────────────────────────────────────

def test_model_failure_after_streaming_starts_is_reported_in_band(app, client):
    def explode(*args, **kwargs):
        yield "partial "
        raise RuntimeError("upstream died")

    app.config["openai_handler"].stream_response.side_effect = explode
    response = post(client)
    frames = read_frames(response)

    # Status is already 200 by then; the failure can only arrive as an event.
    assert response.status_code == 200
    assert [e for e, _ in frames][-1] == "error"
    assert dict(frames)["error"]["code"] == "internal"
    # The partial answer is still delivered so the client can keep it.
    assert any(e == "delta" for e, _ in frames)


# ── History persistence across a streaming response ─────────────────────────

def test_history_survives_the_streaming_response(app, client):
    """The Flask-session trap: a session write inside the generator would be
    silently discarded, so history lives in ConversationStore instead."""
    post(client, query="first question")
    post(client, query="second question")

    history = app.config["openai_handler"].stream_response.call_args.args[3]
    assert [m["content"] for m in history] == [
        "first question",
        "".join(ANSWER_TOKENS).strip(),
    ]


def test_cancelled_turn_is_not_recorded(app, client):
    """A generator closed early must skip append_turn."""
    store = app.config["conversations"]
    with app.test_request_context():
        pass

    def stall(*args, **kwargs):
        yield "partial"
        raise GeneratorExit

    app.config["openai_handler"].stream_response.side_effect = stall
    try:
        post(client)
    except GeneratorExit:
        pass
    assert len(store) == 0


# ── ConversationStore ───────────────────────────────────────────────────────

def test_store_round_trips_a_turn():
    store = ConversationStore()
    store.append_turn("c1", "q", "a", max_pairs=10, max_chars=10_000)
    assert store.get("c1") == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
    ]


def test_store_caps_by_pair_count():
    store = ConversationStore()
    for i in range(12):
        store.append_turn("c1", f"q{i}", f"a{i}", max_pairs=3, max_chars=100_000)
    history = store.get("c1")
    assert len(history) == 6
    assert history[0]["content"] == "q9"  # oldest pairs dropped, not newest


def test_store_caps_by_serialized_size():
    store = ConversationStore()
    for i in range(6):
        store.append_turn("c1", "q" * 200, "a" * 200, max_pairs=50, max_chars=1_000)
    assert len(json.dumps(store.get("c1"))) <= 1_000


def test_store_evicts_least_recently_used():
    store = ConversationStore(max_conversations=2)
    for cid in ("a", "b", "c"):
        store.append_turn(cid, "q", "a", max_pairs=5, max_chars=10_000)
    assert len(store) == 2
    assert store.get("a") == []


def test_adopt_cookie_history_migrates_once():
    store = ConversationStore()
    legacy = [{"role": "user", "content": "before deploy"}]
    store.adopt_cookie_history("c1", legacy)
    store.adopt_cookie_history("c1", [{"role": "user", "content": "should not overwrite"}])
    assert store.get("c1") == legacy


def test_adopt_ignores_empty_history():
    store = ConversationStore()
    store.adopt_cookie_history("c1", None)
    assert store.get("c1") == []


def test_unknown_conversation_is_empty_not_an_error():
    assert ConversationStore().get("nope") == []
