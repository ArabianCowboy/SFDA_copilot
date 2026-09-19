"""The transcript-orphan detector.

`public.chat_sessions.owner_id` has no foreign key and none is queued — the
`ON DELETE RESTRICT` migration was removed on 2026-09-19 rather than kept
parked (`TODO.md`, "`chat_sessions.owner_id` still has no foreign key"). An
orphaned transcript is therefore prevented only in software, and — the reason
this script exists — would be **invisible** if that software ever failed:
unreachable through RLS, unreachable through every RPC, and queried by nothing.

These tests pin the three properties that make the detector trustworthy rather
than decorative:

* it finds an orphan at all, and exits non-zero so a timer can alert;
* it **never** issues a delete, asserted structurally rather than by reading
  the source — a fake client that records every call it receives and fails the
  test if a write verb appears;
* a failure to run is distinguishable from a clean run (exit 2, not 0), because
  a broken check that exits 0 is worse than no check.

The paging loop is covered too: a single-page fetch that stopped at
PostgREST's silent 1000-row default would report "clean" on a database whose
orphan sat at row 1001.
"""

from __future__ import annotations

import pytest

from scripts.check_transcript_orphans import _find_orphans, main

SESSION_COLUMNS = "id,owner_id,created_at"


class _Result:
    def __init__(self, data):
        self.data = data


class FakeDB:
    """A PostgREST double that records everything and refuses to be written to.

    `calls` is the tripwire: any verb other than `select`/`range`/`execute`
    reaching this object is a write the detector must never perform, and the
    attribute lookup raises rather than returning a no-op.
    """

    _WRITE_VERBS = frozenset({"delete", "insert", "update", "upsert", "rpc"})

    def __init__(self, rows: dict[str, list[dict]], page_size: int = 1000):
        self.rows = rows
        self.page_size = page_size
        self.calls: list[tuple[str, str]] = []

    def rpc(self, *args, **kwargs):  # pragma: no cover - the guard below fires first
        raise AssertionError("the detector called rpc(); it must only read")

    def table(self, name):
        db = self

        class _Table:
            def __getattr__(self, verb):
                if verb in FakeDB._WRITE_VERBS:
                    raise AssertionError(
                        f"the detector called {verb}() on {name}; it must never write"
                    )
                raise AttributeError(verb)

            def select(self, columns):
                db.calls.append((name, columns))
                self._columns = columns
                return self

            def range(self, start, end):
                self._start, self._end = start, end
                return self

            def execute(self):
                page = db.rows.get(name, [])[self._start : self._end + 1]
                return _Result(page)

        return _Table()


def _session(sid: str, owner: str) -> dict:
    return {"id": sid, "owner_id": owner, "created_at": "2026-09-19T00:00:00+00:00"}


def test_a_clean_database_reports_no_orphans_and_exits_zero(caplog):
    db = FakeDB({"chat_sessions": [_session("s1", "u1")], "profiles": [{"id": "u1"}]})

    assert _find_orphans(db) == []
    assert main([], db=db) == 0


def test_an_orphan_is_found_and_exits_non_zero(caplog):
    """The whole point. Fails against a detector that only counts rows."""
    db = FakeDB(
        {
            "chat_sessions": [_session("s1", "u1"), _session("s2", "ghost")],
            "profiles": [{"id": "u1"}],
        }
    )

    orphans = _find_orphans(db)
    assert [row["id"] for row in orphans] == ["s2"]
    assert main([], db=db) == 1


def test_the_hit_is_logged_with_ids_only_and_carries_the_do_not_delete_caveat(caplog):
    """The deletion ledger's rule — UUIDs, counts and timestamps leave the
    database, nothing else — and the one instruction an operator reading this
    at 3am must not miss."""
    db = FakeDB({"chat_sessions": [_session("s2", "ghost")], "profiles": [{"id": "u1"}]})

    with caplog.at_level("WARNING"):
        assert main([], db=db) == 1

    message = caplog.text
    assert "s2" in message and "ghost" in message
    assert "must never be auto-deleted" in message
    assert "incident, not cleanup" in message


def test_quiet_is_silent_on_a_clean_run_and_still_speaks_on_a_hit(caplog):
    """A daily timer that mails on every clean run gets filtered, and then the
    one that matters is filtered with it."""
    clean = FakeDB({"chat_sessions": [_session("s1", "u1")], "profiles": [{"id": "u1"}]})
    with caplog.at_level("INFO"):
        assert main(["--quiet"], db=clean) == 0
    assert caplog.text.strip() == ""

    caplog.clear()
    dirty = FakeDB({"chat_sessions": [_session("s2", "ghost")], "profiles": []})
    with caplog.at_level("INFO"):
        assert main(["--quiet"], db=dirty) == 1
    assert "ghost" in caplog.text


def test_it_pages_past_the_first_thousand_rows():
    """A fetch that stopped at PostgREST's silent default would report a clean
    database whose only orphan sits at row 1001. Fails against a `_find_orphans`
    that calls `.execute()` once."""
    sessions = [_session(f"s{i}", "u1") for i in range(1000)] + [_session("late", "ghost")]
    db = FakeDB({"chat_sessions": sessions, "profiles": [{"id": "u1"}]})

    assert [row["id"] for row in _find_orphans(db)] == ["late"]


def test_a_read_failure_exits_two_not_zero(caplog):
    """A broken check that exits 0 is worse than no check: the timer stays
    green and nobody looks again. Fails against a bare `except: return 0`."""

    class Exploding(FakeDB):
        def table(self, name):
            raise RuntimeError("PostgREST is down")

    assert main([], db=Exploding({})) == 2


def test_it_never_issues_a_write():
    """Structural, not a source grep: the double raises on any write verb, so a
    future edit that reaches for `.delete()` fails here rather than in
    production against rows nothing else can see."""
    db = FakeDB({"chat_sessions": [_session("s2", "ghost")], "profiles": []})

    main([], db=db)

    assert all(columns == SESSION_COLUMNS or columns == "id" for _, columns in db.calls)
    with pytest.raises(AssertionError, match="must never write"):
        db.table("chat_sessions").delete()
