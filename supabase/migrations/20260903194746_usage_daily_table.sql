-- The counter. One row per account per calendar day that the account actually
-- asked something on; no row means no questions asked that day. Written only by
-- chat_claim_daily_message and chat_release_daily_message, both security
-- definer. See docs/reader-quota-plan.md §1.3.
--
-- References auth.users, not public.profiles: usage is a fact about an
-- authenticated identity and must be recorded even for an account whose profile
-- row is somehow missing -- the same account-shaped reasoning that made
-- touch_last_seen tolerate a profileless account (20260828143044). `on delete
-- cascade` because usage cannot outlive the account it describes; this is also
-- what makes the account-deletion story require no extra step.
--
-- `day` is a DATE in Asia/Riyadh (owner decision, 2026-09-03), computed by the
-- claim RPC from a single named constant. It is stored, never recomputed on
-- read, so a later change to the boundary cannot retroactively re-bucket
-- history that was already counted under the old rule.
create table public.usage_daily (
  user_id uuid not null references auth.users(id) on delete cascade,
  day     date not null,
  used    integer not null default 0 check (used >= 0),
  primary key (user_id, day)
);

-- README rule 4: the composite primary key's leading column IS user_id, so it
-- already serves the foreign key and the cascade. No second index is added --
-- deliberately. There is no query in this design that filters on `day` alone
-- (the claim and the read both name a user), and an unused index would show up
-- in the performance advisor and cost every claim a write.

alter table public.usage_daily enable row level security;
-- Intentional zero policies; standing-findings row in supabase/README.md.
revoke all on table public.usage_daily
  from anon, authenticated, public, service_role;
