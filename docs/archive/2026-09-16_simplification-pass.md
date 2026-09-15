---
authority: historical
status: superseded
do_not_implement: true
archived: 2026-09-16
supersedes_note: >
  A finished plan. Every step, 0.1 to 3.4, was built on 2026-09-16 and passed the fast
  suite, the browser suite, ruff, mypy, eslint and prettier. Its own "Build record" lists
  where the build departed from the step text; those departures win.
live_authority:
  - docs/ARCHITECTURE.md
  - web/services/admin_store.py
  - web/services/notification_store.py
  - web/services/chat_store.py
  - web/api/app.py
  - static/js/modules/ui.js
---

> [!CAUTION]
> **You are reading history, not a specification.** Do not implement anything found
> in this file without first confirming it against `docs/ARCHITECTURE.md` or the code.
> Every heading below is prefixed `[HISTORICAL]` so a search result cannot be mistaken
> for current design.
>
> **Final position, so no reading order is required.** All of it shipped. Where a step's
> text and the _Build record_ near the end disagree, the Build record is what was built:
> the build was committed as one change, not one commit per step, with a single
> `ASSET_VERSION` bump. The chat error test was renamed
> `test_chat_store_raises_persistence_unavailable_with_described_error`.
> `hideBootstrapModal` null-checks its two arguments independently. The "reset, not close"
> comment also stayed at `handleNewChat` and `clearReaderLocalState`. The storage-write log
> label also became `rememberNotice`. Every `file:line` here describes `07d0fc9`, before
> the build.
>
> **What it reversed.** Four claims from the scouts that proposed it, each corrected
> against the code before any step was written:
>
> - a proposed admin RPC wrapper that already existed as `_quota_rpc`;
> - a fourth uuid guard, `get_user`, that returns `None` and so has a different contract;
> - a `require_owner` flag no caller needed;
> - "seven identical clear-view sites", which were five.
>
> Within review it also reversed two of its own drafts:
>
> - a `Promise.allSettled` account open that would have delayed the failure view, replaced
>   by awaiting the user request first;
> - plain `xfail(strict=True)`, which passes on any failure, replaced by
>   `raises=AssertionError`.
>
> **Rejected, and should stay rejected:** that parallel account requests break
> `test_opening_an_account_fetches_it_once`. The success path already fetched all three.
>
> **Open work was lifted out, not left here.** The `ResultCombiner` batching and the
> `CATEGORY_MAP` deletion are `TODO.md` entries.

# [HISTORICAL] Simplification Pass: Admin Store, Chat Persistence, Chat Frontend

Three features with high impact and low-to-medium risk, picked from a whole-app scan and
ranked by payoff against effort. The work is quality only: less duplication and fewer
places where two copies can drift apart. Where a step does change behaviour, the step says
so under **Behaviour change**; any other change is a bug in the refactor.

**How the scope was found.** Four Sonnet scouts each read one feature area (chat backend,
admin console, chat frontend, auth/retrieval). Their reports were then checked by hand
against the source. That check corrected the scouts in five places:

1. **The admin RPC wrapper already exists.** `SupabaseAdminBackend._quota_rpc`
   (`web/services/admin_store.py:532-536`) is the try/`_refusal_from` helper the scout
   proposed adding. This plan reuses it.
2. **Only three inline uuid guards match `_require_uuid`, not four.** The fourth,
   `get_user` (`admin_store.py:489-492`), returns `None` rather than refusing. It has a
   different contract and stays as it is.
3. **The shared precondition needs no `require_owner` flag.** Both account callers
   (`web/api/account.py:196`, `:247`) already treat "no owner" and "no backend" the same
   way.
4. **The notice builders share less than claimed.** Only the scaffolding is shared, so the
   estimate drops from ~50 lines to ~35.
5. **Only five of the seven "clear the conversation view" sites are identical.**
   `handleNewChat` and `clearReaderLocalState` stay explicit.

---

## [HISTORICAL] Ground rules for every step

- **One step, one commit.** The fast suite is green before and after each one.
- **Run tools from `.venv`, not `venv`:**

  ```bash
  .venv/Scripts/python.exe -m pytest -m "not browser and not integration"
  .venv/Scripts/python.exe -m pytest -m browser --browser chromium   # any JS step
  .venv/Scripts/python.exe -m ruff check . --fix && .venv/Scripts/python.exe -m ruff format .
  .venv/Scripts/python.exe -m mypy web
  npm run lint:fix && npm run format
  ```

- **Bump `ASSET_VERSION` in `web/api/app.py`** in every commit that touches `static/js/`.
- **Python 3.10 floor.** No `datetime.UTC`, no 3.11+ syntax.
- **Fix a document in the same commit that makes it wrong.** Each step lists the
  documents it affects.
- **Do not trust a delegate's self-report.** If a step is handed to `/agy-delegate` or
  another implementer, read the diff before committing.
- **Comments move with the code they explain.** When two copies merge, keep every distinct
  rationale, not just one of them. Several steps below name the comments that must survive.

