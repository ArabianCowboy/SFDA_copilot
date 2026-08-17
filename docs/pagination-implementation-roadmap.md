# Admin People Pager — Implementation Plan

**Status:** Implemented and landed 2026-08-17 — migration, backend, and frontend all committed and
independently reviewed post-implementation (§14). See §14 for the one real deviation from plan (the
`pg_trgm` index, deferred by a genuine platform permission wall, not a code issue).

**How this document was built — three rounds, each cross-checked and then folded in.**

*Round 1 — functional plan.* Two independent planning passes were run cold against this repo —
`opencode-delegate` (GPT-5.6 Luna, `xhigh`) for an implementation plan, `agy-delegate` (Gemini 3.7
Flash, `high`) for community-practice research plus an independent codebase audit — alongside
Context7 documentation lookups (`/alisaifee/flask-limiter`, `/postgrest/postgrest`). Both outputs
were reviewed against the actual source, reconciled, and merged with seven open decisions resolved
with the project owner. The two source documents this produced
(`pagination-plan-opencode.md`, `pagination-research-agy.md`) were folded in here and removed.

*Round 2 — visual/interaction design (§2).* `agy-delegate` researched how leading products style
dense-table pagers and produced a first concrete CSS/DOM spec grounded in this project's own
design tokens; `opencode-delegate` (Luna) then critically re-audited that spec against the actual
current source and corrected twelve issues (detailed in §2, summarized in §13). The two documents
this produced (`pagination-ux-research-agy.md`, `pagination-ux-design-opencode.md`) were likewise
folded in and removed.

