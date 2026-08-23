/**
 * SFDA Copilot — Privacy policy page entry point
 *
 * Public, ungated content. No Supabase, no identity — only the chrome every
 * page shares (theme, language), matching account.js's own "chrome first"
 * boot order for the same reason: a reader who cannot reach the rest of the
 * app for any reason still gets a themed, translated page.
 */

import { ThemeManager } from './modules/theme.js';
import { initLanguageToggle } from './modules/i18n.js';

document.addEventListener('DOMContentLoaded', () => {
  ThemeManager.init();
  initLanguageToggle();
});
