STATUS: PROPOSAL for questions 1-3 — recommended, none taken, awaiting the operator's
sign-off and, for question 1, a lawyer's. **Question 4 is IMPLEMENTED, 2026-08-28** — the
operator decided the opposite of this document's original recommendation, and §4 now
carries the full buildable design, its review history, and its shipped migrations, code
and tests in place of that recommendation. Applied and verified against the live
database; not yet committed to git. See the correction notice at the top of §4 before
reading it.
Researched and adversarially reviewed 2026-08-28.

# Four data-policy decisions

`TODO.md` carries four entries that are blocked on a decision rather than on engineering.
Each one stops a small piece of work, and none of them can be settled by reading the code —
they are questions about what this product owes its readers and its regulator.

This document brings back what the industry actually does, argues the four questions out, and
proposes an answer to each with the implementation sequence that follows from it.

## How this was produced

Two independent passes, then an adjudication.

1. **Research** — an Antigravity pass (`gemini-3.7-flash-high`) asked for the community and
   industry consensus, the competing positions, and what decides between them for an
   application of this shape.
2. **Opposition** — an OpenCode pass (`muse-spark-1.2`, read-only) asked to attack all four
   recommendations, ranked by the cost of acting on them wrongly.
3. **Adjudication** — every contested point settled against the repository or the live
   database rather than split. Three of the four recommendations changed as a result, and the
   opposition's own preferred mechanism for question 2 was disproved by direct test.

The disagreements are recorded below rather than smoothed over, because on three of these
four the first answer was the confident one and the second was the correct one.

---

## The four decisions, in one table

| #   | Question                                           | Recommendation                                                                                                                                                               | Cost if wrong                                                                                                |
| --- | -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| 1   | How long do we keep transcripts and the audit log? | **Life of the account for transcripts, no automatic timer. Minimum 12 months for the audit log, with no deletion mechanism built yet.**                                      | **Highest, and irreversible.** Deleting a regulatory professional's work record on a timer cannot be undone. |
| 2   | What does "disabled" mean?                         | **A full freeze on identity fields — but consent withdrawal must survive it, through a new RPC, not an RLS carve-out.**                                                      | Medium. Getting it wrong either leaves a hole open or blocks a right the law does not let you block.         |
| 3   | `chatbot_settings` — drop or use?                  | **Drop it, in its own migration, next time the schema is touched. Not urgent.**                                                                                              | Low. Recoverable from git.                                                                                   |
| 4   | `last_seen_at` — write or drop?                    | ~~Neither. Stop displaying it. Leave the column alone.~~ **Reversed by the operator — write it, via a dedicated `profile_last_seen` table. Implemented 2026-08-28; see §4.** | Low, but the obvious answer is the expensive one.                                                            |

---

## 1. Retention

**This is the one with real law in it, and the one where both passes should be read with
suspicion.**

### The recommendation

**Chat transcripts (`chat_sessions`, `chat_messages`, `chat_message_sources`): retain for the
life of the account.** No automatic time-based deletion. The reader deletes their own
conversations whenever they want — that path already exists and works. When an account is
deleted, its conversations are purged after a 30-day grace window.

**Audit log: retain for a minimum of 12 months. Do not build a deletion mechanism yet.**
Write the rule down; build the purge when there is something to purge.

**`chat_archive`: it is dormant and it stays dormant.** No collection means no retention
question. If it is ever switched on, it does not get switched on without a delete path.

### Why not the 180-day timer the research proposed

The research pass recommended a 180-day rolling inactivity TTL on transcripts, benchmarked
against OpenAI, Microsoft Copilot and Veeva. The opposition pass called this a category
error and it is right.

Those benchmarks are consumer chat products and _search query logs kept for analytics_. This
is neither. `docs/PRODUCT.md` describes the reader as a regulatory-affairs or
pharmacovigilance professional asking a question they need to be able to **defend to a
colleague or an auditor**. That makes a transcript a work record, not a session artifact.

The failure mode is concrete: an officer is inspected eleven months after a submission and
needs to show which SFDA guidance they relied on. A 180-day sweep deleted it, silently, in
bulk, with no export and no warning. Nobody would choose that; it would arrive as a
side-effect of copying a consumer product's default.

Note also that the benchmark was read backwards. OpenAI Enterprise's _default_ is retention
until the user deletes; the TTL is opt-in and admin-configured. The research pass turned an
opt-in ceiling into a mandatory sweep.

**And there is no problem to solve.** 56 message rows. Four accounts. There is no storage
cost, no performance cost, and no breach-surface argument that a hundred rows can carry.
Deleting is the liability here, not keeping.

### Why the audit log gets a different answer

The research pass was right that transcripts and the audit log are not the same question, and
its reasoning holds: different owner, different purpose, different legal basis. A reader owns
their transcript and can ask for it to be destroyed. Nobody owns the audit log except the
operator, and its whole point is that it can be trusted later — a subject-erasure request
does not reach into the record of who administered what.

But the research pass then recommended a **strict** 12-month window, deleting anything older.
That inverts the control it cites. Log-retention rules of this kind set a **floor** — keep at
least twelve months — not a ceiling. Deleting at exactly 365 days satisfies nothing and
destroys forensic value. The rule is "at least twelve months," and the correct posture today
is to write that down.

### Why not partitioning

The research pass recommended converting `audit_log` to monthly range partitioning so old
partitions can be dropped without tripping the append-only trigger. The mechanism is real —
`DROP TABLE` on a partition does not fire row-level triggers — and it is wildly
disproportionate here.

Measured on the live database: **121 rows, accumulated over 14 days — about 8.6 rows a day, so
roughly 3,100 a year.** Ten years of this table is thirty thousand rows. Postgres does not
notice thirty thousand rows.

Against that, converting an existing table to partitioned cannot be done in place. It means
building a new partitioned table, copying the data, swapping names, recreating three indexes,
re-applying the `REVOKE` and the append-only trigger, and living with the window in between —
on the one table in this schema whose entire value is that it has not been tampered with. Then
it means a privileged scheduled job holding partition-drop rights forever.

