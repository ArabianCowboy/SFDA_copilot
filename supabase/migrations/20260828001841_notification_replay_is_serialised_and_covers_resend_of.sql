-- Two defects in one idempotency mechanism.
-- ===========================================================================
-- Plan: docs/database-improvement-plan.md finding 17.
--
-- 1. THE REPLAY PROBE WAS READ-THEN-INSERT WITH NOTHING SERIALISING IT.
-- admin_create_notification selected any existing row for (created_by,
-- client_request_id) and, finding none, inserted. Two concurrent calls with
-- the same key — a double-click, a retry after a timeout — could both read
-- nothing and both proceed; one won the unique index and the other got 23505.
-- The caller that lost was told "storage error" about a notification that had
-- in fact been created successfully, which is precisely the outcome the replay
-- contract exists to prevent.
--
-- Fixed with a transaction-scoped advisory lock keyed on the actor and the
-- request id, taken before the probe. It serialises only genuine duplicates —
-- two different requests hash to two different keys and never wait on each
-- other — and the unique index stays the final arbiter.
--
-- 2. THE REPLAY COMPARISON DID NOT COVER resend_of. The server-side payload
-- hash inputs stop at expires_at (web/services/notification_store.py:269-281)
-- while p_resend_of is inserted into the row (:297-304). So a retry that
-- changed only resend_of hashed identically, was reported as a replay, and
-- silently kept the original provenance link — making the console's "resent
-- from" history wrong in the one place it is consulted.
--
-- Fixed by comparing resend_of alongside the hash rather than by adding it to
-- the Flask-side hash inputs. Adding it there would also work and is arguably
-- cleaner, but it changes what a hash MEANS across a deploy, so retries in
-- flight at the moment of the deploy would stop matching. The in-function
-- comparison has no such boundary.
--
-- WHY THIS COULD NOT LAND BEFORE THE ACTOR MIGRATION. pg_advisory_xact_lock
-- and hashtextextended are both strict:
--
--   select proname, proisstrict from pg_proc
--    where proname in ('pg_advisory_xact_lock','hashtextextended');
--   -- hashtextextended      | t
--   -- pg_advisory_xact_lock | t
--
-- So with a null p_actor_id, `p_actor_id::text || ':' || …` is null, the hash
-- is null, and pg_advisory_xact_lock(null) returns null HAVING TAKEN NO LOCK.
-- It does not raise. It does not warn. The serialisation this migration exists
-- to add would simply not be there, in exactly the null-actor case. The
-- preceding migration (admin_rpcs_require_an_enabled_actor) removes that case
-- by refusing a null actor outright, which is what makes the concatenated key
-- safe to use here. This ordering constraint is the one in the plan that fails
-- without a symptom.

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
  v_actor_email    text;
  v_existing       jsonb;
  v_existing_hash  text;
  v_requires_ack   boolean;
  v_target_count   integer;
  v_notification   public.notifications%rowtype;
  v_target_disabled boolean;
begin
  -- Establishes that p_actor_id is non-null, which the lock key below depends
  -- on. Do not move the lock above this line.
  v_actor_email := public.admin_actor_email(p_actor_id, 'AN005');

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_actor_id::text || ':' || p_client_request_id::text, 0));

  select to_jsonb(n), n.request_payload_hash
    into v_existing, v_existing_hash
    from public.notifications n
   where n.created_by = p_actor_id
     and n.client_request_id = p_client_request_id;

  if v_existing is not null then
    -- `is not distinct from` rather than `=`: resend_of is null on the great
    -- majority of notifications, and `null = null` would make every ordinary
    -- replay fall through to the AN001 conflict below.
    if v_existing_hash = p_request_payload_hash
       and (v_existing ->> 'resend_of') is not distinct from p_resend_of::text then
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
    v_requires_ack, p_actor_id, v_actor_email,
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
    p_actor_id, v_actor_email, 'notification.create', 'notification', v_notification.id::text,
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
