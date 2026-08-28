-- Every mutating admin RPC now requires an enabled administrator, and records
-- the email that belongs to them rather than the one it was handed.
-- ===========================================================================
-- Plan: docs/database-improvement-plan.md finding 15.
--
-- WHAT WAS WRONG. All seven mutating admin_* functions guarded on p_actor_id
-- only when it was present:
--
--   if p_actor_id is not null then … check role = 'admin' … end if;
--
-- so `p_actor_id => null` performed the mutation with no authorization check
-- at all and wrote an audit row with a null actor. admin_write_settings did
-- not check even that much — it had no actor block whatsoever. And
-- p_actor_email was never compared against p_actor_id, so a call could pass
-- one administrator's id (passing the check) and any string at all as the
-- email, and audit_log recorded the string.
--
-- This is not a privilege boundary — anyone holding the service key can
-- already do anything. It is the AUDIT LOG's boundary. audit_log is defended
-- by a revoke and an append-only trigger precisely so it can be trusted later;
-- those defend the rows from being rewritten and do nothing about a row that
-- was false when it was written. The practical failure is a future call site —
-- a script, a migration helper, a new route — that omits the actor because the
-- parameter is optional and the function does not complain, producing a
-- privileged mutation attributed to nobody in the table whose job is
-- attribution.
--
-- SEVEN FUNCTIONS, NAMED IN FULL so the count cannot drift again (an earlier
-- draft of the finding said six against its own evidence, and the one it
-- dropped was admin_purge_notification — the permanent-erasure path, where a
-- false actor matters most):
--
--   admin_write_settings          admin_create_notification
--   admin_set_user_flags          admin_deactivate_notification
--   admin_update_profile          admin_delete_notification
--                                 admin_purge_notification
--
-- The other three admin_* functions — admin_get_user, admin_list_users,
-- admin_list_notification_history — are readers, write no audit row, and are
-- not touched.
--
-- ONE GATE, NOT SEVEN COPIES. The check is factored into
-- public.admin_actor_email rather than pasted into each body. Seven copies of
-- the same ten lines is precisely the shape that drifts, and this plan's own
-- history is the argument: the same authorization rule written in seven places
-- is seven places for it to be edited in six. The helper returns the email so
-- that "the actor is valid" and "this is the actor's email" are one fact
-- established once, and it takes the SQLSTATE as a parameter so each family
-- keeps the code its Flask mapping already expects — AD004 for the account
-- functions, AN005 for the notification ones. Changing those would be a
-- second concern.
--
-- p_actor_email STAYS IN EVERY SIGNATURE and stops being trusted. Removing it
-- would be a drop-and-create of seven functions — a destructive change, its
-- own migration under rule 2 — and would buy nothing the ignore does not.
--
-- THE HONEST LIMIT. SQL cannot establish which human held the service key.
-- This refuses an unattributed mutation and guarantees the recorded email
-- belongs to the id that passed the check. That is the whole of the claim.
--
-- SCHEMA BEFORE CODE, AND THE INTERVAL IS USER-VISIBLE HERE. Until Flask ships
-- alongside, put_settings (web/services/admin_store.py) has no try/except at
-- all, so a demoted administrator saving settings would get an unconverted
-- PostgREST exception rather than the intended refusal — and it has three
-- callers (settings_service.py set_signup_enabled and update,
-- notification_store.py set_purge_retention_days), which is the settings page,
-- the registration pause control and the purge-retention control. The Python
-- change ships in the same release. See the plan's finding 15 for the
-- lockstep list, which also covers the four in-memory test doubles that
-- currently wave a null actor through.

