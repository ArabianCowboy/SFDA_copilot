/**
 * SFDA Copilot — Backend & auth services
 * Supabase auth, profile CRUD, FAQ fetch and the chat API call.
 */

import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.39.7/+esm';

/* Deliberately NOT global: a /g regex carries lastIndex between calls, and
   this one is reused across every drain of the stream buffer. */
const FRAME_SEPARATOR = /\r?\n\r?\n/;

/**
 * Parse one SSE frame into { event, data }.
 * Returns null for comment-only frames (keep-alive pings) and unparseable data.
 */
export function parseSseFrame(raw) {
  let event = 'message';
  const dataLines = [];

  for (const line of raw.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue;   // blank or comment
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);

    if (field === 'event') event = value;
    else if (field === 'data') dataLines.push(value);
  }

  if (!dataLines.length) return null;
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) };
  } catch {
    return null;
  }
}

export const Services = {
  supabase: null,
  chatAbortController: null,

  init() {
    if (this.supabase) return this.supabase;

    const { SUPABASE_URL, SUPABASE_ANON_KEY } = window;

    if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
      throw new Error('Supabase configuration is missing.');
    }

    if (!SUPABASE_URL.startsWith('http://') && !SUPABASE_URL.startsWith('https://')) {
      throw new Error('Invalid Supabase URL format.');
    }

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
    return this.supabase;
  },

  parseSseFrame,

  async getFaqData() {
    const response = await fetch('/api/frequent-questions');
    if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
    return response.json();
  },

  async sendChatRequest(query, category, token) {
    this.cancelChatRequest();
    this.chatAbortController = new AbortController();

    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch('/api/chat', {
      method: 'POST',
      headers,
      signal: this.chatAbortController.signal,
      body: JSON.stringify({ query, category }),
    });

    if (!response.ok) {
      const errorJson = await response.json().catch(() => ({}));
      throw new Error(errorJson.error || `Network error (${response.status})`);
    }
    return response.json();
  },

  /**
   * Stream a chat answer over SSE.
   *
   * EventSource cannot set an Authorization header, and the alternatives are
   * all worse — a token in the query string leaks into access logs, Referer
   * and history; a cookie duplicates the header-based Supabase auth surface.
   * fetch + response.body.getReader() avoids both and gives AbortController
   * support, which EventSource also lacks.
   *
   * `on` is a map of event name -> handler, keeping this module free of any
   * dom/state/ui import (enforced by test_frontend_architecture.py).
   */
  async streamChatRequest(query, category, token, lang, on = {}) {
    this.cancelChatRequest();
    this.chatAbortController = new AbortController();

    const headers = { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers,
      cache: 'no-store',
      signal: this.chatAbortController.signal,
      body: JSON.stringify({ query, category, lang }),
    });

    // Failures before the first frame still carry a real status code, so the
    // caller can distinguish them from an in-band `error` event.
    if (!response.ok) {
      const errorJson = await response.json().catch(() => ({}));
      throw new Error(errorJson.error || `Network error (${response.status})`);
    }
    if (!response.body) throw new Error('STREAM_UNSUPPORTED');

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    /* A chunk is not a frame: one read may deliver half a frame or twelve of
       them. Drain whatever complete frames the buffer currently holds. */
    const drain = () => {
      let boundary;
      while ((boundary = FRAME_SEPARATOR.exec(buffer)) !== null) {
        const raw = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const frame = parseSseFrame(raw);
        if (frame) on[frame.event]?.(frame.data);
      }
    };

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        drain();
      }
      buffer += decoder.decode();  // flush any trailing multi-byte sequence
      drain();
    } finally {
      try { reader.releaseLock(); } catch { /* already released */ }
    }
  },

  cancelChatRequest() {
    this.chatAbortController?.abort();
    this.chatAbortController = null;
  },

  async getSessionToken() {
    if (window.location.search.includes('testing=true')) return 'fake_token';
    if (!this.supabase) throw new Error('Supabase client not initialized.');

    const { data, error } = await this.supabase.auth.getSession();
    if (error) throw error;
    return data.session?.access_token ?? null;
  },

  async login(email, password) {
    if (!this.supabase) throw new Error('Supabase client not initialized.');
    const { data, error } = await this.supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
    return data;
  },

  async signup(email, password) {
    if (!this.supabase) throw new Error('Supabase client not initialized.');
    const { data, error } = await this.supabase.auth.signUp({ email, password });
    if (error) throw error;
    return data;
  },

  async logout() {
    if (window.location.search.includes('testing=true')) return { testing: true };
    if (!this.supabase) throw new Error('Authentication service not available.');

    const { data: { session }, error: sessionError } = await this.supabase.auth.getSession();
    if (sessionError) throw sessionError;
    if (!session) return { signedOut: false, sessionMissing: true };

    const { error } = await this.supabase.auth.signOut();
    if (error) throw error;
    return { signedOut: true, sessionMissing: false };
  },

  async getProfile(userId) {
    if (!this.supabase) throw new Error('Supabase client not initialized.');
    const { data, error } = await this.supabase
      .from('profiles')
      .select('id, full_name, organization, specialization, preferences')
      .eq('id', userId)
      .single();

    if (error && error.code !== 'PGRST116') throw error;
    return data;
  },

  async updateProfile(userId, updates) {
    if (!this.supabase) throw new Error('Supabase client not initialized.');
    const { error } = await this.supabase
      .from('profiles')
      .upsert({ id: userId, ...updates }, { onConflict: 'id' });
    if (error) throw error;
    return true;
  },
};
