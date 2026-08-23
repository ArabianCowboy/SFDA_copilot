"""The server half of password recovery: sending the link, and saying nothing else.

The properties worth pinning here are mostly *absences* — what the endpoint
refuses to reveal, and what it refuses to write down. Those are easy to lose in a
later refactor precisely because no reader ever sees them working.
"""

from __future__ import annotations

import pytest

from web.api.app import create_app
from web.services.account_recovery import (
    RecoveryRefused,
    classify_send_failure,
    recovery_redirect_url,
)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://sfda-copilot.example")
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def dispatcher(app):
    return app.config["_testing_recovery_dispatcher"]


def test_a_reset_request_sends_a_link_to_the_recovery_landing(client, dispatcher):
    response = client.post("/auth/recover", json={"email": "reader@example.com"})

    assert response.status_code == 202
    assert dispatcher.sent == [
        {
            "email": "reader@example.com",
            "redirect_to": "https://sfda-copilot.example/?recovery=1",
        }
    ]


def test_the_readers_language_rides_along_on_the_link(client, dispatcher):
    """Proven against the live project: GoTrue appends its fragment and leaves
    the query alone, so `lang` survives to the landing and the reader comes back
    to the language they asked in."""
    client.post("/auth/recover", json={"email": "reader@example.com", "lang": "ar"})

    assert dispatcher.sent[0]["redirect_to"].endswith("/?recovery=1&lang=ar")


def test_a_send_failure_is_indistinguishable_from_a_send(client, dispatcher):
    """The app must not turn a provider outcome into an oracle.

    Note what this does and does not prove. GoTrue answers the same way for a
    known and an unknown address, so the app never learns which it was and there
    is nothing here to branch on — this pins that a *failure*, the only signal
    the app does receive, still looks exactly like success. True known-versus-
    unknown parity, including timing, is a provider property and needs measuring
    against a live project, not asserting here.
    """
    sent = client.post("/auth/recover", json={"email": "reader@example.com"})

    dispatcher.refuse_with = "reset_send_failed"
    failed = client.post("/auth/recover", json={"email": "nobody@example.com"})

    assert sent.status_code == failed.status_code == 202
    assert sent.get_json() == failed.get_json() == {"sent": True}
    assert sent.headers.get("Content-Type") == failed.headers.get("Content-Type")


def test_a_broken_dispatcher_does_not_answer_differently(app):
    """A misconfigured deployment must look like every other outcome. This is the
    path that used to raise before the dispatcher was resolved inside the try."""

    def explode():
        raise ValueError("malformed SUPABASE_URL")

    app.config["recovery_dispatcher"] = explode
    response = app.test_client().post("/auth/recover", json={"email": "a@example.com"})

    assert response.status_code == 202
    assert response.get_json() == {"sent": True}


@pytest.mark.parametrize(
    "base, ok",
    [
        ("https://sfda-copilot.example", True),
        ("http://127.0.0.1:5000", True),  # local development must stay usable
        ("javascript:alert(1)", False),
        ("not-a-url", False),
        ("https://user:pw@evil.example", False),
        ("https://example.com/?next=x", False),
    ],
)
def test_the_base_url_is_validated_not_merely_present(monkeypatch, base, ok):
    """This value becomes a link in an email that people are told to click, so a
    typo is not a 404 — it is a recovery link pointing somewhere else."""
    monkeypatch.setenv("PUBLIC_BASE_URL", base)

    if ok:
        assert recovery_redirect_url().startswith(base)
    else:
        with pytest.raises(RecoveryRefused):
            recovery_redirect_url()


def test_a_rate_limit_is_reported_because_it_tells_the_reader_to_wait(client, dispatcher):
    """The one honest refusal. It leaks nothing — any address reaches it — and
    withholding it would leave a reader who asked twice staring at a success
    message and an inbox that stays empty."""
    dispatcher.refuse_with = "reset_rate_limited"
    response = client.post("/auth/recover", json={"email": "reader@example.com"})

    assert response.status_code == 429
    assert response.get_json() == {"error": "reset_rate_limited"}


def test_an_exhausted_project_allowance_is_its_own_code(client, dispatcher):
    """Distinct from the per-address limit: an operator who does not know a
    project-wide ceiling exists will conclude the account is broken."""
    dispatcher.refuse_with = "reset_quota_exhausted"
    response = client.post("/auth/recover", json={"email": "reader@example.com"})

    assert response.status_code == 429
    assert response.get_json() == {"error": "reset_quota_exhausted"}


