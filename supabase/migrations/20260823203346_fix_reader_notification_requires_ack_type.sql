-- Bug fix, caught before any caller was written: the previous migration
-- (reader_notification_rpcs) declared requires_ack as `text` with an
-- explicit ::text cast on both reader-facing list RPCs. A JSON boolean
-- serialized as the *string* "false" is truthy in Python
-- (`bool("false") is True`), which would have made every non-modal
-- notification's requires_ack read as true the moment client code checked
-- it. Return-type changes need drop + create (a table-returning function's
-- signature includes its OUT columns), matching supabase/README.md's rule
-- for argument-list changes.

drop function if exists public.notifications_list_active_for_reader(uuid);

create function public.notifications_list_active_for_reader(
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
  requires_ack  boolean,
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
         n.requires_ack, n.created_at, n.expires_at,
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


drop function if exists public.notifications_list_history_for_reader(uuid, timestamptz, uuid, integer);

create function public.notifications_list_history_for_reader(
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
  requires_ack    boolean,
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
         n.requires_ack, n.created_at, n.expires_at, n.deactivated_at,
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
