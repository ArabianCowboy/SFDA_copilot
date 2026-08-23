-- chat_session_exists — the 404 that /c/<id> deep-linking needs
-- ===========================================================================
-- Plan: docs/per-tab-conversation-deep-linking-plan.md §3.3.
--
-- WHY THIS DID NOT EXIST BEFORE. `chat_load_session` (20260820131914) returns
-- zero rows for "not yours" and for "empty conversation" alike, and that was
-- harmless while the server always minted the id — a session Flask itself
-- just created is yours by construction, so the ambiguity was never
-- reachable. Once an id can arrive from a URL the two cases must diverge, or
-- a hostile or stale deep link renders as an ordinary empty conversation
-- instead of "not found".
--
-- ONE INDEXED LOOKUP, NO TIMING SKEW. `chat_sessions_pkey` on (id) plus the
-- `owner_id` filter is a single index probe either way — a foreign id, a
-- never-existed id and a deleted id all cost the same, which is what keeps
-- this from becoming an existence oracle by response time rather than by
-- response shape. Verified against the security review: no new leak, because
-- it mirrors the refusal shape `chat_load_session` and every RPC in
-- 20260821145319 already take.
--
-- `security definer` + `set search_path = ''` + owner filtering follows
-- 20260821145319's pattern exactly; execute is revoked from
-- anon/authenticated/public and granted to service_role only, matching
-- 20260820131914:597-599.
create or replace function public.chat_session_exists(
  p_owner_id   uuid,
  p_session_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
      from public.chat_sessions s
     where s.id = p_session_id
       and s.owner_id = p_owner_id
  );
$$;

comment on function public.chat_session_exists(uuid, uuid) is
  'Does this owner have a session by this id? The 404 discipline '
  '`GET /api/chat/history?c=<id>` needs once the id can arrive from a URL '
  'rather than always being server-minted. An unowned id answers false, '
  'identically to an absent one.';

revoke execute on function public.chat_session_exists(uuid, uuid)
  from anon, authenticated, public;
grant execute on function public.chat_session_exists(uuid, uuid)
  to service_role;
