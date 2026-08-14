# TODO

Known problems found but deliberately not fixed in the commit that found them,
usually because the fix reaches further than the work in hand. Each entry says
what is wrong, how it was found, and what fixing it would disturb — so the next
person can judge the cost rather than rediscover it.

**Known bugs** are things that are wrong now. **Planned work** is wanted but not
started. Both are written the same way and for the same reason: an entry that
says only what it wants is a wish, and the useful half is the cost.

---

## Known bugs

### Signup email runs on Supabase's built-in SMTP, which is capped at ~2/hour

**Where:** The Supabase project's Auth settings, not this repo. Surfaced on
2026-08-14 while testing the rewritten signup trigger: three signups in seven
minutes produced one `mail.send` and two `429 over_email_send_rate_limit`.

**What is wrong.** Email confirmation is enabled and mail goes out through
`noreply@mail.app.supabase.io`, Supabase's shared built-in sender. It is
documented as being for testing rather than production, and its per-hour
allowance is small — observed here as one confirmation delivered and the next
two rejected. GoTrue rolls the account back when the send fails, so the reader
gets no account **and** no email, and the address stays free.

**Who it reaches.** Every new registration on the live deployment
(`sfda-copilot.aifoudahub.com`). The third person to sign up within an hour is
turned away. There is nothing wrong with their details and nothing they can do
except wait, which the surface does not tell them.

**It is worse than a failed signup.** `Handlers` surfaces the raw Supabase
message, so the reader sees "email rate limit exceeded" — English-only, and
phrased as though *they* exceeded a limit. `runtime.auth.*` has no key for it.
Whatever else is decided, the message needs a key in both catalogues and wording
that says the service is busy rather than blaming the reader.

**The fix, and why it was not made here.** Configure a custom SMTP sender
(Resend, SES, Postmark, or the SFDA-side mail relay) under Authentication →
Emails. That is a project-settings and DNS change — a sending domain with SPF
and DKIM — not a code change, and it belongs to whoever owns the domain. It was
found during unrelated work on the signup trigger and recorded rather than
half-done. Until then, treat the deployment as unable to onboard more than a
couple of people an hour.

**Related, same session:** email confirmation is on, yet only one of the three
existing accounts has `email_confirmed_at` set. Worth deciding deliberately
whether confirmation is required to chat, because right now the answer is
implicit.

---

### Leaked-password protection is disabled in Supabase Auth

**Where:** The Supabase project itself (`yjjuudnsnjzhyqllsqrd`), not this
repo — surfaced by Supabase's advisors during a 2026-08-13 database audit.

**What is wrong.** Leaked-password protection is off in Auth: Supabase would
otherwise reject signups/password changes using a password known to be
compromised, checked against HaveIBeenPwned.

**Who it reaches.** Every signup — project-wide, not per-route.

**The fix, and why it was not made here.** It's a toggle under
Authentication → Attack Protection, but the toggle is a **Pro-plan feature**
and this project is on a lower tier while actively developing. Left off
intentionally rather than forced — revisit when the project upgrades to Pro
or moves toward production.

**Companion item, resolved:** the same audit flagged the project's Postgres
as behind on security patches. That side is done — upgraded to `17.6.1.155`
on 2026-08-13, confirmed via Security Advisor (warnings dropped from 2 to
1, the remaining one being leaked-password protection above). The same
audit pass also fixed what it could reach via `apply_migration` (revoking
public `EXECUTE` on the `handle_new_user` signup trigger, pinning
`handle_profile_update`'s `search_path`, and optimizing the RLS policies on
`profiles`/`users`).

---

## Planned work

### Answer from a second provider — and why the code is the easy half

**Where:** `web/services/openai_app.py` builds one `OpenAI(api_key=...)` client
in `__init__` and calls `client.chat.completions.create(...)`. The model
allowlist lives in `web/config.yaml` under `openai.allowed_models`, and each
entry already describes that model's parameter contract (`token_param`,
`supports_temperature`, `reasoning_efforts`) because the OpenAI families do not
share one. `web/services/settings_service.py` validates a selection against
that list; `apply_generation_settings` in `web/api/app.py` builds a replacement
handler and swaps it.

