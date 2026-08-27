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
        "admin@example.com",
        "test@example.com",
        "disabled@example.com",
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
    response = client.patch("/admin/api/users/test-admin-id", json={"role": "user"}, headers=ADMIN)
    assert response.status_code == 409
    assert response.get_json() == {"error": "cannot_change_own_access"}


def test_an_administrator_cannot_disable_themselves(client):
    """Sent with a reason, because the route validates the payload before the
    database applies the rule — and a console always sends one."""
    response = client.patch(
        "/admin/api/users/test-admin-id",
        json={"is_disabled": True, "reason": "tidying up"},
        headers=ADMIN,
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
        response = client.patch("/admin/api/users/test-user-id", json=payload, headers=ADMIN)
        assert response.status_code == 422
        assert response.get_json() == {"error": "reason_required"}


def test_restoring_access_needs_no_justification(client):
    """The burden belongs on the restrictive act, not on undoing it."""
    client.patch(
        "/admin/api/users/test-user-id",
        json={"is_disabled": True, "reason": "spam"},
        headers=ADMIN,
    )
    response = client.patch(
        "/admin/api/users/test-user-id", json={"is_disabled": False}, headers=ADMIN
    )
    assert response.status_code == 200


def test_a_non_string_reason_is_a_400_rather_than_a_crash(client):
    """`.strip()` on a number raised, and the client saw a 500."""
    response = client.patch(
        "/admin/api/users/test-user-id",
        json={"is_disabled": True, "reason": 12},
        headers=ADMIN,
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
    other = AuditActor("test-user-id", "test@example.com")  # a reader, not an admin

    with pytest.raises(AdminActionRefused) as refused:
        backend.set_user_flags("test-disabled-id", role="admin", actor=other)
    assert refused.value.code == "actor_no_longer_administrator"


def test_disabling_and_restoring_chat_access(client):
    off = client.patch(
        "/admin/api/users/test-user-id",
        json={"is_disabled": True, "reason": "spam"},
        headers=ADMIN,
    ).get_json()
    assert off["user"]["is_disabled"] is True

    on = client.patch(
        "/admin/api/users/test-user-id", json={"is_disabled": False}, headers=ADMIN
    ).get_json()
    assert on["user"]["is_disabled"] is False


def test_every_change_is_recorded_with_its_reason(client):
    client.patch(
        "/admin/api/users/test-user-id",
        json={"is_disabled": True, "reason": "abusive questions"},
        headers=ADMIN,
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


def _seed_token_cache(app, token: str, user_id: str) -> None:
    """Reach into the token cache directly — it has no public "put" (publish
    is deliberately entangled with single-flight), so this is how a test puts
    an entry there without also faking a whole GoTrue round trip."""
    from web.services.token_verification_cache import VerifiedIdentity

    cache = app.config["token_verification"]
    identity = VerifiedIdentity(user_id=user_id, email=f"{user_id}@example.com", token_exp=None)
    key = cache._key(token)
    with cache._lock:
        cache._data[key] = (cache._now() + 30, cache._now(), identity)
        cache._by_user.setdefault(user_id, set()).add(key)


def test_a_role_change_invalidates_the_token_cache_too(client, app):
    """The flags cache is not the only thing a role change must drop — the
    token cache separately remembers "GoTrue said this credential is good"
    and must not let a demoted reader's session outlive its TTL."""
    _seed_token_cache(app, "some-live-token", "test-user-id")
    assert len(app.config["token_verification"]) == 1

    client.patch("/admin/api/users/test-user-id", json={"role": "user"}, headers=ADMIN)

    assert len(app.config["token_verification"]) == 0


# ── Payload validation ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload,status",
    [
        ({}, 400),  # nothing to change
        ({"role": "root"}, 422),  # not a role this app has
        ({"is_disabled": "yes"}, 400),  # not a boolean
        ("not a dict", 400),
    ],
)
def test_bad_payloads_are_refused(client, payload, status):
    response = client.patch("/admin/api/users/test-user-id", json=payload, headers=ADMIN)
    assert response.status_code == status


def test_a_change_by_a_reader_is_refused(client):
    response = client.patch("/admin/api/users/test-user-id", json={"role": "admin"}, headers=AUTH)
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


def test_account_detail_carries_the_consent_record(client):
    """docs/profile-refactor-plan.md Step 6 checklist item: admin visibility
    of the consent record. Read-only — no route here writes any of these
    fields; the guard trigger refuses that regardless of what a route sent."""
    account = client.get("/admin/api/users/test-user-id", headers=ADMIN).get_json()["user"]

    for field in (
        "marketing_consent",
        "marketing_consent_granted_at",
        "marketing_consent_withdrawn_at",
        "marketing_consent_policy_version",
        "marketing_consent_language",
        "marketing_consent_surface",
        "marketing_consent_granted_while_unconfirmed",
    ):
        assert field in account
    # The seeded test identity has never consented.
    assert account["marketing_consent"] is False


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
    """ "What has happened to this person" had no surface at all before this —
    /admin/api/audit is global and newest-first."""
    client.patch(
        "/admin/api/users/test-user-id",
        headers=ADMIN,
        json={"is_disabled": True, "reason": "for the record"},
    )
    client.patch("/admin/api/users/test-disabled-id", headers=ADMIN, json={"is_disabled": False})

    entries = client.get(
        "/admin/api/audit?target_type=user&target_id=test-user-id", headers=ADMIN
    ).get_json()["entries"]

    assert entries, "the filter returned nothing for an account that was just changed"
    assert {e["target_id"] for e in entries} == {"test-user-id"}


@pytest.mark.parametrize(
    "query",
    [
        "target_type=conversations",
        "target_type=user&target_id=" + "x" * 65,
    ],
)
def test_a_target_the_log_does_not_recognise_is_refused(client, query):
    assert client.get(f"/admin/api/audit?{query}", headers=ADMIN).status_code == 422


# ── Profile editing ───────────────────────────────────────────────────────────


def test_a_profile_edit_is_recorded_with_before_and_after(client):
    """A free-text overwrite is unrecoverable without the diff, which is the
    whole reason this is audited rather than just permitted."""
    response = client.patch(
        "/admin/api/users/test-user-id/profile",
        headers=ADMIN,
        json={
            "first_name": "New",
            "family_name": "Name",
            "age": 30,
            "organization": "New Org",
            "specialization": "Regulatory",
        },
    )
    assert response.status_code == 200

    entry = client.get(
        "/admin/api/audit?target_type=user&target_id=test-user-id", headers=ADMIN
    ).get_json()["entries"][0]
    assert entry["action"] == "user.profile_change"
    assert entry["after"]["first_name"] == "New"
    assert entry["after"]["family_name"] == "Name"
    assert "first_name" in entry["before"]


def test_a_no_op_profile_edit_records_nothing(client):
    """TODO.md files the opposite behaviour as a bug against the sibling RPC: a
    patch that sets a field to the value it already holds recording a change
    that did not occur. There is no reason to reproduce it here."""
    payload = {
        "first_name": "Same",
        "family_name": "Same",
        "age": None,
        "organization": "Same",
        "specialization": "Same",
    }
    client.patch("/admin/api/users/test-user-id/profile", headers=ADMIN, json=payload)
    before = len(client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"])

    client.patch("/admin/api/users/test-user-id/profile", headers=ADMIN, json=payload)

    after = len(client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"])
    assert after == before, "an unchanged save wrote an audit row"


def test_a_stale_edit_is_refused_rather_than_clobbering(client):
    """A row lock protects execution time, not the minutes an operator spends
    typing. Two people editing the same account otherwise last-write-wins."""
    response = client.patch(
        "/admin/api/users/test-user-id/profile",
        headers=ADMIN,
        json={
            "first_name": "A",
            "family_name": "B",
            "organization": "C",
            "specialization": "D",
            "expected_updated_at": "1999-01-01T00:00:00+00:00",
        },
    )
    assert response.status_code == 409
    assert response.get_json() == {"error": "profile_changed_since_loaded"}


def test_an_account_with_no_profile_cannot_have_one_edited(client):
    response = client.patch(
        "/admin/api/users/test-orphan-id/profile",
        headers=ADMIN,
        json={"first_name": "X", "organization": "Y", "specialization": "Z"},
    )
    assert response.status_code == 409
    assert response.get_json() == {"error": "no_such_account"}


@pytest.mark.parametrize(
    "payload, status",
    [
        ({"first_name": 12}, 400),
        ({"first_name": "x" * 101}, 422),
        ({"organization": "x" * 201}, 422),
        ({"age": "30"}, 400),
        ({"age": True}, 400),
        ({"age": 12}, 422),
        ({"age": 121}, 422),
        ({"full_name": "New Name"}, 422),
        ({"role": "admin"}, 422),
        ({"is_disabled": True}, 422),
        ({"password": "hunter2"}, 422),
    ],
)
def test_the_profile_route_accepts_only_the_fields_it_owns(client, payload, status):
    assert (
        client.patch(
            "/admin/api/users/test-user-id/profile", headers=ADMIN, json=payload
        ).status_code
        == status
    )


def test_the_profile_route_is_gated_like_every_other_mutation(client):
    body = {"first_name": "X", "organization": "Y", "specialization": "Z"}
    assert client.patch("/admin/api/users/test-user-id/profile", json=body).status_code == 401
    assert (
        client.patch("/admin/api/users/test-user-id/profile", headers=AUTH, json=body).status_code
        == 403
    )


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
        response = client.open(path, method=method, headers=ADMIN, json={"password": "hunter2"})
        assert response.status_code >= 400, (
            f"{method} {path} accepted a password field ({response.status_code})"
        )


# ── Sending a reset ───────────────────────────────────────────────────────────


def test_a_reset_records_intent_before_the_send_and_the_outcome_after(client, app):
    """Two rows, correlated. The failure this shape exists for is the process
    dying between the send and the record — which leaves a dangling `requested`
    rather than silence, and that is the point."""
    response = client.post("/admin/api/users/test-user-id/reset-password", headers=ADMIN)
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
        e["action"] for e in client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]
    ]
    assert "user.password_reset_accepted" in actions
    assert "user.password_reset_sent" not in actions


def test_a_failed_send_is_recorded_as_failed_not_accepted(client, app):
    app.config["_testing_recovery_dispatcher"].refuse_with = "reset_rate_limited"

    response = client.post("/admin/api/users/test-user-id/reset-password", headers=ADMIN)
    assert response.status_code == 429
    assert response.get_json() == {"error": "reset_rate_limited"}

    actions = [
        e["action"] for e in client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]
    ]
    assert "user.password_reset_failed" in actions
    assert "user.password_reset_accepted" not in actions
    # The intent still stands: something was attempted, and the log says so.
    assert "user.password_reset_requested" in actions


def test_the_console_never_returns_a_recovery_link(client):
    """The design position in one assertion. A body carrying the link would put
    a bearer credential on whatever screen called this."""
    body = client.post("/admin/api/users/test-user-id/reset-password", headers=ADMIN).get_data(
        as_text=True
    )

    assert "http" not in body
    assert "token" not in body.lower()


def test_a_reset_for_an_unknown_account_is_refused(client):
    assert (
        client.post("/admin/api/users/test-nobody-id/reset-password", headers=ADMIN).status_code
        == 404
    )


def test_sending_a_reset_is_gated(client):
    assert client.post("/admin/api/users/test-user-id/reset-password").status_code == 401
    assert (
        client.post("/admin/api/users/test-user-id/reset-password", headers=AUTH).status_code == 403
    )


# ── Ending sessions ────────────────────────────────────────────────────────────


def test_a_revoke_records_intent_before_the_call_and_the_outcome_after(client):
    response = client.post("/admin/api/users/test-user-id/revoke-sessions", headers=ADMIN)
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
    response = client.post("/admin/api/users/test-user-id/revoke-sessions", headers=ADMIN)
    assert response.get_json() == {
        "accepted": True,
        "operation_id": response.get_json()["operation_id"],
    }


def test_a_failed_revoke_is_recorded_as_failed_not_accepted(app, client):
    app.config["_testing_auth_admin_dispatcher"].refuse_with = "auth_admin_failed"
    response = client.post("/admin/api/users/test-user-id/revoke-sessions", headers=ADMIN)
    assert response.status_code == 502
    assert response.get_json()["error"] == "auth_admin_failed"

    actions = [
        e["action"] for e in client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]
    ]
    assert "user.sessions_revoke_failed" in actions
    assert "user.sessions_revoke_accepted" not in actions


