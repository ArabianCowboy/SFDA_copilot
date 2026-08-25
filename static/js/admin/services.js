/**
 * SFDA Copilot — Console transport
 *
 * Fetch only. No DOM, no app state, no user-facing strings — the same contract
 * `modules/services.js` is held to, and asserted by test_frontend_architecture.
 * A failure here is thrown, not displayed; `admin/handlers.js` decides what a
 * person is told about it.
 *
 * The bearer token is passed in rather than resolved here. Obtaining it means
 * asking the Supabase client, which lives in `modules/services.js` — and
 * reaching for it from this file would be the first step toward this module
 * knowing about sessions, which is precisely what it must not know.
 */

const JSON_HEADERS = { 'Content-Type': 'application/json' };

/**
 * An error that survives the boundary with its status intact.
 *
 * `handlers.js` needs to tell "you are not an administrator" (403) from "your
 * token expired" (401) from "the server broke" (5xx), and a bare
 * `new Error(message)` flattens all three into a string nobody can branch on
 * without matching prose.
 */
export class AdminRequestError extends Error {
  constructor(status, code, message, errors) {
    super(message || code || `Request failed (${status})`);
    this.name = 'AdminRequestError';
    this.status = status;
    this.code = code;
    /** Per-field validation failures, when the server sent any. */
    this.errors = errors || [];
  }
}

/**
 * @param getToken async () => string|null — resolved PER REQUEST, not once.
 *
 * A provider rather than a token, because Supabase refreshes the underlying
 * session while the console stays open. Capturing one string at init meant a
 * tab left open past expiry kept presenting a token the server had stopped
 * accepting, and only a reload fixed it — on the surface an operator is most
 * likely to leave open.
 */
