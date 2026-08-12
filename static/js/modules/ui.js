/**
 * SFDA Copilot — UI module
 * Message rendering, typing indicator, FAQ list, profile form population and
 * send-button state.
 */

import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.2/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.4.13/+esm';

import { CONFIG, prefersReducedMotion } from './config.js';
import { DOMCache } from './dom.js';
import { AppState } from './state.js';
import { Utils } from './utils.js';
import { ThemeManager } from './theme.js';
import { RobotStateManager } from './robot.js';
import { bindCitations, renderSourceTrigger, nextMessageId } from './citations.js';
import { SourcePanel } from './source-panel.js';
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
  /* No .source-deck exclusion any more: the sources are a panel outside the
     message subtree now, so the only lists in `scope` are the answer's own. */
  scope.querySelectorAll('ul, ol').forEach(el => el.classList.add(CONFIG.CLASSES.MESSAGE_LIST));
  scope.querySelectorAll('pre code').forEach(el => el.parentElement?.classList.add(CONFIG.CLASSES.MESSAGE_CODE_BLOCK));
  scope.querySelectorAll(':not(pre) > code').forEach(el => el.classList.add(CONFIG.CLASSES.MESSAGE_INLINE_CODE));
}

export const UI = {
  /**
   * Whether the transcript should keep following new content.
   *
   * This is intent, not geometry. It used to be recomputed from
   * `isPinnedToBottom()` at the moment content arrived, which cannot tell
   * "the reader scrolled up" apart from "we just inserted 560px of source
   * cards under them" — and the source deck lands BEFORE the first token.
   * The result was an answer that streamed entirely below the fold while the
   * reader looked at a jump pill.
   *
   * Content growth raises scrollHeight but never scrollTop, so tracking the
   * scrollTop delta separates the two cases exactly: only a scroll that moves
   * the reader UP stops the transcript following.
   */
  _follow: true,
  _lastScrollTop: 0,

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
    // Going to the bottom always clears the pill and resumes following —
    // including when the reader sends a message, which should bring them back
    // regardless of where they had scrolled to.
    this._follow = true;
    if (container) this._lastScrollTop = container.scrollTop;
    container?.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    this.setJumpToLatest(false);
  },

  addMessage(text, sender, suggestedQuestions = [], sources = [], meta = null) {
    const msgId = sender === 'bot' ? nextMessageId() : null;
    const messageEl = createMessageElement(text, sender, msgId);
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!container) return;

    /* Appended synchronously. This used to run inside document.startViewTransition,
       whose callback is deferred a frame — so anything downstream that measured
       or queried the transcript ran against a DOM the message was not in yet.
       That is not theoretical: it silently broke the closing scroll and the
       source deck whenever a whole answer arrived in one chunk. The entrance is
       already an authored CSS keyframe (botMessageIn / userMessageIn), so the
       transition was buying a full-page snapshot per message and no motion that
       was not already there. */
    const render = () => {
      container.appendChild(messageEl);

      if (sender === 'bot') {
        const content = messageEl.querySelector('.message-content');
        decorateMarkdown(messageEl);
        const bound = bindCitations(content, sources, msgId);

        // Only passages whose marker the reader can actually click. See the
        // note on bindCitations: this is what keeps the panel from offering a
        // source that markdown swallowed into a link or a code span.
        const reachable = sources.filter(s => bound.has(s.index));

        const trigger = renderSourceTrigger({
          sources: reachable,
          cited: meta?.cited ?? null,
          retrieved: meta?.retrieved ?? sources.length,
        }, msgId);
        if (trigger) {
          messageEl.insertBefore(
            trigger,
            messageEl.querySelector(`.${CONFIG.CLASSES.SUGGESTED_CONTAINER}`)
          );
        }

        const suggestionsContainer = messageEl.querySelector(`.${CONFIG.CLASSES.SUGGESTED_CONTAINER}`);
        Utils.renderSuggestedQuestions(suggestionsContainer, suggestedQuestions);
      }
      this.scrollMessagesToBottom();
      this.updateNewChatAvailability();
    };

    render();
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
   * The bubble is attached synchronously and deliberately: everything after
   * this — the source deck, the stage line, the closing scroll — measures or
   * queries the transcript, and all of it is wrong if the message is still
   * detached. See the note in addMessage.
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

    container.appendChild(messageEl);

    /* `bound` records which markers the last parse actually turned into
       buttons. It stays null until a parse has run against a non-empty
       payload, so "no parse yet" is distinguishable from "parsed, bound
       nothing" — the first must not be read as "this answer has no reachable
       sources". Sources arrive only on the terminal frame, so the per-frame
       calls during streaming are no-ops and the meaningful one is finish(). */
    const state = { sources: [], bound: null };
    const stream = new MarkdownStream(content, (scope) => {
      decorateMarkdown(scope);
      const bound = bindCitations(scope, state.sources, msgId);
      if (state.sources.length) state.bound = bound;
    });

    return { msgId, messageEl, content, stream, state };
  },

  /** Auto-scroll only when the reader hasn't scrolled away. */
  followStream() {
    if (!this._follow) {
      // Content is arriving below the fold; flag it rather than yanking them back.
      this.setJumpToLatest(true, true);
      return;
    }
    const c = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!c) return;
    /* 'auto', not 'smooth': a smooth scroll target retargeted at 60Hz is
       visibly janky. The CSS smooth behaviour resumes once streaming ends. */
    c.scrollTo({ top: c.scrollHeight, behavior: 'auto' });
    this._lastScrollTop = c.scrollTop;
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

    this._lastScrollTop = container.scrollTop;

    let queued = false;
    const sync = () => {
      queued = false;
      /* Being at the bottom always means following, and it is checked AFTER
         the intent decision below rather than as its `else` branch. Shrinking
         the transcript — collapsing an expanded deck — makes the browser clamp
         scrollTop downward, which looks exactly like an upward scroll; without
         this the reader got a jump pill telling them to jump to where they
         already were. This check reads layout, so it stays coalesced. */
      if (this.isPinnedToBottom()) this._follow = true;
      this.setJumpToLatest(!this._follow);
    };

    container.addEventListener('scroll', () => {
      /* Intent is recorded HERE, synchronously, not in the coalesced frame.
         A token arriving inside the ~16ms rAF window would otherwise call
         followStream() against stale intent, scroll to the bottom, and leave
         _lastScrollTop at the bottom — so the frame that finally ran saw no
         decrease and re-latched following. The reader's scroll was erased
         mid-gesture. Only scrollTop is read, which is already committed by the
         time a scroll event fires and costs no layout.

         Content growth moves scrollHeight, never scrollTop, so inserting a
         source deck still cannot be mistaken for the reader walking away. The
         1px slack absorbs sub-pixel jitter on fractional-DPI displays. */
      const top = container.scrollTop;
      if (top < this._lastScrollTop - 1) this._follow = false;
      this._lastScrollTop = top;

      // rAF-coalesced: scroll fires far more often than once per frame.
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

  /**
   * Close out a streamed answer.
   *
   * @param {object} handle
   * @param {string[]} suggestedQuestions
   * @param {{response: string, sources: object[], cited: number[], retrieved: number}|null} final
   *
   * `final.response` is the server's canonical answer, and it is deliberately
   * re-rendered over what the delta frames built. The deltas are raw model
   * tokens; the server rewrites legacy "[Source: Doc, Page: 14]" citations
   * into "[1]" before deciding anything about them. Without this the reader
   * would be left looking at the prose form while the API reported a citation
   * of source 1 — a marker they were told exists and cannot click.
   */
  finishStreamingMessage(handle, suggestedQuestions = [], final = null) {
    if (!handle) return;

    const sources = final?.sources || [];
    const cited = Array.isArray(final?.cited) ? final.cited : null;

    // Set before finish(), because finish() re-parses and re-runs the decorate
    // callback — which is what binds the markers, and it needs the payload.
    handle.state.sources = sources;
    handle.stream.finish(final?.response ?? null);

    this.setStage(handle, null);
    handle.messageEl.removeAttribute('aria-busy');
    handle.messageEl.setAttribute('aria-live', 'polite');

    /* finish() has now re-parsed the canonical answer and recorded which
       markers became buttons. Show only those: a passage whose marker markdown
       swallowed into a link or a code span is one the reader cannot reach, so
       offering it as a source would be a claim with no way to check it. A null
       `bound` means no parse recorded a result, in which case trust the
       server's set rather than silently dropping everything. */
    const reachable = handle.state.bound
      ? sources.filter(s => handle.state.bound.has(s.index))
      : sources;

    const trigger = renderSourceTrigger({
      sources: reachable,
      cited,
      retrieved: final?.retrieved ?? sources.length,
    }, handle.msgId);
    if (trigger) {
      handle.messageEl.insertBefore(
        trigger,
        handle.messageEl.querySelector(`.${CONFIG.CLASSES.SUGGESTED_CONTAINER}`)
      );
    }

    const container = handle.messageEl.querySelector(`.${CONFIG.CLASSES.SUGGESTED_CONTAINER}`);
    Utils.renderSuggestedQuestions(container, suggestedQuestions);

    /* Announce what was CITED. This line used to read "{n} sources cited" off
       the RETRIEVED count, so it was wrong on every answer — and on a refusal
       it told a screen reader the answer cited eight sources it had just
       declined to use. Counted off `reachable`, the same set the trigger and
       the panel show, so what a screen reader is told and what a sighted
       reader can open cannot disagree. */
    this.announce(reachable.length
      ? I18n.t('cite.answerCompleteWithSources', { n: reachable.length })
      : I18n.t('cite.answerComplete'));

    /* Only if they were still following. A reader who scrolled up mid-answer
       has taken control, and reaching the end of the stream is not a reason to
       take it back — an unconditional jump here undid their scroll at the one
       moment they were most likely reading something specific. */
    if (this._follow) this.scrollMessagesToBottom();
  },

  /**
   * Add the visible "this did not finish" marking to a message.
   *
   * Split out from markStreamIncomplete so a stream that DID deliver a
   * canonical answer can be rendered properly first and then flagged, rather
   * than having to choose between a correct answer and an honest one.
   */
  flagIncomplete(handle, kind = 'error') {
    if (!handle) return;
    handle.messageEl.classList.add(kind === 'cancelled' ? 'is-cancelled' : 'is-errored');

    const note = DOMCache.createElement('div', 'stream-note', kind);
    note.textContent = I18n.t(kind === 'cancelled' ? 'chat.stopped' : 'chat.incomplete');
    handle.messageEl.querySelector('.message-bubble')?.appendChild(note);
  },

  /** Mark a stream that failed or was cancelled, keeping whatever arrived. */
  markStreamIncomplete(handle, kind = 'error') {
    if (!handle) return;
    handle.stream.finish();
    this.setStage(handle, null);
    handle.messageEl.removeAttribute('aria-busy');
    this.flagIncomplete(handle, kind);
  },

  /**
   * Empty the transcript, keeping the server-rendered intro.
   *
   * The authenticated view is only hidden on logout, never emptied, and the
   * app lives at "/" so nothing reloads. Without this, signing in as a second
   * reader in the same tab reveals the first reader's conversation intact.
   */
  clearTranscript() {
    this.detachTranscript();
  },

  /**
   * Take the transcript's turns out of the page and hand them back, still live.
   *
   * The nodes are MOVED into a fragment rather than serialized, because every
   * handler that makes a turn work — citation markers, source triggers,
   * suggested questions — is delegated on #messages rather than bound per
   * node. Nodes that leave and come back are therefore wired exactly as they
   * were, and `stateByMessage` still resolves their sources.
   *
   * Restoring from HTML would not do: that path has to strip its own controls
   * (see neutraliseRestoredCitations), which is correct across a reload, where
   * module memory is genuinely gone, and wrong for an undo, where it is not.
   */
  detachTranscript() {
    const fragment = document.createDocumentFragment();
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (container) {
      [...container.children]
        .filter(el => !el.hasAttribute('data-chat-intro'))
        .forEach(el => fragment.appendChild(el));
    }
    this.updateNewChatAvailability();
    return fragment;
  },

  /**
   * Play the transcript out, then hand back the turns.
   *
   * Newest first: the conversation unwinds rather than the page blanking. The
   * stagger is capped so thirty turns still clear in well under half a second.
   *
   * The class is added at runtime and never authored in the template — a
   * stylesheet that hides content on the promise that a script will move it is
   * the failure mode this codebase already legislates against.
   */
  async playTranscriptExit() {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    const turns = container
      ? [...container.children].filter(el => !el.hasAttribute('data-chat-intro'))
      : [];

    if (!turns.length || prefersReducedMotion()) return this.detachTranscript();

    const last = turns.length - 1;
    turns.forEach((el, index) => {
      el.style.animationDelay = `${Math.min((last - index) * 18, 140)}ms`;
      el.classList.add(CONFIG.CLASSES.IS_CLEARING);
    });

    /* turns[0] is the oldest, so under a newest-first stagger it carries the
       largest delay and finishes last. The timeout is a backstop rather than a
       nicety: animationend does not fire for an interrupted animation, and a
       transcript that never detaches is a worse failure than one that detaches
       a frame early. */
    await new Promise((resolve) => {
      let settled = false;
      const finish = () => { if (!settled) { settled = true; resolve(); } };
      turns[0].addEventListener('animationend', finish, { once: true });
      setTimeout(finish, 400);
    });

    const fragment = this.detachTranscript();
    // The turns come back clean; an undo must not restore a half-played exit.
    [...fragment.children].forEach(el => {
      el.classList.remove(CONFIG.CLASSES.IS_CLEARING);
      el.style.removeProperty('animation-delay');
    });
    return fragment;
  },

  /** Put detached turns back, without re-announcing the whole conversation. */
  restoreTranscript(fragment) {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!container || !fragment) return;

    /* #messages is role="log" aria-live="polite", so re-appending a whole
       conversation would have a screen reader read every turn back. aria-busy
       marks the bulk update as one the reader should not be walked through. */
    container.setAttribute('aria-busy', 'true');
    container.appendChild(fragment);
    requestAnimationFrame(() => container.removeAttribute('aria-busy'));

    // No entrance on the way back: an undo should read as the clear never
    // having happened, and a button animating in would announce that it did.
    this.updateNewChatAvailability({ animate: false });
  },

  /**
   * Show "New chat" only once there is a chat to end.
   *
   * Hidden rather than disabled. On a first visit this column's job is the FAQ
   * rail — a first session usually starts by clicking a question — and a
   * greyed-out control offering to clear a conversation nobody has had yet
   * would still be the first thing in the column.
   */
  updateNewChatAvailability({ animate = true } = {}) {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    const hasTurns = !!container && [...container.children]
      .some(el => !el.hasAttribute('data-chat-intro'));
    const available = hasTurns || AppState.isRequestInProgress();

    DOMCache.getAll(`.${CONFIG.CLASSES.NEW_CHAT_BTN}`).forEach(btn => {
      /* Only the hidden→visible transition animates, and only when the caller
         allows it. Every route that touches the transcript lands here — a sent
         message, a stream starting or ending, a clear, an undo — so keying off
         `available` alone would replay the arrival on every turn, and keying
         off the transition alone would replay it on an undo, which is supposed
         to feel like nothing happened. */
      const arriving = animate && btn.hidden && available;
      btn.hidden = !available;
      if (!arriving) return;

      // Restart the animation: removing the class alone is coalesced away.
      btn.classList.remove(CONFIG.CLASSES.IS_ARRIVING);
      void btn.offsetHeight;
      btn.classList.add(CONFIG.CLASSES.IS_ARRIVING);
      // Cleared once it has played, so the class means "arriving" rather than
      // "arrived once, some time ago".
      btn.addEventListener(
        'animationend',
        () => btn.classList.remove(CONFIG.CLASSES.IS_ARRIVING),
        { once: true }
      );
    });
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

    /* An in-flight answer counts as a chat to end: New chat cancels it and
       clears, which is a legitimate way out of a question you regret asking. */
    this.updateNewChatAvailability();
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
