-- Chat navigation: list, rename, delete
-- ===========================================================================
-- Step 8's three server-side operations. `chat_append_turn`, `chat_load_session`
-- and `chat_latest_session` (20260820131914) let a reader continue ONE
-- conversation; these let them see, name and discard the others.
--
-- WHY THESE ARE RPCs AND NOT DIRECT TABLE ACCESS, given the base migration
-- already gives readers SELECT and DELETE through RLS.
--
-- The base migration's own §8 note argued the opposite — that a delete RPC
-- would be "a second, privileged path" to what `chat_sessions_delete_own`
-- already permits, and that step 8 would call that policy from the browser with
-- no Flask route in between. Two facts, both verifiable above, retired that
-- plan rather than merely outvoting it:
--
--   1. `revoke all on public.chat_sessions from service_role` (base migration
--      line 245) leaves Flask holding SELECT and nothing else. There is no
--      server-side delete or update to route through, so "browser-direct or an
--      RPC" was never the choice — it was "browser-direct or nothing".
--   2. A browser-direct delete cannot finish the job. Deleting the row the
--      Flask cookie's `conv_id` names leaves that cookie pointing at a
--      conversation that no longer exists, and `chat_append_turn`'s
--      `on conflict (id) do nothing` lazily RECREATES it on the reader's next
--      question. The reader deletes a conversation and it comes back. Clearing
--      the cookie and the process-local `ConversationStore` window is Flask's
--      job by construction, so the delete has to pass through Flask anyway.
--
-- RLS stays exactly as it is. It is defence in depth against a leaked anon key,
-- not the coordinator of a workflow that spans a cookie, an in-RAM window and a
-- table. The reader's DELETE grant is left standing rather than revoked: it is a
-- genuine reader right and revoking it would be a change this migration has no
-- reason to make.
--
-- All three are `security definer` with `set search_path = ''` (README rule 3),
-- executable by `service_role` only, and every one of them filters on
-- p_owner_id. An unowned id is never distinguishable from an absent one — the
-- same refusal shape `chat_load_session` already takes, so probing for a
-- stranger's session id learns nothing either way.

-- ---------------------------------------------------------------------------
-- chat_list_sessions — the sidebar, keyset-paginated
-- ---------------------------------------------------------------------------
-- KEYSET, NOT OFFSET, and the reason is specific to this table rather than
-- general performance folklore. `updated_at` means "last spoken in" and
-- `chat_append_turn` moves it on every completed turn, so the ordering key is
-- live. Under `offset 30` an answer landing in another tab between page 1 and
-- page 2 shifts the whole window down by one and the reader sees the same
-- conversation twice. `(updated_at, id) < (cursor)` is stable across exactly
-- that mutation.
--
-- The index it rides was already built for this: `chat_sessions_owner_updated_idx
-- on (owner_id, updated_at desc, id desc)` (base migration line 70), which is
-- the row-wise comparison's ordering, column for column.
--
-- `id desc` is the tiebreaker, and it is not decoration. Migration
-- 20260817161427 exists because same-instant timestamps produced
-- non-deterministic page boundaries in the People list; two conversations can
-- share an `updated_at` here just as easily, and without the tiebreaker a
-- cursor could skip one or repeat one forever.
create or replace function public.chat_list_sessions(
  p_owner_id          uuid,
  p_limit             integer default 30,
  p_cursor_updated_at timestamptz default null,
  p_cursor_id         uuid default null
)
returns table (
  id            uuid,
  title         text,
  created_at    timestamptz,
  updated_at    timestamptz,
  message_count bigint
)
language sql
stable
security definer
set search_path = ''
as $$
  select
    s.id,
    s.title,
    s.created_at,
    s.updated_at,
    -- Derived, not counted. `next_seq` starts at 1 and advances by 2 per turn
    -- pair, so `next_seq - 1` is the message count exactly — from a column
    -- already on the row. A `count(*)` over chat_messages would be a genuine
    -- N+1: one index scan per listed conversation, on the request that draws
    -- the sidebar.
    (s.next_seq - 1) as message_count
  from public.chat_sessions s
  where s.owner_id = p_owner_id
    -- BOTH cursor halves or neither. A caller supplying only a timestamp would
    -- otherwise compare against `(ts, null)`, and row comparison with a null
    -- yields null — every row filtered out, an empty page, and a sidebar that
    -- says the reader has no older conversations. Treated as "no cursor"
    -- instead, which pages from the top: visibly wrong beats silently empty.
    and (
      p_cursor_updated_at is null
      or p_cursor_id is null
      or (s.updated_at, s.id) < (p_cursor_updated_at, p_cursor_id)
    )
  order by s.updated_at desc, s.id desc
  -- Clamped HERE as well as in Flask. Flask's clamp is the one that reports a
  -- bad request honestly; this one is what stops a future caller that forgets.
  limit greatest(1, least(coalesce(p_limit, 30), 100));
