"""The console's deletion-ledger view and reconcile action (slice 2c).

The original plan promised two retry drivers: a systemd timer (built in
slice 2b) and an admin console reconcile action (never built — every route
here was a 404). Each test fails against the code as it stood, for the
reason its own comment gives: the routes did not exist, and the ledger was
reachable only through raw SQL.

Two contracts share this file. The first is the operator surface: the
ledger lists saga rows and nothing else, and the reconcile action drives
the SAME `reconcile_one` the timer runs (reached through the
`deletion_reconciler` config callable — a test fake under TESTING), then
audits. The second is the shape of that audit: the row carries no PII
beyond the actor's existing fields — the target is a uuid, and `after`
holds only the state found and the outcome word.
"""

from __future__ import annotations

import json

import pytest

from web.api.app import create_app

ADMIN = {"Authorization": "Bearer fake_admin_token"}
AUTH = {"Authorization": "Bearer fake_token"}

PENDING_ROW = {
    "user_id": "11111111-1111-4111-8111-111111111111",
    "state": "pending",
    "requested_at": "2026-09-18T00:00:00+00:00",
    "grace_until": "2026-10-18T00:00:00+00:00",
    "purge_after": "2026-10-18T00:00:00+00:00",
    "next_attempt_at": "2026-10-18T00:00:00+00:00",
    "attempt_count": 3,
    "lease_until": None,
    "transcripts_purged_at": None,
    "auth_delete_begun_at": None,
    "auth_deleted_at": None,
    "completed_at": None,
    "last_error_code": "auth_admin_unreachable",
}

# The ledger's whole vocabulary: UUIDs, states and timestamps only. Anything
# outside this set in a ledger response is a D3 violation — the point of the
# ledger's shape is that no email, IP or user agent can be recovered from it.
LEDGER_COLUMNS = {
    "user_id",
    "state",
    "requested_at",
    "grace_until",
    "purge_after",
    "next_attempt_at",
    "attempt_count",
    "lease_until",
    "transcripts_purged_at",
    "auth_delete_begun_at",
    "auth_deleted_at",
    "completed_at",
    "last_error_code",
}


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def backend(app):
    return app.config["_testing_admin_backend"]


@pytest.fixture
def seeded(backend):
    backend.seed_deletion_saga(dict(PENDING_ROW))
    backend.seed_deletion_saga(
        {**PENDING_ROW, "user_id": "22222222-2222-4222-8222-222222222222", "state": "failed"}
    )
    return backend


# ── The ledger view ─────────────────────────────────────────────────────────


def test_the_ledger_requires_a_bearer_token(client):
    """Against the pre-2c code this is a 404 with no JSON body at all."""
    response = client.get("/admin/api/deletions")
    assert response.status_code == 401
    assert response.get_json() == {"error": "bearer_required"}


def test_a_reader_is_refused_the_ledger(client):
    """The gate is the blueprint's before_request, not per-route memory —
    but a route added later inherits it only if it lives on the blueprint,
    so this pins the new endpoint explicitly. 404 before 2c."""
    response = client.get("/admin/api/deletions", headers=AUTH)
    assert response.status_code == 403
    assert response.get_json() == {"error": "forbidden"}


def test_the_ledger_lists_states_timestamps_and_attempts_only(client, seeded):
    """The D3 shape: UUIDs, states, timestamps, counters — and nothing that
    identifies the reader behind the uuid. Fails before 2c: 404, no rows."""
    body = client.get("/admin/api/deletions", headers=ADMIN).get_json()

    assert body["total"] == 2
    for row in body["deletions"]:
        assert set(row) <= LEDGER_COLUMNS, (
            f"ledger leaked a column: {sorted(set(row) - LEDGER_COLUMNS)}"
        )
    states = {row["state"] for row in body["deletions"]}
    assert states == {"pending", "failed"}
    pending = next(r for r in body["deletions"] if r["state"] == "pending")
    assert pending["attempt_count"] == 3
    assert pending["last_error_code"] == "auth_admin_unreachable"


