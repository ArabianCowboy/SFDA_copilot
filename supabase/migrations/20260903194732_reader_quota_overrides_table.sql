-- One optional per-account override of the tier's daily allowance, with an
-- optional validity window. Kept OFF public.profiles deliberately: profiles
-- carries on_profile_update, which bumps updated_at on every UPDATE and feeds
-- the optimistic-concurrency check admin_update_profile makes, so storing a
-- quota here would make an allowance change look like a profile edit. The
-- precedent is profile_last_seen (20260828135721) and the argument is
-- docs/data-policy-decisions.md §4. See docs/reader-quota-plan.md §1.2.
--
-- The audit_log keeps the full history of who changed what; this table holds
-- only the CURRENT override, so "clear the override" is a delete, not a null.
create table public.reader_quota_overrides (
  -- Primary key doubles as the FK index (README rule 4 satisfied by the PK).
  user_id             uuid primary key references public.profiles(id) on delete cascade,
  -- >= 0 for the same reason as tiers.daily_message_limit: an override of 0
  -- silences one account for the day without disabling the account.
  daily_message_limit integer not null check (daily_message_limit >= 0),
  reason              text check (reason is null or length(reason) <= 500),
  -- Optional window (owner decision, 2026-09-03). Both null is the ordinary
  -- case and means "in force until an operator clears it" -- the only behaviour
  -- that existed before these columns. A window is how "500 a day until the end
  -- of the month" is expressed WITHOUT a scheduler: nothing sweeps this table,
  -- the claim RPC simply stops matching the row once now() leaves the window,
  -- and the account falls back to its tier on the very next claim.
  starts_at           timestamptz,
  expires_at          timestamptz,
  constraint reader_quota_overrides_window_chk
    check (starts_at is null or expires_at is null or expires_at > starts_at),
  -- Attribution only. `on delete set null` because deleting the administrator's
  -- account must not refuse the delete -- the precedent is
  -- notification_recipients.user_id (20260823202146), NOT profiles.disabled_by,
  -- which has no stated action and therefore refuses. The audit_log retains who
  -- did it regardless.
  set_by              uuid references auth.users(id) on delete set null,
  set_at              timestamptz not null default now()
);

-- README rule 4: the second foreign key needs its own index. Partial, because
-- set_by is null for any override whose author has since been deleted.
create index reader_quota_overrides_set_by_idx
  on public.reader_quota_overrides (set_by) where set_by is not null;

alter table public.reader_quota_overrides enable row level security;
-- Intentional zero policies; standing-findings row in supabase/README.md.
revoke all on table public.reader_quota_overrides
  from anon, authenticated, public, service_role;
