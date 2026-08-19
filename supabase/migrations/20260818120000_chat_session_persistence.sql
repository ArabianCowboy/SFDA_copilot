-- Per-user chat session persistence: durable conversations, plus an append-only
-- archive kept for quality review and internal model work.
--
-- Plan: docs/chat-persistence-implementation-roadmap.md. Read §2.4 before
-- changing any policy here — the split below is deliberate and narrow.
--
-- NOT YET APPLIED when this file was written. Per supabase/README.md the
-- filename must match what `list_migrations` reports, so rename this file to the
-- version `apply_migration` assigns.
--
-- TWO ACCESS PATTERNS, ON PURPOSE.
--
--   Readers SELECT their own rows and DELETE their own sessions through RLS.
--   Nobody but the service role may INSERT or UPDATE message content.
--
-- The asymmetry is the point. A reader who can write `chat_messages` can author
-- an assistant answer and its citation rows, and it renders as something *the
-- system* said — a provenance forgery primitive reachable from a browser
-- console, on an assistant whose first principle is that every answer carries a
-- resolvable source. So content writes go through `chat_append_turn` and nowhere
-- else, and there is no `grant insert/update` on these tables at all.
--
-- Reader history and the archive are SEPARATE TABLES WITH SEPARATE LIFETIMES.
-- Folded together, a reader deleting their own conversation would destroy the
-- archive with it — which is how you end up either lying to the reader about
-- deletion or soft-deleting a regulatory conversation they were told was gone.
-- Split, the reader's delete really deletes and the archive is governed on its
-- own terms.

-- ---------------------------------------------------------------------------
-- Reader-facing history
-- ---------------------------------------------------------------------------

create table if not exists public.chat_sessions (
  id           uuid primary key default gen_random_uuid(),

  -- Denormalised, no FK to auth.users — the same call audit_log.actor_id makes,
  -- for the same reason plus one more: an FK brings ON DELETE CASCADE with it,
  -- and deleting one account would take a year of retained conversation with it.
  -- Ownership is enforced by the policies below and by every RPC filtering
  -- p_owner_id, not by referential integrity.
  owner_id     uuid not null,

  -- Null until Phase 2 ships titling. Clamped in Flask before the RPC is
  -- called, never here: a length constraint enforced inside a SECURITY DEFINER
  -- function surfaces a client mistake as a 500.
  title        text check (title is null or char_length(title) between 1 and 120),

  created_at   timestamptz not null default now(),

  -- NO `before insert or update` touch trigger, unlike app_settings. That
  -- trigger bumps updated_at on any write, so merely opening a session would
  -- reorder a list sorted `updated_at desc` and the sidebar would shuffle on
  -- read. chat_append_turn sets this explicitly, so it means "last spoken in".
  updated_at   timestamptz not null default now(),

  -- Message order is a per-session counter, never a timestamp. Migration
  -- 20260817161427 exists because same-millisecond created_at produced
  -- non-deterministic page boundaries in the People list; the same bug in a
  -- transcript reorders a question and its answer.
  next_seq     bigint not null default 1 check (next_seq > 0),

  -- Exists only so chat_messages can carry a composite FK on (session_id,
  -- owner_id). That is what makes "a message in my session is owned by me"
  -- a database invariant rather than an application promise.
  constraint chat_sessions_id_owner_key unique (id, owner_id)
);

create index if not exists chat_sessions_owner_updated_idx
  on public.chat_sessions (owner_id, updated_at desc, id desc);

create table if not exists public.chat_messages (
  id                uuid primary key default gen_random_uuid(),
  session_id        uuid not null,
  owner_id          uuid not null,
  seq               bigint not null,
  role              text not null check (role in ('user', 'assistant')),
  content           text not null,

  -- Client-minted, one per logical submission, reused across retries. Server
  -- minting was considered and rejected: a retry would mint a fresh id and the
  -- idempotency would be decorative.
  client_request_id uuid not null,

  -- Answer metadata, written on the ASSISTANT ROW ONLY and left null on the
  -- user row. Both readings pass the schema, so the choice is stated here and
  -- asserted by a test — otherwise two exports of the same data disagree.
  corpus_revision   text,
  model             text,
  lang              text,
  category          text,

  created_at        timestamptz not null default now(),

  constraint chat_messages_session_owner_fk
    foreign key (session_id, owner_id)
    references public.chat_sessions (id, owner_id) on delete cascade,
  constraint chat_messages_order_key unique (session_id, seq),
  constraint chat_messages_idem_key  unique (session_id, client_request_id, role)
);

