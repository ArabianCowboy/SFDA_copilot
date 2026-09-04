"""The console's tier catalogue and the per-account quota override.

Covers the five new routes, every refusal code they can return, and the thing
that is easy to get wrong and impossible to see: that a change made through the
console is visible to the very next claim, because the two doubles share one
dict rather than each holding a copy.
"""

from __future__ import annotations

import pytest

from web.api.app import create_app

ADMIN = {"Authorization": "Bearer fake_admin_token"}
READER = {"Authorization": "Bearer fake_token"}


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def quota(app):
    return app.config["_testing_quota_backend"]


@pytest.fixture
def user_id(client):
    return client.get("/admin/api/users", headers=ADMIN).get_json()["users"][0]["id"]


def tier_body(**kw):
    return {"key": "promo", "label_en": "Promo", "label_ar": "ترويجي", **kw}


def quota_body(**kw):
    """A FULL quota PUT. Every key present, always — see the route's docstring."""
    return {
        "tier": None,
        "daily_message_limit_override": None,
        "override_starts_at": None,
        "override_expires_at": None,
        **kw,
    }


# ── the gates ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/admin/api/tiers"),
        ("post", "/admin/api/tiers"),
        ("patch", "/admin/api/tiers/free"),
        ("delete", "/admin/api/tiers/free"),
        ("put", "/admin/api/users/whoever/quota"),
    ],
)
def test_every_route_refuses_an_unauthenticated_caller(client, method, path):
    assert getattr(client, method)(path, json={}).status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/admin/api/tiers"),
        ("post", "/admin/api/tiers"),
        ("patch", "/admin/api/tiers/free"),
        ("delete", "/admin/api/tiers/free"),
        ("put", "/admin/api/users/whoever/quota"),
    ],
)
def test_every_route_refuses_an_ordinary_reader(client, method, path):
    """The mutations too, not just the GET.

    `test_admin_page.py`'s route-gate test only walks GET routes, so a mutation
    added without a gate would pass it. These are asserted explicitly.
    """
    assert getattr(client, method)(path, json={}, headers=READER).status_code == 403


# ── tier CRUD ────────────────────────────────────────────────────────────────


def test_the_shipped_tiers_are_listed_with_member_counts(client):
    tiers = client.get("/admin/api/tiers", headers=ADMIN).get_json()["tiers"]
    keys = [t["key"] for t in tiers]
    assert keys == ["free", "staff"], "ordering, then key"
    assert all("member_count" in t for t in tiers)
    assert all("label_en" in t and "label_ar" in t for t in tiers)


def test_create_then_delete_a_tier(client):
    created = client.post("/admin/api/tiers", json=tier_body(daily_message_limit=50), headers=ADMIN)
    assert created.status_code == 200
    assert created.get_json()["tier"]["daily_message_limit"] == 50
    assert client.delete("/admin/api/tiers/promo", headers=ADMIN).status_code == 200


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (tier_body(key="Bad-Key", daily_message_limit=5), "invalid_key"),
        (tier_body(key="free", daily_message_limit=5), "duplicate_key"),
        (tier_body(daily_message_limit=-1), "invalid_limit"),
        (tier_body(daily_message_limit=True), "invalid_limit"),
        (tier_body(label_en="", daily_message_limit=5), "invalid_labels"),
        (tier_body(label_ar="x" * 41, daily_message_limit=5), "invalid_labels"),
    ],
)
def test_create_refuses_bad_input_with_a_mapped_code(client, body, code):
    """Never a raw 23514 surfacing as a 500 — a code the console can translate."""
    response = client.post("/admin/api/tiers", json=body, headers=ADMIN)
    assert response.status_code in (409, 422)
    assert response.get_json()["error"] == code


def test_the_free_tier_cannot_be_deleted(client):
    """It is structural: the column default, the trigger's literal, what signup relies on."""
    response = client.delete("/admin/api/tiers/free", headers=ADMIN)
    assert response.status_code == 409
    assert response.get_json()["error"] == "default_tier_protected"


def test_a_tier_with_members_cannot_be_deleted(client, user_id):
    client.post("/admin/api/tiers", json=tier_body(daily_message_limit=50), headers=ADMIN)
    client.put(
        f"/admin/api/users/{user_id}/quota",
        json=quota_body(tier="promo"),
        headers=ADMIN,
    )
    response = client.delete("/admin/api/tiers/promo", headers=ADMIN)
    assert response.status_code == 409
    assert response.get_json()["error"] == "tier_in_use"


def test_deleting_an_unknown_tier_says_so(client):
    assert client.delete("/admin/api/tiers/ghost", headers=ADMIN).get_json()["error"] == (
        "no_such_tier"
    )


def test_updating_an_unknown_tier_says_so(client):
    response = client.patch("/admin/api/tiers/ghost", json={"ordering": 1}, headers=ADMIN)
    assert response.get_json()["error"] == "no_such_tier"


