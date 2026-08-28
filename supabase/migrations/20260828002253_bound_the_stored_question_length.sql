-- Give chat_messages.content a bound — on the question, and only the question.
-- ===========================================================================
-- Plan: docs/database-improvement-plan.md finding 8, first half.
--
-- chat_sessions.title has a length CHECK and chat_message_sources.snippet has
-- one; chat_messages.content had none, so a direct service-role write could
-- store a question of any size at all. Flask caps a question at
-- MAX_CHAT_QUERY_CHARS = 8_000 (web/api/app.py:235, enforced at :2415), so
-- that number is derived rather than invented — but Flask is not the
-- enforcement boundary.
--
-- THE ANSWER IS DELIBERATELY LEFT UNBOUNDED, and inventing a bound for it
-- would corrupt history. grep finds no answer-length check anywhere in
-- web/api/app.py; the only reference is `"chars": len(answer)` at :3231, a log
-- field. A model answer routinely exceeds 8,000 characters when the question
-- that produced it cannot — the live rows already show it: user content maxes
-- at 250 characters, assistant content at 4,462. Clamping p_answer to the
-- question's limit would silently store a truncated copy of an answer the
-- reader had already been streamed in full, which is durable history quietly
-- disagreeing with what was on screen — the worst failure available in a
-- citation product. An assistant bound needs its own product number (the
-- model's max_tokens times a safe character ratio) and a matching
-- pre-persistence policy. Until that number exists, assistant rows stay
-- unbounded and that is the correct trade.
--
-- Hence the role-scoped predicate: `role <> 'user' or …`.
--
-- BELT AND BRACES, IN THAT ORDER, because a bare CHECK would violate the rule
-- 20260820131914:44-47 states for title — "Clamped in Flask before the RPC is
-- called, never here: a length constraint enforced inside a SECURITY DEFINER
-- function surfaces a client mistake as a 500." The constraint fires inside
-- chat_append_turn and would abort the whole turn including an answer the
-- reader is already reading.
--
--   * BELT: chat_append_turn clamps p_question to 8,000 characters before the
--     insert, so an over-long question is truncated rather than rejected. The
--     turn survives; the citation product's guarantee about the answer is
--     untouched.
--   * BRACES: the CHECK, which now only ever fires for a writer that bypassed
--     the RPC entirely — which is precisely the writer it exists for.
--
-- The lower bound of 1 is safe rather than a new abort path: Flask returns 400
-- "Query cannot be empty" at web/api/app.py:2413 before any generation starts,
-- so an empty question cannot reach this function from the application.
--
-- NOT VALID then VALIDATE, as separate statements, even though the scan is
-- trivial at 50 rows. `select max(char_length(content)) from
-- public.chat_messages where role = 'user'` returns 250, so no existing row
-- can fail — the split is kept because VALIDATE takes SHARE UPDATE EXCLUSIVE
-- rather than the ACCESS EXCLUSIVE a plain ADD CONSTRAINT would, and because
-- adding the constraint now is cheap in a way it will not be at five million
-- rows. Doing it while it is free is the whole argument for doing it today.
--
-- audit_log's own text columns (action, target_id, user_agent, note,
-- actor_email) are NOT bounded here. user_agent is attacker-controlled and is
-- the one that most wants a cap, but a CHECK on audit_log would abort an
-- administrative action inside a SECURITY DEFINER function for the same reason
-- given above, so the right shape there is a clamp in the seven writers plus
-- admin_store.py — a different concern, in a different set of functions, and
-- it needs numbers nobody has picked yet. Tracked in TODO.md.

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

  -- The belt for chat_messages_user_content_len_chk. Applied once, at the top,
  -- so every path below — the durable rows and the archive row alike — stores
  -- the same text. p_answer is NOT clamped; see the migration header.
  p_question := pg_catalog.left(p_question, 8000);

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
  -- below: an OR cannot be relied on to short-circuit, so the array test must
  -- have completed before anything expands p_sources.
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

alter table public.chat_messages
  add constraint chat_messages_user_content_len_chk
  check (role <> 'user' or char_length(content) between 1 and 8000) not valid;

alter table public.chat_messages
  validate constraint chat_messages_user_content_len_chk;
