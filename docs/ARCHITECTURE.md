STATUS: CURRENT AUTHORITY — the live system contract. Last verified against code 2026-09-23.

# Architecture

What this system actually does, as opposed to what any plan once proposed it should do.

This file exists because four implementation roadmaps — now in `docs/archive/` — each
carried a section of the live contract along with the positions they later reversed.
Read cold, they contradict each other and the code. The rules that are still law were
lifted here; the roadmaps keep the reasoning and the cost, which is what they were
always for.

---

## Which document wins

When two documents disagree, this is the order. It is short on purpose.

| Subject                                          | Authority                                                                                                                                                                                                  |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Conversations, chat, persistence                 | This file. Then `docs/archive/2026-08-22_per-tab-deep-linking.md`, then `2026-08-20_chat-persistence.md`, then `TODO.md`. Newest wins.                                                                     |
| Registrations pause                              | This file (see _Registrations pause_). Then `docs/archive/2026-08-25_registrations-pause.md`, then `TODO.md`.                                                                                              |
| Notification Center                              | This file (see _Notification Center_). Then `docs/archive/2026-08-24_notification-center.md` (and `2026-08-29_notification-mark-read-500.md` for the mark-read fix), then `TODO.md`.                       |
| Admin analytics                                  | This file (see _Admin analytics_). Then `docs/archive/2026-09-20_admin-analytics-v1.md` for the RPC/data layer and `docs/archive/2026-09-23_admin-analytics-tab.md` for console placement, then `TODO.md`. |
| Account page, profile, data rights               | This file (see _Account page and profile_). Then `docs/archive/2026-08-23_profile-refactor.md`, then `TODO.md`.                                                                                            |
| Account deletion, disabled accounts, consent     | This file (see _Account deletion and trust_). Then `docs/archive/2026-09-18_account-and-trust.md`, then `TODO.md`.                                                                                         |
| The daily reader quota                           | This file (see _Reader quota_). Then `docs/archive/2026-09-04_reader-quota.md`, then `TODO.md`.                                                                                                            |
| Copy, product claims, terminology                | `docs/PRODUCT.md`                                                                                                                                                                                          |
| Design, tokens, RTL presentation                 | `DESIGN.md`                                                                                                                                                                                                |
| Database, migrations, RLS                        | `supabase/README.md` — it sits beside the migrations, which is where you are when you need it                                                                                                              |
| Deployment, DNS, mail, anything outside the repo | `docs/OPERATIONS.md`                                                                                                                                                                                       |
| A document's index vs. its own body              | The body.                                                                                                                                                                                                  |
| **Anything vs. a passing test**                  | **The test.** It is the only artifact here that cannot silently drift.                                                                                                                                     |

Every document in this repository opens with a `STATUS:` line and a date. A file
without one is not finished. A file whose date is old is a file to check before you
trust it. **Two files carry the banner just below a required header instead of on line
one:** `DESIGN.md`, whose YAML frontmatter must come first for the design tooling to
parse it, and `CLAUDE.md`, which opens with the standard Claude Code heading.

Archived documents carry the same claim in a machine-readable form — `authority: historical`
frontmatter, `[HISTORICAL]` on every heading, and exclusion from search via `/.ignore` —
because a prose banner at the top of a file does nothing for a tool that retrieves line
3,204. See [`docs/archive/README.md`](archive/README.md).

---

## The URL is the pointer

There is no per-tab pointer, no cookie naming a conversation, and no `sessionStorage`
key. The address bar holds the state.

- `/` is a new, empty conversation.
- `/c/<uuid>` is that conversation.

`sessionStorage` was considered and rejected: all three browser engines clone it
verbatim on tab duplication, which recreates the exact collision it was meant to fix.
It also throws in some private windows and WebViews, and is empty in a new tab.

`session["conv_id"]`, `prev_conv_id`, `POST /api/chat/sessions/<id>/select` and
`POST /api/conversation/reset` were **deleted**, not deprecated. `web/api/app.py`
keeps tombstone comments where the two routes were. `CHAT_RESUME_LATEST_SESSION` and
the whole resume-fallback subsystem are gone; `web/tests/test_session_isolation.py`
carries the note _"NO MORE 'resume' TESTS HERE"_ so the mechanism cannot quietly
return.

**Undo is the Back button.** New chat is a navigation from `/c/<id>` to `/`. There is
no undo toast and no server-side undo state.

### The security shape of `/c/<uuid>`

Pinned by `web/tests/test_deep_link_contract.py`. All four properties are load-bearing:

1. **Not authenticated, and no ownership check.** For a fixed requester, varying the
   uuid produces no observable difference. There is no existence oracle.
2. **No state written.** No `Set-Cookie`, nothing session-scoped. A page render that
   mutates state would let a third-party link repoint another tab's conversation, and
   would be detonated by link scanners such as Safe Links.
3. **Foreign is indistinguishable from nonexistent.** Same status, byte-identical body.
   House policy, not a local choice.
4. **`X-Robots-Tag: noindex, nofollow`.** Header, not a meta tag. **Do not add a
   `robots.txt`** — `Disallow` and `noindex` defeat each other, and that combination is
   the documented root cause of several public AI-chat indexing incidents.

Enforcement lives entirely in `GET /api/chat/history`, which _is_ authenticated.

**If sharing is ever built** it must be a separate, revocable object with its own id —
never a visibility flag on the conversation. Unfurling is acceptable today only
because the render is content-free; it would not be safe if the URL became a
capability.

### Conversation ids

The **client** mints the id (`crypto.randomUUID()`) before the first request. A
client-minted id is **not an authorization claim**: `p_owner_id` is always derived
server-side from `g.identity`, never from the request body.

An absent or malformed `conversation_id` mints a fresh one rather than returning 400 —
a 400 turns a client bug into a failed question. Ids are normalised with
`str(uuid.UUID(x))` at the Flask boundary, never in SQL.

Keep the uuid **v4**. Do not "upgrade" to v7: it encodes the creation millisecond into
a pasted URL.

### Ownership preflight

On a request that names an **existing** conversation (`allow_create: false` — the shape a
`/c/<id>` deep link produces on turn 2 onward), the streaming route calls
`_preflight_conversation(persistence, owner_id, conversation_id)` (`web/api/app.py`) before
retrieval and before any SSE frame, inside the `_InFlightGenerations` hold already taken for
that `(owner_id, conversation_id)` pair. It calls `ConversationStore.session_exists` (the
persistence protocol declared in `web/services/chat_store.py`); on `False` it releases the hold
and returns a plain `404 {"error": "Unknown conversation.", "code": "not_found"}` before any
retrieval or LLM call — pinned by `test_deep_link_contract.py`'s assertion that the search/LLM
double's `call_count` stays `0`. On a persistence outage the check **fails open** (treats the
conversation as existing), by explicit design: refusing a legitimate question because an
existence check could not be reached is judged worse than the resurrection risk this guards
against, which `chat_append_turn`'s own `p_allow_create` still refuses at the database
regardless.
Reasoning: docs/archive/2026-08-22_per-tab-deep-linking.md §3.4.

### Request validation and response headers

