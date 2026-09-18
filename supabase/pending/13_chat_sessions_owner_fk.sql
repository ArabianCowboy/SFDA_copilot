-- > [!CAUTION]
-- > PARKED — DO NOT APPLY. This file is written so the ordering is
-- > unambiguous (highest ordinal in supabase/pending/), NOT so it can land.
-- > It must NOT be applied until at least one real deletion has completed
-- > end to end through the saga (07-12). Before it ever lands, run the
-- > orphan check below; ANY HIT IS AN INCIDENT — a transcript whose owner
-- > resolves to nothing — not a row to force, delete, or backfill. Find why
-- > the saga left it before touching this file again.
--
-- Migration M6 of docs/account-and-trust-plan.md §3: `chat_sessions.owner_id`
-- gains its foreign key, `ON DELETE RESTRICT`.
--
-- WHY RESTRICT, AND WHY IT WAS MISSING. The base migration
-- (20260820131914_chat_session_persistence.sql:37-42) left owner_id without
-- an FK on the grounds that "an FK brings ON DELETE CASCADE with it" — which
-- is not true (supabase/README.md rule 8); NO ACTION or RESTRICT keeps every
-- conversation and makes an orphan impossible. RESTRICT (rather than NO
-- ACTION) because the check must not be deferrable past the purge: with the
-- saga purging transcripts BEFORE the GoTrue delete, RESTRICT turns any
-- ordering bug into a loud 23503 instead of a silent orphan.
--
-- WHY PARKED. RESTRICT makes deleting an account fail with 23503 while any
-- session row survives. Until the saga is proven, that failure lands on a
-- real reader's deletion with no proven driver to clear it. The saga purges
-- first and deletes the provider user second, which is exactly the order
-- RESTRICT demands — but the order is unproven until it has run for real.
--
-- ORPHAN CHECK — run first, on the live database, before ever applying:
--
--   select s.id, s.owner_id
--     from public.chat_sessions s
--     left join public.profiles p on p.id = s.owner_id
--    where p.id is null;
--
-- Any row returned is an incident, not cleanup. (Note the join is to
-- profiles, not auth.users: service_role reaches auth.users nowhere —
-- supabase/README.md — and the saga deletes the profile row through the
-- GoTrue cascade, so profiles is the correct orphan test.)
--
-- `NOT VALID` then a separate `VALIDATE` (see 06 for why the split), under
-- `SET LOCAL lock_timeout` — chat_sessions is written by every completed
-- turn.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction.
--
-- APPLY NOTE (for when it is UNPARKED, not now): apply with
-- apply_migration, read the real version back from list_migrations, then
-- `git mv` it into supabase/migrations/ under that name. Until then it
-- stays exactly where it is.

set local lock_timeout = '3s';

alter table public.chat_sessions
  add constraint chat_sessions_owner_fk
  foreign key (owner_id) references public.profiles(id) on delete restrict
  not valid;

alter table public.chat_sessions
  validate constraint chat_sessions_owner_fk;
