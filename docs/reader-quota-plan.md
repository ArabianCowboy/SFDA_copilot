STATUS: BUILT — Commits A–E applied 2026-09-03/04 and verified. Nine migrations live, the claim and refund wired into both chat routes, the reader notice and counter shipped, the Tiers tab and per-account override in the console, and the documents corrected. §§1–8 and §10 are the specification this was built from; the review sections are provenance. **§14 records two corrections made after the build, one of which reverses a line of §5.1.** Not committed to git at the time of writing.

# Reader Quota: tiers, per-account overrides, and a daily allowance that survives a deploy

**How to read this document if you are building it.** §§1–8 and §10 are the **specification** — build exactly what they say. The review sections (_Inputs & disagreement rulings_, _Adversarial review round_, _Second review round_, _Third review round_) are **provenance**: they record what was contested, what was found wrong and what was rejected, so that a decision you are tempted to change quietly can first be read as a decision somebody already made. If the spec and a review section disagree, the spec wins and the disagreement is a bug in this document — fix it here in the same commit.

**Source:** `TODO.md` → [Give readers a quota, and limits worth having](../TODO.md#give-readers-a-quota-and-limits-worth-having). That entry stays in `TODO.md` as the short version and points here; this document is the design.

**Supersession note (2026-09-03).** The TODO entry records that two independent reviews judged the full tier matrix premature for three accounts and one operator, and asked for "one number per reader per day". On 2026-09-03 the product owner ruled otherwise: the quota is operator-configurable at two levels — a daily allowance per tier (group of readers) and a per-account override — both managed from the admin console. That decision supersedes the deferral. What stays deferred, by the same ruling: **token credits** (the OpenAI stream ignores usage chunks, and a tokenizer estimate is not a billing ledger) and **time-windowed access**. A quota here means a daily _message_ allowance — questions per reader per day — and nothing else.

**Partial reversal of that same ruling, 2026-09-03 (later the same day).** The owner has taken back one half of "time-windowed access": a per-account override may now carry an optional **window** (`starts_at` / `expires_at`), so "500 a day for this reader until the end of the month" is a thing the console can express. This is a reversal, stated as one rather than reasoned around: the deferred item was time-windowed _access_, and a time-windowed _allowance_ is the same idea applied to a smaller lever. It costs two nullable columns and one clause because `reader_quota_overrides` has not shipped — the same "free today, a data migration tomorrow" argument as the `staff` rename (§1.1). What is **still** deferred, and was reconsidered on the same day: a **fixed promo pool** of N bonus messages drawn after the daily allowance. That design was worked out in full and is parked in §12 with its corrected schema, because it needs a second table, a second atomic path inside the claim, a bucket-tagged refund and a second counter — for a product question nobody can answer until the meter has run. Token credits remain deferred on their original technical grounds, which a message count does not share.

---

## Context

Rate limiting today is one global, IP-keyed setting: `web/config.yaml` `server.rate_limit` (200/day, 50/hour, 10/minute defaults; `chat_api: "15 per minute"`) applied by a Flask-Limiter built on `get_remote_address` with `storage_uri="memory://"` (`web/api/app.py`, `_init_extensions`). An office behind one NAT shares a budget; one person on two networks gets two; every counter dies on restart. `profiles.tier` exists (`text not null default 'free'`, `20260814005509`), rides `IdentityFlags`, and nothing branches on it. `public.chatbot_settings` sits in the database with zero rows and zero readers.

This plan makes four changes: the chat burst limit becomes reader-keyed; a durable daily allowance is claimed atomically in Postgres before any retrieval or model call; tiers and per-account overrides become real, operator-managed data with bilingual labels; and `chatbot_settings` is dropped. It went through the "debate the plan before building it" pattern: an orchestrator read of every file named below, two independent delegated drafts (research/adversary and designer, neither seeing the other), a documentation check of the two libraries the design leans on, and a read-only adversarial review of the synthesized plan. Every disagreement between the drafts is ruled on below with codebase evidence, not preference.

---

## Ground truth this plan was verified against

Read directly in the session that wrote this, 2026-09-03. Where a delegate contradicted one of these, the source was re-read and the delegate was wrong (see _What the delegates got wrong_).

- **Decorator order is load-bearing, and it was proven, not assumed.** Flask-Limiter 4.1.1 evaluates a _decorated_ limit inside the decorator's own wrapper (`LimitDecorator.__call__` → `__inner` → `_check_request_limit(in_middleware=False)`), and its `before_request` hook deliberately skips routes that carry a decorated limit. So with `@auth_required` outermost, `g.identity` exists when a key function runs; with the two lines reversed, the key function runs before authentication. Reproduced in a throwaway app on the installed version: readers A, B, A from one IP under "1 per minute" gave `200, 200, 429` in the shipped order and `200, 429, 429` reversed.
- **Five limits in `app.py` are currently not enforced at all.** `limiter.limit(...)(app.view_functions["admin.revoke_sessions"])` and its four siblings (`admin.change_email`, `admin.create_notification`, `account.export`, `account.delete_all_conversations`) discard the wrapper Flask-Limiter returns. In 4.1.1 that _marks_ the endpoint (so the middleware skips it — including its blueprint's blanket 60/minute) but no wrapper ever runs. Reproduced: a "1 per minute" route limit plus a "2 per minute" blueprint limit answered `200, 200, 200, 200` to four hits; reassigning `app.view_functions[name] = limiter.limit(...)(fn)` answered `200, 429, 429, 429`. This is a pre-existing bug, adjacent to this feature, and §3 fixes it.
- **A structural check cannot pin decorator order.** `functools.wraps` copies `__dict__`, so Flask-Limiter's `__wrapper-limiter-instance` marker propagates onto the outer `auth_required` wrapper; both wrappers carry it. Only a behavioural test can pin the order — and **not** by flipping `Limiter.enabled` on the retained instance, as this plan's first draft said: `init_app` returns before building storage or registering its `before_request` hook when the flag is off (`_extension.py:331-334`), so a later `enabled = True` enforces nothing and `reset()` asserts on a missing storage. The test app has to be _built_ with the limiter on (§3.7). `test_registrations_pause.py`'s comment is right in its conclusion and stale only in its "never retained" clause; §9 trims that clause rather than reversing it.
- **The limiter is disabled under pytest** (`RATELIMIT_ENABLED=not testing`). The daily allowance is therefore _not_ a Flask-Limiter limit: it is an explicit claim against a `QuotaBackend` with an in-memory double, so every quota path is exercised offline exactly as durable chat history already is ("UNDER TESTING PERSISTENCE IS ON", `app.py` `chat_backend()`).
- **The streaming lifecycle.** `handle_chat_stream` validates (`_validate_chat_request`, 400s), takes the `_InFlightGenerations` hold in the view body, refuses `allow_create=false` on an unknown conversation (404, before any frame), loads history, and only then builds `Response(stream_with_context(generate()))`. Nothing in `generate()` runs until the WSGI server iterates it; every failure after the first byte is an in-band `error` frame. `test_deep_link_contract.py` pins "no LLM call before the ownership check" with `handler.stream_response.call_count == 0`; the same assertion pins "no LLM call when the allowance is spent".
- **`stream_response` is a generator function, and that changes where "the model was called" is.** `OpenAIHandler.stream_response` (`web/services/openai_app.py:410`) contains `yield`, so `handler.stream_response(...)` returns a generator and runs none of its body. Both `_build_messages` and the `client.chat.completions.create(...)` context manager execute on the **first `next()`**, i.e. inside `app.py:3130`'s `for token in handler.stream_response(...)`. `handler.stream_response.call_count == 1` therefore proves the generator was constructed, not that the provider was reached — which is fine for the assertion above (it checks for zero) but is exactly the trap the refund boundary has to avoid (§3.2). The blocking route inherits the same shape: `generate_response` joins the same generator.
- **Identity.** `_authenticate_request` sets `g.identity: IdentityFlags(user_id, email, role, tier, is_disabled, is_resolved)`; the flags cache is process-local, 30 s TTL, fails open for access and closed for privilege. `admin.py`'s `_evict_identity_caches(user_id)` is the chokepoint after any identity-changing admin action. `GET /api/identity` returns `user_id, email, role, tier, is_admin, is_disabled, created_at, conversation_count`, with `touch_last_seen` and `get_identity_flags` each in their own `try`/`except`. `static/js/account/ui.js` `renderStanding` maps the tier to two hardcoded catalogue keys (`profile.account.tierInternal` / `tierFree`).
- **`profiles.tier` is already server-owned.** Column-level `REVOKE` plus `profiles_guard_privilege_columns` (latest body `20260828222859`) which refuses `new.tier <> 'free'` on browser INSERT and any tier change on browser UPDATE. `handle_new_user` relies on the column default; `admin_list_users` coalesces to `'free'`; `admin_set_user_flags` snapshots `tier` in its before/after JSON but takes no `p_tier`. The notification composer accepts `target_kind='tier'` with a free-text `target_tier`.
- **The admin RPC contract** (`supabase/README.md`): `security definer`, `set search_path = ''`, revoke from `anon`/`authenticated`/`public`, grant to `service_role` only, owner argument first and filtered inside; signature changes are drop + create; one concern per migration; destructive changes alone; every FK indexed and with a stated `ON DELETE`; RLS on every table and every zero-policy table listed in the standing-findings table; migration files renamed to the applied timestamp. Mutating admin RPCs call `admin_actor_email(p_actor_id, errcode)` and write their audit row in the same transaction; only `admin_set_user_flags` takes `pg_advisory_xact_lock(hashtext('sfda.admin_membership'))` before validating the actor (`TODO.md`, _Six of the seven admin RPCs…_).
- **`profile_last_seen`** (`20260828135721`/`135732`) is the precedent for a per-account side table: `user_id uuid primary key references profiles(id) on delete cascade`, RLS on, zero policies, `revoke all` from every role including `service_role`, written only by a throttled `insert … on conflict … do update … where …` RPC. `docs/data-policy-decisions.md` §4 is the argument for keeping such state off `profiles`.
- **`chatbot_settings` is already decided:** `docs/data-policy-decisions.md` §3 — drop it in its own migration the next time the schema is touched, recording row count, absent FKs, absent triggers and the grep (README rule 7), then delete its standing-findings row and close the TODO item.
- **Settings.** `SettingsService` has two cache slots (`GENERATION_KEYS`, `NON_GENERATION_KEYS=("signup_enabled",)`) over one `app_settings` row, and `TODO.md` already records that they each query the row independently. This plan adds **no** third slot and puts nothing in `app_settings`.
- **Frontend contract.** `services.js` throws an `Error` carrying `.status` and `.code = body.error` for any pre-stream non-2xx; `handlers.js` `processChatRequestInternal` special-cases `account_disabled` (a bot bubble in the reader's language, no toast, no error mascot) and treats every other pre-stream failure as a fault (`chat.genericError` bubble, `chat.sendFailed` toast, `RobotStateManager.showError()`). `test_admin_page.py` pins the `runtime.*` top-level catalogue to eleven names; every new reader string nests under `runtime.chat.*` or `runtime.profile.account.*`, every console string under `runtime.admin.*`. DESIGN.md's _Notices_ define the in-transcript notice shape and the rule that a boundary is marked in `--confidence`, never `--danger` (`components.css` ~1287, `.source-trigger-badge`). `.stream-note.error` uses `--danger` and must not be reused.
- **The live project, read through the Supabase MCP the same day (read-only).** Four `profiles` rows, all `tier = 'free'` — the second tier (`internal`, renamed to `staff` by §1.1) exists only in code fixtures, never live, which is what makes that rename free today. The database runs `TimeZone = UTC` on Postgres 17.6. Every `public` function is owned by `postgres`, so a `security definer` RPC reads a table that has `revoke all … from service_role` without difficulty. `profiles` carries `on_profile_update` (`before update`, sets `updated_at = now()` on every UPDATE) beside the privilege guard and the consent-record trigger, so any column written on `profiles` bumps the optimistic-concurrency stamp `admin_update_profile` checks. The security and performance advisors report exactly the standing findings `supabase/README.md` lists (eight `rls_enabled_no_policy` rows, two intentional definer functions, leaked-password protection) plus six `unused_index` INFO rows — the FK indexes this schema adds by rule are expected to appear there too. Existing indexes relevant here: `audit_log_target_idx (target_type, target_id, occurred_at desc)` serves the account-detail activity list the new audit rows land in; `profiles` has only its primary key and the partial `disabled_by` index.
- **Library facts, checked against current documentation (Context7, 2026-09-03).** Flask-Limiter: `key_func` may be given per `limit`/`shared_limit` and is called inside the request context; the supported `storage_uri` backends are memory, Redis, Memcached and MongoDB — there is no Postgres storage, which is one more reason the daily allowance is not a limiter limit. Supabase: RLS does not apply to functions, so a `security definer` RPC is secured by `EXECUTE` grants alone; a PL/pgSQL body runs in one transaction and `raise exception` rolls back all of it; `set search_path = ''` is required on every `security definer` function.

---

## Inputs, and where the drafts disagreed

Two delegated drafts, dispatched in parallel with the same verified-facts brief and neither seeing the other: a research-and-adversary pass (Antigravity, `gemini-3.7-flash-high`) and an independent design (OpenCode, `openai/gpt-5.6-luna`, xhigh effort, read-only `plan` agent). Both left the tree untouched (`git status` clean after each). Every claim below that came from a delegate was re-read in the source before being kept.

**What the delegates got wrong.** The research pass "corrected" the facts brief by claiming `handlers.js` has no `processChatRequestInternal`; it does (`static/js/modules/handlers.js:297`), and the tag it cited is that method's own `logError` label. Its claim RPC also let a zero limit through: an `insert … on conflict … do update … where used < limit` guards only the UPDATE branch, so the very first claim of a day succeeds against a limit of 0 (§2 closes this). Neither draft noticed that the seeded default number and `web/config.yaml` can drift apart silently (§4 adds a test). The design pass proposed a `usage_daily_day_idx` on `day` with no query to serve; not built.

| #   | Disagreement                          | Research pass                                | Design pass                                     | Ruling, and the evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| --- | ------------------------------------- | -------------------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Where a per-account override lives    | Separate table                               | Nullable column on `profiles`, trigger extended | **Separate table** `reader_quota_overrides`. `profiles` is the one browser-direct table; every column added to it is one more column in PostgREST's schema for `authenticated` and one more clause in the guard trigger. The `profile_last_seen` precedent and `data-policy-decisions.md` §4 exist precisely to keep operator-written state off `profiles`. A side table also carries `set_by`, `set_at`, `reason` for free, and its `ON DELETE` is its own to state. The live `on_profile_update` trigger settles it: an override written to `profiles` would bump `updated_at` and make a profile form open in another console tab fail its `AD005` save for a change that touched no profile field. |
| 2   | Which calendar day                    | `Asia/Riyadh`                                | UTC                                             | **SUPERSEDED 2026-09-03 — the owner chose `Asia/Riyadh`; §2 ships it, and the reasoning below is kept because it is why the boundary was made one named constant.** ~~UTC.~~ Every timestamp in `web/` is UTC (`account.py`, `admin_store.py`, `chat_store.py`, `data_processing.py`); nothing in the repository names a timezone; the client renders instants in the reader's own locale (`ui.js` `_formatTimestamp`). A reset at 03:00 Riyadh is unusual but honest and rendered locally. The boundary is one named constant in the claim RPC so a later product decision is a one-line migration — which is exactly what happened, on the same day, before anything was built.                      |
| 3   | Quota backend unreachable             | "coherent with Postgres already on the path" | `503 quota_unavailable`, fail closed            | **Fail open, logged.** `identity_cache.py` states the house philosophy: an outage fails open for _access_ and closed for _privilege_; a persistence failure already answers the question and reports the failure in-band. A quota is an allowance, not a credential. During a genuine Supabase outage the token verification (which fails closed) already refuses the request, so the open posture only ever applies to a quota-RPC fault in isolation, which must not take the product down. The reader sees no counter for that turn (`quota: null`).                                                                                                                                                |
| 4   | Tier-management surface               | (not addressed)                              | Third block in the Settings panel               | **Its own console tab.** The Settings panel holds two single-value instance controls, and the registrations plan kept even those apart to avoid re-render entanglement. Tier management is membership administration — a table with member counts, create/edit/delete — and belongs beside _Users_, not under generation settings. Cost of a tab is one section, one init call, one `page.admin.tabs.*` key, one route-gate row.                                                                                                                                                                                                                                                                       |
| 5   | `is_default` column on tiers          | Yes                                          | Yes (partial unique index)                      | **No.** The default tier is `free` by construction: `profiles.tier` defaults to it, `handle_new_user` relies on that default, and the guard trigger's INSERT clause literally compares to `'free'`. A data flag those three cannot follow would be a second, disagreeing source of truth. `free` is undeletable; its key is immutable; its labels and limit are editable.                                                                                                                                                                                                                                                                                                                              |
| 6   | Widen `admin_set_user_flags` for tier | (not addressed)                              | New RPC                                         | **New RPC** `admin_set_reader_quota` covering tier assignment _and_ override in one call, taking the membership advisory lock. No drop + create of a seven-argument function, no change to `PATCH /admin/api/users/<id>`'s tested contract.                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| 7   | Shipped default number                | 50, hard-coded in SQL                        | 200, from `per_day`                             | **Seeded from `web/config.yaml`'s new `server.quota.daily_messages_default`**, hand-copied into the seed migration and pinned equal by a test. **The number is 200** for both seeded rows (owner decision, 2026-09-03).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| 8   | Fix the five unenforced limits here?  | Yes                                          | Yes                                             | **Yes, in Commit A**, because the behavioural harness this plan adds (an enabled limiter in one test) is what proves both the new key and the old fix.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |

Where both drafts agreed and the code agrees with them, the design below simply adopts it: resolution inside the claim RPC rather than from cached `IdentityFlags`; the claim taken after validation and the `allow_create` preflight and before the generator; refund on pre-model failure only; the burst limit re-keyed to the reader; the notification composer's free-text tier becoming a select; the account standing line reading labels from the API.

---

## Adversarial review round

The gate this repo uses before building: a read-only reviewer is handed the synthesized plan and asked to find what the drafters missed. The reviewer of record was meant to be Codex (`/codex-delegate --read-only`); it exhausted its OpenAI usage allowance a third of the way through its read and returned nothing, and an OpenCode `gpt-5.6-sol` fallback on the same account was refused at the first call for the same reason. The round therefore ran on Antigravity (`gemini-3.7-flash-high`, same brief, tree verified untouched) and a fresh Claude sub-agent with no session context (same brief). Every finding below was re-read in the source before it changed the plan; the two the reviewers did not raise but the live-database read did are in _Ground truth_.

### Confirmed defects, and how each is fixed above

1. **`admin_get_user` cannot be `create or replace`d.** It `returns table (…)` (`20260828135749`), and adding columns changes the return type — Postgres refuses with `42P13`. §1.7 is now drop + create.
2. **The refund could land on the wrong day.** `chat_release_daily_message` recomputed "today"; a claim at 23:59:59 whose retrieval failed at 00:00:01 would refund nothing (no row for D+1) or decrement another day's count. The claim now returns `day`, Python carries it on `QuotaClaim`, and the release takes `p_day` (§2).
3. **The timestamp formatter is not where the plan said.** `_formatTimestamp` is a method of the `UI.Notifications` sub-object (`ui.js` ~1688), not of `UI`; `UI.showQuotaNotice` could not have called it. It is hoisted to a module-scoped helper (§6.1).
4. **The reader's own bubble would have been orphaned.** `processChatRequestInternal` draws `UI.addMessage(queryText, 'user')` before the request leaves (`handlers.js` ~306). On a 429 the plan restored the draft to the composer and left the bubble in the transcript as an unanswered turn that `isTranscriptTurn` counts. The bubble is removed first (§6.1).
5. **Only one of the two transport paths carried the 429 body.** `sendChatRequest` (the blocking fallback `blockingChat` uses) was not named; it is now (§6.1).
6. **`admin_set_reader_quota` left `TQ005` to the table `check`.** A negative override would have surfaced as `23514`, unmapped, a 500. The function raises `TQ005` itself (§1.6).
7. **Two protocols owned tier management.** `QuotaBackend` carried admin CRUD that `admin.py` could never reach (it consumes `admin_backend()` only). `QuotaBackend` is now claim/release/status; everything audited lives on `AdminBackend` (§4).
8. **Migration 1.1 bundled four concerns with no rule-1 header.** Split into two files that sequence cleanly (§1.1), so no exception is claimed.
9. **The in-code burst fallback disagrees with `config.yaml`** (`"10 per minute"` vs `"15 per minute"`). Aligned in Commit A (§3.5).

10. **The decorator-order harness could not have worked.** `init_app` returns before building storage or registering `before_request` when `RATELIMIT_ENABLED` is false, so flipping `enabled` on the retained instance enforces nothing. `create_app` gains `enforce_rate_limits` (§3.7).
11. **`/api/identity` would have answered `quota: null` in every test.** The route resolves its backend with `get_admin_backend()` directly, which is `None` under TESTING; the quota read goes through the `quota_backend` factory instead (§4). `test_account_browser.py`'s `Free` assertion depends on it.
12. **A claim taken before `_load_history` could be spent on a 500.** Only `PersistenceUnavailable` is swallowed there; the claim moves to immediately before `Response(...)` and the view-body `try` starts at the claim (§3.1).
13. **"The blueprint's 60/minute also applies" was false**, in the plan and in `app.py`'s own comments: a route limit overrides its blueprint's by default. Corrected in §3.6 and in `TODO.md`'s Known-bug entry.
14. **`profiles.disabled_by` is `NO ACTION`, not the `set null` precedent the plan cited** (§1.2).
15. **`_validate_notification_payload` does not exist**; the validator is `_validate_notification_targeting` (§5.4).
16. **`privileges.test.sql` asserts `chatbot_settings` grants** and would fail after the drop (§1.8).
17. **`composer.tierPlaceholder` would become a key read by nothing** once the input is a select (§7).

### Suggestions adopted

- The two token-hash key functions' docstrings, which justify the hash by saying they run before the blueprint gate, are rewritten in Commit A because that stops being true (§3.5).
- The claim keys on the canonical uuid, never a raw email fallback (§3.2).
- A stale PostgREST schema cache after Commit A is the realistic fail-open scenario; the backend counts consecutive faults and the deploy smoke test asserts `done.quota` (§3.4).
- The notice registers with `NoticeCoordinator` and `clearReaderScopedUI` hides it explicitly (§6.1); the counter sits after `.composer`, not inside its flex row (§6.2); the quota PUT always carries both keys (§5.2); the browser suite never spends its shared in-memory allowance (§10).
- The counter's `aria-live` region writes only when its numbers change, so an unchanged remainder is not re-announced on every answer (§6.2).
- Restoring the draft after a 429 never overwrites a newer draft the reader has typed since (§6.1).
- A new tab glyph must be registered in `ADMIN_RUNTIME_ICON_NAMES` or `test_admin_page.py`'s icon-subset test fails (§5.1).

### Claims the reviewers checked and found correct

Decorator evaluation inside the limiter wrapper (`_limits.py` ~315-325); the five discarded wrappers (`app.py` ~2060-2106); `Limiter.enabled` settable and the instance retained; the fail-open posture against `identity_cache.py` and ARCHITECTURE's outage rules; the zero-limit guard and row-lock behaviour of the claim; the cascade and set-null choices; `security definer` RPCs owned by `postgres` reading tables `service_role` cannot; the closed eleven-name `runtime.*` namespace; the `chatbot_settings` drop; the membership advisory lock precedent.

### Second review round, 2026-09-03

A fourth reviewer — the owner's own planning session, which had independently verified the same codebase and run its own Codex round — read the amended text against its notes and raised five residual gaps plus four nits. Its convergence with this round on the refund day, the limiter-test harness, `42P13`, `TQ005` and the `override_defaults` correction is recorded above; what follows is only the delta, each item re-checked in the source before it moved.

**Taken in full.**

1. **`spent` was set before the generator body could run.** The strongest finding of the round and the reason it was worth having. `stream_response` is a generator function, so the plan's "immediately before `handler.stream_response(...)` is first called" left `_build_messages` and `chat.completions.create` — every provider auth failure, 429 and timeout — inside the spent window, unrefundable. The boundary is now the first delta token (§3.2), and §10's test pair was rewritten: it previously _pinned_ the bug ("a failure after `stream_response` started does not [release]").
2. **Release is not idempotent as a primitive.** True; the once-per-request property was control flow, not an invariant. A `released` guard plus its test (§3.2, §10).
3. **The profileless contradiction.** `/api/identity` said `free` while `get_reader_quota` would have said `null`, and the account's limit would have drifted from the live `free` tier for good. Fourth resolution leg (§2).
4. **The fail-open price was never stated.** Now it is, in the words the ruling actually bought (§3.4).
5. **`_account_rate_key`'s per-session hash.** Conceded against this plan's own first ruling, and extended to `_admin_notification_rate_key`, whose docstring names the very threat a per-session key fails against (§3.5).
6. **The `data-policy-decisions.md` correction was scheduled too late.** Moved from Commit E to Commit A (§9).

**Taken as a documented rule and a test rather than a mechanism.**

- **Edit-vs-claim race.** Real, and the reviewer's `select … for share` fix does not compile: Postgres refuses `for share` on the nullable side of an outer join, and every leg of the resolution query is a `left join`. Consequence is one message, once. The weaker rule is now stated and raced in SQL (§2, §10).
- **Retry double-claim.** The mechanism is real but the premise was not — the reviewer had it that "the client reuses `client_request_id` on retries", where the shipped client mints a fresh id per submission and has no chat retry path (`handlers.js:342`, `:361`, `:1000`; `app.py:1249` says so in a log line). What is true is that the _contract_ (`app.py:2450`, `_InFlightGenerations`) anticipates reuse, so a future retry feature opens it. The proposed `last_claim_request_id` column also under-delivers: one slot per `(user, day)` catches only an immediately consecutive replay. Recorded in §12 with the rule that binds whoever builds the retry.

**Declined.**

- **"`data-policy-decisions.md` §3 says decided while its `STATUS` says proposal."** It does not. §3 is headed _The recommendation_ and the summary table reads "Drop it… Not urgent." — consistent with the `STATUS` line as written. The real item is the sequencing one taken under _Taken in full_ above.

### Third review round, 2026-09-03 — three agents, one debate and one security sweep

Three independent read-only agents on the amended text: OpenCode `gpt-5.6-terra` briefed to **argue** rather than list, Antigravity `gemini-3.8-flash-high` on correctness and internal consistency, and a second Antigravity on security only. None saw the others. Each was told the two prior rounds' findings were already fixed and which six owner decisions were settled. Every finding below was re-read in the source before it changed anything; the false ones are listed too, because a reviewer's miss is as much a fact about this document as a hit.

**Blocking, and found independently by two of the three.**

- **`admin_set_reader_quota`'s signature could not have been created.** The window parameters added in the previous round were defaulted and sat **before** `p_actor_id`/`p_actor_email`, which were not. Postgres refuses: every parameter after a defaulted one must also have a default. `apply_migration` would have failed. Fixed; defaults now last, as every existing admin RPC already does.

**Serious — all confirmed against source.**

- **A false claim about the shipped numbers, and it was load-bearing.** §1.1 said 200/200 changed nothing because the global `per_day: 200` already applied. It does not apply to chat: `chat_limit` is a `shared_limit`, which defaults `override_defaults=True`, so `chat_api: "15 per minute"` **replaces** the daily default — the same mechanism as the five-limits bug, and `config.yaml`'s own comment beside `history_api` says so outright. Chat has no daily ceiling today; 200/day is new enforcement. Paragraph rewritten as a correction rather than edited away.
- **The blocking route cannot refund** (found by two agents). `generate_response` catches every exception and returns apology prose (`openai_app.py:452-460`), so a provider failure is invisible to `handle_chat` — which then finalizes, persists and, once this ships, charges for the apology. §3.2 now changes that method in Commit B, and §10 pins it with a test that fails against today's code.
- **A pre-existing hold leak this plan lands inside.** `adopt_cookie_history` and `_load_history` run between `hold.__enter__()` and any `try`; a non-`PersistenceUnavailable` exception there freezes the conversation as `generation_in_flight` for the life of the process. The view-body `try` now starts at the hold.
- **`admin_get_user` was missing the override window, and would have needed it unfiltered.** The console must distinguish "scheduled", "expired" and "no override" — which §2's window-filtered join collapses to `null` — and an operator's next save would have erased a promotion that had not started yet. It now returns the raw row plus a separately computed `effective_daily_limit`.
- **Documents were scheduled three commits after the code that falsifies them**, against §11's own "must ship together" and `CLAUDE.md`'s same-commit rule. Split by which commit makes which sentence false.
- **The fault counter had no console path.** §3.4 promised the overview would show it; no interface existed to build that from. Given one.

**Security sweep: no critical, no high.** The reviewer confirmed the perimeter holds — all three tables RLS-on with zero policies and `revoke all` including `service_role`; every RPC `security definer` with `set search_path = ''` and granted only to `service_role`; the claim's owner id sourced only from `_durable_owner()`, never from the request body; readers cannot see `reason` or `set_by`; no dynamic SQL anywhere; and the `chatbot_settings` drop severs nothing. Four defence-in-depth items taken:

- **An unverified bearer token must not mint its own rate-limit bucket.** `_rate_key`'s token-hash fallback would let a caller sending a random string per request get a fresh limit per request — a bypass, not a limit — reachable if a route ever attached `@chat_limit` without `@auth_required`. Branch removed; the fallback is the IP.
- **No `p_actor_email` on any of the five new RPCs**, so a caller-supplied address can never reach `audit_log`. The compatibility argument that kept it on the existing seven does not apply to functions that have never shipped.
- **The audit route's `target_type` whitelist** rejects anything but `user` and `settings`, so the `tier` rows §1.5 writes would have been unfilterable the moment they existed.
- **A distinct `quota_reason_required` code**, because the existing `reason_required` string is hardcoded to "A reason is required to disable chat access."

**Also corrected:** the Tiers tab is the **sixth**, not the fifth (the console already ships five); a server-rendered tab glyph must live in `ICONS`, not `ADMIN_RUNTIME_ICON_NAMES`; §1.1's backfill kept a `tier is null` clause the prose two paragraphs later says is dropped; `account.html` was missing from §11; and `function_acls.test.sql` pins the actor gate against a **hardcoded seven-name array** that the five new RPCs must join or one can ship ungated on a green suite.

**Findings checked and rejected.**

- "`reader_quota_overrides.set_by` has no index, violating README rule 4." It does — §1.2 has carried `reader_quota_overrides_set_by_idx` since the table was first drafted. The reviewer read the prose and not the SQL block above it.
- "§7 adds a `runtime.admin.tabs.*` key, but no such namespace exists." §7 adds `page.admin.tabs.tiers`, which is correct and is what the file says. Invented.
- "The in-memory double should be demoted to control flow only, with SQL as the sole authority." Declined — this repo is offline-first by design and the SQL suite is hand-run, so that would leave resolution untested in CI. The drift risk is real and is now recorded in §4 with a procedural mitigation instead.

---

## 1. Database schema and migrations

One concern per file; every FK states its action and gets its index in the same file; every table has RLS on, zero policies, and `revoke all … from anon, authenticated, public, service_role` (the `profile_last_seen` shape — every access path is a `security definer` RPC). Files are named here by concern; the timestamp prefix is whatever `list_migrations` reports after `apply_migration`, and the rename is a mandatory step (collision #2).

### 1.1 `public.tiers` — `…_tiers_table.sql`, then `…_profiles_tier_references_tiers.sql`

Two files, not one: the first creates and seeds the table; the second backfills `profiles.tier` and adds the constraint. They sequence cleanly (a seeded table is harmless until something references it), so README rule 1 needs no exception header. The first file's seed and the second file's backfill are what let the FK apply without a `23503`.

```sql
create table public.tiers (
  key                 text primary key
                      check (key ~ '^[a-z][a-z0-9_]{0,31}$'),
  label_en            text not null check (length(label_en) between 1 and 40),
  label_ar            text not null check (length(label_ar) between 1 and 40),
  -- >= 0, not >= 1: zero is a legal, meaningful limit (owner decision,
  -- 2026-09-03). A tier or an override of 0 means "may sign in, read their
  -- history and browse, but may not ask anything today" — deliberately
  -- distinct from is_disabled, which refuses the session outright. The claim
  -- RPC's explicit `v_limit >= 1` guard is what makes 0 refuse the FIRST
  -- claim of the day as well as later ones (§2).
  daily_message_limit integer not null check (daily_message_limit >= 0),
  ordering            integer not null default 0,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
alter table public.tiers enable row level security;
-- Intentional: rls_enabled_no_policy is expected. Operator-owned; every reader and
-- writer is a security definer RPC. Add the standing-findings row.
revoke all on table public.tiers from anon, authenticated, public, service_role;

-- Seed. 'free' MUST exist before the FK below: it is the column default, the
-- literal in profiles_guard_privilege_columns, and what handle_new_user relies on.
-- BOTH numbers are hand-copied from web/config.yaml server.quota.daily_messages_default
-- (200) and pinned equal by web/tests/test_quota.py::test_seed_matches_shipped_default.
-- Parity is deliberate on day one; the operator raises 'staff' from the console, which
-- is the whole point of the table. See "What 200/200 means on day one" below.
insert into public.tiers (key, label_en, label_ar, daily_message_limit, ordering) values
  ('free',  'Free',  'مجاني',      200, 0),
  ('staff', 'Staff', 'الإداريين',  200, 10);
-- ---- second file: …_profiles_tier_references_tiers.sql ----
-- Any other value already present on a live profile becomes a tier too, so no
-- account is orphaned when the FK lands:
insert into public.tiers (key, label_en, label_ar, daily_message_limit, ordering)
select distinct p.tier, initcap(p.tier), p.tier, <daily_messages_default>, 100
  from public.profiles p
 where p.tier is not null and p.tier not in (select key from public.tiers)
   and p.tier ~ '^[a-z][a-z0-9_]{0,31}$';
update public.profiles set tier = 'free'
 where tier not in (select key from public.tiers);

alter table public.profiles
  add constraint profiles_tier_fkey foreign key (tier)
  references public.tiers(key) on update cascade on delete restrict;
create index profiles_tier_idx on public.profiles (tier);
```

`staff` is seeded because the codebase already assigns a second tier (the admin testing identity, `InMemoryAdminBackend`'s seed, the account page's label map) even though no live profile carries it today — all four live rows are `free`. Seeding it keeps the fixtures and the database describing the same world; the `select distinct` clause that follows is belt to those braces and, on the live project, inserts nothing.

**The key is `staff`, not `internal` — and the codebase rename happens in this same window (owner decision, 2026-09-03).** `internal` names where a person sits rather than who they are; `staff` names the reader. The rename is nearly free **today** and expensive **after** this migration: the `tiers` table does not exist yet, and the live project has zero `internal` rows, so it is a find-and-replace across fourteen fixture, seed and label lines. Once the FK in the second file lands, the same rename is a data migration plus an `on update cascade` rewrite. The touchpoints, all of which move in Commit A **before** the FK file is applied:

| File                                                                                                                                                          | What                                                                                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `web/api/app.py:379`                                                                                                                                          | `_TESTING_IDENTITIES` → `IdentityFlags(..., "staff", ...)`                             |
| `web/services/admin_store.py:621`                                                                                                                             | in-memory admin seed → `"tier": "staff"`                                               |
| `static/js/account/ui.js:102`                                                                                                                                 | `tier === 'internal'` → `tier === 'staff'` (removed entirely by §6.3 — labels go data) |
| `web/i18n/en.yaml:239`, `ar.yaml:157`                                                                                                                         | `tierInternal` → `tierStaff`, `"Staff"` / `"الإداريين"` (also removed by §7)           |
| `test_admin_browser.py:30,733`, `test_notifications_browser.py:36`, `test_admin_audit.py:263`, `test_auth_failure_modes.py:542`, `test_identity_roles.py:231` | fixture tier values                                                                    |
| `web/services/notification_store.py:540,617`                                                                                                                  | data-driven `target_tier`; no code change, fixtures targeting a tier use `"staff"`     |

**Not renamed, and this matters:** the SSE error code `"internal"` (`app.py:3297`, `:3312`; asserted in `test_chat_stream.py:280` and `test_source_panel.py:496`, described in `test_chat_stream.py:139`) and the `processChatRequestInternal` method name (`handlers.js:297`). Both are the ordinary English word, unrelated to a tier; a blanket find-and-replace over `internal` breaks the streaming error contract and its tests.

**What 200/200 means on day one — and a correction, because the first draft of this paragraph was wrong.** It claimed this was a dark launch in which "no reader's behaviour changes", on the reasoning that `web/config.yaml`'s global `per_day: 200` already caps everyone. **It does not cap the chat routes.** `chat_limit` is built with `limiter.shared_limit(<chat_api callable>, scope="chat")` (`app.py` ~2405) and `shared_limit`, like `limit`, defaults `override_defaults=True` — so the explicit `chat_api: "15 per minute"` **replaces** the global `per_day`/`per_hour`/`per_minute` rather than adding to them. `config.yaml`'s own comment beside `history_api` says exactly this ("an explicit limit replaces the defaults in Flask-Limiter"), and so does `app.py` ~2487. The same mechanism as the five-limits bug in _Ground truth_, applied to the defaults instead of a blueprint.

So the truth is: **chat has no daily ceiling today, and 200/day is new enforcement.** A reader who paces themselves under 15/minute can send far more than 200 questions in a day right now; after Commit B, question 201 is refused. Nobody is likely to notice — with four accounts and no observed usage anywhere near it, 200 is well above the waterline — but that is an argument about the number, not about whether the mechanism binds. Do not tell the owner that nothing changes.

What is still true, and is the actual reason for parity: 200 is a **generous first number chosen so the meter can be switched on and watched before it is tightened**, and `staff` starts equal so raising it later is a console edit rather than a decision that has to be made now. The counter (threshold `remaining <= max(3, 20 % of limit)` = 40 at this number) will rarely appear until the number comes down. The first real product decision after Commit B is what `free` should actually be, informed by a month of `usage_daily` rows — which is the whole point of building the meter before the policy. `on delete restrict` is the database's answer to "delete a tier with members"; `admin_delete_tier` refuses first with `tier_in_use` so the reader of the console never meets a `23503`. `on update cascade` exists only so that a key rename, if ever allowed, cannot orphan a profile; the console does not offer renames.

The second file's header records the live row count of `profiles` per tier value before and after the backfill (on the live project: four rows, all `free`, so the `update` touches zero rows and fires neither `on_profile_update` nor the consent trigger — say so, per README's "Checking that a migration touched no rows"; the `tier is null` clause is dead against a `not null` column and is dropped), and asserts afterwards that `select count(*) from profiles where tier not in (select key from tiers)` is zero (a `do $$ … raise exception … $$` block, so the file fails rather than applies half-way).

**`profiles_guard_privilege_columns` is not touched.** Its `'free'` literal stays correct because `free` is the structural default (ruling 5).

### 1.2 `public.reader_quota_overrides` — `…_reader_quota_overrides_table.sql`

```sql
create table public.reader_quota_overrides (
  user_id             uuid primary key references public.profiles(id) on delete cascade,
  -- >= 0 for the same reason as tiers.daily_message_limit: an override of 0
  -- silences one account for the day without disabling it.
  daily_message_limit integer not null check (daily_message_limit >= 0),
  reason              text check (reason is null or length(reason) <= 500),
  -- Optional window (owner decision, 2026-09-03 — see the supersession note).
  -- Both null is the ordinary case and means "in force until an operator
  -- clears it", which is the only behaviour that existed before this column.
  -- A window is how "500 a day until the end of the month" is expressed
  -- without a scheduler: nothing sweeps the table, the claim simply stops
  -- seeing an override once `now()` leaves the window (§2).
  starts_at           timestamptz,
  expires_at          timestamptz,
  constraint reader_quota_overrides_window_chk
    check (starts_at is null or expires_at is null or expires_at > starts_at),
  set_by              uuid references auth.users(id) on delete set null,
  set_at              timestamptz not null default now()
);
create index reader_quota_overrides_set_by_idx
  on public.reader_quota_overrides (set_by) where set_by is not null;
alter table public.reader_quota_overrides enable row level security;
-- Intentional zero policies; add the standing-findings row.
revoke all on table public.reader_quota_overrides
  from anon, authenticated, public, service_role;
```

`on delete cascade` on `user_id`: an override describes an account and must not outlive it (the `profile_last_seen` and notification-child reasoning). `set_by … on delete set null`: the record of _who_ set it is attribution, and deleting the administrator's account must not refuse the delete. The precedent is `notification_recipients.user_id` / `user_notification_reads.user_id` (`20260823202146`), not `profiles.disabled_by` — that column has no stated action and is therefore `NO ACTION`, which _refuses_ the administrator's delete while any profile names them; it belongs in the account-deletion saga's list, and this plan does not copy it. The audit log keeps the full history; this table holds only the current override, so "clear the override" is a `delete`.

**The window expires on read, never on a timer.** An expired row is left exactly where it is and simply stops matching the claim's `where` (§2). There is no `pg_cron` job, no sweep, no "expired" flag to keep in step with the clock — the same discipline the plan already applies to the day boundary, which is also computed rather than stored. Two consequences worth stating: an expired override is still visible in the console (as "expired on {date}", not as a live value) so the operator can see what happened and re-set it, and the row's disappearance from enforcement needs no deploy, no job, and no successful background process. The account's limit falls back to its tier on the very next claim.

### 1.3 `public.usage_daily` — `…_usage_daily_table.sql`

```sql
create table public.usage_daily (
  user_id uuid not null references auth.users(id) on delete cascade,
  day     date not null,
  used    integer not null default 0 check (used >= 0),
  primary key (user_id, day)
);
alter table public.usage_daily enable row level security;
-- Intentional zero policies; add the standing-findings row.
revoke all on table public.usage_daily from anon, authenticated, public, service_role;
```

References `auth.users`, not `profiles`, because accounts without a profile row exist (`admin_get_user` reports `has_profile`) and can hold a valid token; a claim for such an account must resolve to the shipped default (§2), not fail an FK. `on delete cascade`: a count of questions asked has no meaning after the account is gone, and it contains no text — this is the opposite call from `chat_sessions.owner_id`, deliberately, for the opposite reason (a conversation is the reader's work product; a tally is not). The primary key's leading column covers the FK, so no extra index. No `day` index: nothing queries by day yet, and an index for a purge that does not exist is exactly what README rule "no column grant for a feature that does not exist" warns against.

Rows accumulate at one per active reader per day, counts only. Retention is added to the existing `TODO.md` retention entry rather than decided here.

### 1.4 Reader quota RPCs — `…_reader_quota_rpcs.sql`

Three functions, all `security definer`, `set search_path = ''`, revoked from `anon`/`authenticated`/`public`, granted to `service_role`. Full text of the claim in §2; the other two are defined there too.

- `chat_claim_daily_message(p_user_id uuid, p_default_limit integer)`
- `chat_release_daily_message(p_user_id uuid, p_day date)`
- `get_reader_quota(p_user_id uuid, p_default_limit integer)` — read-only; never creates a row.

### 1.5 Admin tier RPCs — `…_admin_tier_rpcs.sql`

`admin_list_tiers()` (reader; returns every tier with a `member_count`), `admin_create_tier(p_key, p_label_en, p_label_ar, p_daily_message_limit, p_ordering, p_actor_id, p_request_ip default null, p_user_agent default null)`, `admin_update_tier(p_key, p_label_en, p_label_ar, p_daily_message_limit, p_ordering, p_actor_id, …)`, `admin_delete_tier(p_key, p_actor_id, …)` — **no `p_actor_email` on any of them**, for the reason §1.6 gives: these are new functions, so the compatibility argument that kept the parameter on the existing seven does not apply, and not accepting a caller-supplied email is the only way to guarantee the audit trail's attribution cannot be forged. Each mutating one takes `pg_advisory_xact_lock(hashtext('sfda.admin_membership'))` **first**, then `admin_actor_email(p_actor_id, 'AD004')`, then mutates, then writes one `audit_log` row (`tier.create`, `tier.update`, `tier.delete`; `target_type 'tier'`, `target_id` = key; before/after JSON of the row) in the same transaction. Refusals by SQLSTATE, mapped in `admin_store._refusal_from`: `TQ001 duplicate_key`, `TQ002 no_such_tier`, `TQ003 tier_in_use`, `TQ004 default_tier_protected` (delete `free`), `TQ005 invalid_limit`, `TQ006 invalid_labels`, `TQ007 invalid_window`. `admin_update_tier` writes no audit row when nothing changed (the `admin_set_user_flags` diff rule).

### 1.6 `admin_set_reader_quota` — `…_admin_set_reader_quota_rpc.sql`

```sql
admin_set_reader_quota(
  p_user_id uuid, p_tier text, p_daily_message_limit_override integer, p_reason text,
  p_actor_id uuid,
  p_override_starts_at timestamptz default null, p_override_expires_at timestamptz default null,
  p_request_ip text default null, p_user_agent text default null
) returns jsonb
```

**No `p_actor_email` parameter, on any of the five new RPCs.** The seven existing admin functions still carry one, and `20260828001543`'s own header explains why it stayed: removing it would have meant a destructive drop-and-create of seven functions for no gain, since the body already ignores the argument and uses `v_actor_email := public.admin_actor_email(p_actor_id, 'AD004')` instead. That constraint does not apply to a function that has never shipped. Taking the parameter at all would leave a caller-supplied email one careless line away from `audit_log.actor_email` — an operator, or a bug in the Python layer, writing an arbitrary address into the immutable attribution trail. The new functions resolve the email from the id they just validated, inside the same transaction, and there is no second source to confuse it with.

**Argument order is load-bearing, not cosmetic.** PostgreSQL requires that every parameter following one with a default also have a default; an earlier draft of this section put the two window parameters (defaulted) ahead of `p_actor_id` and `p_actor_email` (not defaulted), which `create function` rejects outright. All defaulted parameters go last, which is also the shape every existing admin RPC uses (`20260814110722_serialize_admin_membership_changes.sql`). The window parameters therefore sit **after** the actor pair and before the two request-context ones. Because the Python side passes these by keyword through PostgREST, the reordering costs nothing at the call site.

`p_tier null` = leave the tier alone; `p_daily_message_limit_override null` = clear the override (delete the row). Takes the membership advisory lock first, validates the actor inside it, locks the target profile `for update` (`AD003 no such account` if absent — a profileless account cannot be assigned a tier), validates the tier exists (`TQ002`), the override is null or `>= 0` (`TQ005` — raised by the function, not left to the table's `check`, so a bad value is a mapped 422/409 and never a `23514` surfacing as a 500) and the window is coherent (`TQ007 invalid_window`: `expires_at > starts_at` when both are given, and `expires_at > now()` on a write — an override that is already expired the moment it is saved is an operator mistake, not a state worth storing), then: updates `profiles.tier` if changed and audits `user.tier_change` (before/after `{tier}`); upserts or deletes `reader_quota_overrides` and audits `user.quota_override_change` (before/after `{daily_message_limit, starts_at, expires_at}` — the window is part of the decision and belongs in the diff, so extending a promotion by a week is as auditable as changing its number; `note` = `p_reason`). Returns `{tier, override, override_starts_at, override_expires_at, effective_limit}`. `effective_limit` is resolved through the **same window clause the claim uses**, so an override saved with a future `starts_at` returns the tier's number and the console shows the operator what is in force right now rather than what they just scheduled. Two audit rows when both changed, none when nothing did. A tier change is an UPDATE on `profiles`, so `on_profile_update` bumps `updated_at`; a profile form the operator had open loads a fresh `updated_at` because the console re-opens the account after every save (`openAccount(userId)`), which is the same interaction `admin_set_user_flags` already has with a role change. The override write touches only the side table and bumps nothing.

Why the lock: `TODO.md` records that six of seven admin RPCs validate the actor without holding anything; this feature adds four mutating RPCs and takes the lock in every one of them so it adds to the one, not the six. The lock is cheap on an instance this size and is already the documented fix shape.

### 1.7 `admin_get_user` — `…_admin_get_user_reports_quota.sql`

**Drop + create, not `create or replace`:** the function `returns table (…)` (`20260828135749`), and adding columns changes the return type, which Postgres refuses (`42P13`). The returned row gains `tier_label_en`, `tier_label_ar`, `daily_message_limit_override`, `override_starts_at`, `override_expires_at`, `effective_daily_limit`, `used_today`, `quota_resets_at`. Counts only, never text.

**This function reads `reader_quota_overrides` WITHOUT the window clause — and that is the point.** §2's resolution join deliberately hides an override that is outside its window, because enforcement must not see it. The console has the opposite need: §5.2 has to render "scheduled, starts 1 October" and "expired on 30 September, now using the tier limit", and it cannot tell either of those from "this account has no override" if the row arrives as `null`. Worse, the operator's next save would then `PUT` a null window and silently erase a promotion that had not started yet. So `admin_get_user` joins the override plainly and returns the raw row; `effective_daily_limit` is computed **with** the window clause, so the console gets both truths side by side — what is stored, and what is actually in force right now. The two must never be collapsed into one field.

### 1.8 Drop `public.chatbot_settings` — `…_drop_chatbot_settings.sql`

Its own migration, last, exactly as `data-policy-decisions.md` §3 specifies: the header records the row count (0), the foreign keys in both directions (none), the triggers (none) and the grep across `web/`, `static/`, `supabase/` that proves nothing reads it; `drop table public.chatbot_settings;` with no `cascade`. Then delete its row from `supabase/README.md`'s standing-findings table and its row from _Current shape of `public`_, remove the three `chatbot_settings` grant assertions from `supabase/tests/privileges.test.sql` (~65-67; the by-hand run would otherwise fail on a missing relation), and close the `chatbot_settings` question in `TODO.md`'s quota entry.

### 1.9 `get_identity_flags` — unchanged

`/api/identity` calls `get_reader_quota` separately (§4), in its own `try`/`except`, rather than widening the deliberately narrowed standing-line RPC (`20260822231726`).

---

## 2. Resolution semantics and the atomic claim

**Order:** `reader_quota_overrides.daily_message_limit` **(only while inside its window, if it has one)** → `tiers.daily_message_limit` (via `profiles.tier`) → **the live `free` tier's limit** → `p_default_limit` (the shipped default, passed in from `web/config.yaml` by Python). Every profile has a tier by FK, so the last two legs are reachable only by an account with no `profiles` row.

**Why four legs and not three.** A profileless account is very nearly unreachable — `handle_new_user` (`20260814005509` §1) inserts a profile on every `auth.users` insert with `on conflict (id) do nothing`, and §3 of that same migration backfilled every account that predated it, so only a manual profile delete produces one. But the three-leg version had a contradiction visible in the shipped API: `/api/identity` reports `tier: free` for an unresolved reader (`IdentityFlags`'s own default), while `get_reader_quota`'s left join would report `tier_key: null` with null labels for the same account — two endpoints disagreeing about the same reader in the same response cycle. Worse, that reader's limit would sit on the config default for good, drifting away from the `free` tier every time the operator edits it, with no way to see the drift in the console. Resolving to the live `free` row costs one more join leg, makes the two endpoints agree, and keeps the config default as what it is meant to be: the **seed**, and a last resort if somebody deletes the `free` row the schema is supposed to protect (`TQ004`). A `p_default_limit` fallback that actually fires is logged at `warning` — it means the structural tier is gone.

**Where it executes: inside the claim RPC, in one statement's transaction.** Not in Python from `IdentityFlags`, because those flags are cached for 30 s and a limit read from them could be stale for a change the operator just saved; because the comparison and the increment must be one atomic operation; and because the RPC contract already wants the owner id first and filtered inside. The 30-second cache therefore does not affect enforcement at all — it still carries `tier` for the notification composer's targeting, and `_evict_identity_caches` is still called after a tier change so the composer and the account page see it at once.

**Calendar day: `Asia/Riyadh`** (owner decision, 2026-09-03, reversing ruling 2's UTC — see §13 Q2), as a single constant `v_tz constant text := 'Asia/Riyadh'` at the top of the function. This is the one place the zone is named. `resets_at` is the next Riyadh midnight rendered as a `timestamptz`, and the expression `((v_day + 1)::timestamp at time zone v_tz)` is zone-agnostic — it needs no change beyond the constant. Riyadh is a fixed UTC+3 with no daylight saving, so there is no ambiguous or skipped local midnight to design around; the client still renders the instant in the reader's own locale. The allowance therefore resets when the reader's day does, which is the point: a UTC reset landing at 03:00 local was defensible but not explicable to a reader.

**Mid-day changes have one semantic: immediate, applied to the remaining allowance, never to `used`.** `remaining = greatest(0, new_limit − used)`. Raising a limit frees capacity on the next claim; lowering it below `used` makes the next claim a 429 until midnight; clearing an override returns the reader to the tier limit on the next claim. No historical count is rewritten. Tested at both the RPC (SQL) and the in-memory double (pytest).

**"Immediate" means from the next claim, not mid-claim — the weaker rule, stated deliberately.** The resolution `select` and the incremental `insert` are two statements in one function, and under `READ COMMITTED` each takes its own snapshot. An operator who lowers a limit can commit in the gap, and a claim that had already resolved the old, higher limit will succeed against it. The rule this plan adopts is therefore: **a claim that has begun uses the limit it resolved.** The window is microseconds wide and the consequence is bounded at one message, once, on the edit that closes it.

Locking it away was considered and rejected on cost, but the reason is worth recording so nobody re-derives the obvious fix and finds it does not compile. `select … for share` on the resolution query would serialise against `admin_set_reader_quota`, which already takes `for update` on the profile row (§1.6) — except that Postgres refuses `for share` on the nullable side of an outer join (`0A000: FOR SHARE cannot be applied to the nullable side of an outer join`), and every leg of that query is a `left join`. Closing it properly means a separate `select 1 from public.profiles where id = p_user_id for share` ahead of the resolution — which locks nothing at all in the profileless case, the one case where a lock would be hardest to reason about. A one-message overshoot is not worth a second statement on the hot path plus an asterisk. `test_quota.py` and the SQL suite both pin the rule as behaviour (§10), so a future change to it is a test change rather than a silent drift.

```sql
create function public.chat_claim_daily_message(p_user_id uuid, p_default_limit integer)
returns table (allowed boolean, used integer, "limit" integer, remaining integer,
               resets_at timestamptz, tier_key text, day date)
language plpgsql security definer set search_path = '' as $$
declare
  v_tz   constant text := 'Asia/Riyadh';
  v_day  date;
  v_limit integer;
  v_tier text;
  v_used integer;
begin
  v_day := (now() at time zone v_tz)::date;

  -- Four legs, in order: override, the account's tier, the live `free` tier
  -- (a profileless account, which `handle_new_user` makes near-impossible),
  -- and only then the shipped default — which fires only if `free` itself is
  -- missing, and says so in the log.
  select coalesce(o.daily_message_limit, t.daily_message_limit,
                  f.daily_message_limit, p_default_limit),
         coalesce(p.tier, f.key)
    into v_limit, v_tier
    from (select p_user_id as id) x
    left join public.profiles p on p.id = x.id
    left join public.tiers t on t.key = p.tier
    left join public.tiers f on f.key = 'free'
    left join public.reader_quota_overrides o
           on o.user_id = x.id
          -- The window, applied in the join rather than after it: an override
          -- outside its window must be invisible to `coalesce`, not merely
          -- filtered later. Both bounds nullable, so an unwindowed override
          -- (the ordinary case) matches exactly as it did before the columns
          -- existed.
          and (o.starts_at  is null or o.starts_at  <= now())
          and (o.expires_at is null or o.expires_at >  now());

  -- `v_tier` is null only when the account has no profile AND the structural
  -- `free` row is gone, which is the one case the shipped default actually
  -- serves. Loud, because TQ004 exists to make it impossible.
  if v_tier is null then
    raise warning 'quota: no tier resolved for %; falling back to the shipped default', p_user_id;
  end if;

  -- A zero limit must refuse the FIRST claim of the day too. The INSERT branch
  -- of an upsert has no WHERE clause, so it is guarded here, explicitly.
  if v_limit >= 1 then
    insert into public.usage_daily as u (user_id, day, used)
    values (p_user_id, v_day, 1)
    -- NOT `on conflict (user_id, day)` -- see below. This is load-bearing.
    on conflict on constraint usage_daily_pkey do update
      set used = u.used + 1
      where u.used < v_limit
    returning u.used into v_used;
  end if;

  if v_used is not null then
    return query select true, v_used, v_limit, greatest(0, v_limit - v_used),
                        ((v_day + 1)::timestamp at time zone v_tz), v_tier, v_day;
  else
    select coalesce(u.used, 0) into v_used
      from (select 1) s left join public.usage_daily u
        on u.user_id = p_user_id and u.day = v_day;
    return query select false, v_used, v_limit, 0,
                        ((v_day + 1)::timestamp at time zone v_tz), v_tier, v_day;
  end if;
end $$;
```

**The conflict target names the constraint, not the columns — and this was found by running it, not by reading it.** This function returns a column called `day`, so `day` is a PL/pgSQL variable in scope for the whole body. A bare `day` inside `on conflict (user_id, day)` is therefore ambiguous, and Postgres raises `42702: column reference "day" is ambiguous`. The trap is _when_: PL/pgSQL defers parsing of embedded SQL until first execution, so the column-list form **creates perfectly happily** — `apply_migration` succeeds, `get_advisors` is clean, the migration looks done — and then throws on the first real chat request. Caught during Commit A by exercising the function against the live project before filing it; a plan that had only been read would have shipped it. `on conflict on constraint usage_daily_pkey` names the primary key and contains no ambiguous identifier at all. Do not "tidy" it back to the column list. (The alternatives considered: a `#variable_conflict use_column` pragma, which changes name resolution for the whole body and would silently alter behaviour if a later local ever matched a column; or renaming the returned column, which would ripple into Python and the double for no gain.)

Concurrency: `on conflict … do update` takes the row lock on the existing `(user_id, day)` row; a second concurrent claim blocks until the first commits and then evaluates `where u.used < v_limit` against the committed value. Two concurrent _first_ claims of a day serialise on the unique index the same way. Eight tabs from one reader cannot overspend; no advisory lock, no `select … for update` retry loop, no `23505` to catch. Exhaustion is a returned row (`allowed=false`), never an exception — an exception would roll back nothing useful and cost a Python `try` per call.

`chat_release_daily_message(p_user_id, p_day)`: `update public.usage_daily set used = greatest(0, used - 1) where user_id = p_user_id and day = p_day returning used`. The day is the one the claim returned, carried on the Python `QuotaClaim`, never recomputed: a claim at 23:59:59 whose retrieval fails at 00:00:01 must refund day D, not touch day D+1 (or, with no row yet for D+1, refund nothing). Called only when the request fails **before the model produced a token** (§3.2 — the boundary is the first delta, not the call that builds the generator). Never after: a reader who watches most of an answer stream and cancels has consumed the model call, and refunding that is the exploit every naive quota ships with.

The RPC is deliberately **not** idempotent — `greatest(0, used - 1)` decrements every time it is called — and it stays that way, because making it idempotent would need a claim identity the day row does not carry. The once-per-request guarantee lives in Python instead (`_release_daily_message`'s `released` flag, §3.2), which is where the control flow that could violate it also lives.

`get_reader_quota(p_user_id, p_default_limit)`: the same resolution `select` — **including the window clause, so a read and a claim can never disagree about whether an override is in force** — left-joined to today's `usage_daily` row, returning `used, "limit", remaining, resets_at, tier_key, tier_label_en, tier_label_ar, override, override_expires_at`. The extra column is what lets the console say "500/day until 30 September" and, if question 8 is answered yes, the reader too. A read never inserts a row.

---

## 3. Request lifecycle and rate-limit keys (`web/api/app.py`)

### 3.1 Where the claim runs

In `handle_chat_stream`, after `_validate_chat_request` (a 400 spends nothing), after `generations.hold(...)`, after the `allow_create=false` preflight (a 404 spends nothing), after `store.adopt_cookie_history` / `_load_history` (either can raise something other than `PersistenceUnavailable` and become a 500 — a claim taken before them would be spent on a request that never reached the generator), and immediately **before** `Response(stream_with_context(generate()))`. The view-body `try` that today wraps only the `Response(...)` line starts at the claim, and its `except` refunds as well as releasing the hold.

**It must start earlier than the claim, in fact — at `hold.__enter__()` — because there is a pre-existing hold leak in exactly this stretch of code.** `hold.__enter__()` runs at `app.py` ~3083; the `allow_create=false` preflight below it releases explicitly on its 404 path; but `store.adopt_cookie_history(...)` (~3094) and `_load_history(...)` (~3097) then run **outside any `try`**, and the only two releases in the route are the generator's own `finally` (~3320, which never runs because nothing ever iterates a `Response` that was never built) and the `except` around `Response(...)` construction (~3327). An exception from either of those two calls that is not `PersistenceUnavailable` therefore leaves the hold set for the life of the process, and every later request naming that conversation is refused as `generation_in_flight` — a conversation permanently frozen by one transient failure, on a single-worker deployment where the process is long-lived.

This plan does not cause that bug but it lands its claim in the middle of it, so Commit B closes it: one `try` opened immediately after `hold.__enter__()`, covering the preflight, the cookie adoption, the history load **and** the claim, whose `except` releases the hold, refunds if a claim was taken, and re-raises. Ownership of the release transfers to the generator only once `Response(...)` has been constructed successfully. `test_chat_stream.py` gains a case that makes `_load_history` raise a plain `RuntimeError` and asserts the conversation is not left live — it fails against today's code, which is the point.

```python
quota = _claim_daily_message()  # None on backend fault → fail open, logged
if quota is not None and not quota.allowed:
    hold.__exit__(None, None, None)
    return _quota_exhausted_response(quota)
```

`_quota_exhausted_response` returns `429 {"error": "quota_exhausted", "limit", "used", "remaining": 0, "resets_at": <iso>, "tier": <key>}` with `Retry-After` = seconds until `resets_at`, rounded up, and `Cache-Control: no-store`. This is the route's own response, not Flask-Limiter's generic 429, so the client can tell an allowance from a burst refusal (`code` present vs absent). The identical block sits in `handle_chat` so alternating endpoints cannot double the allowance.

### 3.2 Refund, and the `spent` flag

The claim keys on `_durable_owner()`'s canonical uuid, not `g.identity.user_id` raw: `_authenticate_request` falls back to the email when a provider omits `id`, and an email cannot key a `uuid` column (`20260828143044` fixed exactly this for `touch_last_seen`). A non-uuid owner skips the claim and streams uncounted, logged once, the same degradation durable history already applies.

**The refund boundary is the first delta token, not the call to `stream_response`.** This is the one place the boundary is easy to draw wrongly, and drawing it wrongly costs the reader a message for a turn the model never saw. `OpenAIHandler.stream_response` (`web/services/openai_app.py:410`) is a **generator function**: `handler.stream_response(...)` constructs a generator and executes none of its body. `_build_messages` and `self.client.chat.completions.create(...)` both run inside that body, on the first `next()` — which is to say inside `app.py`'s `for token in handler.stream_response(...)` loop, not before it. Setting `spent = True` on the line above that loop would therefore mark the allowance consumed for every provider auth failure, provider 429, timeout and connection error, which is the most likely pre-answer failure in production and exactly the class the refund exists for.

So, inside `generate()`:

```python
spent = False
for token in handler.stream_response(query, llm_context, category, history, lang=lang):
    spent = True  # the model has produced output; the call is real
    parts.append(token)
    yield sse("delta", {"t": token})
```

An assignment per token is cheaper than the branch that would avoid it, and it needs no separate "first iteration" flag.

**The blocking route cannot take that rule as written, and needs a small change to `openai_app.py` first.** `handle_chat` calls `openai_handler.generate_response(...)` (`app.py` ~3404), and `generate_response` joins the same generator inside its own `try`/`except Exception` which **swallows every failure and returns apology prose** — `"I'm sorry, I encountered an error while generating a response. Please try again."` with an empty suggestion list (`openai_app.py:452-460`). From the route's side a provider outage is therefore indistinguishable from a real answer: no exception reaches it, so no wrapper it could write would ever see the failure, and today that apology is finalized, persisted and returned as though it were an answer. Wiring a quota onto that path unchanged would **charge a reader for the apology** and never refund, which is the exact opposite of what §3.2 exists to guarantee.

Two ways to close it, and Commit B takes the first:

1. **Make the failure visible.** `generate_response` gains a third return element (or raises a dedicated `GenerationFailed` that `handle_chat` catches), so the route can tell "the model answered" from "the model never did". The apology string stays exactly where it is for every existing caller that wants it — `scripts/eval_citations.py` and the tests use this method — but the route learns the truth. Small, and it fixes a pre-existing honesty bug that has nothing to do with quotas: today the blocking route persists an apology into a reader's durable history as a regulatory answer.
2. Have `handle_chat` consume `stream_response` itself and join the parts, so both routes share one generation contract. Cleaner in the long run, larger diff, and it moves suggestion generation too — recorded as the alternative, not taken here.

Until one of them lands, the blocking route's claim is **not** refundable, and that must not be papered over: §10 pins the behaviour with a test that fails against today's `generate_response`.

The consequence is deliberate: a provider that connects and returns an **empty** stream is refunded. That is the honest reading — the reader got no answer — and it is a rarer case than the failure modes above.

The existing `except SearchEngineError` branch, the generic `except Exception` branch and the `GeneratorExit` branch each call `_release_daily_message()` **only if `not spent`**. The `except Exception` in the view body around `Response(...)` construction does the same. Nothing else refunds. A refund failure is logged and swallowed: it must never turn a reported retrieval outage into a second error. On the blocking route the same three branches apply once `generate_response` can report failure at all (above); until then that route's claim is knowingly unrefundable, which is why the change to `openai_app.py` is part of Commit B rather than a follow-up.

**Release runs at most once per request.** `chat_release_daily_message`'s `greatest(0, used - 1)` is not idempotent as a primitive; nothing in the SQL stops a second call from refunding a message the reader actually spent. Today the `spent` flag happens to make the single call site once-per-request, but that is control flow, not an invariant, and it would not survive a refactor that moved the refund. `_release_daily_message()` therefore keeps its own request-local guard — a `released` flag set on first entry, returning immediately thereafter — and `test_quota.py` asserts a double call decrements once (§10).

### 3.3 The `done` frame and the blocking response carry the counter

`done` gains `quota: {used, limit, remaining, resets_at}` (the claim's own return value; zero extra round trips). `handle_chat`'s JSON gains the same object. `ARCHITECTURE.md`'s frame-order sentence does not change; `test_chat_stream.py`'s frame-order test gains an assertion on the field.

### 3.4 Fail-open posture

`_claim_daily_message()` wraps the backend call; any exception is logged at `error` with `exc_info` and returns `None`, and the request proceeds uncounted with `quota: null` on `done` (ruling 3). A `None` backend (no service-role key configured, no persistence) behaves the same way, so a Supabase-less deployment keeps working. The realistic failure is not an outage but a stale PostgREST schema cache right after Commit A (`PGRST202` on the new function), under which every request would fail open with only a log line to show for it — so the backend keeps a process-local count of consecutive claim faults and `scripts/smoke_real.py` gained a **DAILY ALLOWANCE** section that exercises the three real RPCs through `SupabaseQuotaBackend` — status, claim, release — and asserts the refund lands. An earlier draft of this sentence said the script asserts `done.quota` is non-null; it cannot, because it deliberately bypasses Flask (`search → build_source_payload → streamed answer → citation validation`) and never builds a response frame. What it can do is the check that actually matters after a deploy: prove the function exists, that `service_role` may execute it, and that PostgREST's schema cache has caught up — the three faults that would otherwise fail closed on every request. It costs no model call and releases the claim it makes.

That counter needs somewhere to surface, and an earlier draft said "the console overview shows it" without giving it a path — `QuotaBackend` has three reader methods and §5 defined no overview surface, so the promised signal could not have been built from the stated interfaces. It gets one: `SupabaseQuotaBackend` exposes `fault_count` as a plain attribute, `GET /admin/api/overview` (which `initOverviewTab` already calls) returns `quota_fault_count`, and the overview renders a single line only when it is non-zero — "Quota backend: N consecutive failures" in `--danger`. Zero chrome on the happy path, and the number is process-local, so it resets on restart and means "since this worker started", which the label says.

**Refinement, third review round: fail open on transport faults, fail closed on configuration faults.** The owner's ruling was that a quota fault must not take the product down — an allowance is not a credential. That reasoning holds for a timeout, a dropped connection, a PostgREST 5xx: transient, self-healing, and refusing readers over one would be an outage the quota caused rather than prevented. It does **not** hold for a fault that is permanent until a human acts. `PGRST202` (the function is not in the schema cache, or does not exist), `42501` (permission denied on the RPC), and a missing-grant failure all mean the deploy is broken, not that the database is briefly unwell — and under a blanket fail-open they convert a broken deploy into **unmetered access for every authenticated reader**, indefinitely, with a log line as the only evidence. That is a bigger failure than the one the ruling was protecting against, and the mitigation (a counter and a smoke test) is detection, not prevention.

So `_claim_daily_message()` classifies: a configuration-shaped fault returns a sentinel that makes the route answer `503 {"error": "quota_unavailable"}` with `Retry-After`, exactly as the token-verification path already fails closed; everything else keeps the open posture with `quota: null`. Both branches increment the fault counter. This narrows the owner's ruling rather than reversing it, and it is cheap — the SQLSTATE and the PostgREST code are already on the exception. The owner can reverse it back to a blanket fail-open in one line if they would rather carry the risk; it is called out in §13 so the choice is theirs and visible.

State the price of the open half plainly, because ruling 3 bought it deliberately: **every deploy carries an unbilled window that lasts until the smoke test passes.** Nobody is refused during it and nothing is counted; the log line and the fault counter are the only evidence it happened. That is the trade against the stricter `503 quota_unavailable` posture, and it is acceptable only because the counter and the smoke assertion make the window observable rather than silent. If either is dropped, the ruling should be revisited with it.

### 3.5 Burst limit keyed to the reader

```python
def _rate_key() -> str:
    identity = getattr(g, "identity", None)
    if identity is not None:
        return f"reader:{identity.user_id}"
    # NO token-hash branch. An UNVERIFIED bearer token must never mint its own
    # bucket: a caller sending a fresh random string per request would get a
    # fresh limit per request, which is a complete bypass rather than a limit.
    # Every route this keys is behind a gate that populates g.identity before
    # dispatch, so reaching this line means a misconfiguration, and the safe
    # answer to a misconfiguration is the coarser key, not the forgeable one.
    return "ip:" + get_remote_address()
```

The dropped branch is the one place this design could have been turned inside out. `_account_rate_key` hashes the bearer token today **because** it runs in middleware before the gate and has nothing better; once §3.6's reassignment moves these limits to dispatch, `g.identity` is always set on the paths that matter, and keeping a token-hash fallback would leave a forgeable key reachable if a future route ever attached `@chat_limit` without `@auth_required`, or inverted the decorator order §3.7 pins. Falling back to the IP is strictly weaker for a legitimate reader behind NAT and strictly stronger against an attacker, which is the right way round for a fallback that should never execute.

`chat_limit = limiter.shared_limit(<callable>, scope="chat", key_func=_rate_key)`; the callable's in-code fallback becomes `"15 per minute"` to match `config.yaml` (it is `"10 per minute"` today, a silent disagreement). The decorator order on both chat routes stays `@app.route` / `@auth_required` / `@chat_limit` and gains a comment naming the test that pins it. **`_account_rate_key` re-keys to the account** in the same commit, which is a reversal of this plan's first draft ("the token hash already gives per-reader isolation and changing it buys nothing") and is worth stating as one. The hash is per-**session**, not per-reader: one account on a laptop and a phone holds two export budgets, while `config.yaml:127` says in as many words "Keyed per reader, not per IP". The docstring's justification for the hash — Flask-Limiter's `before_request` runs before `account_bp._gate`, so `g.identity` is not set — is true **only of a middleware-evaluated limit**, and `_account_rate_key` is used by exactly two registrations (`app.py:2095`, `:2105`), both of them among the five whose wrappers §3.6 reassigns. Once reassigned they evaluate inside `LimitDecorator.__inner`, at dispatch, after every `before_request` hook including `_gate` — so `g.identity` _is_ populated, and the stated reason stops applying to the only two callers it was written for. The key becomes `g.identity.user_id` with the token hash and then the IP as fallbacks (the `_rate_key` ladder above, which is why all three end up sharing one helper). An unauthenticated request never reaches the wrapper at all, because `_gate` has already refused it.

**`_admin_notification_rate_key` re-keys for the same reason**, and its own docstring makes the case: it names "a compromised admin account spamming via multiple IPs" as the threat, and a per-session hash is precisely what fails against it — an attacker holding the credentials signs in, gets a session of their own, and with it a fresh 10/hour. `admin_bp._gate` calls `_authenticate_request`, which sets `g.identity` (`app.py:747`) before dispatch, and `admin.create_notification` is itself one of the five reassignments, so the same ordering argument holds without a second GoTrue round trip — the objection the docstring raises. All three docstrings, which explain the hash by saying the key runs _before_ the gate, become false in the same commit and are rewritten with it; `config.yaml`'s `export_api` comment stops being aspirational. `history_api`/`sessions_api` stay IP-keyed; re-keying navigation reads is a separate decision and is listed under _Deliberately not done_.

### 3.6 The five unenforced limits

Each `limiter.limit(...)(app.view_functions[name])` becomes `app.view_functions[name] = limiter.limit(...)(app.view_functions[name])`, with a comment explaining why the assignment is load-bearing and pointing at the test. Flask dispatches through `view_functions`, so the replaced callable is what runs; the blueprint's `before_request` gate still runs first. One correction to the comments beside those five registrations (`app.py` ~2089-2092, "Both stack on top of the blanket 60/minute"): they do not. `limit()` defaults `override_defaults=True`, and `_manager.py` adds a blueprint's limits only when a route carries no overriding limit of its own, so once enforced each of the five carries exactly its own limit and not the blueprint's. Commit A rewrites those comments to say so; if stacking is wanted, `override_defaults=False` is the switch. Filed as a _Known bug_ entry in `TODO.md` in the same commit that plans this (this session), closed by Commit A.

### 3.7 Pinning the order, behaviourally

`web/tests/test_rate_limit_keys.py`: `create_app` gains a keyword-only `enforce_rate_limits: bool = False`, and `_configure_app` sets `RATELIMIT_ENABLED = enforce_rate_limits or not testing`, so a test can build one app with the limiter genuinely initialised (memory storage, the IP-keyed defaults included — harmless across three requests) while every other test keeps today's disabled limiter. The chat limit is lowered by `monkeypatch.setitem(config._config["server"]["rate_limit"], "chat_api", "1 per minute")` — not by patching `config.get`, which four other request-time lambdas share. Test: reader A (`fake_token`) → 200, reader B (`fake_reader_b_token`) from the same test client IP → 200, A again → 429 with **no** `quota_exhausted` code. Reversing the decorators makes B's request a 429 and the test fail. Sibling tests hit `account.export` twice with `export_api` at `"1 per 10 minutes"` and `admin.revoke_sessions` twice at `"1 per minute"` and expect a 429 on the second — the regression test for §3.6. `test_registrations_pause.py`'s comment keeps its conclusion (you cannot flip the limiter on for one test) and loses its stale "never retained" clause, pointing at this file for the harness that does work.

---

## 4. Services and configuration

- **`web/config.yaml`** gains `server.quota.daily_messages_default: 200` (owner decision, 2026-09-03 — the same number today's global `per_day` already carries) with a comment saying it is the seed for **both** shipped tiers and the last-resort fallback for a profileless account whose `free` row is missing, that tiers are the runtime authority, and that `test_quota.py::test_seed_matches_shipped_default` pins the seed migration to it. **Both seeded numbers move together, or not at all:** `free` and `staff` are seeded from this one key, and the test compares **both** rows to it, so an implementer who edits the migration to give `staff` a different number fails the suite rather than shipping a silent divergence between the config comment and the database. Differentiating the two tiers is a **console** edit after Commit D, never a change to the seed — which also guarantees that an account whose override is cleared always falls back to a tier limit somebody deliberately set, rather than to whichever number happened to be typed into a migration. Nothing goes into `app_settings` or `SettingsService`; no third cache slot.
- **`web/services/quota_store.py`** — `QuotaBackend(Protocol)` with exactly three methods, the reader path only: `claim(user_id) -> QuotaClaim` (`allowed, used, limit, remaining, resets_at, tier_key, day`), `release(user_id, day) -> None`, `status(user_id) -> QuotaStatus`. Tier CRUD and `set_reader_quota` live on `AdminBackend` (below), because `admin.py` consumes `admin_backend()` exclusively and every audited, actor-carrying mutation in this repo already lives there; two protocols owning tier management would be the kind of split that drifts. `SupabaseQuotaBackend` calls the three reader RPCs with `p_default_limit` from config; `InMemoryQuotaBackend` seeded with `free`/`staff` and the testing identities, day keyed on the **`Asia/Riyadh`** date (the same zone as the RPC — a double that rolls over on a different day than the thing it doubles is worse than no double), with a `_now` hook so rollover is testable.

  **Use `zoneinfo` from the standard library, and add `tzdata` to `requirements-dev.txt`.** `zoneinfo` is stdlib from Python 3.9, so the 3.10 floor is fine and no third-party date library is warranted — but `ZoneInfo("Asia/Riyadh")` resolves against the _system_ IANA database, which **Windows does not have**. Per PEP 615 the fallback is the `tzdata` PyPI package (a first-party CPython artifact carrying the zic-compiled IANA binaries), and without it a Windows developer gets `ZoneInfoNotFoundError` on every quota test while Linux CI and the Linux VPS pass. It resolves on this machine today only because something else pulled it in transitively; neither requirements file declares it, so that is luck, not configuration. It belongs in **`requirements-dev.txt`**, not `requirements.txt`: production Python never names the zone at all — the RPC does the day arithmetic in Postgres and hands back `day` and `resets_at` — so only the test double needs it.

  **The double applies the same override-window matching as the RPC**, resolved against the same `_now` hook: an override is in force only when `starts_at is null or starts_at <= _now()` and `expires_at is null or expires_at > _now()`, and outside that the tier limit applies. This is written down because §10 drives every window case through the double, and a double that quietly ignored the window would let all of those tests pass against logic the database does not implement — the failure mode `CLAUDE.md` names as "a test that mocks the function under test proves nothing". The double's resolution order must match §2 leg for leg, window included, or the SQL suite is the only thing actually testing this feature.

  **The standing risk this creates, recorded rather than solved.** Two implementations of one authorization policy — PL/pgSQL and Python — will drift, and when they do the offline suite keeps passing against the wrong one. A reviewer argued the double should therefore be reduced to route control flow only, with the SQL suite as the sole authority on resolution semantics. Not taken, because this repo's testing posture is offline-first by design (the limiter is disabled under pytest, durable chat history runs on an in-memory double for the same reason) and the SQL suite is hand-run against the live project, so demoting the double would leave resolution with no coverage in CI at all — a worse failure than drift. The mitigation is procedural and belongs in _Verification_: `supabase/tests/quota_behaviour.test.sql` is the **authority** on resolution semantics, the Python double is a convenience, and any change to the resolution order or the window clause must be made in the SQL first and the double second, in the same commit, with the SQL suite re-run. Where they disagree, the database is right.

  `AdminActionRefused` codes mirror §1.5/§1.6. Wired in `app.py` `_register_testing_doubles` as `app.config["_testing_quota_backend"]` and `app.config["quota_backend"]` (a callable, resolved per call, like `chat_backend`).

- **`IdentityFlags` unchanged.** Labels and limits are never cached on the identity object.
- **`GET /api/identity`** gains `quota: {used, limit, remaining, resets_at, tier: {key, label_en, label_ar}, override, override_expires_at}` from `current_app.config["quota_backend"]().status(user_id)` — the per-call factory that resolves to the in-memory double under TESTING, the `chat_backend()` shape, and deliberately **not** the route's existing `get_admin_backend()` call, which is `None` in every test and would leave `quota` null throughout the suite (the browser suite's `test_account_browser.py` asserts the standing line reads `Free`, and after §6.3 that text comes from this field). In a third independent `try`/`except` (the docstring's own rule: one failure must not blank the others); on failure `quota: null`. Nothing about any other account.
- **`admin_store.py`** — `AdminBackend` gains `set_reader_quota(user_id, *, tier, override, starts_at, expires_at, reason, actor)`, `list_tiers()`, `create_tier`, `update_tier`, `delete_tier`; `_refusal_from` learns the `TQ00x` SQLSTATEs (`TQ007` included); `InMemoryAdminBackend` mirrors them and shares **both** the tier table and the override table — windows and all — with `InMemoryQuotaBackend` (one dict each, injected), so a test that assigns a tier or sets a windowed override sees the changed limit on the next claim, and sees it stop applying when the window closes.

---

## 5. Admin console

### 5.1 Tiers tab (new)

`web/templates/admin.html`: a **sixth** tab button (the console already ships five — Overview, Settings, People, Activity, Notifications, `admin.html` ~122-141) and `#panel-tiers` with `#tiers-body`, aria wired like the others; `page.admin.tabs.tiers` — labelled **Tiers** / **الفئات** (owner decision, 2026-09-03, closing §13 Q6; "groups" was the owner's own earlier word and was considered, but the console already calls the column `tier` and two names for one thing is how a console starts lying). The tab button's glyph is rendered **server-side** by Jinja (`{{ icon('…', 15) }}`, like its five siblings), so a new one must exist in `web/utils/icons.py`'s primary `ICONS` dict — **not** `ADMIN_RUNTIME_ICON_NAMES`, which is only for glyphs `iconMarkup()` draws in the browser and which an earlier draft of this line wrongly named. Simplest is to reuse a glyph already in `ICONS` and add nothing. `static/js/admin.js` calls `initTiersTab(services)` beside the existing inits. `static/js/admin/handlers.js` `initTiersTab`: load `services.tiers()`, render a table (key, **one** label resolved against the console language — see §14.1, which reverses this line's original "label EN, label AR" — daily limit, members, ordering, edit/delete), an inline create/edit form (key immutable after create; `free` shows no delete control), `window.confirm` on delete with the member count in the copy, `loadAudit(services)` after every successful save (the registrations handler's reason). `static/js/admin/ui.js` `renderTiers(tiers, {editingKey})`; labels via `textContent`. `static/js/admin/services.js`: `tiers`, `createTier`, `updateTier`, `deleteTier`. Routes in `admin.py`: `GET /admin/api/tiers`, `POST /admin/api/tiers`, `PATCH /admin/api/tiers/<key>`, `DELETE /admin/api/tiers/<key>`; validation in Flask before the RPC (key regex, label lengths, integer ≥ 0) returning `422` with the same machine codes the RPC uses; `AdminActionRefused` → `409 {error: code}`. `test_admin_page.py`'s route-gate test only covers GET routes (notification plan finding 16), so the three mutations get their own 401/403 tests.

### 5.2 Account detail: tier and override

`renderAccountDetail` gains a **Quota** section between the profile form and the actions card (Zone 2b): the tier as a `<select>` fed by `services.tiers()`, the override as a numeric input with a "Use tier limit" clear control, **two optional datetime fields for the override's window** (blank = in force until cleared, which is the default and the common case), a required-when-set reason field (mirroring the disable-reason rule — enforced at the route, as `admin.py` already enforces the disable reason, not in the RPC; it returns **`quota_reason_required`**, not the existing `reason_required`, whose catalogue string is hardcoded to "A reason is required to disable chat access." / «السبب مطلوب لتعطيل الوصول إلى المحادثة.» at `en.yaml:561` / `ar.yaml:353` — reusing the code would tell an operator setting an allowance that chat access cannot be disabled), today's usage as `used / effective limit` with the reset time, and one Save. When a window is set the section states in words what it means — "500 a day until 30 September" — and a window that has passed renders as "expired on {date}, now using the tier limit" rather than as a live number, because the row is still there (§1.2, expiry-on-read) and showing its value would be a lie. **That sentence carries a date, and §14.2 records why interpolating one is not as simple as it looks.** `PUT /admin/api/users/<id>/quota` `{tier, daily_message_limit_override: int|null, override_starts_at: iso|null, override_expires_at: iso|null, reason?}` — a PUT of the whole quota state, every key always present, because the RPC's nulls are asymmetric (`p_tier null` = unchanged, override `null` = clear) and a partial body would turn "I did not send it" into "clear it" → `backend.set_reader_quota` → `admin_set_reader_quota`; `_evict_identity_caches(user_id)` before returning; then `openAccount(userId)` and `loadAudit`. Hidden when `has_profile` is false (the RPC refuses `AD003` anyway). Disabled for self? No: changing your own allowance is not a privilege escalation and `AD001` does not apply; the audit row records it.

### 5.3 Audit labels

`static/js/admin/ui.js` action map gains `tier.create`, `tier.update`, `tier.delete`, `user.tier_change`, `user.quota_override_change` → `runtime.admin.audit.action*` keys.

### 5.4 Notification composer

`target_tier` becomes a `<select>` populated from `services.tiers()`; `admin.py`'s `_validate_notification_targeting` checks the key exists via the backend (`422 invalid_target_tier`, the existing code). The audience preview and `admin_create_notification` are unchanged in signature.

---

## 6. Reader-facing behaviour

### 6.1 The exhausted notice

`handlers.js` `processChatRequestInternal`, in the outer `catch`, gains a branch **before** the generic fault path and beside `account_disabled`:

```js
if (error?.code === 'quota_exhausted') {
  UI.removePendingUserTurn(queryText); // the bubble addMessage drew before the request
  UI.showQuotaNotice(error.quota); // {limit, used, resets_at}
  UI.restoreComposerDraft(queryText); // only if the composer is empty; a newer draft wins
  RobotStateManager.resetToIdle();
  return; // no toast, no error face, no genericError bubble
}
```

`services.js` attaches the parsed 429 body as `failure.quota` alongside `.status`/`.code` in **both** `streamChatRequest` and `sendChatRequest` (the blocking fallback `handlers.js` `blockingChat` uses), transport only, no view import. `processChatRequestInternal` draws the reader's own bubble with `UI.addMessage(queryText, 'user')` before the request leaves (`handlers.js` ~306), so on a 429 that bubble is removed first: left in place it would sit as an unanswered turn, count for `isTranscriptTurn`, and duplicate the text now back in the composer. `UI.showQuotaNotice` (`ui.js`) renders one `div.quota-notice#quota-notice[role=note][data-non-turn][aria-live=polite]` inside `#messages`, replacing any existing one (keyed by `resets_at` so repeated sends do not stack), with a dismiss control like the two existing Notices. It registers with the `NoticeCoordinator` (`ui.js` ~165-183) as the third notice in `#messages`, and `Handlers.clearReaderScopedUI` gains an explicit `UI.hideQuotaNotice()` beside `hideProfileCompletionNotice()`, because `clearTranscript` detaches turns only. **Copy — DECIDED by the owner, 2026-09-03.** State the number, in both languages:

- EN — `runtime.chat.quota.body`: "You've asked all {limit} of today's questions. Your allowance resets at {resets_at}."
- AR — `runtime.chat.quota.body`: «لقد استخدمت كل رصيدك اليوم ({limit}). يُعاد فتح رصيدك في {resets_at}.»

**`{limit}` is always interpolated, never written into the string.** The owner's instruction is explicit and the reason is structural: the tier limit is operator-editable from the console, so a hardcoded "200" becomes a lie the first time somebody changes it — in a catalogue file, where nothing would catch it. `test_frontend_architecture.py`'s banned-literal check is the natural place to pin that no digit sequence appears in either `quota.body`.

**When a windowed override is in force, the notice states the override's number, not the tier's.** This costs nothing — the 429 body already carries the resolved `limit` from the claim, which §2 resolves through the override and its window — but it must be said, because the reader whose promotion grants 500 a day must not be told they have used all 200. The counter (§6.2) reads the same resolved field for the same reason.

`{resets_at}` is rendered through the timestamp formatter that today lives as `UI.Notifications._formatTimestamp` (`ui.js` ~1688; `toLocaleString(I18n.lang, {dateStyle, timeStyle})`), hoisted to a module-scoped `formatTimestamp(iso)` used by both callers rather than reached across sub-objects; the Arabic bidi-mark problem is handled where that helper's own comment says it is, by the caller rendering the value in `<time datetime dir="auto">`; the ISO value rides a `<time datetime>` for tests. `{limit}` is a machine value and follows DESIGN.md's machine-value rule (isolated, not `dir="ltr"` on a block).

CSS in `components.css`, next to the history notice: `.quota-notice` reuses the Notices shape (sunken fill, `rule-200` hairline, 3px radius, muted ink, the inset 2px inline-start pill) with the pill in `--confidence`. Never `--danger`, never `.stream-note`. Logical properties only. `ASSET_VERSION` bump.

### 6.2 The quiet counter

`web/templates/index.html`: `<p class="composer-quota" id="composer-quota" hidden aria-live="polite"></p>` as a sibling _after_ `.composer` inside `footer.input-area` — never inside `.composer`, which is a flex row and would take it as a fourth item on the input line — muted ink, `--fs-100`. `UI.updateQuotaCounter(quota)` shows it only when `remaining <= max(3, ceil(limit * 0.2))` — 40 at the shipped 200, **DECIDED 2026-09-03** — text `runtime.chat.quota.counter` ("{remaining} of {limit} questions left today · resets {resets_at}") or `counterOne`. **The threshold is a constant in `ui.js`, not a setting.** No `config.yaml` key, no `app_settings` row, no console control: a display threshold is not a product setting for four accounts, and wiring one now would add a cache slot, a route and a test for a number nobody has evidence to choose. It is revisited after Commit C, against real `usage_daily` rows. Hidden otherwise; hidden otherwise; shown with `remaining = 0` after a 429. It writes `textContent` only when `remaining` or `resets_at` actually changed, so the `aria-live` region does not re-announce an unchanged number on every answer. Fed from: `/api/identity` at sign-in (`app.js`'s `fetchIdentityWithRetry` `.then`, guarded by the same `identityCheckId` and `user_id` checks that guard `renderAdminAffordance`), every `done` frame, every `handle_chat` response, and every 429 body. Never a re-fetch of identity after an answer. Cleared by `Handlers.clearReaderScopedUI` on sign-out.

### 6.3 Account standing line

`static/js/account.js` passes `identity.quota` to `renderStanding`; `account/ui.js` renders `tier` from `quota.tier.label_en` / `label_ar` by `I18n.lang` (falling back to the key when `quota` is null), and adds "{used} of {limit} questions today" and the reset time.

**A windowed override is shown to the reader — DECIDED 2026-09-03 (§13 Q8).** When `quota.override_expires_at` is non-null, the standing block adds one line: `runtime.profile.account.quotaUntil` — "{limit} questions a day until {date}" / «{limit} سؤال يوميًا حتى {date}». The reason is support load, not generosity: on the morning the window closes the reader's allowance silently drops to the tier's number, and a reader who was never told it was temporary reads that as a bug and opens a ticket. Telling them once, where they already look at their standing, costs a field that `/api/identity` carries anyway and a copy key in each catalogue. `{date}` goes through the same hoisted `formatTimestamp` as every other instant, and rides a `<time datetime dir="auto">` for the Arabic bidi reason §6.1 gives. No line at all when the override is unwindowed or absent — an open-ended allowance has no date to promise. `profile.account.tierFree` / `tierStaff` (renamed from `tierInternal` in the same commit, §1.1) are removed from both catalogues (neither is frozen; `test_frontend_architecture.py`'s banned-literal list gains nothing because no literal is being replaced).

---

## 7. i18n

Both catalogues, together, per key. Nothing new at the top level of `runtime.*` (collision #3).

- `runtime.chat.quota.*`: `title`, `body`, `dismiss`, `counter`, `counterOne`, `resets`
- `runtime.profile.account.*`: `tierUnknown`, `quotaToday`, `quotaResets`, `quotaUntil` (the windowed-override line, §6.3)
- `runtime.admin.tiers.*`: `heading`, `hint`, `key`, `keyHint`, `labelEn`, `labelAr`, `dailyLimit`, `ordering`, `members`, `add`, `edit`, `delete`, `save`, `cancel`, `confirmDelete`, `saved`, `deleted`, `empty`, `loadFailed`, `saveFailed`, `deleteFailed`, `duplicate_key`, `no_such_tier`, `tier_in_use`, `default_tier_protected`, `invalid_limit`, `invalid_labels`, `invalid_key`
- `runtime.admin.account.*`: `quotaHeading`, `tierLabel`, `overrideLabel`, `overrideHint`, `useTierLimit`, `reasonLabel`, `usageToday`, `resetsAt`, `saveQuota`, `quotaSaved`, `quotaSaveFailed`, `no_such_tier`, `invalid_limit`, `quota_reason_required`, `overrideStartsLabel`, `overrideExpiresLabel`, `overrideWindowHint`, `overrideInForce`, `overrideScheduled`, `overrideExpired`, `invalid_window`
- `runtime.admin.audit.*`: `actionTierCreate`, `actionTierUpdate`, `actionTierDelete`, `actionUserTierChange`, `actionUserQuotaOverrideChange`
- `runtime.admin.notifications.composer.tierSelectEmpty`
- `page.admin.tabs.tiers`, `page.chat.quotaCounterAria`
- Removed: `runtime.profile.account.tierFree`, `tierStaff` (`tierInternal` before §1.1's rename), and `runtime.admin.notifications.composer.tierPlaceholder` (the text input it belonged to becomes a select; a key read by nothing is the failure mode `test_frontend_architecture.py`'s docstring names)

Tier labels themselves are data (`tiers.label_en`/`label_ar`), edited from the console, and never pass through the catalogue.

---

## 8. Security and privacy checklist

1. `tiers`, `reader_quota_overrides`, `usage_daily`: RLS on, zero policies, `revoke all` from every role including `service_role`; every path a `security definer` RPC with `set search_path = ''`, revoked from `anon`/`authenticated`/`public`, granted to `service_role` only. Three new rows in the standing-findings table; `supabase/tests/privileges.test.sql` and `function_acls.test.sql` extended.
2. No browser-direct write to tier, override or usage state. `profiles.tier` keeps its column `REVOKE` and trigger; the override is not on `profiles` at all.
3. `p_user_id` for the reader RPCs always comes from `g.identity`, never from the body.
4. Every tier/override mutation revalidates the actor inside the membership advisory lock and writes its audit row in the same transaction.
5. `/api/identity` returns only the caller's own numbers and their own tier's labels. `admin_get_user` returns counts and policy, never question text; no route lists another reader's usage.
6. `usage_daily` holds `(user_id, day, used)` and nothing else — no text, category, conversation id or timestamp of individual questions — so it is not the question log `TODO.md`'s "Know what people actually ask" entry wants and must not grow into one.
7. Account deletion: `usage_daily` and `reader_quota_overrides` cascade; `set_by` sets null; `profiles.tier` restricts tier deletion. `chat_sessions.owner_id`'s missing FK is neither fixed nor imitated.
8. The 429 body carries `Retry-After` and `no-store`; the client retries neither 429 nor any mutation.
9. A zero limit refuses the first claim of the day (the explicit guard in §2).
10. `_rate_key` never keys an authenticated reader on IP; the fallback order is identity → token hash → IP.

---

## 9. Rollout order

Five commits, schema first (README: schema before code).

> **BUILT — Commits A–E, 2026-09-03/04.** Nine migrations live (`20260903194624` …
> `20260903200806`), each filed in `supabase/migrations/` under the version
> `list_migrations` reports. Advisors: 11 `rls_enabled_no_policy` INFO (the 8 standing plus
> the 3 new tables, all registered in `supabase/README.md`) and 8 `unused_index` INFO (6
> standing plus the 2 new FK indexes) — no warnings, nothing unexpected. Behaviour was
> exercised against the live database rather than only applied: all four resolution legs,
> in-window / expired / scheduled overrides, the zero-limit guard refusing a first claim,
> exhaustion at the boundary, the refund freeing capacity, a mid-day lower refusing without
> rewriting `used`, a release against the wrong day as a no-op, and all eight admin refusal
> codes.
>
> Gates at completion: **947 non-browser and 263 browser tests passing**, ruff and eslint
> clean, prettier and markdownlint clean, `ASSET_VERSION` at `warm66`. mypy is blocked by a
> pre-existing environment mismatch (numpy's stubs use 3.12 syntax against the pinned
> `python_version = 3.10`), verified identical on a clean tree — so it gave this work no
> coverage either way.
>
> **Three defects were found only by RUNNING it, and all three are fixed in the spec above:**
>
> 1. The claim's `on conflict (user_id, day)` is ambiguous, because the function returns a
>    column named `day`. PL/pgSQL defers parsing embedded SQL until first execution, so it
>    created cleanly, applied cleanly and the advisors were green — then raised `42702` on
>    the first real call. Three reviewers had read that SQL and none caught it. Naming the
>    constraint removes the identifier entirely (§2).
> 2. The in-memory double stored the override window as the ISO string the route sends and
>    compared it against a `datetime`, raising `TypeError` at claim time. Found by driving
>    the console route end to end, not by unit-testing the double against itself (§4).
> 3. `_register_testing_doubles` gave the admin double its own tier dict, so a tier assigned
>    through the console was invisible to the very next claim — the exact "console and chat
>    route disagree about one account" failure this feature exists to prevent. They share
>    one dict now.
>
> Two things were corrected in passing: the Tiers tab loads on first activation rather than
> on console boot (an operator who never opens it should not pay for the request, and its
> failure must not raise a toast over whichever tab they are actually using), and the
> notification composer's tier is now a select validated against the catalogue — a mistyped
> key used to broadcast to an audience of nobody and report success.
>
> **Verified against production, 2026-09-04.** `scripts/smoke_real.py` run in both languages:
> 0 hallucinated citations, 0 legacy prose citations, first token at 1.27s. Its new DAILY
> ALLOWANCE section exercised the three real RPCs (status → claim → release, refund verified
> to land, 0 consecutive faults), and the four admin tier RPCs were driven against the live
> project too — create, update and delete round-tripped with their audit rows, and both
> `TQ004` (the `free` tier is protected) and `TQ002` (no such tier) refused correctly.
> `resets_at` came back as `21:00Z` — midnight Riyadh.

**Commit A — schema and the limits that exist today.** Migrations 1.1 (two files) through 1.8 applied via `apply_migration` in order; after each: `list_migrations` (rename the file), `get_advisors` security + performance (expect exactly the three new `rls_enabled_no_policy` rows, and the `chatbot_settings` one gone), `supabase/tests/*.test.sql` by hand. `_rate_key`, `key_func` on `chat_limit`, the five `view_functions` reassignments, `test_rate_limit_keys.py`, the `test_registrations_pause.py` comment fix. `TODO.md`: the five-limits Known bug entry written and closed in this same commit's note. **`docs/data-policy-decisions.md` is corrected here, not in Commit E**: its `STATUS` line says `PROPOSAL for questions 1-3` and §3 is headed _The recommendation_, which is self-consistent only until 1.8 drops the table. The moment the destructive migration lands, the document is describing as an unexercised proposal a thing that has already happened — so §3 and the `STATUS` line take the same "IMPLEMENTED, dated" treatment question 4 already carries, in the commit that makes it true.

**Commit B — the claim.** `quota_store.py`, `config.yaml` key, wiring, the view-body claim and refund in both chat routes, the resolution's window clause, `done`/response `quota`, `/api/identity` `quota`, `admin_get_user` consumer in `admin_store.py`. Backend tests (§10).

**Commit C — reader UI.** Notice, counter, account standing line, catalogues, CSS, `ASSET_VERSION`. Browser tests.

**Commit D — console.** Tiers tab, account quota section, composer select, audit labels, admin routes and `admin_store` methods, catalogues. Admin tests, browser tests.

**Commit E — the documents that only the finished feature makes false.** §11 says the documents "must ship together" with the code that falsifies them, and `CLAUDE.md`'s _Writing things down_ makes that a rule ("When your change makes a document wrong, fix the document in the same commit"), so the split is by **which commit makes which sentence false**, not "docs last". **`ARCHITECTURE.md`'s rate-limit table and `supabase/README.md`'s _Current shape_ and standing findings move to Commit A**, with the migrations and the re-keyed limits that falsify them; `PRODUCT.md`'s allowance paragraph moves to **Commit B**, with the enforcement it describes. Leaving three commits in which the architecture document knowingly lies about rate limiting is the failure this repo archived eight thousand lines to stop repeating. What genuinely belongs last: `docs/ARCHITECTURE.md` 's _Deliberately not built_ (token credits, time-windowed access, the parked pool), `DESIGN.md` _Notices_ (the quota notice as the third instance of the shape), `TODO.md` (entry shortened to point here; retention entry gains `usage_daily`; the claim-idempotency rule from §12 recorded under it), this file's `STATUS` line. `docs/data-policy-decisions.md` is **not** here — it moved to Commit A, with the migration that makes it true. `CLAUDE.md` is not expected to change; if it does, bump `APP_VERSION` per its rule 9.

---

## 10. Test plan

Offline first: every Python test runs against the in-memory doubles; the SQL tests run by hand against the live project, because a mock cannot prove a grant.

**`web/tests/test_quota.py`** (new): claim allowed / exhausted / zero-limit-refuses-first-claim; a zero limit refuses the first claim of the day and is distinct from `is_disabled` (the reader still authenticates and still loads history); release never below zero and only when not spent; **a second `_release_daily_message()` in one request decrements once** (the `released` guard, §3.2); `Asia/Riyadh` rollover via the `_now` hook (a claim at 23:59 Riyadh and one at 00:01 Riyadh fall on different days; two claims either side of UTC midnight do not); override beats tier beats **the live `free` tier** beats the shipped default; **an override outside its window does not beat anything** — before `starts_at` and after `expires_at` the tier limit applies, at `starts_at` exactly it does, and an unwindowed override behaves as it always did (all four driven through the `_now` hook, no sleeping); a profileless account tracks an edit to the live `free` tier and does _not_ sit on the config number; the shipped default fires only with no `free` row and logs a warning when it does; mid-day raise and lower semantics; **an override that expires between two claims takes effect on the next claim with no sweep, job or restart** (the expiry-on-read rule, §1.2); **a limit lowered between resolve and increment does not retract a claim already in flight** (the stated weaker rule, §2 — driven through the double's seam, not a real race); `test_seed_matches_shipped_default` (regex the seed migration for **both** seeded rows' numbers — `'free'` and `'staff'` — and compare each to `config.get("server","quota",{})["daily_messages_default"]`, so neither row can drift from the config key unnoticed).

**`web/tests/test_chat_stream.py`** (extend): exhaustion is a 429 before any frame with `stream_response.call_count == 0`; `Retry-After` present; retrieval failure releases; **a generator that raises on its first `next()` — the provider-error shape, since `_build_messages` and `chat.completions.create` both run in the body — releases**, while one that raises after yielding a token does not (this pair is the §3.2 boundary, and the first half fails against a `spent` flag set before the loop); `done` carries `quota`; `allow_create=false` 404 spends nothing; a 400 spends nothing; backend fault → answer streams with `quota: null`.

**`web/tests/test_chat_api.py`** (extend): the blocking route's 429 shape and no model call; alternating routes share the allowance; **a provider failure on the blocking route refunds** — the case that fails against today's `generate_response`, which swallows the exception and returns apology prose, and the reason §3.2 changes that method before wiring the claim to this route. Without this test the blocking path reaches production charging readers for apologies while the streaming suite stays green.

**`web/tests/test_rate_limit_keys.py`** (new): §3.7.

**`web/tests/test_identity_roles.py`** (extend): `quota` shape, bilingual labels, `quota: null` degradation, nothing about another account.

**`web/tests/test_admin_tiers.py`** (new) and **`test_admin_users.py`** (extend): CRUD, every refusal code including `TQ007`, a window round-tripping through the route and the audit diff carrying it, `free` undeletable, `tier_in_use`, 401/403 on every route including the non-GET ones, actor demoted between gate and RPC (`InMemoryAdminBackend._require_admin_actor`), audit before/after, `_evict_identity_caches` called, composer rejects an unknown tier key.

**`web/tests/test_admin_page.py`** (extend): the tab is in the pinned catalogue subtree, `page.admin.tabs.tiers` never reaches the landing page.

**`web/tests/test_frontend_architecture.py`** / **`test_rtl.py`**: unchanged assertions must still pass (transport in `services.js`, failures in `handlers.js`, Arabic parity on every new key).

**SQL — `supabase/tests/quota_behaviour.test.sql`** (new, in the always-rolling-back `do` block shape): resolution order, zero limit, exhaustion, release floor, mid-day change, an override inside / before / after its window and an unwindowed one, `get_reader_quota` and the claim agreeing on the same window boundary, `TQ007` on a backwards or already-expired window, tier delete refused while in use and allowed when empty, `free` protected, `admin_set_reader_quota` audit rows and diff rule; **`privileges.test.sql`** / **`function_acls.test.sql`** (extend): the three tables and eight functions. Specifically, `function_acls.test.sql` asserts the actor gate by matching `prosrc` against a **hardcoded seven-name array** (`admin_write_settings`, `admin_set_user_flags`, `admin_update_profile`, and the four notification RPCs, ~line 173). The five new mutating admin RPCs — `admin_create_tier`, `admin_update_tier`, `admin_delete_tier`, `admin_set_reader_quota`, and any later pool RPC — must be **added to that array**, or one of them can silently ship without calling `admin_actor_email` and still pass a green suite. Extending a fixed list is easy to forget precisely because the test keeps passing. Concurrency is proven by two `execute_sql` sessions racing the claim at `limit = 1` — a mock cannot show a row lock — and by a second, differently shaped race: session A opens a transaction and resolves, session B runs `admin_set_reader_quota` to a lower limit and commits, session A completes its claim. The assertion is the documented outcome, not the intuitive one: A's claim **succeeds** against the limit it resolved, and B's new limit binds from A's next claim onward (§2). It is written down because a future reader who finds it surprising should find it deliberate.

**Browser — `web/tests/test_quota_browser.py`** (new, `-m browser`, against `conftest.py`'s mock at `?testing=true`; the session-scoped live server shares one `InMemoryQuotaBackend` across the whole suite, so its testing identities are seeded with a large limit and the exhausted state is produced by the Playwright route mock returning a 429 body, not by spending the shared allowance): the notice renders in EN and AR with the `--confidence` pill and no `--danger` colour, `data-non-turn`, dismisses, does not stack; the composer stays enabled and keeps the draft; no toast and no error mascot; the counter appears at the threshold and updates after an answer; the account standing line shows the tier label from the API. **`test_admin_browser.py`** (extend): tier create/edit/delete, `free` has no delete, account tier select, override set and clear, a window set and the section reading it back in words, an expired window rendering as expired rather than as a live number, usage shown.

---

## 11. What this disturbs

Roughly notification-center scale: nine migrations, one new console tab, one new service module, two new test files plus extensions to nine, and three documents that describe rate limiting today.

- **`web/api/app.py`**: both chat routes gain a claim, a refund flag and a 429 path; `chat_limit` gains a key; five limit registrations change shape; `/api/identity` gains a field; the `done` frame gains a field. The frame-order test and the deep-link contract test both change.
- **`web/api/admin.py`, `web/services/admin_store.py`**: four tier routes, one quota route (carrying the override's window), six backend methods, new refusal codes; the composer's tier validation; **the audit route's `target_type` whitelist** (`admin.py` ~1031 rejects anything but `"user"` and `"settings"` with a 422, so the `target_type='tier'` rows §1.5 writes would be unfilterable in the console the moment they exist — `"tier"` joins the tuple in Commit D, with the audit rows that need it).
- **`static/js`**: `modules/services.js`, `handlers.js`, `ui.js`; `account.js`, `account/ui.js`; `admin.js`, `admin/{services,handlers,ui}.js`; `templates/index.html`, `admin.html`, **`account.html`** (the standing block carries only `#standing-tier` today, ~151-154; the usage line and reset time need their own elements rather than text concatenated into the tier cell); `components.css`; `ASSET_VERSION`.
- **Catalogues**: ~62 new keys in each language once the copy keys settle, and **two removed** (`tierFree`, `tierStaff`) — tier labels become data in `tiers.label_en`/`label_ar`, so this count does not grow with the number of tiers an operator creates.
- **The `internal` → `staff` tier rename** (§1.1): fourteen fixture, seed and label lines across `app.py`, `admin_store.py`, `account/ui.js`, both catalogues and six test files, all of which must move in Commit A **before** the FK migration, since afterwards the same rename is a data migration. The SSE error code `"internal"` and `processChatRequestInternal` are the same English word and are not touched.
- **Decisions reopened**: the tier-matrix deferral (superseded, dated above); the notification composer's free-text tier (now a select); the account page's hardcoded tier labels (now data); the chat burst limit's subject (IP → reader, so an office no longer shares 15/minute and a single reader on two networks no longer gets 30); the five routes that were silently unlimited (now limited — an operator who relied on that will notice); **`_account_rate_key` and `_admin_notification_rate_key`'s subject** (session → account, reversing this plan's own first ruling — see §3.5: one reader on two devices had two export budgets, and one admin on two sessions had two broadcast budgets).
- **Things that do not change but must be re-verified**: `chat_sessions.owner_id` still has no FK; `profiles_guard_privilege_columns` is untouched; `get_identity_flags` is untouched; `SettingsService` is untouched.
- **Must ship together**: schema before code (A before B); the catalogue and the UI (C and D each carry their own keys); the docs with the last code commit, because `ARCHITECTURE.md`'s rate-limit table and `PRODUCT.md`'s paragraph become false the moment Commit A lands.

---

## 12. Deliberately not done

### The fixed promo pool — designed 2026-09-03, deliberately not built

Worked out in full on the day this plan was written, and parked here rather than in the build, because the design is worth keeping and the feature is not worth shipping yet. Recorded with its defects already corrected, so whoever picks it up starts from a version that applies.

**What it is.** A grant of _N bonus messages_ to one reader, usable across a window, drawn **only after** the daily allowance is exhausted — headroom on top of the meter, not a replacement for it. That composition is the right one: the daily quota stays the steady-state guard and the pool is reachable only when the guard has already said no.

**Why not now.** Nothing in this plan is built yet, and the plan is already notification-center scale — nine migrations, five commits, ~60 keys per language. The pool adds a table, two migrations, two admin RPCs, two SQLSTATEs, a second console block, a two-row counter, and — the real cost — a **second atomic path inside the claim plus a bucket-tagged refund**, making the most delicate SQL in the plan roughly twice as delicate. All of that for four accounts, all `free`, all at 200 a day, none of whom has ever met a limit. The windowed override taken above covers most of the same operator need ("more, for this person, for a while") at the cost of two nullable columns. Revisit once the meter has produced a month of real numbers and the question "a higher rate for a while, or a bag of extras?" has an evidence-backed answer instead of a guess.

**The schema, corrected.**

```sql
create table public.quota_grants (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  granted_total integer not null check (granted_total >= 1),
  used          integer not null default 0 check (used between 0 and granted_total),
  starts_at     timestamptz not null default now(),
  expires_at    timestamptz not null,
  revoked_at    timestamptz,
  revoked_by    uuid references auth.users(id) on delete set null,
  granted_by    uuid references auth.users(id) on delete set null,
  reason        text check (reason is null or length(reason) <= 500),
  created_at    timestamptz not null default now(),
  constraint quota_grants_window_chk check (expires_at > starts_at)
);
create index quota_grants_user_open_idx on public.quota_grants (user_id, expires_at desc)
  where revoked_at is null;
```

**Do not enforce "one open grant" with a partial unique index.** The obvious form —

```sql
-- WRONG: fails at apply time
create unique index quota_grants_one_open on public.quota_grants (user_id)
  where revoked_at is null and expires_at > now();
```

— is rejected outright: `now()` is `STABLE`, and Postgres requires index predicates to be `IMMUTABLE` (`42P17: functions in index predicate must be marked IMMUTABLE`). Even if it applied it would prove nothing, because a predicate is evaluated when the row is written and can never notice a grant ceasing to be open as the clock moves. Two workable choices: an `exclude using gist (user_id with =, tstzrange(starts_at, expires_at) with &&) where (revoked_at is null)`, which is stronger (it forbids _overlapping_ grants, not merely simultaneous ones) but needs the `btree_gist` extension enabled and checked first; or enforce it inside `admin_grant_reader_pool`, which already holds `pg_advisory_xact_lock(hashtext('sfda.admin_membership'))` and so gets the check for free. Prefer the second unless overlapping grants are a real product concern.

**The claim, if it is ever built.** Resolve the daily limit exactly as §2 does; try the daily upsert; if that returns no row, try the grant in **one** statement — not a `select` for the id followed by an `update` against it, which reintroduces the resolve-then-act gap §2 spends a paragraph on:

```sql
update public.quota_grants g set used = g.used + 1
 where g.id = (select id from public.quota_grants
                where user_id = p_user_id and revoked_at is null
                  and starts_at <= now() and expires_at > now()
                  and used < granted_total
                order by expires_at limit 1 for update)
returning g.id, g.used;
```

The return shape gains `bucket ('day' | 'grant')` and `grant_id`, the claim carries the bucket on `QuotaClaim`, and the refund dispatches on it — the day-scoped release for `day`, `update quota_grants set used = greatest(0, used - 1) where id = p_grant_id` for `grant` — under the same first-token boundary and the same `released` guard (§3.2).

**The rule that must not be got wrong: a daily limit of 0 blocks the grant too.** Owner question 3 decided that 0 means "may sign in, read and browse, but may not ask today", deliberately distinct from `is_disabled`. If the grant simply fires whenever "the daily allowance is exhausted", a reader silenced with 0 keeps asking on their grant, and the operator who set the 0 has been overruled by an operator who set a pool last week — silently, with the conflict invisible in the console. The two states are different and the SQL must say so: **`daily_limit > 0 and exhausted`** draws from the grant; `daily_limit = 0` refuses, pool or no pool. Zero means zero.

**Still open if it is revived:** whether leftover pool at expiry simply vanishes (it should — that is what makes it a promotion); whether the reader is told about the pool at all, or only sees a larger number; whether grants may stack.

**Per-claim idempotency against a replayed `client_request_id`.** The claim is keyed on `(user_id, day)` and carries no request id, so a request that reaches the model and then fails in transport would, if the client re-sent the **same** `client_request_id`, charge the allowance twice while `chat_append_turn`'s `unique (session_id, client_request_id, role)` quietly kept the original turn. The turn is idempotent; the claim is not.

This is latent, not live, and the distinction decides the disposition. The shipped client mints a fresh id per submission (`handlers.js:342`) and has no chat retry path at all — the streaming/blocking choice at `:361` is a static capability check (`CONFIG.STREAMING && 'body' in Response.prototype`), not a runtime fallback, and `case 'retry'` at `:1000` reloads the session list. `_persist_turn` says as much where it logs the replay: _"the browser mints a fresh id per submission, so today it should not"_ (`app.py:1249`). What makes it worth writing down is that the **contract** anticipates the opposite: `app.py:2450` calls the id "reused across retries — that is the whole point", and `_InFlightGenerations` counts holds because "two tabs, or a retry". The day a retry feature is built on that contract, this hole opens with it.

The obvious cheap fix does not work and should not be reached for. A `usage_daily.last_claim_request_id` column with `... where u.last_claim_request_id is distinct from excluded.last_claim_request_id` holds **one** slot per `(user, day)`, so it catches only an immediately consecutive replay: send A, send B, retry A, and A charges twice. Doing it correctly needs a claim ledger keyed by request id — a table with `unique (user_id, day, client_request_id)`, its retention and its index — or a replay probe before generation, which is the reserve-shaped design `_persist_turn`'s comment records as already rejected. A third reviewer, given only the plan and the repo, independently proposed that same ledger shape and the same rejection of the single-slot column, which is the strongest evidence available that it is the right fix and that the cheap version is not one. **The rule instead: any commit that adds a client-side chat retry reusing `client_request_id` must ship claim idempotency with it.** Carried as a `TODO.md` line under the quota entry rather than built here.

Token credits (owner ruling, on technical grounds a message count does not share). Time-windowed _access_ as such — the windowed override (§1.2) grants a time-boxed **allowance**, not time-boxed sign-in. A configurable default tier (structural `free`, ruling 5). Per-tier burst limits (the burst limit is anti-hammering, not policy; one value). Re-keying `history_api`/`sessions_api` from IP to reader (separate decision; note in `TODO.md`). A usage purge (retention entry). Admin-role exemption from the quota (put the operator in a tier with a high limit; an exemption is a second resolution rule nobody can see in the console). A per-account "unlimited" override (a tier with a large limit does it; three-valued override semantics are not worth their tests). Realtime push of the counter to other tabs (each tab updates on its own next answer). Folding `/api/identity`'s three RPC round trips (`touch_last_seen`, `get_identity_flags`, now `get_reader_quota`) into one — a real optimisation for a route called once per sign-in, recorded as a follow-up in `TODO.md` rather than done here, because `20260822231726` deliberately narrowed `get_identity_flags` and widening it is its own decision.

---

## 13. Questions for the product owner

**All eight are now answered**, on **2026-09-03**, before anything was built. The numbering is unchanged — other sections cite these by number — and each question is kept beside its answer, because the question is the record of what was weighed. Only question 7 (retention) is deliberately left to an existing `TODO.md` entry rather than answered here.

1. **DECIDED 2026-09-03 — the shipped default number** for `free` and `staff`: **200 for both, and deliberately identical.** The design pass proposed reusing today's `per_day: 200`; the research pass proposed 50. One `config.yaml` key seeds both rows and the test pins both to it (§4).

   **Why not differentiate `staff` now, since the whole point of tiers is that they differ?** Because there is _zero_ production evidence about usage — four accounts, none of which has ever met a limit — and any number picked for `staff` today would be a guess dressed as a policy. The Tiers tab (Commit D) makes raising it a one-click console edit: no migration, no deploy, no code review. So the cost of waiting is one console visit, and the cost of guessing is a number that looks authoritative and is not. When the meter has run and `usage_daily` has something to say, `staff` goes up **by console, not by code**. Note this is _not_ a dark launch — see §1.1: chat has no daily ceiling today, so 200/day is real new enforcement, just set well above the waterline.

2. **DECIDED 2026-09-03 — calendar day: `Asia/Riyadh`,** not UTC. One constant in the claim RPC and one in the in-memory double; the codebase's UTC convention still holds for every stored instant, and only the day boundary a reader is told about is local. Riyadh has no daylight saving, so the boundary is unambiguous. Ruling 2 above is marked superseded rather than rewritten.
3. **DECIDED 2026-09-03 — a tier or an override may be zero.** Constraints stay `>= 0`; the `v_limit >= 1` guard in the claim is what makes 0 refuse the first claim of the day as well as later ones. Zero means "may sign in, read their history and browse, but may not ask today" — deliberately distinct from `is_disabled`, which refuses the session outright. Documented in both table comments and pinned by a test.
4. **DECIDED 2026-09-03 — the notice states the number, in both languages.** EN: "You've asked all {limit} of today's questions. Your allowance resets at {resets_at}." AR: «لقد استخدمت كل رصيدك اليوم ({limit}). يُعاد فتح رصيدك في {resets_at}.» Both placeholders are **always interpolated** — the limit is operator-editable, so a hardcoded number would rot silently inside a catalogue file — and when a windowed override is in force the notice states the override's number, not the tier's (§6.1).
5. **DECIDED 2026-09-03 — keep `remaining <= max(3, 20 % of limit)`**, which is 40 at the shipped 200. Ship it and fine-tune after Commit C against real usage. It stays a **constant in `ui.js`** — no config key, no `app_settings` row, no console control: a display threshold is not a product setting for four accounts, and wiring one would add a cache slot, a route and a test for a number nobody yet has evidence to choose (§6.2).
6. **DECIDED 2026-09-03 — the tab is `Tiers` / `الفئات`,** not `Groups`/`المجموعات`, even though "groups" was the owner's own earlier word (§5.1). Decided with it: the second seeded tier is renamed `internal` → **`staff` / «الإداريين»**, in Commit A before the FK lands (§1.1).
7. **OPEN, and deliberately not blocking — retention of `usage_daily` rows.** Folded into the existing retention entry in `TODO.md` unless the owner wants a number now.
8. **DECIDED 2026-09-03 — yes, the reader sees it.** The account page shows "{limit} questions a day until {date}" whenever `override_expires_at` is set. The argument that won: on the day the window closes the allowance silently drops back to the tier's number, and a reader who was never told it was temporary experiences that as a bug and opens a support ticket. One line, where they already look at their standing, prevents it. It needs only the `override_expires_at` field `/api/identity` already carries and one copy key per catalogue (§6.3).

---

## 14. Amendments after the build (2026-09-04)

Two defects that only the built surface could show. Both are recorded here rather than
edited away, because one of them reverses a line this document itself specified.

### 14.1 The tier table showed both labels — a reversal of §5.1

§5.1 specified a table of "key, label EN, label AR, daily limit, members, ordering". That is
the storage shape, and it should never have reached the screen. A tier's label is stored
twice because each reader sees one in their own language; printing both made the Tiers tab
the **only** surface in the product that ignores the language toggle. An operator who had
switched the console to English still read Arabic in the column beside it — while the
allowance card's `<select>` and the notification composer's target list, both fed from the
same rows, had been resolving `I18n.lang` correctly since the day they shipped.

**Corrected to: author both, display one.** The create/edit form keeps `label_en` and
`label_ar` and always will — a tier with one label renders blank for half the audience — and
carries a note saying so. The table prints one resolved label. The **key** is not a label: it
stays as it is in both languages, in the mono face, because it is what the database and the
notification composer both name.

Pinned in both directions by `test_admin_browser.py` — an English console must not contain
`مجاني`, an Arabic one must not contain `Free`, and the form must still hold both. Written up
as a rule in DESIGN.md, _Operator-authored bilingual data_, and as row 13 of
_Rules that collide_.

### 14.2 Three classes that no stylesheet defined, and a date that rendered backwards

**`admin-btn`, `admin-btn-quiet` and `admin-hint` were applied by `ui.js` and `admin.html`
and defined nowhere.** The Tiers tab's Edit, Delete, Save and Cancel controls, and the
allowance card's Save, were raw user-agent buttons sitting beside the console's own
`btn btn-primary btn-sm` / `btn btn-sm btn-ghost admin-row-action`; every hint was full-size
body text. Eighty browser tests passed throughout, because an unstyled button is still a
button and they assert what is on the page rather than what it looks like.

The console's real vocabulary was used instead — no new classes where the system already owns
the pattern — and the two forms moved from `.admin-field` (the settings tab's page-width row,
which draws a hairline under every control and turns a card into a table) to
`.admin-profile-field` inside `.admin-editor-card`, the shape the profile form two zones up
already had. `test_css_contract.py` now fails on any `admin-*` class the stylesheets do not
define; it was verified to fail on `admin-btn` before being believed.

**And `formatStamp` interpolated `toLocaleString(I18n.lang)` into the window's state line.**
Probed in Chrome, `new Date('2026-08-01T00:00:00Z').toLocaleString('ar', {dateStyle:'medium'})`
returns `01‏/08‏/2026` — U+200F RIGHT-TO-LEFT MARK between every field — and the bidi
algorithm reorders the run around those marks, so the first of August **rendered** as
`2026/08/01`. A date that says the wrong thing, in the one sentence on that card whose entire
job is to say when a window closed. This is the trap `exactWhen` was written for one zone up
(and which `docs/archive` records costing the people table once already), so it takes the same
way out: the stamp is built from parts with no localised characters in it, the catalogue string
is split on its own `{date}` placeholder rather than interpolated, and the stamp sits in its own
`dir="ltr"` isolate. Interpolation can only produce a string; an isolate has to be an element.

---

## Verification (when built)

`python -m pytest -m "not browser and not integration"`; `python -m pytest -m browser --browser chromium`; `ruff check . --fix && ruff format .`; `mypy web`; `npm run lint:fix && npm run format`; `npm run lint:md`; `get_advisors` after every migration; every `supabase/tests/*.test.sql` pasted into `execute_sql` before and after Commit A; a real `scripts/smoke_real.py` run once the claim is wired (it costs money and is not in CI).
