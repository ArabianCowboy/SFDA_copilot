/**
 * SFDA Copilot — Source panel
 *
 * The evidence behind one answer, in a surface of its own.
 *
 * This replaces the inline deck, which rendered every retrieved passage as a
 * card directly under the answer. Eight cards under a two-line reply buried
 * the reply, and — because the passages were sent before the model had even
 * been called — they appeared under refusals too, so an answer that cited
 * nothing looked thoroughly sourced. Both problems come from the same place:
 * provenance was being asserted in the reading column, at a size proportional
 * to how much was retrieved rather than how much was used.
 *
 * So the transcript keeps one line — a trigger naming the documents — and the
 * passages live here, opened on request. `.chat-rail` was always where this
 * was meant to land; the comments in base.css and index.html have said "and,
 * from Phase 4, the source deck" since the rail was built.
 *
 * Two presentations, one component:
 *
 *   ≥1200px  the rail, a real grid column. NOT modal: it sits beside the
 *            transcript rather than over it, so the answer stays readable
 *            while its sources are open. No backdrop, no focus trap — a
 *            trap here would be a lie about what is reachable.
 *   <1200px  a bottom sheet, which IS modal, because it covers the reading
 *            column. Backdrop, focus containment, Escape.
 *
 * The mode is re-evaluated on resize, so a panel open at 1400px survives being
 * dragged down to 900px by re-mounting rather than by having two components
 * that drift apart.
 */

import { DOMCache } from './dom.js';
import { iconMarkup, categoryIcon } from './icons.js';
import { I18n } from './i18n.js';
import { RobotStateManager } from './robot.js';

const RAIL_QUERY = '(min-width: 1200px)';

const FOCUSABLE =
  'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** Two decimal places, or an em-dash for a score the payload did not carry. */
function fmt(score) {
  return typeof score === 'number' ? score.toFixed(2) : '—';
}

/**
 * Group passages under their document, preserving first-appearance order.
 *
 * Sources arrive sorted by score, so the strongest document leads and the
 * order within a group is retrieval order. Nothing is re-sorted and nothing is
 * re-indexed: `source.index` IS the citation number the answer wrote, and the
 * only thing grouping changes is which heading a passage sits beneath.
 *
 * This is where the density comes from — eight passages are typically three
 * documents, and printing the filename once per document instead of once per
 * passage is most of the difference between a wall and a list.
 */
export function groupByDocument(sources) {
  const groups = new Map();
  for (const source of sources) {
    const key = source.document || '';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(source);
  }
  return [...groups].map(([document, items]) => ({ document, sources: items }));
}

/**
 * A corpus filename as a spine label.
 *
 * Every one of the 111 documents in the corpus begins with an ISO date —
 * "2010-08-31_Guideline_on_Allergenic_Products.pdf" — so truncating the raw
 * filename produces "2010-08-31_Gui" for both the allergenics guideline and
 * the antisera one. Three spines would carry the same label and the shelf
 * would be worse than a list. The date and the extension go first, then the
 * underscores, and only what is left gets truncated (by CSS, so the full name
 * survives in the passage card and the title attribute).
 */
export function documentLabel(name) {
  const cleaned = String(name || "")
    .replace(/\.pdf$/i, "")
    .replace(/^\d{4}-\d{2}-\d{2}[_-]/, "")
    .replace(/_+/g, " ")
    .trim();
  return cleaned || I18n.t("cite.unknownDocument");
}

/**
 * Whether an answer's evidence predates the corpus the app is serving now.
 *
 * The server sends three states and the surface shows two. `verified` is the
 * ordinary case and says nothing. `stale` (the corpus was rebuilt under this
 * answer) and `unverifiable` (one side or the other carries no build id) both
 * reduce to the same honest sentence for a reader — we cannot confirm this is
 * still in the live corpus — so they share one badge, and stay distinct in the
 * payload where a log or a test can tell them apart.
 *
 * MISSING IS NOT DATED. An answer rendered before this field existed, or by a
 * caller that does not set it, is left alone rather than badged: warning about
 * every answer is the same as warning about none.
 *
 * It lives here rather than in citations.js because citations.js already
 * imports this module; the reverse would close a cycle.
 */
