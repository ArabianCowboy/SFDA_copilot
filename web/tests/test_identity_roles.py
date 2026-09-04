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


def test_a_disabled_account_stays_disabled_through_a_lookup_failure(monkeypatch, app):
    """The hole this closes: an outage used to readmit every suspended account.

    "We could not check" and "we checked, they are fine" were the same value —
    `is_disabled=False` — so nothing downstream could tell them apart, and a
    Supabase hiccup silently let a disabled reader back in.
    """
    from web.services import admin_store

    # ttl=0 so the entry is immediately stale: resolve() must take the fetch
    # path, fail, and fall back to what it last knew.
    cache = IdentityFlagsCache(ttl_seconds=0)
    cache.put(IdentityFlags("u1", "u1@example.com", "user", "free", is_disabled=True))

    class Broken:
        def fetch_identity(self, user_id, email):
            raise RuntimeError("supabase is down")

    monkeypatch.setattr(admin_store, "get_admin_backend", lambda: Broken())

    with app.app_context():
        flags = admin_store.resolve_identity_flags(cache, "u1", "u1@example.com")

    assert flags.is_disabled is True, "a known-disabled reader must not be readmitted"
    assert flags.is_resolved is False, "and the answer must be marked as stale"


def test_an_unresolved_identity_is_never_an_administrator(monkeypatch, app):
    """Privilege requires an answer, not the absence of one.

    Even a remembered admin, republished after a failed lookup, loses the
    console — the safe reading of "we could not check" is the unprivileged one.
    """
    from web.services import admin_store

    cache = IdentityFlagsCache(ttl_seconds=0)
    cache.put(IdentityFlags("u1", "u1@example.com", "admin", "staff", False))

    class Broken:
        def fetch_identity(self, user_id, email):
            raise RuntimeError("down")

    monkeypatch.setattr(admin_store, "get_admin_backend", lambda: Broken())

    with app.app_context():
        flags = admin_store.resolve_identity_flags(cache, "u1", "u1@example.com")

    assert flags.role == "admin"
    assert flags.is_resolved is False
    assert flags.is_admin is False, "an unconfirmed admin is not an admin"


def test_a_slow_older_lookup_cannot_overwrite_a_newer_one(monkeypatch):
    """Two concurrent misses can finish out of order.

    Without ordering by when the fetch STARTED, the older answer wins and is
    given a full fresh TTL — so a demotion observed by the newer request is
    undone by the older one.
    """
    clock = {"t": 1000.0}
    monkeypatch.setattr(IdentityFlagsCache, "_now", staticmethod(lambda: clock["t"]))
    cache = IdentityFlagsCache()

    old_started = cache.begin_fetch()
    clock["t"] += 1
    new_started = cache.begin_fetch()

    # The newer fetch lands first.
    assert cache.put(_flags("u1", "user"), fetched_at=new_started) is True
    # The older one arrives late carrying the pre-demotion answer.
    assert cache.put(_flags("u1", "admin"), fetched_at=old_started) is False

    assert cache.get("u1").role == "user"


def test_invalidating_beats_a_lookup_already_in_flight(monkeypatch):
    """`invalidate()` cannot stop a SELECT that has already been issued.

    Without this, the console demotes someone, and a request that was mid-lookup
    republishes their old role with a fresh TTL — restoring exactly what was
    just revoked.
    """
    clock = {"t": 1000.0}
    monkeypatch.setattr(IdentityFlagsCache, "_now", staticmethod(lambda: clock["t"]))
    cache = IdentityFlagsCache()

    started = cache.begin_fetch()  # a lookup begins
    clock["t"] += 1
    cache.invalidate("u1")  # an operator demotes them meanwhile
    clock["t"] += 1

    assert cache.put(_flags("u1", "admin"), fetched_at=started) is False
    assert cache.get("u1") is None


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
    assert set(body) == {
        "user_id",
        "email",
        "role",
        "tier",
        "is_admin",
        "is_disabled",
        # Both back the /account standing line. Null under TESTING — no
        # service-role key means get_admin_backend() returns None — which is
        # the honest answer, not an omission of the key.
        "created_at",
        "conversation_count",
        # The daily allowance. Present under TESTING because `quota_backend()`
        # resolves to the in-memory double rather than None -- deliberately, so
        # a regression in this field cannot hide behind a null.
        "quota",
    }
    assert body["created_at"] is None
    assert body["conversation_count"] is None


