"""Who the server thinks you are, and what it refuses to let that decide.

Three things are being pinned here, and they fail in different directions:

* **The bypass still admits the plain reader.** Five server test files send the
  literal `Bearer fake_token` and expect 200. Adding privileged identities next
  to it must not disturb that, and the first test says so out loud rather than
  leaving it implied by the other suites passing.
* **A role is never trusted from the cookie.** `is_admin_hint` decides whether a
  link is drawn, nothing more, and it rotates the moment a different reader
  picks up the same cookie.
* **The cache is not the authority.** It answers fast; the database decides.
"""

from __future__ import annotations

import pytest

from web.api.app import create_app
from web.services.identity_cache import IdentityFlags, IdentityFlagsCache


AUTH = {"Authorization": "Bearer fake_token"}
ADMIN = {"Authorization": "Bearer fake_admin_token"}
DISABLED = {"Authorization": "Bearer fake_disabled_token"}


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


# ── The bypass ────────────────────────────────────────────────────────────────


def test_the_plain_reader_token_still_authenticates(client):
    """The regression the other five suites would only report as noise.

    They send `Bearer fake_token` and assert chat behaviour, so a broken bypass
    surfaces there as sixty unrelated failures. This asserts the one thing that
    actually changed.
    """
    response = client.get("/api/identity", headers=AUTH)
    assert response.status_code == 200
    assert response.get_json()["role"] == "user"


def test_a_missing_token_keeps_its_exact_body(client):
    """`test_auth_routes.py:68-75` asserts this string byte for byte."""
    response = client.get("/api/identity")
    assert response.status_code == 401
    assert response.get_json() == {"error": "Invalid or missing test token"}


def test_the_admin_token_resolves_to_an_administrator(client):
    body = client.get("/api/identity", headers=ADMIN).get_json()
    assert body["role"] == "admin"
    assert body["is_admin"] is True
    assert body["user_id"] == "test-admin-id"


def test_the_admin_marker_is_not_shadowed_by_the_reader_marker(client):
    """`_TESTING_IDENTITIES` is ordered most-specific-first on purpose.

    These two markers do not collide today — "fake_token" is not a contiguous
    substring of "fake_admin_token" — but the lookup is a substring match, so a
    marker that *did* contain it would be shadowed by whichever entry came
    first. This fails the moment someone reorders the table.
    """
    assert client.get("/api/identity", headers=ADMIN).get_json()["is_admin"] is True
    assert client.get("/api/identity", headers=AUTH).get_json()["is_admin"] is False


# ── Disabled accounts ─────────────────────────────────────────────────────────


def test_a_disabled_reader_is_refused_with_403_not_401(client):
    """401 would log them out, let them log back in, and refuse them again.

    That loop reads as a broken product. 403 says the true thing: we know who
    you are and the answer is still no.
    """
    response = client.post("/api/chat", json={"query": "hello"}, headers=DISABLED)
    assert response.status_code == 403
    assert response.get_json() == {"error": "account_disabled"}


def test_a_disabled_reader_stays_signed_in(client):
    """The 401 path clears the session; the 403 path must not.

    Being told why you are blocked is only possible while the client still
    believes you are signed in.
    """
    with client:
        client.post("/api/chat", json={"query": "hello"}, headers=DISABLED)
        from flask import session
        assert session.get("user_email") == "disabled@example.com"


# ── The admin hint is a render hint, and it rotates ───────────────────────────


def test_the_admin_hint_does_not_survive_a_change_of_reader(client):
    """The leak this whole rotation discipline exists to close.

    One browser, two people. An elevated marker left in the cookie would draw
    admin chrome for whoever signs in next — cosmetic, but it advertises a
    surface and invites a click that a shared machine should never offer.
    """
    with client:
        from flask import session

        client.get("/api/identity", headers=ADMIN)
        assert session["is_admin_hint"] is True

        client.get("/api/identity", headers=AUTH)
        assert session["is_admin_hint"] is False
        assert session["auth_identity"] == "test-user-id"


