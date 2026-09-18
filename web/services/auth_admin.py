"""Session revocation and email change, both through Supabase Auth Admin.

Cloned from ``account_recovery.py``'s shape (a refused-with-a-code exception,
a Protocol, a real dispatcher, an in-memory test double) but a genuinely
different seam: ``/recover`` is unauthenticated and reached with the anon
key; both actions here reach ``auth.admin.*`` and require the service-role
client, because there is no unauthenticated equivalent for either.

**Why password rotation is "revoke sessions".** GoTrue's Admin API has no
endpoint that revokes a user's sessions by id alone — confirmed against its
Go source (``internal/api/admin.go``, ``internal/models/sessions.go``). The
only thing that deletes every session/refresh-token row for a user is
``models.Logout``, and the only Admin API call that triggers it is a password
update with no session context (``PUT /admin/users/{id}`` with a ``password``
field). So this rotates the password to a value nobody — not even the
operator — ever sees, purely as a mechanism to force that side effect.

**Why the generated password is never returned, logged, or stored.** Same
principle ``account_recovery.py`` states for why it avoids
``auth.admin.generate_link``: a value that can authenticate as the reader is a
bearer credential, and the console's whole thesis is that an operator helps
without ever holding one.

**Why ``email_confirm: False`` on the email-change call does not lock the
account out.** Verified live against the real project (not assumed from
docs): ``SetEmail()`` changes ``auth.users.email`` unconditionally, and
``email_confirmed_at`` is only ever set by ``Confirm()``, which only runs when
``email_confirm`` is true. So an already-confirmed account keeps its
(now stale) ``email_confirmed_at`` and keeps signing in — what the call
actually leaves behind is an email identity whose ``email_verified`` is
``False`` for the new address, which is a display problem for the console to
show honestly (see ``admin_get_user``'s ``email_identity_verified`` column),
not a login problem.
"""

from __future__ import annotations

import logging
import secrets
import string
from typing import Protocol

import httpx

from supabase import AuthApiError, AuthRetryableError, Client
from web.utils.supabase_client import get_supabase_admin

logger = logging.getLogger(__name__)


class AuthAdminRefused(Exception):
    """Mirrors ``RecoveryRefused``: ``.code`` is the contract, ``.message`` is
    for the log only and must never reach a response or an audit note — a
    provider's raw English text is not something this surface repeats.

    ``.ambiguous`` distinguishes a definitive refusal (the provider understood
    the request and declined it — nothing happened) from a transport failure
    whose true outcome this process never learned (the request may have
    already committed server-side). Recording the second as an ordinary
    "failed" would be a false entry on the one surface whose entire purpose is
    to be trustworthy later.
    """

    def __init__(self, code: str, message: str = "", *, ambiguous: bool = False) -> None:
        super().__init__(message or code)
        self.code = code
        self.ambiguous = ambiguous


# Structured, definitive provider rejections: GoTrue understood the request
# and refused it, so nothing happened. Codes not listed here still count as
# definitive (an AuthApiError is always a response GoTrue actually sent) —
# they fall through to the generic `auth_admin_failed` in the function below.
_DEFINITIVE_CODES = {
    "email_exists": "email_already_registered",
    "user_not_found": "no_such_account",
}


def classify_admin_failure(error: Exception) -> tuple[str, bool]:
    """Map a provider exception to ``(code, is_ambiguous)``.

    Three disjoint failure shapes, verified against the vendored
    ``supabase_auth`` SDK rather than assumed:

    * :class:`AuthApiError` — GoTrue answered with a structured error. Always
      definitive: the request was received and understood.
    * :class:`AuthRetryableError` — GoTrue answered with a 502/503/504/
      520-524/530. Ambiguous: the request reached the server, which is not
      the same as the server never having acted on it.
    * a raw :class:`httpx.HTTPError` — the SDK does not wrap transport-level
      failures. Split further: a connect-stage failure (DNS, refused
      connection) never reached GoTrue at all and is *not* ambiguous; any
      other transport error (a read timeout, a dropped response) means the
      request was sent and its outcome is genuinely unknown.
    """
    if isinstance(error, AuthApiError):
        return _DEFINITIVE_CODES.get(error.code or "", "auth_admin_failed"), False
    if isinstance(error, AuthRetryableError):
        return "auth_admin_unreachable", True
    if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout)):
        return "auth_admin_unreachable", False
    if isinstance(error, httpx.HTTPError):
        return "auth_admin_unreachable", True
    return "auth_admin_failed", False


