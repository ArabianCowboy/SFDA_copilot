/**
 * SFDA Copilot — Core helpers
 * DOM caching and centralised error presentation.
 */

import { CONFIG, prefersReducedMotion } from './config.js';
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
    if (channel === 'pointer') pointerHeld = true;
    else focusHeld = true;
    if (wasHeld) return; // already stopped; do not subtract twice

    clearTimeout(toastTimer);
    toastRemaining = Math.max(0, toastRemaining - (performance.now() - toastResumeAt));
    toast.classList.add(CONFIG.CLASSES.IS_HELD);
  };

  const release = (channel) => () => {
    if (!held()) return;
    if (channel === 'pointer') pointerHeld = false;
    else focusHeld = false;
    if (held()) return; // the other channel still holds it

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
      over_email_send_rate_limit: I18n.t('auth.emailUnavailable'),
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
  showToast(
    message,
    isError = false,
    duration = CONFIG.TOAST_DURATION,
    { actionLabel, onAction } = {},
  ) {
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
    const recoveryError = DOMCache.get(CONFIG.SELECTORS.RECOVERY_ERROR);

    if (authError) {
      authError.classList.add(CONFIG.CLASSES.D_NONE);
      authError.innerHTML = '';
    }

    if (recoveryError) {
      recoveryError.classList.add(CONFIG.CLASSES.D_NONE);
      recoveryError.textContent = '';
    }

    [
      CONFIG.SELECTORS.LOGIN_FORM,
      CONFIG.SELECTORS.SIGNUP_FORM,
      CONFIG.SELECTORS.RESET_REQUEST_FORM,
      CONFIG.SELECTORS.RECOVERY_FORM,
    ]
      .map((sel) => DOMCache.get(sel))
      .filter(Boolean)
      .forEach((form) => {
        form.querySelectorAll(`.${CONFIG.CLASSES.INVALID}`).forEach((input) => {
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

/* ——————————————— NOTIFICATION CENTER (broadcast notices) ——————————————— */
/* docs/notification-center-plan.md §4. A sibling to ErrorHandler above, not
   an extension of it: ErrorHandler owns the single #toast slot for this
   reader's OWN request failures; a broadcast is admin-authored, can stack,
   and has three distinct display shapes (toast/banner/modal) with different
   dismissal semantics. Sharing one slot would mean an admin notice and a
   "could not send message" toast fighting over the same element. */

const AUTO_DISMISS_MS = 8000;

export const BroadcastNotice = {
  /* Session-only snooze: a modal closed via Escape/backdrop (not the
     explicit Acknowledge action) is suppressed for the rest of THIS browser
     session so the next poll/reconnect does not reopen it immediately. It
     stays unacknowledged server-side and resurfaces on the next real
     session — see notifications_mark_read's own type-checked action set,
     which has no "snoozed" action because this is deliberately never sent
     to the server at all. */
  _snoozed: new Set(),

  isSnoozed(id) {
    if (this._snoozed.has(id)) return true;
    try {
      return sessionStorage.getItem(`sfda-notif-snooze-${id}`) === '1';
    } catch {
      return false;
    }
  },

  snooze(id) {
    this._snoozed.add(id);
    try {
      sessionStorage.setItem(`sfda-notif-snooze-${id}`, '1');
    } catch {
      /* Private browsing or storage disabled. The in-memory Set still
         covers the rest of this page's life, which is all a snooze ever
         promised — see the plan's own "session-level, not a server fact". */
    }
  },

  /**
   * A corner toast: severity-tinted, auto-dismissing, stackable.
   * `onDismiss(reason)` fires once, with `'auto' | 'manual'`.
   */
  showToast(notification, { onDismiss } = {}) {
    const stack = DOMCache.get(CONFIG.SELECTORS.NOTIFICATIONS_TOAST_STACK);
    if (!stack) return;

    const el = document.createElement('div');
    el.className = `${CONFIG.CLASSES.NOTIF_TOAST} severity-${notification.severity}`;
    el.dataset.notificationId = notification.id;
    el.setAttribute('role', 'status');
    if (!prefersReducedMotion())
      el.style.setProperty('--notif-toast-duration', `${AUTO_DISMISS_MS}ms`);

    const body = document.createElement('div');
    body.className = 'broadcast-toast-body';
    body.setAttribute('dir', 'auto'); // admin-authored, mixed-script safe
    const title = document.createElement('strong');
    title.textContent = notification.title;
    const message = document.createElement('p');
    message.textContent = notification.body;
    body.append(title, message);

    const dismissBtn = document.createElement('button');
    dismissBtn.type = 'button';
    dismissBtn.className = 'broadcast-toast-dismiss';
    dismissBtn.setAttribute('aria-label', I18n.t('chat.notifications.dismiss'));
    dismissBtn.innerHTML = iconMarkup('close', 14);

    el.append(body, dismissBtn);
    stack.appendChild(el);

    let settled = false;
    let timer = null;

    const settle = (reason) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      el.classList.add(CONFIG.CLASSES.NOTIF_TOAST_LEAVING);
      const finish = () => {
        el.remove();
        onDismiss?.(reason);
      };
      if (prefersReducedMotion()) finish();
      else el.addEventListener('animationend', finish, { once: true });
    };

    dismissBtn.addEventListener('click', () => settle('manual'));

    if (!prefersReducedMotion()) {
      // Paused while hovered or focused, mirroring ErrorHandler's own
      // #toast hold behaviour — a countdown a reader is actively engaging
      // with must not remove itself out from under them.
      const hold = () => clearTimeout(timer);
      const resume = () => {
        clearTimeout(timer);
        timer = setTimeout(() => settle('auto'), AUTO_DISMISS_MS);
      };
      el.addEventListener('mouseenter', hold);
      el.addEventListener('focusin', hold);
      el.addEventListener('mouseleave', resume);
      el.addEventListener('focusout', resume);
      resume();
    }

    return { dismiss: () => settle('manual') };
  },

  /**
   * The single-slot banner. `aria-live="polite"` and deliberately never
   * steals keyboard focus on arrival — forced focus is reserved for the
   * acknowledgement modal alone, per the plan's own accessibility rule.
   */
  showBanner(notification, { onDismiss } = {}) {
    const el = DOMCache.get(CONFIG.SELECTORS.NOTIFICATIONS_BANNER);
    if (!el) return;

    el.innerHTML = '';
    el.className = `broadcast-banner severity-${notification.severity}`;
    el.dataset.notificationId = notification.id;

    const body = document.createElement('div');
    body.className = 'broadcast-banner-body';
    body.setAttribute('dir', 'auto');
    const title = document.createElement('strong');
    title.textContent = notification.title;
    const message = document.createElement('span');
    message.textContent = notification.body;
    body.append(title, message);

    const dismissBtn = document.createElement('button');
    dismissBtn.type = 'button';
    dismissBtn.className = 'broadcast-banner-dismiss';
    dismissBtn.setAttribute('aria-label', I18n.t('chat.notifications.bannerDismiss'));
    dismissBtn.innerHTML = iconMarkup('close', 14);
    dismissBtn.addEventListener('click', () => BroadcastNotice.hideBanner(onDismiss));

    el.append(body, dismissBtn);
    // A rAF between setting content and adding the open class, so the
    // height-collapse transition actually runs from 0 rather than starting
    // already at its resting height on the very first paint.
    requestAnimationFrame(() => el.classList.add(CONFIG.CLASSES.NOTIF_BANNER_OPEN));
  },

  hideBanner(onDismiss) {
    const el = DOMCache.get(CONFIG.SELECTORS.NOTIFICATIONS_BANNER);
    if (!el || !el.classList.contains(CONFIG.CLASSES.NOTIF_BANNER_OPEN)) return;
    const id = el.dataset.notificationId;
    el.classList.remove(CONFIG.CLASSES.NOTIF_BANNER_OPEN);
    onDismiss?.(id);
  },

  /**
   * The acknowledgement modal. Reuses this app's existing Bootstrap Modal
   * utility (the same one #authModal already uses) rather than a bespoke
   * dialog — DESIGN.md's One Drawer Rule is about offcanvas drawers, not
   * this, and a centered modal is what the auth flow already proves works
   * with this codebase's focus-trap/backdrop/Escape handling.
   *
   * Escape and backdrop-click DO close it — they are never disabled — but
   * only the explicit Acknowledge button calls `onAcknowledge`. Every other
   * close path calls `onSnooze` instead, which the caller uses to suppress
   * it client-side for the rest of this session (see `snooze` above).
   */
  showModal(notification, { onAcknowledge, onSnooze } = {}) {
    const el = DOMCache.get(CONFIG.SELECTORS.NOTIFICATIONS_MODAL);
    if (!el || !window.bootstrap?.Modal) return null;

    const titleEl = el.querySelector('.broadcast-modal-title');
    const bodyEl = el.querySelector('.broadcast-modal-body');
    const ackBtn = el.querySelector('.broadcast-modal-acknowledge');
    if (titleEl) titleEl.textContent = notification.title;
    if (bodyEl) bodyEl.textContent = notification.body;
    el.dataset.notificationId = notification.id;
    el.className = `modal fade broadcast-modal severity-${notification.severity}`;

    const modal = window.bootstrap.Modal.getOrCreateInstance(el, {
      backdrop: true,
      keyboard: true,
    });

    let acknowledged = false;
    // Bootstrap ignores hide() while its own fade-in transition is still
    // running (see handlers.js's hideModal, which documents this same
    // limitation for the auth modal) — a click landing in that window would
    // otherwise be silently swallowed, leaving an urgent notice open with no
    // sign the reader's own "Got it" was heard at all.
    const requestHide = () => {
      modal.hide();
      if (el.classList.contains('fade')) {
        setTimeout(() => {
          if (el.classList.contains('show')) modal.hide();
        }, 350);
      }
    };
    const onAckClick = () => {
      acknowledged = true;
      requestHide();
    };
    const onHidden = () => {
      ackBtn?.removeEventListener('click', onAckClick);
      el.removeEventListener('hidden.bs.modal', onHidden);
      if (acknowledged) onAcknowledge?.();
      else onSnooze?.();
    };

    ackBtn?.addEventListener('click', onAckClick);
    el.addEventListener('hidden.bs.modal', onHidden);
    modal.show();
    return modal;
  },
};
