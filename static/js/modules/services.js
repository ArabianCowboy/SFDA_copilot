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

/**
 * Is this page load the landing leg of a password recovery?
 *
 * Read before the Supabase client exists, because the answer picks the client's
 * flow type and that is fixed at construction.
 *
 * Recovery mail is sent server-side (see `web/services/account_recovery.py`), so
 * the link comes back with tokens in the fragment rather than a `?code=` to
 * exchange. Measured against gotrue-js 2.62.2 on 2026-08-14: a client built with
 * `flowType: 'pkce'` **silently drops** that callback — no session, no
 * PASSWORD_RECOVERY event, and no error either, because `_initialize` swallows
 * the "Not a valid PKCE flow url" it raises. The reader lands on the page and
 * nothing whatsoever happens. `'implicit'` consumes it correctly.
 *
 * Every other flow keeps PKCE. Only this one page load changes.
 *
 * The `?recovery=1` marker is checked as well as the fragment because it is the
 * thing we control: it survives GoTrue's redirect (proven), it states the
 * reader's intent before any auth event fires, and the event ordering is a known
 * upstream bug (supabase/auth-js#349).
 */
/** Where a recovery session lives — per tab, never beside the reader's own. */
export const RECOVERY_STORAGE_KEY = 'sfda-supabase-recovery';

