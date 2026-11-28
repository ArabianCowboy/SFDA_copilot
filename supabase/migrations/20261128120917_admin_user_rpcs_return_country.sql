-- admin_list_users and admin_get_user return profiles.country; the list filters on it
-- ===========================================================================
-- One concern: the console's two account reads show Country, which
-- 20261127230444_country_on_accounts.sql added to profiles. Until now an admin
-- saw Country only as counts on Overview (accounts_by_country), never on the
-- account it belongs to. Three changes, nothing else:
--
--   * admin_list_users gains `p_country` (an ISO code; NULL = no filter), on
--     the REAL `p.country`, so a profile-less account appears under no
--     country, as it does under no tier.
--   * admin_list_users projects `country` (NULL where unset or no profile).
--   * admin_get_user projects `country`, after `age`.
--
-- The bodies are otherwise byte-for-byte the live definitions, read with
-- pg_get_functiondef on 2026-11-28 and identical to 20260923174827 and
-- 20260903200740.
--
-- ---------------------------------------------------------------------------
-- DESTRUCTIVE: this drops two functions that are live and in use.
-- ---------------------------------------------------------------------------
-- `create or replace` CANNOT be used. Both `returns table (...)`, and a new
-- output column changes the return type (42P13). admin_list_users also gains
-- an argument, and a 4-argument version left standing beside a 5-argument
-- one with a default makes a PostgREST call naming four arguments ambiguous
-- (supabase/README.md, "Changing a function's argument list"). apply_migration
-- wraps the file in one transaction, so there is no instant at which neither
-- version exists. Plain `drop function`, not `if exists`: a missing old
-- version is drift worth stopping on.
--
-- What was checked before dropping:
--   * Callers: SupabaseAdminBackend.list_users and .get_user
--     (web/services/admin_store.py) are the only ones. Flask passes rows
--     through by name, so a new column needs no Flask allow-list change, and
--     p_country is sent only when filtering, so the unfiltered list keeps
--     working against the 4-argument function a rollback would restore.
--     Thaqib does not call either function.
--   * Grants: execute revoked from anon/authenticated/public and granted to
--     service_role, for both. Re-established below; a dropped function does
--     not carry its ACL forward.
--   * Dependents: none. Both are called over PostgREST and from nowhere in SQL.
--   * Rollback: drop both new versions, re-apply 20260923174827's and
--     20260903200740's definitions, restate the same revokes and grants. The
--     console then shows no Country and its filter returns 400 from PostgREST
--     (unknown p_country), so revert the Flask/JS commit first.

drop function public.admin_list_users(int, int, text, text);

create function public.admin_list_users(
  p_limit   int default 50,
  p_offset  int default 0,
  p_search  text default null,
  p_tier    text default null,
  p_country text default null
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
  country         text,
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
           (p.id is not null)            as has_profile,
           p.country
    from auth.users u
    left join public.profiles p on p.id = u.id
    where (p_search is null
       or p_search = ''
       or u.email::text ilike '%' || replace(replace(replace(
            p_search, '\', '\\'), '%', '\%'), '_', '\_') || '%' escape '\')
      and (p_tier is null or p.tier = p_tier)
      and (p_country is null or p.country = p_country)
  )
  select m.*, (select count(*) from matched) as total
  from matched m
  order by m.created_at desc, m.id desc
  limit greatest(least(p_limit, 200), 1)
  offset greatest(p_offset, 0);
$$;

revoke execute on function public.admin_list_users(int, int, text, text, text)
  from anon, authenticated, public;
grant execute on function public.admin_list_users(int, int, text, text, text)
  to service_role;

drop function public.admin_get_user(uuid);

-- The override is read unfiltered on purpose; see 20260903200740's header.
create function public.admin_get_user(p_user_id uuid)
returns table (
  id uuid, email text, created_at timestamptz, last_sign_in_at timestamptz,
  email_confirmed_at timestamptz, banned_until timestamptz, has_profile boolean,
  role text, tier text, is_disabled boolean, disabled_at timestamptz,
  disabled_by_email text, disabled_reason text, first_name text, family_name text,
  age smallint, country text, full_name text, organization text, specialization text,
  last_seen_at timestamptz, updated_at timestamptz, marketing_consent boolean,
  marketing_consent_granted_at timestamptz, marketing_consent_withdrawn_at timestamptz,
  marketing_consent_policy_version text, marketing_consent_language text,
  marketing_consent_surface text, marketing_consent_granted_while_unconfirmed boolean,
  tier_label_en text, tier_label_ar text,
  daily_message_limit_override integer, override_starts_at timestamptz,
  override_expires_at timestamptz, override_reason text,
  effective_daily_limit integer, used_today integer, quota_resets_at timestamptz)
language sql security definer set search_path = '' as $function$
  select
    u.id, u.email::text, u.created_at, u.last_sign_in_at, u.email_confirmed_at,
    u.banned_until, (p.id is not null) as has_profile, p.role, p.tier, p.is_disabled,
    p.disabled_at,
    (select d.email::text from auth.users d where d.id = p.disabled_by),
    p.disabled_reason, p.first_name, p.family_name, p.age, p.country, p.full_name,
    p.organization, p.specialization, pls.last_seen_at, p.updated_at,
    p.marketing_consent, p.marketing_consent_granted_at,
    p.marketing_consent_withdrawn_at, p.marketing_consent_policy_version,
    p.marketing_consent_language, p.marketing_consent_surface,
    p.marketing_consent_granted_while_unconfirmed,
    t.label_en, t.label_ar,
    -- Stored, unfiltered.
    o.daily_message_limit, o.starts_at, o.expires_at, o.reason,
    -- In force right now: the same window clause the claim uses.
    coalesce(
      case when (o.starts_at  is null or o.starts_at  <= now())
            and (o.expires_at is null or o.expires_at >  now())
           then o.daily_message_limit end,
      t.daily_message_limit,
      (select f.daily_message_limit from public.tiers f where f.key = 'free')),
    coalesce(ud.used, 0),
    (((now() at time zone 'Asia/Riyadh')::date + 1)::timestamp at time zone 'Asia/Riyadh')
  from auth.users u
  left join public.profiles p on p.id = u.id
  left join public.profile_last_seen pls on pls.user_id = u.id
  left join public.tiers t on t.key = p.tier
  left join public.reader_quota_overrides o on o.user_id = u.id
  left join public.usage_daily ud
         on ud.user_id = u.id and ud.day = (now() at time zone 'Asia/Riyadh')::date
  where u.id = p_user_id
$function$;

revoke execute on function public.admin_get_user(uuid) from anon, authenticated, public;
grant execute on function public.admin_get_user(uuid) to service_role;
