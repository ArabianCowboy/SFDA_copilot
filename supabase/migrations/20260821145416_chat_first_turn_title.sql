-- First-turn titling, inside the turn's own transaction
-- ===========================================================================
-- `chat_sessions.title` has been null since 20260820131914, which reserved it
-- for "Phase 2 titling" and wrote nothing. This is that.
--
-- WHY THE TITLE IS SET BY THIS FUNCTION AND NOT BY A SECOND CALL AFTER IT.
-- The obvious implementation — persist the turn, then PATCH the title — is a
-- race against the session's own lifecycle, and every branch of it loses:
--
--   * The second call can fail on its own (network, 503, a closed tab) and
--     leave a permanently untitled conversation whose opening question is
--     sitting one table away.
--   * The reader can delete or rename the conversation in the window between
--     the two calls, and the late title then lands on a row they just renamed —
--     or recreates one they just deleted, since a rename UPDATE cannot, but a
--     careless upsert could.
--   * Two first turns submitted from two tabs both see `title is null` and both
--     write. Whichever lands second wins, arbitrarily.
--
-- Folding it into the append makes all three unreachable: the title is written
-- by the same statement that claims the sequence numbers, inside the same
-- transaction, while this session's row is already held by the `for update`
-- taken above. Two concurrent first turns serialise on that lock and the first
-- one's question becomes the title, deterministically.
--
-- `coalesce(title, …)` IS THE WHOLE RULE: set when null, never overwritten.
-- Every later turn passes its own question in and every later turn is a no-op,
-- so this needs no "is this the first turn?" test on the caller's side — which
-- is good, because the caller cannot answer that question without a round trip
-- it would then be racing.
--
-- A RENAME IS STILL A SEPARATE OPERATION. `chat_rename_session` writes the
-- column unconditionally; this one only fills a hole. A renamed conversation
-- keeps its name through every subsequent turn.
--
-- ---------------------------------------------------------------------------
-- DESTRUCTIVE: this drops a function that is live and in use.
-- ---------------------------------------------------------------------------
-- README rule 2 puts destructive changes in their own migration, and rule 1
-- keeps this to one concern, which is why the navigation RPCs ship separately
-- in 20260821145319.
--
-- `create or replace` CANNOT be used here. Adding `p_title` changes the
-- signature, and Postgres treats a different argument list as a different
-- function — so `create or replace` would leave the 13-argument version
-- standing beside the new 14-argument one. PostgREST resolves an RPC by the
-- named arguments in the request body, and a call naming the original thirteen
-- would then match BOTH candidates and fail as ambiguous. Every turn would stop
-- persisting, on a deployment where the migration "succeeded".
--
-- What was checked before dropping:
--   * Callers: `SupabaseChatBackend.append_turn` (web/services/chat_store.py) is
--     the only one. `grep -rn "chat_append_turn" --include=*.py --include=*.js`
--     returns that call, the in-memory double that mirrors it, and comments.
--   * Grants: `execute` is revoked from anon/authenticated/public and granted to
--     service_role only. Both are re-established below; a dropped function does
--     not carry its ACL forward.
--   * Dependents: none. No view, trigger, policy or default expression
--     references it — it is called over PostgREST and from nowhere in SQL.
--   * Rollback: re-applying 20260820131914's function definition restores the
--     13-argument form. Flask would then need `title` removed from the payload,
--     which is why the Python side treats a rejected title as a persistence
--     failure rather than silently dropping it.
--
-- The drop and the create are one transaction: `apply_migration` wraps the file,
-- so there is no instant at which neither version exists.

drop function if exists public.chat_append_turn(
  uuid, uuid, uuid, text, text, jsonb, text, text, text, text, text, text, boolean
);

