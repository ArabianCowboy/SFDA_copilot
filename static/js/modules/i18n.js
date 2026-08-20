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
 * language. The one cost — losing the transcript — used to be bought back by a
 * markup copy in `sessionStorage`; it is now bought back properly, by hydrating
 * from durable rows on the way back up, which covers an ordinary refresh and a
 * second device as well. See `App.hydrateTranscript`.
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

    /* `pick_lang` ranks `?lang=` above the cookie (web/utils/i18n.py), so a URL
       carrying one reloads straight back into the language just left — the
       cookie is written and then ignored. Rewrite the parameter in place rather
       than stripping it, because everything else in the query has to survive:
       `?recovery=1` exists precisely to be readable after a reload, and losing
       it would drop a reader mid-recovery back onto the landing page.

       `replace` rather than `reload`, so Back does not return to a URL pinning
       the language they just left. */
    const url = new URL(window.location.href);
    if (url.searchParams.has('lang')) {
      url.searchParams.set('lang', lang);
      window.location.replace(url.toString());
      return;
    }

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
  /**
   * Clear any transcript this tab saved before step 6.
   *
   * ALL THAT REMAINS OF A LARGER OBJECT, and what it used to do is worth
   * recording because the reasons were sound and the mechanism was not.
   *
   * `save()` serialized the rendered turns into `sessionStorage` and `restore()`
   * put the markup back, tagged with `_owner` so one reader's conversation
   * could not surface for the next person to sign in on the same tab. It had
   * exactly one caller — the language toggle, which reloads the page — so an
   * ordinary refresh lost the conversation regardless, a second device never
   * had one, and a restored answer's citations had to be stripped by
   * `neutraliseRestoredCitations` because the markup came back and the
   * passages, which live in module memory, did not.
   *
   * The transcript now hydrates from durable per-account rows through
   * `GET /api/chat/history`, which answers all three. Nothing writes this key
   * any more; this clears it for a tab still carrying one from an older build,
   * and for the sign-out path where leaving a previous reader's turns in
   * storage was the original hazard.
   */
  discard() {
    try {
      sessionStorage.removeItem(TRANSCRIPT_KEY);
    } catch { /* private mode: nothing was stored, nothing to remove */ }
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
