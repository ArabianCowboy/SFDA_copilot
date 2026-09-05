STATUS: IN PROGRESS — Commits A, B and C shipped 2026-09-05. Commit D still open.
Written 2026-09-05.

Supersedes nothing. When each commit lands, tick it in _Rollout_ below and update this
`STATUS:` line; when all four are done, archive this file per
[`docs/archive/README.md`](archive/README.md#adding-to-this-archive).

# Fixing the four findings from the 2026-09-05 review

## Context

A whole-codebase review followed by an adversarial re-review adjudicated four current-codebase
defects: three P2 and one P3. Both reviewers were read-only. Neither ran browser tests or live
SQL, and no probe established production frequency, so **none of the four is a demonstrated
regression** — introduction dates are unverified and no base diff exists. They are current
defects, which is enough.

Every `file:line` in this document was read in the session that wrote it. That re-verification
corrected four claims the review itself got wrong, and two of those corrections change what the
fix is allowed to do — they are called out inline rather than quietly absorbed.

| #   | Defect                                                                                           | Severity | Anchor                                                      |
| --- | ------------------------------------------------------------------------------------------------ | -------- | ----------------------------------------------------------- |
| 1   | `/auth/logout` revokes whatever identity a process-global singleton last saved, not the caller's | P2       | `web/api/auth.py:460`                                       |
| 2   | A token-limit-truncated answer is announced to the browser as complete                           | P2       | `web/services/openai_app.py:443-448`, `web/api/app.py:3493` |
| 3   | An empty answer is charged, persisted and returned 200 — on both chat routes                     | P2       | `web/api/app.py:3368`, `:3698`                              |
| 4   | Demo mode (`?testing=true`) is lost on conversation navigation                                   | P3       | `static/js/modules/route.js:30-32`                          |

Two false comments become true as a side effect, and both must land in the commit that makes
them so, per CLAUDE.md's document rule: `app.py:3363-3364` promises a refund that does not
happen, and `web/utils/supabase_client.py:73-75` calls a live route dead.

### Corrections to the review this plan is built on

1. **`apply_generation_settings` does not mutate the shared handler in place.** `app.py:2081-2117`
   builds a replacement through `openai_handler_factory` and rebinds `app.config["openai_handler"]`.
   Both that function's docstring (`:2084`) and `OpenAIHandler.__init__` (`openai_app.py:176-183`)
   state replacement-not-mutation as a contract. This rules out the review's first-draft fix shape.
2. **`UI.flagIncomplete` is defined at `ui.js:564`**, not in `handlers.js` — those were call sites,
   and there is a third at `handlers.js:1551` the review missed.
3. **`Route.commit()` is not a partial mitigation** for finding 4. It re-emits the search already
   on the URL, which `enter`/`go` have by then stripped. It is precedent for the pattern, not a
   fallback.
4. **`app.py:1726` is the wrong citation** for operator-editable `max_tokens` — that line is inside
   `build_testing_handler`. The real surface is `settings_service.py:28-31` + `admin.py:165` +
   `static/js/admin/ui.js:215`. The conclusion stands; the reference did not.

---

## Finding 1 — logout is not bound to the requester

### What is wrong

`web/api/auth.py:460` calls `supabase.auth.sign_out()` on the **anon singleton** from
`get_supabase()` (`web/utils/supabase_client.py:82-91`). The SDK's no-arg `sign_out()` defaults to
`scope: "global"`, reads _the client's own saved session_, and revokes every refresh token for
whoever that is. If the stored session has expired it is **refreshed first**, rotating the victim's
refresh token before revoking it.

The caller's own token is read at `auth.py:432` and used at `:443-444` and nowhere else.

The singleton's session is written by `_save_session`, reached from two places:

- `auth.py:308` `sign_in_with_password` — `POST /auth/login`. Registered unconditionally at
  `app.py:2166`, accepts unauthenticated credentials, and carries no rate limit because `auth_bp`
  has none (deliberate for logout, per `auth.py:27-28`; login inherits the exemption by accident).
  **The browser never calls it** — `services.js:377` logs in browser-direct.
- `auth.py:195` `sign_up` — `POST /auth/signup`, which _is_ live and browser-called since the
  registrations-pause work. It saves only when GoTrue returns a session, i.e. when email
  confirmation is off. The original review missed this path; it is the more reachable of the two.

So after any direct API login, the next anonymous `POST /auth/logout` revokes that user globally.
It is one-shot per poisoning — `_remove_session()` clears the singleton on the way out.

Two facts shape the fix:

- **No test reaches line 460.** `auth.py:446-447` short-circuits under `TESTING` and returns first.
- **The browser already performs the real revoke.** `services.js:518` calls
  `supabase.auth.signOut({ scope: 'global' })` browser-direct, after `endServerSession()`
  (`services.js:483-493`, called at `:501`). On the other path into the endpoint —
  `handlers.js:1976` `clearSessionState()`, reached when a session expires or is revoked — the
  comment at `:1970-1975` states the endpoint's job is Flask-side rotation, and the session is
  already dead upstream.

Verified separately: token verification passes the token explicitly
(`app.py:677-678` `supabase.auth.get_user(token)`), so a stale saved session on the singleton
affects nothing else. Line 460 is its only consumer.

### The change

> **This reverses an earlier decision, and the reversal is signed off (2026-09-05).** The first
> draft simply deleted the upstream revoke, on the reasoning that the browser always performs it.
> An adversarial review found three paths where it does not, and the installed SDK turned out to
> expose a correctly-scoped server-side revoke after all. Re-scoping fixes the wrong-principal bug
> _and_ keeps a working logout, for the same effort. Deletion was only ever right while a scoped
> call was believed not to exist.

**Two changes, and the first is the one that actually closes the hole.**

**1. Stop the singleton ever holding a session.** `supabase_client.py:76-78` builds the client as
`create_client(url, key, SyncClientOptions(httpx_client=_auth_http_client()))`. `SyncClientOptions`
also accepts `persist_session` and `auto_refresh_token` (verified against the installed package).
Setting both to `False` means `sign_in_with_password` and `sign_up` no longer write a session into
process-global state at all.

This removes the _polluter_, not just the consumer, and it is what the community recommends for a
shared server-side client in a threaded app: verify JWTs statelessly and never let the singleton
carry user state. Deleting `sign_out()` alone would leave `/auth/signup` — a live, browser-called
route — still saving whoever registered last into a client nothing ever clears again.

**2. Bind the revoke to the caller.** Replace the no-arg `sign_out()` at `auth.py:460` with
`supabase.auth.admin.sign_out(token, "global")` using the token already read at `:432`, and no-op
when that token is `None`. The signature is real: `gotrue_admin_api.py:70`
`def sign_out(self, jwt: str, scope: SignOutScope = "global") -> None`. Keep the existing
`try`/`except` and its 400 response — an unreachable GoTrue must not fail the logout, since the
Flask-side teardown at `:437-438` has already happened.

The `TESTING` short-circuit at `:446-447` stays, because the route still makes a network call.

**Why not just delete it.** Three paths run `/auth/logout` with no browser revoke behind it, so
deletion would leave a live refresh token in each:

1. `Services.logout()` calls `endServerSession()` **first** (`services.js:501`) and only then
   reaches `:504`, which throws when `this.supabase` is null — a blocked CDN clears the server
   session while the upstream refresh token stays valid until `exp`.
2. `clearSessionState()` (`handlers.js:1970-1976`) calls `endServerSession()` and nothing else, by
   design — its own comment says `Services.logout()` never ran on that path.
3. Any non-browser caller holding a session cookie.

In each, today's code is _also_ useless (the singleton is normally sessionless, so `sign_out()` is
a no-op making zero HTTP calls), so deletion loses nothing that currently works — but re-scoping
_gains_ something neither the current code nor deletion provides.