When a purge is eventually needed, the shape is a `security definer` function owned by
`postgres` that refuses a cutoff more recent than twelve months and writes an audit row about
the purge before performing it. That is a few dozen lines, it fits the RPC contract this repo
already has, and it does not exist yet because it does not need to.

### `chat_archive` — the gap both passes nearly missed

The research pass did not mention `chat_archive` **once**. That is the table where retention is
actually hard, and leaving it out is what makes a retention policy incomplete rather than
merely conservative.

It is a pseudonymous training record keyed by HMAC digests of the owner and session ids. It has
**no foreign key to anything**, so a reader deleting their history does not touch it. It has
**no delete path at all** — that is deliberate and documented. It is currently empty because its
salts are unset.

Two things follow.

**While dormant, the policy is "we do not collect."** There is no retention period to set
because there are no rows. That is the current state and it is a coherent one.

**It must not be switched on in its current shape.** A table that cannot be deleted from is
incompatible with any erasure obligation and with the account-deletion work already in
`TODO.md`. The precondition for setting those salts is a purge path — both a
cutoff-based purge and a per-owner purge that computes the HMAC inside the function rather than
accepting it from a caller — plus the reader-facing disclosure and opt-out that
`web/config.yaml`'s `archive_disclosed` guard already insists on.

Worth stating plainly for whoever revisits this: **pseudonymised is not anonymised while the
operator still holds the salt.** Destroying the salts would anonymise the history, and would
also destroy the ability to honour a future erasure request against it. That is a real trade,
not a loophole, and it should be made deliberately if it is made at all.

### The legal citations — read this before quoting any of it

The research pass cited specific article numbers: PDPL Articles 3, 4(4), 5, 13 and 18,
Implementing Regulations Articles 18 and 21, an NCA cybersecurity control numbered 2-8-3 with a
twelve-month log mandate, and the Saudi Commercial Books Law with a ten-year record rule.

**It was asked to mark anything recalled rather than verified. It marked nothing.** A
compliance document with no uncertainty in it is not a confident document; it is an unmarked
one.

The opposition pass and I agree on where the line falls:

- **The principles are sound and safe to rely on.** That personal data must be destroyed when
  the purpose for collecting it ends; that retention must be tied to a stated purpose; that
  there are narrow exceptions for a statutory retention duty, for genuine anonymisation, and
  for defending a legal claim. These mirror well-established data-protection principles and the
  reasoning above does not depend on any specific article number.
- **The article and control numbers are exactly what a language model invents.** Neither pass
  read the Arabic PDPL text or the Implementing Regulations. Getting the principle right and
  the number wrong is the characteristic failure, and a wrong article number in a compliance
  file is worse than no number.
- **The pharmacovigilance analysis is sound and is the load-bearing one.** GVP retention
  obligations — the ten-year-plus rules — attach to marketing authorisation holders, sponsors
  and official reporting channels. This product is a reference tool that reads public
  guidance; a professional asking it about reporting timelines is not lodging a report. That
  distinction is why transcripts are not subject to a decade-long floor, and it is the single
  most important conclusion in this section.

**Therefore: cite the principle, never the number, until somebody has the primary text open.**
Before this policy is published anywhere reader-facing, a Saudi-qualified lawyer or the
operator's DPO should confirm it. Nothing in this document should reach a privacy policy on an
agent's say-so.

### What to implement

Nothing, immediately, except writing the decision down. That is the point: the entry in
`TODO.md` is blocked on somebody owning a number, and the answer is that two of the three
numbers should be "no timer" and the third should be a floor rather than a job.

1. Record the policy in `docs/OPERATIONS.md` — transcripts kept for the life of the account,
   audit log kept at least twelve months, archive not collected.
2. Update `docs/PRODUCT.md` and the privacy policy so the stated purpose of storing a
   conversation is "so the reader can return to it," which is what makes life-of-account
   retention defensible.
3. Leave the purge mechanisms unbuilt. Revisit when `audit_log` passes a hundred thousand rows
   or a lawyer sets a ceiling.
4. Add the `chat_archive` preconditions to `TODO.md` so switching the salts on cannot happen
   quietly.

---

## 2. What "disabled" means

### The recommendation

**Disabled means the account is frozen — with one carve-out that is not optional.**

A disabled reader cannot use the product and cannot edit their name, organization,
specialization, age or preferences. They **can** still withdraw marketing consent, and that
has to keep working through the product rather than through an email address.

### The problem being fixed

`profiles` is the one table the browser writes directly. Flask refuses a disabled account, but
the RLS policy on `profiles` checks only that the row belongs to the caller. So a disabled
reader holding an unexpired token can still `PATCH` their own profile over PostgREST with Flask
nowhere in the path — for up to an hour, which is the default access-token lifetime.

Both passes agree this is a gap rather than a design, and both agree the fix is to add
`is_active_account()` to the UPDATE policy. That much is settled.

### Where the two passes disagreed, and who was right

The research pass said a total freeze is fine, and that a disabled reader who wants to withdraw
consent should email a privacy inbox. **That is wrong, and it is the kind of wrong that
attracts a regulator's attention.** Withdrawing consent is required to be as easy as giving it.
Giving it, here, is a one-click toggle on the account page. Redirecting a locked-out reader to
an email address is precisely the friction that rule exists to prevent.

So the opposition pass is right that a carve-out is needed. **Its proposed mechanism is wrong,
and I tested it rather than reasoning about it.**

It suggested a second permissive UPDATE policy scoped to disabled users, intended to allow only
the consent columns. Applied to the live database in a transaction that was rolled back:

```text
disabled_user_consent      = ALLOWED   <- intended
disabled_user_first_name   = ALLOWED   <- NOT intended
```

A disabled reader could change their name too. **RLS restricts rows, not columns** — which is
already written down in this repository as collision #4 in `docs/ARCHITECTURE.md`, and is the
reason `20260814005509` had to protect columns with a `REVOKE` and a trigger rather than a
policy. Adding a second policy re-opens every column the reader holds a column grant on, all
eleven of them.

