---
authority: historical
status: superseded
do_not_implement: true
archived: 2026-08-20
supersedes_note: >
  This document is a finished plan. Parts of it were reversed before shipping.
  It is a record of what was decided and what it cost, not a specification.
live_authority:
  - docs/ARCHITECTURE.md
  - supabase/README.md
  - DESIGN.md
---

> [!CAUTION]
> **You are reading history, not a specification.** Do not implement anything found
> in this file without first confirming it against `docs/ARCHITECTURE.md` or the code.
> Every heading below is prefixed `[HISTORICAL]` so a search result cannot be mistaken
> for current design.

STATUS: HISTORICAL RECORD — all eight steps complete 2026-08-21. Archived 2026-08-23.
Nothing here is an instruction. Live rules: `docs/ARCHITECTURE.md`, `supabase/README.md`.

**Four positions in this document were reversed after it was written. Do not implement
any of them:**

1. **The cookie-held `conv_id`, the "current-session rule" (§5) and
   `CHAT_RESUME_LATEST_SESSION`.** All deleted. The URL is the pointer — see
   `docs/ARCHITECTURE.md`. `web/tests/test_session_isolation.py` carries a note so the
   resume machinery cannot quietly return.
2. **"Only a `verified` citation renders as openable evidence" (§3).** Reversed in step 5:
   a stale citation still opens. Classification drives *disclosure*, not *access*.
3. **"Step 8 is the first feature to call `chat_sessions_delete_own` from a browser"
   (§8/§9).** Reversed. The browser never touches the chat tables; `chat_delete_session`
   was re-added as an RPC behind a Flask route.
4. **§7 in its entirety** — consent columns, routes, purge/export/frequency RPCs, the CLI
   and the JSONL export — was **cut, not deferred**. Some of it returned in a different
   shape via the profile refactor; read that plan, not this section.

This document also says of itself that revision 2 contradicted itself badly enough to need
a clean rewrite. Read it as a record of how the thinking moved, and take
`docs/ARCHITECTURE.md` as what the system does.

# [HISTORICAL] Save Chat Sessions Per User — Implementation Plan

Planning record for the `TODO.md` *Planned work* entry **"Save chat sessions per
user"**. Written the same way as
[2026-08-17_pagination.md](2026-08-17_pagination.md): the
useful half is the cost.

**Revision 4 — steps 1-4 are done: applied 2026-08-20 as
`supabase/migrations/20260820131914_chat_session_persistence.sql`, and `chat_persistence` is live
in `config.yaml`.** Revision 2
was revised in place enough times that it began contradicting itself, so revision 3 was a
clean rewrite; revision 4 folds in what implementation actually found. §11 records what each
pass caught, and §8 carries a status column. Where the plan and the code now disagree, the
code is right and the paragraph says so rather than being quietly deleted.

**What implementation changed in the plan:** §5's third cookie state was cut (the rule only
needed stating correctly), §9's per-turn round trip was overpriced by a factor of a
conversation, §6's "vacuous assertions" turned out to be loud failures, and step 1 shed the
consent columns, the admin RPCs and `chat_delete_session`.

**What two post-implementation bug hunts changed.** The most important finding was not a
bug at all but a coherence argument: **the resume rule now ships behind a flag that is OFF**
(`CHAT_RESUME_LATEST_SESSION`). The visible transcript still restores from per-tab
`sessionStorage` until step 6, so every case where the fallback fires — new device, new
tab, the request after a logout — would show a reader a blank screen while the model
silently received the conversation behind it. Two halves of one feature, disagreeing, on an
assistant whose whole claim is that a reader can check where an answer came from. The
machinery is built and tested; step 6 flips the flag. See §5.

The rest, in order of how much they were worth:

- **The test double was laxer than the schema.** It accepted `source_index = 150`, a
  400-character snippet and a null document — three CHECK constraints that every test in
  the suite was silently failing to assert, because the double is what tests run against.
  `InMemoryChatBackend._validate_sources` now mirrors the schema, and round 2 caught that
  the first version of that fix validated *before* the replay check while the RPC returns
  *after* it — making the double stricter than Postgres on the one path where that is wrong.
- **A cold-hydration race.** `_load_history` reads an empty window, goes to Postgres, and
  installs what it found; the lock inside each store method does not span that gap, so two
  tabs could have the slower one erase a completed turn. `replace()` now refuses to
  overwrite a non-empty window.
- **`revoke all` rather than three named verbs.** Revoking `insert, update, delete` from
  `service_role` left `TRUNCATE` standing, and Supabase's default table ACL can include it —
  a single statement would have erased every citation in the system while bypassing RLS.
- **Two redundant indexes and a missing FK index.** `unique (session_id, seq)` already
  indexed exactly what `chat_messages_session_seq_idx` re-indexed, while the actual foreign
  key `(session_id, owner_id)` had none.
- **A `DELETE` grant on the archive with nothing allowed to use it**, described in a comment
  as existing "solely so `admin_purge_chat_archive` can…" — a function that ships in step 7.
- **A JSON scalar `null` aborts `jsonb_array_elements`**, rolling back a turn the reader is
  already reading. `coalesce` catches SQL NULL only.
- **Client-side:** the last error frame overwrote the first, so a reader whose answer merely
  went unsaved was told their message failed to send; and suppressing the mascot's error
  state under a complete answer left it animating forever, because that branch returns
  before the happy path's `returnToIdle`.

## [HISTORICAL] Provenance

| Pass | Who | Contributed |
|---|---|---|
| Research | Antigravity `gemini-3.7-flash-high` | Community practice, failure taxonomy |
| Design | OpenCode `gpt-5.6-luna` (xhigh, read-only) | Independent schema |
| Docs | Context7 `/supabase/supabase` | RLS, cascade, indexing guidance |
| Reviews A, B | external, no codebase access | Corpus-loss paths, `seq` ambiguity, operational gaps |
| Debate | Claude Opus, read-only | 17 gaps; the argument to delete the state machine |
| Fresh eyes | Claude Opus, read-only | 15 internal contradictions; the proportionality argument |
| Bug hunt ×2 | OpenCode `gpt-5.6-sol`, read-only | Post-implementation. Round 1: the laxer test double, the cold-hydration race, redundant indexes, the archive delete grant. Round 2: defects in round 1's own fixes, and the transcript-coherence argument that gated the resume rule |

Claims from reviews A and B that did **not** survive verification are in §12, so they
are not re-inherited.

---

## [HISTORICAL] 0. Verified against the current source

Re-read here before being built on. **Bold rows changed the design.**

