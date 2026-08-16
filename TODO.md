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

### ~~A transient Supabase outage signed readers out~~ — FIXED 2026-08-15

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
administrator they were signed out *and* destroyed their server-side session:
the stored access token, the email, and the admin render hint. The credential in
their hands was valid throughout. The same branch also caught a missing
environment variable, a provider response in an unexpected shape, a GoTrue
rate limit, and any bug in identity resolution, and blamed the reader's
credential for all of them.

**Why it survived.** The rule was already written down one layer lower —
`web/api/admin.py` answers 503 when the *profile* store cannot be read, because
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

### ~~There is no password reset~~ — FIXED 2026-08-14

**Resolved.** Reader-facing recovery ships: a *forgot password* affordance in the
login pane, `POST /auth/recover`, and a third view in the shell that receives the
callback and calls `auth.updateUser({ password })`. Proven end to end against the
live project — `midoxp@yahoo.com` went from never-signed-in and unconfirmed to
confirmed and signed in through the real email.

Three things the original entry did not know, kept because they cost a day to
learn and are invisible in the finished code:

- **Recovery mail is sent server-side, not from the browser.** A browser-issued
  `resetPasswordForEmail` under `flowType: 'pkce'` stores its code verifier in
  *that* browser's `localStorage`, so opening the mail on a phone can never
  complete the exchange. A server-generated link returns tokens in the fragment
  instead, which any device can consume.
- **`flowType: 'pkce'` silently drops that fragment.** Measured against
  gotrue-js 2.62.2: no session, no `PASSWORD_RECOVERY`, and no error, because
  `_initialize` swallows the "Not a valid PKCE flow url" it raises. The client is
  built with `'implicit'` when the recovery marker is present and `'pkce'`
  otherwise.
