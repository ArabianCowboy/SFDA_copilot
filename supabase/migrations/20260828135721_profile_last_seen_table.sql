-- One row per account ever touched by touch_last_seen(uuid). Kept off `profiles`
-- deliberately -- see docs/data-policy-decisions.md's §4. `on delete cascade`
-- because this row exists only to describe the account and should not survive it,
-- matching 20260828001910's reasoning for the notification child tables.
--
-- No role gets any grant at all, service_role included: every reader and writer of
-- this table is a `security definer` function running as its owner, the same
-- reasoning `admin_actor_email` uses (supabase/README.md). New tables are already
-- born inaccessible to anon/authenticated/service_role since 20260828000737; this
-- `revoke all` is explicit belt-and-braces per supabase/README.md's "prefer revoke
-- all over named-verb revokes."
create table public.profile_last_seen (
  user_id      uuid primary key references public.profiles(id) on delete cascade,
  last_seen_at timestamptz not null
);

alter table public.profile_last_seen enable row level security;
-- Intentional: rls_enabled_no_policy is expected here. Every access path is a
-- security definer function running as the table owner; a policy would be how you
-- let the browser or service_role in directly, and nothing should.

revoke all on table public.profile_last_seen from anon, authenticated, public, service_role;
