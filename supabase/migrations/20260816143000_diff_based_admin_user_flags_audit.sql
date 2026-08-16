-- Derive the audit action name for admin_set_user_flags from the actual diff
-- between the target row's before-state and after-state, not from the parameters
-- supplied in the request.
--
-- Two bugs fixed:
--
--   1. An empty diff records nothing at all. A patch that sets a field to the
--      value it already holds (e.g. {role: "user", is_disabled: false} on an
--      already-enabled reader) previously wrote an audit row claiming an action
--      occurred. A row recording an event that did not occur is worse than no row.
--   2. A mutation that changes BOTH role and chat access (is_disabled) records
--      two distinct audit rows — one for the role change and one for the disable/
--      enable — rather than picking only one action name and dropping the other.
--      This preserves full attribution, correct localization in Arabic/English,
--      and visibility in both the global Activity tab and the per-account
--      detail activity table.
--
-- Preserves all serialized membership invariants:
--   * pg_advisory_xact_lock on admin membership
--   * Actor revalidation inside the serialized transaction (AD004)
--   * Self-change prohibition (AD001)
--   * Last-admin count guard (AD002)
--   * Row-level locking FOR UPDATE before capturing before-state (AD003)

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

  -- Record audit rows only for fields that actually changed. p_reason is a
  -- general note on the call, not a field reserved for disabling — the route
  -- only *requires* it when p_is_disabled is true (web/api/admin.py), it does
  -- not forbid sending it alongside a role-only change. Attaching it here too
  -- means a caller-supplied reason is never silently dropped.
  if (v_before ->> 'role') is distinct from (v_after ->> 'role') then
    insert into public.audit_log (
      actor_id, actor_email, action, target_type, target_id,
      before, after, request_ip, user_agent, note
    )
    values (
      p_actor_id, p_actor_email, 'user.role_change',
      'user', p_user_id::text,
      jsonb_build_object('role', v_before -> 'role'),
      jsonb_build_object('role', v_after -> 'role'),
      nullif(p_request_ip, '')::inet, p_user_agent, p_reason
    );
  end if;

  if (v_before ->> 'is_disabled')::boolean is distinct from (v_after ->> 'is_disabled')::boolean then
    insert into public.audit_log (
      actor_id, actor_email, action, target_type, target_id,
      before, after, request_ip, user_agent, note
    )
    values (
      p_actor_id, p_actor_email,
      case when (v_after ->> 'is_disabled')::boolean is true then 'user.disable'
           else 'user.enable' end,
      'user', p_user_id::text,
      jsonb_build_object('is_disabled', (v_before -> 'is_disabled')::boolean),
      jsonb_build_object('is_disabled', (v_after -> 'is_disabled')::boolean),
      nullif(p_request_ip, '')::inet, p_user_agent,
      case when (v_after ->> 'is_disabled')::boolean is true then p_reason else null end
    );
  end if;

  return v_after;
end;
$$;

revoke execute on function public.admin_set_user_flags(uuid, text, boolean, text, uuid, text, text, text)
  from anon, authenticated, public;
grant execute on function public.admin_set_user_flags(uuid, text, boolean, text, uuid, text, text, text)
  to service_role;