---

## [HISTORICAL] Phase 0: Safety net (before touching anything)

Some tests already call the Supabase backends directly: `test_postgrest_errors.py:179-199`
drives `SupabaseChatBackend`, and `test_notification_fanout_pagination.py` drives
`SupabaseNotificationBackend` through its table queries. **None of them pins the RPC names
or argument dicts of the write methods** these refactors reshape, and every route-level
admin, notification and chat test runs against the `InMemory*Backend` doubles.

That gap matters because of how PostgREST resolves functions. An RPC is a POST to
`/rpc/<fn>` whose JSON keys are the function's argument names, and PostgREST picks the
overload by those names (PostgREST v14 docs). A missing or extra key is
`PGRST202 function not found`, which a double that accepts any dict never sees. A value
under the wrong key resolves fine and writes the wrong data. Pin names, keys **and**
values first.

Phase 0 is several commits (one per sub-step), all landing before Phase 1.

### [HISTORICAL] 0.1 Pin every admin and notification RPC payload

**New file:** `web/tests/test_rpc_payloads.py`.

**The stub.** A recording client whose `rpc(name, args)` stores `(name, dict(args))` and
returns an object whose `.execute()` yields `data=None` by default, overridable per case.
`None` passes cleanly through both the `or {}` and `or []` unwraps; `{}` would break any
list-returning caller that iterates it.

**Coverage.** For each write method, assert the RPC name and **full dict equality**
against an expected dict. Build that dict from distinct sentinel values, one per input and
one per actor field (e.g. `actor.user_id="actor-id"`, `actor.email="actor@x"`), so a value
under the wrong key fails the test:

- `SupabaseAdminBackend`: `put_settings`, `update_profile`, `set_user_flags`,
  `create_tier`, `update_tier`, `delete_tier`, `set_reader_quota`
- `SupabaseNotificationBackend`: `create`, `deactivate`, `delete`, `purge`, `mark_read`,
  `mark_all_read` (`web/services/notification_store.py:262-418`)

**Derived fields.** Compute them in the expected dict through the same helpers, never as
literals:

- `create`'s `p_request_payload_hash` comes from `_payload_hash` (`notification_store.py:283-295`).
- `append_turn`'s `p_title` and `p_archive_opted_out` (0.2) come from `clamp_title` and the
  opt-out expression (`chat_store.py:424`, `:439-441`).

Pinning a hash literal would pin hashing internals rather than the payload.

**Deliberate absence.** The tier and quota expected dicts carry no `p_actor_email`.
`admin_store.py:551-553` explains why: the SQL resolves the email from the validated id,
so a caller-supplied address can never reach the audit trail.

**Prove it is not vacuous.** Temporarily add `"p_actor_email": actor.email` to
`create_tier` and swap two actor values in `update_profile`. Both must fail. Revert.

### [HISTORICAL] 0.2 Pin every chat RPC payload and its error wrapping

**Payloads.** In the same file with the same stub, cover `SupabaseChatBackend`'s seven
methods (`chat_store.py:401-543`) for name and full dict. Parametrize over per-method
invocation callables. `append_turn` takes 14 keyword arguments while the others take one to
three, so each callable supplies valid arguments.

**Error wrapping.** Extend
`test_postgrest_errors.py::test_chat_store_list_sessions_raises_persistence_unavailable_with_described_error`
(`:179`) into a test parametrized over the same seven callables.

- **What each case asserts:** the stub raises the same placeholder `APIError`, and each
  case asserts the recovered description is present and the placeholder headline absent.
- **Marking:** mark the six methods that wrap `str(exception)` today as
  `xfail(raises=AssertionError, strict=True)`. The `raises=` part matters. Plain
  `strict=True` counts **any** failure as the expected one, so a `TypeError` from a bad
  argument list would pass as "expected". With `raises=`, any other exception is a real
  failure (pytest docs). The payload tests above prove each callable reaches its RPC.
- **Failing-first proof:** step 2.1 removes the marks.

### [HISTORICAL] 0.3 Pin the admin panels' load-failure message

No test covers the five `show*Message` panels. Add one browser test parametrized over
them. Each case routes the panel's load request to **500** and asserts one `.admin-empty`
paragraph with the translated `*.loadFailed` text inside that panel's container, and no
rendered list or table.

Use 500, not 503. `request()` retries a GET once on 503 (`static/js/admin/services.js:86-88`),
and it throws on any non-OK status (`:98-105`). Every path is prefixed `/admin/api/` (`:51`):

| Panel                | Request to fail               | `services.js` |
| -------------------- | ----------------------------- | ------------- |
| Notification history | `GET notifications/history?…` | `:194`        |
| Audit                | `GET audit?…`                 | `:172`        |
| People               | `GET users?…`                 | `:136`        |
| Registrations        | `GET registrations`           | `:128`        |
| Settings             | `GET settings`                | `:114`        |

