-- Stop the account detail view from certifying an address nobody verified.
--
-- Found while planning admin-triggered email change (TODO.md): GoTrue's
-- `auth.admin.update_user_by_id(..., email_confirm=False)` leaves
-- `auth.users.email_confirmed_at` untouched -- it does NOT clear it. Verified
-- live against the project: a confirmed account whose email was changed this
-- way keeps signing in, but its identity row's `email_verified` is false for
-- the new address. So `email_confirmed_at` alone, which is what
-- `admin_get_user` returned until now, would show a "confirmed" timestamp
-- beside an address nobody ever proved control of -- a stale, misleading
-- signal, not a broken one.
--
-- `email_identity_verified` is the identity-level truth for the CURRENT
-- email specifically (`auth.identities.identity_data->>'email_verified'` for
-- the `provider = 'email'` row), independent of the account-level timestamp.
-- The console should read this to decide whether to badge an address as
-- verified, and can still show `email_confirmed_at` as what it actually is:
-- when the account was first confirmed, not proof the current address was.
--
-- `create or replace` cannot add a column to a function's `returns table`
-- shape, so this drops and recreates rather than layering another migration
-- of decorative-only changes on top.
drop function if exists public.admin_get_user(uuid);

create or replace function public.admin_get_user(p_user_id uuid)
returns table (
  id                     uuid,
  email                  text,
  created_at             timestamptz,
  last_sign_in_at        timestamptz,
  email_confirmed_at     timestamptz,
  email_identity_verified boolean,
  banned_until           timestamptz,
  has_profile            boolean,
  role                   text,
  tier                   text,
  is_disabled            boolean,
  disabled_at            timestamptz,
  disabled_by_email      text,
  disabled_reason        text,
  full_name              text,
  organization           text,
  specialization         text,
  last_seen_at           timestamptz,
  updated_at             timestamptz
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
    -- No email identity at all (rare, but the left join must not turn that
    -- into a false "verified") reads as null, which the console must not
    -- treat as true.
    (select (i.identity_data ->> 'email_verified')::boolean
       from auth.identities i
      where i.user_id = u.id and i.provider = 'email'
      limit 1),
    u.banned_until,
    (p.id is not null) as has_profile,
    p.role,
    p.tier,
    p.is_disabled,
    p.disabled_at,
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

revoke execute on function public.admin_get_user(uuid) from anon, authenticated, public;
grant execute on function public.admin_get_user(uuid) to service_role;
