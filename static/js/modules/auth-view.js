/**
 * SFDA Copilot — Authentication view coordinator
 *
 * Owns authenticated/unauthenticated visibility and the transition between
 * those views. Data services deliberately know nothing about this module.
 */

import { CONFIG } from './config.js';
import { DOMCache } from './dom.js';
import { AppState } from './state.js';
import { Effects } from './effects.js';
import { RobotStateManager } from './robot.js';

function updateStatusAndActions(user) {
  const isLoggedIn = !!user;
  const statusText = isLoggedIn ? `Logged in as: ${user.email}` : 'Not logged in';

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
    if (unauthView) {
      unauthView.classList.add(CONFIG.CLASSES.D_NONE);
      const particles = AppState.get('particleBackground');
      if (particles) {
        particles.destroy();
        AppState.set('particleBackground', null);
      }
    }
    if (authView) {
      authView.classList.remove(CONFIG.CLASSES.D_NONE);
      authView.style.animation = 'viewFadeIn 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards';
    }
  }, 300);
}

function showUnauthenticatedView() {
  const unauthView = DOMCache.get(CONFIG.SELECTORS.UNAUTH_VIEW);
  const authView = DOMCache.get(CONFIG.SELECTORS.AUTH_VIEW);

  if (authView) authView.classList.add(CONFIG.CLASSES.D_NONE);
  if (unauthView) {
    unauthView.classList.remove(CONFIG.CLASSES.D_NONE);
    unauthView.style.animation = 'viewFadeIn 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards';
    setTimeout(() => Effects.initParticles(), 100);
  }
}

export const AuthView = {
  render(user) {
    updateStatusAndActions(user);
    user ? showAuthenticatedView() : showUnauthenticatedView();
  },
};
