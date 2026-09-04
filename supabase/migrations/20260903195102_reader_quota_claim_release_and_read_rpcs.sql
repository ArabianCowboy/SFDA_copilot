drop function if exists public.zz_probe_claim(uuid, integer);

-- The three reader-path functions. See docs/reader-quota-plan.md §2.
--
-- WHY `on conflict on constraint usage_daily_pkey` AND NOT `on conflict (user_id, day)`:
-- this function RETURNS a column named `day`, which makes `day` a PL/pgSQL
-- variable in scope. A bare `day` in the conflict target is then ambiguous and
-- the call fails at RUNTIME with 42702 -- not at create time, because PL/pgSQL
-- defers parsing of embedded SQL until first execution. Verified the hard way:
-- the column-list form created cleanly and threw on the first real call, which
-- in production would have meant a migration that applied and a chat route that
-- broke on its first question. Naming the constraint removes the identifier
-- entirely. Do not "simplify" this back.
create function public.chat_claim_daily_message(p_user_id uuid, p_default_limit integer)
returns table (allowed boolean, used integer, "limit" integer, remaining integer,
               resets_at timestamptz, tier_key text, day date)
language plpgsql security definer set search_path = '' as $$
declare
  v_tz    constant text := 'Asia/Riyadh';  -- owner decision 2026-09-03; the ONLY place the zone is named
  v_day   date;
  v_limit integer;
  v_tier  text;
  v_used  integer;
begin
  v_day := (now() at time zone v_tz)::date;

  -- Resolution, four legs: an IN-WINDOW override, then the account's tier, then
  -- the live `free` row (an account with no profile), then the shipped default
  -- from config (only reachable if `free` itself is gone). The window lives in
  -- the JOIN, not a later filter, so an out-of-window override is invisible to
  -- coalesce rather than merely filtered afterwards.
  select coalesce(o.daily_message_limit, t.daily_message_limit,
                  f.daily_message_limit, p_default_limit),
         coalesce(p.tier, f.key)
    into v_limit, v_tier
    from (select p_user_id as id) x
    left join public.profiles p on p.id = x.id
    left join public.tiers t on t.key = p.tier
    left join public.tiers f on f.key = 'free'
    left join public.reader_quota_overrides o
           on o.user_id = x.id
          and (o.starts_at  is null or o.starts_at  <= now())
          and (o.expires_at is null or o.expires_at >  now());

  if v_tier is null then
    raise warning 'quota: no tier resolved for %; falling back to the shipped default', p_user_id;
  end if;

  -- A zero limit must refuse the FIRST claim of the day too. The INSERT branch of
  -- an upsert has no WHERE clause, so it is guarded here, explicitly.
  if v_limit >= 1 then
    insert into public.usage_daily as u (user_id, day, used)
    values (p_user_id, v_day, 1)
    on conflict on constraint usage_daily_pkey do update
      set used = u.used + 1
      where u.used < v_limit
    returning u.used into v_used;
  end if;

  if v_used is not null then
    return query select true, v_used, v_limit, greatest(0, v_limit - v_used),
                        ((v_day + 1)::timestamp at time zone v_tz), v_tier, v_day;
  else
    select coalesce(u.used, 0) into v_used
      from (select 1) s
      left join public.usage_daily u on u.user_id = p_user_id and u.day = v_day;
    return query select false, v_used, v_limit, 0,
                        ((v_day + 1)::timestamp at time zone v_tz), v_tier, v_day;
  end if;
end $$;

-- The refund. Takes the day the CLAIM returned and never recomputes it: a claim
-- at 23:59:59 whose retrieval fails at 00:00:01 must refund day D, not touch
-- D+1. Deliberately NOT idempotent -- `greatest(0, used - 1)` decrements every
-- call -- because making it so would need a claim identity the day row does not
-- carry. The once-per-request guarantee lives in Python's `released` guard.
create function public.chat_release_daily_message(p_user_id uuid, p_day date)
returns integer
language plpgsql security definer set search_path = '' as $$
declare
  v_used integer;
begin
  update public.usage_daily u
     set used = greatest(0, u.used - 1)
   where u.user_id = p_user_id and u.day = p_day
  returning u.used into v_used;
  return v_used;
end $$;

-- The read. Same resolution and the SAME window clause as the claim, so a read
-- and an enforcement can never disagree about whether an override is in force.
-- Returns no `reason` and no `set_by`: operator notes and operator identities
-- are not the reader's business.
create function public.get_reader_quota(p_user_id uuid, p_default_limit integer)
returns table (used integer, "limit" integer, remaining integer, resets_at timestamptz,
               tier_key text, tier_label_en text, tier_label_ar text,
               override_limit integer, override_expires_at timestamptz)
language plpgsql security definer set search_path = '' as $$
declare
  v_tz constant text := 'Asia/Riyadh';
  v_day date;
begin
  v_day := (now() at time zone v_tz)::date;
  return query
  select coalesce(ud.used, 0),
         coalesce(o.daily_message_limit, t.daily_message_limit, f.daily_message_limit, p_default_limit),
         greatest(0, coalesce(o.daily_message_limit, t.daily_message_limit,
                              f.daily_message_limit, p_default_limit) - coalesce(ud.used, 0)),
         ((v_day + 1)::timestamp at time zone v_tz),
         coalesce(p.tier, f.key),
         coalesce(t.label_en, f.label_en),
         coalesce(t.label_ar, f.label_ar),
         o.daily_message_limit,
         o.expires_at
    from (select p_user_id as id) x
    left join public.profiles p on p.id = x.id
    left join public.tiers t on t.key = p.tier
    left join public.tiers f on f.key = 'free'
    left join public.reader_quota_overrides o
           on o.user_id = x.id
          and (o.starts_at  is null or o.starts_at  <= now())
          and (o.expires_at is null or o.expires_at >  now())
    left join public.usage_daily ud on ud.user_id = x.id and ud.day = v_day;
end $$;

-- supabase/README.md: revoke from every browser-reachable role, grant only to
-- the key Flask holds. 20260828100816 already closes the PUBLIC execute default
-- on new functions; these revokes are the explicit belt-and-braces the README asks for.
revoke execute on function public.chat_claim_daily_message(uuid, integer) from anon, authenticated, public;
revoke execute on function public.chat_release_daily_message(uuid, date)   from anon, authenticated, public;
revoke execute on function public.get_reader_quota(uuid, integer)          from anon, authenticated, public;
grant  execute on function public.chat_claim_daily_message(uuid, integer) to service_role;
grant  execute on function public.chat_release_daily_message(uuid, date)   to service_role;
grant  execute on function public.get_reader_quota(uuid, integer)          to service_role;
