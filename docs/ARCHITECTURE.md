STATUS: CURRENT AUTHORITY — the live system contract. Last verified against code 2026-08-28.

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

| Subject                                          | Authority                                                                                                                              |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| Conversations, chat, persistence                 | This file. Then `docs/archive/2026-08-22_per-tab-deep-linking.md`, then `2026-08-20_chat-persistence.md`, then `TODO.md`. Newest wins. |
| Copy, product claims, terminology                | `docs/PRODUCT.md`                                                                                                                      |
| Design, tokens, RTL presentation                 | `DESIGN.md`                                                                                                                            |
| Database, migrations, RLS                        | `supabase/README.md` — it sits beside the migrations, which is where you are when you need it                                          |
| Deployment, DNS, mail, anything outside the repo | `docs/OPERATIONS.md`                                                                                                                   |
| A document's index vs. its own body              | The body.                                                                                                                              |
| **Anything vs. a passing test**                  | **The test.** It is the only artifact here that cannot silently drift.                                                                 |

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

---

## Single worker

```bash
gunicorn --workers 1 --threads 8 --timeout 300 "web.api.app:create_app()"
```

The app logs a warning at startup if `WEB_CONCURRENCY` is not `1`.

**The current reason is the in-RAM FAISS index and the sentence-transformers model.**
A second worker means a second copy of both.

The reason you will find in older documents — that Flask writes `Set-Cookie` before the
WSGI server iterates a streaming body, so conversation history had to live in a
process-local store — **is retired**. History is durable in Postgres now. The
constraint outlived its original justification; the justification did not.

Two things still depend on single-worker and would need replacing before it changes:

- `ConversationStore` — the computed prompt window, keyed `(owner, conversation)`. It
  is **not** a cache of the stored rows; making it write-through would let a restart
  change the prompt mid-conversation. Its `clear()` is deliberately owner-blind:
  under-purging leaks one reader's questions into another's prompt.
- `_InFlightGenerations` — a counted claim on `(owner, conversation)`. Select and
  delete answer **409 `generation_in_flight`** while a claim is held. The replacement
  at multi-worker is a tombstone table, not a bigger dict.

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

Every page inlines the whole `runtime:` subtree of `web/i18n/en.yaml` as
`window.__I18N`. The server-only `page:` subtree must never reach the browser
(`test_rtl.py`, `test_admin_page.py`).

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
`chat_archive`, `audit_log`, `app_settings`:

- RLS **on**, and for writes **no policies at all**.
- `revoke all from anon, authenticated`.
- All writes go through `security definer` RPCs, every one filtered on `p_owner_id`.
- **Do not "fix" this by adding a policy.** RLS here is defence in depth, not the
  coordinator of a workflow that spans a process-local cache, an in-flight lock and
  three tables. A browser-writable `chat_messages` is a provenance-forgery primitive.

Readers get `select` and `delete` on their own `chat_sessions` rows via RLS, and
`select` on their own messages and sources. There is no insert or update policy on any
chat table, and none should be added.

**Browser-direct tables** — `profiles`, and only `profiles`:

- Read and write straight from the browser to PostgREST under RLS.
- Column protection is a **column-level `REVOKE` plus a trigger**, because RLS
  restricts rows and cannot restrict columns. `profiles.role`, `tier` and
  `is_disabled` are writable only by the service role.
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

