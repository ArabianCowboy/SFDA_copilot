import logging
import os

import httpx
from flask import current_app

# SyncClientOptions, not the base ClientOptions. Only the sync subclass carries
# `httpx_client`; the base accepts it as no keyword at all, so importing the
# wrong one is a TypeError at client construction — which is to say, at the
# first authenticated request in production, and nowhere in the test suite,
# because SupabaseClient returns None under TESTING and never builds one.
from supabase.lib.client_options import SyncClientOptions

from supabase import Client, create_client

logger = logging.getLogger(__name__)


def _auth_timeout() -> httpx.Timeout:
    """How long the token check may take before it is called an outage.

    Every authenticated request pays one `auth.get_user` round trip to GoTrue,
    and production runs `--workers 1 --threads 8` (README.md) — so a stalled
    auth call holds one of eight request threads for the whole stall, and eight
    concurrent ones exhaust the only worker's capacity for every reader. Opening
    one console account already costs two of them.

    Gunicorn's own `--timeout 300` does not bound this: it governs the worker,
    not an outbound call.

    5 seconds is not a new policy: it is httpx's own default, which this call
    has always been running on by accident. Stating it makes the bound a
    decision rather than a library detail that a future `supabase` bump could
    change underneath the one call that gates the whole app.
    """
    return httpx.Timeout(float(os.getenv("SUPABASE_AUTH_TIMEOUT", "5")), connect=5.0)


def _auth_http_client() -> httpx.Client:
    """The transport GoTrue will use.

    `follow_redirects` and `http2` are repeated deliberately. supabase-py only
    applies its own defaults when no client is injected, so an injected client
    that omitted them would quietly downgrade the connection — and the incident
    this bounds was observed on an HTTP/2 stream.
    """
    return httpx.Client(timeout=_auth_timeout(), follow_redirects=True, http2=True)


def _without_http2(client: Client) -> Client:
    """Move the service-role PostgREST session off HTTP/2.

    `postgrest` hardcodes `http2=True` when it builds its own session, so every
    admin call in the process multiplexes onto ONE connection. Under
    `--threads 8` that is a shared, concurrently-read socket, and httpcore's
    sync HTTP/2 backend caches the first read error on the connection and
    re-raises it for every stream on it:

        httpcore/_sync/http2.py, in _read_incoming_data
            raise self._read_exception  # pragma: nocover

    So one transient read failure does not fail one request — it fails every
    request multiplexed on that connection until the pool discards it. Observed
    2026-09-19 opening the admin console, which fans out six calls at once: a
    `WinError 10035` on one stream took down users, audit, notifications,
    registrations and tiers together, and the retries a few hundred
    milliseconds later all succeeded on a fresh connection.

    The knock-on was worse than the failed panels. `fetch_identity` was one of
    the casualties, so `resolve_identity_flags` fell back to the last known
    answer with `is_resolved=False` — and `IdentityFlags.is_admin` requires a
    resolved answer, correctly, because "we could not check" must never confer
    privilege. The administrator's own console link vanished from the sidebar.
    That fail-closed behaviour is right and is not what this changes; this
    removes the transport fault that kept triggering it.

    HTTP/1.1 takes one pooled connection per concurrent request instead of
    multiplexing, so a read error costs exactly the request that suffered it.
    At this request volume the extra sockets are not a cost worth weighing
    against a failure that fans out.

    REPLACING THE SESSION, not injecting one through `SyncClientOptions`.
    That looks like the tidier lever and is the wrong one: an injected client
    is used verbatim, and `postgrest`'s request builder sends a RELATIVE path
    (`base_request_builder.send` passes `str(self.path)`), so it depends on a
    `base_url` that supabase-py only sets on the session it builds itself. The
    same injected client would also serve GoTrue, whose base URL differs — one
    client cannot carry both. Rebuilding from the live session copies whatever
    supabase-py actually configured (`base_url`, headers, timeout) and changes
    the one thing at issue, so a dependency bump that alters those defaults is
    carried along rather than silently re-derived here.

    The anon client is deliberately untouched: it injects its own HTTP/2 client
    and `SupabaseClient`'s own comment records that as a decision. It is also
    auth-only, so it never takes the PostgREST path this fixes.
    """
    session = getattr(getattr(client, "postgrest", None), "session", None)
    if session is None:  # pragma: no cover - shape changed under us
        logger.warning("Admin PostgREST session not found; leaving the transport alone.")
        return client

    client.postgrest.session = httpx.Client(
        base_url=session.base_url,
        headers=session.headers,
        timeout=session.timeout,
        follow_redirects=True,
        http2=False,
    )
    session.close()
    return client