### The mechanism that does work

Freeze the policy completely, then reopen consent through a function — the same shape
`update_own_preferences` already uses for the one other thing a reader may write in a
controlled way:

1. `alter policy "Users can update own profile"` to add `and (select public.is_active_account())`.
2. Add `update_own_marketing_consent(...)`: `security definer`, `set search_path = ''`, writing
   only the consent columns, only for `auth.uid()`, and deliberately **not** gated on
   `is_active_account()`. Grant execute to `authenticated` — a third documented exemption from
   point 4 of the RPC contract, for the same reason `update_own_preferences` has one.
3. Point the account page's consent toggle at the RPC instead of the direct `PATCH`.

Leave `SELECT` open — a locked-out reader must be able to read `is_disabled` and
`disabled_reason` to be shown why. Leave `INSERT` open — it is the signup fallback, and there is
no profile row yet for `is_active_account()` to consult.

**Not adopted:** the research pass's five-state account model (active / deactivated / suspended
/ disabled / pending deletion). This product has one flag. Introducing four more states is a
feature request wearing a taxonomy, and nothing in the codebase or `TODO.md` asks for it.

### What to implement

Three migrations and one frontend change, in order — schema before code, per the repo rule:

1. `..._update_own_marketing_consent_rpc.sql` — the new RPC, granted to `authenticated`.
2. `..._profiles_update_requires_active_account.sql` — the policy change.
3. `static/js/account/handlers.js` — consent toggle calls the RPC. Bump `ASSET_VERSION`.
4. `supabase/README.md` — register the third contract exemption beside the other two.
5. `supabase/tests/rls_chat.test.sql` or a new `rls_profiles.test.sql` — assert a disabled
   reader cannot write `first_name` and **can** still withdraw consent. This is the assertion
   that would have caught the broken carve-out.

---

## 3. `chatbot_settings`

### The recommendation

**Drop it — in its own migration, the next time the schema is being touched anyway. It is not
urgent and it does not block anything.**

Both passes agree it should go, and the case is not close: zero rows, zero foreign keys in
either direction, zero triggers, and no reference anywhere in `web/`. It is a table created
through the dashboard before this project had migration discipline. Its browser grants were
revoked on 2026-08-28, so the only cost of keeping it is a row in the standing-findings
register that a reader has to evaluate and dismiss every time they audit the advisors.

The product question that kept it alive is already answered: a per-instance
`rate_limit_per_minute` scalar belongs on a tier, and runtime configuration already has a home
in `app_settings` and `web/config.yaml`.

**The only correction is to urgency.** The research pass wanted a standalone drop now. The
migration that revoked its grants deliberately described itself as the reversible half of an
open decision. Now that the decision is made, the drop is safe — but a `DROP TABLE` is a
destructive migration, it needs its own file and its own approval moment under rule 2, and
there is no cost to waiting for the next time somebody is in the schema with a reason.

### What to implement

One migration, when convenient: `..._drop_chatbot_settings.sql`, recording the row count, the
absent foreign keys in both directions, the absent triggers, and the grep that proves nothing
reads it — as rule 7 requires. Then delete its row from the standing-findings register in
`supabase/README.md` and close the `TODO.md` entry.

---

## 4. `profiles.last_seen_at`

**STATUS for this section: IMPLEMENTED 2026-08-28**, unlike questions 1-3 above. Written
2026-08-28, revised the same day after an adversarial review (`opencode`,
`openai/gpt-5.6-terra`, `xhigh`) and a DRY/reuse audit (Antigravity, `gemini-3.7-flash-high`),
both read-only, then implemented and its migrations applied and verified against the live
database the same day, then reviewed a fourth time against the landed diff itself
(`opencode`, `openai/gpt-5.6-sol`, read-only, harsh) — see "What a harsh review found, and
fixed" below — which caught two real gaps in the shipped implementation and both were
fixed the same day. Not yet committed to git — pending review of the diff and the
project gates.

> **Correction, recorded rather than edited away — 2026-08-28.** The recommendation below
> was the right call against the design it reasoned about, and the reasoning that follows
> is left intact because it is what makes the correction legible. **It no longer applies.**
> The operator has since decided to write the field — the admin console showing "Never"
> next to a working "Last Signed In" was the wrong outcome to leave standing. **What was
> actually built avoids the exact hazard this section warns about**: it keeps
> `last_seen_at` off `profiles` entirely, in a new `profile_last_seen` table, so the
> `updated_at`/optimistic-concurrency collision described below never occurs — not because
> the collision was mitigated, but because nothing in the shipped design ever writes to
> `profiles` at all. "What was built instead," below, is the complete, implemented design;
> §4's original "What to implement" steps (a column drop, a `ui.js` edit, an
> `admin_store.py` payload change) were never performed and do not apply.

This closes the `TODO.md` entry that originally read "`profiles.last_seen_at` is written
by nothing" — retitled to track the column's disposal instead, and itself closed
2026-08-28 when the column was dropped; both entries are now in
[`docs/archive/TODO-resolved.md`](archive/TODO-resolved.md) — and finding 13 in
[`docs/database-improvement-plan.md`](database-improvement-plan.md), by writing the field
rather than dropping it: the operator's call, made after seeing the admin console still
show "Never" next to a working "Last Signed In" (2026-08-28 screenshot).

### The recommendation (superseded — see correction above)

**Stop displaying it. Do not drop it. Do not write it.**

This is the one where the obvious answer is the expensive one, and the opposition pass is
decisively right.

### Why not drop it

The research pass framed the drop as small: remove the column, a trigger clause, a read, and a
UI placeholder. The actual footprint, which I verified:

- `last_seen_at` is in the **`RETURNS TABLE` signature of four `admin_get_user` migrations** —
  `20260814175551`, `20260816215103`, `20260822225623`, `20260823014310`.
- It is guarded in the body of **two trigger functions**, `profiles_guard_privilege_columns`
  and the marketing-consent revision of it.

