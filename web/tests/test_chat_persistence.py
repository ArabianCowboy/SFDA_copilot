"""Durable chat history: what actually reaches the database, and when.

The invariants under test here are the ones that cannot be read off the code.

* A turn becomes durable at `final` and not before, so a retrieval failure
  leaves no orphan question — the property
  `test_a_retrieval_failure_does_not_start_a_conversation` already pins for the
  cookie, extended to the rows.
* The citation contract survives the trip: `source_index` is the `[n]` the model
  saw, and EVERY retrieved passage is stored, not only the cited ones.
* A retry is a no-op, including on the archive and including on `seq`.
* A storage failure never costs the reader their answer.

`InMemoryChatBackend` reimplements the RPC's guarantees rather than
approximating them, so a test that passes here is making a claim about
`chat_append_turn` and not merely about the double.
"""

from __future__ import annotations

import json

import pytest

from web.api.app import create_app
from web.services.chat_store import (
    InMemoryChatBackend,
    PersistenceUnavailable,
    canonical_uuid,
)
from web.services.result_combiner import SearchResult
from web.services.search_exceptions import SearchEngineError

AUTH = {"Authorization": "Bearer fake_token"}
OWNER = "test-user-id"
AUTH_B = {"Authorization": "Bearer fake_reader_b_token"}
OWNER_B = "test-reader-b-id"

# Cites [1] and [3]. The gap is deliberate: `cited` is sparse in practice, and a
# test that only ever cites [1] cannot tell an index from a list position.
ANSWER_TOKENS = ["Applications ", "must be submitted [1] ", "within 15 days [3]."]


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
    application.config["search_engine"].search.return_value = [make_result(i) for i in range(1, 5)]
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


def frames(response) -> list[tuple[str, dict]]:
    parsed = []
    for block in response.get_data(as_text=True).split("\n\n"):
        if not block.strip():
            continue
        event, data = "message", None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:") :].strip())
        if data is not None:
            parsed.append((event, data))
    return parsed


def conversation_of(response) -> str:
    """The id a chat response's turn landed under.

    THE URL IS THE POINTER now (docs/per-tab-conversation-deep-linking-plan.md
    §1) — there is no session-held `conv_id` to read any more. Every chat
    route echoes the resolved id on the wire (§3.2), streaming inside the
    `meta`/`final`/`done` frames and blocking in the JSON body, so this reads
    it from whichever shape the caller passed.
    """
    if response.mimetype == "text/event-stream":
        meta = next(data for event, data in frames(response) if event == "meta")
        return meta["conversation_id"]
    return response.get_json()["conversation_id"]


# ── The turn becomes durable ────────────────────────────────────────────────


def test_a_streamed_turn_is_stored_as_a_user_row_and_an_assistant_row(client, backend):
    response = ask(client, "How long is the review?")
    rows = backend.load_session(OWNER, conversation_of(response))

    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[0].content == "How long is the review?"
    assert rows[1].content.startswith("Applications")
    assert rows[1].seq == rows[0].seq + 1


def test_a_blocking_turn_is_stored_too(client, backend):
    response = client.post("/api/chat", json={"query": "first"}, headers=AUTH)
    assert response.get_json()["persisted"] is True

    rows = backend.load_session(OWNER, conversation_of(response))
    assert [row.role for row in rows] == ["user", "assistant"]


def test_answer_metadata_lives_on_the_assistant_row_only(client, backend):
    """Both readings pass the schema, so the choice is asserted rather than
    inferred — otherwise two exports of the same turn disagree."""
    response = ask(client, lang="ar", category="regulatory")
    user_row, assistant_row = backend.load_session(OWNER, conversation_of(response))

    assert assistant_row.model == "gpt-4o-mini"
    assert assistant_row.lang == "ar"
    assert assistant_row.category == "regulatory"

    assert user_row.model is None
    assert user_row.lang is None
    assert user_row.category is None


def test_a_retrieval_failure_stores_nothing_at_all(app, client, backend):
    """The reason the reserve-then-finalise design was not built.

    Reserving a row in the view body would put it in front of retrieval, so
    every search outage would leave a durable session and a question with no
    answer. Writing at `final` keeps the existing guarantee — pinned for the
    cookie by test_a_retrieval_failure_does_not_start_a_conversation — and
    extends it to the rows.
    """
    app.config["search_engine"].search.side_effect = SearchEngineError("index down")

    response = ask(client)
    assert (
        "error",
        {"error": "Search service is currently unavailable.", "code": "search_unavailable"},
    ) in frames(response)

    assert backend.sessions_for(OWNER) == []
    assert backend.archive == []


def test_an_aborted_answer_leaves_no_durable_trace(app, client, backend):
    """The consequence of writing at `final`, accepted knowingly.

    A generation that dies mid-stream records nothing — exactly what happens
    today. Stated as a test so it reads as a decision rather than as a bug
    somebody later 'fixes' by reintroducing the state machine.
    """

    def die_mid_stream(*args, **kwargs):
        yield "Applications "
        raise RuntimeError("model died")

    app.config["openai_handler"].stream_response.side_effect = die_mid_stream

    ask(client)
    assert backend.sessions_for(OWNER) == []


# ── Citations survive the trip ──────────────────────────────────────────────


def test_every_retrieved_passage_is_stored_with_its_cited_flag(client, backend):
    """Not only the cited ones.

    `_finalize_answer` reduces the uncited passages to a count, which is right
    for the wire and wrong for the record: what search offered and the model
    declined is unrecoverable afterwards, because retrieval is not reproducible
    across a corpus rebuild.
    """
    response = ask(client)
    _, assistant_row = backend.load_session(OWNER, conversation_of(response))

    assert [s["source_index"] for s in assistant_row.sources] == [1, 2, 3, 4]
    assert [s["cited"] for s in assistant_row.sources] == [True, False, True, False]


