-- admin_top_questions — recurring questions, grouped, with the privacy floor
-- held in SQL rather than in the console.
-- ===========================================================================
-- Plan: docs/admin-analytics-v1-plan.md §4.1, §4.3 and §5. Second of three
-- analytics migrations; the index it reads landed first.
--
-- NO p_owner_id, AND THAT IS NOT AN OVERSIGHT. supabase/README.md's RPC
-- contract point 5 asks for `p_owner_id` as the first argument, filtered on
-- inside the function — a rule about reader-facing functions, where the whole
-- job is to scope a query to one account. This is an operator aggregate over
-- every account, so there is no owner to filter on: an owner argument here
-- would either be ignored or would turn the console's figures into one
-- reader's figures. It matches the admin_* readers that already ship —
-- admin_list_tiers (20260903200618:19-28), admin_list_users and
-- admin_get_user take no actor either and are service_role-only. The gate is
-- Flask's `_gate()` before_request, which re-resolves identity live;
-- admin_actor_email() is the gate for MUTATIONS, and this function mutates
-- nothing, which is also why it does not belong in the hardcoded mutating list
-- in supabase/tests/function_acls.test.sql. That README point is scoped in the
-- same commit as this file.
--
-- owner_id IS READ AND IS NEVER PROJECTED. It appears exactly twice below —
-- inside `count(distinct s.owner_id)` for the floor, and inside the same
-- expression for the asker bucket. The `returns table` names no owner, no
-- session, no message id and no email, which supabase/tests/function_acls.
-- test.sql asserts against pg_get_function_result rather than trusting this
-- comment.
--
-- THE FLOOR IS UN-LOWERABLE, and that is the whole reason it lives here
-- instead of in the route. `greatest(coalesce(p_min_askers, 2), 2)` lets a
-- caller RAISE the minimum and never lower it: not through the route (which
-- never sends the parameter at all), and not through any later caller of this
-- function that forgets to. WHAT THIS IS NOT (corrected 2026-09-21 after a
-- second review): a defence against a leaked service key. Measured —
-- service_role holds SELECT on chat_messages and bypasses RLS, so that key
-- reads the rows themselves and no function can stand in its way. The floor
-- guards the application layer: a route bug, a new caller, a careless
-- parameter. It is also a release rule for ONE result, not protection against
-- inference ACROSS results — an operator who is themselves an asker, two
-- windows subtracted, or a group vanishing after a known deletion can each
-- say more than any single response does. The floor counts DISTINCT
-- ASKERS, not asks — `group by` over turns does not deduplicate by reader, so
-- one person asking five times would otherwise read as a five-count row that
-- is one reader's content shown verbatim to an operator. With the floor in
-- SQL, nothing this function returns is a single reader's content, which is
-- what lets V1 ship with no privacy-policy edit and no audit row per read
-- (web/services/audit.py:14-18 draws the audit line at access to a reader's
-- own content).
--
-- THE ASKER COUNT IS BUCKETED HERE TOO: NULL below 5, exact from 5 up. At
-- three accounts an exact figure is a participation oracle on its own —
-- `askers = 2` on a row the operator also asked identifies the other asker
-- without reading a word — so below five the function returns NULL and the
-- console prints the range 2-4. From five up the exact number is what
-- separates "10 asks from 9 accounts" from "10 asks from 2", which the ask
-- count alone never can. The 5 is hard-coded for the same reason the 2 is: no
-- caller of this function sees more than the console does. (A caller who
-- RAISES p_min_askers to 3 or 4 can watch a group vanish and so recover the
-- exact count the bucket hides. The route never sends it; anyone else able to
-- is holding the service key and can read the table.) Residual, accepted: with
-- a population barely above five, askers = 5 is near-unanimity.
--
-- THE SIGNATURE IS SETTLED ON PURPOSE. Adding a column to `returns table`
-- later is a `drop function` plus a `create`, never a `create or replace`, so
-- the asker column ships now rather than being added back after the console
-- proves it was needed.
--
-- NORMALISATION IS INLINE, not a helper function: it has exactly one SQL
-- caller, and a helper would add an ACL surface and a migration for nothing.
-- Three passes, in this order:
--
--   1. delete the zero-width and direction marks — U+200B..U+200F, the four
--      isolate controls U+2066..U+2069, and U+FEFF;
--   2. lower(), then collapse every run of spaces to a single space and btrim;
--   3. strip one trailing run of `?`, `!`, `.`, U+061F (Arabic question mark),
--      U+06D4 (Arabic full stop), U+2026 (ellipsis) and spaces.
--
-- THE EXPLICIT SPACE LIST IS LOAD-BEARING. Measured on this database
-- (Postgres 17): `\s` matches NONE of U+00A0, U+200B or U+200F. The manual
-- says why — `\s` is `[[:space:]]`, and classification of non-ASCII characters
-- depends on the active collation or LC_CTYPE. Python's `\s` DOES match
-- U+00A0. With a bare `\s` here, Arabic pasted out of Word or WhatsApp would
-- fragment its group in production while the in-memory double grouped it, and
-- the suite would stay green. web/services/admin_store.py's
-- normalize_question() spells the same three passes by code point and is the
-- only Python copy; supabase/tests/rpc_behaviour.test.sql pins the pair.
--
-- THE `\uXXXX` SEQUENCES BELOW ARE REGEX ESCAPES, NOT STRING ESCAPES, and the
-- literals are deliberately plain rather than E''. With standard_conforming_
-- strings = on (the default since 9.1, and the setting on this project) a
-- backslash in a plain literal is an ordinary character, so the pattern that
-- reaches the regex engine still contains `\u200B` and the engine's own
-- character-entry escape resolves it. Written as E'\u200B' the character would
-- be substituted by the string parser instead and the file would carry
-- invisible characters no reviewer could see. Do not "fix" these into E''
-- strings, and do not paste raw characters in: an invisible character inside a
-- bracket expression is unreviewable, and an Arabic one reorders the line
-- visually so that the class no longer reads as what it is.
--
-- NOT FOLDED IN V1, recorded so the gaps read as decisions: alef, yaa and
-- taa-marbuta variants, tashkeel, tatweel, and the Arabic comma. Known engine
-- gap: lower() differs between Postgres and Python for a handful of characters
-- (Turkish dotted I, sharp s); irrelevant to this corpus.
--
-- THE WINDOW FLOOR IS SEVEN DAYS, not one. The console only offers 7 / 30 / 90,
-- and the floor means no SINGLE response ever describes less than a week.
-- What it does NOT do (corrected 2026-09-20 after review — this header first
-- claimed it "stops differencing"): a direct caller can still subtract
-- p_days => 7 from p_days => 8 and get a one-day slice. Accepted, because the
-- two-asker floor applies to each call separately, so the subtraction can date
-- an already-listed group to a day and can never surface a group that neither
-- call was allowed to return. A time oracle, not an identity one. Snapping
-- p_days to 7 / 30 / 90 would close it and is the fix if that ever matters.
--
-- NO TIMESTAMP IS RETURNED. A `last_asked` on a rare question is a correlation
-- handle against audit_log.occurred_at and profile_last_seen; the window
-- parameter already says "the last 30 days".
--
-- NO STATEMENT TIMEOUT. `set search_path = '' set statement_timeout = ...`
-- yields proconfig `search_path="",statement_timeout=...`, and
-- function_acls.test.sql's check is end-anchored (`!~ 'search_path=("")?$'`),
-- so the function would ship failing the suite. The clamped p_days and p_limit
-- are what bound the query instead. If a timeout is ever wanted, the
-- search_path clause has to come LAST.
--
-- APPLY NOTE (2026-09-20). The MCP transport that applied this file decoded every
-- \uXXXX in the statement into the raw character, so the first live copy carried
-- invisible characters in prosrc. Same semantics, but not this file. It was re-created
-- in place the same hour with `create or replace`, the backslashes built from chr(92),
-- and verified: zero non-ASCII in prosrc, ACLs and comment intact. If this is ever
-- re-applied through that transport, check prosrc the same way.

