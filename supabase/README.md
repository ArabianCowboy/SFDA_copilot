STATUS: CURRENT AUTHORITY — migration process and current schema shape.
Last verified against the live project 2026-08-28.

`profiles.last_seen_at` was dropped 2026-08-28
(`20260828222859_profiles_guard_stops_checking_last_seen_at.sql`,
`20260828222917_drop_profiles_last_seen_at.sql`) — closing the `TODO.md` entry that had
deferred it. `profile_last_seen`, below, is the only place "last active" lives now.

# Supabase schema

The database is part of this application, so its schema lives here in version control.
Until 2026-08-14 it did not: every table, policy and trigger had been applied straight to
the project, and the only record of the 2026-08-13 security audit was prose in `TODO.md`.

## What is here

```
supabase/
  migrations/     one .sql file per migration, named <version>_<name>.sql
  tests/          privilege, function-ACL and RLS assertions — see tests/README.md
  README.md       this file
```

There is no `seed.sql`. Nothing in the schema currently needs reference data — add one
when something does, rather than committing an empty file that implies otherwise.

`tests/` is new as of 2026-08-28 and exists because **the Python suite cannot fail because
of a grant.** Every Python test mocks the Supabase client, so the four grant-layer defects
that `docs/database-improvement-plan.md` opens with sat under a green CI run indefinitely,
and the advisors do not check grants at all. Those three files assert the privilege and
policy state directly. Run them before and after any migration that touches a grant, a
policy or a role — that is the cheap half of the plan's finding 7 and it does not wait on
the rest of it.

## How migrations are applied

Through the Supabase MCP `apply_migration` tool. There is no Supabase CLI in this project
and no automatic runner, so the file and the applied migration are kept in step by one
rule:

> **A migration's filename is exactly `<version>_<name>.sql`, where both halves are what
> `list_migrations` reports.**

`apply_migration` assigns the version (a UTC timestamp) when it runs, so the sequence is
the order things were _actually applied_ — which is not necessarily the order they were
written. That way `list_migrations` and `ls migrations/` can be read side by side and any
disagreement is a real one.

**This makes renaming a mandatory step of every migration, not a tidy-up.** The applied
name does not exist until after you apply, so the sequence is always: write it, apply it,
read the version back from `list_migrations`, rename the file. Skipping the fourth step is
not a small omission — six files had drifted before this was spelled out, and unpicking
them needed a commit of its own.

Migrations that predate this directory (everything up to `20260813101816`) were applied
directly and are recorded only in `supabase_migrations.schema_migrations`. They are listed
in `migrations/0000_baseline.md` for reference rather than reconstructed as SQL, because
re-deriving them would produce files that were never actually run.

## Rules

1. **One concern per migration**, and the name says which.
   _The one exception this project has actually met:_ a change no writer can be sequenced
   around. `20260822225415_profile_identity_atomic_cutover.sql` converts a column and
   rewrites `handle_new_user`, `admin_update_profile` and the grants in one file, because a
   generated column rejects all three existing writes — sequencing the conversion first
   breaks signup and both save paths for the length of the deployment. If you believe you
   are in that case, trace **every** writer of the column first, and say in the file header
   why it could not be split. Rule 2 still applies: a destructive step never joins it.
2. **Destructive changes go in their own migration.** A `drop` should never ride along with
   a fix that needs to be applied promptly and without hesitation — the two have different
   approval costs, and coupling them raises the cost of the urgent one to that of the
   dangerous one.
3. **Every function ships `set search_path = ''`** with fully-qualified names. A mutable
   `search_path` on a `SECURITY DEFINER` function is a privilege-escalation vector, and the
   security advisor flags it.
4. **Every foreign key gets its index in the same migration** that creates it, or the
   performance advisor flags it.
5. **RLS is enabled on every new table.** Where a table is deliberately service-role-only
   and therefore has zero policies, say so in a comment in the migration — the advisor
   reports `rls_enabled_no_policy` as INFO and the next reader must be able to tell intent
   from oversight.
6. **RLS cannot restrict columns.** A policy like `USING (auth.uid() = id)` lets the row's
   owner write _any_ column in that row, including one that grants them privileges. Column
   protection needs a column-level `REVOKE` plus a trigger. See
   `20260814005509_lock_profile_privileges_and_repair_signup.sql`, which exists because
   that was not understood the first time.
