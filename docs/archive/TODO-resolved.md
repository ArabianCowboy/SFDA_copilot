---
authority: historical
status: superseded
do_not_implement: true
archived: unknown
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

STATUS: HISTORICAL RECORD — resolved entries lifted out of `TODO.md` on 2026-08-23.
Nothing here is an instruction. For work that is actually open, see `TODO.md`.

# [HISTORICAL] TODO — resolved

Every entry below is closed. They are kept because this project writes an entry as
_what is wrong, how it was found, and what fixing it would disturb_ — and the second
and third halves stay useful long after the first stops being true. A fix whose
reasoning is thrown away gets rediscovered, or undone.

**Read these as history, not as rules.** Several record diagnoses that were later
found wrong, decisions that were later reversed, and mechanisms that no longer exist.
Where an entry says something the code no longer does, the code is right. The live
rules extracted from these entries live in `docs/ARCHITECTURE.md`, `docs/DATABASE.md`
and `DESIGN.md`.

Entries appear in the order they sat in `TODO.md`: resolved bugs first, then resolved
planned work. A `(original entry)` heading is the first draft of the entry above it,
kept where the later diagnosis superseded an earlier one and the difference was worth
recording.

---

## [HISTORICAL] Resolved bugs

### [HISTORICAL] ~~A new `security definer` function is born callable by anyone signed in~~ — FIXED 2026-08-28

**Closed the same day it was opened, by an adversarial review that refused the diagnosis.**
The entry below was written on the strength of a probe that was correctly run and wrongly
interpreted. `20260828100816` fixes it in one statement, with no event trigger and no
superuser: a per-schema `ALTER DEFAULT PRIVILEGES` is merged onto the hard-wired base and
cannot subtract from it, so `IN SCHEMA public … revoke all on functions from public` applied
cleanly and changed nothing. The **global** form, with no `IN SCHEMA`, replaces that base.
A function created afterwards comes out `{postgres=X, service_role=X}` — no PUBLIC, and
`has_function_privilege('anon', …, 'EXECUTE')` is false.

The correction is recorded at the foot of `20260828000737`, as collision #10 in
`docs/ARCHITECTURE.md`, and asserted by `supabase/tests/privileges.test.sql`. The lesson
worth keeping: **`IN SCHEMA` adds, global replaces** — and a probe that confirms a symptom
is not a probe that confirms a cause.

### A new `security definer` function is born callable by anyone signed in

**Where:** Schema `public`'s default privileges, and
`supabase/migrations/20260828000737_default_privileges_fail_closed_in_public.sql`, whose
post-apply correction records this.

**What is wrong.** That migration was meant to make point 3 of the RPC contract —
`revoke execute from anon, authenticated, public` — unnecessary, by flipping the schema's
default privileges from open to closed. It does that for **tables** and **sequences**. It
does not, and cannot, do it for **functions**: Postgres merges the built-in default, which
grants `EXECUTE` to `PUBLIC`, with whatever `ALTER DEFAULT PRIVILEGES` stores, so PUBLIC's
grant survives a `revoke all on functions from public` on the default ACL. Verified in a
rolled-back transaction: the stored default is `{postgres=X, service_role=X}` and a
function created immediately afterwards still comes out `{=X/postgres, postgres=X,
service_role=X}`, where `=X` is PUBLIC. Every role inherits PUBLIC's privileges, so
`has_function_privilege('anon', <new function>, 'EXECUTE')` is true.

**Who it reaches.** Nobody today — every existing function has an explicit revoke, and
`supabase/tests/function_acls.test.sql` asserts it. It reaches the next `security definer`
function whose migration forgets the line: that one is callable at `/rest/v1/rpc/<name>` by
any signed-in session on the day it is applied, and nothing in CI notices. This is exactly
how `audit_log_is_append_only` and `handle_profile_update` stayed `anon`-executable for
months (harmless, being trigger functions — `20260828004228` closed them anyway, because
the mechanism that missed them is the mechanism that would miss a consequential one).

**How it was found.** By probing after applying `20260828000737`, rather than by trusting
that the migration did what its own header claimed. The table half was verified at the
same time and does work.

**What fixing it would disturb.** The durable fix is an event trigger on
`ddl_command_end` that revokes `EXECUTE` from `PUBLIC` on every function created in
`public`. **Creating an event trigger requires superuser, and `postgres` is not superuser
on a hosted Supabase project** — the same class of limit that makes a trigram index on
`auth.users` impossible (`20260817161427`). So this is blocked on Supabase support, a
self-hosted stack, or accepting it. Until then the mitigation is the test file, which is
run by hand; making it automatic is the same "a database in CI" decision as the entry
below.

---

---

### [HISTORICAL] ~~A late profile read has no identity guard~~ — FIXED 2026-08-23

**Where:** `static/js/app.js:407` — the `.then` that calls `AppState.set('userProfile', profile)`
after `Services.getProfile()` resolves.

**What is wrong.** `hydrateTranscript` (`app.js:248`) and the auth-state handler
(`app.js:433-444`) both check that the identity the response belongs to still matches the
identity currently signed in before writing it to `AppState`. The profile read at `app.js:407`
does not. If reader A signs out and reader B signs in while A's `getProfile()` call is still in
flight — slow network, a fast account switch on a shared machine — B's screen can end up showing
A's name, organization, and specialization for as long as that stale write survives.

**Who it reaches.** Anyone on a shared or slow connection who switches accounts quickly. Not
theoretical: this is the exact race the two guards above already exist to close, on the one read
that was missed.

