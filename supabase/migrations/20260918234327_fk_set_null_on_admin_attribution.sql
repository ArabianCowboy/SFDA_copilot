-- Migration A: the two NO ACTION FKs to auth.users become ON DELETE SET NULL.
-- Slice 2a of docs/account-and-trust-plan.md §3-M3 (decision D1: a reader may
-- delete their own account, so deleting one must not be refused).
--
-- WHAT WAS WRONG. Exactly two foreign keys to `auth.users` in `public` are
-- `NO ACTION` (verified against the live catalogue 2026-09-18, recorded in
-- docs/account-and-trust-plan.md §0):
--
--   profiles_disabled_by_fkey     on public.profiles(disabled_by)
--   app_settings_updated_by_fkey  on public.app_settings(updated_by)
--
-- The default is NO ACTION: the parent delete is refused while children
-- exist. So deleting an account that ever disabled someone (disabled_by) or
-- ever wrote a setting (updated_by) fails — which in practice means deleting
-- an administrator. SET NULL keeps the referencing row and anonymises the
-- attribution, the same call the notification and quota tables already make
-- (20260823202146_notification_recipients_and_reads.sql:17,38 and
-- 20260903194732_reader_quota_overrides_table.sql:33).
--
-- WHAT WAS CHECKED. Both columns are nullable — `disabled_by uuid references
-- auth.users(id)` (20260814005509_lock_profile_privileges_and_repair_signup.sql:88)
-- and `updated_by uuid references auth.users(id)`
-- (20260814022601_app_settings.sql:37) — so SET NULL can never violate a NOT
-- NULL. Both already carry a partial index on the column
-- (profiles_disabled_by_idx, app_settings_updated_by_idx), which a drop and
-- re-add of the CONSTRAINT does not touch: indexes survive; only the
-- constraint is replaced. The other per-reader FKs to auth.users need no
-- change: profiles_id_fkey and usage_daily_user_id_fkey are CASCADE,
-- user_notification_reads_user_id_fkey, notification_recipients_user_id_fkey
-- and reader_quota_overrides_set_by_fkey are already SET NULL, and
-- profile_last_seen.user_id and reader_quota_overrides.user_id reference
-- public.profiles, not auth.users, so they purge by cascade through
-- profiles_id_fkey when the GoTrue delete cascades the profile row.
--
-- DESTRUCTIVE DDL, OWN FILE, BACKUP TAKEN BEFORE APPLYING. Dropping a
-- constraint briefly removes the referential guard on that column; nothing
-- else in this file touches data. Take a backup first (see TODO.md's backup
-- entry), apply, then re-run the advisors and supabase/tests/.
--
-- `SET LOCAL lock_timeout`: both tables are read by every request; this DDL
-- must fail fast rather than queue behind a slow read and starve the pool.
-- `NOT VALID` then a separate `VALIDATE`: the validate takes SHARE UPDATE
-- EXCLUSIVE rather than the ACCESS EXCLUSIVE a plain re-add would hold for
-- the whole scan.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction (which is also what makes SET LOCAL meaningful here).
--
-- APPLY NOTE: this file lives in supabase/pending/ (see supabase/README.md).
-- Apply it with apply_migration, read the real version back from
-- list_migrations, then `git mv` it into supabase/migrations/ under that
-- name.

set local lock_timeout = '3s';

alter table public.profiles
  drop constraint profiles_disabled_by_fkey;

alter table public.profiles
  add constraint profiles_disabled_by_fkey
  foreign key (disabled_by) references auth.users(id) on delete set null
  not valid;

alter table public.profiles
  validate constraint profiles_disabled_by_fkey;

alter table public.app_settings
  drop constraint app_settings_updated_by_fkey;

alter table public.app_settings
  add constraint app_settings_updated_by_fkey
  foreign key (updated_by) references auth.users(id) on delete set null
  not valid;

alter table public.app_settings
  validate constraint app_settings_updated_by_fkey;
