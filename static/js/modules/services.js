/**
 * SFDA Copilot — Backend & auth services
 * Supabase auth, profile CRUD, FAQ fetch and the chat API call.
 */

import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.39.7/+esm';

import { CONFIG } from './config.js';
import { DOMCache, AppState, ErrorHandler, logError } from './dom.js';
import { UI } from './ui.js';

export const Services = {
  supabase: null,

  init() {
    if (this.supabase) return true;

    const { SUPABASE_URL, SUPABASE_ANON_KEY } = window;

    if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
      logError('Supabase configuration missing.', 'Services.init');
      ErrorHandler.showToast('Supabase configuration is missing.', true);
      return false;
    }

    if (!SUPABASE_URL.startsWith('http://') && !SUPABASE_URL.startsWith('https://')) {
      logError('Invalid Supabase URL format.', 'Services.init');
      ErrorHandler.showToast('Invalid Supabase URL format.', true);
      return false;
    }

    try {
      const isDebugMode =
        window.location.hostname === 'localhost' ||
        window.location.hostname === '127.0.0.1';

      this.supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true,
          storage: window.localStorage,
          storageKey: 'sfda-supabase-auth',
          flowType: 'pkce',
          debug: isDebugMode,
        },
      });

      if (isDebugMode) window.supabaseClient = this.supabase;

      AppState.set('supabase', this.supabase);
      return true;
    } catch (error) {
      logError(error, 'Services.init');
      ErrorHandler.showToast('Failed to initialize authentication service.', true);
      return false;
    }
  },

  async getFaqData() {
    try {
      const response = await fetch('/api/frequent-questions');
      if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
      return await response.json();
    } catch (error) {
      logError(error, 'getFaqData');
      ErrorHandler.showToast('Failed to load FAQs.', true);
      return null;
    }
  },

  async sendChatRequest(query, category, token) {
    const abortController = AppState.resetAbortController();

    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch('/api/chat', {
      method: 'POST',
      headers,
      signal: abortController.signal,
      body: JSON.stringify({ query, category }),
    });

    if (!response.ok) {
      const errorJson = await response.json().catch(() => ({}));
      throw new Error(errorJson.error || `Network error (${response.status})`);
    }
    return response.json();
  },

  async getSessionToken() {
    if (window.location.search.includes('testing=true')) return 'fake_token';
    if (!this.supabase) {
      logError('Supabase client not initialized.', 'getSessionToken');
      return null;
    }

    const { data, error } = await this.supabase.auth.getSession();
    if (error) {
      logError(error, 'getSessionToken');
      return null;
    }
    return data.session?.access_token ?? null;
  },

  async login(email, password) {
    try {
      if (!this.supabase) throw new Error('Supabase client not initialized.');

      const { data, error } = await this.supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;

      AppState.get('authModal')?.hide();
      DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.reset();
      ErrorHandler.showToast(data?.user?.email ? `Logged in as ${data.user.email}` : 'Login successful!');
    } catch (error) {
      logError(error, 'Services.login');
      ErrorHandler.showAuthError(ErrorHandler.formatAuthError(error));
    }
  },

  async signup(email, password) {
    try {
      if (!this.supabase) throw new Error('Supabase client not initialized.');

      const { error } = await this.supabase.auth.signUp({ email, password });
      if (error) throw error;

      DOMCache.get(CONFIG.SELECTORS.SIGNUP_FORM)?.reset();
      ErrorHandler.showToast('Signup initiated! Please check your email to confirm.');
    } catch (error) {
      logError(error, 'Services.signup');
      ErrorHandler.showAuthError(ErrorHandler.formatAuthError(error));
    }
  },

  redirectToHomeIfNeeded() {
    if (window.location.pathname !== '/') window.location.replace('/');
  },

  clearLocalAuthData() {
    ['sb-access-token', 'sb-refresh-token', 'sb-user', 'sb-session', 'sfda-supabase-auth'].forEach(key => {
      try {
        localStorage.removeItem(key);
      } catch (error) {
        logError(error, `clearLocalAuthData: ${key}`);
      }
    });
  },

  async logout() {
    if (window.location.search.includes('testing=true')) {
      UI.updateAuthUI(null);
      ErrorHandler.showToast('Logged out successfully (testing mode)');
      return;
    }

    if (!this.supabase) {
      ErrorHandler.showToast('Authentication service not available', true);
      return;
    }

    try {
      const { data: { session } } = await this.supabase.auth.getSession();

      if (!session) {
        this.clearLocalAuthData();
        UI.updateAuthUI(null);
        ErrorHandler.showToast('Logged out successfully');
        this.redirectToHomeIfNeeded();
        return;
      }

      const { error } = await this.supabase.auth.signOut();
      if (error) throw error;

      ErrorHandler.showToast('Logged out successfully');
      this.clearLocalAuthData();
      this.redirectToHomeIfNeeded();
    } catch (error) {
      logError(error, 'logout');
      this.clearLocalAuthData();
      UI.updateAuthUI(null);
      ErrorHandler.showToast('Logged out (session cleared)', false);
      this.redirectToHomeIfNeeded();
    }
  },

  async getProfile(userId) {
    try {
      if (!this.supabase) throw new Error('Supabase client not initialized.');

      const { data, error } = await this.supabase
        .from('profiles')
        .select('id, full_name, organization, specialization, preferences')
        .eq('id', userId)
        .single();

      if (error && error.code !== 'PGRST116') throw error;
      return data;
    } catch (error) {
      logError(error, 'getProfile');
      ErrorHandler.showToast('Could not load your profile.', true);
      return null;
    }
  },

  async updateProfile(userId, updates) {
    try {
      if (!this.supabase) throw new Error('Supabase client not initialized.');

      const { error } = await this.supabase.from('profiles').upsert({ id: userId, ...updates }, { onConflict: 'id' });
      if (error) throw error;
      return true;
    } catch (error) {
      logError(error, 'updateProfile');
      ErrorHandler.showProfileError(`Failed to save: ${error.message}`);
      return false;
    }
  },
};