def test_sources_come_back_ordered_by_source_index_regardless_of_insert_order(backend):
    """`chat_load_session` orders sources with `jsonb_agg(... order by
    src.source_index)` — a guarantee made on READ, not on write. Every other
    test in this file happens to insert sources already in index order, which
    would let `InMemoryChatBackend` echo insert order and still look correct.
    This one inserts out of order specifically to prove the double enforces
    the same ordering guarantee the RPC does, not merely whatever order a
    caller happened to append in."""
    kwargs = {
        "owner_id": OWNER,
        "session_id": "s1",
        "client_request_id": "r1",
        "question": "q",
        "answer": "a",
        "lang": "en",
        "category": "all",
        "model": "m",
        "corpus_revision": None,
        "owner_key": None,
        "session_key": None,
        "archive_opted_out": True,
    }
    backend.append_turn(
        sources=[
            {"source_index": 3, "snippet": "third"},
            {"source_index": 1, "snippet": "first"},
            {"source_index": 2, "snippet": "second"},
        ],
        **kwargs,
    )

    _, assistant_row = backend.load_session(OWNER, "s1")

    assert [s["source_index"] for s in assistant_row.sources] == [1, 2, 3]
    assert [s["snippet"] for s in assistant_row.sources] == ["first", "second", "third"]


def test_stored_source_index_is_the_marker_the_model_saw(client, backend):
    """The citation contract, as a database row.

    `build_source_payload` emits `index`; the column is `source_index`. The
    remap happens once, at the persistence boundary, so a stored row and the
    marker in the answer text cannot drift apart.
    """
    response = ask(client)
    final = next(data for event, data in frames(response) if event == "final")
    _, assistant_row = backend.load_session(OWNER, conversation_of(response))

    cited_on_the_wire = final["cited"]
    cited_in_the_rows = [s["source_index"] for s in assistant_row.sources if s["cited"]]
    assert cited_in_the_rows == cited_on_the_wire == [1, 3]

    by_index = {s["source_index"]: s for s in assistant_row.sources}
    assert by_index[3]["document"] == "Doc_3.pdf"
    assert by_index[3]["page"] == 3
    assert by_index[3]["chunk_id"] == "c3"


def test_a_turn_records_the_corpus_revision_it_was_answered_from(app, client, backend):
    """A stored citation is only openable evidence while the corpus behind it is
    the corpus that produced it. Null is `unverifiable`, never `verified`."""
    app.config["CORPUS_REVISION"] = "build-2026-08-18"

    response = ask(client)
    _, assistant_row = backend.load_session(OWNER, conversation_of(response))
    assert assistant_row.corpus_revision == "build-2026-08-18"


# ── Idempotency ─────────────────────────────────────────────────────────────


def test_a_replayed_request_id_writes_one_turn(client, backend):
    conversation_id = "aaaaaaaa-2222-3333-4444-555555555555"
    request_id = "11111111-2222-3333-4444-555555555555"
    ask(client, "same question", conversation_id=conversation_id, client_request_id=request_id)
    ask(client, "same question", conversation_id=conversation_id, client_request_id=request_id)

    rows = backend.load_session(OWNER, conversation_id)
    assert len(rows) == 2, "the retry wrote a second copy of the exchange"


def test_a_replay_does_not_advance_the_sequence(client, backend):
    """A gap in `seq` is indistinguishable from a deleted message to anything
    reading the transcript, so the counter must not move on a no-op."""
    conversation_id = "aaaaaaaa-2222-3333-4444-555555555555"
    request_id = "11111111-2222-3333-4444-555555555555"
    ask(client, "first", conversation_id=conversation_id, client_request_id=request_id)
    ask(client, "first", conversation_id=conversation_id, client_request_id=request_id)
    ask(
        client,
        "second",
        conversation_id=conversation_id,
        client_request_id="66666666-7777-8888-9999-000000000000",
    )

    seqs = [row.seq for row in backend.load_session(OWNER, conversation_id)]
    assert seqs == [1, 2, 3, 4], f"sequence gapped: {seqs}"


def test_a_replay_does_not_write_a_second_archive_row(client, backend, monkeypatch):
    """Without `unique (owner_key, turn_key)` the replay skips the message rows —
    they conflict — and silently double-weights one exchange in the archive."""
    monkeypatch.setenv("ARCHIVE_OWNER_SALT", "owner-salt")
    monkeypatch.setenv("ARCHIVE_SESSION_SALT", "session-salt")

    conversation_id = "aaaaaaaa-2222-3333-4444-555555555555"
    request_id = "11111111-2222-3333-4444-555555555555"
    ask(client, "same question", conversation_id=conversation_id, client_request_id=request_id)
    ask(client, "same question", conversation_id=conversation_id, client_request_id=request_id)

    assert len(backend.archive) == 1


def test_a_replay_is_reported_as_a_replay(backend):
    """`replayed` must come back true, or `_persist_turn`'s replay branch is
    dead code that no test ever enters — which is what it was."""
    kwargs = {
        "owner_id": OWNER,
        "session_id": "s1",
        "client_request_id": "r1",
        "question": "q",
        "answer": "a",
        "sources": [],
        "lang": "en",
        "category": "all",
        "model": "m",
        "corpus_revision": None,
        "owner_key": None,
        "session_key": None,
        "archive_opted_out": True,
    }
    first = backend.append_turn(**kwargs)
    second = backend.append_turn(**kwargs)

    assert first.replayed is False
    assert second.replayed is True
    assert second.user_message_id == first.user_message_id
    assert second.assistant_message_id == first.assistant_message_id


