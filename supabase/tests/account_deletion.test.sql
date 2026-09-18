-- The self-serve deletion saga, exercised for real and rolled back.
-- ===========================================================================
-- Slice 2a of docs/account-and-trust-plan.md (decisions D1, D2, D3).
--
-- PENDING-STATE ASSERTIONS: these pass only AFTER supabase/pending/06-12 are
-- applied. Against today's database the FIRST saga reference fails with
-- 42P01 (`account_deletions` does not exist) — that is the point: like the
-- other files here, this one encodes the intended end state rather than
-- whatever the database happens to hold. Per-assertion "fails today"
-- reasons are noted inline as (TODAY: ...).
--
-- FIXTURES ARE REAL ACCOUNTS, chosen dynamically. A synthetic id would fail
-- `account_deletion_request` for the wrong reason (no profile row reads as
-- P0002, and an admin refusal needs a real admin row), and the test would
-- pass while proving nothing. Needs one enabled administrator and three
-- enabled readers; if they do not exist the file fails at the first
-- assertion rather than silently passing.
--
-- PHASE ORDER IS LOAD-BEARING. The saga RPCs are service-role-only, and
-- Postgres checks EXECUTE against the CURRENT role at call time — so every
-- saga call runs first as the executing owner, and `set local role
-- authenticated` plus a `request.jwt.claims` setting (the same mechanism
-- rls_chat.test.sql uses) comes LAST, for the browser-callable checks only.
--
-- THIS FILE WRITES ROWS (saga rows, a disable, a purge of real sessions).
-- Everything is rolled back by the closing `raise`. Do not remove that
-- raise.
--
-- Run: paste into execute_sql. Read the word after P0001 — PASS or FAIL.
-- See supabase/tests/README.md.

do $$
declare
  n int := 0;
  summary text;

  admin_a uuid;
  reader_a uuid;
  reader_b uuid;
  reader_c uuid;

  v_json jsonb;
  v_count int;
  v_state text;
  v_disabled boolean;
  v_reason text;
  v_sess uuid;
  v_active boolean;
