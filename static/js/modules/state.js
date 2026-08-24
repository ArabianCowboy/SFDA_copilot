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
    userProfile: null,
    // Bumped by auth-view.js whenever a view stops being "this signed-in
    // reader" (sign-out, entering recovery). app.js captures the value
    // before dispatching an /api/identity check and compares it on
    // resolution, so a check that outlives its view cannot apply itself to
    // the one that replaced it.
    identityCheckId: 0,
    // Which reader the conversation sidebar was loaded for, and whether its
    // default tab has been chosen yet. Both are cleared on sign-out and on an
    // identity change: the list carries the reader's own opening questions, and
    // the app lives at "/" so nothing reloads on the way out. Declared here
    // rather than left to `set` on first use so the reader-scoped keys are
    // visible in one place — `clearSessionState` has to clear every one of them.
    sidebarOwner: null,
    sidebarTabSettled: false,

    // ── Notification Center (docs/notification-center-plan.md) ──────────
    // The interval id for the active-notifications poll, so it can be torn
    // down on sign-out and on the tab going hidden, and re-established on
    // sign-in / the tab becoming visible again — the same reasoning
    // `sidebarOwner` documents above, applied to a recurring fetch instead
    // of a one-shot one.
    notificationsPollTimer: null,
    // The real Supabase auth user id the poll/Realtime pair are currently
    // running for — distinct from sidebarOwner, which falls back to an
    // email under the ?testing=true bypass where no real session (and so
    // no channel to authorize) exists at all.
    notificationsUserId: null,
    // The last-fetched active list, cached so the inbox and the bell badge
    // agree without a second round trip when the inbox opens.
    notificationsActive: [],
    // At most one modal-type notification shown at once (BroadcastCoordinator
    // in ui.js) — an id, not a boolean, so a second poll tick that still
    // finds the same notification active does not reopen what the reader is
    // already looking at.
    notificationsOpenModalId: null,
    // Cursor for the inbox's own keyset pagination.
    notificationsHistoryCursor: null,
    notificationsHistoryExhausted: false,
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
