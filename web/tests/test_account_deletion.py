"""Self-serve account deletion, web surface (slice 2b of docs/account-and-trust-plan.md).

Each test below fails against today's code, for the reason its own comment
gives: the routes did not exist (404), the step-up check did not exist, the
startup check warned instead of refusing, and `_persist_turn` logged a saga
refusal as a storage failure.

A pending reader CAN cancel and CAN export: that is asserted here through
the ordinary bearer, because the whole point is that NO gate change was
needed — `_gate` refuses only `is_disabled`, which the saga never sets, so a
pending reader authenticates normally and reaches both routes untouched.
(See the brief's verified ground truth; `account_deletion_is_live` folds
into `is_active_account()`, which no Flask gate reads.)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from supabase import AuthApiError
from web.api.app import _persist_turn, create_app
from web.services.chat_store import PersistenceUnavailable
from web.utils.config_loader import config

AUTH = {"Authorization": "Bearer fake_token"}
ADMIN = {"Authorization": "Bearer fake_admin_token"}
READER_B = {"Authorization": "Bearer fake_reader_b_token"}

GRACE = "2026-10-18T00:00:00+00:00"


class _SagaError(Exception):
    """A saga RPC refusal carrying its DL-code, like the real PostgREST error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    """`client.table(...).select(...).eq(...).execute()` chain, recording filters."""

    def __init__(self, client, name):
        self._client = client
        self._name = name
        self._filters: list[tuple] = []

    def select(self, *columns):
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def execute(self):
        self._client.table_calls.append((self._name, list(self._filters)))
        rows = [
            row
            for row in self._client.table_rows
            if all(row.get(column) == value for column, value in self._filters)
        ]
        return _FakeResult(rows)


class _FakeAdminClient:
    """Stands in for the service-role client: RPCs by name, one table."""

    def __init__(self):
        self.rpc_calls: list[tuple] = []
        self.rpc_handlers: dict = {}
        self.table_calls: list[tuple] = []
        self.table_rows: list[dict] = []

    def rpc(self, name, params):
        client = self

        class _Call:
            def execute(self):
                client.rpc_calls.append((name, params))
                handler = client.rpc_handlers.get(name, lambda p: {"ok": True})
                return _FakeResult(handler(params))

        return _Call()

    def table(self, name):
        return _FakeTable(self, name)


@pytest.fixture
def app():
    app = create_app(testing=True)
    app.config["deletion_password_verifier"] = lambda email, password: password == "CorrectPass1"
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client():
    return _FakeAdminClient()


def _request_body(password="CorrectPass1", confirmation="DELETE"):
    return {"password": password, "confirmation": confirmation}


# ── POST /account/api/deletion ──────────────────────────────────────────────


def test_request_requires_a_bearer_token(client):
    """Against today's code this is a 404 (no route); with a gate but no
    step-up it would be a 401 only for the token — the password assertions
    below are what pin the second factor."""
    response = client.post("/account/api/deletion", json=_request_body())
    assert response.status_code == 401


def test_request_rejects_a_missing_password_or_confirmation(client, admin_client):
    """Payload validation runs BEFORE the step-up check and before any RPC."""
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        for body in ({}, {"password": "CorrectPass1"}, {"confirmation": "DELETE"}):
            response = client.post("/account/api/deletion", json=body, headers=AUTH)
            assert response.status_code == 400
    assert admin_client.rpc_calls == []


def test_request_rejects_a_wrong_confirmation_word(client, admin_client):
    """The typed confirmation is checked server-side against the catalogue
    word — a body that guesses the shape but not the word goes nowhere."""
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = client.post(
            "/account/api/deletion", json=_request_body(confirmation="please"), headers=AUTH
        )
    assert response.status_code == 400
    assert admin_client.rpc_calls == []


def test_request_with_a_wrong_password_is_401_and_calls_no_rpc(client, admin_client):
    """Step-up failed: the saga RPC must not run on an unverified request.
    Against today's code the route (and the check) did not exist at all."""
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = client.post(
            "/account/api/deletion", json=_request_body(password="WrongPass1"), headers=AUTH
        )
    assert response.status_code == 401
    assert response.get_json() == {"error": "step_up_failed"}
    assert admin_client.rpc_calls == []