7. **Destructive changes state what they checked.** Dropping a table means recording the
   row count, the foreign keys in both directions, the triggers, and the grep that proved
   nothing reads it — in the migration, where the next reader will find it.
8. **A foreign key does not imply `ON DELETE CASCADE`, and every FK states its action.**
   The default is `NO ACTION`: the parent delete is _refused_ while children exist.
   `CASCADE` is opt-in and has to be typed. This is written down because
   `20260820131914_chat_session_persistence.sql:37-42` justifies leaving
   `chat_sessions.owner_id` **without** an FK on the grounds that "an FK brings ON DELETE
   CASCADE with it, and deleting one account would take a year of retained conversation
   with it" — **which is not true**, and the trade-off it describes is a false choice. A
   third option existed and was never considered: an FK with `NO ACTION` or `RESTRICT`,
   which keeps every conversation and makes an orphan impossible. The consequence today is
   real: `profiles.id → auth.users` does cascade, so deleting an account removes the
   profile and leaves that reader's `chat_sessions`, `chat_messages` and
   `chat_message_sources` behind with an `owner_id` resolving to nothing, permanently and
   with no detector. **The constraint is deliberately not added yet** — `ON DELETE
RESTRICT` would make account deletion fail with `23503` until something decides what
   happens to the conversations, and that decision is the account-deletion saga in
   `TODO.md`. The correction is recorded here because the sentence in that migration
   header is load-bearing and wrong, and correcting it does not wait on the saga.
   This schema demonstrates both defaults, deliberately: `profiles.id` says
   `on delete cascade` explicitly; `notifications.resend_of` and `app_settings.updated_by`
   say nothing and are `NO ACTION`; and `20260828001910` moved the two notification child
   FKs to `CASCADE` because a notification's receipts are meaningless without it — the
   opposite call from `chat_sessions`, and for the opposite reason (a notification is
   operator-owned; a conversation is reader-owned and outlives the account by design).

## The RPC contract

Every `security definer` function in this schema ships with all five of these. They are
one rule, not five, because any one of them missing re-opens the hole the others close:

1. `security definer`
2. `set search_path = ''`, with every name fully qualified (rule 3)
3. `revoke execute` from `anon`, `authenticated` and `public`
4. `grant execute` to `service_role` only
5. `p_owner_id` as the first argument, **filtered on inside the function**

Two functions are deliberately exempt from 3 and 4, and both are listed in the advisor
table above with the reasoning: `is_active_account()` (the RLS policies call it, and
Postgres evaluates a `USING` clause as the querying role) and
`update_own_preferences(jsonb)` (being reachable from the browser is the whole point).

A third is exempt from **4 alone, in the opposite direction**:
`admin_actor_email(uuid, text)` (`20260828001543`) is granted to **no role, service_role
included**. It is the gate the seven mutating `admin_*` RPCs call to refuse an absent or
demoted actor, and they execute as its owner, so it needs no grant. Granting it to
`service_role` would create a capability that does not otherwise exist — resolving any
administrator's email address from their uuid over `/rest/v1/rpc/`, on a database where
`service_role` reaches `auth.users` nowhere else. Point 3 is satisfied in full; point 4 is
narrowed rather than skipped, and `supabase/tests/function_acls.test.sql` asserts the
narrowing so it cannot quietly widen back.

> **Default privileges have two layers, and only one of them can close a function.**
> `20260828000737` revoked the defaults **in schema `public`**, so a new **table** is born
> inaccessible to `anon` and `authenticated` — and to `service_role`, which is the point of
> finding 14. New **sequences** lose `anon` and `authenticated` but deliberately keep
> `service_role`, matching the function split.
>
> That migration then observed that new **functions** were still `PUBLIC`-executable and
> wrongly concluded Postgres could not express the change. The cause was the layer: a
> per-schema default ACL is merged onto the hard-wired base and **cannot subtract** what the
> base supplies, and the hard-wired function default grants `EXECUTE` to `PUBLIC`. The
> **global** form — `alter default privileges for role postgres revoke execute on functions
from public`, with no `IN SCHEMA` — replaces that base instead, and does work.
> `20260828100816` applies it; a function created afterwards comes out
> `{postgres=X, service_role=X}`.
>
> Point 3 stays in the contract as belt to that braces, and
> `supabase/tests/privileges.test.sql` asserts the global default itself while
> `function_acls.test.sql` asserts the resulting per-function state. If you ever need to
> reach a default ACL again: **`IN SCHEMA` adds, global replaces.**

More:

