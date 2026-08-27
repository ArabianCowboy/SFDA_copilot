"""Unit tests for `web.services.token_verification_cache`.

Two properties are load-bearing and get the most coverage: single-flight
collapses a concurrent burst on one token into one call to `verify` (this is
what actually fixes worker starvation — see docs/archive/2026-08-27_token-verification-cache.md
§1), and a failure — any failure, of any kind — is never remembered. The
positive cache itself is comparatively simple and ships disabled by default;
its tests exist so enabling it later is safe, not because it is on the hot
path today.
"""

from __future__ import annotations

import threading
import time

import pytest

from web.services.token_verification_cache import (
    TokenVerificationCache,
    TokenVerificationTimeout,
    VerifiedIdentity,
)


def _identity(user_id: str = "user-1") -> VerifiedIdentity:
    return VerifiedIdentity(user_id=user_id, email=f"{user_id}@example.com", token_exp=None)


def _must_not_be_called() -> VerifiedIdentity:
    raise AssertionError("verify() must not be called — a waiter must reuse the owner's result")


class _CountingVerifier:
    """Counts calls; returns a fixed identity or raises a fixed exception."""

    def __init__(
        self, identity: VerifiedIdentity | None = None, error: BaseException | None = None
    ):
        self.calls = 0
        self._identity = identity or _identity()
        self._error = error

    def __call__(self) -> VerifiedIdentity:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._identity


# ── Basic reuse and the cache key ────────────────────────────────────────────


def test_a_second_request_with_one_token_does_not_ask_again():
    cache = TokenVerificationCache(ttl_seconds=30)
    verifier = _CountingVerifier()

    first = cache.get_or_verify("token-a", verifier)
    second = cache.get_or_verify("token-a", verifier)

    assert first == second == _identity()
    assert verifier.calls == 1


def test_the_cache_key_is_a_digest_not_the_token():
    cache = TokenVerificationCache(ttl_seconds=30)
    cache.get_or_verify("super-secret-token", _CountingVerifier())

    assert "super-secret-token" not in cache._data
    assert not any("super-secret-token" in key for key in cache._data)
    assert not any("super-secret-token" in key for key in cache._by_user.get("user-1", set()))


def test_a_different_token_is_a_different_entry():
    cache = TokenVerificationCache(ttl_seconds=30)
    verifier = _CountingVerifier()
    cache.get_or_verify("token-a", verifier)
    cache.get_or_verify("token-b", verifier)
    assert verifier.calls == 2


# ── TTL and the `exp` ceiling ────────────────────────────────────────────────


def test_an_entry_expires_at_the_ttl(monkeypatch):
    cache = TokenVerificationCache(ttl_seconds=10)
    clock = {"now": 1000.0}
    monkeypatch.setattr(TokenVerificationCache, "_now", staticmethod(lambda: clock["now"]))
    verifier = _CountingVerifier()

    cache.get_or_verify("token-a", verifier)
    clock["now"] += 5
    cache.get_or_verify("token-a", verifier)
    assert verifier.calls == 1, "still within the TTL"

    clock["now"] += 6
    cache.get_or_verify("token-a", verifier)
    assert verifier.calls == 2, "past the TTL, must re-verify"


def test_an_entry_never_outlives_the_token_exp(monkeypatch):
    cache = TokenVerificationCache(ttl_seconds=60)
    clock = {"now": 1000.0}
    monkeypatch.setattr(TokenVerificationCache, "_now", staticmethod(lambda: clock["now"]))
    monkeypatch.setattr(time, "time", lambda: clock["now"])

    verifier = _CountingVerifier(VerifiedIdentity("user-1", "u@example.com", token_exp=1002.0))
    cache.get_or_verify("token-a", verifier)

    clock["now"] += 1.5  # inside the 60s TTL, but the token's own exp is 2s away
    cache.get_or_verify("token-a", verifier)
    assert verifier.calls == 1

    clock["now"] += 1  # now past the token's own exp
    cache.get_or_verify("token-a", verifier)
    assert verifier.calls == 2


