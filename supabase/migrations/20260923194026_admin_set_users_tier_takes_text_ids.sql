-- admin_set_users_tier takes its ids as text and sorts out the non-uuids itself
-- ===========================================================================
-- Replaces 20260923174838's `p_user_ids uuid[]` with `text[]`. Two review
-- findings on the day it shipped, both caused by deciding "is this a uuid?" in
-- Python and the uuid[] cast in Postgres separately:
--
--   * The two disagree. Python's uuid.UUID() accepts forms Postgres's uuid
--     input rejects (a `urn:uuid:` prefix, a leading `+`, unbalanced braces,
--     non-ASCII digits…). One such id reached the cast as 22P02, which nothing
--     maps, and the whole batch became a 500.
--   * When NO id looked like a uuid, Flask answered "all missing" without
--     calling this function at all, so the actor gate (AD004) and the tier
--     check (TQ002) never ran — a demoted operator or a deleted tier got 200.
--
-- Now every id reaches this function. One that is not a canonical hyphenated
-- uuid (either case) identifies no account and is reported in `missing`,
-- exactly as an unknown uuid is — after the actor, batch and tier checks, so
-- refusals are the same whatever the ids look like. Valid ids are compared
-- case-insensitively, so 'ABC…' and 'abc…' are one account and one move.
--
-- Everything else is 20260923174838 unchanged: the lock, the refusals, the
-- per-move audit row, and never touching reader_quota_overrides.
--
-- DESTRUCTIVE: drops a live function. `create or replace` cannot change an
-- argument type (supabase/README.md), and leaving the uuid[] overload beside a
-- text[] one would make a PostgREST call ambiguous. The only caller is
-- SupabaseAdminBackend.set_users_tier (web/services/admin_store.py), which
-- sends a JSON array of strings either way. Rollback: re-apply 20260923174838
-- after dropping this signature, and restore the Python-side uuid split.

drop function public.admin_set_users_tier(uuid[], text, text, uuid, text, text);

create function public.admin_set_users_tier(
  p_user_ids text[], p_tier text, p_reason text,
  p_actor_id uuid,
  p_request_ip text default null, p_user_agent text default null
) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_actor_email text;
  v_id          uuid;
  v_tier_before text;
  v_moved       uuid[]  := '{}';
  v_missing     text[]  := '{}';
  v_unchanged   integer := 0;
begin
  if p_actor_id is null then
    raise exception 'an enabled administrator is required' using errcode = 'AD004';
  end if;
  perform pg_advisory_xact_lock(hashtext('sfda.admin_membership'));
  v_actor_email := public.admin_actor_email(p_actor_id, 'AD004');

  -- Counted on the RAW array, before dedup, matching the route's own check.
  if p_user_ids is null
     or cardinality(p_user_ids) not between 1 and 200
     or pg_catalog.array_position(p_user_ids, null) is not null then
    raise exception 'between 1 and 200 accounts per move' using errcode = 'TQ009';
  end if;

  if not exists (select 1 from public.tiers where key = p_tier) then
    raise exception 'no such tier' using errcode = 'TQ002';
  end if;

  -- Not a uuid: names no account. Reported as sent, once each.
  select coalesce(array_agg(distinct t.raw order by t.raw), '{}') into v_missing
    from unnest(p_user_ids) as t(raw)
   where t.raw !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

  -- The rest, deduplicated case-insensitively and in id order, so two
  -- overlapping batches would take their row locks in the same order.
  for v_id in
    select distinct pg_catalog.lower(t.raw)::uuid
      from unnest(p_user_ids) as t(raw)
     where t.raw ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
     order by 1
  loop
    select tier into v_tier_before from public.profiles where id = v_id for update;
    if not found then
      v_missing := v_missing || v_id::text;
    elsif v_tier_before = p_tier then
      v_unchanged := v_unchanged + 1;
    else
      update public.profiles set tier = p_tier where id = v_id;
      insert into public.audit_log (actor_id, actor_email, action, target_type, target_id,
                                    before, after, request_ip, user_agent, note)
      values (p_actor_id, v_actor_email, 'user.tier_change', 'user', v_id::text,
              jsonb_build_object('tier', v_tier_before),
              jsonb_build_object('tier', p_tier),
              nullif(p_request_ip, '')::inet, p_user_agent, p_reason);
      v_moved := v_moved || v_id;
    end if;
  end loop;

  return jsonb_build_object(
    'moved_ids', to_jsonb(v_moved),
    'unchanged', v_unchanged,
    'missing', to_jsonb(v_missing));
end $$;

revoke execute on function public.admin_set_users_tier(text[], text, text, uuid, text, text)
  from anon, authenticated, public;
grant execute on function public.admin_set_users_tier(text[], text, text, uuid, text, text)
  to service_role;
