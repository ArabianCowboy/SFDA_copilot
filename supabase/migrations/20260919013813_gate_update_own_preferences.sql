-- Gate `update_own_preferences` on an active account. Slice 1 of
-- docs/account-and-trust-plan.md §3-M2b (decision D5).
--
-- WHY THE FUNCTION NEEDS ITS OWN GATE: it is `security definer`, so it
-- bypasses RLS — freezing the profiles UPDATE policy (04) does not reach
-- it, and a disabled account could otherwise still write `theme`,
-- `language` and `search_scope` through the browser-callable RPC. The gate
-- is checked FIRST, before the patch validation, so a disabled caller is
-- refused without its input being examined.
--
-- SAFE FOR SIGNUP: the function already raises P0002 when no profile row
-- exists, so a profile-less caller is refused today regardless — the new
-- gate changes nothing on that path (`is_active_account()` is false with
-- no row, which is the same refusal with a clearer code).
--
-- Otherwise byte-for-byte the function 20260822225239 created: the same
-- allow-list, the same merge, the same P0002 idiom. A `create or replace`
-- does not reset grants, but they are stated explicitly below anyway, in
-- the house style, so the exemption stays visible at the definition.
--
-- CONTRACT EXEMPTION (unchanged): browser-callable by design, exempt from
-- points 3 and 4 of the RPC contract like before.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction.
--
-- APPLY NOTE: this file lives in supabase/pending/ (see supabase/README.md).
-- Apply it with apply_migration, read the real version back from
-- list_migrations, then `git mv` it into supabase/migrations/ under that
-- name.

create or replace function public.update_own_preferences(p_patch jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  -- Widen this list, not the column's shape, as new preferences ship.
  v_allowed_keys text[] := array['theme', 'language', 'search_scope'];
  v_key          text;
  v_result       jsonb;
begin
  if not (select public.is_active_account()) then
    raise exception 'account is disabled' using errcode = '42501';
  end if;

  if p_patch is null or jsonb_typeof(p_patch) <> 'object' then
    raise exception 'preferences patch must be a JSON object' using errcode = '22023';
  end if;

  for v_key in select jsonb_object_keys(p_patch) loop
    if not (v_key = any(v_allowed_keys)) then
      raise exception 'unknown preference key: %', v_key using errcode = '22023';
    end if;
  end loop;

  -- Bound to the caller's own row via auth.uid(), never a passed-in id --
  -- this function is SECURITY DEFINER and would otherwise let any caller
  -- patch any account's preferences.
  update public.profiles
     set preferences = coalesce(preferences, '{}'::jsonb) || p_patch
   where id = (select auth.uid())
  returning preferences into v_result;

  if v_result is null then
    raise exception 'no profile row for the current account' using errcode = 'P0002';
  end if;

  return v_result;
end;
$$;

revoke execute on function public.update_own_preferences(jsonb) from anon, public;
grant execute on function public.update_own_preferences(jsonb) to authenticated, service_role;
