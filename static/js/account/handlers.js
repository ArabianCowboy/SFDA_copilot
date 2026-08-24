/**
 * SFDA Copilot — Account page event handlers
 *
 * Identity is explicit-save and dirty-guarded; Preferences is instant-apply.
 * The two forms are deliberately not the same shape — see
 * docs/profile-refactor-plan.md §3's per-section state contract.
 */

import { Services } from '../modules/services.js';
import { ThemeManager } from '../modules/theme.js';
import { I18n } from '../modules/i18n.js';
import {
  readIdentityForm,
  setIdentityDirty,
  setIdentitySaving,
  showIdentitySaved,
  showIdentityError,
  clearIdentityNotes,
  showPreferencesSaved,
  showPreferencesError,
  clearPasswordNotes,
  setPasswordSaving,
  showReauthStep,
  showPasswordSaved,
  showPasswordError,
  setSignOutOthersSaving,
  showSignOutOthersSaved,
  showSignOutOthersError,
  setExportSaving,
  showExportSaved,
  showExportError,
  setDeleteAllSaving,
  showDeleteAllSaved,
  showDeleteAllError,
  showConsentState,
  showConsentSaved,
  showConsentError,
} from './ui.js';

const el = (id) => document.getElementById(id);

function isDirty(form) {
  const snapshot = form.dataset.snapshot;
  if (!snapshot) return false;
  return JSON.stringify(readIdentityForm()) !== snapshot;
}

/** Wire the Identity form: dirty tracking, explicit save, re-snapshot after. */
export function bindIdentityForm(getUserId) {
  const form = el('identity-form');
  if (!form) return;

  form.addEventListener('input', () => {
    clearIdentityNotes();
    setIdentityDirty(isDirty(form));
  });

  // Guarded dismissal (docs/profile-refactor-plan.md §3's per-section state
  // contract): a reader who typed a correction and then closed the tab
  // should be asked, not silently lose it. Preferences carries no such
  // guard — it never has unsaved state, by design (instant-apply).
  window.addEventListener('beforeunload', (event) => {
    if (!isDirty(form)) return;
    event.preventDefault();
    event.returnValue = '';
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const userId = getUserId();
    if (!userId) return;

    setIdentitySaving(true);
    clearIdentityNotes();
    try {
      const updates = readIdentityForm();
      await Services.updateProfile(userId, updates);
      form.dataset.snapshot = JSON.stringify(updates);
      showIdentitySaved();
    } catch (error) {
      console.error('[SFDA Copilot account] identity save failed', error);
      showIdentityError();
    } finally {
      // setIdentitySaving(false) turns the disabled attribute back on for
      // its own reason (no longer mid-request) — re-derive dirty state
      // after it, or a failed save (still dirty) would come back enabled by
      // coincidence and a successful one (no longer dirty) would too.
      setIdentitySaving(false);
      setIdentityDirty(isDirty(form));
    }
  });
}

/**
 * "System" resolves to the OS preference at the moment it is chosen, the
 * same one-shot resolution every page's own FOUC-prevention script already
 * does when no explicit theme is stored — this is not a weaker version of
 * that behaviour, it is the same one, reachable from a control instead of
 * only from a first visit.
 */
