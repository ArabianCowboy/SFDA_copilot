/**
 * SFDA Copilot — Application entry point
 *
 * AI-powered regulatory guidance for pharmaceutical regulations.
 * This file wires the ES modules together; logic lives under ./modules/.
 *
 * @version 5.0.0 (Dossier — ink + Plex, citations as the signature element)
 */

import { CONFIG } from './modules/config.js';
import { DOMCache, ErrorHandler, logError } from './modules/dom.js';
import { AppState } from './modules/state.js';
import { AuthView } from './modules/auth-view.js';
import { ThemeManager } from './modules/theme.js';
import { UI } from './modules/ui.js';
import { Effects } from './modules/effects.js';
import { Services } from './modules/services.js';
import { Handlers } from './modules/handlers.js';
import { CustomDropdown } from './modules/dropdown.js';
import { mountRobots, initLandingRobot, RobotCompanion } from './modules/robot.js';

const App = {
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

  async handleTestingModeInit() {
    console.log('[App] Testing mode enabled - bypassing authentication.');
    AuthView.render({ email: 'test@example.com' });

    try {
      UI.Faq.renderButtons(await Services.getFaqData());
    } catch (error) {
      logError(error, 'handleTestingModeInit.getFaqData');
      UI.Faq.clearButtons();
      ErrorHandler.showToast('Failed to load FAQs in testing mode.', true);
    }
  },

  async init() {
    window.APP_INITIALIZED = true;
    console.log('[App] Initializing SFDA Copilot...');

    Handlers.bindEvents();
    ThemeManager.init();
    UI.hydrateTimestamps();

    /* Mount the mascot and the card reveal. These run regardless of whether
       auth services are configured below. */
    mountRobots();
    Effects.initCardAnimations();
    initLandingRobot();
    RobotCompanion.init();
    CustomDropdown.init();

    if (!window.SUPABASE_URL || !window.SUPABASE_ANON_KEY) {
      logError('Supabase configuration missing.', 'App.init');
      return ErrorHandler.showToast('Authentication services are not configured.', true);
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
        AppState.set('originalSendButtonText', sendBtn.textContent?.trim() || 'Send');
      }
    } catch (error) {
      logError(error, 'App.init services');
      return ErrorHandler.showToast('Failed to initialize core application services.', true);
    }

    if (window.location.search.includes('testing=true')) {
      return this.handleTestingModeInit();
    }

    if (!Services.supabase) {
      AuthView.render(null);
      return;
    }

    try {
      const { data: { session: initialSession }, error: sessionError } = await Services.supabase.auth.getSession();

      if (sessionError) {
        logError(sessionError, 'App.init.initialSessionCheck');
        AuthView.render(null);
      } else if (initialSession?.user) {
        AuthView.render(initialSession.user);
      } else {
        AuthView.render(null);
      }
    } catch (error) {
      logError(error, 'App.init.checkInitialSession');
      AuthView.render(null);
    }

    Services.supabase.auth.onAuthStateChange(async (_event, session) => {
      const user = session?.user ?? null;
      AuthView.render(user);

      if (user) {
        try {
          UI.Faq.renderButtons(await Services.getFaqData());
        } catch (error) {
          logError(error, 'onAuthStateChange.getFaqData');
          UI.Faq.clearButtons();
          ErrorHandler.showToast('Failed to load FAQs.', true);
        }

        this.loadProfileWithTimeout(user.id)
          .then(profileData => {
            if (profileData) AppState.set('userProfile', profileData);
          })
          .catch(err => logError(err, 'loadProfileWithTimeout'));
      } else {
        AppState.set('userProfile', null);
        UI.Faq.clearButtons();
      }
    });

    console.log('[App] SFDA Copilot initialized successfully.');
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
