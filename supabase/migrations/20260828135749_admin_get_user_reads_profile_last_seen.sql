-- Source `last_seen_at` from the new public.profile_last_seen table instead of the
-- dead public.profiles.last_seen_at column -- see docs/data-policy-decisions.md's §4,
-- design piece 3. CREATE OR REPLACE, not DROP + CREATE: the return row *type* is unchanged
-- (still a `last_seen_at timestamptz` column in the same position), only the source
-- expression for that one column changes, so 42P13 does not apply. Body copied
-- verbatim from 20260823014310_admin_get_user_exposes_consent_record.sql with exactly
-- that one column swapped and one `left join` added.
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
    pls.last_seen_at,
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
  left join public.profile_last_seen pls on pls.user_id = u.id
  where u.id = p_user_id
$$;

revoke execute on function public.admin_get_user(uuid) from anon, authenticated, public;
grant execute on function public.admin_get_user(uuid) to service_role;