begin
  n := n + 1;
  select id into admin_a from public.profiles
   where role = 'admin' and not is_disabled order by id limit 1;
  select id into reader_a from public.profiles
   where role <> 'admin' and not is_disabled order by id limit 1;
  select id into reader_b from public.profiles
   where role <> 'admin' and not is_disabled and id <> reader_a order by id limit 1;
  select id into reader_c from public.profiles
   where role <> 'admin' and not is_disabled and id <> reader_a and id <> reader_b
   order by id limit 1;
  if admin_a is null or reader_a is null or reader_b is null or reader_c is null then
    raise exception 'FAIL account_deletion — needs one enabled administrator and three '
      'enabled readers; found admin_a=%, reader_a=%, reader_b=%, reader_c=%',
      admin_a, reader_a, reader_b, reader_c;
  end if;

  -- (a) REQUEST inserts a pending saga with a 30-day grace.
  --     (TODAY: 42P01, account_deletions does not exist.)
  n := n + 1;
  select public.account_deletion_request(reader_a) into v_json;
  if (v_json ->> 'state') <> 'pending' then
    raise exception 'FAIL account_deletion — request left state %, not pending',
      v_json ->> 'state';
  end if;
  if (v_json ->> '_replay')::boolean is distinct from false then
    raise exception 'FAIL account_deletion — a first request must not replay';
  end if;

  -- (b) REQUEST is idempotent: a second request replays the row, no duplicate.
  --     (TODAY: 42P01, same as (a).)
  n := n + 1;
  select public.account_deletion_request(reader_a) into v_json;
  if (v_json ->> '_replay')::boolean is distinct from true then
    raise exception 'FAIL account_deletion — a second request for a live saga must replay';
  end if;
  select count(*) into v_count from public.account_deletions where user_id = reader_a;
  if v_count <> 1 then
    raise exception 'FAIL account_deletion — % saga rows for one owner', v_count;
  end if;

  -- (c) REQUEST refuses an administrator (D1's carve-out, enforced in the body).
  --     (TODAY: 42P01 — and after 07 alone, the refusal it would MISS is the
  --     point: without the DL003 body check an admin could self-delete.)
  n := n + 1;
  begin
    perform public.account_deletion_request(admin_a);
    raise exception 'FAIL account_deletion — request accepted an administrator target';
  exception when sqlstate 'DL003' then
    -- Expected: self-serve deletion is not available to administrators.
  end;

  -- (d) CLAIM before grace expiry returns null — not due is a normal outcome.
  --     (TODAY: 42883, the function does not exist.)
  n := n + 1;
  select public.account_deletion_claim(reader_a, 'pending', 300) into v_json;
  if v_json is not null then
    raise exception 'FAIL account_deletion — claimed a saga still inside its grace window';
  end if;

  -- (e) CLAIM from the wrong state raises DL004.
  --     (TODAY: 42883, same as (d).)
  n := n + 1;
  begin
    perform public.account_deletion_claim(reader_a, 'auth_delete_begun', 300);
    raise exception 'FAIL account_deletion — claim from a non-edge state did not raise';
  exception when sqlstate 'DL004' then
    -- Expected: only pending / failed / purging are claimable.
  end;

  -- Simulate grace expiry. now() is transaction-stable, so the +30 days from
  -- (a) cannot elapse on its own; moving purge_after is the only way to make
  -- a row due inside this block.
  update public.account_deletions
     set purge_after = now() - interval '1 second'
   where user_id = reader_a;

  -- (f) LEASE CONTENTION: two claims, one wins. The first takes the lease;
  --     the second — same state, live lease — returns null, not an error.
  --     (TODAY: 42883, same as (d).)
  n := n + 1;
  select public.account_deletion_claim(reader_a, 'pending', 300) into v_json;
  if (v_json ->> 'state') <> 'purging' then
    raise exception 'FAIL account_deletion — a due claim did not enter purging';
  end if;
  select public.account_deletion_claim(reader_a, 'purging', 300) into v_json;
  if v_json is not null then
    raise exception 'FAIL account_deletion — two drivers claimed one step';
  end if;

  -- (g) chat_append_turn refuses a PURGING owner with the distinct UDL01,
  --     and creates NO session row in the attempt. Slice 2c narrowed this
  --     refusal from "any live saga" to "a frozen one" (purging and beyond):
  --     reader_a was claimed into `purging` in (f), so the refusal still
  --     fires here — the predicate changed, not the outcome for this state.
  --     (TODAY, unapplied: the call succeeds — no refusal exists until
  --     pending/11.)
  n := n + 1;
  v_sess := gen_random_uuid();
  begin
    perform public.chat_append_turn(
      reader_a, v_sess, gen_random_uuid(), 'q', 'a', '[]'::jsonb,
      'en', 'general', 'm', 'r', null, null, true);
    raise exception 'FAIL account_deletion — chat_append_turn wrote for a purging owner';
  exception when sqlstate 'UDL01' then
    -- Expected: DL001, told apart from an ordinary failure by the state.
  end;
  perform 1 from public.chat_sessions s where s.id = v_sess;
  if found then
    raise exception 'FAIL account_deletion — the refused turn still created a session row';
  end if;

  -- (g2) …but a PENDING owner's turn IS filed. Slice 2c's reversal: grace is
  --     fully usable, and the freeze begins only once the purge starts.
  --     reader_b is requested fresh here, so it is pending; the turn must
  --     land, INCLUDING its lazily created session row. (Against the
  --     pre-2c draft this call raises UDL01 — that is the contract change.)
  --     The later re-request of reader_b below replays idempotently.
  n := n + 1;
  perform public.account_deletion_request(reader_b);
  v_sess := gen_random_uuid();
  perform public.chat_append_turn(
    reader_b, v_sess, gen_random_uuid(), 'q', 'a', '[]'::jsonb,
    'en', 'general', 'm', 'r', null, null, true);
  perform 1 from public.chat_sessions s where s.id = v_sess;
  if not found then
    raise exception 'FAIL account_deletion — chat_append_turn did not file a pending turn';
  end if;

  -- (h) admin_set_user_flags on a pending target: a pure DISABLE goes
  --     through (slice 2d — the operator must be able to stop an abusive
  --     account inside usable grace), while an Enable and any role change
  --     are refused with DL002 (the resurrection hole stays closed).
  --     (TODAY: the call succeeds and rewrites flags on a doomed account.)
  n := n + 1;
  perform public.admin_set_user_flags(
    reader_a, null, true, 'operator stop', admin_a, 'probe@example.com');
  select p.is_disabled into v_disabled from public.profiles p where p.id = reader_a;
  if v_disabled is distinct from true then
    raise exception 'FAIL account_deletion — a pure disable did not land on a pending target';
  end if;
  -- reader_a stays disabled from here on: the saga steps below take
  -- p_owner_id under service_role and never consult is_disabled, so they
  -- are unaffected. (Resuming reader_a is impossible by design — an Enable
  -- on a live saga is refused, as just asserted.)
  begin
    perform public.admin_set_user_flags(
      reader_a, null, false, 'probe', admin_a, 'probe@example.com');
    raise exception 'FAIL account_deletion — admin_set_user_flags enabled a pending target';
  exception when sqlstate 'DL002' then
    -- Expected.
  end;
  begin
    perform public.admin_set_user_flags(
      reader_a, 'admin', null, 'probe', admin_a, 'probe@example.com');
    raise exception 'FAIL account_deletion — admin_set_user_flags re-roled a pending target';
  exception when sqlstate 'DL002' then
    -- Expected.
  end;

  -- (i) PURGE deletes the owner's sessions; the re-purge inside
  --     begin_auth_delete then finds nothing further to do but still moves
  --     the state. (TODAY: 42883 for both functions.)
  n := n + 1;
  select public.account_deletion_purge_transcripts(reader_a) into v_json;
  select public.account_deletion_begin_auth_delete(reader_a) into v_json;
  if (v_json ->> 'state') <> 'auth_delete_begun' then
    raise exception 'FAIL account_deletion — did not reach auth_delete_begun, at %',
      v_json ->> 'state';
  end if;
  if (v_json ->> 'repurged_sessions')::int <> 0 then
    raise exception 'FAIL account_deletion — the re-purge found sessions the purge missed';
  end if;
  select count(*) into v_count from public.chat_sessions s where s.owner_id = reader_a;
  if v_count <> 0 then
    raise exception 'FAIL account_deletion — % session(s) survived the purge', v_count;
  end if;

  -- (j) record_auth_outcome treats not_found as SUCCESS (the user is gone,
  --     which is the goal). (TODAY: 42883.)
  n := n + 1;
  select public.account_deletion_record_auth_outcome(reader_a, 'not_found') into v_json;
  if (v_json ->> 'auth_deleted_at') is null then
    raise exception 'FAIL account_deletion — not_found did not mark the auth user gone';
  end if;
  if (v_json ->> 'state') <> 'auth_delete_begun' then
    raise exception 'FAIL account_deletion — not_found moved the state to %',
      v_json ->> 'state';
  end if;

  -- (k) COMPLETE refuses DL006 while the profile row still exists — fail
  --     closed, never certify an erasure that kept the PII. (The success
  --     path needs the GoTrue user gone first, which SQL cannot do —
  --     service_role reaches auth.users nowhere — so only the refusal is
  --     asserted here. TODAY: 42883.)
  n := n + 1;
  begin
    perform public.account_deletion_complete(reader_a);
    raise exception 'FAIL account_deletion — complete certified a surviving profile row';
  exception when sqlstate 'DL006' then
    -- Expected: the profile row is still there, so PII remains.
  end;

  -- (l) FAIL then CANCEL-too-late: transcripts are purged, so DL005.
  --     (TODAY: 42883 for account_deletion_fail.)
  n := n + 1;
  select public.account_deletion_fail(reader_a, 'E2E-probe') into v_json;
  if (v_json ->> 'state') <> 'failed' or (v_json ->> 'last_error_code') <> 'E2E-probe' then
    raise exception 'FAIL account_deletion — fail did not record state and code';
  end if;
  begin
    perform public.account_deletion_cancel(reader_a);
    raise exception 'FAIL account_deletion — cancel succeeded past the purge';
  exception when sqlstate 'DL005' then
    -- Expected: nothing truthful left to cancel back to.
  end;

  -- (l2) A FAILED owner is still refused a turn (fail closed: a partial
  --     purge must not silently reactivate), and creates no session row.
  --     (TODAY, unapplied: the call succeeds — no refusal exists at all.)
  n := n + 1;
  v_sess := gen_random_uuid();
  begin
    perform public.chat_append_turn(
      reader_a, v_sess, gen_random_uuid(), 'q', 'a', '[]'::jsonb,
      'en', 'general', 'm', 'r', null, null, true);
    raise exception 'FAIL account_deletion — chat_append_turn wrote for a failed owner';
  exception when sqlstate 'UDL01' then
    -- Expected: DL001, like (g).
  end;
  perform 1 from public.chat_sessions s where s.id = v_sess;
  if found then
    raise exception 'FAIL account_deletion — the refused turn still created a session row';
  end if;

  -- (m) CANCEL restores only what the saga set: an operator disable from
  --     BEFORE the request survives the cancel untouched. Reader_c is
  --     disabled first (no saga row yet, so no DL002), then requested,
  --     failed without any purge, then cancelled.
  --     (TODAY: DL002 never fires and cancel does not exist — 42883.)
  n := n + 1;
  perform public.admin_set_user_flags(
    reader_c, null, true, 'operator case', admin_a, 'probe@example.com');
  perform public.account_deletion_request(reader_c);
  perform public.account_deletion_fail(reader_c, 'E2E-probe');
  select public.account_deletion_cancel(reader_c) into v_json;
  if (v_json ->> 'state') <> 'cancelled' then
    raise exception 'FAIL account_deletion — cancel from unpurged failed did not cancel';
  end if;
  select p.is_disabled, p.disabled_reason into v_disabled, v_reason
    from public.profiles p where p.id = reader_c;
  if v_disabled is distinct from true or v_reason <> 'operator case' then
    raise exception 'FAIL account_deletion — cancel cleared an operator disable';
  end if;

  -- A second pending saga, left pending for the browser-callable phase.
  perform public.account_deletion_request(reader_b);

  -- Become that pending reader. From here on only browser-callable calls.
  set local role authenticated;
  perform set_config('request.jwt.claims',
                     json_build_object('sub', reader_b::text)::text, true);

  -- (n) The pending reader SEES their own pending state, and nobody else's
  --     answer leaks: a clean account reads false.
  --     (TODAY: 42883, the function does not exist.)
  n := n + 1;
  select public.account_deletion_is_pending() into v_active;
  if v_active is distinct from true then
    raise exception 'FAIL account_deletion — a pending reader reads pending = %', v_active;
  end if;
  perform set_config('request.jwt.claims',
                     json_build_object('sub', reader_c::text)::text, true);
  select public.account_deletion_is_pending() into v_active;
  if v_active is distinct from false then
    raise exception 'FAIL account_deletion — a cancelled reader reads pending = %', v_active;
  end if;
  perform set_config('request.jwt.claims',
                     json_build_object('sub', reader_b::text)::text, true);

  -- (o) Consent withdrawal STILL WORKS while pending (slice 1's carve-out
  --     is deliberately ungated on is_active_account).
  --     (TODAY: passes already — which is why it is asserted: the 08 fold
  --     must not close it.)
  n := n + 1;
  perform public.update_own_marketing_consent(true);

  -- (o2) …but GRANTING consent is refused while pending (14's DL007):
  --     collecting a FRESH marketing permission from someone who has asked
  --     to be erased stays closed even in a fully usable grace window —
  --     the one carve-out slice 2c kept. reader_b is pending here.
  --     (TODAY: the call SUCCEEDS — 02 ships with no saga gate until 14
  --     lands.)
  n := n + 1;
  begin
    perform public.grant_marketing_consent(
      reader_b, '2026-09-18-draft-2', 'en', 'account');
    raise exception 'FAIL account_deletion — grant_marketing_consent accepted a grant '
      'from a pending account; pending/14 is not applied';
  exception when sqlstate 'DL007' then
    -- Expected: the grant direction stays closed during grace.
  end;

  -- (p) …and preference writes FOLLOW the freeze: a `pending` reader writes
  --     normally (slice 2c: grace is fully usable), while a `failed` one is
  --     still refused. reader_b is pending here; reader_a reached `failed`
  --     in (l) above, so it takes the refusal arm.
  --     (TODAY, unapplied: the pending call is REFUSED — is_active_account
  --     knows nothing of any saga until pending/08 lands — which is the old
  --     contract this assertion reverses.)
  n := n + 1;
  perform public.update_own_preferences('{"theme":"dark"}'::jsonb);
  -- The profiles UPDATE policy (04) follows the same fold: a pending
  -- reader writes `first_name` directly. (TODAY, unapplied: the update
  -- matches no row — the fold reads every live saga as inactive until
  -- 08 lands.)
  update public.profiles set first_name = 'Grace' where id = reader_b;
  get diagnostics v_count = row_count;
  if v_count <> 1 then
    raise exception 'FAIL account_deletion — a pending reader could not write its profile';
  end if;
  perform set_config('request.jwt.claims',
                     json_build_object('sub', reader_a::text)::text, true);
  begin
    perform public.update_own_preferences('{"theme":"dark"}'::jsonb);
    raise exception 'FAIL account_deletion — update_own_preferences accepted a write '
      'from a failed account; the freeze must hold past the purge';
  exception when sqlstate '42501' then
    if sqlerrm not like '%account is disabled%' then
      raise;
    end if;
    -- Expected: 05's gate refused it, via the folded 08 predicate.
  end;
  -- …and the profiles UPDATE policy (04) refuses the failed reader the
  -- same way: the claims above name reader_a itself, so the USING clause
  -- matches on identity and fails on the freeze — zero rows, no error.
  update public.profiles set first_name = 'Grace' where id = reader_a;
  get diagnostics v_count = row_count;
  if v_count <> 0 then
    raise exception 'FAIL account_deletion — a failed reader wrote its profile';
  end if;
  perform set_config('request.jwt.claims',
                     json_build_object('sub', reader_b::text)::text, true);

  summary := format('PASS account_deletion.test.sql — %s assertions', n);
  raise exception '%', summary;
end $$;
