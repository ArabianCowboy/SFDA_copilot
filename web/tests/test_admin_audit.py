"""What the record says, and what it refuses to say.

The console's claim is that administrative acts are accountable. That claim
fails in two directions and both are tested here: an action with no record
(silent power) and a record with no action (a log that lies about what happened).

Append-only is enforced in the database by REVOKE plus a trigger, which cannot
be exercised against the in-memory backend these tests use. It was verified
directly against the live project — UPDATE and DELETE both return 42501 — and
the enforcement lives in
`supabase/migrations/20260814032447_audit_log.sql`. What is testable here is
that the application never tries.
"""

from __future__ import annotations

import pytest

from web.api.app import create_app
from web.services.admin_store import AdminBackend, InMemoryAdminBackend
from web.services.audit import AuditActor, changed_keys
from web.services.settings_service import SettingsService


ADMIN = {"Authorization": "Bearer fake_admin_token"}
AUTH = {"Authorization": "Bearer fake_token"}
ACTOR = AuditActor("admin-id", "admin@example.com", "127.0.0.1", "pytest")


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


# ── An action leaves a record ─────────────────────────────────────────────────


def test_a_settings_change_is_recorded_with_who_and_what(client):
    client.put("/admin/api/settings", json={"model": "gpt-4o"}, headers=ADMIN)

    entries = client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]
    assert len(entries) == 1

    entry = entries[0]
    assert entry["action"] == "settings.update"
    assert entry["actor_email"] == "admin@example.com"
    assert entry["target_type"] == "settings"
    assert entry["before"] == {}
    assert entry["after"] == {"model": "gpt-4o"}
    assert entry["request_ip"]


def test_the_record_shows_the_overrides_not_the_effective_settings(client):
    """"Somebody set the model" and "the model differs from the default" are
    different facts, and only the first is an action anyone took."""
    client.put("/admin/api/settings", json={"temperature": 0.7}, headers=ADMIN)

    entry = client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"][0]
    # Only the changed key — not model, max_tokens and the rest, which nobody
    # touched and which would bury the one field that moved.
    assert entry["after"] == {"temperature": 0.7}


def test_entries_are_newest_first(client):
    client.put("/admin/api/settings", json={"model": "gpt-4o"}, headers=ADMIN)
    client.put("/admin/api/settings", json={"temperature": 0.4}, headers=ADMIN)

    entries = client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]
    assert [e["id"] for e in entries] == [2, 1]


# ── A refusal leaves none ─────────────────────────────────────────────────────


def test_a_rejected_change_is_not_recorded_as_one(client):
    """A log that records attempts as though they were changes is worse than no
    log: it accuses someone of doing something that never happened."""
    response = client.put(
        "/admin/api/settings", json={"max_tokens": 999_999}, headers=ADMIN
    )
    assert response.status_code == 422

    assert client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"] == []


def test_a_write_that_could_not_be_stored_is_not_recorded(client, app):
    """The pairing runs the other way too: no change, no record.

    In production these are one transaction, so neither can happen without the
    other. This asserts the application does not fake the record when the write
    never reached the store.
    """
    with app.app_context():
        service = SettingsService(lambda: None)   # no backend at all
        errors = service.update({"model": "gpt-4o"}, actor=ACTOR)

    assert [e.code for e in errors] == ["storage_unavailable"]
    assert client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"] == []


# ── Reading is not an action ──────────────────────────────────────────────────


def test_reading_the_log_does_not_add_to_it(client):
    """Auditing reads of a surface only administrators can reach produces noise
    that buries the signal. The line is state changes, plus access to a
    reader's own content."""
    client.put("/admin/api/settings", json={"model": "gpt-4o"}, headers=ADMIN)

    first = client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]
    client.get("/admin/api/audit", headers=ADMIN)
    second = client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]

    assert len(first) == len(second) == 1


# ── Access ────────────────────────────────────────────────────────────────────


def test_the_log_is_not_readable_by_a_reader(client):
    assert client.get("/admin/api/audit", headers=AUTH).status_code == 403


def test_the_log_requires_a_bearer_header(client):
    assert client.get("/admin/api/audit").status_code == 401


def test_pagination_is_bounded(client):
    """A window onto a larger table. An unbounded limit is a way to ask the
    database for everything at once."""
    body = client.get("/admin/api/audit?limit=100000", headers=ADMIN).get_json()
    assert body["limit"] <= 200

    assert client.get("/admin/api/audit?limit=nonsense", headers=ADMIN).status_code == 400


def test_a_negative_offset_does_not_reach_the_query(client):
    body = client.get("/admin/api/audit?offset=-5", headers=ADMIN).get_json()
    assert body["offset"] == 0


# ── The application never tries to rewrite history ───────────────────────────


def test_the_backend_offers_no_way_to_change_a_recorded_entry():
    """Append-only is enforced by database privileges; this pins that no code
    path even asks. A method to update an entry would be the first step toward
    something calling it."""
    surface = {name for name in dir(AdminBackend) if not name.startswith("_")}
    assert not {n for n in surface if "audit" in n and n != "list_audit"}

    backend = InMemoryAdminBackend()
    methods = {name for name in dir(backend) if "audit" in name and not name.startswith("_")}
    assert methods == {"list_audit"}


# ── The diff helper ───────────────────────────────────────────────────────────


def test_changed_keys_reports_only_what_moved():
    before = {"model": "a", "temperature": 0.1}
    after = {"model": "b", "temperature": 0.1}

    assert changed_keys(before, after) == {"model": {"from": "a", "to": "b"}}


def test_changed_keys_reports_additions_and_removals():
    assert changed_keys({}, {"model": "b"}) == {"model": {"from": None, "to": "b"}}
    assert changed_keys({"model": "a"}, {}) == {"model": {"from": "a", "to": None}}
