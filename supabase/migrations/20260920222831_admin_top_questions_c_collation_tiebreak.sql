-- admin_top_questions: break ties on the key in "C" order, not the database's.
-- ===========================================================================
-- Plan: docs/admin-analytics-v1-plan.md, "Third review (2026-09-21)".
--
-- THE ONE CHANGE. `order by <count> desc, s.normalized` tie-broke under the
-- database collation (en_US.UTF-8), which ignores spaces and hyphens at the
-- primary level: 'a-b' < 'ab' < 'a b c' there, 'a b c' < 'a-b' < 'ab' by code
-- point. The in-memory double sorts by code point and cannot imitate glibc.
-- That matters more than ordering usually does, because on a small population
-- most groups sit at two or three asks, so twenty-plus rows tie and the
-- tie-break decides WHICH rows survive `limit` -- production and the demo
-- returned different sets of twenty. `collate "C"` is code-point order, which
-- both sides can hold. Everything else in the body is unchanged from
-- 20260920192411, and `create or replace` keeps its ACL and its comment.
--
-- WHY THIS FILE IS A DO BLOCK WITH @U PLACEHOLDERS. The transport that applies
-- migrations to this project decodes every backslash-u escape in a statement
-- into the raw character. 20260920192411 was applied through it, so the
-- statement recorded in supabase_migrations.schema_migrations for that version
-- carries raw zero-width characters and is NOT the file of the same name; the
-- live function was repaired by hand the same hour, and that repair was in no
-- file. This file ends that: it contains no backslash-u sequence for a
-- transport to decode -- the backslash is built from chr(92) on the server --
-- so what is recorded IS this file, and replaying the two files in order on a
-- fresh database reproduces the live function exactly. After applying, check
-- prosrc holds zero non-ASCII characters.

do $do$
begin
  execute replace($f$
create or replace function public.admin_top_questions(
  p_days       integer default 30,
  p_lang       text    default null,
  p_category   text    default null,
  p_min_askers integer default 2,
  p_limit      integer default 20,
  p_order      text    default 'asks'     -- 'asks' | 'uncited'
)
returns table (
  question text,    -- the most recent raw phrasing in the group, not the key
  asks     bigint,  -- saved turns
  uncited  bigint,  -- turns in this group whose answer cited nothing
  askers   bigint   -- distinct accounts, NULL below 5: bucketed HERE, not in the UI
)
language sql
stable
security definer
set search_path = ''
as $$
  with turns as (
    select a.id as assistant_id, a.owner_id, a.created_at,
           u.content as question,
           pg_catalog.regexp_replace(
             pg_catalog.btrim(pg_catalog.regexp_replace(
               pg_catalog.lower(pg_catalog.regexp_replace(
                 u.content, '[@U200B-@U200F@U2066-@U2069@UFEFF]', '', 'g')),
               '[\s@U00A0@U1680@U2000-@U200A@U202F@U205F@U3000]+', ' ', 'g')),
             '[?!.@U061F@U06D4@U2026 ]+$', '') as normalized
      from public.chat_messages a
      join public.chat_messages u
        on  u.session_id        = a.session_id
        and u.client_request_id = a.client_request_id
        and u.role              = 'user'
     where a.role = 'assistant'
       and a.created_at >= pg_catalog.now() - pg_catalog.make_interval(
             days => greatest(least(coalesce(p_days, 30), 3650), 7))
       and (p_lang     is null or a.lang     = p_lang)
       and (p_category is null or a.category = p_category)
  ),
  scored as (
    select t.*,
           (select count(*) filter (where s.cited)
              from public.chat_message_sources s
             where s.message_id = t.assistant_id) as cited_count
      from turns t
  )
  select (array_agg(s.question order by s.created_at desc))[1],
         count(*),
         count(*) filter (where s.cited_count = 0),
         case when count(distinct s.owner_id) >= 5
              then count(distinct s.owner_id) end
    from scored s
   group by s.normalized
  having count(distinct s.owner_id) >= greatest(coalesce(p_min_askers, 2), 2)
   order by case when p_order = 'uncited'
                 then count(*) filter (where s.cited_count = 0)
                 else count(*) end desc,
            s.normalized collate "C"
   limit greatest(least(coalesce(p_limit, 20), 100), 1);
$$
$f$, '@U', chr(92) || 'u');
end
$do$;
