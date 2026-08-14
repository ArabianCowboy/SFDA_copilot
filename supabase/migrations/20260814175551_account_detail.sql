-- One account, in full, for the console's detail view.
--
-- Why a function and not table access: auth.users is unreachable through
-- PostgREST, and public.users was dropped in 20260814024903. The console's
-- service-role client can only see auth.users through a definer function.
--
-- The join is LEFT and the profile columns are NOT coalesced, deliberately.
-- admin_list_users coalesces role/tier/is_disabled to healthy defaults
-- (20260814100500:37-40), so an account with no profile row renders in the
-- People list as a perfectly ordinary reader — which is worse than it being
-- absent, because nothing looks wrong. `has_profile` lets the detail view say
-- what is actually true.
--
-- `updated_at` is returned so a later edit can be refused when it is stale:
-- a row lock protects execution time, not the time an operator spends typing.
create or replace function public.admin_get_user(p_user_id uuid)
returns table (
  id                 uuid,
  email              text,
  created_at         timestamptz,
  last_sign_in_at    timestamptz,
  email_confirmed_at timestamptz,
  banned_until       timestamptz,
  has_profile        boolean,
  role               text,
  tier               text,
  is_disabled        boolean,
  disabled_at        timestamptz,
  disabled_by_email  text,
  disabled_reason    text,
  full_name          text,
  organization       text,
  specialization     text,
  last_seen_at       timestamptz,
  updated_at         timestamptz
)
language sql
security definer
set search_path = ''
as $$
  select
    u.id,
    u.email::text,
    u.created_at,
    u.last_sign_in_at,
    u.email_confirmed_at,
    u.banned_until,
    (p.id is not null) as has_profile,
    p.role,
    p.tier,
    p.is_disabled,
    p.disabled_at,
    -- The operator wants to know WHO, and a uuid is not an answer. Resolved
    -- here rather than client-side so the console never needs a second lookup.
    (select d.email::text from auth.users d where d.id = p.disabled_by),
    p.disabled_reason,
    p.full_name,
    p.organization,
    p.specialization,
    p.last_seen_at,
    p.updated_at
  from auth.users u
  left join public.profiles p on p.id = u.id
  where u.id = p_user_id
$$;

-- Explicit on both sides. A new function receives PUBLIC execute by default, so
-- the revoke is what closes it; the grant is stated rather than inherited so the
-- privilege the console actually relies on is visible in this file.
revoke execute on function public.admin_get_user(uuid) from anon, authenticated, public;
grant execute on function public.admin_get_user(uuid) to service_role;