def test_revoking_sessions_drops_the_token_cache(client, app):
    """The sharpest of the invalidation call sites: this route's entire
    purpose is ending sessions right now, and a warm token cache is exactly
    what would let a revoked session keep authenticating anyway."""
    _seed_token_cache(app, "some-live-token", "test-user-id")
    assert len(app.config["token_verification"]) == 1

    client.post("/admin/api/users/test-user-id/revoke-sessions", headers=ADMIN)

    assert len(app.config["token_verification"]) == 0


def test_an_ambiguous_revoke_failure_still_drops_the_token_cache(app, client):
    """A transport failure does not prove the revocation failed — GoTrue may
    have already committed it. The cache must resolve that ambiguity in the
    safe direction: assume it happened."""
    _seed_token_cache(app, "some-live-token", "test-user-id")
    app.config["_testing_auth_admin_dispatcher"].refuse_with = "auth_admin_unreachable"
    app.config["_testing_auth_admin_dispatcher"].refuse_ambiguous = True

    client.post("/admin/api/users/test-user-id/revoke-sessions", headers=ADMIN)

    assert len(app.config["token_verification"]) == 0


def test_a_definitive_revoke_failure_leaves_the_token_cache_alone(app, client):
    """The opposite case: a definitive, non-ambiguous refusal means nothing
    actually happened at GoTrue, so there is nothing to evict."""
    _seed_token_cache(app, "some-live-token", "test-user-id")
    app.config["_testing_auth_admin_dispatcher"].refuse_with = "auth_admin_failed"

    client.post("/admin/api/users/test-user-id/revoke-sessions", headers=ADMIN)

    assert len(app.config["token_verification"]) == 1


