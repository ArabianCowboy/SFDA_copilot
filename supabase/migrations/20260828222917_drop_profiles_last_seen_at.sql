-- Drops public.profiles.last_seen_at -- the column public.profile_last_seen replaced
-- (20260828135721_profile_last_seen_table.sql, docs/data-policy-decisions.md §4). Closes
-- the TODO.md entry "Drop profiles.last_seen_at, the column this feature replaced".
-- Own migration per supabase/README.md rule 2 (destructive changes never ride along with
-- a non-destructive one) -- the prerequisite trigger fix landed separately, immediately
-- before this, as 20260828222859_profiles_guard_stops_checking_last_seen_at.sql.
--
-- What was checked before this ran (rule 7):
--   * Row count: 4 (list_tables, public.profiles, at the time this was written).
--   * Foreign keys: none reference profiles.last_seen_at. The FK constraints touching
--     public.profiles are profiles_id_fkey (id -> auth.users), profiles_disabled_by_fkey
--     (disabled_by -> auth.users), and profile_last_seen_user_id_fkey
--     (profile_last_seen.user_id -> profiles.id) -- none of the three names or
--     constrains last_seen_at itself.
--   * Indexes: none. last_seen_at was never indexed (list_tables verbose confirms no
--     index beyond the profiles_pkey on id).
--   * Triggers: profiles_guard_privilege_columns was the only trigger function on this
--     table referencing the column, and the immediately preceding migration removed
--     that reference. on_profile_update and profiles_set_marketing_consent_record do
--     not touch it.
--   * Grep: `grep -rn "profiles\.last_seen_at\|new\.last_seen_at\|old\.last_seen_at\|p\.last_seen_at"`
--     across supabase/migrations/ and web/ turns up nothing after the trigger fix above
--     -- admin_get_user has read from profile_last_seen via a left join, not from this
--     column, since 20260828135749_admin_get_user_reads_profile_last_seen.sql. The
--     `last_seen_at` key Python code reads/writes (web/services/admin_store.py,
--     TestAdminStore's in-memory fixture) is the RPC's *output column name*, unaffected
--     by dropping the underlying table column it used to be sourced from.
--
-- A short lock_timeout so this fails loudly rather than queueing behind a live
-- transaction on profiles (Supabase's own guidance for a DROP COLUMN on a table with
-- concurrent traffic): DROP COLUMN is metadata-only in Postgres but still takes
-- ACCESS EXCLUSIVE. `set local` scopes the timeout to this transaction only, and
-- apply_migration already wraps this file in one.
set local lock_timeout = '5s';

alter table public.profiles
  drop column last_seen_at;
