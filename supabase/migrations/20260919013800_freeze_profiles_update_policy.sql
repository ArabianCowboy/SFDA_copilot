-- Freeze direct profile writes for disabled accounts, keeping the consent
-- withdrawal carve-out reachable. Slice 1 of docs/account-and-trust-plan.md
-- §3-M2 (decision D5).
--
-- WHAT CHANGES: one predicate added to the live UPDATE policy's USING text
-- (read from pg_policy; these policies predate supabase/migrations/ and
-- survive only as names in migrations/0000_baseline.md):
--
--   BEFORE: USING (( SELECT auth.uid() AS uid) = id)
--   AFTER:  USING (( SELECT auth.uid() AS uid) = id AND (SELECT public.is_active_account()))
--
-- WHAT DOES NOT CHANGE, DELIBERATELY
-- ----------------------------------
-- SELECT is untouched: a locked-out reader must still read `is_disabled`
-- and `disabled_reason` (why they are refused is part of the refusal).
-- INSERT is untouched: the signup fallback runs before a profile row
-- exists, and `is_active_account()` is false when there is no row, so
-- gating INSERT would break every signup.
--
-- WHAT THIS DOES NOT CLOSE: `update_own_preferences` is `security definer`
-- and bypasses RLS, so this policy cannot reach it — 05 gates that
-- function itself. The consent withdrawal RPC (01) is deliberately NOT
-- gated either way: withdrawing while disabled is the carve-out.
--
-- `SET LOCAL lock_timeout`: profiles is read by every request; this DDL
-- must fail fast rather than queue behind a slow read and starve the pool.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction (which is also what makes SET LOCAL meaningful here).
--
-- APPLY NOTE: this file lives in supabase/pending/ (see supabase/README.md).
-- Apply it with apply_migration, read the real version back from
-- list_migrations, then `git mv` it into supabase/migrations/ under that
-- name.

set local lock_timeout = '3s';

alter policy "Users can update own profile" on public.profiles
  using ((select auth.uid() as uid) = id and (select public.is_active_account()));