def test_request_success_signs_out_everywhere_and_clears_the_flask_session(
    app, client, admin_client
):
    """The happy path: RPC, then global sign-out by THIS session's JWT (never
    password rotation, never a ban), then the Flask session is cleared. Fails
    today: 404, and no dispatcher call exists to assert."""
    admin_client.rpc_handlers["account_deletion_request"] = lambda p: {
        "user_id": p["p_owner_id"],
        "state": "pending",
        "grace_until": GRACE,
    }
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = client.post("/account/api/deletion", json=_request_body(), headers=AUTH)

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["grace_until"] == GRACE
    assert admin_client.rpc_calls == [("account_deletion_request", {"p_owner_id": "test-user-id"})]
    # Global scope on the requesting session's token — the thief's sessions
    # die with the owner's, and the password is untouched.
    assert "fake_token" in app.config["_testing_auth_admin_dispatcher"].signed_out
    with client.session_transaction() as flask_session:
        assert "auth_identity" not in flask_session


def test_request_is_refused_for_an_administrator(client, admin_client):
    """D1's carve-out, enforced in the RPC body (DL003) and surfaced here as
    a clear 403 — the route does not re-implement the role check."""

    def refuse(params):
        raise _SagaError("DL003")

    admin_client.rpc_handlers["account_deletion_request"] = refuse
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = client.post("/account/api/deletion", json=_request_body(), headers=ADMIN)
    assert response.status_code == 403
    assert response.get_json() == {"error": "deletion_unavailable_for_admin"}


def test_request_for_an_already_deleted_account_has_its_own_code(client, admin_client):
    """DL004 (completed) is neither the admin refusal nor a generic outage."""

    def refuse(params):
        raise _SagaError("DL004")

    admin_client.rpc_handlers["account_deletion_request"] = refuse
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = client.post("/account/api/deletion", json=_request_body(), headers=AUTH)
    assert response.status_code == 410
    assert response.get_json() == {"error": "already_deleted"}


def test_request_without_an_admin_client_is_a_503_not_a_500(client):
    """No service-role client under TESTING — an unavailable dependency, not
    a crash and not a refusal that reads as the reader's fault."""
    response = client.post("/account/api/deletion", json=_request_body(), headers=AUTH)
    assert response.status_code == 503
    assert response.get_json() == {"error": "deletion_unavailable"}


# ── POST /account/api/deletion/cancel ───────────────────────────────────────


def test_cancel_requires_a_bearer_token(client):
    response = client.post("/account/api/deletion/cancel")
    assert response.status_code == 401


def test_cancel_reaches_the_saga_with_the_owner_from_identity(client, admin_client):
    """The owner comes from `g.identity`, never the body — and a pending
    reader arrives here with no gate change at all (the point of the grace
    design). Fails today: 404."""
    admin_client.rpc_handlers["account_deletion_cancel"] = lambda p: {
        "user_id": p["p_owner_id"],
        "state": "cancelled",
    }
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = client.post(
            "/account/api/deletion/cancel", json={"user_id": "someone-else"}, headers=AUTH
        )
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert admin_client.rpc_calls == [("account_deletion_cancel", {"p_owner_id": "test-user-id"})]


def test_cancel_past_the_purge_is_a_409_not_a_silent_success(client, admin_client):
    """DL005: cancelling past the purge would be a lie — there is nothing
    truthful left to cancel back to."""

    def refuse(params):
        raise _SagaError("DL005")

    admin_client.rpc_handlers["account_deletion_cancel"] = refuse
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = client.post("/account/api/deletion/cancel", headers=AUTH)
    assert response.status_code == 409
    assert response.get_json() == {"error": "cancel_unavailable"}


# ── GET /account/api/deletion ───────────────────────────────────────────────


def test_status_requires_a_bearer_token(client):
    response = client.get("/account/api/deletion")
    assert response.status_code == 401


