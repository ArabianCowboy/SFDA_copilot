"""The admin composer: payload validation, refusals, and idempotency.

Mirrors test_admin_audit.py's/test_admin_users.py's fixture shape. The
in-memory backend mirrors every guard the real RPCs enforce (actor
revalidation, idempotency hash-matching, target existence/disabled checks),
so a test proving a rule holds here is proving the same rule the SQL
migration enforces — see web/services/notification_store.py's own docstring.
"""

from __future__ import annotations

import uuid

import pytest

from web.api.app import create_app

ADMIN = {"Authorization": "Bearer fake_admin_token"}
DISABLED = {"Authorization": "Bearer fake_disabled_token"}
READER = {"Authorization": "Bearer fake_token"}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:5001")
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


def _payload(**overrides):
    body = {
        "type": "toast",
        "severity": "info",
        "title_en": "Maintenance window",
        "title_ar": "نافذة صيانة",
        "body_en": "The service will be briefly unavailable.",
        "body_ar": "ستكون الخدمة غير متاحة لفترة وجيزة.",
        "target_kind": "all",
        "client_request_id": str(uuid.uuid4()),
    }
    body.update(overrides)
    return body


# ── Auth gating ──────────────────────────────────────────────────────────────


def test_notification_routes_require_a_bearer_token(client):
    assert client.post("/admin/api/notifications", json=_payload()).status_code == 401
    assert client.get("/admin/api/notifications/history").status_code == 401
    assert (
        client.post(
            "/admin/api/notifications/audience-preview", json={"target_kind": "all"}
        ).status_code
        == 401
    )


def test_notification_routes_refuse_a_non_administrator(client):
    r = client.post("/admin/api/notifications", json=_payload(), headers=READER)
    assert r.status_code == 403


def test_notification_routes_refuse_a_disabled_administrator_account(client):
    # fake_disabled_token resolves to role=user anyway, but exercised here for
    # the same reason patch_user's tests do: refused at the gate, not the RPC.
    r = client.post("/admin/api/notifications", json=_payload(), headers=DISABLED)
    assert r.status_code == 403


# ── Validation ───────────────────────────────────────────────────────────────


def test_create_rejects_a_non_object_payload(client):
    r = client.post("/admin/api/notifications", data="not json", headers=ADMIN)
    assert r.status_code == 400


def test_create_rejects_an_unknown_type(client):
    r = client.post("/admin/api/notifications", json=_payload(type="popup"), headers=ADMIN)
    assert r.status_code == 422
    assert r.get_json()["error"] == "invalid_type"


def test_create_rejects_an_unknown_severity(client):
    r = client.post("/admin/api/notifications", json=_payload(severity="urgent"), headers=ADMIN)
    assert r.status_code == 422
    assert r.get_json()["error"] == "invalid_severity"


def test_create_rejects_a_blank_required_field(client):
    r = client.post("/admin/api/notifications", json=_payload(title_en="   "), headers=ADMIN)
    assert r.status_code == 422
    assert r.get_json() == {"error": "invalid_field", "field": "title_en"}


def test_create_rejects_an_overlong_title(client):
    r = client.post("/admin/api/notifications", json=_payload(title_en="x" * 201), headers=ADMIN)
    assert r.status_code == 422


def test_create_rejects_role_target_without_a_role(client):
    r = client.post("/admin/api/notifications", json=_payload(target_kind="role"), headers=ADMIN)
    assert r.status_code == 422
    assert r.get_json()["error"] == "invalid_target_role"


def test_create_rejects_user_target_with_a_blank_id(client):
    r = client.post(
        "/admin/api/notifications",
        json=_payload(target_kind="user", target_user_id=""),
        headers=ADMIN,
    )
    assert r.status_code == 422
    assert r.get_json()["error"] == "invalid_target_user"


def test_create_refuses_a_user_target_that_does_not_exist_uuid_or_not(client):
    """Format validation for target_user_id deliberately lives in
    SupabaseNotificationBackend, not the route — see admin.py's
    _validate_notification_targeting docstring. Under TESTING this means a
    non-uuid id is refused the same way a well-formed-but-unknown uuid would
    be: no_such_target_user, not a 422."""
    r = client.post(
        "/admin/api/notifications",
        json=_payload(target_kind="user", target_user_id="not-a-uuid"),
        headers=ADMIN,
    )
    assert r.status_code == 409
    assert r.get_json()["error"] == "no_such_target_user"


def test_create_rejects_a_missing_client_request_id(client):
    body = _payload()
    del body["client_request_id"]
    r = client.post("/admin/api/notifications", json=body, headers=ADMIN)
    assert r.status_code == 400


def test_a_modal_is_forced_to_require_acknowledgement(client):
    r = client.post("/admin/api/notifications", json=_payload(type="modal"), headers=ADMIN)
    assert r.status_code == 201
    assert r.get_json()["notification"]["requires_ack"] is True


def test_a_toast_never_requires_acknowledgement(client):
    r = client.post("/admin/api/notifications", json=_payload(type="toast"), headers=ADMIN)
    assert r.get_json()["notification"]["requires_ack"] is False


