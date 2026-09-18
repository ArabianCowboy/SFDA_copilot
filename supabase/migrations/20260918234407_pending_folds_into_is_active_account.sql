-- A live deletion saga deactivates the account, in the one predicate every
-- chat policy already calls. Slice 2a of docs/account-and-trust-plan.md
-- §3-M4 (decision D2: `deletion_pending` is its own state, NOT `is_disabled`).
--
-- SLICE 2c REVISION — ONE PREDICATE SPLIT INTO TWO. This file as first
-- written folded EVERY non-terminal saga state into `is_active_account()`,
-- freezing a pending account out of chat writes, profile writes and
-- preference writes for the whole 30-day grace. The product owner reversed
-- that after adversarial review: a `pending` account is a normal account
-- with a scheduled deletion — fully usable, with the freeze beginning only
-- once the purge actually starts. So the operator/consent boundary and the
-- reader write freeze are now DIFFERENT questions, answered by different
-- predicates defined side by side below:
--
--   * `account_deletion_is_live(uuid)` — UNCHANGED semantics: true for every
--     non-terminal state (`pending`, `purging`, `auth_delete_begun`,
--     `failed`). Answers "is there a saga in flight". Kept by its
--     operator/consent callers: 12 (`admin_set_user_flags` refuses an Enable
--     or a role change on a live-saga target — a pure Disable goes through,
--     slice 2d — while subtler operator handling still belongs to the saga's
--     cancel, never a flag change) and 14 (`grant_marketing_consent`
--     refuses a live-saga owner — collecting a FRESH marketing permission
--     from someone who has asked to be erased is the one thing even a
--     "fully usable" grace window must still refuse). Do NOT "fix" those
--     callers onto the narrower predicate: the apparent inconsistency is
--     the decision.
--   * `account_deletion_freezes_writes(uuid)` — NEW: true only for
--     `purging`, `auth_delete_begun` and `failed`. `pending` is NOT frozen.
--     `failed` stays frozen (fail closed: a partial purge must not silently
--     reactivate an account). Answers "must this account stop writing".
--     Called by `is_active_account()` below and by `chat_append_turn`
--     (11) — and by nothing else.
--
-- WHY THIS IS SAFE — each checked before the split shipped:
--
--   * The expiry purge (`account_deletion_purge_transcripts`, 10) deletes
--     `chat_sessions` by `owner_id`, idempotently — deleting already-deleted
--     sessions deletes nothing — so conversations written during grace are
--     removed by machinery that already exists.
--   * `begin_auth_delete` (10) RE-PURGES inside the step that moves the saga
--     to `auth_delete_begun`, closing the in-flight-stream window from the
--     other side: a turn admitted just before the first purge still lands,
--     and the re-purge removes it.
--   * Nothing leaks past the purge because of this change: the archive
--     branch of `chat_append_turn` only ever fires on a filed turn, and a
--     filed turn's session is owned by `owner_id`, which is exactly what
--     both purges delete by.
--
-- WHY NOT is_disabled. `_authenticate_request` refuses a disabled account
-- with 403 (web/api/app.py:932-933), which would make the cancel path
-- unreachable — a grace window nobody can cancel from is storage, not
-- recovery. And `admin_set_user_flags` clears the disabled columns
-- unconditionally
-- (20260828001543_admin_rpcs_require_an_enabled_actor.sql:252-264), so an
-- operator's Enable would silently resurrect a pending deletion. The saga
-- state lives in `account_deletions` (07) and touches no `profiles` column.
--
-- CONSEQUENCES, EACH CHECKED (revised for the split — `pending` now passes):
--
--   * Chat writes CONTINUE during `pending`. There is no INSERT policy on
--     any chat table by design, so the only browser-direct write is DELETE
--     on chat_sessions, whose USING clause calls this function — now true
--     for a pending owner. Service-side writes go through
--     `chat_append_turn`, which refuses on the NEW predicate in 11, so a
--     pending reader's turn is filed normally and only a purging/failed
--     one is refused (a definer function bypasses RLS, so this fold alone
--     cannot reach it either way).
--   * Slice 1's 04 works normally during `pending`: the profiles UPDATE
--     policy calls this function, so a pending reader CAN write `first_name`
--     et alii directly again. The freeze now begins with the purge, not
--     with the request.
--   * Slice 1's 05 works normally during `pending`: `update_own_preferences`
--     gates on this function, so theme/language/search_scope writes go
--     through again until the purge starts.
--   * Consent withdrawal STILL WORKS in every state: slice 1's
--     `update_own_marketing_consent` (01) deliberately never calls this
--     function — withdrawing while deletion is pending is the same carve-out
--     as withdrawing while disabled, and this fold does not touch it.
--   * Consent GRANT stays refused during `pending` — but NOT through this
--     function: 14 consults `account_deletion_is_live`, the wider predicate,
--     on purpose (see above).
--   * SELECT policies are untouched by this file — and the honest limit the
--     original header recorded is gone with the reason for it: since
--     `pending` no longer reads as inactive, a pending reader keeps their
--     browser-direct PostgREST reads too. A purging/failed owner still loses
--     them as a side effect of the fold; that path has no cancel decision
--     left to make in the UI, so nothing reachable is lost.
--
-- `create or replace`: the argument list is unchanged (no arguments), so
-- this is not the drop-and-create case. Grants are restated explicitly in
-- the house style so the browser-callable exemption stays visible.
--
-- The live-saga predicate lives HERE, beside its first consumer, rather
-- than in 10: 11 and 12 need it too, and this file lands first. Both
-- predicates are full-contract definer functions (service_role only —
-- browsers reach the pending question through 09, never these), so
-- function_acls.test.sql's "every callable granted to service_role"
-- assertion holds without a new exemption, for the new function exactly as
-- for the existing one.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction.
--
-- APPLY NOTE: this file lives in supabase/pending/ (see supabase/README.md).
-- Apply it with apply_migration, read the real version back from
-- list_migrations, then `git mv` it into supabase/migrations/ under that
-- name. Lands after 07 (the table it reads) and after slice 1's 04/05 (the
-- policies and function that call it) — order is by ordinal.

