---
authority: historical
status: superseded
do_not_implement: true
archived: 2026-09-23
supersedes_note: >
  A finished plan, built on 2026-09-23 after three reviews of the plan (OpenCode, Codex,
  Antigravity) and two of the implementation (/code-review, OpenCode). It reversed its own
  route-level UUID check twice: first to a Python-side split, then to a text[] RPC that
  reports non-uuids itself. It records what was decided and what it cost; it is not a
  specification.
live_authority:
  - docs/ARCHITECTURE.md
  - TODO.md
---

> [!CAUTION]
> **You are reading history, not a specification.** The live contract is
> `docs/ARCHITECTURE.md#reader-quota`; read that, not this. Final position, so no section has
> to be read in a special order:
>
> - **One selection surface.** People has the tier filter, row checkboxes and an
>   always-visible "Move to {tier}" toolbar; the Tiers tab only links into it (Readers count
>   → filtered, "Add readers" → destination preset).
> - **Three migrations**, all applied 2026-09-23: `20260923174827` (list filter and
>   `has_profile`), `20260923174838` (the move RPC), `20260923194026` (its ids become
>   `text[]`). The Backend section below describes the second one's `uuid[]` form, which
>   the third replaced.
> - **Ids:** the route checks shape only (1–200 non-empty strings); a non-uuid is reported
>   `missing` by the SQL, after its refusals — not refused with 400 (§Backend and §Review
>   disposition say otherwise; "Changes during implementation" reversed them).
> - **The toolbar is always visible** ("0 selected", Move disabled), not shown on the first
>   tick as §People tab describes; and focus moves after a Move or a Tiers-tab jump only if it
>   was lost to `<body>`. The Tiers table skips its post-Move refresh while a tier form is in
>   progress.
> - **Overrides are never touched** by a move; that part never changed.
> - **Still open, lifted into `TODO.md`:** arrow-key tab activation skips the lazy loaders,
>   Notification History's post-action focus, the Overview's tier counts.

# [HISTORICAL] Tier membership from the admin console — plan

## [HISTORICAL] Context

Today a reader can be moved to a tier only one at a time: People → open account → allowance card → Tier dropdown → Save (`quotaForm`, `static/js/admin/ui.js:1552`; `saveAccountQuota`, `static/js/admin/handlers.js:1342`). The Tiers tab shows a "Readers" count, but it has no way to add people, and the People list cannot be filtered by tier. The operator expected to manage membership from the tier itself.

Two backend gaps:

- `admin_list_users(p_limit, p_offset, p_search)` has no tier filter (`supabase/migrations/20260817161427_people_pager_sort_tiebreaker_and_search_escape.sql`), and `GET /admin/api/users` only reads `limit/offset/q` (`web/api/admin.py:367-393`).
- The only write path, `admin_set_reader_quota`, **deletes the per-reader override when `p_daily_message_limit_override` is null** (`20260903200648_admin_set_reader_quota_rpc.sql:78-79`). Reusing it for bulk moves would silently wipe allowances, so a tier-only RPC is required. Both reviewers confirmed this.

**Outcome.** One selection surface, the People tab, gets a tier filter, row checkboxes and a "Move to tier" toolbar. Each Tiers row gets two entry points into it:

- the **Readers count** opens People filtered to that tier;
- **"Add readers"** opens People with every tier shown, that tier preselected as the destination, and the search box focused.

This is a design change from the first draft. The draft built a second search-and-select card inside the Tiers tab, and both reviewers flagged it as a duplicate of the People pipeline. Removing it saves roughly 200-250 lines.

## [HISTORICAL] Backend

### [HISTORICAL] Migration 1 — `admin_list_users` gains `p_tier` and `has_profile`

This is one file. `drop function public.admin_list_users(int, int, text);` then `create function` with `p_tier text default null`. Never `create or replace`, per `supabase/README.md:182-185`.

The body is the current one, with two changes:

- Add `(p_tier is null or p.tier = p_tier)` to the `matched` filter. Filter on the **real** `p.tier`, not the coalesced display value. That way the filtered list agrees with `admin_list_tiers.member_count`, which counts only profile rows (`20260903200618_admin_tier_rpcs.sql:23`), and orphans never appear under a tier filter.
- Add `(p.id is not null) as has_profile` to the projection, so the UI can make orphan rows unselectable.

