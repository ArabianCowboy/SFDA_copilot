"""Slice 2c's predicate split, asserted against the migration drafts.

Slice 2a folded EVERY non-terminal saga state into `is_active_account()`,
freezing a pending account out of chat, profile and preference writes for
the whole 30-day grace. Slice 2c splits that one predicate into two:

* `account_deletion_is_live(uuid)` — UNCHANGED, every non-terminal state.
  Kept by the operator/consent callers (12's `admin_set_user_flags`, 14's
  `grant_marketing_consent`), including for `pending`.
* `account_deletion_freezes_writes(uuid)` — NEW, `purging` /
  `auth_delete_begun` / `failed` only. Called by `is_active_account()`
  (08) and by `chat_append_turn` (11), so a pending turn is filed normally
  and only a purging/failed one is refused.

These tests read the UNAPPLIED drafts in `supabase/pending/` — deliberately.
The predicates live in SQL no pytest fixture can execute (there is no
database under the fast suite), so the only runnable proof that the split
is complete is that every draft consults the right predicate. Each test
fails against the pre-2c drafts, for the reason its own comment gives: 08
defined no freeze predicate and folded `is_live` into the active-account
gate, and 11 refused on `is_live` three times over.

The behavioural halves — a pending turn IS filed, a purging/failed one is
still refused, a pending profile/prefs write succeeds — are asserted for
real in `supabase/tests/account_deletion.test.sql` ((g), (g2), (p)), which
runs by hand against a live project.
"""

from __future__ import annotations

from pathlib import Path

PENDING = Path(__file__).resolve().parents[2] / "supabase" / "pending"


def _read(name: str) -> str:
    return (PENDING / name).read_text(encoding="utf-8")


def _code(text: str) -> str:
    """The draft with its `--` comments stripped, so assertions pin the
    statements rather than the prose about them (the headers name both
    predicates on purpose, and counting those would prove nothing)."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))


def test_the_freeze_predicate_exists_with_the_narrow_state_list():
    """08 must define `account_deletion_freezes_writes` over exactly the
    post-grace states. Fails against the pre-2c 08: no such function, so
    `in` finds nothing and the definition assertion fails first."""
    code = _code(_read("08_pending_folds_into_is_active_account.sql"))

    assert "create function public.account_deletion_freezes_writes(p_user_id uuid)" in code
    # The freeze list, as written in the EXISTS subquery.
    assert "d.state in ('purging', 'auth_delete_begun', 'failed', 'completed')" in code


def test_the_freeze_predicate_covers_completed_so_a_late_turn_cannot_land():
    """`completed` MUST be in the freeze set, and this is the one entry that
    looks redundant and is not.

    `chat_append_turn` takes `p_owner_id` as an argument and lazily creates
    the session row. It never reads `profiles` or `auth.users`, and
    `chat_sessions.owner_id` has no foreign key (13 is parked). A stream
    admitted during grace can run for up to 300 seconds
    (`docs/ARCHITECTURE.md:173`), while the timer's whole run — purge,
    re-purge, provider delete, complete — takes seconds. So that stream can
    file its turn AFTER the saga completed, landing full question and answer
    text under an owner id that resolves to nothing: no purge path reaches
    it, the reader cannot see it, and the copy promised "every conversation".

    The re-purge does not close this. It runs milliseconds after the first
    purge, not minutes later.

    Fails against the first 2c draft, whose freeze list stopped at `failed`.
    """
    code = _code(_read("08_pending_folds_into_is_active_account.sql"))
    freeze_body = code.split("account_deletion_freezes_writes(p_user_id uuid)", 1)[1]
    states = freeze_body.split("d.state in (", 1)[1].split(")", 1)[0]

    assert "'completed'" in states
    # And the two states that must NOT freeze, so this never silently widens
    # into "any row at all" and re-freezes a cancelled or pending account.
    assert "'pending'" not in states
    assert "'cancelled'" not in states


def test_is_active_account_consults_the_freeze_predicate_not_the_live_one():
    """The fold must answer the write-freeze question, not the
    saga-in-flight question. Fails against the pre-2c 08, whose
    `is_active_account()` body calls `account_deletion_is_live` and never
    names the freeze predicate."""
    code = _code(_read("08_pending_folds_into_is_active_account.sql"))

    assert "not public.account_deletion_freezes_writes((select auth.uid()))" in code
    assert "account_deletion_is_live((select auth.uid())" not in code


def test_the_live_predicate_keeps_its_wide_semantics():
    """`account_deletion_is_live` must still cover every non-terminal state —
    narrowing it would silently unfreeze the operator/consent callers below.
    Fails against any "simplification" that rewrites it as the freeze list."""
    code = _code(_read("08_pending_folds_into_is_active_account.sql"))

    assert "d.state not in ('completed', 'cancelled')" in code


def test_chat_append_turn_refuses_on_the_freeze_predicate():
    """All three checks in 11 — the lazy-create guard, the post-purge
    ownership branch, the post-probe refusal — must consult the narrow
    predicate, so a pending turn is filed normally. Fails against the
    pre-2c 11, which calls `account_deletion_is_live` three times."""
    code = _code(_read("11_chat_append_turn_refuses_a_pending_owner.sql"))

    assert code.count("public.account_deletion_freezes_writes(p_owner_id)") == 3
    assert "account_deletion_is_live" not in code


def test_the_operator_and_consent_gates_keep_the_live_predicate():
    """12 (`admin_set_user_flags`) and 14 (`grant_marketing_consent`) must
    KEEP refusing a `pending` target/owner: the operator's path for a
    pending account is the saga's cancel, and collecting fresh marketing
    permission from someone who asked to be erased stays refused even in a
    fully usable grace window. Fails against a split that "fixes" these
    onto the narrow predicate — the apparent inconsistency is the decision,
    and this pins it."""
    twelve = _code(_read("12_admin_set_user_flags_refuses_a_pending_target.sql"))
    fourteen = _code(_read("14_grant_marketing_consent_refuses_a_live_saga.sql"))

    assert "public.account_deletion_is_live(p_user_id)" in twelve
    assert "account_deletion_freezes_writes" not in twelve
    assert "public.account_deletion_is_live(p_owner_id)" in fourteen
    assert "account_deletion_freezes_writes" not in fourteen


def test_no_pending_draft_consults_the_wrong_predicate():
    """The whole split in one scan: across every pending draft, the freeze
    predicate is consulted only where a write is at stake (08's gate, 11's
    three checks), and the live predicate everywhere else. A future draft
    that reaches for the wrong one fails here rather than drifting."""
    live_users = set()
    freeze_users = set()
    for path in sorted(PENDING.glob("*.sql")):
        code = _code(path.read_text(encoding="utf-8"))
        if "public.account_deletion_is_live(" in code:
            live_users.add(path.name)
        if "public.account_deletion_freezes_writes(" in code:
            freeze_users.add(path.name)

    assert live_users == {
        "08_pending_folds_into_is_active_account.sql",
        "12_admin_set_user_flags_refuses_a_pending_target.sql",
        "14_grant_marketing_consent_refuses_a_live_saga.sql",
    }, f"live-predicate callers changed: {sorted(live_users)}"
    assert freeze_users == {
        "08_pending_folds_into_is_active_account.sql",
        "11_chat_append_turn_refuses_a_pending_owner.sql",
    }, f"freeze-predicate callers changed: {sorted(freeze_users)}"
