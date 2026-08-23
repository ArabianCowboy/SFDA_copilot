STATUS: HISTORICAL RECORD — the schema as it stood on 2026-08-14. Not current state.
For the current shape of `public`, see `supabase/README.md`.

# Baseline — migrations applied before this directory existed

These were applied directly to the project and exist only in
`supabase_migrations.schema_migrations`. They are recorded here by version and name rather
than reconstructed as `.sql`, because a reconstruction would be a file that was never run —
which is exactly the drift this directory exists to prevent.

| version        | name                                    |
| -------------- | --------------------------------------- |
| 20250427073035 | create_profiles_table                   |
| 20250629083241 | add_profile_customization               |
| 20250630111737 | add_profiles_rls_policy                 |
| 20250630114337 | add_profiles_insert_policy              |
| 20251207173359 | fix_auth_triggers_and_policies          |
| 20260813101747 | harden_security_definer_and_search_path |
| 20260813101816 | optimize_rls_auth_uid_calls             |

Everything from `20260814005509` onward is a `.sql` file in this directory.

## State at the point this directory was created (2026-08-14)

_(Historical. For the current shape of `public`, see `../README.md`.)_

Three tables in `public`, all with RLS enabled:

- **`profiles`** — 2 rows, FK to `auth.users(id)`, `role text default 'user'` with one row
  already set to `admin`. Own-row select/insert/update policies for `authenticated`.
- **`users`** — 0 rows, no FK, columns `role` / `is_admin` / `tier`. Own-row select policy.
  Read by no application code (verified by grep). Dropped by
  `20260814024903_drop_unused_public_users.sql`.
- **`chatbot_settings`** — 0 rows, RLS enabled with zero policies. Unused. Left untouched.

`auth.users` held 3 accounts; `profiles` held 2.

**Why `users` was empty.** `fix_auth_triggers_and_policies` (2025-12-07) is what introduced
the `insert into public.users` in `handle_new_user`. The most recent signup was 2025-11-16 —
three weeks earlier. The trigger has therefore never fired for any existing account, which
is also why the 2025-11-16 account has no `profiles` row: it was created under the _previous_
trigger, the one that migration was written to fix.

`TODO.md` stated that `public.users` was "populated by the signup trigger on every new
account". That was never true, and is corrected in the commit that adds this directory.
