// SFDA Copilot — Unified Single-Page Application Script
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';
import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.0/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.0.8/+esm';

const App = (() => {
    /* 1. CONFIGURATION & STATE -------------------- */
    const CONFIG = {
        TOAST_DURATION: 3000,
        DEBOUNCE_DELAY: 300,
        SUPABASE_URL: window.SUPABASE_URL,
        SUPABASE_ANON_KEY: window.SUPABASE_ANON_KEY,
        CSS_CLASSES: {
            HIDDEN: 'hidden',
            D_NONE: 'd-none',
            INVALID: 'is-invalid',
            DARK_THEME: 'dark',
            LIGHT_THEME: 'light',
        },
    };

    const DOMElements = {}; // Cache for frequently accessed DOM elements.
    const state = {
        supabase: null,
        abortController: null,
        debounceTimer: null,
        isRequestInProgress: false,
        originalSendButtonText: 'Send',
        authModal: null,
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
            contentDiv.textContent = text;
        }
        return contentDiv;
    };

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
            'to be a valid email': 'Please provide a valid email address.',
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
                // Views
                unauthenticatedView: '#unauthenticated-view',
                authenticatedView: '#authenticated-view',
                // Auth
                loginForm: '#login-form',
                signupForm: '#signup-form',
                logoutButton: '#logout-button',
                logoutButtonOffcanvas: '#logout-button-offcanvas',
                authButton: '#auth-button',
                authButtonOffcanvas: '#auth-button-offcanvas',
                authButtonMain: '#auth-button-main',
                userStatusSpan: '#user-status',
                userStatusOffcanvas: '#user-status-offcanvas',
                authErrorDiv: '#auth-error',
                // Chat
                messagesContainer: '#messages',
                queryInput: '#query-input',
                sendButton: '#send-button',
                queryCategorySelect: '#query-category',
                // Shared
                themeToggle: '#theme-toggle',
                toastElem: '#toast',
                // FAQ
                faqSidebarSection: '#faq-sidebar-section',
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
            timestampEl.textContent = new Date().toLocaleTimeString();
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
            let existingIndicator = document.getElementById(indicatorId);

            if (show && !existingIndicator) {
                const skeletonHtml = `
                    <div id="${indicatorId}" class="skeleton-message-container">
                        <div class="skeleton skeleton-avatar"></div>
                        <div class="skeleton-content">
                            <div class="skeleton skeleton-line medium"></div>
                            <div class="skeleton skeleton-line"></div>
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
        
            // Update all status displays
            [DOMElements.userStatusSpan, DOMElements.userStatusOffcanvas].forEach(el => {
                if (el) el.textContent = statusText;
            });
        
            // Toggle main view visibility
            DOMElements.unauthenticatedView?.classList.toggle(CONFIG.CSS_CLASSES.D_NONE, isLoggedIn);
            DOMElements.authenticatedView?.classList.toggle(CONFIG.CSS_CLASSES.D_NONE, !isLoggedIn);
        
            // Toggle visibility of all login/signup buttons
            [DOMElements.authButton, DOMElements.authButtonOffcanvas, DOMElements.authButtonMain].forEach(button => {
                button?.classList.toggle(CONFIG.CSS_CLASSES.D_NONE, isLoggedIn);
            });
        
            // Toggle visibility of all logout buttons
            [DOMElements.logoutButton, DOMElements.logoutButtonOffcanvas].forEach(button => {
                button?.classList.toggle(CONFIG.CSS_CLASSES.D_NONE, !isLoggedIn);
            });
        },

        displayAuthError(message) {
            if (!DOMElements.authErrorDiv) return;
            DOMElements.authErrorDiv.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-2"></i><strong>${message}</strong>`;
            DOMElements.authErrorDiv.classList.remove(CONFIG.CSS_CLASSES.D_NONE);
        },

        clearAuthError() {
            if (DOMElements.authErrorDiv) {
                DOMElements.authErrorDiv.classList.add(CONFIG.CSS_CLASSES.D_NONE);
                DOMElements.authErrorDiv.innerHTML = '';
            }
            [DOMElements.loginForm, DOMElements.signupForm].forEach(form => {
                form?.querySelectorAll(`.${CONFIG.CSS_CLASSES.INVALID}`).forEach(input => input.classList.remove(CONFIG.CSS_CLASSES.INVALID));
            });
        },

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

        renderFaqButtons(faqData) {
            const { faqSidebarSection } = DOMElements;
            if (!faqSidebarSection) return;

            faqSidebarSection.innerHTML = '';
            const fragment = document.createDocumentFragment();

            Object.entries(faqData).forEach(([category, data]) => {
                if (!data.questions?.length) return;

                const header = document.createElement('h4');
                header.className = 'ps-2 mt-3';
                header.innerHTML = `<i class="bi ${data.icon || 'bi-question-circle'}"></i>${data.title || category}`;
                
                const nav = document.createElement('nav');
                nav.className = 'nav nav-pills flex-column';
                
                data.questions.forEach(({ short, text }) => {
                    const button = document.createElement('button');
                    button.className = 'nav-link faq-button';
                    Object.assign(button.dataset, { category, question: text });
                    button.textContent = short;
                    nav.appendChild(button);
                });

                fragment.appendChild(header);
                fragment.appendChild(nav);
            });
            
            faqSidebarSection.appendChild(fragment);
            faqSidebarSection.querySelector('h4:first-of-type')?.classList.remove('mt-3');
        },
    };

    /* 4. API & AUTH SERVICES -------------------- */
    const Services = {
        async getFaqData() {
            try {
                const response = await fetch('/api/frequent-questions');
                if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
                return await response.json();
            } catch (error) {
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
                const errorJson = await response.json().catch(() => ({}));
                throw new Error(errorJson.error || `Network error (${response.status})`);
            }
            return response.json();
        },

        async getSessionToken() {
            const { data, error } = await state.supabase.auth.getSession();
            return error ? null : data.session?.access_token ?? null;
        },

        async login(email, password) {
            try {
                const { error } = await state.supabase.auth.signInWithPassword({ email, password });
                if (error) throw error;

                // On success, hide the modal and let onAuthStateChange handle the view transition.
                state.authModal?.hide();
                DOMElements.loginForm?.reset();
                UI.showToast('Login successful!');
            } catch (error) {
                UI.displayAuthError(formatAuthError(error));
            }
        },

        async signup(email, password) {
            const { error } = await state.supabase.auth.signUp({ email, password });
            if (error) {
                UI.displayAuthError(formatAuthError(error));
            } else {
                DOMElements.signupForm?.reset();
                UI.showToast('Signup initiated! Please check your email to confirm.');
            }
        },

        async logout() {
            const { error } = await state.supabase.auth.signOut();
            if (error) {
                UI.showToast(`Logout failed: ${error.message}`, true);
            }
            // onAuthStateChange will handle the UI update.
        },
    };

    /* 5. EVENT HANDLERS -------------------- */
    const Handlers = {
        handleAuthFormSubmit(event) {
            event.preventDefault();
            UI.clearAuthError();
            const form = event.target;
            const email = form.querySelector('input[type="email"]').value.trim();
            const password = form.querySelector('input[type="password"]').value;

            if (!email || !password) {
                return UI.displayAuthError('Please provide both email and password.');
            }

            if (form.id === 'login-form') Services.login(email, password);
            else if (form.id === 'signup-form') Services.signup(email, password);
        },

        handleFaqClick(event) {
            const button = event.target.closest('.faq-button');
            if (!button || state.isRequestInProgress) return;

            document.querySelectorAll('.faq-button.active').forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');

            DOMElements.queryInput.value = button.dataset.question;
            DOMElements.queryCategorySelect.value = button.dataset.category;
            
            this.processQuery();
        },

        async processQuery() {
            state.abortController?.abort();
            const query = DOMElements.queryInput.value.trim();
            if (!query) return;

            const token = await Services.getSessionToken();
            if (!token) {
                UI.showToast('Your session has expired. Please log in again.', true);
                Services.logout(); // Force logout to reset state
                return;
            }

            UI.setSendingState(true);
            UI.addMessage(query, 'user');
            DOMElements.queryInput.value = '';
            UI.toggleTypingIndicator(true);

            try {
                const category = DOMElements.queryCategorySelect.value;
                const data = await Services.sendChatRequest(query, category, token);
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

    /* 6. EVENT BINDING -------------------- */
    function bindEventListeners() {
        // Auth forms
        DOMElements.loginForm?.addEventListener('submit', Handlers.handleAuthFormSubmit);
        DOMElements.signupForm?.addEventListener('submit', Handlers.handleAuthFormSubmit);
        
        // Chat
        DOMElements.sendButton?.addEventListener('click', () => Handlers.processQuery());
        DOMElements.queryInput?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                Handlers.debouncedProcessQuery();
            }
        });

        // FAQ (Event Delegation)
        DOMElements.faqSidebarSection?.addEventListener('click', (e) => Handlers.handleFaqClick(e));

        // Shared controls
        [DOMElements.logoutButton, DOMElements.logoutButtonOffcanvas].forEach(btn => btn?.addEventListener('click', () => Services.logout()));
        [DOMElements.authButton, DOMElements.authButtonOffcanvas, DOMElements.authButtonMain].forEach(btn => btn?.addEventListener('click', () => {
            state.authModal?.show();
        }));
        DOMElements.themeToggle?.addEventListener('click', () => UI.toggleTheme());
    }

    /* 7. INITIALIZATION -------------------- */
    async function init() {
        UI.cacheDomElements();
        UI.initTheme();

        if (!CONFIG.SUPABASE_URL || !CONFIG.SUPABASE_ANON_KEY) {
            return UI.showToast("Authentication services are not configured.", true);
        }

        try {
            state.supabase = createClient(CONFIG.SUPABASE_URL, CONFIG.SUPABASE_ANON_KEY);

            // Initialize the Bootstrap modal instance once and cache it.
            const authModalEl = document.getElementById('authModal');
            if (authModalEl) {
                state.authModal = new bootstrap.Modal(authModalEl);
            }

            if (DOMElements.sendButton) {
                state.originalSendButtonText = DOMElements.sendButton.textContent.trim() || 'Send';
            }
        } catch (error) {
            console.error("Initialization error:", error);
            return UI.showToast("Failed to initialize core application services.", true);
        }

        bindEventListeners();

        // Central Authentication Handler
        state.supabase.auth.onAuthStateChange(async (_event, session) => {
            const user = session?.user;
            UI.updateAuthUI(user);

            if (user) {
                // User is logged in, initialize the authenticated experience
                const faqData = await Services.getFaqData();
                if (faqData) {
                    UI.renderFaqButtons(faqData);
                } else {
                    DOMElements.faqSidebarSection.innerHTML = '<div class="text-secondary small text-center py-3">No FAQs available.</div>';
                }
            }
            // If not logged in, the UI is already correctly set by updateAuthUI
        });
    }

    return { init };
})();

document.addEventListener('DOMContentLoaded', App.init);