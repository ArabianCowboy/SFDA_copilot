# Per-tab conversation pointer + `/c/<id>` deep-linking — Implementation Plan

**Status:** All of §8 (steps 0–6) implemented and verified 2026-08-22. Steps 0–4: Cache-Control on
the page routes, the `conftest.py` context-level fixtures, both migrations (applied and verified
against the live Supabase project), the full server request/response contract (§3), and the full
client — `route.js`, the navigation state machine, the first-turn transition, Back/Forward and
bfcache handling, the sidebar's epoch-based navigation, deletion of the conversation on screen, and
the recovery-flow fix. Steps 5–6: `/select` deleted, `active` dropped from the sessions list, undo
state (`prev_conv_id`/`prev_chat_history`) and the whole resume surface
(`CHAT_RESUME_LATEST_SESSION`, `latest_session`, `resumed`, the resumed-notice UI and its i18n keys)
removed, `_resolve_conversation_id` collapsed, and the cookie fallback taken out of
`_validate_chat_request` and both chat routes. Decision 1 = (a); Decision 2 = replace the toast with
Back.

**One deletion beyond §5's own list, recorded rather than absorbed:** `POST /api/conversation/reset`
is gone too. §9 had assumed it would remain, forgeable on its default branch; by the time steps 5–6
were implemented the step-3/4 client no longer called it at all — `Handlers.handleNewChat` already
did the whole of "New chat" client-side, with zero server round trip — and its only remaining job,
rotating `session["conv_id"]`, has no object once that key is deleted. Two now-dead client functions
went with it: `Services.resetConversation` and `Services.selectSession` (the latter's route was
already gone via §5.2). `test_new_chat.py`'s server-side rotation/undo/legacy-migration tests, which
exercised the deleted route directly, are deleted with it; the browser-level control they verified
was already covered by the same file's Playwright tests against the real client behaviour.

