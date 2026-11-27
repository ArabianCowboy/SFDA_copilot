-- Country on Accounts: the list, the sign-up coercion, and who may count.
-- ===========================================================================
-- Protects 20261127230444_country_on_accounts.sql, which Thaqib (the other App
-- on these Accounts) relies on. Three things a catalogue assertion cannot see:
--   * public.countries holds 247 rows (ISO's 249 minus IL and EH, left out by
--     the owner's decision 2026-11-28), RLS on, one SELECT-only policy;
--   * handle_new_user stores a code on the list and NULL for anything else,
--     and never fails the sign-up over it;
--   * accounts_by_country() refuses a signed-out caller, a reader and a
--     disabled admin with its own 42501, and an enabled admin's counts add up
--     to every Account, one without a Profile row included.
--
-- THE FIXTURES ARE SYNTHETIC: auth.users rows on unroutable addresses, so
-- copilot's on_auth_user_created fires exactly as at a real sign-up.
--
-- THIS FILE WRITES ROWS. Everything is rolled back by the closing `raise`.
-- Do not remove that raise. It holds a brief lock on auth.users while it runs.
--
-- Run: paste into execute_sql. Read the word after P0001 — PASS or FAIL.
-- See supabase/tests/README.md.

do $$
declare
  n int := 0;
  v_id uuid;
  v_reader uuid;
  v_admin uuid := gen_random_uuid();
  v_orphan uuid := gen_random_uuid();
  v_got text;
  v_total bigint;
  v_sum bigint;
  i int;

  -- Sign-up metadata, and the country each must leave on the Profile.
  metas jsonb[] := array[
    '{"country":"SA"}', '{"country":"sa"}', '{"country":" SA "}',
    '{"country":"SAU"}', '{"country":"XK"}', '{"country":123}',
    '{"country":null}', '{"country":["SA"]}', '{}',
    jsonb_build_object('country', chr(383) || 'a'),   -- 'ſa': upper() gives 'SA'
    jsonb_build_object('country', repeat('A', 100000)),
    '{"country":"IL"}', '{"country":"EH"}'             -- left off the list
  ]::jsonb[];
  expected text[] := array[
    'SA', 'SA', 'SA',
    null, null, null,
    null, null, null,
    null,
    null,
    null, null
  ];
begin
  -- 1. The list.
  n := n + 1;
  if (select count(*) from public.countries) <> 247 then
    raise exception 'FAIL country_on_accounts — countries has % rows, not 247',
      (select count(*) from public.countries);
  end if;

  n := n + 1;
  if exists (select 1 from public.countries where code in ('IL', 'EH')) then
    raise exception 'FAIL country_on_accounts — IL or EH is on the list; the owner '
      'left both out (2026-11-28)';
  end if;

  n := n + 1;
  if not (select relrowsecurity from pg_class where oid = 'public.countries'::regclass) then
    raise exception 'FAIL country_on_accounts — RLS is off on public.countries';
  end if;

  n := n + 1;
  if (select count(*) from pg_policies
       where schemaname = 'public' and tablename = 'countries') <> 1
     or not exists (select 1 from pg_policies
                     where schemaname = 'public' and tablename = 'countries'
                       and cmd = 'SELECT') then
    raise exception 'FAIL country_on_accounts — countries must have exactly one '
      'policy, and it must be SELECT';
  end if;

  -- 2. Sign-up coercion. Each INSERT is a real sign-up as far as the trigger
  --    can tell; a raise here would be a sign-up that rolled back.
  for i in 1 .. array_length(metas, 1) loop
    v_id := gen_random_uuid();
    insert into auth.users (instance_id, id, aud, role, email, encrypted_password,
                            raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
    values ('00000000-0000-0000-0000-000000000000', v_id, 'authenticated', 'authenticated',
            'country-test+' || v_id || '@example.invalid', '',
            '{}', metas[i], now(), now());

    select country into v_got from public.profiles where id = v_id;
    n := n + 1;
    if not found or v_got is distinct from expected[i] then
      raise exception 'FAIL country_on_accounts — sign-up metadata % left country % '
        '(expected %)', left(metas[i]::text, 40), v_got, expected[i];
    end if;
    v_reader := v_id;  -- any of these is an ordinary reader for part 3
  end loop;

  -- 3. Who may count. Fixtures: an admin, and an Account with no Profile row.
  insert into auth.users (instance_id, id, aud, role, email, encrypted_password,
                          raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
  values ('00000000-0000-0000-0000-000000000000', v_admin, 'authenticated', 'authenticated',
          'country-test+' || v_admin || '@example.invalid', '', '{}', '{}', now(), now()),
         ('00000000-0000-0000-0000-000000000000', v_orphan, 'authenticated', 'authenticated',
          'country-test+' || v_orphan || '@example.invalid', '', '{}', '{}', now(), now());
  update public.profiles set role = 'admin' where id = v_admin;
  delete from public.profiles where id = v_orphan;
  select count(*) into v_total from auth.users;

  -- (a) Signed out: no claims, so auth.uid() is NULL.
  n := n + 1;
  begin
    perform public.accounts_by_country();
    raise exception 'FAIL country_on_accounts — a signed-out caller got counts';
  exception when sqlstate '42501' then
    if sqlerrm <> 'an enabled administrator is required' then raise; end if;
  end;

  set local role authenticated;

  -- (b) An ordinary reader.
  perform set_config('request.jwt.claims',
                     json_build_object('sub', v_reader::text)::text, true);
  n := n + 1;
  begin
    perform public.accounts_by_country();
    raise exception 'FAIL country_on_accounts — a reader got counts';
  exception when sqlstate '42501' then
    if sqlerrm <> 'an enabled administrator is required' then raise; end if;
  end;

  -- (c) An enabled admin: one row per country, adding up to every Account.
  perform set_config('request.jwt.claims',
                     json_build_object('sub', v_admin::text)::text, true);
  n := n + 1;
  select sum(count) into v_sum from public.accounts_by_country();
  if v_sum is distinct from v_total then
    raise exception 'FAIL country_on_accounts — counts add up to %, but there are % '
      'Accounts (an Account without a Profile must land in the NULL row)', v_sum, v_total;
  end if;

  n := n + 1;
  if (select count from public.accounts_by_country() where country = 'SA') < 3 then
    raise exception 'FAIL country_on_accounts — the three SA sign-ups above are not counted';
  end if;

  -- (d) The same admin, disabled.
  reset role;
  update public.profiles set is_disabled = true where id = v_admin;
  set local role authenticated;
  perform set_config('request.jwt.claims',
                     json_build_object('sub', v_admin::text)::text, true);
  n := n + 1;
  begin
    perform public.accounts_by_country();
    raise exception 'FAIL country_on_accounts — a disabled admin got counts';
  exception when sqlstate '42501' then
    if sqlerrm <> 'an enabled administrator is required' then raise; end if;
  end;

  reset role;
  raise exception 'PASS country_on_accounts.test.sql — % assertions', n;
end
$$;
