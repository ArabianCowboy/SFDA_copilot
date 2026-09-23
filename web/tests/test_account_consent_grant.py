"""Consent grant route and server-stamped signup version (slice 1 of
docs/ARCHITECTURE.md#account-deletion-and-trust; reasoning in docs/archive/2026-09-18_account-and-trust.md D5, D6b).

The browser used to send `marketing_consent_policy_version` itself — from the
account toggle and from signup — and the trigger validated only its shape, so
a client could stamp the current version without ever seeing the prompt. Now
the version is server-supplied in both places: the grant route stamps
`PRIVACY_POLICY_VERSION`, and signup overwrites whatever the client sent.

Each test below fails against today's code, for the reason its own comment
gives: the route did not exist (404), and signup forwarded the client's
version verbatim.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from web.api.app import PRIVACY_POLICY_VERSION, create_app

AUTH = {"Authorization": "Bearer fake_token"}
DISABLED = {"Authorization": "Bearer fake_disabled_token"}


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


def _admin_client():
    client = MagicMock()
    client.rpc.return_value.execute.return_value = None
    return client


# ── POST /account/api/consent/grant ─────────────────────────────────────────


def test_grant_requires_a_bearer_token(client):
    response = client.post("/account/api/consent/grant", json={"language": "en"})
    assert response.status_code == 401


def test_grant_is_refused_for_a_disabled_account(client):
    """A disabled account may withdraw consent but never grant it. The refusal
    comes from `account_bp._gate` (via `_authenticate_request`'s
    `account_disabled`), not from a second check in the view — so this asserts
    the gate, with no admin-client patch: the route must refuse before any
    privileged call exists to make."""
    response = client.post("/account/api/consent/grant", json={"language": "en"}, headers=DISABLED)
    assert response.status_code == 403
    assert response.get_json() == {"error": "account_disabled"}


def test_grant_stamps_the_server_version_and_ignores_the_client(client):
    """The owner comes from `g.identity` and the version from
    `PRIVACY_POLICY_VERSION` — a forged version and a forged user id in the
    body change nothing. Against today's code this is a 404: the route did
    not exist and the toggle wrote PostgREST directly."""
    admin = _admin_client()
    with patch("web.api.account.get_supabase_admin", return_value=admin):
        response = client.post(
            "/account/api/consent/grant",
            json={
                "language": "en",
                "surface": "account",
                "marketing_consent_policy_version": "forged-by-client",
                "user_id": "someone-else-entirely",
            },
            headers=AUTH,
        )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    admin.rpc.assert_called_once_with(
        "grant_marketing_consent",
        {
            "p_owner_id": "test-user-id",
            "p_policy_version": PRIVACY_POLICY_VERSION,
            "p_language": "en",
            "p_surface": "account",
        },
    )


def test_grant_rejects_an_unknown_language(client):
    """`handle_new_user` would degrade this grant to a decline downstream;
    the route refuses it up front instead, so a typo'd language never reads
    as a recorded grant."""
    admin = _admin_client()
    with patch("web.api.account.get_supabase_admin", return_value=admin):
        response = client.post("/account/api/consent/grant", json={"language": "zz"}, headers=AUTH)

    assert response.status_code == 400
    admin.rpc.assert_not_called()


def test_grant_without_an_admin_client_is_a_503_not_a_500(client):
    """`get_supabase_admin()` answers None under TESTING (and when no service
    key is configured) — the route reports an unavailable dependency, not a
    crash and not a refusal that would read as the reader's fault."""
    response = client.post("/account/api/consent/grant", json={"language": "ar"}, headers=AUTH)
    assert response.status_code == 503
    assert response.get_json() == {"error": "consent_unavailable"}


def test_a_failing_grant_rpc_is_a_503(client):
    admin = _admin_client()
    admin.rpc.return_value.execute.side_effect = RuntimeError("db unreachable")
    with patch("web.api.account.get_supabase_admin", return_value=admin):
        response = client.post("/account/api/consent/grant", json={"language": "en"}, headers=AUTH)
    assert response.status_code == 503


# ── POST /auth/signup stamps the version ────────────────────────────────────


def _signup_client():
    supabase = MagicMock()
    supabase.auth.sign_up.return_value = MagicMock(
        error=None, user=MagicMock(id="u1", email="new@example.com")
    )
    return supabase


def test_signup_overwrites_a_client_sent_version_with_the_server_one(client):
    """Against today's code the forged string travelled verbatim into
    `raw_user_meta_data` (and `handle_new_user` accepted it on shape alone).
    Now the client's value is dropped and the server's stamped."""
    supabase = _signup_client()
    with patch("web.api.auth.get_supabase", return_value=supabase):
        response = client.post(
            "/auth/signup",
            json={
                "email": "new@example.com",
                "password": "ValidPass1",
                "first_name": "Sara",
                "marketing_consent": True,
                "marketing_consent_language": "en",
                "marketing_consent_policy_version": "forged-by-client",
            },
        )

    assert response.status_code == 201
    metadata = supabase.auth.sign_up.call_args[0][0]["options"]["data"]
    assert metadata["marketing_consent"] is True
    assert metadata["marketing_consent_policy_version"] == PRIVACY_POLICY_VERSION


def test_signup_without_consent_carries_no_version_at_all(client):
    """A declined consent is not a grant under a version — nothing to stamp,
    and any client-sent value must not survive either."""
    supabase = _signup_client()
    with patch("web.api.auth.get_supabase", return_value=supabase):
        response = client.post(
            "/auth/signup",
            json={
                "email": "new@example.com",
                "password": "ValidPass1",
                "first_name": "Cher",
                "marketing_consent": False,
                "marketing_consent_policy_version": "forged-by-client",
            },
        )

    assert response.status_code == 201
    metadata = supabase.auth.sign_up.call_args[0][0]["options"]["data"]
    assert metadata["marketing_consent"] is False
    assert "marketing_consent_policy_version" not in metadata
