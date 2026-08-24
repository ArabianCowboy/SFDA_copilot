-- admin_deactivate_notification / admin_delete_notification: two separate
-- functions rather than one with a mode flag — cleaner audit action strings,
-- independently revokable later. Both actor-revalidating, both write an
-- audit row in the same transaction as the mutation. The Realtime
-- invalidation publish for each happens in Python, after the RPC commits
-- (web/services/notification_service.py) — never inside the SQL transaction.

create or replace function public.admin_deactivate_notification(
  p_notification_id uuid,
  p_actor_id         uuid,
  p_actor_email      text,
  p_request_ip       text default null,
  p_user_agent       text default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor_ok boolean;
  v_row      public.notifications%rowtype;
begin
  if p_actor_id is not null then
    select (pr.role = 'admin' and pr.is_disabled = false)
      into v_actor_ok
      from public.profiles pr
     where pr.id = p_actor_id;

    if coalesce(v_actor_ok, false) = false then
      raise exception 'the acting account is no longer an enabled administrator'
        using errcode = 'AN005';
    end if;
  end if;

  select * into v_row from public.notifications where id = p_notification_id for update;

  if v_row.id is null then
    raise exception 'no such notification' using errcode = 'AN006';
  end if;
  if v_row.deleted_at is not null then
    raise exception 'this notification was deleted' using errcode = 'AN008';
  end if;
  if v_row.deactivated_at is not null then
    raise exception 'this notification is already deactivated' using errcode = 'AN007';
  end if;

  update public.notifications
     set deactivated_at = now(), deactivated_by = p_actor_id
   where id = p_notification_id
  returning * into v_row;

  insert into public.audit_log (
    actor_id, actor_email, action, target_type, target_id,
    before, after, request_ip, user_agent
  )
  values (
    p_actor_id, p_actor_email, 'notification.deactivate', 'notification', p_notification_id::text,
    jsonb_build_object('deactivated_at', null), jsonb_build_object('deactivated_at', v_row.deactivated_at),
    nullif(p_request_ip, '')::inet, p_user_agent
  );

  return to_jsonb(v_row);
end;
$$;

revoke execute on function public.admin_deactivate_notification(uuid, uuid, text, text, text)
  from anon, authenticated, public;
grant execute on function public.admin_deactivate_notification(uuid, uuid, text, text, text)
  to service_role;


create or replace function public.admin_delete_notification(
  p_notification_id uuid,
  p_actor_id         uuid,
  p_actor_email      text,
  p_request_ip       text default null,
  p_user_agent       text default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor_ok boolean;
  v_row      public.notifications%rowtype;
begin
  if p_actor_id is not null then
    select (pr.role = 'admin' and pr.is_disabled = false)
      into v_actor_ok
      from public.profiles pr
     where pr.id = p_actor_id;

    if coalesce(v_actor_ok, false) = false then
      raise exception 'the acting account is no longer an enabled administrator'
        using errcode = 'AN005';
    end if;
  end if;

  select * into v_row from public.notifications where id = p_notification_id for update;

  if v_row.id is null then
    raise exception 'no such notification' using errcode = 'AN006';
  end if;
  if v_row.deleted_at is not null then
    raise exception 'this notification was already deleted' using errcode = 'AN008';
  end if;

  -- Soft delete only. Preserves recipient/read history for later audit
  -- review; never a hard DELETE.
  update public.notifications
     set deleted_at = now(), deleted_by = p_actor_id
   where id = p_notification_id
  returning * into v_row;

  insert into public.audit_log (
    actor_id, actor_email, action, target_type, target_id,
    before, after, request_ip, user_agent
  )
  values (
    p_actor_id, p_actor_email, 'notification.delete', 'notification', p_notification_id::text,
    jsonb_build_object('deleted_at', null), jsonb_build_object('deleted_at', v_row.deleted_at),
    nullif(p_request_ip, '')::inet, p_user_agent
  );

  return to_jsonb(v_row);
end;
$$;

revoke execute on function public.admin_delete_notification(uuid, uuid, text, text, text)
  from anon, authenticated, public;
grant execute on function public.admin_delete_notification(uuid, uuid, text, text, text)
  to service_role;
