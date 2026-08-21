-- ---------------------------------------------------------------------------
-- chat_load_session — replace the per-row correlated jsonb_agg subquery with
-- a single batched fetch of chat_message_sources for the whole window.
-- ---------------------------------------------------------------------------
-- TODO.md recorded this as a known N+1 wearing SQL clothing: up to 200
-- independent jsonb_agg builds per call (one per message in the hydration
-- window), which mattered once step 6 made hydration user-triggered (every
-- reload/language toggle/sign-in), not once-per-process.
--
-- Body-only change. Parameter list and `returns table (...)` shape are
-- byte-identical to the definition in
-- 20260820131914_chat_session_persistence.sql:533-600, so CREATE OR REPLACE
-- is correct and sufficient — unlike chat_append_turn's drop+create in
-- 20260821145416_chat_first_turn_title.sql, which had to change the argument
-- list. Grants below are unchanged and restated only for clarity; CREATE OR
-- REPLACE preserves them automatically. No new index: chat_message_sources'
-- only index, the unique constraint on (message_id, source_index), already
-- leads with message_id and serves this batched fetch.
--
-- Live-verified in a rolled-back transaction on this project before applying:
-- the old body's aggregate SubPlan executed with loops=200 (once per window
-- row) — the N+1 signature.
--
-- NOTE: the join form this migration ships (a plain `join window_rows` inside
-- the sources_by_message CTE) turned out to be a performance regression, not
-- a fix — see the immediately following migration,
-- chat_load_session_batch_sources_fix_join_form, which corrects it and
-- records the EXPLAIN evidence for both forms. Kept here, unmodified, as the
-- accurate history of what was actually applied and in what order; the fix
-- migration is what the live function's body reflects going forward.
create or replace function public.chat_load_session(
  p_owner_id   uuid,
  p_session_id uuid,
  p_limit      integer default 50,
  p_before_seq bigint default null
)
returns table (
  message_id      uuid,
  seq             bigint,
  role            text,
  content         text,
  created_at      timestamptz,
  corpus_revision text,
  model           text,
  lang            text,
  category        text,
  sources         jsonb
)
language sql
stable
security definer
set search_path = ''
as $$
  with window_rows as (
    select m.*
      from public.chat_messages m
     where m.owner_id = p_owner_id
       and m.session_id = p_session_id
       and (p_before_seq is null or m.seq < p_before_seq)
     order by m.seq desc
     limit greatest(1, least(coalesce(p_limit, 50), 200))
  ),
  sources_by_message as (
    select src.message_id,
           jsonb_agg(
             jsonb_build_object(
               'source_index',   src.source_index,
               'cited',          src.cited,
               'document',       src.document,
               'page',           src.page,
               'category',       src.category,
               'score',          src.score,
               'semantic_score', src.semantic_score,
               'lexical_score',  src.lexical_score,
               'chunk_id',       src.chunk_id,
               'snippet',        src.snippet
             ) order by src.source_index
           ) as sources
      from public.chat_message_sources src
      join window_rows w on w.id = src.message_id
     group by src.message_id
  )
  select w.id,
         w.seq,
         w.role,
         w.content,
         w.created_at,
         w.corpus_revision,
         w.model,
         w.lang,
         w.category,
         coalesce(s.sources, '[]'::jsonb)
    from window_rows w
    left join sources_by_message s
      on s.message_id = w.id
   order by w.seq;
$$;

revoke execute on function public.chat_load_session(uuid, uuid, integer, bigint)
  from anon, authenticated, public;
grant execute on function public.chat_load_session(uuid, uuid, integer, bigint)
  to service_role;
