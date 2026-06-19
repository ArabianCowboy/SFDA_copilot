/**
 * SFDA Copilot — Application state
 *
 * Runtime state lives here so data services and view helpers do not depend on
 * DOM utilities merely to coordinate requests and UI components.
 */

export const AppState = {
  state: {
    debounceTimer: null,
    isRequestInProgress: false,
    originalSendButtonText: 'Send',
    authModal: null,
    profileModal: null,
    userProfile: null,
    viewTransitionEnabled: !!document.startViewTransition,
    particleBackground: null,
  },

  get(key) {
    return this.state[key];
  },

  set(key, value) {
    this.state[key] = value;
  },

  isRequestInProgress() {
    return this.state.isRequestInProgress;
  },

  setRequestInProgress(inProgress) {
    this.state.isRequestInProgress = inProgress;
  },
};
