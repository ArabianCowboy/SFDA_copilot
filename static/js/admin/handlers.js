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
  renderAccountDetail,
  renderAudit,
  renderUsers,
  showAccountList,
  showAccountMessage,
  showAuditMessage,
  showPeopleMessage,
  readProfileForm,
  readSettingsDisplay,
  readSettingsForm,
  renderSettings,
  selectTab,
  setProfileSaving,
  setSettingsSaving,
  showGateMessage,
  stageRevert,
  showSettingsErrors,
  showSettingsMessage,
  tabIds,
} from './ui.js';

/**
 * Which sentence a refused profile save gets.
 *
 * A lookup rather than a prefix, because these codes do not all live under one
 * catalogue branch: a stale write is specific to this form, but "that account is
 * gone" and "you are no longer an administrator" are the same facts the role
 * controls report and share their wording.
 */
const PROFILE_REFUSALS = {
  profile_changed_since_loaded: 'admin.account.profile_changed_since_loaded',
  no_such_account: 'admin.people.no_such_account',
  actor_no_longer_administrator: 'admin.people.actor_no_longer_administrator',
  too_long: 'admin.account.profile_too_long',
};

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
    // The server could not REACH the identity provider. Distinct from 401 on
    // purpose: telling an administrator whose session is perfectly good to go
    // and sign in again sends them to fix something that is not broken.
    if (error.status === 503) return I18n.t('admin.identityUnavailable');
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

  const search = document.getElementById('people-search');
  let searchTimer = null;
  /* Which account is already being fetched, if any.
     The generation counter below discards a stale RENDER, but both requests
     still leave the browser — and opening an account costs two of them, each
     paying a GoTrue token verification on the server. A double-click therefore
     spends four verifications to draw one page, against the exact service whose
     timeout produced the 401 this was hardened for. Same account already in
     flight: do nothing. */
  let opening = null;
  /* Which view the operator last asked for. Every render checks it before
     touching the DOM, so a request that resolves late cannot redraw a panel the
     operator has already moved on from — typing and then opening a result
     within the debounce window otherwise let the list replace the detail. */
  let generation = 0;

  async function load() {
    clearTimeout(searchTimer);
    // Returning to the list abandons whatever was being opened. Without this,
    // opening an account, going back, and opening the same one again inside one
    // round trip would find the guard below still held and do nothing at all.
    opening = null;
    const mine = ++generation;
    try {
      const result = await services.users({ q: search?.value.trim() || '' });
      if (mine !== generation) return;
      showAccountList();
      renderUsers(result);
    } catch (error) {
      if (mine !== generation) return;
      showAccountList();
      showPeopleMessage(I18n.t('admin.people.loadFailed'));
    }
  }

  /* The detail view is reachable only from this list, and the list serves one
     page of 50. Without a search box it is a door with no corridor the moment an
     instance has more accounts than that — the API and the RPC have taken `q`
     since they were written. */
  search?.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(load, 300);
  });

  async function openAccount(userId) {
    if (opening === userId) return;
    opening = userId;
    clearTimeout(searchTimer);
    const mine = ++generation;
    try {
      const { user, self_id: selfId } = await services.user(userId);
      // The activity is a second request and is allowed to fail on its own: a
      // log outage should not stop an operator seeing who they are looking at.
      let entries = [];
      try {
        entries = (await services.audit({ targetType: 'user', targetId: userId })).entries;
      } catch (error) {
        entries = null;
      }
      if (mine !== generation) return;
      renderAccountDetail(user, entries, selfId);
    } catch (error) {
      if (mine !== generation) return;
      showAccountMessage(I18n.t('admin.account.loadFailed'));
    } finally {
      // Released in `finally`, and only if this call is still the current one:
      // a failed open must not leave the account permanently unopenable, and a
      // slow one that has already been superseded must not clear the newer
      // request's claim on the way out.
      if (opening === userId) opening = null;
    }
  }

  await load();

  /* Saving a profile is its own route and its own RPC, so it is its own
     listener. Delegated from the panel, because the form is rebuilt from
     scratch every time an account is opened. */
  body.addEventListener('submit', async (event) => {
    if (event.target.id !== 'account-profile-form') return;
    event.preventDefault();

    const form = readProfileForm();
    if (!form) return;

    setProfileSaving(true);
    try {
      await services.updateProfile(form.userId, form.patch);
      ErrorHandler.showToast(I18n.t('admin.account.profileSaved'));
      // Re-read rather than patch in place: the response carries a new
      // `updated_at`, and saving twice against the stale one would be refused
      // as a conflict with nobody.
      await openAccount(form.userId);
      loadAudit(services);
    } catch (error) {
      setProfileSaving(false);
      const code = error instanceof AdminRequestError ? error.code : null;
      ErrorHandler.showToast(
        I18n.t(PROFILE_REFUSALS[code] || 'admin.account.profileSaveFailed'), true,
      );
    }
  });

  body.addEventListener('click', async (event) => {
    if (event.target.closest('#account-back')) {
      await load();
      document.querySelector('.admin-account-open')?.focus();
      return;
    }

    /* The whole row opens its account. The address stays a real button because
       a keyboard and a screen reader need a control to land on, but a
       five-column row where only the first cell answers is a target the eye has
       to aim at. Anything that is itself a control keeps its own behaviour. */
    const row = event.target.closest('#people-table tbody tr[data-user-id]');
    if (row && !event.target.closest('button')) {
      await openAccount(row.dataset.userId);
      return;
    }

    const button = event.target.closest('.admin-row-action');
    if (!button || button.disabled) return;

    const { action, userId } = button.dataset;

    if (action === 'open') {
      await openAccount(userId);
      return;
    }

    /* Role and access now live only on the account page, so the account being
       acted on is the one the page is showing. It used to be read out of the
       row the button sat in, and that row no longer exists. */
    const email = document.getElementById('account-heading')?.textContent || '';

    if (action === 'send-reset') {
      /* Confirmed, because it puts a credential-recovery link in somebody's
         inbox. `DESIGN.md` gives the system no danger button to lean on, so the
         weight has to come from the words and from the record. */
      if (!window.confirm(I18n.t('admin.account.confirmReset', { email }))) return;

      button.disabled = true;
      try {
        await services.sendPasswordReset(userId);
        ErrorHandler.showToast(I18n.t('admin.account.resetAccepted'));
      } catch (error) {
        const code = error instanceof AdminRequestError ? error.code : null;
        const known = ['reset_rate_limited', 'reset_quota_exhausted', 'reset_no_email'];
        ErrorHandler.showToast(
          known.includes(code)
            ? I18n.t(`admin.account.${code}`)
            : I18n.t('admin.account.resetFailed'),
          true,
        );
      } finally {
        button.disabled = false;
      }
      // Reload so the two new audit rows appear in this account's own history.
      await openAccount(userId);
      return;
    }

    if (action === 'revoke-sessions') {
      /* Confirmed for the same reason send-reset is: no danger-button variant
         exists, so the weight comes from the words and the record. The
         confirm copy itself states the residual-JWT-validity caveat, so an
         operator reads it before committing, not after. */
      if (!window.confirm(I18n.t('admin.account.confirmRevoke', { email }))) return;

      button.disabled = true;
      try {
        await services.revokeSessions(userId);
        ErrorHandler.showToast(I18n.t('admin.account.revokeAccepted'));
      } catch (error) {
        const code = error instanceof AdminRequestError ? error.code : null;
        const known = [
          'auth_admin_unavailable', 'auth_admin_unreachable', 'auth_admin_failed',
          'no_such_account', 'actor_no_longer_administrator',
        ];
        ErrorHandler.showToast(
          known.includes(code) ? I18n.t(`admin.account.${code}`) : I18n.t('admin.account.revokeFailed'),
          true,
        );
      } finally {
        button.disabled = false;
      }
      await openAccount(userId);
      return;
    }

    if (action === 'change-email') {
      /* A prompt, not a form: matching the disable-reason input above rather
         than inventing a modal this console has never had. Validated
         client-side before the confirm step is even shown, so a mistyped
         address never reaches a confirmation dialog that names it. */
      const newEmail = window.prompt(I18n.t('admin.account.emailPrompt', { email }));
      if (newEmail === null) return;
      const trimmed = newEmail.trim();
      if (!trimmed || !trimmed.includes('@')) {
        ErrorHandler.showToast(I18n.t('admin.account.invalid_email'), true);
        return;
      }
      /* States plainly that this takes effect immediately with no reader-side
         confirmation step — the Admin API has no defer-until-confirmed flow,
         and the operator should read that before committing, not discover it
         after. */
      if (!window.confirm(I18n.t('admin.account.confirmEmailChange', { email, newEmail: trimmed }))) {
        return;
      }

      button.disabled = true;
      try {
        await services.changeEmail(userId, trimmed);
        ErrorHandler.showToast(I18n.t('admin.account.emailChangeAccepted'));
      } catch (error) {
        const code = error instanceof AdminRequestError ? error.code : null;
        const known = [
          'email_already_registered', 'auth_admin_unavailable', 'auth_admin_unreachable',
          'auth_admin_failed', 'no_such_account', 'same_email', 'invalid_email',
          'cannot_change_own_email', 'actor_no_longer_administrator', 'too_long',
        ];
        ErrorHandler.showToast(
          known.includes(code) ? I18n.t(`admin.account.${code}`) : I18n.t('admin.account.emailChangeFailed'),
          true,
        );
      } finally {
        button.disabled = false;
      }
      await openAccount(userId);
      return;
    }

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

    // Where the operator acted from decides where they end up. Acting on the
    // detail view and being returned to the list would lose the account they
    // were working on, and the change they just made is only visible there.
    const fromDetail = !document.getElementById('people-detail')?.hidden;

    button.disabled = true;
    try {
      await services.setUserFlags(userId, patch);
      ErrorHandler.showToast(I18n.t('admin.people.changed'));
      if (fromDetail) await openAccount(userId);
      else await load();
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
  // The last state the SERVER reported, kept as the floor a re-render falls
  // back to. A model switch hides the controls the new model has no parameter
  // for, and reading the form is therefore a lossy snapshot of it — switching
  // to a reasoning model and back used to return a blank temperature box,
  // because the value only ever existed in the control that had just been
  // removed. An empty box is then dropped from the patch, so the round trip
  // quietly abandoned a setting the operator never touched.
  let currentSettings = {};
  // What the running handler is actually generating with, which is not the same
  // fact as what is stored. Carried across re-renders so the warning does not
  // vanish the moment the operator touches the model select.
  let currentActive = {};

  try {
    const loaded = await services.settings();
    allowedModels = loaded.allowed_models || [];
    currentOverrides = loaded.overrides || {};
    currentDefaults = loaded.defaults || {};
    currentSettings = loaded.settings || {};
    currentActive = loaded.active || {};
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

    // Over the last state the server reported, not in place of it. A control
    // the outgoing model had and the incoming one does not is absent from the
    // read, and `currentSettings` is then the only place its value still
    // exists — reading the form alone is how the temperature box came back
    // empty after a trip through a reasoning model.
    const settings = {
      ...currentSettings,
      ...readSettingsDisplay(),
      model: event.target.value,
    };

    renderSettings({
      settings,
      overrides: currentOverrides,
      defaults: currentDefaults,
      allowed_models: allowedModels,
      active: currentActive,
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
      currentSettings = saved.settings || currentSettings;
      currentActive = saved.active || {};
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
        // Whatever could not be placed beside a field is spoken aloud. Asking
        // the renderer which ones those were, rather than assuming it is only
        // the field-less `_` code, is what stops a refusal from disappearing:
        // an error against a control this model does not draw is homeless in
        // exactly the same way, and used to be dropped on the floor — the save
        // failed and the console said nothing at all.
        const homeless = showSettingsErrors(error.errors);
        homeless.forEach((entry) =>
          ErrorHandler.showToast(I18n.t(`admin.errors.${entry.code}`), true));
        return;
      }
      ErrorHandler.showToast(I18n.t('admin.settings.saveFailed'), true);
    }
  });
}
