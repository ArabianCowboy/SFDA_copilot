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

### Arabic readers get no chat history on the non-streaming path

**Where:** `_truncate_chat_history` in `web/api/app.py` (~line 245), against
`MAX_SESSION_CHAT_HISTORY_CHARS = 3_500`.

**What is wrong.** The cap is measured with `json.dumps(truncated_history)`,
which defaults to `ensure_ascii=True` and escapes every non-ASCII character to
`\uXXXX` — six characters where the reader typed one. A single Arabic
question-and-answer pair of ~950 characters measures ~4,700 against a 3,500
budget, so the `while` loop drops the oldest pair, measures again, and keeps
going until the list is empty. The Arabic reader does not get a shortened
history; they get **none**.

Measured directly:

```
actual characters in one pair:            948
json.dumps length (what the cap measures): 4704
json.dumps(..., ensure_ascii=False):       1019
```

**Who it reaches.** Only `/api/chat`, the blocking fallback — the path a browser
without streaming bodies takes. `/api/chat/stream` keeps its history in the
`ConversationStore` and is unaffected. So this is invisible on a current desktop
browser and total on an old one, which is why it went unnoticed.

**How it was found.** Not by a bug report. A cookie-size guard added alongside
the New chat undo work — since reworked into
`test_the_cookie_never_carries_two_histories` — was parametrised over English
and Arabic, and the Arabic case could not reach its own precondition: the
history it built came back empty.

**The fix, and why it was not made here.** Measuring with
`ensure_ascii=False` is a one-line change and is almost certainly right: the
budget is meant to bound the session cookie, the cookie is compressed and signed
after this point, and `ensure_ascii` affects neither. But it silently changes how
much history *every* reader is handed on the main chat path — more turns of
context per question, in both languages — which is a behavioural change to the
product's answers, not a bug fix. It wants its own commit, its own before/after
on answer quality, and a decision on whether 3,500 is still the right number once
it means what it says.

**When it is fixed:** add an Arabic case to the blocking-path history tests in
`web/tests/test_new_chat.py` — an Arabic exchange should survive a round trip
through the session at all, which today it does not.

---

### The session cookie can be blown by one history of low-entropy content

**Where:** `MAX_SESSION_CHAT_HISTORY_CHARS = 3_500` in `web/api/app.py`, applied
by `_truncate_chat_history` (and by `_truncate` in
`web/services/conversation_store.py`).

**What is wrong.** The cap counts **JSON characters**, but the thing that has to
fit is the **serialized, signed, compressed session cookie**, and browsers
silently drop a cookie over ~4,093 bytes. Losing the cookie costs the reader
their *session*, not just their history. Prose compresses ~3x so a 3,500-char
history lands around 1KB and nobody notices — but content that compresses badly
does not, and this product invites it: a pasted table of batch numbers,
submission IDs, signed URLs, OCR output, a list of product codes.

Measured with incompressible content, one history produced a **4,544-byte**
cookie and Werkzeug logged `the 'session' cookie is too large`.

**Who it reaches.** `/api/chat` only, the blocking fallback — the streaming path
keeps history server-side.

**What this is NOT.** It is not caused by the New chat undo work. Setting a
history aside was made cookie-neutral by `/api/chat` dropping
`prev_chat_history` whenever it records a turn, so the cookie carries at most
one history at any moment — pinned by
`test_the_cookie_never_carries_two_histories`. This entry is the *pre-existing*
single-history case underneath that.

**The fix.** Bound the serialized session rather than the JSON string: either
measure what the session interface will actually emit and trim until it fits, or
stop keeping blocking-path history in the cookie at all and give `/api/chat` the
same server-side `ConversationStore` the streaming path uses. The second is the
better shape and removes this whole class of problem — `adopt_cookie_history`
already exists for exactly that migration — but it changes where the blocking
path's memory lives, so it wants its own commit.

---

## Planned work

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
surface is silently English-only: the profile-toast strings in `handlers.js`
(lines 620, 635, 650) are hardcoded literals while the `runtime.profile.*` keys
written for exactly this sit unused — an Arabic reader gets English error copy
on this one surface. The immediate reason to touch it is downstairs: the admin
controls (below) will need somewhere to live, and nothing but this modal exists
to hang them from.

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

