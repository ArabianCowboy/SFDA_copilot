-- Extend admin_get_user with the identity components the console's edit form
-- must now submit, following the identity cutover
-- (20260822225415_profile_identity_atomic_cutover.sql): full_name is a
-- generated column and cannot be written, so admin_update_profile now takes
-- p_first_name/p_family_name/p_age instead of p_full_name. The detail view
-- has to read them to prefill that form. full_name stays in the return shape
-- too -- it is still a real, readable value, and the console's existing
-- subtitle line reads it (static/js/admin/ui.js:1154).
--
-- DROP + CREATE, not CREATE OR REPLACE: Postgres refuses to change a
-- function's return row type in place (42P13).
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction (20260814005509...sql:35-43).

drop function public.admin_get_user(uuid);

create function public.admin_get_user(p_user_id uuid)
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
  first_name         text,
  family_name        text,
  age                smallint,
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
    (select d.email::text from auth.users d where d.id = p.disabled_by),
    p.disabled_reason,
    p.first_name,
    p.family_name,
    p.age,
    p.full_name,
    p.organization,
    p.specialization,
    p.last_seen_at,
    p.updated_at
  from auth.users u
  left join public.profiles p on p.id = u.id
  where u.id = p_user_id
$$;

revoke execute on function public.admin_get_user(uuid) from anon, authenticated, public;
grant execute on function public.admin_get_user(uuid) to service_role;