export function isDatedEvidence(evidenceState) {
  return evidenceState === 'stale' || evidenceState === 'unverifiable';
}

export const SourcePanel = {
  _panel: null,
  _backdrop: null,
  _msgId: null,
  _returnFocus: null,
  _isModal: false,
  _mql: null,

  /** Build the element once and bind everything that outlives a single open. */
  init() {
    if (this._panel) return;

    const panel = DOMCache.createElement('aside', 'source-panel');
    panel.id = 'source-panel';
    panel.hidden = true;
    panel.setAttribute('aria-labelledby', 'source-panel-title');
    panel.innerHTML =
      `<div class="source-panel-head">` +
      `<h2 class="source-panel-title" id="source-panel-title"></h2>` +
      `<button type="button" class="source-panel-close">${iconMarkup('close', 16)}</button>` +
      `</div>` +
      `<p class="source-panel-dated" hidden></p>` +
      `<div class="source-panel-body"></div>` +
      `<div class="passage-card" hidden>` +
      `<div class="passage-card-head">` +
      `<span class="passage-index"></span>` +
      `<span class="passage-page" dir="ltr"></span>` +
      `<button type="button" class="passage-close">${iconMarkup('close', 14)}</button>` +
      `</div>` +
      `<p class="passage-doc" dir="auto"></p>` +
      `<p class="passage-snippet" dir="auto"></p>` +
      `<span class="passage-cat"></span>` +
      `</div>`;

    const backdrop = DOMCache.createElement('div', 'source-panel-backdrop');
    backdrop.hidden = true;

    document.body.append(backdrop, panel);
    this._panel = panel;
    this._backdrop = backdrop;

    panel.addEventListener('click', (event) => {
      if (event.target.closest('.source-panel-close')) {
        this.close();
        return;
      }
      const tab = event.target.closest('.spine-tab');
      if (tab) {
        const index = Number(tab.dataset.index);
        // A second press on the open tab closes it, like the trigger.
        if (tab.classList.contains('is-open')) this._closePassage();
        else this._openPassage(index);
        return;
      }
      if (event.target.closest('.passage-close')) {
        this._closePassage();
        return;
      }

      const toggle = event.target.closest('.source-diag-toggle');
      if (toggle) {
        const list = document.getElementById(toggle.getAttribute('aria-controls'));
        const open = list?.hidden;
        if (list) list.hidden = !open;
        toggle.setAttribute('aria-expanded', String(!!open));
      }
    });

    backdrop.addEventListener('click', () => this.close());

    document.addEventListener('keydown', (event) => {
      if (this._panel.hidden) return;
      if (event.key === 'Escape') {
        event.stopPropagation();
        this.close();
        return;
      }
      // Containment applies only to the sheet. In the rail the panel is a
      // sibling region, and trapping Tab inside it would strand the reader
      // away from the transcript and the composer.
      if (event.key === 'Tab' && this._isModal) this._containFocus(event);
    });

    // Re-mount rather than maintain two components. Rebuilding on a breakpoint
    // cross is cheap and happens only while the panel is open.
    this._mql = window.matchMedia(RAIL_QUERY);
    const onModeChange = () => {
      if (!this._panel.hidden) this._mount();
    };
    this._mql.addEventListener?.('change', onModeChange);
  },

  /** True when the panel is showing this specific answer's sources. */
  isOpenFor(msgId) {
    return !!this._panel && !this._panel.hidden && this._msgId === msgId;
  },

  /**
   * Show the evidence for one answer.
   *
   * @param {string} msgId
   * @param {{sources: object[], cited: number[]|null, retrieved: number,
   *          evidenceState?: 'verified'|'stale'|'unverifiable'}} state
   * @param {{focusIndex?: number, returnFocus?: HTMLElement}} [options]
   */
  open(msgId, state, { focusIndex = null, returnFocus = null } = {}) {
    this.init();
    const sources = state?.sources || [];
    if (!sources.length) return;

    // Only capture the return target on a fresh open. Clicking a second marker
    // while the panel is already up should not re-point Escape at that marker
    // — the reader's way back is where they came in.
    if (this._panel.hidden || this._msgId !== msgId) {
      this._returnFocus = returnFocus || document.activeElement;
    }

    this._msgId = msgId;
    this._state = state;
    this._render(state);
    this._mount();
    this._syncTriggers();

    if (focusIndex != null) this.revealPassage(msgId, focusIndex);
  },

  /**
   * Exactly one trigger may claim to be expanded: the one whose answer the
   * panel is showing.
   *
   * Owned here because this object owns the open/closed state. It used to be
   * set by whichever click handler happened to fire, which meant opening
   * answer B left answer A's trigger still claiming expanded, and opening via
   * an inline marker set nothing at all — so the panel could be showing an
   * answer whose own control said it was closed.
   */
  _syncTriggers() {
    document.querySelectorAll('.source-trigger').forEach((el) => {
      el.setAttribute('aria-expanded', String(el.dataset.msg === this._msgId));
    });
  },

  /**
   * Close and empty.
   *
   * `close()` only hides — the passages stay in the DOM, which is fine for an
   * ordinary close and wrong on logout: one reader's evidence would sit in
   * the document while the next one signs in. Anything ending a session uses
   * this instead.
   */
  reset() {
    this.close({ restoreFocus: false });
    if (this._panel) {
      this._panel.querySelector('.source-panel-body').textContent = '';
      this._closePassage();
      this._panel.querySelector('.source-panel-title').textContent = '';
      const dated = this._panel.querySelector('.source-panel-dated');
      dated.textContent = '';
      dated.hidden = true;
    }
  },

  /**
   * @param {{restoreFocus?: boolean}} [options]
   *
   * Focus returns to whatever opened the panel — right when the reader closed
   * it, wrong when something else did. An automatic close (a new question, a
   * logout) would otherwise throw the caret back to an old answer's trigger
   * while the reader is looking somewhere else entirely.
   */
  close({ restoreFocus = true } = {}) {
    if (!this._panel || this._panel.hidden) return;

    this._closePassage();
    RobotStateManager.presentSources(false);
    this._panel.hidden = true;
    this._backdrop.hidden = true;
    this._panel.removeAttribute('role');
    this._panel.removeAttribute('aria-modal');
    document.getElementById('chat-rail')?.classList.remove('rail-shows-sources');
    this._msgId = null;

    /* The panel closes by five routes — the close button, the backdrop,
       Escape, a second press on the trigger, and a new question arriving — and
       only one of those is in a position to reset the trigger itself. With
       _msgId already null this matches nothing, so every trigger goes false
       and none can be left claiming to be expanded over a hidden panel. */
    this._syncTriggers();

    // Returning focus is the whole reason the trigger is a button. Guard the
    // element still being in the document: a language switch re-renders the
    // transcript, so the trigger that opened this may be gone.
    const target = this._returnFocus;
    this._returnFocus = null;
    if (restoreFocus && target && document.contains(target)) target.focus();
  },

  /** Scroll one passage into view and mark it, e.g. after a marker click. */
  revealPassage(msgId, index) {
    if (!this.isOpenFor(msgId)) return;
    // On the shelf a passage IS its tab, so a marker click opens it rather
    // than merely lighting a card the reader would still have to find.
    if (this._panel.querySelector('.spine-tab')) {
      this._openPassage(index);
      this._panel.querySelector(`.spine-tab[data-index="${index}"]`)
        ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      return;
    }
    this._panel.querySelectorAll('.source-card.is-lit')
      .forEach((el) => el.classList.remove('is-lit'));
    const card = this._panel.querySelector(`[data-index="${index}"]`);
    if (!card) return;
    card.classList.add('is-lit');
    card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  },

  /** Transient highlight while a marker is hovered or focused. */
  highlight(msgId, index) {
    if (!this.isOpenFor(msgId)) return;
    this._panel.querySelectorAll('.source-card.is-lit')
      .forEach((el) => el.classList.remove('is-lit'));
    if (index != null) {
      this._panel.querySelector(`[data-index="${index}"]`)?.classList.add('is-lit');
    }
  },

  // ── internals ────────────────────────────────────────────────────────────

  /** Put the panel where this viewport wants it, and set modality to match. */
  _mount() {
    const rail = document.getElementById('chat-rail');
    const useRail = this._mql.matches && !!rail;

    this._isModal = !useRail;
    this._panel.hidden = false;
    this._panel.classList.toggle('is-sheet', !useRail);
    RobotStateManager.presentSources(true);

    if (useRail) {
      rail.appendChild(this._panel);
      // The mascot and the panel share the column. Toggling a class on the
      // rail rather than hiding the companion directly keeps RobotStateManager
      // out of it — it goes on animating behind a display:none, harmlessly,
      // and needs no knowledge that this surface exists.
      rail.classList.add('rail-shows-sources');
      this._backdrop.hidden = true;
      this._panel.removeAttribute('role');
      this._panel.removeAttribute('aria-modal');
    } else {
      document.body.appendChild(this._panel);
      rail?.classList.remove('rail-shows-sources');
      this._backdrop.hidden = false;
      this._panel.setAttribute('role', 'dialog');
      this._panel.setAttribute('aria-modal', 'true');
      this._panel.querySelector('.source-panel-close')?.focus();
    }
  },

  _containFocus(event) {
    const items = [...this._panel.querySelectorAll(FOCUSABLE)]
      .filter((el) => el.offsetParent !== null);
    if (!items.length) return;

    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    const inside = this._panel.contains(active);

    /* Focus that has already escaped — the sheet opens over the transcript,
       and anything can move focus out — is pulled back on the next Tab in
       EITHER direction. Handling only the shift case left forward Tab walking
       away through the page behind the backdrop, which is a trap that only
       works one way and so is not a trap. */
    if (!inside) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
      return;
    }

    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  },

  _render(state) {
    this._panel.querySelector('.source-panel-title').textContent =
      I18n.t('cite.panelTitle');
    this._panel.querySelector('.source-panel-close')
      .setAttribute('aria-label', I18n.t('cite.close'));

    /* Said once, at the top, where a reader decides how much weight to put on
       what follows — not repeated on every card, which would read as an alarm
       about each passage rather than a fact about the answer.

       The sentence has to do real work: these passages ARE what the model read,
       and they are still worth reading, but the corpus has moved since. Wording
       that only said "may be outdated" would invite the reader to discount
       evidence that is a faithful record; wording that said nothing would let
       them quote a superseded regulation to an auditor. */
    const dated = this._panel.querySelector('.source-panel-dated');
    if (isDatedEvidence(state?.evidenceState)) {
      dated.textContent = I18n.t('cite.datedNote');
      dated.hidden = false;
    } else {
      dated.textContent = '';
      dated.hidden = true;
    }

    const body = this._panel.querySelector('.source-panel-body');
    body.textContent = '';

    /* The shelf is a rail form: it reads vertically and needs the column's
       height. In the sheet it would be a second metaphor to validate on the
       breakpoint where it reads worst, so the sheet keeps the grouped list —
       which carries the same fact (how many documents, and where in each). */
    if (this._mql.matches && document.getElementById('chat-rail')) {
      this._renderShelf(state, body);
    } else {
      this._renderList(state, body);
    }

    body.appendChild(this._renderDiagnostics(state.sources || [], this._msgId));
  },

  _renderList({ sources = [], cited = null }, body) {
    const msgId = this._msgId;

    for (const group of groupByDocument(sources)) {
      const section = DOMCache.createElement('section', 'source-group');

      const heading = DOMCache.createElement('h3', 'source-group-doc');
      heading.setAttribute('dir', 'auto');
      // Document names come from the corpus, so they go in as text.
      heading.textContent = group.document || I18n.t('cite.unknownDocument');
      section.appendChild(heading);

      const list = DOMCache.createElement('ol', 'source-passages');
      for (const source of group.sources) {
        const card = DOMCache.createElement('li', 'source-card');
        // The id and data-index are the contract with the inline markers:
        // `[3]` resolves to the passage the model labelled 3, wherever
        // grouping has placed it.
        card.id = `src-${msgId}-${source.index}`;
        card.dataset.index = String(source.index);
        if (Array.isArray(cited) && cited.includes(source.index)) {
          card.classList.add('is-cited');
        }

        card.innerHTML =
          `<div class="source-card-head">` +
          `<span class="source-index">${source.index}</span>` +
          `<span class="source-page" dir="ltr"></span>` +
          `</div>` +
          `<p class="source-snippet" dir="auto"></p>` +
          `<span class="source-cat"></span>`;

        card.querySelector('.source-page').textContent =
          source.page != null ? I18n.t('cite.page', { n: source.page }) : '';
        card.querySelector('.source-snippet').textContent = source.snippet || '';
        card.querySelector('.source-cat').textContent = source.category || '';

        list.appendChild(card);
      }
      section.appendChild(list);
      body.appendChild(section);
    }
  },

  /**
   * The shelf: one spine per cited document, one tab per cited passage.
   *
   * Tabs are ordered by page and spaced EVENLY, never proportionally. A tab
   * placed at a fraction of the spine's height would be claiming a document
   * length nobody knows — the payload carries the page a passage came from,
   * not how many pages the guideline has. Even spacing with the page printed
   * says exactly what is known and nothing more.
   */
  _renderShelf({ sources = [], cited = null }, body) {
    const msgId = this._msgId;
    const groups = groupByDocument(sources);

    const shelf = DOMCache.createElement('div', 'source-shelf');
    // The sparse case is the one that has to look deliberate rather than
    // broken: a single spine gets the full width and presents as one exhibit.
    shelf.dataset.spines = String(groups.length);

    const spines = DOMCache.createElement('ol', 'shelf-spines');

    for (const group of groups) {
      const spine = DOMCache.createElement('li', 'shelf-spine');
      const face = DOMCache.createElement('div', 'spine-face');

      const ordered = [...group.sources].sort(
        (a, b) => (a.page ?? Number.MAX_SAFE_INTEGER) - (b.page ?? Number.MAX_SAFE_INTEGER)
      );

      ordered.forEach((source, i) => {
        const tab = DOMCache.createElement('button', 'spine-tab');
        tab.type = 'button';
        tab.id = `src-${msgId}-${source.index}`;
        tab.dataset.index = String(source.index);
        tab.setAttribute('aria-expanded', 'false');
        // Even spacing: the i-th of n tabs sits at (i+1)/(n+1) of the face.
        tab.style.setProperty('--at', `${((i + 1) / (ordered.length + 1)) * 100}%`);
        if (Array.isArray(cited) && cited.includes(source.index)) {
          tab.classList.add('is-cited');
        }

        const num = DOMCache.createElement('span', 'tab-index');
        num.textContent = String(source.index);

        const page = DOMCache.createElement('span', 'tab-page');
        // Latin digits, isolated. The model is told to keep page numbers in
        // Latin form and the citation markers already are; a page rendered in
        // Arabic-Indic digits beside a Latin marker on the same tab is
        // incoherent, and Azeret Mono has no tabular figures for them.
        page.setAttribute('dir', 'ltr');
        page.textContent = source.page != null
          ? I18n.t('cite.pageShort', { n: source.page })
          : '';
        tab.setAttribute('aria-label', source.page != null
          ? I18n.t('cite.tabAria', { n: source.index, page: source.page })
          : I18n.t('cite.tabAriaNoPage', { n: source.index }));

        tab.append(num, page);
        face.appendChild(tab);
      });

      const head = DOMCache.createElement('div', 'spine-head');
      const glyph = categoryIcon(group.sources[0]?.category);
      if (glyph) head.innerHTML = iconMarkup(glyph, 14, 'spine-glyph');

      const label = DOMCache.createElement('p', 'spine-label');
      const full = group.document || I18n.t('cite.unknownDocument');
      label.textContent = documentLabel(full);
      label.title = full;

      spine.append(head, face, label);
      spines.appendChild(spine);
    }

    shelf.appendChild(spines);
    body.appendChild(shelf);
  },

  /** The passage behind a tab, over the shelf, with its spine still visible. */
  _openPassage(index) {
    const source = (this._state?.sources || []).find(s => s.index === index);
    if (!source) return;

    this._panel.querySelectorAll('.spine-tab').forEach((t) => {
      t.setAttribute('aria-expanded', String(Number(t.dataset.index) === index));
      t.classList.toggle('is-open', Number(t.dataset.index) === index);
    });

    const card = this._panel.querySelector('.passage-card');
    card.hidden = false;
    card.querySelector('.passage-doc').textContent =
      source.document || I18n.t('cite.unknownDocument');
    card.querySelector('.passage-page').textContent = source.page != null
      ? I18n.t('cite.page', { n: source.page })
      : I18n.t('cite.pageUnknown');
    card.querySelector('.passage-snippet').textContent = source.snippet || '';
    card.querySelector('.passage-cat').textContent = source.category || '';
    card.querySelector('.passage-index').textContent = String(source.index);
    card.querySelector('.passage-close')
      .setAttribute('aria-label', I18n.t('cite.closePassage'));
  },

  _closePassage() {
    const card = this._panel.querySelector('.passage-card');
    if (card) card.hidden = true;
    this._panel.querySelectorAll('.spine-tab').forEach((t) => {
      t.setAttribute('aria-expanded', 'false');
      t.classList.remove('is-open');
    });
  },

  /**
   * Raw retrieval scores, collapsed.
   *
   * These used to be a bar on every card, width = score * 100. That read as a
   * calibrated confidence in the answer, which it is not: it is a configurable
   * blend of two cosine similarities with a heuristic penalty applied, and a
   * near-empty bar beside a passage the answer actually cited undermined a
   * correct answer. No bars, no percentages, no colour — figures, behind a
   * disclosure, labelled as what they are.
   */
  _renderDiagnostics(sources, msgId) {
    const wrap = DOMCache.createElement('div', 'source-diagnostics');
    const listId = `diag-${msgId}`;

    const toggle = DOMCache.createElement('button', 'source-diag-toggle');
    toggle.type = 'button';
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-controls', listId);
    toggle.innerHTML =
      iconMarkup('chevron-right', 12, 'chev') +
      `<span>${I18n.t('cite.diagnostics')}</span>`;

    const list = DOMCache.createElement('div', 'source-diag-list');
    list.id = listId;
    list.hidden = true;

    const note = DOMCache.createElement('p', 'source-diag-note');
    note.textContent = I18n.t('cite.diagnosticsNote');
    list.appendChild(note);

    for (const source of sources) {
      const row = DOMCache.createElement('div', 'source-diag-row');
      row.innerHTML =
        `<span class="source-index">${source.index}</span>` +
        `<span class="source-diag-score" dir="ltr"></span>`;
      row.querySelector('.source-diag-score').textContent =
        `${I18n.t('cite.combinedMatch')} ${fmt(source.score)}   ` +
        `${I18n.t('cite.semanticMatch')} ${fmt(source.semantic_score)}   ` +
        `${I18n.t('cite.keywordMatch')} ${fmt(source.lexical_score)}`;
      list.appendChild(row);
    }

    wrap.append(toggle, list);
    return wrap;
  },
};
