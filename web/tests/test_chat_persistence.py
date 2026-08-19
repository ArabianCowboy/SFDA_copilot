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
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        if data is not None:
            parsed.append((event, data))
    return parsed


def conversation_of(client) -> str:
    with client.session_transaction() as flask_session:
        return flask_session["conv_id"]


# ── The turn becomes durable ────────────────────────────────────────────────

def test_a_streamed_turn_is_stored_as_a_user_row_and_an_assistant_row(client, backend):
    ask(client, "How long is the review?")
    rows = backend.load_session(OWNER, conversation_of(client))

    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[0].content == "How long is the review?"
    assert rows[1].content.startswith("Applications")
    assert rows[1].seq == rows[0].seq + 1


def test_a_blocking_turn_is_stored_too(client, backend):
    response = client.post("/api/chat", json={"query": "first"}, headers=AUTH)
    assert response.get_json()["persisted"] is True

    rows = backend.load_session(OWNER, conversation_of(client))
    assert [row.role for row in rows] == ["user", "assistant"]


def test_answer_metadata_lives_on_the_assistant_row_only(client, backend):
    """Both readings pass the schema, so the choice is asserted rather than
    inferred — otherwise two exports of the same turn disagree."""
    ask(client, lang="ar", category="regulatory")
    user_row, assistant_row = backend.load_session(OWNER, conversation_of(client))

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
    assert ("error", {"error": "Search service is currently unavailable.",
                      "code": "search_unavailable"}) in frames(response)

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
    ask(client)
    _, assistant_row = backend.load_session(OWNER, conversation_of(client))

    assert [s["source_index"] for s in assistant_row.sources] == [1, 2, 3, 4]
    assert [s["cited"] for s in assistant_row.sources] == [True, False, True, False]


def test_stored_source_index_is_the_marker_the_model_saw(client, backend):
    """The citation contract, as a database row.

    `build_source_payload` emits `index`; the column is `source_index`. The
    remap happens once, at the persistence boundary, so a stored row and the
    marker in the answer text cannot drift apart.
    """
    response = ask(client)
    final = next(data for event, data in frames(response) if event == "final")
    _, assistant_row = backend.load_session(OWNER, conversation_of(client))

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

    ask(client)
    _, assistant_row = backend.load_session(OWNER, conversation_of(client))
    assert assistant_row.corpus_revision == "build-2026-08-18"


# ── Idempotency ─────────────────────────────────────────────────────────────

def test_a_replayed_request_id_writes_one_turn(client, backend):
    request_id = "11111111-2222-3333-4444-555555555555"
    ask(client, "same question", client_request_id=request_id)
    ask(client, "same question", client_request_id=request_id)

    rows = backend.load_session(OWNER, conversation_of(client))
    assert len(rows) == 2, "the retry wrote a second copy of the exchange"


def test_a_replay_does_not_advance_the_sequence(client, backend):
    """A gap in `seq` is indistinguishable from a deleted message to anything
    reading the transcript, so the counter must not move on a no-op."""
    request_id = "11111111-2222-3333-4444-555555555555"
    ask(client, "first", client_request_id=request_id)
    ask(client, "first", client_request_id=request_id)
    ask(client, "second", client_request_id="66666666-7777-8888-9999-000000000000")

    seqs = [row.seq for row in backend.load_session(OWNER, conversation_of(client))]
    assert seqs == [1, 2, 3, 4], f"sequence gapped: {seqs}"


def test_a_replay_does_not_write_a_second_archive_row(client, backend, monkeypatch):
    """Without `unique (owner_key, turn_key)` the replay skips the message rows —
    they conflict — and silently double-weights one exchange in the archive."""
    monkeypatch.setenv("ARCHIVE_OWNER_SALT", "owner-salt")
    monkeypatch.setenv("ARCHIVE_SESSION_SALT", "session-salt")

    request_id = "11111111-2222-3333-4444-555555555555"
    ask(client, "same question", client_request_id=request_id)
    ask(client, "same question", client_request_id=request_id)

    assert len(backend.archive) == 1