-- True while the account has a saga row that is neither completed nor
-- cancelled. `failed` counts as live: fail closed, per the 07 header.
-- Null-safe: a null argument matches no row and returns false.
--
-- UNCHANGED BY SLICE 2c, DELIBERATELY. The narrower
-- `account_deletion_freezes_writes` below answers the write-freeze question;
-- this answers the operator/consent question, and its two callers — 12
-- (`admin_set_user_flags`) and 14 (`grant_marketing_consent`) — keep calling
-- THIS, including for `pending`. See the header: narrowing them would reopen
-- the resurrection hole (12) and let a grace-window reader grant fresh
-- marketing consent (14).
create function public.account_deletion_is_live(p_user_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.account_deletions d
     where d.user_id = p_user_id
       and d.state not in ('completed', 'cancelled')
  );
$$;

revoke execute on function public.account_deletion_is_live(uuid)
  from anon, authenticated, public;
grant execute on function public.account_deletion_is_live(uuid)
  to service_role;

-- True while the account's writes are frozen: every state from the moment the
-- purge starts onward — `purging`, `auth_delete_begun`, `failed` and
-- `completed`. Equivalently: everything except `pending` and `cancelled`.
--
-- `pending` is NOT frozen: a pending account is a normal account with a
-- scheduled deletion, fully usable until the purge starts (slice 2c).
-- `cancelled` is NOT frozen: the deletion was called off and the account is
-- ordinary again.
-- `failed` IS frozen: fail closed, per the 07 header — a partial purge must
-- not silently reactivate an account.
--
-- `completed` IS FROZEN, PERMANENTLY, AND THAT IS NOT REDUNDANT. It is
-- tempting to leave it out on the grounds that a completed account no longer
-- exists, but `chat_append_turn` takes `p_owner_id` as an ARGUMENT and lazily
-- creates the session row — it never reads `profiles` or `auth.users`, and
-- `chat_sessions.owner_id` has no foreign key (13 is parked). So a stream
-- admitted during grace, which may run for up to 300 seconds
-- (`docs/ARCHITECTURE.md:173`), can call `chat_append_turn` AFTER the timer
-- has purged, deleted the provider user and completed the saga — the whole
-- run takes seconds. The turn would then land as full question and answer
-- text under an owner id that resolves to nothing: unreachable by any purge
-- path, invisible to the reader, and contradicting the copy's "every
-- conversation". The re-purge in `begin_auth_delete` does not close this; it
-- runs milliseconds after the first purge, not minutes later.
--
-- A user id is never reused, so freezing a completed owner forever costs
-- nothing and is the only state in which "frozen" is simply permanent.
-- Null-safe, like the predicate above.
create function public.account_deletion_freezes_writes(p_user_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.account_deletions d
     where d.user_id = p_user_id
       and d.state in ('purging', 'auth_delete_begun', 'failed', 'completed')
  );
$$;

revoke execute on function public.account_deletion_freezes_writes(uuid)
  from anon, authenticated, public;
grant execute on function public.account_deletion_freezes_writes(uuid)
  to service_role;

create or replace function public.is_active_account()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.profiles
     where id = (select auth.uid())
       and is_disabled = false
   )
  -- A saga past grace deactivates the account without disabling it:
  -- `failed` counts as frozen (fail closed — a partial purge must not
  -- silently reactivate), so only the two terminal states plus `pending`
  -- are excluded from the freeze here. `pending` passes every gate this
  -- function feeds — chat RLS, the frozen profiles UPDATE policy (04) and
  -- `update_own_preferences` (05) — by consulting the NARROW predicate.
  -- The operator/consent boundary stays on the WIDE one (see above).
  and not public.account_deletion_freezes_writes((select auth.uid()));
$$;

revoke execute on function public.is_active_account() from anon, public;
grant execute on function public.is_active_account() to authenticated;
