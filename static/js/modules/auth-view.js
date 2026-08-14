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

function showAuthenticatedView() {
  const unauthView = DOMCache.get(CONFIG.SELECTORS.UNAUTH_VIEW);
  const authView = DOMCache.get(CONFIG.SELECTORS.AUTH_VIEW);

  RobotStateManager.transitionToAuthenticatedView();

  setTimeout(() => {
    if (unauthView) unauthView.classList.add(CONFIG.CLASSES.D_NONE);
    if (authView) {
      authView.classList.remove(CONFIG.CLASSES.D_NONE);
      authView.style.animation = 'viewFadeIn 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards';
    }
  }, 300);
}

function showUnauthenticatedView() {
  const unauthView = DOMCache.get(CONFIG.SELECTORS.UNAUTH_VIEW);
  const authView = DOMCache.get(CONFIG.SELECTORS.AUTH_VIEW);

  /* Symmetry with showAuthenticatedView. Without this the landing came back
     with the mascot still held at the last frame of its exit animation. */
  RobotStateManager.transitionToUnauthenticatedView();

  if (authView) authView.classList.add(CONFIG.CLASSES.D_NONE);
  if (unauthView) {
    unauthView.classList.remove(CONFIG.CLASSES.D_NONE);
    unauthView.style.animation = 'viewFadeIn 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards';
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
  render(user) {
    updateStatusAndActions(user);
    // Signing out is the one moment this can be decided locally, and it must
    // be: leaving the link up for the next person on a shared machine is the
    // same shape of leak as a stale `is_admin_hint`.
    if (!user) renderAdminAffordance(false);
    user ? showAuthenticatedView() : showUnauthenticatedView();
  },
  renderAdminAffordance,
};