Under this repository's own rule, changing a function's return signature is a **drop plus a
create**, never a `create or replace`. So "drop the column" means dropping and recreating a
`security definer` RPC that the admin console depends on, editing two trigger functions whose
firing order is load-bearing, and updating the privilege test — to remove a column holding four
NULLs.

### Why not write it either

Both passes agree, and the reasoning is already in `TODO.md`. Writing it per request turns the
one table every request already reads into a continuous write target — the same write
amplification that `20260828001636` just removed from `user_notification_reads`. And because a
trigger sets `updated_at` on every `profiles` update while `admin_update_profile` uses that
same column for optimistic concurrency, a background last-seen write would make an
administrator's in-flight edit fail with a spurious conflict.

### What to do instead

Remove the empty row from the account detail view. The console **already renders
`last_sign_in_at`** from GoTrue immediately above it, which answers the only question an
operator actually has — is this account still in use. Two file edits, no migration, fully
reversible.

Leave the column, its trigger guard and the RPC signature exactly as they are. If `profiles` is
ever being migrated for another reason — the account-deletion work is the likely occasion — the
column can ride along in that migration at near-zero marginal cost.

**One caveat worth recording:** `last_sign_in_at` moves when a session is established, not when
a reader asks a question. For "active or dormant?" that is sufficient. If somebody later wants
genuine activity recency, it belongs in its own throttled table, never on `profiles`.

### What was built instead

Three new pieces and one small existing-function change, replacing the recommendation
above rather than extending it.

#### What the review changed

The first draft of this design wrote `last_seen_at` onto `public.profiles` directly,
throttled, and decoupled `updated_at` from it by editing `handle_profile_update()` — the
trigger function that stamps `profiles.updated_at`. Terra's review named the real problem
with that: **`handle_profile_update()` predates this repo's migration discipline and its
live body is not in this checkout.** The draft's own "verify before writing" step was
already an admission that the design depended on an object nobody could currently read.
`docs/database-improvement-plan.md`'s own finding 13 had already pointed at the fix: _"the
cleaner design ... is to keep last-seen off `profiles` entirely rather than add a
per-request write to the one table every request already reads"_ (line 1247-1249) — the
first draft read past that sentence and did the opposite anyway.

**The shipped design keeps `last_seen_at` off `profiles` entirely.** A small dedicated
table holds it; `admin_get_user` — whose _current_ body was fully visible in
`supabase/migrations/20260823014310_admin_get_user_exposes_consent_record.sql`, no live
pull required — was changed to read from it. `handle_profile_update()` was never touched.
Every downstream consequence of the original design — the `updated_at`-decoupling
migration, the "verify the live trigger before writing" step, the no-op-save
behavior-change test, the `AD005`-collision regression test — is gone, not mitigated,
because the thing that caused them no longer exists in the design.

Two smaller corrections carried over from both reviews, independently flagged by each:

- **`/api/identity` needs two separate `try`/`except` blocks, not one.** The first draft
  said to add the new call "in the same block, wrapped the same way" as the existing
  `get_standing_line_facts` call. Both reviewers caught the same failure-domain bug: a
  throttled-write failure would blank out `created_at`/`conversation_count` on `/account`,
  which have nothing to do with it.
- **"Once per page load" overstated the guarantee.** `identityInFlight`
  (`static/js/modules/services.js:585-600`) only coalesces _concurrent_ calls in one browser
  module lifetime — it does not span reloads, tabs, devices, or `fetchIdentityWithRetry`'s
  sequential retry (`static/js/app.js:77-85`). This does not change the design: the SQL
  throttle bounds writes regardless of call frequency. It changes what the design is allowed
  to claim about it.

A third correction, made after the reviews and not itself reviewed: the naming across UI,
code and database did not agree, in two separate ways — see design piece 5 below.

#### What was verified true before building

- `profiles.last_seen_at` was read into the admin payload at
  `web/services/admin_store.py:769` (`InMemoryAdminBackend`) and, on the real backend, came
  back as one column of `admin_get_user`'s output (`SupabaseAdminBackend.get_user`,
  `web/services/admin_store.py:433-442`, calling the RPC and returning its row verbatim).
  Nothing wrote the column.
- It was **already guarded as server-owned**. `profiles_guard_privilege_columns`
  (`supabase/migrations/20260822224942_profile_privilege_guard_covers_insert.sql:34-64`)
  raises `42501` if `authenticated`/`anon` touch it. The shipped design does not need that
  guard — nothing in it ever writes to `profiles.last_seen_at` — but leaves it in place; see
  "What happens to the old column" below.
- `admin_get_user(uuid)` (`supabase/migrations/20260823014310_admin_get_user_exposes_consent_
record.sql`) was a single `language sql` function, one `select` with a `left join
public.profiles`, `security definer`, `set search_path = ''`. Its complete body was in
  that file — no live-database pull needed to change it safely.
- `admin_update_profile` (`20260814200342_admin_update_profile.sql:71-72`,
  `20260822225415_profile_identity_atomic_cutover.sql:203-231`) uses `profiles.updated_at`
  for optimistic concurrency (`AD005` on mismatch). This design never writes to `profiles`,
  so this mechanism is entirely unaffected — not "avoided by careful design," just not in
  the blast radius.
- `/api/identity` (`web/api/app.py:2337-2384`) already loads one privileged fact through
  `get_admin_backend()` (`get_standing_line_facts`), in a `try/except Exception` that logs
  and degrades to `null` on failure, never surfacing to the caller.
- `get_admin_backend()` (`web/services/admin_store.py:868-877`) returns `None` in `TESTING`
  or with no service-role key, and otherwise a `SupabaseAdminBackend` on the **service-role**
  client. A write issued from it is never browser-authenticated, so `touch_last_seen` needs
  no exemption from `supabase/README.md`'s five-point RPC contract — the same reasoning
  `get_identity_flags(p_user_id uuid)` already relies on (it also trusts its caller purely by
  virtue of being `service_role`-only, with no in-function check that the caller "owns"
  `p_user_id`). `supabase/README.md`'s contract text names the first argument `p_owner_id`;
  this function follows `get_identity_flags`'s own established variance (`p_user_id`) rather
  than the literal name, because it is that function's direct sibling.
