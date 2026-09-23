---
authority: historical
status: superseded
do_not_implement: true
archived: 2026-09-24
supersedes_note: >
  A finished plan for three admin-console gaps found in the tier-membership review.
  Two reviews (OpenCode, Antigravity) reversed three parts of its first draft before any
  code was written. It records what was decided and what it cost; it is not a specification.
live_authority:
  - docs/ARCHITECTURE.md
  - TODO.md
---

> [!CAUTION]
> **You are reading history, not a specification.** Confirm anything here against the code.
> Final position, so no section has to be read in a special order:
>
> - **Activation is a click.** The tablist arrow keys call `tab.click()`, and `admin.js`
>   clicks Overview once at boot. No `init*Tab` checks whether its panel is already
>   showing.
> - **Tier counts:** `markTierCountsStale()` marks both Tiers and Overview stale. Tier
>   create, edit and delete mark Overview only.
> - **Notification History** never disables its status select. `setHistoryControlsDisabled`
>   records the focused element and hands focus back to it, or to the select.
> - **Reversed from the first draft:** the `onTabActivated` helper, the `tierCountViews` Set,
>   and the unconditional `recoverFocus(select)`, which stole focus on composer Send, a
>   cancelled confirm and Load more. Also reversed: the claim that automatic activation
>   met the APG latency condition.

# [HISTORICAL] Admin console: three gaps left by the tier-membership review

## [HISTORICAL] Context

The tier-membership review (2026-09-23) found three pre-existing gaps in
`static/js/admin/handlers.js`, all read in this session:

1. **Arrow keys never load a lazy tab.** The tablist `keydown` handler (`bindConsoleEvents`,
   ~line 118) calls `selectTab()` + `focusTab()`. Every lazy loader hangs off the tab
   button's `click` (Analytics ~1732, Overview ~1782, Tiers ~1844, Deletions ~1951), so
   arrowing onto Tiers shows an empty panel. The existing tests
   (`test_the_tablist_is_navigable_by_keyboard`, and the Activity test at ~line 464) assert
   visibility only, which is why they pass. The docstring's claim that "there is nothing to
   load" is also stale.
2. **Notification History drops focus to `<body>`.** `loadHistory` calls
   `setHistoryControlsDisabled(true)`, which disables the status select, Load more, Clear
   selected, Purge selected, Purge eligible and Clear all. Disabling the focused control
   loses focus. The bulk toolbar then hides once `selectedIds` is emptied. The same happens
   on every path that disables them: a bulk action, Clear all, Purge eligible, a cancelled
   confirm, a filter change and Load more.
3. **The Overview's per-tier counts never refresh.** `initOverviewTab` loads once. A Move
   (`moveSelected`) or a single-account tier save calls `markTiersStale`, which reaches the
   Tiers tab only.

Docs checked (Context7):

- **WAI-ARIA APG, Tabs Pattern.** Automatic activation (arrows activate) is recommended
  "provided that the associated tab panels are displayed without noticeable latency".
  Otherwise, manual activation (arrow moves focus, Enter/Space activates) is preferred.
- **Playwright Python.** `expect(locator).to_be_focused()` is the focus assertion.

## [HISTORICAL] Review round (2026-09-24)

Two read-only reviews, both briefed to judge by the DRY principle first:

- OpenCode (Muse Spark 1.3, max effort) returned **approve with changes**.
- Antigravity (Gemini 3.8 Flash High) returned **reject**.

Every point adopted below was checked against the code. They agreed on four things:

1. **The first draft's `onTabActivated` helper saved nothing.** It would add 5 lines to
   remove 8, and three of its four boot checks can never be true. `admin.js:49` selects
   Overview before any `init*` runs (`admin.js:82-90`), and the console is hidden until
   `revealConsole`, so no other tab can be selected at boot.
2. **The draft's `tierCountViews` Set was a pub/sub registry for two fixed tabs.** Two
   plain module pointers are enough. This matches `showPeopleForTier` and `markTiersStale`
   at `handlers.js:812-816`.
3. **The draft's single `recoverFocus` call in `setHistoryControlsDisabled(false)` stole
   focus.** Both reviewers found it; Antigravity's composer case was verified:
   - **Send:** `setNotificationComposerSending` disables `#notif-send` (`ui.js:2571`), so
     focus falls to `<body>`. The un-awaited `loadHistory()` then ends by re-enabling the
     history controls, and focus would have jumped to the status select.
   - **Cancelled confirm:** Clear all and Purge eligible disable their controls before
     `confirm()`, so a cancel would move focus to the select instead of back to the button.
   - **Load more:** focus would also jump from the bottom of the table to the top.
4. **The console already has a rule for this.** `setPeopleLoading` (`ui.js:765`) leaves its
   select enabled because "disabling a focused control drops focus", and
   `setAnalyticsLoading` does the same (`ui.js:776`). `setHistoryControlsDisabled` breaks
   that rule by disabling `#notification-history-status`.