| Claim | Verdict |
|---|---|
| **`conv_id` is `uuid.uuid4().hex` — 32 chars, no dashes** | **Confirmed** — `app.py:559,1319,1495,1615`. A `uuid` column round-trips to the *dashed* form, so every cross-boundary equality silently fails. §2.5 |
| **TESTING identities are `"test-user-id"` etc. — not UUIDs** | **Confirmed** — `app.py:303-315`. `get_supabase()`/`get_supabase_admin()` return `None` under TESTING (`supabase_client.py:61,98,134`) |
| **A second bypass identity already exists** | **Confirmed** — `fake_admin_token` → `test-admin-id`. What is missing is a second *non-admin, non-disabled* reader; `fake_disabled_token` is intercepted at `app.py:523` |
| **`_truncate` assumes strict `[u,a,u,a,…]` alternation** | **Confirmed** — `conversation_store.py:175-183` |
| **`_finalize_answer` keeps only cited sources** | **Confirmed** — `app.py:608-620`. `cited` is sorted, deduped, and may be **sparse** |
| **`build_source_payload` emits `index`, not `source_index`, and has no `cited` key** | **Confirmed** — `citations.py:119-131`. §3 names the remap |
| **`read_active_build_id(processed_data_dir)` takes an argument and may return `None`** | **Confirmed** — `build_registry.py:116-128` |
| **`on[frame.event]?.()` silently drops unknown SSE events** | **Confirmed** — `services.js:237` |
| **`handlers.js` already anticipates a persistence failure** | **Confirmed** — the `failed` branch comment names *"suggestion generation, history persistence"* as auxiliary, renders the answer, toasts, and calls `RobotStateManager.showError()` (`handlers.js:506-525`) |
| **The request body is `{query, category, lang}`** | **Confirmed** — `services.js:204`. A client-minted id changes this file |
| **`_validate_chat_request` has no length cap** | **Confirmed** — strips, rejects empty, checks category and engine only (`app.py:1270-1295`) |
| **`audit_log.actor_id` is `uuid` with deliberately no FK** | **Confirmed** — *"an audit row that can no longer say who acted has lost the thing it exists to record"* (`20260814032447_audit_log.sql:22-27`) |
| **`audit_log`'s second lock is a `before update or delete` trigger** | **Confirmed** — `audit_log_is_append_only()` (`:65-98`). `chat_archive` **cannot** copy it; §3 |
| **Blocking route retrieves before minting a conversation** | **Confirmed** — `app.py:1469-1473`, pinned by `test_a_retrieval_failure_does_not_start_a_conversation` |
| **`profiles_guard_privilege_columns` is a deny-list** naming `role`, `tier`, `is_disabled` | **Confirmed** — `20260814005509…:174-186`, and the migration says the deny-list is deliberate |
| **`profiles` column grants are an allow-list** | **Confirmed** — `grant insert/update (id, full_name, organization, specialization, preferences)` (`:141-151`) |
| Both chat routes are `@auth_required` — **there are no guests** | **Confirmed** — `app.py:1298,1441` |
| `stateByMessage` caps at `MAX_TRACKED_ANSWERS = 100`, evicts oldest-first | **Confirmed** — `citations.js:62-71` |
| `neutraliseRestoredCitations` strips dead controls deliberately | **Confirmed** — `citations.js:214-228` |
| `_snippet` bounded at 321 chars | **Confirmed** — `citations.py:97-102` |
| `CITATION_MARKER` is `[0-9]{1,2}`; `_context_ceiling()` caps at `search_engine.k` | **Confirmed** — a source index >99 is unreachable |
| `chat_limit` defaults to `"10 per minute"`, shared across both routes | **Confirmed** — `app.py:1265-1268` |
| `updated_at` is maintained by a `before insert or update` trigger | **Confirmed** — `app_settings_touch_updated_at` (`20260814110200`) |
| An in-memory backend double is the house pattern | **Confirmed** — `AdminBackend` / `SupabaseAdminBackend` / `InMemoryAdminBackend` (`admin_store.py:93,185,391`) |
| `SUPABASE_BROWSER_MOCK` implements `auth` + a `profiles` chain only | **Confirmed** — `conftest.py:13-80` |

**Two table-access patterns exist here.** Browser-direct (`profiles`: policy admits the
row, **column grants** decide what may be written) and Flask-mediated (`app_settings`,
`audit_log`: RLS on, *no policies*, `revoke all from anon, authenticated`, RPC-only,
and *"Do not 'fix' this by adding a policy."*). The chat tables use both — §2.4.

---

## [HISTORICAL] 1. Owner decisions

1. **Reader-owned rows with real RLS** — `auth.uid() = owner_id`, chats restore on any
   device.
2. **Analysis and training** across all readers. Reverses a documented position — §6.
3. **Retention** — logout clears cookie and cache only, never durable rows.
4. ~~Persist in the view body~~ — **superseded, and the replacement is now ruled on:
   write at `final`** (2026-08-18). The reserve-then-finalise state machine is not
   built. §4.1 records why. **There are no open architectural decisions left.**
5. **Data sensitivity — owner ruling.** This is a controlled environment; questions
   concern published SFDA guidelines; patient and adverse-event narratives are not the
   expected use. The content is regulatory Q&A, not health data. §7's posture follows
   from this, and a proposal to exclude `data/pharmacovigilance/` turns from the
   archive was **declined as disproportionate**.
6. **Notice at first use, no gate.** Acceptance is a *record*, not a precondition —
   see §7.

---

## [HISTORICAL] 2. Design calls

### [HISTORICAL] 2.1 Message rows, written as a pair in one statement

`chat_messages`, one row per message. The pair-shaped alternative was argued for
(everything downstream is pair-shaped: `append_turn(conv, user, assistant, …)`,
`_truncate` dropping whole *pairs*, `_clamp` protecting the newest *exchange*) and not
taken.

**The interior-unpaired-row hazard is designed out rather than defended against.**
`_truncate` slices on a strict `[u,a,u,a,…]` assumption (`conversation_store.py:175-183`),
so `[u,a,u,u,a]` would corrupt the prompt window. Revision 2 answered that with a
pair-assembly builder joining on `client_request_id`. **That is now unnecessary work
and is cut**: `chat_append_turn` writes both rows in one statement (§3), a user row
without its assistant row is unreachable, and per-message deletion is in §8's
*deliberately not built*. What remains is `order by seq` plus **one test asserting the
rows arrive paired** — cheaper than a builder, and it fails loudly if the invariant
ever breaks.

If branching or message editing is ever wanted, this is the decision to reopen first.

### [HISTORICAL] 2.2 Citation sources as rows — **all** retrieved, not only cited

Rows, because the invariant at the top of `citations.py` — *"`sources[i]["index"]` must
equal the `[i]` label the model saw"* — is load-bearing, and as rows the database
enforces it via `unique (message_id, source_index)`.

**Persist every retrieved passage with a `cited boolean`.** `_finalize_answer`
(`app.py:608-620`) discards uncited passages and keeps only a count; for training the
retrieval set *is* the signal, positives and negatives both, and it is unrecoverable
later because retrieval is not reproducible across rebuilds. `retrieved` is already in
scope at that call site.

This makes the schema stricter: `source_index` equals the `[i]` the model saw for
**every** `i`. It also deletes `cited integer[]` and `retrieved integer` from
`chat_messages` — both derivable, and duplicating them is what creates drift.

### [HISTORICAL] 2.3 Ordering — a per-session `seq`

`next_seq` on the session, allocated with `update … returning` (not
`select … for update` then `update` — the second is what most people write and it is
the slower, racier one). `unique (session_id, seq)`. Never timestamps: migration
`20260817161427` exists because same-millisecond `created_at` produced
non-deterministic page boundaries in the People list.

One insert writes both rows, taking `next_seq` and `next_seq + 1`.

### [HISTORICAL] 2.4 RLS — readers read, the server writes

| Operation | Who | Mechanism |
|---|---|---|
| `SELECT` own sessions / messages / sources | Reader | RLS `owner_id = (select auth.uid())` |
| `DELETE` own session | Reader | RLS policy, cascading |
| `INSERT`/`UPDATE` message content | **Server only** | `security definer` RPC |

**Message content is not reader-writable**, a deliberate narrowing of §1.1. A reader
who can write `chat_messages` can author or rewrite an assistant answer and its
citation rows, and it renders as something *the system* said — a provenance forgery
primitive reachable from a browser console, on an assistant whose first principle is
resolvable sources.

No `grant update (title, …)` until Phase 2 ships rename: a column grant for a feature
that does not exist is untested surface, the same objection this section raises against
policies no code takes.

### [HISTORICAL] 2.5 Conversation ids must be canonicalised — a bug revision 1 would have shipped

`conv_id` is `uuid.uuid4().hex` — 32 chars, no dashes. A `uuid` column accepts it and
returns the dashed form, so the cache key `(owner_id, conversation_id)` gets two entries
for one session and any client-side comparison never matches.

**Mint `str(uuid.uuid4())`; normalise with `str(uuid.UUID(x))` at the Flask boundary
(never in SQL); pin with a test.**

---

## [HISTORICAL] 3. Schema

Reader history and the training archive are **separate tables with separate lifetimes**.
Folding them together is what made reader deletion, account deletion and admin cleanup
each destroy training data. Split, a reader's delete really deletes — a soft-deleted
regulatory conversation the reader was told was gone is worse than either alternative —
while the archive is append-only and governed by §7.

