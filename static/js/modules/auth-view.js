/**
 * SFDA Copilot — Authentication view coordinator
 *
 * Owns authenticated/unauthenticated visibility and the transition between
 * those views. Data services deliberately know nothing about this module.
 */

import { CONFIG } from './config.js';
import { DOMCache } from './dom.js';
import { RobotStateManager } from './robot.js';
import { I18n } from './i18n.js';

function updateStatusAndActions(user) {
  const isLoggedIn = !!user;
  const statusText = isLoggedIn
    ? I18n.t('auth.loggedInAs', { email: user.email })
    : I18n.t('auth.notLoggedIn');

  DOMCache.getAll(`${CONFIG.SELECTORS.USER_STATUS}, ${CONFIG.SELECTORS.USER_STATUS_OFFCANVAS}`).forEach(el => {
    if (el) el.textContent = statusText;
  });

  const authSelectors = [
    CONFIG.SELECTORS.AUTH_BTN,
    CONFIG.SELECTORS.AUTH_BTN_OFFCANVAS,
    CONFIG.SELECTORS.AUTH_BTN_MAIN,
  ];
  const userSelectors = [
    CONFIG.SELECTORS.LOGOUT_BTN,
    CONFIG.SELECTORS.LOGOUT_BTN_OFFCANVAS,
    CONFIG.SELECTORS.PROFILE_BTN,
    CONFIG.SELECTORS.PROFILE_BTN_OFFCANVAS,
  ];

  DOMCache.getAll([...authSelectors, ...userSelectors].join(', ')).forEach(btn => {
    if (!btn) return;
    const isAuthButton = authSelectors.some(selector => btn.matches(selector));
    btn.classList.toggle(CONFIG.CLASSES.D_NONE, isAuthButton ? isLoggedIn : !isLoggedIn);
  });
}

/* Which of the three views is showing. Recovery is a state the shell did not
   have when it was two views and a boolean, and `render(user)` cannot infer it:
   a recovery session carries a user, so it is indistinguishable from a sign-in
   by that argument alone. */
const VIEW = { LANDING: 'landing', CHAT: 'chat', RECOVERY: 'recovery' };
let currentView = null;

/* The pending handle for showAuthenticatedView's delay below. Without this a
   fast sequence — recovery entered while a chat transition is still queued —
   let the stale timer fire afterwards and reveal the chat view over the top. */
let pendingTransition = null;

function cancelPendingTransition() {
  if (pendingTransition !== null) {
    clearTimeout(pendingTransition);
    pendingTransition = null;
  }
}

function showAuthenticatedView() {
  const unauthView = DOMCache.get(CONFIG.SELECTORS.UNAUTH_VIEW);
  const authView = DOMCache.get(CONFIG.SELECTORS.AUTH_VIEW);
  const recoveryView = DOMCache.get(CONFIG.SELECTORS.RECOVERY_VIEW);

  RobotStateManager.transitionToAuthenticatedView();

  cancelPendingTransition();
  pendingTransition = setTimeout(() => {
    pendingTransition = null;
    if (unauthView) unauthView.classList.add(CONFIG.CLASSES.D_NONE);
    if (recoveryView) recoveryView.classList.add(CONFIG.CLASSES.D_NONE);
    if (authView) {
      authView.classList.remove(CONFIG.CLASSES.D_NONE);
      authView.style.animation = 'viewFadeIn 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards';
    }
  }, 300);
}

function showUnauthenticatedView() {
  const unauthView = DOMCache.get(CONFIG.SELECTORS.UNAUTH_VIEW);
  const authView = DOMCache.get(CONFIG.SELECTORS.AUTH_VIEW);
  const recoveryView = DOMCache.get(CONFIG.SELECTORS.RECOVERY_VIEW);

  /* Symmetry with showAuthenticatedView. Without this the landing came back
     with the mascot still held at the last frame of its exit animation. */
  RobotStateManager.transitionToUnauthenticatedView();

  cancelPendingTransition();
  if (authView) authView.classList.add(CONFIG.CLASSES.D_NONE);
  if (recoveryView) recoveryView.classList.add(CONFIG.CLASSES.D_NONE);
  if (unauthView) {
    unauthView.classList.remove(CONFIG.CLASSES.D_NONE);
    unauthView.style.animation = 'viewFadeIn 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards';
  }
}

