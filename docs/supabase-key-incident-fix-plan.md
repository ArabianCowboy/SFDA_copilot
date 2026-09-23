# Supabase secret-key incident — fix plan

STATUS: ACTIVE PLAN — **P0 resolved 2026-09-07**; follow-ups open.
Opened 2026-09-07. Revision 3, same day. Revision 2 followed an adversarial
review; revision 3 records the resolution and a second, unrelated credential
failure the same day.

An `Unregistered API key` 401 took every privileged Supabase call down on
2026-09-07. This plan records the confirmed root cause, the recovery, and the
defects the incident exposed. **P0, P1, P4, P6, P7, P8, P9 and P10 are done**, each
in its own commit on `fix/supabase-key-incident-followups`. **P3 is done** (2026-09-23;
see its section). **P5 is half done** — the observability half shipped; the
three-state model has not. **P2 remains open**, blocked on something this machine
cannot supply: sanitized fixtures captured from live GoTrue.

**Revision 2 changed the plan materially.** Revision 1's P0 was judged unsafe to
execute (no production scope, no rollback, no acceptance checks) and its P5
remedy was actively dangerous — see §6.

---

## 1. Root cause (confirmed, not open for debate)

`SUPABASE_SECRET_KEY` in `.env` is a **well-formed `sb_secret_` key that is not
registered for project `yjjuudnsnjzhyqllsqrd`**, and
`web/utils/supabase_client.py:148` prefers it over the `service_role` JWT that
still works:

```python
key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
```

The `or` short-circuits onto the bad value, so the working JWT is never reached.

### Evidence

Live `curl` against `https://yjjuudnsnjzhyqllsqrd.supabase.co`:

| Credential                  | Shape                                                | Result                                           |
| --------------------------- | ---------------------------------------------------- | ------------------------------------------------ |
| `SUPABASE_ANON_KEY`         | legacy JWT, `ref` matches, `exp` 2035-04-26          | `/auth/v1/health` → **200**                      |
| `SUPABASE_SERVICE_ROLE_KEY` | legacy JWT, `ref` matches, `exp` 2035-04-26          | `GET /rest/v1/` → **200**                        |
| `SUPABASE_SECRET_KEY`       | `sb_secret_` + 22 + `_` + 8-char checksum (41 total) | `GET /rest/v1/` → **401 `Unregistered API key`** |

Both JWTs carry `ref: yjjuudnsnjzhyqllsqrd`, matching `SUPABASE_URL`; neither is
expired. The `sb_secret_` value matches Supabase's documented layout exactly, so
it is not truncated — it is a valid key belonging to a **different project**.
New-format keys carry no `ref` claim, so this is undetectable offline.

`curl` reproduces the failure with no application code in the path, so no commit
is responsible. `.env` is untracked (`.gitignore:56-62`), so no commit could have
changed it.

### Blast radius

All six failing call sites resolve, through different `get_*_backend()`
factories, to **one** cached client instance (`supabase_client.py:164`,
class-level `_instance`): `admin_store.py:298` `fetch_identity`,
`admin_store.py:317` `get_standing_line_facts`, `admin_store.py:1266`
`resolve_identity_flags`, `notification_store.py:387` `list_active_for_reader`,
`quota_store.py:156` `_rpc`/`status`, `chat_store.py:498` `list_sessions`.

Authentication was **never broken**. Token verification and login use a separate
anon client (`app.py:679`, `auth.py:305`, reading `SUPABASE_ANON_KEY`), verified
healthy. Every `Identity lookup failed for <uuid>` line is downstream of a
_successful_ token verification.

### Explained symptoms

- `/api/chat/sessions` → 503; `/api/notifications/active` → 503 every 45s.
- `/api/identity` → 200 with `quota: null`, `created_at: null`.
- **Admin button missing despite admin authorization.** `resolve_identity_flags`
  falls back (`admin_store.py:1273`) → cold cache → `IdentityFlags.unknown()`
  sets `role="user"`, `is_resolved=False` (`identity_cache.py:96-101`) →
  `is_admin` is `role == "admin" and is_resolved` (`identity_cache.py:66`) →
  `renderAdminAffordance(false)` applies `d-none` (`auth-view.js:153-157`).
  Fails closed on privilege, by design. This is a _symptom_, not an auth bug.