def test_an_ambiguous_revoke_failure_is_recorded_as_outcome_unknown_not_failed(app, client):
    """A transport failure does not prove the mutation failed — GoTrue may
    have already committed it. Recording that as an ordinary "failed" would
    be a false entry on the one surface whose purpose is to be trustworthy
    later."""
    app.config["_testing_auth_admin_dispatcher"].refuse_with = "auth_admin_unreachable"
    app.config["_testing_auth_admin_dispatcher"].refuse_ambiguous = True

    response = client.post("/admin/api/users/test-user-id/revoke-sessions", headers=ADMIN)
    assert response.get_json()["outcome_unknown"] is True

    actions = [
        e["action"] for e in client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]
    ]
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
        response = client.post("/admin/api/users/test-user-id/revoke-sessions", headers=ADMIN)
        assert response.status_code == 409
        assert response.get_json()["error"] == "actor_no_longer_administrator"
    finally:
        admin_row["is_disabled"] = False


def test_a_revoke_for_an_unknown_account_is_refused(client):
    assert (
        client.post("/admin/api/users/test-nobody-id/revoke-sessions", headers=ADMIN).status_code
        == 404
    )


def test_revoking_sessions_rejects_a_nonempty_body(client):
    response = client.post(
        "/admin/api/users/test-user-id/revoke-sessions",
        json={"password": "whatever"},
        headers=ADMIN,
    )
    assert response.status_code == 422
    assert response.get_json()["error"] == "unknown_field"


