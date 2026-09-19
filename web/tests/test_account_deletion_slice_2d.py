"""Slice 2d: fixes from the second adversarial review of account deletion.

Each test fails against the pre-2d code, for the reason its own comment
gives. Two existing tests in `test_admin_deletions.py` change shape with the
two-row reconcile audit (requested first, outcome after) and are updated
there, not here.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from web.api.account import _saga_error_code
from web.api.app import create_app

AUTH = {"Authorization": "Bearer fake_token"}
ADMIN = {"Authorization": "Bearer fake_admin_token"}

SUPABASE = Path(__file__).resolve().parents[2] / "supabase"
PENDING = SUPABASE / "pending"


def _migration(name: str) -> Path:
    """One migration file, wherever it currently lives.

    A migration moves. It is drafted in `supabase/pending/` under an ordinal,
    and the moment it is applied the filename rule renames it to the version
    `list_migrations` reports and `git mv`s it into `supabase/migrations/`
    (`supabase/README.md`). These assertions are about the SQL, not about which
    directory it is sitting in today, so the lookup follows it: exact name in
    `pending/` first, then a suffix match in `migrations/`, where the ordinal
    prefix has been replaced by a timestamp and the tail may have been renamed
    with it.
    """
    exact = PENDING / name
    if exact.exists():
        return exact
    tail = name.split("_", 1)[1]
    stem = tail.removesuffix(".sql")
    for candidate in sorted((SUPABASE / "migrations").glob("*.sql")):
        if candidate.name.endswith(tail) or stem in candidate.name:
            return candidate
    # Renamed on apply beyond a suffix match: fall back to the closest stem.
    words = [w for w in stem.split("_") if len(w) > 3]
    for candidate in sorted((SUPABASE / "migrations").glob("*.sql")):
        if sum(w in candidate.name for w in words) >= max(2, len(words) - 2):
            return candidate
    raise FileNotFoundError(f"no migration matching {name} in pending/ or migrations/")


STATIC_ACCOUNT = Path(__file__).resolve().parents[2] / "static" / "js" / "account"


class _SagaError(Exception):
    """A saga RPC refusal carrying its DL-code, like the real PostgREST error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeTable:
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
def switched_off_app(app):
    """The pre-launch posture: the code is deployed, the switch is off."""
    app.config["DELETION_SELF_SERVE_ENABLED"] = False
    return app


@pytest.fixture
def switched_off_client(switched_off_app):
    return switched_off_app.test_client()


@pytest.fixture
def admin_client():
    return _FakeAdminClient()


def _catalog(lang):
    return yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "web" / "i18n" / f"{lang}.yaml").read_text(
            encoding="utf-8"
        )
    )


def _request_body(password="CorrectPass1", confirmation="DELETE"):
    return {"password": password, "confirmation": confirmation}


# ── A. The feature switch ─────────────────────────────────────────────────
# With the switch OFF the routes refuse, the card is absent, and /privacy
# shows no self-service promise. Against pre-2d code every one of these
# fails: there is no switch, so the routes answer, the card renders, and
# /privacy promises a feature that answers 503.


def test_the_switch_is_on_in_config_yaml():
    """Pins the shipped value so neither direction moves by accident.

    It asserted False until 2026-09-19, guarding against a flip that would
    publish the promise before the timer existed. The flip has since been
    made deliberately, against the gate in supabase/pending/README.md:
    migrations 01-12, 14 and 15 applied, and the reconcile timer installed,
    enabled and ticking. The tripwire is kept and inverted rather than
    deleted — turning the promise back off is as much a deploy event as
    turning it on, and neither should happen silently.
    """
    raw = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "web" / "config.yaml").read_text(encoding="utf-8")
    )
    assert raw["server"]["account_deletion_self_serve_enabled"] is True


