/**
 * SFDA Copilot — Account page rendering
 *
 * Pure DOM writes. Nothing here decides what to fetch or when — app.js and
 * handlers.js own that; this module only draws what it is told.
 */

import { I18n } from '../modules/i18n.js';
import { countryName, readCountrySelect } from '../modules/countries.js';

const el = (id) => document.getElementById(id);

/* ── Gate states ─────────────────────────────────────────────────────────── */

export function showRecord() {
  el('account-gate')?.setAttribute('hidden', '');
  el('account-signed-out')?.setAttribute('hidden', '');
  el('account-record')?.removeAttribute('hidden');
}

export function showSignedOut() {
  el('account-gate')?.setAttribute('hidden', '');
  el('account-record')?.setAttribute('hidden', '');
  el('account-signed-out')?.removeAttribute('hidden');
}

export function showLoadFailed() {
  const gate = el('account-gate');
  if (!gate) return;
  const text = gate.querySelector('.account-gate-text');
  if (text) text.textContent = I18n.t('profile.account.loadFailed');
  el('account-gate-retry')?.classList.remove('d-none');
}

/* ── Monogram ────────────────────────────────────────────────────────────── */

/**
 * Two initials, by grapheme rather than by UTF-16 code unit or byte.
 * `String.prototype[0]` can split a surrogate pair or a combining mark in
 * two; `Intl.Segmenter` (broadly supported in current engines) does not.
 * Falls back to a plain code-point slice where it is unavailable.
 */
function graphemes(text, count) {
  if (!text) return '';
  if (typeof Intl !== 'undefined' && Intl.Segmenter) {
    const segmenter = new Intl.Segmenter(I18n.lang, { granularity: 'grapheme' });
    const parts = [...segmenter.segment(text)].map((s) => s.segment);
    return parts.slice(0, count).join('');
  }
  return [...text].slice(0, count).join('');
}

function monogramFrom(profile, email) {
  const first = graphemes((profile?.first_name || '').trim(), 1);
  const family = graphemes((profile?.family_name || '').trim(), 1);
  if (first || family) return (first + family).toUpperCase();
  // No name on record. The email's own first grapheme is a real fact about
  // the account rather than a placeholder glyph — a "?" would look like
  // something failed to load.
  return graphemes((email || '').trim(), 1).toUpperCase();
}

/* ── Record head ─────────────────────────────────────────────────────────── */

export function renderRecordHead(profile, user) {
  const monogram = el('account-monogram');
  if (monogram) monogram.textContent = monogramFrom(profile, user?.email);

  const heading = el('account-heading');
  if (heading) heading.textContent = profile?.full_name || user?.email || '';

  const email = el('account-email');
  if (email) email.textContent = user?.email || '';
}

/* ── Standing line ───────────────────────────────────────────────────────── */

/**
 * A date, built from parts rather than `toLocaleDateString('ar')` — that
 * call embeds U+200F marks that bidi reorders even inside a directional
 * isolate (docs/archive/2026-08-23_profile-refactor.md §7.2).
 *
 * Exported for the deletion banner, which interpolates a grace deadline the
 * same way the standing line interpolates its dates.
 */
export function formatSince(isoString) {
  if (!isoString) return '—';
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return '—';
  const parts = new Intl.DateTimeFormat(I18n.lang, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  }).formatToParts(date);
  return parts.map((p) => p.value).join('');
}