*Round 3 — audit.* `agy-delegate` audited the fully-merged document for internal consistency,
completeness, and continued technical accuracy, catching three real should-fix issues (a SQL
escape-character gap, a live-backend `total` edge case in the boundary-drift logic, and a CSS
auto-margin conflict introduced by Round 2's own DOM-order fix) plus stale cross-references —
applied directly into this document rather than kept as a separate file.

Every model output across all three rounds was re-verified by the orchestrator directly against
the actual source before being trusted into this document — never taken on a report's own word.

**The TODO item this closes** (`TODO.md`, "An account outside the newest 50 cannot be found or
administered — HALF FIXED 2026-08-15"): the admin People tab's search box already works, but the
pager was never built. `static/js/admin/services.js`/`handlers.js` call `GET /admin/api/users`
with no `limit`/`offset`, even though that route and the `admin_list_users` Postgres RPC beneath
it already accept `q`, `limit` (server-capped at 200), and `offset`. The response already
includes `total`, rendered today as an inert `"N / M"` line. A search matching more than 50
accounts silently shows only the first 50 with no indication there's more — **silent
truncation**, the actual severity, since a partial page looks identical to a complete one.

---

## 0. Verified against the current source (not taken on either report's word)

| Claim | File:Line | Status |
|---|---|---|
| `ORDER BY m.created_at desc` has no tie-breaker | `supabase/migrations/20260814100500_user_management.sql:50` | ✅ confirmed |
| `services.js`'s `users()` already defaults/serializes `limit=50, offset=0`; the frontend just never varies them | `static/js/admin/services.js` | ✅ confirmed (OpenCode's reading, more precise than the original TODO wording) |
| Truncation notice is `${users.length} / ${total}` as a bare paragraph | `static/js/admin/ui.js:566-571` | ✅ confirmed |
| Server clamps `limit ∈ [1,200]`, `offset ≥ 0` | `web/api/admin.py:246-247` | ✅ confirmed |
| RPC signature is `p_limit int`, `p_offset int` (Postgres `int4`, 32-bit) | `supabase/migrations/20260814100500_user_management.sql:14-17` | ✅ confirmed |
| CTE computes `count(*)` over the full matched set on every call | same file:35-52 | ✅ confirmed |
| RPC execute revoked from `anon`/`authenticated`/`public` | same file:55-56 | ✅ confirmed |
| `admin_bp` rate-limited at 60/min | `web/api/app.py:1104` | ✅ confirmed |
| **The identical limit/offset clamping block is copy-pasted verbatim** in `/admin/api/users` (`admin.py:246-247`) **and** `/admin/api/audit` (`admin.py:747-748`) | `web/api/admin.py` | ✅ new finding — neither delegate was scoped to look at `/api/audit`; extract a shared helper while this is being touched (Decision #7) |

---

## 1. Architecture: offset/limit pagination, not keyset — locked

Both independent passes converged on this without seeing each other's output.

**Page drift.** Offset pagination (`OFFSET N LIMIT M`) is stateless — the database evaluates
offsets against the dataset's snapshot at query time. If a row is inserted while an operator
sits on page 1, the old 50th row shifts to position 51 and reappears on page 2 (duplicate). If a
row is deleted, everything downstream shifts up and a row is skipped. This is mathematically
inevitable with offset pagination and does not need to be "fixed" — it needs a tie-breaker so
it's at least *deterministic* (see below), and to be named as a known, accepted characteristic
rather than a bug.

**OFFSET performance at scale.** Postgres doesn't jump to row N — it scans, sorts, and discards
the first N tuples, cost `O(N+M)`. The current RPC's CTE already computes `count(*)` over the
full matched set on *every* call regardless of `limit`/`offset`, so the count, not the offset
walk, is the actual cost driver here.

**Keyset/cursor pagination — considered and rejected for this surface.** Keyset pagination
(`WHERE (created_at, id) < (:last, :last_id) ORDER BY ... LIMIT 50`) gives `O(M)` constant-time
seeks via a B-tree and is immune to page drift on forward walks — but it can't jump to an
arbitrary page number, bidirectional paging needs inverted predicates, it doesn't yield a total
count without a separate query, and combining it with the existing substring `ILIKE` search adds
real indexing complexity. None of that trade is worth it at this project's scale.

**Recommendation, locked: keep offset/limit.** At a projected scale of hundreds to low thousands
of accounts (3 today), Postgres executes indexed `OFFSET` queries in single-digit milliseconds.
Administrators want an explicit total ("Showing 1–50 of 137") and predictable next/previous
transitions — cursor pagination's UI friction isn't warranted here. **Add one thing neither the
existing code nor either plan started with:** `ORDER BY m.created_at DESC, m.id DESC` in
`admin_list_users` — without a tie-breaker, two accounts created in the same millisecond produce
non-deterministic ordering across page boundaries. One-line SQL change, ships in the same
migration as the trigram index (§7).

| Data volume | Query mode (current, no index) | Latency | Impact on debounced search |
|---|---|---|---|
| 1 – 1,000 rows | Seq scan (RAM cache) | < 2 ms | None |
| 1,000 – 20,000 | Seq scan (disk/RAM) | 5 – 50 ms | Minor CPU increase |
| 20,000 – 100,000 | Seq scan (heavy CPU) | 50 – 300 ms | Stall on fast typing |
| 100,000+ | Seq scan (I/O bound) | > 500 ms – seconds | Connection exhaustion, 503s |
| *Any volume, with `pg_trgm` GIN* | Bitmap index scan | < 5 ms | Stable, scalable |

---

## 2. UI shape — locked, including full visual/interaction design

**How this section was built — a third independent pass, this time on the visual design itself.**
After the functional plan (§0–§1, §3–§12) was locked, a further two-stage pipeline refined its
*visual and interaction* design specifically: `agy-delegate` (Gemini 3.7 Flash, high) researched
how dense-table pagers are styled in leading products (Linear, Stripe Dashboard, Supabase Studio,
GitHub, Vercel) and produced a first concrete CSS + DOM-builder spec grounded in this project's
own design tokens; `opencode-delegate` (GPT-5.6 Luna, xhigh) then critically re-audited that spec
against the actual current source — not just restating it — and corrected twelve real issues
before it's presented below as final. Both passes, and every token/class/icon name either one
cited, were independently re-verified by the orchestrator directly against `tokens.css`,
`admin.css`, `icons.py`, and `icons.js` before being trusted into this document. What follows is
the corrected, thrice-verified result.

**What the second design pass caught that the first missed** (worth recording, same as the
functional plan's own cross-check note in §13):
1. **A real correctness bug.** The first draft's DOM builder assigned a translated string via
   `button.innerHTML = ...I18n.t(...)...` — piping translated text through `innerHTML`, directly
   contradicting this project's own established rule (translated values go through DOM nodes /
   `textContent`, never `innerHTML` — the same rule §6 already states for the range numerals, and
   the same class of incident recorded in this project's own history). Fixed by using the existing
   `iconElement()` helper (which only ever parses static, translation-free icon markup) for the
   icon, and a separate `textContent`-only node for the label.
2. **The first draft's own DOM order contradicted this document's already-locked order.** It
   appended the page-size group *before* the previous/status/next group; this document specifies
   previous → status → next → page-size (§2 above, unchanged). Corrected to match.
3. **Wrong `aria-controls` target** (`people-list` — doesn't exist; the real table id is
   `people-table`, confirmed against `static/js/admin/ui.js`).
4. **An unreachable focus fallback.** The plan's own focus-retention requirement (below) falls
   back to focusing the range status when the equivalent button is now disabled — but the first
   draft's status span had no `tabindex`, so that fallback could never actually receive focus.
   Fixed with `tabIndex = -1`.
5. **The loading treatment could flash on fast requests.** The first draft dimmed the table and
   started the pulse animation the instant a request began, with no threshold — so a normal,
   near-instant local response would still produce a visible flash of "loading," which reads as
   janky rather than polished. Fixed with a 100ms delay before any visual dimming appears (see
   below) — a standard perceived-performance technique the first pass didn't include.
6. **The page-size select was disabled while loading**, inconsistent with this document's own
   already-locked principle (§3–§5: the search input stays interactive during a request because
   the sequence-token guard makes the *latest* intent authoritative). Corrected to leave it
   enabled — the same reasoning applies to page-size changes as to search edits.
7. Five smaller corrections: missing `.form-select` class (breaks the existing RTL select-chevron
   contract), the Next-button boundary check used the wrong variable (`count`, the *displayed* row
   number, instead of `limit`, the *committed* page size — this document's §3 state model already
   specifies `limit` correctly; the first visual draft's JS didn't match it), the old row-locking
   during loading (`pointer-events: none`) contradicted §5's "old rows may remain openable during
   debounce," a `.admin-table-wrapper` element the CSS depends on doesn't exist yet in the current
   `ui.js` and must be added, and an overclaimed "full WCAG 2.1 AA" guarantee was narrowed to what
   the CSS actually enforces (this repo's `test_css_contract.py` checks logical-property patterns,
   not full accessibility conformance — confirmed by reading the test file directly).

### DOM shape and ARIA

```text
nav#people-pager.admin-pager
  div.admin-pager-nav
    button#people-prev.admin-pager-btn.admin-pager-btn--prev
    span#people-range-status[role=status][aria-live=polite][aria-atomic=true][tabindex=-1]
    button#people-next.admin-pager-btn.admin-pager-btn--next
  div.admin-pager-size
    label[for=people-page-size]
    select#people-page-size.form-select.admin-input.admin-pager-select
```

`nav` carries `aria-label` (`admin.people.pagerLabel`), `aria-controls="people-table"` (the real
table id), and `aria-busy` reflecting the in-flight state. Native `<button type="button">`
elements throughout (no implicit form submission), native `disabled` (not just `aria-disabled`).

**Why Next/Previous over the alternatives** (unchanged from the original functional pass):
*infinite scroll* hides the boundary and complicates keyboard/screen-reader navigation; *load
more* keeps growing the DOM and gives no way back; *Next/Previous* keeps the table dense and
stable, makes "more records exist" explicit, and maps directly onto the server's `limit`/`offset`
contract — matching PostgREST's own `Content-Range` convention (confirmed via Context7, see intro).

**Range display.** Rendered for every non-empty result, including a complete one-page result
(`Showing 1-4 of 4`, making completeness explicit). Empty result: keep `No accounts found.`,
render no pager. Computed from the *committed* response: `start = offset + 1`,
`end = offset + count` (the actual row count returned), `total = response.total` — never
`offset + limit`, which is an off-by-one bug on the final page.

**Page size — resolved (Decision #1): operator-customizable, default 50**, via
`select#people-page-size` offering `25 / 50 / 100 / 200` (200 is also the server's hard cap).
Changing it resets `offset` to 0 and refetches, sharing the same invalidation path as a search
change (§4–§5). **Stays enabled while a request is loading** — see correction #6 above. Not
persisted across reloads (cheap `localStorage` follow-up if ever wanted; not built now).

### Loading treatment — a quiet, threshold-delayed signal, not a skeleton or spinner

Evaluated and rejected: skeleton rows (row-jump layout jitter, high DOM churn, flashes on fast
queries), a centered spinner (obscures the data an operator needs to keep reading), a bare
progress line alone (insufficient — rows still look active/correct while stale). **Recommended
and locked: tonal table dimming plus a top hairline pulse, both delayed 100ms:**

1. `aria-busy="true"` on the list/pager region is set **immediately** — that's semantic state,
   not decoration, and costs nothing visually.
2. Both pager buttons are disabled immediately on click (the button-level race guard from §4).
   The search input and page-size select stay enabled throughout (correction #6).
3. A `.is-busy-visual` class — the actual dimming (`opacity: 0.45` on `tbody`) and the animated
   top-edge pulse — is applied only after a **100ms timer**, cleared on commit/abort/failure. A
   request that resolves inside 100ms (the common case for a small table) never shows any visual
   loading state at all — no flash, no flicker. This threshold is a design recommendation, not a
   value measured against this repo's actual latency; revisit if real usage disagrees.
4. Rows dim as a stale-data cue but are **not** locked with `pointer-events: none` — §5 already
   established that old rows may remain clickable during the search debounce window, and the same
   reasoning applies here.
5. On commit, both visual classes clear and the new table/range/pager render atomically in one
   frame — no partial-update flash.
6. All transitions restricted to `opacity`/`transform` only (the project's existing
   `prefers-reduced-motion` rule in `base.css` already collapses these to near-instant for
   motion-sensitive operators — confirmed directly, no new reduced-motion rule needed).

### Rebuild vs. in-place update — kept as rebuild, with explicit focus restoration

`renderUsers()` already clears and rebuilds `#people-list` on every render; changing that render
boundary to an in-place update is a larger change than this feature justifies, so the pager is
rebuilt alongside the table on every page change, exactly like the rest of the row content. That
makes **focus retention a required, explicit step**, not a side effect:

- Capture `document.activeElement?.id` before the render clears the DOM.
- After the new pager is appended: re-focus the same element if it still exists and isn't
  disabled; if it was `#people-prev`/`#people-next` and that button is now disabled at a boundary,
  focus `#people-range-status` instead (works only because of the `tabIndex = -1` fix above).

### Structural prerequisite

The corrected CSS's loading indicator depends on a `div.admin-table-wrapper` around the table,
which **does not exist yet** in the current `ui.js` — adding it is part of this feature's frontend
work (§12 step 4), not a pre-existing element being reused.

### Corrected CSS (`static/css/admin.css`)

```css
/* ── Admin People Pager ─────────────────────────────────────────────────── */

.admin-table-wrapper {
  position: relative;
  inline-size: 100%;
}

/* Visual busy state is added only after the 100ms threshold — see above. */
.admin-table.is-busy-visual tbody {
  opacity: 0.45;
  transition: opacity var(--duration-s) var(--ease-soft);
}

.admin-table tbody {
  transition: opacity var(--duration-s) var(--ease-soft);
}

.admin-table-wrapper.is-busy-visual::after {
  content: "";
  position: absolute;
  inset-block-start: 0;
  inset-inline: 0;
  block-size: 2px;
  background: var(--signal);
  border-start-start-radius: var(--radius-md);
  border-start-end-radius: var(--radius-md);
  animation: adminPagerPulse 1.2s var(--ease-soft) infinite;
  transform-origin: center; /* direction-neutral: symmetric in both LTR and RTL */
}

@keyframes adminPagerPulse {
  0% { transform: scaleX(0.1); opacity: 0.4; }
  50% { transform: scaleX(0.8); opacity: 1; }
  100% { transform: scaleX(1); opacity: 0; }
}

.admin-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--space-3) var(--space-4);
  margin-block-start: var(--space-4);
  padding-block: var(--space-2);
}

.admin-pager-size {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  flex: 0 0 auto;
}

.admin-pager-size-label {
  font-family: var(--font-sans);
  font-size: var(--fs-200);
  color: var(--fg-muted);
  font-weight: var(--fw-body);
  white-space: nowrap;
}

.admin-pager-select {
  min-block-size: 32px;
  padding: var(--space-1) var(--space-3);
  padding-inline-end: var(--space-7);
  font-family: var(--font-mono);
  font-size: var(--fs-200);
  font-variant-numeric: tabular-nums;
  color: var(--fg-primary);
  background-color: var(--bg-surface);
  border: 1px solid var(--hairline-strong);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: var(--btn-transition);
}

.admin-pager-select:focus {
  outline: none;
  border-color: var(--signal);
  box-shadow: 0 0 0 3px var(--focus-ring-shadow);
}

.admin-pager-nav {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-3);
  flex: 0 0 auto;
  /* No margin-inline-start: auto here — an audit pass caught that this was a
     leftover from an earlier draft where the size group was appended first.
     Now that navGroup is the first child (DOM order corrected above), an auto
     margin on it would consume all the flex free space and push both groups
     to the same end, overriding .admin-pager's own `justify-content:
     space-between` below. The parent's space-between already places navGroup
     at inline-start and sizeGroup at inline-end without any margin here. */
}

.admin-pager-status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--fs-200);
  color: var(--fg-secondary);
  white-space: nowrap;
}

.admin-pager-status .admin-cell-machine {
  font-family: var(--font-mono);
  font-size: var(--fs-200);
  font-variant-numeric: tabular-nums;
  color: var(--fg-primary);
  font-weight: var(--fw-medium);
}

.admin-pager-status:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 4px;
  border-radius: var(--radius-xs);
}

.admin-pager-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-block-size: 32px;
  padding: var(--space-2) var(--space-3);
  background: transparent;
  border: 1px solid var(--hairline-strong);
  border-radius: var(--radius-sm);
  font-family: var(--font-sans);
  font-size: var(--fs-200);
  font-weight: var(--fw-medium);
  color: var(--fg-secondary);
  cursor: pointer;
  text-decoration: none;
  white-space: nowrap;
  transition: var(--btn-transition);
}

.admin-pager-btn .icon {
  color: var(--fg-muted);
  transition: color var(--duration-s) var(--ease-soft),
              transform var(--duration-s) var(--ease-soft);
}

.admin-pager-btn:hover:not(:disabled) {
  background: var(--bg-sunken);
  border-color: var(--fg-faint);
  color: var(--fg-primary);
  transform: translateY(-1px);
}

.admin-pager-btn:hover:not(:disabled) .icon {
  color: var(--fg-primary);
}

.admin-pager-btn:active:not(:disabled) {
  transform: translateY(0);
}

.admin-pager-btn:focus-visible {
  outline: none;
  border-color: var(--signal);
  box-shadow: 0 0 0 3px var(--focus-ring-shadow);
  background: var(--bg-surface);
  color: var(--fg-primary);
}

.admin-pager-btn:disabled {
  opacity: 0.45;
  border-color: var(--hairline);
  color: var(--fg-faint);
  cursor: not-allowed;
  pointer-events: none;
  transform: none;
}

.admin-pager-btn:disabled .icon {
  color: var(--fg-faint);
}

.admin-pager-btn--prev .icon {
  transform: scaleX(calc(-1 * var(--flip)));
}

.admin-pager-btn--next .icon {
  transform: scaleX(calc(1 * var(--flip)));
}

.admin-pager-btn--prev:hover:not(:disabled) .icon {
  transform: scaleX(calc(-1 * var(--flip))) translateX(calc(-2px * var(--flip)));
}

.admin-pager-btn--next:hover:not(:disabled) .icon {
  transform: scaleX(calc(1 * var(--flip))) translateX(calc(2px * var(--flip)));
}

@media (max-width: 640px) {
  .admin-pager {
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-3);
  }

  .admin-pager-nav {
    inline-size: 100%;
    justify-content: space-between;
    margin-inline-start: 0;
  }

  .admin-pager-status {
    order: -1;
    flex-basis: 100%;
    inline-size: auto;
    justify-content: center;
    margin-block-end: var(--space-1);
  }

  .admin-pager-size {
    justify-content: center;
    inline-size: 100%;
  }
}
```

Every token above (`--flip`, `--signal`, `--hairline-strong`, `--bg-sunken`, `--focus-ring-shadow`,
`--focus-ring`, `--duration-s`, `--ease-soft`, `--btn-transition`, `--radius-sm`, `--radius-xs`,
`--radius-md`, `--fs-200`, `--fw-medium`, `--fw-body`, `--font-sans`, `--font-mono`, `--space-1`
through `--space-7`, `--fg-primary/secondary/muted/faint`, `--bg-page/surface`) and every reused
class (`.admin-input`, `.admin-cell-machine`, `.form-select`) was verified directly against
`tokens.css`/`admin.css`/`components.css` — none invented. Zero new dependencies, zero new icon
assets (`chevron-right` already exists in the runtime icon registry), zero webfonts.

### Corrected DOM builder (`static/js/admin/ui.js`)

Requires importing `iconElement` alongside the existing `iconMarkup`:
`import { iconElement, iconMarkup } from '../modules/icons.js';` — `iconElement()` parses only
static, translation-free registry markup (verified in `static/js/modules/icons.js`), so using it
for the chevron never risks a translated string reaching `innerHTML`.

```javascript
function appendPagerButtonContent(button, label, iconFirst) {
  const icon = iconElement('chevron-right', 14);
  const labelNode = document.createElement('span');
  labelNode.textContent = label;

  if (iconFirst) {
    if (icon) button.appendChild(icon);
    button.appendChild(labelNode);
  } else {
    button.appendChild(labelNode);
    if (icon) button.appendChild(icon);
  }
}

/**
 * Build the People pager from one committed response.
 * Caller must not call this for an empty result. `count` is the committed row
 * count (for the displayed end number); `limit` (not `count`) drives the
 * Next-button boundary check, since the final page can be shorter than `limit`.
 */
export function createPeoplePager({ offset, limit, total, count, loading = false }) {
  const pager = document.createElement('nav');
  pager.id = 'people-pager';
  pager.className = 'admin-pager';
  pager.setAttribute('aria-label', I18n.t('admin.people.pagerLabel'));
  pager.setAttribute('aria-controls', 'people-table');
  pager.setAttribute('aria-busy', String(loading));

  const navGroup = document.createElement('div');
  navGroup.className = 'admin-pager-nav';

  const prevBtn = document.createElement('button');
  prevBtn.type = 'button';
  prevBtn.id = 'people-prev';
  prevBtn.className = 'admin-pager-btn admin-pager-btn--prev';
  prevBtn.disabled = loading || offset <= 0;
  appendPagerButtonContent(prevBtn, I18n.t('admin.people.previousPage'), true);

  const status = document.createElement('span');
  status.id = 'people-range-status';
  status.className = 'admin-pager-status';
  status.tabIndex = -1; // required so the boundary focus fallback below actually works
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  status.setAttribute('aria-atomic', 'true');

  const startNum = total === 0 ? 0 : offset + 1;
  const endNum = offset + count;
  const rangeBdi = document.createElement('bdi');
  rangeBdi.setAttribute('dir', 'ltr');
  rangeBdi.className = 'admin-cell-machine';
  rangeBdi.textContent = `${startNum}–${endNum}`;

  const totalBdi = document.createElement('bdi');
  totalBdi.setAttribute('dir', 'ltr');
  totalBdi.className = 'admin-cell-machine';
  totalBdi.textContent = String(total);

  status.append(
    document.createTextNode(I18n.t('admin.people.showing')),
    rangeBdi,
    document.createTextNode(I18n.t('admin.people.of')),
    totalBdi,
  );

  const nextBtn = document.createElement('button');
  nextBtn.type = 'button';
  nextBtn.id = 'people-next';
  nextBtn.className = 'admin-pager-btn admin-pager-btn--next';
  nextBtn.disabled = loading || offset + limit >= total;
  appendPagerButtonContent(nextBtn, I18n.t('admin.people.nextPage'), false);

  navGroup.append(prevBtn, status, nextBtn);

  const sizeGroup = document.createElement('div');
  sizeGroup.className = 'admin-pager-size';

  const sizeLabel = document.createElement('label');
  sizeLabel.className = 'admin-pager-size-label';
  sizeLabel.htmlFor = 'people-page-size';
  sizeLabel.textContent = I18n.t('admin.people.pageSize');

  const select = document.createElement('select');
  select.className = 'form-select admin-input admin-pager-select';
  select.id = 'people-page-size';
  // Deliberately left enabled during loading — see "Loading treatment" above.

  [25, 50, 100, 200].forEach((size) => {
    const option = document.createElement('option');
    option.value = String(size);
    option.textContent = String(size);
    option.selected = size === limit;
    select.appendChild(option);
  });

  sizeGroup.append(sizeLabel, select);
  pager.append(navGroup, sizeGroup); // locked DOM order — see "DOM shape" above
  return pager;
}
```

Caller responsibility in `renderUsers()`: capture `document.activeElement?.id` before the
existing DOM clear, render the pager from the committed `{offset, limit, total, count, loading}`,
then restore focus per "Rebuild vs. in-place update" above. This is also where the missing
`div.admin-table-wrapper` needs to be introduced around the table.

In RTL, "Next" points visually left and "Previous" right — handled entirely by DOM order plus
flexbox mirroring under `dir="rtl"` and the `--flip`-based chevron transforms above; never a
hardcoded physical direction.

---

## 3. Client state management — locked

Keep pager state in the closure of `initPeopleTab()`, beside the existing `searchTimer`,
`opening`, and view-generation variables — not in a module global, not in `ui.js` (which renders
from an explicit result shape and neither fetches nor owns the current page).

- `offset` — offset of the last *committed* page, initially `0`.
- `limit` — the operator-selected page size, initially `50`, never above the server's 200 cap.
- `total` — the filtered total from the last committed response; unknown while the first request
  is pending.
- `query` — the normalized, trimmed query associated with that committed page.
- `loading` — whether a list request is active; disables pager controls.
- `requestSequence` — a monotonically increasing token for list requests (§4).
- `activeListAbort` — the `AbortController` for the current list request.

`loadPage()` captures `query`/`offset`/`limit` before calling `services.users({ q, limit,
offset })`. On success, commit the response's own `offset`/`limit`/`total` together with the
captured query, then render from *that* — never compute `total` from the number of rows the
browser happened to receive; the server's count is authoritative.

**State transitions:**
- Initial load: query empty, offset 0.
- Next: `offset += limit`, only if `offset + limit < total`.
- Previous: `offset -= limit`, only if `offset > 0`.
- Search change: reset offset to 0, associate future requests with the new normalized query (§4).
- Page-size change: reset offset to 0, refetch at the new limit — shares the same invalidation
  path as a search change rather than being a special case.
- Back from account detail: preserve the current query and committed page, reload it so changes
  made in detail are reflected — do not silently jump back to page 1.

**Boundary drift.** If a page request returns zero rows with `total > 0` (accounts were deleted
while the operator was viewing an old offset), clamp to the last valid page boundary
(`Math.floor((total-1)/limit) * limit`) and refetch once, rather than showing "no accounts found"
when only the offset is stale. If `total` is genuinely `0`, render the normal empty state.

**A gap an audit pass caught in this logic, verified against the real backend:** that clamp
depends on the response still reporting an accurate `total > 0` even when the requested page comes
back empty. It doesn't, against Supabase. `total` is carried as a column on each *row* the RPC
returns (`select m.*, (select count(*) from matched) as total from matched m limit ... offset
...`), so when `offset` lands past the end of the matched set, the RPC returns zero rows and
`SupabaseAdminBackend.list_users` (`web/services/admin_store.py:279-288`) falls back to
`total = rows[0]["total"] if rows else 0` — collapsing the real count to `0` alongside the empty
row list. The client then sees `users: [], total: 0` and can't tell "genuinely no accounts" from
"this offset ran off the end," so the `total > 0` condition above never fires and the clamp never
runs. (The in-memory test double, `InMemoryAdminBackend.list_users`, does *not* have this gap — it
computes `total` from the full filtered set regardless of slice, so this asymmetry is invisible in
backend unit tests and only shows up against the real database — flagged for §9.) **Client-side
fix:** treat `users.length === 0 && offset > 0` as ambiguous regardless of what `total` says —
reset `offset` to `0` and refetch once unconditionally in that case, rather than branching on
`total > 0`. A genuinely empty result set (no accounts at all, or no search matches) always has
`offset === 0` already, so this fallback can never mask a real empty state.

---

## 4. Concurrency / race protection — locked, converged independently

Two concrete failure classes, both real:

- **Fast Next/Previous clicks.** If `offset` is mutated locally before the previous response
  resolves, a double-click can fire `offset=50` and `offset=100` simultaneously; if the second
  returns first, the operator sees a jarring jump or a page rendered out of order.
- **Search/page-size edit racing an in-flight page fetch.** An in-flight page-2 request can
  resolve *after* a newer search or page-size-change request, overwriting the newer view with
  stale rows. This is not hypothetical — HTTP response order is not guaranteed to match request
  order, especially when queries have different costs (e.g. a short search term scanning slower
  than a longer, more selective one issued moments later).

**Layered defense — do not rely on network order alone:**

1. **Button-level guard.** Disable pager buttons immediately on click; the delegated handler
   re-checks `loading` and the boundary before actually requesting. Stops ordinary double-clicks
   from producing duplicate transitions.
2. **Sequence token — the actual correctness guarantee.** Every list request gets a
   monotonically increasing token, capturing the query/offset/limit/view-generation it was issued
   with. Only the request whose token still matches current state may commit or touch the DOM. An
   older response must never overwrite a newer page's state, even if it arrives last.
3. **`AbortController` — best-effort, not sufficient alone.** One controller for the active list
   request; abort it on search edit, page-size change, a different page request, or opening
   account detail. Extend the transport's request options to pass the signal through to `fetch`,
   reused across the existing 401/GET-503 retry paths. An aborted request must be recognized as an
   expected cancellation — never surface `loadFailed` or a toast for it. Keep the sequence check
   even with abort available: abort is racy too, and the token is what actually guarantees
   correctness.
4. **Cleanup ownership.** Restore `loading`/disabled-state/`aria-busy` only for the request that
   still owns them — a stale request's `finally` block must not re-enable controls for a newer
   request.

`renderUsers()` should receive a complete committed result (including `offset`/`limit`) rather
than reading mutable handler state while it renders, so the render itself can't race the state
machine.

**Opening an account remains a view transition:** cancel the list timer, invalidate the active
list request, and increment the existing view generation before loading detail — preserving the
current test contract where typing/opening inside the debounce window can't let a delayed list
load replace the detail panel. Returning with Back starts a fresh list request for the preserved
query/offset.

---

## 5. Search debounce and reset — locked

Keep the existing 300ms debounce, but **invalidate synchronously on keystroke, not only when the
timer fires**: normalize the value, clear the existing timer, reset `offset` to 0 immediately, and
mark the previously committed total stale — *then* start a new 300ms timer for the actual
request. Without the synchronous reset, a narrow search typed while on page 2 can request
`offset=50` against what turns out to be a 3-row result and render a false "no accounts found,"
even though matches exist on page 1.

Old rows may remain visible during the debounce window (so an operator can still open a
currently-visible row mid-type) but must be marked busy and treated as belonging to the *previous*
committed view — never as results for the new query. Once the new response commits, replace the
table and range atomically.

---

## 6. i18n / RTL markup — locked

Six new keys under `runtime.admin.people.*` in both `web/i18n/en.yaml` and `web/i18n/ar.yaml`:

| Key | English | Arabic (draft) |
|---|---|---|
| `admin.people.pagerLabel` | People pages | صفحات المستخدمين |
| `admin.people.previousPage` | Previous page | الصفحة السابقة |
| `admin.people.nextPage` | Next page | الصفحة التالية |
| `admin.people.showing` | Showing | عرض |
| `admin.people.of` | of | من |
| `admin.people.pageSize` | Rows per page | عدد الصفوف في الصفحة |

**Resolved (was open question #2): ship these Arabic strings now rather than blocking the
feature on native review** — flag all six keys for a native-speaker pass before or shortly after
release, tracked as a follow-up, not a blocker.

**Numeric range/total must be built as DOM nodes, never string-interpolated into one translated
template.** Both independent passes named the same failure mode — the Unicode bidi algorithm
scrambling `1–50` inside Arabic prose (e.g. naive interpolation can render `"عرض 50-1 من 137"`
instead of the intended left-to-right range) — which also matches this project's own recorded
incident (`arabic-dates-need-parts-not-intl`). Build the range from: a text node from `showing` →
a `<bdi dir="ltr">` containing `start`–`end` → a text node from `of` → a second `<bdi dir="ltr">`
containing `total`. Use DOM APIs and `textContent` exclusively; never `innerHTML` for a translated
value. The `bdi` wrapping is needed even though the page already has `dir="rtl"` — the counts are
machine facts embedded in Arabic prose, the same reasoning already applied to email/date cells
elsewhere in this admin console.

Pager CSS (`static/css/admin.css`) uses only logical properties — `margin-inline-*`,
`padding-inline`, `inline-size`, `border-block`, `text-align: start/end` — never `left`/`right`
or physical margins/padding. A flex row in DOM order previous/status/next mirrors automatically
under `dir="rtl"`. Enforced by the existing `test_css_contract.py`.

---

## 7. Database changes — migration applied 2026-08-17, one item deferred by a real platform wall

The current predicate is a leading-wildcard substring search:
`u.email::text ILIKE '%' || p_search || '%'`. A B-tree index cannot support that shape — Postgres
falls back to a sequential scan, evaluating every row's email on every request, made worse by the
CTE recomputing the full-match `count(*)` on every call regardless of page.

**Migration `20260817161427_people_pager_sort_tiebreaker_and_search_escape` (Decision #3 — was
"ship now vs. defer") shipped two of the three planned items; the third was attempted and blocked:**

1. **Tie-breaker sort** (§1): `ORDER BY m.created_at DESC, m.id DESC`. Shipped, verified live.
2. **Wildcard escaping (Decision #5 — resolved "yes"):** literal `%`/`_` in `p_search` currently
   act as SQL wildcards (searching `_` matches every email) — not a security issue (`p_search` is
   parameterized, never injectable), but a semantics one.
   `replace(replace(p_search, '%', '\%'), '_', '\_')` with `ESCAPE '\'` is **incomplete on its
   own** — an audit pass caught that it never escapes a literal backslash in the search term
   itself, so a query like `user\name` hits Postgres's own `ESCAPE '\'` clause with an unescaped
   backslash and raises `SQLSTATE 22025` (invalid escape sequence) as an unhandled 500, not a
   graceful "no matches." The escape character has to be escaped **first**, before `%`/`_`:
   `replace(replace(replace(p_search, '\', '\\'), '%', '\%'), '_', '\_')` with the same
   `ESCAPE '\'` clause, so search stays literal-substring for every input including a backslash.
   Shipped, verified live against `'user\name'`, `'_'`, `'%'`, and a real substring (`'midoxp'`,
   3 matches) via `execute_sql` — no `SQLSTATE 22025`, no false wildcard matches.
3. **Trigram index for the email search — attempted, blocked, deferred.** The planned
   `create index ... on auth.users using gin ((email::text) extensions.gin_trgm_ops)` failed with
   `42501: must be owner of table users` the first time this migration was run: `auth.users` is
   owned by `supabase_auth_admin` on this hosted project, and the `postgres` migration role is
   **not** a member of that role (confirmed via `pg_auth_members` — no grant exists, and nothing in
   this project's access grants one). This is Supabase's own auth-schema protection working as
   designed, not a bug to route around from a migration. Because `apply_migration` runs each
   migration as a single transaction, the failed `CREATE INDEX` rolled back the *entire* migration
   including the two items above — confirmed by re-checking `pg_extension` (no `pg_trgm`) and
   `pg_get_functiondef` (function unchanged) immediately after the failure, before re-running with
   the index statement removed. **Deferred, not shipped.** At today's row count (4 accounts) the
   existing sequential scan costs low single-digit milliseconds regardless (§1's volume/latency
   table), so nothing is unsafe about shipping without it now. Revisit before the accounts table
   grows past roughly the 1,000–20,000 row band in that table — the two real options are (a) get
   Supabase support to grant `postgres` membership in `supabase_auth_admin` (or run the index
   creation through the Supabase dashboard SQL editor under a role that already has it, if one
   does), or (b) denormalize `email` onto `public.profiles` (which `postgres` does own) via a
   trigger kept in sync with `auth.users`, and index that copy instead — a materially bigger change
   than this feature scoped, so not attempted here without its own review.
4. Documented in the migration comments — including the exact `42501` failure and why the index
   was left out — so a future reader isn't left guessing why a trigram index that was clearly
   planned for isn't there.

**`offset` overflow cap (Decision #4 — resolved):** Postgres `int4` maxes at 2,147,483,647; a
malformed or adversarial `offset` at or beyond that raises an unhandled `SQLSTATE 22003`. Cap it
well below that in the Python layer — `offset = min(offset, 1_000_000)` — turning a possible 500
into a normal clamped response.

**Shared helper (Decision #7 — resolved):** extract `_parse_pagination_params(request)` in
`web/api/admin.py` and use it in both `/api/users` (`admin.py:246-247`) and `/api/audit`
(`admin.py:747-748`), which currently duplicate the identical clamping block verbatim (§0). Apply
the new overflow cap there once, not twice.

---

## 8. Security posture — audited, no gaps requiring a fix beyond §7

Full pass against `web/api/admin.py` and the RPC's grants, confirming what's already solid before
adding anything:

- **Unbounded limit / resource exhaustion:** protected — `limit` clamped to `[1,200]` in both the
  Python gateway and the SQL RPC.
- **Negative offset:** protected — clamped to `≥ 0` in both layers.
- **Type coercion failures:** protected — non-numeric `limit`/`offset` raise `ValueError`/
  `TypeError`, caught, returned as `400 invalid_pagination`.
- **Integer overflow / deep-offset abuse:** the one real gap, closed by Decision #4 above.
- **Authentication/authorization:** `admin_bp.before_request` enforces bearer-only admin gating
  (`_gate()`) on every route in scope; the RPC itself has `EXECUTE` revoked from `anon` and
  `authenticated`, callable only via the backend's `service_role` key — direct PostgREST access by
  an unauthorized caller is blocked at the database privilege layer, independent of the API layer.
- **Rate limiting:** `admin_bp` is rate-limited at 60/minute, mitigating pagination-driven
  scraping or automated request floods (per-IP, so a shared corporate NAT shares the pool — a
  separate, already-tracked TODO item, not specific to pagination).
- **Wildcard search semantics:** the one genuine (low-severity) gap, closed by Decision #5 above.

No new security work is required beyond what §7 already covers.

---

## 9. Test coverage — locked

Follow the existing split exactly.

**Backend (`web/tests/test_admin_users.py`):**
- A synthetic set larger than one page: passing `limit`/`offset` returns the expected ordered
  slice and still reports the full filtered `total` (not the page length).
- A search whose matching set exceeds 50: page 1 and page 2 both honor the same `q`, and `total`
  is the filtered count.
- The route's clamp/validation behavior, including the new overflow cap, so the frontend can't
  accidentally depend on an uncapped server value.
- Existing authorization assertions remain in place — pagination must not widen access.
- The extracted `_parse_pagination_params()` helper is exercised identically from both
  `/api/users` and `/api/audit`.

**Browser (`web/tests/test_admin_browser.py`)**, extending the `_open_people` route stub to parse
`q`/`limit`/`offset` and return only the requested slice:
- One-page result: range shown, both pager buttons disabled.
- Multi-page result: Next sends `limit`/`offset=<limit>`, preserves the query, replaces rows,
  shows the new range; Previous returns to offset 0.
- Page-size change: resets offset to 0, requests the new limit, never exceeds the server's 200 cap.
- A search typed while on page 2 sends offset 0 after the debounce and renders the new query's
  first page.
- Out-of-order responses: hold an old response, resolve a newer one first, then release the old
  one — assert the DOM still shows the newer query/page, and that an aborted request is not
  presented as a load failure.
- Repeated Next/Previous activation while a request is pending: controls stay disabled/guarded,
  only one request per transition is issued.
- Arabic rendering: nav/button labels come from the Arabic catalogue, `html` stays `dir="rtl"`,
  range/total render inside `bdi[dir="ltr"]` with no stray bidi control characters.
- The existing pending-search/detail-open test still passes — a delayed list request still cannot
  replace an opened account detail view.
- **New from the visual design pass (§2):** a request resolving inside the 100ms threshold shows
  no `.is-busy-visual` class at any point (assert it's never applied, not just that it's removed);
  a request slower than that does show it and clears it on commit. The page-size `<select>` and
  `#people-search` remain non-disabled throughout an in-flight request. Keyboard focus on
  `#people-next` before a page change that disables it lands on `#people-range-status` afterward
  (the `tabIndex = -1` fallback); focus on a still-enabled control after a page change stays on
  the equivalent element. `aria-controls` on `#people-pager` resolves to a real element id
  (`people-table`).
- **An out-of-bounds offset against the real Supabase backend** returns `users: [], total: 0`
  (not `total > 0`, per the boundary-drift gap in §3) — assert the client resets to offset 0 and
  refetches rather than getting stuck on a permanently-empty page. Note this specific case cannot
  be caught by the in-memory backend double alone, since `InMemoryAdminBackend` doesn't reproduce
  it (§3) — cover it at the browser-test layer, stubbing the exact `{users: [], total: 0}` shape.

**A note for whoever writes the range-status assertions:** `#people-range-status`'s `textContent`
concatenates without inner whitespace (`"Showing1–50of137"`) — spacing comes entirely from CSS
`gap`, not from the text nodes. Assert against the individual child text/`bdi` nodes or the
rendered layout, not against a literal space-containing string in `textContent`.

The existing catalogue-parity test (`test_arabic_catalogue_covers_every_runtime_key`) catches
missing Arabic keys automatically. The existing CSS logical-property contract covers the new
pager rules. The `pg_trgm` index plan needs its own production-like `EXPLAIN`/migration smoke
check — that's a database-level validation, not something the in-memory backend tests can prove.

---

## 10. `ASSET_VERSION` — locked

This repo requires bumping `ASSET_VERSION` in `web/api/app.py` on any commit touching CSS or JS.
This implementation will touch:

- `static/js/admin/handlers.js` — page/page-size state, debounce reset, pager events, sequencing,
  cancellation.
- `static/js/admin/ui.js` — `#people-pager` rendering (`createPeoplePager()`, §2), the new
  `div.admin-table-wrapper` structural element, range, disabled states, live/busy attributes,
  `bdi` nodes, the 100ms-delayed `.is-busy-visual` timer, and focus capture/restoration.
- `static/js/admin/services.js` — only if the transport is extended to carry an `AbortSignal`
  (page arguments themselves are already supported by `users()`).
- `static/css/admin.css` — the full pager stylesheet in §2 (button states, page-size select,
  loading pulse, responsive reflow) — copy directly from §2's corrected CSS block rather than
  re-deriving it.

**Bump `ASSET_VERSION` once**, in the commit that lands the frontend UI (§12 step 4) — including
if only CSS changes in that particular commit. The version feeds the admin module import map, the
static admin script URL, and stylesheet URLs. YAML catalogue changes and server-rendered
template-only changes do not by themselves trigger this rule, but the JS/CSS above does.

---

## 11. Decisions — all resolved 2026-08-17, step 1 (migration) applied and verified live

Each decision is discussed in full in its thematic section (§1–§7); this table is a summary index,
not a second copy of record. §2 (CSS/DOM) and §7 (SQL) hold the authoritative, copy-from-here
specifications referenced throughout §9–§12.

| # | Decision | Resolution |
|---|---|---|
| 1 | Page size | **Operator-customizable**, default 50, via a `25/50/100/200` `<select>` (§2). Not persisted across reloads. |
| 2 | Arabic pager copy | **Ship the draft now** (§6); flag all six keys for native-speaker review before/shortly after release. |
| 3 | `pg_trgm` migration timing | **Ship now** attempted; blocked by `42501` (not owner of `auth.users`) and deferred — tie-breaker + escape fix shipped without it (§7). |
| 4 | `offset` int4-overflow cap | **`min(offset, 1_000_000)`**, in the shared helper (§7). |
| 5 | Escape literal `%`/`_` in `p_search` | **Yes** — `ESCAPE` fix, must also escape a literal backslash first or it 500s on one (§7). |
| 6 | Focus-retention target on page change | **Re-focus the equivalent pager button**, falling back to the range label if disabled (§2). |
| 7 | Extract shared `_parse_pagination_params()` | **Yes**, for `/api/users` + `/api/audit` in the same change (§7). |

No open decisions remain.

---

## 12. Execution order (each step independently shippable/testable)

1. **Migration** — ✅ **applied 2026-08-17** as
   `20260817161427_people_pager_sort_tiebreaker_and_search_escape`: tie-breaker sort + `p_search`
   wildcard escape landed; the `pg_trgm` GIN index was attempted and deferred (blocked by `42501`,
   not a code issue — see §7). No API or frontend change; verified live via `execute_sql` and
   `get_advisors` (§7).
2. **Backend hardening** — extract `_parse_pagination_params()` (limit clamp + offset clamp +
   overflow cap), use it in both routes (§7, §0). Covered by §9's backend tests.
3. **Frontend state + wiring** — `handlers.js` state machine (§3) including `pageSize`,
   `services.js` passing `limit`/`offset`/`AbortSignal`, sequence-token + abort guard (§4),
   page-size change sharing the search invalidation path (§5).
4. **Frontend UI** — `ui.js`'s `createPeoplePager()` (§2's corrected DOM builder, verbatim),
   the new `div.admin-table-wrapper`, the 100ms-delayed loading-visual timer, focus
   capture/restoration, and `admin.css`'s pager stylesheet (§2's corrected CSS block, verbatim).
   Bump `ASSET_VERSION` once, in this commit (§10).
5. **i18n** — all six EN/AR keys, landed alongside step 4 in the same commit (§6) — the catalogue
   parity test fails otherwise.
6. **Tests** — §9's backend and browser cases, landed with the corresponding implementation step
   rather than as a separate pass at the end.

Steps 1–2 (database + backend) can start immediately and in parallel with steps 3–5 (frontend) —
the server already accepts `limit`/`offset` today, so neither side blocks the other. Step 6 tracks
whichever of 1–5 it's testing.

---

## 13. Where the multi-pass cross-checks earned their cost

Two separate cross-check rounds went into this document; both paid for themselves.

**Round 1 — the functional plan (§0–§1, §3–§12).** The implementation-focused pass produced the
more complete build document — state machine, exact DOM structure, an off-by-one-safe range
formula, ARIA busy/live wiring. The research-focused pass, run cold against the same repo with no
visibility into the first, caught three concrete things the first didn't mention — the missing
`id` tie-breaker, the `int4` offset-overflow ceiling, and keyboard focus loss on re-render — while
independently cross-confirming everything else without prompting (both landed on sequence tokens +
`AbortController` for concurrency, and both landed on `<bdi dir="ltr">` for the RTL numerics,
without seeing each other's work).

**Round 2 — the visual/interaction design (§2).** Same shape, different pair of models: a
research pass produced the more complete first visual spec (benchmarked against real products,
full token mapping, complete CSS and DOM builder). A second, critical pass — explicitly briefed to
verify rather than restate — caught twelve real issues, the most serious being an actual
correctness bug (a translated string piped through `innerHTML`, contradicting a rule this same
project has been burned by before) and a DOM order that silently contradicted this document's own
already-locked §2 order. The rest were smaller but still real: a nonexistent ARIA target, an
unreachable focus fallback, a loading treatment that would flash on every fast request, a disabled
control that fought the concurrency model §3–§5 already established, and an overclaimed
accessibility guarantee.

**The pattern across both rounds:** none of the caught issues would have blocked a demo or an
initial "it works." All of them would have shipped as quiet, hard-to-attribute defects — a rare
double-listed account, a crash on a malformed deep link, a broken keyboard flow, a flash of
unnecessary loading chrome on every page turn, a screen-reader user silently losing their place —
discovered months later by someone with no idea where to start looking, if discovered at all. Each
was caught within minutes by a second model with no stake in defending the first pass's work, and
every claim from both rounds was still re-verified by the orchestrator directly against the actual
source before being trusted into this document, rather than taken on any model's self-report. That
three-layer discipline — independent second pass, then direct verification — is what "planning
phase" means for this feature, not a summary of what one model produced.

---

## 14. Implementation, landed 2026-08-17

Three commits, each independently re-verified against source and re-tested before being committed
— the same discipline as the planning phase, now applied to code:

1. **`4278741`** — the migration (§7, §12 step 1). Applied directly to the live Supabase project
   via MCP (delegates have no database access), verified live with `execute_sql` and
   `get_advisors`, then committed. One real deviation from plan surfaced here and nowhere else in
   the plan anticipated it precisely: the `pg_trgm` index on `auth.users.email` is blocked by a
   genuine Supabase platform permission wall (`42501`, `postgres` is not a member of
   `supabase_auth_admin`), not a bug — deferred, documented in §7 and the migration file itself,
   safe at today's 4-row table.
2. **`43d6b67`** — backend hardening + backend tests (§7 Decision #7 and #4, §9, §12 step 2).
   `_parse_pagination_params()` extracted and shared by both routes, overflow cap added, six new
   tests. Implemented by `agy-delegate` (Gemini 3.7 Flash, high); diff read in full, typing imports
   and the `InMemoryAdminBackend._users` seeding pattern independently confirmed against source,
   both pytest gates independently re-run by the orchestrator (not just the delegate's own report).
3. **Frontend** — state machine, pager UI, CSS, i18n, `ASSET_VERSION`, browser tests (§2–§6, §9,
   §10, §12 steps 3–5 and the browser half of step 6). Implemented by `agy-delegate` in one
   dispatch, since the roadmap's own §12 groups these steps into one commit. Reviewed in two
   layers before landing:
   - **The orchestrator's own read**: every diff read in full, including hand-tracing the
     sequence-token/`AbortController`/recursive-`loadPage` interaction through four concurrency
     scenarios (double-click, search-during-fetch, the boundary-drift recursion's `finally`
     ownership handoff, and `AbortError` never reaching the failure toast) to confirm the
     `finally`-block cleanup ownership is never claimed by a superseded request.
   - **A second, independent `agy-delegate` review pass**, explicitly briefed read-only (report
     only, no edits permitted) to trace the same four scenarios plus DOM order, the CSS
     auto-margin regression risk, i18n parity, and test-coverage accuracy against the roadmap.
     Verdict: zero findings at any severity — and its trace of the recursive-`finally` scenario
     independently reached the same conclusion, by the same reasoning, as the orchestrator's own
     pass done beforehand. Folded into this section and its own file removed, per this project's
     one-document convention.
   - **A discovered tooling caveat, not a code issue:** on both the implementation dispatch and
     this review dispatch, `agy`'s own runtime silently re-staged (`git add`) the modified tracked
     files despite the brief explicitly forbidding it — and the review dispatch's structured report
     explicitly (and incorrectly) claimed no such command had run. The orchestrator caught this by
     checking `git status --porcelain` directly rather than trusting the report, and unstaged it
     both times before proceeding. Likely `agy`'s own internal checkpointing rather than a
     deliberate model action, but it means this tool's "I didn't touch git" self-report cannot be
     trusted without independently checking the index — noted here so a future session doesn't
     re-learn it.
   - **Test gates, run independently by the orchestrator, not taken from either delegate's
     report:** fast suite `415 passed, 203 deselected`; full Chromium browser suite
     `200-201 passed, 417 deselected` across two runs, with the one-test discrepancy
     (`test_new_chat.py::test_a_new_answer_still_makes_its_entrance`, unrelated to this feature —
     the chat entrance animation, sharing no touched file) traced to resource contention from
     running the ~7-minute suite concurrently with the review dispatch, not a regression — confirmed
     by re-running that single test in isolation, where it passed cleanly.

No should-fix, minor, or nitpick findings survived either review layer. The TODO item this document
opened with — an account outside the newest 50 could not be found or administered, with a silent,
undetectable truncation as the actual failure mode — is closed.