### Refactor authorization into two roles: admin and user

**Where:** `auth_required` in `web/api/app.py` (lines 203-242) is the only gate
in the app: every authenticated route — `/api/chat/stream`, `/api/chat`,
`/api/conversation/reset`, all decorated `@auth_required` — passes through it.
Its TESTING-mode bypass (lines 208-213) admits any request whose
`Authorization` header contains `fake_token` and binds it to
`"test@example.com"`. Below that, the only identity handling is
`_bind_session_to_identity` (lines 183-201) — the per-request check that calls
`purge_conversation_state()` in `web/api/auth.py` (lines 31-54) when the reader
changes — and `session.update`, which stores only `supabase_access_token` and
`user_email` (app.py:235). The auth blueprint (`signup`, `login`, `logout` in
`web/api/auth.py`) returns `{id, email}`; nothing in the repo ever reads a role.
The profile projection (`Services.getProfile`, services.js:302) selects no role
field either.

**Why it is wanted.** Every authenticated reader is today equivalent — the same
token gate, the same surface, the same rights, whatever the account. There is no
notion of privilege anywhere: no role read from the Supabase `user` object that
`auth_required` already resolves, no role column in the `profiles` projection, no
endpoint or UI that lets an operator do something a reader cannot. The two
entries that follow (admin operational control, per-user sessions) both need this
distinction underneath, and a regulatory instrument needs the vocabulary for
"who may stop a user or change the model" before it can exercise it.

**What it would disturb.** The decorator is exercised through nothing but the
TESTING bypass: `test_auth_routes.py`, `test_session_isolation.py`,
`test_new_chat.py`, `test_chat_api.py` and `test_chat_stream.py` all
authenticate with the literal header `Bearer fake_token` and expect 200s — a role
check has to ride inside the same bypass or the whole server suite goes 401. The
browser mock in `web/tests/conftest.py` (`SUPABASE_BROWSER_MOCK`) seeds a user
with no role, and `test_frontend.py` (`test_login_and_logout_flow`,
`test_testing_mode_bypasses_auth`) pins what a signed-in reader sees. A role
marker cached in the Flask session must invalidate exactly where
`_bind_session_to_identity` purges: an elevated flag riding the cookie onto a
shared machine's next reader is the precise leak that function exists to close,
so the role needs the same rotation discipline as `conv_id`. And `auth_required`
serves two masters — page requests (`is_page_request` redirects to `index`,
app.py:216-219) and API requests (a 401) — so an admin-only route has to decide
which response shape it wants, and the landing page's own authentication signal
(`is_authenticated=bool(session.get("user_email"))`, app.py:558) does not
distinguish roles.

**Open questions.** Where the role lives: a `profiles` column (an out-of-repo
Supabase migration plus RLS — there are no `.sql` files in this repo to point
at) versus something read off the Supabase auth user's `app_metadata`, which
`auth_required` already has in hand. Whether the gate is one decorator that tags
the session, or a second `admin_required` composed on top — and how either
behaves in TESTING mode where the "user" is a literal string
`"test@example.com"` with no database row. What a mid-session revocation does to
a session that already holds the elevated marker.

---

### Give admins operational control

**Where:** The model is a static, deploy-time constant. `web/config.yaml` sets
`openai.model: gpt-4o-mini` (with `temperature: 0.1` and `max_tokens: 16384`);
`OpenAIHandler.__init__` reads it once into `self.model`, alongside
`self.max_tokens`, `self.temperature` and `self.max_context_results`
(`web/services/openai_app.py` lines 146-149), and derives
`self.tokenizer = tiktoken.encoding_for_model(self.model)` (line 172);
`self.model` is what `stream_response` and `generate_suggestions` pass to the
OpenAI client (lines 268-272, 330-333) and what `/api/chat/stream` echoes to the
browser in its `meta` frame — `"model": getattr(handler, "model", "unknown")`
(`web/api/app.py:681`); the testing double mirrors the same read (app.py:382).
No user-disable concept exists: `auth_required` trusts whatever
`supabase.auth.get_user(token)` resolves (app.py:221-235), and no `profiles`
field for a disabled flag is selected or consulted anywhere. There is no admin
endpoint and no admin surface; the only chrome a signed-in reader has is the
account block in `web/templates/partials/_sidebar.html` and the profile modal
(the entry above).

