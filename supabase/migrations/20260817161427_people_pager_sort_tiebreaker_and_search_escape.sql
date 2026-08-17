-- Two of the three fixes from docs/pagination-implementation-roadmap.md §7 for the admin
-- People-tab pager. The third (a pg_trgm GIN index on auth.users.email) is NOT included
-- here: `create index ... on auth.users` failed with `42501: must be owner of table users`
-- when first attempted in this same migration. auth.users is owned by supabase_auth_admin
-- on this hosted project, and the postgres migration role is not a member of that role
-- (verified: no pg_auth_members row grants it), so it cannot create an index on that table
-- by design — this is Supabase's own auth-schema protection, not a bug to work around here.
-- Tracked as a follow-up requiring either a Supabase-support-granted privilege or a
-- profiles-table email denormalization; not attempted in this migration. At today's row
-- count (4 accounts) the existing sequential scan costs low single-digit milliseconds
-- regardless (see roadmap §1's volume/latency table), so this is safe to defer.
--
-- 1. Deterministic ordering: created_at alone is not unique, so two accounts created in
--    the same millisecond produced non-deterministic ordering across page boundaries.
-- 2. Literal-substring search: p_search containing SQL wildcard characters (%, _) matched
--    unintended rows. Escaped so search is always literal. The escape character itself
--    (backslash) must be escaped first, or a literal backslash in a search term raises
--    Postgres SQLSTATE 22025 (invalid escape sequence) as an unhandled 500.

create or replace function public.admin_list_users(
  p_limit  int default 50,
  p_offset int default 0,
  p_search text default null
)
returns table (
  id              uuid,
  email           text,
  role            text,
  tier            text,
  is_disabled     boolean,
  disabled_at     timestamptz,
  disabled_reason text,
  created_at      timestamptz,
  last_sign_in_at timestamptz,
  total           bigint
)
language sql
security definer
set search_path = ''
as $$
  with matched as (
    select u.id, u.email::text as email,
           coalesce(p.role, 'user')      as role,
           coalesce(p.tier, 'free')      as tier,
           coalesce(p.is_disabled, false) as is_disabled,
           p.disabled_at, p.disabled_reason,
           u.created_at, u.last_sign_in_at
    from auth.users u
    left join public.profiles p on p.id = u.id
    where p_search is null
       or p_search = ''
       or u.email::text ilike '%' || replace(replace(replace(
            p_search, '\', '\\'), '%', '\%'), '_', '\_') || '%' escape '\'
  )
  select m.*, (select count(*) from matched) as total
  from matched m
  order by m.created_at desc, m.id desc
  limit greatest(least(p_limit, 200), 1)
  offset greatest(p_offset, 0);
$$;

revoke execute on function public.admin_list_users(int, int, text)
  from anon, authenticated, public;
