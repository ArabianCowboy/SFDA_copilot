STATUS: CURRENT AUTHORITY — migration process and current schema shape.
Last verified against the live project 2026-08-23.

# Supabase schema

The database is part of this application, so its schema lives here in version control.
Until 2026-08-14 it did not: every table, policy and trigger had been applied straight to
the project, and the only record of the 2026-08-13 security audit was prose in `TODO.md`.

## What is here

```
supabase/
  migrations/     one .sql file per migration, named <version>_<name>.sql
  README.md       this file
```

There is no `seed.sql`. Nothing in the schema currently needs reference data — add one
when something does, rather than committing an empty file that implies otherwise.

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

### Findings that are expected, and must stay explained

The advisors are only useful if a clean run means something, so every standing finding is
accounted for here. Anything not on this list is a regression from the migration you just
applied.

| Finding                                                                                        | Why it stands                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `rls_enabled_no_policy` on `public.app_settings`                                               | Intentional. Service-role only; a policy is how you would let the browser in.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `rls_enabled_no_policy` on `public.chatbot_settings`                                           | Unused table from an abandoned design, left untouched rather than dropped by an unrelated migration.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `rls_enabled_no_policy` on `public.audit_log`                                                  | Intentional. Written by the admin RPCs and read through them; a policy is how you would let the browser read it directly. Recorded here 2026-08-20 — it had been standing unlisted, which is the thing this table exists to prevent.                                                                                                                                                                                                                                                                                                                                                 |
| `rls_enabled_no_policy` on `public.chat_archive`                                               | Intentional, and rule 5 requires it be said here. The training archive is service-role **read-only** by design: no reader may select from it, and its only writer is `chat_append_turn` (`security definer`). A policy is how you would let a browser in, and nothing should be. `20260820213833` reduced `service_role` from `INSERT, REFERENCES, SELECT, TRIGGER` to `SELECT` — the named-verb revoke in the base migration had left `REFERENCES` and `TRIGGER` standing, which is precisely what that migration's own sibling-table comment warns `revoke all` exists to prevent. |
| `auth_leaked_password_protection`                                                              | A Pro-plan feature; the project is on a lower tier. Tracked in `TODO.md`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `authenticated_security_definer_function_executable` on `public.is_active_account()`           | Intentional, added `20260822225054`. It is `stable`/read-only, takes no arguments, and answers only for the caller's own row via `auth.uid()` — there is nothing for a caller to leverage against another account. `EXECUTE` cannot be revoked from `authenticated`: the RLS policies on `chat_sessions`, `chat_messages` and `chat_message_sources` call it from their `USING` clause, and Postgres evaluates that clause as the querying role — revoking would break every reader's own chat access, not just PostgREST's direct RPC exposure.                                     |
| `authenticated_security_definer_function_executable` on `public.update_own_preferences(jsonb)` | Intentional, added `20260822225239`. Being callable via `/rest/v1/rpc/update_own_preferences` is the point — it is the merge-write path for `profiles.preferences` (Decision 6). It writes only the caller's own row (`where id = (select auth.uid())`, never a passed-in id) and only through an in-function key allow-list, so `SECURITY DEFINER` grants it write access to a column the caller could already write via the ordinary column grant — it does not cross an ownership boundary.                                                                                       |

## Current shape of `public`

| table                  | rows                          | notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ---------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `profiles`             | one per account               | Identity **and** authorization. `role`, `tier`, `is_disabled` are writable only by the service role — see rule 6.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `app_settings`         | exactly one                   | Runtime overrides as JSONB. Absent keys fall back to `web/config.yaml`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `chatbot_settings`     | 0                             | Unused. Not read or written by any code.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `chat_sessions`        | one per conversation          | Created lazily by `chat_append_turn` on the first completed turn, so a reset cannot fill the table with empties. Readers `select`/`delete` their own via RLS; **no insert or update policy exists** and none should. `title` is set by `chat_append_turn` from the first turn's question (`coalesce(title, …)` — set when null, never overwritten, so a rename survives every later turn) and changed only by `chat_rename_session`, which deliberately **does not touch `updated_at`**: that column means "last spoken in", and a rename must not lift a months-old conversation to the top of the sidebar. See `20260821145319` and `20260821145416`. |
| `chat_messages`        | two per turn                  | The question and the answer, ordered by a per-session `seq` (never a timestamp — see `20260817161427` for what same-millisecond ordering cost the People list). Content is writable only by `chat_append_turn`.                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `chat_message_sources` | one per **retrieved** passage | Not one per cited passage: what search offered and the model declined is unrecoverable after a rebuild. `cited` flags which ones the answer used, and `source_index` is the `[n]` the model saw.                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `chat_archive`         | **0 — dormant**               | Append-only training record under HMAC'd owner/session keys, with **no FK** to anything — so a reader deleting their history does not delete training data, and vice versa. Skipped entirely when the salts are unset, which they are, so nothing has ever been written. Since `20260820213833`, `service_role` holds **`SELECT` and nothing else**: the only writer is `chat_append_turn` (`security definer`), and **there is no delete path at all**. See `web/config.yaml`'s `archive_disclosed` for the guard that stops the salts being set without restoring the reader-facing controls that were cut while it was empty.                        |

`public.users` was dropped on 2026-08-14. It had never held a row: the signup trigger's
insert into it was added on 2025-12-07, three weeks after the most recent signup, so it
never once ran. `profiles` is the only identity table.

---

## Before your next migration

Two of the eight known rule collisions in this repository live in this file — the
one-concern rule versus the atomic cutover, and the filename rule versus the fact that
the name only exists after applying. Both are written above. The other six, and the
register they are kept in, are in
[`docs/ARCHITECTURE.md` → _Rules that collide_](../docs/ARCHITECTURE.md#rules-that-collide).
Read it before you write the migration, not after it surprises you.
