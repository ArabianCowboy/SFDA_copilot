/**
 * SFDA Copilot — Unified Single-Page Application Script
 * 
 * This is a comprehensive single-page application for the SFDA (Saudi Food and Drug Authority)
 * Copilot system, providing AI-powered regulatory guidance for pharmaceutical regulations.
 * 
 * Features:
 * - Authentication via Supabase
 * - Real-time chat with AI assistant  
 * - FAQ system with categorized questions
 * - Suggested questions for enhanced user experience
 * - Profile management with theme preferences
 * - Responsive design with dark/light theme support
 * - Comprehensive error handling and logging
 * 
 * @author SFDA Copilot Team
 * @version 2.0.0
 * @since 2024
 */

// SFDA Copilot — Unified Single-Page Application Script (Synthesized)
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm'
import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.0/+esm'
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.0.8/+esm'

/* ——————————————— CONFIGURATION & STATE ——————————————— */
/**
 * Global configuration object containing timing constants, CSS classes, and DOM selectors.
 * This centralizes all configuration values for easy maintenance and consistency.
 */
const CONFIG = {
  // Timing constants
  TOAST_DURATION: 3000,
  DEBOUNCE_DELAY: 300,
  ANIMATION_DELAY: 100,
  API_TIMEOUT: 15000,
  RETRY_MAX_ATTEMPTS: 3,
  RETRY_DELAY_INITIAL: 1000,

  // CSS Classes
  CLASSES: {
    HIDDEN: 'hidden',
    D_NONE: 'd-none',
    INVALID: 'is-invalid',
    DARK: 'dark',
    LIGHT: 'light',
    ANIMATE_CARD: 'animate-card',
    ANIMATED: 'animated',
    ACTIVE: 'active',
    LOADING: 'loading',
    ERROR: 'error',
    SUCCESS: 'success',
    SKELETON: 'skeleton',
    TYPING: 'typing-indicator',
    // Suggested Questions Classes
    SUGGESTED_CONTAINER: 'suggested-questions-container',
    SUGGESTED_BUTTON: 'suggested-question-enhanced',
    SUGGESTED_ICON: 'suggested-question-icon',
  },

  // Selectors for DOM queries
  SELECTORS: {
    // Views
    UNAUTH_VIEW: '#unauthenticated-view',
    AUTH_VIEW: '#authenticated-view',
    // Auth
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
    // Chat
    MESSAGES: '#messages',
    QUERY_INPUT: '#query-input',
    SEND_BTN: '#send-button',
    CATEGORY_SELECT: '#query-category',
    // Modals
    AUTH_MODAL: '#authModal',
    PROFILE_MODAL: '#profileModal',
    PROFILE_FORM: '#profile-form',
    PROFILE_ERROR: '#profile-error',
    PROFILE_BTN: '#profile-button',
    PROFILE_BTN_OFFCANVAS: '#profile-button-offcanvas',
    // Shared
    TOAST: '#toast',
    // FAQ Sections
    FAQ_SIDEBAR: '#faq-sidebar-section',
    FAQ_OFFCANVAS: '#faq-offcanvas-section',
  },
};

// Efficient DOM caching system
const DOMCache = {
  elements: new Map(),

  get(selector) {
    if (!this.elements.has(selector)) {
      const element = document.querySelector(selector);
      this.elements.set(selector, element);
    }
    return this.elements.get(selector);
  },

  getAll(selector) {
    return document.querySelectorAll(selector);
  },

  createElement(tagName, ...classes) {
    const el = document.createElement(tagName);
    if (classes.length > 0) {
      el.classList.add(...classes);
    }
    return el;
  },

  setAttributes(element, attributes) {
    Object.entries(attributes).forEach(([key, value]) => {
      element.setAttribute(key, value);
    });
  },
};

// Centralized error handling system
const ErrorHandler = {
  formatAuthError(error) {
    const message = error?.message?.toLowerCase() || '';
    const errorMap = {
      'invalid login credentials': 'Incorrect email or password.',
      'email not confirmed': 'Please confirm your email before logging in.',
      'user already registered': 'This email is already registered. Please log in.',
      'to be a valid email': 'Please provide a valid email address.',
    };
    for (const key in errorMap) {
      if (message.includes(key)) return errorMap[key];
    }
    return error.message || 'An unknown authentication error occurred.';
  },

  showToast(message, isError = false, duration = CONFIG.TOAST_DURATION) {
    const toast = DOMCache.get(CONFIG.SELECTORS.TOAST);
    if (!toast) return;

    toast.textContent = message;
    toast.className = `toast-notification ${isError ? CONFIG.CLASSES.ERROR : CONFIG.CLASSES.SUCCESS}`;
    toast.classList.remove(CONFIG.CLASSES.HIDDEN);

    setTimeout(() => toast.classList.add(CONFIG.CLASSES.HIDDEN), duration);
  },

  showAuthError(message) {
    const errorEl = DOMCache.get(CONFIG.SELECTORS.AUTH_ERROR);
    if (!errorEl) return;

    errorEl.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-2"></i><strong>${message}</strong>`;
    errorEl.classList.remove(CONFIG.CLASSES.D_NONE);
  },

  showProfileError(message) {
    const errorEl = DOMCache.get(CONFIG.SELECTORS.PROFILE_ERROR);
    if (!errorEl) return;

    errorEl.textContent = message;
    errorEl.classList.remove(CONFIG.CLASSES.D_NONE);
  },

  clearErrors() {
    const authError = DOMCache.get(CONFIG.SELECTORS.AUTH_ERROR);
    const profileError = DOMCache.get(CONFIG.SELECTORS.PROFILE_ERROR);

    if (authError) {
      authError.classList.add(CONFIG.CLASSES.D_NONE);
      authError.innerHTML = '';
    }

    if (profileError) {
      profileError.classList.add(CONFIG.CLASSES.D_NONE);
      profileError.textContent = '';
    }

    // Clear form validation errors
    const forms = [CONFIG.SELECTORS.LOGIN_FORM, CONFIG.SELECTORS.SIGNUP_FORM].map(sel => DOMCache.get(sel)).filter(Boolean);
    forms.forEach(form => {
      form.querySelectorAll(`.${CONFIG.CLASSES.INVALID}`).forEach(input => input.classList.remove(CONFIG.CLASSES.INVALID));
    });
  },

  log(error, context = '') {
    console.error(`[SFDA Copilot ${context}]`, error);
  },
};

