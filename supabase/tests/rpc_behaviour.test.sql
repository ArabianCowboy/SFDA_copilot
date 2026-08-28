-- What the hardening migrations actually DO, not just what they granted.
-- ===========================================================================
-- The other three files in this directory assert catalogue state — grants,
-- ACLs, policies. That is most of what went wrong in the 2026-08-28 review, and
-- it is not all of it. Six of the twelve migrations changed a FUNCTION BODY,
-- and every one of those was verified once, by hand, by the agent that wrote
-- it. A manual verification is not a test: it proves the code was right that
-- afternoon and protects nothing afterwards.
--
-- This file is those verifications, made repeatable. It exercises the RPCs for
-- real — inserting notifications, calling functions, reading back what landed —
-- and rolls all of it back through the closing `raise`.
--
-- **THIS FILE WRITES ROWS AND CALLS MUTATING RPCs.** It is safe only because
-- the whole `do` block aborts. Do not remove the trailing raise, and do not
-- split it into statements that commit.
--
-- Run: paste into execute_sql. Read the word after P0001 — PASS or FAIL.
-- See supabase/tests/README.md.

do $$
declare
  n int := 0;
  summary text;

  -- Two enabled administrators and one ordinary reader. Two admins is required,
  -- not incidental: the actor gate refuses a self-target, so a demotion test
  -- needs a second one to act as.
  admin_a uuid;
  admin_b uuid;
  reader  uuid;

  nid_live uuid; nid_deact uuid; nid_del uuid; nid_expired uuid; nid_modal uuid;
  req uuid := gen_random_uuid();
  sess uuid := gen_random_uuid();
  -- A SECOND session for the clamp check. Sharing one would make
  -- `content like 'q%'` match the one-character question of the turn above.
  sess_len uuid := gen_random_uuid();

  r text; upd_before bigint; upd_after bigint;
  a jsonb; b jsonb;
  kept text; qlen int; alen int;
  ts timestamptz; ts3 timestamptz;
  -- Captured once. now() is transaction-stable — every call to it inside this
  -- one `do` block returns the identical value — which the profile_last_seen
  -- assertions below rely on twice: to prove a write landed at exactly the
  -- right instant (not merely "later than before"), and, combined with
  -- pg_stat_xact_user_tables, to prove a *second* touch performed no write at
  -- all rather than merely writing the same-looking value again.
  tx_now timestamptz;