export function renderStanding({ tier, isAdmin, isDisabled, createdAt, conversationCount, quota }) {
  const roleEl = el('standing-role');
  if (roleEl)
    roleEl.textContent = I18n.t(isAdmin ? 'profile.account.roleAdmin' : 'profile.account.roleUser');

  const tierEl = el('standing-tier');
  if (tierEl) {
    /* The label comes from the DATABASE, not the catalogue. An operator who
       creates a tier in the console cannot add a key to web/i18n/*.yaml, so
       tier labels are data (tiers.label_en / label_ar) and this picks the one
       matching the reader's language. Falls back to the key, then to the old
       catalogue strings, so the line still renders if the quota lookup failed. */
    const label = I18n.lang === 'ar' ? quota?.tier?.label_ar : quota?.tier?.label_en;
    tierEl.textContent =
      label ||
      quota?.tier?.key ||
      (tier === 'staff' ? I18n.t('profile.account.tierStaff') : I18n.t('profile.account.tierFree'));
  }

  const quotaEl = el('standing-quota');
  if (quotaEl) {
    quotaEl.textContent = '';
    if (!quota || typeof quota.limit !== 'number') {
      quotaEl.textContent = '—';
    } else {
      const used = document.createElement('span');
      used.textContent = I18n.t('profile.account.quotaToday', {
        used: quota.used,
        limit: quota.limit,
      });
      quotaEl.append(used);

      /* A WINDOWED override is told to the reader (owner decision, 2026-09-03).
         On the morning it ends their allowance silently drops back to the tier's
         number, and a reader who was never told it was temporary reads that as a
         bug and opens a ticket. No line at all when the override is open-ended
         or absent — there is no date to promise. */
      if (quota.override_expires_at) {
        const until = document.createElement('div');
        const when = document.createElement('time');
        when.setAttribute('datetime', quota.override_expires_at);
        when.setAttribute('dir', 'auto');
        when.textContent = formatSince(quota.override_expires_at);
        const parts = I18n.t('profile.account.quotaUntil', {
          limit: quota.limit,
          date: '\0',
        }).split('\0');
        until.append(document.createTextNode(parts[0] || ''), when);
        if (parts[1]) until.append(document.createTextNode(parts[1]));
        quotaEl.append(until);
      } else if (quota.resets_at) {
        const resets = document.createElement('div');
        resets.textContent = I18n.t('profile.account.quotaResets', {
          resets_at: formatSince(quota.resets_at),
        });
        quotaEl.append(resets);
      }
    }
  }

  const sinceEl = el('standing-since');
  if (sinceEl) sinceEl.textContent = formatSince(createdAt);

  const conversationsEl = el('standing-conversations');
  if (conversationsEl) {
    conversationsEl.textContent =
      conversationCount == null
        ? '—'
        : I18n.plural(
            conversationCount,
            'profile.account.conversationOne',
            'profile.account.conversations',
          );
  }

  const statusEl = el('standing-status');
  if (statusEl) {
    statusEl.textContent = I18n.t(
      isDisabled ? 'profile.account.standingDisabled' : 'profile.account.standingEnabled',
    );
  }
}

/* ── Identity form ───────────────────────────────────────────────────────── */

export function populateIdentityForm(profile) {
  const form = el('identity-form');
  if (!form || !profile) return;

  el('identity-first-name').value = profile.first_name || '';
  el('identity-family-name').value = profile.family_name || '';
  const country = el('identity-country');
  // A list that never loaded holds only "Not set"; show the saved Country
  // anyway (the select stays disabled, so it is still left out of the save).
  if (profile.country && ![...country.options].some((o) => o.value === profile.country)) {
    country.add(new Option(countryName(profile.country), profile.country));
  }
  country.value = profile.country || '';
  el('identity-age').value = profile.age ?? '';
  el('identity-organization').value = profile.organization || '';
  el('identity-specialization').value = profile.specialization || '';

  // The saved snapshot dirty tracking compares against — set once, on load,
  // never on save (handlers.js re-snapshots after a successful save).
  form.dataset.snapshot = JSON.stringify(readIdentityForm());
}

export function readIdentityForm() {
  return {
    first_name: el('identity-first-name')?.value.trim() || null,
    family_name: el('identity-family-name')?.value.trim() || null,
    // undefined (list not loaded) drops out of the upsert, leaving it as is.
    country: readCountrySelect(el('identity-country')),
    age: el('identity-age')?.value === '' ? null : Number(el('identity-age').value),
    organization: el('identity-organization')?.value.trim() || null,
    specialization: el('identity-specialization')?.value.trim() || null,
  };
}