def test_an_already_expired_token_is_not_cached_at_all(monkeypatch):
    cache = TokenVerificationCache(ttl_seconds=60)
    monkeypatch.setattr(time, "time", lambda: 2000.0)
    verifier = _CountingVerifier(VerifiedIdentity("user-1", "u@example.com", token_exp=1000.0))

    cache.get_or_verify("token-a", verifier)
    assert len(cache) == 0


def test_an_expired_entry_is_actually_removed_not_just_ignored(monkeypatch):
    """A read past the TTL must not merely answer "no hit" — it must forget
    the stale entry, in both `_data` and `_by_user`. Left in place, a stale
    digest and its reverse-index membership would sit in memory,
    unreachable but unfreed, until LRU pressure happened to reach them."""
    cache = TokenVerificationCache(ttl_seconds=10)
    clock = {"now": 1000.0}
    monkeypatch.setattr(TokenVerificationCache, "_now", staticmethod(lambda: clock["now"]))

    cache.get_or_verify("token-a", _CountingVerifier(_identity("user-1")))
    assert len(cache) == 1
    assert "user-1" in cache._by_user

    clock["now"] += 11  # past the TTL
    key = cache._key("token-a")
    with cache._lock:
        hit = cache._live_entry(key)
    assert hit is None

    assert len(cache) == 0
    assert "user-1" not in cache._by_user, "the reverse index must be forgotten too"


def test_ttl_zero_never_caches_anything():
    """The shipped default. Single-flight still applies — proven separately
    below — but nothing is ever remembered between calls."""
    cache = TokenVerificationCache(ttl_seconds=0)
    verifier = _CountingVerifier()
    cache.get_or_verify("token-a", verifier)
    cache.get_or_verify("token-a", verifier)
    assert verifier.calls == 2
    assert len(cache) == 0


# ── Single-flight ─────────────────────────────────────────────────────────────


def test_eight_threads_on_one_token_make_one_call():
    """One thread becomes the owner and is held in `verify()`; the other
    seven are only started once that owner is provably registered and
    blocked, and the owner cannot finish (and drop the flight) until this
    test explicitly releases it. That closes the obvious race — a waiter
    thread cannot possibly start before the owner has registered.

    What it does NOT prove: that every one of the seven actually reaches
    `flight.done.wait()` while the flight is still registered, as opposed to
    being scheduled late enough to see a cache hit instead (`ttl_seconds=30`
    here makes that a harmless fallback, not a failure — `verifier.calls == 1`
    holds either way). Proving a specific thread reached a specific blocking
    call from outside it, without instrumenting the class, isn't possible
    with stdlib primitives alone. The single-waiter tests below
    (`test_a_waiter_inherits_the_owners_failure`,
    `test_a_waiter_gives_up_bounded_and_does_not_call_gotrue`) are the ones
    that deterministically exercise the waiter code path, because there the
    "waiter" runs on the test's own thread after independently confirming the
    owner is registered and blocked. This test's job is different: proving
    the aggregate call count holds under real concurrent scheduling, not
    tracing one thread's control flow.
    """
    cache = TokenVerificationCache(ttl_seconds=30)
    owner_registered = threading.Event()
    release = threading.Event()
    calls = []

    def verify() -> VerifiedIdentity:
        calls.append(1)
        owner_registered.set()
        release.wait(timeout=5)
        return _identity()

    results: list[VerifiedIdentity | None] = [None] * 8
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            results[i] = cache.get_or_verify("token-a", verify)
        except BaseException as exc:
            errors.append(exc)

    owner_thread = threading.Thread(target=worker, args=(0,))
    owner_thread.start()
    assert owner_registered.wait(timeout=5)

    waiter_threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, 8)]
    for t in waiter_threads:
        t.start()
    release.set()
    for t in [owner_thread, *waiter_threads]:
        t.join(timeout=5)

    assert not errors
    assert len(calls) == 1
    assert all(r == _identity() for r in results)