What survives unchanged is what was already correct: `purge_conversation_state()` and
`session.clear()` at `:437-438`, and `invalidate_token(token)` at `:444`, which
`web/services/token_verification_cache.py:448-464` keys entirely on the passed token.

Same commit:

- **`web/utils/supabase_client.py:73-75`** — the comment names the client's users as "token
  verification, logout, the dead signup/login routes". After this change logout is not one of them,
  and the claim about signup is _already_ false (`docs/ARCHITECTURE.md:318-322`). Rewrite both halves.
- **`docs/ARCHITECTURE.md:315-326`** — currently concludes "signup, recovery and logout are
  server-mediated; login is browser-direct". Logout stays server-mediated for session teardown but
  no longer touches GoTrue. Say so.
- Drop the now-unused `Any` import from `auth.py` if nothing else needs it.

### Tests

- `web/tests/test_auth_routes.py:162-191`
  `test_logout_drops_the_token_even_when_gotrue_fails` is the **only pin on the ordering** —
  that cache invalidation runs regardless of the GoTrue outcome. **Keep that assertion.** Do not
  replace it with a bare "was not called" negative, which passes vacuously if the route is ever
  gutted further. Add new assertions alongside it rather than swapping them in.
- `web/tests/test_auth_routes.py:46` — the `sign_out` stub becomes an `admin.sign_out` stub.
- **New:** a direct `POST /auth/login` followed by an unauthenticated `POST /auth/logout` revokes
  **the caller's** token, not the logged-in user's. Fails today — today it revokes the wrong
  principal. This is the regression test for the whole finding.
- **New:** after `sign_in_with_password`, the singleton holds no session (`persist_session=False`).
  Fails today.
- **New:** logout with no token makes no upstream call.
- `web/tests/test_session_isolation.py:125-154` — unaffected.

