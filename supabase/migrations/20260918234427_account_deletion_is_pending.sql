-- The reader's own grace-window answer: am I pending deletion?
-- Slice 2a of docs/account-and-trust-plan.md §3-M4.
--
-- Bound to the caller's own row via auth.uid(), never a passed-in id — this
-- function is SECURITY DEFINER and would otherwise let any caller probe any
-- account's deletion state. Answers for state = 'pending' ONLY: that is the
-- state with a reachable cancel path, which is the only state the reader
-- needs to distinguish (slice 2b's cancel/status surface). A saga in
-- `purging` or beyond is past cancellation and says nothing to the browser.
--
-- CONTRACT EXEMPTION: browser-callable by design, so exempt from points 3
-- and 4 of the RPC contract (supabase/README.md) like `is_active_account()`,
-- `update_own_preferences(jsonb)` and `update_own_marketing_consent(boolean)`
-- before it — the FOURTH such exemption. Registered there and in
-- supabase/tests/function_acls.test.sql's `browser_callable` allow-list.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction.
--
-- APPLY NOTE: this file lives in supabase/pending/ (see supabase/README.md).
-- Apply it with apply_migration, read the real version back from
-- list_migrations, then `git mv` it into supabase/migrations/ under that
-- name.

create function public.account_deletion_is_pending()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.account_deletions d
     where d.user_id = (select auth.uid())
       and d.state = 'pending'
  );
$$;

revoke execute on function public.account_deletion_is_pending() from anon, public;
grant execute on function public.account_deletion_is_pending()
  to authenticated, service_role;
