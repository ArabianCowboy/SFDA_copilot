-- Reader isolation on the chat tables, proved rather than assumed.
-- ===========================================================================
-- The property every Python test in this repository mocks away: that reader A
-- cannot see, write, or delete reader B's conversation. It is enforced by four
-- RLS policies and by the ABSENCE of write grants, and neither half is visible
-- to a suite that stands a fake client in front of PostgREST.
--
-- HOW THE READER IS SIMULATED. `set local role authenticated` plus a
-- `request.jwt.claims` setting, which is what `auth.uid()` reads. That is the
-- same mechanism the notification-center work used to verify its Realtime
-- boundary against the live project, and it is honest about its own limit:
-- it proves the POLICIES hold for a given claim. It does not prove GoTrue
-- issues that claim, and it does not prove PostgREST sets the role. Those are
-- the HTTP layer's to answer.
--
-- THIS FILE WRITES ROWS. Two sessions, two messages and two source rows, using
-- two real profile ids — real because `is_active_account()` reads
-- public.profiles, so a synthetic owner would fail the policy for the wrong
-- reason and the test would pass while proving nothing. Everything is rolled
-- back by the closing `raise`. Do not remove that raise.
--
-- Run: paste into execute_sql. Read the word after P0001 — PASS or FAIL.
-- See supabase/tests/README.md.

do $$
declare
  n int := 0;
  summary text;

  -- Two enabled, non-administrator accounts. If these ids ever stop existing
  -- the test fails at the first assertion rather than silently passing, which
  -- is the intended behaviour — an isolation test against an account that is
  -- not there proves nothing.
  reader_a uuid := 'b01aef2c-7bea-491c-a368-99cd6cc4a5ca';
  reader_b uuid := 'd216e1d3-04c7-4998-b43d-9d38c987fdb9';

  session_a uuid := gen_random_uuid();
  session_b uuid := gen_random_uuid();

  visible_own int; visible_other int;
  messages_own int; messages_other int; sources_other int;
  forged_insert  text := 'ACCEPTED';
  forged_update  text := 'ACCEPTED';
  forged_session text := 'ACCEPTED';
  forged_source  text := 'ACCEPTED';
  deleted_other int; deleted_own int;
  active boolean;