class SupabaseClient:
    _instance: Client | None = None

    def __new__(cls) -> Client | None:  # type: ignore[misc]
        # Deliberately returns a `Client`, not a `SupabaseClient` instance —
        # this is a factory hiding behind constructor syntax, same shape as
        # `SupabaseAdminClient` below. mypy's `__new__` contract expects an
        # instance of `cls`; this class intentionally does not follow it.
        if cls._instance is None:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_ANON_KEY")

            if not url or not key:
                raise ValueError(
                    "SUPABASE_URL and SUPABASE_ANON_KEY environment variables are required"
                )

            # Handle test environment
            if current_app and current_app.config.get("TESTING"):
                # In test environment, we don't actually create a Supabase client
                # The mock will be injected by the test fixtures
                return None

            # This client is only ever used for auth: token verification, the
            # live signup route, and logout. There is no server-side sign-in:
            # `Services.login` goes straight to GoTrue. See ARCHITECTURE.md.
            # Nothing reads PostgREST through it, so one timeout tuned for
            # GoTrue is safe to share.
            #
            # SESSIONLESS ON PURPOSE. `persist_session=False` is what keeps this
            # process-global client from becoming a shared identity: without it,
            # `sign_in_with_password` and `sign_up` call `_save_session` and the
            # singleton starts holding whoever authenticated last, for every
            # thread in the worker. A no-arg `auth.sign_out()` then revokes THAT
            # reader's sessions rather than the caller's, which is exactly the
            # bug fixed alongside this line — but the deeper problem was the
            # client storing a session at all, and only this closes it. Every
            # auth call here passes its own JWT explicitly (`get_user(token)`,
            # `admin.sign_out(token, ...)`), so nothing needs the stored copy.
            # `auto_refresh_token` follows: with no session to refresh, its
            # background timer thread is pure overhead.
            cls._instance = create_client(
                url,
                key,
                SyncClientOptions(
                    httpx_client=_auth_http_client(),
                    persist_session=False,
                    auto_refresh_token=False,
                ),
            )
        return cls._instance


def get_supabase() -> Client:
    """Get the Supabase client instance.

    None only happens under TESTING (see `SupabaseClient.__new__`), and every
    caller already runs behind its own TESTING branch that never reaches this
    function in that mode — see e.g. `_authenticate_request` in app.py.
    """
    client = SupabaseClient()
    assert client is not None
    return client


class SupabaseAdminClient:
    """Service-role client. SERVER-SIDE ONLY.

    This key bypasses every RLS policy on the project. It must never be
    rendered into a template, returned in a JSON response, or logged — the
    anon key above is the only one a browser is ever allowed to hold.

    Deliberately separate from ``SupabaseClient`` rather than a flag on it:
    five test files sit downstream of that singleton, and the two clients
    differ in more than a key. This one checks TESTING *before* reading the
    environment, because the anon client's ordering means it raises when the
    vars are unset — fine for a client the whole app needs, wrong for one that
    only the admin surface needs.
    """

    _instance: Client | None = None
    _warned = False

    def __new__(cls) -> Client | None:  # type: ignore[misc]
        # Same factory-behind-constructor-syntax shape as SupabaseClient above.
        if current_app and current_app.config.get("TESTING"):
            return None

        if cls._instance is None:
            url = os.getenv("SUPABASE_URL")
            # Both names are accepted so the key can be migrated without a code
            # change. Supabase is replacing the long-lived JWT `service_role`
            # key with individually revocable `sb_secret_…` keys and removes the
            # legacy ones in late 2026; `create_client` does not inspect the
            # format, so the migration is a value swap. The new name wins when
            # both are present, which makes the cutover a rename rather than an
            # edit-in-place — and leaves the old value recoverable for a rollback.
            source = next(
                (
                    name
                    for name in ("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")
                    if os.getenv(name)
                ),
                None,
            )
            key = os.getenv(source) if source else None

            if not url or not key:
                # Loud in the log, but not fatal. A missing admin key must not
                # stop the app serving chat: the reader-facing product does not
                # depend on it, and callers treat "no admin client" as "nobody
                # is an administrator", which fails in the safe direction.
                if not cls._warned:
                    logger.error(
                        "Neither SUPABASE_SECRET_KEY nor SUPABASE_SERVICE_ROLE_KEY is set "
                        "(or SUPABASE_URL is missing); every reader will resolve as a "
                        "non-administrator and the admin surface will be unreachable. "
                        "Set one in .env to enable it."
                    )
                    cls._warned = True
                return None

            # WHICH name won, by name only and never the value. On 2026-09-07 a
            # foreign `sb_secret_` key shadowed a working `service_role` JWT and
            # 401'd every privileged call; the log said only that
            # SUPABASE_SERVICE_ROLE_KEY was unset, which was both untrue and the
            # opposite of useful, because the guard above had not fired at all.
            # A present-but-wrong key looks identical to a correct one from here
            # — `create_client` validates nothing — so the one thing this can
            # honestly report is which variable it read, and that is exactly the
            # fact the incident needed and did not have.
            logger.info("Supabase admin client built from %s.", source)

            cls._instance = _without_http2(create_client(url, key))

        return cls._instance


def get_supabase_admin() -> Client | None:
    """Service-role Supabase client, or None when unavailable.

    None means one of: running under TESTING, or no service-role key is
    configured. Callers must treat it as "no privileged data available"
    rather than as an error.
    """
    return SupabaseAdminClient()