$$;

comment on function public.chat_list_sessions(uuid, integer, timestamptz, uuid) is
  'One owner''s conversations, newest activity first, keyset-paginated on '
  '(updated_at, id). message_count is derived from next_seq, never counted.';

revoke execute on function public.chat_list_sessions(uuid, integer, timestamptz, uuid)
  from anon, authenticated, public;
grant execute on function public.chat_list_sessions(uuid, integer, timestamptz, uuid)
  to service_role;

-- ---------------------------------------------------------------------------
-- chat_rename_session — metadata, and deliberately not activity
-- ---------------------------------------------------------------------------
-- `updated_at` IS NOT TOUCHED, and that is the whole design of this function.
-- The base migration went out of its way to refuse a `before update` touch
-- trigger on this table (line 52) precisely so the column could keep meaning
-- "last spoken in". Bumping it on a rename would take a conversation from three
-- months ago and drop it at the top of TODAY, displacing the reader's actual
-- current work — the sidebar shuffling on an edit that changed no content.
--
-- LENGTH IS NOT CHECKED HERE EITHER. `chat_sessions.title` carries
-- `char_length(title) between 1 and 120`, and a caller that trips a CHECK inside
-- a `security definer` function gets a 500 — a client mistake wearing a server
-- error's clothes. Flask clamps before calling (chat_store.clamp_title), and the
-- `substring` below is the belt to that braces: it makes an over-long title
-- impossible rather than fatal.
create or replace function public.chat_rename_session(
  p_owner_id   uuid,
  p_session_id uuid,
  p_title      text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_title text;
  v_found boolean;
begin
  if p_owner_id is null or p_session_id is null then
    raise exception 'chat_rename_session requires owner and session ids';
  end if;

  -- Trim first, then cut. Cutting first can leave a trailing space that the
  -- CHECK counts as a character, and `nullif(…, '')` collapses a whitespace-only
  -- title to NULL — which is the "untitled" state the sidebar already renders a
  -- fallback for, rather than a row whose title is one blank.
  v_title := nullif(substring(btrim(coalesce(p_title, '')) from 1 for 120), '');

  update public.chat_sessions
     set title = v_title
   where id = p_session_id
     and owner_id = p_owner_id;

  get diagnostics v_found = row_count;
  -- False for "not yours" AND for "not there", identically. Distinguishing them
  -- would turn this into an oracle for whether a guessed uuid names somebody
  -- else's conversation.
  return v_found;
end;
$$;

comment on function public.chat_rename_session(uuid, uuid, text) is
  'Set one owned session''s title. Deliberately does NOT touch updated_at: that '
  'column means "last spoken in", and a rename is not activity.';

revoke execute on function public.chat_rename_session(uuid, uuid, text)
  from anon, authenticated, public;
grant execute on function public.chat_rename_session(uuid, uuid, text)
  to service_role;

-- ---------------------------------------------------------------------------
-- chat_delete_session — the reader's own erasure, cascaded
-- ---------------------------------------------------------------------------
-- One statement. `chat_messages_session_owner_fk` cascades to the messages and
-- `chat_message_sources.message_id` cascades from there, so deleting the session
-- row takes the whole conversation and leaves no orphan — verified against the
-- live schema when the base migration was applied (0 orphans after a reader's
-- own delete).
--
-- WHAT THIS DOES NOT DELETE, stated here because the notice copy depends on it:
-- `chat_archive` rows are pseudonymous and keyed by HMAC digests, carry no
-- foreign key to this table, and are not reachable from an owner id. They are
-- unaffected, exactly as the disclosure says. PITR and backups outlive this
-- delete too.
create or replace function public.chat_delete_session(
  p_owner_id   uuid,
  p_session_id uuid
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_found boolean;
begin
  if p_owner_id is null or p_session_id is null then
    raise exception 'chat_delete_session requires owner and session ids';
  end if;

  delete from public.chat_sessions
   where id = p_session_id
     and owner_id = p_owner_id;

  get diagnostics v_found = row_count;
  return v_found;
end;
$$;

comment on function public.chat_delete_session(uuid, uuid) is
  'Delete one owned conversation and, by cascade, its messages and sources. '
  'Exists because service_role holds no DELETE on chat_sessions, and because a '
  'browser-direct delete cannot clear Flask''s conv_id or its RAM window.';

revoke execute on function public.chat_delete_session(uuid, uuid)
  from anon, authenticated, public;
grant execute on function public.chat_delete_session(uuid, uuid)
  to service_role;