-- The FK's index (README rule 4), and it has to be THIS pair. The foreign key
-- is on (session_id, owner_id); an index on (session_id, seq) does not satisfy
-- rule 4 and the performance advisor flags it. It is also not a free extra:
-- `chat_messages_order_key unique (session_id, seq)` already creates an index
-- on exactly (session_id, seq), so a hand-rolled one beside it is a pure
-- duplicate — twice the write cost, no read ever served by the second copy.
-- Ordered reads use the unique constraint's index; this one serves the cascade
-- and the owner filter.
create index if not exists chat_messages_session_owner_idx
  on public.chat_messages (session_id, owner_id);

create table if not exists public.chat_message_sources (
  id             bigint generated always as identity primary key,
  message_id     uuid not null references public.chat_messages(id) on delete cascade,

  -- MUST equal the [n] label the model saw in its prompt context. That equality
  -- is the whole citation contract (web/services/citations.py), and as a column
  -- under a unique constraint the database enforces it instead of the code
  -- hoping for it.
  --
  -- The bound mirrors CITATION_MARKER's [0-9]{1,2}. Do not relax it: a 3-digit
  -- marker is not recognised as a citation on either side of the wire, so a
  -- source numbered 100 would render with nothing pointing at it.
  source_index   integer not null check (source_index between 1 and 99),

  -- Every RETRIEVED passage is stored, not only the cited ones. _finalize_answer
  -- discards the uncited ones and keeps a count; for quality review the
  -- retrieval set is the signal — what was offered and not used is as
  -- informative as what was — and it is unrecoverable later, because retrieval
  -- is not reproducible across a corpus rebuild.
  cited          boolean not null,

  document       text not null,
  page           integer,
  category       text not null,
  score          double precision,
  semantic_score double precision,
  lexical_score  double precision,
  chunk_id       text,

  -- _snippet caps at SNIPPET_CHARS (320) and may append one "…".
  snippet        text not null check (char_length(snippet) <= 321),

  constraint chat_message_sources_unique_index unique (message_id, source_index)
);

-- NO standalone index on message_id. `chat_message_sources_unique_index unique
-- (message_id, source_index)` already provides one leading with message_id,
-- which serves both the FK cascade and every read here — sources are only ever
-- fetched for a known message. A second index on the same leading column is
-- write cost with no reader.

comment on table public.chat_sessions is
  'One durable conversation. Readers select and delete their own through RLS; '
  'content is written only by public.chat_append_turn.';
comment on table public.chat_messages is
  'One row per message. Ordered by (session_id, seq) — never by created_at.';
comment on table public.chat_message_sources is
  'Every retrieved passage for an assistant message, cited or not. source_index '
  'equals the [n] the model saw.';

-- ---------------------------------------------------------------------------
-- Policies and grants
-- ---------------------------------------------------------------------------
-- auth.uid() is wrapped as (select auth.uid()) so the planner evaluates it once
-- per statement rather than once per row.
--
-- No policy for INSERT or UPDATE anywhere below, and no grant to match: see the
-- forgery argument at the top of this file. Do not "fix" this by adding one.

alter table public.chat_sessions        enable row level security;
alter table public.chat_messages        enable row level security;
alter table public.chat_message_sources enable row level security;

drop policy if exists chat_sessions_select_own on public.chat_sessions;
create policy chat_sessions_select_own on public.chat_sessions
  for select to authenticated
  using (owner_id = (select auth.uid()));

drop policy if exists chat_sessions_delete_own on public.chat_sessions;
create policy chat_sessions_delete_own on public.chat_sessions
  for delete to authenticated
  using (owner_id = (select auth.uid()));

drop policy if exists chat_messages_select_own on public.chat_messages;
create policy chat_messages_select_own on public.chat_messages
  for select to authenticated
  using (owner_id = (select auth.uid()));

drop policy if exists chat_message_sources_select_own on public.chat_message_sources;
create policy chat_message_sources_select_own on public.chat_message_sources
  for select to authenticated
  using (
    exists (
      select 1 from public.chat_messages m
       where m.id = chat_message_sources.message_id
         and m.owner_id = (select auth.uid())
    )
  );

revoke all on public.chat_sessions        from anon, authenticated;
revoke all on public.chat_messages        from anon, authenticated;
revoke all on public.chat_message_sources from anon, authenticated;

-- Delete on chat_sessions only. The cascade carries messages and sources, so a
-- direct delete grant on the children would add a way to punch a hole in a
-- transcript — an answer without its question — and buy nothing.
grant select, delete on public.chat_sessions to authenticated;
grant select on public.chat_messages        to authenticated;
grant select on public.chat_message_sources to authenticated;