**Not every route under `auth_bp` is actually used.** `POST /auth/login` is
browser-direct — `Services.login` calls `supabase.auth.signInWithPassword`
straight to GoTrue with the public anon key, and nothing gates it, so moving
it server-side would be cost without a property. `POST /auth/signup` used to
be the same shape and was dead code in production as a result — nothing
called it — until the registrations-pause work
(`docs/registrations-pause-plan.md`) moved `Services.signup` onto it, which
is the only way an operator's pause can actually be enforced. `POST
/auth/recover` and `POST /auth/logout` were already server-mediated before
that, for reasons specific to each (recovery: PKCE, see
`web/services/account_recovery.py`'s module docstring). So today: **signup,
recovery and logout are server-mediated; login is browser-direct.**

Limits on `/account/api/*` key on the **authenticated user id**, not the IP
(`_account_rate_key`) — otherwise it is "two exports per ten minutes _per building_".

---

## Rate limits

Flask-Limiter, `memory://` storage, keyed on the remote address unless noted.

| Scope                                               | Limit                                  |
| --------------------------------------------------- | -------------------------------------- |
| Global default                                      | 200/day, 50/hour, 10/minute            |
| Chat (`/api/chat` and `/api/chat/stream`, shared)   | 15/minute                              |
| `GET /api/chat/history`                             | 30/minute                              |
| `/api/chat/sessions` (list, select, rename, delete) | 60/minute                              |
| `POST /auth/recover`                                | 5/minute                               |
| `POST /auth/signup`                                 | 5/minute                               |
| `GET /account/api/export`                           | 2 per 10 minutes, **keyed per reader** |
| `DELETE /account/api/conversations`                 | 10/hour, **keyed per reader**          |
| `admin_bp` (whole blueprint)                        | 60/minute                              |
| `admin.revoke_sessions`, `admin.change_email`       | 10/minute                              |

`history_api` and `sessions_api` carry their own limits **specifically so that
ordinary navigation cannot spend the 200/day budget an office behind one NAT shares
with chat itself.** An explicit limit replaces the defaults in Flask-Limiter; that is
the mechanism being used deliberately.

`memory://` counters are fine for a burst limit and **not** for a daily quota. A real
per-reader quota needs a durable row and one atomic
`insert … on conflict … where used < limit returning`, taken in the view body **before
the generator**, so a denial is a 429 and not a dying SSE stream. Not built — see
`TODO.md`.

---

## What is mechanically enforced

There is now a lint step — `ruff`, `eslint`/`prettier` and `markdownlint-cli2`, wired
through `pre-commit`, with `mypy` gating the `lint` CI job instead (see `CLAUDE.md`). It
catches style and types. It does **not** catch any of the rules below: those are pytest
assertions, and this list is the real product contract.

The one thing neither the linter nor pytest can reach is the database, because every
Python test mocks the Supabase client. `supabase/tests/*.test.sql` covers that gap and is
run by hand — see the last row of this table.

| Where                           | What it enforces                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_css_contract.py`          | 16 banned physical CSS properties across every `static/css/*.css`. Escape hatch: a trailing `/* physical-ok: <reason> */`. `width`/`height` are tracked but not gated.                                                                                                                                                                                                                                                                                                                          |
| `test_frontend_architecture.py` | `static/js/modules/services.js` and `static/js/admin/services.js` import no view or state module and name neither `ErrorHandler` nor `DOMCache`; handlers own every user-facing failure; the console never imports the chat shell (5 forbidden names × 4 files); auth and account flows read the catalogue instead of literals, with the old literals banned by name so a revert fails loudly; 12 English strings frozen verbatim; Arabic covers every key under **both** `runtime` and `page`. |
| `test_composer.py`              | Zero icon-webfont markup; more than 10 inline SVGs actually rendered; **every** module URL carries the current `ASSET_VERSION`.                                                                                                                                                                                                                                                                                                                                                                 |
| `test_deep_link_contract.py`    | No LLM call before the ownership check (`call_count == 0`); foreign ≡ nonexistent, byte-identical; no `Set-Cookie` on `/c/<id>`; uppercase id 301s to canonical; `X-Robots-Tag`.                                                                                                                                                                                                                                                                                                                |
| `test_rtl.py`                   | Direction resolution and language selection; `page.*` never reaches the browser.                                                                                                                                                                                                                                                                                                                                                                                                                |
| `test_admin_page.py`            | The closed 11-key `runtime.*` top-level list; the console catalogue never ships to the landing page.                                                                                                                                                                                                                                                                                                                                                                                            |
| `test_source_panel.py`          | A real bounding box for a passage at 1600px — the shrink-to-fit flex bug that once resolved the source deck to zero by zero.                                                                                                                                                                                                                                                                                                                                                                    |
| `test_admin_actor_gate.py`      | Settings write, profile update, user flags and notification create each refuse an absent, unknown, non-administrator or disabled actor, in the in-memory doubles that previously asserted the opposite. Deactivate, delete and purge share the same gate and are **not** separately covered here; `supabase/tests/function_acls.test.sql` is what checks all seven still call it.                                                                                                               |
| `supabase/tests/*.test.sql`     | **Not in CI, and not runnable from it** — CI has no database. 176 assertions on grants, column privileges, both default-ACL layers, function ACLs, `search_path`, reader-to-reader RLS isolation, and — in `rpc_behaviour.test.sql` — what the hardened RPCs actually do when called. Paste into `execute_sql` before and after any migration touching a grant, a policy or a role. This is the only thing in the repository that can fail because of a privilege.                              |

CI runs two jobs: `-m "not browser and not integration"` with `--cov=web` but **no
coverage threshold**, and `-m browser --browser chromium`. Note that
`integration`-marked tests are selected by neither job.

---

## Rules that collide

Two rules can both be correct, both be well written, and still meet badly at one
specific point. These are found by hitting them, because nothing else says they will
meet. **Append to this table when you find an eleventh.**

| #   | The collision                                                                                                                                                                                                                               | What to do                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | _One concern per migration_ — except the identity cutover had to be **one** migration (column conversion + `handle_new_user` + `admin_update_profile` + grants), because splitting it breaks signup for the length of the deploy            | Trace every writer of a column before converting it. If they cannot be sequenced, one migration is correct and the file header must say why. Precedent: `20260822225415`.                                                                                                                                                                                                                                                                                                                                          |
| 2   | Migration filenames must match what was applied — but the applied name only exists **after** applying                                                                                                                                       | Renaming is a mandatory fourth step of every migration: write, apply, read the timestamp back, rename. Six files drifted before this was written down.                                                                                                                                                                                                                                                                                                                                                             |
| 3   | Every page inlines the whole `runtime.*` tree — but its top-level key list is pinned to eleven names                                                                                                                                        | A new feature nests under an existing namespace, or changes the test deliberately. See the section above.                                                                                                                                                                                                                                                                                                                                                                                                          |
| 4   | RLS restricts rows, not columns                                                                                                                                                                                                             | "Own profile but not own role" needs a column `REVOKE` **plus** a trigger. One policy cannot do it. `supabase/README.md` Rule 6.                                                                                                                                                                                                                                                                                                                                                                                   |
| 5   | The product is RTL-first, but all three templates load the **LTR** Bootstrap build (`bootstrap.min.css`, not `bootstrap.rtl.min.css`)                                                                                                       | Some Bootstrap components mirror wrong and must be rebuilt by hand — `.form-check` is the known one. `test_css_contract.py` scans **repository CSS only** and validates nothing about the CDN stylesheet, so it will not catch this.                                                                                                                                                                                                                                                                               |
| 6   | The sidebar macro renders **twice** per page (desktop aside + mobile offcanvas)                                                                                                                                                             | Nothing needing a unique id can live in it unsuffixed — including ids that `aria-controls` and `aria-labelledby` point at, which resolve against the whole document. It is also why the monogram `view-transition-name` transition was not shipped.                                                                                                                                                                                                                                                                |
| 7   | Identity is cached 30s for chat speed; the account page needs fresher and richer data                                                                                                                                                       | Both are correct and one path cannot serve both. `get_identity_flags` is a second, uncached RPC, deliberately kept off the hot path.                                                                                                                                                                                                                                                                                                                                                                               |
| 8   | Saving one preference can silently delete the others                                                                                                                                                                                        | `Services.updateProfile` upserts the **whole row**. The safe path for `preferences` is a different method calling `update_own_preferences`, which merges. Never pass `preferences` to `updateProfile`.                                                                                                                                                                                                                                                                                                             |
| 9   | Two caches now sit on the auth path, keyed differently, with opposite outage postures — `IdentityFlagsCache` fails open (an outage still answers, just unprivileged), `TokenVerificationCache` fails closed (an outage refuses and retries) | Never let one absorb the other. A `user_id`-keyed cache cannot be consulted before a token is verified, and giving token verification a fail-open outage posture would readmit a credential nobody could confirm. See `docs/archive/2026-08-27_token-verification-cache.md` §3.                                                                                                                                                                                                                                    |
| 10  | `ALTER DEFAULT PRIVILEGES … IN SCHEMA x` cannot revoke a privilege the hard-wired default grants — so a per-schema revoke of `EXECUTE` from `PUBLIC` applies cleanly and changes nothing                                                    | Default ACLs have two layers. Postgres uses the hard-wired `acldefault()` as the base **only when no global row exists**; a per-schema entry is then merged onto that base, and a merge cannot subtract. Table defaults grant nothing to `PUBLIC`, so `IN SCHEMA` works there and hid the rule. Function defaults do grant it, so only the **global** form (no `IN SCHEMA`) closes them — `20260828000737` got this wrong and `20260828100816` corrected it. Rule of thumb: **`IN SCHEMA` adds, global replaces.** |
| 11  | Requiring an enabled administrator on every mutating admin RPC (`20260828001543`) made the last-administrator guard (`AD002`) **unreachable**                                                                                               | Both are correct and the guard stays. To pass the actor gate you must be an enabled administrator; you cannot target yourself (`AD001`); so if the target is another enabled administrator there are at least two, and the count guard never fires. Verified against the live project. Do not delete `AD002` as dead code — it is the backstop if the actor gate is ever loosened. `test_admin_users.py` documents this rather than asserting a state the database can no longer reach.                            |

---

## Deliberately not built

Listed so the absence reads as a decision rather than an oversight: resumable streams;
cross-tab synchronisation; conversation branching, merging or message editing;
per-message deletion; background completion; model-generated titles; a virtualised
conversation list; browser-direct writes to the chat tables; deleting durable history
on logout; a transcript console page for operators; and any surface that lets an
operator read what a reader asked.
