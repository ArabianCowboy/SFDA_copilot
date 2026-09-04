"""What the server says when it cannot check a credential.

Three unrelated failures used to arrive as one answer. A read timeout to GoTrue,
a missing environment variable, and a genuinely invalid token all returned 401
and cleared the session — so a transient network blip told a signed-in
administrator they were signed out, and destroyed their server-side session on
the way out. Observed in production:

    ERROR:root:Authentication error at endpoint admin.audit: The read operation
    timed out
    ... httpx.ReadTimeout
    "GET /admin/api/audit?...&target_id=..." 401

The rule was already written down one layer lower. `web/api/admin.py` answers
503 when the *profile* store cannot be read, because "an outage is not a
refusal, and saying 'forbidden' when the truth is 'we could not check' tells an
administrator they have lost access they still have". These tests hold the hop
above it — token verification — to exactly the same rule.

`test_an_identity_outage_is_a_503_not_a_refusal` in `test_admin_audit.py` does
not cover any of this, which is why the bug survived: it monkeypatches
`_authenticate_request` itself, so the `except` block that made the mistake
never runs.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from flask import request
from supabase_auth.errors import AuthApiError, AuthRetryableError, AuthUnknownError

from web.api.app import _is_auth_refusal, _is_upstream_outage, create_app
from web.services.identity_cache import IdentityFlags
from web.services.token_verification_cache import TokenVerificationTimeout


def _fake_jwt(exp: float) -> str:
    """A JWT-*shaped* (unsigned, unverified) string that clears Layer 0.

    These tests are about what happens after a token reaches the (mocked)
    GoTrue call — outage vs. refusal classification — not about JWT shape.
    `_is_structurally_live` only inspects the payload segment, so header and
    signature can be anything; the payload just needs a not-yet-expired `exp`.
    """
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"header.{payload}.signature"


AUTH = {"Authorization": f"Bearer {_fake_jwt(time.time() + 3600)}"}


@pytest.fixture
def app():
    application = create_app(testing=True)
    # The branch under test is the real one. `_authenticate_request` short
    # circuits to a fake identity while TESTING is on and never reaches a
    # Supabase client at all, so leaving it on would test nothing.
    application.config["TESTING"] = False
    return application


@pytest.fixture
def client(app):
    return app.test_client()


class _FailingSupabase:
    """A client whose auth call fails the way production's did."""

    def __init__(self, exception: BaseException) -> None:
        self._exception = exception
        self.auth = self

    def get_user(self, _token):
        raise self._exception


def _seed_session(client) -> None:
    """A reader who is signed in, before anything goes wrong."""
    with client.session_transaction() as session:
        session["supabase_access_token"] = "stored-token"
        session["user_email"] = "reader@example.com"
        session["is_admin_hint"] = True


def _use(monkeypatch, exception: BaseException) -> None:
    monkeypatch.setattr("web.api.app.get_supabase", lambda: _FailingSupabase(exception))


# ── The reported incident ────────────────────────────────────────────────────


def test_a_gotrue_timeout_is_an_outage_not_a_refusal(client, monkeypatch):
    _use(monkeypatch, httpx.ReadTimeout("The read operation timed out"))
    _seed_session(client)

    response = client.get("/api/identity", headers=AUTH)

    assert response.status_code == 503
    assert response.get_json() == {"error": "identity_unavailable"}


def test_a_timeout_does_not_sign_the_reader_out(client, monkeypatch):
    """The half that actually hurt.

    401 is not merely the wrong number: `_handle_unauthorized` acts on it by
    calling `clear_auth_session()`, so a blip lasting one request threw away the
    stored access token, the email, and the admin render hint. The credential in
    the reader's hands was valid throughout.
    """
    _use(monkeypatch, httpx.ReadTimeout("The read operation timed out"))
    _seed_session(client)

    client.get("/api/identity", headers=AUTH)

    with client.session_transaction() as session:
        assert session.get("supabase_access_token") == "stored-token"
        assert session.get("user_email") == "reader@example.com"
        assert session.get("is_admin_hint") is True