// Centralized state management
const AppState = {
  state: {
    supabase: null,
    abortController: null,
    debounceTimer: null,
    isRequestInProgress: false,
    originalSendButtonText: 'Send',
    authModal: null,
    profileModal: null,
    userProfile: null,
    viewTransitionEnabled: document.startViewTransition ? true : false,
  },

  reset() {
    this.state = {
      supabase: null,
      abortController: null,
      debounceTimer: null,
      isRequestInProgress: false,
      originalSendButtonText: 'Send',
      authModal: null,
      profileModal: null,
      userProfile: null,
      viewTransitionEnabled: document.startViewTransition ? true : false,
    };
  },

  get(key) {
    return this.state[key];
  },

  set(key, value) {
    this.state[key] = value;
  },

  update(updates) {
    Object.assign(this.state, updates);
  },

  resetAbortController() {
    if (this.state.abortController) {
      this.state.abortController.abort();
    }
    this.state.abortController = new AbortController();
    return this.state.abortController;
  },

  isRequestInProgress() {
    return this.state.isRequestInProgress;
  },

  setRequestInProgress(inProgress) {
    this.state.isRequestInProgress = inProgress;
    if (!inProgress) {
      this.state.abortController = null;
    }
  },
};

/* ——————————————— UTILITY MODULE ——————————————— */
const Utils = {
  createMessageContent(text, isBot) {
    const contentDiv = DOMCache.createElement('div', 'message-content');
    if (isBot) {
      const sanitizedHtml = DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } });
      contentDiv.innerHTML = sanitizedHtml;
    } else {
      contentDiv.textContent = text;
    }
    return contentDiv;
  },

  createMessageElement(text, sender) {
    const isBot = sender === 'bot';
    const messageWrapper = DOMCache.createElement('div', 'message', isBot ? 'chatbot-message' : 'user-message', 'mb-3', 'message-medium');
    const messageBubble = DOMCache.createElement('div', 'message-bubble');

    if (isBot) {
      const avatarDiv = DOMCache.createElement('div', 'avatar', 'mb-2');
      avatarDiv.innerHTML = `<img src="/static/images/bot.jpg" alt="Bot Avatar" class="rounded-circle" loading="lazy">`;
      messageBubble.appendChild(avatarDiv);
    }

    messageBubble.appendChild(this.createMessageContent(text, isBot));

    const timestampEl = DOMCache.createElement('div', 'timestamp');
    timestampEl.textContent = new Date().toLocaleTimeString();
    messageBubble.appendChild(timestampEl);

    messageWrapper.appendChild(messageBubble);

    // Add container for suggested questions for bot messages
    if (isBot) {
      const suggestionsContainer = DOMCache.createElement('div', 'suggested-questions-container', 'mt-2');
      messageWrapper.appendChild(suggestionsContainer);
    }

    return messageWrapper;
  },

  renderSuggestedQuestions(container, questions) {
    if (!container || !Array.isArray(questions) || questions.length === 0) return;

    // Add extra spacing from left sidebar
    container.style.marginLeft = '20px';
    container.style.paddingLeft = '10px';

    questions.forEach((question, index) => {
      const button = DOMCache.createElement('button', 'suggested-question-enhanced');
      const icon = DOMCache.createElement('i', 'fas', 'fa-lightbulb', 'suggested-question-icon');

      icon.setAttribute('aria-hidden', 'true');
      button.appendChild(icon);
      button.appendChild(document.createTextNode(question));

      DOMCache.setAttributes(button, {
        role: 'button',
        'aria-label': `Ask: ${question}`,
        tabindex: '0',
        'data-question-text': question, // Store pure text for click handler
      });

      // Add additional spacing per button
      button.style.marginBottom = '8px';
      button.style.marginRight = '8px';
      button.style.animationDelay = `${index * CONFIG.ANIMATION_DELAY / 1000}s`;
      container.appendChild(button);
    });
  },

  applyToElements(elements, updater) {
    elements?.filter(Boolean).forEach(updater);
  },

  logError(error, context = '') {
    ErrorHandler.log(error, context);
  },
};