- **Prefer `revoke all` over named-verb revokes.** A named revoke on `chat_archive` left
  `REFERENCES` and `TRIGGER` standing, which `20260820213833` had to clean up. Revoke
  everything, then grant back exactly what is needed.
- **No column grant for a feature that does not exist.** Do not `grant update (title)`
  before a rename control ships; an untested writable column is surface for nothing.
- **Changing a function's argument list is a `drop` plus a `create`, in one file and one
  transaction** — never `create or replace`. Overloads resolve by argument count, so the
  old signature stays callable beside the new one and PostgREST calls become ambiguous.
  Follow the shape of `20260821145416`.
- **Schema before code.** The migration lands first. A route calling a function that does
  not exist yet fails loudly; a function nothing calls yet is harmless.
- **PostgREST serves from a cached schema.** Confirm the reload happened after applying —
  from Flask's side a stale cache and a missing migration look identical.
- **No explicit `begin;`/`commit;` in a migration file.** `apply_migration` runs each file
  as a single transaction and owns it; one failing statement rolls back the whole file.
- **No `CASCADE` on a `drop column`.** An unrecorded dependent object should abort the
  migration, not be silently dropped with it.
- **Round-trip a risky migration in a deliberately aborted transaction first**, and re-run
  the advisors before it lands.

## Verifying the database matches this directory

After applying anything:

```
list_tables            → compare tables, columns and FKs against the migrations
list_migrations        → versions and names should match the filenames here, in order
get_advisors security
get_advisors performance
```

And, for anything touching a grant, a policy, a role or an `admin_*` function, paste each
of `supabase/tests/*.test.sql` into `execute_sql`. They answer the question the advisors
cannot: the advisors do not check grants, which is why the four grant-layer defects
`docs/database-improvement-plan.md` opens with were invisible to both the linter and CI.
Each file raises `PASS …` or `FAIL …`; see `supabase/tests/README.md`.

### Checking that a migration touched no rows

Grant, policy and function migrations are not supposed to move data, and that is worth
verifying rather than assuming. Take this before and compare after — it is
order-independent, so it catches an insert, update or delete without depending on physical
row order:

```sql
select 'profiles' as tbl, count(*) as n,
       md5(string_agg(x::text, '|' order by x::text)) as content_md5
  from public.profiles x
union all select 'chat_messages', count(*), md5(string_agg(x::text,'|' order by x::text))
  from public.chat_messages x
-- …one line per table…
;
```

Expect drift on exactly two: `audit_log` grows whenever an administrator does anything,
and `user_notification_reads` gains rows the moment a notification goes live. A changed
hash on any other table means the migration did something it was not meant to do.

### Reading the statistics nobody reads

`pg_stat_statements` is installed and consulted by nobody on a schedule. It has data.
Run these when something feels slow, and once in a while when it does not — without
something like this, a write-amplification problem is invisible until a reader complains:

```sql
select relname, n_live_tup, n_dead_tup, seq_scan, idx_scan,
       last_autovacuum, last_autoanalyze
  from pg_stat_user_tables where schemaname = 'public'
 order by n_dead_tup desc;

select calls, round(mean_exec_time::numeric, 2) as mean_ms, rows,
       left(regexp_replace(query, '\s+', ' ', 'g'), 120) as q
  from extensions.pg_stat_statements
 where dbid = (select oid from pg_database where datname = current_database())
 order by total_exec_time desc limit 20;
```

The first query is what surfaced `user_notification_reads` sitting at 0 live rows and 32
dead ones from testing alone — the signature of the unconditional `on conflict do update`
that `20260828001636` removed. Note that the dashboard and the MCP tools are themselves
load on this database, so the slowest query by total time is usually Supabase's own.

### Findings that are expected, and must stay explained

The advisors are only useful if a clean run means something, so every standing finding is
accounted for here. Anything not on this list is a regression from the migration you just
applied.