**Why it is wanted.** Much cheaper models exist and some are free. DeepSeek V4
Flash is roughly $0.14/$0.28 per 1M tokens against gpt-4o-mini's $0.15/$0.60;
NVIDIA's Nemotron 3.5 Lightning is about $0.05/$0.20 on DeepInfra and free on
`build.nvidia.com`. For a project that is also a demonstration piece, being able
to fail over to a free model when a key runs dry has obvious value.

**The integration is genuinely small.** Both are OpenAI-SDK drop-ins: DeepSeek
at `https://api.deepseek.com` (models `deepseek-v4-flash`, `deepseek-v4-pro` —
note `deepseek-chat` was deprecated 2026-07-24), NVIDIA at
`https://integrate.api.nvidia.com/v1` (`nvidia/nemotron-3.5-lightning-30b-a3b`).
An allowlist entry would gain `provider`, and the handler would pick a
`base_url` and an API key per provider. Perhaps an afternoon.

**What it would disturb — and this is the actual cost.** PRODUCT.md's first
principle is that provenance is the product: "An answer without a resolvable
source is a liability, not a feature." `BASE_SYSTEM_MESSAGE` in
`openai_app.py:35-59` is tuned so that every claim carries a `[n]` marker, no
number is ever invented, and a refusal carries no markers at all. The API
decides whether an answer gets a source panel by counting those markers
(`extract_cited_indices`), so a model that follows those instructions *less
reliably* does not fail loudly — it produces a confident answer with citations
that do not support it, on a regulatory question, for a professional who will
quote it to an auditor.

**So the prerequisite is a citation-fidelity harness, not the client change.**
`scripts/eval_retrieval.py` and `web/tests/data/retrieval_eval.yaml` measure
retrieval, not whether the model cites what it actually used. Something has to
answer, per model: what share of factual sentences carry a marker; how often a
marker points at a passage that does not support the sentence; and whether a
refusal stays clean. Without that, switching providers is a change to the
product's central claim made on the basis of price.

Two smaller consequences: `tiktoken` does not apply to a non-OpenAI model, so
`tokenizer_exact` is permanently False and logged token counts stop meaning
much; and cost metadata becomes per-provider rather than per-model.

**Open questions.** Whether a second provider is a per-instance choice or a
per-request fallback when the primary errors. Whether the Arabic half holds —
the corpus is bilingual and a cheaper model's Arabic regulatory register is a
separate question from its English one, which the harness has to measure in both.

---

### OpenRouter as one integration instead of several

**Where:** the same seam as the entry above.

**Why it is wanted.** It subsumes that work rather than competing with it. One
OpenAI-compatible endpoint (`https://openrouter.ai/api/v1`), one key, and model
ids of the form `deepseek/deepseek-v4-flash` or
`nvidia/nemotron-3.5-lightning:free` — so DeepSeek, Nemotron and a few hundred
others arrive together, including a free tier. Optional `HTTP-Referer` and
`X-Title` headers attribute usage. Compared with wiring each provider
separately, this is one `base_url`, one secret, and an allowlist that can grow
without code.

**What it would disturb.** Everything in the entry above still applies — the
citation-fidelity question is about the *model*, and routing through OpenRouter
does not answer it. Three things are specific to the aggregator:

- **A router is not a model.** The same id can be served by different providers
  with different quantisation and context handling, so behaviour can move
  without the id changing. `provider.order` / `allow_fallbacks` pin it; unpinned,
  the thing the harness measured is not necessarily the thing that answers.
- **Free tiers carry their own limits** — roughly 50 requests/day, and 20/minute
  on `:free` variants at the time of writing. That is below this app's own
  15/minute chat limit, so a free model would need the quota work to know about
  a *provider* ceiling as well as a per-reader one.
- **A third party sees the prompts.** Every question includes retrieved SFDA
  passages and the reader's own words. Sending those to an aggregator that
  routes to an undisclosed provider is a disclosure decision, not a technical
  one, and it belongs with whoever owns the deployment — the same conversation
  as the conversation-persistence privacy posture.

**Open questions.** Whether OpenRouter replaces the direct OpenAI client or sits
beside it as a second provider — keeping the direct path means the primary model
never depends on a third party's uptime. And whether free models are usable at
all given the rate limits, or whether their real role is a demonstration of
failover rather than a way to serve readers.

### Refactor the profile page

