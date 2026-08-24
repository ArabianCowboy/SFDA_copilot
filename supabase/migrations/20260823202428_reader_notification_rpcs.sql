-- Reader-facing notification RPCs. Ownership-filtering shape: p_user_id is
-- the first argument, filtered on inside every function — the spirit of
-- this repo's p_owner_id convention for reader-owned data.
--
-- DEVIATION FROM THE ORIGINAL PLAN, recorded rather than silently made: the
-- plan's draft signatures also carried p_role/p_tier. They are dropped here
-- because they turned out to be redundant given the send-time snapshot
-- design already adopted for role/tier/user targeting (see
-- admin_create_notification): eligibility for every non-'all' notification
-- is already fully determined by a public.notification_recipients row
-- captured at send time. A reader is eligible for a notification iff
-- target_kind = 'all' OR a recipients row exists for (notification_id,
-- p_user_id) — role/tier membership at READ time is irrelevant, matching
-- the plan's own accepted cost ("a role/tier broadcast never retroactively
-- reaches someone promoted into that role/tier after send"). Carrying
-- p_role/p_tier through four functions that never reference them would be
-- noise, not fidelity to the plan.

create or replace function public.notifications_list_active_for_reader(
  p_user_id uuid
)
returns table (
  id            uuid,
  type          text,
  severity      text,
  title_en      text,
  title_ar      text,
  body_en       text,
  body_ar       text,
  requires_ack  text,
  created_at    timestamptz,
  expires_at    timestamptz,
  read_at       timestamptz,
  dismissed_at  timestamptz,
  acknowledged_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $$
begin
  -- Every currently-visible, not-yet-dismissed/acknowledged notification
  -- counts as "served" by this response — a network fact, not a rendering
  -- fact (see user_notification_reads.served_at's own comment).
  insert into public.user_notification_reads (notification_id, user_id, served_at)
  select n.id, p_user_id, now()
    from public.notifications n
   where n.deactivated_at is null
     and n.deleted_at is null
     and (n.expires_at is null or n.expires_at > now())
     and (
       n.target_kind = 'all'
       or exists (
         select 1 from public.notification_recipients nr
          where nr.notification_id = n.id and nr.user_id = p_user_id
       )
     )
     and not exists (
       select 1 from public.user_notification_reads r
        where r.notification_id = n.id and r.user_id = p_user_id
          and (r.dismissed_at is not null or r.acknowledged_at is not null)
     )
  on conflict (notification_id, user_id) do update
    set served_at = coalesce(public.user_notification_reads.served_at, excluded.served_at);

  return query
  select n.id, n.type, n.severity, n.title_en, n.title_ar, n.body_en, n.body_ar,
         n.requires_ack::text, n.created_at, n.expires_at,
         r.read_at, r.dismissed_at, r.acknowledged_at
    from public.notifications n
    left join public.user_notification_reads r
      on r.notification_id = n.id and r.user_id = p_user_id
   where n.deactivated_at is null
     and n.deleted_at is null
     and (n.expires_at is null or n.expires_at > now())
     and (
       n.target_kind = 'all'
       or exists (
         select 1 from public.notification_recipients nr
          where nr.notification_id = n.id and nr.user_id = p_user_id
       )
     )
     and r.dismissed_at is null
     and r.acknowledged_at is null
   order by n.created_at desc;
end;
$$;

revoke execute on function public.notifications_list_active_for_reader(uuid)
  from anon, authenticated, public;
grant execute on function public.notifications_list_active_for_reader(uuid)
  to service_role;


-- Cursor/keyset pagination, matching web/api/app.py's existing
-- cursor_updated_at/cursor_id chat-session pattern exactly (this app's real
-- reader-facing precedent — verified directly, not offset/limit).
create or replace function public.notifications_list_history_for_reader(
  p_user_id           uuid,
  p_cursor_created_at timestamptz default null,
  p_cursor_id         uuid default null,
  p_limit             integer default 20
)
returns table (
  id              uuid,
  type            text,
  severity        text,
  title_en        text,
  title_ar        text,
  body_en         text,
  body_ar         text,
  requires_ack    text,
  created_at      timestamptz,
  expires_at      timestamptz,
  deactivated_at  timestamptz,
  read_at         timestamptz,
  dismissed_at    timestamptz,
  acknowledged_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.user_notification_reads (notification_id, user_id, served_at)
  select n.id, p_user_id, now()
    from public.notifications n
   where n.deleted_at is null
     and (
       n.target_kind = 'all'
       or exists (
         select 1 from public.notification_recipients nr
          where nr.notification_id = n.id and nr.user_id = p_user_id
       )
     )
     and (
       p_cursor_created_at is null
       or n.created_at < p_cursor_created_at
       or (n.created_at = p_cursor_created_at and n.id < p_cursor_id)
     )
   order by n.created_at desc, n.id desc
   limit greatest(1, least(coalesce(p_limit, 20), 100))
  on conflict (notification_id, user_id) do update
    set served_at = coalesce(public.user_notification_reads.served_at, excluded.served_at);

  return query
  select n.id, n.type, n.severity, n.title_en, n.title_ar, n.body_en, n.body_ar,
         n.requires_ack::text, n.created_at, n.expires_at, n.deactivated_at,
         r.read_at, r.dismissed_at, r.acknowledged_at
    from public.notifications n
    left join public.user_notification_reads r
      on r.notification_id = n.id and r.user_id = p_user_id
   where n.deleted_at is null
     and (
       n.target_kind = 'all'
       or exists (
         select 1 from public.notification_recipients nr
          where nr.notification_id = n.id and nr.user_id = p_user_id
       )
     )
     and (
       p_cursor_created_at is null
       or n.created_at < p_cursor_created_at
       or (n.created_at = p_cursor_created_at and n.id < p_cursor_id)
     )
   order by n.created_at desc, n.id desc
   limit greatest(1, least(coalesce(p_limit, 20), 100));
end;
$$;

revoke execute on function public.notifications_list_history_for_reader(uuid, timestamptz, uuid, integer)
  from anon, authenticated, public;
grant execute on function public.notifications_list_history_for_reader(uuid, timestamptz, uuid, integer)
  to service_role;


-- notifications_mark_read: verifies recipient eligibility AND validates the
-- action against the notification's type before writing — closes the
-- "fabricate my own receipt for a notification I was never targeted by" gap.
-- dismissed is only valid for toast/banner; acknowledged only for modal;
-- read is valid for any type (inbox item opened).
create or replace function public.notifications_mark_read(
  p_notification_id uuid,
  p_user_id          uuid,
  p_action           text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_notification public.notifications%rowtype;
  v_eligible     boolean;
  v_row          public.user_notification_reads%rowtype;
begin
  if p_action not in ('read', 'dismissed', 'acknowledged') then
    raise exception 'unknown action' using errcode = 'RN002';
  end if;

  select * into v_notification from public.notifications where id = p_notification_id;
  if v_notification.id is null then
    raise exception 'no such notification' using errcode = 'AN006';
  end if;

  if p_action = 'dismissed' and v_notification.type not in ('toast', 'banner') then
    raise exception 'dismissed does not apply to this notification type' using errcode = 'RN002';
  end if;
  if p_action = 'acknowledged' and v_notification.type <> 'modal' then
    raise exception 'acknowledged does not apply to this notification type' using errcode = 'RN002';
  end if;

  select (
    v_notification.target_kind = 'all'
    or exists (
      select 1 from public.notification_recipients nr
       where nr.notification_id = p_notification_id and nr.user_id = p_user_id
    )
  ) into v_eligible;

  if not v_eligible then
    raise exception 'this notification was not targeted to this account' using errcode = 'RN001';
  end if;

  insert into public.user_notification_reads (
    notification_id, user_id, served_at, read_at, dismissed_at, acknowledged_at
  )
  values (
    p_notification_id, p_user_id, now(),
    case when p_action = 'read' then now() else null end,
    case when p_action = 'dismissed' then now() else null end,
    case when p_action = 'acknowledged' then now() else null end
  )
  on conflict (notification_id, user_id) do update
    set served_at       = coalesce(public.user_notification_reads.served_at, excluded.served_at),
        read_at          = coalesce(public.user_notification_reads.read_at, case when p_action = 'read' then now() else public.user_notification_reads.read_at end),
        dismissed_at     = coalesce(public.user_notification_reads.dismissed_at, case when p_action = 'dismissed' then now() else public.user_notification_reads.dismissed_at end),
        acknowledged_at  = coalesce(public.user_notification_reads.acknowledged_at, case when p_action = 'acknowledged' then now() else public.user_notification_reads.acknowledged_at end)
  returning * into v_row;

  return to_jsonb(v_row);
end;
$$;

revoke execute on function public.notifications_mark_read(uuid, uuid, text)
  from anon, authenticated, public;
grant execute on function public.notifications_mark_read(uuid, uuid, text)
  to service_role;


-- notifications_mark_all_read: same eligibility join, one statement, not an
-- N-call loop. Marks read_at (inbox "mark all read") only — never touches
-- dismissed_at/acknowledged_at, which stay per-item, explicit actions.
create or replace function public.notifications_mark_all_read(
  p_user_id uuid
)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_count integer;
begin
  with eligible as (
    select n.id
      from public.notifications n
     where n.deleted_at is null
       and (
         n.target_kind = 'all'
         or exists (
           select 1 from public.notification_recipients nr
            where nr.notification_id = n.id and nr.user_id = p_user_id
         )
       )
  ),
  upserted as (
    insert into public.user_notification_reads (notification_id, user_id, served_at, read_at)
    select e.id, p_user_id, now(), now() from eligible e
    on conflict (notification_id, user_id) do update
      set served_at = coalesce(public.user_notification_reads.served_at, excluded.served_at),
          read_at    = coalesce(public.user_notification_reads.read_at, excluded.read_at)
    returning 1
  )
  select count(*) into v_count from upserted;

  return v_count;
end;
$$;

revoke execute on function public.notifications_mark_all_read(uuid)
  from anon, authenticated, public;
grant execute on function public.notifications_mark_all_read(uuid)
  to service_role;
