/**
 * SFDA Copilot — Unified Single-Page Application Script
 *
 * AI-powered regulatory guidance for pharmaceutical regulations.
 *
 * @author SFDA Copilot Team
 * @version 2.2.0 (Merged Refactoring)
 * @since 2024
 */

import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.39.7/+esm';
import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.0/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.0.8/+esm';

/* ——————————————— CONFIGURATION ——————————————— */

const CONFIG = {
  TOAST_DURATION: 3000,
  DEBOUNCE_DELAY: 300,
  ANIMATION_DELAY: 100,
  API_TIMEOUT: 15000,
  RETRY_MAX_ATTEMPTS: 3,
  RETRY_DELAY_INITIAL: 1000,

  CLASSES: {
    HIDDEN: 'hidden',
    D_NONE: 'd-none',
    INVALID: 'is-invalid',
    DARK: 'dark',
    LIGHT: 'light',
    ANIMATE_CARD: 'animate-card',
    ANIMATED: 'animated',
    ACTIVE: 'active',
    ERROR: 'error',
    SUCCESS: 'success',
    SKELETON: 'skeleton',
    TYPING_INDICATOR_ID: 'typing-indicator',
    THEME_TOGGLE: 'theme-toggle-btn',
    SUGGESTED_CONTAINER: 'suggested-questions-container',
    SUGGESTED_BUTTON: 'suggested-question-enhanced',
    SUGGESTED_ICON: 'suggested-question-icon',
    FAQ_BUTTON: 'faq-button',
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
  },
};

/* ——————————————— DOM CACHE ——————————————— */

const DOMCache = {
  elements: new Map(),

  get(selector) {
    if (!this.elements.has(selector)) {
      this.elements.set(selector, document.querySelector(selector));
    }
    return this.elements.get(selector);
  },

  getAll(selector) {
    return document.querySelectorAll(selector);
  },

  createElement(tagName, ...classes) {
    const el = document.createElement(tagName);
    if (classes.length) el.classList.add(...classes);
    return el;
  },

  setAttributes(element, attributes = {}) {
    for (const [key, value] of Object.entries(attributes)) {
      element.setAttribute(key, value);
    }
  },
};

/* ——————————————— ERROR HANDLER ——————————————— */

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
    return error?.message || 'An unknown authentication error occurred.';
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

    [CONFIG.SELECTORS.LOGIN_FORM, CONFIG.SELECTORS.SIGNUP_FORM]
      .map(sel => DOMCache.get(sel))
      .filter(Boolean)
      .forEach(form => {
        form.querySelectorAll(`.${CONFIG.CLASSES.INVALID}`).forEach(input => {
          input.classList.remove(CONFIG.CLASSES.INVALID);
        });
        form.classList.remove('was-validated');
      });
  },

  log(error, context = '') {
    console.error(`[SFDA Copilot${context ? ` ${context}` : ''}]`, error);
  },
};

/* ——————————————— APP STATE ——————————————— */

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
    viewTransitionEnabled: !!document.startViewTransition,
  },

  get(key) {
    return this.state[key];
  },

  set(key, value) {
    this.state[key] = value;
  },

  resetAbortController() {
    this.state.abortController?.abort();
    this.state.abortController = new AbortController();
    return this.state.abortController;
  },

  isRequestInProgress() {
    return this.state.isRequestInProgress;
  },

  setRequestInProgress(inProgress) {
    this.state.isRequestInProgress = inProgress;
    if (!inProgress) this.state.abortController = null;
  },
};

/* ——————————————— UTILITIES ——————————————— */

