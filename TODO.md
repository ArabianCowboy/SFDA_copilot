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

### There is no password reset, so a forgotten password is an unrecoverable account

**Where:** `static/js/modules/services.js` exposes `signInWithPassword` (line
222) and `signUp` (line 229) and nothing else — no `resetPasswordForEmail`, no
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
[docs/SMTP_CONFIGURATION.md](docs/SMTP_CONFIGURATION.md) records as configured
but not yet proven.

**Do this before the admin credential work below**, which is partly made
unnecessary by it.

---

### The console cannot change an email address, and deliberately cannot set a password

**Where:** `admin_set_user_flags` reaches `role` and `is_disabled` only. Both
`auth.users.email` and the credential live in Supabase Auth, not in
`public.profiles`, so neither is reachable from the RPC the console uses.

**Why an email change is wanted.** People change employer and typo their address
at signup. With confirmation off, a typo'd address is currently permanent and
invisible — the account works, and the mail it should receive goes to a stranger.

**Why setting a password is *not* wanted, and this is a design position rather
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

**What it would disturb.** Both reach `auth.admin.*`, so both are the
outside-Postgres case the audit design already anticipates: the mutation and its
audit row cannot share a transaction, so they need intent-then-outcome — record
the intent, perform the call, record what happened. An email change is also an
account-takeover primitive when paired with a reset, so it wants confirmation to
the *new* address rather than `email_confirm: true`, and it wants the old address
kept in the audit row — otherwise the log cannot show what the account used to be.

---

### The signup rate-limit message reaches the reader as raw English

**Where:** `static/js/modules/handlers.js` surfaces the Supabase error text
verbatim; `runtime.auth.*` has no key for it in either catalogue.

**What is wrong.** When Supabase refuses a signup for exceeding its email
allowance, the reader sees "email rate limit exceeded" — English on a bilingual
surface, and phrased as though *they* exceeded a limit rather than the service
being busy. GoTrue rolls the account back when a send fails, so they get no
account and no email, and the address stays free to retry — none of which the
message says.

**Who it reaches.** Any signup that trips the ceiling. That is now much rarer
than it was, which is precisely why it is worth fixing rather than forgetting:
it will next be seen by a real person, not by someone testing.

**What changed underneath it.** The 2/hour cap that made this common was fixed
on 2026-08-14 by moving to custom SMTP through Resend — see
[docs/SMTP_CONFIGURATION.md](docs/SMTP_CONFIGURATION.md). Note the ceiling was
**raised to 30/hour, not removed**: GoTrue enforces its own limiter independently
of the provider's allowance. So this path is still reachable.

**The fix.** A key in both `web/i18n/en.yaml` and `web/i18n/ar.yaml` under
`runtime.auth.*`, worded as "we could not send the confirmation email just now —
please try again shortly", plus mapping Supabase's message to it in `handlers.js`.
Small, and blocked on nothing.

---

### Email confirmation is disabled, so any address can register

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
implicitly: *is a confirmed address required to chat?* Supabase can enforce it,
or `auth_required` can, or nobody can — but it should be decided rather than
inherited. Note that re-enabling it is also the honest way to prove the new SMTP
path actually delivers, which has not yet been demonstrated.

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

### An account outside the newest 50 cannot be found or administered

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

### An account with no profile row can chat but cannot be administered

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
are *visible* as a broken state rather than invisible. The second is the more
honest surface and the larger change. Backfilling first is not wrong, but doing
only that leaves the class of bug intact: the console would still silently omit
any future account in this state.

---

### A combined or no-op account change is recorded under a misleading name

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

---

### A disabled reader is not told until they ask a question

**Where:** `Services.getIdentity` (`static/js/modules/services.js:328`) returns
`null` for both 401 and 403, and `static/js/app.js:218` uses it only to decide
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

### Know what people actually ask — without reading anyone's conversation

**Where:** nothing records question text today. `ConversationStore`
(`web/services/conversation_store.py`) holds turns in RAM, TTL 3600s, LRU 500,
keyed to a cookie — so the record of what was asked dies within the hour. The
sidebar's suggested questions are hand-curated in `faq.yaml`, categorised and
translated, and were written by guessing at what readers want.

**Why it is wanted.** Two things at once: know which questions recur, and turn
that into a cheaper, faster answer. Put the genuinely common questions in the
sidebar and a large share of traffic converges on a small set of answers.

**The mechanism matters more than the goal here, so it is worth being exact.**
The obvious route — let an administrator read conversations and notice the
patterns — is both more invasive and worse at the job than the alternative.
Frequency is an aggregate question: it needs the *text* of what was asked, not
who asked it. A table of `(asked_at, lang, scope, question_text, cited_count)`
with **no `user_id` column at all** answers "what are the twenty most common
questions this month" completely and exactly, in one `group by`, forever — while
reading transcripts answers it approximately, by hand, and only for as long as
someone keeps doing it.

Leaving identity out is not only a privacy posture, it is the thing that makes
the table cheap to keep: with no reader attached there is no retention deadline,
no disclosure to write, and no question about who else may be granted admin
later. If "how many *distinct* people asked this" is ever needed, a per-period
salted hash gives that without storing who.

**The cost saving is real but not where it looks.** Two different caches get
conflated, and only one of them pays:

- **OpenAI prompt caching** discounts a repeated *prefix*, and the prefix here is
  `BASE_SYSTEM_MESSAGE` + retrieved passages + the question. The system message
  alone is **246 tokens** (measured with `o200k_base`), well under the ~1024-token
  floor at which caching engages — so nothing is cached on the strength of the
  system prompt. The prefix only qualifies once passages are included, and those
  are identical only when the question is identical. So repeated questions *do*
  hit, which is the intuition behind putting them in the sidebar. The cache also
  goes cold after a short idle window unless `prompt_cache_retention` is set.