---

## Finding 3 — an empty answer is charged, persisted and returned 200

Sequenced before finding 2; see _Rollout_ for why.

### What is wrong

**Streaming.** `spent = True` sits _inside_ the token loop (`app.py:3368`), so an empty stream never
sets it — but all three refunds live in `except` handlers (`:3537`, `:3545`, `:3558`) and an empty
iterator raises nothing. Control falls through `_finalize_answer("")` at `:3372`, emits `final` at
`:3396` with `"response": ""`, calls `append_turn` at `:3431` and `_persist_turn` at `:3450`, emits
`suggestions` at `:3481` (a wasted provider call) and `done` at `:3490`. The claim is reported spent.

The comment at **`app.py:3363-3364`** reads: _"a provider that connects and returns an EMPTY stream
is refunded. The reader got no answer."_ It is false.

**Blocking.** `handle_chat` sets `spent = True` unconditionally at `:3698`, under a comment claiming
"The model answered" — also false here. `generate_response` returns `("", [])` without raising,
because `GenerationFailed`'s docstring (`openai_app.py:158-164`) defines an empty answer as "a
legitimate (if unhelpful) result", so the refund at `:3683-3694` never fires and `:3703`/`:3706`
persist an empty assistant message.

Production persistence is statically supported — `chat_append_turn` has no content guard and the
only CHECK constraint bounds `user` content, leaving assistant content unbounded so `''` passes.
Neither reviewer ran live SQL and none should be attempted for this.

**This is reachable, not theoretical.** A reasoning model's `max_completion_tokens` caps reasoning
tokens _and_ visible tokens together; exhausting the budget on hidden reasoning yields zero content
terminating on `finish_reason: "length"`. The provider bills every reasoning token regardless, so
the upstream cost is real even when the reader gets nothing — refunding the reader is a deliberate
product choice to absorb that cost, not a way to recover it.

### The change

**Streaming** — after the loop, before `_finalize_answer` at `:3372`, branch on an empty joined and
stripped answer: log it, `_release_daily_message(quota)`, emit an `error` frame carrying a new
`empty_answer` code, and `return` — skipping `final`, `append_turn`, `_persist_turn`, `suggestions`
and `done`. `hold.__exit__` still runs, because a `return` inside the generator falls through the
`finally` at `:3565-3571`.

It must be an **`error` event with a new code, never a new event name**: the comment at `:3466-3472`
records that `services.js` dispatches `on[frame.event]?.()` and silently drops anything
unregistered. Mirror the `persistence_unavailable` shape at `:3473-3479`.

**Blocking** — guard immediately before `spent = True` at `:3698`, mirroring the `GenerationFailed`
branch: refund, `hold.__exit__(None, None, None)`, return 503. **Use a distinct `empty_answer`
code, not the existing `generation_failed`** — reusing it would conflate "the provider returned
nothing" with "the provider was unreachable" in logs, metrics and any client branching on the code,
and those need telling apart. The HTTP status and message body can match; the code must not.

A second `hold.__exit__` from the `finally` at `:3720` is safe — `hold` is a `@contextmanager`
generator, so the second call raises `StopIteration` internally and returns `False` without
re-decrementing. The `GenerationFailed` branch at `:3690` already relies on exactly this.

**Ship both halves in one commit.** Split, either interim is incoherent: blocking-first refunds
empties while streaming still charges them, and streaming-first does the reverse. Do not let this
commit be bisected in review.

Correct both false comments in this commit.

The refund cannot double-fire: `_release_daily_message` (`app.py:863`) is idempotent per request via
`g._quota_released` at `:878-880`, and its docstring says the guard is there "rather than assumed"
because the RPC's `greatest(0, used - 1)` is not.

**The client mostly handles this already, but not entirely.** The `error` frame sets `failed` at
`handlers.js:1417-1419`; with no `final`, `:1500-1501` calls
`UI.markStreamIncomplete(handle, 'error')`, `:1508-1511` toasts and `:1524` puts the mascot in its
error state. Two gaps remain, and the first is a real bug:

**The quota counter goes stale after the refund.** `UI.updateQuotaCounter` is called from the
`done` handler (`handlers.js:1423`) and the blocking response (`:1599`) — and the empty path emits
no `done`. So the server refunds the allowance while the UI keeps showing one fewer remaining
question until the reader's next completed turn. A refund the reader cannot see is a refund they
will not believe. **Carry the post-refund quota in the `error` frame's payload and have the client
apply it**, which keeps the "no extra round trip" property the `done` frame's own comment at
`app.py:3496-3498` argues for. This is a small client change, so the commit is not server-only
after all — but it needs no new copy and no `ASSET_VERSION` reasoning beyond the bump itself.

