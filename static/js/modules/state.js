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
    // Bumped by auth-view.js whenever a view stops being "this signed-in
    // reader" (sign-out, entering recovery). app.js captures the value
    // before dispatching an /api/identity check and compares it on
    // resolution, so a check that outlives its view cannot apply itself to
    // the one that replaced it.
    identityCheckId: 0,
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