```sql
create table public.chat_sessions (
  id           uuid primary key default gen_random_uuid(),
  owner_id     uuid not null,          -- no FK; see below
  title        text check (title is null or char_length(title) between 1 and 120),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  next_seq     bigint not null default 1 check (next_seq > 0),
  constraint chat_sessions_id_owner_key unique (id, owner_id)
);
create index chat_sessions_owner_updated_idx
  on public.chat_sessions (owner_id, updated_at desc, id desc);

create table public.chat_messages (
  id                uuid primary key default gen_random_uuid(),
  session_id        uuid not null,
  owner_id          uuid not null,
  seq               bigint not null,
  role              text not null check (role in ('user','assistant')),
  content           text not null,
  client_request_id uuid not null,
  -- Answer metadata lives on the assistant row only (§3, "which row carries what").
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
create index chat_messages_session_seq_idx on public.chat_messages (session_id, seq);

create table public.chat_message_sources (
  id             bigint generated always as identity primary key,
  message_id     uuid not null references public.chat_messages(id) on delete cascade,
  -- Mirrors CITATION_MARKER's [0-9]{1,2}. Do not relax: a 3-digit marker is not
  -- recognised as a citation on either side.
  source_index   integer not null check (source_index between 1 and 99),
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
create index chat_message_sources_message_idx on public.chat_message_sources (message_id);
```

**`owner_id` carries no FK to `auth.users`**, following `audit_log.actor_id`, whose
migration already argues the case. It also removes the cascade that would wipe a year of
data on account deletion. Ownership is enforced by the RLS policy and by every RPC
filtering `p_owner_id`.

**Which row carries what.** `content` is the message text on both rows. `corpus_revision`,
`model`, `lang` and `category` are written on the **assistant row only** and left null on
the user row — both readings pass the schema, so the choice is stated here and asserted by
a test, or two exports disagree.

**No touch trigger on `chat_sessions`.** The house `before insert or update` trigger would
bump `updated_at` on any write, so merely opening a session would reorder a list sorted
`updated_at desc`. `updated_at` is set explicitly by `chat_append_turn`.

**`title` is not written by `chat_append_turn`.** It stays null until Phase 2 ships
titling. When it does, the title is **clamped in Flask before the RPC**, never allowed to
hit `char_length(title) between 1 and 120` — a length constraint enforced inside an RPC
surfaces a client error as a 500.

### [HISTORICAL] Policies and grants

```sql
alter table public.chat_sessions        enable row level security;
alter table public.chat_messages        enable row level security;
alter table public.chat_message_sources enable row level security;

create policy chat_sessions_select_own on public.chat_sessions
  for select to authenticated using (owner_id = (select auth.uid()));
create policy chat_sessions_delete_own on public.chat_sessions
  for delete to authenticated using (owner_id = (select auth.uid()));

create policy chat_messages_select_own on public.chat_messages
  for select to authenticated using (owner_id = (select auth.uid()));

create policy chat_message_sources_select_own on public.chat_message_sources
  for select to authenticated
  using (exists (select 1 from public.chat_messages m
                 where m.id = chat_message_sources.message_id
                   and m.owner_id = (select auth.uid())));

revoke all on public.chat_sessions, public.chat_messages,
              public.chat_message_sources from anon, authenticated;
grant select, delete on public.chat_sessions to authenticated;
grant select on public.chat_messages, public.chat_message_sources to authenticated;
```

`auth.uid()` is wrapped as `(select auth.uid())` so it evaluates once per statement, and
`owner_id` leads `chat_sessions_owner_updated_idx`. On `chat_messages` the access path is
always `session_id` — hydration is per session — which `chat_messages_session_seq_idx`
leads.

### [HISTORICAL] The archive

```sql
create table public.chat_archive (
  id              bigint generated always as identity primary key,
  occurred_at     timestamptz not null default now(),
  -- HMAC-SHA256 digests computed by Flask from a verified id (§7). Never a raw
  -- owner_id, never the live session uuid, never client-supplied.
  owner_key       text not null,
  session_key     text not null,
  turn_key        uuid not null,   -- = client_request_id; the idempotency anchor
  question        text not null,
  answer          text not null,
  sources         jsonb not null,
  lang            text,
  category        text,
  model           text,
  corpus_revision text,
  -- Without this, a replayed turn skips the message rows and inserts a SECOND
  -- archive row — the failure the "one row per turn" test exists to catch.
  constraint chat_archive_turn_key unique (owner_key, turn_key)
);
create index chat_archive_occurred_idx on public.chat_archive (occurred_at desc);
create index chat_archive_owner_idx    on public.chat_archive (owner_key, occurred_at desc);

alter table public.chat_archive enable row level security;
revoke all on public.chat_archive from anon, authenticated;
revoke update, delete, truncate on public.chat_archive from service_role;
```

Append-only **in a weaker sense than `audit_log`**, and the difference is worth stating
rather than glossing: `audit_log`'s second lock is a `before update or delete` trigger
(`20260814032447_audit_log.sql:65-98`). `chat_archive` cannot have one, because
`admin_purge_chat_archive` must delete. So the archive is append-only *except through one
`security definer` path*, and that path is the whole exposure.

JSONB here and rows there is not an inconsistency: the reader table needs per-source
constraints because a citation must resolve; the archive needs a faithful snapshot and is
never queried per source.

### [HISTORICAL] Stale sources — fail closed, cheaply

Revision 1 required a `chunk_sha256` over the full chunk text. That is **unimplementable**:
persistence consumes `build_source_payload`, which carries `snippet` and never `text`. And
nothing here resolves a `chunk_id` — it is only constructed (`data_processing.py:248`) and
serialised — so verification would mean a pandas column scan per source on the hydration
path.

**Replaced by one string comparison per message:** the message's `corpus_revision` against
the active build id. Builds are immutable directories, so a different build is the only
case that matters.

`read_active_build_id(processed_data_dir)` **takes an argument and returns `None` for the
legacy flat layout** (`build_registry.py:116-128`). A null on either side resolves to
`unverifiable`, not `verified`. The engine caches the active id at load rather than
reading the pointer file per turn.

Three states: `verified` (equal), `stale` (different), `unverifiable` (either side null).

~~Only `verified` renders as openable evidence. **No document/page fallback** — a document
and page can plausibly match the wrong passage, and a confidently wrong citation is the
worst outcome available here.~~

**Reversed in step 5 (2026-08-20). A stale citation still opens; what changes is what the
reader is told.** The rule above is right about the act it describes and wrong about the act
hydration performs, and the two were conflated. Re-resolving a `chunk_id` against a rebuilt
index *can* surface a plausible but wrong passage — nothing does that, and nothing should.
But `chat_message_sources` stores the document, page, category and snippet **frozen at write
time**, so opening a stored citation shows what the model actually read. That is a record,
not a lookup, and withholding it hides the audit trail rather than protecting it.

Kept strictly the rule had two costs it did not price. One corpus rebuild would deaden every
citation in every stored conversation **at once**, on the surface built for a reader auditing
an answer. And an answer whose markers reverted to plain text with no trigger is
indistinguishable from an answer that cited nothing — the same *control that does nothing*
failure `neutraliseRestoredCitations` was written to avoid, arrived at from the other side.

So the three states survive as classification and drive disclosure, not access: `verified`
says nothing, while `stale` and `unverifiable` share one badge and one explanatory line,
because to a reader they mean the same thing. They remain distinct in the payload, in logs
and in tests.

One consequence worth stating: **`evidence_state` on a LIVE answer is asserted, not
computed.** A fresh answer came from the active index, so its currency is known rather than
inferred; and computing it there would mark every fresh answer `unverifiable` on a
deployment where `read_active_build_id` finds no pointer — badging the one case beyond
doubt.

### [HISTORICAL] RPC signatures

All `security definer`, `set search_path = ''`, execute revoked from `anon`,
`authenticated`, `public`, granted to the service role. Every one takes `p_owner_id` first
and filters on it.

