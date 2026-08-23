/**
 * SFDA Copilot — Account page entry point
 *
 * Deliberately not `app.js`. That file boots the chat shell — a composer, a
 * transcript, a mascot — none of which exist on this page. Only the shared
 * modules are reused: theme, language, i18n, the Supabase transport.
 *
 * Identity and Preferences read and write straight from the browser to
 * Supabase, under RLS (Decision 8 of docs/profile-refactor-plan.md) — there
 * is no Flask API for them. `/api/identity` is called once, only for the
 * standing line's role/tier/since/conversation-count/standing, which cannot
 * come from `profiles` at all (see that route's own docstring).
 */

import { Services } from './modules/services.js';
import { ThemeManager } from './modules/theme.js';
import { initLanguageToggle } from './modules/i18n.js';
import {
  showRecord,
  showSignedOut,
  showLoadFailed,
  renderRecordHead,
  renderStanding,
  populateIdentityForm,
  populatePreferences,
  populateConsent,
} from './account/ui.js';
import {
  bindIdentityForm,
  bindThemeChoice,
  bindLanguageChoice,
  bindPasswordForm,
  bindSignOutOthers,
  bindExportConversations,
  bindDeleteAllConversations,
  bindConsentToggle,
} from './account/handlers.js';

const Account = {
  async init() {
    // Chrome first, unconditionally — a reader who turns out to be signed
    // out still gets a themed, translated page with a way back.
    ThemeManager.init();
    initLanguageToggle();
    bindThemeChoice();
    bindLanguageChoice();
    document
      .getElementById('account-gate-retry')
      ?.addEventListener('click', () => location.reload());

    if (!window.SUPABASE_URL || !window.SUPABASE_ANON_KEY) {
      showLoadFailed();
      return;
    }

    try {
      Services.init();

      const token = await Services.getSessionToken();
      if (!token) {
        showSignedOut();
        return;
      }

      const { data: sessionData } = await Services.supabase.auth.getSession();
      const user = sessionData?.session?.user;
      if (!user) {
        showSignedOut();
        return;
      }

      // Fresh read on open, never a cached snapshot from elsewhere on the
      // site (docs/profile-refactor-plan.md §0.3-H) — this page has no
      // shared AppState to be stale against in the first place, but the
      // principle is the same: what is shown here is what is true now.
      const [profile, identity] = await Promise.all([
        Services.getProfile(user.id),
        Services.getIdentity().catch(() => null),
      ]);

      renderRecordHead(profile, user);
      renderStanding({
        role: identity?.role,
        tier: identity?.tier,
        isAdmin: identity?.is_admin,
        isDisabled: identity?.is_disabled,
        createdAt: identity?.created_at,
        conversationCount: identity?.conversation_count,
      });
      populateIdentityForm(profile || {});
      populatePreferences(profile || {});
      populateConsent(profile || {});
      bindIdentityForm(() => user.id);
      bindPasswordForm();
      bindSignOutOthers();
      bindConsentToggle(() => user.id);
      bindExportConversations();
      bindDeleteAllConversations();

      showRecord();
    } catch (error) {
      console.error('[SFDA Copilot account] failed to load', error);
      showLoadFailed();
    }
  },
};

document.addEventListener('DOMContentLoaded', () => Account.init());