- Migration `20260828001636_served_at_is_written_once_not_on_every_poll.sql:91-93` already
  established the exact write-suppression idiom this design reuses: an `on conflict ... do
update ... where <condition>` clause that makes a stale-write attempt affect zero rows.
- The naming already disagreed with itself in two independent ways, unrelated to anything
  this design adds. `web/i18n/en.yaml:540` — `columnLastSeen: "Last signed in"`, rendered in
  the people table (`static/js/admin/ui.js:736`, `798-799`) — was bound to `last_sign_in_at`,
  not to anything "seen"; the key name simply lied about what it held. Separately,
  `web/i18n/en.yaml:450` — `lastSeen: "Last active"`, rendered in the account-detail panel
  (`static/js/admin/ui.js:1384-1385`) — had a key that already matched the DB column
  (`last_seen_at`) and this design's new table/RPC (`profile_last_seen`, `touch_last_seen`),
  but a label that said "Active" while everything underneath said "Seen". Neither string
  carried a `# frozen` marker (checked against every `# frozen` line in `web/i18n/en.yaml`),
  so both were plain copy/key changes, not the frozen-string test change `docs/PRODUCT.md`
  warns about.

#### Design

Three new pieces and one small existing-function change.

##### 1. A dedicated table, not a column on `profiles`

```sql
create table public.profile_last_seen (
  user_id      uuid primary key references public.profiles(id) on delete cascade,
  last_seen_at timestamptz not null
);

revoke all on table public.profile_last_seen from anon, authenticated, public, service_role;
```

`on delete cascade`, deliberately — matching how `20260828001910_notification_child_rows_
cascade_on_delete.sql` (finding 9) already treats a table that exists only to describe another
row: this one should not survive the account it describes. No role gets any grant at all,
service_role included: every reader and writer of this table is a `security definer`
function running as its owner, so a grant would only be a capability nobody needs, the same
reasoning `admin_actor_email` uses for granting execute to no role
(`supabase/README.md:120-129`).

One row per account that has ever been touched — bounded by account count, not by request
volume, and this product currently has four accounts.

##### 2. A throttled write RPC, the standard contract, no exemption

```sql
create or replace function public.touch_last_seen(p_user_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profile_last_seen (user_id, last_seen_at)
  values (p_user_id, now())
  on conflict (user_id) do update
     set last_seen_at = excluded.last_seen_at
   where public.profile_last_seen.last_seen_at < now() - interval '1 hour';
end;
$$;

revoke execute on function public.touch_last_seen(uuid) from anon, authenticated, public;
grant execute on function public.touch_last_seen(uuid) to service_role;
```

The `on conflict ... where` clause is the entire throttle, reusing
`20260828001636`'s idiom rather than a second way of expressing "skip this write." First
touch for an account always writes (the row does not exist yet, so `on conflict` does not
apply and the `insert` proceeds). A touch inside the same hour is zero rows affected. No
in-process debounce, no new cache: `identity_cache.py`'s TTL+LRU cache exists to save a
network round trip on the hot chat-request path, which this call is not on (see point 4);
adding a second cache here would be state without a job to do.

##### 3. `admin_get_user` reads from the new table

`create or replace function` — the return row _type_ is unchanged (still a `last_seen_at
timestamptz` column, same name, same position), only the source expression for one column
changes, so this is not the drop-plus-create the file's own header comment warns about for a
genuine signature change. **Correction — position is not optional, as an earlier draft of
this section implied:** `create or replace function` on a `returns table (...)` requires the
output columns to match in name, type _and order_; reordering them is itself a signature
change and hits `42P13` exactly like adding, removing or retyping one would. This migration
kept every column in its original position and changed only the `from`/`select` expression
feeding one of them — that is what makes it safe, not any tolerance Postgres has for
reordering:

```sql
create or replace function public.admin_get_user(p_user_id uuid)
returns table (
  -- ... unchanged ...
)
language sql
security definer
set search_path = ''
as $$
  select
    -- ... unchanged columns ...
    pls.last_seen_at,
    -- ... unchanged columns ...
  from auth.users u
  left join public.profiles p on p.id = u.id
  left join public.profile_last_seen pls on pls.user_id = u.id
  where u.id = p_user_id
$$;
```

Copy the full current body from `20260823014310_admin_get_user_exposes_consent_record.sql`
verbatim and change exactly the one line plus the added `left join` — that file is the
verification, nothing needed to be pulled live for this one.

##### 4. Call `touch_last_seen` from `/api/identity`, in its own `try`/`except`

Not `/api/chat/stream`, not `_authenticate_request`. **Correction — "every route funnels
through" overstated it, as a harsh review caught:** `/api/identity` is a specific endpoint
the _frontend_ calls once per browser session (`identityInFlight`,
`static/js/modules/services.js`), not a server-side funnel every request passes through —
ordinary chat/API requests never touch it, and `web/api/admin.py`'s console has its own,
separate `/admin/api/identity` (see "What a harsh review found, and fixed" below).
`/api/identity` is where `get_standing_line_facts` already lives, for the same reason: an
extra privileged, best-effort fact, loaded once the caller is known to be authenticated,
that must never break the response it rides along with.

```python
if backend is not None:
    try:
        backend.touch_last_seen(flags.user_id)
    except Exception:
        logger.exception("Could not touch last_seen for %s", flags.user_id)

    try:
        facts = backend.get_standing_line_facts(flags.user_id)
    except Exception:
        logger.exception("Could not load standing-line facts for %s", flags.user_id)
        facts = None
    if facts is not None:
        created_at = facts.get("created_at")
        conversation_count = facts.get("conversation_count")
```

Two `try` blocks, not one — a failing touch must never blank out facts that loaded fine, and
a facts failure must not skip the touch. `/api/identity` is called at least once per browser
session (`identityInFlight` coalesces concurrent callers within it) but not provably exactly
once — reloads, retries and multiple tabs can all call it again. That is fine: the throttle
in point 2 is what bounds the actual writes, not the call site.

