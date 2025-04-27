// SFDA Copilot Main App Script (Optimized)
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';
import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.0/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.0.8/+esm';

// Date formatting fallback
let formatRelative = (date) => date.toLocaleString();
(function checkDateFns() {
    if (window.dateFns && window.dateFns.formatRelative) {
        formatRelative = window.dateFns.formatRelative;
    } else {
        setTimeout(checkDateFns, 100);
    }
})();

document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Elements ---
    const toastElem = document.getElementById('toast');
    const messagesContainer = document.getElementById('messages');
    const queryInput = document.getElementById('query-input');
    const sendButton = document.getElementById('send-button');
    const queryCategorySelect = document.getElementById('query-category');
    const faqButtons = document.querySelectorAll('.faq-button');
    const authModalElement = document.getElementById('authModal');
    const authModal = authModalElement ? new bootstrap.Modal(authModalElement) : null;
    const loginForm = document.getElementById('login-form');
    const signupForm = document.getElementById('signup-form');
    const logoutButton = document.getElementById('logout-button');
    const logoutButtonOffcanvas = document.getElementById('logout-button-offcanvas');
    const authButton = document.getElementById('auth-button');
    const authButtonOffcanvas = document.getElementById('auth-button-offcanvas');
    const userStatusSpan = document.getElementById('user-status');
    const userStatusSpanOffcanvas = document.getElementById('user-status-offcanvas');
    const authErrorDiv = document.getElementById('auth-error');
    const sidebarOffcanvasElement = document.getElementById('sidebarOffcanvas');
    const sidebarOffcanvas = sidebarOffcanvasElement ? new bootstrap.Offcanvas(sidebarOffcanvasElement) : null;

    // --- Supabase Setup ---
    const SUPABASE_URL = window.SUPABASE_URL;
    const SUPABASE_ANON_KEY = window.SUPABASE_ANON_KEY;
    let supabase = null;
    if (SUPABASE_URL && SUPABASE_ANON_KEY) {
        try {
            supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
        } catch (error) {
            showToast("Error initializing authentication. Please refresh.");
            return;
        }
    } else {
        showToast("Authentication configuration error. Please contact support.");
        return;
    }

    // --- Event Listeners ---
    let activeRequest = null;
    let debounceTimer = null;
    const eventListeners = new Map();

    function addEventListenerTracked(element, event, handler) {
        if (!element) return;
        element.addEventListener(event, handler);
        eventListeners.set(`${event}-${element.id || element.tagName}`, { element, event, handler });
    }

    function cleanupEventListeners() {
        eventListeners.forEach(({ element, event, handler }) => {
            element.removeEventListener(event, handler);
        });
        eventListeners.clear();
    }

    // Debounced send handler
    function debouncedSend() {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            if (activeRequest) {
                activeRequest.abort();
                activeRequest = null;
            }
            sendQuery();
        }, 300);
    }

    addEventListenerTracked(sendButton, 'click', debouncedSend);
    addEventListenerTracked(queryInput, 'keypress', e => { if (e.key === 'Enter') debouncedSend(); });

    // FAQ Buttons
    faqButtons.forEach(button => {
        addEventListenerTracked(button, 'click', function () {
            queryInput.value = this.getAttribute('data-question');
            const category = this.getAttribute('data-category');
            if (category) queryCategorySelect.value = category;
            if (sidebarOffcanvas && this.closest('#sidebarOffcanvas')) sidebarOffcanvas.hide();
            sendQuery();
        });
    });

    // Auth Modal Buttons
    addEventListenerTracked(authButton, 'click', () => { if (authModal) authModal.show(); });
    addEventListenerTracked(authButtonOffcanvas, 'click', () => { if (authModal) authModal.show(); });
    addEventListenerTracked(logoutButton, 'click', handleLogout);
    addEventListenerTracked(logoutButtonOffcanvas, 'click', handleLogout);

    // Auth Forms
    if (loginForm) loginForm.addEventListener('submit', handleLogin);
    if (signupForm) signupForm.addEventListener('submit', handleSignup);

    // --- Auth Functions ---
    async function handleLogin(event) {
        event.preventDefault();
        clearAuthError();
        const email = document.getElementById('login-email').value;
        const password = document.getElementById('login-password').value;
        try {
            const { data, error } = await supabase.auth.signInWithPassword({ email, password });
            if (error) throw error;
            updateAuthStatus(data.user);
            authModal.hide();
            loginForm.reset();
            showToast('Login successful!');
        } catch (error) {
            let errorMessage = error.message;
            if (error.message.includes('Invalid login credentials')) {
                errorMessage = 'Incorrect email or password. Please try again.';
            } else if (error.message.includes('Email not confirmed')) {
                errorMessage = 'Please confirm your email before logging in.';
            }
            authErrorDiv.innerHTML = `
                <div class="d-flex align-items-center">
                    <i class="bi bi-exclamation-triangle-fill me-2"></i>
                    <strong>${errorMessage}</strong>
                </div>
            `;
            authErrorDiv.classList.remove('d-none');
            document.getElementById('login-email').classList.add('is-invalid');
            document.getElementById('login-password').classList.add('is-invalid');
        }
    }

    async function handleSignup(event) {
        event.preventDefault();
        clearAuthError();
        const email = document.getElementById('signup-email').value;
        const password = document.getElementById('signup-password').value;
        try {
            const { data, error } = await supabase.auth.signUp({ email, password });
            if (error) throw error;
            updateAuthStatus(data.user);
            authModal.hide();
            signupForm.reset();
            showToast('Signup successful! Check your email for confirmation if required.');
        } catch (error) {
            displayAuthError(error.message);
        }
    }

    async function handleLogout() {
        clearAuthError();
        try {
            const { error } = await supabase.auth.signOut();
            if (error) throw error;
            updateAuthStatus(null);
            showToast('Logout successful!');
        } catch (error) {
            showToast(`Logout failed: ${error.message}`);
        }
    }

    async function checkUserSession() {
        try {
            const { data: { session }, error } = await supabase.auth.getSession();
            if (error) throw error;
            updateAuthStatus(session?.user ?? null);
        } catch (error) {
            updateAuthStatus(null);
            showToast('Error checking login status. Please refresh.');
        }
        supabase.auth.onAuthStateChange((_event, session) => {
            updateAuthStatus(session?.user ?? null);
        });
    }

    function updateAuthStatus(user) {
        const loggedIn = !!user;
        const userEmail = user ? user.email : '';
        const statusText = loggedIn ? `Logged in as: ${userEmail}` : 'Not logged in';
        if (userStatusSpan) userStatusSpan.textContent = statusText;
        if (authButton) authButton.classList.toggle('d-none', loggedIn);
        if (logoutButton) logoutButton.classList.toggle('d-none', !loggedIn);
        if (userStatusSpanOffcanvas) userStatusSpanOffcanvas.textContent = statusText;
        if (authButtonOffcanvas) authButtonOffcanvas.classList.toggle('d-none', loggedIn);
        if (logoutButtonOffcanvas) logoutButtonOffcanvas.classList.toggle('d-none', !loggedIn);
    }

    function displayAuthError(message) { authErrorDiv.textContent = message; }
    function clearAuthError() { authErrorDiv.textContent = ''; }

    async function getAuthToken() {
        try {
            const { data: { session }, error } = await supabase.auth.getSession();
            if (error) return null;
            return session?.access_token ?? null;
        } catch {
            return null;
        }
    }

    // --- Chat Functions ---
    async function sendQuery() {
        const query = queryInput.value.trim();
        const category = queryCategorySelect.value;
        if (!query) { showToast('Please enter a question'); return; }
        addMessage(query, 'user');
        queryInput.value = '';
        // Ensure skeleton is shown after user message is rendered
        requestAnimationFrame(() => {
            showTypingIndicator();
        });

        // Input area feedback
        const sendButtonIcon = sendButton.querySelector('i');
        const sendButtonText = sendButton.childNodes[sendButton.childNodes.length - 1];
        const originalButtonText = sendButtonText.textContent.trim();
        const spinner = document.createElement('span');
        spinner.className = 'spinner-border spinner-border-sm me-2';
        spinner.setAttribute('role', 'status');
        spinner.setAttribute('aria-hidden', 'true');
        queryInput.disabled = true;
        sendButton.disabled = true;
        sendButton.replaceChild(spinner, sendButtonIcon);
        sendButtonText.textContent = ' Sending...';

        const token = await getAuthToken();
        const controller = new AbortController();
        activeRequest = controller;

        const restoreInputArea = () => {
            queryInput.disabled = false;
            sendButton.disabled = false;
            sendButton.replaceChild(sendButtonIcon, spinner);
            sendButtonText.textContent = ` ${originalButtonText}`;
            activeRequest = null;
        };

        if (!token) {
            hideTypingIndicator();
            restoreInputArea();
            showToast('You must be logged in to chat.');
            return;
        }

        fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            signal: controller.signal,
            body: JSON.stringify({ query, category })
        })
        .then(async response => {
            if (!response.ok) {
                let errorMsg = `Network response was not ok (${response.status})`;
                try {
                    const errorData = await response.json();
                    errorMsg = errorData.error || errorMsg;
                } catch (e) {}
                throw new Error(errorMsg);
            }
            return response.json();
        })
        .then(data => {
            hideTypingIndicator();
            if (data.response) {
                addMessage(data.response, 'bot');
            } else if (data.error) {
                showToast(`Error: ${data.error}`);
            }
        })
        .catch(error => {
            if (error.name !== 'AbortError') {
                hideTypingIndicator();
                showToast(error.message || 'Error: Could not get response');
            }
        })
        .finally(() => {
            restoreInputArea();
        });
    }

    function addMessage(text, sender) {
        requestAnimationFrame(() => {
            const fragment = document.createDocumentFragment();
            const messageDiv = document.createElement('div');
            let sizeClass = 'message-medium';
            if (text.length < 100) sizeClass = 'message-small';
            else if (text.length > 300) sizeClass = 'message-large';
            messageDiv.className = `message ${sender === 'user' ? 'user-message' : 'chatbot-message'} animated-message mb-3 ${sizeClass}`;
            const bubbleDiv = document.createElement('div');
            bubbleDiv.className = 'message-bubble';

            if (sender === 'bot') {
                const avatarDiv = document.createElement('div');
                avatarDiv.className = 'avatar mb-2';
                const img = document.createElement('img');
                img.src = '/static/images/bot.jpg';
                img.alt = 'bot avatar';
                img.className = 'rounded-circle';
                img.loading = 'lazy';
                avatarDiv.appendChild(img);
                bubbleDiv.appendChild(avatarDiv);
            }

            const contentDiv = document.createElement('div');
            contentDiv.className = 'message-content';

            if (sender === 'bot') {
                const rawHtml = marked.parse(text);
                contentDiv.innerHTML = DOMPurify.sanitize(rawHtml);
                const lists = contentDiv.querySelectorAll('ul');
                lists.forEach(list => list.className = 'message-list');
                const codeBlocks = contentDiv.querySelectorAll('code');
                codeBlocks.forEach(code => {
                    const codeWrapper = document.createElement('div');
                    codeWrapper.className = 'message-code';
                    code.parentNode.insertBefore(codeWrapper, code);
                    codeWrapper.appendChild(code);
                });
            } else {
                contentDiv.textContent = text;
            }

            bubbleDiv.appendChild(contentDiv);

            const timestamp = document.createElement('div');
            timestamp.className = 'timestamp';
            timestamp.textContent = formatRelativeTime(new Date());
            bubbleDiv.appendChild(timestamp);

            messageDiv.appendChild(bubbleDiv);
            fragment.appendChild(messageDiv);

            if (document.startViewTransition) {
                document.startViewTransition(() => {
                    messagesContainer.appendChild(fragment);
                    scrollMessagesToBottom();
                });
            } else {
                messagesContainer.appendChild(fragment);
                scrollMessagesToBottom();
            }
        });
    }

    function showTypingIndicator() {
        requestAnimationFrame(() => {
            let skeletonDiv = document.getElementById('typing-indicator');
            if (!skeletonDiv) {
                skeletonDiv = document.createElement('div');
                skeletonDiv.id = 'typing-indicator';
                skeletonDiv.className = 'skeleton-message-container animated-message';
                const avatarSkeleton = document.createElement('div');
                avatarSkeleton.className = 'skeleton skeleton-avatar';
                skeletonDiv.appendChild(avatarSkeleton);
                const contentSkeleton = document.createElement('div');
                contentSkeleton.className = 'skeleton-content';
                const line1 = document.createElement('div');
                line1.className = 'skeleton skeleton-line medium';
                contentSkeleton.appendChild(line1);
                const line2 = document.createElement('div');
                line2.className = 'skeleton skeleton-line';
                contentSkeleton.appendChild(line2);
                const line3 = document.createElement('div');
                line3.className = 'skeleton skeleton-line short';
                contentSkeleton.appendChild(line3);
                skeletonDiv.appendChild(contentSkeleton);
            }
            // Always append (moves to end if already present)
            messagesContainer.appendChild(skeletonDiv);
            scrollMessagesToBottom();
        });
    }

    function hideTypingIndicator() {
        const typingIndicator = document.getElementById('typing-indicator');
        if (typingIndicator) typingIndicator.remove();
    }

    function scrollMessagesToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function formatRelativeTime(timestamp) {
        const now = new Date();
        const messageDate = new Date(timestamp);
        return formatRelative(messageDate, now);
    }

    function showToast(message, duration = 3000) {
        toastElem.textContent = message;
        toastElem.classList.remove('hidden');
        setTimeout(() => {
            toastElem.classList.add('hidden');
        }, duration);
    }

    // Initialize user session on load
    checkUserSession();
});
