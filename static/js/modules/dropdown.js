/**
 * SFDA Copilot — Category selector
 *
 * A styled listbox mirrored to a hidden <select> so the chat logic keeps a
 * single source of truth for the selected category.
 *
 * The options used to carry their glyph as an emoji in `data-icon` and the
 * trigger copied it across with textContent. Emoji render per-platform, ignore
 * currentColor and cannot follow the theme, so `data-icon` now holds an icon
 * NAME and the markup is rebuilt from the shared registry.
 */

import { iconMarkup } from './icons.js';

export const CustomDropdown = {
  init() {
    const dropdown = document.getElementById('category-dropdown');
    if (!dropdown) return;

    const trigger = dropdown.querySelector('.custom-dropdown-trigger');
    const menu = dropdown.querySelector('.custom-dropdown-menu');
    const items = [...dropdown.querySelectorAll('.custom-dropdown-item')];
    const hiddenSelect = document.getElementById('query-category-hidden');

    if (!trigger || !menu || !items.length) return;

    const isOpen = () => dropdown.classList.contains('open');

    /**
     * @param {boolean} open
     * @param {boolean} [restoreFocus] move focus back to the trigger when the
     *   menu closes while focus is still inside it. Default true; Tab passes
     *   false so the browser's own focus move is not fought.
     */
    const setOpen = (open, restoreFocus = true) => {
      const wasOpen = dropdown.classList.contains('open');
      dropdown.classList.toggle('open', open);
      trigger.setAttribute('aria-expanded', String(open));

      if (open) {
        /* Style is recalculated lazily, and `focus()` is a NO-OP inside a
           `visibility: hidden` subtree — so focusing straight after toggling
           the class silently failed and left focus on the trigger. The first
           ArrowDown was then spent moving to the option that was already
           selected, and Enter re-picked the current value. Reading a layout
           property forces the flush. */
        void menu.offsetHeight;
        (items.find(i => i.classList.contains('active')) || items[0]).focus();
        return;
      }
      /* Closing hides the menu with `visibility: hidden`, which does NOT move
         focus. Without this, clicking anywhere outside left keyboard and
         screen-reader users focused on an option inside an invisible menu,
         with no way back except Tab. */
      if (wasOpen && restoreFocus && menu.contains(document.activeElement)) {
        trigger.focus();
      }
    };

    const select = (item) => {
      const { value, icon } = item.dataset;
      const text = item.querySelector('.dropdown-text')?.textContent.trim() ?? '';

      trigger.querySelector('.dropdown-icon').innerHTML = iconMarkup(icon, 15);
      trigger.querySelector('.dropdown-text').textContent = text;
      trigger.dataset.value = value;
      /* The trigger shows the value but not what the value IS, so the label
         the control lost when it moved into the composer lives here. */
      const prefix = trigger.dataset.labelPrefix || '';
      trigger.setAttribute('aria-label', `${prefix} ${text}`.trim());

      if (hiddenSelect) {
        hiddenSelect.value = value;
        hiddenSelect.dispatchEvent(new Event('change'));
      }

      items.forEach(i => {
        const on = i === item;
        i.classList.toggle('active', on);
        i.setAttribute('aria-selected', String(on));
      });
    };

    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      setOpen(!isOpen());
    });

    items.forEach(item => {
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        select(item);
        setOpen(false);
      });
    });

    /* Arrow keys, Home/End and type-ahead-free Enter/Space, so the control is
       operable without a pointer like the native <select> it replaces. */
    menu.addEventListener('keydown', (e) => {
      const current = items.indexOf(document.activeElement);
      let next = null;

      switch (e.key) {
        case 'ArrowDown': next = Math.min(items.length - 1, current + 1); break;
        case 'ArrowUp':   next = Math.max(0, current - 1); break;
        case 'Home':      next = 0; break;
        case 'End':       next = items.length - 1; break;
        case 'Enter':
        case ' ':
          if (current > -1) select(items[current]);
          setOpen(false);
          e.preventDefault();
          return;
        case 'Escape':
          setOpen(false);
          e.preventDefault();
          return;
        case 'Tab':
          // Close, but let the browser move focus onward from here.
          setOpen(false, false);
          return;
        default:
          return;
      }

      e.preventDefault();
      items[next]?.focus();
    });

    document.addEventListener('click', () => {
      if (isOpen()) setOpen(false);
    });

    /* Enter and Space are deliberately NOT handled here. The trigger is a
       <button>, so the browser already turns both into a click, and the click
       handler above already toggles — opening on keydown as well meant the
       menu opened and the synthesized click immediately shut it again. Arrow
       keys have no native behaviour on a button, so they are ours. */
    trigger.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        setOpen(true);
      } else if (e.key === 'Escape') {
        setOpen(false);
      }
    });
  },
};
