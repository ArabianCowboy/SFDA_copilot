// SFDA Copilot — Main Application Script (Consolidated Version)
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';
import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.0/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.0.8/+esm';

/**
 * Main application module, wrapped in an IIFE to create a private scope.
 */
const App = (() => {

    /* 1. CONFIGURATION & STATE -------------------- */

    const config = {
        TOAST_DURATION: 3000,
        DEBOUNCE_DELAY: 300,
        SUPABASE_URL: window.SUPABASE_URL,
        SUPABASE_ANON_KEY: window.SUPABASE_ANON_KEY,
    };

    // DOM cache, populated by ui.cacheDomElements()
    const dom = {};

    const state = {
        supabase: null,
        authModal: null,
        sidebarOffcanvas: null,
        abortController: null,
        debounceTimer: null,
        isRequestInProgress: false,
        originalSendButtonText: 'Send',
        // Fallback formatter, will be replaced by date-fns if it loads
        formatRelativeDate: (date) => date.toLocaleString(),
    };


    /* 2. UTILITY FUNCTIONS -------------------- */

    /**
     * Formats a raw Supabase auth error into a user-friendly message.
     * @param {Error} error The error object from Supabase.
     * @returns {string} A user-friendly error message.
     */
    const formatAuthError = (error) => {
        const message = error?.message?.toLowerCase() || '';
        if (message.includes('invalid login credentials')) return 'Incorrect email or password.';
        if (message.includes('email not confirmed')) return 'Please confirm your email first.';
        return error.message || 'An unknown error occurred.';
    };

    /**
     * Polls for the date-fns library to become available on the window object.
     */
    const pollForDateFns = () => {
        let attempts = 0;
        const maxAttempts = 50;
        const pollInterval = 100;

        const check = () => {
            if (window.dateFns?.formatRelative) {
                state.formatRelativeDate = window.dateFns.formatRelative;
            } else if (attempts++ < maxAttempts) {
                setTimeout(check, pollInterval);
            }
        };
        check();
    };


    /* 3. UI LAYER -------------------- */

    const ui = {
        /**
         * Caches all necessary DOM elements into the `dom` object for performance.
         */
        cacheDomElements() {
            const elementIds = {
                toastElem: 'toast', messagesContainer: 'messages', queryInput: 'query-input',
                sendButton: 'send-button', queryCategorySelect: 'query-category',
                authModalElement: 'authModal', loginForm: 'login-form', signupForm: 'signup-form',
                logoutButton: 'logout-button', logoutButtonOffcanvas: 'logout-button-offcanvas',
                authButton: 'auth-button', authButtonOffcanvas: 'auth-button-offcanvas',
                userStatusSpan: 'user-status', userStatusSpanOffcanvas: 'user-status-offcanvas',
                authErrorDiv: 'auth-error', sidebarOffcanvasElement: 'sidebarOffcanvas',
                sidebarContentRegular: 'sidebarContentRegular', themeToggle: 'theme-toggle',
                themeToggleOffcanvas: 'theme-toggle-offcanvas',
            };
            // Use Object.entries for a modern loop over the IDs
            Object.entries(elementIds).forEach(([key, id]) => {
                dom[key] = document.getElementById(id);
            });
        },

        /**
         * Displays a toast notification.
         * @param {string} message The message to display.
         * @param {boolean} [isError=false] True if the toast should have an error style.
         */
        showToast(message, isError = false) {
            if (!dom.toastElem) return;

            dom.toastElem.textContent = message;
            dom.toastElem.className = `toast-notification ${isError ? 'error' : 'success'}`;
            dom.toastElem.classList.remove('hidden');
            setTimeout(() => dom.toastElem.classList.add('hidden'), config.TOAST_DURATION);
        },

        /**
         * Scrolls the messages container to the bottom.
         */
        scrollMessagesToBottom() {
            dom.messagesContainer?.scrollTo({
                top: dom.messagesContainer.scrollHeight,
                behavior: 'smooth',
            });
        },

        /**
         * Adds a new message to the chat interface.
         * @param {string} text The message text.
         * @param {'user'|'bot'} sender The sender of the message.
         */
        addMessage(text, sender) {
            const isBot = sender === 'bot';
            // Sanitize bot HTML; escape user text to prevent XSS attacks.
            const safeHtml = isBot
                ? DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } })
                : text.replace(/</g, "&lt;").replace(/>/g, "&gt;");

            const messageHtml = `
                <div class="message ${isBot ? 'chatbot-message' : 'user-message'} animated-message mb-3">
                    <div class="message-bubble">
                        ${isBot ? '<div class="avatar mb-2"><img src="/static/images/bot.jpg" alt="Bot Avatar" class="rounded-circle" loading="lazy"></div>' : ''}
                        <div class="message-content">${safeHtml}</div>
                        <div class="timestamp">${state.formatRelativeDate(new Date())}</div>
                    </div>
                </div>`;

            const render = () => {
                dom.messagesContainer.insertAdjacentHTML('beforeend', messageHtml);
                if (isBot) {
                    const lastMessage = dom.messagesContainer.lastElementChild;
                    // Add styling classes to lists and code blocks from the parsed markdown
                    lastMessage.querySelectorAll('ul, ol').forEach(el => el.classList.add('message-list'));
                    lastMessage.querySelectorAll('pre code').forEach(el => el.parentElement.classList.add('message-code-block'));
                    lastMessage.querySelectorAll(':not(pre) > code').forEach(el => el.classList.add('message-inline-code'));
                }
                ui.scrollMessagesToBottom();
            };

            // Use the View Transitions API for smooth rendering if available
            document.startViewTransition ? document.startViewTransition(render) : render();
        },

        /**
         * Toggles the visibility of the skeleton loader/typing indicator.
         * @param {boolean} show True to show the indicator, false to hide it.
         */
        toggleTypingIndicator(show) {
            const indicatorId = 'typing-indicator';
            let indicator = document.getElementById(indicatorId);

            if (show) {
                if (indicator) return; // Already visible
                const skeletonHtml = `
                    <div id="${indicatorId}" class="skeleton-message-container animated-message">
                        <div class="skeleton skeleton-avatar"></div>
                        <div class="skeleton-content">
                            <div class="skeleton skeleton-line medium"></div>
                            <div class="skeleton skeleton-line"></div>
                            <div class="skeleton skeleton-line short"></div>
                        </div>
                    </div>`;
                dom.messagesContainer.insertAdjacentHTML('beforeend', skeletonHtml);
                this.scrollMessagesToBottom();
            } else {
                indicator?.remove();
            }
        },

        /**
         * Updates all auth-related UI elements based on user login status.
         * @param {object|null} user The Supabase user object, or null if logged out.
         */
        updateAuthUI(user) {
            const isLoggedIn = !!user;
            const statusText = isLoggedIn ? `Logged in as: ${user.email}` : 'Not logged in';

            const uiGroups = [
                { status: dom.userStatusSpan, auth: dom.authButton, logout: dom.logoutButton },
                { status: dom.userStatusSpanOffcanvas, auth: dom.authButtonOffcanvas, logout: dom.logoutButtonOffcanvas },
            ];

            uiGroups.forEach(group => {
                if (group.status) group.status.textContent = statusText;
                group.auth?.classList.toggle('d-none', isLoggedIn);
                group.logout?.classList.toggle('d-none', !isLoggedIn);
            });
        },

        /**
         * Displays an error message in the authentication modal.
         * @param {string} message The error message to display.
         */
        displayAuthError(message) {
            if (!dom.authErrorDiv) return;
            dom.authErrorDiv.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-2"></i><strong>${message}</strong>`;
            dom.authErrorDiv.classList.remove('d-none');
        },

        /**
         * Clears any visible auth errors and removes invalid input styles.
         */
        clearAuthError() {
            if (dom.authErrorDiv) {
                dom.authErrorDiv.classList.add('d-none');
                dom.authErrorDiv.innerHTML = '';
            }
            // Clear validation styles from both forms
            [dom.loginForm, dom.signupForm].forEach(form => {
                form?.querySelectorAll('.is-invalid').forEach(input => input.classList.remove('is-invalid'));
            });
        },

        /**
         * Toggles the UI into a "sending" state, disabling inputs.
         * @param {boolean} isSending True to enter sending state, false to exit.
         */
        setSendingState(isSending) {
            state.isRequestInProgress = isSending;
            if (!dom.sendButton || !dom.queryInput) return;

            // Collect all interactive elements and disable them in one go
            [dom.queryInput, dom.sendButton, ...document.querySelectorAll('.faq-button')].forEach(el => {
                if (el) el.disabled = isSending;
            });

            dom.sendButton.innerHTML = isSending
                ? `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Sending...`
                : `<i class="bi bi-send"></i> ${state.originalSendButtonText}`;

            if (!isSending) {
                state.abortController = null;
            }
        },

        /**
         * Initializes the color theme based on user preference or system settings.
         */
        initTheme() {
            const storedTheme = localStorage.getItem('theme');
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const defaultTheme = storedTheme || (prefersDark ? 'dark' : 'light');
            this.setTheme(defaultTheme, false);
        },

        /**
         * Sets the color theme for the entire application.
         * @param {'light'|'dark'} theme The theme to apply.
         * @param {boolean} [save=true] Whether to save the choice to localStorage.
         */
        setTheme(theme, save = true) {
            document.documentElement.setAttribute('data-bs-theme', theme);
            if (save) {
                localStorage.setItem('theme', theme);
            }
        },

        /**
         * Renders the FAQ buttons from the fetched data.
         * @param {object} faqData The FAQ data grouped by category.
         */
        renderFaqButtons(faqData) {
            const containers = {
                regulatory: document.querySelectorAll('[aria-label="Regulatory FAQs"]'),
                pharmacovigilance: document.querySelectorAll('[aria-label="Pharmacovigilance FAQs"]'),
            };

            // Clear any existing buttons from all containers first
            Object.values(containers).flat().forEach(container => container.innerHTML = '');

            Object.entries(faqData).forEach(([category, items]) => {
                if (!containers[category]) return;

                const fragment = document.createDocumentFragment();
                items.forEach(({ short, text }) => {
                    const button = document.createElement('button');
                    button.className = 'nav-link faq-button';
                    // Use Object.assign for a clean way to set multiple data attributes
                    Object.assign(button.dataset, { category: category, question: text });
                    button.textContent = short;
                    fragment.appendChild(button);
                });

                // Append the created buttons to all relevant containers
                containers[category].forEach(container => container.appendChild(fragment.cloneNode(true)));
            });
        },
    };


    /* 4. API SERVICES -------------------- */

    const services = {
        /**
         * Fetches FAQ data, using a cache-first strategy.
         * @returns {Promise<object|null>} The FAQ data or null on failure.
         */
        async getFaqData() {
            const cacheKey = 'frequentQuestionsData';
            const cached = localStorage.getItem(cacheKey);
            if (cached) {
                try {
                    return JSON.parse(cached);
                } catch (e) {
                    console.error("Failed to parse cached FAQ data:", e);
                    localStorage.removeItem(cacheKey); // Clear corrupted cache
                }
            }

            try {
                const response = await fetch('/api/frequent-questions');
                if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
                const data = await response.json();
                localStorage.setItem(cacheKey, JSON.stringify(data));
                return data;
            } catch (error) {
                console.error('Failed to fetch FAQs:', error);
                return null;
            }
        },

        /**
         * Sends a chat request to the backend API.
         * @param {string} query The user's query.
         * @param {string} category The selected category.
         * @param {string} token The user's JWT.
         * @returns {Promise<object>} The server's JSON response.
         */
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
                } catch {
                    // Ignore if response body is not valid JSON
                }
                throw new Error(errorMsg);
            }
            return response.json();
        },
    };


    /* 5. AUTHENTICATION LOGIC -------------------- */

    const auth = {
        /**
         * Retrieves the current session's JWT.
         * @returns {Promise<string|null>} The access token or null.
         */
        async getSessionToken() {
            const { data, error } = await state.supabase.auth.getSession();
            return error ? null : data.session?.access_token ?? null;
        },

        /**
         * Handles user login.
         * @param {string} email
         * @param {string} password
         */
        async login(email, password) {
            try {
                const { error } = await state.supabase.auth.signInWithPassword({ email, password });
                if (error) throw error;
                state.authModal?.hide();
                dom.loginForm?.reset();
                ui.showToast('Login successful!');
            } catch (error) {
                ui.displayAuthError(formatAuthError(error));
                dom.loginForm?.querySelectorAll('input').forEach(i => i.classList.add('is-invalid'));
            }
        },

        /**
         * Handles user signup.
         * @param {string} email
         * @param {string} password
         */
        async signup(email, password) {
            const { error } = await state.supabase.auth.signUp({ email, password });
            if (error) {
                ui.displayAuthError(formatAuthError(error));
            } else {
                state.authModal?.hide();
                dom.signupForm?.reset();
                ui.showToast('Signup initiated! Please check your email to confirm.');
            }
        },

        /**
         * Handles user logout.
         */
        async logout() {
            const { error } = await state.supabase.auth.signOut();
            if (error) {
                ui.showToast(`Logout failed: ${error.message}`, true);
            }
        },
    };


    /* 6. EVENT HANDLERS -------------------- */

    const handlers = {
        /**
         * Handles submissions for both login and signup forms.
         */
        handleAuthFormSubmit(event) {
            event.preventDefault();
            ui.clearAuthError();
            const form = event.target;
            const email = form.querySelector('input[type="email"]')?.value;
            const password = form.querySelector('input[type="password"]')?.value;

            if (form.id === 'login-form') {
                auth.login(email, password);
            } else if (form.id === 'signup-form') {
                auth.signup(email, password);
            }
        },

        /**
         * Handles clicks on FAQ buttons using event delegation.
         */
        handleFaqClick(event) {
            const button = event.target.closest('.faq-button');
            if (!button || state.isRequestInProgress) return;

            // Deactivate other buttons and activate the clicked one
            document.querySelectorAll('.faq-button.active').forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');

            // Populate input and submit
            dom.queryInput.value = button.dataset.question;
            dom.queryCategorySelect.value = button.dataset.category;

            // Hide the offcanvas sidebar if the click came from it
            if (state.sidebarOffcanvas && button.closest('#sidebarOffcanvas')) {
                state.sidebarOffcanvas.hide();
            }
            handlers.processQuery();
        },

        /**
         * The main logic for processing a user's query.
         */
        async processQuery() {
            // Abort any previous request that might still be running
            state.abortController?.abort();

            const query = dom.queryInput.value.trim();
            if (!query) return;

            const token = await auth.getSessionToken();
            if (!token) {
                ui.showToast('You must be logged in to chat.', true);
                state.authModal?.show();
                return;
            }

            ui.setSendingState(true);
            ui.addMessage(query, 'user');
            dom.queryInput.value = '';
            ui.toggleTypingIndicator(true);

            try {
                const category = dom.queryCategorySelect.value;
                const data = await services.sendChatRequest(query, category, token);
                ui.addMessage(data.response || `Error: ${data.error}`, 'bot');
            } catch (error) {
                // Don't show an error message if the request was intentionally aborted
                if (error.name !== 'AbortError') {
                    ui.addMessage(`Sorry, there was an error: ${error.message}`, 'bot');
                }
            } finally {
                ui.toggleTypingIndicator(false);
                ui.setSendingState(false);
            }
        },

        /**
         * A debounced wrapper for processQuery to prevent spamming.
         */
        debouncedProcessQuery() {
            clearTimeout(state.debounceTimer);
            state.debounceTimer = setTimeout(handlers.processQuery, config.DEBOUNCE_DELAY);
        }
    };


    /* 7. EVENT BINDING -------------------- */

    /**
     * Binds all application event listeners to the DOM.
     */
    function bindEventListeners() {
        // Chat Input
        dom.sendButton?.addEventListener('click', handlers.debouncedProcessQuery);
        dom.queryInput?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault(); // Prevent new line on enter
                handlers.debouncedProcessQuery();
            }
        });

        // Auth Forms
        dom.loginForm?.addEventListener('submit', handlers.handleAuthFormSubmit);
        dom.signupForm?.addEventListener('submit', handlers.handleAuthFormSubmit);

        // FAQ Buttons (using delegation)
        dom.sidebarContentRegular?.addEventListener('click', handlers.handleFaqClick);
        dom.sidebarOffcanvasElement?.addEventListener('click', handlers.handleFaqClick);

        // Auth/Logout and Theme Toggle Buttons
        [dom.authButton, dom.authButtonOffcanvas].forEach(btn => btn?.addEventListener('click', () => state.authModal?.show()));
        [dom.logoutButton, dom.logoutButtonOffcanvas].forEach(btn => btn?.addEventListener('click', auth.logout));
        [dom.themeToggle, dom.themeToggleOffcanvas].forEach(btn => {
            btn?.addEventListener('click', () => {
                const currentTheme = document.documentElement.getAttribute('data-bs-theme');
                ui.setTheme(currentTheme === 'dark' ? 'light' : 'dark');
            });
        });
    }


    /* 8. INITIALIZATION -------------------- */

    /**
     * Initializes the entire application. This is the only public method.
     */
    async function init() {
        ui.cacheDomElements();
        ui.initTheme();
        pollForDateFns();

        if (!config.SUPABASE_URL || !config.SUPABASE_ANON_KEY) {
            return ui.showToast("Authentication is not configured. Please check environment variables.", true);
        }

        try {
            state.supabase = createClient(config.SUPABASE_URL, config.SUPABASE_ANON_KEY);
            // Initialize Bootstrap components only if their elements exist
            if (dom.authModalElement) {
                state.authModal = new bootstrap.Modal(dom.authModalElement);
            }
            if (dom.sidebarOffcanvasElement) {
                state.sidebarOffcanvas = new bootstrap.Offcanvas(dom.sidebarOffcanvasElement);
            }
            if (dom.sendButton) {
                state.originalSendButtonText = dom.sendButton.textContent.trim() || 'Send';
            }
        } catch (error) {
            console.error("Initialization error:", error);
            return ui.showToast("Failed to initialize application UI.", true);
        }

        bindEventListeners();

        const faqData = await services.getFaqData();
        if (faqData) {
            ui.renderFaqButtons(faqData);
        } else {
            // Display an error if FAQs couldn't be loaded
            document.querySelectorAll('[aria-label$="FAQs"]').forEach(container => {
                container.innerHTML = '<div class="text-danger small text-center py-3">Failed to load FAQs.</div>';
            });
        }

        // Set initial auth state and listen for changes
        const { data: { session } } = await state.supabase.auth.getSession();
        ui.updateAuthUI(session?.user ?? null);
        state.supabase.auth.onAuthStateChange((_event, session) => {
            ui.updateAuthUI(session?.user ?? null);
        });
    }

    // Public API: only expose the init function
    return {
        init: init
    };

})();

// Start the application once the DOM is fully loaded
document.addEventListener('DOMContentLoaded', App.init);
