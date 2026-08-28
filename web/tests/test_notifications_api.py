"""The reader-facing Notification Center: gating, targeting isolation, and
the mark-read eligibility/action-type guards.

`notifications_mark_read`'s whole point is that a reader cannot fabricate a
receipt for a notification they were never targeted by, and cannot dismiss a
modal or acknowledge a toast — these tests exercise that guard through the
Flask route exactly the way a browser would reach it, against the in-memory
backend that mirrors the real RPC's checks (see
web/services/notification_store.py's own docstring for why one shared
backend, not two, is what makes this assertion meaningful under TESTING).
"""

from __future__ import annotations

import uuid

import pytest

from web.api.app import create_app

ADMIN = {"Authorization": "Bearer fake_admin_token"}
READER_A = {"Authorization": "Bearer fake_token"}  # test-user-id
READER_B = {"Authorization": "Bearer fake_reader_b_token"}  # test-reader-b-id
# test-reader-b-id has an auth-bypass identity (_TESTING_IDENTITIES) but no
# seeded profile row in InMemoryAdminBackend, so it cannot be a notification
# target — user-targeting tests that need a second real profile use
# test-orphan-id instead (seeded, enabled, distinct from READER_A).


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:5001")
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


def _send(client, **overrides):
    body = {
        "type": "toast",
        "severity": "info",
        "title_en": "Title",
        "title_ar": "عنوان",
        "body_en": "Body",
        "body_ar": "نص",
        "target_kind": "all",
        "client_request_id": str(uuid.uuid4()),
    }
    body.update(overrides)
    return client.post("/admin/api/notifications", json=body, headers=ADMIN).get_json()[
        "notification"
    ]


# ── Auth gating ──────────────────────────────────────────────────────────────


def test_reader_routes_require_a_bearer_token(client):
    assert client.get("/api/notifications/active").status_code == 401
    assert client.get("/api/notifications/history").status_code == 401
    assert client.post("/api/notifications/mark-read", json={}).status_code == 401
    assert client.post("/api/notifications/mark-all-read").status_code == 401


# ── 'all' targeting reaches every reader ────────────────────────────────────


def test_an_all_targeted_notification_is_visible_to_any_signed_in_reader(client):
    _send(client, target_kind="all")

    active = client.get("/api/notifications/active", headers=READER_A).get_json()
    assert len(active["notifications"]) == 1
    assert active["notifications"][0]["title"] == "Title"


def test_language_resolves_server_side(client):
    _send(client, title_en="English title", title_ar="عنوان عربي")

    en = client.get("/api/notifications/active?lang=en", headers=READER_A).get_json()
    ar = client.get("/api/notifications/active?lang=ar", headers=READER_A).get_json()

    assert en["notifications"][0]["title"] == "English title"
    assert ar["notifications"][0]["title"] == "عنوان عربي"


# ── Targeting isolation ──────────────────────────────────────────────────────


def test_a_user_targeted_notification_is_invisible_to_everyone_else(client):
    _send(client, target_kind="user", target_user_id="test-user-id")

    mine = client.get("/api/notifications/active", headers=READER_A).get_json()
    assert len(mine["notifications"]) == 1

    someone_elses = client.get("/api/notifications/active", headers=READER_B).get_json()
    assert someone_elses["notifications"] == []


def test_a_role_targeted_notification_reaches_only_that_role(client):
    # test-admin-id is the only seeded admin; readers are role=user.
    _send(client, target_kind="role", target_role="admin")

    assert (
        client.get("/api/notifications/active", headers=READER_A).get_json()["notifications"] == []
    )


# ── mark-read: eligibility ───────────────────────────────────────────────────


def test_a_reader_cannot_fabricate_a_receipt_for_a_notification_never_targeted_to_them(client):
    """The specific gap adversarial review found and the plan's fix closes."""
    notification = _send(client, target_kind="user", target_user_id="test-user-id")

    r = client.post(
        "/api/notifications/mark-read",
        json={"notification_id": notification["id"], "action": "dismissed"},
        headers=READER_B,
    )
    assert r.status_code == 409
    assert r.get_json()["error"] == "not_a_recipient"