##### 5. Unify the naming: fix the wrong key, align the mislabeled one

Two independent renames, not a redesign of either side — the DB/RPC vocabulary chosen in
pieces 1–3 (`profile_last_seen`, `touch_last_seen`, `last_seen_at`) did not change; the i18n
layer moved to agree with it, and one unrelated wrong key was corrected on the way past.

- **Fix the wrong key.** `columnLastSeen` (`web/i18n/en.yaml:540`, `web/i18n/ar.yaml:413`) was
  bound to `last_sign_in_at`, not to anything "seen" — renamed to `columnLastSignIn` in both
  files and at its one reference (`static/js/admin/ui.js:736`). No visible text changed; this
  only fixed a key name that already lied about what it held.
- **Align the label with the key and the schema.** Changed the visible string bound to
  `lastSeen` (`web/i18n/en.yaml:450`) from `"Last active"` to `"Last seen"`. This was the
  cheaper direction — the table, RPC and column names already said "seen"; changing three
  database identifiers to match a UI word would have been the wrong side to move — and it is
  also the more honest label: `touch_last_seen` records a successful `/api/identity` call,
  i.e. presence, not genuine in-app activity (a tab can sit open, chatting, for hours between
  touches). "Last active" claimed more than the signal supports; "last seen" does not.
  `web/i18n/ar.yaml:342` read `"آخر نشاط"` ("last activity") for the same key — re-translated
  to `"آخر ظهور"` ("last seen", the term Arabic messaging UIs use for presence), not a literal
  swap, to carry the same honesty shift into Arabic.
- **`columnLastSeen`'s Arabic counterpart** (`web/i18n/ar.yaml:413`, `"آخر دخول"` — "last
  login") kept its existing Arabic text; only its key renamed, matching the English side.
- The `runtime.*`/`page.*` parity test (`CLAUDE.md` rule 2) already fails on an English/Arabic
  key mismatch, so a renamed key left stale in one file is caught mechanically, not just by
  review.

#### What happened to the old column

**Update 2026-08-28 — dropped.** `profiles.last_seen_at` no longer exists.
`20260828222859_profiles_guard_stops_checking_last_seen_at.sql` first removed the column
from `profiles_guard_privilege_columns`'s INSERT/UPDATE checks (the last thing in the
schema still referencing it), then `20260828222917_drop_profiles_last_seen_at.sql`
dropped the column itself — its own migration, per `supabase/README.md` rule 2. This
closed the `TODO.md` entry this section originally deferred to. The paragraph below is
kept for the record of what was decided at the time; it no longer describes the live
schema.

Originally, after this design shipped, `profiles.last_seen_at` still existed, was still
guarded by `profiles_guard_privilege_columns`, and was still never written by anything —
the write had moved to a different table entirely. Two things distinguished this from the
original problem rather than just relocating it:

- **Nothing that reaches a human reads it anymore.** `admin_get_user` stopped selecting it;
  the only remaining reader of `profiles.last_seen_at` the column (as opposed to the output
  field of the same name) would be someone running a raw query against `profiles` directly.
  The "contract lie" `TODO.md`'s note on this entry warned about was specifically that the
  admin console shows it as real data — that stopped being true.
- **It was not free to leave, and that was not pretended.** It was the same category of
  object as `chatbot_settings` (§3 above): a dead artifact, safe to leave, not urgent to
  remove — tracked as a follow-up in `TODO.md`, deferred to the next migration that touched
  `profiles` for another reason, exactly the sequencing recommended for `chatbot_settings`
  in §3. Not done as part of this change originally; it was unrelated
  to making "last active" work and would just be a second destructive migration riding on
  the same release.

#### What a harsh review found, and fixed

A fourth pass — `opencode`, `openai/gpt-5.6-sol`, dispatched adversarially against the
_landed_ diff rather than the plan, after the three pieces above already shipped — found
two real gaps neither earlier review had reason to look for, because both are properties
of the actual call graph, not of the design on paper:

- **An orphaned account (an `auth.users` row with no matching `profiles` row — the state
  the `test-orphan-id` fixture already models) made `touch_last_seen` raise a foreign-key
  violation on every call it was reached from**, forever, silently swallowed by
  `/api/identity`'s `try`/`except` — no crash reached a reader, but every `/api/identity`
  request from such an account logged an exception and attempted a doomed insert (not
  every request the account made generally — only the ones reaching that specific route).
  `InMemoryAdminBackend.touch_last_seen`
  already promised silent no-op for this case; the real RPC did not match it, and no test
  could see the divergence because the fake and the real function disagreed. Fixed in
  `20260828143044_touch_last_seen_tolerates_a_profileless_account.sql`: `insert ... select
... from public.profiles where id = p_user_id` inserts zero rows instead of one that
  violates the FK, rather than an unconditional `insert ... values (...)`.
- **An administrator who only ever uses the console never touched `last_seen_at` at all.**
  `web/api/admin.py`'s `/admin/api/identity` is a _separate_ route from
  `web/api/app.py`'s `/api/identity` — the one `touch_last_seen` piece 4 above actually
  calls — and the console deliberately never imports `static/js/modules/services.js`
  (`test_the_console_does_not_import_the_chat_shell` pins that boundary as a security
  property, not an oversight). So the one account type an operator most wants fresh
  presence data for, from the one surface most likely to be console-only, was exactly the
  case this feature could never observe. Fixed by adding the same best-effort,
  independently-`try`'d `touch_last_seen` call to `admin.py`'s `identity()` route,
  resolved through `current_app.config["admin_backend"]()` — the pattern that route
  already uses elsewhere — rather than the module-level `get_admin_backend()` import
  `app.py`'s route uses.

A third point the review raised is real but **not fixed, because it is not new**: both
`touch_last_seen` and `get_standing_line_facts` are synchronous, sequential round trips on
the service-role client with no explicit short timeout, so a stalled RPC delays the whole
response by that much. This is not a property this feature introduced — `get_standing_line
_facts` already had exactly this characteristic before this feature existed — the two-`try`
design only adds a second call with the same trait, roughly doubling the worst-case
exposure at this one path rather than creating a new category of risk. Worth a timeout
policy for the service-role client at some point; not something this feature's own review
should quietly decide on its own, since it is a client-wide concern, not a
`touch_last_seen`-specific one.

