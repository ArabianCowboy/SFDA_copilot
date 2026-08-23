"""Data-rights export and bulk deletion: the persistence-layer generator and
RPC double (docs/profile-refactor-plan.md Step 7).

`export_all_sessions`/`_export_session_messages` (web/services/chat_store.py)
must not silently inherit either UI bound they walk past — `list_sessions`'
MAX_LIST_LIMIT (one sidebar page) or `load_session`'s MAX_LOAD_LIMIT (one
hydration window). Both are exercised here past their cap, in full, because a
truncated export is not an error a reader would ever see — it is a file that
looks complete and is not.
"""

from __future__ import annotations

from web.services.chat_store import (
    MAX_LIST_LIMIT,
    MAX_LOAD_LIMIT,
    InMemoryChatBackend,
    export_all_sessions,
)

OWNER = "export-owner"
OTHER = "someone-else"


def seed_turns(backend: InMemoryChatBackend, owner_id: str, session_id: str, count: int) -> None:
    """`count` question/answer pairs into one session, via the same
    `append_turn` entry point a real turn uses — not a private-attribute
    reach-in, so this seeds through the double's own guarantees (seq
    allocation in pairs, replay-key bookkeeping) rather than around them."""
    for i in range(count):
        backend.append_turn(
            owner_id=owner_id,
            session_id=session_id,
            client_request_id=f"{session_id}-{i}",
            question=f"Question {i}",
            answer=f"Answer {i}",
            sources=[],
            lang="en",
            category=None,
            model="gpt-4o-mini",
            corpus_revision=None,
            owner_key=None,
            session_key=None,
            archive_opted_out=True,
        )


def test_export_includes_every_message_beyond_the_hydration_window():
    """A session with more messages than MAX_LOAD_LIMIT must appear in full —
    that cap exists for a UI hydration read, not an export."""
    backend = InMemoryChatBackend()
    session_id = "sess-1"
    # append_turn writes 2 messages per call; this guarantees the session's
    # total exceeds one MAX_LOAD_LIMIT page.
    turns = MAX_LOAD_LIMIT // 2 + 5
    seed_turns(backend, OWNER, session_id, turns)

    [session] = list(export_all_sessions(backend, OWNER))

    assert session["session_id"] == session_id
    assert session["message_count"] == turns * 2
    assert len(session["messages"]) == turns * 2
    # Oldest first, one unbroken seq run — a pagination bug that lost or
    # duplicated a page shows up here as a gap or a repeat, not just a count.
    assert [m["seq"] for m in session["messages"]] == list(range(1, turns * 2 + 1))
    assert session["messages"][0]["content"] == "Question 0"
    assert session["messages"][-1]["content"] == f"Answer {turns - 1}"


def test_export_is_scoped_to_the_owner():
    backend = InMemoryChatBackend()
    seed_turns(backend, OWNER, "mine", 1)
    seed_turns(backend, OTHER, "theirs", 1)

    exported = list(export_all_sessions(backend, OWNER))

    assert [s["session_id"] for s in exported] == ["mine"]


def test_export_of_no_history_is_empty():
    backend = InMemoryChatBackend()
    assert list(export_all_sessions(backend, OWNER)) == []


def test_export_walks_more_sessions_than_one_sidebar_page():
    """Same silent-truncation hazard as the per-session window, for the
    session LIST itself — MAX_LIST_LIMIT is a sidebar page size, not an
    export cap."""
    backend = InMemoryChatBackend()
    total_sessions = MAX_LIST_LIMIT + 5
    for i in range(total_sessions):
        seed_turns(backend, OWNER, f"sess-{i}", 1)

    exported = list(export_all_sessions(backend, OWNER))

    assert len(exported) == total_sessions
    assert len({s["session_id"] for s in exported}) == total_sessions


def test_export_carries_sources_with_each_message():
    backend = InMemoryChatBackend()
    backend.append_turn(
        owner_id=OWNER,
        session_id="sourced",
        client_request_id="r1",
        question="What is required?",
        answer="See the regulation.",
        sources=[
            {
                "source_index": 1,
                "cited": True,
                "document": "Doc.pdf",
                "page": 3,
                "category": "regulatory",
                "score": 0.9,
            }
        ],
        lang="en",
        category="regulatory",
        model="gpt-4o-mini",
        corpus_revision=None,
        owner_key=None,
        session_key=None,
        archive_opted_out=True,
    )

    [session] = list(export_all_sessions(backend, OWNER))
    assistant_message = session["messages"][1]

    assert assistant_message["role"] == "assistant"
    assert assistant_message["sources"][0]["document"] == "Doc.pdf"


def test_delete_all_sessions_removes_every_owned_session_and_returns_their_ids():
    backend = InMemoryChatBackend()
    seed_turns(backend, OWNER, "mine-1", 1)
    seed_turns(backend, OWNER, "mine-2", 1)
    seed_turns(backend, OTHER, "theirs", 1)

    deleted = backend.delete_all_sessions(OWNER)

    assert sorted(deleted) == ["mine-1", "mine-2"]
    assert backend.list_sessions(OWNER).sessions == []
    # The other owner's history is untouched.
    assert len(backend.list_sessions(OTHER).sessions) == 1
    # And genuinely gone, not merely delisted — the same cascade
    # `delete_session` gives.
    assert backend.load_session(OWNER, "mine-1") == []


def test_delete_all_sessions_on_an_empty_history_is_a_quiet_no_op():
    backend = InMemoryChatBackend()
    assert backend.delete_all_sessions(OWNER) == []