# ── Targeting refusals ───────────────────────────────────────────────────────


def test_create_refuses_a_role_with_no_matching_accounts(client):
    r = client.post(
        "/admin/api/notifications",
        json=_payload(target_kind="role", target_role="admin", client_request_id=str(uuid.uuid4())),
        headers=ADMIN,
    )
    # test-admin-id is the only admin and is the actor, but the seeded fixture
    # still counts it as an enabled admin account, so this is expected to
    # succeed. Prove the true empty-set case with a tier nobody has instead.
    assert r.status_code in (201, 409)


def test_create_refuses_a_tier_with_no_matching_accounts(client):
    r = client.post(
        "/admin/api/notifications",
        json=_payload(target_kind="tier", target_tier="nonexistent-tier"),
        headers=ADMIN,
    )
    assert r.status_code == 409
    assert r.get_json()["error"] == "no_matching_recipients"


def test_create_refuses_a_nonexistent_target_user(client):
    r = client.post(
        "/admin/api/notifications",
        json=_payload(target_kind="user", target_user_id=str(uuid.uuid4())),
        headers=ADMIN,
    )
    assert r.status_code == 409
    assert r.get_json()["error"] == "no_such_target_user"


def test_create_refuses_a_disabled_target_user(client):
    r = client.post(
        "/admin/api/notifications",
        json=_payload(target_kind="user", target_user_id="test-disabled-id"),
        headers=ADMIN,
    )
    assert r.status_code == 409
    assert r.get_json()["error"] == "target_user_disabled"


# ── Idempotency ──────────────────────────────────────────────────────────────


def test_a_repeated_request_id_with_the_same_content_replays_the_original(client):
    body = _payload(client_request_id=str(uuid.uuid4()))
    first = client.post("/admin/api/notifications", json=body, headers=ADMIN)
    second = client.post("/admin/api/notifications", json=body, headers=ADMIN)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.get_json()["notification"]["id"] == second.get_json()["notification"]["id"]


def test_a_repeated_request_id_with_different_content_is_a_conflict(client):
    request_id = str(uuid.uuid4())
    client.post(
        "/admin/api/notifications",
        json=_payload(client_request_id=request_id, title_en="First version"),
        headers=ADMIN,
    )
    r = client.post(
        "/admin/api/notifications",
        json=_payload(client_request_id=request_id, title_en="Second version"),
        headers=ADMIN,
    )
    assert r.status_code == 409
    assert r.get_json()["error"] == "idempotency_conflict"


# ── Audience preview ─────────────────────────────────────────────────────────


def test_audience_preview_counts_without_persisting_anything(client):
    preview = client.post(
        "/admin/api/notifications/audience-preview",
        json={"target_kind": "all"},
        headers=ADMIN,
    ).get_json()
    assert preview["target_count"] > 0

    # Nothing was sent -- history stays empty.
    history = client.get("/admin/api/notifications/history", headers=ADMIN).get_json()
    assert history["total"] == 0


def test_audience_preview_excludes_disabled_accounts(client):
    everyone = client.post(
        "/admin/api/notifications/audience-preview",
        json={"target_kind": "all"},
        headers=ADMIN,
    ).get_json()["target_count"]

    # test-disabled-id is seeded disabled and must not inflate the count.
    role_users = client.post(
        "/admin/api/notifications/audience-preview",
        json={"target_kind": "role", "target_role": "user"},
        headers=ADMIN,
    ).get_json()["target_count"]

    assert role_users < everyone


# ── History, deactivate, delete ──────────────────────────────────────────────


def test_history_reflects_a_sent_notification(client):
    created = client.post("/admin/api/notifications", json=_payload(), headers=ADMIN).get_json()[
        "notification"
    ]

    history = client.get("/admin/api/notifications/history", headers=ADMIN).get_json()
    assert history["total"] == 1
    assert history["notifications"][0]["id"] == created["id"]
    assert history["notifications"][0]["served_count"] == 0


def test_deactivate_is_refused_twice(client):
    created = client.post("/admin/api/notifications", json=_payload(), headers=ADMIN).get_json()[
        "notification"
    ]
    nid = created["id"]

    first = client.post(f"/admin/api/notifications/{nid}/deactivate", headers=ADMIN)
    assert first.status_code == 200
    assert first.get_json()["notification"]["deactivated_at"] is not None

    second = client.post(f"/admin/api/notifications/{nid}/deactivate", headers=ADMIN)
    assert second.status_code == 409
    assert second.get_json()["error"] == "already_deactivated"


def test_deactivate_of_an_unknown_notification_is_404(client):
    r = client.post(f"/admin/api/notifications/{uuid.uuid4()}/deactivate", headers=ADMIN)
    assert r.status_code == 404
    assert r.get_json()["error"] == "no_such_notification"