def test_an_update_that_changes_nothing_writes_no_audit_row(client):
    """The `admin_set_user_flags` diff rule, applied to tiers."""
    before = len(client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"])
    client.patch("/admin/api/tiers/free", json={"daily_message_limit": 200}, headers=ADMIN)
    after = len(client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"])
    assert after == before


# ── the two levels reach the claim ───────────────────────────────────────────


def test_a_tier_limit_change_reaches_the_next_claim(client, quota, user_id):
    """The console and the chat route must never disagree about one account."""
    client.put(f"/admin/api/users/{user_id}/quota", json=quota_body(tier="staff"), headers=ADMIN)
    client.patch("/admin/api/tiers/staff", json={"daily_message_limit": 7}, headers=ADMIN)
    assert quota.claim(user_id, 200).limit == 7


def test_an_override_beats_the_tier_on_the_next_claim(client, quota, user_id):
    client.put(
        f"/admin/api/users/{user_id}/quota",
        json=quota_body(tier="staff", daily_message_limit_override=500, reason="promo"),
        headers=ADMIN,
    )
    assert quota.claim(user_id, 200).limit == 500


def test_clearing_the_override_returns_the_reader_to_their_tier(client, quota, user_id):
    client.put(
        f"/admin/api/users/{user_id}/quota",
        json=quota_body(tier="staff", daily_message_limit_override=500, reason="promo"),
        headers=ADMIN,
    )
    client.put(f"/admin/api/users/{user_id}/quota", json=quota_body(tier="staff"), headers=ADMIN)
    assert quota.overrides.get(user_id) is None
    assert quota.claim(user_id, 200).limit == 200


def test_a_windowed_override_round_trips_and_expires_on_read(client, quota, user_id):
    client.put(
        f"/admin/api/users/{user_id}/quota",
        json=quota_body(
            daily_message_limit_override=500,
            override_expires_at="2030-09-30T00:00:00Z",
            reason="promo",
        ),
        headers=ADMIN,
    )
    assert quota.claim(user_id, 200).limit == 500
    assert quota.status(user_id, 200).override_expires_at

    # An ISO STRING from the route, compared against a datetime at claim time.
    # Storing one and comparing the other raised TypeError until 2026-09-04.
    quota.overrides[user_id]["expires_at"] = "2020-01-01T00:00:00Z"
    assert quota.claim(user_id, 200).limit == 200
    assert quota.status(user_id, 200).override_expires_at is None


# ── the quota route's own contract ───────────────────────────────────────────


def test_a_partial_body_is_refused(client, user_id):
    """The asymmetric nulls make a partial PUT dangerous, so it is not allowed.

    `tier: null` means "leave it alone" but `daily_message_limit_override: null`
    means "clear it" — so a body omitting the override would silently delete one.
    """
    response = client.put(
        f"/admin/api/users/{user_id}/quota", json={"tier": "staff"}, headers=ADMIN
    )
    assert response.status_code == 400


def test_setting_an_override_requires_its_own_reason_code(client, user_id):
    """NOT the existing `reason_required`, whose string is about disabling chat."""
    response = client.put(
        f"/admin/api/users/{user_id}/quota",
        json=quota_body(daily_message_limit_override=50),
        headers=ADMIN,
    )
    assert response.status_code == 422
    assert response.get_json()["error"] == "quota_reason_required"


def test_clearing_an_override_needs_no_reason(client, user_id):
    """The burden belongs on the restrictive act, as with the disable reason."""
    assert (
        client.put(
            f"/admin/api/users/{user_id}/quota", json=quota_body(tier="free"), headers=ADMIN
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        (quota_body(daily_message_limit_override=-5, reason="x"), 422, "invalid_limit"),
        (quota_body(daily_message_limit_override=True, reason="x"), 422, "invalid_limit"),
        (quota_body(tier="ghost", reason="x"), 409, "no_such_tier"),
        (quota_body(override_starts_at=7, reason="x"), 422, "invalid_window"),
    ],
)
def test_the_quota_route_refuses_bad_input(client, user_id, body, status, code):
    response = client.put(f"/admin/api/users/{user_id}/quota", json=body, headers=ADMIN)
    assert response.status_code == status
    assert response.get_json()["error"] == code


def test_an_unknown_account_is_refused(client):
    response = client.put(
        "/admin/api/users/00000000-0000-0000-0000-0000000000ff/quota",
        json=quota_body(tier="staff"),
        headers=ADMIN,
    )
    assert response.status_code == 409
    assert response.get_json()["error"] == "no_such_account"


# ── the audit trail ──────────────────────────────────────────────────────────


def test_every_mutation_is_audited(client, user_id):
    client.post("/admin/api/tiers", json=tier_body(daily_message_limit=50), headers=ADMIN)
    client.patch("/admin/api/tiers/promo", json={"daily_message_limit": 60}, headers=ADMIN)
    client.delete("/admin/api/tiers/promo", headers=ADMIN)
    client.put(
        f"/admin/api/users/{user_id}/quota",
        json=quota_body(daily_message_limit_override=50, reason="a stated reason"),
        headers=ADMIN,
    )
    actions = {
        e["action"] for e in client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]
    }
    assert {"tier.create", "tier.update", "tier.delete", "user.quota_override_change"} <= actions


def test_the_override_reason_is_recorded_as_the_audit_note(client, user_id):
    client.put(
        f"/admin/api/users/{user_id}/quota",
        json=quota_body(daily_message_limit_override=50, reason="conference week"),
        headers=ADMIN,
    )
    entries = client.get("/admin/api/audit", headers=ADMIN).get_json()["entries"]
    row = next(e for e in entries if e["action"] == "user.quota_override_change")
    assert row["note"] == "conference week"
    assert row["after"]["daily_message_limit"] == 50
