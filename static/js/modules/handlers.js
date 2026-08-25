/**
 * SFDA Copilot — Event handlers
 * Wires up auth forms, chat input, FAQ/suggested questions and profile actions.
 */

import { CONFIG } from './config.js';
import { DOMCache, ErrorHandler, logError, BroadcastNotice } from './dom.js';
import { AppState } from './state.js';
import { AuthView } from './auth-view.js';
import { UI } from './ui.js';
import { Services, RECOVERY_STORAGE_KEY, newRequestId } from './services.js';
import { RobotStateManager } from './robot.js';
import { I18n } from './i18n.js';
import { SourcePanel } from './source-panel.js';
import { resetCitationState } from './citations.js';
import { Route } from './route.js';

/* Sent with every chat request so the model answers in the reader's language. */
const I18N_LANG = I18n.lang;

/* Honest progress text, driven by real server stages rather than a timer. */
const STAGE_LABELS = {
  searching: () => I18n.t('stage.searching'),
  retrieved: (d) => I18n.plural(d.count, 'stage.retrievedOne', 'stage.retrieved'),
  drafting: () => I18n.t('stage.drafting'),
  finalizing: () => I18n.t('stage.finalizing'),
};

/* Bumped by every reset. A streaming request stamps itself with the value it
   started under, so its abort handler can tell "the reader pressed Stop" from
   "the conversation this answer belonged to no longer exists". */
let resetGeneration = 0;

/* Bumped whenever the transcript on screen stops being the conversation an
   in-flight history fetch was asked about: a New chat, a sidebar switch, a
   delete, or a sign-out. Distinct from `resetGeneration`, which guards a
   streaming ANSWER; this guards the TRANSCRIPT, and the two move
   independently — a sidebar switch restores a different transcript without
   touching any stream. */
let transcriptEpoch = 0;

/* Guards the window a New chat's own transcript-exit animation runs in,
   during which a second press would re-enter this function over its own
   in-progress navigation. */
let resetInFlight = false;

/* Bumped by every act that changes WHICH conversation the sidebar is showing —
   a selection, a delete that lands on the active row, and a New chat.
   `transcriptEpoch` guards the transcript's CONTENT against a late history
   fetch; this guards the sidebar's own asynchronous work against a selection
   that moved under it, which is a different question with a different answer.
   A list fetch dispatched for reader A's conversation A must not paint after
   the reader has already opened conversation B. */
let selectionEpoch = 0;

/* The conversation id the currently-streaming request belongs to, or null.
   Cleared in processChatRequestInternal's finally, alongside setSendingState
   — the two mark the same thing, the end of one request's lifetime. */
let activeStreamConversationId = null;

/* Ticks down the advisory cooldown on the reset button. Advisory only: GoTrue
   enforces one mail per address per minute and the server enforces its own rate
   limit — this exists so the reader is told how long is left instead of pressing
   a button that silently cannot work yet. */
let resetCooldownTimer = null;

/* Guards the one call in this flow that is not safe to repeat. Deliberately
   module-scoped rather than a form attribute: the form is torn down on success
   and the guard has to outlive it. */
let recoverySubmitInFlight = false;

/* Notification Center (docs/notification-center-plan.md §2/§4). Bumped on
   every start/stop of the poll — a sign-out, a sign-in, or the tab leaving
   or regaining visibility. An in-flight /active fetch stamps the value it
   started under, so a response that resolves after the reader signed out
   or switched identity is discarded rather than painted into the new
   session's bell/inbox — the same "race safety on the client" the plan
   requires of the (not yet wired) Realtime path, applied here to polling. */
let notificationsGeneration = 0;

/* Which notifications this tab has already shown as a toast/banner/modal
   this poll session, so a notification does not re-present itself every
   30s poll tick while it stays active and un-dismissed. Cleared whenever
   polling (re)starts for a fresh identity. */
let notificationsPresented = new Set();

