# Admin analytics from saved chats — V1 design and implementation plan

STATUS: IMPLEMENTED 2026-09-20, all of V1 including the 7b controls; uncommitted at the time of
writing. Synthesised from four independent planning lanes (see
[_How this plan was made_](#how-this-plan-was-made)). The three owner decisions were taken on
2026-09-20 and refined after a second review — see [_Decisions_](#decisions).

Scope authority: [`TODO.md` → _Admin analytics from saved chats_](../TODO.md). This plan does not
widen that entry. It corrects it in four places, and every correction is called out as one.

---

## 1. What ships

Two read-only aggregate RPCs over `chat_messages` + `chat_message_sources`, two
`GET /admin/api/analytics/*` routes, two `AdminBackend` methods on both backends, and an
analytics region at the bottom of the existing Overview tab. No new table, no materialised view,
no scheduler, no cache, no new tab, no charting library, no new frontend module file.

> **Reversed 2026-09-23.** "No new tab" did not hold: the region is now its own tab, last in
> the tablist, with the hint prose behind an "i" beside each zone heading. The reasoning and the
> build are in [`archive/2026-09-23_admin-analytics-tab.md`](archive/2026-09-23_admin-analytics-tab.md). Everything else in
> this section still stands.

**Out, unchanged from the TODO entry:** the answer cache, an index-version identifier, the V2
no-name log table, the per-member conversation viewer, and all seven follow-ups. Section 9 says
how each follow-up slots in later.

## 2. Four corrections to the locked spec

Each of these was found by reading the schema, not by disagreeing with the owner. None changes
what V1 is for.

1. **"One `group by`" is a self-join.** The question text is on the _user_ row; `lang`,
   `category`, `model` and `corpus_revision` are written on the _assistant row only_
   (`supabase/migrations/20260820131914_chat_session_persistence.sql:86-92`). Every metric joins a
   turn's two rows on `(session_id, client_request_id)`, which
   `chat_messages_idem_key unique (session_id, client_request_id, role)` (same file, `:100`)
   already indexes.
2. **`category` is the reader's chosen search scope, not a subject.** It defaults to `"all"`
   (`web/api/app.py:3150`). V1 ships it as locked and labels it "search scope". An earlier draft of
   this plan said the breakdown would be "mostly one bucket"; **that was a guess and it was
   wrong** — measured on the live database on 2026-09-20, about two-thirds of saved answers carry
   a non-`all` scope, so the breakdown is informative as it stands. See decision 3.
3. **"Unanswered = `cited == []`" is two different failures.** Search found passages and the
   model cited none, versus search found nothing at all. Both are stored and separable for free,
   so V1 reports them separately. Nothing persisted marks a _refusal_, so the word never appears
   in copy.
4. **The TODO's `web/api/app.py:3730-3747` reference has drifted.** The claim is true; the
   anchors today are `web/api/app.py:3927` (streaming `empty_answer`, returns before the durable
   write) and `web/api/app.py:4277-4301` (blocking route). Fix the reference when the entry is
   next edited.

Two properties that follow from "no new log table" and must be _labelled_, not fixed:

- The figures count **saved turns**, not asked questions. A cancelled stream, a quota refusal or
  a provider failure saves nothing.
- The aggregate is **retroactive**. Reader deletes and the account-deletion purge cascade through
  `chat_messages_session_owner_fk … on delete cascade`, so last month's number can go down. That
  is the deletion promise working. A test pins it so nobody later "fixes" it into a log table.

## 3. Architecture decision

| Option                                           | Verdict                                                                                                                                                                                                                                                                                        |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A. Live aggregate RPCs**, computed per request | **Chosen.** One blocking socket read per figure, no Python CPU on the single worker. Sub-millisecond at today's size.                                                                                                                                                                          |
| B. Materialised view + scheduled refresh         | Rejected. No `pg_cron` in this project, so it means a third systemd timer; and a matview holding question text does not shrink when a reader deletes a chat until the next refresh — it quietly rebuilds the log table the owner ruled out. Becomes right only if a window query crosses ~1 s. |
| C. Aggregate in Flask                            | Rejected. Pulls every question through PostgREST into the one worker, needs its own paging loop past 1,000 rows, and moves "never return `owner_id`" from a SQL projection into Python control flow.                                                                                           |

**Deliberately not built:** a third RPC for "unanswered" (one `p_order` parameter covers it), a
process-local TTL cache (would be the fourth on a single-worker app, for a surface loaded once per
visit), a per-route rate limit (a route limit _replaces_ the blueprint's 60/minute rather than
stacking), and a statement timeout — see the trap in section 10.

## 4. Data layer

### 4.1 `admin_top_questions`

```sql
create function public.admin_top_questions(
  p_days       integer default 30,
  p_lang       text    default null,
  p_category   text    default null,
  p_min_askers integer default 2,
  p_limit      integer default 20,
  p_order      text    default 'asks'     -- 'asks' | 'uncited'
)
returns table (
  question text,    -- most recent raw phrasing in the group, not the normalised key
  asks     bigint,  -- saved turns
  uncited  bigint,  -- turns in this group whose answer cited nothing
  askers   bigint   -- DISTINCT accounts, but NULL below 5: the bucket is made HERE, not in the UI
)
language sql stable security definer set search_path = ''
as $$
  with turns as (
    select a.id as assistant_id, a.owner_id, a.created_at,
           u.content as question,
           -- zero-width / direction marks out; every space kind to one space; trailing
           -- punctuation run off. Postgres `\s` does NOT match U+00A0 here — measured.
           pg_catalog.regexp_replace(
             pg_catalog.btrim(pg_catalog.regexp_replace(
               pg_catalog.lower(pg_catalog.regexp_replace(
                 u.content, '[\u200B-\u200F\u2066-\u2069\uFEFF]', '', 'g')),
               '[\s\u00A0\u1680\u2000-\u200A\u202F\u205F\u3000]+', ' ', 'g')),
             '[?؟!.۔… ]+$', '') as normalized
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
  -- The floor lives HERE. greatest(..., 2) lets a caller raise it and never lower it —
  -- not through the route, not through a leaked service key at /rest/v1/rpc/.
  having count(distinct s.owner_id) >= greatest(coalesce(p_min_askers, 2), 2)
   order by case when p_order = 'uncited'
                 then count(*) filter (where s.cited_count = 0)
                 else count(*) end desc,
            s.normalized
   limit greatest(least(coalesce(p_limit, 20), 100), 1);
$$;

revoke execute on function public.admin_top_questions(integer, text, text, integer, integer, text)
  from anon, authenticated, public;
grant  execute on function public.admin_top_questions(integer, text, text, integer, integer, text)
  to service_role;
```

**The asker count is bucketed in SQL: `NULL` below 5, exact from 5 up.** Decided 2026-09-20,
replacing an earlier draft of this section that dropped the count entirely. At three accounts an
exact figure is a participation oracle on its own — `askers = 2` on a row the operator also asked
identifies the other asker without reading a word — so below 5 the function returns `NULL` and
the console prints the range `2–4`. At scale the exact figure is what separates "10 asks from 9
accounts" from "10 asks from 2", which `asks` alone never can. Because the bucket is made in the
function, no caller of it sees more than the console does. The `5` is hard-coded, like the floor.
_Corrected 2026-09-21:_ this first said "a leaked service key sees exactly what the console sees".
See the second review below — that key reads the table itself. _Residual, accepted:_ with a population barely above 5, `askers = 5`
is near-unanimity; a question everyone asks singles nobody out.

Settling the column now also settles the signature: adding a column to `returns table` later
means `drop function` + `create`, not `create or replace`.

**Normalisation is inline, not a helper function** — it has exactly one SQL caller, and a helper
would add a migration and ACL surface for nothing. Three passes:

1. delete zero-width and direction marks — U+200B–U+200F, U+2066–U+2069, U+FEFF;
2. `lower`, then collapse every run of spaces to one — `\s` **plus** U+00A0, U+1680,
   U+2000–U+200A, U+202F, U+205F, U+3000 — and `btrim`;
3. strip one trailing run of `?` `؟` `!` `.` `۔` `…` and spaces.

The explicit space list is load-bearing, not cosmetic. **Measured on the live database
(Postgres 17): `\s` matches none of U+00A0, U+200B or U+200F**, and the Postgres 17 manual says
why — `\s` is `[[:space:]]`, and "classification of non-ASCII characters depends on the active
collation or LC_CTYPE". Python's `\s` _does_ match U+00A0. With a bare `\s`, Arabic pasted from
Word or WhatsApp would fragment its group in production while the in-memory double grouped it,
and the suite would stay green.

The Python side is **one** function, `normalize_question()` in `web/services/admin_store.py`,
with the same three passes spelled by code point (never a bare `\s`). It has two callers — the
in-memory backend and the FAQ match in section 6 — and no second copy. The SQL expression
above was run on the live database on 2026-09-20 as a pure expression over literals (no table
read): NBSP, a zero-width space, an RLM, a trailing `؟`, `…` and mixed case all land on one key
per language. `rpc_behaviour.test.sql` still has to pin it. Not folded in V1: alef, yaa and taa-marbuta variants, tashkeel, tatweel,
`،`. Known engine gap: `lower()` differs between Postgres and Python for a handful of characters
(`İ`, `ß`); irrelevant to this corpus, recorded so nobody is surprised.

The window floor is **7 days**, not 1. The console only offers 7 / 30 / 90, and the floor means
no single response describes less than a week. _Corrected 2026-09-20 after the adversarial review:_
this paragraph first said the floor stops a caller differencing two days. It does not —
`p_days => 8` minus `p_days => 7` is a one-day slice. Accepted: the two-asker floor applies to each
call on its own, so the subtraction can date an already-listed group and can never surface one
neither call returned. Snapping `p_days` to 7 / 30 / 90 in SQL would close it.

No timestamp is returned. `last_asked` on a rare question is a correlation handle against
`audit_log.occurred_at` and `last_seen`; the window parameter already says "last 30 days".

### 4.2 `admin_citation_stats`

```sql
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
language sql stable security definer set search_path = ''
as $$
  with turns as (
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
         sum(t.cited_count),
         sum(t.retrieved_count)
    from turns t
   group by grouping sets ((), (t.lang), (t.category));
$$;
-- same revoke / grant pair
```

**Counts only, never percentages or averages.** The console divides and guards zero and small n.
Three grouping sets rather than the 2×5 cross product, which is noise at any plausible volume.
`turns_uncited` and `turns_no_retrieval` are disjoint by construction; a question row's `uncited`
is their union.

### 4.3 Actor gating

**No `p_actor_id`.** That matches every existing `admin_*` _read_ RPC — `admin_list_tiers`
(`supabase/migrations/20260903200618_admin_tier_rpcs.sql:19-28`) and `admin_list_users` take no
actor and are `service_role`-only. The gate is Flask's `_gate()` `before_request`, which
re-resolves identity live. `admin_actor_email()` is for mutations; these mutate nothing, and
`function_acls.test.sql`'s hardcoded list is the _mutating_ list.

_Corrected 2026-09-21 after the second review._ This paragraph first called the SQL-side floor
"the mitigation that matters" against a leaked service key. **Measured: `service_role` holds
`SELECT` on `chat_messages` and bypasses RLS**, so that key reads the rows directly and no function
stands in its way. What the floor in SQL actually guards is the application layer — a route bug, a
future caller, a careless parameter — which is still the right place for it.

### 4.4 Index

```sql
create index chat_messages_assistant_created_idx
  on public.chat_messages (created_at desc)
  where role = 'assistant';
```

There is no index on `chat_messages.created_at` today. Partial, so it covers half the table and
serves the one predicate both functions share; the join back to the user row rides
`chat_messages_idem_key`. Free at today's size and expensive at millions of rows — the same
argument `20260828002253_bound_the_stored_question_length.sql` makes for its CHECK. It is its own
first migration so it can be dropped alone.

**Do not build the expression index on the normalised question** that the research lane
proposed. A B-tree entry is capped near 2.7 kB and `MAX_CHAT_QUERY_CHARS` is 8,000
(`web/api/app.py:356`), so one long Arabic question would make `chat_append_turn` _fail on
insert_. It would also not serve a date-windowed `group by`.

## 5. Privacy architecture

"No identity in any response" is held by three layers that each fail visibly on their own:

1. **SQL projection.** Neither `returns table` names an owner, session, message or email.
   Asserted against the real catalogue: a new `function_acls.test.sql` check fails if
   `pg_get_function_result(p.oid)` matches `owner|user_id|actor|email|session_id|message_id`.
2. **Python allow-list.** `_ANALYTICS_QUESTION_COLUMNS` / `_ANALYTICS_CITATION_COLUMNS`, applied
   by **both** backends on the way out — the `_DELETION_LEDGER_COLUMNS` pattern
   (`web/services/admin_store.py`, `_DELETION_LEDGER_COLUMNS`).
3. **A route test on the raw JSON body** — no seeded owner id, no seeded email, no matching key.

**The minimum-asker floor is the one addition beyond the spec.** At three accounts, a question
with `asks = 1` printed verbatim _is_ one reader's content shown to an operator. The floor counts
**distinct askers, not asks** — `group by` over turns does not deduplicate by reader, so one
person asking five times would otherwise read as `count = 5`.

With the floor in SQL, nothing in the response is one reader's content, so:

- the existing `page.policy.useImprove` disclosure ("in aggregate — never to single out one
  person's activity") covers the surface with **no privacy-policy edit**;
- **no audit row is needed.** `web/services/audit.py:14-18` draws the audit line at "any access
  to a reader's own content", and this is not that.

Both of those flip if the owner overrules the floor (decision 1).

`admin_citation_stats` returns no text, needs no threshold, and carries real numbers on day one —
which is what keeps the feature useful while the question list is legitimately empty.

## 6. Backend and routes

**`web/services/admin_store.py`** — `AdminBackend` gains:

```python
def top_questions(self, *, days, lang, category, limit, order) -> list[dict]: ...
def citation_stats(self, *, days, lang, category) -> list[dict]: ...
```

Empty window returns `[]`, never `None`, so the frontend's null-vs-empty rule keeps working.
`SupabaseAdminBackend` calls through the existing `_rpc()` helper and shapes rows to the
allow-list tuples. `InMemoryAdminBackend` aggregates over the **real in-memory chat turns**,
injected the way `quota` already is, so `?testing=true` is a working demo — plus a `seed_turns()`
test affordance outside the Protocol. It reimplements the normalisation and the floor faithfully;
a double laxer than production is a green suite asserting the opposite of production.

**Wiring:** `_testing_chat_backend` is built at `web/api/app.py:2316`, immediately before
`_testing_admin_backend` at `:2319`, which is injected with it — the reorder this paragraph
called for has shipped.

**`web/api/admin.py`:**

```text
GET /admin/api/analytics/questions?days=30&lang=&category=&limit=20&order=asks
GET /admin/api/analytics/citations?days=30&lang=&category=
```

- Gated automatically by `_gate`; `test_every_admin_api_route_is_gated` walks `url_map` and
  covers both with no edit. Say so in the commit message.
- `days` / `limit` via a small `_parse_analytics_window()` mirroring `_parse_pagination_params` →
  `400 invalid_window`.
- `lang` against `SUPPORTED_CHAT_LANGS` (`web/api/app.py:366`), `category` against
  `CHAT_CATEGORIES` (`:362`), imported inside the view body per the file's cycle-breaking
  convention → `422`. `order` against `("asks", "uncited")` → `422`. Empty string → `None`.
- `backend is None` → `503 storage_unavailable`.
- **`min_askers` is not a query parameter.** The route never sends it.
- **Each question row gains `from_faq: bool`, set in the route.** A sidebar FAQ click sends the
  FAQ's text verbatim, with the FAQ's own category (`static/js/modules/handlers.js:1910`), and
  grouping is by exact string — so the rows that clear the floor first, and at scale most rows
  that clear 5, are the sidebar's own questions. Unmarked, "top questions" mirrors `faq.yaml`,
  which is the opposite of what the list is for (finding what to _add_ to it). The route builds
  one `frozenset` of `normalize_question(q["text"])` over every language block of
  `app.config["FREQUENT_QUESTIONS"]` — already loaded at startup by `_load_faq_data`, so no new
  loader — and flags `normalize_question(row["question"]) in that_set`. In the route, not the
  backends, because the FAQ data lives in app config: two backends, zero copies. It is added
  _after_ the allow-list shaping, so the allow-list stays the single statement of what the
  database may return.

## 7. Interface

### 7.1 Where it lives

A **sibling `#overview-analytics.admin-panel-body`** inside `#panel-overview`, below
`#overview-body`. The Settings panel already stacks two sibling bodies
(`web/templates/admin.html:186-187`).

This resolves the one real disagreement between lanes. The architecture lane wanted to extend
`renderOverview` (six requests in one `allSettled`, zero CSS, three edits to existing browser
tests). The UI lane wanted a sibling. **Sibling wins**, for three reasons:

- `renderOverview` does `body.textContent = ''` and repaints whole. Any re-render on a filter
  change would destroy the focused `<select>`.
- The existing overview tests assert `.admin-facts .admin-fact` has count 3
  (`web/tests/test_admin_browser.py:2245`) and a strict single `table` (`:2249`), scoped to
  `#overview-body`. A sibling leaves them green and unedited.
- Aggregates are slower than the four cheap reads and must never delay the landing figures.
  `loadOnce` calls `loadAnalytics()` un-awaited beside the existing `allSettled`, with the same
  `null` = could not load / `[]` = nothing yet semantics.

Analytics goes **below** the operational figures: signup state and account count are what an
operator acts on, and at three accounts the question lists will usually be policy-empty.

> **Reversed 2026-09-23** by [`archive/2026-09-23_admin-analytics-tab.md`](archive/2026-09-23_admin-analytics-tab.md). The
> three reasons above were all reasons not to put analytics _inside_ `renderOverview`; none was
> a reason against a tab, and a tab satisfies all three better while restoring Overview's own
> contract (cheap reads, every figure links to the tab that owns it). The region now lives in
> `#analytics-body` inside `#panel-analytics`, the last tab; the lead zone is drawn once at
> init and the three requests fire on first activation. The zone list in §7.2 is unchanged
> except that the hint prose in zones 1–3 moved behind an "i" beside each heading and the
> `privacy` line joined the `source` popup.

### 7.2 Zones

1. **Saved conversations** — one hint (where the numbers come from, that they can shrink, that
   the lists never show who asked), the controls, a "Counted at" stamp.
2. **Citation quality** — always has numbers, so it leads. Five tiles in a
   `dl.admin-facts.admin-card` from the `total` row: saved answers; found passages, cited none;
   search found nothing; passages cited per answer; passages retrieved per answer. Then one
   `.admin-table` with two `<tbody>` groups (by question language, by search scope), each led by
   a `th scope="rowgroup"`.
3. **Recurring questions** — table: Question / Times asked / Accounts / Without a citation.
   - **The Accounts column renders only when some row has a non-null `askers`.** Until a question
     reaches 5 distinct accounts every cell would read `2–4` — a constant column is noise, and
     this repo does not ship the sentence before the feature. One `rows.some(...)`.
   - When shown: the exact number, or `2–4` for `NULL`. Digits in a `machineValue` isolate, so it
     needs **no catalogue string** in either language.
   - A row with `from_faq` carries a quiet text mark, "Sidebar question", after the question.
     Reuse an existing mark class (`.admin-marks` family — **confirm the exact class at build
     time**; do not add one). Text, not colour.
4. **Recurring questions answered without a citation** — the same `questionTable()` builder on a
   second call with `order=uncited`. Omitted entirely when zone 3 is `[]`.

Codex's one surviving decision before its quota ran out agrees with this order: citation health
first, zero-citation questions second, popular third, rows do not click through.

### 7.3 No charts, no bars

`DESIGN.md:182` bans reporting a _relevance score_ as a proportion; a bar of counted things is
outside its letter. Bars are still declined for V1: it would be the first instance of the
reserved 4px meter, at n < ~20 a bar's visual precision overclaims (the same failure `:182`
describes), and a per-question uncited bar reads as a quality score for that question. Revisit
with follow-up 4 (daily counts), the first genuinely chart-shaped data.

### 7.4 Small-n honesty

- Counts are always primary: `3 of 14`.
- A percentage appears only when the denominator is ≥ 10 (`MIN_RATE_DENOMINATOR` in `ui.js`).
  When any is withheld, one `.admin-form-hint` explains the rule.
- `turns === 0` renders the empty state — never `0%`, never `NaN`, never `—` (`—` means _failed_
  in this console).
- No tone class on any tile. Nothing malfunctioned; "a number that is merely true does not need a
  mark" (`DESIGN.md`, the daily-allowance colour-rule paragraph — currently `:450`). No colour
  encoding at all, so nothing is colour-only.

### 7.5 States

| State                   | Renders                                                                                                                                                                                                                            |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| First load              | Lead zone immediately; results region `aria-busy="true"` with **one** `p.admin-empty`. No skeletons — the console has no skeleton idiom.                                                                                           |
| Refetch                 | Old content stays; `.is-busy-visual` after 100 ms (the existing `setPeopleLoading` idiom). Selects are **not** disabled — disabling a focused select drops focus. Prior request aborted; a sequence token discards late responses. |
| Questions `[]`          | **`.admin-notice`**, not `.admin-empty`: states the two-account rule and that an empty list is the rule working. Must look different from a failure.                                                                               |
| Request failed (`null`) | Per zone, the existing `admin.overview.unavailable` in `p.admin-empty`. Refresh is the retry.                                                                                                                                      |
| Partial                 | Each request stands alone, exactly like the four above it.                                                                                                                                                                         |
| Stale                   | "Counted at …" built by `exactWhen()` from parts. No polling, no visibility refetch.                                                                                                                                               |

### 7.6 Question text

`td dir="auto"`, `textContent` only. Up to 160 graphemes, plain. Longer, a native `<details>`
whose `summary` is cut at the last whitespace before 160 graphemes — `Intl.Segmenter` when
present, else `Array.from`, **never `slice`**, which can split a surrogate pair or strand a
shadda. Native `<details>` gives keyboard, screen-reader state and RTL marker mirroring with zero
handlers and zero classes. `dir="auto"` on the `td` deliberately lets `text-align: start` flip per
row — the opposite of the machine-value case.

### 7.7 RTL rules specific to this surface

- **Latin digits everywhere**, from `String()` / `toFixed(1)`. Never `Intl.NumberFormat('ar')` or
  `toLocaleString('ar')`.
- **Ratios are sentences**, each number its own inline `dir="ltr"` isolate joined by
  `admin.people.of` (the pager pattern, `createPeoplePager`'s status range in
  `static/js/admin/ui.js`). Never `3 / 14`, and
  never one LTR isolate around the whole phrase — that renders "14 of 3" to an Arabic reader.
- **Two separate average tiles**, not `2.2 / 8.0`, for the same reason.
- **Never `dir="ltr"` on a `td` or `dd`** — that is the block-box alignment flip. Isolates stay
  inline.
- Author **no `letter-spacing` and no `text-transform`**. Reused labels go through
  `var(--track-caps)`, which zeroes in RTL. Do not rely on the blanket `[dir=rtl] *` reset.
- No `<caption>` — Bootstrap's LTR build aligns captions physically.
- The "Counted at" stamp is split on `{time}` (the `stampedSentence` pattern), not interpolated.

### 7.8 Controls — staged

Shipped as a second frontend commit so the owner can stop after the first:

- **Period**: 7 / 30 / 90 days, default 30. Three fixed catalogue strings, no plural engine
  (Arabic 7 takes أيام; 30 and 90 take يوماً).
- **Question language**: both / English / Arabic, default both. Element id `analytics-lang`.
- **Refresh.** No category filter — that is follow-up 6.
- Persistence in **`sessionStorage`**, validated against allow-lists on read, in try/catch. The
  language toggle reloads the page, so without it a filter dies on toggle; a URL param would be
  the console's first URL state while tabs themselves cannot be deep-linked; `localStorage` leaks
  one operator's choice to the next on a shared machine.

### 7.9 CSS — the whole change

```css
/* A wrapping row of labelled filters. `.admin-pager-size` cannot wrap and
   `.admin-notif-history-toolbar` spaces a label, a select and a button as one
   group; two groups at that gap lose their grouping. align-self: collision #15. */
.admin-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3) var(--space-5);
  align-self: start;
}
.admin-filters > * {
  flex: 0 0 auto;
}

/* Two bodies stacked in one panel keep the rhythm of zones inside one body. */
.admin-panel-body + .admin-panel-body {
  margin-block-start: var(--space-4);
}

.admin-table summary {
  cursor: pointer;
}
```

One new class, and only in the controls commit. The sibling-combinator rule also reaches
Settings' two bodies — check Settings in both languages after.

### 7.10 Copy

All keys under `runtime.admin.analytics.*` — a second-level addition inside the existing `admin`
namespace, so the eleven-name pin is untouched. Both catalogues, same commit.

Decisions that bind the wording:

- **"Recurring", not "Common" or "Frequent".** `الأسئلة الشائعة` is already the FAQ tab.
- **`scope.all` in Arabic is not `جميع الفئات`.** Inside this console `الفئات` means _Tiers_.
- Never "refusal", "unanswered", "anonymous" or "failed". The text is never called anonymous: a
  reader can type a company name into a question. The floor reduces that risk; the copy does not
  claim it is gone.
- The privacy sentence is scoped to "these lists" so it stays true when the viewer ships.
- Label + number, never a counted noun ("{n} answers"): `I18n.plural` knows two forms and Arabic
  has six.
- The scope labels are a forced duplicate of `page.categories.*`, because `page.*` never reaches
  the browser. A pytest asserts the four real category values match across the two blocks.

| Key                        | EN                                                                                                                                                                                                               |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `heading`                  | Saved conversations                                                                                                                                                                                              |
| `source`                   | Counted from conversations readers have saved. When a reader deletes a conversation, or an account is deleted, its questions leave these figures — so a number here can go down.                                 |
| `privacy`                  | These lists show saved question text without account identifiers.                                                                                                                                                |
| `quality.heading`          | Citation quality                                                                                                                                                                                                 |
| `quality.uncited`          | Found passages, cited none                                                                                                                                                                                       |
| `quality.noRetrieval`      | Search found nothing                                                                                                                                                                                             |
| `quality.scopeHint`        | Search scope is the guideline category the search ran in — set by the reader, or by the sidebar question they clicked. It is not a classification of what the question was about.                                |
| `quality.smallSample`      | Percentages appear once there are 10 saved answers. Below that, a single answer moves the figure too far for it to mean anything.                                                                                |
| `questions.heading`        | Recurring questions                                                                                                                                                                                              |
| `questions.grouping`       | Grouped by wording, ignoring capitals and spacing. Two phrasings of one question are counted separately.                                                                                                         |
| `questions.floorEmpty`     | No question was asked by two or more accounts in this period.                                                                                                                                                    |
| `questions.floorWhy`       | A question is listed only once at least two different accounts have asked it, so that no entry can point to a single reader. With few accounts this list is often empty — that is the rule working, not a fault. |
| `uncitedQuestions.heading` | Recurring questions answered without a citation                                                                                                                                                                  |

The remaining keys and the Arabic for all of them are in
[the appendix](#appendix--full-string-table). The Arabic was reviewed by the
owner on 2026-09-20. It must still be verified by code point after it lands in `ar.yaml` —
Arabic pasted through a terminal arrives reversed.

## 8. Tests

**New `web/tests/test_admin_analytics.py`**

| Test                                                                          | Note                                                                                                                   |
| ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `test_every_analytics_route_refuses_an_unauthenticated_caller` / `…_a_reader` | 404 before the routes exist                                                                                            |
| `test_questions_are_grouped_by_normalized_text`                               | two owners, different case and spacing → one group, one row once both have asked                                       |
| `test_a_question_only_one_account_asked_is_not_returned`                      | **prove non-vacuous:** swap `greatest(coalesce(p_min_askers,2), 2)` for `coalesce(p_min_askers,2)` and watch it go red |
| `test_the_asker_floor_cannot_be_lowered_through_the_route`                    | `?min_askers=1` → still absent                                                                                         |
| `test_the_asker_count_is_null_below_five_and_exact_from_five`                 | 4 distinct → `None`, 5 → `5`; prove non-vacuous by changing the `5`                                                    |
| `test_a_sidebar_question_is_flagged_and_a_typed_one_is_not`                   | FAQ text with different case, an NBSP and a trailing `؟` still flags; Arabic block included                            |
| `test_the_double_and_the_database_normalise_alike`                            | one shared fixture list of (raw, expected) pairs, read by this test **and** pasted into `rpc_behaviour.test.sql`       |
| `test_no_identity_appears_in_any_analytics_response`                          | raw body; pair it with a shape test so it cannot pass vacuously                                                        |
| `test_a_turn_with_no_retrieval_is_separated_from_one_that_cited_nothing`      | pins correction 3                                                                                                      |
| `test_citation_stats_break_down_by_lang_and_category`                         | asserts the three `scope` values                                                                                       |
| `test_deleting_a_conversation_removes_it_from_the_aggregate`                  | pins retroactivity as intended                                                                                         |
| `test_an_unknown_lang_is_422` / `test_an_unparseable_window_is_400`           |                                                                                                                        |

**Database, run by hand:** `function_acls.test.sql` gains an existence check plus the
no-identifier-in-result check; `rpc_behaviour.test.sql` gains a block proving normalisation and
the floor against real Postgres — the only place either is proven off a Python double.

**New `web/tests/test_admin_analytics_browser.py`** — 25 named tests in the UI lane's report.
The ones that catch a real regression rather than restate the design:

- `test_an_empty_question_list_reads_as_a_privacy_rule_not_a_fault`, and its twin
  `test_a_failed_question_request_is_not_shown_as_the_privacy_floor`
- `test_percentages_are_withheld_below_ten_saved_answers` (n = 9 and n = 10)
- `test_changing_the_period_refetches_all_three_and_keeps_focus_on_the_select`
- `test_out_of_order_analytics_responses_resolve_to_the_last_choice`
- `test_a_ratio_reads_count_then_total_in_arabic` (bounding boxes, not text)
- `test_analytics_numbers_stay_latin_and_carry_no_bidi_marks_in_arabic`
- `test_question_text_is_never_parsed_as_html`
- `test_the_accounts_column_is_absent_until_a_row_has_an_exact_count`, and
  `test_a_bucketed_row_reads_two_to_four_beside_an_exact_one`
- `test_a_sidebar_question_carries_its_mark`
- `test_a_slow_analytics_request_does_not_delay_the_overview_figures`

Use real keystrokes, not `fill()`, anywhere user activation matters.

`test_frontend_architecture.py` gains one assertion that the console actually _reads_
`I18n.t('admin.analytics.` — a key present in both catalogues and read by nothing is a failure
this repo has shipped twice, and parity cannot see it.

Every new test is run against the pre-change code first.

## 9. Commit sequence

Schema before code, one concern per migration, **rename each file to what `list_migrations`
reports after applying**. Each step is green on its own.

| #   | Change                                                                                                                                                                                              | Document it makes wrong — fix in the same commit                                                                                                                                                                                                                                                                                                 |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Migration: `chat_messages_assistant_created_idx`. Header records the live row count at apply time.                                                                                                  | None. First, so it can be dropped alone.                                                                                                                                                                                                                                                                                                         |
| 2   | Migration: `admin_top_questions`. Header: no `p_owner_id` and why; the floor is un-lowerable; `owner_id` is read and never projected.                                                               | **`supabase/README.md:125`** — RPC contract point 5 ("`p_owner_id` as the first argument") is stated unconditionally and is already violated by three `admin_*` readers. Add the sentence scoping it to reader-facing functions.                                                                                                                 |
| 3   | Migration: `admin_citation_stats`.                                                                                                                                                                  | None.                                                                                                                                                                                                                                                                                                                                            |
| 4   | `function_acls.test.sql` + `rpc_behaviour.test.sql` additions; record the new `PASS … — N assertions` line.                                                                                         | **`docs/ARCHITECTURE.md:518`** — the literal assertion count in the "mechanically enforced" table.                                                                                                                                                                                                                                               |
| 5   | `admin_store.py` Protocol + both backends + allow-lists; `app.py` doubles reorder; backend-level tests.                                                                                             | None.                                                                                                                                                                                                                                                                                                                                            |
| 6   | The two routes and their validation; gate / 400 / 422 / no-identity-over-the-wire tests.                                                                                                            | None — the routes inherit the blueprint's 60/minute, so the rate-limit table needs no row. Say so in the commit message.                                                                                                                                                                                                                         |
| 7a  | Template sibling div, `services.js`, `ui.js`, `handlers.js`, both catalogues, the sibling-combinator CSS rule, **`ASSET_VERSION` bump**, browser tests. Fixed 30 days, both languages, no controls. | **`DESIGN.md:375-384`** says the Overview "adds no endpoint", has "four requests", and "every figure links to the tab that owns it" — all three become false. Record the deliberate departure (analytics figures link nowhere; no tab owns them). Also the comments at `static/js/admin/ui.js:2585-2591` and `static/js/admin/handlers.js:1391`. |
| 7b  | Controls: `.admin-filters`, `sessionStorage`, abort + sequence token, the filter tests, **`ASSET_VERSION` bump**.                                                                                   | None.                                                                                                                                                                                                                                                                                                                                            |
| 8   | Close the `TODO.md` entry per its own procedure. Record what stayed out: unanswered text below the floor, the category caveat, Arabic orthographic folding, trailing `?` / `؟`.                     | —                                                                                                                                                                                                                                                                                                                                                |

If the implementer cannot reach the project, the three SQL files wait in `supabase/pending/` as
`01_`…`03_`.

**How the seven follow-ups slot in.** (1) click-through: an additive `sample_session_ids` column,
and a row builder that is already one function. (2) thumbs down: its own column; the stats rows
already have a slice to hang a rate on. (4) daily counts: a fourth grouping set on
`date_trunc('day', …)`; the client already ignores a `scope` it does not know. (6) per-category:
`p_category` and the service parameter already exist; add a third control. (3), (5), (7) belong
to the viewer and are untouched.

## 10. Risks

| Risk                                                                                                                                                                                                                                                                                                     | Resolution                                                                                                                                                                                                                             |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The question list is **empty at three accounts** and the feature looks broken on day one.                                                                                                                                                                                                                | Accept. Do not lower the floor. Citation stats need no threshold and carry real numbers at once, and the empty state states the rule as a policy.                                                                                      |
| **`set statement_timeout` would break `function_acls.test.sql`.** Its `search_path` check is `!~ 'search_path=("")?$'` (`supabase/tests/function_acls.test.sql:170`), anchored at the end. `set search_path = '' set statement_timeout = …` yields `search_path="",statement_timeout=…`, which fails it. | No timeout in V1 — clamped `p_days` and `p_limit` bound the queries. If one is ever wanted, the `search_path` clause must come **last**. Also: `SET LOCAL` inside a `language sql stable` body, which one lane proposed, is not legal. |
| Unrouted analytics fetches in the _existing_ overview browser tests. `_overview_console` (`web/tests/test_admin_browser.py:2196`) routes four endpoints; the two new ones will fall through to the test server.                                                                                          | **Unverified.** Check in commit 7a whether that produces a console error or a toast that an existing test asserts against. If it does, add a default analytics route to `_overview_console`.                                           |
| `admin_citation_stats` with a narrow window plus `lang` plus `category` can read `turns = 1` — activity disclosure at tiny n, no content.                                                                                                                                                                | Accept and document. The 7-day floor keeps any single response at a week or more; adjacent windows can still be subtracted into a per-day count (section 4.1). Counts carry no text, so no threshold.                                  |
| Normalisation does not fold alef / yaa / taa-marbuta variants or tashkeel, so some Arabic questions fragment.                                                                                                                                                                                            | Accept for V1. It affects only the admin list, never an answer. Changing the normaliser later is free, but it regroups history — period-over-period counts are not comparable across the change.                                       |
| Suspected existing RTL defect: `[dir="rtl"] select.admin-input` (`static/css/admin.css`) puts the chevron on the physical left but pads `inline-start`, which in RTL is the right. The new selects inherit it.                                                                                           | **Reasoned, not observed.** Probe it in the 390px Arabic test. If real, fix separately with a failing-first test.                                                                                                                      |
| `th scope="row"` takes the UA bold weight; no console table uses row headers today.                                                                                                                                                                                                                      | Check in both scripts; if too heavy, one declaration on `.admin-table tbody th`.                                                                                                                                                       |

## Decisions

Taken by the owner on 2026-09-20, then put to an adversarial read-only review (OpenCode,
`muse-spark-1.3`) alongside the orchestrator's own reading. All three stand; each was refined.

1. **Floor of two distinct accounts, hard-coded in SQL — yes.** A question group is returned only
   if at least two distinct _surviving_ accounts asked it, enforced as
   `having count(distinct owner_id) >= greatest(coalesce(p_min_askers, 2), 2)`, with no route
   parameter. It is what lets V1 ship with no privacy-policy edit (`page.policy.useImprove`
   already says "in aggregate — never to single out one person's activity") and no audit row per
   read. Overruling it reopens both.
   _Refinement:_ the asker count is **bucketed in SQL** — `NULL` below 5, exact from 5 up
   (section 4.1) — and the window has a 7-day floor. An intermediate draft dropped the count
   entirely; that was reversed the same day because it could never tell "10 asks from 9
   accounts" from "10 asks from 2" at scale, and fixing it later costs a function drop. _Residuals accepted:_ one person with two accounts defeats the count; a deletion
   can drop a group back under the floor retroactively; singleton questions — often the most
   worth reading — stay hidden. _Rejected:_ excluding admin accounts from the count (with one
   admin and two readers, a listed row still means both readers asked it) and a floor of three
   (at three accounts that lists only unanimous questions).
2. **Strip trailing punctuation when normalising — yes, widened.** Not only a trailing `?` / `؟`
   but the whole trailing run of `?` `؟` `!` `.` `۔` `…`, plus the Unicode-space and zero-width
   handling in section 4.1, which matters more than the punctuation does.
   _Correction:_ the collision risk is **negligible, not zero** — `Renew the licence!` and
   `Renew the licence?` merge. Same topic, same retrieval, so it is the cheap kind of collision.
   (The reviewer's own counter-example, `…requires X.` against `Does … require X?`, does not
   collide: the two normalise to different strings.)
3. **"By category" is the reader's search scope — ship it, and drop the "or switch now" branch.**
   The premise that the breakdown would be "99% `all`" was never measured; measured, roughly a
   third is `all`. The cited-documents alternative is **not** the same cost and not a drop-in: a
   turn with no retrieval has no source rows at all, so it cannot be attributed — and that slice
   is half the quality story; a turn citing several categories needs a tie-break; and a
   non-`all` scope filters both searchers, so there the source category merely echoes the scope.
   For the copy: `all` also holds requests that never sent a category, so it means "chose all,
   or never chose".
   _Deferred candidate, to record in `TODO.md`:_ modal **retrieved**-source category, restricted
   to scope-`all` turns.

**Added to V1 on 2026-09-20: the sidebar-question flag** (section 6). Without it the list
mostly mirrors `faq.yaml`. It also corrects a reading in decision 3: FAQ clicks carry the FAQ's
category, so part of the non-`all` share is sidebar buttons rather than reader choice — hence the
hint says "the category the search ran in", not "the category a reader chose".

**Found by the review, affecting later work:** follow-up 1 (click-through) is not "one frontend
link". Any `sample_session_ids`-style column is access to a reader's own content — the line
`web/services/audit.py:14-18` draws — so it inherits the conversation viewer's per-open audit
rule. The analytics RPCs must never gain a drill-down without it.

Defaults: 30 days, 20 rows, percentages from n ≥ 10, periods of 7 / 30 / 90 days.

---

## How this plan was made

Four lanes ran in parallel on 2026-09-20. None edited the repository; `git status` was clean
after each.

| Lane                        | Model                                                                               | Outcome                                                                                                                                                                                                      |
| --------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Architecture and scoping    | Claude Opus 5                                                                       | Delivered. Source of sections 2–6 and the commit table.                                                                                                                                                      |
| Technical and design-system | OpenCode, `muse-spark-1.3`, variant `max`                                           | Delivered. Source of the allow-list pattern, extensibility notes and route conventions.                                                                                                                      |
| UI/UX                       | Codex, `gpt-5.6-sol`, effort `xhigh`                                                | **Failed — ChatGPT usage limit** after 71 read commands, before any plan. Resets 2026-09-21 00:09; thread `01a0bf94-24f2-7600-80a6-a0afd9879383` is resumable. One decision survived and is recorded in 7.2. |
| UI/UX (substitute)          | Claude subagent, same brief plus the settled data shapes                            | Delivered. Source of section 7 and the browser-test list.                                                                                                                                                    |
| Web research                | Antigravity, `gemini-3.8-flash-high`                                                | Delivered. See the reference note below.                                                                                                                                                                     |
| Decision review             | OpenCode `muse-spark-1.3` (read-only), then an owner brainstorm with the same model | Delivered. Source of the asker-count bucket and several normaliser characters. The orchestrator added the measured `\s` behaviour, the category distribution and the sidebar-question finding.               |

**Where lanes disagreed, and what won**

| Question                | Positions                                                                                                               | Decision                                                                                                                                               |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Turn join key           | `seq + 1` (OpenCode) vs `(session_id, client_request_id)` (Opus, research)                                              | `client_request_id`. OpenCode rejected it as "per-submission, not per-pair", which the `(session_id, client_request_id, role)` unique key contradicts. |
| Actor gate on read RPCs | gate with `p_actor_id` (OpenCode) vs none (Opus)                                                                        | None — matches `admin_list_tiers` and `admin_list_users`. OpenCode's `p_actor_id default null` would also have made its own gate optional.             |
| Index                   | normalised-text expression index (research) vs defer everything (OpenCode) vs partial `created_at` index now (Opus)     | Opus's. The expression index would break inserts on long questions.                                                                                    |
| Statement timeout       | `SET LOCAL … '10s'` (OpenCode) vs none (Opus)                                                                           | None. Not legal in that function kind, and it trips the ACL test.                                                                                      |
| Return shape            | percentages and averages in SQL over a lang×category cross product (OpenCode) vs counts over three grouping sets (Opus) | Counts. Small-n handling belongs in the client.                                                                                                        |
| Privacy floor           | none (OpenCode) vs UI default with an admin override (research) vs SQL, un-lowerable (Opus)                             | SQL. An override is a floor that is not one.                                                                                                           |
| Overview integration    | extend `renderOverview` (Opus, OpenCode) vs sibling container (UI)                                                      | Sibling — section 7.1.                                                                                                                                 |
| Audit row on read       | required by PDPL (research) vs not needed with the floor (Opus)                                                         | Not needed. The research claim rests on a source that was not read; the repo's own rule decides it.                                                    |

**Verified by the orchestrator against the code, not taken from a lane:** the assistant-row-only
metadata and both unique keys (`20260820131914…sql:86-100`); no `created_at` index on
`chat_messages`; `category` defaulting to `"all"` (`app.py:3150`); `empty_answer` at
`app.py:3927` and `:4277-4301`; the testing-double construction order (`app.py:2312-2322`);
`audit.py:14-18`; the end-anchored ACL regex (`function_acls.test.sql:170`); the two overview
assertions a non-sibling design would break (`test_admin_browser.py:2245`, `:2249`);
`README.md:125`; `MAX_CHAT_QUERY_CHARS` (`app.py:356`). Everything else carries its lane's own
verification claim and should be re-read before it is relied on.

**Reference note.** The research lane cited 28 URLs. An HTTP check found **8 return 404** —
the Arize Phoenix, Zendesk, Algolia, Intercom, NN/g, RobiFox, W3C `typography-arabic` and
Princeton links — and one returns 403. Those are dropped. The rest resolve, but **none was read
by the orchestrator**, so they are leads, not citations:

- Small-n ratios: <https://www.evanmiller.org/how-not-to-sort-by-average-rating.html>
- Query thresholding as a privacy control: <https://support.google.com/webmasters/answer/6155685>
- k-anonymity: <https://arxiv.org/abs/cs/0212008>
- Bidi markup: <https://www.w3.org/International/articles/inline-bidi-markup/>
- RTL layout: <https://m2.material.io/design/usability/bidirectionality.html>,
  <https://developer.apple.com/design/human-interface-guidelines/right-to-left>
- Use of colour: <https://www.w3.org/WAI/WCAG21/Understanding/use-of-color.html>
- Empty states: <https://carbondesignsystem.com/patterns/empty-states-pattern/>
- Expression indexes: <https://www.postgresql.org/docs/current/indexes-expressional.html>
- Saudi PDPL: <https://sdaia.gov.sa/en/SDAIA/about/Pages/PersonalDataProtectionLaw.aspx>

The research lane's PDPL claims (k-anonymity expectations, mandatory operator access logging) are
**not** relied on anywhere in this plan. Legal review is parked by the owner per the TODO entry.

## What is not verified

- No `EXPLAIN` has been run on either function at volume — clamped `p_days` / `p_limit` bound
  today's queries, but nobody has measured a real plan.
- Only the new `rpc_behaviour.test.sql` block (19 assertions) ran today; the pre-existing 24 in
  that file were not re-run.
- The Arabic has not yet been eyeballed rendered in the console by the owner — reviewed as text on
  2026-09-20 (section 7.10), not seen on screen.
- The `[dir="rtl"] select.admin-input` defect (section 10) is **real and not fixed here**: the
  chevron sits on the physical left, 12px in, while the 48px of clearance lands on the right.
  Measured on `#analytics-window` at 390px; the Settings model select shows the same geometry, so
  it predates this work. It wants its own failing-first commit.
  **Fixed 2026-09-21, in its own commit.** The cause was narrower than "pads the wrong side":
  the base rule's `padding-inline-end` already mirrors, and the RTL override swapped it back.
  The override's two padding lines are deleted; its `background-position` stays. Pinned by
  `test_a_select_keeps_its_chevron_clearance_on_the_chevron_side_in_arabic`, red against the
  old rule (`12.0 > 48.0`).

## Build record (2026-09-20)

All of V1 was built today, 7b included. `web/tests/test_admin_analytics_browser.py` holds 31
tests: 21 for the region, 8 for the controls, 2 found in review.

**7b and the review pass.** The controls are one `role="group"` in the lead zone, reusing the
pager's label/select classes; `.admin-filters` is the only new class. `setPeopleLoading` was
generalised into `setRegionBusy`, its single timer becoming a `Map` keyed by region, because two
regions can now be in flight at once. **The sequence token matters more than section 7.5 says:**
measured by deleting it, the abort alone still lets an abandoned run paint three "could not load"
lines, because `allSettled` resolves with the `AbortError`s. The abort stops the traffic; the
token stops the paint. Two race tests first passed with the token deleted — Playwright's retrying
assertions forgive a flash — and were rebuilt on a `MutationObserver` that records every state
the region passes through. The `updated` announcement is an `.sr-only` polite live region: a
sighted operator already sees the figures and the stamp change.

Found by the orchestrator reading the agent's Arabic screenshot, each fixed failing-first: the two
selects inherited the pager's mono face, which has no Arabic, so its fallback set every letter of
`اللغتان` apart — now `var(--font-sans)`; and `th scope="row"` took the UA's 700 against 400 in
every other cell (section 10's last row) — now `var(--fw-body)`. The Settings tab's two bodies
gained the intended 16px gap in both languages and look right. `retrievedPerAnswer` wraps to about
three lines as a column header at 390px in Arabic; the table scrolls inside its panel and the page
does not overflow. Same-face selects in the notification-history toolbar were left alone: not this
feature's surface.

**Built and green.** Three migrations applied live and renamed —
`supabase/migrations/20260920192349_chat_messages_assistant_created_idx.sql`,
`20260920192411_admin_top_questions.sql`, `20260920192419_admin_citation_stats.sql`;
`AdminBackend.top_questions` / `citation_stats` on both backends, plus `normalize_question()`, in
`web/services/admin_store.py`; `InMemoryChatBackend.turns()` in `web/services/chat_store.py`;
routes `GET /admin/api/analytics/questions` and `/citations` in `web/api/admin.py`; 44 strings
under `runtime.admin.analytics` in both catalogues; the `#overview-analytics` region
(`web/templates/admin.html`, `static/js/admin/{services,ui,handlers}.js`, two CSS rules);
`web/tests/test_admin_analytics.py` (66 tests).

**Live database results.** `function_acls.test.sql` PASS 11 assertions (was 9). The new
`rpc_behaviour.test.sql` block PASS 19 assertions run standalone (file total 43 at the time, was
24 — the pre-existing 24 were not re-run today). _Corrected 2026-09-21: `grep -c "n := n + 1"
supabase/tests/rpc_behaviour.test.sql` now reads 45, not 43 — two more assertions landed in this
file after this record was written (another lane's normalisation addition; not this session's
doing). The file total is 45 as of today, not 43, and `docs/ARCHITECTURE.md`'s running total is
corrected to match — see that document._ Four falsification runs each went red at the intended
assertion: floor lowered → B2; bucket held at 4 → C1; window clamp removed → D1; U+00A0 dropped
from the space class → A1. The Python `normalize_question` and the live Postgres expression agree
on all 21 pairs of `NORMALISATION_FIXTURE`. Security advisors: no new finding.
`docs/ARCHITECTURE.md`'s assertion total was updated 175 → 196. _Corrected 2026-09-21: with
`rpc_behaviour.test.sql` measured live at 45 assertions rather than 43 (see above), the arithmetic
is 175 + 2 + 21 = 198, not 196; `docs/ARCHITECTURE.md` now reads 198._

**Corrections found during the build** — each is a correction to the text above, not a silent
edit of it:

1. Section 4.2's `sum(t.cited_count)` / `sum(t.retrieved_count)` return `numeric`; the shipped
   function casts both `::bigint` to match `returns table`.
2. Section 4.1's trailing-punctuation class is shipped as regex-escape sequences for the Arabic
   question mark, Arabic full stop and horizontal ellipsis (codepoints U+061F, U+06D4, U+2026)
   rather than the raw characters typed inline — same semantics, a reviewable file. (Typing the
   literal escape syntax here hit the same tool-transport decoding bug described in correction 3,
   so it is described by codepoint instead.)
3. A tool transport decoded every `\uXXXX` typed into a parameter into the raw character. It put
   raw invisible characters into the first live copy of `admin_top_questions` (re-created in
   place, verified zero non-ASCII in `prosrc`, noted in the migration header), into three regex
   lines of `admin_store.py`, and into `test_admin_analytics.py` — all repaired by the
   orchestrator. Two lane self-reports had claimed the escapes were verified; they were not.
4. The route parser rejects `days` / `limit` ≥ 2^31 with `400 invalid_window` (Postgres would
   refuse the int4 argument and surface a 500); otherwise out-of-range values are clamped
   downstream, not refused. Section 6 left this open; it is now the shipped behaviour.
5. Added beyond section 8's table because a break-matrix showed the filters were otherwise
   untested: `test_a_filter_narrows_both_routes`, `test_an_empty_string_filter_is_no_filter`, and
   SQL assertions (g) for `p_category`.
6. The `from_faq` mark uses the bare existing `.admin-mark` class, no variant — the variants
   encode state, and provenance is not a state.

**Resolved from _What is not verified_ above:**

- `InMemoryChatBackend` does store `lang`, `category`, `created_at` and per-source `cited` in a
  shape the in-memory aggregate can read usably — owner lives on the session. Commit 5 grew by one
  read accessor, `turns()`; no `seed_turns()` was needed.
- Unrouted analytics fetches do not disturb the existing overview browser tests: all 99 admin
  browser tests are green unedited, and a failed analytics fetch raises neither a toast nor a
  `pageerror`.
- The twelve frozen English strings do not collide with the new copy.
- The `DESIGN.md:375-384` anchor cited in the commit-sequence table (section 9) was rechecked on
  2026-09-21 against the live file: it is unchanged and still correct. The claim of drift to
  `~:386-395` recorded here on 2026-09-20 does not hold up against a direct read — `:375-384` still
  opens on "adds no endpoint" and closes on the `Promise.allSettled` sentence; `:386-395` is the
  separate departure paragraph added right after it, not a moved copy of the same text.

**Anchors corrected 2026-09-21.** A documentation-verification pass swept every `path:line`
anchor in this plan against the code as it stands today; `git status` and the diff hash of every
non-doc file were unchanged by it. Ten were wrong. Eight had shifted because this build's own
edits moved the lines they used to point at: `app.py:3146` → `:3150` (category default),
`app.py:4282-4296` → `:4277-4301` (blocking-route `empty_answer` guard — `TODO.md` already had
this one right, so only this document needed the fix), `app.py:2315`/`:2318` →
`:2316`/`:2319` (testing-double construction, already reordered), `app.py:2312-2324` → `:2312-2322`
(tightened to the actual construction block); `admin_store.py:318-337`,
`static/js/admin/ui.js:679-694` and `static/css/admin.css:272-276` are now cited by symbol
(`_DELETION_LEDGER_COLUMNS`, `createPeoplePager`, `[dir="rtl"] select.admin-input`) rather than a
line, because those three files — plus `app.py` and `DESIGN.md` — are under concurrent edit today
and a line number would go stale again before this lands. The other two predate this build and
were simply wrong, unrelated to today's edits: `DESIGN.md:440` (the "merely true" sentence is
at `:450`) and `supabase/tests/function_acls.test.sql:162`, cited twice, is really `:170` — the
end-anchored `search_path` check is one `if` block further down than recorded. `web/templates/admin.html:178-179`
was also wrong (the two sibling `.admin-panel-body` divs are at `:186-187`); `admin.html` is not
being edited today, so that one is a plain fix, not a symbol substitution.

## Adversarial review of the build (2026-09-20)

OpenCode, `muse-spark-1.3`, variant `max`, read-only `plan` agent; `git status` and the diff
hash were identical before and after. Thirteen findings and two simplifications, no blocker.
Each was checked against the code before anything changed, and every fix below has a test that
was watched failing with the fix reverted.

| #   | Finding                                                                                               | Verdict                                                                                                                                                                                                                                                                                  |
| --- | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | A hand-edited `faq.yaml` with a non-mapping block or a bare-string question 500s the questions route. | **Confirmed, fixed.** `/api/frequent-questions` already guards `isinstance(block, dict)`; the new traversal now guards all three levels.                                                                                                                                                 |
| 2   | The two `questions` requests return the same rows, so fetch once and sort in the client.              | **Rejected — the premise is false.** Both calls carry `limit=20`, so past twenty groups `order=uncited` returns rows the `asks` ranking cut off; a client sort of the top twenty by asks would silently drop the question with the most uncited answers. True only while groups ≤ limit. |
| 3   | The 7-day floor has no Python test, and the double cannot seed an old turn.                           | **Confirmed, fixed.** `test_a_window_narrower_than_seven_days_is_widened_to_seven` backdates a saved session (3 and 8 days) and pins both the floor and the bound, on both routes. Removing the floor from the double turns it red.                                                      |
| 4   | "The floor stops differencing" is false: `p_days => 8` minus `=> 7` is a one-day slice.               | **Confirmed — a wrong sentence, not a wrong function.** Reworded in both migration headers, section 4.1 and the risk table. Snapping `p_days` to 7 / 30 / 90 would close it; not done, because the two-asker floor holds per call and the residue is a date on an already-listed group.  |
| 5   | The citations route 400s on a bad `limit` it never reads.                                             | **Confirmed, fixed.** `_parse_analytics_window(**defaults)` parses only what the route names.                                                                                                                                                                                            |
| 6   | The change handler skips the allow-list the storage read applies.                                     | **Confirmed, fixed.** One `validAnalyticsFilters()` gates both. A forged `<option value="xx">` used to earn a 422 and blank every zone.                                                                                                                                                  |
| 7   | "never who asked it" over-promises when the question itself names a company.                          | **Valid, left for the owner.** Section 7.10 made this trade knowingly and the string was owner-reviewed in both languages twice; a rewording needs the same review. Candidate: "never which account asked it".                                                                           |
| 8   | `3 of 3000` renders `0%`.                                                                             | **Confirmed (also found independently), fixed** both ways: `<1%` and `>99%`.                                                                                                                                                                                                             |
| 9   | `admin_citation_stats` has no `order by`; the double sorts; the table keeps arrival order.            | **Confirmed, fixed in the client** — one comparator, known buckets in the reader's selector order, so both backends draw one table and the live function is not redeployed for a presentation concern.                                                                                   |
| 10  | A NULL `lang` / `category` bucket renders an empty row header.                                        | **Confirmed (also found independently), fixed** by borrowing the console's existing `admin.account.emailVerifiedUnknown` ("Unknown") rather than adding a 45th string. The live table holds no NULL in either column today.                                                              |
| 11  | The browser tests' default `askers=2` is a value production never emits.                              | **Confirmed, fixed.** Default is `None`; every test still passes, so none depended on it.                                                                                                                                                                                                |
| 12  | The `updated` live region is set to the same sentence twice and may announce once.                    | **Plausible, unproven with a screen reader; fixed cheaply** — the region is emptied when a refetch starts.                                                                                                                                                                               |
| 13  | A preview with no whitespace to cut at is 161 graphemes.                                              | **Confirmed, fixed.**                                                                                                                                                                                                                                                                    |
| (a) | Move the `None`-sum fix-up into SQL as `coalesce(sum(…), 0)`.                                         | **Rejected.** It moves four lines rather than deleting them — the backend must still drop the all-zero `total` row — and costs a live redeploy.                                                                                                                                          |
| (b) | The two browser helpers duplicate the operational route setup.                                        | **Confirmed, fixed.** One `_route_operational(page)`.                                                                                                                                                                                                                                    |

What the review tried to break and could not is a useful list in its own right: XSS through
question text, identity in any response, a NULL `client_request_id` escaping the self-join,
`coalesce(t.lang, t.category)` mislabelling a grouping set, partial-index usability, Python 3.10
compatibility, question text in logs, gating and rate limits, catalogue parity, and the abort /
sequence-token interleavings.

## Second adversarial check (2026-09-21)

Codex, `gpt-6-astra`, effort `medium`, read-only sandbox, one run; tree and diff hash unchanged.
Quota was the constraint, so the brief inlined the two functions, the double, the routes and the
refetch logic, and asked six questions — the contested ones — rather than for a sweep. No blocker.
It changed no code and corrected two claims this plan had made since its first draft.

| #   | Question put to it                                          | Outcome after checking                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| --- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Three requests, or fetch once and sort in the client?       | **Agrees with the rejection**, with the counter-example: twenty groups of 100 cited asks, a twenty-first with 99 asks all uncited. A larger limit only moves the failure point.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| 2   | Is "the floor holds per call" a sound privacy argument?     | **Disagrees, and is right.** The floor is a release rule for one result, not protection against inference across results: an operator who asks a suspected question themselves turns a singleton into a listed group and learns somebody else asked it; two windows subtract; a group vanishing after a known deletion names a contributor; raising `p_min_askers` to 3 or 4 recovers the exact count the bucket hides. No combination surfaces a group only one account asked. **Docs corrected; no code change** — the threshold oracle needs the service key, which reads the table anyway (measured, see section 4.3). The operator-as-asker probe is the one with teeth and is an owner decision (below). |
| 3   | SQL correctness.                                            | **No defect.** Confirmed by measurement: `owner_id` is `not null`, `chat_messages_session_owner_fk` keeps a turn's two rows under one owner, and the source lookups ride `chat_message_sources_unique_index` (seen in `EXPLAIN`). `coalesce(sum(…), 0)` rejected a second time, same reason. An `assistant_id` tie-break on the representative phrasing rejected: a tie needs two turns committed in the same microsecond, and it would cost a live redeploy.                                                                                                                                                                                                                                                  |
| 4   | Where do the double and the database disagree?              | **Nothing reachable.** Its candidates rest on inputs the double never receives: every `created_at` is written by `append_turn` as UTC ISO text, so the string ordering it worried about is the chronological one; regex parity was proven against the live expression on 21 pairs, which the brief did not show it.                                                                                                                                                                                                                                                                                                                                                                                            |
| 5   | Find an interleaving that paints stale data or sticks busy. | **None stands.** Its one candidate — `storeAnalyticsFilters` throwing before the refetch — cannot happen: that function already swallows storage errors, which the brief had not inlined. `request()` is `async`, so no synchronous throw precedes `allSettled`. It independently confirmed the abort / token logic is sound for every real overlap.                                                                                                                                                                                                                                                                                                                                                           |
| 6   | The privacy sentence.                                       | **Agrees it over-promises**, and argues "never which account" still sounds like a guarantee against inference. Its wording: "These lists show saved question text without account identifiers." Owner decision, both languages.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |

**Left for the owner, from this check:** whether an administrator's own account should count
toward the two-asker floor. Section _Decisions_ rejected excluding admins because a listed row
would still mean two readers asked it. The probe above is a reason that argument did not weigh:
while the operator counts, they can manufacture the second asker for any wording they can guess.
Excluding `role = 'admin'` owners from the distinct count closes it for a single operator account
(not for one who also holds a reader account — the residual already accepted), at the cost of a
join to `profiles` and a function redeploy.

## Third review (2026-09-21)

A reviewer the owner ran separately, ten angles, fifteen findings and a list of runners-up, all
with the gates green — so everything in it was latent, cross-engine or documentary. It is the
review that found the most, because it measured instead of reading.

| #   | Finding                                                                                                                               | Outcome after checking                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| --- | ------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1–2 | The Python normaliser and the SQL disagree on U+2028, U+2029, U+0085 and U+001C–U+001F.                                               | **Confirmed against the live expression, code point by code point (52 space, control and format characters): exactly those seven disagreed.** Postgres's `\s` matches the two separators; a bare `.strip()` eats the other five where `btrim` does not. Python now matches: the separators join the space class and the trim is `.strip(" ")`. All 52 agree. Five fixture pairs and an SQL assertion pin it. The earlier "agree on all 21 pairs" was true and proved less than it sounded — none of the 21 was one of these.                         |
| 3   | A non-string `text` in `faq.yaml` (`2026`, `yes`) 500s the questions route.                                                           | **Confirmed, fixed** — `isinstance(…, str)`. The first review's fix guarded the containers and not the leaf.                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| 4   | A failed `order=uncited` request is drawn as nothing when the asks list is `[]`.                                                      | **Confirmed, fixed.** The zone is omitted only when both say "nothing".                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| 5   | `Boolean([])` is true, so `counted` means "something answered".                                                                       | **Half confirmed.** Announcing "updated" over one failed zone stands — the other zones did update, and failure is per zone by contract. A refetch where all three fail now announces `admin.overview.unavailable` instead of silence. The expression is respelt so it says what it means.                                                                                                                                                                                                                                                            |
| 6   | `?category=all` filters to the literal scope `all`, which the catalogue labels "All categories".                                      | **Correct as built, and a trap for follow-up 6.** `all` is a real stored scope and a real breakdown bucket. The category selector must add its own no-filter option rather than reuse that label. Recorded in `TODO.md`.                                                                                                                                                                                                                                                                                                                             |
| 7   | Ties break under the database collation in SQL and by code point in the double, and the tie-break decides which rows survive `limit`. | **Confirmed (measured), fixed in SQL** — `s.normalized collate "C"`, migration `20260920222831`. My first assertion for it was vacuous: its three keys sort identically under both collations. Replaced with four that do not, and shown red against the function without the `collate`.                                                                                                                                                                                                                                                             |
| 8   | The two question tables can disagree on whether there is an Accounts column.                                                          | **Confirmed, fixed** — derived once from both payloads.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| 9   | The statement recorded for migration `20260920192411` is not the file, and the hand repair was in no file.                            | **Confirmed (3,315 recorded characters, 15 of them non-ASCII). Resolved by the same migration as 7**, which is written so the transport has nothing to decode: recorded length 4,342, zero non-ASCII, file 4,343 bytes with its newline. Replaying the two files in order reproduces the live function.                                                                                                                                                                                                                                              |
| 10  | `loadAnalytics()` has no catch; a second Overview activation rebuilds the lead zone.                                                  | **Both confirmed, fixed.** A throw lands as "could not load" behind the sequence token; the lead renders once. One correction to the report: a throw inside the results renderer left the region blank, not busy.                                                                                                                                                                                                                                                                                                                                    |
| 11  | `fromisoformat` on Python 3.10 rejects `Z` and naive stamps.                                                                          | **Rejected as unreachable** — only `append_turn` writes the field, always as UTC ISO text.                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| 12  | `turns()` pairs rows by list position with `strict=True`.                                                                             | **Confirmed, fixed** — paired by role with `itertools.pairwise`, so an unpaired row is dropped as the SQL join drops it, and a test proves a stray row no longer turns every later answer into a question.                                                                                                                                                                                                                                                                                                                                           |
| 13  | The double counts `cited` by truthiness.                                                                                              | **Rejected as unreachable** — `_validate_sources` stores a `bool`. What `bool("false")` does on the way in is the chat double's own, older behaviour.                                                                                                                                                                                                                                                                                                                                                                                                |
| 14  | The test module claims the fixture is pasted verbatim into the SQL test.                                                              | **Confirmed, fixed** — the docstring now says what actually ties the engines together, and that it is run by hand.                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| 15  | A leading space collapses a long question's preview to `…`; the fallback walk can strand a shadda.                                    | **Both confirmed, fixed**, and the segmenter is built once.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| —   | Runners-up.                                                                                                                           | **Taken:** ten drifted anchors in this plan, a citation to a scratch file, the assertion total (now 198), a false reason in the rate-limit comment, `?days=` answering 400 while `?lang=` means no filter, a stale test docstring, and a seventeenth row in _Rules that collide_ for the `p_owner_id` scoping. **Not taken:** the duplicate `order=uncited` call (settled twice above), a lateral join and the double's triple materialisation (no measured cost), and `scope.all` differing from `page.categories.all` (deliberate — section 7.10). |

**Owner decisions taken the same day.** Administrators keep counting toward the two-asker
floor: excluding them closes the self-ask probe only for an operator with one account, costs a
join and a redeploy, and at three accounts would demand unanimity from both readers. Revisit
when administrator test traffic pollutes the counts, not for privacy. The privacy sentence is
now "These lists show saved question text without account identifiers." — what the surface
does, not what an attacker cannot infer. **Its Arabic is an orchestrator draft and has not been
through the owner's reviewer**, unlike the other 43 strings.

## Appendix — full string table

All keys are relative to `runtime.admin.analytics`. Reused rather than duplicated:
`admin.overview.unavailable`, `admin.people.of`. **The Arabic column was reviewed by the owner with a
reviewer on 2026-09-20** and 22 strings were rewritten to read as Arabic written for an admin
console rather than translated into it (the `privacy` string was replaced on 2026-09-21 and its
Arabic is an unreviewed draft — see _Third review_). A second, final pass the same day changed eight more. Two of those
overrule the orchestrator's earlier picks, and are recorded as such: `scope.all` is
`جميع فئات الإرشادات` (qualified, so it does not collide with `الفئات` = _Tiers_), not
`جميع نطاقات البحث`; and `retrievedPerAnswer` takes the natural `التي عثر عليها البحث` over the
shorter `المسترجعة`. That key also heads a column in the six-column breakdown table, so **check
how it wraps at 390px in commit 7a**. Both Arabic averages say `متوسط` ("average"), which the
English labels only imply. Still required when the strings land in `ar.yaml`: verify by code point.

| Key                          | EN                                                                                                                                                                                                               | AR (owner-reviewed 2026-09-20)                                                                                                                                                                 |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `heading`                    | Saved conversations                                                                                                                                                                                              | المحادثات المحفوظة                                                                                                                                                                             |
| `source`                     | Counted from conversations readers have saved. When a reader deletes a conversation, or an account is deleted, its questions leave these figures — so a number here can go down.                                 | تعتمد هذه الأرقام على المحادثات المحفوظة. وعند حذف محادثة أو حساب، لا تعود الأسئلة المرتبطة به ضمن هذه الأرقام؛ لذلك قد تنخفض الأرقام بمرور الوقت.                                             |
| `privacy`                    | These lists show saved question text without account identifiers.                                                                                                                                                | تعرض هذه القوائم نصوص الأسئلة المحفوظة دون معرّفات الحسابات.                                                                                                                                   |
| `filtersLabel`               | Filter the figures below                                                                                                                                                                                         | تصفية النتائج أدناه                                                                                                                                                                            |
| `window`                     | Period                                                                                                                                                                                                           | الفترة                                                                                                                                                                                         |
| `windowDays7`                | Last 7 days                                                                                                                                                                                                      | آخر 7 أيام                                                                                                                                                                                     |
| `windowDays30`               | Last 30 days                                                                                                                                                                                                     | آخر 30 يوماً                                                                                                                                                                                   |
| `windowDays90`               | Last 90 days                                                                                                                                                                                                     | آخر 90 يوماً                                                                                                                                                                                   |
| `language`                   | Question language                                                                                                                                                                                                | لغة السؤال                                                                                                                                                                                     |
| `languageAll`                | Both languages                                                                                                                                                                                                   | اللغتان                                                                                                                                                                                        |
| `languageEn`                 | English                                                                                                                                                                                                          | الإنجليزية                                                                                                                                                                                     |
| `languageAr`                 | Arabic                                                                                                                                                                                                           | العربية                                                                                                                                                                                        |
| `refresh`                    | Refresh                                                                                                                                                                                                          | تحديث                                                                                                                                                                                          |
| `countedAt`                  | Counted at {time}                                                                                                                                                                                                | آخر تحديث للأرقام: {time}                                                                                                                                                                      |
| `loading`                    | Counting saved conversations…                                                                                                                                                                                    | جارٍ تحميل بيانات المحادثات المحفوظة…                                                                                                                                                          |
| `updated`                    | Figures updated.                                                                                                                                                                                                 | تم تحديث البيانات.                                                                                                                                                                             |
| `quality.heading`            | Citation quality                                                                                                                                                                                                 | جودة الاستشهادات                                                                                                                                                                               |
| `quality.turns`              | Saved answers                                                                                                                                                                                                    | الإجابات المحفوظة                                                                                                                                                                              |
| `quality.uncited`            | Found passages, cited none                                                                                                                                                                                       | عُثر على مقاطع دون الاستشهاد بأيٍّ منها                                                                                                                                                        |
| `quality.noRetrieval`        | Search found nothing                                                                                                                                                                                             | لم يعثر البحث على نتائج                                                                                                                                                                        |
| `quality.citedPerAnswer`     | Passages cited per answer                                                                                                                                                                                        | متوسط المقاطع المستشهد بها لكل إجابة                                                                                                                                                           |
| `quality.retrievedPerAnswer` | Passages retrieved per answer                                                                                                                                                                                    | متوسط المقاطع التي عثر عليها البحث لكل إجابة                                                                                                                                                   |
| `quality.group`              | Group                                                                                                                                                                                                            | المجموعة                                                                                                                                                                                       |
| `quality.byLanguage`         | By question language                                                                                                                                                                                             | حسب لغة السؤال                                                                                                                                                                                 |
| `quality.byScope`            | By search scope                                                                                                                                                                                                  | حسب نطاق البحث                                                                                                                                                                                 |
| `quality.scopeHint`          | Search scope is the guideline category the search ran in — set by the reader, or by the sidebar question they clicked. It is not a classification of what the question was about.                                | يشير نطاق البحث إلى فئة الإرشادات التي تم البحث ضمنها، سواء اختارها القارئ أو حددها السؤال المختار من القائمة الجانبية. ولا يعني ذلك أنها تصنيف لموضوع السؤال نفسه.                            |
| `quality.empty`              | No saved answers in this period.                                                                                                                                                                                 | لا توجد إجابات محفوظة خلال هذه الفترة.                                                                                                                                                         |
| `quality.smallSample`        | Percentages appear once there are 10 saved answers. Below that, a single answer moves the figure too far for it to mean anything.                                                                                | تظهر النسب المئوية عند توفر 10 إجابات محفوظة على الأقل. وعند انخفاض العدد عن ذلك، قد تؤثر إجابة واحدة بشكل كبير في النسبة، مما يجعلها أقل دلالة.                                               |
| `scope.all`                  | All categories                                                                                                                                                                                                   | جميع فئات الإرشادات                                                                                                                                                                            |
| `scope.regulatory`           | Regulatory                                                                                                                                                                                                       | copy from `page.categories` in `ar.yaml`                                                                                                                                                       |
| `scope.pharmacovigilance`    | Pharmacovigilance                                                                                                                                                                                                | copy from `page.categories` in `ar.yaml`                                                                                                                                                       |
| `scope.veterinary`           | Veterinary Medicines                                                                                                                                                                                             | copy from `page.categories` in `ar.yaml`                                                                                                                                                       |
| `scope.biological`           | Biological Products                                                                                                                                                                                              | copy from `page.categories` in `ar.yaml`                                                                                                                                                       |
| `questions.heading`          | Recurring questions                                                                                                                                                                                              | الأسئلة المتكررة                                                                                                                                                                               |
| `questions.grouping`         | Grouped by wording, ignoring capitals and spacing. Two phrasings of one question are counted separately.                                                                                                         | تُجمع الأسئلة بحسب صياغتها، مع تجاهل اختلاف حالة الأحرف والمسافات. وتُحسب الصياغات المختلفة للسؤال نفسه بشكل منفصل.                                                                            |
| `questions.question`         | Question                                                                                                                                                                                                         | السؤال                                                                                                                                                                                         |
| `questions.asks`             | Times asked                                                                                                                                                                                                      | عدد مرات الطرح                                                                                                                                                                                 |
| `questions.askers`           | Accounts                                                                                                                                                                                                         | عدد الحسابات                                                                                                                                                                                   |
| `questions.fromFaq`          | Sidebar question                                                                                                                                                                                                 | من أسئلة القائمة الجانبية                                                                                                                                                                      |
| `questions.uncited`          | Without a citation                                                                                                                                                                                               | دون استشهاد                                                                                                                                                                                    |
| `questions.floorEmpty`       | No question was asked by two or more accounts in this period.                                                                                                                                                    | لا توجد خلال هذه الفترة أسئلة طرحها حسابان مختلفان أو أكثر.                                                                                                                                    |
| `questions.floorWhy`         | A question is listed only once at least two different accounts have asked it, so that no entry can point to a single reader. With few accounts this list is often empty — that is the rule working, not a fault. | لا يظهر السؤال في هذه القائمة إلا إذا طرحه حسابان مختلفان على الأقل، وذلك لتجنب ربط أي سؤال بقارئ بعينه. لذلك قد تكون القائمة فارغة عندما يكون عدد الحسابات قليلاً، وهذا أمر متوقع وليس خللاً. |
| `uncitedQuestions.heading`   | Recurring questions answered without a citation                                                                                                                                                                  | أسئلة متكررة تمت الإجابة عنها دون استشهاد                                                                                                                                                      |
| `uncitedQuestions.empty`     | Every recurring question in this period was answered with at least one citation.                                                                                                                                 | جميع الأسئلة المتكررة خلال هذه الفترة تتضمن إجاباتها استشهاداً واحداً على الأقل.                                                                                                               |

Put a catalogue comment beside `floorEmpty` naming the migration that holds the constant "two",
and one beside `smallSample` naming `MIN_RATE_DENOMINATOR`.
