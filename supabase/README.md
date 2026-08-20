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
the order things were *actually applied* — which is not necessarily the order they were
written. Name the file after applying, or rename it to match. That way `list_migrations`
and `ls migrations/` can be read side by side and any disagreement is a real one.

Migrations that predate this directory (everything up to `20260813101816`) were applied
directly and are recorded only in `supabase_migrations.schema_migrations`. They are listed
in `migrations/0000_baseline.md` for reference rather than reconstructed as SQL, because
re-deriving them would produce files that were never actually run.

## Rules

1. **One concern per migration**, and the name says which.
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
   owner write *any* column in that row, including one that grants them privileges. Column
   protection needs a column-level `REVOKE` plus a trigger. See
   `20260814005509_lock_profile_privileges_and_repair_signup.sql`, which exists because
   that was not understood the first time.
7. **Destructive changes state what they checked.** Dropping a table means recording the
   row count, the foreign keys in both directions, the triggers, and the grep that proved
   nothing reads it — in the migration, where the next reader will find it.

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

| Finding | Why it stands |
|---|---|
| `rls_enabled_no_policy` on `public.app_settings` | Intentional. Service-role only; a policy is how you would let the browser in. |
| `rls_enabled_no_policy` on `public.chatbot_settings` | Unused table from an abandoned design, left untouched rather than dropped by an unrelated migration. |
| `rls_enabled_no_policy` on `public.audit_log` | Intentional. Written by the admin RPCs and read through them; a policy is how you would let the browser read it directly. Recorded here 2026-08-20 — it had been standing unlisted, which is the thing this table exists to prevent. |
| `rls_enabled_no_policy` on `public.chat_archive` | Intentional, and rule 5 requires it be said here. The training archive is service-role only by design: no reader may select from it, and its only writer is `chat_append_turn` (`security definer`). A policy is how you would let a browser in, and nothing should be. |
| `auth_leaked_password_protection` | A Pro-plan feature; the project is on a lower tier. Tracked in `TODO.md`. |

## Current shape of `public`

| table | rows | notes |
|---|---|---|
| `profiles` | one per account | Identity **and** authorization. `role`, `tier`, `is_disabled` are writable only by the service role — see rule 6. |
| `app_settings` | exactly one | Runtime overrides as JSONB. Absent keys fall back to `web/config.yaml`. |
| `chatbot_settings` | 0 | Unused. Not read or written by any code. |
| `chat_sessions` | one per conversation | Created lazily by `chat_append_turn` on the first completed turn, so a reset cannot fill the table with empties. Readers `select`/`delete` their own via RLS; **no insert or update policy exists** and none should. |
| `chat_messages` | two per turn | The question and the answer, ordered by a per-session `seq` (never a timestamp — see `20260817161427` for what same-millisecond ordering cost the People list). Content is writable only by `chat_append_turn`. |
| `chat_message_sources` | one per **retrieved** passage | Not one per cited passage: what search offered and the model declined is unrecoverable after a rebuild. `cited` flags which ones the answer used, and `source_index` is the `[n]` the model saw. |
| `chat_archive` | one per turn | Append-only training record under HMAC'd owner/session keys, with **no FK** to anything — so a reader deleting their history does not delete training data, and vice versa. Skipped entirely when the salts are unset. |

`public.users` was dropped on 2026-08-14. It had never held a row: the signup trigger's
insert into it was added on 2025-12-07, three weeks after the most recent signup, so it
never once ran. `profiles` is the only identity table.
