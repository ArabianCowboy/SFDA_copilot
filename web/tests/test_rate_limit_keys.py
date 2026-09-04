"""The rate limits are actually wired, and keyed on the account.

WHY THIS FILE EXISTS. The limiter is disabled under TESTING, so until now
nothing in the suite could tell a registered limit from an enforced one — and
five of this app's limits were registered and silently unenforced for months
(`account.export`, `account.delete_all_conversations`, `admin.revoke_sessions`,
`admin.change_email`, `admin.create_notification`). Each was written as

    limiter.limit(...)(app.view_functions[name])

which RETURNS a wrapper and throws it away. Flask-Limiter marks the endpoint as
carrying a limit — so its own middleware skips it — while nothing enforces one.
The endpoint therefore ended up LESS limited than if the line had been absent.

A structural assertion cannot catch this: `functools.wraps` copies `__dict__`,
so the `__wrapper-limiter-instance` marker propagates onto the outer
`auth_required` wrapper and both wrappers carry it. Only firing real requests
and counting 429s proves anything, which is what this file does.
"""

from __future__ import annotations

import uuid

import pytest

from web.api.app import create_app
from web.utils.config_loader import config


@pytest.fixture
def limited_app(monkeypatch):
    """A TESTING app with the limiter genuinely on.

    `enforce_rate_limits` has to be a factory argument. `Limiter.init_app`
    returns early when `RATELIMIT_ENABLED` is false — before it builds storage or
    registers its `before_request` hook — so flipping `limiter.enabled = True`
    on the retained instance afterwards enforces nothing, and `reset()` raises on
    the storage that was never created. The app must be BUILT with it on.

    Storage is `memory://` and each app gets its own, so tests do not leak
    counters into one another.
    """
    monkeypatch.setitem(config._config["server"]["rate_limit"], "chat_api", "2 per minute")
    app = create_app(testing=True, enforce_rate_limits=True)
    app.config["_LIMITER_INSTANCE"].reset()
    return app


def _payload():
    return {
        "query": "ما هي متطلبات تسجيل الأدوية؟",
        "category": "all",
        "lang": "ar",
        "client_request_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "allow_create": True,
    }


def test_the_limiter_is_actually_enforcing(limited_app):
    """Sanity: without this, every other assertion here would pass vacuously."""
    assert limited_app.config["RATELIMIT_ENABLED"] is True
    assert limited_app.config["_LIMITER_INSTANCE"].enabled is True
    # TESTING itself must be untouched — the mock services depend on it.
    assert limited_app.config["TESTING"] is True


def test_chat_burst_limit_fires_and_is_keyed_per_reader(limited_app):
    """Two requests pass, the third is refused — and a DIFFERENT reader is not.

    The second half is the point of the re-key. While the chat limit was keyed on
    `get_remote_address`, every reader behind one office NAT shared a single
    15/minute budget; the test client reports one address for everybody, so a
    per-IP key would refuse reader B on its first request here.
    """
    client = limited_app.test_client()
    a = {"Authorization": "Bearer fake_token"}  # test-user-id
    b = {"Authorization": "Bearer fake_reader_b_token"}  # test-reader-b-id

    codes = [client.post("/api/chat", json=_payload(), headers=a).status_code for _ in range(3)]
    assert codes[:2] == [c for c in codes[:2] if c != 429], f"first two refused: {codes}"
    assert codes[2] == 429, f"third request was not refused: {codes}"

    # A different account starts with its own budget.
    assert client.post("/api/chat", json=_payload(), headers=b).status_code != 429


def test_the_two_chat_routes_share_one_allowance(limited_app):
    """`shared_limit(scope="chat")` — alternating routes must not double it."""
    client = limited_app.test_client()
    h = {"Authorization": "Bearer fake_token"}
    client.post("/api/chat", json=_payload(), headers=h)
    client.post("/api/chat/stream", json=_payload(), headers=h)
    assert client.post("/api/chat", json=_payload(), headers=h).status_code == 429


@pytest.mark.parametrize(
    "endpoint",
    [
        "account.export",
        "account.delete_all_conversations",
        "admin.revoke_sessions",
        "admin.change_email",
        "admin.create_notification",
    ],
)
def test_the_five_formerly_discarded_limits_are_reassigned(limited_app, endpoint):
    """The regression guard for the wrapper-discarding bug itself.

    `view_functions[name]` must BE the limiter's wrapper, not the bare view. The
    marker attribute is what Flask-Limiter sets on the callable it returns; if a
    future edit drops the assignment, the registered function is the undecorated
    one and this fails.
    """
    fn = limited_app.view_functions[endpoint]
    assert hasattr(fn, "__wrapper-limiter-instance"), (
        f"{endpoint} is not wrapped by the limiter — the assignment back into "
        "app.view_functions was probably dropped, which silently disables the limit"
    )


def test_decorator_order_on_the_chat_routes(limited_app):
    """`@auth_required` must stay OUTSIDE `@chat_limit`.

    If the order inverts, the limit is spent before the request is authenticated,
    so an unauthenticated flood consumes a real reader's budget — and `_rate_key`
    would fall back to the IP for all of it. Asserted behaviourally: an
    unauthenticated request must be refused for AUTH reasons (401/403), never 429,
    no matter how many times it is repeated.
    """
    client = limited_app.test_client()
    codes = {client.post("/api/chat", json=_payload()).status_code for _ in range(4)}
    assert 429 not in codes, (
        f"an unauthenticated caller reached the rate limiter: {codes}. "
        "@chat_limit is evaluating before @auth_required."
    )