/* ——————————————— UI MODULE ——————————————— */
const UI = {
  scrollMessagesToBottom() {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    }
  },

  addMessage(text, sender, suggestedQuestions = []) {
    const messageEl = Utils.createMessageElement(text, sender);
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);

    if (!container) return;

    const render = () => {
      container.appendChild(messageEl);

      if (sender === 'bot') {
        // Apply specific styling for Markdown-rendered elements
        messageEl.querySelectorAll('ul, ol').forEach(el => el.classList.add('message-list'));
        messageEl.querySelectorAll('pre code').forEach(el => el.parentElement?.classList.add('message-code-block'));
        messageEl.querySelectorAll(':not(pre) > code').forEach(el => el.classList.add('message-inline-code'));

        // Render suggested questions
        const suggestionsContainer = messageEl.querySelector('.suggested-questions-container');
        Utils.renderSuggestedQuestions(suggestionsContainer, suggestedQuestions);
      }
      this.scrollMessagesToBottom();
    };

    // Use View Transitions API if available
    AppState.get('viewTransitionEnabled') ? document.startViewTransition(render) : render();
  },

  toggleTypingIndicator(show) {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!container) return;

    const indicatorId = 'typing-indicator';
    let existingIndicator = document.getElementById(indicatorId);

    if (show && !existingIndicator) {
      const fragment = document.createDocumentFragment();
      const wrapper = DOMCache.createElement('div', 'skeleton-message-container');
      DOMCache.setAttributes(wrapper, { id: indicatorId });

      const avatar = DOMCache.createElement('div', 'skeleton', 'skeleton-avatar');
      const content = DOMCache.createElement('div', 'skeleton-content');
      const line1 = DOMCache.createElement('div', 'skeleton', 'skeleton-line', 'medium');
      const line2 = DOMCache.createElement('div', 'skeleton', 'skeleton-line');

      content.appendChild(line1);
      content.appendChild(line2);
      wrapper.appendChild(avatar);
      wrapper.appendChild(content);

      container.appendChild(wrapper);
      this.scrollMessagesToBottom();
    } else if (!show && existingIndicator) {
      existingIndicator.remove();
    }
  },

  updateAuthUI(user) {
    const isLoggedIn = !!user;
    const statusText = isLoggedIn ? `Logged in as: ${user.email}` : 'Not logged in';

    // Update user status displays
    DOMCache.getAll([CONFIG.SELECTORS.USER_STATUS, CONFIG.SELECTORS.USER_STATUS_OFFCANVAS].join(', ')).forEach(el => {
      el.textContent = statusText;
    });

    // Toggle visibility of authenticated/unauthenticated views
    DOMCache.get(CONFIG.SELECTORS.UNAUTH_VIEW)?.classList.toggle(CONFIG.CLASSES.D_NONE, isLoggedIn);
    DOMCache.get(CONFIG.SELECTORS.AUTH_VIEW)?.classList.toggle(CONFIG.CLASSES.D_NONE, !isLoggedIn);

    // Toggle visibility of auth, logout, and profile buttons
    DOMCache.getAll([
      CONFIG.SELECTORS.AUTH_BTN,
      CONFIG.SELECTORS.AUTH_BTN_OFFCANVAS,
      CONFIG.SELECTORS.AUTH_BTN_MAIN
    ].join(', ')).forEach(btn => btn?.classList.toggle(CONFIG.CLASSES.D_NONE, isLoggedIn));

    DOMCache.getAll([
      CONFIG.SELECTORS.LOGOUT_BTN,
      CONFIG.SELECTORS.LOGOUT_BTN_OFFCANVAS,
      CONFIG.SELECTORS.PROFILE_BTN,
      CONFIG.SELECTORS.PROFILE_BTN_OFFCANVAS
    ].join(', ')).forEach(btn => btn?.classList.toggle(CONFIG.CLASSES.D_NONE, !isLoggedIn));
  },

  populateProfileForm(profile) {
    const form = DOMCache.get(CONFIG.SELECTORS.PROFILE_FORM);
    if (!profile || !form) return;

    const { full_name = '', organization = '', specialization = '', preferences: { theme = CONFIG.CLASSES.LIGHT } = {} } = profile;
    const fullNameInput = form.querySelector('#profile-full-name');
    const orgInput = form.querySelector('#profile-organization');
    const specInput = form.querySelector('#profile-specialization');
    if (fullNameInput) fullNameInput.value = full_name;
    if (orgInput) orgInput.value = organization;
    if (specInput) specInput.value = specialization;

    // Sync with CURRENT active theme, not just stored profile preference
    const currentTheme = getCurrentTheme();
    const themeRadio = form.querySelector(`input[name="theme-preference"][value="${currentTheme}"]`);
    if (themeRadio) themeRadio.checked = true;
  },

  setSendingState(isSending) {
    AppState.setRequestInProgress(isSending);

    // Select all relevant elements
    const elementsToToggle = [
      DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT),
      DOMCache.get(CONFIG.SELECTORS.SEND_BTN),
      ...DOMCache.getAll('.faq-button'),
      ...DOMCache.getAll('.suggested-question-enhanced')
    ].filter(Boolean);

    elementsToToggle.forEach(el => (el.disabled = isSending));

    const sendBtn = DOMCache.get(CONFIG.SELECTORS.SEND_BTN);
    if (sendBtn) {
      const originalText = AppState.get('originalSendButtonText');
      sendBtn.innerHTML = isSending
        ? `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Sending...`
        : `<i class="bi bi-send"></i> ${originalText || 'Send'}`; // Defensive check for originalText
    }
  },

  Faq: {
    renderButtons(faqData) {
      const faqSections = [
        DOMCache.get(CONFIG.SELECTORS.FAQ_SIDEBAR),
        DOMCache.get(CONFIG.SELECTORS.FAQ_OFFCANVAS)
      ].filter(Boolean);

      if (faqSections.length === 0) return;

      const createFaqContent = () => {
        const fragment = document.createDocumentFragment();

        Object.entries(faqData || {}).forEach(([category, data]) => {
          if (!data?.questions?.length) return;

          const header = DOMCache.createElement('h4', 'ps-2', 'mt-3');
          header.innerHTML = `<i class="bi ${data.icon || 'bi-question-circle'}"></i>${data.title || category}`;

          const nav = DOMCache.createElement('nav', 'nav', 'nav-pills', 'flex-column');

          data.questions.forEach(({ short, text }) => {
            if (!short || !text) return;
            const button = DOMCache.createElement('button', 'nav-link', 'faq-button');
            DOMCache.setAttributes(button, { 'data-category': category, 'data-question': text });
            button.textContent = short;
            nav.appendChild(button);
          });

          fragment.appendChild(header);
          fragment.appendChild(nav);
        });

        return fragment;
      };

      faqSections.forEach((section, index) => {
        section.innerHTML = '';
        const content = createFaqContent();
        if (content.children.length > 0) {
          section.appendChild(index === 0 ? content : content.cloneNode(true));
          section.querySelector('h4:first-of-type')?.classList.remove('mt-3');
        } else {
          section.innerHTML = '<div class="text-secondary small text-center py-3">No FAQs available.</div>';
        }
      });
    },

    clearButtons() {
      DOMCache.getAll([
        CONFIG.SELECTORS.FAQ_SIDEBAR,
        CONFIG.SELECTORS.FAQ_OFFCANVAS
      ].join(', ')).forEach(section => (section.innerHTML = ''));
    },
  },
};