# ── The refusal it must not swallow ──────────────────────────────────────────


def test_an_invalid_token_is_still_a_refusal(client, monkeypatch):
    """The fix must not become "never say no". A bad JWT is a real 401."""
    _use(monkeypatch, AuthApiError("invalid JWT", 401, "bad_jwt"))
    _seed_session(client)

    response = client.get("/api/identity", headers=AUTH)
    assert response.status_code == 401

    # And this one SHOULD clear the session — the credential really is bad.
    with client.session_transaction() as session:
        assert "supabase_access_token" not in session
        assert "is_admin_hint" not in session


# ── Our own faults are ours ──────────────────────────────────────────────────


def test_a_server_fault_is_not_blamed_on_the_credential(client, monkeypatch):
    """Found by the audit rather than by the incident.

    The same bare `except` also caught a missing environment variable, a
    provider response in an unexpected shape, and any bug in identity
    resolution. "Your credentials are invalid" is exactly as untrue for those as
    it is for a timeout, and it carried the same session-clearing cost.
    """
    _use(monkeypatch, ValueError("SUPABASE_URL and SUPABASE_ANON_KEY are required"))
    _seed_session(client)

    response = client.get("/api/identity", headers=AUTH)

    assert response.status_code == 500
    assert response.get_json() == {"error": "identity_check_failed"}
    # It still denies the request. It just does not lie about why.
    with client.session_transaction() as session:
        assert session.get("supabase_access_token") == "stored-token"


# ── The client that makes the call ───────────────────────────────────────────


def test_the_anon_client_builds_with_its_injected_transport(monkeypatch):
    """Nothing in this suite ever constructed a real Supabase client.

    `SupabaseClient.__new__` returns None under TESTING, so the whole
    construction path — including the `SyncClientOptions(httpx_client=...)`
    injection that bounds the auth call — ran for the first time in production.
    It was written against the base `ClientOptions`, which takes no such
    keyword, and would have raised `TypeError` on the first authenticated
    request with every test still green.

    So this builds one for real, with throwaway credentials. No network call is
    made: supabase-py constructs its subclients lazily.
    """
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")

    from web.utils import supabase_client as module

    monkeypatch.setattr(module.SupabaseClient, "_instance", None)
    transport = module.SupabaseClient().auth._http_client

    # The ceiling is on the client GoTrue actually uses, not merely configured
    # somewhere adjacent to it.
    assert transport.timeout.read == 5.0
    assert transport.timeout.connect == 5.0
    # Repeated from supabase-py's own default, which an injected client replaces
    # rather than extends. Dropping either would silently downgrade the
    # connection — and the incident this bounds was on an HTTP/2 stream.
    assert transport.follow_redirects is True


def test_the_auth_timeout_can_be_tuned_without_a_code_change(monkeypatch):
    monkeypatch.setenv("SUPABASE_AUTH_TIMEOUT", "12")

    from web.utils.supabase_client import _auth_timeout

    assert _auth_timeout().read == 12.0


# ── The classifier itself ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exception",
    [
        httpx.ReadTimeout("read"),
        httpx.ConnectTimeout("connect"),
        httpx.PoolTimeout("pool"),
        httpx.WriteTimeout("write"),
        httpx.ConnectError("refused"),
        httpx.ReadError("reset"),
        httpx.RemoteProtocolError("garbage"),
    ],
)
def test_every_transport_failure_counts_as_an_outage(exception):
    """One family, not a list of the timeouts we happened to have seen.

    The incident was a ReadTimeout. Enumerating that alone would leave a
    connection refusal — the same outage, a different socket call — still
    reading as a bad password.
    """
    assert _is_upstream_outage(exception) is True


def test_a_five_hundred_from_the_auth_service_is_an_outage():
    assert _is_upstream_outage(AuthApiError("upstream exploded", 503, None)) is True
    assert _is_upstream_outage(AuthRetryableError("try again", 502)) is True