### [HISTORICAL] 0.4 Pin the eight source passthrough fields

No test asserts them. `test_chat_persistence.py:878-911` checks only the `index` remap and
cited filtering. Add a unit test that gives each of `document`, `page`, `category`, `score`,
`semantic_score`, `lexical_score`, `chunk_id` and `snippet` a unique value. It runs
`_persistable_sources` then `_hydration_sources` (`web/api/app.py:1256`, `:1328`) and asserts
every value survives, with `source_index`/`index` and `cited` correct.

### [HISTORICAL] 0.5 Pin the export schema

In `test_chat_store_export.py`, assert **exact key-set equality**, not a subset:

- **Session:** `{session_id, title, created_at, updated_at, message_count, messages}`
- **Message:** `{message_id, seq, role, content, created_at, corpus_revision, model, lang,
category, sources}`

The export is a data-rights file whose header declares `export_version: 1`
(`web/api/account.py:191`). This test turns any future change to its shape into a loud,
deliberate decision (add the field and bump the version, or exclude it), whatever step 2.3
does.

### [HISTORICAL] 0.6 Pin the persistence-misconfigured branch on all five routes

Only the hydrate route tests "persistence on, no backend"
(`test_chat_persistence.py:1033-1047`). The sidebar test cited earlier only mocks the
browser response (`test_chat_sidebar.py:193-200`).

Add Flask tests with `app.config["chat_backend"] = lambda: None` and
`CHAT_PERSISTENCE_ENABLED=True`. Each asserts the **exact** 503 JSON for its surface:

- **The three session routes** that call `_sidebar_preconditions` (`app.py:3152`, `:3233`,
  `:3291`): `{"error": "Your conversations could not be loaded.", "code": "history_unavailable"}`.
  Use `caplog` to assert today's `logger.error`.
- **The account export and bulk-delete routes** (`account.py:182`, `:243`):
  `{"error": "Your data could not be reached.", "code": "history_unavailable"}`.

### [HISTORICAL] 0.7 Pin the account view's unparsable-200 path

`request()` returns `null` for a 2xx whose body will not parse (`services.js:90-96`).
Today `openAccount` destructures that `null`, throws, and shows the failure view
(`static/js/admin/handlers.js:940`, `:961-963`). Add a browser test beside
`test_admin_browser.py::test_a_failed_account_load_says_so_instead_of_showing_nothing`
(`:1004`). It fulfils `**/admin/api/users/*` with status 200 and a non-JSON body, and asserts
`#account-error` is visible.

---

## [HISTORICAL] Phase 1: Admin console backend calls

**Estimate:** ~100 production lines removed. Measure it; don't repeat this number.

### [HISTORICAL] 1.1 `AuditActor.as_rpc_args(*, with_email: bool)`

**Where:** `web/services/audit.py:32-43`.

**What it replaces:** the actor keys (`p_actor_id`, `p_actor_email`, `p_request_ip`,
`p_user_agent`) typed out by hand at 11 call sites:

- `admin_store.py`: `put_settings`, `update_profile`, `set_user_flags` **with** email;
  `create_tier`, `update_tier`, `delete_tier`, `set_reader_quota` **without**
- `notification_store.py`: `create`, `deactivate`, `delete`, `purge`, all with email

`with_email` is a **required** keyword with no default, so each call site states the
security decision explicitly. Each site becomes `{..., **actor.as_rpc_args(with_email=...)}`.
`mark_read` and `mark_all_read` carry no actor and are untouched.

**Guarded by:** 0.1.

### [HISTORICAL] 1.2 One refusal-converting RPC call per backend

`_rpc(name, args)` wraps only `self._client.rpc(name, args).execute()` and the
`except` → `raise _refusal_from(exception) from exception`. It **returns the raw response**.
Every caller keeps its own unwrap line: `or {}` for writers, `or []` for `list_tiers`.

**Admin backend:**

- Rename `SupabaseAdminBackend._quota_rpc` (`admin_store.py:532`) to `_rpc`.
- Update its five existing callers: `list_tiers` (`:539`), `create_tier` (`:543`),
  `update_tier` (`:564`), `delete_tier` (`:580`), `set_reader_quota` (`:598`).
- Route three more writers through it: `put_settings` (`:354-377`), `update_profile`
  (`:431-449`), `set_user_flags` (`:510-526`).
- Condense `put_settings`'s long `except` comment (`:368-376`) into a sentence on `_rpc`.
  Its point (every writer must convert refusals, or a demoted administrator gets a raw
  PostgREST error) is now structural.

**Notification backend:**

- Add `_rpc` to `SupabaseNotificationBackend`, using **its own** `_refusal_from`
  (`notification_store.py:75`). Do not import admin's; the two map different SQLSTATEs.
- Route `create` (`:296-322`) and `mark_read` (`:404-413`) through it. `create` keeps its
  `target_kind == "user"` uuid guard and its `_payload_hash` computation at the call site.
