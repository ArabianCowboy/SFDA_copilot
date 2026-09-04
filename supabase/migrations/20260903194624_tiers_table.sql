-- The operator-owned catalogue of reader tiers. Each row carries the daily
-- message allowance for every account assigned to it, plus the bilingual label
-- the reader and the console both display -- labels are DATA, not catalogue
-- keys, because an operator who creates a tier cannot add a key to
-- web/i18n/*.yaml. See docs/reader-quota-plan.md §1.1.
--
-- `key` is the value profiles.tier already holds, so the regex mirrors what the
-- column has always accepted in practice and keeps the key usable as a machine
-- identifier (it reaches the notification composer's target_tier).
--
-- daily_message_limit >= 0, not >= 1: zero is a legal, meaningful limit (owner
-- decision, 2026-09-03). A tier of 0 means "may sign in, read their history and
-- browse, but may not ask anything today" -- deliberately distinct from
-- is_disabled, which refuses the session outright. The claim RPC's explicit
-- `v_limit >= 1` guard is what makes 0 refuse the FIRST claim of a day as well
-- as later ones, because the INSERT branch of an upsert has no WHERE clause.
--
-- No role gets any grant, service_role included: every reader and writer of this
-- table is a `security definer` function running as its owner, the same
-- reasoning profile_last_seen (20260828135721) and admin_actor_email use.
create table public.tiers (
  key                 text primary key
                      check (key ~ '^[a-z][a-z0-9_]{0,31}$'),
  label_en            text not null check (length(label_en) between 1 and 40),
  label_ar            text not null check (length(label_ar) between 1 and 40),
  daily_message_limit integer not null check (daily_message_limit >= 0),
  ordering            integer not null default 0,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

alter table public.tiers enable row level security;
-- Intentional: rls_enabled_no_policy is expected here, and gets a standing-findings
-- row in supabase/README.md. Every access path is a security definer function
-- running as the table owner; a policy would be how you let the browser or
-- service_role in directly, and nothing should.

revoke all on table public.tiers from anon, authenticated, public, service_role;

-- Seed. 'free' MUST exist before the foreign key in the next migration: it is the
-- column default on profiles.tier, the literal inside
-- profiles_guard_privilege_columns, and what handle_new_user relies on.
--
-- BOTH numbers are hand-copied from web/config.yaml server.quota.daily_messages_default
-- and pinned equal to it by web/tests/test_quota.py::test_seed_matches_shipped_default,
-- which checks BOTH rows. They are deliberately identical on day one: there is no
-- production evidence about usage yet, and the Tiers console tab makes raising
-- 'staff' later a one-click edit with no migration and no deploy. Differentiating
-- them here would be guessing at a number nobody can justify. Change them together
-- or not at all -- an account whose override is cleared must always fall back to a
-- tier limit somebody deliberately set.
insert into public.tiers (key, label_en, label_ar, daily_message_limit, ordering) values
  ('free',  'Free',  'مجاني',     200, 0),
  ('staff', 'Staff', 'الإداريين', 200, 10);
