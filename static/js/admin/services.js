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

  async function send(path, method, body, token) {
    return fetch(`/admin/api/${path}`, {
      method,
      headers: { ...JSON_HEADERS, Authorization: `Bearer ${token}` },
      body: body === undefined ? undefined : JSON.stringify(body),
      // The gate answers JSON for every /admin/api/* route, so a redirect here
      // would mean something upstream intercepted us. Following it would turn a
      // login page into a parsed-as-null success.
      redirect: 'error',
    });
  }

  async function request(path, { method = 'GET', body } = {}) {
    let response = await send(path, method, body, await getToken());

    // One retry, and only on 401. A token that expired between resolution and
    // arrival is the ordinary case here; anything else repeated would just be
    // sending a rejected request twice.
    if (response.status === 401) {
      const refreshed = await getToken();
      if (refreshed) response = await send(path, method, body, refreshed);
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
        response.status, payload?.error, payload?.message, payload?.errors,
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
    users: ({ limit = 50, offset = 0, q = '' } = {}) =>
      request(`users?limit=${limit}&offset=${offset}&q=${encodeURIComponent(q)}`),

    /** Change a role or chat access. Refusals arrive as 409 with a code. */
    setUserFlags: (id, patch) =>
      request(`users/${encodeURIComponent(id)}`, { method: 'PATCH', body: patch }),

    /** Recorded actions, newest first. Paginated server-side. */
    audit: ({ limit = 50, offset = 0 } = {}) =>
      request(`audit?limit=${limit}&offset=${offset}`),
  };
}