def test_the_actual_recipient_can_mark_it_read(client):
    notification = _send(client, target_kind="user", target_user_id="test-user-id")

    r = client.post(
        "/api/notifications/mark-read",
        json={"notification_id": notification["id"], "action": "dismissed"},
        headers=READER_A,
    )
    assert r.status_code == 200
    assert r.get_json()["dismissed_at"] is not None


def test_an_all_targeted_notification_can_be_marked_by_any_reader(client):
    notification = _send(client, target_kind="all")

    r = client.post(
        "/api/notifications/mark-read",
        json={"notification_id": notification["id"], "action": "read"},
        headers=READER_B,
    )
    assert r.status_code == 200


def test_mark_read_on_an_unknown_notification_is_404(client):
    r = client.post(
        "/api/notifications/mark-read",
        json={"notification_id": str(uuid.uuid4()), "action": "read"},
        headers=READER_A,
    )
    assert r.status_code == 404


# ── mark-read: action/type validity ──────────────────────────────────────────


def test_dismissed_is_refused_on_a_modal(client):
    notification = _send(client, type="modal", target_kind="all")

    r = client.post(
        "/api/notifications/mark-read",
        json={"notification_id": notification["id"], "action": "dismissed"},
        headers=READER_A,
    )
    assert r.status_code == 409
    assert r.get_json()["error"] == "action_type_mismatch"


def test_acknowledged_is_refused_on_a_toast(client):
    notification = _send(client, type="toast", target_kind="all")

    r = client.post(
        "/api/notifications/mark-read",
        json={"notification_id": notification["id"], "action": "acknowledged"},
        headers=READER_A,
    )
    assert r.status_code == 409
    assert r.get_json()["error"] == "action_type_mismatch"


def test_acknowledged_is_accepted_on_a_modal(client):
    notification = _send(client, type="modal", target_kind="all")

    r = client.post(
        "/api/notifications/mark-read",
        json={"notification_id": notification["id"], "action": "acknowledged"},
        headers=READER_A,
    )
    assert r.status_code == 200
    assert r.get_json()["acknowledged_at"] is not None


def test_mark_read_rejects_an_unknown_action(client):
    notification = _send(client, target_kind="all")

    r = client.post(
        "/api/notifications/mark-read",
        json={"notification_id": notification["id"], "action": "wave-hello"},
        headers=READER_A,
    )
    assert r.status_code == 400


# ── Visibility after dismissal/acknowledgement/deactivation ─────────────────


def test_a_dismissed_notification_drops_out_of_active(client):
    notification = _send(client, target_kind="all")
    client.post(
        "/api/notifications/mark-read",
        json={"notification_id": notification["id"], "action": "dismissed"},
        headers=READER_A,
    )

    active = client.get("/api/notifications/active", headers=READER_A).get_json()
    assert active["notifications"] == []


def test_a_deactivated_notification_drops_out_of_active_for_everyone(client):
    notification = _send(client, target_kind="all")
    client.post(f"/admin/api/notifications/{notification['id']}/deactivate", headers=ADMIN)

    active = client.get("/api/notifications/active", headers=READER_A).get_json()
    assert active["notifications"] == []


def test_dismissing_a_withdrawn_notification_is_refused(client):
    """A stale tab must not be able to dismiss what the operator retracted.

    The count is the reason. For a `requires_ack` modal — the type that exists
    so somebody can later demonstrate readers saw something — an
    acknowledgement count that includes acknowledgements of a withdrawn notice
    is worse than no count. `notifications_mark_read` therefore refuses
    dismissal and acknowledgement once the notification is deactivated, deleted
    or expired (RN003), and takes FOR SHARE on the row so the retraction cannot
    commit between the check and the write.
    """
    notification = _send(client, target_kind="all")
    client.post(f"/admin/api/notifications/{notification['id']}/deactivate", headers=ADMIN)

    response = client.post(
        "/api/notifications/mark-read",
        json={"notification_id": notification["id"], "action": "dismissed"},
        headers=READER_A,
    )

    assert response.status_code == 409
    assert response.get_json() == {"error": "notification_no_longer_active"}