def test_revoking_sessions_is_gated(client):
    assert client.post("/admin/api/users/test-user-id/revoke-sessions").status_code == 401
    assert (
        client.post("/admin/api/users/test-user-id/revoke-sessions", headers=AUTH).status_code
        == 403
    )


# ── Changing an email address ─────────────────────────────────────────────────


def test_an_email_change_records_intent_before_the_call_and_the_outcome_after(client):
    response = client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "new-address@example.com"},
        headers=ADMIN,
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
        json={"email": "new-address@example.com"},
        headers=ADMIN,
    )
    account = client.get("/admin/api/users/test-user-id", headers=ADMIN).get_json()["user"]
    assert account["email"] == "new-address@example.com"
    assert account["email_identity_verified"] is False


def test_an_email_change_drops_the_token_cache(client, app):
    """The token cache holds "GoTrue said this credential is good"; it must
    not keep answering for a token verified against the account's old
    identity."""
    _seed_token_cache(app, "some-live-token", "test-user-id")
    assert len(app.config["token_verification"]) == 1

    client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "new-address@example.com"},
        headers=ADMIN,
    )

    assert len(app.config["token_verification"]) == 0


def test_an_email_change_drops_the_identity_flags_cache_too(client, app):
    """`session["user_email"]` is set from `resolve_identity_flags`'s result
    (app.py's `_authenticate_request`), which returns a flags-cache HIT
    verbatim — ignoring whatever fresh email the token carried. The token
    cache alone does not keep this fresh; `identity_flags` must be dropped
    too, or a reader keeps seeing their old address in their own session for
    up to that cache's TTL."""
    from web.services.identity_cache import IdentityFlags

    flags_cache = app.config["identity_flags"]
    flags_cache.put(IdentityFlags("test-user-id", "test@example.com", "user", "free", False))
    assert flags_cache.get("test-user-id") is not None

    client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "new-address@example.com"},
        headers=ADMIN,
    )

    assert flags_cache.get("test-user-id") is None


