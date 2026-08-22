/**
 * The conversation pointer — and the URL is the whole of it.
 *
 * docs/per-tab-conversation-deep-linking-plan.md §1, §4.1. There is no
 * per-tab store here, deliberately: §1.2 found that `sessionStorage` is
 * cloned verbatim on tab duplication, which reintroduces the exact
 * cross-tab collision this module exists to remove. No new web-storage key
 * is introduced by this module either — the one piece of state that does
 * not fit in the URL (whether the conversation this tab named has actually
 * landed a first turn yet) rides `history.state` instead, which is scoped
 * to the history ENTRY rather than to the tab, is not web storage, and
 * survives a reload.
 */

const PREFIX = '/c/';

// Werkzeug's `<uuid:>` converter is the format guard server-side; this is
// its client-side mirror. Case-insensitive, then lowercased — the server
// 301s a mismatched case to the canonical form (§4.7), and lowercasing here
// is only what keeps a same-conversation comparison from failing on case
// alone in the instant before that redirect lands.
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function idFromPath(pathname) {
  if (!pathname.startsWith(PREFIX)) return null;
  const raw = pathname.slice(PREFIX.length);
  return UUID_RE.test(raw) ? raw.toLowerCase() : null;
}

function pathFor(id) {
  return id ? `${PREFIX}${id}` : '/';
}

export const Route = {
  /** The conversation the current URL names, or null at `/` (or anywhere
   *  else — an unrecognised path is treated the same as `/`, since this app
   *  has only two client routes). */
  current() {
    return idFromPath(window.location.pathname);
  },

  /**
   * The first-turn transition (§4.2). Moves to `/c/<id>`, REPLACING the
   * current entry — `/` is replaced rather than stacked, so Back from a
   * brand-new conversation goes wherever the reader was before, not to a
   * blank composer.
   *
   * Marks the entry `committed: false`. That marker, not an in-memory flag,
   * is what lets a reload during the first stream tell "this id was just
   * minted and nothing has landed yet" from "this is a conversation with
   * real history" — an in-memory set does not survive the reload it exists
   * to guard against.
   */
  enter(id) {
    window.history.replaceState(
      { ...window.history.state, convId: id, committed: false },
      '', pathFor(id),
    );
  },

  /**
   * Error recovery. Replaces the current entry with `/c/<id>` or `/`
   * (pass a falsy id). Used for EVERY recovery path — a stale deep link, a
   * failed sidebar navigation rolling back, a deleted conversation — and
   * NEVER for a reader's deliberate choice, which is `go()`. Conflating the
   * two produces a Back-button loop: `/c/missing` → 404 → push `/` → Back →
   * `/c/missing` → 404 → push `/`, forever.
   */
  replace(id) {
    window.history.replaceState(
      { ...window.history.state, convId: id || null, committed: true },
      '', pathFor(id),
    );
  },

  /**
   * Deliberate navigation — a sidebar click, New chat. PUSHES a new entry.
   * `popstate` must never call this: pushing over a traversal the reader
   * just performed with Back/Forward would corrupt the very stack they are
   * navigating, which is what makes the refuse-vs-abort split in §4.3 real
   * rather than cosmetic.
   */
  go(id) {
    window.history.pushState({ convId: id || null, committed: true }, '', pathFor(id));
  },

  /**
   * Mark the conversation the URL currently names as durably landed —
   * called once the server has confirmed the turn was persisted (the
   * stream's `final`+`done` with no `persistence_unavailable` error, or the
   * blocking route's `persisted: true`). Not merely arriving at `final`:
   * verified against the actual generator ordering
   * (`app.py:2610` → `:2642` → `:2661`), the durable write itself runs
   * after `final` is yielded, so committing any earlier would reopen the
   * same false-404-on-reload window §4.2 exists to close, just narrower.
   */
  commit() {
    const id = this.current();
    if (!id) return;
    window.history.replaceState(
      { ...window.history.state, convId: id, committed: true },
      '', window.location.pathname + window.location.search,
    );
  },

  /** Whether the entry the URL currently names has landed a first turn —
   *  see `enter`/`commit`. Also true for a fresh navigation whose
   *  `history.state` was never touched by this module at all (a deep link
   *  opened cold, or a reload of an ordinary `/c/<id>` visit): only a state
   *  object THIS TAB WROTE, naming THIS URL, and marked uncommitted, means
   *  "nothing landed yet". Everything else is treated as committed, which is
   *  what lets a cold deep link hydrate normally instead of every unrelated
   *  history entry being mistaken for an abandoned first turn. */
  isCommitted() {
    const state = window.history.state;
    const id = this.current();
    if (!id) return true;
    if (state && state.convId === id && state.committed === false) return false;
    return true;
  },

  /**
   * Wire Back/Forward and bfcache restores to `onNavigate`.
   *
   * `pushState`/`replaceState` never fire `popstate` themselves — only
   * genuine traversal does — which is what makes the rollback in the
   * sidebar's failed-navigation path safe (§4.3): it cannot recursively
   * trigger this handler.
   *
   * `pageshow` with `event.persisted === true` covers the bfcache case §9
   * notes: Chrome now permits bfcaching a `Cache-Control: no-store` page, so
   * a Back into `/c/<id>` can restore the DOM with no `popstate` and no
   * refetch. Re-derived from `current()` rather than trusted as still valid,
   * so a "conversation not found" state fixed since the tab was cached is
   * not shown stale.
   */
  init(onNavigate) {
    window.addEventListener('popstate', () => onNavigate({ persisted: false }));
    window.addEventListener('pageshow', (event) => {
      if (event.persisted) onNavigate({ persisted: true });
    });
  },
};