-- AND THE SERVICE ROLE LOSES DIRECT WRITES TOO. This is what turns "message
-- content is written only by chat_append_turn" from a convention the
-- application happens to follow into a property the database enforces.
--
-- Revoking from anon and authenticated alone left the claim resting on Flask's
-- good behaviour: Supabase grants service_role broad DML by default, so any
-- code path holding the service key could have inserted an assistant row
-- directly — the provenance-forgery primitive this whole section exists to
-- close, just from the server side instead of the browser.
--
-- It does not break the RPCs. They are SECURITY DEFINER, which executes with
-- the privileges of the function OWNER, not the caller; the caller needs only
-- EXECUTE, which is granted below. The owner also bypasses RLS as the table
-- owner, which is what lets the functions read and write across owners.
--
-- SELECT is deliberately kept: reads are harmless (Flask already sees
-- everything through the RPCs) and removing it would break ad-hoc inspection
-- for no gain.
--
-- VERIFY THIS AT APPLY TIME. It is the one statement here whose effect depends
-- on the project's default privileges and on the functions being owned by the
-- same role that owns the tables. If chat_append_turn fails with a permission
-- error after applying, this is why — and the fix is to correct the function
-- owner, not to re-grant the writes.
-- REVOKE ALL then grant back SELECT, rather than naming three verbs. Naming
-- insert/update/delete leaves TRUNCATE, REFERENCES and TRIGGER standing, and
-- Supabase's default table ACL for service_role can include them — so a
-- `truncate public.chat_message_sources` would still erase every citation in
-- the system, bypassing RLS, through a privilege the revoke had not thought to
-- name. Deny-by-default and grant what is needed is the only form of this that
-- stays correct when Postgres adds a privilege.
revoke all on public.chat_sessions        from service_role;
revoke all on public.chat_messages        from service_role;
revoke all on public.chat_message_sources from service_role;

grant select on public.chat_sessions        to service_role;
grant select on public.chat_messages        to service_role;
grant select on public.chat_message_sources to service_role;