24 new server tests (`test_deep_link_contract.py`), 3 new multi-tab tests
(`test_multi_tab_conversations.py`, §7.2's core proof), full existing suite green — 843 tests,
including the browser suite, plus 2 pre-existing failures in `test_auth.py` unrelated to this plan
(they require a live server on `localhost:5000`). Written 2026-08-22; revised the same day after
three adversarial reviews, which overturned four load-bearing pieces of the first draft (§11).
Closes two `TODO.md` entries at once — "The active conversation is per-browser, not per-tab"
(`TODO.md:787`, now struck) and roadmap §10.3 "Deep-linking (`/c/<id>`)"
(`docs/chat-persistence-implementation-roadmap.md:1054-1062`) — which that entry already argues
are one change: *"both need a conversation id that travels with the request rather than with the
browser."*

**This plan disagrees with `TODO.md` about the mechanism, and §1 is that argument.** `TODO.md:805-808`
specifies "a tab-scoped pointer — held in `sessionStorage`". The research says `sessionStorage` is
the wrong store and that the pointer should not exist at all. The conclusion — an id that travels
with the request, validated against `g.identity`, never trusted as an owner claim — is unchanged.
Only where it lives changes.

**How this document was built — two rounds.**

*Round 1 — three independent passes.* A read-only exploration agent mapped `_resolve_conversation_id`,
the three chat routes, `ConversationStore`, `_InFlightGenerations`, identity resolution, the sidebar
frontend, page routing, the language toggle, the test suite, and web-storage/CSRF posture. A research
agent read the source of six production chat implementations — `vercel/ai-chatbot` (current `main`
and the older widely-tutorialised revision), `huggingface/chat-ui`, LibreChat, Open WebUI, Lobe Chat,
`chatbot-ui`, `assistant-ui` — plus shipped bundles from ChatGPT, Claude.ai, Gemini and Perplexity,
and the RFC/OWASP/W3C-TAG literature. `agy-delegate` (Antigravity, `gemini-3.7-flash-high`) was asked
not for a plan but for the mistakes developers make and the questions they answer too late.

*Round 2 — three adversarial reviews of the round-1 draft, in separate lanes, all read-only.*
`opencode-delegate` (OpenCode, `gpt-5.6-terra`, `high`, `--read-only`) on architecture and
correctness; `agy-delegate` (`gemini-3.7-flash-high`) on operations, sequencing and testing, and
made to defend or concede three of its own round-1 recommendations this draft had rejected;
`claude-delegate` (Claude Sonnet, `high`, `--read-only`) on security. Between them they broke §3.4
outright, corrected a migration default that would have failed 100% of new conversations on deploy,
found five client-side state gaps, and surfaced a pre-existing CSRF hole this change is the natural
place to close. §11 records what each earned.

*Round 3 — an independent reviewer outside that fleet*, reviewing the round-2 draft cold. It found
the one thing all three lanes and this document had missed (`handlers.js:1361`), plus four
corrections; one of its twelve findings was wrong and two had already been fixed in round 2, which
is the expected cost of reviewing in parallel rather than in sequence. §11.5.

*Documentation checks.* PostgREST's and Playwright's current docs were fetched (`ctx7`) to verify
the two load-bearing claims no amount of reading this repo could settle — RPC overload resolution
with a defaulted argument (§3.6) and context-level request routing (§7.1). Both held; both added a
step nobody had raised. §11.6.

**Every claim any pass made about this codebase was re-checked against the source before being
trusted into this document**, including the reviews' own claims — one of which (§11.1) was
verified to be *worse* than the reviewer stated, and one of which (§11.5) was verified to be wrong. Where a pass was wrong or out of scope, §0.2 says
so. Where a review overturned this document, §0.3 says so rather than quietly absorbing it.

---

## 0. Verified against the current source

### 0.1 Confirmed

| Claim | File:Line | Status |
|---|---|---|
| `_resolve_conversation_id` is the single current-session rule; exactly three callers | `web/api/app.py:671-763`; callers `:2069`, `:2533`, `:2824` | ✅ confirmed |
| The rule: *"A cookie that names a conversation is honoured as-is. Only a cookie with no conversation at all resumes the owner's most recent one."* | `app.py:676-677` | ✅ confirmed |
| `session["conv_id"]` has **eight** write sites and three pop sites | writes `:718`, `:755`, `:758`, `:762`, `:2383`, `:2503`, `:2944`, `:2996`; pops `:2078`, `:2137`, `auth.py:80` | ✅ confirmed — and no others on the normal path (independently re-checked in review) |
| `/api/chat/history` takes no session id, by design | `app.py:2048-2054` | ✅ confirmed |
| …and that GET **writes** the session cookie | `app.py:2056-2058` | ✅ confirmed |
| `_validate_chat_request` accepts `query`, `category`, `lang`, `client_request_id` — **no** conversation id field | `app.py:1985-2030` | ✅ confirmed |
| …and parses with **`request.get_json(force=True, silent=True)`** — the only `force=True` in the app | `app.py:1987`; other sites `:2408`, `:2929` use `silent=True` alone | ✅ confirmed — load-bearing for §3.6 |
| The client always sends `Content-Type: application/json` on chat requests | `services.js:179`, `:221`, `:340`, `:388`, `:410`, `:615` | ✅ confirmed — so §3.6's fix breaks nothing |
| `client_request_id` is already **client-minted**, canonicalised, malformed → fresh id rather than 400 | `app.py:2019-2027` | ✅ confirmed |
| `chat_append_turn` takes `p_session_id`, **lazily creates** `insert … on conflict (id) do nothing`, then verifies ownership `where id = p_session_id and owner_id = p_owner_id for update`, raising if null | `20260820131914_chat_session_persistence.sql:376-397` | ✅ confirmed |
| **`p_owner_id` is always server-derived from `g.identity`, never from the request body** | `app.py:2523` via `_durable_owner()` (`:636-662`) | ✅ confirmed — why a hostile id can only ever create a row owned by the caller |
| **`_persist_turn`'s contract is that it never raises** — it catches bare `Exception` and returns `False`, deliberately, so a filing failure never discards a good answer | `app.py:1134-1145` | ✅ confirmed — the reason §3.4 was rewritten |
| Streaming order is `yield sse("final", …)` → `store.append_turn(…)` → `_persist_turn(…)` | `app.py:2610`, `:2642`, `:2661` | ✅ confirmed — the RAM write precedes and is independent of the durable one |
| The blocking route has the same ordering and answers `200` with `persisted: false` | `app.py:2846-2879` | ✅ confirmed |
| `chat_load_session` filters `owner_id and session_id`; a foreign id returns **zero rows**, not an error | migration `:556-559` | ✅ confirmed |
| *"An unowned id is never distinguishable from an absent one."* | `20260821145319_chat_navigation_rpcs.sql:36` | ✅ confirmed — 404 discipline is house policy |
| `/select` already returns one answer for both: *"Not yours, or not there. Deliberately one answer."* | `app.py:2371` | ✅ confirmed |
| **The drop-and-recreate precedent is `20260821145416`, not `20260820131914`** — the latter's `:514-519` is `revoke`/`grant` | `20260821145416_chat_first_turn_title.sql:68-70` | ✅ corrected in review |
| …and that migration already ruled on defaults for this exact function: `p_title` is *"Last, and defaulted, so the argument list stays append-only. A caller that has not been updated yet still resolves, and files an untitled session rather than failing"* | same file:83-86 | ✅ confirmed — decides §3.5 |
| `ConversationStore` is keyed `(owner_id, conversation_id)`; the docstring says the re-key was done **for this feature**: *"Phase 2's deep links would let one arrive from a URL."* | `web/services/conversation_store.py:36-51` | ✅ confirmed |
| `ConversationStore.clear` is deliberately **not** owner-scoped | same file:192-207 | ✅ confirmed |
| `_InFlightGenerations` keys `(str(owner_id), str(conversation_id))`, **counted not flagged**, explicitly because *"one reader can legitimately have two submissions in flight against one conversation (two tabs, or a retry)"* | `app.py:996-998`, `:1013` | ✅ confirmed |
| The hold is released in a `finally`, naming `GeneratorExit` as *"the ORDINARY way this generator ends"*; it is claimed in the **view body** because the generator does not start until the WSGI server iterates it | `app.py:2543-2550`, `:2745-2756`, `:1019-1023` | ✅ confirmed |
| Session writes must happen in the view body — Flask writes `Set-Cookie` in `finalize_request()` before the generator is iterated | `app.py:2526-2531` | ✅ confirmed — and removing the cookie does **not** obsolete it (§5.1) |
| All chat/session routes are `@auth_required`; anonymous readers never reach them | `app.py:569-577` | ✅ confirmed |
| Every asset URL in `index.html` is `url_for()`-absolute, including the ES import map | `index.html:42-46`, `:98`, `:697`; `app.py:1849-1857` | ✅ confirmed — path depth cannot break asset resolution |
| `Referrer-Policy: strict-origin-when-cross-origin` and `X-Frame-Options: SAMEORIGIN` are already served, both as **Talisman defaults** applied to every response | verified in `.venv`; `app.py:1375-1379` | ✅ confirmed — clickjacking on `/c/<id>` needs no new code; §6.1 pins the referrer one |
| CSP `img-src` is `'self' data: https:` — an unrestricted HTTPS wildcard; `script-src` trusts three third-party origins | `app.py:1354`, `:1356` | ✅ confirmed — see §6.4 |
| Language toggle is cookie + full navigation, preserving the path | `i18n.js:45-67`; `pick_lang` precedence `?lang=` → cookie → `Accept-Language` | ✅ confirmed |
| There is **no** `robots.txt`; `admin.html:18` already ships a robots meta, `index.html` does not | `ls`; grep | ✅ confirmed |
| There is **no CSRF protection anywhere**, acknowledged in-source | `admin.py:18-19` | ✅ confirmed |
| `_get_token_from_request` accepts the `sb-access-token` **cookie** and `session["supabase_access_token"]` | `app.py:269-273` | ✅ confirmed |
| ~~`SESSION_COOKIE_SAMESITE` is never configured~~ — **wrong, caught during implementation.** `Talisman(app, ...)` sets it unconditionally via its own default: `'Lax'`, verified by reading `app.config['SESSION_COOKIE_SAMESITE']` off a real `create_app()` | `flask_talisman/talisman.py:199`; `DEFAULT_SESSION_COOKIE_SAMESITE = "Lax"` | ❌ every round — 3 delegate reviews, the security review, and this document's own §0.1 — stated this as confirmed. See §3.5. |
| No client-side router and only two HTML routes app-wide | `app.py:1905`, `admin.py:101`; `app.js:91-93` | ✅ confirmed |
| **There is exactly one History-API call in the codebase, and it hard-codes `/`**: `window.history.replaceState({}, '', '/')` in the password-recovery flow. No `pushState`, no `popstate`, no `pageshow` handler anywhere | `static/js/modules/handlers.js:1361` | ✅ confirmed — round-1 said "nothing to integrate with"; that was wrong (§4.8) |
| **`index()` sets no `Cache-Control`** — the only two in the app are on an unrelated route and on `/api/chat/history` | `app.py:1052`, `:2158`; absent at `:1905-1920` | ✅ confirmed — decides §8's step 0 |
| `index()` interpolates `is_authenticated` and `user_email` into the template, so the HTML **does** vary by reader | `app.py:1908-1911` | ✅ confirmed — §3.1's claim needed narrowing |
| **The resolved `conversation_id` is already echoed on every chat route** — stream `meta` and `final`, blocking response, history response | `app.py:2559`, `:2615`, `:2869`, `:2148` | ✅ confirmed — the field exists; only the client's reconciliation rule is new (§3.2) |
| PostgREST: *"If a function parameter has a default value, it can be omitted in the API request"*, and overloads resolve by argument count — but *"overloaded functions with the same argument names but different types are not supported"* | `/postgrest/postgrest` docs, `references/api/functions.md` | ✅ confirmed — validates §3.6's `default true`, and why the old signature must be dropped rather than left alongside |
| PostgREST answers an unknown signature with `404 PGRST202 "Could not find the … function in the schema cache"` | same, `references/errors.md` | ✅ confirmed — the failure mode if code deploys before schema |
| `browserContext.route()` *"Intercepts network requests made by any page in the browser context"*; `storage_state` covers cookies + localStorage + IndexedDB and **not** `sessionStorage` | `/websites/playwright_dev`, `class-browsercontext` | ✅ confirmed — §7.1's fix is the documented mechanism, and the omission of `sessionStorage` reinforces §1.2 |
| The installed Playwright has `BrowserContext.route` and `storage_state` but **not** `page.session_storage` / `page.local_storage` | verified in `.venv` | ✅ confirmed — §7 must assert storage via `page.evaluate`, not the newer `WebStorage` API |
| No bundler, no `node_modules`; native ES modules + an import map that globs the directory at import time | `package.json`; `app.py:249`, `:1849-1857` | ✅ confirmed |
| **Every Playwright mock in `conftest.py` is `page.route(...)`; there is not one `context.route(...)`**, and the Supabase mock stores auth in per-page `window.__supabaseState` | `conftest.py:16`, `:380`, `:426`, `:437-468`, `:499`, `:516` | ✅ confirmed — §7.1 is blocked on this |
| `conversation_of()` reads `flask_session["conv_id"]` in **both** test helper modules | `test_chat_persistence.py:102-104`; `test_chat_sessions.py:97-99` | ✅ confirmed — decides §7.3 |
| Werkzeug's `<uuid:>` regex is `[A-Fa-f0-9]{8}-…` — it **accepts uppercase**, rejects undashed/braced/URN, and `to_python` normalises via `uuid.UUID()` | verified in `.venv`; `werkzeug/routing/converters.py` | ✅ confirmed — a strict subset of `canonical_uuid`, so no id can diverge between them; but two URL casings map to one conversation (§4.6) |

### 0.2 Where a round-1 pass was wrong, or out of scope

- **Anonymous-reader hazards cannot arise.** Every chat route is `@auth_required`. Dropped.
- **The in-flight-lock leak is already fixed**, with a source comment naming the exact failure.
  Kept only as a regression note in §7.
- **`Referrer-Policy` is already mitigated** — by a library default, not by this app. §6.1 converts
  it into a choice.
- **A round-1 pass asserted `web/services/conversation_store.py` against this document's
  `web/api/` assumption and was right.** Recorded because the correction went the other way.
- **Perplexity is not public-by-default for SEO.** The pass corrected its own premise. Nothing here
  rests on it.

### 0.3 What round 2 overturned in this document

Recorded here rather than silently absorbed, because a plan that hides its own corrections teaches
nothing. Full accounting in §11.

1. **§3.4's `p_allow_create` fired too late to do what it claimed** — the mechanism was sound and
   the placement was wrong. Replaced by a preflight (§3.4).
2. **The migration default was backwards** — `default false` would have failed every new
   conversation during the deploy window (§3.5).
3. **§7's "must keep passing unchanged" list was wrong** — it confused a surviving *property* with
   a surviving *test* (§7.3).
4. **§8's hard cut ignored tabs already open at deploy time** (§8).

A third review round (a reviewer working independently of the three above) added five more, all
verified:

5. **"Nothing to integrate with" was false** — `handlers.js:1361` already calls `replaceState` and
   hard-codes `/`, silently erasing a deep link on password recovery (§4.8).
6. **"Byte-identical HTML" was imprecise** and made one proposed test unwritable (§3.1, §7.3).
7. **A failed sidebar navigation leaves the URL lying**, because `pushState` fires before the fetch
   that may 404 (§4.3).
8. **The deletion inventory was incomplete** — it missed the entire resume/resumed-notice surface
   (§5.5), and missed that Decision 1(a) closes a gap the code documents as knowingly open.
9. **`index.html` carries no `Cache-Control`**, which extends §8's old-client window indefinitely.

---

## 1. Architecture — the URL is the pointer. There is no per-tab pointer.

**Locked.** It reverses `TODO.md`'s stated mechanism, and both round-2 reviewers who were asked
about it concurred.

### 1.1 What the prior art shows

Six independent implementations read at source level. **None keeps a server-side "current
conversation" pointer, and none keeps a per-tab client one either.** The session cookie carries
identity; the URL carries the conversation.

| Project | Conversation id lives in | Server-side "current conversation"? |
|---|---|---|
| `vercel/ai-chatbot` | `/chat/<uuid>` path | No — cookies hold `sidebar_state`, `chat-model` |
| `huggingface/chat-ui` | `/conversation/<ObjectId>` path | No — `authCondition()` returns identity only |
| LibreChat | `/c/:conversationId` path | No — JWT; `req.session` is OIDC tokens only |
| Open WebUI | `/c/[id]` path | No — the socket pool maps sid→user, never sid→chat |
| Lobe Chat | `?session=` v1, path segment v2 | No |
| `assistant-ui` | refuses to own it — `threadId` in, `onThreadIdChange` out | n/a |

Lobe Chat states the doctrine in a source comment: *"URL is the source of truth for workspace
context… URL is a passive source, not an explicit user intent."*

You do not *add* per-tab state; you *delete* the shared state and let the URL be the state.
Deep-linking then falls out for free — the same observation `TODO.md:814-817` makes from the other
direction.

Corroboration by omission: LibreChat, Lobe Chat, `chatbot-ui` and `assistant-ui` have **zero**
`BroadcastChannel` or `storage`-event listeners for chat identity.

### 1.2 Why `sessionStorage` is the wrong store for *this* pointer

`services.js:131-149` is a correct use of `sessionStorage` and this plan keeps it. It does not
generalise, for one reason:

> **`sessionStorage` is cloned verbatim on tab duplication.** Ctrl+Click, right-click →
> "Duplicate Tab", and `window.open()` without `noopener` all copy it into the new tab in
> Chromium, Firefox and WebKit.

So a `sessionStorage` pointer reintroduces the exact collision it exists to prevent, in the flow
users hit most. Tab B starts pointing at Tab A's conversation, and the first question typed into B
lands in A — `TODO.md:793-796` verbatim, with a new cause.

The URL does not have this failure. A duplicated tab showing `/c/A` genuinely *is* a second view of
A, because that is what the user asked for by duplicating it.

Three further hazards the URL avoids: session restore (`Ctrl+Shift+T`) resurrects a pointer to a
conversation deleted meanwhile; private windows and locked-down WebViews **throw** on `setItem`
rather than degrading; and a brand-new tab has no pointer at all, which puts you back to inventing
a server-side fallback.

Asked in round 2 whether a `sessionStorage` variant survives this, the reviewer conceded it does
not: any workaround needs cross-tab collision negotiation, which trades a deterministic failure for
an asynchronous one.

### 1.3 What this means concretely

- **`/` is a new, empty conversation.** Nothing else.
- **`/c/<uuid>` is that conversation.** The path is the whole pointer.
- **`session["conv_id"]` and `prev_conv_id` are deleted.** §5 lists what falls out with them.
- **No new web-storage key is introduced.** The `sessionStorage`/`localStorage` inventory is
  unchanged. One piece of per-entry state rides `history.state` instead (§4.2) — which is not
  web storage, is scoped to the history entry rather than the tab, and survives reload.

---

## 2. Decisions the owner has to make

### Decision 1 — What happens when a returning reader opens `/`? **BLOCKING.**

Today an empty cookie resumes the reader's most recent conversation
(`CHAT_RESUME_LATEST_SESSION`, `app.py:739-759`). Roadmap §6 records that this flag was deliberately
*"held off for"* two steps and shipped only once hydration was correct. Under URL-as-truth, `/` has
no conversation, so the flag has nowhere to act.

| Option | Behaviour | Cost |
|---|---|---|
| **(a) `/` is always a new chat** — ChatGPT's model, recommended | Resume disappears as an automatic behaviour; the sidebar's top row is one click away | A real, visible product change, and **"sign in on a new device and your conversation is there" is the named casualty** — `app.py:721-723` says that is precisely what the branch is for. Two tests rewritten, and the whole resumed-notice surface deleted (§5.5) |
| **(b) `/` 302-redirects to `/c/<latest>`** | Resume preserved, now visible in the URL | **Rejected.** Opening a second tab lands on the same conversation again — the original collision, restored, in the commonest flow |
| **(c) `/` is a new chat plus a "continue where you left off" affordance** | Resume becomes explicit | Extra UI and copy in two languages; a third path through hydration |

Recommendation: **(a)**, with the sidebar as the resume affordance it already is. This is the one
place the plan removes a behaviour rather than moving one, which is why it is the owner's call —
and option (c) is the compromise that keeps new-device resume, so it deserves weighing rather than
dismissing.

**(a) also closes a gap the code documents as knowingly open.** `app.py:732-738`:

> *"One gap stays open knowingly: ending a conversation and then logging out BEFORE asking anything
> else purges the cookie, so the next visit looks like a new device and resumes the conversation
> that was ended. Closing it properly needs a durable owner-level reset marker."*

With no cookie and no automatic resume, that gap disappears without the reset marker ever being
built. Worth recording as a benefit of (a), not just a cost.

### Decision 2 — Does "New chat" undo survive, and in what form? **BLOCKING.**

Undo lives in the Flask session (`prev_conv_id`, `prev_chat_history`) and is therefore
browser-wide — the same defect as `conv_id`, in a control nobody has complained about yet. Roadmap
§10.5 records that undo was *"kept and scoped"* on purpose.

Under URL-as-truth, "New chat" is a navigation from `/c/A` to `/`, and undo is the Back button —
free, per-tab, already understood.

Recommendation: **replace the undo toast with Back**, delete `prev_conv_id` and `prev_chat_history`.
If the toast is kept, it must hold the previous id in module memory and act by performing the same
navigation Back would.

### Decision 3 — Who mints the conversation id?

Recommendation: **the client, with `crypto.randomUUID()`, before the first request.**

Not a style preference. In `vercel/ai-chatbot` the id is minted client-side into a ref precisely so
it does not change when the URL catches up; the AI SDK destroys the chat instance and its in-flight
stream whenever `id` changes. The same hazard exists here in a different shape: if the server mints,
the URL cannot change until the first frame arrives, and the id then changes underneath a running
stream.

The precedent and the plumbing exist. `client_request_id` is client-minted and canonicalised
server-side (`app.py:2019-2027`), and `chat_append_turn` already accepts `p_session_id` from Flask.
The `gen_random_uuid()` column default is effectively unused on the normal path.

**A client-minted id is not an authorization claim** and nothing here treats it as one —
`chat_append_turn`'s ownership `select … for update` is the guarantee, and `p_owner_id` is always
server-derived (`app.py:2523`), verified in the security review.

Rejected: LibreChat's `uuidv5(userId:clientRequestId)` gives server authority *and* retry
idempotency, but costs a round trip before the URL can change, and this app already gets replay
safety from `unique (session_id, client_request_id, role)`.

### Decision 4 — Where does the id travel on the wire?

Recommendation: **`conversation_id` in the JSON body for the two POSTs, `?c=<uuid>` on
`GET /api/chat/history`.** Consistent with `client_request_id`; no preflight semantics to reason
about.

Rejected: a custom `X-Conversation-Id` header — tidier in the abstract, but a header some routes
require and others fall back from is the shape that grows an inconsistency at the fifth endpoint.

**Amended after review:** the round-1 draft listed "visible in ordinary request logging" as a
*benefit*. It is also a cost — see §6.3. The recommendation stands; the reasoning is corrected.

### Decision 5 — Is `/c/<id>` server-rendered with the transcript, or a shell the client hydrates?

Recommendation: **the same shell `/` renders**, hydrated by the existing
`Services.getChatHistory()` → `UI.hydrateTranscript()` path. Server-rendering the transcript would
duplicate turn rendering across Jinja and `ui.js`, and would require the render to read the
conversation — which §3.1 exists to avoid.

Cost, stated honestly: a hydration delay on a deep link, during which the transcript is empty.
Mitigated by a skeleton state, not by rendering twice.

### Decision 6 — Public id separate from the primary key?

Recommendation: **no. Keep the `uuid` v4 primary key as the URL id.**

The literature (RFC 9562 §8, OWASP IDOR, W3C TAG on capability URLs) favours splitting internal and
external identifiers, and at scale it is right. Here it is not worth a second column, a second
index, and a translation layer at every RPC boundary.

**Do not "upgrade" to UUIDv7.** It encodes the creation millisecond into a URL people paste to each
other, and Postgres 18 ships `uuid_extract_timestamp()` to read it back; Python 3.14's `uuid7()`
also spends 42 bits on a counter, leaving 32 random bits. Asked to defend its round-1 UUIDv7
recommendation, the reviewer **conceded** on exactly these grounds.

---

## 3. Server changes

### 3.1 The new route: `GET /c/<uuid:conversation_id>`

Add it inside `_register_routes`, immediately after `index()` at `app.py:1905`. It renders
**exactly what `/` renders** — same `base_render_context`, same `module_import_map`, same `?lang=`
cookie persistence.

Three properties, each a decision:

**It is not `@auth_required`.** `/` is not either. A deep link opened by a signed-out reader must
land on the landing page *and keep its path*, so signing in hydrates the conversation they clicked.

**It performs no ownership check and touches no session state.** The response **never varies with
the id** — that is the security property, and it is narrower than the round-1 draft's "byte-identical
HTML for every well-formed uuid," which was false: `index()` interpolates `is_authenticated` and
`user_email` (`app.py:1908-1911`), so the page differs between readers and between signed-in and
signed-out. The correct statement, and the one §7.3's test must assert, is: **for a fixed requester,
varying the uuid produces no observable difference.** This is the security-critical part:

- **There is no existence oracle at all**, which is stronger than status-code parity. The security
  review probed this by chaining it with rate limiting, CSP and unauthenticated reachability and
  confirmed it holds: for a fixed requester, varying the uuid produces no observable difference,
  and `?lang=`/cookie variance is orthogonal to which uuid was requested.
- **It cannot be a CSRF vector.** `GET /api/chat/history` writes `session["conv_id"]` today
  (`app.py:2056-2058`). If `/c/<id>` did the same, a third-party link would repoint another tab's
  conversation — the bug this feature removes, reintroduced through the front door, in an app with
  no CSRF protection and a token reader that accepts cookies. A pure render cannot do this.
- **It survives link scanners.** Defender Safe Links detonates URLs before the human clicks. `GET
  /c/<id>` mutating nothing is RFC 9110 safe-method semantics; the scanner ecosystem is what turns
  violating it into a production bug rather than a theoretical one.
- **Clickjacking needs no new code** — Talisman already serves `X-Frame-Options: SAMEORIGIN` on
  every response.

Enforcement lives entirely in `GET /api/chat/history`, which is authenticated and cannot be reached
cross-site without a token.

**The `<uuid:…>` converter is the shape guard, not a canonicaliser.** It accepts only the 36-char
dashed form and is a *strict subset* of `canonical_uuid` — verified in both directions, so no id can
diverge between routing and the rest of the app. But its regex accepts **uppercase**, so
`/c/<UPPER>` and `/c/<lower>` are one conversation at two URLs. See §4.6.

### 3.2 The request contract for the three chat routes

`_validate_chat_request` (`app.py:1985-2030`) gains **two** fields:

```
conversation_id : canonical_uuid(body.get("conversation_id"))
allow_create    : bool(body.get("allow_create"))
```

- **`conversation_id` absent or malformed → mint a fresh one**, matching `client_request_id`'s rule
  at `app.py:2019-2027`. A 400 would turn a client bug into a failed question. (§8 narrows when
  "absent" can legitimately happen.)
- **Well-formed → a *request* to file this turn under that id**, never a claim of ownership.

**`allow_create` must be threaded end to end, and the round-1 draft did not specify this.** A
literal implementation of the draft would have taken the SQL default and never created a first turn.
The full path, every hop of which needs the parameter:

`_validate_chat_request` → the two route bodies → `_persist_turn` (`app.py:1056-1069`) → the
`ChatBackend` protocol (`web/services/chat_store.py:286-315`) → `SupabaseChatBackend.append_turn`'s
RPC payload (`:363-391`) → `chat_append_turn`'s `p_allow_create`.

`_persist_turn` also needs a **typed not-found result** distinct from `False`, so the caller can
tell "this conversation is gone" from "the backend is down" — today both collapse to `False`
(`app.py:1134-1145`). Without that distinction §3.4's preflight has nothing to report.

**The response already echoes the resolved id; what is new is the client's duty to reconcile.**
Every chat route returns `conversation_id` today — stream `meta` (`app.py:2559`) and `final`
(`:2615`), the blocking response (`:2869`), the history response (`:2148`) — and this plan keeps
all four. But once the URL is the pointer, an echo that *differs* from the path is a desync of
exactly the kind §4 warns about. Specify it as a rule rather than leaving it implicit:

> On the first frame or response carrying `conversation_id`, the client compares it to
> `Route.current()`. If they differ, the server's value wins and the client `Route.enter()`s it.

On the happy path (client-minted v4, echoed back unchanged) this is a no-op. It matters only where
§3.2 mints — a malformed id, or an old client under §8's fallback — and those are precisely the
cases where a silent divergence would be hardest to diagnose.

### 3.3 The 404 that does not exist today

`chat_load_session` returns **zero rows** for "not yours" and for "empty conversation" alike.
Harmless while the server minted the id — it was yours by construction. Once the id arrives from a
URL the two must diverge, or a hostile or stale deep link renders as an *empty conversation*.

- Add `chat_session_exists(p_owner_id uuid, p_session_id uuid) returns boolean` — one
  `security definer` function, `set search_path = ''`, filtered on `p_owner_id`, execute revoked
  from `anon`/`authenticated`/`public` and granted to `service_role`, matching migration
  `:597-599`.
- `GET /api/chat/history?c=<id>` → **404 `not_found`** when the session does not exist for this
  owner, reusing `/select`'s exact response body and comment.

The security review confirmed this creates no new oracle: it mirrors the pattern already shipped in
`20260821145319:36-38`, is a single indexed-key lookup with no timing skew between the two cases,
and is reachable only behind `@auth_required` with the RPC filtered on `p_owner_id`.

**One case must not 404: an id the client minted for a turn that has not landed.** Lazy creation
means a brand-new conversation has no row. §4.2 handles this, and its round-1 handling was wrong.

### 3.4 Preflight — the stale/deleted conversation, done at the right time

**This section replaced the round-1 draft's `p_allow_create`-only design, which was broken.**

The draft claimed a stale-tab send against a deleted conversation would be *"surfaced as 404, not
500."* It would not. Verified order in the streaming route:

```
yield sse("final", …)        app.py:2610   ← the reader already has the answer
store.append_turn(…)         app.py:2642   ← the turn enters the RAM prompt window
_persist_turn(…)             app.py:2661   ← only now does the RPC run
```

and `_persist_turn`'s documented contract is that **it never raises** — it catches bare `Exception`
and returns `False` (`app.py:1134-1145`), deliberately, so a filing failure never discards a good
answer. The blocking route has the same ordering and answers `200 persisted: false`
(`app.py:2846-2879`).

So the actual sequence was: run retrieval, pay for the generation, stream the whole answer, **write
the turn into `ConversationStore` RAM**, then fail to persist and emit an in-band
`persistence_unavailable` frame. The reader gets a complete answer for a conversation that no longer
exists, and the model keeps that context in its prompt window until TTL or reload.

**The fix is a preflight, and it is strictly better than what it replaces:**

> For any request carrying a `conversation_id` with `allow_create` false, verify existence and
> ownership **in the view body, before retrieval and before any response frame**, under the
> `_InFlightGenerations` hold that is already taken there (`app.py:2543-2550`).

- A stale id becomes a clean **404 before a token is generated** — no LLM cost, no RAM write, no
  partial answer.
- Taking the hold first means a concurrent delete gets its existing 409 rather than racing.
- It costs one extra round trip on turns 2+, against a retrieval-plus-generation the route was
  about to do anyway.

`p_allow_create` stays, demoted to **defence in depth at the database** — it stops resurrection if a
future code path ever reaches `chat_append_turn` without preflighting. It is explicitly **not an
authorization control**: a hostile client can always pass `true`, and `p_owner_id` is server-derived,
so the worst it can do is create a row owned by the caller. The security review confirmed this
reading against the insert-then-ownership-select sequence.

### 3.5 Close the `force=True` CSRF hole while editing this function

`_validate_chat_request` parses with `request.get_json(force=True, silent=True)` (`app.py:1987`) —
the only `force=True` in the app. `force=True` parses the body **regardless of `Content-Type`**,
which makes both chat POSTs reachable by a cross-site auto-submitting form with
`enctype="text/plain"` — a CORS-simple content type that triggers no preflight, combined with
`_get_token_from_request` accepting the session cookie (`app.py:269-273`).

**Correction made during implementation, not by any review round: `SESSION_COOKIE_SAMESITE` is
NOT unconfigured.** Every round — three delegate reviews, the security review specifically, and this
document's own §0.1 — stated it as a confirmed fact, on the evidence that `app.py` never assigns
`SESSION_COOKIE_SAMESITE` directly. That evidence was real; the conclusion drawn from it was not.
`Talisman(app, ...)` is called with no `session_cookie_samesite` argument, and flask-talisman's own
`init_app` runs `app.config['SESSION_COOKIE_SAMESITE'] = session_cookie_samesite` **unconditionally**,
defaulting to `'Lax'` (`flask_talisman/talisman.py`, `DEFAULT_SESSION_COOKIE_SAMESITE = "Lax"`).
Verified by instantiating `create_app(testing=True)` and reading `app.config['SESSION_COOKIE_SAMESITE']`
back: `'Lax'`, in every environment this app runs in — the flag is set before `force_https`/`testing`
branching, not conditioned on it. A cookie scoped `Lax` is not attached to a cross-site POST at all
(only to a cross-site top-level GET navigation), so **the `force=True` hole was materially narrower
than every prior round of this document claimed**: the session cookie itself was never riding a
forged cross-site POST in the first place.

**What is still real.** `_get_token_from_request` also accepts a bare `sb-access-token` **cookie**
(`app.py:269-273`) — a separate cookie from Flask's session cookie, and grep shows nothing in this
codebase ever sets it server-side; `handlers.js:1560` only ever clears it. If nothing sets it, it
cannot ride a forged request either, which would retire this vector entirely rather than narrow it —
but that is an absence-of-evidence finding, not a proof the cookie is unreachable by every path
(a browser extension, a stale value from a retired auth flow, a future regression that starts setting
it again). Treated as latent rather than dead: worth refusing, not worth asserting closed.

This hole **predates this plan** and was already narrower than described. But this plan adds
`conversation_id` and `allow_create` to that same forgeable body, which lets an attacker name the
container rather than mixing into whatever the cookie already pointed at — a real widening over the
narrower base, and this is still the natural place to close it.

**Fix, one line:** drop `force=True`. The client always sends `Content-Type: application/json`
(`services.js:179`, `:221`, `:340`, `:388`, `:410`, `:615`), so nothing legitimate depends on it,
and a text/plain form cannot forge a real JSON content type. **Implemented and tested**
(`test_a_chat_request_without_a_json_content_type_is_refused`,
`web/tests/test_deep_link_contract.py`).

**Belt and braces, implemented anyway despite already matching the default:** `session_cookie_samesite="Lax"`
and `referrer_policy="strict-origin-when-cross-origin"` are now passed to `Talisman(...)` explicitly
(`app.py`) — both already held via flask-talisman's own defaults, silently inherited rather than
stated. Pinning them is what stops a future flask-talisman upgrade, or a config refactor that drops
this call's arguments, from silently regressing either one — the same "pin it, don't inherit it"
argument §6.1 already makes for `Referrer-Policy`, now applied to both.

### 3.6 Migration ordering

Schema before code, per `supabase/migrations/README`'s rule 1 and the argument at `TODO.md:822-829`.
Two concerns, two migrations:

1. `chat_session_exists` (§3.3).
2. `chat_append_turn` gaining `p_allow_create boolean **default true**`.

**The default must be `true`, and the round-1 draft had it backwards.** With `default false`, the
window between the migration landing and the new Flask deploying would have failed **100% of new
conversations**: old Flask omits the argument, PostgREST resolves to the new signature and supplies
`false`, the lazy insert is skipped, the ownership select finds nothing, and the function raises.

`default true` makes an un-updated caller behave exactly as it does today, and the new Flask passes
`false` explicitly on turns 2+ — which is where the protection is wanted. This is not a novel
judgement: `20260821145416:83-86` already ruled the same way for `p_title`, in a comment that reads
as if written for this case — *"Last, and defaulted, so the argument list stays append-only. A
caller that has not been updated yet still resolves, and files an untitled session rather than
failing."*

Follow that migration's shape exactly (`:68-70`): an explicit `drop function` of the old signature
and a `create` in the same file, since `apply_migration` wraps the file in one transaction and there
is therefore no instant at which neither version exists. The round-1 draft cited
`20260820131914:515-518` as this precedent; those lines are `revoke`/`grant`.

PostgREST's own documentation confirms both halves of this: *"If a function parameter has a default
value, it can be omitted in the API request"* — which is what makes `default true` safe for the
un-updated caller — and overloads resolve by **argument count**, which is why the old signature must
be dropped rather than left standing beside the new one. (Overloads sharing argument *names* with
different types are explicitly unsupported, so leaving both would be a latent trap, not merely
untidy.)

**One operational step the round-1 draft omitted: PostgREST serves from a cached schema.** An
unknown signature answers `404 PGRST202 "Could not find the … function in the schema cache"` — which
is also the exact failure if code somehow deploys before schema. Supabase reloads the cache on DDL
via an event trigger, so this is normally automatic; confirm it happened rather than assuming, since
a stale cache and a missing migration are indistinguishable from Flask's side.

Round-trip both in aborted transactions and re-run advisors before either lands.

---

## 4. Client changes

This app has **no client-side router and no `history.pushState` anywhere**. That is a liability and
an asset: nothing to integrate with, nothing to desync from.

The research documents what desync costs. LibreChat calls `navigate('/c/new')` without
`{replace: true}` immediately before its `replaceState`, leaving the router's location saying
`/c/new` while the store holds the real id — issue #7700, still open. The report's summary is the
sentence to keep: *"The trick that makes the stream survive is the same trick that desyncs the
router; you must decide which one you feed."* Here there is only one thing to feed.

### 4.1 A new module: `static/js/modules/route.js`

The import map globs `static/js/modules/` at import time, so a new file needs no registration. It
owns five things:

- `current()` — parse `/c/<uuid>` from `location.pathname`, canonicalise case, return `null` at `/`.
- `enter(id)` — `history.replaceState({...history.state, convId: id}, '', '/c/' + id)`.
- `replace(target)` — `replaceState` to `/c/<id>` or `/`. **Used for every error recovery.**
- `go(id)` — `pushState`. **Used only for deliberate reader navigation.**
- a `popstate` listener that re-drives the same path `openSession` takes.

**Pass `history.state`, not `{}`.** Both LibreChat and Open WebUI preserve the existing state
object; `vercel/ai-chatbot` passes `{}` and only gets away with it because Next re-derives its own.

**`replace` and `go` are separate functions on purpose.** The round-1 draft had one `go(null)` and
used it for error recovery, which produces a loop: `/c/missing` → 404 → push `/` → Back →
`/c/missing` → 404 → push `/`. Recovery must replace the invalid entry, never push over it.

### 4.2 The first-turn transition — `replaceState`, at submit

```
[ / ]  ── user sends first message
   │
   ├─ id = crypto.randomUUID()                 (minted once, never changes)
   ├─ Route.enter(id)                          → replaceState; state.convId = id, uncommitted
   └─ POST /api/chat/stream { conversation_id: id, allow_create: true, … }
```

**`replaceState`, not `pushState`.** `/` is replaced rather than stacked, so Back from a brand-new
conversation goes wherever the reader was before, not to a blank composer. Open WebUI, LibreChat,
the older `vercel/ai-chatbot`, ChatGPT, Claude.ai, Lobe Chat and `assistant-ui`'s documented example
all use `replace` here; `vercel/ai-chatbot`'s `main` is the outlier.

**At submit, not at stream end.** The id is already known, so there is nothing to wait for.

**The uncommitted marker lives in `history.state`, not module memory.** The moment the path becomes
`/c/<id>`, path-driven hydration would fetch `?c=<id>` against a conversation whose first turn has
not landed — 404 under §3.3, blanking a live stream. `vercel/ai-chatbot` solves this with an
in-memory `loadedChatIds` set, and the round-1 draft copied that. **It does not survive a reload.**

The failing sequence: `/` → submit → `replaceState('/c/X')` → reload before `final`. The in-memory
marker is gone; startup always settles an authenticated transcript and dispatches hydration
(`app.js:166-180`, `:195-209`); the fetch 404s; the reader is told the conversation they just
started does not exist and is bounced to `/`. The reload also aborts the stream before its write, so
X genuinely never existed.

`history.state` fixes this because it is persisted with the history entry and restored on reload,
is per-entry rather than per-tab, and is not web storage — so §1.3's "no new storage key" holds.
The lifecycle:

| `state.convId` | `state.committed` | On load | On history 404 |
|---|---|---|---|
| absent | — | new chat at `/` | n/a |
| present | `false` | do **not** fetch; the turn was lost to the reload — start a fresh composer at `/`, via `Route.replace(null)` | n/a |
| present | `true` | fetch `?c=` | conversation is gone → `Route.replace(null)` |

`committed` flips to `true` on the `final` frame, which is the first moment the row is durable.
§9 already accepts that an aborted first turn leaves no durable trace — this makes the client agree
with the server about that rather than reporting a false 404.

### 4.3 The navigation state machine

The round-1 draft gave three bullets here. That was not enough: the interactions between the URL,
an in-flight stream, an in-flight hydration, and the Back/Forward buttons are where this design
either holds together or produces the exact "screen and next question disagree" lie it exists to
remove. Specify it as one machine.

**Two entry points with opposite semantics, and conflating them is the single most common way to get
this wrong.**

| Trigger | Can it be refused? | Rule |
|---|---|---|
| **Sidebar click / New chat** — reader *asks* to navigate | **Yes.** Today `openSession` refuses while a stream is live (`handlers.js:611-617`) | Refuse first, navigate second. The URL must not move until the refusal check passes |
| **`popstate`** — Back/Forward | **No.** The URL has *already* changed before the handler runs | Abort the in-flight stream fetch and proceed. There is nothing to refuse |

The round-1 draft said "abort the fetch, as `openSession` already refuses-if-busy today," which
prescribes both behaviours in one sentence. They are opposites. Sidebar clicks refuse; `popstate`
aborts.

**Order for a sidebar click**, which the round-1 draft had backwards:

1. Refusal check (`_refuseWhileStreaming`) — before anything moves.
2. Bump the navigation epoch **at intent**, not after the first server call succeeds.
3. `Route.go(id)` — `pushState`.
4. Fetch history. **On 404 or failure, roll the URL back** with `Route.replace(previousPath)` and
   surface the shared not-found handling (§4.5).

Step 4 is the correction. `openSession`'s own rule is *"a failed select must leave the reader where
they were"* (`handlers.js:605-609`) — but `pushState` has already fired by then, so without an
explicit rollback the reader sits on a URL naming a conversation they are not viewing, and their
next question inherits the dead id. That is LibreChat #7700's exact shape, rebuilt locally. Roll back
with `replace`, not `history.back()`, so the rollback does not re-enter the `popstate` handler and
drive a second navigation.

**`openSession`'s in-flight guard must also move.** Today a second invocation is dropped while
`switchInFlight` is true (`:611-617`) and the epochs bump only after the first server call succeeds
(`:618-626`). With the URL changing at click time: at A, click B (URL → B, load starts), immediately
click C (URL → C, dropped by the guard), B completes and paints B — **URL says C, transcript says
B**. Setting the epoch at intent and obsoleting any in-flight read when a newer target arrives makes
the last route target win.

**`popstate` must consult the same uncommitted marker as page load** (§4.2), and the round-1 draft
did not say so. The failing sequence otherwise: at `/c/<id>` with turn 1 in flight → Back to `/` →
**Forward** → `popstate` fires → the handler fetches history for an id whose row does not exist yet
→ 404 → the reader is yanked off the page they deliberately navigated forward to, while the stream
keeps writing into a discarded transcript. Forward into an entry whose `state.committed` is `false`
and whose stream this page still owns must **re-attach to the live stream, not fetch**.

`pushState`/`replaceState` never fire `popstate` themselves, so the handler only ever sees genuine
traversal — which is what makes the rollback in step 4 safe.

**bfcache.** §9 notes Chrome now bfcaches `Cache-Control: no-store` pages. A Back into `/c/<id>` may
therefore restore the DOM via `pageshow` with **no** `popstate` and no refetch — usually desirable,
but it means a "conversation not found" state can be restored stale, after the reader has fixed
whatever caused it. Handle `pageshow` with `event.persisted === true` by re-deriving from
`Route.current()`. There is no `pageshow` handler in the codebase today.

### 4.4 Deleting the conversation on screen

`handle_chat_session_delete` mints a replacement id from the cookie and returns it
(`app.py:2494-2505`); the client clears the UI and adopts that value (`handlers.js:700-723`). With
no cookie there is no replacement, and the round-1 draft did not replace this transition — so the
URL would stay `/c/X` after X was deleted, and the next send would derive X from the URL and walk
straight into §3.4's stale path.

On a successful delete of the conversation the current route names: `Route.replace(null)`,
invalidate any pending hydration, and do **not** depend on `result.conversation_id`. Deleting a
conversation the route does not name leaves the URL alone, as today.

### 4.5 Deep links across the auth boundary

A signed-out reader who opens `/c/<id>` gets the landing page at that path. After sign-in,
`settleTranscript(user)` (`app.js:108`) already waits for *"who is here?"* before drawing anything —
hydrate from `Route.current()` at that moment. The path is preserved by construction, so no redirect
target needs storing and LibreChat's open-redirect guard has nothing to guard.

A signed-in reader who opens someone else's `/c/<id>` gets the shell, then 404 from the history
fetch: show a "conversation not found" state and `Route.replace(null)` — replace, per §4.1.

**This handling belongs in the shared hydrate layer, not at the deep-link entry point.** The
round-1 draft specified it only for opening someone else's link, but the sidebar reaches the same
404 by an ordinary route: the conversation is deleted in tab B between tab A listing it and tab A
clicking it — which per-tab conversations make *more* likely, not less. Today both callers collapse
any failure into a generic toast (`app.js:221-226`, `handlers.js:651-658`). Define the 404 →
not-found → `Route.replace(null)` behaviour once, where both `settleTranscript` and `openSession`
reach it, and test the sidebar case explicitly — it is the natural home for the cross-tab delete
test in §7.2.

### 4.6 The recovery flow already calls `replaceState`, and it erases deep links

`handlers.js:1361` is the codebase's only History-API call:

```js
window.history.replaceState({}, '', '/');
```

It hard-codes `/` and passes `{}` instead of `history.state`. A signed-out reader who opens
`/c/<id>`, clicks "forgot password", and completes recovery has the path they arrived on **silently
replaced with `/`** — and, once §4.2 lands, the `history.state` carrying `convId` discarded with it.

Route it through `route.js`: preserve the pathname, strip only `?recovery=1`, and spread the
existing state. The comment above it (*"Past this line the password is already changed. Nothing
below may report failure"*) is the reason it is unconditional, and that reasoning is sound — it just
should not be unconditional about the *path*.

This also corrects §4's framing: there was never "nothing to integrate with." There was one
integration, and it was silently hostile to this feature.

### 4.7 Canonical case

Werkzeug's converter accepts uppercase hex, so `/c/F47AC…` and `/c/f47ac…` route to the same
conversation as two distinct URLs — two history entries, two log lines, and a `Route.current()`
that can miss a string comparison against a lowercase minted id. Not a security divergence (the
converter is a strict subset of `canonical_uuid`), but the same *shape* as the dash-normalisation
bug `app.py:704-719` already documents as having bitten once.

`Route.current()` lowercases before comparing, and the route issues a 301 to the canonical form when
the path differs from `str(conversation_id)` — mirroring the existing "canonicalise once and
rewrite" precedent.

### 4.8 Language toggle

Nothing to change, and worth stating because roadmap §10.3 named it as a risk. `I18n.set` either
`reload()`s or rewrites `?lang=` and `replace()`s (`i18n.js:59-66`); both preserve the path. The
`__langfix` pre-paint guard (`index.html:63-74`) does not touch the path either.

Deep-linking makes the toggle *better*: the conversation is in the URL, so it survives the
navigation without depending on a cookie the reload might race.

---

## 5. What gets deleted

The largest part of this change is subtraction.

### 5.1 `_resolve_conversation_id` collapses

Its cookie branch (`:704-719`) and fallback mint (`:761-763`) are replaced by the validated request
field. Its resume branch (`:739-759`) lives or dies on Decision 1, and removing it removes the only
caller of `latest_session` in the current-session rule.

All eight `session["conv_id"]` writes and three pops go, along with `conv_id` and `prev_conv_id` in
`CONVERSATION_SESSION_KEYS`/`CONVERSATION_ID_KEYS` (`auth.py:35-43`). `purge_conversation_state()`
keeps purging the store; it has no cookie left to clear.

**Two things this does *not* obsolete**, both confirmed in review:

- **The streaming view-body constraint** (`app.py:2526-2531`) stands. The comment distinguishes
  cookie writes from durable ones, and the `_InFlightGenerations` hold must still be acquired before
  the generator is iterated so a concurrent delete is blocked.
- **`_bind_session_to_identity`'s rotation** (`app.py:296-313`). Roadmap §6 records that isolation
  *"rests entirely on the owner filter inside the RPC"* — rotation was already only a convenience —
  and owner-keyed RAM history prevents an identity change from making another reader's cached
  context reachable. §7 pins this rather than assuming it.

### 5.2 `POST /api/chat/sessions/<id>/select` — delete the route

Its entire job is moving the cookie (`app.py:2383`). With no cookie, selecting is navigating.
Ownership verification moves to the history fetch, which already had to do it.

Deleting it removes an inverted guard rather than leaving it to rot: its 409 checks whether **the
cookie's current** conversation is streaming, not the target (`app.py:2353`), on a per-browser
rationale that no longer applies.

It also closes a live CSRF hole incidentally. `handle_chat_session_select` parses **no body at all**
(`app.py:2306-2384`), so any cross-site auto-submitting form of any `enctype` can repoint the
victim's `conv_id` today. **Pin the removal with a test** (§7.2) so a future refactor cannot
reintroduce an equivalent unprotected cookie-repoint endpoint.

### 5.3 `active` leaves the `/api/chat/sessions` response

`app.py:2252` fills it from the cookie, justified as *"The client cannot know which conversation the
server considers current — it is a signed cookie"* (`:2237-2241`).

**That justification inverts.** The client now knows exactly, from its own URL, and the server's
answer is wrong for every tab but one — by that comment's own standard, *"worse than one that
highlights none."* Drop the field; `UI.History.setActive` (`ui.js:1167-1171`) takes
`Route.current()`.

### 5.4 Undo state

`prev_conv_id` / `prev_chat_history` and their five call sites, per Decision 2.

### 5.5 The whole resume surface — the round-1 draft listed none of it

Decision 1(a) does not just orphan a branch; it orphans a feature with server, wire, client and
catalogue components. All of it goes, and missing any one leaves dead code that reads as intentional:

| Piece | Where |
|---|---|
| The config flag itself | `CHAT_RESUME_LATEST_SESSION`, `app.py:1299` |
| The resume branch and its outage handling | `app.py:739-759`, and the `resume_failed` rollbacks at `:2078`, `:2079-2085` |
| `latest_session()` — three implementations, one caller | `chat_store.py:330` (protocol), `:422` (Supabase), `:796` (in-memory); called only at `app.py:741` |
| The `chat_latest_session` RPC | `20260820131914…sql:619` — keep or drop deliberately; the sidebar does not use it |
| `resumed` on the wire | `app.py:2148`, `:2090`, `:2110`; `services.js:539`, `:554`, `:582` |
| The resumed-notice UI | `app.js:220` `showResumedNotice()`; `handlers.js:638`, `:721` `hideResumedNotice()`; `ui.js`'s notice and its `localStorage` per-reader key at `ui.js:105-120` |
| Its i18n keys, both catalogues | `web/i18n/en.yaml`, `ar.yaml` |

`resumed` is also the reason `historyNoticeKey(identity)` exists in `localStorage`. Removing the
notice removes the only writer of that key, so sweep it the way `Transcript.discard()` sweeps its
retired predecessor (`i18n.js:101-105`) rather than leaving it to rot in readers' browsers.

### 5.6 What explicitly stays

- **`ConversationStore`'s `(owner, conversation)` key** — the whole point.
- **`clear()` staying owner-blind** (`:192-207`) — *"Under-purging is a leak of one reader's
  questions into another's prompt."*
- **`_InFlightGenerations` exactly as it is** — counted, keyed on the pair, released in `finally`.
- **`GET /api/chat/sessions` not resolving the current-session rule** — *"Listing conversations is
  not starting one."*
- **The single-worker contract** (`conversation_store.py:15-21`). See §9.

---

## 6. Leakage and headers

### 6.1 Pin `Referrer-Policy` explicitly

`strict-origin-when-cross-origin` is already served, but as **Talisman's default**. It is now
load-bearing: it is what stops `/c/<uuid>` reaching jsdelivr, Google Fonts, cdnjs and lordicon.
Pass it explicitly at `app.py:1375-1379` with a comment, so a future config change cannot silently
start leaking conversation ids. Consider `same-origin`; the app has no cross-origin referrer
dependency.

### 6.2 `X-Robots-Tag: noindex, nofollow` on `/c/*`

`admin.html:18` already sets the meta equivalent; `index.html` does not. Prefer the header — it
applies to non-HTML responses and cannot be missed by a parser that bails early.

### 6.3 The URL now reaches the logs — an accepted trade, not a non-issue

Decision 4 puts the id in the path and the query string, which means every layer that logs a
request line now records it: reverse proxy, CDN, APM, any log-shipping SaaS. Previously the id was
in a cookie and a JSON body and appeared in none of them.

This does not block the plan, but it is a real change under the "content reaches a third party"
half of the threat model, and the round-1 draft listed log visibility as a *benefit* without
weighing it. Before shipping: confirm no third-party log sink in the path retains full request
paths, or scrub `/c/<uuid>` → `/c/:id` at the access-log layer. LibreChat's
`client/src/lib/rum/routes.ts` is a copyable implementation of exactly this normalisation.

### 6.4 The id is now JS-readable, and `img-src` is a wildcard

Flask's session cookie is `HttpOnly` by default, so `conv_id` is not script-readable today. In the
URL it is readable by anything running on the page. CSP `script-src` trusts three third-party
origins and `img-src` is `'self' data: https:` (`app.py:1354`, `:1356`) — an unrestricted HTTPS
wildcard, so a compromised trusted script could exfiltrate `document.location` with
`new Image().src = …` and raise no CSP violation.

This is a supply-chain/XSS-conditional exposure, not an exploit today. Tighten `img-src` off the
`https:` wildcard as defence in depth now that the URL carries something worth taking.

### 6.5 Do **not** add `robots.txt`

There is none today, and that is the safe state. `Disallow` and `noindex` defeat each other: a
crawler blocked from fetching the page never reads the `noindex`. **Three of the five documented
AI-chat indexing incidents have exactly this root cause** — Gemini (Feb 2024) needed its
`Disallow: /share/` *removed* so the noindex became readable, and Claude repeated it in July 2026.
`robots.txt` also publishes the list of paths you wanted quiet, and Slack states it does not honour
it.

### 6.6 Unfurling is disclosure, and that is acceptable here

Pasting `/c/<id>` into Slack causes Slack's servers to fetch it; unfurling is on by default and
opt-out is the poster's. This is safe **because auth is a cookie and §3.1's render is
content-free** — an unfurl bot gets the same generic shell as everyone else, which is what ChatGPT
and Claude were measured to return. It would *not* be safe if the URL ever became a capability
(a share token). §9 keeps it that way.

---

## 7. Tests

Roadmap §6 is the model: a test that can no longer distinguish the property it names is more useful
failing than passing.

### 7.1 Prerequisite — `conftest.py` cannot express a second tab today

**This is a build step, not a detail, and the round-1 draft assumed it away.** Every Playwright mock
in `web/tests/conftest.py` is registered with `page.route(...)` — `:380`, `:426`, `:437-468`, `:499`,
`:516` — and there is **no `context.route(...)` anywhere in the file**. The Supabase mock keeps its
session in per-page `window.__supabaseState` (`:16`).

So a second `Page` opened in the same `BrowserContext` gets **no mocks** (its requests hit the real
network) and **no auth** (it renders the signed-out view). The multi-tab tests below are unwritable
until:

- route registration moves to `context.route(...)` on a context-level fixture — Playwright's docs
  state it *"intercepts network requests made by any page in the browser context"*, which is exactly
  the property needed and the reason this is a fixture change rather than a per-test workaround; and
- the Supabase browser mock persists its session where sibling pages inherit it — context cookies
  or `localStorage`, which is also what the real client does (`services.js:149`). Note
  `BrowserContext.storage_state()` covers cookies, `localStorage` and IndexedDB and **not**
  `sessionStorage`, which is the same isolation boundary §1.2 relies on — so the fixture cannot
  cheat by seeding `sessionStorage`, and should not want to.

**API caveat, verified in this project's `.venv`:** `BrowserContext.route` and `storage_state` are
available, but `page.session_storage` / `page.local_storage` (the newer `WebStorage` class) are
**not**. Storage assertions must go through `page.evaluate(...)`, or the pin in
`requirements-dev.txt` must be raised deliberately — not discovered mid-implementation.

Do this first. It is also the only change in this plan that touches existing browser tests
wholesale.

### 7.2 The multi-tab proof — the test that does not exist and is the point

> **Two `Page`s in one `BrowserContext`.** Cookies and `localStorage` shared — same signed-in
> reader — while `sessionStorage` and the DOM are per-page. That is a real second tab.

In a new `web/tests/test_multi_tab_conversations.py`:

- `test_two_tabs_hold_two_conversations` — the `TODO.md:793-796` symptom, inverted. Send in A, send
  in B, assert the URLs differ, assert neither transcript contains the other's question, and
  **reload tab A** — the step the original report singles out.
- `test_a_duplicated_tab_is_a_second_view_of_one_conversation` — §1.2's claim, pinned as an
  assertion of intent, so a future `sessionStorage` pointer fails it.
- `test_a_second_tab_can_generate_while_the_first_is_streaming` — no 409 for two different
  conversations; 409 for a delete of the one being streamed.
- `test_a_reload_during_the_first_turn_does_not_report_a_missing_conversation` — §4.2's
  `history.state` lifecycle, which is invisible to every other test.
- `test_the_last_sidebar_click_wins` — §4.3's epoch fix: click B then immediately C, assert the URL
  and the transcript agree.

### 7.3 Server tests — and a correction

New:

- `test_a_conversation_id_the_reader_does_not_own_is_not_found` — `?c=` a second reader's id via the
  existing `fake_reader_b_token` / `test-reader-b-id` bypass identity. Assert the response is
  **byte-identical** to a nonexistent id, not merely the same status.
- `test_a_stale_conversation_is_refused_before_the_answer_is_generated` — §3.4's preflight. Must
  assert *no* `final` frame and *no* `ConversationStore` entry, not merely a non-200; the round-1
  design would have passed a status-only assertion.
- `test_a_malformed_conversation_id_is_refused_at_routing` — extend the parametrised
  `test_a_session_id_that_is_not_a_uuid_is_refused_everywhere` (`test_chat_sessions.py:692`) to
  `/c/<id>`, including the 32-char undashed legacy form and an uppercase one.
- `test_the_deep_link_route_writes_no_session_state` — §3.1's CSRF property, invisible otherwise.
- `test_the_deep_link_route_response_does_not_vary_with_the_conversation_id` — the no-oracle
  property, scoped correctly. **Compare a real id against a random one *as the same reader*.** The
  round-1 draft named this `…renders_the_same_page_for_any_reader`, which is unwritable: `index()`
  interpolates `is_authenticated` and `user_email` (`app.py:1908-1911`), so the page legitimately
  differs between readers. The property is invariance across *ids*, not across *readers*.
- `test_the_response_id_wins_when_it_differs_from_the_url` — §3.2's reconciliation rule.
- `test_a_failed_sidebar_navigation_rolls_the_url_back` — §4.3 step 4.
- `test_forward_into_an_uncommitted_conversation_does_not_report_it_missing` — §4.3's
  Forward-popstate case.
- `test_completing_account_recovery_keeps_the_deep_link_path` — §4.6, and a live bug today
  independent of this feature.
- `test_a_deleted_conversation_reached_from_the_sidebar_uses_the_shared_not_found_path` — §4.5.
- `test_a_chat_request_without_a_json_content_type_is_refused` — §3.5's `force=True` removal.
- `test_there_is_no_route_that_repoints_a_conversation_by_cookie` — pins §5.2's deletion.
- `test_an_absent_conversation_id_starts_a_new_conversation` rather than resuming — Decision 1.

**Rewritten. The round-1 draft listed the first four of these as "must keep passing unchanged" and
that was wrong** — it confused a surviving *property* with a surviving *test*. Each still tests
something true; each reads the conversation id from a place that will not exist:

| Test | Why it breaks |
|---|---|
| `test_the_streaming_route_keys_history_by_owner` (`test_session_isolation.py:209`) | reads `flask_session["conv_id"]` → `KeyError` |
| `test_a_second_reader_cannot_load_the_first_readers_session` (`:226`) | same |
| `test_the_refusal_lifts_once_the_answer_has_landed` (`test_chat_sessions.py:657`) | `conversation_of()` returns `None`; deletes `/sessions/None` |
| `test_a_conversation_being_written_to_cannot_be_deleted` (`:594`) | seeds `flask_session["conv_id"]` and posts no `conversation_id`, so the stream runs on a different id and the racing delete returns 200, not 409 |
| `test_a_second_reader_cannot_hydrate_the_first_readers_transcript` (`test_chat_persistence.py:877`) | hydrates with no `?c=`, so under Decision 1 it never reaches `chat_load_session` |

The shared helper is the root cause: `conversation_of()` reads `flask_session["conv_id"]` in **both**
test modules (`test_chat_persistence.py:102-104`, `test_chat_sessions.py:97-99`). Re-point it at the
id the client sent, and most of these follow.

Also rewritten, for behaviour changes rather than plumbing:
`test_a_returning_reader_resumes_their_own_history` and `test_the_resume_fallback_is_on_by_default`
(Decision 1); `test_selecting_a_conversation_repoints_the_cookie`;
`test_deleting_the_active_conversation_rotates_the_cookie`;
`test_the_replacement_conversation_is_minted_rather_than_resumed`;
`test_a_legacy_undashed_cookie_is_canonicalised_in_place`; the `test_new_chat.py` undo set
(Decision 2).

**Watch for vacuous passes.** Roadmap §6 records a test that kept passing while proving nothing once
the current-session rule changed. Any test whose second reader is faked by writing `flask_session`
rather than by using `fake_reader_b_token` is a candidate; check each survivor still fails against
the pre-fix code.

### 7.4 Browser tests

`test_chat_sidebar.py` (24 tests) drives select/rename/delete through mocked routes; the select mock
becomes a navigation. Add a `popstate` test — Back after two sidebar selections — because that is
the one path with no server involvement at all.

---

## 8. Rollout

**Server and client are one coupled artifact.** The round-1 draft claimed each step was
"revertable on its own"; it is not, in either direction. Old client + new server fragments every
turn into a fresh conversation and hydrates nothing; new client + old server 404s on `/c/<id>` and
has its `?c=` ignored. Ship steps 2 and 3 together and revert them together.

**A one-release cookie fallback is warranted after all, and the round-1 draft's rejection of it was
wrong.** That rejection rested on "client and server ship together" — true for *new page loads*,
false for *tabs already open at deploy time*. `asset_version` only busts a URL when something is
fetched; a tab open across the deploy keeps running old JS, sends no `conversation_id`, and under
§3.2's mint-on-absent rule turns each subsequent question into its own one-turn conversation with no
model context. The same applies under any rolling/blue-green topology.

The fallback is narrower than it sounds and does not preserve the bug for anyone new:

- It reads `session["conv_id"]` **only** when `conversation_id` is absent from the request.
- A new client always sends one, so a new client never takes this path.
- An old client therefore gets **exactly today's behaviour**, including today's cross-tab
  collision — which is strictly better than fragmenting its conversation.
- It is deleted in the next release, and the deletion is the last step below rather than a promise.

**One thing must land before any of it: `index()` sets no `Cache-Control`** (`app.py:1905-1920` —
the only two in the app are at `:1052` and `:2158`). Without an explicit directive the HTML document
is heuristically cacheable, so a reader can keep being served the pre-deploy page long after the
deploy, extending the old-client window past any release boundary and making the §8 fallback's
removal date unknowable. Set `Cache-Control: no-cache` (revalidate, don't refuse to store) on the
page routes **one release ahead of everything else**, so the window is bounded before it matters.

Order:

0. **`Cache-Control: no-cache` on `/` (and, when it exists, `/c/<id>`)** — shipped ahead of the rest.
1. **`conftest.py` context-level fixtures** (§7.1) — because the tests that prove the rest cannot be
   written without it.
2. **Both migrations** (§3.6), round-tripped, advisors clean. `p_allow_create` defaults to `true`,
   so this is a no-op for the running code.
3. **Server**: the route, the request contract, `allow_create` threaded end to end, the preflight,
   the 404, `force=True` removed, the header changes. Cookie fallback retained.
4. **Client**: `route.js`, the transition, `history.state` lifecycle, `popstate`, the sidebar epoch
   fix, delete-the-current-route. **Ships with step 3.**
5. **Deletions** (§5) — `/select`, `active`, undo, `_resolve_conversation_id`.
6. **Remove the cookie fallback** and drop `conv_id`/`prev_conv_id` from
   `CONVERSATION_SESSION_KEYS`. Stale cookies in the wild are inert once nothing reads them.

---

## 9. What this does not do

- **No sharing, and no share links.** If sharing is ever built it must be a **separate, revocable
  object with its own id**, not a visibility flag. Every project in the research does it this way;
  Dropbox 2014 is what the alternative costs. §6.6's safety depends on this staying true.
- **No resumable streams.** Navigating away mid-stream still abandons the generation, and §4.2 now
  makes the client agree with the server about that. The right shape when it is built is
  `huggingface/chat-ui`'s append-only `generationEvents` table + SSE `id: <seq>` + the browser's
  automatic `Last-Event-ID` — no Redis, survives process death, works from any tab. Vercel's
  `resumable-stream` is the weaker option and is currently **stubbed to `204` in Vercel's own
  template**. Known trap for whoever picks it up: a dropped SSE connection frequently does not
  announce itself, which is what LibreChat's `visibilitychange` re-subscribe exists to catch.
- **No cross-tab synchronisation.** Rename in tab A and tab B keeps the old title until it
  refetches. No project in the research treats this as a correctness problem.
- **Still single-worker**, and this change makes one consequence more reachable. The documented
  shape is `--workers 1 --threads 8` (`conversation_store.py:19-21`). Per-tab conversations make
  concurrent streams from one reader legitimate, so **eight simultaneous SSE streams occupy every
  worker thread** and short requests queue behind them. This is a capacity question, not a code
  one, but it moves from theoretical to reachable here and should be sized before launch — alongside
  HTTP/1.1's six-connection-per-origin limit, which is a reverse-proxy setting (HTTP/2) and out of
  scope for this change.
- **No `Cache-Control` change on the HTML.** `GET /api/chat/history` already sets
  `private, no-store`. The `/c/<id>` shell is content-free. Note Chrome now permits bfcache for
  `no-store` pages, so the old assumption that `no-store` keeps a page out of bfcache no longer
  holds.
- **This is not a CSRF fix for the app**, only for the routes it touches. §3.5 closes the
  `force=True` vector and §5.2 removes `/select`; `POST /api/conversation/reset` remains forgeable
  for its default branch (`app.py:2929` uses `get_json(silent=True)`, so the `undo` branch is safe).
  That is annoyance-level — it forces a new chat, exposes nothing — and is left alone deliberately
  rather than expanded into.

---

## 10. Open questions for the next pass

1. **Does the preflight (§3.4) want its own RPC or can it reuse `chat_session_exists`?** They are
   the same query; the question is whether folding it into `chat_load_session`'s return saves a
   round trip worth the wider return type on a function six call sites depend on.
2. **Should `/c/<id>` 404 for a well-formed uuid that is not a conversation uuid?** §3.1 says no, on
   no-oracle grounds, and the security review agreed after probing it. Flagged anyway because it is
   the load-bearing security decision and it is counter-intuitive.
3. **Decision 2's shape** if the toast is kept: does Back-as-undo confuse a reader who expects it?
4. **How long is the §8 fallback window in practice** — one release, or one release *plus* a measured
   period with no old-client requests observed? The second is more honest and needs a log signal to
   measure, which §6.3 may want scrubbed.

---

## 11. Where the reviews earned their cost

Three reviewers, three lanes, one round. Each found something the others did not, which is the
argument for running them in separate lanes rather than asking one reviewer for everything.

1. **OpenCode (`gpt-5.6-terra`, architecture) broke §3.4 outright** — the single most valuable
   finding here. `p_allow_create` was placed at durable-append time, which runs *after* the answer
   has streamed and inside a function whose contract is that it never raises. The stale-link 404 the
   whole section promised was unreachable. On verification the failure was **worse** than reported:
   `store.append_turn` at `app.py:2642` precedes `_persist_turn`, so the deleted conversation's turn
   enters the model's RAM prompt window unconditionally. Rewritten as a preflight.
2. **It also found four client-state gaps** the draft had no answer for: `allow_create` never
   threaded through the request contract; the reload-during-first-stream hole in the "already
   loaded" guard; `switchInFlight` letting the URL and the transcript disagree; and a dead `/c/X`
   after deleting the conversation on screen. Plus one internal inconsistency of the draft's own —
   `Route.go(null)` used for error recovery, producing a Back-button loop.
3. **Antigravity (`gemini-3.7-flash-high`, operations) caught the migration default**, which would
   have failed 100% of new conversations during the deploy window — and the repo had already ruled
   the same way once, in `20260821145416:83-86`, which the draft had not noticed while citing the
   wrong lines for the precedent. It also proved `conftest.py` cannot express a second tab today,
   corrected the "keep passing unchanged" test list, and **defended one of its own round-1
   recommendations the draft had rejected** — the open-tab case the hard-cut argument missed. It
   conceded the other two (UUIDv7, `sessionStorage`) on the merits.
4. **Claude Sonnet (security) found the `force=True` hole** — pre-existing, unrelated to this
   feature, and widened by it, since the draft was already editing the exact function. One-line fix.
   It also flagged the URL becoming JS-readable against a wildcard `img-src`, the access-log
   exposure the draft had listed as a *benefit*, and identified that deleting `/select` closes a
   live zero-crafting CSRF hole incidentally — worth a regression test, which §7.3 now has.
5. **A third round, by a reviewer working independently of those three, found the one thing all of
   them missed**: `handlers.js:1361`. Three reviewers and this document all asserted there was no
   History-API usage to integrate with; there was exactly one, it hard-codes `/`, and it silently
   erases a deep link on password recovery — a live user-facing bug the moment `/c/<id>` exists. It
   also caught that "byte-identical HTML" made a proposed test unwritable, that a failed sidebar
   navigation leaves the URL lying, that §5's deletion inventory omitted the entire resume surface,
   and that `index.html` carries no `Cache-Control` — which is what §8's step 0 now answers. One of
   its findings was wrong (it reported no id echo in the response contract; the echo exists on all
   four routes) and two had already been fixed in round 2, which is the expected cost of reviewing
   in parallel rather than in sequence.
6. **Documentation lookups corrected one thing and confirmed two.** PostgREST's docs confirm the
   `default true` reasoning and, more usefully, that overloads resolve by argument *count* while
   same-name/different-type overloads are unsupported — which is why §3.6 drops the old signature
   rather than leaving it beside the new one, and added the schema-cache-reload step nobody had
   raised. Playwright's docs confirm `context.route` is the documented mechanism for §7.1, and
   checking the installed version caught that `page.session_storage` does not exist here — an API
   the test plan would otherwise have specified and discovered mid-implementation.
7. **What survived all of it.** The core architecture (§1), the no-oracle deep-link render (§3.1,
   once narrowed), the 404 discipline (§3.3), `p_allow_create` not being an authorization control,
   and the claim that removing the cookie does not obsolete the streaming view-body constraint. All
   five were probed by at least one reviewer and held.
