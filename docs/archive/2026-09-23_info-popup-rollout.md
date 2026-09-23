---
authority: historical
status: superseded
do_not_implement: true
archived: 2026-09-23
supersedes_note: >
  A finished plan, built on 2026-09-23 in one commit after two adversarial reviews: one of the
  plan (§9) and one of the implementation (§11). It reversed the Analytics-only scope of
  DESIGN.md's standing-context rule, eight visible hint paragraphs, and the popup geometry
  shipped in fd516a5. It records what was decided and what it cost; it is not a specification.
live_authority:
  - DESIGN.md
  - TODO.md
---

> [!CAUTION]
> **You are reading history, not a specification.** The live rule is `DESIGN.md`'s "Standing
> context may hide; a state may not"; read that, not this. Final position, so no section has
> to be read in a special order:
>
> - **12 triggers** in the console: Analytics' 4, 5 zone-level and 3 panel-level.
>   `noPasswordHint` stays **visible** (§9 reversed the first draft).
> - **`panelInfo(row)`** reads its key from `data-info` on `.admin-heading-row` (§10 reversed
>   §3.1's `panelInfo(panel, text)`).
> - **Geometry:** a `--space-4` gutter, a 12rem minimum width, and a flip to the button's other
>   side (§11 reversed §10's "a gutter is a separate decision").
> - **Coarse-pointer 44px hit area (§5.2):** not adopted. The 28px target meets WCAG 2.5.8.
> - **Still open, lifted into `TODO.md`:** the NVDA and JAWS check, and the seven
>   never-rendered console strings (§4.1).
>
> Every `file:line` describes the tree at `31b0302`, before the build. Every heading is
> prefixed `[HISTORICAL]`.

# [HISTORICAL] Rolling out the "i" popup beyond Analytics

The Analytics tab moved its standing context behind an "i" (`fd516a5`). This plan is about
taking that pattern to the rest of the admin console, the chat page, the landing page and
`/account`, without ending up with a second implementation or hiding anything a reader needs.

**What the audit found.** The request assumed things that are not in this app. There is no
pricing, billing, integrations or model-settings surface for readers, and no FAQ section on
the landing page ("FAQ" is the sidebar's list of preset questions). On the surfaces that do
exist, the governing rule — **standing context may hide; a state may not** (`DESIGN.md`, the
paragraph of that name) — keeps almost all reader-facing text visible. It also agrees with
the outside guidance (§8):

- **Admin console:** 8 new triggers, 1 hint deleted, and 1 hint's content moved into its
  confirm dialog.
- **Chat, landing, `/account`, `/privacy`:** no triggers. Every string on those pages is
  either a state, a field requirement, a privacy or consent disclosure, the independence
  notice (PRODUCT.md Principle 2), or marketing copy that exists to be read.

So the component **stays in the console**. It gets promoted to a shared module only when a
reader surface has a real candidate (§3.3).

---

## [HISTORICAL] 1. The pattern as shipped (the reference implementation)

| Piece                                 | Where                                                      | What it does                                                                                                                                                                                                                                                       |
| ------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `infoPopup(text, topic)`              | `static/js/admin/ui.js:1510`                               | Returns `[button, span]`. The span is `popover="auto"` with id `admin-info-N`. The button carries `popovertarget` and `aria-label` = `admin.analytics.about` ("About {topic}"), and each is paired to the other through an inline `anchor-name`/`position-anchor`. |
| `section(title, info)`                | `static/js/admin/ui.js:1368`                               | A zone `h2`. When `info` is passed, the trigger goes right after the heading, inside `.admin-section-head`.                                                                                                                                                        |
| `.admin-info-btn` / `.admin-info-pop` | `static/css/admin.css:1354-1403`                           | A 28px ghost circle and the popover's styling. Placement is `position-area: block-end span-inline-end`, which flips to stay in the viewport. It is gated on `@supports (position-area: block-end)`; without anchor positioning the browser centres the popover.    |
| Rules                                 | `DESIGN.md` → "Standing context may hide; a state may not" | What may hide. The trigger goes only after a heading or a notice lead: never in a cell, never one per tile. Use "i", not "?". Names follow `About {topic}`.                                                                                                        |
| Tests                                 | `web/tests/test_admin_analytics_browser.py:1525-1640`      | Checks the contract (named, unique, targets resolve, text matches, hidden by default, states stay visible), Esc and focus return, and geometry at 390px in Arabic including the flip.                                                                              |
| AT check                              | `docs/archive/TODO-resolved.md` (closed 2026-09-23)        | Tested with VoiceOver on macOS: the popup text is read right after "expanded", so no `aria-describedby` is needed. **NVDA and JAWS have not been checked.**                                                                                                        |

The browser handles the interaction itself: toggle, Esc, light dismiss, focus return,
expanded state, and top-layer stacking (so no clipping and no z-index problems). Nothing in
this plan adds JavaScript for any of that. The expanded state lives in the **accessibility
tree, not the DOM**. On Chromium 148 a `<button popovertarget>` has no `aria-expanded`
attribute, but CDP `Accessibility.getFullAXTree` reports `expanded: false`, then `true` after
a click (probed 2026-09-23). That is why a DOM-attribute assertion would fail, and why §7
asserts it through CDP instead.

---

## [HISTORICAL] 2. Decision rule for every candidate string

Before the popup is used anywhere, a string has to pass all four questions. One "no" keeps
it visible.

1. **Is it standing context?** Where data comes from, what a term means, how a figure is
   counted, why a rule exists. Not a state, error, empty or loading line, field requirement,
   or live warning.
2. **Would the reader act the same without reading it?** If skipping it changes what they do
   next, such as a consequence shown right before a destructive click, it stays.
3. **Is it not a disclosure?** Privacy, consent and independence text, and anything
   PRODUCT.md Principle 2 requires, is never hidden.
4. **Is there a heading or notice lead to hang it on?** If not, there is nowhere to put a
   trigger, so the copy is kept, rewritten, or deleted.

A string that fails question 1 because it only repeats what the UI already shows gets
**deleted**, not hidden. An "i" in front of redundant copy still costs a click and a tab stop.

---

## [HISTORICAL] 3. Component architecture

### [HISTORICAL] 3.1 Keep one producer and generalize it in place

`infoPopup` is already the lean component the request asks for: two arguments, no options
object, no state, and no event listeners. Changes:

- **Rename the name key** from `admin.analytics.about` to `admin.about`. It will be used
  across the whole console, and `runtime.admin.*` is an existing namespace, so the pinned
  list of eleven top-level names is not affected (CLAUDE.md rule 3). Update both catalogues
  and the one test that reads the old key (`_admin_catalogue("en")["analytics"]["about"]`).
- **Add one sibling helper, `panelInfo(panel, text)`**, for the three tabs whose explanation
  belongs to the panel's `h1` rather than to a zone heading (§4). The `h1`s are server-rendered
  (`web/templates/admin.html:172-247`), and a button _inside_ an `h1` would become part of
  the heading's accessible name. So:
  - In the template, wrap those three `h1`s in `<div class="admin-heading-row">`, a flex row
    like `.admin-section-head`.
  - Add a `.admin-heading-row` rule to `admin.css` in the same commit.
    `test_css_contract.py` fails any `admin-*` class that has no stylesheet rule.
  - `panelInfo` appends `infoPopup(text, h1.textContent)` to that row **once, at console
    init**. The row is a sibling of `#…-body`, and repaints clear only the body
    (`ui.js:1005`, `:1091`, `:3424`), so repainting cannot duplicate the trigger. What would
    duplicate it is init running twice, so `panelInfo` returns early if the row already
    holds an `.admin-info-btn`. A language switch reloads the page
    (`static/js/modules/i18n.js:70`), so topics never go stale.
- **No Jinja macro.** A second, server-side producer of the same markup is exactly the drift
  that `DESIGN.md` warns against. The single server-rendered hint (`page.admin.tiersHint`,
  `admin.html:217`) moves to `runtime.admin.tiers.hint`, so JavaScript draws it like every
  other hint.

The prop interface stays minimal: `text` (plain string) and `topic` (visible text of the
thing it explains). There is no rich-content slot, on purpose (§5.3).

### [HISTORICAL] 3.2 Features from the request this plan does not build

| Asked for              | Decision        | Why                                                                                                                                                                                                                                                                                                  |
| ---------------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Hover trigger mode     | **No**          | Touch has no hover. WCAG 1.4.13 requires content to be dismissible, hoverable and persistent, and hover popups fail that easily. `interestfor` and `popover="hint"` are Chromium-only per the research pass (§8). A second mode would also be a second code path for no reader gain.                 |
| JS collision detection | **No**          | `position-try-fallbacks: flip-block, flip-inline, flip-block flip-inline` already does it in CSS, and the 390px Arabic test proves the flip. Where anchor positioning is missing, the browser centres the popover, which is in-viewport by definition.                                               |
| Rich content / links   | **No, for now** | A `popover="auto"` span with plain text reads correctly as the next thing after "expanded" (VoiceOver-verified). Links would need `role="dialog"`, a label and tab-order work. Do that the day a candidate actually needs a link (§5.3).                                                             |
| Typing definitions     | **JSDoc only**  | There is no TypeScript and no bundler (CLAUDE.md). The existing doc comment on `infoPopup` is the type surface; add `@param {string} text` / `@param {string} topic` / `@returns {[HTMLButtonElement, HTMLSpanElement]}`. `mypy` does not cover JavaScript, and eslint already runs on `static/js/`. |
| Tailwind               | **N/A**         | The app uses no Tailwind. Tokens are CSS custom properties in `static/css/tokens.css`, which the component already uses (`--fg-muted`, `--signal`, `--bg-sunken`, `--radius-*`, `--shadow-md`, `--fs-200`).                                                                                          |

### [HISTORICAL] 3.3 Promotion trigger: when a reader surface needs it

Promote only when §2 approves the first reader-surface candidate. The steps are known now, so
nobody improvises them later:

1. Move `infoPopup` to `static/js/modules/info-popup.js` and export it. `admin/ui.js`
   imports it the way it already imports `../modules/icons.js`. A generic module in
   `modules/` is allowed on the landing page's import map; the security rule is about
   **console** filenames (`docs/ARCHITECTURE.md`, "The import map…").
2. Move `.admin-info-btn`/`.admin-info-pop` into `static/css/components.css` (loaded by
   every page) as `.info-btn`/`.info-pop`.
3. Add `info` to `RUNTIME_ICON_NAMES` (`web/utils/icons.py:440`); today it is only in
   `ADMIN_RUNTIME_ICON_NAMES`, so `iconMarkup('info')` returns `''` on reader pages.
4. Move the name key to a runtime namespace that reader pages receive, since
   `runtime.admin` is withheld from them (`web/utils/i18n.py:135`).
5. Restart the server, because module filenames are enumerated at import (`web/api/app.py:411`).

---

## [HISTORICAL] 4. Inventory: surface by surface

Kinds: **SC** standing context · **ST** state/empty/error · **FR** field requirement ·
**CQ** consequence of an action · **DI** disclosure (privacy, consent, independence, legal) ·
**MK** marketing copy. Line numbers are as of `31b0302`.

### [HISTORICAL] 4.1 Admin console

| Tab                         | String (key)                                            | Rendered at              | Kind                 | Decision                                                                                                                                                                                                                                                               |
| --------------------------- | ------------------------------------------------------- | ------------------------ | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Overview                    | none                                                    | —                        | —                    | Nothing to do. The tile labels are self-describing by rule.                                                                                                                                                                                                            |
| Settings › Registrations    | `admin.registrations.hint`                              | `ui.js:128`              | SC                   | **"i"** via `section('admin.registrations.heading', hint)` at `ui.js:124`. The confirm dialog (`confirmPause`) already restates the only consequence.                                                                                                                  |
| Settings › Registrations    | `admin.registrations.bypassHeading`/`bypassNote`        | `ui.js:140-143`          | CQ (security caveat) | **Keep.** It is an `.admin-notice` stating a limit the operator must not assume away.                                                                                                                                                                                  |
| Settings › Generation       | `admin.settings.hint`                                   | `ui.js:314`              | SC                   | **"i"** via `section('admin.settings.heading', hint)` at `ui.js:301`.                                                                                                                                                                                                  |
| Settings › Generation       | `admin.settings.notLive`                                | `ui.js:325`              | ST                   | **Keep.**                                                                                                                                                                                                                                                              |
| Users (list)                | `admin.people.hint`                                     | `ui.js:791`              | SC + CQ              | **Split.** "Accounts on this instance" repeats the tab name, so **delete** it. The consequence sentence moves into `admin.people.confirmDisable` (`en.yaml:681`, which today says only "Disable chat access for {email}?"), where it is read at the moment it matters. |
| Users › account › Profile   | `admin.account.profileHint`                             | `ui.js:2069`             | SC                   | **"i"** on the Profile zone (`ui.js:1865`).                                                                                                                                                                                                                            |
| Users › account › Allowance | `admin.account.quotaHint`                               | `ui.js:1677`             | SC                   | **"i"** on the Allowance zone (`ui.js:1875`).                                                                                                                                                                                                                          |
| Users › account › Allowance | `overrideHint`, `overrideWindowHint`, `quotaReasonHint` | `ui.js:1635, 1656, 1667` | FR                   | **Keep.** They are needed to fill in the form correctly.                                                                                                                                                                                                               |
| Users › account › Actions   | `admin.account.noPasswordHint`                          | `ui.js:1943`             | CQ                   | **Keep** (changed in review, §9). It tells the operator why there is no set-password control and what to do instead, so skipping it changes their next move.                                                                                                           |
| Users › account             | `brokenHeading`/`brokenBody`                            | `ui.js:1793`             | ST                   | **Keep.**                                                                                                                                                                                                                                                              |
| Tiers (panel)               | `page.admin.tiersHint`                                  | `admin.html:217`         | SC                   | **"i"** via `panelInfo` on the Tiers `h1`. The key moves to `runtime.admin.tiers.hint`.                                                                                                                                                                                |
| Tiers › editor              | `admin.tiers.labelsHint`                                | `ui.js:3533`             | SC                   | **"i"** on the editor zone (`ui.js:3502`).                                                                                                                                                                                                                             |
| Tiers › editor              | `admin.tiers.keyHint`                                   | `ui.js:3534`             | CQ + FR              | **Keep.** "The key is permanent" has to be seen while typing it.                                                                                                                                                                                                       |
| Deletions (panel)           | `admin.deletions.hint`                                  | `ui.js:1093`             | SC                   | **"i"** via `panelInfo`. `confirmReconcile` states the consequence, and terminal rows get no Reconcile button (`ui.js:1161`).                                                                                                                                          |
| Activity (panel)            | `admin.audit.hint`                                      | `ui.js:1007`             | SC                   | **"i"** via `panelInfo`.                                                                                                                                                                                                                                               |
| Notifications › Composer    | `admin.notifications.hint`                              | `ui.js:2248`             | redundant            | **Delete.** The type `<select>` shows the three delivery kinds this sentence lists.                                                                                                                                                                                    |
| Every tab                   | `.admin-empty` states, toasts, `window.confirm` text    | many                     | ST / CQ              | **Keep.** A state never hides.                                                                                                                                                                                                                                         |

**Totals:** 8 new triggers: 5 zone-level (Registrations, Generation, Profile, Allowance,
Tier editor) and 3 panel-level (Tiers, Deletions, Activity). With Analytics' 4, that makes 12
triggers in the console. The plan deletes 2 hint strings (people, notifications) and rewrites
1 confirm string.

**Found while auditing (not in scope; each render path must be re-traced before acting, and
any deletion is its own commit, not part of a rollout phase):**
`admin.audit.heading`, `admin.notifications.heading`,
`admin.notifications.composer.reviewHeading`/`resendFrom`, `admin.signedInAs`,
`admin.roleLabel` and `admin.settings.reasoningNotSupported` are never rendered.
`admin.account.absentHeading` is reachable only through dead code (`absentEntries` is always
`[]`, `ui.js:1953-1970`).

### [HISTORICAL] 4.2 Chat page (`index.html` + `static/js/modules/`)

| String                                                                  | Kind             | Decision                                                                                                                                                                                                         |
| ----------------------------------------------------------------------- | ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Welcome intro and bullets (`page.chat.*`, `index.html:643-650`)         | ST (empty state) | Keep                                                                                                                                                                                                             |
| `page.chat.cutoff` knowledge-cutoff notice (`index.html:651`)           | DI               | Keep. Provenance is the product (Principle 1).                                                                                                                                                                   |
| `runtime.chat.historyNotice` + `historyNoticeWarning` (`ui.js:874-878`) | DI               | Keep. The warning is the "do not enter patient identifiers" instruction.                                                                                                                                         |
| `runtime.chat.quota.*` counter and notice                               | ST               | Keep                                                                                                                                                                                                             |
| Stage lines, stream notes (`stopped`/`truncated`/`incomplete`)          | ST               | Keep                                                                                                                                                                                                             |
| `runtime.cite.datedNote` in the source panel                            | DI               | Keep. It qualifies the citations beside it.                                                                                                                                                                      |
| `runtime.cite.diagnosticsNote`                                          | SC               | **Keep as is.** It is already inside the collapsed "Retrieval diagnostics" disclosure and appears exactly when the figures it qualifies appear. Hiding it a second time would split the caveat from the numbers. |
| `account-disabled-notice`, session list states, FAQ empty               | ST               | Keep                                                                                                                                                                                                             |

**Result: no triggers.** There are no model settings, prompt helpers or session-control
explanations on the chat page. The scope dropdown ("Search in:") has no explanatory text, and
writing some is new copy, not a migration. If it is ever wanted, it goes through §2 and
§3.3.

### [HISTORICAL] 4.3 Landing page and auth modal

| String                                                            | Kind             | Decision                                                                                            |
| ----------------------------------------------------------------- | ---------------- | --------------------------------------------------------------------------------------------------- |
| Hero (`page.landing.lead`, `cta`, greeting)                       | MK               | Keep                                                                                                |
| Five feature cards (`page.features.*`, `index.html:437-467`)      | MK               | **Keep.** An icon-gated feature card is the textbook over-use mistake (§8). The body _is_ the card. |
| `page.features.coverage.badge` ("current through August 2026")    | DI               | Keep                                                                                                |
| `page.landing.notice` independence notice (`index.html:477, 557`) | DI               | **Never hide** (Principle 2; the key's own YAML comment says "Not optional copy").                  |
| `page.auth.passwordHint` (`index.html:295, 532`)                  | FR               | Keep. It is also `aria-describedby` for the input.                                                  |
| `page.auth.consent.ageHint`, `consent.marketing`, `consent.terms` | DI               | Keep                                                                                                |
| `page.auth.reset.lead`, `recovery.lead`, `signupPaused.*`         | ST / instruction | Keep                                                                                                |

**Result: no triggers.** There are no pricing tiers, technical specs or FAQ on the landing
page.

### [HISTORICAL] 4.4 `/account` and `/privacy`

- Everything under Security, Data and Delete-your-account is FR, CQ or DI. That covers
  `passwordHint`, `signOutOthersHint`, `deleteAllHint`, `deletionLead`, `deletionGoes/StaysBody`,
  `deletionPasswordHint` (also `aria-describedby`), `ageHint`, `logoutScope` and the
  independence notice. **Keep all of them.** Putting an "i" next to fields in a destructive
  form is two anti-patterns at once: a trigger beside every field, and friction in a
  high-stakes flow.
- The Role, Tier, Daily-questions and Standing `<dl>` (`account.html:141-166`) has **no**
  explanatory text today. Explaining "tier" there would be the first real reader candidate,
  and it would trigger §3.3. It is new copy, so it is out of scope.
- `/privacy` is a legal page and is all DI. **No triggers.**

---

## [HISTORICAL] 5. Accessibility and interaction contract

These apply to every trigger, and the tests in §7 enforce them.

### [HISTORICAL] 5.1 What is already met and must not regress

- The trigger is a native `<button type="button">`. Tab reaches it, and Enter/Space toggle
  it. Toggle, Esc, light dismiss (including tapping outside on touch), focus return and
  `aria-expanded` come from the browser.
- `popover="auto"` means only one popup is open at a time: opening one closes the others.
- The accessible name is `About {topic}`, where the topic is the visible heading or notice
  lead. Names are unique per page (asserted). The icon SVG is `aria-hidden` through
  `iconElement`.
- The popover span comes **immediately after** its button in the DOM, which is what makes
  the VoiceOver read-out work. Never move it to the end of `<body>`.
- Target size: 28px against WCAG 2.5.8's 24px minimum. Popovers use the top layer, so no
  `overflow` ancestor can clip them.
- RTL: only logical placement (`block-end span-inline-end`, `flip-inline`), no physical
  properties (`test_css_contract.py`).
- The trigger is never inside a `<label>`, `<summary>`, table cell or tile.

### [HISTORICAL] 5.2 Additions in this rollout

- **NVDA + Firefox and JAWS + Chrome check.** Only VoiceOver has been verified. Add a
  `TODO.md` entry in Phase 1 and close it with the result. If either reader does not
  announce the text after "expanded", the fix is one `aria-describedby` in `infoPopup`
  (recorded in the archived entry). Do not add it before then, because it would make
  VoiceOver announce the text twice.
- **Coarse-pointer hit area (optional; decide in Phase 1).** The research recommends a 44px
  hit area. The 28px size was a deliberate `DESIGN.md` decision (a louder control would
  out-shout the 12px heading), and the minimum is already met. If adopted, apply it only
  under `@media (pointer: coarse)` with a `::before { inset: -8px }` so the visual size is
  unchanged, and check it does not overlap the next control in a `.admin-section-head`.
- **Panel focus order.** A `panelInfo` trigger sits between the tabpanel and the panel body in
  tab order. That is intended: the explanation comes before the content. Assert it once.

### [HISTORICAL] 5.3 The rule for rich content, recorded now

If a future popup needs a link or any control, the popover gets `role="dialog"` and
`aria-label` = the topic. It stays `popover="auto"` (non-modal, so no focus trap), and
content can be reached by Tab after opening. It must **not** use `aria-describedby`, which
flattens links to text. Plain-text popups stay role-less, as they are today.

---

## [HISTORICAL] 6. Phased rollout

Each phase is one commit, bumps `ASSET_VERSION` (CLAUDE.md rule 1), ships every string in
`en.yaml` and `ar.yaml` (rule 2), and leaves the suite green. Write each new test first and
watch it fail against the previous commit.

**Phase 0: generalize and change no behaviour.**

- Rename `admin.analytics.about` to `admin.about` in both catalogues and in the test that
  reads it.
- Add the JSDoc types to `infoPopup`.
- Update `DESIGN.md`'s paragraph to name the rule "console-wide". §2's four-question test
  is condensed there in two sentences, not copied in full.
- Fix `docs/ARCHITECTURE.md:229` and `:536`, which say every page inlines the _whole_
  `runtime.*` tree. `runtime.admin` is withheld from reader pages (`web/utils/i18n.py:135`).
- Gate: the Analytics tests still pass unchanged apart from the key path.

**Phase 1: zone-level triggers (5).**

- Pass `info` to the five `section()` calls in §4.1 and delete the five hint paragraphs they
  replace.
- Add the `TODO.md` entry for NVDA/JAWS.
- New tests are listed in §7.

**Phase 2: panel-level triggers (3) and copy moves.**

- Add the `.admin-heading-row` wrapper and its CSS rule for Tiers, Deletions and Activity.
  Add `panelInfo` (idempotent, §3.1), called once from console init.
- Move `page.admin.tiersHint` to `runtime.admin.tiers.hint`.
- Delete `admin.people.hint` and `admin.notifications.hint`, and extend
  `admin.people.confirmDisable` with the consequence sentence in both languages. **That
  rewrite is reader-facing copy, so read `docs/PRODUCT.md` first.** The Arabic has to be
  written, not machine-translated, and checked by code point (see the
  arabic-from-a-terminal memory).

**Phase 3: closeout.**

- Run the AT check and close the `TODO.md` entry.
- Archive this plan per `docs/archive/README.md` (lift open items, `git mv`, banner, index
  row).

There is no reader-surface phase. §3.3 is the recorded procedure for when one is needed.

**Browser floor.** The `popover` attribute is required; without it the trigger does nothing.
That is accepted, not polyfilled. The console already needs a current evergreen browser, and
popover support predates anchor positioning, which is itself gated in CSS.

**Rollback.** Each phase reverts cleanly on its own. No phase touches the schema, the server
routes or the reader pages.

---

## [HISTORICAL] 7. Verification

Extend the existing geometry-and-contract approach rather than adding pixel snapshots. The
suite has no screenshot baselines (`grep to_have_screenshot web/tests` returns nothing), and
font rendering differs between CI and dev machines. That is why the 390px Arabic test asserts
bounding boxes instead.

1. **One console-wide contract test.** Widen `_info_triggers` to every `.admin-info-btn`
   under `#admin-console` and parametrize the Analytics contract assertions over every tab
   (a `browser` marker, so CI runs it). For each tab it checks:
   - the expected trigger count;
   - `aria-label` unique across the whole console;
   - `popovertarget` resolves to the **next sibling**, which has `popover="auto"` and the
     exact catalogue text. Adjacency is asserted because the VoiceOver read-out depends on
     it (§5.1), not for tidiness;
   - hidden by default;
   - no trigger inside `label`, `summary`, `td`, `th` or `h1`/`h2`.
2. **States stay visible, exhaustively.** Pinning one sample string per tab passes vacuously
   the day a different hint migrates. Instead, collect every `.admin-form-hint`,
   `.admin-account-hint` and `.admin-notice` rendered on each tab and assert that the set
   equals a named allowlist of kept keys (§4.1 "Keep" rows). A new hint then has to be
   classified before the suite goes green.
3. **Interaction, asserted once per mechanism.** Click opens, Esc closes and returns focus,
   opening a second trigger closes the first (`:popover-open` count is 1), and tapping outside
   closes it. The expanded state is read through a CDP session
   (`Accessibility.getFullAXTree`, `expanded` false→true), not from the DOM attribute (§1).
   One test covers `section()` and one covers `panelInfo`.
4. **Geometry.** At 390×844 in Arabic, and at 1280 in English: every trigger's popup is
   inside the viewport and edge-aligned to its button on the inline-start side. Include one
   forced flip at the bottom edge, as in
   `test_the_popup_sits_by_its_button_inside_the_viewport_at_390px_in_arabic`, and the longest
   new popup (`deletions.hint`) at 390px in Arabic.
5. **No duplicate trigger.** Activate Tiers, repaint its body (save or delete), and call
   console init's `panelInfo` pass a second time. Assert the heading row still holds exactly
   one trigger.
6. **The copy moves.** Assert that `confirmDisable` in both catalogues carries the
   consequence, that the confirm still comes before the reason prompt
   (`handlers.js:1217-1220`), and that the deleted keys are gone from both. The catalogue parity test
   (CLAUDE.md rule 2) covers the rest.
7. **Unchanged gates.** Run `python -m pytest -m "not browser and not integration"`,
   `python -m pytest -m browser --browser chromium`, `ruff`, `mypy web`,
   `npm run lint`, and `npm run lint:md` on this file and `DESIGN.md`.
8. **Manual checks.** Do a phone-width pass in both themes. Do NVDA and JAWS passes (§5.2).
   Tab through each tab and confirm the trigger falls where §5.2 says.

---

## [HISTORICAL] 8. External research

This was gathered by a delegated research pass (Antigravity, 2026-09-23), not by this plan's
author. **Verify a claim at its source before quoting it anywhere else.** Where it agrees with
the rules already in this repo, the repo rule is cited instead.

- **Do not hide:** field requirements, errors, legal or consent terms, and text most users
  need to finish a task. Toggletips are for optional definitions and methodology. Sources
  cited: NN/g tooltip guidelines (<https://www.nngroup.com/articles/tooltip-guidelines/>),
  GOV.UK hint text (<https://design-system.service.gov.uk/components/hint/>), and Heydon
  Pickering's tooltips and toggletips (<https://inclusive-components.design/tooltips-toggletips/>).
  This matches §2.
- **Native popover:** the browser provides top layer, light dismiss, Esc, focus return and
  expanded state. It does _not_ provide the trigger's name, a role for the popover, or an
  announcement of the content. Source: Hidde de Vries and Scott O'Hara on popover
  accessibility (<https://hidde.blog/popover-accessibility/>). This is consistent with the
  VoiceOver result; the announcement came from DOM adjacency.
- **Hover triggers:** the research recommends against them for info icons (touch, WCAG
  1.4.13, magnifier users). It reports `popover="hint"` and `interestfor` as Chromium-only
  in 2026. Source: W3C Understanding 1.4.13
  (<https://www.w3.org/WAI/WCAG21/Understanding/content-on-hover-or-focus.html>).
- **Anchor positioning:** the research reports it as Baseline across current engines in 2026,
  with logical `position-area` keywords that mirror in RTL without overrides. The repo's
  `@supports (position-area: block-end)` gate and centred fallback stay; its comment explains
  why the implicit anchor is not relied on.
- **Common mistakes named:** an "i" on every field or column; links inside tooltip-role
  content; generic repeated names ("More info"); triggers nested in `<label>` or `<summary>`;
  triggers on marketing cards; physical offsets in RTL; announcing the same text two or three
  times by stacking `aria-label`, visible text and `aria-describedby`.
- **Disagreement with repo rules, and the repo wins:** the research frames "?" as the help
  glyph. `DESIGN.md` uses "i" because the Arabic question mark is "؟" and "i" is symmetric.
  Keep "i".

---

## [HISTORICAL] 9. Review record

On 2026-09-23 an adversarial review (OpenCode, Muse Spark 1.3 at max effort, read-only) raised
eleven objections and returned "ship with changes". Each was checked against the code before
it was accepted or rejected.

| #   | Objection                                                                                     | Outcome                                                                                                                                                                                                                                                                                                                 | Evidence                                                       |
| --- | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| 1   | `infoPopup` exposes no expanded state; the "browser handles it" claim is unverified (blocker) | **Rejected, and the test gap accepted.** Chromium exposes `expanded` in the AX tree with no DOM attribute. No test asserted it, so §7.3 now does, through CDP.                                                                                                                                                          | CDP probe on Chromium 148 (§1)                                 |
| 2   | `noPasswordHint` changes the operator's next action                                           | **Accepted.** Moved to Keep; 8 triggers, not 9.                                                                                                                                                                                                                                                                         | `en.yaml:617`                                                  |
| 3   | `settings.hint` and `registrations.hint` carry timing the operator acts on                    | **Rejected.** The Open/Paused mark and the toast show that the change is live. `confirmPause` states the exemption for signed-in readers. "Streaming finishes on the old settings" changes nothing the operator can do.                                                                                                 | `ui.js:158-160`, `en.yaml:473`                                 |
| 4   | "Completed and cancelled rows need nothing" is a triage instruction                           | **Rejected.** The UI already says it: terminal rows have no Reconcile button.                                                                                                                                                                                                                                           | `ui.js:1161`                                                   |
| 5   | `panelInfo` is missing its CSS rule, and its duplication rationale is wrong                   | **Accepted (a, b).** The CSS step is now explicit and the rationale is corrected: repaints clear only the body, and the real risk, a double init, is guarded. **Rejected (c)**, keeping the three panel hints visible: they are pure standing context, and exempting them would make the rule inconsistent across tabs. | `ui.js:1005`, `:1091`, `:3424`; `test_css_contract.py:151-218` |
| 6   | Deleting `notifications.hint` loses "targeted"                                                | **Rejected.** The composer's audience controls and its "Reaches {count} accounts" preview state the targeting.                                                                                                                                                                                                          | `ui.js:2368-2407`                                              |
| 7   | "Accounts on this instance" scopes the list                                                   | **Rejected.** A single-instance console has nothing else it could be scoped to. The confirm-then-prompt order is now pinned (§7.6).                                                                                                                                                                                     | `handlers.js:1217-1220`                                        |
| 8   | Test gaps: vacuous state check, Arabic long string, no-JS, no-popover                         | **Accepted:** the exhaustive allowlist (§7.2), the Arabic long-string case (§7.4), and a recorded browser floor (§6). **Rejected:** no-JS, because the console cannot pass its identity gate without JavaScript.                                                                                                        | `admin.html:112-117`                                           |
| 9   | Line numbers off by one or two; do not bundle dead-key deletions                              | **Accepted.** Line numbers are corrected and the dead keys are split out of the phases.                                                                                                                                                                                                                                 | —                                                              |
| 10  | Coarse-pointer overlap check is misplaced                                                     | **No change.** It stays optional for Phase 1.                                                                                                                                                                                                                                                                           | —                                                              |
| 11  | A `<span>` popover depends on UA display internals                                            | **Rejected.** The UA popover rule's `position: fixed` blockifies the span, and it is a `span` so that it stays valid inside the floor notice's `<strong>`.                                                                                                                                                              | `ui.js:1505-1510`                                              |

---

## [HISTORICAL] 10. Build record

Phases 0–2 were built on 2026-09-23 as one working-tree change. Deviations from the text above:

- **`panelInfo(row)`, not `panelInfo(panel, text)`.** Each `.admin-heading-row` names its
  catalogue key in `data-info`, and `revealConsole` runs `panelInfo` over every row. No list of
  panels is kept in JavaScript.
- **`cardActions` lost its `note` argument.** `quotaHint` was its only caller.
- **Tests live in `web/tests/test_admin_info_popups_browser.py`** (29 cases). The first 27
  were written before the build: on `31b0302`, 22 fail and 5 pass. The 5 are views the change
  was never meant to affect. With the `panelInfo` guard removed, the duplicate-trigger test
  fails.
- **Two visible states that §4.1 does not list** are allowlisted there: the notification
  composer's audience preview and the Analytics "Counted at" stamp.
- **Geometry changed after review (§11).** The popup now keeps a `--space-4` gutter from the
  viewport edge and is at least 12rem wide; when that does not fit on its usual side it flips
  to the button's other side. Before, at 390px in English the `floorWhy` popup was 100px wide
  and 540px tall and touched the viewport edge. The console-wide geometry test now covers 390px
  in English as well, and it asserts the gutter, the minimum width and alignment with one of
  the button's two inline edges. It superseded
  `test_the_popup_sits_by_its_button_inside_the_viewport_at_390px_in_arabic`, which was
  deleted.

---

## [HISTORICAL] 11. Implementation review

On 2026-09-23 an adversarial review (Codex, `gpt-5.6-sol` at xhigh effort, read-only) returned
"ship with changes". It defended P1–P7 and P11: `data-info`, the idempotent `panelInfo`, the
heading-row CSS, removing `cardActions`' `note`, the `confirmDisable` copy, the two deletions,
the §2 classification, and the docs. It raised two objections, and both were accepted after
they were checked in the browser:

| Objection                                                                                                                     | Outcome                                                                                                                                                                                                                                                                                                                             | Evidence                                                                            |
| ----------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Popups at 390px touch the viewport edge, although the popup CSS already reserves `2 * --space-4` of gutter (major)            | **Accepted.** Fixed with an inline-end margin and a 12rem minimum width; `flip-inline` carries the margin to the other side. Measured at 390px in both languages: every popup sits between 16px and 374px across and is at least 192px wide. At 320px in Arabic a few popups fit on neither side and are shifted inside the gutter. | `admin.css`, the `@supports` block; the geometry test fails against `31b0302`'s CSS |
| §5.2's focus-order assertion is missing, and "heading focus order" misdescribes it: the h1 is not a tab stop, the tabpanel is | **Accepted.** A new test checks that Tab goes from the panel to the "i" to the panel body. With the row moved after the body, the test fails.                                                                                                                                                                                       | `test_the_panel_trigger_is_reached_before_the_panel_body`                           |