def test_a_failed_email_change_is_recorded_as_failed_not_accepted(app, client):
    app.config["_testing_auth_admin_dispatcher"].refuse_with = "email_already_registered"
    response = client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "admin@example.com"},
        headers=ADMIN,
    )
    assert response.status_code == 409
    assert response.get_json()["error"] == "email_already_registered"

    actions = [
        e["action"] for e in client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]
    ]
    assert "user.email_change_failed" in actions
    assert "user.email_change_accepted" not in actions


def test_an_ambiguous_email_change_failure_is_recorded_as_outcome_unknown(app, client):
    app.config["_testing_auth_admin_dispatcher"].refuse_with = "auth_admin_unreachable"
    app.config["_testing_auth_admin_dispatcher"].refuse_ambiguous = True

    response = client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "new-address@example.com"},
        headers=ADMIN,
    )
    assert response.get_json()["outcome_unknown"] is True
    actions = [
        e["action"] for e in client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]
    ]
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
        json={"email": "someone-else@example.com"},
        headers=ADMIN,
    )
    assert response.status_code == 409
    assert response.get_json()["error"] == "cannot_change_own_email"


def test_changing_email_to_the_current_address_is_refused_as_a_no_op(client):
    response = client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "TEST@EXAMPLE.COM"},
        headers=ADMIN,
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "same_email"


def test_changing_email_rejects_a_value_with_no_at_sign(client):
    response = client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "not-an-email"},
        headers=ADMIN,
    )
    assert response.status_code == 422
    assert response.get_json()["error"] == "invalid_email"


def test_changing_email_rejects_a_non_string_or_missing_email(client):
    assert (
        client.post(
            "/admin/api/users/test-user-id/change-email",
            json={},
            headers=ADMIN,
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/admin/api/users/test-user-id/change-email",
            json={"email": 5},
            headers=ADMIN,
        ).status_code
        == 400
    )


def test_changing_email_rejects_an_unknown_field(client):
    response = client.post(
        "/admin/api/users/test-user-id/change-email",
        json={"email": "new@example.com", "password": "x"},
        headers=ADMIN,
    )
    assert response.status_code == 422
    assert response.get_json()["error"] == "unknown_field"


def test_an_email_change_for_an_unknown_account_is_refused(client):
    assert (
        client.post(
            "/admin/api/users/test-nobody-id/change-email",
            json={"email": "new@example.com"},
            headers=ADMIN,
        ).status_code
        == 404
    )


