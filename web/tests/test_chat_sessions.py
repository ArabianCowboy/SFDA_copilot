"""The conversation sidebar: listing, titling, renaming, deleting.

Step 8, revised for docs/per-tab-conversation-deep-linking-plan.md. Everything
here is a claim about behaviour that cannot be read off the code, and most of
it exists because an adversarial review found the failure first. The ones
worth naming up front:

* **A delete must not be undone by a write already in flight.**
  `chat_append_turn` opens with `insert … on conflict (id) do nothing`, so a
  turn that lands after its session was deleted RECREATES that session — the
  reader deletes a conversation and it comes back carrying the answer they
  discarded. There is no tombstone. The refusal is the fix, and it is tested
  from the server side rather than trusted to the client's own guard.

* **Deleting the conversation the URL names is the client's navigation to do,
  not the server's cookie to rotate.** There is no cookie any more (§5.1,
  §5.2): the response names the deleted id and nothing else, and the
  `ConversationStore` window for it is cleared here because that is RAM this
  process holds, not something RLS reaches.

* **A title is written by the turn, not after it.** A second call would race
  the session's own lifecycle in three separate ways, all of which end with a
  title on the wrong row or on no row at all.

* **An outage must not render as "you have no conversations."** That is a
  claim about the reader, and `/api/chat/history` already refuses to make its
  equivalent. The list route inherits the rule.

`InMemoryChatBackend` mirrors the RPCs rather than approximating them — the
title's `coalesce`, the rename's refusal to touch `updated_at`, the delete's
cascade — so a test that passes here is making a claim about the SQL and not
merely about the double.
"""

from __future__ import annotations

import threading

import pytest

from web.api.app import create_app
from web.services.chat_store import (
    InMemoryChatBackend,
    PersistenceUnavailable,
    clamp_title,
)
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
    """One turn. With no `conversation_id`, this is what a real "New chat"
    looks like now (Decision 2 of docs/per-tab-conversation-deep-linking-plan.md):
    a fresh, unrelated conversation — there is no cookie left to continue an
    old one implicitly, so continuing one is always an explicit
    `conversation_id=` passed by the caller.
    """
    body.setdefault("query", query)
    response = client.post("/api/chat/stream", json=body, headers=headers)
    response.get_data()
    return response


def conversation_of(response) -> str:
    """The id a streamed chat response's turn landed under, off its `meta`
    frame."""
    import json

    for block in response.get_data(as_text=True).split("\n\n"):
        if not block.strip():
            continue
        event, data = "message", None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:") :].strip())
        if event == "meta" and data is not None:
            return data["conversation_id"]
    raise AssertionError("no meta frame in the streamed response")


def listing(client, headers=AUTH, **params):
    return client.get("/api/chat/sessions", query_string=params, headers=headers)


# ── Titling: written by the turn that creates the session ────────────────────


def test_the_first_question_names_the_conversation(client, backend):
    ask(client, "How long does a variation review take?")
    page = backend.list_sessions(OWNER)

    assert [s.title for s in page.sessions] == ["How long does a variation review take?"]


def test_a_later_question_does_not_rename_the_conversation(client, backend):
    """`coalesce(title, …)` — set when null, never overwritten.

    This is the property that lets the caller send the current question on every
    turn without first asking whether the session already has a name. Asking
    would be a round trip whose answer the very next turn is racing.
    """
    response = ask(client, "First question, which becomes the title")
    conversation_id = conversation_of(response)
    ask(
        client,
        "Second question, which must not",
        conversation_id=conversation_id,
        allow_create=False,
    )

    assert backend.list_sessions(OWNER).sessions[0].title == (
        "First question, which becomes the title"
    )


def test_a_rename_survives_every_later_turn(client, backend):
    """The other half of the same rule, and the one a reader would notice.

    A double that overwrote the title on each append would let this suite prove
    that renaming works while production silently reverted the name on the
    reader's next question.
    """
    response = ask(client, "Original question")
    session_id = conversation_of(response)

    client.patch(
        f"/api/chat/sessions/{session_id}",
        json={"title": "Bioequivalence file"},
        headers=AUTH,
    )
    ask(client, "A follow-up", conversation_id=session_id, allow_create=False)

    assert backend.list_sessions(OWNER).sessions[0].title == "Bioequivalence file"