def test_a_waiter_inherits_the_owners_failure():
    cache = TokenVerificationCache(ttl_seconds=30)
    ready = threading.Event()
    release = threading.Event()
    calls = []

    def owner_verify() -> VerifiedIdentity:
        calls.append(1)
        ready.set()
        release.wait(timeout=5)
        raise RuntimeError("gotrue said no")

    owner_error: list[BaseException] = []
    waiter_error: list[BaseException] = []

    def run_owner() -> None:
        try:
            cache.get_or_verify("token-a", owner_verify)
        except BaseException as exc:
            owner_error.append(exc)

    owner_thread = threading.Thread(target=run_owner)
    owner_thread.start()
    assert ready.wait(timeout=5)

    def run_waiter() -> None:
        try:
            cache.get_or_verify("token-a", _must_not_be_called)
        except BaseException as exc:
            waiter_error.append(exc)

    waiter_thread = threading.Thread(target=run_waiter)
    waiter_thread.start()
    release.set()
    owner_thread.join(timeout=5)
    waiter_thread.join(timeout=5)

    assert len(calls) == 1
    assert isinstance(owner_error[0], RuntimeError)
    assert waiter_error and waiter_error[0] is owner_error[0]


def test_a_waiter_gives_up_bounded_and_does_not_call_gotrue():
    cache = TokenVerificationCache(ttl_seconds=30, wait_timeout_seconds=0.2)
    ready = threading.Event()
    hold = threading.Event()
    calls = []

    def owner_verify() -> VerifiedIdentity:
        calls.append(1)
        ready.set()
        hold.wait(timeout=5)  # held well past the waiter's 0.2s ceiling
        return _identity()

    def run_owner() -> None:
        cache.get_or_verify("token-a", owner_verify)

    owner_thread = threading.Thread(target=run_owner)
    owner_thread.start()
    assert ready.wait(timeout=5)

    with pytest.raises(TokenVerificationTimeout):
        cache.get_or_verify("token-a", _must_not_be_called)

    hold.set()
    owner_thread.join(timeout=5)
    assert len(calls) == 1


def test_use_cache_false_still_single_flights():
    """No TTL to fall back on here (`use_cache=False` never publishes), so
    unlike the test above, a waiter thread scheduled late enough to miss the
    still-registered flight has nothing to save it — it would start its own
    verification, and `calls` would show it. Same owner-then-waiters
    construction as above: the owner is proven registered and blocked before
    any waiter is even created, and stays blocked until every waiter has
    been started. What is NOT proven (see the note on the test above, which
    applies here too) is that each waiter thread's OS scheduling actually
    lands it inside `flight.done.wait()` before this test calls
    `release.set()` — that specific claim would need a hook into the
    class this test does not have. In practice this has run green
    repeatedly under load (see the session history), which is the same
    standard of confidence the single-waiter tests below establish
    rigorously and this one establishes empirically.
    """
    cache = TokenVerificationCache(ttl_seconds=30)
    owner_registered = threading.Event()
    release = threading.Event()
    calls = []

    def verify() -> VerifiedIdentity:
        calls.append(1)
        owner_registered.set()
        release.wait(timeout=5)
        return _identity()

    def worker() -> None:
        cache.get_or_verify("token-a", verify, use_cache=False)

    owner_thread = threading.Thread(target=worker)
    owner_thread.start()
    assert owner_registered.wait(timeout=5)

    waiter_threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in waiter_threads:
        t.start()
    release.set()
    for t in [owner_thread, *waiter_threads]:
        t.join(timeout=5)

    assert len(calls) == 1
    assert len(cache) == 0, "use_cache=False must never write an entry"


# ── Failures are never remembered ────────────────────────────────────────────


def test_a_failure_is_never_remembered():
    cache = TokenVerificationCache(ttl_seconds=30)
    verifier = _CountingVerifier(error=RuntimeError("outage or refusal — this class does not care"))

    with pytest.raises(RuntimeError):
        cache.get_or_verify("token-a", verifier)
    with pytest.raises(RuntimeError):
        cache.get_or_verify("token-a", verifier)

    assert verifier.calls == 2
    assert len(cache) == 0


