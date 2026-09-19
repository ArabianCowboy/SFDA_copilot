-- admin_set_user_flags refuses an ENABLE or a role change on a target with a
-- live deletion saga, while a pure DISABLE goes through. Slice 2a
-- of docs/account-and-trust-plan.md §3-M4 and §6 ("Operator's Enable
-- resurrects a pending deletion"), revised by slice 2d (see WHY).
--
-- WHY. The update below clears the disabled columns unconditionally
-- (disabled_at / disabled_by / disabled_reason set to null whenever
-- p_is_disabled is false). Pending is its own state rather than is_disabled
-- precisely so an operator's Enable cannot resurrect it — but only if this
-- function refuses a pending target's ENABLE outright: any Enable on such a
-- row (even alongside a role change) would write an audit row against an
-- account whose erasure is in flight and invite exactly the resurrection
-- the separate state was built to prevent.
--
-- SLICE 2d REVISION — DISABLE IS ALLOWED, ENABLE AND ROLE CHANGES ARE NOT.
-- As first written this file refused EVERY flag change on a live saga, and
-- slice 2c made `pending` fully usable — so any reader who knew their own
-- password could request deletion and become immune to the operator's
-- Disable, renewably (cancel, re-request, another 30 days). An abusive
-- account could not be stopped. A DISABLE is the operator doing exactly
-- their job and carries no resurrection risk (disabling sets the columns
-- the update below only ever clears on Enable), so a PURE disable —
-- p_is_disabled true with no role change — goes through, while an Enable
-- and any role change are still refused with DL002.
--
-- RESIDUAL CONSEQUENCE, CHECKED, NOT DISCOVERED. A disabled pending reader
-- is refused by `_gate` (`_authenticate_request` answers `account_disabled`
-- for is_disabled before any account view runs — web/api/app.py, and the
-- account blueprint's own `_gate` docstring), so they cannot reach the
-- cancel route either. That is the correct trade — an operator disabling an
-- abusive account must not also hand them a cancel button — but it means a
-- Disable during grace is effectively cancel-proof until an operator
-- re-enables, and the operator should know that before clicking.
--
-- PLACEMENT. After the actor gate and the v_before null check, before the
-- last-administrator guard. Order matters on both sides: the actor must be
-- verified first (an unauthenticated call gets AD004, not DL002), and a
-- nonexistent target must still report AD003 rather than misreporting a
-- pending deletion for an account that does not exist.
--
-- OTHERWISE UNCHANGED from the function 20260828001543 created: the same
-- advisory lock, the same in-lock actor revalidation, the same last-admin
-- guard, the same diff-based audit rows. One surgical addition, marked NEW
-- in place. Same signature, so `create or replace` — not the
-- drop-and-create case. Grants restated explicitly in the house style.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction.
--
-- APPLY NOTE: this file lives in supabase/pending/ (see supabase/README.md).
-- Apply it with apply_migration, read the real version back from
-- list_migrations, then `git mv` it into supabase/migrations/ under that
-- name.

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
  v_actor_email text;
begin
  if p_actor_id is null then
    raise exception 'an enabled administrator is required' using errcode = 'AD004';
  end if;

  if p_actor_id = p_user_id then
    raise exception 'an administrator cannot change their own role or access'
      using errcode = 'AD001';
  end if;

  perform pg_advisory_xact_lock(hashtext('sfda.admin_membership'));

  -- Inside the lock, deliberately.
  v_actor_email := public.admin_actor_email(p_actor_id, 'AD004');

  select to_jsonb(x) into v_before
  from (
    select role, tier, is_disabled from public.profiles where id = p_user_id for update
  ) x;

  if v_before is null then
    raise exception 'no profile for %', p_user_id using errcode = 'AD003';
  end if;

  -- NEW IN THIS MIGRATION, and the ONLY new statement. A target with a live
  -- deletion saga takes no Enable and no role change — an Enable would
  -- otherwise silently resurrect a pending deletion by clearing columns this
  -- function unconditionally resets below. A PURE DISABLE (p_is_disabled true
  -- with no role change) is the operator doing exactly their job — stopping
  -- an abusive account that slice 2c's usable grace would otherwise leave
  -- unstoppable — and carries no resurrection risk, so it goes through. The
  -- operator's path for anything subtler on such an account is the saga's
  -- cancel, never this function.
  if public.account_deletion_is_live(p_user_id)
     and not (p_is_disabled is true and p_role is null) then
    raise exception 'DL002: this account has a live deletion saga and takes no flag change'
      using errcode = 'DL002';
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
      p_actor_id, v_actor_email, 'user.role_change',
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
      p_actor_id, v_actor_email,
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
