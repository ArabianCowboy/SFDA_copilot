"""The budget that stops a broken deployment serving free answers forever.

Plan item P1 of docs/supabase-key-incident-fix-plan.md. On 2026-09-07 a rejected
Supabase key made every claim RPC fail, and because a 401 is not one of
``_CONFIGURATION_FAULTS`` the route's blanket ``except Exception`` streamed every
answer uncounted for the duration — the exact outcome ``quota_store``'s own
docstring says the design refuses.

These tests pin the two halves of the correction: a brief blip is still absorbed
(five answers, or two minutes, are cheap against refusing a real question), and a
fault that outlives the budget stops being free.
"""

from __future__ import annotations

import pytest

from web.services.quota_store import ClaimFailureTolerance


class _Clock:
    """A hand-wound monotonic clock, so the elapsed-time rule needs no sleeping."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_a_brief_blip_is_absorbed_rather_than_refused():
    """Four consecutive failures still answer: the budget is five."""
    tolerance = ClaimFailureTolerance(clock=_Clock())

    for attempt in range(ClaimFailureTolerance.MAX_CONSECUTIVE_FAILURES - 1):
        assert tolerance.record_failure() is False, f"refused on failure {attempt + 1}"

    assert tolerance.consecutive_failures == ClaimFailureTolerance.MAX_CONSECUTIVE_FAILURES - 1


def test_the_fifth_consecutive_failure_fails_closed():
    """The budget is spent in whole units — the fifth failure is the one that refuses."""
    tolerance = ClaimFailureTolerance(clock=_Clock())

    for _ in range(ClaimFailureTolerance.MAX_CONSECUTIVE_FAILURES - 1):
        tolerance.record_failure()

    assert tolerance.record_failure() is True


def test_a_success_restores_the_whole_budget():
    """Recovery needs no probe: the next successful claim is the probe.

    This is the property that makes the absence of an explicit half-open state
    safe — a deployment that recovers does not stay closed until a restart.
    """
    tolerance = ClaimFailureTolerance(clock=_Clock())

    for _ in range(ClaimFailureTolerance.MAX_CONSECUTIVE_FAILURES - 1):
        tolerance.record_failure()
    tolerance.record_success()

    assert tolerance.consecutive_failures == 0
    # A full fresh budget, not a partially-spent one.
    for _ in range(ClaimFailureTolerance.MAX_CONSECUTIVE_FAILURES - 1):
        assert tolerance.record_failure() is False


def test_two_minutes_of_failure_fails_closed_even_below_the_count():
    """The other currency. A low-traffic app might take an hour to reach five
    failures; the elapsed-time rule is what stops it serving free answers for
    that hour."""
    clock = _Clock()
    tolerance = ClaimFailureTolerance(clock=clock)

    assert tolerance.record_failure() is False  # starts the clock
    clock.advance(ClaimFailureTolerance.MAX_TOLERATED_SECONDS + 1)

    assert tolerance.record_failure() is True
    assert tolerance.consecutive_failures < ClaimFailureTolerance.MAX_CONSECUTIVE_FAILURES


def test_the_elapsed_clock_starts_at_the_first_failure_not_at_construction():
    """A worker up for hours before its first failure still gets the full two
    minutes, rather than being refused on the first one."""
    clock = _Clock()
    tolerance = ClaimFailureTolerance(clock=clock)

    clock.advance(6 * 60 * 60)  # six quiet hours
    assert tolerance.record_failure() is False


def test_a_success_also_restarts_the_elapsed_clock():
    """Otherwise a single failure hours ago would make a later, unrelated blip
    fail closed immediately."""
    clock = _Clock()
    tolerance = ClaimFailureTolerance(clock=clock)

    tolerance.record_failure()
    tolerance.record_success()
    clock.advance(ClaimFailureTolerance.MAX_TOLERATED_SECONDS + 1)

    assert tolerance.record_failure() is False


@pytest.mark.parametrize("threads", [8])
def test_the_counter_is_safe_across_the_worker_s_threads(threads):
    """Deployed as `--workers 1 --threads 8`, so the counter is shared mutable
    state under real concurrency."""
    import threading as _threading

    tolerance = ClaimFailureTolerance(clock=_Clock())
    barrier = _threading.Barrier(threads)
    per_thread = 50
    verdicts: list[bool] = []
    verdicts_lock = _threading.Lock()

    def hammer():
        barrier.wait()
        for _ in range(per_thread):
            verdict = tolerance.record_failure()
            with verdicts_lock:
                verdicts.append(verdict)

    workers = [_threading.Thread(target=hammer) for _ in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()

    # No lost updates: every increment landed.
    assert tolerance.consecutive_failures == threads * per_thread

    # And the DECISION is atomic, which is the property that actually matters.
    # Counting correctly while two threads both read "budget not yet spent"
    # would still overshoot the policy and serve free answers past the limit.
    # Exactly MAX-1 callers may be told to keep answering, ever.
    assert sum(1 for verdict in verdicts if verdict is False) == (
        ClaimFailureTolerance.MAX_CONSECUTIVE_FAILURES - 1
    )
