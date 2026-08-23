-- Extend the privilege-column guard to INSERT, and widen it to every
-- administered column, not just role/tier/is_disabled.
--
-- WHY BEFORE INSERT NEEDS ITS OWN BRANCH, NOT A DIFF AGAINST OLD
-- ----------------------------------------------------------------
-- profiles_guard_privilege_columns (20260814005509...sql:168-192) compares
-- `new.col is distinct from old.col`. On INSERT, `old` is NULL, so
-- `new.role = 'user'` -- the column default -- IS distinct from NULL and the
-- guard would raise on every ordinary signup/first-save row. The INSERT
-- branch below asserts literal values instead of diffing against a row that
-- does not exist yet. Getting this wrong rejects every new profile --
-- Services.updateProfile (services.js:677-684) is an upsert, so this is the
-- live path for the first save on any profile-less account.
--
-- WHY THE OTHER FOUR COLUMNS JOIN THE CHECK NOW
-- ----------------------------------------------
-- The original guard watched 3 of 7 administrative columns. Not exploitable
-- while the column grants hold -- Postgres rejects an ungranted column at
-- parse time -- but the trigger exists precisely because that migration's own
-- comment (line 17) says Supabase re-grants table privileges on some schema
-- operations. Closing the gap while defence-in-depth is already being
-- touched, per docs/profile-refactor-plan.md section 0.3-D / section 6 item 2.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction (20260814005509...sql:35-43).

create or replace function public.profiles_guard_privilege_columns()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    if current_user in ('authenticated', 'anon') and (
         new.role            <> 'user'
      or new.tier             <> 'free'
      or new.is_disabled
      or new.disabled_at      is not null
      or new.disabled_by      is not null
      or new.disabled_reason  is not null
      or new.last_seen_at     is not null
    ) then
      raise exception
        'profiles.role, tier, is_disabled, disabled_at, disabled_by, '
        'disabled_reason and last_seen_at are administered server-side'
        using errcode = '42501';
    end if;
    return new;
  end if;

  if current_user in ('authenticated', 'anon') and (
       new.role            is distinct from old.role
    or new.tier             is distinct from old.tier
    or new.is_disabled      is distinct from old.is_disabled
    or new.disabled_at      is distinct from old.disabled_at
    or new.disabled_by      is distinct from old.disabled_by
    or new.disabled_reason  is distinct from old.disabled_reason
    or new.last_seen_at     is distinct from old.last_seen_at
  ) then
    raise exception
      'profiles.role, tier, is_disabled, disabled_at, disabled_by, '
      'disabled_reason and last_seen_at are administered server-side'
      using errcode = '42501';
  end if;
  return new;
end;
$$;

revoke execute on function public.profiles_guard_privilege_columns()
  from anon, authenticated, public;

drop trigger if exists profiles_guard_privilege_columns on public.profiles;
create trigger profiles_guard_privilege_columns
  before insert or update on public.profiles
  for each row execute function public.profiles_guard_privilege_columns();
