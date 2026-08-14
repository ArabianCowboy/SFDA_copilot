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

export function createAdminServices(token) {
  if (!token) throw new Error('createAdminServices requires a bearer token');

  async function request(path, { method = 'GET', body } = {}) {
    const response = await fetch(`/admin/api/${path}`, {
      method,
      headers: { ...JSON_HEADERS, Authorization: `Bearer ${token}` },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

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
  };
}
