-- Moves a batch of accounts into one tier, and touches nothing else.
-- ===========================================================================
-- See docs/ARCHITECTURE.md#reader-quota (reasoning in
-- docs/archive/2026-09-23_tier-membership.md, "Migration 2"). The People tab's bulk
-- "Move to tier" calls this once per Move.
--
-- WHY NOT admin_set_reader_quota IN A LOOP. That function treats a null
-- p_daily_message_limit_override as "CLEAR the override" and deletes the
-- account's reader_quota_overrides row
-- (20260903200648_admin_set_reader_quota_rpc.sql). A bulk move has no override
-- to send, so reusing it would silently wipe every moved reader's personal
-- allowance. This function NEVER reads or writes reader_quota_overrides; a
-- move changes profiles.tier and the audit log, and nothing else.
--
-- NO p_actor_email, for the reason 20260903200618_admin_tier_rpcs.sql gives:
-- the audit email is resolved from the id admin_actor_email just validated.
--
-- The lock is taken FIRST and the actor validated INSIDE it — the same
-- 'sfda.admin_membership' lock every tier and quota writer takes — so a
-- concurrent demotion cannot slip between the check and the writes.
--
-- Partial results are reported, never aborted on: an id with no profile row
-- goes into `missing`, one already in the tier counts as `unchanged`, and only
-- the rest are written. Each moved account gets its own `user.tier_change`
-- audit row, the same shape admin_set_reader_quota writes, so the console's
-- audit view needs no new action. No row is written for unchanged or missing
-- ids (the diff rule: no audit row when nothing changed).
--
-- Refusals (mapped in web/services/admin_store.py's _REFUSAL_CODES):
--   AD004  absent, non-administrator or disabled actor
--   TQ009  p_user_ids null, empty, over 200 elements, or holding a null
--   TQ002  no such tier
--
-- Returns {moved_ids: [uuid, ...], unchanged: n, missing: [uuid, ...]}. Both
-- arrays are always arrays, never null. The route evicts identity caches for
-- `moved_ids` exactly, which is why the ids and not merely a count come back.
create function public.admin_set_users_tier(
  p_user_ids uuid[], p_tier text, p_reason text,
  p_actor_id uuid,
  p_request_ip text default null, p_user_agent text default null
) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_actor_email text;
  v_id          uuid;
  v_tier_before text;
  v_moved       uuid[]  := '{}';
  v_missing     uuid[]  := '{}';
  v_unchanged   integer := 0;
begin
  if p_actor_id is null then
    raise exception 'an enabled administrator is required' using errcode = 'AD004';
  end if;
  perform pg_advisory_xact_lock(hashtext('sfda.admin_membership'));
  v_actor_email := public.admin_actor_email(p_actor_id, 'AD004');

  -- Counted on the RAW array, before dedup, matching the route's own check.
  -- A null element is refused rather than reported as missing: it would reach
  -- the console as a JSON null in `missing`, which names no account.
  if p_user_ids is null
     or cardinality(p_user_ids) not between 1 and 200
     or pg_catalog.array_position(p_user_ids, null) is not null then
    raise exception 'between 1 and 200 accounts per move' using errcode = 'TQ009';
  end if;

  if not exists (select 1 from public.tiers where key = p_tier) then
    raise exception 'no such tier' using errcode = 'TQ002';
  end if;

  -- Deduplicated, and in id order so two overlapping batches would take their
  -- row locks in the same order (the advisory lock already serialises them;
  -- this keeps it true should that lock ever narrow).
  for v_id in select distinct t.uid from unnest(p_user_ids) as t(uid) order by 1 loop
    select tier into v_tier_before from public.profiles where id = v_id for update;
    if not found then
      v_missing := v_missing || v_id;
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

revoke execute on function public.admin_set_users_tier(uuid[], text, text, uuid, text, text)
  from anon, authenticated, public;
grant execute on function public.admin_set_users_tier(uuid[], text, text, uuid, text, text)
  to service_role;