def test_a_replay_carrying_a_malformed_payload_is_still_a_no_op(backend):
    """The RPC's replay branch returns BEFORE it parses p_sources, so a retry
    with a bad payload is a successful no-op there. The double validated first
    and raised instead — stricter than the database on the one path where being
    stricter is wrong, and invisible because the double is what tests run on."""
    kwargs = {
        "owner_id": OWNER,
        "session_id": "s1",
        "client_request_id": "r1",
        "question": "q",
        "answer": "a",
        "lang": "en",
        "category": "all",
        "model": "m",
        "corpus_revision": None,
        "owner_key": None,
        "session_key": None,
        "archive_opted_out": True,
    }
    backend.append_turn(sources=[{"source_index": 1, "snippet": "ok"}], **kwargs)

    replayed = backend.append_turn(sources=[{"source_index": 999}], **kwargs)

    assert replayed.replayed is True
    assert len(backend.load_session(OWNER, "s1")) == 2


def test_the_archive_dedupes_per_session_not_per_owner(backend):
    """Matching `unique (owner_key, session_key, turn_key)`. Keyed on the owner
    alone, one request id reused in two conversations wrote both turns to the
    reader's history and only the first to the archive."""
    kwargs = {
        "owner_id": OWNER,
        "client_request_id": "r1",
        "question": "q",
        "answer": "a",
        "sources": [],
        "lang": "en",
        "category": "all",
        "model": "m",
        "corpus_revision": None,
        "owner_key": "owner-digest",
        "archive_opted_out": False,
    }
    backend.append_turn(session_id="s1", session_key="session-1", **kwargs)
    backend.append_turn(session_id="s2", session_key="session-2", **kwargs)

    assert len(backend.archive) == 2

    # Same session and same turn key is still one row.
    backend.append_turn(session_id="s1", session_key="session-1", **kwargs)
    assert len(backend.archive) == 2


def test_a_missing_request_id_still_answers(client, backend):
    """An old client that has not learned to mint one keeps working; it simply
    gets no replay protection."""
    conversation_id = "aaaaaaaa-2222-3333-4444-555555555555"
    ask(client, "first", conversation_id=conversation_id)
    ask(client, "first", conversation_id=conversation_id)

    assert len(backend.load_session(OWNER, conversation_id)) == 4


# ── Ownership ───────────────────────────────────────────────────────────────


def test_appending_into_someone_elses_session_is_refused(backend):
    """The guard that makes a guessed session id useless."""
    backend.append_turn(
        owner_id=OWNER,
        session_id="s1",
        client_request_id="r1",
        question="q",
        answer="a",
        sources=[],
        lang="en",
        category="all",
        model="m",
        corpus_revision=None,
        owner_key=None,
        session_key=None,
        archive_opted_out=True,
    )

    with pytest.raises(PersistenceUnavailable):
        backend.append_turn(
            owner_id=OWNER_B,
            session_id="s1",
            client_request_id="r2",
            question="q",
            answer="a",
            sources=[],
            lang="en",
            category="all",
            model="m",
            corpus_revision=None,
            owner_key=None,
            session_key=None,
            archive_opted_out=True,
        )


def test_loading_an_unowned_session_is_indistinguishable_from_an_empty_one(backend):
    """Both answer `[]`, deliberately: probing for a stranger's session id must
    not be able to tell 'not yours' from 'not there'."""
    backend.append_turn(
        owner_id=OWNER,
        session_id="s1",
        client_request_id="r1",
        question="q",
        answer="a",
        sources=[],
        lang="en",
        category="all",
        model="m",
        corpus_revision=None,
        owner_key=None,
        session_key=None,
        archive_opted_out=True,
    )

    assert backend.load_session(OWNER_B, "s1") == []
    assert backend.load_session(OWNER_B, "no-such-session") == []


# NO MORE "CURRENT-SESSION RULE" SECTION. `_resolve_conversation_id`, the
# cookie it resolved, `/api/conversation/reset` and its `undo`/`forget`
# branches are all deleted (docs/per-tab-conversation-deep-linking-plan.md
# §5.1, §5.4) — there is no session-held pointer left for a resurrection to
# exploit, because every request names its conversation explicitly and
# `ConversationStore` never resolves one on its own. "New chat" ending one
# conversation without disturbing another is now a property of two distinct
# client-minted ids never sharing a bucket, which
# `web/tests/test_multi_tab_conversations.py` proves through the real
# multi-tab surface (§7.2) rather than by simulating a cookie here.


def test_hydration_restores_the_prompt_window_after_the_cache_is_lost(app, client):
    """A process restart, the store's TTL, or a new device all land here."""
    response = ask(client, "first")
    conversation = conversation_of(response)

    app.config["conversations"].clear(conversation)
    ask(client, "second", conversation_id=conversation, allow_create=False)

    handed_to_the_model = app.config["openai_handler"].stream_response.call_args[0][3]
    assert [message["content"] for message in handed_to_the_model] == [
        "first",
        "".join(ANSWER_TOKENS),
    ]


# ── Failure is auxiliary ────────────────────────────────────────────────────


def test_a_storage_failure_still_ships_the_answer(app, client):
    """`handlers.js` already names history persistence as an auxiliary failure
    that must render the answer anyway. This is the server half of that."""

    class Broken:
        def load_session(self, *args, **kwargs):
            raise PersistenceUnavailable("down")

        def append_turn(self, **kwargs):
            raise PersistenceUnavailable("down")

    app.config["chat_backend"] = lambda: Broken()

    events = frames(ask(client))
    names = [event for event, _ in events]

    assert "final" in names and "done" in names
    assert (
        "error",
        {
            "error": "This answer could not be saved to your history.",
            "code": "persistence_unavailable",
        },
    ) in events
    # An `error` frame, not a bespoke event name: services.js dispatches with
    # `on[frame.event]?.()` and silently drops anything unregistered.
    assert "persistence_unavailable" not in names


