-- 0003 · Runtime settings an administrator can change without a deploy.
--
-- WHY NOT public.chatbot_settings
-- -------------------------------
-- That table already exists, is empty, and is the wrong shape:
-- `rate_limit_per_minute` as a single global scalar belongs on a tier rather
-- than on the instance, and `response_style` duplicates territory that
-- temperature and the system message already own. Reusing it would mean
-- inheriting a schema somebody abandoned before it was ever read. It is left
-- untouched rather than dropped — a destructive change to an unrelated table
-- has no business riding along in a feature migration.
--
-- WHY ONE JSONB DOCUMENT RATHER THAN A COLUMN PER SETTING
-- -------------------------------------------------------
-- The set of settings will grow; that is what an operations console is for.
-- A column each means a migration each. The cost is no database-level type
-- checking, which is paid for by validating against a Python schema on write
-- and falling back to the deployed default on read when a value is malformed.
--
-- WHY OVERRIDES ONLY, NEVER A FULL COPY
-- --------------------------------------
-- The document holds only what an administrator has actually changed. Removing
-- a key reverts to the value in config.yaml, and a deploy that changes a
-- default is picked up rather than silently shadowed by a stale row written
-- months earlier. A settings table that mirrors the whole config is a settings
-- table that pins it.
--
-- There is deliberately no `version` column for optimistic concurrency. One
-- operator cannot race themselves. Add it alongside the second administrator.

create table if not exists public.app_settings (
  -- Single row, enforced by the check rather than by convention: a second row
  -- would be a silent fork of the instance's configuration.
  id         smallint primary key default 1 check (id = 1),
  settings   jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users(id)
);

insert into public.app_settings (id) values (1) on conflict (id) do nothing;

create index if not exists app_settings_updated_by_idx
  on public.app_settings (updated_by) where updated_by is not null;

-- RLS on, ZERO POLICIES, DELIBERATELY.
--
-- The security advisor reports this as rls_enabled_no_policy (INFO). That is
-- the intent, not an oversight: `anon` and `authenticated` must never read or
-- write this table, and a policy is how you would let them. Every read and
-- write goes through the service role, which bypasses RLS entirely.
--
-- Do not "fix" this by adding a policy.
alter table public.app_settings enable row level security;

-- Belt to the RLS braces: withdraw the default grants so the browser-facing
-- roles cannot reach the table even if a policy is added by mistake later.
revoke all on public.app_settings from anon, authenticated;

comment on table public.app_settings is
  'Single-row runtime configuration overrides. Service-role only; RLS enabled '
  'with no policies by design. Holds only settings an administrator changed — '
  'absent keys fall back to web/config.yaml.';