- **Chat still works**, streaming answers neither saved nor counted (see P1).

---

## 2. P0 — restore service-key access — **RESOLVED 2026-09-07**

**Outcome.** The operator replaced the `SUPABASE_SECRET_KEY` value in `.env` and
restarted. Every previously-failing surface returned to HTTP 200 in the same boot
— `/api/chat/sessions`, `/api/notifications/active`, `/api/identity` — with no
`Unregistered API key` line anywhere in the startup log, and the administration
console became reachable again. That last point independently confirms the
diagnosis in §1: the admin affordance was hidden because the _role lookup_
failed, not because authentication did.

The procedure below is retained as the **runbook** for the next occurrence, and
should be lifted into `docs/OPERATIONS.md` under P10. Its production-scope steps
(P0.1, P0.3, P0.6) were **not** exercised this time — recovery was local only, so
production remains **UNVERIFIED** and those steps are still untested.

### A second credential failed the same day

Immediately after the Supabase fix, chat failed with:

```text
openai.AuthenticationError: Error code: 401 ... 'code': 'invalid_api_key'
```

`OPENAI_API_KEY` in the same `.env` was dead — confirmed by direct `curl` to
`https://api.openai.com/v1/models` (401), with no application code in the path.
Replacing it resolved chat. It was unrelated to the Supabase fault and to any
commit; the two were coincident, not causal.

**Two invalid credentials in one file in one day, neither detected by anything
except a human noticing, is the strongest evidence in this document for two
otherwise-easy-to-defer items in §4:** an independent health/readiness check, and
a named owner for secret rotation. Neither incident would have been caught by an
uptime check, because `/api/identity` answers 200 while degraded (P6) and a dead
OpenAI key fails only at generation time.

### Original procedure (retained as the runbook)

**Revision 1's P0 was "swap the value and restart Flask." That is not an
executable production instruction and must not be run as written.** The repo
documents a VPS and Gunicorn (`README.md:95`, `CLAUDE.md:9-12`) but contains
**no deployment artifacts at all** — no Dockerfile, no systemd unit, no Procfile,
no Makefile, no deploy script — and `docs/OPERATIONS.md` has no deployment
section. Production's `.env`, health, and restart command are **UNVERIFIED**.

### P0.1 — Establish deployment scope first

Record for **each** deployment (local and production): application URL, Supabase
project, deployed revision, Python environment, deployment directory, process
manager, credential source, and the exact restart command. **Check production
independently — local recovery does not establish production recovery.** Production
may be healthy (different `.env`), already broken, or about to break.

### P0.2 — Preflight the candidate before cutover

From each affected host, verify the candidate key against the intended project
using **both** a privileged table read and an existing read-only RPC. A `200` from
`/rest/v1/` alone is insufficient — application reads also depend on table grants
and RPC execution (`admin_store.py:292-328`, `quota_store.py:193-208`). Record
status and sanitized error category only; never credentials or raw headers.

### P0.3 — Prepare a tested rollback before cutover

Keep a credential already verified against that deployment's project. **Do not
use the known-bad value as rollback.** Do not disable legacy keys or rotate the
JWT signing secret as part of this restoration — rotating the JWT secret
invalidates the anon key and every live session simultaneously
(`.env.example:19-38`). Creating a new secret key does not itself revoke
anything.

### P0.4 — Update the effective source and do a managed restart

- The project-root `.env` **overrides inherited environment variables**
  (`app.py:107`, `load_dotenv(..., override=True)`). Commenting out a line in
  `.env` does **not** unset a variable inherited from the environment.