def test_a_rejected_credential_is_not_an_outage():
    assert _is_upstream_outage(AuthApiError("invalid JWT", 401, "bad_jwt")) is False
    assert _is_upstream_outage(AuthApiError("forbidden", 403, None)) is False


def test_being_rate_limited_is_not_a_verdict_on_the_credential():
    """429 is the provider declining to answer, not a rejection.

    Easy to put in the wrong bucket, because it is a 4xx and every other 4xx
    here is a refusal. But this app verifies a token on every authenticated
    request — four of them before an operator has clicked anything in the
    console — so treating a rate limit as a bad credential would sign an
    administrator out for being busy.
    """
    assert _is_upstream_outage(AuthApiError("too many requests", 429, None)) is True


def test_a_rate_limit_does_not_sign_the_reader_out(client, monkeypatch):
    _use(monkeypatch, AuthApiError("too many requests", 429, None))
    _seed_session(client)

    response = client.get("/api/identity", headers=AUTH)

    assert response.status_code == 503
    with client.session_transaction() as session:
        assert session.get("supabase_access_token") == "stored-token"


def test_only_the_auth_family_counts_as_a_refusal():
    assert _is_auth_refusal(AuthApiError("invalid JWT", 401, "bad_jwt")) is True
    assert _is_auth_refusal(ValueError("misconfigured")) is False
    assert _is_auth_refusal(KeyError("user")) is False


def test_the_real_refusal_types_are_still_refusals():
    """The guard below requires an integer status, so this pins that every error
    the library actually raises for a rejected credential carries one. If a
    future version stops doing that, a real 401 would silently become a 500 and
    this is what says so."""
    from supabase_auth.errors import (
        AuthInvalidCredentialsError,
        AuthInvalidJwtError,
        AuthSessionMissingError,
    )

    assert _is_auth_refusal(AuthInvalidJwtError("bad jwt")) is True
    assert _is_auth_refusal(AuthSessionMissingError()) is True
    assert _is_auth_refusal(AuthInvalidCredentialsError("nope")) is True


def test_a_refusal_without_a_status_is_not_established():
    """401 destroys the session, so it is the claim that needs evidence.

    An auth-family error carrying no usable status has not shown that the
    credential was rejected — and answering "your credentials are invalid" from
    that is the same unfounded certainty the timeout bug was made of.
    """

    class _Statusless(AuthApiError):
        def __init__(self):
            super().__init__("mystery", 400, None)
            self.status = None

    assert _is_auth_refusal(_Statusless()) is False


def test_an_unparseable_provider_error_is_not_a_verdict(monkeypatch):
    """`AuthUnknownError` is inside the auth family but is not a decision.

    GoTrue returns it from `handle_exception` when it could not parse the error
    body at all — the second argument is the parse failure itself. Being in the
    family made it read as a rejected credential, so a malformed response from
    the provider cleared a valid session.
    """
    unknown = AuthUnknownError("could not parse", ValueError("not json"))

    assert _is_auth_refusal(unknown) is False
    assert _is_upstream_outage(unknown) is False


def test_an_unparseable_provider_error_leaves_the_session_alone(client, monkeypatch):
    _use(monkeypatch, AuthUnknownError("could not parse", ValueError("not json")))
    _seed_session(client)

    response = client.get("/api/identity", headers=AUTH)

    assert response.status_code == 500
    with client.session_transaction() as session:
        assert session.get("supabase_access_token") == "stored-token"


def test_a_wrapped_network_failure_is_still_an_outage():
    """GoTrue funnels every non-HTTP failure through
    `AuthRetryableError(message, 0)` — status zero, not a 5xx. A classifier that
    only looked at the status number would miss it."""
    assert _is_upstream_outage(AuthRetryableError("connection reset", 0)) is True


