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
import { focusTab, selectTab, showGateMessage, tabIds } from './ui.js';

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