def test_a_long_question_is_cut_on_a_word_boundary_with_an_ellipsis(client, backend):
    """120 characters is the column's CHECK. Clamped in Flask, above the
    database, so an over-long title is a shorter title rather than a 500 raised
    inside a `security definer` function."""
    question = (
        "What are the complete stability testing requirements for immediate "
        "release solid oral dosage forms intended for registration in the Gulf "
        "Cooperation Council region under the current guideline?"
    )
    ask(client, question)

    title = backend.list_sessions(OWNER).sessions[0].title
    assert len(title) <= 120
    assert title.endswith("…")
    # Cut between words, never mid-word: "immediate-rele" reads as damage.
    assert not title[:-1].endswith(" ")
    assert question.startswith(title[:-1])


def test_a_whitespace_only_title_becomes_null_rather_than_an_empty_string():
    """The column rejects a zero-length title, and the sidebar already renders a
    fallback for null. Returning '' would turn a blank name into a 500."""
    assert clamp_title("   \n\t ") is None
    assert clamp_title(None) is None
    assert clamp_title("") is None


def test_whitespace_inside_a_title_is_collapsed():
    """A question pasted out of a PDF arrives full of newlines. Left alone they
    survive into the sidebar as a title with a hole in it, and they spend the
    120-character budget carrying nothing."""
    assert clamp_title("What   are\n\nthe  requirements?") == "What are the requirements?"


# ── Listing ──────────────────────────────────────────────────────────────────


def test_the_list_carries_title_time_and_length(client):
    ask(client, "A question")
    body = listing(client).get_json()

    assert len(body["sessions"]) == 1
    row = body["sessions"][0]
    assert row["title"] == "A question"
    assert row["message_count"] == 2  # one pair
    assert row["updated_at"]
    assert "active" not in body, (
        "the client knows its own current conversation from its own URL now "
        "(§5.3 of docs/per-tab-conversation-deep-linking-plan.md) — a "
        "cookie-derived answer here would be wrong for every tab but one"
    )


def test_a_reader_never_sees_another_readers_conversations(client, app):
    """The isolation contract, on the newest surface. `test_session_isolation.py`
    proves it for the transcript; a sidebar that leaked titles would leak the
    reader's own questions, which is the same disclosure in a shorter form."""
    ask(client, "Reader A's private question", headers=AUTH)

    other = app.test_client()
    ask(other, "Reader B's private question", headers=AUTH_B)

    a_titles = [s["title"] for s in listing(client, AUTH).get_json()["sessions"]]
    b_titles = [s["title"] for s in listing(other, AUTH_B).get_json()["sessions"]]

    assert a_titles == ["Reader A's private question"]
    assert b_titles == ["Reader B's private question"]


def test_the_newest_conversation_comes_first(client):
    ask(client, "Oldest")
    ask(client, "Middle")
    ask(client, "Newest")

    titles = [s["title"] for s in listing(client).get_json()["sessions"]]
    assert titles == ["Newest", "Middle", "Oldest"]


def test_a_full_page_offers_a_cursor_and_a_short_one_does_not(client):
    """ "Not full" is the only honest end-of-list signal a keyset pager has.

    A lookahead row would make the end exact, at the cost of one extra read on
    every page to save one empty read at the end.
    """
    for index in range(3):
        ask(client, f"Question {index}")

    full = listing(client, limit=2).get_json()
    assert len(full["sessions"]) == 2
    assert full["next_cursor"]["id"] == full["sessions"][-1]["id"]

    short = listing(client, limit=10).get_json()
    assert len(short["sessions"]) == 3
    assert short["next_cursor"] is None


def test_the_cursor_pages_without_repeating_or_skipping(client):
    for index in range(5):
        ask(client, f"Question {index}")

    first = listing(client, limit=2).get_json()
    second = listing(
        client,
        limit=2,
        cursor_updated_at=first["next_cursor"]["updated_at"],
        cursor_id=first["next_cursor"]["id"],
    ).get_json()

    ids = [s["id"] for s in first["sessions"] + second["sessions"]]
    assert len(ids) == 4
    assert len(set(ids)) == 4, "the cursor handed back a conversation twice"


def test_a_half_cursor_pages_from_the_top_rather_than_returning_nothing(client):
    """Row comparison against a null yields null, which filters out every row.

    A client bug that dropped one half of the cursor would otherwise render an
    empty sidebar and read as "you have no older conversations" — a wrong answer
    that looks like a right one. Paging from the top is visibly wrong instead.
    """
    ask(client, "A question")
    body = listing(client, cursor_updated_at="2026-01-01T00:00:00+00:00").get_json()
    assert len(body["sessions"]) == 1


