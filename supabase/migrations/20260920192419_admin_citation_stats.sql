-- admin_citation_stats — how often a saved answer cited anything, split by the
-- two ways it can fail to.
-- ===========================================================================
-- Plan: docs/admin-analytics-v1-plan.md §4.2. Third of three analytics
-- migrations; it reads the partial index the first one added.
--
-- "UNANSWERED = cited == []" IS TWO DIFFERENT FAILURES, and both are already
-- stored. Search found passages and the model cited none of them
-- (turns_uncited), versus search returned nothing at all to cite
-- (turns_no_retrieval). chat_message_sources holds one row per RETRIEVED
-- passage, not per cited one (20260820131914:128-133), so the two are
-- separable for free and the function reports them apart. They are disjoint by
-- construction, and admin_top_questions' `uncited` column is deliberately
-- their union. Nothing persisted marks a REFUSAL, so that word appears in no
-- column here and in no copy above it.
--
-- COUNTS ONLY — never a percentage, never an average. The console divides, and
-- it is the console that has to guard a zero denominator and withhold a ratio
-- at small n; a rate computed here would arrive already rounded and with no
-- way to tell 1-of-2 from 50-of-100.
--
-- THREE GROUPING SETS, not the lang x category cross product: at any plausible
-- volume the cross product is noise, and the client already ignores a `scope`
-- value it does not know — which is what lets follow-up 4 add a fourth set on
-- date_trunc('day', ...) without a client change.
--
-- bucket IS `coalesce(t.lang, t.category)` because exactly one of the two is
-- non-aggregated in each non-total set. A turn whose assistant row has a NULL
-- lang therefore lands in a `scope = 'lang'` row with a NULL bucket — correct
-- and not a defect: the wire contract types bucket as string-or-null, and the
-- console labels an unknown bucket rather than dropping the turn out of the
-- breakdown. The `total` row is the one that is null by construction.
--
-- NO p_actor_id and no audit row, for the reasons the sibling migration's
-- header gives at length. This function returns no text at all — only counts —
-- so it needs no asker floor either, which is what keeps the surface useful on
-- day one while the question list is legitimately empty at three accounts.
-- ACCEPTED AND DOCUMENTED: a narrow window plus p_lang plus p_category can
-- read turns = 1. That is activity disclosure at tiny n with no content
-- attached. The seven-day window floor keeps any single response at a week or
-- more; it does not stop a direct caller subtracting two adjacent windows, which
-- yields a per-day count of saved answers and nothing else (corrected
-- 2026-09-20 after review — see the same note in *_admin_top_questions.sql).
--
-- sum() OVER bigint RETURNS numeric, so both totals carry an explicit
-- ::bigint. A `language sql` function's final statement must produce the
-- declared column types — Postgres inserts no assignment cast there — and
-- without these two casts the CREATE itself fails with "Final statement
-- returns numeric instead of bigint". The values are counts of source rows per
-- turn summed over a bounded window, so nothing can be lost narrowing them.
--
-- NO STATEMENT TIMEOUT, same trap as the sibling: the ACL suite's search_path
-- check is end-anchored, so a second SET would ship this function failing it.

create function public.admin_citation_stats(
  p_days integer default 30, p_lang text default null, p_category text default null
)
returns table (
  scope              text,    -- 'total' | 'lang' | 'category'
  bucket             text,    -- null for 'total'
  turns              bigint,
  turns_uncited      bigint,  -- retrieved something, cited nothing
  turns_no_retrieval bigint,  -- search returned nothing at all
  cited_total        bigint,
  retrieved_total    bigint
)
language sql
stable
security definer
set search_path = ''
as $$
  with turns as (
    -- No self-join here: this function never reads the question text, so the
    -- assistant row alone carries everything it needs.
    select a.lang, a.category,
           (select count(*) filter (where s.cited) from public.chat_message_sources s
             where s.message_id = a.id) as cited_count,
           (select count(*) from public.chat_message_sources s
             where s.message_id = a.id) as retrieved_count
      from public.chat_messages a
     where a.role = 'assistant'
       and a.created_at >= pg_catalog.now() - pg_catalog.make_interval(
             days => greatest(least(coalesce(p_days, 30), 3650), 7))
       and (p_lang     is null or a.lang     = p_lang)
       and (p_category is null or a.category = p_category)
  )
  select case when grouping(t.lang) = 0 then 'lang'
              when grouping(t.category) = 0 then 'category'
              else 'total' end,
         coalesce(t.lang, t.category),
         count(*),
         count(*) filter (where t.cited_count = 0 and t.retrieved_count > 0),
         count(*) filter (where t.retrieved_count = 0),
         sum(t.cited_count)::bigint,
         sum(t.retrieved_count)::bigint
    from turns t
   group by grouping sets ((), (t.lang), (t.category));
$$;

comment on function public.admin_citation_stats(integer, text, text) is
  'Counts of saved answers per window, split by question language and by search '
  'scope: how many cited nothing despite retrieval, and how many had nothing to '
  'cite. Counts only — the console computes every rate. Returns no text.';

revoke execute on function public.admin_citation_stats(integer, text, text)
  from anon, authenticated, public;
grant  execute on function public.admin_citation_stats(integer, text, text)
  to service_role;