def test_identity_quota_reports_only_this_reader(client):
    """The quota block carries counts and labels — never operator notes."""
    quota = client.get("/api/identity", headers=ADMIN).get_json()["quota"]
    assert set(quota) == {
        "used",
        "limit",
        "remaining",
        "resets_at",
        "tier",
        "override",
        "override_expires_at",
    }
    assert set(quota["tier"]) == {"key", "label_en", "label_ar"}
    # `reason` and `set_by` live on reader_quota_overrides and are an operator's
    # private note about an account. `get_reader_quota` does not select them, and
    # this asserts the shape stays that way.
    assert "reason" not in quota
    assert "set_by" not in quota


def test_identity_quota_starts_from_this_readers_own_usage(client):
    """A fresh reader has spent nothing, and `remaining` agrees with `limit`."""
    quota = client.get("/api/identity", headers=ADMIN).get_json()["quota"]
    assert quota["used"] == 0
    assert quota["remaining"] == quota["limit"]
    assert quota["limit"] > 0
    assert quota["resets_at"]


# ── touch_last_seen: its own try, never sharing the standing-line facts one ───


def test_identity_touches_last_seen_when_a_backend_is_present(monkeypatch, client):
    """The write half of docs/data-policy-decisions.md's §4, from the route."""
    from web.services import admin_store

    touched = []

    class Backend:
        def touch_last_seen(self, user_id):
            touched.append(user_id)

        def get_standing_line_facts(self, user_id):
            return {"created_at": "2026-01-01T00:00:00+00:00", "conversation_count": 3}

    monkeypatch.setattr(admin_store, "get_admin_backend", lambda: Backend())

    body = client.get("/api/identity", headers=AUTH).get_json()

    assert touched == ["test-user-id"]
    assert body["created_at"] == "2026-01-01T00:00:00+00:00"
    assert body["conversation_count"] == 3


def test_a_failing_touch_last_seen_does_not_blank_out_standing_line_facts(monkeypatch, client):
    """The regression two separate `try` blocks exist to prevent.

    A shared `try` would let a throttled-write failure suppress facts that
    loaded fine and have nothing to do with it — caught independently by both
    delegate reviews of the plan (see "What the review changed").
    """
    from web.services import admin_store

    class Backend:
        def touch_last_seen(self, user_id):
            raise RuntimeError("touch_last_seen is down")

        def get_standing_line_facts(self, user_id):
            return {"created_at": "2026-01-01T00:00:00+00:00", "conversation_count": 3}

    monkeypatch.setattr(admin_store, "get_admin_backend", lambda: Backend())

    response = client.get("/api/identity", headers=AUTH)

    assert response.status_code == 200
    body = response.get_json()
    assert body["created_at"] == "2026-01-01T00:00:00+00:00"
    assert body["conversation_count"] == 3


def test_a_failing_standing_line_lookup_does_not_skip_the_touch(monkeypatch, client):
    """The other half of the same guarantee, in the other direction."""
    from web.services import admin_store

    touched = []

    class Backend:
        def touch_last_seen(self, user_id):
            touched.append(user_id)

        def get_standing_line_facts(self, user_id):
            raise RuntimeError("get_standing_line_facts is down")

    monkeypatch.setattr(admin_store, "get_admin_backend", lambda: Backend())

    response = client.get("/api/identity", headers=AUTH)

    assert response.status_code == 200
    assert touched == ["test-user-id"]
    body = response.get_json()
    assert body["created_at"] is None
    assert body["conversation_count"] is None