After the body:

- Restate **both** `revoke … from anon, authenticated, public` **and** `grant execute … to service_role` on the new signature. A dropped function loses its ACL, as in the precedent at `20260821145416_chat_first_turn_title.sql:283-292`.
- The header records the callers audit: the only caller is `SupabaseAdminBackend.list_users` (`web/services/admin_store.py:536`). It also records the rollback, which is to recreate the 3-argument version.

### [HISTORICAL] Migration 2 — new RPC `admin_set_users_tier`

Signature: `(p_user_ids uuid[], p_tier text, p_reason text, p_actor_id uuid, p_request_ip text default null, p_user_agent text default null) returns jsonb`, `security definer`, `set search_path = ''`.

Steps, in order:

1. If `p_actor_id` is null, raise AD004.
2. `pg_advisory_xact_lock(hashtext('sfda.admin_membership'))`.
3. `v_actor_email := public.admin_actor_email(p_actor_id, 'AD004')`.
4. If `p_user_ids is null or cardinality(p_user_ids) not between 1 and 200`, raise **TQ009**.
5. If the tier does not exist, raise TQ002.
6. For each id in `select distinct unnest(p_user_ids)`, run `select tier … from public.profiles where id = … for update`:
   - no row → the id goes into `missing`;
   - same tier → count it as `unchanged`;
   - otherwise → `update profiles set tier`, then insert one `user.tier_change` audit row. It has the same columns and shape as `admin_set_reader_quota.sql:68-76`: `before {tier}`, `after {tier}`, `note = p_reason`, and `nullif(p_request_ip,'')::inet`.
7. **Never reads or writes `reader_quota_overrides`.**

Returns `{moved_ids: [...], unchanged: n, missing: [...]}`. The route needs `moved_ids` to evict exactly those ids' caches.

Grants: revoke from anon/authenticated/public, then `grant execute … to service_role`.

Required in the same commit:

- add the RPC to the mutating-RPC list in `supabase/tests/function_acls.test.sql:191-204`;
- add executable cases to `supabase/tests/rpc_behaviour.test.sql` (see Tests).

**Applying.** Use `apply_migration`, then rename each file to the version that `list_migrations` reports. Confirm the PostgREST schema cache reloaded, then run `supabase/tests/*.test.sql`.

### [HISTORICAL] Store — `web/services/admin_store.py`

- Add `"TQ009": "invalid_member_batch"` to `_REFUSAL_CODES` (`:72-92`).
- **Protocol:**
  - `list_users(*, limit, offset, search, tier=None)`;
  - new `set_users_tier(user_ids, *, tier, reason, actor) -> dict`.
- **Supabase backend:**
  - `list_users` sends `p_tier` and keeps `has_profile`;
  - `set_users_tier` goes through `self._rpc` with `actor.as_rpc_args(with_email=False)`.
- **In-memory double:**
  - `list_users` filters `r.get("has_profile", True) and r["tier"] == tier` when `tier` is set, keeps `has_profile` in the rows, and totals the filtered set.
  - Fix `list_tiers` (`:845-855`) so it does not count the profile-less seed as `free`. That brings it into parity with the SQL.
  - `set_users_tier` calls **`self._require_admin_actor(actor)` first** (`:1010`). The existing tier/quota doubles skip this, and that bug must not be copied.
  - It then mirrors the SQL: TQ009/TQ002 refusals, dedup, missing/unchanged/moved, audit rows, and a `self._quota.profile_tiers[uid]` sync for moved ids.

### [HISTORICAL] Routes — `web/api/admin.py`