def test_a_waiter_is_freed_promptly_even_if_publishing_the_result_breaks(monkeypatch):
    """`flight.done.set()` must fire from a `finally`, not only on the two
    paths that were written to reach it. If something between `verify()`
    succeeding and the owner re-acquiring the lock raises (a bug in
    `_publish`, a `MemoryError`), a waiter must still be released promptly —
    not left blocked for the full wait ceiling and told it was an outage
    when the real story is a bug in this class.
    """
    cache = TokenVerificationCache(ttl_seconds=30, wait_timeout_seconds=5)
    monkeypatch.setattr(
        cache,
        "_publish",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pretend _publish is broken")),
    )

    owner_entered = threading.Event()
    owner_release = threading.Event()

    def owner_verify() -> VerifiedIdentity:
        owner_entered.set()
        owner_release.wait(timeout=5)
        return _identity("user-1")

    owner_errors: list[BaseException] = []

    def run_owner() -> None:
        try:
            cache.get_or_verify("token-a", owner_verify)
        except BaseException as exc:
            owner_errors.append(exc)

    owner_thread = threading.Thread(target=run_owner)
    owner_thread.start()
    assert owner_entered.wait(timeout=5)

    waiter_errors: list[BaseException] = []

    def run_waiter() -> None:
        try:
            cache.get_or_verify("token-a", _must_not_be_called)
        except BaseException as exc:
            waiter_errors.append(exc)

    waiter_thread = threading.Thread(target=run_waiter)
    waiter_thread.start()

    started = time.monotonic()
    owner_release.set()
    owner_thread.join(timeout=5)
    waiter_thread.join(timeout=5)
    elapsed = time.monotonic() - started

    assert elapsed < 4, "the waiter must be freed by done.set(), not by the 5s wait ceiling"
    assert owner_errors and isinstance(owner_errors[0], RuntimeError)
    # The waiter inherits the owner's `_publish` failure rather than the
    # identity that never got published, since publishing is what failed.
    assert waiter_errors and isinstance(waiter_errors[0], RuntimeError)


# ── Invalidation and its races ───────────────────────────────────────────────


def test_invalidation_during_a_flight_does_not_publish():
    cache = TokenVerificationCache(ttl_seconds=30)
    entered = threading.Event()
    release = threading.Event()

    def verify() -> VerifiedIdentity:
        entered.set()
        release.wait(timeout=5)
        return _identity("user-1")

    def run() -> None:
        cache.get_or_verify("token-a", verify)

    thread = threading.Thread(target=run)
    thread.start()
    assert entered.wait(timeout=5)

    cache.invalidate_user("user-1")  # revoked while the verification is in flight
    release.set()
    thread.join(timeout=5)

    assert len(cache) == 0, "a flight that started before invalidation must not publish"


def test_invalidate_user_drops_every_token_for_that_user():
    cache = TokenVerificationCache(ttl_seconds=30)
    cache.get_or_verify("token-a", _CountingVerifier(_identity("user-1")))
    cache.get_or_verify("token-b", _CountingVerifier(_identity("user-1")))
    cache.get_or_verify("token-c", _CountingVerifier(_identity("user-2")))
    assert len(cache) == 3

    cache.invalidate_user("user-1")

    assert len(cache) == 1, "only user-2's entry may survive"
    # token-c's entry for user-2 must have survived untouched — a cache hit
    # returns without ever calling the verifier.
    verifier = _CountingVerifier(_identity("user-2"))
    result = cache.get_or_verify("token-c", verifier)
    assert result.user_id == "user-2"
    assert verifier.calls == 0, "user-2's entry must not have been touched"


