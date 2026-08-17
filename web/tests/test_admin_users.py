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
def app(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:5001")
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


def test_a_single_call_changing_both_role_and_standing_records_both(client):
    """A mutation carrying both role and is_disabled records two distinct audit
    rows with their respective diffs, rather than dropping one."""
    response = client.patch(
        "/admin/api/users/test-user-id",
        json={"role": "admin", "is_disabled": True, "reason": "quarantined admin"},
        headers=ADMIN,
    )
    assert response.status_code == 200

    entries = client.get(
        "/admin/api/audit?target_type=user&target_id=test-user-id", headers=ADMIN
    ).get_json()["entries"]

    assert len(entries) == 2
    actions = {e["action"] for e in entries}
    assert actions == {"user.role_change", "user.disable"}

    disable_entry = next(e for e in entries if e["action"] == "user.disable")
    assert disable_entry["before"] == {"is_disabled": False}
    assert disable_entry["after"] == {"is_disabled": True}
    assert disable_entry["note"] == "quarantined admin"

    role_entry = next(e for e in entries if e["action"] == "user.role_change")
    assert role_entry["before"] == {"role": "user"}
    assert role_entry["after"] == {"role": "admin"}


def test_a_no_op_user_flags_edit_records_nothing(client):
    """A patch setting a field to the value it already holds records nothing at
    all — matching admin_update_profile and avoiding false audit entries."""
    before = len(client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"])

    response = client.patch(
        "/admin/api/users/test-user-id",
        json={"role": "user", "is_disabled": False},
        headers=ADMIN,
    )
    assert response.status_code == 200

    after = len(client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"])
    assert after == before, "an unchanged user flags patch wrote an audit row"


def test_a_partial_no_op_records_only_the_field_that_moved(client):
    """When both fields are sent but only one changed, only the changed field
    gets an audit row."""
    response = client.patch(
        "/admin/api/users/test-user-id",
        json={"role": "user", "is_disabled": True, "reason": "abusive questions"},
        headers=ADMIN,
    )
    assert response.status_code == 200

    entries = client.get(
        "/admin/api/audit?target_type=user&target_id=test-user-id", headers=ADMIN
    ).get_json()["entries"]

    assert len(entries) == 1
    assert entries[0]["action"] == "user.disable"
    assert entries[0]["before"] == {"is_disabled": False}
    assert entries[0]["after"] == {"is_disabled": True}


def test_a_reason_on_a_role_only_change_is_not_dropped(client):
    """`reason` is a general note on the call, not a field reserved for
    disabling — the route only requires it when is_disabled is true, it does
    not forbid sending it alongside a role-only change. A role_change row
    must keep it rather than silently discarding it."""
    response = client.patch(
        "/admin/api/users/test-user-id",
        json={"role": "admin", "reason": "promoted after training"},
        headers=ADMIN,
    )
    assert response.status_code == 200

    entries = client.get(
        "/admin/api/audit?target_type=user&target_id=test-user-id", headers=ADMIN
    ).get_json()["entries"]

    assert len(entries) == 1
    assert entries[0]["action"] == "user.role_change"
    assert entries[0]["note"] == "promoted after training"


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


# ── Profile editing ───────────────────────────────────────────────────────────


def test_a_profile_edit_is_recorded_with_before_and_after(client):
    """A free-text overwrite is unrecoverable without the diff, which is the
    whole reason this is audited rather than just permitted."""
    response = client.patch(
        "/admin/api/users/test-user-id/profile", headers=ADMIN,
        json={"full_name": "New Name", "organization": "New Org",
              "specialization": "Regulatory"},
    )
    assert response.status_code == 200

    entry = client.get(
        "/admin/api/audit?target_type=user&target_id=test-user-id", headers=ADMIN
    ).get_json()["entries"][0]
    assert entry["action"] == "user.profile_change"
    assert entry["after"]["full_name"] == "New Name"
    assert "full_name" in entry["before"]


def test_a_no_op_profile_edit_records_nothing(client):
    """TODO.md files the opposite behaviour as a bug against the sibling RPC: a
    patch that sets a field to the value it already holds recording a change
    that did not occur. There is no reason to reproduce it here."""
    payload = {"full_name": "Same", "organization": "Same", "specialization": "Same"}
    client.patch("/admin/api/users/test-user-id/profile", headers=ADMIN, json=payload)
    before = len(client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"])

    client.patch("/admin/api/users/test-user-id/profile", headers=ADMIN, json=payload)

    after = len(client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"])
    assert after == before, "an unchanged save wrote an audit row"


def test_a_stale_edit_is_refused_rather_than_clobbering(client):
    """A row lock protects execution time, not the minutes an operator spends
    typing. Two people editing the same account otherwise last-write-wins."""
    response = client.patch(
        "/admin/api/users/test-user-id/profile", headers=ADMIN,
        json={"full_name": "A", "organization": "B", "specialization": "C",
              "expected_updated_at": "1999-01-01T00:00:00+00:00"},
    )
    assert response.status_code == 409
    assert response.get_json() == {"error": "profile_changed_since_loaded"}


def test_an_account_with_no_profile_cannot_have_one_edited(client):
    response = client.patch(
        "/admin/api/users/test-orphan-id/profile", headers=ADMIN,
        json={"full_name": "X", "organization": "Y", "specialization": "Z"},
    )
    assert response.status_code == 409
    assert response.get_json() == {"error": "no_such_account"}


@pytest.mark.parametrize("payload, status", [
    ({"full_name": 12}, 400),
    ({"full_name": "x" * 201}, 422),
    ({"role": "admin"}, 422),
    ({"is_disabled": True}, 422),
    ({"password": "hunter2"}, 422),
])
def test_the_profile_route_accepts_only_the_three_fields_it_owns(client, payload, status):
    assert client.patch(
        "/admin/api/users/test-user-id/profile", headers=ADMIN, json=payload
    ).status_code == status


def test_the_profile_route_is_gated_like_every_other_mutation(client):
    body = {"full_name": "X", "organization": "Y", "specialization": "Z"}
    assert client.patch("/admin/api/users/test-user-id/profile", json=body).status_code == 401
    assert client.patch(
        "/admin/api/users/test-user-id/profile", headers=AUTH, json=body
    ).status_code == 403


def test_no_console_route_accepts_a_password(client, app):
    """The design position, pinned rather than documented.

    An operator may send a reset link and may never set a credential — a shared
    password breaks attribution for every row in the audit log, not just its own.

    Restricted to MUTATION methods on purpose: an earlier draft of this test sent
    a body to every admin route and asserted no 2xx, which cannot work, because
    GET handlers ignore request bodies and correctly answer 200. The real
    property is that no route that CHANGES anything will act on a password, and
    that only means something because each one rejects unknown keys outright.
    """
    mutations = [
        (rule.rule.replace("<user_id>", "test-user-id"), method)
        for rule in app.url_map.iter_rules()
        if str(rule.endpoint).startswith("admin.")
        for method in ("POST", "PATCH", "PUT")
        if method in rule.methods
    ]
    assert mutations, "expected the console to have mutation routes to check"

    for path, method in mutations:
        response = client.open(path, method=method, headers=ADMIN,
                               json={"password": "hunter2"})
        assert response.status_code >= 400, (
            f"{method} {path} accepted a password field ({response.status_code})"
        )


# ── Sending a reset ───────────────────────────────────────────────────────────


def test_a_reset_records_intent_before_the_send_and_the_outcome_after(client, app):
    """Two rows, correlated. The failure this shape exists for is the process
    dying between the send and the record — which leaves a dangling `requested`
    rather than silence, and that is the point."""
    response = client.post(
        "/admin/api/users/test-user-id/reset-password", headers=ADMIN
    )
    assert response.status_code == 200

    entries = client.get(
        "/admin/api/audit?target_type=user&target_id=test-user-id", headers=ADMIN
    ).get_json()["entries"]
    actions = [e["action"] for e in entries]
    assert "user.password_reset_requested" in actions
    assert "user.password_reset_accepted" in actions

    ids = {e["after"]["operation_id"] for e in entries if e.get("after")}
    assert len(ids) == 1, "the pair must share one operation_id"
    assert response.get_json()["operation_id"] in ids


def test_the_outcome_is_named_accepted_rather_than_sent(client):
    """The dispatcher establishes that GoTrue accepted the request, not that
    anything was delivered. Delivery lives in the provider's log."""
    client.post("/admin/api/users/test-user-id/reset-password", headers=ADMIN)
    actions = [
        e["action"] for e in
        client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]
    ]
    assert "user.password_reset_accepted" in actions
    assert "user.password_reset_sent" not in actions


def test_a_failed_send_is_recorded_as_failed_not_accepted(client, app):
    app.config["_testing_recovery_dispatcher"].refuse_with = "reset_rate_limited"

    response = client.post(
        "/admin/api/users/test-user-id/reset-password", headers=ADMIN
    )
    assert response.status_code == 429
    assert response.get_json() == {"error": "reset_rate_limited"}

    actions = [
        e["action"] for e in
        client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]
    ]
    assert "user.password_reset_failed" in actions
    assert "user.password_reset_accepted" not in actions
    # The intent still stands: something was attempted, and the log says so.
    assert "user.password_reset_requested" in actions


def test_the_console_never_returns_a_recovery_link(client):
    """The design position in one assertion. A body carrying the link would put
    a bearer credential on whatever screen called this."""
    body = client.post(
        "/admin/api/users/test-user-id/reset-password", headers=ADMIN
    ).get_data(as_text=True)

    assert "http" not in body
    assert "token" not in body.lower()


def test_a_reset_for_an_unknown_account_is_refused(client):
    assert client.post(
        "/admin/api/users/test-nobody-id/reset-password", headers=ADMIN
    ).status_code == 404


def test_sending_a_reset_is_gated(client):
    assert client.post("/admin/api/users/test-user-id/reset-password").status_code == 401
    assert client.post(
        "/admin/api/users/test-user-id/reset-password", headers=AUTH
    ).status_code == 403


# ── Ending sessions ────────────────────────────────────────────────────────────


def test_a_revoke_records_intent_before_the_call_and_the_outcome_after(client):
    response = client.post(
        "/admin/api/users/test-user-id/revoke-sessions", headers=ADMIN
    )
    assert response.status_code == 200

    entries = client.get(
        "/admin/api/audit?target_type=user&target_id=test-user-id", headers=ADMIN
    ).get_json()["entries"]
    actions = [e["action"] for e in entries]
    assert "user.sessions_revoke_requested" in actions
    assert "user.sessions_revoke_accepted" in actions

    ids = {e["after"]["operation_id"] for e in entries if e.get("after")}
    assert len(ids) == 1, "the pair must share one operation_id"
    assert response.get_json()["operation_id"] in ids


def test_the_console_never_returns_a_generated_password(client):
    """The design position this route exists to preserve: nobody, not even the
    operator, ever sees the value that actually ends the sessions."""
    response = client.post(
        "/admin/api/users/test-user-id/revoke-sessions", headers=ADMIN
    )
    assert response.get_json() == {
        "accepted": True, "operation_id": response.get_json()["operation_id"],
    }


def test_a_failed_revoke_is_recorded_as_failed_not_accepted(app, client):
    app.config["_testing_auth_admin_dispatcher"].refuse_with = "auth_admin_failed"
    response = client.post(
        "/admin/api/users/test-user-id/revoke-sessions", headers=ADMIN
    )
    assert response.status_code == 502
    assert response.get_json()["error"] == "auth_admin_failed"

    actions = [e["action"] for e in
               client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]]
    assert "user.sessions_revoke_failed" in actions
    assert "user.sessions_revoke_accepted" not in actions


def test_an_ambiguous_revoke_failure_is_recorded_as_outcome_unknown_not_failed(app, client):
    """A transport failure does not prove the mutation failed — GoTrue may
    have already committed it. Recording that as an ordinary "failed" would
    be a false entry on the one surface whose purpose is to be trustworthy
    later."""
    app.config["_testing_auth_admin_dispatcher"].refuse_with = "auth_admin_unreachable"
    app.config["_testing_auth_admin_dispatcher"].refuse_ambiguous = True

    response = client.post(
        "/admin/api/users/test-user-id/revoke-sessions", headers=ADMIN
    )
    assert response.get_json()["outcome_unknown"] is True

    actions = [e["action"] for e in
               client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]]
    assert "user.sessions_revoke_outcome_unknown" in actions
    assert "user.sessions_revoke_failed" not in actions
    assert "user.sessions_revoke_accepted" not in actions


def test_revoking_sessions_refuses_when_the_actor_is_no_longer_admin(app, client):
    """Re-checked immediately before the external call, not only at the gate —
    an operator demoted mid-request should not still complete this."""
    admin_row = next(
        r for r in app.config["_testing_admin_backend"]._users if r["id"] == "test-admin-id"
    )
    admin_row["is_disabled"] = True
    try:
        response = client.post(
            "/admin/api/users/test-user-id/revoke-sessions", headers=ADMIN
        )
        assert response.status_code == 409
        assert response.get_json()["error"] == "actor_no_longer_administrator"
    finally:
        admin_row["is_disabled"] = False


def test_a_revoke_for_an_unknown_account_is_refused(client):
    assert client.post(
        "/admin/api/users/test-nobody-id/revoke-sessions", headers=ADMIN
    ).status_code == 404


def test_revoking_sessions_rejects_a_nonempty_body(client):
    response = client.post(
        "/admin/api/users/test-user-id/revoke-sessions",
        json={"password": "whatever"}, headers=ADMIN,
    )
    assert response.status_code == 422
    assert response.get_json()["error"] == "unknown_field"


def test_revoking_sessions_is_gated(client):
    assert client.post("/admin/api/users/test-user-id/revoke-sessions").status_code == 401
    assert client.post(
        "/admin/api/users/test-user-id/revoke-sessions", headers=AUTH
    ).status_code == 403


# ── Changing an email address ─────────────────────────────────────────────────


def test_an_email_change_records_intent_before_the_call_and_the_outcome_after(client):
    response = client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "new-address@example.com"}, headers=ADMIN,
    )
    assert response.status_code == 200

    entries = client.get(
        "/admin/api/audit?target_type=user&target_id=test-user-id", headers=ADMIN
    ).get_json()["entries"]
    actions = [e["action"] for e in entries]
    assert "user.email_change_requested" in actions
    assert "user.email_change_accepted" in actions

    requested = next(e for e in entries if e["action"] == "user.email_change_requested")
    assert requested["before"] == {"email": "test@example.com"}

    accepted = next(e for e in entries if e["action"] == "user.email_change_accepted")
    assert accepted["after"]["email"] == "new-address@example.com"

    ids = {e["after"]["operation_id"] for e in entries if e.get("after")}
    assert len(ids) == 1
    assert response.get_json()["operation_id"] in ids