def test_status_with_no_row_is_not_a_404(client, admin_client):
    """Absence of a saga row is an answer (`pending: false`), not a missing
    resource."""
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = client.get("/account/api/deletion", headers=AUTH)
    assert response.status_code == 200
    assert response.get_json() == {"pending": False, "state": "none"}


def test_status_reads_only_the_callers_own_row(client, admin_client):
    """The equality filter is built from `g.identity` — no request-supplied
    id is read, so another account's row is unreachable through this route.
    Fails today: 404, and no table read exists to audit."""
    admin_client.table_rows = [
        {
            "user_id": "test-user-id",
            "state": "pending",
            "grace_until": GRACE,
            "requested_at": "2026-09-18T00:00:00+00:00",
            "purge_after": GRACE,
            "completed_at": None,
        },
        {
            "user_id": "test-reader-b-id",
            "state": "pending",
            "grace_until": GRACE,
            "requested_at": "2026-09-18T00:00:00+00:00",
            "purge_after": GRACE,
            "completed_at": None,
        },
    ]
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = client.get("/account/api/deletion", headers=AUTH)
    assert response.status_code == 200
    body = response.get_json()
    assert body["pending"] is True
    assert body["state"] == "pending"
    assert body["grace_until"] == GRACE
    # The ONLY ownership boundary on this read, and it names the caller.
    assert admin_client.table_calls == [("account_deletions", [("user_id", "test-user-id")])]


# ── What a pending reader can still do ──────────────────────────────────────


def test_export_still_works_over_an_authenticated_session(client):
    """Export is Flask-mediated and must keep working during grace — a reader
    deciding whether to cancel needs to see what they would lose. Reached
    here with the ordinary bearer precisely because pending needs no gate
    exemption: `_gate` refuses only `is_disabled`."""
    response = client.get("/account/api/export", headers=AUTH)
    assert response.status_code == 200
    assert response.mimetype == "application/x-ndjson"


# ── Rate limits are wired ───────────────────────────────────────────────────


@pytest.fixture
def limited_app(monkeypatch):
    monkeypatch.setitem(
        config._config["server"]["rate_limit"], "account_deletion_api", "1 per minute"
    )
    monkeypatch.setitem(
        config._config["server"]["rate_limit"], "account_deletion_status_api", "1 per minute"
    )
    app = create_app(testing=True, enforce_rate_limits=True)
    app.config["_LIMITER_INSTANCE"].reset()
    app.config["deletion_password_verifier"] = lambda email, password: True
    return app


def test_the_request_limit_fires_and_is_keyed_per_reader(limited_app):
    """One request passes, the second is refused — and a DIFFERENT reader is
    not. Fails today: the routes (and their limits) do not exist."""
    fake = _FakeAdminClient()
    fake.rpc_handlers["account_deletion_request"] = lambda p: {"ok": True}
    limited_client = limited_app.test_client()
    with patch("web.api.account.get_supabase_admin", return_value=fake):
        first = limited_client.post(
            "/account/api/deletion", json=_request_body(), headers=AUTH
        ).status_code
        second = limited_client.post(
            "/account/api/deletion", json=_request_body(), headers=AUTH
        ).status_code
        other = limited_client.post(
            "/account/api/deletion", json=_request_body(), headers=READER_B
        ).status_code
    assert first == 200
    assert second == 429
    assert other == 200


def test_status_carries_its_own_looser_limit(limited_app):
    """Status is a separate, looser budget from the mutations — exhausting it
    must not spend the request budget, and vice versa."""
    fake = _FakeAdminClient()
    limited_client = limited_app.test_client()
    with patch("web.api.account.get_supabase_admin", return_value=fake):
        assert limited_client.get("/account/api/deletion", headers=AUTH).status_code == 200
        assert limited_client.get("/account/api/deletion", headers=AUTH).status_code == 429


# ── The signup generic message ──────────────────────────────────────────────


def _signup_client(refusal):
    from unittest.mock import MagicMock

    supabase = MagicMock()
    supabase.auth.sign_up.side_effect = refusal
    return supabase


