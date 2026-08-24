STATUS: IMPLEMENTED. Written 2026-08-23; built 2026-08-24.

# Admin Broadcast & Reader Notification Center

**Source:** `TODO.md` → [Admin broadcast & Reader Notification Center](../TODO.md#admin-broadcast--reader-notification-center-popups-banners-and-inbox-history) — see that entry's own status line for the current one-paragraph summary.

**Implementation note (2026-08-24):** every section below shipped as designed, including the SDK upgrade §7 Step 4a treats as mandatory-not-conditional — `@supabase/supabase-js` is now pinned at `2.74.0` (up from `2.39.7`; `realtime-js@2.74.0` carries the `private` channel option this plan's own research proved `2.9.3` lacked entirely). That upgrade was preceded by a full read of `auth-js`'s changelog across the whole version span (no breaking change found to the `onAuthStateChange`/session-storage/PKCE behavior this app's own code depends on), and followed by the full non-browser and browser suites passing, including the auth/recovery-adjacent tests — but **not** by a login against a real Supabase project, which no tool available in that session could do. Treat the auth flow as diligently reviewed, not as production-verified, until it has been exercised against a live project once.

**Realtime authorization, verified directly against the live project (2026-08-24)**, exactly as §8 says a browser mock cannot: `realtime.messages` has `relrowsecurity = true`, `notify_own_channel_select` is its only policy (`to authenticated`, `SELECT` only — no `INSERT` policy exists for any non-service role, so a reader genuinely cannot publish), and a session-variable simulation of two distinct readers (`request.jwt.claims`/`realtime.topic` GUCs, the same ones PostgREST/Realtime actually set per connection) confirmed the policy admits reader A onto `notify:user:<A>` and refuses `notify:user:<B>`. `anon` holds the same table-level grants as `authenticated` but matches zero policies, so it is denied entirely by construction, not by an extra rule.

## Context

Operators today have no way to reach readers directly — no maintenance warning, no regulatory-alert push, no feature announcement. TODO.md scopes this as a full feature: three popup styles (toast/banner/modal), a reader inbox (bell + unread badge + history), and an admin composer with targeting (all/role/tier/user) and engagement metrics. This plan turns that scope entry into a buildable design, grounded in this repo's actual patterns rather than generic notification-system advice.

The delivery mechanism was the one real open question — TODO.md's own spec line says "Supabase Realtime broadcast for active sessions + REST DB query for offline/new sessions." **Decided (user-approved): hybrid**, per the TODO's own spec. Everything below scopes that decision narrowly (per-user private channels, content-free push payloads, service-role REST publish, no persistent server-side connection) to keep it from destabilizing the single-worker deployment or opening a leak surface — and, after two rounds of adversarial review below, to keep it from silently assuming SDK capabilities that don't actually exist yet.

This plan went through three passes: an initial draft grounded in direct codebase research, a comparison against two independently-drafted alternative plans, and an adversarial read-only review by OpenCode (`gpt-5.6-sol`) that found real, verified defects in the second draft. Every fix below was checked against the real source before being accepted — several of the reviewer's most consequential claims were independently re-verified in this session, not taken on faith.

---

## Adversarial review round (OpenCode, `gpt-5.6-sol`, read-only)

Dispatched via `/opencode-delegate` against the prior draft of this plan. 17 confirmed defects, 6 suggestions. The two most load-bearing factual claims were independently re-verified before accepting anything:

- **Verified true:** `@supabase/realtime-js@2.9.3` is the actual pinned version (`package-lock.json:347`), and its `RealtimeChannelOptions` type (`node_modules/@supabase/realtime-js/src/RealtimeChannel.ts:15-27`) only declares `broadcast`/`presence` config — no `private` field exists in this version at all. The earlier draft's "may not support private channels, verify" hedge was too soft — **the SDK upgrade is mandatory, not conditional.**
- **Verified true:** reader-facing pagination already uses a real keyset cursor (`web/api/app.py:2451-2496`: `cursor_updated_at`/`cursor_id` params, `chat_store.py:486-504`). The earlier draft's "this app uses offset/limit consistently, so reject cursor pagination for notification history" claim was wrong — reversed below.

Every other fix in this section came from the reviewer and was accepted on its own merits (each is a verifiable defect against a real rule in this codebase, not a stylistic preference) or reworked where the reviewer's fix and the plan's original goal both had a valid point.

### Confirmed defects, and how each is fixed below

1. **Composite primary key can't hold `ON DELETE SET NULL`.** `primary key (notification_id, user_id)` makes `user_id` implicitly `NOT NULL` in Postgres — the anonymize-on-delete design from the previous round would make account deletion _fail_ against a referenced row, not anonymize it. **Fix:** surrogate `id` primary key on both `notification_recipients` and `user_notification_reads`, with a `unique(notification_id, user_id)` constraint instead (§1).
2. **`notifications.target_user_id` wasn't covered by the anonymization story at all**, and the plan's own CHECK constraint requires it to be non-null forever for `target_kind='user'` rows — anonymizing it would violate the plan's own schema. **Fix:** explicit decision, stated rather than left as a silent gap — `target_user_id` is **not** anonymized; it's treated as an administrative targeting instruction (who the admin chose), the same category as `audit_log`'s intentionally-retained before/after values, not reader-subject data. Documented as a considered asymmetry, not an oversight (§1).
3. **`notifications_mark_read` didn't verify the caller was an actual recipient.** Scoping the write by `p_user_id` stops a reader forging _someone else's_ receipt, but not fabricating their _own_ receipt for a notification never targeted to them — corrupting engagement metrics, and for a `modal`, potentially faking an acknowledgment record for something they were never shown. **Fix:** the RPC now requires either `target_kind='all'` or an existing `notification_recipients` row for the caller before it will upsert, and validates the `action` against the notification's `type` (§1).
4. **No actor revalidation inside the admin RPCs' own transaction** — a demotion between the Flask gate and the SQL write would still let a just-demoted account publish. This repo already closes exactly this race elsewhere (`admin_update_profile` at `20260822225415_profile_identity_atomic_cutover.sql:193-201`, `admin_set_user_flags` at `20260816121335_diff_based_admin_user_flags_audit.sql:48-57`) — the plan should have followed that precedent from the start. **Fix:** every admin notification RPC revalidates `p_actor_id` is still an enabled administrator inside its own transaction, refusing `actor_no_longer_administrator` if not (§1, §3).
5. **The batch Realtime-publish shape assumed a `private` flag exists on the batch REST endpoint without confirming it.** Public/private channel settings must match on both ends, and only the single-topic endpoint is documented with `?private=true`; the batch body's private-support isn't confirmed. **Fix:** treat the exact request shape as an implementation-time verification gate, not an assumption — chunk to per-recipient calls with an explicit private flag if the batch endpoint doesn't support it (§2).
6. **The SDK-upgrade language was too soft** — see "Verified true" above. **Fix:** upgrade is now a required rollout step, not a conditional branch (§2, §7).
7. **The broadcast rate limit inherits this app's default IP-based key**, not an admin-id key — a compromised or malicious admin account could spam via multiple IPs, and admins behind one NAT would wrongly share a budget. **Fix:** `broadcast_limit` gets its own `key_func` keyed on `g.identity.user_id`, not the Limiter's default `get_remote_address` (§3).
8. **`client_request_id` uniqueness wasn't scoped to actor or payload** — a reused or colliding id from a different actor/payload would silently return the stale original row instead of erroring. **Fix:** uniqueness scoped to `(created_by, client_request_id)`, plus a stored payload hash; an exact replay returns the original result, a same-id-different-payload replay returns 409 `idempotency_conflict` (§1, §3).
9. **Dynamic `'all'` targeting has no stable denominator** for "% who read/dismissed," which TODO.md explicitly wants. **Fix:** every notification — including `'all'` — stores a plain `target_count` integer computed at send time (not a full recipient snapshot for `'all'`, just the count), used purely as the metrics denominator; the _active-list/delivery_ decision for `'all'` stays dynamic so new signups still see an open maintenance banner. This resolves the tension between "stable metrics" and "banner reaches new signups" without conflating the two concerns (§1).
10. **`presented_at` still overclaimed** — even after the previous round's rename from `delivered_at`, the column fires at the RPC/response layer, not when a popup actually renders client-side, and the plan didn't build a real presentation callback. **Fix:** renamed again, to `served_at`, with a precise definition: "stamped when a REST response for `/active` or `/history` included this row — a network fact, not a rendering fact." No new client→server call added; the claim now matches what's actually measured (§1).
11. **`resend_of` was a bare FK with no index**, violating `supabase/README.md`'s "every FK gets its index in the same migration" rule (verified directly against that file earlier in this process). **Fix:** `notifications_resend_of_idx` added; the now-redundant `notification_recipients_notification_idx` (redundant once the unique `(notification_id, user_id)` constraint's leading column already covers it) is dropped (§1).
12. **The plan overclaimed RPC-contract uniformity** — it said "7 RPCs, all following the `p_owner_id`-first-arg contract," but actually named 8 functions, and the admin RPCs don't take an ownership-filtering argument at all (they take an actor for audit attribution, a different, already-precedented shape). **Fix:** corrected below to state plainly which RPCs follow which shape (§1).
13. **The inbox, as drawn, would violate DESIGN.md's One Drawer Rule** (`DESIGN.md:349`, read directly earlier in this process: "Navigation never spawns a second drawer... Two offcanvases on a phone means two backdrops, two focus traps") — the sidebar is already a mobile offcanvas, and a second inbox drawer would stack on top of it. **Fix:** the inbox is a centered modal dialog on every viewport, never an offcanvas — it reuses this app's existing modal utility (the same one auth/profile already use) instead of adding a second drawer, sidestepping the conflict entirely rather than building a responsive drawer/modal split (§4).
14. **`title_ar`/`body_ar` were nullable in the schema** while the plan's own frontend section described them as validated/required and TODO.md requires dual-language fields. **Fix:** both Arabic columns are `NOT NULL`, matching the English ones, enforced in Flask (400) as well as SQL, not just client-side (§1).
15. **Deactivate/delete never triggered a Realtime invalidation**, only create did — an open tab could keep showing a modal an operator had just pulled until reload or reconnect, undermining the entire point of "early-deactivate." **Fix:** the same content-free invalidation publish fires on create, deactivate, _and_ delete (§2).
16. **Three factual claims in the plan itself were wrong**, corrected here:
    - Reader history now uses **cursor/keyset pagination** (`cursor_updated_at`/`cursor_id`-style, matching `web/api/app.py:2451-2496` exactly), not offset/limit — the earlier "this app is offset/limit-consistent" claim was false; the reader-facing precedent is keyset (§3).
    - The generic admin route-gating test (`test_admin_page.py`) **skips every route without a GET method**, so the new POST/DELETE notification mutations need their own dedicated auth-gate tests, not a free ride from that test (§8).
    - `mypy` is correctly excluded from pre-commit per `CLAUDE.md`, but the plan's Verification section hadn't listed `mypy web` as its own separate check — added explicitly (§Verification).
17. **The Playwright test plan assumed Realtime/channel coverage the existing browser-test mock doesn't have** — `conftest.py`'s `SUPABASE_BROWSER_MOCK` has no `channel`/broadcast/private-auth simulation. **Fix:** UI-level Playwright tests scope to the REST path only (which the mock supports); private-channel authorization gets its own separate, non-browser-mock integration test — a mock can't prove reader A is denied reader B's topic (§8).

### Suggestions adopted

- **Async banner arrival never steals keyboard focus** — live-region semantics (`aria-live="polite"`) for the banner/toast; forced focus is reserved for the acknowledgment modal alone, where it belongs (§4).
- **A session-level modal snooze**, so Escape/backdrop-dismiss doesn't recreate a practical trap: without it, a reader who dismisses stays on the page and the next ~30-60s poll/reconnect could reopen the same modal immediately. Client-side (`sessionStorage`) suppression for that specific notification for the rest of the browser session; still unacknowledged server-side, still resurfaces on the next real session (§4).
- **Multi-tab behavior stated explicitly rather than left implicit**: each open tab holds its own per-user channel and its own unread badge; mark-read/acknowledge in one tab reconciles in a sibling tab only on that sibling's own next poll or visibility-change refetch, not instantly — an accepted v1 scope limit, not an oversight (§4).
- **Direct SQL/integration tests for the security boundary itself** — cross-user mark-read attempts, actor demotion mid-transaction, wrong action/type combinations, and confirming `authenticated` genuinely cannot execute the service-only RPCs — added to §8, since a Flask-level mock alone can't prove these properties.

---

## Research this plan is built on

- **Codebase** (3 parallel Explore passes, verified against source, plus direct reads of `audit_log.sql`, `DESIGN.md`'s Notices section and One Drawer Rule, and `test_admin_page.py`'s pinned namespace list): frontend layering, admin console tab/route/RPC patterns, auth/rate-limit/identity-cache internals, confirmation this app is single-worker with no prior Realtime/websocket usage.
- **Supabase Realtime docs (ctx7)**: public channels skip RLS/authorization entirely; private channels enforce it via a policy on `realtime.messages` gated by `realtime.topic()`.
- **External research** — common mistakes in broadcast/notification systems (delivery-channel isolation, alert fatigue, client-trust bugs, reconnect/replay handling) and toast/banner/modal design patterns (2026 sources) — every finding has an explicit mitigation below.
- **Adversarial review (this round)** — see above.
- **Note on delegated review:** the community-mistakes and creative-design research was gathered via read-only web search (plan mode's hard read-only constraint ruled out dispatching write-capable implementer CLIs during planning). The security review, once out of plan mode, _was_ run for real — `/opencode-delegate` with `gpt-5.6-sol`, read-only `plan` agent, against a copy of this document placed inside the repo tree (the reviewer runs read-only with no auto-approval for paths outside its working directory, so the plan file had to be reachable from `--cd` — first attempt failed silently for exactly this reason and was redispatched after copying the file in). The Antigravity (`agy-delegate`) and Codex (`codex-delegate`, `luna`) passes originally requested were not run in this session; recommended as a further round if wanted.

---

## 1. Database schema

### `public.notifications`

```sql
create table if not exists public.notifications (
  id             uuid primary key default gen_random_uuid(),

  type           text not null check (type in ('toast','banner','modal')),
  severity       text not null default 'info' check (severity in ('info','success','warning','danger')),

  title_en       text not null check (char_length(title_en) between 1 and 200),
  title_ar       text not null check (char_length(title_ar) between 1 and 200),
  body_en        text not null check (char_length(body_en) between 1 and 2000),
  body_ar        text not null check (char_length(body_ar) between 1 and 2000),

  target_kind    text not null check (target_kind in ('all','role','tier','user')),
  target_role    text check (target_role is null or target_role in ('user','admin')),
  target_tier    text,
  -- Not anonymized on account deletion — deliberately. This column records an
  -- administrative instruction ("who the operator chose"), the same category
  -- as audit_log's intentionally-retained before/after values, not reader-
  -- subject data. Contrast notification_recipients.user_id and
  -- user_notification_reads.user_id below, which ARE anonymized because they
  -- record what a reader did, not what an admin decided.
  target_user_id uuid,
  check (
    (target_kind = 'all'  and target_role is null and target_tier is null and target_user_id is null) or
    (target_kind = 'role' and target_role is not null and target_tier is null and target_user_id is null) or
    (target_kind = 'tier' and target_tier is not null and target_role is null and target_user_id is null) or
    (target_kind = 'user' and target_user_id is not null and target_role is null and target_tier is null)
  ),

  -- Metrics denominator, captured at send time for EVERY target_kind
  -- including 'all' (a plain count, not a full recipient snapshot for
  -- 'all' — see the split decision below). Answers "% who read this" as a
  -- stable historical fact even though 'all' delivery itself stays dynamic.
  target_count   integer not null check (target_count >= 0),

  requires_ack   boolean not null default false,
  check (type <> 'modal' or requires_ack = true),
  check (type = 'modal' or requires_ack = false),

  -- Denormalised actor, no FK — same reasoning as audit_log.actor_id: an
  -- operator account later deleted must not erase who sent this.
  created_by       uuid not null,
  created_by_email text not null,

  -- Idempotency: scoped to the actor, not global, so a colliding id from a
  -- different admin can't silently return someone else's row. Paired with a
  -- payload hash so a same-id-different-content replay is a conflict, not a
  -- silent stale success.
  client_request_id uuid not null,
  request_payload_hash text not null,
  unique (created_by, client_request_id),

  -- Provenance for a resend, not a live relationship — purely for the
  -- history table's "resent from #..." display and audit trail.
  resend_of         uuid references public.notifications(id),

  created_at     timestamptz not null default now(),
  expires_at     timestamptz,
  deactivated_at timestamptz,
  deactivated_by uuid,
  deleted_at     timestamptz,
  deleted_by     uuid,

  check (expires_at is null or expires_at > created_at)
);

create index if not exists notifications_active_idx
  on public.notifications (target_kind, created_at desc)
  where deactivated_at is null and deleted_at is null;
create index if not exists notifications_created_by_idx on public.notifications (created_by);
create index if not exists notifications_target_user_idx on public.notifications (target_user_id)
  where target_kind = 'user';
create index if not exists notifications_resend_of_idx on public.notifications (resend_of);

alter table public.notifications enable row level security;
-- Zero policies, the audit_log template. Every reader-facing endpoint in
-- TODO.md's own spec is a Flask route, never a direct-from-browser Supabase
-- call — there is no browser-direct access path here to gate with a policy.
revoke all on public.notifications from anon, authenticated;
```

### `public.notification_recipients` (snapshot join table — see decision below)

```sql
create table if not exists public.notification_recipients (
  -- Surrogate key: user_id must stay nullable for ON DELETE SET NULL, which
  -- a composite (notification_id, user_id) primary key would rule out —
  -- Postgres makes every PK column implicitly NOT NULL, so that shape would
  -- make account deletion fail instead of anonymize. Caught in adversarial
  -- review; this is the fix.
  id               bigint generated always as identity primary key,
  notification_id  uuid not null references public.notifications(id),
  -- Real FK, ON DELETE SET NULL: this is reader-subject data, not actor
  -- attribution (contrast public.audit_log.actor_id and
  -- notifications.target_user_id above, both deliberately un-anonymized).
  -- Anonymizing on deletion while keeping the row preserves aggregate
  -- audience-size counts without keeping a deleted reader's identity
  -- attached to them.
  user_id          uuid references auth.users(id) on delete set null,
  created_at       timestamptz not null default now(),
  unique (notification_id, user_id)
);

-- No separate index on notification_id alone: the unique constraint above
-- already leads with it, so a dedicated index would be redundant.
create index if not exists notification_recipients_user_idx
  on public.notification_recipients (user_id, notification_id);

alter table public.notification_recipients enable row level security;
revoke all on public.notification_recipients from anon, authenticated;
```

_(Snapshotting explicitly excludes disabled accounts — `admin_create_notification` filters `profiles.is_disabled = false` when populating this table for a `role`/`tier`/`user` send, same as the existing `target_user_disabled` refusal for the `user` case.)_

### `public.user_notification_reads`

```sql
create table if not exists public.user_notification_reads (
  id               bigint generated always as identity primary key,  -- same surrogate-key fix as above
  notification_id  uuid not null references public.notifications(id),
  user_id          uuid references auth.users(id) on delete set null,  -- same anonymize-on-delete reasoning
  served_at        timestamptz,   -- stamped when a REST response for /active or /history included this row —
                                  -- a network fact, not a claim about client-side rendering
  read_at          timestamptz,   -- inbox item opened
  dismissed_at     timestamptz,   -- toast/banner dismissed (never set for a modal — see acknowledged_at)
  acknowledged_at  timestamptz,   -- modal's explicit Acknowledge action only — never implied by Escape/
                                  -- backdrop-click, and never set for a toast/banner (type-checked by the RPC)
  created_at       timestamptz not null default now(),
  unique (notification_id, user_id)
);

create index if not exists user_notification_reads_user_idx
  on public.user_notification_reads (user_id, created_at desc);

alter table public.user_notification_reads enable row level security;
revoke all on public.user_notification_reads from anon, authenticated;
```

_(Vocabulary used throughout this plan and in admin analytics copy: targeted → served → read → dismissed → acknowledged. "Delivered" is avoided everywhere as a claim this app can't actually verify.)_

**Why all three tables are zero-policy rather than reader-facing RLS**, despite the codebase's own `is_active_account_gates_chat_rls.sql` idiom for reader-owned tables: that idiom applies specifically when the _browser_ reaches a table directly. TODO.md pins every reader notification path (`GET /active`, `GET /history`, `POST /mark-read`) as a Flask route. There is no direct-from-browser access to gate, so mixing two access models for one feature would add a policy that constrains nothing real.

### RPCs — 8 functions, two distinct argument shapes (corrected from the prior draft's overclaim of "7, all `p_owner_id`")

**Reader-facing (4), ownership-filtering shape** — first argument is `p_user_id`, filtered inside the function, following the spirit of this repo's `p_owner_id` convention for reader-owned data:

1. `notifications_list_active_for_reader(p_user_id, p_role, p_tier)`
2. `notifications_list_history_for_reader(p_user_id, p_role, p_tier, p_cursor_created_at, p_cursor_id, p_limit)` — **cursor/keyset**, matching `web/api/app.py:2451-2496`'s existing `cursor_updated_at`/`cursor_id` pattern exactly (corrected from offset/limit in the prior draft — verified this app's reader-facing precedent is keyset, not offset).
3. `notifications_mark_read(p_notification_id, p_user_id, p_action)` — **now verifies eligibility**: requires `target_kind='all'` OR an existing `notification_recipients` row for `(p_notification_id, p_user_id)` before upserting, and validates `p_action` against the notification's `type` (`dismissed` only for toast/banner, `acknowledged` only for modal) — closes the "fabricate my own receipt for a notification I was never targeted by" gap adversarial review found.
4. `notifications_mark_all_read(p_user_id, p_role, p_tier)` — same eligibility join, one statement, not an N-call loop.

**Admin-facing (4), actor-attribution shape** — first arguments are `p_actor_id`/`p_actor_email` (audit attribution, matching `admin_write_settings`'s existing shape), **not** a `p_owner_id`-style row filter, because these mutate rows the actor doesn't own. Every one of the four **revalidates the actor is still an enabled administrator inside its own transaction** (matching `admin_update_profile`'s and `admin_set_user_flags`'s existing pattern — a gap the prior draft missed), refusing `actor_no_longer_administrator` if not: 5. `admin_create_notification(...)` — inserts the `notifications` row (including the send-time `target_count`); for `role`/`tier`/`user` targets also snapshots `notification_recipients` from `public.profiles` (excluding disabled accounts) in the same transaction; inserts an `audit_log` row. On a repeat `(created_by, client_request_id)`, returns the original row if the payload hash matches, or 409 `idempotency_conflict` if it doesn't. Raises `AdminActionRefused` for `no_matching_recipients`/`no_such_target_user`/`target_user_disabled`/`actor_no_longer_administrator`. 6. `admin_list_notification_history(p_limit, p_offset, p_status)` — admin console pagination stays offset/limit, consistent with the rest of the admin surface (`list_users`, `list_audit`) — only the _reader-facing_ history switches to cursor, since that's where this app's own precedent actually points. 7. `admin_deactivate_notification(...)` — sets `deactivated_at`/`deactivated_by`, atomic audit row, **publishes the same Realtime invalidation as create** (§2 — deactivate never used to trigger a push in the prior draft, a real gap: an open tab could keep showing a modal an operator just pulled). 8. `admin_delete_notification(...)` — **soft delete** (`deleted_at`/`deleted_by`), atomic audit row, same Realtime invalidation as deactivate. Never a hard `DELETE` — preserves recipient/read history for later audit review.

_(Deactivate and delete stay two separate functions rather than one with a mode flag — cleaner audit action strings, independently revokable later.)_

### Snapshot vs. dynamic audience — split decision, refined

- **`role`/`tier`/`user` targets → snapshot** into `notification_recipients` at send time (excluding disabled accounts). Accepted cost: a role/tier broadcast never retroactively reaches someone promoted into that role/tier after send.
- **`all` targets → delivery stays dynamic**, so a maintenance banner still reaches someone who signs up while the window is open.
- **Every target_kind → `target_count` captured at send time regardless.** This is the fix for the gap adversarial review found: without it, `'all'`-targeted metrics had no stable denominator at all (a live re-count is a moving target, and a lazy read-row count only measures who happened to fetch, not who was targeted). `target_count` is a single integer, cheap to compute even for `'all'`, and answers "how many were targeted" as a historical fact — completely separate from the _delivery_ decision above, which is what stays dynamic for `'all'`.

---

## 2. Realtime security design

**Mechanism (verified against current Supabase Realtime docs via ctx7):** Realtime Authorization is an RLS policy on `realtime.messages`, gated by `realtime.topic()`. A client channel must be created with `{ config: { private: true } }` to be subject to it at all — a public channel skips authorization entirely.

**Topology: per-user private channel, not per-role/tier.** Topic: `notify:user:<user_id>`.

```sql
create policy notify_own_channel_select on realtime.messages
for select to authenticated
using (
  (select realtime.topic()) = 'notify:user:' || (select auth.uid())::text
  and realtime.messages.extension = 'broadcast'
);
-- Deliberately no INSERT policy for `authenticated` — readers never publish.
```

**Why per-user, not per-role/tier, even though both are "private":** a shared channel's _membership itself_ is informative — anyone subscribed to `notify:role:admin` can infer "a broadcast is happening" purely from channel activity, correctly-scoped RLS notwithstanding. A per-user channel removes that inference surface entirely.

**Who publishes, and how:** this app is synchronous, single-worker, no async runtime — none should be added for this. `notification_service.publish_realtime(recipient_ids, notification_id)` is one (or, chunked, several) `httpx.post` calls to Supabase's Realtime REST broadcast endpoint per event, authenticated with the service-role key.

**The payload carries no notification content — only `{"notification_id": "...", "revision": <server timestamp>}`.** REST is the single source of truth for title/body/severity; Realtime's only job is telling an open tab "go refetch." A Realtime message discloses nothing on its own if intercepted, and it collapses "handle a push" and "handle a reconnect" into the exact same refetch code path.

**Verify the exact private-broadcast request shape before writing the publish code — do not assume.** Adversarial review flagged this precisely: Supabase's documentation confirms `?private=true` on the _single-topic_ REST broadcast endpoint, but does not clearly document private-flag support on the _batch_ `{"messages":[...]}` shape this plan originally assumed. If the batch endpoint doesn't support mixed/private publishing, chunk to individual per-recipient calls with an explicit private flag on each rather than assuming batching "just works" for private channels. This is an implementation-time verification gate, stated here so it isn't silently assumed away.

**Publish fires on create, deactivate, AND delete** — not just create. An admin pulling a wrong or urgent modal needs already-open tabs to actually stop showing it; publishing only on create (the prior draft's gap) would leave a deactivated modal blocking someone until their next reload or reconnect.

**Failure isolation:** every broadcast POST is wrapped in try/except in Python (never inside the SQL transaction), logged on failure, and never fails the admin's response. `GET /api/notifications/active` is the guaranteed-delivery path; Realtime is a latency optimization for open tabs, not the source of truth.

**Reconnect/reconciliation:** the browser channel gets its own exponential backoff on `CHANNEL_ERROR`/`TIMED_OUT`. Every successful `.subscribe()` — including the very first — triggers a `GET /api/notifications/active` refetch. The channel is torn down whenever the tab goes hidden (Page Visibility API) or the reader signs out, and re-established (with its own fresh reconcile fetch) when the tab becomes visible again or a new sign-in completes.

**SDK upgrade is a required rollout step, confirmed mandatory — not a conditional branch.** Verified directly: this app pins `@supabase/supabase-js@2.39.7` / `@supabase/realtime-js@2.9.3` (`package.json:5`, `package-lock.json:347`), and `realtime-js@2.9.3`'s `RealtimeChannelOptions` type (`node_modules/@supabase/realtime-js/src/RealtimeChannel.ts:15-27`) declares only `broadcast`/`presence` config — **no `private` field exists in this version.** The upgrade must also respect `services.js:15`'s documented version-specific `onAuthStateChange`/`_recoverAndRefresh` ordering the sign-in flow depends on — a full login/signup/recovery/reauthentication regression pass is required after upgrading, not a spot check, since that comment exists precisely because this ordering has silently changed across versions before. This is now §7 Step 4a, ahead of any Realtime code.

**Race safety on the client:** every in-flight notification fetch is stamped with the identity/session generation active when it was issued; a response that resolves after the reader has signed out or switched accounts is discarded rather than painted into the new session's UI.

**Multi-tab scope, stated explicitly (not left implicit):** each open tab holds its own per-user channel and its own unread badge. Mark-read/acknowledge in one tab reconciles in a sibling tab only on that sibling's own next poll or visibility-change refetch, not instantly. Accepted as a v1 scope limit.

---

## 3. Backend

### Reader — new `web/services/notification_service.py`, wired in `web/api/app.py`

| Method | Path                               | Auth             | Notes                                                                                                                                                                                                         |
| ------ | ---------------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/notifications/active`        | `@auth_required` | Language-resolved server-side from `title_en`/`title_ar` per request `lang`.                                                                                                                                  |
| GET    | `/api/notifications/history`       | `@auth_required` | **Cursor pagination** — `cursor_created_at`/`cursor_id` query params, matching `web/api/app.py:2451-2496`'s existing pattern exactly (corrected from offset/limit); returns `next_cursor` and `unread_count`. |
| POST   | `/api/notifications/mark-read`     | `@auth_required` | `{notification_id, action: read\|dismissed\|acknowledged}`; RPC now enforces recipient eligibility and action/type validity (§1).                                                                             |
| POST   | `/api/notifications/mark-all-read` | `@auth_required` | —                                                                                                                                                                                                             |

All four pass `g.identity.user_id`/`role`/`tier` server-side, never from the request. Every response sets `Cache-Control: private, no-store` — per-reader data, must not sit in a shared or intermediary cache.

New `web/config.yaml` rate-limit keys:

```yaml
notifications_active_api: '30 per minute'
notifications_history_api: '20 per minute'
notifications_mark_api: '60 per minute'
```

### Admin — `web/api/admin.py` + `web/services/admin_store.py`

| Method | Path                                        | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ------ | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| POST   | `/admin/api/notifications/audience-preview` | Dry run: resolves targeting against `profiles` (excluding disabled accounts), returns `{"target_count": N}`, persists nothing. Composer calls this on every targeting-field change.                                                                                                                                                                                                                                                                                   |
| POST   | `/admin/api/notifications`                  | Body includes `client_request_id` + the fields hashed into `request_payload_hash`. A repeat with the same `(actor, client_request_id)` and matching hash returns the original row (200); a mismatched-hash repeat returns 409 `idempotency_conflict`. 201 on first creation; 400 invalid payload; 422 invalid enum/target combo; 409 `AdminActionRefused` (`no_matching_recipients`, `no_such_target_user`, `target_user_disabled`, `actor_no_longer_administrator`). |
| GET    | `/admin/api/notifications/history`          | Offset/limit — template = existing `GET /admin/api/audit`.                                                                                                                                                                                                                                                                                                                                                                                                            |
| POST   | `/admin/api/notifications/<id>/deactivate`  | 409 `already_deactivated`/`no_such_notification`/`actor_no_longer_administrator`. Triggers Realtime invalidation.                                                                                                                                                                                                                                                                                                                                                     |
| DELETE | `/admin/api/notifications/<id>`             | Soft delete; same refusal set; triggers Realtime invalidation.                                                                                                                                                                                                                                                                                                                                                                                                        |

"Resend" is **not** a new endpoint — the composer prefills from a history row (fresh `client_request_id`, `resend_of` set to the source row's id) and calls `POST .../notifications` again. The composer's review step shows both languages, the display type, and the live `audience-preview` count before the actual send.

**`broadcast_limit` is keyed by administrator, not IP** — corrected from the prior draft, which inherited this app's Limiter default (`get_remote_address`). A custom `key_func` returning `g.identity.user_id` closes the "spam via multiple IPs" / "shared-NAT admins share a budget" gap adversarial review found:

```python
notification_broadcast_limit = limiter.shared_limit(
    lambda: config.get("server", "rate_limit", {}).get("notification_broadcast_api", "10 per hour"),
    scope="notification_broadcast",
    key_func=lambda: g.identity.user_id,
)
```

**Targeting scope note (unchanged):** `IdentityFlags` carries only `user_id`/`role`/`tier`/`is_disabled` — targeting is exactly `all`/`role`/`tier`/`user`, matching TODO.md's own spec.

---

## 4. Frontend

### Reader surface

- **`static/js/modules/services.js`** (transport only): `Services.notifications.{fetchActive, fetchHistory(cursor), markRead, markAllRead}`; Realtime channel lifecycle — `subscribeToNotifications(userId, onMessage)` / `unsubscribeFromNotifications()`, exponential backoff on disconnect, torn down on Page Visibility hidden or sign-out.
- **`static/js/modules/dom.js`**: new `BroadcastNotice` object, sibling to `ErrorHandler`, not built on the single-slot `#toast`. Three shells: `#broadcast-toast-stack` (corner, stacking, per-item countdown), `#broadcast-banner` (single-slot, `aria-live="polite"` — **never steals keyboard focus on arrival**, per adversarial review's accessibility suggestion; forced focus is reserved for the modal alone), `#broadcast-modal` (reuses the existing auth/profile modal's focus-trap/backdrop utility — Escape and backdrop-click _do_ close it, they just don't call `mark-read` with `acknowledged`; only the explicit **Acknowledge** button does). **Session-level snooze**: once dismissed via Escape/backdrop-click, that specific notification is suppressed client-side (`sessionStorage`) for the rest of the browser session, so the next poll/reconnect doesn't immediately reopen it — it stays unacknowledged server-side and resurfaces on the next real session.
- **`static/js/modules/ui.js`**: bell + badge, **inbox as a centered modal dialog on every viewport — never an offcanvas/drawer.** This is a direct fix for a real conflict adversarial review found: `DESIGN.md:349`'s One Drawer Rule explicitly bans a second offcanvas on mobile (the sidebar is already one), so the inbox reuses the existing modal utility instead, sidestepping the conflict rather than building a responsive drawer/modal split. New `BroadcastCoordinator` (not an extension of the existing transcript-scoped `NoticeCoordinator`) ensures at most one modal is shown at once.
- **`static/js/modules/handlers.js`**: fetch failures surface here via `ErrorHandler.showToast(...)`, per the test-enforced layering rule.
- **`web/templates/partials/_sidebar.html` / `index.html`**: bell + badge in `.sidebar-account`, duplicated desktop/mobile via the existing `{{ suffix }}` convention. The inbox modal markup and three broadcast shells live outside the sidebar macro (they're not part of it, avoiding any duplicate-render question).
- **`web/utils/icons.py`**: add `"bell"` to `ICONS` + `RUNTIME_ICON_NAMES`.
- **`web/api/app.py`**: bump `ASSET_VERSION` in the same commit as any CSS/JS touch.

### Admin surface

- **`static/js/admin/services.js`**: `audiencePreview`, `createNotification`, `notificationHistory`, `deactivateNotification`, `deleteNotification`.
- **`static/js/admin/ui.js`**: add `{tab:'tab-notifications', panel:'panel-notifications'}` to `TABS`; `renderNotificationHistory` mirrors `renderAudit`.
- **`static/js/admin/handlers.js`**: composer calls `audience-preview` on every targeting-field change; validates bilingual fields client-side _and_ relies on the server-side 400/422 as the real gate; deactivate/delete require confirmation; resend prefills the composer with a fresh idempotency key.
- **`web/templates/admin.html`**: new tab + panel, composer form, history table — ships **empty**. The four bilingual composer fields (`title_en/ar`, `body_en/ar`) and every rendered notification body carry `dir="auto"` for mixed-script safety.

### Design direction

This is a **regulatory dispatch**, not a generic app notification — the admin composer reads like drafting a dispatch (paired EN/AR folios, a compact operational strip for type/severity/audience/expiry, a review step showing the actual dispatch with live audience count before it goes out), never a blind "Send" on an irreversible action. The signature element: the admin history table renders timestamps in this app's existing mono face alongside semantic status labels (targeted/served/read/dismissed/acknowledged, per the vocabulary in §1) rather than color-only dots. Entirely inside DESIGN.md's existing Warm Instrument vocabulary — the inline-start pill mark, the same rule weights, the same tokens.

### Motion, and the Top-10 creative reference list

DESIGN.md ground rules applied: 200-300ms entrance/exit; slide via `inset-inline-start/end` only; stagger multi-element exit newest-first with a capped total delay; `prefers-reduced-motion` makes the countdown/slide discrete, not removed; severity maps to existing semantic tokens.

Ten concrete patterns synthesized from current design research — pick per type, don't build all ten:

1. **Spring-eased slide + settle** — toast overshoots slightly then eases back.
2. **Stacked depth-offset queue** — later toasts sit behind earlier ones at 4-8px offset, promoting forward as each dismisses.
3. **Progress-bar countdown edge** — thin bar on the block-end edge, drains over the auto-dismiss duration, pauses on hover/focus.
4. **Swipe-to-dismiss with rubber-band resistance** — inline-axis drag, RTL-aware direction.
5. **Banner height-collapse, not fade** — grows in by height, pushes content down rather than overlaying it.
6. **Backdrop blur-in for the modal** — background blurs/dims over ~200ms as the modal does a short scale-in; used sparingly given the narrow, ack-only scope.
7. **Icon micro-bounce on arrival** — the severity icon does a single small scale bounce independent of the container's slide.
8. **Unread-badge pulse, not a spinner** — one soft scale pulse on increment, never continuous ambient motion.
9. **Inbox item reveal on open** — history rows fade+rise with a short per-row stagger capped at ~6 rows.
10. **Read-state color settle** — the existing inline-start accent-pill mark fades to neutral over ~250ms as `mark-read` fires, rather than an instant re-render.

---

## 5. i18n

**Verified directly against `web/tests/test_admin_page.py:228-246`**: the pinned `runtime.*` top-level set is exactly `{chat, stage, robot, auth, profile, faq, theme, cite, lang, admin, sessions}` (11 names). `runtime.notifications.*` as a new top-level namespace would fail this test.

**Reader, under `runtime.chat.notifications.*`:**

```
bellAria, unreadBadge, inboxTitle, inboxEmpty, inboxUnavailable,
markAllRead, markAllReadFailed, markReadFailed, dismiss, acknowledge,
loadFailed, bannerDismiss
```

**Admin, under `runtime.admin.notifications.*`:**

```
heading, hint
composer.{typeLabel, severityLabel, titleEnLabel, titleArLabel, bodyEnLabel, bodyArLabel,
          targetLabel, targetAll, targetRole, targetTier, targetUser, userIdPlaceholder,
          expiresLabel, audiencePreviewLabel, send, sending, sent, sendFailed, idempotencyConflict}
history.{heading, empty, loadFailed, columnStatus, columnTargets, columnServed, columnRead,
         columnDismissed, columnAcknowledged, deactivate, deactivateConfirm, delete,
         deleteConfirm, resend, deactivated, deactivateFailed, deleted, deleteFailed}
```

Plus `page.admin.notifications` for the server-rendered tab label. Write English and Arabic together per key.

---

## 6. Security checklist

1. **XSS in admin-authored body.** `title_*`/`body_*` render via `textContent` only, plain text, no markdown/HTML interpretation in v1.
2. **Server-side targeting enforcement.** Every reader RPC takes `p_user_id`/`p_role`/`p_tier` from `g.identity`, never from query/body.
3. **`notifications_mark_read` verifies recipient eligibility and action/type validity** before writing (§1) — closes the "fabricate my own receipt" gap found in adversarial review.
4. **Two distinct rate-limit scopes**, both keyed correctly: `notification_broadcast_api` (admin send, keyed by admin id, not IP) is separate from the reader poll/history/mark scopes.
5. **Every admin RPC revalidates the actor is still an enabled administrator inside its own transaction** — closes a demotion-race gap the prior draft missed, matching existing `admin_update_profile`/`admin_set_user_flags` precedent.
6. **Audit logging.** Every create/deactivate/delete inserts an `audit_log` row in the same transaction as the mutation.
7. **Realtime channel scoping.** Per-user private channel, SELECT-only RLS policy on `realtime.messages`, no INSERT policy for `authenticated`.
8. **Realtime payload carries no content**, only `{notification_id, revision}` — nothing to leak if intercepted.
9. **CSP.** Already covers `wss://*.supabase.co` and the Supabase REST origin — nothing new to loosen.
10. **Delivery-channel isolation.** A Realtime publish failure is caught, logged, never fails the admin's response.
11. **Reconnect reconciliation**, on create, deactivate, and delete alike.
12. **Never trust a client-supplied `user_id`** on the mark-read path.
13. **Soft-delete integrity.** Delete never hard-deletes.
14. **Idempotency scoped to actor + payload hash**, not a bare global key — closes a "stale replay returns wrong success" gap.
15. **Recipient/read-receipt data anonymizes on account deletion** (real FK, `on delete set null`) — `notifications.target_user_id` deliberately does not, as an administrative-instruction fact, stated explicitly rather than left as a silent inconsistency.
16. **Alert fatigue / community-mistake mitigation.** Tight, correctly-keyed broadcast-send rate limit + audit trail + admin-only write access.

---

## 7. Rollout order

1. **Schema** — one concern per migration file: (a) `notifications`; (b) `notification_recipients` + `user_notification_reads` (surrogate keys, anonymize-on-delete FKs); (c) `admin_create_notification` (with actor revalidation, idempotency, target_count) + `admin_list_notification_history`; (d) `admin_deactivate_notification` + `admin_delete_notification` (both actor-revalidating, both Realtime-invalidating); (e) the four reader-facing RPCs (`notifications_mark_read` with eligibility+action checks); (f) the `realtime.messages` authorization policy. Apply via `apply_migration`, then `list_tables`/`list_migrations`/`get_advisors` (security + performance), log expected `rls_enabled_no_policy` findings, rename files to match `list_migrations`.
2. **Reader backend** — `notification_service.py`, routes + rate limits (cursor pagination for history), `ASSET_VERSION` bump.
3. **Admin backend** — `admin_store.py` extensions, routes in `admin.py`, admin-id-keyed `broadcast_limit`.
4. **Realtime plumbing**, built _after_ REST works end-to-end:
   - **4a. SDK upgrade — confirmed mandatory, do this first.** `@supabase/realtime-js@2.9.3` verifiably lacks a `private` channel option. Upgrade `@supabase/supabase-js` (and its `realtime-js` dependency) to a version that supports it, then run a full login/signup/recovery/reauthentication regression pass — not a spot check — because `services.js:15`'s documented `onAuthStateChange`/`_recoverAndRefresh` ordering is exactly the kind of behavior that has silently changed across versions before.
   - **4b.** Verify the exact private-broadcast REST request shape (single-topic vs. batch) before writing the publish code (§2).
   - **4c.** Publish server-side (create/deactivate/delete), subscribe client-side, with Page Visibility-driven teardown and session-generation stamping.
5. **Admin UI** — wired to an already-working backend, including the audience-preview call.
6. **Reader UI** — bell/badge, inbox-as-modal, three renderers, `BroadcastCoordinator`, session-level modal snooze.
7. **i18n** — interleaved with 5-6, English and Arabic together per key.
8. **Hardening + tests** (§8), plus manual Arabic/RTL, `prefers-reduced-motion`, and `get_advisors` passes.
9. **Documentation closure.** Move the TODO.md entry to `docs/archive/TODO-resolved.md`; re-check `docs/ARCHITECTURE.md`, `DESIGN.md`, `docs/PRODUCT.md` for anything this feature makes stale and fix in the same commit.

---

## 8. Test coverage plan

- **`test_frontend_architecture.py`** — re-verify services.js layering after adding Realtime subscribe code; add a sibling to the "handlers own user-facing failures" test for the notification-fetch failure path.
- **`test_css_contract.py`** — logical properties, no new test needed.
- **Dedicated mutation-gate tests, not the generic route test.** `test_admin_page.py`'s route-gating test skips every route without a GET method — the new POST/DELETE notification mutations need their own 401/403/actor-demotion coverage, added explicitly rather than assumed covered.
- **New `web/tests/test_admin_notifications.py`** (template: `test_admin_audit.py`) — payload validation, `AdminActionRefused` → 409 paths including `actor_no_longer_administrator`, idempotency replay (matching-hash success, mismatched-hash 409), audience-preview correctness, cursor-vs-offset pagination shape per surface.
- **New `web/tests/test_notifications_api.py`** (reader side) — 401 gating, targeting isolation, rate-limit trip, **mark-read scoped to actual recipient eligibility** (a reader who was never targeted cannot fabricate a receipt — the specific gap adversarial review found), action/type validity (dismiss vs. acknowledge).
- **Direct SQL/integration tests for the security boundary itself** (not just Flask-mocked): cross-user mark-read attempts, actor demotion mid-transaction, wrong action/type combinations, and confirming `authenticated` cannot execute the service-only RPCs at all — a Flask-level mock can't prove these properties.
- **New `web/tests/test_notifications_browser.py`** (Playwright, `-m browser`) — **scoped to the REST path only**, since `conftest.py`'s `SUPABASE_BROWSER_MOCK` has no channel/broadcast/private-auth simulation: composer submit → history row appears; bell badge increments; opening the inbox modal marks items read; modal is dismissible via Escape/backdrop-click but stays unacknowledged and snoozed for the session; banner uses `aria-live` without stealing focus; `?lang=ar` mirrors slide direction. **Private-channel authorization gets its own separate, non-browser-mock integration test** — a mock cannot prove reader A is denied reader B's topic.
- **Post-migration:** `get_advisors` (security + performance) after every apply.

---

## Verification

1. `python -m pytest -m "not browser and not integration"` stays green through each backend/schema step.
2. `python -m pytest web/tests/test_admin_notifications.py web/tests/test_notifications_api.py` pass in isolation.
3. `python -m pytest -m browser --browser chromium -k notification` for both `?lang=en` and `?lang=ar`.
4. `pre-commit run --all-files` (ruff/eslint/prettier/markdownlint) clean.
5. **`mypy web` run separately** — not covered by pre-commit per `CLAUDE.md`, listed here explicitly rather than assumed.
6. Manual: `FLASK_TESTING=true python web/api/app.py`, exercise all three notification types, the bell/inbox, and the admin composer in both languages.
7. `mcp__plugin_supabase_supabase__get_advisors` (security, performance) after every migration apply.
8. Bump `ASSET_VERSION`; confirm no CSP console warnings on all three templates, both languages, both themes.
9. **Full auth/recovery regression pass after the SDK upgrade** (§7 Step 4a) — login, signup, password recovery, reauthentication, sign-out-everywhere-else — before any Realtime code is trusted.
