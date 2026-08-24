-- Small enhancement, same signature (jsonb return needs no drop): tag the
-- returned object with `_replay` so the Flask route can answer 200 for an
-- idempotent repeat and 201 for a genuine first creation, instead of
-- collapsing both to one status code.
create or replace function public.admin_create_notification(
  p_type                text,
  p_severity            text,
  p_title_en            text,
  p_title_ar            text,
  p_body_en             text,
  p_body_ar             text,
  p_target_kind         text,
  p_target_role         text,
  p_target_tier         text,
  p_target_user_id      uuid,
  p_expires_at          timestamptz,
  p_resend_of           uuid,
  p_client_request_id   uuid,
  p_request_payload_hash text,
  p_actor_id            uuid,
  p_actor_email         text,
  p_request_ip          text default null,
  p_user_agent          text default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor_ok       boolean;
  v_existing       jsonb;
  v_existing_hash  text;
  v_requires_ack   boolean;
  v_target_count   integer;
  v_notification   public.notifications%rowtype;
  v_target_disabled boolean;
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

  select to_jsonb(n), n.request_payload_hash
    into v_existing, v_existing_hash
    from public.notifications n
   where n.created_by = p_actor_id
     and n.client_request_id = p_client_request_id;

  if v_existing is not null then
    if v_existing_hash = p_request_payload_hash then
      return v_existing || jsonb_build_object('_replay', true);
    end if;
    raise exception 'a different notification was already sent with this request id'
      using errcode = 'AN001';
  end if;

  v_requires_ack := (p_type = 'modal');

  if p_target_kind = 'user' then
    select (pr.is_disabled = true)
      into v_target_disabled
      from public.profiles pr
     where pr.id = p_target_user_id;

    if v_target_disabled is null then
      raise exception 'no such account' using errcode = 'AN003';
    end if;
    if v_target_disabled then
      raise exception 'the target account is disabled' using errcode = 'AN004';
    end if;
    v_target_count := 1;
  elsif p_target_kind = 'role' then
    select count(*) into v_target_count
      from public.profiles pr
     where pr.role = p_target_role and pr.is_disabled = false;
    if v_target_count = 0 then
      raise exception 'no accounts match this role' using errcode = 'AN002';
    end if;
  elsif p_target_kind = 'tier' then
    select count(*) into v_target_count
      from public.profiles pr
     where pr.tier = p_target_tier and pr.is_disabled = false;
    if v_target_count = 0 then
      raise exception 'no accounts match this tier' using errcode = 'AN002';
    end if;
  else
    select count(*) into v_target_count
      from public.profiles pr
     where pr.is_disabled = false;
  end if;

  insert into public.notifications (
    type, severity, title_en, title_ar, body_en, body_ar,
    target_kind, target_role, target_tier, target_user_id, target_count,
    requires_ack, created_by, created_by_email,
    client_request_id, request_payload_hash, resend_of, expires_at
  )
  values (
    p_type, p_severity, p_title_en, p_title_ar, p_body_en, p_body_ar,
    p_target_kind, p_target_role, p_target_tier, p_target_user_id, v_target_count,
    v_requires_ack, p_actor_id, p_actor_email,
    p_client_request_id, p_request_payload_hash, p_resend_of, p_expires_at
  )
  returning * into v_notification;

  if p_target_kind = 'role' then
    insert into public.notification_recipients (notification_id, user_id)
    select v_notification.id, pr.id
      from public.profiles pr
     where pr.role = p_target_role and pr.is_disabled = false;
  elsif p_target_kind = 'tier' then
    insert into public.notification_recipients (notification_id, user_id)
    select v_notification.id, pr.id
      from public.profiles pr
     where pr.tier = p_target_tier and pr.is_disabled = false;
  elsif p_target_kind = 'user' then
    insert into public.notification_recipients (notification_id, user_id)
    values (v_notification.id, p_target_user_id);
  end if;

  insert into public.audit_log (
    actor_id, actor_email, action, target_type, target_id,
    before, after, request_ip, user_agent
  )
  values (
    p_actor_id, p_actor_email, 'notification.create', 'notification', v_notification.id::text,
    null, to_jsonb(v_notification),
    nullif(p_request_ip, '')::inet, p_user_agent
  );

  return to_jsonb(v_notification) || jsonb_build_object('_replay', false);
end;
$$;

revoke execute on function public.admin_create_notification(
  text, text, text, text, text, text, text, text, text, uuid,
  timestamptz, uuid, uuid, text, uuid, text, text, text
) from anon, authenticated, public;
grant execute on function public.admin_create_notification(
  text, text, text, text, text, text, text, text, text, uuid,
  timestamptz, uuid, uuid, text, uuid, text, text, text
) to service_role;
