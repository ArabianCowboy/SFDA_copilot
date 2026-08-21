"""The conversation sidebar: listing, titling, switching, renaming, deleting.

Step 8. Everything here is a claim about behaviour that cannot be read off the
code, and most of it exists because an adversarial review found the failure
first. The ones worth naming up front:

* **A delete must not be undone by a write already in flight.**
  `chat_append_turn` opens with `insert … on conflict (id) do nothing`, so a
  turn that lands after its session was deleted RECREATES that session — the
  reader deletes a conversation and it comes back carrying the answer they
  discarded. There is no tombstone. The refusal is the fix, and it is tested
  from the server side rather than trusted to the client's own guard.

* **Deleting the conversation you are IN has three pointers to clean up**, not
  one: the cookie, the undo pointer, and the process-local prompt window. Any of
  them left behind resurrects the conversation on the reader's next question or
  their next Undo.

* **A title is written by the turn, not after it.** A second call would race the
  session's own lifecycle in three separate ways, all of which end with a title
  on the wrong row or on no row at all.

* **An outage must not render as "you have no conversations."** That is a claim
  about the reader, and `/api/chat/history` already refuses to make its
  equivalent. The list route inherits the rule.

`InMemoryChatBackend` mirrors the RPCs rather than approximating them — the
title's `coalesce`, the rename's refusal to touch `updated_at`, the delete's
cascade — so a test that passes here is making a claim about the SQL and not
merely about the double.
"""

from __future__ import annotations

import threading
import time

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


def ask(client, query="What are the requirements?", headers=AUTH):
    response = client.post("/api/chat/stream", json={"query": query}, headers=headers)
    response.get_data()
    return response


def conversation_of(client) -> str:
    with client.session_transaction() as flask_session:
        return flask_session.get("conv_id")


def listing(client, headers=AUTH, **params):
    return client.get("/api/chat/sessions", query_string=params, headers=headers)


def new_chat(client, headers=AUTH):
    return client.post("/api/conversation/reset", json={}, headers=headers)


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
    ask(client, "First question, which becomes the title")
    ask(client, "Second question, which must not")

    assert backend.list_sessions(OWNER).sessions[0].title == (
        "First question, which becomes the title"
    )


def test_a_rename_survives_every_later_turn(client, backend):
    """The other half of the same rule, and the one a reader would notice.

    A double that overwrote the title on each append would let this suite prove
    that renaming works while production silently reverted the name on the
    reader's next question.
    """
    ask(client, "Original question")
    session_id = conversation_of(client)

    client.patch(
        f"/api/chat/sessions/{session_id}", json={"title": "Bioequivalence file"},
        headers=AUTH,
    )
    ask(client, "A follow-up")

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
    assert row["message_count"] == 2      # one pair
    assert row["updated_at"]
    assert body["active"] == row["id"]


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
    new_chat(client)
    ask(client, "Middle")
    new_chat(client)
    ask(client, "Newest")

    titles = [s["title"] for s in listing(client).get_json()["sessions"]]
    assert titles == ["Newest", "Middle", "Oldest"]


def test_a_full_page_offers_a_cursor_and_a_short_one_does_not(client):
    """"Not full" is the only honest end-of-list signal a keyset pager has.

    A lookahead row would make the end exact, at the cost of one extra read on
    every page to save one empty read at the end.
    """
    for index in range(3):
        if index:
            new_chat(client)
        ask(client, f"Question {index}")

    full = listing(client, limit=2).get_json()
    assert len(full["sessions"]) == 2
    assert full["next_cursor"]["id"] == full["sessions"][-1]["id"]

    short = listing(client, limit=10).get_json()
    assert len(short["sessions"]) == 3
    assert short["next_cursor"] is None


