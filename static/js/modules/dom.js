/**
 * SFDA Copilot — Core helpers
 * DOM caching and centralised error presentation.
 */

import { CONFIG } from './config.js';
import { I18n } from './i18n.js';
import { iconMarkup } from './icons.js';

/* ——————————————— DOM CACHE ——————————————— */

export const DOMCache = {
  elements: new Map(),

  get(selector) {
    if (!this.elements.has(selector)) {
      this.elements.set(selector, document.querySelector(selector));
    }
    return this.elements.get(selector);
  },

  getAll(selector) {
    return document.querySelectorAll(selector);
  },

  createElement(tagName, ...classes) {
    const el = document.createElement(tagName);
    if (classes.length) el.classList.add(...classes);
    return el;
  },

  setAttributes(element, attributes = {}) {
    for (const [key, value] of Object.entries(attributes)) {
      element.setAttribute(key, value);
    }
  },
};

/* ——————————————— TOAST TIMING ——————————————— */

/* There is ONE #toast element and many callers, so every piece of state below
   is shared and has to be torn down between messages rather than accumulated.
   The countdown made that a correctness problem instead of a tidiness one: a
   status toast firing mid-undo inherits whatever the previous one left behind. */
let toastTimer = null;
let toastRemaining = 0;
let toastResumeAt = 0;

/* Bumped on every show and hide. A timeout or an action handler from a toast
   that has since been replaced compares its captured id and declines to act. */
let toastId = 0;

/* Two independent hold channels — pointer and focus — so hovering the toast
   and then tabbing into its action does not subtract the same elapsed span
   twice, and leaving with focus still inside does not resume early. */
let pointerHeld = false;
let focusHeld = false;

/** Drop every trace of the toast currently on screen. */
function resetToastState(toast) {
  clearTimeout(toastTimer);
  toastTimer = null;
  toastRemaining = 0;
  toastResumeAt = 0;
  pointerHeld = false;
  focusHeld = false;
  toastId += 1;

  toast.classList.remove(CONFIG.CLASSES.IS_HELD);
  toast.style.removeProperty('--toast-duration');
  return toastId;
}

function armToastHide(toast, id) {
  clearTimeout(toastTimer);
  toastResumeAt = performance.now();
  toastTimer = setTimeout(() => {
    if (id !== toastId) return;
    toast.classList.add(CONFIG.CLASSES.HIDDEN);
  }, toastRemaining);
}

/**
 * Hold a toast open while it is being read or reached.
 *
 * An undo on a timer is a timing constraint on the reader, so the clock stops
 * for anyone plainly still deciding. The countdown rule is a CSS animation on
 * the toast's own ::after, paused by the same class — pausing an animation
 * freezes its elapsed time, so the bar and the timeout stay in step without
 * either one driving the other.
 *
 * Bound once per element; the toast is server-rendered and never replaced.
 */
function bindToastHold(toast) {
  if (toast.dataset.holdBound) return;
  toast.dataset.holdBound = '1';

  const held = () => pointerHeld || focusHeld;

  const hold = (channel) => () => {
    if (toast.classList.contains(CONFIG.CLASSES.HIDDEN)) return;
    const wasHeld = held();
    if (channel === 'pointer') pointerHeld = true; else focusHeld = true;
    if (wasHeld) return;                       // already stopped; do not subtract twice

    clearTimeout(toastTimer);
    toastRemaining = Math.max(0, toastRemaining - (performance.now() - toastResumeAt));
    toast.classList.add(CONFIG.CLASSES.IS_HELD);
  };

  const release = (channel) => () => {
    if (!held()) return;
    if (channel === 'pointer') pointerHeld = false; else focusHeld = false;
    if (held()) return;                        // the other channel still holds it

    toast.classList.remove(CONFIG.CLASSES.IS_HELD);
    if (!toast.classList.contains(CONFIG.CLASSES.HIDDEN)) armToastHide(toast, toastId);
  };

  toast.addEventListener('mouseenter', hold('pointer'));
  toast.addEventListener('focusin', hold('focus'));
  toast.addEventListener('mouseleave', release('pointer'));
  toast.addEventListener('focusout', release('focus'));
}

/* ——————————————— ERROR HANDLER ——————————————— */

