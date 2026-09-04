-- Sets an account's tier and/or its per-account override in ONE call, so the
-- console's Quota section is one Save and one audited transaction.
-- See docs/reader-quota-plan.md §1.6.
--
-- ARGUMENT ORDER IS LOAD-BEARING: PostgreSQL requires every parameter after a
-- defaulted one to also have a default, so the window pair sits AFTER the
-- non-defaulted actor argument. An earlier draft put the defaulted window
-- parameters before p_actor_id and could not have been created at all.
--
-- NO p_actor_email, for the reason 20260903200618_admin_tier_rpcs.sql gives.
--
-- Null semantics are deliberately asymmetric and the route compensates by always
-- sending every key (a partial body would turn "I did not send it" into "clear it"):
--   p_tier null                          -> leave the tier alone
--   p_daily_message_limit_override null  -> CLEAR the override (delete the row)
create function public.admin_set_reader_quota(
  p_user_id uuid, p_tier text, p_daily_message_limit_override integer, p_reason text,
  p_actor_id uuid,
  p_override_starts_at timestamptz default null,
  p_override_expires_at timestamptz default null,
  p_request_ip text default null, p_user_agent text default null
) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_actor_email  text;
  v_tier_before  text;
  v_ov_before    jsonb;
  v_ov_after     jsonb;
  v_effective    integer;
  v_tier_after   text;
begin
  if p_actor_id is null then
    raise exception 'an enabled administrator is required' using errcode = 'AD004';
  end if;
  perform pg_advisory_xact_lock(hashtext('sfda.admin_membership'));
  v_actor_email := public.admin_actor_email(p_actor_id, 'AD004');

  -- TQ005 raised by the function, never left to the table's CHECK: a 23514
  -- surfacing as an unmapped 500 tells an operator nothing.
  if p_daily_message_limit_override is not null and p_daily_message_limit_override < 0 then
    raise exception 'invalid daily limit' using errcode = 'TQ005';
  end if;
  -- TQ007: a window that runs backwards, or one already over at the moment it is
  -- saved, is an operator mistake rather than a state worth storing.
  if p_daily_message_limit_override is not null then
    if p_override_starts_at is not null and p_override_expires_at is not null
       and p_override_expires_at <= p_override_starts_at then
      raise exception 'window ends before it starts' using errcode = 'TQ007';
    end if;
    if p_override_expires_at is not null and p_override_expires_at <= now() then
      raise exception 'window has already expired' using errcode = 'TQ007';
    end if;
  end if;

  select tier into v_tier_before from public.profiles where id = p_user_id for update;
  if v_tier_before is null then
    raise exception 'no profile for %', p_user_id using errcode = 'AD003';
  end if;

  if p_tier is not null and not exists (select 1 from public.tiers where key = p_tier) then
    raise exception 'no such tier' using errcode = 'TQ002';
  end if;

  select to_jsonb(x) into v_ov_before from (
    select daily_message_limit, starts_at, expires_at
      from public.reader_quota_overrides where user_id = p_user_id) x;

  if p_tier is not null and p_tier is distinct from v_tier_before then
    update public.profiles set tier = p_tier where id = p_user_id;
    insert into public.audit_log (actor_id, actor_email, action, target_type, target_id,
                                  before, after, request_ip, user_agent, note)
    values (p_actor_id, v_actor_email, 'user.tier_change', 'user', p_user_id::text,
            jsonb_build_object('tier', v_tier_before),
            jsonb_build_object('tier', p_tier),
            nullif(p_request_ip, '')::inet, p_user_agent, p_reason);
  end if;

  if p_daily_message_limit_override is null then
    delete from public.reader_quota_overrides where user_id = p_user_id;
  else
    insert into public.reader_quota_overrides
      (user_id, daily_message_limit, reason, starts_at, expires_at, set_by, set_at)
    values (p_user_id, p_daily_message_limit_override, p_reason,
            p_override_starts_at, p_override_expires_at, p_actor_id, now())
    on conflict on constraint reader_quota_overrides_pkey do update
      set daily_message_limit = excluded.daily_message_limit,
          reason     = excluded.reason,
          starts_at  = excluded.starts_at,
          expires_at = excluded.expires_at,
          set_by     = excluded.set_by,
          set_at     = excluded.set_at;
  end if;

  select to_jsonb(x) into v_ov_after from (
    select daily_message_limit, starts_at, expires_at
      from public.reader_quota_overrides where user_id = p_user_id) x;

  -- The diff rule: no audit row when nothing actually changed. The WINDOW is part
  -- of the decision, so extending a promotion by a week is as auditable as
  -- changing its number.
  if v_ov_before is distinct from v_ov_after then
    insert into public.audit_log (actor_id, actor_email, action, target_type, target_id,
                                  before, after, request_ip, user_agent, note)
    values (p_actor_id, v_actor_email, 'user.quota_override_change', 'user', p_user_id::text,
            v_ov_before, v_ov_after, nullif(p_request_ip, '')::inet, p_user_agent, p_reason);
  end if;

  -- effective_limit is resolved through the SAME window clause the claim uses, so
  -- an override saved with a future starts_at reports the tier's number and the
  -- console shows what is in force NOW rather than what was just scheduled.
  select coalesce(p.tier, 'free'),
         coalesce(o.daily_message_limit, t.daily_message_limit, f.daily_message_limit)
    into v_tier_after, v_effective
    from (select p_user_id as id) x
    left join public.profiles p on p.id = x.id
    left join public.tiers t on t.key = p.tier
    left join public.tiers f on f.key = 'free'
    left join public.reader_quota_overrides o
           on o.user_id = x.id
          and (o.starts_at  is null or o.starts_at  <= now())
          and (o.expires_at is null or o.expires_at >  now());

  return jsonb_build_object(
    'tier', v_tier_after,
    'override', v_ov_after -> 'daily_message_limit',
    'override_starts_at', v_ov_after -> 'starts_at',
    'override_expires_at', v_ov_after -> 'expires_at',
    'effective_limit', v_effective);
end $$;

revoke execute on function public.admin_set_reader_quota(uuid, text, integer, text, uuid, timestamptz, timestamptz, text, text)
  from anon, authenticated, public;
grant execute on function public.admin_set_reader_quota(uuid, text, integer, text, uuid, timestamptz, timestamptz, text, text)
  to service_role;
