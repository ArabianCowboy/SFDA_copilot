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
import { MarkdownStream } from './stream-render.js';
import { I18n } from './i18n.js';
import { iconMarkup } from './icons.js';

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
  /* Locale-aware, and dir="auto" so bidi cannot reorder it: an en-US time
     dropped into an Arabic transcript rendered as "AM 3:17:18" because the
     RTL context reversed the run. The same string in `ar` is Arabic and must
     stay RTL, so the direction is detected rather than forced. */
  timestampEl.textContent = now.toLocaleTimeString(I18n.lang);
  timestampEl.dateTime = now.toISOString();
  timestampEl.setAttribute('dir', 'auto');
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
      el.textContent = now.toLocaleTimeString(I18n.lang);
      el.dateTime = now.toISOString();
      el.setAttribute('dir', 'auto');
    });
  },

  scrollMessagesToBottom() {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    container?.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    // Going to the bottom always clears the pill — including when the reader
    // sends a message, which should bring them back regardless of where they
    // had scrolled to.
    this.setJumpToLatest(false);
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

  /** True when the reader is at (or near) the bottom of the transcript. */
  isPinnedToBottom() {
    const c = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!c) return true;
    return c.scrollHeight - c.scrollTop - c.clientHeight < 80;
  },

  /**
   * Insert an empty bot bubble and return a MarkdownStream that fills it.
   *
   * This is the ONLY view-transition-wrapped call in the streaming path. A
   * view transition snapshots the whole page; running one per token would
   * freeze the tab.
   */
  beginStreamingMessage() {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!container) return null;

    const msgId = nextMessageId();
    const messageEl = createMessageElement('', 'bot', msgId);
    const content = messageEl.querySelector('.message-content');

    /* Announcing a 2000-character answer token by token makes the app
       unusable with a screen reader. #messages stays aria-live="polite" for
       completed messages; the in-flight one opts out and announces once at
       the end instead. */
    messageEl.setAttribute('aria-live', 'off');
    messageEl.setAttribute('aria-busy', 'true');

    const render = () => container.appendChild(messageEl);
    AppState.get('viewTransitionEnabled') ? document.startViewTransition(render) : render();

    const state = { sources: [] };
    const stream = new MarkdownStream(content, (scope) => {
      decorateMarkdown(scope);
      bindCitations(scope, state.sources, msgId);
    });

    return { msgId, messageEl, content, stream, state };
  },

  /** Auto-scroll only when the reader hasn't scrolled away. */
  followStream() {
    if (!this.isPinnedToBottom()) {
      // Content is arriving below the fold; flag it rather than yanking them back.
      this.setJumpToLatest(true, true);
      return;
    }
    const c = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    /* 'auto', not 'smooth': a smooth scroll target retargeted at 60Hz is
       visibly janky. The CSS smooth behaviour resumes once streaming ends. */
    c?.scrollTo({ top: c.scrollHeight, behavior: 'auto' });
  },

  /**
   * Show or hide the jump-to-latest pill.
   * @param {boolean} show
   * @param {boolean} [unread] mark that new content arrived below the fold
   */
  setJumpToLatest(show, unread = false) {
    const pill = document.getElementById('jump-to-latest');
    if (!pill) return;

    if (unread) pill.querySelector('.jump-dot')?.removeAttribute('hidden');

    if (show === !pill.hidden) return;   // already in the requested state

    pill.hidden = !show;
    // The entrance is a CSS animation keyed off :not([hidden]), so nothing
    // here depends on an animation frame ever arriving.
    if (!show) pill.querySelector('.jump-dot')?.setAttribute('hidden', '');
  },

  /**
   * Track scroll position and reveal the pill when the reader scrolls away
   * from the bottom, so a long answer streaming in never drags them along.
   */
  initJumpToLatest() {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    const pill = document.getElementById('jump-to-latest');
    if (!container || !pill) return;

    let queued = false;
    const sync = () => {
      queued = false;
      this.setJumpToLatest(!this.isPinnedToBottom());
    };

    // rAF-coalesced: scroll fires far more often than once per frame.
    container.addEventListener('scroll', () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(sync);
    }, { passive: true });

    /* rAF is throttled while the tab is hidden, so a scroll that happened just
       before backgrounding may not have synced. Re-check on return. */
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) sync();
    });

    pill.addEventListener('click', () => {
      this.setJumpToLatest(false);
      this.scrollMessagesToBottom();
    });
  },

  attachSourceDeck(handle, sources) {
    if (!handle || !Array.isArray(sources) || !sources.length) return;
    handle.state.sources = sources;
    handle.messageEl.insertBefore(
      renderSourceDeck(sources, handle.msgId),
      handle.messageEl.querySelector(`.${CONFIG.CLASSES.SUGGESTED_CONTAINER}`)
    );
  },

  finishStreamingMessage(handle, suggestedQuestions = []) {
    if (!handle) return;
    handle.stream.finish();
    this.setStage(handle, null);
    handle.messageEl.removeAttribute('aria-busy');
    handle.messageEl.setAttribute('aria-live', 'polite');

    const container = handle.messageEl.querySelector(`.${CONFIG.CLASSES.SUGGESTED_CONTAINER}`);
    Utils.renderSuggestedQuestions(container, suggestedQuestions);

    const count = handle.state.sources.length;
    this.announce(count
      ? I18n.t('cite.answerCompleteWithSources', { n: count })
      : I18n.t('cite.answerComplete'));
    this.scrollMessagesToBottom();
  },

  /** Mark a stream that failed or was cancelled, keeping whatever arrived. */
  markStreamIncomplete(handle, kind = 'error') {
    if (!handle) return;
    handle.stream.finish();
    this.setStage(handle, null);
    handle.messageEl.removeAttribute('aria-busy');
    handle.messageEl.classList.add(kind === 'cancelled' ? 'is-cancelled' : 'is-errored');

    const note = DOMCache.createElement('div', 'stream-note', kind);
    note.textContent = I18n.t(kind === 'cancelled' ? 'chat.stopped' : 'chat.incomplete');
    handle.messageEl.querySelector('.message-bubble')?.appendChild(note);
  },

  /** One-shot screen-reader announcement. */
  announce(message) {
    let region = document.getElementById('sr-announcer');
    if (!region) {
      region = DOMCache.createElement('div', 'sr-only');
      region.id = 'sr-announcer';
      region.setAttribute('role', 'status');
      region.setAttribute('aria-live', 'polite');
      document.body.appendChild(region);
    }
    region.textContent = message;
  },

  /** Honest retrieval progress, replacing the blind 800ms timer. */
  setStage(handle, text) {
    if (!handle) return;
    let line = handle.messageEl.querySelector('.stage-line');
    if (!text) { line?.remove(); return; }
    if (!line) {
      line = DOMCache.createElement('div', 'stage-line');
      line.innerHTML = '<span class="stage-dot"></span><span class="stage-text"></span>';
      handle.messageEl.querySelector('.message-bubble')?.prepend(line);
    }
    line.querySelector('.stage-text').textContent = text;
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
      const originalText = AppState.get('originalSendButtonText') || I18n.t('chat.send');
      sendBtn.innerHTML = isSending
        ? `${iconMarkup('stop', 16)}<span>${I18n.t('chat.cancel')}</span>`
        : `${iconMarkup('send', 16)}<span>${originalText}</span>`;
      sendBtn.setAttribute(
        'aria-label',
        isSending ? I18n.t('chat.cancelAria') : I18n.t('chat.sendAria')
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

          /* The glyph is the category's own — the same mark the composer's
             selector shows for it — so the two places a category appears
             never drift apart. */
          const header = DOMCache.createElement('h4');
          const label = DOMCache.createElement('span');
          label.textContent = data.title || category;
          header.innerHTML = iconMarkup(data.icon || 'question', 14);
          header.appendChild(label);

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
          /* The first group heads the rail, so it drops the separating rule
             and the space above it that every later group needs. */
          section.querySelector('h4:first-of-type')?.classList.add('is-first');
        } else {
          section.innerHTML = `<p class="faq-empty">${I18n.t('faq.empty')}</p>`;
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