def test_a_replay_is_reported_as_a_replay(backend):
    """`replayed` must come back true, or `_persist_turn`'s replay branch is
    dead code that no test ever enters — which is what it was."""
    kwargs = dict(
        owner_id=OWNER, session_id="s1", client_request_id="r1", question="q",
        answer="a", sources=[], lang="en", category="all", model="m",
        corpus_revision=None, owner_key=None, session_key=None, archive_opted_out=True,
    )
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
    kwargs = dict(
        owner_id=OWNER, session_id="s1", client_request_id="r1", question="q",
        answer="a", lang="en", category="all", model="m", corpus_revision=None,
        owner_key=None, session_key=None, archive_opted_out=True,
    )
    backend.append_turn(sources=[{"source_index": 1, "snippet": "ok"}], **kwargs)

    replayed = backend.append_turn(sources=[{"source_index": 999}], **kwargs)

    assert replayed.replayed is True
    assert len(backend.load_session(OWNER, "s1")) == 2


def test_the_archive_dedupes_per_session_not_per_owner(backend):
    """Matching `unique (owner_key, session_key, turn_key)`. Keyed on the owner
    alone, one request id reused in two conversations wrote both turns to the
    reader's history and only the first to the archive."""
    kwargs = dict(
        owner_id=OWNER, client_request_id="r1", question="q", answer="a",
        sources=[], lang="en", category="all", model="m", corpus_revision=None,
        owner_key="owner-digest", archive_opted_out=False,
    )
    backend.append_turn(session_id="s1", session_key="session-1", **kwargs)
    backend.append_turn(session_id="s2", session_key="session-2", **kwargs)

    assert len(backend.archive) == 2

    # Same session and same turn key is still one row.
    backend.append_turn(session_id="s1", session_key="session-1", **kwargs)
    assert len(backend.archive) == 2


def test_a_missing_request_id_still_answers(client, backend):
    """An old client that has not learned to mint one keeps working; it simply
    gets no replay protection."""
    ask(client, "first")
    ask(client, "first")

    assert len(backend.load_session(OWNER, conversation_of(client))) == 4


# ── Ownership ───────────────────────────────────────────────────────────────

def test_appending_into_someone_elses_session_is_refused(backend):
    """The guard that makes a guessed session id useless."""
    backend.append_turn(
        owner_id=OWNER, session_id="s1", client_request_id="r1",
        question="q", answer="a", sources=[], lang="en", category="all",
        model="m", corpus_revision=None, owner_key=None, session_key=None,
        archive_opted_out=True,
    )

    with pytest.raises(PersistenceUnavailable):
        backend.append_turn(
            owner_id=OWNER_B, session_id="s1", client_request_id="r2",
            question="q", answer="a", sources=[], lang="en", category="all",
            model="m", corpus_revision=None, owner_key=None, session_key=None,
            archive_opted_out=True,
        )


def test_loading_an_unowned_session_is_indistinguishable_from_an_empty_one(backend):
    """Both answer `[]`, deliberately: probing for a stranger's session id must
    not be able to tell 'not yours' from 'not there'."""
    backend.append_turn(
        owner_id=OWNER, session_id="s1", client_request_id="r1",
        question="q", answer="a", sources=[], lang="en", category="all",
        model="m", corpus_revision=None, owner_key=None, session_key=None,
        archive_opted_out=True,
    )

    assert backend.load_session(OWNER_B, "s1") == []
    assert backend.load_session(OWNER_B, "no-such-session") == []


# ── The current-session rule ────────────────────────────────────────────────

def test_new_chat_is_not_resurrected_by_the_current_session_rule(client, backend):
    """The sharpest failure this rule can produce, pinned.

    After a reset the cookie holds a fresh id with no durable row, while the
    abandoned conversation is the owner's newest by `updated_at`. A rule keyed
    on 'the cookie's id has no rows' would resume it, and the reader would watch
    the conversation they just ended come back on the next page reload — which
    the language toggle performs.
    """
    ask(client, "first")
    ended = conversation_of(client)

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    ask(client, "second")

    assert conversation_of(client) != ended
    assert [row.content for row in backend.load_session(OWNER, conversation_of(client))][0] \
        == "second"


