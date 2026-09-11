# Fix: an ended session leaves reader A's traces for reader B

STATUS: APPROVED PLAN — IN PROGRESS. Written and approved 2026-09-11; commits 1 and 2 of 4
(§1-§6, §9) shipped 2026-09-11 — see _Implementation notes_ for where the build departed from
this text.
Closes the TODO.md entry _A revoked or expired session clears the transcript but leaves the
conversation id in the address bar_ once all four commits below land; archive this file then
(see _Docs_).

_Plan, 2026-09-11. Reviewed by three independent models: OpenCode · Muse Spark 1.3 xhigh (gap
debate), agy · Gemini 3.8 Flash High (security), and Codex · gpt-6-astra medium (debate and
final review). bfcache behaviour was verified by a Chromium 151 probe. Every accepted finding
was re-checked against the code by the orchestrator (see the review record)._

## Context

The starting point is TODO.md → _A revoked or expired session clears the transcript but leaves
the conversation id in the address bar_ (`TODO.md:312`, index `:66`).

- **The logout button** (`handleLogout`, `static/js/modules/handlers.js:2101`) calls
  `redirectToHomeIfNeeded()`.
- **Every other ending** arrives as `SIGNED_OUT`/`USER_DELETED` at `static/js/app.js:514` and
  calls only `Handlers.clearSessionState()`.

So a reader whose session dies at `/c/<uuid>` leaves that id in the address bar. On a shared
machine it's a durable pointer to someone else's conversation. Access control holds: the
server's ownership preflight answers 404 for another reader's id (`session_exists(owner_id,
id)`), so this is exposure of an identifier and a confusing first screen.

The reviews and the probe found more of the same class: reader A's residue reaching reader B.
The user asked for no loose ends, so this plan covers all of it:

- **Teardown gaps:** the composer draft, the quota notice, notification toasts, banners, the
  modal and inbox, and snoozes. These already leak today at `/` and on every revocation. The
  URL fix removes the `/c/<id>` logout reload that used to mask them.
- **Back navigation:** Back into A's earlier `/c/<id>` entries, both same-document and
  cross-document.
- **bfcache:** a restore shows A's signed-in chat or account page after the session ended
  (verified in the probe).
- **`/account` and `/admin`:** neither page ever reacts to a session ending.
- **Races:** a late chat request or inbox response for A lands after the sign-out.
- **Reader switch:** a direct A→B switch runs a weaker teardown than a sign-out.

**User decisions (2026-09-11):**

1. No page reload on logout; make the teardown complete instead.
2. Scrub `/c/<id>` when a signed-out reader traverses Back.
3. Fix the bfcache restore too, after verifying it's real (verified).

**Must keep working:** password recovery (the §4.6 deep-link preservation), a cold signed-out
deep link (§4.5), the `?testing=true` demo, and the `?lang=` param.

## Changes

### 1. URL reset at the `SIGNED_OUT` call site — `app.js:514`

```js
if (event === 'SIGNED_OUT' || event === 'USER_DELETED') {
  Handlers.clearSessionState();
  if (Route.current()) Route.replace(null);
}
```

- **Which helper:** `Route.replace` (`route.js:107`) is the documented non-deliberate reset.
  `Route` is already imported (`app.js:21`).
- **Why not `location.replace('/')`:**
  - It doesn't reload, so it doesn't cancel the unawaited `/auth/logout` POST that
    `clearSessionState` fires. That POST does `session.clear()`, purges the legacy
    `chat_history`, and evicts the token from the verification cache _when the request carries
    one_ (`auth.py:429-441`).
  - It keeps `?lang=`/`?testing=` (`CARRIED_PARAMS`).
  - It doesn't reload every tab on a broadcast sign-out.
- **The `Route.current()` guard** leaves `/` and its query string alone.
- **The next sign-in** then hydrates nothing (`app.js:246-248`), so there's no 404 bounce.
- **Recovery is excluded by structure:** the recovery branch returns first (`app.js:383-390`).
  This is why the reset can't live inside `clearSessionState`, which `endRecovery` also calls.