- `deactivate`, `delete` and `purge` (`:324-373`) become one-line calls to a private
  `_lifecycle(rpc_name, notification_id, actor)`. It **performs
  `_require_uuid(notification_id, "no_such_notification")` itself** before calling `_rpc`.
  Dropping that guard would turn an invalid id's 404 into a cast error.
- `mark_all_read` (`:415-418`) has no `try` today and gets none; it has no refusal to
  convert.

**Guarded by:** 0.1, `test_admin_refusal_routes.py`, `test_admin_notifications.py`.

### [HISTORICAL] 1.3 One `_require_uuid`

- Move `_require_uuid` from `notification_store.py:118-128` to `admin_store.py`, beside
  `AdminActionRefused`, and add it to the existing import at `notification_store.py:34`.
- Replace three inline refusal guards: `update_profile` (`admin_store.py:426-429`),
  `set_user_flags` (`:505-508`) and `set_reader_quota` (`:594-597`).
- Leave `get_user` (`:489-492`) alone; see correction 2.
- Rewrite `_require_uuid`'s docstring. It says "same reasoning as
  `set_user_flags`/`update_profile`", which is circular once those call it.

**Guarded by:** `test_admin_users.py`, `test_admin_refusal_routes.py`.

### [HISTORICAL] 1.4 One panel-message renderer in `static/js/admin/ui.js`

**What it replaces:** `showRegistrationsMessage` (`:191`), `showPeopleMessage` (`:884`),
`showAuditMessage` (`:1040`), `showSettingsMessage` (`:1050`) and
`showNotificationHistoryMessage` (`:2853`), which are identical apart from the container
id.

**The change:**

- Replace them with `showPanelMessage(containerId, message)`.
- Update the five callers in `static/js/admin/handlers.js` (`:324`, `:792`, `:897`,
  `:1281`, `:1613`) and the import list (`:30-48`).
- Leave `showGateMessage` and `showAccountMessage` alone. They have different shapes.
- Drop `showPeopleMessage`'s leading `setPeopleLoading(false)`. The `catch` reaches the
  message only when `seq === requestSequence` (`handlers.js:896`), and the `finally` then
  makes the same call synchronously (`:900-902`) before the browser paints.

**Documents:** `docs/registrations-pause-plan.md:120-124` names the old functions. It is a
BUILT design record, so add a one-line dated note that this step merged them, rather than
rewriting the history.

**Guarded by:** 0.3, `test_frontend_architecture.py`. **Bump `ASSET_VERSION`.**

### [HISTORICAL] 1.5 Start an account's three requests together

**Where:** `static/js/admin/handlers.js:930-971` (`openAccount`).

**The change:** its three requests (`services.user`, `services.audit`, `services.tiers`) run
one after another today. Start them together, but **await the user request first**, so a
failed open still shows its message immediately rather than waiting on the other two:

```js
// Started before the user request is awaited; each carries its own fallback,
// so neither can reject, and neither is left unhandled on an early return.
const entriesPending = services
  .audit({ targetType: 'user', targetId: userId })
  .then((payload) => payload.entries)
  .catch(() => null);
const tiersPending = services
  .tiers()
  .then((payload) => payload.tiers || [])
  .catch(() => []);
const { user, self_id: selfId } = await services.user(userId); // throws → outer catch, as today
const [entries, tiers] = await Promise.all([entriesPending, tiersPending]);
```

Each part of this is deliberate:

- **`.then(...).catch(...)` preserves every current case.** A rejected request, a
  fulfilled `null` payload (whose `.entries`/`.tiers` read throws inside `.then`) and a
  missing field all resolve exactly as the sequential `try`/`catch` blocks do now
  (`:943-958`).
- **Unhandled rejections can't happen.** The `.catch` is attached at creation, so an early
  return on a failed user request cannot orphan a rejection.
- **The user request keeps the outer `try`.** A rejection or a fulfilled `null` still throws
  into `showAccountMessage(loadFailed)` (`:961-963`); 0.7 pins the `null` case.
- **Both guards stay unchanged:** `mine !== generation` before rendering, and the `opening`
  release in `finally`.
- **Keep both existing comments** ("allowed to fail on its own") on the two pending
  promises.

This replaces the earlier `Promise.allSettled` sketch, which would have delayed the failure
view until audit and tiers settled.

**Behaviour change:** when the user request fails, the audit and tiers requests have
already been sent. Two wasted reads on an error path are accepted in exchange for two fewer
round trips on every successful open. The failure message is not delayed.

**Guarded by:** 0.7 and `test_admin_browser.py`:

- `test_opening_an_account_fetches_it_once`, which intercepts only the user route; the
  success path already fetched audit and tiers, so its count is unchanged
- `test_a_double_click_does_not_open_an_account_twice`
- `test_an_account_can_be_reopened_after_going_back`
- `test_a_failed_open_does_not_lock_the_account_shut`
- `test_a_failed_account_load_says_so_instead_of_showing_nothing`
- `test_a_pending_search_does_not_replace_an_open_account`

