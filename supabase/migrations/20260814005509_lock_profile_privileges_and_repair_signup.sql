-- 0001 · Lock the privilege columns on public.profiles, and repair signup.
--
-- WHY THIS IS URGENT
-- ------------------
-- `authenticated` holds column-level UPDATE on public.profiles.role, and the
-- "Users can update own profile" policy is USING (auth.uid() = id) with no
-- WITH CHECK — so Postgres reuses USING as the check, and changing `role` does
-- not change `id`. The anon key is published in the page and the app already
-- calls .upsert({ id, ... }) on this table, so any signed-in reader could run:
--
--     supabase.from('profiles').upsert({ id: myUserId, role: 'admin' })
--
-- That is inert only for as long as no code reads `role`. The admin console
-- reads it, so this migration must land before that code, not after.
--
-- RLS CANNOT FIX THIS. Policies are row-granular, not column-granular. The
-- control is a column-level REVOKE (primary) plus a trigger (defence in depth,
-- because Supabase re-grants table privileges on some schema operations).
--
-- WHY SIGNUP IS ALSO REPAIRED HERE
-- --------------------------------
-- handle_new_user currently inserts into public.users and then public.profiles.
-- public.users is empty, has no FK to auth.users, and is read by no application
-- code (verified by grep across *.py/*.js/*.html/*.yaml). The trigger is
-- rewritten below to stop referencing it, which is what makes the table
-- droppable; the drop itself is migration 0002.
--
-- The trigger was introduced 2025-12-07; the most recent signup was 2025-11-16.
-- It has therefore never fired. It is untested rather than known-broken, and it
-- is tested live immediately after this migration is applied.
--
-- The 2025-11-16 account has no profiles row at all — created under the earlier
-- trigger that the 2025-12-07 migration was written to fix. It is backfilled.

-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction, and a nested COMMIT here would end that outer transaction early
-- and leave the rest of the file running unprotected.
--
-- ⚠ IF YOU ARE PASTING THIS INTO THE SUPABASE SQL EDITOR INSTEAD, wrap it:
-- put `begin;` on the first line and `commit;` on the last. Section 4 revokes
-- the table-level write grants before granting the columns back, so a run that
-- fails between those two statements leaves `authenticated` unable to save a
-- profile at all. Atomicity is what makes that window safe.

-- ---------------------------------------------------------------------------
-- 1. Signup trigger: profiles only, idempotent, pinned search_path.
-- ---------------------------------------------------------------------------
-- `on conflict (id) do nothing` so a retried or replayed insert cannot abort
-- signup: a raise in an AFTER INSERT trigger on auth.users rolls back the
-- account creation itself, which turns a duplicate row into a failed signup.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, full_name, role, organization, specialization, preferences)
  values (
    new.id,
    new.raw_user_meta_data ->> 'full_name',
    'user',
    '',
    '',
    '{"theme": "system"}'::jsonb
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

-- Postgres grants EXECUTE to PUBLIC by default on CREATE OR REPLACE, which
-- silently undoes migration 20260813101747. Re-revoke.
revoke execute on function public.handle_new_user() from anon, authenticated, public;

-- public.users is NOT dropped here. Rewriting the trigger above is what makes
-- it droppable — nothing references it any more — but a destructive change does
-- not belong in the same migration as a security fix that must be applied
-- promptly and without hesitation. It gets its own migration, 0002.

-- ---------------------------------------------------------------------------
-- 2. Identity columns on profiles.
-- ---------------------------------------------------------------------------
alter table public.profiles
  add column if not exists tier            text        not null default 'free',
  add column if not exists is_disabled     boolean     not null default false,
  add column if not exists disabled_at     timestamptz,
  add column if not exists disabled_by     uuid references auth.users(id),
  add column if not exists disabled_reason text,
  add column if not exists last_seen_at    timestamptz;

-- Every FK gets its index in the migration that creates it. Partial, because
-- the overwhelming majority of rows will never have a value here.
create index if not exists profiles_disabled_by_idx
  on public.profiles (disabled_by) where disabled_by is not null;

-- Backfill before adding the CHECK, so a null role cannot fail the constraint.
update public.profiles set role = 'user' where role is null;

alter table public.profiles
  alter column role set default 'user',
  alter column role set not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.profiles'::regclass and conname = 'profiles_role_chk'
  ) then
    alter table public.profiles
      add constraint profiles_role_chk check (role in ('user', 'admin'));
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- 3. Backfill the auth.users rows that never got a profile.
-- ---------------------------------------------------------------------------
insert into public.profiles (id, full_name, role, organization, specialization, preferences)
select u.id,
       u.raw_user_meta_data ->> 'full_name',
       'user',
       '',
       '',
       '{"theme": "system"}'::jsonb
from auth.users u
left join public.profiles p on p.id = u.id
where p.id is null;

-- ---------------------------------------------------------------------------
-- 4. THE LOCK. Column-level privileges.
-- ---------------------------------------------------------------------------
-- A column-level REVOKE is a no-op while a table-level grant exists, so the
-- table-level write grants are revoked first and only the reader-owned columns
-- are granted back. `id` is included in the INSERT grant because the client
-- writes via .upsert({ id, ... }), which is INSERT ... ON CONFLICT UPDATE.
--
-- SELECT is deliberately left table-wide: reading your own role is harmless,
-- and narrowing it would break the existing profile read for no security gain.
revoke insert, update on public.profiles from authenticated, anon;

grant insert (id, full_name, organization, specialization, preferences)
  on public.profiles to authenticated;

-- `id` is granted on UPDATE as well, because PostgREST's upsert emits
-- ON CONFLICT DO UPDATE SET for every column in the payload — including id —
-- and a missing privilege there would break the shipped profile save. It is
-- safe: the row policy is USING (auth.uid() = id) with no WITH CHECK, so
-- Postgres reuses USING as the check and a row whose id moved to someone else
-- fails it.
grant update (id, full_name, organization, specialization, preferences)
  on public.profiles to authenticated;

-- anon never writes a profile: signup goes through the SECURITY DEFINER trigger
-- above, which runs as the function owner rather than as the caller.

-- ---------------------------------------------------------------------------
-- 5. Defence in depth: reject privilege changes from the browser-facing roles.
-- ---------------------------------------------------------------------------
-- Deny-list rather than allow-list, deliberately: `authenticated` and `anon`
-- are the two roles a browser can ever hold, and an allow-list would risk
-- locking out migration tooling or a future internal role.
-- SECURITY INVOKER (the default) is load-bearing here. Inside a SECURITY
-- DEFINER function `current_user` is the function's *owner*, so the check
-- below would compare the owner against 'authenticated' and never fire.
-- PostgREST applies SET LOCAL ROLE, so an invoker-rights function sees the
-- real caller. A trigger function needs no elevated rights to raise, and the
-- firing role does not need EXECUTE on it.
create or replace function public.profiles_guard_privilege_columns()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if current_user in ('authenticated', 'anon') and (
       new.role        is distinct from old.role
    or new.tier        is distinct from old.tier
    or new.is_disabled is distinct from old.is_disabled
  ) then
    raise exception
      'profiles.role, profiles.tier and profiles.is_disabled are administered server-side'
      using errcode = '42501';
  end if;
  return new;
end;
$$;

revoke execute on function public.profiles_guard_privilege_columns() from anon, authenticated, public;

drop trigger if exists profiles_guard_privilege_columns on public.profiles;
create trigger profiles_guard_privilege_columns
  before update on public.profiles
  for each row execute function public.profiles_guard_privilege_columns();