def test_listing_does_not_start_a_conversation(client, backend):
    """A GET must not create a row. Under the deleted cookie rule this used to
    be phrased as "does not mint a cookie"; there is no session pointer left
    for a GET to mint at all, so the durable claim is the one still worth
    making."""
    listing(client)
    assert backend.list_sessions(OWNER).sessions == []


def test_an_outage_is_reported_rather_than_rendered_as_an_empty_list(client, backend, monkeypatch):
    """The claim "you have no saved conversations" is about the READER. Making
    it while the store is unreachable is the quiet untruth this product refuses
    everywhere else — `/api/chat/history` answers 503 for exactly this, and the
    index of the transcript inherits the rule."""

    def explode(*args, **kwargs):
        raise PersistenceUnavailable("down")

    monkeypatch.setattr(backend, "list_sessions", explode)
    response = listing(client)

    assert response.status_code == 503
    assert response.get_json()["code"] == "history_unavailable"


def test_the_list_is_never_cached(client):
    """These rows are the reader's own opening questions. On a shared machine a
    cached list is the previous reader's questions served to the next one."""
    ask(client, "A question")
    assert listing(client).headers["Cache-Control"] == "private, no-store"


# ── There is no /select route ────────────────────────────────────────────────
#
# docs/per-tab-conversation-deep-linking-plan.md §5.2: its entire job was
# moving a cookie that no longer exists. Selecting a conversation is
# navigating to its `/c/<id>` URL now, client-side, with no server round trip.
# Deleting it also closed a live CSRF hole incidentally — it parsed no body at
# all, so any cross-site auto-submitting form could repoint a victim's
# conversation. Pinned here so a future refactor cannot reintroduce an
# equivalent unprotected endpoint.


def test_there_is_no_route_that_repoints_a_conversation_by_cookie(client):
    response = ask(client, "First conversation")
    session_id = conversation_of(response)

    reply = client.post(f"/api/chat/sessions/{session_id}/select", headers=AUTH)

    assert reply.status_code in (404, 405)


# ── Renaming ─────────────────────────────────────────────────────────────────


def test_renaming_changes_the_title(client, backend):
    response = ask(client, "Original")
    session_id = conversation_of(response)

    reply = client.patch(
        f"/api/chat/sessions/{session_id}", json={"title": "Renamed"}, headers=AUTH
    )

    assert reply.status_code == 200
    assert reply.get_json()["title"] == "Renamed"
    assert backend.list_sessions(OWNER).sessions[0].title == "Renamed"


def test_renaming_does_not_move_a_conversation_to_the_top(client):
    """`updated_at` MEANS "last spoken in", and the base migration went out of
    its way to refuse a touch trigger so it could keep meaning that.

    A rename that bumped it would take a conversation from three months ago and
    drop it at the top of Today, displacing the reader's actual current work on
    an edit that changed no content.
    """
    response = ask(client, "Older conversation")
    older = conversation_of(response)
    ask(client, "Newer conversation")

    client.patch(f"/api/chat/sessions/{older}", json={"title": "Renamed"}, headers=AUTH)

    titles = [s["title"] for s in listing(client).get_json()["sessions"]]
    assert titles == ["Newer conversation", "Renamed"]


def test_the_server_echoes_the_clamped_title_not_the_submitted_one(client):
    """The client renders what comes back. Echoing the raw input would show an
    untruncated name until the next reload — a row quietly disagreeing with the
    database."""
    response = ask(client, "Original")
    session_id = conversation_of(response)

    reply = client.patch(
        f"/api/chat/sessions/{session_id}",
        json={"title": "  spaced   out  "},
        headers=AUTH,
    )

    assert reply.get_json()["title"] == "spaced out"


def test_clearing_a_title_is_allowed_and_stores_null(client, backend):
    """ "Untitled" is a state the sidebar already renders, so clearing the name is
    a meaningful action rather than an error."""
    response = ask(client, "Original")
    session_id = conversation_of(response)

    reply = client.patch(f"/api/chat/sessions/{session_id}", json={"title": "   "}, headers=AUTH)

    assert reply.status_code == 200
    assert reply.get_json()["title"] is None
    assert backend.list_sessions(OWNER).sessions[0].title is None


def test_a_rename_without_a_title_field_is_a_client_error(client):
    response = ask(client, "Original")
    session_id = conversation_of(response)

    reply = client.patch(f"/api/chat/sessions/{session_id}", json={}, headers=AUTH)

    assert reply.status_code == 400
    assert reply.get_json()["code"] == "invalid_request"


