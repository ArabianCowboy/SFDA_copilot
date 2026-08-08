/**
 * SFDA Copilot — Runtime translation
 *
 * The catalogue arrives inline as window.__I18N (the `runtime:` subtree of the
 * server-side YAML), so there is no extra request and no CSP change — the page
 * already allows inline script.
 *
 * Switching language reloads the page. That is deliberate, not a shortcut: it
 * re-renders the server-side strings, resets `dir` cleanly rather than
 * live-flipping a laid-out document, and re-fetches the FAQ in the new
 * language. The one cost — losing the transcript — is bought back by
 * Transcript.save()/restore() below, which also makes the transcript survive
 * an ordinary refresh.
 */

const TRANSCRIPT_KEY = 'sfda-transcript';

export const I18n = {
  lang: window.__LANG || 'en',
  _catalog: window.__I18N || {},

  get dir() {
    return this.lang === 'ar' ? 'rtl' : 'ltr';
  },

  /** t('chat.sendFailed') / t('cite.marker', { n: 3 }) */
  t(key, params) {
    const value = key.split('.').reduce((node, part) => node?.[part], this._catalog);
    if (typeof value !== 'string') {
      console.warn('[i18n] missing key:', key);
      return key;
    }
    if (!params) return value;
    return value.replace(/\{(\w+)\}/g, (_, name) =>
      params[name] !== undefined ? params[name] : `{${name}}`
    );
  },

  /** Pick a singular/plural key by count. */
  plural(count, oneKey, manyKey, params = {}) {
    return this.t(count === 1 ? oneKey : manyKey, { ...params, count, n: count });
  },

  set(lang) {
    if (lang === this.lang) return;
    try { localStorage.setItem('lang', lang); } catch { /* private mode */ }
    document.cookie = `lang=${lang};path=/;max-age=31536000;samesite=lax`;
    Transcript.save();
    window.location.reload();
  },

  toggle() {
    this.set(this.lang === 'ar' ? 'en' : 'ar');
  },
};

/**
 * Persist the visible transcript across a reload.
 * sessionStorage, not localStorage: a transcript is per-tab and should not
 * outlive the browsing session.
 */
export const Transcript = {
  save() {
    try {
      const messages = document.getElementById('messages');
      if (!messages) return;
      /* The opening state is server-rendered in the CURRENT language. Saving
         it would restore English copy onto an Arabic page after a switch —
         which is the one thing this module exists to prevent. */
      const turns = [...messages.children]
        .filter(el => !el.hasAttribute('data-chat-intro'))
        .map(el => el.outerHTML)
        .join('');
      sessionStorage.setItem(TRANSCRIPT_KEY, turns);
    } catch { /* quota or private mode */ }
  },

  /**
   * @param {(el: Element) => void} [onRestored] runs on each restored turn.
   *
   * Taken as a callback rather than imported: citations.js already imports
   * I18n from this module, and reaching back into it would make the two
   * mutually dependent for the sake of one DOM sweep.
   */
  restore(onRestored) {
    try {
      const saved = sessionStorage.getItem(TRANSCRIPT_KEY);
      if (!saved) return false;
      sessionStorage.removeItem(TRANSCRIPT_KEY);
      const messages = document.getElementById('messages');
      if (!messages) return false;
      // Appended after the freshly rendered intro, not over it.
      const start = messages.childElementCount;
      messages.insertAdjacentHTML('beforeend', saved);

      /* Only the MARKUP came back. Anything behind it — an answer's source
         passages, say — lives in module memory the reload cleared. Scoped to
         what was just inserted, so restoring cannot touch a live answer. */
      if (onRestored) {
        for (let i = start; i < messages.childElementCount; i++) {
          onRestored(messages.children[i]);
        }
      }

      messages.scrollTop = messages.scrollHeight;
      return true;
    } catch {
      return false;
    }
  },
};

/** Wire the [EN | ع] segmented control. */
export function initLanguageToggle() {
  document.addEventListener('click', (event) => {
    const button = event.target.closest('.lang-toggle-btn');
    if (!button) return;
    const target = button.dataset.lang;
    if (target) I18n.set(target);
    else I18n.toggle();
  });
}