def test_clearing_the_auth_session_takes_the_hint_with_it(app):
    """`clear_auth_session` runs on the 401 path, which is where a stale hint
    would otherwise be stranded on a shared machine's cookie."""
    from web.api.app import clear_auth_session

    with app.test_request_context():
        from flask import session

        session["user_email"] = "someone@example.com"
        session["supabase_access_token"] = "token"
        session["is_admin_hint"] = True

        clear_auth_session()

        assert "is_admin_hint" not in session
        assert "user_email" not in session
        assert "supabase_access_token" not in session


# ── The cache ─────────────────────────────────────────────────────────────────


def _flags(user_id: str = "u1", role: str = "user") -> IdentityFlags:
    return IdentityFlags(user_id, f"{user_id}@example.com", role, "free", False)


def test_the_cache_returns_what_it_was_given():
    cache = IdentityFlagsCache()
    cache.put(_flags("u1", "admin"))
    assert cache.get("u1").is_admin is True
    assert cache.get("absent") is None


def test_an_entry_expires_rather_than_outliving_a_demotion(monkeypatch):
    """The TTL is the ceiling on staleness for a change made outside the app —
    in the SQL editor, or the Supabase dashboard. A console change invalidates
    explicitly and does not wait for this."""
    clock = {"t": 1000.0}
    monkeypatch.setattr(IdentityFlagsCache, "_now", staticmethod(lambda: clock["t"]))

    cache = IdentityFlagsCache(ttl_seconds=30)
    cache.put(_flags("u1", "admin"))
    assert cache.get("u1") is not None

    clock["t"] += 31
    assert cache.get("u1") is None


def test_invalidating_is_immediate(monkeypatch):
    """An operator must never see their own change lag."""
    clock = {"t": 1000.0}
    monkeypatch.setattr(IdentityFlagsCache, "_now", staticmethod(lambda: clock["t"]))

    cache = IdentityFlagsCache(ttl_seconds=3600)
    cache.put(_flags("u1", "admin"))
    cache.invalidate("u1")
    assert cache.get("u1") is None


def test_the_cache_is_bounded():
    cache = IdentityFlagsCache(max_entries=3)
    for n in range(10):
        cache.put(_flags(f"u{n}"))
    assert len(cache) <= 3


# ── Failure is unprivileged, and is not remembered ────────────────────────────


def test_a_failed_lookup_serves_a_reader_and_is_not_cached(monkeypatch, app):
    """Fails open on access, closed on privilege.

    A Supabase blip must not lock everyone out of a product whose whole job is
    answering one question quickly — but it must not hand anyone the console
    either. And the failure must not be remembered: caching it would pin the
    reader to `role='user'` for the length of the TTL, turning a one-request
    blip into a thirty-second one.
    """
    from web.services import admin_store

    class Broken:
        def fetch_identity(self, user_id, email):
            raise RuntimeError("supabase is down")

    monkeypatch.setattr(admin_store, "get_admin_backend", lambda: Broken())

    cache = IdentityFlagsCache()
    with app.app_context():
        flags = admin_store.resolve_identity_flags(cache, "u1", "u1@example.com")

    assert flags.is_admin is False
    assert flags.is_disabled is False
    assert len(cache) == 0, "a transient failure must not be cached"


def test_no_service_role_key_means_nobody_is_an_administrator(monkeypatch, app):
    """The state this ships in until the key is configured."""
    from web.services import admin_store

    monkeypatch.setattr(admin_store, "get_admin_backend", lambda: None)

    cache = IdentityFlagsCache()
    with app.app_context():
        flags = admin_store.resolve_identity_flags(cache, "u1", "u1@example.com")

    assert flags.is_admin is False


def test_a_missing_profile_row_is_cached_because_it_is_a_stable_fact(monkeypatch, app):
    from web.services import admin_store

    class Empty:
        def fetch_identity(self, user_id, email):
            return None

    monkeypatch.setattr(admin_store, "get_admin_backend", lambda: Empty())

    cache = IdentityFlagsCache()
    with app.app_context():
        flags = admin_store.resolve_identity_flags(cache, "u1", "u1@example.com")

    assert flags.is_admin is False
    assert len(cache) == 1


# ── The endpoint tells a reader only about themselves ─────────────────────────


def test_identity_says_nothing_about_anyone_else(client):
    body = client.get("/api/identity", headers=ADMIN).get_json()
    assert set(body) == {"user_id", "email", "role", "tier", "is_admin"}