export function setIdentityDirty(isDirty) {
  const save = el('identity-save');
  if (save) save.disabled = !isDirty;
}

export function setIdentitySaving(isSaving) {
  const save = el('identity-save');
  if (!save) return;
  save.disabled = isSaving;
  save.querySelector('.spinner-border')?.classList.toggle('d-none', !isSaving);
}

export function showIdentitySaved() {
  const note = el('identity-saved-note');
  if (note) {
    note.textContent = I18n.t('profile.account.identitySaved');
    note.hidden = false;
  }
  el('identity-error')?.setAttribute('hidden', '');
}

export function showIdentityError() {
  const error = el('identity-error');
  if (error) {
    error.textContent = I18n.t('profile.account.identitySaveFailed');
    error.hidden = false;
  }
}

export function clearIdentityNotes() {
  el('identity-saved-note')?.setAttribute('hidden', '');
  el('identity-error')?.setAttribute('hidden', '');
}

/* ── Preferences ─────────────────────────────────────────────────────────── */

export function populatePreferences(profile) {
  const theme = profile?.preferences?.theme || 'system';
  const themeInput =
    document.getElementById(`theme-choice-${theme}`) ||
    document.getElementById('theme-choice-system');
  if (themeInput) themeInput.checked = true;

  const langInput = document.getElementById(`language-choice-${I18n.lang}`);
  if (langInput) langInput.checked = true;
}

export function showPreferencesSaved() {
  const note = el('preferences-saved-note');
  if (note) {
    note.textContent = I18n.t('profile.account.preferencesSaved');
    note.hidden = false;
  }
  el('preferences-error')?.setAttribute('hidden', '');
  // A confirmation that never clears reads as stale advice on the next
  // visit; this one is allowed to fade because nothing was left half-done —
  // unlike the identity form's note, which stays until the next edit.
  clearTimeout(showPreferencesSaved._timer);
  showPreferencesSaved._timer = setTimeout(() => {
    if (note) note.hidden = true;
  }, 4000);
}

export function showPreferencesError() {
  const error = el('preferences-error');
  if (error) {
    error.textContent = I18n.t('profile.account.preferencesSaveFailed');
    error.hidden = false;
  }
}

/* ── Security: password ─────────────────────────────────────────────────── */

export function clearPasswordNotes() {
  el('password-saved-note')?.setAttribute('hidden', '');
  el('password-error')?.setAttribute('hidden', '');
}

export function setPasswordSaving(isSaving) {
  const save = el('password-save');
  if (!save) return;
  save.disabled = isSaving;
  save.querySelector('.spinner-border')?.classList.toggle('d-none', !isSaving);
}

/** Reveal the code field GoTrue just asked for, without treating the ask as
 *  an error — the form stays exactly as the reader left it otherwise. */
export function showReauthStep() {
  const step = el('password-reauth-step');
  if (step) step.hidden = false;
  const note = el('password-saved-note');
  if (note) {
    note.textContent = I18n.t('profile.account.passwordReauthSent');
    note.hidden = false;
  }
  el('password-nonce')?.focus();
}

export function showPasswordSaved() {
  const note = el('password-saved-note');
  if (note) {
    note.textContent = I18n.t('profile.account.passwordSaved');
    note.hidden = false;
  }
  el('password-error')?.setAttribute('hidden', '');
  // Done: the reauth step (if it was ever shown) has served its purpose and
  // should not linger for a reader who changes their password again later.
  const step = el('password-reauth-step');
  if (step) step.hidden = true;
  const form = el('password-form');
  form?.reset();
}

/** `key` selects which of the specific runtime.profile.account.passwordError*
 *  strings to show — see handlers.js for how a GoTrue error code maps to one. */
