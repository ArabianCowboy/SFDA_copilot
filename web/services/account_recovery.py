"""Sending password-recovery email, for readers and for operators alike.

Both callers land here on purpose. The reader's *forgot password* link and the
console's *send reset* button must produce the **same** recovery link, because
they return to the same landing view — build the mail path once and the console's
button is an authorisation check on top of finished work.

**Why this is server-side at all**, when login and signup talk to Supabase
straight from the browser: a link generated in the browser carries a PKCE
`code_challenge`, and completing it needs the code verifier that
``resetPasswordForEmail`` wrote into *that* browser's ``localStorage``. A reader
who asks on their laptop and opens the mail on their phone has no verifier there,
and the exchange cannot complete. Measured against the live project on
2026-08-14: a server-generated link instead returns tokens in the URL fragment
(``#access_token=…&type=recovery``), which any browser can consume. Originating
every recovery mail here is what makes recovery work on the device the reader
actually opens their mail on.

**Why the anon key and not the service role.** ``/recover`` is an unauthenticated
GoTrue endpoint — it is precisely what the browser would have called. Using the
publishable key keeps this off the key that bypasses every RLS policy, and adds
no new secret: ``SUPABASE_ANON_KEY`` is already required to render the page.

**What this module deliberately does not do.** It never generates a link and
hands it back (``auth.admin.generate_link``). That return value *is* a bearer
credential — whoever holds the URL can set the password — and it would then exist
in this process, in tracebacks, and one careless ``jsonify`` from an operator's
screen. The console's whole thesis is that an operator helps without ever
learning a credential, and a call whose return value is one cannot be part of it.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol
from urllib.parse import quote, urlparse

from supabase import Client, create_client

logger = logging.getLogger(__name__)


class RecoveryRefused(Exception):
    """A recovery mail was not sent, with a machine code for the caller.

    Mirrors ``AdminActionRefused``: the code is the contract, the message is for
    the log. Callers map the code to a translated string; nothing from the
    provider's own text reaches a reader, because it is English-only and
    frequently phrased as though the reader had done something wrong.
    """

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


# GoTrue reports both of these as 429 and only the prose distinguishes them, so
# the substring match is the only thing available. They mean different things to
# whoever is reading the screen and so they get different codes: one is "you just
# did this", the other is "the project's allowance is gone", and an operator who
# does not know the second exists will conclude the account is broken.
_RATE_LIMIT_MARKERS = (
    ("for security purposes", "reset_rate_limited"),
    ("only request this after", "reset_rate_limited"),
    ("email rate limit exceeded", "reset_quota_exhausted"),
    ("over_email_send_rate_limit", "reset_quota_exhausted"),
)


def classify_send_failure(error: Exception) -> str:
    """Map a provider exception to one of this module's refusal codes."""
    text = str(getattr(error, "message", None) or error).lower()
    for marker, code in _RATE_LIMIT_MARKERS:
        if marker in text:
            return code
    return "reset_send_failed"


class RecoveryDispatcher(Protocol):
    """Sends one recovery mail. Raises :class:`RecoveryRefused` if it did not."""

    def send_recovery(self, email: str, redirect_to: str) -> None: ...