def test_a_reset_does_not_delete_the_conversation_behind_it(client, backend):
    """New chat ends this browser's claim on a conversation, not the
    conversation. Phase 2's sidebar depends on it still being there."""
    ask(client, "first")
    ended = conversation_of(client)

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    client.post("/api/conversation/reset", json={"forget": True}, headers=AUTH)

    assert backend.load_session(OWNER, ended), "forget deleted durable rows"


def test_an_undone_conversation_is_not_resurrected_either(client, backend):
    """Undo restores the cookie pointer, so the rule sees an id and stands
    aside. The path exists because `store.clear` drops RAM only, leaving the
    undone conversation newest by `updated_at`."""
    ask(client, "first")
    original = conversation_of(client)

    client.post("/api/conversation/reset", json={}, headers=AUTH)
    client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)

    assert conversation_of(client) == original


def test_hydration_restores_the_prompt_window_after_the_cache_is_lost(app, client):
    """A process restart, the store's TTL, or a new device all land here."""
    ask(client, "first")
    conversation = conversation_of(client)

    app.config["conversations"].clear(conversation)
    ask(client, "second")

    handed_to_the_model = app.config["openai_handler"].stream_response.call_args[0][3]
    assert [message["content"] for message in handed_to_the_model] == [
        "first", "".join(ANSWER_TOKENS),
    ]


# ── Failure is auxiliary ────────────────────────────────────────────────────

def test_a_storage_failure_still_ships_the_answer(app, client):
    """`handlers.js` already names history persistence as an auxiliary failure
    that must render the answer anyway. This is the server half of that."""
    class Broken:
        def latest_session(self, owner_id):
            raise PersistenceUnavailable("down")

        def load_session(self, *args, **kwargs):
            raise PersistenceUnavailable("down")

        def append_turn(self, **kwargs):
            raise PersistenceUnavailable("down")

    app.config["chat_backend"] = lambda: Broken()

    events = frames(ask(client))
    names = [event for event, _ in events]

    assert "final" in names and "done" in names
    assert ("error", {"error": "This answer could not be saved to your history.",
                      "code": "persistence_unavailable"}) in events
    # An `error` frame, not a bespoke event name: services.js dispatches with
    # `on[frame.event]?.()` and silently drops anything unregistered.
    assert "persistence_unavailable" not in names


def test_the_answer_is_recorded_in_ram_even_when_storage_fails(app, client):
    class Broken:
        def latest_session(self, owner_id):
            return None

        def load_session(self, *args, **kwargs):
            return []

        def append_turn(self, **kwargs):
            raise PersistenceUnavailable("down")

    app.config["chat_backend"] = lambda: Broken()
    ask(client, "first")

    window = app.config["conversations"].get(conversation_of(client), owner_id=OWNER)
    assert [message["content"] for message in window] == ["first", "".join(ANSWER_TOKENS)]


# ── The uuid boundary ───────────────────────────────────────────────────────

def test_conversation_ids_are_minted_in_the_canonical_dashed_form(client):
    """`uuid4().hex` is 32 characters with no dashes. A `uuid` column accepts it
    and returns the DASHED form, so the value that went in stops comparing equal
    to the one that comes back — two cache entries for one conversation, and a
    client-side comparison that never matches."""
    ask(client)
    conversation = conversation_of(client)

    assert "-" in conversation
    assert canonical_uuid(conversation) == conversation


def test_a_legacy_undashed_cookie_is_canonicalised_in_place(client, backend):
    """Cookies outlive the deploy that introduced this; store entries do not."""
    legacy = "b6b1a3f0c4d94e2a9f1b7c8d2e3f4a5b"
    with client.session_transaction() as flask_session:
        flask_session["conv_id"] = legacy

    ask(client)

    conversation = conversation_of(client)
    assert conversation == "b6b1a3f0-c4d9-4e2a-9f1b-7c8d2e3f4a5b"
    assert backend.load_session(OWNER, conversation)