Also adopted: the scope call is **yes**. Tier create, edit and delete stale the Overview too
(it shows the tier count, labels, limits and member counts). The draft's claim that the APG
latency condition was met "in spirit" is withdrawn (see Decisions). The tests must also
route `/admin/api/*`: under `?testing=true` the browser suite mocks every admin route, with a
stateful handler where counts must change (as at `test_admin_browser.py:2213-2263`).

Rejected: Antigravity's proposal to fix focus only at the two bulk-action call sites. It
leaves the cancelled-confirm and Load more paths broken. Also rejected: deduplicating the
four `loadOnce` guards and the two paginated id fetchers, which both reviewers suggested.
Each `loadOnce` has different retry semantics (Analytics keeps its result, Overview clears
only on total failure, Tiers and Deletions set the flag inside `reload`). A shared guard
would need a parameter per difference, and neither is part of these three bugs.

## [HISTORICAL] Decisions

- **Keep automatic activation (arrows activate), routed through `click()`.** The APG
  recommends it only when panels show "without noticeable latency". Tiers and Overview show
  an empty panel until their first fetch lands, so strictly this is the case where APG
  prefers manual activation. It stays automatic because that is the shipped, tested
  keyboard model, and each loader runs once and never blocks focus movement. This is a
  known compromise, not an APG claim.
- **Boot activation is one click, not four checks.** This deletes a mechanism instead of
  wrapping it.
- **Focus goes back to the control that had it, and to the status select only when that
  control is gone.** Nothing is recorded when focus was already on `<body>`, and
  `recoverFocus` never moves focus the operator placed elsewhere. A background reload
  therefore can never take it.

## [HISTORICAL] Changes

### [HISTORICAL] 1. The activation signal is a click

- `handlers.js` keydown handler (~line 137): replace `selectTab(target)` with
  `document.getElementById(target)?.click()`, keeping `focusTab(target)`. The tablist's
  click listener (~line 113) is then the only path that calls `selectTab`.
- Delete all four "already showing at boot" lines: Analytics ~1733, Overview ~1783, Tiers
  ~1846 and Deletions ~1953, plus the two "(a reload with this tab selected)" comments.
- `admin.js`: after the `init*` calls (~line 90), add one line:
  `document.getElementById('tab-overview')?.click();`. Keep the early
  `selectTab('tab-overview')` at line 49, which paints the chrome before auth. The click
  then runs Overview's loader through the same path a person uses, so moving the default
  tab stays a one-word change.
- Rewrite the `bindConsoleEvents` docstring, since "nothing to load" is false. Shorten the
  `openPeopleForTier` comment to point at it.

### [HISTORICAL] 2. Two stale pointers, one combiner

```js
/* Set by initTiersTab and initOverviewTab: each re-reads its tier counts on
   its next activation. */
let markTiersStale = null;
let markOverviewStale = null;
const markTierCountsStale = () => (markTiersStale?.(), markOverviewStale?.());
```

- `initOverviewTab` sets `markOverviewStale = () => { loaded = false; };`.
- The move (~1025) and the account tier save (~1566) call `markTierCountsStale()` instead
  of `markTiersStale?.()`.
- Tier create, edit and delete (~1876, ~1902-1906) call `markOverviewStale?.()` next to
  their existing `loadAudit(services)`. They do not call the combiner, because Tiers just
  re-rendered.
- **Accepted, not fixed:** Overview has no generation token, so marking it stale while its
  own load is in flight lets two loads race. The later one to land wins. At admin scale
  this is a redundant fetch at worst. The trigger needs a Move to finish during the brief
  Overview load. Not adding a token keeps the change small.

### [HISTORICAL] 3. Notification History focus: stop dropping it, then restore it

- Delete `if (select) select.disabled = disabled;` from `setHistoryControlsDisabled`
  (~line 294). This follows the `ui.js:765` rule. `historyGeneration` already makes a
  filter change during a load safe (`handlers.js:310`, `:324`).
- Hoist `recoverFocus` from `initPeopleTab` (~1002) to module scope, unchanged, so People
  and Notifications share it.