def test_a_misconfigured_backend_fails_loud_not_silent(app, client):
    """Regression for a gap an external review caught: `backend is None` used
    to mean "no persistence, silently fine" whether the deployment turned the
    feature off on purpose (a quiet no-op, correct) or turned it ON and then
    failed to build a backend — e.g. SUPABASE_SERVICE_ROLE_KEY missing or
    wrong. The second case was ALSO silent: `persisted: true` on the blocking
    route and no error frame at all on the streaming one, while nothing
    reached Postgres. It must now fail exactly like any other storage failure
    above.
    """
    app.config["CHAT_PERSISTENCE_ENABLED"] = True
    app.config["chat_backend"] = lambda: None

    events = frames(ask(client))
    assert (
        "error",
        {
            "error": "This answer could not be saved to your history.",
            "code": "persistence_unavailable",
        },
    ) in events


def test_a_disabled_deployment_stays_a_quiet_noop(app, client):
    """The deployment-choice half of the same branch stays silent, as before
    this fix — a Supabase-less install or the flag simply not turned on yet is
    not a failure."""
    app.config["CHAT_PERSISTENCE_ENABLED"] = False
    app.config["chat_backend"] = lambda: None

    events = frames(ask(client))
    names = [event for event, _ in events]
    assert "final" in names and "done" in names
    assert "persistence_unavailable" not in [data.get("code") for _, data in events]


def test_the_blocking_route_reports_persisted_false_for_the_same_gap(app, client):
    app.config["CHAT_PERSISTENCE_ENABLED"] = True
    app.config["chat_backend"] = lambda: None

    response = client.post("/api/chat", json={"query": "first"}, headers=AUTH)
    assert response.get_json()["persisted"] is False


def test_the_answer_is_recorded_in_ram_even_when_storage_fails(app, client):
    class Broken:
        def load_session(self, *args, **kwargs):
            return []

        def append_turn(self, **kwargs):
            raise PersistenceUnavailable("down")

    app.config["chat_backend"] = lambda: Broken()
    response = ask(client, "first")

    window = app.config["conversations"].get(conversation_of(response), owner_id=OWNER)
    assert [message["content"] for message in window] == ["first", "".join(ANSWER_TOKENS)]


# ── The uuid boundary ───────────────────────────────────────────────────────


def test_conversation_ids_are_minted_in_the_canonical_dashed_form(client):
    """`uuid4().hex` is 32 characters with no dashes. A `uuid` column accepts it
    and returns the DASHED form, so the value that went in stops comparing equal
    to the one that comes back — two cache entries for one conversation, and a
    client-side comparison that never matches."""
    response = ask(client)
    conversation = conversation_of(response)

    assert "-" in conversation
    assert canonical_uuid(conversation) == conversation


def test_a_legacy_undashed_conversation_id_is_canonicalised_in_place(client, backend):
    """`_validate_chat_request` canonicalises the CLIENT-SUPPLIED id the same
    way the deleted cookie rule used to (docs/per-tab-conversation-deep-
    linking-plan.md §5.1) — a request naming a 32-char undashed id, which
    predates the dashed form shipping, must still land under the dashed id a
    `uuid` column round-trips to."""
    legacy = "b6b1a3f0c4d94e2a9f1b7c8d2e3f4a5b"

    response = ask(client, conversation_id=legacy)

    conversation = conversation_of(response)
    assert conversation == "b6b1a3f0-c4d9-4e2a-9f1b-7c8d2e3f4a5b"
    assert backend.load_session(OWNER, conversation)


def test_the_final_frame_carries_the_conversation_id(client):
    """It rides meta, final and done — never delta. A uuid per token adds ~29KB
    to an 800-token answer."""
    response = ask(client)
    events = frames(response)
    final = next(data for event, data in events if event == "final")
    meta = next(data for event, data in events if event == "meta")

    done = next(data for event, data in events if event == "done")

    assert final["conversation_id"] == meta["conversation_id"] == conversation_of(response)
    assert done["conversation_id"] == meta["conversation_id"]
    assert all("conversation_id" not in data for event, data in events if event == "delta")


# ── Bounds ──────────────────────────────────────────────────────────────────


def test_an_over_long_question_is_refused_before_it_reaches_storage(client, backend):
    """`_validate_chat_request` had no length bound, so a 200KB body was
    accepted, embedded, answered and — once questions became durable — kept."""
    response = client.post("/api/chat/stream", json={"query": "x" * 8_001}, headers=AUTH)

    assert response.status_code == 400
    assert backend.sessions_for(OWNER) == []


def test_hydration_is_bounded_through_the_request_path(app, client):
    """Unbounded restore meets citations.js's 100-answer tracking cap and drops
    the citation controls off the oldest answers without saying so.

    Asserted through the ROUTE, not by calling the backend with an explicit
    limit. The earlier version set `CHAT_HYDRATION_LIMIT` and then passed its own
    limit straight to `load_session`, so `_load_history` could have ignored the
    setting entirely and the test would still have been green.
    """
    app.config["CHAT_HYDRATION_LIMIT"] = 2

    conversation = "aaaaaaaa-2222-3333-4444-555555555555"
    for turn in range(3):
        ask(client, f"question {turn}", conversation_id=conversation)

    # Lose the cache, forcing the next request to hydrate from durable rows.
    app.config["conversations"].clear(conversation)
    ask(client, "question 3", conversation_id=conversation, allow_create=False)

    handed_to_the_model = app.config["openai_handler"].stream_response.call_args[0][3]
    assert [m["content"] for m in handed_to_the_model] == [
        "question 2",
        "".join(ANSWER_TOKENS),
    ], "the hydration limit did not bound what reached the prompt"


