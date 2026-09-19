-- A durable per-account throttle on deletion step-up re-authentication.
--
-- WHY THIS EXISTS
-- ---------------
-- Requesting account deletion requires step-up: the reader re-enters their
-- current password and `_verify_current_password` (web/api/account.py) checks
-- it by calling GoTrue's sign-in SERVER-SIDE. That is the only
-- server-verifiable step-up this stack offers — the password-change nonce is
-- consumed by GoTrue's `updateUser` in the browser and Flask cannot see it.
--
-- But it reintroduces the shape this repository already removed once.
-- `POST /auth/login` answers 410 because the server-side route "forwarded the
-- caller's traffic to GoTrue from this host's single address, blinding
-- GoTrue's own per-IP /token limiter to the attacker's real address"
-- (docs/ARCHITECTURE.md:345-352). Every step-up guess now arrives at GoTrue
-- from the VPS's one address.
--
-- The Flask limiter in front of it (`account_deletion_api`, 3/hour, keyed per
-- account) was the only thing bounding per-account guessing — and it is
-- `memory://`, so its counters reset on every worker recycle. The production
-- unit sets `--max-requests 1000` (deploy/sfda-copilot.service), so recycles
-- are routine. The durable throttle was GoTrue's, and the server-side call is
-- what blinds it. This table is the durable throttle put back, on our side.
--
-- WHAT IT DELIBERATELY DOES NOT STORE
-- -----------------------------------
-- UUIDs, counts and timestamps ONLY — the same rule the deletion ledger
-- follows (see 07's header). No email, no IP, no user agent, and above all no
-- password and no hash of one. A throttle that leaks the thing it protects is
-- worse than no throttle.
--
-- WHY ONE STATEMENT, NOT READ-THEN-WRITE
-- --------------------------------------
-- Eight threads share this worker. A check that SELECTs the count and then
-- UPDATEs it lets two concurrent requests both read "not locked" and both
-- proceed, which is exactly the burst a guesser wants. `record_step_up_failure`
-- is a single upsert with the decision in its RETURNING clause, so the row
-- lock serialises them and the second caller sees the first one's increment.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction.
--
-- APPLY NOTE: lives in supabase/pending/ (see supabase/README.md). Apply with
-- apply_migration, read the real version back from list_migrations, then
-- `git mv` it into supabase/migrations/ under that name. It has no dependency
-- on the rest of this batch and may be applied at any point.

create table public.step_up_attempts (
  user_id       uuid primary key,
  failure_count integer     not null default 0,
  window_opened timestamptz not null default now(),
  locked_until  timestamptz
);

comment on table public.step_up_attempts is
  'Durable per-account step-up failure counter. UUIDs, counts and timestamps '
  'only (D3). Survives the worker recycles that clear the memory:// limiter.';

alter table public.step_up_attempts enable row level security;
-- No policies, deliberately: every reader and writer is a security definer RPC
-- below. A policy is how you would let the browser in, and nothing in a
-- browser has any business here.

revoke all on table public.step_up_attempts from anon, authenticated, public;

-- The window and the threshold, named once so they are easy to find and change
-- together. Five failures in fifteen minutes locks the account out for fifteen.
--
-- Five, not three: the Flask limit already refuses at 3/hour whenever the
-- worker has not recycled, so this is the floor that holds when it has, and it
-- should not be tighter than the control it backstops or an honest reader who
-- mistypes twice across two recycles gets locked out by the safety net rather
-- than the rule. Fifteen minutes because the cost of a lockout falls entirely
-- on the legitimate owner — a guesser simply waits — so the value of a longer
-- one is small and its cost is a support request.
create function public.record_step_up_failure(p_owner_id uuid)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_window   interval := interval '15 minutes';
  v_max      integer  := 5;
  v_lockout  interval := interval '15 minutes';
  v_locked   boolean;
begin
  if p_owner_id is null then
    raise exception 'an owner id is required' using errcode = '22023';
  end if;

  -- One statement. The upsert takes the row lock, so a second thread arriving
  -- concurrently blocks here and then sees this increment rather than racing
  -- past a stale read.
  insert into public.step_up_attempts as a (user_id, failure_count, window_opened)
  values (p_owner_id, 1, now())
  on conflict (user_id) do update
     set failure_count = case
           when a.window_opened < now() - v_window then 1
           else a.failure_count + 1
         end,
         window_opened = case
           when a.window_opened < now() - v_window then now()
           else a.window_opened
         end,
         locked_until = case
           when (case
                   when a.window_opened < now() - v_window then 1
                   else a.failure_count + 1
                 end) >= v_max then now() + v_lockout
           else a.locked_until
         end
  returning (a.locked_until is not null and a.locked_until > now()) into v_locked;

  return coalesce(v_locked, false);
end;
$$;

-- True while the account is locked out. Checked BEFORE the provider call, so a
-- locked-out caller produces no GoTrue round trip at all — which is the whole
-- point: an unbounded oracle is what blinds the provider's own limiter.
create function public.step_up_is_locked_out(p_owner_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.step_up_attempts a
     where a.user_id = p_owner_id
       and a.locked_until is not null
       and a.locked_until > now()
  );
$$;

-- A reader who mistypes twice and then succeeds must not stay penalised.
create function public.clear_step_up_failures(p_owner_id uuid)
returns void
language sql
security definer
set search_path = ''
as $$
  delete from public.step_up_attempts a where a.user_id = p_owner_id;
$$;

revoke execute on function public.record_step_up_failure(uuid) from anon, authenticated, public;
revoke execute on function public.step_up_is_locked_out(uuid) from anon, authenticated, public;
revoke execute on function public.clear_step_up_failures(uuid) from anon, authenticated, public;
grant execute on function public.record_step_up_failure(uuid) to service_role;
grant execute on function public.step_up_is_locked_out(uuid) to service_role;
grant execute on function public.clear_step_up_failures(uuid) to service_role;