**Why it is wanted.** The chatbot's model is changed by editing YAML and
redeploying — there is no in-app path for an operator to fail a degraded model
over to a cheaper or heavier one, and no way to cut off a specific account. The
brief treats model switching and disabling a user as a starting list, not a
closed one: the entry is about the class of thing, operational acts that a
reader cannot, and should not, be able to perform.

**What it would disturb.** A runtime model switch breaks an invariant
`OpenAIHandler` keeps for itself: the tokenizer is bound to the model at
construction and `_log_token_counts` depends on it, while `max_tokens: 16384`
is pinned to gpt-4o-mini's ceiling (config.yaml:64) — swapping `self.model`
without a rebind silently misreports token counts and can exceed a smaller
model's cap. Tests pin the model by hand: `handler.model = "gpt-4o-mini"` in
`test_session_isolation.py:46`, `test_new_chat.py:57` and
`test_chat_stream.py:42`, and every SSE fixture in conftest.py carries
`"model": "mock"` in its `meta` frame — a configurable or per-request model has
to decide what those become. Disabling a user means a check inside
`auth_required`, which is the same decorator the whole suite authenticates
through, and the mock user in `test_auth_routes.py` has no disabled flag. Admin
endpoints are new, authenticated, *gated* API surface that does not exist and
must sit behind the role from the entry above — which also does not exist — so
the honest cost of this feature is the cost of two. Any model change touches the
answer-quality contract `BASE_SYSTEM_MESSAGE` and the citation scheme in
`web/services/openai_app.py` are tuned to current behaviour, and the change is
disclosed to the reader through the `meta` frame already. Everything new on
screen is bilingual (`test_arabic_catalogue_covers_every_runtime_key`),
logical-property CSS (`web/tests/test_css_contract.py`, zero violations today),
and an `ASSET_VERSION` bump — no bundler means the build-step temptation should
be counted as behind this too.

**Open questions.** Where the selection is stored so the change is durable:
config.yaml is read once at process start with no live-reload seam, so a
per-instance or per-account record is new persistence and sits adjacent to the
saved-sessions work below. Whether the admin's choice is global to the instance
or per conversation — per-conversation would have to ride `ConversationStore`
entries or the `meta` frame. What "disable" means at the boundary — reject the
token outright, or consult a flag alongside — and what the disabled reader is
shown. And whether admin controls belong in the reader-facing modal or a
separate admin surface, and how that surface is reached without a route change.

---

### Save chat sessions per user

**Where:** Today a conversation is keyed to a cookie, not to an account.
Server-side: `ConversationStore` (`web/services/conversation_store.py`), created
in `_register_routes` as `app.config["conversations"] = ConversationStore()`
(`web/api/app.py:513`) — process-local, TTL 3600s, LRU-bounded to 500, keyed by
the opaque `conv_id` that `handle_chat_stream` invents and parks in the Flask
session (app.py:668-671). The non-streaming path never touches the store: its
history rides the cookie as `session["chat_history"]`, capped by
`_truncate_chat_history` / `MAX_SESSION_CHAT_HISTORY_CHARS = 3_500` (app.py:120,
245-255), and `handle_conversation_reset` rotates `conv_id` → `prev_conv_id` and
`chat_history` → `prev_chat_history` to keep the undo honest (app.py:846-933);
`adopt_cookie_history` is the one-time cookie→store migration
(`conversation_store.py:95-108`). All of it is torn down by
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
reader picks up the same cookie. The cookie is already at its limit: the two
bug entries above in this file describe how the 3,500-character cap exists
because the serialized cookie is ~4KB. Real persistence means a database, and
this repo has none of it ready: there are no `.sql` migrations, and the only
table named anywhere is `profiles`, read and upserted from the browser with no
Flask route in between. Schema, RLS, and a server-side path for reads and writes
are all net-new. The reset/undo design threads through every history test —
`test_new_chat.py` end to end (rotation, the `prev_*` keys,
`test_the_cookie_never_carries_two_histories`), `test_chat_stream.py`
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