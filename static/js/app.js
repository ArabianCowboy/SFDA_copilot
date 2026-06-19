/**
 * SFDA Copilot — Application entry point
 *
 * AI-powered regulatory guidance for pharmaceutical regulations.
 * This file wires the ES modules together; logic lives under ./modules/.
 *
 * @version 4.0.0 (Clinical Blue refactor — modular + fresh mascot)
 */

import { CONFIG } from './modules/config.js';
import { DOMCache, AppState, ErrorHandler, logError } from './modules/dom.js';
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
    UI.updateAuthUI({ email: 'test@example.com' });

    const faqData = await Services.getFaqData();
    if (faqData) {
      UI.Faq.renderButtons(faqData);
    } else {
      UI.Faq.clearButtons();
      ErrorHandler.showToast('Failed to load FAQs in testing mode.', true);
    }
  },

  async init() {
    window.APP_INITIALIZED = true;
    console.log('[App] Initializing SFDA Copilot...');

    Handlers.bindEvents();
    ThemeManager.init();

    /* Mount the mascot, then start the purely-decorative cinematic layer.
       These run regardless of whether auth services are configured below. */
    mountRobots();
    Effects.initParticles();
    Effects.initCardAnimations();
    Effects.initHeroParallax();
    Effects.initButtonRipples();
    initLandingRobot();
    RobotCompanion.init();
    CustomDropdown.init();

    if (!window.SUPABASE_URL || !window.SUPABASE_ANON_KEY) {
      logError('Supabase configuration missing.', 'App.init');
      return ErrorHandler.showToast('Authentication services are not configured.', true);
    }

    try {
      if (!Services.init()) return;

      const authModalEl = DOMCache.get(CONFIG.SELECTORS.AUTH_MODAL);
      if (authModalEl && window.bootstrap?.Modal) {
        AppState.set('authModal', new bootstrap.Modal(authModalEl));
      }

      const profileModalEl = DOMCache.get(CONFIG.SELECTORS.PROFILE_MODAL);
      if (profileModalEl && window.bootstrap?.Modal) {
        AppState.set('profileModal', new bootstrap.Modal(profileModalEl));
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
      UI.updateAuthUI(null);
      return;
    }

    try {
      const { data: { session: initialSession }, error: sessionError } = await Services.supabase.auth.getSession();

      if (sessionError) {
        logError(sessionError, 'App.init.initialSessionCheck');
        UI.updateAuthUI(null);
      } else if (initialSession?.user) {
        UI.updateAuthUI(initialSession.user);
      } else {
        UI.updateAuthUI(null);
      }
    } catch (error) {
      logError(error, 'App.init.checkInitialSession');
      UI.updateAuthUI(null);
    }

    Services.supabase.auth.onAuthStateChange(async (_event, session) => {
      const user = session?.user ?? null;
      UI.updateAuthUI(user);

      if (user) {
        const faqData = await Services.getFaqData();
        faqData ? UI.Faq.renderButtons(faqData) : UI.Faq.clearButtons();

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
