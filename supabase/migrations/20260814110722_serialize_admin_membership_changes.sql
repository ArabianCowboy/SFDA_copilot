-- AD002 was a write-skew race, and a guard against lockout that loses under
-- concurrency is not a guard.
--
-- With enabled administrators A and B: A demotes B while B demotes A. Both
-- transactions count two administrators, both pass the check, both UPDATE
-- different rows, and both commit. Zero administrators remain. Nothing about
-- one gunicorn worker prevents this — eight threads issue eight independent
-- transactions, and the check reads a state neither of them ends up in.
--
-- Reproduced against the live project before this migration, and confirmed
-- closed after it: the two concurrent demotions now end with one succeeding,
-- the other refused AD004, and one enabled administrator remaining.
--
-- The predicate itself is correct sequentially, so it is not rewritten. What it
-- lacked was serialization:
--
--   1. pg_advisory_xact_lock — every change that can alter enabled-admin
--      membership takes the same lock, so those transactions run one at a time.
--      Held to commit; nothing to release by hand.
--   2. The actor is revalidated INSIDE that transaction. The route checks the
--      caller before calling, but the two were separate transactions, so a
--      request admitted a moment before its actor was demoted could still act.
--      That is the same race seen from the other side, and it is what actually
--      catches the second demotion above.
--   3. The target row is locked FOR UPDATE before `before` is captured.
--      Otherwise two concurrent changes to one account can both record the same
--      old state, and the audit chronology says something that did not happen.
--
--   AD004  the acting account is no longer an enabled administrator

create or replace function public.admin_set_user_flags(
  p_user_id uuid, p_role text, p_is_disabled boolean, p_reason text,
  p_actor_id uuid, p_actor_email text,
  p_request_ip text default null, p_user_agent text default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_before jsonb;
  v_after  jsonb;
  v_was_admin boolean;
  v_enabled_admins int;
  v_actor_role text;
  v_actor_disabled boolean;
begin
  if p_actor_id is not null and p_actor_id = p_user_id then
    raise exception 'an administrator cannot change their own role or access'
      using errcode = 'AD001';
  end if;

  perform pg_advisory_xact_lock(hashtext('sfda.admin_membership'));

  if p_actor_id is not null then
    select role, is_disabled into v_actor_role, v_actor_disabled
    from public.profiles where id = p_actor_id;

    if v_actor_role is distinct from 'admin' or coalesce(v_actor_disabled, false) then
      raise exception 'the acting account is no longer an enabled administrator'
        using errcode = 'AD004';
    end if;
  end if;

  select to_jsonb(x) into v_before
  from (
    select role, tier, is_disabled from public.profiles where id = p_user_id for update
  ) x;

  if v_before is null then
    raise exception 'no profile for %', p_user_id using errcode = 'AD003';
  end if;

  v_was_admin := (v_before ->> 'role') = 'admin'
             and not (v_before ->> 'is_disabled')::boolean;

  if v_was_admin
     and ((p_role is not null and p_role <> 'admin') or p_is_disabled is true) then
    select count(*) into v_enabled_admins
    from public.profiles where role = 'admin' and not is_disabled;
    if v_enabled_admins <= 1 then
      raise exception 'this would leave no enabled administrator'
        using errcode = 'AD002';
    end if;
  end if;

  update public.profiles
  set role = coalesce(p_role, role),
      is_disabled = coalesce(p_is_disabled, is_disabled),
      disabled_at = case when p_is_disabled is true then now()
                         when p_is_disabled is false then null
                         else disabled_at end,
      disabled_by = case when p_is_disabled is true then p_actor_id
                         when p_is_disabled is false then null
                         else disabled_by end,
      disabled_reason = case when p_is_disabled is true then p_reason
                             when p_is_disabled is false then null
                             else disabled_reason end
  where id = p_user_id;

  select to_jsonb(x) into v_after
  from (select role, tier, is_disabled from public.profiles where id = p_user_id) x;

  insert into public.audit_log (
    actor_id, actor_email, action, target_type, target_id,
    before, after, request_ip, user_agent, note
  )
  values (
    p_actor_id, p_actor_email,
    case when p_is_disabled is true then 'user.disable'
         when p_is_disabled is false then 'user.enable'
         else 'user.role_change' end,
    'user', p_user_id::text, v_before, v_after,
    nullif(p_request_ip, '')::inet, p_user_agent, p_reason
  );

  return v_after;
end;
$$;

revoke execute on function public.admin_set_user_flags(uuid, text, boolean, text, uuid, text, text, text)
  from anon, authenticated, public;
