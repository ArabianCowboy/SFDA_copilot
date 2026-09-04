-- DROP + CREATE, not CREATE OR REPLACE: this function `returns table (...)`, and
-- adding columns changes its return type, which Postgres refuses with 42P13.
-- The same reason 20260828135749 gives. See docs/reader-quota-plan.md §1.7.
drop function if exists public.admin_get_user(uuid);

-- The account-detail read. Gains the tier's bilingual labels, the stored
-- override WITH its window, and today's usage.
--
-- THE OVERRIDE IS READ UNFILTERED, AND THAT IS THE POINT. The claim RPC and
-- get_reader_quota deliberately hide an override that is outside its window,
-- because enforcement must not see it. The console needs the opposite: §5.2 has
-- to render "scheduled, starts 1 October" and "expired on 30 September, now
-- using the tier limit", and it cannot tell either of those from "this account
-- has no override" if the row arrives as null. Worse, the operator's next save
-- would then PUT a null window and silently erase a promotion that had not
-- started yet. So the raw row is returned here, and `effective_daily_limit` is
-- computed separately WITH the window clause -- both truths, side by side.
-- Never collapse them into one field.
create function public.admin_get_user(p_user_id uuid)
returns table (
  id uuid, email text, created_at timestamptz, last_sign_in_at timestamptz,
  email_confirmed_at timestamptz, banned_until timestamptz, has_profile boolean,
  role text, tier text, is_disabled boolean, disabled_at timestamptz,
  disabled_by_email text, disabled_reason text, first_name text, family_name text,
  age smallint, full_name text, organization text, specialization text,
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
    p.disabled_reason, p.first_name, p.family_name, p.age, p.full_name,
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
