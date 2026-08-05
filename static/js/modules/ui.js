/**
 * SFDA Copilot — UI module
 * Message rendering, typing indicator, FAQ list, profile form population and
 * send-button state.
 */

import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.2/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.4.12/+esm';

import { CONFIG } from './config.js';
import { DOMCache } from './dom.js';
import { AppState } from './state.js';
import { Utils } from './utils.js';
import { ThemeManager } from './theme.js';
import { RobotStateManager } from './robot.js';
import { bindCitations, renderSourceDeck, nextMessageId } from './citations.js';

function createMessageContent(text, isBot) {
  const contentDiv = DOMCache.createElement('div', 'message-content');
  if (isBot) {
    contentDiv.innerHTML = DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } });
  } else {
    contentDiv.textContent = text;
  }
  return contentDiv;
}

function createMessageElement(text, sender, msgId) {
  const isBot = sender === 'bot';
  const messageWrapper = DOMCache.createElement(
    'div', 'message', isBot ? 'chatbot-message' : 'user-message', 'mb-3'
  );
  if (msgId) messageWrapper.dataset.msgId = msgId;

  const messageBubble = DOMCache.createElement('div', 'message-bubble');

  if (isBot) {
    const avatarDiv = DOMCache.createElement('div', 'avatar');
    avatarDiv.innerHTML = RobotStateManager.createAvatarHTML();
    messageBubble.appendChild(avatarDiv);
  }

  const content = createMessageContent(text, isBot);
  /* dir="auto" so an Arabic answer lays out RTL inside an LTR page, and an
     English answer lays out LTR inside an Arabic one. */
  content.setAttribute('dir', 'auto');
  messageBubble.appendChild(content);

  const timestampEl = DOMCache.createElement('time', 'timestamp');
  const now = new Date();
  timestampEl.textContent = now.toLocaleTimeString();
  timestampEl.dateTime = now.toISOString();
  messageBubble.appendChild(timestampEl);

  messageWrapper.appendChild(messageBubble);

  if (isBot) {
    messageWrapper.appendChild(DOMCache.createElement('div', CONFIG.CLASSES.SUGGESTED_CONTAINER));
  }

  return messageWrapper;
}

/** Apply the markdown class hooks the stylesheet expects. */
function decorateMarkdown(scope) {
  scope.querySelectorAll('ul, ol').forEach(el => {
    if (!el.closest('.source-deck')) el.classList.add(CONFIG.CLASSES.MESSAGE_LIST);
  });
  scope.querySelectorAll('pre code').forEach(el => el.parentElement?.classList.add(CONFIG.CLASSES.MESSAGE_CODE_BLOCK));
  scope.querySelectorAll(':not(pre) > code').forEach(el => el.classList.add(CONFIG.CLASSES.MESSAGE_INLINE_CODE));
}

