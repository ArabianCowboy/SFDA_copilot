/**
 * SFDA Copilot — Event handlers
 * Wires up auth forms, chat input, FAQ/suggested questions and profile actions.
 */

import { CONFIG } from './config.js';
import { DOMCache, AppState, ErrorHandler, logError } from './dom.js';
import { UI } from './ui.js';
import { Services } from './services.js';
import { ThemeManager } from './theme.js';
import { RobotStateManager } from './robot.js';

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

    if (source === 'login') {
      await Services.login(email, password);
    } else {
      await Services.signup(email, password);
    }
  },

  async processChatRequestInternal(queryText, category = '') {
    UI.addMessage(queryText, 'user');
    UI.setSendingState(true);

    RobotStateManager.reactToUser();
    setTimeout(() => {
      RobotStateManager.startThinking();
      UI.toggleTypingIndicator(true);
    }, 800);

    try {
      const token = await Services.getSessionToken();

      if (!token && !window.location.search.includes('testing=true')) {
        AppState.get('authModal')?.show();
        ErrorHandler.showToast('Please log in to chat with the AI.', true);
        throw new Error('Authentication required for chat.');
      }

      const data = await Services.sendChatRequest(queryText, category, token);

      UI.toggleTypingIndicator(false);
      RobotStateManager.startTalking();

      if (data?.response) {
        UI.addMessage(data.response, 'bot', data.suggested_questions || []);
      } else {
        throw new Error('Invalid response format from AI service.');
      }

      RobotStateManager.returnToIdle(4000);
    } catch (error) {
      UI.toggleTypingIndicator(false);
      logError(error, 'processChatRequestInternal');
      UI.addMessage('Sorry, I encountered an error while processing your request. Please try again.', 'bot');
      ErrorHandler.showToast('Failed to send message.', true);
      RobotStateManager.showError();
    } finally {
      UI.setSendingState(false);
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
      AppState.resetAbortController();
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

      const success = await Services.updateProfile(user.id, updates);

      if (success) {
        AppState.set('userProfile', { ...AppState.get('userProfile'), ...updates });
        ThemeManager.apply(updates.preferences?.theme || CONFIG.CLASSES.LIGHT);
        ErrorHandler.showToast('Profile saved successfully!');
        AppState.get('profileModal')?.hide();
      }
    } catch (error) {
      logError(error, 'handleProfileFormSubmit');
      ErrorHandler.showProfileError('A critical error occurred.');
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
    }

    AppState.get('profileModal')?.show();
  },

  async handleLogout(event) {
    event.preventDefault();
    await Services.logout();
  },
};