- **An answer cache in this app** — normalised question + language + model +
  **index version** → the stored answer and its source payload — makes no API
  call at all. That is the whole bill rather than a discount on part of it, and
  it is also the latency win: an instant answer instead of a stream.

**This prompt is input-heavy, which decides how much either is worth.**
`max_context_results: 8` at `chunk_size: 5000` characters puts roughly 10,000
input tokens against a few hundred output tokens on a typical answer. On
`gpt-4o-mini`'s 1:4 input:output pricing that makes **input around 80% of the
cost of an answer** — so prefix caching is worth substantially more here than on
a chat-shaped workload, and the two caches are closer in value than the "one is a
discount, one is free" framing suggests. Any decision resting on this should
re-measure rather than trust these figures: `max_context_results` is
operator-adjustable from the console, and doubling it moves the ratio.

So the answer cache is still the feature and the sidebar is how traffic is
steered into it — but at volume, prefix caching on the repeats is not a rounding
error either. Both want the question log first, and neither wants transcripts.

**Scale is what makes this worth building at all.** At three accounts it saves
nothing worth the code. The arithmetic only turns at volume, and it turns hard:
the same per-answer cost against a thousand readers asking a handful of questions
a day is the difference between a rounding error and a monthly bill someone
notices — more so on a frontier model, where the same prompt costs roughly ten
times what it does on `gpt-4o-mini`. **And money is not the binding constraint.**
This deployment runs `--workers 1 --threads 8` with an in-RAM FAISS index and a
sentence-transformers model, because conversation state is process-local. At that
scale the scarce resource is that single worker, and a cache hit skips embedding,
FAISS search, TF-IDF, and fusion as well as the API call. The cache relieves the
bottleneck that actually binds, which is a better argument for it than the bill.

**What it would disturb — and this is the real cost.** A cached regulatory
answer is a *stale* regulatory answer the moment the corpus changes, and
PRODUCT.md's first principle is that provenance is the product. So the cache key
must include the index build identity and every entry must be invalidated when
the index is rebuilt — a cache that outlives its evidence is worse than no cache,
because it answers confidently from a document that no longer says that. There is
no index-version identifier surfaced anywhere today; that is net-new and is the
prerequisite, not a detail.

The rest is smaller: writing a question log on the request path must not be able
to fail a request (best-effort, unlike quota, which must not be), and promoting a
logged question into the sidebar means translating it — `faq.yaml` is bilingual
and a question logged in English has no Arabic twin. That is a human step, which
argues for the console surfacing candidates for an operator to accept rather than
the sidebar populating itself.

**Deliberately narrower than what was asked.** The original framing was to review
reader transcripts for analysis. Transcript browsing is declined here on two
grounds: it depends on conversation persistence, which does not exist yet (see
below) and is the largest deferred item in the admin plan; and it buys a worse
dataset at a much higher privacy cost than a question log that answers the same
question better. If per-reader context is ever genuinely needed — a specific
complaint to investigate — the narrow form is a reader-initiated *answer receipt*
they can share, not a browsing surface for everyone.

**Open questions.** Whether the log stores the raw question or a normalised form
— readers paste identifying details into questions, and a regulatory question can
name a product and a company. Some normalisation or truncation before storage may
be wanted, which trades exactness for safety. And whether "same question" is
string equality after normalisation or embedding similarity — the second catches
far more repeats and can also collide two questions that deserve different
answers, which on a regulatory surface is the more expensive mistake.

---

### Account detail view in the console

**Where:** `/admin` People renders one row per account — email, role, standing.
`public.profiles` already holds `full_name`, `organization`, `specialization`
and `preferences`, and `auth.users` holds `created_at`, `last_sign_in_at` and
`email_confirmed_at`. None of it is shown.

**Why it is wanted.** An operator deciding whether to disable an account is
currently deciding from an email address. The data that would inform that
decision is already stored and already reachable by the service role — the
console simply never asks for it. It also gives the audit log somewhere to
land: "what else happened to this account" is a per-account question and there
is no per-account page to ask it on.

**What it would disturb.** Little structurally — a route, a panel, and the
existing bearer-only gate. Two things need deciding rather than defaulting. It
is a new bilingual surface with mixed Latin/Arabic content and machine
identifiers, so it needs `<bdi dir="ltr">` discipline and the `page.admin.*` /
`runtime.admin.*` parity test. And it draws the line that the entry above is
about: profile fields and sign-in timestamps are operational data and belong
here; what the person *asked* is not, and does not.

---

### Ending a session, as distinct from disabling chat

**Where:** `admin_set_user_flags` sets `profiles.is_disabled`, and
`auth_required` (`web/api/app.py:351`) refuses new requests with 403
`account_disabled`.

**Why it is wanted.** The flag is named accurately for what it does and that
naming is deliberate — but it means the console has no answer to an actual
incident. A disabled account keeps its Supabase access token until it expires,
keeps its refresh token indefinitely, can still sign in, and can still reach
PostgREST directly with the published anon key for anything RLS permits. If
credentials are believed compromised, "disable chat" is not the response.

**What it would disturb.** This is the first console action that reaches outside
Postgres, which is precisely why the audit design already anticipates it: a
database mutation and its audit row go in one transaction, but an Auth Admin call
cannot, so it needs the intent-then-outcome shape — write the intent, perform the
action, record what happened. `auth.admin.signOut(jwt, 'global')` revokes refresh
tokens; banning is a separate `updateUserById({ ban_duration })`. Both are
irreversible in the sense that matters (the reader is signed out of every device
immediately), so this is the strongest case in the console for explicit
confirmation — and `DESIGN.md:278` gives it no red button to lean on, by design.

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