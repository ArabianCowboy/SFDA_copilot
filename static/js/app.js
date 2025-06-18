// SFDA Copilot — Main Application Script (Refactored Version)
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';
import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.0/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.0.8/+esm';

const App = (() => {
    /* 1. CONSTANTS & CONFIGURATION -------------------- */
    const C = {
        TOAST_DURATION: 3000,
        DEBOUNCE_DELAY: 300,
        DATE_FNS_POLL_INTERVAL: 100,
        DATE_FNS_MAX_ATTEMPTS: 50,
        SUPABASE_URL: window.SUPABASE_URL,
        SUPABASE_ANON_KEY: window.SUPABASE_ANON_KEY,
        // CSS classes
        HIDDEN_CLASS: 'hidden',
        INVALID_CLASS: 'is-invalid',
        DARK_THEME_CLASS: 'dark',
        LIGHT_THEME_CLASS: 'light',
    };

    const dom = {}; // DOM element cache
    const state = {
        supabase: null,
        authModal: null,
        sidebarOffcanvas: null,
        abortController: null,
        debounceTimer: null,
        isRequestInProgress: false,
        originalSendButtonText: 'Send',
        formatRelativeDate: (date) => date.toLocaleString(), // Fallback
    };

    /* 2. UTILITY & HELPER FUNCTIONS -------------------- */

    /** Safely creates and sanitizes message content. */
    const createMessageContent = (text, isBot) => {
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        if (isBot) {
            const sanitizedHtml = DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } });
            contentDiv.innerHTML = sanitizedHtml;
        } else {
            // This is the safest way to insert user-provided text into the DOM.
            // It treats the text as plain text, not HTML, preventing XSS attacks.
            contentDiv.textContent = text;
        }
        return contentDiv;
    };

    /** Waits for the date-fns library to be available on the window object. */
    const waitForDateFns = () => {
        return new Promise((resolve) => {
            let attempts = 0;
            const check = () => {
                if (window.dateFns?.formatRelative) {
                    state.formatRelativeDate = (date) => window.dateFns.formatRelative(date, new Date());
                    resolve();
                } else if (attempts++ < C.DATE_FNS_MAX_ATTEMPTS) {
                    setTimeout(check, C.DATE_FNS_POLL_INTERVAL);
                } else {
                    console.warn('date-fns library not found after polling.');
                    resolve(); // Resolve anyway to not block initialization
                }
            };
            check();
        });
    };
    
    /** Formats a Supabase auth error into a user-friendly message. */
    const formatAuthError = (error) => {
        const message = error?.message?.toLowerCase() || '';
        if (message.includes('invalid login credentials')) return 'Incorrect email or password.';
        if (message.includes('email not confirmed')) return 'Please confirm your email first.';
        return error.message || 'An unknown error occurred.';
    };

    /* 3. UI LAYER -------------------- */
    const ui = {
        cacheDomElements() {
            const ids = {
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
            for (const key in ids) {
                dom[key] = document.getElementById(ids[key]);
            }
        },

        showToast(message, isError = false) {
            if (!dom.toastElem) return;
            dom.toastElem.textContent = message;
            dom.toastElem.className = `toast-notification ${isError ? 'error' : 'success'}`;
            dom.toastElem.classList.remove(C.HIDDEN_CLASS);
            setTimeout(() => dom.toastElem.classList.add(C.HIDDEN_CLASS), C.TOAST_DURATION);
        },
        
        scrollMessagesToBottom() {
            dom.messagesContainer?.scrollTo({ top: dom.messagesContainer.scrollHeight, behavior: 'smooth' });
        },

        /** Creates and appends a new message element to the chat interface. */
        addMessage(text, sender) {
            const isBot = sender === 'bot';
            
            // Create elements programmatically to ensure security
            const messageWrapper = document.createElement('div');
            messageWrapper.className = `message ${isBot ? 'chatbot-message' : 'user-message'} animated-message mb-3`;
            
            const messageBubble = document.createElement('div');
            messageBubble.className = 'message-bubble';

            if (isBot) {
                const avatarDiv = document.createElement('div');
                avatarDiv.className = 'avatar mb-2';
                avatarDiv.innerHTML = `<img src="/static/images/bot.jpg" alt="Bot Avatar" class="rounded-circle" loading="lazy">`;
                messageBubble.appendChild(avatarDiv);
            }

            const contentEl = createMessageContent(text, isBot);
            messageBubble.appendChild(contentEl);

            const timestampEl = document.createElement('div');
            timestampEl.className = 'timestamp';
            timestampEl.textContent = state.formatRelativeDate(new Date());
            messageBubble.appendChild(timestampEl);

            messageWrapper.appendChild(messageBubble);

            const render = () => {
                dom.messagesContainer.appendChild(messageWrapper);
                if (isBot) {
                    messageWrapper.querySelectorAll('ul, ol').forEach(el => el.classList.add('message-list'));
                    messageWrapper.querySelectorAll('pre code').forEach(el => el.parentElement.classList.add('message-code-block'));
                    messageWrapper.querySelectorAll(':not(pre) > code').forEach(el => el.classList.add('message-inline-code'));
                }
                this.scrollMessagesToBottom();
            };

            document.startViewTransition ? document.startViewTransition(render) : render();
        },
        
        toggleTypingIndicator(show) {
            const indicatorId = 'typing-indicator';
            const existingIndicator = document.getElementById(indicatorId);

            if (show) {
                if (existingIndicator) return;
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
                existingIndicator?.remove();
            }
        },

        updateAuthUI(user) {
            const isLoggedIn = !!user;
            const statusText = isLoggedIn ? `Logged in as: ${user.email}` : 'Not logged in';
            const uiGroups = [
                { status: dom.userStatusSpan, auth: dom.authButton, logout: dom.logoutButton },
                { status: dom.userStatusSpanOffcanvas, auth: dom.authButtonOffcanvas, logout: dom.logoutButtonOffcanvas },
            ];
            uiGroups.forEach(({ status, auth, logout }) => {
                if (status) status.textContent = statusText;
                auth?.classList.toggle('d-none', isLoggedIn);
                logout?.classList.toggle('d-none', !isLoggedIn);
            });
        },
        
        displayAuthError(message) {
            if (!dom.authErrorDiv) return;
            dom.authErrorDiv.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-2"></i><strong>${message}</strong>`;
            dom.authErrorDiv.classList.remove('d-none');
        },
        
        clearAuthError() {
            if (dom.authErrorDiv) {
                dom.authErrorDiv.classList.add('d-none');
                dom.authErrorDiv.innerHTML = '';
            }
            [dom.loginForm, dom.signupForm].forEach(form => {
                form?.querySelectorAll(`.${C.INVALID_CLASS}`).forEach(input => input.classList.remove(C.INVALID_CLASS));
            });
        },
        
        setSendingState(isSending) {
            state.isRequestInProgress = isSending;
            const elementsToToggle = [dom.queryInput, dom.sendButton, ...document.querySelectorAll('.faq-button')];
            elementsToToggle.forEach(el => { if (el) el.disabled = isSending; });

            if (dom.sendButton) {
                 dom.sendButton.innerHTML = isSending
                    ? `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Sending...`
                    : `<i class="bi bi-send"></i> ${state.originalSendButtonText}`;
            }
           
            if (!isSending) state.abortController = null;
        },

        initTheme() {
            const storedTheme = localStorage.getItem('theme');
            const prefersDark = window.matchMedia(`(prefers-color-scheme: ${C.DARK_THEME_CLASS})`).matches;
            this.setTheme(storedTheme || (prefersDark ? C.DARK_THEME_CLASS : C.LIGHT_THEME_CLASS), false);
        },

        setTheme(theme, save = true) {
            document.documentElement.setAttribute('data-bs-theme', theme);
            if (save) localStorage.setItem('theme', theme);
        },
        
        toggleTheme() {
            const currentTheme = document.documentElement.getAttribute('data-bs-theme');
            this.setTheme(currentTheme === C.DARK_THEME_CLASS ? C.LIGHT_THEME_CLASS : C.DARK_THEME_CLASS);
        },

        renderFaqButtons(faqData) {
            const mainFaqContainer = document.getElementById('faq-sidebar-section');
            const offcanvasFaqContainer = document.getElementById('faq-offcanvas-section');

            // Clear existing content
            if (mainFaqContainer) mainFaqContainer.innerHTML = '';
            if (offcanvasFaqContainer) offcanvasFaqContainer.innerHTML = '';

            Object.entries(faqData).forEach(([category, categoryData]) => {
                console.log("Processing category:", category); // Debug log
                if (!categoryData.questions || categoryData.questions.length === 0) return; // Skip empty categories

                const iconClass = categoryData.icon || 'bi-question-circle'; // Default icon
                const titleText = categoryData.title || `${category.charAt(0).toUpperCase() + category.slice(1)} FAQs`;

                // Create elements for main sidebar
                const mainCategoryHeader = document.createElement('h4');
                mainCategoryHeader.className = 'ps-2' + (category !== 'regulatory' ? ' mt-3' : ''); // Add margin top for all but first
                mainCategoryHeader.innerHTML = `<i class="bi ${iconClass}"></i>${titleText}`;
                
                const mainCategoryNav = document.createElement('nav');
                mainCategoryNav.className = 'nav nav-pills flex-column';
                mainCategoryNav.id = `${category}-faq-container`; // Keep old IDs for compatibility if needed

                // Create elements for offcanvas sidebar
                const offcanvasCategoryHeader = document.createElement('h4');
                offcanvasCategoryHeader.className = 'ps-2' + (category !== 'regulatory' ? ' mt-3' : '');
                offcanvasCategoryHeader.innerHTML = `<i class="bi ${iconClass}"></i>${titleText}`;
                
                const offcanvasCategoryNav = document.createElement('nav');
                offcanvasCategoryNav.className = 'nav nav-pills flex-column';
                offcanvasCategoryNav.id = `${category}-faq-offcanvas-container`; // Keep old IDs for compatibility if needed

                categoryData.questions.forEach(({ short, text }) => {
                    const button = document.createElement('button');
                    button.className = 'nav-link faq-button';
                    Object.assign(button.dataset, { category, question: text });
                    button.textContent = short;
                    
                    mainCategoryNav.appendChild(button.cloneNode(true)); // Clone for main sidebar
                    offcanvasCategoryNav.appendChild(button); // Use original for offcanvas
                });

                if (mainFaqContainer) {
                    mainFaqContainer.appendChild(mainCategoryHeader);
                    mainFaqContainer.appendChild(mainCategoryNav);
                }
                if (offcanvasFaqContainer) {
                    offcanvasFaqContainer.appendChild(offcanvasCategoryHeader);
                    offcanvasFaqContainer.appendChild(offcanvasCategoryNav);
                }
            });
        },
    };

    /* 4. API SERVICES -------------------- */
    const services = {
        async getFaqData() {
            const cacheKey = 'frequentQuestionsData';
            localStorage.removeItem(cacheKey); // Temporarily clear cache for debugging
            const cached = localStorage.getItem(cacheKey);
            if (cached) {
                try {
                    return JSON.parse(cached);
                } catch (e) {
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
                    errorMsg = (await response.json()).error || errorMsg;
                } catch { /* Ignore if response body is not valid JSON */ }
                throw new Error(errorMsg);
            }
            return response.json();
        },
    };

    /* 5. AUTHENTICATION LOGIC -------------------- */
    const auth = {
        async getSessionToken() {
            const { data, error } = await state.supabase.auth.getSession();
            return error ? null : data.session?.access_token ?? null;
        },

        async login(email, password) {
            try {
                const { error } = await state.supabase.auth.signInWithPassword({ email, password });
                if (error) throw error;
                state.authModal?.hide();
                dom.loginForm?.reset();
                ui.showToast('Login successful!');
            } catch (error) {
                ui.displayAuthError(formatAuthError(error));
                dom.loginForm?.querySelectorAll('input').forEach(i => i.classList.add(C.INVALID_CLASS));
            }
        },

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

        async logout() {
            const { error } = await state.supabase.auth.signOut();
            if (error) {
                ui.showToast(`Logout failed: ${error.message}`, true);
            }
        },
    };

    /* 6. EVENT HANDLERS -------------------- */
    const handlers = {
        handleAuthFormSubmit(event) {
            event.preventDefault();
            ui.clearAuthError();
            const form = event.target;
            const email = form.elements.email.value;
            const password = form.elements.password.value;
            
            if (form.id === 'login-form') auth.login(email, password);
            else if (form.id === 'signup-form') auth.signup(email, password);
        },

        handleFaqClick(event) {
            const button = event.target.closest('.faq-button');
            if (!button || state.isRequestInProgress) return;

            document.querySelectorAll('.faq-button.active').forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');

            dom.queryInput.value = button.dataset.question;
            dom.queryCategorySelect.value = button.dataset.category;

            console.log("Category from button dataset:", button.dataset.category); // Debug log
            console.log("Category set in select element:", dom.queryCategorySelect.value); // Debug log

            if (button.closest('#sidebarOffcanvas')) {
                state.sidebarOffcanvas?.hide();
            }
            handlers.processQuery();
        },

        async processQuery() {
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
                console.log("Category being sent to API:", category); // Debug log
                const data = await services.sendChatRequest(query, category, token);
                ui.addMessage(data.response || `Error: ${data.error}`, 'bot');
            } catch (error) {
                if (error.name !== 'AbortError') {
                    ui.addMessage(`Sorry, there was an error: ${error.message}`, 'bot');
                }
            } finally {
                ui.toggleTypingIndicator(false);
                ui.setSendingState(false);
            }
        },

        debouncedProcessQuery() {
            clearTimeout(state.debounceTimer);
            state.debounceTimer = setTimeout(handlers.processQuery, C.DEBOUNCE_DELAY);
        }
    };

    /* 7. EVENT BINDING -------------------- */
    function bindEventListeners() {
        dom.sendButton?.addEventListener('click', handlers.processQuery);
        dom.queryInput?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handlers.debouncedProcessQuery();
            }
        });
        
        dom.loginForm?.addEventListener('submit', handlers.handleAuthFormSubmit);
        dom.signupForm?.addEventListener('submit', handlers.handleAuthFormSubmit);

        dom.sidebarContentRegular?.addEventListener('click', handlers.handleFaqClick);
        dom.sidebarOffcanvasElement?.addEventListener('click', handlers.handleFaqClick);

        [dom.authButton, dom.authButtonOffcanvas].forEach(btn => btn?.addEventListener('click', () => state.authModal?.show()));
        [dom.logoutButton, dom.logoutButtonOffcanvas].forEach(btn => btn?.addEventListener('click', auth.logout));
        [dom.themeToggle, dom.themeToggleOffcanvas].forEach(btn => btn?.addEventListener('click', () => ui.toggleTheme()));
    }

    /* 8. INITIALIZATION -------------------- */
    async function init() {
        ui.cacheDomElements();
        ui.initTheme();
        await waitForDateFns();

        if (!C.SUPABASE_URL || !C.SUPABASE_ANON_KEY) {
            return ui.showToast("Authentication is not configured.", true);
        }

        try {
            state.supabase = createClient(C.SUPABASE_URL, C.SUPABASE_ANON_KEY);
            if (dom.authModalElement) state.authModal = new bootstrap.Modal(dom.authModalElement);
            if (dom.sidebarOffcanvasElement) state.sidebarOffcanvas = new bootstrap.Offcanvas(dom.sidebarOffcanvasElement);
            if (dom.sendButton) state.originalSendButtonText = dom.sendButton.textContent.trim() || 'Send';
        } catch (error) {
            console.error("Initialization error:", error);
            return ui.showToast("Failed to initialize application UI.", true);
        }

        bindEventListeners();

        const faqData = await services.getFaqData();
        console.log("FAQ Data received by frontend:", faqData); // New debug log
        if (faqData && Object.keys(faqData).length > 0) { // Check if faqData is not empty
            ui.renderFaqButtons(faqData);
        } else {
            document.querySelectorAll('[aria-label$="FAQs"]').forEach(container => {
                container.innerHTML = '<div class="text-danger small text-center py-3">Failed to load FAQs or FAQs are empty.</div>';
            });
        }

        const { data: { session } } = await state.supabase.auth.getSession();
        ui.updateAuthUI(session?.user ?? null);
        state.supabase.auth.onAuthStateChange((_event, session) => {
            ui.updateAuthUI(session?.user ?? null);
        });
    }
    
    return { init };
})();

document.addEventListener('DOMContentLoaded', App.init);
