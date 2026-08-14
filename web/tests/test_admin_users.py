"""Account management, and the two ways an operator can lock everyone out.

Both guards live in the database function, so they hold for anything that calls
it — a future script, a psql session, not just this API. They were verified
against the live project before the application layer existed; these tests pin
the same rules against the in-memory backend so the suite can run without one.
"""

from __future__ import annotations

import pytest

from web.api.app import create_app
from web.services.admin_store import AdminActionRefused, InMemoryAdminBackend
from web.services.audit import AuditActor


ADMIN = {"Authorization": "Bearer fake_admin_token"}
AUTH = {"Authorization": "Bearer fake_token"}
ACTOR = AuditActor("test-admin-id", "admin@example.com", "127.0.0.1", "pytest")


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def backend():
    return InMemoryAdminBackend()


# ── Listing ───────────────────────────────────────────────────────────────────


def test_accounts_are_listed_with_their_standing(client):
    body = client.get("/admin/api/users", headers=ADMIN).get_json()

    assert body["total"] == 3
    emails = {u["email"] for u in body["users"]}
    assert emails == {"admin@example.com", "test@example.com", "disabled@example.com"}


def test_the_list_says_which_account_is_yours(client):
    """So the console can grey out the controls the server would refuse, rather
    than letting an operator discover the rule by being told no."""
    assert client.get("/admin/api/users", headers=ADMIN).get_json()["self_id"] == "test-admin-id"


def test_the_list_can_be_searched(client):
    body = client.get("/admin/api/users?q=disabled", headers=ADMIN).get_json()
    assert [u["email"] for u in body["users"]] == ["disabled@example.com"]


def test_accounts_are_not_listed_to_a_reader(client):
    assert client.get("/admin/api/users", headers=AUTH).status_code == 403
    assert client.get("/admin/api/users").status_code == 401


# ── The lockout guards ────────────────────────────────────────────────────────


def test_an_administrator_cannot_demote_themselves(client):
    """The common accident: tidying up the account list and removing your own
    access on the way through."""
    response = client.patch(
        "/admin/api/users/test-admin-id", json={"role": "user"}, headers=ADMIN
    )
    assert response.status_code == 409
    assert response.get_json() == {"error": "cannot_change_own_access"}


def test_an_administrator_cannot_disable_themselves(client):
    response = client.patch(
        "/admin/api/users/test-admin-id", json={"is_disabled": True}, headers=ADMIN
    )
    assert response.status_code == 409


def test_the_last_administrator_cannot_be_removed(backend):
    """The one that looks reasonable at the time, because the account belongs to
    somebody who left. Enforced in the database, so it holds for any caller."""
    other = AuditActor("someone-else", "other@example.com")

    with pytest.raises(AdminActionRefused) as refused:
        backend.set_user_flags("test-admin-id", role="user", actor=other)
    assert refused.value.code == "would_leave_no_administrator"

    with pytest.raises(AdminActionRefused):
        backend.set_user_flags("test-admin-id", is_disabled=True, actor=other)


def test_an_administrator_can_be_removed_once_there_is_another(backend):
    """The guard is about the last one, not about administrators in general."""
    other = AuditActor("someone-else", "other@example.com")
    backend.set_user_flags("test-user-id", role="admin", actor=other)

    backend.set_user_flags("test-admin-id", role="user", actor=other)

    rows, _ = backend.list_users(limit=10, offset=0, search=None)
    assert {r["email"]: r["role"] for r in rows}["admin@example.com"] == "user"


# ── Changes ───────────────────────────────────────────────────────────────────


def test_a_reader_can_be_promoted_and_demoted(client):
    promoted = client.patch(
        "/admin/api/users/test-user-id", json={"role": "admin"}, headers=ADMIN
    ).get_json()
    assert promoted["user"]["role"] == "admin"

    demoted = client.patch(
        "/admin/api/users/test-user-id", json={"role": "user"}, headers=ADMIN
    ).get_json()
    assert demoted["user"]["role"] == "user"


def test_disabling_and_restoring_chat_access(client):
    off = client.patch(
        "/admin/api/users/test-user-id",
        json={"is_disabled": True, "reason": "spam"}, headers=ADMIN,
    ).get_json()
    assert off["user"]["is_disabled"] is True

    on = client.patch(
        "/admin/api/users/test-user-id", json={"is_disabled": False}, headers=ADMIN
    ).get_json()
    assert on["user"]["is_disabled"] is False


def test_every_change_is_recorded_with_its_reason(client):
    client.patch(
        "/admin/api/users/test-user-id",
        json={"is_disabled": True, "reason": "abusive questions"}, headers=ADMIN,
    )

    entry = client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"][0]
    assert entry["action"] == "user.disable"
    assert entry["target_id"] == "test-user-id"
    assert entry["actor_email"] == "admin@example.com"
    assert entry["note"] == "abusive questions"


def test_a_refused_change_is_not_recorded(client):
    """A log that records attempts as changes accuses someone of something that
    never happened."""
    client.patch("/admin/api/users/test-admin-id", json={"role": "user"}, headers=ADMIN)
    assert client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"] == []


def test_the_identity_cache_is_invalidated_so_the_change_takes_effect(client, app):
    """A demotion that waits out a 30-second TTL is a demotion an operator
    watches fail to happen."""
    from web.services.identity_cache import IdentityFlags

    cache = app.config["identity_flags"]
    cache.put(IdentityFlags("test-user-id", "test@example.com", "admin", "free", False))
    assert cache.get("test-user-id") is not None

    client.patch("/admin/api/users/test-user-id", json={"role": "user"}, headers=ADMIN)

    assert cache.get("test-user-id") is None


# ── Payload validation ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload,status",
    [
        ({}, 400),                       # nothing to change
        ({"role": "root"}, 422),         # not a role this app has
        ({"is_disabled": "yes"}, 400),   # not a boolean
        ("not a dict", 400),
    ],
)
def test_bad_payloads_are_refused(client, payload, status):
    response = client.patch("/admin/api/users/test-user-id", json=payload, headers=ADMIN)
    assert response.status_code == status


def test_a_change_by_a_reader_is_refused(client):
    response = client.patch(
        "/admin/api/users/test-user-id", json={"role": "admin"}, headers=AUTH
    )
    assert response.status_code == 403
