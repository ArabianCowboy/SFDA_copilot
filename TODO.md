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
correct but collide at one specific point — and there are eleven known ones — are listed
there too, under
[_Rules that collide_](docs/ARCHITECTURE.md#rules-that-collide). Read that section
before your next migration or your first RTL component.

**Adding an entry, or closing one?** The template and the closing procedure are at the
bottom of this file: [How this file works](#how-this-file-works).

---

## Open now

- [Leaked-password protection is disabled in Supabase Auth](#leaked-password-protection-is-disabled-in-supabase-auth) — blocked on a Pro-plan upgrade, not code.
- [`auth_bp` carries no rate limit, so `/auth/login` is unlimited](#auth_bp-carries-no-rate-limit-so-authlogin-is-unlimited) — diagnosed, unfixed; the exemption is deliberate for logout and accidental for login.
- [A silent truncation from a provider that omits `finish_reason` is still undetected](#a-silent-truncation-from-a-provider-that-omits-finish_reason-is-still-undetected) — diagnosed; needs `include_usage`, not a different default.
- [An empty answer toasts "failed to send", which is the wrong thing](#an-empty-answer-toasts-failed-to-send-which-is-the-wrong-thing) — cosmetic, needs a bilingual key pair.
- [`max_tokens` has no floor, and a low one guarantees empty answers](#max_tokens-has-no-floor-and-a-low-one-guarantees-empty-answers) — not started; prevention rather than the reporting that now exists.
- [Ten source comments cite a plan file that has been archived](#ten-source-comments-cite-a-plan-file-that-has-been-archived) — doc rot, mechanical to fix.
- [Security email is English-only](#security-email-is-english-only-on-a-product-that-is-bilingual-by-construction) — blocked in the Supabase dashboard, not code.
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
- [Know what people actually ask](#know-what-people-actually-ask--without-reading-anyones-conversation) — an identity-free question log; not started, gated on scale.
- [Enable the token-verification cache once production numbers justify it](#enable-the-token-verification-cache-once-production-numbers-justify-it) — single-flight (the worker-starvation fix) shipped 2026-08-27 at no revocation cost; the optional positive cache stays off, gated on measurement.
- [Admin broadcast & Reader Notification Center](#admin-broadcast--reader-notification-center-popups-banners-and-inbox-history) — implemented 2026-08-24; live login/session smoke-tested against production 2026-08-29 (by hand), which also surfaced and closed a real `mark-read` 500 the same day ([fix write-up](docs/notification-mark-read-500-fix.md)); still owes a live Realtime-push check, the sign-out/reauthenticate paths, and a clean `mypy web` run (unrelated numpy/Python-3.14 stub issue).
- [The privacy policy (/privacy) is a draft, not reviewed legal text](#the-privacy-policy-privacy-is-a-draft-not-reviewed-legal-text) — consent shipped against this draft; the legal review of the text is what is still owed.
- [Account deletion (Spec 4)](#account-deletion-spec-4--blocked-on-a-product-decision-not-on-engineering) — blocked on an unclosed product decision; both migrations written.
- [A conversation id now reaches the access log](#a-conversation-id-now-reaches-the-access-log) — a verification task, possibly already fine; unverified either way.
- [Six of the seven admin RPCs validate the actor without holding a lock](#six-of-the-seven-admin-rpcs-validate-the-actor-without-holding-a-lock) — a check-then-act window; pre-existing, not introduced by the actor gate.
- [A retention policy, and the bounds that depend on one](#a-retention-policy-and-the-bounds-that-depend-on-one) — blocked on a retention period nobody owns; covers the assistant-message and audit_log text bounds too.
- [`chat_sessions.owner_id` still has no foreign key](#chat_sessionsowner_id-still-has-no-foreign-key) — sequenced behind account deletion; the migration is small and the header's reasoning is already corrected.
- [Does "disabled" freeze an account's own profile edits?](#does-disabled-freeze-an-accounts-own-profile-edits-or-only-its-use-of-the-product) — blocked on a product decision, not on engineering.
- [Confirm the backup schedule, and rehearse a restore once](#confirm-the-backup-schedule-and-rehearse-a-restore-once) — dashboard task; the recovery position is currently an assumption.
- [Measure the real statement and lock timeouts on the write path](#measure-the-real-statement-and-lock-timeouts-on-the-write-path) — needs a call through PostgREST, not MCP.
- [Run the database assertions somewhere other than by hand](#run-the-database-assertions-somewhere-other-than-by-hand) — `supabase/tests/` exists and runs by hand only.

---

## Known bugs

### `auth_bp` carries no rate limit, so `/auth/login` is unlimited

**Where:** `web/api/app.py:2166` registers `auth_bp` with no limiter, while
`recover_bp` and `signup_bp` get one immediately after (`:2173-2184`).

**What is wrong.** The exemption is deliberate for logout — `web/api/auth.py:27-28`
argues that a 5/minute ceiling on signing out would be wrong, and it is right. But
`POST /auth/login` sits on the same blueprint and inherits it by accident. It
accepts unauthenticated credentials and calls `sign_in_with_password`, so it is an
unmetered credential-stuffing and account-enumeration oracle. No browser calls it —
`Services.login` goes browser-direct — which is why it has attracted no attention.

**Who it reaches.** Nobody through the UI. Anyone who can reach the public API.

**How it was found.** The 2026-09-05 review pass, as an aside to the logout finding
([the archived plan](docs/archive/2026-09-05_review-findings-fix.md), finding 1).

**What fixing it would disturb.** Either a per-route limit on login alone —
Flask-Limiter supports a route decorator, so the blueprint-wide exemption can stay —
or splitting login onto its own blueprint the way signup already is. The second is
tidier and matches the existing shape. Either way `test_rate_limit_keys.py` gains a
case, and someone has to decide whether a route no browser calls should simply be
deleted instead, which is a product decision rather than a fix.

---

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

### Ten source comments cite a plan file that has been archived

**Where:** `static/js/app.js:122`, `static/js/modules/handlers.js:457`,
`static/js/modules/route.js:4`, `static/js/modules/services.js:496,662,793`, and
`web/api/app.py:1356,1406,1677,2435`.

**What is wrong.** All of them cite `docs/per-tab-conversation-deep-linking-plan.md`
by section. That path no longer exists: the file is
`docs/archive/2026-08-22_per-tab-deep-linking.md`, carrying `status: superseded`.
So a reader following any of these citations finds nothing, and one who locates the
archived file is reading a document the archive itself marks as not-current —
exactly the failure mode `CLAUDE.md` warns about for `docs/archive/`.

**Who it reaches.** Every contributor who tries to follow the reasoning behind the
URL-as-pointer conversation model, which is most of them, because these comments
sit on the load-bearing parts of it.

**How it was found.** While editing `route.js` for the demo-flag fix; the citation
at its line 4 was checked and did not resolve.

**What fixing it would disturb.** Nothing functional — it is ten comment edits. The
real decision is what to point them AT: `docs/ARCHITECTURE.md` now holds the live
contract, but it does not carry the plan's section numbers (§1, §3.4, §5.1 and so
on) that these comments cite precisely. Either the citations lose that precision,
or ARCHITECTURE.md grows anchors to match. Deliberately not bundled into the
demo-flag commit: one concern per commit, and this one spans four files that change
for no other reason.

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

---

### Security email is English-only, on a product that is bilingual by construction

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

---

## Planned work

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

---

### Know what people actually ask — without reading anyone's conversation

**Where:** nothing records question text today. `ConversationStore`
(`web/services/conversation_store.py`) holds turns in RAM, TTL 3600s, LRU 500,
keyed to a cookie — so the record of what was asked dies within the hour. The
sidebar's suggested questions are hand-curated in `faq.yaml`, categorised and
translated, and were written by guessing at what readers want.

**Why it is wanted.** Two things at once: know which questions recur, and turn
that into a cheaper, faster answer. Put the genuinely common questions in the
sidebar and a large share of traffic converges on a small set of answers.

**The mechanism matters more than the goal here, so it is worth being exact.**
The obvious route — let an administrator read conversations and notice the
patterns — is both more invasive and worse at the job than the alternative.
Frequency is an aggregate question: it needs the _text_ of what was asked, not
who asked it. A table of `(asked_at, lang, scope, question_text, cited_count)`
with **no `user_id` column at all** answers "what are the twenty most common
questions this month" completely and exactly, in one `group by`, forever — while
reading transcripts answers it approximately, by hand, and only for as long as
someone keeps doing it.

Leaving identity out is not only a privacy posture, it is the thing that makes
the table cheap to keep: with no reader attached there is no retention deadline,
no disclosure to write, and no question about who else may be granted admin
later. If "how many _distinct_ people asked this" is ever needed, a per-period
salted hash gives that without storing who.

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
error either. Both want the question log first, and neither wants transcripts.

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

**Deliberately narrower than what was asked.** The original framing was to review
reader transcripts for analysis. Transcript browsing is declined here on two
grounds: it depends on conversation persistence, which does not exist yet (see
below) and is the largest deferred item in the admin plan; and it buys a worse
dataset at a much higher privacy cost than a question log that answers the same
question better. If per-reader context is ever genuinely needed — a specific
complaint to investigate — the narrow form is a reader-initiated _answer receipt_
they can share, not a browsing surface for everyone.

**Open questions.** Whether the log stores the raw question or a normalised form
— readers paste identifying details into questions, and a regulatory question can
name a product and a company. Some normalisation or truncation before storage may
be wanted, which trades exactness for safety. And whether "same question" is
string equality after normalisation or embedding similarity — the second catches
far more repeats and can also collide two questions that deserve different
answers, which on a regulatory surface is the more expensive mistake.

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
[`docs/notification-mark-read-500-fix.md`](docs/notification-mark-read-500-fix.md). 864-test
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

---

### The privacy policy (/privacy) is a draft, not reviewed legal text

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

### `chat_sessions.owner_id` still has no foreign key

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

**Where:** `supabase/tests/` (four files), and the absence of a database in CI.

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
