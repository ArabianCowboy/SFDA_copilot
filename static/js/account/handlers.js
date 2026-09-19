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
  showDeletionPending,
  showDeletionInProgress,
  showDeletionForm,
  showDeletionAdminNote,
  setDeletionSaving,
  setDeletionCancelling,
  showDeletionError,
  showDeletionRequested,
  showDeletionCancelSaved,
  showDeletionCancelError,
} from './ui.js';

const el = (id) => document.getElementById(id);

// Stands down the dirty-form guard when the session ends elsewhere and a forced reload occurs.
let forcedReload = false;

/** The session ended: the page is about to reload into its signed-out state,
 *  and edits to a record that is no longer this reader's cannot be saved. Lets
 *  the dirty-form guard below stand down for that one reload only. */
export function allowForcedReload() {
  forcedReload = true;
}

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
    if (forcedReload) return;
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
 * easy as granting".
 *
 * Granting goes through `POST /account/api/consent/grant`
 * (Services.grantMarketingConsent), so the policy version is stamped
 * server-side — the browser no longer sends `marketing_consent_policy_version`
 * at all. Withdrawing goes browser-direct to `update_own_marketing_consent`
 * (Services.withdrawMarketingConsent), which is withdrawal-only by
 * construction and stays reachable for a disabled account past the frozen
 * profiles UPDATE policy; the "also clear my age" offer rides that RPC's
 * `p_clear_age` parameter rather than a second write — never a mandate, per
 * T9. A disabled account may never grant: the grant route's `_gate` refuses
 * it before the view runs.
 */