function resolveTheme(choice) {
  if (choice === 'system') {
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return choice;
}

/** Wire the theme radios: instant apply, instant persist. */
export function bindThemeChoice() {
  const row = el('theme-choice-row');
  if (!row) return;

  row.addEventListener('change', async (event) => {
    const choice = event.target?.value;
    if (!choice) return;

    ThemeManager.apply(resolveTheme(choice));
    try {
      await Services.updateOwnPreferences({ theme: choice });
      showPreferencesSaved();
    } catch (error) {
      console.error('[SFDA Copilot account] theme preference save failed', error);
      showPreferencesError();
    }
  });
}

/**
 * Wire the language radios: I18n.set() reloads the page (deliberately — see
 * that module's own docstring), so the preference is written first and the
 * reload carries the account page straight back to itself.
 */
export function bindLanguageChoice() {
  const row = el('language-choice-row');
  if (!row) return;

  row.addEventListener('change', async (event) => {
    const choice = event.target?.value;
    if (!choice || choice === I18n.lang) return;

    try {
      await Services.updateOwnPreferences({ language: choice });
    } catch (error) {
      // Not fatal to the language switch itself — the reload still honours
      // the reader's choice locally even if the server-side mirror failed.
      console.error('[SFDA Copilot account] language preference save failed', error);
    }
    I18n.set(choice);
  });
}

/**
 * Map a GoTrue error to which `runtime.profile.account.passwordError*` key
 * to show. Matched on `.message` text, not a `.code` field.
 *
 * Originally because the pinned @supabase/supabase-js@2.39.7 (->
 * gotrue-js@2.62.2) threw AuthApiError with only `{message, status}` — the
 * server's own `error_code` field was read into nothing and never reached
 * the client at all. Upgraded to 2.74.0 (2026-08-24; auth-js's `error_code`
 * support landed in 2.63.0), which DOES populate `.code` now — but this is
 * left as substring matching rather than switched to it: every string
 * checked below is matched against GoTrue's own English error prose, which
 * still needs to work regardless of whether a future response happens to
 * carry a structured code, and rewriting a working classifier on an
 * unrelated SDK bump is exactly the kind of untested scope creep this
 * upgrade was deliberately kept narrow to avoid. Same defensive
 * substring-matching convention as `ErrorHandler.formatAuthError` (dom.js)
 * uses for the same reason.
 */
function classifyPasswordError(error) {
  const message = (error?.message || '').toLowerCase();
  // Checked before the general "reauthenticat" match below: a rejected code
  // ("...code is not valid") also contains that substring, and must not be
  // read as "start the flow" a second time — it already was started.
  if (message.includes('not valid') || message.includes('incorrect')) return 'passwordErrorReauth';
  if (message.includes('reauthenticat')) return 'reauth-needed';
  if (message.includes('weak')) return 'passwordErrorWeak';
  if (message.includes('same') || message.includes('different from')) return 'passwordErrorSame';
  if (message.includes('session') || message.includes('expired')) return 'passwordErrorSession';
  return 'passwordErrorGeneric';
}

/**
 * Wire the password-change form.
 *
 * No current-password field — GoTrue has none. The reauthentication step is
 * asked for only when the server actually demands it (a session older than
 * the project's "recently logged in" window, when that setting is on):
 * the form tries a bare `updateUser({ password })` first, and only on a
 * `reauthentication_needed`-shaped refusal does it call `reauthenticate()`
 * (sending the reader an emailed code) and reveal the code field for a
 * second submit.
 */
export function bindPasswordForm() {
  const form = el('password-form');
  if (!form) return;

  // Set once reauthenticate() has actually sent a code, so the second
  // submit knows to include the nonce the reader was just asked for.
  let awaitingNonce = false;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const password = el('password-new')?.value;
    if (!password) return;

    setPasswordSaving(true);
    clearPasswordNotes();
    try {
      const nonce = awaitingNonce ? el('password-nonce')?.value?.trim() : null;
      await Services.updateOwnPassword(password, nonce);
      awaitingNonce = false;
      showPasswordSaved();

      // OWASP's Forgot/Change Password guidance: every OTHER session should
      // end on a password change. This device's own session is left alone —
      // the reader is using it right now to make the change.
      try {
        await Services.signOutOtherSessions();
      } catch (revokeError) {
        console.error(
          '[SFDA Copilot account] could not revoke other sessions after password change',
          revokeError,
        );
      }
    } catch (error) {
      const classification = classifyPasswordError(error);
      if (classification === 'reauth-needed') {
        try {
          await Services.reauthenticate();
          awaitingNonce = true;
          showReauthStep();
        } catch (reauthError) {
          console.error('[SFDA Copilot account] reauthenticate() failed', reauthError);
          showPasswordError('passwordErrorGeneric');
        }
      } else {
        console.error('[SFDA Copilot account] password change failed', error);
        showPasswordError(classification);
      }
    } finally {
      setPasswordSaving(false);
    }
  });
}

