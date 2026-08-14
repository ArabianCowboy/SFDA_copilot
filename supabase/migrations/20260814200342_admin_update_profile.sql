-- Let an operator correct a reader's profile text, and record that they did.
--
-- Separate from admin_set_user_flags rather than a widening of it. That
-- function carries membership invariants — the advisory lock, the last-admin
-- count, AD001/AD002 — and profile text carries none of them; inheriting that
-- machinery would be misleading about what this change can cost. It also takes
-- only the target row lock, so it sits outside any lock cycle with that one.
--
-- Three things this does that admin_set_user_flags does not, and should:
--
--   * The action name comes from the DIFF, not from which fields were sent. A
--     patch that sets a field to the value it already holds records nothing at
--     all — TODO.md files the opposite behaviour as a bug against the other
--     function, and there is no reason to reproduce it here.
--   * The caller's expected `updated_at` is required and checked. A row lock
--     protects execution time, not the minutes an operator spends typing; two
--     people editing the same account would otherwise silently last-write-wins.
--   * The actor is revalidated inside the transaction. The Flask gate authorises
--     at request start, and an operator demoted in between could still write.
--
-- AD005 is new: stale write. AD003/AD004 keep their meanings from the sibling.
create or replace function public.admin_update_profile(
  p_user_id      uuid,
  p_full_name    text,
  p_organization text,
  p_specialization text,
  p_expected_updated_at timestamptz,
  p_actor_id     uuid,
  p_actor_email  text,
  p_request_ip   text,
  p_user_agent   text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_before jsonb;
  v_after  jsonb;
  v_actor_ok boolean;
  v_updated_at timestamptz;
begin
  -- The actor must still be an enabled administrator right now, not merely when
  -- the request was authorised.
  select (pr.role = 'admin' and pr.is_disabled = false)
    into v_actor_ok
    from public.profiles pr
   where pr.id = p_actor_id;

  if p_actor_id is not null and coalesce(v_actor_ok, false) = false then
    raise exception 'actor is no longer an administrator'
      using errcode = 'AD004';
  end if;

  select to_jsonb(t), t.updated_at
    into v_before, v_updated_at
    from (
      select p.full_name, p.organization, p.specialization, p.updated_at
        from public.profiles p
       where p.id = p_user_id
       for update
    ) t;

  if v_before is null then
    raise exception 'no such account' using errcode = 'AD003';
  end if;

  -- Refuse rather than clobber. The client sends back what it was shown; if the
  -- row moved underneath it, somebody else's edit is about to be lost.
  if p_expected_updated_at is not null
     and v_updated_at is distinct from p_expected_updated_at then
    raise exception 'profile changed since it was loaded' using errcode = 'AD005';
  end if;

  update public.profiles
     set full_name      = p_full_name,
         organization   = p_organization,
         specialization = p_specialization
   where id = p_user_id;
  -- `updated_at` is deliberately not set here: the on_profile_update trigger
  -- owns it, exactly as it does for a reader editing their own profile.

  select to_jsonb(t) into v_after
    from (
      select p.full_name, p.organization, p.specialization
        from public.profiles p
       where p.id = p_user_id
    ) t;

  -- Nothing changed means nothing happened. A row saying otherwise is a record
  -- of an event that did not occur, which is worse than no row.
  if v_before - 'updated_at' = v_after then
    return v_after;
  end if;

  insert into public.audit_log (
    actor_id, actor_email, action, target_type, target_id,
    before, after, request_ip, user_agent
  )
  values (
    p_actor_id, p_actor_email, 'user.profile_change',
    'user', p_user_id::text,
    v_before - 'updated_at', v_after,
    nullif(p_request_ip, '')::inet, p_user_agent
  );

  return v_after;
end;
$$;

revoke execute on function public.admin_update_profile(
  uuid, text, text, text, timestamptz, uuid, text, text, text
) from anon, authenticated, public;
grant execute on function public.admin_update_profile(
  uuid, text, text, text, timestamptz, uuid, text, text, text
) to service_role;