```sql
-- Creates the session when p_session_id has no row (lazy creation), allocates
-- next_seq/next_seq+1, writes both message rows, all source rows, updated_at,
-- and the archive row unless p_archive_opted_out.
-- On a replayed client_request_id: returns the existing session/message ids and
-- writes nothing (on conflict do nothing), so next_seq does NOT advance.
chat_append_turn(
  p_owner_id          uuid,
  p_session_id        uuid,          -- caller pre-mints; canonicalised in Flask
  p_client_request_id uuid,
  p_question          text,
  p_answer            text,
  p_sources           jsonb,         -- expanded to rows; the document is never stored
  p_lang              text,
  p_category          text,
  p_model             text,
  p_corpus_revision   text,
  p_owner_key         text,          -- computed by Flask, never by the client
  p_session_key       text,
  p_archive_opted_out boolean
) returns table (session_id uuid, user_message_id uuid, assistant_message_id uuid, replayed boolean)

-- Ordered by seq. Sources come back in the same call to avoid an N+1 on hydration.
-- p_limit is clamped in Flask to the same [1,200] the People pager uses.
chat_load_session(p_owner_id uuid, p_session_id uuid, p_limit int, p_before_seq bigint default null)
  returns table (...)

-- Returns the owner's most recently updated session id, or null. Backs the
-- current-session rule (§5).
chat_latest_session(p_owner_id uuid) returns uuid

chat_delete_session(p_owner_id uuid, p_session_id uuid) returns void
chat_list_sessions(p_owner_id uuid, p_limit int, p_offset int) returns table (...)  -- Phase 2
```

Admin, §6:

```sql
-- Frequency analysis. No transcripts: grouped question text and counts only.
admin_chat_question_frequency(p_from timestamptz, p_to timestamptz, p_lang text,
                              p_limit int) returns table (question text, asked_count bigint, ...)

-- The ONLY delete path on the archive. Both-null is refused: without this guard a
-- call with two omitted arguments deletes the entire archive.
admin_purge_chat_archive(p_before timestamptz, p_owner_key text) returns bigint
  -- raise when p_before is null and p_owner_key is null

admin_export_chat_archive(p_from timestamptz, p_to timestamptz, p_lang text,
                          p_corpus_revision text) returns setof ...

admin_delete_chat_sessions(p_before timestamptz, p_owner_id uuid) returns bigint
```

---

## [HISTORICAL] 4. The write path

### [HISTORICAL] 4.1 Write at `final` — **decided 2026-08-18**

Revision 1 built a reserve-then-finalise state machine. It is deleted, for four reasons:

- **It breaks a guarantee that has a test.** Streaming retrieval happens *inside*
  `generate()` (`app.py:1334`), so reserving in the view body means a `SearchEngineError`
  leaves a durable session and an orphan question. The blocking route deliberately
  retrieves first, pinned by `test_a_retrieval_failure_does_not_start_a_conversation`
  (`app.py:1469-1473`).
- **It costs time-to-first-byte**, and the reason given for "view body" does not apply to
  it: the `Set-Cookie` constraint governs *Flask session writes*, not a Supabase RPC.
- **Its `GeneratorExit` handler can swallow the re-raise.** `app.py:1406-1420` is
  `except GeneratorExit: log; raise`; a network RPC before that `raise` can replace the
  exception, so `stream_response`'s context manager never closes the upstream connection —
  the exact leak the handler exists to prevent.
- **It buys one thing**: a durable record of a question whose answer was aborted. Against
  a status enum, a lease, a startup sweep, an abort RPC, 409 semantics, and a
  `status = 'complete'` policy that then hides the truth from the UI.

Today an aborted question leaves no record and nobody has reported that as a problem, so
this keeps current semantics exactly while deleting the machinery.

**Ruled 2026-08-18: write at `final`.** The consequence to accept knowingly is the one
thing the reserve design bought — a question whose answer was aborted mid-stream leaves
**no durable trace at all**, exactly as today. If the logs later show abandoned questions
matter, the reserve design is recoverable from this document's git history; it is not a
decision this plan leaves open.

### [HISTORICAL] 4.2 The shape

Ordering is preserved exactly as `app.py:1384-1398` requires — `final` → durable →
`suggestions` → `done` — because that ordering was itself a fix.

1. **View body:** resolve `conv_id` (canonicalised, §2.5), apply the current-session rule
   (§5), load history.
2. **`generate()`:** `meta` (carrying `conversation_id`) → `stage:*` → retrieval →
   `delta` × n → `final`.
3. **`chat_append_turn`** — one call, one transaction.
4. `suggestions`, then `done`.

**`conversation_id` rides `meta`, `final` and `done` only — never `delta`.** A delta frame
is `{"t": token}` (`app.py:1351`); a uuid per token adds ~29KB to an 800-token answer, and
the client already has `AbortController` (`services.js:155,194,269`) plus a generation
stamp (`handlers.js:309`) to discard a stale stream.

**Idempotency.** `client_request_id` is **client-minted** — `crypto.randomUUID()` per
logical submission, reused across retries. That means `services.js:204`
(`body: JSON.stringify({query, category, lang})`) and `_validate_chat_request`
(`app.py:1270-1295`) both change, and the id is echoed in `meta`. Server-minting was
rejected: a retry would mint a new id and the idempotency would be decorative.
`unique (session_id, client_request_id, role)` plus `on conflict do nothing` makes a
replay a genuine no-op — **and `next_seq` must not advance on a replay**, or the sequence
gaps. `chat_archive`'s `unique (owner_key, turn_key)` gives the archive the same property;
without it a replay skips the message rows and inserts a second archive row.

**`persistence_unavailable` is an `error` frame, not a new event name.**
`on[frame.event]?.()` (`services.js:237`) silently drops unregistered names. As an `error`
frame, `handlers.js:449` captures it and `506-525` already does the right thing — the
comment there names *"history persistence"* explicitly. Two edits are still needed at that
site: the toast becomes `chat.persistenceUnavailable` rather than `chat.sendFailed`, and
**`RobotStateManager.showError()` (`handlers.js:524`) must not fire** when `handle.final`
is set — the mascot entering an error state under a complete, correctly cited answer
contradicts the answer.

**Persistence under TESTING.** `PERSISTENCE_ENABLED` and an `InMemoryChatBackend` are not
alternatives — revision 2 required both and they exclude each other. Resolved: a
`ChatBackend` Protocol with `SupabaseChatBackend` and `InMemoryChatBackend`, mirroring
`admin_store.py:93,185,391`. **Under TESTING the in-memory backend is selected and
persistence is ON**, so every promised test can actually run; it stores by string key and
performs no uuid cast, which is why `test-user-id` works. `PERSISTENCE_ENABLED` is a
deploy flag for a Supabase-less deployment, not a test switch. Production carries a second
hazard: `user_id = str(getattr(user, "id", None) or user.email)` (`app.py:479`) can yield
an email, so the Flask boundary guards with `uuid.UUID(x)` and degrades to cache-only with
a log rather than raising.

**`ConversationStore` is re-keyed to `(owner_id, conversation_id)` and remains the
computed prompt window.** It is *not* a cache of these rows: `append_turn` writes back what
`_truncate` returned and `_clamp` rewrites content with `ELISION_NOTICE`
(`conversation_store.py:96-97,131-151`), so it holds different text from the rows. Calling
it write-through would let a restart change the prompt mid-conversation. **History is read
from Postgres once per turn** — the fork revision 2 left open is closed this way, and §9
prices the round trip. The re-key changes `get`/`append_turn` signatures at ~45 call sites
across `test_chat_stream.py`, `test_new_chat.py` and `test_session_isolation.py`; that is
scheduled in step 2, not left implicit.

**Reset and undo** keep their mechanism, with one addition in §5: `forget` and a second
reset drop the cookie *pointer* only and never delete a durable session. Session rows are
created lazily on first append, so `/api/conversation/reset` (30/min) cannot fill a sidebar
with empty sessions.

---

## [HISTORICAL] 5. The current-session rule — and the resurrection bug it must not cause

After sign-in on a new device there is no cookie and no sidebar, and the language toggle
reloads the page, so a rule is required in Phase 1, not Phase 2:

> **owned cookie with a durable row → else that owner's latest `updated_at`
> (`chat_latest_session`) → else create lazily on first append.**

**Naively, that rule resurrects exactly what *New chat* destroys.** Three paths:

1. After a reset the cookie holds a freshly minted id with **no durable row**, so the first
   branch fails, the fallback fires, and the next language toggle restores the conversation
   the reader just ended.