def test_signup_keeps_its_code_but_never_names_deletion(client):
    """The machine code stays `already_registered` — existing clients branch on
    it — while the RENDERED string must never name deletion.

    REVERSAL, recorded rather than edited away. This test was first written to
    assert the rendered string was GENERIC ("not available for a new account"),
    on the reasoning that during a 30-day grace the email's constraint still
    holds, so saying "already registered" might reveal that a named
    professional had recently deleted their account.

    That reasoning was wrong, and an adversarial review proved it: the
    genuinely-registered case and the pending-deletion case return the SAME
    GoTrue `email_exists` path (`web/api/auth.py:347-348, 372-373`), so nothing
    distinguishes them, and during grace an account really does exist — it can
    still sign in and cancel. The vagueness protected nothing and cost the
    common case its clarity; a reader whose account simply exists was told
    their address was "not available", which reads as a ban.

    So the string says plainly that the address is linked to an account. What
    it must never do is name DELETION, which is what would actually disclose
    something. That is what this test now pins.
    """
    from pathlib import Path

    import yaml

    supabase = _signup_client(AuthApiError("User already registered", 422, "email_exists"))
    with patch("web.api.auth.get_supabase", return_value=supabase):
        response = client.post(
            "/auth/signup",
            json={"email": "taken@example.com", "password": "ValidPass1", "lang": "en"},
        )
    assert response.status_code == 400
    assert response.get_json() == {"error": "already_registered"}

    catalog = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "web" / "i18n" / "en.yaml").read_text(
            encoding="utf-8"
        )
    )
    rendered = catalog["runtime"]["auth"]["alreadyRegistered"]
    # It may say the address is taken; it may NOT say anything about deletion.
    for forbidden in ("delet", "pending", "removed", "closed"):
        assert forbidden not in rendered.lower(), f"signup copy must not name deletion: {rendered}"
    assert "log in" in rendered.lower()


# ── The archive refuse-to-collect ──────────────────────────────────────────
# Slice 2c REVERSED slice 2b's boot refusal into a refusal at the WRITE
# path (`chat_store.archive_keys`). The tests that asserted the raise now
# assert the new contract instead — and they still PROVE the guarantee
# (nothing is collected), not merely that the process stays up.


def test_archive_salts_refuse_collection_not_startup(monkeypatch, caplog):
    """Salts-on with no purge path makes the erasure promise false, so the
    archive write must not happen — but the process must still start. Fails
    against slice 2b's code: `create_app` raised RuntimeError, and
    `archive_keys` returned real digests."""
    import logging

    from web.services import chat_store

    monkeypatch.setenv("ARCHIVE_OWNER_SALT", "x" * 32)
    monkeypatch.setenv("ARCHIVE_SESSION_SALT", "y" * 32)
    monkeypatch.setattr(chat_store, "_archive_no_purge_warned", False)

    app = create_app(testing=True)  # must not raise
    assert app is not None

    with caplog.at_level(logging.ERROR):
        assert chat_store.archive_keys("owner", "session") == (None, None)
        # Loud but once: a second turn must not log a second line.
        assert chat_store.archive_keys("owner", "session") == (None, None)

    refusals = [r for r in caplog.records if "purge path" in r.message]
    assert len(refusals) == 1
    assert refusals[0].levelname == "ERROR"


def test_no_salts_start_normally_and_skip_the_archive(monkeypatch):
    """Unset salts are the supported dormant state: boot, skip, keep the
    reader's history. Fails against slice 2b's code only in the import it
    no longer needs — the behaviour itself is unchanged, which is the
    point: the dormant path was never the problem."""
    from web.services import chat_store

    monkeypatch.delenv("ARCHIVE_OWNER_SALT", raising=False)
    monkeypatch.delenv("ARCHIVE_SESSION_SALT", raising=False)

    app = create_app(testing=True)
    assert app is not None
    assert chat_store.archive_keys("owner", "session") == (None, None)


# ── In-flight stream handling ───────────────────────────────────────────────


