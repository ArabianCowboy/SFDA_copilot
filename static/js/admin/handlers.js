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
  renderUsers,
  showAuditMessage,
  showPeopleMessage,
  readSettingsForm,
  renderSettings,
  selectTab,
  setSettingsSaving,
  showGateMessage,
  stageRevert,
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
 * Load the People tab and wire its actions.
 *
 * Every destructive action is CONFIRMED rather than undoable. The reader app
 * uses an undo toast for New chat, and that is right there — clearing a
 * transcript is reversible and low-stakes. Disabling someone's access is
 * neither: they may already have been turned away by the time an undo window
 * closed, and "it was undone within eight seconds" is not something the person
 * affected experiences. So it asks first, and the record carries the reason.
 */
export async function initPeopleTab(services) {
  const body = document.getElementById('people-body');
  if (!body) return;

  async function load() {
    try {
      renderUsers(await services.users());
    } catch (error) {
      showPeopleMessage(I18n.t('admin.people.loadFailed'));
    }
  }

  await load();

  body.addEventListener('click', async (event) => {
    const button = event.target.closest('.admin-row-action');
    if (!button || button.disabled) return;

    const { action, userId } = button.dataset;
    const email = button.closest('tr')?.querySelector('.admin-cell-machine')?.textContent || '';
    let patch = null;

    if (action === 'promote') {
      patch = { role: 'admin' };
    } else if (action === 'demote') {
      if (!window.confirm(I18n.t('admin.people.confirmDemote', { email }))) return;
      patch = { role: 'user' };
    } else if (action === 'enable') {
      patch = { is_disabled: false };
    } else if (action === 'disable') {
      if (!window.confirm(I18n.t('admin.people.confirmDisable', { email }))) return;
      // Asked for, not optional: a disabled account with no stated reason is a
      // decision nobody can review later, including the person who made it.
      const reason = window.prompt(I18n.t('admin.people.reasonPrompt'));
      if (reason === null) return;
      // The server requires one. Catching it here means an operator is told
      // before the round trip rather than after it, and the two agree about
      // what "required" means — an empty prompt used to normalise to NULL and
      // be accepted.
      if (!reason.trim()) {
        ErrorHandler.showToast(I18n.t('admin.people.reason_required'), true);
        return;
      }
      patch = { is_disabled: true, reason: reason.trim() };
    }
    if (!patch) return;

    button.disabled = true;
    try {
      await services.setUserFlags(userId, patch);
      ErrorHandler.showToast(I18n.t('admin.people.changed'));
      await load();
      loadAudit(services);
    } catch (error) {
      // A 409 is the system refusing on principle — it understood perfectly.
      // It gets the specific sentence rather than a generic failure, because
      // "you cannot demote yourself" is actionable and "something went wrong"
      // is not.
      const code = error instanceof AdminRequestError ? error.code : null;
      const known = ['cannot_change_own_access', 'would_leave_no_administrator',
                     'no_such_account', 'actor_no_longer_administrator', 'reason_required'];
      ErrorHandler.showToast(
        known.includes(code)
          ? I18n.t(`admin.people.${code}`)
          : I18n.t('admin.people.changeFailed'),
        true,
      );
      button.disabled = false;
    }
  });
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
  // Held so a re-render on model change keeps showing which values were
  // actually chosen rather than resetting every marker to "default".
  let currentOverrides = {};
  // What each field reverts TO. An overridden field hides its own default,
  // so the console cannot offer reversion without being told.
  let currentDefaults = {};

  try {
    const loaded = await services.settings();
    allowedModels = loaded.allowed_models || [];
    currentOverrides = loaded.overrides || {};
    currentDefaults = loaded.defaults || {};
    renderSettings(loaded);
  } catch (error) {
    showSettingsMessage(I18n.t('admin.settings.loadFailed'));
    ErrorHandler.showToast(I18n.t('admin.settings.loadFailed'), true);
    return;
  }

  // Changing the model changes which controls are even valid — a reasoning
  // model has an effort level and no temperature, an ordinary one the reverse.
  // Re-rendering on change means the form always shows what this model accepts,
  // rather than making an operator save once to discover the second control.
  body.addEventListener('click', (event) => {
    const revert = event.target.closest('.admin-field-revert');
    if (revert) stageRevert(revert.dataset.revert, currentDefaults);
  });

  body.addEventListener('change', (event) => {
    if (event.target.name !== 'model') return;
    renderSettings({
      settings: { ...readSettingsForm(), model: event.target.value },
      overrides: currentOverrides,
      defaults: currentDefaults,
      allowed_models: allowedModels,
    });
  });

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
      currentOverrides = saved.overrides || {};
      currentDefaults = saved.defaults || currentDefaults;
      renderSettings({ ...saved, defaults: currentDefaults, allowed_models: allowedModels });

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
