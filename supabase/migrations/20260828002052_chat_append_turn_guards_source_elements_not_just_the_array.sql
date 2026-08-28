-- A malformed source element must cost the citations, never the turn.
-- ===========================================================================
-- Plan: docs/database-improvement-plan.md finding 18.
--
-- WHAT WAS WRONG. The function guarded the outer shape and stopped there:
--
--   if jsonb_typeof(coalesce(p_sources, '[]'::jsonb)) <> 'array' then
--     p_sources := '[]'::jsonb;
--   end if;
--
-- and its comment states the intent exactly right — "losing the citation rows
-- of a malformed payload is bad; losing the turn is worse". But the very next
-- statement expanded every element and cast source_index, page, score,
-- semantic_score, lexical_score and cited without checking the element was an
-- object. '[null]'::jsonb passes the array guard, source_index resolves to
-- NULL, the NOT NULL column rejects it, and the whole transaction aborts —
-- including the message rows.
--
-- WHEN that happens is what makes it matter. Flask writes the turn AFTER the
-- `final` SSE frame has been sent (web/api/app.py:3187-3216), so the reader has
-- already read the answer. The abort produces no error they can act on; it
-- produces an answer that vanishes on refresh — the exact outcome the comment
-- says it is avoiding, reached one level down.
--
-- Not currently reachable: the Flask source builder emits objects and
-- p_sources is not browser-controlled. This is a guard that stopped one level
-- short of its own stated intent, hardened before a serialiser change reaches
-- it rather than after.
--
-- THE OBVIOUS ONE-STATEMENT FIX IS ITSELF THE BUG IT IS FIXING:
--
--   -- WRONG. Do not reintroduce this.
--   if jsonb_typeof(...) <> 'array'
--      or exists (select 1 from jsonb_array_elements(p_sources) as e(value)
--                  where jsonb_typeof(e.value) <> 'object') then
--
-- Postgres does not guarantee left-to-right evaluation of OR operands and may
-- reorder them, so jsonb_array_elements can be evaluated against a scalar and
-- raise — precisely the failure the guard exists to prevent. The array test
-- stays its own statement, and only after it has run is the expansion safe.
--
-- DROPPING NON-OBJECT ELEMENTS IS NOT ENOUGH ON ITS OWN. An object with a
-- missing source_index, an uncastable page, a duplicate index or an overlong
-- snippet still aborts the turn. So every cast now sits behind
-- pg_input_is_valid, source_index is filtered to the column's own 1..99 CHECK
-- range, duplicates are dropped before the insert (there is a unique index on
-- (message_id, source_index)), and snippet is clamped to the 321 characters
-- its own CHECK allows. handle_new_user already demonstrates this style on
-- signup metadata — normalise to null, never cast blind.
--
-- DISTINCT ON keeps the FIRST element carrying each source_index, ordered by
-- position in the array, so a duplicate is discarded rather than allowed to
-- overwrite the citation the reader was actually shown.
--
-- create or replace: the argument list and the RETURNS TABLE signature are
-- unchanged, so this is not the drop-and-create case 20260822143411 needed.

