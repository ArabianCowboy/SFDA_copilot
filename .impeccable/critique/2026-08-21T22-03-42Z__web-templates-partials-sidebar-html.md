---
target: web/templates/partials/_sidebar.html
total_score: 29
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
timestamp: 2026-08-21T22-03-42Z
slug: web-templates-partials-sidebar-html
---
Method: dual-agent (A: a59dfab8420ecfd3a · B: a37feb34705a7f386)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3/4 | FAQ clicks silently no-op mid-stream instead of calling `_refuseWhileStreaming()` like every sibling handler |
| 2 | Match System / Real World | 4/4 | Physical segmented-control metaphor and calendar-day buckets both match real mental models |
| 3 | User Control and Freedom | 4/4 | Inline rename/delete with scoped Escape, undo window, arrow-key tabs |
| 4 | Consistency and Standards | 3/4 | Active-state marker unified across FAQ/history rows, but the busy-state guard isn't applied uniformly |
| 5 | Error Prevention | 3/4 | Inline delete confirm, matched maxlength — but no guard on double-firing an FAQ request mid-stream |
| 6 | Recognition Rather Than Recall | 2/4 | No search/filter over conversation history; 30-row page + Load More only |
| 7 | Flexibility and Efficiency | 2/4 | No bulk actions, no shortcuts beyond arrow-key tabs, no search |
| 8 | Aesthetic and Minimalist Design | 3/4 | Disciplined chrome, but FAQ rail content undercuts the minimalism the shell promises |
| 9 | Error Recovery | 4/4 | Three distinct history states (loading/empty/unavailable+retry), specific toast copy |
| 10 | Help and Documentation | 1/4 | No first-run affordance explaining Chats vs FAQ; no contextual help |
| **Total** | | **29/40** | **Good (low end)** |

## Design Specificity Verdict

**LLM assessment:** Not a generic sidebar. The grid-not-flex conversation row, the shared `signal-tint` + inset-2px-pill treatment used identically on the active conversation row and the active FAQ button, per-row `dir="auto"` titles, RTL-aware arrow-key tab direction keyed off `document.documentElement.dir` (not locale), and the New Chat button's borrowed citation-marker treatment are all present in code exactly as `DESIGN.md` argues for them — this is a component built from an internally-argued system, not assembled from framework defaults. Where it drifts from its own documentation: `DESIGN.md` still describes the tabs as "Chats | Explore" after the sidebar's user-facing label was renamed to FAQ (commit `cf2a951`), and internal identifiers (`tab-explore{{ suffix }}`, `data-sidebar-tab="explore"`) still say "explore" — harmless to users, but a crack in the "the doc is the source of truth" discipline this system prides itself on.

**Deterministic scan:** `detect.mjs` reported zero findings against the static partial, the sidebar's CSS, and its JS module. A live browser scan (English/LTR and Arabic/RTL) surfaced two sidebar-relevant warnings: a boundary-case `tight-leading` flag on `.history-empty` (`--lh-snug: 1.3` sits exactly at the rule's `>=1.3` threshold — almost certainly a rounding artifact, not a real defect), and an `all-caps-body` flag on `.faq-section h4` in Arabic. I traced the second one myself: `.faq-section h4` isn't in the `.label-caps` class the RTL stylesheet resets, so `text-transform: uppercase` does stay active in Arabic — but `--track-caps` zeroes under `[dir="rtl"]` and a blanket `[dir="rtl"] * { letter-spacing: normal }` catches the rest, so the letter-spacing that actually breaks Arabic glyph joining is already neutralized here. Per `DESIGN.md`'s own stated rule, an uppercase transform with no tracking is a harmless no-op on a script with no case. **Confirmed false positive**, not a live defect. Manual grep checks (logical properties, hardcoded colors, `dir="auto"`, duplicate/unsuffixed ids across the two macro instances, icon-webfont/emoji, `font-style: italic`) came back clean across the board — corroborating the LLM review's read on this component's RTL and consistency discipline.

## Overall Impression

The sidebar is a well-argued, internally consistent component — its cross-list active-state unification and RTL correctness are real engineering, not aspirational copy in a design doc. The gap is what happens once real content lands in it: the FAQ rail, which is the actual first-run experience for a new reader, presents 17 flat questions across categories that exceed the system's own ≤4-per-group chunking rule, and one interaction (clicking a question while an answer is mid-stream) silently drops on the floor while every sibling control gives feedback. Neither is a "wrong architecture" problem — both are cases of a well-designed shell not being finished all the way down to its own content and its own edge cases.

## What's Working

1. **Active-state unification is enforced in code, not just described.** `.history-item.is-active::before` and `.faq-section .nav-link.faq-button.active::before` are byte-for-byte the same rule — inset 2px pill, same radius, same `--signal` fill — so two different lists sharing one column genuinely read as one system.
2. **RTL correctness goes past the stylesheet layer.** The sidebar-tab arrow-key handler reads live layout direction (`document.documentElement.dir`), not locale, so keyboard navigation actually reverses correctly in Arabic — the kind of bug that normally only surfaces in manual QA. Verified independently: the RTL letter-spacing reset is a blanket selector plus a zeroed token, which is why the FAQ heading's leftover `text-transform: uppercase` is inert rather than harmful.
3. **Three distinct history states, including a working retry**, prevents the single worst failure mode of a list like this: telling a reader "you have nothing" when the real answer is "the store didn't respond."

