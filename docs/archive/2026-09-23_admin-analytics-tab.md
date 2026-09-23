---
authority: historical
status: superseded
do_not_implement: true
archived: 2026-09-23
supersedes_note: >
  This document is a finished plan, built and shipped on 2026-09-23 in one commit. It
  reversed admin-analytics-v1-plan.md §7.1 (analytics as a sibling body under Overview) and,
  during review, three of its own first-draft decisions. It is a record of what was decided
  and what it cost, not a specification.
live_authority:
  - DESIGN.md
  - docs/ARCHITECTURE.md
  - TODO.md
---

> [!CAUTION]
> **You are reading history, not a specification.** The live rules this plan produced are in
> `DESIGN.md` ("The saved-conversation figures are their own tab" and "Standing context may
> hide; a state may not"); read those, not this. Final position, so no section here has to
> be read in a special order: analytics is the **last** tab; the `privacy` sentence is **in**
> the popup; the trigger is a **28px** ghost "i"; the lead zone renders **once at init** and
> a total failure **retries** on the next activation. Every `file:line` below describes the
> tree **before** the build. What is still open: the one-time screen-reader check — verified 2026-09-23
> with VoiceOver; the popovers announce correctly and no code change was needed.
> The check is now closed and archived in `TODO-resolved.md`. Every heading is prefixed `[HISTORICAL]`.

# [HISTORICAL] Admin analytics — its own tab, explanations behind an "i"

**Reverses** [`admin-analytics-v1-plan.md`](../admin-analytics-v1-plan.md) §7.1 ("a sibling body in
Overview, no new tab"). The reasons §7.1 gave for a sibling were all reasons not to put analytics
_inside_ `renderOverview`; none was a reason against a tab, and a tab satisfies all three better.
Overview's own contract in `DESIGN.md:375-384` — cheap reads, every figure links to the tab that
owns it — is one the analytics region breaks on every count, which `DESIGN.md:386-394` currently
has to excuse.

## [HISTORICAL] How this plan was made

Two independent plans from the same brief (OpenCode `muse-spark-1.3` at `xhigh`, read-only;
Antigravity `gemini-3.7-flash-high`), a third Antigravity session for toggletip best practice,
Context7 for the MDN Popover / anchor-positioning pages, and `impeccable` (shape, Operate mode).
The merged draft then went to Codex (`gpt-5.6-sol`, `xhigh`, read-only) to be attacked. Every
claim kept here was re-read against the source. The working tree was unchanged after all four
delegate runs.

| Question         | OpenCode                   | Antigravity                      | This plan                                                                      |
| ---------------- | -------------------------- | -------------------------------- | ------------------------------------------------------------------------------ |
| Tab position     | last                       | second                           | **last** — zero test churn (`test_admin_browser.py:92-107` hardcodes the step) |
| Container id     | keep `#overview-analytics` | rename `#analytics-body`         | **rename** — net zero lines, and every panel is `#<name>-body`                 |
| Tab glyph        | `info`                     | `journal`                        | **neither** — register `chart` (see step 1)                                    |
| Popup mechanism  | native `popover`           | native `popover`                 | native `popover`                                                               |
| Popup placement  | UA-centred                 | UA-centred                       | **anchored to the button**, centred only as the fallback                       |
| Popup role       | none, `aria-describedby`   | `role="tooltip"` (wrong)         | none, no `aria-describedby`; a named trigger                                   |
| Triggers         | beside zone headings only  | headings, a `th`, inside notices | beside zone headings, plus the floor notice                                    |
| `privacy` line   | stays visible              | into a popup                     | **into the popup** — owner decision; this plan's first draft kept it visible   |
| `smallSample`    | stays (it is a state)      | into a popup                     | stays                                                                          |
| Lead-zone render | on first load              | on first load                    | **once, at init** — which deletes the re-entry guard outright                  |

Errors caught in the planners: Antigravity's `--shadow-menu` token does not exist
(`static/css/tokens.css:206-209` has `sm/md/lg/xl`); its handler sketch uses `value()` out of
scope; it says CSS anchor positioning lacks Firefox/Safari support, which is out of date.

### [HISTORICAL] What the Codex review changed

Reversals of this plan's own first draft, kept on the record:

| First draft said                                               | Codex found                                                                                                                       | Now                                                                         |
| -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `infoPopup(floorWhy, heading)` in the floor notice             | no `heading` binding exists at `ui.js:3122-3141`; and both triggers in that zone would be named "About Recurring questions"       | the notice's own lead sentence is the topic                                 |
| one helper click covers the test file                          | `_filtered_console` (`test_admin_analytics_browser.py:920-952`) navigates on its own; its eleven callers would go red             | both helpers click the tab                                                  |
| the analytics `loaded` flag is never un-set; "the Tiers idiom" | `DESIGN.md:396-402` requires clearing it when every request failed; Tiers sets `loaded` only on success (`handlers.js:1602`)      | retry on the next activation; the lead is drawn at init so nothing rebuilds |
| implicit anchor, explicit one "only if test 4 says so"         | implicit `popovertarget` anchoring is newer than `position-area`, so `@supports` could un-centre a popup and anchor it to nothing | the explicit anchor is unconditional — one line                             |
| `flip-block, flip-inline`                                      | neither alone rescues a corner                                                                                                    | adds `flip-block flip-inline`                                               |
| the popover is a `<p>`                                         | `.admin-notice p` (`admin.css:1343-1347`) out-ranks the popup rule, and `test…:209` would pass vacuously on the hidden `<p>`      | a `<span>` — valid inside `<strong>`, matched by neither                    |
| "one line plus an icon" in the notice                          | `.admin-notice strong` is a block with a bottom margin (`admin.css:1337-1341`)                                                    | trigger goes inside the `<strong>`; one `:last-child` rule drops the margin |
| "check the focus ring at build time"                           | it is global: `static/css/base.css:85`                                                                                            | cited, no rule added                                                        |
| "the pinned Playwright Chromium"                               | nothing pins it (`requirements-dev.txt`, `.github/workflows/tests.yml:48-50`)                                                     | wording dropped                                                             |
| net +70 lines                                                  | not credible once the tests are non-vacuous                                                                                       | about +110                                                                  |

Rejected, with reasons: **reuse `gauge` for the tab** — it is already Overview's glyph
(`admin.html:124`), and all seven tabs carry a distinct one; **a 38px bordered trigger** — see the
design brief; **`justify-self: start`** — `span-inline-end` already aligns to the anchor's start
edge as far as I can tell, so test 5 asserts the edge and the declaration is added only if it is
red; **archive the V1 plan in this change** — that archive is already a separate open item, and a
dated note at §7.1 records the reversal whichever lands first.

## [HISTORICAL] Design brief

- **Who and when.** One operator, occasionally, asking "are answers being cited, and what do
  people keep asking". Never urgent — so it is the last tab, and it costs nothing until opened.
- **The page.** `h1` Analytics → zone "Saved conversations" (period, language, Refresh, the
  "Counted at" stamp) → "Citation quality" (five tiles, one breakdown table) → "Recurring
  questions" → "…answered without a citation". Same zones, tiles and tables as today; nothing is
  restyled. What goes is the prose between them.
- **The "i".** A 28px round ghost button carrying the existing `info` glyph at 14px, directly
  after a zone heading, before the hairline. `.admin-section-head` is already a flex row with a
  gap (`static/css/admin.css:996-1000`), so it needs no layout rule. An "i", not a "?": the
  Arabic question mark is "؟" and a Latin "?" in an RTL console reads as a bug; "i" is symmetric.
  **This departs from `DESIGN.md:318`** (icon controls are 38px bordered circles). That rule
  describes page chrome — the language and theme toggles. Three 38px bordered circles beside
  12px cap headings would be louder than the paragraphs they replace. 28px clears WCAG 2.5.8's
  24px, and step 7 writes the exception into `DESIGN.md` rather than leaving it implied.
- **The popup.** A small card under the button, inline-start edges aligned, flipping up, across,
  or both when it would leave the viewport. Click, Enter or Space opens; Esc, a click outside, or
  a second click closes; focus returns to the button. One open at a time. All of that is the
  browser's, not ours.
- **What never hides.** States ("could not load", "nothing yet", the floor notice's lead
  sentence, the small-sample line), control labels and the stamp. A popup holds _standing
  context_ — a definition, where the numbers come from, how the data is handled; it never holds
  the only copy of something that changes what the operator does next.
- **Few, not many.** Four triggers on the page. No "i" per tile or per column: the tile labels
  were written to be self-describing ("Found passages, cited none"), and an icon beside every
  label is the most common way this pattern goes wrong.
- **Out of scope: print.** A closed popover does not print, and today's hint paragraphs do. The
  console has no `@media print` rule anywhere, so nothing is being taken away that was designed.

## [HISTORICAL] Steps

Failing-first throughout: write the tests in step 6 before steps 1–5 and watch them fail.

### [HISTORICAL] 1. Template and icon — `web/templates/admin.html`, `web/utils/icons.py`

- Append `#tab-analytics` after `#tab-notifications` (`admin.html:158-161`) and
  `#panel-analytics` after `#panel-notifications` (`:238-242`), each copied from its neighbour.
  The panel holds the `h1.admin-heading` and `<div id="analytics-body" class="admin-panel-body">`.
- Delete `#overview-analytics` and its comment from the Overview panel (`admin.html:168-175`).
- Register one glyph, `chart` (three bars on a baseline, about three lines in `ICONS`). Every tab
  has its own glyph today, and every reusable candidate says something else — `gauge` is
  Overview, `journal` is the corpus, `lightbulb` is suggestions — while `info` would mean "this
  tab" and "explain this" on the same screen. Tab buttons are server-rendered, so it does **not**
  go in `ADMIN_RUNTIME_ICON_NAMES` (`icons.py:466-473`).
- Nothing else wires a tab: clicks are delegated from `.admin-tabs`
  (`static/js/admin/handlers.js:107-114`), the arrow keys read the live list, and `.admin-tabs`
  already wraps (`static/css/admin.css:119-125`).
- Keep the id one word. `test_admin_page.py:352-355` extracts tab ids with `tab-[a-z]+`, so a
  hyphenated id would slip past the template/`TABS` equality test unseen.

### [HISTORICAL] 2. Strings — `web/i18n/en.yaml`, `web/i18n/ar.yaml`

Two keys, both files, no new namespace:

- `page.admin.tabs.analytics` — `Analytics` / `التحليلات`
- `runtime.admin.analytics.about` — `About {topic}` / `حول {topic}` (the trigger's accessible
  name; `I18n.t` substitutes any `{word}` placeholder — `static/js/modules/i18n.js:28-38`)

No existing string is reworded, so the twelve frozen strings are untouched. The owner approved
both Arabic strings on 2026-09-22.

### [HISTORICAL] 3. `static/js/admin/ui.js`

- Add `{ tab: 'tab-analytics', panel: 'panel-analytics' }` to `TABS` (`ui.js:24-32`).
  `test_admin_page.py` pins this list to the template, so it fails until both sides match.
- One helper beside `cardHint` (`ui.js:1492`), and one optional argument on `section()`
  (`ui.js:1365`). All sixteen existing callers pass one argument, so nothing collides; a call
  site changes by one argument, and the zone title doubles as the trigger's topic:

```js
let infoSeq = 0;

/** Standing context on demand: an "i" and the native popover it opens. The
    browser owns toggling, Esc, light dismiss, focus return and the expanded
    state. A span, so it is valid inside the floor notice's <strong> and no
    `p` rule reaches it. The anchor is named explicitly: `popovertarget`'s
    implicit anchor shipped later than `position-area` did. */
function infoPopup(text, topic) {
  const button = document.createElement('button');
  const pop = document.createElement('span');
  pop.id = `admin-info-${(infoSeq += 1)}`;
  pop.className = 'admin-info-pop';
  pop.popover = 'auto';
  pop.textContent = text;
  button.type = 'button';
  button.className = 'admin-info-btn';
  button.setAttribute('popovertarget', pop.id);
  button.setAttribute('aria-label', I18n.t('admin.analytics.about', { topic }));
  button.style.anchorName = pop.style.positionAnchor = `--${pop.id}`;
  button.append(iconElement('info', 14));
  return [button, pop];
}

// in section(title, info):
if (info) head.append(...infoPopup(info, title));
```

- Call sites: `renderAnalyticsLead` (`ui.js:3252-3262`) paints into `analytics-body` and passes
  `source` and `privacy` to `section()` as one popup, joined with a space — both `cardHint`
  lines (`:3259-3260`) go; `citationZone` passes `quality.scopeHint` and drops its trailing
  `cardHint` (`:3044`); `recurringZone` passes `questions.grouping` (replacing `:3144`). In the
  floor notice (`:3133-3141`) the `why` paragraph goes and the trigger joins the lead:
  `lead.append(' ', ...infoPopup(floorWhyText, lead.textContent))` — the lead sentence is its
  topic, so the zone's two triggers have different names.
- A repaint of `#analytics-results` removes each button together with its popover, so nothing
  leaks and nothing is orphaned; the counter only has to be unique, not dense.
- The id rename touches `admin.html:175`, `ui.js:3253`, `handlers.js:1530`, and five test
  selectors (step 6). `info` is already in `ADMIN_RUNTIME_ICON_NAMES` (`web/utils/icons.py:472`)
  and drawn by nothing in the console today, so the trigger's glyph needs no registration.

| String (`admin.analytics.*`)                                          | Where it goes                       |
| --------------------------------------------------------------------- | ----------------------------------- |
| `source`, then `privacy`                                              | popup on "Saved conversations"      |
| `quality.scopeHint`                                                   | popup on "Citation quality"         |
| `questions.grouping`                                                  | popup on "Recurring questions"      |
| `questions.floorWhy`                                                  | popup after the floor notice's lead |
| `quality.smallSample`                                                 | stays — shown only when it applies  |
| `questions.floorEmpty`, every `empty`/`loading`/`countedAt`/`updated` | stay — states                       |
| every label, option and column head                                   | stay                                |

### [HISTORICAL] 4. `static/js/admin/handlers.js`, `static/js/admin.js`

- Move `loadAnalytics`, its three closure variables and the two delegated listeners
  (`handlers.js:1468-1542`) into `export function initAnalyticsTab(services)`, bound to
  `#analytics-body`. Hoist `value()` (`:1461-1466`) to module scope so both inits share it; the
  only other `value` in the file is function-local (`:1358`).
- **The lead is drawn once, at init** — `renderAnalyticsLead(filters)`, no request. It paints
  into a hidden panel, as every other tab's init already does. `loadAnalytics` then only ever
  repaints `#analytics-results`, so the `refetch`-or-rebuild branch (`:1500-1501`), its guard and
  its comment (`:1496-1499`) are deleted rather than moved. `refetch` survives only as
  `announce`.
- **Activation retries after a total failure**, as `DESIGN.md:396-402` requires and Overview
  does (`:1568-1571`). `loadAnalytics` resolves `false` only when its own run finished with
  nothing usable (a superseded run resolves `true`), and:

```js
async function loadOnce() {
  if (loaded) return;
  loaded = true;
  loaded = await loadAnalytics();
}
```

- `initOverviewTab.loadOnce` loses its `loadAnalytics()` call (`:1548`) and nothing else.
- `admin.js`: import `initAnalyticsTab` and call it beside `initOverviewTab` (`admin.js:31`,
  `:88`) — after `revealConsole`, so boot order is unchanged, and no import-map entry is added.
- Comments this makes false, fixed in place: `ui.js:2641-2644` ("no tab owns them") and
  `:2776-2780` ("second body"), `handlers.js:1435-1449` (Overview's "plus three more") and
  `:1472-1482` (landing figures, toasting over another tab).

### [HISTORICAL] 5. CSS — `static/css/admin.css`

Two classes and one notice rule. Layer-3 tokens only, so dark mode is free
(`static/css/tokens.css:220-265`). Logical properties only. Focus needs nothing: `:focus-visible`
is global (`static/css/base.css:85`).

```css
.admin-info-btn {
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  inline-size: 28px;
  block-size: 28px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-pill);
  background: none;
  color: var(--fg-muted);
  vertical-align: middle;
}

.admin-info-btn:hover,
.admin-info-btn:has(+ :popover-open) {
  background: var(--bg-sunken);
  color: var(--signal);
}

.admin-info-pop {
  max-inline-size: min(22rem, calc(100vw - 2 * var(--space-4)));
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  color: var(--fg-secondary);
  box-shadow: var(--shadow-md);
  font-size: var(--fs-200);
  font-weight: var(--fw-body);
}

/* Without anchor positioning the UA centres the popover in the viewport,
   which is still correct. */
@supports (position-area: block-end) {
  .admin-info-pop {
    inset: auto;
    margin: var(--space-1) 0;
    position-area: block-end span-inline-end;
    position-try-fallbacks:
      flip-block,
      flip-inline,
      flip-block flip-inline;
  }
}

/* A notice whose explanation moved behind an "i" ends on its lead. */
.admin-notice strong:last-child {
  margin-block-end: 0;
}
```

`font-weight` is set because one popup lives inside a `<strong>` (`--fw-body`,
`static/css/tokens.css:102`). Support: `popover` in Chrome 114, Firefox 125, Safari 17; anchor positioning in Chrome 125,
Firefox 147, Safari 26.

### [HISTORICAL] 6. Tests — `web/tests/test_admin_analytics_browser.py`

New. Each is red against today's code, and each asserts something positive first so it cannot
pass on an empty page:

1. **Overview boot fires no analytics request.** Record every `**/admin/api/analytics/**` hit,
   open the console, wait for an Overview figure to render, then assert none. Red today:
   `loadOnce` fires three (`handlers.js:1548`).
2. **The tab is last, loads on first click, and only once.** The last `.admin-tab` is
   `#tab-analytics`; its panel shows; exactly three requests after the first click; still three
   after a second.
3. **A total failure is retried on the next activation, and the lead survives it.** All three
   routes abort; three "could not load" zones; mark `#analytics-window`; click the tab again;
   three more requests and the mark is still there. Replaces `:1415-1467`.
4. **Explanations are popups, states are not.** Exactly four triggers with four distinct
   accessible names and four distinct targets; each popup holds its exact catalogue text and is
   hidden; the small-sample line and the floor lead are visible; click opens, Esc closes and
   focus is back on the trigger.
5. **The popup sits by its button and inside the viewport, at 390px, in Arabic** — four triggers
   found first; inline-start edges within a pixel; then a trigger scrolled to the bottom edge, so
   a fallback is actually exercised.

Edited:

- `_analytics_console` (`:121-174`) and `_filtered_console` (`:920-952`) each click
  `#tab-analytics` after navigating; both docstrings stop saying "Overview" and "landing tab".
- Five selectors `#overview-analytics` → `#analytics-body` (`:495`, `:503`, `:522`, `:811`,
  `:975`), and the module docstring (`:1-20`).
- `test_an_empty_question_list_reads_as_a_privacy_rule_not_a_fault` (`:205-210`): the
  `notice.locator("p")` assertion becomes "the lead is visible, the `floorWhy` text is in its
  closed popup".
- `test_a_slow_analytics_request…` (`:683-701`) is renamed for what it still proves, the busy
  region, and drops its `#overview-body` line — that claim is now test 1's.

Untouched and still green by construction: the template/`TABS` equality and `aria-controls` tests
(`test_admin_page.py:336-373`), the icon-literal test (`:309-333`, which scans `iconMarkup`, not
`iconElement`), the keyboard test (`test_admin_browser.py:92-107`), the every-tab walk
(`:2044-2070`), every `#overview-body` assertion, the small-sample test (`:237-256`), i18n parity,
the CSS contract and the `admin-*` class gate.

### [HISTORICAL] 7. Documents, same commit

- `admin-analytics-v1-plan.md`: a dated reversal note under §7.1 (`:353-373`) and beside the "no
  new tab" line (`:17-18`), pointing here. Do not rewrite it; its other placement mentions
  (`:596`, `:697`, `:777`, `:923`) are build history.
- `DESIGN.md:386-394`: replace the "departure" paragraph — Overview's rule holds again as
  written. Add the info-popup rule: standing context may hide, states may not; beside a heading,
  never in a cell; an "i", not a "?"; and the 28px ghost trigger as a named exception to `:318`.
- `TODO.md:1349`, `:1353`: the two phrases that say "Overview".
- `docs/ARCHITECTURE.md`, `docs/PRODUCT.md`, `docs/OPERATIONS.md`: none names the placement.
- Bump `ASSET_VERSION`. `CLAUDE.md` is not edited, so `APP_VERSION` stays.
- After the build, archive **this** plan by the five-step procedure in `docs/archive/README.md`.

### [HISTORICAL] 8. Gates

```bash
.venv/Scripts/python.exe -m pytest -m "not browser and not integration"
.venv/Scripts/python.exe -m pytest web/tests/test_admin_analytics_browser.py web/tests/test_admin_browser.py --browser chromium
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m mypy web
npm run lint && npm run format:check && npm run lint:md
```

Then two checks no suite makes. By eye, in Arabic at 390px — a green suite is not evidence here
(`CLAUDE.md`, rule 4). And once with a screen reader (NVDA or VoiceOver): the trigger announces
its name and "expanded", and the text is the next thing read. The popover sits directly after its
button in the DOM for that reason. If it is not reachable, the fallback is `aria-describedby` on
the trigger — one line — not focus management.

## [HISTORICAL] Size

Production code about +75 (helper 20, CSS 45, template 6, strings 4, glyph 3, wiring 5) against
−30 (five hint call sites and the `why` paragraph, the re-entry branch, guard and comment, the
Overview sibling and comment). Tests about +125 against −60. Documents about +25. **Net roughly
+110 lines.** The first draft said +70; that did not survive making the tests non-vacuous.

## [HISTORICAL] Decided by the owner, 2026-09-22

1. **`privacy` goes into the "Saved conversations" popup.** It is helpful context, but it does not
   affect the operator's next action or report a state, and the "i" beside the heading is where
   someone looking for data-handling detail would look. This reverses the first draft of this
   plan, which kept it visible on the advice of the research lane and one planner. Visible text is
   now only states, controls, the stamp and the small-sample line.
2. **Arabic:** `التحليلات` and `حول {topic}`.
3. **The tab is last.** Analytics is occasional and on demand; Overview stays the first
   destination, and second place buys little prominence for test churn and a busier tab row.

## [HISTORICAL] Not in this plan

Per-tile or per-column definitions. The helper supports them (`infoPopup` takes any text), but
they need new copy in two languages and nobody has asked a question the labels do not answer.