create or replace function public.chat_append_turn(
  p_owner_id          uuid,
  p_session_id        uuid,
  p_client_request_id uuid,
  p_question          text,
  p_answer            text,
  p_sources           jsonb,
  p_lang              text,
  p_category          text,
  p_model             text,
  p_corpus_revision   text,
  p_owner_key         text,
  p_session_key       text,
  p_archive_opted_out boolean,
  p_title             text default null,
  p_allow_create      boolean default true
)
returns table (
  session_id           uuid,
  user_message_id      uuid,
  assistant_message_id uuid,
  replayed             boolean
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_owner        uuid;
  v_seq          bigint;
  v_user_id      uuid;
  v_assistant_id uuid;
begin
  if p_owner_id is null or p_session_id is null or p_client_request_id is null then
    raise exception 'chat_append_turn requires owner, session and request ids';
  end if;

  -- Lazy creation, bounded. A session row is never created by opening a chat,
  -- only by completing a turn — otherwise /api/conversation/reset (30/min)
  -- would let a reader fill their own sidebar with empty conversations.
  -- p_allow_create = false additionally refuses to resurrect a session that
  -- does not exist under this owner at all — the backstop for a caller that
  -- reaches this function without Flask's preflight having already turned that
  -- case into a clean 404 before any tokens were generated.
  if coalesce(p_allow_create, true) then
    insert into public.chat_sessions (id, owner_id)
    values (p_session_id, p_owner_id)
    on conflict (id) do nothing;
  end if;

  -- Ownership check and serialisation point in one. If the row already existed
  -- under a different owner, or was never created because p_allow_create was
  -- false, this finds nothing — so a caller cannot append into someone else's
  -- conversation by guessing its id, and cannot resurrect a stale one either.
  select s.owner_id into v_owner
    from public.chat_sessions s
   where s.id = p_session_id and s.owner_id = p_owner_id
   for update;

  if v_owner is null then
    raise exception 'chat session % is not owned by %', p_session_id, p_owner_id;
  end if;

  select m.id into v_user_id
    from public.chat_messages m
   where m.session_id = p_session_id
     and m.client_request_id = p_client_request_id
     and m.role = 'user';

  if v_user_id is not null then
    select m.id into v_assistant_id
      from public.chat_messages m
     where m.session_id = p_session_id
       and m.client_request_id = p_client_request_id
       and m.role = 'assistant';

    -- Both rows or neither. Finding only the question is not a replay, it is a
    -- corrupt turn — and reporting replayed = true with a null assistant id
    -- would tell the caller "already saved" about a transcript that has a
    -- question and no answer.
    if v_assistant_id is null then
      raise exception 'chat turn % in session % has a question with no answer',
        p_client_request_id, p_session_id;
    end if;

    -- RETURNS BEFORE THE TITLE WRITE, deliberately. A replay is a retry of a
    -- turn already recorded; the original call already had its chance to name
    -- the session, and a reader may have renamed it since. This branch must
    -- stay a pure no-op — which is also why p_sources is not parsed here.
    return query select p_session_id, v_user_id, v_assistant_id, true;
    return;
  end if;

  -- `update … returning` rather than `select … for update` then `update`.
  -- RETURNING sees the NEW value, so `next_seq - 2` is the pair just claimed.
  -- The title rides this statement: coalesce(title, …) sets it only when the
  -- column is still null, so the first completed turn names the conversation
  -- and every later turn leaves the name alone, including a reader's rename.
  update public.chat_sessions
     set next_seq = next_seq + 2,
         updated_at = now(),
         title = coalesce(
           title,
           nullif(substring(btrim(coalesce(p_title, '')) from 1 for 120), '')
         )
   where id = p_session_id
  returning next_seq - 2 into v_seq;

  -- BOTH ROWS IN ONE STATEMENT. This is what makes an interior unpaired row
  -- unreachable — ConversationStore._truncate slices on a strict
  -- [user, assistant, …] assumption, and a lone user row would corrupt the
  -- prompt window rather than raise.
  with inserted as (
    insert into public.chat_messages (
      session_id, owner_id, seq, role, content, client_request_id,
      corpus_revision, model, lang, category
    )
    values
      (p_session_id, p_owner_id, v_seq,     'user',      p_question,
       p_client_request_id, null, null, null, null),
      (p_session_id, p_owner_id, v_seq + 1, 'assistant', p_answer,
       p_client_request_id, p_corpus_revision, p_model, p_lang, p_category)
    returning id, role
  )
  select (array_agg(i.id) filter (where i.role = 'user'))[1],
         (array_agg(i.id) filter (where i.role = 'assistant'))[1]
    into v_user_id, v_assistant_id
    from inserted i;

  -- STATEMENT ONE: is it an array at all?
  --
  -- `coalesce` catches SQL NULL and nothing else. A JSONB scalar `null` — what
  -- a caller sending JSON null produces — survives it untouched, and
  -- jsonb_array_elements('null'::jsonb) then raises "cannot extract elements
  -- from a scalar". That abort rolls back the whole turn, including the answer
  -- the reader is already reading. An object or a string does the same.
  --
  -- This stays a separate statement rather than being folded into the query
  -- below. See the migration header: an OR cannot be relied on to short-
  -- circuit, so the array test must have completed before anything expands
  -- p_sources.
  if pg_catalog.jsonb_typeof(coalesce(p_sources, '[]'::jsonb)) <> 'array' then
    p_sources := '[]'::jsonb;
  end if;

  -- STATEMENT TWO: only now is p_sources known to be an array, so expanding it
  -- is safe. Every element is normalised rather than cast blind — a bad
  -- element costs its own citation row and nothing else.
  insert into public.chat_message_sources (
    message_id, source_index, cited, document, page, category,
    score, semantic_score, lexical_score, chunk_id, snippet
  )
  select v_assistant_id,
         e.source_index, e.cited, e.document, e.page, e.category,
         e.score, e.semantic_score, e.lexical_score, e.chunk_id, e.snippet
    from (
      -- First element wins each source_index: there is a unique index on
      -- (message_id, source_index), and a later duplicate must not displace
      -- the citation the reader was actually shown.
      select distinct on (v.source_index)
             v.source_index, v.cited, v.document, v.page, v.category,
             v.score, v.semantic_score, v.lexical_score, v.chunk_id, v.snippet
        from (
          select
            case when pg_catalog.pg_input_is_valid(s.value ->> 'source_index', 'integer')
                 then (s.value ->> 'source_index')::integer
            end as source_index,
            -- NOT NULL column, and the old expression already defaulted it.
            coalesce(
              case when pg_catalog.pg_input_is_valid(s.value ->> 'cited', 'boolean')
                   then (s.value ->> 'cited')::boolean
              end, false) as cited,
            coalesce(s.value ->> 'document', '') as document,
            case when pg_catalog.pg_input_is_valid(s.value ->> 'page', 'integer')
                 then (s.value ->> 'page')::integer
            end as page,
            coalesce(s.value ->> 'category', '') as category,
            case when pg_catalog.pg_input_is_valid(s.value ->> 'score', 'double precision')
                 then (s.value ->> 'score')::double precision
            end as score,
            case when pg_catalog.pg_input_is_valid(s.value ->> 'semantic_score', 'double precision')
                 then (s.value ->> 'semantic_score')::double precision
            end as semantic_score,
            case when pg_catalog.pg_input_is_valid(s.value ->> 'lexical_score', 'double precision')
                 then (s.value ->> 'lexical_score')::double precision
            end as lexical_score,
            s.value ->> 'chunk_id' as chunk_id,
            -- chat_message_sources_snippet_check allows 321 characters.
            substring(coalesce(s.value ->> 'snippet', '') from 1 for 321) as snippet,
            s.ord
          from pg_catalog.jsonb_array_elements(coalesce(p_sources, '[]'::jsonb))
               with ordinality as s(value, ord)
          -- Anything that is not an object is dropped here rather than casting
          -- to NULL and hitting the NOT NULL column.
         where pg_catalog.jsonb_typeof(s.value) = 'object'
        ) v
       -- chat_message_sources_source_index_check allows 1..99. A missing or
       -- uncastable index is NULL and is filtered out by the same predicate.
       where v.source_index between 1 and 99
       order by v.source_index, v.ord
    ) e;

  -- A missing salt must never reach here as a null-salted digest. Flask sets
  -- p_archive_opted_out when it cannot compute one, so the reader's own history
  -- still lands.
  --
  -- The title is NOT archived. The archive is a pseudonymous record of what was
  -- asked and answered; a title is a label the reader chose for their own
  -- navigation and can be renamed to anything, including something
  -- identifying. It has no place in a table keyed by HMAC digests.
  if not coalesce(p_archive_opted_out, false)
     and p_owner_key is not null and p_session_key is not null then
    insert into public.chat_archive (
      owner_key, session_key, turn_key, question, answer, sources,
      lang, category, model, corpus_revision
    )
    values (
      p_owner_key, p_session_key, p_client_request_id, p_question, p_answer,
      coalesce(p_sources, '[]'::jsonb),
      p_lang, p_category, p_model, p_corpus_revision
    )
    on conflict (owner_key, session_key, turn_key) do nothing;
  end if;

  return query select p_session_id, v_user_id, v_assistant_id, false;
end;
$$;

revoke execute on function public.chat_append_turn(
  uuid, uuid, uuid, text, text, jsonb, text, text, text, text, text, text, boolean, text, boolean
) from anon, authenticated, public;
grant execute on function public.chat_append_turn(
  uuid, uuid, uuid, text, text, jsonb, text, text, text, text, text, text, boolean, text, boolean
) to service_role;