There is still no CSRF token or Origin check anywhere in this app — see _Authentication and the
blueprint gate_ below. Two narrower fixes live near where an older citation calls this
"CSRF-shaped": `_validate_chat_request` (`web/api/app.py`) parses the body with
`request.get_json(silent=True)`, not `force=True`, so a cross-site `enctype="text/plain"`
auto-submitting form cannot inject a body regardless of `Content-Type`; and the route it used to
share that vector with, `POST /api/chat/sessions/<id>/select`, is deleted outright rather than
merely secured (see the next section). `Talisman(...)` is configured with
`session_cookie_samesite="Lax"` and `referrer_policy="strict-origin-when-cross-origin"` passed
explicitly, rather than left to the library's default, so an upgrade cannot silently change
either. `GET /c/<uuid:conversation_id>` sets `X-Robots-Tag: noindex, nofollow` on its own
response — `/` does not — because it is the only page whose path carries a conversation id.
Reasoning: docs/archive/2026-08-22_per-tab-deep-linking.md §3.5, §6.1.

### Deletion, resume, and multi-tab isolation

Selecting or resuming a conversation is client-side navigation, not a server call:
`POST /api/chat/sessions/<id>/select` and `POST /api/conversation/reset` are both deleted, and
`session["conv_id"]`/`prev_conv_id` no longer exist. "New chat" (`Handlers.handleNewChat`) is a
pure navigation from `/c/<id>` to `/`, with Back as the only undo. `/` is always a new, empty
conversation — there is no "resume my last session" fallback (`CHAT_RESUME_LATEST_SESSION` is
retired); `GET /api/chat/history` requires an explicit `?c=<uuid>` and has no cookie fallback, so
a bare `/` renders an empty transcript rather than resuming anything. `GET /api/chat/sessions`
paginates by cursor (`next_cursor: {updated_at, id}`), not offset. Two tabs are independent by
construction — each holds its own URL and its own `(owner_id, conversation_id)`-keyed server
state (`ConversationStore`, `_InFlightGenerations`); duplicating a tab is a second view of the
same conversation, not a collision, and a `409 generation_in_flight` is scoped to one
conversation, never shared across two different ones open in the same browser. Pinned by
`test_multi_tab_conversations.py` (two Playwright pages sharing one browser context).
Reasoning: docs/archive/2026-08-22_per-tab-deep-linking.md §5.1, §5.2, §5.5 (Decision 1a: `/` is
always new, never a resume), §7.2.

---

## Single worker

```bash
gunicorn --workers 1 --threads 8 "web.api.app:create_app()"
```

**That line is the shape, not the deployment.** What production actually runs is committed at
[`deploy/sfda-copilot.service`](../deploy/sfda-copilot.service) and was verified byte-identical to
the live unit on 2026-09-18 — read that file, not this snippet. Two differences are worth knowing
because they have already misled a reader: the worker count is not on the command line at all (it
is `workers = 1` in `gunicorn.conf.py`, per the precedence note below), and there is no
`--timeout`, so gunicorn's 30-second default applies rather than the 300 this example used to
show. That default is **not** a cap on how long a chat answer may take: with `--threads 8` the
worker is `gthread`, whose main loop heartbeats once a second while requests run in a thread pool,
so a slow LLM call never looks idle to the arbiter. nginx's `proxy_read_timeout 300s` below is the
bound that actually matters for a long answer.

The app logs a warning at startup under gunicorn if it is launched with more than one worker,
checking the four sources in gunicorn's precedence order: the command line (`--workers`/`-w`),
`GUNICORN_CMD_ARGS`, `gunicorn.conf.py` (via `SFDA_CONFIG_WORKERS`), and `WEB_CONCURRENCY`
(`_configured_worker_count`). `gunicorn.conf.py` owns the committed worker count (`workers = 1`);
any `--workers` flag in the `systemd` `ExecStart` overrides it because command-line flags
silently win. The check is gunicorn-only (the dev server and pytest stay quiet). **It infers
the configured count from how the process was launched, so it is a report, not an enforcement**:
a count changed afterwards by signalling the master (`TTIN`/`TTOU`) is not seen.

**The current reason is the in-RAM FAISS index and the sentence-transformers model.**
A second worker means a second copy of both.

The reason you will find in older documents — that Flask writes `Set-Cookie` before the
WSGI server iterates a streaming body, so conversation history had to live in a
process-local store — **is retired**. History is durable in Postgres now. The
constraint outlived its original justification; the justification did not.

Four things still depend on single-worker and would need replacing before it changes:

- `ConversationStore` — the computed prompt window, keyed `(owner, conversation)`. It
  is **not** a cache of the stored rows; making it write-through would let a restart
  change the prompt mid-conversation. Its `clear()` is deliberately owner-blind:
  under-purging leaks one reader's questions into another's prompt.
- `_InFlightGenerations` — a counted claim on `(owner, conversation)`. Select and
  delete answer **409 `generation_in_flight`** while a claim is held. The replacement
  at multi-worker is a tombstone table, not a bigger dict.
- `IdentityFlagsCache` — one per process, so an admin's disable or retier only reaches the
  worker that served it and the others answer from their own copy until it expires. The
  console itself is not at risk: an admin request resolves identity fresh. The shipped
  `TokenVerificationCache` is process-local too but stores nothing (TTL 0), so at
  multi-worker it costs duplicate verification calls, not stale credentials — raising that
  TTL is what would make it the same problem.
- **Every Flask-Limiter limit**, because the Limiter is built with `storage_uri="memory://"`
  and each worker therefore counts alone: aggregate enforcement allows up to N times each
  published `rate_limit.*` number. Not the daily message allowance, which is a durable
  atomic RPC and survives any worker count intact. The replacement at multi-worker is
  shared storage, and every number in `web/config.yaml` would have to be re-judged
  against it.

Per-tab conversations make eight simultaneous SSE streams from one reader legitimate.
That capacity question is open and unsized.

---

## The stream must not be buffered

Answers stream over SSE. Any proxy in front of the app has to disable response
buffering or streaming is defeated entirely — each answer is held until it completes.

The app sends `X-Accel-Buffering: no`. Set it explicitly too:

```nginx
location /api/chat/stream {
    proxy_pass http://127.0.0.1:5001;
    proxy_buffering off;
    proxy_read_timeout 300s;
    gzip off;
}
```

Frame ordering is fixed and tested: `final` → durable write → `suggestions` → `done`.
`conversation_id` rides `meta`, `final` and `done` **only, never `delta`** — on an
800-token answer that would be about 29 KB of repetition.

A persistence failure is an **`error` frame, not a new event name**: the client
dispatches with `on[frame.event]?.()`, which silently drops names it does not know.

---

## No bundler

Browser-native ES modules. No `node_modules`, no build step, no bundler. Bootstrap
5.3, DOMPurify, marked and supabase-js load from jsDelivr at pinned versions.
`package.json` exists so `npm audit` covers what users actually run; **its versions
must stay in sync with the CDN URLs** in `static/js/modules/{ui,stream-render,services}.js`
and the templates. Nothing tests that coupling.

Icons are not a dependency: every glyph is inline SVG from `web/utils/icons.py`, so
there is no webfont to download or to fail.

### The import map, and why there are three module directories

A `?v=` on the `<script>` tag busts only the entry point; a static
`import './modules/ui.js'` inside it resolves to a bare, unversioned URL. So each
template emits a browser-native **import map** that rewrites every module URL to its
versioned twin, generated by `_import_map()` in `web/api/app.py` from `ASSET_VERSION`.
Filenames are enumerated once at import time — **adding a module needs a restart.**

There are three separate directories, and the separation is a security boundary, not
tidiness:

