-- Withdraw marketing consent for the caller's own account, and nothing else.
-- Slice 1 of docs/account-and-trust-plan.md §3-M1 (decision D5: a disabled
-- account may WITHDRAW, never grant).
--
-- WHY A WITHDRAWAL-ONLY RPC, NOT A SECOND POLICY
-- ----------------------------------------------
-- Freezing the profiles UPDATE policy for disabled accounts (04) would also
-- block consent withdrawal for exactly the people most likely to want it.
-- A second permissive policy cannot carve out one action: RLS restricts
-- rows, not columns, so it would re-open every column. A browser-callable
-- RPC with a fixed body is the carve-out instead.
--
-- WHY WITHDRAWAL-ONLY, AND WHY A STATIC COLUMN LIST
-- -------------------------------------------------
-- The privilege-guard trigger tests `current_user in ('authenticated','anon')`
-- (20260823014034_marketing_consent_record.sql:222), but inside a
-- `security definer` function `current_user` is the owner, so the guard never
-- fires here. The RPC body is therefore the only protection for
-- server-owned columns: it takes no column name, no jsonb patch and no
-- target id, and the `update ... set` below names its columns literally.
-- There is deliberately no way to spell "consent = true" through this
-- function. Withdrawal when consent is already false is a no-op (the
-- trigger's no-op branch restores the metadata from `old`), so this yields
-- at most one meaningful write per account and cannot serve as a
-- write-amplification primitive against a table every request reads.
--
-- WHY NOT GATED ON is_active_account()
-- ------------------------------------
-- A disabled reader withdrawing consent is the entire point of the
-- carve-out. Granting stays on the Flask route beside 02, which refuses
-- disabled accounts at its `_gate`.
--
-- CONTRACT EXEMPTION: browser-callable by design, so exempt from points 3
-- and 4 of the RPC contract (supabase/README.md) like `is_active_account()`
-- and `update_own_preferences(jsonb)` before it. Registered there and in
-- supabase/tests/function_acls.test.sql's `browser_callable` allow-list.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction.
--
-- APPLY NOTE: this file lives in supabase/pending/ (see supabase/README.md).
-- Apply it with apply_migration, read the real version back from
-- list_migrations, then `git mv` it into supabase/migrations/ under that
-- name. It must land BEFORE 03 revokes the direct column grants, and the
-- repointed toggle (static/js/account/handlers.js) must be verified before
-- that revoke.

create function public.update_own_marketing_consent(p_clear_age boolean default false)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_rows integer;
begin
  -- Bound to the caller's own row via auth.uid(), never a passed-in id --
  -- this function is SECURITY DEFINER and would otherwise let any caller
  -- withdraw any account's consent.
  if coalesce(p_clear_age, false) then
    update public.profiles
       set marketing_consent = false,
           age = null
     where id = (select auth.uid());
  else
    update public.profiles
       set marketing_consent = false
     where id = (select auth.uid());
  end if;

  get diagnostics v_rows = row_count;
  if v_rows = 0 then
    raise exception 'no profile row for the current account' using errcode = 'P0002';
  end if;
end;
$$;

revoke execute on function public.update_own_marketing_consent(boolean) from anon, public;
grant execute on function public.update_own_marketing_consent(boolean) to authenticated, service_role;
