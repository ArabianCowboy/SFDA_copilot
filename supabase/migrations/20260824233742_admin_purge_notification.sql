-- admin_purge_notification: permanent, irreversible erasure of an already
-- soft-deleted notification and its recipient/read-receipt rows. Distinct
-- from admin_delete_notification (soft delete, kept forever by design) —
-- this is the follow-up action an administrator takes at their own
-- discretion once a notification has been sitting Deleted for a while.
--
-- Deliberately NO age/retention enforcement here: the console's own
-- "purge eligible" bulk convenience action filters by a configurable
-- retention-days setting client-side before calling this per id, but this
-- RPC itself only requires the row to already be soft-deleted. An
-- administrator's explicit purge of any Deleted row — however recent — is
-- intentionally never refused for being "too soon"; the operator's own
-- judgment is the gate, not a server-side clock.
--
-- A summary audit_log row is written BEFORE the underlying rows are
-- destroyed, since after this transaction commits there is nothing left
-- for a later query to look up — the same "record before you erase"
-- discipline this codebase already applies elsewhere.

create or replace function public.admin_purge_notification(
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
  v_actor_ok           boolean;
  v_row                public.notifications%rowtype;
  v_recipient_count    integer;
  v_served_count       integer;
  v_read_count         integer;
  v_dismissed_count    integer;
  v_acknowledged_count integer;
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
  if v_row.deleted_at is null then
    raise exception 'this notification must be deleted before it can be purged'
      using errcode = 'AN009';
  end if;

  select count(*) into v_recipient_count
    from public.notification_recipients where notification_id = p_notification_id;

  select
      count(*) filter (where served_at is not null),
      count(*) filter (where read_at is not null),
      count(*) filter (where dismissed_at is not null),
      count(*) filter (where acknowledged_at is not null)
    into v_served_count, v_read_count, v_dismissed_count, v_acknowledged_count
    from public.user_notification_reads where notification_id = p_notification_id;

  insert into public.audit_log (
    actor_id, actor_email, action, target_type, target_id,
    before, after, request_ip, user_agent
  )
  values (
    p_actor_id, p_actor_email, 'notification.purge', 'notification', p_notification_id::text,
    jsonb_build_object(
      'type', v_row.type,
      'severity', v_row.severity,
      'target_kind', v_row.target_kind,
      'target_count', v_row.target_count,
      'created_at', v_row.created_at,
      'deleted_at', v_row.deleted_at,
      'recipient_count', v_recipient_count,
      'served_count', v_served_count,
      'read_count', v_read_count,
      'dismissed_count', v_dismissed_count,
      'acknowledged_count', v_acknowledged_count
    ),
    null,
    nullif(p_request_ip, '')::inet, p_user_agent
  );

  delete from public.user_notification_reads where notification_id = p_notification_id;
  delete from public.notification_recipients where notification_id = p_notification_id;
  delete from public.notifications where id = p_notification_id;

  return jsonb_build_object('id', p_notification_id, 'purged', true);
end;
$$;

revoke execute on function public.admin_purge_notification(uuid, uuid, text, text, text)
  from anon, authenticated, public;
grant execute on function public.admin_purge_notification(uuid, uuid, text, text, text)
  to service_role;