/* ——————————————— ANIMATION MODULE ——————————————— */
const Animations = {
  initCardAnimations() {
    const cards = document.querySelectorAll(`.${CONFIG.CLASSES.ANIMATE_CARD}`);
    if (typeof anime !== 'function') {
      console.warn('[Animations] anime.js not found. Card animations skipped.');
      return;
    }

    const animateCard = (targets, options) => {
      anime.remove(targets);
      anime({ targets, ...options });
    };

    const observer = new IntersectionObserver(
      (entries, observer) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && !entry.target.classList.contains(CONFIG.CLASSES.ANIMATED)) {
            const delay = parseInt(entry.target.dataset.delay || '0', 10);
            animateCard(entry.target, {
              translateY: [20, 0],
              opacity: [0, 1],
              duration: 800,
              easing: 'easeOutQuad',
              delay,
              complete: () => {
                entry.target.classList.add(CONFIG.CLASSES.ANIMATED);
                observer.unobserve(entry.target);
              },
            });
          }
        });
      },
      { threshold: 0.1 }
    );

    cards.forEach((card) => {
      observer.observe(card);
      card.addEventListener('mouseenter', () =>
        animateCard(card, { scale: 1.03, boxShadow: '0 8px 24px rgba(0,0,0,0.15)', duration: 200, easing: 'easeOutQuad' })
      );
      card.addEventListener('mouseleave', () =>
        animateCard(card, { scale: 1, boxShadow: '0 4px 12px rgba(0,0,0,0.08)', duration: 200, easing: 'easeOutQuad' })
      );
    });
  },

  initHeroParallax() {
    const heroImage = document.querySelector('.hero-visual img');
    if (!heroImage) return;

    const parallaxStrength = 0.05;
    window.addEventListener(
      'scroll',
      () => {
        heroImage.style.transform = `translateY(${window.pageYOffset * parallaxStrength}px)`;
      },
      { passive: true }
    );
  },
};