- For the interim fallback, remove `SUPABASE_SECRET_KEY` from **every** effective
  source and confirm `SUPABASE_SERVICE_ROLE_KEY` is populated.
- Reloading dotenv, or constructing another Flask app in the same process, does
  **not** reset the cached client (`supabase_client.py:139-166`). A full managed
  process restart is required.
- The app is single-worker; account for in-flight SSE streams and index
  initialization (`app.py:2008-2013`) before restarting.

### P0.5 — Acceptance matrix

Checking HTTP 200 is not sufficient anywhere in this table, because several
routes swallow their own failures.

| Surface             | Required evidence                                                                                                                                                                   |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Reader identity     | `/api/identity`: expected role/tier **and** a populated, plausible `quota` (`app.py:2562-2603`)                                                                                     |
| Console             | `/admin/api/identity`, settings, registrations, users, tiers, audit, notification history. Check API responses — the `/admin` shell is not proof (`admin.py:78-116`)                |
| Durable history     | `/api/chat/sessions` and `/api/chat/history?c=<owned-existing-id>`. Without `c`, history returns empty success without consulting persistence (`app.py:2696-2727`)                  |
| Paid generation     | One controlled request through **each** chat route: response consumed, allowance increment verified, turn reloadable, no persistence error (`app.py:3333-3340`, `app.py:3755-3770`) |
| Notifications       | Active/history retrieval, a targeted notification, mark-read, and **actual Realtime delivery** — REST success does not prove broadcast (`notification_service.py:101-128`)          |
| Auth administration | Privileged GoTrue access separately; session revocation and email change also use the service client (`auth_admin.py:45-46`)                                                        |
| Security & language | Reader denied console; disabled test account refused; EN and AR surfaces checked (`admin.py:101-109`, `app.py:758-759`)                                                             |

### P0.6 — Rollback on failure

Restore the prevalidated credential, repeat the same managed restart, rerun the
same checks. **If neither credential works, declare recovery unsuccessful and
contain paid generation (P1) rather than claiming restoration.** Retire
superseded credentials only after all consumers and rollback needs are checked.

### P0.7 — Open trap

The revision-1 claim that a value swap repairs Realtime is **UNVERIFIED**.
`notification_service.py:101` sends the key in both `apikey` and
`Authorization: Bearer`; current Supabase guidance directs opaque `sb_secret_`
keys to `apikey`. Require a live delivery check; do not infer from REST success.

### P0.8 — Investigate provenance

A well-formed key registered to another project is a dashboard copy-paste, not a
code event. Establish who changed it and when, and whether any other deployment
received the same value.

---

## 3. Follow-ups

### P1 — Quota fails open: unmetered chat spend (HIGH, active cost)

`_claim_daily_message` (`app.py:856-862`) re-raises only `QuotaUnavailable`, then
catches `Exception` and returns `None`, which both chat routes treat as "stream
uncounted" (`app.py:3333-3340`, `app.py:3755-3762`). A PostgREST 401 is not in
`_CONFIGURATION_FAULTS` (`quota_store.py:49-57`), so it reaches the broad catch.
During this incident **every reader had unmetered LLM access**.

`quota_store.py:18-27` and `app.py:842-847` both state the design refuses exactly
this outcome. A credential fault reaches the wrong branch.

**Design constraints the remedy must satisfy:**

1. Fail **closed** only on positively identified deployment-credential rejection.
2. For transient or ambiguous failures, allow uncounted requests bounded by
   **both count and elapsed time**, with an aggregate ceiling across readers.
   "Fail closed after N" alone converts a brief blip into a chat outage.
3. Keep the failure state outside per-request wrappers and synchronize it across
   the eight threads. Separate `claim` health from `status`/refund health —
   `/api/identity` calls `status()` on a different path (`app.py:2583`).
4. Specify cooldown and a single recovery probe. **Recovery must not require a
   restart.**
5. **Do not blindly retry claims or refunds.** The RPC increments and decrements
   usage with no request-id argument
   (`supabase/migrations/20260903195102_reader_quota_claim_release_and_read_rpcs.sql:14-17,51-57,77-86`),
   so an uncertain response can double-count.