**The toast says the wrong thing.** `:1509` routes any code other than `persistence_unavailable`
to `chat.sendFailed`, telling the reader their _message_ failed to send. For an empty answer the
message sent fine and the model returned nothing. The repo already reasons about exactly this
distinction at `:1504-1507`. Accurate copy needs a third branch plus a bilingual key pair, which is
outside the copy scope chosen for this plan — so it becomes a `TODO.md` entry, and this commit
ships the slightly-wrong-but-not-misleading existing string.

### Tests

There is no existing empty-stream test on either route — `iter([])` appears nowhere in
`web/tests/` — so this is new coverage, not changed coverage.

1. Streaming, empty stream → an `error` frame with `code == "empty_answer"`; no `final`, no
   `suggestions`, no `done`. Fails today (all three are emitted, `final.response` is `""`).
2. Streaming, empty stream → `generate_suggestions` not called. Fails today (`:3484` runs).
3. Streaming, empty stream → nothing recorded in history. Fails today (`:3431`).
4. Streaming, empty stream → quota usage unchanged. Fails today (reads 1).
5. Blocking, `generate_response` returning `("", [])` → 503 `empty_answer`/`generation_failed`,
   usage unchanged, nothing persisted. Fails today (200, `persisted: true`, `used: 1`).

Mind the fixture warning at `test_quota_routes.py:73-84`: the response body **must** be consumed or
`GeneratorExit` fires and silently zeroes the counter. An empty-stream test is exactly where that
trap bites.

---

## Finding 2 — the truncation signal is thrown away

### What is wrong

`stream_response` (`openai_app.py:420-448`) reads `chunk.choices[0].delta.content` and nothing else.
`app.py:3493` then writes the literal `"finish_reason": "stop"` into the `done` frame. A token-limit
truncation is byte-for-byte indistinguishable from a finished answer, and the client's completeness
rule is frame presence (`services.js:358`, `{ complete: seen.final && seen.done }`), not the field —
no JS reads `finish_reason` at all today.

Reachable by operator action, not only by a very long answer: `max_tokens` is runtime-editable
through the admin console (`settings_service.py:28-31`, `admin.py:165`,
`static/js/admin/ui.js:215`), shipping at `16384` (`config.yaml:246`).

Discarding `finish_reason` is one of the most commonly reported defects in streaming LLM
integrations, so this is a well-trodden failure rather than an exotic one.

### The hard constraint

**The finish reason must not be stored on the handler.** One worker, eight threads, one shared
instance; `OpenAIHandler` has no per-request mutable state today and documents immutability as a
contract (`openai_app.py:176-183`), and `apply_generation_settings` replaces rather than mutates
(`app.py:2081-2117`). An instance attribute would be read by whichever request got there last.

### The change

**Carriage.** A small `FinishSignal` dataclass beside `GenerationFailed` (`openai_app.py:157`),
passed as a keyword-only argument:

```python
def stream_response(self, query, search_results, category="all",
                    chat_history=None, lang="en", *, finish: FinishSignal | None = None)
```

A dataclass rather than a bare dict so mypy can check it. The caller allocates one per request, so
it lives on the caller's frame — eight threads, eight sinks. The yield type stays `Iterator[str]`,
which `generate_response`'s `"".join(...)` at `:463-465` depends on. Keyword-**only** so positional
drift cannot fill it. `generate_response` takes and forwards the same argument, so the two paths
still cannot drift.

**Read the field before the content guard.** `finish_reason` arrives on a terminal chunk whose
`delta.content` is `None` — not `""` — so it must be read after `if not chunk.choices: continue`
but _before_ `if content:`. The obvious placement would skip precisely the chunk that carries it.
The existing `if not chunk.choices` guard at `:444` is already correct and must stay: with
`include_usage` enabled a final chunk arrives whose `choices` is an empty list.

Set `"stop"` explicitly on the easter-egg early return at `:429-431`.

**The default is what makes this safe, and one test double proves it is needed.** Most doubles are
`lambda *a, **k: iter(ANSWER_TOKENS)` (e.g. `test_chat_stream.py:43`) and absorb anything — but
`test_eval_citations.py:59` is rigid: `def stream_response(self, query, search_results, category,
chat_history, lang)`, no `*args`, no `**kwargs`, no defaults. It survives only because nothing
passes `finish=` to it: `scripts/eval_citations.py:196` and `scripts/smoke_real.py:96` call
positionally, and only `app.py`'s two chat routes pass the new argument. **Do not thread `finish`
into the eval harness without also widening that fake.** An earlier draft of this plan claimed
every double took `**kwargs`; that was wrong, and this is the counterexample.

**Server.** Allocate the sink in `generate()` beside `spent`, pass it at `:3365`, and emit
`finish.reason or "unknown"` at `:3493`.