def test_a_successful_email_change_is_visible_on_the_next_load(client):
    """Not just recorded — the account state itself must actually change, or a
    success toast is followed by a stale view. Catches the in-memory
    dispatcher recording a call without mutating the account it claims to."""
    client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "new-address@example.com"}, headers=ADMIN,
    )
    account = client.get(
        "/admin/api/users/test-user-id", headers=ADMIN
    ).get_json()["user"]
    assert account["email"] == "new-address@example.com"
    assert account["email_identity_verified"] is False


def test_a_failed_email_change_is_recorded_as_failed_not_accepted(app, client):
    app.config["_testing_auth_admin_dispatcher"].refuse_with = "email_already_registered"
    response = client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "admin@example.com"}, headers=ADMIN,
    )
    assert response.status_code == 409
    assert response.get_json()["error"] == "email_already_registered"

    actions = [e["action"] for e in
               client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]]
    assert "user.email_change_failed" in actions
    assert "user.email_change_accepted" not in actions


def test_an_ambiguous_email_change_failure_is_recorded_as_outcome_unknown(app, client):
    app.config["_testing_auth_admin_dispatcher"].refuse_with = "auth_admin_unreachable"
    app.config["_testing_auth_admin_dispatcher"].refuse_ambiguous = True

    response = client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "new-address@example.com"}, headers=ADMIN,
    )
    assert response.get_json()["outcome_unknown"] is True
    actions = [e["action"] for e in
               client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]]
    assert "user.email_change_outcome_unknown" in actions
    assert "user.email_change_failed" not in actions


