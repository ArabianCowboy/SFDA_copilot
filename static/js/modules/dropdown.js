/**
 * SFDA Copilot — Custom category dropdown
 * A styled dropdown mirrored to a hidden <select> so chat logic keeps a single
 * source of truth for the selected category.
 */

export const CustomDropdown = {
  init() {
    const trigger = document.querySelector('.custom-dropdown-trigger');
    const dropdown = document.getElementById('category-dropdown');
    const items = document.querySelectorAll('.custom-dropdown-item');
    const hiddenSelect = document.getElementById('query-category-hidden');

    if (!trigger || !dropdown || !items.length) return;

    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = dropdown.classList.contains('open');
      document.querySelectorAll('.custom-dropdown.open').forEach(d => d.classList.remove('open'));
      dropdown.classList.toggle('open', !isOpen);
      trigger.setAttribute('aria-expanded', String(!isOpen));
    });

    items.forEach(item => {
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        const { value, icon } = item.dataset;
        const text = item.textContent.trim();

        trigger.querySelector('.dropdown-icon').textContent = icon;
        trigger.querySelector('.dropdown-text').textContent = text;
        trigger.dataset.value = value;

        if (hiddenSelect) {
          hiddenSelect.value = value;
          hiddenSelect.dispatchEvent(new Event('change'));
        }

        items.forEach(i => i.classList.remove('active'));
        item.classList.add('active');

        dropdown.classList.remove('open');
        trigger.setAttribute('aria-expanded', 'false');
      });
    });

    document.addEventListener('click', () => {
      dropdown.classList.remove('open');
      trigger.setAttribute('aria-expanded', 'false');
    });

    trigger.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        trigger.click();
      } else if (e.key === 'Escape') {
        dropdown.classList.remove('open');
        trigger.setAttribute('aria-expanded', 'false');
      }
    });
  },
};
