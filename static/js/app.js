/**
 * SFDA Copilot — Application entry point
 *
 * AI-powered regulatory guidance for pharmaceutical regulations.
 * This file wires the ES modules together; logic lives under ./modules/.
 *
 * @version 0.3.5 (Beta) — kept in step with APP_VERSION in web/api/app.py, which is
 * the single source the landing footer renders from.
 */

import { CONFIG } from './modules/config.js';
import { DOMCache, ErrorHandler, logError } from './modules/dom.js';
import { AppState } from './modules/state.js';
import { AuthView } from './modules/auth-view.js';
import { ThemeManager } from './modules/theme.js';
import { UI } from './modules/ui.js';
import { Effects } from './modules/effects.js';
import { Services, isRecoveryCallback } from './modules/services.js';
import { Handlers } from './modules/handlers.js';
import { CustomDropdown } from './modules/dropdown.js';
import { mountRobots, initLandingRobot, RobotCompanion } from './modules/robot.js';
import { initCitationInteractions, neutraliseRestoredCitations } from './modules/citations.js';
import { I18n, Transcript, initLanguageToggle } from './modules/i18n.js';

const App = {
  /* Set once settleTranscript has decided; see there. */
  _transcriptSettled: false,

  async loadProfileWithTimeout(userId, timeoutMs = CONFIG.API_TIMEOUT, retries = CONFIG.RETRY_MAX_ATTEMPTS) {
    let delay = CONFIG.RETRY_DELAY_INITIAL;

    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        const timeoutPromise = new Promise((_, reject) => {
          setTimeout(() => reject(new Error('Profile load timeout')), timeoutMs);
        });
        return await Promise.race([Services.getProfile(userId), timeoutPromise]);
      } catch (error) {
        logError(error, `loadProfileWithTimeout attempt ${attempt}/${retries}`);
        if (attempt < retries) {
          await new Promise(resolve => setTimeout(resolve, delay));
          delay *= 2;
        } else {
          throw error;
        }
      }
    }
    return null;
  },

  /**
   * `Services.getIdentity()`, retried on a genuine, transient fault only.
   *
   * `getIdentity()` already resolves — never throws — for "nobody" (401, no
   * session or an invalid one). "Not allowed" (403, a disabled account) now
   * throws instead, carrying `.status = 403`, but is equally not worth
   * retrying: it is a real answer, not a fault, and hammering a refusal would
   * only delay the disabled-notice ever settling. Only a network failure (no
   * `.status` — the fetch itself never got a response, which now includes the
   * client-side timeout `getIdentity` enforces) or a 5xx/503 from an
   * identity-provider outage — the exact shape `_authenticate_request`
   * classifies server-side — is worth a second attempt, because that is the
   * case the server is explicitly built to recover from: `resolve_identity_flags`
   * deliberately never caches a failed lookup, precisely so the next request
   * gets a clean try. Any other status (400, 403, 404, 429, ...) is retried
   * zero times — repeating the same request would only repeat the same answer.
   */
  async fetchIdentityWithRetry(attempts = 2, delayMs = 500) {
    for (let attempt = 1; attempt <= attempts; attempt++) {
      try {
        return await Services.getIdentity();
      } catch (error) {
        const retryable = error.status === undefined || error.status >= 500;
        if (!retryable || attempt >= attempts) throw error;
        await new Promise(resolve => setTimeout(resolve, delayMs));
      }
    }
    return null;
  },

  /**
   * Decide, once, what happens to the transcript saved by a language switch.
   *
   * Deliberately NOT done during init(). Restoring before authentication
   * resolves means restoring for nobody in particular: if startup then found
   * no valid session, the previous reader's transcript sat in the DOM behind
   * the landing view — hidden, not removed, because AuthView only toggles
   * `d-none` and the app lives at "/" so nothing reloads — and the next
   * person to sign in had it revealed to them.
   *
   * So the transcript waits for an answer to "who is here?", and is either
   * restored to the reader who saved it or dropped.
   */
  settleTranscript(user) {
    const identity = user?.id || user?.email || null;

    /* Ownership tracks the current reader ALWAYS, outside the once-guard. A
       tab that opens signed out settles immediately (nothing to restore), and
       the sign-in that follows still has to have its transcript tagged — or
       the next language switch saves one owned by nobody, which then fails
       its own ownership check on the way back. */
    if (identity) Transcript.setOwner(identity);

    if (this._transcriptSettled) return;
    this._transcriptSettled = true;

    if (!identity) {
      Transcript.discard();
      return;
    }

    /* Markup only — a restored answer's source passages did not survive the
       reload, so its controls are stripped rather than left resolving to
       nothing. */
    Transcript.restore(identity, neutraliseRestoredCitations);

    /* Every other route to a populated transcript runs through UI, which keeps
       New chat in step. This one writes the turns in as markup and never told
       it — so after a language switch the reader had a conversation on screen
       and no way to end it, which is the state the control exists for.
       `animate: false`: nothing arrived, the page loaded. */
    UI.updateNewChatAvailability({ animate: false });
  },

  async handleTestingModeInit() {
    console.log('[App] Testing mode enabled - bypassing authentication.');
    AuthView.render({ email: 'test@example.com' });
    this.settleTranscript({ email: 'test@example.com' });

    try {
      UI.Faq.renderButtons(await Services.getFaqData());
    } catch (error) {
      logError(error, 'handleTestingModeInit.getFaqData');
      UI.Faq.clearButtons();
      ErrorHandler.showToast(I18n.t('faq.loadFailedTesting'), true);
    }
  },

  async init() {
    window.APP_INITIALIZED = true;
    console.log('[App] Initializing SFDA Copilot...');

    Handlers.bindEvents();
    ThemeManager.init();
    UI.hydrateTimestamps();
    initCitationInteractions(DOMCache.get(CONFIG.SELECTORS.MESSAGES));
    UI.initJumpToLatest();
    initLanguageToggle();

    /* Mount the mascot and the card reveal. These run regardless of whether
       auth services are configured below. */
    mountRobots();
    Effects.initCardAnimations();
    initLandingRobot();
    RobotCompanion.init();
    CustomDropdown.init();

    if (!window.SUPABASE_URL || !window.SUPABASE_ANON_KEY) {
      logError('Supabase configuration missing.', 'App.init');
      return ErrorHandler.showToast(I18n.t('auth.servicesUnavailable'), true);
    }

    try {
      Services.init();

      const authModalEl = DOMCache.get(CONFIG.SELECTORS.AUTH_MODAL);
      if (authModalEl && window.bootstrap?.Modal) {
        AppState.set(
          'authModal',
          window.bootstrap.Modal.getOrCreateInstance(authModalEl)
        );
      }

      const profileModalEl = DOMCache.get(CONFIG.SELECTORS.PROFILE_MODAL);
      if (profileModalEl && window.bootstrap?.Modal) {
        AppState.set(
          'profileModal',
          window.bootstrap.Modal.getOrCreateInstance(profileModalEl)
        );
      }

      const sendBtn = DOMCache.get(CONFIG.SELECTORS.SEND_BTN);
      if (sendBtn) {
        AppState.set('originalSendButtonText', sendBtn.textContent?.trim() || I18n.t('chat.send'));
      }
    } catch (error) {
      logError(error, 'App.init services');
      return ErrorHandler.showToast(I18n.t('auth.initFailed'), true);
    }

    /* Recovery is decided before the testing bypass, and deliberately does not
       return: the demo path must be able to show this view, and the bypass at
       `handleTestingModeInit` would otherwise render a signed-in chat over it. */
    const recovering = isRecoveryCallback();
    if (recovering) {
      AppState.set('recoveryMode', true);
      AuthView.renderRecovery();
      /* Nobody in particular yet. Settling to null takes the discard branch, so
         the previous reader of this browser does not get their transcript
         restored to whoever followed a link from an inbox. */
      this.settleTranscript(null);
    } else if (window.location.search.includes('testing=true')) {
      return this.handleTestingModeInit();
    }

    if (!Services.supabase) {
      if (!recovering) AuthView.render(null);
      return;
    }

    /* Subscribed BEFORE the first await, not after it.
       This used to sit below `getSession()`. Anything Supabase emitted while
       that promise was in flight — including the PASSWORD_RECOVERY this flow
       depends on, which `_initialize` fires from a setTimeout during
       `Services.init()` — landed before there was a listener and was lost. The
       marker above is what makes recovery work regardless; this ordering is what
       makes the event a real second path rather than a decorative one. */
    Services.supabase.auth.onAuthStateChange(async (event, session) => {
      const user = session?.user ?? null;

      if (event === 'PASSWORD_RECOVERY') {
        AppState.set('recoveryMode', true);
        AuthView.renderRecovery();
        Handlers.setRecoveryReady(!!user);
        return;
      }

      /* While recovering, no auth event may draw a signed-in shell. Supabase
         emits SIGNED_IN first (supabase/auth-js#349) and a recovery session
         carries a user, so this is the event that would otherwise open the chat.
         SIGNED_OUT is the one that means the flow is over. */
      if (AppState.get('recoveryMode')) {
        if (event === 'SIGNED_OUT') {
          AppState.set('recoveryMode', false);
          AuthView.leaveRecovery(null);
          Handlers.clearSessionState();
        }
        return;
      }

      AuthView.render(user);
      /* No-op after startup has already settled it. Present so a session that
         resolves through this path rather than getSession() — a sign-in on a
         tab that opened signed out — still gets an ownership decision. */
      this.settleTranscript(user);

      if (user) {
        // Independent of everything else in this block — not awaited, so a
        // slow FAQ response no longer holds up the identity check below it.
        Services.getFaqData()
          .then(faqData => UI.Faq.renderButtons(faqData))
          .catch(error => {
            logError(error, 'onAuthStateChange.getFaqData');
            UI.Faq.clearButtons();
            ErrorHandler.showToast(I18n.t('faq.loadFailed'), true);
          });

        this.loadProfileWithTimeout(user.id)
          .then(profileData => {
            if (profileData) AppState.set('userProfile', profileData);
          })
          .catch(err => logError(err, 'loadProfileWithTimeout'));

        /* Ask the server whether this reader is an administrator, and reveal
           the console link from the answer rather than from anything the page
           already held. Fire-and-forget: the link is an affordance, and a
           reader who never learns about it has lost nothing, while a failed
           check must not delay or break the chat. Defaults to hidden.

           `checkId` is captured now, before either await below, and compared
           after: `auth-view.js` bumps `identityCheckId` on sign-out and on
           entering recovery, so a check dispatched for this reader that only
           resolves after they have left this view is recognised as stale and
           discarded rather than applied to whatever view replaced it.

           `Services.getIdentity()` dedupes concurrent calls into one shared
           promise (see its own comment), and that promise is not scoped to
           who asked. On a shared machine, if reader A signs out and reader B
           signs in on the same tab before A's still-pending check resolves,
           B's call joins A's promise and would otherwise receive A's answer.
           `identity.user_id` is checked against the user this dispatch was
           actually for so a borrowed answer for someone else's account is
           discarded rather than applied — this fails to "unresolved, stay
           hidden" for B rather than showing them A's standing, which matches
           how this app already treats every other unresolved case. */
        const checkId = AppState.get('identityCheckId') || 0;
        const dispatchedForUserId = user.id;
        this.fetchIdentityWithRetry()
          .then(identity => {
            if ((AppState.get('identityCheckId') || 0) !== checkId) return;
            if (identity && identity.user_id !== dispatchedForUserId) {
              logError(
                `getIdentity answered for ${identity.user_id}, expected ${dispatchedForUserId}`,
                'getIdentity.identityMismatch'
              );
              return;
            }
            AuthView.renderAdminAffordance(!!identity?.is_admin);
          })
          .catch(err => {
            if ((AppState.get('identityCheckId') || 0) !== checkId) return;
            AuthView.renderAdminAffordance(false);
            /* A disabled account is not a fault — see getIdentity's own
               comment. Surface the early notice instead of logging it as an
               error, so a disabled reader learns their standing before they
               type a question rather than only after (handlers.js already
               shows the same string on a 403 chat response; this is the
               earlier half of the same fix). Every other rejection here is
               a genuine fault and keeps the existing log-and-hide-link path. */
            if (err?.code === 'account_disabled') {
              UI.showAccountDisabledNotice();
              return;
            }
            logError(err, 'getIdentity');
          });
      } else {
        AppState.set('userProfile', null);
        /* Only on an actual sign-out — revoked, expired, or the logout button
           — never on the INITIAL_SESSION event this fires on subscribe. That
           event reports "no session yet" during startup, and clearing on it
           would wipe the transcript Transcript.restore() had just put back
           after a language switch.

           Without the cleanup here a session that ends anywhere other than the
           logout button leaves the previous reader's transcript, source panel
           and citation state live behind the landing view, because the tab is
           never reloaded on the way out. */
        if (event === 'SIGNED_OUT' || event === 'USER_DELETED') {
          Handlers.clearSessionState();
        } else {
          UI.Faq.clearButtons();
        }
      }
    });

    if (recovering) {
      /* The demo has no Supabase project behind it, so there is no session to
         find and the expired notice would be the only thing it could ever show.
         PRODUCT.md treats the demo as a shipping surface: `?testing=true&recovery=1`
         renders the real form, and `Services.updatePassword` short-circuits to
         success the same way `getSessionToken` and `logout` already do. */
      if (window.location.search.includes('testing=true')) {
        Handlers.setRecoveryReady(true);
        console.log('[App] Recovery view shown in testing mode.');
        return;
      }

      /* Whether the link actually produced a session. A marker with no session
         means expired, already used, or forged — and the form must say so rather
         than accept a password it can never save. */
      try {
        const { data: { session } } = await Services.supabase.auth.getSession();
        Handlers.setRecoveryReady(!!session?.user);
      } catch (error) {
        logError(error, 'App.init.recoverySessionCheck');
        Handlers.setRecoveryReady(false);
      }
      console.log('[App] SFDA Copilot initialized in recovery mode.');
      return;
    }

    try {
      const { data: { session: initialSession }, error: sessionError } = await Services.supabase.auth.getSession();

      if (sessionError) {
        logError(sessionError, 'App.init.initialSessionCheck');
        AuthView.render(null);
        this.settleTranscript(null);
      } else if (initialSession?.user) {
        AuthView.render(initialSession.user);
        this.settleTranscript(initialSession.user);
      } else {
        AuthView.render(null);
        this.settleTranscript(null);
      }
    } catch (error) {
      logError(error, 'App.init.checkInitialSession');
      AuthView.render(null);
      this.settleTranscript(null);
    }

    console.log('[App] SFDA Copilot initialized successfully.');
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