**Bump `ASSET_VERSION`.**

---

## [HISTORICAL] Phase 2: Saving and exporting chat history

**Estimate:** ~70 production lines removed. Measure it.

### [HISTORICAL] 2.1 `SupabaseChatBackend._rpc(name, params)`

**Where:** `web/services/chat_store.py:401-543`.

**The change:** all seven methods repeat the same `try`/`except`/`raise
PersistenceUnavailable`. Six wrap `str(exception)`; only `list_sessions` (`:501`) uses
`describe_api_error`, which bounds and sanitizes the text and recovers a message PostgREST
hid behind a placeholder.

- Add `_rpc`, which wraps **only** `rpc(name, params).execute()` and the `except` →
  `PersistenceUnavailable(describe_api_error(exception))`.
- Leave all per-method parameter computation where it is: `clamp_title`, the archive
  opt-out expression, `clamp_load_limit`, and the cursor split.
- Remove 0.2's `xfail` marks.

**Behaviour change:** the exception text for six methods becomes the sanitized, bounded
form. It reaches logs only: no route in `web/api/` binds a `PersistenceUnavailable` to
read its message.

### [HISTORICAL] 2.2 One list of source passthrough fields

**Where:** `web/api/app.py:1256-1287` (`_persistable_sources`) and `:1328-1356`
(`_hydration_sources`).

**The change:** both functions spell out the same eight passthrough fields. Hoist them into
one `_SOURCE_PASSTHROUGH_FIELDS` tuple placed right before `_persistable_sources`. Each
function keeps its two asymmetric keys (`source_index`/`index`, `cited`) explicit.

Update `_hydration_sources`' "change them together" paragraph (`:1337-1340`). The shared
tuple now enforces what the paragraph asked for, so say that instead.

**Guarded by:** 0.4, `test_chat_persistence.py::test_a_stored_source_index_reaches_the_browser_as_index`
and `::test_only_the_cited_passages_reach_the_transcript`.

### [HISTORICAL] 2.3 `dataclasses.asdict` in the export

**Where:** `chat_store.py:627-633` (the session dict) and `:668-679` (the message dict).

**The change:** both dicts copy `SessionSummary` and `StoredMessage` field by field. Their
key order matches the dataclass field order (`chat_store.py:104-108`, `:126-138`), and
`asdict` emits keys in field order, so the output is identical. The session becomes
`{**asdict(summary), "messages": [...]}`. Add `asdict` to the `dataclasses` import at
`:35`.

`asdict` recurses into dicts and lists and deep-copies other values (Python 3.10 docs), so
each message's `sources` is copied. For plain JSON-derived dicts that `account.py:199-200`
serializes immediately, that is behaviour-neutral. The allocation is transient and small
next to the RPC round trip each batch already pays.

**Dissent, recorded.** Antigravity argued to cut this step: `StoredMessage` is an internal
storage model while the export is a public, versioned contract, and ~18 lines don't justify
coupling them. The majority kept the step because 0.5 makes the contract explicit anyway.
Any new dataclass field fails that exact-key test before it can reach an export. **If a
field is ever added to `StoredMessage` or `SessionSummary` that must not be exported,
revert this step to an explicit mapping instead of excluding keys after `asdict`.**

**Guarded by:** 0.5, `test_chat_store_export.py`.

### [HISTORICAL] 2.4 One persistence precondition

**Where:** `_sidebar_preconditions`, a closure inside `_register_routes`
(`web/api/app.py:3086-3121`).

**The change:** hoist it to module level beside `_durable_owner` (`app.py:936`), as
`_persistence_preconditions(error_message: str)`. It closes over nothing; everything it
uses (`_durable_owner`, `_chat_persistence`, `current_app`, `logger`, `jsonify`) is already
module-level.

- **Sidebar routes:** the three at `:3152`, `:3233` and `:3291` pass
  `"Your conversations could not be loaded."`.
- **Account routes:** `account.py` deletes `_persistence_precondition` (`:127-152`). Its two
  call sites (`:182`, `:243`) import the shared helper inside the function, the same
  cycle-avoidance `:138` already uses, and pass `"Your data could not be reached."`.
- **Imports:** remove `ChatBackend` from `account.py:43`. Its only use is that function's
  annotation (`:128`), and `ruff` fails on the unused import (F401).
- **Log message:** make the `logger.error` at `app.py:3104-3107` surface-neutral
  ("Chat persistence is enabled but no backend is configured."). Today it says "the
  conversation list cannot be served", which is wrong once account export and bulk delete
  call it too.
- **Docstring:** fix the account docstring's stale claim that the helper cannot be imported
  because it is a closure.

**Behaviour change:** the two account routes now emit that `logger.error` on a
misconfigured deployment, as the sidebar already does. Extend 0.6's two account cases with
a `caplog` assertion in this commit. That assertion fails before the change, which proves
the step. No wire response changes, and 0.6 pins each surface's message.