-- ---------------------------------------------------------------------------
-- The gate.
-- ---------------------------------------------------------------------------
-- DELIBERATE EXEMPTION FROM POINT 4 OF THE RPC CONTRACT. supabase/README.md
-- says revoke from anon/authenticated/public and grant to service_role. This
-- function is granted to NOBODY, service_role included, and the exemption is
-- registered in that README alongside the other two.
--
-- Why: it is never called over PostgREST. Its only callers are the seven
-- SECURITY DEFINER functions below, which execute as this function's owner
-- (postgres) and therefore need no grant. Granting it to service_role would
-- create a small new capability that does not otherwise exist — resolving any
-- administrator's email address from their uuid, over /rest/v1/rpc/, on a
-- database where service_role holds no access to auth.users at all.
create or replace function public.admin_actor_email(
  p_actor_id uuid,
  p_errcode  text
)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_email text;
begin
  -- Null first and separately, because it is the case the old guard skipped
  -- rather than failed: `if p_actor_id is not null then` made an absent actor
  -- indistinguishable from an authorized one.
  if p_actor_id is null then
    raise exception 'an enabled administrator is required'
      using errcode = p_errcode;
  end if;

  -- The join is what makes the email derived rather than asserted. A row comes
  -- back only for an account that is an administrator and is not disabled, so
  -- one null test covers "no such account", "not an administrator" and
  -- "disabled" — three refusals the caller has no business telling apart.
  select u.email::text
    into v_email
    from public.profiles p
    join auth.users u on u.id = p.id
   where p.id = p_actor_id
     and p.role = 'admin'
     and p.is_disabled = false;

  if v_email is null then
    raise exception 'the acting account is no longer an enabled administrator'
      using errcode = p_errcode;
  end if;

  return v_email;
end;
$$;

comment on function public.admin_actor_email(uuid, text) is
  'Refuse an absent, non-administrator or disabled actor, and return the email '
  'that belongs to the id. Called only from the mutating admin_* SECURITY '
  'DEFINER functions, which execute as this function''s owner; granted to no '
  'role, including service_role.';

revoke execute on function public.admin_actor_email(uuid, text)
  from anon, authenticated, service_role, public;


