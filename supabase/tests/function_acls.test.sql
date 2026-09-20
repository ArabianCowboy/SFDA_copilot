-- The RPC contract, written as an assertion instead of a paragraph.
-- ===========================================================================
-- supabase/README.md states it in five points and enforces it by remembering.
-- This is the same contract, checked. It is the test that fails the day a new
-- `security definer` function ships without its revoke line and is therefore
-- callable at /rest/v1/rpc/<name> by anyone with a signed-in session.
--
-- That failure mode used to be unprotected and is now protected in two layers,
-- which is worth stating precisely because the first attempt got it wrong.
-- 20260828000737 revoked the default in schema `public` and observed that new
-- functions were STILL PUBLIC-executable; it wrongly concluded Postgres cannot
-- express this. The real cause was the layer: a per-schema default ACL is
-- merged onto the hard-wired base and cannot subtract PUBLIC from it. The
-- GLOBAL form can, and 20260828100816 applies it, so a new function is now born
-- callable by nobody but its owner and service_role.
--
-- The per-function `revoke execute` line therefore stays in the contract as
-- belt to that braces — and this file is what notices if either is removed.
-- privileges.test.sql asserts the global default itself; this file asserts the
-- resulting per-function state.
--
-- Run: paste into execute_sql. Read the word after P0001 — PASS or FAIL.
-- See supabase/tests/README.md.

do $$
declare
  n int := 0;
  summary text;
  bad text;

  -- The four documented exemptions, and the whole of them. All four are
  -- argued in supabase/README.md's standing-findings table:
  --
  --   is_active_account       — a chat RLS USING clause evaluates it AS THE
  --                             QUERYING ROLE, so revoking EXECUTE from
  --                             authenticated breaks every chat policy.
  --   update_own_preferences  — browser-callable is the entire point of it.
  --   update_own_marketing_consent
  --                           — the consent-withdrawal carve-out: it must stay
  --                             reachable for a disabled account past the
  --                             frozen profiles UPDATE policy.
  --   account_deletion_is_pending
  --                           — the grace-window answer: a pending reader must
  --                             reach their own cancel path past the same
  --                             freeze. Lands with supabase/pending/09.
  --
  -- Adding a fourth name here is a decision, not a fix. If a function needs to
  -- be on this list, it needs a row in that table first.
  browser_callable text[] := array['is_active_account','update_own_preferences',
    'update_own_marketing_consent','account_deletion_is_pending'];

  -- Called only from inside other SECURITY DEFINER functions, which execute as
  -- its owner. Granted to nobody, service_role included — granting it would
  -- create a way to resolve any administrator's email from their uuid over
  -- /rest/v1/rpc/, on a database where service_role holds no access to
  -- auth.users at all. See 20260828001543.
  granted_to_nobody text[] := array['admin_actor_email'];

  -- The two read-only analytics aggregates (docs/admin-analytics-v1-plan.md
  -- §4). They are listed here for two checks the whole-schema sweeps above
  -- cannot make — that they exist at all, and that neither one's RESULT names
  -- an identity column. They deliberately do NOT belong in the mutating list
  -- at assertion 8: they mutate nothing, take no actor, and are gated by
  -- Flask's _gate() before_request, exactly like admin_list_tiers.
  analytics_readers text[] := array['admin_top_questions','admin_citation_stats'];
