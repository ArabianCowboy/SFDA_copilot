-- ---------------------------------------------------------------------------
-- chat_load_session — correct the join form from the previous migration in
-- this same pass.
-- ---------------------------------------------------------------------------
-- The immediately preceding migration (chat_load_session_batch_sources)
-- replaced the N+1 with a plain `join window_rows w on w.id = src.message_id`
-- inside the sources_by_message CTE. Live EXPLAIN (ANALYZE, BUFFERS) on this
-- project, on a seeded 200-message/300-source window (100 assistant rows,
-- 3 sources each), showed the planner did NOT hash/merge-join it: it chose a
-- Nested Loop Left Join ("Inner Unique: true") that re-ran the GroupAggregate
-- over the ENTIRE window once per outer row (loops=200) instead of once
-- overall. Rows Removed by Join Filter: 14950 — not the naive 200*100-100 =
-- 19900 a uniform full-rescan-every-time model would predict, because "Inner
-- Unique: true" lets the 100 assistant-role outer rows stop as soon as they
-- hit their own matching group (averaging a partial scan each), while the
-- 100 user-role outer rows (no source group exists for them) still have to
-- exhaust every one of the ~100 groups before concluding no match. That mix
-- reconciles to ~14900, matching the observed 14950 within rounding — a
-- materially different mechanism from "discards a full rescan every time,"
-- worth stating precisely rather than glossing over: it is still a per-row
-- re-execution of the whole aggregate, just with early-exit on half the
-- rows, not a flat 200x cost. Buffers shared hit=712, Execution Time=
-- 530.316ms — WORSE than the original correlated-subquery N+1 it was meant
-- to fix (buffers=712 too, but 7.003ms).
--
-- The `= any(array(select id from window_rows))` form, tested in the same
-- rolled-back transaction against identical seed data, produced a single
-- InitPlan evaluation of window_rows, one Bitmap Index Scan against
-- chat_message_sources_unique_index for the whole id array, one GroupAggregate
-- pass (loops=1), and a Merge Left Join back onto window_rows. Buffers shared
-- hit=19, Execution Time=4.726ms. This is what ships.
--
-- Lesson recorded here because it contradicts the intuition that a plain JOIN
-- is "more idiomatic" than `= ANY(array(...))` for this pattern: the CTE
-- (window_rows) is not indexed and not materialized-and-reused the way a real
-- table would be, so a join against it can get planned as a per-row
-- re-evaluation. `= ANY(array(...))` sidesteps this by making the whole id
-- set a single scalar value the inner scan can use directly. Do not change
-- this back to a plain join without re-running the same EXPLAIN comparison.
--
-- No other change from the previous migration: signature, returns table
-- shape, grants all identical. Functional round-trip re-verified against
-- this body afterward: full 200-row window, ownership isolation (wrong
-- owner/session -> 0 rows), limit clamping (-5 -> 1, 9999 -> 200), every
-- user row sources = '[]', every seeded assistant row's 3 sources ordered
-- ascending 1,2,3, full seq range 1..200 intact. get_advisors (security,
-- performance) showed no new findings.
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
     where src.message_id = any (array (select id from window_rows))
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
