-- A repeat sign-up email clears an unconfirmed account's password; nothing else does.
-- ===========================================================================
-- Protects the trigger public.clear_password_on_repeat_signup_email on
-- auth.users (pre-registration takeover, repeat-sign-up case). Read its
-- migration's header for why it exists and what it does NOT cover.
--
-- THE UPDATES COPY GoTrue's ORDER, read from supabase/auth master on
-- 2026-11-26: signupNewUser INSERTs with confirmation_sent_at NULL, then
-- sendConfirmation UPDATEs confirmation_token + confirmation_sent_at (the
-- first email). A repeat sign-up or /resend runs that same UPDATE again.
-- User.Confirm UPDATEs email_confirmed_at only. UpdatePassword (an admin
-- password set, which web/services/auth_admin.py revoke_sessions uses) writes
-- the password and NULLs confirmation_sent_at in the same UPDATE.
-- now() is fixed for the transaction, so each "new email" adds an interval.
--
-- THE FIXTURE IS SYNTHETIC: one auth.users row on an unroutable address. Its
-- INSERT also fires copilot's on_auth_user_created, which is asserted too:
-- both triggers sit on this table and either one failing blocks sign-up.
--
-- THIS FILE WRITES ROWS and drops the trigger at the end (proving the
-- rollback line works without owning auth.users). Everything is rolled back
-- by the closing `raise`. Do not remove that raise. It holds a brief lock on
-- auth.users while it runs.
--
-- Run: paste into execute_sql. Read the word after P0001 — PASS or FAIL.
-- See supabase/tests/README.md.

do $$
declare
  n int := 0;
  v_id uuid := gen_random_uuid();
  v_pw text;
begin
  n := n + 1;
  if not exists (select 1 from pg_trigger
                  where tgrelid = 'auth.users'::regclass
                    and tgname = 'clear_password_on_repeat_signup_email') then
    raise exception 'FAIL repeat_signup_password — trigger is not installed';
  end if;

  -- Sign-up: inserted with no email sent yet.
  insert into auth.users (instance_id, id, aud, role, email, encrypted_password,
                          raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
  values ('00000000-0000-0000-0000-000000000000', v_id, 'authenticated', 'authenticated',
          'repeat-signup-test+' || v_id || '@example.invalid', 'hash-a',
          '{}', '{}', now(), now());

  n := n + 1;
  if not exists (select 1 from public.profiles where id = v_id) then
    raise exception 'FAIL repeat_signup_password — profile trigger did not create the profile row';
  end if;

  -- First email: kept.
  update auth.users set confirmation_token = 't1', confirmation_sent_at = now()
   where id = v_id;
  select encrypted_password into v_pw from auth.users where id = v_id;
  n := n + 1;
  if v_pw is distinct from 'hash-a' then
    raise exception 'FAIL repeat_signup_password — first email changed the password (%)', v_pw;
  end if;

  -- An unrelated update (sign-in attempts, metadata): kept.
  update auth.users set updated_at = now() + interval '1 second' where id = v_id;
  select encrypted_password into v_pw from auth.users where id = v_id;
  n := n + 1;
  if v_pw is distinct from 'hash-a' then
    raise exception 'FAIL repeat_signup_password — an unrelated update changed the password (%)', v_pw;
  end if;

  -- Admin password set (UpdatePassword NULLs the sent time): the new one is kept.
  update auth.users set encrypted_password = 'hash-b', confirmation_token = '',
                        confirmation_sent_at = null
   where id = v_id;
  select encrypted_password into v_pw from auth.users where id = v_id;
  n := n + 1;
  if v_pw is distinct from 'hash-b' then
    raise exception 'FAIL repeat_signup_password — an admin password set was overwritten (%)', v_pw;
  end if;

  -- Next email after that NULL counts as a first email again: kept.
  update auth.users set confirmation_token = 't2',
                        confirmation_sent_at = now() + interval '2 minutes'
   where id = v_id;
  select encrypted_password into v_pw from auth.users where id = v_id;
  n := n + 1;
  if v_pw is distinct from 'hash-b' then
    raise exception 'FAIL repeat_signup_password — first email after an admin set changed the password (%)', v_pw;
  end if;

  -- Repeat sign-up / resend (a second email): cleared.
  update auth.users set confirmation_token = 't3',
                        confirmation_sent_at = now() + interval '4 minutes'
   where id = v_id;
  select encrypted_password into v_pw from auth.users where id = v_id;
  n := n + 1;
  if v_pw is not null then
    raise exception 'FAIL repeat_signup_password — a second email left the password set (%)', v_pw;
  end if;

  -- A password written without a new email (sent time unchanged): kept.
  update auth.users set encrypted_password = 'hash-c' where id = v_id;
  select encrypted_password into v_pw from auth.users where id = v_id;
  n := n + 1;
  if v_pw is distinct from 'hash-c' then
    raise exception 'FAIL repeat_signup_password — a password write with no email was cleared (%)', v_pw;
  end if;

  -- Confirmation (email_confirmed_at only, sent time unchanged): kept.
  update auth.users set email_confirmed_at = now() + interval '5 minutes' where id = v_id;
  select encrypted_password into v_pw from auth.users where id = v_id;
  n := n + 1;
  if v_pw is distinct from 'hash-c' then
    raise exception 'FAIL repeat_signup_password — confirmation changed the password (%)', v_pw;
  end if;

  -- A confirmed account getting another email: never touched.
  update auth.users set confirmation_token = 't4',
                        confirmation_sent_at = now() + interval '6 minutes'
   where id = v_id;
  select encrypted_password into v_pw from auth.users where id = v_id;
  n := n + 1;
  if v_pw is distinct from 'hash-c' then
    raise exception 'FAIL repeat_signup_password — a confirmed account lost its password (%)', v_pw;
  end if;

  -- The documented rollback works for postgres, which does not own auth.users.
  drop function public.clear_password_on_repeat_signup_email() cascade;
  n := n + 1;
  if exists (select 1 from pg_trigger
              where tgrelid = 'auth.users'::regclass
                and tgname = 'clear_password_on_repeat_signup_email') then
    raise exception 'FAIL repeat_signup_password — drop function cascade left the trigger behind';
  end if;

  raise exception 'PASS repeat_signup_password.test.sql — % assertions', n;
end
$$;