def test_a_deleted_notification_refuses_every_action_including_read(client):
    """Deleted is stricter than deactivated, and the difference is deliberate.

    `notifications_list_history_for_reader` filters `deleted_at is null`, so a
    soft-deleted notification is in NO reader surface — a `read` receipt on one
    cannot be the reader action it claims to be, and it still counts, because
    `admin_purge_notification` reports read/dismissed/acknowledged totals in the
    audit row it writes before erasing everything. So engagement figures on a
    withdrawn notice could move between the delete and the purge, permanently,
    in the audit record.
    """
    notification = _send(client, target_kind="all")
    client.delete(f"/admin/api/notifications/{notification['id']}", headers=ADMIN)

    for action in ("read", "dismissed"):
        response = client.post(
            "/api/notifications/mark-read",
            json={"notification_id": notification["id"], "action": action},
            headers=READER_A,
        )
        assert response.status_code == 409, action
        assert response.get_json() == {"error": "notification_no_longer_active"}


def test_an_acknowledgement_of_a_withdrawn_modal_is_refused(client):
    """The case the whole lifecycle check exists for: `requires_ack` modals are
    the type that exists so somebody can later demonstrate readers saw
    something, so an acknowledgement count that includes a retracted notice is
    worse than no count."""
    notification = _send(client, type="modal", target_kind="all")
    client.post(f"/admin/api/notifications/{notification['id']}/deactivate", headers=ADMIN)

    response = client.post(
        "/api/notifications/mark-read",
        json={"notification_id": notification["id"], "action": "acknowledged"},
        headers=READER_A,
    )

    assert response.status_code == 409
    assert response.get_json() == {"error": "notification_no_longer_active"}


def test_a_withdrawn_notification_can_still_be_marked_read(client):
    """The deliberate asymmetry, so nobody "fixes" it into symmetry later.

    Marking an item read in a history list is reasonable long after it stopped
    being active — `notifications_list_history_for_reader` exists to show
    exactly that. Only the two display actions on a live notice are refused.
    """
    notification = _send(client, target_kind="all")
    client.post(f"/admin/api/notifications/{notification['id']}/deactivate", headers=ADMIN)

    response = client.post(
        "/api/notifications/mark-read",
        json={"notification_id": notification["id"], "action": "read"},
        headers=READER_A,
    )

    assert response.status_code == 200


def test_history_still_shows_a_dismissed_notification(client):
    notification = _send(client, target_kind="all")
    client.post(
        "/api/notifications/mark-read",
        json={"notification_id": notification["id"], "action": "dismissed"},
        headers=READER_A,
    )

    history = client.get("/api/notifications/history", headers=READER_A).get_json()
    assert any(n["id"] == notification["id"] for n in history["notifications"])
    row = next(n for n in history["notifications"] if n["id"] == notification["id"])
    assert row["dismissed_at"] is not None


# ── mark-all-read ─────────────────────────────────────────────────────────────


def test_mark_all_read_marks_every_eligible_unread_notification(client):
    _send(client, target_kind="all", client_request_id=str(uuid.uuid4()))
    _send(client, target_kind="all", client_request_id=str(uuid.uuid4()))
    _send(
        client,
        target_kind="user",
        target_user_id="test-orphan-id",
        client_request_id=str(uuid.uuid4()),
    )

    r = client.post("/api/notifications/mark-all-read", headers=READER_A)
    assert r.status_code == 200
    # Only the two 'all' notifications are eligible for reader A.
    assert r.get_json()["marked"] == 2


def test_mark_all_read_does_not_mark_a_notification_targeted_to_someone_else(client):
    _send(client, target_kind="user", target_user_id="test-orphan-id")

    r = client.post("/api/notifications/mark-all-read", headers=READER_A)
    assert r.get_json()["marked"] == 0