create function public.chat_append_turn(
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
  -- Last, and defaulted, so the argument list stays append-only. A caller that
  -- has not been updated yet still resolves, and files an untitled session
  -- rather than failing — the same degradation posture the rest of this
  -- function takes toward the archive.
  p_title             text default null
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

  -- Lazy creation. A session row is never created by opening a chat, only by
  -- completing a turn — otherwise /api/conversation/reset (30/min) would let a
  -- reader fill their own sidebar with empty conversations.
  --
  -- NOTE FOR STEP 8: this is also what makes deleting a conversation whose
  -- generation is still in flight unsafe. The append arrives after the delete,
  -- finds no row, and recreates it — with the answer the reader believed they
  -- had discarded. The client refuses destructive sidebar actions while a
  -- stream is live for exactly this reason; there is no tombstone here.
  insert into public.chat_sessions (id, owner_id)
  values (p_session_id, p_owner_id)
  on conflict (id) do nothing;

  -- Ownership check and serialisation point in one. If the row already existed
  -- under a different owner the insert above did nothing and this finds
  -- nothing, so a caller cannot append into someone else's conversation by
  -- guessing its id. Holding the lock also makes the replay probe below safe
  -- against two concurrent submissions of the same request id — and, now, makes
  -- the title write below deterministic under two concurrent first turns.
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
    -- question and no answer. The two rows are written by one statement in one
    -- transaction, so this is unreachable through this function; it is
    -- reachable by a direct service-role write, which is exactly the case worth
    -- refusing loudly rather than papering over.
    if v_assistant_id is null then
      raise exception 'chat turn % in session % has a question with no answer',
        p_client_request_id, p_session_id;
    end if;

    -- RETURNS BEFORE THE TITLE WRITE, and that is deliberate. A replay is a
    -- retry of a turn already recorded; the original call already had its
    -- chance to name the session, and a reader may have renamed it since. This
    -- branch must stay a pure no-op — it is the reason p_sources is not parsed
    -- here either.
    return query select p_session_id, v_user_id, v_assistant_id, true;
    return;
  end if;

  -- `update … returning` rather than `select … for update` then `update`. The
  -- second is what most people write and it is both slower and racier.
  -- RETURNING sees the NEW value, so `next_seq - 2` is the pair we just claimed.
  --
  -- THE TITLE RIDES THIS STATEMENT. `coalesce(title, …)` sets it only when the
  -- column is still null, so the first completed turn names the conversation and
  -- every later turn leaves the name alone — including a name the reader chose.
  -- Trimmed before it is cut, so a trailing space cannot push the result past
  -- the column's `char_length(title) between 1 and 120`; a whitespace-only
  -- candidate collapses to NULL and the sidebar renders its untitled fallback.
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
  -- unreachable — which matters because ConversationStore._truncate slices on a
  -- strict [user, assistant, user, assistant, …] assumption, and a lone user row
  -- would corrupt the prompt window rather than raise.
  with inserted as (
    insert into public.chat_messages (
      session_id, owner_id, seq, role, content, client_request_id,
      corpus_revision, model, lang, category
    )
    values
      -- The user row carries client_request_id too: the replay probe above
      -- looks it up by (session, request id, role='user'), so a null here would
      -- make every retry insert a duplicate question.
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

  -- `coalesce` catches SQL NULL and nothing else. A JSONB scalar `null` — which
  -- is what a caller sending JSON `null` produces — survives it untouched, and
  -- `jsonb_array_elements('null'::jsonb)` then raises "cannot extract elements
  -- from a scalar". That abort rolls back the whole turn, including the answer
  -- the reader is already reading. An object or a string does the same.
  --
  -- So the shape is checked rather than assumed: anything that is not a JSON
  -- array becomes an empty source list. Losing the citation rows of a
  -- malformed payload is bad; losing the turn is worse, and a hard failure
  -- here would be triggered by the caller rather than by the data.
  if jsonb_typeof(coalesce(p_sources, '[]'::jsonb)) <> 'array' then
    p_sources := '[]'::jsonb;
  end if;

  insert into public.chat_message_sources (
    message_id, source_index, cited, document, page, category,
    score, semantic_score, lexical_score, chunk_id, snippet
  )
  select v_assistant_id,
         (s->>'source_index')::integer,
         coalesce((s->>'cited')::boolean, false),
         coalesce(s->>'document', ''),
         (s->>'page')::integer,
         coalesce(s->>'category', ''),
         (s->>'score')::double precision,
         (s->>'semantic_score')::double precision,
         (s->>'lexical_score')::double precision,
         s->>'chunk_id',
         coalesce(s->>'snippet', '')
    from jsonb_array_elements(coalesce(p_sources, '[]'::jsonb)) as s;

  -- A missing salt must never reach here as a null-salted digest. Flask sets
  -- p_archive_opted_out when it cannot compute one, so the reader's own history
  -- still lands — losing the turn the reader is looking at would be a far worse
  -- failure than losing one archive row.
  --
  -- The title is NOT archived. The archive is a pseudonymous record of what was
  -- asked and answered; a title is a label the reader chose for their own
  -- navigation, and it can be renamed to anything, including something
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

comment on function public.chat_append_turn(
  uuid, uuid, uuid, text, text, jsonb, text, text, text, text, text, text, boolean, text
) is
  'Record one exchange, creating the session lazily and naming it from the '
  'first turn''s question. p_title is applied only when title is null, so a '
  'rename survives every later turn.';

-- A dropped function does not carry its ACL forward, so both halves are stated
-- again. `security definer` executes as the function OWNER, which still holds
-- the table writes that `revoke all … from service_role` took away from the
-- caller — the arrangement the base migration set up and verified at apply time.
revoke execute on function public.chat_append_turn(
  uuid, uuid, uuid, text, text, jsonb, text, text, text, text, text, text, boolean, text
) from anon, authenticated, public;
grant execute on function public.chat_append_turn(
  uuid, uuid, uuid, text, text, jsonb, text, text, text, text, text, text, boolean, text
) to service_role;
