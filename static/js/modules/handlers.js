/**
 * SFDA Copilot — Event handlers
 * Wires up auth forms, chat input, FAQ/suggested questions and profile actions.
 */

import { CONFIG } from './config.js';
import { DOMCache, ErrorHandler, logError } from './dom.js';
import { AppState } from './state.js';
import { AuthView } from './auth-view.js';
import { UI } from './ui.js';
import { Services, RECOVERY_STORAGE_KEY, newRequestId } from './services.js';
import { ThemeManager } from './theme.js';
import { RobotStateManager } from './robot.js';
import { I18n } from './i18n.js';
import { SourcePanel } from './source-panel.js';
import { resetCitationState } from './citations.js';

/* Sent with every chat request so the model answers in the reader's language. */
const I18N_LANG = I18n.lang;

/* Honest progress text, driven by real server stages rather than a timer. */
const STAGE_LABELS = {
  searching: () => I18n.t('stage.searching'),
  retrieved: (d) => I18n.plural(d.count, 'stage.retrievedOne', 'stage.retrieved'),
  drafting: () => I18n.t('stage.drafting'),
  finalizing: () => I18n.t('stage.finalizing'),
};

/* The turns a New chat took off screen, held live so an undo can put the same
   nodes back rather than rebuild them from markup. Null whenever there is
   nothing to restore. */
let pendingUndo = null;

/* Bumped by every reset. A streaming request stamps itself with the value it
   started under, so its abort handler can tell "the reader pressed Stop" from
   "the conversation this answer belonged to no longer exists". */
let resetGeneration = 0;

/* Bumped whenever the transcript on screen stops being the conversation an
   in-flight history fetch was asked about: a reset, an undo, or a sign-out.
   Distinct from `resetGeneration`, which guards a streaming ANSWER; this guards
   the TRANSCRIPT, and the two move independently — an undo restores the
   transcript without restoring a stream. */
let transcriptEpoch = 0;

/* Guards the window between a reset's server call and its transcript clear,
   during which a second press would reset the freshly-started conversation. */
let resetInFlight = false;

/* The handle of the answer currently streaming, or null. Cleared in
 * processChatRequestInternal's finally, alongside setSendingState — the two
 * mark the same thing, the end of one request's lifetime.
 *
 * Published because handleNewChat can end up owning that bubble. It aborts the
 * stream before calling the server, and streamChat then walks away without
 * touching the bubble — correctly, since on the normal path the bubble is a
 * fraction of a second from leaving the transcript entirely. When the server
 * call FAILS the transcript stays put, and the bubble stays with it: spinning,
 * still aria-busy, with no stream behind it and nothing coming back for it. */
let activeStream = null;

/**
 * Close out a bubble a failed reset abandoned.
 *
 * Takes the handle rather than reading `activeStream` itself, and that is the
 * whole point. A reset releases the composer the moment it aborts, so the
 * reader can start a NEW question during the server round trip — and by the
 * time a failure comes back, `activeStream` points at that new, legitimately
 * streaming answer. Reading it here would kill the wrong bubble.
 *
 * Whether there is anything to close out is then read off the bubble rather
 * than tracked: aria-busy means "still mid-flight", set by
 * beginStreamingMessage and removed by every path that finishes one, and
 * dropInFlightExchange already relies on exactly that. So a handle whose stream
 * finished on its own before the reset failed filters itself out.
 *
 * Marked `cancelled` rather than `error`: nothing went wrong with the answer,
 * the reader ended it. That the reset then failed is a separate fact, and the
 * toast carries it.
 */
function settleAbandonedStream(handle) {
  if (!handle?.messageEl?.hasAttribute('aria-busy')) return;
  UI.markStreamIncomplete(handle, 'cancelled');
  RobotStateManager.resetToIdle();
}

/**
 * Drop the exchange that was still streaming when a reset landed.
 *
 * A cancelled turn is never written to server history — the streaming
 * generator skips append_turn when the client disconnects — so restoring it
 * would put a question and a half-answer on screen that the model has no
 * record of. The invariant undo keeps is that the transcript shows what the
 * model remembers, and this is what maintains it.
 *
 * The in-flight bubble is the one still carrying aria-busy:
 * beginStreamingMessage sets it and finishStreamingMessage removes it, so the
 * marker already exists and needs no bookkeeping of its own.
 */
function dropInFlightExchange(fragment) {
  const answer = fragment.querySelector('[aria-busy="true"]');
  if (!answer) return;
  const question = answer.previousElementSibling;
  answer.remove();
  if (question?.classList.contains('user-message')) question.remove();
}

/* Ticks down the advisory cooldown on the reset button. Advisory only: GoTrue
   enforces one mail per address per minute and the server enforces its own rate
   limit — this exists so the reader is told how long is left instead of pressing
   a button that silently cannot work yet. */
let resetCooldownTimer = null;

/* Guards the one call in this flow that is not safe to repeat. Deliberately
   module-scoped rather than a form attribute: the form is torn down on success
   and the guard has to outlive it. */
let recoverySubmitInFlight = false;