**Where:** All of it lives browser-side; there is no Flask route and no
server-rendered profile page. `handleProfileButtonClick` and
`handleProfileFormSubmit` in `static/js/modules/handlers.js` (lines 611-681);
`populateProfileForm` in `static/js/modules/ui.js` (~line 611); `getProfile` and
`updateProfile` in `static/js/modules/services.js` (lines 299-318), speaking
straight to Supabase's `profiles` table via
`from('profiles').select('id, full_name, organization, specialization, preferences')`
and `from('profiles').upsert({ id, ...updates }, { onConflict: 'id' })`;
`loadProfileWithTimeout` in `static/js/app.js` (lines 29-49), fed by
`API_TIMEOUT` / `RETRY_MAX_ATTEMPTS` / `RETRY_DELAY_INITIAL` in
`static/js/modules/config.js`; the `#profileModal` form in
`web/templates/index.html` (lines 239-289); the two `profile-button*` triggers
in `web/templates/partials/_sidebar.html` (lines 59-62); and
`AppState.state.userProfile` in `static/js/modules/state.js`. The catalogue
already carries `runtime.profile.*` keys (`loadFailed`, `saveFailed`, `saved`)
in both `web/i18n/en.yaml` and `web/i18n/ar.yaml` — no JS module reads them.

**Why it is wanted.** The profile is a Bootstrap modal bolted onto the chat
shell, and its wiring strains in visible ways. The form is seeded from the
*startup snapshot*: `loadProfileWithTimeout` fills `AppState.userProfile` once at
sign-in (`static/js/app.js:207`), and `handleProfileButtonClick` only calls
`Services.getProfile` on a cache miss (handlers.js:655-678) — so the modal shows
whatever the page captured on load, never a fresh read. The theme radios never
reflect the stored preference: both `populateProfileForm` (ui.js:625) and the
empty-profile reset (handlers.js:668) check `ThemeManager.getCurrent()` — the
live `data-bs-theme` attribute — not `profile.preferences.theme`, so a reader
who saved Dark is shown their *current* theme, not their saved one. And the
surface is silently English-only while the `runtime.profile.*` keys written for
exactly this sit unused.

The reason to touch it has changed. It used to be that the admin controls needed
somewhere to live and nothing but this modal existed to hang them from — that is
no longer true; they live at `/admin`, on their own page, and this modal was
never asked to carry them. What is left is the modal's own two bugs, below, and
the question of whether a reader-facing profile deserves better than a Bootstrap
modal bolted onto the chat shell.

**Two live bugs to fix while you are in here.** Both are shipped today, both
were confirmed by reading the code, and neither has a test that would catch it —
which is why they are written out rather than left in the prose above.

1. **The theme radios ignore the saved preference.** `populateProfileForm`
   (`static/js/modules/ui.js:625`) and the empty-profile reset
   (`static/js/modules/handlers.js:668`) both select the radio matching
   `ThemeManager.getCurrent()` — the live `data-bs-theme` attribute — rather
   than `profile.preferences.theme`. Save Dark, switch to Light, reopen the
   modal: it shows Light, and saving from there silently overwrites the stored
   preference with the current one. Neither test in
   `test_profile_theme_integration.py` asserts which radio is *selected*:
   `test_profile_form_loads_cached_profile` opens the modal but checks only the
   name and organization fields, and `test_profile_update_applies_and_persists_theme`
   saves and never reopens it. The gap is the read-back, so that is where the
   new test goes.

2. **Every profile string is hardcoded English.** Five call sites in
   `static/js/modules/handlers.js` — 620, 635, 639, 650 and 674 — pass literals
   to `showProfileError`/`showToast`, while
   `runtime.profile.{loadFailed,saveFailed,saved}` sit in *both*
   `web/i18n/en.yaml` and `web/i18n/ar.yaml` and are read by no module. An
   Arabic reader gets English on this one surface.
   `test_arabic_catalogue_covers_every_runtime_key` cannot catch this: it
   checks that Arabic has every key English has, and both catalogues have
   these — they are simply never used. Note there are five sites and only
   three keys, so translating them is not a one-to-one mapping; the session-
   expired (620) and save-failure (639) messages need keys that do not exist
   yet.