- `GET /api/users`: optional `tier`, which must match `TIER_KEY_RE` (`:49`) or the route returns 422 `invalid_tier`. It is passed through to `list_users`.
- New `POST /api/tiers/<key>/members`, body `{user_ids: [...], reason?: str}`:
  - validate `key` against `TIER_KEY_RE`;
  - `user_ids` must be a list of 1-200 **UUID strings**, checked on the raw list, then deduplicated with order kept. Anything else returns 400 `invalid_payload`;
  - `reason` is optional and trimmed; empty becomes null;
  - `AdminActionRefused` → 409 `{error: code}`;
  - call `_evict_identity_caches(uid)` (`:580-596`) for each of `moved_ids` before responding, for the same reason `put_user_quota:1180-1182` does;
  - respond `{moved: len(moved_ids), unchanged, missing}`.

## [HISTORICAL] Frontend

### [HISTORICAL] `static/js/admin/services.js`

- `users({…, tier})` appends `&tier=` when it is set.
- New `addTierMembers(key, userIds, reason)`, which POSTs `tiers/<key>/members`.

### [HISTORICAL] People tab — the one selection surface

- **Template** (`web/templates/admin.html:202-206`): a labelled `<select id="people-tier-filter">` beside `#people-search`, with a visible label and an "All tiers" option.
- **`initPeopleTab`** (`handlers.js:811`):
  - Attach the filter and bulk listeners **before** the first `await loadPage()` (`:983`). Today the `change` listener is attached only after it (`:1021`), so an early programmatic change can be lost.
  - Load the tier catalogue **independently** of the user list. If the catalogue is unavailable, the list still renders, the filter stays on "All", and bulk move is disabled.
  - Thread `tier` through `loadPage` next to `targetQuery`, at every call site. A filter change resets `offset` to 0 and uses the existing abort and `requestSequence` guards.
- **`renderUsers`** (`ui.js:767`): a checkbox column. Copy the Notification History precedent (`ui.js:3624-3632`, `3674-3680`; `handlers.js:219-260`, `620-628`):
  - the header "Select all rows on this page";
  - row checkboxes labelled with the account's email;
  - rows without a profile (`!has_profile`) are disabled, with a hint;
  - the header checkbox is tri-state: `checked` when every selectable row is ticked, `indeterminate` when only some are. Port `syncSelectAllCheckbox` (`handlers.js:250-261`); do not rewrite it.
- **Toolbar** (visible while anything is selected): "N selected", then a labelled destination tier select, a labelled optional reason field, and the submit button.
  - The button reads **"Move to {tier label}"** and follows the destination select. The verb and the target are both on the button, so an operator cannot click without seeing where the readers are going.
  - One hint line under the toolbar: "A reader is in one tier at a time — moving replaces their current tier. Personal allowances are kept." "Add readers" on the Tiers tab reads as additive, and this line corrects that where the action happens.
  - Move makes one `addTierMembers` call, then shows a toast with the moved, unchanged and missing counts.
  - It then reloads the page and calls `loadAudit`.
  - Selection clears after each successful render, on page, filter or search change.
  - **Focus after Move.** The toolbar hides when selection clears, and it held the focused button, so focus would drop to `<body>`. After the reload, move focus to `#people-tier-filter`. The Notification History bulk actions have the same gap (`handlers.js:396-426`); this plan does not fix that one.
- **Row-click-opens-account** (`handlers.js:1075-1079`) must ignore the checkbox and its cell.

### [HISTORICAL] Tiers tab — two entry points, no new card

- **`renderTiers`** (`ui.js:3449-3457`):
  - `member_count` becomes a `button type="button"` with `data-tier-action="members"`, with an accessible name such as "{count} readers in {label}";
  - add an "Add readers" row button, `data-tier-action="add"`.
- **One helper**, `openPeopleForTier(key, { filter })`, in `handlers.js`:
  1. click `#tab-people` (tab lazy-loaders hang off the button click; the precedent is the Overview goto at `handlers.js:1600-1615`);
  2. set the filter: `members` → that key; `add` → All, with the destination select preset to that key;
  3. trigger the reload;
  4. move focus to the filter (`members`) or the search box (`add`), so keyboard focus does not stay in the now-hidden Tiers panel.

  The People listeners are attached before the first await, so there is no initialisation race.

- Refusal text goes through `tierFailureMessage` (`handlers.js:1816`), which looks under `admin.tiers.*`.

### [HISTORICAL] Strings, versions, docs