**Guarded by:** 0.6, `test_account_data_rights.py`, `test_chat_sessions.py`.

---

## [HISTORICAL] Phase 3: Chat screen in the browser

**Estimate:** ~70 lines removed. That is down from the ~90-100 first reported; see
corrections 4 and 5. Measure it. Run the browser suite after every step, and **bump
`ASSET_VERSION`** in each commit.

### [HISTORICAL] 3.1 One chat-failure builder in `static/js/modules/services.js`

**Where:** `sendChatRequest` (`:214-234`) and `streamChatRequest` (`:287-304`).

**The change:** both repeat the same block that builds an error carrying `status`, `code`
and the 429 `quota` object. Replace it with a module-private
`async function chatFailure(response)` that returns the `Error`, with
`throw await chatFailure(response)` at both sites. The module stays transport-only and
imports nothing new.

**Comments:** the two copies carry different comments, and all three rationales survive:

- "Status and code ride along…" (`:216-218`) moves onto `chatFailure`.
- The 429 "Transport only — this module still imports no view and no state" note
  (`:222-224`, duplicated at `:292-294`) moves onto `chatFailure` once.
- "Failures before the first frame still carry a real status code…" (`:285-286`) **stays at
  the stream call site**, because it explains why the stream checks `response.ok` before
  reading frames.

**Guarded by:** `test_quota_notice.py`, `test_quota_routes.py`,
`test_frontend_architecture.py`.

### [HISTORICAL] 3.2 One Bootstrap modal-hide workaround

**Where:** `BroadcastNotice.showModal`'s `requestHide` (`static/js/modules/dom.js:518-525`)
and `Handlers.hideModal` (`static/js/modules/handlers.js:2340-2355`).

**The change:** both implement "hide, and retry after 350ms if a fade-in swallowed it". The
retry is genuinely required. Bootstrap 5.3 (the repo loads 5.3.0) documents that modal
methods "return control to the caller immediately after the transition starts" and that
"method calls made while a component is already transitioning are ignored".

- Export `hideBootstrapModal(el, modal)` from `dom.js` and call it from both sites.
  `handlers.js:7` already imports from `./dom.js`.
- The helper **no-ops on a null `el` or `modal`**, because `hideModal` uses `modal?.hide()`.
- It does **not** create an instance. `getOrCreateInstance` / `AppState.get(stateKey)`
  resolution stays at each call site.
- **Comments:** keep both contexts on the helper, in two sentences. `dom.js:513-517` is
  about an urgent notice's "Got it" click being swallowed; `handlers.js:2347-2348` is about
  fast mocked auth resolving inside the fade.

**Guarded by:** `test_logout_single_post.py`, `test_notifications_browser.py`,
`test_signed_out_route.py`.

### [HISTORICAL] 3.3 `_clearConversationView()` in `static/js/modules/handlers.js`

**Where:** five sites that repeat `UI.clearTranscript(); SourcePanel.reset();
resetCitationState();` in that order:

- `openSession` (`:783-785`)
- `_conversationUnreachable` (`:839-841`)
- `handlePopState`'s `/` branch (`:882-884`)
- `handlePopState`'s general branch (`:893-895`)
- `deleteSession`'s `wasCurrent` branch (`:1020-1022`)

**The change:** the three calls become one method called from all five sites. The
`UI.History.setActive(...)` calls stay at each site because their arguments differ. Leave
`handleNewChat` (`:601-602`) and `clearReaderLocalState` (`:2240-2241`) explicit; see
correction 5. Put the "reset, not close" warning, currently repeated at `:599-600` and
`:2238-2239`, on the new method.

**Guarded by:**

- `test_chat_sidebar.py::test_switching_clears_the_previous_conversations_evidence`
- `test_source_panel.py::test_logging_out_leaves_nothing_of_the_previous_reader`
- `test_new_chat.py`
- `test_chat_sidebar.py`

### [HISTORICAL] 3.4 Shared notice scaffolding in `static/js/modules/ui.js`

**Do this step last.** It is the most order-sensitive.

**The change:**

- `noticeSeen(key)` and `rememberNotice(key)` replace `historyNoticeSeen`,
  `rememberHistoryNotice`, `profileNoticeSeen` and `rememberProfileNotice`
  (`:131-146`, `:180-195`). Callers pass `historyNoticeKey(identity)` or
  `profileNoticeKey(identity)`.
- `buildNotice({ id, modifier, dismissLabel, onDismiss })` returns `{ notice, body }` and
  owns only the shared scaffolding: the `div.history-notice` plus modifier, `id`,
  `role="note"`, `data-non-turn`, the body div, and the dismiss button with its close icon
  and aria-label.
- **The dismiss handler runs `notice.remove()` first, then `onDismiss?.()`.** Order matters:
  the history notice's `onDismiss` calls `NoticeCoordinator.release`, which draws the queued
  profile strip. That strip positions itself by looking up `#history-notice` (`:941`), so
  the history node must already be gone. Today's handler already runs remember → remove →
  release (`:868-874`). Remembering after removal is equivalent, since it only writes
  `localStorage`.