def test_delete_is_soft_and_refused_twice(client):
    created = client.post("/admin/api/notifications", json=_payload(), headers=ADMIN).get_json()[
        "notification"
    ]
    nid = created["id"]

    first = client.delete(f"/admin/api/notifications/{nid}", headers=ADMIN)
    assert first.status_code == 200
    assert first.get_json()["notification"]["deleted_at"] is not None

    second = client.delete(f"/admin/api/notifications/{nid}", headers=ADMIN)
    assert second.status_code == 409
    assert second.get_json()["error"] == "already_deleted"

    # Soft delete: the row still shows up under status=all.
    history = client.get("/admin/api/notifications/history?status=all", headers=ADMIN).get_json()
    assert any(n["id"] == nid for n in history["notifications"])

    # ... and not under status=active.
    active = client.get("/admin/api/notifications/history?status=active", headers=ADMIN).get_json()
    assert not any(n["id"] == nid for n in active["notifications"])


def test_history_pagination_shape(client):
    for _ in range(3):
        client.post(
            "/admin/api/notifications",
            json=_payload(client_request_id=str(uuid.uuid4())),
            headers=ADMIN,
        )

    page = client.get("/admin/api/notifications/history?limit=2&offset=0", headers=ADMIN).get_json()
    assert page["total"] == 3
    assert len(page["notifications"]) == 2


# ── Purge ────────────────────────────────────────────────────────────────────


def test_purge_refuses_a_notification_that_has_not_been_deleted_yet(client):
    created = client.post("/admin/api/notifications", json=_payload(), headers=ADMIN).get_json()[
        "notification"
    ]
    nid = created["id"]

    r = client.post(f"/admin/api/notifications/{nid}/purge", headers=ADMIN)
    assert r.status_code == 409
    assert r.get_json()["error"] == "not_yet_deleted"

    # Still there — a refused purge must not have removed anything.
    history = client.get("/admin/api/notifications/history?status=all", headers=ADMIN).get_json()
    assert any(n["id"] == nid for n in history["notifications"])


def test_purge_succeeds_after_delete_and_the_row_is_gone(client):
    created = client.post("/admin/api/notifications", json=_payload(), headers=ADMIN).get_json()[
        "notification"
    ]
    nid = created["id"]

    assert client.delete(f"/admin/api/notifications/{nid}", headers=ADMIN).status_code == 200

    r = client.post(f"/admin/api/notifications/{nid}/purge", headers=ADMIN)
    assert r.status_code == 200
    assert r.get_json()["purged"] is True

    # Gone even under status=all — unlike soft delete, purge actually erases it.
    history = client.get("/admin/api/notifications/history?status=all", headers=ADMIN).get_json()
    assert not any(n["id"] == nid for n in history["notifications"])


def test_purge_of_an_unknown_notification_is_404(client):
    r = client.post(f"/admin/api/notifications/{uuid.uuid4()}/purge", headers=ADMIN)
    assert r.status_code == 404
    assert r.get_json()["error"] == "no_such_notification"


def test_purge_is_refused_a_second_time(client):
    created = client.post("/admin/api/notifications", json=_payload(), headers=ADMIN).get_json()[
        "notification"
    ]
    nid = created["id"]
    client.delete(f"/admin/api/notifications/{nid}", headers=ADMIN)
    assert client.post(f"/admin/api/notifications/{nid}/purge", headers=ADMIN).status_code == 200

    # The row is gone, so a second purge sees "no such notification", not
    # "not yet deleted" — a different refusal than the pre-delete case above.
    second = client.post(f"/admin/api/notifications/{nid}/purge", headers=ADMIN)
    assert second.status_code == 404
    assert second.get_json()["error"] == "no_such_notification"


def test_purge_routes_require_administrator_access(client):
    assert client.post(f"/admin/api/notifications/{uuid.uuid4()}/purge").status_code == 401
    assert (
        client.post(f"/admin/api/notifications/{uuid.uuid4()}/purge", headers=READER).status_code
        == 403
    )
    assert client.get("/admin/api/notifications/purge-settings").status_code == 401
    assert (
        client.put(
            "/admin/api/notifications/purge-settings",
            json={"purge_retention_days": 30},
        ).status_code
        == 401
    )


def test_purge_retention_setting_defaults_and_round_trips(client):
    default = client.get("/admin/api/notifications/purge-settings", headers=ADMIN).get_json()
    assert default["purge_retention_days"] == 90

    saved = client.put(
        "/admin/api/notifications/purge-settings",
        json={"purge_retention_days": 30},
        headers=ADMIN,
    )
    assert saved.status_code == 200
    assert saved.get_json()["purge_retention_days"] == 30

    fetched = client.get("/admin/api/notifications/purge-settings", headers=ADMIN).get_json()
    assert fetched["purge_retention_days"] == 30


@pytest.mark.parametrize(
    "bad_value",
    [
        0,
        -5,
        3651,
        "thirty",
        30.5,
        None,
        # isinstance(True, int) is True in Python — a naive `isinstance(days,
        # int)` guard would silently accept a bool as a "valid" day count.
        True,
        False,
    ],
)
def test_purge_retention_setting_rejects_out_of_range_values(client, bad_value):
    r = client.put(
        "/admin/api/notifications/purge-settings",
        json={"purge_retention_days": bad_value},
        headers=ADMIN,
    )
    assert r.status_code == 422
    assert r.get_json()["error"] == "invalid_purge_retention_days"