2. `test_a_late_append_cannot_resurrect_a_reset_conversation` (`test_new_chat.py:152`) holds
   today only because a late append lands on a rotated id nothing will ever read again. With
   durable rows that append writes real rows and bumps `updated_at`, making the abandoned
   session the newest.
3. Undo calls `store.clear(current)` (`app.py:1576-1577`), which drops RAM only — so the
   session just undone is the newest by `updated_at` and gets resumed.

~~**Therefore the cookie needs a third state.**~~ **Cut during implementation — the rule
just needed stating correctly.** The proposed fix was a "deliberately empty" marker written
by a reset and honoured by the rule. It is not needed, and a marker that three separate
branches of the reset route had to remember to write is a marker one of them would forget.

**Shipped rule — keyed on the *presence* of `conv_id`, not on whether it resolves:**

> **A cookie that names a conversation is honoured as-is. Only a cookie with no
> conversation at all resumes the owner's most recent one.**

All three paths above become no-ops, because the cookie holds an id in every one of them:
after a reset it is the freshly minted one, after an undo it is the restored one, and a late
append lands on an id the cookie no longer names. The fallback fires exactly where it should
— no cookie at all, which is a new device, a cleared browser, or the request after a logout.

**The fallback half ships OFF** (`CHAT_RESUME_LATEST_SESSION`, default false). A bug-hunt
pass made the argument that closed it: the visible transcript restores from per-tab
`sessionStorage` and is dropped on sign-out, while these rows are per-account and durable —
so *every* case where the fallback fires is a case where the two disagree, and the reader
gets a blank screen backed by a model that remembers. Pinned by
`test_the_resume_fallback_is_off_by_default`; the behaviour itself is pinned by two tests
that set the flag, so step 6 only has to flip it.

**A gap that remains open, knowingly.** With the flag on, ending a conversation and then
logging out *before asking anything else* loses the reset: the cookie is purged, so the next
visit sees no `conv_id` and resumes the conversation that was ended. Closing it needs a
durable owner-level reset marker or an empty session row, and §4.2 deliberately creates
sessions lazily so `/api/conversation/reset` (30/min) cannot fill a sidebar with empties.
Worth fixing before the flag turns on, not before step 5.

The failure mode is real and the test is load-bearing: reverting to the "cookie id has no
durable row" reading was tried against the suite and
`test_new_chat_is_not_resurrected_by_the_current_session_rule` fails.
`web/api/app.py::_resolve_conversation_id` carries the argument; the sharpest gap the
fresh-eyes pass found cost one predicate, not a new cookie state.

---

## [HISTORICAL] 6. The isolation contract

`purge_conversation_state()` splits: **cache and cookie purge stay unconditional** (on
logout and on every identity change via `_bind_session_to_identity`); **durable rows
survive**. A returning reader A is distinguished from a new reader B by the verified
Supabase user UUID, not by browser state.

| Test | Under persistence |
|---|---|
| `test_logout_clears_the_conversation_cookie` | Passes |
| `test_logout_clears_the_server_side_conversation_store` | **Must be rewritten** — it currently asserts the absence of the feature. Replacement: cache empty, durable session still present for the original account |
| `test_logout_succeeds_even_though_supabase_is_absent` | Passes |
| `test_a_different_reader_does_not_inherit_the_streaming_conversation` | **Rewritten** — it failed loudly rather than going vacuous; see below |
| `test_a_different_reader_does_not_inherit_the_blocking_history` | Passes |
| `test_the_same_reader_keeps_their_conversation` | Passes |

**Corrections, the last one from implementation.** Revision 2 claimed five of six pass
unchanged; they pass only after the store re-key (§4.2), which is not "unchanged". And
`test_a_different_reader_does_not_inherit_the_streaming_conversation` fakes its second
reader by writing `flask_session["auth_identity"]` (`test_session_isolation.py:139-141`)
while the header still resolves to `test-user-id` — so in the database **both requests have
the same owner**, and the claim that B would additionally get `session_not_found` is false.

Worse, once the current-session rule exists, `_bind_session_to_identity` rotation drops a
pointer the next request repopulates from the new owner's own latest session. That is
correct behaviour, but it means **isolation now rests entirely on the owner filter inside
the RPC**, and this test keeps passing while proving nothing about the durable path.

**Predicted "vacuous", observed "fails".** Better than expected, and worth recording. The
fake second reader shares `test-user-id`, so once the current-session rule existed the purge
dropped the cookie and the very next line resumed *that same owner's* latest session and
rehydrated it. The blocking variant failed with two prior messages where it asserted zero.
A test that can no longer distinguish the property it names is more useful failing than
passing, and this one failed.

**The replacement, which step 3 built:** `fake_reader_b_token` → `test-reader-b-id`, a
second non-admin, non-disabled bypass identity (one already existed for admin), and both
tests re-pointed at a genuinely different account. Plus three assertions that did not exist
before, in `test_chat_persistence.py` and `test_session_isolation.py`:

- `test_a_second_reader_cannot_load_the_first_readers_session` — the durable-path assertion
  isolation now actually rests on. Cookie rotation became a convenience the moment rows were
  owned; the owner filter is the guarantee, and nothing tested it.
- `test_a_returning_reader_resumes_their_own_history` — the deliberate behaviour change,
  pinned so it cannot regress into the old unconditional purge.
- `test_the_streaming_route_keys_history_by_owner` — asserts the bare id does not reach the
  window, which is what stops a request path silently dropping `owner_id` and filing every
  reader in one bucket.

---

## [HISTORICAL] 7. Consent, retention, export — notice at first use

> **REVISION, 2026-08-21 — this section describes a design that was reduced
> before it was built.** What shipped is the notice and nothing else. The
> `profiles` consent columns, the acceptance and withdrawal routes,
> `admin_purge_chat_archive`, `admin_export_chat_archive`,
> `admin_chat_question_frequency`, the purge CLI and the JSONL export were all
> **cut, not deferred**. Read the rest of this section as the record of a plan,
> not of the system.
>
> **Why.** The archive is dormant — both salts are unset, `archive_keys()`
> returns `(None, None)`, `chat_archive` holds 0 rows — so every control here
> governs a collection process that is not running, and a Settings toggle
> reading "Research archive: ON" would assert something false to the person it
> exists to inform. Consent specifically was dropped as the *wrong instrument*
> rather than as scope: the basis is legitimate interest, and recording consent
> that was not required manufactures the proof-and-symmetry obligations that
> come with claiming it.
>
> **Three corrections to what is written below**, worth having beside it:
> - The opt-out flag as designed here (read via `IdentityFlags` behind the
>   30-second cache) **races**: the decision is taken at request start and
>   applied to a write that lands later. It needs to be checked and serialized
>   inside the write transaction.
> - It also **fails open** — the unresolved-identity fallback would read as
>   *opted in*.
> - The **export was pointed the wrong way**. This section specifies an operator
>   export of `chat_archive`; the access right that is actually owed is the
>   reader's own history. If an export returns, it should be that one, and its
>   cursor must order by time — `(session_id, seq)` orders by a random UUID.
>
> **And the `DELETE` grant this section's admin RPCs assume was retired**, not
> granted: `20260820213833_revoke_chat_archive_direct_writes` reduced
> `service_role` to `SELECT` alone. A `security definer` purge function executes
> as its owner and needs no table grant, so a standing one could only ever be a
> second, unguarded delete path.
>
> **The gate that keeps this honest:** `server.archive_disclosed` plus
> `_warn_if_archive_is_undisclosed` — setting either salt while the notice still
> says nothing about the archive logs a loud error at startup. Reopen this
> section before enabling collection.


**Owner decision: a notice, recorded, not a gate.** Persistence is on regardless.
The hard gate was considered and dropped: it would have forced a blocking bilingual screen
into the first increment and made the ephemeral path permanent — a second conversation path
maintained indefinitely for readers who decline. Given §1.5, that is disproportionate.