def test_invalidate_token_drops_only_that_token():
    cache = TokenVerificationCache(ttl_seconds=30)
    cache.get_or_verify("token-a", _CountingVerifier(_identity("user-1")))
    cache.get_or_verify("token-b", _CountingVerifier(_identity("user-1")))

    cache.invalidate_token("token-a")

    verifier_a = _CountingVerifier(_identity("user-1"))
    cache.get_or_verify("token-a", verifier_a)
    assert verifier_a.calls == 1, "token-a must have been evicted"

    verifier_b = _CountingVerifier(_identity("user-1"))
    cache.get_or_verify("token-b", verifier_b)
    assert verifier_b.calls == 0, "token-b must be untouched"


def test_invalidating_many_distinct_unauthenticated_tokens_does_not_grow_forever(monkeypatch):
    """`invalidate_token` is reachable from `POST /auth/logout`, which is
    deliberately unauthenticated — a caller never has to present a token
    this cache ever verified to have it stamped. Pins the fix for the
    memory-exhaustion primitive review found: without pruning, an anonymous
    caller sending endless distinct garbage bearer tokens to `/logout` would
    grow `_invalidated_at` without bound, forever, at zero cost to the
    attacker.
    """
    cache = TokenVerificationCache(ttl_seconds=0, wait_timeout_seconds=1.0)
    clock = {"now": 1000.0}
    monkeypatch.setattr(TokenVerificationCache, "_now", staticmethod(lambda: clock["now"]))

    for i in range(500):
        cache.invalidate_token(f"never-verified-garbage-token-{i}")
    assert len(cache._invalidated_at) == 500

    # Time passes well beyond the pruning cutoff (4x the wait timeout); the
    # NEXT invalidation call is what actually sweeps the stale ones.
    clock["now"] += 10.0
    cache.invalidate_token("one-more-garbage-token")

    assert len(cache._invalidated_at) == 1, "the 500 stale stamps must be pruned"


def test_a_verification_started_before_invalidate_token_does_not_publish():
    cache = TokenVerificationCache(ttl_seconds=30)
    entered = threading.Event()
    release = threading.Event()

    def verify() -> VerifiedIdentity:
        entered.set()
        release.wait(timeout=5)
        return _identity("user-1")

    thread = threading.Thread(target=lambda: cache.get_or_verify("token-a", verify))
    thread.start()
    assert entered.wait(timeout=5)

    cache.invalidate_token("token-a")
    release.set()
    thread.join(timeout=5)

    assert len(cache) == 0


def test_invalidate_all_drops_everything_including_in_flight():
    cache = TokenVerificationCache(ttl_seconds=30)
    entered = threading.Event()
    release = threading.Event()

    def verify() -> VerifiedIdentity:
        entered.set()
        release.wait(timeout=5)
        return _identity("user-1")

    thread = threading.Thread(target=lambda: cache.get_or_verify("token-a", verify))
    thread.start()
    assert entered.wait(timeout=5)

    cache.invalidate_all()
    release.set()
    thread.join(timeout=5)

    assert len(cache) == 0


def test_publish_does_not_let_an_older_start_overwrite_a_newer_one():
    """Mirrors `IdentityFlagsCache.put`'s `existing[0] > started` guard. Past
    `_max_in_flight`, two truly concurrent unregistered (overflow)
    verifications for the same key run outside single-flight and can finish
    out of order. Without this, an earlier-started call finishing after a
    later-started one already published would silently overwrite the fresher
    answer with a stale one.
    """
    cache = TokenVerificationCache(ttl_seconds=30)
    key = cache._key("token-a")
    newer = _identity("user-newer")
    older = _identity("user-older")

    with cache._lock:
        cache._publish(key, newer, started=200.0)
        # An earlier-started publish arriving after a later-started one is
        # already stored must be rejected outright.
        cache._publish(key, older, started=100.0)
        stored = cache._live_entry(key)

    assert stored == newer


# ── Bounds ────────────────────────────────────────────────────────────────────


def test_the_cache_is_bounded():
    cache = TokenVerificationCache(ttl_seconds=30, max_entries=100)
    for i in range(300):
        cache.get_or_verify(f"token-{i}", _CountingVerifier(_identity(f"user-{i}")))

    assert len(cache) <= 100
    total_indexed = sum(len(keys) for keys in cache._by_user.values())
    assert total_indexed == len(cache), "_by_user must shrink in lockstep with eviction"


