"""Registrations pause — docs/registrations-pause-plan.md.

Three layers, each with its own tests: the `SettingsService` key family that
stores and caches the flag; the `/auth/signup` gate that reads it before any
provider work; and the `/admin/api/registrations` endpoint an operator uses to
flip it. `web/tests/test_admin_settings.py` is the sibling file for the
generation-settings half of `SettingsService` and sets the conventions this
file follows.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from supabase_auth.errors import AuthApiError, AuthWeakPasswordError

from web.api.app import create_app
from web.services.admin_store import InMemoryAdminBackend
from web.services.audit import AuditActor
from web.services.settings_service import (
    SettingsService,
    deployed_defaults,
    deployed_non_generation_defaults,
)

ADMIN = {"Authorization": "Bearer fake_admin_token"}
AUTH = {"Authorization": "Bearer fake_token"}
ACTOR = AuditActor("admin-id", "admin@example.com", "127.0.0.1", "pytest")


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def service():
    backend = InMemoryAdminBackend()
    return SettingsService(backend_provider=lambda: backend)


# ── SettingsService: the NON_GENERATION_KEYS family ─────────────────────────


def test_an_untouched_instance_is_open(service):
    assert service.signup_enabled() is deployed_non_generation_defaults()["signup_enabled"]


def test_signup_enabled_is_absent_from_the_generation_snapshot_and_overrides(service):
    service.set_signup_enabled(False, actor=ACTOR)

    assert "signup_enabled" not in service.snapshot()
    assert "signup_enabled" not in service.overrides()
    assert service.snapshot() == deployed_defaults()


@pytest.mark.parametrize("value", [1, 0, "true", "false", [], None, {}])
def test_a_non_boolean_is_refused(service, value):
    if value is None:
        # None is the "revert to default" convention, not a value to refuse —
        # covered by test_null_reverts_to_the_deployed_default below.
        pytest.skip("None removes the override; see the dedicated test")
    errors = service.set_signup_enabled(value, actor=ACTOR)
    assert errors and errors[0].code == "not_a_boolean"
    # Refused means refused: nothing was written.
    assert service.signup_enabled() is deployed_non_generation_defaults()["signup_enabled"]


def test_null_reverts_to_the_deployed_default(service):
    service.set_signup_enabled(False, actor=ACTOR)
    assert service.signup_enabled() is False

    errors = service.set_signup_enabled(None, actor=ACTOR)
    assert errors == []
    assert service.signup_enabled() is deployed_non_generation_defaults()["signup_enabled"]


def test_a_write_is_visible_immediately(service):
    """Publish-on-write, not TTL expiry, is the propagation mechanism on a
    single-worker deployment — the whole reason this has its own cache slot
    rather than sharing the generation TTL wholesale."""
    errors = service.set_signup_enabled(False, actor=ACTOR)
    assert errors == []
    assert service.signup_enabled() is False


def test_the_flag_cache_expires(service, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(SettingsService, "_now", staticmethod(lambda: clock["t"]))

    service.set_signup_enabled(False, actor=ACTOR)
    assert service.signup_enabled() is False

    # An out-of-band edit — the console cannot know about this one, so the
    # cache, not publish-on-write, is what eventually notices it.
    service._backend.put_settings(
        {"signup_enabled": True}, actor=ACTOR, before={}, after={"signup_enabled": True}
    )
    clock["t"] += 44
    assert service.signup_enabled() is False, "still within the TTL"
    clock["t"] += 2
    assert service.signup_enabled() is True, "the TTL has elapsed"


def test_a_generation_save_invalidates_the_flag_cache(service):
    """`update()` rewrites the WHOLE row, including whatever `signup_enabled`
    already held — a write to the flag's storage even though the patch never
    named it. Missing this invalidation is the one bug this design cannot
    afford (docs/registrations-pause-plan.md §9 Step 8)."""
    service.set_signup_enabled(False, actor=ACTOR)
    assert service.signup_enabled() is False

    # Flip the row directly, bypassing the service — simulating an operator's
    # generation save landing between two reads of the flag.
    backend = service._backend
    stored = dict(backend.get_settings())
    stored["signup_enabled"] = True
    backend.put_settings(stored, actor=ACTOR, before={}, after=stored)

    # Without invalidation this would still read the pre-flip cached False.
    service._invalidate_operational_cache()
    assert service.signup_enabled() is True

    # And the real path: a generation update() call invalidates it itself.
    # The cached value is left DIVERGENT from the stored one first — True
    # cached, False stored — so a re-read after invalidation is the only way
    # the assertion below can come out False. A patch that removed the
    # `_invalidate_operational_cache()` call inside `update()` would still
    # pass a version of this test that left the two values equal, which is
    # exactly the shape opencode's review flagged as unable to distinguish
    # "invalidated and correctly re-read" from "never invalidated, stale
    # value happens to already be right".
    service.set_signup_enabled(True, actor=ACTOR)
    assert service.signup_enabled() is True
    backend.put_settings({"signup_enabled": False}, actor=ACTOR, before={}, after={})
    service.update({"model": "gpt-4o"}, actor=ACTOR)
    assert service.signup_enabled() is False


def test_a_read_failure_serves_the_last_known_value(service):
    service.set_signup_enabled(False, actor=ACTOR)
    assert service.signup_enabled() is False

    with patch.object(service._backend, "get_settings", side_effect=RuntimeError("boom")):
        # A pause must survive a Supabase blip: the last known value, however
        # stale, not a fabricated "open".
        assert service.signup_enabled() is False


def test_a_read_failure_right_after_a_generation_save_still_serves_the_stale_value(service):
    """Regression: `_invalidate_operational_cache` used to clear the cached
    VALUE, not just its freshness. A generation save that happened to be
    followed by a read failure then answered `None` (undetermined, `503`)
    instead of the last known value — exactly the fabricated-outage failure
    mode `signup_enabled` exists to avoid. Found in review (opencode,
    2026-08-25)."""
    service.set_signup_enabled(False, actor=ACTOR)
    assert service.signup_enabled() is False

    service.update({"model": "gpt-4o"}, actor=ACTOR)  # invalidates the flag's cache

    with patch.object(service._backend, "get_settings", side_effect=RuntimeError("boom")):
        assert service.signup_enabled() is False, (
            "a cache invalidated by an unrelated save must still fall back to "
            "the last known value on a read failure, not answer undetermined"
        )


def test_a_slow_read_in_flight_does_not_clobber_a_concurrent_publish(service):
    """Regression: `signup_enabled()`'s store read happens outside the lock
    (deliberately — I/O must not block every other reader). A read that
    started before a `set_signup_enabled` call published a newer value, but
    finishes after, used to overwrite that fresh value with the stale one it
    started with. Found in review (agy, 2026-08-25).

    Simulated deterministically: the backend's `get_settings` triggers the
    concurrent publish itself, mid-read, rather than relying on real thread
    scheduling to land the race.
    """
    service.set_signup_enabled(True, actor=ACTOR)
    assert service.signup_enabled() is True
    # Force the next read to miss the cache and go to the backend.
    service._invalidate_operational_cache()

    real_get_settings = service._backend.get_settings
    raced = False

    def racing_get_settings():
        # "Another thread" wins the race and publishes a fresh value while
        # THIS read is already in flight, reading the OLD stored value.
        # Fires exactly once: `set_signup_enabled` below does its OWN read
        # of the (still-patched) backend, and without this guard that
        # nested read would trigger the race again — a second, nested
        # `set_signup_enabled` call that then self-deadlocks trying to
        # re-acquire the `_write_lock` its own caller already holds.
        nonlocal raced
        value = real_get_settings()
        if not raced:
            raced = True
            service.set_signup_enabled(False, actor=ACTOR)
        return value

    with patch.object(service._backend, "get_settings", side_effect=racing_get_settings):
        result = service.signup_enabled()

    # Whichever of the two calls returns last, the cache must end up holding
    # the value that was actually published LAST (False), never clobbered
    # back to the stale True the slow read started with.
    assert result is False
    assert service.signup_enabled() is False


def test_a_cold_read_failure_is_undetermined():
    """A process that has NEVER successfully read the flag cannot honestly
    answer True or False — answering the deployed default here would be a
    fabricated "open" during a cold-start outage."""
    backend = MagicMock()
    backend.get_settings.side_effect = RuntimeError("boom")
    service = SettingsService(backend_provider=lambda: backend)

    assert service.signup_enabled() is None


def test_a_backend_provider_that_raises_does_not_500_every_page():
    """Regression (/code-review, 2026-08-26): `self._backend` used to be read
    OUTSIDE the try block — a present-but-malformed SUPABASE_URL/key raises
    from `create_client()` inside the provider closure, not just from
    `get_settings()`, and that raise reached every caller uncaught. Since
    `base_render_context()` calls `signup_enabled()` on EVERY page render
    (including /admin and /account, which never read the result), an
    unguarded raise here would take down the whole site, not just signup."""

    def raising_provider():
        raise RuntimeError("create_client: invalid URL")

    service = SettingsService(backend_provider=raising_provider)
    assert service.signup_enabled() is None  # undetermined, not a raised exception


def test_no_backend_answers_the_deployed_default():
    """No service-role key configured: nothing could ever have been written,
    so there is nothing to disagree with — the same reasoning
    `read_overrides` already gives for the generation keys."""
    service = SettingsService(backend_provider=lambda: None)
    assert service.signup_enabled() is deployed_non_generation_defaults()["signup_enabled"]


def test_a_malformed_stored_value_reverts_to_the_default(service):
    backend = service._backend
    backend.put_settings({"signup_enabled": "not-a-bool"}, actor=ACTOR, before={}, after={})
    assert service.signup_enabled() is deployed_non_generation_defaults()["signup_enabled"]


def test_a_flag_write_does_not_rebuild_the_handler(service):
    calls = []
    errors = service.update({"model": "gpt-4o"}, actor=ACTOR, on_committed=lambda: calls.append(1))
    assert errors == []
    assert calls == [1], "a generation save still applies, for the regression this guards"

    calls.clear()
    # set_signup_enabled has no on_committed parameter at all — the absence
    # itself is the guarantee nothing here can ever rebuild generation.
    service.set_signup_enabled(True, actor=ACTOR)
    assert calls == []


def test_a_write_with_no_storage_is_refused():
    service = SettingsService(backend_provider=lambda: None)
    errors = service.set_signup_enabled(False, actor=ACTOR)
    assert errors and errors[0].code == "storage_unavailable"


# ── The gate: POST /auth/signup ─────────────────────────────────────────────


def _pause(app):
    app.config["settings_service"].set_signup_enabled(False, actor=ACTOR)


def test_a_paused_instance_refuses_signup(app, client):
    _pause(app)

    with patch("web.api.auth.get_supabase") as mock_get_supabase:
        response = client.post(
            "/auth/signup", json={"email": "new@example.com", "password": "ValidPass1"}
        )

    assert response.status_code == 403
    assert response.get_json() == {"error": "signup_disabled"}
    # The status alone does not prove the gate ran BEFORE provider work — the
    # actual requirement (docs/registrations-pause-plan.md §9 Step 9).
    mock_get_supabase.assert_not_called()


def test_a_pause_that_lands_mid_request_still_stops_the_network_call(app, client):
    """The gate is re-read immediately before the network call, not just once
    at the top of the view — narrowing (not eliminating; see the code comment
    for why full elimination is rejected) the window in which a pause that
    lands mid-request still lets a signup through. Found in review
    (/code-review, 2026-08-26)."""
    broken = MagicMock()
    # Open on the first read (the primary gate, at the top of the view),
    # paused on the second (immediately before the network call) — simulating
    # an operator's pause landing while this request was already in flight.
    broken.signup_enabled.side_effect = [True, False]
    app.config["settings_service"] = broken

    supabase = MagicMock()
    with patch("web.api.auth.get_supabase", return_value=supabase):
        response = client.post(
            "/auth/signup", json={"email": "new@example.com", "password": "ValidPass1"}
        )

    assert response.status_code == 403
    assert response.get_json() == {"error": "signup_disabled"}
    supabase.auth.sign_up.assert_not_called()


def test_an_open_instance_still_creates_an_account(client):
    user = MagicMock(id="u1", email="new@example.com")
    response_obj = MagicMock(error=None, user=user)
    supabase = MagicMock()
    supabase.auth.sign_up.return_value = response_obj

    with patch("web.api.auth.get_supabase", return_value=supabase):
        response = client.post(
            "/auth/signup", json={"email": "new@example.com", "password": "ValidPass1"}
        )

    assert response.status_code == 201
    assert response.get_json()["user"]["email"] == "new@example.com"


def test_an_undetermined_flag_is_a_503_not_a_403(app, client):
    broken = MagicMock()
    broken.signup_enabled.return_value = None
    app.config["settings_service"] = broken

    with patch("web.api.auth.get_supabase") as mock_get_supabase:
        response = client.post(
            "/auth/signup", json={"email": "new@example.com", "password": "ValidPass1"}
        )

    assert response.status_code == 503
    assert response.get_json() == {"error": "auth_unavailable"}
    mock_get_supabase.assert_not_called()


def test_a_blank_password_is_still_a_400_while_paused(app, client):
    """Malformed before paused: a blank password is wrong regardless, and
    should not spend a settings read at all."""
    _pause(app)
    broken = app.config["settings_service"]
    original = broken.signup_enabled
    calls = []

    def spy():
        calls.append(1)
        return original()

    broken.signup_enabled = spy

    response = client.post("/auth/signup", json={"email": "new@example.com", "password": ""})
    assert response.status_code == 400
    assert response.get_json() == {"error": "missing_fields"}
    assert calls == [], "a malformed request must not spend a settings read"


@pytest.mark.parametrize("bad_lang", [123, True, ["en"], {"lang": "en"}, 1.5])
def test_a_non_string_lang_is_a_400_not_a_503(client, bad_lang):
    """Regression: a non-string `lang` used to reach `quote()` unguarded in
    `signup_redirect_url`, raise `TypeError`, and get reported as a `503
    provider_unavailable` — a malformed client request read as an upstream
    outage. Found in review (agy, 2026-08-25)."""
    with patch("web.api.auth.get_supabase") as mock_get_supabase:
        response = client.post(
            "/auth/signup",
            json={"email": "new@example.com", "password": "ValidPass1", "lang": bad_lang},
        )

    assert response.status_code == 400
    assert response.get_json() == {"error": "missing_fields"}
    mock_get_supabase.assert_not_called()


def test_a_missing_or_null_lang_is_still_accepted(client):
    """The browser sometimes sends no lang at all; must not regress to 400."""
    supabase = MagicMock()
    supabase.auth.sign_up.return_value = MagicMock(
        error=None, user=MagicMock(id="u1", email="new@example.com")
    )
    with patch("web.api.auth.get_supabase", return_value=supabase):
        response = client.post(
            "/auth/signup", json={"email": "new@example.com", "password": "ValidPass1"}
        )
    assert response.status_code == 201


# No `test_signup_is_rate_limited` here. `create_app` sets
# `RATELIMIT_ENABLED=not testing` (app.py, `_configure_app`), and
# Flask-Limiter reads that once at `init_app` and binds it to `self.enabled`
# — there is no live app.config it re-reads per request, and the extension
# instance itself is never retained anywhere `create_app`'s caller can reach
# to flip it back on for one test. That is a real gap (recover_api's own
# rate limit has never had a test either, for the same reason), not
# something this migration introduces; noted rather than worked around with
# something that reaches into flask_limiter's private state.


def test_only_allow_listed_metadata_keys_are_forwarded(client):
    supabase = MagicMock()
    supabase.auth.sign_up.return_value = MagicMock(
        error=None, user=MagicMock(id="u1", email="new@example.com")
    )

    with patch("web.api.auth.get_supabase", return_value=supabase):
        client.post(
            "/auth/signup",
            json={
                "email": "new@example.com",
                "password": "ValidPass1",
                "first_name": "Amina",
                "family_name": "",
                "marketing_consent": False,
                "is_admin_hint": True,  # NOT allow-listed — must not be forwarded
                "role": "admin",  # NOT allow-listed
            },
        )

    sent = supabase.auth.sign_up.call_args[0][0]
    metadata = sent["options"]["data"]
    assert metadata == {"first_name": "Amina", "family_name": "", "marketing_consent": False}


# ── Real GoTrue refusals: sign_up() RAISES, it never returns .error ────────
#
# Regression for a real bug (found by /code-review, 2026-08-26): the installed
# `supabase_auth` 2.31.0's `sign_up()` either succeeds or raises an `AuthError`
# subclass — it never returns a response with a populated `.error` attribute.
# Every test above that mocks a refusal via `MagicMock(error=...)` was
# therefore testing a shape the real SDK never produces, and the original
# `except Exception:` swallowed every real refusal (a duplicate email, a weak
# password, a rate limit) into `503 provider_unavailable` — telling a reader
# whose signup was correctly refused that the service was down instead.


def test_a_duplicate_email_is_reported_by_gotrues_own_code_not_swallowed(client):
    supabase = MagicMock()
    supabase.auth.sign_up.side_effect = AuthApiError("User already registered", 422, "email_exists")
    with patch("web.api.auth.get_supabase", return_value=supabase):
        response = client.post(
            "/auth/signup", json={"email": "new@example.com", "password": "ValidPass1"}
        )
    assert response.status_code == 400
    assert response.get_json() == {"error": "already_registered"}


def test_a_weak_password_is_reported_not_swallowed(client):
    supabase = MagicMock()
    supabase.auth.sign_up.side_effect = AuthWeakPasswordError(
        "Password should be at least 8 characters", 422, ["length"]
    )
    with patch("web.api.auth.get_supabase", return_value=supabase):
        response = client.post("/auth/signup", json={"email": "new@example.com", "password": "x"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "weak_password"}


def test_a_gotrue_rate_limit_is_a_429_not_a_400(client):
    supabase = MagicMock()
    supabase.auth.sign_up.side_effect = AuthApiError(
        "Email rate limit exceeded", 429, "over_email_send_rate_limit"
    )
    with patch("web.api.auth.get_supabase", return_value=supabase):
        response = client.post(
            "/auth/signup", json={"email": "new@example.com", "password": "ValidPass1"}
        )
    assert response.status_code == 429
    assert response.get_json() == {"error": "email_unavailable"}


def test_a_gotrue_side_hard_close_maps_onto_the_same_code_as_our_own_pause(client):
    """An operator who used the dashboard/Management-API hard close
    (docs/OPERATIONS.md) gets GoTrue refusing signup directly — this must
    read the same to a reader as our own console-driven pause, not a
    different, confusing refusal."""
    supabase = MagicMock()
    supabase.auth.sign_up.side_effect = AuthApiError(
        "Signups not allowed for this instance", 422, "signup_disabled"
    )
    with patch("web.api.auth.get_supabase", return_value=supabase):
        response = client.post(
            "/auth/signup", json={"email": "new@example.com", "password": "ValidPass1"}
        )
    assert response.status_code == 403
    assert response.get_json() == {"error": "signup_disabled"}


def test_an_unrecognised_gotrue_code_falls_back_to_the_message_heuristic(client):
    supabase = MagicMock()
    supabase.auth.sign_up.side_effect = AuthApiError(
        "For security purposes, you can only request this after 41 seconds", 429, None
    )
    with patch("web.api.auth.get_supabase", return_value=supabase):
        response = client.post(
            "/auth/signup", json={"email": "new@example.com", "password": "ValidPass1"}
        )
    assert response.status_code == 429
    assert response.get_json() == {"error": "too_soon"}


def test_a_true_provider_outage_is_still_503(client):
    """Not every raised exception is an AuthError — a bare network failure
    must still read as an outage, not a refusal."""
    supabase = MagicMock()
    supabase.auth.sign_up.side_effect = ConnectionError("boom")
    with patch("web.api.auth.get_supabase", return_value=supabase):
        response = client.post(
            "/auth/signup", json={"email": "new@example.com", "password": "ValidPass1"}
        )
    assert response.status_code == 503
    assert response.get_json() == {"error": "provider_unavailable"}


# ── GET/PUT /admin/api/registrations ────────────────────────────────────────


def test_registrations_are_readable_by_an_administrator(client):
    body = client.get("/admin/api/registrations", headers=ADMIN).get_json()
    assert body == {"signup_enabled": True, "default": True}


def test_the_toggle_requires_a_bearer_header(client):
    assert client.get("/admin/api/registrations").status_code == 401
    assert client.put("/admin/api/registrations", json={"signup_enabled": False}).status_code == 401


def test_a_reader_cannot_toggle_registrations(client):
    assert client.get("/admin/api/registrations", headers=AUTH).status_code == 403
    response = client.put("/admin/api/registrations", json={"signup_enabled": False}, headers=AUTH)
    assert response.status_code == 403


def test_a_valid_toggle_returns_the_new_state(client):
    response = client.put("/admin/api/registrations", json={"signup_enabled": False}, headers=ADMIN)
    assert response.status_code == 200
    assert response.get_json() == {"signup_enabled": False, "default": True}


def test_an_invalid_toggle_is_a_422(client):
    response = client.put(
        "/admin/api/registrations", json={"signup_enabled": "nope"}, headers=ADMIN
    )
    assert response.status_code == 422
    assert response.get_json() == {"error": "invalid_signup_enabled"}


def test_a_non_object_payload_is_rejected(client):
    assert client.put("/admin/api/registrations", json=["nope"], headers=ADMIN).status_code == 400
    assert client.put("/admin/api/registrations", json={}, headers=ADMIN).status_code == 400


def test_the_toggle_writes_an_audit_row(app, client):
    client.put("/admin/api/registrations", json={"signup_enabled": False}, headers=ADMIN)

    backend = app.config["_testing_admin_backend"]
    rows = backend.list_audit(limit=5, offset=0)
    assert rows, "the pause must be audited"
    latest = rows[0]
    assert latest["action"] == "settings.update"
    assert latest["after"].get("signup_enabled") is False


def test_the_toggle_never_rebuilds_the_generation_handler(app, client):
    calls = {"n": 0}
    real_factory = app.config["openai_handler_factory"]

    def counting_factory(settings):
        calls["n"] += 1
        return real_factory(settings)

    app.config["openai_handler_factory"] = counting_factory

    client.put("/admin/api/registrations", json={"signup_enabled": False}, headers=ADMIN)
    assert calls["n"] == 0

    client.put("/admin/api/settings", json={"model": "gpt-4o"}, headers=ADMIN)
    assert calls["n"] == 1, "a generation save must still rebuild the handler"


# ── Server-rendered proactive state ─────────────────────────────────────────


def test_a_paused_page_renders_the_notice_and_hides_the_form(app, client):
    _pause(app)
    html = client.get("/").get_data(as_text=True)
    assert 'id="signup-paused" class="signup-paused-notice "' in html
    assert 'id="signup-form" class="d-none"' in html


def test_an_open_page_hides_the_notice_and_shows_the_form(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="signup-paused" class="signup-paused-notice d-none"' in html
    assert 'id="signup-form" class="" novalidate>' in html
    assert "signup-tab-paused-dot" not in html


def test_a_paused_page_marks_the_signup_tab(app, client):
    _pause(app)
    html = client.get("/").get_data(as_text=True)
    assert "signup-tab-paused-dot" in html


def test_an_undetermined_flag_still_renders_the_form(app, client):
    broken = MagicMock()
    broken.signup_enabled.return_value = None
    app.config["settings_service"] = broken

    html = client.get("/").get_data(as_text=True)
    assert 'id="signup-paused" class="signup-paused-notice d-none"' in html
    assert 'id="signup-form" class="" novalidate>' in html