- **`INITIAL_SESSION`** falls through to `else`, so §4.5 is untouched.
- **Logout-button ordering (verified):** `signOut` awaits all subscribers
  (`GoTrueClient.js` ~1493-1520, 1981-1990). The listener has therefore already moved the URL
  when `handleLogout` reaches `redirectToHomeIfNeeded()`, which becomes a no-op on success.
  - Keep that call as the fallback for the paths where no `SIGNED_OUT` arrives: testing mode,
    `signOut` throwing, and `sessionMissing: true` (`services.js:511`). Those paths still
    reload; say so where the no-reload design is described.

### 2. One complete local teardown, shared by sign-out and reader switch — `handlers.js`

Today there are two diverging teardowns:

- `clearSessionState` (sign-out, `:2141`).
- `clearReaderScopedUI` (a direct A→B switch, `:1128`, called from `app.js:161`). It skips
  stream cancellation, the composer and notifications, and it doesn't invalidate A's in-flight
  identity and profile callbacks. `AuthView.render(user)` bumps `identityCheckId` only for a
  null user (`auth-view.js:195`), so A's profile can land for B via `app.js:422`.

Refactor:

- **`clearReaderLocalState()`** (new) holds everything `clearSessionState` does today _except_
  `Services.endServerSession()`, plus the additions below.
- **`clearSessionState()`** = `clearReaderLocalState()` + `Services.endServerSession()`. Its
  callers don't change.
- **`clearReaderScopedUI()`** = `clearReaderLocalState()`. It doesn't POST `/auth/logout`,
  because on a switch the Flask session now belongs to B.
- **Additions inside `clearReaderLocalState()`** (each verified):

| Add                                                                                                                                                                                                              | Why                                                                                                                                                      |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Composer: `#query-input` gets `value = ''`, then `UI.autoResizeInput?.(composer)` (as at `:461-464`)                                                                                                             | The composer is only hidden with `#authenticated-view`, so A's draft reappears for B.                                                                    |
| `UI.hideQuotaNotice(); UI.updateQuotaCounter(null); UI.hideProfileCompletionNotice();`                                                                                                                           | The notice is `data-non-turn`, so `clearTranscript` skips it. After a sign-out, B's settle sees `previous === null` and never ran `clearReaderScopedUI`. |
| `BroadcastNotice.reset()` (new, in `dom.js`; see §9)                                                                                                                                                             | Toasts, the banner and the modal render outside the authenticated view, so they survive onto the landing view.                                           |
| Hide the inbox modal transition-safely (`this.hideModal('notificationsInboxModal', …)`, `:2209`), `UI.Notifications.renderInboxList([])`, and reset `notificationsHistoryCursor`/`notificationsHistoryExhausted` | Only `notificationsHistoryItems` is reset today (`:2175`). Plain `.hide()` is ignored mid-fade (`:2216`).                                                |
| `activeStreamConversationId = null;`                                                                                                                                                                             | Stops a dead stream's re-attach early return (`:827-830`).                                                                                               |
| Bump `identityCheckId` (`AppState`, the same shape as `auth-view.js:175`)                                                                                                                                        | A's in-flight profile and identity callbacks (`app.js:417-501`) are then discarded on a switch, not only on sign-out.                                    |

- **Reader-switch branch of `settleTranscript`** (`app.js:161`): after `clearReaderScopedUI()`,
  add `if (Route.current()) Route.replace(null);` before `hydrateTranscript`. B then doesn't
  request A's conversation and bounce off a 404. The URL reset stays at call sites, never in the
  shared teardown.
- **Accepted trade-off:** a reader whose session expires mid-typing loses the draft.

### 3. No URL write for A after the teardown — `handlers.js`

- **Late chat request** (Codex C1). `processChatRequestInternal` awaits the token (`:367`) and
  then calls `Route.enter()` (`:402`) with no check that a sign-out happened meanwhile.
  `streamChat` captures `generation` only later (`:1508`).
  - Capture `const startGeneration = resetGeneration;` at entry.
  - After the token await, `if (startGeneration !== resetGeneration) return;` before minting or
    entering a route.
  - In the `catch`, skip the error UI (bubble, toast, quota restore) when the generation moved.
  - The existing `finally` still restores the send state.
- **Stream `meta`** (`:1540`): add `if (generation !== resetGeneration) return;`. Reviewers split
  on whether this is reachable. Adopted as an invariant: nothing writes `/c/<id>` after a
  teardown. This matches the blocking twin (`:1768`).

### 4. Signed-out Back guard — `handlePopState` (`handlers.js:814`)

Insert after the `if (!id)` branch and before `!Route.isCommitted()`:

```js
let token;
try {
  token = await Services.getSessionToken();
} catch (error) {
  logError(error, 'handlePopState.session');
  token = undefined;
}
if (epoch !== transcriptEpoch) return;
if (token === null) {
  // confirmed absence only — an error is not absence (Codex C4)
  Route.replace(null);
  UI.clearTranscript();
  SourcePanel.reset();
  resetCitationState();
  UI.History.setActive(null);
  return;
}
// token string, or undefined after an error → existing path, unchanged
```

- **When `getSessionToken` returns null:** only when there's no session. Refresh and lock
  contention wait rather than return null (`GoTrueClient.js:1015,1159`). A refresh error throws
  (`services.js:370`) and must not scrub a signed-in reader.
- **Testing mode:** it returns `'fake_token'`, so the demo is unaffected.
- **Cost:** a signed-out reader who Backs into a deep link they opened loses it. A cold-opened
  deep link doesn't go through `popstate` (§4.5 intact).
- **Comment it:** add a comment tying this to the §4.5 trade-off.

**4b. Cross-document Back** (probe: an evicted or non-bfcache Back loads `/c/<id>` fresh and
keeps it).

- **Placement:** only in `init`'s successful no-session branch (`app.js:563`), which runs once.
- **Guard:**
  `if (Route.current() && performance.getEntriesByType('navigation')[0]?.type === 'back_forward') Route.replace(null);`
- **Scope:** `navigate` and `reload` keep the path. Navigation Timing's `type` describes the
  document's own load, so leave it in `init` and don't move it into reusable handlers.

### 5. Write the reasons down, and correct the stale comments

- **`app.js:504-513`:** why this exit rewrites the URL, why `Route.replace` and not a reload, and
  why the reset isn't in the teardown (recovery).
- **Teardown docstrings (`handlers.js:1116-1127`, `:2124-2140`):** rewrite them to describe the
  new split.
  - The URL is the caller's job. Name the three callers that reset it (the `SIGNED_OUT` branch,
    the reader-switch branch, `reconcileRestoredSession`) and the one that deliberately
    doesn't (`endRecovery`).
  - Neither exit reloads, except the no-event fallback.
  - Delete the false claims: "the app lives at '/'…" and "purges … conv_id / prev_conv_id".
- **`handlers.js:2154-2159`:** remove "the Flask cookie still holds conv_id". Since per-tab deep
  linking the cookie carries none (`auth.py:75-92`, `test_deep_link_contract.py:128-134`).
- **`auth.py:47-49`:** correct the same stale conversation-pointer explanation.
- **`handleLogout`:** mark the `redirectToHomeIfNeeded()` calls as the no-event fallback.

### 6. `ASSET_VERSION` (`web/api/app.py:306`)

Bump it in **every** commit, since each commit touches JS.

### 7. bfcache restore of the chat page — conceal on leave, fresh-read on mismatch

**Verified real** (probe, Chromium 151, bfcache on).

- **Setup:** reader A is signed in at `/c/<id>`, leaves in the same tab, and the session is
  then removed without a broadcast reaching the page.
- **Result on Back:** the page restores (`persisted: true`) showing "Logged in as:
  reader-a@…", A's 8 sidebar rows and `/c/<id>`, and stays that way.
- **Why nothing fires:** `_recoverAndRefresh` returns silently on empty storage
  (`GoTrueClient.js:1815-1820`), so no `SIGNED_OUT` ever comes.
- **In Chrome**, a broadcast sign-out evicts the page (`BroadcastChannelOnMessage`), leaving
  only §4b. That isn't guaranteed elsewhere.

The design **doesn't synthesize auth events**. Codex showed that route double-tears down,
misses `getSession` errors, and races `getSession`'s own `SIGNED_OUT`. Any doubt instead
becomes a fresh load, which is the app's normal, fully tested init path.

- **`auth-view.js`:** add `AuthView.concealForRestore()`. It's synchronous: it cancels the
  pending transition and adds `d-none` to `#authenticated-view`, without touching
  `currentView`.
- **`route.js`:** add `Route.homeHref()` returning `pathFor(null)` (`/` plus the carried
  params).
- **`app.js` `init`**, after `Route.init(...)`:

```js
window.addEventListener('pagehide', (e) => {
  // the snapshot itself is concealed —
  if (e.persisted && this._settledFor) AuthView.concealForRestore(); // no portable "before first paint" guarantee (Codex C2)
});
window.addEventListener('pageshow', (e) => {
  if (e.persisted) this.reconcileRestoredSession();
});
```

```js
async reconcileRestoredSession() {
  if (AppState.get('recoveryMode') || !Services.supabase
      || window.location.search.includes('testing=true')) return;
  const shownFor = this._settledFor;
  if (!shownFor) return;                                   // landing was showing: nobody's data
  AuthView.concealForRestore();                            // idempotent with pagehide
  const { data, error } = await Services.supabase.auth.getSession()
    .catch((e) => ({ data: null, error: e }));
  if (error) { window.location.reload(); return; }         // unknown ≠ absent: let a fresh init decide
  const user = data?.session?.user ?? null;
  if (user && (user.id || user.email) === shownFor) { AuthView.render(user); return; } // same reader: reveal
  window.location.replace(Route.homeHref());               // ended, or a different reader: fresh '/'
}
```

- **Why this shape:**
  - `getSession()` re-reads storage on every call (`GoTrueClient.js:1102-1121`).
  - `getSession()` can return `{session: null, error}` without removing the session
    (`:1159`, `:1897`), so an error means reload, not scrub.
  - A navigation can't race a later auth event: whatever the listener does meanwhile, the page
    is replaced.
  - No extra `/auth/logout` is sent. The sign-out that emptied storage already sent one, and
    the server rotates on an identity change (`_bind_session_to_identity`, `app.py:407-412`).
  - A reader returning by Back to their own page sees the same 300 ms reveal a sign-in shows,
    and `handlePopState` already re-fetches the transcript on a persisted `pageshow`.

### 8. `/account` and `/admin` — reload into their own signed-out states

**Verified real:**

- Neither `account.js` nor `admin.js` subscribes to `onAuthStateChange`, so a live tab keeps
  showing A's record or the console after A signs out elsewhere.
- The probe restored `/account` from bfcache with name, email, role, tier and quota.
- Both pages are fresh-read by design (`account.js:72-75`), and their init already renders the
  right signed-out and refused states (`showSignedOut`, `showAccessFailure`).

Add a small shared helper, `static/js/modules/session-reset.js` (`installSessionResetOnEnd`),
used by both entry points after `Services.init()`:

```js
let resetting = false;
function reset() {
  if (resetting) return; // idempotent
  resetting = true;
  document.body.hidden = true; // conceal before the reload can be delayed
  onForcedReset?.(); // account: lets the dirty-form guard stand down
  location.reload();
}
Services.supabase.auth.onAuthStateChange((event) => {
  if (event === 'SIGNED_OUT' || event === 'USER_DELETED') reset();
});
window.addEventListener('pagehide', (e) => {
  if (e.persisted) document.body.hidden = true;
});
window.addEventListener('pageshow', (e) => {
  if (e.persisted) reset();
});
```

- **Account's dirty-form guard** (`account/handlers.js:62`) would otherwise cancel the reload
  and leave A's record showing. Export `allowForcedReload()` from `account/handlers.js`, which
  sets a module flag that `beforeunload` checks first. Pass it as `onForcedReset`. Keep the
  guard for ordinary navigation. A's unsaved edits can't be saved anyway once the session is
  gone.
- **No reload loop:** subscribing emits `INITIAL_SESSION`, and session removal precedes
  `SIGNED_OUT` (`GoTrueClient.js:1546,1983`).
- **Password change, reauthentication, "sign out everywhere else" (`scope: 'others'`), consent
  and profile writes** don't emit `SIGNED_OUT` for this session (`services.js:537-571`,
  `account/handlers.js:211-219`).
- **Import map:** the new file lives in `static/js/modules/`, the shared directory both pages
  already import from, so no new import-map directory is needed. Check
  `test_frontend_architecture.py` and each page's import-map list (`MODULE_FILENAMES`) for the
  new filename.
- **Comment it:** explain why these pages reload while the chat page reconciles. The chat page
  has a live stream and in-page state, and on the sign-out path a reload would cancel the
  teardown POST.

### 9. Notification Center teardown — `dom.js` + `handlers.js`

This is the sign-out half the Notification Center TODO entry (`TODO.md:55`, `:1191-1196`) says
it still owes.