def test_a_window_that_starts_mid_exchange_is_repaired(app):
    """`_truncate` slices on a strict [user, assistant, …] alternation, so a row
    limit landing on an odd boundary must not hand it a leading answer."""
    from web.services.conversation_store import ConversationStore

    store = ConversationStore()
    kept = store.replace(
        "c1",
        [
            {"role": "assistant", "content": "orphaned answer"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ],
        max_pairs=10,
        max_chars=10_000,
    )

    assert [message["role"] for message in kept] == ["user", "assistant"]


# ── The double must not be laxer than the schema ────────────────────────────
#
# Every test above runs against `InMemoryChatBackend`. Anything the schema
# rejects but the double accepts is a constraint nobody is asserting — a review
# found three such, and these are what stop them coming back.


@pytest.mark.parametrize(
    "sources, why",
    [
        ([{"source_index": 150, "snippet": "x"}], "source_index outside 1..99"),
        ([{"source_index": 0, "snippet": "x"}], "source_index below 1"),
        ([{"source_index": 1, "snippet": "x" * 400}], "snippet over 321 chars"),
        (
            [{"source_index": 1, "snippet": "a"}, {"source_index": 1, "snippet": "b"}],
            "duplicate (message_id, source_index)",
        ),
        (["not an object"], "source is not an object"),
    ],
)
def test_the_double_rejects_what_the_schema_rejects(backend, sources, why):
    with pytest.raises(PersistenceUnavailable):
        backend.append_turn(
            owner_id=OWNER,
            session_id="s1",
            client_request_id="r1",
            question="q",
            answer="a",
            sources=sources,
            lang="en",
            category="all",
            model="m",
            corpus_revision=None,
            owner_key=None,
            session_key=None,
            archive_opted_out=True,
        )


def test_a_rejected_payload_leaves_no_half_written_session(backend):
    """The RPC gets this from its transaction; the double has to arrange it."""
    with pytest.raises(PersistenceUnavailable):
        backend.append_turn(
            owner_id=OWNER,
            session_id="s1",
            client_request_id="r1",
            question="q",
            answer="a",
            sources=[{"source_index": 150, "snippet": "x"}],
            lang="en",
            category="all",
            model="m",
            corpus_revision=None,
            owner_key=None,
            session_key=None,
            archive_opted_out=True,
        )

    assert backend.sessions_for(OWNER) == []
    assert backend.archive == []


def test_a_non_array_source_payload_becomes_an_empty_list(backend):
    """`coalesce` in SQL catches SQL NULL only. A JSON scalar `null` survives it
    and aborts `jsonb_array_elements`, rolling back a turn the reader is already
    reading — so the RPC checks `jsonb_typeof` and this mirrors that."""
    backend.append_turn(
        owner_id=OWNER,
        session_id="s1",
        client_request_id="r1",
        question="q",
        answer="a",
        sources=None,
        lang="en",
        category="all",
        model="m",
        corpus_revision=None,
        owner_key=None,
        session_key=None,
        archive_opted_out=True,
    )

    assert backend.load_session(OWNER, "s1")[1].sources == []


def test_the_real_citation_payload_satisfies_the_schema(client, backend):
    """The constraints above are only worth having if the live path clears them."""
    response = ask(client)
    _, assistant_row = backend.load_session(OWNER, conversation_of(response))

    for source in assistant_row.sources:
        assert 1 <= source["source_index"] <= 99
        assert len(source["snippet"]) <= 321
        assert source["document"] and source["category"]


# ── Concurrency ─────────────────────────────────────────────────────────────


def test_hydration_never_overwrites_a_window_that_already_has_turns(app):
    """Cold hydration is a check-then-act across two calls, and the lock inside
    each does not span the gap. Two tabs on one conversation both read an empty
    window, both fetch the same history, and the slower one used to arrive with
    a stale copy and erase a turn the reader had already been shown."""
    from web.services.conversation_store import ConversationStore

    store = ConversationStore()
    stale = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]

    store.replace("c1", stale, 10, 10_000, owner_id=OWNER)
    store.append_turn("c1", "q2", "a2", 10, 10_000, owner_id=OWNER)

    # The delayed second hydration lands here, carrying only what it read.
    kept = store.replace("c1", stale, 10, 10_000, owner_id=OWNER)

    assert [m["content"] for m in kept] == ["q1", "a1", "q2", "a2"]
    assert [m["content"] for m in store.get("c1", owner_id=OWNER)] == ["q1", "a1", "q2", "a2"]


# ── Ship state ──────────────────────────────────────────────────────────────


def test_persistence_ships_on():
    """`CHAT_PERSISTENCE_ENABLED` waited for the MIGRATION — applied
    2026-08-20 as `supabase/migrations/20260820131914_chat_session_
    persistence.sql` — and ships on by default now that it has landed.

    There is no second flag to check any more. `CHAT_RESUME_LATEST_SESSION`
    waited for the TRANSCRIPT (`GET /api/chat/history`) and was retired the
    moment the URL became the pointer (docs/per-tab-conversation-deep-
    linking-plan.md §5.5, Decision 1a): `/` is always a new conversation, with
    no cookie-held "most recent session" left to resume.

    Read off a non-testing app, because under TESTING the in-memory backend is
    selected unconditionally and would hide the production default.
    """
    from flask import Flask

    from web.api.app import _configure_app

    application = Flask(__name__)
    _configure_app(application, testing=False)

    assert application.config["CHAT_PERSISTENCE_ENABLED"] is True


# ── The transcript comes back (step 6) ──────────────────────────────────────
#
# Everything above proves rows are WRITTEN. This section is the other half: the
# reader gets them back, with the evidence under each answer still openable.
# Before `GET /api/chat/history` a restored answer kept its prose and lost its
# citations, on a product whose first principle is that an answer without a
# resolvable source is a liability.


