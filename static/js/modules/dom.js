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

/* One timer for the one toast element. See showToast for why it is not a
   per-call setTimeout any more. */
let toastTimer = null;
let toastDuration = CONFIG.TOAST_DURATION;

function scheduleToastHide(toast) {
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add(CONFIG.CLASSES.HIDDEN), toastDuration);
}

/**
 * Hold an actionable toast open while it is being read or reached.
 *
 * An undo on a timer is a timing constraint on the reader, so the timer stops
 * for anyone who is plainly still deciding — pointer over it, or focus inside
 * it. Bound once per element; the toast is server-rendered and never replaced.
 */
function bindToastHold(toast) {
  if (toast.dataset.holdBound) return;
  toast.dataset.holdBound = '1';

  const hold = () => clearTimeout(toastTimer);
  const release = () => {
    if (!toast.classList.contains(CONFIG.CLASSES.HIDDEN)) scheduleToastHide(toast);
  };

  toast.addEventListener('mouseenter', hold);
  toast.addEventListener('focusin', hold);
  toast.addEventListener('mouseleave', release);
  toast.addEventListener('focusout', release);
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

    clearTimeout(toastTimer);
    toastDuration = duration;

    // Wipes any previous action button along with the previous text.
    toast.textContent = message;
    toast.className = `toast-notification ${isError ? CONFIG.CLASSES.ERROR : CONFIG.CLASSES.SUCCESS}`;

    if (actionLabel && typeof onAction === 'function') {
      toast.classList.add(CONFIG.CLASSES.HAS_ACTION);
      const action = DOMCache.createElement('button', CONFIG.CLASSES.TOAST_ACTION);
      action.type = 'button';
      action.textContent = actionLabel;
      action.addEventListener('click', () => {
        ErrorHandler.hideToast();
        onAction();
      });
      toast.appendChild(action);
      bindToastHold(toast);
    }

    toast.classList.remove(CONFIG.CLASSES.HIDDEN);
    scheduleToastHide(toast);
  },

  hideToast() {
    const toast = DOMCache.get(CONFIG.SELECTORS.TOAST);
    if (!toast) return;
    clearTimeout(toastTimer);
    toast.classList.add(CONFIG.CLASSES.HIDDEN);
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

  clearErrors() {
    const authError = DOMCache.get(CONFIG.SELECTORS.AUTH_ERROR);
    const profileError = DOMCache.get(CONFIG.SELECTORS.PROFILE_ERROR);

    if (authError) {
      authError.classList.add(CONFIG.CLASSES.D_NONE);
      authError.innerHTML = '';
    }

    if (profileError) {
      profileError.classList.add(CONFIG.CLASSES.D_NONE);
      profileError.textContent = '';
    }

    [CONFIG.SELECTORS.LOGIN_FORM, CONFIG.SELECTORS.SIGNUP_FORM]
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
