-- A small RPC that merges into public.profiles.preferences instead of
-- replacing it, plus an allow-list of the keys it will accept.
--
-- WHY
-- ---
-- Services.updateProfile (services.js:677-684) does
-- upsert({ id, ...updates }, { onConflict: 'id' }), so any caller sending a
-- preferences object REPLACES the whole JSONB column. Today that column holds
-- exactly one key ({"theme": "system"}, seeded by handle_new_user) so nothing
-- is lost yet -- but the moment a second preference exists (language,
-- reduce-motion, search scope), a save from any form that does not carry
-- every key silently deletes the rest. Docs/profile-refactor-plan.md
-- Decision 6 names this the single most load-bearing structural fix in P0.
--
-- This migration only ADDS the RPC -- it does not yet change what the
-- profile-modal save path calls, because the modal is being replaced by
-- /account (Step 3) rather than patched in place. Wiring a caller to this
-- RPC lands with whichever step first introduces a second preference key
-- (Step 3's language/theme controls, Step 4's search-scope default).
--
-- WHY AN ALLOW-LIST, NOT JUST THE SIZE CHECK
-- -------------------------------------------
-- profiles_preferences_size_chk (20260822224844_profile_column_bounds.sql)
-- already bounds total size, but a size bound alone still lets a caller stuff
-- arbitrary keys into a column nothing reads. Rejecting an unknown key here
-- keeps `preferences` to what the product actually defines, and the allow-
-- list is data, not schema, so widening it later needs no migration.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction (20260814005509...sql:35-43).

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
grant execute on function public.update_own_preferences(jsonb) to authenticated;
