"""The service-role PostgREST session must not run on HTTP/2.

`postgrest` hardcodes `http2=True` when it builds its own session, so every
admin call in the process multiplexes onto one connection. Under `--threads 8`
that is a shared, concurrently-read socket, and httpcore's sync HTTP/2 backend
caches the first read error and re-raises it for every stream on that
connection — so one transient failure fails every in-flight admin request, not
just its own.

Observed 2026-09-19 opening the admin console (six parallel calls): a single
`WinError 10035` took down users, audit, notifications, registrations and tiers
together. `fetch_identity` was among them, so identity fell back unresolved,
`is_admin` correctly refused to infer privilege from a non-answer, and the
administrator's console link disappeared.

These fail against the previous code, where `SupabaseAdminClient` returned
`create_client(url, key)` untouched and its session carried `http2=True`.
"""

from __future__ import annotations

import httpx

from web.utils.supabase_client import _without_http2


class _FakePostgrest:
    def __init__(self, session):
        self.session = session


class _FakeClient:
    def __init__(self, session):
        self.postgrest = _FakePostgrest(session)


def _session() -> httpx.Client:
    """A stand-in for the session supabase-py builds, HTTP/2 and all."""
    return httpx.Client(
        base_url="https://project.supabase.co/rest/v1",
        headers={"apikey": "service-role-key", "authorization": "Bearer service-role-key"},
        timeout=120,
        follow_redirects=True,
        http2=True,
    )


def test_the_admin_session_is_moved_off_http2():
    original = _session()
    client = _FakeClient(original)

    _without_http2(client)

    assert client.postgrest.session is not original
    # httpx exposes the negotiated protocols through the transport's pool.
    pool = client.postgrest.session._transport._pool
    assert pool._http2 is False, "the admin session is still multiplexing on HTTP/2"


def test_the_rebuilt_session_keeps_base_url_headers_and_timeout():
    """The reason this rebuilds from the LIVE session rather than injecting a
    fresh client through `SyncClientOptions`.

    `postgrest`'s request builder sends a RELATIVE path
    (`base_request_builder.send` passes `str(self.path)`), so the session's
    `base_url` is load-bearing — an injected client never gets one, and every
    admin call would fail. The auth headers matter for the same reason.
    """
    original = _session()
    client = _FakeClient(original)

    _without_http2(client)
    rebuilt = client.postgrest.session

    assert str(rebuilt.base_url).rstrip("/") == "https://project.supabase.co/rest/v1"
    assert rebuilt.headers["apikey"] == "service-role-key"
    assert rebuilt.headers["authorization"] == "Bearer service-role-key"
    assert rebuilt.timeout.read == 120, "the 120s PostgREST timeout must survive"
    assert rebuilt.follow_redirects is True


def test_the_old_session_is_closed_so_its_pool_is_not_leaked():
    original = _session()
    client = _FakeClient(original)

    _without_http2(client)

    assert original.is_closed, "the replaced session would leak its connection pool"


def test_a_client_without_a_postgrest_session_is_left_alone(caplog):
    """A supabase-py shape change must degrade to a log line, not an
    AttributeError on the first admin request of the process."""

    class _Bare:
        pass

    bare = _Bare()
    with caplog.at_level("WARNING"):
        assert _without_http2(bare) is bare
    assert any("session not found" in record.message for record in caplog.records)