**Threshold decided 2026-09-07 (owner):** keep answering for the first **5
consecutive claim failures or 2 minutes, whichever comes first**, then refuse
with 503. Two refinements agreed alongside it:

- The counter is **process-global, not per-reader**. A rejected key is a
  deployment fault, not a reader's; per-reader, five failures across two hundred
  readers is a thousand unmetered requests, while global it is five.
  Single-worker makes one counter trivially correct.
- A **recovery probe** is required, not optional: once closed, one request is let
  through every 30s to test recovery. Without it a transient blip that trips the
  threshold keeps chat closed until somebody restarts the process — worse than
  the bug being fixed.

The cost arithmetic supports erring toward answering: a chat request is roughly
4,400 input tokens, so five unmetered requests is negligible spend, whereas
closing too eagerly takes chat down for everyone.

**Tests:** both routes, real SDK error construction, repeated requests,
concurrency, recovery, and zero model invocation on rejection. Existing coverage
verifies that a generic failure streams uncounted (`test_quota_routes.py:332-341`)
and uses the in-memory backend — it does not exercise this path.

**Precedent:** `6347212` and `80593b4` hardened the _refund_ path. This is the
same reasoning applied to the _claim_ path.

### P2 — A GoTrue 401 would sign everyone out (HIGH, dated trigger)

`_is_upstream_outage` (`app.py:476-513`) ends
`return isinstance(status, int) and (status >= 500 or status == 429)`. 401 is not
an outage, so it falls to `_is_auth_refusal` (`app.py:516-555`), which returns
True for any `AuthError` with an int status → cleared session → 401.

**Not reachable from this incident** — auth uses the anon client, and
`resolve_identity_flags` swallows PostgREST errors before any classifier sees
them (`admin_store.py:1265-1273`). Revision 1 over-claimed this; corrected here.

**The trigger is nonetheless dated.** `SUPABASE_ANON_KEY` is still a legacy JWT
and Supabase deprecates legacy keys by end-2026 (`.env.example:19-38`; the exact
date and failure response are **UNVERIFIED**).

**"Inspect the body" is not an implementation spec.** The installed SDK retains
`message`, `status` and an optional `code` on `AuthApiError`, not a complete
structured response (`supabase_auth/errors.py:113-126`). The remedy requires an
explicit classification table:

- Recognized user-token failures (`bad_jwt`, `session_not_found`) stay refusals.
- Only **positively recognized** API-key rejection signatures become outages.
- Absence of an error code is **not** evidence of a bad deployment key.
- Ambiguous responses must not authorize a request or reuse an unverified
  identity. If the session is preserved behind a 503, document that uncertainty
  separately and require subsequent live verification.

**Capture sanitized fixtures before changing classification.** Existing tests
require an invalid JWT to 401 and clear the session
(`test_auth_failure_modes.py:132-143,269-271`); a careless fix here is a security
regression that never signs out a genuinely revoked token.

The anon-key migration to `sb_publishable_` is a **separate change**, and its
acceptance scope includes password recovery's separate cached client
(`account_recovery.py:121-151`), signup, logout, browser profile/preferences
access, session refresh and private Realtime reconnection — not just login and
rendered templates.

### P3 — Pin dependencies (MEDIUM) — **DONE 2026-09-23**

**As shipped:** `requirements.txt` pins `supabase==2.30.1` and `httpx==0.28.1`, and
only those two. The siblings stay unpinned so they follow `supabase`'s own metadata,
as prescribed below. The set was resolved in a fresh Python 3.10.20 venv (a uv-managed
interpreter this machine did have), imported cleanly there, and a `pip install
--dry-run` of the whole `requirements.txt` with both pins resolved without conflict.
The constraint is enforced where installs happen: CI installs from `requirements.txt`,
and `docs/OPERATIONS.md`'s deploy checklist calls for a `pip install` whenever that file
changes, which this change does. That install moves the VPS to these versions if it
runs others. Nobody has checked what it runs now.