begin
  n := n + 1;
  if (select count(*) from public.profiles
       where id in (reader_a, reader_b) and is_disabled = false) <> 2 then
    raise exception 'FAIL rls_chat — the two fixture accounts are missing or disabled; '
      'update the ids at the top of this file';
  end if;

  insert into public.chat_sessions (id, owner_id, next_seq)
  values (session_a, reader_a, 3), (session_b, reader_b, 3);

  insert into public.chat_messages (session_id, owner_id, seq, role, content, client_request_id)
  values (session_a, reader_a, 1, 'user', 'A question', gen_random_uuid()),
         (session_b, reader_b, 1, 'user', 'B question', gen_random_uuid());

  insert into public.chat_message_sources
    (message_id, source_index, cited, document, category, snippet)
  select id, 1, true, 'doc', 'cat', 'snip'
    from public.chat_messages where session_id in (session_a, session_b);

  -- Become reader A.
  set local role authenticated;
  perform set_config('request.jwt.claims',
                     json_build_object('sub', reader_a::text)::text, true);

  select public.is_active_account() into active;
  select count(*) into visible_own    from public.chat_sessions where id = session_a;
  select count(*) into visible_other  from public.chat_sessions where id = session_b;
  select count(*) into messages_own   from public.chat_messages where session_id = session_a;
  select count(*) into messages_other from public.chat_messages where session_id = session_b;
  select count(*) into sources_other
    from public.chat_message_sources s
    join public.chat_messages m on m.id = s.message_id
   where m.session_id = session_b;

  -- The provenance-forgery primitive that would exist if the chat tables had
  -- write policies: a client crafting an `assistant` row with citations of its
  -- choosing. Refused by the absence of a grant, before RLS is even consulted.
  -- `when insufficient_privilege`, not `when others`. Catching everything would
  -- record a CHECK violation, a foreign-key error or a typo'd column as
  -- "security enforced" — a green result for a database whose grants had been
  -- opened up, as long as the row happened to fail for some unrelated reason.
  -- 42501 is the answer this is actually asserting.
  begin
    insert into public.chat_messages (session_id, owner_id, seq, role, content, client_request_id)
    values (session_a, reader_a, 9, 'assistant', 'forged', gen_random_uuid());
  exception when insufficient_privilege then forged_insert := sqlstate; end;

  begin
    update public.chat_messages set content = 'rewritten' where session_id = session_a;
  exception when insufficient_privilege then forged_update := sqlstate; end;

  begin
    insert into public.chat_sessions (id, owner_id) values (gen_random_uuid(), reader_a);
  exception when insufficient_privilege then forged_session := sqlstate; end;

  begin
    insert into public.chat_message_sources
      (message_id, source_index, cited, document, category, snippet)
    values (gen_random_uuid(), 1, true, 'd', 'c', 's');
  exception when insufficient_privilege then forged_source := sqlstate; end;

  -- Deleting a conversation IS browser-direct — see the chat_sessions_delete_own
  -- policy. So this checks the policy scopes it rather than that the verb is
  -- unavailable: someone else's conversation must match zero rows, and the
  -- reader's own must match one.
  delete from public.chat_sessions where id = session_b;
  get diagnostics deleted_other = row_count;
  delete from public.chat_sessions where id = session_a;
  get diagnostics deleted_own = row_count;

  reset role;

  n := n + 1;
  if not active then
    raise exception 'FAIL rls_chat — is_active_account() is false for an enabled account; '
      'every chat policy depends on it and all of them are now closed';
  end if;

  n := n + 1;
  if visible_own <> 1 then
    raise exception 'FAIL rls_chat — a reader cannot see their OWN session (% rows)', visible_own;
  end if;

  n := n + 1;
  if visible_other <> 0 then
    raise exception 'FAIL rls_chat — a reader can see another account''s session (% rows)',
      visible_other;
  end if;

  n := n + 1;
  if messages_own <> 1 then
    raise exception 'FAIL rls_chat — a reader cannot see their own messages (% rows)', messages_own;
  end if;

  n := n + 1;
  if messages_other <> 0 then
    raise exception 'FAIL rls_chat — a reader can read another account''s messages (% rows)',
      messages_other;
  end if;

  n := n + 1;
  if sources_other <> 0 then
    raise exception 'FAIL rls_chat — a reader can read another account''s citation rows (% rows) '
      '— chat_message_sources joins back to chat_messages and the join is the policy', sources_other;
  end if;

  n := n + 1;
  if forged_insert = 'ACCEPTED' then
    raise exception 'FAIL rls_chat — a signed-in reader can INSERT into chat_messages; that '
      'is a provenance-forgery primitive, not a missing feature';
  end if;

  n := n + 1;
  if forged_update = 'ACCEPTED' then
    raise exception 'FAIL rls_chat — a signed-in reader can UPDATE chat_messages and rewrite '
      'their own transcript';
  end if;

  -- The header claims no browser-direct write path to ANY chat table, so all
  -- three are attempted rather than just the one.
  n := n + 1;
  if forged_session = 'ACCEPTED' then
    raise exception 'FAIL rls_chat — a signed-in reader can INSERT into chat_sessions; '
      'sessions are created only by chat_append_turn';
  end if;

  n := n + 1;
  if forged_source = 'ACCEPTED' then
    raise exception 'FAIL rls_chat — a signed-in reader can INSERT into '
      'chat_message_sources; that is citation forgery';
  end if;

  n := n + 1;
  if deleted_other <> 0 then
    raise exception 'FAIL rls_chat — a reader deleted another account''s conversation (% rows)',
      deleted_other;
  end if;

  n := n + 1;
  if deleted_own <> 1 then
    raise exception 'FAIL rls_chat — a reader cannot delete their own conversation (% rows); '
      'the sidebar delete is broken', deleted_own;
  end if;

  summary := format('PASS rls_chat.test.sql — %s assertions', n);
  raise exception '%', summary;
end $$;
