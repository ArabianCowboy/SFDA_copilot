-- Close the read-after-delete hole the lifecycle check left open.
-- ===========================================================================
-- Plan: docs/database-improvement-plan.md finding 16, narrowing a decision
-- that 20260828001731 got half right.
--
-- WHAT THAT MIGRATION DID. It refused `dismissed` and `acknowledged` once a
-- notification is deleted, deactivated or expired, and deliberately continued
-- to allow plain `read`. The justification was sound as far as it went:
-- marking an item read in a HISTORY list is reasonable long after it stopped
-- being active, and notifications_list_history_for_reader exists to show
-- exactly that.
--
-- WHAT IT MISSED. That argument holds for `deactivated_at` and `expires_at`.
-- It does not hold for `deleted_at`, because the history RPC filters
-- `n.deleted_at is null` (20260828001636) — a soft-deleted notification
-- appears in NO reader surface at all. So a `read` receipt on one can only come
-- from a stale tab or a scripted call, can never be the reader action it
-- purports to record, and still counts: admin_purge_notification reports
-- `count(*) filter (where read_at is not null)` in the audit row it writes
-- before erasing everything (20260828001543).
--
-- The result was that engagement figures on a withdrawn notification could
-- still move between the delete and the purge — a smaller version of exactly
-- the count corruption finding 16 exists to prevent, and one that survives in
-- the permanent audit record.
--
-- So: deleted refuses every action; deactivated and expired keep refusing only
-- the two display actions. The three lifecycle conditions are no longer
-- interchangeable, and the difference is which reader surface can still show
-- the row.
--
-- Verified after applying:
--
--   deleted     + read       -> RN003        deleted     + dismissed -> RN003
--   deactivated + read       -> allowed      deactivated + dismissed -> RN003
--   live        + dismissed  -> allowed
--
-- FOR SHARE is unchanged and still load-bearing — see 20260828001731's header
-- for why the check alone would not close the race against the admin path's
-- FOR UPDATE.
--
-- RN003 already maps to `notification_no_longer_active` in
-- web/services/notification_store.py, so this widens an existing refusal
-- rather than introducing a code Flask cannot translate. The in-memory double
-- mirrors the same split.

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

  -- FOR SHARE, not a bare select: the lock is taken as part of the read so the
  -- lifecycle cannot change between the checks below and the upsert at the end
  -- of this function. It conflicts with the FOR UPDATE the admin deactivate,
  -- delete and purge paths take on the same row.
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

  -- Deleted: no receipts of any kind. The row is in no reader surface, so any
  -- receipt is spurious by construction, and the purge audit row counts it.
  if v_notification.deleted_at is not null then
    raise exception 'this notification is no longer active' using errcode = 'RN003';
  end if;

  -- Deactivated or expired: still visible in history, so `read` stays legal
  -- and only the two live-notice display actions are refused.
  if p_action in ('dismissed', 'acknowledged')
     and (v_notification.deactivated_at is not null
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
  -- clauses that must NOT get the `where served_at is null` predicate
  -- 20260828001636 added to the list RPCs: by the time a reader can click
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
