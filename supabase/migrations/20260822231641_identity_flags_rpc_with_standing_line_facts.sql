-- One RPC for everything /api/identity needs, including the two facts that
-- cannot come from public.profiles at all.
--
-- WHY THIS REPLACES A PLAIN TABLE READ
-- -------------------------------------
-- web/services/identity_cache.py's fetch_identity currently does
-- `.table('profiles').select('id, role, tier, is_disabled').eq('id', ...)`.
-- That covers role/tier/is_disabled, but the account page's standing line
-- also needs "since" (account age) and a conversation count, and neither can
-- come from that query:
--   * auth.users is unreachable through PostgREST at all -- confirmed by
--     20260814175551_account_detail.sql's own comment -- so created_at can
--     only be reached through a SECURITY DEFINER function.
--   * A conversation count needs chat_sessions, a second table, which a
--     single-table PostgREST select cannot join.
-- One RPC keeps this to the one round trip the current query already costs,
-- rather than adding a second one on every identity resolution.
--
-- Deliberately does NOT read first_name/family_name/age/organization/
-- specialization: this function backs an identity check used on every page,
-- not the account page's own profile read, and "says nothing a reader may
-- not know about themselves" (app.py's own docstring for /api/identity)
-- does not mean "says everything".
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction (20260814005509...sql:35-43).

create or replace function public.get_identity_flags(p_user_id uuid)
returns table (
  role                text,
  tier                text,
  is_disabled         boolean,
  created_at          timestamptz,
  conversation_count  integer
)
language sql
stable
security definer
set search_path = ''
as $$
  select
    p.role,
    p.tier,
    p.is_disabled,
    u.created_at,
    (select count(*)::integer
       from public.chat_sessions s
      where s.owner_id = p_user_id) as conversation_count
    from public.profiles p
    join auth.users u on u.id = p.id
   where p.id = p_user_id
$$;

revoke execute on function public.get_identity_flags(uuid)
  from anon, authenticated, public;
grant execute on function public.get_identity_flags(uuid) to service_role;