export function isRecoveryCallback() {
  /* Parsed, not substring-matched. `search.includes('recovery=1')` also matched
     `?notrecovery=1`, and `hash.includes('access_token=')` matched a stale or
     empty fragment — either of which put a perfectly ordinary page load into
     recovery mode. */
  if (new URLSearchParams(window.location.search).get('recovery') === '1') {
    return true;
  }

  const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  return Boolean(fragment.get('access_token')) && fragment.get('type') === 'recovery';
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

    /* A recovery session is kept in per-tab sessionStorage under its own key,
       not in the shared localStorage the signed-in reader uses.

       Supabase propagates a localStorage session to every open tab. Without this
       split, following a recovery link while the app is open elsewhere writes
       over that tab's session and hands it a recovery token as an ordinary
       sign-in — the chat shell, drawn from a link in an inbox, in a tab that
       never asked. The guards in auth-view.js only cover the tab that did.

       sessionStorage survives a reload of this tab, which is all the flow needs,
       and dies with it, which is the point. */
    const recovering = isRecoveryCallback();

    this.supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        storage: recovering ? window.sessionStorage : window.localStorage,
        storageKey: recovering ? RECOVERY_STORAGE_KEY : 'sfda-supabase-auth',
        flowType: recovering ? 'implicit' : 'pkce',
        debug: isDebugMode,
      },
    });

    if (isDebugMode) window.supabaseClient = this.supabase;
    return this.supabase;
  },

  parseSseFrame,

  async getFaqData(lang = document.documentElement.lang || 'en') {
    const response = await fetch(`/api/frequent-questions?lang=${encodeURIComponent(lang)}`);
    if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
    return response.json();
  },

  /** Blocking fallback for browsers without streaming bodies.
   *
   *  `lang` is not optional: the route answers in whatever language it is
   *  given, so omitting it here answered an Arabic reader in English on every
   *  browser that lands on this path. The server accepting `lang` is only half
   *  the fix — nothing was sending it.
   */
  async sendChatRequest(query, category, token, lang = 'en') {
    this.cancelChatRequest();
    this.chatAbortController = new AbortController();

    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch('/api/chat', {
      method: 'POST',
      headers,
      signal: this.chatAbortController.signal,
      body: JSON.stringify({ query, category, lang }),
    });

    if (!response.ok) {
      const errorJson = await response.json().catch(() => ({}));
      // Status and code ride along. Flattening to a message string loses the
      // difference between "you are blocked" and "the network failed", and the
      // reader is owed different words for each.
      const failure = new Error(errorJson.error || `Network error (${response.status})`);
      failure.status = response.status;
      failure.code = errorJson.error;
      throw failure;
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
      const failure = new Error(errorJson.error || `Network error (${response.status})`);
      failure.status = response.status;
      failure.code = errorJson.error;
      throw failure;
    }
    if (!response.body) throw new Error('STREAM_UNSUPPORTED');

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    // Both are required for the exchange to count as complete; see the note
    // at the end of this function.
    const seen = { final: false, done: false };

    /* A chunk is not a frame: one read may deliver half a frame or twelve of
       them. Drain whatever complete frames the buffer currently holds. */
    const drain = () => {
      let boundary;
      while ((boundary = FRAME_SEPARATOR.exec(buffer)) !== null) {
        const raw = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const frame = parseSseFrame(raw);
        if (!frame) continue;
        if (frame.event === 'final') seen.final = true;
        if (frame.event === 'done') seen.done = true;
        on[frame.event]?.(frame.data);
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

    /* A closed socket is not a finished answer. A proxy timeout, a dropped
       connection or a killed worker all end the body cleanly, and without this
       the caller treated the tokens it happened to receive as the whole
       answer: rendered, announced complete, and — because `final` never
       arrived — never normalized, so legacy "[Source: Doc, Page: N]" citations
       stayed as prose and the reader was shown a truncated answer with no
       indication it was truncated. On a regulatory surface a half-answer
       presented as authoritative is the worst thing this module can do.

       Reported to the caller rather than thrown, so whatever DID arrive is
       still shown — flagged as incomplete instead of discarded. */
    return { complete: seen.final && seen.done };
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

  /**
   * Ask for a password-reset link.
   *
   * Goes to our own origin rather than straight to Supabase, unlike `login` and
   * `signup` above. A link requested from the browser carries a PKCE
   * `code_challenge` whose verifier is written into *this* browser's storage, so
   * opening the mail on a phone could never complete it. The server has no such
   * problem, and readers open mail on whatever device is to hand.
   *
   * The server answers the same way whether or not the address exists, so there
   * is nothing here to branch on — only a rate limit, which is worth telling the
   * reader about because it means "wait", not "give up".
   */
  async requestPasswordReset(email, lang) {
    const response = await fetch('/auth/recover', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ email, lang }),
    });

    if (response.status === 429) {
      const body = await response.json().catch(() => ({}));
      const refusal = new Error(body.error || 'reset_rate_limited');
      refusal.code = body.error || 'reset_rate_limited';
      throw refusal;
    }
    if (!response.ok) throw new Error(`Reset request failed: ${response.status}`);
    return response.json().catch(() => ({ sent: true }));
  },

  /**
   * Set a new password on the recovery session the callback established.
   *
   * Short-circuits under `?testing=true` for the same reason `getSessionToken`
   * and `logout` do: the demo path is a shipping surface and has to be able to
   * show this view end to end without a Supabase project behind it.
   */
  async updatePassword(password) {
    if (window.location.search.includes('testing=true')) return { testing: true };
    if (!this.supabase) throw new Error('Supabase client not initialized.');
    const { data, error } = await this.supabase.auth.updateUser({ password });
    if (error) throw error;
    return data;
  },

  /**
   * End the session on BOTH sides.
   *
   * Signing out of Supabase drops the access token; it does nothing to the
   * Flask session cookie, which carries `conv_id` — the key into the
   * server-side conversation history. Without the call below that cookie
   * survived logout intact, and the next reader to sign in on this browser
   * had the previous reader's conversation fed to the model as context.
   *
   * The server call goes FIRST and its failure is not fatal: a network error
   * must not leave the reader signed in, and the server rotates conversation
   * state on an identity change anyway. `credentials: 'same-origin'` is
   * explicit because the whole point is to send the cookie.
   */
  async endServerSession() {
    try {
      await fetch('/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
      });
    } catch (error) {
      console.warn('[SFDA Copilot] Server session teardown failed:', error);
    }
  },

  /**
   * End the current conversation server-side, keeping the reader signed in.
   *
   * `mode` is `{}` to reset, `{ undo: true }` to put the previous conversation
   * back, `{ forget: true }` to drop the one an earlier reset set aside.
   *
   * Failure THROWS here, unlike endServerSession, and the difference is
   * deliberate. A logout that cannot reach the server must still sign the
   * reader out locally. A reset that cannot reach the server must not clear
   * the transcript: a blank screen over a server that still holds the history
   * is worse than no reset at all, because the next answer would silently
   * carry context the reader believes they deleted.
   */
  async resetConversation(mode = {}) {
    const headers = { 'Content-Type': 'application/json' };
    const token = await this.getSessionToken().catch(() => null);
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch('/api/conversation/reset', {
      method: 'POST',
      headers,
      cache: 'no-store',
      credentials: 'same-origin',
      body: JSON.stringify(mode),
    });

    if (!response.ok) {
      const errorJson = await response.json().catch(() => ({}));
      throw new Error(errorJson.error || `Network error (${response.status})`);
    }
    return response.json().catch(() => ({}));
  },

  async logout() {
    await this.endServerSession();

    if (window.location.search.includes('testing=true')) return { testing: true };
    if (!this.supabase) throw new Error('Authentication service not available.');

    const { data: { session }, error: sessionError } = await this.supabase.auth.getSession();
    if (sessionError) throw sessionError;
    if (!session) return { signedOut: false, sessionMissing: true };

    /* `global` is already the library default, and it is stated here anyway.
       After a password change every other device must lose its session — OWASP's
       Forgot Password guidance asks for exactly that, and Supabase does not do it
       on a password change by itself. A property that matters this much should
       not rest on a default that a future version is free to change. */
    const { error } = await this.supabase.auth.signOut({ scope: 'global' });
    if (error) throw error;
    return { signedOut: true, sessionMissing: false };
  },

  /**
   * What the server believes about the signed-in reader.
   *
   * The authoritative answer to "is this an administrator" — as opposed to the
   * `is_admin_hint` cookie, which only decides whether a link is drawn on a
   * page the server renders without validating a token. It is also the only
   * thing that works on a first sign-in in a fresh browser, where no hint
   * exists yet because no authenticated request has been made.
   *
   * Returns null when the answer is simply "nobody" or "not allowed" — those
   * are answers, not faults, and the caller's safe default for both is the
   * same. A network failure still throws, because that is a fault.
   */
  async getIdentity() {
    const token = await this.getSessionToken();
    if (!token) return null;

    const response = await fetch('/api/identity', {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (response.status === 401 || response.status === 403) return null;
    if (!response.ok) throw new Error(`Identity check failed (${response.status})`);
    return response.json();
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
