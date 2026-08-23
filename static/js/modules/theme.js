/**
 * SFDA Copilot — Theme manager
 * Light/dark switching synced across every toggle button, persisted to
 * localStorage and reflected via the `data-bs-theme` attribute.
 */

import { CONFIG } from './config.js';
import { DOMCache, logError } from './dom.js';
import { I18n } from './i18n.js';
import { iconMarkup } from './icons.js';

export const ThemeManager = {
  init() {
    let storedTheme;
    try {
      storedTheme = localStorage.getItem('theme');
    } catch (error) {
      logError(error, 'ThemeManager.init');
      storedTheme = null;
    }

    const systemPrefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
    const defaultTheme =
      storedTheme || (systemPrefersDark ? CONFIG.CLASSES.DARK : CONFIG.CLASSES.LIGHT);

    this.apply(defaultTheme);
    this.initToggles();
  },

  getCurrent() {
    return document.documentElement.getAttribute('data-bs-theme') || CONFIG.CLASSES.LIGHT;
  },

  apply(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);
    try {
      localStorage.setItem('theme', theme);
    } catch (error) {
      logError(error, 'ThemeManager.apply');
    }
    this.updateToggleIcons();
  },

  toggle() {
    const newTheme =
      this.getCurrent() === CONFIG.CLASSES.DARK ? CONFIG.CLASSES.LIGHT : CONFIG.CLASSES.DARK;
    this.apply(newTheme);
    this.animateToggleButtons();
    this.announceChange(newTheme);
  },

  updateToggleIcons() {
    const isDark = this.getCurrent() === CONFIG.CLASSES.DARK;
    const glyph = isDark ? 'sun' : 'moon';
    const newTitle = isDark ? 'Switch to light theme' : 'Switch to dark theme';

    DOMCache.getAll(`.${CONFIG.CLASSES.THEME_TOGGLE}`).forEach((btn) => {
      btn.innerHTML = iconMarkup(glyph, 16);
      DOMCache.setAttributes(btn, {
        title: newTitle,
        'aria-label': newTitle,
        'aria-pressed': String(isDark),
      });
    });
  },

  initToggles() {
    this.updateToggleIcons();
    this.bindToggleEvents();
  },

  bindToggleEvents() {
    document.addEventListener('click', (e) => {
      if (e.target.closest(`.${CONFIG.CLASSES.THEME_TOGGLE}`)) {
        e.preventDefault();
        this.toggle();
      }
    });

    document.addEventListener('keydown', (e) => {
      if (
        e.target.closest(`.${CONFIG.CLASSES.THEME_TOGGLE}`) &&
        (e.key === 'Enter' || e.key === ' ')
      ) {
        e.preventDefault();
        this.toggle();
      }
    });
  },

  animateToggleButtons() {
    DOMCache.getAll(`.${CONFIG.CLASSES.THEME_TOGGLE}`).forEach((btn) => {
      const icon = btn.querySelector('.icon');
      if (icon) {
        icon.style.animation = 'none';
        icon.offsetHeight; /* force reflow */
        icon.style.animation = 'themeToggleSpin 0.5s ease';
      }
    });
  },

  announceChange(newTheme) {
    const announcement = DOMCache.createElement('div', 'sr-only');
    DOMCache.setAttributes(announcement, { role: 'status', 'aria-live': 'polite' });
    announcement.textContent = I18n.t('theme.announced', { mode: newTheme });
    document.body.appendChild(announcement);
    setTimeout(() => announcement.remove(), 1000);
  },
};