- **The `?recovery=1` marker is load-bearing twice.** Supabase emits `SIGNED_IN`
  *before* `PASSWORD_RECOVERY` (supabase/auth-js#349), so the event cannot be
  trusted to open the view; and the marker has to be readable before the client is
  constructed, because it selects the flow type.

**Update 2026-08-16 — the admin half has shipped too.** `POST
/admin/api/users/<user_id>/reset-password` (`web/api/admin.py:265-340`) sends
the same recovery link from the account detail view via `#account-send-reset`
(`static/js/admin/ui.js:956-959`, wired through
`services.sendPasswordReset(userId)` in
`static/js/admin/handlers.js:287-312` and `static/js/admin/services.js:132-133`).
Tested in `web/tests/test_admin_users.py:461-530` and
`web/tests/test_admin_browser.py:658-705`. See *Account detail view* under
Planned work for what else that page does and does not do yet.

---

### (original entry, kept for the cost it records) There is no password reset, so a forgotten password is an unrecoverable account

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
*to the new address* rather than `email_confirm: true` — but building that
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
shipping: chained with the *existing* reset-password button, an unconfirmed
email change is a complete impersonation primitive — change the victim's
email, click reset, they never see it coming (this is exactly how Twitter's
2020 breach worked). The mitigation built: `change-email`, uniquely among
the three auth-admin actions on this page, refuses to target the operator's
own account. `revoke-sessions` and the existing `reset-password` still do
not, on the same reasoning `set_user_flags`'s self-change guard already
established — the two also worth turning on but not yet done: enabling
Supabase's `GOTRUE_MAILER_NOTIFICATIONS_EMAIL_CHANGED_ENABLED` project
setting (notifies the *old* address as tamper-evidence — external config,
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
*Account detail view* below.

---

### ~~The signup rate-limit message reaches the reader as raw English~~ — FIXED 2026-08-14

**Resolved.** `runtime.auth.tooSoon` and `runtime.auth.emailUnavailable` exist in
both catalogues and are mapped in `ErrorHandler.formatAuthError`
(`static/js/modules/dom.js`), which is the only path signup errors take. Recovery
reaches the same two strings by status code from our own endpoint rather than by
substring, because it does not go through Supabase directly.

Worth recording: this was *claimed* fixed when the keys were added, and was not —
the keys sat in both languages with no mapping, exactly the dead-string failure
this file already records for `runtime.profile.*`. It was caught by an audit
asking whether every added key was actually reached. There is now a test that
fails if any `runtime.auth.recovery.*` key is drawn by nothing.

---

### (original entry) The signup rate-limit message reaches the reader as raw English

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

### ~~Email confirmation is disabled~~ — RESOLVED 2026-08-14 (outside this repo)

**Turned back on at 12:05:17Z**, confirmed from `auth.users`: `mohifouda@gmail.com`
has `confirmation_sent_at` set, unlike the auto-confirmed `midoxp@live.com` whose
value is null. The open question the old entry left — *is a confirmed address
required to chat?* — is answered and needs no code: GoTrue refuses to issue a
session for an unconfirmed address, so `auth_required` never sees a token to
accept. Enforcement sits at the session boundary, which is the strongest place
available.

One consequence this created and password recovery then cleared:
`midoxp@yahoo.com` had `email_confirmed_at = null` and could no longer sign in at
all. Completing a recovery confirms the address as a side effect, which is how
that account was settled.

---

### (original entry) Email confirmation is disabled, so any address can register

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

### An account outside the newest 50 cannot be found or administered — HALF FIXED 2026-08-15

**Update.** The **search box now exists**: `#people-search` in `admin.html`,
debounced in `initPeopleTab`, passing `q` through to the RPC that always
accepted it. So an account outside the newest 50 can now be *found*.

**The pager was not built.** `limit` and `offset` are still never sent, so a
search matching more than 50 accounts silently shows the first 50 and says
nothing about the rest — which is the more dangerous half of this entry, because
a truncated result set looks exactly like a complete one. `total` is returned
and rendered as a bare `N / M` line; that is a count, not a control. Closing
this properly means a next-page control, or a stated "showing N of M" that reads
as a limit rather than as a total.

The original diagnosis follows.

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

### ~~An account with no profile row can chat but cannot be administered~~ — FIXED 2026-08-16

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

### (original entry, diagnosis superseded above) An account with no profile row can chat but cannot be administered

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

### ~~A combined or no-op account change is recorded under a misleading name~~ — FIXED 2026-08-16

**Resolved.** `admin_set_user_flags` (migration
`20260816121335_diff_based_admin_user_flags_audit.sql`) now derives its audit
rows from the diff between before-state and after-state rather than from
whichever fields the request carried, exactly as the entry below recommended
after the sibling RPC set the precedent. Two behaviours changed:

- A patch touching both `role` and `is_disabled` now writes **two** audit rows
  — `user.role_change` and `user.disable`/`user.enable` — rather than
  dropping one.
- A field sent back at the value it already holds writes **no** row for that
  field; a fully no-op call writes nothing at all.

Both are covered live:
`test_a_single_call_changing_both_role_and_standing_records_both` asserts the
two-row split (`web/tests/test_admin_users.py:233`), and
`test_a_no_op_user_flags_edit_records_nothing` /
`test_a_partial_no_op_records_only_the_field_that_moved`
(`web/tests/test_admin_users.py:261,277`) assert the no-op case. The in-memory
test double in `web/services/admin_store.py:600-625` mirrors the SQL shape
rather than reimplementing it separately, so the two cannot drift.

---

### (original entry, kept for the cost it records) A combined or no-op account change is recorded under a misleading name

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
So this entry is now a *port*, not a design problem: `admin_set_user_flags` is
the one still deriving its name from whichever field the request happened to
carry. Copy the shape, do not reinvent it.

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
straight to Supabase's `profiles` table; `handleAuthFormSubmit` (signup leg)
in `handlers.js:164-200` and `Services.signup` in `services.js:277-282`; the
`#signup-pane` and `#profileModal` forms in `web/templates/index.html` (lines
228-258 and 271-321); `handle_new_user` trigger and `admin_update_profile` RPC
in `supabase/migrations/`; `loadProfileWithTimeout` in `static/js/app.js` (lines
29-49), fed by `API_TIMEOUT` / `RETRY_MAX_ATTEMPTS` / `RETRY_DELAY_INITIAL` in
`static/js/modules/config.js`; the two `profile-button*` triggers in
`web/templates/partials/_sidebar.html` (lines 59-62); and
`AppState.state.userProfile` in `static/js/modules/state.js`. The catalogue
already carries `runtime.profile.*` keys (`loadFailed`, `saveFailed`, `saved`)
in both `web/i18n/en.yaml` and `web/i18n/ar.yaml` — no JS module reads them.

**Why it is wanted.** Three things converge on this surface:

1. **Identity fields need structuring.** `full_name` is currently a single
   free-text field that gives no clean way to address readers politely or sort
   by family name. It wants a split into `first_name` and `family_name`. In
   addition, collecting numeric `age` provides demographic context for
   regulatory queries without requiring sensitive birthdates.
2. **Registration captures nothing today.** Signup takes only email and password,
   leaving `profiles` initialised with empty strings for everything else until
   someone finds the profile modal. Capturing `first_name`, `family_name`, and
   `age` during signup passes them via user metadata into `handle_new_user`, so
   an account starts with real identity data.
3. **The profile modal strains in visible ways.** The form is seeded from the
   *startup snapshot*: `loadProfileWithTimeout` fills `AppState.userProfile` once
   at sign-in (`static/js/app.js:207`), and `handleProfileButtonClick` only calls
   `Services.getProfile` on a cache miss (handlers.js:655-678) — so the modal
   shows whatever the page captured on load, never a fresh read. The theme radios
   never reflect the stored preference: both `populateProfileForm` (ui.js:625)
   and the empty-profile reset (handlers.js:895) check `ThemeManager.getCurrent()`
   — the live `data-bs-theme` attribute — not `profile.preferences.theme`, so a
   reader who saved Dark is shown their *current* theme, not their saved one. And
   the surface is silently English-only while the `runtime.profile.*` keys
   written for exactly this sit unused.

**Two live bugs to fix while you are in here.** Both are shipped today, both
were confirmed by reading the code, and neither has a test that would catch it —
which is why they are written out rather than left in the prose above.

1. **The theme radios ignore the saved preference.** `populateProfileForm`
   (`static/js/modules/ui.js:625`) and the empty-profile reset
   (`static/js/modules/handlers.js:895`) both select the radio matching
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
   `static/js/modules/handlers.js` — 841, 862, 866, 877 and 901 — pass literals
   to `showProfileError`/`showToast`, while
   `runtime.profile.{loadFailed,saveFailed,saved}` sit in *both*
   `web/i18n/en.yaml` and `web/i18n/ar.yaml` and are read by no module. An
   Arabic reader gets English on this one surface.
   `test_arabic_catalogue_covers_every_runtime_key` cannot catch this: it
   checks that Arabic has every key English has, and both catalogues have
   these — they are simply never used. Note there are five sites and only
   three keys, so translating them is not a one-to-one mapping; the session-
   expired (841) and save-failure (866) messages need keys that do not exist
   yet.

**What it would disturb.** Every profile behaviour is pinned by tests that name
it. `web/tests/test_profile_theme_integration.py` runs three browser tests —
cached form fill, theme-persists-through-save, and the `updateProfile` /
`getProfile` wire contract (`test_profile_service_contracts`) — entirely against
the `SUPABASE_BROWSER_MOCK` `from('profiles')` chain in
`web/tests/conftest.py`, a chain that currently asserts the
`{id, full_name, organization, specialization, preferences}` shape. Changing
`public.profiles` to replace `full_name` with `first_name`, `family_name`, and
`age` requires migrating existing rows, updating `admin_update_profile` and
`handle_new_user`, and adjusting the admin account detail view that reads
profile columns. `test_frontend_architecture.py::test_handlers_own_user_facing_service_failures`
pins that `ErrorHandler.showProfileError` stays in `handlers.js`.
`test_frontend.py::test_login_and_logout_flow` asserts `#profile-button` is
visible after sign-in. Any new `page.auth.*`, `page.profile.*`, or `runtime:`
strings must ship in both YAML files (`test_arabic_catalogue_covers_every_runtime_key`
fails if Arabic lags) and any new CSS must use logical properties
(`web/tests/test_css_contract.py`); any commit touching CSS or JS bumps
`ASSET_VERSION` in `web/api/app.py`.

**Open questions.** Is the profile a better modal or its own server-rendered
page, and if a page, how does it coexist with the landing/auth shell and the
`?testing=true` demo path? Should profile data keep flowing browser-side through
the anon-key Supabase client, or move behind an authenticated Flask route? And
for the future newsletter plan: when integrating Beehiiv, should the opt-in
checkbox live in `preferences.newsletter` on `public.profiles` and sync via
a server-side webhook/background worker, or sync directly at signup/profile save?

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

### Account detail view — the home for everything done to one account — MOSTLY BUILT 2026-08-16

**Decided 2026-08-14:** this is where per-account management lives. Email
changes, password recovery, role, chat access and session revocation all land
here rather than being scattered across the People table. The entries above that
describe those actions individually describe *what* to build; this describes
*where*, and they should not grow separate surfaces.

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

**The dependency worth knowing before sequencing.** The admin's *send password
reset* button and the reader's *forgot password* link need the same thing: a
landing view that receives Supabase's recovery redirect, handles the
`PASSWORD_RECOVERY` event, and calls `auth.updateUser({ password })`. Whether the
link comes from `resetPasswordForEmail` or from `auth.admin.generateLink({ type:
'recovery' })`, it returns to the same place. So the reader-facing reset is not a
detour on the way to this page — it *is* the hard half of one of its buttons, and
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

### ~~Ending a session, as distinct from disabling chat~~ — BUILT 2026-08-17, pending a production migration

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

**What is still open, deliberately.** The new `admin_get_user` SQL
(`supabase/migrations/20260817120000_admin_get_user_email_verified.sql`)
has been dry-run against the live project inside a rolled-back
transaction — proven syntactically and semantically correct against real
data — but not yet applied for real. Both routes work today off the
*old* `admin_get_user` shape (missing `email_identity_verified` just
degrades to "Unknown" in the UI, not an error), so this is safe to apply
whenever convenient rather than blocking. Covered by
`web/tests/test_admin_users.py` and `web/tests/test_admin_browser.py`
(65/65 admin browser tests passing, including the new dual-dialog
change-email flow).

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
an account, which is only safe if the *account*, not the browser, becomes the
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

---

### ~~Consolidate every documentation file into `docs/`~~ — FIXED 2026-08-16

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

### ~~The memory-bank docs are stale, and the review cannot trust them~~ — FIXED 2026-08-16

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

### ~~The `.env` file carries keys nothing reads~~ — FIXED 2026-08-16

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

---

### ~~Stale claims in README, and a one-time orphan-file sweep~~ — FIXED 2026-08-16

**Resolved, both halves.** The README half was fixed earlier this session
(see the `.env` entry above). The orphan-file sweep — the half this entry
left open — is now done too: every git-tracked module under `web/` (32
files) and `static/js/` (22 files) was checked for a real cross-file
reference, not just presence in a directory.

**Method, since the risk was overreach.** A name match alone isn't proof of
use — the risk this entry itself named was a file that's actually loaded by
glob (`MODULE_FILENAMES`/`ADMIN_MODULE_FILENAMES` in `web/api/app.py:222-235`
publish *every* file under `static/js/modules/` and `static/js/admin/` into
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

### ~~The docs quote three different `ASSET_VERSION` values, none of them current~~ — FIXED 2026-08-16

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

### (original entry) The docs quote three different `ASSET_VERSION` values, none of them current

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

### Every authenticated request pays a network round trip to verify its token

**Where:** `web/api/app.py`, `_authenticate_request` calls
`supabase.auth.get_user(token)` on every request that is not the public
landing. Surfaced 2026-08-15 by the audit of the outage bug above.

**What is wrong.** Nothing is cached. Opening the console costs **four** GoTrue
verifications — identity, settings, users, audit — before an operator has
clicked anything, and opening one account costs **two more**. There is an
identity-flags cache (`web/services/identity_cache.py`, 30s TTL) but it covers
the *profile* lookup that follows, and console requests deliberately pass
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
the same trade as the identity-flags cache, which only ever caches *flags* for
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