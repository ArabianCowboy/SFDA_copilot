"""The daily allowance: resolution, the atomic claim, the refund, and rollover.

These run against `InMemoryQuotaBackend`, which duplicates the resolution the RPC
does. That duplication is a known risk and the mitigation is procedural: the SQL
suite (`supabase/tests/quota_behaviour.test.sql`) is the AUTHORITY on resolution
semantics, this is a convenience, and any change to the order or the window
clause is made in the SQL first and the double second, in the same commit. Where
they disagree the database is right.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from web.services.quota_store import InMemoryQuotaBackend
from web.utils.config_loader import config

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


@pytest.fixture
def backend():
    b = InMemoryQuotaBackend()
    b.profile_tiers["u1"] = "free"
    return b


# ── the claim ────────────────────────────────────────────────────────────────


def test_claim_decrements_the_remaining_allowance(backend):
    backend.tiers["free"]["daily_message_limit"] = 3
    first = backend.claim("u1", 200)
    assert (first.allowed, first.used, first.limit, first.remaining) == (True, 1, 3, 2)
    second = backend.claim("u1", 200)
    assert (second.allowed, second.used, second.remaining) == (True, 2, 1)


def test_claim_refuses_at_the_boundary_and_does_not_overcount(backend):
    backend.tiers["free"]["daily_message_limit"] = 2
    backend.claim("u1", 200)
    backend.claim("u1", 200)
    refused = backend.claim("u1", 200)
    assert refused.allowed is False
    # `used` must NOT advance past the limit on a refusal — the counter is what
    # the reader is shown, and 3 of 2 is a lie.
    assert refused.used == 2
    assert refused.remaining == 0


def test_a_zero_limit_refuses_the_very_first_claim_of_the_day(backend):
    """The guard the upsert cannot provide.

    `insert … on conflict … do update … where used < limit` guards only the
    UPDATE branch; the INSERT branch has no WHERE, so the first claim of a day
    would succeed against a limit of 0 without an explicit check.
    """
    backend.tiers["free"]["daily_message_limit"] = 0
    claim = backend.claim("u1", 200)
    assert claim.allowed is False
    assert claim.used == 0


def test_zero_is_not_the_same_as_disabled(backend):
    """Owner decision: 0 means "may read and browse, may not ask today"."""
    backend.tiers["free"]["daily_message_limit"] = 0
    # The account still resolves, still reports a tier, still has a reset time.
    status = backend.status("u1", 200)
    assert status.limit == 0
    assert status.tier_key == "free"
    assert status.resets_at


# ── resolution order: override → tier → live free → shipped default ─────────


def test_tier_beats_the_shipped_default(backend):
    backend.tiers["free"]["daily_message_limit"] = 7
    assert backend.claim("u1", 999).limit == 7


def test_an_in_window_override_beats_the_tier(backend):
    backend.tiers["free"]["daily_message_limit"] = 7
    backend.overrides["u1"] = {"daily_message_limit": 50}
    assert backend.claim("u1", 999).limit == 50


def test_an_expired_override_is_invisible(backend):
    backend.tiers["free"]["daily_message_limit"] = 7
    backend.overrides["u1"] = {
        "daily_message_limit": 50,
        "starts_at": datetime.now(timezone.utc) - timedelta(days=9),
        "expires_at": datetime.now(timezone.utc) - timedelta(days=1),
    }
    assert backend.claim("u1", 999).limit == 7
    # And it does not advertise an expiry the reader could act on.
    assert backend.status("u1", 999).override_expires_at is None


def test_a_scheduled_override_is_not_in_force_yet(backend):
    backend.tiers["free"]["daily_message_limit"] = 7
    backend.overrides["u1"] = {
        "daily_message_limit": 50,
        "starts_at": datetime.now(timezone.utc) + timedelta(days=1),
    }
    assert backend.claim("u1", 999).limit == 7


def test_an_override_expiring_between_two_claims_needs_no_sweep(backend):
    """Expiry-on-read: no scheduler, no job, no restart."""
    backend.tiers["free"]["daily_message_limit"] = 7
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    backend.overrides["u1"] = {"daily_message_limit": 50, "expires_at": expiry}
    assert backend.claim("u1", 999).limit == 50
    backend._now = lambda: expiry + timedelta(seconds=1)
    assert backend.claim("u1", 999).limit == 7


def test_a_profileless_account_tracks_the_live_free_tier(backend):
    """Not the config number — the operator's edit must reach it."""
    backend.tiers["free"]["daily_message_limit"] = 42
    claim = backend.claim("nobody-has-a-profile", 999)
    assert claim.limit == 42
    assert claim.tier_key == "free"


def test_the_shipped_default_applies_only_when_free_is_gone(backend):
    del backend.tiers["free"]
    backend.profile_tiers.pop("u1")
    assert backend.claim("u1", 123).limit == 123