export function showPasswordError(key = 'passwordErrorGeneric') {
  const error = el('password-error');
  if (error) {
    error.textContent = I18n.t(`profile.account.${key}`);
    error.hidden = false;
  }
}

/* ── Security: sign out other sessions ──────────────────────────────────── */

export function setSignOutOthersSaving(isSaving) {
  const button = el('sign-out-others');
  if (button) button.disabled = isSaving;
}

export function showSignOutOthersSaved() {
  const note = el('sign-out-others-note');
  if (note) {
    note.textContent = I18n.t('profile.account.signOutOthersSaved');
    note.hidden = false;
  }
  el('sign-out-others-error')?.setAttribute('hidden', '');
}

export function showSignOutOthersError() {
  const error = el('sign-out-others-error');
  if (error) {
    error.textContent = I18n.t('profile.account.signOutOthersFailed');
    error.hidden = false;
  }
}

/* ── Consent (docs/ARCHITECTURE.md#account-page-and-profile; reasoning in
   docs/archive/2026-08-23_profile-refactor.md §12.3, Step 6) ──────────── */

export function populateConsent(profile) {
  const toggle = el('consent-marketing-toggle');
  if (toggle) toggle.checked = Boolean(profile?.marketing_consent);
  const clearAgeRow = el('consent-clear-age-row');
  if (clearAgeRow) clearAgeRow.hidden = !profile?.marketing_consent;
  showConsentState(Boolean(profile?.marketing_consent));
}

export function showConsentState(granted) {
  const note = el('consent-state-note');
  if (note)
    note.textContent = I18n.t(
      granted ? 'profile.account.consentGranted' : 'profile.account.consentNotGranted',
    );
  const clearAgeRow = el('consent-clear-age-row');
  if (clearAgeRow) clearAgeRow.hidden = !granted;
}

export function showConsentSaved() {
  const note = el('consent-saved-note');
  if (note) {
    note.textContent = I18n.t('profile.account.consentSaved');
    note.hidden = false;
  }
  el('consent-error')?.setAttribute('hidden', '');
  clearTimeout(showConsentSaved._timer);
  showConsentSaved._timer = setTimeout(() => {
    if (note) note.hidden = true;
  }, 4000);
}

export function showConsentError(key = 'consentFailed') {
  const error = el('consent-error');
  if (error) {
    error.textContent = I18n.t(`profile.account.${key}`);
    error.hidden = false;
  }
}

/* ── Your data: export & bulk delete ────────────────────────────────────── */

export function setExportSaving(isSaving) {
  const button = el('export-conversations');
  if (!button) return;
  button.disabled = isSaving;
  button.querySelector('.spinner-border')?.classList.toggle('d-none', !isSaving);
}

export function showExportSaved() {
  const note = el('export-note');
  if (note) {
    note.textContent = I18n.t('profile.account.exportStarted');
    note.hidden = false;
  }
  el('export-error')?.setAttribute('hidden', '');
}

export function showExportError() {
  const error = el('export-error');
  if (error) {
    error.textContent = I18n.t('profile.account.exportFailed');
    error.hidden = false;
  }
}

export function setDeleteAllSaving(isSaving) {
  const button = el('delete-all-conversations');
  if (!button) return;
  button.disabled = isSaving;
  button.querySelector('.spinner-border')?.classList.toggle('d-none', !isSaving);
}

export function showDeleteAllSaved() {
  const note = el('delete-all-note');
  if (note) {
    note.textContent = I18n.t('profile.account.deleteAllSaved');
    note.hidden = false;
  }
  el('delete-all-error')?.setAttribute('hidden', '');
}

/** `key` selects which runtime.profile.account.deleteAll* string to show —
 *  a generation-in-flight refusal reads differently from a genuine failure. */