**What it would disturb.** Every profile behaviour is pinned by tests that name
it. `web/tests/test_profile_theme_integration.py` runs three browser tests —
cached form fill, theme-persists-through-save, and the `updateProfile` /
`getProfile` wire contract (`test_profile_service_contracts`) — entirely against
the `SUPABASE_BROWSER_MOCK` `from('profiles')` chain in
`web/tests/conftest.py`, a chain that supports exactly the one
`{id, full_name, organization, specialization, preferences}` shape.
`test_frontend_architecture.py::test_handlers_own_user_facing_service_failures`
pins that `ErrorHandler.showProfileError` stays in `handlers.js`, so moving
profile handling to another module is a contract change, not a relocation.
`test_frontend.py::test_login_and_logout_flow` asserts `#profile-button` is
visible after sign-in. Any new `runtime:` strings must ship in both YAML files —
`test_arabic_catalogue_covers_every_runtime_key` fails if Arabic lags — and any
new CSS must use logical properties or `web/tests/test_css_contract.py` (zero
violations today) fails; any commit touching CSS or JS bumps `ASSET_VERSION` in
`web/api/app.py`. A separate page would break the one-page two-views model
(`index()` renders a single template and `AuthView` toggles `d-none` between
landing and chat), and this project deliberately has no bundler, so a build step
is a much bigger change than it looks — new modules under `static/js/modules/`
are picked up at import time by the `MODULE_FILENAMES` glob and the import map,
but only after a restart.

**Open questions.** Is the profile a better modal or its own server-rendered
page, and if a page, how does it coexist with the landing/auth shell and the
`?testing=true` demo path? Should profile data keep flowing browser-side through
the anon-key Supabase client, or move behind an authenticated Flask route — no
such route exists today, and the operations this exposes are governed only by
Supabase RLS, which is not located in this repo (there are no `.sql` files)? And
should the theme preference even be a stored profile field when nothing renders
from it server-side?

---

### Give readers a quota, and limits worth having

**Where:** rate limiting is one global setting. `web/config.yaml` has
`server.rate_limit` (`per_day: 200`, `per_hour: 50`, `per_minute: 10`,
`chat_api: "15 per minute"`), and `web/api/app.py` builds a `Limiter` keyed by
`get_remote_address` with `storage_uri="memory://"`. `chat_limit` is a *callable*
limit, re-read per request, so the value is already live-tunable — what is not
live is who it applies to. `public.profiles` gained a `tier` column
(`20260814005509_lock_profile_privileges_and_repair_signup.sql`) that nothing
reads: `IdentityFlags` carries it, and no code branches on it.

**Why it is wanted.** Every reader gets the same allowance, keyed to an IP —
so an office behind one NAT shares a budget, and one person on two networks gets
two. The console can now change the model and cut off an account, which are the
blunt instruments; a quota is the one that lets an operator say "this is fine,
but not unlimited" without a confrontation.

**What it would disturb.** The limiter's key function is the change with the
widest blast radius: `_rate_key` would return the reader rather than the address,
and the decorator order at the chat routes is load-bearing — `auth_required` runs
outermost, so `g.identity` exists before the limit callable is evaluated, and
reversing those two lines silently reverts to IP keying with no error. `memory://`
loses counters on restart, which is acceptable for a burst limit and not for a
daily budget: a monthly allowance that resets on every deploy is not an
allowance. That means real persistence — a `usage_daily(user_id, day, used)` row
and one atomic `insert ... on conflict ... where used < limit returning`, taken
in the view body *before* the generator, so a denial is a 429 instead of an SSE
stream that dies halfway.

The reader-facing half matters as much: a quota is a normal boundary, not a
failure, so it wants an inline transcript notice in both languages styled with
`--confidence`, never `--danger` — and `/api/identity` already returns enough
shape to show a quiet counter before someone hits the wall, which beats being
stopped at it.

**Deliberately deferred once already.** Two independent reviews judged the full
tier matrix — a `tiers` table with `label_en`/`label_ar`, per-user overrides,
time-windowed access, token credits — premature for an instance with three
accounts and one operator. Token credits in particular need exact provider usage
first: the OpenAI stream currently ignores usage chunks, and tokenizer estimates
are not a billing ledger. Start with one number per reader per day.