def test_max_in_flight_falls_back_to_verifying_without_collapse():
    """Past the in-flight bound, the request is still answered correctly —
    just without single-flight collapse — rather than refused."""
    cache = TokenVerificationCache(ttl_seconds=0, max_in_flight=1)
    hold = threading.Event()
    entered = threading.Event()

    def blocking_verify() -> VerifiedIdentity:
        entered.set()
        hold.wait(timeout=5)
        return _identity("user-1")

    blocker = threading.Thread(target=lambda: cache.get_or_verify("token-a", blocking_verify))
    blocker.start()
    assert entered.wait(timeout=5)

    # A second, distinct token while the first flight slot is occupied.
    verifier = _CountingVerifier(_identity("user-2"))
    result = cache.get_or_verify("token-b", verifier)
    assert result.user_id == "user-2"
    assert verifier.calls == 1

    hold.set()
    blocker.join(timeout=5)


def test_an_overflow_owner_does_not_delete_a_later_registered_flight_for_the_same_key():
    """Pins the bug found in review: an overflow (unregistered) owner used to
    pop `_flights[key]` unconditionally on completion. If a DIFFERENT,
    legitimately registered flight for the same key had appeared in the
    meantime — because capacity freed up between the overflow owner starting
    and finishing — that unconditional pop silently discarded it, and the
    next request for that token started a fresh, duplicate verification
    instead of joining the one already running.
    """
    cache = TokenVerificationCache(ttl_seconds=0, max_in_flight=1)

    a_entered = threading.Event()
    a_release = threading.Event()

    def a_verify() -> VerifiedIdentity:
        a_entered.set()
        a_release.wait(timeout=5)
        return _identity("user-a")

    a_thread = threading.Thread(target=lambda: cache.get_or_verify("token-a", a_verify))
    a_thread.start()
    assert a_entered.wait(timeout=5)  # the one in-flight slot is occupied by A

    # First token-b request: the slot is full, so this is an unregistered
    # overflow owner.
    b1_entered = threading.Event()
    b1_release = threading.Event()

    def b1_verify() -> VerifiedIdentity:
        b1_entered.set()
        b1_release.wait(timeout=5)
        return _identity("user-b")

    b1_thread = threading.Thread(target=lambda: cache.get_or_verify("token-b", b1_verify))
    b1_thread.start()
    assert b1_entered.wait(timeout=5)

    # Free the slot A held.
    a_release.set()
    a_thread.join(timeout=5)

    # A second token-b request now finds capacity and registers a REAL
    # flight for "token-b" while b1 (the overflow owner) is still running.
    b2_entered = threading.Event()
    b2_release = threading.Event()
    b2_calls = []

    def b2_verify() -> VerifiedIdentity:
        b2_calls.append(1)
        b2_entered.set()
        b2_release.wait(timeout=5)
        return _identity("user-b")

    b2_thread = threading.Thread(target=lambda: cache.get_or_verify("token-b", b2_verify))
    b2_thread.start()
    assert b2_entered.wait(timeout=5)

    # Let the overflow owner (b1) finish. Its cleanup must NOT remove b2's
    # now-registered flight.
    b1_release.set()
    b1_thread.join(timeout=5)

    # A third request, while b2 is still in flight, must join b2's flight —
    # proving it survived b1's cleanup — rather than starting its own.
    b3_errors: list[BaseException] = []
    b3_result: dict[str, VerifiedIdentity] = {}

    def b3_call() -> None:
        try:
            b3_result["identity"] = cache.get_or_verify("token-b", _must_not_be_called)
        except BaseException as exc:
            b3_errors.append(exc)

    b3_thread = threading.Thread(target=b3_call)
    b3_thread.start()

    b2_release.set()
    b2_thread.join(timeout=5)
    b3_thread.join(timeout=5)

    assert not b3_errors
    assert b2_calls == [1], "b2's verifier must run exactly once"
    assert b3_result["identity"] == _identity("user-b")
