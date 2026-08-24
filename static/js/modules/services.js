/**
 * SFDA Copilot — Backend & auth services
 * Supabase auth, profile CRUD, FAQ fetch and the chat API call.
 */

import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.74.0/+esm';

/* Deliberately NOT global: a /g regex carries lastIndex between calls, and
   this one is reused across every drain of the stream buffer. */
const FRAME_SEPARATOR = /\r?\n\r?\n/;

/* The one outstanding /api/identity call, shared by every concurrent
   caller. `onAuthStateChange` fires this lookup on both INITIAL_SESSION and
   SIGNED_IN for a single page load — originally verified against
   @supabase/supabase-js@2.39.7 (`_recoverAndRefresh` queues a SIGNED_IN
   notification during initialize() while `onAuthStateChange` separately
   emits INITIAL_SESSION straight to each subscriber once initializePromise
   settles), and re-confirmed on upgrade to 2.74.0 (2026-08-24, see
   docs/notification-center-plan.md §2/§7 step 4a: auth-js's own changelog
   between those versions documents no change to this ordering, and this
   dedup does not depend on which event causes the double-fire — only on the
   fact that concurrent calls can happen). Without it, two independent,
   unordered fetches race to decide one boolean, and whichever happens to
   RESOLVE last wins regardless of which was more current. One shared
   promise means both callers see the same answer, so there is nothing left
   to race. */
let identityInFlight = null;

/**
 * Mint an idempotency key for one logical submission.
 *
 * The SERVER cannot mint this. A server-minted id would be fresh on every
 * retry, so the unique constraint it feeds would never fire and a resend after
 * a dropped connection would file the same exchange twice. The id has to be
 * stable across retries of one question, which only the sender knows.
 *
 * `crypto.randomUUID` is unavailable on insecure origins and in a few older
 * browsers; the fallback is not cryptographically strong and does not need to
 * be. Its only job is to be unlikely to collide with another submission by the
 * same reader in the same session, and a collision costs a dropped duplicate
 * rather than anything unsafe.
 */
export function newRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/**
 * Parse one SSE frame into { event, data }.
 * Returns null for comment-only frames (keep-alive pings) and unparseable data.
 */