const Utils = {
  logError(error, context = '') {
    ErrorHandler.log(error, context);
  },

  createMessageContent(text, isBot) {
    const contentDiv = DOMCache.createElement('div', 'message-content');
    if (isBot) {
      contentDiv.innerHTML = DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } });
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
      avatarDiv.innerHTML = '<img src="/static/images/bot.jpg" alt="Bot Avatar" class="rounded-circle" loading="lazy">';
      messageBubble.appendChild(avatarDiv);
    }

    messageBubble.appendChild(this.createMessageContent(text, isBot));

    const timestampEl = DOMCache.createElement('div', 'timestamp');
    timestampEl.textContent = new Date().toLocaleTimeString();
    messageBubble.appendChild(timestampEl);

    messageWrapper.appendChild(messageBubble);

    if (isBot) {
      const suggestionsContainer = DOMCache.createElement('div', CONFIG.CLASSES.SUGGESTED_CONTAINER, 'mt-2');
      messageWrapper.appendChild(suggestionsContainer);
    }

    return messageWrapper;
  },

  renderSuggestedQuestions(container, questions) {
    if (!container || !Array.isArray(questions) || !questions.length) return;

    Object.assign(container.style, { marginLeft: '20px', paddingLeft: '10px' });

    questions.forEach((question, index) => {
      const button = DOMCache.createElement('button', CONFIG.CLASSES.SUGGESTED_BUTTON);
      const icon = DOMCache.createElement('i', 'fas', 'fa-lightbulb', CONFIG.CLASSES.SUGGESTED_ICON);

      icon.setAttribute('aria-hidden', 'true');
      button.appendChild(icon);
      button.appendChild(document.createTextNode(question));

      DOMCache.setAttributes(button, {
        'aria-label': `Ask: ${question}`,
        'data-question-text': question,
      });

      Object.assign(button.style, {
        marginBottom: '8px',
        marginRight: '8px',
        animationDelay: `${(index * CONFIG.ANIMATION_DELAY) / 1000}s`,
      });

      container.appendChild(button);
    });
  },
};

/* ——————————————— THEME MANAGER ——————————————— */

const ThemeManager = {
  init() {
    let storedTheme;
    try {
      storedTheme = localStorage.getItem('theme');
    } catch (error) {
      Utils.logError(error, 'ThemeManager.init');
      storedTheme = null;
    }

    const systemPrefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
    const defaultTheme = storedTheme || (systemPrefersDark ? CONFIG.CLASSES.DARK : CONFIG.CLASSES.LIGHT);

    this.apply(defaultTheme);
    this.initToggles();
  },

  getCurrent() {
    return document.documentElement.getAttribute('data-bs-theme') || CONFIG.CLASSES.LIGHT;
  },

  apply(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);

    try {
      localStorage.setItem('theme', theme);
    } catch (error) {
      Utils.logError(error, 'ThemeManager.apply');
    }

    this.updateToggleIcons();
  },

  toggle() {
    const currentTheme = this.getCurrent();
    const newTheme = currentTheme === CONFIG.CLASSES.DARK ? CONFIG.CLASSES.LIGHT : CONFIG.CLASSES.DARK;

    this.apply(newTheme);
    this.animateToggleButtons();
    this.announceChange(newTheme);
  },

  updateToggleIcons() {
    const currentTheme = this.getCurrent();
    const isDark = currentTheme === CONFIG.CLASSES.DARK;
    const iconClass = isDark ? 'bi-sun-fill' : 'bi-moon-fill';
    const newTitle = isDark ? 'Switch to light theme' : 'Switch to dark theme';

    DOMCache.getAll(`.${CONFIG.CLASSES.THEME_TOGGLE}`).forEach(btn => {
      btn.innerHTML = `<i class="bi ${iconClass}"></i>`;
      DOMCache.setAttributes(btn, {
        title: newTitle,
        'aria-label': newTitle,
        'aria-pressed': String(isDark),
      });
    });
  },

  initToggles() {
    this.updateToggleIcons();
    this.bindToggleEvents();
  },

  bindToggleEvents() {
    document.addEventListener('click', (e) => {
      if (e.target.closest(`.${CONFIG.CLASSES.THEME_TOGGLE}`)) {
        e.preventDefault();
        this.toggle();
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.target.closest(`.${CONFIG.CLASSES.THEME_TOGGLE}`) && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault();
        this.toggle();
      }
    });
  },

  animateToggleButtons() {
    DOMCache.getAll(`.${CONFIG.CLASSES.THEME_TOGGLE}`).forEach(btn => {
      btn.style.transform = 'scale(1.2)';
      setTimeout(() => { btn.style.transform = 'scale(1)'; }, 150);
    });
  },

  announceChange(newTheme) {
    const announcement = DOMCache.createElement('div', 'sr-only');
    DOMCache.setAttributes(announcement, { role: 'status', 'aria-live': 'polite' });
    announcement.textContent = `Theme changed to ${newTheme} mode`;
    document.body.appendChild(announcement);
    setTimeout(() => announcement.remove(), 1000);
  },
};