**Do the blocking route too.** `POST /api/chat` has the identical defect one route over:
`generate_response` (`openai_app.py:450-465`) discards the finish reason, so an answer cut by the
same operator-editable ceiling returns 200, renders whole, and persists as whole
(`app.py:3701-3719`) with no signal. Fixing streaming alone would leave that permanent — and worse,
would make it look deliberate. Since `generate_response` already forwards `finish`, the marginal
cost is a sink allocation in `handle_chat`, a field in the JSON body beside `persisted`, and the
same client branch in `Handlers.blockingChat` (which already reads `data?.quota` at
`handlers.js:1599`, so it has the shape for it). This was not in the original review's four
findings; it is the same defect and should not be left behind.

**Emit `"unknown"` when the provider reported nothing — do not default to `"stop"`.** An earlier
draft defaulted to `"stop"` to keep `test_chat_stream.py:195` green. That is the wrong trade, and
two independent sources said so: `"stop"` is a positive assertion of completeness that hydration,
the eval harness and future readers will trust, manufactured from an absence — the same
asserted-not-computed sin the `evidence_state` comment at `app.py:3404-3414` already condemns
elsewhere in this file. OpenAI-compatible gateways do not all emit a terminal `finish_reason`, so
the absence is not rare.

Honesty here costs nothing, because **the client flags only an explicit `"length"`**. `"unknown"`
renders exactly like `"stop"` — a whole answer, no warning — so the demo surface and the Playwright
fixtures are unaffected and no correct answer gets a warning badge. The difference is that the
server now logs the truth and the field stops lying.

Consequence: `test_chat_stream.py:195` **does** change, from `== "stop"` to `== "unknown"`. That is
a deliberate test change, not collateral. The easter-egg path still sets `"stop"` explicitly,
because that answer genuinely is complete.

This still **under-flags** a provider that truncates silently. The fix for that is a positive
signal, not a different default: `include_usage` exposes
`usage.completion_tokens_details.reasoning_tokens`, which separates budget exhaustion from a model
that chose to say nothing. Record it as a `TODO.md` entry rather than pretending the gap is closed.

**Client.** `handlers.js`'s `done` handler at `:1420-1424` captures the reason alongside the quota
read. On the completion path, after `UI.finishStreamingMessage` at `:1568` — the finish-then-flag
order the abort path already uses at `:1453-1455` — call `UI.flagIncomplete(handle, 'truncated')`.
Apply it at `:1499` too, inside the `failed`-with-`final` branch: an auxiliary failure does not
change the fact that the answer itself was cut off. **Not** at `:1549-1551`, which is unreachable
with a `length` reason — the reason only arrives on `done`, and `!result.complete` means `final`
never arrived. Worth a one-line comment there, since the omission looks like an oversight.

**Presentation.** `ui.js:564-571` understands two kinds; add a third.

**Both ternaries must change, not just the copy one.** `:566` reads
`kind === 'cancelled' ? 'is-cancelled' : 'is-errored'`, so a new `'truncated'` kind falls through to
`is-errored` and the bubble wears failure chrome while the note underneath claims a boundary — the
exact signal-swap `DESIGN.md:440` forbids, introduced by the change meant to respect it. Replace
both ternaries with `kind → class` and `kind → i18n key` maps so a fourth kind is a data change and
this cannot recur.

Do **not** route it through `error`: `.stream-note.error` (`components.css:2363-2365`) is `--danger`,
and `components.css:1639-1640` says in its own words that it "must not be reused" for a non-error
meaning. Nothing malfunctioned — the operator's ceiling did its job — and red would send the reader
retrying into the same ceiling.

**Use `--confidence`. Decided 2026-09-05.** `DESIGN.md:440` `[CORRECTNESS]` generalises to _"a
boundary the product is deliberately enforcing is marked in `--confidence`; a failure is marked in
`--danger`; the two must not be swapped for visual convenience."_ An operator-set `max_tokens`
ceiling is precisely a deliberately-enforced boundary, so the rule the repo already has answers
this. A third register was considered and rejected: `--warning` (`tokens.css:184`) is real, with
nine uses across `admin.css` and `components.css`, but it reads as "something might be wrong", and
nothing is wrong — the model reached a limit that was set on purpose. Inventing a third case for a
rule that already covers this one is how colour vocabularies rot.

Extend the `DESIGN.md:440` paragraph in the same commit to name the second `--confidence` surface,
so the next person does not re-litigate it from the quota notice alone.

Also add `.message.is-truncated .md-pending::after` to the caret-suppression rule at
`components.css:2347-2350`, so no cursor blinks under a finished answer. `color` is not among the
sixteen properties `test_css_contract.py` bans.

**Copy.** New key `runtime.chat.truncated`, beside `incomplete` at `en.yaml:31` and `ar.yaml:25`.
Nesting under the existing `chat` namespace is required — the eleven top-level `runtime.*` names are
pinned.

- English: **"Answer cut short — the length limit was reached"**
- Arabic: **"الإجابة غير مكتملة — تم بلوغ الحد الأقصى للطول"**

