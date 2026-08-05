/**
 * SFDA Copilot — Entrance choreography
 *
 * One orchestrated moment: feature cards reveal as they scroll into view.
 *
 * The canvas particle field, hero scroll/mouse parallax, per-card 3D tilt and
 * click ripples that used to live here were removed with the Dossier redesign.
 * They were ambient decoration on every surface at once, which left nothing as
 * the hero and cost a full repaint per mousemove.
 */

import { CONFIG, prefersReducedMotion } from './config.js';
import { DOMCache } from './dom.js';

export const Effects = {
  initCardAnimations() {
    const cards = DOMCache.getAll(`.${CONFIG.CLASSES.ANIMATE_CARD}`);
    if (!cards.length) return;

    if (prefersReducedMotion()) {
      cards.forEach(card => card.classList.add(CONFIG.CLASSES.REVEALED));
      return;
    }

    const observer = new IntersectionObserver(
      (entries, obs) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const delay = parseInt(entry.target.dataset.delay || '0', 10);
          setTimeout(() => entry.target.classList.add(CONFIG.CLASSES.REVEALED), delay);
          obs.unobserve(entry.target);
        });
      },
      { threshold: 0.1, rootMargin: '0px 0px -50px 0px' }
    );

    cards.forEach(card => observer.observe(card));
  },
};