def hydrate(client, conversation_id, headers=AUTH, **params):
    """`?c=<id>` names the conversation (Decision 4 of
    docs/per-tab-conversation-deep-linking-plan.md) — there is no cookie left
    to fall back to, so every caller must name one explicitly."""
    return client.get(
        "/api/chat/history", query_string={"c": conversation_id, **params}, headers=headers
    )


def test_the_transcript_comes_back_from_the_durable_rows(client):
    conversation_id = "aaaaaaaa-2222-3333-4444-555555555555"
    ask(client, "first", conversation_id=conversation_id)
    ask(client, "second", conversation_id=conversation_id, allow_create=False)

    body = hydrate(client, conversation_id).get_json()

    assert [message["role"] for message in body["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ], "the transcript did not come back oldest-first as an alternating exchange"
    assert body["messages"][0]["content"] == "first"
    assert body["messages"][2]["content"] == "second"
    assert body["conversation_id"] == conversation_id


def test_a_stored_source_index_reaches_the_browser_as_index(client):
    """The remap `_hydration_sources` exists for, and the one bug in this whole
    step that would render as silence rather than an error.

    The live wire ships `index`; the stored column is `source_index`; the client
    reads `s.index` in `bindCitations` and `_openPassage`. Ship the column name
    and every restored citation becomes a control that resolves to nothing.
    """
    response = ask(client)

    answer = hydrate(client, conversation_of(response)).get_json()["messages"][1]

    assert all("index" in source for source in answer["sources"])
    assert not any("source_index" in source for source in answer["sources"])
    assert answer["cited"] == [1, 3], "the restored markers are not the ones the model saw"


def test_only_the_cited_passages_reach_the_transcript(client, backend):
    """Stored for the archive, shown to the reader on the same terms as live.

    `_persistable_sources` deliberately stores every RETRIEVED passage, because
    what search offered and the model declined is unrecoverable after a rebuild.
    The transcript is not that record: an answer ships the evidence it used, so a
    restored answer must not grow sources it never displayed.
    """
    response = ask(client)
    conversation_id = conversation_of(response)

    answer = hydrate(client, conversation_id).get_json()["messages"][1]
    stored = backend.load_session(OWNER, conversation_id)[1].sources

    assert len(stored) == 4, "precondition: all four retrieved passages were stored"
    assert [source["index"] for source in answer["sources"]] == [1, 3]
    assert answer["retrieved"] == 4, "the passage count stopped counting what was retrieved"


def test_a_user_message_carries_no_evidence_fields(client):
    """A question has no sources. Emitting empty ones would invite the client to
    render a source control under the reader's own words."""
    response = ask(client)

    question = hydrate(client, conversation_of(response)).get_json()["messages"][0]

    assert "sources" not in question
    assert "evidence_state" not in question


# ── The evidence state ──────────────────────────────────────────────────────


def test_a_live_answer_is_verified_by_construction(app, client):
    """Asserted on the wire, never compared — including when nothing can be
    compared. `read_active_build_id` returns None for the legacy flat layout, and
    computing the state here would badge every FRESH answer as unverifiable on
    exactly the deployments least able to explain why."""
    app.config["CORPUS_REVISION"] = None

    final = dict(frames(ask(client)))["final"]

    assert final["evidence_state"] == "verified"


def test_a_stored_answer_from_the_active_build_is_verified(client):
    response = ask(client)
    assert (
        hydrate(client, conversation_of(response)).get_json()["messages"][1]["evidence_state"]
        == "verified"
    )


def test_a_rebuilt_corpus_marks_stored_evidence_stale(app, client):
    """The case no test environment produces by accident, and the one the whole
    three-state gate exists for."""
    response = ask(client)
    app.config["CORPUS_REVISION"] = "a-later-build"

    answer = hydrate(client, conversation_of(response)).get_json()["messages"][1]

    assert answer["evidence_state"] == "stale"
    assert answer["sources"], (
        "a rebuilt corpus emptied the evidence instead of dating it — the stored "
        "row IS what the model read, and withholding it hides the audit trail "
        "rather than protecting it"
    )


def test_an_unreadable_build_pointer_is_unverifiable_not_verified(app, client):
    """Fails closed. A null on either side is 'we cannot confirm', never 'fine'."""
    response = ask(client)
    app.config["CORPUS_REVISION"] = None

    assert (
        hydrate(client, conversation_of(response)).get_json()["messages"][1]["evidence_state"]
        == "unverifiable"
    )


# ── Who may hydrate ─────────────────────────────────────────────────────────


def test_a_second_reader_cannot_hydrate_the_first_readers_transcript(client):
    """The owner filter, asserted through the route rather than the backend.

    `test_a_second_reader_cannot_load_the_first_readers_session` proves the RPC
    filters. This proves the route did not hand B a way around it — a
    CLIENT-SUPPLIED id naming a conversation the requester does not own
    answers 404, not an empty transcript (§3.3 of
    docs/per-tab-conversation-deep-linking-plan.md): `chat_load_session`
    cannot otherwise tell "not yours" from "yours, but empty".
    """
    response = ask(client, "a question from the first reader", headers=AUTH)
    a_conversation = conversation_of(response)

    reply = hydrate(client, a_conversation, headers=AUTH_B)

    assert reply.status_code == 404
    assert reply.get_json()["code"] == "not_found"


def test_hydrating_without_signing_in_is_refused(client):
    assert hydrate(client, "aaaaaaaa-2222-3333-4444-555555555555", headers={}).status_code == 401


def test_a_storage_failure_is_not_reported_as_an_empty_history(app, client, backend):
    """An empty transcript is a CLAIM — that the reader has no history. Making it
    while the store is unreachable is the quiet untruth this product refuses
    everywhere else, so the route says 503 instead of shrugging."""
    response = ask(client)
    conversation_id = conversation_of(response)

    class Broken:
        def session_exists(self, owner_id, session_id):
            raise PersistenceUnavailable("down")

        def load_session(self, *args, **kwargs):
            raise PersistenceUnavailable("down")

        def append_turn(self, **kwargs):
            raise PersistenceUnavailable("down")

    app.config["chat_backend"] = lambda: Broken()

    reply = hydrate(client, conversation_id)

    assert reply.status_code == 503
    assert reply.get_json()["code"] == "history_unavailable"


# NO MORE "resume" TESTS HERE. `_resolve_conversation_id`'s resume branch,
# `latest_session` (all three implementations) and the `resumed` field on the
# wire are all deleted (docs/per-tab-conversation-deep-linking-plan.md §5.5,
# Decision 1a) — `/` is always a new conversation now, with no cookie-driven
# fallback for an outage to corrupt.


def test_persistence_enabled_with_no_backend_is_reported_not_shrugged_off(app, client):
    """The same gap `_persist_turn` was already fixed for, on the read side.

    `chat_persistence: true` with no backend is a misconfiguration — most often
    a missing service-role key. Answering "you have no history" hides it behind
    a plausible-looking empty screen, which is the silent-success failure this
    feature has now refused twice.
    """
    app.config["chat_backend"] = lambda: None
    app.config["CHAT_PERSISTENCE_ENABLED"] = True

    response = hydrate(client, "aaaaaaaa-2222-3333-4444-555555555555")

    assert response.status_code == 503
    assert response.get_json()["code"] == "history_unavailable"


def test_a_deployment_without_persistence_still_answers_an_empty_transcript(app, client):
    """The other half of the same distinction: switched off is not broken."""
    app.config["chat_backend"] = lambda: None
    app.config["CHAT_PERSISTENCE_ENABLED"] = False

    response = hydrate(client, "aaaaaaaa-2222-3333-4444-555555555555")

    assert response.status_code == 200
    assert response.get_json()["messages"] == []


def test_a_stored_turn_keeps_the_time_it_happened(client):
    """A hydrated transcript rebuilds turns that may be days old. Stamping them
    with the reload time would tell a reader every question in their history was
    asked just now, on a tool where when something was asked is part of the
    record."""
    response = ask(client)

    messages = hydrate(client, conversation_of(response)).get_json()["messages"]

    assert all(message.get("created_at") for message in messages), (
        "the transcript cannot show when a turn happened if the time never ships"
    )


def test_the_transcript_is_not_cacheable(client):
    """One reader's conversation must not sit in a shared machine's cache."""
    response = ask(client)

    reply = hydrate(client, conversation_of(response))

    assert "no-store" in reply.headers.get("Cache-Control", "")


# ── Bounds and disclosure ───────────────────────────────────────────────────


def test_the_hydration_limit_is_clamped_at_both_ends(client):
    conversation_id = "aaaaaaaa-2222-3333-4444-555555555555"
    for _ in range(3):
        ask(client, conversation_id=conversation_id)

    assert len(hydrate(client, conversation_id, limit=2).get_json()["messages"]) == 2
    assert len(hydrate(client, conversation_id, limit=9999).get_json()["messages"]) == 6, (
        "200 is the ceiling"
    )
    assert len(hydrate(client, conversation_id, limit=-5).get_json()["messages"]) == 0, (
        "a negative limit must clamp, not raise or invert"
    )


def test_a_window_never_starts_on_an_answer(client):
    """`chat_load_session` takes the newest N messages, so an ODD limit slices
    between a question and the answer to it.

    Handing that back would render an answer that appears to have been given to
    nothing, with evidence attached — on the surface a reader opens to audit
    what was asked. The half exchange is dropped rather than shown, which is the
    same repair `ConversationStore.replace` already makes for the prompt window,
    applied where a reader can see it.
    """
    conversation_id = "aaaaaaaa-2222-3333-4444-555555555555"
    for _ in range(3):
        ask(client, conversation_id=conversation_id)

    for limit in (1, 3, 5):
        messages = hydrate(client, conversation_id, limit=limit).get_json()["messages"]
        assert len(messages) % 2 == 0, f"limit={limit} returned a half exchange"
        if messages:
            assert messages[0]["role"] == "user", (
                f"limit={limit} started the transcript on an answer"
            )


# NO MORE "resumed" DISCLOSURE TESTS HERE — the field, and the fallback it
# described, are both deleted (§5.5, Decision 1a).

# ── The archive ─────────────────────────────────────────────────────────────


def test_the_archive_records_a_turn_under_pseudonymous_keys(client, backend, monkeypatch):
    monkeypatch.setenv("ARCHIVE_OWNER_SALT", "owner-salt")
    monkeypatch.setenv("ARCHIVE_SESSION_SALT", "session-salt")

    response = ask(client, "how long is the review?")

    assert len(backend.archive) == 1
    row = backend.archive[0]
    assert row["question"] == "how long is the review?"
    assert OWNER not in row["owner_key"]
    assert conversation_of(response) not in row["session_key"]
    assert len(row["sources"]) == 4


def test_a_missing_salt_skips_the_archive_and_keeps_the_readers_history(
    client, backend, monkeypatch
):
    """Fail closed on the archive, never on the reader.

    A null-salted digest would be a stable key derived from nothing —
    indistinguishable later from a real one. Losing the turn the reader is
    looking at, to protect a dataset row, would be the wrong trade.
    """
    monkeypatch.delenv("ARCHIVE_OWNER_SALT", raising=False)
    monkeypatch.delenv("ARCHIVE_SESSION_SALT", raising=False)

    response = ask(client, "first")

    assert backend.archive == []
    assert backend.load_session(OWNER, conversation_of(response))


def test_a_missing_salt_is_logged_once_per_process_not_every_turn(monkeypatch, caplog):
    """Regression for a gap an external review caught: the skip above used to
    be silent — no log line at all — contradicting the design record's "a
    missing salt fails the archive write closed and logs" (roadmap doc). Once
    per process, not once per turn: .env.example calls an unset salt a
    SUPPORTED, possibly permanent state, and an ERROR on every single chat
    turn forever would be noise, not signal.
    """
    from web.services import chat_store

    monkeypatch.delenv("ARCHIVE_OWNER_SALT", raising=False)
    monkeypatch.delenv("ARCHIVE_SESSION_SALT", raising=False)
    monkeypatch.setattr(chat_store, "_salt_missing_warned", False)

    with caplog.at_level("ERROR"):
        first = chat_store.archive_keys(OWNER, "conv-1")
        second = chat_store.archive_keys(OWNER, "conv-2")

    assert first == (None, None)
    assert second == (None, None)
    warnings = [r for r in caplog.records if "ARCHIVE_OWNER_SALT" in r.message]
    assert len(warnings) == 1


# ── The archive's disclosure gate ───────────────────────────────────────────
#
# Step 7 shipped a durable-history notice and CUT the archive's controls — the
# opt-out toggle, the withdrawal column, the purge RPC, the retention CLI, the
# export. That was sound only because the archive is dormant. Setting a salt
# ends the dormancy and, with it, the justification. These pin the one mechanism
# that stops the two from silently disagreeing.


@pytest.mark.parametrize(
    "owner_salt, session_salt",
    [
        ("owner-salt", "session-salt"),
        ("owner-salt", None),  # one salt alone still collects nothing, but the
        (None, "session-salt"),  # INTENT to enable is what this warns about
    ],
)
def test_enabling_the_archive_requires_its_disclosure(
    monkeypatch, caplog, owner_salt, session_salt
):
    """A salt set while `archive_disclosed` is false is a loud error.

    The reasoning this guards is a pairing, not a single fact: the notice says
    nothing about the archive BECAUSE the archive collects nothing, and the
    opt-out was never built BECAUSE there was nothing to opt out of. Setting a
    salt breaks the first half and leaves the second half standing — text starts
    being kept that the reader was not told about and cannot decline.

    Either salt alone trips it. Neither one alone actually enables collection
    (`archive_keys` requires both), but a half-configured archive is somebody
    part-way through enabling it, which is exactly when the warning is useful
    rather than after the fact.
    """
    from web.api import app as app_module

    monkeypatch.delenv("ARCHIVE_OWNER_SALT", raising=False)
    monkeypatch.delenv("ARCHIVE_SESSION_SALT", raising=False)
    if owner_salt:
        monkeypatch.setenv("ARCHIVE_OWNER_SALT", owner_salt)
    if session_salt:
        monkeypatch.setenv("ARCHIVE_SESSION_SALT", session_salt)

    app = create_app(testing=True)
    app.config["ARCHIVE_DISCLOSED"] = False

    with caplog.at_level("ERROR"):
        tripped = app_module._warn_if_archive_is_undisclosed(app)

    assert tripped is True
    assert any("archive_disclosed" in r.message for r in caplog.records), (
        "the guard must name the config flag an operator has to change"
    )


def test_a_dormant_archive_does_not_warn(monkeypatch, caplog):
    """The other half of the distinction: unset salts are the supported state.

    `.env.example` calls an unset salt a supported, possibly permanent
    configuration. Warning about it every boot would make the real warning
    invisible.
    """
    from web.api import app as app_module

    monkeypatch.delenv("ARCHIVE_OWNER_SALT", raising=False)
    monkeypatch.delenv("ARCHIVE_SESSION_SALT", raising=False)

    app = create_app(testing=True)
    app.config["ARCHIVE_DISCLOSED"] = False

    with caplog.at_level("ERROR"):
        assert app_module._warn_if_archive_is_undisclosed(app) is False

    assert not [r for r in caplog.records if "archive_disclosed" in r.message]


def test_a_disclosed_archive_does_not_warn(monkeypatch, caplog):
    """Once the notice covers the archive and its controls are back, the salts
    are free to be set — the guard exists to force that work, not to forbid the
    feature."""
    from web.api import app as app_module

    monkeypatch.setenv("ARCHIVE_OWNER_SALT", "owner-salt")
    monkeypatch.setenv("ARCHIVE_SESSION_SALT", "session-salt")

    app = create_app(testing=True)
    app.config["ARCHIVE_DISCLOSED"] = True

    with caplog.at_level("ERROR"):
        assert app_module._warn_if_archive_is_undisclosed(app) is False


def test_the_archive_ships_undisclosed_by_default():
    """`config.yaml` must not drift out of step with the shipped notice.

    The notice says nothing about the archive. If this flag were ever flipped
    true without that copy changing, the guard above would fall silent while the
    thing it guards became true — the failure mode of every flag that describes
    something other than itself.
    """
    app = create_app(testing=True)
    assert app.config["ARCHIVE_DISCLOSED"] is False


def test_the_disclosure_guard_actually_runs_at_startup(monkeypatch, caplog):
    """The tests above call the guard directly, which proves it is correct and
    proves nothing about whether anything calls it.

    A guard that is never reached is worse than no guard, because the reasoning
    it protects gets written down as though it is enforced. So this one goes
    through `create_app` and asserts on the log, touching the function's name
    nowhere.
    """
    monkeypatch.setenv("ARCHIVE_OWNER_SALT", "owner-salt")
    monkeypatch.setenv("ARCHIVE_SESSION_SALT", "session-salt")

    with caplog.at_level("ERROR"):
        create_app(testing=True)

    assert any("archive_disclosed" in r.message for r in caplog.records), (
        "create_app did not reach the archive disclosure guard"
    )