**The Arabic deliberately shares its opening clause with `chat.incomplete`** (`ar.yaml:25`,
"الإجابة غير مكتملة — حدث خطأ ما") and differs only after the dash. An earlier draft used
"الإجابة مقطوعة", which reads more abruptly than intended; the chosen wording is the owner's
(2026-09-05). The near-collision is the right outcome rather than a problem to design around —
both states genuinely _are_ an incomplete answer, the reader ever sees only one at a time, and the
clause after the dash is what carries the actual information. English does not mirror the
structure, and does not need to.

Bump `ASSET_VERSION` (`app.py:265`, currently `"warm69"`).

### Which branch wins when both conditions hold

An empty stream that terminated on `length` satisfies both findings. **The empty guard wins**,
because it returns before the `done` frame is built, so no finish reason is transmitted. That is the
right precedence, not an accident of ordering: "there is no answer" dominates "the answer stopped
early", and labelling a nonexistent answer as truncated implies there is something on screen to read.

The two remain **separate requirements** even though one patch touches both. Neither guard subsumes
the other, and they differ on every axis that matters:

|           | empty                    | truncated, non-empty                                     |
| --------- | ------------------------ | -------------------------------------------------------- |
| allowance | refunded                 | **charged** — a real, partial model call                 |
| history   | not written              | **written** — the reader's next question may refer to it |
| wire      | `error` frame, no `done` | normal `final` + `done`, `finish_reason: "length"`       |

Collapsing them into one "incomplete" concept would either refund a truncated answer or file an
empty one.

### Tests

Changing:

- `test_chat_stream.py:195` pins `done.finish_reason == "stop"`. It **changes to `"unknown"`** —
  the mock populates no sink, and the whole point of the default decision above is that the server
  stops claiming completeness it cannot observe. A deliberate test change, and the one place a
  reviewer should look to confirm the decision was made on purpose.
- `test_chat_stream.py:158-168` pins the frame order ending `final, suggestions, done`. It covers
  the non-empty path and stays; finding 3's different sequence is asserted by its own test rather
  than by loosening this one.
- `conftest.py:256`, `:350`, `:387` and `test_multi_tab_conversations.py:45` carry `done`-frame
  fixtures. This design does not change the frame's shape, so they should not need touching —
  confirm rather than assume.
- `test_frontend_architecture.py:40` and `:46-49` assert exact substrings of `handlers.js`,
  including a `count(...) >= 2`. Any tidying near the toast copy must be re-run against them.

New:

1. Handler-level: a terminal chunk carrying `finish_reason="length"` and `delta.content=None`
   populates the sink. Fails today (the parameter does not exist).
2. Handler-level: a provider reporting no finish reason leaves the sink empty — pinning that the
   default lives in the route, not the handler. Fails today.
3. Handler-level: two interleaved streams with two sinks each get their own value, and the handler
   grows no finish attribute. This is the immutability contract as an assertion. Fails today.
4. Route: a `length` finish emits `done.finish_reason == "length"` and still persists the turn.
   Fails today (hardcoded literal).
5. Route: a truncated answer is **still charged** — usage 1 _and_ reason `length`. Half passes
   today; it exists to stop a later reading of "incomplete" from collapsing the two branches and
   refunding a real model call.
6. Browser: a `length` `done` frame renders the truncation note **and** still shows the canonical
   answer with its source control. Fails today (no JS reads the field). Sibling to
   `test_source_panel.py:433`.
7. Browser: a normal `stop` finish is **not** flagged. Passes today, and guards the over-flagging
   failure mode the default argues about — without it, a later change of default ships silently.

---

## Finding 4 — demo mode is lost on navigation

### What is wrong

`route.js:30-32` `pathFor(id)` returns `` `${PREFIX}${id}` `` with no query string, and `enter`
(`:58`), `replace` (`:74`) and `go` (`:86`) all navigate through it. Six places read the flag live
off `window.location.search`, none cached:

| Read                                | Effect once the flag is gone                               |
| ----------------------------------- | ---------------------------------------------------------- |
| `services.js:367` `getSessionToken` | returns `null` instead of `'fake_token'`                   |
| `handlers.js:331` send guard        | opens the auth modal, toasts `chat.loginRequired`, aborts  |
| `services.js:462` `updatePassword`  | takes the real Supabase path                               |
| `services.js:503` `logout`          | throws `'Authentication service not available.'`           |
| `app.js:353`                        | on **reload** of `/c/<id>`, the demo never initialises     |
| `app.js:518`                        | `?testing=true&recovery=1` loses its recovery-ready branch |

Ordering makes turn 1 work and turn 2 fail: the token is read at `handlers.js:323`, `Route.enter`
runs at `:358`. Note `handlers.js:331` re-reads the flag independently, so the guard is defeated
too — the demo user takes the _signed-out_ branch rather than a graceful bypass.

