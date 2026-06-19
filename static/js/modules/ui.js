/**
 * SFDA Copilot — UI module
 * Message rendering, typing indicator, auth view transitions, FAQ list,
 * profile form population and send-button state.
 */

import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.0/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.0.8/+esm';

import { CONFIG } from './config.js';
import { DOMCache, AppState } from './dom.js';
import { Utils } from './utils.js';
import { Effects } from './effects.js';
import { ThemeManager } from './theme.js';
import { RobotStateManager } from './robot.js';

function createMessageContent(text, isBot) {
  const contentDiv = DOMCache.createElement('div', 'message-content');
  if (isBot) {
    contentDiv.innerHTML = DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } });
  } else {
    contentDiv.textContent = text;
  }
  return contentDiv;
}

function createMessageElement(text, sender) {
  const isBot = sender === 'bot';
  const messageWrapper = DOMCache.createElement(
    'div', 'message', isBot ? 'chatbot-message' : 'user-message', 'mb-3', 'message-medium'
  );
  const messageBubble = DOMCache.createElement('div', 'message-bubble');

  if (isBot) {
    const avatarDiv = DOMCache.createElement('div', 'avatar', 'mb-2');
    avatarDiv.innerHTML = RobotStateManager.createAvatarHTML();
    messageBubble.appendChild(avatarDiv);
  }

  messageBubble.appendChild(createMessageContent(text, isBot));

  const timestampEl = DOMCache.createElement('div', 'timestamp');
  timestampEl.textContent = new Date().toLocaleTimeString();
  messageBubble.appendChild(timestampEl);

  messageWrapper.appendChild(messageBubble);

  if (isBot) {
    messageWrapper.appendChild(DOMCache.createElement('div', CONFIG.CLASSES.SUGGESTED_CONTAINER, 'mt-2'));
  }

  return messageWrapper;
}

export const UI = {
  scrollMessagesToBottom() {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    container?.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
  },

  addMessage(text, sender, suggestedQuestions = []) {
    const messageEl = createMessageElement(text, sender);
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!container) return;

    const render = () => {
      container.appendChild(messageEl);

      if (sender === 'bot') {
        messageEl.querySelectorAll('ul, ol').forEach(el => el.classList.add(CONFIG.CLASSES.MESSAGE_LIST));
        messageEl.querySelectorAll('pre code').forEach(el => el.parentElement?.classList.add(CONFIG.CLASSES.MESSAGE_CODE_BLOCK));
        messageEl.querySelectorAll(':not(pre) > code').forEach(el => el.classList.add(CONFIG.CLASSES.MESSAGE_INLINE_CODE));

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
      const wrapper = DOMCache.createElement('div', 'message', 'chatbot-message', 'message-medium');
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

  updateAuthUI(user) {
    const isLoggedIn = !!user;
    const statusText = isLoggedIn ? `Logged in as: ${user.email}` : 'Not logged in';

    DOMCache.getAll(`${CONFIG.SELECTORS.USER_STATUS}, ${CONFIG.SELECTORS.USER_STATUS_OFFCANVAS}`).forEach(el => {
      if (el) el.textContent = statusText;
    });

    const unauthView = DOMCache.get(CONFIG.SELECTORS.UNAUTH_VIEW);
    const authView = DOMCache.get(CONFIG.SELECTORS.AUTH_VIEW);
    const companionBody = document.getElementById('robot-companion-body');
    const companion = document.getElementById('robot-companion');

    if (isLoggedIn) {
      /* --- Cinematic dual-robot hand-off: landing robot flies up, chat robot enters --- */
      const landingRobot = document.getElementById('landing-robot');
      const landingRobotBody = document.getElementById('landing-robot-body');
      const landingRobotStatus = document.getElementById('landing-robot-status');

      if (landingRobot) {
        landingRobot.classList.add('robot-exit');
        if (landingRobotBody) RobotStateManager._spawnReactionAt(landingRobotBody);
      }
      if (landingRobotStatus) landingRobotStatus.textContent = 'See you in the chat! 🚀';

      setTimeout(() => {
        if (companionBody) {
          companionBody.style.animation = 'none';
          companionBody.offsetHeight; /* force reflow */
          companionBody.style.animation = 'robotCompanionEntrance 1.2s cubic-bezier(0.25, 0.46, 0.45, 0.94) both';
          companionBody.classList.add('robot-entrance');
        }
        if (companion) companion.style.opacity = '1';
        RobotStateManager._spawnReactionParticles();
      }, 600);

      setTimeout(() => {
        if (unauthView) {
          unauthView.classList.add(CONFIG.CLASSES.D_NONE);
          const particles = AppState.get('particleBackground');
          if (particles) {
            particles.destroy();
            AppState.set('particleBackground', null);
          }
        }
        if (authView) {
          authView.classList.remove(CONFIG.CLASSES.D_NONE);
          authView.style.animation = 'viewFadeIn 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards';
        }
      }, 300);
    } else {
      if (authView) authView.classList.add(CONFIG.CLASSES.D_NONE);
      if (unauthView) {
        unauthView.classList.remove(CONFIG.CLASSES.D_NONE);
        unauthView.style.animation = 'viewFadeIn 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards';
        setTimeout(() => Effects.initParticles(), 100);
      }
    }

    const authButtonSelectors = [CONFIG.SELECTORS.AUTH_BTN, CONFIG.SELECTORS.AUTH_BTN_OFFCANVAS, CONFIG.SELECTORS.AUTH_BTN_MAIN];
    const userButtonSelectors = [CONFIG.SELECTORS.LOGOUT_BTN, CONFIG.SELECTORS.LOGOUT_BTN_OFFCANVAS, CONFIG.SELECTORS.PROFILE_BTN, CONFIG.SELECTORS.PROFILE_BTN_OFFCANVAS];

    DOMCache.getAll([...authButtonSelectors, ...userButtonSelectors].join(', ')).forEach(btn => {
      if (!btn) return;
      const isAuthButton = authButtonSelectors.some(sel => btn.matches(sel));
      btn.classList.toggle(CONFIG.CLASSES.D_NONE, isAuthButton ? isLoggedIn : !isLoggedIn);
    });
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
      DOMCache.get(CONFIG.SELECTORS.SEND_BTN),
      ...DOMCache.getAll(`.${CONFIG.CLASSES.FAQ_BUTTON}`),
      ...DOMCache.getAll(`.${CONFIG.CLASSES.SUGGESTED_BUTTON}`),
    ].filter(Boolean);

    elementsToToggle.forEach(el => { el.disabled = isSending; });

    const sendBtn = DOMCache.get(CONFIG.SELECTORS.SEND_BTN);
    if (sendBtn) {
      const originalText = AppState.get('originalSendButtonText') || 'Send';
      sendBtn.innerHTML = isSending
        ? '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Sending...'
        : `<i class="bi bi-send"></i> ${originalText}`;
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