def test_the_ledger_carries_no_email_ip_or_user_agent_even_when_seeded(client, backend):
    """The backend shapes rows on the way out: seeding a row that carries
    an email must not surface it. Fails before 2c (404), and fails against
    any backend that passes a `select("*")` through unshaped."""
    backend.seed_deletion_saga({**PENDING_ROW, "email": "target@example.com"})
    body = client.get("/admin/api/deletions", headers=ADMIN).get_json()

    dumped = json.dumps(body)
    assert "target@example.com" not in dumped
    assert all(set(row) <= LEDGER_COLUMNS for row in body["deletions"])


# ── The reconcile action ────────────────────────────────────────────────────


def test_reconcile_requires_a_bearer_token(client):
    """POST is not walked by the suite's url_map gate test (GET only), so
    both halves are pinned here. 404 before 2c."""
    response = client.post(f"/admin/api/deletions/{PENDING_ROW['user_id']}/reconcile")
    assert response.status_code == 401


def test_a_reader_is_refused_the_reconcile(client):
    """404 before 2c."""
    response = client.post(f"/admin/api/deletions/{PENDING_ROW['user_id']}/reconcile", headers=AUTH)
    assert response.status_code == 403


def test_reconcile_drives_the_saga_through_the_shared_driver(app, client, seeded):
    """The route calls the SAME driver the timer runs — reached through the
    config callable, which the test owns here — with the row's own uuid and
    state. Fails before 2c: 404, and no driver call exists to assert."""
    calls = []

    def fake_reconciler(user_id, from_state):
        calls.append((user_id, from_state))
        return "completed"

    app.config["_testing_deletion_reconciler"] = fake_reconciler

    response = client.post(
        f"/admin/api/deletions/{PENDING_ROW['user_id']}/reconcile", headers=ADMIN
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["outcome"] == "completed"
    assert body["ok"] is True
    assert calls == [(PENDING_ROW["user_id"], "pending")]


def test_reconcile_audits_without_pii(app, client, seeded, backend):
    """The audit is two rows — requested BEFORE the drive, outcome after —
    and neither carries PII beyond the actor's existing fields: the target
    is a uuid, `after` holds only the state found and the outcome word.
    Fails before 2c: 404, and no audit row exists. Reshaped by slice 2d:
    an exception used to return 502 with no audit row at all, though the
    purge may already have run."""
    app.config["_testing_deletion_reconciler"] = lambda user_id, from_state: "failed"

    response = client.post(
        f"/admin/api/deletions/{PENDING_ROW['user_id']}/reconcile", headers=ADMIN
    )
    assert response.status_code == 200
    assert response.get_json()["ok"] is False

    entries = backend.list_audit(limit=10, offset=0)
    assert len(entries) == 2
    # Newest first: the outcome, then the request that preceded the drive.
    outcome, requested = entries
    assert requested["action"] == "user.deletion_reconcile_requested"
    assert requested["target_type"] == "user"
    assert requested["target_id"] == PENDING_ROW["user_id"]
    assert requested["after"]["from_state"] == "pending"
    assert requested["after"]["status"] == "requested"
    assert outcome["action"] == "user.deletion_reconcile"
    assert outcome["target_type"] == "user"
    assert outcome["target_id"] == PENDING_ROW["user_id"]
    # The actor's own fields are the existing record, not a leak.
    assert outcome["actor_email"] == "admin@example.com"
    assert outcome["after"]["from_state"] == "pending"
    assert outcome["after"]["outcome"] == "failed"
    # One operation, two rows: the same id links them.
    assert outcome["after"]["operation_id"] == requested["after"]["operation_id"]
    for entry in entries:
        dumped = json.dumps(entry)
        assert "test@example.com" not in dumped
        assert "user_agent" not in (entry["after"] or {})
    assert (outcome["note"] or "") == ""


def test_reconcile_of_a_terminal_saga_is_a_409_that_drives_nothing(app, client, seeded, backend):
    """Completed and cancelled are terminal: driving either through the
    claim/purge RPCs would raise DL004 and record a failure the saga never
    suffered. Refused before the driver runs. Fails before 2c: 404."""
    backend.seed_deletion_saga(
        {**PENDING_ROW, "user_id": "33333333-3333-4333-8333-333333333333", "state": "completed"}
    )
    calls = []
    app.config["_testing_deletion_reconciler"] = lambda u, s: calls.append((u, s)) or "completed"

    response = client.post(
        "/admin/api/deletions/33333333-3333-4333-8333-333333333333/reconcile", headers=ADMIN
    )
    assert response.status_code == 409
    assert response.get_json() == {"error": "deletion_terminal", "state": "completed"}
    assert calls == []
    assert backend.list_audit(limit=10, offset=0) == []


def test_reconcile_of_an_unknown_saga_is_a_404(client, seeded):
    """Fails before 2c: 404 for the wrong reason (no route at all)."""
    response = client.post(
        "/admin/api/deletions/44444444-4444-4444-8444-444444444444/reconcile", headers=ADMIN
    )
    assert response.status_code == 404
    assert response.get_json() == {"error": "no_such_deletion"}


def test_reconcile_takes_no_body(client, seeded):
    """The account is in the path; a caller sending fields must be told no,
    not quietly succeed — the same position the reset-password route takes.
    Fails before 2c: 404."""
    response = client.post(
        f"/admin/api/deletions/{PENDING_ROW['user_id']}/reconcile",
        json={"user_id": "someone-else"},
        headers=ADMIN,
    )
    assert response.status_code == 422
    assert response.get_json()["error"] == "unknown_field"


def test_a_driver_crash_is_a_502_with_both_audit_rows(app, client, seeded, backend):
    """The driver raised outside its own contract — an unavailable
    dependency, not a crash report. The requested row is still written
    first (the purge may already have run), then the failure. Fails before
    2c: 404. Reshaped by slice 2d: the crash used to leave no audit row."""

    def broken(user_id, from_state):
        raise RuntimeError("the provider caught fire")

    app.config["_testing_deletion_reconciler"] = broken

    response = client.post(
        f"/admin/api/deletions/{PENDING_ROW['user_id']}/reconcile", headers=ADMIN
    )
    assert response.status_code == 502
    assert response.get_json() == {"error": "reconcile_failed"}

    entries = backend.list_audit(limit=10, offset=0)
    assert len(entries) == 2
    failed, requested = entries
    assert requested["action"] == "user.deletion_reconcile_requested"
    assert failed["action"] == "user.deletion_reconcile_failed"
    assert failed["after"]["from_state"] == "pending"
    assert failed["after"]["status"] == "failed"
    assert failed["after"]["operation_id"] == requested["after"]["operation_id"]
    # The exception class, never its message.
    assert failed["note"] == "RuntimeError"


def test_a_settled_saga_reports_honestly(app, client, seeded, backend):
    """The other driver won the race and this drive's outcome word is
    'settled' (DL004 on an outcome record): nothing left to drive, so ok is
    true and the audit still pairs requested with outcome. Fails pre-2d:
    only 'completed' counted as ok, and the driver never said 'settled'."""
    app.config["_testing_deletion_reconciler"] = lambda user_id, from_state: "settled"

    response = client.post(
        f"/admin/api/deletions/{PENDING_ROW['user_id']}/reconcile", headers=ADMIN
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["outcome"] == "settled"
    assert body["ok"] is True

    entries = backend.list_audit(limit=10, offset=0)
    assert len(entries) == 2
    assert entries[0]["after"]["outcome"] == "settled"


def test_the_reconcile_limit_is_reassigned_not_discarded(app):
    """The regression guard for the wrapper-discarding bug (see
    test_rate_limit_keys.py): `view_functions[name]` must BE the limiter's
    wrapper. Fails against a wiring that registers the limit and throws the
    wrapper away — which silently disables it."""
    fn = app.view_functions["admin.reconcile_deletion"]
    assert hasattr(fn, "__wrapper-limiter-instance"), (
        "admin.reconcile_deletion is not wrapped by the limiter — the assignment "
        "back into app.view_functions was probably dropped"
    )