**And the protection it was defending was weaker than it looked.** The archive row is
written in the same transaction as the turn, carrying the same question and answer text,
while `chat_messages` holds that text under a real `owner_id` with a `created_at` in the
same microsecond. Joining the archive back to a person is a text equality, not a hash
inversion. The hashing is still worth keeping — it is real protection if the archive leaks
*alone*, and it is what makes the owner purge path possible — but it does not carry legal
weight on its own.

**What ships:**

- **The notice**, both catalogues, shown once at first use, saying: chats restore across
  devices; you can delete a session; **logout does not delete**; the question, answer and
  retrieval set are kept for quality and internal model work; do not paste names,
  identifiers or patient data; nothing goes to a third party for training; deleting rows
  cannot un-train a model already trained; backups outlive a deletion until they expire.
- **`profiles.terms_accepted_at`, `terms_version`, `archive_withdrawn_at`.** Acceptance is
  a record. **`archive_withdrawn_at` is what stops collection** — without a separate flag,
  "no gate" and "withdrawal stops new archive rows" contradict each other. `chat_append_turn`
  receives `p_archive_opted_out` and skips the archive row when set; the reader's own
  history is unaffected.
- **All three columns join the `profiles_guard_privilege_columns` deny-list.** Column grants
  are an allow-list so a new column is write-denied by default — but the trigger is a
  *deliberate* deny-list, so if anyone later bundles these into the grant while touching the
  profile form, consent becomes writable from a browser console and nothing fires. Both
  locks, as `role`/`tier`/`is_disabled` have.
- **Acceptance and withdrawal are written by a Flask route**, never a PostgREST upsert. Read
  via `IdentityFlags` behind the existing 30-second identity cache (`admin_store.py:671-694`)
  — the house pattern, and it means up to 30s of archive writes after a withdrawal, which is
  acceptable for a record and is stated rather than discovered.
- **`TERMS_VERSION` lives in `app_settings`**, the repo's admin-editable-config pattern, not
  in env. Bumping it re-prompts.

**Keys.** One stable salt, no rotation:

```
owner_key   = hex(HMAC-SHA256(ARCHIVE_OWNER_SALT,   owner_id))
session_key = hex(HMAC-SHA256(ARCHIVE_SESSION_SALT, session_id))
```

Salts live in Flask env (`.env.example` updated in step 2); **a missing salt fails the
archive write closed and logs, never silently writes a null-salted digest.** Flask computes
both digests from a verified id and passes them in; **a precomputed digest is never accepted
from a client or read from a request body** — otherwise the caller controls the mapping.

Rotation was considered and dropped: a stable `session_key` is required to keep a
conversation's turns grouped and would re-link rotated owner keys anyway, and rotation makes
erasure impossible unless every salt is retained, in which case it protects nothing against
the only party holding them.

**Retention.**

| Store | Keep | Who deletes |
|---|---|---|
| `chat_sessions` and children | Reader's own, indefinitely | Reader, or `admin_delete_chat_sessions` |
| `chat_archive` | 24 months | `admin_purge_chat_archive` only |

`admin_purge_chat_archive(p_before, p_owner_key)` takes a cutoff (the 24-month job), an
owner key (erasure and withdrawal), or both — **and refuses when both are null**, which
would otherwise delete the whole archive. One `audit_log` row per call carrying bounds and
row count. Run from an admin action or a documented `flask purge-archive` CLI; **the CLI
ships with the archive**, because a ceiling that exists only in the notice is a promise
rather than a mechanism. No `pg_cron` until the project verifiably has it.

**Withdrawal is partial by construction, and the notice must say so.** It deletes the
owner's archive rows and sets `archive_withdrawn_at`; it does **not** delete
`chat_messages`, where the same question and answer text sits under a real `owner_id` until
the reader deletes those sessions themselves. Either the notice says which one withdrawal
clears, or readers will reasonably believe it cleared both.

**Export** is JSONL, owner-run, streamed, never emailed. One object per line, UTF-8,
`ensure_ascii=False` — the lesson `conversation_store.py` already records, where default
escaping made a ~950-char Arabic exchange measure ~4,700. CSV is rejected (nested sources,
Arabic quoting) and so is one large JSON array (cannot stream). Filters: date range, `lang`,
`corpus_revision`, plus a dataset-version tag. Filename
`chat-archive-YYYY-MM-DD-to-YYYY-MM-DD.jsonl`. One `audit_log` row per export recording who,
the filters and the row count — **not the text**.

**The export's `sources` are remapped, not passed through.** `build_source_payload` emits
`index` and has no `cited` key (`citations.py:119-131`), while the export needs
`source_index` and `cited`. The remap happens once, at the persistence boundary, so the
stored rows and the export agree:

```json
{"occurred_at":"…","owner_key":"…","session_key":"…","lang":"ar","category":"…",
 "model":"…","corpus_revision":"…","question":"…","answer":"…",
 "sources":[{"source_index":1,"cited":true,"document":"…","page":12,
             "category":"…","snippet":"…","chunk_id":"…","score":0.41}]}
```

---

## [HISTORICAL] 8. Execution order

**Minimum coherent increment is steps 1-4** — through the first durable write. Revision 2
described an increment its own table did not schedule; this is the correction.

| # | Step | Gate | Status |
|---|---|---|---|
| 1 | Migration: reader tables + archive, policies, grants, RPCs | applies; **RLS proven from a reader JWT** (§9); RPC round-trip by hand | **applied 2026-08-20; gate CLOSED 2026-08-21** — policies exercised as a real `authenticated` role with real JWT claims; see §9 |
| 2 | `ChatBackend` Protocol + Supabase/InMemory backends; uuid canonicalisation; `ConversationStore` re-key; salt helpers + `.env.example` | `pytest -m "not browser and not integration"` | **done** |
| 3 | Current-session rule (§5); ownership verification; logout/purge split; second non-admin bypass identity; replacement isolation assertions | `test_session_isolation.py`, `test_new_chat.py` | **done** |
| 4 | Write at `final`; client-minted `client_request_id`; `persistence_unavailable` as an `error` frame; `handlers.js` toast + robot fix | `test_chat_stream.py`, `test_chat_api.py`; **both catalogues**; `ASSET_VERSION` bump | **done** |
| 5 | Citation persistence (all retrieved, `cited`) + `corpus_revision` **rendering** gate | `test_citations.py` + sparse-index, NaN, stale-build tests; `ASSET_VERSION` bump | **done 2026-08-20** — with the gate's *rendering* rule reversed; see below |
| 6 | Hydration replaces `sessionStorage`; eviction neutralises its own markers | `-m browser`, `test_source_panel.py`; `ASSET_VERSION` bump | **done 2026-08-20** — `GET /api/chat/history`; `Transcript.save/restore` and `neutraliseRestoredCitations` deleted; `chat_resume_latest_session` on |
| 7 | ~~Notice screen + acceptance/withdrawal routes; `profiles` consent columns; purge CLI; export RPC; frequency RPC~~ **Shipped 2026-08-21 as a notice ONLY**, plus the archive revoke and a disclosure guard. Everything else cut — see the revision note under §7 | `-m browser`, `test_rtl.py`, `test_css_contract.py`; both catalogues; `ASSET_VERSION` bump | **done 2026-08-21**, deliberately narrowed |
| 8 | Phase 2 sidebar, titling, rename, delete; `chat_list_sessions` | `-m browser`, `test_css_contract.py`, `test_rtl.py`; `ASSET_VERSION` bump | **done 2026-08-21** — with the browser-direct delete reversed and an in-flight refusal added; see below |

**Step 8 shipped 2026-08-21, and two written positions were reversed.**

- **The browser never touches these tables after all.** §9 said step 8 "is the
  first feature to call `chat_sessions_delete_own` from a browser with no Flask
  route in between", and §8 deleted `chat_delete_session` on the argument that an
  RPC would be "a second, privileged path" to what RLS already permits. Both
  fell to facts already in the tree. First, `revoke all on public.chat_sessions
  from service_role` leaves Flask holding SELECT and nothing else, so the choice
  was never "browser-direct or an RPC" — it was "browser-direct or nothing".
  Second, and decisively, a browser-direct delete cannot finish the job: it
  cannot clear `conv_id`, `prev_conv_id` or the `ConversationStore` window, and
  `chat_append_turn`'s `insert … on conflict (id) do nothing` then lazily
  RECREATES the deleted session on the reader's next question. So all four
  operations are Flask routes over three new `security definer` RPCs
  (`20260821145319_chat_navigation_rpcs.sql`), and RLS goes back to being
  defence in depth rather than the coordinator of a workflow spanning a cookie,
  a process-local cache and three tables.
