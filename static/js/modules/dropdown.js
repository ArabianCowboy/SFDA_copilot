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

    const setOpen = (open) => {
      dropdown.classList.toggle('open', open);
      trigger.setAttribute('aria-expanded', String(open));
      if (open) {
        (items.find(i => i.classList.contains('active')) || items[0]).focus();
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
      const next = !isOpen();
      document.querySelectorAll('.custom-dropdown.open').forEach(d => d.classList.remove('open'));
      setOpen(next);
    });

    items.forEach(item => {
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        select(item);
        setOpen(false);
        trigger.focus();
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
          trigger.focus();
          e.preventDefault();
          return;
        case 'Escape':
        case 'Tab':
          setOpen(false);
          if (e.key === 'Escape') { trigger.focus(); e.preventDefault(); }
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

    trigger.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
        e.preventDefault();
        setOpen(true);
      } else if (e.key === 'Escape') {
        setOpen(false);
      }
    });
  },
};
