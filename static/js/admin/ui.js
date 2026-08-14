/**
 * SFDA Copilot — Console rendering
 *
 * Reads the DOM and writes to it. Decides nothing about access and fetches
 * nothing; it is handed an answer and shows it.
 *
 * The console starts hidden and is revealed only once the server has confirmed
 * an administrator. That ordering is why `#admin-console` carries `hidden` in
 * the template and is not merely styled away: DESIGN.md's rule is that content
 * is never hidden by a stylesheet on the promise that a script will unhide it —
 * but here the promise runs the other way. A dead module leaves the console
 * hidden, which is the safe failure.
 */

import { I18n } from '../modules/i18n.js';

const TABS = [
  { tab: 'tab-overview', panel: 'panel-overview' },
  { tab: 'tab-settings', panel: 'panel-settings' },
  { tab: 'tab-people', panel: 'panel-people' },
];

const el = (id) => document.getElementById(id);

/** Replace the access-check placeholder with a final message. */
export function showGateMessage(message) {
  const gate = el('admin-gate');
  if (!gate) return;
  gate.hidden = false;
  const text = gate.querySelector('.admin-gate-text');
  if (text) text.textContent = message;
}

/** Reveal the console. Only ever called after the server confirmed the role. */
export function revealConsole(identity) {
  const gate = el('admin-gate');
  const console_ = el('admin-console');
  if (gate) gate.hidden = true;
  if (!console_) return;
  console_.hidden = false;

  const whoami = el('admin-whoami');
  if (whoami && identity?.email) {
    whoami.hidden = false;
    // dir="ltr" on the element, not the page: an email address inside an
    // Arabic bar would otherwise be reordered by the bidi algorithm.
    whoami.setAttribute('dir', 'ltr');
    whoami.textContent = identity.email;
  }

  TABS.forEach(({ panel }) => {
    const body = el(panel)?.querySelector('.admin-panel-body');
    if (body && !body.textContent.trim()) {
      const empty = document.createElement('p');
      empty.className = 'admin-empty';
      empty.textContent = I18n.t('admin.empty');
      body.appendChild(empty);
    }
  });
}

/** Select one tab, updating both ARIA state and roving tabindex. */
export function selectTab(tabId) {
  TABS.forEach(({ tab, panel }) => {
    const isActive = tab === tabId;
    const tabEl = el(tab);
    const panelEl = el(panel);
    if (tabEl) {
      tabEl.setAttribute('aria-selected', String(isActive));
      // Roving tabindex: one stop for the whole tablist, then arrow keys move
      // within it. Leaving every tab focusable makes Tab walk the set, which is
      // the wrong shape for a tablist.
      tabEl.tabIndex = isActive ? 0 : -1;
    }
    if (panelEl) panelEl.hidden = !isActive;
  });
}

export function focusTab(tabId) {
  el(tabId)?.focus();
}

export const tabIds = () => TABS.map((entry) => entry.tab);
