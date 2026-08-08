/**
 * SFDA Copilot — Small UI utilities (suggested-question pills).
 */

import { CONFIG } from './config.js';
import { DOMCache } from './dom.js';
import { I18n } from './i18n.js';
import { iconElement } from './icons.js';

export const Utils = {
  renderSuggestedQuestions(container, questions) {
    if (!container || !Array.isArray(questions) || !questions.length) return;

    questions.forEach((question, index) => {
      const button = DOMCache.createElement('button', CONFIG.CLASSES.SUGGESTED_BUTTON);
      const icon = iconElement('lightbulb', 13, CONFIG.CLASSES.SUGGESTED_ICON);

      if (icon) button.appendChild(icon);
      button.appendChild(document.createTextNode(question));

      DOMCache.setAttributes(button, {
        'aria-label': I18n.t('chat.askPrefix', { question }),
        'data-question-text': question,
      });

      /* Staggered entrance */
      button.style.opacity = '0';
      button.style.animation = `messageSlideIn3D 0.3s ease ${index * 0.1}s forwards`;

      container.appendChild(button);
    });
  },
};