**Found while planning, not fixing.** Surfaced during the design pass for
[Refactor the profile page](../../TODO.md#refactor-the-profile-page) (§14·D·25 / T7 of
`2026-08-23_profile-refactor.md`), because that work adds two more UI elements
(the composer's default search scope and the first-run completion strip) that hang off this same
callback — so the guard has to be added there anyway. Recorded here because the bug predates that
work and is independent of it.

**The fix:** the same identity check `app.js:433-444` already does, applied to the `.then` at
`app.js:407` before the `AppState.set` call.

**Fixed 2026-08-23.** `checkId`/`dispatchedForUserId` are now captured once, before both
fire-and-forget calls (`loadProfileWithTimeout` and `fetchIdentityWithRetry`), and the profile
`.then` checks `identityCheckId` against it before writing `AppState.userProfile` — exactly the
guard `app.js:433-444` already had, extended to cover the read that was missed. Landed alongside
Step 4 of `2026-08-23_profile-refactor.md` (the completion strip and search-scope preference both
hang off this same callback, so the guard had to exist before either could be built on top of it).

---

### [HISTORICAL] ~~The FAQ rail gave no feedback on a busy click, and blew past its own chunking rule~~ — FIXED 2026-08-22

**Where:** `static/js/modules/handlers.js` (`handleFaqClick`, `handleSuggestedQuestionClick`),
`static/js/modules/ui.js` (`UI.Faq`), `static/js/modules/config.js`, `static/css/components.css`
(`.faq-more`), `web/i18n/{en,ar}.yaml` (`runtime.chat.busy`, `runtime.faq.showMore{One,Many}`).
Surfaced by an `/impeccable critique` dual-agent review of `_sidebar.html` run after the sidebar's
Explore tab was renamed to FAQ (commit `cf2a951`).

**What was wrong.** Two P1s in the same component. First, `handleFaqClick` checked
`AppState.isRequestInProgress()` and returned silently when an answer was still streaming — a dead
button with no explanation, while every sibling sidebar control (`openSession`, rename, delete) already
called `_refuseWhileStreaming()` for the identical guard; `handleSuggestedQuestionClick` had the same
silent gap. Second, the FAQ rail — the default landing panel for a first-time reader — rendered every
question in a category at once, and two of the four shipped categories (`regulatory`: 5,
`pharmacovigilance`: 6) exceeded the system's own ≤4-per-group chunking rule, so the component whose job
is to be the easiest on-ramp presented its heaviest cognitive load exactly when a new reader has the
least context to filter it.

**What fixed it.** The busy guard now shows a toast (`chat.busy`, new key, not a reuse of
`sessions.busy` — that string is specifically about switching conversations and would have been the
wrong sentence) instead of swallowing the click, on both handlers. The FAQ rail caps each category at 4
questions and appends a `.faq-more` button — visually the same quiet, bordered, full-width control
`.history-more` already uses for session pagination — that reveals the rest in place on click, no
accordion, no animation on the revealed items (the reader asked; it should be there the instant they
look). One shot per category: every shipped category is small enough that "show the rest" is the whole
interaction, no second layer of pagination. Localized one/many via `I18n.plural`, matching the
`cite.sourcesOne`/`sourcesMany` pattern already in the catalogue, including that pattern's known,
already-documented dual-form gap for Arabic's exactly-2 case. `ASSET_VERSION` bumped twice
(`warm37` → `warm39`) across the two edits.

**Verified live**, not only against the mechanical detector (clean on every touched file, both passes).
Rendered in the real Flask app (`FLASK_TESTING=true`) in English/LTR and Arabic/RTL: the chunking cap and
expand button work correctly in both, correct singular/plural copy ("Show 1 more" vs "Show 2 more",
matching Arabic forms). The busy-guard path doesn't reproduce reliably against the mock backend's
near-instant responses, so it was verified by patching `AppState.isRequestInProgress` to `true` in the
live page (via a `import()` of the exact same versioned module instance the page already loaded) and
clicking a live FAQ button — the toast rendered correctly in both languages and no request fired. 43
tests green across `test_frontend_architecture.py`, `test_admin_page.py`, `test_composer.py`,
`test_css_contract.py`.

---

### [HISTORICAL] ~~`chat_load_session` fetches sources with a correlated `jsonb_agg` subquery per window row~~ — FIXED 2026-08-22

**Where:** `supabase/migrations/20260820131914_chat_session_persistence.sql:533-600` defined
`chat_load_session`. Recorded as a deliberately deferred follow-up in the step-6 persistence record
below: "up to 200 index seeks and 200 JSONB builds per call." Also touched:
`web/services/chat_store.py` (`InMemoryChatBackend`), `web/tests/test_chat_persistence.py`.

**What was wrong.** The correlated subquery re-ran `jsonb_agg` once per row in the up-to-200-row
hydration window — an N+1 wearing SQL clothing. It didn't matter while hydration ran once per process
per conversation; step 6 made it user-triggered (every reload, language toggle, sign-in), turning it
into a per-visit cost.

**What fixed it, and the mistake caught along the way.** Two migrations, not one, both applied
2026-08-21 — the second corrects the first within the same pass, kept as an honest record rather than
squashed together. `20260821224353_chat_load_session_batch_sources` replaced the correlated subquery
with a `sources_by_message` CTE grouped by `message_id`, joined back with a plain `join window_rows w
on w.id = src.message_id`. Live `EXPLAIN (ANALYZE, BUFFERS)` on a seeded 200-message/300-source window
— required because `chat_load_session` is `security definer` and therefore never inlines, so wrapping
`EXPLAIN` around a call to the function itself would have shown nothing but an opaque `Function Scan`
— showed the planner did **not** hash/merge-join that CTE: it ran a Nested Loop Left Join
(`Inner Unique: true`) that re-executed the `GroupAggregate` over the _entire_ window once per outer row
(`loops=200`). `Rows Removed by Join Filter: 14950` — not the naive `200*100-100 = 19900` a uniform
full-rescan-every-time model predicts, because `Inner Unique: true` lets the 100 matching (assistant-role)
outer rows stop early once they hit their own group, while the 100 non-matching (user-role) rows still
scan all ~100 groups before concluding no match; that mix reconciles to ~14900, matching the observed
14950 within rounding. Still a per-row re-execution of the whole aggregate, just with early exit on half
the rows rather than a flat 200x cost — worth stating precisely, since the first version of this record
implied a simpler mechanism than what Postgres actually did (caught in review). 530ms — worse than the
7ms the original N+1 cost on the same seeded data. `20260821224534_chat_load_session_batch_sources_fix_join_form`,
applied minutes later, replaced the join with `where src.message_id = any(array(select id from
window_rows))`, which the planner instead ran as a single `InitPlan` evaluation, one bitmap index scan
against the whole id array, one `GroupAggregate` pass, and a merge join — 4.7ms, 19 buffers against the
original 712 (and the intermediate regression's 712 too, at 75x the runtime).

A companion gap surfaced by review: `InMemoryChatBackend.load_session` (`web/services/chat_store.py`)
preserved sources in _write_ order, while the real RPC has always guaranteed `source_index`-ascending
order on _read_. Every existing test inserted sources already sorted, so the double gave the right
answer for the wrong reason. Fixed to sort on read (`load_session` now returns each message with
`sources` sorted by `source_index`), with a new regression test,
`test_sources_come_back_ordered_by_source_index_regardless_of_insert_order`, that inserts out of order
specifically to catch what the old tests could not.

Debated before shipping with an adversarial review (OpenCode/`gpt-5.6-terra`, read-only `plan` agent, no
repo edits) that pushed back on the original plan's `EXPLAIN`-on-function-call verification approach and
its pre-commitment to the `= ANY(...)` form over a plain join without live evidence — both concerns the
join-form regression above then confirmed were real, not hypothetical caution.

**Verified live**, not only against the in-memory double: functional round-trip on the corrected function
confirmed the full 200-row window, ownership isolation (wrong owner or wrong session → 0 rows), limit
clamping (`-5` → 1 row, `9999` → 200 rows), every user row's `sources = []`, and every seeded assistant
row's 3 sources ordered ascending by `source_index`. `get_advisors` (security, performance) showed no new
findings. 553 tests green in `web/tests/` (excluding the browser/integration markers).

---

### [HISTORICAL] ~~The embedding model loaded twice at startup, and huggingface_hub's own HTTP logging was never quieted~~ — FIXED 2026-08-21

**Where:** `web/services/search_engine.py`, `web/services/search_index.py`,
`web/utils/local_embedding_client.py`, `web/api/app.py`. Found from a user
reading their own startup log and describing a wall of `HEAD ... 404 Not
Found` lines as "400 errors."

**What was wrong.** Two independent things compounded into one confusing
wall of text. First, `SearchEngine.__init__` built its own
`SentenceTransformer`-backed embedding client, then constructed `SearchIndex`
without passing it — so `SearchIndex._validate_manifest()` built a second,
independent one just to read `embedding_dimension`, doubling every
HuggingFace Hub HEAD request the library makes on load. `SearchIndex.__init__`
had accepted an `embedding_client` parameter for exactly this reason since it
was written, with a docstring saying so; nothing had ever passed one. Second,
nothing set a log level for `httpx`, `httpcore`, or `huggingface_hub`, so
every one of those HEAD requests — including the benign 404s those libraries
always send probing for optional model files a sentence-transformers
checkpoint doesn't have — printed at INFO by inheriting the root logger.

**What fixed it.** `search_engine.py:212` now passes
`embedding_client=self._embedding_client` into `SearchIndex(...)`. `app.py`
sets `httpx`/`httpcore`/`huggingface_hub` to `WARNING`.
`local_embedding_client.py` tries `SentenceTransformer(model_name,
local_files_only=True)` first and only falls back to a normal network load on
`LocalEntryNotFoundError` (a corrupted cache or other failure still raises,
unchanged). One accepted, narrow behavior change: a transient network failure
specifically on the now-removed _redundant_ second construction can no longer
crash startup the way `ManifestValidationError` used to guarantee — a genuine
manifest/model mismatch still does, since that check still runs against the
injected client's real values. 12 new tests
(`web/tests/test_search_index_injection.py`) cover the injection path, the
mismatch-still-fires case, and all three `local_embedding_client.py` loading
branches.

### [HISTORICAL] ~~A transient Supabase outage signed readers out~~ — FIXED 2026-08-15

**Where:** `web/api/app.py`, `_authenticate_request`. Found in production on
2026-08-15 from a single log line:

```
ERROR:root:Authentication error at endpoint admin.audit: The read operation timed out
  ... httpx.ReadTimeout
"GET /admin/api/audit?...&target_id=..." 401
```

**What was wrong.** One bare `except Exception` answered every failure with
`_handle_unauthorized`. That is not merely the wrong status — it calls
`clear_auth_session()`, so a read timeout to GoTrue told a signed-in
administrator they were signed out _and_ destroyed their server-side session:
the stored access token, the email, and the admin render hint. The credential in
their hands was valid throughout. The same branch also caught a missing
environment variable, a provider response in an unexpected shape, a GoTrue
rate limit, and any bug in identity resolution, and blamed the reader's
credential for all of them.

**Why it survived.** The rule was already written down one layer lower —
`web/api/admin.py` answers 503 when the _profile_ store cannot be read, because
"an outage is not a refusal" — and
`test_an_identity_outage_is_a_503_not_a_refusal` appears to guard it. It does
not: it monkeypatches `_authenticate_request` itself, so the `except` block that
made the mistake never ran. A test that mocks the function under test is how a
bug hides behind green.

**What fixed it.** A three-way split in `_authenticate_request`: **503**
`identity_unavailable` for an outage (`httpx.TransportError`,
`AuthRetryableError`, a 5xx, or a 429), **500** `identity_check_failed` for our
own faults, and **401** only for a genuine refusal — which now additionally
requires the exception to carry an integer status, because 401 is the strongest
claim the code can make and it should rest on evidence. `AuthUnknownError` is
excluded from refusals: GoTrue mints it when it cannot parse the provider's
error body at all, which is not a verdict on anyone's credential. The auth call
also gained an explicit 5s ceiling (`web/utils/supabase_client.py`) — not a new
policy, just httpx's existing default made a decision rather than a library
detail. Client side, `static/js/admin/services.js` retries a 503 once **for GET
only**: a 401 provably precedes the route body, a 503 does not, and re-sending a
mutation on one could put a second recovery link in somebody's inbox.

Covered by `web/tests/test_auth_failure_modes.py`, which was verified to fail
against the old code rather than merely to pass against the new.

---

### [HISTORICAL] ~~There is no password reset~~ — FIXED 2026-08-14

**Resolved.** Reader-facing recovery ships: a _forgot password_ affordance in the
login pane, `POST /auth/recover`, and a third view in the shell that receives the
callback and calls `auth.updateUser({ password })`. Proven end to end against the
live project — `midoxp@yahoo.com` went from never-signed-in and unconfirmed to
confirmed and signed in through the real email.

Three things the original entry did not know, kept because they cost a day to
learn and are invisible in the finished code:

- **Recovery mail is sent server-side, not from the browser.** A browser-issued
  `resetPasswordForEmail` under `flowType: 'pkce'` stores its code verifier in
  _that_ browser's `localStorage`, so opening the mail on a phone can never
  complete the exchange. A server-generated link returns tokens in the fragment
  instead, which any device can consume.
- **`flowType: 'pkce'` silently drops that fragment.** Measured against
  gotrue-js 2.62.2: no session, no `PASSWORD_RECOVERY`, and no error, because
  `_initialize` swallows the "Not a valid PKCE flow url" it raises. The client is
  built with `'implicit'` when the recovery marker is present and `'pkce'`
  otherwise.
- **The `?recovery=1` marker is load-bearing twice.** Supabase emits `SIGNED_IN`
  _before_ `PASSWORD_RECOVERY` (supabase/auth-js#349), so the event cannot be
  trusted to open the view; and the marker has to be readable before the client is
  constructed, because it selects the flow type.

**Update 2026-08-16 — the admin half has shipped too.** `POST
/admin/api/users/<user_id>/reset-password` (`web/api/admin.py:265-340`) sends
the same recovery link from the account detail view via `#account-send-reset`
(`static/js/admin/ui.js:956-959`, wired through
`services.sendPasswordReset(userId)` in
`static/js/admin/handlers.js:287-312` and `static/js/admin/services.js:132-133`).
Tested in `web/tests/test_admin_users.py:461-530` and
`web/tests/test_admin_browser.py:658-705`. See _Account detail view_ under
Planned work for what else that page does and does not do yet.

---

### [HISTORICAL] (original entry, kept for the cost it records) There is no password reset, so a forgotten password is an unrecoverable account

**Where:** `static/js/modules/services.js` exposes `signInWithPassword` (line 222) and `signUp` (line 229) and nothing else — no `resetPasswordForEmail`, no
`updateUser`, no handling of Supabase's `PASSWORD_RECOVERY` event. The auth modal
(`web/templates/index.html:128-224`) has a Login tab and a Signup tab and no
third affordance. `web/api/auth.py` has `/signup` and `/login` and no recovery
route.

**What is wrong.** A reader who forgets their password has no way back into their
account. Not a slow way — none. The surface offers no link, the client has no
call, and the server has no route.

**It is worse in combination, which is why it is filed as one bug.** Three
things compound:

1. There is no self-service reset.
2. There is no operator-side recovery either — the console can change a role and
   revoke chat access, and cannot touch an email address or a credential.
3. Email confirmation is currently off, so an address was never proven to belong
   to its account in the first place.

Together those mean a locked-out reader is locked out permanently and nobody in
the system can help them. That is the actual severity, and none of the three
parts shows it alone.

**Who it reaches.** Anyone who forgets a password, changes employer, or typos
their address at signup. On a professional tool where accounts are months old
between sign-ins, that is not an edge case.

**What fixing it costs.** `supabase.auth.resetPasswordForEmail(email, {
redirectTo })` sends the mail; the return leg is the work. Supabase redirects
back with a recovery token, the client sees a `PASSWORD_RECOVERY` auth event, and
something has to render a "choose a new password" form and call
`auth.updateUser({ password })`. This app is a one-page two-view shell —
`AuthView` toggles `d-none` between landing and chat — so that form is a third
view in the existing shell rather than a route, which is the consistent choice
but is still a new state the view logic does not have.

Three things are easy to miss. The `redirectTo` URL must be added to Supabase's
allow-list or the link silently fails. The recovery email template is a Supabase
setting and ships in English, so a bilingual product needs it authored in both
languages — it is one of the few reader-facing strings that does not live in
`web/i18n/`. And the whole flow depends on email actually being delivered, which
[../OPERATIONS.md](../OPERATIONS.md) records as configured
but not yet proven.

**Do this before the admin credential work below**, which is partly made
unnecessary by it.

---

### [HISTORICAL] ~~The console cannot change an email address, and deliberately cannot set a password~~ — FIXED 2026-08-17

**Where:** `admin_set_user_flags` reaches `role` and `is_disabled` only. Both
`auth.users.email` and the credential live in Supabase Auth, not in
`public.profiles`, so neither is reachable from the RPC the console uses.

**Why an email change is wanted.** People change employer and typo their address
at signup. With confirmation off, a typo'd address is currently permanent and
invisible — the account works, and the mail it should receive goes to a stranger.

**Why setting a password is _not_ wanted, and this is a design position rather
than an omission.** An operator who can set a reader's password can sign in as
that reader, and nothing downstream can tell the two apart — the audit log would
attribute to the reader actions the operator took. The console's whole thesis is
that privileged acts are attributable, and a shared credential is the one change
that quietly breaks it for every other record in the table. The support outcome
people actually want from "set their password" is "get them back into their
account", and a reset link delivers that without anyone learning a secret.

So the shape to build is **send a password reset** (`auth.admin.generateLink`
with `type: 'recovery'`, or triggering the same reader-facing flow), not **set a
password**.

**Update 2026-08-16 — the send-reset half is built; email change is not.**
`POST /admin/api/users/<user_id>/reset-password` (`web/api/admin.py:265-340`)
does exactly what this entry recommended, and structurally enforces the
"deliberately cannot set a password" position: it rejects any request body at
all, returning 422 `unknown_field` if a payload such as `{"password": ...}`
is submitted (`web/api/admin.py:299-303`). No route or RPC anywhere in the
repository reaches `auth.users.email` (confirmed by a repo-wide search) — an
email change is still genuinely unbuilt.

**Update 2026-08-17 — email change is now built too, with one deviation from
this entry's own recommendation, made deliberately and disclosed rather than
silently substituted.** `POST /admin/api/users/<user_id>/change-email`
(`web/api/admin.py`) ships. This entry originally called for confirmation
_to the new address_ rather than `email_confirm: true` — but building that
would mean a new pending-email column, a confirmation route, and its own
email template, real scope beyond one action, and out of reach for what the
Admin API itself supports in a single call anyway (its email-change path has
no defer-until-confirmed flow at all; that only exists for a reader changing
their own email through an authenticated session). Rather than build the
larger thing or quietly ship `email_confirm: true` (which requires nothing
and would look, on the surface, like the address was verified), the change
takes effect **immediately** with `email_confirm: false`, disclosed plainly
in the confirm dialog before an operator commits. Live-verified against the
real project before shipping (not assumed from documentation): this does
**not** lock the account out — `email_confirmed_at` is untouched, so a
previously-confirmed account keeps signing in — but it does leave the
identity's `email_verified` flag false for the new address, and the console
now reads that flag directly (`admin_get_user`'s new
`email_identity_verified` column) rather than continuing to show the old,
now-stale confirmation timestamp as if it certified the current address.

**The account-takeover risk this entry named up front turned out to be the
central design question**, surfaced sharply by an adversarial review before
shipping: chained with the _existing_ reset-password button, an unconfirmed
email change is a complete impersonation primitive — change the victim's
email, click reset, they never see it coming (this is exactly how Twitter's
2020 breach worked). The mitigation built: `change-email`, uniquely among
the three auth-admin actions on this page, refuses to target the operator's
own account. `revoke-sessions` and the existing `reset-password` still do
not, on the same reasoning `set_user_flags`'s self-change guard already
established — the two also worth turning on but not yet done: enabling
Supabase's `GOTRUE_MAILER_NOTIFICATIONS_EMAIL_CHANGED_ENABLED` project
setting (notifies the _old_ address as tamper-evidence — external config,
not app code, same category as leaked-password-protection below) and
tightening the shared `60/minute` admin rate limit specifically for these
two destructive routes, both done (limiter applied per-route in
`web/api/app.py`), but the mailer setting itself is still an open item for
whoever holds the Supabase dashboard.

**What it would disturb — confirmed, not just anticipated.** Both reach
`auth.admin.*`, so both use the intent-then-outcome shape, now extended with
a third outcome (`outcome_unknown`) for transport failures whose true result
is genuinely unknown rather than provably failed. The old address is kept in
the audit row (`before={"email": old}`), and — a real gap an adversarial
review caught before shipping — the per-account audit table did not
previously render `before`/`after` at all, so capturing the old address
would have gone nowhere any operator could see it; it now does (mirroring
what the global Activity tab already had).

**Where it lives:** the account detail view, exactly as predicted — see
_Account detail view_ below.

---

### [HISTORICAL] ~~The signup rate-limit message reaches the reader as raw English~~ — FIXED 2026-08-14

**Resolved.** `runtime.auth.tooSoon` and `runtime.auth.emailUnavailable` exist in
both catalogues and are mapped in `ErrorHandler.formatAuthError`
(`static/js/modules/dom.js`), which is the only path signup errors take. Recovery
reaches the same two strings by status code from our own endpoint rather than by
substring, because it does not go through Supabase directly.

Worth recording: this was _claimed_ fixed when the keys were added, and was not —
the keys sat in both languages with no mapping, exactly the dead-string failure
this file already records for `runtime.profile.*`. It was caught by an audit
asking whether every added key was actually reached. There is now a test that
fails if any `runtime.auth.recovery.*` key is drawn by nothing.

---

### [HISTORICAL] (original entry) The signup rate-limit message reaches the reader as raw English

**Where:** `static/js/modules/handlers.js` surfaces the Supabase error text
verbatim; `runtime.auth.*` has no key for it in either catalogue.

**What is wrong.** When Supabase refuses a signup for exceeding its email
allowance, the reader sees "email rate limit exceeded" — English on a bilingual
surface, and phrased as though _they_ exceeded a limit rather than the service
being busy. GoTrue rolls the account back when a send fails, so they get no
account and no email, and the address stays free to retry — none of which the
message says.

**Who it reaches.** Any signup that trips the ceiling. That is now much rarer
than it was, which is precisely why it is worth fixing rather than forgetting:
it will next be seen by a real person, not by someone testing.

**What changed underneath it.** The 2/hour cap that made this common was fixed
on 2026-08-14 by moving to custom SMTP through Resend — see
[../OPERATIONS.md](../OPERATIONS.md). Note the ceiling was
**raised to 30/hour, not removed**: GoTrue enforces its own limiter independently
of the provider's allowance. So this path is still reachable.

**The fix.** A key in both `web/i18n/en.yaml` and `web/i18n/ar.yaml` under
`runtime.auth.*`, worded as "we could not send the confirmation email just now —
please try again shortly", plus mapping Supabase's message to it in `handlers.js`.
Small, and blocked on nothing.

---

### [HISTORICAL] ~~Email confirmation is disabled~~ — RESOLVED 2026-08-14 (outside this repo)

**Turned back on at 12:05:17Z**, confirmed from `auth.users`: `mohifouda@gmail.com`
has `confirmation_sent_at` set, unlike the auto-confirmed `midoxp@live.com` whose
value is null. The open question the old entry left — _is a confirmed address
required to chat?_ — is answered and needs no code: GoTrue refuses to issue a
session for an unconfirmed address, so `auth_required` never sees a token to
accept. Enforcement sits at the session boundary, which is the strongest place
available.

One consequence this created and password recovery then cleared:
`midoxp@yahoo.com` had `email_confirmed_at = null` and could no longer sign in at
all. Completing a recovery confirms the address as a side effect, which is how
that account was settled.

---

### [HISTORICAL] (original entry) Email confirmation is disabled, so any address can register

**Where:** The Supabase project's Auth settings, not this repo. Confirmed
2026-08-14 from `auth.users`: the most recent account has
`confirmation_sent_at = null` and `email_confirmed_at` set 25 ms after
`created_at` — auto-confirmed, no email attempted.

**What is wrong.** Nothing verifies that a registrant controls the address they
signed up with. Someone can register as anyone, and the account is immediately
usable. It also means password reset — the one flow that assumes the address is
real — is the only thing standing between a typo'd address and a lost account.

**Who it reaches.** Every registration. Of the three existing accounts, one has
never been confirmed at all (`midoxp@yahoo.com`, since 2025-11-16).

**Why it is like this.** It appears to have been turned off to work around the
2 emails/hour cap, which was a reasonable thing to do at the time and is no
longer necessary now that custom SMTP is configured.

**What it would disturb.** Turning confirmation back on changes the signup flow
the browser tests exercise, and re-opens the question the previous state answered
implicitly: _is a confirmed address required to chat?_ Supabase can enforce it,
or `auth_required` can, or nobody can — but it should be decided rather than
inherited. Note that re-enabling it is also the honest way to prove the new SMTP
path actually delivers, which has not yet been demonstrated.

---

### [HISTORICAL] ~~An account outside the newest 50 cannot be found or administered~~ — FIXED 2026-08-17

**Resolved.** The search half (`#people-search`, debounced, passing `q`
through to the RPC) landed 2026-08-15. The pager half — the more dangerous
part, since a truncated result set looks identical to a complete one — landed
2026-08-17: `handlers.js` now sends `limit`/`offset` and tracks them in a
proper state machine (sequence-token + `AbortController` guarded), `ui.js`
renders a real Next/Previous pager with an explicit "Showing N–M of T" range
instead of the old bare `N / M` line, and the range/pager gain full EN/AR
catalogue coverage and RTL mirroring. Two correctness gaps closed alongside
it: `admin_list_users` now tie-breaks `ORDER BY created_at DESC, id DESC`
(same-millisecond signups no longer produce non-deterministic page
boundaries), and `p_search` is now escaped so literal `%`/`_`/`\` in a search
term can't act as SQL wildcards or crash the RPC. A planned `pg_trgm` index on
`auth.users.email` was attempted and deliberately deferred — blocked by a
genuine Supabase permission wall (`postgres` is not a member of
`supabase_auth_admin`, which owns `auth.users` on this hosted project), not a
code issue, and safe to defer at today's row count. Full design record,
including that deferral and its follow-up options, in
[2026-08-17_pagination.md](2026-08-17_pagination.md).

---

### [HISTORICAL] (original entry, diagnosis superseded above) An account outside the newest 50 cannot be found or administered

**Where:** `static/js/admin/services.js` and `handlers.js` call
`/admin/api/users` with no query string, so it serves its default page. Found
2026-08-14 by an independent review of the account-management surface.

**What is wrong.** The console's People tab renders exactly one page of the
newest 50 accounts and offers neither a search box nor a next-page control. The
server does not have this limitation — `GET /admin/api/users` already accepts
`q`, `limit` (max 200) and `offset`, and the `admin_list_users` RPC beneath it
takes `p_search`, `p_limit` and `p_offset`. The capability is built and unreached.

**Who it reaches.** Nobody today: there are three accounts. It becomes a real
problem at the 51st, and it fails in the least helpful way — an operator looking
for a specific person finds nothing and has no way to tell "this account does not
exist" from "this account is not on this page".

**What fixing it costs.** A search input, a debounce, and either paging controls
or an infinite scroll, all of which need EN/AR keys in both catalogues and RTL
mirroring. The search itself is worth thinking about once: matching on email
substring is what an operator wants and is also the query that scans, so it wants
an index before it meets a real user table. Deliberately not fixed in the commit
that found it — it is a feature-sized piece of frontend, not a repair.

---

### [HISTORICAL] ~~An account with no profile row can chat but cannot be administered~~ — FIXED 2026-08-16

**Resolved.** The instance (`midoxp@yahoo.com`) was backfilled and all
accounts now have profiles, but the class of bug was the more important
half — and it is now fixed too. `admin_list_users`
(`20260814100500_user_management.sql:35-47`) still left-joins
`auth.users u left join public.profiles p` and paints healthy defaults over a
missing profile with `coalesce(p.role,'user')` / `coalesce(p.tier,'free')` /
`coalesce(p.is_disabled,false)`, so the underlying data shape is unchanged.
What changed is that the account detail view now acts on the gap instead of
hiding it: `has_profile` shipped in
`supabase/migrations/20260814175551_account_detail.sql:24,48`
(`(p.id is not null) as has_profile`), and the admin UI renders an explicit
`#account-broken` warning (`admin.account.brokenHeading` /
`admin.account.brokenBody`) and gates the profile-edit and role/disable
controls behind it (`static/js/admin/ui.js:907-917,939,961`) whenever a future
account arrives in this state. A broken account is now a visible problem, not
an absence.

---

### [HISTORICAL] (original entry, diagnosis superseded above) An account with no profile row can chat but cannot be administered

**Where:** `admin_list_users` reads from `public.profiles`; `auth_required`
treats an unresolved profile as a non-admin reader rather than as a refusal.

**What is wrong.** If an `auth.users` row exists with no matching
`public.profiles` row, the account works — the reader signs in and chats — but it
does not appear in the console's People list, and any attempt to act on it by id
raises `AD003 / no_such_account`. It is a live account that no operator can
disable.

**Who it reaches.** One account today: `midoxp@yahoo.com` (registered
2025-11-16, before the signup trigger was repaired). The repaired trigger makes
new occurrences unlikely, which is exactly why this one is easy to forget.

**What fixing it costs.** Two candidate fixes with different meanings. Backfill
the missing profile — cheap, and makes this account administrable — or have the
console list from `auth.users` left-joined to `profiles` so profile-less accounts
are _visible_ as a broken state rather than invisible. The second is the more
honest surface and the larger change. Backfilling first is not wrong, but doing
only that leaves the class of bug intact: the console would still silently omit
any future account in this state.

---

### [HISTORICAL] ~~A combined or no-op account change is recorded under a misleading name~~ — FIXED 2026-08-16

**Resolved.** `admin_set_user_flags` (migration
`20260816121335_diff_based_admin_user_flags_audit.sql`) now derives its audit
rows from the diff between before-state and after-state rather than from
whichever fields the request carried, exactly as `admin_update_profile`
already did and as the entry below itself recommended once the sibling RPC
set the precedent. A combined `{role, is_disabled}` change writes **two**
audit rows — `user.role_change` and `user.disable`/`user.enable` — one per
field, deliberately not the same shape as `admin_update_profile`'s single
row: the per-account audit view (`static/js/admin/ui.js`) renders only an
action name and a note, no before/after diff, so collapsing two simultaneous
changes under one label would silently drop one of them on exactly the page
built to show "what happened to this account." A field sent back at the
value it already holds writes no row for that field, and a fully no-op call
writes nothing at all — matching the reference. A caller-supplied `reason`
is preserved on a role-only change too — it is a general note on the call,
not a field reserved for disabling, and the first draft of this fix dropped
it there before review caught it.

Investigated and implemented by two independently delegated implementers
(Antigravity/`gemini-3.7-flash-high` and OpenCode/`gpt-5.6-luna`) working from
the same brief, whose designs disagreed on one-row-vs-two; adjudicated by
reading the actual per-account UI rather than guessing. Both behaviours are
covered live: `test_a_single_call_changing_both_role_and_standing_records_both`
asserts the two-row split (`web/tests/test_admin_users.py:233`), and
`test_a_no_op_user_flags_edit_records_nothing` /
`test_a_partial_no_op_records_only_the_field_that_moved`
(`web/tests/test_admin_users.py:261,277`) assert the no-op case. The in-memory
test double in `web/services/admin_store.py:600-625` mirrors the SQL shape
rather than reimplementing it separately, so the two cannot drift. Applied
live and verified against the deployed function body on the project
(`yjjuudnsnjzhyqllsqrd`), not just committed.

---

### [HISTORICAL] (original entry, kept for the cost it records) A combined or no-op account change is recorded under a misleading name

**Where:** the action name is derived in `web/services/admin_store.py` from
whichever field is present, and written by the `admin_set_user_flags` RPC.

**What is wrong.** A `PATCH` carrying both `role` and `is_disabled` records one
action name, not two, so the audit log describes half of what happened. A patch
that sets a field to the value it already holds records a change that did not
occur — `{role: "user", is_disabled: false}` on an already-enabled reader logs as
`user.enable`.

**Who it reaches.** Only whoever reads the log later, which is the entire reason
the log exists. The mutation itself is correct; the record of it is not.

**What fixing it costs.** Small, and it interacts with the `before`/`after`
JSONB the RPC already captures — the honest fix is to derive the name from the
diff rather than from the request, and to record nothing when the diff is empty.
Worth doing before the log has enough entries for anyone to trust it.

**Update 2026-08-15 — the pattern now exists, in the other RPC.**
`admin_update_profile` (migration `20260814200342`) was written this way from
the start: it derives the action from the diff, and returns early without
writing an audit row at all when `before` and `after` match apart from
`updated_at`. Verified live — one real change wrote one row, a no-op wrote none.
So this entry is now a _port_, not a design problem: `admin_set_user_flags` is
the one still deriving its name from whichever field the request happened to
carry. Copy the shape, do not reinvent it.

---

### [HISTORICAL] ~~A disabled reader is not told until they ask a question~~ — FIXED 2026-08-17

**Resolved.** `/api/identity` already distinguished the two states server-side
— 401 for signed-out, 403 with `{"error": "account_disabled"}` for
signed-in-but-disabled — so no server change was needed. `Services.getIdentity`
(`static/js/modules/services.js`) now keeps returning `null` only for the true
"nobody" case (401); a 403 throws with `.status = 403` and `.code =
'account_disabled'`, the same error-tagging shape chat requests already use.
`app.js`'s identity-check `.catch` branch renders an inline banner
(`UI.showAccountDisabledNotice`, `static/js/modules/ui.js`) reusing the
existing `auth.accountDisabled` string that was previously shown only after a
disabled reader submitted a question — that late path
(`handlers.js:261-265`) is unchanged and stays as a fallback. The composer is
deliberately left usable rather than disabled, the smaller of the two options
this entry weighed, chosen to avoid new bilingual CSS for a notice-not-lockout
state. Covered by `test_a_disabled_reader_sees_the_notice_immediately_on_sign_in`
and `test_a_signed_out_identity_check_resolves_null_not_an_error`
(`web/tests/test_frontend.py`).

---

### [HISTORICAL] (original entry, kept for the cost it records) A disabled reader is not told until they ask a question

**Where:** `Services.getIdentity` (`static/js/modules/services.js:462`) returns
`null` for both 401 and 403, and `static/js/app.js:296` uses it only to decide
whether to reveal the admin link.

**What is wrong.** Disabling chat access is enforced server-side on every
request, which is correct. But the reader signs in normally, the chat shell
renders, the composer accepts their question — and only then does the 403 arrive
and `handlers.js:244` render the notice. They discover the state by hitting it.

The cause is a deliberate simplification with an unintended consequence:
`getIdentity` flattens "not allowed" and "nobody" to the same `null` because the
one caller's safe default is the same for both. Adding a second caller with a
different question makes the two indistinguishable when they need to be told apart.

**What fixing it costs.** `getIdentity` would have to distinguish 403 from 401 —
a contract change to a function whose docstring currently promises it does not —
and the composer would need a disabled state, which is a bilingual surface with
its own CSS. Not urgent: the current behaviour is correct, merely late and
graceless.

---

### [HISTORICAL] ~~The admin console link disappears intermittently for a genuine administrator~~ — FIXED 2026-08-16

**Resolved.** `onAuthStateChange`'s callback in `static/js/app.js` fires
**twice** on a page load with an existing session — once for `INITIAL_SESSION`,
once for `SIGNED_IN` — confirmed against the pinned
`@supabase/supabase-js@2.39.7` source rather than assumed: `_recoverAndRefresh`
queues a `SIGNED_IN` notification during `initialize()` while `onAuthStateChange`
separately emits `INITIAL_SESSION` straight to each subscriber once
`initializePromise` settles. Both firings independently dispatched
`Services.getIdentity().then(identity => AuthView.renderAdminAffordance(...))`
with no ordering guard, so whichever of the two _resolved_ last decided the
final visible state, regardless of which was dispatched first. `getIdentity`
also had zero retry, so a single transient hiccup — the same class of GoTrue
outage the entry above this one already proved happens on this project —
permanently hid the link for that page load with nothing bringing it back
short of a reload. Both weaknesses had to be present for the symptom to be
this rare and this unpredictable; either alone would have been more consistent.

**What fixed it.** `Services.getIdentity()` (`static/js/modules/services.js`)
now dedupes concurrent calls into one shared promise, assigned synchronously
before any `await` so two callers in the same tick can never both see it
unset — closing the race at its source rather than picking a winner after the
fact. It also enforces a 5s request timeout (a hung request previously
defeated retry outright) and attaches `.status` to what it throws. A new
`identityCheckId` generation counter (`auth-view.js` / `state.js`), bumped
whenever a view stops being the signed-in reader's — sign-out, entering
recovery — lets `app.js` discard a check's result if it resolves after the
view that asked for it is gone. `app.js` also no longer blocks the identity
check behind FAQ loading, and retries only network failures and 5xx/503, never
a 401/403 (a real answer) or another 4xx (repeating it would only repeat the
answer).

**A second, more serious bug found in review, on the same code.** The dedup
above is not scoped to _who_ asked — on a shared machine, if reader A signs
out while their check is still in flight and reader B signs in before it
resolves, B's call would join A's promise and could be shown A's admin
standing. `/admin/api/*` stays gated server-side regardless — this is an
affordance leak, not an authorization bypass — but it is exactly the class of
bug this fix exists to close, just for a second person instead of one. Fixed
by checking the resolved identity's `user_id` against the reader the check
was actually dispatched for; a mismatch is discarded, which fails to
"unresolved, stay hidden" rather than showing anyone the wrong account's
standing — the same posture this app already takes for every other
unresolved case.

Investigated independently by two implementers reasoning from the same
symptom (Antigravity/`gemini-3.7-flash-high` for the initial root cause and a
risk-review pass on the proposed fix; Codex/`gpt-5.6-luna` for a read-only
adversarial review of the finished diff), which is what surfaced the
cross-user leak above along with the missing timeout and an over-broad retry
scope — all fixed here rather than left for later. Covered by a new browser
test in `web/tests/test_frontend.py` proving the specific ordering this
guards against, using Playwright's deferred `route.fulfill()` rather than a
thread blocked inside the route handler — the first draft used the latter and
it stalled Playwright's own sync dispatcher badly enough to look like a
different bug entirely before the mechanism was understood. Verified to fail
against the pre-fix code and pass against the fix; full suite otherwise
unaffected (the one browser-suite failure seen while testing this was the
already-documented `test_source_panel.py` flake below, confirmed unrelated by
reproducing it identically on the pre-fix code).

**What this was not.** A local `.env` missing `SUPABASE_SECRET_KEY` /
`SUPABASE_SERVICE_ROLE_KEY` separately made a local dev instance unable to
resolve _any_ reader as an administrator — a deploy-config gap, unrelated to
this bug, and not fixed here. See "The `.env` file carries keys nothing
reads" below.

---

### [HISTORICAL] ~~`SettingsService.snapshot()` can publish a stale value over a fresher one~~ — FIXED 2026-08-26

**Where:** `web/services/settings_service.py`, `snapshot()` and `_publish()`. `snapshot()`
reads the store via `self._overrides()` (I/O) with no lock held, then unconditionally
writes the result into `self._cached` / `self._loaded_at` under `self._lock`, with no check
for whether a write landed in between.

**What is wrong.** Two threads (production runs `--threads 8`) can interleave: thread A's
`snapshot()` starts its unlocked read while the settings are still old, thread B calls
`update()` (a genuine settings save), which writes the new value and calls `_publish()`
to install it — then thread A's read finishes, using the value it read before B's write, and
unconditionally overwrites `_cached`/`_loaded_at` with that stale copy. For up to `ttl_seconds`
(60s default), every reader sees the value **before** the save that just succeeded, even
though the store and the save's own HTTP response both say the new one is live.

**Who it reaches.** Any concurrent `GET /admin/api/settings` (or an internal `snapshot()`
call from `apply_generation_settings`) racing a `PUT` from another operator, or from the
same operator opening a second tab. Narrow window, plausible on a console two people share.

**How it was found.** An adversarial security review (agy, `gemini-3.7-flash-high`, its
default model, 2026-08-25)
of the registrations-pause feature (`docs/registrations-pause-plan.md`) found the identical
shape in the NEW code this feature added — `SettingsService.signup_enabled()`'s operational
cache had the same unlocked-read-then-unconditional-write race, fixed in that commit with a
"did a newer value get published while I was reading" check before the write-back
(`settings_service.py`, `signup_enabled()`'s `baseline_loaded_at` guard). Checking whether
`snapshot()` — the pattern `signup_enabled()` was modelled on — had the same problem found
that it does, and predates this feature.

**What fixing it would disturb.** The fix is the same shape already proven for
`signup_enabled()`: capture `self._loaded_at` under the lock before starting the unlocked
read, and on write-back check whether it advanced past that baseline before overwriting —
if it did, a concurrent writer already published something newer, so defer to it instead.
Needs a regression test in the shape of `test_a_slow_read_in_flight_does_not_clobber_a_
concurrent_publish` (`web/tests/test_registrations_pause.py`), which proves the equivalent
fix for the operational cache without relying on real thread scheduling — that test's
own docstring explains the deterministic-interleaving technique. Touches the generation
settings path every chat request depends on for its model/temperature/token ceiling, so
it deserves its own commit and its own careful review rather than folding into an unrelated
change.

**Confirmed independently 2026-08-26** by `/code-review` (a forked session with real
repository access, reviewing the built registrations-pause feature), which found the same
gap without being told about it. That pass also surfaced two smaller, related items, filed
here rather than each earning a separate entry — both lifted into their own open `TODO.md`
entries rather than archived here, since neither is fixed by this commit: **`Services.signup()`
builds its request body with metadata spread last**, and **SettingsService's two cache slots
each query the settings row independently**.

**Fixed 2026-08-26.** `snapshot()` gained the same `baseline_loaded_at` guard already proven in
`signup_enabled()`: the lock captures `self._loaded_at` before the unlocked `_overrides()` read
starts, and the write-back checks whether it advanced past that baseline before installing —
if a concurrent `update()`'s `_publish()` (or another `snapshot()` call) already landed, this
read defers to the cached value instead of overwriting it with the stale one it started with.
Regression test: `test_a_slow_snapshot_read_in_flight_does_not_clobber_a_concurrent_publish`
(`web/tests/test_admin_settings.py`), using the same deterministic-interleaving technique as
`signup_enabled()`'s sibling test. The same `/code-review` pass that applied this fix also found
and fixed one more thing the fix itself introduced: `snapshot()`'s "stored settings are invalid"
error log used to fire unconditionally on a validation failure, even when the new guard was
about to discard that exact read because a fresher, valid value had already been published
concurrently — logging "serving deployed defaults instead" for a read that, in fact, was not
what ended up being served. The log now fires only inside the same locked block that decides
whether this read's result is actually installed, so it stays true to what `snapshot()` returns.

---

### [HISTORICAL] ~~`Services.signup()` builds its request body with metadata spread last~~ — FIXED 2026-08-27

**Where:** `static/js/modules/services.js`, `Services.signup()`.

**What is wrong.** The signup request body is built as `{ email, password, lang, ...metadata }`
— `metadata` spread last, so a future metadata key literally named `email`, `password`, or
`lang` would silently overwrite the real value client-side before the request is sent. There is
no server-side collision guard for this: `SIGNUP_METADATA_KEYS` in `web/api/auth.py` only
filters what gets forwarded into `raw_user_meta_data` once the request already arrived — it does
not guard the top-level request fields this spread order can clobber.

**Who it reaches.** Nobody yet — dormant, since no metadata field sent today is named `email`,
`password`, or `lang`. Would reach every signup once a colliding metadata field is ever added,
silently sending the wrong password/email/language with no error surfaced anywhere.

**How it was found.** Surfaced as a related item by `/code-review`'s 2026-08-26 pass on the
`SettingsService.snapshot()` race above, while reviewing the registrations-pause feature; filed
as its own entry rather than folded into that review.

**What fixing it would disturb.** Small: reorder the spread so explicit fields win —
`{ ...metadata, email, password, lang }` — or add a client-side guard that rejects a metadata
payload containing those keys before the request is built. Touches only the signup
request-building path; wants a test asserting an explicit field survives a colliding metadata
key.

**Fixed 2026-08-27** (`d9e542c`). Reordered to `{ ...metadata, email, password, lang }`, exactly
as this entry proposed. The JSDoc above `Services.signup()` now states the precedence
explicitly. Regression test:
`test_explicit_signup_fields_survive_a_colliding_metadata_key`
(`web/tests/test_signup_identity_capture.py`) drives `Services.signup` directly with a crafted
colliding metadata key and asserts the explicit arguments win — verified to fail against the old
spread order and pass against the new one. `ASSET_VERSION` bumped `warm57` → `warm58` in the same
commit. No server-side change: `web/api/auth.py` reads `email`/`password`/`lang` from the request
top level and forwards metadata separately, so there was nothing for a server-side guard to
protect — confirmed as part of the same review rather than assumed. Full analysis in
`docs/security-hardening-plan.md` (Task 2).

---

### [HISTORICAL] `profiles.last_seen_at` is written by nothing

**Where:** `public.profiles.last_seen_at`; read at `web/services/admin_store.py` into the
admin account-detail payload and rendered by `static/js/admin/ui.js`.

**What is wrong.** Nothing anywhere writes it. `grep -rn "last_seen_at" web/` returns one
production reference and it is a read. The column is guarded as server-owned by
`profiles_guard_privilege_columns` — a trigger defending a column that never changes — and
the admin console shows an empty field for every account.

**Who it reaches.** Any operator looking at an account. The cost is a contract lie: they
learn to ignore the field, and when a real "last seen" is wanted later, a column full of
NULLs will be misread as "nobody ever used the product".

**How it was found.** The 2026-08-28 database review
(`docs/database-improvement-plan.md`, finding 13).

**What fixing it would disturb.** Two honest resolutions and the choice is a product one.
**Drop it** — and its guard clause, its store field and its admin view; three files plus a
migration. **Or write it**, carefully, for two reasons that are easy to miss:
`handle_profile_update` sets `updated_at = now()` on every update to `profiles`, and
`admin_update_profile` uses `p_expected_updated_at` for optimistic concurrency against
that same column — so a background `last_seen_at` write would bump `updated_at` and make
an administrator's in-flight edit fail with a spurious `AD005` conflict. And a per-request
write to `profiles` is `20260828001636`'s write-amplification problem on a much bigger
table; it would need throttling (`where last_seen_at is null or last_seen_at < now() -
interval '1 hour'`) and a once-per-page-load path such as `/api/identity`, never
`/api/chat/stream`. If the feature is genuinely wanted, the cleaner design keeps last-seen
off `profiles` entirely rather than adding a per-request write to the one table every
request already reads.

**Written 2026-08-28.** The operator decided: write it. A first design did exactly what
this entry warned against — writing straight to `profiles` and editing the undiscoverable
legacy `handle_profile_update()` trigger — and was reversed after an adversarial review
(`opencode`, `openai/gpt-5.6-terra`, `xhigh`) named the real problem: that trigger's live
body was not in the checkout, so the design depended on an object nobody could read. The
shipped design is the "cleaner design" this entry already named: a new
`public.profile_last_seen` table (migrations `20260828135721`/`20260828135732`/
`20260828135749`), written by a throttled `touch_last_seen(uuid)` RPC called from
`/api/identity` (its own `try`/`except`, independently flagged by two reviewers so it
cannot suppress the unrelated standing-line facts also loaded there), and read into the
admin payload through `admin_get_user`'s new `left join` — so the `updated_at`/
`admin_update_profile` collision this entry warned about never occurs; nothing in the
shipped design writes to `profiles` at all. Full design and review trail:
`docs/data-policy-decisions.md`'s §4. `profiles.last_seen_at` itself is untouched and
still unwritten — dropping it is now its own, separate, still-open `TODO.md` entry: "Drop
`profiles.last_seen_at`, the column this feature replaced."

---

## [HISTORICAL] Resolved planned work

### [HISTORICAL] ~~Registrations pause — let an operator pause new signups~~ — BUILT 2026-08-25

> Built per `docs/registrations-pause-plan.md`, which stays live (it is a design
> record, not a superseded one — see its own STATUS line). **The filed entry's
> central premise was wrong**, and that is worth saying plainly rather than
> editing away: `POST /auth/signup`, the route it named to gate, was **dead in
> production**. The browser signed up straight through `supabase-js`
> `auth.signUp()`, direct to GoTrue with the public anon key — nothing called
> the Flask route at all. Gating it as filed would have shipped an operator
> control that paused nothing. Commit A of the plan moved
> `static/js/modules/services.js`'s `signup()` onto `POST /auth/signup` first,
> so the gate would have something real to gate; Commit B then added the flag
> behind it, as a `NON_GENERATION_KEYS` family inside `SettingsService` (own
> cache slot, same `_write_lock`, `signup_enabled()` reading three-valued —
> `True`/`False`/`None` for "could not determine" — rather than the two-valued
> fail-open/fail-closed the filed entry assumed). No migration: the flag lives
> in `app_settings.settings.signup_enabled`, the same JSONB row generation
> settings already use. `GET/PUT /admin/api/registrations` is its own endpoint,
> not folded into `/admin/api/settings` — the filed entry's "add or extend"
> phrasing left that open, and extending would have made every registrations
> toggle rebuild the OpenAI handler (`apply_generation_settings` runs inside
> `put_settings`'s write lock). Audited through the existing
> `admin_write_settings` RPC (action `settings.update`) rather than a new
> migration for a more specific action name. `docs/OPERATIONS.md` gained the
> bypass note the filed entry asked for, plus the Management API hard-close
> command and the Confirm-email interaction this migration introduces.
> `docs/ARCHITECTURE.md` now states which `auth_bp` routes are browser-direct
> (`login`) versus server-mediated (`signup`, `recover`, `logout`) — a fact
> that was true before this work and had never been written down. 35 new
> server-side tests (`web/tests/test_registrations_pause.py`), 8 rewritten
> browser tests (`test_signup_identity_capture.py`'s 7 plus one in
> `test_password_recovery.py`) that now intercept `/auth/signup` at the network
> layer instead of reading a browser-side Supabase mock that the migration made
> unreachable, and 3 new admin-console browser tests including the
> pause-persists-across-reload proof the plan asked for.
>
> Filed 2026-08-24 as _Signup kill-switch_; renamed because "kill-switch" is jargon
> the control itself should not carry — the feature is unchanged.

**Where:** `web/api/auth.py:90` `POST /auth/signup` (no gate today); `web/config.yaml:server` defaults; `web/services/settings_service.py:28` `GENERATION_KEYS` / `SettingsService`; `web/api/admin.py:192` `GET/PUT /admin/api/settings`; `web/templates/index.html:231` `#signup-pane` + `static/js/modules/handlers.js:207` `handleAuthFormSubmit`; `web/i18n/en.yaml` / `ar.yaml`.

**What is wrong.** Signup cannot be paused without a deploy or a Supabase-dashboard change. When load spikes there is no operator control in the console to refuse `POST /auth/signup` with a machine code and render a bilingual explanation; the only levers are code or the project-wide Supabase Auth toggle outside the app's audit trail.

**Who it reaches.** Every new visitor during a surge; operators who need a reversible, audited control that does not affect chat/auth for existing readers.

**How it was found.** Operator request 2026-08-24; code read confirms no check before `supabase.auth.sign_up` and no `signup_enabled` key in `web/config.yaml` or `app_settings`.

**What fixing it would disturb.** No migration if stored as `app_settings.settings.signup_enabled` (same JSONB as generation settings, different key namespace + bool validation). Otherwise: add `server.signup_enabled: true` default in `web/config.yaml`, extend `SettingsService` with a non-generation key set + bool validation and 30–60s TTL with immediate invalidate on `PUT`, gate `signup()` before the Supabase call (return `403 {error:"signup_disabled"}`), add or extend `GET/PUT /admin/api/settings` behind `admin_bp`'s bearer gate (`web/api/admin.py:98`) with `actor_from_request` audit, add admin toggle + reader banner/disabled tab in `index.html` / `handlers.js` / `services.js` with `runtime.auth` / `runtime.admin` keys in both YAML files (fails `test_arabic_catalogue_covers_every_runtime_key` if AR lags), and add unit + browser tests. Document the bypass: a Flask gate does not block a direct `supabase-js` `signUp` with the anon key — note the hard-close option (dashboard disable or Management API) in `docs/OPERATIONS.md`. Bump `ASSET_VERSION` in `web/api/app.py:248` for any CSS/JS change.

### [HISTORICAL] ~~The active conversation is per-browser, not per-tab~~ — CLOSED 2026-08-22

> Closed by `2026-08-22_per-tab-deep-linking.md`, landed the same
> day as roadmap §10.3's `/c/<id>` deep-linking — this entry already argued the
> two were one change: _"a conversation id that travels with the request
> rather than with the browser."_ The mechanism disagrees with what this entry
> proposed, though: not a `sessionStorage`-held tab-scoped pointer, but no
> pointer at all. The URL is the conversation id. `session["conv_id"]`, the
> cookie it named, `_resolve_conversation_id` and
> `POST /api/chat/sessions/<id>/select` are all deleted rather than
> generalised — see the plan's §1.2 for why a tab-scoped `sessionStorage`
> pointer would have reintroduced the exact collision this entry describes
> (it is cloned verbatim on tab duplication). Two tabs are now two independent
> conversations by construction: each carries its own client-minted id, and
> `ConversationStore`'s owner re-key — already anticipated here — is what
> stops one from ever reaching the other's window. Pinned by
> `web/tests/test_multi_tab_conversations.py`.

### [HISTORICAL] ~~Two step-8 migrations are written and not yet applied~~ — APPLIED 2026-08-21

> Applied as `20260821145319_chat_navigation_rpcs` and
> `20260821145416_chat_first_turn_title`, verified by round-trip in aborted
> transactions, advisors clean, and both files renamed to the assigned versions.
> The full record is in the step-8 entry above. Kept, struck through, for the
> ordering argument it makes — schema before code, because the reverse breaks
> persistence silently — which is the part worth re-reading next time.

**Where:** `supabase/migrations/20260821145319_chat_navigation_rpcs.sql` and
`20260821145416_chat_first_turn_title.sql`.

**Why this is its own entry.** The whole test suite — 540 server, 243 browser —
runs against `InMemoryChatBackend`, which mirrors the RPCs' guarantees rather
than approximating them: the title's `coalesce`, the rename's refusal to touch
`updated_at`, the delete's cascade and its idempotency-key cleanup. That is what
let step 8 be built and tested with the SQL unapplied, exactly as steps 2-6 were.
It also means **a green suite is not evidence that the database has these
functions**, and the failure in production is silent in the worst direction: the
sidebar lists nothing and every rename and delete 503s.

**Order matters and the second one is destructive.** Apply
`..._chat_navigation_rpcs` first. `..._chat_first_turn_title` then DROPS the live
13-argument `chat_append_turn` and recreates it with fourteen. `create or
replace` is not an option — a changed argument list makes a _second_ function,
and PostgREST would find a 13-argument call ambiguous and stop persisting every
turn on a deployment where the migration reported success. The drop and the
create are one transaction. What was checked before dropping (callers, grants,
dependents, rollback) is written into the file's header, per README rule 7.

**Verify after applying**, per `supabase/README.md`: `list_migrations` against
`ls migrations/`, then `get_advisors security` and `get_advisors performance`.
Round-trip `chat_append_turn` → `chat_list_sessions` in a deliberately aborted
transaction and confirm the title lands on the first turn and survives a second.

### [HISTORICAL] ~~Account detail view — the home for everything done to one account~~ — BUILT 2026-08-17

**Decided 2026-08-14:** this is where per-account management lives. Email
changes, password recovery, role, chat access and session revocation all land
here rather than being scattered across the People table. The entries above that
describe those actions individually describe _what_ to build; this describes
_where_, and they should not grow separate surfaces.

**Where:** `/admin` People renders one row per account — email, role, standing.
`public.profiles` already holds `full_name`, `organization`, `specialization`
and `preferences`; `auth.users` holds `created_at`, `last_sign_in_at` and
`email_confirmed_at`. None of it is shown anywhere.

**Why it is the right container, and not merely a convenient one.** A table
answers "who exists"; it is the wrong shape for "what about this person". Three
consequences follow from putting the actions on a per-account page instead of in
a row:

- **Sensitive actions get room to be confirmed properly.** Changing an email and
  revoking sessions both need explicit confirmation copy, and `DESIGN.md:278`
  gives the system no danger-button variant to lean on — the weight has to come
  from words. There is no space for that in a table cell, and a modal per row is
  worse than either.
- **The audit log gets a per-account home.** `/admin/api/audit` is global and
  newest-first, so "what has happened to this account" currently has no surface
  at all. It is the same query with a filter, and this is the page it belongs on.
- **It can show a broken account instead of hiding it.** The profile-less account
  bug above exists because People lists from `profiles`. A detail view loading
  `auth.users` left-joined to `profiles` renders that state as a visible problem
  rather than an absence.

**Three zones, in increasing severity — the page should read that way.**

1. **Identity, read-only.** Created, last sign-in, email confirmed, role,
   standing, and the reason if disabled. Facts an operator needs before deciding
   anything.
2. **Profile.** `full_name`, `organization`, `specialization`. Worth deciding
   deliberately whether these are editable or merely visible — showing them is
   most of the value, and editing another person's own description of themselves
   wants a reason better than "we could".
3. **Account actions.** Email change, send password reset, role, disable/enable,
   revoke sessions. Every one audited; the last three confirmed.

**What stays off this page.** What the reader asked. That line was drawn when
transcript browsing was declined in favour of an identity-free question log, and
a detail view is exactly where it would erode — "while we're here, show their
conversations" is the natural next request and the answer is still no.

**The dependency worth knowing before sequencing.** The admin's _send password
reset_ button and the reader's _forgot password_ link need the same thing: a
landing view that receives Supabase's recovery redirect, handles the
`PASSWORD_RECOVERY` event, and calls `auth.updateUser({ password })`. Whether the
link comes from `resetPasswordForEmail` or from `auth.admin.generateLink({ type:
'recovery' })`, it returns to the same place. So the reader-facing reset is not a
detour on the way to this page — it _is_ the hard half of one of its buttons, and
building it first means the console's version is a single API call on top of
finished work.

**Suggested order, each step shippable.** (a) The recovery landing view plus the
reader's forgot-password link — the foundation, and the thing that fixes a live
outage. (b) This page read-only: identity, profile, per-account audit. (c) The
actions, moving role and disable here from the table rather than duplicating them.

**What it would disturb.** Structurally little — a route, a panel, the existing
bearer-only gate. Two things need deciding rather than defaulting. It is a new
bilingual surface carrying emails, UUIDs, and timestamps in mixed Latin/Arabic
context, so it needs `<bdi dir="ltr">` discipline and coverage by the
`page.admin.*` / `runtime.admin.*` parity test. And once it can change an email
and trigger credential recovery, an admin session's blast radius grows
considerably — which is an argument for the severity zoning above, and for
`auth.admin.*` calls using the intent-then-outcome audit shape, since they cannot
share a transaction with their audit row.

**Update 2026-08-16 — built, except two things.** The page exists and all
three suggested-order steps landed: (a) the recovery landing view shipped
with reader-facing password reset, above; (b) and (c) shipped together rather
than sequentially.

- **Zone 1, identity: built.** Created, last sign-in, confirmed, last seen,
  disabled-at/by — `static/js/admin/ui.js:919-936`.
- **Zone 2, profile: built, and made editable.** The entry's own open
  question — visible or editable — was answered as editable:
  `static/js/admin/ui.js:938-943`, backed by `PATCH
/admin/api/users/<id>/profile` and `admin_update_profile`.
- **Zone 3, actions: built in full, 2026-08-17.** Send-password-reset
  (`static/js/admin/ui.js:956-959`), promote/demote and enable/disable
  **moved here from the People table** as planned
  (`static/js/admin/ui.js:961-977`), and — the two actions the "what is
  missing" notice used to name, closing this zone out — end-sessions
  (`#account-revoke-sessions`) and change-email (`#account-change-email`).
  The notice itself is now a conditionally-rendered empty block rather than
  deleted outright, so a future deferred action still has a home. See
  "Ending a session, as distinct from disabling chat" and the email-change
  half of "The console cannot change an email address..." above for what
  shipped and what it cost.
- **Zone 4, per-account audit: built.** `static/js/admin/ui.js:1010-1012`,
  backed by audit filtering in `web/api/admin.py:231-250,476-513`.
- Route/RPC: `supabase/migrations/20260814175551_account_detail.sql:16-65`.
  Browser coverage: `web/tests/test_admin_browser.py:519+`.

---

### [HISTORICAL] ~~Ending a session, as distinct from disabling chat~~ — BUILT and DEPLOYED 2026-08-17

**Resolved, in code.** `POST /admin/api/users/<user_id>/revoke-sessions`
(`web/api/admin.py`) ships. **The actual mechanism is not
`auth.admin.signOut(jwt, 'global')`** as this entry originally proposed —
verified against GoTrue's Go source that no endpoint revokes sessions by
user id alone, `signOut` needs the target's own live token, which the
console never holds. The real mechanism GoTrue's Admin API exposes is a
password rotation with no session context, which triggers the same
`models.Logout` (full session wipe) as a side effect. So `revoke-sessions`
rotates the account's password to a server-generated value that is
discarded immediately — never logged, stored, or returned — purely to
trigger that wipe. Chat access (`is_disabled`) is untouched, exactly as
this entry specified. The intent-then-outcome shape is built as predicted,
extended with a third outcome (`outcome_unknown`, alongside
`accepted`/`failed`) for transport failures whose true result is
genuinely unknown rather than provably failed — a refinement three
adversarial reviews converged on independently. `DESIGN.md`'s no-danger-
button constraint is answered the same way `send-reset` already answers
it: confirm copy carries the weight, including the honest caveat that an
already-issued access token remains valid until its own natural expiry.

Shipped alongside it, on the same page and by the same mechanism: `POST
.../change-email` — see the email-address entry above, which this was
built together with.

**Fully shipped, not just merged.** The new `admin_get_user` SQL
(`supabase/migrations/20260816215103_admin_get_user_email_verified.sql`)
was dry-run inside a rolled-back transaction first, then applied for real
against the live project and re-verified against real data afterward. The
application code reached production the same day: `main` was 79 commits
behind on the production server, deployed in one pass (`fb1f0a3` →
`dbfe151`), with `PUBLIC_BASE_URL` added to production's `.env` and
confirmed on Supabase's redirect allow-list — required for password
recovery, which this feature's own confirm-copy leans on for the
"send reset" companion action. Verified live post-deploy: clean gunicorn
restart, no startup errors, correct asset version served, and a real
recovery-mail send against the production redirect URL. Covered by
`web/tests/test_admin_users.py` and `web/tests/test_admin_browser.py`
(65/65 admin browser tests passing, including the new dual-dialog
change-email flow).

**One false alarm worth recording, so it isn't re-investigated as a mystery
bug later.** After deploy, admin-changing an account's email and then
logging in with what looked like the right password intermittently failed
with GoTrue's `invalid_credentials` — recoverable only by requesting a
fresh password reset. Investigated properly rather than assumed: two
independent adversarial passes (a live disposable-account test reproducing
the _exact_ reported round-trip sequence, and an independent code trace by
a second model) both confirmed the email-change call never touches
`encrypted_password` — proven by logging into the same disposable account
with the same known password before and after the exact change sequence,
repeatedly, with zero failures. The real account's own audit trail matched
this: every failure paired with a password the operator was recalling from
memory, and every fix was a password reset that supplied a password
they'd just typed. **Conclusion: this is not a bug, and a reader does not
need to reset their password after an admin-triggered email change** —
the apparent correlation was an artifact of testing against an account
that had already been through several password resets in this session
alone.

---

### [HISTORICAL] ~~Save chat sessions per user~~ — COMPLETE 2026-08-21, all eight steps

> **Status in one line:** steps 1-8 are done as of 2026-08-21. Turns are
> recorded to Postgres, `GET /api/chat/history` draws the visible transcript
> back out of those same rows, restored citations open their stored passages,
> `chat_resume_latest_session` is **on**, a notice **says so** — and a sidebar
> now lists every saved conversation, names each one from its opening question,
> and lets the reader switch, rename and delete.
>
> **Struck through at last**, and the convention is worth restating because this
> entry spent three revisions refusing to be: a heading is struck when a reader
> can see the difference AND nothing material is outstanding. Both are now true.
> Two things remain open and are tracked below as their own entries rather than
> here, because they are not this feature's unfinished half — they are separate
> changes to the chat routes' contract that this feature made worth doing.
>
> **What step 8 shipped (2026-08-21).**
>
> - **A segmented sidebar**, not a second drawer. `_sidebar.html` renders one
>   `role="tablist"` — Chats | FAQ — into the same macro that already
>   produces the desktop aside and the mobile offcanvas, so the FAQ rail and the
>   conversation list share the column instead of competing for it. The default
>   tab is chosen from the data on first load: a reader with history lands on it,
>   a first-time reader lands on the questions this column was originally for.
>   One offcanvas, always: navigation never spawns a second drawer, which is
>   what makes the overlapping-backdrop lockout impossible rather than merely
>   unlikely.
> - **Four Flask routes** — `GET /api/chat/sessions`,
>   `POST /api/chat/sessions/<id>/select`, `PATCH`, `DELETE` — over three new
>   `security definer` RPCs (`20260821145319_chat_navigation_rpcs.sql`):
>   `chat_list_sessions` (keyset on `(updated_at, id)`), `chat_rename_session`,
>   `chat_delete_session`.
> - **First-turn titling, inside the turn's own transaction.**
>   `20260821145416_chat_first_turn_title.sql` drops and recreates
>   `chat_append_turn` with `p_title`, applied as `title = coalesce(title, …)` in
>   the statement that claims the sequence numbers.
> - **`sessions_api: "60 per minute"`**, its own limit like `history_api`, so
>   ordinary browsing cannot spend the 200/day budget an office behind one NAT
>   shares with chat itself.
> - **Gates:** 540 server tests, 243 browser tests. `ASSET_VERSION` → `warm37`.
>   Both catalogues carry the new `runtime.sessions` block and `page.sidebar`.
>
> **Two written positions were reversed, deliberately.**
>
> - **The browser never touches these tables.** The roadmap said step 8 would be
>   "the first feature to call `chat_sessions_delete_own` from a browser with no
>   Flask route in between", and had deleted `chat_delete_session` as "a second,
>   privileged path". Two facts already in the tree retired that. First,
>   `revoke all on public.chat_sessions from service_role` leaves Flask holding
>   SELECT and nothing else — the choice was never "browser-direct or an RPC", it
>   was "browser-direct or nothing". Second, and decisively, a browser-direct
>   delete **cannot finish the job**: it cannot clear `conv_id`, `prev_conv_id`
>   or the `ConversationStore` window, and `chat_append_turn`'s
>   `insert … on conflict (id) do nothing` then lazily recreates the deleted
>   session on the reader's next question. RLS is back to being defence in depth
>   rather than the coordinator of a workflow spanning a cookie, a process-local
>   cache and three tables.
> - **The notice now names the delete, and the test that forbade it was
>   inverted.** `test_the_notice_does_not_promise_a_delete_control_that_does_not_
exist` existed because a draft offered a control nothing implemented. There
>   is now a control, so the assertion flips: a disclosure that omits the one
>   thing a reader would go looking for is misleading by omission in exactly the
>   way the draft was misleading by invention. Both the server-side and browser
>   halves were rewritten with the reasoning in the docstring, since a future
>   reader will otherwise see a check that got weaker.
>
> **A race the plan did not have, closed on the server as well as in the UI.**
> Both chat routes close over `conversation_id` and write at `final`; the
> sidebar's delete is a separate request. Delete a conversation mid-stream and
> the late append meets `on conflict (id) do nothing`, finds no row, and creates
> one — carrying the answer the reader thought they had discarded, on a
> regulatory product. `_InFlightGenerations` holds a counted claim on
> `(owner, conversation)` across the whole generation window; select and delete
> answer **409 `generation_in_flight`** against it, and the client refuses the
> controls with an explanatory toast so the reader is told rather than
> stonewalled. Correct because this app is single-worker by documented contract
> (`conversation_store.py:15-21`); if that changes the replacement is a tombstone
> table, not a bigger dict. `test_a_conversation_being_written_to_cannot_be_
deleted` drives it through the real generator and was **verified to fail
> without the guard** — it returns 404, because the session does not exist yet.
>
> **Three things deliberately not built**, recorded so they are not
> rediscovered as oversights:
>
> - **No virtualisation.** A bounded 30-row page and a cursor instead. The rows
>   are short titles, and this panel is already a scroll port inside the
>   offcanvas body, which is another one — virtualising would unmount rows while
>   focus and `aria-labelledby` still point at them and would fight Bootstrap's
>   focus trap, to save a cost that does not exist.
> - **No `Intl.RelativeTimeFormat`.** Arabic has six plural forms where
>   `I18n.plural` knows two, `Intl` emits bidi control marks that reorder inside
>   an RTL column — this repo has already paid for that once, with an en-US time
>   rendering as "AM 3:17:18" in an Arabic transcript — and the language toggle
>   reloads the page, so a cached relative string is stale by construction. Five
>   catalogue-owned day buckets instead, plus the exact timestamp in each row's
>   `title` attribute.
> - **No LLM titling and no boilerplate stripping.** `clamp_title` collapses
>   whitespace and cuts on a word boundary at 120 characters. A phrase list that
>   stripped "What are the requirements for…" / "ما هي اشتراطات…" is one
>   language's grammar wearing a general rule's clothing, needs maintaining in
>   two scripts, and fails by mangling the one string the reader uses to
>   recognise their own conversation.
>
> **The migrations were applied 2026-08-21, and the order was forced.** The new
> `SupabaseChatBackend` always sends `p_title`, so shipping the code first would
> have met the live 13-argument `chat_append_turn`, found no matching function,
> and reported every turn as unsaved. Schema first is the only safe sequence —
> and it is safe in the other direction too, which was **verified rather than
> assumed** before applying: a 13-argument named call resolves against the
> 14-argument function through `p_title`'s default, so the then-deployed code
> kept working with titles simply staying null.
>
> **Timing was the cheapest it will ever be.** `chat_sessions`, `chat_messages`,
> `chat_message_sources` and `chat_archive` all held **0 rows** — persistence has
> been on since 2026-08-20 with nobody having chatted since — so there was no
> backfill, no legacy `title is null` population, and no reader to disrupt. On a
> populated table this would have shipped a wart: an existing conversation would
> be named after whatever its reader asked _next_, since `coalesce` fires on the
> next append rather than on the opening question. That case does not exist here.
>
> **The `SECURITY DEFINER` ownership warning in the base migration was checked
> first**, since `20260821145416` drops and recreates a function that must keep
> table-write privileges the caller does not have: `apply_migration` runs as
> `postgres`, all four chat tables are owned by `postgres`, and the recreated
> function is owned by `postgres`. Confirmed after applying, along with
> `search_path=""`, `security definer`, and `EXECUTE` granted to `service_role`
> only on all four functions.
>
> **Round-tripped against the real database in aborted transactions** — the same
> technique the base migration was verified with, and the row counts afterwards
> confirm nothing committed (still 0/0/0/0). What it proved: the first turn names
> the session; a second turn does not rename it; a 13-argument call still
> resolves; `chat_rename_session` returns true and stores the trimmed title;
> a rename survives every later turn; clearing a name returns the row to null;
> a stranger's rename and delete both return false; `chat_list_sessions` derives
> `message_count` correctly and orders newest-activity-first; and an owner delete
> cascades leaving **0 orphan messages and 0 orphan sources**.
>
> **One property could not be shown dynamically and was checked statically
> instead.** "A turn moves `updated_at`, a rename does not" is untestable inside
> a single transaction, because `now()` is transaction-start time and does not
> advance. Read off the installed definitions instead:
> `chat_append_turn` contains `updated_at = now()` and `chat_rename_session` does
> not — which is the property, stated where it actually lives.
>
> **Advisors after applying: no new findings.** `get_advisors security` returns
> the four documented `rls_enabled_no_policy` entries and the Pro-plan
> `auth_leaked_password_protection`; `get_advisors performance` returns five
> pre-existing `unused_index` INFOs. These migrations add no table and no index,
> so a clean run was the expected result rather than a lucky one.
>
> **One divergence worth recording, on no reachable path.** Flask's `clamp_title`
> collapses interior whitespace (`"a   b"` → `"a b"`); `chat_rename_session`
> only `btrim`s and truncates, so it would store `"a   b"`. They never disagree
> in practice because every caller clamps in Python before the RPC — the SQL
> bound is the documented backstop for _length_, not a second normaliser. Left
> as is rather than "fixed" with a third migration, but written down so the next
> person does not discover it as a surprise.
>
> **The research that shaped it.** Two delegated passes, same shape as the ones
> that produced the roadmap itself: Antigravity `gemini-3.7-flash-high` ranked
> ten navigation patterns against this specific shell (segmented tabs first,
> rail-plus-panel rejected on the arithmetic — a 56px rail plus a 240px flyout
> plus the mascot rail suffocates the 68ch reading measure), and OpenCode
> `gpt-5.6-terra` at high effort produced fifteen ranked failure modes, of which
> the delete/stream race, the six-things-move-together switch, and the
> optimistic-rename ordering trap are all fixed above. **The OpenCode lane was
> re-dispatched off DeepSeek**, whose free tier now 401s
> ("Free promotion has ended for DeepSeek V4 Flash Free").
>
> **What changed 2026-08-20 (steps 5 and 6).**
>
> - **`GET /api/chat/history`** (`web/api/app.py`) serves the current
>   conversation. It takes **no conversation id**: the server resolves it through
>   `_resolve_conversation_id`, so the transcript on screen and the history
>   behind the model are chosen by one piece of code, and a browser cannot ask
>   for a conversation it does not own. An empty or unowned session is 200 with
>   no messages; a store failure is **503 `history_unavailable`**, deliberately
>   not an empty list — an empty transcript is a _claim_ that the reader has no
>   history, and making it while the store is unreachable is the quiet untruth
>   this product refuses everywhere else.
> - **`sessionStorage` is gone as a transcript store.** `Transcript.save`,
>   `Transcript.restore` and `neutraliseRestoredCitations` are **deleted**, not
>   merely unused: called on a hydrated transcript, that last one would strip
>   evidence that is present and correct. Worth recording, because it justified
>   the whole swap: `save()` had exactly one caller — the language toggle — so an
>   ordinary refresh already lost the conversation, a second device never had
>   one, and a restored answer's citations were stripped by construction. The
>   module header claimed it survived a refresh; it did not.
> - **Hydration renders through `UI.addMessage`**, the same path a live answer
>   takes, so `bindCitations` and `renderSourceTrigger` run and a restored
>   answer's controls resolve against real passages. Never re-inject stored
>   markup here — that is precisely what forced the neutralising.
> - **`chat_resume_latest_session: true`.** The flag waited for hydration
>   because, while the transcript lived in per-tab `sessionStorage`, every case
>   where the fallback fired was a case where the two halves disagreed — a blank
>   screen backed by a model that remembered. They now agree by construction.
>
> **A written design position was reversed, deliberately: a stale citation still
> opens.** The plan said only `verified` renders as openable evidence, with no
> document/page fallback (roadmap §"Stale sources"). That rule was aimed at
> _re-resolving_ a `chunk_id` against a rebuilt index, which can surface a
> plausible but wrong passage. It does not describe what hydration actually does:
> `chat_message_sources` already stores the document, page, category and snippet
> **frozen at write time**, so opening a stored citation shows what the model
> read, not a guess about where that text lives now. Kept strictly, the rule
> meant one corpus rebuild would silently deaden every citation in every stored
> conversation at once — and would leave a reader unable to tell "this evidence
> is dated" from "this answer had no sources", which is the same
> control-that-does-nothing failure the neutralising was invented to avoid.
> Two independent research passes reached this conclusion before the code did.
>
> So the three states survive as _classification_ and drive what the reader is
> **told**, not what they may open: `verified` says nothing; `stale` and
> `unverifiable` share one badge (`cite.datedBadge`) plus an explanatory line in
> the panel (`cite.datedNote`), because to a reader they mean the same thing and
> they stay distinct only in logs and tests.
>
> **`evidence_state` on a live answer is asserted, not computed.** A fresh answer
> came from the active index, so its evidence is current by construction. The
> comparison is inference and only hydration needs it — and computing it on the
> live path would mark every _fresh_ answer `unverifiable` on any deployment
> where `read_active_build_id` finds no pointer (the legacy flat layout), badging
> the one case that is beyond doubt.
>
> **One gap stays open knowingly, and is now disclosed rather than silent.**
> Ending a conversation and then logging out _before asking anything else_
> purges the cookie, so the next visit looks like a new device and resumes the
> conversation that was ended. With hydration on, that comes back as a full
> visible transcript rather than model-only memory — which an external review
> argued makes it worse, not better. The mitigation shipped instead of the fix:
> the route reports `resumed`, and the transcript carries a dismissible notice
> (`chat.resumed`) saying the conversation was picked up from history, with
> _New chat_ named as the way to start fresh. Closing it properly needs a
> durable owner-level reset marker; step 8's sidebar retires the question.
> Note `resumed` is only reported when there are messages — a notice about a
> thing the reader cannot see is worse than no notice.
>
> **Verified against the real database, not only the double.** `chat_append_turn`
> → `chat_load_session` was round-tripped in a rolled-back transaction on the
> live project: the user row carries no `corpus_revision` and no sources, the
> assistant row carries both, and each source arrives as `source_index` +
> `cited`. That is what `_hydration_payload` reduces, so the shape it consumes is
> now confirmed against the schema rather than inferred from `InMemoryChatBackend`.
>
> **Adversarial review of steps 5-6 (Codex `gpt-5.6-terra`, max effort, read-only),
> plus one bug found by hand before it ran.** Verdict was _do not ship_; everything
> below is fixed. 488 server tests, 213 browser tests.
>
> - **The transcript guard was keyed to the PAGE, not the reader** — found by hand.
>   `settleTranscript(null)` fires at startup, so the once-guard was already spent
>   by the time anyone signed in: on the ordinary path (sign in without a reload)
>   the transcript was never drawn at all, while the server resumed that reader's
>   history into the prompt window. A blank screen backed by a model that
>   remembers — the exact state `chat_resume_latest_session` waited two steps to
>   avoid, reintroduced by the client. Now keyed to the identity, and settling is
>   idempotent per reader so a second reader in the same tab gets their own
>   transcript. Pinned by `test_a_second_reader_in_the_same_tab_gets_their_own_transcript`,
>   verified to fail against the old guard.
> - **A late history fetch could resurrect a conversation the reader ended.** The
>   fetch is dispatched at sign-in and not awaited; pressing _New chat_ while it
>   was in flight put the ended conversation back on screen when it landed.
>   Identity cannot catch this — it is the same reader pressing the button. A
>   `transcriptEpoch`, bumped by reset, undo and sign-out, now invalidates a
>   response whose transcript moved under it. Pinned by
>   `test_late_history_cannot_resurrect_a_conversation_the_reader_ended`.
> - **A late fetch could also file history BELOW a live exchange.** Stored turns
>   are older than anything the tab has done, so they are inserted above the first
>   live turn rather than appended. Pinned by
>   `test_history_arriving_late_is_filed_above_the_live_exchange`, using a
>   controllable fetch so the race is entered deliberately rather than hoped for.
> - **`CORPUS_REVISION` was read from the pointer file, not from the engine.** The
>   search engine initialises _before_ that read, so an activation in between
>   recorded a revision the passages did not come from; and a dangling pointer is
>   returned verbatim while the engine silently falls back to the legacy flat
>   corpus. Either way a superseded answer would later compare equal and render as
>   current evidence — on the one product that cannot afford it. Now taken from
>   `SearchEngine.active_build_id`, which reports what was **loaded** and is `None`
>   for the legacy layout.
> - **An outage resolved to "you have no history", permanently.** A failing
>   `chat_latest_session` was swallowed, a fresh id minted and written to the
>   cookie — so every later visit found a cookie and never tried to resume again.
>   One transient failure cost the reader their conversation for good. The rule now
>   reports a failed resume distinctly; the transcript route answers 503 and rolls
>   the cookie write back, while the chat routes still answer. This is the same
>   shape as _"a transient Supabase outage signed readers out"_ at the top of this
>   file, which is why it is written out rather than quietly patched.
> - **Persistence enabled with no backend answered 200 with an empty transcript**,
>   while `_persist_turn` already treats that configuration as a failure. Now 503,
>   closing the read-side half of a gap the write side had already closed.
> - **An odd hydration limit split an exchange**, returning an answer with no
>   question and evidence attached. A leading assistant row is dropped, matching
>   what `ConversationStore.replace` already does for the prompt window.
> - **Hydrated turns were stamped with the reload time.** Every question in a
>   reader's history appeared to have been asked just now. `created_at` now
>   travels; and the in-memory double, which never set it, was corrected — the
>   same double-laxer-than-the-schema drift this feature was already bitten by
>   once, caught this time by a test that looked.
> - **Also fixed:** an identity change without a `SIGNED_OUT` left the previous
>   reader's passages in an open source panel (`clearReaderScopedUI`); the
>   transcript response was cacheable (`Cache-Control: private, no-store` plus
>   `cache: 'no-store'`); the blocking route shipped `evidence_state` that the
>   client dropped; unused `message_id`/`seq` were removed from the wire; and the
>   comment at the `CORPUS_REVISION` assignment still described the reversed
>   "stale is not openable" rule.
>
> Two of the review's findings were **not** acted on: it argued for reconciling
> rather than appending on hydration (the epoch guard plus above-insertion covers
> the cases it named), and for removing the public `limit` parameter outright
> (kept, now that a half exchange is impossible, because Phase 2's paging needs it).
> **Gates:** 488 server tests, 213 browser tests. The two browser tests that went
> red were the two that pinned the _old_ behaviour and were rewritten, not
> patched — see below.
>
> ---
>
> **Step 7 shipped as a notice, not a consent system (2026-08-21).** What landed
> is a bilingual dismissible banner, one hardening migration, and a startup
> guard. What was _planned_ — consent columns, an opt-out toggle, a withdrawal
> RPC, `admin_purge_chat_archive`, a retention CLI, JSONL export, three new
> routes and two more migrations — was **cut**. The reasoning, because "we
> decided not to" ages badly without it:
>
> - **The archive is dormant and cutting followed from that.** Both salts are
>   unset, so `archive_keys()` returns `(None, None)` and every archive insert is
>   skipped; `chat_archive` holds 0 rows. Controls for a collection process that
>   is not collecting are worse than absent — a Settings toggle reading
>   "Research archive: ON" asserts something false to the one person it is meant
>   to inform.
> - **Consent was dropped as the wrong instrument, not deferred.** The lawful
>   basis is legitimate interest on pseudonymized data, so `terms_accepted_at` /
>   `terms_version` were never needed — and recording consent you did not need
>   _manufactures_ an obligation, since claiming consent as the basis means
>   proving it was freely given and making withdrawal as easy as granting.
> - **Three cuts were for correctness, not size**, and are the ones not to
>   casually re-add:
>   - **The opt-out toggle had a race.** The archive decision would have been
>     read from the 30-second identity cache at request start and applied to a
>     write landing later. Correct needs the decision checked and serialized
>     _inside_ the write transaction.
>   - **It would also have failed open.** A transient identity-lookup failure
>     yields the unresolved fallback (`admin_store.py:706`); an `is not None`
>     check reads that as _opted in_. Privilege fails closed here; a privacy flag
>     must too.
>   - **The export's cursor was wrong.** Keyset on `(session_id, seq)` orders by
>     a random UUID, not by time, so "oldest first" would have been arbitrary.
> - **The notice deliberately promises no delete control**, because none exists:
>   the RLS `DELETE` grant is real but no route and no client code calls it. A
>   draft said "start a new chat, or delete a conversation, to clear one", which
>   would have made the disclosure the product's newest false claim. Pinned in
>   both suites so the tempting edit fails.
> - **And no model provider is named** (owner's decision), so the "never shared
>   for training" line went too — denying a third party the notice does not
>   acknowledge invites the question it closes. Verified while drafting, and
>   worth keeping on record: OpenAI does not train on API data by default (since
>   2023-03-01), `openai_app.py:377` sends no `store=` parameter, and
>   `config.yaml:96` sets `embedding_type: local`, so **question text is embedded
>   on this machine and only answer generation calls out**. Abuse-monitoring logs
>   retain requests up to 30 days. **Open lever:** OpenAI org-level Zero Data
>   Retention / Modified Abuse Monitoring would remove that window as a fact
>   rather than as wording.
>
> **The guard is the whole price of deferring.** Cutting the archive's controls
> is sound only while it is off, and left as a note that is a promise. So
> `server.archive_disclosed: false` plus `_warn_if_archive_is_undisclosed` logs a
> loud error at startup if either salt is set while the notice still says nothing
> about the archive — one config key, one log line, four tests, and "we'll
> revisit this" now fails visibly if nobody does.
>
> **The migration was amended before it was applied, and the live ACLs proved it
> necessary.** The pending file said `revoke insert`. `service_role` actually
> held **`INSERT, REFERENCES, SELECT, TRIGGER`** — so a named-verb revoke would
> have left `REFERENCES` and `TRIGGER` standing, which is exactly what the base
> migration's own sibling-table comment says `revoke all` exists to prevent. It
> now revokes all and grants back `SELECT`. **The `DELETE` grant that migration
> promised was retired rather than kept**: a purge function would be `security
definer` and would not need it, so a standing grant could only ever be a second
> unguarded delete path. Round-tripped after applying in a deliberately aborted
> transaction — there is no delete path left to clean up a test row —
> `archive_rows=1, message_rows=2`, confirming `security definer` bypasses the
> grants as designed.
>
> **An adversarial review (Codex `gpt-5.6-terra`, max effort, read-only) is what
> produced the cut list**, asked to default all 17 planned components to CUT.
> It cut 13. **Two of its own claims were checked and are wrong**, recorded so
> the reasoning is not inherited: `get_supabase_admin()` does _not_ raise outside
> an app context — `bool(current_app)` is `False` when unbound so the guard
> short-circuits, verified by running it — and "salts can never be rotated" was
> _my_ overstatement, since a versioned-key scheme retaining old keys could. Its
> adjacent point is right and kept: a bare `python -m` does not load `.env`
> unless it imports `web/utils/config_loader.py`.
>
> **Gates:** 497 server tests, 219 browser tests.
>
> **What is left, in order:**
>
> 1. ~~Apply the migration~~ — done 2026-08-20.
> 2. ~~Set `server.chat_persistence: true`~~ — done 2026-08-20.
> 3. ~~Build step 6 (transcript hydration), then set
>    `server.chat_resume_latest_session: true`~~ — done 2026-08-20.
> 4. ~~Step 7~~ — done 2026-08-21, **and deliberately much smaller than planned**.
>    See "Step 7 shipped as a notice, not a consent system" above.
> 5. ~~Step 8: the multi-session sidebar, auto-titling, switching, rename,
>    delete~~ — done 2026-08-21. The notice got its sentence and the test that
>    forbade it was inverted; see the step-8 record above.
> 6. ~~**Apply the two step-8 migrations.**~~ **Applied 2026-08-21** as
>    `20260821145319_chat_navigation_rpcs` and
>    `20260821145416_chat_first_turn_title`, in that order, through the Supabase
>    MCP `apply_migration` tool; both files renamed to the versions
>    `list_migrations` assigned. See "The migrations were applied" below.
>
> **Two follow-ups this pass deliberately did not build**, recorded so they are
> not rediscovered:
>
> - ~~**`chat_load_session` fetches sources with a correlated `jsonb_agg` subquery
>   per window row** (migration `:574-592`). The plan called this "sources come
>   back in the same call to avoid an N+1"; it is an N+1 wearing SQL clothing —
>   up to 200 index seeks and 200 JSONB builds per call. It did not matter while
>   `_load_history` was the only caller, because that reads once per process per
>   conversation. **Step 6 changes the economics**: hydration is now user-
>   triggered, so it runs on every reload, language toggle and sign-in — the
>   request that draws the whole screen. One `message_id = any(...)` fetch is the
>   fix. Not urgent at single-digit readers, where the SSE thread pool and the
>   single-worker FAISS constraint bind first, but it is now a per-visit cost
>   rather than an amortised one.~~ **Fixed 2026-08-22** — see the entry at the
>   top of Known bugs, which also records a join-form regression caught live
>   before it shipped.
> - ~~**`ARCHIVE_OWNER_SALT` / `ARCHIVE_SESSION_SALT` are unset**, and step 7
>   should decide whether the archive is wanted before building a purge path for
>   it.~~ **Decided 2026-08-21: it stays dormant, and the purge path was not
>   built.** See the step 7 record above.
> - ~~**`20260820140000_revoke_chat_archive_service_role_insert.sql` is still
>   unapplied.**~~ Applied 2026-08-21 as `20260820213833_revoke_chat_archive_
direct_writes`, **amended first** — see the step 7 record above.

**Where:** Today a conversation is keyed to a cookie, not to an account.
Server-side: `ConversationStore` (`web/services/conversation_store.py`), created
in `_register_routes` as `app.config["conversations"] = ConversationStore()`
(`web/api/app.py:513`) — process-local, TTL 3600s, LRU-bounded to 500, keyed by
the opaque `conv_id` that both `handle_chat` and `handle_chat_stream` invent and
park in the Flask session. The cookie itself never carries conversation content
any more, only `conv_id` / `prev_conv_id`; `handle_conversation_reset` rotates
those two to keep the undo honest (app.py:846-933), and `adopt_cookie_history`
is the one-time cookie→store migration for sessions that predate that (also
used to adopt any still-legacy `chat_history` / `prev_chat_history` a reader's
cookie might still be carrying). All of it is torn down by
`purge_conversation_state` and the `CONVERSATION_SESSION_KEYS` /
`CONVERSATION_ID_KEYS` tuples (`web/api/auth.py:20-54`) on logout or on an
identity change. Client-side: `Transcript` in `static/js/modules/i18n.js`
(lines 62-147) persists only _rendered markup_ into per-tab `sessionStorage`
under `sfda-transcript`, tagged with `_owner` (the user's id, via
`settleTranscript` in `static/js/app.js` lines 64-93) and restored only to the
same owner; `clearSessionState` removes it on sign-out
(`static/js/modules/handlers.js:723-751`).

**Why it is wanted.** A conversation lives exactly as long as one browser tab
and one hour in a process-local dict. A closed tab, a different machine, or a
store TTL loses the whole chat — the transcript resumes only as markup, and the
model's memory with it, because the context is the same `ConversationStore`
entry or the same cookie list. This is a mid-task tool (PRODUCT.md: the reader
is mid-task, not browsing), and there is no way to come back to a session later
or from another browser.

**Suggested sequence (Two Phases):**

1. **Phase 1 — Single-Session Cloud Persistence.** Move conversation state and
   citation payloads from process-local RAM/cookies to Postgres (`chat_sessions`
   and `chat_messages` with user-level RLS). This closes the 1-hour TTL and
   tab-close context loss, ensuring the active conversation and its clickable
   source citations survive reloads and work across devices without UI changes.
2. **Phase 2 — Full Multi-Session Conversation Manager.** Introduce a sidebar
   conversation list, opening-question auto-titling, session switching, and
   per-session deletion.

**What it would disturb.** The isolation contract is the reason a whole suite
exists: `test_session_isolation.py` (logout purge, server-side store purge,
`test_a_different_reader_does_not_inherit_the_streaming_conversation`,
`test_a_different_reader_does_not_inherit_the_blocking_history`,
`test_the_same_reader_keeps_their_conversation`) and the rotation in
`_bind_session_to_identity` exist to prove one reader's conversation never
reaches another. Saving per user re-keys conversations from a random cookie to
an account, which is only safe if the _account_, not the browser, becomes the
boundary — and it must still respect the purge that fires when a different
reader picks up the same cookie. Real persistence requires dedicated schema
and RLS policies (`supabase/migrations/`) and authenticated backend routes
for fetching and managing session trees. What survives the round trip matters
greatly: turn text is needed for the model's context, but the source passages
and citation payloads that feed the Source Panel must also be persisted or
rehydrated, rather than neutralising citations on reload. The reset/undo design
threads through every history test (`test_new_chat.py`, `test_chat_stream.py`,
`test_chat_api.py`). A multi-session sidebar in Phase 2 is a new bilingual
surface (`test_arabic_catalogue_covers_every_runtime_key`), logical-property
CSS (`web/tests/test_css_contract.py`), and an `ASSET_VERSION` bump.

**Open questions.** Data retention posture: whether chats are kept
indefinitely or subject to user-driven deletion / export ("answer receipts").
And how active SSE streaming interacts with background session switching if a
reader navigates to an older chat while a generation is in-flight.

**Update 2026-08-18 — planned, not yet built.** A full design record now exists
in [2026-08-20_chat-persistence.md](2026-08-20_chat-persistence.md),
synthesised from two independent delegated designs (Antigravity
`gemini-3.7-flash-high` for community practice and failure modes, OpenCode
`gpt-5.6-luna` at xhigh for an independent schema) plus current Supabase
documentation, with every claim about this repository re-verified against the
source before being built on — two of the research pass's ranked risks turned out
to be already handled here and are recorded as such rather than carried forward.

Four things it establishes that this entry did not know:

- **Phase 1 cannot be as invisible as proposed above.** Hydrating the transcript
  from persisted messages _is_ the payoff, because it is what lets
  `neutraliseRestoredCitations` be replaced by real citation rehydration. A
  restored answer currently keeps its prose and loses its evidence.
- **A stored `chunk_id` is not a citation.** Builds are versioned and swappable
  (`build_registry.py`), so a persisted source needs a content hash and a
  `corpus_revision`, and must fail closed to an explicit unavailable state — never
  fall back to document/page, which can plausibly match the wrong passage.
- **The logout guarantee changes.** Durable per-account history must survive a
  sign-out that today destroys it. Decided 2026-08-18: logout clears the cookie
  and the in-RAM cache only, retention ≥ 1 year, with administrator cleanup.
- **The admin analysis RPC reverses a written position.** _"Know what people
  actually ask — without reading anyone's conversation"_ (above) argues for an
  identity-free aggregate table instead, and its reasons survive the decision to
  build cross-user transcript access anyway. Recorded as a reversal, with the
  disclosure it now owes left open as a decision.

**Revision 2, after an adversarial review pass.** The plan was reviewed by two
external readers without the codebase and one adversarial pass with it. That pass
found a bug the first revision would have shipped — `conv_id` is
`uuid.uuid4().hex` (`app.py:559,1319,1495,1615`), 32 chars with no dashes, and a
Postgres `uuid` column returns the canonical dashed form, so every equality check
across the boundary fails silently — plus an unimplementable requirement (a hash of
the full chunk text, from a payload that carries only a 320-char snippet), a false
claim about the isolation suite, and a prompt-corruption path where `_truncate`'s
strict `[u,a,u,a]` assumption meets an interior unpaired row.

It also argued successfully for **deleting about half the design**: the
reserve-then-finalise state machine bought one thing — a durable record of a
question whose answer was aborted — at the cost of a status enum, a lease, a
startup sweep, an abort RPC, 409 semantics, and a `status='complete'` policy that
then hid the truth from the UI. Worse, reserving before retrieval would have
regressed `test_a_retrieval_failure_does_not_start_a_conversation`. The
recommendation is to write at `final`, where `append_turn` already sits.

The other structural change: **reader history and the training archive are now two
tables.** Folding them together was what made reader deletion, account deletion and
admin cleanup each destroy training data. Split, a reader's delete really deletes,
and the archive is append-only with no FK — following `audit_log.actor_id`, which
already argues that case.

**Consent is a notice, not a gate** (plan §7). A hard gate was drafted and dropped:
it would have forced a blocking bilingual screen into the first increment and made
the ephemeral path _permanent_, since a reader who declined would need today's
cache-and-cookie behaviour maintained indefinitely — a second conversation path
forever. It was also defending less than it appeared to: the archive row is written
in the same transaction as the turn, carrying the same question and answer text,
while `chat_messages` holds that text under a real `owner_id` with a `created_at` in
the same microsecond, so joining the archive back to a person is a text equality, not
a hash inversion. The hashing stays — it protects an archive that leaks _alone_, and
it is what makes erasure-by-owner possible — but it does not carry the weight a gate
was being built on top of.

So: the notice ships once at first use; `terms_accepted_at` / `terms_version` record
it; a separate `archive_withdrawn_at` is what actually stops collection, because "no
gate" and "withdrawal stops new archive rows" would otherwise contradict. All three
columns join the `profiles_guard_privilege_columns` deny-list — the column grants are
an allow-list so they are denied by default, but that trigger is a _deliberate_
deny-list, so a later change bundling them into a grant would make consent writable
from a browser console with nothing firing. One stable HMAC salt, no rotation
(rotation is defeated by a stable `session_key` and makes erasure impossible).
`admin_purge_chat_archive` takes a cutoff or an owner key and **refuses when both are
null**, which would otherwise delete the entire archive. Export is streamed JSONL,
`ensure_ascii=False`; there is deliberately no transcript console page.

**Revision 3 is a clean rewrite.** A fourth review pass found the document had been
revised in place until it contradicted itself — the central write-placement ruling was
simultaneously open and closed, §7's prose scheduled work its own table put elsewhere,
and a pair-assembly builder was defending a state the design could no longer reach. It
also found the sharpest bug yet, which only appears once Phase 1 meets the language
toggle: after _New chat_ the cookie holds a freshly minted id with **no durable row**,
so a naive "owned cookie → else latest `updated_at`" rule falls through and restores
the conversation the reader just ended. The cookie needs a third state — deliberately
empty — that the rule honours rather than overrides.

**Decided 2026-08-18: write at `final`**, in the position `store.append_turn` already
occupies (`app.py:1398`), rather than a reserve-then-finalise state machine. That
deletes a status enum, a lease column, a startup sweep, an abort RPC, 409 semantics and
a `status='complete'` policy that would then have hidden aborted turns from the UI — and
it avoids regressing `test_a_retrieval_failure_does_not_start_a_conversation`, which
reserving before retrieval would have broken. The consequence accepted knowingly: a
question whose answer is aborted mid-stream leaves no durable trace, exactly as today.

**Update 2026-08-19 — steps 2, 3 and 4 are BUILT; step 1 is written and not applied.**
Both gates green: 448 server tests, 204 browser tests.

Shipped: `web/services/chat_store.py` (`ChatBackend` Protocol, `SupabaseChatBackend`,
`InMemoryChatBackend`, uuid canonicalisation, HMAC archive keys); `ConversationStore`
re-keyed to `(owner, conversation)` with a new `replace()` for hydration; the
current-session rule and hydration in both chat routes; write-at-`final` with a
client-minted `client_request_id`; `persistence_unavailable` as an `error` frame; a
second bypass identity (`fake_reader_b_token` → `test-reader-b-id`); `chat.notSaved` in
both catalogues; `MAX_CHAT_QUERY_CHARS = 8_000`; `ASSET_VERSION` → `warm34`. New:
`web/tests/test_chat_persistence.py` (28 tests).

**Four plan claims implementation corrected** — the plan carries each as a struck
paragraph rather than a quiet deletion:

- **§5's "third cookie state" was unnecessary.** Keying the fallback on the _presence_ of
  `conv_id` rather than on whether it resolves makes all three resurrection paths no-ops,
  because the cookie holds an id in every one of them. The bug was real — reverting to the
  naive reading fails
  `test_new_chat_is_not_resurrected_by_the_current_session_rule` — but the fix is one
  predicate, not a marker three branches of the reset route must remember to write.
- **§9 overpriced the round trip.** Durable rows are read only when the RAM window is
  cold, so it is one read per conversation per process, not one per turn. The
  `(owner, session, last_seq)` caching idea it motivated is dropped.
- **§6 predicted the isolation assertions would go vacuous; they failed loudly instead** —
  better, and the reason is worth keeping: the fake second reader shared `test-user-id`,
  so the rule correctly resumed that owner's own history.
- **Step 1 shed three things.** Consent columns and the admin RPCs moved to step 7 (one
  concern per migration; a column no code reads is the untested surface §2.4 objects to),
  and `chat_delete_session` was deleted outright — readers already delete through an RLS
  policy, so a service-role RPC doing the same thing is a second privileged path to one
  effect. **Epilogue, 2026-08-21:** step 7 then cut the consent columns and the
  admin RPCs rather than building them — §2.4's objection turned out to apply to the
  whole feature, not just to its timing. `chat_delete_session` staying deleted is the one
  decision of the three that survived intact.

**One thing surfaced that this entry should carry: "New chat" no longer destroys
anything.** Reset drops the cookie pointer and the RAM window; the rows survive and will
appear in Phase 2's sidebar. That is correct and expected behaviour, but it makes _undo_
close to vestigial and means `forget` no longer forgets anything durable. Either the copy
changes in step 8 or `forget` grows a real delete. Pinned meanwhile by
`test_a_reset_does_not_delete_the_conversation_behind_it`.

**~~Blocked on one owner decision: applying the migration.~~ — RESOLVED 2026-08-20.**
Applied through the MCP `apply_migration` tool, straight to the live project (there is no
Supabase CLI, `config.toml` or Docker here — `supabase/README.md`), and renamed to
`supabase/migrations/20260820131914_chat_session_persistence.sql` to match what
`list_migrations` reports.

**Update 2026-08-20 — two adversarial bug-hunt passes (OpenCode `gpt-5.6-sol`, read-only).**
Round 1 reviewed the implementation; round 2 reviewed round 1's fixes and found defects in
them. 461 server tests, 204 browser tests, both green.

**The most consequential finding was not a bug.** The resume-my-last-conversation rule now
ships behind `CHAT_RESUME_LATEST_SESSION`, **default off**. The visible transcript still
restores from per-tab `sessionStorage` until step 6, so every case where the fallback fires
— new device, new tab, the request after a logout — would show a reader a blank screen while
the model silently received the conversation behind it. On an assistant whose claim is that
a reader can check where an answer came from, shipping half of that is worse than shipping
none of it. The machinery is built and pinned by tests that set the flag; step 6 flips it.

Real defects found and fixed:

- **The in-memory test double was laxer than the schema** — it accepted `source_index = 150`,
  a 400-char snippet and a null document. Every test runs against the double, so three CHECK
  constraints were being asserted by nobody. Round 2 then caught that the fix validated
  _before_ the replay check while the RPC returns _after_ it, making the double stricter than
  Postgres on the one path where that is wrong.
- **A cold-hydration race** could erase a completed turn: two tabs both read an empty window,
  and the slower one installed its stale copy over the newer one.
- **`revoke insert, update, delete` from `service_role` left `TRUNCATE` standing** — one
  statement could have erased every citation in the system, bypassing RLS. Now `revoke all`
  then `grant select`, which also makes "content is written only by `chat_append_turn`" a
  property the database enforces rather than a convention Flask follows. Confirmed against
  Supabase docs: `security definer` runs as the function owner, so the RPCs are unaffected.
- **Two redundant indexes and a missing FK index** — `unique (session_id, seq)` already
  indexed what `chat_messages_session_seq_idx` re-indexed, while the FK `(session_id,
owner_id)` had none.
- **A `DELETE` grant on the archive** whose comment credited it to a function that ships in
  step 7. Revoked. ~~The migration that adds the purge RPC grants what it needs.~~
  **Superseded 2026-08-21:** no purge RPC shipped, and when one does it will be
  `security definer` and will not need the grant either — so a standing `DELETE` could
  only ever be a second, unguarded delete path. `20260820213833` retired the promise and
  reduced `service_role` to `SELECT` alone.
- **A JSON scalar `null` aborts `jsonb_array_elements`**, rolling back a turn the reader is
  already reading — `coalesce` catches SQL NULL only.
- **The last error frame overwrote the first**, so a reader whose answer merely went unsaved
  was told their message failed to send; and **suppressing the mascot's error state left it
  animating forever**, because that branch returns before the happy path's `returnToIdle`.

Also: the migration now parses under the real PostgreSQL grammar (`pglast`/libpg_query,
PG17) — top level and all three function bodies. That is syntax only, not semantics,
constraints, grants or runtime.

**One gap accepted knowingly**, to fix before the resume flag turns on: with it on, ending a
conversation and then logging out _before asking anything else_ loses the reset, because the
purged cookie makes the next visit look like a new device.

**Late catch, after the branch was already pushed: `chat_persistence` defaulted ON.** With
the schema unapplied, that meant a deploy of this code would have called RPCs that do not
exist, turning every single answer into a "could not be saved to your history" toast. A
feature that defaults on before its schema exists ships as a visible error. Now defaults
off, pinned by `test_persistence_and_resume_both_default_off`, which reads the flags off a
non-testing app because TESTING selects the in-memory backend unconditionally and would have
hidden the production default.

~~**And one claim this work cannot yet back.** The RLS policies are unexercised. The service
role bypasses RLS, so every green test proves the _application's_ owner filtering, not the
database's. Until a reader JWT hits these tables — a harness that does not exist here, and
costs more than the migration did — `chat_sessions_select_own` and its three siblings are
reviewed code, not verified code.~~

**Backed 2026-08-21. The harness cost nothing, because a signed token was never the
requirement.** PostgREST authenticates by setting `role` and `request.jwt.claims` on the
connection, and `auth.uid()` reads `sub` out of that GUC — both settable directly with
`set_config` and `set local role`. Two readers were seeded through `chat_append_turn`, the
connection dropped to `authenticated` as reader A, and the transaction aborted so nothing
committed. With both readers' rows present in every table, A saw **1 session of 2, 2 messages
of 4, 1 source of 2**; `chat_archive` was **DENIED**; forging a message row and tampering with
a stored answer were both **DENIED** (no insert or update policy, exactly as designed);
deleting another reader's session touched **0 rows**; deleting their own touched **1** and
cascaded to **0 orphans**.

This closes step 1's gate, which had been the only thing outstanding in the feature's critical
path since 2026-08-20 — and it is worth noting _why_ it stayed open: the estimate was wrong,
not the work. It was priced as needing a Supabase project, two real accounts and a signed
token, so it was deferred as expensive. It was one query.

**One honest limit.** This exercises the policies, not PostgREST. A browser reading these
tables through the anon key is still untested _plumbing_ on _verified_ policy — which is a
live concern for step 8, the first feature to call `chat_sessions_delete_own` from a browser
with no Flask route in between.

**Update 2026-08-20 — two independent post-live reviews (OpenCode `gpt-5.6-terra` at high
effort; Antigravity `gemini-3.7-flash-high`), each pointed at the roadmap's §11/§12 so they
would not re-report what two earlier passes already fixed.** `gemini-3.7-flash-high` found
nothing new, with a specific verification note per risk area. `gpt-5.6-terra`'s first run
(read-only `plan` agent) died mid-review on a denied tool permission with no way to approve it
headless; the rerun as `build` (instructed not to edit, and didn't) found four real gaps, all
verified against the source before acting on them:

- **Fixed.** `_persist_turn` treated `backend is None` as one case, when it is two: the
  deployment choice ("this install has no database") and a live misconfiguration
  (`chat_persistence: true`, but `get_chat_backend()` came back empty — most likely
  `SUPABASE_SERVICE_ROLE_KEY` missing or wrong). Both returned `True` silently — `persisted:
true` on the blocking route, no error frame at all on the streaming one — while nothing
  reached Postgres. Only the first should be quiet; the second now fails exactly like any
  other storage failure. `web/api/app.py` (`_persist_turn`), three new tests in
  `web/tests/test_chat_persistence.py`.
- **Fixed.** `archive_keys()` returning `(None, None)` on a missing salt logged nothing, though
  the design record above states "a missing salt fails the archive write closed **and logs**."
  Now logs once per process (not once per turn — `.env.example` calls an unset salt a
  supported, possibly permanent state, so an ERROR on every turn forever would be noise).
  `web/services/chat_store.py` (`archive_keys`), one new test.
- **Written, not applied.** `grant insert, select on public.chat_archive to service_role` is
  unnecessary — `chat_append_turn` is `SECURITY DEFINER` and never needed the grant to do its
  own insert — and it is a second, unguarded path into the archive for anything holding the
  service-role key, bypassing `chat_append_turn`'s owner/session validation and its atomic
  pairing with a real turn. Nothing in this codebase currently uses that path. Migration
  drafted at `supabase/migrations/20260820140000_revoke_chat_archive_service_role_insert.sql`;
  applying it needs the Supabase MCP connection re-authenticated first (session expired
  mid-review) — an owner decision, same as step 1 originally was.
- **Fixed (docs only).** The roadmap doc still said "step 1 is written and not applied" in
  three places after it was applied. Corrected to match `TODO.md` and the real migration
  state.

---

### [HISTORICAL] ~~Two notices carried an off-vocabulary rule weight, and one referenced a token that does not exist~~ — FIXED 2026-08-21

**The weight.** `.resumed-notice` and `.history-notice` in `static/css/components.css` each carried `border-inline-start: 3px solid var(--confidence)` / `var(--warning)` on top of a 1px hairline box. `DESIGN.md` had already committed to a three-weight vocabulary in which each weight means something: 1px is a hairline, 2px is a mark that carries meaning (DESIGN.md: "Don't use the 2px rule weight decoratively — it is reserved for marks that carry meaning"), and 4px is a meter (the undo countdown, whose own comment says it is 4px "and not the system's 2px" precisely because a meter is not a rule). 3px was none of the three.

**The fix.** Both notices now use the same inset 2px pseudo-element pill that `.faq-button.active` and `.history-item.is-active` already use — `inset-block`, `inset-inline-start: 0`, `inline-size: 2px`, `border-radius: var(--radius-pill)`. The box keeps a 1px hairline on all four sides. Three components now share one mark for "this edge is telling you something." Note it is a pseudo-element rather than a border, which is what puts it on the reserved weight instead of inventing a fourth.

**The phantom token.** `.history-notice` declared `line-height: var(--lh-normal, 1.5)`. There is no `--lh-normal` in `static/css/tokens.css` and there never was — the ramp is `--lh-tight` / `--lh-snug` / `--lh-body` / `--lh-loose`. The declaration resolved to its own fallback every time, so it worked, which is why it went unnoticed while quietly opting that notice out of the type scale. Now `var(--lh-body)`.

**How it surfaced.** The Impeccable design hook flagged the two borders as a "side-tab accent" pattern. Worth recording that the detector's reason (a thick coloured side border is a recognisable AI-generated tell) was the weaker argument; the one that actually decided it was the project's own weight vocabulary. Both borders predated step 8 — they shipped in steps 6 and 7 — and were deliberately left untouched when step 8 landed rather than being changed as a side effect of an unrelated feature.

**Verification.** Re-rendered and checked in light, dark and Arabic RTL: the pill mirrors to the inline-start edge under `dir="rtl"`, and the dark-mode warn ramp (`#E0A94D`) reads clearly against the dark ground. `grep` confirms no `border-inline-start: 3px` or `border-inline-end: 3px` survives in any of the five stylesheets. Gates: `test_css_contract.py` at zero physical-property violations, 540 server tests, and 242 browser tests. The full browser run also reported one _error_ — a Playwright setup timeout in `test_source_panel.py::test_an_error_after_final_keeps_the_canonical_answer`, not an assertion failure — and that whole file then passed 42/42 in isolation. Recorded rather than rounded to "green": it is the intermittent flake already tracked under _"The browser suite flakes intermittently in test_source_panel.py"_, and this pass touched only two notice rules, neither of which the source panel uses.

**Docs.** `DESIGN.md`'s Notices subsection now describes the pill and states the weight reasoning, and a new Don't was added — "Don't invent a rule weight outside the vocabulary" — so the pattern cannot return unremarked. `.impeccable/design.json` was regenerated from that DESIGN.md in the same pass.

This landed alongside a `/impeccable document` merge that added the step-8 sidebar components (sidebar tabs, the conversation row, the two notices) to `DESIGN.md`, which had documented none of steps 6-8's visual surface.

---

### [HISTORICAL] ~~Consolidate every documentation file into `docs/`~~ — FIXED 2026-08-16

**Resolved, partially by design.** `PRODUCT.md` and `memory-bank`'s two
survivors (`productContext.md`, `projectbrief.md`) moved into `docs/`, which
now holds `PRODUCT.md`, `productContext.md`, `projectbrief.md`, and
`SMTP_CONFIGURATION.md`. `memory-bank/` no longer exists. Two of the four
"Root" documents deliberately did **not** move, answering this entry's own
open question about whether README stays the only root-level doc: it gains
one sibling directory (`docs/`), not more root-level files.

- **`DESIGN.md` stays at root.** It's the companion file for this project's
  Impeccable design-tooling sidecar (`.impeccable/design.json`); that
  tooling's convention reads it from the repo root. Moving it risked breaking
  tooling for a discoverability gain that matters less for a file read
  mostly by tooling, not humans browsing the repo.
- **`TODO.md` stays at root.** The most actively-edited file in the project,
  and the conventional place a contributor looks for a backlog.
- **`supabase/README.md` stays put**, and was never really the problem: it's
  subsystem-scoped documentation next to the migrations it describes, which
  is exactly where a contributor working in `supabase/` expects to find it.
  It wasn't contributing to the root-clutter problem this entry was actually
  about.

The cost this entry worried about turned out smaller than expected: a
repo-wide search found every bare-filename mention of `DESIGN.md`/`PRODUCT.md`
in code, tests, CSS, JS, and i18n comments — `test_admin_page.py:80`,
`test_admin_settings.py:321`, `test_password_recovery.py:176`,
`static/js/app.js:266`, `static/js/admin/ui.js:9,787`,
`static/js/admin/handlers.js:290`, `static/css/components.css:304`,
`web/i18n/en.yaml:305,316`, `web/i18n/ar.yaml:279,290`,
`web/services/admin_store.py:386`, `web/templates/index.html:123,429,452`,
`web/api/app.py:1154` — is a **human-readable citation in a comment or
docstring, not a functional path reference**: nothing programmatically
opens/imports these files by path. Moving `PRODUCT.md` broke zero tests and
zero runtime behavior. Those citations are deliberately left as bare
`PRODUCT.md`/`DESIGN.md` rather than updated to `docs/PRODUCT.md` — editing
`static/css/components.css` or `static/js/app.js`, even comment-only,
triggers this project's own "any commit touching CSS or JS bumps
`ASSET_VERSION`" convention for zero functional benefit, and the citations
still correctly name the file, just not its folder. The only things that
actually needed updating were the real markdown links and the
project-structure tree, both in `README.md`, plus the now-orphaned
`memory-bank/Issue-teckting/` line in `.gitignore` (removed alongside).

---

### [HISTORICAL] ~~The memory-bank docs are stale, and the review cannot trust them~~ — FIXED 2026-08-16

**Resolved.** The review this entry deferred is done. Of the eight tracked
files, six were confirmed dead and deleted — `activeContext.md`,
`CHANGELOG.md`, `NewKnowledgeBase.md`, `progress.md`, `systemPatterns.md`,
`techContext.md` — each verified individually against current code before
removal (the specific staleness this entry already listed for each: the
`feature/All-Guideline` branch, the pre-2026-08 changelog, dead file
references, the broken `system-architecture.png`, `Python 3.9+`/`unittest`,
and coverage numbers matching nothing real). `productContext.md` and
`projectbrief.md` survive unchanged, exactly as this entry predicted: no
dates, no dead references, product rationale that still holds. Nothing was
cross-referenced by code or tests, so nothing else moved — confirmed by a
fresh repo-wide grep for `memory-bank` immediately before deleting (only
README.md, TODO.md, and `.gitignore` mentioned it, and all three are now
updated).

`memory-bank/Issue-teckting/` — the ten gitignored fix-plan and analysis
files this file's "Consolidate every documentation" entry flagged as an
at-risk, ungitted cluster — was reviewed in full and deleted too rather than
brought under version control. Every file targeted a codebase shape that no
longer exists: a single `static/css/style.css` (replaced by the layered
`tokens/base/components/robot/effects` system), a `web/docker-compose.yml`
and `web/.env.example` that aren't in the repo, and bugs (the FAQ-buttons RLS
hang, the theme-toggle icon collision, the stale-refresh-token handling) that
were fixed long ago through other means. Not git-recoverable, unlike the six
above — deleted deliberately rather than by the same-risk reasoning that
applied to the tracked files.

Net effect: `memory-bank/` is now two files, both accurate. The larger
"Consolidate every documentation file into `docs/`" entry below is unaffected
in shape but smaller in scope — there is no `memory-bank/Issue-teckting/`
left to migrate, and `memory-bank/` itself is now two small, already-correct
files rather than a set needing review before any move.

---

### [HISTORICAL] ~~The `.env` file carries keys nothing reads~~ — FIXED 2026-08-16

**Resolved, in two steps.** `README.md:329-361` and `.env.example` were
re-verified against a fresh repo-wide grep of every `os.getenv`/`os.environ`
read: they already listed exactly what the code reads — including
`SUPABASE_AUTH_TIMEOUT`, added since this entry was first written — and
README already stated outright that `FLASK_ENV`, `FLASK_DEBUG`, plain
`SECRET_KEY`, and `DATABASE_URL` are dead. That half needed no further work.

The project's actual `.env` is gitignored and was never read here — it
carries real secrets — but a sanitized working copy (`.env copy`) was
reviewed line by line against the same grep, and every variable it carried
that nothing reads was identified and removed: `OPENAI_MODEL`,
`EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`, `MAX_TOKENS` (all superseded by
`web/config.yaml`'s `openai.*` / `search_engine.*` keys, and already out of
sync with the live values there), `SUPABASE_KEY`, `supabasePassword`,
`FLASK_APP`, `PORT` (the real port is `config.yaml` -> `server.port`, and the
`.env` copy's value didn't even match it), `CHUNK_SIZE`/`CHUNK_OVERLAP`
(from `config.yaml` -> `data_processing.*` instead), and `API_KEY`. The
legacy `SUPABASE_SERVICE_ROLE_KEY` was also dropped in favour of the
`SUPABASE_SECRET_KEY` already present — the code prefers the latter whenever
both are set (`web/utils/supabase_client.py:110`), so the legacy key was
already inert and is one fewer non-revocable credential to track. The
cleaned copy was then applied to the real `.env` by hand, since only whoever
holds that file can safely do the reconciliation.

One side effect worth recording: reviewing the sanitized copy in this
conversation surfaced that it wasn't actually sanitized — it still carried
live values for `OPENAI_API_KEY`, `SUPABASE_SECRET_KEY`, and
`FLASK_SECRET_KEY` (also `SUPABASE_SERVICE_ROLE_KEY` and a raw
`supabasePassword`, both now removed regardless). Those three should be
treated as exposed and rotated independently of this cleanup — that is
tracked as a follow-up outside this file, not blocking it.

**This stopped being theoretical on 2026-08-16.** A local `.env`, untouched
since 2026-05-30, was carrying exactly the dead set this entry describes
(`FLASK_APP`, `FLASK_ENV`, `PORT`, …) and neither `FLASK_SECRET_KEY` nor
`SUPABASE_SECRET_KEY`/`SUPABASE_SERVICE_ROLE_KEY` — so `get_supabase_admin()`
had no credential to construct a privileged client with, and _every_ reader
on that instance resolved as a non-administrator, unconditionally. It read as
"the admin button is broken" and cost real investigation time before the
file's own modification timestamp settled it: nothing had changed recently,
the `.env` had simply never been updated to match what the app grew to need.
Confirms the severity this entry already claimed — updated after the fact.

---

### [HISTORICAL] ~~Stale claims in README, and a one-time orphan-file sweep~~ — FIXED 2026-08-16

**Resolved, both halves.** The README half was fixed earlier this session
(see the `.env` entry above). The orphan-file sweep — the half this entry
left open — is now done too: every git-tracked module under `web/` (32
files) and `static/js/` (22 files) was checked for a real cross-file
reference, not just presence in a directory.

**Method, since the risk was overreach.** A name match alone isn't proof of
use — the risk this entry itself named was a file that's actually loaded by
glob (`MODULE_FILENAMES`/`ADMIN_MODULE_FILENAMES` in `web/api/app.py:222-235`
publish _every_ file under `static/js/modules/` and `static/js/admin/` into
the browser import map automatically) rather than by a literal import
statement, which would make "not imported by name" a false positive. So
every low-hit-count result was read in full before being called clean, not
just counted.

**Result: nothing orphaned.** On the Python side, every module traces back
to `web/api/app.py` either directly or through `search_engine.py`'s
composition (`search_index`, `lexical_searcher`, `semantic_searcher`,
`result_combiner`, `query_processor`, `build_registry`, `pharma_constants`
all confirmed as real imports, several via one-hit modules that were read
individually to be sure). The dual OpenAI files are also both live:
`openai_client.py` and `openai_app.py` are separately imported and serve
different callers, confirming the entry's own suspicion that this is
deliberate decomposition, not duplication. On the JS side, `app.js` and
`admin.js` are the two template `<script type="module">` entry points
(`index.html:688`, `admin.html:193`); every other file is `import`ed by name
from another module — nothing exists only via the import-map glob without
also being actually imported somewhere.

**One unrelated thing the file listing surfaced.** A `web/api/.venv/`
directory exists on disk — a second, nested virtualenv sitting inside
`web/api/` beside the real project-root `.venv`. It is gitignored and
0 files are tracked in it, so it is local disk clutter rather than a repo
problem; not acted on here since it isn't part of what this entry scoped.

---

### [HISTORICAL] ~~The docs quote three different `ASSET_VERSION` values, none of them current~~ — FIXED 2026-08-16

**Resolved by the fix this entry itself recommended.** `DESIGN.md`'s "Do bump
`ASSET_VERSION`" bullet no longer names a value at all — it now reads "Do bump
`ASSET_VERSION` in `web/api/app.py` in any commit touching CSS or JS," which
cannot go stale the way a quoted example (`"warm14"`, before that `"warm6"`)
does on the very next commit that follows the instruction. `web/api/app.py`
itself was at `warm30` by the time this was fixed, one more bump past the
`warm28` this entry quoted when it was written — confirming the entry's own
point about how fast the quoted value ages.

`.impeccable/design.json`'s `narrative.dos` still cites an old value, left
alone as this entry already concluded: it is generated, `detector/design-system.mjs`
parses `DESIGN.md`'s frontmatter live rather than the sidecar, and it will
correct itself whenever the sidecar is next regenerated.

---

### [HISTORICAL] (original entry) The docs quote three different `ASSET_VERSION` values, none of them current

**Where:** belongs with the documentation entries above. `web/api/app.py` is the
live source and reads `warm28` (2026-08-16 — this entry's own previously-quoted
`warm27` was already stale by the time it was read again, which is the point).
`DESIGN.md`'s "Do bump `ASSET_VERSION`" bullet cites `warm14`.
`.impeccable/design.json`'s `narrative.dos` cites `warm6`.

**What is wrong.** Nothing functional — no check reads either quoted value, and
the design hook parses `DESIGN.md`'s frontmatter live rather than the sidecar
(verified in `detector/design-system.mjs`, which is also why the "sidecar is
stale" advisory is cosmetic here and not a correctness risk). The problem is
that a rule quoting its own stale example teaches the reader to distrust the
rule. `DESIGN.md` is the maintained document and is the one worth fixing;
`design.json` is generated and will correct itself whenever the sidecar is
regenerated.

**What fixing it costs.** One line in `DESIGN.md`, plus a decision worth taking
once: **stop quoting the value at all.** "Bump `ASSET_VERSION` in
`web/api/app.py`" is the durable instruction; naming the current value adds
nothing and goes stale on the very next commit that follows the instruction.

---

### [HISTORICAL] ~~The CSP still allows an image from any HTTPS origin~~ — FIXED 2026-08-27

**Where:** `web/api/app.py` — Talisman's `content_security_policy`, the `img-src`
directive, currently `["'self'", "data:", "https:"]`.

**What is wrong.** `https:` is a wildcard: it permits an image request to any host on
the internet. On its own that is an ordinary, common relaxation. It stopped being
ordinary when the URL started carrying a conversation id. An image URL is a GET the
browser makes automatically, carrying a `Referer`, and the deep-linking work made
`/c/<uuid>` the address of a reader's conversation. §6.4 of
`docs/archive/2026-08-22_per-tab-deep-linking.md` asked for this to be tightened as
defence in depth for exactly that reason, and the request was never carried out.

**How it was found.** Reading that plan's own §6 against the code during the
2026-08-23 documentation audit. The plan lists it; nothing else did, which is why it
was filed as its own entry before the plan was archived.

**What fixing it would disturb.** The audit did not enumerate what the three templates
actually load, so the honest first step was to find out rather than guess a
replacement list. Sunny is inline SVG, every icon is inline SVG from
`web/utils/icons.py`, and there is no avatar upload — Decision 4 of the profile plan
declined it — so the real surface may already be `'self' data:`. If it is, the change
is one line. If a CDN image is in use somewhere, the directive names that host instead
of the whole web. Tighten it, then load all three pages in both languages and both
themes and watch the console for a CSP violation.

**Priority:** low severity, low cost. It is here because a hardening step a plan asked
for and nobody did would otherwise be archived along with the plan.

**Fixed 2026-08-27** (`366f1a6`). Tightened to `"img-src": ["'self'", "data:"]`. **The
`Referer` premise above turned out not to hold**, and the record should say so rather than
let a wrong diagnosis stand corrected only in the commit: Talisman already sets
`referrer_policy="strict-origin-when-cross-origin"`, which strips path and query from every
cross-origin referrer — the conversation id was never in that header. The actual unmitigated
vector was that model output renders through a DOMPurify profile that permits `<img>`
(`static/js/modules/stream-render.js`), so a markdown image in an answer was a live outbound
beacon under the old `'self' data: https:` policy. The image surface was swept across all five
templates (three assumed here undercounted `web/templates/partials/_sidebar.html`) plus
`static/js/` and `static/css/`: nothing loads an image from any external origin. New test:
`web/tests/test_security_headers.py`, verified to fail against the old policy and pass against
the new one. Full inventory and reasoning in `docs/security-hardening-plan.md` (Task 1).

---

### [HISTORICAL] ~~Every authenticated request pays a network round trip to verify its token~~ — FIXED 2026-08-27

> The worker-starvation mechanism this entry is actually about — a burst of
> concurrent requests on one bearer token exhausting all eight threads — is
> closed with **no revocation trade at all**:
> `web/services/token_verification_cache.py` single-flights every
> authenticated request, on every route including `/admin/*`, so a console
> boot's fan-out collapses to one live GoTrue call regardless of how many
> requests fire together. A structural pre-check rejects a malformed or
> already-expired token before any network call, closing the one thing
> single-flight cannot: a flood of _distinct_ invalid tokens.
>
> The revocation-window decision this entry demanded, written down: the
> positive cache — reusing a verified result across _sequential_, not
> concurrent, requests — ships disabled (`ttl_seconds: 0` in
> `web/config.yaml`, reader routes only, `/admin/*` always exempt). Enabling
> it is a separate, smaller, deliberately deferred decision — see
> _Enable the token-verification cache once production numbers justify it_
> in `TODO.md`. The original diagnosis's "four" console verifications was
> also undercounted — it is six to seven. Full plan, adversarial review, and
> file-by-file implementation in
> `docs/archive/2026-08-27_token-verification-cache.md`.

**Where:** `web/api/app.py`, `_authenticate_request` calls
`supabase.auth.get_user(token)` on every request that is not the public
landing. Surfaced 2026-08-15 by the audit of the outage bug above.

**What is wrong.** Nothing is cached. Opening the console costs **four** GoTrue
verifications — identity, settings, users, audit — before an operator has
clicked anything, and opening one account costs **two more**. There is an
identity-flags cache (`web/services/identity_cache.py`, 30s TTL) but it covers
the _profile_ lookup that follows, and console requests deliberately pass
`fresh=True` to bypass even that, for a documented and correct reason: being
thirty seconds behind a demotion is unacceptable on the surface that can disable
an account.

**Who it reaches.** Everyone, as latency; and it is the reason the timeout bug
above had such a wide blast radius. Production runs `--workers 1 --threads 8`,
so a slow GoTrue holds one of eight request threads per in-flight verification
and eight concurrent stalls exhaust the only worker for every reader.

**What fixing it costs — and why it is not obviously worth paying.** The obvious
move, caching token→user for a short TTL, buys latency at the price of a revoked
session staying valid for that TTL. That is a real security trade and it is not
the same trade as the identity-flags cache, which only ever caches _flags_ for
an already-verified caller. The alternative is verifying the JWT locally against
the project's signing key, which removes the round trip entirely and keeps
revocation semantics honest for expiry — but not for revocation, and it means
holding key material and tracking Supabase's move to asymmetric keys.

**Do not do this quietly.** It is a deliberate weakening of a check that
currently asks the authority on every request. Whoever picks it up should write
down the revocation window they are choosing, and say it out loud in this file.
The mitigations already shipped — a 5s ceiling, correct outage classification,
and a client-side guard against double-opening an account — address the harm
this caused without touching the trade.

---
