-- Tier CRUD for the console's Tiers tab. See docs/reader-quota-plan.md §1.5.
--
-- NO p_actor_email PARAMETER on any of these. The seven existing admin RPCs
-- still carry one because removing it would have meant a destructive
-- drop-and-create of seven functions (20260828001543's own header says so), and
-- their bodies already discard the argument in favour of admin_actor_email().
-- That compatibility argument cannot apply to a function that has never
-- shipped, and accepting a caller-supplied email would leave an arbitrary
-- address one careless line away from the immutable audit trail. The email is
-- resolved from the id these functions just validated.
--
-- Every mutating function takes pg_advisory_xact_lock(hashtext('sfda.admin_membership'))
-- FIRST and validates the actor INSIDE it, so a concurrent demotion cannot slip
-- between the check and the write. TODO.md records that six of the seven
-- existing RPCs validate without holding anything; this feature adds to the one,
-- not the six.

-- Reader. No lock, no actor mutation, but still service_role-only.
create function public.admin_list_tiers()
returns table (key text, label_en text, label_ar text, daily_message_limit integer,
               ordering integer, member_count bigint, created_at timestamptz, updated_at timestamptz)
language sql security definer set search_path = '' stable as $$
  select t.key, t.label_en, t.label_ar, t.daily_message_limit, t.ordering,
         (select count(*) from public.profiles p where p.tier = t.key),
         t.created_at, t.updated_at
    from public.tiers t
   order by t.ordering, t.key;
$$;

create function public.admin_create_tier(
  p_key text, p_label_en text, p_label_ar text, p_daily_message_limit integer,
  p_ordering integer, p_actor_id uuid,
  p_request_ip text default null, p_user_agent text default null
) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_actor_email text;
  v_after jsonb;
begin
  if p_actor_id is null then
    raise exception 'an enabled administrator is required' using errcode = 'AD004';
  end if;
  perform pg_advisory_xact_lock(hashtext('sfda.admin_membership'));
  v_actor_email := public.admin_actor_email(p_actor_id, 'AD004');

  -- Validated here, not left to the table's CHECK: a 23514 surfacing as a 500 is
  -- not a message an operator can act on. These map to 422/409 in admin_store.
  if p_key is null or p_key !~ '^[a-z][a-z0-9_]{0,31}$' then
    raise exception 'invalid tier key' using errcode = 'TQ008';
  end if;
  if p_daily_message_limit is null or p_daily_message_limit < 0 then
    raise exception 'invalid daily limit' using errcode = 'TQ005';
  end if;
  if p_label_en is null or length(p_label_en) not between 1 and 40
     or p_label_ar is null or length(p_label_ar) not between 1 and 40 then
    raise exception 'invalid labels' using errcode = 'TQ006';
  end if;
  if exists (select 1 from public.tiers where key = p_key) then
    raise exception 'tier already exists' using errcode = 'TQ001';
  end if;

  insert into public.tiers (key, label_en, label_ar, daily_message_limit, ordering)
  values (p_key, p_label_en, p_label_ar, p_daily_message_limit, coalesce(p_ordering, 0));

  select to_jsonb(x) into v_after from (
    select key, label_en, label_ar, daily_message_limit, ordering
      from public.tiers where key = p_key) x;

  insert into public.audit_log (actor_id, actor_email, action, target_type, target_id,
                                before, after, request_ip, user_agent)
  values (p_actor_id, v_actor_email, 'tier.create', 'tier', p_key,
          null, v_after, nullif(p_request_ip, '')::inet, p_user_agent);
  return v_after;
end $$;

create function public.admin_update_tier(
  p_key text, p_label_en text, p_label_ar text, p_daily_message_limit integer,
  p_ordering integer, p_actor_id uuid,
  p_request_ip text default null, p_user_agent text default null
) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_actor_email text;
  v_before jsonb;
  v_after  jsonb;
begin
  if p_actor_id is null then
    raise exception 'an enabled administrator is required' using errcode = 'AD004';
  end if;
  perform pg_advisory_xact_lock(hashtext('sfda.admin_membership'));
  v_actor_email := public.admin_actor_email(p_actor_id, 'AD004');

  if p_daily_message_limit is not null and p_daily_message_limit < 0 then
    raise exception 'invalid daily limit' using errcode = 'TQ005';
  end if;
  if (p_label_en is not null and length(p_label_en) not between 1 and 40)
     or (p_label_ar is not null and length(p_label_ar) not between 1 and 40) then
    raise exception 'invalid labels' using errcode = 'TQ006';
  end if;

  select to_jsonb(x) into v_before from (
    select key, label_en, label_ar, daily_message_limit, ordering
      from public.tiers where key = p_key for update) x;
  if v_before is null then
    raise exception 'no such tier' using errcode = 'TQ002';
  end if;

  -- The key itself is immutable: renaming it would cascade through profiles.tier
  -- and every notification whose target_tier names it. The console offers no rename.
  update public.tiers
     set label_en = coalesce(p_label_en, label_en),
         label_ar = coalesce(p_label_ar, label_ar),
         daily_message_limit = coalesce(p_daily_message_limit, daily_message_limit),
         ordering = coalesce(p_ordering, ordering),
         updated_at = now()
   where key = p_key;

  select to_jsonb(x) into v_after from (
    select key, label_en, label_ar, daily_message_limit, ordering
      from public.tiers where key = p_key) x;

  -- The admin_set_user_flags diff rule: no audit row when nothing changed.
  if v_before is distinct from v_after then
    insert into public.audit_log (actor_id, actor_email, action, target_type, target_id,
                                  before, after, request_ip, user_agent)
    values (p_actor_id, v_actor_email, 'tier.update', 'tier', p_key,
            v_before, v_after, nullif(p_request_ip, '')::inet, p_user_agent);
  end if;
  return v_after;
end $$;

create function public.admin_delete_tier(
  p_key text, p_actor_id uuid,
  p_request_ip text default null, p_user_agent text default null
) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_actor_email text;
  v_before jsonb;
  v_members bigint;
begin
  if p_actor_id is null then
    raise exception 'an enabled administrator is required' using errcode = 'AD004';
  end if;
  perform pg_advisory_xact_lock(hashtext('sfda.admin_membership'));
  v_actor_email := public.admin_actor_email(p_actor_id, 'AD004');

  -- 'free' is structural, not a preference: it is profiles.tier's column default,
  -- the literal inside profiles_guard_privilege_columns, and what handle_new_user
  -- relies on. Deleting it would break signup, not merely a tier.
  if p_key = 'free' then
    raise exception 'the free tier cannot be deleted' using errcode = 'TQ004';
  end if;

  select to_jsonb(x) into v_before from (
    select key, label_en, label_ar, daily_message_limit, ordering
      from public.tiers where key = p_key for update) x;
  if v_before is null then
    raise exception 'no such tier' using errcode = 'TQ002';
  end if;

  -- Refused here with a mapped code so the console never meets the FK's raw
  -- 23503 from `on delete restrict`.
  select count(*) into v_members from public.profiles where tier = p_key;
  if v_members > 0 then
    raise exception 'tier still has % member(s)', v_members using errcode = 'TQ003';
  end if;

  delete from public.tiers where key = p_key;

  insert into public.audit_log (actor_id, actor_email, action, target_type, target_id,
                                before, after, request_ip, user_agent)
  values (p_actor_id, v_actor_email, 'tier.delete', 'tier', p_key,
          v_before, null, nullif(p_request_ip, '')::inet, p_user_agent);
  return v_before;
end $$;

revoke execute on function public.admin_list_tiers() from anon, authenticated, public;
revoke execute on function public.admin_create_tier(text, text, text, integer, integer, uuid, text, text) from anon, authenticated, public;
revoke execute on function public.admin_update_tier(text, text, text, integer, integer, uuid, text, text) from anon, authenticated, public;
revoke execute on function public.admin_delete_tier(text, uuid, text, text) from anon, authenticated, public;
grant execute on function public.admin_list_tiers() to service_role;
grant execute on function public.admin_create_tier(text, text, text, integer, integer, uuid, text, text) to service_role;
grant execute on function public.admin_update_tier(text, text, text, integer, integer, uuid, text, text) to service_role;
grant execute on function public.admin_delete_tier(text, uuid, text, text) to service_role;
