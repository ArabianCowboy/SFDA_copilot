/**
 * SFDA Copilot — Configuration
 * Centralised constants, CSS class names and DOM selectors.
 */

export const CONFIG = {
  /* Kill switch for SSE streaming. Set false to fall back to the blocking
     /api/chat path, which is kept working for exactly this reason. */
  STREAMING: true,

  TOAST_DURATION: 3000,
  /* Longer than a status toast, because this one carries a control the reader
     has to notice, read and reach. Hovering or tabbing into the toast holds it
     open, so the number is a floor rather than a deadline. */
  UNDO_DURATION: 10000,
  DEBOUNCE_DELAY: 300,
  ANIMATION_DELAY: 100,
  API_TIMEOUT: 15000,
  RETRY_MAX_ATTEMPTS: 3,
  RETRY_DELAY_INITIAL: 1000,
  /* Matches GoTrue's minimum interval between recovery mails to one address.
     Advisory only — the server is what enforces it; this just stops the reader
     hammering a button that cannot work yet, and says how long is left. */
  RESET_COOLDOWN_MS: 60000,

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
    NEW_CHAT_BTN: 'new-chat-btn',
    IS_CLEARING: 'is-clearing',
    IS_ACTIVATING: 'is-activating',
    IS_ARRIVING: 'is-arriving',
    ANIM_SUPPRESSED: 'anim-suppressed',
    IS_HELD: 'is-held',
    HAS_ACTION: 'has-action',
    TOAST_ACTION: 'toast-action',
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
    ADMIN_BTN: '#admin-button',
    ADMIN_BTN_OFFCANVAS: '#admin-button-offcanvas',
    RECOVERY_VIEW: '#recovery-view',
    RECOVERY_FORM: '#recovery-form',
    RECOVERY_PASSWORD: '#recovery-password',
    RECOVERY_CONFIRM: '#recovery-password-confirm',
    RECOVERY_ERROR: '#recovery-error',
    RECOVERY_HEADING: '#recovery-heading',
    RECOVERY_EXPIRED: '#recovery-expired',
    RECOVERY_CANCEL: '#recovery-cancel',
    RESET_REQUEST_FORM: '#reset-request-form',
    RESET_EMAIL: '#reset-email',
    RESET_SENT: '#reset-sent',
    FORGOT_LINK: '#forgot-password-link',
    RESET_BACK: '#reset-back-to-login',
    LOGIN_PANE_FORM: '#login-form',
  },
};

/** Convenience: true when the user prefers reduced motion. */
export const prefersReducedMotion = () =>
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