-- ---------------------------------------------------------------------------
-- 1. admin_write_settings — the one that had no check at all.
-- ---------------------------------------------------------------------------
create or replace function public.admin_write_settings(
  p_settings   jsonb,
  p_actor_id   uuid,
  p_actor_email text,
  p_before     jsonb,
  p_after      jsonb,
  p_request_ip text default null,
  p_user_agent text default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_settings    jsonb;
  v_actor_email text;
begin
  v_actor_email := public.admin_actor_email(p_actor_id, 'AD004');

  insert into public.app_settings (id, settings, updated_at, updated_by)
  values (1, p_settings, now(), p_actor_id)
  on conflict (id) do update
    set settings = excluded.settings,
        updated_at = now(),
        updated_by = excluded.updated_by
  returning settings into v_settings;

  insert into public.audit_log (
    actor_id, actor_email, action, target_type, target_id,
    before, after, request_ip, user_agent
  )
  values (
    p_actor_id, v_actor_email, 'settings.update', 'settings', 'app_settings',
    p_before, p_after,
    nullif(p_request_ip, '')::inet, p_user_agent
  );

  return v_settings;
end;
$$;

revoke execute on function public.admin_write_settings(jsonb, uuid, text, jsonb, jsonb, text, text)
  from anon, authenticated, public;


-- ---------------------------------------------------------------------------
-- 2. admin_set_user_flags — the ordering here is load-bearing.
-- ---------------------------------------------------------------------------
-- The null test moves to the top, before the advisory lock, because it is free
-- and there is no reason to serialise a call that is already refused. The
-- ENABLED-ADMINISTRATOR revalidation stays where 20260814110722 put it —
-- inside the lock — because that is the property that migration exists to
-- provide: an actor demoted by a concurrent transaction must not be able to
-- act on a snapshot taken before the demotion committed.
--
-- The self-change guard (AD001) becomes unconditional. It was written as
-- `p_actor_id is not null and p_actor_id = p_user_id`, which was correct while
-- a null actor was permitted and is now dead weight.
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


-- ---------------------------------------------------------------------------
-- 3. admin_update_profile — same signature, no defaults, per 20260822225415.
-- ---------------------------------------------------------------------------
create or replace function public.admin_update_profile(
  p_user_id             uuid,
  p_first_name          text,
  p_family_name         text,
  p_age                 smallint,
  p_organization        text,
  p_specialization      text,
  p_expected_updated_at timestamptz,
  p_actor_id            uuid,
  p_actor_email         text,
  p_request_ip          text,
  p_user_agent          text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_before      jsonb;
  v_after       jsonb;
  v_actor_email text;
  v_updated_at  timestamptz;
begin
  v_actor_email := public.admin_actor_email(p_actor_id, 'AD004');

  select to_jsonb(t), t.updated_at
    into v_before, v_updated_at
    from (
      select p.first_name, p.family_name, p.full_name, p.age,
             p.organization, p.specialization, p.updated_at
        from public.profiles p
       where p.id = p_user_id
       for update
    ) t;

  if v_before is null then
    raise exception 'no such account' using errcode = 'AD003';
  end if;

  if p_expected_updated_at is not null
     and v_updated_at is distinct from p_expected_updated_at then
    raise exception 'profile changed since it was loaded'
      using errcode = 'AD005';
  end if;

  update public.profiles
     set first_name     = p_first_name,
         family_name    = p_family_name,
         age            = p_age,
         organization   = p_organization,
         specialization = p_specialization
   where id = p_user_id;

  -- on_profile_update remains the sole owner of updated_at.
  select to_jsonb(t)
    into v_after
    from (
      select p.first_name, p.family_name, p.full_name, p.age,
             p.organization, p.specialization
        from public.profiles p
       where p.id = p_user_id
    ) t;

  if v_before - 'updated_at' = v_after then
    return v_after;
  end if;

  insert into public.audit_log (
    actor_id, actor_email, action, target_type, target_id,
    before, after, request_ip, user_agent
  )
  values (
    p_actor_id, v_actor_email, 'user.profile_change',
    'user', p_user_id::text,
    v_before - 'updated_at', v_after,
    nullif(p_request_ip, '')::inet, p_user_agent
  );

  return v_after;
end;
$$;

revoke execute on function public.admin_update_profile(
  uuid, text, text, smallint, text, text,
  timestamptz, uuid, text, text, text
) from anon, authenticated, public;
grant execute on function public.admin_update_profile(
  uuid, text, text, smallint, text, text,
  timestamptz, uuid, text, text, text
) to service_role;


-- ---------------------------------------------------------------------------
-- 4. admin_create_notification.
-- ---------------------------------------------------------------------------
-- notifications.created_by_email is written from the derived address too, not
-- just the audit row: the history console renders that column, so an unchecked
-- string there is the same attribution defect one table over.
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
  v_actor_email := public.admin_actor_email(p_actor_id, 'AN005');

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


-- ---------------------------------------------------------------------------
-- 5. admin_deactivate_notification.
-- ---------------------------------------------------------------------------
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
  v_actor_email text;
  v_row         public.notifications%rowtype;
begin
  v_actor_email := public.admin_actor_email(p_actor_id, 'AN005');

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
    p_actor_id, v_actor_email, 'notification.deactivate', 'notification', p_notification_id::text,
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


-- ---------------------------------------------------------------------------
-- 6. admin_delete_notification.
-- ---------------------------------------------------------------------------
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
  v_actor_email text;
  v_row         public.notifications%rowtype;
begin
  v_actor_email := public.admin_actor_email(p_actor_id, 'AN005');

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
    p_actor_id, v_actor_email, 'notification.delete', 'notification', p_notification_id::text,
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


-- ---------------------------------------------------------------------------
-- 7. admin_purge_notification — the permanent-erasure path.
-- ---------------------------------------------------------------------------
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
  v_actor_email        text;
  v_row                public.notifications%rowtype;
  v_recipient_count    integer;
  v_served_count       integer;
  v_read_count         integer;
  v_dismissed_count    integer;
  v_acknowledged_count integer;
begin
  v_actor_email := public.admin_actor_email(p_actor_id, 'AN005');

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
    p_actor_id, v_actor_email, 'notification.purge', 'notification', p_notification_id::text,
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