def test_switch_off_the_request_route_is_404(switched_off_client, admin_client):
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = switched_off_client.post(
            "/account/api/deletion", json=_request_body(), headers=AUTH
        )
    assert response.status_code == 404
    assert response.get_json() == {"error": "deletion_unavailable"}
    assert admin_client.rpc_calls == []


def test_switch_off_the_cancel_route_is_404(switched_off_client, admin_client):
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = switched_off_client.post("/account/api/deletion/cancel", headers=AUTH)
    assert response.status_code == 404
    assert admin_client.rpc_calls == []


def test_switch_off_the_status_route_is_404(switched_off_client, admin_client):
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = switched_off_client.get("/account/api/deletion", headers=AUTH)
    assert response.status_code == 404
    assert admin_client.table_calls == []


def test_switch_off_the_account_page_has_no_deletion_card(switched_off_client):
    """No section, no heading, no confirmation input — a promise rendered
    nowhere. Fails pre-2d: the section renders unconditionally."""
    html = switched_off_client.get("/account").get_data(as_text=True)
    assert "deletion-heading" not in html
    assert "Delete your account" not in html
    assert "deletion-confirm" not in html
    assert "deletion-password" not in html


def test_switch_off_privacy_shows_the_previous_wording(switched_off_client):
    """The pre-self-serve retention sentence instead of the new promise, no
    'what remains' section for a deletion that cannot happen yet, and a
    rights bullet that stops at conversations. Fails pre-2d on every leg."""
    html = switched_off_client.get("/privacy").get_data(as_text=True)
    assert "not yet self-service" in html
    assert "you can delete your entire account yourself" not in html
    assert "What remains after deletion" not in html
    assert "or your entire account" not in html


def test_switch_on_privacy_shows_the_promise(client):
    """The ON posture is the built behaviour: the promise renders. A guard,
    not a failing-first test — it passes pre-2d too, and pins what the
    switch restores."""
    html = client.get("/privacy").get_data(as_text=True)
    assert "you can delete your entire account yourself" in html
    assert "What remains after deletion" in html


def test_switch_on_the_account_page_renders_the_card(client):
    """Same guard for the card: testing forces the switch on, so the suite
    keeps exercising the built UI."""
    html = client.get("/account").get_data(as_text=True)
    assert "deletion-heading" in html
    assert "deletion-confirm" in html


# ── B. The operator boundary ──────────────────────────────────────────────
# 12 must permit a pure DISABLE on a live saga while still refusing an
# Enable and any role change. Read against the unapplied draft, like the
# predicate tests: there is no database under this suite.


def _twelve_code():
    text = _migration("12_admin_set_user_flags_refuses_a_pending_target.sql").read_text(
        encoding="utf-8"
    )
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))


def test_12_permits_a_pure_disable_on_a_live_saga():
    """Fails pre-2d: the guard refused every flag change unconditionally,
    which made a deleting reader immune to the operator's Disable."""
    code = _twelve_code()
    assert "and not (p_is_disabled is true and p_role is null)" in code
    assert "if public.account_deletion_is_live(p_user_id) then" not in code


def test_12_still_refuses_enable_and_role_change_with_dl002():
    """The resurrection risk the guard exists for is unchanged: anything but
    a pure disable still raises DL002. Fails pre-2d only in the weak sense
    (the old text refused more) — the load-bearing assertion is that the
    new exception still carries DL002 rather than a softened code."""
    code = _twelve_code()
    assert "using errcode = 'DL002'" in code


def test_12_documents_the_disabled_pending_cancel_consequence():
    """The residual trade must be written down, not discovered: a disabled
    pending reader is refused by _gate and cannot reach cancel. Fails pre-2d:
    the header describes no such consequence."""
    text = _migration("12_admin_set_user_flags_refuses_a_pending_target.sql").read_text(
        encoding="utf-8"
    )
    assert "cannot reach" in text
    assert "cancel" in text


