/**
 * @file Main application script for the SFDA Copilot frontend.
 * @description This script handles Supabase initialization, user authentication,
 * API requests, and all UI interactions. It is structured as a modular application
 * within an IIFE to ensure encapsulation, robustness, and maintainability.
 * This version combines a clean modular architecture with defensive programming practices.
 */

import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm';

/**
 * Main application module, created using an IIFE (Immediately Invoked Function Expression)
 * to encapsulate all logic and avoid polluting the global scope.
 * @module App
 */
const App = (function () {

    // --- Private State and Configuration ---

    /**
     * Application-wide configuration constants.
     * @private
     */
    const config = {
        SUPABASE_URL: window.SUPABASE_URL,
        SUPABASE_ANON_KEY: window.SUPABASE_ANON_KEY,
        AUTH_COOKIE_NAME: 'sb-access-token',
        AUTH_COOKIE_MAX_AGE_SECONDS: 3600, // 1 hour
        TOAST_VISIBILITY_DURATION_MS: 3000,
    };

    /**
     * Cached DOM elements for efficient access. Populated by _cacheDomElements().
     * @private
     */
    const dom = {};

    /**
     * Runtime state of the application.
     * @private
     */
    const state = {
        supabase: null,
        authModalInstance: null,
    };

    // --- Private Helper Functions ---

    /**
     * Formats a raw authentication error from Supabase into a user-friendly message.
     * @private
     * @param {Error} error - The error object from Supabase.
     * @returns {string} A user-friendly error message.
     */
    function _formatAuthError(error) {
        const message = error.message.toLowerCase();
        if (message.includes('invalid login credentials')) {
            return 'Incorrect email or password. Please try again.';
        }
        if (message.includes('email not confirmed')) {
            return 'Please confirm your email before logging in.';
        }
        if (message.includes('to be a valid email')) {
            return 'Please provide a valid email address.';
        }
        return error.message || 'An unknown error occurred.';
    }

    /**
     * Validates that a list of DOM elements exists.
     * @private
     * @param {HTMLElement[]} elements - An array of DOM elements to check.
     * @returns {boolean} True if all elements exist, false otherwise.
     */
    function _validateDomElements(elements) {
        return elements.every(el => el !== null && el !== undefined);
    }

    // --- Theme Management ---
    /**
     * Initializes the theme based on local storage or system preference.
     * @private
     */
    function _initTheme() {
        const storedTheme = localStorage.getItem('theme');
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const defaultTheme = storedTheme || (prefersDark ? 'dark' : 'light');
        _setTheme(defaultTheme);
    }

    /**
     * Sets the theme attribute on the HTML element and saves to local storage.
     * @private
     * @param {'light'|'dark'} theme - The theme to set.
     */
    function _setTheme(theme) {
        if (theme === 'dark') {
            document.documentElement.setAttribute('data-bs-theme', 'dark');
            localStorage.setItem('theme', 'dark');
        } else {
            document.documentElement.setAttribute('data-bs-theme', 'light');
            localStorage.setItem('theme', 'light');
        }
    }


    // --- Private Core Modules (Services) ---

    const AuthService = {
        /**
         * Retrieves the current user's JWT from the Supabase session.
         * @returns {Promise<string|null>} The access token or null if not available.
         */
        async getSessionToken() {
            if (!state.supabase) {
                console.warn('Cannot get session token: Supabase not initialized.');
                return null;
            }
            try {
                const { data: { session }, error } = await state.supabase.auth.getSession();
                if (error) throw error;
                return session?.access_token ?? null;
            } catch (error) {
                console.error('Error getting Supabase session token:', error.message);
                return null;
            }
        },

        /**
         * Sets the authentication token in a secure cookie.
         * @param {string} token - The JWT to set.
         */
        setAuthCookie(token) {
            if (!token) return;
            document.cookie = `${config.AUTH_COOKIE_NAME}=${token}; path=/; max-age=${config.AUTH_COOKIE_MAX_AGE_SECONDS}; SameSite=Lax; Secure`;
        },

        /**
         * Clears the authentication cookie.
         */
        clearAuthCookie() {
            document.cookie = `${config.AUTH_COOKIE_NAME}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax; Secure`;
        }
    };

    const ApiService = {
        /**
         * Makes a generic, authenticated API request.
         * @param {string} url - The URL to request.
         * @param {object} options - Standard Fetch API options (method, body, etc.).
         * @returns {Promise<object>} The JSON response.
         * @throws {Error} Throws an error if the request fails or the response is not ok.
         */
        async makeAuthenticatedRequest(url, options = {}) {
            if (!state.supabase) {
                throw new Error('Core services unavailable. Please try again later.');
            }

            const token = await AuthService.getSessionToken();
            if (!token) {
                // This error will be caught and shown to the user.
                throw new Error('Authentication required. Please login to continue.');
            }

            const fetchOptions = {
                ...options,
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`,
                    ...(options.headers || {}),
                },
            };

            const response = await fetch(url, fetchOptions);

            if (response.status === 401) {
                // Handle session expiration gracefully
                await state.supabase.auth.signOut();
                AuthService.clearAuthCookie();
                window.location.reload();
                // Throw an error that stops the current flow and is shown to the user
                throw new Error('Your session has expired. Please login again.');
            }

            if (!response.ok) {
                let errorData;
                try {
                    errorData = await response.json();
                } catch {
                    // If response is not JSON, use the status text as the error.
                    throw new Error(response.statusText || `Request failed with status ${response.status}`);
                }
                throw new Error(errorData.message || `Request failed with status ${response.status}`);
            }

            return response.json();
        }
    };


    // --- Private UI and Event Handlers ---

    /**
     * Caches frequently accessed DOM elements into the private `dom` object.
     * @private
     */
    function _cacheDomElements() {
        const elementIds = {
            authModalElement: 'authModal',
            loginForm: 'login-form',
            signupForm: 'signup-form',
            authButton: 'auth-button-main',
            logoutButton: 'logout-button-main',
            toastElement: 'toast',
            authErrorFeedback: 'auth-error',
            loginEmailInput: 'login-email',
            loginPasswordInput: 'login-password',
            signupEmailInput: 'signup-email',
            signupPasswordInput: 'signup-password',
            themeToggleMain: 'theme-toggle-main',
        };
        for (const key in elementIds) {
            dom[key] = document.getElementById(elementIds[key]);
        }
    }

    /**
     * Visibly disables authentication UI elements if Supabase fails to initialize.
     * Provides clear user feedback that a core service is unavailable.
     * @private
     */
    function _disableAuthUI() {
        console.warn("Authentication features are disabled due to Supabase initialization failure.");
        const elementsToDisable = [
            dom.loginForm,
            dom.signupForm,
            dom.authButton,
            dom.logoutButton
        ];

        elementsToDisable.forEach(element => {
            if (element) {
                element.classList.add('disabled-form'); // Assumes a CSS class to style disabled forms
                if (element.tagName === 'BUTTON') {
                    element.setAttribute('disabled', 'true');
                    element.title = "Authentication service unavailable";
                }
            }
        });
    }
    
    /**
     * Displays a toast notification message.
     * @private
     * @param {string} message - The message to display.
     * @param {'success'|'error'} type - The type of toast to show.
     */
    function _showToastNotification(message, type = 'success') {
        if (!dom.toastElement) return;
        dom.toastElement.textContent = message;
        dom.toastElement.className = `toast-notification ${type}`;
        dom.toastElement.classList.remove('hidden');

        setTimeout(() => {
            dom.toastElement.classList.add('hidden');
        }, config.TOAST_VISIBILITY_DURATION_MS);
    }

    /**
     * Displays an error message within the authentication form.
     * @private
     * @param {string} message - The error message to display.
     * @param {string[]} fieldIdsToMarkInvalid - An array of input IDs to mark as invalid.
     */
    function _displayAuthFormError(message, fieldIdsToMarkInvalid = []) {
        if (!dom.authErrorFeedback) return;
        
        const container = document.createElement('div');
        container.className = 'd-flex align-items-center';
        
        const icon = document.createElement('i');
        icon.className = 'bi bi-exclamation-triangle-fill me-2';
        
        const strongMessage = document.createElement('strong');
        strongMessage.textContent = message;
        
        container.appendChild(icon);
        container.appendChild(strongMessage);

        dom.authErrorFeedback.innerHTML = '';
        dom.authErrorFeedback.appendChild(container);
        dom.authErrorFeedback.classList.remove('d-none');
        
        fieldIdsToMarkInvalid.forEach(id => {
            document.getElementById(id)?.classList.add('is-invalid');
        });
    }

    /**
     * Clears any visible authentication form errors.
     * @private
     */
    function _clearAuthFormError() {
        if (dom.authErrorFeedback) {
            dom.authErrorFeedback.classList.add('d-none');
            dom.authErrorFeedback.innerHTML = '';
        }
        [dom.loginEmailInput, dom.loginPasswordInput, dom.signupEmailInput, dom.signupPasswordInput]
            .forEach(input => input?.classList.remove('is-invalid'));
    }

    /**
     * Handles the user login form submission with robust validation.
     * @private
     * @param {Event} event - The form submission event.
     */
    async function _handleLogin(event) {
        event.preventDefault();
        _clearAuthFormError();

        // Defensive check for required DOM elements
        if (!_validateDomElements([dom.loginForm, dom.loginEmailInput, dom.loginPasswordInput])) {
             console.error('Login form or its inputs are missing from the DOM.');
             return;
        }

        const email = dom.loginEmailInput.value.trim();
        const password = dom.loginPasswordInput.value;

        // Explicit validation before making an API call
        if (!email || !password) {
            _displayAuthFormError('Please provide both email and password.', ['login-email', 'login-password']);
            return;
        }

        try {
            const { data, error } = await state.supabase.auth.signInWithPassword({ email, password });
            if (error) throw error;

            if (data.session?.access_token) {
                AuthService.setAuthCookie(data.session.access_token);
            }
            state.authModalInstance?.hide();
            window.location.href = '/chat';
        } catch (error) {
            console.error('Login failed:', error.message);
            const friendlyMessage = _formatAuthError(error);
            _displayAuthFormError(friendlyMessage, ['login-email', 'login-password']);
        }
    }

    /**
     * Handles the user signup form submission with robust validation.
     * @private
     * @param {Event} event - The form submission event.
     */
    async function _handleSignup(event) {
        event.preventDefault();
        _clearAuthFormError();

        if (!_validateDomElements([dom.signupForm, dom.signupEmailInput, dom.signupPasswordInput])) {
             console.error('Signup form or its inputs are missing from the DOM.');
             return;
        }

        const email = dom.signupEmailInput.value.trim();
        const password = dom.signupPasswordInput.value;

        if (!email || !password) {
             _displayAuthFormError('Please provide both email and password.', ['signup-email', 'signup-password']);
            return;
        }

        try {
            const { data, error } = await state.supabase.auth.signUp({ email, password });
            if (error) throw error;
            
            if (data.session?.access_token) {
                AuthService.setAuthCookie(data.session.access_token);
            }
            state.authModalInstance?.hide();

            // Provide clear user feedback based on whether email confirmation is needed
            if (data.user && !data.session) {
                _showToastNotification('Signup successful! Please check your email to confirm your account.');
            } else {
                window.location.href = '/chat';
            }
        } catch (error) {
            console.error('Signup failed:', error.message);
            const friendlyMessage = _formatAuthError(error);
            _displayAuthFormError(friendlyMessage, ['signup-email', 'signup-password']);
        }
    }

    /**
     * Handles the user logout action.
     * @private
     */
    async function _handleLogout() {
        if (!state.supabase) return;
        try {
            const { error } = await state.supabase.auth.signOut();
            if (error) throw error;
            AuthService.clearAuthCookie();
            window.location.reload();
        } catch (error) {
            _showToastNotification(`Logout failed: ${error.message}`, 'error');
        }
    }
    
    /**
     * Binds all necessary event listeners to DOM elements.
     * @private
     */
    function _bindEventListeners() {
        // Stop if Supabase failed, UI is already disabled
        if (!state.supabase) return;
        
        dom.loginForm?.addEventListener('submit', _handleLogin);
        dom.signupForm?.addEventListener('submit', _handleSignup);
        dom.authButton?.addEventListener('click', () => state.authModalInstance?.show());
        dom.logoutButton?.addEventListener('click', _handleLogout);

        // Theme toggle listener
        dom.themeToggleMain?.addEventListener('click', () => {
            const currentTheme = document.documentElement.getAttribute('data-bs-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            _setTheme(newTheme);
        });
    }
    
    /**
     * Initializes the application.
     * This is the only public method exposed by the App module.
     * @public
     */
    function init() {
        _cacheDomElements();
        _initTheme(); // Initialize theme on landing page load
        
        if (!config.SUPABASE_URL || !config.SUPABASE_ANON_KEY) {
            console.error('CRITICAL: Supabase URL or Anonymous Key is not configured.');
            _disableAuthUI();
            return;
        }
        
        try {
            state.supabase = createClient(config.SUPABASE_URL, config.SUPABASE_ANON_KEY);
            if (dom.authModalElement) {
                state.authModalInstance = new bootstrap.Modal(dom.authModalElement);
            }
            _bindEventListeners();
        } catch (error) {
            console.error('CRITICAL: Failed to initialize application dependencies:', error.message);
            _disableAuthUI();
        }
    }

    // --- Public API ---
    // Expose only what is absolutely necessary to the global scope.
    return {
        init: init
    };

})();

// --- Application Entry Point ---
document.addEventListener('DOMContentLoaded', App.init);