- **`BroadcastNotice.reset()`** (new, `dom.js`):
  - Remove every toast from the stack immediately, **without** calling `onDismiss`.
  - Clear the banner's content, open class and `dataset`, without `onDismiss`.
  - For an open modal, set a module flag so `onHidden` fires **neither** `onAcknowledge` nor
    `onSnooze`, then hide it transition-safely (the `requestHide` pattern, `dom.js:501-508`).
  - Clear `_snoozed` and every `sfda-notif-snooze-*` key in `sessionStorage`
    (`dom.js:330-350`). Snoozes today leak across readers in a tab, so B misses broadcasts A
    snoozed.
  - A teardown must never record a read, dismissal or acknowledgement for anyone.
- **Inbox race** (`loadNotificationHistory`, `handlers.js:1443`): it awaits (`:1452`) and then
  writes items, cursor and DOM unconditionally (`:1472-1476`).
  - Stamp `const generation = notificationsGeneration;` at entry.
  - Return before any mutation, in both the success and failure branches, if it changed.
    `stopNotificationsPolling` already bumps it on every teardown (`:1274`).
  - Apply the same check to `markNotificationRead`'s continuation (`:1385`) and to any
    follow-up load.

## Tests

Two files:

- **`web/tests/test_signed_out_route.py`** runs in the default browser.
- **`web/tests/test_bfcache_session.py`** needs full Chromium.

Both use `pytestmark = pytest.mark.browser` and `import re`.

**Shared rules:**

- **Assertions:** use `re.compile(...)` for URLs. After `goto`, wait for the auth callback and
  the rendered state, not only `APP_INITIALIZED`, which is set at the start of init
  (`app.js:297`).
- **Revocation fixture:** it already exists. Set `__supabaseState.user = null`, remove
  `__mock_supabase_user`, then call `authCallback('SIGNED_OUT', null)`
  (`test_history_notice.py:120-123`).
- **Proving no reload:** a `window.__noReload` marker must survive.
- **Fail first:** check that every behavioural test **fails on the current code** first.

**`test_signed_out_route.py`**

1. **Revocation at `/c/<CONV>`:**
   - Assert: the URL is `/`, the signed-out view shows, there are 0 turns,
     `history.state.convId` is null, and the marker survives.
2. **Same flow from `/c/<CONV>?lang=ar`:** assert the URL ends `/?lang=ar`.
3. **Guard:** a signed-out cold `/c/<CONV>` stays put after `authCallback('INITIAL_SESSION', null)`.
4. **§4 Back guard:**
   - Setup: sign in at `/c/<CONV>` (hydrated), click New chat, revoke.
   - Action: `go_back()`.
   - Assert: the URL is `/`, `convId` is null, and no `/api/chat/history` request is sent after
     the revocation.
5. **§4 error path:** make `getSession` reject once (mock hook). Then Back into `/c/<id>` while
   signed in keeps the URL.
6. **§2 teardown after revocation:**
   - Setup: type a draft, raise the quota notice (route the stream to the 429
     `quota_exhausted` shape handled at `handlers.js:452-467`), show a toast, a banner and an
     open modal (`window.__supabaseState.notificationChannelBroadcastCallback` or a routed
     `fetchActive`), and open the inbox.
   - Action: revoke.
   - Assert: the composer is empty, and no quota notice, toast, banner, modal or inbox rows
     remain. No `mark-read` request was sent. The snooze keys are gone.
   - Then sign in as B (`SIGNED_IN` pattern, `test_history_notice.py:124-131`) and assert all of
     it is still absent.
7. **§9 inbox race:**
   - Setup: hold A's `/notifications/history` response (the held-route pattern,
     `test_frontend.py:53-77`).
   - Action: revoke, sign in as B, then release A's response.
   - Assert: none of A's rows are rendered.
8. **§3 late request:**
   - Setup: hold `getSession` (mock hook) while sending.
   - Action: revoke, then release the hold.
   - Assert: the URL stays `/` and no stream request goes out.
9. **§2 reader switch:**
   - Setup: signed in as A at `/c/<CONV>` with a draft and a held profile read.
   - Action: `SIGNED_IN` as B.
   - Assert: the URL is `/`, the composer is empty, and A's late profile doesn't apply (for
     example, no profile-completion notice queued for A).