`requirements.txt` pins nothing relevant: `supabase` (line 35) and `httpx`
(line 41) are bare; `postgrest`, `supabase_auth`, `pydantic` are transitive. No
lock file, no `constraints.txt`.

Installed: `supabase 2.30.1`, `postgrest 2.30.1`, `pydantic 2.13.4` under
**Python 3.14.7**, against a 3.10 production floor (`pyproject.toml:7,57`). Only
one venv exists, so ruff and mypy check a floor no local run exercises.

**Do not freeze the 3.14 resolution.** Resolve and validate a compatible set
under **Python 3.10**. The `supabase` package already pins its siblings to the
same release, so independent sibling pins fight its metadata. `requires-python`
alone enforces nothing here — this repo deliberately has no `[project]` section
and CI installs requirements files; specify how the constraint is enforced in the
actual install path. CI already runs 3.10; the divergence is local only.

### P4 — Unreadable PostgREST errors (MEDIUM — dependency of P1)

`APIErrorFromJSON` declares four `Optional[str]` fields with no defaults —
**required** under pydantic v2 (verified: all four `is_required() == True`).
Supabase returned only `{message, hint}`, so validation failed and
`_sync/request_builder.py:98` substituted `"JSON could not be generated"`,
re-raising with implicit chaining. The real message survives only in `details`.
Library defect, not this repo's; cross-version range **UNVERIFIED**.

**Logging `e.json()` is not enough** — it returns the fallback dict still headed
by "JSON could not be generated" (`postgrest/exceptions.py:53-68`). Specify a
**bounded, sanitized extractor** and where it runs. A global Flask handler misses
everything already swallowed by identity/quota/notification code or wrapped as
`PersistenceUnavailable`. Preserve propagation and operation context; never log
whole arbitrary response bodies.

This extractor is a **prerequisite for reliable P1 classification** and should
ship and be tested with it.

### P5 — Present-but-invalid key defeats the safety guard (MEDIUM — remedy corrected)

`supabase_client.py:150-161` checks `not url or not key`. Its comment promises a
missing admin key "fails in the safe direction." A present-but-foreign key sails
past it and 401s on every call instead, and nothing logs which key was chosen.

**Revision 1 proposed treating a 401 as "no admin backend." That is WRONG and
must not be implemented.** Returning `None` for a configured-but-invalid
credential would:

- **Re-enable unmetered chat** via `_claim_daily_message`'s `backend is None`
  branch (`app.py:847-849`) — directly undoing P1.
- Turn notification failure into HTTP 200 with an empty list (`app.py:3101-3106`).
- **Silently reopen registrations.** `signup_enabled` returns the _deployed
  default_ when the backend is `None` (`settings_service.py:497-502`), but the
  last-known cached value or `None` (undetermined) when a read _fails_
  (`settings_service.py:509-520`). Collapsing the two can defeat an operational
  pause.

**Correct remedy:** three distinct states — _intentionally unconfigured_,
_configured and healthy_, _configured but unavailable_. Do not erase the
distinction by returning `None`. Startup validation is useful as a bounded
readiness check but needs a specified timeout, retries, recovery and failure
posture; an unconditional network requirement at startup changes an explicitly
deferred-backend design. Fix the misleading error text at
`supabase_client.py:156-160` (it names only `SUPABASE_SERVICE_ROLE_KEY` while
`SUPABASE_SECRET_KEY` is in use) and the stale admin-only framing at
`README.md:245-247` in the same concern.

### P6 — `/api/identity` hides degradation (MEDIUM)

Returns **200** during a total outage with `role: "user"`, `tier: "free"`,
`is_disabled: false` and **no `is_resolved`** (`app.py:2589-2603`),
indistinguishable from a healthy free-tier response.

