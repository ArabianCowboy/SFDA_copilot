// SFDA Copilot Main App Script
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';
import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.0/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.0.8/+esm';

// --- Date Formatting Fallback ---
// This attempts to use date-fns if available globally, otherwise falls back to toLocaleString.
// It polls because date-fns might be loaded asynchronously by a separate script tag.
let formatRelativeDate = (date) => date.toLocaleString();
(function initializeDateFormatter() {
    const checkDateFns = () => {
        if (window.dateFns && window.dateFns.formatRelative) {
            formatRelativeDate = window.dateFns.formatRelative;
        } else {
            // Poll every 100ms until date-fns is found or the page is closed.
            setTimeout(checkDateFns, 100);
        }
    };
    checkDateFns();
})();

document.addEventListener('DOMContentLoaded', () => {
    // --- Constants ---
    const SUPABASE_URL = window.SUPABASE_URL;
    const SUPABASE_ANON_KEY = window.SUPABASE_ANON_KEY;
    const TOAST_DURATION = 3000;
    const DEBOUNCE_DELAY = 300;

    // --- DOM Element Cache ---
    const DOM = {
        toastElem: document.getElementById('toast'),
        messagesContainer: document.getElementById('messages'),
        queryInput: document.getElementById('query-input'),
        sendButton: document.getElementById('send-button'),
        queryCategorySelect: document.getElementById('query-category'),
        faqButtons: document.querySelectorAll('.faq-button'),
        authModalElement: document.getElementById('authModal'),
        loginForm: document.getElementById('login-form'),
        signupForm: document.getElementById('signup-form'),
        logoutButton: document.getElementById('logout-button'),
        logoutButtonOffcanvas: document.getElementById('logout-button-offcanvas'),
        authButton: document.getElementById('auth-button'),
        authButtonOffcanvas: document.getElementById('auth-button-offcanvas'),
        userStatusSpan: document.getElementById('user-status'),
        userStatusSpanOffcanvas: document.getElementById('user-status-offcanvas'),
        authErrorDiv: document.getElementById('auth-error'),
        sidebarOffcanvasElement: document.getElementById('sidebarOffcanvas'),
        // Elements specific to sendButton UI updates
        sendButtonIcon: document.getElementById('send-button')?.querySelector('i'),
        // Assuming the text node is the last child. A more robust solution would be a dedicated span for text.
        sendButtonTextNode: document.getElementById('send-button')?.childNodes[document.getElementById('send-button')?.childNodes.length - 1],
    };

    // --- Bootstrap Component Instances ---
    const authModal = DOM.authModalElement ? new bootstrap.Modal(DOM.authModalElement) : null;
    const sidebarOffcanvas = DOM.sidebarOffcanvasElement ? new bootstrap.Offcanvas(DOM.sidebarOffcanvasElement) : null;

    // --- Supabase Client ---
    let supabase = null;
    if (SUPABASE_URL && SUPABASE_ANON_KEY) {
        try {
            supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
        } catch (error) {
            console.error("Error initializing Supabase client:", error);
            showToast("Error initializing authentication. Please refresh.");
            return; // Critical failure
        }
    } else {
        console.error("Supabase URL or Anon Key is missing.");
        showToast("Authentication configuration error. Please contact support.");
        return; // Critical failure
    }

    // --- State Variables ---
    let activeRequestController = null;
    let debounceTimer = null;
    const eventListeners = new Map();
    let originalSendButtonText = DOM.sendButtonTextNode?.textContent.trim() || 'Send';


    // --- Helper Functions ---
    function showToast(message, duration = TOAST_DURATION) {
        if (!DOM.toastElem) return;
        DOM.toastElem.textContent = message;
        DOM.toastElem.classList.remove('hidden');
        setTimeout(() => {
            DOM.toastElem.classList.add('hidden');
        }, duration);
    }

    function formatTimestamp(date) {
        return formatRelativeDate(date, new Date());
    }

    function scrollMessagesToBottom() {
        if (DOM.messagesContainer) {
            DOM.messagesContainer.scrollTop = DOM.messagesContainer.scrollHeight;
        }
    }

    // --- Event Listener Management ---
    function addTrackedEventListener(element, event, handler) {
        if (!element) return;
        element.addEventListener(event, handler);
        // Key generation could be improved for non-IDed elements if many similar ones exist
        eventListeners.set(`${event}-${element.id || element.tagName}-${Math.random()}`, { element, event, handler });
    }

    /**
     * Cleans up all tracked event listeners.
     * Call this function if the part of the DOM containing these elements is removed
     * or if the script needs to be re-initialized, to prevent memory leaks.
     * Currently not called as the script runs once on DOMContentLoaded for a persistent UI.
     */
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    function cleanupEventListeners() {
        eventListeners.forEach(({ element, event, handler }) => {
            element.removeEventListener(event, handler);
        });
        eventListeners.clear();
    }

    // --- UI Update Functions ---
    function updateAuthUI(user) {
        const isLoggedIn = !!user;
        const userEmail = user ? user.email : '';
        const statusText = isLoggedIn ? `Logged in as: ${userEmail}` : 'Not logged in';

        if (DOM.userStatusSpan) DOM.userStatusSpan.textContent = statusText;
        if (DOM.authButton) DOM.authButton.classList.toggle('d-none', isLoggedIn);
        if (DOM.logoutButton) DOM.logoutButton.classList.toggle('d-none', !isLoggedIn);

        if (DOM.userStatusSpanOffcanvas) DOM.userStatusSpanOffcanvas.textContent = statusText;
        if (DOM.authButtonOffcanvas) DOM.authButtonOffcanvas.classList.toggle('d-none', isLoggedIn);
        if (DOM.logoutButtonOffcanvas) DOM.logoutButtonOffcanvas.classList.toggle('d-none', !isLoggedIn);
    }

    function displayAuthError(message, isHtml = false) {
        if (!DOM.authErrorDiv) return;
        if (isHtml) {
            DOM.authErrorDiv.innerHTML = message;
        } else {
            DOM.authErrorDiv.textContent = message;
        }
        DOM.authErrorDiv.classList.remove('d-none');
    }

    function clearAuthError() {
        if (DOM.authErrorDiv) {
            DOM.authErrorDiv.textContent = '';
            DOM.authErrorDiv.classList.add('d-none');
            // Clear validation states from form inputs
            [DOM.loginForm, DOM.signupForm].forEach(form => {
                form?.querySelectorAll('.is-invalid').forEach(input => input.classList.remove('is-invalid'));
            });
        }
    }

    function setSendButtonState(isSending) {
        if (!DOM.sendButton || !DOM.queryInput || !DOM.sendButtonIcon || !DOM.sendButtonTextNode) return;

        DOM.queryInput.disabled = isSending;
        DOM.sendButton.disabled = isSending;

        if (isSending) {
            const spinner = document.createElement('span');
            spinner.className = 'spinner-border spinner-border-sm me-2';
            spinner.setAttribute('role', 'status');
            spinner.setAttribute('aria-hidden', 'true');
            spinner.id = 'send-spinner'; // ID to help replace it later

            DOM.sendButton.replaceChild(spinner, DOM.sendButtonIcon);
            DOM.sendButtonTextNode.textContent = ' Sending...';
        } else {
            const spinner = DOM.sendButton.querySelector('#send-spinner');
            if (spinner) {
                DOM.sendButton.replaceChild(DOM.sendButtonIcon, spinner);
            } else { // Fallback if spinner not found, e.g. error during replace
                DOM.sendButton.prepend(DOM.sendButtonIcon);
            }
            DOM.sendButtonTextNode.textContent = ` ${originalSendButtonText}`;
            activeRequestController = null;
        }
    }

    function showTypingIndicator() {
        if (!DOM.messagesContainer) return;
        requestAnimationFrame(() => {
            let skeletonDiv = document.getElementById('typing-indicator');
            if (!skeletonDiv) {
                skeletonDiv = document.createElement('div');
                skeletonDiv.id = 'typing-indicator';
                skeletonDiv.className = 'skeleton-message-container animated-message';
                skeletonDiv.innerHTML = `
                    <div class="skeleton skeleton-avatar"></div>
                    <div class="skeleton-content">
                        <div class="skeleton skeleton-line medium"></div>
                        <div class="skeleton skeleton-line"></div>
                        <div class="skeleton skeleton-line short"></div>
                    </div>`;
            }
            DOM.messagesContainer.appendChild(skeletonDiv); // Moves to end if already present
            scrollMessagesToBottom();
        });
    }

    function hideTypingIndicator() {
        const typingIndicator = document.getElementById('typing-indicator');
        if (typingIndicator) typingIndicator.remove();
    }


    // --- Authentication Functions ---
    async function getAuthToken() {
        try {
            const { data: { session }, error } = await supabase.auth.getSession();
            if (error) {
                console.error('Error getting session:', error);
                return null;
            }
            return session?.access_token ?? null;
        } catch (e) {
            console.error('Exception in getAuthToken:', e);
            return null;
        }
    }

    async function handleLogin(event) {
        event.preventDefault();
        clearAuthError();
        const emailInput = DOM.loginForm.querySelector('#login-email');
        const passwordInput = DOM.loginForm.querySelector('#login-password');
        const email = emailInput.value;
        const password = passwordInput.value;

        try {
            const { data, error } = await supabase.auth.signInWithPassword({ email, password });
            if (error) throw error;
            updateAuthUI(data.user);
            if (authModal) authModal.hide();
            DOM.loginForm.reset();
            showToast('Login successful!');
        } catch (error) {
            let errorMessage = error.message;
            if (error.message.includes('Invalid login credentials')) {
                errorMessage = 'Incorrect email or password. Please try again.';
            } else if (error.message.includes('Email not confirmed')) {
                errorMessage = 'Please confirm your email before logging in.';
            }
            displayAuthError(`
                <div class="d-flex align-items-center">
                    <i class="bi bi-exclamation-triangle-fill me-2"></i>
                    <strong>${errorMessage}</strong>
                </div>
            `, true);
            emailInput.classList.add('is-invalid');
            passwordInput.classList.add('is-invalid');
        }
    }

    async function handleSignup(event) {
        event.preventDefault();
        clearAuthError();
        const email = DOM.signupForm.querySelector('#signup-email').value;
        const password = DOM.signupForm.querySelector('#signup-password').value;

        try {
            const { data, error } = await supabase.auth.signUp({ email, password });
            if (error) throw error;
            // User might be null if email confirmation is required.
            // Supabase onAuthStateChange will handle UI update once confirmed/logged in.
            // For immediate feedback, we can check data.user
            if (data.user) {
                 updateAuthUI(data.user);
                 showToast('Signup successful! Please check your email for a confirmation link.');
            } else {
                 // This case handles when session is null but user object exists (e.g. email confirmation pending)
                 showToast('Signup initiated! Please check your email for a confirmation link.');
            }
            if (authModal) authModal.hide();
            DOM.signupForm.reset();
        } catch (error) {
            displayAuthError(error.message || 'An unknown error occurred during signup.');
        }
    }

    async function handleLogout() {
        clearAuthError();
        try {
            const { error } = await supabase.auth.signOut();
            if (error) throw error;
            updateAuthUI(null); // updateAuthUI will be called by onAuthStateChange too
            showToast('Logout successful!');
        } catch (error) {
            showToast(`Logout failed: ${error.message}`);
        }
    }

    async function initializeUserSession() {
        try {
            const { data: { session }, error } = await supabase.auth.getSession();
            if (error) throw error;
            updateAuthUI(session?.user ?? null);
        } catch (error) {
            console.error('Error checking initial user session:', error);
            updateAuthUI(null);
            // showToast('Error checking login status. Please refresh.'); // Potentially too noisy
        }

        supabase.auth.onAuthStateChange((_event, session) => {
            updateAuthUI(session?.user ?? null);
        });
    }


    // --- Chat Functions ---
    function addMessage(text, sender) {
        if (!DOM.messagesContainer) return;

        requestAnimationFrame(() => {
            const fragment = document.createDocumentFragment();
            const messageDiv = document.createElement('div');
            const textSizeClass = text.length < 100 ? 'message-small' : text.length > 300 ? 'message-large' : 'message-medium';
            messageDiv.className = `message ${sender === 'user' ? 'user-message' : 'chatbot-message'} animated-message mb-3 ${textSizeClass}`;

            const bubbleDiv = document.createElement('div');
            bubbleDiv.className = 'message-bubble';
            bubbleDiv.style.viewTransitionName = `message-bubble-${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;

            if (sender === 'bot') {
                const avatarDiv = document.createElement('div');
                avatarDiv.className = 'avatar mb-2';
                avatarDiv.innerHTML = `<img src="/static/images/bot.jpg" alt="Bot Avatar" class="rounded-circle" loading="lazy">`;
                bubbleDiv.appendChild(avatarDiv);
            }

            const contentDiv = document.createElement('div');
            contentDiv.className = 'message-content';
            if (sender === 'bot') {
                const rawHtml = marked.parse(text);
                contentDiv.innerHTML = DOMPurify.sanitize(rawHtml, { USE_PROFILES: { html: true } });
                contentDiv.querySelectorAll('ul, ol').forEach(list => list.classList.add('message-list'));
                contentDiv.querySelectorAll('pre code').forEach(codeBlock => { // Target pre > code for blocks
                    const parentPre = codeBlock.parentElement;
                    if (parentPre && parentPre.tagName === 'PRE') {
                        parentPre.classList.add('message-code-block');
                        // Optional: Add copy button or other enhancements here
                    }
                });
                 contentDiv.querySelectorAll('p code, li code').forEach(inlineCode => { // Target inline code
                    inlineCode.classList.add('message-inline-code');
                });
            } else {
                contentDiv.textContent = text;
            }
            bubbleDiv.appendChild(contentDiv);

            const timestampDiv = document.createElement('div');
            timestampDiv.className = 'timestamp';
            timestampDiv.textContent = formatTimestamp(new Date());
            bubbleDiv.appendChild(timestampDiv);

            messageDiv.appendChild(bubbleDiv);
            fragment.appendChild(messageDiv);

            if (document.startViewTransition) {
                document.startViewTransition(() => {
                    DOM.messagesContainer.appendChild(fragment);
                    scrollMessagesToBottom();
                });
            } else {
                DOM.messagesContainer.appendChild(fragment);
                scrollMessagesToBottom();
            }
        });
    }

    async function processSendQuery() {
        if (activeRequestController) { // Abort previous request if a new one is fired quickly
            activeRequestController.abort();
        }

        const query = DOM.queryInput.value.trim();
        const category = DOM.queryCategorySelect.value;

        if (!query) {
            showToast('Please enter a question.');
            return;
        }

        const token = await getAuthToken();
        if (!token) {
            showToast('You must be logged in to chat. Please log in or sign up.');
            if (authModal) authModal.show();
            return;
        }

        addMessage(query, 'user');
        DOM.queryInput.value = '';
        showTypingIndicator();
        setSendButtonState(true);

        activeRequestController = new AbortController();

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                signal: activeRequestController.signal,
                body: JSON.stringify({ query, category })
            });

            if (!response.ok) {
                let errorMsg = `Network response was not ok (${response.status})`;
                try {
                    const errorData = await response.json();
                    errorMsg = errorData.error || errorData.message || errorMsg;
                } catch (e) { /* Ignore if response is not JSON */ }
                throw new Error(errorMsg);
            }

            const data = await response.json();
            hideTypingIndicator();
            if (data.response) {
                addMessage(data.response, 'bot');
            } else if (data.error) {
                showToast(`Error from API: ${data.error}`);
                addMessage(`Sorry, I encountered an error: ${data.error}`, 'bot');
            } else {
                 addMessage("Sorry, I received an empty response from the server.", 'bot');
            }

        } catch (error) {
            hideTypingIndicator();
            if (error.name !== 'AbortError') {
                console.error('Error sending query:', error);
                showToast(error.message || 'Error: Could not get response');
                addMessage(`Sorry, I couldn't connect to the server. Error: ${error.message}`, 'bot');
            }
        } finally {
            setSendButtonState(false);
        }
    }

    function debouncedSendQuery() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(processSendQuery, DEBOUNCE_DELAY);
    }


    // --- Event Listener Setup ---
    if (DOM.sendButton) addTrackedEventListener(DOM.sendButton, 'click', debouncedSendQuery);
    if (DOM.queryInput) addTrackedEventListener(DOM.queryInput, 'keypress', e => { if (e.key === 'Enter') debouncedSendQuery(); });

    DOM.faqButtons.forEach(button => {
        addTrackedEventListener(button, 'click', function () { // Use function for `this`
            DOM.queryInput.value = this.getAttribute('data-question');
            const category = this.getAttribute('data-category');
            if (category && DOM.queryCategorySelect) DOM.queryCategorySelect.value = category;
            if (sidebarOffcanvas && this.closest('#sidebarOffcanvas')) {
                sidebarOffcanvas.hide();
            }
            processSendQuery(); // Send immediately, no debounce for FAQ
        });
    });

    if (DOM.authButton) addTrackedEventListener(DOM.authButton, 'click', () => { if (authModal) authModal.show(); });
    if (DOM.authButtonOffcanvas) addTrackedEventListener(DOM.authButtonOffcanvas, 'click', () => { if (authModal) authModal.show(); });
    if (DOM.logoutButton) addTrackedEventListener(DOM.logoutButton, 'click', handleLogout);
    if (DOM.logoutButtonOffcanvas) addTrackedEventListener(DOM.logoutButtonOffcanvas, 'click', handleLogout);

    if (DOM.loginForm) addTrackedEventListener(DOM.loginForm, 'submit', handleLogin);
    if (DOM.signupForm) addTrackedEventListener(DOM.signupForm, 'submit', handleSignup);


    // --- Initializations ---
    if (supabase) {
        initializeUserSession();
        originalSendButtonText = DOM.sendButtonTextNode?.textContent.trim() || 'Send'; // Ensure it's set after DOM ready
    } else {
        // Handle UI for non-functional Supabase (e.g., disable chat)
        if (DOM.queryInput) DOM.queryInput.disabled = true;
        if (DOM.sendButton) DOM.sendButton.disabled = true;
        if (DOM.queryInput) DOM.queryInput.placeholder = "Chat unavailable due to configuration error.";
    }
});