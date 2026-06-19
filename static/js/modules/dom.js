/**
 * SFDA Copilot — Core helpers
 * DOM caching and centralised error presentation.
 */

import { CONFIG } from './config.js';

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

/* ——————————————— ERROR HANDLER ——————————————— */

export const ErrorHandler = {
  formatAuthError(error) {
    const message = error?.message?.toLowerCase() || '';
    const errorMap = {
      'invalid login credentials': 'Incorrect email or password.',
      'email not confirmed': 'Please confirm your email before logging in.',
      'user already registered': 'This email is already registered. Please log in.',
      'to be a valid email': 'Please provide a valid email address.',
    };
    for (const key in errorMap) {
      if (message.includes(key)) return errorMap[key];
    }
    return error?.message || 'An unknown authentication error occurred.';
  },

  showToast(message, isError = false, duration = CONFIG.TOAST_DURATION) {
    const toast = DOMCache.get(CONFIG.SELECTORS.TOAST);
    if (!toast) return;

    toast.textContent = message;
    toast.className = `toast-notification ${isError ? CONFIG.CLASSES.ERROR : CONFIG.CLASSES.SUCCESS}`;
    toast.classList.remove(CONFIG.CLASSES.HIDDEN);

    setTimeout(() => toast.classList.add(CONFIG.CLASSES.HIDDEN), duration);
  },

  showAuthError(message) {
    const errorEl = DOMCache.get(CONFIG.SELECTORS.AUTH_ERROR);
    if (!errorEl) return;

    errorEl.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-2"></i><strong>${message}</strong>`;
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
