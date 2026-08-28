-- The two receipts for the default-privileges finding, cleaned up.
-- ===========================================================================
-- Plan: docs/database-improvement-plan.md finding 1, and the precondition for
-- finding 7's function_acls suite.
--
-- Every function in public is revoked from anon/authenticated/public and
-- granted to service_role — bar two documented exemptions (is_active_account,
-- which a chat RLS USING clause evaluates as the querying role, and
-- update_own_preferences, which is browser-callable by design). Two others
-- were neither:
--
--   select proname, proacl::text from pg_proc
--    where pronamespace = 'public'::regnamespace and proacl::text like '%anon=X%';
--   -- audit_log_is_append_only  | {=X/postgres, …, anon=X/postgres, …}
--   -- handle_profile_update     | {=X/postgres, …, anon=X/postgres, …}
--
-- Both are trigger functions, so neither is reachable through PostgREST — it
-- does not expose functions returning `trigger`, and Postgres refuses a direct
-- call outright. THE EXPOSURE IS NIL AND THE DISCIPLINE GAP IS NOT: these two
-- were missed by exactly the mechanism that would miss a consequential one,
-- their own migrations (20260814032139 and the profiles trigger work) simply
-- did not write the revoke line, and nothing in CI said so.
--
-- The default-privileges migration earlier in this wave was supposed to make
-- that class impossible. It does for tables and sequences and DOES NOT for
-- functions — Postgres merges the built-in default, which grants EXECUTE to
-- PUBLIC, with the stored one, so ALTER DEFAULT PRIVILEGES cannot take PUBLIC
-- off a future function. That correction is recorded at the end of
-- 20260828000737. A per-function REVOKE still works, which is what this is.
--
-- WHY THE TRIGGERS KEEP FIRING. Postgres checks EXECUTE on a trigger function
-- when the trigger is CREATED, not each time it fires. Both triggers already
-- exist, and the function owner (postgres) retains EXECUTE regardless.
-- Verified after applying: an UPDATE on public.audit_log still raises from
-- audit_log_is_append_only, and an UPDATE on public.profiles still moves
-- updated_at via handle_profile_update.
--
-- After this, "no function in public is executable by anon or authenticated,
-- except the two named exemptions" is true and can be asserted rather than
-- hoped for. supabase/tests/function_acls.test.sql does exactly that.

revoke execute on function public.audit_log_is_append_only()
  from anon, authenticated, public;

revoke execute on function public.handle_profile_update()
  from anon, authenticated, public;