export function createAdminServices(getToken) {
  if (typeof getToken !== 'function') {
    throw new Error('createAdminServices requires a token provider');
  }

  async function send(path, method, body, token, signal) {
    return fetch(`/admin/api/${path}`, {
      method,
      headers: { ...JSON_HEADERS, Authorization: `Bearer ${token}` },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      // The gate answers JSON for every /admin/api/* route, so a redirect here
      // would mean something upstream intercepted us. Following it would turn a
      // login page into a parsed-as-null success.
      redirect: 'error',
    });
  }

  async function request(path, { method = 'GET', body, signal } = {}) {
    let response = await send(path, method, body, await getToken(), signal);

    // One retry on 401. A token that expired between resolution and arrival is
    // the ordinary case here, and the gate answers 401 before any route body
    // runs, so re-sending cannot repeat work that already happened.
    if (response.status === 401) {
      const refreshed = await getToken();
      if (refreshed) response = await send(path, method, body, refreshed, signal);
    }

    /* One retry on 503, and only for GET.
       The server used to answer 401 when it could not REACH the identity
       provider, so a transient blip was quietly absorbed by the retry above and
       looked like nothing had happened. It now answers 503, which is truthful —
       and would have turned that same blip into a visible failure had this not
       been added.

       Narrower than the 401 retry on purpose. A 401 provably precedes the route
       body; a 503 does not — `storage_unavailable` is returned by routes that
       have already begun work. Re-sending a PATCH or POST on one would be a
       second attempt at a mutation nobody asked for twice, and this console can
       send a password-reset email. A GET cannot have that problem. */
    if (response.status === 503 && method === 'GET') {
      response = await send(path, method, body, await getToken(), signal);
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch {
      /* A gateway or proxy can return HTML on an error. Falling through with a
         null payload keeps the status, which is the part worth branching on. */
    }

    if (!response.ok) {
      throw new AdminRequestError(
        response.status,
        payload?.error,
        payload?.message,
        payload?.errors,
      );
    }
    return payload;
  }

  return {
    /** Confirms the caller is an administrator. Reaching it at all is the answer. */
    identity: () => request('identity'),

    /** Effective settings, which of them are overrides, and the model allowlist. */
    settings: () => request('settings'),

    /**
     * Apply a patch. A key set to null is removed, reverting to the deployed
     * default — which is not the same as writing the default's current value,
     * because that would pin it against a future deploy.
     *
     * A 422 arrives as an AdminRequestError carrying `errors`, so the caller
     * can put each one beside the field it belongs to instead of stacking
     * prose at the top of a form.
     */
    saveSettings: (patch) => request('settings', { method: 'PUT', body: patch }),

    /** Accounts and their standing. */
    users: ({ limit = 50, offset = 0, q = '', signal } = {}) =>
      request(`users?limit=${limit}&offset=${offset}&q=${encodeURIComponent(q)}`, { signal }),

    /** Change a role or chat access. Refusals arrive as 409 with a code. */
    setUserFlags: (id, patch) =>
      request(`users/${encodeURIComponent(id)}`, { method: 'PATCH', body: patch }),

    /** Send this account a recovery link. Returns no link, by design. */
    sendPasswordReset: (id) =>
      request(`users/${encodeURIComponent(id)}/reset-password`, { method: 'POST' }),

    /** End every session this account holds. Returns no credential, by design. */
    revokeSessions: (id) =>
      request(`users/${encodeURIComponent(id)}/revoke-sessions`, { method: 'POST' }),

    /** Set a new email immediately. No confirmation step exists on this path. */
    changeEmail: (id, email) =>
      request(`users/${encodeURIComponent(id)}/change-email`, { method: 'POST', body: { email } }),

    /** Rewrite the three profile fields an operator may touch. */
    updateProfile: (id, patch) =>
      request(`users/${encodeURIComponent(id)}/profile`, { method: 'PATCH', body: patch }),

    /** One account in full. 404 when there is no such account. */
    user: (id) => request(`users/${encodeURIComponent(id)}`),

    /**
     * Recorded actions, newest first. Paginated server-side.
     *
     * `targetType`/`targetId` narrow it to one account, which is the same query
     * with a filter rather than a second endpoint — "what has happened to this
     * person" had no surface at all before the detail view.
     */
    audit: ({ limit = 50, offset = 0, targetType = '', targetId = '' } = {}) => {
      const query = new URLSearchParams({ limit, offset });
      if (targetType) query.set('target_type', targetType);
      if (targetId) query.set('target_id', targetId);
      return request(`audit?${query}`);
    },

    /**
     * Notification Center (docs/notification-center-plan.md). Dry run: how
     * many accounts one targeting choice would currently reach. Persists
     * nothing — the composer calls this on every field change.
     */
    notificationAudiencePreview: (targeting) =>
      request('notifications/audience-preview', { method: 'POST', body: targeting }),

    /**
     * Send a broadcast. `payload.client_request_id` makes a retry of the
     * SAME submission idempotent — see the composer's own resend/retry
     * handling. A 409 `idempotency_conflict` means the same id was already
     * used for different content; a 201/200 response carries the sent row.
     */
    createNotification: (payload) => request('notifications', { method: 'POST', body: payload }),

    /** Offset/limit, matching users()/audit() above — only the reader-facing
     * inbox uses cursor pagination (docs/notification-center-plan.md §3). */
    notificationHistory: ({ limit = 20, offset = 0, status = 'all' } = {}) =>
      request(`notifications/history?limit=${limit}&offset=${offset}&status=${status}`),

    deactivateNotification: (id) =>
      request(`notifications/${encodeURIComponent(id)}/deactivate`, { method: 'POST' }),

    /** Soft delete. Preserves recipient/read history for audit review. */
    deleteNotification: (id) =>
      request(`notifications/${encodeURIComponent(id)}`, { method: 'DELETE' }),

    /** Permanent erasure — only valid on an already-Deleted row. */
    purgeNotification: (id) =>
      request(`notifications/${encodeURIComponent(id)}/purge`, { method: 'POST' }),

    getPurgeRetentionDays: () => request('notifications/purge-settings'),

    setPurgeRetentionDays: (days) =>
      request('notifications/purge-settings', {
        method: 'PUT',
        body: { purge_retention_days: days },
      }),
  };
}
