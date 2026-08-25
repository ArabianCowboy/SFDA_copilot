-- Fixes a real bug found in live use: notifications.resend_of self-
-- references another row in the same table (set when an admin "resends" a
-- past notification, purely for the history table's own "resent from #..."
-- display — see the original notifications_table.sql comment). Purging a
-- notification that some OTHER notification's resend_of still points to
-- violated notifications_resend_of_fkey with a foreign-key error, since the
-- RPC never accounted for that inbound reference before deleting the row.
--
-- Fix: sever any inbound resend_of pointers to the row being purged before
-- deleting it. This only nulls a provenance pointer, never deletes or
-- otherwise touches the referencing notification itself — purging a
-- resend's *source* must not also erase the resend.

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

  -- Sever inbound "resent from" pointers before the delete, or the FK on
  -- notifications.resend_of rejects the delete outright whenever this row
  -- was ever the source of a resend.
  update public.notifications set resend_of = null where resend_of = p_notification_id;

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