# ── C. The frozen-state replay and third view ─────────────────────────────
# For purging/auth_delete_begun/failed the status route's `pending: false`
# put the request form back on screen, and submitting replayed the saga,
# re-ran the global sign-out, and printed the 30-day claim.


def test_a_frozen_replay_does_not_sign_out(app, client, admin_client):
    """The replay returns the row as-is — no global sign-out, and the state
    rides along so the UI skips its 30-day toast. Fails pre-2d: the route
    ignored the row's state and replay flag, signed out everywhere, and
    answered {"ok": true} with no state at all."""
    admin_client.rpc_handlers["account_deletion_request"] = lambda p: {
        "user_id": p["p_owner_id"],
        "state": "purging",
        "grace_until": "2026-09-18T00:00:00+00:00",
        "_replay": True,
    }
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = client.post("/account/api/deletion", json=_request_body(), headers=AUTH)
    assert response.status_code == 200
    body = response.get_json()
    assert body["replay"] is True
    assert body["state"] == "purging"
    assert "fake_token" not in app.config["_testing_auth_admin_dispatcher"].signed_out


def test_a_pending_replay_still_signs_out(app, client, admin_client):
    """The guard for the other half of the replay contract: a pending replay
    keeps the existing behaviour (sessions end on request). Passes pre-2d
    too — it pins that fix C narrowed the change to frozen states only."""
    admin_client.rpc_handlers["account_deletion_request"] = lambda p: {
        "user_id": p["p_owner_id"],
        "state": "pending",
        "grace_until": "2026-10-18T00:00:00+00:00",
        "_replay": True,
    }
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = client.post("/account/api/deletion", json=_request_body(), headers=AUTH)
    assert response.status_code == 200
    assert "fake_token" in app.config["_testing_auth_admin_dispatcher"].signed_out


def test_status_returns_the_state_for_a_frozen_saga(client, admin_client):
    """The endpoint already returns `state` beside `pending` — this pins
    that the UI's third view has something to branch on. Passes pre-2d too;
    the failing halves of fix C are the replay test above and the view
    tests below."""
    admin_client.table_rows = [
        {
            "user_id": "test-user-id",
            "state": "auth_delete_begun",
            "requested_at": "2026-09-18T00:00:00+00:00",
            "grace_until": "2026-09-18T00:00:00+00:00",
            "purge_after": "2026-09-18T00:00:00+00:00",
            "completed_at": None,
        }
    ]
    with patch("web.api.account.get_supabase_admin", return_value=admin_client):
        response = client.get("/account/api/deletion", headers=AUTH)
    body = response.get_json()
    assert body["pending"] is False
    assert body["state"] == "auth_delete_begun"


def test_the_account_page_has_an_in_progress_view():
    """No request form, no cancel button, no 30-day claim for frozen states:
    a third banner branched on the frozen states. Fails pre-2d three ways —
    no banner element, no branch, no copy."""
    template = (
        Path(__file__).resolve().parents[2] / "web" / "templates" / "account.html"
    ).read_text(encoding="utf-8")
    assert "deletion-inprogress" in template
    handlers = (STATIC_ACCOUNT / "handlers.js").read_text(encoding="utf-8")
    assert "showDeletionInProgress" in handlers
    assert "auth_delete_begun" in handlers
    ui = (STATIC_ACCOUNT / "ui.js").read_text(encoding="utf-8")
    assert "export function showDeletionInProgress" in ui


def test_in_progress_copy_makes_no_30_day_claim_in_either_language():
    """The new strings exist in both catalogues and promise no usable days.
    Fails pre-2d: the keys do not exist."""
    for lang in ("en", "ar"):
        catalog = _catalog(lang)
        body = catalog["runtime"]["profile"]["account"]["deletionInProgressBody"]
        assert "30" not in body
        assert catalog["page"]["account"]["deletionInProgressTitle"]
        assert catalog["page"]["account"]["deletionInProgressBody"]


