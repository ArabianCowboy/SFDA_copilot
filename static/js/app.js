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
            ANIMATE_CARD: 'animate-card',
            ANIMATED: 'animated', // Class to mark elements that have been animated
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
        profileModal: null,
        userProfile: null,
        eventListenersBound: false,
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
                themeToggleOffcanvas: '#theme-toggle-offcanvas',
                landingThemeToggle: '#landing-theme-toggle',
                toastElem: '#toast',
                // FAQ
                faqSidebarSection: '#faq-sidebar-section',
                // Profile
                profileButton: '#profile-button',
                profileButtonOffcanvas: '#profile-button-offcanvas',
                profileForm: '#profile-form',
                profileErrorDiv: '#profile-error',
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
            messageWrapper.className = `message ${isBot ? 'chatbot-message' : 'user-message'} mb-3 message-medium`;

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

            // Add suggested questions container for bot messages
            if (isBot) {
                const suggestionsContainer = document.createElement('div');
                suggestionsContainer.className = 'suggested-questions-container mt-2';
                messageBubble.appendChild(suggestionsContainer);
            }

            messageWrapper.appendChild(messageBubble);
            return messageWrapper;
        },

        /** Appends a new message to the chat and applies post-processing. */
        addMessage(text, sender, suggestedQuestions = []) {
            const messageEl = this.createMessageElement(text, sender);

            const render = () => {
                DOMElements.messagesContainer.appendChild(messageEl);
                if (sender === 'bot') {
                    messageEl.querySelectorAll('ul, ol').forEach(el => el.classList.add('message-list'));
                    messageEl.querySelectorAll('pre code').forEach(el => el.parentElement.classList.add('message-code-block'));
                    messageEl.querySelectorAll(':not(pre) > code').forEach(el => el.classList.add('message-inline-code'));
                    
                    // Render suggested questions if available
                    if (suggestedQuestions && suggestedQuestions.length > 0) {
                        const suggestionsContainer = messageEl.querySelector('.suggested-questions-container');
                        if (suggestionsContainer) {
                            suggestedQuestions.forEach((question, index) => {
                                const button = document.createElement('button');
                                button.className = 'suggested-question-enhanced';
                                
                                // Add icon element
                                const icon = document.createElement('i');
                                icon.className = 'fas fa-lightbulb suggested-question-icon';
                                icon.setAttribute('aria-hidden', 'true');
                                
                                // Create text node
                                const textNode = document.createTextNode(question);
                                
                                // Append icon and text to button
                                button.appendChild(icon);
                                button.appendChild(textNode);
                                
                                // Add accessibility attributes
                                button.setAttribute('role', 'button');
                                button.setAttribute('aria-label', `Ask: ${question}`);
                                button.setAttribute('tabindex', '0');
                                
                                // Add subtle staggered animation delay for visual appeal
                                button.style.animationDelay = `${index * 0.1}s`;
                                
                                suggestionsContainer.appendChild(button);
                            });
                        } else {
                            console.warn('Suggested questions container not found for bot message.');
                        }
                    }
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
            [DOMElements.profileButton, DOMElements.profileButtonOffcanvas].forEach(button => {
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

        displayProfileError(message) {
            if (!DOMElements.profileErrorDiv) return;
            DOMElements.profileErrorDiv.textContent = message;
            DOMElements.profileErrorDiv.classList.remove(CONFIG.CSS_CLASSES.D_NONE);
        },

        clearProfileError() {
            if (DOMElements.profileErrorDiv) {
                DOMElements.profileErrorDiv.classList.add(CONFIG.CSS_CLASSES.D_NONE);
                DOMElements.profileErrorDiv.textContent = '';
            }
        },

        populateProfileForm(profile) {
            if (!profile || !DOMElements.profileForm) return;
            DOMElements.profileForm.querySelector('#profile-full-name').value = profile.full_name || '';
            DOMElements.profileForm.querySelector('#profile-organization').value = profile.organization || '';
            DOMElements.profileForm.querySelector('#profile-specialization').value = profile.specialization || '';
            
            const themePreference = profile.preferences?.theme || 'light';
            const themeRadio = DOMElements.profileForm.querySelector(`input[name="theme-preference"][value="${themePreference}"]`);
            if (themeRadio) themeRadio.checked = true;
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
            this.bindThemeToggleEvents();
        },

        setTheme(theme, save = true) {
            document.documentElement.setAttribute('data-bs-theme', theme);
            if (save) localStorage.setItem('theme', theme);
            
            // Update the checked state for all theme toggles
            const isDark = theme === CONFIG.CSS_CLASSES.DARK_THEME;
            [
                DOMElements.landingThemeToggle,
                DOMElements.themeToggle,
                DOMElements.themeToggleOffcanvas
            ].forEach(toggle => {
                if (toggle) toggle.checked = isDark;
            });
        },

        toggleTheme() {
            const currentTheme = document.documentElement.getAttribute('data-bs-theme');
            this.setTheme(currentTheme === CONFIG.CSS_CLASSES.DARK_THEME ? CONFIG.CSS_CLASSES.LIGHT_THEME : CONFIG.CSS_CLASSES.DARK_THEME);
        },

        bindThemeToggleEvents() {
            [
                DOMElements.landingThemeToggle,
                DOMElements.themeToggle,
                DOMElements.themeToggleOffcanvas
            ].forEach(toggle => {
                if (toggle) {
                    toggle.addEventListener('change', () => this.toggleTheme());
                }
            });
        },

        renderFaqButtons(faqData) {
            // Get both FAQ sections (desktop and mobile offcanvas)
            const faqSections = [
                document.querySelector('#faq-sidebar-section'),
                document.querySelector('#faq-offcanvas-section')
            ].filter(Boolean); // Remove any null elements
            
            if (faqSections.length === 0) return;

            // Create FAQ content once and clone it for each section
            const createFaqContent = () => {
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

                return fragment;
            };

            // Populate both FAQ sections
            faqSections.forEach((section, index) => {
                section.innerHTML = '';
                const faqContent = createFaqContent();
                section.appendChild(faqContent);
                section.querySelector('h4:first-of-type')?.classList.remove('mt-3');
            });
        },
    };

    /* 4. ANIMATION MODULE -------------------- */
    const Animations = {
        initCardAnimations() {
            const cards = document.querySelectorAll(`.${CONFIG.CSS_CLASSES.ANIMATE_CARD}`);

            const observer = new IntersectionObserver((entries, observer) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting && !entry.target.classList.contains(CONFIG.CSS_CLASSES.ANIMATED)) {
                        const delay = parseInt(entry.target.dataset.delay || '0', 10);
                        anime({
                            targets: entry.target,
                            translateY: [20, 0],
                            opacity: [0, 1],
                            duration: 800,
                            easing: 'easeOutQuad',
                            delay: delay,
                            complete: () => {
                                entry.target.classList.add(CONFIG.CSS_CLASSES.ANIMATED);
                                observer.unobserve(entry.target); // Stop observing once animated
                            }
                        });
                    }
                });
            }, { threshold: 0.1 }); // Trigger when 10% of the item is visible

            cards.forEach(card => {
                observer.observe(card);

                // Hover animations
                card.addEventListener('mouseenter', () => {
                    anime.remove(card); // Stop any current animation
                    anime({
                        targets: card,
                        scale: 1.03,
                        boxShadow: '0 8px 24px rgba(0,0,0,0.15)', // Enhanced shadow
                        duration: 200,
                        easing: 'easeOutQuad'
                    });
                });

                card.addEventListener('mouseleave', () => {
                    anime.remove(card); // Stop any current animation
                    anime({
                        targets: card,
                        scale: 1,
                        boxShadow: '0 4px 12px rgba(0,0,0,0.08)', // Revert to original shadow
                        duration: 200,
                        easing: 'easeOutQuad'
                    });
                });
            });
        }
    };

    /* 5. API & AUTH SERVICES -------------------- */
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
            // Check for testing mode
            const isTestingMode = window.location.search.includes('testing=true');
            if (isTestingMode) {
                return 'fake_token'; // Return fake token for testing
            }
            
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
            // Check for testing mode
            const isTestingMode = window.location.search.includes('testing=true');
            if (isTestingMode) {
                // In testing mode, just update the UI directly
                UI.updateAuthUI(null);
                UI.showToast('Logged out successfully (testing mode)');
                return;
            }

            if (!state.supabase) {
                UI.showToast('Authentication service not available', true);
                return;
            }

            try {
                const { error } = await state.supabase.auth.signOut();
                if (error) {
                    UI.showToast(`Logout failed: ${error.message}`, true);
                } else {
                    UI.showToast('Logged out successfully');
                }
                // onAuthStateChange will handle the UI update.
            } catch (error) {
                console.error('Logout error:', error);
                UI.showToast('Logout failed due to an unexpected error', true);
            }
        },

        async getProfile(userId) {
            const { data, error } = await state.supabase
                .from('profiles')
                .select(`*`)
                .eq('id', userId)
                .single();

            if (error && error.code !== 'PGRST116') { // Ignore 'PGRST116' (no rows found)
                console.error('Error fetching profile:', error);
                UI.showToast('Could not load your profile.', true);
                return null;
            }
            return data;
        },

        async updateProfile(userId, updates) {
            const { error } = await state.supabase
                .from('profiles')
                .update(updates)
                .eq('id', userId);
            
            if (error) {
                console.error('Error updating profile:', error);
                UI.displayProfileError(`Failed to save: ${error.message}`);
                return false;
            }
            return true;
        },
    };

    /* 6. EVENT HANDLERS -------------------- */
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
                UI.addMessage(data.response || `Error: ${data.error}`, 'bot', data.suggested_questions);
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
        },

        handleSuggestedQuestionClick(event) {
            const button = event.target.closest('.suggested-question-enhanced');
            if (!button || state.isRequestInProgress) return;

            console.log('Suggested question clicked:', button.textContent);
            DOMElements.queryInput.value = button.textContent;
            this.processQuery();

            // Optionally disable all suggested buttons after one is clicked
            document.querySelectorAll('.suggested-question-enhanced').forEach(btn => btn.disabled = true);
        },

        async handleProfileFormSubmit(event) {
            event.preventDefault();
            console.log('[1/5] Profile form submission started.');
            try {
                UI.clearProfileError();

                console.log('[2/5] Fetching user session...');
                const sessionResponse = await state.supabase.auth.getSession();
                console.log('[3/5] Session response received:', sessionResponse);

                const user = sessionResponse?.data?.session?.user;
                if (!user) {
                    console.error('User not found for profile update. Session might be invalid.');
                    return UI.displayProfileError('Your session seems to have expired. Please log out and log in again.');
                }
                console.log('[4/5] User identified:', user.id);

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

                console.log('[5/5] Attempting to save updates:', updates);
                const success = await Services.updateProfile(user.id, updates);

                if (success) {
                    state.userProfile = { ...state.userProfile, ...updates };
                    UI.setTheme(updates.preferences.theme);
                    UI.showToast('Profile saved successfully!');
                    state.profileModal?.hide();
                }
            } catch (error) {
                console.error('An unexpected error occurred in handleProfileFormSubmit:', error);
                UI.displayProfileError('A critical error occurred. Please check the console.');
            }
        },

        async handleProfileButtonClick() {
            UI.clearProfileError();
            const { data: { session } } = await state.supabase.auth.getSession();
            const user = session?.user;
            if (!user) return;
        
            if (state.userProfile) {
                UI.populateProfileForm(state.userProfile);
            } else {
                // If profile hasn't been fetched yet, get it now.
                const profile = await Services.getProfile(user.id);
                if (profile) {
                    state.userProfile = profile;
                    UI.populateProfileForm(profile);
                } else {
                    UI.displayProfileError('Could not load your profile data.');
                }
            }
        },

        handleLogout(event) {
            event.preventDefault();
            console.log('Logout initiated...');
            Services.logout();
        },
    };

    /* 7. EVENT BINDING -------------------- */
    function bindEventListeners() {
        // Prevent duplicate binding
        if (state.eventListenersBound) {
            console.log('Event listeners already bound, skipping...');
            return;
        }

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

        // Profile
        DOMElements.profileForm?.addEventListener('submit', (e) => Handlers.handleProfileFormSubmit(e));
        [DOMElements.profileButton, DOMElements.profileButtonOffcanvas].forEach(btn =>
            btn?.addEventListener('click', () => Handlers.handleProfileButtonClick())
        );

        // FAQ (Event Delegation) - Handle both desktop and mobile FAQ sections
        const faqSections = [
            document.querySelector('#faq-sidebar-section'),
            document.querySelector('#faq-offcanvas-section')
        ].filter(Boolean);
        
        faqSections.forEach(section => {
            section?.addEventListener('click', (e) => Handlers.handleFaqClick(e));
        });

        // Suggested Questions (Event Delegation)
        DOMElements.messagesContainer?.addEventListener('click', (e) => Handlers.handleSuggestedQuestionClick(e));

        // Shared controls
        [DOMElements.logoutButton, DOMElements.logoutButtonOffcanvas].forEach(btn => btn?.addEventListener('click', (e) => Handlers.handleLogout(e)));
        [DOMElements.authButton, DOMElements.authButtonOffcanvas, DOMElements.authButtonMain].forEach(btn => btn?.addEventListener('click', () => {
            state.authModal?.show();
        }));

        // Mark event listeners as bound
        state.eventListenersBound = true;
        console.log('Event listeners bound successfully');
    }

    /* 8. INITIALIZATION -------------------- */
    async function init() {
        UI.cacheDomElements();
        UI.initTheme();
        Animations.initCardAnimations(); // Initialize card animations

        // Check for testing mode
        const isTestingMode = window.location.search.includes('testing=true');
        if (isTestingMode) {
            console.log('Testing mode enabled - bypassing authentication');
            // Simulate authenticated user for testing
            UI.updateAuthUI({ email: 'test@example.com' });
            const faqData = await Services.getFaqData();
            if (faqData) {
                UI.renderFaqButtons(faqData);
            } else {
                const faqSections = [
                    document.querySelector('#faq-sidebar-section'),
                    document.querySelector('#faq-offcanvas-section')
                ].filter(Boolean);
                
                faqSections.forEach(section => {
                    section.innerHTML = '<div class="text-secondary small text-center py-3">No FAQs available.</div>';
                });
            }
            bindEventListeners();
            return;
        }

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

            const profileModalEl = document.getElementById('profileModal');
            if (profileModalEl) {
                state.profileModal = new bootstrap.Modal(profileModalEl);
            }

            if (DOMElements.sendButton) {
                state.originalSendButtonText = DOMElements.sendButton.textContent.trim() || 'Send';
            }
        } catch (error) {
            console.error("Initialization error:", error);
            return UI.showToast("Failed to initialize core application services.", true);
        }

        // Bind event listeners once
        bindEventListeners();

        // Central Authentication Handler
        state.supabase.auth.onAuthStateChange(async (_event, session) => {
            const user = session?.user;
            UI.updateAuthUI(user);

            if (user) {
                // User is logged in, initialize the authenticated experience
                const [faqData, profileData] = await Promise.all([
                    Services.getFaqData(),
                    Services.getProfile(user.id)
                ]);

                if (profileData) {
                   state.userProfile = profileData;
                   // Apply theme preference on login
                   UI.setTheme(profileData.preferences?.theme || 'light');
                }

                if (faqData) {
                    UI.renderFaqButtons(faqData);
                } else {
                    const faqSections = [
                        document.querySelector('#faq-sidebar-section'),
                        document.querySelector('#faq-offcanvas-section')
                    ].filter(Boolean);
                    
                    faqSections.forEach(section => {
                        section.innerHTML = '<div class="text-secondary small text-center py-3">No FAQs available.</div>';
                    });
                }
           } else {
               state.userProfile = null;
           }
            // If not logged in, the UI is already correctly set by updateAuthUI
        });
    }

    return { init };
})();

document.addEventListener('DOMContentLoaded', App.init);