#### Migration files

Four files. The first three were applied together and `list_migrations` renamed all three
after apply per this repo's rule 6; the fourth was applied separately, afterward, once the
harsh review below caught the gap it fixes — not part of the original batch, despite fixing
a defect in one of that batch's own migrations:

1. `20260828135721_profile_last_seen_table.sql` — creates `public.profile_last_seen`, fully
   locked down.
2. `20260828135732_touch_last_seen_rpc.sql` — creates `touch_last_seen(uuid)`,
   contract-compliant, no exemption.
3. `20260828135749_admin_get_user_reads_profile_last_seen.sql` — `create or replace`, sourced
   from the previously checked-in body.
4. `20260828143044_touch_last_seen_tolerates_a_profileless_account.sql` — `create or
replace`, fixing the orphan-account foreign-key violation the harsh review caught.

Schema before code, per this repo's rule. No live-database read was required before writing
any of the four — a change from the first draft, which needed one for the object this
revision no longer touches.

#### Code changes

**`web/services/admin_store.py`** — one method added to the `AdminBackend` `Protocol`
(`web/services/admin_store.py:114`), next to `get_standing_line_facts`:

```python
def touch_last_seen(self, user_id: str) -> None:
    """Best-effort. Throttled in the database; callers do not need to."""
    ...
```

`SupabaseAdminBackend` implements it as one `rpc("touch_last_seen", {"p_user_id":
user_id}).execute()` call, the same shape as `get_standing_line_facts`
(`web/services/admin_store.py:267-274`). `InMemoryAdminBackend` sets
`row["last_seen_at"]` on the matching seeded user and **returns silently, doing nothing, when
`user_id` matches no seeded row or matches one with `has_profile is False`** — the same
"must not raise for not found" contract every other method on this `Protocol` already
follows (`web/services/admin_store.py:114-115`), made explicit here because it is the one
method on this interface with no natural "not found" return value to fall back on.

**`web/api/app.py`**, inside `identity()` (`web/api/app.py:2337`) — the two-`try` shape from
design piece 4 above.

`static/js/admin/ui.js:1385` already rendered `account.last_seen_at` when present; it simply
stopped being `null` — no change needed there. **`static/js/admin/ui.js:736`** did change:
its `columnLastSeen` reference became `columnLastSignIn` (design piece 5). **`ASSET_VERSION`
was bumped** in `web/api/app.py` in the same commit — this design does touch JS, via that one
key reference, even though nothing else in `ui.js` changes.

**`web/api/admin.py`**'s `identity()` route (the harsh-review fix above) — the same
best-effort `try`/`except` shape as `web/api/app.py`'s `identity()`, resolving the backend
via `current_app.config["admin_backend"]()` rather than importing `get_admin_backend`
directly, matching this file's own existing pattern (`user_detail`, elsewhere in the file).

**`web/i18n/en.yaml` and `web/i18n/ar.yaml`** — the two renames from design piece 5:
`columnLastSeen` → `columnLastSignIn` (both files, key only, no text change) and the `lastSeen`
value in `en.yaml` from `"Last active"` to `"Last seen"`, with `ar.yaml`'s `lastSeen` value
re-translated from `"آخر نشاط"` to `"آخر ظهور"`.

#### Tests

- **SQL** (`supabase/tests/rpc_behaviour.test.sql`): inside the file's one rolled-back `DO`
  block. **Correction — against a live account, not a seeded/fixture one**, as an earlier
  draft of this section claimed: `reader` is the same live, currently-enabled non-admin
  profile every other assertion in this file already uses (`admin_a`/`admin_b`/`reader`,
  selected at the top), not a fixture unique to this feature. What makes it deterministic
  is clearing any existing `profile_last_seen` row first and relying on the whole block's
  rollback, not the identity of the account:
  - `touch_last_seen` on a user with no `profile_last_seen` row: asserts `last_seen_at` is
    written as _exactly_ the transaction's own `now()` — not merely non-null, since a
    weaker check cannot tell "wrote the right value" from "wrote something".
  - `touch_last_seen` again immediately: asserts **zero rows were updated**
    (`pg_stat_xact_user_tables.n_tup_upd`, the identical idiom `20260828001636`'s own
    throttle test already uses), not that the read-back timestamp "looks unchanged" — a
    harsh review caught that `now()` is transaction-stable, so an unthrottled RPC would
    also leave the read-back value looking unchanged inside one transaction, making a
    timestamp-comparison assertion pass against a completely missing throttle predicate.
  - Set `last_seen_at` to two hours in the past, then `touch_last_seen`: asserts it advances
    to _exactly_ `now()`, not merely "later than it was" — a harsh review caught that a
    predicate advancing a stale row by one second, or to 90 minutes ago rather than to now,
    would pass a weaker "did it move" check while leaving the row still effectively stale.
  - A random id with no matching `profiles` row does not raise (the orphan-tolerance
    regression test for `20260828143044`, added by the harsh-review pass below).
  - No named privilege round-trip: `function_acls.test.sql`'s existing sweep over every
    function in `public` already covers `touch_last_seen`'s grants; a named re-check here
    would be a second, weaker copy of the same fact.
- **SQL**: `admin_get_user` on a user with a `profile_last_seen` row returns it in
  `last_seen_at`. On a user with none, the row must still come back with `last_seen_at`
  null — asserted as two separate checks, not one: `exists(select 1 from admin_get_user(...))`
  proves the row itself is present (a harsh review caught that a regression from `left join`
  to `inner join` would make the whole row vanish rather than merely null the column, and a
  bare `(select last_seen_at from admin_get_user(...)) is not null` scalar-subquery check
  cannot tell a present-row-with-null-column apart from a vanished-row-so-the-subquery-reads-
  null — Postgres evaluates a scalar subquery over zero rows as `NULL`, the same value it
  would evaluate a genuinely null column to), then the null-column check itself.