- **i18n**, under the existing `admin.people.*` and `admin.tiers.*` only, in **both** `web/i18n/en.yaml` and `ar.yaml`:
  - filter label and "All tiers";
  - select-all and row-select labels;
  - selected count, destination label, reason label, Move;
  - moved/unchanged/missing summary, including "allowances are kept";
  - "no profile — cannot be moved";
  - the Readers-button and Add-readers labels;
  - `admin.tiers.invalid_member_batch`, `admin.tiers.invalid_tier`, and `admin.tiers.actor_no_longer_administrator` (which is missing from that namespace today; it exists under others, `en.yaml:647/693/807/869`).

  No new top-level namespace, and no new audit action: `user.tier_change` is already pinned (`ui.js:942`).

- **CSS**, only if needed, and logical properties only. Bump **`ASSET_VERSION`** (`web/api/app.py:379`).
- **Docs**, in the same commit:
  - `docs/ARCHITECTURE.md#reader-quota`: the bulk tier route and RPC, the rule that overrides are never touched, and the orphan rule (not in any tier filter, not selectable);
  - update the pinned orphan comment in `web/tests/test_admin_users.py:50`, because the list now reports `has_profile`.

## [HISTORICAL] Tests (each written to fail first)

- **SQL, `supabase/tests/rpc_behaviour.test.sql`.** This is the only real proof: the Python tests mock Supabase (`docs/ARCHITECTURE.md:780`). Cases:
  - **an existing override row is unchanged after the move**;
  - exactly one audit row per moved profile, and none for unchanged or missing ids;
  - duplicate ids are counted once;
  - a null, empty or 201-element array raises TQ009;
  - an unknown tier raises TQ002 and rolls back;
  - a null or non-admin actor raises AD004;
  - `admin_list_users(p_tier => 'staff')` excludes orphans and returns `has_profile`.
- **SQL, `function_acls.test.sql`:** the list entry.
- **`web/tests/test_admin_users.py`:**
  - `?tier=staff` returns only staff;
  - an orphan is absent under `?tier=free` but present under All, with `has_profile: false`;
  - a bad tier returns 422.
- **`web/tests/test_admin_tiers.py`** (members POST):
  - readers move, with audit rows;
  - unchanged and missing readers are counted;
  - an override survives, in the double;
  - malformed UUIDs, 0 ids, 201 ids, or a non-list return 400;
  - an unknown tier returns 409 `no_such_tier`;
  - a reader token returns 403, and an absent or demoted actor returns 409 `actor_no_longer_administrator`;
  - caches are evicted for moved ids only.
- **`web/tests/test_rpc_payloads.py`:** cases for `set_users_tier`, and for `list_users` with `p_tier`.
- **`web/tests/test_admin_browser.py`:**
  - The Readers button, activated **by keyboard**, lands on People. The outgoing request carries `tier=<key>`, and focus is on the filter.
  - "Add readers" presets the destination and focuses search.
  - With a delayed users response, the filter is still applied.
  - Checking a box sends no account-detail request.
  - Bulk Move sends **one** POST with deduplicated ids, and a stateful mock proves the count refreshes.
  - Selection clears on page or filter change.
  - Ticking one of several rows sets the header checkbox to `indeterminate`.
  - After a keyboard-driven Move, `#people-tier-filter` is focused (`expect(...).to_be_focused()`), not `<body>`.
  - The Move button's label follows the destination select.
  - A tier-catalogue failure still renders the list.
  - Add a `**/admin/api/tiers` route to the shared People fixture (`:916`).

## [HISTORICAL] Verification

1. `.venv/Scripts/python.exe -m pytest -m "not browser and not integration"` and `-m browser --browser chromium`.
2. `ruff check . && ruff format --check .`, `.venv/Scripts/python.exe -m mypy web`, `npm run lint`, and `pre-commit run --all-files`.
3. `FLASK_TESTING=true python web/api/app.py`, then drive `/admin`:
   - Readers count → filtered People;
   - Add readers → preset destination;
   - bulk-move two readers, and confirm the audit log.
4. Live DB, after applying the migrations:
   - run `supabase/tests/*.test.sql`;
   - move a test account into `staff` and back, and confirm the `user.tier_change` rows and that its `reader_quota_overrides` row is untouched.

