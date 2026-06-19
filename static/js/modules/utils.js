/**
 * SFDA Copilot — Small UI utilities (ripples, suggested-question pills).
 */

import { CONFIG } from './config.js';
import { DOMCache } from './dom.js';

export const Utils = {
  renderSuggestedQuestions(container, questions) {
    if (!container || !Array.isArray(questions) || !questions.length) return;

    Object.assign(container.style, { marginLeft: '12px', paddingLeft: '10px' });

    questions.forEach((question, index) => {
      const button = DOMCache.createElement('button', CONFIG.CLASSES.SUGGESTED_BUTTON);
      const icon = DOMCache.createElement('i', 'bi', 'bi-lightbulb-fill', CONFIG.CLASSES.SUGGESTED_ICON);

      icon.setAttribute('aria-hidden', 'true');
      button.appendChild(icon);
      button.appendChild(document.createTextNode(question));

      DOMCache.setAttributes(button, {
        'aria-label': `Ask: ${question}`,
        'data-question-text': question,
      });

      /* Staggered entrance */
      button.style.opacity = '0';
      button.style.animation = `messageSlideIn3D 0.3s ease ${index * 0.1}s forwards`;

      container.appendChild(button);
    });
  },

  /** Material-style ripple emanating from the click point. */
  addRippleEffect(button, event) {
    const rect = button.getBoundingClientRect();
    const ripple = DOMCache.createElement('span', 'ripple');
    const size = Math.max(rect.width, rect.height);

    ripple.style.width = ripple.style.height = `${size}px`;
    ripple.style.left = `${event.clientX - rect.left - size / 2}px`;
    ripple.style.top = `${event.clientY - rect.top - size / 2}px`;

    let container = button.querySelector('.ripple-container');
    if (!container) {
      container = DOMCache.createElement('div', 'ripple-container');
      button.appendChild(container);
    }
    container.appendChild(ripple);

    setTimeout(() => ripple.remove(), 600);
  },
};