create function public.admin_top_questions(
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
  askers   bigint   -- distinct accounts, NULL below 5 — bucketed HERE, not in the UI
)
language sql
stable
security definer
set search_path = ''
as $$
  with turns as (
    -- The question text is on the USER row; lang and category are written on
    -- the ASSISTANT row only (20260820131914:86-92), so every metric is a
    -- self-join of a turn's two rows on (session_id, client_request_id) —
    -- which chat_messages_idem_key already indexes.
    select a.id as assistant_id, a.owner_id, a.created_at,
           u.content as question,
           pg_catalog.regexp_replace(
             pg_catalog.btrim(pg_catalog.regexp_replace(
               pg_catalog.lower(pg_catalog.regexp_replace(
                 u.content, '[\u200B-\u200F\u2066-\u2069\uFEFF]', '', 'g')),
               '[\s\u00A0\u1680\u2000-\u200A\u202F\u205F\u3000]+', ' ', 'g')),
             '[?!.\u061F\u06D4\u2026 ]+$', '') as normalized
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
    -- count() over zero rows is 0, never null, so a turn whose search returned
    -- nothing and a turn whose answer cited nothing both land on 0 here. They
    -- are separated by admin_citation_stats, not by this function: a question
    -- row's `uncited` is deliberately their union.
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
            s.normalized
   limit greatest(least(coalesce(p_limit, 20), 100), 1);
$$;

comment on function public.admin_top_questions(integer, text, text, integer, integer, text) is
  'Recurring questions over saved turns, grouped by a normalised key. Returns a '
  'group only once at least two distinct accounts have asked it, and buckets the '
  'asker count to NULL below five. Projects no owner, session or message id.';

revoke execute on function public.admin_top_questions(integer, text, text, integer, integer, text)
  from anon, authenticated, public;
grant  execute on function public.admin_top_questions(integer, text, text, integer, integer, text)
  to service_role;