- `showHistoryNotice`, `showProfileCompletionNotice` and `showQuotaNotice` (`:836-1008`)
  each keep their own content, their insertion logic, and their `onDismiss` side effects:
  remember plus `NoticeCoordinator.release` for history, remember for profile, nothing for
  quota. Quota also keeps its own `aria-live` and `followStream`.

**Behaviour change:** the `logError` context label for a storage failure changes from
`historyNoticeSeen` or `profileNoticeSeen` to `noticeSeen`.

**Hazard:** `ui.js` contains a NUL byte used as the split sentinel in `showQuotaNotice`'s
`resets_at` placeholder (`:992-993`). Plain `grep` calls the file binary because of it; use
`grep -a`. After editing, confirm with `git diff` that the byte is still there and that
`test_quota_notice.py` still renders the reset time.

**Guarded by:** `test_history_notice.py`, `test_profile_completion_notice.py`,
`test_quota_notice.py`. `data-non-turn` is load-bearing, because `isTranscriptTurn`
(`:246`) would otherwise count a notice as a turn.

---

## [HISTORICAL] Phase 4: Close-out

1. Run the full fast suite, the browser suite, `ruff`, `mypy web` and `npm run lint`.
2. Measure with `git diff --shortstat 07d0fc9..HEAD -- web/api web/services static/js`, and
   separately for `web/tests`. Record both numbers here.
3. Change this file's `STATUS:` line to BUILT with the final commit hash. Record anything a
   step skipped and why.
4. If nothing cites this file, follow the archive procedure in
   `docs/archive/README.md#adding-to-this-archive`.

### [HISTORICAL] Build record

Built on 2026-09-16. Every step 0.1 to 3.4 landed, and none was skipped.

**Measured, not estimated.** Figures are `git diff --shortstat 07d0fc9` against the
working tree:

| Scope                                               | Files | Lines added | Lines removed |
| --------------------------------------------------- | ----- | ----------- | ------------- |
| Production (`web/api`, `web/services`, `static/js`) | 12    | 478         | 634           |
| Tests (`web/tests`, tracked files)                  | 6     | 222         | 3             |
| New `web/tests/test_rpc_payloads.py`                | 1     | 352         | 0             |

Production net is 156 lines removed, against the ~240 the phase estimates summed to. The
gap is mostly re-indented RPC argument blocks and comments kept per the ground rule.

**Gates at the end:**

- Fast suite: 1077 passed, 1 skipped. Baseline was 1044.
- Browser suite: 336 passed.
- `ruff check`, `ruff format --check`, `mypy web`, `npm run lint` and `prettier --check`
  are all clean.

**Proofs run, not assumed:**

- **0.1 vacuity.** Adding `p_actor_email` to `create_tier` and swapping the actor values in
  `update_profile` failed exactly those two cases. Both were reverted.
- **0.2.** The six `xfail(raises=AssertionError, strict=True)` cases failed as expected
  before 2.1. They pass after it with the marks removed.
- **2.4.** The account routes' `caplog` assertion failed before the hoist and passes after
  it.
- **3.4.** `ui.js` still carries its two NUL bytes, the same count as `07d0fc9`.

**Departures from the text above:**

- **Commits.** There is no one-step-one-commit history. The user asked for the whole pass
  uncommitted, to review and commit themselves. For the same reason `ASSET_VERSION` was
  bumped once, not per step.
- **0.2 renamed the test.** It is now
  `test_postgrest_errors.py::test_chat_store_raises_persistence_unavailable_with_described_error`,
  parametrized over `CHAT_CALLS`, which is imported from `test_rpc_payloads.py` so that
  both tests drive the same seven invocations.
- **0.3 and 0.6 locations.** The panel test is
  `test_admin_browser.py::test_a_panel_that_fails_to_load_says_so_in_place`. The session
  routes' misconfiguration test is in `test_chat_sessions.py`, and the account routes'
  version is in `test_account_data_rights.py`.
- **1.2 placement.** Admin `_rpc` moved from the tiers section to just after `__init__`,
  since every writer now uses it. The tier section keeps the "no `p_actor_email`"
  rationale as a section comment.
- **3.2 null-safety.** `hideBootstrapModal` checks `el` and `modal` independently rather
  than returning early when either is missing. `hideModal` could hold an instance from
  `AppState` with no element in `DOMCache`, and an early return would have skipped its
  `hide()`.
- **3.3 comments.** The "reset, not close" warning is on `_clearConversationView`, and
  also stays at `handleNewChat` and `clearReaderLocalState`. Both of those still call
  `SourcePanel.reset()` directly.
- **3.4 log context.** The storage-write context label also changed, from
  `rememberHistoryNotice`/`rememberProfileNotice` to `rememberNotice`, alongside the read
  label the step names.

---

## [HISTORICAL] Deliberately out of scope

