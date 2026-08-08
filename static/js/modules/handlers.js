/**
 * SFDA Copilot — Event handlers
 * Wires up auth forms, chat input, FAQ/suggested questions and profile actions.
 */

import { CONFIG } from './config.js';
import { DOMCache, ErrorHandler, logError } from './dom.js';
import { AppState } from './state.js';
import { AuthView } from './auth-view.js';
import { UI } from './ui.js';
import { Services } from './services.js';
import { ThemeManager } from './theme.js';
import { RobotStateManager } from './robot.js';
import { I18n } from './i18n.js';
import { SourcePanel } from './source-panel.js';
import { resetCitationState } from './citations.js';

/* Sent with every chat request so the model answers in the reader's language. */
const I18N_LANG = I18n.lang;

/* Honest progress text, driven by real server stages rather than a timer. */
const STAGE_LABELS = {
  searching: () => I18n.t('stage.searching'),
  retrieved: (d) => I18n.plural(d.count, 'stage.retrievedOne', 'stage.retrieved'),
  drafting: () => I18n.t('stage.drafting'),
  finalizing: () => I18n.t('stage.finalizing'),
};

export const Handlers = {
  bindEvents() {
    DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.addEventListener('submit', (e) => this.handleAuthFormSubmit(e, 'login'));
    DOMCache.get(CONFIG.SELECTORS.SIGNUP_FORM)?.addEventListener('submit', (e) => this.handleAuthFormSubmit(e, 'signup'));

    document.getElementById('login-btn-submit')?.addEventListener('click', (e) => {
      e.preventDefault();
      DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    DOMCache.get(CONFIG.SELECTORS.SEND_BTN)?.addEventListener('click', () => this.processQuery());
    DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT)?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.processQuery();
      }
    });

    DOMCache.getAll(`${CONFIG.SELECTORS.LOGOUT_BTN}, ${CONFIG.SELECTORS.LOGOUT_BTN_OFFCANVAS}`).forEach(btn => {
      btn?.addEventListener('click', (e) => this.handleLogout(e));
    });

    DOMCache.getAll(`${CONFIG.SELECTORS.AUTH_BTN}, ${CONFIG.SELECTORS.AUTH_BTN_OFFCANVAS}, ${CONFIG.SELECTORS.AUTH_BTN_MAIN}`).forEach(btn => {
      btn?.addEventListener('click', () => AppState.get('authModal')?.show());
    });

    DOMCache.get(CONFIG.SELECTORS.PROFILE_FORM)?.addEventListener('submit', (e) => this.handleProfileFormSubmit(e));
    DOMCache.getAll(`${CONFIG.SELECTORS.PROFILE_BTN}, ${CONFIG.SELECTORS.PROFILE_BTN_OFFCANVAS}`).forEach(btn => {
      btn?.addEventListener('click', () => this.handleProfileButtonClick());
    });

    DOMCache.getAll(`${CONFIG.SELECTORS.FAQ_SIDEBAR}, ${CONFIG.SELECTORS.FAQ_OFFCANVAS}`).forEach(section => {
      section?.addEventListener('click', (e) => this.handleFaqClick(e));
    });

    DOMCache.get(CONFIG.SELECTORS.MESSAGES)?.addEventListener('click', (e) => this.handleSuggestedQuestionClick(e));
  },

  async handleAuthFormSubmit(event, source) {
    event.preventDefault();
    event.stopPropagation();
    ErrorHandler.clearErrors();

    const form = event.target;
    if (!form.checkValidity()) {
      form.classList.add('was-validated');
      return;
    }

    const email = form.querySelector(`#${source}-email`)?.value?.trim();
    const password = form.querySelector(`#${source}-password`)?.value;

    if (!email || !password) {
      ErrorHandler.showAuthError('Please fill in both email and password.');
      return;
    }

    try {
      if (source === 'login') {
        const data = await Services.login(email, password);
        this.hideModal('authModal', CONFIG.SELECTORS.AUTH_MODAL);
        form.reset();
        ErrorHandler.showToast(
          data?.user?.email ? `Logged in as ${data.user.email}` : 'Login successful!'
        );
      } else {
        await Services.signup(email, password);
        form.reset();
        ErrorHandler.showToast('Signup initiated! Please check your email to confirm.');
      }
    } catch (error) {
      logError(error, `handleAuthFormSubmit.${source}`);
      ErrorHandler.showAuthError(ErrorHandler.formatAuthError(error));
    }
  },

  async processChatRequestInternal(queryText, category = '') {
    /* A new question makes whatever the panel is showing stale — it would sit
       beside an answer it has nothing to do with, in the one column the reader
       is watching for the new one. Here rather than in beginStreamingMessage,
       so the blocking path and a failed token check close it too. Focus is
       left where the reader put it: they asked a question, they are not
       looking at the previous answer's trigger. */
    SourcePanel.close({ restoreFocus: false });

    UI.addMessage(queryText, 'user');
    UI.setSendingState(true);
    RobotStateManager.reactToUser();

    try {
      let token;
      try {
        token = await Services.getSessionToken();
      } catch (error) {
        logError(error, 'processChatRequestInternal.getSessionToken');
        ErrorHandler.showToast(
          I18n.t('chat.sessionUnverified'),
          true
        );
        RobotStateManager.resetToIdle();
        return;
      }

      if (!token && !window.location.search.includes('testing=true')) {
        AppState.get('authModal')?.show();
        ErrorHandler.showToast(I18n.t('chat.loginRequired'), true);
        RobotStateManager.resetToIdle();
        return;
      }

      if (CONFIG.STREAMING && 'body' in Response.prototype) {
        await this.streamChat(queryText, category, token);
      } else {
        await this.blockingChat(queryText, category, token);
      }
    } catch (error) {
      UI.toggleTypingIndicator(false);
      if (error?.name === 'AbortError') {
        RobotStateManager.resetToIdle();
        return;
      }

      logError(error, 'processChatRequestInternal');
      UI.addMessage(I18n.t('chat.genericError'), 'bot');
      ErrorHandler.showToast(I18n.t('chat.sendFailed'), true);
      RobotStateManager.showError();
    } finally {
      UI.setSendingState(false);
    }
  },

  /** SSE path. The stage line reports the retrieval count mid-stream, but the
   *  passages themselves arrive on the terminal `final` frame — there is no
   *  honest way to present them as an answer's sources before the answer
   *  exists, and doing so is what put eight cards under a refusal. */
  async streamChat(queryText, category, token) {
    const handle = UI.beginStreamingMessage();
    let sawToken = false;
    let failed = null;

    let result = null;
    try {
      result = await Services.streamChatRequest(queryText, category, token, I18N_LANG, {
        stage: (d) => {
          RobotStateManager.onStage?.(d.stage, d);
          UI.setStage(handle, STAGE_LABELS[d.stage]
            ? STAGE_LABELS[d.stage](d)
            : null);
        },
        final: (d) => { handle.final = d; },
        delta: (d) => {
          if (!sawToken) {
            sawToken = true;
            UI.setStage(handle, null);
            RobotStateManager.startTalking();
          }
          handle.stream.push(d.t);
          UI.followStream();
        },
        suggestions: (d) => { handle.suggested = d.suggested_questions || []; },
        error: (d) => { failed = d; },
        done: () => { /* terminal; the reader loop ends on its own */ },
      });
    } catch (error) {
      if (error?.name === 'AbortError') {
        /* Cancelled. If `final` already arrived the answer is whole and
           normalized — the reader stopped a stream that had, unknown to them,
           already finished — so render it properly and mark it stopped.
           Falling back to raw deltas here would discard a complete answer and
           un-resolve its citations for pressing Stop a moment too late. */
        if (handle.final) {
          UI.finishStreamingMessage(handle, handle.suggested || [], handle.final);
          UI.flagIncomplete(handle, 'cancelled');
        } else {
          // Keep whatever arrived rather than leaving an empty bubble.
          UI.markStreamIncomplete(handle, 'cancelled');
        }
        RobotStateManager.resetToIdle();
        return;
      }
      if (handle.final) {
        UI.finishStreamingMessage(handle, handle.suggested || [], handle.final);
        UI.flagIncomplete(handle, 'error');
      } else {
        UI.markStreamIncomplete(handle, 'error');
      }
      throw error;
    }

    if (failed) {
      /* A failure after streaming began cannot change the 200 status line, so
         it arrives in-band. Where it lands matters:

         BEFORE `final` — there is no canonical answer, so keep the partial
         text and flag it.

         AFTER `final` — the answer is complete and normalized; what failed is
         auxiliary (suggestion generation, history persistence). Discarding it
         to show a raw, unnormalized partial would throw away the good answer
         the reader already has, along with its citations, over a failure that
         did not touch it. Render it properly and toast the failure. */
      if (handle.final) {
        UI.finishStreamingMessage(handle, handle.suggested || [], handle.final);
      } else {
        UI.markStreamIncomplete(handle, 'error');
      }
      ErrorHandler.showToast(I18n.t('chat.sendFailed'), true);
      RobotStateManager.showError();
      return;
    }

    if (result && !result.complete) {
      /* The socket closed without both `final` and `done`.

         No `final` — what arrived is a truncated answer that never went
         through citation normalization, so showing it as finished would
         present a half-answer as authoritative.

         `final` but no `done` — the answer itself is whole and normalized;
         only the close-out is missing, which most likely means the turn was
         never persisted to history. Falling back to the raw deltas here would
         throw away the canonical text and un-resolve its citations to punish
         a failure that happened after the answer was complete. Render it
         properly, then say the exchange did not finish.

         The inline note is kept here but not in the `failed` branch above,
         deliberately: there the server told us what went wrong and a toast
         carries it, whereas a dead socket says nothing at all, so the reader
         gets a marking that outlives the toast. */
      if (handle.final) {
        UI.finishStreamingMessage(handle, handle.suggested || [], handle.final);
        UI.flagIncomplete(handle, 'error');
      } else {
        UI.markStreamIncomplete(handle, 'error');
      }
      ErrorHandler.showToast(I18n.t('chat.sendFailed'), true);
      RobotStateManager.showError();
      return;
    }

    UI.finishStreamingMessage(handle, handle.suggested || [], handle.final || null);
    RobotStateManager.returnToIdle(4000);
  },

  /** Fallback for browsers without streaming bodies, or CONFIG.STREAMING off. */
  async blockingChat(queryText, category, token) {
    const thinkingTimer = setTimeout(() => {
      RobotStateManager.startThinking();
      UI.toggleTypingIndicator(true);
    }, 800);

    try {
      const data = await Services.sendChatRequest(queryText, category, token, I18N_LANG);
      UI.toggleTypingIndicator(false);
      RobotStateManager.startTalking();

      if (!data?.response) throw new Error(I18n.t('chat.invalidResponse'));
      UI.addMessage(data.response, 'bot', data.suggested_questions || [], data.sources || [], {
        cited: data.cited ?? null,
        retrieved: data.retrieved ?? (data.sources || []).length,
      });
      RobotStateManager.returnToIdle(4000);
    } finally {
      clearTimeout(thinkingTimer);
    }
  },

  async handleFaqClick(event) {
    const button = event.target.closest(`.${CONFIG.CLASSES.FAQ_BUTTON}`);
    if (!button || AppState.isRequestInProgress()) return;

    DOMCache.getAll(`.${CONFIG.CLASSES.FAQ_BUTTON}.active`).forEach(btn => btn.classList.remove(CONFIG.CLASSES.ACTIVE));
    button.classList.add(CONFIG.CLASSES.ACTIVE);

    await this.processChatRequestInternal(button.dataset.question, button.dataset.category);
  },

  async processQuery() {
    const queryInput = DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT);
    const categorySelect = DOMCache.get(CONFIG.SELECTORS.CATEGORY_SELECT);
    if (!queryInput || !categorySelect) return;

    if (AppState.isRequestInProgress()) {
      Services.cancelChatRequest();
      ErrorHandler.showToast('Chat request cancelled.', false);
      UI.toggleTypingIndicator(false);
      UI.setSendingState(false);
      return;
    }

    const query = queryInput.value.trim();
    if (!query) return;

    queryInput.value = '';
    const hiddenSelect = document.getElementById('query-category-hidden');
    const selectedCategory = categorySelect.dataset?.value || hiddenSelect?.value || 'all';
    await this.processChatRequestInternal(query, selectedCategory);
  },

  async handleSuggestedQuestionClick(event) {
    const button = event.target.closest(`.${CONFIG.CLASSES.SUGGESTED_BUTTON}`);
    if (!button || AppState.isRequestInProgress()) return;

    const questionText = button.dataset.questionText;
    if (!questionText) return;

    DOMCache.getAll(`.${CONFIG.CLASSES.SUGGESTED_BUTTON}`).forEach(btn => { btn.disabled = true; });

    const categorySelect = DOMCache.get(CONFIG.SELECTORS.CATEGORY_SELECT);
    const hiddenSelect = document.getElementById('query-category-hidden');
    const selectedCategory = categorySelect?.dataset?.value || hiddenSelect?.value || '';
    await this.processChatRequestInternal(questionText, selectedCategory);
  },

  async handleProfileFormSubmit(event) {
    event.preventDefault();
    ErrorHandler.clearErrors();

    try {
      const sessionData = await Services.supabase?.auth.getSession();
      const user = sessionData?.data?.session?.user;

      if (!user) {
        return ErrorHandler.showProfileError('Your session seems to have expired. Please log out and log in again.');
      }

      const formData = new FormData(event.target);
      const updates = {
        full_name: formData.get('full_name'),
        organization: formData.get('organization'),
        specialization: formData.get('specialization'),
        preferences: { theme: formData.get('theme-preference') },
        updated_at: new Date(),
      };

      await Services.updateProfile(user.id, updates);
      AppState.set('userProfile', { ...AppState.get('userProfile'), ...updates });
      ThemeManager.apply(updates.preferences?.theme || CONFIG.CLASSES.LIGHT);
      ErrorHandler.showToast('Profile saved successfully!');
      this.hideModal('profileModal', CONFIG.SELECTORS.PROFILE_MODAL);
    } catch (error) {
      logError(error, 'handleProfileFormSubmit');
      ErrorHandler.showProfileError(`Failed to save: ${error.message}`);
    }
  },

  async handleProfileButtonClick() {
    ErrorHandler.clearErrors();

    const sessionData = await Services.supabase?.auth.getSession();
    const user = sessionData?.data?.session?.user;

    if (!user) {
      ErrorHandler.showToast('Please log in to manage your profile.', true);
      AppState.get('authModal')?.show();
      return;
    }

    const cachedProfile = AppState.get('userProfile');
    if (cachedProfile) {
      UI.populateProfileForm(cachedProfile);
    } else {
      try {
        const profile = await Services.getProfile(user.id);
        if (profile) {
          AppState.set('userProfile', profile);
          UI.populateProfileForm(profile);
        } else {
          const form = DOMCache.get(CONFIG.SELECTORS.PROFILE_FORM);
          if (form) {
            form.reset();
            const defaultThemeRadio = form.querySelector(`input[name="theme-preference"][value="${ThemeManager.getCurrent()}"]`);
            if (defaultThemeRadio) defaultThemeRadio.checked = true;
          }
        }
      } catch (error) {
        logError(error, 'handleProfileButtonClick');
        ErrorHandler.showToast('Could not load your profile.', true);
        const form = DOMCache.get(CONFIG.SELECTORS.PROFILE_FORM);
        form?.reset();
      }
    }

    AppState.get('profileModal')?.show();
  },

  async handleLogout(event) {
    event.preventDefault();
    try {
      const result = await Services.logout();
      this.clearLocalAuthData();
      AuthView.render(null);
      AppState.set('userProfile', null);
      this.clearSessionState();
      ErrorHandler.showToast(
        result?.testing ? 'Logged out successfully (testing mode)' : 'Logged out successfully'
      );
      this.redirectToHomeIfNeeded();
    } catch (error) {
      logError(error, 'handleLogout');
      this.clearLocalAuthData();
      AuthView.render(null);
      AppState.set('userProfile', null);
      this.clearSessionState();
      ErrorHandler.showToast('Logged out (session cleared)', false);
      this.redirectToHomeIfNeeded();
    }
  },

  /**
   * Drop everything in this tab that belonged to the signed-out reader.
   *
   * One function because there are two ways out — the logout button and a
   * session that expires or is revoked elsewhere (app.js routes
   * onAuthStateChange here) — and only one of them used to clean up. The tab
   * is not reloaded on the way out: the app lives at "/", so
   * redirectToHomeIfNeeded is a no-op, and AuthView only toggles `d-none` on
   * the authenticated view. Everything below therefore survives into the next
   * sign-in unless it is explicitly cleared, which on a regulatory product
   * means a second reader on a shared machine sees the first one's questions,
   * answers and evidence.
   *
   * Does NOT clear the server's conversation history or the Flask conv_id
   * cookie, so a second sign-in in this tab can still continue the previous
   * conversation server-side. That needs a change in the logout route
   * (session.clear() plus ConversationStore.clear) and is tracked separately.
   */
  clearSessionState() {
    // An in-flight answer would otherwise keep streaming into the hidden
    // transcript and repopulate the citation map after logout.
    Services.cancelChatRequest();
    /* Also reached when a session expires or is revoked rather than being
       signed out here, in which case Services.logout() never ran and the
       Flask cookie still holds conv_id. Not awaited — this function is the
       synchronous teardown, and the server rotates on an identity change
       regardless. On the logout-button path this is a duplicate of the call
       inside Services.logout(); the endpoint is idempotent. */
    Services.endServerSession();
    UI.clearTranscript();
    // reset, not close: closing leaves the previous reader's passages sitting
    // in the panel's DOM for the next one.
    SourcePanel.reset();
    resetCitationState();
    UI.Faq.clearButtons();
    try {
      sessionStorage.removeItem('sfda-transcript');
    } catch (error) {
      logError(error, 'clearSessionState: sessionStorage');
    }
  },

  clearLocalAuthData() {
    ['sb-access-token', 'sb-refresh-token', 'sb-user', 'sb-session', 'sfda-supabase-auth'].forEach(key => {
      try {
        localStorage.removeItem(key);
      } catch (error) {
        logError(error, `clearLocalAuthData: ${key}`);
      }
    });
  },

  redirectToHomeIfNeeded() {
    if (window.location.pathname !== '/') window.location.replace('/');
  },

  hideModal(stateKey, selector) {
    const modalElement = DOMCache.get(selector);
    const modal =
      AppState.get(stateKey) ||
      (modalElement && window.bootstrap?.Modal?.getOrCreateInstance(modalElement));
    modal?.hide();

    // Bootstrap ignores hide() while a fade-in transition is still running.
    // Fast mocked auth can resolve inside that window, so retry once after it.
    if (modalElement?.classList.contains('fade')) {
      setTimeout(() => {
        if (modalElement.classList.contains('show')) modal?.hide();
      }, 350);
    }
  },
};
