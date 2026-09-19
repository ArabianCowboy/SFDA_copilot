STATUS: CURRENT AUTHORITY — open work only. Last verified against code 2026-09-03.
Resolved entries live in `docs/archive/TODO-resolved.md`.

# TODO

Known problems found but deliberately not fixed in the commit that found them,
usually because the fix reaches further than the work in hand. Each entry says
what is wrong, how it was found, and what fixing it would disturb — so the next
person can judge the cost rather than rediscover it.

**Known bugs** are things that are wrong now. **Planned work** is wanted but not
started. Both are written the same way and for the same reason: an entry that
says only what it wants is a wish, and the useful half is the cost.

Everything in this file is open. Resolved entries — with the reasoning trail that
made them worth writing — moved to `docs/archive/TODO-resolved.md` on 2026-08-23,
because a file where nine entries in forty-four read as current is a file nobody
trusts the index of. **When you close an entry, move it there; do not strike it in
place.**

When two documents disagree about how this system works, the order that settles it
is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Rules that are individually
correct but collide at one specific point — and there are sixteen known ones — are listed
there too, under
[_Rules that collide_](docs/ARCHITECTURE.md#rules-that-collide). Read that section
before your next migration or your first RTL component.

**Adding an entry, or closing one?** The template and the closing procedure are at the
bottom of this file: [How this file works](#how-this-file-works).

---

## Open now

- [The Arabic deletion confirmation word is the everyday word for "delete"](#the-arabic-deletion-confirmation-word-is-the-everyday-word-for-delete) — a product decision, not a translation bug; `حذف` carries less friction than `DELETE`.
- [A deletion request may leave the requesting access token usable until it expires](#a-deletion-request-may-leave-the-requesting-access-token-usable-until-it-expires) — diagnosed, unconfirmed; one bearer-token call decides it.
- [Live code cites plan sections instead of the live contract](#live-code-cites-plan-sections-instead-of-the-live-contract) — blocks archiving two finished plans; count citations, do not trust a written figure.
- [Leaked-password protection is disabled in Supabase Auth](#leaked-password-protection-is-disabled-in-supabase-auth) — blocked on a Pro-plan upgrade, not code.
- [`POST /auth/login` is a 410 tombstone pending deletion](#post-authlogin-is-a-410-tombstone-pending-deletion) — tombstone shipped; the bare deletion is still owed next release.
- [A silent truncation from a provider that omits `finish_reason` is still undetected](#a-silent-truncation-from-a-provider-that-omits-finish_reason-is-still-undetected) — diagnosed; needs `include_usage`, not a different default.
- [An empty answer toasts "failed to send", which is the wrong thing](#an-empty-answer-toasts-failed-to-send-which-is-the-wrong-thing) — cosmetic, needs a bilingual key pair.
- [`max_tokens` has no floor, and a low one guarantees empty answers](#max_tokens-has-no-floor-and-a-low-one-guarantees-empty-answers) — not started; prevention rather than the reporting that now exists.
- [Security email is English-only](#security-email-is-english-only-on-a-product-that-is-bilingual-by-construction) — still blocked in the Supabase dashboard, not code; the mechanism question is now settled (2026-09-18) and the templates are unwritten.
- [SettingsService's two cache slots each query the settings row independently](#settingsservices-two-cache-slots-each-query-the-settings-row-independently) — not a correctness issue; recorded in case the round trip ever becomes measurable.
- [Answer from a second provider](#answer-from-a-second-provider--and-why-the-code-is-the-easy-half) — the citation-fidelity harness is built (2026-08-22); still blocked on running it for real against the API.
- [OpenRouter as one integration instead of several](#openrouter-as-one-integration-instead-of-several) — alternative to the entry above; same harness, same not-yet-run status.
- [Refactor the profile page](#refactor-the-profile-page) — Steps 0-5 and most of Step 7 shipped 2026-08-23; the three remaining items each have their own entry below.
- [The shipped daily allowance is a placeholder number](#the-shipped-daily-allowance-is-a-placeholder-number-not-a-measured-one) — both tiers are 200; waiting on a month of `usage_daily` rows and an owner for the number.
- [The daily-allowance claim is not idempotent](#the-daily-allowance-claim-is-not-idempotent-and-one-future-commit-would-make-that-matter) — harmless today, **mandatory** in any commit that adds a client-side chat retry.
- [A fixed promo pool of bonus messages](#a-fixed-promo-pool-of-bonus-messages-designed-and-deliberately-not-built) — designed in full, parked by owner decision pending real usage data.
- [`/api/identity` makes three RPC round trips](#apiidentity-makes-three-rpc-round-trips-where-one-would-do) — an optimisation that reopens a deliberate narrowing decision.
- [`history_api` and `sessions_api` are still keyed by IP](#history_api-and-sessions_api-are-still-rate-limited-by-ip-not-by-account) — a decision about navigation reads, not a defect.
- [The console's class-existence gate cannot see a class built from a variable](#the-consoles-class-existence-gate-cannot-see-a-class-built-from-a-variable) — a known hole in a gate that otherwise reads as total.
- [The browser suite flakes intermittently in test_source_panel.py](#the-browser-suite-flakes-intermittently-in-test_source_panelpy) — undiagnosed; resource-contention evidence only.
- [Admin analytics from saved chats](#admin-analytics-from-saved-chats--common-questions-unanswered-topics-citation-quality) — not started; V1 aggregates off saved chats.
- [Admin per-member conversation viewer](#admin-per-member-conversation-viewer--full-qa-with-audit) — not started; full Q&A with audit row per open.
- [Admin analytics + viewer follow-ups](#admin-analytics--viewer-follow-ups--click-through-feedback-search-daily-counts-audit-display) — not started; seven small adds.
- [Enable the token-verification cache once production numbers justify it](#enable-the-token-verification-cache-once-production-numbers-justify-it) — single-flight (the worker-starvation fix) shipped 2026-08-27 at no revocation cost; the optional positive cache stays off, gated on measurement.
- [Admin broadcast & Reader Notification Center](#admin-broadcast--reader-notification-center-popups-banners-and-inbox-history) — implemented 2026-08-24; live login/session smoke-tested against production 2026-08-29 (by hand), which also surfaced and closed a real `mark-read` 500 the same day ([fix write-up](docs/archive/2026-08-29_notification-mark-read-500.md)); still owes a live Realtime-push check; the sign-out teardown shipped 2026-09-11 and the reauthenticate path needs none; the `mypy web` caveat closed 2026-09-08.
- [Marketing consent has no re-prompt path](#marketing-consent-has-no-re-prompt-path-and-the-trigger-cannot-record-a-re-affirmation) — deferred by decision 2026-09-18; due when the policy next changes materially.
- [The privacy policy (/privacy) is a draft, not reviewed legal text](#the-privacy-policy-privacy-is-a-draft-not-reviewed-legal-text) — consent shipped against this draft; deletion copy corrected it to `-draft-2` on 2026-09-18, and the legal review of the text is still owed.
- [Account deletion (Spec 4)](#account-deletion-spec-4--blocked-on-a-product-decision-not-on-engineering) — decision closed 2026-09-18 (yes, 30-day grace); built and **fourteen of fifteen migrations applied 2026-09-19**, code deployed, reconcile timer running. Held only on the feature switch, and on one real deletion before `13`. See `supabase/pending/README.md`.
- [Gunicorn writes no access log](#gunicorn-writes-no-access-log-so-served-fine-and-never-asked-look-identical) — found 2026-09-19 when it made a deploy check ambiguous; decide it WITH the entry below, not before.
- [A conversation id now reaches the access log](#a-conversation-id-now-reaches-the-access-log) — a verification task, possibly already fine; unverified either way.
- [Six of the seven admin RPCs validate the actor without holding a lock](#six-of-the-seven-admin-rpcs-validate-the-actor-without-holding-a-lock) — a check-then-act window; pre-existing, not introduced by the actor gate.
- [Two search artifacts are unpickled before anything has validated them](#two-search-artifacts-are-unpickled-before-anything-has-validated-them) — not started; needs a format change and a corpus rebuild, not a hash.
- [Nothing ever deletes an old search build](#nothing-ever-deletes-an-old-search-build) — not started; 16 on disk, 8 of them failed runs; the cleanup step is the risky half.
- [`IndexFlatL2` shifts every id above a deleted vector](#indexflatl2-shifts-every-id-above-a-deleted-vector) — nothing is wrong today; **mandatory** in any commit that adds incremental delete or update.
- [One guideline is silently absent from the corpus](#one-guideline-is-silently-absent-from-the-corpus-and-warehouse-questions-land-elsewhere) — measured 2026-09-18; the cheap half is surfacing `skipped_documents`, the expensive half is OCR.
- [LOG_LEVEL works only because of import order](#log_level-works-only-because-of-import-order-and-nothing-protects-that) — nothing is broken; the one removable hazard shipped 2026-09-18, the ordering dependency remains unguarded.
- [Every candidate's TF-IDF cosine is computed twice per question](#every-candidates-tf-idf-cosine-is-computed-twice-per-question) — not started; 561 µs a question, recorded because the cost of fixing it is the interesting half.
- [A retention policy, and the bounds that depend on one](#a-retention-policy-and-the-bounds-that-depend-on-one) — blocked on a retention period nobody owns; covers the assistant-message and audit_log text bounds too.
- [`chat_sessions.owner_id` still has no foreign key](#chat_sessionsowner_id-still-has-no-foreign-key) — still open; the staged migration was **removed** 2026-09-19 rather than kept parked. Low priority while no deletion has completed, but there is **no orphan detector**, so a failure would be invisible.
- [Does "disabled" freeze an account's own profile edits?](#does-disabled-freeze-an-accounts-own-profile-edits-or-only-its-use-of-the-product) — decided 2026-09-18 (freeze everything but consent withdrawal); **fully applied and live 2026-09-19**. The consent column grants are revoked, the `profiles` UPDATE policy is gated, and `update_own_preferences` is closed.
- [Confirm the backup schedule, and rehearse a restore once](#confirm-the-backup-schedule-and-rehearse-a-restore-once) — dashboard task; the recovery position is currently an assumption.
- [Measure the real statement and lock timeouts on the write path](#measure-the-real-statement-and-lock-timeouts-on-the-write-path) — needs a call through PostgREST, not MCP.
- [Run the database assertions somewhere other than by hand](#run-the-database-assertions-somewhere-other-than-by-hand) — `supabase/tests/` exists and runs by hand only; the two newest files have never been run at all.
- [One Realtime socket per reader, not one per visible tab](#one-realtime-socket-per-reader-not-one-per-visible-tab) — not started; costs nothing measurable yet, written down because the cost is the interesting half.
- [Confirm on the live site that chat streaming arrives token by token](#confirm-on-the-live-site-that-chat-streaming-arrives-token-by-token) — post-restart verification; circumstantial log evidence says yes, owed by a human.

---

## Known bugs

### The Arabic deletion confirmation word is the everyday word for "delete"

**Where:** `page.account.deletionConfirmWord` in `web/i18n/ar.yaml` (`حذف`), its English
counterpart in `en.yaml` (`DELETE`), and `_expected_deletion_confirmations()` in
`web/api/account.py:368-386`.

**What is wrong.** The typed confirmation exists to create deliberate friction before an
irreversible request — the reader must stop and type something rather than click through. The
English does that with case: `DELETE` is six characters that need Shift or Caps Lock, and it is
not a word the UI uses anywhere else.

The Arabic does not. Arabic script has no letter case, and `حذف` is a three-letter root that is
the standard label on every delete button in every Arabic application. It is the single most
typed delete-related word an Arabic reader knows, it can be produced almost reflexively, and a
mobile keyboard will happily autocomplete it. The friction the English control depends on does
not survive the translation, so the two languages ship different amounts of protection for the
same irreversible action.

**Forcing Latin `DELETE` on an Arabic reader is not the fix** and should not be the reflex: it
would require a keyboard-layout switch, which is jarring on mobile and contradicts
`docs/PRODUCT.md`'s principle that Arabic is not a translation layer. The proposal on the table
is `حذف الحساب` — two words, ten characters including the space, still natural formal Arabic,
and it names the scope (the account, not a message) the way the bare verb does not. `تأكيد
الحذف` is the alternative.

**Who it reaches.** Every Arabic reader who reaches the deletion form, which is the majority of
this product's audience. Nobody has been harmed: the step-up password and the durable throttle
sit behind this control, so a reflexive confirmation still cannot delete an account on its own.
This is the outer of several gates, and it is the one that is weaker in Arabic than in English.

**How it was found.** An AI QA pass over the deletion catalogue on 2026-09-19, reviewing copy a
human had already signed off across two rounds. The human review was looking for translation
errors; this is not one. The Arabic is correct — it is the control that is weaker, which is a
question only a reader of both languages would think to ask.

**What fixing it would disturb.** Less than it looks. `_expected_deletion_confirmations()` reads
the word from the catalogue rather than hardcoding it, deliberately, so changing `ar.yaml`
updates the browser's enable-gate and the server's acceptance together with no code change —
`web/tests/test_account_deletion.py` and `test_account_deletion_slice_2d.py` exercise both. The
real cost is a decision, not a diff: this is a product call about how much friction an Arabic
destructive confirmation should carry, and it belongs to whoever owns `docs/PRODUCT.md`. Note
also that any reader mid-flow when it changes sees the label change under them, which is
harmless but worth doing in a quiet moment rather than during a deploy that touches deletion.

### A deletion request may leave the requesting access token usable until it expires

**Where:** `deletion_request` in `web/api/account.py` (the `sign_out_all` block) and
`web/services/auth_admin.py`.

**What is wrong — and what is only suspected.** Requesting deletion calls GoTrue's global
sign-out with the requesting session's JWT, and that half is **verified**: after the
2026-09-19 production round trip, `auth.sessions` held exactly one row for the account,
created at `10:46:56`, four minutes AFTER the `10:42:25` request. Every session predating
the request was gone. The server-side revocation works.

What is **not** confirmed is what an already-issued access token can still do in the window
between the request and its own expiry. The browser assistant running that round trip
reported it "was not signed out immediately" and "remained signed in on the next
navigation", with the old session already deleted — which would mean GoTrue's `get_user`
still accepts an unexpired JWT whose session has been revoked, as a stateless JWT check
would. But that observation is not airtight: a `supabase-js` session restored from
`localStorage` renders as signed-in without any authenticated call necessarily succeeding,
and the operator also signed out and back in by hand during the test, which confounds it.

**Who it reaches.** Bounded either way, and this is not the control that stops a thief — the
route's own comment is careful to say it kills refresh tokens, not that it locks the account
instantly. But the reader-facing promise is "requesting deletion ends your sessions", and if
a stolen access token keeps working for up to the Supabase default hour, that sentence is
approximately rather than exactly true. The repo records no configured `jwt_exp`, so the
window is whatever the project default is — itself worth writing down.

**How it was found.** The production round trip on 2026-09-19, when an observation that first
looked like "the sign-out did not run" turned out to be the opposite: it ran, and the
question is what survives it.

**What settling it would disturb.** Nothing, to settle: issue a deletion request, then make
one authenticated API call with the pre-request bearer and see whether it answers 200 or 401.
That is a five-minute test and it decides whether there is a defect here at all. Note the
access log cannot answer it retroactively — see _A conversation id now reaches the access
log_ — because gunicorn logs no request. **If** it turns out a revoked session's token still
authenticates, the fix is not more sign-out calls: it is `token_verification`'s cache and TTL
posture, which is deliberately `0` as shipped, plus a decision about whether the reader-facing
copy should promise session termination at all.

### Live code cites plan sections instead of the live contract

**Where:** the per-tab set was repointed at
`docs/archive/2026-08-22_per-tab-deep-linking.md` on 2026-09-12;
`registrations-pause-plan.md` and `notification-center-plan.md` are still cited from `docs/`.
Count the citing files with `git ls-files -z | xargs -0 grep -l '<path>'` rather than trusting
any figure — every hand-written count of this in the repo has been wrong, including the ones
written while filing this entry. Two migration headers still name the pre-archive path:
`supabase/migrations/20260822143317_chat_session_exists.sql:3` and
`20260822143411_chat_append_turn_allow_create.sql:3`.

**What is wrong.** `CLAUDE.md` says to treat anything under `docs/archive/` as "evidence about
the past, never as current behaviour" and to "confirm against `docs/ARCHITECTURE.md` or the
code and cite that instead". Forty-one live comments now cite the archive for **present-tense**
behaviour ("THE URL IS THE POINTER now (docs/archive/… §1)"), which is the prohibited form.
The archive is also excluded from search by `/.ignore`, so those pointers aim at content the
default search cannot reach, and the file they open says not to trust it — a circle back to
`ARCHITECTURE.md`, which is what should have been cited. `docs/ARCHITECTURE.md:21` already
names itself first authority and the archived plan second; citing only the second inverts that
in 41 places.

**Who it reaches.** Every contributor or agent following the reasoning behind the
URL-as-pointer model, the registrations pause, or the Notification Center — which is most of
the load-bearing code in this app.

**How it was found.** An adversarial review of `019b8aa` (`opencode/muse-spark-1.3`, xhigh).
That commit fixed 41 dangling citations but chose section precision over currency, and its own
closing note conceded `ARCHITECTURE.md` "does not carry the plan's section numbers" — which is
an argument for adding anchors, not for citing history.

**What fixing it would disturb.** `docs/ARCHITECTURE.md` grows anchors where a `§X` reference
is load-bearing (pointer §1, preflight §3.4, CSRF §3.5, deletions §5.x, headers §6.1), then
citations become `live authority; reasoning in archive §Z` — archive-only for genuinely
historical asides. It spans ~19 files and should not ride along with an unrelated change. Doing
it is also what makes archiving the two remaining finished plans a `git mv` again instead of a
rewrite, so it blocks that cleanup.

**The two migration headers are a deliberate exception.** An applied migration's file is a
point-in-time record of what ran; editing it after the fact breaks the property that the
recorded file is the applied file. They keep the pre-archive path. Do not "fix" them.

### A silent truncation from a provider that omits `finish_reason` is still undetected

**Where:** `web/services/openai_app.py` (`stream_response`) and the `done` frame in
`web/api/app.py`.

**What is wrong.** Since `80593b4` the server reports the provider's real
termination reason, or `"unknown"` when none arrives, and the client flags an
explicit `"length"`. That is honest but incomplete: not every OpenAI-compatible
gateway sends a terminal `finish_reason`, and one that truncates without saying so
still reaches the reader looking whole.

**Who it reaches.** Nobody on stock OpenAI, which does send it. Anyone reached
through a `base_url` override — today only the citation-fidelity harness, but that
field exists precisely so a second provider can be tried.

**How it was found.** Raised against the fix in `80593b4` by both an adversarial
review and a pass over upstream sources. The fallback was chosen to under-flag
rather than over-flag on purpose: a warning that appears on correct answers is
trained away within a day, and then it is worth nothing on the answer that needed
it.

**What fixing it would disturb.** The answer is a positive signal, not a different
default: `stream_options={"include_usage": True}` exposes
`usage.completion_tokens_details.reasoning_tokens`, which separates budget
exhaustion from a model that chose to say nothing. That means reading the
usage-only final chunk the loop currently skips, deciding what to do when it never
arrives (the SDK documents it as absent on an interrupted stream), and probably a
second field on the `done` frame. It also costs a little response size on every
request, for a signal only some providers make necessary.

---

### An empty answer toasts "failed to send", which is the wrong thing

**Where:** `static/js/modules/handlers.js` — the toast copy selection in the
stream's failure branch, which routes every code except `persistence_unavailable`
to `chat.sendFailed`.

**What is wrong.** Since `6347212` a provider that returns nothing produces an
`error` frame coded `empty_answer`, the allowance is refunded and nothing is filed.
But the reader is told their message failed to send. It did not: it was sent,
understood, and answered with nothing. The file already reasons about exactly this
distinction one branch over, for `chat.notSaved`.

**Who it reaches.** Any reader who hits an empty answer — rare, and unmeasured.

**How it was found.** Flagged during the `6347212` review as a known, accepted
inaccuracy rather than discovered afterwards.

**What fixing it would disturb.** A third branch in that lookup and a new key pair
in both `en.yaml` and `ar.yaml` under an existing `runtime.*` namespace, plus an
`ASSET_VERSION` bump. Small, but it is reader-facing copy, so `docs/PRODUCT.md`
governs the wording and the Arabic needs a native read.

---

### `max_tokens` has no floor, and a low one guarantees empty answers

**Where:** `web/services/settings_service.py` (`GENERATION_KEYS`, and the
validation beside it), reached from the console's generation settings.

**What is wrong.** `max_tokens` is validated as a positive integer under the
model's declared ceiling, with no lower bound. For a reasoning model the budget
covers hidden reasoning tokens **and** visible output, so a low value is spent
entirely on reasoning and the model returns nothing, terminating on
`finish_reason: "length"`. The provider bills every one of those tokens. An
operator can therefore configure a guaranteed-empty, fully-billed answer from a
form that reports no problem.

**Who it reaches.** Every reader, immediately, from one console edit.

**How it was found.** A pass over upstream guidance during the 2026-09-05 fixes:
the recommendation is to leave the budget unset, or keep it well clear of the
reasoning cost and control spend with `reasoning_effort` instead.

**What fixing it would disturb.** The commits in
[the archived review-findings plan](docs/archive/2026-09-05_review-findings-fix.md)
made this _reportable_ — refunded, not filed, and flagged — but not _preventable_.
A floor needs a number, and the honest number is model-dependent, so it probably
belongs in `allowed_models` in `config.yaml` beside each model's ceiling rather
than as one global constant. That reopens the shape of the model contract, which is
why it was not done alongside the reporting.

---

### Leaked-password protection is disabled in Supabase Auth

**Where:** The Supabase project itself (`yjjuudnsnjzhyqllsqrd`), not this
repo — surfaced by Supabase's advisors during a 2026-08-13 database audit.

**What is wrong.** Leaked-password protection is off in Auth: Supabase would
otherwise reject signups/password changes using a password known to be
compromised, checked against HaveIBeenPwned.

**Who it reaches.** Every signup — project-wide, not per-route.

**The fix, and why it was not made here.** It's a toggle under
Authentication → Attack Protection, but the toggle is a **Pro-plan feature**
and this project is on a lower tier while actively developing. Left off
intentionally rather than forced — revisit when the project upgrades to Pro
or moves toward production.

**Companion item, resolved:** the same audit flagged the project's Postgres
as behind on security patches. That side is done — upgraded to `17.6.1.155`
on 2026-08-13, confirmed via Security Advisor (warnings dropped from 2 to
1, the remaining one being leaked-password protection above). The same
audit pass also fixed what it could reach via `apply_migration` (revoking
public `EXECUTE` on the `handle_new_user` signup trigger, pinning
`handle_profile_update`'s `search_path`, and optimizing the RLS policies on
`profiles`/`users`).

---

### Security email is English-only, on a product that is bilingual by construction

**Update 2026-09-18 — the premise changed, the answer did not.** This entry says GoTrue
"offers no per-request language negotiation" and that this is "not a code change". The first
half is now false: Supabase's Send Email Hook replaces GoTrue's templating with a function
that picks language per user, and `web/api/auth.py:219,434` already carries `lang` through
signup and recovery. It was **rejected anyway, on availability rather than capability** — it
puts an Edge Function and a third-party SMTP provider on the critical path of signup and
password recovery, and this repository's rule is that an outage is a 503 and never a 401.
The decision is to ship **one dual-language template per type, Arabic first**, set `dir` on
`<table>` and `<td>` (desktop Outlook renders through Word, which ignores `direction: rtl`),
share one link between both languages, and never interpolate `.Data.*`. Change one template
first and verify by watching `recovery_sent_at` move — a broken recovery template locks people
out. Still open: the templates are unwritten, and this remains dashboard work.

**Where:** Supabase → Authentication → Emails. The confirmation, recovery, and
email-change templates GoTrue sends.

**What is wrong.** `docs/PRODUCT.md` makes EN/AR parity a binding brand commitment —
"every surface ships bilingual, no English-only feature, no Arabic afterthought" — and
the application honours it: `test_arabic_catalogue_covers_every_runtime_key` fails the
build if a single string lags. The security email does not. A reader who signs up in
Arabic, and reads every word of the product in Arabic, gets an English email asking
them to confirm their address or reset their password.

**Who it reaches.** Every Arabic reader, at the two moments the product is least able
to explain itself: account creation, and account recovery. Recovery is the sharper
case — someone locked out cannot read the app's own Arabic to work out what the
English email is asking of them.

**Why it is not fixed.** The templates are not in this repository. They live in the
Supabase dashboard, they are authored per project, and GoTrue offers no per-request
language negotiation: one template per email type, one language each. Shipping
bilingual security mail means writing each template with both languages in the body,
Arabic first — a copywriting task in a legal-ish register in two languages, not a code
change.

**What fixing it would disturb.** Nothing in the codebase. `docs/OPERATIONS.md` gains a
section, and every template edit becomes a two-language edit from then on. Recorded at
§14·D·26 and §17 Step 5 of `docs/archive/2026-08-23_profile-refactor.md`, where it is
the one Step 5 item left unchecked — blocked, not attempted.

---

### SettingsService's two cache slots each query the settings row independently

**Where:** `web/services/settings_service.py` — `signup_enabled()` (the operational cache) and
`snapshot()` (the generation cache) each independently call `admin_store.get_settings()` against
the same single-row JSONB document; likewise their write counterparts, `set_signup_enabled()`
and `update()`.

**What is wrong.** `static/js/admin.js` fires `initRegistrationsTab` and `initSettingsTab`
concurrently on every admin console open, so a cold cache on both sides (e.g. right after a
process restart, or after both caches' TTLs expire together) costs two Supabase round trips for
the identical row instead of one.

**Who it reaches.** Nobody in a way that matters today — not a correctness issue, only a
possibly-redundant round trip on an admin-only, low-frequency surface.

**How it was found.** Surfaced as a related item by `/code-review`'s 2026-08-26 pass on the
`SettingsService.snapshot()` race below (now `docs/archive/TODO-resolved.md`), while reviewing
the registrations-pause feature; filed here rather than as its own review.

**What fixing it would disturb.** Judged not worth it today: merging the two cache slots would
couple two caches the registrations-pause feature deliberately kept separate (§2 of
`docs/registrations-pause-plan.md`), to remove a round trip that isn't currently measurable.
Recorded in case that changes.

### Six of the seven admin RPCs validate the actor without holding a lock

**Where:** `public.admin_actor_email`, called at the top of `admin_write_settings`,
`admin_update_profile`, `admin_create_notification`, `admin_deactivate_notification`,
`admin_delete_notification` and `admin_purge_notification`
(`supabase/migrations/20260828001543_admin_rpcs_require_an_enabled_actor.sql`).

**What is wrong.** The gate is an ordinary unlocked read of `public.profiles` joined to
`auth.users`. Six of the seven callers then mutate without holding anything that would stop
the actor's own row changing underneath them, so this interleaving is legal:

1. T1 calls `admin_actor_email` and sees administrator A as enabled.
2. T2 takes the membership advisory lock, demotes or disables A, and commits.
3. T1 proceeds and commits its mutation, attributed to A as an authorized administrator.

`admin_set_user_flags` is the exception and shows what the fix looks like: it takes
`pg_advisory_xact_lock(hashtext('sfda.admin_membership'))` first and validates the actor
**inside** the lock, which is what `20260814110722` was written to provide.

**Who it reaches.** An administrator whose access is revoked while they have an action in
flight. The window is one statement wide and the console is used by two accounts, so nobody
has hit it. Note the honest scope: this is not privilege escalation and not a regression —
the old `if p_actor_id is not null then …` guard had exactly the same property in exactly
the same six functions. The actor migration made the check mandatory, not atomic.

**How it was found.** An adversarial review of the applied implementation
(`openai/gpt-5.6-sol`, 2026-08-28), which was asked to find what the implementer's own
verification had missed.

**What fixing it would disturb.** Serialising all seven on one advisory lock would make
every settings save, profile edit and notification send contend on a single lock that today
only guards administrator-membership changes — a real throughput cost on the console's
common paths to close a window nobody can currently reach. The cheaper alternative is to
have `admin_actor_email` take `for share` on the actor's `profiles` row, which conflicts
with the `for update` that `admin_set_user_flags` already takes on a demotion target and
costs nothing on the uncontended path. That is probably the right answer, and it should be
measured rather than assumed: `for share` on `profiles` sits on the hot path of every admin
mutation, and `profiles` is also the table every reader request reads.

### Two search artifacts are unpickled before anything has validated them

**Where:** `web/services/search_index.py` — `_load_tfidf_vectorizer` and `_load_tfidf_matrix`,
called at `load()` steps 5 and 6, before `_validate_dimensions` and `_validate_manifest` run.
Also `build_registry.validate_build_dir`, which unpickles both "only to confirm it is not
corrupt".

**What is wrong.** `tfidf_vectorizer.pkl` and `tfidf_matrix.pkl` are Python pickles, and
`pickle.load` executes opcodes as it reads them — a crafted stream runs code the microsecond it
is loaded, not when loading finishes. Every check this app performs on those files happens
afterwards, so no check can protect the process from them. This is a property of the ordering,
not a weak guard: a verification placed after `pickle.load` is mechanically incapable of firing
before the thing it guards against.

**Who it reaches.** Nobody today, and the honest reason is that nothing untrusted reaches this
path: the app builds these artifacts itself, from its own corpus, into a gitignored directory on
its own disk. It matters if that ever stops being true — a restored backup, an artifact copied
between machines, a CI runner that fetches a prebuilt index.

**How it was found.** The adversarial security review of the 2026-09-16 integrity work
(`gemini-3.8-flash-high`) rated it HIGH; `gpt-5.6-sol` independently flagged the same ordering.
A web-research pass then found the supporting precedent: seven picklescan bypass CVEs during
2025 (Sonatype's four, JFrog's three at CVSS 9.3), malicious models served live on Hugging Face,
and `CVE-2025-32434`, which defeated PyTorch's own `weights_only=True` mitigation.

**What fixing it would disturb.** The two halves are not equal. `tfidf_matrix.pkl` is nearly
free to move — `scipy.sparse.save_npz`/`load_npz` is a plain, non-executable format, and the
matrix is the larger file. `tfidf_vectorizer.pkl` is the awkward one: `TfidfVectorizer.idf_` is
a read-only property with no setter, so a non-pickle round trip means extracting `vocabulary_`
and `idf_` and reconstructing the object by hand — [documented since
2015](https://thiagomarzagao.com/2015/12/08/saving-TfidfVectorizer-without-pickles/) and still
true. `safetensors` cannot hold either object; it stores tensors, not Python object graphs.
Changing the format also changes `REQUIRED_ARTIFACTS`, so every existing build stops loading and
the corpus must be rebuilt — which is the real cost, and the reason this did not ride along with
the fail-closed change. **Note what is _not_ the answer:** a SHA-256 recorded beside the artifact
it vouches for. That was the original plan and it was dropped; it gives corruption detection, not
tamper resistance, because a writer who can replace the pickle can rewrite the manifest.
[scikit-learn's own persistence guidance](https://scikit-learn.org/stable/model_persistence.html)
does not mention hashing at all — it says load only from a trusted source, or change format.

### Nothing ever deletes an old search build

**Where:** `web/services/build_registry.py` — `new_build_id` mints a fresh directory per run and
no code path removes one. `web/processed_data/builds/` holds 16 on the development machine.

**What is wrong.** Builds accumulate without bound. Eight of the sixteen here are **failed
runs**: they contain `chunks_data.csv` and both TF-IDF pickles but no FAISS index and no
manifest, so they died inside `_create_faiss_index` and left their partial output behind. Two of
those failures (`20260808T175236248701Z`, `20260808T184831545766Z`) are newer than the active
build, so the directory listing reads as though the corpus moved on when it did not.

**Who it reaches.** Nobody yet. Each complete build is about 27 MB, so sixteen is roughly 400 MB
on a VPS nobody is watching the disk of.

**How it was found.** Counted while verifying a claim about manifest coverage during the
2026-09-16 integrity work, then checked against practice: Capistrano and Deployer default to
keeping 3–5 releases and Uber's index blue/green keeps exactly 2.

**What fixing it would disturb.** The number is the easy part; the cleanup step is where the real
incidents are. [Capistrano #1907](https://github.com/capistrano/capistrano/issues/1907) deleted
the oldest _good_ release while a newer failed one survived, and
[Deployer #1004](https://github.com/deployphp/deployer/issues/1004) had its `keep_releases` limit
silently fail to enforce itself. Both are the failure this repo already names: a guard that
cannot fire. So a retention cap needs a test that proves the cap actually fires, it must never
delete the active build, and it should probably treat a manifest-less partial directory as
garbage collectable immediately rather than counting it as one of the N kept. Note also that
`activate` is the rollback tool, so any cap sets a hard floor on how far back a rollback can go.

### `IndexFlatL2` shifts every id above a deleted vector

**Where:** `web/services/data_processing.py:466` — `index.add(embeddings_array)` is the only
FAISS mutation in the repository, and it only ever writes into a freshly-created build directory.

**What is wrong.** Nothing, today, and that is the entire point of writing it down. FAISS
documents that for sequential indexes — `IndexFlat`, `IndexPQ`, `IndexLSH` — [removal "shifts
the ids of vectors above the removed vector
id"](https://github.com/facebookresearch/faiss/wiki/Special-operations-on-indexes). Delete row 5
of 1000 and rows 6–1000 silently become 5–999, while the DataFrame keeps its own numbering. The
row-count check cannot see it, because both stores can legitimately end up the same length.

**Who it reaches.** Nobody, because this app never deletes or updates a vector: every ingest is a
full rebuild into a new directory. It reaches every reader on the day that stops being true.

**How it was found.** A web-research pass over real incidents during the 2026-09-16 integrity
work. This exact mechanism produced
[mem0 #3246](https://github.com/mem0ai/mem0/issues/3246) and
[#3787](https://github.com/mem0ai/mem0/issues/3787),
[Haystack #6228](https://github.com/deepset-ai/haystack/issues/6228),
[LangChain #9019](https://github.com/langchain-ai/langchain/issues/9019), and FAISS's own
[#255](https://github.com/facebookresearch/faiss/issues/255) — in every case triggered by an
in-place delete or partial add, never by a clean rebuild. Worth knowing that LangChain's own
FAISS wrapper uses the same positional coupling this repo does, which is why the bug keeps
recurring there.

**What fixing it would disturb.** **Any commit that adds incremental delete or update to the
index must ship stable ids in the same commit** — `IndexIDMap2` with `add_with_ids`, keyed on the
existing namespaced `chunk_id`, or mem0's shipped answer of reconstructing every surviving
vector and rebuilding from scratch. Note that `IndexIDMap` had [its own desync
bug](https://github.com/facebookresearch/faiss/issues/255) on add→remove→add, so it is not free
either. Adding ids also means the TF-IDF matrix needs the same treatment, since it is positionally
bound too. Doing it speculatively now would be machinery guarding a code path that does not
exist; the trigger is what matters.

---

## Planned work

### Confirm on the live site that chat streaming arrives token by token

**Where:** the live production site (`POST /api/chat/stream` behind nginx).

**What is wrong.** After the 2026-09-12 production restart, no human has directly
verified on the live site that a chat answer still arrives token-by-token rather
than buffering into a single block. Nothing in the configuration changes should
have altered it — `web/services/sse.py` sets `X-Accel-Buffering: no` (which stops
nginx from buffering), the nginx vhost sets no conflicting `proxy_buffering`,
and production logs show incremental chunk delivery — but it has not been
observed firsthand by a reader.

**Who it reaches.** Any signed-in or anonymous reader asking a question in chat
on production. If buffering occurred, the token-by-token stream would stall and
dump the complete text at the end.

**How it was found.** Lifted out of `docs/archive/TODO-resolved.md` (finding F10 in
`docs/archive/2026-09-12_worker-count-guard.md`). The entry was resolved and archived, but
left an unresolved verification instruction that belongs in active tracking.

**What fixing it would disturb.** No code changes. A human logs in, asks a question
on the production site, and confirms visually that tokens stream incrementally.
Once confirmed, this entry can be closed and moved to `docs/archive/TODO-resolved.md`.

### `POST /auth/login` is a 410 tombstone pending deletion

**Where:** `login()` at `web/api/auth.py:316-356` — the tombstone itself, which is
what the remaining work deletes — plus the test that pins it,
`test_login_route_is_a_gone_tombstone` at `web/tests/test_auth_routes.py:285-321`.
For context: `web/api/app.py:2318` registers `auth_bp` with no limiter, while
`recover_bp` and `signup_bp` get one immediately after (`:2324-2336`).

**What is wrong.** This entry's original title was false: the route was never
unlimited — with no explicit limit it inherited the global defaults (200/day,
50/hour, 10/minute per IP) all along. The real defect was worse than a missing
limit: the route forwarded unauthenticated credentials to GoTrue's `/token`
from this host's single address, blinding GoTrue's own per-IP limiter to the
attacker's real address, while answering with distinguishable refusal bodies.
What shipped is a one-release `410 Gone` tombstone answering
`{"error": "endpoint_removed"}` without reading the request body or calling
GoTrue — a tombstone rather than a deletion because no in-tree caller exists
(the browser signs in browser-direct) but an out-of-tree client cannot be
ruled out from the repository alone. Nothing in the UI ever called it —
`Services.login` goes browser-direct — which is why the route attracted no
attention for a year, and why the module comment above it was left describing
a logout exemption that never existed.

**Who it reaches.** Nobody through the UI. Anyone who can reach the public API.

**How it was found.** The 2026-09-05 review pass, as an aside to the logout finding
([the archived plan](docs/archive/2026-09-05_review-findings-fix.md), finding 1).
The "unlimited" premise was corrected by measurement in
`docs/auth-login-rate-limit-plan.md` §0.

**What fixing it would disturb.** Deleting `login()` and its route entry outright,
plus the tombstone test that pins the 410 — that test must go with the route, or it
fails on a green tree. The plan document (`docs/auth-login-rate-limit-plan.md`) is
then archived per the closing procedure at the bottom of this file, with its
still-open items (C1, C2, C3 and the password-spraying note) lifted back here as
their own entries **first** — the archive is excluded from search, so anything left
inside that document at archiving time disappears.

**Update 2026-09-09 — the tombstone landed; the deletion did not.** `login()` now
answers `410 {"error": "endpoint_removed"}` under both `GET` and `POST`, reads no
request body, and calls nothing. It logs one bounded `warning` per call naming the
method, address and user agent: **that log is the whole point of the release.** The
route was tombstoned rather than deleted only because the production access log
could not be consulted, so an out-of-tree caller could not be ruled out — and a
tombstone that records nothing would end the release knowing exactly as much as a
deletion would have. Read that log before deleting: silence is the evidence to
delete on, and a hit is a caller to find first.

Also landed: the module comment claiming a logout exemption that never existed is
gone (logout keeps the global defaults, and one sign-out press spends two of them —
`Services.logout` and `clearSessionState` each POST to `/auth/logout`; _corrected
2026-09-11: it was three, because `clearSessionState` ran twice; fixed 2026-09-12 to one
per press, plus one per other open chat tab on a broadcast sign-out — see
the closed "One logout-button press sends `POST /auth/logout` three times" entry in
[`docs/archive/TODO-resolved.md`](docs/archive/TODO-resolved.md)_), and
`web/tests/test_auth.py` was deleted whole. **That deletion left the `integration`
pytest marker with no users at all** — `pytest.ini:6` still defines it and
`CLAUDE.md` still tells contributors to run those tests by hand, so
`pytest -m integration` now collects nothing. The two tests were genuinely stale
(they hit port 5000 and asserted a top-level `access_token` the route stopped
returning long ago), but one of them was the only end-to-end check that a real
bearer token is accepted by `/api/chat`. Nothing replaces it.

---

### Answer from a second provider — and why the code is the easy half

**Where:** `web/services/openai_app.py` builds one `OpenAI(api_key=...)` client
in `__init__` and calls `client.chat.completions.create(...)`. The model
allowlist lives in `web/config.yaml` under `openai.allowed_models`, and each
entry already describes that model's parameter contract (`token_param`,
`supports_temperature`, `reasoning_efforts`) because the OpenAI families do not
share one. `web/services/settings_service.py` validates a selection against
that list; `apply_generation_settings` in `web/api/app.py` builds a replacement
handler and swaps it.

**Why it is wanted.** Much cheaper models exist and some are free. DeepSeek V4
Flash is roughly $0.14/$0.28 per 1M tokens against gpt-4o-mini's $0.15/$0.60;
NVIDIA's Nemotron 3.5 Lightning is about $0.05/$0.20 on DeepInfra and free on
`build.nvidia.com`. For a project that is also a demonstration piece, being able
to fail over to a free model when a key runs dry has obvious value.

**The integration is genuinely small.** Both are OpenAI-SDK drop-ins: DeepSeek
at `https://api.deepseek.com` (models `deepseek-v4-flash`, `deepseek-v4-pro` —
note `deepseek-chat` was deprecated 2026-07-24), NVIDIA at
`https://integrate.api.nvidia.com/v1` (`nvidia/nemotron-3.5-lightning-30b-a3b`).
An allowlist entry would gain `provider`, and the handler would pick a
`base_url` and an API key per provider. Perhaps an afternoon.

**What it would disturb — and this is the actual cost.** PRODUCT.md's first
principle is that provenance is the product: "An answer without a resolvable
source is a liability, not a feature." `BASE_SYSTEM_MESSAGE` in
`openai_app.py:35-59` is tuned so that every claim carries a `[n]` marker, no
number is ever invented, and a refusal carries no markers at all. The API
decides whether an answer gets a source panel by counting those markers
(`extract_cited_indices`), so a model that follows those instructions _less
reliably_ does not fail loudly — it produces a confident answer with citations
that do not support it, on a regulatory question, for a professional who will
quote it to an auditor.

**So the prerequisite is a citation-fidelity harness, not the client change.**
`scripts/eval_retrieval.py` and `web/tests/data/retrieval_eval.yaml` measure
retrieval, not whether the model cites what it actually used. Something has to
answer, per model: what share of factual sentences carry a marker; how often a
marker points at a passage that does not support the sentence; and whether a
refusal stays clean. Without that, switching providers is a change to the
product's central claim made on the basis of price.

**Update 2026-08-22 — the harness exists now; the gate has not been run for
real yet.** Built from an implementation plan that two independent read-only
adversarial reviews (OpenCode, `gpt-5.6-terra` and `gpt-5.6-luna`, no repo
edits) debated before a line of code was written — both found and the plan
was corrected for real defects in the first draft: a `base_url` constructor
snippet that would have raised on every ordinary call (`settings` was
normalized _after_ the client was built, not before), an Arabic HHEM-scoring
assumption with no evidence behind it, arbitrary gate thresholds with no
sample-size reasoning, and a redundant addendum this file did not need. The
same "debate the plan before building it" pattern this file already records
for the `chat_load_session` fix above.

What shipped: `web/services/citations.py` gained `CitationDiagnostics` /
`extract_citation_diagnostics` — the invalid-marker count
`extract_cited_indices` always computed internally but only ever logged
(`citations.py:345-352`) is now a returnable, aggregable number, with
`extract_cited_indices` itself unchanged as a thin wrapper over it.
`web/services/citation_eval_metrics.py` is Layer 1 (citation _format_, not
fidelity — coverage, hallucination rate, refusal cleanliness scoped to
labelled probes, cross-turn leakage) with a gate that combines an absolute
floor with a minimum-sample-size guard, specifically so a ten-probe smoke
run cannot masquerade as evidence for a two-percentage-point claim, and a
`baseline_fails_floor` state so an already-broken baseline can never
legitimize an equally broken challenger. `web/services/citation_fidelity.py`
is Layer 2 — Vectara HHEM, **English only** (the open checkpoint's model
card documents English; Arabic cross-lingual support is a claimed advantage
of the commercial HHEM-2.3, not this one), never imported from the request
path. `scripts/eval_citations.py` is the driver, mirroring
`eval_retrieval.py`'s load → run → report shape (single-pass, no cache — an
earlier description of this as a "cache once, evaluate cheaply" split was
wrong; `eval_retrieval.py` doesn't do that either). `web/tests/data/
citation_eval.yaml` is the probe set — `pair_id`-linked EN/AR pairs, a
`refusal` group with ground-truth `expected_refusal` tags, fixed (not
runtime-generated) cross-turn and legacy-format history so every candidate
model sees identical injected history, and `multi_source`/`numeric_claims`/
`conflicting_guidance`/`adversarial` groups that feed the Layer-3 pilot
rather than an automated gate. `citation_eval_candidates.yaml` lists
DeepSeek/NVIDIA/OpenRouter candidates, deliberately kept out of
`config.yaml`'s real `allowed_models` until a model actually clears the
gate. `OpenAIHandler.__init__` gained an inert `base_url` / `api_key_env` /
`model_contract` override — `base_url` defaults to `None`, `api_key_env`
defaults to `OPENAI_API_KEY`, and nothing in `config.yaml` or
`settings_service.py`'s `GENERATION_KEYS` can reach any of the three, so
every existing production call is byte-for-byte unchanged; covered by a
dedicated constructor-equivalence test
(`web/tests/test_openai_handler_provider_config.py`).
`docs/citation-eval-judge-protocol.md` is Layer 3's adjudication rubric —
scoped to a small pilot of the curated `judge: true` subset first, not the
100–300-probe scale the first draft of this plan assumed before anyone had
timed how long adjudication actually takes.

73 new tests (68 across four new files, 5 added to `test_citations.py`),
every one of them offline — stub NLI scorers, mocked handlers and search
engines, no real HHEM download and no real OpenAI call anywhere in CI —
plus the existing 626-test non-browser/non-integration suite still green
against these changes.

**What this does NOT do yet.** Nobody has run `scripts/eval_citations.py`
against the real API — there is no baseline number, and neither this entry
nor the OpenRouter one below is unblocked by this update. That run costs
real money, same posture as `smoke_real.py` ("run it by hand"), and is
deliberately not something to trigger without asking first. Running it,
reading the gate report, and — only if it passes — migrating a candidate
from `citation_eval_candidates.yaml` into `config.yaml`'s real
`allowed_models` is the remaining work.

Two smaller consequences: `tiktoken` does not apply to a non-OpenAI model, so
`tokenizer_exact` is permanently False and logged token counts stop meaning
much; and cost metadata becomes per-provider rather than per-model.

**Open questions.** Whether a second provider is a per-instance choice or a
per-request fallback when the primary errors. Whether the Arabic half holds —
the corpus is bilingual and a cheaper model's Arabic regulatory register is a
separate question from its English one, which the harness has to measure in both.

---

### OpenRouter as one integration instead of several

**Where:** the same seam as the entry above.

**Why it is wanted.** It subsumes that work rather than competing with it. One
OpenAI-compatible endpoint (`https://openrouter.ai/api/v1`), one key, and model
ids of the form `deepseek/deepseek-v4-flash` or
`nvidia/nemotron-3.5-lightning:free` — so DeepSeek, Nemotron and a few hundred
others arrive together, including a free tier. Optional `HTTP-Referer` and
`X-Title` headers attribute usage. Compared with wiring each provider
separately, this is one `base_url`, one secret, and an allowlist that can grow
without code.

**Update 2026-08-22.** The harness this entry and the one above share as a
prerequisite now exists — see the update in "Answer from a second provider"
above for what shipped. Not yet run for real, so this entry stays open too.

**What it would disturb.** Everything in the entry above still applies — the
citation-fidelity question is about the _model_, and routing through OpenRouter
does not answer it. Three things are specific to the aggregator:

- **A router is not a model.** The same id can be served by different providers
  with different quantisation and context handling, so behaviour can move
  without the id changing. `provider.order` / `allow_fallbacks` pin it; unpinned,
  the thing the harness measured is not necessarily the thing that answers.
- **Free tiers carry their own limits** — roughly 50 requests/day, and 20/minute
  on `:free` variants at the time of writing. That is below this app's own
  15/minute chat limit, so a free model would need the quota work to know about
  a _provider_ ceiling as well as a per-reader one.
- **A third party sees the prompts.** Every question includes retrieved SFDA
  passages and the reader's own words. Sending those to an aggregator that
  routes to an undisclosed provider is a disclosure decision, not a technical
  one, and it belongs with whoever owns the deployment — the same conversation
  as the conversation-persistence privacy posture.

**Open questions.** Whether OpenRouter replaces the direct OpenAI client or sits
beside it as a second provider — keeping the direct path means the primary model
never depends on a third party's uptime. And whether free models are usable at
all given the rate limits, or whether their real role is a demonstration of
failover rather than a way to serve readers.

### Refactor the profile page

**Update 2026-09-18.** One of the three remaining items — the `disabled`/consent question —
was decided and built; see its own entry. The account-menu consolidation and the monogram
view-transition are untouched and remain appetite-only.

> **Everything between here and the 2026-08-23 update is pre-work material from
> 2026-08-17, and is now historical.** File paths, line numbers and named tests in it
> predate the refactor; many have moved and some no longer exist at all —
> `test_profile_theme_integration.py`, referenced repeatedly below, was deleted when
> `/account` replaced the modal. It is kept because it records what the work had to
> reach, which is the cost this entry exists to state. **For what is actually true
> now, skip to the 2026-08-23 update.**

**Where (as of 2026-08-17):** All of it lives browser-side; there is no Flask route
and no server-rendered profile page. `handleProfileButtonClick` and
`handleProfileFormSubmit` in `static/js/modules/handlers.js` (lines 611-681);
`populateProfileForm` in `static/js/modules/ui.js` (~line 611); `getProfile` and
`updateProfile` in `static/js/modules/services.js` (lines 299-318), speaking
straight to Supabase's `profiles` table; `handleAuthFormSubmit` (signup leg)
in `handlers.js:164-200` and `Services.signup` in `services.js:277-282`; the
`#signup-pane` and `#profileModal` forms in `web/templates/index.html` (lines
228-258 and 271-321); `handle_new_user` trigger and `admin_update_profile` RPC
in `supabase/migrations/`; `loadProfileWithTimeout` in `static/js/app.js` (lines
29-49), fed by `API_TIMEOUT` / `RETRY_MAX_ATTEMPTS` / `RETRY_DELAY_INITIAL` in
`static/js/modules/config.js`; the two `profile-button*` triggers in
`web/templates/partials/_sidebar.html` (lines 59-62); and
`AppState.state.userProfile` in `static/js/modules/state.js`. The catalogue
already carries `runtime.profile.*` keys (`loadFailed`, `saveFailed`, `saved`)
in both `web/i18n/en.yaml` and `web/i18n/ar.yaml` — no JS module reads them.

**Why it is wanted.** Three things converge on this surface:

1. **Identity fields need structuring.** `full_name` is currently a single
   free-text field that gives no clean way to address readers politely or sort
   by family name. It wants a split into `first_name` and `family_name`. In
   addition, collecting numeric `age` provides demographic context for
   regulatory queries without requiring sensitive birthdates.
2. **Registration captures nothing today.** Signup takes only email and password,
   leaving `profiles` initialised with empty strings for everything else until
   someone finds the profile modal. Capturing `first_name`, `family_name`, and
   `age` during signup passes them via user metadata into `handle_new_user`, so
   an account starts with real identity data.
3. **The profile modal strains in visible ways.** The form is seeded from the
   _startup snapshot_: `loadProfileWithTimeout` fills `AppState.userProfile` once
   at sign-in (`static/js/app.js:207`), and `handleProfileButtonClick` only calls
   `Services.getProfile` on a cache miss (handlers.js:655-678) — so the modal
   shows whatever the page captured on load, never a fresh read. The theme radios
   never reflect the stored preference: both `populateProfileForm` (ui.js:625)
   and the empty-profile reset (handlers.js:895) check `ThemeManager.getCurrent()`
   — the live `data-bs-theme` attribute — not `profile.preferences.theme`, so a
   reader who saved Dark is shown their _current_ theme, not their saved one. And
   the surface is silently English-only while the `runtime.profile.*` keys
   written for exactly this sit unused.

**Two live bugs to fix while you are in here.** Both are shipped today, both
were confirmed by reading the code, and neither has a test that would catch it —
which is why they are written out rather than left in the prose above.

1. **The theme radios ignore the saved preference.** `populateProfileForm`
   (`static/js/modules/ui.js:625`) and the empty-profile reset
   (`static/js/modules/handlers.js:895`) both select the radio matching
   `ThemeManager.getCurrent()` — the live `data-bs-theme` attribute — rather
   than `profile.preferences.theme`. Save Dark, switch to Light, reopen the
   modal: it shows Light, and saving from there silently overwrites the stored
   preference with the current one. Neither test in
   `test_profile_theme_integration.py` asserts which radio is _selected_:
   `test_profile_form_loads_cached_profile` opens the modal but checks only the
   name and organization fields, and `test_profile_update_applies_and_persists_theme`
   saves and never reopens it. The gap is the read-back, so that is where the
   new test goes.

2. **Every profile string is hardcoded English.** Five call sites in
   `static/js/modules/handlers.js` — 841, 862, 866, 877 and 901 — pass literals
   to `showProfileError`/`showToast`, while
   `runtime.profile.{loadFailed,saveFailed,saved}` sit in _both_
   `web/i18n/en.yaml` and `web/i18n/ar.yaml` and are read by no module. An
   Arabic reader gets English on this one surface.
   `test_arabic_catalogue_covers_every_runtime_key` cannot catch this: it
   checks that Arabic has every key English has, and both catalogues have
   these — they are simply never used. Note there are five sites and only
   three keys, so translating them is not a one-to-one mapping; the session-
   expired (841) and save-failure (866) messages need keys that do not exist
   yet.

**Update 2026-08-17 — both live bugs fixed; the rest of this entry (identity
field restructuring, signup capture, modal-vs-page) is still open.** The
theme radio now reads `profile.preferences.theme` via a shared
`UI.selectThemeRadio(form, profile)` helper (`static/js/modules/ui.js`),
called from both `populateProfileForm` and the empty-profile reset in
`handlers.js` rather than patched at each call site separately — the second
site had no saved value to read (a genuinely profile-less account) so was
never independently buggy, but shared the same fragile pattern. All 5
hardcoded call sites now draw from `runtime.profile.*`: two new keys,
`sessionExpired` and `loginRequired`, joined the three that already existed
unused; the save-failure site (866) stopped interpolating the raw
`error.message` into the reader-facing string at all — untranslatable and a
minor detail leak — logging it via the existing `logError` pattern instead.
Covered by a new theme-selection browser test in
`test_profile_theme_integration.py` (the read-back gap this entry itself
named) and `test_profile_flow_uses_the_i18n_catalogue_not_literals`
(`web/tests/test_frontend_architecture.py`), which pins each call site to
its i18n key and would fail on a reverted literal.

**What it would disturb.** Every profile behaviour is pinned by tests that name
it. `web/tests/test_profile_theme_integration.py` runs three browser tests —
cached form fill, theme-persists-through-save, and the `updateProfile` /
`getProfile` wire contract (`test_profile_service_contracts`) — entirely against
the `SUPABASE_BROWSER_MOCK` `from('profiles')` chain in
`web/tests/conftest.py`, a chain that currently asserts the
`{id, full_name, organization, specialization, preferences}` shape. Changing
`public.profiles` to replace `full_name` with `first_name`, `family_name`, and
`age` requires migrating existing rows, updating `admin_update_profile` and
`handle_new_user`, and adjusting the admin account detail view that reads
profile columns. `test_frontend_architecture.py::test_handlers_own_user_facing_service_failures`
pins that `ErrorHandler.showProfileError` stays in `handlers.js`.

**Update 2026-08-23 — most of this shipped; three items remain, all blocked on
something that is not code.** Superseded by the full design in
`docs/archive/2026-08-23_profile-refactor.md`, produced and built across two passes:

- **Identity split.** `full_name` is now a stored generated column over new
  `first_name`/`family_name`/`age` columns
  (`supabase/migrations/20260822225415_profile_identity_atomic_cutover.sql`).
  All 4 live rows preserved byte-for-byte (legacy display names copied
  verbatim into `first_name`, `family_name` left explicitly null — see that
  migration and the plan's §15.2 for why a mechanical name split was
  rejected). `handle_new_user` and `admin_update_profile` both rewritten;
  `admin_get_user` extended (`20260822225623`) to expose the new columns to
  the console's own edit form (`static/js/admin/ui.js`).
- **Modal retired; `/account` built.** `#profileModal` is gone —
  `web/api/account.py` (new blueprint), `web/templates/account.html`,
  `static/js/account/{ui,handlers}.js` and `static/css/account.css` ship
  the record's Identity and Preferences sections (theme + language,
  instant-apply; identity, explicit-save with dirty tracking), the monogram,
  and the standing line (role/tier/since/conversation-count/standing) via a
  new `public.get_identity_flags(uuid)` RPC and `/api/identity`'s now-wider
  response. `.sidebar-account`'s profile button is a plain link to it.
- **Preferences merge RPC** shipped (`public.update_own_preferences(jsonb)`,
  `20260822225239`) so the theme/language controls above cannot clobber each
  other's stored preference the way the old modal's whole-object upsert
  could have. Not yet wired into the identity form's organization/
  specialization save, which still upserts — those two columns are not JSON,
  so nothing is at risk there today.
- **Signup capture, first-run, and search scope** shipped (Step 4):
  `first_name`/`family_name` on the signup form passed as `options.data`
  (`test_signup_identity_capture.py`), the completion strip queued through a
  notice coordinator rather than suppressed by inspecting `#history-notice`
  (`test_profile_completion_notice.py`), and search scope as a reversible
  preference defaulting to `all` (`test_search_scope_preference.py`).
- **Security** shipped (Step 5): password change via GoTrue `reauthenticate()`
  - `updateUser({ nonce, password })`, email change, and "sign out everywhere
    else" via `signOut({ scope: 'others' })` — there is no session-listing
    endpoint in the API and there cannot be a session list
    (`test_account_security.py`).
- **Export and bulk conversation deletion** shipped (Step 7):
  `GET /account/api/export` streams NDJSON scoped from `g.identity`, never
  from anything the caller supplies; `DELETE /account/api/conversations` is
  named distinctly from account deletion and refuses with 409 while any of
  the owner's conversations is mid-generation
  (`test_account_data_rights.py`, `test_chat_store_export.py`). Note the
  routes live at `/account/api/*`, following `admin.py`'s established
  `<blueprint-prefix>/api/<thing>` convention rather than the plan's §4
  shorthand of `/api/account/*`.

**Still open — two items, each blocked on a decision or a document, not on
engineering.** Each has its own entry below rather than living only here:

- Bilingual GoTrue email templates — see _Security email is English-only_.
- Account deletion (Step 7) — see _Account deletion (Spec 4)_.

**Consent (Step 6) shipped 2026-08-23**, unblocked by publishing `/privacy` as an
openly-labelled draft rather than by waiting for reviewed text. The review that is
still owed is tracked separately — see _The privacy policy (/privacy) is a draft_.

Also deferred, and not blocked on anything but appetite: full account-menu
consolidation (the sidebar footer collapsing to one control, per Decision 1),
and the monogram `view-transition-name` cross-document transition — the latter
needs a media-query-scoped assignment across `_sidebar.html`'s two rendered
copies that was not safe to ship in this pass (see that partial's own comment).

`test_frontend.py::test_login_and_logout_flow` asserts `#profile-button` is
visible after sign-in. Any new `page.*` or `runtime.*` strings must ship in both
YAML files (`test_arabic_catalogue_covers_every_runtime_key` fails if Arabic
lags) and any new CSS must use logical properties
(`web/tests/test_css_contract.py`); any commit touching CSS or JS bumps
`ASSET_VERSION` in `web/api/app.py`.

**Open question that remains.** For the future newsletter plan: when integrating
Beehiiv, should the opt-in checkbox live in `preferences.newsletter` on
`public.profiles` and sync via a server-side webhook/background worker, or sync
directly at signup/profile save? The modal-vs-page and browser-vs-Flask
questions this entry used to carry are both answered — Decisions 1 and 8 of the
archived plan.

### The shipped daily allowance is a placeholder number, not a measured one

**Where:** `public.tiers`, both seeded rows — `free` and `staff` are each 200 a day; the
same number is `server.quota.daily_messages_default` in `web/config.yaml`.

**What is wrong.** 200 was chosen to sit well above observed usage so the meter could be
switched on and watched before it was tightened, not because anybody measured what a
reader needs. A quota nobody ever reaches is a quota that has not been set; it costs the
same to run as a real one and buys none of the protection. Two tiers holding the identical
number also means the tier mechanism is, today, doing nothing an operator can see.

**Who it reaches.** Nobody yet — that is the point. It reaches whoever is first to hit a
number chosen without evidence, on the day somebody finally lowers it.

**How it was found.** Recorded as a deliberate open decision when the feature was built
(owner decision, 2026-09-03), in the archived plan's §13.

**What fixing it would disturb.** Nothing in code: both levels are console edits, and
raising `staff` above `free` is a form submission, not a migration. What it needs is a
month of `usage_daily` rows and somebody willing to own the number. The one code-side
cost is `test_quota.py::test_seed_matches_shipped_default`, which pins both seeded rows to
the single `config.yaml` key and will fail the moment the two tiers are meant to differ —
by design, so that differentiating them is a conscious edit to the test as well.

### The daily-allowance claim is not idempotent, and one future commit would make that matter

**Where:** `chat_claim_daily_message` in
`supabase/migrations/20260903195102_reader_quota_claim_release_and_read_rpcs.sql`, and its
callers `_claim_daily_message` / `_release_daily_message` in `web/api/app.py`.

**What is wrong.** The claim carries no request id, so a replay charges twice.
`chat_append_turn` is idempotent against `client_request_id`; the claim is not. This is
safe **today** only because the browser mints a fresh id per submission and there is no
client-side chat retry path at all. It is a latent contradiction, not a theoretical one:
`app.py`'s own validator comment and `_InFlightGenerations`' docstring both describe
`client_request_id` as "reused across retries", which is exactly the usage that would break
this.

**Who it reaches.** No reader today. On the day a retry path is added, it reaches any
reader whose connection drops after the model answered: they are charged twice for one
answer the database quietly refuses to store twice.

**How it was found.** A review round during the build (archived plan, third review),
which also established that the obvious cheap fix does not work.

**What fixing it would disturb.** **Any commit that adds a client-side retry reusing
`client_request_id` must ship claim idempotency in the same commit.** A
`last_claim_request_id` column is not sufficient — one slot per `(user, day)` catches only
an immediately consecutive replay. It needs the per-claim ledger shape designed in §12 of
[`the archived plan`](docs/archive/2026-09-04_reader-quota.md), which is a second table, a second write inside the
atomic claim, and a bucket-tagged refund.

### A fixed promo pool of bonus messages, designed and deliberately not built

**Where:** Designed in full in §12 of [`the archived reader-quota plan`](docs/archive/2026-09-04_reader-quota.md),
including its corrected `42P17` immutable-predicate index bug and the "a zero daily limit
blocks the grant too" rule.

**What is wrong.** Nothing is wrong; this is wanted, not broken. A pool of N bonus
messages drawn once the daily allowance is spent is the natural next lever after a
per-day number, and it is the shape that also solves claim idempotency above.

**Who it reaches.** Nobody yet. It matters first for whoever needs to hand one reader extra
capacity for a fixed total rather than a fixed rate — the conference-week case the windowed
override half-covers.

**How it was found.** Brainstormed with the owner during the build, worked through to a
complete schema, then parked by owner decision on 2026-09-03: the daily allowance covers
most of the same need, and the pool needs real usage data to justify its second table.

**What fixing it would disturb.** A second table, a second atomic path inside
`chat_claim_daily_message`, a bucket-tagged refund so a failure returns the message to the
bucket it came from, and a second counter on the reader surface. It also reopens the
notice copy, which currently says one thing about one allowance.

### `/api/identity` makes three RPC round trips where one would do

**Where:** `web/api/app.py`'s `/api/identity` route — `touch_last_seen`,
`get_identity_flags` and `get_reader_quota`, called in sequence.

**What is wrong.** Three round trips to answer one question, on a route called once per
sign-in and once per page load. Not a correctness issue; a real and easily-measured
optimisation that has simply not been taken.

**Who it reaches.** Every signed-in reader, once per load, at whatever the round-trip
latency to Supabase is. Invisible at the current scale.

**How it was found.** Noted while building the quota feature, which added the third call.

**What fixing it would disturb.** `20260822231726` deliberately **narrowed**
`get_identity_flags` to the columns the hot path needs. Widening it again to absorb the
other two reopens that decision, so this is not a mechanical merge — it is a request to
revisit a scoping choice that was made on purpose, and it should be argued on its own
terms rather than folded in as a performance tidy-up.

### Every candidate's TF-IDF cosine is computed twice per question

**Where:** `LexicalSearcher.search` (`web/services/lexical_searcher.py:71-72`) scores the query
against the whole matrix and keeps the top _k_; `ResultCombiner._compute_lexical_scores`
(`web/services/result_combiner.py:219-228`) then transforms the same query again and re-scores
the candidate union. Both are reached from `SearchEngine.search`
(`web/services/search_engine.py:296-310`), fourteen lines apart, with the same `lexical_query`.

**What is wrong.** Nothing incorrect — the two agree, and the second call exists for a real
reason. `search` has already computed every chunk's similarity and discarded all but _k_; the
combiner then pays for a second `transform()` and a second cosine to recover numbers that were
in hand a moment earlier. It cannot simply read the returned top-_k_ instead, because the union
also contains semantic-only candidates the lexical leg never returned and which therefore have
no score yet. The full similarity array would answer both; the top-_k_ list answers only half.

**Who it reaches.** Every question, at a cost nobody can perceive. Measured against the live
build's 4545×5000 matrix with a representative registration query and a 30-candidate union:
`transform()` 186 µs plus 376 µs for the slice cosine, so **561 µs per question** would
disappear. For scale, the full-corpus cosine `search` already pays is 8.0 ms, and the model call
downstream is three orders of magnitude larger again. _(An earlier pass put this at 795 µs;
561 µs is the re-measured figure — the 30-row slice is cheaper than that estimate assumed.)_

**How it was found.** `/code-review` over the uncommitted combiner work on 2026-09-16, and
deliberately left out of `4b35351`: that commit was a correctness fix, and this one changes a
public return contract.

**What fixing it would disturb.** `LexicalSearcher.search` returns a `list[dict]` of the top _k_.
The fix is to hand back the full `similarities` array as well, so the combiner indexes into it
instead of recomputing — which changes that method's signature, `SearchEngine.search`'s call
site, and `web/tests/test_retrieval_failures.py`, the only file that constructs a
`LexicalSearcher` directly. It also couples two components that are independent today: the
combiner would need a defined behaviour for a caller that supplies no array — every test in
`test_result_combiner.py` constructs a `ResultCombiner` directly and hands `combine()` candidate
lists built by hand, with no searcher anywhere, and `search_engine.py:418` is the only place in
production that builds one. So the array has to be optional and the recompute has to survive as
the fallback, which means the duplicated code does not actually go away; it just stops running on
the hot path. That is a real design decision in exchange for 561 µs, which is why this is
recorded rather than done. _(An earlier draft of this entry also named the citation-fidelity
harness as a hand-built caller. That was wrong — `scripts/eval_citations.py:151-172` either calls
`engine.search()` or constructs `SearchResult` objects directly, and never reaches
`ResultCombiner.combine` at all.)_

### LOG_LEVEL works only because of import order, and nothing protects that

**Where:** `web/api/app.py:147-174` — the `if not logging.getLogger().handlers:` guard around
`basicConfig(level=LOG_LEVEL, format=...)`. The imports that would install a root handler and
make that guard false — `web/utils/config_loader.py`, whose module-level `logging.warning(...)`
makes Python install a root handler implicitly — is imported at `:259`, below it.

**What is wrong.** Nothing, today, and this entry is a correction of one that claimed otherwise.
**It previously read "LOG_LEVEL is silently ignored", which was wrong.** That was measured by
importing `config_loader` alone, which does install a root handler and does make the guard fail —
but that is the CLI's import order, not the app's. Under `gunicorn --preload` the guard passes,
because gunicorn hangs its handlers off `gunicorn.error` rather than root and every in-app import
that would poison root happens afterwards. Measured on the VPS on 2026-09-18 by booting a spare
worker with `LOG_LEVEL=WARNING`: it dropped `Loaded .env` (`app.py:163`, a `web.api.app` record
with no explicit level, so purely root-gated) which appears six times in the live journal at the
default. One variable changed, the knob moved.

What is left is the fragility. The configuration is correct by accident of import order, not by
construction. Moving any import above line 147, or adding a top-level one that reaches
`config_loader`, turns `LOG_LEVEL` off across the whole app — silently, with no error, no failing
test, and no symptom except that the logs a future incident depends on are quieter than the
operator believes.

**Update 2026-09-18 — the loaded gun is gone; the fragility is not.** `openai_app.py` also
carried a bare module-level `basicConfig`, which would have configured root at INFO and disabled
`LOG_LEVEL` application-wide had it ever been imported before `config_loader`. It never was, and
was measurably a no-op, so deleting it changed nothing — but it is deleted (`a93db81`), because
dead code that would be catastrophic if it ever ran is not the kind of dead code to keep.
`config_loader` remains, and it is not removable in the same way: the implicit `basicConfig` there
is a side effect of logging at import time, not a call anyone wrote.

**Who it reaches.** Nobody now. Whoever is reading production logs during the incident after
someone tidies the imports.

**How it was found.** A production rebuild on 2026-09-17 lost its entire success log to the CLI
half of this (fixed in `a2285a3`). The scan for the same pattern produced the over-broad claim
above; a controlled measurement on the server then disproved it and produced this.

**What fixing it would disturb.** The unambiguous half is done (above). What remains is that
"has a handler" is not the same
question as "has been configured by us", and the robust form is `force=True` unconditionally. But
that changes behaviour under gunicorn, which is the one context currently known to work, and the
suite captures logs in several places. **Do not unify the app and CLI paths without re-measuring
both** — the same guard is correct in one and a no-op in the other, and that is now written into
the comment at the site. A test that boots the app and asserts `logging.getLogger().level` matches
`LOG_LEVEL` would at least make a future import reshuffle fail loudly.

### One guideline is silently absent from the corpus, and warehouse questions land elsewhere

**Where:** `data/regulatory/2023-11-26_Investor_Guideline_for_Pharmaceutical__Herbal_and_Cosmetic_Products_Warehouse_License.pdf`,
skipped by `DataProcessor._extract_text_from_pdf` on every build since at least 2026-08-03 and
recorded in each manifest's `skipped_documents` with the reason.

**What is wrong.** PyPDF2 extracts no text from any page of it — a scanned or image-only PDF — so
it contributes zero chunks. The pipeline handles this honestly: it warns, records the filename and
reason in the manifest, and carries on. What nothing handles is the consequence. Measured against
the live build: **no document in the corpus has "warehouse" in its filename**, and the 19 chunks
whose text mentions the word belong to nine unrelated documents — a DTTS integration guide, the
track-and-trace portal manual, a temperature-monitor FAQ, barcoding specifications.

So a reader asking what a warehouse licence requires does not get "nothing found". Retrieval
returns the least-bad of an unrelated set, and `apply_relevance_floor` only drops results beneath
a threshold — it cannot know the right document was never indexed. The answer arrives with
confident citations to guidance about barcode formats.

**Who it reaches.** Anyone asking about warehouse licensing — plausibly a whole category of
investor-facing question, since the missing file is an _Investor Guideline_. Silently, with no
signal to the reader or the operator that the corpus has a hole.

**How it was found.** The skip warning has scrolled past every rebuild for weeks. Its consequence
was only checked on 2026-09-18, by asking the live build which documents actually cover the topic.

**What fixing it would disturb.** Getting the text in means OCR — a new dependency
(`ocrmypdf`/Tesseract, with Arabic language data), a slower and less deterministic extraction path,
and a decision about whether OCR output is trustworthy enough to cite by page number on a
regulatory product. That is a real piece of work and probably its own plan.

The cheaper half is worth separating: **the pipeline knows exactly which documents it dropped and
never tells anyone afterwards.** `skipped_documents` is in the manifest, and nothing reads it —
not the admin console, not startup, not `build_registry list`. Surfacing it (a startup warning
naming the count, or a line in the console's overview) is small, and turns a silent hole into a
known one. Do that first; it is what makes the OCR decision a choice rather than a discovery.

### `history_api` and `sessions_api` are still rate-limited by IP, not by account

**Where:** The `history_api` and `sessions_api` limits registered in `web/api/app.py`.

**What is wrong.** Chat, export, bulk delete and the admin broadcast are all keyed per
account by `_rate_key`. These two are not, so they still key on the IP — which means one
office behind one NAT shares a budget for reading their own history, while the same people
have individual budgets for asking questions.

**Who it reaches.** Any group of readers sharing an egress IP, on navigation reads rather
than on anything expensive.

**How it was found.** Left explicitly out of scope when the quota work re-keyed the other
five limits (archived plan §3).

**What fixing it would disturb.** It is a decision, not a defect: these are navigation
reads, and an account key makes a shared-machine reader's browsing count against them
personally. Changing it touches the limit registrations and
`web/tests/test_rate_limit_keys.py`, which currently pins exactly which routes are
account-keyed.

### The console's class-existence gate cannot see a class built from a variable

**Where:** `_JS_CLASS_SITES` in `web/tests/test_css_contract.py`.

**What is wrong.** The gate that catches an `admin-*` class no stylesheet defines reads
four literal shapes: `className =`, `className +=`, `setAttribute('class', …)` and
`classList.add/toggle/remove(…)`. A class assembled at runtime — `classList.add(someVar)`,
or the interpolated tail of a template literal — is invisible to it. The gate reports
nothing, which reads identically to a clean pass.

**Who it reaches.** No reader. It reaches the next person who trusts a green gate and ships
an unstyled control, which is exactly the failure the gate was written for after
`admin-btn`, `admin-btn-quiet` and `admin-hint` shipped defined nowhere.

**How it was found.** An adversarial review of the gate itself (`gpt-5.6-terra`,
2026-09-04) named the hole while confirming the shapes it does cover.

**What fixing it would disturb.** Static analysis cannot resolve a variable, so a complete
fix is not a wider regex — it is either a convention (every `admin-*` class is a literal at
its use site, enforced by banning the dynamic form) or a runtime check that walks the
rendered DOM in the browser suite and compares against the parsed stylesheets. The second
is the honest one and costs a new browser test plus a CSS parser.

### The browser suite flakes intermittently in test_source_panel.py

**Where:** `web/tests/test_source_panel.py`, only under a full `-m browser` run.
Seen twice on 2026-08-14 across roughly five full runs, on different tests each
time — once as a teardown ERROR on
`test_a_restored_answer_cannot_open_another_answers_sources`, once as an
`ERROR at setup of test_a_citation_marker_opens_the_panel_on_its_passage`.

**What is wrong.** Unknown. It is an error rather than an assertion failure, so
it is the Playwright fixture rather than the assertion — the page or context is
gone by the time the test wants it. It does not reproduce running the file alone
(36 passed) or on a repeat of the full suite (131 passed both times).

**Who it reaches.** CI, as a red build on a green branch. `.github/workflows/tests.yml`
runs the browser suite as a separate merge gate, so an intermittent error there
is a merge blocked for no reason — and the fix people reach for is "re-run it",
which is how a real failure eventually gets waved through.

**Why it is written down rather than fixed.** Nothing was diagnosed. The
plausible causes are resource contention across ~36 browser contexts in one
session, or a fixture that outlives its page — `sourced_page` and friends layer
`page.route` handlers over the shared `browser_page`, and Playwright matches the
most recently added handler first, which is order-dependent by construction.
Chasing it needs a reproduction, and it did not reproduce on demand.

**Where to start.** Run the browser suite with `-p no:randomly` if ordering is
suspected, or `--tracing retain-on-failure` to capture the context state at the
moment it dies. If it recurs in CI, that trace is the thing worth having.

**2026-08-16 — a different symptom, same suspect.** Seen again during an
unrelated session that had run many browser tests back to back: not a fixture
teardown ERROR this time but an assertion failure —
`test_opening_sources_does_not_move_the_answer` and
`test_scrolling_up_hands_control_back_to_the_reader` both failing on
"transcript moved 652px" (a real scroll-position check, not a fixture crash).
Unlike the original write-up, the _same pair_ failed across several repeats
rather than a different test each time — but it failed identically on
pre-existing, unmodified code too, and stopped correlating with any particular
diff once ~8 leftover Chromium processes and a stray unrelated `opencode`
process (from earlier delegate work in the same long session, never cleaned
up) were killed. Not a diagnosis — the original ERROR-at-teardown shape is
still unexplained — but real, session-level evidence for the "resource
contention" half of the theory above: a long session that accumulates
un-cleaned browser/agent processes measurably degrades this specific suite's
timing-sensitive assertions. Worth checking process count before trusting a
red run in a long-lived session, CI or not.

**2026-09-11 — not only this file.** Across seven full `-m browser` runs in one long session
(the revoked-session work, with delegate agents running beside it), three tests outside
`test_source_panel.py` each failed once and then passed every time in isolation (3/3 each):
`test_signup_identity_capture.py::test_family_name_is_optional`,
`test_history_notice.py::test_the_notice_names_the_delete_control_now_that_one_exists` and
`test_notifications_browser.py::test_history_status_filter_hides_deleted_notifications_by_default`.
None touches the code that work changed, and a clean full re-run passed 310/310. The heading
still names one file because that is where the entry started; the symptom is suite-wide. The
runs kept only the summary line, so no failure text was captured for any of the three — nothing
to add on the cause.

**2026-09-12 — one failure per full run, a different test each time, and one traceback at last.**
Two back-to-back full `-m browser` runs during the logout work, on the same unchanged tree: the
first failed `test_password_recovery.py::test_switching_language_mid_recovery_stays_in_recovery`
(329 passed), the second errored at the setup of
`test_account_security.py::test_sign_out_others_button_ends_other_sessions_only` (329 passed).
Each passed in isolation, and running the changed file beside the recovery file passed 32/32.
The second is the first captured traceback of this shape: the shared `authenticated_page`
fixture (`conftest.py:675`) timed out after 30 s waiting for `#authenticated-view` to lose
`d-none` after a real login-form submit — the page navigated, the element resolved, and the view
simply never opened inside the window. That is the mocked sign-in not completing in time, not a
dead page or context, which narrows "a fixture that outlives its page" and fits the contention
half of the theory. `page` is function-scoped, so no state crosses tests. Still undiagnosed;
`--tracing retain-on-failure` on a full run is still the thing to capture.

---

### Admin analytics from saved chats — common questions, unanswered topics, citation quality

**Update 2026-09-18 — rescoped.** This entry was `Know what people actually ask` (identity-free log, gated on scale). Owner decision: V1 aggregates off saved chats instead of a new log table; per-member full Q&A split into the next entry. The no-name log below is kept as V2, not V1. Legal review parked — sorted with lawyer later, not gating dev. V1 scope is the update at the bottom, not the original mechanism.

**Where:** turns persist per reader in `chat_messages` + `chat_message_sources` via `chat_append_turn` (durable Postgres history). The sidebar's suggested questions are hand-curated in `faq.yaml`, categorised and translated, and were written by guessing at what readers want.

**Why it is wanted.** Two things at once: know which questions recur, and turn
that into a cheaper, faster answer. Put the genuinely common questions in the
sidebar and a large share of traffic converges on a small set of answers.

**Mechanism (V1).** Frequency is an aggregate question: it needs the _text_ of what was asked, not who asked it. V1 answers "what are the twenty most common questions this month" with one `group by` over saved chats and never returns `owner_id` in any analytics response. The V2 no-name table of `(asked_at, lang, scope, question_text, cited_count)` below is deferred, not V1. Per-member full Q&A lives in the next entry and is not declined here.

**The cost saving is real but not where it looks.** Two different caches get
conflated, and only one of them pays:

- **OpenAI prompt caching** discounts a repeated _prefix_, and the prefix here is
  `BASE_SYSTEM_MESSAGE` + retrieved passages + the question. The system message
  alone is **246 tokens** (measured with `o200k_base`), well under the ~1024-token
  floor at which caching engages — so nothing is cached on the strength of the
  system prompt. The prefix only qualifies once passages are included, and those
  are identical only when the question is identical. So repeated questions _do_
  hit, which is the intuition behind putting them in the sidebar. The cache also
  goes cold after a short idle window unless `prompt_cache_retention` is set.
- **An answer cache in this app** — normalised question + language + model +
  **index version** → the stored answer and its source payload — makes no API
  call at all. That is the whole bill rather than a discount on part of it, and
  it is also the latency win: an instant answer instead of a stream.

**This prompt is input-heavy, which decides how much either is worth.**
`max_context_results: 8` at `chunk_size: 5000` characters puts roughly 10,000
input tokens against a few hundred output tokens on a typical answer. On
`gpt-4o-mini`'s 1:4 input:output pricing that makes **input around 80% of the
cost of an answer** — so prefix caching is worth substantially more here than on
a chat-shaped workload, and the two caches are closer in value than the "one is a
discount, one is free" framing suggests. Any decision resting on this should
re-measure rather than trust these figures: `max_context_results` is
operator-adjustable from the console, and doubling it moves the ratio.

So the answer cache is still the feature and the sidebar is how traffic is
steered into it — but at volume, prefix caching on the repeats is not a rounding
error either.

**Scale is what makes this worth building at all.** At three accounts it saves
nothing worth the code. The arithmetic only turns at volume, and it turns hard:
the same per-answer cost against a thousand readers asking a handful of questions
a day is the difference between a rounding error and a monthly bill someone
notices — more so on a frontier model, where the same prompt costs roughly ten
times what it does on `gpt-4o-mini`. **And money is not the binding constraint.**
This deployment runs `--workers 1 --threads 8` with an in-RAM FAISS index and a
sentence-transformers model, because conversation state is process-local. At that
scale the scarce resource is that single worker, and a cache hit skips embedding,
FAISS search, TF-IDF, and fusion as well as the API call. The cache relieves the
bottleneck that actually binds, which is a better argument for it than the bill.

**What it would disturb — and this is the real cost.** A cached regulatory
answer is a _stale_ regulatory answer the moment the corpus changes, and
PRODUCT.md's first principle is that provenance is the product. So the cache key
must include the index build identity and every entry must be invalidated when
the index is rebuilt — a cache that outlives its evidence is worse than no cache,
because it answers confidently from a document that no longer says that. There is
no index-version identifier surfaced anywhere today; that is net-new and is the
prerequisite, not a detail.

The rest is smaller: writing a question log on the request path must not be able
to fail a request (best-effort, unlike quota, which must not be), and promoting a
logged question into the sidebar means translating it — `faq.yaml` is bilingual
and a question logged in English has no Arabic twin. That is a human step, which
argues for the console surfacing candidates for an operator to accept rather than
the sidebar populating itself.

**Open questions.** What counts as the "same question" — string equality after normalisation or embedding similarity — the second catches far more repeats and can also collide two questions that deserve different answers, which on a regulatory surface is the more expensive mistake.

**V1 scope (2026-09-18, owner-locked).** No new log table. Aggregate off saved chats: `chat_messages` + `chat_message_sources` via reader RPCs (`admin_top_questions`, `admin_citation_stats`). Common = `group by` normalized question (lowercase, trim, collapse whitespace; embedding similarity out). Unanswered = `cited == []` (refusals persist; `empty_answer` / `generation_failed` never save per `web/api/app.py:3730-3747`, so excluded). Quality = `% with 0 citations`, avg cited/retrieved, by category/lang; invalid-marker rate and coverage (`citations.py:294-370`) not stored, out of V1. Responses never include `owner_id`.

**What V1 would disturb.** 2 reader RPCs (`security definer`, `search_path=''`, revoke all, grant `service_role` only); `AdminBackend` + both backends in `web/services/admin_store.py`; routes `GET /admin/api/analytics/*` in `web/api/admin.py`; Overview tab render in `static/js/admin/`; strings under existing `runtime.admin.*` in `en.yaml` + `ar.yaml`; `ASSET_VERSION` bump; tests for aggregation + no identity in response.

---

### Admin per-member conversation viewer — full Q&A with audit

**Where:** no admin chat-read path today. `web/api/admin.py` has no `/api/chat/*`; `SupabaseChatBackend` (`web/services/chat_store.py`) always uses the owner from `g.identity`. RLS gives readers only own rows (`chat_sessions`, `chat_messages`, `chat_message_sources`).

**What is wanted.** Admin opens any reader → session list → full question + answer + sources, for customer support and chatbot performance review.

**Who it reaches.** Admins for support; readers whose chats are opened (legal text follows later, parked per owner 2026-09-18).

**How it was found.** Owner request 2026-09-18, split out of the analytics entry above.

**What fixing it would disturb.** 2 RPCs (`admin_list_user_sessions`, `admin_load_user_session`) with `admin_actor_email()` gate inside; add both to `supabase/tests/function_acls.test.sql` hardcoded list; no RLS policy adds. Routes `GET /admin/api/users/<id>/sessions` + `/sessions/<sid>` in `web/api/admin.py` (`404` for bad/foreign id, orphan-safe). One audit row per session-open (`chat.session_read`) — needs `ACTION_KEYS` entry in `static/js/admin/ui.js` + `en/ar` labels. Frontend inside `people-detail` panel (no new tab). Same i18n + `ASSET_VERSION` rules.

---

### Admin analytics + viewer follow-ups — click-through, feedback, search, daily counts, audit display

**Where:** the two entries above (analytics + viewer). Small adds, all not started.

**What is wanted.**

1. Click-through — an unanswered row in charts opens its example chats.
2. Thumbs down — one reader signal on an answer, feeds the quality chart (`cited == []` alone only catches refusals, not confident-but-wrong answers).
3. Viewer search — find member by email + filter by date.
4. Daily counts — questions/day, % unanswered/day.
5. Audit shows chat-opens — `who opened whose chat when` visible in the audit tab.
6. Per-category split — same charts cut by All / Regulatory / Pharma / Vet / Bio.
7. Deleted state — a reader-deleted chat shows `deleted by reader` in the viewer instead of blank.

**Who it reaches.** Admins for support and review.

**How it was found.** Owner accepted items 1–5, then 6–7, on 2026-09-18.

**What fixing it would disturb.** (1) reuses both RPCs above, one frontend link; (2) one nullable column or side table + one route + bilingual labels + `ASSET_VERSION` bump; (3) extends `admin_list_users` search pattern to sessions; (4) reuses analytics RPCs with a day bucket; (5) `ACTION_KEYS` + `en/ar` labels for `chat.session_read` (same test that pins every audited action); (6) adds a category filter to the analytics RPCs, no new tables; (7) viewer checks session existence first and renders the deleted notice, no schema change.

---

### Enable the token-verification cache once production numbers justify it

**Where:** `web/config.yaml`, `server.auth_token_cache.ttl_seconds` (currently
`0`); the cache itself is `web/services/token_verification_cache.py`.

**What is wanted.** The worker-starvation problem is already fixed by
single-flight (previous entry) at no revocation cost. What remains on the
table is reusing a _successful_ verification across sequential reader
requests within a short window, which would save GoTrue round trips single-
flight does not — a chat session sending several turns in a row, for
example — at the cost of a real, if small, revocation window: a session
revoked at GoTrue by a path this application cannot observe — a password
change or "sign out other sessions," both performed browser-direct against
Supabase, see `docs/archive/2026-08-27_token-verification-cache.md` §4.6 —
could keep authenticating on reader routes for up to the TTL. **Logout is
not part of that exposure**: `POST /auth/logout` is server-mediated and
already evicts the token cache on every call (`web/api/auth.py`), regardless
of `ttl_seconds`. `/admin/*` is exempt in every configuration.

**Why it is not done.** There is no measurement in this repository showing
the trade is worth taking — no hit-rate, no GoTrue latency distribution, no
QPS figure. Raising the TTL on the strength of an unrelated observation (an
earlier draft did exactly this, using the browser-direct PostgREST path's own
~3600s exposure to justify widening this one) was tried and reversed during
review; existing exposure elsewhere is not a license for more here.

**What turning it on requires**, per §1.4 of the archived plan:

1. Deploy with `ttl_seconds: 0` (already shipped) and watch `get_user` call
   volume and the cache's `len()` in production for a while.
2. Show, from those numbers, what fraction of reader verifications are
   sequential repeats within a candidate window, and what that costs in
   GoTrue latency today.
3. Only if that fraction is material, set `ttl_seconds` to a small positive
   number (5 seconds was the figure reasoned through, not derived from
   measurement) — and record that window here, in this entry, in the same
   commit, per this file's standing instruction.

---

### Admin broadcast & Reader Notification Center (Popups, Banners, and Inbox History)

**Full implementation plan:** [`docs/notification-center-plan.md`](docs/notification-center-plan.md) — schema, RLS/RPC design, Realtime security model, backend/frontend file plan, i18n, security checklist, rollout order, and test plan. Went through direct codebase verification, a comparison against two independently-drafted alternative plans, and an adversarial OpenCode review that found and fixed 17 real defects (a schema bug that would have broken account deletion, a security gap letting a reader forge their own read receipts, a missing actor-revalidation race, and more). This entry stays here as the short version.

**Status (2026-08-24): implemented, including the Realtime hybrid leg.** Schema (6 migrations plus 2 follow-up fixes, all applied and advisor-clean), the reader and admin RPCs, `web/services/notification_store.py` and `notification_service.py`, every reader/admin route, rate limits, the full reader UI (bell/badge, toast/banner/acknowledgement-modal, session-snoozed inbox, private-channel Realtime subscribe) and admin UI (composer with audience preview, send history, deactivate/delete/resend), and bilingual i18n are all built and wired. `@supabase/supabase-js` is upgraded to `2.74.0` (from `2.39.7`, which verifiably lacked the `private` channel option this feature needs) after a full read of `auth-js`'s changelog across that span found no breaking change to this app's own fragile auth behaviors. The private-channel RLS boundary was verified directly against the live Postgres project (a session-variable simulation of two distinct readers, confirming the policy admits one and refuses the other) — a mock cannot prove that property, so it was proven where it actually lives. Coverage: 45 backend tests, 9 Playwright browser tests for the feature itself, and the full pre-existing 252-test browser suite still green against the new SDK pin. `mypy web` could not be run to verify this pass locally — it fails on an unrelated, pre-existing numpy/mypy stub incompatibility in this dev environment (reproduced identically on a clean `main`, before this feature's changes), and no tool in this session could log into a real Supabase project to exercise the upgraded auth flow end-to-end — that one check is still owed before this ships to production.

**Re-checked 2026-08-29 — both caveats still stand, feature otherwise confirmed live.** Every
file, route and i18n key this entry names still exists and is wired; the `supabase-js` pin is
still `2.74.0` (`static/js/modules/services.js:6`); the backend suite now counts 77 passing
tests across the four notification test files (grown from 45, from unrelated later work), all
green. `python -m mypy web` still fails on the identical `numpy/__init__.pyi` error — this dev
environment runs Python 3.14, and the error is "Type statement is only supported in Python 3.12
and greater," which is a numpy-stub/interpreter mismatch, not this feature. That caveat is
unchanged.

**Live-SDK login — partially closed 2026-08-29, by hand, not by a new automated test.** The
operator ran the app against the live Supabase project (no `testing=true`) with
`supabase-js@2.74.0` in place, signed in, and navigated `/` → `/account/` → `/admin/` in one
session. Server log shows real authenticated `200`s throughout: `/api/identity`,
`/admin/api/identity`, `/admin/api/notifications/history`,
`/admin/api/notifications/purge-settings`, and the admin identity panel rendering a real
`LAST SEEN` value sourced through `admin_get_user`'s `profile_last_seen` join (screenshot).
One transient `httpcore.ReadError: [WinError 10035]` on the Flask→PostgREST leg self-resolved
on retry — a Windows non-blocking-socket read glitch, unrelated to `auth-js` or the SDK bump.

This confirms **session persistence and every reader/admin RPC route work under the upgraded
SDK against production** — the exact gap this entry flagged for basic sign-in. It does **not**
exercise the specific reason the SDK was bumped: the log cannot show whether a broadcast
actually arrives live over the `private: true` Realtime channel (that leg is browser↔Supabase
directly, invisible to Flask's log), and no one has exercised sign-out, "sign out everywhere
else," or the password-change reauthenticate flow since the bump. Narrowed, not closed: what's
still owed before production is a live Realtime-push check and those three auth-mutation paths
— not a login smoke test in general, which is now done.

**Correction, same day — that live check surfaced a real bug the "confirmed live" line above
should not have implied was fully covered.** The operator clicked a notification in the inbox
during that same session and hit **"Could not update that notification"** — a genuine,
unconditional 500 on every real call to `/api/notifications/mark-read`
(`TypeError: flask.json.jsonify() got multiple values for keyword argument 'notification_id'`).
This session's first guess was that it was the same transient Windows socket glitch seen
elsewhere in the log; the traceback proved that guess wrong. Root cause: the real backend's
`row` (from `notifications_mark_read`'s `to_jsonb(v_row)`) already carries its own
`notification_id` column, colliding with the route's explicit `notification_id=notification_id`
keyword — and `InMemoryNotificationBackend`'s `mark_read` never included that key, so all 22
tests in `test_notifications_api.py`, three of them exercising this exact route, passed against
genuinely broken production code throughout. **Fixed 2026-08-29** in both the route (build the
response dict explicitly rather than via colliding kwargs) and the in-memory double (made its
return shape match the real RPC's, so this class of bug fails a test from now on). Full
diagnosis, root cause and verification:
[`docs/archive/2026-08-29_notification-mark-read-500.md`](docs/archive/2026-08-29_notification-mark-read-500.md). 864-test
non-browser suite green afterward, and the operator independently confirmed it live the same
day after restarting the server: four `mark-read` calls and one `mark-all-read` call all `200`,
toast/banner/modal/inbox all rendering correctly, no further `TypeError`. This is the second
same-day correction to a "confirmed live" claim on this entry — both live checks were genuinely
useful, and both turned out narrower than they first read; take that as read for the two items
still open above.

**Where:**

- Database: `supabase/migrations/` (tables: `public.notifications`, `public.user_notification_reads`, RLS policies, RPC queries for read metrics).
- Admin Backend: `web/api/admin.py`, `web/services/admin_store.py` (`POST /admin/api/notifications`, `GET /admin/api/notifications/history`, `DELETE /admin/api/notifications/<id>`).
- Admin UI: `web/templates/admin.html`, `static/js/admin/ui.js`, `handlers.js` (new Notifications management tab with broadcast composer & history table).
- Reader Backend: `web/api/app.py`, `web/services/notification_service.py` (`GET /api/notifications/active`, `GET /api/notifications/history`, `POST /api/notifications/mark-read`).
- Reader UI: `web/templates/index.html`, `static/js/modules/ui.js`, `handlers.js` (toast/banner/modal renderer, Notification Bell header icon, unread counter badge, and Inbox history modal/drawer).
- i18n: `web/i18n/en.yaml`, `web/i18n/ar.yaml` (`admin.notifications.*` and `runtime.notifications.*`).

**Why it is wanted.**
Operators need a direct mechanism to send real-time or persistent notifications to readers (maintenance, emergency regulatory alerts, feature announcements), while readers need a central inbox to review past notifications they might have dismissed.

**What it involves & key features:**

- **Notification Types**: 3 display styles:
  - `toast` (auto-dismissing corner toast for updates/tips).
  - `banner` (top-of-screen bar for maintenance warnings).
  - `modal` (urgent backdrop popup requiring explicit acknowledgement).
- **Reader Notification Center (Inbox)**:
  - Notification Bell icon in header/sidebar displaying an unread count badge.
  - Slide-out panel or modal listing historical notifications with Read/Unread status and "Mark all as read" capability.
- **Admin Management & Analytics**:
  - Broadcast composer supporting targeting (All users, specific role/tier, or user ID).
  - Notification history table in admin console showing delivery status and engagement metrics (% of target readers who read/dismissed).
  - Controls to early-deactivate, delete, or re-send past broadcasts.
- **Bilingual & Real-time**:
  - Dual-language fields (`title_en`, `title_ar`, `body_en`, `body_ar`) matching reader UI language.

**2026-09-08 — one of the three outstanding checks closes; the other two do not.**
`python -m mypy web` now reports `Success: no issues found in 44 source files` on this same
Python 3.14 environment, so the numpy-stub caveat above is spent and should not be repeated
as a reason to distrust a pass. It was an environment problem and it went away with the
environment, which is worth saying plainly: nothing in this feature fixed it.

The other two are still owed, and one of them has since been diagnosed rather than merely
listed. The sign-out path is now its own entry — [a revoked or expired session clears the
transcript but leaves the conversation id in the address
bar](docs/archive/TODO-resolved.md) (now closed and archived)
— because it turned out to be a specific missing call rather than an unverified area, and a
named bug is worth more than a caveat. The live Realtime-push check is unchanged and still
needs a real project. Separately, the poll cadence this entry describes was changed on
2026-09-07: `fetchActive` now backs off from 45s toward 600s on repeated failure instead of
polling at a fixed interval, which is also what makes [one Realtime socket per
reader](#one-realtime-socket-per-reader-not-one-per-visible-tab) worth writing down.

**2026-09-11 — the sign-out half closes; the Realtime-push check does not.** The diagnosis
above turned out to be half the story: besides the URL, sign-out left this feature's own
surfaces for the next reader. Toasts, the banner and the acknowledgement modal render outside
`#authenticated-view`; a teardown that hid the modal fired its snooze; snoozes survived in
`sessionStorage`; the inbox stayed open with its rows; and a late inbox page or mark-read failure
painted over the next reader. Commit 2 of
[the revoked-session plan](docs/archive/2026-09-11_revoked-session-url-reset.md) (§9) fixed all
of it — `BroadcastNotice.reset()` plus a `readerGeneration` guard — with four browser tests in
`web/tests/test_signed_out_route.py`. The reauthenticate path was checked on the way: the
password-change reauthentication and "sign out everywhere else" do not end this tab's session, so
there is nothing to tear down there. What this entry still owes is the live Realtime-push check.

---

### The privacy policy (/privacy) is a draft, not reviewed legal text

**Update 2026-09-18 — the engineering half shipped; the legal half is still owed.**
Self-serve deletion made `page.policy.retentionBody` false (it promised deletion "is not yet
self-service"), so it was rewritten, `rightsDelete` was updated, and a new
`retentionStaysHeading`/`retentionStaysBody` pair now discloses what survives a deletion:
administrative records written beforehand, the ledger row (identifier and timestamps only),
`notifications.target_user_id`, backup copies **with no day-count claimed** because
`docs/OPERATIONS.md` records none, the model provider's own prompt retention, and server logs.
`PRIVACY_POLICY_VERSION` moved to `2026-09-18-draft-2` and `draftNotice` stays up.

**Still owed, and none of it is an engineer's to write:** the legal review itself; the
cross-border transfer basis (the project runs in `eu-central-1`, outside the Kingdom, and the
text does not say so); naming the sub-processors, including whether prompts are excluded from
model training; and removing the draft label. Two standing cautions: never cite article
numbers a language model produced — `docs/data-policy-decisions.md` already warns these are
"exactly what a language model invents" — and the Arabic of every new string above is
unreviewed.

**Where:** `web/i18n/en.yaml`/`ar.yaml` (`page.policy.*`), `web/templates/privacy.html`,
`web/api/app.py`'s `PRIVACY_POLICY_VERSION` constant.

**What happened:** Step 6 of `docs/archive/2026-08-23_profile-refactor.md` (consent) was blocked on §12.4's own
rule — no marketing collection until a bilingual policy is approved and published. Written and
published 2026-08-23 by explicit product-owner instruction: a generic, honest draft, specifically
to unblock the engineering, with content review deferred. `page.policy.draftHeading`/`draftNotice`
say so on the page itself, in both languages — this is not a silent placeholder.

**What's still owed:** legal/product review of the actual policy text (accuracy of the
data-sharing claims, retention statement, and rights list; a real "last reviewed" date; whether
the generic infrastructure-provider language needs to name Supabase and the model provider
explicitly for the jurisdictions this product serves). When that review lands, bump
`PRIVACY_POLICY_VERSION` in `app.py` — every consent record on `profiles` stores the exact version
string it was granted under, specifically so a reviewed policy replacing the draft does not
silently reinterpret consent nobody actually gave to the new text.

---

### Account deletion (Spec 4) — blocked on a product decision, not on engineering

**Update 2026-09-18 — the decision is closed and the whole feature is built. Nothing is
applied.** The product owner decided: **yes**, with a **30-day grace window**, matching
`docs/data-policy-decisions.md` §1. Self-serve deletion is refused for `role='admin'`.

Built and gate-green (1166 tests, mypy/ruff/eslint/markdownlint clean): thirteen migrations in
`supabase/pending/`, three GoTrue dispatcher methods, the request/cancel/status routes with
server-verified step-up re-authentication, the reader-facing card and pending banner in both
languages, and a systemd one-shot reconcile driver in `deploy/`.

**Three design corrections worth keeping**, each found by review and verified in code:

- `deletion_pending` is **its own state**, never `is_disabled`. `_authenticate_request`
  refuses a disabled account (`web/api/app.py:932-933`), so conflating them would have made
  the cancel path unreachable — the grace window would have been storage, not recovery.
- **Sessions are revoked with `auth.admin.sign_out(jwt, scope="global")`**, never
  `revoke_sessions` (which revokes by rotating the password to a value nobody learns,
  `web/services/auth_admin.py:153-156`) and never a GoTrue ban (which kills token refresh).
  Either would lock the reader out of the cancel path. Global sign-out kills a thief's session
  while the owner signs back in with the password they still know.
- The saga's own rows carry **UUIDs and timestamps only**. The ordinary audit pattern stores
  `actor_email`, `request_ip` and `user_agent` in an append-only table, which would have
  preserved the deleted person's email and IP forever.

**Still open:** applying the batch, in the order and against the gates in
`supabase/pending/README.md` — which includes a confirmed backup schedule and one restore
rehearsal before the destructive DDL, and installing the reconcile timer, without which
"deletion in progress" is a promise nothing drives. Arabic review of every new string. No SQL
in this batch has ever run against a real database.

**Where:** `docs/archive/2026-08-23_profile-refactor.md` §16·4 has the full design (Migration A — FK-action
fixes on `profiles.disabled_by`/`app_settings.updated_by`, verified live and ready to apply —
then Migration B — a durable `account_deletions` saga table with retry/backoff, since a database
transaction cannot include the outbound GoTrue admin-delete call). §17's Step 7 entry is marked
`[ ]`, explicitly not started.

**Why it's blocked.** §10's open question — "is reader self-deletion permitted at all, given the
audit log?" — was never closed. P2 of the plan assumes yes; the "Still open" list at §17 still
lists it as undecided. Export and bulk conversation deletion (same Step 7) do not depend on this
answer and shipped 2026-08-23; account deletion does, and building a background saga that calls
GoTrue's admin delete API on a schedule, against real accounts, on an assumption rather than a
decision is the kind of hard-to-reverse action this file exists to flag rather than quietly do.

**What's needed to unblock:** an explicit yes/no on self-deletion from whoever owns that call,
given the audit-log retention question it raises. Once decided, the two migrations in §16·4 are
already written and only need re-verification against the live schema before applying.

- Hybrid delivery: Supabase Realtime broadcast for active sessions + REST DB query on page load for offline/new sessions.

---

### Gunicorn writes no access log, so "served fine" and "never asked" look identical

**Where:** `gunicorn.conf.py` (which sets only `workers` and `raw_env`) and the
`ExecStart` line in `deploy/sfda-copilot.service`, neither of which passes
`--access-logfile`. Nginx in front of it does log.

**What is wrong.** The application server records nothing about the requests it serves.
A successful request produces no line at all, so an empty journal window is ambiguous
between "the request was served cleanly" and "no request ever arrived". Errors still
surface, because those go through the logger — it is the ordinary, successful traffic
that is invisible.

**Who it reaches.** Nobody, in the sense of a reader-visible fault. It reaches whoever
is trying to establish what the server actually did — which in practice is whoever is
mid-incident, and therefore the worst moment to discover the evidence was never
recorded.

**How it was found.** 2026-09-19, verifying that the HTTP/2 transport fix had landed in
production. The check was "watch the journal while `/admin` loads, and report any
`httpx.ReadError`". The window came back empty — which proved nothing, because nginx
showed no `/admin` request had arrived in it at all. Reporting that empty window as a
pass would have been wrong twice over: once about the fix, and once about whether the
code had even run. Nginx's log is what separated the two, and only because it happened
to be there.

**What fixing it would disturb, and why it is not obviously a yes.** Mechanically it is
one flag. The cost is that it creates a SECOND place every request path is written, and
this application's paths are not neutral: `GET /c/<uuid>` puts a specific person's
conversation identifier in the URL. That is already an open question in
_A conversation id now reaches the access log_ below, unresolved, and turning on a
second logger without settling it doubles the surface of the thing that entry exists to
worry about. The privacy policy now discloses that server logs persist "including
conversation access paths", so this would not make the copy false — but it would make
it truer than anyone has decided it should be.

**Therefore decide the two together**, and in this order: settle whether `/c/<uuid>` is
scrubbed or retained, write the answer into `docs/OPERATIONS.md`, and only then choose
an access-log format that matches that decision. A format that logs the path verbatim
and one that scrubs it to `/c/:id` are the same one-line change; which one is correct
is not a question this repository can answer.

### A conversation id now reaches the access log

**Where:** wherever this deployment's HTTP access logs are written and retained —
which this repository cannot tell you. `docs/OPERATIONS.md` is the place that can.

**What is wrong, possibly.** Before deep linking, a reader's conversation was named by
a cookie and never appeared in a URL. Now it is the URL: `/c/<uuid>`. Every layer that
logs request paths — the WSGI server, any reverse proxy, any hosted logging or APM
sink — now records the identifier of a specific person's conversation, in a system
whose retention and access rules are set somewhere other than this codebase.

The id is not a capability. `GET /c/<uuid>` is unauthenticated by design, performs no
ownership check, writes no state, and returns byte-identical content for a foreign id
and for one that never existed — properties pinned by
`web/tests/test_deep_link_contract.py`. So a leaked id does not read a conversation.
It does reveal that a conversation exists and roughly when it was visited, which is
more than the cookie ever put in a log line.

**Why this is a task and not a bug.** It may already be fine. §6.3 of
`docs/archive/2026-08-22_per-tab-deep-linking.md` states the action as: confirm no
third-party log sink retains full paths, or scrub `/c/<uuid>` to `/c/:id` before
shipping. Neither half was done, and the audit could not do it — the answer lives in
the deployment, not the repository.

**What fixing it would disturb.** If scrubbing is needed it belongs in the proxy or the
log formatter, not in Flask, so no application code changes either way. Whatever the
answer turns out to be, write it down in `docs/OPERATIONS.md`, which exists precisely
for state this repository cannot hold.

### A retention policy, and the bounds that depend on one

**Where:** `public.audit_log`, `public.chat_messages`, `public.chat_message_sources`,
`public.user_notification_reads`, `public.usage_daily`, and `public.chat_archive` once its
salts are set.

**What is wrong.** There is no `pg_cron`, no scheduled job, no partition and no retention
policy on any table, and five of them grow forever. `usage_daily` joined the list on
2026-09-04: it writes one row per reader per day they ask anything, forever, and the
allowance only ever reads today's — every row older than the current Riyadh day is dead
weight the moment midnight passes. It is the cheapest of these to sweep and the one with
the least to argue about, since nothing reads a past day. `chat_archive` is designed to be
append-only with **no delete path at all** — deliberately, and documented — so when the
salts are set it starts growing at roughly one `question` + `answer` + `sources jsonb` per
turn with no way to stop it.

Two column-level bounds are missing for the same reason. `20260828002253` bounded
`chat_messages.content` for `role = 'user'` at 8,000 characters, derived from Flask's
`MAX_CHAT_QUERY_CHARS`. It deliberately left two things alone:

- **Assistant content is unbounded**, and inventing a bound would corrupt history. There is
  no answer-length check anywhere in `web/api/app.py`; a model answer routinely exceeds the
  question limit (live rows: user content maxes at 250 characters, assistant at 4,462).
  Clamping it to the question's limit would store a truncated copy of an answer the reader
  had already been streamed in full — durable history quietly disagreeing with what was on
  screen, the worst failure available in a citation product. The number has to come from
  the model's `max_tokens` times a safe character ratio, plus a matching pre-persistence
  policy. **That number does not exist yet.**
- **`audit_log`'s text columns are unbounded** — `action`, `target_id`, `user_agent`,
  `note`, `actor_email`. `user_agent` is attacker-controlled and is the one that most wants
  a cap. A `CHECK` is the wrong shape here for the reason `20260820131914:44-47` gives for
  `title`: it would fire inside a `SECURITY DEFINER` function and abort an administrative
  action, surfacing a client mistake as a 500. The right shape is a clamp in the seven
  admin writers plus `admin_store.py`'s direct insert — a different concern, in a different
  set of functions, and it needs numbers picked from what those writers actually produce.

**Who it reaches.** Nobody, for a long time. The database is roughly 14 MB and Postgres
does not care about a million-row `audit_log`. **It bites as a compliance question before
it bites as a performance one**: an application that records which regulatory guidance
named professionals asked about, keyed to real accounts, with an audit log of
administrative action, in a jurisdiction with data-protection law, and no answer to "how
long do you keep it".

**How it was found.** The 2026-08-28 database review
(`docs/database-improvement-plan.md`, finding 8).

**What fixing it would disturb.** **Do not build a purge before somebody owns the
retention period** — a job that deletes before a legal hold is defined is worse than no
job. The predecessor is a documented policy, and it overlaps the account-deletion question
already open below. When it exists, `user_notification_reads` is the table where a rolling
delete is uncontroversial and `audit_log` is the one where it is not. Adding the remaining
`NOT VALID` CHECKs is cheap at today's row counts and expensive at five million, which is
an argument for settling the numbers sooner rather than later.

---

### Marketing consent has no re-prompt path, and the trigger cannot record a re-affirmation

**Where:** `supabase/migrations/20260823014034_marketing_consent_record.sql:110-124` (the
trigger's no-op branch) and `web/api/app.py:352-354` (`PRIVACY_POLICY_VERSION`).

**What is wrong.** Every consent record is stamped with the policy version in force when it was
given, but **nothing compares a stored version to the current one**. Bumping the constant
silently leaves every existing consent attributed to the older string, and no reader is ever
re-asked. Worse, a re-affirmation cannot be recorded even by hand: when `marketing_consent` is
unchanged, the trigger's no-op branch restores all six consent metadata columns from `old`, so
the only way to restamp is a fake withdraw-then-grant, which would write a false
`marketing_consent_withdrawn_at`.

**Who it reaches.** Every reader who has granted marketing consent, the first time the policy
changes materially. Nobody yet — `PRIVACY_POLICY_VERSION` has moved only between draft strings
(`2026-08-23-draft-1` → `2026-09-18-draft-2` on 2026-09-18), and a draft-to-draft retention edit
is not a material change to what was consented to.

**How it was found.** An adversarial review of `docs/account-and-trust-plan.md` on 2026-09-18,
then verified against the trigger source.

**What fixing it would disturb.** Three defects were found together; **two are already fixed**
and this is the third. The version is now supplied by the server on both paths — the account
route stamps it (`web/api/account.py`, `consent_grant`) and signup stamps it in
`_signup_metadata` — and `supabase/pending/03` revokes the direct column grants that let a
client stamp a version it never saw. What remains is the comparator itself: an explicit
re-affirm branch in the trigger (so a restamp does not have to lie about a withdrawal), a
server-side comparison of stored against current, and a prompt. It was deferred deliberately,
on the grounds that a re-affirm branch with no caller is surface for a feature that does not
exist. **Decided 2026-09-18: re-prompt on material change only, with materiality judged by a
human per bump** — so this becomes due the first time the policy changes in substance, which is
most likely when counsel's review lands and the draft label comes off.

### `chat_sessions.owner_id` still has no foreign key

**Update 2026-09-19 — the migration was REMOVED, and this entry stays open.** It was written
on 2026-09-18 as `supabase/pending/13` and parked behind "one real deletion has completed end
to end", because `ON DELETE RESTRICT` would convert a saga bug into a `23503` that blocks
deletion entirely. The owner's decision on 2026-09-19 was to delete the file rather than carry
a parked migration whose gate might not be met for thirty days. **That is a reversal of the
2026-09-18 decision to stage it, not a resolution of the finding below** — the FK still does
not exist, and now nothing is queued to create it.

**What now carries the guarantee, in the FK's place.** Only the saga, and only in software.
`account_deletion_purge_transcripts` deletes the rows explicitly, and
`account_deletion_freezes_writes` includes the `completed` state precisely because
`chat_sessions.owner_id` has no foreign key — a 300-second stream admitted during grace could
otherwise file a turn after the purge, under an owner id resolving to nothing. Before, that
predicate was belt-and-braces ahead of a constraint that was coming. **Now it is the only
belt**, which is worth knowing before anyone "simplifies" it; `test_account_deletion_predicates.py`
pins it and its docstring says why.

**And the software guard does not close everything the FK would have.** Found 2026-09-19 by
an adversarial read of the removal decision, then verified against the SQL. Two sequences
survive a completed deletion with transcripts intact:

1. **A check-to-commit race inside the saga.** `chat_append_turn` evaluates
   `account_deletion_freezes_writes`, gets "not frozen" while the account is still `pending`,
   and inserts its `chat_sessions` row — but has not committed. The purge runs in a different
   transaction and **cannot see an uncommitted row**, so it deletes nothing; the re-purge in
   `account_deletion_begin_auth_delete` misses it for the same reason. The append then
   commits, GoTrue deletes the account, and `account_deletion_complete` succeeds — because it
   checks only that the `profiles` row is gone (`DL006`), **never that transcripts are gone**.
   Nothing serialises the two: the purge takes `for update` on the ledger row, and the append
   takes no lock at all. The window is narrow — the append transaction must stay open across
   both purges, which run milliseconds apart — and this is established by inspection, not by
   an observed incident.
2. **A deletion that never goes through the saga at all.** Deleting a user in the Supabase
   dashboard or through the raw Auth Admin API cascades the profile away and leaves the
   sessions, with no ledger row for the reconcile timer to find. **This is not reachable from
   the app:** `delete_user` is called from exactly one place,
   `scripts/reconcile_account_deletions.py`. It needs a human with dashboard access.

`ON DELETE RESTRICT` would have converted both into a loud `23503` at the moment the profile
cascade fired, instead of a silent survival.

**The detection gap is the part worth fixing first, and it is cheap.** There is no orphan
detector anywhere — no query, no job, no panel — and orphaned rows are unreachable through
RLS (no `auth.uid()` will match a deleted user) and through every RPC (all filter
`p_owner_id`). So a failure of the software guard is not merely possible, it is **invisible**.
A scheduled `select count(*) from public.chat_sessions s left join public.profiles p on
p.id = s.owner_id where p.id is null` with an alert closes that, works whether or not the FK
ever lands, and is the one thing that turns "we believe there are none" into "we would know".
**Verified 0 on 2026-09-19**, which is a snapshot and not a guarantee — and is unsurprising,
since no deletion has completed yet.

**One trap in reading that query:** a hit is NOT automatically a deleted-account leftover.
This app deliberately tolerates an `auth.users` row with no `profiles` row — see
`20260828143044_touch_last_seen_tolerates_a_profileless_account` — so any row it returns needs
investigating before anything is deleted.

**Priority.** Low today and not low forever. No account has completed deletion, so the
population at risk is currently zero; the race needs a deletion to race against. **The
detector should land before the first real completion**, because after that point "we have
never seen an orphan" stops being reassuring and starts being a statement about not looking.

**If it is ever rebuilt** the design is unchanged and is recorded in `docs/database-improvement-plan.md`
(finding 5) and in git history at `supabase/pending/13_chat_sessions_owner_fk.sql`: an orphan
check that aborts, then `NOT VALID` + a separate `VALIDATE` under `SET LOCAL lock_timeout`,
referencing `public.profiles(id)` — not `auth.users`, which service_role cannot reach. Run the
orphan check first; any hit is an incident, not a row to force.

**Where:** `supabase/migrations/20260820131914_chat_session_persistence.sql:37-42`, and
rule 8 of `supabase/README.md`, which records the correction.

**What is wrong.** `profiles.id → auth.users(id)` cascades. So deleting an account today
succeeds, removes the profile, and leaves that reader's `chat_sessions`, `chat_messages`
and `chat_message_sources` behind with an `owner_id` that resolves to nothing — forever,
with no detector and no purge path. For an application that records which regulatory
guidance named professionals asked about, "the erasure request completed and the
transcripts are still there" is the failure mode.

The reason there is no FK is **factually wrong**, and that half is already fixed:
the migration header says "an FK brings ON DELETE CASCADE with it, and deleting one account
would take a year of retained conversation with it". A `REFERENCES` clause with no
`ON DELETE` action defaults to `NO ACTION` — the parent delete is refused while children
exist. `CASCADE` is opt-in and has to be typed. So the stated trade-off is a false choice,
and a third option was never considered: an FK with `RESTRICT`, which keeps every
conversation and makes an orphan impossible.

**Who it reaches.** Nobody yet — no account has been deleted. Note what this is _not_: it
is not a live leak. Those rows would be unreachable through RLS (no `auth.uid()` will ever
match a deleted user's id) and unreachable through the RPCs (every one filters
`p_owner_id`). They would be invisible and permanent, which is the shape of a retention
problem rather than an access problem.

**How it was found.** The 2026-08-28 database review
(`docs/database-improvement-plan.md`, finding 5).

**What fixing it would disturb.** `ON DELETE RESTRICT` **changes an existing operator
capability**: deleting a user from the Supabase dashboard or through GoTrue's admin API
succeeds today, and would afterwards fail with `23503` until that user's conversations are
dealt with. That is the point — it converts silent orphaning into a loud refusal — but it
is a behaviour change to a path that is used. **Sequence it behind the account-deletion
entry below, not ahead of it:** landing the constraint before there is any path to delete
a reader's conversations makes account deletion impossible rather than explicit. The
migration itself is small (an orphan check that aborts, then one `add constraint`) and
needs no new index: `chat_sessions_owner_updated_idx` leads with `owner_id`.

---

### Does "disabled" freeze an account's own profile edits, or only its use of the product?

**Update 2026-09-18 — decided and built; applied 2026-09-19.** The answer is **freeze
everything in `public` except marketing-consent withdrawal**. Built as `01`-`05` of the
account-and-trust batch, all now in `supabase/migrations/`:
a withdrawal-only `security definer` RPC that a disabled account can still reach, a
`service_role` grant RPC behind a Flask route (so a disabled account can never _grant_, and so
the policy version is stamped server-side), `is_active_account()` added to the `profiles`
UPDATE policy, and the same gate added to `update_own_preferences`.

**Three things this turned up that the entry did not anticipate:**

- `update_own_preferences` was a **second unguarded write path**. It is `security definer`, so
  it bypasses RLS entirely — freezing the policy alone would have left `theme`, `language` and
  `search_scope` writable by a disabled account.
- The privilege-guard trigger **cannot protect an RPC**: it tests
  `current_user in ('authenticated','anon')`, and inside a `security definer` function
  `current_user` is the owner. Only the function body protects server-owned columns, which is
  why the withdrawal RPC uses a static column list and takes no patch.
- `authenticated` held **INSERT** as well as UPDATE on the four consent columns, and
  `Services.updateProfile` upserts — so for a profile-less account that upsert is an INSERT.
  Revoking UPDATE alone would have left the policy version forgeable through it.

**Deliberately not done, and recorded so nobody re-litigates it:** no GoTrue ban accompanies
`disabled`. A ban kills token refresh, which would make the consent carve-out unreachable —
the precise hole the carve-out exists to close. "Frozen" is therefore true of this schema and
not of the provider: a disabled reader can still change their own GoTrue email or password.

**Still open:** applying the batch (`supabase/pending/README.md`), and the consent re-prompt
comparator, which is deferred — see its own note under the privacy-policy entry.

**Where:** The three RLS policies on `public.profiles`; `web/api/app.py`'s
`if identity.is_disabled:` refusal; `docs/PRODUCT.md`, which does not say.

**What is wrong.** Every chat policy gates on `is_active_account()`. None of the three
`profiles` policies does. Flask refuses a disabled account, so no Flask route is affected —
but `profiles` is the one browser-direct table, and a disabled account holding an unexpired
JWT can `GET` and `PATCH` its own row against PostgREST with Flask nowhere in the path. A
GoTrue access token stays cryptographically valid until its `exp` regardless of what the
operator did to the account.

**Who it reaches.** A disabled reader, for the remaining life of their token. The privilege
columns are safe — `profiles_guard_privilege_columns` raises `42501` for `authenticated` on
`role`, `tier`, `is_disabled` and the consent timestamps — so this is not privilege
escalation. It is a disabled user still able to change their name, organization,
specialization, age and marketing consent.

**How it was found.** The 2026-08-28 database review
(`docs/database-improvement-plan.md`, finding 6).

**What fixing it would disturb.** Whether it matters at all is a product question, and
that is why this is open rather than fixed: "disabled" might reasonably mean "cannot use
the product" rather than "is frozen". Right now it is an asymmetry nobody chose. If the
answer is _frozen_, the change is one statement — `alter policy "Users can update own
profile" … using (((select auth.uid()) = id) and (select public.is_active_account()))` —
and the two policies it must **not** touch are worth stating: **leave `SELECT` alone** or a
locked-out reader cannot be shown why they are locked out, and **leave `INSERT` alone**
because it is the browser's fallback path at signup, at which point no profile row exists
for `is_active_account()` to consult. There is no recursion risk in calling it from a
policy on `profiles`: it is `security definer` owned by `postgres`, which holds
`BYPASSRLS`. Testing it needs a disabled account's live JWT, which the browser suite
cannot mint — so the gate is `supabase/tests/`, extended.

---

### Confirm the backup schedule, and rehearse a restore once

**Where:** The Supabase dashboard (Database → Backups). Written up as an assumption in
`docs/OPERATIONS.md`.

**What is wrong.** The database's recovery position is written down nowhere and has never
been tested. The MCP `get_project` response says nothing about backup schedule or
point-in-time recovery, so it cannot be answered from an agent session. The advisor's
standing `auth_leaked_password_protection` finding tells us the project is below the Pro
tier and PITR is a paid add-on, so the working assumption is daily backups with no PITR —
an assumption, stated as one.

**Who it reaches.** Everyone, once. The entire content of this database is user-generated
and unreproducible: reader conversations, an audit log of administrative action, consent
records with timestamps and policy versions. There is no re-derivation path for any of it.

**How it was found.** Writing Wave 0 of `docs/database-improvement-plan.md`, which asked
for a pre-migration export and discovered the question had no answer. A row-count and
content-hash baseline was taken instead — that is a verification baseline, not a backup,
and it is stored outside this repository because it names real account ids.

**What fixing it would disturb.** Nothing in the codebase. Two steps: read the dashboard
and replace the assumption in `docs/OPERATIONS.md` with what is actually configured, then
restore into a scratch project once, to turn a setting into a known-good procedure. At 14
MB this is the cheapest it will ever be to rehearse; the cost only rises.

---

### Measure the real statement and lock timeouts on the write path

**Where:** `pg_roles.rolconfig`; the procedure and the probe function are in
`docs/OPERATIONS.md`.

**What is wrong.** `service_role` has no role-level `statement_timeout`, and **no role and
no cluster default sets a `lock_timeout` or an `idle_in_transaction_session_timeout`
anywhere**. `chat_append_turn` takes `select … for update` on the session row and holds it
until the function returns; a transaction that stalls while holding it has nothing bounding
the waiters, so every subsequent turn in that conversation blocks until the statement
timeout — whatever it actually is — fires.

What it actually is, is the open question. The cluster's `statement_timeout = 120000` was
observed from an MCP session, which is not how Flask reaches the database: Flask calls
PostgREST, which logs in as `authenticator` (`statement_timeout=8s`, `lock_timeout=8s`) and
switches role per request, applying each role's `rolconfig` as it goes — this database's
own `pg_stat_statements` records that happening. With no `rolconfig` on `service_role`
there is nothing to apply, so a service-role request most likely inherits `authenticator`'s
8s rather than two minutes. **That is a deduction from the mechanism, not a measurement.**

**Who it reaches.** Nobody observed. The app is single-worker
(`gunicorn --workers 1 --threads 8`), which narrows it considerably — it is a gap in the
layer below the app, not an active incident.

**How it was found.** The 2026-08-28 database review
(`docs/database-improvement-plan.md`, finding 11), whose first two drafts both got the
premise wrong in opposite directions before it was reduced to "measure it".

**What fixing it would disturb.** The measurement is the deliverable and it needs a call
path an agent session does not have: the probe must be invoked as `service_role` through
`/rest/v1/rpc/`, not through MCP, or it measures the wrong connection again. Setting
`lock_timeout` afterwards is the safe half. **Tightening `statement_timeout` on
`service_role` changes the operator's own environment as well as the application's** — it
is what the MCP tools and any administrative script connect as, so a long maintenance query
would be aborted. An `idle_in_transaction_session_timeout` is worth setting as a backstop
against a dead client but would **not** bound the lock above: it acts on a transaction that
is idle, and a PL/pgSQL function still executing is not idle.

---

### Run the database assertions somewhere other than by hand

**Update 2026-09-19 — the cost of this landed, concretely.** The account-and-trust batch
applied fourteen migrations to the live project, and its runbook's own closing step was
"re-run `supabase/tests/`, including the two new files (`disabled_consent.test.sql` and
`account_deletion.test.sql`), which pass only once these are applied". **That step was not
done.** Nothing failed and nothing complained, because nothing runs them. The two new files
have therefore never executed against the schema they were written for — they are 2026-09-18
assertions about migrations that landed on 2026-09-19, and their current status is unknown
rather than green. The advisors were re-run and are clean, but the advisors do not check
grants, which is exactly the gap this entry is about. **Run all six files by hand before the
next migration touches consent, deletion or the profiles policy.**

**Where:** `supabase/tests/` (four files at the time of writing, six now), and the absence of
a database in CI.

**What is wrong.** Those four files hold 175 assertions about grants, column privileges,
the default ACL, function ACLs, `search_path` and reader-to-reader RLS isolation. They are
the only thing in this repository that can fail because of a privilege — every Python test
mocks the Supabase client, and the advisors do not check grants at all, which is why the
four grant-layer defects the 2026-08-28 review opens with sat under a green CI run
indefinitely. **They run only when somebody remembers to paste them into `execute_sql`.**

**Who it reaches.** The next person to write a migration that forgets a revoke line — and
specifically the next `security definer` function, which is born `PUBLIC`-executable
whatever the default ACL says (see the entry under Known bugs).

**How it was found.** Writing them, on 2026-08-28, as the deliverable of the review's
finding 7.

**What fixing it would disturb.** Two honest options with very different sizes. **Adopt
the Supabase CLI and a local stack**, which gets `supabase test db` in CI — a structural
change to a project that has deliberately never had a CLI, and it deserves its own
decision rather than arriving as a rider. **Or point a CI job at a scratch Supabase
project** and run the files through it, which needs a second project and a service key in
CI secrets, and tests a database that is not the one that matters. A third, cheaper move
that is worth doing either way: fail a check if `get_advisors` returns any finding not in
`supabase/README.md`'s standing-findings table — that turns the register from a convention
into a gate, and it needs no database at all.

Converting the files to pgTAP is **not** part of this. `pgtap` is available and not
installed, and installing a few hundred functions into the production database to run
three assertion files is a bigger change than the files are. They are plain `do` blocks
that need no extension and convert mechanically if that ever changes.

### One Realtime socket per reader, not one per visible tab

**Where:** `static/js/modules/services.js:955-964` (`Notifications.subscribe`) and the poll
loop in `static/js/modules/handlers.js` (`startNotificationsPolling`, line 1176), both
driven by the visibility listener at `handlers.js:244-247`.

**What is wanted.** Every visible tab opens its own `notify:user:<uid>` Realtime channel
and runs its own REST poll loop, so one reader with four windows open holds four
WebSockets and four independent timers against a server that runs a single worker. Web
Locks (`navigator.locks.request` in exclusive mode) plus a `BroadcastChannel` would elect
one leader tab to hold the socket and the poll and fan the results out to the rest. That is
the standard browser answer, and the reason to prefer it over an election written by hand
is that the browser releases the lock when the leader tab dies — a hand-rolled leader has
to detect its own death, which is the part that goes wrong.

**Who it reaches.** Nobody badly, today, and that is why this is planned work rather than a
bug. The visibility listener already tears down both the channel and the poll when a tab is
hidden (`handlers.js:246`), so the multiplier is _visible_ tabs, not open ones — normally
one. It reaches the reader working across two monitors, and it multiplies whatever the poll
costs: the P7 work set that at 45s, rising to 600s under sustained failure, so four visible
tabs is four times that floor.

**How it was found.** A code read on 2026-09-08 during the P7 notification-poll work,
alongside a survey of how other projects handle multi-tab state.

**What fixing it would disturb.** Leader election is genuinely stateful, and wrong in ways
that only appear in production. The sharp edge here is that leadership and visibility are
two different things: a leader tab that becomes hidden tears its own subscription down by
the rule above, so it must hand the lock on rather than hold it while delivering nothing —
which means the visibility listener and the lock have to be reasoned about together, not
bolted on to each other. `BroadcastChannel` also adds a new cross-tab surface carrying
notification state, and `test_frontend_architecture.py` has an opinion about that:
`services.js` is transport only and may not reach into view or state, which a fan-out that
delivers straight into the other tabs' handlers would do. Verifying it needs real
multi-context browser tests — `test_multi_tab_conversations.py` is the pattern — and those
are the slowest and most contention-prone tests in the suite, which is the subject of its
own entry above. Worth doing when someone can show the duplicate polling costs something;
not before.

---

## How this file works

### Writing a new entry

Put it under **Known bugs** if it is wrong now, **Planned work** if it is wanted but not
started. Same shape either way:

```markdown
### A one-line statement of the problem, in plain words

**Where:** the file, function and line — or, if it lives outside the repo, say so and
name the dashboard, DNS zone or provider that holds it.

**What is wrong.** What actually happens, and why that is wrong rather than merely
surprising. Name the rule or guarantee it breaks if there is one.

**Who it reaches.** Which readers, in which situation, how often. "Nobody yet" is a
legitimate answer and worth writing down.

**How it was found.** A failing test, a live report, a code read, a review pass. This is
what tells the next person how much to trust the diagnosis.

**What fixing it would disturb.** The cost. Which files, which tests, which decisions get
reopened, and anything that has to ship in the same commit.
```

The last section is not optional. **An entry that says only what it wants is a wish; the
useful half is the cost.** If you cannot say what fixing it would disturb, you have not
finished looking.

Then add one line to **Open now** at the top, linking to the heading, with a short clause
saying what state it is in — _not started_, _blocked on X_, _diagnosed, unfixed_. The index
and the body must agree; when they drift, the body wins, and that has already happened
once in this file.

### Closing an entry

1. **Add a closing note to the entry itself** — dated, saying what actually shipped and
   where. If the original diagnosis turned out to be wrong, say so rather than editing it
   into looking right; the correction is the valuable part.
2. **Move the whole entry** to `docs/archive/TODO-resolved.md`, under _Resolved bugs_ or
   _Resolved planned work_. **Do not strike it through and leave it here.** A file where a
   handful of entries in forty read as current is a file nobody trusts the index of — that
   is why the archive exists.
3. **Delete its line from Open now.**
4. If the entry named a document, check that document is still true. Closing the work is
   what makes the docs stale.

**Strike a heading only when a reader can see the difference and nothing material is
outstanding.** Partly-done work stays open, with an update note saying which part landed.

### When an entry is superseded by a plan

If the work grew into its own planning document, the entry stays here as the short version
and points at the plan. When the plan is finished, **archive the plan and lift any still-open
items back into this file as their own entries** — otherwise the open work is buried inside
a document banner-marked as history. The full archiving procedure is in
[`docs/archive/README.md`](docs/archive/README.md#adding-to-this-archive). That is exactly what happened to the profile refactor's
three blocked items, and why they are now separate entries above.