10. **`/account` live:**
    - Setup: open it signed in, **make the identity form dirty**, revoke.
    - Assert: the page reloads into the signed-out state. A's email isn't in `body.innerText`.
11. **`/admin` live:**
    - Setup: a **session-backed** console. `_admin_console` uses `?testing=true`
      (`test_admin_browser.py:187`), which makes the token always `fake_token`, so don't use it.
      Route `/api/identity` to an admin answer with no testing param.
    - Action: revoke.
    - Assert: the console is no longer revealed.
12. **§4b:**
    - Setup: sign in at `/c/<CONV>`, go cross-site
      (`base.replace("127.0.0.1", "localhost")`), remove the storage key.
    - Action: `go_back()`. The default headless shell has no bfcache, so this is a fresh
      `back_forward` load.
    - Assert: the URL is `/`.

**Strengthen** `test_source_panel.py::test_logging_out_leaves_nothing_of_the_previous_reader`
(`:634-654`). It logs out from `/c/<id>` and now takes the no-reload path. Fill a distinctive
draft **right before** logout (otherwise the empty-composer assert is vacuous), then assert the
URL is `/`, the composer is empty, and the no-reload marker survives.

**`test_bfcache_session.py`** (full Chromium)

- **Why a custom launch:** the default headless shell reports
  `BackForwardCacheDisabledForDelegate` (observed). Launch via
  `browser_type.launch(channel="chromium", ignore_default_args=["--disable-back-forward-cache"])`.
  CI installs full Chromium (`.github/workflows/tests.yml:49-52`, no `--only-shell`).
- **Context setup:** build the context with `base_url` and install the Supabase, history,
  sessions and stream mocks explicitly. `browser_page` only configures its own context
  (`conftest.py:582-599`).
- **Realistic `getSession`:** add an opt-in `if (window.__mockSessionFromStorage) state.user = readStoredUser();`
  at the top of the mock's `getSession()` (`conftest.py:90`). It's opt-in because
  `test_history_notice.py:124-131` sets `state.user` directly.
- **Leaving and returning:** leave cross-site, remove the key from a second page, then
  `go_back(wait_until="commit")`. A restore fires no `load` event, so the default times out
  (observed).
- **Precondition:** record `pageshow.persisted` **outside the document** (for example via
  `page.expose_function` or a CDP `Page.backForwardCacheNotUsed` listener). It must survive the
  reload that §7 and §8 trigger. Assert that bfcache was actually used, and fail loudly if not.

- **Test 13 — Restored chat page, session ended:** assert it lands on a fresh `/` in the signed-out
  view, without A's email and with 0 sidebar rows. Fails today (probe: A's email, 8 rows).
- **Test 14 — Restored chat page, same reader:** the authenticated view comes back and the transcript
  rehydrates.
- **Test 15 — Restored chat page, `getSession` error:** it reloads (fresh `navigate`) and doesn't scrub
  the URL.
- **Test 16 — Restored `/account`, session ended:** it reloads into the signed-out state without A's
  email. Fails today (probe).

## Docs

Update each doc in the commit that introduces the behaviour it describes.

- **Commit 1:** publish this plan as `docs/revoked-session-url-reset-plan.md` (`STATUS:` line
  plus date). Also do the §5 comment fixes, and add the new TODO entry: **`/auth/logout` fires
  three times per logout-button press.**
  - Where the three come from: `Services.logout`, then the listener's `clearSessionState`, then
    `handleLogout`'s own. Each open tab adds one more on a broadcast sign-out.
  - `auth.py:35-41` says TWO.
  - Cost: it spends the 10/min per-IP budget faster than documented.
  - Deduplication is its own change (the documented-idempotent contract).
  - This plan adds no new POST path: §7 and §8 navigate instead of tearing down.
- **Commit with §7/§8:** add a `docs/ARCHITECTURE.md` identity-section paragraph on how each
  frontend handles an ended session, live and on restore, and why they differ. The reviewer
  confirmed it says nothing about this today.
- **Last commit:**
  - Close the TODO entry per `TODO.md:1587`. Add a dated closing note recording what shipped,
    the corrected "no fixture" and "cookie holds conv_id" claims, the §4 history limit, and
    §7-§9 as found and fixed with the probe evidence.
  - Move the entry to `docs/archive/TODO-resolved.md` and delete Open-now `:66`.
  - Update the Notification Center entry: its sign-out half is closed and the Realtime-push
    check stays open.
  - Archive the published plan with `docs/archive/README.md`'s five steps: lift anything still
    open into TODO.md first, `git mv`, add the `STATUS: HISTORICAL RECORD` banner, and add an
    index row.

