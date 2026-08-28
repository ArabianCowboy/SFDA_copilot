-- A dismissal or acknowledgement of a withdrawn notice is refused, not counted.
-- ===========================================================================
-- Plan: docs/database-improvement-plan.md finding 16.
--
-- WHAT WAS WRONG. notifications_list_active_for_reader filters on all three
-- lifecycle conditions — deactivated_at is null, deleted_at is null, and
-- expires_at in the future. The mutation that writes receipts did not.
-- notifications_mark_read checked existence, type and targeting only
-- (20260823202428:201-223), and is reachable by any authenticated reader
-- holding a notification id (web/api/app.py:2957-3020).
--
-- So a stale browser tab, or a scripted call, could acknowledge a modal the
-- operator withdrew an hour ago, and the acknowledgement count went up. For a
-- requires_ack modal — the notification type that exists specifically so
-- somebody can later demonstrate that readers saw something — a count that
-- includes acknowledgements of a retracted notice is worse than no count.
--
-- THE CHECK ALONE WOULD NOT HAVE BEEN ENOUGH, because the read was unlocked.
-- admin_deactivate_notification and admin_delete_notification both take
-- `for update` on the same row (20260823202323:36 and :101), so a reader could
-- observe "active", the administrator could retract and commit, and the reader
-- could then write the acknowledgement — reproducing the exact count
-- corruption this migration exists to prevent, just in a narrower window.
--
-- Hence FOR SHARE on the read. FOR SHARE conflicts with FOR UPDATE and FOR NO
-- KEY UPDATE and is held to the end of the transaction, so the retraction
-- waits behind the receipt or the receipt is refused. FOR KEY SHARE would be
-- too weak: a lifecycle update touches non-key columns and would not conflict
-- with it.
--
-- ONLY dismissed AND acknowledged ARE GATED, and that is a product judgement
-- rather than an oversight. Marking an item read in a *history* list is
-- reasonable long after it stopped being active —
-- notifications_list_history_for_reader exists to show exactly that. Dismissal
-- and acknowledgement are display actions on a live notice and should not
-- survive it.
--
-- RN003 IS NEW AND MUST BE MAPPED IN THE SAME RELEASE. _REFUSAL_CODES in
-- web/services/notification_store.py mapped AN001–AN009, RN001 and RN002.
-- mark_read routes PostgREST errors through _refusal_from, but an unmapped
-- SQLSTATE comes back as a raw exception and web/api/app.py:2985-2998 falls
-- through to `except Exception: … return jsonify(error="mark_read_failed"),
-- 503` — a server-error shape for a deliberate refusal, wrong for the client
-- and misleading in the logs. The Flask mapping ships alongside this.

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

  -- FOR SHARE, not a bare select: see the migration header. The lock is taken
  -- as part of the read so the lifecycle cannot change between the check below
  -- and the upsert at the end of this function.
  select * into v_notification
    from public.notifications
   where id = p_notification_id
   for share;

  if v_notification.id is null then
    raise exception 'no such notification' using errcode = 'AN006';
  end if;

  if p_action = 'dismissed' and v_notification.type not in ('toast', 'banner') then
    raise exception 'dismissed does not apply to this notification type' using errcode = 'RN002';
  end if;
  if p_action = 'acknowledged' and v_notification.type <> 'modal' then
    raise exception 'acknowledged does not apply to this notification type' using errcode = 'RN002';
  end if;

  if p_action in ('dismissed', 'acknowledged')
     and (v_notification.deleted_at is not null
          or v_notification.deactivated_at is not null
          or (v_notification.expires_at is not null
              and v_notification.expires_at <= now())) then
    raise exception 'this notification is no longer active' using errcode = 'RN003';
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
  -- Unconditional DO UPDATE on purpose. This is one of the two conflict
  -- clauses that must NOT get the `where served_at is null` predicate the
  -- previous migration added to the list RPCs: by the time a reader can click
  -- anything, served_at is already set, and the predicate would make every
  -- read, dismissal and acknowledgement a permanent no-op.
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