- In `setHistoryControlsDisabled`, keep a closure variable `returnTo`:

  ```js
  if (disabled) {
    const active = document.activeElement;
    returnTo ??= active && active !== document.body ? active : null;
  } else if (returnTo) {
    recoverFocus(returnTo.isConnected && returnTo.checkVisibility() ? returnTo : select);
    returnTo = null;
  }
  ```

  `select` is the status select that the function already looks up. The composer and the
  history table are siblings in `#notifications-body` (`ui.js:3725-3756`), and no element
  wraps just the history section, so the snippet does not test where focus is. Two rules
  cover that instead:
  - `??=` keeps the first element recorded. A bulk action disables the controls and then
    `loadHistory` disables them again, by which point focus is already on `<body>`; the
    button must not be overwritten.
  - `recoverFocus` only acts when focus is on `<body>`, so it never takes focus from
    somewhere the operator moved to.

  This one site covers the paths below.

  | Path              | What happens                                                                                                                                                                                       |
  | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
  | Bulk actions      | The toolbar hides, so focus goes to the select.                                                                                                                                                    |
  | Cancelled confirm | Focus goes back to the button.                                                                                                                                                                     |
  | Load more         | Focus stays on the button, or goes to the select if the button is now hidden.                                                                                                                      |
  | Row actions       | The row is rebuilt, so focus goes to the select.                                                                                                                                                   |
  | Composer send     | Clicking Send disables the button, so focus is on `<body>`. `returnTo` is `null` and nothing is restored. If Enter was pressed in an input, the input keeps focus and `recoverFocus` does nothing. |

## [HISTORICAL] Tests (`web/tests/test_admin_browser.py`), each shown to fail against the current code first

Every test routes its `/admin/api/*` calls. Focus assertions use
`expect(...).to_be_focused()`, which retries, rather than a one-shot `evaluate`.

1. **Arrowing onto Tiers loads it.** Route `/admin/api/tiers` with `TIERS_RESPONSE`
   (~line 964). From `#tab-overview`, press End and ArrowLeft until `#tab-tiers` is focused,
   then expect a tier label in `#tiers-body`.
2. **The Overview re-reads after a Move.** A stateful tiers route returns `member_count` +1
   after the POST to `…/members`, reusing the recorder at ~2213. Load Overview, move a
   reader, click `#tab-overview`, and expect the new count. Add the same assertion for tier
   create.
3. **Notification History focus.** Four cases:
   - (a) Clear selected then accept: the status select is focused.
   - (b) Clear all then dismiss: `#notification-history-clear-all` is focused.
   - (c) Change the status filter: the select stays focused.
   - (d) Composer Send: focus is **not** on the status select. This guards the
     regression both reviewers found.
4. The existing keyboard tests stay unchanged and must pass.

Fail-first uses the `failfirst.py` break/restore pattern.

## [HISTORICAL] Housekeeping (same commit)

- Bump `ASSET_VERSION` in `web/api/app.py`. No i18n keys.
- `TODO.md`: move the entry and its index line to `docs/archive/TODO-resolved.md`.
- `docs/ARCHITECTURE.md` has no text on tab activation or these hooks. Re-grep before
  committing.
- Archive this plan via the five-step procedure once it is built. Its reversals are the
  `onTabActivated` helper, the `Set`, and the unconditional focus call.

## [HISTORICAL] Gates

```bash
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m mypy web
npm run lint && npx prettier --check static/js && npm run lint:md
.venv/Scripts/python.exe -m pytest -m "not browser and not integration"
.venv/Scripts/python.exe -m pytest web/tests/test_admin_browser.py web/tests/test_admin_info_popups_browser.py --browser chromium
```

## [HISTORICAL] Size

Estimated net change in production JS is about −3 lines:

- `handlers.js`, removed about 11: four boot lines, their two comments, `select.disabled`,
  and duplicate comment text.
- `handlers.js`, added about 9: the stale pointers and combiner, the tier-save calls, and
  `returnTo`.
- `admin.js`: +1.

The first draft's "−5" did not survive review. Its helper and `Set` cost more than they
removed. Most of the diff is the new tests.

## [HISTORICAL] Implementation (2026-09-24)

Implemented by Antigravity (Gemini 3.8 Flash High). The orchestrator then reviewed the
diff, re-ran the gates, and proved every test fail-first.

- **Production code followed the plan.** The one deviation was the right call:
  `recoverFocus` runs after the controls are re-enabled, because a disabled button cannot
  take focus.
- **Tests were rewritten for DRY.** The delegate's 402 lines copied the notification-row
  dict four times and the tier list twice. The final version reuses `_admin_console`,
  `_open_people`, `_members_route`, `TIERS_RESPONSE`, `_bulk_row` and
  `_route_bulk_history`:
  - Two Notification History cases became single assertions in existing tests: Clear
    selected, and composer Send.
  - The focus tests moved to `test_notifications_browser.py`, next to those helpers.
- **The filter-focus test first passed against the broken code.** Focus recovery masked
  the disabled select, because focus returned once the reload landed. It now holds the
  history response and asserts focus while the reload is still in flight.
- **Fail-first:** seven break/restore pairs.
  - Arrow click, the Move re-read, the tier-save re-read, the enabled select, focus
    restore and the boot click each fail with their fix removed.
  - The draft's unconditional `recoverFocus(select)` fails the composer-Send assertion.