def test_a_missing_auth_library_is_our_fault_not_a_refusal(monkeypatch):
    """The fallback when neither `supabase_auth` nor `gotrue` imports.

    Answering "refusal" there looks like the cautious choice and is the wrong
    one: that branch is only reachable when the auth library is absent, so
    `get_user` never works — and every request would 401 and clear its session,
    which is the original bug restored in the degenerate case.
    """
    monkeypatch.setattr("web.api.app.AuthError", None)

    assert _is_auth_refusal(ValueError("no library")) is False
    assert _is_auth_refusal(RuntimeError("no library")) is False


# ── Layer 0: structural pre-validation ───────────────────────────────────────


def test_a_malformed_token_never_reaches_the_provider(client, monkeypatch):
    """Not authentication — a shape check. Garbage is rejected before the
    network call it would otherwise cost, which is the one attack a
    token-verification cache cannot help with: a flood of distinct invalid
    tokens is a cache miss every time."""
    calls = []
    monkeypatch.setattr(
        "web.api.app.get_supabase",
        lambda: (_ for _ in ()).throw(AssertionError("must not reach the provider")),
    )

    response = client.get("/api/identity", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401
    assert calls == []  # the monkeypatched get_supabase was never called


def test_an_already_expired_token_never_reaches_the_provider(client, monkeypatch):
    monkeypatch.setattr(
        "web.api.app.get_supabase",
        lambda: (_ for _ in ()).throw(AssertionError("must not reach the provider")),
    )
    expired = _fake_jwt(time.time() - 3600)

    response = client.get("/api/identity", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401


def test_a_clock_60s_ahead_does_not_reject_a_valid_token(monkeypatch):
    """The grace is for OUR clock, not the token's — a VPS with drifting NTP
    must not start refusing credentials GoTrue itself would still accept."""
    from web.api.app import _is_structurally_live

    just_expired = time.time() - 30  # past its own exp, but within the 60s leeway
    assert _is_structurally_live(_fake_jwt(just_expired)) is True

    truly_expired = time.time() - 120  # past both the exp and the leeway
    assert _is_structurally_live(_fake_jwt(truly_expired)) is False


def test_a_deeply_nested_payload_is_rejected_not_a_crash():
    """`json.loads` raises `RecursionError`, not `ValueError`, past a certain
    nesting depth — well within what fits in an ordinary header. Layer 0
    runs before the auth path's own `try/except`, so an uncaught
    `RecursionError` here would propagate straight out of an unauthenticated
    request instead of the clean 401 this function's own docstring promises.
    """
    from web.api.app import _is_structurally_live

    nested = base64.urlsafe_b64encode(b"[" * 20000 + b"]" * 20000).decode()
    hostile_token = f"header.{nested}.signature"

    assert _is_structurally_live(hostile_token) is False


def test_an_infinite_exp_is_rejected_not_treated_as_forever_live():
    """JSON has no `Infinity`/`NaN` literals, but `json.loads` accepts them
    as a de facto extension anyway — and `float('inf') + leeway > time.time()`
    is trivially true. Layer 0's whole documented job is rejecting garbage in
    microseconds; a payload of `{"exp": Infinity}` must not be the one input
    that sails through it and costs a real GoTrue round trip instead."""
    from web.api.app import _is_structurally_live, _token_exp

    infinite = base64.urlsafe_b64encode(b'{"exp": Infinity}').decode()
    hostile_token = f"header.{infinite}.signature"

    assert _is_structurally_live(hostile_token) is False
    assert _token_exp(hostile_token) is None


# ── Single-flight, wired into the real route ─────────────────────────────────


def test_two_concurrent_reader_requests_on_one_token_call_gotrue_once(app):
    """This is what actually answers worker starvation, and it holds even
    with the shipped `ttl_seconds: 0` (docs/archive/2026-08-27_token-verification-cache.md §1.4):
    nothing needs to be remembered for a concurrent burst on one token to
    collapse into a single GoTrue call."""
    calls = []
    lock = threading.Lock()
    entered = threading.Event()
    release = threading.Event()

    class _CountingSupabase:
        def __init__(self) -> None:
            self.auth = self

        def get_user(self, _token):
            with lock:
                calls.append(1)
            entered.set()
            release.wait(timeout=5)
            return SimpleNamespace(user=SimpleNamespace(id="reader-1", email="reader@example.com"))

    results: list[int] = []

    def call(test_client) -> None:
        results.append(test_client.get("/api/identity", headers=AUTH).status_code)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("web.api.app.get_supabase", lambda: _CountingSupabase())

        owner_thread = threading.Thread(target=call, args=(app.test_client(),))
        owner_thread.start()
        assert entered.wait(timeout=5)

        waiter_thread = threading.Thread(target=call, args=(app.test_client(),))
        waiter_thread.start()
        release.set()

        owner_thread.join(timeout=5)
        waiter_thread.join(timeout=5)

    assert len(calls) == 1
    assert results == [200, 200]


def test_a_verification_timeout_is_an_outage_not_a_refusal():
    """Unit-level pin for the classifier itself — the route-level version is
    `test_a_stalled_leader_is_a_503_with_the_session_intact` below."""
    assert _is_upstream_outage(TokenVerificationTimeout(5.5)) is True
    assert _is_auth_refusal(TokenVerificationTimeout(5.5)) is False


def test_a_stalled_leader_is_a_503_with_the_session_intact(client, app, monkeypatch):
    """A `TokenVerificationTimeout` reaching a real request must classify as
    the outage it is — 503, session untouched — exactly like a raw
    `httpx.TransportError` does elsewhere in this file. Exercised through the
    actual route, not just through `_is_upstream_outage` in isolation: this
    is the path a genuinely stalled leader thread would put every waiter on.
    """

    def _raise_timeout(_token, _verify, **_kwargs):
        raise TokenVerificationTimeout(5.5)

    monkeypatch.setattr(app.config["token_verification"], "get_or_verify", _raise_timeout)
    _seed_session(client)

    response = client.get("/api/identity", headers=AUTH)

    assert response.status_code == 503
    assert response.get_json() == {"error": "identity_unavailable"}
    with client.session_transaction() as session:
        assert session.get("supabase_access_token") == "stored-token"


def test_admin_route_wiring_never_caches_and_always_asks_live(app, monkeypatch):
    """Proves the `request.blueprint == "admin"` wiring end to end, not just
    the cache class's own `use_cache` parameter in isolation — the gap a
    review pass flagged: a regression that let the admin blueprint fall
    through to `use_cache=True` could otherwise still pass every other test
    in this suite.

    No real admin backend is exercised or needed: `resolve_identity_flags`
    is replaced directly, since this test is about how many times the TOKEN
    was verified, not about console authorization content.

    The cache is swapped for one with `ttl_seconds=30`, not left at the
    shipped `0` default — at `0` a positive cache never stores anything for
    ANY route, so a `use_cache` regression on the admin blueprint would be
    invisible here. A positive TTL is what actually gives "never cached"
    something to fail against.
    """
    from web.api import app as app_module
    from web.services.token_verification_cache import TokenVerificationCache

    monkeypatch.setitem(app.config, "token_verification", TokenVerificationCache(ttl_seconds=30))

    calls = []

    class _CountingSupabase:
        def __init__(self) -> None:
            self.auth = self

        def get_user(self, _token):
            calls.append(1)
            from types import SimpleNamespace

            return SimpleNamespace(user=SimpleNamespace(id="admin-1", email="admin@example.com"))

    monkeypatch.setattr(app_module, "get_supabase", lambda: _CountingSupabase())
    monkeypatch.setattr(
        app_module,
        "resolve_identity_flags",
        lambda cache, user_id, email, *, fresh=False: IdentityFlags(
            user_id, email, "admin", "staff", False
        ),
    )

    with app.test_request_context("/admin/api/audit", headers=AUTH):
        assert request.blueprint == "admin"
        identity, early_response = app_module._authenticate_request()
    assert early_response is None
    assert identity.is_admin

    with app.test_request_context("/admin/api/audit", headers=AUTH):
        app_module._authenticate_request()

    assert len(calls) == 2, "the admin blueprint must verify live on every request"
