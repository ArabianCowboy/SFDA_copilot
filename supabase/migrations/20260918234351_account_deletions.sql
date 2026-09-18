-- The deletion saga ledger: one row per account being deleted, and nothing else.
-- Slice 2a of docs/account-and-trust-plan.md §3-M4 (decisions D1, D2, D3).
--
-- NO FOREIGN KEY TO auth.users, DELIBERATELY. The row must outlive the
-- provider deleting that user: after the GoTrue delete cascades the profile
-- row, this is the only record that a deletion happened and finished. A
-- referencing FK would either block that delete (NO ACTION/RESTRICT) or
-- delete the ledger with it (CASCADE) — both defeat the purpose. Likewise no
-- FK to public.profiles, for the same reason through the cascade.
--
-- NO PII ON THIS TABLE, EVER (decision D3). The audit pattern stores
-- actor_email, request_ip and user_agent
-- (20260814032139_audit_log.sql:27-41) in an append-only table with no FK,
-- so a self-deletion recorded through that pattern would preserve the
-- deleted person's email and IP forever — the exact opposite of erasure.
-- This table therefore carries UUIDs, states, timestamps and counters ONLY.
-- No email. No IP. No user agent. No display name. `last_error_code` holds
-- a DL-code from the vocabulary below, never a provider message (a raw
-- message can carry an email or an IP). The re-registration lookup the grace
-- window creates has NO column here: pgcrypto availability could not be
-- verified without touching the live database (no `pg_extension` read was
-- possible from this environment, and nothing in this repository records it
-- as installed), so rather than inventing a lookup value, none is stored —
-- slice 2b answers the "is this email pending deletion?" question without a
-- database lookup column. If pgcrypto is later confirmed, add the keyed-hash
-- column in its own migration and destroy the value at completion/cancel.
--
-- ERROR CODE VOCABULARY (stored in last_error_code, raised by 10/11/12):
--
--   DL001  chat_append_turn refused: the owner has a live deletion saga
--   DL002  admin_set_user_flags refused: the target has a live deletion saga
--   DL003  account_deletion_request refused: the target is an administrator
--   DL004  saga step precondition failed: no live row, wrong state, or the
--          lease is held by another driver (a claim returning no row is the
--          same outcome without the raise — see 10)
--   DL005  account_deletion_cancel refused: transcripts are already purged,
--          so there is nothing truthful left to cancel back to
--   DL006  account_deletion_complete refused: the profile row still exists,
--          so PII remains and completion must not be recorded
--
-- THE STATE MACHINE. `state` is constrained to exactly these six. Every
-- legal transition, and nothing else:
--
--   pending ──grace expires, claim──> purging ──purge + re-purge, claim──>
--     auth_delete_begun ──GoTrue gone──> completed
--   pending ──cancel──> cancelled
--   failed ──cancel, only if transcripts_purged_at is null──> cancelled
--   pending | purging | auth_delete_begun | failed ──fail──> failed
--   failed ──claim──> purging (retry re-enters the purge; the purge is
--     idempotent — deleting already-deleted sessions deletes nothing)
--
-- `cancelled` and `completed` are terminal. `failed` counts as LIVE for the
-- `account_deletion_is_live` predicate: a failed saga may hold a partial
-- purge, and treating it as not-live would silently reactivate an account
-- whose transcripts are half gone. Fail closed; the operator cancels or
-- retries.
--
-- GRACE IS 30 DAYS FROM requested_at (decision D2, matching
-- docs/data-policy-decisions.md §1). grace_until and purge_after are equal
-- by construction today; the split exists so a future stagger needs no
-- schema change. The driver acts when now() >= purge_after; the reader may
-- cancel while state = 'pending'.
--
-- LEASES. lease_until is the M5 concurrency guard: every step claims the row
-- with `update ... where lease_until < now() ... returning`, so two drivers
-- under `--threads 8` cannot run one step twice. A claim that returns no row
-- means someone else holds it or the row is not due — a normal outcome, not
-- an error. attempt_count counts claims; next_attempt_at tells the timer
-- driver when to look again.
--
-- RLS ON, NO BROWSER POLICIES AT ALL. This table is service_role (SELECT,
-- for the console reconcile read) and RPC territory (every write through
-- the definer functions in 10, which run as the table owner). A policy is
-- how you would let the browser in, and nothing in a browser has any
-- business here — the reader's only window is account_deletion_is_pending
-- (09), which answers for their own row and exposes nothing else.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction.
--
-- APPLY NOTE: this file lives in supabase/pending/ (see supabase/README.md).
-- Apply it with apply_migration, read the real version back from
-- list_migrations, then `git mv` it into supabase/migrations/ under that
-- name.

create table if not exists public.account_deletions (
  -- The account being deleted. Primary key, not a foreign key: see header.
  user_id uuid primary key,

  state text not null default 'pending'
    check (state in (
      'pending', 'purging', 'auth_delete_begun',
      'completed', 'cancelled', 'failed'
    )),

  requested_at timestamptz not null default now(),
  -- 30-day grace (D2). Cancel deadline and driver start are the same instant
  -- today; see header for why both columns exist.
  grace_until  timestamptz not null,
  purge_after  timestamptz not null,

  -- Driver bookkeeping. lease_until null means unclaimed.
  next_attempt_at timestamptz not null default now(),
  attempt_count   integer    not null default 0 check (attempt_count >= 0),
  lease_until     timestamptz,

  -- Purge and provider progress markers. Null until the step runs.
  transcripts_purged_at timestamptz,
  auth_delete_begun_at  timestamptz,
  auth_deleted_at       timestamptz,

  -- Terminal timestamp for completed AND cancelled alike.
  completed_at timestamptz,

  -- A DL-code from the header vocabulary, never a message. Null means the
  -- last step reported no error.
  last_error_code text,

  check (completed_at is null or state in ('completed', 'cancelled'))
);

comment on table public.account_deletions is
  'Self-serve deletion saga ledger (D1/D2). UUIDs, states, timestamps and '
  'counters only — no email, no IP, no user agent (D3). One row per account; '
  'no FK to auth.users or profiles so the row outlives the deleted account. '
  'Writes only through the service-role saga RPCs; reads only service_role '
  'SELECT and those RPCs. RLS enabled with no policies by design.';

create index if not exists account_deletions_due_idx
  on public.account_deletions (next_attempt_at)
  where state not in ('completed', 'cancelled');

alter table public.account_deletions enable row level security;

-- Belt to the RLS braces: born closed by the global default, stated
-- explicitly so a later default change cannot silently open it.
revoke all on public.account_deletions from anon, authenticated, public;
revoke all on public.account_deletions from service_role;
-- The console reconcile read (slice 2b timer) inspects due rows directly;
-- every write still goes through the definer RPCs in 10.
grant select on public.account_deletions to service_role;
