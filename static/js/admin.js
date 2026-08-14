/**
 * SFDA Copilot — Console entry point
 *
 * Deliberately not `app.js`. That file boots the chat shell and binds selectors
 * that do not exist on this page; importing it here would wire a mascot, a
 * composer and a transcript into a console and fail loudly on the first missing
 * node. Only the genuinely shared modules are reused — theme, language, i18n,
 * and the Supabase transport.
 *
 * The order below is the whole security posture of this page:
 *
 *   1. Render chrome. The server already did; nothing privileged is in it.
 *   2. Resolve a bearer token from the Supabase session in localStorage.
 *   3. Ask the server whether this person is an administrator.
 *   4. Only then reveal the console.
 *
 * Step 3 is the authority. Step 2 cannot be, because a token is just a claim,
 * and step 4 never runs on the strength of anything the page already held.
 *
 * @version 3.0.0
 */

import { Services } from './modules/services.js';
import { ThemeManager } from './modules/theme.js';
import { initLanguageToggle } from './modules/i18n.js';
import { AdminRequestError, createAdminServices } from './admin/services.js';
import { revealConsole, selectTab } from './admin/ui.js';
import {
  bindConsoleEvents,
  initPeopleTab,
  initSettingsTab,
  loadAudit,
  showAccessFailure,
} from './admin/handlers.js';

const Admin = {
  async init() {
    // Chrome first, and unconditionally: a reader who is refused should still
    // get a themed, translated page with a way back to the chat, not a
    // half-painted one.
    ThemeManager.init();
    initLanguageToggle();
    bindConsoleEvents();
    selectTab('tab-overview');

    if (!window.SUPABASE_URL || !window.SUPABASE_ANON_KEY) {
      showAccessFailure(new Error('supabase-not-configured'));
      return;
    }

    try {
      Services.init();
      const token = await Services.getSessionToken();
      if (!token) {
        // No session at all. Raised as the same type the server would have
        // produced, so there is one path through describeAccessFailure rather
        // than a second shape that only looks like an error — a plain object
        // would miss the instanceof check and be reported as a fault.
        showAccessFailure(new AdminRequestError(401, 'no_session'));
        return;
      }

      const services = createAdminServices(token);
      const identity = await services.identity();
      revealConsole(identity);

      // Only after the console is revealed, and deliberately not awaited: a
      // panel that fails to load should leave the rest of the console usable
      // rather than take the page down with it.
      initSettingsTab(services);
      initPeopleTab(services);
      loadAudit(services);
    } catch (error) {
      showAccessFailure(error);
    }
  },
};

document.addEventListener('DOMContentLoaded', () => Admin.init());
