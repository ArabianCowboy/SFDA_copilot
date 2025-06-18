// SFDA Copilot — Main Application Script (Production Optimized)
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';
import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.0/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.0.8/+esm';

const App = (() => {
    /* 1. CONFIGURATION & STATE -------------------- */
    const CONFIG = {
        TOAST_DURATION: 3000,
        DEBOUNCE_DELAY: 300,
        DATE_FNS_POLL_INTERVAL: 100,
        DATE_FNS_MAX_ATTEMPTS: 50,
        SUPABASE_URL: window.SUPABASE_URL,
        SUPABASE_ANON_KEY: window.SUPABASE_ANON_KEY,
        CSS_CLASSES: {
            HIDDEN: 'hidden',
            INVALID: 'is-invalid',
            DARK_THEME: 'dark',
            LIGHT_THEME: 'light',
        },
    };

    const DOMElements = {}; // Cache for frequently accessed DOM elements.
    const state = {
        supabase: null,
        authModal: null,
        sidebarOffcanvas: null,
        abortController: null,
        debounceTimer: null,
        isRequestInProgress: false,
        originalSendButtonText: 'Send',
        formatRelativeDate: (date) => date.toLocaleString(), // Fallback date formatter.
    };

    /* 2. UTILITY & HELPER FUNCTIONS -------------------- */

    /**
     * Safely creates and sanitizes message content from text.
     * @param {string} text - The raw text content.
     * @param {boolean} isBot - True if the message is from the bot (enables Markdown).
     * @returns {HTMLElement} A div element with the sanitized content.
     */
    const createMessageContent = (text, isBot) => {
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        if (isBot) {
            const sanitizedHtml = DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } });
            contentDiv.innerHTML = sanitizedHtml;
        } else {
            contentDiv.textContent = text; // Safest method for user input, prevents XSS.
        }
        return contentDiv;
    };

    /**
     * Polls for the date-fns library on the window object and updates the state formatter.
     * @returns {Promise<void>}
     */
    const waitForDateFns = () => new Promise((resolve) => {
        let attempts = 0;
        const check = () => {
            if (window.dateFns?.formatRelative) {
                state.formatRelativeDate = (date) => window.dateFns.formatRelative(date, new Date());
                resolve();
            } else if (attempts++ < CONFIG.DATE_FNS_MAX_ATTEMPTS) {
                setTimeout(check, CONFIG.DATE_FNS_POLL_INTERVAL);
            } else {
                // This is a valuable operational warning for developers.
                console.warn('date-fns library not found after polling; using fallback.');
                resolve(); // Resolve anyway to not block initialization.
            }
        };
        check();
    });

    /**
     * Formats a Supabase auth error into a user-friendly message.
     * @param {Error} error - The error object from Supabase.
     * @returns {string} A user-friendly error message.
     */
    const formatAuthError = (error) => {
        const message = error?.message?.toLowerCase() || '';
        const errorMap = {
            'invalid login credentials': 'Incorrect email or password.',
            'email not confirmed': 'Please confirm your email before logging in.',
            'user already registered': 'This email is already registered. Please log in.',
        };
        for (const key in errorMap) {
            if (message.includes(key)) return errorMap[key];
        }
        return error.message || 'An unknown authentication error occurred.';
    };

    /* 3. UI MODULE -------------------- */
    const UI = {
        /** Caches DOM elements for performance. */
        cacheDomElements() {
            const selectors = {
                toastElem: '#toast', messagesContainer: '#messages', queryInput: '#query-input',
                sendButton: '#send-button', queryCategorySelect: '#query-category',
                authModalElement: '#authModal', loginForm: '#login-form', signupForm: '#signup-form',
                logoutButton: '#logout-button', logoutButtonOffcanvas: '#logout-button-offcanvas',
                authButton: '#auth-button', authButtonOffcanvas: '#auth-button-offcanvas',
                userStatusSpan: '#user-status', userStatusSpanOffcanvas: '#user-status-offcanvas',
                authErrorDiv: '#auth-error', sidebarOffcanvasElement: '#sidebarOffcanvas',
                sidebarContentRegular: '#sidebarContentRegular', themeToggle: '#theme-toggle',
                themeToggleOffcanvas: '#theme-toggle-offcanvas', faqSidebarSection: '#faq-sidebar-section',
                faqOffcanvasSection: '#faq-offcanvas-section',
            };
            for (const key in selectors) {
                DOMElements[key] = document.querySelector(selectors[key]);
            }
        },

        /**
         * Displays a toast notification.
         * @param {string} message - The message to display.
         * @param {boolean} [isError=false] - If true, styles the toast as an error.
         */
        showToast(message, isError = false) {
            if (!DOMElements.toastElem) return;
            DOMElements.toastElem.textContent = message;
            DOMElements.toastElem.className = `toast-notification ${isError ? 'error' : 'success'}`;
            DOMElements.toastElem.classList.remove(CONFIG.CSS_CLASSES.HIDDEN);
            setTimeout(() => DOMElements.toastElem.classList.add(CONFIG.CSS_CLASSES.HIDDEN), CONFIG.TOAST_DURATION);
        },

        /** Smoothly scrolls the messages container to the bottom. */
        scrollMessagesToBottom() {
            DOMElements.messagesContainer?.scrollTo({ top: DOMElements.messagesContainer.scrollHeight, behavior: 'smooth' });
        },

        /**
         * Creates a complete message element.
         * @param {string} text - The message content.
         * @param {'user'|'bot'} sender - The sender of the message.
         * @returns {HTMLElement} The fully constructed message element.
         */
        createMessageElement(text, sender) {
            const isBot = sender === 'bot';
            const messageWrapper = document.createElement('div');
            messageWrapper.className = `message ${isBot ? 'chatbot-message' : 'user-message'}`;

            const messageBubble = document.createElement('div');
            messageBubble.className = 'message-bubble';

            if (isBot) {
                const avatarDiv = document.createElement('div');
                avatarDiv.className = 'avatar mb-2';
                avatarDiv.innerHTML = `<img src="/static/images/bot.jpg" alt="Bot Avatar" class="rounded-circle" loading="lazy">`;
                messageBubble.appendChild(avatarDiv);
            }

            messageBubble.appendChild(createMessageContent(text, isBot));

            const timestampEl = document.createElement('div');
            timestampEl.className = 'timestamp';
            timestampEl.textContent = state.formatRelativeDate(new Date());
            messageBubble.appendChild(timestampEl);

            messageWrapper.appendChild(messageBubble);
            return messageWrapper;
        },

        /** Appends a new message to the chat and applies post-processing. */
        addMessage(text, sender) {
            const messageEl = this.createMessageElement(text, sender);

            const render = () => {
                DOMElements.messagesContainer.appendChild(messageEl);
                if (sender === 'bot') {
                    messageEl.querySelectorAll('ul, ol').forEach(el => el.classList.add('message-list'));
                    messageEl.querySelectorAll('pre code').forEach(el => el.parentElement.classList.add('message-code-block'));
                    messageEl.querySelectorAll(':not(pre) > code').forEach(el => el.classList.add('message-inline-code'));
                }
                this.scrollMessagesToBottom();
            };

            document.startViewTransition ? document.startViewTransition(render) : render();
        },

        /** Displays or hides the typing indicator skeleton loader. */
        toggleTypingIndicator(show) {
            const indicatorId = 'typing-indicator';
            const existingIndicator = document.getElementById(indicatorId);

            if (show && !existingIndicator) {
                const skeletonHtml = `
                    <div id="${indicatorId}" class="skeleton-message-container">
                        <div class="skeleton skeleton-avatar"></div>
                        <div class="skeleton-content">
                            <div class="skeleton skeleton-line medium"></div>
                            <div class="skeleton skeleton-line"></div>
                            <div class="skeleton skeleton-line short"></div>
                        </div>
                    </div>`;
                DOMElements.messagesContainer.insertAdjacentHTML('beforeend', skeletonHtml);
                this.scrollMessagesToBottom();
            } else if (!show && existingIndicator) {
                existingIndicator.remove();
            }
        },

        /** Updates the UI based on the user's authentication state. */
        updateAuthUI(user) {
            const isLoggedIn = !!user;
            const statusText = isLoggedIn ? `Logged in as: ${user.email}` : 'Not logged in';

            const updateGroup = ({ status, auth, logout }) => {
                if (status) status.textContent = statusText;
                auth?.classList.toggle('d-none', isLoggedIn);
                logout?.classList.toggle('d-none', !isLoggedIn);
            };

            updateGroup({ status: DOMElements.userStatusSpan, auth: DOMElements.authButton, logout: DOMElements.logoutButton });
            updateGroup({ status: DOMElements.userStatusSpanOffcanvas, auth: DOMElements.authButtonOffcanvas, logout: DOMElements.logoutButtonOffcanvas });
        },

        displayAuthError(message) {
            if (!DOMElements.authErrorDiv) return;
            DOMElements.authErrorDiv.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-2"></i><strong>${message}</strong>`;
            DOMElements.authErrorDiv.classList.remove('d-none');
        },

        clearAuthError() {
            if (DOMElements.authErrorDiv) {
                DOMElements.authErrorDiv.classList.add('d-none');
                DOMElements.authErrorDiv.innerHTML = '';
            }
            [DOMElements.loginForm, DOMElements.signupForm].forEach(form => {
                form?.querySelectorAll(`.${CONFIG.CSS_CLASSES.INVALID}`).forEach(input => input.classList.remove(CONFIG.CSS_CLASSES.INVALID));
            });
        },

        /**
         * Sets the UI state for sending a message (disabling inputs, showing spinner).
         * @param {boolean} isSending - True to enter sending state, false to exit.
         */
        setSendingState(isSending) {
            state.isRequestInProgress = isSending;
            const elementsToToggle = [DOMElements.queryInput, DOMElements.sendButton, ...document.querySelectorAll('.faq-button')];
            elementsToToggle.forEach(el => { if (el) el.disabled = isSending; });

            if (DOMElements.sendButton) {
                DOMElements.sendButton.innerHTML = isSending
                    ? `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Sending...`
                    : `<i class="bi bi-send"></i> ${state.originalSendButtonText}`;
            }

            if (!isSending) state.abortController = null;
        },

        initTheme() {
            const storedTheme = localStorage.getItem('theme');
            const prefersDark = window.matchMedia(`(prefers-color-scheme: ${CONFIG.CSS_CLASSES.DARK_THEME})`).matches;
            this.setTheme(storedTheme || (prefersDark ? CONFIG.CSS_CLASSES.DARK_THEME : CONFIG.CSS_CLASSES.LIGHT_THEME), false);
        },

        setTheme(theme, save = true) {
            document.documentElement.setAttribute('data-bs-theme', theme);
            if (save) localStorage.setItem('theme', theme);
        },

        toggleTheme() {
            const currentTheme = document.documentElement.getAttribute('data-bs-theme');
            this.setTheme(currentTheme === CONFIG.CSS_CLASSES.DARK_THEME ? CONFIG.CSS_CLASSES.LIGHT_THEME : CONFIG.CSS_CLASSES.DARK_THEME);
        },

        /** Creates a document fragment for a single FAQ category. */
        createFaqCategoryFragment(category, categoryData) {
            if (!categoryData.questions?.length) return null;

            const fragment = document.createDocumentFragment();
            const iconClass = categoryData.icon || 'bi-question-circle';
            const titleText = categoryData.title || `${category.charAt(0).toUpperCase() + category.slice(1)} FAQs`;

            const header = document.createElement('h4');
            header.className = 'ps-2 mt-3';
            header.innerHTML = `<i class="bi ${iconClass}"></i>${titleText}`;

            const nav = document.createElement('nav');
            nav.className = 'nav nav-pills flex-column';

            categoryData.questions.forEach(({ short, text }) => {
                const button = document.createElement('button');
                button.className = 'nav-link faq-button';
                Object.assign(button.dataset, { category, question: text });
                button.textContent = short;
                nav.appendChild(button);
            });

            fragment.appendChild(header);
            fragment.appendChild(nav);
            return fragment;
        },
        
        /** Renders all FAQ buttons into their containers. */
        renderFaqButtons(faqData) {
            const { faqSidebarSection, faqOffcanvasSection } = DOMElements;
            if (!faqSidebarSection || !faqOffcanvasSection) return;

            faqSidebarSection.innerHTML = '';
            faqOffcanvasSection.innerHTML = '';

            Object.entries(faqData).forEach(([category, data]) => {
                const fragment = this.createFaqCategoryFragment(category, data);
                if (fragment) {
                    faqSidebarSection.appendChild(fragment.cloneNode(true)); // Append a clone to the main sidebar
                    faqOffcanvasSection.appendChild(fragment); // Append the original to the offcanvas
                }
            });
            // Remove margin from the very first category header for cleaner look
            faqSidebarSection.querySelector('h4:first-of-type')?.classList.remove('mt-3');
            faqOffcanvasSection.querySelector('h4:first-of-type')?.classList.remove('mt-3');
        },
    };

    /* 4. API SERVICES MODULE -------------------- */
    const API = {
        async getFaqData() {
            const cacheKey = 'frequentQuestionsData';
            const cached = localStorage.getItem(cacheKey);
            if (cached) {
                try {
                    return JSON.parse(cached);
                } catch (e) {
                    // Important: Log error if cache is corrupted.
                    console.error("Failed to parse cached FAQ data:", e);
                    localStorage.removeItem(cacheKey);
                }
            }
            try {
                const response = await fetch('/api/frequent-questions');
                if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
                const data = await response.json();
                localStorage.setItem(cacheKey, JSON.stringify(data));
                return data;
            } catch (error) {
                // Important: Log error if API fails.
                console.error('Failed to fetch FAQs:', error);
                return null;
            }
        },

        async sendChatRequest(query, category, token) {
            state.abortController = new AbortController();
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                signal: state.abortController.signal,
                body: JSON.stringify({ query, category }),
            });

            if (!response.ok) {
                let errorMsg = `Network error (${response.status})`;
                try {
                    const errorJson = await response.json();
                    errorMsg = errorJson.error || errorMsg;
                } catch { /* Ignore if response body isn't valid JSON */ }
                throw new Error(errorMsg);
            }
            return response.json();
        },
    };

    /* 5. AUTHENTICATION SERVICE MODULE -------------------- */
    const AuthService = {
        async getSessionToken() {
            const { data, error } = await state.supabase.auth.getSession();
            return error ? null : data.session?.access_token ?? null;
        },

        async login(email, password) {
            try {
                const { error } = await state.supabase.auth.signInWithPassword({ email, password });
                if (error) throw error;
                state.authModal?.hide();
                DOMElements.loginForm?.reset();
                UI.showToast('Login successful!');
            } catch (error) {
                UI.displayAuthError(formatAuthError(error));
                DOMElements.loginForm?.querySelectorAll('input').forEach(i => i.classList.add(CONFIG.CSS_CLASSES.INVALID));
            }
        },

        async signup(email, password) {
            const { error } = await state.supabase.auth.signUp({ email, password });
            if (error) {
                UI.displayAuthError(formatAuthError(error));
            } else {
                state.authModal?.hide();
                DOMElements.signupForm?.reset();
                UI.showToast('Signup initiated! Please check your email to confirm.');
            }
        },

        async logout() {
            const { error } = await state.supabase.auth.signOut();
            if (error) {
                UI.showToast(`Logout failed: ${error.message}`, true);
            }
        },
    };

    /* 6. EVENT HANDLERS -------------------- */
    const Handlers = {
        handleAuthFormSubmit(event) {
            event.preventDefault();
            UI.clearAuthError();
            const form = event.target;
            const email = form.elements.email.value;
            const password = form.elements.password.value;

            if (form.id === 'login-form') AuthService.login(email, password);
            else if (form.id === 'signup-form') AuthService.signup(email, password);
        },

        handleFaqClick(event) {
            const button = event.target.closest('.faq-button');
            if (!button || state.isRequestInProgress) return;

            document.querySelectorAll('.faq-button.active').forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');

            DOMElements.queryInput.value = button.dataset.question;
            DOMElements.queryCategorySelect.value = button.dataset.category;

            if (button.closest('#sidebarOffcanvas')) {
                state.sidebarOffcanvas?.hide();
            }
            this.processQuery();
        },

        async processQuery() {
            state.abortController?.abort();
            const query = DOMElements.queryInput.value.trim();
            if (!query) return;

            const token = await AuthService.getSessionToken();
            if (!token) {
                UI.showToast('You must be logged in to chat.', true);
                state.authModal?.show();
                return;
            }

            UI.setSendingState(true);
            UI.addMessage(query, 'user');
            DOMElements.queryInput.value = '';
            UI.toggleTypingIndicator(true);

            try {
                const category = DOMElements.queryCategorySelect.value;
                const data = await API.sendChatRequest(query, category, token);
                UI.addMessage(data.response || `Error: ${data.error}`, 'bot');
            } catch (error) {
                if (error.name !== 'AbortError') {
                    UI.addMessage(`Sorry, there was an error: ${error.message}`, 'bot');
                }
            } finally {
                UI.toggleTypingIndicator(false);
                UI.setSendingState(false);
            }
        },

        debouncedProcessQuery() {
            clearTimeout(state.debounceTimer);
            state.debounceTimer = setTimeout(() => this.processQuery(), CONFIG.DEBOUNCE_DELAY);
        }
    };

    /* 7. EVENT BINDING -------------------- */
    function bindEventListeners() {
        DOMElements.sendButton?.addEventListener('click', () => Handlers.processQuery());
        DOMElements.queryInput?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                Handlers.debouncedProcessQuery();
            }
        });

        DOMElements.loginForm?.addEventListener('submit', Handlers.handleAuthFormSubmit);
        DOMElements.signupForm?.addEventListener('submit', Handlers.handleAuthFormSubmit);

        // Use event delegation for FAQ clicks for better performance
        DOMElements.sidebarContentRegular?.addEventListener('click', (e) => Handlers.handleFaqClick(e));
        DOMElements.sidebarOffcanvasElement?.addEventListener('click', (e) => Handlers.handleFaqClick(e));

        [DOMElements.authButton, DOMElements.authButtonOffcanvas].forEach(btn => btn?.addEventListener('click', () => state.authModal?.show()));
        [DOMElements.logoutButton, DOMElements.logoutButtonOffcanvas].forEach(btn => btn?.addEventListener('click', () => AuthService.logout()));
        [DOMElements.themeToggle, DOMElements.themeToggleOffcanvas].forEach(btn => btn?.addEventListener('click', () => UI.toggleTheme()));
    }

    /* 8. INITIALIZATION -------------------- */
    async function init() {
        UI.cacheDomElements();
        UI.initTheme();
        await waitForDateFns();

        if (!CONFIG.SUPABASE_URL || !CONFIG.SUPABASE_ANON_KEY) {
            return UI.showToast("Authentication services are not configured.", true);
        }

        try {
            state.supabase = createClient(CONFIG.SUPABASE_URL, CONFIG.SUPABASE_ANON_KEY);
            if (DOMElements.authModalElement) state.authModal = new bootstrap.Modal(DOMElements.authModalElement);
            if (DOMElements.sidebarOffcanvasElement) state.sidebarOffcanvas = new bootstrap.Offcanvas(DOMElements.sidebarOffcanvasElement);
            
            // **FIX APPLIED:** Store the raw text content for robustness.
            if (DOMElements.sendButton) {
                state.originalSendButtonText = DOMElements.sendButton.textContent.trim() || 'Send';
            }
        } catch (error) {
            // Important: Log error if Bootstrap or Supabase fail to initialize.
            console.error("Initialization error:", error);
            return UI.showToast("Failed to initialize core application UI.", true);
        }

        bindEventListeners();

        const faqData = await API.getFaqData();
        if (faqData && Object.keys(faqData).length > 0) {
            UI.renderFaqButtons(faqData);
        } else {
            document.querySelectorAll('[id^="faq-"]').forEach(container => {
                container.innerHTML = '<div class="text-secondary small text-center py-3">No frequently asked questions available.</div>';
            });
        }

        const { data: { session } } = await state.supabase.auth.getSession();
        UI.updateAuthUI(session?.user ?? null);
        state.supabase.auth.onAuthStateChange((_event, session) => {
            UI.updateAuthUI(session?.user ?? null);
        });
    }

    return { init };
})();

document.addEventListener('DOMContentLoaded', App.init);