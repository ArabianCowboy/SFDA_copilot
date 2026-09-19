-- Close the browser's direct write path to the four consent columns.
-- Slice 1 of docs/account-and-trust-plan.md §3-M1b / D6b.3.
--
-- WHY BOTH UPDATE AND INSERT
-- --------------------------
-- The UPDATE revoke alone leaves the INSERT fallback open:
-- `Services.updateProfile` upserts `{ id, ...updates }`, so for an account
-- with no profile row yet that upsert takes the INSERT branch, and the
-- consent trigger's INSERT branch validates only that the version is 1-64
-- trimmed characters
-- (20260823014034_marketing_consent_record.sql:129-142) — a client could
-- stamp an arbitrary version string with `marketing_consent = true` without
-- ever seeing the prompt. Signup itself does not need these grants:
-- `handle_new_user` runs as the table owner, not as `authenticated`.
--
-- WHAT MOVES WHERE: granting goes through `grant_marketing_consent`
-- (02, service-role only, version stamped server-side) and withdrawing
-- through `update_own_marketing_consent` (01, withdrawal-only). `age` is
-- deliberately NOT revoked — it is reader-owned data, still written through
-- the Identity form's upsert.
--
-- ORDERING: applies only AFTER the repointed toggle
-- (static/js/account/handlers.js) is verified — this revoke is what makes
-- 01/02's validation unbypassable, and landing it first would break the
-- toggle silently.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction.
--
-- APPLY NOTE: this file lives in supabase/pending/ (see supabase/README.md).
-- Apply it with apply_migration, read the real version back from
-- list_migrations, then `git mv` it into supabase/migrations/ under that
-- name. supabase/tests/privileges.test.sql's `writable_columns` list moves
-- with it: the four consent columns leave that list for a revoked list in
-- the same commit.

revoke update (
  marketing_consent,
  marketing_consent_policy_version,
  marketing_consent_language,
  marketing_consent_surface
) on public.profiles from authenticated;

revoke insert (
  marketing_consent,
  marketing_consent_policy_version,
  marketing_consent_language,
  marketing_consent_surface
) on public.profiles from authenticated;
