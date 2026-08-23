/**
 * SFDA Copilot — Citations
 *
 * The answer text arrives carrying numbered markers ([1], [2][5]) that the
 * model wrote against numbered context blocks. This module turns those into
 * interactive markers, and renders the one-line trigger that opens the
 * passages behind them.
 *
 * The passages themselves live in source-panel.js. They used to be rendered
 * here, as a deck of cards under the answer; see that module's header for why
 * they moved.
 *
 * Load-bearing detail: markers are built with createElement AFTER the markdown
 * has been sanitized, so DOMPurify never sees them. Never string-replace into
 * the HTML before sanitizing — that would put attacker-influenced answer text
 * back through the parser.
 */

import { DOMCache } from './dom.js';
import { iconMarkup } from './icons.js';
import { I18n } from './i18n.js';
import { SourcePanel, groupByDocument, isDatedEvidence } from './source-panel.js';

/* Two regexes, deliberately. Sharing one /g regex between .test() in
   acceptNode and .exec() in the replace loop corrupts lastIndex and silently
   drops every other match. */
const CITE_TEST = /\[\d{1,2}\]/;
const CITE_SCAN = /\[(\d{1,2})\]/g;

/**
 * A message id that cannot collide with one from an earlier page load.
 *
 * This was a counter — m1, m2, m3 — reset to zero on every load. The transcript
 * survives a language switch by being re-inserted as saved HTML, so a restored
 * answer arrived still carrying `data-msg="m1"` while the counter handed the
 * NEXT answer that same id. Clicking the old answer's [1] then opened the new
 * answer's sources: a citation resolving to evidence from a different question,
 * silently, with nothing on screen to suggest anything was wrong. On a
 * regulatory surface that is the worst failure this module can produce, worse
 * than showing no sources at all.
 *
 * randomUUID needs a secure context, which http:// on a LAN address is not, so
 * the fallback keeps the guarantee where it is unavailable.
 */