/** Wire "Sign out everywhere else" — ends every session but this one. */
export function bindSignOutOthers() {
  const button = el('sign-out-others');
  if (!button) return;

  button.addEventListener('click', async () => {
    setSignOutOthersSaving(true);
    try {
      await Services.signOutOtherSessions();
      showSignOutOthersSaved();
    } catch (error) {
      console.error('[SFDA Copilot account] sign-out-others failed', error);
      showSignOutOthersError();
    } finally {
      setSignOutOthersSaving(false);
    }
  });
}

/**
 * Wire the marketing-consent toggle — instant-apply, like theme/language,
 * matching docs/profile-refactor-plan.md §12.3's "withdrawal must be as
 * easy as granting". A direct browser->Postgres write under RLS
 * (Services.updateProfile, the same path the Identity form uses for its
 * own top-level columns), never a Flask route — which is also why this is
 * never rate-limited: there is no route in front of it to limit.
 *
 * Granting sends the policy version/language/surface the guard trigger
 * requires (profiles_set_marketing_consent_record); withdrawing sends only
 * `marketing_consent: false` and, if the reader also ticked "also clear my
 * age", `age: null` in the same write — never a mandate, per T9.
 */
export function bindConsentToggle(getUserId) {
  const toggle = el('consent-marketing-toggle');
  if (!toggle) return;

  toggle.addEventListener('change', async () => {
    const userId = getUserId();
    if (!userId) return;

    const granted = toggle.checked;
    showConsentState(granted);
    el('consent-saved-note')?.setAttribute('hidden', '');
    el('consent-error')?.setAttribute('hidden', '');

    const updates = granted
      ? {
          marketing_consent: true,
          marketing_consent_policy_version: window.__POLICY_VERSION,
          marketing_consent_language: I18n.lang,
          marketing_consent_surface: 'account',
        }
      : {
          marketing_consent: false,
          ...(el('consent-clear-age')?.checked ? { age: null } : {}),
        };

    try {
      await Services.updateProfile(userId, updates);
      if (!granted && el('consent-clear-age')) el('consent-clear-age').checked = false;
      showConsentSaved();
    } catch (error) {
      console.error('[SFDA Copilot account] consent save failed', error);
      // Revert the control to the state it actually holds server-side —
      // an unreverted checkbox after a failed write would show a consent
      // that was never recorded.
      toggle.checked = !granted;
      showConsentState(!granted);
      showConsentError();
    }
  });
}

/**
 * Wire "Export my conversations" — downloads the full history as NDJSON via
 * a synthetic, in-memory anchor click (the browser download primitive; the
 * file never touches this module's own state).
 */
export function bindExportConversations() {
  const button = el('export-conversations');
  if (!button) return;

  button.addEventListener('click', async () => {
    setExportSaving(true);
    el('export-note')?.setAttribute('hidden', '');
    el('export-error')?.setAttribute('hidden', '');
    try {
      const result = await Services.exportConversations();
      if (!result) return; // Signed out mid-click — nothing to download.
      const url = URL.createObjectURL(result.blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = result.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      showExportSaved();
    } catch (error) {
      console.error('[SFDA Copilot account] export failed', error);
      showExportError();
    } finally {
      setExportSaving(false);
    }
  });
}

/**
 * Wire "Delete all conversations" — a native confirm() first, matching
 * admin/handlers.js's own convention for a destructive action of this
 * severity (revoke sessions, disable an account).
 */
export function bindDeleteAllConversations() {
  const button = el('delete-all-conversations');
  if (!button) return;

  button.addEventListener('click', async () => {
    if (!window.confirm(I18n.t('profile.account.deleteAllConfirm'))) return;

    setDeleteAllSaving(true);
    el('delete-all-note')?.setAttribute('hidden', '');
    el('delete-all-error')?.setAttribute('hidden', '');
    try {
      await Services.deleteAllConversations();
      showDeleteAllSaved();
    } catch (error) {
      console.error('[SFDA Copilot account] bulk delete failed', error);
      const key = error?.code === 'generation_in_flight' ? 'deleteAllInFlight' : 'deleteAllFailed';
      showDeleteAllError(key);
    } finally {
      setDeleteAllSaving(false);
    }
  });
}
