# Fixing the `/auth/login` rate limit

STATUS: PARTIALLY BUILT 2026-09-09 — Option A shipped as a one-release `410 Gone`
tombstone, not yet as the bare deletion. See §10 for what landed and what is still owed.
Written 2026-09-06 against commit `f4d8976`; revised 2026-09-06 after an
adversarial review and a measured adjudication of that review; **rebased
2026-09-08 onto `ade91f4`**, with every citation renumbered and every
measurement re-taken (see §8); implemented 2026-09-09 (§10).
Tracks TODO.md's
[`POST /auth/login` is a 410 tombstone pending deletion](../TODO.md#post-authlogin-is-a-410-tombstone-pending-deletion)
— an entry this work retitled, because its original title ("`auth_bp` carries no rate
limit, so `/auth/login` is unlimited") stated a premise §0 disproves.

Every measurement below was taken against this working tree. Where a claim is
inference rather than measurement it says so. Where this revision overrules the
review, or the review overruled v1, the text says which and why — including the
two places v1 itself was wrong.

---

## 0. The entry's premise is wrong, and that changes the fix

TODO.md:73 says `/auth/login` is **unlimited**. It is not. Measured — an app built with
`create_app(testing=True, enforce_rate_limits=True)`, fourteen consecutive
`POST /auth/login`:

```text
LOGIN  : [401 ×10, 429, 429, 429, 429]
LOGOUT : [200 ×10, 429, 429, 429, 429]
flask-limiter - INFO - ratelimit 10 per 1 minute (127.0.0.1) exceeded at endpoint: auth.login
```

Flask-Limiter applies `default_limits` to any route that carries no explicit limit of its
own, and nothing exempts `auth_bp`. So today `POST /auth/login` is capped at
**200/day, 50/hour, 10/minute, per IP** (`web/config.yaml:114-116`,
`web/api/app.py:1821-1834`).

Two consequences, and they are the whole reason this plan is longer than one line:

1. **`/auth/logout` is already capped at 10/minute too.** `web/api/auth.py:28-29` argues
   the blueprint must stay unlimited because "a 5/minute ceiling on logout would be
   wrong". That comment describes an exemption that does not exist — logout has had a
   10/minute ceiling all along. The comment is not just imprecise, it is the reason
   nobody looked closer at login for a year.
2. **The naive fix makes login weaker, not stronger.** A route limit _replaces_ the
   defaults rather than stacking on them (`limit()` defaults `override_defaults=True`;
   `docs/ARCHITECTURE.md:375-378` already says so). Measured, on `/auth/recover` with its
   limit temporarily raised to `500 per minute`: **260 consecutive requests all passed**,
   where the 200/day default would have refused #201. So adding
   `login_api: "5 per minute"` the obvious way removes daily-window enforcement
   altogether and raises the nominal daily maximum from 200 to 7 200 — **36× the former
   daily allowance**, dressed up as a security fix. Stated precisely, because two
   reviewers read the earlier phrasing as conflating a burst limit with a daily one: a
   minute limit is _stricter_ than today for a burst (5 beats 10) and _absent_ for a day.
   The 260-request run proves the replacement, not that an attacker sends 7 200.

The same measurement means `POST /auth/recover` and `POST /auth/signup` **have no daily
or hourly Flask ceiling today** — each carries only its explicit 5/minute blueprint
limit. That is a live finding this plan surfaces, not one it creates, but **reframed
2026-09-08** after three reviewers pushed on the volume: the mail those endpoints send is
backstopped by GoTrue's project-wide ceiling of 30/hour and its 60-second per-address
interval (`docs/OPERATIONS.md:79-84`, `:97-98`), so 7 200 messages a day never leave.
The real exposure is worse in a dimension the earlier phrasing missed. At 5/minute a
single IP burns the **entire project's** 30/hour mail allowance in six minutes, denying
password-recovery and signup mail to every legitimate reader — which is precisely what
`web/api/app.py:2319-2323`'s own comment says the limit exists to prevent, at a number
that does not prevent it.

---

**Every `file:line` in sections 0 through 8 is against `ade91f4`, the tree this plan was
written for — that is, BEFORE the change section 10 records.** They were correct when
written and they are the right references for reading the diagnosis. They are the wrong
references for _executing_ anything now: the retirement moved `login()` and added twelve
lines to the module comment above it, so a range like section 2 step 1's
`web/api/auth.py:295-360` no longer bounds the function it names — following it literally
would delete the tail of `_signup_error_response` and the head of `recover()`. Section 10
carries the current numbers for the work that is still owed. Use those.

## 1. What is actually wrong with `/auth/login`

Ranked by how much a fix buys.

### 1.1 The IP key is not trustworthy, so no per-IP number on this route means anything

`ProxyFix` is applied only when `BEHIND_PROXY=true` (`web/api/app.py:1697-1712`,
`web/utils/config_loader.py:124-126`), which **defaults to false**
(`.env.example:43-45`). There is no trusted-proxy allowlist anywhere in the tree. The
nginx snippet the project documents (`README.md:100-110`, `docs/ARCHITECTURE.md:137-146`)
sets `proxy_pass` and `proxy_buffering off` and **no `X-Forwarded-For` header at all**.

Both reachable production states are wrong:

| State                                                                       | What `get_remote_address()` returns          | Effect on every IP-keyed limit                                                                                                                                                                                                                                                                                                                                                     |
| --------------------------------------------------------------------------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BEHIND_PROXY` left false behind nginx                                      | `127.0.0.1` for every request on earth       | One global bucket per scope. 10/minute is 10/minute **for the whole product** on every route that inherits the defaults, so one caller can deny login and logout to everyone. Corrected 2026-09-08: this does **not** reach chat or history, which carry explicit limits that replace the defaults and so hold their own separate buckets — the denial is per-scope, not app-wide. |
| `BEHIND_PROXY=true`, header not set by nginx or gunicorn reachable directly | whatever the caller put in `X-Forwarded-For` | Unlimited fresh buckets, one per forged header. No limit at all, and no error surfaces because Werkzeug silently falls back to `REMOTE_ADDR` when the header is absent.                                                                                                                                                                                                            |

`docs/security-hardening-plan.md:547-555` already declines to assert which state
production is in: "This repository cannot establish the live topology." Supabase's own
GoTrue README makes the identical point about its `/token` limiter — a trusted upstream
proxy header must be specified, "as client-supplied headers like x-forwarded-for are
spoofable."

**This gates the IP-keyed work only.** It is one question to the person who owns the
VPS, not an engineering task.

**Corrected 2026-09-08.** Earlier revisions said "nothing in §2 or §3 is worth shipping
before this is answered." That was wrong, and all three reviewers caught it
independently. Deleting the route (§2) is topology-independent: a deleted route reads no
address, consults no limiter key, and forwards nothing to GoTrue, so it closes §1.2,
§1.3 and §1.4 under either broken state. The same is true of B′ steps 3, 4 and 5, which
are input validation, response shape and logging. C1 gates exactly two things — B′ step
2 and C2 — because those are the only items whose behaviour depends on the key being
meaningful. Making C1 a blanket prerequisite turned an unowned, undated question into an
indefinite hold on fixes that are safe today.

**What the 2026-09-07 incident work changed here, and what it did not.** `a3a5d99`
(the incident plan's P8) flipped `load_dotenv(..., override=True)` to `override=False`
in both loaders, so the real environment now beats `.env`. That does not touch this
section's diagnosis — the default is still `false`, there is still no trusted-proxy
allowlist, and the documented nginx snippet still sets no header. It does make C1's
_remedy_ work: before it, a `BEHIND_PROXY=true` supplied by a systemd
`EnvironmentFile=` was silently overridden back to `false` by a `.env` copied from
`.env.example`, which ships the variable as an explicit `false` rather than a comment.
Setting it in the deployment environment would have appeared to do nothing.

The same commit added a startup warning naming every variable set in both places
(names only — several are secrets). That is a cheap way to get part of C1's answer out
of the logs rather than out of a conversation: if `BEHIND_PROXY` appears in that line,
someone has set it in both places and the two disagree.

### 1.2 The route launders the attacker's IP past GoTrue's own limiter

GoTrue rate-limits its `/token` password grant **per IP** (`GOTRUE_RATE_LIMIT_TOKEN_REFRESH`,
default 150 requests; the window is not documented in the source consulted). The review
claimed this variable governs only the refresh grant and that password grants use a
separate `GOTRUE_RATE_LIMIT_TOKEN_PASSWORD`, citing nothing — the upstream source says
otherwise (supabase/auth `internal/api/token.go` routes `case "password":` through the
`Token` limiter, and `internal/conf/configuration.go` states the password grant shares
the `RateLimitTokenRefresh` field). There is no `RateLimitTokenPassword` field in that
config. The v1 citation stands, with the window caveat stated exactly as measured.

Every browser sign-in on this product goes browser-direct
(`static/js/modules/services.js:375-380`), so GoTrue sees the reader's own address and
that limiter does its job.

`POST /auth/login` breaks exactly that. It forwards a stuffing run to GoTrue from the
VPS's single trusted IP, so the one limiter that can see the attacker no longer can.
Our route is not merely an unmetered door — it is an anonymising proxy in front of
someone else's working defence.

### 1.3 The response is an enumeration and information oracle

Nine distinguishable outcomes from `web/api/auth.py:295-360`. The ones that matter:

- **401 `"Invalid email or password"`** (`:356-357`) vs **401 `"Please confirm your email
address before logging in"`** (`:358-359`). Same status, different body — a caller
  distinguishes the two states on one request. **Scoped down 2026-09-08:** this is not
  a general existence oracle for an arbitrary password. GoTrue returns
  `email_not_confirmed` only after the password check passes (inference from GoTrue's
  ordering, not verified here), so reaching that branch requires already holding valid
  credentials. What it discloses is narrower and still worth removing — that a _correct_
  credential pair belongs to an unconfirmed account — but the earlier phrasing claimed
  more than the code supports.
- **401 `{"error": str(e)}`** (`:360`) — an unfiltered exception passthrough. The
  `except` is bare `Exception`, so an `httpx.ConnectError` stringifies **the Supabase
  project hostname** into an anonymous caller's response, reported as a 401. Compare
  `signup()` (`:236-242`), which maps that exact case to `503 provider_unavailable` with
  no exception text, and `recover()` (`:417-419`), which collapses it into `202`.
- `recover()`'s own docstring (`:374-380`) states the contract this route breaks: "The
  response never says whether the address exists."

Two further oracles no response-body fix can close. First, **the 429 is itself an
oracle**: under any per-identifier limit, an immediate `429` on a first attempt for
address X proves X's bucket is already warm — i.e. that X exists and is seeing traffic
or being targeted. Second, **the timing side channel** (hypothesis — documented
mechanism, NOT tested against the live provider): GoTrue is expected to abort fast on an
unknown address but spend ~100–250 ms in password hashing on a known one, so even
byte-identical refusals may still separate the two by latency. Only deletion removes the
endpoint the measurement is taken against.

### 1.4 The route is free to call and expensive to serve

`login()` costs one outbound GoTrue round trip per request (`web/api/auth.py:309`) and
runs no auth hooks — no `before_request` on `auth_bp` gates or meters it — so the
attacker pays for a cheap POST and we pay a network call plus, on every mistyped
password, an ERROR-severity traceback (`:353`, logged with `exc_info=True`). A stuffing
run therefore fills the error log while spending our upstream budget. `signup()` logs
refusals at `warning` (`:233`); login logs them at `error`.

### 1.5 Three smaller defects in the same view

- `request.get_json()` **without `silent=True`** (`:297`), above the `try`, with no
  `errorhandler` registered anywhere in `web/`. A wrong `Content-Type` returns an **HTML
  415**; a JSON scalar body returns an **HTML 500** via `AttributeError` on `:298`.
  Every other route on the blueprint returns JSON.
- It **composes English** — five sentences — against the rule `signup()`'s docstring
  states at `:141-144`. Worse, `:356-359` rewrites GoTrue's `"Invalid login credentials"`
  and `"Email not confirmed"` into strings that match neither the code map nor the
  substring map in `formatAuthError` (`static/js/modules/dom.js:131-175`), so it defeats
  the only i18n path the app has.
- The log-severity defect belongs here too, and is stated once in §1.4 rather than
  twice: `:353` logs a mistyped password at `error` with a full traceback.

### 1.6 Neither option stops password spraying

Stated here so it is not discovered later: an attacker trying one common password
across thousands of addresses — one attempt per email, one per IP, from a residential
pool — stays under every per-IP and per-email ceiling in this document, and deletion
does not touch it either because the browser already authenticates against GoTrue
directly. The real control is compromised-credential checking — the leaked-password
protection entry already open in TODO.md (`TODO.md:214-229`), blocked on a Pro-plan
upgrade, not on code. Nothing in §2 or §3 substitutes for it.

---

## 2. Recommendation — delete the route (Option A)

**`POST /auth/login` is dead code.** Verified across the whole tree: no
`fetch('/auth/login')` in any JS module or template, no `action=` form, no `url_for`, no
script in `scripts/`, no external client, no API spec. `Services.login` calls
`supabase.auth.signInWithPassword` browser-direct (`services.js:375-380`). Its only live
exerciser is `web/tests/test_auth_routes.py:273-288`, a unit test against a mock — the
test is the only thing keeping the route "used", and it would pass just as well deleted
alongside it.

`docs/ARCHITECTURE.md:315-326` already reached this conclusion and stopped one step
short: "moving it server-side would be cost without a property … login is
browser-direct."

Deletion is the only option that closes §1.2, §1.3 and §1.4 outright rather than
mitigating them, and it is the only one that hands GoTrue's per-IP `/token` limiter back
the attacker's real address. It costs nothing that works today: `login()` writes nothing
to the Flask session (`session_obj` is the Supabase SDK object, not `flask.session`),
and `session["supabase_access_token"]` / `session["is_admin_hint"]` are written only in
`_authenticate_request` (`web/api/app.py:789-794`) on every authenticated request seeded
by the browser-direct sign-in — so no session fallback is orphaned by deletion.

### Steps

1. Delete `login()` — `web/api/auth.py:295-360`.
2. Delete `test_auth_api_endpoints`'s login third (`web/tests/test_auth_routes.py:273-288`);
   keep its signup and logout assertions. Delete `test_auth.py`'s
   `test_signup_login_flow` and `test_protected_endpoint` (`:16-46`, **not `:16-40`** —
   `test_protected_endpoint` runs to line 46, and cutting at 40 strands its last six
   lines at method-body indentation and breaks collection outright; `setUpClass` at
   `:9-15` stays) — both are
   `integration`-marked, both hit a live `:5000`, and both already assert a **top-level**
   `access_token` the route has not returned since it started nesting under `session`
   (`auth.py:342-350`). They are stale, not merely login-dependent.
3. Add the regression pin: `POST /auth/login` returns **404, not 405** — and the body is
   `text/html`, not JSON. Correction to v1, which asserted 405 on the theory that the
   blueprint's surviving `/logout` keeps `/auth` alive: Flask matches exact endpoint
   rules, not prefixes, so with no rule for `/auth/login` under any method Werkzeug
   raises `NotFound`. Rebuilt against the real app's `url_map` without the `auth.login`
   rule and measured: `POST /auth/login -> 404`, `GET /auth/login -> 404`,
   `POST /auth/logout -> 200`. A test may therefore assert the **status only** (and, if
   it must, a `text/html` content type) — it must not pin a JSON body, because no
   `errorhandler` is registered anywhere in `web/` and a 405 assertion would fail on a
   green tree.

   **Superseded 2026-09-09 for this release, not withdrawn.** Step 7's tombstone shipped
   instead of the bare deletion, so what is pinned today is `410` with a JSON
   `{"error": "endpoint_removed"}` body — `test_login_route_is_a_gone_tombstone` in
   `web/tests/test_auth_routes.py`. This 404 measurement is still the correct pin for the
   release that deletes the function, and the tombstone test is replaced by it then. Both
   numbers are right; they belong to different commits.

4. Correct the comment in `SupabaseClient.__new__` (`web/utils/supabase_client.py:73-78`),
   which names "the live signup route, and logout" plus login among the client's users.
   Named by class rather than by line alone on purpose: `676d2e6` edited the _other_
   client in the same file (`SupabaseAdminClient`, from line 148 down), so this file's
   later line numbers move without the cited comment changing at all.
5. Correct `docs/ARCHITECTURE.md:315-326` and its rate-limit table (`:349-361`), and
   `docs/registrations-pause-plan.md:158`.
6. **Decide the logout contract — do not just correct the comment.** The comment at
   `web/api/auth.py:17-29` describes an exemption that has never existed, and logout has
   always run at the global 10/minute. Two reviewers flagged that "correct the comment"
   normalises the bug rather than resolving it, and they are right: the comment states a
   deliberate intent that logout must stay available, and the code has silently
   contradicted it. Either exempt `logout` from the limiter (its Flask-side teardown is
   idempotent and security-positive, so refusing it protects nothing) or state in the
   comment why 10/minute is now the accepted ceiling. Pick one and write down which.

   **Blast radius, measured — and narrower than both reviewers claimed.** They argued an
   attacker sharing the effective IP could stop a reader terminating their session. That
   is wrong: `Services.endServerSession` wraps its `fetch` in a `try/catch` that only
   catches network errors (`static/js/modules/services.js:483-493`), and a 429 is a
   _successful_ HTTP response, so nothing throws and `logout()` proceeds to the
   browser-direct `supabase.auth.signOut({ scope: 'global' })` at `:518`. The session is
   revoked upstream either way. What a refused logout actually skips is the Flask-side
   teardown — `purge_conversation_state()`, `session.clear()` and
   `invalidate_token(token)` (`web/api/auth.py:433-445`) — which is exactly the
   shared-browser leak that function exists to close: the previous reader's conversation
   pointer stays in the cookie for the next person on that machine. Real, and worth
   fixing; not a sign-out denial.

7. **Before deleting, check the production access log for `/auth/login`, and consider a
   tombstone.** Two reviewers made the same point and it is fair: everything establishing
   this route as dead is repository-deep. A grep proves no in-tree caller; it cannot see
   a CLI, a bookmarked curl, a monitoring probe, or an integration that deliberately uses
   this origin as a stable façade rather than embedding the Supabase URL and anon key. If
   the log shows traffic, that changes the decision. If no log is available, ship a
   `410 Gone` with a JSON body for one release instead of a bare deletion — it stops
   calling GoTrue and stops returning tokens on the first commit, which is the whole
   security benefit, while giving an unknown client a diagnosable failure rather than an
   HTML 404. Delete the tombstone in the following release.
8. Move the TODO entry to `docs/archive/TODO-resolved.md` per TODO.md's own closing
   procedure, **recording the correction** — that the entry's "unlimited" was wrong and
   the route was deleted rather than limited. Note while doing it that the entry's own
   two citations are stale in a way that predates this plan: it cites
   `web/api/app.py:2166` for the `auth_bp` registration and `:2173-2184` for
   `recover_bp`/`signup_bp`, and both were already wrong at `f4d8976` (2166 was an
   unrelated comment there). On `ade91f4` the registration is at **2318** and the two
   limited blueprints at **2324-2337**. Carry the corrected numbers across rather than
   archiving the wrong ones.

### What deletion does not fix

Credential stuffing against **this product** is unaffected: the anon key and the GoTrue
endpoint are public by design, and the browser already authenticates there directly.
Deletion removes our unmetered _proxy_ to it. Password spraying is likewise untouched
(§1.6). **And the anonymising-proxy shape of §1.2 survives on three sibling routes**, a
point the earlier revisions missed: `recover()`, `signup()` and `logout()` all reach
GoTrue from the VPS's single address too. For those the laundering matters less — they
are metered, and two of them are bounded by GoTrue's own mail ceiling — but "deletion
hands GoTrue's per-IP limiter back the attacker's real address" is true of login and of
nothing else. Anyone who wants a ceiling on sign-in attempts as a product property has to set
it in GoTrue (`GOTRUE_RATE_LIMIT_TOKEN_REFRESH`), not in Flask — **but verify it is
reachable before promising it.** Two reviewers observed that this project runs on
Supabase Cloud (`web/api/app.py` builds Realtime origins as `wss://{ref}.supabase.co`;
`web/config.yaml:195-196` is a public HTTPS host), where GoTrue container environment
variables are platform-managed and the dashboard exposes only the email and SMS limits.
The variable is real in the self-hosted source; whether this deployment can set it is
unestablished, and if it cannot, then no per-account sign-in ceiling is available from
either side and that has to be stated rather than deferred to a task nobody can do. **Say that in the
archived entry**, or the next reader will believe this commit bought a property it did
not.

---

## 3. Fallback — keep and harden (Option B, rewritten)

V1's Option B is not shippable, and this section now says so instead of describing it.
Its centrepiece — step 3's email-keyed limit, `sha256(email.lower())` via
`web/utils/hashing.py` — fails six independent ways, each confirmed or measured in the
adjudication round:

1. **Victim lockout.** Flask-Limiter limits are conjunctive: exceeding _either_ the IP
   or the email bucket refuses the request. V1's "two limits, two keys, both applied"
   does not prevent lockout — an attacker burns five attempts against
   `victim@example.com` from their own machine, and the victim's next sign-in from a
   different IP is refused with `429` before GoTrue is ever reached. Zero-cost,
   unauthenticated denial of service against any known address.
2. **Unbounded key growth against `memory://`.** One attacker-supplied address pins one
   entry per window tier for the full window (measured against the installed
   `limits` 5.8.0: a `5/min;30/hr;100/day` triple holds three entries, the last for
   86 400 s; sweeps run only when re-armed by traffic). Distinct-email cardinality is
   attacker-controlled, and under sustained load the expiry scan walks the full key
   list on a fresh timer thread roughly every 10 ms. Random-address flooding bloats
   the single worker's heap (`web/api/app.py:2426-2437`) toward an OOM that takes the
   whole product down — and per finding 4 below, the restart that follows wipes every
   counter, resetting the attacker's budget.
3. **A new 429-based oracle.** Under an email-keyed limit, an immediate `429` on a first
   attempt for address X proves X's bucket is warm — the limit itself becomes the
   account-activity signal §1.3's uniform refusals were meant to suppress.
4. **Evadable by canonicalisation.** `sha256(email.lower())` gives distinct buckets to
   `v.i.c.t.i.m@gmail.com`, `victim+tag@gmail.com`, and leading-whitespace variants of
   one mailbox — no stripping, no Unicode normalisation, no provider-aware alias
   folding — multiplying an attacker's budget against one real account.
5. **Unsalted digest.** `hashing.py:20-27` is bare SHA-256 with no pepper, so anyone
   with read access to process memory, a diagnostic dump, or a future shared store can
   invert the key space against a dictionary of corporate addresses. The repo already
   owns the keyed alternative (`web/services/chat_store.py:219-222` uses
   `hmac.new(owner_salt, …)`); the plan's step 3 did not use it.
6. **Key-function crash surface.** A key function reading `email` before validation
   dies on `{"email": 12345}` with `AttributeError` on `.lower()` — an HTML 500 before
   any handler runs, on an unauthenticated endpoint.

And it reintroduces a pattern this repo deliberately removed on 2026-09-03.
`web/utils/hashing.py:9-12` records that the two rate-limit key functions on unverified
caller-supplied input were deleted, and `web/api/app.py:1080-1089` states the rule: "An
unverified bearer token must never mint its own bucket." An unverified submitted email
is the same class of input. There is one asymmetry, stated honestly because it is the
only thing that could rescue the idea: a token hash let an attacker _escape_ their own
limit (a bypass), while an email key _adds_ a limit the attacker cannot escape (the IP
limit still binds) — so this is not a bypass. It is a victim-lockout and memory-growth
vector instead. That does not save it; it only changes what it breaks. No existing limit
in this app is keyed on attacker-controlled input — all four `key_func=` sites pass `_rate_key` (account id, IP fallback) — and Option B's step 3 would have been the first.

### Option B′ — what is actually shippable

Drop the email key entirely. What remains is strictly hardening, and it buys strictly
less than v1's Option B claimed: no per-account throttling, no spraying resistance, no
closure of the timing oracle (§1.3). A per-account sign-in ceiling as a product property
belongs in GoTrue's config, not in Flask — same sentence as §2's closing paragraph.

1. **Give it its own blueprint**, `login_bp`, registered in `_register_routes` — matching
   `signup_bp`/`recover_bp`. Do **not** use `limiter.limit(...)` on the resolved view
   function; `auth.py:20-26` records why that registers the limit nowhere.
2. **Carry all three windows explicitly on the IP key**, never one:
   `login_api: "5 per minute;30 per hour;100 per day"`. A single `5 per minute` erases
   today's 200/day (§0.2). Alternatively pass `override_defaults=False`, but the explicit
   triple is self-documenting and the repo has been bitten twice by limiter defaults
   already. Stated with open eyes: the day window is only as durable as process uptime
   — `memory://` counters reset on every restart, no Redis exists anywhere in
   `requirements.txt`, `config.yaml` or `.env.example`, so a deploy wipes the ceiling.
   That is acceptable for a burst limit and must not be mistaken for a quota; the
   durable daily allowance pattern (`ARCHITECTURE.md:385-392`) is per-account and does
   not apply to an unauthenticated route.
3. **Collapse the refusals to one answer**: one status, one machine code
   (`invalid_credentials`) for wrong password, unknown address and unconfirmed email
   alike. `503 provider_unavailable` for transport failure, with **no** `str(e)` in the
   body. Machine codes only, per `signup()`'s docstring; add the pair to
   `formatAuthError` and to both `en.yaml` and `ar.yaml`. This closes the body-based
   oracle; it does not close the timing hypothesis or the 429 oracle (§1.3).

   Three constraints found in the 2026-09-08 review, all verified:
   - **Do not reuse `provider_unavailable` for the transport failure.**
     `static/js/modules/dom.js:142` already maps it to `I18n.t('auth.signupUnavailable')`,
     which renders "We could not check whether registration is open." A reader who failed
     to _log in_ would be told something about registration. Add a distinct code.
   - **Keep `email_not_confirmed` distinct from `invalid_credentials`.** Collapsing it
     strands a legitimate reader who has registered but not clicked the link: they are
     told their password is wrong, and will reset a password that was never wrong. Per
     the scoping in §1.3, that branch is only reachable by someone who already holds
     valid credentials, so keeping it costs little.
   - **The 429 and timing oracles are accepted residual risk, not closed.** Say so
     plainly rather than calling them "weaker": §3 kills the email key partly _for_
     having a 429 oracle, and an IP-keyed limit has one too. The honest difference is
     what the bucket is keyed to — an identifier the attacker supplies versus an address
     they share — not that one is an oracle and the other is not. Carry both as TODO
     entries.

4. `request.get_json(silent=True) or {}` plus explicit type validation, matching
   `signup()` (`:146`, `:161`) — so a malformed body is a JSON 400, never an HTML 500.
5. **Stop logging one record per attempt at all** — then demote what remains. Demoting
   `:353` to `warning` was the earlier instruction and it is not enough: the attacker
   still controls one log record per guess, so storage, alert noise and log-processing
   cost stay attacker-driven and only the severity label changes. Expected credential
   refusals (`invalid_credentials`, `email_not_confirmed`) should be silent, sampled, or
   aggregated into a counter; transport and structural faults keep a bounded diagnostic
   line. For that remaining line, demote `:353` to `warning` and replace `{e!s}` with
   `describe_api_error(e)` from
   `web/utils/postgrest_errors.py` rather than simply dropping the text. That module
   arrived with `c071ccb` after v1 was written and is now the repo's established answer
   to this exact anti-pattern: bounded to 300 characters, redacts JWTs and `sb_secret_`
   values, and is documented never to raise. `admin_store.py` and `chat_store.py`
   already use it. Note its scope limit, which matters here: every existing caller feeds
   it to a logger or to an internal exception message (`SupabaseChatBackend._rpc` in
   `chat_store.py`), never into
   a response body, and it changes no status code or control flow. So it does nothing
   about §1.3's separate defect of returning `str(e)` to an anonymous caller — step 3 is
   what closes that, and the two must not be conflated.
6. **Add `Cache-Control: no-store` to every token-bearing response.** The success path
   returns an access token and a refresh token (`web/api/auth.py:342-350`) with no cache
   directive at all, which is the one thing on this route more sensitive than any refusal
   body — and every earlier revision of this plan, plus two of the three reviews, looked
   straight past it while arguing about error codes. The repo already sets this header on
   its quota refusals (`web/api/app.py:991`, `:1061`), so the pattern exists. Option A
   removes the concern entirely, which is one more argument for it.
7. Same doc corrections as Option A steps 4-6, plus a new row in ARCHITECTURE.md's
   rate-limit table.

---

## 4. Independent of A and B — the work that actually protects anything

Neither option is worth much until these are done. Each deserves its own TODO entry;
none belongs in the same commit.

- **C1 — ~~Answer the proxy question (blocking, and not code).~~ ANSWERED 2026-09-12, and the
  answer is the safe one.** The live vhost sets
  `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` (plus `X-Real-IP`, `Host` and
  `X-Forwarded-Proto`), `BEHIND_PROXY=true` makes `ProxyFix` trust exactly one hop, and
  gunicorn is bound to `127.0.0.1:5001` so the header cannot be forged from outside. Every
  IP-keyed limit therefore keys on the real client address — neither §1.1 failure is live. The
  vhost is quoted in [`OPERATIONS.md`](OPERATIONS.md#nginx-what-the-proxy-actually-sets).
  **This unblocks C2**, whose number must still be derived from measured per-IP volume.
  One trap for whoever re-verifies: `sites-enabled/` is all symlinks and `grep -r` does not
  follow them, so `-r` returns nothing on a correctly-configured host. Use `grep -R` or
  `nginx -T`. The snippet `README.md` documents still omits the header and should be
  corrected to match what is deployed.
- **C2 — Restore a ceiling that a route limit cannot erase.** Flask-Limiter's
  `application_limits` applies regardless of route-level limits (current upstream docs).
  An application limit would have made §0.2's regression impossible and would cover
  `/auth/recover` and `/auth/signup`, which have no daily ceiling **right now**.
  **The number in earlier revisions — `1000 per day` — must not ship.** An application
  limit is per key and shared across every route, so under a single office NAT (or under
  C1's collapsed state, where the key is one address for everybody) a handful of readers
  polling notifications, loading history and chatting would exhaust 1000/day within
  hours and be refused on _every_ route. Whatever number is chosen has to be derived
  from measured per-IP daily volume at the busiest real site, with headroom, and it has
  to be re-derived if polling cadence changes. Ship the mechanism only with a number
  somebody has measured. The review objected that this bucket is global and would lock out a whole office
  — measured, that objection is false: with two distinct keys against a 3/minute
  application limit, alice got `[200,200,200,429]` and bob got his own `[200,200,200,429]`.
  The bucket is shared _across routes_, per key, not one bucket for the deployment. The
  mechanism therefore stands; the sizing does not. Note what the alice/bob measurement
  does and does not settle: it refutes "one bucket for the whole deployment", but it says
  nothing about an office behind one NAT, where every reader genuinely _is_ one key. That
  is the case the number has to survive, and it is the same case C1 describes — so C1
  first, then measure, then choose.
- **C3 — Pin the "explicit limit replaces defaults" behaviour behaviourally.**
  `test_rate_limit_keys.py` proves limits _fire_; nothing proves what they _replace_.
  The 260-request measurement in §0 belongs in that file as a test.
- **Neighbouring hazard, not login work: the CORS debug branch.**
  `web/api/app.py:1714-1722` — when `DEBUG` is true the app calls
  `CORS(app, supports_credentials=True)` with all origins allowed. App-wide, not
  login-specific; neither option fixes it and deletion does not touch it. Recorded here
  because the review surfaced it and it would otherwise be lost; it wants its own entry
  and its own verification that production never runs with `DEBUG=true`.

---

## 5. Tests

Option A: the 404 pin (§2.3 — status only; a JSON-body assertion would fail on a green
tree), plus the two deletions. Nothing else in the suite touches
the route — verified across `test_auth_routes.py`, `test_auth_failure_modes.py`,
`test_auth.py` and `conftest.py`.

Option B′, all in `web/tests/test_rate_limit_keys.py`, the **only** file that builds the
app with `enforce_rate_limits=True` (`create_app(testing=True, enforce_rate_limits=True)`,
`app.py:4050`; a limit added anywhere else is unenforced in tests and proves nothing):

- The 6th login POST in a minute is refused; the 5th is not.
- The daily window is enforced at all — the §0.2 regression guard, and the reason step 2
  is not optional. **Rewritten 2026-09-08:** earlier revisions asked for "101 requests in
  a day are refused even at 5/minute", which all three reviewers correctly called
  untestable. Against real windows request 6 dies on the _minute_ bucket and request 31
  on the hour bucket, so the test would go green at request 6 having proved only that
  _some_ limiter fired — the exact failure mode this plan criticises elsewhere. Isolate
  the day window instead: build the app with `login_api` overridden to something like
  `"1000 per minute;1000 per hour;100 per day"` (the fixture already monkeypatches
  `config._config` this way for `chat_api`), then assert requests 1-100 pass and 101 is
  refused. Freezing the clock is the alternative; the repo has no time-mocking dependency
  today, so the window override is the cheaper route.
- The refusal for an unknown address is **byte-identical** to the refusal for a wrong
  password — with the §1.3 caveat that byte-identical does not mean
  timing-identical (hypothesis, untested against the live provider).
- Malformed bodies (`{"email": 12345}`, JSON scalars, wrong `Content-Type`) are JSON
  400s, never HTML 500s.

V1's email-bucket tests ("two emails share the IP bucket, one email shares across IPs")
are deleted with the email key — they described the lockout vector, not a property.

Each must be seen failing against the current code before it is believed
(CLAUDE.md, _Working style_).

---

## 6. Sequencing

**A now.** Then C3, then C1 (a question, not a commit), then B′ step 2 and C2 if the
route is kept.

Corrected 2026-09-08: earlier revisions sequenced `C1 → A or B′ → C2 → C3`, which put an
unowned question in front of a deletion that does not depend on it. Option A, B′ steps
3-5 and C3 are all safe under either §1.1 state and can ship immediately. Only B′ step 2
and C2 need C1 answered first, because only those two mint a new IP-keyed bucket.

Shipping **B′ step 2** before C1 is the failure mode worth naming: it produces a
`5 per minute` login limit that is either shared by every reader on earth or bypassed by
one forged header, and — if the three windows of step 2 are collapsed to one — a
nominally 36× looser daily allowance than today, under a commit message that says the
opposite. That is the whole reason step 2 is the one item still held behind C1.

---

## 7. Open decisions for the owner

1. **Delete or keep?** TODO.md:94-95 already flags this as a product decision. §2 is the
   engineering recommendation; the counter-argument is a future non-browser client, and
   the route is 60 lines in git history if that client ever appears.
2. **C1: what is actually in front of gunicorn?** Nobody in this repository knows.
3. **Is a per-account sign-in ceiling wanted as a product property?** If so it belongs in
   GoTrue's config, not in Flask — and it is a dashboard task, not this commit. The same
   answer covers password spraying (§1.6): the control that touches it is the
   leaked-password protection toggle already open in TODO.md, blocked on the Pro-plan
   upgrade.

---

## 8. Rebase onto `ade91f4` — what the incident work changed, and what it did not

Written after merging the sixteen commits that landed 2026-09-07/08 (the Supabase
key incident, `f4d8976..ade91f4`). Recorded so the next reader does not repeat the
search.

**None of those sixteen commits addresses this entry.** Four independent checks:

```text
web/config.yaml in the range          -> unchanged, no diff at all
`login_api` anywhere on ade91f4       -> not found
web/api/auth.py in the range          -> +2/-1, both inside signup()
test_rate_limit_keys.py, test_auth*   -> unchanged
```

The whole change to `auth.py` is a `SignUpWithEmailAndPasswordCredentialsOptions`
annotation on `signup()`'s options dict. `login()` is byte-identical, `auth_bp` is
still registered at `app.py:2318` with no limiter, and the TODO entry sits unchanged
at the same index position — `ade91f4`'s own message says "this branch closed no open
entry outright."

Two things in the range do touch this plan, both already folded in above: `a3a5d99`
makes C1's remedy actually take effect (§1.1), and `c071ccb` supplies the error
describer that Option B′ step 5 should use.

**Every measurement in §0 and §2 was re-taken on `ade91f4` and is unchanged:**
login `[401 ×10, 429 ×4]`, logout `[200 ×10, 429 ×4]`, 260 consecutive `/auth/recover`
requests with no daily ceiling, and `POST /auth/login -> 404 text/html` once the rule
is removed.

**One search-method note, because it would have produced a false negative.**
`git log -S'limiter'` reports no limiter changes in this range, which is wrong:
`69ec122` wraps **five** `limiter.limit(...)` calls in `cast(RouteCallable, ...)`
(`admin.revoke_sessions`, `admin.change_email`, `admin.create_notification`,
`account.export`, `account.delete_all_conversations` — earlier revisions said four). `-S`
counts occurrences and that edit is count-neutral; `-G` finds it. The cast itself is
harmless — the limiter call is evaluated inside it, so the wrapper is preserved and
the documented `view_functions` bug class is not reintroduced — but a future check of
the form "has anything touched the limiter?" must use `-G`.

**Version constants, for whichever option ships.** `ASSET_VERSION` moved
`warm72 -> warm75` across the range and `APP_VERSION` to `0.7.2 (Beta)`. Option A
touches no CSS or JS and needs neither; Option B′ needs neither either unless step 3's
new machine code reaches `formatAuthError`, which it does — so B′ bumps
`ASSET_VERSION` to `warm76`. Editing `CLAUDE.md` is what bumps `APP_VERSION`, to
`0.7.3`; neither option requires that.

---

## 9. The three-way review of 2026-09-08, and what it changed

Three independent reviewers read revision 3 in parallel — `muse-spark-1.3`,
`gpt-5.6-sol` and `gemini-3.8-flash-high` — each told to be adversarial and to verify
before asserting. Recorded here because the disagreements are the useful part, and
because two of the corrections are to claims this document itself made.

**Where all three agreed, and were right.** C1 was gating work that does not depend on
it; the 101-request daily test cannot work as written; and the `7 200/day` framing for
recover and signup overstated the volume while missing the sharper harm. All three are
fixed above, in §1.1, §5 and §0.

**Where two agreed and were right.** The logout finding was noticed and then dropped
into a documentation fix (§2 step 6); B′ step 5 changed a log's severity without
changing who controls its volume (§3); and "dead code" was established by grep, which
cannot see consumers outside this tree (§2 step 7).

**Where a reviewer was right and alone.** The success path returns tokens with no
`Cache-Control: no-store` (§3 step 6) — three revisions of this plan and two of the
three reviews argued about refusal bodies while the token response sat uncovered. Also
that `provider_unavailable` already renders as a _registration_ message in `dom.js:142`,
and that collapsing `email_not_confirmed` strands legitimate unconfirmed readers (both
§3 step 3).

**Where a reviewer was wrong, checked and rejected.** One argued that Flask-Limiter's
HTML `429` breaks the frontend, since callers `await response.json()`. The `429` is
indeed HTML (measured: `text/html; charset=utf-8`, body `<!doctype html>...`), but every
bare `response.json()` in `services.js` sits behind an `if (!response.ok) throw`, and the
rest use `.json().catch(() => ({}))`. Nothing parses it. Two reviewers also claimed an
attacker exhausting the logout bucket stops a reader signing out; measured, they are
wrong, and §2 step 6 records what actually happens instead.

**What the reviews did not settle.** Whether the timing side channel is real — it is
still an untested hypothesis, and testing it needs the live provider. Whether
`GOTRUE_RATE_LIMIT_TOKEN_REFRESH` is settable on Supabase Cloud (§2). And C1 itself,
which no amount of reviewing can answer because the answer is not in this repository.

---

## 10. What shipped, 2026-09-09

Option A, in the tombstone form §2 step 7 prescribes rather than as the bare deletion.
Implemented by a delegated agent (OpenCode, `muse-spark-1.3`, high effort) against a brief
derived from §§0-2 and §8; reviewed, re-gated and corrected by the orchestrator before
commit, per CLAUDE.md's _Do not trust a delegated agent's self-report_.

**Why the tombstone and not the deletion.** §2 step 7 makes the choice conditional on the
production access log, and that log is not reachable from this work. Its stated fallback
therefore applies: `410 Gone` for one release. This buys the whole security benefit on the
first commit — no GoTrue call, no tokens returned, no `str(e)` in a response body — while
an out-of-tree client that a grep cannot see gets a diagnosable JSON failure rather than an
HTML 404.

**What landed.**

- `web/api/auth.py` — `login()` reduced to `return jsonify({"error": "endpoint_removed"}), 410`.
  It calls nothing, logs nothing, and **does not read the request body at all**, which is
  what closes §1.5's HTML 415/500 pair rather than merely narrowing it.
- `web/api/auth.py:17-29` — the module comment's claim of a logout exemption removed. §2
  step 6's decision, taken and written down: **logout keeps the global 10/minute.**
  Exempting it would mint a second unmetered GoTrue proxy (`admin.sign_out` from this
  host's address) of exactly the shape this commit closes. The comment now carries the
  measured blast radius from §2 step 6 — a refused logout still signs the reader out; what
  it skips is the Flask-side teardown.
- `web/utils/supabase_client.py` — the `SupabaseClient` comment no longer names login among
  the client's users.
- `web/tests/test_auth_routes.py` — the login third dropped from `test_auth_api_endpoints`;
  new `test_login_route_is_a_gone_tombstone` pinning the 410, the JSON machine code, both
  malformed-body shapes, and — the assertion that carries the security property —
  `sign_in_with_password.assert_not_called()`.
- `web/tests/test_auth.py` — deleted whole. **Divergence from §2 step 2**, which said to cut
  lines 16-46 and keep `setUpClass`: both of that file's tests are login-dependent _and_
  stale (each asserts a top-level `access_token` the route stopped returning when the
  tokens moved under `session`), so trimming would leave a `TestCase` with no tests and a
  `setUpClass` configuring nothing.
- `docs/ARCHITECTURE.md:315-326` — corrected, including the reason the old paragraph missed:
  a server-side login was not "cost without a property", it was a negative property.
- `TODO.md` — entry retitled (its old title asserted the premise §0 disproves), the two
  stale `app.py` citations corrected to `:2318` and `:2324-2336`, and the remaining work
  restated as the deletion.

**Two prescriptions deliberately not followed.** `docs/registrations-pause-plan.md:158` was
left alone — it is a `STATUS: BUILT` design record whose claim (login is browser-direct)
stays true, and this repo records reversals rather than editing history away. No row was
added to ARCHITECTURE.md's rate-limit table: a `410` does no work and the route still
inherits the global default, so a row would imply a limit designed for it.

**Verified by the orchestrator, not taken on report.** The full CI suite re-run
(`-m "not browser and not integration"`); `ruff check`/`format` and `npm run lint:md`
re-run; the whole diff read line by line. `mypy web` fails identically on a clean tree —
`numpy/__init__.pyi:737: Type statement is only supported in Python 3.12 and greater`,
a local-interpreter artefact (this machine runs 3.14 against a 3.10 floor), not this
change. And the new test's teeth were checked directly rather than inferred: with
`web/api/auth.py` stashed, `sign_in_with_password.assert_called_once()` **passes** against
the old body, so `assert_not_called()` is a real assertion and not a vacuous one. The
agent's own stash check only exercised the `410` assertion, which fails first.

**Still owed, with post-change line numbers.** Delete `login()`
(`web/api/auth.py:316-356`) and `test_login_route_is_a_gone_tombstone`
(`web/tests/test_auth_routes.py:285-321`) together — the test fails on a green tree the
moment the route goes. **Read the new log line first.** The tombstone answers `410` under
`GET` and `POST`, reads no body, calls nothing, and writes one bounded `warning` per call
naming method, address and user agent. That log is why the release exists: the access log
was unreachable, so silence across the release is the evidence to delete on and a hit is a
caller to find before deleting. Logging an unauthenticated endpoint is refused elsewhere in
this plan for handing an attacker our storage bill; it is safe here only because `auth_bp`
carries no explicit limit, so the global defaults cap one address at 200 records a day.

Then archive this document per TODO.md's closing procedure — and **lift §4's C1, C2 and C3
and §1.6's spraying note into their own TODO entries before archiving, not after.**
`docs/archive/` is excluded from search by `/.ignore` and CLAUDE.md calls it "history, not
instructions", so an open item still sitting in this file on archiving day stops existing.
C1 in particular is load-bearing for something that shipped: `web/api/auth.py`'s new
comment cites the global per-IP defaults as logout's accepted ceiling, and C1 is the
unanswered question of whether that key means anything.

Neither `ASSET_VERSION` nor `APP_VERSION` moved: no CSS, no JS, no `CLAUDE.md` edit.