/* ——————————————— API & AUTH SERVICES ——————————————— */
const Services = {
  supabase: null,

  init() {
    // Initialize Supabase client outside of class context
    if (!window.supabaseClient) {
      try {
        window.supabaseClient = createClient(window.SUPABASE_URL, window.SUPABASE_ANON_KEY, {
          auth: {
            persistSession: true,
            autoRefreshToken: true,
            detectSessionInUrl: true,
            storage: window.localStorage,
            storageKey: 'sfda-supabase-auth'
          }
        });
      } catch (error) {
        Utils.logError(error, 'Failed to initialize Supabase client');
        return false;
      }
    }
    this.supabase = window.supabaseClient;
    return true;
  },

  async getFaqData() {
    try {
      const response = await fetch('/api/frequent-questions');
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! Status: ${response.status}. Details: ${errorText}`);
      }
      const data = await response.json();
      if (!data) {
        Utils.logError('No data received from FAQ endpoint', 'getFaqData');
        return null;
      }
      return data;
    } catch (error) {
      Utils.logError(error, 'getFaqData');
      ErrorHandler.showToast('Failed to load FAQs. Please try again later.', true);
      return null;
    }
  },

  async sendChatRequest(query, category, token) {
    const abortController = AppState.resetAbortController();

    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      signal: abortController.signal,
      body: JSON.stringify({ query, category }),
    });

    if (!response.ok) {
      const errorJson = await response.json().catch(() => ({}));
      throw new Error(errorJson.error || `Network error (${response.status})`);
    }
    return response.json();
  },

  async getSessionToken() {
    if (window.location.search.includes('testing=true')) {
      return 'fake_token'; // Bypass for testing
    }
    if (!this.supabase) {
      ErrorHandler.log('Supabase client not initialized.', 'getSessionToken');
      return null;
    }
    const { data, error } = await this.supabase.auth.getSession();
    if (error) {
      ErrorHandler.log(error, 'getSessionToken');
      return null;
    }
    return data.session?.access_token ?? null;
  },

  async login(email, password) {
    try {
      const { error } = await this.supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;

      const authModal = AppState.get('authModal');
      const loginForm = DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM);

      if (authModal) authModal.hide();
      if (loginForm) loginForm.reset();

      ErrorHandler.showToast('Login successful!');
    } catch (error) {
      const authError = ErrorHandler.formatAuthError(error);
      ErrorHandler.showAuthError(authError);
    }
  },

  async signup(email, password) {
    try {
      const { error } = await this.supabase.auth.signUp({ email, password });
      if (error) throw error;

      const signupForm = DOMCache.get(CONFIG.SELECTORS.SIGNUP_FORM);
      if (signupForm) signupForm.reset();

      ErrorHandler.showToast('Signup initiated! Please check your email to confirm.');
    } catch (error) {
      const authError = ErrorHandler.formatAuthError(error);
      ErrorHandler.showAuthError(authError);
    }
  },

  async logout() {
    if (window.location.search.includes('testing=true')) {
      UI.updateAuthUI(null);
      ErrorHandler.showToast('Logged out successfully (testing mode)');
      return;
    }
    if (!this.supabase) {
      ErrorHandler.showToast('Authentication service not available', true);
      return;
    }

    try {
      // Try to get current session first
      const { data: { session } } = await this.supabase.auth.getSession();
      
      if (!session) {
        // No active session - just clear local state
        console.log('[Auth] No active session to sign out from - clearing local data');
        this.clearLocalAuthData();
        UI.updateAuthUI(null);
        ErrorHandler.showToast('Logged out successfully');
        
        // Redirect to home page if not already there
        if (window.location.pathname !== '/') {
          window.location.replace('/');
        }
        return;
      }

      // Active session exists - sign out properly
      const { error } = await this.supabase.auth.signOut();
      if (error) throw error;

      ErrorHandler.showToast('Logged out successfully');
      
      // Clear local storage items related to Supabase session
      this.clearLocalAuthData();

      // Redirect to home page if not already there
      if (window.location.pathname !== '/') {
        window.location.replace('/');
      }
    } catch (error) {
      ErrorHandler.log(error, 'logout');
      // Even if signOut fails, clear local state
      this.clearLocalAuthData();
      UI.updateAuthUI(null);
      ErrorHandler.showToast('Logged out (session cleared)', false);
      
      // Redirect to home page if not already there
      if (window.location.pathname !== '/') {
        window.location.replace('/');
      }
    }
  },

  clearLocalAuthData() {
    // Clear Supabase session data from localStorage
    const keysToRemove = [
      'sb-access-token', 
      'sb-refresh-token', 
      'sb-user', 
      'sb-session',
      'sfda-supabase-auth'
    ];
    
    keysToRemove.forEach(key => {
      try {
        localStorage.removeItem(key);
      } catch (error) {
        Utils.logError(error, `localStorage removeItem for ${key} in clearLocalAuthData`);
      }
    });
    
    console.log('[Auth] Local authentication data cleared');
  },

  async getProfile(userId) {
    try {
      const { data, error } = await this.supabase
        .from('profiles')
        .select('id, full_name, organization, specialization, preferences')
        .eq('id', userId)
        .single();

      if (error && error.code !== 'PGRST116') {
        throw error;
      }
      return data;
    } catch (error) {
      ErrorHandler.log(error, 'getProfile');
      ErrorHandler.showToast('Could not load your profile.', true);
      return null;
    }
  },

  async updateProfile(userId, updates) {
    try {
      const profileData = { id: userId, ...updates };
      const { error } = await this.supabase.from('profiles').upsert(profileData, { onConflict: 'id' });

      if (error) throw error;
      return true;
    } catch (error) {
      ErrorHandler.log(error, 'updateProfile');
      ErrorHandler.showProfileError(`Failed to save: ${error.message}`);
      return false;
    }
  },
};

/* ——————————————— EVENT HANDLERS ——————————————— */
const Handlers = {
  /**
   * Private helper function to encapsulate common chat request logic.
   * It sets sending state, adds user message, calls API, and handles response/errors.
   * This greatly improves maintainability and reduces duplication.
   * @private
   * @param {string} queryText - The text of the user's query.
   * @param {string} [category=''] - The category for the query, if applicable.
   */
  async _processChatRequest(queryText, category = '') {
    // Set UI to sending state immediately
    UI.setSendingState(true);
    UI.addMessage(queryText, 'user');
    UI.toggleTypingIndicator(true);

    try {
      const token = await Services.getSessionToken();
      if (!token) {
        // If session expired, show toast and trigger logout, then return
        ErrorHandler.showToast('Your session has expired. Please log in again.', true);
        await Services.logout();
        return;
      }
      // Services.sendChatRequest internally handles `AppState.resetAbortController()`
      const data = await Services.sendChatRequest(queryText, category, token);
      UI.addMessage(
        data.response || data.error || 'An error occurred',
        'bot',
        data.suggested_questions // Pass suggested questions to UI
      );
    } catch (error) {
      // Only show error if it's not an AbortError (user-initiated cancellation)
      if (error.name !== 'AbortError') {
        UI.addMessage(`Sorry, there was an error processing your request: ${error.message}`, 'bot');
      } else {
        console.log('[Chat] Request aborted by user action.'); // Log cancellation for debugging
      }
    } finally {
      // Always reset UI state regardless of success or failure
      UI.toggleTypingIndicator(false);
      UI.setSendingState(false);
    }
  },

  handleAuthFormSubmit(event) {
    event.preventDefault();
    ErrorHandler.clearErrors();

    const form = event.target;
    const email = form.querySelector('input[type="email"]').value.trim();
    const password = form.querySelector('input[type="password"]').value;

    if (!email || !password) {
      return ErrorHandler.showAuthError('Please provide both email and password.');
    }

    const loginFormId = DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.id;
    const signupFormId = DOMCache.get(CONFIG.SELECTORS.SIGNUP_FORM)?.id;

    if (form.id === loginFormId) {
      Services.login(email, password);
    } else if (form.id === signupFormId) {
      Services.signup(email, password);
    }
  },

  async handleFaqClick(event) {
    const button = event.target.closest('.faq-button');
    if (!button || AppState.isRequestInProgress()) return;

    // Deactivate currently active FAQ button
    DOMCache.getAll('.faq-button.active').forEach(btn => btn.classList.remove(CONFIG.CLASSES.ACTIVE));
    button.classList.add(CONFIG.CLASSES.ACTIVE);

    const questionText = button.dataset.question;
    const category = button.dataset.category;

    // Use the unified chat request processor
    await this._processChatRequest(questionText, category);
  },

  async processQuery() {
    const queryInput = DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT);
    const categorySelect = DOMCache.get(CONFIG.SELECTORS.CATEGORY_SELECT);

    if (!queryInput || !categorySelect) return;
    if (AppState.isRequestInProgress()) {
      AppState.resetAbortController();
      return;
    }

    const query = queryInput.value.trim();
    if (!query) return;

    queryInput.value = ''; // Clear input field
    const category = categorySelect.value;

    // Use the unified chat request processor
    await this._processChatRequest(query, category);
  },

  debouncedProcessQuery() {
    clearTimeout(AppState.get('debounceTimer'));
    const timer = setTimeout(() => this.processQuery(), CONFIG.DEBOUNCE_DELAY);
    AppState.set('debounceTimer', timer);
  },

  async handleSuggestedQuestionClick(event) {
    const button = event.target.closest('.suggested-question-enhanced');
    if (!button || AppState.isRequestInProgress()) return;

    const questionText = button.dataset.questionText;
    if (!questionText) return;

    // Disable all suggested buttons after one is clicked to prevent multiple submissions
    DOMCache.getAll('.suggested-question-enhanced').forEach(btn => (btn.disabled = true));

    const categorySelect = DOMCache.get(CONFIG.SELECTORS.CATEGORY_SELECT);
    const category = categorySelect ? categorySelect.value : '';

    // Use the unified chat request processor
    await this._processChatRequest(questionText, category);
  },

  async handleProfileFormSubmit(event) {
    event.preventDefault();
    ErrorHandler.clearErrors();

    try {
      const { data: { session } = {} } = await Services.supabase.auth.getSession();
      const user = session?.user;

      if (!user) {
        return ErrorHandler.showProfileError('Your session seems to have expired. Please log out and log in again.');
      }

      const formData = new FormData(event.target);
      const updates = {
        full_name: formData.get('full_name'),
        organization: formData.get('organization'),
        specialization: formData.get('specialization'),
        preferences: {
          theme: formData.get('theme-preference'),
        },
        updated_at: new Date(),
      };

      const success = await Services.updateProfile(user.id, updates);

      if (success) {
        AppState.set('userProfile', { ...AppState.get('userProfile'), ...updates });

        // Apply the new theme preference immediately
        const newTheme = updates.preferences?.theme || 'light';
        applyTheme(newTheme);

        ErrorHandler.showToast('Profile saved successfully!');

        const profileModal = AppState.get('profileModal');
        if (profileModal) profileModal.hide();
      }
    } catch (error) {
      ErrorHandler.log(error, 'handleProfileFormSubmit');
      ErrorHandler.showProfileError('A critical error occurred. Please check the console.');
    }
  },

  async handleProfileButtonClick() {
    ErrorHandler.clearErrors();

    const { data: { session } = {} } = await Services.supabase.auth.getSession();
    const user = session?.user;
    if (!user) return;

    const cachedProfile = AppState.get('userProfile');
    if (cachedProfile) {
      UI.populateProfileForm(cachedProfile);
      return;
    }

    const profile = await Services.getProfile(user.id);
    if (profile) {
      AppState.set('userProfile', profile);
      UI.populateProfileForm(profile);
    } else {
      const form = DOMCache.get(CONFIG.SELECTORS.PROFILE_FORM);
      if (form) {
        form.reset();
        const defaultThemeRadio = form.querySelector('input[name="theme-preference"][value="light"]');
        if (defaultThemeRadio) defaultThemeRadio.checked = true;
      }
    }
  },

  async handleLogout(event) {
    event.preventDefault();
    await Services.logout();
  },

  bindEvents() {
    // Auth Forms
    const loginForm = DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM);
    const signupForm = DOMCache.get(CONFIG.SELECTORS.SIGNUP_FORM);

    if (loginForm) loginForm.addEventListener('submit', this.handleAuthFormSubmit);
    if (signupForm) signupForm.addEventListener('submit', this.handleAuthFormSubmit);

    // Chat Interactions
    const sendBtn = DOMCache.get(CONFIG.SELECTORS.SEND_BTN);
    const queryInput = DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT);

    if (sendBtn) sendBtn.addEventListener('click', () => this.processQuery());
    if (queryInput) {
      queryInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          this.debouncedProcessQuery();
        }
      });
    }

    // Profile Interactions
    const profileForm = DOMCache.get(CONFIG.SELECTORS.PROFILE_FORM);
    if (profileForm) profileForm.addEventListener('submit', this.handleProfileFormSubmit);

    DOMCache.getAll([CONFIG.SELECTORS.PROFILE_BTN, CONFIG.SELECTORS.PROFILE_BTN_OFFCANVAS].join(', ')).forEach(btn => {
      btn?.addEventListener('click', this.handleProfileButtonClick.bind(this));
    });

    // FAQ Interactions (delegated on FAQ sections)
    DOMCache.getAll([CONFIG.SELECTORS.FAQ_SIDEBAR, CONFIG.SELECTORS.FAQ_OFFCANVAS].join(', ')).forEach(section => {
      section?.addEventListener('click', this.handleFaqClick.bind(this));
    });

    // Suggested questions (delegated on messages container)
    const messagesContainer = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (messagesContainer) messagesContainer.addEventListener('click', this.handleSuggestedQuestionClick.bind(this));

    // Logout Buttons
    DOMCache.getAll([CONFIG.SELECTORS.LOGOUT_BTN, CONFIG.SELECTORS.LOGOUT_BTN_OFFCANVAS].join(', ')).forEach(btn => {
      btn?.addEventListener('click', this.handleLogout.bind(this));
    });

    // Auth Modal Trigger Buttons
    DOMCache.getAll([CONFIG.SELECTORS.AUTH_BTN, CONFIG.SELECTORS.AUTH_BTN_OFFCANVAS, CONFIG.SELECTORS.AUTH_BTN_MAIN].join(', ')).forEach(btn => {
      if (btn) {
        btn.addEventListener('click', () => {
          const modal = AppState.get('authModal');
          if (modal) modal.show();
        });
      }
    });

  },
};

/* ——————————————— INITIALIZATION ——————————————— */
async function loadProfileWithTimeout(userId, timeoutMs = CONFIG.API_TIMEOUT, retries = CONFIG.RETRY_MAX_ATTEMPTS) {
  let delay = CONFIG.RETRY_DELAY_INITIAL;
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const timeoutPromise = new Promise((_, reject) => {
        setTimeout(() => reject(new Error('Profile load timeout')), timeoutMs);
      });

      const result = await Promise.race([Services.getProfile(userId), timeoutPromise]);
      return result;
    } catch (error) {
      ErrorHandler.log(`Profile load attempt ${attempt}/${retries} failed:`, error);
      if (attempt < retries) {
        await new Promise(resolve => setTimeout(resolve, delay));
        delay *= 2;
      } else {
        throw error;
      }
    }
  }
  return null;
}

async function handleTestingModeInit() {
  console.log('[App] Testing mode enabled - bypassing authentication.');
  UI.updateAuthUI({ email: 'test@example.com' });
  const faqData = await Services.getFaqData();
  if (faqData) {
    UI.Faq.renderButtons(faqData);
  } else {
    UI.Faq.clearButtons();
    ErrorHandler.showToast('Failed to load FAQs in testing mode.', true);
  }
  Handlers.bindEvents();
}

async function init() {
  console.log('[App] Initializing SFDA Copilot application...');

  // 1. Initialize simple theme system
  initThemeSystem();

  // 2. Check for Supabase configuration
  if (!window.SUPABASE_URL || !window.SUPABASE_ANON_KEY) {
    ErrorHandler.log('Supabase configuration missing.', 'init');
    return ErrorHandler.showToast('Authentication services are not configured. Please check your environment variables.', true);
  }

  // 3. Initialize Supabase client and modals
  try {
    Services.init();

    // Initialize Bootstrap Modals
    const authModalEl = DOMCache.get(CONFIG.SELECTORS.AUTH_MODAL);
    if (authModalEl && window.bootstrap && bootstrap.Modal) {
      AppState.set('authModal', new bootstrap.Modal(authModalEl));
    }

    const profileModalEl = DOMCache.get(CONFIG.SELECTORS.PROFILE_MODAL);
    if (profileModalEl && window.bootstrap && bootstrap.Modal) {
      AppState.set('profileModal', new bootstrap.Modal(profileModalEl));
    }

    // Cache original send button text
    const sendBtn = DOMCache.get(CONFIG.SELECTORS.SEND_BTN);
    if (sendBtn) {
      AppState.set('originalSendButtonText', sendBtn.textContent?.trim() || 'Send');
    }
  } catch (error) {
    ErrorHandler.log(error, 'init_supabase');
    return ErrorHandler.showToast('Failed to initialize core application services.', true);
  }

  // 4. Initialize animations
  Animations.initCardAnimations();
  Animations.initHeroParallax();

  // 5. Handle testing mode early
  if (window.location.search.includes('testing=true')) {
    await handleTestingModeInit();
    return;
  }

  // 6. Bind all event listeners
  Handlers.bindEvents();

  // 7. Set up authentication state change listener
  Services.supabase.auth.onAuthStateChange(async (_event, session) => {
    const user = session?.user || null;
    UI.updateAuthUI(user);

    if (user) {
      console.log(`[Auth] User logged in: ${user.email}`);

      // Load FAQ data immediately upon login
      const faqData = await Services.getFaqData();
      if (faqData) {
        UI.Faq.renderButtons(faqData);
      } else {
        UI.Faq.clearButtons();
        ErrorHandler.showToast('Failed to load FAQs.', true);
      }

      // Load profile data asynchronously with timeout and retries
      loadProfileWithTimeout(user.id)
        .then((profileData) => {
          if (profileData) {
            AppState.set('userProfile', profileData);
            // Theme will be automatically handled by the new system
          } else {
            console.warn('[App] User profile not found or timed out after retries, using default theme.');
          }
        })
        .catch((err) => {
          ErrorHandler.log(err, 'loadProfileWithTimeout');
          console.warn('[App] Profile loading failed or timed out, continuing with defaults.');
        });
    } else {
      console.log('[Auth] User logged out.');
      AppState.set('userProfile', null);
      UI.Faq.clearButtons();
    }
  });

  console.log('[App] SFDA Copilot application initialized successfully.');
}

/* ——————————————— THEME SYSTEM ——————————————— */
function initThemeSystem() {
  // Get stored theme or use system preference
  let storedTheme;
  try {
    storedTheme = localStorage.getItem('theme');
  } catch (error) {
    Utils.logError(error, 'localStorage getItem in initThemeSystem');
    storedTheme = null;
  }
  const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const defaultTheme = storedTheme || (systemPrefersDark ? 'dark' : 'light');
  
  // Apply the theme using Bootstrap's native theme system
  applyTheme(defaultTheme);
  
  // Initialize button icons and bind events - buttons already exist in HTML
  initThemeToggles();

  console.log(`[Theme] Initialized with ${defaultTheme} theme`);
}


function updateThemeToggleIcons() {
  const currentTheme = getCurrentTheme();
  const iconClass = currentTheme === 'dark' ? 'bi-sun-fill' : 'bi-moon-fill';
  const newTitle = currentTheme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme';
  
  // Add existence check
  document.querySelectorAll('.theme-toggle-btn').forEach(btn => {
    if (btn) { // Ensure button exists
      btn.innerHTML = `<i class="bi ${iconClass}"></i>`;
      btn.setAttribute('title', newTitle);
      btn.setAttribute('aria-label', newTitle);
    }
  });
}

function initThemeToggles() {
  updateThemeToggleIcons();
  bindThemeToggleEvents();
}

function bindThemeToggleEvents() {
  // Use event delegation for better performance
  document.addEventListener('click', (e) => {
    if (e.target.closest('.theme-toggle-btn')) {
      e.preventDefault();
      toggleTheme();
    }
  });

  // Add keyboard navigation support
  document.addEventListener('keydown', (e) => {
    if (e.target.closest('.theme-toggle-btn') && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      toggleTheme();
    }
  });
}

function applyTheme(theme) {
  // Use Bootstrap's native theme system
  document.documentElement.setAttribute('data-bs-theme', theme);
  
  // Persist theme preference
  try {
    localStorage.setItem('theme', theme);
  } catch (error) {
    Utils.logError(error, 'localStorage setItem in applyTheme');
  }

  // Update toggle button icons
  updateThemeToggleIcons();

  console.log(`[Theme] Applied ${theme} theme to document`);
}

function toggleTheme() {
  const currentTheme = getCurrentTheme();
  const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

  console.log(`[Theme] Switching from ${currentTheme} to ${newTheme}`);
  applyTheme(newTheme);

  // Add visual feedback animation
  document.querySelectorAll('.theme-toggle-btn').forEach(btn => {
    btn.style.transform = 'scale(1.2)';
    setTimeout(() => {
      btn.style.transform = 'scale(1)';
    }, 150);
  });

  // Announce theme change to screen readers
  const announcement = document.createElement('div');
  announcement.setAttribute('role', 'status');
  announcement.setAttribute('aria-live', 'polite');
  announcement.className = 'sr-only';
  announcement.textContent = `Theme changed to ${newTheme} mode`;
  document.body.appendChild(announcement);
  
  // Remove announcement after it's been read
  setTimeout(() => {
    announcement.remove();
  }, 1000);
}

function getCurrentTheme() {
  return document.documentElement.getAttribute('data-bs-theme') || 'light';
}

// Application entry point
document.addEventListener('DOMContentLoaded', init);
