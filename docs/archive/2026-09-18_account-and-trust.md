---
authority: historical
status: superseded
do_not_implement: true
archived: 2026-09-18
supersedes_note: >
  A finished plan. Its section 1 decisions were closed by the product owner on
  2026-09-18 and SEVERAL OF ITS OWN RECOMMENDATIONS WERE REVERSED before the work
  was built. Read the reversal list below before trusting any recommendation here.
live_authority:
  - supabase/README.md
  - TODO.md
  - docs/ARCHITECTURE.md
  - supabase/README.md
---

> [!CAUTION]
> **You are reading history, not a specification.** Do not implement anything found
> in this file without first confirming it against `docs/ARCHITECTURE.md` or the code.
> Every heading below is prefixed `[HISTORICAL]` so a search result cannot be mistaken
> for current design.

## [HISTORICAL] What this plan got wrong, and what was built instead

This plan was executed on 2026-09-18. It is preserved because its verification work — the
live FK catalogue in §0, the four re-verified security findings in §0b — was correct and
expensive. **Its recommendations were not all correct.** The final position, which overrides
every conflicting sentence below:

| The plan said                                                              | What shipped, and why                                                                                                                                                                                      |
| -------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D2: 30 days, conditional on a redesign                                     | **30 days, unconditional** — the product owner's decision, matching `docs/data-policy-decisions.md` §1                                                                                                     |
| §4: revoke sessions with a **GoTrue ban**, lifted on cancel                | **Reversed.** A ban kills token refresh, so the reader could not authenticate to cancel — the same unreachable-cancel flaw §0b.2 had just diagnosed. Ships as `auth.admin.sign_out(jwt, scope="global")`.  |
| §4: admit pending to `_gate` via an exemption                              | **Not needed and not done.** Pending is never `is_disabled`, so `_authenticate_request` admits it already. The exemption was an artefact of the abandoned design and would have weakened the gate.         |
| D4: guard the archive "in the same shape as the `archive_disclosed` check" | **Reversed.** That check's own docstring says it "does not stop the process". Copying its shape would have shipped theatre. The new guard is a hard startup raise.                                         |
| D6b: the trigger's re-affirm branch is in scope                            | **Deferred** — a re-affirm branch with no caller is surface for a feature that does not exist. Lifted to `TODO.md`.                                                                                        |
| M1 revokes the consent column grants                                       | **Incomplete as written.** Granting was the same direct PATCH, so the revoke would have left nobody able to opt in. A server-side grant route was added. `authenticated` also held **INSERT**, closed too. |
| "a **fourth** browser-callable function"                                   | The consent RPC is the **third**; `account_deletion_is_pending()` is the fourth.                                                                                                                           |
| §5: an HTTP reconcile timer on a stored admin credential                   | Already rejected in this document, and correctly: it ships as a systemd one-shot on the service key already in `.env`.                                                                                     |

Two adversarial debates were then run against the built code, and both found real defects. The
further reversals they forced, recorded here because the reasoning is the valuable part:

| What was built                                                      | What it became, and why                                                                                                                                                                                                                                    |
| ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A pending account was frozen out of chat and profile writes         | **Reversed. Grace is fully usable.** The freeze fired at persist time, _after_ the LLM had generated — so a pending reader burned quota and spend on answers that were then discarded, and the copy's "you cannot start new conversations" was false.      |
| One predicate, `account_deletion_is_live`, gated everything         | **Split in two.** `account_deletion_freezes_writes` (purging/auth_delete_begun/failed/**completed**) gates the reader; `account_deletion_is_live` (every non-terminal state) keeps the operator and consent boundaries.                                    |
| The freeze set stopped at `failed`                                  | **`completed` added.** `chat_append_turn` takes an owner id as an argument and lazily creates, reading no profile and bound by no FK — so a 300s stream admitted in grace could file a turn _after_ the purge, under a deleted owner, unreachable forever. |
| The archive guard refused to boot                                   | **Refuse to collect instead.** Same guarantee at the actual enforcement point, without taking production down over an env typo nobody may see the traceback for.                                                                                           |
| `admin_set_user_flags` refused every flag change on a live saga     | **A pure Disable is permitted.** Otherwise any reader who knows their password could request deletion, cancel, re-request, and stay permanently un-disableable while grace remained fully usable.                                                          |
| The deletion UI and privacy promise shipped with the consent deploy | **Behind a switch, default off.** The consent code must deploy between `02` and `03`, long before the saga exists — so without the switch `/privacy` would promise self-serve deletion while both routes answered 503.                                     |

**Where the live authority now lives:** the apply runbook is `supabase/pending/README.md`;
the open work is in `TODO.md`; the conventions are in `supabase/README.md`.

# [HISTORICAL] Account & Trust — one meeting, one migration batch

Five `TODO.md` entries share one decision-maker and one blast radius (`profiles`, `auth`,
deletion, transactional email). This plan turns them into a decision sheet, a dependency
order, and one ordered migration batch.

**The five:** account deletion (Spec 4) · what `disabled` means · `/privacy` is a draft ·
security email is English-only · profile leftovers (account-menu, monogram).

## [HISTORICAL] How this was produced

Independent passes plus direct verification, adjudicated here.

1. **Community/industry research** — Antigravity (`gemini-3.8-flash-high`).
2. **Repository-grounded plan** — OpenCode (`muse-spark-1.3`, max, read-only).
3. **Adversarial security review of the first draft** — Claude (`fable-5-1`, high, read-only).
   Its four load-bearing findings were re-verified against the code before adoption.
4. **Three code-map passes** over the enforcement surface, the deletion blast radius, and the
   profile/consent machinery.
5. **Live-database verification** against project `yjjuudnsnjzhyqllsqrd` — FK actions,
   `profiles` policies, and column grants read from the live catalogue, not the migration files.

Two lanes were lost to environment failures rather than to the work: Codex
(`gpt-5.6-terra`) cannot spawn a process on this machine, and a second OpenCode pass
(`gpt-5.6-sol`) hit a provider usage limit. Both refused rather than fabricated. The
gap-closing sweep they would have done was completed directly instead.

Where the passes disagreed, the disagreement is recorded in §1 rather than smoothed over.

---

## [HISTORICAL] 0. What the live database says that the written design does not

Read from the live catalogue on 2026-09-18. These change the batch before it starts.

**Migration A is still correct and still needed.** `profiles.disabled_by` and
`app_settings.updated_by` both still reference `auth.users(id)` with `NO ACTION`. Narrowed
scope: they block a delete only when the departing account ever disabled someone or wrote a
setting — i.e. **they block deleting an administrator**, not an ordinary reader.

**Migration B's purge list is stale.** Per-reader FKs to `auth.users` that landed after Spec 4
was written (quota and notification work, 2026-08-28 → 2026-09-03):

| Table.column                      | On delete                  | Status vs. Spec 4          |
| --------------------------------- | -------------------------- | -------------------------- |
| `profiles.id`                     | `CASCADE`                  | as designed                |
| `profiles.disabled_by`            | `NO ACTION`                | Migration A target         |
| `app_settings.updated_by`         | `NO ACTION`                | Migration A target         |
| `usage_daily.user_id`             | `CASCADE`                  | **new** — purges itself    |
| `user_notification_reads.user_id` | `SET NULL`                 | **new** — anonymises       |
| `notification_recipients.user_id` | `SET NULL`                 | **new** — anonymises       |
| `reader_quota_overrides.set_by`   | `SET NULL`                 | **new** — attribution only |
| `profile_last_seen.user_id`       | `CASCADE` (via `profiles`) | **new** — purges itself    |
| `reader_quota_overrides.user_id`  | `CASCADE` (via `profiles`) | **new** — purges itself    |

**The transcript purge is one statement, not three.** `chat_sessions.owner_id` has no FK at
all; `chat_messages` and `chat_message_sources` cascade off `chat_sessions`.

**`public.account_deletions` does not exist.** Confirmed absent from live schema and from
`supabase/migrations/`.

**The `profiles` policies are not in this repository.** They predate the migrations directory
and survive only as names in `supabase/migrations/0000_baseline.md:13-19`. The live UPDATE
policy is `USING ((select auth.uid()) = id)` with **no `WITH CHECK`**. Any `alter policy` in §3
must be written against that live text, which this plan is the first document to record.

**The saga's own rationale is cited from a line that moved.** §16·4 and `TODO.md:1499` cite
`web/api/admin.py:329-339` for "a database transaction cannot contain an outbound provider
call." Those lines are now the registrations-pause route; the live statement is
`web/api/admin.py:457-459`. An instance of the open _Live code cites plan sections instead of
the live contract_ entry.

## [HISTORICAL] 0b. What the security review changed, and what was verified first

Four findings were re-verified against the code before being adopted. All four held.

1. **`disabled` is not a ban at the provider.** No `ban_duration` is set anywhere in `web/`;
   the sole occurrence is `web/services/admin_store.py:1045` writing `"banned_until": None`
   for display. A disabled account can still sign in to GoTrue, refresh its session, and call
   GoTrue's own user-update endpoint. The first draft's claim that "login cannot resurrect it"
   was true of Flask only, and is withdrawn.
2. **The first draft's grace window was unreachable.** Deletion set `is_disabled`;
   `account_bp._gate` refuses disabled accounts (`web/api/account.py:89-95`), so the cancel and
   status endpoints refused the very reader who needed them. Worse, `revoke_sessions` rotates
   the password to a value nobody knows (`web/services/auth_admin.py:153-156`), so the reader
   could not sign back in either. **The recovery argument that justified 30 days was void.**
   Fixed by giving deletion-pending its own state — see D2 and §3-M4.
3. **The privilege-guard trigger cannot protect an RPC.** It tests
   `current_user in ('authenticated','anon')`
   (`supabase/migrations/20260823014034_marketing_consent_record.sql:222`); inside a
   `security definer` function `current_user` is the owner, so it never fires. **Only the RPC
   body protects server-owned columns.** This constrains how M1 must be written.
4. **"Database truth wins" cannot read `auth.users`.** `supabase/README.md:131-139` records
   that `service_role` reaches `auth.users` nowhere on this database, deliberately.
   Reconciliation must use GoTrue's admin get-by-id instead.

---

## [HISTORICAL] 1. The decision sheet

Six questions plus one addendum. Each is answerable by a non-engineer.

### [HISTORICAL] D1 — May a reader delete their own account at all? (yes / no)

- **Unblocks:** the entire saga, the `chat_sessions` FK, the `/privacy` retention copy.
- **Recommendation: yes.** A product storing named professionals' regulatory questions with no
  self-service erasure is the weakest posture available in front of a regulator.
- **Cost of wrong:** a GoTrue admin delete against real accounts cannot be undone. Do not build
  before the yes.
- **One exception to decide with it:** self-serve deletion is **refused for `role='admin'`**.
  Self-deletion is the first path where actor equals target, which makes the last-admin guard
  reachable for the first time; an administrator leaving should be an operator action.

### [HISTORICAL] D2 — Grace window before the purge? (none / 14 days / 30 days)

**The two research passes disagreed, and the security review then invalidated the argument
that settled it.** Recorded in full because the reversal is the useful part.

- **For no grace (Antigravity):** resurrection by login, zombie marketing email, and
  re-registration deadlock.
- **For 30 days (OpenCode, and `docs/data-policy-decisions.md` §1):** grace makes accidental
  deletion and account-takeover-then-delete recoverable.
- **The first draft chose 30 days on that recoverability argument. That argument was wrong**
  as the mechanism was drafted: the cancel path was unreachable and the password was already
  rotated (§0b.2). A grace window nobody can cancel from is storage, not recovery.
- **The recommendation survives only with the redesign.** 30 days is worth having **if and only
  if** deletion-pending is its own state with a reachable, authenticated cancel path
  (§3-M4). Without that, choose **none** — an honest irreversible delete beats a fake undo.
- **The re-registration deadlock is real and neither pass solved it.** `auth.users` holds the
  email's unique constraint for the whole window. Signup must answer this case without
  confirming it: today signup already discloses `already_registered`
  (`web/api/auth.py:324-325`), and naming pending deletion would newly reveal that a named
  professional recently deleted their account. **Use one generic message covering both.**

### [HISTORICAL] D3 — Do `audit_log` rows naming the account survive? (survive / scrubbed)

- **Recommendation: survive, disclosed accurately.** `audit_log` carries no FK
  (`supabase/migrations/20260814032139_audit_log.sql:24-26`), so the rows simply remain.
- **The first draft's disclosure understated this, and the fix is a design change, not copy.**
  The audit pattern stores `actor_email`, `request_ip` and `user_agent`
  (`…20260814032139_audit_log.sql:27-41`) in an append-only table. A self-deletion recorded
  through that pattern would **keep the deleted person's email and IP address forever**, which
  is not defensible as "audit rows naming the account."
- **Therefore:** the saga's own audit and ledger rows carry **uuid and timestamps only** — no
  email, no IP, no user agent. Any lookup the re-registration message needs uses a keyed hash
  destroyed at grace expiry. Administrative audit rows written _before_ the deletion keep their
  existing shape and are disclosed as such.

### [HISTORICAL] D4 — Does `chat_archive` participate in erasure? (excluded & disclosed / purgeable first)

- **Verified state:** the write path is **live code that runs every turn**, no-oping only
  because the two HMAC salts are unset (`web/services/chat_store.py:192-222`). The table has
  **no delete path at all** — `admin_purge_chat_archive` exists in comments and design docs but
  was never created.
- **Recommendation: ship deletion with the archive excluded and disclosed.**
- **The guard must be code, not a document.** The first draft proposed an
  `docs/OPERATIONS.md` checklist; a checklist is not a control. The archive is **pseudonymous,
  not anonymous** — the HMAC is of the uuid (`chat_store.py:219-222`), the uuid survives in
  `audit_log`, and the salt sits in `.env`. **Refuse at startup** if a salt is set while no
  purge path exists, in the same shape as the existing `archive_disclosed` check.

### [HISTORICAL] D5 — What does `disabled` freeze? (A: everything except consent withdrawal / B: product use only)

- **Recommendation: A, with the consent carve-out delivered as a function, not a policy.**
- **Why the carve-out is not optional, proven rather than argued.** The consent toggle is a
  direct browser→Postgres write (`static/js/account/handlers.js:279-283` says so outright), and
  `authenticated` holds UPDATE grants on all four `marketing_consent*` columns. Freezing the
  policy without a carve-out blocks withdrawal for exactly the people most likely to want it.
- **Do not use a second permissive policy.** `docs/data-policy-decisions.md` §2 disproved it
  live: RLS restricts rows, not columns, so a second policy re-opens all eleven columns.
- **§2's plan is incomplete.** `public.update_own_preferences` is `security definer`, granted to
  `authenticated`, and never calls `is_active_account()`
  (`supabase/migrations/20260822225239_profile_preferences_merge_rpc.sql:32-71`). A
  `security definer` function bypasses RLS, so freezing the policy does not reach it — a
  disabled account could still write `theme`, `language` and `search_scope`. See M2b.
- **Scope the carve-out to withdrawal only.** A disabled account may **withdraw**, never grant.
  Withdrawal when consent is already false is a no-op, so the RPC yields at most one write per
  account and cannot be used as a write-amplification primitive against a table every request
  reads. The age-clearing offer moves to an explicit parameter rather than riding along in the
  same write (`handlers.js:310-313`).

### [HISTORICAL] D6 — Is the reviewed privacy text approved? (approve / approve with edits / not yet)

- **Unblocks:** the `PRIVACY_POLICY_VERSION` bump, the `page.policy.*` rewrite, the email
  templates, every deletion-facing string.
- **Treat as exposure, not cleanup.** `TODO.md:1476` files this as owed work; the research
  position is that consent collected against a document labelled "draft" is not "informed."
  Both readings agree on the action and differ on urgency.
- **Two verified gaps in the text:** cross-border transfer is undisclosed (the project runs in
  `eu-central-1`, outside the Kingdom), and sub-processors are unnamed — the reviewed text must
  name Supabase and the model provider, and say whether prompts are excluded from training.
- **Never cite article numbers a language model produced.** `docs/data-policy-decisions.md`
  already warns these are "exactly what a language model invents." Cite principles to counsel.

### [HISTORICAL] D6b — Consent has no re-prompt path, and the version string is client-supplied

`PRIVACY_POLICY_VERSION = "2026-08-23-draft-1"` (`web/api/app.py:352-354`) is stamped onto each
consent record, but **nothing compares a stored version to the current one.** Bumping it would
silently re-attribute every existing consent to the draft string.

**Three defects to fix before a comparator is worth building**, all verified:

1. **The version is sent by the browser** (`static/js/account/handlers.js:306`) and the trigger
   validates only that it is 1–64 characters
   (`…20260823014034_marketing_consent_record.sql:129-142`). A client can stamp the current
   version without ever being shown the prompt. **The server must supply it.**
2. **The trigger's no-op branch keeps the old version when consent stays true** (`:110-124`), so
   a re-affirmation cannot be recorded at all without a fake withdraw-then-grant that would
   write a false `withdrawn_at`. **Add an explicit re-affirm branch.**
3. **The direct column grants survive the repoint.** Once the toggle calls the RPC (M1b),
   `revoke update` the four consent columns — otherwise every validation the RPC performs is
   bypassable by the PATCH it replaced.

**Decide:** re-prompt on every change, or only on material change? **Recommendation:** material
change only, with the comparator built server-side and materiality judged by a human per bump.

---

## [HISTORICAL] 2. Dependency order

### [HISTORICAL] Ships before the meeting

1. **Account-menu consolidation** — `TODO.md:857-858` says appetite-only.
2. **Monogram transition** — half-shipped: `web/templates/account.html:86` already has
   `@view-transition { navigation: auto; }` and names `#account-monogram` at line 139. Only the
   sidebar end is missing; `_sidebar.html:125-130` states the blocker (the macro renders twice,
   and a closed offcanvas is `visibility:hidden`, which still counts).
3. **Re-verification reads** for Migration A/B — §0 is this work.
4. **Bilingual email copy drafting** — writing the bodies is copywriting; applying them is D6.
5. **The `delete_user` dispatcher method and its in-memory double** — decision-neutral.

### [HISTORICAL] Strictly gated on an answer

The saga (D1, then D2/D3/D4 shape every state and string) · the `profiles` freeze, the consent
RPC and the `update_own_preferences` gate (D5) · the `chat_sessions` FK (D1 **and** a proven
saga) · the consent comparator (D6b).

### [HISTORICAL] Gated on a document or a dashboard

`/privacy` legal review (D6) · the Supabase email templates · **backup confirmation and one
restore rehearsal** (`TODO.md:1682`), required _before_ the destructive DDL · the project's JWT
expiry, **not recorded anywhere in this repository**, which sets D5's exposure window.

---

## [HISTORICAL] 3. The one migration batch

Contract throughout: one concern per file, `security definer` + `search_path = ''` +
owner-filtered, schema before code, and **rename each file to what `list_migrations` reports
after applying**. Guard every DDL statement with `SET lock_timeout` — the batch touches
`profiles`, which every request reads. Add foreign keys `NOT VALID`, then `VALIDATE` separately.

**M1 — `update_own_marketing_consent(p_clear_age boolean)` RPC.** `security definer`,
`search_path = ''`, filtered on `auth.uid()` only. **Withdrawal only** — it sets
`marketing_consent = false` and, when asked, `age = null`. Because the privilege-guard trigger
cannot fire inside a `security definer` function (§0b.3), the body must use a **static column
list**, never a jsonb-driven `SET`. Granted to `authenticated`; register the third RPC-contract
exemption in `supabase/README.md`. Additive; no destructive check.

**M1b — repoint the consent toggle** (`static/js/account/handlers.js`), **then
`revoke update` on the four `marketing_consent*` columns** (D6b.3). Code between two
migrations, deliberately: the revoke is what makes M1's validation unbypassable, and M2 is
unsafe before the repoint is verified.

**M2 — freeze the `profiles` UPDATE policy.** Add `and (select public.is_active_account())` to
the live `USING`. **Leave SELECT alone** (a locked-out reader must read `is_disabled` and
`disabled_reason`) and **leave INSERT alone** (the signup fallback runs before a profile row
exists).

**M2b — gate `update_own_preferences` on `is_active_account()`.** Safe for the signup path: the
function already raises `P0002` when no profile row exists, so a profile-less caller is refused
today regardless. Without M2b, M2 closes one of two doors.

**M3 — Migration A, re-verified.** The two `NO ACTION` FKs → `ON DELETE SET NULL`. Destructive
DDL, own file, backup taken first. Re-verify constraint names, non-null populations, index
survival, and §0's four new FKs.

**M4 — the saga table, with deletion-pending as its own state.** This is the change that makes
D2 honest.

- `account_deletions` carries **no FK to `auth.users`** (it must survive the provider deleting
  that user) and holds `state`, `requested_at`, `grace_until`, `next_attempt_at`,
  `attempt_count`, and **`lease_until`** (M5's concurrency guard).
- **Pending is not `is_disabled`.** Conflating them is what made the first draft's cancel path
  unreachable and lets an operator's Enable resurrect a pending deletion —
  `admin_set_user_flags` clears `disabled_at`/`disabled_by`/`disabled_reason` unconditionally
  (`supabase/migrations/20260828001543_admin_rpcs_require_an_enabled_actor.sql:252-264`).
- `admin_set_user_flags` must **refuse or explicitly handle** a target with a pending saga row.
- `account_deletion_is_pending()` is granted to `authenticated` — a **fourth** browser-callable
  `security definer` function. Register the exemption **and** update the `browser_callable`
  allow-list at `supabase/tests/function_acls.test.sql:41`, or that test fails.
- Fold the pending check **into `is_active_account()`** rather than adding a parallel check to
  each chat policy; one predicate, one place.

**M5 — the saga RPCs.** `service_role`-only, each idempotent, each claiming the row with
`update … where lease_until < now() returning` so three drivers cannot run one step twice.
`record_auth_outcome` must treat GoTrue's `user_not_found` as **success**, not failure —
`classify_admin_failure` classifies it as the definitive `no_such_account`
(`web/services/auth_admin.py:74-77`), which would otherwise flip a completed saga to failed.
Reconciliation reads GoTrue's admin get-by-id, **not `auth.users`** (§0b.4).

**M6 — `chat_sessions.owner_id` FK `ON DELETE RESTRICT`, last.** Orphan check first; any hit is
an incident, not a row to force. Do not edit the false header at
`20260820131914_chat_session_persistence.sql:38-42` — an applied migration is a point-in-time
record.

**Not in this batch:** any retention purge job, the assistant-content and `audit_log` text
bounds, and the `chat_archive` purge path.

---

## [HISTORICAL] 4. The application work

Global: Python 3.10 · logical CSS only · every new string in **both** catalogues · no new
top-level `runtime.*` namespace (pinned to eleven; nest under `runtime.profile.*`) ·
`ASSET_VERSION` bumped on any CSS/JS touch.

**Deletion endpoints** (`web/api/account.py`), all deriving the user from `g.identity`:

- **Step-up authentication is required on the request.** A bearer token alone must not be able
  to delete an account — `docs/ARCHITECTURE.md:378` calls a shared machine "the ordinary case,"
  and the export route already hands over everything. Reuse the nonce re-authentication the
  password change uses (`static/js/account/handlers.js:241-243`), plus a typed confirmation.
- **The pending state must be admitted to `_gate`.** Cancel and status are exempted by pending
  state only — never by `is_disabled`, which would open the gate to every banned account.
- **Do not rotate the password at request time.** Revocation-by-rotation
  (`web/services/auth_admin.py:153-156`) belongs at final purge. During grace, revoke sessions
  by setting a **GoTrue ban** in the same dispatcher call, lifted on cancel — which also closes
  the provider-side hole in §0b.1.
- **Rate limits are named config, not a phrase.** Add `account_deletion_api` (tight, per
  account) and a separate, looser `account_deletion_status_api` to `web/config.yaml` beside
  `account_bulk_delete_api: "10 per hour"` — separate because the plan makes polling a driver.
  Note the limiter's `memory://` counters reset on every worker recycle, so these bound
  accidents, not a determined attacker; the durable guards are the lease and idempotency.

**In-flight generation.** A 409 while a conversation is mid-generation is a check followed by a
separate action. A stream admitted just before the disable commits can run for up to 300s
(`docs/ARCHITECTURE.md:173`) and write its turn **after** the purge — `chat_append_turn` has no
disabled or pending check and lazily creates the session row
(`supabase/migrations/20260828002052_chat_append_turn_guards_source_elements_not_just_the_array.sql:102-106`).
**Therefore:** `chat_append_turn` refuses a pending owner, **and** the purge runs again inside
the RPC that moves the saga to auth-delete-begun. Before M6 the gap is a silent orphan
transcript; after M6 it is a stuck saga and a `23503`.

**Deletion UX** (`account.html`): a destructive-pattern card stating truthfully what goes and
what stays. Arabic reviewed first.

**`page.policy.retentionBody` must change in the same release.** It currently reads _"deleting
your account entirely is not yet self-service — contact us if you need it"_
(`web/i18n/en.yaml:971`). Shipping deletion without changing it makes the privacy policy false.
Bump `PRIVACY_POLICY_VERSION` with it.

**Dispatcher** (`web/services/auth_admin.py`): add `delete_user` and a ban/unban to all three
implementations, reusing `classify_admin_failure` so a timeout is `ambiguous`, not `failed`.

**Tests.** Each must fail against today's code. Saga state transitions, lease contention, and
idempotency; a disabled account can withdraw consent but cannot write `first_name`; **a
disabled account cannot write `preferences` via the RPC** (M2b); `chat_append_turn` refuses a
pending owner; ambiguous-timeout reconciliation. The disabled-account assertions belong in
`supabase/tests/` — the browser suite cannot mint a disabled JWT, **and there is no such
assertion today**, which is how this class of gap survived. Note `supabase/tests/` runs by hand
and is not in CI (`docs/ARCHITECTURE.md:507`), so these are a release-checklist item, not a gate.

### [HISTORICAL] Security email — the mechanism exists, and is still the wrong choice

`TODO.md:235` says GoTrue "offers no per-request language negotiation" and that this is "not a
code change." **The first half is now false.** Supabase's Send Email Hook replaces GoTrue's
templating with a function that picks language per user, first-party with an official i18n
example, and `web/api/auth.py:219,434` already carries `lang` through signup and recovery.

**Reject it anyway, and record why.** It puts an Edge Function and a third-party SMTP provider
on the critical path of signup and password recovery; a cold start or provider latency spike
turns both into 500s. This repository's rule is that an outage is a 503 and never a 401.

**Ship instead:** one dual-language template per type, **Arabic first**. Set `dir` on `<table>`
and `<td>`, never CSS alone — desktop Outlook renders through Word, which ignores
`direction: rtl`. Isolate every token and URL in `dir="ltr"`, and use **one link shared by both
languages** so the visible target is unambiguous. **Never interpolate `.Data.*`** — signup to
an arbitrary address is attacker-triggerable and the metadata is unbounded at the GoTrue layer.
Keep each body well under Gmail's 102 KB clip. Change **one** template first and verify by
watching `recovery_sent_at` move: a broken recovery template locks people out.

---

## [HISTORICAL] 5. The deletion saga — who drives it

Verified constraints: `gunicorn.conf.py` pins `workers = 1` and says it must stay 1;
`deploy/sfda-copilot.service:12` adds `--threads 8 --max-requests 1000`, so the worker recycles
roughly every thousand requests; there is **no cron, no worker, no thread, no `pg_cron` and no
`pg_net`** anywhere in the repository or the deployment.

**The reader's own request drives the happy path synchronously; two drivers share the retry
path, and every step claims a lease first.**

1. **One commit:** insert the saga row in `pending` state, set the GoTrue ban, evict the
   **`identity_flags`** cache. (The first draft said "evict the token cache"; that cache stores
   nothing at TTL 0 — `web/config.yaml` sets `auth_token_cache.ttl_seconds: 0` — so evicting it
   is a no-op. The cache that matters is `identity_flags`, 30 seconds.)
2. **Inline continuation, bounded and sequential:** revoke sessions → record → purge by
   `owner_id` → re-check in-flight → begin auth delete → GoTrue delete → record outcome. Each
   step idempotent, each provider call resolved as accepted / rejected / unknown.
3. **Retry:** (a) an admin console "reconcile" action; (b) a **systemd one-shot Python entry
   point** run on a timer, using the service key **already in `.env`** and speaking to the
   database directly — no HTTP, no new credential.

**Why not the HTTP-timer-with-admin-credential of the first draft.** The admin gate takes a
bearer header verified live against GoTrue (`web/api/admin.py:84-109`), so a timer would have
to store an administrator password or refresh token on the VPS. A leak of that grants the whole
console, including `change_email` (`web/api/admin.py:707`) — takeover of any account. Worse,
the timer's account would count as an enabled administrator, so the last human admin could
delete themselves and the last-admin guard would never fire. That is strictly worse than the
`pg_cron` it was meant to avoid. The one-shot entry point adds no credential that is not
already on the box.

**Not a thread, not `atexit`, not an in-Flask scheduler.** `--max-requests` recycles the worker
under the saga's feet, and a daemon thread dying mid-GoTrue-call produces exactly the
unknown-outcome state with nobody left to reconcile it.

**Reconciliation rule:** if GoTrue's admin get-by-id no longer returns the user, the step
succeeded, whatever the transport said.

### [HISTORICAL] What the reader is told, accurately

- **Goes:** login identity, profile (name, age, organization, specialization, consent record),
  every transcript, `profile_last_seen`, quota overrides.
- **Stays, and all of it must be disclosed:** administrative audit rows written before the
  deletion; the deletion ledger row (uuid and timestamps only, per D3);
  `notifications.target_user_id`, a bare uuid beside an operator's message body
  (`supabase/migrations/20260823202130_notifications_table.sql:31`); the dormant archive;
  backups until their retention expires — **claim no day-count until `docs/OPERATIONS.md`
  records one**; the model provider's own prompt retention; and server logs, including
  `/c/<uuid>` access-log paths, which `TODO.md:1520` leaves open.
- **Clears on worker recycle, not on deletion:** the in-memory `ConversationStore` prompt
  window (`docs/ARCHITECTURE.md:137-140`). Not durable, but not instant either.

---

## [HISTORICAL] 6. Risk register

| Risk                                                           | Guard                                                                                              |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Cancel path unreachable — grace is fake                        | Pending is its own state; `_gate` exempts pending only; no password rotation until purge           |
| Stolen token deletes an account                                | Step-up re-authentication plus typed confirmation on request                                       |
| Operator's Enable resurrects a pending deletion                | `admin_set_user_flags` refuses or handles a pending target; cancel restores only what the saga set |
| In-flight stream writes a transcript after the purge           | `chat_append_turn` refuses a pending owner; re-purge inside the auth-delete step                   |
| Deletion audit row preserves the deleted person's email and IP | Saga rows carry uuid and timestamps only; keyed hash destroyed at grace expiry                     |
| Two drivers run one step twice                                 | `lease_until` claim; `user_not_found` maps to success                                              |
| M2 before M1b — consent withdrawal breaks silently             | Fixed order; SQL assertion proves a disabled account can still withdraw                            |
| M2 without M2b — the RPC hole stays open                       | M2b in the same batch, with its own failing-first test                                             |
| M6 before a working saga — deletion fails `23503`              | M6 last, gated on a proven saga                                                                    |
| Timer credential leak grants the whole console                 | No new credential: one-shot entry point on the existing service key, no HTTP                       |
| Consent RPC used as write amplification                        | Withdrawal-only; already-false is a no-op                                                          |
| Client stamps a policy version it never saw                    | Server supplies the version; RPC validates it                                                      |
| Archive salts set without a purge path                         | Refuse at startup, not a checklist                                                                 |
| DDL queues behind a slow read and starves the pool             | `SET lock_timeout`; `NOT VALID` then `VALIDATE`                                                    |
| Migration filename drift                                       | Rename from `list_migrations` after each apply                                                     |

---

## [HISTORICAL] 7. What this plan declines to do

1. **A second permissive UPDATE policy for consent** — disproved live; RLS restricts rows, not
   columns.
2. **A full five-state account lifecycle.** One new state (`deletion_pending`) is added because
   §0b.2 proved it load-bearing; the other three states the research proposed remain taxonomy
   without a customer.
3. **Anonymise-instead-of-delete for transcripts.** The research argued for tombstoning because
   a regulatory query is GxP evidence belonging to a corporate licensee. That premise fails
   here — `docs/PRODUCT.md` describes individual professional accounts, not seats under a
   licence. Purge the transcripts; keep the audit log (D3).
4. **A 180-day transcript TTL** — the benchmarks are consumer chat logs.
5. **Any purge job before someone owns the retention period.**
6. **`pg_cron`, an in-Flask scheduler, or a background thread** — see §5.
7. **An HTTP reconcile endpoint driven by a stored admin credential** — strictly worse than the
   `pg_cron` it replaces.
8. **Scrubbing `audit_log`, or "anonymising" the archive by destroying its salts** — the first
   destroys accountability evidence; the second destroys future erasure capability while
   calling itself erasure.
9. **The Send Email Hook** — rejected on availability, not capability, and the distinction is
   recorded so nobody re-litigates it from the stale premise.

---

## [HISTORICAL] 8. What the repository cannot answer

1. **D1–D6b.** The product owner, with counsel present for D3, D4 and D6.
2. **The project's JWT expiry** — not in this repository; it sets D5's exposure window.
3. **Backup schedule, retention and PITR status**, then one restore rehearsal — before M3.
4. **Whether the pinned Supabase SDK exposes a GoTrue admin delete and a ban.** Today the
   codebase calls only `update_user_by_id` and `sign_out`.
5. **Whether the Flask session cookie is signed-only or encrypted** — it holds the email and
   the JWT (`web/api/app.py:926-928`), and that changes what a deletion leaves behind.
6. **Whether the access log retains full `/c/<uuid>` paths** (`TODO.md:1520`).
7. **Arabic review** of every new string: the deletion disclosure, the email bodies, and the
   rewritten `retentionBody`.