def test_a_reader_cannot_rename_another_readers_conversation(client, app, backend):
    other = app.test_client()
    response = ask(other, "Reader B's conversation", headers=AUTH_B)
    stranger = conversation_of(response)

    reply = client.patch(f"/api/chat/sessions/{stranger}", json={"title": "Mine now"}, headers=AUTH)

    assert reply.status_code == 404
    assert backend.list_sessions(OWNER_B).sessions[0].title == "Reader B's conversation"


# ── Deleting ─────────────────────────────────────────────────────────────────


def test_deleting_removes_the_conversation_and_its_messages(client, backend):
    response = ask(client, "Doomed")
    session_id = conversation_of(response)

    reply = client.delete(f"/api/chat/sessions/{session_id}", headers=AUTH)

    assert reply.status_code == 200
    assert backend.list_sessions(OWNER).sessions == []
    assert backend.load_session(OWNER, session_id) == []


def test_the_delete_response_names_only_the_deleted_id(client):
    """No `conversation_id` in the body any more (§5.1, §5.2 of
    docs/per-tab-conversation-deep-linking-plan.md) — there is no cookie left
    to rotate, and no replacement to mint. Moving off the deleted
    conversation's URL, if the client was on it, is the client's job (§4.4)."""
    response = ask(client, "Doomed")
    session_id = conversation_of(response)

    body = client.delete(f"/api/chat/sessions/{session_id}", headers=AUTH).get_json()

    assert body == {"ok": True, "id": session_id}


def test_deleting_the_active_conversation_clears_the_models_memory(client, app):
    """A blank screen over a server that still remembers is the failure this
    guards against. Deleting has to clear the prompt window too, or the next
    answer to this id is informed by a conversation the reader deleted."""
    response = ask(client, "A question about paracetamol")
    session_id = conversation_of(response)
    store = app.config["conversations"]
    assert store.get(session_id, owner_id=OWNER)

    client.delete(f"/api/chat/sessions/{session_id}", headers=AUTH)

    assert store.get(session_id, owner_id=OWNER) == []


def test_a_reader_cannot_delete_another_readers_conversation(client, app, backend):
    other = app.test_client()
    response = ask(other, "Reader B's conversation", headers=AUTH_B)
    stranger = conversation_of(response)

    reply = client.delete(f"/api/chat/sessions/{stranger}", headers=AUTH)

    assert reply.status_code == 404
    assert len(backend.list_sessions(OWNER_B).sessions) == 1


def test_a_question_reasked_after_a_delete_is_recorded_rather_than_replayed(client, backend):
    """The idempotency keys go with the cascade.

    Left behind, `chat_append_turn`'s replay probe would still find the deleted
    turn's `client_request_id`, report `replayed`, and write nothing — so a
    stale tab that never navigated off the deleted id, and resends the same
    request, would have its turn silently vanish.
    """
    request_id = "11111111-2222-4333-8444-555555555555"
    conversation_id = "aaaaaaaa-2222-3333-4444-555555555555"
    client.post(
        "/api/chat/stream",
        json={
            "query": "A question",
            "conversation_id": conversation_id,
            "client_request_id": request_id,
        },
        headers=AUTH,
    ).get_data()

    client.delete(f"/api/chat/sessions/{conversation_id}", headers=AUTH)
    client.post(
        "/api/chat/stream",
        json={
            "query": "A question",
            "conversation_id": conversation_id,
            "client_request_id": request_id,
        },
        headers=AUTH,
    ).get_data()

    rows = backend.load_session(OWNER, conversation_id)
    assert [row.role for row in rows] == ["user", "assistant"]


# ── The in-flight race ───────────────────────────────────────────────────────