## Priority Issues

**[P1] FAQ clicks give zero feedback when refused mid-stream**
- Why it matters: `handleFaqClick` checks `isRequestInProgress()` and returns silently, while `openSession`/rename/delete all call `_refuseWhileStreaming()` for the identical guard. A reader clicking a question while an answer streams gets a dead button with no explanation — inconsistent with every sibling control in the same file.
- Fix: call the same busy-guard/toast path at the top of `handleFaqClick` that the other three handlers use.
- File: `static/js/modules/handlers.js:1145-1153`
- Suggested command: `/impeccable harden`

**[P1] FAQ rail violates the system's own ≤4-per-group chunking rule on real content**
- Why it matters: `regulatory` (5 questions) and `pharmacovigilance` (6 questions) both exceed the checklist threshold, and this is the default landing panel for a first-time reader with no history — the component whose job is to be the easiest on-ramp presents its heaviest load exactly when the reader has the least context to filter it.
- Fix: cap visible questions per category with a "more" affordance in the same inline style already used for history pagination, rather than the accordion `DESIGN.md` deliberately rejected.
- File: `faq.yaml:16-45` (content), rendered via `static/js/modules/ui.js:967-1022`
- Suggested command: `/impeccable layout`

**[P2] `--fg-faint` fails WCAG AA contrast on the untitled-conversation label**
- Why it matters: `ink-300` (#857A94) on the porcelain/white sidebar surfaces computes to roughly 3.6:1–4.0:1, below the 4.5:1 AA threshold for normal text — and by `DESIGN.md`'s own rule for this state ("color only, never italic... `--fg-faint` is the whole cue it needs"), contrast is the *entire* signal, which is exactly the one under-threshold.
- Fix: step up to `--fg-muted` (ink-500, ≈5.5:1–6.2:1, already used elsewhere for secondary UI text) or darken the `ink-300` primitive.
- File: `static/css/components.css:647, 768-772`; ramp at `static/css/tokens.css:25` (light)
- Suggested command: `/impeccable audit`

**[P2] No search/filter over conversation history**
- Why it matters: history is a bounded 30-row page with "Load more" and no filter surface anywhere in the sidebar — a returning reader with more than a screenful of history has no path back to an older conversation beyond scrolling, which is exactly the failure mode day-bucket grouping was built to reduce but doesn't solve past "Older."
- Fix: a lightweight inline filter input above the history list, filtering the already-loaded page client-side for the common case.
- File: `web/templates/partials/_sidebar.html` (`.history-section` container)
- Suggested command: `/impeccable shape`

**[P3] `DESIGN.md` and internal identifiers still say "Explore"**
- Why it matters: low severity (invisible to users) but it's exactly the drift `DESIGN.md`'s own "one mapping written down twice is the same mapping drifting eventually" rule warns against — and a separate, currently-uncommitted edit to `TODO.md` already fixes the same wording in the changelog without touching `DESIGN.md` itself (see note below the report).
- Fix: rename the internal identifiers to `faq` for consistency, or add a one-line note in `DESIGN.md` acknowledging the intentional internal/external naming split.
- File: `web/templates/partials/_sidebar.html:85-92`; `DESIGN.md` (Navigation section)
- Suggested command: `/impeccable document`

**[P3] `.history-empty` line-height sits exactly at the detector's threshold**
- Why it matters: `--lh-snug: 1.3` triggers a boundary-case `tight-leading` warning; almost certainly a rounding artifact rather than a real readability defect, but worth a deliberate nudge so it stops tripping the detector on every future scan.
- Fix: bump `--lh-snug` a hair above 1.3, or exempt this specific rule if it's confirmed cosmetic.
- File: `static/css/components.css:764`; token at `static/css/tokens.css:93`
- Suggested command: `/impeccable typeset`

## Persona Red Flags

**Alex (Power User):** No search/filter forces scroll + Load More past ~30 conversations. A second FAQ click while an answer streams is silently swallowed — Alex will assume the app is broken, not busy. No bulk delete/archive; only one-row-at-a-time inline confirm.

**Sam (Accessibility-Dependent User):** The untitled-conversation label sits below WCAG AA contrast — and it's the row's only differentiator per the system's own rule. `.history-open` is `display: contents` with focus relocated via `:has()`, which has no fallback for browsers/AT without `:has()` support — a keyboard user there gets zero visible focus indicator on the densest interactive list in the sidebar. The New Chat button's hidden→visible reveal has no `aria-live` announcement.

**Jordan (bilingual/RTL first-timer):** What's verified working: per-row `dir="auto"` titles, RTL-aware arrow-key tab direction, logical-property active-row marker. Risk: the account footer row (`Profile + Admin + Logout + Lang`, up to 4 controls) wraps inside a `flex-wrap` container and hasn't been stress-tested against longer Arabic labels on a narrow offcanvas.

## Minor Observations

- The mobile offcanvas shows a generic "Menu" header directly above the sidebar's own branded header (shield icon + "SFDA Copilot") — two headers doing similar identity work in a small viewport.
- `.sidebar-tabs[data-loading="chats"]`'s pulse dot during initial fetch is a good, deliberate touch — avoids the tab looking "empty but final."
- `tabsAria: "Sidebar contents"` is generic; naming what's actually inside ("Conversations and frequently asked questions") would tell a screen-reader user more before they explore.