def test_changing_email_is_gated(client):
    assert (
        client.post(
            "/admin/api/users/test-user-id/change-email",
            json={"email": "new@example.com"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/admin/api/users/test-user-id/change-email",
            json={"email": "new@example.com"},
            headers=AUTH,
        ).status_code
        == 403
    )


# ── Pagination ────────────────────────────────────────────────────────────────


def _synthetic_user(index: int, email_prefix: str = "synthetic") -> dict:
    """Construct a minimal user record matching InMemoryAdminBackend's schema."""
    return {
        "id": f"synthetic-user-{index:04d}",
        "email": f"{email_prefix}_{index:04d}@example.com",
        "role": "user",
        "tier": "free",
        "is_disabled": False,
        "disabled_at": None,
        "disabled_reason": None,
        "created_at": f"2026-05-01T{index % 24:02d}:00:00+00:00",
        "last_sign_in_at": None,
        "email_identity_verified": True,
    }


def test_users_pagination_returns_ordered_slice_and_full_total(app, client):
    """A paginated response must return only the requested slice while reporting
    the full filtered total so the frontend can render an accurate 'Showing X–Y
    of Z' range rather than confusing page length with total dataset size."""
    backend_users = app.config["_testing_admin_backend"]._users
    # 4 initial seeded users + 70 synthetic users = 74 total users (> 1 page of 50)
    synthetic = [_synthetic_user(i) for i in range(1, 71)]
    backend_users.extend(synthetic)

    # Page 1 (offset 0, limit 50)
    page1_resp = client.get("/admin/api/users?limit=50&offset=0", headers=ADMIN)
    assert page1_resp.status_code == 200
    page1 = page1_resp.get_json()
    assert len(page1["users"]) == 50
    assert page1["total"] == 74
    assert page1["limit"] == 50
    assert page1["offset"] == 0

    # Page 2 (offset 50, limit 50)
    page2_resp = client.get("/admin/api/users?limit=50&offset=50", headers=ADMIN)
    assert page2_resp.status_code == 200
    page2 = page2_resp.get_json()
    assert len(page2["users"]) == 24
    assert page2["total"] == 74
    assert page2["limit"] == 50
    assert page2["offset"] == 50

    # Verify slices are distinct and together cover all 74 accounts in order
    page1_ids = [u["id"] for u in page1["users"]]
    page2_ids = [u["id"] for u in page2["users"]]
    assert not set(page1_ids).intersection(set(page2_ids))
    all_expected_ids = [u["id"] for u in backend_users]
    assert page1_ids + page2_ids == all_expected_ids


def test_users_search_pagination_preserves_query_and_reports_filtered_total(app, client):
    """When a search matches more accounts than fit on one page, navigating across
    pages must maintain the query filter 'q' and report 'total' as the filtered
    match count — not the unfiltered database total."""
    backend_users = app.config["_testing_admin_backend"]._users
    # Seed 60 matching accounts and 15 non-matching accounts
    matching = [_synthetic_user(i, email_prefix="qa_tester") for i in range(1, 61)]
    unrelated = [_synthetic_user(i, email_prefix="unrelated") for i in range(1, 16)]
    backend_users.extend(matching + unrelated)

    # Page 1 of filtered search (q=qa_tester, limit=50, offset=0)
    page1_resp = client.get("/admin/api/users?q=qa_tester&limit=50&offset=0", headers=ADMIN)
    assert page1_resp.status_code == 200
    page1 = page1_resp.get_json()
    assert len(page1["users"]) == 50
    assert page1["total"] == 60
    assert all("qa_tester" in u["email"] for u in page1["users"])

    # Page 2 of filtered search (q=qa_tester, limit=50, offset=50)
    page2_resp = client.get("/admin/api/users?q=qa_tester&limit=50&offset=50", headers=ADMIN)
    assert page2_resp.status_code == 200
    page2 = page2_resp.get_json()
    assert len(page2["users"]) == 10
    assert page2["total"] == 60
    assert all("qa_tester" in u["email"] for u in page2["users"])

    # Verify no overlap between page 1 and page 2, and combined they equal all 60 matches
    page1_emails = [u["email"] for u in page1["users"]]
    page2_emails = [u["email"] for u in page2["users"]]
    assert not set(page1_emails).intersection(set(page2_emails))
    assert page1_emails + page2_emails == [u["email"] for u in matching]


def test_users_pagination_clamping_and_overflow_cap(client):
    """Limit is clamped to [1, 200] and offset clamped to [0, 1_000_000].
    The 1,000,000 offset cap prevents Postgres int4 32-bit overflow (SQLSTATE 22003)
    on adversarial deep offsets while avoiding 500 crashes."""
    # Default parameters when omitted
    default_body = client.get("/admin/api/users", headers=ADMIN).get_json()
    assert default_body["limit"] == 50
    assert default_body["offset"] == 0

    # Limit lower bound clamp (0 and negative -> 1)
    zero_limit = client.get("/admin/api/users?limit=0", headers=ADMIN).get_json()
    assert zero_limit["limit"] == 1
    assert len(zero_limit["users"]) == 1

    neg_limit = client.get("/admin/api/users?limit=-10", headers=ADMIN).get_json()
    assert neg_limit["limit"] == 1
    assert len(neg_limit["users"]) == 1

    # Limit upper bound clamp (> 200 -> 200)
    large_limit = client.get("/admin/api/users?limit=500", headers=ADMIN).get_json()
    assert large_limit["limit"] == 200

    # Offset lower bound clamp (negative -> 0)
    neg_offset = client.get("/admin/api/users?offset=-5", headers=ADMIN).get_json()
    assert neg_offset["offset"] == 0

    # Offset overflow cap (values beyond 1_000_000 clamped to 1_000_000)
    overflow_offset = client.get("/admin/api/users?offset=10000000", headers=ADMIN).get_json()
    assert overflow_offset["offset"] == 1_000_000
    assert overflow_offset["users"] == []

    # Offset at or beyond int4 max (2,147,483,647) clamped safely without 500
    int4_overflow = client.get("/admin/api/users?offset=2147483648", headers=ADMIN).get_json()
    assert int4_overflow["offset"] == 1_000_000
    assert int4_overflow["users"] == []

    # Malformed limit or offset returns 400 invalid_pagination
    assert client.get("/admin/api/users?limit=abc", headers=ADMIN).status_code == 400
    assert client.get("/admin/api/users?limit=abc", headers=ADMIN).get_json() == {
        "error": "invalid_pagination"
    }
    assert client.get("/admin/api/users?offset=xyz", headers=ADMIN).status_code == 400
    assert client.get("/admin/api/users?offset=xyz", headers=ADMIN).get_json() == {
        "error": "invalid_pagination"
    }


def test_pagination_parameters_do_not_bypass_authorization(client):
    """Pagination query parameters must not alter route authentication or authorization
    checks; unauthenticated and unprivileged requests must still be rejected."""
    assert client.get("/admin/api/users?limit=10&offset=0").status_code == 401
    assert client.get("/admin/api/users?limit=10&offset=0", headers=AUTH).status_code == 403


def test_audit_route_shares_identical_pagination_parsing_and_overflow_cap(client):
    """Both /admin/api/users and /admin/api/audit share _parse_pagination_params,
    guaranteeing identical defaults, boundary clamping, overflow capping, and
    error contracts across endpoints."""
    # Defaults
    default_body = client.get("/admin/api/audit", headers=ADMIN).get_json()
    assert default_body["limit"] == 50
    assert default_body["offset"] == 0

    # Limit clamping
    assert client.get("/admin/api/audit?limit=0", headers=ADMIN).get_json()["limit"] == 1
    assert client.get("/admin/api/audit?limit=-20", headers=ADMIN).get_json()["limit"] == 1
    assert client.get("/admin/api/audit?limit=9999", headers=ADMIN).get_json()["limit"] == 200

    # Offset clamping & overflow cap
    assert client.get("/admin/api/audit?offset=-5", headers=ADMIN).get_json()["offset"] == 0
    assert (
        client.get("/admin/api/audit?offset=10000000", headers=ADMIN).get_json()["offset"]
        == 1_000_000
    )
    assert (
        client.get("/admin/api/audit?offset=2147483648", headers=ADMIN).get_json()["offset"]
        == 1_000_000
    )

    # Malformed parameter rejection
    assert client.get("/admin/api/audit?limit=bad", headers=ADMIN).status_code == 400
    assert client.get("/admin/api/audit?limit=bad", headers=ADMIN).get_json() == {
        "error": "invalid_pagination"
    }
    assert client.get("/admin/api/audit?offset=bad", headers=ADMIN).status_code == 400
    assert client.get("/admin/api/audit?offset=bad", headers=ADMIN).get_json() == {
        "error": "invalid_pagination"
    }


def test_parse_pagination_params_helper_direct():
    """Direct unit test of _parse_pagination_params verifying clamping, defaults,
    overflow cap, and exception contracts."""
    from web.api.admin import _parse_pagination_params

    class DummyRequest:
        def __init__(self, args):
            self.args = args

    # Defaults
    assert _parse_pagination_params(DummyRequest({})) == (50, 0)

    # Clamping
    assert _parse_pagination_params(DummyRequest({"limit": "0", "offset": "-10"})) == (1, 0)
    assert _parse_pagination_params(DummyRequest({"limit": "500", "offset": "50"})) == (200, 50)
    assert _parse_pagination_params(DummyRequest({"limit": "25", "offset": "10000000"})) == (
        25,
        1_000_000,
    )

    # Value errors
    with pytest.raises(ValueError):
        _parse_pagination_params(DummyRequest({"limit": "invalid"}))
    with pytest.raises(ValueError):
        _parse_pagination_params(DummyRequest({"offset": "invalid"}))