- **Titling is part of the append, not a call after it.**
  `20260821145416_chat_first_turn_title.sql` drops and recreates
  `chat_append_turn` with a fourteenth argument, `p_title`, applied as
  `title = coalesce(title, …)` in the same statement that claims the sequence
  numbers, under the row lock already held. A separate PATCH would have raced the
  session lifecycle three ways: it can fail on its own and strand an untitled
  conversation, it can land on a row the reader renamed or deleted in between,
  and two first turns from two tabs would both see `title is null`. `create or
  replace` was not usable — a changed signature makes a second function, and
  PostgREST would then find a 13-argument call ambiguous and stop persisting
  every turn on a deployment where the migration "succeeded".

**A race the plan did not have**, found by an adversarial pass and closed
server-side rather than only in the UI. Both chat routes close over
`conversation_id` and write at `final`; the sidebar's delete is a separate
request. Delete a conversation mid-stream and the late append meets
`on conflict (id) do nothing`, finds no row, and creates one — carrying the
answer the reader discarded. `_InFlightGenerations` (`web/api/app.py`) holds a
counted claim on `(owner, conversation)` for the whole generation window and the
select/delete routes answer 409 `generation_in_flight` against it; the client
refuses the controls too, so the affordance and the guarantee are separate
things. Correct because this app is single-worker by documented contract
(`conversation_store.py:15-21`); if that ever changes the replacement is a
tombstone table, not a bigger dict. Pinned by
`test_a_conversation_being_written_to_cannot_be_deleted`, verified to fail
without the guard.

**One limit is disclosed rather than fixed.** `conv_id` is a per-BROWSER cookie,
so selecting a conversation in one tab changes it in every tab of the profile.
That was already true before this step — two tabs have always shared one
conversation — but the sidebar makes it easy to trip. The fix is a tab-scoped
pointer sent on every chat request, which is a change to the chat routes'
contract and not to the sidebar; it is recorded in `TODO.md`, not smuggled in
here. Deep-linking (§10.3) is the same change and would land with it.

**Also decided:** no virtualisation (a bounded 30-row page and a cursor;
virtualising a list of short titles inside an offcanvas that already scrolls
adds focus, ARIA and scroll-chaining failures to save a cost that does not
exist); no `Intl.RelativeTimeFormat` (Arabic has six plural forms where
`I18n.plural` knows two, `Intl` emits bidi control marks that reorder in an RTL
column, and the language toggle reloads the page, so a cached relative string is
stale by construction — five catalogue-owned day buckets instead); and rename
deliberately does not touch `updated_at`, so naming a three-month-old
conversation does not lift it to the top of Today.

**Three things moved out of step 1 during implementation, on the migration README's own
rule 1 — one concern per migration — and on §2.4's objection to untested surface.**

- **`profiles` consent columns → step 7.** They are read by the notice and by nothing else.
  Shipping them now means three columns and two deny-list entries that no code touches, which
  is the same argument §2.4 makes against a policy no code takes.
- **The admin RPCs → step 7.** `admin_purge_chat_archive` is the only delete path on an
  otherwise append-only table. It should arrive with the thing that calls it and the
  `audit_log` row that records it, not months earlier with nothing exercising it.
- **`chat_delete_session` → deleted, not deferred.** §2.4's table already gives readers
  `DELETE` through an RLS policy, so an RPC that does the same thing through the service role
  is a second, privileged path to the same effect. Step 1's migration ships the policy.

What step 1 does ship: three reader tables, the archive, all policies and grants, and the
three RPCs steps 3-6 actually call — `chat_append_turn`, `chat_load_session`,
`chat_latest_session`.

**Step 8's two migrations are applied — 2026-08-21.**
`20260821145319_chat_navigation_rpcs` (list, rename, delete) and
`20260821145416_chat_first_turn_title` (the 14-argument `chat_append_turn`), in that order,
with both filenames matching what `list_migrations` reports. Schema went first because the
reverse order breaks silently: the new backend always sends `p_title`, and against the old
13-argument function PostgREST finds no match and every turn reports unsaved. It is safe in
the other direction too, verified before applying rather than assumed — a 13-argument named
call resolves through `p_title`'s default, so the then-deployed code kept working with
titles staying null. All four chat tables held **0 rows** at apply time, so there was no
backfill and no legacy untitled population to inherit. Round-tripped in aborted transactions
(0 orphan messages and 0 orphan sources after an owner delete; row counts confirm nothing
committed), and the advisors returned no new findings — these migrations add no table and no
index, so a clean run was expected rather than lucky.

Every step touching JS or CSS bumps `ASSET_VERSION` and names both catalogues —
`test_frontend_architecture.py:134` asserts the Arabic catalogue covers every runtime key,
so a missed one is a red build, not a cosmetic lapse.

**`TODO.md` is updated in step 1** — §1.6 promised it and no revision-2 step owned it.

**~~Step 1 is written but NOT applied~~ — applied 2026-08-20** as
`supabase/migrations/20260820131914_chat_session_persistence.sql`, matching what
`list_migrations` reports, through the MCP `apply_migration` tool (there is no Supabase CLI,
`supabase/config.toml` or Docker in this project — `supabase/README.md`). Verified by hand, in a
rolled-back transaction, that `chat_append_turn` and `chat_load_session` round-trip and the
`service_role` revokes did not break the `SECURITY DEFINER` path.

- **Steps 2-6 did not wait on it.** Under TESTING the backend is `InMemoryChatBackend`, which
  reimplements the RPC's guarantees rather than approximating them — ownership refusal, seq
  allocation in pairs, replay that does not advance the counter. That is what let steps 2-4
  ship and be tested with the migration still unapplied.

**Hydration is bounded.** `chat_load_session` takes `p_limit`, clamped in Flask to the
`[1,200]` the People pager already uses (`admin.py:242-252`). Unbounded hydration would meet
`stateByMessage`'s 100-answer cap (`citations.js:62-71`) and lose citation controls on the
oldest turns of a long session **without saying so** — on the product whose central claim is
resolvable citations. Step 6 handles eviction neutralising its own markers; the limit is what
stops the situation arising.

**Most likely failures, and what catches each**

1. **A reset or undo is resurrected by the current-session rule** (§5). A test that resets,
   reloads, and asserts an empty transcript — and the undo variant.
2. **An owner scope is missed.** B loads A's session id and gets nothing while A still sees
   it. Needs the second bypass identity (§6).
3. **RLS proven only against the service role**, which bypasses it, so a broken policy
   passes. Policy tests run with a reader JWT.
4. **Undashed vs dashed uuid** (§2.5) — an equality test across the boundary.
5. **A replay double-writes the archive or advances `next_seq`** (§4.2).
6. **A stale source renders as valid.** Mutate the active build id; assert the citation
   degrades and is unopenable.

**Deliberately not built:** full passage text; automatic re-citation; model-generated
titles; branching, merging, editing; per-message deletion; background completion;
browser-direct writes; deleting durable history on logout; suggestions persistence (a
garnish, regenerated on demand); `chunk_sha256` resolution; a transcript console page.

---

## [HISTORICAL] 9. Costs priced rather than assumed

- ~~**One Postgres round trip per turn**~~ — **overpriced; it is one per conversation per
  process.** Implementation reads durable rows only when the RAM window is *cold*
  (`_load_history`), so an ongoing exchange costs nothing and the read happens on a new
  device, after a restart, or after the store's hour of inactivity. The store is still not a
  cache of these rows — §4.2's argument stands, and `replace()` seeds the window rather than
  claiming the rows and the window agree — but the latency worry that motivated the
  `(owner, session, last_seq)` caching idea does not arise, and that idea is dropped.
  `chat_latest_session` adds a second cold read on exactly the requests that have no cookie.
