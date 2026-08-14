# Supabase schema

The database is part of this application, so its schema lives here in version control.
Until now it did not: every table, policy and trigger was applied straight to the project,
and the only record of the 2026-08-13 security audit was prose in `TODO.md`.

## What is here

```
supabase/
  migrations/     one .sql file per migration, named <version>_<name>.sql
  README.md       this file
```

There is no `seed.sql` yet. Nothing in the schema currently needs reference data — add one
when something does, rather than committing an empty file that implies otherwise.

`migrations/` is the **canonical, reviewable record**. A migration is not "done" until its
`.sql` file is committed alongside the code that depends on it.

## How migrations are applied

Through the Supabase MCP `apply_migration` tool, using the **same `name` as the file**, so
`list_migrations` and `git log` describe the same history. There is no Supabase CLI in this
project and no automatic runner — the file and the applied migration are kept in step by
that naming discipline plus the verification below.

Migrations that predate this directory (everything up to `20260813101816`) were applied
directly and are recorded only in `supabase_migrations.schema_migrations`. They are listed
in `migrations/0000_baseline.md` for reference rather than reconstructed as SQL, because
re-deriving them would produce files that were never actually run.

## Rules

1. **One concern per migration**, and the name says which.
2. **Every function ships `set search_path = ''`** with fully-qualified names. A mutable
   `search_path` on a `SECURITY DEFINER` function is a privilege-escalation vector, and the
   Supabase security advisor flags it.
3. **Every foreign key gets its index in the same migration** that creates it, or the
   performance advisor flags it.
4. **RLS is enabled on every new table.** Where a table is deliberately service-role-only and
   therefore has zero policies, say so in a comment in the migration — the advisor reports
   `rls_enabled_no_policy` as INFO and the next reader must be able to tell intent from
   oversight.
5. **RLS cannot restrict columns.** A policy like `USING (auth.uid() = id)` lets the row's
   owner write *any* column in that row, including one that grants them privileges. Column
   protection needs a column-level `REVOKE` plus a trigger. See `0001`.
6. **Destructive changes state what they checked.** Dropping a table means recording the grep
   that proved nothing reads it.

## Verifying the database matches this directory

After applying anything:

```
list_tables            → compare tables, columns and FKs against the migrations
get_advisors security  → expect only the known Pro-plan leaked-password WARN
get_advisors performance
list_migrations        → versions and names should match the filenames here
```

The known, accepted advisor findings are recorded in `TODO.md`. Anything else is a
regression introduced by the migration you just applied.
