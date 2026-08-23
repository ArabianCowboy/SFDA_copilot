"""What the record says, and what it refuses to say.

The console's claim is that administrative acts are accountable. That claim
fails in two directions and both are tested here: an action with no record
(silent power) and a record with no action (a log that lies about what happened).

Append-only is enforced in the database by REVOKE plus a trigger, which cannot
be exercised against the in-memory backend these tests use. It was verified
directly against the live project — UPDATE and DELETE both return 42501 — and
the enforcement lives in
`supabase/migrations/20260814032139_audit_log.sql`. What is testable here is
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
    """ "Somebody set the model" and "the model differs from the default" are
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
    response = client.put("/admin/api/settings", json={"max_tokens": 999_999}, headers=ADMIN)
    assert response.status_code == 422

    assert client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"] == []


def test_a_write_that_could_not_be_stored_is_not_recorded(client, app):
    """The pairing runs the other way too: no change, no record.

    In production these are one transaction, so neither can happen without the
    other. This asserts the application does not fake the record when the write
    never reached the store.
    """
    with app.app_context():
        service = SettingsService(lambda: None)  # no backend at all
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
    path even asks.

    Amended when `append_audit` was added, and amended deliberately rather than
    evaded. The original stated the rule by proxy — no method name containing
    "audit" other than `list_audit` — so the cheap way past it was to name the
    new method something else, which would have left this test passing and
    meaning nothing.

    Appending is not the danger. `append_audit` exists because an outbound email
    cannot share a transaction with its record, so the intent and the outcome are
    two inserts. **Changing** an entry is the danger, and that is what is
    asserted: an exact surface, plus a check that no audit method is named for
    mutation.
    """
    surface = {name for name in dir(AdminBackend) if not name.startswith("_")}
    assert {n for n in surface if "audit" in n} == {"list_audit", "append_audit"}

    forbidden = ("update", "edit", "delete", "remove", "amend", "rewrite", "purge", "set")
    assert not {n for n in surface if "audit" in n and any(verb in n for verb in forbidden)}

    backend = InMemoryAdminBackend()
    methods = {name for name in dir(backend) if "audit" in name and not name.startswith("_")}
    assert methods == {"list_audit", "append_audit"}


def test_an_appended_entry_is_never_revisited():
    """Carries the weight the assertion above used to.

    The intent row must survive the outcome row untouched — if the second write
    could amend the first, the whole reason for writing two would be gone.
    """
    backend = InMemoryAdminBackend()
    actor = AuditActor("test-admin-id", "admin@example.com")

    backend.append_audit(
        action="user.password_reset_requested",
        target_type="user",
        target_id="test-user-id",
        actor=actor,
        after={"status": "requested", "operation_id": "op-1"},
    )
    intent = backend.list_audit(limit=10, offset=0)[0]
    snapshot = dict(intent)

    backend.append_audit(
        action="user.password_reset_accepted",
        target_type="user",
        target_id="test-user-id",
        actor=actor,
        after={"status": "accepted", "operation_id": "op-1"},
    )

    rows = backend.list_audit(limit=10, offset=0)
    assert len(rows) == 2
    unchanged = next(r for r in rows if r["action"] == "user.password_reset_requested")
    assert unchanged == snapshot


# ── The diff helper ───────────────────────────────────────────────────────────


def test_changed_keys_reports_only_what_moved():
    before = {"model": "a", "temperature": 0.1}
    after = {"model": "b", "temperature": 0.1}

    assert changed_keys(before, after) == {"model": {"from": "a", "to": "b"}}


def test_changed_keys_reports_additions_and_removals():
    assert changed_keys({}, {"model": "b"}) == {"model": {"from": None, "to": "b"}}
    assert changed_keys({"model": "a"}, {}) == {"model": {"from": "a", "to": None}}


# ── Fixes from the second adversarial review ─────────────────────────────────


def test_a_non_object_settings_row_does_not_take_the_app_down(app):
    """Startup adopts stored overrides, so malformed data became a boot failure.

    The column is JSONB with no object-shape constraint, so a scalar or an array
    written directly to the row reached `.items()` and raised — during
    create_app, where nothing catches it.
    """
    from web.services.settings_service import SettingsService, deployed_defaults

    class Malformed:
        def get_settings(self):
            return ["not", "an", "object"]

    service = SettingsService(lambda: Malformed())
    assert service.snapshot() == deployed_defaults()


def test_a_rejected_identity_publication_does_not_authorize_its_own_request(monkeypatch, app):
    """The demotion arrived everywhere except the request that needed to see it.

    `put()` correctly refused to keep a stale admin result, but the resolver
    returned that rejected object anyway — so the request holding it acted on a
    role the cache had just thrown away.
    """
    from web.services import admin_store
    from web.services.identity_cache import IdentityFlags, IdentityFlagsCache

    cache = IdentityFlagsCache()

    class SlowStaleAdmin:
        def fetch_identity(self, user_id, email):
            # While "this" lookup was in flight, a newer one published a
            # demotion. Publication must reject us, and so must the answer.
            cache.put(IdentityFlags(user_id, email, "user", "free", False))
            return IdentityFlags(user_id, email, "admin", "internal", False)

    monkeypatch.setattr(admin_store, "get_admin_backend", lambda: SlowStaleAdmin())

    with app.app_context():
        flags = admin_store.resolve_identity_flags(cache, "u1", "u1@example.com")

    assert flags.is_admin is False, "a rejected publication must not authorize its own request"
    assert cache.get("u1").role == "user"


def test_an_identity_outage_is_a_503_not_a_refusal(monkeypatch, client):
    """ "Forbidden" tells an administrator they lost access they still have.

    The console re-reads identity on every request, so a profile-store outage
    makes a real admin unresolved. That has to read as an outage — and the
    ordering matters: an unresolved identity reports role='user', so testing
    is_admin first would misclassify every lookup failure as a denial.
    """
    from web.services.identity_cache import IdentityFlags

    # Patched on web.api.app, not web.api.admin: the gate imports it inside the
    # function to avoid a circular import, so the name is resolved from the
    # source module at call time and a patch on the importer would do nothing.
    monkeypatch.setattr(
        "web.api.app._authenticate_request",
        lambda: (IdentityFlags.unknown("test-admin-id", "admin@example.com"), None),
    )

    response = client.get("/admin/api/settings", headers=ADMIN)
    assert response.status_code == 503
    assert response.get_json() == {"error": "identity_unavailable"}