# ── mid-day changes ──────────────────────────────────────────────────────────


def test_lowering_the_limit_below_used_refuses_without_rewriting_history(backend):
    backend.tiers["free"]["daily_message_limit"] = 5
    backend.claim("u1", 200)
    backend.claim("u1", 200)
    backend.tiers["free"]["daily_message_limit"] = 1
    refused = backend.claim("u1", 200)
    assert refused.allowed is False
    assert refused.used == 2, "a lowered limit must not rewrite what was already spent"
    assert refused.limit == 1


def test_raising_the_limit_frees_capacity_immediately(backend):
    backend.tiers["free"]["daily_message_limit"] = 1
    backend.claim("u1", 200)
    assert backend.claim("u1", 200).allowed is False
    backend.tiers["free"]["daily_message_limit"] = 3
    assert backend.claim("u1", 200).allowed is True


# ── the refund ───────────────────────────────────────────────────────────────


def test_release_frees_one_message(backend):
    backend.tiers["free"]["daily_message_limit"] = 1
    claim = backend.claim("u1", 200)
    assert backend.claim("u1", 200).allowed is False
    backend.release("u1", claim.day)
    assert backend.claim("u1", 200).allowed is True


def test_release_never_goes_below_zero(backend):
    claim = backend.claim("u1", 200)
    backend.release("u1", claim.day)
    backend.release("u1", claim.day)
    backend.release("u1", claim.day)
    assert backend.usage[("u1", claim.day)] == 0


def test_release_against_another_day_is_a_no_op(backend):
    """The reason the claim CARRIES its day instead of recomputing one.

    A claim at 23:59:59 whose retrieval fails at 00:00:01 must refund the day it
    charged. Recomputing "today" would decrement a different day's count, or find
    no row at all and refund nothing.
    """
    claim = backend.claim("u1", 200)
    backend.release("u1", "1999-01-01")
    assert backend.usage[("u1", claim.day)] == 1


# ── the day boundary ─────────────────────────────────────────────────────────


def test_the_day_rolls_over_at_riyadh_midnight_not_utc(backend):
    """Owner decision, 2026-09-03: the reader's day, not the server's.

    21:00 UTC is midnight in Riyadh (UTC+3, no daylight saving). Two claims
    either side of it fall on different days; two either side of UTC midnight
    do not.
    """
    backend._now = lambda: datetime(2026, 9, 4, 20, 59, tzinfo=timezone.utc)
    before = backend.claim("u1", 200).day
    backend._now = lambda: datetime(2026, 9, 4, 21, 1, tzinfo=timezone.utc)
    after = backend.claim("u1", 200).day
    assert before != after, "the allowance must reset at Riyadh midnight"

    backend._now = lambda: datetime(2026, 9, 6, 23, 30, tzinfo=timezone.utc)
    late = backend.claim("u1", 200).day
    backend._now = lambda: datetime(2026, 9, 7, 0, 30, tzinfo=timezone.utc)
    assert backend.claim("u1", 200).day == late, "UTC midnight must NOT roll the day"


def test_a_fresh_day_restores_the_whole_allowance(backend):
    backend.tiers["free"]["daily_message_limit"] = 1
    backend._now = lambda: datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    backend.claim("u1", 200)
    assert backend.claim("u1", 200).allowed is False
    backend._now = lambda: datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    assert backend.claim("u1", 200).allowed is True


# ── the seed cannot drift from the config ────────────────────────────────────


def test_seed_matches_shipped_default():
    """BOTH seeded rows are pinned to the one config key.

    An implementer who gives `staff` a different number in the migration fails
    here rather than shipping a database that disagrees with `config.yaml`'s own
    comment. Differentiating the tiers is a CONSOLE edit after Commit D, never a
    change to the seed.
    """
    shipped = int(config.get("server", "quota", {})["daily_messages_default"])
    seed = next(MIGRATIONS.glob("*_tiers_table.sql")).read_text(encoding="utf-8")
    rows = re.findall(r"\('(free|staff)',\s*'[^']*',\s*'[^']*',\s*(\d+),", seed)
    assert {key for key, _ in rows} == {"free", "staff"}, f"seed rows not found: {rows}"
    for key, number in rows:
        assert int(number) == shipped, (
            f"the '{key}' seed is {number} but config.yaml says {shipped}; "
            "both seeded rows must equal the one config key"
        )


def test_the_double_and_the_rpc_name_the_same_timezone():
    """A double that rolled over on a different day than the RPC is worse than none."""
    from web.services.quota_store import QUOTA_TIMEZONE

    claim_sql = next(MIGRATIONS.glob("*_reader_quota_claim_release_and_read_rpcs.sql")).read_text(
        encoding="utf-8"
    )
    assert f"'{QUOTA_TIMEZONE}'" in claim_sql