export const UI = {
  /**
   * Fill any server-rendered `<time data-ts-now>` with the reader's local time.
   * The welcome bubble's timestamp used to be a `{{ now }}` Jinja variable that
   * was never provided, so it always shipped empty.
   */
  hydrateTimestamps() {
    const now = new Date();
    document.querySelectorAll('[data-ts-now]').forEach(el => {
      el.textContent = now.toLocaleTimeString();
      el.dateTime = now.toISOString();
    });
  },

  scrollMessagesToBottom() {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    container?.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
  },

  addMessage(text, sender, suggestedQuestions = [], sources = []) {
    const msgId = sender === 'bot' ? nextMessageId() : null;
    const messageEl = createMessageElement(text, sender, msgId);
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!container) return;

    const render = () => {
      container.appendChild(messageEl);

      if (sender === 'bot') {
        const content = messageEl.querySelector('.message-content');
        decorateMarkdown(messageEl);
        bindCitations(content, sources, msgId);

        if (Array.isArray(sources) && sources.length) {
          messageEl.insertBefore(
            renderSourceDeck(sources, msgId),
            messageEl.querySelector(`.${CONFIG.CLASSES.SUGGESTED_CONTAINER}`)
          );
        }

        const suggestionsContainer = messageEl.querySelector(`.${CONFIG.CLASSES.SUGGESTED_CONTAINER}`);
        Utils.renderSuggestedQuestions(suggestionsContainer, suggestedQuestions);
      }
      this.scrollMessagesToBottom();
    };

    AppState.get('viewTransitionEnabled') ? document.startViewTransition(render) : render();
  },

  toggleTypingIndicator(show) {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!container) return;

    const indicatorId = CONFIG.CLASSES.TYPING_INDICATOR_ID;
    const existingIndicator = document.getElementById(indicatorId);

    if (show && !existingIndicator) {
      const wrapper = DOMCache.createElement('div', 'message', 'chatbot-message');
      wrapper.id = indicatorId;
      wrapper.style.opacity = '1';

      const bubble = DOMCache.createElement('div', 'message-bubble');
      const avatarDiv = DOMCache.createElement('div', 'avatar', 'mb-2');
      avatarDiv.innerHTML = RobotStateManager.createAvatarHTML();
      bubble.appendChild(avatarDiv);

      const indicator = DOMCache.createElement('div', 'typing-indicator');
      for (let i = 0; i < 3; i++) indicator.appendChild(DOMCache.createElement('div', 'dot'));
      bubble.appendChild(indicator);
      wrapper.appendChild(bubble);
      container.appendChild(wrapper);
      this.scrollMessagesToBottom();
    } else if (!show && existingIndicator) {
      existingIndicator.style.opacity = '0';
      existingIndicator.style.transform = 'translateY(10px)';
      setTimeout(() => existingIndicator.remove(), 200);
    }
  },

  populateProfileForm(profile) {
    const form = DOMCache.get(CONFIG.SELECTORS.PROFILE_FORM);
    if (!profile || !form) return;

    const { full_name = '', organization = '', specialization = '' } = profile;

    const fullNameInput = form.querySelector('#profile-full-name');
    const orgInput = form.querySelector('#profile-organization');
    const specInput = form.querySelector('#profile-specialization');

    if (fullNameInput) fullNameInput.value = full_name;
    if (orgInput) orgInput.value = organization;
    if (specInput) specInput.value = specialization;

    const themeRadio = form.querySelector(`input[name="theme-preference"][value="${ThemeManager.getCurrent()}"]`);
    if (themeRadio) themeRadio.checked = true;
  },

  setSendingState(isSending) {
    AppState.setRequestInProgress(isSending);

    const elementsToToggle = [
      DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT),
      ...DOMCache.getAll(`.${CONFIG.CLASSES.FAQ_BUTTON}`),
      ...DOMCache.getAll(`.${CONFIG.CLASSES.SUGGESTED_BUTTON}`),
    ].filter(Boolean);

    elementsToToggle.forEach(el => { el.disabled = isSending; });

    const sendBtn = DOMCache.get(CONFIG.SELECTORS.SEND_BTN);
    if (sendBtn) {
      const originalText = AppState.get('originalSendButtonText') || 'Send';
      sendBtn.innerHTML = isSending
        ? '<i class="bi bi-stop-circle"></i> Cancel'
        : `<i class="bi bi-send"></i> ${originalText}`;
      sendBtn.setAttribute(
        'aria-label',
        isSending ? 'Cancel message' : 'Send message'
      );
    }
  },

  Faq: {
    renderButtons(faqData) {
      const faqSections = [DOMCache.get(CONFIG.SELECTORS.FAQ_SIDEBAR), DOMCache.get(CONFIG.SELECTORS.FAQ_OFFCANVAS)].filter(Boolean);
      if (!faqSections.length) return;

      const createFaqContent = () => {
        const fragment = document.createDocumentFragment();
        let itemIndex = 0;

        for (const [category, data] of Object.entries(faqData || {})) {
          if (!data?.questions?.length) continue;

          const header = DOMCache.createElement('h4', 'ps-2', 'mt-3');
          header.innerHTML = `<i class="bi ${data.icon || 'bi-question-circle'}"></i>${data.title || category}`;

          const nav = DOMCache.createElement('nav', 'nav', 'nav-pills', 'flex-column');

          for (const { short, text } of data.questions) {
            if (!short || !text) continue;
            const button = DOMCache.createElement('button', 'nav-link', CONFIG.CLASSES.FAQ_BUTTON);
            DOMCache.setAttributes(button, { 'data-category': category, 'data-question': text });
            button.textContent = short;

            button.style.opacity = '0';
            button.style.animation = `faqSlideIn 0.3s ease ${itemIndex * 0.05}s forwards`;
            itemIndex++;

            nav.appendChild(button);
          }

          fragment.appendChild(header);
          fragment.appendChild(nav);
        }

        return fragment;
      };

      faqSections.forEach((section, index) => {
        section.innerHTML = '';
        const content = createFaqContent();
        if (content.childElementCount > 0) {
          section.appendChild(index === 0 ? content : content.cloneNode(true));
          section.querySelector('h4:first-of-type')?.classList.remove('mt-3');
        } else {
          section.innerHTML = '<div class="text-secondary small text-center py-3">No FAQs available.</div>';
        }
      });
    },

    clearButtons() {
      DOMCache.getAll(`${CONFIG.SELECTORS.FAQ_SIDEBAR}, ${CONFIG.SELECTORS.FAQ_OFFCANVAS}`).forEach(section => {
        section.innerHTML = '';
      });
    },
  },
};