class SupabaseRecoveryDispatcher:
    """Sends through the project's configured SMTP (Resend), via GoTrue."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def send_recovery(self, email: str, redirect_to: str) -> None:
        try:
            self._client.auth.reset_password_for_email(email, {"redirect_to": redirect_to})
        except Exception as exc:
            code = classify_send_failure(exc)
            # The address is not logged. A recovery request is a statement that
            # someone may have lost an account, and this log is read by more
            # people than the audit table is.
            logger.warning("recovery send refused (%s)", code)
            raise RecoveryRefused(code, str(exc)) from exc


class InMemoryRecoveryDispatcher:
    """Records sends instead of making them. Serves TESTING and ``?testing=true``.

    Mutable and per-process, matching ``InMemoryAdminBackend``: a test can assert
    what would have been sent, and nothing survives the process.
    """

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.refuse_with: str | None = None

    def send_recovery(self, email: str, redirect_to: str) -> None:
        if self.refuse_with:
            raise RecoveryRefused(self.refuse_with, "refused by test double")
        self.sent.append({"email": email, "redirect_to": redirect_to})


_client: Client | None = None
_warned = False


def get_recovery_dispatcher() -> RecoveryDispatcher | None:
    """Anon-key dispatcher, or None when it cannot be built.

    None means no recovery mail can be sent. Callers must treat that as a
    refusal to report, never as a success: telling a reader their link is on the
    way when nothing was sent is the one outcome worse than an error, because
    they will wait instead of trying something else.
    """
    global _client, _warned

    if _client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_ANON_KEY")
        if not url or not key:
            # Warned, not raised. The anon key is read-and-warned at startup
            # rather than required (see `base_render_context`), so a deployment
            # missing it still serves; recovery is the part that cannot work.
            if not _warned:
                logger.error(
                    "SUPABASE_ANON_KEY is not set; password recovery cannot send "
                    "mail and every reset request will be refused."
                )
                _warned = True
            return None
        _client = create_client(url, key)

    return SupabaseRecoveryDispatcher(_client)


def _public_base_url() -> str | None:
    """``PUBLIC_BASE_URL``, validated as a bare http(s) origin, or ``None``.

    Never raises. Whether an unusable value is a refusal (recovery) or a value
    to silently omit (signup) is a decision only each caller can make, so it is
    made there, not here.

    Non-empty is not the same as usable. This value ends up in an email as a
    link people are told to click, so a typo here is not a 404 — it is a link
    that goes somewhere else. Validated rather than trusted.

    Deliberately NOT https-only: local development runs on http://127.0.0.1:5000
    and refusing that would make the flow untestable off a deployed host. The
    scheme check exists to reject `javascript:` and friends, and Supabase's own
    redirect allow-list is the control that decides which hosts are real.
    """
    base = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return None
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.query or parsed.fragment or "@" in parsed.netloc:
        return None
    return base


def recovery_redirect_url(lang: str | None = None) -> str:
    """Where the recovery link comes back to.

    Built from ``PUBLIC_BASE_URL`` and **never** from ``request.host_url``: the
    Host header is attacker-controlled, and a poisoned Host would mail readers a
    recovery link pointing at somewhere else entirely. Refusing to send is the
    correct answer to not knowing our own address.

    ``?recovery=1`` is the marker the boot path reads to know this is a recovery
    landing before any auth event fires — the event ordering is a known upstream
    bug, and the marker also has to be readable *before* the Supabase client is
    constructed, because it selects the flow type.
    """
    base = _public_base_url()
    if base is None:
        raise RecoveryRefused(
            "reset_not_configured",
            "PUBLIC_BASE_URL is not set, or is not a bare http(s) origin",
        )

    url = f"{base}/?recovery=1"
    # Proven to survive GoTrue's redirect: it appends its fragment and leaves the
    # query alone. Only the reader-initiated path can set this — the console does
    # not know what language the target reads.
    if lang:
        url += f"&lang={quote(lang, safe='')}"
    return url


def signup_redirect_url(lang: str | None = None) -> str | None:
    """Where a confirmation link comes back to, or ``None`` to send no
    ``email_redirect_to`` at all — GoTrue then falls back to the project's own
    Site URL, which is what every signup used before this function existed.

    Shares `_public_base_url`'s validation with `recovery_redirect_url`, but
    unlike that function this one never raises. A recovery mail with a broken
    link is worse than not sending one; a signup with a broken link is not
    worse than the signup this app has always sent with no link option at
    all — so refusing to send here would be a regression this migration must
    not cause. Logged rather than silent, so a misconfigured deployment is at
    least visible. Drops the `?recovery=1` marker (this is not a recovery
    landing) and keeps `&lang=`.
    """
    base = _public_base_url()
    if base is None:
        logger.warning(
            "PUBLIC_BASE_URL is not set, or is not a bare http(s) origin; "
            "signup will omit email_redirect_to and GoTrue will use the "
            "project's own Site URL instead."
        )
        return None
    url = f"{base}/"
    if lang:
        url += f"?lang={quote(lang, safe='')}"
    return url