def test_the_final_frame_carries_the_conversation_id(client):
    """It rides meta, final and done — never delta. A uuid per token adds ~29KB
    to an 800-token answer."""
    events = frames(ask(client))
    final = next(data for event, data in events if event == "final")
    meta = next(data for event, data in events if event == "meta")

    done = next(data for event, data in events if event == "done")

    assert final["conversation_id"] == meta["conversation_id"] == conversation_of(client)
    assert done["conversation_id"] == meta["conversation_id"]
    assert all("conversation_id" not in data for event, data in events if event == "delta")


# ── Bounds ──────────────────────────────────────────────────────────────────

def test_an_over_long_question_is_refused_before_it_reaches_storage(client, backend):
    """`_validate_chat_request` had no length bound, so a 200KB body was
    accepted, embedded, answered and — once questions became durable — kept."""
    response = client.post(
        "/api/chat/stream", json={"query": "x" * 8_001}, headers=AUTH
    )

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

    for turn in range(3):
        ask(client, f"question {turn}")
    conversation = conversation_of(client)

    # Lose the cache, forcing the next request to hydrate from durable rows.
    app.config["conversations"].clear(conversation)
    ask(client, "question 3")

    handed_to_the_model = app.config["openai_handler"].stream_response.call_args[0][3]
    assert [m["content"] for m in handed_to_the_model] == [
        "question 2", "".join(ANSWER_TOKENS),
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
            owner_id=OWNER, session_id="s1", client_request_id="r1",
            question="q", answer="a", sources=sources, lang="en", category="all",
            model="m", corpus_revision=None, owner_key=None, session_key=None,
            archive_opted_out=True,
        )


def test_a_rejected_payload_leaves_no_half_written_session(backend):
    """The RPC gets this from its transaction; the double has to arrange it."""
    with pytest.raises(PersistenceUnavailable):
        backend.append_turn(
            owner_id=OWNER, session_id="s1", client_request_id="r1",
            question="q", answer="a", sources=[{"source_index": 150, "snippet": "x"}],
            lang="en", category="all", model="m", corpus_revision=None,
            owner_key=None, session_key=None, archive_opted_out=True,
        )

    assert backend.sessions_for(OWNER) == []
    assert backend.archive == []


def test_a_non_array_source_payload_becomes_an_empty_list(backend):
    """`coalesce` in SQL catches SQL NULL only. A JSON scalar `null` survives it
    and aborts `jsonb_array_elements`, rolling back a turn the reader is already
    reading — so the RPC checks `jsonb_typeof` and this mirrors that."""
    backend.append_turn(
        owner_id=OWNER, session_id="s1", client_request_id="r1",
        question="q", answer="a", sources=None, lang="en", category="all",
        model="m", corpus_revision=None, owner_key=None, session_key=None,
        archive_opted_out=True,
    )

    assert backend.load_session(OWNER, "s1")[1].sources == []


def test_the_real_citation_payload_satisfies_the_schema(client, backend):
    """The constraints above are only worth having if the live path clears them."""
    ask(client)
    _, assistant_row = backend.load_session(OWNER, conversation_of(client))

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


# ── The archive ─────────────────────────────────────────────────────────────

def test_the_archive_records_a_turn_under_pseudonymous_keys(client, backend, monkeypatch):
    monkeypatch.setenv("ARCHIVE_OWNER_SALT", "owner-salt")
    monkeypatch.setenv("ARCHIVE_SESSION_SALT", "session-salt")

    ask(client, "how long is the review?")

    assert len(backend.archive) == 1
    row = backend.archive[0]
    assert row["question"] == "how long is the review?"
    assert OWNER not in row["owner_key"]
    assert conversation_of(client) not in row["session_key"]
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

    ask(client, "first")

    assert backend.archive == []
    assert backend.load_session(OWNER, conversation_of(client))