begin
  tx_now := now();
  select id into admin_a from public.profiles where role = 'admin' and not is_disabled order by id limit 1;
  select id into admin_b from public.profiles where role = 'admin' and not is_disabled and id <> admin_a order by id limit 1;
  select id into reader  from public.profiles where role <> 'admin' and not is_disabled order by id limit 1;

  n := n + 1;
  if admin_a is null or admin_b is null or reader is null then
    raise exception 'FAIL rpc_behaviour — needs two enabled administrators and one enabled '
      'reader; found admin_a=%, admin_b=%, reader=%', admin_a, admin_b, reader;
  end if;

  -- ── The actor gate (20260828001543) ──────────────────────────────────────
  -- A null actor is the case the old `if p_actor_id is not null then` guard
  -- skipped rather than failed, so it is the one that most needs pinning.
  n := n + 1;
  r := 'ACCEPTED';
  begin
    perform public.admin_write_settings('{}'::jsonb, null, 'forged@example.com', null, null, null, null);
  exception when others then r := sqlstate; end;
  if r <> 'AD004' then
    raise exception 'FAIL rpc_behaviour — a NULL actor writing settings gave % (want AD004); '
      'the mutation is unauthorized and the audit row would name nobody', r;
  end if;

  n := n + 1;
  r := 'ACCEPTED';
  begin
    perform public.admin_deactivate_notification(gen_random_uuid(), null, 'forged@example.com');
  exception when others then r := sqlstate; end;
  if r <> 'AN005' then
    raise exception 'FAIL rpc_behaviour — a NULL actor on the notification family gave % '
      '(want AN005)', r;
  end if;

  n := n + 1;
  r := 'ACCEPTED';
  begin
    perform public.admin_write_settings('{}'::jsonb, reader, 'forged@example.com', null, null, null, null);
  exception when others then r := sqlstate; end;
  if r <> 'AD004' then
    raise exception 'FAIL rpc_behaviour — a non-administrator actor gave % (want AD004)', r;
  end if;

  -- The audit email must be DERIVED, never the string the caller supplied.
  n := n + 1;
  perform public.admin_write_settings(
    (select settings from public.app_settings where id = 1),
    admin_a, 'forged@example.com', null, null, null, null);
  select actor_email into r from public.audit_log order by id desc limit 1;
  if r = 'forged@example.com' then
    raise exception 'FAIL rpc_behaviour — audit_log recorded the caller-supplied email; '
      'p_actor_email is meant to be ignored in favour of the id''s real address';
  end if;
  if r is null then
    raise exception 'FAIL rpc_behaviour — audit_log recorded a null actor_email';
  end if;

  -- ── served_at is written once, not per poll (20260828001636) ─────────────
  insert into public.notifications (type, severity, title_en, title_ar, body_en, body_ar,
      target_kind, target_count, requires_ack, created_by, created_by_email,
      client_request_id, request_payload_hash)
    values ('banner','info','t','ت','b','ب','all',1,false,admin_a,'a@b.c',gen_random_uuid(),'h-live')
    returning id into nid_live;

  perform count(*) from public.notifications_list_active_for_reader(reader);
  select n_tup_upd into upd_before from pg_stat_xact_user_tables where relname = 'user_notification_reads';
  perform count(*) from public.notifications_list_active_for_reader(reader);
  perform count(*) from public.notifications_list_history_for_reader(reader);
  select n_tup_upd into upd_after from pg_stat_xact_user_tables where relname = 'user_notification_reads';

  n := n + 1;
  if coalesce(upd_after, 0) <> coalesce(upd_before, 0) then
    raise exception 'FAIL rpc_behaviour — repeat list calls updated % row versions; the '
      '`where served_at is null` predicate is missing and every poll bloats the table',
      coalesce(upd_after,0) - coalesce(upd_before,0);
  end if;

  -- …and the other two conflict sites must STILL WORK. A green bloat number
  -- with a bell that no longer records anything is the worse outcome, and it is
  -- what applying the predicate to all four sites would have produced.
  n := n + 1;
  perform public.notifications_mark_read(nid_live, reader, 'read');
  select read_at into ts from public.user_notification_reads
   where notification_id = nid_live and user_id = reader;
  if ts is null then
    raise exception 'FAIL rpc_behaviour — mark_read recorded no read_at; the served-at '
      'predicate has been applied to a site it must not touch';
  end if;

  n := n + 1;
  perform public.notifications_mark_read(nid_live, reader, 'dismissed');
  select dismissed_at into ts from public.user_notification_reads
   where notification_id = nid_live and user_id = reader;
  if ts is null then
    raise exception 'FAIL rpc_behaviour — mark_read recorded no dismissed_at';
  end if;

  -- ── The receipt lifecycle matrix (20260828001731 + 20260828101339) ───────
  insert into public.notifications (type, severity, title_en, title_ar, body_en, body_ar,
      target_kind, target_count, requires_ack, created_by, created_by_email,
      client_request_id, request_payload_hash, deactivated_at)
    values ('modal','info','t','ت','b','ب','all',1,true,admin_a,'a@b.c',gen_random_uuid(),'h-deact',now())
    returning id into nid_deact;
  insert into public.notifications (type, severity, title_en, title_ar, body_en, body_ar,
      target_kind, target_count, requires_ack, created_by, created_by_email,
      client_request_id, request_payload_hash, deleted_at)
    values ('banner','info','t','ت','b','ب','all',1,false,admin_a,'a@b.c',gen_random_uuid(),'h-del',now())
    returning id into nid_del;
  insert into public.notifications (type, severity, title_en, title_ar, body_en, body_ar,
      target_kind, target_count, requires_ack, created_by, created_by_email,
      client_request_id, request_payload_hash, created_at, expires_at)
    values ('banner','info','t','ت','b','ب','all',1,false,admin_a,'a@b.c',gen_random_uuid(),'h-exp',
            now() - interval '2 hours', now() - interval '1 hour')
    returning id into nid_expired;

  -- Deactivated: `read` allowed (history still shows it), display actions refused.
  n := n + 1;
  perform public.notifications_mark_read(nid_deact, reader, 'read');

  n := n + 1;
  r := 'ACCEPTED';
  begin perform public.notifications_mark_read(nid_deact, reader, 'acknowledged');
  exception when others then r := sqlstate; end;
  if r <> 'RN003' then
    raise exception 'FAIL rpc_behaviour — acknowledging a DEACTIVATED modal gave % (want '
      'RN003); a retracted modal can still accrue acknowledgements', r;
  end if;

  n := n + 1;
  r := 'ACCEPTED';
  begin perform public.notifications_mark_read(nid_expired, reader, 'dismissed');
  exception when others then r := sqlstate; end;
  if r <> 'RN003' then
    raise exception 'FAIL rpc_behaviour — dismissing an EXPIRED banner gave % (want RN003)', r;
  end if;

  -- Deleted: everything refused, `read` included. The history RPC filters
  -- deleted rows, so a read receipt there is unreachable through any reader
  -- surface — and still counts in the purge audit row.
  n := n + 1;
  r := 'ACCEPTED';
  begin perform public.notifications_mark_read(nid_del, reader, 'read');
  exception when others then r := sqlstate; end;
  if r <> 'RN003' then
    raise exception 'FAIL rpc_behaviour — reading a DELETED notification gave % (want '
      'RN003); engagement counts can move after withdrawal', r;
  end if;

  -- ── Replay serialisation and resend_of (20260828001841) ──────────────────
  a := public.admin_create_notification('banner','info','t','ت','b','ب','all',null,null,null,
         null, null, req, 'hash-A', admin_a, 'x@y.z', null, null);
  b := public.admin_create_notification('banner','info','t','ت','b','ب','all',null,null,null,
         null, null, req, 'hash-A', admin_a, 'x@y.z', null, null);

  n := n + 1;
  if (a ->> '_replay') <> 'false' or (b ->> '_replay') <> 'true' then
    raise exception 'FAIL rpc_behaviour — replay reporting is wrong: first=%, second=%',
      a ->> '_replay', b ->> '_replay';
  end if;

  -- Same hash, different resend_of: NOT a replay. The Flask-side payload hash
  -- stops at expires_at and never covered resend_of, so without the extra
  -- comparison this returns the original row and the console's "resent from"
  -- provenance is silently wrong.
  n := n + 1;
  r := 'ACCEPTED';
  begin
    perform public.admin_create_notification('banner','info','t','ت','b','ب','all',null,null,null,
      null, nid_live, req, 'hash-A', admin_a, 'x@y.z', null, null);
  exception when others then r := sqlstate; end;
  if r <> 'AN001' then
    raise exception 'FAIL rpc_behaviour — a retry differing only in resend_of gave % (want '
      'AN001); it was accepted as a replay and the provenance link was dropped', r;
  end if;

  -- ── Source-element normalisation (20260828002052) ────────────────────────
  -- The payload that used to abort the whole turn AFTER the reader had already
  -- been streamed the answer.
  perform public.chat_append_turn(
    reader, sess, gen_random_uuid(), 'q', 'a',
    jsonb_build_array(
      null::jsonb,
      '"scalar"'::jsonb,
      42::text::jsonb,
      jsonb_build_object('source_index','not-a-number','document','x'),
      jsonb_build_object('source_index',0,'document','below-range'),
      jsonb_build_object('source_index',100,'document','above-range'),
      jsonb_build_object('source_index',1,'document','FIRST','page','not-an-int',
                         'score','nan-ish','snippet', repeat('z', 900), 'cited','maybe'),
      jsonb_build_object('source_index',1,'document','DUPLICATE-MUST-LOSE'),
      jsonb_build_object('source_index',2,'document','GOOD','page',7,'score',0.5,'cited',true)
    ),
    'en','g','m','r', null, null, true, 'title', true);

  select string_agg(s.source_index || ':' || s.document || ':' || char_length(s.snippet),
                    ' | ' order by s.source_index)
    into kept
    from public.chat_message_sources s
    join public.chat_messages m on m.id = s.message_id
   where m.session_id = sess;

  n := n + 1;
  -- '1:FIRST:321' — the 900-character snippet clamped to the column's own CHECK
  -- limit, and the later duplicate at index 1 discarded rather than allowed to
  -- overwrite the citation the reader was shown.
  -- '2:GOOD:0'    — that element carries no `snippet` key at all, so it
  --                 normalises to the empty string. NOT NULL is satisfied and
  --                 the row survives, which is the property being pinned.
  if kept is distinct from '1:FIRST:321 | 2:GOOD:0' then
    raise exception 'FAIL rpc_behaviour — source normalisation produced [%]; expected '
      '[1:FIRST:321 | 2:GOOD:0] — two valid rows, first duplicate winning, snippet '
      'clamped to 321, and a missing snippet normalised rather than aborting the turn', kept;
  end if;

  -- ── The question clamp, and the answer left alone (20260828002253) ───────
  perform public.chat_append_turn(
    reader, sess_len, gen_random_uuid(), repeat('q', 12000), repeat('a', 30000),
    '[]'::jsonb, 'en','g','m','r', null, null, true, 't', true);

  select char_length(content) into qlen from public.chat_messages
   where session_id = sess_len and role = 'user';
  select char_length(content) into alen from public.chat_messages
   where session_id = sess_len and role = 'assistant';

  n := n + 1;
  if qlen <> 8000 then
    raise exception 'FAIL rpc_behaviour — a 12,000-character question stored as %; the '
      'clamp is missing and the CHECK would abort the turn instead', qlen;
  end if;

  n := n + 1;
  if alen <> 30000 then
    raise exception 'FAIL rpc_behaviour — a 30,000-character answer stored as %; the answer '
      'must NOT be clamped — truncating it makes durable history disagree with what the '
      'reader was streamed', alen;
  end if;

  -- ── touch_last_seen's throttle, and admin_get_user's new left join
  -- (20260828135721 / 20260828135732 / 20260828135749) ─────────────────────
  -- Cleared first rather than assumed empty: `reader` is a live account, and
  -- this feature may already have touched it in production. Deterministic
  -- regardless, because the whole block rolls back — the same convention
  -- every other assertion in this file already uses against admin_a/admin_b/
  -- reader, not a seeded fixture unique to this feature.
  delete from public.profile_last_seen where user_id = reader;

  n := n + 1;
  perform public.touch_last_seen(reader);
  select last_seen_at into ts from public.profile_last_seen where user_id = reader;
  -- Exact equality to tx_now, not merely "not null": now() is transaction-
  -- stable, so this is a real assertion about what got written, not a weaker
  -- "something happened" check.
  if ts is distinct from tx_now then
    raise exception 'FAIL rpc_behaviour — touch_last_seen on a first touch wrote % '
      '(want %)', ts, tx_now;
  end if;

  -- The within-the-hour branch, proven by absence of a write, not by
  -- comparing timestamps. now() is transaction-stable, so an UNTHROTTLED
  -- `on conflict do update set last_seen_at = excluded.last_seen_at` would
  -- ALSO leave the read-back value looking unchanged inside this one
  -- transaction — comparing two timestamps here would pass against a
  -- completely missing throttle predicate. pg_stat_xact_user_tables' tuple-
  -- update counter is what 20260828001636's own throttle test already uses
  -- for the identical reason, reused here rather than a second technique.
  select n_tup_upd into upd_before from pg_stat_xact_user_tables
   where relname = 'profile_last_seen';
  perform public.touch_last_seen(reader);
  select n_tup_upd into upd_after from pg_stat_xact_user_tables
   where relname = 'profile_last_seen';
  n := n + 1;
  if coalesce(upd_after, 0) <> coalesce(upd_before, 0) then
    raise exception 'FAIL rpc_behaviour — an immediate repeat touch performed % row '
      'update(s); the within-the-hour throttle predicate is missing', upd_after - upd_before;
  end if;

  -- The stale-but-not-null branch. Exact equality to tx_now again — a
  -- predicate that advances a two-hour-old row by one second, or to 90
  -- minutes ago rather than to now, would pass a merely-"did it move" check
  -- while leaving the row still stale.
  n := n + 1;
  update public.profile_last_seen set last_seen_at = tx_now - interval '2 hours'
   where user_id = reader;
  perform public.touch_last_seen(reader);
  select last_seen_at into ts3 from public.profile_last_seen where user_id = reader;
  if ts3 is distinct from tx_now then
    raise exception 'FAIL rpc_behaviour — touch_last_seen advanced a stale row to % '
      '(want %); it moved, but not to the correct value', ts3, tx_now;
  end if;

  -- No privilege round-trip here: function_acls.test.sql already sweeps every
  -- function in `public`, touch_last_seen included, so a named re-check here
  -- would just be a second, weaker copy of the same fact.
  n := n + 1;
  if (select last_seen_at from public.admin_get_user(reader)) is distinct from ts3 then
    raise exception 'FAIL rpc_behaviour — admin_get_user did not return '
      'profile_last_seen''s last_seen_at through the new left join';
  end if;

  -- No profile_last_seen row at all: admin_get_user must still return the
  -- account's row, with last_seen_at null — proving a LEFT join, not merely
  -- "the scalar subquery below reads as null either way". A regression to an
  -- inner join would make admin_get_user return NO row for this account, and
  -- `(select last_seen_at from admin_get_user(reader))` — a scalar subquery
  -- over zero rows — ALSO evaluates to NULL in Postgres, which the null-check
  -- alone cannot tell apart from a present row with a null column. The
  -- `exists` check below is what actually distinguishes them.
  delete from public.profile_last_seen where user_id = reader;
  n := n + 1;
  if not exists (select 1 from public.admin_get_user(reader)) then
    raise exception 'FAIL rpc_behaviour — admin_get_user returned no row at all for a '
      'known account with no profile_last_seen row; a left join regressed to an inner one';
  end if;
  n := n + 1;
  if (select last_seen_at from public.admin_get_user(reader)) is not null then
    raise exception 'FAIL rpc_behaviour — admin_get_user returned a non-null last_seen_at '
      'for an account with no profile_last_seen row';
  end if;

  -- An id with no matching public.profiles row at all — an auth.users row with
  -- no profile, or simply an id nobody has ever seen (20260828143044). The
  -- first version of this RPC did `insert ... values (...)` unconditionally,
  -- which raised a foreign-key violation here; /api/identity's try/except
  -- swallowed it, so this regressed silently — logged noise on every request
  -- from an orphaned account, forever, with no test catching it.
  n := n + 1;
  r := 'ACCEPTED';
  begin
    perform public.touch_last_seen(gen_random_uuid());
  exception when others then r := sqlstate; end;
  if r <> 'ACCEPTED' then
    raise exception 'FAIL rpc_behaviour — touch_last_seen raised % for an id with no '
      'matching profiles row; it must silently insert nothing (23503 means the '
      'orphan-tolerance fix in 20260828143044 regressed)', r;
  end if;

  summary := format('PASS rpc_behaviour.test.sql — %s assertions', n);
  raise exception '%', summary;
end $$;