def test_a_conversation_being_written_to_cannot_be_deleted(app):
    """THE RACE THIS FEATURE WOULD OTHERWISE SHIP.

    Both chat routes close over their conversation id and write the turn at
    `final`, near the end. Delete that conversation while its answer is still
    streaming and the late `chat_append_turn` meets `insert … on conflict (id)
    do nothing`, finds no row, and CREATES one — with the answer the reader
    believed they had discarded, on a regulatory product.

    The client refuses the control while a stream is live, and that is the
    affordance. This is the guarantee: a delete that arrives anyway — a second
    tab, a replayed request, a client that skipped the check — is refused.

    Driven through the real generator rather than by poking the registry, so
    what is being tested is the hold's actual lifetime and not a mock of it.
    """
    client = app.test_client()
    entered = threading.Event()
    release = threading.Event()

    def slow_stream(*args, **kwargs):
        entered.set()
        release.wait(5)
        return iter(ANSWER_TOKENS)

    app.config["openai_handler"].stream_response.side_effect = slow_stream

    session_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

    streamed: list = []

    def run_stream():
        response = client.post(
            "/api/chat/stream",
            json={"query": "A slow question", "conversation_id": session_id},
            headers=AUTH,
        )
        streamed.append(response.get_data())

    thread = threading.Thread(target=run_stream)
    thread.start()
    assert entered.wait(5), "the stream never started"

    try:
        # A second client, same signed-in reader, exactly as a second tab on
        # the same URL would be.
        racer = app.test_client()
        refused = racer.delete(f"/api/chat/sessions/{session_id}", headers=AUTH)
    finally:
        release.set()
        thread.join(10)

    assert refused.status_code == 409
    assert refused.get_json()["code"] == "generation_in_flight"


def test_the_refusal_lifts_once_the_answer_has_landed(client, backend):
    """The hold is released in the generator's `finally`, so it covers a client
    disconnect too — the ordinary way a stream ends early. Without that the
    conversation would stay undeletable for the life of the process."""
    response = ask(client, "A question")
    session_id = conversation_of(response)

    reply = client.delete(f"/api/chat/sessions/{session_id}", headers=AUTH)

    assert reply.status_code == 200
    assert backend.list_sessions(OWNER).sessions == []


def test_an_abandoned_stream_does_not_leave_a_conversation_undeletable(app):
    """A reader who cancels mid-answer must still be able to delete what they
    were in. `GeneratorExit` is the ordinary exit here, and a hold released only
    on the success path would strand the conversation forever.

    Both requests explicitly name the same id — there is no cookie left to
    continue it implicitly — so a hold leaked by the first (crashed) request
    would make the delete below hang behind it.
    """
    client = app.test_client()
    conversation_id = "aaaaaaaa-2222-3333-4444-555555555555"

    def explode(*args, **kwargs):
        raise RuntimeError("upstream died mid-answer")

    app.config["openai_handler"].stream_response.side_effect = explode
    client.post(
        "/api/chat/stream",
        json={"query": "A doomed question", "conversation_id": conversation_id},
        headers=AUTH,
    ).get_data()

    # Nothing was persisted — the write happens at `final` — so a fresh turn
    # under the same id is what gives the delete something to remove.
    app.config["openai_handler"].stream_response.side_effect = lambda *a, **k: iter(ANSWER_TOKENS)
    ask(client, "A question that lands", conversation_id=conversation_id)

    assert client.delete(f"/api/chat/sessions/{conversation_id}", headers=AUTH).status_code == 200


# ── Malformed input ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("session_id", ["not-a-uuid", "../../etc/passwd", "1", ""])
def test_a_session_id_that_is_not_a_uuid_is_refused_everywhere(client, session_id):
    """Canonicalised before anything else looks at it. A value that cannot name a
    session must never reach a durable write, and must not be distinguishable
    from an id that names somebody else's."""
    for response in (
        client.patch(f"/api/chat/sessions/{session_id}", json={"title": "x"}, headers=AUTH),
        client.delete(f"/api/chat/sessions/{session_id}", headers=AUTH),
    ):
        assert response.status_code in (404, 405), session_id


def test_every_session_route_requires_authentication(client):
    """`@auth_required` on all three, asserted rather than assumed: these routes
    read and destroy one reader's history."""
    response = ask(client, "A question")
    session_id = conversation_of(response)

    assert client.get("/api/chat/sessions").status_code == 401
    assert client.patch(f"/api/chat/sessions/{session_id}", json={"title": "x"}).status_code == 401
    assert client.delete(f"/api/chat/sessions/{session_id}").status_code == 401


def test_a_new_chat_still_leaves_the_conversation_behind_it_in_the_sidebar(client):
    """ "New chat" is a client-side navigation now (Decision 2 of
    docs/per-tab-conversation-deep-linking-plan.md) with no server round trip
    at all — asking a second, unrelated question is the whole of it, and the
    first conversation must still be exactly where it was."""
    ask(client, "The conversation being left")
    ask(client, "An unrelated second conversation")

    titles = [s["title"] for s in listing(client).get_json()["sessions"]]
    assert titles == ["An unrelated second conversation", "The conversation being left"]