## Commit split

Each commit passes all gates on its own and bumps `ASSET_VERSION`.

1. **§1-§6** (the TODO fix, the shared teardown, the race guards, the §4 Back guard **without
   §4b**), plus tests 1-6, 8, 9 and the strengthened source-panel test.
2. **§9** (Notification Center teardown and inbox race), plus test 7. Extend test 6's
   notification assertions here if they were stubbed in commit 1.
3. **§4b + §7**, plus tests 12-15 and the mock opt-in flag.
4. **§8**, plus tests 10, 11 and 16, then the final docs close.

## Evidence (orchestrator probe, 2026-09-11 — a throwaway Playwright script against the testing app, not committed; `test_bfcache_session.py` is its durable form)

| Case                                          | Browser                               | Result on Back                                                                                                                |
| --------------------------------------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Chat `/c/<id>`, storage cleared, no broadcast | Chromium 151 new-headless, bfcache on | **Restored** (`persisted:true`). "Logged in as: `reader-a@example.com`", 8 sidebar rows, URL `/c/<id>`; unchanged after 2.8 s |
| Same, with a BroadcastChannel message         | same                                  | Evicted (`BroadcastChannelOnMessage`). Fresh load, signed out, **URL still `/c/<id>`**                                        |
| `/account`, storage cleared, no broadcast     | same                                  | **Restored** with name, email, role, tier and quota; unchanged                                                                |
| Any case                                      | Playwright default headless shell     | bfcache disabled (`BackForwardCacheDisabledForDelegate`)                                                                      |

## Out of scope

- **Reader A never signs out and leaves the machine:** A's session is still live. That's not a
  defect.
- **Deduplicating `/auth/logout`:** covered by the new TODO entry.
- **FAQ callbacks after a switch** are unguarded (`app.js:401-406`), but the FAQ data is public
  (`services.js:166`). No change; don't describe it as identity-guarded.

## Verification

```bash
python -m pytest web/tests/test_signed_out_route.py web/tests/test_source_panel.py --browser chromium
python -m pytest web/tests/test_bfcache_session.py --browser chromium
python -m pytest -m browser --browser chromium
python -m pytest -m "not browser and not integration"        # frontend-architecture, i18n parity, css contract
ruff check . && ruff format --check . && mypy web && npm run lint && pre-commit run --all-files
```

**Manual check** against a real project:

1. Sign in and open `/c/<id>`.
2. Sign out in a second tab. Confirm the first tab resets to `/` with no reload, the composer is
   empty, no notification surfaces remain, and Back doesn't restore the id.
3. Open `/account` with a dirty form and sign out elsewhere. Confirm it reloads into the
   signed-out state.
4. Leave `/c/<id>` for an external site, sign out in another tab, press Back. Confirm nothing of
   A's shows.

## Implementation notes

Where the build departed from the text above, and why. Implemented by agy (Gemini 3.8 Flash
High) from orchestrator briefs; every diff was reviewed line by line, every new test was run
against the pre-change code, and the two guard branches were mutation-tested.

**Commit 1 (§1-§6):**

- **`UI.autoResizeInput` does not exist.** §2's table calls it; the only existing call
  (`handlers.js`, the quota path) is optional-chained and has always been a no-op. The teardown
  empties the composer the way `processQuery` does, with `value = ''` alone.
- **The teardown also hides the admin link** (`AuthView.renderAdminAffordance(false)`), beyond
  §2's table. On a direct A→B switch, A's link otherwise stays up until B's identity check
  resolves — and indefinitely if it resolves as `is_resolved: false`. Test 9 proves the
  `identityCheckId` bump is load-bearing: with it removed, A's late answer shows the console link
  to B.
- **The browser double never emits `INITIAL_SESSION`**, so after a `goto` the listener's
  identity/profile branch never runs. Test 9 therefore reaches `/c/<id>` signed out and signs in
  through the form (the §4.5 deep-link-across-sign-in path) to get a held `/api/identity` call.
- **Test 5 is not a pure guard.** On the old code a `getSession` error during Back surfaces
  through `getChatHistory` and the transcript never rehydrates, so it fails there as well as
  under the `!token` mutation. Test 3 is the only test that passes on the pre-change code, by
  design.