begin
  -- 1. Nothing in public is executable by anon. No exceptions, including the
  --    four above — none is reachable without a session.
  n := n + 1;
  select string_agg(p.proname, ', ' order by p.proname) into bad
    from pg_proc p
   where p.pronamespace = 'public'::regnamespace
     and has_function_privilege('anon', p.oid, 'EXECUTE');
  if bad is not null then
    raise exception 'FAIL function_acls — anon can execute: %', bad;
  end if;

  -- 2. Exactly the named functions are executable by authenticated.
  n := n + 1;
  select string_agg(p.proname, ', ' order by p.proname) into bad
    from pg_proc p
   where p.pronamespace = 'public'::regnamespace
     and has_function_privilege('authenticated', p.oid, 'EXECUTE')
     and not (p.proname = any(browser_callable));
  if bad is not null then
    raise exception 'FAIL function_acls — authenticated can execute beyond the four '
      'documented exemptions: %', bad;
  end if;

  -- 3. …and both exemptions are still there. A test that only checks for
  --    excess passes against a database where somebody revoked one of these
  --    and broke every chat RLS policy.
  n := n + 1;
  select string_agg(x, ', ') into bad
    from unnest(browser_callable) as x
   where not exists (
     select 1 from pg_proc p
      where p.pronamespace = 'public'::regnamespace and p.proname = x
        and has_function_privilege('authenticated', p.oid, 'EXECUTE'));
  if bad is not null then
    raise exception 'FAIL function_acls — a documented browser-callable function is no '
      'longer executable by authenticated: %', bad;
  end if;

  -- 4. Every callable function is granted to service_role. Trigger functions
  --    are excluded — they are invoked by the trigger, never called — and so
  --    is the internal gate.
  n := n + 1;
  select string_agg(p.proname, ', ' order by p.proname) into bad
    from pg_proc p
   where p.pronamespace = 'public'::regnamespace
     and p.prorettype <> 'trigger'::regtype
     and not (p.proname = any(granted_to_nobody))
     and not has_function_privilege('service_role', p.oid, 'EXECUTE');
  if bad is not null then
    raise exception 'FAIL function_acls — service_role cannot execute: % — Flask calls '
      'these', bad;
  end if;

  -- 5a. The internal gate EXISTS. Not padding: a `where proname = any(...)`
  --     scan returns no rows when the function is absent, so the grant check
  --     below alone reports PASS for a database where the gate was dropped —
  --     the single change that would silently unauthorize every mutating admin
  --     RPC while every other assertion in this file still passed.
  n := n + 1;
  select string_agg(x, ', ') into bad
    from unnest(granted_to_nobody) as x
   where not exists (
     select 1 from pg_proc p
      where p.pronamespace = 'public'::regnamespace and p.proname = x);
  if bad is not null then
    raise exception 'FAIL function_acls — % does not exist; the mutating admin RPCs '
      'call it and are unauthorized without it', bad;
  end if;

  -- 5b. …and is granted to nobody at all.
  n := n + 1;
  select string_agg(p.proname, ', ' order by p.proname) into bad
    from pg_proc p
   where p.pronamespace = 'public'::regnamespace
     and p.proname = any(granted_to_nobody)
     and (has_function_privilege('anon', p.oid, 'EXECUTE')
          or has_function_privilege('authenticated', p.oid, 'EXECUTE')
          or has_function_privilege('service_role', p.oid, 'EXECUTE'));
  if bad is not null then
    raise exception 'FAIL function_acls — % is granted to a role; it is called only from '
      'inside other definer functions and must reach no API surface', bad;
  end if;

  -- 6. Point 2 of the contract: an empty search_path on every function, not
  --    only the definer ones. A definer function without it is a privilege
  --    escalation waiting for a schema the caller controls; an invoker one
  --    without it is a correctness bug waiting for the same thing.
  n := n + 1;
  select string_agg(p.proname, ', ' order by p.proname) into bad
    from pg_proc p
   where p.pronamespace = 'public'::regnamespace
     and coalesce(array_to_string(p.proconfig, ','), '') not like '%search_path=%';
  if bad is not null then
    raise exception 'FAIL function_acls — no `set search_path` on: %', bad;
  end if;

  -- 7. And it is empty, not merely present. `set search_path = public` would
  --    satisfy point 6 and defeat it.
  n := n + 1;
  select string_agg(p.proname, ', ' order by p.proname) into bad
    from pg_proc p
   where p.pronamespace = 'public'::regnamespace
     and coalesce(array_to_string(p.proconfig, ','), '') like '%search_path=%'
     and array_to_string(p.proconfig, ',') !~ 'search_path=("")?$';
  if bad is not null then
    raise exception 'FAIL function_acls — search_path is set but not empty on: %', bad;
  end if;

  -- 8. The seven mutating admin RPCs all route through the actor gate. Checked
  --    by reading the body, which is crude and is still the only thing that
  --    catches a `create or replace` that quietly drops the call — the exact
  --    regression 20260828001543 exists to prevent, and one that no privilege
  --    assertion can see.
  --
  --    HONEST LIMIT: this matches a call-shaped substring, not a call. A dead
  --    branch would satisfy it. Matching `public.admin_actor_email(` rather than
  --    the bare name rules out the commonest false pass — a prose mention in the
  --    function's own header comment — without pretending to be a parser.
  --    Proving the refusal actually fires means calling each RPC with a null
  --    actor and expecting AD004/AN005, which needs a session, not a catalogue
  --    query.
  n := n + 1;
  select string_agg(x, ', ') into bad
    from unnest(array['admin_write_settings','admin_set_user_flags','admin_update_profile',
                      'admin_create_notification','admin_deactivate_notification',
                      'admin_delete_notification','admin_purge_notification',
                      -- Added 2026-09-03 with the reader-quota feature. This array is a
                      -- HARDCODED list, so a new mutating admin RPC that forgets the actor
                      -- gate still passes this suite unless its name is added here. Any
                      -- future one goes in the same commit that creates it.
                      -- A READ-ONLY admin RPC does not go here and never has:
                      -- admin_list_tiers, admin_list_users, admin_get_user and the two
                      -- analytics aggregates are all absent on purpose. Adding one would
                      -- assert that a function which mutates nothing calls the mutation
                      -- gate, which it has no reason to.
                      'admin_create_tier','admin_update_tier','admin_delete_tier',
                      'admin_set_reader_quota']) as x
   where not exists (
     select 1 from pg_proc p
      where p.pronamespace = 'public'::regnamespace and p.proname = x
        and p.prosrc like '%public.admin_actor_email(%');
  if bad is not null then
    raise exception 'FAIL function_acls — these mutating admin RPCs no longer call '
      'admin_actor_email, so a null or demoted actor is unchecked again: %', bad;
  end if;

  -- 9. The two analytics readers EXIST. Not padding, and the same argument as
  --    5a: assertion 10 below is a `where proname = any(...)` scan, which
  --    returns no rows — and so reports PASS — against a database where
  --    neither function was ever applied. Assertions 1, 2, 4, 6 and 7 already
  --    sweep every function in `public`, so once these two exist their ACL and
  --    search_path state is covered by those sweeps and a named re-check here
  --    would be a second, weaker copy. Existence is the one thing a sweep
  --    cannot assert.
  n := n + 1;
  select string_agg(x, ', ') into bad
    from unnest(analytics_readers) as x
   where not exists (
     select 1 from pg_proc p
      where p.pronamespace = 'public'::regnamespace and p.proname = x);
  if bad is not null then
    raise exception 'FAIL function_acls — % does not exist; the admin analytics routes '
      'call it and fail without it', bad;
  end if;

  -- 10. The first of the three privacy layers in
  --     docs/admin-analytics-v1-plan.md §5: the SQL PROJECTION itself names no
  --     identity. Read off the live catalogue rather than the migration text,
  --     so a later `drop function` + `create` that adds an owner, session or
  --     message column to either result fails HERE — before the Python
  --     allow-list and the raw-body route test, each of which is meant to fail
  --     on its own.
  --
  --     Scoped to these two by name deliberately. admin_get_user returns an
  --     email because reporting one account's detail is its whole job; an
  --     aggregate over every account has no such excuse.
  n := n + 1;
  select string_agg(p.proname, ', ' order by p.proname) into bad
    from pg_proc p
   where p.pronamespace = 'public'::regnamespace
     and p.proname = any(analytics_readers)
     and pg_get_function_result(p.oid) ~* 'owner|user_id|actor|email|session_id|message_id';
  if bad is not null then
    raise exception 'FAIL function_acls — an analytics aggregate now returns an identity '
      'column, so the console can print who asked: %', bad;
  end if;

  summary := format('PASS function_acls.test.sql — %s assertions', n);
  raise exception '%', summary;
end $$;