/* ——————————————— UI MODULE ——————————————— */

const UI = {
  scrollMessagesToBottom() {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    container?.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
  },

  addMessage(text, sender, suggestedQuestions = []) {
    const messageEl = Utils.createMessageElement(text, sender);
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!container) return;

    const render = () => {
      container.appendChild(messageEl);

      if (sender === 'bot') {
        messageEl.querySelectorAll('ul, ol').forEach(el => el.classList.add(CONFIG.CLASSES.MESSAGE_LIST));
        messageEl.querySelectorAll('pre code').forEach(el => el.parentElement?.classList.add(CONFIG.CLASSES.MESSAGE_CODE_BLOCK));
        messageEl.querySelectorAll(':not(pre) > code').forEach(el => el.classList.add(CONFIG.CLASSES.MESSAGE_INLINE_CODE));

        const suggestionsContainer = messageEl.querySelector(`.${CONFIG.CLASSES.SUGGESTED_CONTAINER}`);
        Utils.renderSuggestedQuestions(suggestionsContainer, suggestedQuestions);
      }
      this.scrollMessagesToBottom();
    };

    AppState.get('viewTransitionEnabled') ? document.startViewTransition(render) : render();
  },

  toggleTypingIndicator(show) {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!container) return;

    const indicatorId = CONFIG.CLASSES.TYPING_INDICATOR_ID;
    const existingIndicator = document.getElementById(indicatorId);

    if (show && !existingIndicator) {
      const wrapper = DOMCache.createElement('div', 'skeleton-message-container');
      wrapper.id = indicatorId;

      const avatar = DOMCache.createElement('div', CONFIG.CLASSES.SKELETON, 'skeleton-avatar');
      const content = DOMCache.createElement('div', 'skeleton-content');
      content.appendChild(DOMCache.createElement('div', CONFIG.CLASSES.SKELETON, 'skeleton-line', 'medium'));
      content.appendChild(DOMCache.createElement('div', CONFIG.CLASSES.SKELETON, 'skeleton-line'));

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

    DOMCache.getAll(`${CONFIG.SELECTORS.USER_STATUS}, ${CONFIG.SELECTORS.USER_STATUS_OFFCANVAS}`).forEach(el => {
      if (el) el.textContent = statusText;
    });

    DOMCache.get(CONFIG.SELECTORS.UNAUTH_VIEW)?.classList.toggle(CONFIG.CLASSES.D_NONE, isLoggedIn);
    DOMCache.get(CONFIG.SELECTORS.AUTH_VIEW)?.classList.toggle(CONFIG.CLASSES.D_NONE, !isLoggedIn);

    const authButtonSelectors = [CONFIG.SELECTORS.AUTH_BTN, CONFIG.SELECTORS.AUTH_BTN_OFFCANVAS, CONFIG.SELECTORS.AUTH_BTN_MAIN];
    const userButtonSelectors = [CONFIG.SELECTORS.LOGOUT_BTN, CONFIG.SELECTORS.LOGOUT_BTN_OFFCANVAS, CONFIG.SELECTORS.PROFILE_BTN, CONFIG.SELECTORS.PROFILE_BTN_OFFCANVAS];

    const allButtonSelectors = [...authButtonSelectors, ...userButtonSelectors].join(', ');
    DOMCache.getAll(allButtonSelectors).forEach(btn => {
      if (!btn) return;
      const isAuthButton = authButtonSelectors.some(sel => btn.matches(sel));
      btn.classList.toggle(CONFIG.CLASSES.D_NONE, isAuthButton ? isLoggedIn : !isLoggedIn);
    });
  },

  populateProfileForm(profile) {
    const form = DOMCache.get(CONFIG.SELECTORS.PROFILE_FORM);
    if (!profile || !form) return;

    const { full_name = '', organization = '', specialization = '' } = profile;

    // Use .value assignment (not setAttribute) for proper form population
    const fullNameInput = form.querySelector('#profile-full-name');
    const orgInput = form.querySelector('#profile-organization');
    const specInput = form.querySelector('#profile-specialization');

    if (fullNameInput) fullNameInput.value = full_name;
    if (orgInput) orgInput.value = organization;
    if (specInput) specInput.value = specialization;

    // Sync theme radio with current active theme
    const currentTheme = ThemeManager.getCurrent();
    const themeRadio = form.querySelector(`input[name="theme-preference"][value="${currentTheme}"]`);
    if (themeRadio) themeRadio.checked = true;
  },

  setSendingState(isSending) {
    AppState.setRequestInProgress(isSending);

    const elementsToToggle = [
      DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT),
      DOMCache.get(CONFIG.SELECTORS.SEND_BTN),
      ...DOMCache.getAll(`.${CONFIG.CLASSES.FAQ_BUTTON}`),
      ...DOMCache.getAll(`.${CONFIG.CLASSES.SUGGESTED_BUTTON}`),
    ].filter(Boolean);

    elementsToToggle.forEach(el => { el.disabled = isSending; });

    const sendBtn = DOMCache.get(CONFIG.SELECTORS.SEND_BTN);
    if (sendBtn) {
      const originalText = AppState.get('originalSendButtonText') || 'Send';
      sendBtn.innerHTML = isSending
        ? '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Sending...'
        : `<i class="bi bi-send"></i> ${originalText}`;
    }
  },

  Faq: {
    renderButtons(faqData) {
      const faqSections = [DOMCache.get(CONFIG.SELECTORS.FAQ_SIDEBAR), DOMCache.get(CONFIG.SELECTORS.FAQ_OFFCANVAS)].filter(Boolean);
      if (!faqSections.length) return;

      const createFaqContent = () => {
        const fragment = document.createDocumentFragment();

        for (const [category, data] of Object.entries(faqData || {})) {
          if (!data?.questions?.length) continue;

          const header = DOMCache.createElement('h4', 'ps-2', 'mt-3');
          header.innerHTML = `<i class="bi ${data.icon || 'bi-question-circle'}"></i>${data.title || category}`;

          const nav = DOMCache.createElement('nav', 'nav', 'nav-pills', 'flex-column');

          for (const { short, text } of data.questions) {
            if (!short || !text) continue;
            const button = DOMCache.createElement('button', 'nav-link', CONFIG.CLASSES.FAQ_BUTTON);
            DOMCache.setAttributes(button, { 'data-category': category, 'data-question': text });
            button.textContent = short;
            nav.appendChild(button);
          }

          fragment.appendChild(header);
          fragment.appendChild(nav);
        }

        return fragment;
      };

      faqSections.forEach((section, index) => {
        section.innerHTML = '';
        const content = createFaqContent();
        if (content.childElementCount > 0) {
          section.appendChild(index === 0 ? content : content.cloneNode(true));
          section.querySelector('h4:first-of-type')?.classList.remove('mt-3');
        } else {
          section.innerHTML = '<div class="text-secondary small text-center py-3">No FAQs available.</div>';
        }
      });
    },

    clearButtons() {
      DOMCache.getAll(`${CONFIG.SELECTORS.FAQ_SIDEBAR}, ${CONFIG.SELECTORS.FAQ_OFFCANVAS}`).forEach(section => {
        section.innerHTML = '';
      });
    },
  },
};

