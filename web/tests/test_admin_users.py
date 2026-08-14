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

    assert body["total"] == 4
    emails = {u["email"] for u in body["users"]}
    assert emails == {
        "admin@example.com", "test@example.com", "disabled@example.com",
        # An account with no profile row. It appears in the list looking
        # perfectly ordinary, which is the defect the detail view exists to
        # surface — `admin_list_users` coalesces the missing columns to healthy
        # defaults and cannot tell you otherwise.
        "orphan@example.com",
    }


def test_the_list_cannot_tell_a_broken_account_from_a_healthy_one(client):
    """Pins the limitation rather than the fix.

    `admin_list_users` coalesces role/tier/is_disabled, so a profile-less
    account is indistinguishable here. Asserted so that if someone later makes
    the list honest, this test fails and points at the detail view that was
    built to compensate.
    """
    body = client.get("/admin/api/users", headers=ADMIN).get_json()
    orphan = next(u for u in body["users"] if u["email"] == "orphan@example.com")

    assert orphan["role"] == "user"
    assert orphan["is_disabled"] is False
    assert "has_profile" not in orphan


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
    """Sent with a reason, because the route validates the payload before the
    database applies the rule — and a console always sends one."""
    response = client.patch(
        "/admin/api/users/test-admin-id",
        json={"is_disabled": True, "reason": "tidying up"}, headers=ADMIN,
    )
    assert response.status_code == 409
    assert response.get_json() == {"error": "cannot_change_own_access"}


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


def test_a_disable_without_a_reason_is_refused(client):
    """Asking for a reason is not enforcing one. An empty prompt normalised to
    NULL, so the accountability it exists for was optional in practice."""
    for payload in ({"is_disabled": True}, {"is_disabled": True, "reason": "   "}):
        response = client.patch(
            "/admin/api/users/test-user-id", json=payload, headers=ADMIN
        )
        assert response.status_code == 422
        assert response.get_json() == {"error": "reason_required"}


def test_restoring_access_needs_no_justification(client):
    """The burden belongs on the restrictive act, not on undoing it."""
    client.patch(
        "/admin/api/users/test-user-id",
        json={"is_disabled": True, "reason": "spam"}, headers=ADMIN,
    )
    response = client.patch(
        "/admin/api/users/test-user-id", json={"is_disabled": False}, headers=ADMIN
    )
    assert response.status_code == 200


def test_a_non_string_reason_is_a_400_rather_than_a_crash(client):
    """`.strip()` on a number raised, and the client saw a 500."""
    response = client.patch(
        "/admin/api/users/test-user-id",
        json={"is_disabled": True, "reason": 12}, headers=ADMIN,
    )
    assert response.status_code == 400


def test_an_actor_who_lost_access_mid_request_cannot_act(backend):
    """The other half of the write-skew fix.

    Two administrators removing each other simultaneously both passed the route
    gate before either removal committed. The database revalidates the actor
    inside the serialized transaction, so the second one is refused — verified
    against the live project, where exactly this ordering now leaves one
    enabled administrator instead of none.
    """
    other = AuditActor("test-user-id", "test@example.com")   # a reader, not an admin

    with pytest.raises(AdminActionRefused) as refused:
        backend.set_user_flags("test-disabled-id", role="admin", actor=other)
    assert refused.value.code == "actor_no_longer_administrator"


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


# ── Account detail ────────────────────────────────────────────────────────────


def test_an_account_detail_shows_identity_standing_and_profile(client):
    body = client.get("/admin/api/users/test-user-id", headers=ADMIN).get_json()
    account = body["user"]

    assert account["email"] == "test@example.com"
    assert account["role"] == "user"
    assert account["is_disabled"] is False
    assert account["has_profile"] is True
    # Facts an operator needs before deciding anything, none of which the People
    # table shows.
    for field in ("created_at", "last_sign_in_at", "email_confirmed_at", "updated_at"):
        assert field in account
    assert body["self_id"] == "test-admin-id"


def test_a_profile_less_account_is_shown_as_broken_rather_than_ordinary(client):
    """The whole reason the detail view reads from a left join without coalescing.

    In the People list this account looks like any other reader. Here it has to
    say what is actually true, or an operator will spend their time wondering
    why a perfectly normal-looking account behaves strangely.
    """
    account = client.get("/admin/api/users/test-orphan-id", headers=ADMIN).get_json()["user"]

    assert account["has_profile"] is False
    assert account["email"] == "orphan@example.com"
    # Null, not a manufactured default.
    assert account["role"] is None
    assert account["tier"] is None
    assert account["is_disabled"] is None


def test_an_unknown_account_is_a_404_not_a_500(client):
    response = client.get("/admin/api/users/test-nobody-id", headers=ADMIN)

    assert response.status_code == 404
    assert response.get_json() == {"error": "no_such_account"}


def test_an_id_that_cannot_name_an_account_is_also_a_404(client):
    """A non-uuid names no account. Left to the driver it surfaces as a 500 for
    what is really a not-found."""
    assert client.get("/admin/api/users/not-a-uuid", headers=ADMIN).status_code == 404


def test_the_detail_is_gated_like_every_other_console_read(client):
    assert client.get("/admin/api/users/test-user-id").status_code == 401
    assert client.get("/admin/api/users/test-user-id", headers=AUTH).status_code == 403


def test_the_activity_log_can_be_filtered_to_one_account(client):
    """"What has happened to this person" had no surface at all before this —
    /admin/api/audit is global and newest-first."""
    client.patch("/admin/api/users/test-user-id", headers=ADMIN,
                 json={"is_disabled": True, "reason": "for the record"})
    client.patch("/admin/api/users/test-disabled-id", headers=ADMIN,
                 json={"is_disabled": False})

    entries = client.get(
        "/admin/api/audit?target_type=user&target_id=test-user-id", headers=ADMIN
    ).get_json()["entries"]

    assert entries, "the filter returned nothing for an account that was just changed"
    assert {e["target_id"] for e in entries} == {"test-user-id"}


@pytest.mark.parametrize("query", [
    "target_type=conversations",
    "target_type=user&target_id=" + "x" * 65,
])
def test_a_target_the_log_does_not_recognise_is_refused(client, query):
    assert client.get(f"/admin/api/audit?{query}", headers=ADMIN).status_code == 422