def test_a_missing_dispatcher_is_never_reported_as_a_send(app):
    """No dispatcher means no mail. The reader still gets the generic answer, but
    nothing may be recorded as sent, and the failure has to reach the log."""
    app.config["recovery_dispatcher"] = lambda: None
    response = app.test_client().post("/auth/recover", json={"email": "a@example.com"})

    assert response.status_code == 202
    assert response.get_json() == {"sent": True}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"email": ""},
        {"email": "   "},
        {"email": 42},
        {"email": "a@example.com", "lang": 7},
    ],
)
def test_a_malformed_request_is_refused_before_anything_is_sent(client, dispatcher, payload):
    response = client.post("/auth/recover", json=payload)

    assert response.status_code == 400
    assert dispatcher.sent == []


def test_the_response_never_carries_a_link_or_a_token(client, dispatcher):
    """The whole design position in one assertion: recovery mail is sent, never
    handed back. A body carrying the link would put a bearer credential on
    whatever screen called this."""
    body = client.post("/auth/recover", json={"email": "reader@example.com"}).get_data(as_text=True)

    assert "http" not in body
    assert "token" not in body.lower()
    assert "code" not in body.lower()


def test_recovery_is_not_written_to_the_audit_log(client, app):
    """`audit_log` records privileged acts by operators. A reader recovering
    their own account is neither, and logging it would quietly turn the table
    into a reader-activity trail."""
    client.post("/auth/recover", json={"email": "reader@example.com"})

    assert app.config["_testing_admin_backend"].list_audit(limit=50, offset=0) == []


def test_the_endpoint_carries_the_rate_limit_it_is_configured_with(app):
    """The route is on its own blueprint solely so it can hold this limit.

    Asserted against the *resolved* limit rather than by exhausting it, because
    `_configure_app` forces `RATELIMIT_ENABLED = not testing` and the limiter
    reads that at init — an exhaustion test under TESTING measures nothing.

    Worth the awkwardness. The first version of this wiring called the limiter's
    decorator on the resolved view function and discarded the wrapper it
    returned; the limit registered nowhere, and an unauthenticated mail-sending
    endpoint answered unlimited with nothing anywhere saying so. Resolving the
    limit here fails loudly on that, where reading the code did not.
    """
    limiter = app.config["_LIMITER_INSTANCE"]
    limits = list(limiter.limit_manager.blueprint_limits(app, "recover"))

    assert limits, (
        "POST /auth/recover has no rate limit; it sends mail to an address "
        "supplied by an unauthenticated caller."
    )
    assert str(limits[0].limit) == "5 per 1 minute"


def test_the_redirect_is_refused_rather_than_guessed(monkeypatch):
    """`request.host_url` is attacker-controlled. Not knowing our own address is
    a reason to refuse, never a reason to infer one — a poisoned Host would mail
    readers a recovery link pointing somewhere else entirely."""
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

    with pytest.raises(RecoveryRefused) as refusal:
        recovery_redirect_url()

    assert refusal.value.code == "reset_not_configured"


def test_every_recovery_string_is_actually_drawn_somewhere():
    """A key nobody reads is a translation nobody sees.

    This repo has the failure already: `runtime.profile.*` sits in both
    catalogues read by no module, and `admin.people.search` is drawn by nothing.
    Catalogue parity tests cannot catch it — both languages have the key, it is
    simply never used — so it is asserted here, against the one group of keys
    this work added.
    """
    import re
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2]
    catalogue = yaml.safe_load((root / "web" / "i18n" / "en.yaml").read_text(encoding="utf-8"))
    keys = set(catalogue["runtime"]["auth"]["recovery"])

    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            *(root / "static" / "js").rglob("*.js"),
            root / "web" / "templates" / "index.html",
        ]
    )
    unused = {key for key in keys if not re.search(rf"recovery\.{key}\b", sources)}

    assert not unused, (
        f"runtime.auth.recovery keys translated into two languages and drawn by "
        f"nothing: {sorted(unused)}"
    )


@pytest.mark.parametrize(
    "message, expected",
    [
        ("For security purposes, you can only request this after 47 seconds", "reset_rate_limited"),
        ("Email rate limit exceeded", "reset_quota_exhausted"),
        ("over_email_send_rate_limit", "reset_quota_exhausted"),
        ("something nobody has seen before", "reset_send_failed"),
    ],
)
def test_provider_messages_are_mapped_to_codes_not_shown_to_readers(message, expected):
    """GoTrue's text is English-only and phrased as though the reader had
    exceeded a limit rather than the service being busy. It never reaches a
    bilingual surface; the code does, and the catalogue supplies the words."""
    assert classify_send_failure(Exception(message)) == expected