export function bindConsentToggle() {
  const toggle = el('consent-marketing-toggle');
  if (!toggle) return;

  toggle.addEventListener('change', async () => {
    const granted = toggle.checked;
    showConsentState(granted);
    el('consent-saved-note')?.setAttribute('hidden', '');
    el('consent-error')?.setAttribute('hidden', '');

    try {
      if (granted) {
        // `sessionRequest` resolves null (rather than throwing) when nobody
        // is signed in — a null grant is a grant that never happened.
        const result = await Services.grantMarketingConsent({
          language: I18n.lang,
          surface: 'account',
        });
        if (!result) throw new Error('Consent grant did not complete.');
      } else {
        await Services.withdrawMarketingConsent(el('consent-clear-age')?.checked === true);
      }
      if (!granted && el('consent-clear-age')) el('consent-clear-age').checked = false;
      showConsentSaved();
    } catch (error) {
      console.error('[SFDA Copilot account] consent save failed', error);
      // Revert the control to the state it actually holds server-side —
      // an unreverted checkbox after a failed write would show a consent
      // that was never recorded.
      toggle.checked = !granted;
      showConsentState(!granted);
      // DL007 (supabase/pending/14): the grant direction stays closed while
      // a deletion saga is live. The reader is told why, not shown an
      // outage — withdrawing stays available throughout.
      showConsentError(
        granted && error?.code === 'deletion_pending'
          ? 'consentGrantPendingDeletion'
          : 'consentFailed',
      );
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

/**
 * The saga states whose writes are frozen (supabase/pending/08's narrow
 * predicate): the request form must not show again for these, and neither
 * the cancel button nor the 30-day claim applies. Rendered as the
 * deletion-in-progress view instead.
 */
const FROZEN_DELETION_STATES = new Set(['purging', 'auth_delete_begun', 'failed']);

/**
 * Wire self-serve account deletion (docs/account-and-trust-plan.md §3-M4/M5).
 *
 * The section opens by asking `/account/api/deletion` for the caller's own
 * status: pending shows the grace banner (deadline + cancel), a frozen state
 * shows the in-progress view (no form, no cancel, no 30-day claim), anything
 * else shows the request form, and an administrator sees neither — the saga
 * refuses them server-side (DL003) and the form would only invite a refusal.
 *
 * The request button arms only when the confirmation field holds the exact
 * localized word the server rendered into `data-confirm-word` AND a password
 * is present. Both are re-checked server-side — the arming is an affordance,
 * not a gate — and the password is verified there as step-up, never logged
 * (see web/api/account.py).
 *
 * While the self-serve deploy switch is off the server renders no deletion
 * section at all; every lookup below then finds nothing and this returns
 * before the status read, so no 404 noise is produced.
 */
export function bindDeletionSection({ isAdmin = false } = {}) {
  const section = el('deletion-form') || el('deletion-pending') || el('deletion-inprogress');
  if (!section) return;
  const form = el('deletion-form');
  const confirmInput = el('deletion-confirm');
  const passwordInput = el('deletion-password');
  const requestButton = el('deletion-request');
  const cancelButton = el('deletion-cancel');

  const expectedWord = confirmInput?.dataset.confirmWord || '';

  const deriveArmed = () => {
    if (!requestButton) return;
    const wordOk = (confirmInput?.value.trim() || '') === expectedWord && expectedWord !== '';
    const passwordOk = (passwordInput?.value || '') !== '';
    requestButton.disabled = !(wordOk && passwordOk);
  };

  confirmInput?.addEventListener('input', deriveArmed);
  passwordInput?.addEventListener('input', deriveArmed);

  async function refresh() {
    const status = await Services.getDeletionStatus().catch((error) => {
      console.error('[SFDA Copilot account] deletion status failed', error);
      // The form is already visible by default; only the banner needs a
      // state. A failed status read leaves whatever is showing in place.
      return null;
    });
    if (!status) return; // Signed out mid-click, or the read above failed.
    if (isAdmin) {
      showDeletionAdminNote();
      return;
    }
    if (status.pending) {
      showDeletionPending(status.grace_until);
    } else if (FROZEN_DELETION_STATES.has(status.state)) {
      showDeletionInProgress();
    } else {
      showDeletionForm();
      deriveArmed();
    }
  }

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const confirmation = confirmInput?.value.trim() || '';
    const password = passwordInput?.value || '';
    if (!confirmation || !password) return;

    setDeletionSaving(true);
    el('deletion-note')?.setAttribute('hidden', '');
    el('deletion-error')?.setAttribute('hidden', '');
    try {
      const result = await Services.requestAccountDeletion({ password, confirmation });
      if (passwordInput) passwordInput.value = '';
      // A replay of an already-in-progress (frozen) saga returns the row
      // without re-running sign-out (web/api/account.py): the 30-day
      // "requested" toast would be a lie for that state, so refresh into
      // the in-progress view with no toast instead.
      if (!result || result.state === 'pending' || !FROZEN_DELETION_STATES.has(result.state)) {
        showDeletionRequested();
      }
      await refresh();
    } catch (error) {
      console.error('[SFDA Copilot account] deletion request failed', error);
      showDeletionError(mapDeletionError(error, 'request'));
    } finally {
      setDeletionSaving(false);
      deriveArmed();
    }
  });

  // Cancelling restores nothing and destroys nothing, so it is one click
  // with no confirm dialog — the safe direction needs no second gate.
  cancelButton?.addEventListener('click', async () => {
    setDeletionCancelling(true);
    el('deletion-cancel-note')?.setAttribute('hidden', '');
    el('deletion-cancel-error')?.setAttribute('hidden', '');
    try {
      await Services.cancelAccountDeletion();
      showDeletionCancelSaved();
      await refresh();
    } catch (error) {
      console.error('[SFDA Copilot account] deletion cancel failed', error);
      showDeletionCancelError(mapDeletionError(error, 'cancel'));
    } finally {
      setDeletionCancelling(false);
    }
  });

  refresh();
}

/** The server's machine code for a deletion failure, to a runtime string key. */
function mapDeletionError(error, kind) {
  const code = error?.code;
  if (code === 'step_up_failed') return 'deletionStepUpFailed';
  if (code === 'step_up_locked_out') return 'deletionStepUpLockedOut';
  if (code === 'deletion_unavailable_for_admin') return 'deletionAdminRefused';
  if (code === 'already_deleted') return 'deletionAlreadyDeleted';
  if (code === 'cancel_unavailable') return 'deletionCancelUnavailable';
  return kind === 'cancel' ? 'deletionCancelFailed' : 'deletionRequestFailed';
}
