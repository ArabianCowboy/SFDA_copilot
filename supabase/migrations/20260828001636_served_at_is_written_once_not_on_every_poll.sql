-- Stop the reader list RPCs writing a dead tuple on every page load.
-- ===========================================================================
-- Plan: docs/database-improvement-plan.md finding 4.
--
-- WHAT WAS WRONG. Both reader list functions open with an upsert whose
-- conflict clause is unconditional:
--
--   on conflict (notification_id, user_id) do update
--     set served_at = coalesce(public.user_notification_reads.served_at,
--                              excluded.served_at);
--
-- The coalesce correctly preserves the first served_at. But DO UPDATE fires
-- regardless, and Postgres does not skip an UPDATE whose new values equal the
-- old ones — only a WHERE predicate on the conflict clause can. So every poll
-- after the first wrote a new row version and left a dead tuple behind, for a
-- column whose value did not change. pg_stat_user_tables already showed the
-- signature from testing alone: n_live_tup 0, n_dead_tup 32.
--
-- Scale it: one active all-targeted banner, R readers, P page loads each per
-- day is R x P dead tuples per day on the smallest and most frequently touched
-- table in the schema, each also a WAL record and index maintenance.
-- Autovacuum keeps up at this size and visibly will not at the size this table
-- is designed for. It would present as "the notification bell got slow".
--
-- TWO SITES, NOT FOUR, AND THE OTHER TWO MUST NOT BE TOUCHED.
-- 20260823202428_reader_notification_rpcs.sql has four `on conflict … do
-- update` clauses. The two changed here are the list RPCs, which set nothing
-- but served_at. The other two — inside notifications_mark_read and
-- notifications_mark_all_read — look identical and are not: they also set
-- read_at, dismissed_at and acknowledged_at. By the time a reader can click
-- anything the list RPC has already inserted their row with served_at set, so
-- a `where served_at is null` predicate there would make every read,
-- dismissal and acknowledgement a permanent no-op and the bell would stop
-- recording entirely. They are also not the problem: they fire on a user
-- action, so their write amplification is one row per actual click.
--
-- WHY THE coalesce GOES AWAY. The WHERE already guarantees the old value was
-- null, so the coalesce it replaces has nothing left to preserve. Semantics
-- are identical: first serve wins, later serves are no-ops.
--
-- WHAT THIS DOES NOT BUY. A false conflict WHERE writes no tuple, but Postgres
-- still takes a row lock while evaluating it. This is a bloat and WAL fix, not
-- a claim that the poll becomes lock-free.
--
-- create or replace, not drop and create: neither argument list nor RETURNS
-- TABLE signature changes, so the ACL carries forward. Both revoke/grant pairs
-- are restated anyway, because a reader checking the contract should not have
-- to go back two migrations to confirm it.

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
    set served_at = excluded.served_at
    where public.user_notification_reads.served_at is null;

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
    set served_at = excluded.served_at
    where public.user_notification_reads.served_at is null;

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