/* ——————————————— ANIMATIONS ——————————————— */

const Animations = {
  initCardAnimations() {
    const cards = DOMCache.getAll(`.${CONFIG.CLASSES.ANIMATE_CARD}`);
    if (typeof anime !== 'function') {
      console.warn('[Animations] anime.js not found. Card animations skipped.');
      return;
    }

    const animateCard = (targets, options) => {
      anime.remove(targets);
      anime({ targets, ...options });
    };

    const observer = new IntersectionObserver(
      (entries, obs) => {
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
                obs.unobserve(entry.target);
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

    // Respect prefers-reduced-motion
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    const parallaxStrength = 0.05;
    let rafId = null;
    window.addEventListener('scroll', () => {
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        heroImage.style.transform = `translateY(${window.pageYOffset * parallaxStrength}px)`;
        rafId = null;
      });
    }, { passive: true });
  },
};

/* ——————————————— SERVICES ——————————————— */

const Services = {
  supabase: null,

  init() {
    if (this.supabase) return true;

    const { SUPABASE_URL, SUPABASE_ANON_KEY } = window;

    if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
      Utils.logError('Supabase configuration missing.', 'Services.init');
      ErrorHandler.showToast('Supabase configuration is missing.', true);
      return false;
    }

    if (!SUPABASE_URL.startsWith('http://') && !SUPABASE_URL.startsWith('https://')) {
      Utils.logError('Invalid Supabase URL format.', 'Services.init');
      ErrorHandler.showToast('Invalid Supabase URL format.', true);
      return false;
    }

    try {
      const isDebugMode =
        window.location.hostname === 'localhost' ||
        window.location.hostname === '127.0.0.1';

      this.supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true,
          storage: window.localStorage,
          storageKey: 'sfda-supabase-auth',
          flowType: 'pkce',
          debug: isDebugMode,
        },
      });

      if (isDebugMode) {
        window.supabaseClient = this.supabase;
      }

      AppState.set('supabase', this.supabase);
      return true;
    } catch (error) {
      Utils.logError(error, 'Services.init');
      ErrorHandler.showToast('Failed to initialize authentication service.', true);
      return false;
    }
  },

  async getFaqData() {
    try {
      const response = await fetch('/api/frequent-questions');
      if (!response.ok) {
        throw new Error(`HTTP error! Status: ${response.status}`);
      }
      return await response.json();
    } catch (error) {
      Utils.logError(error, 'getFaqData');
      ErrorHandler.showToast('Failed to load FAQs.', true);
      return null;
    }
  },

  async sendChatRequest(query, category, token) {
    const abortController = AppState.resetAbortController();

    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch('/api/chat', {
      method: 'POST',
      headers,
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
    if (window.location.search.includes('testing=true')) return 'fake_token';
    if (!this.supabase) {
      Utils.logError('Supabase client not initialized.', 'getSessionToken');
      return null;
    }

    const { data, error } = await this.supabase.auth.getSession();
    if (error) {
      Utils.logError(error, 'getSessionToken');
      return null;
    }
    return data.session?.access_token ?? null;
  },

  async login(email, password) {
    try {
      if (!this.supabase) throw new Error('Supabase client not initialized.');

      const { data, error } = await this.supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;

      AppState.get('authModal')?.hide();
      DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.reset();
      ErrorHandler.showToast(data?.user?.email ? `Logged in as ${data.user.email}` : 'Login successful!');
    } catch (error) {
      Utils.logError(error, 'Services.login');
      ErrorHandler.showAuthError(ErrorHandler.formatAuthError(error));
    }
  },

  async signup(email, password) {
    try {
      if (!this.supabase) throw new Error('Supabase client not initialized.');

      const { error } = await this.supabase.auth.signUp({ email, password });
      if (error) throw error;

      DOMCache.get(CONFIG.SELECTORS.SIGNUP_FORM)?.reset();
      ErrorHandler.showToast('Signup initiated! Please check your email to confirm.');
    } catch (error) {
      Utils.logError(error, 'Services.signup');
      ErrorHandler.showAuthError(ErrorHandler.formatAuthError(error));
    }
  },

  redirectToHomeIfNeeded() {
    if (window.location.pathname !== '/') window.location.replace('/');
  },

  clearLocalAuthData() {
    ['sb-access-token', 'sb-refresh-token', 'sb-user', 'sb-session', 'sfda-supabase-auth'].forEach(key => {
      try {
        localStorage.removeItem(key);
      } catch (error) {
        Utils.logError(error, `clearLocalAuthData: ${key}`);
      }
    });
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
      const { data: { session } } = await this.supabase.auth.getSession();

      if (!session) {
        this.clearLocalAuthData();
        UI.updateAuthUI(null);
        ErrorHandler.showToast('Logged out successfully');
        this.redirectToHomeIfNeeded();
        return;
      }

      const { error } = await this.supabase.auth.signOut();
      if (error) throw error;

      ErrorHandler.showToast('Logged out successfully');
      this.clearLocalAuthData();
      this.redirectToHomeIfNeeded();
    } catch (error) {
      Utils.logError(error, 'logout');
      this.clearLocalAuthData();
      UI.updateAuthUI(null);
      ErrorHandler.showToast('Logged out (session cleared)', false);
      this.redirectToHomeIfNeeded();
    }
  },

  async getProfile(userId) {
    try {
      if (!this.supabase) throw new Error('Supabase client not initialized.');

      const { data, error } = await this.supabase
        .from('profiles')
        .select('id, full_name, organization, specialization, preferences')
        .eq('id', userId)
        .single();

      if (error && error.code !== 'PGRST116') throw error;
      return data;
    } catch (error) {
      Utils.logError(error, 'getProfile');
      ErrorHandler.showToast('Could not load your profile.', true);
      return null;
    }
  },

  async updateProfile(userId, updates) {
    try {
      if (!this.supabase) throw new Error('Supabase client not initialized.');

      const { error } = await this.supabase.from('profiles').upsert({ id: userId, ...updates }, { onConflict: 'id' });
      if (error) throw error;
      return true;
    } catch (error) {
      Utils.logError(error, 'updateProfile');
      ErrorHandler.showProfileError(`Failed to save: ${error.message}`);
      return false;
    }
  },
};

