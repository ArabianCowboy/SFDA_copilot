STATUS: LARGELY APPLIED — waves 1, 2, 3 and 5 landed on 2026-08-28 as twelve
migrations. Wave 4 remains open and its four items are now entries in `TODO.md`.
Audited against the live project `yjjuudnsnjzhyqllsqrd` on 2026-08-28.
**Read [What actually happened](#what-actually-happened-when-this-was-applied) first** —
three of the findings below turned out to be partly wrong at apply time, and that
section is where the corrections live.

# Supabase database improvement plan

A full read of the live database — every grant, policy, foreign key, trigger, index,
function ACL and table statistic — against `supabase/README.md`, the 43 applied
migrations, and the Flask code that calls them.

**The headline is not a bug.** The schema is in unusually good shape: 24 `security
definer` functions, every one of them carrying `set search_path = ''`, every one but two
documented exemptions revoked from `anon` and `authenticated`; RLS policies already
written in the optimised `(select auth.uid())` / `TO authenticated` form the Supabase
performance guide asks for; no unindexed foreign key; no duplicate permissive policy; an
append-only audit log defended by both a revoke and a trigger. The security advisor
returns nothing that `supabase/README.md` has not already argued for in writing.
[Checked and clean](#checked-and-clean) lists what was examined and passed.

The headline is that **all of that is discipline rather than structure**, and this
document's first finding is the one that converts it.

## How this plan was produced

Four passes, then a merge. This file is the merge; it is the only artifact, and the
intermediate reports have been folded into it rather than kept alongside it.

1. A direct read of the live database through the Supabase MCP tools, cross-checked
   against the current Supabase documentation on RLS performance and grant hygiene.
2. An Antigravity pass (`gemini-3.7-flash-high`) asked for the top ten mistakes projects
   of this shape make, with a YES/NO verdict and evidence for each against this database.
3. An OpenCode pass (`muse-spark-1.2`) asked for an independent improvement plan from the
   same introspection dump, deliberately not shown the first two.
4. An adversarial OpenCode pass (`gpt-5.6-terra`, high effort) asked to debate the merged
   plan and find only what it had **missed** — scoped to the current architecture and to
   changes reachable through the Supabase MCP tools. It produced findings 14–18 and three
   corrections, two of which caught fixes in this plan that would have broken working
   features.

Where the four disagreed, the disagreement was resolved against the database rather than
split. Seven of those adjudications changed this document and are recorded in
[Corrections](#corrections-made-during-the-merge) — including two where this plan's own
proposed fix was wrong.

---

## What actually happened when this was applied

Applied 2026-08-28 as twelve migrations, `20260828000737` through `20260828004228`.
Every migration was verified against the live database immediately after applying, and
the whole sequence was checked against a pre-migration row-count and content-hash
baseline: **every table's hash is byte-identical to what it was before the first
migration ran, `audit_log` included.** Nothing in this plan moved a row.

This section exists because three findings were partly wrong, and one thing nobody
predicted changed. Recorded here rather than edited into the findings above, per this
repository's own working style — the corrections are the part worth reading.

### Finding 1 did not work for functions at first, and the diagnosis was wrong

The migration applied cleanly and the verification failed.

`alter default privileges … revoke all on tables from anon, authenticated, service_role`
does exactly what the finding says: a table created afterwards is inaccessible to all
three. Sequences likewise. **Functions do not follow.** Postgres merges the built-in
default — which grants `EXECUTE` to `PUBLIC` — with whatever `ALTER DEFAULT PRIVILEGES`
stores, rather than letting the stored value replace it. Probed in a rolled-back
transaction:

```text
stored default ACL:  {postgres=X/postgres, service_role=X/postgres}
new function's ACL:  {=X/postgres, postgres=X/postgres, service_role=X/postgres}
                      ^^ PUBLIC, back again
```

`=X` is PUBLIC, and every role inherits PUBLIC's privileges, so
`has_function_privilege('anon', <new function>, 'EXECUTE')` is still true.

**The observation was right and the conclusion drawn from it was wrong**, and the wrong
conclusion was confident enough to be copied into four other documents before an
adversarial review pass caught it.

Postgres does not "merge the built-in default" in the way that migration claims. It
consults TWO `pg_default_acl` rows — a GLOBAL one (`defaclnamespace = 0`) and a
schema-specific one — and falls back to the hard-wired `acldefault()` as the base **only
when there is no global row**. A per-schema entry is then merged onto that base, and a
merge cannot subtract what the base supplies. So `IN SCHEMA public` was operating one layer
too low to reach PUBLIC's built-in grant.

The same statement **without `IN SCHEMA`** replaces the base instead. `20260828100816`
applies it, and a function created afterwards comes out
`{postgres=X/postgres, service_role=X/postgres}` — `anon` and `authenticated` both false.
No event trigger, no superuser, no gap. **Finding 1 is now fully closed for tables,
sequences and functions.**

The rule worth carrying forward, and the reason this is collision #10 in
`docs/ARCHITECTURE.md` rather than a closed `TODO.md` entry: **`IN SCHEMA` adds, global
replaces.** Table defaults grant nothing to PUBLIC, so the per-schema form works there and
hides the distinction; function defaults do, so only the global form closes them.

The wider lesson is about the probe rather than the SQL. The verification correctly showed
the symptom — PUBLIC still present — and the implementer inferred a cause from it without
testing the cause. A probe that confirms a symptom is not a probe that confirms a
diagnosis.

**A second, smaller half of finding 1 was also blocked.** The fix names both the
`postgres` and `supabase_admin` grantors and says revoking only one "leaves objects created
by `supabase_admin` wide open". `alter default privileges for role supabase_admin` fails
with `42501`: it requires membership in the grantor role, and
`pg_has_role('postgres','supabase_admin','MEMBER')` is false. The practical impact is
nil — a default ACL only applies to objects created _by_ that grantor, and all eleven
tables in `public` are owned by `postgres`, `chatbot_settings` included. Recorded because
"nil today" is not the same as "cannot happen".

### Finding 15 made finding AD002 unreachable, and nobody saw that coming

Requiring an enabled administrator on every mutating `admin_*` RPC has a consequence the
finding does not mention: **the last-administrator guard can no longer fire.** To pass the
actor gate you must be an enabled administrator; you cannot target yourself (`AD001`); so
if the target is _another_ enabled administrator there are at least two, and
`count(*) where role='admin' and not is_disabled <= 1` is never true. Verified against the
live project — an enabled admin demoting the other enabled admin succeeds and leaves one,
and that survivor is then refused `AD001` rather than `AD002`.

`AD002` was reachable before only through a null or phantom actor, which is precisely what
finding 15 removes. The guard stays as defence in depth behind the gate; it is not dead
code, it is a backstop if the gate is ever loosened. This is collision #11 in
`docs/ARCHITECTURE.md`, and `web/tests/test_admin_users.py` now documents it rather than
asserting a state the database cannot reach — the two tests that used to "prove" `AD002`
were passing on an actor id (`"someone-else"`) that matched no account.

### Finding 8's audit_log half was not applied

The question bound landed in full: `chat_append_turn` clamps `p_question` to 8,000
characters and `chat_messages_user_content_len_chk` is added and validated. The assistant
side is deliberately unbounded, as the finding argues.

The `audit_log` text bounds were **not** applied, because the finding does not specify
them — it says to "pick the bounds from what the writers actually produce" and names no
numbers. Inventing them here would have been worse than leaving them, and a bare `CHECK`
on `audit_log` is the wrong shape anyway: it would fire inside a `SECURITY DEFINER`
function and abort an administrative action, which is the exact failure mode the
`chat_messages` half was designed around. The right shape is a clamp in the seven admin
writers plus `admin_store.py`. Now a `TODO.md` entry, folded into the retention one.

### Finding 11 was not applied at all

The measurement it asks for has to be made by calling a probe **as `service_role` through
`/rest/v1/rpc/`**, which is the whole point of the finding — measuring through MCP is how
its premise got the wrong number twice. That call path is not available from an agent
session, and creating a probe function that nobody can then call would leave a stray
function in production for no gain. The procedure, the probe SQL and the caveat about
`service_role` being the operator's own connection are now in `docs/OPERATIONS.md`, with a
`TODO.md` entry pointing at them.

### One correction the plan did not contain, found by the tests it asked for

`supabase/tests/privileges.test.sql` failed on its first run against an assertion that
`authenticated` holds no `DELETE` on `chat_sessions`. It does — `chat_sessions_delete_own`
is a real, owner-scoped, `is_active_account()`-gated `DELETE` policy, and browser-direct
conversation deletion is a deliberate feature. The test was wrong, not the schema. It now
asserts the grant is **present** _and_ that the policy behind it exists and is scoped,
because the grant without the policy would let any signed-in reader delete any
conversation. This is a small thing and it is the argument for the whole of finding 7: the
first run of a real assertion found something four review passes had read past.

### What was applied, in order

| Migration                                                                      | Finding | Verified by                                                                                                                 |
| ------------------------------------------------------------------------------ | ------- | --------------------------------------------------------------------------------------------------------------------------- |
| `20260828000737_default_privileges_fail_closed_in_public`                      | 1       | Probe table + function in a rolled-back transaction; see the correction above                                               |
| `20260828000952_service_role_loses_direct_writes_on_five_tables`               | 14      | Ten `has_table_privilege` assertions                                                                                        |
| `20260828001035_profiles_table_grant_hygiene`                                  | 2       | Twelve assertions, incl. that the eleven column grants survived the table revoke                                            |
| `20260828001058_chatbot_settings_revoke_browser_grants`                        | 3       | Privilege assertions                                                                                                        |
| `20260828001543_admin_rpcs_require_an_enabled_actor`                           | 15      | Null, unknown and non-admin actors refused `AD004`/`AN005`; forged email discarded                                          |
| `20260828001636_served_at_is_written_once_not_on_every_poll`                   | 4       | `n_tup_upd` stays 0 across repeated list calls; read/dismiss/ack still land                                                 |
| `20260828001731_receipt_writes_respect_the_notification_lifecycle`             | 16      | Live ack allowed; deactivated ack and expired dismiss refused `RN003`; plain read still allowed                             |
| `20260828001841_notification_replay_is_serialised_and_covers_resend_of`        | 17      | Identical retry replays; same hash with a different `resend_of` conflicts `AN001`                                           |
| `20260828001910_notification_child_rows_cascade_on_delete`                     | 9       | `confdeltype` is `c` on both child FKs, `n` on both `user_id` FKs                                                           |
| `20260828002052_chat_append_turn_guards_source_elements_not_just_the_array`    | 18      | A payload of nulls, scalars, bad indices, duplicates and a 900-char snippet keeps the turn and two clean citation rows      |
| `20260828002253_bound_the_stored_question_length`                              | 8       | 12,000-char question stored at 8,000; 30,000-char answer stored whole; direct over-long and empty user rows refused `23514` |
| `20260828004228_revoke_execute_on_the_two_functions_the_default_acl_left_open` | 1       | Both triggers still fire; zero functions anon-executable beyond the two exemptions                                          |

Not migrations, shipped in the same change: the four in-memory test doubles and five test
fixtures finding 15 requires; `put_settings`'s missing `try`/`except` and the three admin
routes above it; `RN003` in `_REFUSAL_CODES` and the client handling that stops a withdrawn
notice looping on an error toast; keyset pagination on **both** unbounded fan-out fetches
(finding 10); `supabase/tests/` (finding 7); and the register rows, rule 8 and the
statistics procedure in `supabase/README.md` (finding 12).

### What was not applied, and why

| Finding                                            | Status                                                                                                                                                                                                                                                                                                                  |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 3 (drop)                                           | Only the `revoke` half. Dropping `chatbot_settings` is the product decision `TODO.md` already owns.                                                                                                                                                                                                                     |
| 5                                                  | Blocked on, and sequenced behind, account deletion. The migration header's `CASCADE` error is corrected now, as rule 8 of `supabase/README.md`.                                                                                                                                                                         |
| 6                                                  | Blocked on what "disabled" means. Now a `TODO.md` entry.                                                                                                                                                                                                                                                                |
| 8 (retention, `audit_log` bounds, assistant bound) | Blocked on numbers and a retention period nobody owns. Now a `TODO.md` entry.                                                                                                                                                                                                                                           |
| 1 (`supabase_admin` grantor)                       | Blocked: `ALTER DEFAULT PRIVILEGES` needs membership in the grantor role and `postgres` is not a member of `supabase_admin` (`42501`). It governs nothing in `public` today — all eleven tables and every function there are `postgres`-owned — so the practical impact is nil, but "nil today" is not "cannot happen". |
| 11                                                 | Needs a measurement through PostgREST. Procedure in `docs/OPERATIONS.md`.                                                                                                                                                                                                                                               |
| 13                                                 | Blocked on write-it-or-drop-it. Now a `TODO.md` entry.                                                                                                                                                                                                                                                                  |

### A second review pass, and what it changed

`docs/database-improvement-plan.md` was reviewed adversarially again **after** it was
applied (`openai/gpt-5.6-sol`, read-only, 2026-08-28), specifically to find where the
implementer's own verification had been too kind to itself. It was right about four things
and wrong about one, and both halves are recorded because the ratio is the point.

**Right, and fixed:**

- **The function default-ACL diagnosis was wrong** — the correction above, and the single
  highest-value finding of the whole exercise. It turned a "blocked, needs superuser"
  `TODO.md` entry into a one-statement migration.
- **The fan-out fix did not deliver the memory bound it claimed.** Pagination bounded the
  number of HTTP requests; `recipients_for_publish` still accumulated the entire audience
  into one list before `_broadcast` chunked it, while the code comment asserted the
  opposite. Now a generator consumed with `islice`, so peak memory really is one chunk.
- **The pagination loop could still truncate silently.** It ended the walk on a page
  shorter than the requested size — but PostgREST's `db-max-rows` caps responses
  server-side, so with a cap below the page size _every_ page is short and the walk would
  have stopped after the first, reinstating the exact silent partial-delivery failure
  finding 10 exists to remove. It now walks until a page is genuinely empty, and
  `test_notification_fanout_pagination.py` drives a stub with an independent server cap.
- **A soft-deleted notification could still accrue `read_at`.** Finding 16 gated only
  `dismissed` and `acknowledged`, on the reasoning that a history list may legitimately be
  read late. True for deactivated and expired; false for deleted, because the history RPC
  filters `deleted_at is null` — so a `read` there is unreachable through any reader
  surface and still counts in the purge audit row. `20260828101339` refuses every action on
  a deleted notification.

Plus several documentation claims that the code did not support: a sequences line that
contradicted the migration it described, an "only direct write in all of `web/`" that
ignored `auth_admin.py`'s GoTrue calls, a `lock_timeout` sentence that contradicted itself
two lines earlier, and a stale collision count in `CLAUDE.md`.

**Wrong, and worth recording because it was stated as PROVEN:** that
`REVOKE ALL ON TABLE` does not remove independently granted column privileges, and that
`20260828001035`'s justification was therefore false. Tested directly — grant
`update (a)` alone, then `revoke all on table … from authenticated` — and
`has_column_privilege(…, 'a', 'UPDATE')` comes back **false**. The table revoke does take
column grants with it, the migration's caution was correct, and a blanket `revoke all` on
`profiles` would have broken the account page, signup and the preferences merge exactly as
its header says.

**Wave 0 is still not complete.** The content-hash baseline exists and proved its point —
no migration here touched a row — but it is not a backup, and a restorable copy still has
to come from the dashboard or a `pg_dump`. Everything applied above is a grant, a policy,
a constraint or a function body, which is why proceeding was defensible; anything that
touches data should wait for a real backup. `docs/OPERATIONS.md` now says so, and it is a
`TODO.md` entry.

---

## Findings, most costly first

Each row names the general mistake it is an instance of, so a finding that is closed stays
closed by recognising the class rather than the line.

Ordered by cost. The numbers are stable identifiers, not positions — findings 14–18 came
from the fourth pass and are placed here by severity.

| #         | Finding                                                                  | Mistake class                            | Severity | Advisors? |
| --------- | ------------------------------------------------------------------------ | ---------------------------------------- | -------- | --------- |
| [1](#1)   | `public`'s default privileges grant ALL to `anon` on every future table  | Trusting RLS instead of grants           | High     | No        |
| [14](#14) | `service_role` can write around the RPCs on five tables                  | Two standards for the same invariant     | High     | No        |
| [2](#2)   | `profiles` carries `DELETE` and `TRUNCATE` for `anon`/`authenticated`    | `TRUNCATE` is not covered by RLS         | High     | No        |
| [15](#15) | A NULL `p_actor_id` skips every admin check; audit email is unverified   | Authorization guarded only when present  | Medium   | No        |
| [3](#3)   | `chatbot_settings` is fully writable by `anon` at the grant layer        | Dead table keeping live privileges       | Medium   | No        |
| [4](#4)   | Two notification list RPCs write a dead tuple on every read              | Unconditional `ON CONFLICT DO UPDATE`    | Medium   | No        |
| [16](#16) | Reader receipt writes ignore the notification lifecycle                  | Mutations that skip the read filter      | Medium   | No        |
| [5](#5)   | `chat_sessions.owner_id` has no FK, for a reason that is factually wrong | Assuming an FK implies `CASCADE`         | Medium   | No        |
| [6](#6)   | `profiles` policies do not gate on `is_active_account()`                 | Deactivation that skips the direct table | Medium   | No        |
| [7](#7)   | No database-level test proves any grant or policy holds                  | Mock-only test suites                    | Medium   | No        |
| [8](#8)   | Unbounded text columns, and no retention anywhere                        | Append-only with no lifecycle            | Medium   | No        |
| [17](#17) | Notification replay races, and its payload hash omits `resend_of`        | A unique index mistaken for idempotency  | Medium   | No        |
| [9](#9)   | Two notification FKs make purge ordering load-bearing                    | Delete order held in one function body   | Low      | No        |
| [10](#10) | The `all`-target broadcast fetches every enabled profile id              | Unbounded fan-out query                  | Low      | No        |
| [18](#18) | `chat_append_turn` validates the sources array but not its elements      | Shape check that stops one level short   | Low      | No        |
| [11](#11) | Liveness bounds on the write path are unverified, not absent             | Measuring the wrong connection path      | Low      | No        |
| [12](#12) | Three standing advisor findings are missing from the register            | Register drift                           | Low      | Partly    |
| [13](#13) | `profiles.last_seen_at` is written by nothing                            | Ghost column                             | Low      | No        |

Not one of these is on the advisor output. That is the point of reading the database
rather than the linter.

---

<a id="1"></a>

## 1. `public`'s default privileges grant ALL to `anon` on every future table

**Severity: High.** This is the finding that makes findings 2 and 3 inevitable rather
than accidental.

### What is wrong

```sql
select pg_get_userbyid(defaclrole) as grantor,
       defaclnamespace::regnamespace as schema,
       defaclobjtype, defaclacl::text
  from pg_default_acl;
```

returns, for schema `public`, from **both** the `postgres` and `supabase_admin` grantors:

```text
objtype r (tables)    → {postgres=arwdDxt/…, anon=arwdDxt/…, authenticated=arwdDxt/…, service_role=arwdDxt/…}
objtype f (functions) → {postgres=X/…,       anon=X/…,       authenticated=X/…,       service_role=X/…}
objtype S (sequences) → {postgres=rwU/…,     anon=rwU/…,     authenticated=rwU/…,     service_role=rwU/…}
```

`arwdDxt` is every table privilege there is: `INSERT`, `SELECT`, `UPDATE`, `DELETE`,
`TRUNCATE`, `REFERENCES`, `TRIGGER`.

So **every table a migration creates in `public` is born fully writable by `anon`, and
every function a migration creates is born executable by `anon`**, until that migration
explicitly revokes it. `supabase/README.md`'s five-part RPC contract — points 3 and 4,
`revoke execute` then `grant execute to service_role` — exists precisely to undo this,
by hand, on every function, forever.

### Why it bites

A contract enforced by remembering is a contract that fails on the migration written at
the end of a long session. Two objects in this database already prove the failure mode:

```sql
select proname, proacl::text from pg_proc
 where pronamespace = 'public'::regnamespace
   and proacl::text like '%anon=X%';
```

```text
audit_log_is_append_only  | {=X/postgres, postgres=X/postgres, anon=X/postgres, authenticated=X/postgres, service_role=X/postgres}
handle_profile_update     | {=X/postgres, postgres=X/postgres, anon=X/postgres, authenticated=X/postgres, service_role=X/postgres}
```

Both are trigger functions, so neither is reachable through PostgREST (it does not expose
functions returning `trigger`, and Postgres refuses a direct call outright). The exposure
is nil. **The discipline gap is not.** These two were missed by exactly the mechanism that
would miss a consequential one, and nothing in CI would have said so. The next
`security definer` function whose `revoke` line is forgotten is browser-callable at
`/rest/v1/rpc/<name>` on the day it is applied.

### The fix

One migration, no behaviour change, flipping the default from open to closed:

```sql
-- Both grantors. A default ACL is per (role, schema, object type); revoking only
-- the `postgres` one leaves objects created by `supabase_admin` wide open.
alter default privileges for role postgres in schema public
  revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all on functions from anon, authenticated, public;
alter default privileges for role postgres in schema public
  revoke all on sequences from anon, authenticated;

alter default privileges for role supabase_admin in schema public
  revoke all on tables from anon, authenticated;
alter default privileges for role supabase_admin in schema public
  revoke all on functions from anon, authenticated, public;
alter default privileges for role supabase_admin in schema public
  revoke all on sequences from anon, authenticated;
```

All six statements are one concern — the default ACL — and must land together. Splitting
by object type leaves sequences wide open while tables are closed.

**`service_role` is split by object type, and the split is the point.** The obvious move is
to leave `service_role` alone entirely, on the grounds that every RPC is granted to it. That
reasoning is sound for _functions_ and wrong for _tables_ — and leaving both alone would
make finding 14 a one-time cleanup that drifts back on the very next migration.

- **Functions: leave the default.** Every RPC in this schema is granted to `service_role`,
  so revoking the default would mean adding a `grant execute` line to every future
  migration — trading one act of remembering for another.
- **Tables: revoke the default.** Finding 14 shows `service_role` holding `ALL` — `TRUNCATE`
  included — on five tables whose invariants are supposed to live in their RPCs. The
  migrations that thought about this already write the grant explicitly:
  `20260820131914_chat_session_persistence.sql:245-251` does `revoke all … from
service_role` then `grant select`, and its line 219 names the reason — _"Supabase grants
  `service_role` broad DML by default, so any …"_. The migrations that did not think about
  it — `20260823202130_notifications_table.sql`,
  `20260823202146_notification_recipients_and_reads.sql`,
  `20260814022601_app_settings.sql` — contain **no `service_role` line at all** and simply
  inherited `ALL`.

So the explicit-grant discipline already exists; it is just not enforced. Revoking the
default table privilege makes the tables that forgot impossible rather than merely unlucky,
and costs nothing new on the ones that already do it right.

Accordingly the table revoke above includes `service_role`, and the function revoke does
not:

```sql
alter default privileges for role postgres in schema public
  revoke all on tables from anon, authenticated, service_role;      -- note service_role
alter default privileges for role supabase_admin in schema public
  revoke all on tables from anon, authenticated, service_role;
-- functions and sequences: service_role is NOT revoked, per the split above.
```

The cost is one `grant` line per future table that `service_role` genuinely needs to read.
That is the same line `20260820131914` already writes, and the absence of it is what
finding 14 is cleaning up.

This inverts the RPC contract's cost. Points 3 and 4 stop being _"remember to close the
door"_ and become _"remember to open it, and only for `is_active_account()`-style
exemptions"_ — a rule that fails safe, because the failure mode is a 404 in testing rather
than an open endpoint in production.

### Proving it worked

```sql
-- In a transaction that ends in ROLLBACK:
create table public._acl_probe (id int);
create function public._acl_probe_fn() returns int language sql as $$ select 1 $$;
select has_table_privilege('anon', 'public._acl_probe', 'SELECT'),         -- expect f
       has_table_privilege('authenticated', 'public._acl_probe', 'INSERT'),-- expect f
       has_function_privilege('anon', 'public._acl_probe_fn()', 'EXECUTE');-- expect f
rollback;
```

Then re-run both advisors: nothing should change, because no existing object is touched.

**This lands first.** Findings 2 and 3 are cleanups of objects created before the default
was closed; doing them first just means doing them again for the next table.

---

<a id="2"></a>

## 2. `profiles` carries `DELETE` and `TRUNCATE` for `anon` and `authenticated`

**Severity: High** on the identity and authorization table.

### What is wrong

```sql
select has_table_privilege('anon','public.profiles','DELETE'),    -- t
       has_table_privilege('anon','public.profiles','TRUNCATE'),  -- t
       has_table_privilege('anon','public.profiles','REFERENCES'),-- t
       has_table_privilege('anon','public.profiles','SELECT');    -- t
```

All true, and all true for `authenticated` as well.
`20260814005509_lock_profile_privileges_and_repair_signup.sql` revoked `INSERT` and
`UPDATE` and re-granted them per column — 11 reader-writable columns, with `role`, `tier`
and `is_disabled` excluded. That part is correct and narrow. The **table-level**
privileges left over from the default ACL were never revoked.

### Why it bites

Three separate ways, in descending order of how much they should worry anyone:

**`TRUNCATE` is not subject to row-level security.** RLS applies to `SELECT`, `INSERT`,
`UPDATE`, `DELETE` and `MERGE`. It does not apply to `TRUNCATE`. Every other dangerous
privilege in this schema is stopped by a policy; this one is stopped by nothing at all.
PostgREST cannot emit a `TRUNCATE`, so there is no route to it today — but "no route
today" is the entire defense, on the table that decides who is an admin.

**`DELETE` is stopped only by the absence of a policy.** `pg_policies` shows three
policies on `profiles`: SELECT, UPDATE, INSERT. There is no DELETE policy, so
`DELETE /rest/v1/profiles` affects zero rows. That is correct behaviour arrived at by
omission. Add a DELETE policy one day for some unrelated reason and the grant is already
there waiting.

**`SELECT` for `anon` puts `profiles` in PostgREST's schema for unauthenticated callers.**
PostgREST exposes a table when any role holds any privilege on it. The rows are protected
(the SELECT policy is `TO authenticated`), but the _shape_ is not: an unauthenticated
`GET /rest/v1/` discloses that this application stores `role`, `tier`, `is_disabled`,
`disabled_reason`, and six `marketing_consent_*` columns. Minor, and worth one line of a
migration to remove.

### The fix

```sql
-- Table-level only. The column grants from 20260814005509 are correct and must survive,
-- so this cannot be a blanket `revoke all` — that would take the column grants with it.
revoke delete, truncate, references, trigger on public.profiles from anon, authenticated;
revoke select on public.profiles from anon;
```

`SELECT` stays for `authenticated`: the browser reads its own profile row directly, and
that is Decision 6 in `docs/ARCHITECTURE.md`, not an oversight.

### Proving it worked

```sql
select has_table_privilege('authenticated','public.profiles','DELETE')   as must_be_false,
       has_table_privilege('authenticated','public.profiles','TRUNCATE') as must_be_false_2,
       has_table_privilege('anon','public.profiles','SELECT')            as must_be_false_3,
       has_table_privilege('authenticated','public.profiles','SELECT')   as must_be_true,
       has_column_privilege('authenticated','public.profiles','first_name','UPDATE') as must_be_true_2,
       has_column_privilege('authenticated','public.profiles','role','UPDATE')       as must_be_false_4;
```

Then the real gate: the signup flow, the account page save, and the preferences merge RPC
must all still work. The account and signup browser suites are what prove the column
grants survived — a grant assertion cannot, because it is the interaction between the
table revoke and the column grant that is at risk.

---

<a id="3"></a>

## 3. `chatbot_settings` is fully writable by `anon` at the grant layer

**Severity: Medium** — because the table is empty and unread, not because the grant is
mild.

### What is wrong

```sql
select has_table_privilege('anon','public.chatbot_settings','INSERT'),   -- t
       has_table_privilege('anon','public.chatbot_settings','UPDATE'),   -- t
       has_table_privilege('anon','public.chatbot_settings','DELETE'),   -- t
       has_table_privilege('anon','public.chatbot_settings','TRUNCATE'); -- t
```

Every privilege, for `anon` and `authenticated` both. RLS is enabled with zero policies,
which blocks the four DML verbs and leaves `TRUNCATE` unguarded — on a table with zero
rows, so truncating it is a no-op.

### Why it bites

It does not, today. It is in this list because it is **the receipt for finding 1**: a
table created through the dashboard before the migration discipline existed, carrying the
default ACL untouched two years later. It is what every future table looks like until
finding 1 lands.

`TODO.md` already has an open question about this table (_"Worth deciding whether it is
dropped or finally used"_, in the tier-quota entry), and `supabase/README.md` lists its
`rls_enabled_no_policy` finding as _"Unused table from an abandoned design, left untouched
rather than dropped by an unrelated migration."_

### The fix

Two options, and the choice is the product decision `TODO.md` already owns:

- **Drop it.** Its own migration, per rule 2, recording the row count (0), the foreign
  keys in both directions (none), the triggers (none), and the grep that proves nothing
  reads it. This is the honest option — the tier-quota entry has already decided that a
  global `rate_limit_per_minute` scalar belongs on a tier, not on the instance.
- **Or `revoke all on public.chatbot_settings from anon, authenticated;`** and leave it,
  if the decision is still genuinely open. This also removes it from PostgREST's exposed
  schema entirely.

Do not do both in one migration, and do not attach either to finding 1's migration — rule
2 keeps a `drop` away from a fix that wants to be applied without hesitation.

---

<a id="4"></a>

## 4. Two notification list RPCs write a dead tuple on every read

**Severity: Medium**, and currently **dormant** — it activates on the first live
notification.

### What is wrong

`notifications_list_active_for_reader(p_user_id)` — called on every reader page load —
opens with a write:

```sql
insert into public.user_notification_reads (notification_id, user_id, served_at)
select n.id, p_user_id, now() from public.notifications n where …
on conflict (notification_id, user_id) do update
  set served_at = coalesce(public.user_notification_reads.served_at, excluded.served_at);
```

The `coalesce` correctly preserves the first `served_at`. But `DO UPDATE` fires
**regardless**, and Postgres does not skip an `UPDATE` whose new values equal the old
ones — only a `WHERE` predicate on the conflict clause can. Every poll after the first
therefore writes a new row version and leaves a dead tuple behind, for a column whose
value did not change.

**It is two sites, not one** — and knowing exactly which two is the whole of the fix.
`supabase/migrations/20260823202428_reader_notification_rpcs.sql` has four
`on conflict … do update` clauses, at lines 63, 143, 234 and 280. The first two are the
list RPCs (`notifications_list_active_for_reader` and
`notifications_list_history_for_reader`) and they set nothing but `served_at`. **Those are
the two to fix.**

The other two — inside `notifications_mark_read` and `notifications_mark_all_read` — look
identical and are not. They also set `read_at`, `dismissed_at` and `acknowledged_at`:

```sql
on conflict (notification_id, user_id) do update
  set served_at      = coalesce(public.user_notification_reads.served_at, excluded.served_at),
      read_at        = coalesce(public.user_notification_reads.read_at, case when p_action = 'read' …),
      dismissed_at   = coalesce(…),
      acknowledged_at = coalesce(…)
```

**Do not apply the fix below to those two.** By the time a reader clicks anything, the
list RPC has already inserted their row with `served_at` set — so a
`where served_at is null` predicate there would make the update a permanent no-op and the
bell would stop recording reads, dismissals and acknowledgements entirely. They are also
not the problem: they fire on a user action, not on every page load, so their write
amplification is one row per actual click. **Leave them alone.**

### Why it bites

`pg_stat_user_tables` already shows the signature, from testing alone:

```text
user_notification_reads | n_live_tup 0 | n_dead_tup 32 | seq_scan 1709
```

Zero live rows, thirty-two dead ones. Scale that: one active `all`-targeted banner, `R`
readers, `P` page loads each per day is `R × P` dead tuples per day on the smallest, most
frequently touched table in the schema — and each one is also a WAL record and index
maintenance. Autovacuum will keep up at the current size and will visibly not keep up at
the size this table is designed for. The symptom, when it arrives, will look like "the
notification bell got slow" and will be traced to bloat rather than to this line.

### The fix

One predicate, applied at the two **list** sites only (lines 63 and 143):

```sql
on conflict (notification_id, user_id) do update
  set served_at = excluded.served_at
  where public.user_notification_reads.served_at is null;
```

The `where` makes the conflicting-row update conditional; when `served_at` is already
set, Postgres skips the row and writes nothing. The `coalesce` becomes unnecessary — the
`where` already guarantees the old value was null. Semantics are identical: first serve
wins, later serves are no-ops.

Per `supabase/README.md`, these are `create or replace` (no argument list changes), so
they are one file and one concern: the served-at write.

### Proving it worked

```sql
-- In a transaction that ends in ROLLBACK, with one active notification and one reader:
select n_tup_upd from pg_stat_xact_user_tables where relname = 'user_notification_reads';
select count(*) from public.notifications_list_active_for_reader('<uuid>');
select count(*) from public.notifications_list_active_for_reader('<uuid>');  -- second call
select n_tup_upd from pg_stat_xact_user_tables where relname = 'user_notification_reads';
-- Before the fix: n_tup_upd grows by 1 per call. After: it stops growing after the first.
rollback;
```

Repeat for `notifications_list_history_for_reader`, or the fix is half-applied — and then
prove the other half was _not_ touched: mark a served notification read, dismiss it, and
acknowledge a modal, and confirm all three timestamps still land. A green bloat number
with a broken bell is a worse outcome than the bloat.

Note also what the predicate does and does not buy. A false conflict `WHERE` writes no
tuple, but Postgres still takes a row lock while evaluating it. This is a bloat and WAL
fix, not a claim that the poll becomes lock-free.

---

<a id="5"></a>

## 5. `chat_sessions.owner_id` has no FK, for a reason that is factually wrong

**Severity: Medium.** The decision may still be right; the sentence that justifies it is
not, and it is load-bearing.

### What is wrong

`20260820131914_chat_session_persistence.sql:37-42` reads:

```sql
-- Denormalised, no FK to auth.users — the same call audit_log.actor_id makes,
-- for the same reason plus one more: an FK brings ON DELETE CASCADE with it,
-- and deleting one account would take a year of retained conversation with it.
owner_id     uuid not null,
```

**An FK does not bring `ON DELETE CASCADE` with it.** A `REFERENCES` clause with no
`ON DELETE` action defaults to `NO ACTION` — the delete of the parent row is _refused_
while children exist. `CASCADE` is opt-in and has to be typed. This database's own
schema demonstrates both: `profiles.id` says `on delete cascade` explicitly, while
`notifications.resend_of` and `app_settings.updated_by` have no action clause and are
`NO ACTION`.

So the stated trade-off — _"an FK, or a year of retained conversation"_ — is a false
choice. A third option was available and was not considered: an FK with `NO ACTION` or
`RESTRICT`, which keeps every conversation and makes an orphan impossible.

### Why it bites

`profiles.id → auth.users(id)` cascades. So deleting an account today succeeds, removes
the profile, and leaves `chat_sessions`, `chat_messages` and `chat_message_sources`
behind with an `owner_id` that resolves to nothing — forever, with no detector and no
purge path. For an app that records which regulatory guidance named professionals asked
about, in a jurisdiction with data-protection law, "the erasure request completed and the
transcripts are still there" is the failure mode.

Note what this is _not_: it is not a live leak. Those rows are unreachable through RLS
(no `auth.uid()` will ever match a deleted user's id) and unreachable through the RPCs
(every one filters `p_owner_id`). They are invisible and permanent, which is precisely
the shape of a retention problem rather than an access problem.

### The fix

```sql
-- 1. Prove there are no orphans, and abort the migration if there are.
do $$
begin
  if exists (
    select 1 from public.chat_sessions s
     where not exists (select 1 from auth.users u where u.id = s.owner_id)
  ) then
    raise exception 'orphaned chat_sessions exist; resolve before adding the constraint';
  end if;
end $$;

-- 2. RESTRICT, not CASCADE, not SET NULL. Conversations are retained; the delete is
--    refused until something has explicitly decided what happens to them.
alter table public.chat_sessions
  add constraint chat_sessions_owner_fk
    foreign key (owner_id) references auth.users(id) on delete restrict;
```

No new index is required: `chat_sessions_owner_updated_idx (owner_id, updated_at desc,
id desc)` leads with `owner_id` and satisfies rule 4. Say so in the migration, or the
next reader will add a redundant one.

### The caveat that makes this a decision, not a cleanup

`ON DELETE RESTRICT` **changes an existing operator capability.** Today, deleting a user
from the Supabase dashboard or through GoTrue's admin API succeeds. After this migration
it fails with `23503` until that user's conversations are dealt with. That is the point —
it converts a silent orphaning into a loud refusal — but it is a behaviour change to a
path that is used, and it is exactly the forcing function the account-deletion saga in
`TODO.md` (_Account deletion, Spec 4_) is supposed to provide.

**Therefore: sequence this with that saga, not ahead of it.** Landing the constraint
before there is any path to delete a user's conversations makes account deletion
impossible rather than explicit. The right order is the saga's conversation-deletion step
first, this constraint second, as its guarantee.

---

<a id="6"></a>

## 6. `profiles` policies do not gate on `is_active_account()`

**Severity: Medium.** An inconsistency in what "disabled" means, on the table that stores
the flag.

### What is wrong

Every chat policy gates on activity:

```text
chat_sessions_select_own  | (owner_id = (select auth.uid())) AND (select is_active_account())
chat_messages_select_own  | (owner_id = (select auth.uid())) AND (select is_active_account())
chat_message_sources_select_own | (select is_active_account()) AND EXISTS (…)
```

None of the three `profiles` policies do:

```text
Users can view own profile   | (select auth.uid()) = id
Users can update own profile | (select auth.uid()) = id
Users can insert own profile | with_check: (select auth.uid()) = id
```

### Why it bites

Flask refuses a disabled account at `web/api/app.py:747` (`if identity.is_disabled:`), so
no Flask route is affected. But `profiles` is the one browser-direct table: a disabled
account holding an unexpired JWT can `GET` and `PATCH` its own row against PostgREST
without Flask in the path at all. A GoTrue access token stays cryptographically valid
until its `exp` regardless of what the operator did to the account.

The privilege columns are safe — `profiles_guard_privilege_columns` raises `42501` for
`authenticated` on any attempt at `role`, `tier`, `is_disabled` or the consent
timestamps — so this is not privilege escalation. It is a disabled user still able to
change their name, organization, specialization, age and marketing consent until their
token expires.

Whether that matters is a product question. "Disabled" might reasonably mean "cannot use
the product" rather than "is frozen". But it should be a decision, and right now it is an
asymmetry nobody chose.

### The fix

If the answer is that disabled means frozen, change `UPDATE` only:

```sql
alter policy "Users can update own profile" on public.profiles
  using (((select auth.uid()) = id) and (select public.is_active_account()));
```

**Leave `SELECT` alone.** The app must be able to read `is_disabled` to render the
disabled state; a reader who cannot select their own profile cannot be shown why they are
locked out. **Leave `INSERT` alone** too: `handle_new_user` creates the row, and the
policy is the browser's fallback path at signup, at which point no profile row exists for
`is_active_account()` to consult.

There is no recursion risk in calling `is_active_account()` from a policy on `profiles`:
it is `security definer` and owned by `postgres`, which holds `BYPASSRLS`, so its internal
read of `profiles` is not subject to the policy that calls it. Wrapping it in `(select …)`
keeps it an InitPlan and out of the per-row path, so it adds no `auth_rls_initplan`
advisor finding.

### Open question this depends on

Does "disabled" freeze the account's own profile edits, or only its use of the product?
`docs/PRODUCT.md` does not say. This finding is blocked on that answer, not on
engineering.

---

<a id="7"></a>

## 7. No database-level test proves any grant or policy holds

**Severity: Medium**, and the reason findings 1–3 could sit undetected.

### What is wrong

Every Python test mocks the Supabase client. `pgtap` is available in this project's
extension list and is **not installed**. There is no Supabase CLI in the repo and no local
stack, so there is nowhere a `supabase test db` would run today.

The consequence is precise: **the test suite cannot fail because of a grant.** Findings 1,
2 and 3 are all grant-layer facts, and a green CI run says nothing about any of them. The
same is true of every RLS policy — the notification-center work already recognised this
and verified its Realtime boundary directly against the live project with a
session-variable simulation of two readers, _because a mock cannot prove that property_.
That instinct was right and was applied once, by hand, to one policy.

The historical evidence that this matters is in this repo:
`20260814005509_lock_profile_privileges_and_repair_signup.sql` exists because a signup
trigger broke user creation, and a mock-only suite passed throughout.

### The fix

A `supabase/tests/` directory of pgTAP files, and a way to run them. In rough priority:

1. **`privileges.test.sql`** — a table of `has_table_privilege` / `has_column_privilege`
   assertions covering every table × (`anon`, `authenticated`) pair, asserted in both
   directions. This is the test that fails when finding 1's default ACL leaks a new table.
2. **`function_acls.test.sql`** — every function in `public` is executable by
   `service_role` and _not_ by `anon`/`authenticated`, with exactly two named exemptions.
   This test is the RPC contract, written down as an assertion instead of a paragraph.
3. **`rls_chat.test.sql`** — `set local role authenticated` plus a JWT claim, and prove
   reader A cannot see reader B's session, message or source; and that no insert or update
   path exists on any chat table.

Sketch of the shape, using the pgTAP form the Supabase docs give for exactly this:

```sql
begin;
select plan(4);
select ok(not has_table_privilege('anon','public.profiles','DELETE'),
          'anon holds no delete grant on profiles');
select ok(not has_table_privilege('anon','public.profiles','TRUNCATE'),
          'anon holds no truncate grant on profiles');
select ok(not has_table_privilege('authenticated','public.chat_messages','INSERT'),
          'no browser-direct write path to chat_messages');
select ok(has_function_privilege('service_role','public.chat_append_turn(…)','EXECUTE'),
          'the only writer is still granted');
select * from finish();
rollback;
```

The mechanics are the real cost, not the assertions. Two honest options:

- **Install `pgtap` on the live project and run the tests through `execute_sql` inside a
  transaction that ends in `rollback`.** No new tooling, matches how this project already
  works, and runs against the database that actually matters. Not wired into CI, so it is
  a pre-migration checklist step rather than a gate.
- **Adopt the Supabase CLI and a local stack**, which gets `supabase test db` in CI —
  but that is a genuinely large change to a project whose stated position is that it has
  no CLI, and it should be its own decision, not a rider on this plan.

Recommendation: start with the first. Three test files that can be pasted into
`execute_sql` before any migration is applied are worth more than a CI integration that
does not exist yet, and they are the input to the second option if it is ever taken.

**Write the privilege test against the post-finding-2 state**, so it encodes the intended
grants rather than the current accident.

**The advisors are the second line, not the first.** A cheap complement to the pgTAP
suite: fail the check if `get_advisors` returns any finding not listed in
`supabase/README.md`'s standing-findings table. That is finding 12 turned into a gate.

---

<a id="8"></a>

## 8. Unbounded text columns, and no retention anywhere

**Severity: Medium**, rising with time rather than with load.

### What is wrong

There is no `pg_cron`, no scheduled job, no partition, and no retention policy on any
table. Four grow forever:

| Table                     | Grows with                    | Today | Bound |
| ------------------------- | ----------------------------- | ----- | ----- |
| `audit_log`               | every administrative action   | 115   | none  |
| `chat_messages`           | two rows per turn, forever    | 50    | none  |
| `chat_message_sources`    | ~4 rows per assistant message | 200   | none  |
| `user_notification_reads` | one row per reader × notice   | 0     | none  |

`chat_archive` is dormant (salts unset) but is designed to be append-only with **no delete
path at all** — deliberately, and documented. When the salts are set it starts growing at
roughly one `question` + `answer` + `sources jsonb` per turn, and there is by design no
way to stop it.

Separately, at the column level: `chat_messages.content` has no length `CHECK`
(`chat_sessions.title` has one, `chat_message_sources.snippet` has one), and `audit_log`'s
`action`, `target_id`, `user_agent`, `note` and `actor_email` are all plain `text`.

### Why it bites

Not for a long time — 14 MB total, and Postgres does not care about a million-row
`audit_log`. It bites as a **compliance** problem before it bites as a performance one: an
app that records what regulators' guidance was asked about, keyed to named professionals,
with an audit log of administrative action, in a jurisdiction with data-protection law,
and no answer to "how long do you keep it".

### The fix, in two independent halves

**A bound can land now for the question, and only for the question.** Flask caps a
question at `MAX_CHAT_QUERY_CHARS = 8_000` (`web/api/app.py:235`, enforced at line 2415),
so that number is not a guess — but Flask is not the enforcement boundary, and a direct
`service_role` write ignores it.

**There is no equivalent bound on the answer, and inventing one would corrupt history.**
`grep` finds no answer-length check anywhere in `web/api/app.py`; the only reference is
`"chars": len(answer)` at line 3231, which is a log field. A model answer routinely
exceeds 8,000 characters when the question that produced it cannot. Clamping `p_answer` to
the question's limit would silently store a truncated version of an answer the reader has
already been streamed in full — durable history quietly disagreeing with what was on
screen, which is the worst failure available in a citation product. So the constraint is
role-scoped:

```sql
alter table public.chat_messages
  add constraint chat_messages_user_content_len_chk
  check (role <> 'user' or char_length(content) between 1 and 8000) not valid;
```

An assistant-message bound needs its own product limit and a matching pre-persistence
policy — the model's `max_tokens` times a safe character ratio is where that number comes
from, not `MAX_CHAT_QUERY_CHARS`. Until that number exists, assistant rows stay unbounded
and that is the correct trade.

The subtlety is where the failure surfaces.
`20260820131914_chat_session_persistence.sql:44-47` already states the rule for `title`:
_"Clamped in Flask before the RPC is called, never here: a length constraint enforced
inside a SECURITY DEFINER function surfaces a client mistake as a 500."_ A bare `CHECK` on
`chat_messages.content` would violate that rule — it fires inside `chat_append_turn`,
which is `security definer`, and aborts the whole turn including an answer the reader is
already reading.

So pair the constraint with a clamp, on the question only:

```sql
-- Belt: clamp inside chat_append_turn, body only, no signature change.
--   p_question := left(p_question, 8000);
-- Applied before the INSERT, so an over-long question is truncated rather than rejected.
-- p_answer is NOT clamped — see above.

-- Braces: `not valid` skips the scan of existing rows and still enforces on new ones.
-- `validate constraint` afterwards, out of band, once existing rows are confirmed to pass
-- (`select max(char_length(content)) from public.chat_messages where role = 'user'`).
```

Adding a `NOT VALID` check and validating separately is cheap at 50 rows and expensive at
five million, which is an argument for doing it now rather than later.

Pick the `audit_log` bounds from what the writers actually produce, not from round
numbers, and note that `user_agent` is attacker-controlled and therefore the one that most
wants a cap.

**The retention job does not land now.** Do not build a purge before someone owns the
retention period — a job that deletes before a legal hold is defined is worse than no job.
The correct predecessor is a documented policy, recorded in `TODO.md` alongside the
account-deletion question it overlaps with. When it exists, `user_notification_reads` is
the table where a rolling delete is uncontroversial; `audit_log` is the one where it is
not.

---

<a id="9"></a>

## 9. Two notification FKs make purge ordering load-bearing

**Severity: Low**, and it is a latent trap rather than a live defect.

`notification_recipients.notification_id → notifications(id)` and
`user_notification_reads.notification_id → notifications(id)` both have no `ON DELETE`
action, so both are `NO ACTION`. `admin_purge_notification` deletes the children first, in
the same transaction, and is correct. But that ordering is now an invariant held only
inside one function body: any future `DELETE FROM notifications` — a manual cleanup, a
retention job, a second purge path — gets `23503` instead of doing the right thing.

The sibling case was already fixed once:
`20260825001815_admin_purge_notification_severs_resend_of_references.sql` exists because
`notifications.resend_of` had exactly this problem. These two were not included.

```sql
alter table public.notification_recipients
  drop constraint notification_recipients_notification_id_fkey,
  add  constraint notification_recipients_notification_id_fkey
    foreign key (notification_id) references public.notifications(id) on delete cascade;

alter table public.user_notification_reads
  drop constraint user_notification_reads_notification_id_fkey,
  add  constraint user_notification_reads_notification_id_fkey
    foreign key (notification_id) references public.notifications(id) on delete cascade;
```

Leave both `user_id → auth.users(id) on delete set null` exactly as they are: that is
deliberate reader anonymisation, and the migration says so.

Note the interaction with finding 5: `CASCADE` is correct _here_ and wrong _there_. The
difference is who owns the row. A notification is operator-owned and its receipts are
meaningless without it; a conversation is reader-owned and outlives the account by
design.

---

<a id="10"></a>

## 10. The `all`-target broadcast fetches every enabled profile id

**Severity: Low** today, and it is the one finding that gets worse with user count rather
than with traffic.

Sending a `target_kind = 'all'` notification resolves its Realtime fan-out through
`web/services/notification_store.py:416`:

```python
def all_enabled_profile_ids(self) -> list:
    response = self._client.table("profiles").select("id").eq("is_disabled", False).execute()
```

No limit, no pagination, no cursor. Every enabled account id crosses PostgREST into Python
memory in one response, and `web/services/notification_service.py:95` then chunks it at
`_CHUNK_SIZE = 500` for the broadcast itself — so the chunking is on the _send_ side only,
after the unbounded fetch has already happened.

There is also no partial index for the predicate; `profiles` is scanned sequentially. At
four rows that is correct and optimal. At a hundred thousand enabled accounts it is a
hundred-thousand-row fetch on a single operator action, and the row cap that saves it is
whatever PostgREST's `db-max-rows` happens to be — which, if it is set, would silently
truncate the audience rather than error. Truncating an audience quietly is the worse
failure of the two.

**There are two of these, not one.** `recipients_for_publish`
(`web/services/notification_service.py:132-143`) branches on `target_kind`, and _both_
branches are unbounded:

```python
# notification_store.py:417  — the 'all' branch
self._client.table("profiles").select("id").eq("is_disabled", False).execute()

# notification_store.py:406-414 — the role / tier / user branch
self._client.table("notification_recipients").select("user_id")
    .eq("notification_id", notification_id).execute()
```

A pre-flight check caught the second one; this finding originally named only the first. A
fix applied to `all_enabled_profile_ids` alone leaves every role- and tier-targeted send on
exactly the same unbounded path, which is the more common send in practice.

The fix for both is a keyset cursor on `id` / `user_id`, streamed into the same
`_CHUNK_SIZE` batches, so the memory bound is the chunk rather than the audience. It is not
urgent, and it should be done before the first broadcast to a large audience rather than
after.

For contrast, and so nobody paginates them by reflex: the audience-preview counts
(`notification_store.py:209, 218, 228, 238`) are already bounded with `.limit(1)` and
`count="exact"`, and the history listings (`:363, :380`) take pagination parameters. Those
are fine.

---

<a id="11"></a>

## 11. Liveness bounds on the write path are unverified, not absent

**Severity: Low.** This finding survived the adversarial pass with its premise demoted:
what looked like a missing timeout is a timeout nobody has measured on the path that
actually carries the writes.

### What is wrong

```sql
select rolname, rolconfig from pg_roles where rolname in ('anon','authenticated','authenticator','service_role');
```

```text
anon          | {statement_timeout=3s}
authenticated | {statement_timeout=8s}
authenticator | {statement_timeout=8s, lock_timeout=8s}
service_role  | (null)
```

And cluster-wide:

```text
statement_timeout                   | 120000 | configuration file
lock_timeout                        | 0      | default
idle_in_transaction_session_timeout | 0      | default
```

**Do not read the 120000 as `service_role`'s effective timeout.** That value was observed
from an MCP session, which is not how Flask reaches the database. Flask calls PostgREST,
which logs in as `authenticator` — a role that _does_ carry `statement_timeout=8s` and
`lock_timeout=8s` — and then switches role per request.

Postgres does not apply `ALTER ROLE … SET` on `SET ROLE`; role GUCs are applied at login.
PostgREST works around that deliberately, reading the rolconfig of every role the
authenticator may become and applying it per request. This database's own
`pg_stat_statements` shows it happening, 134 times:

```text
with role_setting as (select r.rolname, unnest(r.rolconfig) as setting
                        from pg_auth_members m join pg_roles r on r.oid = m.roleid
                       where member = quote_ident(cu…
```

So role settings _do_ reach the PostgREST path — but because `service_role` has no
rolconfig of its own, there is nothing for PostgREST to apply, and a service-role request
most likely runs under whatever `authenticator`'s login left in effect: **8s, not two
minutes.** That is a guess from the mechanism, not a measurement.

What is certain from `pg_settings`: no role and no cluster default sets a `lock_timeout`
or an `idle_in_transaction_session_timeout`.

### Why it bites

`chat_append_turn` takes `select … for update` on the session row and holds it until the
transaction commits — which, called as an RPC, means until the function returns. Correct
and deliberate: the comments explain that the lock is the serialisation point that makes
the replay probe and the title write safe.

A session that stalls while holding that lock has no `lock_timeout` bounding the waiters.
Every subsequent turn in that conversation blocks behind it until the statement timeout —
whatever it really is — fires.

An `idle_in_transaction_session_timeout` would **not** help here, and this plan previously
implied it would. That setting kills a transaction that is _idle_. A PL/pgSQL function
still executing inside `chat_append_turn` is not idle, so the idle bound never sees it. It
is worth setting as a general backstop against a client that dies mid-transaction; it is
not a fix for this lock.

The application is single-worker (`gunicorn --workers 1 --threads 8`,
`docs/ARCHITECTURE.md:104`), which narrows all of this considerably. It is a gap in the
layer below the app, not an active incident.

### The fix — measure first, and measure through PostgREST

The measurement is the deliverable; the `ALTER ROLE` is a footnote to it. Add a temporary
`security definer` reporter, call it as `service_role` through `/rest/v1/rpc/`, read what
comes back, and drop it:

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

Only then decide the numbers:

```sql
alter role service_role set lock_timeout = '8s';   -- mirror authenticator
-- statement_timeout: set above the observed max_exec_time of chat_append_turn, with room.
```

**Caveat worth stating plainly:** `service_role` is also what the Supabase MCP tools and
any administrative script connect as. Tightening its `statement_timeout` will abort a long
maintenance query. That is usually the right trade, but it changes the operator's own
environment as well as the app's, so it warrants a note in `docs/OPERATIONS.md` rather
than a silent `alter role`.

---

<a id="12"></a>

## 12. Three standing advisor findings are missing from the register

**Severity: Low**, and it is a documentation rule this repo wrote for itself.

`supabase/README.md` rule 5 requires every table with RLS enabled and no policies to say
so in its migration _and_ be accounted for in the standing-findings table, so that a clean
advisor run means something. The table currently lists four: `app_settings`,
`chatbot_settings`, `audit_log`, `chat_archive`.

The advisor returns **seven**. The three notification tables — `notifications`,
`notification_recipients`, `user_notification_reads` — were added on 2026-08-23 with the
correct `comment on table` text in their migrations, and never got their rows in the
register.

The fix is three rows in that table. It is on this list only because the README says, of
`audit_log`, that it "had been standing unlisted, which is the thing this table exists to
prevent" — the same drift, one feature later.

---

<a id="13"></a>

## 13. `profiles.last_seen_at` is written by nothing

**Severity: Low.** A column that promises a feature that was never built.

`grep -rn "last_seen_at" web/` returns one production reference:
`web/services/admin_store.py:728`, which reads it into the admin account-detail payload.
`static/js/admin/ui.js` renders it. Nothing anywhere writes it. It is guarded as
server-owned by `profiles_guard_privilege_columns` — a trigger defending a column that
never changes — and the admin console shows an empty field for every account.

The cost is a contract lie: an operator learns to ignore the field, and when a real
"last seen" is wanted later, a column full of NULLs will be misread as "nobody ever used
the product".

Two honest resolutions: drop it (and its guard clause, its store field and its admin
view), or write it. **If it is written, do it carefully**, for two reasons:

- `handle_profile_update` sets `updated_at = now()` on _every_ update to `profiles`, and
  `admin_update_profile` uses `p_expected_updated_at` for optimistic concurrency against
  that same column. A background `last_seen_at` write would bump `updated_at` and make an
  administrator's in-flight edit fail with a spurious conflict.
- A per-request write to `profiles` is finding 4's problem on a bigger table. If it is
  written at all, throttle it —
  `where last_seen_at is null or last_seen_at < now() - interval '1 hour'` — and put it on
  a once-per-page-load path such as `/api/identity`, never on `/api/chat/stream`.

The cleaner design, if the feature is genuinely wanted, is to keep last-seen off
`profiles` entirely rather than add a per-request write to the one table every request
already reads.

---

<a id="14"></a>

## 14. `service_role` can write around the RPCs on five tables

**Severity: High**, and it is the finding this plan's own framing hid.

### What is wrong

Finding 1 leaves `service_role`'s default privileges alone, on the reasoning that every
RPC is granted to it anyway. That reasoning covers _functions_. It quietly extends the
same permission to _tables_ — and the repository does not actually believe that, because
it has already done the tighter thing twice:

```text
chat_sessions / chat_messages / chat_message_sources → service_role: SELECT
chat_archive                                         → service_role: SELECT
audit_log                                            → service_role: INSERT, SELECT
profiles                                             → service_role: ALL
app_settings                                         → service_role: ALL
notifications                                        → service_role: ALL
notification_recipients                              → service_role: ALL
user_notification_reads                              → service_role: ALL
```

`20260820131914_chat_session_persistence.sql` revokes every direct service-role privilege
on the chat tables; `20260814032139_audit_log.sql` reduces it to `INSERT, SELECT` so that
even the service role cannot rewrite history. The notification migrations and
`20260814022601_app_settings.sql` revoke from `anon, authenticated` only, and left
`service_role` holding the default `ALL` — including `TRUNCATE`.

So on five tables there is a second write surface sitting beside the RPC that is supposed
to be the only one. RLS does not close it: `service_role` carries `rolbypassrls`.

### Why it bites

Every invariant those RPCs enforce is optional on that surface. A direct write can create
a notification with no recipient snapshot and no audit row; overwrite the singleton
`app_settings` document without the audit row `admin_write_settings` would have written;
alter or delete a reader's acknowledgement receipts; or change `role`, `tier` and
`is_disabled` on `profiles` without the diff-based audit entry
`admin_set_user_flags` produces. None of that requires a leaked key — an ordinary
server-side regression that reaches for `.table("notifications").insert(...)` instead of
the RPC gets there, and nothing refuses it.

This is defense in depth, not a live vulnerability: anyone holding the service key can
already do a great deal. The point is that the schema currently has two standards for the
same class of invariant, and the weaker one is the accident.

### Why the fix is safe here

Because the direct service-role usage is read-only, and that is checkable. Every direct
table call from the service-role client is a `.select(...)`:

```text
web/services/admin_store.py:245        profiles                 .select(_IDENTITY_COLUMNS)
web/services/admin_store.py:282        app_settings             .select("settings")
web/services/notification_store.py:209/218/228/238  profiles    .select("id", count="exact")
web/services/notification_store.py:408 notification_recipients  .select("user_id")
web/services/notification_store.py:417 profiles                 .select("id")
```

The one direct write in either module is `admin_store.py:402`,
`table("audit_log").insert(...)` — which is exactly why `audit_log` keeps its `INSERT`
grant. Everything else goes through an RPC.

### The fix

```sql
revoke all on public.profiles                from service_role;
grant select on public.profiles              to   service_role;

revoke all on public.app_settings            from service_role;
grant select on public.app_settings          to   service_role;

revoke all on public.notification_recipients from service_role;
grant select on public.notification_recipients to service_role;

revoke all on public.notifications           from service_role;
revoke all on public.user_notification_reads from service_role;
```

`security definer` functions are unaffected: they execute as their owner, `postgres`, not
as `service_role`. Leave `audit_log` exactly as it is.

This is a **different migration from finding 1**. Finding 1 changes what future objects
inherit; this changes the ACL of existing ones. They are one concern only if you squint,
and rule 1 says do not squint.

### Proving it worked

```sql
select has_table_privilege('service_role','public.notifications','INSERT')  as must_be_false,
       has_table_privilege('service_role','public.profiles','UPDATE')       as must_be_false_2,
       has_table_privilege('service_role','public.profiles','SELECT')       as must_be_true,
       has_table_privilege('service_role','public.audit_log','INSERT')      as must_be_true_2;
```

Then exercise, in order: the admin console's settings read and write, an account detail
view, the audience preview counts, a notification send, and a reader's bell. Each of those
is a distinct one of the reads above, and a `42501` from any of them means one more
`grant select` is owed.

---

<a id="15"></a>

## 15. A NULL `p_actor_id` skips every admin check; the audit email is unverified

**Severity: Medium.** Not privilege escalation — an audit-integrity finding.

### What is wrong

Every mutating `admin_*` RPC takes `p_actor_id` and `p_actor_email` as parameters, and
guards on the first **only when it is present**:

```sql
if p_actor_id is not null then
  select (pr.role = 'admin' and pr.is_disabled = false)
    into v_actor_ok from public.profiles pr where pr.id = p_actor_id;
  if coalesce(v_actor_ok, false) = false then
    raise exception … ;
  end if;
end if;
```

Confirmed across all ten `admin_*` functions: none contains a `p_actor_id is null` guard,
and **all seven mutating ones** write `p_actor_email` into `audit_log` verbatim:

```text
admin_write_settings          admin_create_notification       admin_purge_notification
admin_set_user_flags          admin_deactivate_notification
admin_update_profile          admin_delete_notification
```

(The other three — `admin_get_user`, `admin_list_users`,
`admin_list_notification_history` — are readers and write no audit row.)

**Seven, not six.** An earlier draft of this finding said six, against its own evidence.
The one that goes missing when you miscount is `admin_purge_notification`, which is the
permanent-erasure path and therefore the single row where a false actor matters most. Name
all seven in the migration.

So:

- **`p_actor_id => null` performs the mutation with no authorization check at all**, and
  writes an audit row with a null actor.
- **`p_actor_email` is never checked against `p_actor_id`.** A call may pass one
  administrator's id — passing the role check — and any string at all as the email, and
  the audit log records the string.

### Why it bites

Anyone with the service key can already do anything, so this is not a privilege boundary.
It is the _audit log's_ boundary: `audit_log` is defended by a revoke and an append-only
trigger precisely so that it can be trusted later. Those defenses protect the rows from
being rewritten. They do nothing about a row that was false when it was written.

The practical failure is a future call site — a script, a migration helper, a new admin
route — that omits the actor because the parameter is optional and the function does not
complain. That produces a privileged mutation attributed to nobody, in the table whose job
is attribution.

Flask does pass its verified identity at every current call site
(`admin_store.py:301-311`, `366-380`, `445-456`; `notification_store.py:283-304`). The
database simply does not require it.

### The fix

In each of the seven mutating functions, make the actor mandatory and derive the email
rather than accepting it. Keep each family's existing SQLSTATE so the Flask error mapping
still matches — `AD004` for the account functions, `AN005` for the notification ones:

```sql
-- declare v_actor_email text;

if p_actor_id is null then
  raise exception 'an enabled administrator is required' using errcode = 'AD004';
end if;

select u.email::text into v_actor_email
  from public.profiles p
  join auth.users u on u.id = p.id
 where p.id = p_actor_id and p.role = 'admin' and p.is_disabled = false;

if v_actor_email is null then
  raise exception 'the acting account is no longer an enabled administrator'
    using errcode = 'AD004';
end if;

-- then write v_actor_email, never p_actor_email, into audit_log.
```

`p_actor_email` stays in the signature — removing it is a drop-and-create of six
functions and buys nothing — but stops being trusted. Note the honest limit: SQL cannot
establish _which human_ held the service key. It can refuse an unattributed mutation and
guarantee the recorded email belongs to the id that passed the check, and that is the
whole of what this fix claims.

`admin_write_settings` needs the guard added rather than tightened: it performs no actor
check today.

### And `admin_write_settings` has no error path on the Flask side either

This is the part that turns a hardening change into a 500. `AD004` is in `_REFUSAL_CODES`
(`web/services/admin_store.py:51-60`) and `_refusal_from` converts it — but only where it
is called, at lines 383 and 460. `put_settings` (`:287-313`) calls
`.rpc("admin_write_settings", …).execute()` with **no `try`/`except` at all**:

```python
response = self._client.rpc(
    "admin_write_settings", { … "p_actor_id": actor.user_id, … },
).execute()
return getattr(response, "data", None) or {}
```

So the moment this finding gives `admin_write_settings` something to raise, a
demoted-or-disabled administrator saving settings gets an unconverted PostgREST exception
on the generic error path instead of the intended refusal.

**And it has three callers, none of which catch either:**

```text
web/services/settings_service.py:582   set_signup_enabled
web/services/settings_service.py:657   update
web/services/notification_store.py:804 set_purge_retention_days
```

with the routes above them — `web/api/admin.py:247`, `:323`, `:1404` — expecting a
validation result rather than an exception. So the blast radius is the settings page, the
registration pause control, and the notification purge-retention control: three admin
surfaces, all returning a 500.

Wrap `put_settings` the way `update_profile` and `set_user_flags` already are
(`admin_store.py:382`, `:458` route through `_refusal_from`, and `web/api/admin.py:888`,
`:945` turn that into a 409). Do it in the same release as the migration — this is the
concrete case of `supabase/README.md`'s _schema before code_ rule where the interval
between the two is user-visible, so keep it short.

### The test doubles encode the same flaw and must change in lockstep

This is the part that will be missed. The in-memory backends that stand in for Supabase in
every Python test carry the identical conditional:

```text
web/services/admin_store.py:661        if actor.user_id:            # …then check admin
web/services/admin_store.py:761        if actor.user_id:            # …then check admin
web/services/admin_store.py:502        (no actor check at all)
web/services/notification_store.py:444 if not actor.user_id: return True
```

`notification_store.py:444` is the clearest: the double **explicitly returns "authorized"
for a null actor**. And `admin_store.py:502` — `InMemoryAdminBackend.put_settings` — checks
nothing whatsoever, faithfully mirroring the production gap that `admin_write_settings`
has no actor check either. Four sites, not the three an earlier draft listed.

After the migration the database refuses a null-actor mutation and the test suite still
accepts one — a green suite asserting the opposite of production. Update all four in the
same commit, and add a test that a null actor is refused, so the two contracts are pinned
together.

**Five test files will break, and they are the reason this looks harder than it is.** These
construct an actor whose id is not one of the seeded admins, and pass today only because
the doubles wave a falsy or unknown id through:

```text
web/tests/test_admin_settings.py:27      AuditActor("admin-id", …)
web/tests/test_admin_audit.py:26         AuditActor("admin-id", …)
web/tests/test_generation_settings.py:27 AuditActor("admin-id", …)
web/tests/test_registrations_pause.py:29 AuditActor("admin-id", …)
web/tests/test_admin_users.py:116, :128  AuditActor("someone-else", …)
```

Point them at the seeded `"test-admin-id"`. `test_admin_users.py` is the one to read
before changing: `"someone-else"` may be deliberate there — it is testing what a _different_
administrator can do — so check the assertion's intent rather than renaming by reflex.

This does not make the Python test a proof about Postgres — it cannot be, since the doubles
never execute SQL. Proving the RPC raises `AD004` belongs in finding 7's SQL suite. The
point of changing the doubles is narrower and still necessary: to stop them from asserting
a behaviour the database no longer has.

---

<a id="16"></a>

## 16. Reader receipt writes ignore the notification lifecycle

**Severity: Medium.**

`notifications_list_active_for_reader` filters on all three lifecycle conditions —
`deactivated_at is null`, `deleted_at is null`, and `expires_at` in the future. The
mutations that write receipts do not.

`notifications_mark_read` checks existence, type and targeting only
(`20260823202428_reader_notification_rpcs.sql:201-223`).
`notifications_mark_all_read`'s eligible CTE checks `deleted_at` and targeting
(`:265-275`). Both are reachable by any authenticated reader holding a notification id
(`web/api/app.py:2957-3020`).

So a stale browser tab, or a scripted call, can acknowledge a modal the operator withdrew
an hour ago, and the acknowledgement count goes up. For a `requires_ack` modal — the
notification type that exists specifically so somebody can later demonstrate that readers
saw something — a count that includes acknowledgements of a retracted notice is worse than
no count.

The check alone is not enough, because the read is unlocked. `admin_deactivate_notification`
and `admin_delete_notification` both take `for update` on the same row
(`20260823202323_admin_deactivate_and_delete_notification.sql:36` and `:101`), so a reader
can observe "active", the administrator can retract and commit, and the reader can then
write the acknowledgement — reproducing the exact count corruption this finding claims to
prevent, just in a narrower window. **Lock the row as part of the read:**

```sql
select * into v_notification
  from public.notifications
 where id = p_notification_id
   for share;                       -- conflicts with the admin path's FOR UPDATE

if p_action in ('dismissed', 'acknowledged')
   and (v_notification.deleted_at is not null
        or v_notification.deactivated_at is not null
        or (v_notification.expires_at is not null
            and v_notification.expires_at <= now())) then
  raise exception 'this notification is no longer active' using errcode = 'RN003';
end if;
```

`FOR SHARE` conflicts with `FOR UPDATE` and `FOR NO KEY UPDATE` and is held to the end of
the transaction, so the retraction waits behind the receipt or the receipt is refused.
`FOR KEY SHARE` is too weak — a lifecycle update touches non-key columns and would not
conflict with it.

Whether plain `read` should also be refused is a product question: marking an item read in
a _history_ list is reasonable long after it stopped being active, and
`notifications_list_history_for_reader` exists to show exactly that. Dismissal and
acknowledgement are display actions on a live notice and should not survive it.

**`RN003` must be mapped in the same release, or this finding ships a 503.**
`_REFUSAL_CODES` (`web/services/notification_store.py:46-58`) currently maps `AN001`–`AN009`,
`RN001` and `RN002` — not `RN003`. `mark_read` (`:393-398`) routes PostgREST errors through
`_refusal_from`, but an unmapped SQLSTATE comes back as a raw exception, and the route
(`web/api/app.py:2985-2998`) catches `AdminActionRefused` → 409 and then falls through to:

```python
except Exception:
    logger.warning("Could not record %s on %s for %s.", …)
    return jsonify(error="mark_read_failed"), 503
```

So a reader acknowledging a withdrawn notice would get a **503 "mark_read_failed"** — a
server-error shape for a deliberate refusal, which is both wrong for the client and
misleading in the logs. Add `"RN003": "notification_no_longer_active"` to `_REFUSAL_CODES`
before the migration can raise it.

---

<a id="17"></a>

## 17. Notification replay races, and its payload hash omits `resend_of`

**Severity: Medium**, on the admin path rather than the reader path.

Two distinct defects in the same idempotency mechanism:

**The replay probe is read-then-insert with nothing serialising it.**
`admin_create_notification` selects any existing row for
`(created_by, client_request_id)`, and if none is found, inserts. Two concurrent calls with
the same key — a double-click, a retry after a timeout — can both read nothing and both
proceed; one wins the unique index and the other gets `23505`. The caller that loses is
told "storage error" about a notification that was in fact created successfully, which is
precisely the outcome the replay contract exists to prevent.

**The payload hash does not cover `resend_of`.** The server-side hash inputs stop at
`expires_at` (`web/services/notification_store.py:269-281`), while `p_resend_of` is
inserted into the row (`:297-304`). So a retry that changes only `resend_of` hashes
identically, is reported as a replay, and silently keeps the original provenance link —
making the console's "resent from" history wrong in the one place it is consulted.

```sql
-- After actor validation, before the existing probe: serialise only same-key callers.
perform pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(p_actor_id::text || ':' || p_client_request_id::text, 0));

-- And make the replay comparison cover the field the hash misses.
if v_existing_hash = p_request_payload_hash
   and (v_existing ->> 'resend_of') is not distinct from p_resend_of::text then
  return v_existing || jsonb_build_object('_replay', true);
end if;
```

The advisory lock is transaction-scoped and keyed on the actor and request id, so it
serialises only genuine duplicates; the unique index stays the final arbiter. Adding
`resend_of` to the Flask-side hash inputs instead would also work and is arguably cleaner —
but it changes what a hash means across a deploy, so old in-flight retries would stop
matching. The in-function comparison has no such boundary.

### This fix depends on finding 15, and gets it wrong silently

`pg_advisory_xact_lock` and `hashtextextended` are both **strict**:

```sql
select proname, proisstrict from pg_proc
 where proname in ('pg_advisory_xact_lock','hashtextextended');
-- hashtextextended      | t
-- pg_advisory_xact_lock | t
```

So if `p_actor_id` is null, `p_actor_id::text || ':' || …` is null, the hash is null, and
`pg_advisory_xact_lock(null)` returns null **having taken no lock at all** — verified:

```sql
select (null::uuid)::text || ':' || 'x' as concat, pg_catalog.hashtextextended(…) as hash;
-- concat: null   hash: null
```

It does not raise. It does not warn. The serialisation this finding exists to add simply
is not there, in precisely the null-actor case that finding 15 exists to eliminate.

**Land finding 15 first.** The sequencing below already happens to order them that way, but
"happens to" is how the notification bell nearly got broken. If finding 17 must go first
for some reason, key the lock on `p_client_request_id` alone rather than on a concatenation
that a null can poison.

---

<a id="18"></a>

## 18. `chat_append_turn` validates the sources array but not its elements

**Severity: Low** today, Medium the day a source serialiser changes.

The function guards the outer shape and stops there:

```sql
if jsonb_typeof(coalesce(p_sources, '[]'::jsonb)) <> 'array' then
  p_sources := '[]'::jsonb;
end if;
```

The comment above it explains the intent well — a malformed payload should cost the
citations, never the turn, _"losing the citation rows of a malformed payload is bad;
losing the turn is worse"_. But the very next statement expands every element and casts
`source_index`, `page`, `score`, `semantic_score`, `lexical_score` and `cited` without
checking that the element is an object. `'[null]'::jsonb` passes the array guard,
`source_index` resolves to NULL, the `NOT NULL` column rejects it, and the whole
transaction aborts — including the message rows.

That matters because of _when_. Flask writes the turn after the `final` SSE frame has been
sent (`web/api/app.py:3187-3216`), so the reader has already read the answer. The abort
does not produce an error they can act on; it produces an answer that vanishes on
refresh — the exact outcome the comment says it is avoiding, reached one level down.

Not currently reachable: the Flask source builder emits objects, and `p_sources` is not
browser-controlled. It is a guard that stops one level short of its own stated intent.

The obvious one-statement guard is itself the bug it is fixing:

```sql
-- WRONG. Do not use this.
if jsonb_typeof(coalesce(p_sources, '[]'::jsonb)) <> 'array'
   or exists (select 1 from jsonb_array_elements(p_sources) as e(value)
               where jsonb_typeof(e.value) <> 'object') then
```

Postgres does not guarantee left-to-right evaluation of `OR` operands and may reorder
them, so `jsonb_array_elements` can be evaluated against a scalar and raise — the precise
failure the guard exists to prevent. **Two statements, not one:**

```sql
if pg_catalog.jsonb_typeof(coalesce(p_sources, '[]'::jsonb)) <> 'array' then
  p_sources := '[]'::jsonb;
end if;
-- Only now is p_sources known to be an array, so it is safe to expand.
```

Then, on the expansion that follows: keep only `object` elements, put every cast inside a
`CASE` branch whose `pg_catalog.pg_input_is_valid` test succeeded, filter `source_index`
to the column's own 1–99 range, drop duplicate `source_index` values before the insert
(there is a unique index on `(message_id, source_index)`), and clamp `snippet` to 321
characters. Dropping non-object elements alone is not enough: an object with a missing
`source_index`, an uncastable `page`, a duplicate index or an overlong snippet still
aborts the turn. `handle_new_user` already demonstrates this style on signup metadata —
normalise to null, never cast blind.

---

## Checked and clean

Audited and found correct. Recorded so that a later reader knows these were examined
rather than skipped, and so a regression in any of them is visible as a change from a
stated baseline.

| Area                             | What was checked                                                                                                   | Result |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ------ |
| `search_path` on every function  | All 31 `public` functions carry `set search_path = ''` with fully-qualified names                                  | Clean  |
| RPC execute grants               | All 24 `security definer` functions are `service_role`-only, bar the two documented exemptions                     | Clean  |
| RLS policy form                  | All 7 policies use `(select auth.uid())` and name `TO authenticated` — the optimised InitPlan form                 | Clean  |
| Foreign-key indexes              | Every FK has a supporting index; the advisor reports no `unindexed_foreign_keys`                                   | Clean  |
| Multiple permissive policies     | No table has two permissive policies for the same role and command                                                 | Clean  |
| Audit-log immutability           | `service_role` holds `INSERT`/`SELECT` only, and `audit_log_no_rewrite` raises on UPDATE/DELETE — belt and braces  | Clean  |
| Chat write idempotency           | `chat_messages_idem_key (session_id, client_request_id, role)` plus the `FOR UPDATE` serialisation point           | Clean  |
| Chat ordering                    | Ordered by `(session_id, seq)`, never by a timestamp — the bug `20260817161427` was written to prevent             | Clean  |
| Realtime broadcast authorization | One policy on `realtime.messages`, scoped to `notify:user:<uid>` and `extension = 'broadcast'`, `TO authenticated` | Clean  |
| Migration filename discipline    | `list_migrations` and `ls supabase/migrations/` agree, in order, across the whole sequence                         | Clean  |
| Cross-column constraints         | `notifications_check` covers `target_kind` against all three target columns in all four branches                   | Clean  |
| Modal/ack invariant              | `notifications_check1` and `check2` pin `type = 'modal'` to `requires_ack` in both directions                      | Clean  |
| Consent record integrity         | `profiles_marketing_consent_grant_chk` requires timestamp, trimmed policy version, `en`/`ar`, surface and the flag | Clean  |
| Expiry sanity                    | `notifications_check3` forbids `expires_at <= created_at` — a notification cannot be born expired                  | Clean  |
| Signup metadata handling         | `handle_new_user` normalises rather than casts, uses `pg_input_is_valid` for age, and `on conflict do nothing`     | Clean  |
| Reader anonymisation             | Both `user_id` FKs use `on delete set null`, and the surrogate keys are what make that nulling legal               | Clean  |
| Identity/sequence headroom       | Every surrogate key is `bigint` identity or `uuid`; no `int4` sequence to exhaust                                  | Clean  |
| Nullability and defaults         | Every nullable-without-default column is deliberately optional; no accidental nullable required field              | Clean  |

The Realtime row is worth expanding, because it is the mistake most projects of this shape
_do_ commit. A broadcast channel subscribed without `{ config: { private: true } }`
bypasses `realtime.messages` RLS entirely — the policy exists and is simply never
consulted, which looks identical to being protected. This project got it right on both
halves: `20260823202440_notifications_realtime_authorization.sql` documents the client-side
requirement, and `@supabase/supabase-js` was upgraded to `2.74.0` specifically because the
previous pin (`2.39.7`) verifiably lacked the `private` channel option. The boundary was
then verified against the live project with a two-reader simulation rather than a mock.

---

## Pre-flight: verified against the code, 2026-08-28

Before any of this is applied, five assumptions the plan makes about the Flask code were
checked by reading it. Three held; two did not and are folded into the findings above.

| Check                                         | Result                                                                                                                                                                            |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Finding 14's revoke breaks no direct write    | **Safe.** The only direct write in `web/` is `admin_store.py:402` → `audit_log`, which finding 14 preserves. No `.from_()`, no raw SQL, no second client.                         |
| Finding 15's mandatory actor breaks no caller | **Safe.** All seven mutating RPCs are called with `actor.user_id` from `actor_from_request(g.identity)`, behind `admin.py`'s `_gate()`. No script, CLI or cron path reaches them. |
| Findings 15/16 raise codes Flask catches      | **No — three gaps.** Folded into findings 15 and 16.                                                                                                                              |
| Test doubles need lockstep changes            | **Yes — four sites and five test files.** Folded into finding 15.                                                                                                                 |
| Finding 10 covers every unbounded fetch       | **No — a second one.** Folded into finding 10.                                                                                                                                    |

### Wave readiness

- **Wave 1 — ready.** Finding 14 is confirmed safe against every call site; findings 1 and
  12 carry no regression risk. This wave can be applied as written.
- **Wave 2 — ready.** Finding 2's column grants survive the table-level revoke (verified
  directly: `has_column_privilege(… 'first_name','UPDATE')` is true and `… 'role','UPDATE'`
  is false). Finding 3 needs only the drop-or-revoke decision, which has a documented
  fallback.
- **Wave 3 — ready once the Python lands with it.** Nothing here is blocked, but four
  Python changes must ship in the same release as their migrations: wrap `put_settings`
  (`admin_store.py:287`) in `try`/`except _refusal_from`; add `RN003` to `_REFUSAL_CODES`
  (`notification_store.py:58`); require a non-null admin actor in the four doubles and
  repoint five test fixtures; paginate `recipient_ids_for` alongside
  `all_enabled_profile_ids`.

**Wave 0 is not complete.** A row-count and content-hash baseline was captured outside the
repository so that "no migration touched a row" can be verified rather than assumed. That
is not a backup. A restorable copy still has to come from the Supabase dashboard
(Database → Backups) or a `pg_dump` from a machine holding the connection string — neither
is reachable from the MCP tools, and it should be taken before Wave 1.

---

## Sequencing

Each numbered item is one migration, one concern, per `supabase/README.md` rule 1.

**Wave 1 — structural, no behaviour change.** Land together, verify together.

1. Finding 1 — default privileges. _Nothing existing changes; this is the safest
   migration in the plan and the one that makes the rest durable._
2. Finding 14 — revoke `service_role`'s direct writes on the five tables. _Its own
   migration, and it belongs in this wave rather than later: finding 1 closes tomorrow's
   browser-role mistakes while today's privileged code can still bypass every
   notification, settings and profile RPC invariant. Closing the future and leaving the
   present open is the wrong order._
3. Finding 12 — three rows in the README register. _Not a migration. Same commit as
   finding 1, whose verification re-runs the advisors anyway._

**Wave 0 — before any of it.** Take an out-of-band export of the database. Every migration
here is only safe on a database you can restore, and the plan's own Operational gaps
section admits the backup position is unverified. At 14 MB this is minutes, and it is the
cheapest insurance in the document. Do not gate this on confirming PITR: the project is
below the tier PITR requires, so that check will tell you what you already assume.

**Before every grant-changing migration in waves 1 and 2**, run the `has_*_privilege`
probes from findings 1, 2 and 14 inside a transaction that ends in `rollback`. That is a
cheap live check, it needs no CLI and no local stack, and it is the part of finding 7 that
should not wait for finding 7.

Write those probes as assertions rather than as `select` output — a bare `select
has_table_privilege(...)` returns a row that a human has to read and can misread, whereas

```sql
do $$ begin
  if has_table_privilege('anon','public.profiles','TRUNCATE') then
    raise exception 'anon still holds TRUNCATE on profiles';
  end if;
end $$;
```

fails loudly and can be pasted into finding 7's suite later without rewriting. That is the
difference between a probe worth committing to `supabase/tests/` now and a throwaway.

**Wave 2 — close the existing leaks.** After wave 1, so the cleanup is not immediately
re-opened by the next table.

1. Finding 2 — `revoke` on `profiles`. _Highest-value single statement here. The account
   and signup browser suites are the gate._
2. Finding 3 — `chatbot_settings`. _Blocked on the drop-or-keep decision `TODO.md`
   already owns. If undecided, apply the `revoke all` and leave the drop for later._

**Wave 3 — correctness.** Independent of waves 1 and 2; can run in parallel.

1. Finding 15 — mandatory actor and derived audit email across the seven mutating
   `admin_*` functions. _One authorization concern, but it needs complete
   `create or replace` bodies; argument lists must not change._
2. Finding 4 — the `on conflict … where` predicate, at the two **list** sites only.
3. Finding 16 — lifecycle check in `notifications_mark_read`. _Land with, or just after,
   finding 4: both are `create or replace` on the same file's functions, but they are
   different concerns and get different migrations._
4. Finding 17 — advisory lock plus `resend_of` in the replay comparison. **Hard dependency:
   this must land after finding 15.** Both modify `admin_create_notification`, and 17's
   lock key is poisoned by the null actor that 15 removes — silently, taking no lock and
   raising nothing. This is the one ordering constraint in the plan that fails without a
   symptom.
5. Finding 9 — the two notification FKs.
6. Finding 18 — element-shape guard in `chat_append_turn`.
7. Finding 8's question bound — the `chat_append_turn` clamp first, the role-scoped
   `NOT VALID` CHECK second.
8. Finding 10 — paginate the broadcast fan-out. _Application code, not a migration._
9. Finding 11 — measure through PostgREST first; the `alter role` is a footnote to the
   measurement, plus a note in `docs/OPERATIONS.md`.

**Wave 4 — needs a decision first, not engineering.**

1. Finding 6 — `is_active_account()` on the `profiles` UPDATE policy. _Blocked on what
   "disabled" means._
2. Finding 8's retention job. _Blocked on a retention period._
3. Finding 13 — `last_seen_at`. _Blocked on write-it-or-drop-it._
4. Finding 5 — the `chat_sessions.owner_id` FK. _Blocked on, and sequenced behind, the
   account-deletion saga. Correct the migration comment's claim about `ON DELETE CASCADE`
   now, in `supabase/README.md`, even if the constraint waits._

**Wave 5 — the investment.**

1. Finding 7 — pgTAP privilege and RLS tests. _Deliberately last in sequence and first in
   value._

**Nothing here needs an atomic cutover.** No item in this plan requires the documented
exception to rule 1; every one splits cleanly by concern, and no `drop` rides along with a
fix.

### Migration sketch index

| Wave | Sketch filename                                | One-liner                                                     | Risk                              |
| ---- | ---------------------------------------------- | ------------------------------------------------------------- | --------------------------------- |
| 1    | `…_revoke_default_privileges.sql`              | `alter default privileges … revoke all`                       | Low — no existing object moves    |
| 1    | `…_service_role_read_only_tables.sql`          | `revoke all` + `grant select` on five tables                  | Medium — exercise all five reads  |
| 3    | `…_admin_rpcs_require_actor.sql`               | non-null actor + derived audit email, ×7                      | Medium — full bodies, same args   |
| 3    | `…_notification_receipts_require_active.sql`   | lifecycle check before dismiss/acknowledge                    | Low — add `RN003` to the mapping  |
| 3    | `…_notification_replay_serialised.sql`         | advisory lock + `resend_of` in replay compare                 | Low — admin path only             |
| 3    | `…_chat_sources_element_guard.sql`             | drop non-object elements instead of aborting                  | Low — function body only          |
| 2    | `…_profiles_table_grant_hygiene.sql`           | `revoke delete, truncate, references, trigger`                | Low — column grants must survive  |
| 2    | `…_chatbot_settings_revoke.sql` **or** `_drop` | `revoke all` or `drop table`                                  | Low — 0 rows, no FKs              |
| 3    | `…_served_at_write_once.sql`                   | `do update … where served_at is null`, **×2 list sites only** | Low — but see finding 4: never ×4 |
| 3    | `…_notification_child_fk_cascade.sql`          | `on delete cascade` on the two child FKs                      | Low — drop + add in one file      |
| 3    | `…_bound_message_and_audit_text.sql`           | `check (char_length …) not valid` + RPC clamp                 | Low — verify no violating rows    |
| 4    | `…_profiles_update_requires_active.sql`        | `alter policy … and is_active_account()`                      | Medium — test a disabled JWT      |
| 4    | `…_chat_sessions_owner_fk.sql`                 | `references auth.users on delete restrict`                    | Medium — changes user deletion    |

---

## What this plan deliberately does not do

A plan that only adds work is a bad plan. These were considered and rejected:

**Do not enable `FORCE ROW LEVEL SECURITY`.** It looks like free hardening and it is a
**no-op on this database**. `FORCE RLS` removes only the _table owner's_ exemption from
RLS. Here the owner is `postgres`, and:

```sql
select rolname, rolbypassrls from pg_roles where rolname in ('postgres','service_role');
-- postgres     | t
-- service_role | t
```

`BYPASSRLS` is checked before ownership and is not affected by `FORCE`. Both roles that
touch these tables — `postgres`, as which every `security definer` RPC executes, and
`service_role`, as which Flask connects — bypass RLS regardless. So `FORCE RLS` would
neither harden anything nor break anything. Adding it would leave a line of DDL that
future readers reasonably assume is doing work.

**Do not add RLS write policies to the chat tables.** Tempting as "completeness", and
`docs/ARCHITECTURE.md` already forbids it. A write policy creates a second, browser-direct
provenance-forgery primitive — a client crafting an `assistant` row with citations of its
choosing — and would have to reimplement the `FOR UPDATE` serialisation and the
seq-pair allocation in RLS, which it cannot.

**Do not add a per-message `DELETE` grant or policy.** Deleting one message leaves a
transcript hole, and `ConversationStore._truncate` slices on a strict
`[user, assistant, …]` assumption. The whole history subsystem — paired `seq` allocation,
the composite cascade from `chat_sessions` — is built on "delete the conversation or
nothing". This is not a small addition; it is an invariant break.

**Do not drop the seven "unused" indexes.** The performance advisor flags them as never
used. Of course they are: four users, eight conversations, zero notifications. Most are
the foreign-key support indexes that `supabase/README.md` rule 4 _requires_, so dropping
them trades an advisor INFO for an advisor WARN plus a sequential scan later.
`unused_index` is a signal on a database with traffic; here it is an artifact of having
none.

**Do not add RLS policies to the service-role-only tables.** `app_settings`, `audit_log`,
`chat_archive` and the three notification tables have RLS on and zero policies _on
purpose_ — a policy is how you would let the browser in, and nothing should be. The
correct response to `rls_enabled_no_policy` is finding 12, not a policy.

**Do not touch the two `SECURITY DEFINER` advisor exemptions.** `is_active_account()`
cannot have `EXECUTE` revoked from `authenticated` without breaking every chat policy,
because Postgres evaluates a `USING` clause as the querying role.
`update_own_preferences(jsonb)` is browser-callable because that is the entire point of
it. Both arguments in `supabase/README.md` are correct as written.

**Do not try to add a trigram index for the admin People search.** It is not deferred —
it is _impossible_ as currently designed, and this is already known:
`20260817161427_people_pager_sort_tiebreaker_and_search_escape.sql:2-11` records that
`create index … on auth.users` failed with `42501: must be owner of table users`, because
`auth.users` belongs to `supabase_auth_admin` and the migration role is not a member.
`admin_list_users` `ILIKE`s on `auth.users.email` across a join. When this eventually
matters, the fix is to **denormalise `email` into `public.profiles`** (synchronised from
`handle_new_user`) and index that — not `create extension pg_trgm` against a table this
project cannot alter. That follow-up is already named in the same migration header.

**Do not normalise `profiles.preferences`.** It is `jsonb`, merge-written through
`update_own_preferences(jsonb)` behind a key allow-list, and the upsert-clobber hole it
used to have is closed and recorded as collision #8 in `docs/ARCHITECTURE.md`. Normalising
it buys a migration per preference.

**Do not build a conversation tombstone table pre-emptively.** `chat_append_turn`'s own
comments name the race: a delete that lands while generation is in flight is followed by
an append that recreates the session. The client refuses destructive sidebar actions while
a stream is live, which closes it for a single-worker deployment. A tombstone table is the
right answer _if_ the app ever goes multi-worker; building it now adds a table and a
lookup on the hot write path to solve a race the deployment shape prevents.

**Do not enable the token-verification positive cache as part of this plan.** A
`ttl_seconds > 0` on `TokenVerificationCache` is a Flask concern, and it trades a
revocation window against Supabase round trips — a trade that needs production
measurement. It is already tracked in `TODO.md` and correctly sitting at `0`. A database
migration cannot make that measurement and should not pre-empt it.

**Do not adopt the Supabase CLI as part of this plan.** It would give `supabase test db`
in CI, which is genuinely what finding 7 wants. It is also a structural change to a
project that has deliberately not had one, and folding it into a hardening pass is how a
plan doubles in size. It deserves its own decision.

---

## Where this schema will break first as it grows

Reasoning from the actual indexes and function bodies, in the order it will happen.
Magnitudes, not promises — they assume the current Flask shape and Supabase tier.

**First: `user_notification_reads` bloat, at the first broadcast.** Finding 4. Not a
volume problem — a write-amplification problem that starts the day a notification goes
live and scales with page loads rather than with data. Noticeable in the low hundreds of
daily readers; a vacuum-can't-keep-up problem in the low thousands. It will present as a
slow notification bell.

**Second: `admin_list_users` at a few thousand profiles.** An `ILIKE '%needle%'` across a
join to `auth.users`, which cannot be indexed from this project (see above). The People
list is the admin console's landing page. `pg_stat_statements` shows 153 calls at a mean
of 4.09 ms against four rows — essentially all fixed overhead, with the variable part
starting to matter in the low thousands. It is behind a 60/min rate limit, which buys
time.

**Third: the `all`-target broadcast fan-out.** Finding 10. Scales with the user base
rather than with traffic, and fires on a single operator action, so it will arrive as "the
send button hung" rather than as gradual slowness.

**Fourth: `chat_load_session` pagination for a heavy reader.** The window predicate is
`(owner_id, session_id, seq < before_seq)` and the available indexes lead with
`session_id` — `chat_messages_order_key UNIQUE (session_id, seq)` and
`chat_messages_session_owner_idx (session_id, owner_id)`. `session_id` is selective
enough that this is fine now and probably fine for a long time. **Watch it rather than
fix it:** if `pg_stat_user_tables.seq_scan` on `chat_messages` starts climbing past
~100k rows, a single `(session_id, owner_id, seq desc)` index is the answer. Do not add it
speculatively. `export_all_sessions` walks the same path in 200-row batches and will feel
it first.

**Fifth: `chat_list_sessions` for a reader with very many conversations.** The index
`chat_sessions_owner_updated_idx (owner_id, updated_at desc, id desc)` exactly matches the
keyset cursor, which is the right design and stays fast per page. What degrades is the
total, and the answer is a product boundary — a conversation cap or an archive tier —
rather than an index.

**Sixth: `audit_log` and `chat_archive` growth.** Neither breaks as a query:
`audit_log_time_idx` and `audit_log_target_idx` cover the console's access patterns, and
all reads are `order by … limit 50`. What grows is backup and restore time, storage
billing, and the loudness of the compliance question in finding 8.

**Not on this list: the chat write path.** `chat_append_turn` is well built — one
`update … returning` to claim the sequence pair, both message rows in a single insert
statement, the sources in one more, the archive behind a guard. The `FOR UPDATE` lock is
per-session, so two readers never contend. It will scale.

---

## Operational gaps

**Backups and PITR are not visible from here, and are written down nowhere.** The MCP
`get_project` response reports status, region and Postgres version, and says nothing about
backup schedule or point-in-time recovery. The advisor's `auth_leaked_password_protection`
finding tells us the project is below the Pro tier, and PITR is a paid add-on — so the
working assumption is daily backups with no PITR. **That assumption is unverified and
should be confirmed in the dashboard and written into `docs/OPERATIONS.md`**, which today
covers DNS and mail but not the database. For a database whose entire content is
user-generated and unreproducible, the recovery point objective is a fact the operator
should be able to state without logging in. A restore drill into a scratch project, once,
is what turns that from a setting into a known-good procedure — and 14 MB is the cheapest
this will ever be to rehearse.

**There is no way to know a grant or a policy regressed.** Finding 7. Today the only
detector is a human running `get_advisors` and remembering what the register says — and
the advisors do not check grants at all, which is why findings 1, 2 and 3 are in this
document rather than in the linter's output.

**`pg_stat_statements` is installed and consulted by nobody on a schedule.** It has data;
nothing reads it. The two queries worth committing into `supabase/README.md` as a
procedure, to be run when something feels slow and once in a while when it does not:

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

Without something like this, finding 4's write amplification is invisible until a reader
complains. It is also a useful reminder that the dashboard and the MCP tools are
themselves load on this database: today's slowest query by total time is Supabase's own
`SELECT name FROM pg_timezone_names`, at 469 ms mean across 133 calls.

**The migration process has no dry run.** `supabase/README.md` recommends round-tripping a
risky migration in a deliberately aborted transaction, which is the right practice and is
a convention rather than a mechanism. Findings 1, 2, 3 and 9 are all grant or constraint
changes — exactly the class where a `rollback`-terminated round trip plus the
`has_*_privilege` probes above should be mandatory rather than recommended.

---

## Corrections made during the merge

Recorded rather than silently edited away, per this repository's own working style. Each
of these is a case where an independently-produced plan was wrong, and the database
settled it.

**The `FORCE ROW LEVEL SECURITY` question was got wrong twice, in opposite directions.**
The first pass rejected it on the grounds that it would break the `security definer` RPCs
by subjecting the owner to policies that do not exist for writes. The independent pass
recommended it as hardening against an owner-level read. Both are wrong for the same
reason: `postgres` and `service_role` both carry `rolbypassrls`, which is checked ahead of
ownership and is unaffected by `FORCE`. It is a no-op here. The conclusion "do not add it"
survived; the reasoning behind it did not, and the reasoning is the part that would have
misled the next reader.

**Finding 4 was understated by a factor of four.** The first pass found the unguarded
`on conflict … do update` in `notifications_list_active_for_reader` only. There are four
such sites in `20260823202428_reader_notification_rpcs.sql` — lines 63, 143, 234 and 280.
A fix applied to one of them would have looked complete and left the history endpoint
churning.

**The trigram-index advice was wrong.** The first pass listed "add `pg_trgm` and a GIN
index when the People list gets slow" as a deferred improvement. It is not deferrable —
`create index … on auth.users` is refused with `42501` on this hosted project, which
`20260817161427`'s own header records having discovered. The real fix is email
denormalisation into `profiles`, which is a different and larger piece of work.

**The `service_role` timeout finding was imprecise on all three passes.** All described
`service_role` as having "no statement timeout". It has no _role-level_ setting and
therefore inherits the cluster's `statement_timeout = 120000` from the configuration file.
What it genuinely lacks — along with every other role and the cluster default — is a
`lock_timeout` and an `idle_in_transaction_session_timeout`. The finding survived; its
severity dropped and its fix changed.

**One proposed fix was rejected for contradicting a documented decision.** The independent
pass proposed `chat_sessions.owner_id → auth.users ON DELETE CASCADE`. That is exactly the
outcome `20260820131914`'s header was written to prevent, and adopting it would have
deleted conversation history on account deletion. The _correction_ to that header stands
(the FK does not imply `CASCADE`); the conclusion drawn from it does not. `RESTRICT` is
the option that honours both the original intent and the integrity gap — see finding 5.

**Finding 4's fix would have broken the notification bell.** The merged plan said to apply
one `where served_at is null` predicate to "all four sites". Two of those four are inside
`notifications_mark_read` and `notifications_mark_all_read`, whose `do update` also sets
`read_at`, `dismissed_at` and `acknowledged_at`. Since the list RPC has already set
`served_at` before a reader can click anything, that predicate would have made every read,
dismissal and acknowledgement a permanent no-op. The finding is real and the fix now names
the two list sites explicitly, with a regression check that the other two still work. This
is the clearest argument in this document for adversarial review: the finding was correct,
the diagnosis was correct, and the patch was worse than the bug.

**Finding 8's fix would have truncated durable transcripts.** The plan derived an
8,000-character bound from `MAX_CHAT_QUERY_CHARS` and then applied it to `p_answer` as
well as `p_question`. That constant bounds the _question_ only; `grep` finds no
answer-length check anywhere in `web/api/app.py`. Model answers routinely exceed it, so
the clamp would have stored a truncated copy of an answer the reader had already been
streamed in full. The CHECK is now scoped with `role <> 'user' or …`, and an
assistant-message bound is named as needing its own number.

**Finding 11's premise was measured on the wrong connection.** The plan asserted that
`service_role` inherits a two-minute `statement_timeout`. That figure came from an MCP
session; Flask reaches the database through PostgREST, which logs in as `authenticator`
(`statement_timeout=8s`, `lock_timeout=8s`) and switches role per request. The adversarial
pass concluded from this that `ALTER ROLE … SET` cannot reach a service-role request at
all, since Postgres applies role GUCs at login and not on `SET ROLE`. **That is true of
plain Postgres and false here:** PostgREST reads the rolconfig of every role the
authenticator may become and applies it per request, which this database's own
`pg_stat_statements` records happening 134 times. So the mechanism works — but with no
rolconfig on `service_role` there is nothing to apply, and the effective timeout is most
likely `authenticator`'s 8s rather than 120s. Both the original claim and its rebuttal
were wrong; the finding is now a request for a measurement rather than an assertion.

**The plan also implied an idle-transaction timeout would bound the `FOR UPDATE` hold.**
It would not. `idle_in_transaction_session_timeout` acts on a transaction that is idle, and
a PL/pgSQL function still executing inside `chat_append_turn` is not idle. Worth setting
as a backstop against a dead client; not a fix for that lock.

**A claim made in conversation and not in this document was also wrong**, and is corrected
here so it does not resurface: the alphabetical BEFORE-trigger order on `profiles` is _not_
undocumented. `20260823014034_marketing_consent_record.sql:256` states it — _"The guard
therefore rejects a caller-supplied timestamp before the setter"_. The order remains
load-bearing and dependent on trigger names sorting the way they do, which is worth knowing
before renaming one; but it was recorded by the person who built it.

**This document contradicted itself in its own summary table.** After finding 4 was
narrowed from four `on conflict` sites to the two list sites, the Migration Sketch Index
still read _"×4"_. An implementer working from the index rather than the finding would have
reintroduced the exact bug the correction above exists to prevent. Fixed. The lesson
generalises: a summary table that repeats a number is a second place for that number to be
wrong, and it will not be re-read when the finding changes.

**A fifth external review proposed six process changes; two were adopted.** They are
recorded here because the reasoning matters more than the verdicts. _Broaden finding 14's
write-path grep beyond the two modules it cites_ — taken, and now settled: across all of
`web/`, `.table(...)` appears only in `admin_store.py` and `notification_store.py`, there
is no `.from_()` anywhere, and the single direct write is `admin_store.py:402` into
`audit_log`, which finding 14 preserves. _Snapshot the database before wave 1_ — taken in
modified form: the proposal was to verify PITR, but this project is below the Pro tier that
PITR requires, so the check yields "daily backups, no PITR" rather than a safety net. The
useful action is an out-of-band export, which at 14 MB is trivial.

**A sixth pass caught four more defects in this document, and one of its own.** It found:
finding 15 said "six mutating functions" when there are **seven** — the omitted one being
`admin_purge_notification`, the permanent-erasure path; `put_settings` has no
`try`/`except`, so finding 15's new refusal would surface as an unmapped 500; finding 16's
lifecycle check reads the row unlocked while the admin path takes `for update`, leaving the
race it claims to close; and finding 18's proposed guard relied on `OR` short-circuit
evaluation to protect a `jsonb_array_elements` call — in a paragraph that itself warned
against relying on evaluation order. All four are corrected above.

**That same pass's headline finding was wrong, and the reason is worth recording.** It
claimed finding 2 leaves table-wide `INSERT`/`UPDATE` standing on `profiles`, so the
column boundary would not hold. The live database says otherwise:

```sql
select has_table_privilege('authenticated','public.profiles','INSERT'),  -- f
       has_table_privilege('authenticated','public.profiles','UPDATE'),  -- f
       has_column_privilege('authenticated','public.profiles','role','UPDATE'),       -- f
       has_column_privilege('authenticated','public.profiles','first_name','UPDATE'); -- t
```

`20260814005509` already revoked both table-level verbs and re-granted them per column,
which is what finding 2 says it did. The reviewer's general principle — that a table-level
grant supersedes column grants, so you revoke the table verb and re-grant the columns — is
correct Postgres and is exactly the pattern that migration used; it simply did not know the
work was already done, because the introspection dump it was pointed at was missing and it
reasoned from this document's prose instead. It flagged the gap honestly rather than
guessing, which is why the error was cheap to catch. **A reviewer without ground truth
produces plausible findings about the code it can read and unfalsifiable ones about the
database it cannot.**

**Two proposals from the fifth review were rejected on evidence.** _Add a Flask regression test
for the null-actor path_ — Flask's tests run against in-memory doubles that never execute
SQL, so such a test would prove nothing about whether Postgres raises `AD004`. The real
work hiding behind that suggestion is the lockstep double update recorded in finding 15.
_Write reverse SQL into each migration header_ — rejected as actively hazardous for grant
migrations specifically. A table-level grant supersedes narrower column-level grants, so a
naive `grant update on public.profiles to authenticated` pasted from a header comment would
destroy the column boundary that `20260814005509` exists to enforce and hand back write
access to `role` and `tier`. Note the nuance the reviewers on both sides missed: this repo
_does_ have a rollback-note convention — `20260821145416:60` and `20260822143411:53` both
carry one — but only on function drop-and-create migrations, where "re-apply the previous
definition" is genuinely safe and the note also states the application-side consequence.
Extending that convention to grant migrations is where it turns into a trap.

---

## Open questions this plan cannot close

These are decisions, not engineering, and each blocks a wave-4 item:

1. **Does "disabled" freeze an account's own profile edits, or only its use of the
   product?** Blocks finding 6.
2. **What is the retention period for `audit_log`, `chat_messages` and — once the salts
   are set — `chat_archive`?** Blocks finding 8's purge job, and overlaps the already-open
   account-deletion question in `TODO.md`.
3. **Is `chatbot_settings` dropped or finally used?** Already open in `TODO.md`. Blocks
   finding 3's second half.
4. **Is `last_seen_at` written or removed?** Blocks finding 13.
5. **Is reader self-deletion permitted?** Already open in `TODO.md` as the blocker on
   Account deletion (Spec 4). It now also blocks finding 5, because the FK's
   `ON DELETE RESTRICT` is only safe once a path exists to delete a reader's
   conversations.
6. **Does this project want a local Supabase stack?** Blocks the CI half of finding 7; the
   pgTAP files themselves do not wait on it.
