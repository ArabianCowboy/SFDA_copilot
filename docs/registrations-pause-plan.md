STATUS: BUILT 2026-08-25, against `66a9f88`. Design record — the corrections
noted inline below (`Proves it` lines that turned out infeasible, or shapes
the implementation refined) are kept rather than silently edited away; the
TODO.md entry this plan closed carries the short summary of what shipped.

# Registrations Pause

**Source:** `TODO.md` → [Registrations pause — let an operator pause new signups](../TODO.md#registrations-pause--let-an-operator-pause-new-signups).

**Read the correction in §1 before anything else.** The filed entry's central premise is
wrong, and building it as written produces an operator control that pauses nothing.

This plan went through four independent passes: a direct code read in this session, a
research pass on Antigravity (`gemini-3.7-flash-high`), an architecture pass on OpenCode
(`gpt-5.6-luna`), and a fourth plan supplied by the user for comparison. Where they
disagreed the disagreement is written down rather than resolved silently — §5 is the
clearest example, where all four reached different answers. Every `file:line` below was
opened in the session that wrote it.

**Post-build review, 2026-08-25 — three real bugs found and fixed the same day.** A security
pass (Antigravity, `gemini-3.7-flash-high`, its default) and an implementation pass
(OpenCode, `opencode/muse-spark-1.2-contributor-free`) both reviewed the built code against
this document. Three findings were confirmed by hand (reproduced against the pre-fix code,
not taken on the reviewer's word) and fixed:

1. **A TOCTOU race in `SettingsService.signup_enabled()`.** Its store read runs outside any
   lock (deliberately — I/O must not block every other reader), and the write-back used to
   overwrite the cache unconditionally. A slow read that started before a concurrent
   `set_signup_enabled()` publish, but finished after, could silently clobber the fresh value
   with the stale one it started with — an operator's pause invisibly undone for up to the
   45s TTL. Fixed by capturing `_operational_loaded_at` as a baseline before the read and
   deferring to whatever is cached if that baseline advanced while the read was in flight.
   The identical shape exists, unfixed, in the pre-existing `snapshot()`/`_publish()` pair
   for generation settings — filed as its own TODO.md entry rather than fixed here, since it
   predates this feature and widening this diff to include it was not the ask.
2. **`_invalidate_operational_cache()` cleared the cached VALUE, not just its freshness.**
   A generation save immediately followed by a read failure answered `None` (undetermined,
   `503`) instead of the last known value — the fabricated-outage failure mode §5 argues
   against. Fixed by clearing only `_operational_loaded_at`, which is enough to force a real
   re-read without discarding what was last actually observed to be true.
3. **A non-string `lang` reached `quote()` unguarded** in `signup_redirect_url`, raised
   `TypeError`, and was reported as `503 provider_unavailable` — a malformed client request
   read as an upstream outage. `recover()` already validated `lang`'s type; `signup()` did
   not. Fixed by validating it alongside `email`/`password`.

Regression tests for all three are in `web/tests/test_registrations_pause.py`, each verified
to fail against the pre-fix code before being trusted.

**A fourth pass, same day — UX/design review (OpenCode, `opencode/nemotron-3-ultra-free`,
`--variant max`), against `DESIGN.md`.** No `[GATE]` violations. Six `[TASTE]` findings, all
implemented: the reader-facing notice now uses this project's own notice vocabulary
(`.signup-paused-notice` in `static/css/components.css`, matching `.history-notice`'s
sunken-fill-plus-inset-`--warning`-rail shape) instead of a bare Bootstrap `.alert`;
`#signup-tab` carries a small dot (plus `sr-only` text) when paused, so a visitor is not left
to discover the state by clicking in; the console's status indicator is now a real pill
(`.admin-registrations-state`, mirroring `.admin-mark`'s shape) with a `check`/`stop` icon,
using the `.is-signal` tint for "open" and a new `.admin-mark.is-warning` (the neutral
`.is-off` ground, `--warning` text — added to the shared component 2026-08-26 once a fifth
pass found the pill was duplicating `.admin-mark`'s geometry instead of composing it) for
"paused" — **not** a new `--warning-tint`, because `--danger`/`--warning` have no tint
variant anywhere else in this codebase, only text/rail treatments, and one control was not
reason enough to start; pausing (not resuming) now asks for confirmation via `window.confirm`,
matching this console's existing demote/disable-but-not-promote/enable asymmetry; the bypass
note moved into an `.admin-notice` above the toggle rather than a form-hint below it; and the
Arabic strings were tightened to read as considered copy rather than a literal translation.
Two of the review's specifics were checked against the actual CSS and corrected before
implementing rather than taken as given — its claimed "icon + text stack" for the notice
vocabulary does not exist in `.resumed-notice`/`.history-notice` (no icon there; the fix
mirrors the real shape, not the imagined one), and its proposed `--warning-tint` background
would have been the first tint fill this codebase has ever given a `--warning`/`--danger`
severity colour.

**A fifth pass, 2026-08-26 — `/code-review`, run as a forked session with real repository
access (not a fresh sandbox), against the full diff.** Ten findings; three severe enough to
fix immediately, three more addressed the same day, four accepted as pre-existing/tracked or
too small to act on alone:

1. **The installed `supabase_auth` 2.31.0 never returns a response with a populated
   `.error` — it raises.** Every real GoTrue refusal (a duplicate email, a weak password, a
   rate limit) was falling into the blanket `except Exception:` and reported as
   `503 provider_unavailable` — telling a reader whose signup was correctly refused that the
   service was down. No test caught it because every mock modeled the shape the SDK never
   produces. Fixed by catching `AuthError` specifically and reading GoTrue's OWN machine code
   (`AuthApiError.code`, e.g. `email_exists`, `weak_password`, `over_email_send_rate_limit`,
   and — notably — `signup_disabled` if an operator used the dashboard/Management-API hard
   close, which now maps onto the SAME code and status our own console pause answers with)
   rather than the fragile English-substring heuristic, which is kept only as a fallback for
   an unrecognised code. Also corrected the status codes the original hardcoded: `too_soon`
   and `email_unavailable` are `429`, not `400`.
2. **`signup_enabled()` read `self._backend` OUTSIDE its try block.** That property resolves
   `create_client(url, key)` for the real app, which can raise on a present-but-malformed
   URL/key, not just return `None` for an absent one — and `base_render_context()` calls
   `signup_enabled()` unconditionally on EVERY full-page render, including `/admin` and
   `/account`, which never read the result. An unguarded raise there would have 500'd the
   whole site, not just signup. Fixed by moving the property access inside the same try/except
   that already covers `backend.get_settings()`.
3. **No re-check of the flag between the gate and the actual GoTrue call** — contradicting
   `docs/OPERATIONS.md`'s claim of "no window in which the console says Paused and the next
   signup still gets through." On the single-worker/multi-thread deployment, a pause landing
   while a request is mid-flight (past the first check, before the network call) still let
   that one signup through. Fixed by re-reading immediately before the `sign_up()` call, which
   narrows the window from "the whole view" to "one network round trip" — not to zero; that
   would need the `BEFORE INSERT` trigger §4 already rejected. `docs/OPERATIONS.md` corrected
   to say so rather than overclaim.
4. `put_registrations`'s error mapping filtered for an `unknown_setting` code that
   `set_signup_enabled` can never actually produce from this call site — removed as dead code.
5. `.admin-registrations-state` duplicated 10 of `.admin-mark`'s 12 properties instead of
   composing `class="admin-mark is-signal"` / `"is-warning"` — fixed by adding
   `.admin-mark.is-warning` as a proper third state to the shared component (see the UX-pass
   correction above) and composing it, rather than a bespoke duplicate.
6. `initRegistrationsTab`'s load-failure handler hand-rolled the same DOM sequence
   `showPeopleMessage`/`showAuditMessage`/`showSettingsMessage` already implement, with a
   different CSS class — added `showRegistrationsMessage` as the fourth instance of the same
   established (if itself repeated) pattern, rather than a one-off that looked different from
   every sibling panel's failure state.
7. **Accepted, not fixed here:** `SettingsService.snapshot()`/`_publish()` has the identical
   race pattern item 1 of the earlier post-build review fixed for the operational cache — this
   pass independently found the same gap and confirmed it is already tracked in `TODO.md`.
   `Services.signup()` spreading `...metadata` last (a future metadata key literally named
   `email`/`password`/`lang` would silently overwrite the real value) — dormant today, worth a
   `TODO.md` line rather than a defensive rewrite for a collision nothing produces yet. The
   operational and generation caches querying the same JSONB row independently (one extra
   round trip on a cold admin-console open) — a real inefficiency, not a correctness issue, and
   not worth the coupling risk of merging two caches this plan deliberately kept separate.

A sixth dispatch — the same narrow post-fix review, run through `agy-delegate` with
`claude-opus-4-6-thinking` — was attempted first and discarded: its sub-agents fabricated
every file they claimed to quote (a `#signup-tab` markup with `disabled` set, reversing the
tab-stays-selectable decision this document defends twice over; a `tokens.css` in HSL instead
of this project's actual hex ramps; a `set_signup_enabled` with no `actor` parameter) and the
orchestrator certified the invented code as a clean pass. Caught by spot-checking five of its
quotes against the real files — all five wrong — before any of it was trusted. Recorded here
because a discarded review is still evidence: it is why `/code-review` (a forked session with
real repository access) was tried next instead of a second attempt at the same dispatch.

---

## 1. The correction: the route being gated is not the route the product uses

`POST /auth/signup` at `web/api/auth.py:90` is **dead in production**. The browser never
calls it. Its only callers are `web/tests/test_auth_routes.py:182` and
`web/tests/test_auth.py:19`.

The reader signup path is `static/js/modules/handlers.js:249` → `Services.signup`
(`static/js/modules/services.js:369`) → `this.supabase.auth.signUp(...)`, straight to GoTrue
with the public anon key.

TODO.md's instruction — _"gate `signup()` before the Supabase call (return
`403 {error:"signup_disabled"}`)"_ — would therefore refuse a route nobody calls. Its
closing line treats the anon-key bypass as a footnote for `docs/OPERATIONS.md`. It is not a
footnote; it is the only path.

This is worth stating plainly because three of the four planning passes accepted the
entry's framing without checking who calls the route. One of them wrote _"I've verified the
TODO entry's claims against the actual code. Everything checks out"_ and then described the
bypass as an attacker's option rather than as the product's own transport.

`POST /auth/login` is browser-direct too (`services.js:355`). Only `/auth/recover` and
`/auth/logout` actually pass through Flask. `docs/ARCHITECTURE.md`'s "Authentication and the
blueprint gate" section (line 247) never says this, and its rate-limit table (line 270)
lists `POST /auth/recover` and no other auth route — consistent with the rest being unused,
but never written down. §9 Step 16 closes that gap.

**Resolution (user-approved):** move the browser signup onto `POST /auth/signup` first, so
the gate is load-bearing, then add the flag behind it. Steps 1–6 are that migration and ship
as one commit — a half-moved signup path is a broken signup path. Steps 7–13 are the pause.
Steps 14–16 are documentation and ship with whichever commit made them true.

`login` deliberately stays browser-direct: nothing gates it, so moving it is cost without a
property. That reasoning belongs in `docs/ARCHITECTURE.md`, not only here.

---

## 2. The trap: "extend `SettingsService`" is right, and has a wrong reading either side

TODO.md says _"extend `SettingsService` with a non-generation key set + bool validation and
30–60s TTL with immediate invalidate on `PUT`."_ That is the right answer. Both obvious
readings of it are wrong, and the repo contains a live example of the second.

### Wrong reading A — widen `GENERATION_KEYS`

`update()`'s unknown-key check is `set(patch) - set(GENERATION_KEYS)`
(`web/services/settings_service.py:348`), so `PUT {"signup_enabled": false}` is a
`422 unknown_setting` today. Adding the key to that tuple drags a boolean through
`deployed_defaults`, `snapshot`, `overrides`, `read_overrides`, `_publish` and `validate`,
each needing an "except not this one" branch. Two consequences are concrete rather than
aesthetic:

- **`validate()` is pairwise and generation-coupled** — it merges the patch with
  `deployed_defaults()` and cross-checks model against token ceiling against reasoning
  effort. A boolean has no business in that function.
- **`apply_generation_settings` reads `snapshot()` wholesale.** `web/api/app.py:1786` does
  `settings = app.config["settings_service"].snapshot()` and passes it straight to
  `factory(settings)`, where the factory is the `OpenAIHandler` class itself
  (`app.py:1549`). Put the flag in `deployed_defaults()` and it lands in that dict, in
  `GET /admin/api/settings`'s `settings` and `defaults` payloads, and — because
  `put_settings` at `admin.py:220` runs `apply_settings()` inside the write lock — every
  registrations toggle rebuilds the OpenAI handler and logs "Generation settings applied".
  It does not crash (the constructor reads named keys), which is what makes it easy to ship
  by accident.

### Wrong reading B — copy the non-generation setting the repo already has

`web/services/notification_store.py:761` states the pattern verbatim: a non-generation
setting in the same `app_settings.settings` JSONB _"without touching the generation-specific
validation layer"_, implemented as a standalone `get_purge_retention_days` /
`set_purge_retention_days` pair (lines 767 and 796) reading and writing `admin_backend`
directly, never touching `SettingsService`.

It is the obvious model and it should **not** be copied, because it lacks the two things
this flag needs:

- **No cache.** It reads the store on every call. Fine for a value read once per
  Notifications-tab load; not fine for one read on every signup _and_ every page render.
- **No lock.** It does its own read-modify-write without taking `SettingsService._write_lock`
  (`settings_service.py:363`), so a generation save concurrent with a retention change is a
  lost update. **That bug is live today.** Do not add a second instance of it.

### The shape to build

A **parallel key family inside `SettingsService`**: `NON_GENERATION_KEYS` beside
`GENERATION_KEYS`, its own validator, its own cache slot and TTL, its own accessors —
sharing the class's `_write_lock` and its one audited backend write, and nothing else.
Detail in §9 Step 8.

> **Why the document survives a generation save either way.** `update()` reads through
> `_read_overrides()`, which returns the **raw** stored dict rather than a filtered one, then
> writes `stored` back whole (`settings_service.py:359–396`). A non-generation key
> round-trips intact — which is how `notifications_purge_retention_days` survives today.
> The corollary is load-bearing: because a generation `PUT` replaces the whole document, it
> must also invalidate the flag's cache, even though it changed no flag.

---

## 3. Decisions, and what settles each

| Question                               | Decision                                                                                  | What settles it                                                                                                                                                                                                                                                                                                                                        |
| -------------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Where the flag lives                   | `app_settings.settings.signup_enabled` (bool), same single JSONB row                      | No migration. The row is `id = 1` by check constraint, RLS on with zero policies, `revoke all … from anon, authenticated` — `20260814022601_app_settings.sql:31,53,57`                                                                                                                                                                                 |
| Which service owns it                  | `SettingsService`, as a parallel `NON_GENERATION_KEYS` family                             | §2                                                                                                                                                                                                                                                                                                                                                     |
| Which endpoint toggles it              | New `GET/PUT /admin/api/registrations`                                                    | Keeps `put_settings`'s tested response contract and its `applied`/`active` semantics unchanged; keeps the console's two controls independently savable; and makes mixed-patch validation a non-problem rather than something to solve. `admin.py:1261,1273` (`notifications/purge-settings`) is the in-repo precedent for a sibling settings endpoint. |
| How it is audited                      | `admin_backend.put_settings(...)` → `admin_write_settings` RPC → action `settings.update` | The RPC hardcodes the action string (`20260814032139_audit_log.sql:117`). Reusing it needs no migration and already renders in the console via `static/js/admin/ui.js:764`. The `before`/`after` diff names the key.                                                                                                                                   |
| Propagation                            | **Publish on write**, not TTL expiry                                                      | Single worker. The write path can install the committed value directly, exactly as `_publish` does for generation settings (`settings_service.py:322`). TODO.md's "30–60s TTL" is over-specified — see below.                                                                                                                                          |
| Cache                                  | 45s TTL in its own slot, cleared after **every** `PUT` to the row                         | The TTL is not the propagation mechanism. Its only job is bounding staleness from an **out-of-band edit** — someone changing the row in the Supabase SQL editor, which the console cannot know about. Worth 45 seconds; not worth building anything clever.                                                                                            |
| Store unreachable, value known         | Serve the stale value, however old                                                        | A pause must survive a Supabase blip. Reverting to the config default would silently re-open signups mid-incident.                                                                                                                                                                                                                                     |
| Store unreachable, nothing ever cached | `503 {"error": "auth_unavailable"}` — never `403`, never `201`                            | §5                                                                                                                                                                                                                                                                                                                                                     |
| Reader-facing proactive state          | Server-rendered into `base_render_context` (`app.py:1960`)                                | No new public endpoint, no round trip, no flash, and `app_settings` stays unreachable from the browser. The shell already sends `Cache-Control: no-cache`.                                                                                                                                                                                             |
| Rate limit on the migrated route       | New `signup_bp`, limited in `_register_routes`                                            | Signup sends mail. `auth.py:11–23` documents why a decorator at import registers nowhere, and why `recover_bp` exists as its own blueprint rather than limiting all of `auth_bp`: "a 5/minute ceiling on logout would be wrong."                                                                                                                       |

---

## 4. Storage alternatives, priced

| Option                                                               | Cost                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Verdict                                                               |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------- |
| **JSONB key** `app_settings.settings.signup_enabled`                 | None. The row, the RPC, the audit path and the read path all exist.                                                                                                                                                                                                                                                                                                                                                                                                      | **Chosen**                                                            |
| **Dedicated column** on `app_settings`                               | A migration; widening `get_settings`'s `select("settings")` at `admin_store.py:282`; a new signature for `admin_write_settings`, so the audit RPC changes too; then the mandatory rename-after-apply ritual (collision #2). Buys Postgres-level typing for a value already validated in Python and re-validated on read.                                                                                                                                                 | Rejected                                                              |
| **A distinct audit action** e.g. `registrations.pause`               | The action string is hardcoded inside the RPC body (`20260814032139_audit_log.sql:117`), so a new name means a new or replaced RPC — a migration, the rename ritual, and a new entry in the console's action map at `admin/ui.js:764` or the audit tab renders a raw string. Buys a marginally better audit line for a change whose `before`/`after` diff already names `signup_enabled` unambiguously.                                                                  | Rejected                                                              |
| **A separate settings table**                                        | Everything above, plus a second single-row table — which `20260814022601_app_settings.sql:31` explicitly designed against: "a second row would be a silent fork of the instance's configuration."                                                                                                                                                                                                                                                                        | Rejected                                                              |
| **`BEFORE INSERT` trigger on `auth.users`** that raises while paused | The only option that actually closes the anon-key hole from inside the repo, and it is feasible — the project already owns an `AFTER INSERT` trigger on that table. But it would also block admin-created accounts and any provider-internal flow, and collision #1 in `docs/ARCHITECTURE.md` records that a raise in that position rolls back account creation entirely. A pause that can strand a provider-internal write is a worse failure than the one it prevents. | Rejected — reconsider only if the provider toggle proves insufficient |

---

## 5. The contested call: what a signup does when the flag cannot be read

Four passes, four answers. The reasoning is set out rather than asserted.

| Pass               | Answer                                | Argument                                                                                                                                                                         |
| ------------------ | ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Antigravity        | Fail closed, `503`                    | Operators pause during surges and degradation; falling back to "open" floods a database that is already failing. Serve the cached snapshot while one exists.                     |
| OpenCode           | Fail closed, `403 signup_disabled`    | Same concern stated harder: "an open read outage would allow new registrations exactly when the operator may be trying to stop them." Strict read path, one code for both cases. |
| User-supplied plan | Fail **open** to the deployed default | Cites the codebase's stance that "a settings outage must not cost a reader their answer", and argues the pause is an availability control, not a security boundary.              |
| **This plan**      | **Stale if known, else `503`**        | Splits the case the other three merge.                                                                                                                                           |

The two fail-closed passes are right that the flag must not silently flip open during an
incident. But that concern is entirely about **a pause already in force** — and serving the
last known value answers it completely, without a policy that guesses.

The fail-open pass misapplies its quote. `settings_service.py:257` is about **generation**
settings for an existing reader's answer in flight; it is not a general licence for a gate
to assume "permitted" when it cannot check.

What is left is genuinely different from all three: a process that has never successfully
read the flag, during an outage. There, "closed" is not a safe default, it is a fabricated
one. Answering `403 signup_disabled` tells a reader an operator paused registrations when
none did, and there is no audit row to check because nothing was written. It would also mean
a cold restart during a Supabase blip silently closes signups on an instance nobody paused —
with the console still reporting _Open_, because the console reads the same unreadable
store.

That is a failure this repo has already ruled on. `docs/ARCHITECTURE.md:254`: **"An outage is
not a refusal."** The identity path implements exactly this three-way split, keeping
`_is_upstream_outage()` and `_is_auth_refusal()` separate so a `503` is never a `401`.

Hence the flag is **three-valued** at the service boundary — `True`, `False`, `None` — and
`None` is a `503`. In practice the window is tiny: only a cold process whose very first read
fails. Every other outage is covered by the stale value.

> **Related.** `20260814022601_app_settings.sql:28` declines optimistic concurrency on the
> row: "There is deliberately no `version` column… One operator cannot race themselves. Add
> it alongside the second administrator." That reasoning holds only while every writer takes
> the same in-process lock — which is why the flag belongs inside `SettingsService` rather
> than in a sibling module that would quietly reintroduce the race.

---

## 6. Reader-facing behaviour

Two states, and they are not the same problem.

**Proactive** — the page is rendered while signups are paused. `base_render_context`
(`app.py:1960`) carries `signup_enabled`; the template renders `#signup-paused` (an
`.alert.alert-secondary` with `role="status"`) and hides `#signup-form`. This mirrors
`#signup-sent` at `index.html:328`, which already establishes the pattern of an alert
replacing the form outright.

**`#signup-tab` (`index.html:160`) stays selectable.** The user-supplied plan proposed
disabling it with `aria-disabled="true"`. A disabled tab announces "disabled" to a screen
reader with no reason attached, and a visitor who came specifically to register is told
nothing. A selectable tab that explains itself is both the accessible answer and the
respectful one. (If a tab is ever disabled here, `aria-disabled` is the right mechanism —
that part of the suggestion is correct.)

An undetermined flag renders the form **open**. A page that hides the form on an unreadable
store would hide it during every blip; the `503` at submit time is the honest place to say
"we could not check."

**Reactive** — the flag flipped after the page was rendered. The `403` arrives mid-submit
and `handleAuthFormSubmit`'s catch (`handlers.js:266`) surfaces it. This is why the reactive
path is not optional: a server-rendered proactive state is always potentially stale, by
exactly the age of the open tab.

### Alternative considered

OpenCode proposed a public `GET /auth/signup/status` with `signupEnabled` in `AppState` and
an optimistic initial `true`. It has one real advantage — a modal already open can update
without a reload. Not taken: it costs a round trip on every page load, a new public endpoint,
new state, and a visible flash from optimistic `true` to the real value, for a control that
changes a few times a year.

One thing that pass got right and is worth recording either way: **a status route must not
live on the rate-limited signup blueprint.** If this is revisited, put it elsewhere, or a
reader who loads the page six times a minute gets a 429 for reading a boolean.

---

## 7. Machine codes, not sentences

The route today translates GoTrue errors into English prose — `"This email is already
registered"` at `auth.py:143`. That is a second reader-facing string path the app does not
have, and it would break the browser's existing matcher, which looks for GoTrue's own
wording (`'user already registered'`, `dom.js:138`).

| Condition                      | Status | Body                                |
| ------------------------------ | ------ | ----------------------------------- |
| Signups paused                 | 403    | `{"error": "signup_disabled"}`      |
| Cannot determine the flag      | 503    | `{"error": "auth_unavailable"}`     |
| Missing email or password      | 400    | `{"error": "missing_fields"}`       |
| Address already has an account | 400    | `{"error": "already_registered"}`   |
| Malformed address              | 400    | `{"error": "invalid_email"}`        |
| Password rejected by GoTrue    | 400    | `{"error": "weak_password"}`        |
| GoTrue per-address cooldown    | 429    | `{"error": "too_soon"}`             |
| Project email allowance spent  | 429    | `{"error": "email_unavailable"}`    |
| Provider unreachable           | 503    | `{"error": "provider_unavailable"}` |

The house rule is already written down, at `settings_service.py:39`: _"A machine code, not a
sentence… The client owns every reader-facing string in both languages; a message composed
here would be a second translation path this app does not have."_

`formatAuthError` gains a code branch **ahead of** the substring map, and **keeps** the
substring map: login still goes through supabase-js and still throws GoTrue's English.
Deleting it would regress every login error to untranslated English.

---

## 8. i18n

Nest under `runtime.auth`, `runtime.admin` and `page.auth` — all three exist. **No new
top-level `runtime.*` namespace:** `web/tests/test_admin_page.py:228` asserts
`set(config) <= {…eleven…}`, and `docs/ARCHITECTURE.md:331` lists this as collision #3.

Do **not** nest the console strings under `runtime.admin.settings.*`. That panel's heading
is literally `"Generation"` (`en.yaml`), and a registrations switch inside it is a category
error. Use `runtime.admin.registrations.*`.

| Key                                       | English                                                                                                              | العربية                                                                                         |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `runtime.auth.signupDisabled`             | New registrations are paused right now. If you already have an account, sign in above.                               | تسجيل الحسابات الجديدة متوقف مؤقتاً. إذا كان لديك حساب، سجّل الدخول من الأعلى.                  |
| `runtime.auth.signupUnavailable`          | We could not check whether registration is open. Please try again in a moment.                                       | تعذّر التحقق مما إذا كان التسجيل مفتوحاً. يرجى المحاولة بعد قليل.                               |
| `runtime.auth.weakPassword`               | That password was not accepted. Try a longer one.                                                                    | لم يتم قبول كلمة المرور هذه. جرّب كلمة مرور أطول.                                               |
| `page.auth.signupPaused.heading`          | Registration is paused                                                                                               | تسجيل الحسابات متوقف مؤقتاً                                                                     |
| `page.auth.signupPaused.lead`             | New accounts are not being created at the moment. Existing accounts sign in as usual.                                | لا يتم إنشاء حسابات جديدة في الوقت الحالي. أما الحسابات الحالية فتسجّل الدخول كالمعتاد.         |
| `runtime.admin.registrations.heading`     | Registrations                                                                                                        | التسجيل                                                                                         |
| `runtime.admin.registrations.hint`        | Applies to the signup form immediately. Readers who are already signed in are unaffected.                            | يسري على نموذج التسجيل فوراً. لا يؤثر على القرّاء الذين سجّلوا دخولهم بالفعل.                   |
| `runtime.admin.registrations.open`        | Open                                                                                                                 | مفتوح                                                                                           |
| `runtime.admin.registrations.paused`      | Paused                                                                                                               | متوقف                                                                                           |
| `runtime.admin.registrations.pause`       | Pause registrations                                                                                                  | إيقاف التسجيل                                                                                   |
| `runtime.admin.registrations.resume`      | Resume registrations                                                                                                 | استئناف التسجيل                                                                                 |
| `runtime.admin.registrations.saving`      | Saving…                                                                                                              | جارٍ الحفظ…                                                                                     |
| `runtime.admin.registrations.savedPaused` | Registrations paused.                                                                                                | تم إيقاف التسجيل.                                                                               |
| `runtime.admin.registrations.savedOpen`   | Registrations resumed.                                                                                               | تم استئناف التسجيل.                                                                             |
| `runtime.admin.registrations.loadFailed`  | Could not load the registrations setting.                                                                            | تعذّر تحميل إعداد التسجيل.                                                                      |
| `runtime.admin.registrations.saveFailed`  | Could not save the registrations setting.                                                                            | تعذّر حفظ إعداد التسجيل.                                                                        |
| `runtime.admin.registrations.bypassNote`  | This pauses the signup form. It does not stop a direct call to the authentication provider — see docs/OPERATIONS.md. | هذا يوقف نموذج التسجيل فقط، ولا يمنع الاتصال المباشر بمزوّد المصادقة — راجع docs/OPERATIONS.md. |

Copy is checked against `docs/PRODUCT.md`'s voice rule — "direct and professional,
occasionally warm… the regulatory content stays sober." No "kill-switch", no "service down".

---

## 9. Implementation sequence

### Commit A — make the gate load-bearing (steps 1–6)

**Step 1 — Give signup its own rate-limited blueprint.**
`web/api/auth.py:23` (beside `recover_bp`) · `web/api/app.py:1859` (beside its registration)
· `web/config.yaml:83` (`server.rate_limit`).
Add `signup_bp`, move the `POST /signup` view onto it (URL unchanged under
`url_prefix="/auth"`), register and limit it exactly as `recover_bp` is at `app.py:1859–1862`,
reading `server.rate_limit.signup_api`, default `"5 per minute"`.
**Do not use a decorator.** `auth.py:11–22` records that this exact mistake "registers the
limit nowhere and the endpoint answers unlimited, which is what happened here and is
invisible until something exercises it."
_As built:_ no test proves this one. `create_app` sets `RATELIMIT_ENABLED=not
testing` (`app.py`, `_configure_app`), Flask-Limiter reads that once at
`init_app` and binds it to an instance attribute rather than re-reading
`app.config` per request, and the `Limiter` instance itself is never retained
anywhere `create_app`'s caller can reach to flip it back on for one test.
`recover_api`'s own rate limit has never had a test either, for the same
reason — this was a genuine gap in the test harness, not something this
migration introduced, and it surfaced only once a "Proves it" line asserted a
test that could not exist as written. Recorded rather than silently dropped.

**Step 2 — Forward metadata, on an allow-list.**
`web/api/auth.py:90–146`.
The installed client is `supabase 2.31.0`; the module is `supabase_auth`, not `gotrue`, and
`SignUpWithEmailAndPasswordCredentialsOptions` is `{email_redirect_to, data, captcha_token}`
— the same shape supabase-js takes.

```python
response = supabase.auth.sign_up(
    {"email": email, "password": password, "options": {"data": metadata}}
)
```

Build `options.data` from exactly six keys — `first_name`, `family_name`,
`marketing_consent`, `marketing_consent_policy_version`, `marketing_consent_language`,
`age` — copied **by presence, not truthiness**, so `False` and `0` survive.

This is a security gain the migration makes available and should not be skipped.
`services.js:356` currently warns: _"Never send anything here this app is not prepared to
have a direct GoTrue caller send maliciously: that trigger is the only validation."_ Once the
server composes the object, that stops being true for the product path.

**Pass the JSON through unconverted.** `handle_new_user`
(`20260823014034_marketing_consent_record.sql:300`) tests
`jsonb_typeof(v_meta -> 'marketing_consent') = 'boolean'`, and at line 372 records the
consent source as `'signup'` only when that test passes. Stringify the field and consent
silently becomes a decline for every new account. Everything else it coerces toward null
rather than raising — deliberately, because it is an AFTER INSERT trigger on `auth.users`
and a raise there rolls back account creation.

**Send `email_redirect_to` only when it is valid.** Add `signup_redirect_url(lang)` beside
`recovery_redirect_url` (`web/services/account_recovery.py:154`), reusing its
`PUBLIC_BASE_URL` validation — never `request.host_url`, for the reason that function
documents: "the Host header is attacker-controlled, and a poisoned Host would mail readers a
link pointing at somewhere else entirely." Drop the `?recovery=1` marker; keep `&lang=`.
Where they must differ: `recovery_redirect_url` **raises** when `PUBLIC_BASE_URL` is unset,
and refusing to send is right for a recovery mail. For signup it is not — the browser sends
no redirect today, so GoTrue uses the project Site URL and signup works on instances that
never set it. Omit the option when the base URL is absent or malformed, and log it.
_Proves it:_ `::test_signup_forwards_only_the_allowed_metadata_keys`,
`::test_signup_omits_the_redirect_when_public_base_url_is_unset`.

**Step 3 — Return codes, not sentences.** `web/api/auth.py:135–146`. Table in §7.
_Proves it:_ `::test_signup_answers_in_codes_not_sentences`, mirroring
`test_admin_settings.py::test_the_server_sends_codes_not_sentences`.

**Step 4 — Point `Services.signup` at Flask.** `static/js/modules/services.js:369`.
Replace the `supabase.auth.signUp` call with a `fetch('/auth/signup')` POST modelled on
`requestPasswordReset` two methods below (`services.js:394`) — including `credentials:
'same-origin'` and its habit of attaching `error.code` from the body before throwing.
`services.js` is transport only: it may not import view or state and may not name
`ErrorHandler` or `DOMCache` (`test_frontend_architecture.py`). Throw a coded error; let
`handlers.js` decide what the reader sees.

**Step 5 — Map codes to catalogue keys.** `static/js/modules/dom.js:131` ·
`static/js/modules/handlers.js:266`.

```js
const byCode = {
  signup_disabled: I18n.t('auth.signupDisabled'),
  auth_unavailable: I18n.t('auth.signupUnavailable'),
  provider_unavailable: I18n.t('auth.signupUnavailable'),
  missing_fields: I18n.t('auth.missingFields'),
  already_registered: I18n.t('auth.alreadyRegistered'),
  invalid_email: I18n.t('auth.invalidEmail'),
  weak_password: I18n.t('auth.weakPassword'),
  too_soon: I18n.t('auth.tooSoon'),
  email_unavailable: I18n.t('auth.emailUnavailable'),
};
if (error?.code && byCode[error.code]) return byCode[error.code];
```

Five of the nine keys already exist. Only `signupDisabled`, `signupUnavailable` and
`weakPassword` are new.
_Proves it:_ `test_frontend_architecture.py::test_signup_errors_map_from_codes`, in the style
of the existing `test_auth_flow_uses_the_i18n_catalogue_not_literals`.

**Step 6 — Rewrite the signup browser suite against the request.**
`web/tests/test_signup_identity_capture.py` (all 7) · `web/tests/conftest.py:48`.
Every test there asserts `window.__supabaseState.lastSignUpMetadata`, written by the JS
stub's `signUp`. Once signup is a `fetch`, the stub never sees it.

Do **not** add a testing-only server endpoint to read the metadata back. Intercept in
Playwright, capturing the body and fulfilling a deterministic `201` — that keeps the
assertion about what the client sends, removes any dependency on the Flask double's provider
behaviour, and guarantees no test ever sends real confirmation mail.

```python
sent = []


def capture(route):
    sent.append(route.request.post_data_json)
    route.fulfill(
        status=201,
        content_type="application/json",
        body='{"message":"User created successfully","user":{"id":"u1","email":"new@example.com"}}',
    )


browser_page.route("**/auth/signup", capture)
```

| Test                                                         | Becomes                                                                                           |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| `test_first_name_is_required_by_the_form`                    | `sent == []` instead of `lastSignUpMetadata is None`                                              |
| `test_family_name_is_optional`                               | Assert on `sent[0]["metadata"]`; `#signup-sent` check unchanged                                   |
| `test_signup_sends_both_names_as_gotrue_metadata`            | Same substitution; rename to `…_as_signup_metadata` — it is no longer GoTrue the browser talks to |
| `test_terms_acceptance_is_required_by_the_form`              | `sent == []`                                                                                      |
| `test_the_terms_checkbox_links_to_the_privacy_policy`        | Unchanged — pure DOM                                                                              |
| `test_marketing_consent_gates_the_age_field`                 | Unchanged — pure DOM                                                                              |
| `test_signup_sends_consent_context_when_marketing_is_ticked` | Assert on `sent[0]["metadata"]`, including that `marketing_consent` is JSON `true`, not `"true"`  |

Confirm each rewritten test fails against the pre-migration client before believing it.

### Commit B — the pause (steps 7–13)

**Step 7 — Declare the deployed default.** `web/config.yaml:9`, in the `server:` block:

```yaml
# Whether the signup form accepts new accounts. An operator pauses
# registrations from the console, which stores an override in
# app_settings; an absent override means this value. Deployed true so
# an instance that has never been paused is open.
#
# This is an APPLICATION control. It does not stop a caller talking to
# the authentication provider directly with the publishable anon key —
# see docs/OPERATIONS.md for the hard close.
signup_enabled: true
```

**Step 8 — Add the second key family to `SettingsService`.**
`NON_GENERATION_KEYS` beside line 28 · `deployed_non_generation_defaults()` beside line 93 ·
`validate_non_generation()` beside line 141 · methods after `overrides()` at line 300.

```python
NON_GENERATION_KEYS: tuple[str, ...] = ("signup_enabled",)


def deployed_non_generation_defaults() -> dict[str, Any]:
    return {"signup_enabled": config.get("server", "signup_enabled", True)}


class SettingsService:
    def __init__(
        self, backend_provider, ttl_seconds: float = 60.0, operational_ttl_seconds: float = 45.0
    ) -> None: ...

    def signup_enabled(self) -> bool | None:
        """True, False, or None meaning "could not determine".

        Three-valued on purpose: a caller has to tell "an operator paused
        this" from "we could not check", because those are a 403 and a 503
        and they mean opposite things to a reader.
        """

    def set_signup_enabled(self, enabled, *, actor) -> list[ValidationError]:
        """Empty list means written. Takes the same _write_lock as update()."""
```

Behaviour, in order:

- **Reject anything that is not a JSON boolean.** Use `type(value) is bool`, not
  `isinstance` — `isinstance(True, int)` is `True` in Python, which is why every numeric
  validator in this file already carries an explicit `not isinstance(v, bool)` guard. Here
  the test runs the other way: `1`, `0`, `"true"`, `"false"` are all
  `ValidationError("signup_enabled", "not_a_boolean")`. `None` keeps its existing meaning —
  remove the override, revert to the deployed default.
- **Its own cache slot**, `_operational_cached` / `_operational_loaded_at`, distinct from
  `_cached`, so a flag read can never be served from or overwrite the generation snapshot.
- **Publish the committed value on write**, the way `_publish` does at line 322 — that, not
  TTL expiry, is what makes a console toggle take effect immediately.
- **Clear the slot after every successful write to the row — including a generation-only
  `PUT`.** `put_settings` replaces the whole document, so a generation save is a write to the
  flag's storage whether or not it changed the flag. Missing this is the subtle bug in this
  design.
- **Never run `on_committed` for a flag write.** That hook rebuilds `OpenAIHandler`
  (`app.py:1786`). A registrations toggle has no business restarting generation.
- **On read failure:** return the last known value if there is one, however stale, and log at
  `error`. Only if nothing was ever cached return `None`.
- **No backend at all** (no service-role key, or testing without the in-memory backend) is
  **not** a failure — nothing can ever have been written, so answer the `config.yaml`
  default. This is the reasoning `read_overrides` already gives at `settings_service.py:313`.
- **A malformed stored value** (a string, a number, a null) reverts to the default rather
  than propagating — the column is JSONB with no shape constraint, and `snapshot()` already
  holds this line for generation keys.
- **`read_overrides()` stays generation-only.** Startup adoption at `app.py:1832` feeds
  `apply_generation_settings` and must not learn about the flag; the gate reads lazily on its
  own path, so a store outage at boot still cannot stop the process.

_Proves it,_ added to `web/tests/test_admin_settings.py` beside the generation tests that
already establish these shapes: `test_signup_enabled_is_absent_from_the_generation_snapshot_and_overrides`,
`test_a_string_true_is_refused` (parametrised over `1, 0, "true", "false", []`),
`test_null_reverts_to_the_deployed_default`, `test_a_write_is_visible_immediately`,
`test_the_flag_cache_expires` (injected monotonic clock),
`test_a_generation_save_invalidates_the_flag_cache`,
`test_a_read_failure_serves_the_last_known_value`,
`test_a_cold_read_failure_is_undetermined`,
`test_a_flag_write_does_not_rebuild_the_handler`.

**Step 9 — Gate the view body, before the provider call.** `web/api/auth.py`, inside
`signup()`, between the missing-fields guard and `get_supabase()`:

```python
enabled = current_app.config["settings_service"].signup_enabled()
if enabled is None:
    return jsonify({"error": "auth_unavailable"}), 503
if not enabled:
    return jsonify({"error": "signup_disabled"}), 403
```

**After** the `400` for missing fields: a malformed request is malformed whether or not
signups are open, it should not spend a settings read, and "registrations are paused" is a
wrong answer to a blank password — one the reader cannot act on. **Before** the client is
resolved: a paused instance should not touch the provider at all.

_Proves it:_ `test_registrations_pause.py::test_a_paused_instance_refuses_signup` — and this
test must **assert the Supabase client was never constructed**, not merely that the status is 403. The status alone does not prove the gate ran before provider work, which is the actual
requirement. Plus `::test_an_open_instance_still_creates_an_account` (201, guarding the
regression), `::test_an_undetermined_flag_is_a_503_not_a_403`,
`::test_a_blank_password_is_still_a_400_while_paused`.

**Step 10 — Add the admin endpoints.** `web/api/admin.py`, beside
`notifications_purge_settings` at line 1261.
`GET /admin/api/registrations` → `{"signup_enabled": bool, "default": bool}` — the second so
the console can say "deployed default" the way the settings panel already distinguishes an
override from a default. `PUT` takes `{"signup_enabled": bool}`, calls `set_signup_enabled`
with `actor_from_request(g.identity)`, maps a validation failure to
`422 {"error": "invalid_signup_enabled"}` and a missing backend to
`503 {"error": "storage_unavailable"}`.
Nothing needs adding for authorisation: `_gate` (`admin.py:99`) is a `before_request`
covering the whole blueprint and `_UNGATED_ENDPOINTS` (`admin.py:58`) is `{"admin.console"}`
only. Do not add a route decorator gate — `docs/ARCHITECTURE.md:259`: "A decorator can be
forgotten on route nine, and that failure is silent."
_Proves it:_ `::test_the_toggle_requires_a_bearer_header`,
`::test_a_reader_cannot_toggle_registrations`, `::test_the_toggle_writes_an_audit_row`
(asserts the `InMemoryAdminBackend` recorded `settings.update` with
`after == {"signup_enabled": False}`).

**Step 11 — Render the paused state.** `web/api/app.py:1960` ·
`web/templates/index.html:160, 232, 328`. Design in §6.
_Proves it:_ `::test_a_paused_page_renders_the_notice_and_hides_the_form`,
`::test_an_undetermined_flag_still_renders_the_form`, and a Playwright pass in both languages
asserting the notice text and that `#signup-tab` is still selectable.

**Step 12 — Add the console control.** `static/js/admin/services.js:114` ·
`static/js/admin/handlers.js:1231` · `static/js/admin/ui.js:180` ·
`web/templates/admin.html:150`.
Transport first: `registrations: () => request('registrations')` and
`saveRegistrations: (body) => request('registrations', { method: 'PUT', body })`, beside the
existing `settings` pair.
Render it as its own block inside `#panel-settings`, **above** the generation form and
separated by a rule — not as a field inside it. `runtime.admin.settings.heading` is literally
`"Generation"`, and a registrations switch inside that panel would also ride the generation
form's single Save button, coupling two unrelated writes.
States: current standing as a pill (_Open_ / _Paused_), one button labelled with the action it
performs, a saving state reusing the disabled-button pattern at `admin/ui.js:445`, and the
bypass note as permanent small print — an operator deciding to pause is exactly the person
who needs to know what the pause does not cover.
_Proves it:_ `test_admin_browser.py::test_an_operator_can_pause_and_resume_registrations` —
click, expect the pill to flip, reload, expect it to persist.

**Step 13 — Write both catalogues in the same edit.** §8.
_Proves it:_ the existing `test_frontend_architecture.py:182`, which flattens both `runtime`
and `page` and fails on any English key with no Arabic sibling.

### Documentation (steps 14–16)

**Step 14 — Bump `ASSET_VERSION`.** `web/api/app.py:248`. Both commits touch JS, so both
bump it. The durable instruction is _bump it_; do not copy a value out of this document.

**Step 15 — `docs/OPERATIONS.md`,** a new sibling section per its own instruction at line 12.
Two facts belong there because neither lives in the repository:

> **Registrations pause — what it covers.** The console's registrations pause refuses
> `POST /auth/signup`. It is an application control and it is audited. It does **not** stop a
> caller who talks to GoTrue directly: `SUPABASE_URL` and the publishable anon key are in the
> page by necessity, and `POST /auth/v1/signup` against the project accepts them whatever
> this app decides.
>
> For a hard close, disable email signups at the provider — dashboard **Authentication →
> Sign In / Providers → Email**, or the Management API:
>
> ```bash
> curl -X PATCH "https://api.supabase.com/v1/projects/$PROJECT_REF/config/auth" \
>   -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
>   -H "Content-Type: application/json" \
>   -d '{"disable_signup": true}'
> ```
>
> That change is outside this app's audit log. If you make it, note it here with the date and
> who made it, and lift both controls when the incident ends — a provider-side close leaves
> the console still reporting "Open."
>
> **Confirm email must stay enabled.** Signup is server-mediated as of this change. With
> "Confirm email" **on**, GoTrue returns a user and no session, the server answers `201`, and
> the browser shows the check-your-mail panel — the behaviour readers have today. If Confirm
> email is ever turned **off**, GoTrue returns a session to the _server_, which does not
> forward it, and the reader would be told to check mail that never arrives while holding no
> session. Turning that setting off now requires a code change, not just a dashboard toggle.

Also record the failure posture (§5) and that propagation is immediate on a single worker
(§3), so nobody later builds TTL machinery this deployment does not need.

**Step 16 — Correct the architecture record and close the entry.**
`docs/ARCHITECTURE.md:247, 270` — state which auth calls are browser-direct (§1) and add
`POST /auth/signup` to the rate-limit table.
Then follow `TODO.md:907` exactly: (1) add a **dated closing note to the entry itself**,
saying what shipped and — because the original diagnosis was wrong — saying so rather than
editing it into looking right; (2) **move the whole entry** to
`docs/archive/TODO-resolved.md` under _Resolved planned work_, not strike it through in
place; (3) **delete its line from Open now**; (4) check every document the entry named is
still true.

---

## 10. Rollout and rollback

|     | Step                                                                    | Verify                                                                                                                                                                            |
| --- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | No schema change ships.                                                 | `list_migrations` is unchanged.                                                                                                                                                   |
| 2   | Deploy commit A. Signup behaviour is unchanged from a reader's side.    | Create a real account on the deployed host. Confirm the mail arrives and `profiles` has both names and the consent record — that proves metadata survived the new path.           |
| 3   | Deploy commit B. The flag has no override, so every instance is open.   | `GET /admin/api/registrations` → `{"signup_enabled": true, "default": true}`.                                                                                                     |
| 4   | Operator pauses from **/admin → Settings → Registrations**.             | Audit tab shows a `settings.update` row whose diff names `signup_enabled`. Reload `/` and `/?lang=ar`: the signup tab opens onto the notice, in the right language and direction. |
| 5   | Confirm the pause is not load-bearing on its own, before relying on it. | `curl` the project's `/auth/v1/signup` with the anon key. It still works. If that is unacceptable for the incident, apply the provider hard close as well.                        |

**Rollback**

- **Undo the pause** — resume from the console. Instant, audited, no deploy. This is the
  normal path and it is why the feature exists.
- **Clear the override entirely** — `PUT` with the key `null`, reverting to the `config.yaml`
  default. Distinct from setting it to `true`, which pins it against a future deploy.
- **Revert commit B** — safe alone. A stored `signup_enabled: false` becomes an inert key in
  the JSONB document; nothing reads it, nothing breaks, and it round-trips harmlessly through
  generation saves.
- **Revert commit A** — must revert B first, or the gate has no route to gate. Reverting A
  alone leaves the flag stored and the console reporting a pause that is not in force.

---

## 11. What must not ship

- **No RLS policy on `app_settings`.** The migration says so in capitals: "RLS on, ZERO
  POLICIES, DELIBERATELY… Do not 'fix' this by adding a policy." The advisor's
  `rls_enabled_no_policy` INFO is the intent.
- **No RLS write policy on the chat tables.** Unchanged by this work; stated because the
  entry touches settings storage and the two are easy to conflate.
- **No browser-direct read of the flag.** `docs/ARCHITECTURE.md:235`: `profiles` is the one
  browser-direct table, and `app_settings` has `revoke all … from anon, authenticated`.
- **No new top-level `runtime.*` namespace.**
- **No bundler, no runtime `node_modules`.** `node_modules/` stays lint-tooling only.
- **No physical CSS properties.** `test_css_contract.py` bans sixteen. Remember what it does
  not cover: the templates load the **LTR** Bootstrap build, so a green suite proves nothing
  about whether a Bootstrap component mirrors (collision #5). Check the paused notice in
  Arabic by eye.
- **No cross-process state.** Module-scope RAM, single worker. No Redis, and do not raise
  `WEB_CONCURRENCY` — `app.py:1927` already warns, and the FAISS index makes it wrong anyway.
- **No `403` when the answer is "could not check."** The one shape of this feature that
  would lie to a reader.
- **No English composed on the server.**
- **No arbitrary metadata forwarded to `raw_user_meta_data`.** Six allowed keys, by presence.
- **No confirmation redirect built from `request.host_url`.**
- **No `supabase-js` `signUp` left in the product path.** Leaving both transports means the
  gate covers whichever one the reader's browser happens to take.
- **No new audit action the existing RPC cannot write.**
- **No Python 3.11+ syntax.** 3.10 is the production floor; `ruff` and `mypy` are pinned.
- **No corpus count** in any copy or document this change touches.

---

## 12. Gates

```bash
python -m pytest -m "not browser and not integration"
python -m pytest -m browser --browser chromium
ruff check . --fix && ruff format .
mypy web
npm run lint:fix && npm run format
```

**Estimated size:** roughly 200–250 lines of product code across two commits, ~25 tests, two
YAML catalogues, three documents. Commit A is the larger and riskier half — it moves a live
auth path — and is worth landing and observing before commit B.

---

## 13. Deliberately not decided here

1. **Do accounts created before the pause still confirm their email?** Yes, under this design
   — confirmation is a GoTrue link exchange that never touches `/auth/signup`. Flagged
   because it is the first question an operator will ask, and the answer belongs in
   `docs/OPERATIONS.md` rather than being inferred.
2. **Should `email_redirect_to` become mandatory?** Deferred in Step 2. Doing it properly
   makes `PUBLIC_BASE_URL` a hard dependency of signup — its own change with its own failure
   mode.
3. **Should `notifications_purge_retention_days` move into `NON_GENERATION_KEYS`?** It has
   the lost-update race described in §2, and once the family exists it is the obvious home.
   Out of scope — it would widen the diff across the notifications surface — but it should be
   a `TODO.md` entry, and this plan is why it is now visible.
4. **Should pausing broadcast a notification to other administrators?** The machinery exists
   (`notification_service`, the admin broadcast in `f9a9aa2`). Worth a `TODO.md` entry if a
   second operator ever exists.
5. **Should `login` move to Flask?** No, and the reason belongs in `docs/ARCHITECTURE.md`:
   nothing gates it, so moving it is cost without a property.
