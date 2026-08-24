-- admin_create_notification: insert + recipient snapshot + audit row, one
-- transaction (the settings/audit pattern from admin_write_settings).
--
-- Actor-attribution shape (p_actor_id/p_actor_email first, not p_owner_id):
-- this mutates rows the actor does not own, matching admin_update_profile
-- and admin_set_user_flags. Revalidates the actor is still an enabled
-- administrator INSIDE this transaction, the same gap those two functions
-- close (a demotion between the Flask gate and this write must not let a
-- just-demoted account publish).
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

  -- Idempotency: a repeat of the same (actor, client_request_id) returns the
  -- original row if the payload matches, or a conflict if it does not — a
  -- reused/colliding id from a different intent must never silently return
  -- someone else's stale result.
  select to_jsonb(n), n.request_payload_hash
    into v_existing, v_existing_hash
    from public.notifications n
   where n.created_by = p_actor_id
     and n.client_request_id = p_client_request_id;

  if v_existing is not null then
    if v_existing_hash = p_request_payload_hash then
      return v_existing;
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
    -- 'all': delivery stays dynamic (a new signup still sees it), but the
    -- count is still captured now as the metrics denominator.
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

  -- Recipient snapshot: only for role/tier/user targets, excluding disabled
  -- accounts. Not populated for 'all' — its delivery is dynamic, resolved at
  -- read time by the reader RPCs, not enumerated here.
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

  return to_jsonb(v_notification);
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


-- admin_list_notification_history: offset/limit, matching the rest of the
-- admin surface (list_users, list_audit) — only reader-facing history uses
-- cursor pagination (this app's actual reader precedent, web/api/app.py's
-- chat session listing), not admin console pagination.
create or replace function public.admin_list_notification_history(
  p_limit  integer default 20,
  p_offset integer default 0,
  p_status text default 'all'
)
returns table (
  id                uuid,
  type              text,
  severity          text,
  title_en          text,
  title_ar          text,
  body_en           text,
  body_ar           text,
  target_kind       text,
  target_role       text,
  target_tier       text,
  target_user_id    uuid,
  target_count      integer,
  requires_ack      boolean,
  created_by        uuid,
  created_by_email  text,
  resend_of         uuid,
  created_at        timestamptz,
  expires_at        timestamptz,
  deactivated_at    timestamptz,
  deleted_at        timestamptz,
  served_count      bigint,
  read_count        bigint,
  dismissed_count   bigint,
  acknowledged_count bigint,
  total_count       bigint
)
language sql
stable
security definer
set search_path = ''
as $$
  with filtered as (
    select n.*
      from public.notifications n
     where case p_status
             when 'active'      then n.deactivated_at is null and n.deleted_at is null
             when 'deactivated' then n.deactivated_at is not null and n.deleted_at is null
             when 'deleted'     then n.deleted_at is not null
             else true
           end
  ),
  counted as (
    select count(*) as c from filtered
  )
  select
    f.id, f.type, f.severity, f.title_en, f.title_ar, f.body_en, f.body_ar,
    f.target_kind, f.target_role, f.target_tier, f.target_user_id, f.target_count,
    f.requires_ack, f.created_by, f.created_by_email, f.resend_of,
    f.created_at, f.expires_at, f.deactivated_at, f.deleted_at,
    (select count(*) from public.user_notification_reads r where r.notification_id = f.id and r.served_at is not null),
    (select count(*) from public.user_notification_reads r where r.notification_id = f.id and r.read_at is not null),
    (select count(*) from public.user_notification_reads r where r.notification_id = f.id and r.dismissed_at is not null),
    (select count(*) from public.user_notification_reads r where r.notification_id = f.id and r.acknowledged_at is not null),
    counted.c
    from filtered f, counted
   order by f.created_at desc
   limit greatest(1, least(coalesce(p_limit, 20), 100))
   offset greatest(0, coalesce(p_offset, 0));
$$;

revoke execute on function public.admin_list_notification_history(integer, integer, text)
  from anon, authenticated, public;
grant execute on function public.admin_list_notification_history(integer, integer, text)
  to service_role;