export function nextMessageId() {
  if (crypto?.randomUUID) return `m${crypto.randomUUID()}`;
  return `m${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

/* Every answer's source state, keyed by message id. The panel is global and
   shows one answer at a time, so it cannot hold this itself — a reader
   clicking a marker in an older answer has to be able to swap the panel back
   to that answer's passages.

   Bounded because it is otherwise a slow leak: each entry holds up to eight
   passages with their snippets, nothing removed an entry, and a long session
   on one tab accumulates all of them. The cap is generous — far beyond the
   transcript anyone scrolls back through — and eviction is oldest-first,
   which matches the direction people read. An evicted answer's controls stop
   resolving rather than resolving wrongly: the click handler bails when the
   id is unknown. */
const MAX_TRACKED_ANSWERS = 100;
const stateByMessage = new Map();

function rememberSources(msgId, state) {
  stateByMessage.set(msgId, state);
  while (stateByMessage.size > MAX_TRACKED_ANSWERS) {
    // Map iterates in insertion order, so this is the oldest answer.
    stateByMessage.delete(stateByMessage.keys().next().value);
  }
}

function makeMarker(index, msgId) {
  const button = DOMCache.createElement('button', 'cite-marker');
  button.type = 'button';
  button.dataset.cite = String(index);
  button.dataset.msg = msgId;
  button.textContent = String(index);
  button.setAttribute('aria-label', I18n.t('cite.marker', { n: index }));
  button.setAttribute('aria-controls', 'source-panel');
  return button;
}

/**
 * Replace [n] text with marker elements throughout `scope`.
 *
 * Returns the set of indices that actually became buttons. That return value
 * is what makes this function the authority on which sources an answer can
 * display: the server decides which indices are ALLOWED (membership), the
 * browser decides which are REACHABLE, and the panel shows the intersection.
 *
 * Without it the two sides had to agree about markdown, and they cannot. The
 * server matches regexes against the raw source; this walks the tree `marked`
 * actually produced. Every attempt to close that gap case by case — fenced
 * blocks, inline spans, link syntax — is a guess about a parser, and one such
 * guess already misread "[1][2]" as reference-link syntax and silently dropped
 * a sentence's entire provenance. Intersecting the two answers instead makes
 * the whole class safe by construction: an index the browser could not bind is
 * one the reader could not click, so it is not offered as a source.
 *
 * An index the payload does not carry is left as literal text rather than
 * linkified — a model that cites [9] against 8 sources is hallucinating, and
 * silently linking it to nothing would hide that.
 *
 * Membership, not range: once the payload is filtered to the passages the
 * answer cited, the indices are sparse (1, 3, 7). A `n <= sources.length`
 * test would accept [2] and point it at nothing. This mirrors
 * `extract_cited_indices` in web/services/citations.py, which validates the
 * same way — the two must agree or the server reports a citation the reader
 * cannot click.
 */
export function bindCitations(scope, sources, msgId) {
  const bound = new Set();
  if (!scope || !Array.isArray(sources) || !sources.length) return bound;
  const valid = new Set(sources.map((s) => s.index));

  const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      // Never rewrite inside code, existing links, or a marker we already made.
      if (node.parentElement?.closest('pre, code, a, .cite-marker')) {
        return NodeFilter.FILTER_REJECT;
      }
      return CITE_TEST.test(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    },
  });

  // Collect before mutating: replacing nodes mid-walk invalidates the walker.
  const nodes = [];
  for (let node; (node = walker.nextNode());) nodes.push(node);

  for (const node of nodes) {
    const text = node.nodeValue;
    const fragment = document.createDocumentFragment();
    let last = 0;
    let matched = false;
    let match;

    CITE_SCAN.lastIndex = 0;
    while ((match = CITE_SCAN.exec(text))) {
      const index = Number(match[1]);
      if (!valid.has(index)) continue;

      fragment.append(text.slice(last, match.index), makeMarker(index, msgId));
      bound.add(index);
      last = match.index + match[0].length;
      matched = true;
    }

    if (!matched) continue;
    fragment.append(text.slice(last));
    node.replaceWith(fragment);
  }

  return bound;
}

/**
 * The one line an answer's sources get in the reading column.
 *
 * `state.sources` is what the answer CITED **and** the reader can reach —
 * callers pass the set already intersected with what bindCitations bound. An
 * answer that cited nothing gets an empty list from the server and therefore
 * no element here at all, which is the whole fix. A refusal reading "I cannot
 * answer based on the given information" must not be followed by any source
 * control: the evidence the surface is offering belongs to no claim the answer
 * made.
 *
 * There was an intermediate design where a citation-free answer kept a muted
 * "8 passages retrieved, not cited" line, so a reader auditing the answer
 * could still see what search returned. It reads as a contradiction — the
 * label disclaims the passages while advertising eight of them — and under a
 * refusal it is still evidence attached to an answer that has none. Retrieval
 * candidates are a server-side diagnostic now.
 *
 * Returns null when there is nothing to show, so callers can skip appending.
 */
export function renderSourceTrigger(state, msgId) {
  const sources = state?.sources || [];
  if (!sources.length) return null;

  rememberSources(msgId, state);

  const button = DOMCache.createElement('button', 'source-trigger');
  button.type = 'button';
  button.dataset.msg = msgId;
  button.setAttribute('aria-controls', 'source-panel');
  button.setAttribute('aria-expanded', 'false');

  // Both numbers count the same (cited) set, so they cannot contradict.
  const documents = groupByDocument(sources).length;
  const label =
    `${I18n.t('cite.sourcesLabel')} · ` +
    `${I18n.plural(documents, 'cite.docsOne', 'cite.docsMany')} · ` +
    `${I18n.plural(sources.length, 'cite.passagesOne', 'cite.passagesMany')}`;

  const text = DOMCache.createElement('span');
  text.textContent = label;
  button.append(text);

  /* A stored answer whose corpus has been rebuilt under it still opens — the
     row behind it holds the document, page and passage the model actually
     read, frozen when the answer was written, so opening it shows what was
     read rather than a guess about where that text lives now.

     What changes is that the reader is TOLD. Silently serving a passage from a
     superseded build as though it were current is the one failure this product
     cannot afford; silently withholding it is barely better, because the
     reader cannot then tell "this evidence is dated" from "this answer had no
     sources". `stale` and `unverifiable` are one badge on purpose: to a reader
     they mean the same thing — we cannot confirm this is still in the live
     corpus — and they stay distinct in the payload for logs and tests. */
  if (isDatedEvidence(state?.evidenceState)) {
    button.dataset.evidence = state.evidenceState;
    const badge = DOMCache.createElement('span', 'source-trigger-badge');
    badge.textContent = I18n.t('cite.datedBadge');
    button.append(badge);
  }

  button.insertAdjacentHTML('beforeend', iconMarkup('chevron-right', 12, 'chev'));
  return button;
}

/** Forget every answer's sources, e.g. on logout. */
export function resetCitationState() {
  stateByMessage.clear();
}

/* `neutraliseRestoredCitations` lived here until step 6 and is deliberately
   gone rather than merely unused.
 *
 * It stripped the source controls from a transcript restored out of
 * `sessionStorage`, because only the MARKUP came back — `stateByMessage` lives
 * in module memory, so the passages behind a restored answer were genuinely
 * lost and its controls would have opened an empty panel. A control that does
 * nothing is a worse lie than no control, so the markers reverted to plain
 * text.
 *
 * The transcript now hydrates from durable rows through the same render path a
 * live answer takes, so a restored answer arrives WITH its passages and its
 * controls resolve. Keeping the function would leave a loaded gun: called on a
 * hydrated transcript it would silently strip evidence that is present and
 * correct. */

/**
 * One delegated listener set for the whole transcript, so markers created
 * during streaming are live without rebinding.
 */
export function initCitationInteractions(container) {
  if (!container || container.dataset.citationsBound) return;
  container.dataset.citationsBound = '1';
  SourcePanel.init();

  const highlight = (event) => {
    const marker = event.target.closest?.('.cite-marker');
    if (marker) SourcePanel.highlight(marker.dataset.msg, Number(marker.dataset.cite));
  };
  const clear = (event) => {
    if (event.target.closest?.('.cite-marker')) {
      SourcePanel.highlight(event.target.closest('.cite-marker').dataset.msg, null);
    }
  };

  container.addEventListener('pointerover', highlight);
  container.addEventListener('focusin', highlight);
  container.addEventListener('pointerout', clear);
  container.addEventListener('focusout', clear);

  container.addEventListener('click', (event) => {
    const marker = event.target.closest('.cite-marker');
    if (marker) {
      const msgId = marker.dataset.msg;
      const state = stateByMessage.get(msgId);
      if (!state) return;
      SourcePanel.open(msgId, state, {
        focusIndex: Number(marker.dataset.cite),
        returnFocus: marker,
      });
      return;
    }

    const trigger = event.target.closest('.source-trigger');
    if (trigger) {
      const msgId = trigger.dataset.msg;
      // A second press on the trigger that opened it closes it again.
      // aria-expanded is not touched here: SourcePanel owns it, so that every
      // route in and out leaves exactly one trigger claiming to be open.
      if (SourcePanel.isOpenFor(msgId)) {
        SourcePanel.close();
        return;
      }
      const state = stateByMessage.get(msgId);
      if (!state) return;
      SourcePanel.open(msgId, state, { returnFocus: trigger });
    }
  });
}