export function showDeleteAllError(key = 'deleteAllFailed') {
  const error = el('delete-all-error');
  if (error) {
    error.textContent = I18n.t(`profile.account.${key}`);
    error.hidden = false;
  }
}

/* ── Delete account (docs/ARCHITECTURE.md#account-deletion-and-trust;
   reasoning in docs/archive/2026-09-18_account-and-trust.md §3-M4/M5) ── */

/** Render the pending banner and hide the request form, or the reverse. */
export function showDeletionPending(graceUntil) {
  el('deletion-form')?.setAttribute('hidden', '');
  el('deletion-inprogress')?.setAttribute('hidden', '');
  el('deletion-admin-note')?.setAttribute('hidden', '');
  const banner = el('deletion-pending');
  if (banner) banner.hidden = false;
  const body = el('deletion-pending-body');
  if (body) {
    body.textContent = I18n.t('profile.account.deletionPendingBody', {
      date: formatSince(graceUntil),
    });
  }
  el('deletion-cancel-error')?.setAttribute('hidden', '');
}

/**
 * Render the deletion-in-progress view: the saga is frozen (purging and
 * beyond), so there is no request form to show again, no cancel button to
 * offer, and no 30-day claim to make. Hides everything else in the section.
 */
export function showDeletionInProgress() {
  el('deletion-form')?.setAttribute('hidden', '');
  el('deletion-pending')?.setAttribute('hidden', '');
  el('deletion-admin-note')?.setAttribute('hidden', '');
  const banner = el('deletion-inprogress');
  if (banner) banner.hidden = false;
  const body = el('deletion-inprogress-body');
  if (body) {
    body.textContent = I18n.t('profile.account.deletionInProgressBody');
  }
}

export function showDeletionForm() {
  el('deletion-pending')?.setAttribute('hidden', '');
  el('deletion-inprogress')?.setAttribute('hidden', '');
  el('deletion-admin-note')?.setAttribute('hidden', '');
  el('deletion-form')?.removeAttribute('hidden');
}

/** Administrators cannot self-serve: the form hides, the note shows. */
export function showDeletionAdminNote() {
  el('deletion-form')?.setAttribute('hidden', '');
  el('deletion-pending')?.setAttribute('hidden', '');
  el('deletion-inprogress')?.setAttribute('hidden', '');
  el('deletion-admin-note')?.removeAttribute('hidden');
}

export function setDeletionSaving(isSaving) {
  const button = el('deletion-request');
  if (!button) return;
  button.disabled = isSaving;
  button.querySelector('.spinner-border')?.classList.toggle('d-none', !isSaving);
}

export function setDeletionCancelling(isCancelling) {
  const button = el('deletion-cancel');
  if (!button) return;
  button.disabled = isCancelling;
  button.querySelector('.spinner-border')?.classList.toggle('d-none', !isCancelling);
}

/** `key` selects which runtime.profile.account.deletion* string to show. */
export function showDeletionError(key = 'deletionRequestFailed') {
  const error = el('deletion-error');
  if (error) {
    error.textContent = I18n.t(`profile.account.${key}`);
    error.hidden = false;
  }
}

export function showDeletionRequested() {
  const note = el('deletion-note');
  if (note) {
    note.textContent = I18n.t('profile.account.deletionRequested');
    note.hidden = false;
  }
  el('deletion-error')?.setAttribute('hidden', '');
}

export function showDeletionCancelSaved() {
  const note = el('deletion-cancel-note');
  if (note) {
    note.textContent = I18n.t('profile.account.deletionCancelled');
    note.hidden = false;
  }
  el('deletion-cancel-error')?.setAttribute('hidden', '');
}

/** `key` selects which runtime.profile.account.deletion* string to show. */
export function showDeletionCancelError(key = 'deletionCancelFailed') {
  const error = el('deletion-cancel-error');
  if (error) {
    error.textContent = I18n.t(`profile.account.${key}`);
    error.hidden = false;
  }
}
