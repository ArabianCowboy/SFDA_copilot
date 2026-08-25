STATUS: CURRENT AUTHORITY — state this repository cannot hold. Last verified 2026-08-25.

This file records configuration that lives in the Supabase dashboard, in DNS, and in a
third-party mail provider — none of it in version control, some of it write-only once saved.
That is why it is written down at all: six months from now the only other way to recover any
of it is to go and look.

Two things belong here and are not yet written up, both filed as open entries in `TODO.md`:
**bilingual GoTrue email templates**, and **whether this deployment's access logs retain full
`/c/<uuid>` paths**. When either is settled, the answer goes in this file.

Everything below concerns transactional email. As other out-of-repo state gets documented,
add it as a sibling section rather than a new file.

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