def test_a_frozen_owner_refusal_is_a_clean_logged_noop_not_a_storage_failure(app, caplog):
    """`chat_append_turn` raises UDL01 for an owner whose writes are frozen;
    `_persist_turn` must turn that into its ordinary False (the streamed route
    then emits the `persistence_unavailable` frame, the blocking route reports
    `persisted: false`) — logged as the expected saga outcome, not as a
    storage failure.

    Slice 2c narrowed this signal from "any live saga" to "purging/failed":
    a PENDING owner's turn is filed normally and never reaches this branch
    (proven at the SQL level in supabase/tests/account_deletion.test.sql (g)
    and (g2), and by the predicate-text test in
    test_account_deletion_predicates.py). The branch itself is unchanged —
    only which owners arrive here moved — so this test keeps its shape and
    changes its name and its reason.
    """
    import logging

    class _RefusingBackend:
        def append_turn(self, **kwargs):
            raise PersistenceUnavailable("UDL01 DL001: refused for a pending owner")

    with app.app_context(), caplog.at_level(logging.WARNING):
        assert (
            _persist_turn(
                _RefusingBackend(),
                owner_id="owner",
                conversation_id="conv",
                client_request_id="req",
                question="q",
                answer="a",
                sources=[],
                lang="en",
                category="all",
                model="m",
            )
            is False
        )
    assert any("live deletion saga" in record.message for record in caplog.records)


# ── Browser: the card renders ───────────────────────────────────────────────
# The harness cannot mint a pending JWT, so the deep assertions belong in
# supabase/tests/ — this only pins that the destructive-pattern card and its
# truthful disclosure ship in the DOM both languages render from.


@pytest.mark.browser
def test_the_deletion_section_renders(browser_page):
    browser_page.goto("/account")
    content = browser_page.content()
    assert "Delete your account" in content
    assert "deletion-confirm" in content
    assert "deletion-password" in content


# ── Grace copy: fully usable, with the one carve-out named ──────────────────
# Slice 2c reversed the freeze: a pending account is a normal account with a
# scheduled deletion, and the copy that claimed "you cannot start new
# conversations" is false in the other direction now. These pin the
# replacement wording in both catalogues — usable (sign in, chat, read,
# export, profile, cancel) without overclaiming "everything" (granting new
# marketing consent stays off while deletion is pending, per 14).


def _catalog(lang):
    from pathlib import Path

    import yaml

    return yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "web" / "i18n" / f"{lang}.yaml").read_text(
            encoding="utf-8"
        )
    )


def test_grace_copy_says_fully_usable_and_names_the_consent_carve_out():
    """Fails against the pre-2c copy, which forbade new conversations and
    profile changes during grace."""
    en = _catalog("en")

    for text in (
        en["page"]["account"]["deletionLead"],
        en["page"]["account"]["deletionPendingBody"],
        en["runtime"]["profile"]["account"]["deletionPendingBody"],
        en["page"]["policy"]["retentionBody"],
    ):
        assert "cannot start new conversations" not in text
        assert "chat" in text.lower()

    assert "marketing consent" in en["page"]["account"]["deletionLead"]
    assert "marketing consent" in en["page"]["policy"]["retentionBody"]


def test_grace_copy_parity_in_arabic():
    """The Arabic side must make the same two claims — usable, with the
    carve-out — not merely carry the same keys (which the parity test
    already proves). Fails against the pre-2c Arabic copy."""
    ar = _catalog("ar")

    for text in (
        ar["page"]["account"]["deletionLead"],
        ar["page"]["account"]["deletionPendingBody"],
        ar["runtime"]["profile"]["account"]["deletionPendingBody"],
        ar["page"]["policy"]["retentionBody"],
    ):
        assert "لا يمكنك بدء محادثات جديدة" not in text
        assert "حادث" in text or "محادث" in text

    # The root, not a fixed form: a human reviewer rewrote this copy and used
    # "موافقة تسويقية" where the machine draft had "الموافقة التسويقية". Both name
    # the carve-out, which is the claim under test — pinning one inflection
    # would fail good Arabic for a grammatical reason the test does not care
    # about.
    assert "تسويق" in ar["page"]["account"]["deletionLead"]
