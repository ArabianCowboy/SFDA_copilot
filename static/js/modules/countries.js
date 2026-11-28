/**
 * SFDA Copilot — Country <select>, shared by the signup form and /account.
 *
 * The list comes from `public.countries` (Services.listCountries); only the
 * codes are trusted from it. Names are drawn in the page's language by the
 * browser's own CLDR data, because the table holds English names only, and
 * fall back to that English name where the browser has none.
 */

import { I18n } from './i18n.js';

/**
 * Fill `select` after its first (blank) option, sorted by the shown name,
 * and enable it. A select whose list never loaded stays disabled, and
 * callers read a disabled select as "Country not offered": it is left out
 * of the write rather than sent as a clear.
 */
export function fillCountrySelect(select, countries) {
  // An empty list is a failed read too: enabling it would offer only
  // "Not set", and saving would clear a stored Country.
  if (!select || !Array.isArray(countries) || !countries.length) return;
  const options = countries
    .map(({ code, name }) => new Option(countryName(code, name), code))
    .sort((a, b) => a.text.localeCompare(b.text, I18n.lang));
  select.replaceChildren(select.options[0], ...options);
  select.disabled = false;
}

/** A code's name in the page's language; `fallback` (else the code) where the
 * browser has none. */
export function countryName(code, fallback = code) {
  return (
    new Intl.DisplayNames([I18n.lang], { type: 'region', fallback: 'none' }).of(code) ?? fallback
  );
}

/** The value to write: a code, or undefined to leave the column alone. Never
 * null: once set, a Country can be changed but not cleared (Thaqib's C173,
 * adopted by the owner 2026-11-28). */
export function readCountrySelect(select) {
  if (!select || select.disabled) return undefined;
  return select.value || undefined;
}
