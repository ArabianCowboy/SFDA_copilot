"""The reconcile driver's ambiguous-outcome rule (slice 2b of
docs/ARCHITECTURE.md#account-deletion-and-trust; reasoning in docs/archive/2026-09-18_account-and-trust.md §5).

Every test fails against today's code — the driver module does not exist, so
the import itself raises ImportError. The provider boundary is the real
in-memory dispatcher double from `web.services.auth_admin` wherever its
shape fits; the two reconciliation cases use a small stub because the double
refuses `user_exists` too when configured to refuse, and reconciliation is
exactly about those two calls disagreeing.
"""

from __future__ import annotations

from scripts.reconcile_account_deletions import reconcile_one
from web.services.auth_admin import AuthAdminRefused, InMemoryAuthAdminDispatcher


class _FakeResult:
    def __init__(self, data):
        self.data = data


class FakeDB:
    """Saga RPCs by name. Handlers return row dicts, None (empty claim), or raise."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.rpc_handlers: dict = {}
        self.rows: list[dict] = []

    def rpc(self, name, params):
        db = self

        class _Call:
            def execute(self):
                db.calls.append((name, params))
                handler = db.rpc_handlers.get(name, lambda p: {"ok": True})
                return _FakeResult(handler(params))

        return _Call()

    def table(self, name):
        db = self

        class _Table:
            def select(self, *args):
                return self

            def neq(self, *args):
                return self

            def lte(self, *args):
                return self

            def execute(self):
                return _FakeResult(list(db.rows))

        return _Table()

    def outcomes(self, name):
        return [params for call, params in self.calls if call == name]


class _StubDispatcher:
    """A dispatcher whose delete and existence check disagree on purpose."""

    def __init__(self, *, exists: bool, refusal: AuthAdminRefused | None) -> None:
        self.exists_result = exists
        self.refusal = refusal
        self.deleted: list[str] = []

    def delete_user(self, user_id: str) -> None:
        self.deleted.append(user_id)
        if self.refusal is not None:
            raise self.refusal

    def user_exists(self, user_id: str) -> bool:
        return self.exists_result


def _healthy(db: FakeDB) -> FakeDB:
    """Claim, purge, begin, record and complete all answer normally."""
    db.rpc_handlers["account_deletion_claim"] = lambda p: {"user_id": p["p_owner_id"]}
    return db


def test_an_ambiguous_delete_for_a_gone_user_is_success_not_failure():
    """GoTrue no longer returns the user: the step SUCCEEDED whatever the
    transport said — recorded as `not_found` (which the saga treats as
    success) and completed, never failed."""
    db = _healthy(FakeDB())
    dispatcher = _StubDispatcher(
        exists=False,
        refusal=AuthAdminRefused("auth_admin_unreachable", "timeout", ambiguous=True),
    )
    assert reconcile_one(db, dispatcher, "u-1", "pending") == "completed"
    recorded = db.outcomes("account_deletion_record_auth_outcome")
    assert [call["p_outcome"] for call in recorded] == ["not_found"]
    assert ("account_deletion_complete", {"p_owner_id": "u-1"}) in db.calls


def test_an_ambiguous_delete_for_a_present_user_stays_ambiguous():
    """GoTrue still returns the user: nothing is recorded as failed, the
    state stands and the timer looks again."""
    db = _healthy(FakeDB())
    dispatcher = _StubDispatcher(
        exists=True,
        refusal=AuthAdminRefused("auth_admin_unreachable", "timeout", ambiguous=True),
    )
    assert reconcile_one(db, dispatcher, "u-1", "pending") == "ambiguous"
    recorded = db.outcomes("account_deletion_record_auth_outcome")
    assert [call["p_outcome"] for call in recorded] == ["ambiguous"]
    assert db.outcomes("account_deletion_complete") == []


def test_a_definitive_refusal_is_failed_not_ambiguous():
    """GoTrue understood the request and declined it — nothing happened, so
    the saga fails honestly with the provider's code."""
    db = _healthy(FakeDB())
    dispatcher = InMemoryAuthAdminDispatcher([{"id": "u-1", "email": "a@b.c"}])
    dispatcher.refuse_with = "auth_admin_failed"
    assert reconcile_one(db, dispatcher, "u-1", "pending") == "failed"
    recorded = db.outcomes("account_deletion_record_auth_outcome")
    assert recorded == [
        {"p_owner_id": "u-1", "p_outcome": "failed", "p_error_code": "auth_admin_failed"}
    ]


def test_a_held_lease_is_an_unclaimed_normal_outcome_not_an_error():
    """A claim returning no row means another driver holds it — the driver
    moves on without touching the purge, the provider, or the ledger."""
    db = FakeDB()
    db.rpc_handlers["account_deletion_claim"] = lambda p: None
    dispatcher = InMemoryAuthAdminDispatcher()
    assert reconcile_one(db, dispatcher, "u-1", "pending") == "unclaimed"
    assert db.calls == [
        (
            "account_deletion_claim",
            {"p_owner_id": "u-1", "p_from_state": "pending", "p_lease_seconds": 300},
        )
    ]
    assert dispatcher.deleted == []


def test_a_clean_run_deletes_genuinely_through_the_double():
    """A successful call must leave the demo state genuinely changed, per the
    double's own contract — and the saga completes only after recording."""
    db = _healthy(FakeDB())
    users = [{"id": "u-1", "email": "a@b.c"}]
    dispatcher = InMemoryAuthAdminDispatcher(users)
    assert reconcile_one(db, dispatcher, "u-1", "purging") == "completed"
    assert users == []
    recorded = db.outcomes("account_deletion_record_auth_outcome")
    assert [call["p_outcome"] for call in recorded] == ["deleted"]


def test_a_row_at_auth_delete_begun_is_driven_at_the_provider_not_re_purged():
    """The crash window this design exists to close: the driver died between
    `begin_auth_delete` committing and the provider call returning, so the row
    stands at `auth_delete_begun` with the outcome unrecorded.

    It must go straight to the GoTrue step. It must NOT fall into the purge
    loop: `account_deletion_purge_transcripts` and
    `account_deletion_begin_auth_delete` both require `state = 'purging'` with
    a live lease, so calling them here raises DL004 and records a failure the
    saga never suffered — inflating `attempt_count` on every 15-minute tick
    and, because `_due_rows` excludes only the two terminal states, doing it
    to every such row forever.

    Fails against the code before this branch existed: `auth_delete_begun` is
    not in `_CLAIMABLE`, so the claim was skipped and execution fell directly
    into the purge loop.
    """
    db = _healthy(FakeDB())
    dispatcher = _StubDispatcher(exists=False, refusal=None)

    outcome = reconcile_one(db, dispatcher, "user-adb", "auth_delete_begun")

    assert outcome == "completed"
    assert dispatcher.deleted == ["user-adb"]
    called = [name for name, _ in db.calls]
    assert "account_deletion_purge_transcripts" not in called
    assert "account_deletion_begin_auth_delete" not in called
    assert "account_deletion_claim" not in called
    assert db.outcomes("account_deletion_fail") == []