- **Two pre-existing bugs surfaced and were fixed in their own commit ahead of this one.** Test 6
  needs the quota notice on screen, and it had never rendered: `showQuotaNotice` passed
  `'history-notice quota-notice'` to `classList.add` as one token (which throws), and
  `removePendingUserTurn` looked for `.message.user` — a class no bubble carries — while comparing
  against text that includes the timestamp. So a reader who ran out of questions lost the
  question, saw no notice, and got an unhandled rejection. Both came from `a6dbefb`;
  `test_quota_notice.py` pins the fix. agy found the first one and stopped rather than weaken
  the test, as its brief told it to.

**Commit 2 (§9):**

- **The inbox guards stamp a new `readerGeneration`, not `notificationsGeneration`.** §9 said to
  reuse the poll's counter, but `stopNotificationsPolling` also bumps it whenever the tab is
  merely hidden, so an inbox page loading while the reader switched browser tabs would have been
  discarded and left spinning. `readerGeneration` moves only in `clearReaderLocalState`.
- **`BroadcastNotice.reset()` also cancels a banner's pending open.** `showBanner` adds its open
  class in a `requestAnimationFrame`; a reset landing inside that frame would have been undone.
  The callback now checks the banner still names the same notification.
- **Accepted edge:** a reader who clicks _Got it_ on an acknowledgement modal in the ~300 ms
  before a teardown hides it loses that acknowledgement (the suppressed `hidden` handler records
  nothing). The notice resurfaces next session, which fails safe.
- **Tests 10-13** (numbered past the original 12 because test 7 became tests 12 and 13): the two
  race tests call the handlers directly through the page's own module graph and await the stale
  call, so they cannot pass by winning a timing race. All four fail on the pre-change code.

## Review record

| #   | Finding                                                                                      | Source                  | Outcome                                                            |
| --- | -------------------------------------------------------------------------------------------- | ----------------------- | ------------------------------------------------------------------ |
| 1   | Composer and quota notice leak once the reload is gone                                       | OpenCode, agy           | Accepted → §2                                                      |
| 2   | `meta` handler unguarded                                                                     | OpenCode                | Accepted (invariant) → §3                                          |
| 3   | Pre-`Route.enter` token await unguarded                                                      | Codex C1                | Accepted → §3                                                      |
| 4   | `to_have_url("/$")` never matches; vacuous composer assert; `APP_INITIALIZED` too early      | OpenCode, Codex C6      | Accepted → Tests                                                   |
| 5   | Back re-exposes the id; a token error must not scrub                                         | OpenCode, agy, Codex C4 | Accepted (user decision) → §4                                      |
| 6   | Keep the reload on explicit logout                                                           | agy                     | Rejected (user decision); teardown completed instead               |
| 7   | Cookie no longer holds `conv_id`                                                             | agy                     | Accepted → §1, §5                                                  |
| 8   | Triple `/auth/logout`                                                                        | agy, Codex C7           | Pre-existing → new TODO entry; §7/§8 add no POST                   |
| 9   | bfcache restore shows the ended reader                                                       | agy → probe             | Verified and accepted (user) → §7, §8                              |
| 10  | Synthesized auth events unsafe (errors, double `SIGNED_OUT`, stale profile)                  | Codex C2/C7             | Accepted → §7 navigates instead                                    |
| 11  | "Never paints the snapshot" isn't portable                                                   | Codex C2                | Accepted → conceal on `pagehide` too                               |
| 12  | Cross-document Back keeps the id                                                             | probe                   | Accepted → §4b                                                     |
| 13  | `/account`, `/admin` never react to a session ending; the dirty-form guard blocks the reload | code read, Codex C3     | Accepted → §8                                                      |
| 14  | Reader switch: weaker teardown, stale profile                                                | Codex C2                | Accepted → §2                                                      |
| 15  | Notification toast, banner, modal, inbox and snoozes survive; inbox race                     | agy, Codex NF1-2        | Accepted → §9                                                      |
| 16  | Admin test via `?testing=true` is vacuous                                                    | Codex C6                | Accepted → test 11                                                 |
| 17  | Referrer leak of `/c/<id>`                                                                   | agy                     | Confirmed sound: `strict-origin-when-cross-origin` (`app.py:1808`) |
