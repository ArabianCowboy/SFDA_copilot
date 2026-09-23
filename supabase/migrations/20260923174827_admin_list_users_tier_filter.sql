-- admin_list_users gains a tier filter and reports whether a profile exists
-- ===========================================================================
-- See docs/ARCHITECTURE.md#reader-quota (reasoning in
-- docs/archive/2026-09-23_tier-membership.md, "Migration 1"). Two changes to the body of
-- 20260817161427, nothing else:
--
--   * `p_tier` filters on the REAL `p.tier`, not the coalesced display value.
--     admin_list_tiers.member_count counts profile rows only
--     (20260903200618_admin_tier_rpcs.sql), so filtering on the coalesced
--     'free' would list profile-less accounts under Free that the Tiers tab
--     does not count. With the real column an orphan appears under no tier
--     filter at all, and the list agrees with the count.
--   * `has_profile` is projected so the console can make an orphan row
--     unselectable: admin_set_users_tier reports such an id as missing, and a
--     checkbox that can only ever produce "not found" is a trap.
--
-- ---------------------------------------------------------------------------
-- DESTRUCTIVE: this drops a function that is live and in use.
-- ---------------------------------------------------------------------------
-- `create or replace` CANNOT be used here (supabase/README.md, "Changing a
-- function's argument list"). Adding `p_tier` changes the signature, so the
-- 3-argument version would stay standing beside the 4-argument one; because
-- `p_tier` has a default, a PostgREST call naming only the original three
-- arguments would match BOTH and fail as ambiguous. The drop and the create
-- are one transaction: `apply_migration` wraps the file, so there is no
-- instant at which neither version exists. Plain `drop function` rather than
-- `if exists`: if the 3-argument version is somehow absent, that is a drift
-- worth stopping on.
--
-- What was checked before dropping:
--   * Callers: `SupabaseAdminBackend.list_users` (web/services/admin_store.py)
--     is the only one. A grep for `admin_list_users` over *.py, *.js and *.sql
--     returns that call, comments, and the two migrations that defined it.
--   * Grants: `execute` revoked from anon/authenticated/public and granted to
--     service_role. Both are re-established below; a dropped function does not
--     carry its ACL forward (precedent 20260821145416_chat_first_turn_title.sql).
--   * Dependents: none. No view, trigger, policy or other function references
--     it — it is called over PostgREST and from nowhere in SQL.
--   * Rollback: drop the 4-argument version and re-apply 20260817161427's
--     definition to recreate the 3-argument form, then restate the same revoke
--     and grant. Flask would then need `p_tier` removed from the payload.

drop function public.admin_list_users(int, int, text);

create function public.admin_list_users(
  p_limit  int default 50,
  p_offset int default 0,
  p_search text default null,
  p_tier   text default null
)
returns table (
  id              uuid,
  email           text,
  role            text,
  tier            text,
  is_disabled     boolean,
  disabled_at     timestamptz,
  disabled_reason text,
  created_at      timestamptz,
  last_sign_in_at timestamptz,
  has_profile     boolean,
  total           bigint
)
language sql
security definer
set search_path = ''
as $$
  with matched as (
    select u.id, u.email::text as email,
           coalesce(p.role, 'user')      as role,
           coalesce(p.tier, 'free')      as tier,
           coalesce(p.is_disabled, false) as is_disabled,
           p.disabled_at, p.disabled_reason,
           u.created_at, u.last_sign_in_at,
           (p.id is not null)            as has_profile
    from auth.users u
    left join public.profiles p on p.id = u.id
    where (p_search is null
       or p_search = ''
       or u.email::text ilike '%' || replace(replace(replace(
            p_search, '\', '\\'), '%', '\%'), '_', '\_') || '%' escape '\')
      and (p_tier is null or p.tier = p_tier)
  )
  select m.*, (select count(*) from matched) as total
  from matched m
  order by m.created_at desc, m.id desc
  limit greatest(least(p_limit, 200), 1)
  offset greatest(p_offset, 0);
$$;

revoke execute on function public.admin_list_users(int, int, text, text)
  from anon, authenticated, public;
grant execute on function public.admin_list_users(int, int, text, text)
  to service_role;
