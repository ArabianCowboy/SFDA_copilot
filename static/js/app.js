// SFDA Copilot Main App Script - Enhanced Final Version
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';
import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.0/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.0.8/+esm';

/**
 * Main application module, wrapped in an IIFE to create a private scope.
 * This combines the benefits of a single global namespace (App) with strong encapsulation.
 */
const App = (function () {

    // --- Private Application State & Configuration ---

    const config = {
        TOAST_DURATION: 3000,
        DEBOUNCE_DELAY: 300,
        SUPABASE_URL: window.SUPABASE_URL,
        SUPABASE_ANON_KEY: window.SUPABASE_ANON_KEY,
    };

    const dom = {}; // DOM cache, populated by _cacheDomElements

    const state = {
        supabase: null,
        authModal: null,
        sidebarOffcanvas: null,
        abortController: null,
        debounceTimer: null,
        isRequestInProgress: false,
        originalSendButtonText: 'Send',
        formatRelativeDate: (date) => date.toLocaleString(),
    };

    // --- Private Helper Functions ---

    /**
     * Formats a raw authentication error into a user-friendly message.
     * @param {Error} error The error object from Supabase.
     * @returns {string} A user-friendly error message.
     */
    function _formatAuthError(error) {
        const message = error.message.toLowerCase();
        if (message.includes('invalid login credentials')) return 'Incorrect email or password.';
        if (message.includes('email not confirmed')) return 'Please confirm your email first.';
        return error.message || 'An unknown error occurred.';
    }

    // --- Private Modules (organized as objects) ---

    const ui = {
        cacheDomElements() {
            const elements = {
                toastElem: 'toast', messagesContainer: 'messages', queryInput: 'query-input',
                sendButton: 'send-button', queryCategorySelect: 'query-category',
                authModalElement: 'authModal', loginForm: 'login-form', signupForm: 'signup-form',
                logoutButton: 'logout-button', logoutButtonOffcanvas: 'logout-button-offcanvas',
                authButton: 'auth-button', authButtonOffcanvas: 'auth-button-offcanvas',
                userStatusSpan: 'user-status', userStatusSpanOffcanvas: 'user-status-offcanvas',
                authErrorDiv: 'auth-error', sidebarOffcanvasElement: 'sidebarOffcanvas',
                sidebarContentRegular: 'sidebarContentRegular',
            };
            for (const key in elements) {
                dom[key] = document.getElementById(elements[key]);
            }
        },

        showToast(message, isError = false) {
            if (!dom.toastElem) return;
            dom.toastElem.textContent = message;
            dom.toastElem.className = `toast-notification ${isError ? 'error' : ''}`;
            setTimeout(() => dom.toastElem.classList.add('hidden'), config.TOAST_DURATION);
        },

        scrollMessagesToBottom() {
            dom.messagesContainer?.scrollTo({ top: dom.messagesContainer.scrollHeight, behavior: 'smooth' });
        },

        updateAuthUI(user) {
            const isLoggedIn = !!user;
            const statusText = isLoggedIn ? `Logged in as: ${user.email}` : 'Not logged in';
            const elements = [
                { status: dom.userStatusSpan, auth: dom.authButton, logout: dom.logoutButton },
                { status: dom.userStatusSpanOffcanvas, auth: dom.authButtonOffcanvas, logout: dom.logoutButtonOffcanvas },
            ];
            elements.forEach(group => {
                if (group.status) group.status.textContent = statusText;
                group.auth?.classList.toggle('d-none', isLoggedIn);
                group.logout?.classList.toggle('d-none', !isLoggedIn);
            });
        },
        
        displayAuthError(message) {
            if (!dom.authErrorDiv) return;
            dom.authErrorDiv.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-2"></i><strong>${message}</strong>`;
            dom.authErrorDiv.classList.remove('d-none');
        },

        clearAuthError() {
            if (!dom.authErrorDiv) return;
            dom.authErrorDiv.classList.add('d-none');
            dom.authErrorDiv.innerHTML = '';
            [dom.loginForm, dom.signupForm].forEach(form => {
                form?.querySelectorAll('.is-invalid').forEach(input => input.classList.remove('is-invalid'));
            });
        },

        setSendingState(isSending) {
            state.isRequestInProgress = isSending;
            if (!dom.sendButton || !dom.queryInput) return;

            dom.queryInput.disabled = isSending;
            dom.sendButton.disabled = isSending;
            document.querySelectorAll('.faq-button').forEach(button => button.disabled = isSending);

            const spinner = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>`;
            if (isSending) {
                dom.sendButton.innerHTML = `${spinner} Sending...`;
            } else {
                dom.sendButton.innerHTML = `<i class="bi bi-send"></i> ${state.originalSendButtonText}`;
                state.abortController = null;
            }
        },

        toggleTypingIndicator(show) {
            let indicator = document.getElementById('typing-indicator');
            if (show) {
                if (indicator) return;
                const skeletonHtml = `
                    <div id="typing-indicator" class="skeleton-message-container animated-message">
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

        addMessage(text, sender) {
            const isBot = sender === 'bot';
            const safeHtml = isBot ? DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } }) : text;

            const messageHtml = `
                <div class="message ${isBot ? 'chatbot-message' : 'user-message'} animated-message mb-3">
                    <div class="message-bubble">
                        ${isBot ? '<div class="avatar mb-2"><img src="/static/images/bot.jpg" alt="Bot Avatar" class="rounded-circle" loading="lazy"></div>' : ''}
                        <div class="message-content">${safeHtml}</div>
                        <div class="timestamp">${state.formatRelativeDate(new Date(), new Date())}</div>
                    </div>
                </div>`;
            
            const render = () => {
                dom.messagesContainer.insertAdjacentHTML('beforeend', messageHtml);
                if (isBot) {
                    const lastMessage = dom.messagesContainer.lastElementChild;
                    lastMessage.querySelectorAll('ul, ol').forEach(list => list.classList.add('message-list'));
                    lastMessage.querySelectorAll('pre code').forEach(el => el.parentElement.classList.add('message-code-block'));
                    lastMessage.querySelectorAll('p code, li code').forEach(el => el.classList.add('message-inline-code'));
                }
                this.scrollMessagesToBottom();
            };
            
            document.startViewTransition ? document.startViewTransition(render) : render();
        },

        renderFaqButtons(faqData) {
            const containers = {
                regulatory: document.querySelectorAll('[aria-label="Regulatory FAQs"]'),
                pharmacovigilance: document.querySelectorAll('[aria-label="Pharmacovigilance FAQs"]'),
            };
            Object.values(containers).forEach(nodelist => nodelist.forEach(c => c.innerHTML = ''));

            for (const category in faqData) {
                if (Object.hasOwnProperty.call(faqData, category) && containers[category]) {
                    const fragment = document.createDocumentFragment();
                    faqData[category].forEach(q => {
                        const button = document.createElement('button');
                        button.className = 'nav-link faq-button';
                        button.dataset.category = category;
                        button.dataset.question = q.text;
                        button.textContent = q.short;
                        fragment.appendChild(button);
                    });
                    containers[category].forEach(c => c.appendChild(fragment.cloneNode(true)));
                }
            }
        }
    };

    const services = {
        async getFaqData() {
            const cacheKey = 'frequentQuestionsData';
            const cachedData = localStorage.getItem(cacheKey);
            if (cachedData) return JSON.parse(cachedData);

            try {
                const response = await fetch('/api/frequent-questions');
                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                const data = await response.json();
                localStorage.setItem(cacheKey, JSON.stringify(data));
                return data;
            } catch (error) {
                console.error('Failed to fetch frequent questions:', error);
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
                } catch {}
                throw new Error(errorMsg);
            }
            return response.json();
        },
    };

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
                dom.loginForm.reset();
                ui.showToast('Login successful!');
            } catch (error) {
                ui.displayAuthError(_formatAuthError(error));
                dom.loginForm.querySelectorAll('input').forEach(i => i.classList.add('is-invalid'));
            }
        },
        async signup(email, password) {
            const { error } = await state.supabase.auth.signUp({ email, password });
            if (error) {
                ui.displayAuthError(_formatAuthError(error));
            } else {
                state.authModal?.hide();
                dom.signupForm.reset();
                ui.showToast('Signup initiated! Please check your email to confirm.');
            }
        },
        async logout() {
            const { error } = await state.supabase.auth.signOut();
            if (error) ui.showToast(`Logout failed: ${error.message}`, true);
        },
    };

    const handlers = {
        handleFormSubmit(event) {
            event.preventDefault();
            ui.clearAuthError();
            const form = event.target;
            const email = form.querySelector('input[type="email"]').value;
            const password = form.querySelector('input[type="password"]').value;
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

            if (state.sidebarOffcanvas && button.closest('#sidebarOffcanvas')) {
                state.sidebarOffcanvas.hide();
            }
            handlers.processQuery();
        },
        async processQuery() {
            if (state.abortController) state.abortController.abort();

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
            state.debounceTimer = setTimeout(handlers.processQuery, config.DEBOUNCE_DELAY);
        }
    };

    function bindEventListeners() {
        dom.sendButton?.addEventListener('click', handlers.debouncedProcessQuery);
        dom.queryInput?.addEventListener('keypress', e => { if (e.key === 'Enter') handlers.debouncedProcessQuery(); });
        dom.loginForm?.addEventListener('submit', handlers.handleFormSubmit);
        dom.signupForm?.addEventListener('submit', handlers.handleFormSubmit);
        
        dom.sidebarContentRegular?.addEventListener('click', handlers.handleFaqClick);
        dom.sidebarOffcanvasElement?.addEventListener('click', handlers.handleFaqClick);
        
        [dom.authButton, dom.authButtonOffcanvas].forEach(btn => btn?.addEventListener('click', () => state.authModal?.show()));
        [dom.logoutButton, dom.logoutButtonOffcanvas].forEach(btn => btn?.addEventListener('click', auth.logout));
    }

    /**
     * Initializes the entire application. This is the only public method.
     */
    async function init() {
        ui.cacheDomElements();

        // Initialize date-fns fallback
        (() => {
            let attempts = 0;
            const check = () => {
                if (window.dateFns?.formatRelative) state.formatRelativeDate = window.dateFns.formatRelative;
                else if (attempts++ < 50) setTimeout(check, 100);
            };
            check();
        })();

        if (!config.SUPABASE_URL || !config.SUPABASE_ANON_KEY) {
            ui.showToast("Authentication is not configured.", true);
            return;
        }

        try {
            state.supabase = createClient(config.SUPABASE_URL, config.SUPABASE_ANON_KEY);
            state.authModal = new bootstrap.Modal(dom.authModalElement);
            state.sidebarOffcanvas = new bootstrap.Offcanvas(dom.sidebarOffcanvasElement);
            state.originalSendButtonText = dom.sendButton?.textContent.trim() || 'Send';
        } catch (error) {
            ui.showToast("Failed to initialize application.", true);
            return;
        }

        bindEventListeners();

        const faqData = await services.getFaqData();
        if (faqData) {
            ui.renderFaqButtons(faqData);
        } else {
            document.querySelectorAll('[aria-label$="FAQs"]').forEach(c => {
                c.innerHTML = '<div class="text-danger small text-center py-3">Failed to load FAQs.</div>';
            });
        }

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

// Start the application
document.addEventListener('DOMContentLoaded', App.init);