/**
 * SFDA Copilot — Icons
 *
 * Path data lives in ONE place, web/utils/icons.py, and the runtime subset is
 * inlined into the page as `window.__ICONS` (the same trick `window.__I18N`
 * uses). That keeps the server-rendered markup and the DOM these modules build
 * drawing from the same set, with no second request and no CSP change.
 *
 * Every glyph is `fill="currentColor"` on a 16-unit grid, so an icon takes the
 * colour of whatever names it and follows the theme without a rule of its own.
 * That is the whole reason the icon font and the emoji went away: neither could
 * do either.
 */

const REGISTRY = window.__ICONS || {};
const CATEGORY = window.__CATEGORY_ICONS || {};

/**
 * The glyph for a corpus category, from the server's own mapping.
 *
 * Not a copy of it: web/utils/icons.py owns CATEGORY_ICONS and ships it as
 * window.__CATEGORY_ICONS, because a category that gains a glyph in Jinja and
 * not in the browser is the drift this indirection exists to prevent.
 */
export function categoryIcon(category) {
  return CATEGORY[String(category || '').trim().toLowerCase()] || '';
}

/**
 * One icon as an SVG string, for the places that assemble innerHTML.
 * An unknown name returns '' rather than a broken element — a missing glyph
 * should cost a blank space, never a layout.
 */
export function iconMarkup(name, size = 16, cls = '') {
  const paths = REGISTRY[name];
  if (!paths) return '';
  const classes = `icon ${cls}`.trim();
  return `<svg class="${classes}" width="${size}" height="${size}" viewBox="0 0 16 16"` +
    ` fill="currentColor" aria-hidden="true" focusable="false">${paths}</svg>`;
}

/**
 * One icon as a real element, for the places that build DOM node by node.
 * Returns null when the name is unknown so callers can skip appending.
 */
export function iconElement(name, size = 16, cls = '') {
  const markup = iconMarkup(name, size, cls);
  if (!markup) return null;
  const template = document.createElement('template');
  template.innerHTML = markup;
  return template.content.firstElementChild;
}