**A dormant start already exists.** `public.chatbot_settings` — `welcome_message`,
`response_style`, `rate_limit_per_minute` — is still sitting in the database,
RLS-enabled with zero policies and read by nothing. The admin console
deliberately created `public.app_settings` rather than reuse it, because a
global `rate_limit_per_minute` scalar belongs on a tier rather than on the
instance. Worth deciding whether it is dropped or finally used.

---

### The browser suite flakes intermittently in test_source_panel.py

**Where:** `web/tests/test_source_panel.py`, only under a full `-m browser` run.
Seen twice on 2026-08-14 across roughly five full runs, on different tests each
time — once as a teardown ERROR on
`test_a_restored_answer_cannot_open_another_answers_sources`, once as an
`ERROR at setup of test_a_citation_marker_opens_the_panel_on_its_passage`.

**What is wrong.** Unknown. It is an error rather than an assertion failure, so
it is the Playwright fixture rather than the assertion — the page or context is
gone by the time the test wants it. It does not reproduce running the file alone
(36 passed) or on a repeat of the full suite (131 passed both times).

**Who it reaches.** CI, as a red build on a green branch. `.github/workflows/tests.yml`
runs the browser suite as a separate merge gate, so an intermittent error there
is a merge blocked for no reason — and the fix people reach for is "re-run it",
which is how a real failure eventually gets waved through.

**Why it is written down rather than fixed.** Nothing was diagnosed. The
plausible causes are resource contention across ~36 browser contexts in one
session, or a fixture that outlives its page — `sourced_page` and friends layer
`page.route` handlers over the shared `browser_page`, and Playwright matches the
most recently added handler first, which is order-dependent by construction.
Chasing it needs a reproduction, and it did not reproduce on demand.

**Where to start.** Run the browser suite with `-p no:randomly` if ordering is
suspected, or `--tracing retain-on-failure` to capture the context state at the
moment it dies. If it recurs in CI, that trace is the thing worth having.

---

### Save chat sessions per user

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
(lines 62-147) persists only *rendered markup* into per-tab `sessionStorage`
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
or from another browser. The state exists today; it just has no home that
outlives the process.

**What it would disturb.** The isolation contract is the reason a whole suite
exists: `test_session_isolation.py` (logout purge, server-side store purge,
`test_a_different_reader_does_not_inherit_the_streaming_conversation`,
`test_a_different_reader_does_not_inherit_the_blocking_history`,
`test_the_same_reader_keeps_their_conversation`) and the rotation in
`_bind_session_to_identity` exist to prove one reader's conversation never
reaches another. Saving per user re-keys conversations from a random cookie to
an account, which is only safe if the *account*, not the browser, becomes the
boundary — and it must still respect the purge that fires when a different
reader picks up the same cookie. Real persistence means a database, and
this repo has none of it ready: there are no `.sql` migrations, and the only
table named anywhere is `profiles`, read and upserted from the browser with no
Flask route in between. Schema, RLS, and a server-side path for reads and writes
are all net-new. The reset/undo design threads through every history test —
`test_new_chat.py` end to end (rotation, the `prev_*` keys,
`test_undo_survives_a_blocking_question_after_resetting_a_streaming_conversation`),
`test_chat_stream.py`
(`test_history_survives_the_streaming_response`,
`test_adopt_cookie_history_migrates_once`, the `ConversationStore` unit tests),
`test_chat_api.py` history tests — and each of those decides, per assertion,
what "saved" means when the store is a database rather than a cookie or a RAM
dict. A conversation list is a new bilingual surface
(`test_arabic_catalogue_covers_every_runtime_key`), logical-property CSS
(`web/tests/test_css_contract.py`, zero violations today), and an
`ASSET_VERSION` bump.

**Open questions.** Where the sessions live: a new Supabase table plus RLS
(not located in this repo) versus extending `profiles` versus something the
single-instance deployment can own itself — the `ConversationStore` docstring
already names swapping its backing dict for Redis as the seam if process-local
ever stops being acceptable. What the unit is — one auto-saved chat per reader,
several named ones, per browser? — and how that interacts with reset/undo, which
today assume exactly one current conversation. What survives the round trip:
turn text for the model's context, or also the source passages and citation
payloads the panel renders — the client today deliberately restores only markup
and neutralises restored citations, because sources die in module memory on a
reload (`static/js/app.js:85`). And whether a saved session belongs to the
account across browsers, which is the only reading that is safe on a shared
machine.