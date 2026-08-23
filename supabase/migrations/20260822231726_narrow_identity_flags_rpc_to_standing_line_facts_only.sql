-- Narrow get_identity_flags to exactly the two facts nothing else already
-- has: created_at and conversation_count.
--
-- WHY THE NARROWER SHAPE
-- ------------------------
-- The first version of this function also returned role/tier/is_disabled,
-- duplicating web/services/identity_cache.py's IdentityFlags, which the
-- request path already resolves and caches (TTL'd, process-local, exactly
-- so a chat request costs no extra round trip -- see that module's own
-- docstring). Wiring this function into that cache would have put a
-- conversation-count subquery on every cached identity refresh, on the one
-- hot path that module exists to keep cheap.
--
-- Called only from GET /api/identity, once per sign-in per that route's own
-- docstring -- never from the per-request auth path.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction (20260814005509...sql:35-43).

drop function public.get_identity_flags(uuid);

create function public.get_identity_flags(p_user_id uuid)
returns table (
  created_at         timestamptz,
  conversation_count integer
)
language sql
stable
security definer
set search_path = ''
as $$
  select
    u.created_at,
    (select count(*)::integer
       from public.chat_sessions s
      where s.owner_id = p_user_id) as conversation_count
    from auth.users u
   where u.id = p_user_id
$$;

revoke execute on function public.get_identity_flags(uuid)
  from anon, authenticated, public;
grant execute on function public.get_identity_flags(uuid) to service_role;