- **The single-worker contract.** `conversation_store.py:15-21` documents
  `--workers 1 --threads 8` as a consequence of process-local history. Durable rows are the
  thing that could relax it — but FAISS and sentence-transformers in RAM still require it, so
  **this changes nothing today**, and any window-caching optimisation may depend on it.
- ~~**Step 1's gate is the expensive one, and it is now the ONLY thing left in the critical
  path.**~~ **CLOSED 2026-08-21, and it was not expensive.** This section argued the harness
  — "a project, two real accounts, a signed token" — costs more than the migration. It does
  not, because a signed token was never the requirement: PostgREST authenticates a request by
  setting `role` and `request.jwt.claims` on the connection, and `auth.uid()` reads the `sub`
  claim out of that GUC. Both are settable directly:

  ```sql
  perform set_config('request.jwt.claims',
    json_build_object('sub', reader_id::text, 'role', 'authenticated')::text, true);
  set local role authenticated;
  ```

  Two readers were seeded through `chat_append_turn`, the connection dropped to
  `authenticated` as reader A, and the whole thing aborted so nothing committed. Results, with
  both readers' rows present in every table:

  | Property | Result |
  |---|---|
  | `chat_sessions_select_own` | A sees **1** session of 2 |
  | `chat_messages_select_own` | A sees **2** messages of 4 |
  | `chat_message_sources_select_own` | A sees **1** source of 2 |
  | `chat_archive` readable? | **DENIED** — no grant, no policy |
  | Forge a `chat_messages` row? | **DENIED** — no insert policy |
  | Tamper with a stored answer? | **DENIED** — no update policy |
  | Delete another reader's session | **0 rows** |
  | Delete own session | **1 row**, children cascaded, **0 orphans** |

  **What this does and does not prove.** It proves the policies themselves: the same `role`
  and the same claims PostgREST would set, evaluated by the same expressions. It does not
  exercise PostgREST's own request handling, nor the anon-key path through the JS client — so
  a browser reading these tables directly is still untested *plumbing*, on *verified* policy.
  The distinction matters for step 8, which is the first feature to call
  `chat_sessions_delete_own` from a browser with no Flask route in between.

  The paragraph this replaces said the policies were "reviewed code, not verified code". They
  are now verified code.

  **Superseded in part by step 8.** The last sentence above expected step 8 to be the first
  feature to call `chat_sessions_delete_own` from a browser. It is not: every sidebar
  operation goes through Flask, for reasons the step-8 note under §8 sets out — the decisive
  one being that a browser-direct delete cannot clear the cookie or the RAM window, so
  `chat_append_turn` recreates the session it deleted. The "untested plumbing" observation
  therefore still stands and is still untested, because nothing exercises it.
- **Reader-RLS reads need a browser mock.** `SUPABASE_BROWSER_MOCK` (`conftest.py:13-80`)
  implements `auth` and `profiles` only. If the browser ever reads chat tables directly it
  needs a new `from()` chain; Flask-mediated reads need nothing, since browser tests already
  intercept `/api/*`.
- **PITR and backups outlive every delete** — the reader's own session delete included, not
  only the archive purge. Stated in the notice, not solved in SQL.

---

## [HISTORICAL] 10. Decisions still open

**No architectural decisions remain open.** The last one — write at `final` versus the
reserve design — was ruled on 2026-08-18 (§4.1). Steps 2-4 are built; §8 records what shipped.

**One operational decision is now the only blocker: applying the migration**, which touches
the live project and is the owner's to make. See §8 and §9.

What is left is scope and copy, none of it blocking:

1. **Quotas** — no max sessions or messages per owner. Not needed at current scale;
   revisit before the reader count makes an unbounded message table interesting. Note the
   per-*message* half is now partly covered: `MAX_CHAT_QUERY_CHARS` bounds a question at
   8,000 characters, so a single row can no longer be arbitrarily large.
2. ~~**A question-length cap**~~ — **done in step 4.** `MAX_CHAT_QUERY_CHARS = 8_000`,
   enforced in `_validate_chat_request` as a 400, above the database, so an over-long
   question is the client error it is rather than a 500 raised inside a `security definer`
   function.
3. ~~**Deep-linking** (`/c/<id>`)~~ — **done 2026-08-22**, bundled with the multi-tab fix
   exactly as this entry anticipated: `docs/per-tab-conversation-deep-linking-plan.md`. Not
   by generalising `POST /api/chat/sessions/<id>/select`'s cookie-move, though — that route,
   `_resolve_conversation_id`, and the cookie itself are all deleted. The URL is the
   conversation id, sent by the client on every request; there is no server-side
   "current conversation" left to resolve. The `ConversationStore` owner re-key mentioned
   here is exactly what makes two tabs, each naming its own id, unable to reach each
   other's window.
4. **Notice copy** — needs a native-Arabic review pass before step 7. A review task, not an
   engineering one, and it does not gate steps 1-6. `chat.notSaved` shipped in both
   catalogues in step 4 and wants the same pass.
5. ~~**New, surfaced by implementation: "New chat" no longer destroys anything.**~~
   **Resolved in step 8: the copy changed and `forget` did not grow a delete.** Reset still
   drops only the cookie pointer and the RAM window, the rows still survive, and they now
   genuinely appear in the sidebar — so the notice says so (`chat.historyNotice` names the
   sidebar's delete, and `test_the_notice_names_the_delete_control_in_either_language`
   inverted to pin it). Undo was **kept and scoped**, not removed: it still restores the
   immediate New chat, but a sidebar selection, rename or delete ends it, client-side and
   server-side, so a stale Undo can never restore an invisible conversation over the one on
   screen or a conversation the reader has since deleted. Making `forget` destructive was
   rejected — the sidebar's own delete is the honest place for that, and a second delete
   path reachable from a toast is not.

---

## [HISTORICAL] 11. Where the reviews earned their cost

- **Research** — the failure taxonomy and the composite-FK ownership hole.
- **Design** — the schema, read closely enough to get the 321-char snippet bound and the
  `[1,200]`/`[0,1_000_000]` clamps right unprompted.
- **Debate** — a bug revision 1 would have shipped (undashed uuid), an unimplementable
  requirement (`chunk_sha256` from a payload with no text), a false claim about the isolation
  suite, an SSE event that would have been silently dropped, and the argument that deleted the
  reserve/complete state machine.
- **Fresh eyes** — 15 internal contradictions introduced by revising in place, including a
  ruling that was simultaneously open and closed; the pair-assembly builder defending a state
  the design could no longer reach; a purge RPC that deleted everything when called with no
  arguments; an archive with no idempotency key; and the resurrection bug in §5. It also made
  the proportionality argument that reduced consent from a gate to a record.
- Reviews A and B, without the codebase, found the `seq` ambiguity, the corpus-destruction
  paths, the title-atomicity contradiction and the missing current-session rule — and several
  non-issues, §12.

## [HISTORICAL] 12. Review claims that did not survive

| Claim | Verdict |
|---|---|
| "Guests and mid-chat sign-in are unspecified" | **Wrong.** Both chat routes are `@auth_required` (`app.py:1298,1441`). There are no guests |
| "Whitespace-only first message violates the title check" | **Wrong.** `query` is stripped and empty rejected with 400 (`app.py:1273-1278`) |
| "Drop `source_index` outside 1-99" | **Unreachable.** `CITATION_MARKER` is `[0-9]{1,2}`; `_context_ceiling()` caps at `search_engine.k` |
| "`retrieved` unbounded — could claim 10^9" | **Overstated.** Server-written from `len(retrieved)`, on a table with client writes revoked |
| "The RAM cache should hold the prompt slice only" | **Already true** (`conversation_store.py:96-97`). The real defect is the opposite — it is *lossy*, §4.2 |
| "Two tabs burn the eight-thread pool" | **Real, but predates this plan and is not fixed by idempotency.** `chat_limit` already allows 10 generations/min against 8 threads; the control would be a per-owner in-flight semaphore |
| "A second TESTING identity is missing" | **Half wrong** — `fake_admin_token` exists. What is missing is a second *non-admin* reader, §6 |
| "`seq` allocation is ambiguous" | **Correct**, and dissolved once reserve/complete went |
