/**
 * SFDA Copilot — Console event handling and failure presentation
 *
 * Owns everything a person is told. `admin/services.js` throws; this decides
 * what that means and which words it gets — the same split the reader surface
 * keeps between `services.js` and `handlers.js`.
 */

import { ErrorHandler } from '../modules/dom.js';
import { I18n } from '../modules/i18n.js';
import { newRequestId } from '../modules/services.js';
import { AdminRequestError } from './services.js';
import {
  clearSettingsErrors,
  focusTab,
  prefillComposer,
  readComposerForm,
  renderAccountDetail,
  renderAudit,
  renderNotificationHistory,
  renderNotificationsPanel,
  renderUsers,
  resetComposerForm,
  setAudiencePreview,
  setBulkSelectionState,
  setNotificationComposerSending,
  setPeopleLoading,
  showAccountList,
  showAccountMessage,
  showAuditMessage,
  showComposerError,
  showNotificationHistoryMessage,
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
  syncNotificationTargetFields,
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
  const isRefusal = error instanceof AdminRequestError && [401, 403].includes(error.status);
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
    let next;

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
/**
 * Notification Center composer + history (docs/notification-center-plan.md
 * §4). One init function, matching initPeopleTab/initSettingsTab's own
 * shape: closes over the panel's own request state (the preview debounce,
 * the history offset, the row cache resend needs) rather than leaking it
 * onto module scope, which multiple tabs would then have to coordinate.
 */
const NOTIFICATION_REFUSALS = {
  idempotency_conflict: 'admin.notifications.composer.idempotency_conflict',
  no_matching_recipients: 'admin.notifications.composer.no_matching_recipients',
  no_such_target_user: 'admin.notifications.composer.no_such_target_user',
  target_user_disabled: 'admin.notifications.composer.target_user_disabled',
  actor_no_longer_administrator: 'admin.notifications.composer.actor_no_longer_administrator',
};

const NOTIFICATION_VALIDATION_KEYS = {
  invalid_type: 'admin.notifications.composer.invalid_type',
  invalid_severity: 'admin.notifications.composer.invalid_severity',
  invalid_field: 'admin.notifications.composer.invalid_field',
  invalid_target_kind: 'admin.notifications.composer.invalid_target_kind',
  invalid_target_role: 'admin.notifications.composer.invalid_target_role',
  invalid_target_tier: 'admin.notifications.composer.invalid_target_tier',
  invalid_target_user: 'admin.notifications.composer.invalid_target_user',
};

const NOTIFICATION_HISTORY_REFUSALS = {
  no_such_notification: 'admin.notifications.history.no_such_notification',
  already_deactivated: 'admin.notifications.history.already_deactivated',
  already_deleted: 'admin.notifications.history.already_deleted',
  not_yet_deleted: 'admin.notifications.history.not_yet_deleted',
  actor_no_longer_administrator: 'admin.notifications.history.actor_no_longer_administrator',
};

function describeComposerError(error) {
  const code = error instanceof AdminRequestError ? error.code : null;
  const key = NOTIFICATION_REFUSALS[code] || NOTIFICATION_VALIDATION_KEYS[code];
  return key ? I18n.t(key) : I18n.t('admin.notifications.composer.sendFailed');
}

function describeHistoryActionError(error, fallbackKey) {
  const code = error instanceof AdminRequestError ? error.code : null;
  const key = NOTIFICATION_HISTORY_REFUSALS[code];
  return key ? I18n.t(key) : I18n.t(fallbackKey);
}

export async function initNotificationsTab(services) {
  renderNotificationsPanel();

  const form = document.getElementById('notification-composer-form');
  if (!form) return;

  // Full row objects, keyed by id, refreshed on every history load — the
  // table itself only carries what it displays, and "Resend" needs the
  // bilingual title/body/targeting the table never shows in full.
  let historyRows = new Map();
  let historyOffset = 0;
  const historyLimit = 20;
  let previewTimer = null;
  let previewGeneration = 0;
  // "Active" to match the status <select>'s own default (ui.js's
  // buildNotificationHistoryToolbar) — deletion is soft, so without this a
  // deleted notification stayed in this table forever.
  let historyStatus = 'active';
  let historyGeneration = 0;
  // Ids checked via the per-row/select-all checkboxes — cleared on every
  // fresh (non-append) load, since a filter change or a bulk clear both
  // replace the rendered row set.
  let selectedIds = new Set();
  // Overwritten from the server once, right after init — this default only
  // covers the brief window before that read resolves.
  let purgeRetentionDays = 90;

  function updateBulkSelectionUI() {
    setBulkSelectionState(selectedIds.size);
  }

  // Whether a selected id's row is currently rendered as Deleted — read
  // from the DOM (the row's own admin-notif-row--deleted class, set in the
  // same render pass as its checkbox) rather than from the historyRows Map,
  // so "Clear selected"/"Purge selected" can't disagree with each other or
  // silently drop an id whose historyRows entry didn't survive a reload
  // (found in review: relying on historyRows here was fragile across a
  // partial-failure retry that reloads a different page than the one an id
  // was originally selected from).
  function isRowDeleted(id) {
    const checkbox = document.querySelector(
      `#notification-history-table [data-notif-select="${id}"]`,
    );
    return Boolean(checkbox?.closest('tr')?.classList.contains('admin-notif-row--deleted'));
  }

  // Keeps the header "select all" checkbox honest after a render — without
  // this, checking "select all" and then clicking "Load more" left the
  // header checked while only the pre-append rows were actually selected
  // (found in review).
  function syncSelectAllCheckbox() {
    const selectAll = document.getElementById('notification-history-select-all');
    if (!selectAll) return;
    const checkboxes = Array.from(
      document.querySelectorAll('#notification-history-table [data-notif-select]'),
    );
    const checkedCount = checkboxes.filter((checkbox) =>
      selectedIds.has(checkbox.dataset.notifSelect),
    ).length;
    selectAll.checked = checkboxes.length > 0 && checkedCount === checkboxes.length;
    selectAll.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
  }

  function updateClearAllAvailability() {
    const clearAll = document.getElementById('notification-history-clear-all');
    // Nothing to clear while looking at rows that are already deleted.
    if (clearAll) clearAll.disabled = historyStatus === 'deleted';
  }

  // The retention setting and "Purge eligible" only make sense while
  // actually looking at Deleted rows — every other filter hides the toolbar
  // entirely rather than showing it disabled, since there's nothing on
  // screen it could act on.
  function updatePurgeToolbarVisibility() {
    const toolbar = document.getElementById('notification-purge-toolbar');
    if (toolbar) toolbar.hidden = historyStatus !== 'deleted';
  }

  function setHistoryControlsDisabled(disabled) {
    const select = document.getElementById('notification-history-status');
    const loadMore = document.getElementById('notification-history-load-more');
    const clearAll = document.getElementById('notification-history-clear-all');
    const clearSelected = document.getElementById('notification-history-clear-selected');
    const purgeSelected = document.getElementById('notification-history-purge-selected');
    const purgeEligible = document.getElementById('notification-purge-eligible');
    if (select) select.disabled = disabled;
    if (loadMore) loadMore.disabled = disabled;
    if (clearSelected) clearSelected.disabled = disabled;
    if (purgeSelected) purgeSelected.disabled = disabled;
    if (purgeEligible) purgeEligible.disabled = disabled;
    // Re-disabling "Clear all" always follows the deleted-filter rule, not
    // just the in-flight one, so it doesn't spuriously re-enable mid-filter.
    if (clearAll) clearAll.disabled = disabled || historyStatus === 'deleted';
  }

  // Race-safety: a filter change and a "Load more" click can both be in
  // flight at once (or two filter changes in quick succession) — without a
  // generation token, a stale response can render after a newer one, and
  // both would bump the same historyOffset, skipping or duplicating rows.
  // Mirrors updatePreview's own previewGeneration pattern just below.
  async function loadHistory({ append = false } = {}) {
    const mine = ++historyGeneration;
    if (!append) {
      historyOffset = 0;
      historyRows = new Map();
      selectedIds = new Set();
      updateBulkSelectionUI();
    }
    setHistoryControlsDisabled(true);
    try {
      const result = await services.notificationHistory({
        limit: historyLimit,
        offset: historyOffset,
        status: historyStatus,
      });
      if (mine !== historyGeneration) return;
      const rows = result.notifications || [];
      rows.forEach((row) => historyRows.set(row.id, row));
      renderNotificationHistory(rows, { append, filterStatus: historyStatus });
      syncSelectAllCheckbox();
      historyOffset += rows.length;
      const loadMore = document.getElementById('notification-history-load-more');
      if (loadMore) loadMore.hidden = rows.length < historyLimit;
    } catch {
      if (mine !== historyGeneration) return;
      showNotificationHistoryMessage(I18n.t('admin.notifications.history.loadFailed'));
    } finally {
      if (mine === historyGeneration) setHistoryControlsDisabled(false);
    }
  }

  // Pages through every row matching `status`, not just one page — "Clear
  // all" means all, and the history endpoint caps `limit` at 200
  // server-side (web/api/admin.py's _parse_pagination_params). Bounded at
  // 50 pages (10,000 rows) as a runaway-loop backstop — but the caller must
  // check `truncated` and refuse rather than silently clearing a partial
  // set while telling the operator it cleared everything (found in review:
  // the original version returned only the first 10,000 ids with no signal
  // that more existed).
  async function fetchAllIdsForClear(status) {
    const ids = [];
    const pageLimit = 200;
    const maxPages = 50;
    let truncated = true;
    for (let offset = 0, page = 0; page < maxPages; page += 1) {
      const result = await services.notificationHistory({ limit: pageLimit, offset, status });
      const rows = result.notifications || [];
      rows.forEach((row) => {
        if (!row.deleted_at) ids.push(row.id);
      });
      if (rows.length < pageLimit) {
        truncated = false;
        break;
      }
      offset += rows.length;
    }
    return { ids, truncated };
  }

  // Runs `worker` over `items` with at most `concurrency` in flight at once,
  // in Promise.allSettled's own {status, reason}-shaped result order — a
  // plain Promise.allSettled(ids.map(...)) fired every delete at once, which
  // review flagged as an unbounded burst (up to 10,000 concurrent requests
  // at fetchAllIdsForClear's own ceiling). Pooled to be a good citizen of
  // the browser's connection limit and the server's request queue even
  // though neither /deactivate nor the plain DELETE route is rate-limited
  // today (verified against web/api/admin.py — only notification CREATE is,
  // via notification_broadcast_api).
  async function runWithConcurrency(items, worker, concurrency) {
    const results = new Array(items.length);
    let next = 0;
    async function runOne() {
      while (next < items.length) {
        const index = next;
        next += 1;
        try {
          await worker(items[index]);
          results[index] = { status: 'fulfilled' };
        } catch (error) {
          results[index] = { status: 'rejected', reason: error };
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, runOne));
    return results;
  }

  // Shared by "Clear"/"Purge" — both are the same shape: run one action per
  // id (pooled, above), toast a success/partial/fail summary, reload, and
  // re-select whatever failed so a retry doesn't require the operator to
  // re-find and re-check rows by hand (found in review: loadHistory's own
  // !append branch always clears selectedIds, which previously lost this
  // for free after a partial failure).
  async function runBulkAction(ids, actionFn, { successKey, partialKey, failKey }) {
    const results = await runWithConcurrency(ids, actionFn, 8);
    const failedIds = ids.filter((_, index) => results[index].status === 'rejected');
    const succeeded = ids.length - failedIds.length;
    if (failedIds.length === 0) {
      ErrorHandler.showToast(
        I18n.t(`admin.notifications.history.${successKey}`, { count: succeeded }),
      );
    } else if (succeeded === 0) {
      ErrorHandler.showToast(I18n.t(`admin.notifications.history.${failKey}`), true);
    } else {
      ErrorHandler.showToast(
        I18n.t(`admin.notifications.history.${partialKey}`, {
          count: succeeded,
          failed: failedIds.length,
        }),
        true,
      );
    }
    await loadHistory();
    if (failedIds.length) {
      selectedIds = new Set(failedIds);
      document
        .querySelectorAll('#notification-history-table [data-notif-select]')
        .forEach((checkbox) => {
          checkbox.checked = selectedIds.has(checkbox.dataset.notifSelect);
        });
      updateBulkSelectionUI();
      syncSelectAllCheckbox();
    }
  }

  // Reuses the existing single-notification delete RPC per id rather than a
  // dedicated bulk endpoint — no schema/backend change, and this is an
  // admin-console-scale operation (tens, not thousands, per click).
  async function bulkClear(ids) {
    await runBulkAction(ids, (id) => services.deleteNotification(id), {
      successKey: 'bulkCleared',
      partialKey: 'bulkClearedPartial',
      failKey: 'bulkClearFailed',
    });
  }

  // Same reuse-the-single-row-endpoint reasoning as bulkClear, over
  // purgeNotification instead of deleteNotification.
  async function bulkPurge(ids) {
    await runBulkAction(ids, (id) => services.purgeNotification(id), {
      successKey: 'bulkPurged',
      partialKey: 'bulkPurgedPartial',
      failKey: 'bulkPurgeFailed',
    });
  }

  // Same pagination shape as fetchAllIdsForClear, filtered by age instead of
  // by deleted_at presence — only rows that have been sitting Deleted for at
  // least `retentionDays` are included. Manual purge (per-row/selected)
  // never calls this; only the "Purge eligible" bulk action does.
  async function fetchEligiblePurgeIds(retentionDays) {
    const ids = [];
    const pageLimit = 200;
    const maxPages = 50;
    let truncated = true;
    const cutoff = Date.now() - retentionDays * 24 * 60 * 60 * 1000;
    for (let offset = 0, page = 0; page < maxPages; page += 1) {
      const result = await services.notificationHistory({
        limit: pageLimit,
        offset,
        status: 'deleted',
      });
      const rows = result.notifications || [];
      rows.forEach((row) => {
        const deletedAt = row.deleted_at ? new Date(row.deleted_at).getTime() : NaN;
        // Strictly older than the window, matching the confirm dialog's own
        // "more than {days} days" wording (found in review: <= included a
        // row deleted exactly `retentionDays` ago, which the dialog implied
        // it would not).
        if (!Number.isNaN(deletedAt) && deletedAt < cutoff) ids.push(row.id);
      });
      if (rows.length < pageLimit) {
        truncated = false;
        break;
      }
      offset += rows.length;
    }
    return { ids, truncated };
  }

  async function updatePreview() {
    const mine = ++previewGeneration;
    const fields = readComposerForm();
    if (!['all', 'role', 'tier', 'user'].includes(fields.target_kind)) return;
    try {
      const result = await services.notificationAudiencePreview({
        target_kind: fields.target_kind,
        target_role: fields.target_role,
        target_tier: fields.target_tier,
        target_user_id: fields.target_user_id,
      });
      if (mine !== previewGeneration) return;
      setAudiencePreview(result.target_count);
    } catch {
      if (mine !== previewGeneration) return;
      setAudiencePreview(null);
    }
  }

  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(updatePreview, 300);
  }

  document.getElementById('notif-target-kind')?.addEventListener('change', (event) => {
    syncNotificationTargetFields(event.target.value);
    schedulePreview();
  });
  ['notif-target-role', 'notif-target-tier', 'notif-target-user'].forEach((id) => {
    const field = document.getElementById(id);
    field?.addEventListener('input', schedulePreview);
    field?.addEventListener('change', schedulePreview);
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    showComposerError(null);

    const fields = readComposerForm();
    if (!fields.title_en || !fields.title_ar || !fields.body_en || !fields.body_ar) {
      showComposerError(I18n.t('admin.notifications.composer.invalid_field'));
      return;
    }

    // Minted once per DISTINCT submission attempt, not once per click: a
    // retry of the same click (the operator pressing Send again after a
    // transient network failure) must reuse the same id so the server's
    // idempotency check actually applies. A successful send or an explicit
    // Resend/reset both clear it, which is what "distinct" means here.
    if (!form.dataset.requestId) form.dataset.requestId = newRequestId();

    setNotificationComposerSending(true);
    try {
      await services.createNotification({ ...fields, client_request_id: form.dataset.requestId });
      ErrorHandler.showToast(I18n.t('admin.notifications.composer.sent'));
      resetComposerForm();
      delete form.dataset.requestId;
      delete form.dataset.resendOf;
      loadHistory();
    } catch (error) {
      showComposerError(describeComposerError(error));
    } finally {
      setNotificationComposerSending(false);
    }
  });

  document.getElementById('notification-history-body')?.addEventListener('click', async (event) => {
    const deactivateBtn = event.target.closest('[data-notif-deactivate]');
    const deleteBtn = event.target.closest('[data-notif-delete]');
    const purgeBtn = event.target.closest('[data-notif-purge]');
    const resendBtn = event.target.closest('[data-notif-resend]');

    if (deactivateBtn) {
      const id = deactivateBtn.dataset.notifDeactivate;
      if (!window.confirm(I18n.t('admin.notifications.history.deactivateConfirm'))) return;
      try {
        await services.deactivateNotification(id);
        ErrorHandler.showToast(I18n.t('admin.notifications.history.deactivated'));
        loadHistory();
      } catch (error) {
        ErrorHandler.showToast(
          describeHistoryActionError(error, 'admin.notifications.history.deactivateFailed'),
          true,
        );
      }
    } else if (deleteBtn) {
      const id = deleteBtn.dataset.notifDelete;
      if (!window.confirm(I18n.t('admin.notifications.history.deleteConfirm'))) return;
      try {
        await services.deleteNotification(id);
        ErrorHandler.showToast(I18n.t('admin.notifications.history.deleted'));
        loadHistory();
      } catch (error) {
        ErrorHandler.showToast(
          describeHistoryActionError(error, 'admin.notifications.history.deleteFailed'),
          true,
        );
      }
    } else if (purgeBtn) {
      const id = purgeBtn.dataset.notifPurge;
      if (!window.confirm(I18n.t('admin.notifications.history.purgeConfirm'))) return;
      try {
        await services.purgeNotification(id);
        ErrorHandler.showToast(I18n.t('admin.notifications.history.purged'));
        loadHistory();
      } catch (error) {
        ErrorHandler.showToast(
          describeHistoryActionError(error, 'admin.notifications.history.purgeFailed'),
          true,
        );
      }
    } else if (resendBtn) {
      // Not a new endpoint (docs/notification-center-plan.md §3): prefill
      // the composer from the source row, mark it a resend, and let the
      // ordinary submit path send it with a fresh idempotency key.
      const id = resendBtn.dataset.notifResend;
      const row = historyRows.get(id);
      if (!row) return;
      prefillComposer(row);
      delete form.dataset.requestId;
      form.dataset.resendOf = id;
    }
  });

  document.getElementById('notification-history-load-more')?.addEventListener('click', () => {
    loadHistory({ append: true });
  });

  document.getElementById('notification-history-status')?.addEventListener('change', (event) => {
    historyStatus = event.target.value;
    updateClearAllAvailability();
    updatePurgeToolbarVisibility();
    loadHistory();
  });

  document.getElementById('notification-history-body')?.addEventListener('change', (event) => {
    const selectAll = event.target.closest('#notification-history-select-all');
    const rowCheckbox = event.target.closest('[data-notif-select]');
    if (selectAll) {
      document
        .querySelectorAll('#notification-history-table [data-notif-select]')
        .forEach((checkbox) => {
          checkbox.checked = selectAll.checked;
          if (selectAll.checked) selectedIds.add(checkbox.dataset.notifSelect);
          else selectedIds.delete(checkbox.dataset.notifSelect);
        });
      updateBulkSelectionUI();
    } else if (rowCheckbox) {
      if (rowCheckbox.checked) selectedIds.add(rowCheckbox.dataset.notifSelect);
      else selectedIds.delete(rowCheckbox.dataset.notifSelect);
      updateBulkSelectionUI();
      syncSelectAllCheckbox();
    }
  });

  document
    .getElementById('notification-history-clear-selected')
    ?.addEventListener('click', async () => {
      // Same selection as "Purge selected" reads, filtered down to the rows
      // this action actually applies to (found in review: this filter was
      // missing entirely, so selecting a mix of active and already-Deleted
      // rows sent every one of them to deleteNotification, which just
      // refuses the already-deleted ones as a partial-failure).
      const ids = Array.from(selectedIds).filter((id) => !isRowDeleted(id));
      if (!ids.length) {
        ErrorHandler.showToast(I18n.t('admin.notifications.history.nothingToClear'));
        return;
      }
      if (
        !window.confirm(
          I18n.t('admin.notifications.history.clearSelectedConfirm', { count: ids.length }),
        )
      )
        return;
      setHistoryControlsDisabled(true);
      await bulkClear(ids);
    });

  document
    .getElementById('notification-history-purge-selected')
    ?.addEventListener('click', async () => {
      // Same selection as "Clear selected" reads, filtered down to the rows
      // this action actually applies to — see the button's own build
      // comment in ui.js.
      const ids = Array.from(selectedIds).filter((id) => isRowDeleted(id));
      if (!ids.length) {
        ErrorHandler.showToast(I18n.t('admin.notifications.history.nothingToClear'));
        return;
      }
      if (
        !window.confirm(
          I18n.t('admin.notifications.history.purgeSelectedConfirm', { count: ids.length }),
        )
      )
        return;
      setHistoryControlsDisabled(true);
      await bulkPurge(ids);
    });

  document
    .getElementById('notification-purge-retention-save')
    ?.addEventListener('click', async () => {
      const input = document.getElementById('notification-purge-retention-days');
      const days = Number.parseInt(input?.value ?? '', 10);
      if (!Number.isInteger(days) || days < 1 || days > 3650) {
        ErrorHandler.showToast(I18n.t('admin.notifications.history.purgeRetentionInvalid'), true);
        return;
      }
      try {
        const result = await services.setPurgeRetentionDays(days);
        purgeRetentionDays = result.purge_retention_days ?? days;
        ErrorHandler.showToast(I18n.t('admin.notifications.history.purgeRetentionSaved'));
      } catch {
        ErrorHandler.showToast(
          I18n.t('admin.notifications.history.purgeRetentionSaveFailed'),
          true,
        );
      }
    });

  document.getElementById('notification-purge-eligible')?.addEventListener('click', async () => {
    if (historyStatus !== 'deleted') return;
    setHistoryControlsDisabled(true);
    let ids, truncated;
    try {
      ({ ids, truncated } = await fetchEligiblePurgeIds(purgeRetentionDays));
    } catch {
      setHistoryControlsDisabled(false);
      ErrorHandler.showToast(I18n.t('admin.notifications.history.loadFailed'), true);
      return;
    }
    if (truncated) {
      setHistoryControlsDisabled(false);
      ErrorHandler.showToast(I18n.t('admin.notifications.history.clearAllTooLarge'), true);
      return;
    }
    if (!ids.length) {
      setHistoryControlsDisabled(false);
      ErrorHandler.showToast(I18n.t('admin.notifications.history.nothingToClear'));
      return;
    }
    if (
      !window.confirm(
        I18n.t('admin.notifications.history.purgeEligibleConfirm', {
          count: ids.length,
          days: purgeRetentionDays,
        }),
      )
    ) {
      setHistoryControlsDisabled(false);
      return;
    }
    await bulkPurge(ids);
  });

  document.getElementById('notification-history-clear-all')?.addEventListener('click', async () => {
    if (historyStatus === 'deleted') return;
    setHistoryControlsDisabled(true);
    let ids, truncated;
    try {
      ({ ids, truncated } = await fetchAllIdsForClear(historyStatus));
    } catch {
      setHistoryControlsDisabled(false);
      ErrorHandler.showToast(I18n.t('admin.notifications.history.loadFailed'), true);
      return;
    }
    // Refuse rather than silently clear a partial set while implying it
    // cleared everything — narrowing the filter is the operator's own way
    // to bring the matching set under the page-fetch ceiling.
    if (truncated) {
      setHistoryControlsDisabled(false);
      ErrorHandler.showToast(I18n.t('admin.notifications.history.clearAllTooLarge'), true);
      return;
    }
    if (!ids.length) {
      setHistoryControlsDisabled(false);
      ErrorHandler.showToast(I18n.t('admin.notifications.history.nothingToClear'));
      return;
    }
    if (
      !window.confirm(
        I18n.t('admin.notifications.history.clearAllInFilterConfirm', { count: ids.length }),
      )
    ) {
      setHistoryControlsDisabled(false);
      return;
    }
    await bulkClear(ids);
  });

  updateClearAllAvailability();
  updatePurgeToolbarVisibility();
  try {
    const settings = await services.getPurgeRetentionDays();
    if (typeof settings.purge_retention_days === 'number') {
      purgeRetentionDays = settings.purge_retention_days;
    }
  } catch {
    // Keep the client-side default — the input still shows a sane value,
    // and "Purge eligible" still works against it.
  }
  const retentionInput = document.getElementById('notification-purge-retention-days');
  if (retentionInput) retentionInput.value = String(purgeRetentionDays);

  await loadHistory();
}

export async function loadAudit(services) {
  if (!document.getElementById('audit-body')) return;
  try {
    const { entries } = await services.audit();
    renderAudit(entries);
  } catch {
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

  let offset = 0;
  let limit = 50;
  let total = 0;
  let query = '';
  let loading = false;
  let requestSequence = 0;
  let activeListAbort = null;

  async function loadPage({
    targetOffset = offset,
    targetLimit = limit,
    targetQuery = search?.value.trim() || '',
    callerActiveId = null,
  } = {}) {
    clearTimeout(searchTimer);
    // Returning to the list abandons whatever was being opened. Without this,
    // opening an account, going back, and opening the same one again inside one
    // round trip would find the guard below still held and do nothing at all.
    opening = null;

    if (activeListAbort) {
      activeListAbort.abort();
      activeListAbort = null;
    }

    const mine = ++generation;
    const seq = ++requestSequence;
    const controller = new AbortController();
    activeListAbort = controller;

    const activeId = callerActiveId || document.activeElement?.id;
    loading = true;
    setPeopleLoading(true);

    try {
      const result = await services.users({
        q: targetQuery,
        limit: targetLimit,
        offset: targetOffset,
        signal: controller.signal,
      });
      if (mine !== generation || seq !== requestSequence) return;

      // Boundary drift fix: treat users.length === 0 && offset > 0 as ambiguous
      // regardless of total, reset to offset 0 and refetch once unconditionally.
      if (result.users && result.users.length === 0 && targetOffset > 0) {
        offset = 0;
        return await loadPage({ targetOffset: 0, targetLimit, targetQuery });
      }

      offset = typeof result.offset === 'number' ? result.offset : targetOffset;
      limit = typeof result.limit === 'number' ? result.limit : targetLimit;
      total = typeof result.total === 'number' ? result.total : result.users?.length || 0;
      query = targetQuery;

      showAccountList();
      renderUsers({
        users: result.users || [],
        total,
        self_id: result.self_id,
        offset,
        limit,
        loading: false,
        activeId,
      });
    } catch (error) {
      if (error?.name === 'AbortError' || controller.signal.aborted) {
        return;
      }
      if (mine !== generation || seq !== requestSequence) return;
      showAccountList();
      showPeopleMessage(I18n.t('admin.people.loadFailed'));
    } finally {
      if (seq === requestSequence) {
        loading = false;
        setPeopleLoading(false);
        if (activeListAbort === controller) {
          activeListAbort = null;
        }
      }
    }
  }

  /* The detail view is reachable only from this list, and the list serves one
     page of 50. Without a search box it is a door with no corridor the moment an
     instance has more accounts than that — the API and the RPC have taken `q`
     since they were written. */
  search?.addEventListener('input', () => {
    clearTimeout(searchTimer);
    offset = 0;
    if (activeListAbort) {
      activeListAbort.abort();
      activeListAbort = null;
    }
    searchTimer = setTimeout(() => {
      loadPage({
        targetOffset: 0,
        targetLimit: limit,
        targetQuery: search.value.trim(),
        callerActiveId: 'people-search',
      });
    }, 300);
  });

  async function openAccount(userId) {
    if (opening === userId) return;
    opening = userId;
    clearTimeout(searchTimer);
    if (activeListAbort) {
      activeListAbort.abort();
      activeListAbort = null;
    }
    const mine = ++generation;
    try {
      const { user, self_id: selfId } = await services.user(userId);
      // The activity is a second request and is allowed to fail on its own: a
      // log outage should not stop an operator seeing who they are looking at.
      let entries = [];
      try {
        entries = (await services.audit({ targetType: 'user', targetId: userId })).entries;
      } catch {
        entries = null;
      }
      if (mine !== generation) return;
      renderAccountDetail(user, entries, selfId);
    } catch {
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

  await loadPage();

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
        I18n.t(PROFILE_REFUSALS[code] || 'admin.account.profileSaveFailed'),
        true,
      );
    }
  });

  body.addEventListener('change', async (event) => {
    if (event.target.id === 'people-page-size') {
      const newSize = parseInt(event.target.value, 10);
      if (![25, 50, 100, 200].includes(newSize)) return;
      limit = newSize;
      offset = 0;
      await loadPage({
        targetOffset: 0,
        targetLimit: limit,
        targetQuery: query,
        callerActiveId: 'people-page-size',
      });
    }
  });

  body.addEventListener('click', async (event) => {
    if (event.target.closest('#account-back')) {
      await loadPage({ targetOffset: offset, targetLimit: limit, targetQuery: query });
      document.querySelector('.admin-account-open')?.focus();
      return;
    }

    const prevBtn = event.target.closest('#people-prev');
    if (prevBtn) {
      if (loading || offset <= 0) return;
      prevBtn.disabled = true;
      const targetOffset = Math.max(0, offset - limit);
      await loadPage({
        targetOffset,
        targetLimit: limit,
        targetQuery: query,
        callerActiveId: 'people-prev',
      });
      return;
    }

    const nextBtn = event.target.closest('#people-next');
    if (nextBtn) {
      if (loading || offset + limit >= total) return;
      nextBtn.disabled = true;
      const targetOffset = offset + limit;
      await loadPage({
        targetOffset,
        targetLimit: limit,
        targetQuery: query,
        callerActiveId: 'people-next',
      });
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
          'auth_admin_unavailable',
          'auth_admin_unreachable',
          'auth_admin_failed',
          'no_such_account',
          'actor_no_longer_administrator',
        ];
        ErrorHandler.showToast(
          known.includes(code)
            ? I18n.t(`admin.account.${code}`)
            : I18n.t('admin.account.revokeFailed'),
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
      if (
        !window.confirm(I18n.t('admin.account.confirmEmailChange', { email, newEmail: trimmed }))
      ) {
        return;
      }

      button.disabled = true;
      try {
        await services.changeEmail(userId, trimmed);
        ErrorHandler.showToast(I18n.t('admin.account.emailChangeAccepted'));
      } catch (error) {
        const code = error instanceof AdminRequestError ? error.code : null;
        const known = [
          'email_already_registered',
          'auth_admin_unavailable',
          'auth_admin_unreachable',
          'auth_admin_failed',
          'no_such_account',
          'same_email',
          'invalid_email',
          'cannot_change_own_email',
          'actor_no_longer_administrator',
          'too_long',
        ];
        ErrorHandler.showToast(
          known.includes(code)
            ? I18n.t(`admin.account.${code}`)
            : I18n.t('admin.account.emailChangeFailed'),
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
      else await loadPage({ targetOffset: offset, targetLimit: limit, targetQuery: query });
      loadAudit(services);
    } catch (error) {
      // A 409 is the system refusing on principle — it understood perfectly.
      // It gets the specific sentence rather than a generic failure, because
      // "you cannot demote yourself" is actionable and "something went wrong"
      // is not.
      const code = error instanceof AdminRequestError ? error.code : null;
      const known = [
        'cannot_change_own_access',
        'would_leave_no_administrator',
        'no_such_account',
        'actor_no_longer_administrator',
        'reason_required',
      ];
      ErrorHandler.showToast(
        known.includes(code) ? I18n.t(`admin.people.${code}`) : I18n.t('admin.people.changeFailed'),
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
  } catch {
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
          ErrorHandler.showToast(I18n.t(`admin.errors.${entry.code}`), true),
        );
        return;
      }
      ErrorHandler.showToast(I18n.t('admin.settings.saveFailed'), true);
    }
  });
}
