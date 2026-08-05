/**
 * SFDA Copilot — Configuration
 * Centralised constants, CSS class names and DOM selectors.
 */

export const CONFIG = {
  TOAST_DURATION: 3000,
  DEBOUNCE_DELAY: 300,
  ANIMATION_DELAY: 100,
  API_TIMEOUT: 15000,
  RETRY_MAX_ATTEMPTS: 3,
  RETRY_DELAY_INITIAL: 1000,

  CLASSES: {
    HIDDEN: 'hidden',
    D_NONE: 'd-none',
    INVALID: 'is-invalid',
    DARK: 'dark',
    LIGHT: 'light',
    ANIMATE_CARD: 'animate-card',
    ANIMATED: 'animated',
    REVEALED: 'revealed',
    ACTIVE: 'active',
    ERROR: 'error',
    SUCCESS: 'success',
    TYPING_INDICATOR_ID: 'typing-indicator',
    THEME_TOGGLE: 'theme-toggle-btn',
    SUGGESTED_CONTAINER: 'suggested-questions-container',
    SUGGESTED_BUTTON: 'suggested-question-enhanced',
    SUGGESTED_ICON: 'suggested-question-icon',
    FAQ_BUTTON: 'faq-button',
    MESSAGE_LIST: 'message-list',
    MESSAGE_CODE_BLOCK: 'message-code-block',
    MESSAGE_INLINE_CODE: 'message-inline-code',
  },

  SELECTORS: {
    UNAUTH_VIEW: '#unauthenticated-view',
    AUTH_VIEW: '#authenticated-view',
    FAQ_SIDEBAR: '#faq-sidebar-section',
    FAQ_OFFCANVAS: '#faq-offcanvas-section',
    MESSAGES: '#messages',
    TOAST: '#toast',
    LOGIN_FORM: '#login-form',
    SIGNUP_FORM: '#signup-form',
    LOGOUT_BTN: '#logout-button',
    LOGOUT_BTN_OFFCANVAS: '#logout-button-offcanvas',
    AUTH_BTN: '#auth-button',
    AUTH_BTN_OFFCANVAS: '#auth-button-offcanvas',
    AUTH_BTN_MAIN: '#auth-button-main',
    USER_STATUS: '#user-status',
    USER_STATUS_OFFCANVAS: '#user-status-offcanvas',
    AUTH_ERROR: '#auth-error',
    AUTH_MODAL: '#authModal',
    QUERY_INPUT: '#query-input',
    SEND_BTN: '#send-button',
    CATEGORY_SELECT: '#query-category',
    PROFILE_MODAL: '#profileModal',
    PROFILE_FORM: '#profile-form',
    PROFILE_ERROR: '#profile-error',
    PROFILE_BTN: '#profile-button',
    PROFILE_BTN_OFFCANVAS: '#profile-button-offcanvas',
  },
};

/** Convenience: true when the user prefers reduced motion. */
export const prefersReducedMotion = () =>
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