| Finding                                                                                        | Why it stands                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `rls_enabled_no_policy` on `public.app_settings`                                               | Intentional. Service-role only; a policy is how you would let the browser in.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `rls_enabled_no_policy` on `public.tiers`                                                      | Intentional. The operator-owned tier catalogue; every reader and writer is a `security definer` RPC and no role holds a grant, `service_role` included. Added 2026-09-03 with the reader quota.                                                                                                                                                                                                                                                                                                                                                                                      |
| `rls_enabled_no_policy` on `public.reader_quota_overrides`                                     | Intentional, same posture as `tiers`. Holds per-account allowance overrides and the operator's reason for them; a policy is how a reader would read another account's note. Added 2026-09-03.                                                                                                                                                                                                                                                                                                                                                                                        |
| `rls_enabled_no_policy` on `public.usage_daily`                                                | Intentional, same posture. Written only by `chat_claim_daily_message` / `chat_release_daily_message`. Added 2026-09-03.                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `rls_enabled_no_policy` on `public.audit_log`                                                  | Intentional. Written by the admin RPCs and read through them; a policy is how you would let the browser read it directly. Recorded here 2026-08-20 — it had been standing unlisted, which is the thing this table exists to prevent.                                                                                                                                                                                                                                                                                                                                                 |
| `rls_enabled_no_policy` on `public.chat_archive`                                               | Intentional, and rule 5 requires it be said here. The training archive is service-role **read-only** by design: no reader may select from it, and its only writer is `chat_append_turn` (`security definer`). A policy is how you would let a browser in, and nothing should be. `20260820213833` reduced `service_role` from `INSERT, REFERENCES, SELECT, TRIGGER` to `SELECT` — the named-verb revoke in the base migration had left `REFERENCES` and `TRIGGER` standing, which is precisely what that migration's own sibling-table comment warns `revoke all` exists to prevent. |
| `rls_enabled_no_policy` on `public.notifications`                                              | Intentional, added `20260823202130`. Operator-owned: written by the `admin_*` notification RPCs and read by readers only through `notifications_list_*_for_reader` (`security definer`). A policy is how you would let a browser read the composer's own table. Since `20260828000952`, `service_role` holds **no privilege on it at all** — even the direct read surface is gone.                                                                                                                                                                                                   |
| `rls_enabled_no_policy` on `public.notification_recipients`                                    | Intentional, added `20260823202146`. The recipient snapshot; the audience of a notification is not the reader's business. `service_role` retains `SELECT` because `recipients_for_publish` reads it to address the Realtime fan-out, and nothing else.                                                                                                                                                                                                                                                                                                                               |
| `rls_enabled_no_policy` on `public.profile_last_seen`                                          | Intentional, added `20260828135721`. Every access path is `touch_last_seen`/`admin_get_user`, both `security definer` running as the table owner; a policy is how you would let the browser or `service_role` in directly. `service_role` holds no grant on this table at all — see "What `service_role` may touch directly" below, which this table is deliberately absent from.                                                                                                                                                                                                    |
| `rls_enabled_no_policy` on `public.user_notification_reads`                                    | Intentional, added `20260823202146`. Receipts. Reached only through the reader RPCs, which write `served_at` on a list and the three action timestamps on `notifications_mark_read`. `service_role` holds nothing on it since `20260828000952`. **These three rows were added 2026-08-28**, having stood unlisted since the notification centre shipped on 2026-08-23 — the same drift the `audit_log` row above records, one feature later.                                                                                                                                         |
| `auth_leaked_password_protection`                                                              | A Pro-plan feature; the project is on a lower tier. Tracked in `TODO.md`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `authenticated_security_definer_function_executable` on `public.is_active_account()`           | Intentional, added `20260822225054`. It is `stable`/read-only, takes no arguments, and answers only for the caller's own row via `auth.uid()` — there is nothing for a caller to leverage against another account. `EXECUTE` cannot be revoked from `authenticated`: the RLS policies on `chat_sessions`, `chat_messages` and `chat_message_sources` call it from their `USING` clause, and Postgres evaluates that clause as the querying role — revoking would break every reader's own chat access, not just PostgREST's direct RPC exposure.                                     |
| `authenticated_security_definer_function_executable` on `public.update_own_preferences(jsonb)` | Intentional, added `20260822225239`. Being callable via `/rest/v1/rpc/update_own_preferences` is the point — it is the merge-write path for `profiles.preferences` (Decision 6). It writes only the caller's own row (`where id = (select auth.uid())`, never a passed-in id) and only through an in-function key allow-list, so `SECURITY DEFINER` grants it write access to a column the caller could already write via the ordinary column grant — it does not cross an ownership boundary.                                                                                       |

## Current shape of `public`