def test_the_cursor_pages_without_repeating_or_skipping(client):
    for index in range(5):
        if index:
            new_chat(client)
        ask(client, f"Question {index}")

    first = listing(client, limit=2).get_json()
    second = listing(
        client, limit=2,
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


def test_listing_does_not_start_a_conversation(client):
    """A GET that resolved the current-session rule would mint a cookie, so
    merely opening the sidebar would change which conversation the reader's next
    question joins."""
    assert conversation_of(client) is None
    listing(client)
    assert conversation_of(client) is None


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


# ── Selecting ────────────────────────────────────────────────────────────────

def test_selecting_a_conversation_repoints_the_cookie(client):
    ask(client, "First conversation")
    first = conversation_of(client)
    new_chat(client)
    ask(client, "Second conversation")
    assert conversation_of(client) != first

    response = client.post(f"/api/chat/sessions/{first}/select", headers=AUTH)

    assert response.status_code == 200
    assert conversation_of(client) == first


def test_the_transcript_follows_the_selection(client):
    """The point of the whole feature, in one assertion — and the reason
    `/api/chat/history` still takes no session id. Selecting moves the cookie;
    the transcript route reads the cookie. One place decides."""
    ask(client, "First conversation")
    first = conversation_of(client)
    new_chat(client)
    ask(client, "Second conversation")

    client.post(f"/api/chat/sessions/{first}/select", headers=AUTH)
    messages = client.get("/api/chat/history", headers=AUTH).get_json()["messages"]

    assert messages[0]["content"] == "First conversation"


def test_a_reader_cannot_select_another_readers_conversation(client, app):
    """And the refusal cannot distinguish "not yours" from "not there", so a
    reader probing uuids learns nothing either way. A hostile id reaching the
    cookie would make the next question join a stranger's conversation."""
    other = app.test_client()
    ask(other, "Reader B's conversation", headers=AUTH_B)
    stranger = conversation_of(other)

    ask(client, "Reader A's conversation", headers=AUTH)
    mine = conversation_of(client)

    response = client.post(f"/api/chat/sessions/{stranger}/select", headers=AUTH)

    assert response.status_code == 404
    assert conversation_of(client) == mine, "a refused select still moved the cookie"


def test_selecting_drops_the_undo_a_new_chat_set_aside(client):
    """The undo belongs to the conversation a New chat ended, and the reader has
    just navigated somewhere else. Restoring it over their selection would put a
    conversation they did not ask for on top of one they did."""
    ask(client, "First conversation")
    first = conversation_of(client)
    new_chat(client)               # sets prev_conv_id
    ask(client, "Second conversation")
    second = conversation_of(client)
    new_chat(client)

    client.post(f"/api/chat/sessions/{second}/select", headers=AUTH)

    with client.session_transaction() as flask_session:
        assert "prev_conv_id" not in flask_session

    # And the undo now genuinely does nothing rather than restoring `first`.
    client.post("/api/conversation/reset", json={"undo": True}, headers=AUTH)
    assert conversation_of(client) == second


# ── Renaming ─────────────────────────────────────────────────────────────────

def test_renaming_changes_the_title(client, backend):
    ask(client, "Original")
    session_id = conversation_of(client)

    response = client.patch(
        f"/api/chat/sessions/{session_id}", json={"title": "Renamed"}, headers=AUTH
    )

    assert response.status_code == 200
    assert response.get_json()["title"] == "Renamed"
    assert backend.list_sessions(OWNER).sessions[0].title == "Renamed"


def test_renaming_does_not_move_a_conversation_to_the_top(client):
    """`updated_at` MEANS "last spoken in", and the base migration went out of
    its way to refuse a touch trigger so it could keep meaning that.

    A rename that bumped it would take a conversation from three months ago and
    drop it at the top of Today, displacing the reader's actual current work on
    an edit that changed no content.
    """
    ask(client, "Older conversation")
    older = conversation_of(client)
    new_chat(client)
    ask(client, "Newer conversation")

    client.patch(
        f"/api/chat/sessions/{older}", json={"title": "Renamed"}, headers=AUTH
    )

    titles = [s["title"] for s in listing(client).get_json()["sessions"]]
    assert titles == ["Newer conversation", "Renamed"]


def test_the_server_echoes_the_clamped_title_not_the_submitted_one(client):
    """The client renders what comes back. Echoing the raw input would show an
    untruncated name until the next reload — a row quietly disagreeing with the
    database."""
    ask(client, "Original")
    session_id = conversation_of(client)

    response = client.patch(
        f"/api/chat/sessions/{session_id}", json={"title": "  spaced   out  "},
        headers=AUTH,
    )

    assert response.get_json()["title"] == "spaced out"


def test_clearing_a_title_is_allowed_and_stores_null(client, backend):
    """"Untitled" is a state the sidebar already renders, so clearing the name is
    a meaningful action rather than an error."""
    ask(client, "Original")
    session_id = conversation_of(client)

    response = client.patch(
        f"/api/chat/sessions/{session_id}", json={"title": "   "}, headers=AUTH
    )

    assert response.status_code == 200
    assert response.get_json()["title"] is None
    assert backend.list_sessions(OWNER).sessions[0].title is None


def test_a_rename_without_a_title_field_is_a_client_error(client):
    ask(client, "Original")
    session_id = conversation_of(client)

    response = client.patch(f"/api/chat/sessions/{session_id}", json={}, headers=AUTH)

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_request"


def test_a_reader_cannot_rename_another_readers_conversation(client, app, backend):
    other = app.test_client()
    ask(other, "Reader B's conversation", headers=AUTH_B)
    stranger = conversation_of(other)

    response = client.patch(
        f"/api/chat/sessions/{stranger}", json={"title": "Mine now"}, headers=AUTH
    )

    assert response.status_code == 404
    assert backend.list_sessions(OWNER_B).sessions[0].title == "Reader B's conversation"


# ── Deleting ─────────────────────────────────────────────────────────────────

def test_deleting_removes_the_conversation_and_its_messages(client, backend):
    ask(client, "Doomed")
    session_id = conversation_of(client)

    response = client.delete(f"/api/chat/sessions/{session_id}", headers=AUTH)

    assert response.status_code == 200
    assert backend.list_sessions(OWNER).sessions == []
    assert backend.load_session(OWNER, session_id) == []


def test_deleting_the_active_conversation_rotates_the_cookie(client):
    """THE POINTER IS THE HALF THAT MATTERS.

    Left naming the deleted row, the reader's next question hits
    `chat_append_turn`'s `on conflict (id) do nothing`, which finds no row and
    creates one — the conversation they deleted comes back with a new answer in
    it.
    """
    ask(client, "Doomed")
    session_id = conversation_of(client)

    body = client.delete(f"/api/chat/sessions/{session_id}", headers=AUTH).get_json()

    assert body["conversation_id"]
    assert body["conversation_id"] != session_id
    assert conversation_of(client) == body["conversation_id"]


def test_the_replacement_conversation_is_minted_rather_than_resumed(client, backend):
    """Popping the cookie instead of replacing it would ARM the current-session
    rule, whose fallback resumes the reader's most recent conversation when the
    cookie names nothing. The next reload would then open some older
    conversation they never chose — the exact resurrection shape §5 exists to
    prevent, entered through the delete."""
    ask(client, "An older conversation")
    older = conversation_of(client)
    new_chat(client)
    ask(client, "The one being deleted")
    doomed = conversation_of(client)

    client.delete(f"/api/chat/sessions/{doomed}", headers=AUTH)

    assert conversation_of(client) not in (older, doomed)
    assert client.get("/api/chat/history", headers=AUTH).get_json()["messages"] == []


def test_deleting_the_active_conversation_clears_the_models_memory(client, app):
    """A blank screen over a server that still remembers is the failure the reset
    route's own comment refuses. Deleting has to clear the prompt window too, or
    the next answer is informed by a conversation the reader deleted."""
    ask(client, "A question about paracetamol")
    session_id = conversation_of(client)
    store = app.config["conversations"]
    assert store.get(session_id, owner_id=OWNER)

    client.delete(f"/api/chat/sessions/{session_id}", headers=AUTH)

    assert store.get(session_id, owner_id=OWNER) == []


def test_deleting_the_conversation_behind_an_undo_disarms_the_undo(client):
    """Otherwise Undo restores a transcript the database can no longer produce —
    turns on screen that no longer exist anywhere else."""
    ask(client, "Doomed conversation")
    doomed = conversation_of(client)
    new_chat(client)                      # doomed becomes prev_conv_id

    client.delete(f"/api/chat/sessions/{doomed}", headers=AUTH)

    with client.session_transaction() as flask_session:
        assert "prev_conv_id" not in flask_session


def test_deleting_a_conversation_you_are_not_in_leaves_the_cookie_alone(client):
    ask(client, "Doomed")
    doomed = conversation_of(client)
    new_chat(client)
    ask(client, "Current")
    current = conversation_of(client)

    body = client.delete(f"/api/chat/sessions/{doomed}", headers=AUTH).get_json()

    assert body["conversation_id"] is None
    assert conversation_of(client) == current


def test_a_reader_cannot_delete_another_readers_conversation(client, app, backend):
    other = app.test_client()
    ask(other, "Reader B's conversation", headers=AUTH_B)
    stranger = conversation_of(other)

    response = client.delete(f"/api/chat/sessions/{stranger}", headers=AUTH)

    assert response.status_code == 404
    assert len(backend.list_sessions(OWNER_B).sessions) == 1


def test_a_question_reasked_after_a_delete_is_recorded_rather_than_replayed(client, backend):
    """The idempotency keys go with the cascade.

    Left behind, `chat_append_turn`'s replay probe would still find the deleted
    turn's `client_request_id`, report `replayed`, and write nothing — so the
    reader re-asks and their turn silently vanishes.
    """
    request_id = "11111111-2222-4333-8444-555555555555"
    client.post(
        "/api/chat/stream",
        json={"query": "A question", "client_request_id": request_id},
        headers=AUTH,
    ).get_data()
    session_id = conversation_of(client)

    client.delete(f"/api/chat/sessions/{session_id}", headers=AUTH)
    client.post(
        "/api/chat/stream",
        json={"query": "A question", "client_request_id": request_id},
        headers=AUTH,
    ).get_data()

    rows = backend.load_session(OWNER, conversation_of(client))
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

    # The cookie has to exist before the racing request can name the id.
    with client.session_transaction() as flask_session:
        flask_session["conv_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    session_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

    streamed: list = []

    def run_stream():
        response = client.post(
            "/api/chat/stream", json={"query": "A slow question"}, headers=AUTH
        )
        streamed.append(response.get_data())

    thread = threading.Thread(target=run_stream)
    thread.start()
    assert entered.wait(5), "the stream never started"

    try:
        # A second client, same signed session, exactly as a second tab would be.
        racer = app.test_client()
        with racer.session_transaction() as flask_session:
            flask_session["conv_id"] = session_id
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
    ask(client, "A question")
    session_id = conversation_of(client)

    response = client.delete(f"/api/chat/sessions/{session_id}", headers=AUTH)

    assert response.status_code == 200
    assert backend.list_sessions(OWNER).sessions == []


def test_an_abandoned_stream_does_not_leave_a_conversation_undeletable(app):
    """A reader who cancels mid-answer must still be able to delete what they
    were in. `GeneratorExit` is the ordinary exit here, and a hold released only
    on the success path would strand the conversation forever."""
    client = app.test_client()

    def explode(*args, **kwargs):
        raise RuntimeError("upstream died mid-answer")

    app.config["openai_handler"].stream_response.side_effect = explode
    client.post("/api/chat/stream", json={"query": "A doomed question"}, headers=AUTH).get_data()

    # Nothing was persisted — the write happens at `final` — so a fresh turn
    # under the same id is what gives the delete something to remove.
    app.config["openai_handler"].stream_response.side_effect = (
        lambda *a, **k: iter(ANSWER_TOKENS)
    )
    ask(client, "A question that lands")

    assert client.delete(
        f"/api/chat/sessions/{conversation_of(client)}", headers=AUTH
    ).status_code == 200


# ── Malformed input ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("session_id", ["not-a-uuid", "../../etc/passwd", "1", ""])
def test_a_session_id_that_is_not_a_uuid_is_refused_everywhere(client, session_id):
    """Canonicalised before anything else looks at it. A value that cannot name a
    session must never reach the cookie, and must not be distinguishable from an
    id that names somebody else's."""
    ask(client, "A question")
    current = conversation_of(client)

    for response in (
        client.post(f"/api/chat/sessions/{session_id}/select", headers=AUTH),
        client.patch(f"/api/chat/sessions/{session_id}", json={"title": "x"}, headers=AUTH),
        client.delete(f"/api/chat/sessions/{session_id}", headers=AUTH),
    ):
        assert response.status_code in (404, 405), session_id

    assert conversation_of(client) == current


def test_every_session_route_requires_authentication(client):
    """`@auth_required` on all four, asserted rather than assumed: these routes
    read and destroy one reader's history."""
    ask(client, "A question")
    session_id = conversation_of(client)

    assert client.get("/api/chat/sessions").status_code == 401
    assert client.post(f"/api/chat/sessions/{session_id}/select").status_code == 401
    assert client.patch(f"/api/chat/sessions/{session_id}", json={"title": "x"}).status_code == 401
    assert client.delete(f"/api/chat/sessions/{session_id}").status_code == 401


def test_a_new_chat_still_leaves_the_conversation_behind_it_in_the_sidebar(client):
    """The property `test_a_reset_does_not_delete_the_conversation_behind_it`
    already pins for the rows, now asserted where a reader can actually see it —
    which is what makes the notice's "starting a new chat does not delete them"
    a checkable claim rather than a promise."""
    ask(client, "The conversation being left")
    new_chat(client)

    titles = [s["title"] for s in listing(client).get_json()["sessions"]]
    assert titles == ["The conversation being left"]