/**
 * Show the recovery form.
 *
 * Synchronous, unlike `showAuthenticatedView`. That delay exists to let the
 * mascot play its exit before the chat arrives; here it would mean 300ms of
 * landing page painted over a reader who followed a link from their inbox, which
 * is a flash of the wrong page rather than a transition.
 *
 * Note what this does NOT do: it does not ask the server anything. A recovery
 * session has a real access token, so `/api/identity` would answer and the
 * console link could be revealed on a page reached from an emailed link. Not
 * drawing it is view hygiene — the API is gated server-side and stays reachable
 * either way — but there is no reason to draw it.
 */
function showRecoveryView() {
  const unauthView = DOMCache.get(CONFIG.SELECTORS.UNAUTH_VIEW);
  const authView = DOMCache.get(CONFIG.SELECTORS.AUTH_VIEW);
  const recoveryView = DOMCache.get(CONFIG.SELECTORS.RECOVERY_VIEW);

  cancelPendingTransition();
  RobotStateManager.transitionToUnauthenticatedView();

  if (authView) authView.classList.add(CONFIG.CLASSES.D_NONE);
  if (unauthView) unauthView.classList.add(CONFIG.CLASSES.D_NONE);
  if (recoveryView) {
    recoveryView.classList.remove(CONFIG.CLASSES.D_NONE);
    recoveryView.style.animation = 'viewFadeIn 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards';
  }
}

/**
 * Show or hide the console link.
 *
 * Deliberately separate from `render`, and deliberately not driven by the
 * signed-in toggle in `updateStatusAndActions`: that one reveals chrome to
 * *anyone* who signs in, which is exactly wrong for this control. Being an
 * administrator is a second question, answered by the server, and it arrives
 * later than sign-in does.
 *
 * Visibility stays owned by this module because that is what
 * `test_ui_does_not_own_authentication_transitions` protects — the alternative
 * is `app.js` reaching into the DOM to toggle a class, which is how view logic
 * starts leaking out of here.
 *
 * Hiding is courtesy, never a control. `/admin/api/*` is gated server-side, so
 * a reader who unhides this link reaches a page that tells them nothing.
 */
function renderAdminAffordance(isAdmin) {
  const selectors = [
    CONFIG.SELECTORS.ADMIN_BTN,
    CONFIG.SELECTORS.ADMIN_BTN_OFFCANVAS,
  ].join(', ');

  DOMCache.getAll(selectors).forEach(link => {
    if (link) link.classList.toggle(CONFIG.CLASSES.D_NONE, !isAdmin);
  });
}

export const AuthView = {
  /**
   * Draw the view this user implies — unless recovery is in progress.
   *
   * The guard is the load-bearing line. Supabase emits SIGNED_IN *before*
   * PASSWORD_RECOVERY (supabase/auth-js#349), and a recovery session has a user,
   * so without it the very first event of the recovery flow drops the reader
   * into the chat shell holding a session they got from an emailed link. There
   * is exactly one way out of recovery, and it is `leaveRecovery`.
   */
  render(user) {
    if (currentView === VIEW.RECOVERY) return;

    updateStatusAndActions(user);
    // Signing out is the one moment this can be decided locally, and it must
    // be: leaving the link up for the next person on a shared machine is the
    // same shape of leak as a stale `is_admin_hint`.
    if (!user) renderAdminAffordance(false);
    currentView = user ? VIEW.CHAT : VIEW.LANDING;
    user ? showAuthenticatedView() : showUnauthenticatedView();
  },

  /** Enter recovery. Idempotent: the callback and the marker may both fire. */
  renderRecovery() {
    if (currentView === VIEW.RECOVERY) return;
    currentView = VIEW.RECOVERY;
    updateStatusAndActions(null);
    renderAdminAffordance(false);
    showRecoveryView();
  },

  /**
   * Leave recovery, and only then let `render` speak again.
   *
   * Called on cancel and after a completed password change. Deliberately not
   * driven by the SIGNED_OUT event alone: that event does not fire in the demo
   * path (`logout` short-circuits under `?testing=true`) and may not fire at all
   * if sign-out errors — either of which would strand the reader on a form whose
   * work is already done.
   */
  leaveRecovery(user = null) {
    currentView = null;
    this.render(user);
  },

  isRecovering() {
    return currentView === VIEW.RECOVERY;
  },

  renderAdminAffordance,
};
