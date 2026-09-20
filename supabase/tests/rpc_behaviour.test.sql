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

  -- ── The analytics aggregates (docs/admin-analytics-v1-plan.md §4) ────────
  -- FIVE SYNTHETIC OWNERS, not the three real profiles above, because the
  -- asker bucket opens at five distinct accounts and this project has three.
  -- That is legitimate here and nowhere else: chat_sessions.owner_id carries
  -- NO foreign key at all (20260820131914:37-43, and supabase/README.md rule 8
  -- records why), and chat_append_turn's only owner-side lookup is
  -- account_deletion_freezes_writes(), which is false for an id no saga row
  -- names. Nothing survives the closing raise either way.
  owners uuid[] := array[gen_random_uuid(), gen_random_uuid(), gen_random_uuid(),
                         gen_random_uuid(), gen_random_uuid()];
  sess_en1    uuid := gen_random_uuid();  -- owners[1] — the one turn that cited a source
  sess_en2    uuid := gen_random_uuid();  -- owners[2] — three turns
  sess_en_old uuid := gen_random_uuid();  -- owners[1] — backdated three days
  sess_ar1    uuid := gen_random_uuid();
  sess_ar2    uuid := gen_random_uuid();
  sess_solo   uuid := gen_random_uuid();

  -- Built with chr() rather than pasted in. An invisible character inside a
  -- string literal is a character no reviewer can see in a diff, and this is a
  -- fixture whose entire point is which invisible characters it contains.
  nbsp text := chr(160);   -- U+00A0 NO-BREAK SPACE
  zwsp text := chr(8203);  -- U+200B ZERO WIDTH SPACE
  rlm  text := chr(8207);  -- U+200F RIGHT-TO-LEFT MARK
  aqm  text := chr(1567);  -- U+061F ARABIC QUESTION MARK
  ell  text := chr(8230);  -- U+2026 HORIZONTAL ELLIPSIS
  q_ar text := 'ما هي متطلبات التسجيل';
  -- Every run of spaces spelled with repeat(), so the count is readable rather
  -- than something a reviewer has to select the line to measure.
  q_en_old text := repeat(' ', 2) || 'RENEW' || repeat(' ', 3) || 'THE'
                   || repeat(' ', 2) || 'LICENCE' || repeat(' ', 2);
  -- A substring every Arabic phrasing below still contains after the marks are
  -- added, so the group can be found whichever raw phrasing array_agg picked.
  ar_needle text := 'متطلبات';

  n_asks bigint; n_uncited bigint; n_askers bigint; n_rows bigint;
  q_text text;
  scopes text;
  cs record;
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

  -- ── The analytics aggregates: normalisation, the asker floor, the two
  --    citation failures, and retroactivity
  --    (docs/admin-analytics-v1-plan.md §4, and §2's second property) ─────────
  --
  -- THIS IS THE ONLY PLACE EITHER IS PROVEN OFF A PYTHON DOUBLE. The Flask
  -- suite aggregates over an in-memory backend, so it can only ever agree with
  -- itself; `\s` in particular behaves differently here than it does in Python
  -- (it matches NO non-ASCII space in this database, and U+00A0 in Python),
  -- which is exactly the class of disagreement a mocked suite cannot see.
  --
  -- SHARED NORMALISATION FIXTURE — web/tests/test_admin_analytics.py's
  -- test_the_double_and_the_database_normalise_alike carries this identical
  -- list against normalize_question(). Change a pair here and change it there
  -- in the same commit, or the double and the database stop agreeing about
  -- what one question is:
  --
  --   'Renew the licence' || '?'                      -> 'renew the licence'
  --   q_en_old  (2/3/2/2 spaces, upper case)          -> 'renew the licence'
  --   'Renew the' || nbsp || 'licence' || ell         -> 'renew the licence'
  --   'Renew' || zwsp || ' the licence!'              -> 'renew the licence'
  --   rlm || 'Renew the licence.'                     -> 'renew the licence'
  --   q_ar || aqm                                     -> q_ar
  --   'ما هي' || nbsp || 'متطلبات' || 2 spaces || 'التسجيل'  -> q_ar
  --   rlm || q_ar || zwsp || ell                      -> q_ar
  --
  -- lang 'zzq' and 'zzc' isolate these turns from the real saved conversations
  -- this database already holds: no real turn carries either, so every call
  -- below runs against the whole table for real and still sees only what this
  -- block seeded. It also exercises p_lang rather than needing a check of its
  -- own.
  n := n + 1;
  if to_regprocedure('public.admin_top_questions(integer,text,text,integer,integer,text)') is null
     or to_regprocedure('public.admin_citation_stats(integer,text,text)') is null then
    raise exception 'FAIL rpc_behaviour — the analytics aggregates do not exist; apply the '
      'three docs/admin-analytics-v1-plan.md §4 migrations before running this file';
  end if;

  -- Five phrasings of one English question, across TWO accounts: owners[1]
  -- asks twice, owners[2] three times. Only the first turn cites anything.
  perform public.chat_append_turn(owners[1], sess_en1, gen_random_uuid(),
    'Renew the licence?', 'a',
    jsonb_build_array(jsonb_build_object('source_index', 1, 'cited', true)),
    'zzq', 'zzq_cat', 'm', 'r', null, null, true, 't', true);
  perform public.chat_append_turn(owners[1], sess_en_old, gen_random_uuid(),
    q_en_old, 'a', '[]'::jsonb,
    'zzq', 'zzq_cat', 'm', 'r', null, null, true, 't', true);
  perform public.chat_append_turn(owners[2], sess_en2, gen_random_uuid(),
    'Renew the' || nbsp || 'licence' || ell, 'a', '[]'::jsonb,
    'zzq', 'zzq_cat', 'm', 'r', null, null, true, 't', true);
  perform public.chat_append_turn(owners[2], sess_en2, gen_random_uuid(),
    'Renew' || zwsp || ' the licence!', 'a', '[]'::jsonb,
    'zzq', 'zzq_cat', 'm', 'r', null, null, true, 't', true);
  perform public.chat_append_turn(owners[2], sess_en2, gen_random_uuid(),
    rlm || 'Renew the licence.', 'a', '[]'::jsonb,
    'zzq', 'zzq_cat', 'm', 'r', null, null, true, 't', true);

  -- The same three marks on an Arabic question, across the same two accounts.
  perform public.chat_append_turn(owners[1], sess_ar1, gen_random_uuid(),
    q_ar || aqm, 'a', '[]'::jsonb,
    'zzq', 'zzq_cat', 'm', 'r', null, null, true, 't', true);
  perform public.chat_append_turn(owners[2], sess_ar2, gen_random_uuid(),
    'ما هي' || nbsp || 'متطلبات' || repeat(' ', 2) || 'التسجيل', 'a', '[]'::jsonb,
    'zzq', 'zzq_cat', 'm', 'r', null, null, true, 't', true);
  perform public.chat_append_turn(owners[2], sess_ar2, gen_random_uuid(),
    rlm || q_ar || zwsp || ell, 'a', '[]'::jsonb,
    'zzq', 'zzq_cat', 'm', 'r', null, null, true, 't', true);

  -- One account asking the same thing five times. `group by` over turns does
  -- not deduplicate by reader, so without a DISTINCT-asker floor this reads as
  -- a five-count row and prints one reader's content to an operator.
  for i in 1..5 loop
    perform public.chat_append_turn(owners[4], sess_solo, gen_random_uuid(),
      'Does the guideline require a local agent?', 'a', '[]'::jsonb,
      'zzq', 'zzq_cat', 'm', 'r', null, null, true, 't', true);
  end loop;

  -- Four distinct accounts, then five: the two sides of the asker bucket.
  for i in 1..4 loop
    perform public.chat_append_turn(owners[i], gen_random_uuid(), gen_random_uuid(),
      'Ask counted by four accounts', 'a', '[]'::jsonb,
      'zzq', 'zzq_cat', 'm', 'r', null, null, true, 't', true);
  end loop;
  for i in 1..5 loop
    perform public.chat_append_turn(owners[i], gen_random_uuid(), gen_random_uuid(),
      'Ask counted by five accounts', 'a', '[]'::jsonb,
      'zzq', 'zzq_cat', 'm', 'r', null, null, true, 't', true);
  end loop;

  -- Three turns for the citation split, under their own lang and two search
  -- scopes: cited one of two retrieved / retrieved two and cited neither /
  -- retrieved nothing at all.
  perform public.chat_append_turn(owners[1], gen_random_uuid(), gen_random_uuid(),
    'Cited one of two', 'a',
    jsonb_build_array(jsonb_build_object('source_index', 1, 'cited', true),
                      jsonb_build_object('source_index', 2, 'cited', false)),
    'zzc', 'zzc_one', 'm', 'r', null, null, true, 't', true);
  perform public.chat_append_turn(owners[2], gen_random_uuid(), gen_random_uuid(),
    'Retrieved two and cited neither', 'a',
    jsonb_build_array(jsonb_build_object('source_index', 1, 'cited', false),
                      jsonb_build_object('source_index', 2, 'cited', false)),
    'zzc', 'zzc_one', 'm', 'r', null, null, true, 't', true);
  perform public.chat_append_turn(owners[3], gen_random_uuid(), gen_random_uuid(),
    'Search found nothing', 'a', '[]'::jsonb,
    'zzc', 'zzc_two', 'm', 'r', null, null, true, 't', true);

  -- Backdated AFTER the fact rather than seeded that way: chat_append_turn
  -- owns created_at and there is no parameter for it. Three days puts this one
  -- turn outside a one-day window and inside the seven-day floor, which is
  -- what makes the clamp observable further down.
  update public.chat_messages set created_at = tx_now - interval '3 days'
   where session_id = sess_en_old;

  -- (a) Five phrasings, one group. Matched on a substring every phrasing still
  --     contains, because which RAW phrasing array_agg returns is only pinned
  --     down to "not the backdated one".
  select count(*), max(q.asks), max(q.uncited), max(q.askers)
    into n_rows, n_asks, n_uncited, n_askers
    from public.admin_top_questions(p_lang => 'zzq') q
   where lower(q.question) like '%licence%';
  n := n + 1;
  if n_rows <> 1 or n_asks is distinct from 5 then
    raise exception 'FAIL rpc_behaviour — five English phrasings of one question produced '
      '% group(s) totalling % ask(s) (want 1 and 5); mixed case, a doubled space run, an '
      'NBSP, a zero-width space, an RLM and a trailing ? ! . or ellipsis must all '
      'normalise to one key', n_rows, n_asks;
  end if;

  n := n + 1;
  if n_askers is not null then
    raise exception 'FAIL rpc_behaviour — a two-account group reported askers = %; the '
      'bucket is NULL below five distinct accounts, and an exact count at two is a '
      'participation oracle for any operator who asked it themselves', n_askers;
  end if;

  -- `uncited` must count TURNS WHOSE ANSWER CITED NOTHING, not every turn in
  -- the group: four of these five cited nothing, the first cited one source.
  n := n + 1;
  if n_uncited is distinct from 4 then
    raise exception 'FAIL rpc_behaviour — the English group reported % turn(s) without a '
      'citation (want 4 of 5)', n_uncited;
  end if;

  n := n + 1;
  select count(*), max(q.asks) into n_rows, n_asks
    from public.admin_top_questions(p_lang => 'zzq') q
   where q.question like '%' || ar_needle || '%';
  if n_rows <> 1 or n_asks is distinct from 3 then
    raise exception 'FAIL rpc_behaviour — three Arabic phrasings of one question produced '
      '% group(s) totalling % ask(s) (want 1 and 3); this database classifies none of '
      'NBSP, ZWSP or RLM as whitespace, so the explicit space and mark classes in the '
      'function are what hold an Arabic group together', n_rows, n_asks;
  end if;

  -- (b) The floor. Absent by default…
  n := n + 1;
  if exists (select 1 from public.admin_top_questions(p_lang => 'zzq') q
              where lower(q.question) like '%local agent%') then
    raise exception 'FAIL rpc_behaviour — a question asked five times by ONE account was '
      'returned; the floor counts DISTINCT ASKERS, not asks, and one reader''s content is '
      'now printed verbatim in the console';
  end if;

  -- …and not lowerable by a caller, which is the property that lets this ship
  -- with no privacy-policy edit and no audit row per read.
  n := n + 1;
  if exists (select 1 from public.admin_top_questions(p_lang => 'zzq', p_min_askers => 1) q
              where lower(q.question) like '%local agent%') then
    raise exception 'FAIL rpc_behaviour — p_min_askers => 1 lowered the floor; '
      'greatest(coalesce(p_min_askers, 2), 2) is what makes it un-lowerable from '
      '/rest/v1/rpc/ with a leaked service key as well as from the route';
  end if;

  -- Raising it still works. A floor that could not be raised would be a
  -- constant, and follow-up work needs the parameter to mean something.
  n := n + 1;
  if exists (select 1 from public.admin_top_questions(p_lang => 'zzq', p_min_askers => 3) q
              where lower(q.question) like '%licence%') then
    raise exception 'FAIL rpc_behaviour — p_min_askers => 3 still returned a group with '
      'exactly two distinct askers';
  end if;

  -- (c) The bucket, on both sides of five.
  select max(q.asks), max(q.askers) into n_asks, n_askers
    from public.admin_top_questions(p_lang => 'zzq') q
   where lower(q.question) like '%four accounts%';
  n := n + 1;
  if n_asks is distinct from 4 or n_askers is not null then
    raise exception 'FAIL rpc_behaviour — four distinct accounts reported asks = %, '
      'askers = % (want 4 and NULL); the exact count opens at five, not at four',
      n_asks, n_askers;
  end if;

  select max(q.asks), max(q.askers) into n_asks, n_askers
    from public.admin_top_questions(p_lang => 'zzq') q
   where lower(q.question) like '%five accounts%';
  n := n + 1;
  if n_asks is distinct from 5 or n_askers is distinct from 5 then
    raise exception 'FAIL rpc_behaviour — five distinct accounts reported asks = %, '
      'askers = % (want 5 and 5)', n_asks, n_askers;
  end if;

  -- (d) The seven-day window floor. One of the five English turns is three
  --     days old, so a honoured p_days = 1 would report four.
  select max(q.asks) into n_asks
    from public.admin_top_questions(p_days => 1, p_lang => 'zzq') q
   where lower(q.question) like '%licence%';
  n := n + 1;
  if n_asks is distinct from 5 then
    raise exception 'FAIL rpc_behaviour — p_days => 1 returned % ask(s) for a group with '
      'one turn backdated three days (want 5); without the clamp a direct caller can '
      'difference two narrow windows down to a single turn', n_asks;
  end if;

  -- `question` is the MOST RECENT raw phrasing in the group. Every other turn
  -- shares tx_now exactly — now() is transaction-stable — so which of the four
  -- wins is a tie, but the three-day-old one must never.
  select q.question into q_text
    from public.admin_top_questions(p_lang => 'zzq') q
   where lower(q.question) like '%licence%';
  n := n + 1;
  if q_text is not distinct from q_en_old then
    raise exception 'FAIL rpc_behaviour — the group returned the three-day-old phrasing; '
      'the array_agg ordering is load-bearing, not decorative';
  end if;

  -- (e) Citation stats: three grouping sets, and the two failures apart.
  select string_agg(distinct c.scope, ', ' order by c.scope) into scopes
    from public.admin_citation_stats(p_lang => 'zzc') c;
  n := n + 1;
  if scopes is distinct from 'category, lang, total' then
    raise exception 'FAIL rpc_behaviour — admin_citation_stats emitted scopes [%] (want '
      '[category, lang, total]); the three grouping sets are what the console''s two '
      'breakdown tbodies read', scopes;
  end if;

  select * into cs from public.admin_citation_stats(p_lang => 'zzc') c
   where c.scope = 'total';
  n := n + 1;
  if cs.turns is distinct from 3 or cs.turns_uncited is distinct from 1
     or cs.turns_no_retrieval is distinct from 1 or cs.cited_total is distinct from 1
     or cs.retrieved_total is distinct from 4 or cs.bucket is not null then
    raise exception 'FAIL rpc_behaviour — the total row reads turns=%, uncited=%, '
      'no_retrieval=%, cited=%, retrieved=%, bucket=% (want 3, 1, 1, 1, 4 and null)',
      cs.turns, cs.turns_uncited, cs.turns_no_retrieval, cs.cited_total,
      cs.retrieved_total, cs.bucket;
  end if;

  -- The turn with NO source rows at all. "Search found nothing" and "cited
  -- nothing it found" are different failures, they are disjoint, and merging
  -- them is the reading this assertion exists to refuse.
  select * into cs from public.admin_citation_stats(p_lang => 'zzc') c
   where c.scope = 'category' and c.bucket = 'zzc_two';
  n := n + 1;
  if cs.turns is distinct from 1 or cs.turns_no_retrieval is distinct from 1
     or cs.turns_uncited is distinct from 0 or cs.retrieved_total is distinct from 0 then
    raise exception 'FAIL rpc_behaviour — a turn with zero source rows read turns=%, '
      'no_retrieval=%, uncited=%, retrieved=% (want 1, 1, 0, 0)',
      cs.turns, cs.turns_no_retrieval, cs.turns_uncited, cs.retrieved_total;
  end if;

  -- …against the scope holding one cited turn and one that cited none of two.
  select * into cs from public.admin_citation_stats(p_lang => 'zzc') c
   where c.scope = 'category' and c.bucket = 'zzc_one';
  n := n + 1;
  if cs.turns is distinct from 2 or cs.turns_uncited is distinct from 1
     or cs.turns_no_retrieval is distinct from 0 or cs.cited_total is distinct from 1
     or cs.retrieved_total is distinct from 4 then
    raise exception 'FAIL rpc_behaviour — the retrieved-but-uncited scope read turns=%, '
      'uncited=%, no_retrieval=%, cited=%, retrieved=% (want 2, 1, 0, 1, 4)',
      cs.turns, cs.turns_uncited, cs.turns_no_retrieval, cs.cited_total,
      cs.retrieved_total;
  end if;

  -- (f) RETROACTIVITY, pinned as intended behaviour so nobody later "fixes" it
  --     into the no-name log table this feature ruled out. Deleting one
  --     conversation removes its turns from the aggregate through
  --     chat_messages_session_owner_fk's cascade — the same cascade the
  --     account-deletion purge rides. owners[1] keeps the backdated turn, so
  --     the group still clears the floor and the drop is visible rather than
  --     the whole row vanishing.
  delete from public.chat_sessions where id = sess_en1;
  select max(q.asks), max(q.uncited) into n_asks, n_uncited
    from public.admin_top_questions(p_lang => 'zzq') q
   where lower(q.question) like '%licence%';
  n := n + 1;
  if n_asks is distinct from 4 or n_uncited is distinct from 4 then
    raise exception 'FAIL rpc_behaviour — after deleting one conversation the group reads '
      '% ask(s) and % without a citation (want 4 and 4); last month''s figure going down '
      'is the deletion promise working', n_asks, n_uncited;
  end if;

  -- (g) p_category NARROWS both functions. p_lang is exercised by every call
  --     above (it is what isolates this block from real turns); without this
  --     pair a function that ignored p_category would pass the whole file —
  --     the Python suite found exactly that hole in its own double first.
  n := n + 1;
  if exists (select 1 from public.admin_top_questions(p_lang => 'zzq',
                                                       p_category => 'zzq_other') q) then
    raise exception 'FAIL rpc_behaviour — p_category did not narrow admin_top_questions; '
      'a scope no seeded turn carries still returned a group';
  end if;

  select * into cs from public.admin_citation_stats(p_lang => 'zzc', p_category => 'zzc_two') c
   where c.scope = 'total';
  n := n + 1;
  if cs.turns is distinct from 1 then
    raise exception 'FAIL rpc_behaviour — p_category => zzc_two gave a total of % turn(s) '
      '(want 1)', cs.turns;
  end if;

  -- (h) The line and paragraph separators a PDF emits for a soft break.
  --     Postgres's `\s` matches U+2028 and U+2029 on this database and the
  --     Python double did not, until a third review measured all 52 space,
  --     control and format code points against the live expression. Pinned
  --     here because this is the only place the SQL side of that is proven.
  perform public.chat_append_turn(owners[1], gen_random_uuid(), gen_random_uuid(),
    'Soft break question', 'a', '[]'::jsonb,
    'zzq', 'zzq_cat', 'm', 'r', null, null, true, 't', true);
  perform public.chat_append_turn(owners[2], gen_random_uuid(), gen_random_uuid(),
    'soft' || chr(8232) || 'break' || chr(8233) || 'question', 'a', '[]'::jsonb,
    'zzq', 'zzq_cat', 'm', 'r', null, null, true, 't', true);
  select max(q.asks) into n_asks
    from public.admin_top_questions(p_lang => 'zzq') q
   where lower(q.question) like 'soft%question';
  n := n + 1;
  if n_asks is distinct from 2 then
    raise exception 'FAIL rpc_behaviour — a question broken by U+2028 / U+2029 grouped as '
      '% ask(s) with its plain twin (want 2)', n_asks;
  end if;

  -- (i) Ties break in "C" (code-point) order, not the database collation.
  --     en_US.UTF-8 ignores spaces and hyphens at the primary level, so it
  --     returns [tie a | tiea | tie b | tie-b]; the double sorts by code point,
  --     and on a small population the tie-break decides which rows survive
  --     `limit`. The four keys are chosen because the two orders DIFFER on
  --     them — a first draft used three on which they agree, and passed against
  --     the function it was meant to fail.
  for i in 1..2 loop
    perform public.chat_append_turn(owners[i], gen_random_uuid(), gen_random_uuid(),
      'tie-b', 'a', '[]'::jsonb, 'zzt', 'zzt_cat', 'm', 'r', null, null, true, 't', true);
    perform public.chat_append_turn(owners[i], gen_random_uuid(), gen_random_uuid(),
      'tie a', 'a', '[]'::jsonb, 'zzt', 'zzt_cat', 'm', 'r', null, null, true, 't', true);
    perform public.chat_append_turn(owners[i], gen_random_uuid(), gen_random_uuid(),
      'tiea', 'a', '[]'::jsonb, 'zzt', 'zzt_cat', 'm', 'r', null, null, true, 't', true);
    perform public.chat_append_turn(owners[i], gen_random_uuid(), gen_random_uuid(),
      'tie b', 'a', '[]'::jsonb, 'zzt', 'zzt_cat', 'm', 'r', null, null, true, 't', true);
  end loop;
  select string_agg(q.question, ' | ' order by q.ord) into scopes
    from public.admin_top_questions(p_lang => 'zzt')
         with ordinality as q(question, asks, uncited, askers, ord);
  n := n + 1;
  if scopes is distinct from 'tie a | tie b | tie-b | tiea' then
    raise exception 'FAIL rpc_behaviour — tied groups came back as [%] (want '
      '[tie a | tie b | tie-b | tiea], code-point order)', scopes;
  end if;

  summary := format('PASS rpc_behaviour.test.sql — %s assertions', n);
  raise exception '%', summary;
end $$;
