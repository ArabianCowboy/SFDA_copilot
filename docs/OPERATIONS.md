STATUS: CURRENT AUTHORITY — state this repository cannot hold. Last verified 2026-09-12.

This file records configuration that lives in the Supabase dashboard, in DNS, in a
third-party mail provider, and on the VPS itself — none of it in version control, some of it
write-only once saved.
That is why it is written down at all: six months from now the only other way to recover any
of it is to go and look.

Three things belong here and are not yet written up, all filed as open entries in `TODO.md`:
**bilingual GoTrue email templates**; **whether this deployment's access logs retain full
`/c/<uuid>` paths**; and **the actual backup schedule and PITR status**, which the last
section below records as an assumption precisely because nobody has looked. When any of
them is settled, the answer goes in this file.

Five sections follow: transactional email, the registrations pause, database recovery,
Supabase API keys, and how the application server is launched. As other out-of-repo state
gets documented, add it as a sibling section rather than a new file.

---

# Transactional email: custom SMTP through Resend

**Status:** configured 2026-08-14, **delivery proven the same day.** See
[Verification](#verification) for what was confirmed and how — including the
thing that took longest to notice: the `mail.send` log line is _not_ the
evidence, and waiting for it would have left this file saying "unproven"
indefinitely.

This file exists because none of the state it describes lives in this
repository. The SMTP settings are in the Supabase dashboard, the DNS records are
at Hostinger, and the API key is write-only once saved. Six months from now the
only way to recover any of it is to go and look — so it is written down here,
along with how it was checked.

---

## Problem

New readers were not receiving signup confirmation email on the live deployment
(`sfda-copilot.aifoudahub.com`).

Observed on 2026-08-14: three signups within seven minutes produced one
successful send and two rejections. From the project's auth logs:

```
01:03:17  info     mail.send
01:06:45  warning  429: email rate limit exceeded
01:09:11  warning  429: email rate limit exceeded
```

**It failed worse than it looks.** GoTrue rolls the account back when the send
fails, so the reader got no account _and_ no email, and the address stayed free.
The browser surfaced Supabase's raw message — "email rate limit exceeded" —
which is English-only and phrased as though the _reader_ had exceeded a limit.

## Root cause

Supabase's built-in email sender (`noreply@mail.app.supabase.io`) is a shared
service documented for development, not production, and it is rate limited to
**2 emails per hour per project**. Three signups in an hour is over budget.

The limit is not a soft one and there is no way to raise it while using the
built-in sender.

## Solution

Custom SMTP through [Resend](https://resend.com), configured under
**Authentication → Emails** in the Supabase dashboard, sending from a verified
subdomain of a domain the project controls.

The auth service confirms the change in its own log — this line is the single
best evidence that custom SMTP is live, because GoTrue only raises this limiter
when a custom sender is configured:

```
2026-08-14T11:17:50Z  info  env GOTRUE_RATE_LIMIT_EMAIL_SENT changed,
                            updating Email limiter from 2/1h to 30
```

> **Correction worth carrying forward: the rate limit was raised, not removed.**
> Configuring custom SMTP moves GoTrue's own email limiter from 2/hour to
> **30/hour**. That ceiling is enforced by Supabase and is entirely independent
> of Resend's much larger allowance — so "Resend supports high volume" does not
> mean this project can send more than 30 emails an hour. Raise it under
> **Authentication → Rate Limits → Email sent** if 30/hour ever binds.

## Configuration

| Setting                   | Value                                                                                                                                       |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Supabase project          | SFDA Copilot — `yjjuudnsnjzhyqllsqrd` (org: ArabianCowboy's Org)                                                                            |
| SMTP host                 | `smtp.resend.com`                                                                                                                           |
| Port                      | `465` (implicit TLS)                                                                                                                        |
| Username                  | `resend`                                                                                                                                    |
| Password                  | A Resend API key. Write-only — Supabase does not display it after save. Rotating it means generating a new key in Resend and re-saving here |
| Sender email              | `noreply@sfda-copilot.aifoudahub.com`                                                                                                       |
| Sender name               | SFDA Copilot                                                                                                                                |
| Minimum interval per user | 60 seconds                                                                                                                                  |
| GoTrue email limiter      | 30/hour (raised automatically — see above)                                                                                                  |
| Resend sending region     | `ap-northeast-1` (Tokyo) — inferred from the MX target below                                                                                |

Everything in this table except the last two rows was reported by the person who
made the change; the last two were read from the auth log and from public DNS.

## DNS records

At Hostinger, on `aifoudahub.com`, for the `sfda-copilot` subdomain. **All four
were resolved from a public resolver (8.8.8.8) on 2026-08-14 and are live** —
these are the values actually serving, not the values that were meant to be
entered:

| Purpose          | Type | Name                                            | Value                                                                                                                                                                                                                        |
| ---------------- | ---- | ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DKIM             | TXT  | `resend._domainkey.sfda-copilot.aifoudahub.com` | `p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDIHUJ6/qbnz6o21LqYK5N7E19vcHjs6LNYlPS3P6xsrUvlhGCUKYqkUDVaHdobsAfCpVqQOAUgi/m4LDXVujvB6vIzl8A+eIFaN+PevgQQ/RezSQewUE8DEerBdF9IvQhb6lZ9CDP3YmoY3A71/t7DvR4r8Pall9BUnwTYZxyIrQIDAQAB` |
| SPF              | TXT  | `send.sfda-copilot.aifoudahub.com`              | `v=spf1 include:amazonses.com ~all`                                                                                                                                                                                          |
| Bounce/complaint | MX   | `send.sfda-copilot.aifoudahub.com`              | `10 feedback-smtp.ap-northeast-1.amazonses.com`                                                                                                                                                                              |
| DMARC            | TXT  | `_dmarc.sfda-copilot.aifoudahub.com`            | `v=DMARC1; p=none;`                                                                                                                                                                                                          |

Two things about this set are worth understanding rather than just recording.

**SPF and MX sit on the `send.` subdomain, deliberately.** Resend scopes them
there so they cannot collide with the root domain's own mail — the single most
common reason domain verification fails is adding these at the apex instead.

**`p=none` means DMARC is monitoring, not enforcing.** A message forging this
domain is reported, not rejected. That is the correct place to _start_ — you
watch before you enforce — but it is not protection, and it should not be
described as though it were. There is also no `rua=` address, so the aggregate
reports that `p=none` exists to collect are being sent nowhere. Adding
`rua=mailto:...` costs nothing and is the prerequisite for ever moving to
`p=quarantine`.

## Verification

**Confirmed:**

- All four DNS records resolve publicly (`Resolve-DnsName -Server 8.8.8.8`, 2026-08-14).
- Supabase accepted the SMTP settings and reloaded its auth API twice
  (11:17:50Z and 11:18:05Z).
- GoTrue raised its email limiter from 2/1h to 30, which it only does for a
  custom sender.

**Confirmed — mail is being delivered through Resend.** Three sends, all after
the 11:17:50Z SMTP change, each verified in the database rather than by eye:

| What                           | Evidence                                                                                                                                                                                                                        |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Signup confirmation            | `mohifouda@gmail.com` — `confirmation_sent_at = 12:06:22`, then `/verify 303` at 12:06:38 and `email_confirmed_at` set. Sixteen seconds is someone opening a real email and clicking a real link.                               |
| Password recovery              | `midoxp@gmail.com` — `recovery_sent_at` moved from null (since April 2025) to `16:48:19`.                                                                                                                                       |
| Recovery, completed end to end | `midoxp@yahoo.com` — `recovery_sent_at` set at `16:52:58`, then cleared once the single-use token was spent; `email_confirmed_at` set at `16:53:21` and `last_sign_in_at` at `17:03:47`, both previously null since 2025-11-16. |

**The `mail.send` log line is not the test, and this is the trap.** The only
`mail.send` in the auth log is still `2026-08-14T01:03:17Z`, from _before_ the
SMTP change — it has not appeared once for any of the three sends above.
Whatever raises that line, custom SMTP does not. An earlier version of this file
proposed watching for it; anyone who does will conclude delivery is broken while
mail is arriving. Read `auth.users` instead: `confirmation_sent_at`,
`recovery_sent_at`, and the state changes a used token leaves behind.

**Why a signup used to prove nothing, and now does.** Email confirmation was
disabled when this file was first written, and the trap is worth keeping:

```sql
select email, created_at, email_confirmed_at, confirmation_sent_at from auth.users;
-- midoxp@live.com | 2026-08-14 01:13:28.630 | 2026-08-14 01:13:28.655 | null
```

`confirmation_sent_at` null and the address confirmed 25 ms after the account was
created is auto-confirmation with no email attempted — a signup that _reads_ as a
pass while sending nothing. **Confirmation was re-enabled at 12:05:17Z** (auth log:
`reloading api with new configuration`, immediately before the 12:06:22 signup
above), so that hole is closed and `confirmation_sent_at` is now meaningful.

To re-prove delivery later, trigger a password reset for an existing account and
watch `auth.users.recovery_sent_at` move. It sends through the same SMTP
configuration without changing a project setting, and it is reversible.

Cross-check the Resend Activity log for the delivery itself. That is the only
place that distinguishes **accepted then bounced** from **accepted then ignored**
— the database can only tell you a send was accepted, which is why the app names
its audit action `password_reset_accepted` rather than `sent`.

Email confirmation being on is no longer an open question; the remaining decision
recorded in `TODO.md` was whether a confirmed address is _required to chat_, and
it is — GoTrue refuses to issue a session for an unconfirmed address, so the
enforcement sits at the session boundary and needs no application code.

## Troubleshooting and rollback

**Email stops sending.** Check Resend's Activity log first — it distinguishes
"never accepted" from "accepted then bounced", and those have different causes.
Then the Supabase auth log (`source = 'auth_logs'`) for `mail.send` versus a
`429`. A 429 after this change means the 30/hour GoTrue ceiling, not Resend.

**Domain shows unverified in Resend.** Re-resolve the four records above and
compare byte for byte. The usual failures are a record placed at the apex
instead of under `send.`, a DKIM value truncated by a DNS panel's field length,
or Hostinger having appended the domain to a name that was already fully
qualified (producing `send.sfda-copilot.aifoudahub.com.aifoudahub.com`).

**Mail arrives but lands in spam.** Expected while DMARC is `p=none` and the
domain has no sending reputation. It improves with volume; do not chase it by
changing SPF.

**Rollback.** Turn off the custom SMTP toggle under Authentication → Emails.
This is a one-click revert, and it drops the project back to the built-in sender
**and back to 2 emails/hour** — which is the original outage. It is a diagnostic
step, not an operating state. Leave the DNS records in place; they cost nothing
and re-enabling is then just re-entering the API key.

**Resend plan limits.** Not recorded here on purpose — they change, and a stale
number in a file is worse than no number. Read them from the Resend dashboard
when the answer matters.

---

## Related

- `TODO.md` — the reader-facing half is still open: the rate-limit message
  reaches the browser as raw English Supabase text with no key in either
  catalogue.
- `supabase/README.md` — migration conventions and how schema changes are applied.

---

# Registrations pause: what it covers, and what needs the dashboard

**Status:** built 2026-08-25. See `docs/registrations-pause-plan.md` for the full
design; this section is the part of it that lives outside the repository.

The console's **Registrations** control (`/admin` → Settings → Registrations)
refuses `POST /auth/signup` — the route the signup form actually calls — with a
`403 {"error": "signup_disabled"}`, and it is audited the same way a generation
settings change is.

**It is an application control, not a provider one.** `SUPABASE_URL` and the
publishable anon key are in every page by necessity, and
`POST /auth/v1/signup` against the project accepts a request carrying them
whatever this app's console currently says. Pausing here stops the product's
own signup form; it does not stop a caller who talks to GoTrue directly.

**For a hard close** — an incident where that residual path has to be shut
too — disable email signups at the provider:

- Dashboard: **Authentication → Sign In / Providers → Email**, toggle off.
- Or the Management API:

  ```bash
  curl -X PATCH "https://api.supabase.com/v1/projects/$PROJECT_REF/config/auth" \
    -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"disable_signup": true}'
  ```

That change is **outside this app's audit log.** If you make it, note it here
with the date and who made it, and lift both controls when the incident ends —
a provider-side close leaves the console still reporting "Open," and nothing in
this repository will tell you otherwise.

**Propagation is immediate, not TTL-bound — for a NEW request.** This
deployment runs a single worker, so a console toggle publishes the committed
value directly, and any request that reads the flag after the toggle sees it
immediately. The flag's cache (45s) exists only to bound staleness from an
edit made _outside_ this process, such as changing the `app_settings` row
directly in the Supabase SQL editor. Do not build TTL-shortening machinery
for the console path; it is not the propagation mechanism there.

**One narrow exception, corrected 2026-08-26.** `POST /auth/signup` re-reads
the flag twice — once at the top of the view, once immediately before the
GoTrue call — specifically to shrink this window, but a request that is
already past the second check when a pause lands can still complete: nothing
in this application makes "check the flag" and "create the account" one
atomic step. Closing that fully would need a database-level guard (a `BEFORE
INSERT` trigger on `auth.users`), which `docs/registrations-pause-plan.md` §4
explicitly rejects — it would also block admin-created accounts and any
provider-internal flow. In practice the window is one HTTP round trip to
GoTrue, and a pause used during an active incident should be treated as
"effective within about a request's length," not instantaneous for requests
already in flight.

**Failure posture.** If the settings store cannot be read at all and a value
was cached from an earlier successful read, that value is served however
stale — a pause must survive a Supabase blip without silently reopening
signups. Only a process that has _never_ successfully read the flag (a cold
start during an outage) answers `503 {"error": "auth_unavailable"}` rather than
guessing. See §5 of `docs/registrations-pause-plan.md` for the full argument.

**Confirm email must stay enabled** (Authentication → Emails → Confirm email).
Signup is server-mediated: with Confirm email **on**, GoTrue returns a user and
no session, `/auth/signup` answers `201`, and the browser shows the
check-your-mail panel — today's behaviour. Turning Confirm email **off** would
have GoTrue return a session to the _server_, which does not forward it, and a
reader would be told to check mail that never arrives while holding no
session. That would need a code change first, not just a dashboard toggle.
**Verified on 2026-09-06** by reading the dashboard directly (Authentication → Sign In
/ Providers → User Signups): Confirm email is on, and so is _Allow new users to sign
up_; _Allow manual linking_ and _Allow anonymous sign-ins_ are both off, which is the
wanted state — this application never calls GoTrue's identity-linking or anonymous
sign-in APIs.

---

# Database recovery, and the timeouts nobody has measured

Added 2026-08-28, when `docs/database-improvement-plan.md` was applied and the
database's recovery position turned out to be written down nowhere.

## Backups and point-in-time recovery — an assumption, not a fact

**Somebody must confirm this in the dashboard and replace this paragraph with what
they found.** The MCP `get_project` response reports status, region and Postgres
version and says nothing about backup schedule or PITR, so it cannot be answered from
the repository or from an agent session. The advisor's standing
`auth_leaked_password_protection` finding tells us the project is below the Pro tier,
and PITR is a paid add-on — so the working assumption is **daily backups, no PITR**,
and that assumption has never been tested.

For a database whose entire content is user-generated and unreproducible — reader
conversations, an audit log of administrative action, consent records — the recovery
point objective is a fact the operator should be able to state without logging in.

Two actions, in order:

1. **Read Database → Backups** and write the schedule and retention here.
2. **Rehearse a restore into a scratch project, once.** That is what turns a setting
   into a known-good procedure. The database is roughly 14 MB; this is the cheapest it
   will ever be to practise, and the cost only ever rises.

## Before any migration that could touch data

The MCP tools cannot produce a backup — there is no `pg_dump` and no direct
connection. **A restorable copy has to come from the dashboard (Database → Backups) or
a `pg_dump` run from a machine holding the connection string.** Take one before
applying anything that is not purely a grant or a function body.

For migrations that are _supposed_ to touch no rows — grants, policies, function
bodies — a content-hash baseline is the cheap check that they did not. The query is in
[`supabase/README.md`](../supabase/README.md#checking-that-a-migration-touched-no-rows).
Capture it before, compare after; expect drift only on `audit_log` and
`user_notification_reads`.

Store the baseline **outside this repository**. It names real account ids and the live
runtime configuration.

## `service_role` has no `lock_timeout`, and its statement timeout is unverified

`pg_roles` gives `anon` `statement_timeout=3s`, `authenticated` and `authenticator`
`8s` (plus `lock_timeout=8s` on `authenticator`), and **`service_role` nothing at all**.
So exactly one role sets a `lock_timeout` — `authenticator` — and **`service_role` and the
cluster default set none**, which is the gap that matters because `service_role` is the
role Flask's writes execute as. Nothing anywhere sets an
`idle_in_transaction_session_timeout`.

Do not read the cluster's `statement_timeout = 120000` as service_role's effective
value. That figure was observed from an MCP session, which is not how Flask reaches the
database: Flask calls PostgREST, which logs in as `authenticator` and switches role per
request, reading each role's `rolconfig` as it goes — this database's own
`pg_stat_statements` records it doing so. With no `rolconfig` on `service_role` there is
nothing to apply, so a service-role request most likely inherits `authenticator`'s 8s.
**That is a deduction from the mechanism, not a measurement.**

Why it matters: `chat_append_turn` takes `select … for update` on the session row and
holds it until the function returns. A stalled transaction holding that lock has no
`lock_timeout` bounding the waiters, so every subsequent turn in that conversation
blocks until whatever the statement timeout really is fires. The app is single-worker,
which narrows this considerably — it is a gap in the layer below the app, not an active
incident.

**Measure before setting anything.** Add a temporary reporter, call it as `service_role`
through `/rest/v1/rpc/`, read what comes back, then drop it in its own migration:

```sql
create function public._timeout_probe()
returns table (stmt text, lock text, idle text)
language sql security definer set search_path = ''
as $$ select current_setting('statement_timeout'),
             current_setting('lock_timeout'),
             current_setting('idle_in_transaction_session_timeout') $$;
revoke execute on function public._timeout_probe() from anon, authenticated, public;
grant execute on function public._timeout_probe() to service_role;
```

Only then decide the numbers. `alter role service_role set lock_timeout = '8s'` mirrors
`authenticator` and is the safe half. **Tightening `statement_timeout` on `service_role`
changes the operator's own environment as well as the app's** — it is what the Supabase
MCP tools and any administrative script connect as, so a long maintenance query would be
aborted. That is usually the right trade and it should be a decision, not a side effect.

An `idle_in_transaction_session_timeout` would **not** bound the lock above. It acts on a
transaction that is idle, and a PL/pgSQL function still executing is not idle. It is worth
setting as a backstop against a client that dies mid-transaction; it is not a fix for that
lock, and an earlier draft of the plan wrongly implied it was.

---

# Supabase API keys: what breaks, and how to get it back

Written 2026-09-07, the day this was needed and did not exist. On that date a
`sb_secret_` key that belonged to a **different Supabase project** was sitting in
`SUPABASE_SECRET_KEY`, and every privileged call returned
`401 {"message":"Unregistered API key"}`. Diagnosis took a working session because nothing
here said which key does what, and the one relevant log line was actively misleading. The
full incident write-up is `docs/supabase-key-incident-fix-plan.md`; this is the part you
need at 2am.

## Which key does what

Three credentials, three blast radii. Confusing them is most of the diagnostic difficulty.

| Variable                                                           | Client                                                                                   | If it breaks                                                                                                          |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `SUPABASE_ANON_KEY`                                                | the browser, and Flask's GoTrue calls (`web/utils/supabase_client.py`, `SupabaseClient`) | **Sign-in stops working.** It is also rendered into every page, so the browser's own Supabase calls fail too.         |
| `SUPABASE_SECRET_KEY`, falling back to `SUPABASE_SERVICE_ROLE_KEY` | the service-role client (`SupabaseAdminClient`)                                          | **Everything privileged**: conversation history, notifications, the daily allowance, `/admin`. Sign-in keeps working. |
| `SUPABASE_PROJECT_REF`                                             | the Realtime CSP origin only                                                             | Realtime falls back to a wildcard origin. Not an outage.                                                              |

The asymmetry is the thing to internalise: **you can be signed in, with a working session,
while every privileged read fails.** That is what a broken service key looks like, and it
does not look like an auth problem.

## The symptom signature

You have a service-key fault if:

- `/api/chat/sessions` and `/api/notifications/active` return **503**, while
- `/api/identity` returns **200**, and
- the reader stays signed in, and
- **the administration link disappears for a known administrator.**

That last one is the most confusing and the most diagnostic. The admin role is read from
`profiles` through the service key; when that read fails, `resolve_identity_flags` falls
back to `IdentityFlags.unknown()`, `is_admin` requires `is_resolved`, and the console link
is hidden. A missing admin button therefore means **authentication succeeded** — the app
got far enough to know who you are and then failed to look up what you are.

If instead **sign-in itself** fails, suspect the anon key, not the secret key.

## Triage: three commands

Run from the deployment host, against the deployment's own environment.

```bash
# 1. Which project is configured?
echo "$SUPABASE_URL"          # -> https://<ref>.supabase.co

# 2. Does the service key work? 200 = healthy, 401 = this is your problem.
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "apikey: $SUPABASE_SECRET_KEY" -H "Authorization: Bearer $SUPABASE_SECRET_KEY" \
  "$SUPABASE_URL/rest/v1/"

# 3. Does the anon key work? (200 expected; this one is about sign-in.)
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "apikey: $SUPABASE_ANON_KEY" "$SUPABASE_URL/auth/v1/health"
```

`401 Unregistered API key` means the key is not registered **for this project**. That is
different from expired and different from malformed:

- A **legacy JWT** key (`eyJ…`) encodes its project. Decode the middle segment and compare
  its `ref` claim to the host in `SUPABASE_URL`; check `exp` while you are there.
- A **new-format** key (`sb_secret_…`) encodes nothing. It is structurally valid or not,
  and only a live call tells you whether it belongs to this project. This is why the
  2026-09-07 key looked perfect and was not.

## Recovery

1. **Establish scope first.** Local and production have separate `.env` files. A working
   local app tells you nothing about production. Check each one with the commands above.
2. **Mint a replacement**: Supabase dashboard → Project Settings → API Keys → Secret keys →
   Create, _in the project whose ref matches `SUPABASE_URL`_.
3. **Verify the candidate before cutting over**, using command 2 above with the new value.
   A `200` from `/rest/v1/` is necessary but not sufficient — application reads also need
   table grants and RPC execute, so plan to run the acceptance checks below.
4. **Write it to the source the deployment actually reads.** Since 2026-09-07 the real
   environment wins over `.env` (`web/api/app.py`, `override=False`), so a systemd
   `EnvironmentFile=` or container `-e` value is honoured. Variables set in both places are
   logged by name at startup.
5. **Restart the process.** Non-negotiable: `SupabaseAdminClient` caches its instance on the
   class (`web/utils/supabase_client.py`), so a running worker never re-reads the key.
   Editing the file alone changes nothing.
6. **Confirm from the log.** Startup now prints `Supabase admin client built from <NAME>`,
   which tells you which variable won. If that name is not the one you just edited, stop:
   the other variable is shadowing it.

**Rollback:** keep the previous working value until the acceptance checks pass. Do **not**
rotate the JWT signing secret as part of this — that invalidates the anon key and every
live session at once, turning a privileged-read outage into a total one.

## Acceptance checks

HTTP 200 is not sufficient anywhere here: several routes deliberately swallow their own
failures, which is why the incident looked healthier than it was.

- `/api/identity` — expected role and tier, **and a populated `quota`**. A `null` quota
  means the service key is still failing.
- `/api/chat/sessions` — a real list, not a 503.
- The administration link is visible again for an administrator.
- One controlled question through chat: the answer streams, the counter increments, and the
  turn survives a reload.
- Notifications: the bell loads, and a targeted notification actually arrives over Realtime
  — REST success does not prove broadcast delivery.

## What this deployment does while the key is broken

Worth knowing, because it changes how urgent the page is:

- **Chat keeps working.** Answers stream, and until 2026-09-07 they streamed _uncounted_ —
  every reader had unmetered LLM access for the duration. There is now a budget: five
  consecutive claim failures or two minutes, then chat answers 503 rather than serving free
  answers indefinitely (`ClaimFailureTolerance`, `web/services/quota_store.py`).
- **Nothing is saved.** Durable writes fail, so the conversation is gone on reload.
- **Disabled accounts are admitted** on a cold cache, because "we could not check" resolves
  to enabled. Documented and accepted (`web/services/identity_cache.py`), but during a
  credential outage the window is indefinite rather than 30 seconds.
- **Nothing alerts.** There is no health or readiness endpoint, and `/api/identity` answers
  200 while degraded, so an ordinary uptime check sees a healthy app. Both times this has
  happened, a human noticed first. Filed in the incident plan as an open item.

## One more thing that has bitten twice

On 2026-09-07 a **second** credential failed within hours of the first: `OPENAI_API_KEY`,
which presents completely differently — chat returns 500 and the log carries
`openai.AuthenticationError: invalid_api_key` — and is unrelated to Supabase. When
something breaks right after a credential fix, check whether it is a _different_ credential
before assuming the fix failed or that a recent commit caused it.

---

# How the application server is actually launched

Added 2026-09-12, after an audit found the running deployment disagreeing with
`docs/ARCHITECTURE.md` and nobody able to say so from the repository. The unit file is not
in version control and cannot be — it holds paths, a user, and a bind address belonging to
one host — so what it contains is written here instead. `TODO.md`'s closed entry
_Production runs two workers and binds wider than loopback_ (now in
[`docs/archive/TODO-resolved.md`](archive/TODO-resolved.md)) records how the divergence was
found and what it cost.

**The unit:** a systemd service on the VPS, `Restart=always` with `RestartSec=10`, running
gunicorn from the deployment's own virtualenv. **This file has no copy in the repository, so
this block is the only reviewable record of it — when the unit changes, change this block in
the same session, or the next reader is misled the way the `--workers` drift misled everyone.**
Read from the live box on 2026-09-12, after `--workers` was removed:

```ini
[Service]
User=www-data
WorkingDirectory=/var/www/sfda-copilot
Environment=PATH=/var/www/sfda-copilot/venv/bin
EnvironmentFile=/var/www/sfda-copilot/.env
ExecStart=/var/www/sfda-copilot/venv/bin/gunicorn --bind 127.0.0.1:5001 \
  --threads 8 --preload --max-requests 1000 --max-requests-jitter 100 \
  --chdir /var/www/sfda-copilot web.api.app:create_app()
Restart=always
RestartSec=10
Environment=BEHIND_PROXY=true
```

**There is deliberately no `--workers` here.** The count lives in `gunicorn.conf.py` at the
repo root, which is in git and gets diffed like any other file. A flag restated here would be
applied last (`gunicorn/app/base.py:189`) and would silently win, which is the drift this whole
arrangement exists to prevent. Verified live after the change: no `--workers` in the running
command line, one master plus exactly one worker, HTTPS 200, `NRestarts=0`.

Key facts from this service definition:

- **`WorkingDirectory=/var/www/sfda-copilot`:** gunicorn's launch cwd **is** the repo root,
  so a committed `gunicorn.conf.py` is discovered automatically
  (`gunicorn/config.py:583` resolves `./gunicorn.conf.py` against the launch cwd).
  **Do not remove this line thinking `--chdir` covers it — it does not.** Proved on the box
  with `gunicorn --print-config`: run from the repo root the output carries
  `raw_env = ['SFDA_CONFIG_WORKERS=1']`, and run from `/tmp` with `--chdir` pointing at the
  repo it carries `raw_env = []`. **`--chdir` plays no part in discovery at all** — and note
  that `--print-config` reports `config = ./gunicorn.conf.py` in _both_ cases, so that line is
  not evidence of anything. `raw_env` is. (`workers = 1` also shows either way, because that is
  gunicorn's own default.) If someone later tidies the unit and drops `WorkingDirectory=` as
  "redundant next to `--chdir`", the config file goes silently decorative again — the same
  failure as the original drift, with a new cause.

  **Do not try to verify this through `/proc/<pid>/environ`.** `SFDA_CONFIG_WORKERS` will be
  absent there even when everything is working: gunicorn assigns `raw_env` into `os.environ`
  _after_ exec, and `/proc/<pid>/environ` only ever shows the original exec-time block. The
  ordering is still correct for the app — the assignment happens before `preload_app` imports
  it (`arbiter.py:112`/`:117` on production's 23.0.0, `:133-136`/`:138` on 26.0.0) — but the
  proof is `--print-config`, not `/proc`.

- **`--chdir` targets that same directory:** Launch cwd and `--chdir` target coincide.
  `Application.chdir()` (`gunicorn/app/base.py:83-90`) runs `sys.path.insert(0, self.cfg.chdir)`
  which makes `web.api.app:create_app()` importable.
- **`EnvironmentFile=/var/www/sfda-copilot/.env`:** `systemd` injects `.env` **before**
  gunicorn starts, so gunicorn and the app see the same values. `Environment=BEHIND_PROXY=true`
  is redundant with `.env` but harmless.
- **Deployment is `git pull` into `/var/www/sfda-copilot`:** The deployment root is the live
  working tree, so committed files arrive with no extra machinery.
  **`chown -R www-data:www-data` afterwards is a required step, not tidying.** A pull run as
  root leaves the new working-tree files and `.git` objects owned `root:root`. Nothing breaks
  loudly — mode 644 means gunicorn still reads them — but the _next_ pull run as `www-data`
  fails on those objects. Running `git status` or `git diff` as root afterwards rewrites
  `.git/index` back to `root:root`, so do the `chown` **last**, after any root-run git command,
  and verify with `ls -l .git/index`.
- **Check the size of the gap before pulling.** On 2026-09-12 a pull described as "a config
  file lands" was in fact 36 commits, 73 files, +9,300/−497. `git log --oneline HEAD..origin/main`
  and `git diff --stat HEAD..origin/main` first, then confirm whether `requirements.txt`
  changed (a `pip install` is needed) and whether `supabase/migrations/` gained anything
  (schema goes before code). Smoke-booting the new code as a second gunicorn on a spare
  loopback port before restarting the live one turns the restart into a known quantity.
- **Gunicorn version divergence:** Production runs gunicorn **23.0.0**; the development tree
  runs **26.0.0** (due to unpinned `requirements.txt`). Cwd config discovery and `raw_env`
  injection before `--preload` were verified empirically on 23.0.0.

**How the worker count got here, 2026-09-12.** The unit carried `--workers 1` directly until
this date, and had carried `--workers 2` for months before that without anyone noticing,
because nothing reviews the file. The count moved into `gunicorn.conf.py` and the flag was
removed from `ExecStart` the same day; the app's own guard was rewritten in the same commit to
read the config file's declaration. The flag and the file cannot both name it — see the note
above the unit block.

Why each of the load-bearing arguments:

- **Worker count (`workers = 1`)** is in `gunicorn.conf.py` per [`ARCHITECTURE.md`](ARCHITECTURE.md#single-worker).
  The app warns at startup if launched with more than one worker (`_configured_worker_count`, `web/api/app.py`).
- **`--bind 127.0.0.1`** because nginx is the only thing that should reach it. Bound wider,
  a caller who could skip nginx would choose their own `X-Forwarded-For` — and therefore
  their own rate-limit bucket and their own address in the audit log — because
  `BEHIND_PROXY=true` makes the app trust one hop.
- **`--threads 8`** gives eight request slots, which per-tab conversations need: one reader
  can legitimately hold several SSE streams open at once.
- **`--preload`** builds the FAISS index and the model once in the master before forking.

**Two things this line does not say, both deliberate for now:**

- **No `--timeout`,** so gunicorn's 30-second default applies where `ARCHITECTURE.md`'s
  example writes `--timeout 300`. On the `gthread` worker this is not the hazard it looks
  like: the worker's accept loop calls `notify()` about once a second no matter how long a
  request thread runs (`gunicorn/workers/gthread.py`, its `run` loop), so a long SSE answer
  does not starve the arbiter's heartbeat and is not killed. Adding `--timeout 300` would
  match the documented line and cost nothing; it is not urgent.
- **`--max-requests 1000`** recycles the single worker roughly every thousand requests. The
  replacement forks from the preloaded master and the listen backlog covers the gap, but the
  retiring worker only waits `graceful_timeout` (30 seconds by default) for work in flight,
  so an answer still streaming after that point would be cut. Raising
  `--graceful-timeout` to match the longest expected answer is the fix if that is ever seen;
  removing `--max-requests` is not, since it is what bounds this process's memory growth.

**This host runs several other applications** on the same two vCPUs. Anything measured here
— throughput, memory, latency — is measured against that, not against an idle box. A baseline
read on 2026-09-12, after the worker had served 71 requests: true footprint by PSS is master
652 MB plus worker 783 MB, about **1.4 GB**; box-wide 2.8 GB of 7.9 GB used, swap untouched.
RSS is misleading here — under `--preload` master and worker share roughly 426 MB dirty, and a
freshly forked worker reads as ~8 MB private until copy-on-write pages diverge.

**Two operational details that look like trivia until they cost an hour:**

- The production virtualenv is `venv/`, while this repository's is `.venv/`. A command copied
  from `CLAUDE.md` runs the wrong interpreter on the box, and vice versa.
- There is **no `.service.d/` drop-in directory**. When triaging a setting that does not match
  this file, that rules out an override rather than leaving it as an open question.

## nginx: what the proxy actually sets

Read 2026-09-12 from `/etc/nginx/sites-enabled/sfda-copilot` (a symlink into
`sites-available/`). Beware: **`grep -r` does not follow symlinks found during recursion, so it
returns nothing here and reads as "not configured" — use `grep -R`, or `nginx -T`.**

```nginx
proxy_pass http://127.0.0.1:5001;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

The vhost's only non-Certbot include is `snippets/security-headers.conf`, which sets six
`add_header` directives and no `proxy_set_header`. So every proxy header is the list above.

**This settles the open proxy question** in
[`auth-login-rate-limit-plan.md`](auth-login-rate-limit-plan.md) §4 C1. `X-Forwarded-For` is
set with the appending `$proxy_add_x_forwarded_for` form, `BEHIND_PROXY=true` makes `ProxyFix`
trust exactly one hop, and gunicorn is loopback-only so the header cannot be forged from
outside. Rate-limit keys are therefore per-reader, not one global bucket.

**Streaming rests on one application header, with no nginx backstop.** `proxy_buffering`
appears **nowhere** in `/etc/nginx/`, so it is at nginx's default of **on**. SSE works only
because the app sends `X-Accel-Buffering: no` (`web/services/sse.py:40`), which nginx honours
per response. If that header were ever dropped, or a streaming response were built without
going through `sse.py`, nginx would buffer whole answers and streaming would die silently with
nothing in the nginx config to catch it. Note this diverges from the snippet `README.md`
documents, which puts `proxy_buffering off` in a `location /api/chat/stream` block that the
live vhost does not have. Adding `proxy_buffering off;` to the vhost would make it
belt-and-braces; it is a safe, zero-risk edit.

Compression is not a risk: `nginx.conf:53`'s `gzip_types` omits `text/event-stream`, and the
app also sends `Cache-Control: no-cache, no-transform` (`web/services/sse.py:37`).

**Firewall:** UFW only, active, default-deny inbound, with 22, 80 and 443 open. There is no
cloud-provider firewall in front of it — the box is a KVM guest with a NoCloud (ISO-seeded)
datasource, so there is no provider metadata service or network filtering layer to check.