-- ---------------------------------------------------------------------------
-- The archive
-- ---------------------------------------------------------------------------
-- Append-only IN A WEAKER SENSE THAN audit_log, and the difference is worth
-- stating rather than glossing. audit_log's second lock is a `before update or
-- delete` trigger that raises unconditionally. This table cannot have one,
-- because admin_purge_chat_archive must be able to delete — the 24-month
-- ceiling and the withdrawal path are both deletes. So the archive is
-- append-only EXCEPT through one SECURITY DEFINER path, and that path is the
-- whole exposure.

create table if not exists public.chat_archive (
  id              bigint generated always as identity primary key,
  occurred_at     timestamptz not null default now(),

  -- HMAC-SHA256 digests computed by Flask from a VERIFIED id. Never a raw
  -- owner_id, never the live session uuid, and never read from a request body —
  -- a caller who supplies its own digest controls the mapping.
  owner_key       text not null,
  session_key     text not null,

  -- = client_request_id. Without the unique constraint below a replayed turn
  -- skips the message rows (they conflict) and inserts a SECOND archive row,
  -- silently double-weighting one exchange.
  turn_key        uuid not null,

  question        text not null,
  answer          text not null,

  -- JSONB here and rows in chat_message_sources is not an inconsistency. The
  -- reader table needs per-source constraints because a citation has to
  -- resolve; the archive needs a faithful snapshot and is never queried per
  -- source.
  sources         jsonb not null,

  lang            text,
  category        text,
  model           text,
  corpus_revision text,

  -- Scoped to the SESSION as well, matching chat_messages' own idempotency key
  -- `unique (session_id, client_request_id, role)`. Keyed on (owner_key,
  -- turn_key) alone the two disagreed: one request id reused across two
  -- conversations writes both turns to the reader's history and only the first
  -- to the archive, so the archive would silently hold fewer turns than
  -- happened and nothing would say which one it dropped.
  constraint chat_archive_turn_key unique (owner_key, session_key, turn_key)
);

create index if not exists chat_archive_occurred_idx
  on public.chat_archive (occurred_at desc);
create index if not exists chat_archive_owner_idx
  on public.chat_archive (owner_key, occurred_at desc);

-- RLS enabled with ZERO POLICIES, deliberately (README rule 5). The advisor
-- reports rls_enabled_no_policy as INFO; that is intent, not oversight. A
-- policy is how you would let the browser in, and nothing in a browser has any
-- business here.
alter table public.chat_archive enable row level security;

revoke all on public.chat_archive from anon, authenticated;
-- DELETE IS REVOKED HERE, not granted in advance.
--
-- The comment below used to say deletion existed "solely so
-- admin_purge_chat_archive can enforce the retention ceiling" — while that
-- function ships in a later migration and does not exist yet. A standing
-- DELETE grant with nothing allowed to use it is not a controlled purge path;
-- it is an uncontrolled one with a promise attached. The migration that adds
-- the purge RPC grants the DELETE it needs, in the same file, where the two can
-- be read together.
revoke update, delete, truncate on public.chat_archive from service_role;
grant insert, select on public.chat_archive to service_role;

comment on table public.chat_archive is
  'Append-only turn archive for quality review and internal model work. '
  'Service-role insert/select only; RLS enabled with no policies by design. '
  'UPDATE and DELETE are revoked. The migration that adds '
  'admin_purge_chat_archive grants the DELETE that function needs.';

-- ---------------------------------------------------------------------------
-- chat_append_turn — the only way message content is ever written
-- ---------------------------------------------------------------------------
-- One call, one transaction: session (created lazily), both message rows, every
-- source row, updated_at, and the archive row. Splitting these would let the
-- half that fails always be the one that mattered.
--
-- Idempotency. A replayed p_client_request_id returns the existing ids, writes
-- nothing, and — this is the part that is easy to get wrong — does NOT advance
-- next_seq. An advancing counter on a no-op leaves gaps, and a gap is
-- indistinguishable from a deleted message to anything reading the transcript.
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
  p_archive_opted_out boolean
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
  insert into public.chat_sessions (id, owner_id)
  values (p_session_id, p_owner_id)
  on conflict (id) do nothing;

  -- Ownership check and serialisation point in one. If the row already existed
  -- under a different owner the insert above did nothing and this finds
  -- nothing, so a caller cannot append into someone else's conversation by
  -- guessing its id. Holding the lock also makes the replay probe below safe
  -- against two concurrent submissions of the same request id.
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

    return query select p_session_id, v_user_id, v_assistant_id, true;
    return;
  end if;

  -- `update … returning` rather than `select … for update` then `update`. The
  -- second is what most people write and it is both slower and racier.
  -- RETURNING sees the NEW value, so `next_seq - 2` is the pair we just claimed.
  update public.chat_sessions
     set next_seq = next_seq + 2,
         updated_at = now()
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
  uuid, uuid, uuid, text, text, jsonb, text, text, text, text, text, text, boolean
) from anon, authenticated, public;
grant execute on function public.chat_append_turn(
  uuid, uuid, uuid, text, text, jsonb, text, text, text, text, text, text, boolean
) to service_role;

-- ---------------------------------------------------------------------------
-- chat_load_session — hydration, bounded, newest-window-first
-- ---------------------------------------------------------------------------
-- Sources ride along per message so hydrating a transcript is one round trip
-- rather than one plus N.
--
-- p_limit selects the NEWEST p_limit messages and returns them oldest-first,
-- which is the window a reader continues from. Unbounded hydration would meet
-- citations.js's MAX_TRACKED_ANSWERS cap of 100 and silently drop the citation
-- controls off the oldest answers — on the product whose central claim is that
-- every answer carries a resolvable source. Flask clamps p_limit to the [1,200]
-- the People pager already uses.
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
         coalesce(
           (select jsonb_agg(
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
                   )
              from public.chat_message_sources src
             where src.message_id = w.id),
           '[]'::jsonb
         )
    from window_rows w
   order by w.seq;
$$;

revoke execute on function public.chat_load_session(uuid, uuid, integer, bigint)
  from anon, authenticated, public;
grant execute on function public.chat_load_session(uuid, uuid, integer, bigint)
  to service_role;

-- ---------------------------------------------------------------------------
-- chat_latest_session — the current-session rule's fallback
-- ---------------------------------------------------------------------------
-- Called only when the browser presents NO conversation id at all: a new
-- device, a cleared browser, or the request after a logout. A cookie that holds
-- an id the reader started deliberately — including the empty one "New chat"
-- mints — is honoured as-is, because otherwise the next page reload would
-- restore the conversation they just ended. See the plan's §5.
create or replace function public.chat_latest_session(p_owner_id uuid)
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
  select s.id
    from public.chat_sessions s
   where s.owner_id = p_owner_id
   order by s.updated_at desc, s.id desc
   limit 1;
$$;

revoke execute on function public.chat_latest_session(uuid)
  from anon, authenticated, public;
grant execute on function public.chat_latest_session(uuid) to service_role;
