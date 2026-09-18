-- A disabled account can withdraw marketing consent but can do nothing else.
-- ===========================================================================
-- Slice 1 of docs/account-and-trust-plan.md (decision D5: `disabled` freezes
-- everything in `public` EXCEPT marketing-consent withdrawal).
--
-- PENDING-STATE ASSERTIONS: these pass only AFTER supabase/pending/01-05 are
-- applied. Against today's database every one of (a)-(d) fails, each for the
-- reason its own comment gives — that is the point: like the other files
-- here, this one encodes the intended end state rather than whatever the
-- database happens to hold.
--
-- HOW THE DISABLED READER IS SIMULATED. `set local role authenticated` plus
-- a `request.jwt.claims` setting, which is what `auth.uid()` reads — the
-- same mechanism rls_chat.test.sql uses, with the same honest limit: it
-- proves the policies and function bodies hold for a given claim, not that
-- GoTrue issues it.
--
-- THE FIXTURE IS A REAL DISABLED ACCOUNT, chosen dynamically. A synthetic
-- id would fail `is_active_account()` for the wrong reason (no profile row
-- reads as inactive) and the test would pass while proving nothing. If no
-- disabled account exists the file fails at the first assertion rather than
-- silently passing.
--
-- THIS FILE WRITES ROWS (the withdrawal itself). Everything is rolled back
-- by the closing `raise`. Do not remove that raise.
--
-- Run: paste into execute_sql. Read the word after P0001 — PASS or FAIL.
-- See supabase/tests/README.md.

do $$
declare
  n int := 0;
  summary text;

  v_disabled uuid;
  v_consent boolean;
  v_rows int;
  v_grant_oid oid;

  revoked_cols text[] := array[
    'marketing_consent','marketing_consent_language',
    'marketing_consent_policy_version','marketing_consent_surface'
  ];
  c text;
begin
  n := n + 1;
  select id into v_disabled
    from public.profiles
   where is_disabled = true
   order by id
   limit 1;
  if v_disabled is null then
    raise exception 'FAIL disabled_consent — no disabled account exists to test '
      'against; disable a throwaway account and re-run';
  end if;

  -- Become that disabled reader.
  set local role authenticated;
  perform set_config('request.jwt.claims',
                     json_build_object('sub', v_disabled::text)::text, true);

  -- (a) It CAN withdraw consent through the new RPC. Fails today with 42883:
  --     the function does not exist until pending/01 is applied.
  n := n + 1;
  begin
    perform public.update_own_marketing_consent(true);
  exception when sqlstate '42883' then
    raise exception 'FAIL disabled_consent — update_own_marketing_consent() does '
      'not exist; apply supabase/pending/01 first';
  end;
  select marketing_consent into v_consent
    from public.profiles where id = v_disabled;
  if v_consent is distinct from false then
    raise exception 'FAIL disabled_consent — the withdrawal RPC ran but consent '
      'is still %', v_consent;
  end if;

  -- (b) It CANNOT write `first_name` any more. Fails today: the UPDATE lands
  --     (1 row) because the policy has no active-account predicate until
  --     pending/04. After it, the USING clause hides the row and 0 rows move.
  n := n + 1;
  update public.profiles set first_name = 'slice1-probe' where id = v_disabled;
  get diagnostics v_rows = row_count;
  if v_rows <> 0 then
    raise exception 'FAIL disabled_consent — a disabled account updated '
      'profiles.first_name (% row(s)); pending/04 is not applied', v_rows;
  end if;

  -- (c) It CANNOT write `preferences` through `update_own_preferences`.
  --     Fails today: the function has no active-account gate until
  --     pending/05, so the call succeeds and the FAIL below fires.
  n := n + 1;
  begin
    perform public.update_own_preferences('{"theme":"dark"}'::jsonb);
    raise exception 'FAIL disabled_consent — update_own_preferences accepted a '
      'write from a disabled account; pending/05 is not applied';
  exception when sqlstate '42501' then
    if sqlerrm not like '%account is disabled%' then
      raise;
    end if;
    -- Expected: 05's gate refused it before examining the patch.
  end;

  -- (d) It CANNOT grant consent: no path reaches a grant. Two halves —
  --     the grant RPC is service-role-only, and the direct column grants
  --     are gone — and either half missing fails. Fails today twice over:
  --     the function does not exist until pending/02, and the column
  --     grants stand until pending/03.
  n := n + 1;
  select p.oid into v_grant_oid
    from pg_proc p
   where p.pronamespace = 'public'::regnamespace
     and p.proname = 'grant_marketing_consent';
  if v_grant_oid is null then
    raise exception 'FAIL disabled_consent — grant_marketing_consent() does not '
      'exist; apply supabase/pending/02 first';
  end if;
  if has_function_privilege('authenticated', v_grant_oid, 'EXECUTE') then
    raise exception 'FAIL disabled_consent — authenticated can execute '
      'grant_marketing_consent; it must be service-role-only';
  end if;

  foreach c in array revoked_cols loop
    n := n + 2;
    if has_column_privilege('authenticated', 'public.profiles', c, 'UPDATE') then
      raise exception 'FAIL disabled_consent — authenticated can still UPDATE '
        'profiles.% directly; apply supabase/pending/03', c;
    end if;
    if has_column_privilege('authenticated', 'public.profiles', c, 'INSERT') then
      raise exception 'FAIL disabled_consent — authenticated can still INSERT '
        'profiles.% directly; apply supabase/pending/03', c;
    end if;
  end loop;

  summary := format('PASS disabled_consent.test.sql — %s assertions', n);
  raise exception '%', summary;
end $$;