export function parseSseFrame(raw) {
  let event = 'message';
  const dataLines = [];

  for (const line of raw.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue; // blank or comment
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
      window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';

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
  async sendChatRequest(
    query,
    category,
    token,
    lang = 'en',
    requestId = null,
    conversation = null,
  ) {
    this.cancelChatRequest();
    this.chatAbortController = new AbortController();

    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch('/api/chat', {
      method: 'POST',
      headers,
      signal: this.chatAbortController.signal,
      body: JSON.stringify({
        query,
        category,
        lang,
        client_request_id: requestId || newRequestId(),
        // `conversation` carries {id, allowCreate} — the URL-as-pointer
        // contract (Decision 4). Omitted entirely when null, which is the
        // absent-not-malformed signal the server's §8 cookie fallback needs.
        ...(conversation
          ? {
              conversation_id: conversation.id,
              allow_create: conversation.allowCreate,
            }
          : {}),
      }),
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
  async streamChatRequest(
    query,
    category,
    token,
    lang,
    on = {},
    requestId = null,
    conversation = null,
  ) {
    this.cancelChatRequest();
    this.chatAbortController = new AbortController();

    const headers = { 'Content-Type': 'application/json', Accept: 'text/event-stream' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers,
      cache: 'no-store',
      signal: this.chatAbortController.signal,
      body: JSON.stringify({
        query,
        category,
        lang,
        client_request_id: requestId || newRequestId(),
        // See sendChatRequest's comment — same contract, same reason.
        ...(conversation
          ? {
              conversation_id: conversation.id,
              allow_create: conversation.allowCreate,
            }
          : {}),
      }),
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
      buffer += decoder.decode(); // flush any trailing multi-byte sequence
      drain();
    } finally {
      try {
        reader.releaseLock();
      } catch {
        /* already released */
      }
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

  /**
   * `metadata` lands in `raw_user_meta_data`, which `handle_new_user`
   * (supabase/migrations/20260822225415_profile_identity_atomic_cutover.sql)
   * reads to seed `first_name`/`family_name` — coercing malformed input
   * toward null rather than raising, because that trigger is AFTER INSERT
   * on auth.users and a raise there rolls back account creation itself.
   * Never send anything here this app is not prepared to have a direct
   * GoTrue caller send maliciously: that trigger is the only validation.
   */
  async signup(email, password, metadata = {}) {
    if (!this.supabase) throw new Error('Supabase client not initialized.');
    const { data, error } = await this.supabase.auth.signUp({
      email,
      password,
      options: { data: metadata },
    });
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

  // NO `resetConversation`. `/api/conversation/reset` is deleted server-side
  // (docs/per-tab-conversation-deep-linking-plan.md §5.1, §5.4) — "New chat"
  // is a client-side navigation to `/` now (Decision 2), with no server round
  // trip at all. See `Handlers.handleNewChat`.

  async logout() {
    await this.endServerSession();

    if (window.location.search.includes('testing=true')) return { testing: true };
    if (!this.supabase) throw new Error('Authentication service not available.');

    const {
      data: { session },
      error: sessionError,
    } = await this.supabase.auth.getSession();
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
   * End every OTHER session, keeping this device's own signed in. Distinct
   * from `logout`'s `scope: 'global'`, which ends this one too.
   *
   * There is no session-listing endpoint in the GoTrue admin API — it
   * exposes only /admin/generate_link, /admin/user/{id}, /admin/users — so
   * "Sign out everywhere else" is the whole feature, not a stand-in for a
   * list the API does not offer.
   *
   * Revocation is NOT instant: Supabase's own docs are explicit that a
   * revoked session's access token stays valid until its `exp` claim. The
   * caller's copy must say so rather than imply the other devices are
   * signed out the moment this call returns.
   */
  async signOutOtherSessions() {
    if (!this.supabase) throw new Error('Authentication service not available.');
    const { error } = await this.supabase.auth.signOut({ scope: 'others' });
    if (error) throw error;
  },

  /**
   * Send a reauthentication nonce to the reader's own email.
   *
   * GoTrue's own reauthentication_needed error code is what actually decides
   * whether this step is required — the project's own "require
   * reauthentication when changing password" setting exempts a session
   * created within the last 24 hours, so calling this unconditionally before
   * every password change would demand a code that was not always needed.
   * `updateOwnPassword` is written to try without one first.
   */
  async reauthenticate() {
    if (!this.supabase) throw new Error('Authentication service not available.');
    const { error } = await this.supabase.auth.reauthenticate();
    if (error) throw error;
  },

  /**
   * Change the reader's own password. No current-password field: GoTrue has
   * no such check, and asking for one would be UI for a step that does not
   * exist server-side. `nonce` is supplied only on the second attempt, after
   * `reauthenticate()` has sent one — see the caller in account/handlers.js
   * for the two-step flow this single call is a leaf of.
   *
   * Deliberately does NOT revoke other sessions itself — the caller decides
   * whether to (see `signOutOtherSessions`), because a raw GoTrue password
   * change and "also end every other session" are two different promises,
   * and this function keeps to the one its name makes.
   */
  async updateOwnPassword(password, nonce = null) {
    if (!this.supabase) throw new Error('Authentication service not available.');
    const payload = nonce ? { password, nonce } : { password };
    const { data, error } = await this.supabase.auth.updateUser(payload);
    if (error) throw error;
    return data;
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
   * Returns null when the answer is simply "nobody" (no session, or an
   * invalid/expired one — 401) — that is an answer, not a fault, and the
   * caller's safe default for it is the same as for never having asked.
   *
   * "Not allowed" (signed in, but the account is disabled — 403) is answered
   * differently: it throws, with `.status = 403` and `.code =
   * 'account_disabled'`, the same error-tagging shape chat requests already
   * use for this case. A disabled reader is a real, disclosable state a
   * caller may want to act on (e.g. showing an early notice) rather than a
   * plain "nobody" a caller has no way to distinguish from being signed out.
   *
   * A network failure still throws too, because that is a fault.
   *
   * Deduplicated: a call made while one is already in flight gets the same
   * promise rather than starting a second fetch — see `identityInFlight`.
   * The assignment below happens synchronously, before any `await`, so two
   * calls made in the same tick can never both see it unset.
   */
  async getIdentity() {
    if (identityInFlight) return identityInFlight;

    identityInFlight = (async () => {
      const token = await this.getSessionToken();
      if (!token) return null;

      // A hard ceiling, not a courtesy: without it a hung request never
      // rejects, so `fetchIdentityWithRetry` in app.js never gets a chance
      // to try again and the console link stays hidden for the rest of the
      // page's life. AbortController rather than Promise.race, so the
      // underlying request is actually cancelled rather than left running.
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);
      let response;
      try {
        response = await fetch('/api/identity', {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timeoutId);
      }
      if (response.status === 401) return null;
      if (response.status === 403) {
        // Status and code ride along, mirroring the pattern used for chat
        // requests above — flattening this to null loses the difference
        // between "nobody" and "a disabled account", and a caller may need
        // to tell them apart.
        const errorJson = await response.json().catch(() => ({}));
        const refusal = new Error(errorJson.error || 'account_disabled');
        refusal.status = 403;
        refusal.code = errorJson.error || 'account_disabled';
        throw refusal;
      }
      if (!response.ok) {
        // `.status` lets a caller decide what is worth retrying (a 503 from
        // an identity-provider outage, per `_authenticate_request`'s own
        // classification) from what is not (some other 4xx, which retrying
        // would only repeat).
        const error = new Error(`Identity check failed (${response.status})`);
        error.status = response.status;
        throw error;
      }
      return response.json();
    })();

    try {
      return await identityInFlight;
    } finally {
      identityInFlight = null;
    }
  },

  /**
   * One conversation's durable rows, named by the URL (Decision 4 of
   * docs/per-tab-conversation-deep-linking-plan.md).
   *
   * `conversationId` is `Route.current()` — the caller never calls this with
   * nothing to ask for; `/` is a new conversation and has no history to fetch
   * (§4.2). Passed through as `?c=<id>` so the server can tell "not yours, or
   * not there" from "yours, but empty" (§3.3).
   *
   * Returns `{ conversation_id, messages }`. Throws on any failure, tagged
   * with `.status`, so the caller can tell a genuinely empty history ("you
   * have not asked anything yet") from an unreachable store — 503
   * `history_unavailable` — or a stale/foreign id — 404 `not_found`. Those
   * must not look alike: rendering an empty transcript for either would be a
   * claim the app cannot back.
   */
  async getChatHistory(conversationId) {
    const token = await this.getSessionToken();
    if (!token) return { conversation_id: null, messages: [] };

    // The same 5s ceiling `getIdentity` takes, for the same reason: this call
    // sits on the path that draws the whole screen, and a hung request would
    // leave a signed-in reader looking at an empty transcript forever.
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    const query = `?c=${encodeURIComponent(conversationId)}`;
    let response;
    try {
      response = await fetch(`/api/chat/history${query}`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
        /* This body is one reader's conversation. The server also sends
           `Cache-Control: private, no-store`; asking here too means a shared
           machine cannot serve the previous reader's transcript out of the
           browser's cache even if an intermediary is careless with the header. */
        cache: 'no-store',
      });
    } finally {
      clearTimeout(timeoutId);
    }

    /* 401 is an ANSWER, not a fault — the same reading `getIdentity` takes of
       the same status. Nobody is signed in, so there is no transcript to draw
       and nothing to report; throwing here would put an error toast under a
       reader who is simply signed out, and under the `?testing=true` demo
       path, whose deliberately fake token a real server rejects. */
    if (response.status === 401) {
      return { conversation_id: null, messages: [] };
    }

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const error = new Error(body.error || `History unavailable (${response.status})`);
      error.status = response.status;
      error.code = body.code || 'history_unavailable';
      throw error;
    }
    return response.json();
  },

  /**
   * One request against the conversation sidebar's four routes.
   *
   * Factored because the four differ only in method, path and body, and the
   * things they must NOT differ in are exactly the things that get forgotten
   * one call site at a time: the bearer token, `cache: 'no-store'` (these
   * bodies are the reader's own questions, and a shared machine must not serve
   * the previous reader's list out of the browser cache), and an error carrying
   * both `.status` and `.code` so the caller can tell 409 `generation_in_flight`
   * from 503 `history_unavailable` from 404.
   *
   * 401 RESOLVES rather than throwing, matching `getChatHistory` and
   * `getIdentity`: nobody is signed in, so there is no list, and an error toast
   * under a signed-out reader is noise about a state that is correct.
   */
  async sessionRequest(path, { method = 'GET', body = null } = {}) {
    const token = await this.getSessionToken();
    if (!token) return null;

    const headers = { Authorization: `Bearer ${token}` };
    if (body) headers['Content-Type'] = 'application/json';

    /* The same 5s ceiling the transcript read takes. The sidebar sits on the
       path that draws the screen, and a hung request would leave a reader
       looking at a spinner with no way to retry. */
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    let response;
    try {
      response = await fetch(path, {
        method,
        headers,
        cache: 'no-store',
        credentials: 'same-origin',
        signal: controller.signal,
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
    } finally {
      clearTimeout(timeoutId);
    }

    if (response.status === 401) return null;

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      const error = new Error(payload.error || `Request failed (${response.status})`);
      error.status = response.status;
      error.code = payload.code || 'unknown';
      throw error;
    }
    return response.json().catch(() => ({}));
  },

  /**
   * One page of the reader's conversations.
   *
   * `cursor` is the opaque `{updated_at, id}` the previous page returned, and it
   * is passed back verbatim rather than reconstructed from the last row. The
   * server decides what continues a page; a client that rebuilt the cursor
   * would be reimplementing the keyset ordering and would drift the first time
   * that ordering changed.
   */
  async listSessions({ cursor = null } = {}) {
    const params = new URLSearchParams();
    if (cursor?.updated_at && cursor?.id) {
      params.set('cursor_updated_at', cursor.updated_at);
      params.set('cursor_id', cursor.id);
    }
    const query = params.toString();
    return this.sessionRequest(`/api/chat/sessions${query ? `?${query}` : ''}`);
  },

  // NO `selectSession`. `/api/chat/sessions/<id>/select` is deleted
  // server-side (docs/per-tab-conversation-deep-linking-plan.md §5.2) — its
  // entire job was repointing a cookie that no longer exists. Selecting a
  // conversation is navigating to its `/c/<id>` URL now (`Route.go`), and
  // the sidebar re-reads `/api/chat/history?c=<id>` directly.

  async renameSession(sessionId, title) {
    return this.sessionRequest(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'PATCH',
      body: { title },
    });
  },

  async deleteSession(sessionId) {
    return this.sessionRequest(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    });
  },

  /**
   * Downloads the reader's full conversation history as NDJSON.
   *
   * Not `sessionRequest` — that always parses the body as JSON, and this
   * response's body IS the file. Returns `{ blob, filename }` rather than
   * saving it itself: this module does I/O, not DOM manipulation, and the
   * caller (account/handlers.js) is what knows how to trigger a download.
   *
   * Deliberately no `AbortController` ceiling, unlike `getChatHistory` and
   * `sessionRequest`: those sit on a path that draws the screen and must not
   * hang a reader looking at a spinner; this streams a reader's ENTIRE
   * history and may legitimately take longer than either.
   */
  async exportConversations() {
    const token = await this.getSessionToken();
    if (!token) return null;

    const response = await fetch('/account/api/export', {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });

    if (response.status === 401) return null;

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      const error = new Error(payload.error || `Export failed (${response.status})`);
      error.status = response.status;
      error.code = payload.code || 'unknown';
      throw error;
    }

    const disposition = response.headers.get('Content-Disposition') || '';
    const match = /filename="([^"]+)"/.exec(disposition);
    const filename = match ? match[1] : 'sfda-copilot-conversations.ndjson';
    const blob = await response.blob();
    return { blob, filename };
  },

  /** Delete every owned conversation. Named distinctly from account
   * deletion — see web/api/account.py's own docstring. */
  async deleteAllConversations() {
    return this.sessionRequest('/account/api/conversations', { method: 'DELETE' });
  },

  async getProfile(userId) {
    if (!this.supabase) throw new Error('Supabase client not initialized.');
    const { data, error } = await this.supabase
      .from('profiles')
      .select(
        'id, first_name, family_name, age, full_name, organization, specialization, preferences, marketing_consent',
      )
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

  /**
   * Merge into the caller's own `preferences`, never replace it.
   *
   * The upsert `updateProfile` does replaces the whole JSONB column, which
   * is safe only while it holds a single key. This calls
   * `update_own_preferences` (profile_preferences_merge_rpc.sql) instead —
   * `auth.uid()`-bound server-side, so there is no userId argument here to
   * get wrong, and its own allow-list rejects an unknown key rather than
   * silently storing it. Returns the merged document.
   */
  async updateOwnPreferences(patch) {
    if (!this.supabase) throw new Error('Supabase client not initialized.');
    const { data, error } = await this.supabase.rpc('update_own_preferences', { p_patch: patch });
    if (error) throw error;
    return data;
  },

  /**
   * Notification Center (docs/notification-center-plan.md). Reader-facing
   * only — the admin composer/history calls live in static/js/admin/services.js,
   * a separate module tree with its own import map (test_frontend_architecture.py).
   *
   * All four go through `sessionRequest`, which already gives them the
   * bearer token, `cache: 'no-store'` (this is one reader's own targeted
   * messages and read state), 401-resolves-to-null, and a tagged error on
   * every other failure. REST is the guaranteed-delivery path — a Realtime
   * push, when the pinned SDK supports one, only ever tells an open tab to
   * call `fetchActive` again sooner than its next poll.
   */
  notifications: {
    fetchActive(lang = document.documentElement.lang || 'en') {
      return Services.sessionRequest(`/api/notifications/active?lang=${encodeURIComponent(lang)}`);
    },

    /** `cursor` is the opaque `{created_at, id}` the previous page returned,
     * passed back verbatim — the same keyset contract `listSessions` uses. */
    fetchHistory({ cursor = null, lang = document.documentElement.lang || 'en' } = {}) {
      const params = new URLSearchParams({ lang });
      if (cursor?.created_at && cursor?.id) {
        params.set('cursor_created_at', cursor.created_at);
        params.set('cursor_id', cursor.id);
      }
      return Services.sessionRequest(`/api/notifications/history?${params.toString()}`);
    },

    markRead(notificationId, action) {
      return Services.sessionRequest('/api/notifications/mark-read', {
        method: 'POST',
        body: { notification_id: notificationId, action },
      });
    },

    markAllRead() {
      return Services.sessionRequest('/api/notifications/mark-all-read', { method: 'POST' });
    },

    /**
     * The Realtime leg of the plan's hybrid delivery (§2) — a latency
     * optimisation for an already-open tab, never the source of truth.
     * REST (`fetchActive` above, on its own poll loop) is the guaranteed-
     * delivery path; every message this channel delivers carries no
     * notification content at all, only `{notification_id, revision}` —
     * handlers.js's only reaction is "call fetchActive again now instead
     * of waiting for the next poll tick".
     *
     * Requires @supabase/supabase-js >= 2.74.0 (realtime-js's `private`
     * channel option; verified absent below that — see this module's own
     * import comment and docs/notification-center-plan.md §2/§7 step 4a).
     *
     * `onMessage(payload)` fires on every broadcast; `onStatusChange(status)`
     * fires on every `.subscribe()` status transition, INCLUDING the first
     * — handlers.js reconciles with a fresh `fetchActive` on every
     * `SUBSCRIBED`, not just reconnects, so a channel that only just
     * finished authorizing does not miss whatever was sent while it was
     * still connecting.
     */
    subscribe(userId, { onMessage, onStatusChange } = {}) {
      this.unsubscribe();
      if (!Services.supabase || !userId) return null;

      const topic = `notify:user:${userId}`;
      this._channel = Services.supabase
        .channel(topic, { config: { private: true } })
        .on('broadcast', { event: 'notify' }, ({ payload }) => onMessage?.(payload))
        .subscribe((status) => onStatusChange?.(status));
      return this._channel;
    },

    /** Torn down on sign-out and whenever the tab goes hidden (Page
     * Visibility) — re-established, with its own fresh reconcile fetch, on
     * sign-in or the tab becoming visible again. See handlers.js. */
    unsubscribe() {
      if (this._channel && Services.supabase) {
        Services.supabase.removeChannel(this._channel);
      }
      this._channel = null;
    },

    _channel: null,
  },
};
