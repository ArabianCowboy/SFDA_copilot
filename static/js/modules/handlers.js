/**
 * SFDA Copilot — Event handlers
 * Wires up auth forms, chat input, FAQ/suggested questions and profile actions.
 */

import { CONFIG } from './config.js';
import { DOMCache, ErrorHandler, logError } from './dom.js';
import { AppState } from './state.js';
import { AuthView } from './auth-view.js';
import { UI } from './ui.js';
import { Services } from './services.js';
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

/* Guards the window between a reset's server call and its transcript clear,
   during which a second press would reset the freshly-started conversation. */
let resetInFlight = false;

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

export const Handlers = {
  bindEvents() {
    DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.addEventListener('submit', (e) => this.handleAuthFormSubmit(e, 'login'));
    DOMCache.get(CONFIG.SELECTORS.SIGNUP_FORM)?.addEventListener('submit', (e) => this.handleAuthFormSubmit(e, 'signup'));

    document.getElementById('login-btn-submit')?.addEventListener('click', (e) => {
      e.preventDefault();
      DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

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

      if (CONFIG.STREAMING && 'body' in Response.prototype) {
        await this.streamChat(queryText, category, token);
      } else {
        await this.blockingChat(queryText, category, token);
      }
    } catch (error) {
      UI.toggleTypingIndicator(false);
      if (error?.name === 'AbortError') {
        RobotStateManager.resetToIdle();
        return;
      }

      logError(error, 'processChatRequestInternal');
      UI.addMessage(I18n.t('chat.genericError'), 'bot');
      ErrorHandler.showToast(I18n.t('chat.sendFailed'), true);
      RobotStateManager.showError();
    } finally {
      UI.setSendingState(false);
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
    const wasStreaming = AppState.isRequestInProgress();
    if (wasStreaming) {
      Services.cancelChatRequest();
      UI.toggleTypingIndicator(false);
      UI.setSendingState(false);
    }

    try {
      await Services.resetConversation();
    } catch (error) {
      logError(error, 'handleNewChat');
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
         agree. Only the restoration failed. */
      logError(error, 'undoReset');
      pendingUndo = null;
      ErrorHandler.showToast(I18n.t('chat.resetFailed'), true);
      return;
    }

    const fragment = pendingUndo;
    pendingUndo = null;
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
  discardUndo() {
    if (!pendingUndo) return;
    pendingUndo = null;
    resetCitationState();
    Services.resetConversation({ forget: true })
      .catch(error => logError(error, 'discardUndo'));
  },

  /** SSE path. The stage line reports the retrieval count mid-stream, but the
   *  passages themselves arrive on the terminal `final` frame — there is no
   *  honest way to present them as an answer's sources before the answer
   *  exists, and doing so is what put eight cards under a refusal. */
  async streamChat(queryText, category, token) {
    const handle = UI.beginStreamingMessage();
    /* Stamped at the start so every exit below can ask whether the
       conversation this answer belongs to still exists. */
    const generation = resetGeneration;
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
        error: (d) => { failed = d; },
        done: () => { /* terminal; the reader loop ends on its own */ },
      });
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

    /* Same reasoning as the catch above, for a stream that ran to completion
       while the reset was resolving. */
    if (generation !== resetGeneration) return;

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
      ErrorHandler.showToast(I18n.t('chat.sendFailed'), true);
      RobotStateManager.showError();
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
  async blockingChat(queryText, category, token) {
    const generation = resetGeneration;
    const thinkingTimer = setTimeout(() => {
      RobotStateManager.startThinking();
      UI.toggleTypingIndicator(true);
    }, 800);

    try {
      const data = await Services.sendChatRequest(queryText, category, token, I18N_LANG);

      /* This path has no AbortController — cancelChatRequest only reaches the
         streaming one — so a New chat while the request was in the air cannot
         stop the answer arriving. What it can do is decline to append it to a
         conversation that no longer exists. */
      if (generation !== resetGeneration) return;

      UI.toggleTypingIndicator(false);
      RobotStateManager.startTalking();

      if (!data?.response) throw new Error(I18n.t('chat.invalidResponse'));
      UI.addMessage(data.response, 'bot', data.suggested_questions || [], data.sources || [], {
        cited: data.cited ?? null,
        retrieved: data.retrieved ?? (data.sources || []).length,
      });
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

  async handleProfileFormSubmit(event) {
    event.preventDefault();
    ErrorHandler.clearErrors();

    try {
      const sessionData = await Services.supabase?.auth.getSession();
      const user = sessionData?.data?.session?.user;

      if (!user) {
        return ErrorHandler.showProfileError('Your session seems to have expired. Please log out and log in again.');
      }

      const formData = new FormData(event.target);
      const updates = {
        full_name: formData.get('full_name'),
        organization: formData.get('organization'),
        specialization: formData.get('specialization'),
        preferences: { theme: formData.get('theme-preference') },
        updated_at: new Date(),
      };

      await Services.updateProfile(user.id, updates);
      AppState.set('userProfile', { ...AppState.get('userProfile'), ...updates });
      ThemeManager.apply(updates.preferences?.theme || CONFIG.CLASSES.LIGHT);
      ErrorHandler.showToast('Profile saved successfully!');
      this.hideModal('profileModal', CONFIG.SELECTORS.PROFILE_MODAL);
    } catch (error) {
      logError(error, 'handleProfileFormSubmit');
      ErrorHandler.showProfileError(`Failed to save: ${error.message}`);
    }
  },

  async handleProfileButtonClick() {
    ErrorHandler.clearErrors();

    const sessionData = await Services.supabase?.auth.getSession();
    const user = sessionData?.data?.session?.user;

    if (!user) {
      ErrorHandler.showToast('Please log in to manage your profile.', true);
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
            const defaultThemeRadio = form.querySelector(`input[name="theme-preference"][value="${ThemeManager.getCurrent()}"]`);
            if (defaultThemeRadio) defaultThemeRadio.checked = true;
          }
        }
      } catch (error) {
        logError(error, 'handleProfileButtonClick');
        ErrorHandler.showToast('Could not load your profile.', true);
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