/* ——————————————— EVENT HANDLERS ——————————————— */

const Handlers = {
  bindEvents() {
    // Auth forms
    DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.addEventListener('submit', (e) => this.handleAuthFormSubmit(e, 'login'));
    DOMCache.get(CONFIG.SELECTORS.SIGNUP_FORM)?.addEventListener('submit', (e) => this.handleAuthFormSubmit(e, 'signup'));

    // Login button click handler (HTML has type="button", not type="submit")
    document.getElementById('login-btn-submit')?.addEventListener('click', (e) => {
      e.preventDefault();
      const loginForm = DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM);
      if (loginForm) {
        // Create and dispatch a submit event to reuse existing logic
        loginForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      }
    });

    // Chat interactions
    DOMCache.get(CONFIG.SELECTORS.SEND_BTN)?.addEventListener('click', () => this.processQuery());
    DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT)?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.processQuery();
      }
    });

    // Logout buttons
    DOMCache.getAll(`${CONFIG.SELECTORS.LOGOUT_BTN}, ${CONFIG.SELECTORS.LOGOUT_BTN_OFFCANVAS}`).forEach(btn => {
      btn?.addEventListener('click', (e) => this.handleLogout(e));
    });

    // Auth modal triggers
    DOMCache.getAll(`${CONFIG.SELECTORS.AUTH_BTN}, ${CONFIG.SELECTORS.AUTH_BTN_OFFCANVAS}, ${CONFIG.SELECTORS.AUTH_BTN_MAIN}`).forEach(btn => {
      btn?.addEventListener('click', () => AppState.get('authModal')?.show());
    });

    // Profile form and buttons
    DOMCache.get(CONFIG.SELECTORS.PROFILE_FORM)?.addEventListener('submit', (e) => this.handleProfileFormSubmit(e));
    DOMCache.getAll(`${CONFIG.SELECTORS.PROFILE_BTN}, ${CONFIG.SELECTORS.PROFILE_BTN_OFFCANVAS}`).forEach(btn => {
      btn?.addEventListener('click', () => this.handleProfileButtonClick());
    });

    // FAQ interactions (delegated)
    DOMCache.getAll(`${CONFIG.SELECTORS.FAQ_SIDEBAR}, ${CONFIG.SELECTORS.FAQ_OFFCANVAS}`).forEach(section => {
      section?.addEventListener('click', (e) => this.handleFaqClick(e));
    });

    // Suggested questions (delegated)
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
    UI.toggleTypingIndicator(true);

    try {
      const token = await Services.getSessionToken();

      // Auth check (from junior's code - good addition)
      if (!token && !window.location.search.includes('testing=true')) {
        AppState.get('authModal')?.show();
        ErrorHandler.showToast('Please log in to chat with the AI.', true);
        throw new Error('Authentication required for chat.');
      }

      const data = await Services.sendChatRequest(queryText, category, token);

      UI.toggleTypingIndicator(false);

      if (data?.response) {
        UI.addMessage(data.response, 'bot', data.suggested_questions || []);
      } else {
        throw new Error('Invalid response format from AI service.');
      }
    } catch (error) {
      UI.toggleTypingIndicator(false);
      Utils.logError(error, 'processChatRequestInternal');
      UI.addMessage('Sorry, I encountered an error while processing your request. Please try again.', 'bot');
      ErrorHandler.showToast('Failed to send message.', true);
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

    // Cancel in-progress request (from junior's code - good UX)
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
    await this.processChatRequestInternal(query, categorySelect.value);
  },

  async handleSuggestedQuestionClick(event) {
    const button = event.target.closest(`.${CONFIG.CLASSES.SUGGESTED_BUTTON}`);
    if (!button || AppState.isRequestInProgress()) return;

    const questionText = button.dataset.questionText;
    if (!questionText) return;

    DOMCache.getAll(`.${CONFIG.CLASSES.SUGGESTED_BUTTON}`).forEach(btn => { btn.disabled = true; });

    const categorySelect = DOMCache.get(CONFIG.SELECTORS.CATEGORY_SELECT);
    await this.processChatRequestInternal(questionText, categorySelect?.value || '');
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
      Utils.logError(error, 'handleProfileFormSubmit');
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

/* ——————————————— APP MODULE ——————————————— */

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
        Utils.logError(error, `loadProfileWithTimeout attempt ${attempt}/${retries}`);
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
    window.APP_INITIALIZED = true; // ES module loaded — CDN imports succeeded
    console.log('[App] Initializing SFDA Copilot...');

    Handlers.bindEvents();
    ThemeManager.init();

    if (!window.SUPABASE_URL || !window.SUPABASE_ANON_KEY) {
      Utils.logError('Supabase configuration missing.', 'App.init');
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
      Utils.logError(error, 'App.init services');
      return ErrorHandler.showToast('Failed to initialize core application services.', true);
    }

    Animations.initCardAnimations();
    Animations.initHeroParallax();

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
        Utils.logError(sessionError, 'App.init.initialSessionCheck');
        UI.updateAuthUI(null);
      } else if (initialSession?.user) {
        UI.updateAuthUI(initialSession.user);
      } else {
        UI.updateAuthUI(null);
      }
    } catch (error) {
      Utils.logError(error, 'App.init.checkInitialSession');
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
          .catch(err => Utils.logError(err, 'loadProfileWithTimeout'));
      } else {
        AppState.set('userProfile', null);
        UI.Faq.clearButtons();
      }
    });

    console.log('[App] SFDA Copilot initialized successfully.');
  },
};

// Entry point
document.addEventListener('DOMContentLoaded', () => App.init());
