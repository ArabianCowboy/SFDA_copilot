/**
 * SFDA Copilot — Application entry point
 *
 * AI-powered regulatory guidance for pharmaceutical regulations.
 * This file wires the ES modules together; logic lives under ./modules/.
 */

import { CONFIG } from './modules/config.js';
import { DOMCache, ErrorHandler, logError } from './modules/dom.js';
import { AppState } from './modules/state.js';
import { AuthView } from './modules/auth-view.js';
import { ThemeManager } from './modules/theme.js';
import { UI } from './modules/ui.js';
import { Effects } from './modules/effects.js';
import { Services, isRecoveryCallback } from './modules/services.js';
import { Handlers } from './modules/handlers.js';
import { CustomDropdown } from './modules/dropdown.js';
import { mountRobots, initLandingRobot, RobotCompanion } from './modules/robot.js';
import { initCitationInteractions } from './modules/citations.js';
import { I18n, Transcript, initLanguageToggle } from './modules/i18n.js';
import { Route } from './modules/route.js';

const App = {
  /* Which reader the transcript on screen belongs to, and whether the
     question has been asked at all. Keyed to the identity rather than to a
     bare boolean; see settleTranscript for why that distinction is
     load-bearing rather than tidy. */
  _transcriptSettled: false,
  _settledFor: null,

  async loadProfileWithTimeout(
    userId,
    timeoutMs = CONFIG.API_TIMEOUT,
    retries = CONFIG.RETRY_MAX_ATTEMPTS,
  ) {
    let delay = CONFIG.RETRY_DELAY_INITIAL;

    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        const timeoutPromise = new Promise((_, reject) => {
          setTimeout(() => reject(new Error('Profile load timeout')), timeoutMs);
        });
        return await Promise.race([Services.getProfile(userId), timeoutPromise]);
      } catch (error) {
        logError(error, `loadProfileWithTimeout attempt ${attempt}/${retries}`);
        if (attempt < retries) {
          await new Promise((resolve) => setTimeout(resolve, delay));
          delay *= 2;
        } else {
          throw error;
        }
      }
    }
    return null;
  },

  /**
   * `Services.getIdentity()`, retried on a genuine, transient fault only.
   *
   * `getIdentity()` already resolves — never throws — for "nobody" (401, no
   * session or an invalid one). "Not allowed" (403, a disabled account) now
   * throws instead, carrying `.status = 403`, but is equally not worth
   * retrying: it is a real answer, not a fault, and hammering a refusal would
   * only delay the disabled-notice ever settling. Only a network failure (no
   * `.status` — the fetch itself never got a response, which now includes the
   * client-side timeout `getIdentity` enforces) or a 5xx/503 from an
   * identity-provider outage — the exact shape `_authenticate_request`
   * classifies server-side — is worth a second attempt, because that is the
   * case the server is explicitly built to recover from: `resolve_identity_flags`
   * deliberately never caches a failed lookup, precisely so the next request
   * gets a clean try. Any other status (400, 403, 404, 429, ...) is retried
   * zero times — repeating the same request would only repeat the same answer.
   */
  async fetchIdentityWithRetry(attempts = 2, delayMs = 500) {
    for (let attempt = 1; attempt <= attempts; attempt++) {
      try {
        return await Services.getIdentity();
      } catch (error) {
        const retryable = error.status === undefined || error.status >= 500;
        if (!retryable || attempt >= attempts) throw error;
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
    }
    return null;
  },

  /**
   * Decide, once, where this reader's transcript comes from.
   *
   * Deliberately NOT done during init(). Drawing a conversation before
   * authentication resolves means drawing it for nobody in particular: if
   * startup then found no valid session, the previous reader's turns sat in the
   * DOM behind the landing view — hidden, not removed, because AuthView only
   * toggles `d-none` and the app lives at "/" so nothing reloads — and the next
   * person to sign in had them revealed.
   *
   * So the transcript waits for an answer to "who is here?", and is either
   * hydrated for the reader it belongs to or left empty.
   *
   * WHAT CHANGED IN STEP 6. This used to re-inject rendered markup saved into
   * per-tab `sessionStorage` by the language toggle, which had three
   * consequences worth remembering now they are gone: an ordinary refresh lost
   * the conversation entirely (nothing but `I18n.set` ever saved), a restored
   * answer's citations had to be stripped because only the markup came back,
   * and a second device showed nothing at all. The turns now come from the same
   * durable rows the model's prompt window is built from, so screen and model
   * agree by construction — which was the precondition the resume flag was
   * waiting on.
   */
  settleTranscript(user) {
    const identity = user?.id || user?.email || null;

    /* KEYED TO THE READER, NOT TO THE PAGE, and this is not a refinement.

       The sequence: reader A signs out and reader B signs in on the same tab,
       or identity switches under a live page. AuthView only toggles `d-none`, so
       nothing reloads and a plain once-per-page guard would already be spent —
       B's transcript would never be (re)drawn. Both exits (the SIGNED_OUT
       listener and the reader-switch branch below) now reset the URL with
       Route.replace(null) before hydrateTranscript runs, so B does not request
       A's conversation. This per-identity guard is what makes hydrateTranscript
       run again for B at all; the server's ownership 404 remains the backstop
       if a stale route ever did reach it.

       Settling more than once is safe because settling is now idempotent per
       identity: the same reader short-circuits, a different one re-hydrates. */
    if (this._transcriptSettled && identity === this._settledFor) return;

    const previous = this._settledFor;
    this._transcriptSettled = true;
    this._settledFor = identity;

    if (!identity) {
      // Clears any `sfda-transcript` entry left in this tab by a build that
      // predates hydration. Nothing writes that key any more; this is the
      // sweep, not a mechanism.
      Transcript.discard();
      // The disclosure is about a signed-in account. Leaving it over the
      // landing view would be addressing nobody, and would still be on screen
      // for whoever signs in next.
      UI.hideHistoryNotice();
      UI.hideProfileCompletionNotice();
      /* And the sidebar with it. These rows are one reader's own opening
         questions; the app lives at "/" and nothing reloads on the way out, so
         leaving them drawn behind the landing view is the same hazard the
         transcript is cleared here to avoid. */
      AppState.set('sidebarOwner', null);
      AppState.set('sidebarTabSettled', false);
      UI.History.clear();
      return;
    }

    /* A reader changed under a live page without a SIGNED_OUT in between; the
       full local teardown runs, and the URL moves off the previous reader's
       /c/<id> so the new reader does not request a conversation they do not
       own (which would only 404 and bounce). Reset at the call site, like the
       SIGNED_OUT branch, never inside the shared teardown. */
    if (previous && previous !== identity) {
      Handlers.clearReaderScopedUI();
      if (Route.current()) Route.replace(null);
    }

    Transcript.discard();

    /* Before hydration, not after, and not inside it. The disclosure is true of
       the account rather than of any particular conversation, so it must not
       wait on a network read that may be slow, may 503, or may correctly return
       nothing — a reader with no stored history yet is precisely someone who has
       not been told their next question will be kept. */
    UI.showHistoryNotice(identity);

    this.hydrateTranscript(identity);

    /* The sidebar loads alongside the transcript, not after it. They are two
       reads of the same history — the conversation and the index of it — and
       sequencing them would make the column sit empty for the length of a
       transcript fetch it does not depend on.

       `sidebarOwner` is set BEFORE the dispatch and checked when it lands, the
       same identity guard `hydrateTranscript` applies: a sign-out and a second
       sign-in can both happen while a list is in flight, and painting reader
       A's conversation titles into reader B's column is an account leak. */
    AppState.set('sidebarOwner', identity);
    AppState.set('sidebarTabSettled', false);
    Handlers.loadSessions(identity).catch((error) =>
      logError(error, 'settleTranscript.loadSessions'),
    );

    // Notification Center (docs/notification-center-plan.md). Started here
    // rather than from the auth-state listener directly: `settleTranscript`
    // is the one place "a reader is now signed in" is already decided,
    // including the testing-mode bypass (handleTestingModeInit calls this
    // too) and the recovery-mode exclusion (settled to null there, so this
    // branch never runs mid-recovery). `user?.id` is the real Supabase auth
    // id for a genuine session; the testing bypass's `{email}`-only object
    // has none, which correctly skips the Realtime leg (see
    // startNotificationsPolling's own comment) while REST polling still
    // runs either way.
    if (!document.hidden) Handlers.startNotificationsPolling(user?.id || null);
  },

  /**
   * Fetch and draw the conversation the URL names, for a signed-in reader.
   *
   * §4.5: THIS IS THE DEEP-LINK-ACROSS-AUTH-BOUNDARY HANDLING, not a
   * separate mechanism. A signed-out reader who opened `/c/<id>` keeps that
   * path — `/c/<id>` is not `@auth_required` server-side, so nothing
   * redirected them off it — and `settleTranscript` already waits for "who
   * is here?" before drawing anything. Once identity resolves, hydrating
   * from `Route.current()` at that moment is what makes the deep link work
   * for a reader who signs in after following one.
   *
   * §4.2's page-load table, read off `Route`: absent → `/` is always a new
   * chat (Decision 1a) — nothing is fetched, full stop. Present but not
   * `Route.isCommitted()` → this tab minted the id and the turn never
   * landed before whatever brought this reader back (a reload, most often)
   * — not a real conversation yet, so not fetched either; bounced to `/`.
   * Present and committed → fetched, exactly as every reload always has.
   *
   * Not awaited by its caller: a slow history read must not hold up the rest
   * of sign-in, exactly as the identity check is not held up by the profile
   * load.
   *
   * A failure is TOLD, not swallowed. An empty transcript is a claim — that
   * the reader has nothing stored — and making it while the store is
   * unreachable is the kind of quiet untruth this product refuses
   * everywhere else. The server answers 503 `history_unavailable` for that
   * case specifically, so the two are distinguishable here rather than
   * collapsed into "no messages". A 404 is a THIRD thing, distinct from
   * both: not an outage and not "nothing yet" but "not yours, or not
   * there" — the other half of §4.5, reached via the same shared path
   * `Handlers.openSession`'s failure does.
   */
  async hydrateTranscript(identity) {
    /* Stamped before the fetch, checked after it. The request is not awaited by
       its caller, so the transcript can be deliberately emptied while it is in
       flight — and a stored conversation reappearing after the reader pressed
       New chat is the resurrection this whole feature is built to prevent,
       arriving through the one door the server-side rule cannot close.

       Identity alone does not catch it: the same reader is the one pressing the
       button. `Handlers.beginTranscriptEpoch()` is bumped by every act that
       means "what is on screen is no longer the conversation I asked about" —
       New chat, a sidebar switch, a delete, or a sign-out. */
    const epoch = Handlers.transcriptEpoch();
    const id = Route.current();

    if (!id) return; // "/" — always a new chat. Nothing to hydrate.

    if (!Route.isCommitted()) {
      Route.replace(null);
      return;
    }

    try {
      const history = await Services.getChatHistory(id);

      /* Discarded if this is no longer the reader who asked. A sign-out and a
         second sign-in can both land while the fetch is in flight, and drawing
         A's conversation into B's session is an account leak, not a cosmetic
         race. The same shape `getIdentity` already uses, and for the same
         reason: check who the answer was for before acting on it. */
      if (identity !== this._settledFor) return;
      if (epoch !== Handlers.transcriptEpoch()) return;

      UI.hydrateTranscript(history.messages || []);
      Route.commit();
    } catch (error) {
      if (identity !== this._settledFor) return;
      if (epoch !== Handlers.transcriptEpoch()) return;
      logError(error, 'hydrateTranscript');
      if (error?.code === 'not_found') {
        // Someone else's deep link, or one that no longer resolves —
        // §4.5's second half. The shared path, not a bespoke one here.
        Handlers._conversationUnreachable(null);
      } else {
        ErrorHandler.showToast(I18n.t('chat.historyUnavailable'), true);
      }
    }
  },

  /**
   * Runs on a bfcache restore (docs/ARCHITECTURE.md, "When a session ends in the browser").
   * Same reader still in storage → reveal the restored page as it was. Anyone else, or
   * nobody → a fresh load of "/" (the ordinary, tested init path) rather than tearing the
   * restored page down in place and re-deriving auth. getSession error → reload this URL:
   * unknown is not absent. Never synthesizes an auth event.
   */
  async reconcileRestoredSession() {
    const reveal = () => {
      document.body.hidden = false;
    };
    const shownFor = this._settledFor;
    if (
      !shownFor ||
      AppState.get('recoveryMode') ||
      !Services.supabase ||
      window.location.search.includes('testing=true')
    ) {
      reveal();
      return;
    }
    document.body.hidden = true; // idempotent with pagehide; covers a restore pagehide did not conceal
    let session;
    try {
      const { data, error } = await Services.supabase.auth.getSession();
      if (error) throw error;
      session = data?.session ?? null;
    } catch (error) {
      logError(error, 'reconcileRestoredSession');
      window.location.reload();
      return;
    }
    const user = session?.user ?? null;
    if (user && (user.id || user.email) === shownFor) {
      reveal();
      return;
    }
    window.location.replace(Route.homeHref());
  },

  async handleTestingModeInit() {
    console.log('[App] Testing mode enabled - bypassing authentication.');
    AuthView.render({ email: 'test@example.com' });
    this.settleTranscript({ email: 'test@example.com' });

    try {
      UI.Faq.renderButtons(await Services.getFaqData());
    } catch (error) {
      logError(error, 'handleTestingModeInit.getFaqData');
      UI.Faq.clearButtons();
      ErrorHandler.showToast(I18n.t('faq.loadFailedTesting'), true);
    }
  },

  async init() {
    window.APP_INITIALIZED = true;
    console.log('[App] Initializing SFDA Copilot...');

    Handlers.bindEvents();
    // §4.1/§4.3: Back/Forward and bfcache restores. Wired unconditionally,
    // like everything else in this block — a signed-out reader on `/c/<id>`
    // can still navigate, and the popstate handler itself is what decides
    // whether there is anything to hydrate.
    Route.init((navigation) => Handlers.handlePopState(navigation));
    /* bfcache restore (docs/ARCHITECTURE.md, "When a session ends in the browser"). A restored
       page runs no init(), and supabase-js emits no SIGNED_OUT for storage it
       finds empty, so a page frozen while reader A was signed in comes back
       showing A after A's session ended elsewhere. The snapshot is concealed on
       the way OUT (pagehide) because there is no portable guarantee a pageshow
       handler runs before the restored page is painted. Concealing the WHOLE
       body rather than only #authenticated-view ensures Notification Center
       surfaces, modals, and toasts that live outside the view are also hidden.
       Route.init's own pageshow handler (handlePopState) still runs first and
       re-derives the transcript — this handler only decides whose page it is.
       Wired here, before any testing/recovery early returns below, so every
       restored page is reconciled (reconcileRestoredSession itself skips the
       modes it must not touch, and always un-hides on those paths). */
    window.addEventListener('pagehide', (event) => {
      if (event.persisted && this._settledFor) document.body.hidden = true;
    });
    window.addEventListener('pageshow', (event) => {
      if (event.persisted) this.reconcileRestoredSession();
    });
    ThemeManager.init();
    UI.hydrateTimestamps();
    initCitationInteractions(DOMCache.get(CONFIG.SELECTORS.MESSAGES));
    UI.initJumpToLatest();
    initLanguageToggle();

    /* Mount the mascot and the card reveal. These run regardless of whether
       auth services are configured below. */
    mountRobots();
    Effects.initCardAnimations();
    initLandingRobot();
    RobotCompanion.init();
    CustomDropdown.init();

    if (!window.SUPABASE_URL || !window.SUPABASE_ANON_KEY) {
      logError('Supabase configuration missing.', 'App.init');
      return ErrorHandler.showToast(I18n.t('auth.servicesUnavailable'), true);
    }

    try {
      Services.init();

      const authModalEl = DOMCache.get(CONFIG.SELECTORS.AUTH_MODAL);
      if (authModalEl && window.bootstrap?.Modal) {
        AppState.set('authModal', window.bootstrap.Modal.getOrCreateInstance(authModalEl));
      }

      const sendBtn = DOMCache.get(CONFIG.SELECTORS.SEND_BTN);
      if (sendBtn) {
        AppState.set('originalSendButtonText', sendBtn.textContent?.trim() || I18n.t('chat.send'));
      }
    } catch (error) {
      logError(error, 'App.init services');
      return ErrorHandler.showToast(I18n.t('auth.initFailed'), true);
    }

    /* Recovery is decided before the testing bypass, and deliberately does not
       return: the demo path must be able to show this view, and the bypass at
       `handleTestingModeInit` would otherwise render a signed-in chat over it. */
    const recovering = isRecoveryCallback();
    if (recovering) {
      AppState.set('recoveryMode', true);
      AuthView.renderRecovery();
      /* Nobody in particular yet. Settling to null takes the discard branch, so
         the previous reader of this browser does not get their transcript
         restored to whoever followed a link from an inbox. */
      this.settleTranscript(null);
    } else if (window.location.search.includes('testing=true')) {
      return this.handleTestingModeInit();
    }

    if (!Services.supabase) {
      if (!recovering) AuthView.render(null);
      return;
    }

    /* Subscribed BEFORE the first await, not after it.
       This used to sit below `getSession()`. Anything Supabase emitted while
       that promise was in flight — including the PASSWORD_RECOVERY this flow
       depends on, which `_initialize` fires from a setTimeout during
       `Services.init()` — landed before there was a listener and was lost. The
       marker above is what makes recovery work regardless; this ordering is what
       makes the event a real second path rather than a decorative one. */
    Services.supabase.auth.onAuthStateChange(async (event, session) => {
      const user = session?.user ?? null;

      if (event === 'PASSWORD_RECOVERY') {
        AppState.set('recoveryMode', true);
        AuthView.renderRecovery();
        Handlers.setRecoveryReady(!!user);
        return;
      }

      /* While recovering, no auth event may draw a signed-in shell. Supabase
         emits SIGNED_IN first (supabase/auth-js#349) and a recovery session
         carries a user, so this is the event that would otherwise open the chat.
         SIGNED_OUT is the one that means the flow is over. */
      if (AppState.get('recoveryMode')) {
        if (event === 'SIGNED_OUT') {
          AppState.set('recoveryMode', false);
          AuthView.leaveRecovery(null);
          Handlers.clearSessionState();
        }
        return;
      }

      AuthView.render(user);
      /* No-op after startup has already settled it. Present so a session that
         resolves through this path rather than getSession() — a sign-in on a
         tab that opened signed out — still gets an ownership decision. */
      this.settleTranscript(user);

      if (user) {
        // Independent of everything else in this block — not awaited, so a
        // slow FAQ response no longer holds up the identity check below it.
        Services.getFaqData()
          .then((faqData) => UI.Faq.renderButtons(faqData))
          .catch((error) => {
            logError(error, 'onAuthStateChange.getFaqData');
            UI.Faq.clearButtons();
            ErrorHandler.showToast(I18n.t('faq.loadFailed'), true);
          });

        /* Captured once, before either fire-and-forget call below, and
           reused by both: a reader who signs out (or enters recovery) while
           either is still in flight leaves auth-view.js having bumped
           identityCheckId, so a late answer for the account that just left
           is recognised as stale rather than applied to whoever replaced
           them. Previously only the identity check had this guard — see
           TODO.md's "A late profile read has no identity guard" entry,
           which this closes. */
        const checkId = AppState.get('identityCheckId') || 0;
        const dispatchedForUserId = user.id;

        this.loadProfileWithTimeout(user.id)
          .then((profileData) => {
            if ((AppState.get('identityCheckId') || 0) !== checkId) return;
            if (!profileData) return;
            AppState.set('userProfile', profileData);
            // Only from this success branch, never from .catch and never
            // for a stale identity — "don't flash before load" is structural
            // here, not a guard bolted on afterward.
            if (!profileData.first_name) {
              UI.queueProfileCompletionNotice(dispatchedForUserId);
            }
          })
          .catch((err) => logError(err, 'loadProfileWithTimeout'));

        /* Ask the server whether this reader is an administrator, and reveal
           the console link from the answer rather than from anything the page
           already held. Fire-and-forget: the link is an affordance, and a
           reader who never learns about it has lost nothing, while a failed
           check must not delay or break the chat. Defaults to hidden.

           `checkId` is captured now, before either await below, and compared
           after: `auth-view.js` bumps `identityCheckId` on sign-out and on
           entering recovery, so a check dispatched for this reader that only
           resolves after they have left this view is recognised as stale and
           discarded rather than applied to whatever view replaced it.

           `Services.getIdentity()` dedupes concurrent calls into one shared
           promise (see its own comment), and that promise is not scoped to
           who asked. On a shared machine, if reader A signs out and reader B
           signs in on the same tab before A's still-pending check resolves,
           B's call joins A's promise and would otherwise receive A's answer.
           `identity.user_id` is checked against the user this dispatch was
           actually for so a borrowed answer for someone else's account is
           discarded rather than applied — this fails to "unresolved, stay
           hidden" for B rather than showing them A's standing, which matches
           how this app already treats every other unresolved case.
           `checkId`/`dispatchedForUserId` are the ones captured above, ahead
           of both this and the profile load. */
        this.fetchIdentityWithRetry()
          .then((identity) => {
            if ((AppState.get('identityCheckId') || 0) !== checkId) return;
            if (identity && identity.user_id !== dispatchedForUserId) {
              logError(
                `getIdentity answered for ${identity.user_id}, expected ${dispatchedForUserId}`,
                'getIdentity.identityMismatch',
              );
              return;
            }
            /* Skip re-rendering when the identity could not be resolved: during
               an outage is_admin falls back to false because the lookup failed,
               so painting that non-answer would actively hide a real administrator's
               console link. Declining to hide never grants privilege: it only
               avoids hiding a link already shown, and web/api/admin.py:101-105
               still rejects an unresolved identity with 503.
               `!== false` rather than truthiness: an older cached payload omitting
               is_resolved is treated as resolved. */
            if (identity?.is_resolved !== false) {
              AuthView.renderAdminAffordance(!!identity?.is_admin);
            }
            /* Seeds the counter at sign-in, guarded by the same checkId and
               user_id checks that guard the admin affordance above — a stale
               answer must not paint another reader's allowance. Every later
               update rides a `done` frame; identity is never re-fetched to
               refresh a number. */
            UI.updateQuotaCounter(identity?.quota ?? null);
          })
          .catch((err) => {
            if ((AppState.get('identityCheckId') || 0) !== checkId) return;
            AuthView.renderAdminAffordance(false);
            /* A disabled account is not a fault — see getIdentity's own
               comment. Surface the early notice instead of logging it as an
               error, so a disabled reader learns their standing before they
               type a question rather than only after (handlers.js already
               shows the same string on a 403 chat response; this is the
               earlier half of the same fix). Every other rejection here is
               a genuine fault and keeps the existing log-and-hide-link path. */
            if (err?.code === 'account_disabled') {
              UI.showAccountDisabledNotice();
              return;
            }
            logError(err, 'getIdentity');
          });
      } else {
        AppState.set('userProfile', null);
        /* Only on an actual sign-out — revoked, expired, or the logout button
           — never on the INITIAL_SESSION event this fires on subscribe. That
           event reports "no session yet" during startup, and clearing on it
           would wipe the transcript hydration had just drawn
           after a language switch. INITIAL_SESSION falls through to `else`, so
           a signed-out cold deep link keeps its path (§4.5).

           Without the cleanup here a session that ends anywhere other than the
           logout button leaves the previous reader's transcript, source panel
           and citation state live behind the landing view, because the tab is
           never reloaded on the way out.

           This exit also moves the address bar off /c/<id>, because a session
           that ends at /c/<uuid> would otherwise leave the previous reader's
           conversation id in the URL and in the history entry. Route.replace,
           not location.replace('/'): no reload (a reload would cancel the
           unawaited POST /auth/logout that clearSessionState fires, would drop
           nothing the teardown has not already dropped, and would reload every
           open tab on a broadcast sign-out), and it keeps ?lang=/?testing=.
           Guarded by Route.current() so "/" and its query string are left alone.
           The reset lives HERE, not inside clearSessionState, because
           endRecovery and the recovery branch above also call clearSessionState
           and must keep the recovery form's path — the recovery branch returns
           before reaching this line. */
        if (event === 'SIGNED_OUT' || event === 'USER_DELETED') {
          Handlers.clearSessionState();
          if (Route.current()) Route.replace(null);
        } else {
          UI.Faq.clearButtons();
        }
      }
    });

    if (recovering) {
      /* The demo has no Supabase project behind it, so there is no session to
         find and the expired notice would be the only thing it could ever show.
         PRODUCT.md treats the demo as a shipping surface: `?testing=true&recovery=1`
         renders the real form, and `Services.updatePassword` short-circuits to
         success the same way `getSessionToken` and `logout` already do. */
      if (window.location.search.includes('testing=true')) {
        Handlers.setRecoveryReady(true);
        console.log('[App] Recovery view shown in testing mode.');
        return;
      }

      /* Whether the link actually produced a session. A marker with no session
         means expired, already used, or forged — and the form must say so rather
         than accept a password it can never save. */
      try {
        const {
          data: { session },
        } = await Services.supabase.auth.getSession();
        Handlers.setRecoveryReady(!!session?.user);
      } catch (error) {
        logError(error, 'App.init.recoverySessionCheck');
        Handlers.setRecoveryReady(false);
      }
      console.log('[App] SFDA Copilot initialized in recovery mode.');
      return;
    }

    try {
      const {
        data: { session: initialSession },
        error: sessionError,
      } = await Services.supabase.auth.getSession();

      if (sessionError) {
        logError(sessionError, 'App.init.initialSessionCheck');
        AuthView.render(null);
        this.settleTranscript(null);
      } else if (initialSession?.user) {
        AuthView.render(initialSession.user);
        this.settleTranscript(initialSession.user);
      } else {
        AuthView.render(null);
        this.settleTranscript(null);
        /* §4b: A fresh load reached by Back/Forward into /c/<id> with nobody
           signed in is reader A's history entry being revisited, not a deep link
           someone opened — so the id comes out of the address bar (§4b). A cold
           deep link (`navigate`) and a reload keep their path, so §4.5's
           deep-link-across-sign-in is untouched. Navigation Timing's `type`
           describes this document's own load and never changes afterwards, which
           is why this check belongs here, run once, and nowhere reusable. */
        if (
          Route.current() &&
          performance.getEntriesByType('navigation')[0]?.type === 'back_forward'
        ) {
          Route.replace(null);
        }
      }
    } catch (error) {
      logError(error, 'App.init.checkInitialSession');
      AuthView.render(null);
      this.settleTranscript(null);
    }

    console.log('[App] SFDA Copilot initialized successfully.');
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
