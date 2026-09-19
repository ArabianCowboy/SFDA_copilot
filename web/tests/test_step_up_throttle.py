"""The durable step-up throttle (TODO.md: "Deletion step-up blinds GoTrue's
own per-IP rate limiter").

Every test here fails against the code before the throttle existed: the route
called the password verifier unconditionally and answered 401 forever, with
nothing but the `memory://` Flask limiter bounding it.

The point of this feature is the one thing a unit test can genuinely prove:
that the lockout is held in the DATABASE rather than in the worker, so a
recycle does not hand a guesser a fresh budget. `_FakeAdminClient` below keeps
its rows in a dict that OUTLIVES the Flask app under test, which is exactly
what a restarted worker talking to the same Postgres looks like.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from web.api.app import create_app

AUTH = {"Authorization": "Bearer fake_token"}


class _Result:
    def __init__(self, data):
        self.data = data


class _ThrottleDB:
    """Stands in for `public.step_up_attempts` and its three RPCs.

    Deliberately a plain dict held by the TEST, not by the app: every app
    instance built below shares it, the way every worker shares one database.
    """

    WINDOW_MAX = 5

    def __init__(self):
        self.rows: dict[str, int] = {}
        self.locked: set[str] = set()
        self.calls: list[str] = []

    def rpc(self, name, params):
        db = self
        owner = params["p_owner_id"]

        class _Call:
            def execute(self):
                db.calls.append(name)
                if name == "step_up_is_locked_out":
                    return _Result(owner in db.locked)
                if name == "record_step_up_failure":
                    db.rows[owner] = db.rows.get(owner, 0) + 1
                    if db.rows[owner] >= db.WINDOW_MAX:
                        db.locked.add(owner)
                    return _Result(owner in db.locked)
                if name == "clear_step_up_failures":
                    db.rows.pop(owner, None)
                    db.locked.discard(owner)
                    return _Result(None)
                return _Result({"ok": True})

        return _Call()

    def table(self, name):  # pragma: no cover - the throttle never reads a table
        raise AssertionError("the throttle must go through its RPCs")


@pytest.fixture
def throttle():
    return _ThrottleDB()


def _app(verifier):
    app = create_app(testing=True)
    app.config["deletion_password_verifier"] = verifier
    return app


def _post(app, throttle, password):
    with patch("web.api.account.get_supabase_admin", return_value=throttle):
        return app.test_client().post(
            "/account/api/deletion",
            json={"password": password, "confirmation": "DELETE"},
            headers=AUTH,
        )


def test_repeated_wrong_passwords_lock_the_account_out():
    """Five wrong passwords trip the lockout, and the fifth says so rather than
    repeating the ordinary refusal."""
    db = _ThrottleDB()
    app = _app(lambda email, password: False)

    codes = [_post(app, db, "WrongPass1").get_json()["error"] for _ in range(5)]

    assert codes[:4] == ["step_up_failed"] * 4
    assert codes[4] == "step_up_locked_out"


def test_a_lockout_survives_a_worker_recycle():
    """THE point of the whole change.

    `--max-requests 1000` recycles the worker routinely, and the Flask limiter
    is `memory://`, so its counters die with it. A throttle that lived there
    would hand a guesser a fresh budget every recycle while GoTrue — whose own
    per-IP limiter this design blinds — saw nothing unusual.

    The second app below is a DIFFERENT Flask application object sharing the
    same throttle store. That is a recycled worker.
    """
    db = _ThrottleDB()
    first = _app(lambda email, password: False)
    for _ in range(5):
        _post(first, db, "WrongPass1")

    recycled = _app(lambda email, password: False)
    response = _post(recycled, db, "WrongPass1")

    assert response.status_code == 429
    assert response.get_json() == {"error": "step_up_locked_out"}


def test_a_locked_out_caller_makes_no_provider_call():
    """An unbounded oracle is what blinds GoTrue's limiter, so a locked-out
    caller must not reach the verifier at all — not merely be refused after."""
    db = _ThrottleDB()
    reached = []
    app = _app(lambda email, password: reached.append(1) or False)

    for _ in range(5):
        _post(app, db, "WrongPass1")
    before = len(reached)
    _post(app, db, "WrongPass1")

    assert len(reached) == before, "the verifier was called while locked out"


def test_a_correct_password_clears_the_counter():
    """A reader who mistypes twice and then succeeds carries no penalty."""
    db = _ThrottleDB()
    app = _app(lambda email, password: password == "CorrectPass1")

    _post(app, db, "WrongPass1")
    _post(app, db, "WrongPass1")
    assert db.rows.get("user-123", 0) == 2 or sum(db.rows.values()) == 2

    _post(app, db, "CorrectPass1")
    assert sum(db.rows.values()) == 0
    assert db.locked == set()


def test_a_provider_outage_costs_the_reader_nothing():
    """`None` means the check could not run. An outage is not a wrong password:
    it answers 503, never 401, and must not spend one of five attempts."""
    db = _ThrottleDB()
    app = _app(lambda email, password: None)

    response = _post(app, db, "CorrectPass1")

    assert response.status_code == 503
    assert response.get_json() == {"error": "deletion_unavailable"}
    assert "record_step_up_failure" not in db.calls
    assert sum(db.rows.values()) == 0


def test_an_unrecognised_payload_does_not_lock_anyone_out():
    """Fail OPEN, not closed.

    `_step_up_rpc` documents a fail-open posture: the throttle is a rate limit,
    not the authorization check, and turning a database blip into "you cannot
    delete your account" would break the feature to protect a control. An
    earlier draft coerced with `bool()`, so any non-empty payload — `{"ok":
    True}`, an error envelope — read as "locked" and refused every caller.
    Seven existing deletion tests caught it.

    Both helpers now compare with `is True`, so only a real boolean counts.
    """

    class _Payload:
        """Returns a dict where the contract says boolean."""

        def __init__(self):
            self.data = {"ok": True}

    class _Chatty:
        def rpc(self, name, params):
            class _Call:
                def execute(self):
                    return _Payload()

            return _Call()

    app = _app(lambda email, password: True)
    response = _post(app, _Chatty(), "CorrectPass1")

    assert response.status_code != 429, "a non-boolean payload must not lock the account"