| table                  | rows                          | notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ---------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `profiles`             | one per account               | Identity **and** authorization. `role`, `tier`, `is_disabled` are writable only by the service role — see rule 6.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `app_settings`         | exactly one                   | Runtime overrides as JSONB. Absent keys fall back to `web/config.yaml`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `chat_sessions`        | one per conversation          | Created lazily by `chat_append_turn` on the first completed turn, so a reset cannot fill the table with empties. Readers `select`/`delete` their own via RLS; **no insert or update policy exists** and none should. `title` is set by `chat_append_turn` from the first turn's question (`coalesce(title, …)` — set when null, never overwritten, so a rename survives every later turn) and changed only by `chat_rename_session`, which deliberately **does not touch `updated_at`**: that column means "last spoken in", and a rename must not lift a months-old conversation to the top of the sidebar. See `20260821145319` and `20260821145416`. |
| `chat_messages`        | two per turn                  | The question and the answer, ordered by a per-session `seq` (never a timestamp — see `20260817161427` for what same-millisecond ordering cost the People list). Content is writable only by `chat_append_turn`.                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `chat_message_sources` | one per **retrieved** passage | Not one per cited passage: what search offered and the model declined is unrecoverable after a rebuild. `cited` flags which ones the answer used, and `source_index` is the `[n]` the model saw.                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `chat_archive`         | **0 — dormant**               | Append-only training record under HMAC'd owner/session keys, with **no FK** to anything — so a reader deleting their history does not delete training data, and vice versa. Skipped entirely when the salts are unset, which they are, so nothing has ever been written. Since `20260820213833`, `service_role` holds **`SELECT` and nothing else**: the only writer is `chat_append_turn` (`security definer`), and **there is no delete path at all**. See `web/config.yaml`'s `archive_disclosed` for the guard that stops the salts being set without restoring the reader-facing controls that were cut while it was empty.                        |
| `profile_last_seen`    | one per account ever touched  | Added `20260828135721`. Presence, not `profiles.last_seen_at` — kept off `profiles` deliberately so a background write never collides with `admin_update_profile`'s optimistic-concurrency use of `profiles.updated_at`. `on delete cascade` on `user_id → profiles(id)`. **No role holds any grant on it, `service_role` included** — every access path is `touch_last_seen(uuid)` (write, throttled to one row-write per account per hour) or `admin_get_user` (read), both `security definer`. See `docs/data-policy-decisions.md`'s §4.                                                                                                             |

`public.users` was dropped on 2026-08-14. It had never held a row: the signup trigger's
insert into it was added on 2025-12-07, three weeks after the most recent signup, so it
never once ran. `profiles` is the only identity table.

### What `service_role` may touch directly

Since `20260828000952`, the answer is "almost nothing, and only to read". Every write goes
through an RPC, which executes as `postgres` and is unaffected by these grants:

| table                                                                    | `service_role` holds | why                                                          |
| ------------------------------------------------------------------------ | -------------------- | ------------------------------------------------------------ |
| `audit_log`                                                              | `INSERT`, `SELECT`   | the only direct write to a `public` table anywhere in `web/` |
| `profiles`, `app_settings`, `notification_recipients`                    | `SELECT`             | read directly by the admin console and the broadcast fan-out |
| `chat_sessions`, `chat_messages`, `chat_message_sources`, `chat_archive` | `SELECT`             | since `20260820131914` / `20260820213833`                    |
| `notifications`, `user_notification_reads`                               | nothing              | reached only through the reader and admin RPCs               |

The reason is that a table-level `ALL` beside an RPC is a second write surface on which
every invariant that RPC enforces becomes optional — a notification with no recipient
snapshot and no audit row, a settings document overwritten with no record of who changed
it. No leaked key is required; an ordinary regression reaching for
`.table("notifications").insert(...)` gets there. `supabase/tests/privileges.test.sql`
asserts the whole table.

**Scope of "the only direct write":** it means PostgREST table access to a `public` table.
`web/services/auth_admin.py` also mutates state directly, through GoTrue's admin API
(`auth.admin.update_user_by_id`) — a different surface, governed by the service key rather
than by any grant in this schema, and untouched by these revokes.

---

## Before your next migration

Four of the eleven known rule collisions in this repository live in this file — the
one-concern rule versus the atomic cutover; the filename rule versus the fact that the
name only exists after applying; the default ACL that fails closed for tables and cannot
for functions; and the actor gate that made the last-administrator guard unreachable. All
four are written above. The other seven, and the register they are kept in, are in
[`docs/ARCHITECTURE.md` → _Rules that collide_](../docs/ARCHITECTURE.md#rules-that-collide).
Read it before you write the migration, not after it surprises you.
