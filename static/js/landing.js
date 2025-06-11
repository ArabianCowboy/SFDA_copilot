import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';

// --- Constants ---
const SUPABASE_URL = window.SUPABASE_URL;
const SUPABASE_ANON_KEY = window.SUPABASE_ANON_KEY;
const AUTH_COOKIE_NAME = 'sb-access-token';
const AUTH_COOKIE_MAX_AGE_SECONDS = 3600; // 1 hour
const TOAST_VISIBILITY_DURATION_MS = 3000;

// --- Supabase Client Initialization ---
let supabase;
try {
    if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
        throw new Error('Supabase URL or Anonymous Key is not configured.');
    }
    supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
} catch (error) {
    console.error('Failed to initialize Supabase client:', error.message);
    // Optionally, display a persistent error to the user if Supabase is critical
    // document.body.innerHTML = '<p>Application configuration error. Please contact support.</p>';
}

// --- Authentication Utilities ---
async function getSupabaseAuthToken() {
    if (!supabase) return null;
    try {
        const { data: { session }, error } = await supabase.auth.getSession();
        if (error) throw error;
        return session?.access_token ?? null;
    } catch (error) {
        console.error('Error getting Supabase auth token:', error.message);
        return null;
    }
}

function setAuthCookie(token) {
    if (!token) return;
    document.cookie = `${AUTH_COOKIE_NAME}=${token}; path=/; max-age=${AUTH_COOKIE_MAX_AGE_SECONDS}; SameSite=Lax; Secure`; // Added Secure attribute
}

function clearAuthCookie() {
    document.cookie = `${AUTH_COOKIE_NAME}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax; Secure`; // Added Secure attribute
}

// --- API Request Handler ---
/**
 * Makes an authenticated API request.
 * @param {string} url - The URL to request.
 * @param {object} options - Fetch options (method, body, etc.).
 * @param {object} [DOMCache.toastElement] - Optional toast element for displaying messages.
 * @returns {Promise<object|null>} - The JSON response or null on failure.
 */
