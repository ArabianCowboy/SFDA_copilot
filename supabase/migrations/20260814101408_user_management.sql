-- Account listing and account changes, with the two guards that stop an
-- operator locking everyone out.
--
-- Both are functions rather than table access, for two reasons. Emails live in
-- `auth.users` and standing lives in `public.profiles`, so a list needs a join
-- across a schema the service role should not be querying ad hoc. And a change
-- has to write its audit row in the SAME transaction as the change — a
-- disable with no record of who did it is precisely the event a record exists
-- for.

-- ---------------------------------------------------------------------------
-- Listing
-- ---------------------------------------------------------------------------
create or replace function public.admin_list_users(
  p_limit  int default 50,
  p_offset int default 0,
  p_search text default null
)
returns table (
  id              uuid,
  email           text,
  role            text,
  tier            text,
  is_disabled     boolean,
  disabled_at     timestamptz,
  disabled_reason text,
  created_at      timestamptz,
  last_sign_in_at timestamptz,
  total           bigint
)
language sql
security definer
set search_path = ''
as $$
  with matched as (
    select u.id, u.email::text as email,
           coalesce(p.role, 'user')      as role,
           coalesce(p.tier, 'free')      as tier,
           coalesce(p.is_disabled, false) as is_disabled,
           p.disabled_at, p.disabled_reason,
           u.created_at, u.last_sign_in_at
    from auth.users u
    left join public.profiles p on p.id = u.id
    where p_search is null
       or p_search = ''
       or u.email::text ilike '%' || p_search || '%'
  )
  select m.*, (select count(*) from matched) as total
  from matched m
  order by m.created_at desc
  limit greatest(least(p_limit, 200), 1)
  offset greatest(p_offset, 0);
$$;

revoke execute on function public.admin_list_users(int, int, text)
  from anon, authenticated, public;

-- ---------------------------------------------------------------------------
-- Changing a role or chat access
-- ---------------------------------------------------------------------------
-- Returns the updated row. Raises with a distinguishable SQLSTATE for the two
-- refusals the application needs to explain differently.
--
--   AD001  an administrator changing their own role or access
--   AD002  a change that would leave no enabled administrator
--
-- Both are guards against the same outcome: an instance nobody can administer.
-- The first is the common accident — demoting yourself while tidying up. The
-- second is the one that looks reasonable at the time, because the account you
-- are disabling belongs to someone who left.
create or replace function public.admin_set_user_flags(
  p_user_id     uuid,
  p_role        text,
  p_is_disabled boolean,
  p_reason      text,
  p_actor_id    uuid,
  p_actor_email text,
  p_request_ip  text default null,
  p_user_agent  text default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_before   jsonb;
  v_after    jsonb;
  v_was_admin boolean;
  v_enabled_admins int;
begin
  if p_actor_id is not null and p_actor_id = p_user_id then
    raise exception 'an administrator cannot change their own role or access'
      using errcode = 'AD001';
  end if;

  select to_jsonb(x) into v_before
  from (
    select role, tier, is_disabled from public.profiles where id = p_user_id
  ) x;

  if v_before is null then
    raise exception 'no profile for %', p_user_id using errcode = 'AD003';
  end if;

  v_was_admin := (v_before ->> 'role') = 'admin'
             and not (v_before ->> 'is_disabled')::boolean;

  -- Would this change remove an enabled administrator, and is it the last one?
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
  set role        = coalesce(p_role, role),
      is_disabled = coalesce(p_is_disabled, is_disabled),
      disabled_at = case
                      when p_is_disabled is true  then now()
                      when p_is_disabled is false then null
                      else disabled_at
                    end,
      disabled_by = case
                      when p_is_disabled is true  then p_actor_id
                      when p_is_disabled is false then null
                      else disabled_by
                    end,
      disabled_reason = case
                      when p_is_disabled is true  then p_reason
                      when p_is_disabled is false then null
                      else disabled_reason
                    end
  where id = p_user_id;

  select to_jsonb(x) into v_after
  from (
    select role, tier, is_disabled from public.profiles where id = p_user_id
  ) x;

  insert into public.audit_log (
    actor_id, actor_email, action, target_type, target_id,
    before, after, request_ip, user_agent, note
  )
  values (
    p_actor_id, p_actor_email,
    case
      when p_is_disabled is true  then 'user.disable'
      when p_is_disabled is false then 'user.enable'
      else 'user.role_change'
    end,
    'user', p_user_id::text,
    v_before, v_after,
    nullif(p_request_ip, '')::inet, p_user_agent, p_reason
  );

  return v_after;
end;
$$;

revoke execute on function public.admin_set_user_flags(uuid, text, boolean, text, uuid, text, text, text)
  from anon, authenticated, public;