`?lang=` is dropped by the same code path, and `i18n.js:63-68` already states that everything else
in the query has to survive its rewrite. It is the same bug wearing a different hat.

### The change

**Preserve an allow-list of query parameters in `pathFor` — `testing` and `lang` — not the whole
query string.** Allow-listing is the settled practice; blanket preservation is avoided precisely
because auth-callback and recovery parameters get carried into later history entries and
re-trigger their flows. That risk is concrete here: `isRecoveryCallback` (`services.js:102-113`)
reads `recovery=1`, and `handlers.js:1878-1880` deliberately _deletes_ it after a completed reset.

This one function fixes all six reads including reload, because the flag stays in the URL rather
than being re-derived. Reading it once into `AppState` is the better long-term design —
`state.js:9-53` has no `testing` key and all six sites re-read live — but it does **not** fix
reload, so it is a follow-up, not this fix.

Bump `ASSET_VERSION`.

Flagged rather than done silently: `route.js:4` and `services.js:496` cite
`docs/per-tab-conversation-deep-linking-plan.md`, which no longer exists at that path — it is
`docs/archive/2026-08-22_per-tab-deep-linking.md`, `status: superseded`. Repoint or drop.

### On `?testing=true` as a URL flag

A query-string auth-bypass flag is an anti-pattern in general (CWE-598), and preserving one more
widely deserves a second look. **It does not apply here, and this was verified rather than
assumed:** `app.py:660` gates the whole bypass on `current_app.config["TESTING"]`. In production
the branch at `:665` runs instead, so `?testing=true` merely makes the client send `fake_token` to
real Supabase verification, which rejects it. The flag is inert without a server started in testing
mode. The server gate is the control; the URL parameter is a demo affordance, not a credential.

### Tests

`web/tests/test_frontend.py:270-274` is page-load only — it asserts header text and sends nothing,
which is why this was **uncovered** rather than uncontradicted. No test sends two messages in demo
mode.

Add a sibling in that same file — already in the browser-marking allowlist at
`conftest.py:717-740`, so no allowlist edit — using the `browser_page` fixture
(`conftest.py:581-633`, **not** `authenticated_page`, which drives the real login form), going to
`/?testing=true` and sending **two** messages. `browser_page` mocks `/api/chat/stream` at context
level (`conftest.py:614-621`), so both turns resolve. Assert: the second send does not open
`#authModal`; the URL still carries `testing=true` after navigation; and `recovery=1` is **not**
carried into a `/c/<id>` entry.

### One consequence to accept deliberately

Preserving `testing` into `/c/<uuid>` means a **copied link replays demo mode for the recipient**
rather than opening the real conversation. That is inherent to keeping the flag in the URL, it is
low-severity (the server gate above means the recipient gets a demo, not access to anything), and
it is arguably what a demo link should do. But it should be a conscious call, not a side effect
nobody noticed — record it here so the next person does not treat it as a bug.

---

## Rollout

|     | Commit                                                                             | Finding | JS/CSS                | Browser suite |
| --- | ---------------------------------------------------------------------------------- | ------- | --------------------- | ------------- |
| ☑ A | Bind logout to the caller; stop the singleton holding sessions; two stale comments | 1       | no                    | no            |
| ☑ B | Refuse and refund an empty answer on both routes; correct the false comment        | 3       | **yes** (quota frame) | no            |
| ☑ C | Carry the provider's finish reason through to the reader, both routes              | 2       | **yes**               | yes           |
| ☐ D | Preserve demo and language flags across navigation                                 | 4       | **yes**               | yes           |

**B lands before C, which is the reverse of the obvious order.** An empty stream that terminated on
`length` satisfies both. Land C first and there is an interim release where such a turn is charged,
persisted, announced with `done`, _and_ decorated with a "cut short" note under a bubble containing
nothing — worse than either defect alone and genuinely confusing to debug. Land B first and C can
only ever annotate an answer that exists.

A and D are independent of the other two and of each other.

`ASSET_VERSION` (`app.py:265`) is bumped in **B**, **C** and **D** — B acquired a small client
change (the quota frame) after review. `APP_VERSION` (`app.py:271`) is **not** bumped by any of
them; rule 9 fires only on edits to `CLAUDE.md`.

**B must not be bisected.** Its streaming and blocking halves ship together — see that section.

## Verification

```bash
python -m pytest -m "not browser and not integration"      # what CI runs
python -m pytest -m browser --browser chromium             # C and D
ruff check . --fix && ruff format . && mypy web
npm run lint:fix && npm run format                         # C and D
pre-commit run --all-files
```

Beyond the suite:

- **A** — the regression test asserts the revoke targets the caller's token, not the singleton's
  saved one. No live SQL, and **do not test this against the production project** — a working fix
  revokes real sessions.
