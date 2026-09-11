/**
 * SFDA Copilot — Session reset on revocation, sign-out, or bfcache restore.
 *
 * docs/ARCHITECTURE.md, "When a session ends in the browser", has the whole picture.
 *
 * Why this exists:
 * /account and /admin are separate entry points that do not subscribe to
 * Supabase's onAuthStateChange. Without subscription:
 * - A live tab keeps showing reader A's record (name, email, role, tier, quota)
 *   or the admin console after A signs out in another tab or is revoked.
 * - A bfcache restore brings the page back as it was, exposing reader A's
 *   private data or operator surface after the session ended.
 *
 * Why reload rather than in-place teardown:
 * Both pages are fresh-read by design (see account.js's "Fresh read on open"
 * comment) and their own init() already renders the right states when nobody is
 * signed in (/account shows #account-signed-out; /admin shows #admin-gate via
 * showAccessFailure). On SIGNED_OUT, USER_DELETED, or any bfcache restore,
 * concealing the page and reloading it lets the page's own init decide.
 *
 * Why it differs from the chat page:
 * The chat page (app.js) tears down in place without reloading because it has
 * a live stream, in-page transcript state, and an unawaited POST /auth/logout
 * on its sign-out path that a page reload would cancel. /account and /admin
 * have no stream and no teardown POST to preserve. The one thing a reload can
 * lose — /account's unsaved identity edits — belongs to a session that has
 * already ended and could not be saved anyway, so its dirty-form guard is stood
 * down for this reload (onForcedReset) rather than allowed to block it.
 *
 * Why pagehide conceals:
 * The snapshot itself is concealed on pagehide (if persisted) because there is
 * no portable guarantee across browsers that a pageshow listener runs before
 * the restored page is painted.
 *
 * Why no reload loop:
 * Subscribing emits INITIAL_SESSION (not SIGNED_OUT), and supabase-js removes
 * the session from storage BEFORE emitting SIGNED_OUT, so the reload that
 * follows a SIGNED_OUT finds no session and emits nothing that would reset it
 * again. A reload is a fresh load, never a bfcache restore, so the pageshow
 * branch cannot re-fire on it either.
 *
 * This module deliberately imports nothing; it takes the Supabase client as a
 * parameter so it cannot pull the chat shell into /admin.
 */

/**
 * Install listeners to reload the page into its unauthenticated state when the
 * session ends or when restored from bfcache.
 *
 * @param {object|null} supabase  the page's Supabase client (Services.supabase)
 * @param {{ onForcedReset?: () => void }} [options]  called once, just before the
 *        reload — /account uses it to stand its dirty-form guard down.
 */
export function installSessionResetOnEnd(supabase, { onForcedReset } = {}) {
  let resetting = false;
  const reset = () => {
    if (resetting) return;
    resetting = true;
    document.body.hidden = true;
    onForcedReset?.();
    window.location.reload();
  };

  supabase?.auth.onAuthStateChange((event) => {
    if (event === 'SIGNED_OUT' || event === 'USER_DELETED') reset();
  });
  window.addEventListener('pagehide', (event) => {
    if (event.persisted) document.body.hidden = true;
  });
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) reset();
  });
}