- **Python** (`web/tests/test_identity_roles.py`): `identity()` calls `touch_last_seen` when
  a backend is present and a failing `touch_last_seen` does not prevent
  `get_standing_line_facts`'s result from reaching the response (the regression the two-`try`
  fix exists for — asserted directly, not just implied by the code's structure).
- **i18n parity**, design piece 5: the existing `runtime.*`/`page.*` parity assertion
  (`test_arabic_catalogue_covers_every_runtime_key`, `web/tests/test_frontend_architecture.py`)
  already fails if `columnLastSignIn` lands in `en.yaml` without a matching `ar.yaml` key —
  confirmed by reading that test, not assumed. **It does not, however, catch a stale
  `columnLastSeen` string left behind in `ui.js`.** Confirmed by reading both the test (it
  only diffs the two YAML files against each other, never touches `ui.js`) and
  `static/js/modules/i18n.js:31-33` (`I18n.t()` on a missing key logs `console.warn` and
  returns the raw key string — it does not throw). A missed rename at `ui.js:736` would ship
  silently: the column header would render the literal string `"admin.people.
columnLastSignIn"` instead of failing anything. A small guard test,
  `test_no_stale_reference_to_the_renamed_last_seen_column_key`
  (`web/tests/test_frontend_architecture.py`), asserts the string `columnLastSeen` no longer
  appears anywhere under `static/js/`, so a missed rename fails CI instead of shipping.
- **SQL** (harsh-review fix, `supabase/tests/privileges.test.sql`): `profile_last_seen`'s
  denied-privileges list covers all seven table privileges per role
  (`SELECT`/`INSERT`/`UPDATE`/`DELETE`/`TRUNCATE`/`REFERENCES`/`TRIGGER`), not the four-verb
  subset an earlier draft of this test used — a harsh review caught that the migration's
  `revoke all` was correct while the subset test could not have caught an accidental
  `grant truncate`/`grant references` regression.
- **Python** (harsh-review fix, `web/services/admin_store.py`):
  `InMemoryAdminBackend.touch_last_seen`'s docstring now says plainly that it does not
  model the real RPC's one-hour throttle — it always writes. A harsh review caught that
  nothing said this, so a future test touching twice through the fake and expecting the
  second timestamp to move would pass here and fail against the real RPC.
- **Python** (harsh-review fix, `web/tests/test_admin_page.py`):
  `test_console_only_activity_still_touches_last_seen` proves the gap is closed (a request
  through `/admin/api/identity` alone moves the seeded admin's `last_seen_at` from `None`);
  `test_a_failing_touch_does_not_break_the_console_identity_check` proves the same
  failure-isolation guarantee as the reader-facing route holds here too.

Dropped from the first draft, because the thing they were protecting against no longer
exists in the design: a test proving an ordinary profile edit still bumps `updated_at`, and a
before/after capture of `handle_profile_update()`'s owner/ACL/trigger definition.

#### Docs

- `TODO.md`'s entry on this and `docs/database-improvement-plan.md`'s finding 13 both now
  point at this document — merged here on 2026-08-28 rather than left as two documents where
  one could disagree with the other about whether this is decided. That merge, and the
  correction callout at the top of this section, are the "record this as a correction, not a
  silent edit" step called for while this was still a separate implementation plan — done,
  not deferred.
- No new row in `supabase/README.md`'s RPC-contract exemption list — `touch_last_seen` needs
  none. **Still open:** a one-line note next to `get_identity_flags` in that file's function
  inventory recording that both functions share the `p_user_id`-not-`p_owner_id` naming for
  the same reason, so the next reader does not flag it as a contract violation on sight.

#### Sequencing

1. All four migrations, applied together, then `list_migrations` rename. **Done** — the
   fourth (`20260828143044`) landed after a harsh review of the first three caught the
   orphan-account gap; see "What a harsh review found, and fixed" above.
2. `admin_store.py` (Protocol + both backends), `app.py` (`identity()`), `admin.py`
   (`identity()`, the harsh-review fix). **Done.**
3. `en.yaml`/`ar.yaml` renames and the one `ui.js` reference (design piece 5), `ASSET_VERSION`
   bump. **Done.**
4. Tests, above. **Done.**
5. `TODO.md` and `docs/database-improvement-plan.md` pointers to this document. **Done** —
   this merge is that step; see "Docs" above.
6. Separately, later, not part of this change: drop `profiles.last_seen_at` and its guard
   -trigger reference, alongside `chatbot_settings`, next time `profiles` is migrated for
   another reason. **Still open** — tracked in `TODO.md`.

---

## Sequencing

Nothing here is urgent and nothing here blocks anything else. In order of value:

**First — cost nothing, close one entry.** Writing the retention policy into
`docs/OPERATIONS.md`. No migrations, no risk. (§4 does not belong in this sequencing — it
is already implemented; see §4's own "Sequencing" instead.)

**Second — the consent carve-out**, because it is the only item with a live gap behind it. The
RPC, then the policy, then the frontend, then the test. Ships as one release.

**Third — drop `chatbot_settings`**, next time somebody is in the schema.

**Not scheduled:** the audit-log purge function, any transcript TTL, and anything touching
`chat_archive`. These wait for a row count or a lawyer, and building them early would be
building a deletion mechanism before anyone has decided what should be deleted.

## What still needs a human

- **A lawyer or DPO on question 1**, before any of it reaches the privacy policy. The
  principles in this document are sound; the article numbers that were offered alongside them
  are not verified and have been deliberately stripped.
- **The operator on question 2** — "disabled means frozen" is a product decision, and the
  consent carve-out follows from law rather than preference, but the freeze itself is a choice.
- Question 3 is engineering taste and needs no sign-off beyond a review of the diff.
- Question 4 needed a decision, not sign-off — the operator already made it, and §4 records
  the built result. What is left is landing the diff (§4's own "Sequencing" marks every step
  but the drop of the now-dead column, and this document's own STATUS line, as done).
