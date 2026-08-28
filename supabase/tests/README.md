STATUS: CURRENT AUTHORITY — how to run the database assertions, and why they
are shaped the way they are. Last verified against the live project 2026-08-28.

# `supabase/tests/` — assertions the Python suite cannot make

Every Python test in this repository mocks the Supabase client. That is the
right trade for the application logic and it means **the test suite cannot fail
because of a grant**. `docs/database-improvement-plan.md` findings 1, 2, 3 and
14 were all grant-layer facts, sitting undetected under a green CI run, and the
advisors do not check grants at all — which is why those findings came from
reading `pg_default_acl` rather than from a linter.

These files are the detector. Three assert the privilege and policy state
directly; the fourth, `rpc_behaviour.test.sql`, calls the hardened RPCs and
checks what they do — because six of the twelve hardening migrations changed a
function BODY, and a body is not visible in any catalogue assertion.

| File                     | What it protects                                                                |
| ------------------------ | ------------------------------------------------------------------------------- |
| `privileges.test.sql`    | Table and column grants, in both directions, plus both default-ACL layers       |
| `function_acls.test.sql` | The five-part RPC contract: who may execute what, and `search_path`             |
| `rls_chat.test.sql`      | Reader-to-reader isolation, and that no browser-direct write path exists        |
| `rpc_behaviour.test.sql` | The actor gate, receipt lifecycle, replay, source normalisation, question clamp |

`rpc_behaviour.test.sql` is the one that would otherwise rot: every behaviour it
covers was verified once, by hand, on the day it was written. A manual
verification proves the code was right that afternoon and protects nothing
afterwards.

## Running them

There is no Supabase CLI in this repo and no local stack, so there is nowhere
`supabase test db` would run. Paste each file into the Supabase MCP
`execute_sql` tool, or into the dashboard SQL editor, one at a time.

Each file is a single `do $$ … $$` block that **raises on the first failure and
raises a summary line on success**. Both outcomes come back as an error, which
is deliberate: it means the block never commits, and it means a pass is
impossible to misread as "the query returned some rows I did not look at".

- A pass looks like: `ERROR: P0001: PASS privileges.test.sql — <n> assertions`
- A failure looks like: `ERROR: P0001: FAIL privileges — anon holds TRUNCATE on public.profiles`

Read the word after `P0001:`. Nothing else in the line matters.

`rls_chat.test.sql` additionally writes rows before checking them, and relies on
the same raise to roll everything back. Do not edit the trailing `raise` out of
any of these files to "make them return cleanly" — that would commit the
fixtures.

## When to run them

**Before and after every migration that touches a grant, a policy or a role.**
That is the part of the plan's finding 7 that should not wait for the rest of
it. Findings 1, 2, 3, 9 and 14 were all in that class, and a round trip in a
rolled-back transaction plus these assertions is the cheapest check available.

They are not wired into CI. CI has no database, and giving it one is a separate
decision — see `TODO.md`.

## Why plain `do` blocks and not pgTAP

The plan sketched these as pgTAP files. `pgtap` is in this project's available
extension list and is **not installed**, and installing it means adding a few
hundred functions to the production database in order to run three assertion
files. The assertions are the valuable part; `ok()` and `plan()` are not.

A `do` block needs no extension, runs today, and reads the same. If pgTAP is
ever installed the bodies convert mechanically — each `if … then raise` becomes
one `select ok(not …, '…')`.

## What these do NOT cover

- **Anything requiring a real JWT.** `rls_chat.test.sql` simulates a reader with
  `set local role authenticated` plus a `request.jwt.claims` setting, which is
  what `auth.uid()` reads. That proves the policies; it does not prove GoTrue
  issues the claim the policy expects.
- **PostgREST's own behaviour.** Whether a table appears in the exposed schema,
  and what `db-max-rows` truncates, are answered by the HTTP layer, not by SQL.
- **The application.** A grant can be correct and the Flask code still wrong.
  The browser suite is what proves the signup and account flows survive
  `20260828001035_profiles_table_grant_hygiene.sql`; a grant assertion cannot,
  because what is at risk there is the interaction between a table revoke and a
  surviving column grant.