async function makeAuthenticatedRequest(url, options = {}, toastElement = null) {
    if (!supabase) {
        if (toastElement) showToastNotification(toastElement, 'Core services unavailable. Please try again later.', 'error');
        return null;
    }

    const token = await getSupabaseAuthToken();
    if (!token) {
        if (toastElement) showToastNotification(toastElement, 'Please login to access this feature.', 'error');
        // Consider redirecting to login or showing auth modal here if appropriate
        return null;
    }

    const fetchOptions = {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
            ...(options.headers || {}),
        },
    };

    try {
        const response = await fetch(url, fetchOptions);

        if (response.status === 401) { // Unauthorized - session likely expired
            if (toastElement) showToastNotification(toastElement, 'Session expired. Please login again.', 'error');
            await supabase.auth.signOut(); // This should trigger onAuthStateChange if listeneing elsewhere
            clearAuthCookie(); // Explicitly clear cookie as part of this flow
            window.location.reload(); // Reload to reflect logged-out state
            return null;
        }

        if (!response.ok) {
            let errorData;
            try {
                errorData = await response.json();
            } catch (jsonError) {
                // If response is not JSON, use status text
                throw new Error(response.statusText || `Request failed with status ${response.status}`);
            }
            throw new Error(errorData.message || `Request failed with status ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        console.error('API request error:', error.message);
        if (toastElement) showToastNotification(toastElement, error.message || 'An unexpected error occurred.', 'error');
        return null;
    }
}

// --- DOMContentLoaded: UI Interactions and Event Listeners ---
document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Element Cache ---
    const DOM = {
        authModalElement: document.getElementById('authModal'),
        loginForm: document.getElementById('login-form'),
        signupForm: document.getElementById('signup-form'),
        authButton: document.getElementById('auth-button-main'), // Renamed for clarity if it's the main trigger
        logoutButton: document.getElementById('logout-button-main'),
        toastElement: document.getElementById('toast'),
        authErrorFeedback: document.getElementById('auth-error'), // Element to display auth form errors
        loginEmailInput: document.getElementById('login-email'),
        loginPasswordInput: document.getElementById('login-password'),
        signupEmailInput: document.getElementById('signup-email'),
        signupPasswordInput: document.getElementById('signup-password'),
    };

    // --- Bootstrap Component Instances ---
    const authModalInstance = DOM.authModalElement ? new bootstrap.Modal(DOM.authModalElement) : null;

    // --- UI Helper Functions (DOM-dependent) ---
    function showToastNotification(toastEl, message, type = 'success') { // type can be 'success' or 'error'
        if (!toastEl) return;
        toastEl.textContent = message;
        toastEl.className = 'toast-notification'; // Reset to base class
        toastEl.classList.add(type); // Add type-specific class ('success' or 'error')
        toastEl.classList.remove('hidden');

        setTimeout(() => {
            toastEl.classList.add('hidden');
        }, TOAST_VISIBILITY_DURATION_MS);
    }

    function clearAuthFormError() {
        if (DOM.authErrorFeedback) {
            DOM.authErrorFeedback.classList.add('d-none');
            DOM.authErrorFeedback.innerHTML = ''; // Clear previous error content
        }
        // Remove 'is-invalid' from all relevant form inputs
        [DOM.loginEmailInput, DOM.loginPasswordInput, DOM.signupEmailInput, DOM.signupPasswordInput].forEach(input => {
            input?.classList.remove('is-invalid');
        });
    }

    function displayAuthFormError(message, fieldIdsToMarkInvalid = []) {
        if (DOM.authErrorFeedback) {
            // Using textContent for the main message for security, then constructing HTML for icon
            const strongMessage = document.createElement('strong');
            strongMessage.textContent = message;

            const icon = document.createElement('i');
            icon.className = 'bi bi-exclamation-triangle-fill me-2';

            const container = document.createElement('div');
            container.className = 'd-flex align-items-center';
            container.appendChild(icon);
            container.appendChild(strongMessage);

            DOM.authErrorFeedback.innerHTML = ''; // Clear previous content
            DOM.authErrorFeedback.appendChild(container);
            DOM.authErrorFeedback.classList.remove('d-none');
        }
        fieldIdsToMarkInvalid.forEach(id => {
            const field = document.getElementById(id);
            field?.classList.add('is-invalid');
        });
    }

    // --- Authentication Event Handlers ---
    async function handleLogin(event) {
        event.preventDefault();
        if (!supabase || !DOM.loginEmailInput || !DOM.loginPasswordInput) return;
        clearAuthFormError();

        const email = DOM.loginEmailInput.value;
        const password = DOM.loginPasswordInput.value;

        try {
            const { data, error } = await supabase.auth.signInWithPassword({ email, password });
            if (error) throw error;

            if (data.session?.access_token) {
                setAuthCookie(data.session.access_token);
            }
            authModalInstance?.hide();
            window.location.href = '/chat'; // Redirect to chat page
        } catch (error) {
            let errorMessage = error.message;
            const invalidFields = [];
            if (error.message.includes('Invalid login credentials')) {
                errorMessage = 'Incorrect email or password. Please try again.';
                invalidFields.push('login-email', 'login-password');
            } else if (error.message.includes('Email not confirmed')) {
                errorMessage = 'Please confirm your email before logging in.';
                invalidFields.push('login-email');
            } else {
                invalidFields.push('login-email', 'login-password');
            }
            displayAuthFormError(errorMessage, invalidFields);
        }
    }

    async function handleSignup(event) {
        event.preventDefault();
        if (!supabase || !DOM.signupEmailInput || !DOM.signupPasswordInput) return;
        clearAuthFormError();

        const email = DOM.signupEmailInput.value;
        const password = DOM.signupPasswordInput.value;

        try {
            // Supabase sends a confirmation email by default if enabled in project settings.
            // The session might be null immediately after signup if confirmation is required.
            const { data, error } = await supabase.auth.signUp({ email, password });
            if (error) throw error;

            // Session and token might be available if auto-confirm is on or for the first login after confirm.
            if (data.session?.access_token) {
                setAuthCookie(data.session.access_token);
            }
            authModalInstance?.hide();

            // Redirect or show success message
            // If email confirmation is required, user won't be logged in yet.
            // A message prompting to check email is usually better than immediate redirect to /chat here.
            if (data.user && !data.session) { // User created, but no session (likely email confirmation pending)
                showToastNotification(DOM.toastElement, 'Signup successful! Please check your email to confirm your account.', 'success');
            } else { // User created and session active (e.g. auto-confirm on, or already confirmed)
                 window.location.href = '/chat';
            }

        } catch (error) {
            displayAuthFormError(error.message, ['signup-email', 'signup-password']);
        }
    }

    async function handleLogout() {
        if (!supabase) return;
        try {
            const { error } = await supabase.auth.signOut();
            if (error) throw error;
            clearAuthCookie();
            window.location.reload(); // Reload to reflect logged-out state
        } catch (error) {
            showToastNotification(DOM.toastElement, `Logout failed: ${error.message}`, 'error');
        }
    }

    // --- Attach Event Listeners ---
    if (!supabase) {
        // If Supabase failed to initialize, disable auth-related UI or show error
        DOM.loginForm?.classList.add('disabled-form');
        DOM.signupForm?.classList.add('disabled-form');
        DOM.authButton?.setAttribute('disabled', 'true');
        DOM.logoutButton?.setAttribute('disabled', 'true');
        console.warn("Authentication features are disabled due to Supabase initialization failure.");
        if (DOM.authButton) {
            DOM.authButton.title = "Authentication service unavailable";
        }
        if (DOM.logoutButton) {
            DOM.logoutButton.title = "Authentication service unavailable";
        }
        // Optionally display a message in the auth modal area
        return; // Stop further auth-related event listener setup
    }

    DOM.loginForm?.addEventListener('submit', handleLogin);
    DOM.signupForm?.addEventListener('submit', handleSignup);
    DOM.authButton?.addEventListener('click', () => authModalInstance?.show());
    DOM.logoutButton?.addEventListener('click', handleLogout);

    // Example of using makeAuthenticatedRequest if needed (not in original snippet's DOM events)
    // async function fetchSomeUserData() {
    //     const userData = await makeAuthenticatedRequest('/api/user-data', { method: 'GET' }, DOM.toastElement);
    //     if (userData) {
    //         console.log('User data:', userData);
    //     }
    // }
    // document.getElementById('fetch-user-data-button')?.addEventListener('click', fetchSomeUserData);
});