| Entry point            | Modules              | Template       |
| ---------------------- | -------------------- | -------------- |
| `static/js/app.js`     | `static/js/modules/` | `index.html`   |
| `static/js/admin.js`   | `static/js/admin/`   | `admin.html`   |
| `static/js/account.js` | `static/js/account/` | `account.html` |

The landing page inlines an import-map entry for every name in its own directory. A
console module dropped in beside the reader's would publish its filename on the
anonymous landing page — an inventory of the operator surface, rendered for people who
cannot reach it.

`test_frontend_architecture.py` enforces that the console never imports the chat shell.

**Bump `ASSET_VERSION` in `web/api/app.py` in any commit touching CSS or JS.** Do not
write the current value into any document; the durable instruction is _bump it_.

---

## The `runtime.*` catalogue has a closed top-level key list

Every page inlines the `runtime:` subtree of `web/i18n/en.yaml` as
`window.__I18N` — whole on the console, without `runtime.admin` on reader pages
(`runtime_subset` in `web/utils/i18n.py`). The server-only `page:` subtree must
never reach the browser (`test_rtl.py`, `test_admin_page.py`).

**`test_admin_page.py` pins the top-level `runtime.*` keys to a closed set of eleven:**

```
chat  sessions  stage  robot  auth  profile  faq  theme  cite  lang  admin
```

A new feature therefore **cannot open its own top-level string namespace** without
changing that test. This is why the account page's runtime strings live at
`runtime.profile.account.*` rather than a clean `runtime.account.*`, while its
server-rendered strings sit at `page.account.*` where no such ceiling applies.

This was found by breaking the test. It is written here so the next person does not
have to.

---

## Two table-access patterns

**Flask-mediated tables** — `chat_sessions`, `chat_messages`, `chat_message_sources`,
`chat_archive`, `audit_log`, `app_settings`, and the three quota tables `tiers`,
`reader_quota_overrides`, `usage_daily`:

- RLS **on**, and for writes **no policies at all**.
- `revoke all from anon, authenticated`.
- All writes go through `security definer` RPCs, every one filtered on `p_owner_id`.
- **Do not "fix" this by adding a policy.** RLS here is defence in depth, not the
  coordinator of a workflow that spans a process-local cache, an in-flight lock and
  three tables. A browser-writable `chat_messages` is a provenance-forgery primitive.

Readers get `select` and `delete` on their own `chat_sessions` rows via RLS, and
`select` on their own messages and sources. There is no insert or update policy on any
chat table, and none should be added.

The three quota tables go one step further than the rest: **no role holds any grant on
them at all, `service_role` included.** Every reader and writer is a `security definer`
function running as the table owner, which is the posture `profile_last_seen` established.
A reader learns their own allowance through `get_reader_quota`, which returns counts and
tier labels but deliberately not the operator's `reason` or `set_by`.

**Browser-direct tables** — `profiles`, and only `profiles`:

- Read and write straight from the browser to PostgREST under RLS.
- Column protection is a **column-level `REVOKE` plus a trigger**, because RLS
  restricts rows and cannot restrict columns. `profiles.role`, `tier` and
  `is_disabled` are writable only by the service role.
- Since 2026-09-03 `profiles.tier` is also a **foreign key** into `public.tiers`
  (`on update cascade on delete restrict`), so a tier cannot be deleted while anyone is
  in it and no profile can name a tier that does not exist.
- `preferences` is written through `update_own_preferences(jsonb)`, which **merges**.
- `anon` holds **nothing** on it since `20260828001035`. It previously held `SELECT`,
  which put `profiles` in PostgREST's schema for unauthenticated callers: the rows were
  protected but the shape was not, and an anonymous `GET /rest/v1/` disclosed that this
  application stores `role`, `tier`, `is_disabled`, `disabled_reason` and six
  `marketing_consent_*` columns. The same migration took `DELETE` and `TRUNCATE` off both
  browser roles — **`TRUNCATE` is not subject to RLS**, so on the table that decides who
  is an administrator it was stopped by nothing but PostgREST's inability to emit the
  statement.

