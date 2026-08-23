-- Bulk conversation deletion (docs/profile-refactor-plan.md Step 7).
-- ---------------------------------------------------------------------------
-- Named distinctly from account deletion (Spec 4, not built here): this
-- clears a reader's chat history and leaves the account itself, its profile
-- row, and its auth identity untouched.
--
-- One statement, one round trip, same reasoning chat_delete_session already
-- gives for existing as an RPC rather than a browser-direct delete: Flask
-- must clear its own process-local ConversationStore windows for every
-- session it just deleted, or a stray in-flight write recreates one via
-- chat_append_turn's `on conflict (id) do nothing`. A loop of N
-- chat_delete_session calls from Flask would do the same job non-atomically,
-- in N round trips instead of one — this is the one-round-trip version of
-- exactly that loop.

create or replace function public.chat_delete_all_sessions(
  p_owner_id uuid
)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_count integer;
begin
  if p_owner_id is null then
    raise exception 'chat_delete_all_sessions requires an owner id';
  end if;

  delete from public.chat_sessions
   where owner_id = p_owner_id;

  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

comment on function public.chat_delete_all_sessions(uuid) is
  'Delete every owned conversation and, by cascade, their messages and '
  'sources. Returns the number of sessions deleted. Same grant posture as '
  'chat_delete_session: service_role only, browser never reaches this.';

revoke execute on function public.chat_delete_all_sessions(uuid)
  from anon, authenticated, public;
grant execute on function public.chat_delete_all_sessions(uuid)
  to service_role;
