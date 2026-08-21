/**
 * SFDA Copilot — UI module
 * Message rendering, typing indicator, FAQ list, profile form population and
 * send-button state.
 */

import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.2/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.4.13/+esm';

import { CONFIG, prefersReducedMotion } from './config.js';
import { DOMCache, logError } from './dom.js';
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

function createMessageElement(text, sender, msgId, occurredAt = null) {
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
  /* WHEN THE TURN HAPPENED, not when the page was drawn. A hydrated transcript
     rebuilds turns that may be days old, and stamping them with the reload time
     would tell a reader every question in their history was asked just now — on
     a tool where "when did I ask this" is part of the record. An unparseable or
     absent value falls back to now, which is correct for a live message and the
     honest default for a stored one whose timestamp did not survive. */
  const stored = occurredAt ? new Date(occurredAt) : null;
  const now = stored && !Number.isNaN(stored.getTime()) ? stored : new Date();
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

const RESUMED_NOTICE_ID = 'resumed-notice';
const HISTORY_NOTICE_ID = 'history-notice';

/* Bump to re-show the disclosure after its wording materially changes. Part of
   the storage key rather than a separate flag, so an old acknowledgement simply
   stops matching instead of having to be found and cleared. */
const HISTORY_NOTICE_VERSION = 1;

/* Scoped to the READER, not to the browser. A shared machine is the ordinary
   case here, and a notice one colleague dismissed must not be treated as read
   by the next person to sign in — the same reader-scoping the transcript
   already enforces, for the same reason. */
function historyNoticeKey(identity) {
  return `sfda-history-notice:${identity}:v${HISTORY_NOTICE_VERSION}`;
}

/* Both wrapped, because localStorage throws rather than degrades in private
   mode and behind some enterprise policies — the convention every other storage
   access in this app already follows. A storage failure means the notice is
   shown again, which is the safe direction for a disclosure. */
function historyNoticeSeen(identity) {
  try {
    return localStorage.getItem(historyNoticeKey(identity)) !== null;
  } catch (error) {
    logError(error, 'historyNoticeSeen');
    return false;
  }
}

function rememberHistoryNotice(identity) {
  try {
    localStorage.setItem(historyNoticeKey(identity), String(Date.now()));
  } catch (error) {
    logError(error, 'rememberHistoryNotice');
  }
}

/**
 * Whether an element inside `#messages` is one of the conversation's turns.
 *
 * `#messages` holds three things that are NOT turns and must never be counted,
 * detached, cleared or restored as if they were: the server-rendered
 * `[data-chat-intro]` empty state, the resumed notice, and the durable-history
 * notice. Each would otherwise be swept into the fragment an undo puts back,
 * and each would make `updateNewChatAvailability` believe a conversation
 * exists. The history notice is the sharpest case: it is meant to outlive a
 * `New chat`, so a miss here deletes the disclosure at exactly the moment the
 * reader is exercising the control it is telling them about.
 *
 * This started as a repeated `!el.hasAttribute('data-chat-intro')` at four call
 * sites. Adding a second non-turn element to `#messages` is exactly the change
 * that turns a repeated literal into a bug at whichever site the author forgot,
 * so the question is asked in one place.
 */
function isTranscriptTurn(el) {
  return (
    !el.hasAttribute('data-chat-intro')
    && el.id !== RESUMED_NOTICE_ID
    && el.id !== HISTORY_NOTICE_ID
  );
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
    const messageEl = createMessageElement(text, sender, msgId, meta?.occurredAt);
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
          /* Undefined for a caller that does not set it, and that is the
             correct default — `isDatedEvidence` treats missing as "say
             nothing" rather than "warn", so an answer rendered by a path that
             knows nothing about corpus builds is left alone. */
          evidenceState: meta?.evidenceState,
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
      // Always 'verified' from the server on a live answer — it was just drawn
      // from the active index. Read from the frame rather than hardcoded here
      // so the streaming and hydrated paths share one field name.
      evidenceState: final?.evidence_state,
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
    /* The notice describes turns that are no longer on screen. Leaving it up
       after a clear or a sign-out would explain a conversation the reader is
       looking at the absence of. */
    this.hideResumedNotice();
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
   * Restoring from HTML would not do: nodes rebuilt from markup arrive without
   * the passages behind their citation controls, because `stateByMessage` lives
   * in module memory. Across a reload that is unavoidable and the transcript is
   * hydrated from durable rows instead; for an undo, where module memory is
   * still intact, moving the live nodes keeps everything resolving.
   */
  detachTranscript() {
    const fragment = document.createDocumentFragment();
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (container) {
      [...container.children]
        .filter(isTranscriptTurn)
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
    this.hideResumedNotice();
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    const turns = container
      ? [...container.children].filter(isTranscriptTurn)
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

    /* Stamped BEFORE the nodes go back in, because a re-appended element
       replays its entrance animation and there is no frame in between to catch
       it. Same reason as the aria-busy below, in the other channel: an undo
       should reach both a reader watching and a reader listening as the clear
       never having happened. See effects.css. */
    [...fragment.children].forEach(el =>
      el.classList.add(CONFIG.CLASSES.ANIM_SUPPRESSED));

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
      .some(isTranscriptTurn);
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

  /**
   * Draw a stored conversation into the transcript.
   *
   * THROUGH `addMessage`, deliberately — the same path a live answer takes, so
   * `bindCitations` and `renderSourceTrigger` run and a restored answer's
   * controls resolve against real passages. The predecessor of this method
   * re-injected saved HTML from `sessionStorage`, which is why restored
   * citations had to be neutralised: the markup came back and the evidence did
   * not. Never re-inject stored markup here; it would reintroduce exactly that.
   *
   * Turns append AFTER the server-rendered `[data-chat-intro]` block, which is
   * why nothing is cleared first — the intro is the empty state and belongs
   * above the conversation, not instead of it.
   *
   * `#messages` is `role="log" aria-live="polite"`, so drawing a whole
   * conversation would have a screen reader read every turn aloud. `aria-busy`
   * marks the bulk insert as one the reader should not be walked through — the
   * same reasoning `restoreTranscript` already carries for undo.
   */
  hydrateTranscript(messages = []) {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!container || !messages.length) return;

    /* Everything already on screen, captured before a single turn is drawn.
       The fetch behind this is not awaited, so a reader who signs in and asks
       a question straight away can have their new exchange rendered WHILE the
       history is still in flight — and appending then would file their stored
       conversation underneath the question they just asked. Stored turns are
       older than anything this tab has done, so they go above it. */
    const existing = [...container.children];
    const anchor = existing.find(isTranscriptTurn) || null;

    container.setAttribute('aria-busy', 'true');
    messages.forEach((message) => {
      if (message.role === 'user') {
        this.addMessage(message.content, 'user', [], [], {
          occurredAt: message.created_at,
        });
        return;
      }
      this.addMessage(message.content, 'bot', [], message.sources || [], {
        cited: message.cited ?? null,
        retrieved: message.retrieved ?? (message.sources || []).length,
        evidenceState: message.evidence_state,
        occurredAt: message.created_at,
      });
    });

    /* `addMessage` appends, so the drawn turns are whatever is new. Moving
       them one at a time before the same anchor preserves their order. */
    if (anchor) {
      [...container.children]
        .filter(el => !existing.includes(el))
        .forEach(el => container.insertBefore(el, anchor));
    }

    requestAnimationFrame(() => container.removeAttribute('aria-busy'));

    // Bypasses the entrance animation's reason for existing: a conversation
    // being restored did not just arrive, and animating it in would say it did.
    this.updateNewChatAvailability({ animate: false });
  },

  /**
   * Say that this conversation was picked up rather than started here.
   *
   * Shown only when the server resumed the reader's most recent conversation
   * because this browser named none — a new device, a cleared browser, or the
   * first visit after a logout. In every other case the conversation on screen
   * is the one this browser was already having, and a notice would be noise.
   *
   * IT EXISTS FOR ONE KNOWN GAP. Ending a conversation and then logging out
   * before asking anything else purges the cookie, so the next visit looks like
   * a new device and resumes the conversation that was ended. Closing that
   * properly needs a durable owner-level reset marker. Until then this is the
   * difference between a conversation reappearing unexplained — which would
   * read as the app doing something behind the reader's back, on the one
   * product where that is unaffordable — and one that says where it came from
   * and points at the way to start fresh.
   *
   * Dismissible and non-blocking: it is a disclosure, not a decision.
   */
  showResumedNotice() {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!container || document.getElementById(RESUMED_NOTICE_ID)) return;

    const notice = DOMCache.createElement('div', 'resumed-notice');
    notice.id = RESUMED_NOTICE_ID;
    notice.setAttribute('role', 'note');

    const text = DOMCache.createElement('span', 'resumed-notice-text');
    text.textContent = I18n.t('chat.resumed');

    const dismiss = DOMCache.createElement('button', 'resumed-notice-dismiss');
    dismiss.type = 'button';
    dismiss.setAttribute('aria-label', I18n.t('chat.resumedDismiss'));
    dismiss.innerHTML = iconMarkup('close', 14);
    dismiss.addEventListener('click', () => notice.remove());

    notice.append(text, dismiss);

    /* Above the conversation but below the intro, so it reads as a preface to
       what follows rather than a banner about the page — and below the history
       notice when that is present. The order is the reading order: what is
       always true about this account first, then what happened to this
       particular conversation. */
    const intro = container.querySelector('[data-chat-intro]');
    const history = document.getElementById(HISTORY_NOTICE_ID);
    const anchor = history || intro;
    if (anchor) anchor.after(notice);
    else container.prepend(notice);
  },

  /** Remove the resumed notice, e.g. on a reset or a sign-out. */
  hideResumedNotice() {
    document.getElementById(RESUMED_NOTICE_ID)?.remove();
  },

  /**
   * Tell the reader their chats are durable, once per reader per device.
   *
   * This is the disclosure the feature owed from the moment hydration shipped.
   * Before it, the transcript died with the tab and saying nothing was
   * defensible; afterwards a conversation follows the reader across a reload, a
   * language toggle and a different device, and silence became a claim that is
   * no longer true.
   *
   * Deliberately NOT a toast. `ErrorHandler.showToast` auto-hides, and a
   * disclosure shown for four seconds is delivered in form only. It sits in the
   * transcript, survives a `New chat` (see `isTranscriptTurn`), and goes only
   * when the reader dismisses it.
   *
   * Re-showing on a new device is correct rather than a defect: a new device is
   * exactly where cross-device restoration becomes newly relevant to the person
   * looking at it.
   */
  showHistoryNotice(identity) {
    const container = DOMCache.get(CONFIG.SELECTORS.MESSAGES);
    if (!container || !identity) return;

    /* Any notice on screen belongs to whoever was here before. Removing it
       first is what makes this safe to call on an identity change: the next
       reader's own acknowledgement decides whether one is drawn again. */
    this.hideHistoryNotice();
    if (historyNoticeSeen(identity)) return;

    const notice = DOMCache.createElement('div', 'history-notice');
    notice.id = HISTORY_NOTICE_ID;
    notice.setAttribute('role', 'note');

    const body = DOMCache.createElement('div', 'history-notice-body');

    const text = DOMCache.createElement('p', 'history-notice-text');
    text.textContent = I18n.t('chat.historyNotice');

    const warning = DOMCache.createElement('p', 'history-notice-warning');
    warning.textContent = I18n.t('chat.historyNoticeWarning');

    body.append(text, warning);

    const dismiss = DOMCache.createElement('button', 'history-notice-dismiss');
    dismiss.type = 'button';
    dismiss.setAttribute('aria-label', I18n.t('chat.historyNoticeDismiss'));
    dismiss.innerHTML = iconMarkup('close', 14);
    /* Recorded on dismissal, not on display. A notice that was drawn and never
       read is not an acknowledgement, and stamping it on render would silently
       spend the one showing this reader gets. */
    dismiss.addEventListener('click', () => {
      rememberHistoryNotice(identity);
      notice.remove();
    });

    notice.append(body, dismiss);

    const intro = container.querySelector('[data-chat-intro]');
    if (intro) intro.after(notice);
    else container.prepend(notice);
  },

  /** Remove the history notice without recording it as acknowledged. */
  hideHistoryNotice() {
    document.getElementById(HISTORY_NOTICE_ID)?.remove();
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

    this.selectThemeRadio(form, profile);
  },

  /**
   * Check the theme radio matching the reader's *saved* preference
   * (`profile.preferences.theme`), not whichever theme happens to be
   * rendered on screen right now. Those two can diverge the moment a
   * reader toggles the theme button without saving the profile form, and
   * `ThemeManager.getCurrent()` reads the live `data-bs-theme` attribute,
   * not the stored preference. Falls back to the live theme only when the
   * profile carries no saved value at all (e.g. a brand-new, profile-less
   * account), where there is nothing else to honor.
   */
  selectThemeRadio(form, profile) {
    if (!form) return;
    const theme = profile?.preferences?.theme || ThemeManager.getCurrent();
    const themeRadio = form.querySelector(`input[name="theme-preference"][value="${theme}"]`);
    if (themeRadio) themeRadio.checked = true;
  },

  /**
   * Tell a disabled reader as soon as we know, rather than only after they
   * submit a question and hit the same 403 (handlers.js's existing bot-message
   * notice, kept as a fallback). The composer stays usable — this is a notice,
   * not a lockout.
   *
   * The glyph is ours, so it goes in as markup; the message is translated
   * copy, so it goes in as a text node — never `innerHTML` for translated
   * strings, the same rule this app applies everywhere else.
   */
  showAccountDisabledNotice() {
    const el = DOMCache.get(CONFIG.SELECTORS.ACCOUNT_DISABLED_NOTICE);
    if (!el) return;
    el.innerHTML = iconMarkup('alert', 14, 'account-disabled-notice-icon');
    const label = document.createElement('span');
    label.textContent = I18n.t('auth.accountDisabled');
    el.appendChild(label);
    el.hidden = false;
  },

  hideAccountDisabledNotice() {
    const el = DOMCache.get(CONFIG.SELECTORS.ACCOUNT_DISABLED_NOTICE);
    if (el) el.hidden = true;
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
    /* Kept so a later "more" click can pull the rest of a category's
       questions without a second fetch — the payload is small and already in
       memory once. Cleared on logout/clearButtons like everything else
       reader-scoped. */
    _data: null,

    /* The chunking limit a category's first view is held to. Two categories
       in the shipped corpus run past it (5 and 6 questions); the rest render
       whole and never show a "more" button at all. */
    VISIBLE_PER_GROUP: 4,

    _makeQuestionButton(category, short, text, { animate = false, itemIndex = 0 } = {}) {
      const button = DOMCache.createElement('button', 'nav-link', CONFIG.CLASSES.FAQ_BUTTON);
      DOMCache.setAttributes(button, { 'data-category': category, 'data-question': text });
      button.textContent = short;
      if (animate) {
        button.style.opacity = '0';
        button.style.animation = `faqSlideIn 0.3s ease ${itemIndex * 0.05}s forwards`;
      }
      return button;
    },

    renderButtons(faqData) {
      this._data = faqData || {};
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

          /* Hold the first view to the same working-memory limit the rest of
             the sidebar is built to — a category over it gets a "more" step
             instead of dumping every question into the reader's first look. */
          const visibleCount = Math.min(data.questions.length, this.VISIBLE_PER_GROUP);
          data.questions.slice(0, visibleCount).forEach(({ short, text }) => {
            if (!short || !text) return;
            nav.appendChild(this._makeQuestionButton(category, short, text, { animate: true, itemIndex }));
            itemIndex++;
          });

          fragment.appendChild(header);
          fragment.appendChild(nav);

          const remaining = data.questions.length - visibleCount;
          if (remaining > 0) {
            const more = DOMCache.createElement('button', CONFIG.CLASSES.FAQ_MORE);
            DOMCache.setAttributes(more, { type: 'button', 'data-faq-more': category });
            more.textContent = I18n.plural(remaining, 'faq.showMoreOne', 'faq.showMoreMany');
            fragment.appendChild(more);
          }
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

    /* One shot, not a second layer of pagination: every shipped category is
       small enough that "show the rest" is the whole interaction. Reads the
       category straight from the last-rendered payload rather than off the
       button, so the two sidebar copies (desktop aside, mobile offcanvas)
       each expand independently from the same data without needing their
       own render pass. No entrance animation — the reader asked for this,
       so it should be there the instant they look, not staggered in. */
    expandGroup(category, moreButton) {
      const data = this._data?.[category];
      const nav = moreButton?.previousElementSibling;
      if (!data?.questions?.length || !nav || nav.tagName !== 'NAV') return;

      const alreadyShown = nav.querySelectorAll(`.${CONFIG.CLASSES.FAQ_BUTTON}`).length;
      data.questions.slice(alreadyShown).forEach(({ short, text }) => {
        if (!short || !text) return;
        nav.appendChild(this._makeQuestionButton(category, short, text));
      });
      moreButton.remove();
    },

    clearButtons() {
      this._data = null;
      DOMCache.getAll(`${CONFIG.SELECTORS.FAQ_SIDEBAR}, ${CONFIG.SELECTORS.FAQ_OFFCANVAS}`).forEach(section => {
        section.innerHTML = '';
      });
    },
  },

  /**
   * The conversation sidebar.
   *
   * ONE STATE, RENDERED TWICE. The sidebar macro produces a desktop aside and an
   * offcanvas copy, and the failure mode of building this as two lists is that
   * they diverge — a rename lands in one, a delete in the other, and which one
   * the reader sees depends on their viewport. So `_state` is the single truth
   * and `_paint` writes it into both panels from the same builder.
   *
   * It is deliberately NOT virtualised. The rows are short titles, not message
   * cards; the list is bounded by a 30-row page with an explicit "load more";
   * and this panel is already a scroll port inside the offcanvas body, which is
   * another one. Adding a virtual window would unmount rows while focus and
   * `aria-labelledby` still point at them, and would fight Bootstrap's focus
   * trap — three new failure modes to save a cost that does not yet exist.
   */
  History: {
    /* `status` is one of: idle | loading | ready | error. Four states rather
       than a boolean, because "loading", "you have no conversations" and "your
       conversations could not be loaded" are three different claims and
       collapsing any two of them tells the reader something untrue. */
    _state: {
      status: 'idle',
      sessions: [],
      cursor: null,
      active: null,
      loadingMore: false,
      /* The row currently being renamed or confirmed for deletion, as
         `{ id, mode }`. Held in state rather than in the DOM so both rendered
         copies enter the same mode together — otherwise opening the offcanvas
         mid-rename would show an un-renaming row. */
      pending: null,
    },

    panels() {
      return [
        DOMCache.get(CONFIG.SELECTORS.HISTORY_SIDEBAR),
        DOMCache.get(CONFIG.SELECTORS.HISTORY_OFFCANVAS),
      ].filter(Boolean);
    },

    get state() {
      return this._state;
    },

    /** Replace the whole list. Used by a first load and by a retry. */
    setSessions({ sessions, cursor, active }) {
      this._state = {
        ...this._state,
        status: 'ready',
        sessions: sessions.slice(),
        cursor: cursor || null,
        active: active || this._state.active,
        loadingMore: false,
        pending: null,
      };
      this._paint();
    },

    /** Append the next page, keeping what is already drawn. */
    appendSessions({ sessions, cursor }) {
      /* De-duplicated by id on the way in. A conversation that received a turn
         between page 1 and page 2 moves to the top of the ordering, and a
         keyset cursor pointing past its OLD position will hand it back a second
         time. Without this the reader sees the same conversation twice and a
         later rename updates only one of them. */
      const seen = new Set(this._state.sessions.map(s => s.id));
      this._state = {
        ...this._state,
        status: 'ready',
        sessions: this._state.sessions.concat(sessions.filter(s => !seen.has(s.id))),
        cursor: cursor || null,
        loadingMore: false,
      };
      this._paint();
    },

    setStatus(status) {
      this._state = { ...this._state, status, loadingMore: false };
      this._paint();
    },

    setLoadingMore(loading) {
      this._state = { ...this._state, loadingMore: loading };
      this._paint();
    },

    /** Which conversation the row highlight points at. */
    setActive(sessionId) {
      this._state = { ...this._state, active: sessionId || null };
      this._paint();
    },

    /** Put one row into rename or delete-confirm mode, or clear the mode. */
    setPending(pending) {
      this._state = { ...this._state, pending: pending || null };
      this._paint();
    },

    /**
     * Rename one row in place.
     *
     * ORDER IS NOT TOUCHED, and that mirrors the database exactly:
     * `chat_rename_session` deliberately leaves `updated_at` alone, because
     * that column means "last spoken in". A client that re-sorted here — or
     * that stamped the row with `Date.now()` optimistically — would lift a
     * months-old conversation to the top of Today on an edit that changed no
     * content, and the next list fetch would silently put it back.
     */
    applyRename(sessionId, title) {
      this._state = {
        ...this._state,
        sessions: this._state.sessions.map(s => (
          s.id === sessionId ? { ...s, title } : s
        )),
        pending: null,
      };
      this._paint();
    },

    removeSession(sessionId) {
      this._state = {
        ...this._state,
        sessions: this._state.sessions.filter(s => s.id !== sessionId),
        active: this._state.active === sessionId ? null : this._state.active,
        pending: null,
      };
      this._paint();
    },

    /**
     * Forget everything. Called on sign-out and on an identity change.
     *
     * These rows are one reader's own questions. Leaving them drawn behind the
     * landing view is the same hazard the transcript's ownership tag existed to
     * prevent, and the app lives at "/" so nothing reloads on the way out.
     */
    clear() {
      this._state = {
        status: 'idle', sessions: [], cursor: null, active: null,
        loadingMore: false, pending: null,
      };
      this._paint();
    },

    /** Mark the Chats tab as still fetching, in both sidebar copies. */
    setTabLoading(loading) {
      document.querySelectorAll('.sidebar-tabs').forEach(tabs => {
        if (loading) tabs.setAttribute('data-loading', 'chats');
        else tabs.removeAttribute('data-loading');
      });
    },

    /**
     * Group by calendar day, into five fixed buckets.
     *
     * DELIBERATELY NOT `Intl.RelativeTimeFormat`. Three reasons, and the first
     * is the one that would actually ship broken: Arabic has six plural forms
     * where `I18n.plural` knows two, so "3 days ago" renders as an
     * ungrammatical "٣ أيام مضت" under any hand-rolled scheme. Second, `Intl`
     * emits bidi control characters that reorder inside an RTL column — this
     * codebase has already paid for that once, with an en-US time rendering as
     * "AM 3:17:18" in an Arabic transcript. Third, the language toggle reloads
     * the page, so any cached relative string is stale by construction.
     *
     * Fixed bucket names from the catalogue have none of those problems: they
     * are grammatical in both scripts, need no plural rules, and carry no
     * direction marks. The precise timestamp is still available on the row —
     * see `_rowTitleAttr` — for the reader who needs the actual date.
     *
     * Buckets are computed from CALENDAR DAYS, not from elapsed hours. An
     * answer at 23:50 and one at 00:10 are twenty minutes apart and belong under
     * different headings, which is what a reader means by "yesterday".
     */
    _bucketOf(updatedAt) {
      const when = updatedAt ? new Date(updatedAt) : null;
      if (!when || Number.isNaN(when.getTime())) return 'older';

      const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
      const days = Math.round(
        (startOfDay(new Date()) - startOfDay(when)) / 86400000
      );

      // Negative means a clock skew put the row in the future. Treated as today
      // rather than dropped into "older", where a conversation the reader just
      // had would sit at the bottom of their list.
      if (days <= 0) return 'today';
      if (days === 1) return 'yesterday';
      if (days <= 7) return 'previous7';
      if (days <= 30) return 'previous30';
      return 'older';
    },

    _titleOf(session) {
      return session.title || I18n.t('sessions.untitled');
    },

    /**
     * The row's `title` attribute: the full name and the exact time.
     *
     * The visible title truncates, so this is where the whole thing stays
     * readable — and where the precise timestamp lives, since the group heading
     * only says which day. `toLocaleString(I18n.lang)` and never a hand-built
     * string, matching what the transcript's own timestamps already do.
     */
    _rowTitleAttr(session) {
      const name = this._titleOf(session);
      const when = session.updated_at ? new Date(session.updated_at) : null;
      if (!when || Number.isNaN(when.getTime())) return name;
      return `${name}\n${when.toLocaleString(I18n.lang)}`;
    },

    /**
     * One action button, built node by node.
     *
     * DELIBERATELY NOT AN innerHTML TEMPLATE. Every label here interpolates the
     * conversation's title, and the title is reader input — a question they
     * typed, which on this product is routinely pasted out of a PDF. Assembling
     * that into a markup string needs an escape helper that does not exist in
     * this codebase, and the first person to add one and forget to call it has
     * written an XSS into the sidebar. `setAttributes` + `textContent` cannot
     * have that bug at all, which is a better guarantee than remembering.
     *
     * The glyph is the one exception and it is safe: `iconMarkup` returns path
     * data from a fixed server-side registry, with no interpolation of anything
     * the reader controls.
     */
    _actionButton({ action, sessionId, label, icon, size = 14, className = '' }) {
      const button = DOMCache.createElement(
        'button', CONFIG.CLASSES.HISTORY_ACTION, ...(className ? [className] : [])
      );
      DOMCache.setAttributes(button, {
        type: 'button',
        'data-history-action': action,
        'data-session-id': sessionId,
        title: label,
        'aria-label': label,
      });
      button.innerHTML = iconMarkup(icon, size);
      return button;
    },

    _confirmButton({ action, sessionId, label, className }) {
      const button = DOMCache.createElement('button', className);
      DOMCache.setAttributes(button, {
        type: 'button',
        'data-history-action': action,
        'data-session-id': sessionId,
      });
      button.textContent = label;
      return button;
    },

    _buildRow(session) {
      const item = DOMCache.createElement('div', CONFIG.CLASSES.HISTORY_ITEM);
      item.dataset.sessionId = session.id;
      if (session.id === this._state.active) {
        item.classList.add(CONFIG.CLASSES.HISTORY_ACTIVE);
      }

      const pending = this._state.pending;
      const renaming = pending?.id === session.id && pending.mode === 'rename';
      const confirming = pending?.id === session.id && pending.mode === 'delete';
      const name = this._titleOf(session);

      if (renaming) {
        /* The icon still renders, so the row does not jump one column narrower
           the instant it enters rename mode. */
        item.innerHTML = iconMarkup('chat-bubble', 15, 'history-item-icon');

        const input = DOMCache.createElement('input', 'history-rename');
        DOMCache.setAttributes(input, {
          type: 'text',
          value: session.title || '',
          /* 120, matching `chat_sessions.title`'s CHECK and `clamp_title`'s
             bound. Enforced here so the reader is stopped at the limit rather
             than told about it after a round trip that silently truncated. */
          maxlength: '120',
          'aria-label': I18n.t('sessions.renameLabel'),
          /* The name may be Arabic in an English UI or the reverse — it is
             whatever the reader asked. Detected, never forced. */
          dir: 'auto',
          'data-rename-input': session.id,
        });
        item.appendChild(input);

        const actions = DOMCache.createElement('div', 'history-item-actions');
        actions.appendChild(this._actionButton({
          action: 'rename-save', sessionId: session.id,
          label: I18n.t('sessions.renameSave'), icon: 'check',
        }));
        actions.appendChild(this._actionButton({
          action: 'rename-cancel', sessionId: session.id,
          label: I18n.t('sessions.renameCancel'), icon: 'close',
        }));
        item.appendChild(actions);
        return item;
      }

      /* `display: contents` on this button is what lets one control cover the
         icon and the title while the two action buttons stay OUTSIDE it —
         nesting a button inside a button is invalid HTML and, in practice,
         makes the inner one unreachable by keyboard. */
      const open = DOMCache.createElement('button', CONFIG.CLASSES.HISTORY_OPEN);
      DOMCache.setAttributes(open, {
        type: 'button',
        'data-history-action': 'open',
        'data-session-id': session.id,
        title: this._rowTitleAttr(session),
        /* The accessible name carries the title AND the length, because a title
           alone cannot tell a conversation abandoned after one question from
           one worked in all afternoon — and a screen-reader user cannot see the
           row's density. */
        'aria-label': `${I18n.t('sessions.openAria', { title: name })} — ` +
          I18n.plural(
            session.message_count || 0, 'sessions.turnsOne', 'sessions.turns'
          ),
        ...(session.id === this._state.active ? { 'aria-current': 'true' } : {}),
      });
      open.innerHTML = iconMarkup('chat-bubble', 15, 'history-item-icon');

      const label = DOMCache.createElement('span', 'history-item-title');
      if (!session.title) label.classList.add('is-untitled');
      /* `dir="auto"` and textContent, never innerHTML: this string is reader
         input. The direction is detected per row so an Arabic name in an
         English sidebar — and an English one in an Arabic sidebar — each lay
         out correctly, and the ellipsis lands on the right end of both. */
      label.setAttribute('dir', 'auto');
      label.textContent = name;
      open.appendChild(label);
      item.appendChild(open);

      const actions = DOMCache.createElement('div', 'history-item-actions');
      actions.appendChild(this._actionButton({
        action: 'rename', sessionId: session.id,
        label: I18n.t('sessions.renameAria', { title: name }), icon: 'pencil',
      }));
      actions.appendChild(this._actionButton({
        action: 'delete', sessionId: session.id,
        label: I18n.t('sessions.deleteAria', { title: name }), icon: 'trash',
        className: 'is-destructive',
      }));
      item.appendChild(actions);

      if (confirming) {
        /* Inline, in the row's own grid, rather than a modal. Deleting one row
           out of a list needs neither interruption nor protected focus, and a
           dialog would take the reader out of the column to answer a question
           about something in it. */
        const confirm = DOMCache.createElement('div', 'history-confirm');
        const text = DOMCache.createElement('span', 'history-confirm-text');
        text.textContent = I18n.t('sessions.deleteConfirm');
        confirm.appendChild(text);
        confirm.appendChild(this._confirmButton({
          action: 'delete-confirm', sessionId: session.id,
          label: I18n.t('sessions.deleteConfirmYes'), className: 'is-destructive',
        }));
        confirm.appendChild(this._confirmButton({
          action: 'delete-cancel', sessionId: session.id,
          label: I18n.t('sessions.deleteConfirmNo'), className: 'is-keep',
        }));
        item.appendChild(confirm);
      }

      return item;
    },

    _buildContent() {
      const fragment = document.createDocumentFragment();
      const { status, sessions, cursor, loadingMore } = this._state;

      if (status === 'loading' && !sessions.length) {
        const status_ = DOMCache.createElement('p', 'history-status');
        status_.textContent = I18n.t('sessions.loading');
        fragment.appendChild(status_);
        return fragment;
      }

      if (status === 'error') {
        /* NEVER the empty state. "You have no saved conversations" is a claim
           about the reader; making it because the store was unreachable is the
           same quiet untruth `/api/chat/history` answers 503 rather than [] to
           avoid. The retry is what makes this recoverable rather than final. */
        const status_ = DOMCache.createElement('p', 'history-status', 'is-error');
        status_.setAttribute('role', 'status');
        status_.textContent = I18n.t('sessions.unavailable');
        const retry = DOMCache.createElement('button', 'history-retry');
        DOMCache.setAttributes(retry, { type: 'button', 'data-history-action': 'retry' });
        retry.textContent = I18n.t('sessions.retry');
        fragment.appendChild(status_);
        fragment.appendChild(retry);
        return fragment;
      }

      if (status === 'ready' && !sessions.length) {
        const empty = DOMCache.createElement('p', 'history-empty');
        empty.textContent = I18n.t('sessions.empty');
        const hint = DOMCache.createElement('span', 'history-empty-hint');
        hint.textContent = I18n.t('sessions.emptyHint');
        empty.appendChild(hint);
        fragment.appendChild(empty);
        return fragment;
      }

      if (status === 'idle') return fragment;

      const list = DOMCache.createElement('div', 'history-list');
      /* `role="list"` explicitly, because `display: flex` on a <ul> strips the
         implicit list semantics in Safari and VoiceOver. A div carrying the
         role is unambiguous in every engine. */
      DOMCache.setAttributes(list, {
        role: 'list',
        'aria-label': I18n.t('sessions.listAria'),
      });

      let lastBucket = null;
      let first = true;
      sessions.forEach((session) => {
        const bucket = this._bucketOf(session.updated_at);
        if (bucket !== lastBucket) {
          const heading = DOMCache.createElement('h4', 'history-group');
          if (first) heading.classList.add('is-first');
          heading.textContent = I18n.t(`sessions.${bucket}`);
          list.appendChild(heading);
          lastBucket = bucket;
          first = false;
        }
        const row = this._buildRow(session);
        row.setAttribute('role', 'listitem');
        list.appendChild(row);
      });
      fragment.appendChild(list);

      if (cursor) {
        const more = DOMCache.createElement('button', 'history-more');
        DOMCache.setAttributes(more, { type: 'button', 'data-history-action': 'more' });
        if (loadingMore) more.setAttribute('disabled', 'disabled');
        more.textContent = loadingMore
          ? I18n.t('sessions.loading')
          : I18n.t('sessions.loadMore');
        fragment.appendChild(more);
      }

      return fragment;
    },

    /**
     * Write the state into both panels.
     *
     * Scroll position is carried across the repaint. A rename or a delete
     * rebuilds the whole list, and without this the reader who was forty rows
     * down would be thrown back to the top by the edit they just made.
     */
    _paint() {
      const panels = this.panels();
      if (!panels.length) return;

      panels.forEach((panel, index) => {
        const scroll = panel.scrollTop;
        panel.innerHTML = '';
        const content = this._buildContent();
        // The fragment is consumed by the first append, so the second panel
        // gets a clone. Same shape UI.Faq already uses.
        panel.appendChild(index === 0 ? content : content.cloneNode(true));
        panel.scrollTop = scroll;
      });

      /* Focus follows the rename input, and only when it has just appeared.
         Re-focusing on every paint would steal the caret back from a reader
         mid-word every time an unrelated part of the state changed. */
      const pending = this._state.pending;
      if (pending?.mode === 'rename' && !pending.focused) {
        pending.focused = true;
        /* The VISIBLE copy. Both panels hold an input with this attribute and
           one of them is inside a hidden offcanvas; focusing that one moves the
           caret somewhere the reader cannot see it. `offsetParent` is null for
           a display:none subtree, which is exactly the test wanted here. */
        const inputs = [...document.querySelectorAll(`[data-rename-input="${pending.id}"]`)];
        const visible = inputs.find(el => el.offsetParent !== null) || inputs[0];
        visible?.focus();
        visible?.select();
      }
    },
  },
};
