"""A refusal from the settings RPC reaches the operator as 409, not 500.

`admin_write_settings` had no actor check at all until
`20260828001543_admin_rpcs_require_an_enabled_actor.sql` gave it one, and
`SupabaseAdminBackend.put_settings` was correspondingly the one writer with no
`try`/`except` — the two matched, so nothing was wrong. Adding the refusal
without adding the handler would have broken that pairing, and not on one
surface but three: the generation-settings page, the registrations-pause control
and the notification purge-retention control all reach `put_settings`, and none
of their routes caught `AdminActionRefused`.

These drive each route with a service that raises, which is the only way to
reach those handlers — under `?testing=true` the in-memory backend is seeded
with a valid administrator, so the gate legitimately never refuses. The point is
not to prove the database raises (it does; that belongs in
`supabase/tests/`) but that the three routes translate it rather than letting it
fall through to a generic 500.

The registrations-pause case is the one worth reading. Its route inspects
`errors[0].code` and answers `invalid_signup_enabled` for anything that is not
`storage_unavailable` — so a refusal that fell through to that branch would tell
a demoted administrator their *payload* was malformed.
"""

from __future__ import annotations

import pytest

from web.api.app import create_app
from web.services.admin_store import AdminActionRefused

ADMIN = {"Authorization": "Bearer fake_admin_token"}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:5001")
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


class _RefusingSettingsService:
    """Stands in for SettingsService, refusing the way the RPC now can."""

    def update(self, *_args, **_kwargs):
        raise AdminActionRefused("actor_no_longer_administrator")

    def set_signup_enabled(self, *_args, **_kwargs):
        raise AdminActionRefused("actor_no_longer_administrator")

    # Read paths the settings route touches before it writes.
    def snapshot(self):
        return {}

    def effective(self):
        return {}


def test_a_refused_generation_settings_save_is_409(app, client):
    app.config["settings_service"] = _RefusingSettingsService()

    response = client.put("/admin/api/settings", json={"model": "gpt-4o"}, headers=ADMIN)

    assert response.status_code == 409
    assert response.get_json() == {"error": "actor_no_longer_administrator"}


def test_a_refused_registrations_pause_is_409_not_a_payload_error(app, client):
    app.config["settings_service"] = _RefusingSettingsService()

    response = client.put("/admin/api/registrations", json={"signup_enabled": False}, headers=ADMIN)

    assert response.status_code == 409
    # Specifically NOT invalid_signup_enabled: the payload was fine.
    assert response.get_json() == {"error": "actor_no_longer_administrator"}


def test_a_refused_purge_retention_change_is_409(app, client, monkeypatch):
    from web.services import notification_store

    def _refuse(*_args, **_kwargs):
        raise AdminActionRefused("actor_no_longer_administrator")

    monkeypatch.setattr(notification_store, "set_purge_retention_days", _refuse)

    response = client.put(
        "/admin/api/notifications/purge-settings",
        json={"purge_retention_days": 30},
        headers=ADMIN,
    )

    assert response.status_code == 409
    assert response.get_json() == {"error": "actor_no_longer_administrator"}