# ── D. The console reconcile audit ────────────────────────────────────────
# The driver half lives here (DL004 on an outcome record is ALREADY
# SETTLED); the route's two-row shape is asserted in test_admin_deletions.py.


def test_dl004_on_an_outcome_record_is_settled_not_unexpected():
    """The console and the timer overlapped on auth_delete_begun and the
    loser records its outcome against a terminal row. Fails pre-2d: the
    DL004 propagates out of reconcile_one and main() reports 'unexpected'
    for a successful deletion."""

    from scripts.reconcile_account_deletions import reconcile_one
    from web.services.auth_admin import InMemoryAuthAdminDispatcher

    class _DL004(Exception):
        def __init__(self):
            super().__init__("DL004")
            self.code = "DL004"

    class _LosingDB:
        def rpc(self, name, params):
            outer = self

            class _Call:
                def execute(self):
                    outer.calls.append((name, params))
                    if name == "account_deletion_record_auth_outcome":
                        raise _DL004()
                    return _FakeResult({"user_id": params.get("p_owner_id")})

            return _Call()

        def __init__(self):
            self.calls: list[tuple] = []

    db = _LosingDB()
    dispatcher = InMemoryAuthAdminDispatcher([{"id": "u-1", "email": "a@b.c"}])
    assert reconcile_one(db, dispatcher, "u-1", "auth_delete_begun") == "settled"


# ── E. Copy claims ────────────────────────────────────────────────────────


def test_retention_copy_names_the_email_in_audit_and_no_backup_expiry():
    """Administrative records can contain an email address (an operator email
    change stores old AND new beside the uuid), and no backup expiry has
    been evidenced. Fails pre-2d: the ledger-only phrasing and the
    'until their retention expires' claim."""
    en = _catalog("en")
    ar = _catalog("ar")
    assert "email" in en["page"]["policy"]["retentionStaysBody"].lower()
    assert "email" in en["page"]["account"]["deletionStaysBody"].lower()
    assert "until their retention expires" not in en["page"]["policy"]["retentionStaysBody"]
    assert "until their retention expires" not in en["page"]["account"]["deletionStaysBody"]
    assert "بريد" in ar["page"]["policy"]["retentionStaysBody"]
    assert "بريد" in ar["page"]["account"]["deletionStaysBody"]
    assert "حتى انتهاء مدة احتفاظها" not in ar["page"]["policy"]["retentionStaysBody"]
    assert "حتى انتهاء مدة احتفاظها" not in ar["page"]["account"]["deletionStaysBody"]


# ── F. The pending-saga consent refusal ───────────────────────────────────


def test_dl007_maps_to_its_own_refusal_not_an_outage(client):
    """A grant during a live saga is refused with its own code, so the
    reader is told why. Fails pre-2d: every grant failure answered
    consent_unavailable 503, and the DL regex stopped at DL006."""
    admin = MagicMock()
    admin.rpc.return_value.execute.side_effect = _SagaError("DL007")
    with patch("web.api.account.get_supabase_admin", return_value=admin):
        response = client.post("/account/api/consent/grant", json={"language": "en"}, headers=AUTH)
    assert response.status_code == 409
    assert response.get_json() == {"error": "deletion_pending"}


def test_saga_error_codes_reach_dl007():
    """The extractor the consent route now shares must see DL007 whether it
    rides .code or the message. Fails pre-2d: the pattern capped at DL006."""
    assert _saga_error_code(_SagaError("DL007")) == "DL007"

    class _MessageOnly(Exception):
        def __str__(self):
            return "DL007: marketing consent cannot be granted while a deletion is live"

    assert _saga_error_code(_MessageOnly()) == "DL007"


def test_the_consent_refusal_string_exists_in_both_catalogues():
    """Fails pre-2d: no such key."""
    for lang in ("en", "ar"):
        text = _catalog(lang)["runtime"]["profile"]["account"]["consentGrantPendingDeletion"]
        assert isinstance(text, str) and text.strip()