| Candidate                                                                                         | Why not here                                                                                                                                    |
| ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Merging the two chat routes' turn setup (`app.py` `handle_chat_stream`/`handle_chat`)             | `hold.__exit__` must be released on every early exit, and only comments guard it. About 10 lines saved for the highest-risk change in the scan. |
| Batching `ResultCombiner._compute_semantic_score` (`web/services/result_combiner.py:144`, `:221`) | A real hot-path win, but no test exercises `combine`. It needs its own characterization test first.                                             |
| Deleting `CATEGORY_MAP` (`web/services/search_engine.py:140`)                                     | Zero callers, 11 lines. Worth a separate one-line commit, not a place in this plan.                                                             |
| A shared store primitive for `IdentityFlagsCache`/`TokenVerificationCache`                        | Touches invalidation-ordering code with a documented adversarial-review history, for about 20 lines.                                            |
| Merging the two `_refusal_from` functions (`admin_store.py:97`, `notification_store.py:75`)       | Different SQLSTATE maps. They look alike but aren't.                                                                                            |
| Wrapping `mark_all_read` in `_rpc`                                                                | It has no `try` and no refusal to convert today; adding one would be a behaviour change.                                                        |

---

## [HISTORICAL] Review record

On 2026-09-15 a three-model panel reviewed this plan read-only, in two rounds:

- **OpenCode** (`opencode/muse-spark-1.3-contributor-free`, variant `max`)
- **Codex** (`gpt-5.6-terra`, effort `high`)
- **Antigravity** (`gemini-3.8-flash-high`). Its first two attempts failed with server 503
  "no capacity"; the third ran, and its report was recovered by resuming the conversation.

**Round 1** was independent critique. **Round 2** had each reviewer cross-examine the others'
findings and the author's position on each. Every finding was verified against the code by
the author before a position was taken. Library behaviour was checked against current
documentation via Context7: Bootstrap 5.3 modal methods, PostgREST v14 RPC argument
resolution, Python 3.10 `dataclasses.asdict`, and pytest `xfail(raises=…)`.

**What changed because of the review:**

| Finding                                                                                  | Raised by                      | Change                                                                        |
| ---------------------------------------------------------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------- |
| Key-set-only payload tests miss transposed values                                        | Antigravity                    | 0.1/0.2 assert full dicts with sentinels                                      |
| Full-dict equality breaks on derived fields                                              | OpenCode (round 2)             | Expected dicts compute hash/clamp through the real helpers                    |
| Stub `data={}` breaks list-returning callers                                             | Antigravity                    | Stub defaults to `data=None`                                                  |
| `mark_read`/`mark_all_read` unpinned; `create`/`mark_read` duplicate the refusal wrapper | Codex, Antigravity             | Added to 0.1; `create` and `mark_read` routed through `_rpc`                  |
| Five `_quota_rpc` callers would break on rename                                          | Antigravity                    | Named in 1.2                                                                  |
| `_rpc` return shape unspecified                                                          | OpenCode                       | Returns raw response; callers unwrap                                          |
| `_lifecycle` could drop the uuid guard                                                   | OpenCode                       | `_lifecycle` owns `_require_uuid`                                             |
| `xfail(strict=True)` passes on any failure                                               | OpenCode, then Codex (round 2) | `xfail(raises=AssertionError, strict=True)` plus valid per-method invocations |
| Panel test could intercept the wrong request; 503 is retried                             | OpenCode                       | Panel→request table; use 500                                                  |
| Eight source fields and the misconfigured-persistence branch untested                    | Codex                          | New 0.4 and 0.6, widened to all five routes with per-surface messages         |
| "No test touches the Supabase backends" was false                                        | Codex                          | Phase 0 rationale corrected                                                   |
| Fulfilled-`null` user payload not preserved                                              | Codex, Antigravity             | New 0.7; 1.5 keeps the user request in the outer `try`                        |
| `allSettled` delays the failure view                                                     | OpenCode (round 2)             | 1.5 awaits the user request first, with the others already in flight          |
| Merging comments would drop distinct rationales                                          | OpenCode                       | 3.1/3.2 name every comment that must survive                                  |
| Shared log line says "conversation list" on account routes                               | Antigravity                    | Surface-neutral log in 2.4                                                    |
| Unused `ChatBackend` import fails `ruff`                                                 | Antigravity (round 2)          | Named in 2.4                                                                  |
| Notice dismiss order affects the queued profile strip                                    | Antigravity (round 2)          | 3.4 fixes remove-then-`onDismiss`                                             |

**Where the author pushed back:**

- **The claim that parallel requests would break `test_opening_an_account_fetches_it_once`.**
  Rejected. The success path already fetches audit and tiers, so the pinned count is
  unchanged. All three reviewers conceded in round 2.
- **Cutting step 2.3 (`asdict`).** Kept, with the export schema pinned first (0.5). Codex,
  which proposed the cut, conceded in round 2; OpenCode agreed. Antigravity maintained the
  cut, and its dissent is recorded in 2.3.
