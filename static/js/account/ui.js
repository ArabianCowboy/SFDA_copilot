/**
 * SFDA Copilot — Account page rendering
 *
 * Pure DOM writes. Nothing here decides what to fetch or when — app.js and
 * handlers.js own that; this module only draws what it is told.
 */

import { I18n } from '../modules/i18n.js';

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
 * isolate (docs/profile-refactor-plan.md §7.2).
 */
function formatSince(isoString) {
  if (!isoString) return '—';
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return '—';
  const parts = new Intl.DateTimeFormat(I18n.lang, {
    year: 'numeric', month: 'long', day: 'numeric',
  }).formatToParts(date);
  return parts.map((p) => p.value).join('');
}

export function renderStanding({ role, tier, isAdmin, isDisabled, createdAt, conversationCount }) {
  const roleEl = el('standing-role');
  if (roleEl) roleEl.textContent = I18n.t(isAdmin ? 'profile.account.roleAdmin' : 'profile.account.roleUser');

  const tierEl = el('standing-tier');
  if (tierEl) {
    tierEl.textContent = tier === 'internal'
      ? I18n.t('profile.account.tierInternal')
      : I18n.t('profile.account.tierFree');
  }

  const sinceEl = el('standing-since');
  if (sinceEl) sinceEl.textContent = formatSince(createdAt);

  const conversationsEl = el('standing-conversations');
  if (conversationsEl) {
    conversationsEl.textContent = conversationCount == null
      ? '—'
      : I18n.plural(conversationCount, 'profile.account.conversationOne', 'profile.account.conversations');
  }

  const statusEl = el('standing-status');
  if (statusEl) {
    statusEl.textContent = I18n.t(isDisabled ? 'profile.account.standingDisabled' : 'profile.account.standingEnabled');
  }
}

/* ── Identity form ───────────────────────────────────────────────────────── */

export function populateIdentityForm(profile) {
  const form = el('identity-form');
  if (!form || !profile) return;

  el('identity-first-name').value = profile.first_name || '';
  el('identity-family-name').value = profile.family_name || '';
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
  const themeInput = document.getElementById(`theme-choice-${theme}`)
    || document.getElementById('theme-choice-system');
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
  showPreferencesSaved._timer = setTimeout(() => { if (note) note.hidden = true; }, 4000);
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
