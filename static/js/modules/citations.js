/**
 * SFDA Copilot — Citations
 *
 * The answer text arrives carrying numbered markers ([1], [2][5]) that the
 * model wrote against numbered context blocks. This module turns those into
 * interactive markers bound to a deck of source cards.
 *
 * Load-bearing detail: markers are built with createElement AFTER the markdown
 * has been sanitized, so DOMPurify never sees them. Never string-replace into
 * the HTML before sanitizing — that would put attacker-influenced answer text
 * back through the parser.
 */

import { DOMCache } from './dom.js';

/* Two regexes, deliberately. Sharing one /g regex between .test() in
   acceptNode and .exec() in the replace loop corrupts lastIndex and silently
   drops every other match. */
const CITE_TEST = /\[\d{1,2}\]/;
const CITE_SCAN = /\[(\d{1,2})\]/g;

let deckCounter = 0;

export function nextMessageId() {
  return `m${++deckCounter}`;
}

function makeMarker(index, msgId) {
  const button = DOMCache.createElement('button', 'cite-marker');
  button.type = 'button';
  button.dataset.cite = String(index);
  button.dataset.msg = msgId;
  button.textContent = String(index);
  button.setAttribute('aria-label', `Source ${index}`);
  button.setAttribute('aria-controls', `src-${msgId}-${index}`);
  return button;
}

/**
 * Replace [n] text with marker elements throughout `scope`.
 * Out-of-range indices are left as literal text rather than linkified — a
 * model that cites [9] against 8 sources is hallucinating, and silently
 * linking it to nothing would hide that.
 */
export function bindCitations(scope, sources, msgId) {
  if (!scope || !Array.isArray(sources) || !sources.length) return;

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
      if (index < 1 || index > sources.length) continue;

      fragment.append(text.slice(last, match.index), makeMarker(index, msgId));
      last = match.index + match[0].length;
      matched = true;
    }

    if (!matched) continue;
    fragment.append(text.slice(last));
    node.replaceWith(fragment);
  }
}

function pct(score) {
  if (typeof score !== 'number') return 0;
  return Math.max(0, Math.min(100, Math.round(score * 100)));
}

function fmt(score) {
  return typeof score === 'number' ? score.toFixed(2) : '—';
}

/** Build the source deck for one answer. */
export function renderSourceDeck(sources, msgId) {
  const deck = DOMCache.createElement('div', 'source-deck');
  deck.id = `deck-${msgId}`;
  if (!Array.isArray(sources) || !sources.length) return deck;

  const summary = DOMCache.createElement('button', 'source-deck-summary');
  summary.type = 'button';
  summary.setAttribute('aria-expanded', 'false');
  summary.innerHTML =
    `<i class="bi bi-chevron-right chev" aria-hidden="true"></i>` +
    `<span>${sources.length} source${sources.length === 1 ? '' : 's'}</span>`;
  deck.appendChild(summary);

  const list = DOMCache.createElement('ol', 'source-list');
  list.setAttribute('aria-label', 'Sources');

  for (const source of sources) {
    const card = DOMCache.createElement('li', 'source-card');
    card.id = `src-${msgId}-${source.index}`;
    card.dataset.index = String(source.index);

    const relevance = pct(source.score);
    const snippetId = `snip-${msgId}-${source.index}`;

    card.innerHTML = `
      <button class="source-card-head" type="button" aria-expanded="false" aria-controls="${snippetId}">
        <span class="source-index">${source.index}</span>
        <span class="source-doc" dir="auto"></span>
        <span class="source-page" dir="ltr"></span>
      </button>
      <span class="source-cat"></span>
      <div class="relevance" role="img" aria-label="Relevance ${relevance} percent">
        <div class="relevance-bar" style="--pct:${relevance}%"></div>
      </div>
      <div class="score-split">
        <span class="score" dir="ltr"><b>SEM</b> ${fmt(source.semantic_score)}</span>
        <span class="score" dir="ltr"><b>LEX</b> ${fmt(source.lexical_score)}</span>
      </div>
      <div class="source-snippet" id="${snippetId}" dir="auto" hidden></div>`;

    /* Document names, categories and snippets are model- and corpus-derived,
       so they go in as text, never as markup. */
    card.querySelector('.source-doc').textContent = source.document;
    card.querySelector('.source-page').textContent = source.page != null ? `p. ${source.page}` : '';
    card.querySelector('.source-cat').textContent = source.category || '';
    card.querySelector('.source-snippet').textContent = source.snippet || '';

    list.appendChild(card);
  }

  deck.appendChild(list);
  return deck;
}

function litCards(on) {
  document.querySelectorAll('.source-card.is-lit').forEach(c => c.classList.remove('is-lit'));
  document.querySelectorAll('.cite-marker.is-active').forEach(m => m.classList.remove('is-active'));
  if (!on) return;
  const card = document.getElementById(`src-${on.dataset.msg}-${on.dataset.cite}`);
  card?.classList.add('is-lit');
  on.classList.add('is-active');
}

/**
 * One delegated listener set for the whole transcript, so markers created
 * during streaming are live without rebinding.
 */
export function initCitationInteractions(container) {
  if (!container || container.dataset.citationsBound) return;
  container.dataset.citationsBound = '1';

  const highlight = (event) => {
    const marker = event.target.closest?.('.cite-marker');
    if (marker) litCards(marker);
  };
  const clear = (event) => {
    if (event.target.closest?.('.cite-marker')) litCards(null);
  };

  container.addEventListener('pointerover', highlight);
  container.addEventListener('focusin', highlight);
  container.addEventListener('pointerout', clear);
  container.addEventListener('focusout', clear);

  container.addEventListener('click', (event) => {
    const marker = event.target.closest('.cite-marker');
    if (marker) {
      const deck = document.getElementById(`deck-${marker.dataset.msg}`);
      openDeck(deck);
      const card = document.getElementById(`src-${marker.dataset.msg}-${marker.dataset.cite}`);
      card?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      toggleSnippet(card?.querySelector('.source-card-head'), true);
      return;
    }

    const summary = event.target.closest('.source-deck-summary');
    if (summary) {
      const deck = summary.closest('.source-deck');
      deck.classList.contains('is-open') ? closeDeck(deck) : openDeck(deck);
      return;
    }

    const head = event.target.closest('.source-card-head');
    if (head) toggleSnippet(head);
  });
}

function openDeck(deck) {
  if (!deck) return;
  deck.classList.add('is-open');
  deck.querySelector('.source-deck-summary')?.setAttribute('aria-expanded', 'true');
}

function closeDeck(deck) {
  if (!deck) return;
  deck.classList.remove('is-open');
  deck.querySelector('.source-deck-summary')?.setAttribute('aria-expanded', 'false');
}

function toggleSnippet(head, forceOpen = false) {
  if (!head) return;
  const snippet = document.getElementById(head.getAttribute('aria-controls'));
  if (!snippet) return;
  const open = forceOpen || snippet.hidden;
  snippet.hidden = !open;
  head.setAttribute('aria-expanded', String(open));
}