def test_changing_email_refuses_a_self_target(client):
    """The takeover primitive this specifically guards against: change an
    account's email, then click the existing reset-password button. Only this
    action refuses a self-target — revoke-sessions and reset-password do not,
    because ending your own session or resetting your own password is not the
    same risk."""
    response = client.post(
        "/admin/api/users/test-admin-id/change-email",
        json={"email": "someone-else@example.com"}, headers=ADMIN,
    )
    assert response.status_code == 409
    assert response.get_json()["error"] == "cannot_change_own_email"


def test_changing_email_to_the_current_address_is_refused_as_a_no_op(client):
    response = client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "TEST@EXAMPLE.COM"}, headers=ADMIN,
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "same_email"


def test_changing_email_rejects_a_value_with_no_at_sign(client):
    response = client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "not-an-email"}, headers=ADMIN,
    )
    assert response.status_code == 422
    assert response.get_json()["error"] == "invalid_email"


def test_changing_email_rejects_a_non_string_or_missing_email(client):
    assert client.post(
        "/admin/api/users/test-user-id/change-email", json={}, headers=ADMIN,
    ).status_code == 400
    assert client.post(
        "/admin/api/users/test-user-id/change-email", json={"email": 5}, headers=ADMIN,
    ).status_code == 400


def test_changing_email_rejects_an_unknown_field(client):
    response = client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "new@example.com", "password": "x"}, headers=ADMIN,
    )
    assert response.status_code == 422
    assert response.get_json()["error"] == "unknown_field"


def test_an_email_change_for_an_unknown_account_is_refused(client):
    assert client.post(
        "/admin/api/users/test-nobody-id/change-email",
        json={"email": "new@example.com"}, headers=ADMIN,
    ).status_code == 404


def test_changing_email_is_gated(client):
    assert client.post(
        "/admin/api/users/test-user-id/change-email", json={"email": "new@example.com"},
    ).status_code == 401
    assert client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "new@example.com"}, headers=AUTH,
    ).status_code == 403
