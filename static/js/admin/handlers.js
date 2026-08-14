/**
 * SFDA Copilot — Console event handling and failure presentation
 *
 * Owns everything a person is told. `admin/services.js` throws; this decides
 * what that means and which words it gets — the same split the reader surface
 * keeps between `services.js` and `handlers.js`.
 */

import { ErrorHandler } from '../modules/dom.js';
import { I18n } from '../modules/i18n.js';
import { AdminRequestError } from './services.js';
import {
  clearSettingsErrors,
  focusTab,
  renderAudit,
  showAuditMessage,
  readSettingsForm,
  renderSettings,
  selectTab,
  setSettingsSaving,
  showGateMessage,
  showSettingsErrors,
  showSettingsMessage,
  tabIds,
} from './ui.js';

/**
 * Turn a failed access check into one sentence.
 *
 * 403 is not an error to apologise for: the server understood perfectly and
 * the answer is no. A reader who lands here has done nothing wrong and should
 * not be shown a fault message, so it reads as a statement rather than a
 * failure. 401 means the token did not arrive or has expired, which is a
 * different instruction — go and sign in. Anything else genuinely is a fault.
 */
export function describeAccessFailure(error) {
  if (error instanceof AdminRequestError) {
    if (error.status === 403) return I18n.t('admin.accessDenied');
    if (error.status === 401) return I18n.t('admin.signedOut');
  }
  return I18n.t('admin.accessCheckFailed');
}

export function showAccessFailure(error) {
  const message = describeAccessFailure(error);
  showGateMessage(message);
  // Only a genuine fault gets a toast. A refusal is already stated in place,
  // and repeating it as an alert would make a normal boundary read as a crash.
  const isRefusal =
    error instanceof AdminRequestError && [401, 403].includes(error.status);
  if (!isRefusal) ErrorHandler.showToast(message, true);
}

/**
 * Tablist keyboard model: arrows move and activate, Home/End jump to the ends.
 *
 * Activation follows focus, which is correct for panels that are already in the
 * document — there is nothing to load, so requiring a second keypress would be
 * ceremony. Delegated from the tablist so a tab added later is wired for free.
 */
export function bindConsoleEvents() {
  const tablist = document.querySelector('.admin-tabs');
  if (!tablist) return;

  tablist.addEventListener('click', (event) => {
    const tab = event.target.closest('.admin-tab');
    if (tab) selectTab(tab.id);
  });

  tablist.addEventListener('keydown', (event) => {
    const ids = tabIds();
    const current = ids.indexOf(event.target.id);
    if (current === -1) return;

    // The tablist is horizontal, so Left/Right follow the writing direction.
    // Under RTL the visual order is mirrored while the key names are not, which
    // is why the step is negated rather than the array reversed.
    const rtl = document.documentElement.getAttribute('dir') === 'rtl';
    let next = null;

    if (event.key === 'ArrowRight') next = current + (rtl ? -1 : 1);
    else if (event.key === 'ArrowLeft') next = current + (rtl ? 1 : -1);
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = ids.length - 1;
    else return;

    event.preventDefault();
    const target = ids[(next + ids.length) % ids.length];
    selectTab(target);
    focusTab(target);
  });
}

/**
 * Load the activity log.
 *
 * Loaded when the console opens rather than lazily on tab click: it is small,
 * and an operator who is checking what changed wants it there, not one
 * interaction away. Re-read after a save, because the save just added to it.
 */
export async function loadAudit(services) {
  if (!document.getElementById('audit-body')) return;
  try {
    const { entries } = await services.audit();
    renderAudit(entries);
  } catch (error) {
    showAuditMessage(I18n.t('admin.audit.loadFailed'));
  }
}

/**
 * Load the settings tab and wire its save.
 *
 * The form is submitted whole rather than per-field. Partial saves would let an
 * operator leave the instance in a combination neither of them chose — a model
 * with a lower output ceiling saved before the token limit that has to come
 * down with it — and the server validates the resulting state for exactly that
 * reason. One submit, one decision.
 */
export async function initSettingsTab(services) {
  const body = document.getElementById('settings-body');
  if (!body) return;

  // Held here rather than re-fetched after each save: the allowlist comes from
  // config.yaml and cannot change without a deploy, which would reload this
  // page anyway.
  let allowedModels = [];

  try {
    const loaded = await services.settings();
    allowedModels = loaded.allowed_models || [];
    renderSettings(loaded);
  } catch (error) {
    showSettingsMessage(I18n.t('admin.settings.loadFailed'));
    ErrorHandler.showToast(I18n.t('admin.settings.loadFailed'), true);
    return;
  }

  // Delegated from the panel, so the listener survives the form being
  // re-rendered after every save.
  body.addEventListener('submit', async (event) => {
    if (event.target.id !== 'settings-form') return;
    event.preventDefault();

    clearSettingsErrors();
    setSettingsSaving(true);
    try {
      const saved = await services.saveSettings(readSettingsForm());
      // Re-render from the server's answer rather than from what was typed:
      // the response is what is actually stored, and it also refreshes the
      // "changed here" markers, which a local update would leave stale.
      renderSettings({ ...saved, allowed_models: allowedModels });

      // `applied: false` means the values were stored but the generation
      // handler could not be rebuilt from them, so answers are still coming
      // from the previous settings. Saying only "saved" there would be true
      // and misleading — an operator switching away from a degraded model
      // needs to know it has not actually happened yet.
      if (saved.applied === false) {
        ErrorHandler.showToast(I18n.t('admin.settings.savedNotApplied'), true);
      } else {
        ErrorHandler.showToast(I18n.t('admin.settings.saved'));
      }

      // The save just wrote an audit row; showing a stale log next to a change
      // that is already live is the one moment the record looks untrustworthy.
      loadAudit(services);
    } catch (error) {
      setSettingsSaving(false);
      if (error instanceof AdminRequestError && error.errors?.length) {
        showSettingsErrors(error.errors);
        // A failure with no field of its own — storage unavailable — has
        // nowhere to sit in the form, so it is spoken aloud instead.
        const homeless = error.errors.filter((entry) => entry.field === '_');
        homeless.forEach((entry) =>
          ErrorHandler.showToast(I18n.t(`admin.errors.${entry.code}`), true));
        return;
      }
      ErrorHandler.showToast(I18n.t('admin.settings.saveFailed'), true);
    }
  });
}