## [HISTORICAL] Established practice (Antigravity survey, 2026-09-23)

Antigravity compared this plan with products and design systems. Its sources were not re-fetched in this session: treat them as leads, not verified citations.

- **Where membership is edited.** Most products offer two surfaces. Okta, Auth0, GitHub teams and Entra ID each have a bulk action on the user list **and** an "add members" picker inside the group ([Okta](https://help.okta.com/en-us/content/topics/users-groups-profiles/usgp-assign-group.htm), [Auth0](https://auth0.com/docs/manage-users/user-roles/assign-roles-to-users), [GitHub](https://docs.github.com/en/organizations/organizing-members-into-teams/adding-organization-members-to-a-team)). This plan deliberately keeps one surface and links to it from the tier. The survey judged that **a justified divergence** for a console this size.
- **Move, not add.** Where a user can belong to only one container, the verb is "Move" or "Change". Google Workspace does this for organizational units, as opposed to groups ([Google](https://support.google.com/a/answer/182449)). Tiers are one-per-reader, so the toolbar says **Move**, and the hint above explains it.
- **Page-scoped selection with a visible count; select-all spans only the page.** This is Carbon batch actions, PatternFly bulk select and NN/g table UX. It matches the plan.
- **Per-identity audit rows, bounded batches, partial results reported rather than aborting the batch.** These match the plan.
- **Adopted from the survey:** the tri-state header checkbox, focus recovery after Move, "Move to {tier}" on the button, and the one-tier-at-a-time hint.
- **Checked and not needed:** the survey asked for the result toast to be a live region. It already is: `#toast` has `role="alert" aria-live="assertive"` (`web/templates/admin.html:269`).
- **Declined:**
  - disabling the filtered tier in the destination select, because an unchanged move is already reported and costs nothing;
  - a confirmation prompt for large moves, because the button names the target and every move is audited and reversible;
  - cross-page "select all N";
  - undo;
  - a second picker inside Tiers.

## [HISTORICAL] Documentation checked (Context7, 2026-09-23)

- **PostgREST v14, functions** (`/websites/postgrest_en_v14`). Overloads are picked by the names of the arguments sent, and overloads that share argument names but differ in type are unsupported. If the old 3-arg `admin_list_users` ever existed alongside the new 4-arg one, a call carrying only the 3 old names would match both, because the 4th argument has a default. That confirms Migration 1 must **drop the old signature and create the new one in the same file**, never as two steps or as an added overload.
- **PostgREST v14, schema cache.** The cache reloads on `NOTIFY pgrst, 'reload schema'`, and a DDL event trigger sends that on `CREATE`/`ALTER FUNCTION` and on drops. After applying, confirm the reload the way the README says (call the new signature). If the old shape is still being served, run `notify pgrst, 'reload schema';` by hand. Do **not** put the notify inside the migration; the repo's migrations never do.
- **PostgREST v14, array arguments.** A function taking an array accepts a JSON array in the POST body (`{"arr": [1,2,3]}`). So `self._rpc("admin_set_users_tier", {"p_user_ids": [str, …]})` passes the list as-is, and Postgres casts the strings to `uuid[]`. A malformed string would fail that cast with SQLSTATE `22P02`, which is outside `_REFUSAL_CODES` and would surface as a 500. That is the concrete reason the route must reject any value that is not a UUID with a 400 **before** the RPC is called.
- **Playwright Python** (`/websites/playwright_dev_python`). Drive the keyboard path with `locator.press("Enter")`, which focuses the element and then presses. Assert the focus handoff with `expect(locator).to_be_focused()`, for example on `#people-tier-filter` after the Readers button, and on `#people-search` after Add readers. Assert on the outgoing `tier=` query with `page.expect_request`, not on the final DOM alone.

## [HISTORICAL] Review disposition

**Adopted, from both reviewers:**

- the drop+create with explicit revoke **and** grant;
- the TQ009 mapping (`invalid_member_batch`);
- UUID validation at the route (400 rather than 409);
- `moved_ids` so cache eviction can target moved readers only;
- attaching the People listeners before the first await;
- keyboard focus handoff between tabs;
- labelled controls, and email-named row checkboxes;
- no-op checkbox clicks (they don't open the account);
- clearing selection after render.

**Adopted from Codex only:**

- **Replace the Tiers-tab card with navigation into People.** This fits your "shortest, DRY" rule.
- Filter on the real `p.tier` and return `has_profile`, so the count and the list agree.
- `_require_admin_actor` in the new double, plus the list_tiers orphan-parity fix.
- SQL-level override-survival and AD004 tests.
- Load the tier catalogue independently of the list.
- The missing `admin.tiers.actor_no_longer_administrator` string.

**Rejected from OpenCode:**

- _"Make the double's `profile_tiers` sync conditional."_ The comment at `admin_store.py:963-967` explains why the existing quota path must be unconditional. In the new method only moved ids change, so the question does not arise.
- _"Change the quota PUT so an omitted override means 'leave alone'."_ That route requires every key on purpose (docstring `admin.py:1111-1118`), because a partial body would turn "not sent" into "delete".
- _"Cited line numbers are stale."_ I spot-checked them in this session and they are current; Codex independently called them "materially accurate".
- _"The user said two clicks is acceptable."_ You never said that.

## [HISTORICAL] Changes during implementation (2026-09-23)

- **Reversed: non-UUID ids are reported as `missing`, not refused with 400.**
  The plan put a UUID check in the route. That made the in-memory double's
  seeded accounts (`test-user-id`, …) unmovable in `?testing=true`, and it
  contradicted `_require_uuid`'s rule in `web/services/admin_store.py` that the
  uuid check belongs in the Supabase backend, where a non-uuid "identifies no
  account". The route now checks only the payload's shape (1–200 non-empty
  strings).
- **Reversed again, after the implementation review: the RPC sorts out the
  non-uuids, not Python.** The Python split above had two defects. `uuid.UUID`
  accepts forms Postgres rejects (`urn:uuid:…`, a leading `+`, non-ASCII
  digits), so one such id still failed the cast as a 500; and a batch with no
  uuid-shaped id skipped the RPC entirely, so a demoted actor or a deleted tier
  got 200. Migration `20260923194026` changes `p_user_ids` to `text[]`: every id
  reaches the function, the actor/batch/tier refusals run first, and a
  non-canonical id is reported in `missing` by the SQL itself. Valid ids are
  compared case-insensitively. `_is_uuid` in `admin_store.py` now accepts only
  the canonical form, which also hardens `_require_uuid` and `get_user`.
- **Added: the Tiers tab re-reads its counts after a Move.** The tab loads its
  table once; without this, "Add readers" → Move → back to Tiers showed the old
  Readers count.

## [HISTORICAL] Implementation review (2026-09-23)

Two read-only reviews of the built change: `/code-review` (Opus) and OpenCode
(Muse Spark 1.3, max effort). Every finding was re-checked against the code.

- **Fixed:** Move's double-submit guard re-enabled mid-flight; the non-uuid
  defects above; a Readers-count jump leaving an invisible, unclearable filter
  when the catalogue failed or lacked the tier (catalogue reads are now
  sequence-guarded); focus stolen from whatever the operator did next; the
  toolbar pushing the table down on the first tick (it is now always visible,
  per DESIGN.md "reserve a revealed control's space at rest", which also makes
  the catalogue-failure hint visible); a stale Tiers refresh discarding an open
  tier form; a single-account tier save not refreshing the Tiers counts;
  `list_users` sending `p_tier` when unfiltered (now omitted, so a schema-first
  rollback does not break People); double-vs-SQL gaps (unchanged ids now sync
  the quota double, `delete_tier` counts profile rows only); "1 readers" copy;
  four browser tests and one SQL assertion that could not fail; stale comments
  and ARCHITECTURE.md drift.
- **Rejected:** none of substance. OpenCode's "early return skips the actor
  check" was first judged harmless (nothing is written) and then fixed anyway
  by the `text[]` change, which removed the early return.
- **Lifted into `TODO.md`:** arrow-key tab activation never runs the lazy tab
  loaders; Notification History's post-action focus; the Overview's tier
  counts.