export const Handlers = {
  bindEvents() {
    DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.addEventListener('submit', (e) =>
      this.handleAuthFormSubmit(e, 'login'),
    );
    DOMCache.get(CONFIG.SELECTORS.SIGNUP_FORM)?.addEventListener('submit', (e) =>
      this.handleAuthFormSubmit(e, 'signup'),
    );

    // The age field reveals only when marketing consent is ticked
    // (docs/profile-refactor-plan.md §12.3) — a CSS grid-row transition
    // (components.css), toggled by one class here.
    document.getElementById('signup-marketing-consent')?.addEventListener('change', (e) => {
      document.getElementById('signup-age-reveal')?.classList.toggle('is-open', e.target.checked);
      // Unticking clears any age already typed, so a reader who reconsiders
      // does not silently submit an age under a consent they withdrew before
      // sending the form.
      if (!e.target.checked) {
        const age = document.getElementById('signup-age');
        if (age) age.value = '';
      }
    });

    document.getElementById('login-btn-submit')?.addEventListener('click', (e) => {
      e.preventDefault();
      DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.dispatchEvent(
        new Event('submit', { bubbles: true, cancelable: true }),
      );
    });

    DOMCache.get(CONFIG.SELECTORS.FORGOT_LINK)?.addEventListener('click', () =>
      this.showResetRequest(true),
    );
    DOMCache.get(CONFIG.SELECTORS.RESET_BACK)?.addEventListener('click', () =>
      this.showResetRequest(false),
    );
    DOMCache.get(CONFIG.SELECTORS.RESET_REQUEST_FORM)?.addEventListener('submit', (e) =>
      this.handleResetRequestSubmit(e),
    );
    DOMCache.get(CONFIG.SELECTORS.RECOVERY_FORM)?.addEventListener('submit', (e) =>
      this.handleRecoverySubmit(e),
    );
    DOMCache.get(CONFIG.SELECTORS.RECOVERY_CANCEL)?.addEventListener('click', () =>
      this.handleRecoveryCancel(),
    );

    DOMCache.get(CONFIG.SELECTORS.SEND_BTN)?.addEventListener('click', () => this.processQuery());
    DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT)?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.processQuery();
      }
    });

    DOMCache.getAll(
      `${CONFIG.SELECTORS.LOGOUT_BTN}, ${CONFIG.SELECTORS.LOGOUT_BTN_OFFCANVAS}`,
    ).forEach((btn) => {
      btn?.addEventListener('click', (e) => this.handleLogout(e));
    });

    DOMCache.getAll(
      `${CONFIG.SELECTORS.AUTH_BTN}, ${CONFIG.SELECTORS.AUTH_BTN_OFFCANVAS}, ${CONFIG.SELECTORS.AUTH_BTN_MAIN}`,
    ).forEach((btn) => {
      btn?.addEventListener('click', () => AppState.get('authModal')?.show());
    });

    // No click binding for PROFILE_BTN/PROFILE_BTN_OFFCANVAS: it is a plain
    // <a href="/account"> now (docs/profile-refactor-plan.md §5) — the
    // browser navigates on its own. auth-view.js still shows/hides it by
    // sign-in state, same as every other account-scoped control.

    DOMCache.getAll(`${CONFIG.SELECTORS.FAQ_SIDEBAR}, ${CONFIG.SELECTORS.FAQ_OFFCANVAS}`).forEach(
      (section) => {
        section?.addEventListener('click', (e) => this.handleFaqClick(e));
      },
    );

    DOMCache.get(CONFIG.SELECTORS.MESSAGES)?.addEventListener('click', (e) =>
      this.handleSuggestedQuestionClick(e),
    );

    /* Delegated, like the language toggle: the sidebar macro renders twice —
       once as the desktop aside, once inside the offcanvas — so there are two
       of these buttons and one listener is the whole wiring. */
    document.addEventListener('click', (event) => {
      const button = event.target.closest?.(`.${CONFIG.CLASSES.NEW_CHAT_BTN}`);
      if (button) this.handleNewChat(button);
    });

    /* The conversation sidebar, on the same delegation for the same reason —
       twice-rendered, and repainted on every rename, delete and page, so a
       per-instance listener would need re-attaching after each repaint and
       would eventually fire one action twice. */
    document.addEventListener('click', (event) => this.handleSidebarClick(event));
    document.addEventListener('keydown', (event) => this.handleSidebarKeydown(event));

    // ── Notification Center ────────────────────────────────────────────
    DOMCache.getAll(
      `${CONFIG.SELECTORS.NOTIFICATIONS_BELL_BTN}, ${CONFIG.SELECTORS.NOTIFICATIONS_BELL_BTN_OFFCANVAS}`,
    ).forEach((btn) => {
      btn?.addEventListener('click', () => this.openNotificationsInbox());
    });
    document
      .getElementById('notifications-mark-all-read')
      ?.addEventListener('click', () => this.markAllNotificationsRead());
    document
      .getElementById('notifications-inbox-load-more')
      ?.addEventListener('click', () => this.loadMoreNotificationHistory());

    // Torn down/re-established with the tab's own visibility, per the plan's
    // reconnect/reconciliation rule: a hidden tab has no business polling,
    // and a tab that just became visible again is exactly the moment a
    // reader would notice a stale bell.
    document.addEventListener('visibilitychange', () => {
      if (!AppState.get('sidebarOwner')) return; // nobody signed in — nothing to poll
      if (document.hidden) this.stopNotificationsPolling();
      else this.startNotificationsPolling(AppState.get('notificationsUserId'));
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
      ErrorHandler.showAuthError(I18n.t('auth.missingFields'));
      return;
    }

    try {
      if (source === 'login') {
        await Services.login(email, password);
        this.hideModal('authModal', CONFIG.SELECTORS.AUTH_MODAL);
        form.reset();
        // No toast here: AuthView.render (driven by the auth-state listener,
        // not this handler) already writes `#user-status` from the frozen
        // `auth.loggedInAs` key and swaps in the authenticated view. A toast
        // saying the same thing a second time, in different words, was the
        // product stating one fact twice — see the signup panel below for
        // the reader-facing feedback this path still needs.
      } else {
        // family_name is optional; empty stays empty rather than becoming a
        // string GoTrue has to strip — handle_new_user already coerces "" to
        // null via nullif(), so sending "" here is harmless either way.
        const firstName = form.querySelector('#signup-first-name')?.value?.trim();
        const familyName = form.querySelector('#signup-family-name')?.value?.trim();
        // Marketing consent gates age (docs/profile-refactor-plan.md §12.3):
        // an unticked box means age is never sent at all, not sent-and-
        // ignored — handle_new_user coerces it to null regardless, but not
        // sending it is the honest client-side mirror of that rule.
        const consented = form.querySelector('#signup-marketing-consent')?.checked === true;
        const ageValue = form.querySelector('#signup-age')?.value;
        await Services.signup(
          email,
          password,
          {
            first_name: firstName,
            family_name: familyName,
            marketing_consent: consented,
            ...(consented
              ? {
                  marketing_consent_policy_version: window.__POLICY_VERSION,
                  marketing_consent_language: I18n.lang,
                  age: ageValue === '' || ageValue == null ? undefined : Number(ageValue),
                }
              : {}),
          },
          I18n.lang,
        );
        form.reset();
        this.showSignupSent(email);
      }
    } catch (error) {
      logError(error, `handleAuthFormSubmit.${source}`);
      ErrorHandler.showAuthError(ErrorHandler.formatAuthError(error));
    }
  },

  /**
   * Swap the signup form for a persistent confirmation panel, naming the
   * address back to the reader so a typo is visible at the one moment it can
   * still be fixed cheaply. Modelled on `showResetRequest`'s form-for-panel
   * swap, but the panel replaces the form outright rather than sitting above
   * it — signup has nothing left for the reader to do in this modal.
   *
   * A three-second toast used to be the only signal here, over a freshly
   * reset, empty form: to a reader who missed the toast the screen said
   * nothing happened. This is what `#reset-sent` already does one tab over.
   */
  showSignupSent(email) {
    DOMCache.get(CONFIG.SELECTORS.SIGNUP_FORM)?.classList.add(CONFIG.CLASSES.D_NONE);
    DOMCache.get(CONFIG.SELECTORS.SIGNUP_SENT)?.classList.remove(CONFIG.CLASSES.D_NONE);
    const heading = DOMCache.get(CONFIG.SELECTORS.SIGNUP_SENT_HEADING);
    const lead = DOMCache.get(CONFIG.SELECTORS.SIGNUP_SENT_LEAD);
    const spam = DOMCache.get(CONFIG.SELECTORS.SIGNUP_SENT_SPAM);
    if (heading) heading.textContent = I18n.t('auth.signupSent.heading');
    if (lead) lead.textContent = I18n.t('auth.signupSent.lead', { email });
    if (spam) spam.textContent = I18n.t('auth.signupSent.spam');
  },

  async processChatRequestInternal(queryText, category = '') {
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

    /* Whether the exchange reached its end without throwing. The durable write
       happens server-side at `final`, so this is the client's closest honest
       proxy for "the sidebar is now out of date" — a new conversation has just
       acquired its row and its title, or an existing one has moved to the top
       of the ordering. */
    let landed = false;
    /* Hoisted out of the try so the catch below can roll a failed first-turn
       mint back — see there for why. */
    let conversation = null;

    try {
      let token;
      try {
        token = await Services.getSessionToken();
      } catch (error) {
        logError(error, 'processChatRequestInternal.getSessionToken');
        ErrorHandler.showToast(I18n.t('chat.sessionUnverified'), true);
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

      /* §4.2: the conversation id, minted client-side exactly once, before
         the first request — never server-side, and never re-derived per
         attempt. If the URL already names one this is turn 2+ of an
         existing conversation and creation is refused; otherwise this is a
         brand-new conversation and `Route.enter` moves the URL to `/c/<id>`
         BEFORE the request goes out, replacing `/` rather than stacking on
         it. A server-minted id would leave the URL unable to change until
         the first frame arrived, and then changing it would move the ground
         out from under a running stream. */
      const existing = Route.current();
      if (existing) {
        conversation = { id: existing, allowCreate: false };
      } else {
        conversation = { id: crypto.randomUUID(), allowCreate: true };
        Route.enter(conversation.id);
      }

      if (CONFIG.STREAMING && 'body' in Response.prototype) {
        await this.streamChat(queryText, category, token, requestId, conversation);
      } else {
        await this.blockingChat(queryText, category, token, requestId, conversation);
      }
      landed = true;
    } catch (error) {
      UI.toggleTypingIndicator(false);

      /* The URL moved to `/c/<id>` before this attempt even reached the
         network, on the assumption it would land. It did not — and unlike a
         message failing against an EXISTING conversation (which stays
         exactly where it was), a freshly minted id that never lands must not
         linger as the URL: a same-tab retry would read it back from
         `Route.current()`, send it with `allow_create: false` as though it
         were turn 2 of a real conversation, and the preflight (§3.4) would
         404 a question that was never anything but the first. Rolled back
         only if nothing has navigated elsewhere since — a New chat or a
         sidebar click during this same failure must not be undone by it. */
      if (conversation?.allowCreate && Route.current() === conversation.id) {
        Route.replace(null);
      }

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
      /* All three mark the same moment — this request is over. Here rather
         than inside streamChat because this is the one exit every path shares,
         including the one that rethrows. */
      activeStreamConversationId = null;

      /* Re-read the list rather than patching it optimistically. The client
         cannot know what the row should say: the title is minted server-side by
         `clamp_title` from the opening question and applied only when the
         session had none, `updated_at` is set by Postgres, and the message
         count comes off `next_seq`. Guessing any of those produces a row that
         disagrees with the database until the next reload. One indexed read,
         once per completed exchange, is the cheaper kind of correct.

         Not awaited: this runs after the answer is on screen, and a slow list
         must not hold the composer. */
      if (landed && AppState.get('sidebarOwner')) {
        this.loadSessions(AppState.get('sidebarOwner')).catch((error) =>
          logError(error, 'processChatRequestInternal.loadSessions'),
        );
      }
    }
  },

  /**
   * End the conversation without ending the session.
   *
   * DECISION 2 (docs/per-tab-conversation-deep-linking-plan.md): "New chat"
   * is a navigation from `/c/<id>` to `/`, and undo is the Back button —
   * free, per-tab, already understood. There is no server call here any
   * more, and that is not an omission: a client-supplied conversation id has
   * no cookie to rotate, which was the entirety of what the old server round
   * trip did. `prev_conv_id`/`prev_chat_history` and the toast's undo action
   * are gone with it.
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
    if (wasStreaming) {
      Services.cancelChatRequest();
      UI.toggleTypingIndicator(false);
      UI.setSendingState(false);
    }

    /* The navigation itself. `go`, not `replace`: this IS the reader's
       deliberate choice §4.1 reserves `go` for, and it is what makes Back
       reach the conversation just ended. */
    Route.go(null);

    /* The sidebar follows. A New chat mints a conversation that does not exist
       in the database yet — session rows are written lazily, by the first
       completed turn — so there is no row to highlight and the correct state is
       "none of these". Leaving the previous row marked active would claim the
       reader's next question joins a conversation they just left. */
    selectionEpoch += 1;
    UI.History.setActive(null);

    // The exit animation plays and the detached turns are discarded — Back
    // is the undo now, and a Back navigation re-hydrates from the server
    // rather than restoring this DOM.
    await UI.playTranscriptExit();

    /* reset, not close. close() only hides, which would leave the previous
       answer's passages sitting in the panel's DOM behind a "new" chat. */
    SourcePanel.reset();
    resetCitationState();

    // The FAQ list itself stays — it is what the sidebar is for.
    DOMCache.getAll(`.${CONFIG.CLASSES.FAQ_BUTTON}.${CONFIG.CLASSES.ACTIVE}`).forEach((btn) =>
      btn.classList.remove(CONFIG.CLASSES.ACTIVE),
    );

    RobotStateManager.resetToIdle();
    DOMCache.get(CONFIG.SELECTORS.MESSAGES)?.scrollTo({ top: 0 });
    DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT)?.focus();

    resetInFlight = false;
    ErrorHandler.showToast(I18n.t('chat.cleared'));
  },

  /** The current transcript epoch; see the declaration for what bumps it. */
  transcriptEpoch() {
    return transcriptEpoch;
  },

  /** Declare that what is on screen is no longer the conversation it was. */
  beginTranscriptEpoch() {
    transcriptEpoch += 1;
  },

  // ── The conversation sidebar ────────────────────────────────────────────

  /** The current selection epoch; see the declaration for what bumps it. */
  selectionEpoch() {
    return selectionEpoch;
  },

  /**
   * Whether a sidebar action must be refused right now.
   *
   * ONE RULE FOR ALL THREE — switch, rename and delete — and it is the whole
   * mitigation for the two races this feature would otherwise ship.
   *
   * Delete is the sharp one. Both chat routes close over their conversation id
   * and write the turn at `final`, near the end; the sidebar's delete is a
   * separate request. Delete conversation A while its answer is still streaming
   * and the late `chat_append_turn` meets `on conflict (id) do nothing`, finds
   * no row, and CREATES ONE — the conversation the reader deleted comes back,
   * carrying the answer they thought they had discarded. There is no tombstone
   * in that table to prevent it.
   *
   * Switching is the quieter one. The server keeps writing that answer into the
   * conversation the reader left, so a conversation they navigated away from
   * silently gains a turn and the sidebar's title and ordering go stale until
   * something refreshes them.
   *
   * The server refuses both with 409 as well — see `_InFlightGenerations` — so
   * this is the affordance and that is the guarantee. A control that simply did
   * nothing would be worse than one that explains itself, which is why the
   * caller shows `sessions.busy` rather than swallowing the click.
   */
  sidebarIsBusy() {
    return AppState.isRequestInProgress();
  },

  _refuseWhileStreaming() {
    ErrorHandler.showToast(I18n.t('sessions.busy'), true);
  },

  /**
   * Load the first page of the reader's conversations.
   *
   * Not awaited by its caller, for the same reason the transcript read is not:
   * a slow list must not hold up sign-in. Stamped with the identity it was
   * dispatched for and checked on the way back, because a sign-out and a second
   * sign-in can both land while it is in flight and painting reader A's
   * conversation titles into reader B's sidebar is an account leak, not a
   * cosmetic race.
   */
  async loadSessions(identity) {
    const epoch = selectionEpoch;
    UI.History.setStatus('loading');
    UI.History.setTabLoading(true);

    try {
      const page = await Services.listSessions();
      if (epoch !== selectionEpoch) return;
      if (identity && identity !== AppState.get('sidebarOwner')) return;

      if (!page) {
        // Signed out. Not an error, and not an empty list either — there is
        // nobody to have conversations.
        UI.History.clear();
        return;
      }

      UI.History.setSessions({
        sessions: page.sessions || [],
        cursor: page.next_cursor || null,
        /* §5.3: NOT `page.active`. That field is filled from the session
           cookie, which a client-supplied conversation id never touches —
           "the client cannot know which conversation the server considers
           current" inverted the moment the client's own URL is that
           answer. Still served today (its removal is a §5 deletion, not a
           §4 one) but no longer trusted here: `page.active` would show a
           previous tab's cookie-repointed conversation as active in THIS
           tab, which per-tab conversations make routinely wrong rather
           than rare. */
        active: Route.current(),
      });

      /* THE DEFAULT TAB IS DECIDED HERE, once, from what came back. A reader
         with history lands on it; a first-time reader lands on the questions
         that start a session, which is what this column was originally for.
         Only on the FIRST load — flipping the tab under a reader who has since
         chosen the other one would be the app overruling them. */
      if (!AppState.get('sidebarTabSettled')) {
        AppState.set('sidebarTabSettled', true);
        this.showSidebarTab((page.sessions || []).length ? 'chats' : 'explore');
      }
    } catch (error) {
      if (epoch !== selectionEpoch) return;
      logError(error, 'loadSessions');
      UI.History.setStatus('error');
    } finally {
      UI.History.setTabLoading(false);
    }
  },

  async loadMoreSessions() {
    const { cursor, loadingMore } = UI.History.state;
    if (!cursor || loadingMore) return;

    const epoch = selectionEpoch;
    UI.History.setLoadingMore(true);
    try {
      const page = await Services.listSessions({ cursor });
      if (epoch !== selectionEpoch || !page) return UI.History.setLoadingMore(false);
      UI.History.appendSessions({
        sessions: page.sessions || [],
        cursor: page.next_cursor || null,
      });
    } catch (error) {
      logError(error, 'loadMoreSessions');
      UI.History.setLoadingMore(false);
      ErrorHandler.showToast(I18n.t('sessions.unavailable'), true);
    }
  },

  /**
   * Open one stored conversation.
   *
   * THE WHOLE TRANSITION LIVES HERE, in one place, and that is the point. Five
   * things are scoped to "the conversation on screen" and every one of them has
   * to move together: the transcript, the source panel, the citation map, the
   * URL, and the sidebar's active row. A version of this that cleared only the
   * transcript would leave the previous conversation's passages open in the
   * panel beside the new one's answers, and the reader would have no way to
   * tell whose evidence they were reading.
   *
   * §4.3's navigation state machine, the sidebar-click half of it. This is a
   * reader's DELIBERATE navigation — the other half is `handlePopState`,
   * which cannot be refused because the URL has already changed by the time
   * it runs. This one can, and must be: refuse first, navigate second, or
   * the URL moves before the busy check has had its say.
   *
   * THE EPOCH IS BUMPED AT INTENT, not after a server call succeeds — there
   * is no server call to succeed on any more. A second click before this
   * one's history fetch lands must not let the first one win, which is what
   * makes "the last click wins" true instead of "the first click that
   * resolves wins": every click bumps the epoch and every read checks it
   * before painting.
   */
  async openSession(sessionId) {
    if (!sessionId) return;
    if (Route.current() === sessionId) return this.closeSidebarDrawer();
    if (this.sidebarIsBusy()) return this._refuseWhileStreaming();

    const previousId = Route.current();
    selectionEpoch += 1;
    this.beginTranscriptEpoch();
    const epoch = transcriptEpoch;

    Route.go(sessionId);
    ErrorHandler.hideActionToast();

    UI.clearTranscript();
    SourcePanel.reset();
    resetCitationState();
    UI.History.setActive(sessionId);
    this.closeSidebarDrawer();

    try {
      const history = await Services.getChatHistory(sessionId);
      /* Checked after the await. The reader can press New chat, or pick a
         different conversation, while this is in flight — and drawing the
         one they abandoned is the resurrection the epoch exists to stop. A
         NEWER navigation has already painted its own transcript by the time
         a stale one resolves, so this is a silent no-op rather than a race
         the reader can see. */
      if (epoch !== transcriptEpoch) return;

      UI.hydrateTranscript(history.messages || []);
      Route.commit();
      UI.scrollMessagesToBottom();
      DOMCache.get(CONFIG.SELECTORS.QUERY_INPUT)?.focus();
    } catch (error) {
      if (epoch !== transcriptEpoch) return;
      logError(error, 'openSession');

      if (error?.code === 'generation_in_flight') {
        /* Not a missing conversation — a live one, refused for a different
           reason. The URL already moved; leaving it there is correct, since
           the conversation still exists and the reader can retry once the
           other tab's answer finishes. Only 404 rolls the URL back. */
        ErrorHandler.showToast(I18n.t('sessions.busy'), true);
        return;
      }

      /* A FAILED sidebar navigation rolls the URL back — the correction
         over the round-1 draft's account, which pushed first and never
         un-pushed. `openSession`'s own rule has always been "a failed
         select must leave the reader where they were", but `pushState` has
         already fired by the time this runs; without the rollback the
         reader sits on a URL naming a conversation they are not viewing,
         and their next question inherits the dead id — LibreChat #7700's
         shape, rebuilt locally. `Route.replace`, not `history.back()`: back
         would re-enter `handlePopState` and drive a second navigation. */
      this._conversationUnreachable(previousId);
    }
  },

  /**
   * The shared "this conversation could not be opened" path (§4.5). Used by
   * a failed sidebar navigation (`previousId` is where to roll back to) and
   * by a deep link or a Back/Forward traversal that 404s (`previousId` is
   * null — there is no "before" to return to). Both are the same fact from
   * the reader's side: the conversation this control pointed at is not
   * reachable, and the screen must say so rather than sit on a stale URL.
   */
  _conversationUnreachable(previousId) {
    Route.replace(previousId || null);
    UI.clearTranscript();
    SourcePanel.reset();
    resetCitationState();
    UI.History.setActive(previousId || null);
    ErrorHandler.showToast(I18n.t('sessions.switchFailed'), true);
  },

  /**
   * §4.3's navigation state machine, the Back/Forward half. Wired once, at
   * startup, to `Route.init` (route.js).
   *
   * CANNOT BE REFUSED — the other half of the split `openSession` is. The
   * URL has already changed by the time this runs, so there is nothing left
   * to refuse; a live stream is aborted and traversal proceeds regardless.
   * `pushState`/`replaceState` never fire `popstate` themselves, so this
   * only ever runs for genuine traversal — which is what makes
   * `openSession`'s own rollback (`Route.replace`) safe: it cannot
   * recursively re-enter this handler.
   */
  async handlePopState({ persisted: _persisted } = {}) {
    const id = Route.current();

    /* Forward into the SAME conversation a live stream is still writing
       into — the sharpest case here. The reader went Back then Forward (or
       a bfcache restore landed, `persisted: true`) while turn one was still
       resolving; the stream never stopped, only the URL moved away and
       back. Re-attaching means doing nothing at all: the transcript already
       shows this exchange, mid-flight, and clearing it would discard an
       answer that is still arriving over nothing having gone wrong. Forward
       into an id nothing is streaming falls through to the ordinary path
       below, where the uncommitted-marker check is what stops IT being
       reported missing. */
    if (id && id === activeStreamConversationId && AppState.isRequestInProgress()) {
      UI.History.setActive(id);
      return;
    }

    this.beginTranscriptEpoch();
    const epoch = transcriptEpoch;
    selectionEpoch += 1;

    if (!id) {
      // "/" — always a new chat (Decision 1a). Nothing to hydrate.
      UI.clearTranscript();
      SourcePanel.reset();
      resetCitationState();
      UI.History.setActive(null);
      return;
    }

    if (!Route.isCommitted()) {
      /* This tab minted `id` and the turn never landed — a reload mid-first-
         stream, or a Forward into that same abandoned attempt. Fetching
         would 404 a conversation that never existed; treated instead as
         what it is, an unfinished composer. `persisted` (bfcache) does not
         change this — a restored DOM showing a stale "not found" state is
         exactly what re-deriving from `Route` here corrects (§9's bfcache
         note), and an uncommitted entry restored from bfcache is equally
         stale regardless of which way it was reached. */
      Route.replace(null);
      UI.clearTranscript();
      SourcePanel.reset();
      resetCitationState();
      UI.History.setActive(null);
      return;
    }

    UI.clearTranscript();
    SourcePanel.reset();
    resetCitationState();
    UI.History.setActive(id);

    try {
      const history = await Services.getChatHistory(id);
      if (epoch !== transcriptEpoch) return;
      UI.hydrateTranscript(history.messages || []);
      UI.scrollMessagesToBottom();
    } catch (error) {
      if (epoch !== transcriptEpoch) return;
      logError(error, 'handlePopState');
      if (error?.code === 'not_found') {
        // The conversation is gone — deleted in another tab, most likely,
        // which per-tab conversations make more reachable than before.
        this._conversationUnreachable(null);
      } else {
        ErrorHandler.showToast(I18n.t('sessions.switchFailed'), true);
      }
    }
  },

  async saveSessionRename(sessionId, rawTitle) {
    if (!sessionId) return;

    try {
      const result = await Services.renameSession(sessionId, rawTitle);
      if (!result) return UI.History.setPending(null);
      /* The SERVER's clamped title, never the reader's raw input. `clamp_title`
         collapses whitespace and cuts on a word boundary at 120 characters, so
         echoing what was typed would show an untruncated name until the next
         reload — a row that quietly disagreed with the database. */
      UI.History.applyRename(sessionId, result.title || null);
      ErrorHandler.showToast(I18n.t('sessions.renamed'));
    } catch (error) {
      logError(error, 'saveSessionRename');
      UI.History.setPending(null);
      ErrorHandler.showToast(I18n.t('sessions.renameFailed'), true);
    }
  },

  /**
   * Delete one conversation, having already confirmed it inline.
   *
   * NOT OPTIMISTIC. Removing the row before the server agrees would have to be
   * rolled back on failure — restoring the title, the original index, the
   * active state and the scroll position — and a rollback that gets any of
   * those wrong is a delete that appears to half-work. The request is a single
   * indexed statement; waiting for it costs a moment and removes the whole
   * class of bug.
   */
  async deleteSession(sessionId) {
    if (!sessionId) return;
    if (this.sidebarIsBusy()) {
      UI.History.setPending(null);
      return this._refuseWhileStreaming();
    }

    /* §4.4: the ROUTE is what names the conversation on screen, not the
       sidebar's own active marker — the two can only disagree if something
       else already went wrong, and the route is the one the next question
       would actually be sent against. */
    const wasCurrent = Route.current() === sessionId;

    try {
      const result = await Services.deleteSession(sessionId);
      if (!result) return UI.History.setPending(null);

      UI.History.removeSession(sessionId);
      ErrorHandler.showToast(I18n.t('sessions.deleted'));

      /* The reader deleted the conversation the route on screen names. With
         no cookie, there is no server-minted replacement to adopt — under
         Decision 1(a) there is no such thing as "the replacement
         conversation" any more, only `/`, exactly as a deliberate New chat
         already lands on. `result.conversation_id` (the legacy rotated-
         cookie value an old-client server path may still echo) is
         deliberately NOT read here. Any pending hydration for the deleted
         id is invalidated by the epoch bump before the route moves, so a
         history fetch already in flight for it cannot land afterward and
         resurrect it on screen. */
      if (wasCurrent) {
        selectionEpoch += 1;
        this.beginTranscriptEpoch();
        Route.replace(null);
        ErrorHandler.hideActionToast();
        UI.clearTranscript();
        SourcePanel.reset();
        resetCitationState();
        UI.History.setActive(null);
      }
    } catch (error) {
      logError(error, 'deleteSession');
      UI.History.setPending(null);
      ErrorHandler.showToast(
        error?.code === 'generation_in_flight'
          ? I18n.t('sessions.busy')
          : I18n.t('sessions.deleteFailed'),
        true,
      );
    }
  },

  /**
   * Switch the sidebar between its two panels.
   *
   * Both panels stay in the DOM and one is `hidden`; rendering only the active
   * one would throw away the other's scroll position on every switch and would
   * make the FAQ rail — which app.js fills once, on sign-in — need refetching
   * each time the reader glanced at their history.
   *
   * Applied to BOTH rendered copies of the sidebar in one pass. Tracking them
   * separately is how the desktop aside and the offcanvas end up on different
   * tabs, which a reader only discovers by resizing.
   */
  showSidebarTab(which) {
    const isChats = which === 'chats';
    document.querySelectorAll(`.${CONFIG.CLASSES.SIDEBAR_TAB}`).forEach((tab) => {
      const selected = (tab.dataset.sidebarTab === 'chats') === isChats;
      tab.classList.toggle('is-active', selected);
      tab.setAttribute('aria-selected', String(selected));
      /* A tablist is ONE tab stop: only the selected tab is reachable with Tab,
         and the arrow keys move between them. Leaving both at 0 costs a
         keyboard reader an extra stop on every visit to this column. */
      tab.tabIndex = selected ? 0 : -1;
    });

    UI.History.panels().forEach((panel) => {
      panel.hidden = !isChats;
    });
    DOMCache.getAll(`${CONFIG.SELECTORS.FAQ_SIDEBAR}, ${CONFIG.SELECTORS.FAQ_OFFCANVAS}`).forEach(
      (panel) => {
        panel.hidden = isChats;
      },
    );
  },

  /**
   * Arrow-key navigation inside the tablist, per the ARIA authoring practice.
   *
   * `--flip` exists in the stylesheet for exactly this reason: in Arabic the
   * tabs are laid out right-to-left, so ArrowRight must move to the PREVIOUS
   * tab. Reading the document's own direction rather than the language keeps
   * this correct for any future locale.
   */
  handleSidebarTabKeydown(event) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    const rtl = document.documentElement.dir === 'rtl';
    const forward = rtl ? event.key === 'ArrowLeft' : event.key === 'ArrowRight';
    const current = event.target.dataset.sidebarTab;
    const next = forward
      ? current === 'chats'
        ? 'explore'
        : 'chats'
      : current === 'explore'
        ? 'chats'
        : 'explore';
    event.preventDefault();
    this.showSidebarTab(next);
    /* Focus follows selection, and it has to be the VISIBLE copy: both sidebars
       hold a tab with this attribute and one of them is in a hidden offcanvas.
       `offsetParent` is null for a display:none subtree, which is the test. */
    const tabs = [...document.querySelectorAll(`[data-sidebar-tab="${next}"]`)];
    (tabs.find((el) => el.offsetParent !== null) || tabs[0])?.focus();
  },

  /**
   * Dismiss the mobile drawer after a selection.
   *
   * ONE OFFCANVAS, ALWAYS. The source panel is the other panel on this page and
   * the two must never be open together on a phone: overlapping backdrops trap
   * focus with no reachable dismiss, and the reader's only way out is a reload.
   * Swapping the sidebar's contents IN PLACE rather than opening a second drawer
   * is what makes that impossible by construction; this just closes the one
   * drawer once the reader has chosen from it.
   */
  closeSidebarDrawer() {
    const offcanvas = document.getElementById('sidebarOffcanvas');
    if (!offcanvas || !window.bootstrap?.Offcanvas) return;
    window.bootstrap.Offcanvas.getInstance(offcanvas)?.hide();
  },

  /**
   * Every sidebar click, through one delegated listener on the document.
   *
   * DELEGATED, and not merely as a convenience. The sidebar macro renders twice
   * and the list repaints on every rename, delete and page — so per-instance
   * listeners would have to be re-attached after each repaint, which is the
   * shape that ends up firing one action twice. One listener on the document,
   * keyed by `data-history-action` and `data-session-id`, cannot.
   */
  handleSidebarClick(event) {
    const tab = event.target.closest?.(`.${CONFIG.CLASSES.SIDEBAR_TAB}`);
    if (tab) return this.showSidebarTab(tab.dataset.sidebarTab);

    const control = event.target.closest?.('[data-history-action]');
    if (!control) return;

    const action = control.dataset.historyAction;
    const sessionId = control.dataset.sessionId;

    switch (action) {
      case 'open':
        return this.openSession(sessionId);
      case 'retry':
        return this.loadSessions(AppState.get('sidebarOwner'));
      case 'more':
        return this.loadMoreSessions();
      case 'rename':
        if (this.sidebarIsBusy()) return this._refuseWhileStreaming();
        return UI.History.setPending({ id: sessionId, mode: 'rename' });
      case 'rename-cancel':
        return UI.History.setPending(null);
      case 'rename-save': {
        const input = control
          .closest(`.${CONFIG.CLASSES.HISTORY_ITEM}`)
          ?.querySelector('[data-rename-input]');
        return this.saveSessionRename(sessionId, input ? input.value : '');
      }
      case 'delete':
        if (this.sidebarIsBusy()) return this._refuseWhileStreaming();
        return UI.History.setPending({ id: sessionId, mode: 'delete' });
      case 'delete-cancel':
        return UI.History.setPending(null);
      case 'delete-confirm':
        return this.deleteSession(sessionId);
      default:
        return undefined;
    }
  },

  /** Enter commits a rename, Escape abandons it. */
  handleSidebarKeydown(event) {
    const tab = event.target.closest?.(`.${CONFIG.CLASSES.SIDEBAR_TAB}`);
    if (tab) return this.handleSidebarTabKeydown(event);

    const input = event.target.closest?.('[data-rename-input]');
    if (!input) return;

    if (event.key === 'Enter') {
      event.preventDefault();
      this.saveSessionRename(input.dataset.renameInput, input.value);
    } else if (event.key === 'Escape') {
      /* Stopped, so the same Escape does not also close the offcanvas. A reader
         abandoning a rename means "undo this edit", not "leave the sidebar" —
         and having one key do both, in an order the reader cannot predict, is
         the ambiguity a nested dismissible surface always brings. */
      event.preventDefault();
      event.stopPropagation();
      UI.History.setPending(null);
    }
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
    // Unlike the history notice (unconditionally redrawn for the new reader
    // right after this call, via showHistoryNotice's own remove-then-redraw),
    // the completion notice only redraws if the new reader's profile also
    // turns out incomplete — so it needs an explicit hide here, or reader A's
    // strip survives on screen for reader B if B's own profile is complete.
    UI.hideProfileCompletionNotice();
    /* The sidebar moves with everything else scoped to the reader who left.
       These rows are their own opening questions, and the app lives at "/" so
       nothing reloads on the way out — leaving them drawn behind the landing
       view is the same hazard the transcript's ownership tag existed to
       prevent, applied to the index of the transcript instead of the transcript.
       The epoch bump is what stops a list fetch dispatched for them painting
       into the next reader's column when it lands. */
    selectionEpoch += 1;
    UI.History.clear();
    AppState.set('sidebarTabSettled', false);
    UI.clearTranscript();
    SourcePanel.reset();
    resetCitationState();
    // Same reasoning as the sidebar rows above: an active broadcast list is
    // scoped to the reader who was signed in, and re-fetched fresh for
    // whoever replaced them once identity resolves again.
    this.stopNotificationsPolling();
    AppState.set('notificationsUserId', null);
    UI.Notifications.setUnreadCount(0);
  },

  /**
   * Notification Center (docs/notification-center-plan.md §2/§4). The full
   * hybrid delivery: a poll floor (REST is the guaranteed-delivery path,
   * regardless of Realtime's own health) plus a private per-user Realtime
   * channel that reconciles immediately on every message AND on every
   * successful (re)subscribe — covering both a live push and a reconnect
   * after a drop with the exact same code path.
   *
   * `userId` is the real Supabase auth user id, not the `sidebarOwner`
   * identity string `app.js` otherwise uses (which falls back to an email
   * under the `?testing=true` bypass, where there is no real session and
   * therefore no channel to authorize at all — `Services.notifications
   * .subscribe` already no-ops on a falsy id, so passing null there is
   * correct, not a gap).
   */
  startNotificationsPolling(userId = null) {
    this.stopNotificationsPolling();
    AppState.set('notificationsUserId', userId);
    notificationsGeneration += 1;
    const generation = notificationsGeneration;
    notificationsPresented = new Set();

    const tick = () => this.fetchActiveNotifications(generation);
    tick(); // reconcile immediately — every (re)start is also a fresh read
    AppState.set('notificationsPollTimer', setInterval(tick, 45000));

    if (userId) {
      Services.notifications.subscribe(userId, {
        onMessage: () => {
          if (generation !== notificationsGeneration) return;
          this.fetchActiveNotifications(generation);
        },
        onStatusChange: (status) => {
          if (generation !== notificationsGeneration) return;
          if (status === 'SUBSCRIBED') this.fetchActiveNotifications(generation);
        },
      });
    }
  },

  /** Torn down on sign-out, on identity change, and while the tab is
   * hidden — NOT on a full sign-out's own notificationsUserId, which
   * `clearSessionState`/`clearReaderScopedUI` clear explicitly, so the
   * Page Visibility restart below still knows who to resubscribe as
   * for an ordinary tab-hide/show that never left the same reader signed
   * in. */
  stopNotificationsPolling() {
    const timer = AppState.get('notificationsPollTimer');
    if (timer) clearInterval(timer);
    AppState.set('notificationsPollTimer', null);
    Services.notifications.unsubscribe();
    notificationsGeneration += 1; // discard any fetch already in flight
  },

  async fetchActiveNotifications(generation) {
    let response;
    try {
      response = await Services.notifications.fetchActive();
    } catch (error) {
      // Silent by design: a failed poll tick is not a user-facing failure
      // the way a chat request's is — it costs the bell one refresh cycle,
      // and the next tick tries again. Logged for diagnosis only.
      logError(error, 'fetchActiveNotifications');
      return;
    }
    if (generation !== notificationsGeneration) return; // stale — reader signed out/switched
    if (!response) return; // 401 — nobody signed in

    const items = response.notifications || [];
    AppState.set('notificationsActive', items);
    UI.Notifications.setUnreadCount(items.filter((n) => !n.read_at).length);

    items
      .filter((n) => !notificationsPresented.has(n.id) && !BroadcastNotice.isSnoozed(n.id))
      .forEach((n) => this.presentNotification(n));
  },

  /** Route one active notification to its display shape. Fires at most once
   * per id per poll session — see `notificationsPresented`. */
  presentNotification(notification) {
    notificationsPresented.add(notification.id);

    if (notification.type === 'toast') {
      UI.Notifications.pulseBadge();
      BroadcastNotice.showToast(notification, {
        onDismiss: (reason) => {
          if (reason === 'manual') this.markNotificationRead(notification.id, 'dismissed');
        },
      });
      return;
    }

    if (notification.type === 'banner') {
      UI.Notifications.pulseBadge();
      BroadcastNotice.showBanner(notification, {
        onDismiss: (id) => this.markNotificationRead(id, 'dismissed'),
      });
      return;
    }

    // 'modal': at most one shown at once (BroadcastCoordinator, per the
    // plan) — AppState.notificationsOpenModalId is the guard. A second
    // modal-type notification arriving while one is open simply waits for
    // the next poll tick, by which point the first will have been acted on.
    if (AppState.get('notificationsOpenModalId')) return;
    AppState.set('notificationsOpenModalId', notification.id);
    UI.Notifications.pulseBadge();
    BroadcastNotice.showModal(notification, {
      onAcknowledge: () => {
        AppState.set('notificationsOpenModalId', null);
        this.markNotificationRead(notification.id, 'acknowledged');
      },
      onSnooze: () => {
        AppState.set('notificationsOpenModalId', null);
        BroadcastNotice.snooze(notification.id);
      },
    });
  },

  async markNotificationRead(notificationId, action) {
    try {
      await Services.notifications.markRead(notificationId, action);
    } catch (error) {
      logError(error, `markNotificationRead:${action}`);
      ErrorHandler.showToast(I18n.t('chat.notifications.markReadFailed'), true);
      return;
    }
    // Drop it from the cached active list so a reopened inbox and the badge
    // agree without waiting for the next poll tick.
    const remaining = (AppState.get('notificationsActive') || []).filter(
      (n) => n.id !== notificationId,
    );
    AppState.set('notificationsActive', remaining);
    UI.Notifications.setUnreadCount(remaining.filter((n) => !n.read_at).length);
  },

  async markAllNotificationsRead() {
    try {
      await Services.notifications.markAllRead();
    } catch (error) {
      logError(error, 'markAllNotificationsRead');
      ErrorHandler.showToast(I18n.t('chat.notifications.markAllReadFailed'), true);
      return;
    }
    const active = (AppState.get('notificationsActive') || []).map((n) => ({
      ...n,
      read_at: n.read_at || new Date().toISOString(),
    }));
    AppState.set('notificationsActive', active);
    UI.Notifications.setUnreadCount(0);
    this.loadNotificationHistory({ reset: true });
  },

  /** Open the inbox modal and load its first page. A row opening marks it
   * read server-side (notifications_list_history_for_reader's own served_at
   * stamp handles "served"; opening the row itself sends the explicit
   * `read` action). */
  openNotificationsInbox() {
    const el = DOMCache.get(CONFIG.SELECTORS.NOTIFICATIONS_INBOX_MODAL);
    if (!el || !window.bootstrap?.Modal) return;
    const modal = window.bootstrap.Modal.getOrCreateInstance(el);
    AppState.set('notificationsInboxModal', modal);
    modal.show();
    this.loadNotificationHistory({ reset: true });
  },

  async loadNotificationHistory({ reset = false } = {}) {
    if (reset) {
      AppState.set('notificationsHistoryCursor', null);
      AppState.set('notificationsHistoryExhausted', false);
    }
    UI.Notifications.setInboxLoading(true);

    let response;
    try {
      response = await Services.notifications.fetchHistory({
        cursor: reset ? null : AppState.get('notificationsHistoryCursor'),
      });
    } catch (error) {
      logError(error, 'loadNotificationHistory');
      UI.Notifications.setInboxLoading(false);
      UI.Notifications.setInboxUnavailable(true);
      return;
    }
    UI.Notifications.setInboxLoading(false);

    if (!response) {
      UI.Notifications.setInboxUnavailable(true);
      return;
    }

    const items = response.notifications || [];
    const combined = reset
      ? items
      : (AppState.get('notificationsHistoryItems') || []).concat(items);
    AppState.set('notificationsHistoryItems', combined);
    AppState.set('notificationsHistoryCursor', response.next_cursor || null);
    AppState.set('notificationsHistoryExhausted', !response.next_cursor);

    UI.Notifications.renderInboxList(combined, {
      onOpen: (item) => this.openNotificationFromInbox(item),
    });
  },

  loadMoreNotificationHistory() {
    if (AppState.get('notificationsHistoryExhausted')) return;
    this.loadNotificationHistory({ reset: false });
  },

  /** A row activated from the inbox: mark it read (idempotent — the RPC
   * itself only ever sets read_at once) and reflect that in the list
   * without a full reload. */
  async openNotificationFromInbox(item) {
    if (!item.read_at) await this.markNotificationRead(item.id, 'read');
    const items = (AppState.get('notificationsHistoryItems') || []).map((n) =>
      n.id === item.id ? { ...n, read_at: n.read_at || new Date().toISOString() } : n,
    );
    AppState.set('notificationsHistoryItems', items);
    UI.Notifications.renderInboxList(items, {
      onOpen: (row) => this.openNotificationFromInbox(row),
    });
  },

  /** SSE path. The stage line reports the retrieval count mid-stream, but the
   *  passages themselves arrive on the terminal `final` frame — there is no
   *  honest way to present them as an answer's sources before the answer
   *  exists, and doing so is what put eight cards under a refusal. */
  async streamChat(queryText, category, token, requestId = null, conversation = null) {
    const handle = UI.beginStreamingMessage();
    /* Stamped at the start so every exit below can ask whether the
       conversation this answer belongs to still exists. */
    const generation = resetGeneration;
    /* Published for handleNewChat, which can end up owning this bubble — it
       aborts the stream and walks away, leaving the teardown to whichever
       catch below actually runs. `handlePopState`'s re-attach check (§4.3)
       needs to know WHICH conversation is still streaming, not merely that
       one is. */
    activeStreamConversationId = conversation?.id ?? null;
    let sawToken = false;
    let failed = null;

    let result;
    try {
      result = await Services.streamChatRequest(
        queryText,
        category,
        token,
        I18N_LANG,
        {
          /* §3.2's reconciliation rule: the server's resolved id wins over
           whatever this tab sent. A no-op on the happy path (client-minted
           v4, echoed back unchanged) — it matters only where the server
           minted instead: a malformed id, or an old client's cookie
           fallback still inside the §8 rollout window, which are exactly
           the cases where a silent divergence would be hardest to
           diagnose. `Route.replace`, not `enter`: the reconciled id may
           already be a real, committed conversation (a resumed one), and
           `replace` is the safer default either way — see its own comment
           for why a premature "uncommitted" here still degrades gracefully. */
          meta: (d) => {
            if (d.conversation_id && d.conversation_id !== Route.current()) {
              Route.replace(d.conversation_id);
            }
          },
          stage: (d) => {
            RobotStateManager.onStage?.(d.stage, d);
            UI.setStage(handle, STAGE_LABELS[d.stage] ? STAGE_LABELS[d.stage](d) : null);
          },
          final: (d) => {
            handle.final = d;
          },
          delta: (d) => {
            if (!sawToken) {
              sawToken = true;
              UI.setStage(handle, null);
              RobotStateManager.startTalking();
            }
            handle.stream.push(d.t);
            UI.followStream();
          },
          suggestions: (d) => {
            handle.suggested = d.suggested_questions || [];
          },
          /* FIRST failure wins, not last. Two error frames can arrive in one
           stream — a persistence write that did not land, then a suggestions
           call that also failed — and the second is always the less
           informative one. Overwriting meant a reader whose answer merely
           went unsaved was told the message failed to send, which is both
           wrong and more alarming than the truth. */
          error: (d) => {
            failed = failed || d;
          },
          done: () => {
            /* terminal; the reader loop ends on its own */
          },
        },
        requestId,
        conversation,
      );
    } catch (error) {
      /* A New chat ended this conversation, rather than the reader pressing
         Stop. The bubble is already leaving the transcript — handleNewChat
         has detached it and discarded the fragment — so finishing it here
         would paint into a node nothing will ever show again. handleNewChat
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
      /* A New chat ended this conversation while the stream was resolving.
         `handleNewChat` already detached this bubble along with the rest of
         the transcript and discarded it — Back is undo now (Decision 2), and
         a Back navigation re-hydrates from the server rather than restoring
         any DOM this tab held onto, so there is nothing left here to finish
         or paint. The bubble's own mascot/send-button state is already
         handleNewChat's, not this call's, on this path.

         `result.complete` still matters as a FACT, even though there is
         nothing left to render: it means both `final` and `done` arrived, so
         the turn is a real, durable conversation the reader can reach again
         directly at `/c/<id>` — just not, in this one interleaving, via
         Back. `Route.current()` no longer names this conversation — New chat
         already moved the URL to `/` — and the History API has no way to
         reach back into an entry that is no longer current to flip its
         `committed` marker, so that entry stays `committed: false`
         indefinitely even though the row it names is now real. A known,
         narrow gap: Back into that specific entry shows a fresh composer
         rather than the conversation, in exactly this one interleaving. Not
         a data-loss or security gap — the row exists regardless. */
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
        I18n.t(failed?.code === 'persistence_unavailable' ? 'chat.notSaved' : 'chat.sendFailed'),
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

    /* §4.2: committed only here — `result.complete` (both `final` and `done`
       arrived) with no `persistence_unavailable` in between is the client's
       confirmation the turn was durably filed, not merely streamed. Marking
       it earlier, at `final`, would reopen the same false-404-on-reload
       window this exists to close, just narrower: the durable write itself
       runs AFTER `final` is yielded (verified against `app.py:2610` →
       `:2642` → `:2661`), not at it. */
    Route.commit();
    UI.finishStreamingMessage(handle, handle.suggested || [], handle.final || null);
    RobotStateManager.returnToIdle(4000);
  },

  /** Fallback for browsers without streaming bodies, or CONFIG.STREAMING off. */
  async blockingChat(queryText, category, token, requestId = null, conversation = null) {
    const generation = resetGeneration;
    const thinkingTimer = setTimeout(() => {
      RobotStateManager.startThinking();
      UI.toggleTypingIndicator(true);
    }, 800);

    try {
      const data = await Services.sendChatRequest(
        queryText,
        category,
        token,
        I18N_LANG,
        requestId,
        conversation,
      );

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

      /* §3.2's reconciliation rule — see streamChat's `meta` handler for the
         full argument. The blocking route has no earlier frame to carry
         this, so it lands with the rest of the response. */
      if (data.conversation_id && data.conversation_id !== Route.current()) {
        Route.replace(data.conversation_id);
      }

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
      } else {
        // §4.2: committed once the server confirms the turn was durably
        // filed. `!== false` rather than `=== true`, matching the toast
        // check above: an older server that omits the field entirely must
        // not be read as "not persisted".
        Route.commit();
      }
      RobotStateManager.returnToIdle(4000);
    } finally {
      clearTimeout(thinkingTimer);
    }
  },

  async handleFaqClick(event) {
    const moreButton = event.target.closest(`.${CONFIG.CLASSES.FAQ_MORE}`);
    if (moreButton) return UI.Faq.expandGroup(moreButton.dataset.faqMore, moreButton);

    const button = event.target.closest(`.${CONFIG.CLASSES.FAQ_BUTTON}`);
    if (!button) return;
    /* Refuse loudly, not silently: a second question fired mid-stream used to
       return here with no response at all, which reads as a dead button
       rather than a busy one. See handleSuggestedQuestionClick below for the
       identical guard on the composer's suggested-chip path. */
    if (AppState.isRequestInProgress()) {
      ErrorHandler.showToast(I18n.t('chat.busy'), true);
      return;
    }

    DOMCache.getAll(`.${CONFIG.CLASSES.FAQ_BUTTON}.active`).forEach((btn) =>
      btn.classList.remove(CONFIG.CLASSES.ACTIVE),
    );
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
    if (!button) return;
    if (AppState.isRequestInProgress()) {
      ErrorHandler.showToast(I18n.t('chat.busy'), true);
      return;
    }

    const questionText = button.dataset.questionText;
    if (!questionText) return;

    DOMCache.getAll(`.${CONFIG.CLASSES.SUGGESTED_BUTTON}`).forEach((btn) => {
      btn.disabled = true;
    });

    const categorySelect = DOMCache.get(CONFIG.SELECTORS.CATEGORY_SELECT);
    const hiddenSelect = document.getElementById('query-category-hidden');
    const selectedCategory = categorySelect?.dataset?.value || hiddenSelect?.value || '';
    await this.processChatRequestInternal(questionText, selectedCategory);
  },

  /** Swap the login pane between signing in and asking for a reset link. */
  showResetRequest(show) {
    ErrorHandler.clearErrors();
    DOMCache.get(CONFIG.SELECTORS.LOGIN_FORM)?.classList.toggle(CONFIG.CLASSES.D_NONE, show);
    DOMCache.get(CONFIG.SELECTORS.RESET_REQUEST_FORM)?.classList.toggle(
      CONFIG.CLASSES.D_NONE,
      !show,
    );
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
      const key =
        error?.code === 'reset_quota_exhausted'
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

    let email;
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
      /* §4.6: this used to hard-code '/' and pass `{}`, silently discarding
         a deep link's path and its `history.state.convId` along with it — a
         signed-out reader who opened `/c/<id>`, clicked "forgot password",
         and completed recovery lost the path they arrived on. Only the
         `?recovery=1` marker is stripped; the pathname a reader arrived on
         (a deep link included) is preserved so sign-in hydrates it, exactly
         as an ordinary sign-in on that path already would. The hash is
         dropped outright rather than selectively — `isRecoveryCallback`
         (services.js) is the only thing that ever puts anything there, so
         nothing legitimate survives it. */
      const url = new URL(window.location.href);
      url.searchParams.delete('recovery');
      window.history.replaceState({ ...window.history.state }, '', url.pathname + url.search);
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

  async handleLogout(event) {
    event.preventDefault();
    try {
      const result = await Services.logout();
      this.clearLocalAuthData();
      AuthView.render(null);
      AppState.set('userProfile', null);
      this.clearSessionState();
      ErrorHandler.showToast(
        result?.testing ? 'Logged out successfully (testing mode)' : 'Logged out successfully',
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
    resetGeneration += 1;
    // Also invalidates any transcript fetch still in flight, which would
    // otherwise draw the departing reader's conversation into an empty page.
    transcriptEpoch += 1;
    // And any sidebar fetch with it. The list carries the departing reader's
    // own opening questions; landing after a sign-out would paint them into the
    // column the next person sees.
    selectionEpoch += 1;

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
    UI.History.clear();
    AppState.set('sidebarOwner', null);
    AppState.set('sidebarTabSettled', false);
    this.stopNotificationsPolling();
    AppState.set('notificationsUserId', null);
    UI.Notifications.setUnreadCount(0);
    AppState.set('notificationsActive', []);
    AppState.set('notificationsHistoryItems', []);
    AppState.set('notificationsOpenModalId', null);
    try {
      sessionStorage.removeItem('sfda-transcript');
    } catch (error) {
      logError(error, 'clearSessionState: sessionStorage');
    }
  },

  clearLocalAuthData() {
    ['sb-access-token', 'sb-refresh-token', 'sb-user', 'sb-session', 'sfda-supabase-auth'].forEach(
      (key) => {
        try {
          localStorage.removeItem(key);
        } catch (error) {
          logError(error, `clearLocalAuthData: ${key}`);
        }
      },
    );

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