export const Handlers = {
  bindEvents() {
    DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.addEventListener('submit', (e) => this.handleAuthFormSubmit(e, 'login'));
    DOMCache.get(CONFIG.SELECTORS.SIGNUP_FORM)?.addEventListener('submit', (e) => this.handleAuthFormSubmit(e, 'signup'));

    document.getElementById('login-btn-submit')?.addEventListener('click', (e) => {
      e.preventDefault();
      DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    DOMCache.get(CONFIG.SELECTORS.FORGOT_LINK)?.addEventListener('click', () => this.showResetRequest(true));
    DOMCache.get(CONFIG.SELECTORS.RESET_BACK)?.addEventListener('click', () => this.showResetRequest(false));
    DOMCache.get(CONFIG.SELECTORS.RESET_REQUEST_FORM)?.addEventListener('submit', (e) => this.handleResetRequestSubmit(e));
    DOMCache.get(CONFIG.SELECTORS.RECOVERY_FORM)?.addEventListener('submit', (e) => this.handleRecoverySubmit(e));
    DOMCache.get(CONFIG.SELECTORS.RECOVERY_CANCEL)?.addEventListener('click', () => this.handleRecoveryCancel());

    DOMCache.get(CONFIG.SELECTORS.SEND_BTN)?.addEventListener('click', () => this.processQuery());
    DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT)?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.processQuery();
      }
    });

    DOMCache.getAll(`${CONFIG.SELECTORS.LOGOUT_BTN}, ${CONFIG.SELECTORS.LOGOUT_BTN_OFFCANVAS}`).forEach(btn => {
      btn?.addEventListener('click', (e) => this.handleLogout(e));
    });

    DOMCache.getAll(`${CONFIG.SELECTORS.AUTH_BTN}, ${CONFIG.SELECTORS.AUTH_BTN_OFFCANVAS}, ${CONFIG.SELECTORS.AUTH_BTN_MAIN}`).forEach(btn => {
      btn?.addEventListener('click', () => AppState.get('authModal')?.show());
    });

    DOMCache.get(CONFIG.SELECTORS.PROFILE_FORM)?.addEventListener('submit', (e) => this.handleProfileFormSubmit(e));
    DOMCache.getAll(`${CONFIG.SELECTORS.PROFILE_BTN}, ${CONFIG.SELECTORS.PROFILE_BTN_OFFCANVAS}`).forEach(btn => {
      btn?.addEventListener('click', () => this.handleProfileButtonClick());
    });

    DOMCache.getAll(`${CONFIG.SELECTORS.FAQ_SIDEBAR}, ${CONFIG.SELECTORS.FAQ_OFFCANVAS}`).forEach(section => {
      section?.addEventListener('click', (e) => this.handleFaqClick(e));
    });

    DOMCache.get(CONFIG.SELECTORS.MESSAGES)?.addEventListener('click', (e) => this.handleSuggestedQuestionClick(e));

    /* Delegated, like the language toggle: the sidebar macro renders twice —
       once as the desktop aside, once inside the offcanvas — so there are two
       of these buttons and one listener is the whole wiring. */
    document.addEventListener('click', (event) => {
      const button = event.target.closest?.(`.${CONFIG.CLASSES.NEW_CHAT_BTN}`);
      if (button) this.handleNewChat(button);
    });
  },

  async handleAuthFormSubmit(event, source) {
    event.preventDefault();
    event.stopPropagation();
    ErrorHandler.clearErrors();

    const form = event.target;
    if (!form.checkValidity()) {
      form.classList.add('was-validated');
      return;
    }

    const email = form.querySelector(`#${source}-email`)?.value?.trim();
    const password = form.querySelector(`#${source}-password`)?.value;

    if (!email || !password) {
      ErrorHandler.showAuthError('Please fill in both email and password.');
      return;
    }

    try {
      if (source === 'login') {
        const data = await Services.login(email, password);
        this.hideModal('authModal', CONFIG.SELECTORS.AUTH_MODAL);
        form.reset();
        ErrorHandler.showToast(
          data?.user?.email ? `Logged in as ${data.user.email}` : 'Login successful!'
        );
      } else {
        await Services.signup(email, password);
        form.reset();
        ErrorHandler.showToast('Signup initiated! Please check your email to confirm.');
      }
    } catch (error) {
      logError(error, `handleAuthFormSubmit.${source}`);
      ErrorHandler.showAuthError(ErrorHandler.formatAuthError(error));
    }
  },

  async processChatRequestInternal(queryText, category = '') {
    /* Before anything touches the transcript, not after. An undo that survived
       into a new question would splice the old conversation around the new
       one, and the server has already moved on. */
    this.discardUndo();

    /* A new question makes whatever the panel is showing stale — it would sit
       beside an answer it has nothing to do with, in the one column the reader
       is watching for the new one. Here rather than in beginStreamingMessage,
       so the blocking path and a failed token check close it too. Focus is
       left where the reader put it: they asked a question, they are not
       looking at the previous answer's trigger. */
    SourcePanel.close({ restoreFocus: false });

    UI.addMessage(queryText, 'user');
    UI.setSendingState(true);
    RobotStateManager.reactToUser();

    try {
      let token;
      try {
        token = await Services.getSessionToken();
      } catch (error) {
        logError(error, 'processChatRequestInternal.getSessionToken');
        ErrorHandler.showToast(
          I18n.t('chat.sessionUnverified'),
          true
        );
        RobotStateManager.resetToIdle();
        return;
      }

      if (!token && !window.location.search.includes('testing=true')) {
        AppState.get('authModal')?.show();
        ErrorHandler.showToast(I18n.t('chat.loginRequired'), true);
        RobotStateManager.resetToIdle();
        return;
      }

      /* Minted HERE, once per logical submission, so a streaming attempt that
         falls back to the blocking route carries the SAME id. Minting inside
         each path would make the two look like two different questions to the
         server and file the exchange twice. */
      const requestId = newRequestId();
      if (CONFIG.STREAMING && 'body' in Response.prototype) {
        await this.streamChat(queryText, category, token, requestId);
      } else {
        await this.blockingChat(queryText, category, token, requestId);
      }
    } catch (error) {
      UI.toggleTypingIndicator(false);
      if (error?.name === 'AbortError') {
        RobotStateManager.resetToIdle();
        return;
      }

      logError(error, 'processChatRequestInternal');

      /* A disabled account is not a fault. The server understood perfectly and
         the answer is no, so the reader gets an explanation in their own
         language rather than "something went wrong" — which would send them
         retrying a thing that will never work. No error toast and no error
         face for the same reason: this is a decision about their account, not
         a malfunction. */
      if (error?.code === 'account_disabled') {
        UI.addMessage(I18n.t('auth.accountDisabled'), 'bot');
        RobotStateManager.resetToIdle();
        return;
      }

      UI.addMessage(I18n.t('chat.genericError'), 'bot');
      ErrorHandler.showToast(I18n.t('chat.sendFailed'), true);
      RobotStateManager.showError();
    } finally {
      UI.setSendingState(false);
      /* Both lines mark the same moment — this request is over. Here rather
         than inside streamChat because this is the one exit every path shares,
         including the one that rethrows. */
      activeStream = null;
    }
  },

  /**
   * End the conversation without ending the session.
   *
   * The server call goes FIRST and is awaited, and a failure leaves the
   * transcript untouched. The first draft of this cleared optimistically and
   * reconciled with the server afterwards; that was wrong twice over. It made
   * correctness depend on a later call landing — over a beacon that cannot
   * carry an Authorization header, across a language switch that reloads the
   * page — and its failure mode was the single worst state available here: a
   * blank screen over a server that still holds the history, so the next
   * answer silently carries context the reader believes they deleted.
   *
   * The server rotates the conversation rather than deleting it, which is why
   * undo can restore what the model remembers and not merely what the screen
   * showed. See the route in web/api/app.py.
   */
  async handleNewChat(button) {
    if (resetInFlight) return;
    resetInFlight = true;

    /* Restart the glyph's press, the way theme.js restarts its toggle spin:
       removing the class is not enough on its own because the style change is
       coalesced, so the reflow read forces it through. */
    if (button) {
      button.classList.remove(CONFIG.CLASSES.IS_ACTIVATING);
      void button.offsetHeight;
      button.classList.add(CONFIG.CLASSES.IS_ACTIVATING);
    }

    /* Anything still streaming belongs to the conversation being ended. The
       stamp is bumped before the abort so streamChat's handler sees the new
       value and declines to render into a bubble that is on its way out. */
    resetGeneration += 1;
    /* And the transcript epoch with it: a history fetch dispatched at sign-in
       can still be in flight, and letting it land after this would put the
       conversation the reader just ended straight back on screen. */
    transcriptEpoch += 1;
    const wasStreaming = AppState.isRequestInProgress();
    /* Captured BEFORE the abort and held directly, rather than read back off
       `activeStream` if the reset fails — see settleAbandonedStream for the
       question that answers. Reading it before the abort also removes any
       dependence on when the abort's rejection is scheduled. */
    const doomed = wasStreaming ? activeStream : null;
    if (wasStreaming) {
      Services.cancelChatRequest();
      UI.toggleTypingIndicator(false);
      UI.setSendingState(false);
    }

    try {
      await Services.resetConversation();
    } catch (error) {
      logError(error, 'handleNewChat');
      /* The transcript is staying, so the bubble the abort above left mid-flight
         is staying with it. streamChat declined to close it — it could not know
         this call would fail — which leaves that to here. */
      settleAbandonedStream(doomed);
      ErrorHandler.showToast(I18n.t('chat.resetFailed'), true);
      resetInFlight = false;
      return;
    }

    // An older set-aside conversation is unreachable now that this one replaced it.
    this.discardUndo();

    const fragment = await UI.playTranscriptExit();
    if (wasStreaming) dropInFlightExchange(fragment);

    /* reset, not close. close() only hides, which would leave the previous
       answer's passages sitting in the panel's DOM behind a "new" chat. Undo
       does not need them back: the panel rebuilds from stateByMessage, which
       survives the window, and the shelf never opens itself in any case. */
    SourcePanel.reset();

    // The FAQ list itself stays — it is what the sidebar is for.
    DOMCache.getAll(`.${CONFIG.CLASSES.FAQ_BUTTON}.${CONFIG.CLASSES.ACTIVE}`)
      .forEach(btn => btn.classList.remove(CONFIG.CLASSES.ACTIVE));

    RobotStateManager.resetToIdle();
    DOMCache.get(CONFIG.SELECTORS.MESSAGES)?.scrollTo({ top: 0 });
    DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT)?.focus();

    pendingUndo = fragment;
    resetInFlight = false;

    /* The toast is the only route to the undo, so the undo lives exactly as
       long as a route to it exists — no separate expiry timer, which would
       otherwise be free to kill the fragment while a held-open toast still
       showed the button. It ends on the next question, the next reset, or
       logout. */
    ErrorHandler.showToast(I18n.t('chat.cleared'), false, CONFIG.UNDO_DURATION, {
      actionLabel: I18n.t('chat.undo'),
      onAction: () => this.undoReset(),
    });
  },

  async undoReset() {
    if (!pendingUndo) return;

    try {
      await Services.resetConversation({ undo: true });
    } catch (error) {
      /* The reset itself stands, so the cleared view and the server still
         agree. Only the restoration failed — which is why this is not
         `chat.resetFailed`: that message says the conversation is unchanged,
         and here it is precisely the thing that did change. */
      logError(error, 'undoReset');
      pendingUndo = null;
      ErrorHandler.showToast(I18n.t('chat.restoreFailed'), true);
      return;
    }

    const fragment = pendingUndo;
    pendingUndo = null;
    /* An undo puts back a specific transcript. A history fetch that resolves
       afterwards would append a second copy of the same conversation underneath
       it, so the epoch moves here too — the screen changed, whichever direction
       it changed in. */
    transcriptEpoch += 1;
    UI.restoreTranscript(fragment);
    UI.scrollMessagesToBottom();
    ErrorHandler.showToast(I18n.t('chat.restored'));
  },

  /**
   * Let go of the conversation a reset set aside.
   *
   * The server call is best-effort: the ConversationStore's TTL is the
   * backstop, and logout purges both ids outright, so a dropped request costs
   * an unreachable entry an hour of memory rather than correctness.
   */
  /** The current transcript epoch; see the declaration for what bumps it. */
  transcriptEpoch() {
    return transcriptEpoch;
  },

  /** Declare that what is on screen is no longer the conversation it was. */
  beginTranscriptEpoch() {
    transcriptEpoch += 1;
  },

  /**
   * Drop everything scoped to the reader who just left, short of a full
   * sign-out.
   *
   * `clearSessionState` is the sign-out path and does more (it ends the server
   * session and cancels in-flight work). This is the narrower case: the
   * identity changed under a live page without a `SIGNED_OUT` in between, which
   * the auth SDK can do. Clearing only the transcript there would leave the
   * previous reader's passages in an open source panel and their entries in the
   * citation map — one reader's evidence sitting in the next reader's document,
   * which is the hazard the transcript's old ownership tag existed to prevent.
   */
  clearReaderScopedUI() {
    this.beginTranscriptEpoch();
    UI.clearTranscript();
    SourcePanel.reset();
    resetCitationState();
  },

  discardUndo() {
    if (!pendingUndo) return;
    pendingUndo = null;
    /* The toast is the only route to the undo, so it goes when the undo does.
       Leaving it up left an Undo button on screen that silently did nothing —
       and this runs on the reader's next question, which is the moment they
       are least able to tell a dead control from a slow one. */
    ErrorHandler.hideActionToast();
    resetCitationState();
    Services.resetConversation({ forget: true })
      .catch(error => logError(error, 'discardUndo'));
  },

  /** SSE path. The stage line reports the retrieval count mid-stream, but the
   *  passages themselves arrive on the terminal `final` frame — there is no
   *  honest way to present them as an answer's sources before the answer
   *  exists, and doing so is what put eight cards under a refusal. */
  async streamChat(queryText, category, token, requestId = null) {
    const handle = UI.beginStreamingMessage();
    /* Stamped at the start so every exit below can ask whether the
       conversation this answer belongs to still exists. */
    const generation = resetGeneration;
    /* Published for the one caller that can end up owning this bubble instead
       of the code below — see settleAbandonedStream. */
    activeStream = handle;
    let sawToken = false;
    let failed = null;

    let result = null;
    try {
      result = await Services.streamChatRequest(queryText, category, token, I18N_LANG, {
        stage: (d) => {
          RobotStateManager.onStage?.(d.stage, d);
          UI.setStage(handle, STAGE_LABELS[d.stage]
            ? STAGE_LABELS[d.stage](d)
            : null);
        },
        final: (d) => { handle.final = d; },
        delta: (d) => {
          if (!sawToken) {
            sawToken = true;
            UI.setStage(handle, null);
            RobotStateManager.startTalking();
          }
          handle.stream.push(d.t);
          UI.followStream();
        },
        suggestions: (d) => { handle.suggested = d.suggested_questions || []; },
        /* FIRST failure wins, not last. Two error frames can arrive in one
           stream — a persistence write that did not land, then a suggestions
           call that also failed — and the second is always the less
           informative one. Overwriting meant a reader whose answer merely
           went unsaved was told the message failed to send, which is both
           wrong and more alarming than the truth. */
        error: (d) => { failed = failed || d; },
        done: () => { /* terminal; the reader loop ends on its own */ },
      }, requestId);
    } catch (error) {
      /* A New chat ended this conversation, rather than the reader pressing
         Stop. The bubble is already leaving the transcript, and finishing it
         here would render a complete answer into nodes the undo fragment is
         about to hold — so an undo would resurrect an answer that was
         deliberately cleared, and one the server never recorded. handleNewChat
         owns the mascot and the send button on this path. */
      if (generation !== resetGeneration) return;

      if (error?.name === 'AbortError') {
        /* Cancelled. If `final` already arrived the answer is whole and
           normalized — the reader stopped a stream that had, unknown to them,
           already finished — so render it properly and mark it stopped.
           Falling back to raw deltas here would discard a complete answer and
           un-resolve its citations for pressing Stop a moment too late. */
        if (handle.final) {
          UI.finishStreamingMessage(handle, handle.suggested || [], handle.final);
          UI.flagIncomplete(handle, 'cancelled');
        } else {
          // Keep whatever arrived rather than leaving an empty bubble.
          UI.markStreamIncomplete(handle, 'cancelled');
        }
        RobotStateManager.resetToIdle();
        return;
      }
      if (handle.final) {
        UI.finishStreamingMessage(handle, handle.suggested || [], handle.final);
        UI.flagIncomplete(handle, 'error');
      } else {
        UI.markStreamIncomplete(handle, 'error');
      }
      throw error;
    }

    if (generation !== resetGeneration) {
      /* A New chat ended this conversation while the stream was resolving —
         but unlike the catch above, this one got all the way here, so the
         question of whether the server recorded the turn has an answer.
         `result.complete` means both `final` and `done` arrived, and the
         generator writes the turn to the store between them. It is therefore
         part of the conversation the reset set aside, and an undo will bring
         that conversation back.

         So it has to be finished. dropInFlightExchange drops whatever still
         carries aria-busy, and dropping this turn would restore a transcript
         that disagrees with what the model remembers — the one invariant undo
         exists to keep. The bubble is on its way off screen either way;
         handleNewChat owns the mascot and the send button on this path. */
      if (result?.complete && !failed) {
        UI.finishStreamingMessage(handle, handle.suggested || [], handle.final || null);
      }
      return;
    }

    if (failed) {
      /* A failure after streaming began cannot change the 200 status line, so
         it arrives in-band. Where it lands matters:

         BEFORE `final` — there is no canonical answer, so keep the partial
         text and flag it.

         AFTER `final` — the answer is complete and normalized; what failed is
         auxiliary (suggestion generation, history persistence). Discarding it
         to show a raw, unnormalized partial would throw away the good answer
         the reader already has, along with its citations, over a failure that
         did not touch it. Render it properly and toast the failure. */
      if (handle.final) {
        UI.finishStreamingMessage(handle, handle.suggested || [], handle.final);
      } else {
        UI.markStreamIncomplete(handle, 'error');
      }

      /* Two different failures, and they are owed different words. A history
         write that did not land says nothing about the answer above it — the
         reader has a complete, normalized, correctly cited response — so
         calling it "failed to send" describes the wrong thing entirely. */
      ErrorHandler.showToast(
        I18n.t(failed?.code === 'persistence_unavailable'
          ? 'chat.notSaved'
          : 'chat.sendFailed'),
        true,
      );

      /* And the mascot stays out of it when there IS an answer. An error state
         under a complete, cited answer contradicts the answer — the reader sees
         the assistant declaring failure over a response it just finished
         delivering. It fires only where the failure actually cost them
         something: before `final`, where there is no answer.

         The else is not optional. Suppressing showError() without scheduling a
         return to idle left Sunny talking forever: this branch returns before
         the returnToIdle() at the end of the happy path, so the animation had
         nothing to end it. */
      if (!handle.final) {
        RobotStateManager.showError();
      } else {
        RobotStateManager.returnToIdle(4000);
      }
      return;
    }

    if (result && !result.complete) {
      /* The socket closed without both `final` and `done`.

         No `final` — what arrived is a truncated answer that never went
         through citation normalization, so showing it as finished would
         present a half-answer as authoritative.

         `final` but no `done` — the answer itself is whole and normalized;
         only the close-out is missing, which most likely means the turn was
         never persisted to history. Falling back to the raw deltas here would
         throw away the canonical text and un-resolve its citations to punish
         a failure that happened after the answer was complete. Render it
         properly, then say the exchange did not finish.

         The inline note is kept here but not in the `failed` branch above,
         deliberately: there the server told us what went wrong and a toast
         carries it, whereas a dead socket says nothing at all, so the reader
         gets a marking that outlives the toast. */
      if (handle.final) {
        UI.finishStreamingMessage(handle, handle.suggested || [], handle.final);
        UI.flagIncomplete(handle, 'error');
      } else {
        UI.markStreamIncomplete(handle, 'error');
      }
      ErrorHandler.showToast(I18n.t('chat.sendFailed'), true);
      RobotStateManager.showError();
      return;
    }

    UI.finishStreamingMessage(handle, handle.suggested || [], handle.final || null);
    RobotStateManager.returnToIdle(4000);
  },

  /** Fallback for browsers without streaming bodies, or CONFIG.STREAMING off. */
  async blockingChat(queryText, category, token, requestId = null) {
    const generation = resetGeneration;
    const thinkingTimer = setTimeout(() => {
      RobotStateManager.startThinking();
      UI.toggleTypingIndicator(true);
    }, 800);

    try {
      const data = await Services.sendChatRequest(queryText, category, token, I18N_LANG, requestId);

      /* `sendChatRequest` sets `Services.chatAbortController` exactly as the
         streaming path does, so `cancelChatRequest` aborts this request too and
         a New chat mid-flight rejects it — an earlier note here claimed the
         opposite. The check still earns its place: abort and reply race, and a
         reply that already landed cannot be called back. What this declines is
         appending it to a conversation that no longer exists. */
      if (generation !== resetGeneration) return;

      UI.toggleTypingIndicator(false);
      RobotStateManager.startTalking();

      if (!data?.response) throw new Error(I18n.t('chat.invalidResponse'));
      UI.addMessage(data.response, 'bot', data.suggested_questions || [], data.sources || [], {
        cited: data.cited ?? null,
        retrieved: data.retrieved ?? (data.sources || []).length,
        // Always 'verified' from this route today, because a live answer came
        // from the active index. Carried anyway so the blocking and streaming
        // paths hand UI the same shape — a field present on one and absent from
        // the other is how two paths for one contract start to drift.
        evidenceState: data.evidence_state,
      });

      /* The blocking route reports the same auxiliary failure the streaming
         route sends as an `error` frame — it just has a JSON body to say it in.
         `=== false` rather than falsiness: an older server omits the field
         entirely, and treating "did not say" as "did not save" would toast a
         failure on every answer. The mascot stays out of it for the same reason
         it does on the streaming path — there is a complete answer on screen. */
      if (data.persisted === false) {
        ErrorHandler.showToast(I18n.t('chat.notSaved'), true);
      }
      RobotStateManager.returnToIdle(4000);
    } finally {
      clearTimeout(thinkingTimer);
    }
  },

  async handleFaqClick(event) {
    const button = event.target.closest(`.${CONFIG.CLASSES.FAQ_BUTTON}`);
    if (!button || AppState.isRequestInProgress()) return;

    DOMCache.getAll(`.${CONFIG.CLASSES.FAQ_BUTTON}.active`).forEach(btn => btn.classList.remove(CONFIG.CLASSES.ACTIVE));
    button.classList.add(CONFIG.CLASSES.ACTIVE);

    await this.processChatRequestInternal(button.dataset.question, button.dataset.category);
  },

  async processQuery() {
    const queryInput = DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT);
    const categorySelect = DOMCache.get(CONFIG.SELECTORS.CATEGORY_SELECT);
    if (!queryInput || !categorySelect) return;

    if (AppState.isRequestInProgress()) {
      Services.cancelChatRequest();
      ErrorHandler.showToast(I18n.t('chat.cancelled'), false);
      UI.toggleTypingIndicator(false);
      UI.setSendingState(false);
      return;
    }

    const query = queryInput.value.trim();
    if (!query) return;

    queryInput.value = '';
    const hiddenSelect = document.getElementById('query-category-hidden');
    const selectedCategory = categorySelect.dataset?.value || hiddenSelect?.value || 'all';
    await this.processChatRequestInternal(query, selectedCategory);
  },

  async handleSuggestedQuestionClick(event) {
    const button = event.target.closest(`.${CONFIG.CLASSES.SUGGESTED_BUTTON}`);
    if (!button || AppState.isRequestInProgress()) return;

    const questionText = button.dataset.questionText;
    if (!questionText) return;

    DOMCache.getAll(`.${CONFIG.CLASSES.SUGGESTED_BUTTON}`).forEach(btn => { btn.disabled = true; });

    const categorySelect = DOMCache.get(CONFIG.SELECTORS.CATEGORY_SELECT);
    const hiddenSelect = document.getElementById('query-category-hidden');
    const selectedCategory = categorySelect?.dataset?.value || hiddenSelect?.value || '';
    await this.processChatRequestInternal(questionText, selectedCategory);
  },

  /** Swap the login pane between signing in and asking for a reset link. */
  showResetRequest(show) {
    ErrorHandler.clearErrors();
    DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.classList.toggle(CONFIG.CLASSES.D_NONE, show);
    DOMCache.get(CONFIG.SELECTORS.RESET_REQUEST_FORM)?.classList.toggle(CONFIG.CLASSES.D_NONE, !show);
    DOMCache.get(CONFIG.SELECTORS.RESET_SENT)?.classList.add(CONFIG.CLASSES.D_NONE);
    if (show) DOMCache.get(CONFIG.SELECTORS.RESET_EMAIL)?.focus();
  },

  /**
   * Ask for a reset link.
   *
   * The success message is the same whether or not the address has an account,
   * because the server answers the same way — saying "no such account" here
   * would turn the form into a membership oracle. The reader is told to check
   * spam and given a way to reach a human, because "nothing arrived" is
   * otherwise a dead end by construction.
   */
  async handleResetRequestSubmit(event) {
    event.preventDefault();
    event.stopPropagation();
    ErrorHandler.clearErrors();

    const form = event.target;
    if (!form.checkValidity()) {
      form.classList.add('was-validated');
      return;
    }

    const email = DOMCache.get(CONFIG.SELECTORS.RESET_EMAIL)?.value?.trim();
    if (!email) return;

    const submit = form.querySelector('button[type="submit"]');
    try {
      await Services.requestPasswordReset(email, I18n.lang);
      DOMCache.get(CONFIG.SELECTORS.RESET_SENT)?.classList.remove(CONFIG.CLASSES.D_NONE);
      this.startResetCooldown(submit);
    } catch (error) {
      logError(error, 'handleResetRequestSubmit');
      const key = error?.code === 'reset_quota_exhausted'
        ? 'auth.emailUnavailable'
        : error?.code === 'reset_rate_limited'
          ? 'auth.tooSoon'
          : 'auth.emailUnavailable';
      ErrorHandler.showAuthError(I18n.t(key));
      this.startResetCooldown(submit);
    }
  },

  startResetCooldown(button) {
    if (!button) return;
    clearInterval(resetCooldownTimer);
    let left = Math.round(CONFIG.RESET_COOLDOWN_MS / 1000);
    const label = button.dataset.label || button.textContent.trim();
    button.dataset.label = label;
    button.disabled = true;

    const tick = () => {
      if (left <= 0) {
        clearInterval(resetCooldownTimer);
        resetCooldownTimer = null;
        button.disabled = false;
        button.textContent = label;
        return;
      }
      button.textContent = I18n.t('auth.recovery.resendIn', { count: left });
      left -= 1;
    };
    tick();
    resetCooldownTimer = setInterval(tick, 1000);
  },

  /**
   * Whether the recovery link actually produced a session.
   *
   * A marker with no session means expired, already used, or forged. The form is
   * disabled and the expired notice shown, because accepting a password we can
   * never save is a worse answer than saying so.
   */
  setRecoveryReady(ready) {
    const form = DOMCache.get(CONFIG.SELECTORS.RECOVERY_FORM);
    const expired = DOMCache.get(CONFIG.SELECTORS.RECOVERY_EXPIRED);
    if (form) form.classList.toggle(CONFIG.CLASSES.D_NONE, !ready);
    if (expired) expired.classList.toggle(CONFIG.CLASSES.D_NONE, ready);
    if (ready) DOMCache.get(CONFIG.SELECTORS.RECOVERY_PASSWORD)?.focus();
  },

  /**
   * Save the new password, then make them sign in with it.
   *
   * Not signed straight into chat, on purpose. OWASP's guidance is explicit that
   * auto-login after a reset adds session-handling complexity for no gain, and
   * making the reader use the new password now surfaces a password-manager
   * mismatch immediately rather than in three months.
   *
   * The sign-out is global, so a session an attacker holds on another device
   * dies here — Supabase does not do that on a password change by itself.
   */
  async handleRecoverySubmit(event) {
    event.preventDefault();
    event.stopPropagation();
    ErrorHandler.clearErrors();

    const form = event.target;
    if (!form.checkValidity()) {
      form.classList.add('was-validated');
      return;
    }

    const password = DOMCache.get(CONFIG.SELECTORS.RECOVERY_PASSWORD)?.value;
    const confirm = DOMCache.get(CONFIG.SELECTORS.RECOVERY_CONFIRM)?.value;

    if (password !== confirm) {
      ErrorHandler.showRecoveryError(I18n.t('auth.recovery.mismatch'));
      return;
    }

    /* One submission at a time, and the guard is never released on the success
       path. A second submit that overlaps the first would call `updateUser` on a
       session the first one has already invalidated by signing out globally —
       so the password would be changed and the reader told it failed, which
       sends them off to request another link they do not need. */
    if (recoverySubmitInFlight) return;
    recoverySubmitInFlight = true;

    /* Say something during the call, not just go dead. `updateUser` is a network
       round trip and the button is disabled for its duration, which without this
       reads as the form having ignored the click. */
    const submit = form.querySelector('button[type="submit"]');
    const submitLabel = submit?.textContent;
    if (submit) {
      submit.disabled = true;
      submit.textContent = I18n.t('auth.recovery.saving');
    }

    let email = null;
    try {
      const result = await Services.updatePassword(password);
      email = result?.user?.email ?? null;
    } catch (error) {
      logError(error, 'handleRecoverySubmit');
      ErrorHandler.showRecoveryError(I18n.t('auth.recovery.failed'));
      recoverySubmitInFlight = false;
      if (submit) {
        submit.disabled = false;
        submit.textContent = submitLabel;
      }
      return;
    }

    /* Past this line the password is already changed. Nothing below may report
       failure — a reader told "that did not work" would go and request another
       link for a password that is already theirs. */
    try {
      window.history.replaceState({}, '', '/');
    } catch (error) {
      logError(error, 'handleRecoverySubmit.replaceState');
    }
    await this.endRecovery();
    ErrorHandler.showToast(I18n.t('auth.recovery.done'));

    const loginEmail = document.getElementById('login-email');
    if (loginEmail && email) loginEmail.value = email;
    AppState.get('authModal')?.show();
  },

  /** Cancel: leave the view *and* end the session it was holding. */
  async handleRecoveryCancel() {
    await this.endRecovery();
  },

  /**
   * Drop the recovery session and return to the landing.
   *
   * Driven from here rather than from the SIGNED_OUT event: that event never
   * fires in the demo path, and may not fire if sign-out errors — either of
   * which would leave the reader on a form whose work is done. The event handler
   * in app.js still runs this path too, so both are idempotent.
   */
  async endRecovery() {
    try {
      await Services.logout();
    } catch (error) {
      logError(error, 'endRecovery.logout');
    }
    this.clearLocalAuthData();
    AppState.set('recoveryMode', false);
    AuthView.leaveRecovery(null);
    this.clearSessionState();
  },

  async handleProfileFormSubmit(event) {
    event.preventDefault();
    ErrorHandler.clearErrors();

    try {
      const sessionData = await Services.supabase?.auth.getSession();
      const user = sessionData?.data?.session?.user;

      if (!user) {
        return ErrorHandler.showProfileError(I18n.t('runtime.profile.sessionExpired'));
      }

      const formData = new FormData(event.target);
      // No updated_at. The `on_profile_update` trigger sets it from the server
      // clock on every update, and the column default covers the insert — so a
      // browser-supplied timestamp was both redundant and less trustworthy.
      // It is also the one key here the client has no privilege to write: the
      // profile columns are granted individually so that `role`, `tier` and
      // `is_disabled` cannot be, and a payload naming an ungranted column fails
      // the whole statement with "permission denied for table profiles".
      const updates = {
        full_name: formData.get('full_name'),
        organization: formData.get('organization'),
        specialization: formData.get('specialization'),
        preferences: { theme: formData.get('theme-preference') },
      };

      await Services.updateProfile(user.id, updates);
      AppState.set('userProfile', { ...AppState.get('userProfile'), ...updates });
      ThemeManager.apply(updates.preferences?.theme || CONFIG.CLASSES.LIGHT);
      ErrorHandler.showToast(I18n.t('runtime.profile.saved'));
      this.hideModal('profileModal', CONFIG.SELECTORS.PROFILE_MODAL);
    } catch (error) {
      // The raw error.message isn't translatable and can leak technical
      // detail to the reader; log it for diagnosis and keep the surfaced
      // message generic and bilingual.
      logError(error, 'handleProfileFormSubmit');
      ErrorHandler.showProfileError(I18n.t('runtime.profile.saveFailed'));
    }
  },

  async handleProfileButtonClick() {
    ErrorHandler.clearErrors();

    const sessionData = await Services.supabase?.auth.getSession();
    const user = sessionData?.data?.session?.user;

    if (!user) {
      ErrorHandler.showToast(I18n.t('runtime.profile.loginRequired'), true);
      AppState.get('authModal')?.show();
      return;
    }

    const cachedProfile = AppState.get('userProfile');
    if (cachedProfile) {
      UI.populateProfileForm(cachedProfile);
    } else {
      try {
        const profile = await Services.getProfile(user.id);
        if (profile) {
          AppState.set('userProfile', profile);
          UI.populateProfileForm(profile);
        } else {
          const form = DOMCache.get(CONFIG.SELECTORS.PROFILE_FORM);
          if (form) {
            form.reset();
            UI.selectThemeRadio(form, null);
          }
        }
      } catch (error) {
        logError(error, 'handleProfileButtonClick');
        ErrorHandler.showToast(I18n.t('runtime.profile.loadFailed'), true);
        const form = DOMCache.get(CONFIG.SELECTORS.PROFILE_FORM);
        form?.reset();
      }
    }

    AppState.get('profileModal')?.show();
  },

  async handleLogout(event) {
    event.preventDefault();
    try {
      const result = await Services.logout();
      this.clearLocalAuthData();
      AuthView.render(null);
      AppState.set('userProfile', null);
      this.clearSessionState();
      ErrorHandler.showToast(
        result?.testing ? 'Logged out successfully (testing mode)' : 'Logged out successfully'
      );
      this.redirectToHomeIfNeeded();
    } catch (error) {
      logError(error, 'handleLogout');
      this.clearLocalAuthData();
      AuthView.render(null);
      AppState.set('userProfile', null);
      this.clearSessionState();
      ErrorHandler.showToast('Logged out (session cleared)', false);
      this.redirectToHomeIfNeeded();
    }
  },

  /**
   * Drop everything in this tab that belonged to the signed-out reader.
   *
   * One function because there are two ways out — the logout button and a
   * session that expires or is revoked elsewhere (app.js routes
   * onAuthStateChange here) — and only one of them used to clean up. The tab
   * is not reloaded on the way out: the app lives at "/", so
   * redirectToHomeIfNeeded is a no-op, and AuthView only toggles `d-none` on
   * the authenticated view. Everything below therefore survives into the next
   * sign-in unless it is explicitly cleared, which on a regulatory product
   * means a second reader on a shared machine sees the first one's questions,
   * answers and evidence.
   *
   * The server side is handled by the logout route, which purges the store
   * entries behind `conv_id` and `prev_conv_id` and then clears the session —
   * so nothing of this reader's conversation survives on either side.
   */
  clearSessionState() {
    /* Dropped rather than discarded through discardUndo(): that would fire a
       forget request the logout route is about to make redundant, and the
       fragment holds the previous reader's answers. */
    pendingUndo = null;
    resetGeneration += 1;
    // Also invalidates any transcript fetch still in flight, which would
    // otherwise draw the departing reader's conversation into an empty page.
    transcriptEpoch += 1;

    // An in-flight answer would otherwise keep streaming into the hidden
    // transcript and repopulate the citation map after logout.
    Services.cancelChatRequest();
    /* Also reached when a session expires or is revoked rather than being
       signed out here, in which case Services.logout() never ran and the
       Flask cookie still holds conv_id. Not awaited — this function is the
       synchronous teardown, and the server rotates on an identity change
       regardless. On the logout-button path this is a duplicate of the call
       inside Services.logout(); the endpoint is idempotent. */
    Services.endServerSession();
    UI.clearTranscript();
    UI.hideAccountDisabledNotice();
    // reset, not close: closing leaves the previous reader's passages sitting
    // in the panel's DOM for the next one.
    SourcePanel.reset();
    resetCitationState();
    UI.Faq.clearButtons();
    try {
      sessionStorage.removeItem('sfda-transcript');
    } catch (error) {
      logError(error, 'clearSessionState: sessionStorage');
    }
  },

  clearLocalAuthData() {
    ['sb-access-token', 'sb-refresh-token', 'sb-user', 'sb-session', 'sfda-supabase-auth'].forEach(key => {
      try {
        localStorage.removeItem(key);
      } catch (error) {
        logError(error, `clearLocalAuthData: ${key}`);
      }
    });

    /* The recovery session lives in this tab's sessionStorage under its own key,
       so the loop above cannot reach it. Missing this would leave a usable token
       behind after cancel — which is the one thing cancel exists to prevent. */
    try {
      sessionStorage.removeItem(RECOVERY_STORAGE_KEY);
    } catch (error) {
      logError(error, 'clearLocalAuthData: recovery');
    }
  },

  redirectToHomeIfNeeded() {
    if (window.location.pathname !== '/') window.location.replace('/');
  },

  hideModal(stateKey, selector) {
    const modalElement = DOMCache.get(selector);
    const modal =
      AppState.get(stateKey) ||
      (modalElement && window.bootstrap?.Modal?.getOrCreateInstance(modalElement));
    modal?.hide();

    // Bootstrap ignores hide() while a fade-in transition is still running.
    // Fast mocked auth can resolve inside that window, so retry once after it.
    if (modalElement?.classList.contains('fade')) {
      setTimeout(() => {
        if (modalElement.classList.contains('show')) modal?.hide();
      }, 350);
    }
  },
};
