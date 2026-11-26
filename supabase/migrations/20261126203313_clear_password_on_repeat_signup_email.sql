-- Pre-registration takeover, repeat-sign-up case, for every app on this Auth
-- project (SFDA Copilot and Thaqib share it).
-- ===========================================================================
-- THE HOLE. GoTrue leaves an unconfirmed account's password alone when the
-- same address signs up again (signup.go: "we can't be sure of their claimed
-- identity") and only sends the confirmation email again. So if someone signs
-- up with another person's address first, their password would survive the
-- real owner's confirmation.
--
-- THE FIX. A second confirmation email to an unconfirmed account means its
-- password may be someone else's: clear it. Nobody can sign in before
-- confirming, so clearing at the second email is as safe as clearing at
-- confirmation. The owner sets a password with Forgot password. A /resend
-- request clears it too, because it cannot be told apart from a second
-- sign-up.
--
-- NOT COVERED: the owner (or a mail scanner) clicking the FIRST email, which
-- the attacker's sign-up sent, and a repeat sign-up refused with 429 (GoTrue
-- checks the limits before it writes confirmation_sent_at). Tracked in TODO.md.
--
-- WHY IT IS SHAPED THIS WAY
-- - The new sent time must be non-null: an admin password set (GoTrue's
--   UpdatePassword, used by revoke_sessions) NULLs it in the same UPDATE.
-- - Phone-only accounts are skipped: an SMS code also writes confirmation_sent_at.
-- - NULL, not '': GoTrue reads the column as *string and writes NULL itself
--   when it clears a password (ClearUnconfirmedPassword).
-- - Columns are read through to_jsonb and the trigger has no UPDATE OF / WHEN
--   list, so it records no dependency on auth.users columns: a GoTrue upgrade
--   that Supabase runs unattended can neither be blocked by it nor break it.
--   It fires on every auth.users update and does nothing unless all five
--   conditions hold.
-- - Touches only NEW, so no security definer.
--
-- ROLLBACK. postgres does not own auth.users (supabase_auth_admin does), so
-- DROP TRIGGER fails with 42501. This works (asserted by the test):
--   drop function public.clear_password_on_repeat_signup_email() cascade;
--
-- Test: supabase/tests/repeat_signup_password.test.sql.

create or replace function public.clear_password_on_repeat_signup_email()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  o jsonb := to_jsonb(old);
  n jsonb := to_jsonb(new);
begin
  if o ->> 'email_confirmed_at' is null
     and o ->> 'phone_confirmed_at' is null
     and o ->> 'confirmation_sent_at' is not null
     and n ->> 'confirmation_sent_at' is not null
     and n ->> 'confirmation_sent_at' is distinct from o ->> 'confirmation_sent_at'
  then
    new.encrypted_password := null;
  end if;
  return new;
end;
$$;

revoke all on function public.clear_password_on_repeat_signup_email()
  from anon, authenticated, service_role, public;

create trigger clear_password_on_repeat_signup_email
  before update on auth.users
  for each row
  execute function public.clear_password_on_repeat_signup_email();