**A third pattern is now closed rather than open.** `service_role` used to hold table-level
`ALL` — `TRUNCATE` included — on `profiles`, `app_settings`, `notifications`,
`notification_recipients` and `user_notification_reads`, which is a second write surface
beside the RPCs on which every invariant those RPCs enforce is optional. RLS does not close
it, because `service_role` carries `rolbypassrls`. `20260828000952` reduced it to `SELECT`
on the three tables Flask reads directly and nothing at all on the two it does not; the
only direct write left anywhere in `web/` is `admin_store.py`'s insert into `audit_log`.
The full table is in [`supabase/README.md`](../supabase/README.md#what-service_role-may-touch-directly).

**And new objects are now born closed.** Schema `public`'s default privileges granted every
table privilege to `anon` and `authenticated` on every future table until `20260828000737`;
`chatbot_settings` is the surviving receipt. Functions needed a second migration and a
correction: a per-schema default ACL is merged onto the hard-wired base and cannot subtract
from it, so the `IN SCHEMA public` revoke left the built-in `EXECUTE`-to-`PUBLIC` grant
standing. The **global** form (`20260828100816`, no `IN SCHEMA`) replaces that base and does
close it. Both layers are asserted by `supabase/tests/privileges.test.sql`; the per-function
`revoke execute` line stays in the RPC contract as belt to those braces.

Full rules in [`supabase/README.md`](../supabase/README.md).

---

## Authentication and the blueprint gate

Token resolution order is Bearer header → `sb-access-token` cookie → Flask session
(`_get_token_from_request`). `_authenticate_request` and the `@auth_required`
decorator enforce it. Identity is cached process-locally for **30 seconds**
(`web/services/identity_cache.py`).

**Token verification is single-flighted on every route, and cached only on
reader routes.** A structural pre-check (`_is_structurally_live`) rejects a
malformed or already-expired token before any network call. Past that,
`web/services/token_verification_cache.py` collapses concurrent requests
bearing the _same_ bearer token into one `supabase.auth.get_user` call —
including on `/admin/*`, which is what stops the console's own boot fan-out
from starving the single worker. Remembering a successful result for reuse
across _sequential_ requests is a separate, priced decision: it defaults to
`ttl_seconds: 0` (off) on reader routes and is never applied to `/admin/*`,
which always verifies live. Every stored entry is additionally capped at the
token's own `exp`. See `docs/archive/2026-08-27_token-verification-cache.md`
for the full trade and why 0 — not a positive number — shipped as the
default.

**An outage is not a refusal.** `_is_upstream_outage()` and `_is_auth_refusal()` are
separate: an `httpx.TransportError` is a **503**, our own fault is a **500**, and
**401** is reserved for a genuinely rejected credential. A transient Supabase outage
must never sign a reader out. The client retries a 503 **for GET only** — never a
mutation.

**Blueprint gates are `before_request`, not per-route decorators.** `admin_bp` and
`account_bp` each gate the whole blueprint and accept a **bearer header only** —
cookie or session auth on those routes would be CSRF-shaped, and this app has no CSRF
protection. A decorator can be forgotten on route nine, and that failure is silent.

**There is no server-side sign-in.** `/auth/login` was deleted on 2026-09-23 after one
release as a logging `410` tombstone; it now answers Werkzeug's plain `404`. Sign-in is
browser-direct and always was: `Services.login` calls
`supabase.auth.signInWithPassword` straight to GoTrue with the public anon
key. The server-side route was worse than cost without a property: it
forwarded the caller's traffic to GoTrue from this host's single address,
blinding GoTrue's own per-IP `/token` limiter to the attacker's real
address. `POST /auth/signup` used to
be the same shape and was dead code in production as a result — nothing
called it — until the registrations-pause work (see _Registrations pause_
below; reasoning in `docs/archive/2026-08-25_registrations-pause.md`) moved
`Services.signup` onto it, which is the only way an operator's pause can
actually be enforced. `POST
/auth/recover` and `POST /auth/logout` were already server-mediated before
that, for reasons specific to each (recovery: PKCE, see
`web/services/account_recovery.py`'s module docstring). So today: **signup,
recovery and logout are server-mediated; login is browser-direct.**

**That rule has exactly one deliberate exception, and it is bounded.** Deletion
step-up (`_verify_current_password`, `web/api/account.py`) calls GoTrue's
`sign_in_with_password` server-side for the caller — the same shape the route
above was retired for, reintroduced on purpose because a bearer token alone must
not delete an account and this is the only server-verifiable step-up the stack
offers. It is admissible because it sits behind an authenticated session, guards
one action rather than the sign-in path, and ships with the durable per-account
throttle that replaces the per-IP limiter it blinds (`step_up_attempts`,
`20260918234736`). Row 16 of _Rules that collide_ carries the full reasoning.

**The anon client is deliberately sessionless.** `SupabaseClient` builds it with
`persist_session=False`, so neither `sign_in_with_password` nor `sign_up` leaves a
session on the process-global instance. Without that, the singleton starts holding
whoever authenticated last for all eight threads, and any no-argument auth call on it
acts as that reader — which is how `POST /auth/logout` came to revoke a different
person's sessions than the caller's. Every auth call here passes its own JWT
explicitly: `auth.get_user(token)` for verification, `auth.admin.sign_out(token,
"global")` for logout. **Never add a no-argument auth call to this client.**

Limits on `/account/api/*` key on the **authenticated user id**, not the IP
(`_account_rate_key`) — otherwise it is "two exports per ten minutes _per building_".

### When a session ends in the browser

_Verified against code 2026-09-11._ A shared machine is the ordinary case, so the rule is that
nothing of reader A's may reach reader B — not the transcript, not the URL, not a notice. The
three frontends meet it differently, on purpose.

**The chat page tears down in place and never reloads.** `SIGNED_OUT`/`USER_DELETED` runs
`Handlers.clearSessionState()` (the local teardown plus `POST /auth/logout`) and then, if the
address bar names `/c/<id>`, `Route.replace(null)`. One sign-out posts once from this tab: the
logout button and `endRecovery` post through `Services.logout`, first, and run only the local
teardown themselves, and `clearSessionState` skips its POST while that call is running; the
listener posts for every sign-out the tab did not start. Each other open chat tab posts once more
on a broadcast sign-out — accepted, not overlooked: the rate-limit comment at the top of
`web/api/auth.py` records why neither candidate fix is worth its cost, and what would reopen it.
A direct switch to a different reader runs
`clearReaderScopedUI()` (the local teardown without the POST, which would revoke A upstream) and
the same URL reset. Both are one function, `clearReaderLocalState()`: **it is the single list
of reader-scoped state, so new reader-scoped UI is cleared there**. The URL is deliberately not
its job — `endRecovery` shares the teardown and must keep the recovery form's path. The only
reload left is `handleLogout`'s `redirectToHomeIfNeeded()`, a fallback for the paths where no
`SIGNED_OUT` arrives (the demo, a throwing `signOut`, `sessionMissing`).

**Late answers are discarded by generation, not by luck.** A request that outlives the reader
who made it checks the counter it stamped: `resetGeneration` (chat requests and the stream),
`transcriptEpoch` (history), `selectionEpoch` (sidebar), `identityCheckId` (identity and
profile) and `readerGeneration` (the notification inbox). A new asynchronous path that paints
reader-scoped state must stamp one of these.

**Back and bfcache.** `handlePopState` scrubs a `/c/<id>` only when `getSession` confirms there
is no session — an error is not absence, and a signed-in reader must never be bounced to `/`. A
fresh load reached by Back with nobody signed in drops the id too; a cold deep link keeps it. A
bfcache restore runs no init and supabase-js emits no event for storage it finds empty, so the
chat page hides `<body>` on `pagehide`, and on a restore `reconcileRestoredSession` reveals it
only for the same reader, navigates to a fresh `/` for anyone else, and reloads on an error.

**`/account` and `/admin` reload instead.** `installSessionResetOnEnd`
(`static/js/modules/session-reset.js`) hides the page and reloads on `SIGNED_OUT`/`USER_DELETED`
and on any bfcache restore; their own init already renders the signed-out and refused states.
The account page's dirty-form guard stands down for that one reload (`allowForcedReload`). The
chat page cannot do the same: it holds a live stream and in-page state, and on its sign-out path
a reload would cancel the unawaited teardown POST.

Pinned by `web/tests/test_signed_out_route.py` and `web/tests/test_bfcache_session.py`. The
second launches full Chromium: Playwright's default headless shell disables bfcache, so a
bfcache test run against it passes without testing anything. The reasoning, the reviews and
what was reversed on the way are in `docs/archive/2026-09-11_revoked-session-url-reset.md`.

---

## Rate limits

Flask-Limiter, `memory://` storage, keyed on the remote address unless noted.
"Keyed per account" means `_rate_key` (`app.py`), which returns `reader:<user_id>`
from `g.identity` and falls back to the IP only where no identity is present — which
every route below marked that way makes unreachable, because each sits behind a gate.

| Scope                                               | Limit                                   |
| --------------------------------------------------- | --------------------------------------- |
| Global default                                      | 200/day, 50/hour, 10/minute             |
| Chat (`/api/chat` and `/api/chat/stream`, shared)   | 15/minute, **keyed per account**        |
| `GET /api/chat/history`                             | 30/minute                               |
| `/api/chat/sessions` (list, select, rename, delete) | 60/minute                               |
| `POST /auth/recover`                                | 5/minute                                |
| `POST /auth/signup`                                 | 5/minute                                |
| `GET /account/api/export`                           | 2 per 10 minutes, **keyed per account** |
| `DELETE /account/api/conversations`                 | 10/hour, **keyed per account**          |
| `POST /account/api/consent/grant`                   | 30/hour, **keyed per account**          |
| `admin_bp` (whole blueprint)                        | 60/minute                               |
| `admin.revoke_sessions`, `admin.change_email`       | 10/minute                               |
| `admin.create_notification`                         | 10/hour, **keyed per account**          |

**Five of those route limits were registered but never enforced** until 2026-09-03 —
`account.export`, `account.delete_all_conversations`, `admin.revoke_sessions`,
`admin.change_email` and `admin.create_notification`. Each was written as
`limiter.limit(...)(app.view_functions[name])`, which returns a wrapper and discards
it: Flask-Limiter marked the endpoint as carrying a limit (so its own middleware
skipped it) while nothing enforced one, leaving those routes **less** limited than if
the line had been absent. The fix is to assign the wrapper back into
`app.view_functions[name]`. `web/tests/test_rate_limit_keys.py` pins it behaviourally,
which is the only way: `functools.wraps` copies `__dict__`, so the limiter's marker
attribute propagates onto the outer `auth_required` wrapper and a structural check
cannot tell the two apart.

**A route limit REPLACES its blueprint's, it does not stack.** `limit()` defaults
`override_defaults=True`, so each of the five carries exactly its own limit and not
`admin_bp`/`account_bp`'s 60/minute as well. `override_defaults=False` is the switch
if stacking is ever wanted.

`history_api` and `sessions_api` carry their own limits **specifically so that
ordinary navigation cannot spend the 200/day budget an office behind one NAT shares
with chat itself.** An explicit limit replaces the defaults in Flask-Limiter; that is
the mechanism being used deliberately.

`memory://` counters are fine for a burst limit and **not** for a daily quota, because
they do not survive a deploy. The durable daily allowance is therefore a separate
mechanism and not a Flask-Limiter limit at all: `public.usage_daily` holds one row per
account per day, and `chat_claim_daily_message` does one atomic
`insert … on conflict … where used < limit returning` inside a `security definer` RPC.
The claim is taken **in the view body, before the generator**, so exhaustion is a clean
429 with `Retry-After` rather than a dying SSE stream, and it is refunded if the request
fails before the model produces its first token.

The allowance resolves, in order: an in-window per-account override
(`reader_quota_overrides`) → the account's tier (`tiers.daily_message_limit`, via
`profiles.tier`) → the live `free` tier → `web/config.yaml`'s
`server.quota.daily_messages_default`. Tiers and overrides are operator-editable from the
console; the calendar day is `Asia/Riyadh`. Schema and design:
[`docs/archive/2026-09-04_reader-quota.md`](archive/2026-09-04_reader-quota.md).

---

## Registrations pause

An operator can close signup without a deploy. `app_settings.settings` carries a boolean
`signup_enabled`, read through `SettingsService.signup_enabled()` (three-valued: `True`/`False`/
`None` on a load failure) and written through `SettingsService.set_signup_enabled()` under the
same `admin_write_settings` RPC and audit action (`settings.update`) the generation settings
already use — no separate migration or action string. `POST /auth/signup`
(`web/api/auth.py`) gates before calling GoTrue and again immediately before the provider call,
to narrow the race window: `None` answers `503 auth_unavailable`, `False` answers
`403 signup_disabled`. Every page render passes `signup_paused` into the template
(`base_render_context`); `index.html` swaps in a `role="status"` notice and hides the form,
while the signup tab stays selectable with a small "(paused)" indicator. The pause is
enforceable only because `Services.signup` now posts to this server route instead of calling
Supabase directly from the browser — the same move that gave signup its own rate limit
(`signup_bp`, separate from the deleted `/auth/login` proxy; see _Authentication and the
blueprint gate_). The pause has **no database-level enforcement** and does not block a direct
GoTrue call. The operator control is `GET`/`PUT /admin/api/registrations` (`web/api/admin.py`),
rendered as its own zone in the console's Settings panel with a permanent note about that
bypass. The `auth.users` `AFTER INSERT` trigger `handle_new_user` is unrelated to the pause — it
normalises signup metadata and, being `AFTER INSERT`, cannot roll back account creation, so it
was deliberately never used to hard-block signup.
Reasoning: docs/archive/2026-08-25_registrations-pause.md §2, §4, §5, §6, §7, §9.

---

## Notification Center

An admin composes a broadcast (`admin.py`'s `create_notification`, calling
`admin_create_notification`), which inserts one `notifications` row, a
`notification_recipients` snapshot for the targeted role/tier/user set, and an audit row in one
transaction, idempotent on `client_request_id`. A reader's inbox is fetched over REST —
`GET /api/notifications/active` and `/history`, `POST /api/notifications/mark-read` and
`/mark-all-read` — never over Realtime. **REST is the only source of truth for content; the
private per-user Realtime channel carries only `{notification_id, revision}` and exists solely
to make an already-open tab refetch sooner than its next poll**, so an intercepted broadcast
discloses nothing. Three independent display shells render outside the (twice-rendered) sidebar
macro, per the collision noted in _Rules that collide_ #6: a corner toast stack, a single-slot
`aria-live="polite"` banner, and a focus-trapped modal whose only way to mark `acknowledged` is
its own button (Escape/backdrop-click just session-snoozes it). Only the reader-facing inbox
history uses cursor pagination (`cursor_created_at`/`cursor_id`); the admin console's own
notification history stays offset/limit, matching its other list RPCs. A shipped defect
(mark-read `500`: the response builder collided a duplicate `notification_id` key pulled in from
`**row`) is fixed, and is now cited defensively in `admin.py`'s profile-update response building
as the reason to build response dicts explicitly rather than by merging an RPC row's own keys.
Reasoning: docs/archive/2026-08-24_notification-center.md §2, §3, §4, §7, §8; the mark-read
defect and fix are recorded in docs/archive/2026-08-29_notification-mark-read-500.md.

---

## Admin analytics

Two `service_role`-only, `security definer` RPCs answer "what are readers asking, and is the
app citing anything" over `chat_messages`/`chat_message_sources`, gated like every other
`admin_*` reader by the console's blueprint `_gate()` rather than an owner argument (see
_Rules that collide_ #17): `admin_top_questions` groups saved user turns by a normalised
question text and returns ask counts, an uncited count, and an asker count bucketed below 5
distinct accounts; `admin_citation_stats` returns per-scope counts only, never percentages, of
turns, uncited turns, turns with no retrieval at all, and cited/retrieved totals. The
normalisation (`admin_store.py`'s `normalize_question`, stripping zero-width marks, space runs
and trailing punctuation) exists to collapse near-duplicate phrasings for counting, not for
privacy — the privacy line is the SQL projection naming no identity column, a Python column
allow-list, and the minimum-asker floor. On the console this renders in its own last tab
(`#panel-analytics`/`#analytics-body`), not the sibling-of-Overview placement the original plan
shipped with — that placement, and the explanations behind an "i" popup, were superseded by a
later, separate change; see `DESIGN.md` and `docs/archive/2026-09-23_admin-analytics-tab.md` for
the current tab contract. `supabase/tests/function_acls.test.sql` and `rpc_behaviour.test.sql`
are what actually prove the ACL and the grouping/count logic — the latter is the only place
either is proven off a real Postgres run rather than a Python double, because Postgres's `\s`
diverges from Python's.
Reasoning: docs/archive/2026-09-20_admin-analytics-v1.md §4, §4.1, §5, §6, §7 (tab placement
superseded by docs/archive/2026-09-23_admin-analytics-tab.md).

---

## Account page and profile

`account_bp` (`web/api/account.py`) mounts at `/account` and follows the console's own
two-part split: **the page is not gated; the data is.** `GET /account` (`page`) renders
chrome and translated strings only — a document navigation carries no `Authorization`
header, since the Supabase session lives in `localStorage` — and every `/account/api/*`
route is refused by `_gate` (a `before_request` hook) unless the caller presents a bearer
token that `_authenticate_request` accepts; `_gate` deliberately reads only the explicit
`Authorization` header (`_bearer_token`), never the cookie or Flask-session fallback
`_get_token_from_request` allows, for the same CSRF reasoning as the console's own gate.
The reader's identity and profile fields are **not** Flask-mediated: they are read and
written straight from the browser to PostgREST under RLS on `profiles` (see
_Two table-access patterns_), and `preferences` specifically is written only through the
`update_own_preferences(jsonb)` **merge** RPC — never a whole-row upsert (rule #8 above).

Two data-rights routes live on this blueprint. `GET /account/api/export` streams every
session the caller owns as NDJSON (`export_all_sessions`, `web/services/chat_store.py`),
scoped to `owner_id` from `g.identity` and never from the request; a backend outage before
the stream starts is a `503`, and one that fails partway through appends a trailing
`{"error": "history_unavailable"}` line rather than truncating silently. `DELETE
/account/api/conversations` (`delete_all_conversations`) deletes chat history only — the
profile row and auth identity are untouched — and is refused with `409
generation_in_flight` while any owned conversation is mid-generation
(`_generations().is_live_for_owner`), but is **not** refused for an owner with a live
deletion saga (see _Account deletion and trust_): the saga purges the same rows at grace
expiry regardless, so blocking early removal would only take away agency during the grace
window.

`POST /account/api/consent/grant` (`consent_grant`) is the one profile mutation this
blueprint makes server-side rather than browser-direct: it stamps `PRIVACY_POLICY_VERSION`
(the single source in `web/api/app.py`) and calls `grant_marketing_consent`, so a client
cannot backdate or forge the version it consented under. Withdrawal is the opposite shape
by design — `update_own_marketing_consent` stays browser-direct so it keeps working even
while an account is disabled or a deletion is pending (see _Account deletion and trust_).
A grant attempted during a live deletion saga is refused `409 deletion_pending` (saga error
`DL007`), surfaced through `_saga_error_code`.
Reasoning: docs/archive/2026-08-23_profile-refactor.md Decision 8, §4, §5, Step 6, Step 7.

---

## Account deletion and trust

Self-serve account deletion is a saga, gated end to end by one deploy switch —
`server.account_deletion_self_serve_enabled` in `web/config.yaml`, read at request time as
`_deletion_self_serve_enabled()` — because the code ships before the saga schema and the
reconcile timer are both live; while it is off, all three routes below answer `404` (not
`503`, so the feature reads as not-yet-shipped rather than transiently down).

`POST /account/api/deletion` (`deletion_request`, `web/api/account.py`) requires two
things before it calls the `account_deletion_request` RPC: a durable step-up lockout check
(`_step_up_is_locked_out`, checked **before** any provider call, so a locked-out caller
produces no GoTrue round trip at all) and the caller's **current password**, verified
server-side by `_verify_current_password` through a real
`supabase.auth.sign_in_with_password` call — a bearer token alone is never enough, because
on a shared machine the token is the ordinary case. A wrong password is recorded by
`_record_step_up_failure` (fails open on a transport fault: this is a rate limit, not the
authorization boundary) and answers `401 step_up_failed` or, once tripped,
`429 step_up_locked_out`. The RPC itself refuses an administrator (`DL003`) and a
double-request on an already-deleted account (`DL004`); this route surfaces those, it does
not re-implement them. On success it calls `sign_out_all` with the **requesting session's
own JWT**, global scope — never `revoke_sessions` and never a GoTrue ban, both of which
would either lock the real owner out of the cancel path or require a password rotation to
undo. `POST /account/api/deletion/cancel` (`deletion_cancel`) needs no step-up (cancelling
destroys nothing) and is reachable by a pending reader with no gate change, since `_gate`
refuses only `is_disabled` and the saga never sets that column; it is refused `409` once
past the purge boundary (`DL005`). `GET /account/api/deletion` (`deletion_status`) reads
the `account_deletions` ledger row directly, filtered by equality on `g.identity`'s
`owner_id` only — there is no status RPC in the saga contract and no request-supplied id,
so another account's row is unreachable through this route.

Post-grace steps (purge transcripts, re-purge, begin the auth delete, delete the GoTrue
user, record the outcome, complete) run through one driver, `reconcile_one`
(`scripts/reconcile_account_deletions.py`), invoked two ways against the same
implementation: a systemd one-shot timer (`deploy/`) and the admin console's own
`deletion_reconciler` seam in `web/api/app.py` — never a daemon thread, because the
production unit recycles the worker every 1,000 requests (`--max-requests 1000`), which
would strand a saga step mid-flight with nobody left to reconcile it. Each step is
lease-claimed so two drivers cannot run the same step twice; an ambiguous outcome (the
transport failed but the provider call may have already committed) is resolved by calling
`user_exists()` — if GoTrue no longer has the user, the step is treated as succeeded
(`not_found`) regardless of what the transport reported. The driver never calls
`revoke_sessions` or sets a ban during reconcile, and never logs the reader's email, IP or
user agent — only the saga's DL-codes and the ledger's uuid.

**Disabled accounts, and the one thing they can still do.** `is_active_account()` gates
both the `profiles` `UPDATE` policy (`20260919013800_freeze_profiles_update_policy.sql`)
and `update_own_preferences`
(`20260919013813_gate_update_own_preferences.sql`), so a disabled or pending-deletion
account cannot edit its own profile or preferences. The single carve-out is
`update_own_marketing_consent` (withdrawal only, migration
`20260918232554_update_own_marketing_consent.sql`), which deliberately never calls
`is_active_account()`: an account that is disabled, or mid-grace on a deletion it later
cancels, must always be able to withdraw consent. `grant_marketing_consent` is the
opposite of that carve-out (see _Account page and profile_) — it is reachable while
disabled (that is a decision, not an oversight: disabling a reader for policy reasons
should not itself stop a legitimate marketing opt-in) but refused during a live deletion
saga. `supabase/tests/disabled_consent.test.sql` and `account_deletion.test.sql` are what
prove this against real Postgres rather than the in-memory doubles.
Reasoning: docs/archive/2026-09-18_account-and-trust.md §3 (decisions D1, D2, D3, D5,
D6b), §3-M4/M5, §5.

---

## Reader quota

The three quota tables (`tiers`, `reader_quota_overrides`, `usage_daily`) are Flask-mediated
with no grants at all, not even to `service_role` — see _Two table-access patterns_ for the
privilege shape. `QuotaBackend`'s real implementation
(`web/services/quota_store.py`) exposes exactly three reader-path operations — `claim`,
`release`, `status` — each an atomic `insert … on conflict … where used < limit returning`
inside a `security definer` RPC, chosen over Flask-Limiter specifically because
`memory://` storage does not survive a deploy and a daily allowance must. The day boundary
is the reader's own day in `Asia/Riyadh` (`QUOTA_TIMEZONE`), not UTC, so the allowance
resets when their day does; the Python constant is a mirror the SQL owns the real
arithmetic for and must agree with. A `QuotaClaim` carries its own `day` rather than
recomputing it, so a claim made just before midnight refunds the day it charged if
`release` runs just after.

Failure has two different postures on purpose. An ordinary transport fault makes `claim`
return `None` and the caller streams the answer **uncounted** — an allowance is not a
credential, so a blip must not take chat down. A **configuration-shaped** fault — a
missing function or grant, a stale PostgREST schema cache after a deploy
(`PGRST202`/`PGRST203`/`PGRST301`, `42883`, `42501`) — raises `QuotaUnavailable` instead and
the route answers `503`, because failing open on that class of fault would turn a broken
deploy into unmetered access for every reader indefinitely. `ClaimFailureTolerance` sits
between those two postures: it tracks failures **process-globally** (one worker, one
counter) and only forces a fail-closed `503` after five consecutive failures or 120 seconds
from the first one, closing the gap the 2026-09-07 incident found, where an unclassified
failure type was silently streamed uncounted with no budget at all. `get_reader_quota`
(see _Two table-access patterns_) is what `/api/identity` calls for `status`; it returns
counts and tier labels but deliberately never the operator's `reason` or `set_by` for an
override.

Tier CRUD and per-reader overrides are administrative, not reader-path, and live on
`AdminBackend` (`web/services/admin_store.py`: `list_tiers`, `create_tier`, `update_tier`,
`delete_tier`, `set_reader_quota`) rather than on `QuotaBackend` — one protocol owning tier
management is the point, to keep the reader path and the admin path from drifting apart.
`web/api/admin.py`'s `/admin/api/tiers` routes are gated like every other console route
(bearer, verified, `is_admin`) and every mutation re-validates the actor **inside** the
RPC's own transaction, so a demotion racing a tier edit cannot slip through. Refusals
surface as machine codes (`TQ001`–`TQ009`, `_REFUSAL_CODES` in `admin_store.py`) rather than
a raw `23514`/`23503`, so the console can translate them instead of rendering a `500`.
Reasoning: docs/archive/2026-09-04_reader-quota.md §1.5, §1.6, §2, §5, §6.

Tier membership also moves in bulk, from the People tab rather than one account at a time:
`POST /admin/api/tiers/<key>/members` takes 1–200 reader ids and calls `admin_set_users_tier`,
which moves each id to that tier, writes one `user.tier_change` audit row per reader actually
moved, and returns `{moved_ids, unchanged, missing}`; the route evicts the identity cache for
exactly `moved_ids` and answers `{moved, unchanged, missing}`. The RPC takes the ids as text:
one that is not a uuid names no account and is reported in `missing`, after the actor and
tier checks, so no id can fail the batch with a cast error. It never reads or writes
`reader_quota_overrides` — unlike `admin_set_reader_quota`, which deletes the per-reader
override outright when given a null limit — so a bulk move leaves personal allowances alone.
`GET /admin/api/users?tier=` filters on the real `profiles.tier`, the same column
`admin_list_tiers.member_count` counts, so the two agree when read together (the Tiers
table re-reads its counts after a move made from People); an
orphan account (an auth user with no profile row) surfaces under no tier filter and is not
selectable for a move (`has_profile: false`).

---

## What is mechanically enforced

There is now a lint step — `ruff`, `eslint`/`prettier` and `markdownlint-cli2`, wired
through `pre-commit`, with `mypy` gating the `lint` CI job instead (see `CLAUDE.md`). It
catches style and types. It does **not** catch any of the rules below: those are pytest
assertions, and this list is the real product contract.

The one thing neither the linter nor pytest can reach is the database, because every
Python test mocks the Supabase client. `supabase/tests/*.test.sql` covers that gap and is
run by hand — see the last row of this table.

| Where                           | What it enforces                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_css_contract.py`          | 16 banned physical CSS properties across every `static/css/*.css`. Escape hatch: a trailing `/* physical-ok: <reason> */`. `width`/`height` are tracked but not gated.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `test_frontend_architecture.py` | `static/js/modules/services.js` and `static/js/admin/services.js` import no view or state module and name neither `ErrorHandler` nor `DOMCache`; handlers own every user-facing failure; the console never imports the chat shell (5 forbidden names × 4 files); auth and account flows read the catalogue instead of literals, with the old literals banned by name so a revert fails loudly; 12 English strings frozen verbatim; Arabic covers every key under **both** `runtime` and `page`.                                                                                                                                                                                                                                                                                                                                                                     |
| `test_composer.py`              | Zero icon-webfont markup; more than 10 inline SVGs actually rendered; **every** module URL carries the current `ASSET_VERSION`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `test_deep_link_contract.py`    | No LLM call before the ownership check (`call_count == 0`); foreign ≡ nonexistent, byte-identical; no `Set-Cookie` on `/c/<id>`; uppercase id 301s to canonical; `X-Robots-Tag`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `test_rtl.py`                   | Direction resolution and language selection; `page.*` never reaches the browser.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `test_admin_page.py`            | The closed 11-key `runtime.*` top-level list; the console catalogue never ships to the landing page.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `test_source_panel.py`          | A real bounding box for a passage at 1600px — the shrink-to-fit flex bug that once resolved the source deck to zero by zero.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `test_admin_actor_gate.py`      | Settings write, profile update, user flags and notification create each refuse an absent, unknown, non-administrator or disabled actor, in the in-memory doubles that previously asserted the opposite. Deactivate, delete and purge share the same gate and are **not** separately covered here; `supabase/tests/function_acls.test.sql` is what checks all seven still call it.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `supabase/tests/*.test.sql`     | **Not in CI, and not runnable from it** — CI has no database. 216 assertions on grants, column privileges, both default-ACL layers, function ACLs, `search_path`, reader-to-reader RLS isolation, and — in `rpc_behaviour.test.sql` — what the hardened RPCs actually do when called. Paste into `execute_sql` before and after any migration touching a grant, a policy or a role. This is the only thing in the repository that can fail because of a privilege. _Verified 2026-09-23 by `grep -c "n := n + 1" supabase/tests/rpc_behaviour.test.sql` (63: the 45 of 2026-09-21 plus 18 for bulk tier membership); the other five files were not re-measured today, so this total inherits whatever staleness they already carried against `docs/archive/2026-09-20_admin-analytics-v1.md`'s build record — see that document's Build Record for the arithmetic._ |

CI runs two jobs: `-m "not browser and not integration"` with `--cov=web` but **no
coverage threshold**, and `-m browser --browser chromium`. Note that
`integration`-marked tests are selected by neither job.

---

## Rules that collide

Two rules can both be correct, both be well written, and still meet badly at one
specific point. These are found by hitting them, because nothing else says they will
meet. **Append to this table when you find an eighteenth.**

| #   | The collision                                                                                                                                                                                                                                                                                                                                                                                   | What to do                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | _One concern per migration_ — except the identity cutover had to be **one** migration (column conversion + `handle_new_user` + `admin_update_profile` + grants), because splitting it breaks signup for the length of the deploy                                                                                                                                                                | Trace every writer of a column before converting it. If they cannot be sequenced, one migration is correct and the file header must say why. Precedent: `20260822225415`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| 2   | Migration filenames must match what was applied — but the applied name only exists **after** applying                                                                                                                                                                                                                                                                                           | Renaming is a mandatory fourth step of every migration: write, apply, read the timestamp back, rename. Six files drifted before this was written down.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| 3   | Every page inlines the `runtime.*` tree (reader pages without `runtime.admin`) — but its top-level key list is pinned to eleven names                                                                                                                                                                                                                                                           | A new feature nests under an existing namespace, or changes the test deliberately. See the section above.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| 4   | RLS restricts rows, not columns                                                                                                                                                                                                                                                                                                                                                                 | "Own profile but not own role" needs a column `REVOKE` **plus** a trigger. One policy cannot do it. `supabase/README.md` Rule 6.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| 5   | The product is RTL-first, but all three templates load the **LTR** Bootstrap build (`bootstrap.min.css`, not `bootstrap.rtl.min.css`)                                                                                                                                                                                                                                                           | Some Bootstrap components mirror wrong and must be rebuilt by hand — `.form-check` is the known one. `test_css_contract.py` scans **repository CSS only** and validates nothing about the CDN stylesheet, so it will not catch this.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| 6   | The sidebar macro renders **twice** per page (desktop aside + mobile offcanvas)                                                                                                                                                                                                                                                                                                                 | Nothing needing a unique id can live in it unsuffixed — including ids that `aria-controls` and `aria-labelledby` point at, which resolve against the whole document. It is also why the monogram `view-transition-name` transition was not shipped.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| 7   | Identity is cached 30s for chat speed; the account page needs fresher and richer data                                                                                                                                                                                                                                                                                                           | Both are correct and one path cannot serve both. `get_identity_flags` is a second, uncached RPC, deliberately kept off the hot path.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| 8   | Saving one preference can silently delete the others                                                                                                                                                                                                                                                                                                                                            | `Services.updateProfile` upserts the **whole row**. The safe path for `preferences` is a different method calling `update_own_preferences`, which merges. Never pass `preferences` to `updateProfile`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| 9   | Two caches now sit on the auth path, keyed differently, with opposite outage postures — `IdentityFlagsCache` fails open (an outage still answers, just unprivileged), `TokenVerificationCache` fails closed (an outage refuses and retries)                                                                                                                                                     | Never let one absorb the other. A `user_id`-keyed cache cannot be consulted before a token is verified, and giving token verification a fail-open outage posture would readmit a credential nobody could confirm. See `docs/archive/2026-08-27_token-verification-cache.md` §3.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 10  | `ALTER DEFAULT PRIVILEGES … IN SCHEMA x` cannot revoke a privilege the hard-wired default grants — so a per-schema revoke of `EXECUTE` from `PUBLIC` applies cleanly and changes nothing                                                                                                                                                                                                        | Default ACLs have two layers. Postgres uses the hard-wired `acldefault()` as the base **only when no global row exists**; a per-schema entry is then merged onto that base, and a merge cannot subtract. Table defaults grant nothing to `PUBLIC`, so `IN SCHEMA` works there and hid the rule. Function defaults do grant it, so only the **global** form (no `IN SCHEMA`) closes them — `20260828000737` got this wrong and `20260828100816` corrected it. Rule of thumb: **`IN SCHEMA` adds, global replaces.**                                                                                                                                                                                                                                                                                                                                                                               |
| 11  | Requiring an enabled administrator on every mutating admin RPC (`20260828001543`) made the last-administrator guard (`AD002`) **unreachable**                                                                                                                                                                                                                                                   | Both are correct and the guard stays. To pass the actor gate you must be an enabled administrator; you cannot target yourself (`AD001`); so if the target is another enabled administrator there are at least two, and the count guard never fires. Verified against the live project. Do not delete `AD002` as dead code — it is the backstop if the actor gate is ever loosened. `test_admin_users.py` documents this rather than asserting a state the database can no longer reach.                                                                                                                                                                                                                                                                                                                                                                                                          |
| 12  | The console has two form idioms — `.admin-field` (the settings tab's page-width row, closed by its own hairline) and `.admin-profile-field` (a plain column inside a card) — and both are correct                                                                                                                                                                                               | They are not interchangeable and nothing catches the swap: `.admin-field` inside a bordered card draws a rule under every control and reads as a table. Settings rows use the first, editor cards (profile, daily allowance, tier form) use the second. DESIGN.md, _Console forms_.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| 13  | Tier labels are stored in both languages, because every reader sees one in their own — but a console that prints both ignores the language toggle it just obeyed everywhere else                                                                                                                                                                                                                | Author both, display one. The form keeps `label_en` and `label_ar`; every surface that _shows_ a label resolves `I18n.lang`. The key is not a label and stays as it is in both. `test_admin_browser.py` pins both directions. DESIGN.md, _Operator-authored bilingual data_.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| 14  | `describeAction` falls back to the raw action string on purpose — "an unknown action showing its raw identifier is honest; guessing a translation from a dotted name would produce confident nonsense in Arabic" — and that honest fallback is what hid five missing labels for a day                                                                                                           | An audit action is a **three**-file join: `admin_store.py` writes it, `ACTION_KEYS` in `ui.js` maps it, both catalogues translate it. Nothing connected them, so `tier.create` and four others rendered as dotted identifiers in the one table whose purpose is to be readable afterwards. `test_admin_page.py` now walks all three. Keep the fallback; it is still right for an action a newer server records.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 15  | An `inline-flex` toolbar inside `.admin-panel-body`, which is a flex **column**                                                                                                                                                                                                                                                                                                                 | `align-items: stretch` is the default, so the toolbar spans the panel, its select eats the free space, and a sibling button is squeezed until its label wraps. `align-self: start` opts out; children that must not shrink need `flex: 0 0 auto`, and Bootstrap 5 no longer supplies `.btn { white-space: nowrap }`. This is why "Clear all" shipped as two stacked words.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| 16  | _Never proxy a credential to GoTrue from this host_ — the recorded reason `/auth/login` was deleted — against _the server must verify step-up before it will delete an account_                                                                                                                                                                                                                 | Both stand, and the retirement paragraph above is **not** an unconditional rule. What it bans is proxying the **sign-in path**: unauthenticated, unbounded, and the one place GoTrue's per-IP `/token` limiter is the only durable thing counting. Deletion step-up is a single privileged action behind an already-authenticated bearer, and a bearer alone must not delete an account — on a shared machine the borrowed token is the ordinary case. The exception is only safe with its compensating control, which is therefore **mandatory, not optional**: a durable per-account throttle on our side (`step_up_attempts`, 5 failures per 15 minutes then a 15-minute lockout, `20260918234736`), because the Flask limiter in front of it is `memory://` and `--max-requests 1000` resets its counters routinely. **Do not add a second server-side GoTrue credential call without one.** |
| 17  | `supabase/README.md`'s RPC contract point 5 said `p_owner_id` is the first argument on every `security definer` function — but `admin_list_tiers`, `admin_list_users`, `admin_get_user` and the two analytics aggregates (`admin_top_questions`, `admin_citation_stats`) are `service_role`-only reads with no owner argument at all, gated by the console's `_gate()` `before_request` instead | Both stand. Point 5 governs a _reader-facing_ function scoping rows to the one signed-in account; an operator-facing `admin_*` reader answers a different question — "what does the whole system look like" — and is gated by blueprint identity, not a row filter. `supabase/README.md` now states the scope explicitly rather than unconditionally. Points 1–4 (`security definer`, empty `search_path`, `revoke`/`grant` to `service_role` only) still apply to every one of them without exception; only point 5 was ever in question.                                                                                                                                                                                                                                                                                                                                                       |

---

## Deliberately not built

Listed so the absence reads as a decision rather than an oversight: resumable streams;
cross-tab synchronisation; conversation branching, merging or message editing;
per-message deletion; background completion; model-generated titles; a virtualised
conversation list; browser-direct writes to the chat tables; deleting durable history
on logout. (Reversed 2026-09-18 per owner decision: the per-member conversation
viewer in `TODO.md` is now wanted work — the transcript-console exclusion this
line used to carry no longer applies.)

On the reader quota specifically: **token credits** (the OpenAI stream ignores usage
chunks and a tokenizer estimate is not a billing ledger), **time-windowed access** as
such (a per-account override may be time-boxed, but sign-in itself is not), and a
**fixed promo pool** of bonus messages drawn once the daily allowance is spent — that
last one is designed in full, with its schema corrected, in
[`the archived reader-quota plan`](archive/2026-09-04_reader-quota.md) §12, and deliberately not built until
the meter has produced real numbers to decide it on.