# 32 characters, comfortably under bcrypt's 72-byte input ceiling even with
# multi-byte punctuation, with each character class present at least once.
# This reduces the chance a project's password-strength policy rejects it —
# it does not guarantee acceptance against every possible future policy, and
# a rejection is still handled honestly by `classify_admin_failure` above
# rather than assumed away.
_PASSWORD_LENGTH = 32
_SYMBOLS = "!@#$%^&*()-_=+"
_PASSWORD_ALPHABET = string.ascii_letters + string.digits + _SYMBOLS


def _generate_revocation_password() -> str:
    """A value that exists only for the duration of one call. Never logged,
    stored, or returned — see the module docstring."""
    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(_SYMBOLS),
    ]
    rest = [secrets.choice(_PASSWORD_ALPHABET) for _ in range(_PASSWORD_LENGTH - len(required))]
    pool = required + rest
    # Fisher-Yates on the same CSPRNG source as secrets.choice, so the fixed
    # positions of `required` don't leak into the output as a pattern.
    for i in range(len(pool) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        pool[i], pool[j] = pool[j], pool[i]
    return "".join(pool)


class AuthAdminDispatcher(Protocol):
    """Calls that must go through Supabase Auth Admin (service-role) and no
    other seam. Raises :class:`AuthAdminRefused` on any failure."""

    def revoke_sessions(self, user_id: str) -> None: ...

    def change_email(self, user_id: str, new_email: str) -> None: ...

    def delete_user(self, user_id: str) -> None:
        """Delete the GoTrue user outright. A provider ``user_not_found``
        (``no_such_account``) is SUCCESS, not failure — the user is gone,
        which is the goal — so it returns normally instead of raising."""

    def sign_out_all(self, jwt: str) -> None:
        """Revoke every session of the user that JWT belongs to, without
        touching the password and without banning. Takes the SESSION JWT,
        not a user id: the pinned SDK's ``sign_out(jwt, scope)`` revokes by
        presented token, and there is no admin call that signs out by id
        alone. The caller passes the requesting session's token (Flask holds
        it as ``session["supabase_access_token"]``) — global scope then kills
        every refresh token of that account, including a thief's, while the
        real owner signs in again with the password they still know."""

    def user_exists(self, user_id: str) -> bool:
        """True while GoTrue admin get-by-id still returns the user. A
        provider ``user_not_found`` is ``False``; any other failure raises
        :class:`AuthAdminRefused` (ambiguous when the transport may already
        have committed). Service_role reaches ``auth.users`` nowhere, so
        this — never a SQL read — is the "is this user really gone?" check."""


class SupabaseAuthAdminDispatcher:
    """The real one: ``auth.admin.*`` through the service-role client."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def revoke_sessions(self, user_id: str) -> None:
        password = _generate_revocation_password()
        try:
            self._client.auth.admin.update_user_by_id(user_id, {"password": password})
        except Exception as exc:
            code, ambiguous = classify_admin_failure(exc)
            logger.warning(
                "session revocation refused (%s%s)", code, " ambiguous" if ambiguous else ""
            )
            raise AuthAdminRefused(code, str(exc), ambiguous=ambiguous) from exc
        finally:
            # Rebound, not just out of scope, so no traceback captured above
            # this frame can recover it from a `locals()` dump.
            password = None  # type: ignore[assignment]

    def change_email(self, user_id: str, new_email: str) -> None:
        try:
            self._client.auth.admin.update_user_by_id(
                user_id, {"email": new_email, "email_confirm": False}
            )
        except Exception as exc:
            code, ambiguous = classify_admin_failure(exc)
            logger.warning("email change refused (%s%s)", code, " ambiguous" if ambiguous else "")
            raise AuthAdminRefused(code, str(exc), ambiguous=ambiguous) from exc

    def delete_user(self, user_id: str) -> None:
        try:
            self._client.auth.admin.delete_user(user_id)
        except Exception as exc:
            code, ambiguous = classify_admin_failure(exc)
            if code == "no_such_account":
                # The user is gone, which is the goal — not a failure. (The
                # saga's record_auth_outcome treats it the same way from the
                # SQL side; both halves must agree or a completed deletion
                # flips to failed.)
                logger.info("user %s already gone at delete time", user_id)
                return
            logger.warning("user deletion refused (%s%s)", code, " ambiguous" if ambiguous else "")
            raise AuthAdminRefused(code, str(exc), ambiguous=ambiguous) from exc

    def sign_out_all(self, jwt: str) -> None:
        try:
            self._client.auth.admin.sign_out(jwt, scope="global")
        except Exception as exc:
            code, ambiguous = classify_admin_failure(exc)
            logger.warning(
                "global sign-out refused (%s%s)", code, " ambiguous" if ambiguous else ""
            )
            raise AuthAdminRefused(code, str(exc), ambiguous=ambiguous) from exc

    def user_exists(self, user_id: str) -> bool:
        try:
            self._client.auth.admin.get_user_by_id(user_id)
            return True
        except Exception as exc:
            code, ambiguous = classify_admin_failure(exc)
            if code == "no_such_account":
                return False
            logger.warning(
                "existence check refused (%s%s)", code, " ambiguous" if ambiguous else ""
            )
            raise AuthAdminRefused(code, str(exc), ambiguous=ambiguous) from exc


class InMemoryAuthAdminDispatcher:
    """Records calls instead of making them. Serves TESTING and
    ``?testing=true`` — which is a shipping demo surface (see
    ``InMemoryAdminBackend``'s own docstring), not only a pytest fixture, so
    a successful call here must leave the demo account state genuinely
    changed rather than only recording that a call happened. Constructed with
    a **reference** to the same list ``InMemoryAdminBackend._users`` uses, so
    a demo "change email" is visible on the very next account reload, the way
    a real one is.
    """

    def __init__(self, users: list | None = None) -> None:
        self._users = users if users is not None else []
        self.revoked: list[str] = []
        self.changed: list[dict] = []
        self.deleted: list[str] = []
        self.signed_out: list[str] = []
        self.refuse_with: str | None = None
        self.refuse_ambiguous: bool = False

    def _refuse_if_configured(self) -> None:
        if self.refuse_with:
            raise AuthAdminRefused(
                self.refuse_with, "refused by test double", ambiguous=self.refuse_ambiguous
            )

    def _refuse_if_configured_swallow_not_found(self) -> None:
        """Like :meth:`_refuse_if_configured`, but a configured
        ``no_such_account`` is success — mirroring the real
        :meth:`SupabaseAuthAdminDispatcher.delete_user`, where an already-gone
        user is the goal rather than a failure."""
        try:
            self._refuse_if_configured()
        except AuthAdminRefused as exc:
            if exc.code == "no_such_account":
                return
            raise

    def revoke_sessions(self, user_id: str) -> None:
        self._refuse_if_configured()
        self.revoked.append(user_id)

    def change_email(self, user_id: str, new_email: str) -> None:
        self._refuse_if_configured()
        self.changed.append({"user_id": user_id, "email": new_email})
        row = next((r for r in self._users if r["id"] == user_id), None)
        if row is not None:
            row["email"] = new_email
            # Mirrors the live-verified behaviour: the new address starts
            # unverified, and `email_confirmed_at` (a separate field this
            # dispatcher does not touch) is left exactly as stale as it
            # really is against the real provider.
            row["email_identity_verified"] = False

    def delete_user(self, user_id: str) -> None:
        self._refuse_if_configured_swallow_not_found()
        self.deleted.append(user_id)
        self._users[:] = [r for r in self._users if r["id"] != user_id]

    def sign_out_all(self, jwt: str) -> None:
        self._refuse_if_configured()
        self.signed_out.append(jwt)

    def user_exists(self, user_id: str) -> bool:
        self._refuse_if_configured()
        return any(r["id"] == user_id for r in self._users)


_client: Client | None = None


def get_auth_admin_dispatcher() -> AuthAdminDispatcher | None:
    """Service-role dispatcher, or ``None`` when no service-role key is
    configured. ``None`` means neither action can be performed right now —
    callers must treat that as unavailable, not as a silent success.
    """
    global _client
    if _client is None:
        _client = get_supabase_admin()
        if _client is None:
            return None
    return SupabaseAuthAdminDispatcher(_client)
