-- chat_append_turn gains p_allow_create — bounding the lazy create
-- ===========================================================================
-- Plan: docs/per-tab-conversation-deep-linking-plan.md §3.4, §3.6.
--
-- WHAT THIS IS AND IS NOT. Flask's preflight (§3.4) is the real fix for a
-- stale/deleted deep link: it checks existence before retrieval, before any
-- tokens are generated, under the `_InFlightGenerations` hold. This parameter
-- is defence in depth at the database, for a future code path that reaches
-- this function without preflighting. It is NOT an authorization control — a
-- hostile client can always pass `true`, and `p_owner_id` is always
-- server-derived (never taken from the request body), so the worst a forged
-- `true` can do is create a row owned by the caller. Confirmed against the
-- insert-then-ownership-select sequence below in the security review.
--
-- THE DEFAULT MUST BE `true`. With `default false`, the window between this
-- migration landing and the new Flask deploying would fail 100% of new
-- conversations: old Flask omits the argument, PostgREST resolves to this
-- signature and supplies `false`, the lazy insert is skipped, the ownership
-- select finds nothing, and the function raises. `default true` makes an
-- un-updated caller behave exactly as it does today, and the new Flask passes
-- `false` explicitly on turns 2+, which is where the protection is wanted.
-- This is not a novel judgement — `p_title` below was defaulted for exactly
-- this reason one migration ago, and this repeats it rather than setting a
-- new precedent.
--
-- ---------------------------------------------------------------------------
-- DESTRUCTIVE: this drops a function that is live and in use.
-- ---------------------------------------------------------------------------
-- README rule 2 puts destructive changes in their own migration; this one
-- concern (the signature) is why chat_session_exists shipped separately in
-- 20260822090000, per rule 1.
--
-- `create or replace` CANNOT be used here, for the same reason 20260821145416
-- gives: adding `p_allow_create` changes the signature, and PostgREST resolves
-- overloaded functions by argument count. Leaving the 14-argument version
-- standing beside this 15-argument one would make a call naming the original
-- fourteen match both candidates and fail as ambiguous — PostgREST's own docs
-- state overloads sharing argument names with different types are explicitly
-- unsupported, so this is a latent trap, not merely untidy. Every turn would
-- stop persisting, on a deployment where the migration "succeeded".
--
-- What was checked before dropping:
--   * Callers: `SupabaseChatBackend.append_turn` (web/services/chat_store.py)
--     is the only one, exactly as 20260821145416 found. This migration lands
--     BEFORE that call site is updated (schema before code, README rule 1),
--     which is exactly what `default true` is for: the un-updated caller
--     keeps working, untouched, until the Flask change ships.
--   * Grants: execute is revoked from anon/authenticated/public and granted
--     to service_role only. Both are re-established below; a dropped function
--     does not carry its ACL forward.
--   * Dependents: none. No view, trigger, policy or default expression
--     references it — it is called over PostgREST and from nowhere in SQL.
--   * Rollback: re-applying 20260821145416's function definition restores the
--     14-argument form, which is safe because Flask has not yet been changed
--     to send `p_allow_create` at the point this migration ships alone.
--
-- The drop and the create are one transaction: `apply_migration` wraps the
-- file, so there is no instant at which neither version exists.
--
-- SCHEMA-CACHE NOTE. PostgREST answers an unknown signature with
-- `404 PGRST202 "Could not find the function in the schema cache"` — the same
-- failure a missing migration would produce. Supabase reloads the cache on DDL
-- via an event trigger, so this is normally automatic; confirm it actually
-- happened after applying rather than assuming it, since the two are
-- indistinguishable from Flask's side.

drop function if exists public.chat_append_turn(
  uuid, uuid, uuid, text, text, jsonb, text, text, text, text, text, text, boolean, text
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
  p_title             text default null,
  -- Also last, also defaulted, also append-only, and defaulted to `true` for
  -- the reason above: an un-updated caller must keep lazily creating exactly
  -- as it does today. See the migration-level comment for the full argument.
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

  -- Lazy creation, now bounded. A session row is never created by opening a
  -- chat, only by completing a turn — otherwise /api/conversation/reset
  -- (30/min) would let a reader fill their own sidebar with empty
  -- conversations. `p_allow_create = false` additionally refuses to
  -- resurrect a session that does not exist under this owner at all — the
  -- backstop for a caller that reaches this function without Flask's
  -- preflight (§3.4) having already turned that case into a clean 404 before
  -- any tokens were generated.
  --
  -- NOTE FOR STEP 8: this is also what makes deleting a conversation whose
  -- generation is still in flight unsafe. The append arrives after the
  -- delete, finds no row, and recreates it — with the answer the reader
  -- believed they had discarded. The client refuses destructive sidebar
  -- actions while a stream is live for exactly this reason; there is no
  -- tombstone here.
  if coalesce(p_allow_create, true) then
    insert into public.chat_sessions (id, owner_id)
    values (p_session_id, p_owner_id)
    on conflict (id) do nothing;
  end if;

  -- Ownership check and serialisation point in one. If the row already existed
  -- under a different owner, or was never created because p_allow_create was
  -- false, this finds nothing — so a caller cannot append into someone else's
  -- conversation by guessing its id, and cannot resurrect a stale one either.
  -- Holding the lock also makes the replay probe below safe against two
  -- concurrent submissions of the same request id — and, now, makes the title
  -- write below deterministic under two concurrent first turns.
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
  uuid, uuid, uuid, text, text, jsonb, text, text, text, text, text, text, boolean, text, boolean
) is
  'Record one exchange, creating the session lazily and naming it from the '
  'first turn''s question. p_title is applied only when title is null, so a '
  'rename survives every later turn. p_allow_create=false refuses to '
  'resurrect a session that does not already exist under this owner — '
  'defence in depth behind Flask''s preflight, not an authorization control.';

-- A dropped function does not carry its ACL forward, so both halves are stated
-- again. `security definer` executes as the function OWNER, which still holds
-- the table writes that `revoke all … from service_role` took away from the
-- caller — the arrangement the base migration set up and verified at apply time.
revoke execute on function public.chat_append_turn(
  uuid, uuid, uuid, text, text, jsonb, text, text, text, text, text, text, boolean, text, boolean
) from anon, authenticated, public;
grant execute on function public.chat_append_turn(
  uuid, uuid, uuid, text, text, jsonb, text, text, text, text, text, text, boolean, text, boolean
) to service_role;