**This breaks an existing test.** `test_identity_says_nothing_about_anyone_else`
asserts an **exact** top-level key set (`test_identity_roles.py:349-367`). Update
that assertion deliberately in the same commit, preserving its privacy intent.

Adding the field alone changes **no displayed behaviour** — frontend consumers
tolerate extra fields but do not read it (`services.js:650`, `app.js:458-474`,
`account.js:76-90`). Ship the payload change, the consumer change and the
contract test together.

Note `is_resolved` describes _identity resolution_, not backend health: a cached
resolved identity can coexist with a failed quota lookup. **It does not close the
disabled-account admission gap** (see §4).

### P7 — Notification polling has no backoff (LOW)

`handlers.js:1141` — `setInterval(tick, 45000)`, fixed, catch-and-return
(`handlers.js:1171-1192`). No backoff, cap, or failure counter. Bounded only by
sign-out (`handlers.js:1163-1169`) and tab-hide.

**The timer cannot currently infer failure** — `fetchActiveNotifications` catches
and returns, and success also returns nothing. Return a structured result, or
move scheduling somewhere that can distinguish success, failure, stale generation
and signed-out state. Use **completion-based scheduling** with capped backoff and
jitter, preserving immediate reconciliation, generation guards, teardown on
logout/account-switch/tab-hide, and Realtime-triggered refresh — otherwise a
stale request can reschedule polling, or a Realtime event can defeat the backoff.

**No test pins the 45s interval** (verified); `test_notifications_browser.py:106-144`
asserts broadcast-triggered refetch, not timing. Add deterministic tests for
cap/reset, overlap, teardown, account switch.

**Gates:** bump `ASSET_VERSION`; en/ar parity; browser suite and JS
format/lint hooks also apply.

### P8 — `.env` beats the real environment (LOW, deploy trap)

`app.py:107` uses `override=True`; `config_loader.py:31` does not. A systemd
`EnvironmentFile=` key rotation is **silently discarded**. Correction to
revision 1: importing `config_loader` first does **not** preserve its precedence
— `app.py:107` still runs on import (`app.py:211`).

"Pick one rule" is too vague. Prefer an explicit production policy where
**externally supplied configuration wins** and `.env` supplies missing
development values. This affects **all** settings, not just Supabase keys —
inventory conflicting values first. Cover script entrypoints too
(`scripts/smoke_real.py:43`, `eval_retrieval.py:44`, `eval_citations.py:58`).

### P9 — Two separate concerns (LOW)

**(a) Password lifecycle.** `.env:14` `supabasePassword` is read by no
application code, but that does not establish that database tools, backups or
another deployment do not use it. Inventory consumers, establish recovery access,
_then_ rotate and remove. Actual exposure is **UNVERIFIED**; escalate immediately
if exposure is established.

**(b) CSP metadata.** `SUPABASE_PROJECT_REF` is absent from `.env` though
`.env.example:17` documents it. Adding it does **not** tighten CSP while the
wildcard remains — `app.py:1607` adds the project origin, `app.py:1608` appends
`wss://*.supabase.co` unconditionally. Narrowing CSP needs its own compatibility
review.

### P10 — Documentation (folded into each change)

Revision 1 deferred this to a final cleanup commit. **That was wrong** — the
repo's rule is that a change fixes its document in the same commit
(`CLAUDE.md:187-189`). The deployment/restart/rollback runbook specifically
belongs in **P0's prerequisites**, not a later item. `docs/OPERATIONS.md`
documents external configuration but has no deployment procedure and no
key-failure runbook; `README.md:342-344` is the only existing guidance.

---

## 4. Missing items (added in revision 2)

