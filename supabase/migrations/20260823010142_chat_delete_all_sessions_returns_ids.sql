-- chat_delete_all_sessions must return WHICH sessions it deleted, not merely
-- how many.
-- ---------------------------------------------------------------------------
-- Flask's process-local ConversationStore window survives a session row
-- being deleted (the same fact chat_delete_session's own comment states) and
-- must be cleared per id after the delete, or chat_append_turn's
-- `on conflict (id) do nothing` can resurrect a row a stray in-flight write
-- lands on. A bare count gives Flask nothing to clear. Returning the deleted
-- ids lets the caller do `delete then clear` in one round trip rather than
-- `list then delete then clear`, which would race a session created between
-- the list and the delete.
--
-- CREATE OR REPLACE cannot change a function's return type, so the prior
-- version (returns integer) is dropped first.

drop function if exists public.chat_delete_all_sessions(uuid);

create or replace function public.chat_delete_all_sessions(
  p_owner_id uuid
)
returns table (session_id uuid)
language sql
security definer
set search_path = ''
as $$
  delete from public.chat_sessions
   where owner_id = p_owner_id
  returning id;
$$;

comment on function public.chat_delete_all_sessions(uuid) is
  'Delete every owned conversation and, by cascade, their messages and '
  'sources. Returns the deleted session ids so Flask can clear its '
  'per-conversation ConversationStore windows. Same grant posture as '
  'chat_delete_session: service_role only, browser never reaches this.';

revoke execute on function public.chat_delete_all_sessions(uuid)
  from anon, authenticated, public;
grant execute on function public.chat_delete_all_sessions(uuid)
  to service_role;