export const ErrorHandler = {
  formatAuthError(error) {
    const message = error?.message?.toLowerCase() || '';
    /* Built per call, not once at module load, so the catalogue is already
       populated and a language switch is reflected. */
    const errorMap = {
      'invalid login credentials': I18n.t('auth.invalidCredentials'),
      'email not confirmed': I18n.t('auth.emailNotConfirmed'),
      'user already registered': I18n.t('auth.alreadyRegistered'),
      'to be a valid email': I18n.t('auth.invalidEmail'),
      /* GoTrue's own email limiter, reached from signup as well as recovery.
         Its text is English-only and blames the reader for a limit the service
         imposed; worse, GoTrue rolls the account back when a send fails, so they
         get no account, no email, and no hint that the address is still free to
         retry. Recovery handles these as status codes from our own endpoint —
         signup gets them here, which is the only place its errors pass through. */
      'for security purposes': I18n.t('auth.tooSoon'),
      'only request this after': I18n.t('auth.tooSoon'),
      'email rate limit exceeded': I18n.t('auth.emailUnavailable'),
      'over_email_send_rate_limit': I18n.t('auth.emailUnavailable'),
    };
    for (const key in errorMap) {
      if (message.includes(key)) return errorMap[key];
    }
    return error?.message || 'An unknown authentication error occurred.';
  },

  /**
   * Show a toast, optionally carrying one action.
   *
   * The hide timer is held in module scope rather than being a bare setTimeout
   * per call. It used to be the latter, which was harmless while every toast
   * was a status line: the worst case was one message hiding a moment early.
   * It stops being harmless the moment a toast carries an Undo — a status
   * toast fired seconds earlier would take the control away with it.
   */
  showToast(message, isError = false, duration = CONFIG.TOAST_DURATION, { actionLabel, onAction } = {}) {
    const toast = DOMCache.get(CONFIG.SELECTORS.TOAST);
    if (!toast) return;

    // Everything the previous message left behind goes first, so a plain status
    // toast can never inherit a countdown — or a paused one.
    const id = resetToastState(toast);

    // Wipes any previous action button along with the previous text.
    toast.textContent = message;
    toast.className = `toast-notification ${isError ? CONFIG.CLASSES.ERROR : CONFIG.CLASSES.SUCCESS}`;

    if (actionLabel && typeof onAction === 'function') {
      toast.classList.add(CONFIG.CLASSES.HAS_ACTION);

      /* The countdown rule is the toast's own ::after, so there is no node to
         insert in the right place, none to mark aria-hidden, and none for a
         test asserting the plain toast's text to trip over. Its length is data,
         so it arrives as a custom property. */
      toast.style.setProperty('--toast-duration', `${duration}ms`);

      const action = DOMCache.createElement('button', CONFIG.CLASSES.TOAST_ACTION);
      action.type = 'button';
      action.textContent = actionLabel;
      action.addEventListener('click', () => {
        if (id !== toastId) return;
        ErrorHandler.hideToast();
        onAction();
      });
      toast.appendChild(action);
      bindToastHold(toast);
    }

    toast.classList.remove(CONFIG.CLASSES.HIDDEN);
    toastRemaining = duration;
    armToastHide(toast, id);
  },

  hideToast() {
    const toast = DOMCache.get(CONFIG.SELECTORS.TOAST);
    if (!toast) return;
    resetToastState(toast);
    toast.classList.add(CONFIG.CLASSES.HIDDEN);
  },

  /**
   * Take the toast down, but only while it is still offering an action.
   *
   * For the caller that ends the thing the action DID — the toast and the undo
   * behind it are one object to a reader, so an Undo button that outlives the
   * undo is a button that lies. The guard is what keeps that from also taking
   * down a plain status toast which had since replaced it, carrying a message
   * the reader has not read yet.
   */
  hideActionToast() {
    const toast = DOMCache.get(CONFIG.SELECTORS.TOAST);
    if (!toast?.querySelector(`.${CONFIG.CLASSES.TOAST_ACTION}`)) return;
    this.hideToast();
  },

  showAuthError(message) {
    const errorEl = DOMCache.get(CONFIG.SELECTORS.AUTH_ERROR);
    if (!errorEl) return;

    /* The glyph is ours, so it goes in as markup; the message is a provider
       error string, so it goes in as text. */
    errorEl.innerHTML = iconMarkup('alert', 16, 'alert-icon');
    const label = document.createElement('strong');
    label.textContent = message;
    errorEl.appendChild(label);
    errorEl.classList.remove(CONFIG.CLASSES.D_NONE);
  },

  showProfileError(message) {
    const errorEl = DOMCache.get(CONFIG.SELECTORS.PROFILE_ERROR);
    if (!errorEl) return;

    errorEl.textContent = message;
    errorEl.classList.remove(CONFIG.CLASSES.D_NONE);
  },

  /* The recovery view sits outside the auth modal, so `#auth-error` is not on
     screen when it needs to say something. Same treatment, its own element. */
  showRecoveryError(message) {
    const errorEl = DOMCache.get(CONFIG.SELECTORS.RECOVERY_ERROR);
    if (!errorEl) return;

    errorEl.textContent = message;
    errorEl.classList.remove(CONFIG.CLASSES.D_NONE);
  },

  clearErrors() {
    const authError = DOMCache.get(CONFIG.SELECTORS.AUTH_ERROR);
    const profileError = DOMCache.get(CONFIG.SELECTORS.PROFILE_ERROR);
    const recoveryError = DOMCache.get(CONFIG.SELECTORS.RECOVERY_ERROR);

    if (authError) {
      authError.classList.add(CONFIG.CLASSES.D_NONE);
      authError.innerHTML = '';
    }

    if (profileError) {
      profileError.classList.add(CONFIG.CLASSES.D_NONE);
      profileError.textContent = '';
    }

    if (recoveryError) {
      recoveryError.classList.add(CONFIG.CLASSES.D_NONE);
      recoveryError.textContent = '';
    }

    [CONFIG.SELECTORS.LOGIN_FORM, CONFIG.SELECTORS.SIGNUP_FORM,
     CONFIG.SELECTORS.RESET_REQUEST_FORM, CONFIG.SELECTORS.RECOVERY_FORM]
      .map(sel => DOMCache.get(sel))
      .filter(Boolean)
      .forEach(form => {
        form.querySelectorAll(`.${CONFIG.CLASSES.INVALID}`).forEach(input => {
          input.classList.remove(CONFIG.CLASSES.INVALID);
        });
        form.classList.remove('was-validated');
      });
  },

  log(error, context = '') {
    console.error(`[SFDA Copilot${context ? ` ${context}` : ''}]`, error);
  },
};

/** Shorthand used throughout the codebase. */
export const logError = (error, context = '') => ErrorHandler.log(error, context);