| Severity     | Item                                                                      | Rationale                                                                                                                                                                                                                                                                                                                     |
| ------------ | ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Critical** | Production inventory, tested rollback, effective-environment verification | Local success cannot establish production recovery (P0.1-P0.6)                                                                                                                                                                                                                                                                |
| **High**     | Explicit _configured-but-unavailable_ state                               | Revision 1's P5 remedy would bypass quota and reopen registrations                                                                                                                                                                                                                                                            |
| **High**     | Disabled-account outage policy                                            | Unknown identity defaults to enabled (`identity_cache.py:86-101`); a stale resolved identity also cannot reflect a _later_ disable. A payload field does not enforce access — this needs a decision, not a field                                                                                                              |
| **High**     | Independent detection and alerting                                        | **No health or readiness route exists** (verified). Identity and notifications return degraded 200s, so ordinary uptime checks would not have caught this. Alert on unresolved identity, uncounted operation, persistence failure and credential rejection — independently of a console that is inaccessible during the fault |
| **High**     | SDK-boundary regression tests                                             | Quota tests use the in-memory backend and replace `claim`; neither exercises the real malformed-401 path (`test_quota.py`, `test_quota_routes.py:332-341`)                                                                                                                                                                    |
| **High**     | Incident impact assessment                                                | Restoring credentials does not reconstruct failed durable writes or uncounted usage. Quantify the affected period and recovery limits (`app.py:860-862,1360-1371`)                                                                                                                                                            |
| **Medium**   | Secret ownership, storage, retirement policy                              | Disk plaintext is not proof of compromise, but access control, distribution, backup and rotation ownership are unowned. Privileged keys bypass RLS                                                                                                                                                                            |
| **Medium**   | Independent Realtime and Auth-Admin acceptance                            | Separate provider paths; not proved by a PostgREST 200                                                                                                                                                                                                                                                                        |

---

## 5. Sequencing

1. **P0 runbook and credential inventory**, then restoration with rollback-capable
   acceptance checks. Nothing else may precede this.
2. **P1 + the minimum P4 extractor + regression tests**, as one quota-enforcement
   concern. Explicitly reject P5's `None` alternative.
3. **Detection/readiness + corrected P5 state handling**, with OPERATIONS changes.
4. **Decide the disabled-account outage policy**, then implement; ship P6's
   payload, consumers and contract test together.
5. **P2 classifier hardening**, preserving genuine refusals. Fixtures first.
6. **P3 constraints under Python 3.10**, before the separate publishable-key
   migration. If the classifier depends on an SDK version, constrain it with P2.
7. **P8 environment policy** after inventory; **P7** independently.
8. Split **P9(a) password** from **P9(b) CSP**.

One concern per commit. Documentation ships with each change, not at the end.

### Gates (verified against CI)

```bash
python -m pytest -m "not browser and not integration" --cov=web
python -m pytest -m browser --browser chromium
pre-commit run --all-files
mypy web
```

`.github/workflows/tests.yml` is the authority. The bare `ruff`/`npm` commands
are useful locally but are **not** the literal CI lint invocation and omit
Prettier. UI changes retain the asset bump, bilingual strings, existing
`runtime.*` namespaces, frozen copy and logical-CSS rules. No fix here requires
loosening RLS or browser-write access.

---

## 6. How this plan was verified

Five parallel investigation agents produced the findings; the orchestrator
re-verified each against source; two independent models then reviewed
adversarially.

**Review 1 (diagnosis).** Of ten claims: one **wrong** (chat returns HTTP 500 —
it streams uncounted instead, now P1), two **overstated** (P2's incident linkage;
a login-mislabel claim at `auth.py:352-360` with no linkage to this fault), one
**unverifiable** (P4's version range), six confirmed.

**Review 2 (this plan, revision 1).** Verdict on P0: **not safe to execute as
written**. P5's remedy judged **wrong** and dangerous — independently confirmed
here against `app.py:847-849` and `settings_service.py:497-520`. P6 found to
break `test_identity_roles.py:349-367`, confirmed. Four citations in revision 1
were off by one to three lines (`app.py` 474→476, 554→555, 1607→1608;
`README.md` 344-346→342-344) and are corrected above.

The corrections are folded into the plan rather than recorded separately, except
where a reversal is worth keeping visible — P5 and P0 carry explicit
"revision 1 was wrong" notes so the superseded approach is not reintroduced.
