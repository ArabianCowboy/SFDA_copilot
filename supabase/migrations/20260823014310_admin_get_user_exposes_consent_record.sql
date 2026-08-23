-- Admin visibility of the consent record (docs/profile-refactor-plan.md
-- Step 6 checklist item "Admin visibility ... of the consent record").
-- Read-only: nothing here makes any of these fields operator-writable --
-- admin_update_profile is untouched, and the guard trigger
-- (20260823014034_marketing_consent_record.sql) still refuses any write to
-- the three server-owned fields from a non-privileged role regardless.
--
-- DROP + CREATE, not CREATE OR REPLACE: Postgres refuses to change a
-- function's return row type in place (42P13).

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
  updated_at         timestamptz,
  marketing_consent                          boolean,
  marketing_consent_granted_at               timestamptz,
  marketing_consent_withdrawn_at             timestamptz,
  marketing_consent_policy_version           text,
  marketing_consent_language                 text,
  marketing_consent_surface                  text,
  marketing_consent_granted_while_unconfirmed boolean
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
    p.updated_at,
    p.marketing_consent,
    p.marketing_consent_granted_at,
    p.marketing_consent_withdrawn_at,
    p.marketing_consent_policy_version,
    p.marketing_consent_language,
    p.marketing_consent_surface,
    p.marketing_consent_granted_while_unconfirmed
  from auth.users u
  left join public.profiles p on p.id = u.id
  where u.id = p_user_id
$$;

revoke execute on function public.admin_get_user(uuid) from anon, authenticated, public;
grant execute on function public.admin_get_user(uuid) to service_role;
