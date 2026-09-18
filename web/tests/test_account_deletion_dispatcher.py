"""The deletion half of the auth-admin seam: delete, global sign-out, exists.

Slice 2a of docs/account-and-trust-plan.md. Each test fails against today's
code — ``SupabaseAuthAdminDispatcher`` and ``InMemoryAuthAdminDispatcher``
have no ``delete_user`` / ``sign_out_all`` / ``user_exists`` until this
slice, so every one of these raises ``AttributeError`` before it.

The provider boundary (``client.auth.admin.*``) is a recording fake, not the
dispatcher itself: what is asserted is the dispatcher's own behaviour — which
SDK call it makes, how it classifies the failure, and what the double
records.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from supabase import AuthApiError, AuthRetryableError
from web.services.auth_admin import (
    AuthAdminRefused,
    InMemoryAuthAdminDispatcher,
    SupabaseAuthAdminDispatcher,
)


def _not_found() -> AuthApiError:
    return AuthApiError("User not found", 404, "user_not_found")


def _fake_client(admin: object) -> SimpleNamespace:
    return SimpleNamespace(auth=SimpleNamespace(admin=admin))


class _RecordingAdmin:
    """Stands in for the SDK's admin namespace: records calls, replays one
    configured side effect."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.side_effect: Exception | None = None
        self.get_result: object = SimpleNamespace(user=SimpleNamespace(id="u-1"))

    def delete_user(self, user_id: str) -> None:
        self.calls.append(("delete_user", user_id))
        if self.side_effect is not None:
            raise self.side_effect

    def sign_out(self, jwt: str, scope: str = "global") -> None:
        self.calls.append(("sign_out", jwt, scope))
        if self.side_effect is not None:
            raise self.side_effect

    def get_user_by_id(self, user_id: str) -> object:
        self.calls.append(("get_user_by_id", user_id))
        if self.side_effect is not None:
            raise self.side_effect
        return self.get_result


def _dispatcher(admin: _RecordingAdmin) -> SupabaseAuthAdminDispatcher:
    return SupabaseAuthAdminDispatcher(_fake_client(admin))  # type: ignore[arg-type]


# ── delete_user ──────────────────────────────────────────────────────────


def test_delete_user_calls_the_admin_delete_endpoint():
    admin = _RecordingAdmin()
    _dispatcher(admin).delete_user("u-1")
    assert admin.calls == [("delete_user", "u-1")]


def test_delete_user_treats_user_not_found_as_success():
    """The user is gone, which is the goal — not a failure. Letting this
    raise would flip a completed deletion to failed."""
    admin = _RecordingAdmin()
    admin.side_effect = _not_found()
    assert _dispatcher(admin).delete_user("u-1") is None


def test_delete_user_timeout_is_ambiguous_not_failed():
    admin = _RecordingAdmin()
    admin.side_effect = httpx.ReadTimeout("read timed out")
    with pytest.raises(AuthAdminRefused) as exc_info:
        _dispatcher(admin).delete_user("u-1")
    assert exc_info.value.ambiguous is True


def test_delete_user_definitive_refusal_is_not_ambiguous():
    admin = _RecordingAdmin()
    admin.side_effect = AuthApiError("forbidden", 403, "not_admin")
    with pytest.raises(AuthAdminRefused) as exc_info:
        _dispatcher(admin).delete_user("u-1")
    assert exc_info.value.code == "auth_admin_failed"
    assert exc_info.value.ambiguous is False


# ── sign_out_all ─────────────────────────────────────────────────────────


def test_sign_out_all_revokes_globally_by_jwt():
    """The SDK revokes by presented token, not by user id — global scope on
    that JWT is what kills every session of the account."""
    admin = _RecordingAdmin()
    _dispatcher(admin).sign_out_all("session-jwt")
    assert admin.calls == [("sign_out", "session-jwt", "global")]


def test_sign_out_all_timeout_is_ambiguous():
    admin = _RecordingAdmin()
    admin.side_effect = AuthRetryableError("try again", 503)
    with pytest.raises(AuthAdminRefused) as exc_info:
        _dispatcher(admin).sign_out_all("session-jwt")
    assert exc_info.value.ambiguous is True


# ── user_exists ──────────────────────────────────────────────────────────


def test_user_exists_true_while_gotrue_returns_the_user():
    admin = _RecordingAdmin()
    assert _dispatcher(admin).user_exists("u-1") is True


def test_user_exists_false_when_gotrue_reports_not_found():
    admin = _RecordingAdmin()
    admin.side_effect = _not_found()
    assert _dispatcher(admin).user_exists("u-1") is False


def test_user_exists_timeout_raises_ambiguous():
    admin = _RecordingAdmin()
    admin.side_effect = httpx.ReadTimeout("read timed out")
    with pytest.raises(AuthAdminRefused) as exc_info:
        _dispatcher(admin).user_exists("u-1")
    assert exc_info.value.ambiguous is True


# ── the in-memory double ─────────────────────────────────────────────────


def test_double_delete_user_records_and_removes_the_row():
    """A successful call here must leave the demo state genuinely changed,
    per the double's own contract — not only record that a call happened."""
    users = [{"id": "u-1", "email": "a@b.c"}]
    double = InMemoryAuthAdminDispatcher(users)
    double.delete_user("u-1")
    assert double.deleted == ["u-1"]
    assert users == []
    assert double.user_exists("u-1") is False


def test_double_delete_user_treats_configured_not_found_as_success():
    double = InMemoryAuthAdminDispatcher([{"id": "u-1", "email": "a@b.c"}])
    double.refuse_with = "no_such_account"
    assert double.delete_user("u-1") is None
    assert double.deleted == ["u-1"]


def test_double_sign_out_all_records_the_jwt():
    double = InMemoryAuthAdminDispatcher()
    double.sign_out_all("session-jwt")
    assert double.signed_out == ["session-jwt"]


def test_double_refusal_hook_covers_the_new_methods():
    double = InMemoryAuthAdminDispatcher([{"id": "u-1", "email": "a@b.c"}])
    double.refuse_with = "auth_admin_unreachable"
    double.refuse_ambiguous = True
    for call in (
        lambda: double.delete_user("u-1"),
        lambda: double.sign_out_all("session-jwt"),
        lambda: double.user_exists("u-1"),
    ):
        with pytest.raises(AuthAdminRefused) as exc_info:
            call()
        assert exc_info.value.ambiguous is True
    assert double.deleted == []
    assert double.signed_out == []