- **B** — the new tests are the verification. No live SQL. Check the quota counter by hand as well:
  force an empty stream and confirm the on-screen remaining count does not drop.
- **C** — run it (`FLASK_TESTING=true python web/api/app.py`, then `/?testing=true`) and force a
  `length` finish through the testing handler to see the note render in **both** languages
  (`/?lang=ar&testing=true`). The note is uppercase mono with tracking
  (`components.css:2352-2361`), and DESIGN.md's Joined-Script Rule `[CORRECTNESS]` (line 255) means
  the Arabic must be neither uppercased nor tracked. Verify by eye — `test_css_contract.py` scans
  repository CSS only and cannot see this.
- **D** — the two-message demo browser test, plus by hand: ask two questions under `?testing=true`,
  confirm the URL keeps the flag and no auth modal appears; reload `/c/<id>` and confirm the demo
  is still signed in; confirm `recovery=1` is not carried into a `/c/<id>` entry.

**Confirm each new test fails against the unmodified tree before believing it**, and read the diff
rather than trusting any delegated agent's self-report. Both rules are in CLAUDE.md because they
have caught real errors here before.

## Changed during implementation

Recorded rather than quietly absorbed, per the repo's reversal rule.

- **Commit B: `_release_daily_message` now returns the post-refund claim.** The plan said to put
  the refunded counter on the `error` frame, but there was no honest way to build that number —
  `QuotaClaim` is frozen and the refund can fail silently (no backend, RPC error). Computing
  `used - 1` at the call site would have reported a refund that did not happen. Returning the
  claim only when the refund actually lands means the frame carries `null` otherwise, which the
  client already renders as "no counter this turn".
- **Commit C: six test doubles needed widening, not one.** The adversarial review flagged
  `test_eval_citations.py:59` as the rigid fake. It was right about the class of problem and low
  on the count: `test_chat_api.py`, `test_new_chat.py` (x2) and `test_session_isolation.py` (x2)
  had explicit signatures too, and 18 tests failed with
  `TypeError: got an unexpected keyword argument 'finish'` until each grew `**kwargs`.
- **Commit C: `UI.addMessage` now returns its message element.** The blocking route had no handle
  to annotate — the plan assumed one existed. One line, one caller.

## Open questions this plan does not close

Record each as a `TODO.md` entry using the template at _How this file works_.

1. **Is GoTrue email confirmation on for this project?** It decides whether finding 1 was "requires
   a direct API login" or "arms on every signup". `en.yaml:214`'s copy assumes confirmation, which
   proves the copy, not the dashboard. [`docs/security-hardening-plan.md`](security-hardening-plan.md)
   Task 3 already needs someone in that dashboard — fold this in rather than making a second trip.
2. **`auth_bp` carries no rate limit**, so `/auth/login` is an unlimited credential-stuffing
   surface. Deliberate for logout; login inherits it by accident.
3. **Truncation from a provider that omits `finish_reason` is still undetected.** Emitting
   `"unknown"` makes the field honest but does not close the gap. The fix is a positive signal —
   `include_usage` plus `usage.completion_tokens_details.reasoning_tokens` — which would also
   separate "budget exhausted" from "the model chose to say nothing".
4. **An empty answer toasts "failed to send"**, which describes the wrong thing. Needs a third
   error-code branch and bilingual copy.
5. **Production frequency of empty and truncated responses is unmeasured.** It is the only evidence
   that could move findings 2 or 3 off P2, and it needs an operator, not a reviewer.
6. **`max_tokens` has no floor.** A reasoning model's budget covers hidden reasoning _and_ visible
   output, so a low ceiling produces empty answers by construction; guidance is to leave it unset
   or keep it well above the reasoning cost and control spend with `reasoning_effort` instead. The
   console lets an operator set a value that guarantees the failure findings 2 and 3 handle. A
   validated floor would prevent rather than report it.

## How this plan was built

Written 2026-09-05 against a read-only review and its adversarial re-review. Every `file:line` was
then re-read directly rather than carried over, which corrected four of the review's own claims
(listed at the top).

The draft was subsequently attacked by a second adversarial pass, which found five things this
document now incorporates and which the draft had wrong: the three no-browser-revoke paths that
make deletion the weaker fix for finding 1; the surviving signup pollution; the stale quota counter
after an empty-answer refund; the `is-errored` class mapping that would have contradicted the note
it sat under; and the blocking route's identical truncation blindness. A parallel pass over
upstream and community sources confirmed the singleton diagnosis, the reasoning-model empty-answer
mechanism (and that the provider bills for it regardless), and that allow-listing query parameters
is settled practice.

Two claims from that external pass were checked here and **rejected**: that `?testing=true` is a
CWE-598 auth bypass (it is server-gated at `app.py:660` and inert in production), and that a
missing `finish_reason` should be inferred rather than reported (the plan now reports `"unknown"`,
which is the honest form of the same concern).
