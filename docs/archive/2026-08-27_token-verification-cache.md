---
authority: historical
status: superseded
do_not_implement: true
archived: 2026-08-27
supersedes_note: >
  This document is a finished plan, built as written with two corrections made
  during implementation (see the closing note below). It is a record of what
  was decided and what it cost, not a specification.
live_authority:
  - docs/ARCHITECTURE.md
  - CLAUDE.md
  - TODO.md
---

> [!CAUTION]
> **You are reading history, not a specification.** Do not implement anything found
> in this file without first confirming it against `docs/ARCHITECTURE.md` or the code.
> Every heading below is prefixed `[HISTORICAL]` so a search result cannot be mistaken
> for current design.

STATUS: HISTORICAL RECORD — archived 2026-08-27. Nothing here is an instruction.
Live rules: `docs/ARCHITECTURE.md`, `CLAUDE.md`, `TODO.md`.

**Built as written, with two corrections made during implementation, not while
this plan was still being drafted:**

1. **§4.4's constructor sketch and §4.5's config comment still referenced the
   negative-cache design that §4.1 itself says was removed** (a
   `refusal_predicate` parameter, and a default `ttl_seconds` of 5 rather than
   the 0 the rest of the document settles on). Both were leftover from an
   earlier revision pass; corrected in place before this file was archived, to
   match what actually shipped: no refusal predicate, `ttl_seconds: 0`.
2. **§7's routing of the operational note to `docs/OPERATIONS.md` was wrong.**
   That file's own header restricts it to "state this repository cannot
   hold... none of it in version control" — `auth_token_cache.ttl_seconds`
   lives in `web/config.yaml`, which is in version control. The mechanism is
   documented in `docs/ARCHITECTURE.md` instead; no `OPERATIONS.md` entry was
   added.

Everything else below — the layer design, the revocation-window decision, the
module, the call-site diffs, the test matrix — shipped as written. See
`docs/archive/TODO-resolved.md`'s closing note on the original `TODO.md` entry
for the one-paragraph summary, and `TODO.md`'s _Enable the token-verification
cache once production numbers justify it_ for the one piece this plan
deliberately left open.

# [HISTORICAL] Eliminating per-request GoTrue verification latency

Closing the `TODO.md` entry _Every authenticated request pays a network round
trip to verify its token_ — resolved 2026-08-27; see
`docs/archive/TODO-resolved.md`.

That entry carried a standing instruction: **whoever picks this up must write down the
revocation window they are choosing, and say it out loud.** Section 1 does that. It is the
first thing in this document because it is the only part that cannot be undone by a
rollback — the code can be reverted, but a weakened check that shipped without anyone
naming the weakening is how a security posture erodes quietly.

---

## [HISTORICAL] Which document wins

This plan is subordinate to [`docs/ARCHITECTURE.md`](ARCHITECTURE.md). Where this file and
the live contract disagree after implementation, the contract wins and this file is stale.
On completion, follow [`docs/archive/README.md`](archive/README.md#adding-to-this-archive):
lift anything still open into `TODO.md`, `git mv` this file into `docs/archive/`, and add a
row to the archive index.

---

## [HISTORICAL] 1. Executive summary and the revocation window

### [HISTORICAL] The chosen architecture

**Not one mechanism — four layers, each with a different cost.** The mistake available here
is to treat "cache the token check" as a single decision with a single price. It is not.
Three of the four layers below cost _nothing_ in revocation latency, and only one of them
is the deliberate weakening the `TODO.md` entry warns about. Separating them is what lets
the weakening be small.

| Layer                            | What it does                                                                                                                | Applies to                            | Revocation cost                                                                         |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | --------------------------------------------------------------------------------------- |
| **0. Structural pre-validation** | Rejects input that cannot possibly be a live token — wrong shape, undecodable, `exp` already past — before any network call | Every request                         | **None.** A token past its own `exp` is dead by arithmetic.                             |
| **1. Single-flight**             | Concurrent requests bearing the _same_ token share one in-flight GoTrue call instead of making N                            | Every request, **admin included**     | **None.** Every burst still results in a live call to the authority. Nothing is stored. |
| **2. Positive result cache**     | A successful verification is reused for a short TTL                                                                         | Reader routes only — **admin exempt** | **Defaults to 0 — off.** Enabling it is a separate, measured decision (§1.4).           |

Layer 1 is the one that actually addresses worker starvation, and it is free. That is the
central finding of this plan: **the fan-out that exhausts the worker is concurrent and
same-token, so it is solved by a concurrency primitive, not by a cache.** The cache is a
latency improvement on top, and it is priced separately.

### [HISTORICAL] What is actually at stake: `get_user` is stateful

This is the fact the whole trade turns on, and it is easy to get backwards. **GoTrue's
`GET /user` is not a signature check.** Its `requireAuthentication` middleware parses the
JWT, then calls `maybeLoadUserOrSession`, which looks the `session_id` claim up in
`auth.sessions` and returns a **403 `session_not_found`** when the row is gone; it also
rejects a banned user with 403 `user_banned`. Verified against the middleware source in
`supabase/auth`, `internal/api/auth.go`.

Two consequences, and they point in opposite directions:

- **The Flask hop has 0-second revocation today, and that is a real property being spent.**
  Not a theoretical one. `POST /admin/api/users/<id>/revoke-sessions` deletes the session
  rows (via the password-update mechanism in
  [`auth_admin.py:153`](../web/services/auth_admin.py)), and the very next request through
  `_authenticate_request` gets a 403 from GoTrue and is turned away.
- **It is the _only_ hop with that property.** GoTrue's own README: _"the JWT tokens will
  still be valid for stateless auth until they expire."_ Stateless auth is PostgREST — which
  this app uses browser-direct for the reader's own `profiles` row and preference writes
  ([`docs/ARCHITECTURE.md`](ARCHITECTURE.md) two-table-access-patterns). So a revoked reader
  already keeps PostgREST access for up to `exp` (default 3600s) no matter what this plan
  does.

### [HISTORICAL] What actually goes stale — a much narrower set than it first appears

Both source plans, and the `TODO.md` entry itself, imply that caching the token check
delays "revocation" broadly. It does not. The app has **two independent axes**, and
`admin.py:565`'s own docstring says so: _"It does not touch `is_disabled` — chat access and
session validity are a deliberately separate axis."_

| Operator action                                                                   | Mechanism                                                | Delayed by this cache?                                           |
| --------------------------------------------------------------------------------- | -------------------------------------------------------- | ---------------------------------------------------------------- |
| Disable an account                                                                | `is_disabled` column on `profiles`, via `set_user_flags` | **No.** Flags path, `IdentityFlagsCache`, `fresh=True` on admin. |
| Demote an administrator                                                           | `role` column on `profiles`                              | **No.** Same flags path.                                         |
| `_actor_still_admin` mid-request re-check ([`admin.py:545`](../web/api/admin.py)) | Postgres read via `backend.get_user`                     | **No.** Never touched GoTrue.                                    |
| **Revoke sessions / logout / password change**                                    | **GoTrue `auth.sessions` rows**                          | **Yes. This is the entire blast radius.**                        |

So the trade is not "authorization goes stale for N seconds". It is precisely: **a session
that was revoked at GoTrue may keep authenticating on reader routes for up to the TTL.**
Role and disabled state remain exactly as fresh as they are today.

### [HISTORICAL] The stated revocation window

> **Zero seconds as shipped.** The positive cache defaults to `ttl_seconds: 0`, so this
> change introduces **no revocation window at all** on first deploy. Single-flight, the
> part that fixes worker starvation, carries no freshness cost and is what ships.
>
> **If and when positive caching is enabled — 5 seconds, reader routes only, and only for
> session revocation.** A GoTrue session revoked outside this application may keep
> authenticating on reader routes for at most that long, never past the token's `exp`.
>
> **0 seconds on `/admin/*`** in every configuration. Operator requests are always verified
> against live GoTrue authority.
>
> **No additional staleness for role or disabled state.** Those never enter this cache. They
> keep exactly the freshness they have today, which is **not zero on reader routes**: the
> flags cache has its own 30-second TTL (`identity_cache.py:105-118`) and `fresh=True` is
> selected only for the admin blueprint. A disabled reader can already remain admitted for
> up to that window, before and after this change alike.
>
> **0 seconds for anything this application mediates** — logout, admin revoke-sessions,
> admin email change — which evict explicitly.
>
> **Unchanged, and outside this plan's reach: up to `exp` (~3600s) on the browser-direct
> PostgREST path**, and on every browser-direct credential change (§4.6).

The residual exposure is therefore: a browser-direct password change, a browser-direct
"sign out other sessions" ([`static/js/account/handlers.js:248`](../static/js/account/handlers.js)),
or a revocation performed in the Supabase dashboard — for up to 30 seconds, on reader
routes only, for a reader who already retains PostgREST access for up to an hour by
construction.

### [HISTORICAL] 1.4 Why the positive cache ships off, and what enabling it would require

An earlier draft of this plan set the TTL to 5 seconds, then raised it to 30 on the strength
of the PostgREST observation above. **That second move was wrong and is reversed here.**
PostgREST is the browser-direct path for the reader's own `profiles` row
([`docs/ARCHITECTURE.md`](ARCHITECTURE.md) two-table-access-patterns). Chat, transcript
history, the sidebar and the full-account **export** are all Flask-mediated. "The other hop
already leaks for an hour" is a fact about `profiles`; it is not a licence to widen the
window on the hop that guards conversation data. Existing exposure somewhere else is never
an argument for more exposure here.

Worse, the plan has **no measurement**. There is no hit-rate, no GoTrue latency
distribution, and no QPS figure in this repository that shows a positive cache is needed at
all once single-flight exists. Single-flight fixes the concurrent same-token fan-out, which
is the documented starvation mechanism. What a positive cache adds beyond that is reuse
across _sequential_ reader requests — plausibly useful, entirely unmeasured.

So the positive cache ships **disabled**, and enabling it is a separate decision with a
stated bar:

1. Deploy with `ttl_seconds: 0` and the metrics in §7.
2. Show, from production numbers, what fraction of reader verifications are sequential
   repeats within a candidate window, and what that costs in GoTrue latency today.
3. Only if that fraction is material, set `ttl_seconds: 5` — and write the 5-second window
   into `TODO.md` in the same commit, per that file's standing instruction.

5 seconds, not 30, because the threat this window actually serves is a reader whose account
was just compromised: they change their password and sign out other sessions, both
browser-direct, neither of which this server can evict (§4.6). The attacker's token keeps
working for the full TTL against chat history and export. That is the number to minimise,
and it is not helped by anything PostgREST does.

**This is not a merge with `IdentityFlagsCache`.** Equal TTLs are a deliberate coincidence,
not shared machinery: the two remain separate modules, separately keyed, with opposite
outage postures (§3). If one TTL later needs to move, the other does not follow.

### [HISTORICAL] Why not local JWT verification (Option B)

Option B was evaluated and **rejected for now on evidence, not preference.** Three findings,
each independently sufficient:

1. **This project has no asymmetric signing keys.** `GET
https://<project>.supabase.co/auth/v1/.well-known/jwks.json` returns `{"keys":[]}`
   (checked 2026-08-27). The project is still on the legacy HS256 shared secret.
2. **The SDK's own local path would therefore make zero network calls' worth of
   difference.** `supabase_auth`'s `SyncGoTrueClient.get_claims()` branches on
   `if "kid" not in header or header["alg"] == "HS256": self.get_user(token)` — an HS256
   token falls straight through to the same network call this plan is trying to remove.
3. **It regresses the incident-containment surface.** `POST
/admin/api/users/<id>/revoke-sessions` ([`web/api/admin.py:565`](../web/api/admin.py))
   takes effect on the very next request today. Under local verification it is invisible
   until the token expires — `jwt_expiry` defaults to 3600 seconds. Trading a 1-request
   window for a 1-hour window on the route whose entire docstring is about containing an
   incident is the wrong direction.

Option B is not dead; it is **blocked on an operational prerequisite outside this repo**.
Section 8 records what would have to be true first.

---

## [HISTORICAL] 2. Audit: where the round trips actually are

### [HISTORICAL] The single call site

`supabase.auth.get_user(token)` at [`web/api/app.py:548`](../web/api/app.py), inside
`_authenticate_request` ([`app.py:530`](../web/api/app.py)). There is exactly one, reached
three ways:

| Entry point                           | Location                                 |
| ------------------------------------- | ---------------------------------------- |
| `@auth_required` decorator            | [`app.py:617`](../web/api/app.py)        |
| `admin_bp.before_request` → `_gate`   | [`admin.py:99`](../web/api/admin.py)     |
| `account_bp.before_request` → `_gate` | [`account.py:76`](../web/api/account.py) |

Rate limiting does **not** add a second call. `_account_rate_key`
([`app.py:672`](../web/api/app.py)) and `_admin_notification_rate_key`
([`admin.py:76`](../web/api/admin.py)) both hash the bearer token instead, and both
docstrings say why: Flask-Limiter's hook runs before the blueprint gate, so `g.identity`
does not exist yet.

### [HISTORICAL] Fan-out per user action

**`TODO.md` undercounts the console.** It says four. The console boot in
[`static/js/admin.js:69-80`](../static/js/admin.js) awaits `services.identity()`, then
fires five tab initialisers, and `initNotificationsTab` itself awaits `loadHistory()`
([`static/js/admin/handlers.js:773`](../static/js/admin/handlers.js)) plus a purge-settings
read.

| Action                 | Verifications | Notes                                                                                                                                                                 |
| ---------------------- | ------------: | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Load `/admin`          |       **6-7** | `identity`, `registrations`, `settings`, `users`, `audit`, notification history, purge-settings. The shell itself is ungated ([`admin.py:134`](../web/api/admin.py)). |
| Open one admin account |        **+2** | `users/<id>` and a filtered `audit`.                                                                                                                                  |
| One chat turn          |         **1** | Both chat routes are `@auth_required`.                                                                                                                                |
| Load `/account`        |         **1** | `Services.getIdentity()` once ([`static/js/account.js`](../static/js/account.js)); the profile read is browser-direct to PostgREST.                                   |

Correct the count in `TODO.md` when closing the entry — the number is the evidence for the
starvation claim and it should be right.

**The console burst is concurrent and same-token.** Six or seven requests, one bearer token,
fired together. That is why Layer 1 matters and why it must apply to the admin blueprint
even though Layer 2 does not: it collapses 7 GoTrue calls into 1 while still asking the
authority.

### [HISTORICAL] Behaviour a cache must not silently change

Each of these runs today on every successful verification and must keep running on a cache
hit. A hit returns an identity; it is not permission to skip the tail of the function.

| Behaviour                                                                               | Location                                                        |
| --------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| Session rotation when the identity changes                                              | `_bind_session_to_identity` ([`app.py:334`](../web/api/app.py)) |
| `session["supabase_access_token"]`, `session["user_email"]`, `session["is_admin_hint"]` | [`app.py:603-609`](../web/api/app.py)                           |
| Disabled account → **403**, still signed in                                             | [`app.py:611-614`](../web/api/app.py)                           |
| Outage → **503**, session intact                                                        | [`app.py:571-582`](../web/api/app.py)                           |
| Our fault → **500**, session intact                                                     | [`app.py:584-593`](../web/api/app.py)                           |
| Refusal → **401**, session cleared                                                      | [`app.py:595-601`](../web/api/app.py)                           |
| `user.id` falling back to `user.email`                                                  | [`app.py:558-560`](../web/api/app.py)                           |
| `fresh=(request.blueprint == "admin")` on the _flags_ lookup                            | [`app.py:561-569`](../web/api/app.py)                           |
| TESTING short-circuits before any Supabase client exists                                | [`app.py:536-541`](../web/api/app.py)                           |

### [HISTORICAL] Invalidation call sites that exist today

Exactly one: [`admin.py:909`](../web/api/admin.py), in `patch_user`, invalidating
`identity_flags`. Pinned by `test_the_identity_cache_is_invalidated_so_the_change_takes_effect`
([`web/tests/test_admin_users.py:320`](../web/tests/test_admin_users.py)).

`revoke_sessions` ([`admin.py:565`](../web/api/admin.py)), `change_email`
([`admin.py:662`](../web/api/admin.py)) and `logout` ([`auth.py:424`](../web/api/auth.py))
invalidate nothing — correctly today, because none of them change _flags_. All three must
invalidate the **token** cache. That is the largest correctness surface in this change.

---

## [HISTORICAL] 3. The `fresh=True` invariant, and what it means one layer up

Today `fresh` is a _flags_ concept: `resolve_identity_flags(..., fresh=...)`
([`admin_store.py:848`](../web/services/admin_store.py)) skips the 30-second flags TTL for
console requests, because being 30 seconds behind a demotion is unacceptable on the surface
that can disable an account.

This plan introduces a second, independent cache one layer up — token verification — and
the invariant has to be restated for it rather than inherited:

- **A token-level cache with a `fresh` bypass is coherent**, but only if `fresh` means
  "ask the authority for this request", not "prefer a newer cache entry".
- The two `fresh` decisions are made from the same predicate (`request.blueprint == "admin"`)
  and must stay that way. **Do not** introduce a second, separately-configured flag; two
  predicates that are meant to agree will eventually disagree.
- Consequence: on `/admin/*`, both caches are bypassed, and the console keeps exactly the
  authority it has today. Layer 1 still applies, so the burst still collapses.

**Isolation from `IdentityFlagsCache` is mandatory.** They are different caches answering
different questions:

|                 | `IdentityFlagsCache`                          | `TokenVerificationCache` (new)                   |
| --------------- | --------------------------------------------- | ------------------------------------------------ |
| Question        | "What standing does this verified user have?" | "Did GoTrue accept this bearer token?"           |
| Key             | `user_id`                                     | `sha256(token)`                                  |
| Authority       | Postgres `public.profiles`                    | GoTrue                                           |
| Outage fallback | `last_known()` — fails **open** on access     | none — fails **closed**, retries                 |
| TTL             | 30s                                           | 30s — equal by decision, not by sharing. See §1. |

The keying alone forbids a merge: when a request arrives, the server holds a token and does
**not** know the `user_id`. A cache keyed by `user_id` cannot be consulted without first
making the call it exists to avoid.

Do not extend `IdentityFlagsCache` to cover both. Its outage fallback is deliberately
fail-open, and that is exactly wrong for token verification.

---

## [HISTORICAL] 4. Implementation

### [HISTORICAL] 4.1 New module — `web/services/token_verification_cache.py`

Public API:

```python
class VerifiedIdentity          # frozen: user_id, email, token_exp
class TokenVerificationCache
    get_or_verify(token, verify, *, use_cache=True) -> VerifiedIdentity
    invalidate_token(token) -> None
    invalidate_user(user_id) -> None
    invalidate_all() -> None
    __len__()
```

`get_or_verify` raises whatever `verify` raised. Classification stays in `app.py` where it
already lives; this module never decides what a failure _means_.

```diff
diff --git a/web/services/token_verification_cache.py b/web/services/token_verification_cache.py
new file mode 100644
--- /dev/null
+++ b/web/services/token_verification_cache.py
@@
+"""Did GoTrue accept this bearer token? — asked once per burst, remembered briefly.
+
+Deliberately NOT ``IdentityFlagsCache``, and the distinction is the whole
+reason this module exists rather than a widened parameter over there. That
+cache answers "what standing does this already-verified reader have", keyed by
+``user_id``, backed by Postgres, and it fails **open** on an outage because a
+retrieval blip must not take down a product whose job is answering one
+question. This cache answers "is this credential good", keyed by a digest of
+the credential, backed by GoTrue, and it fails **closed**, because the safe
+reading of "we could not check a credential" is not "admit them".
+
+Merging the two is not merely untidy, it is unimplementable in the direction
+that matters: when a request arrives the server holds a token and does not yet
+know the ``user_id``, so a ``user_id``-keyed cache cannot be consulted without
+first making the call it exists to avoid.
+
+Three mechanisms live here and they are priced separately, because conflating
+them is how a small latency fix becomes an unexamined security change:
+
+* **Single-flight** costs nothing in freshness. Concurrent requests bearing the
+  same token wait on one in-flight verification instead of making N. Every
+  burst still reaches the authority; nothing is remembered. This is what
+  actually answers the worker-starvation problem, and it is why the admin
+  blueprint uses this class at all despite taking none of the caching.
+* **The positive cache** is the deliberate trade, bounded by a short TTL and by
+  the token's own ``exp``, and applied to reader routes only.
+* **The negative cache** remembers a *definitive* refusal. A rejected JWT never
+  becomes valid again, so this costs nothing in revocation terms; it exists so
+  a client retrying an expired token — which the admin console does on every
+  401 by design — does not turn one dead credential into a stream of doomed
+  round trips.
+
+PROCESS-LOCAL, exactly like ``ConversationStore`` and ``IdentityFlagsCache``,
+and correct for the same stated deployment reason: this app runs
+``--workers 1 --threads 8``.
+"""
+
+from __future__ import annotations
+
+import hashlib
+import threading
+import time
+from collections import OrderedDict
+from dataclasses import dataclass
+
+from typing import Callable
+
+
+@dataclass(frozen=True)
+class VerifiedIdentity:
+    """What GoTrue confirmed, reduced to what the request path actually reads.
+
+    Frozen, and deliberately not the provider's ``User`` object: caching a
+    library type means a library upgrade can change what is cached without any
+    line in this repository changing. ``token_exp`` is carried so the cache can
+    refuse to outlive the credential it describes.
+    """
+
+    user_id: str
+    email: str | None
+    token_exp: float | None
+
+
+class _Flight:
+    """One in-flight verification, and the result or failure it produced."""
+
+    __slots__ = ("done", "identity", "error", "started")
+
+    def __init__(self, started: float) -> None:
+        self.done = threading.Event()
+        self.identity: VerifiedIdentity | None = None
+        self.error: BaseException | None = None
+        self.started = started
+
+
+class TokenVerificationCache:
+    def __init__(
+        self,
+        # 0 = single-flight only, nothing remembered. THE DEFAULT. See §1.4.
+        ttl_seconds: float = 0.0,
+        max_entries: int = 2000,
+        max_in_flight: int = 64,
+        # 5s is the auth ceiling in supabase_client._auth_timeout; the grace is
+        # for the publish that follows it. Derived from that constant, not
+        # chosen independently, so the two cannot drift apart silently.
+        wait_timeout_seconds: float = 5.5,
+    ) -> None:
+        self._ttl = ttl_seconds
+        self._max = max_entries
+        self._max_in_flight = max_in_flight
+        self._wait_timeout = wait_timeout_seconds
+        self._lock = threading.Lock()
+        self._data: OrderedDict[str, tuple[float, VerifiedIdentity]] = OrderedDict()
+        self._flights: dict[str, _Flight] = {}
+        # Reverse index so `invalidate_user` is a lookup rather than a scan of
+        # every live token. Holds digests only — no plaintext token is ever
+        # stored by this class, in either direction.
+        self._by_user: dict[str, set[str]] = {}
+        # When each user was last invalidated. `invalidate_user` alone cannot
+        # stop a verification that is already in flight, and that verification
+        # would otherwise publish after the revocation and restore the very
+        # session that was just ended — with a fresh TTL on top. Publication is
+        # therefore ordered by when a flight STARTED, exactly as
+        # `IdentityFlagsCache.begin_fetch`/`put` orders the flags lookup.
+        self._user_invalidated_at: dict[str, float] = {}
+        # The same guard keyed by digest, for `invalidate_token` — which runs
+        # on logout, where the user id is not always in hand.
+        self._token_invalidated_at: dict[str, float] = {}
+
+    @staticmethod
+    def _now() -> float:
+        return time.monotonic()
+
+    @staticmethod
+    def _key(token: str) -> str:
+        """SHA-256, matching `_account_rate_key`'s existing pattern.
+
+        A raw bearer token as a dict key is a bearer token in a heap dump, in a
+        `repr()`, and in whatever a future debug endpoint decides to enumerate.
+        The digest is just as unique and carries no credential.
+        """
+        return hashlib.sha256(token.encode("utf-8")).hexdigest()
```

The body of `get_or_verify` — the part where the races live:

```diff
+    def get_or_verify(
+        self,
+        token: str,
+        verify: Callable[[], VerifiedIdentity],
+        *,
+        use_cache: bool = True,
+    ) -> VerifiedIdentity:
+        """One verification per token per burst; a short memory when allowed.
+
+        ``use_cache=False`` (the admin blueprint) still single-flights — the
+        console's own boot fires seven concurrent requests on one token — but
+        neither reads nor writes a remembered answer. Every console request
+        therefore rests on a live answer from the authority, which is the
+        property `fresh=True` protects one layer down.
+
+        Raises whatever ``verify`` raised. This class never decides whether a
+        failure was an outage or a refusal; `_is_upstream_outage` and
+        `_is_auth_refusal` in app.py own that, and duplicating the judgement
+        here would give the app two places to disagree with itself about
+        whether to sign somebody out.
+        """
+        key = self._key(token)
+
+        with self._lock:
+            if use_cache:
+                if (hit := self._live_entry(key)) is not None:
+                    return hit
+
+            flight = self._flights.get(key)
+            if flight is None:
+                # A bounded map. Unique invalid tokens are attacker-supplied,
+                # so an unbounded one is a memory-growth primitive. Past the
+                # bound, verify without single-flight rather than refuse: the
+                # request is still answered correctly, just without the
+                # collapse.
+                if len(self._flights) >= self._max_in_flight:
+                    owner, flight = True, _Flight(self._now())
+                else:
+                    flight = _Flight(self._now())
+                    self._flights[key] = flight
+                    owner = True
+            else:
+                owner = False
+
+        if not owner:
+            # No lock held across the wait, and no lock held across the network
+            # call below. A five-second auth timeout under a cache lock would
+            # stall all eight threads on a cache that has nothing to do with
+            # their tokens — turning a latency fix into the outage it was
+            # written to prevent.
+            #
+            # BOUNDED, and the bound is not decoration. An unbounded wait makes
+            # every waiter's liveness depend on the leader reaching its
+            # `done.set()` — so any path that does not (a MemoryError between
+            # the call and the publish, a thread killed mid-flight) parks the
+            # remaining seven threads forever, which is a worse outage than the
+            # one being fixed and is invisible until it happens. The ceiling is
+            # derived from the auth timeout rather than chosen: a leader that
+            # has not answered within its own 5s budget plus grace is not going
+            # to.
+            if not flight.done.wait(self._wait_timeout):
+                # An outage, and it must classify as one upstream — 503, session
+                # intact. The waiter does NOT fall through to its own
+                # `verify()`: eight threads that each give up and start their
+                # own GoTrue call is the stampede this whole mechanism exists
+                # to prevent, arriving at the exact moment GoTrue is least able
+                # to absorb it.
+                raise TokenVerificationTimeout(self._wait_timeout)
+            if flight.error is not None:
+                # Waiters inherit the owner's failure rather than retrying.
+                # Retrying here would make N threads presenting one bad token
+                # produce N sequential GoTrue calls — a stampede on precisely
+                # the path an attacker controls.
+                raise flight.error
+            assert flight.identity is not None
+            return flight.identity
+
+        try:
+            identity = verify()
+        except BaseException as exception:
+            flight.error = exception
+            with self._lock:
+                # A failure is NEVER remembered. See §5.
+                self._flights.pop(key, None)
+            flight.done.set()
+            raise
+
+        flight.identity = identity
+        with self._lock:
+            self._flights.pop(key, None)
+            if use_cache:
+                self._publish(key, identity, started=flight.started)
+        flight.done.set()
+        return identity
```

Publication, with both staleness guards and the `exp` ceiling:

```diff
+    def _publish(self, key: str, identity: VerifiedIdentity, *, started: float) -> None:
+        """Store a result, unless something revoked it while it was in flight.
+
+        Caller holds the lock. Two rejections, and both are the same bug seen
+        from two directions: an answer that was true when the call started and
+        is not true now must not be written down as if it were current.
+        """
+        invalidated = self._token_invalidated_at.get(key)
+        if invalidated is not None and started <= invalidated:
+            return
+        invalidated = self._user_invalidated_at.get(identity.user_id)
+        if invalidated is not None and started <= invalidated:
+            return
+
+        ttl = self._ttl
+        if identity.token_exp is not None:
+            # The cache may shorten a token's life. It may never extend it.
+            remaining = identity.token_exp - time.time()
+            if remaining <= 0:
+                return
+            ttl = min(ttl, remaining)
+
+        self._data[key] = (self._now() + ttl, identity)
+        self._data.move_to_end(key)
+        self._by_user.setdefault(identity.user_id, set()).add(key)
+        self._evict()
```

`invalidate_user` becomes an index lookup rather than a scan, and — the part that matters —
it also stamps the user so a flight already in progress cannot publish afterwards:

```diff
+    def invalidate_user(self, user_id: str) -> None:
+        """Drop every live token for one reader, including one mid-verification.
+
+        The stamp is not optional. Dropping the stored entries alone leaves any
+        verification that started before this call free to finish and publish —
+        which is the revoked session walking back in with a full fresh TTL,
+        moments after an operator watched the console tell them it was gone.
+        """
+        with self._lock:
+            now = self._now()
+            self._user_invalidated_at[user_id] = now
+            for key in self._by_user.pop(user_id, set()):
+                self._data.pop(key, None)
+                self._token_invalidated_at[key] = now
```

`_is_cacheable_refusal` deliberately reuses the app's classifier rather than restating it:

```diff
+    # NO `_is_cacheable_refusal`, and no negative cache. An earlier draft had one.
+    # It was removed after an adversarial review found two independent defects
+    # that are worth recording, because the idea is tempting enough to be
+    # proposed again:
+    #
+    #   1. It was to be gated on `_is_auth_refusal`, which returns True for ANY
+    #      `AuthError` carrying an integer status — and `AuthApiError` is
+    #      constructed with `status_code or 500` (see that function's own
+    #      docstring, app.py:520-527). A 429 or a 500 from GoTrue is a refusal
+    #      by that predicate. Caching it would have remembered an OUTAGE as a
+    #      credential verdict — the exact failure the whole `_is_upstream_outage`
+    #      / `_is_auth_refusal` split exists to prevent. The app gets this right
+    #      only because it tests for outage FIRST; a cache calling the refusal
+    #      predicate alone inherits none of that ordering.
+    #   2. "A rejected JWT never becomes valid again" is false. GoTrue returns
+    #      403 `user_banned` from GET /user, and a ban can be lifted while the
+    #      same unexpired token is still in the reader's hands. A remembered
+    #      "no" would then be wrong, and `_handle_unauthorized` destroys the
+    #      session on the way out.
+    #
+    # Its only real benefit was absorbing the console's retry-once-on-401
+    # (static/js/admin/services.js) — and the console is exempt from this cache
+    # entirely, so that benefit never existed.
```

`_live_entry`, `_evict` (LRU over `_max`, plus eviction of the parallel
`_by_user` and stamp maps) and `invalidate_token` / `invalidate_all` follow the same shape
as `IdentityFlagsCache` and are omitted here for length. **One departure from that class is
deliberate: expired entries here are dropped, not retained.** `IdentityFlagsCache` keeps
them because `last_known()` needs a stale answer to keep a disabled account out during an
outage. There is no equivalent here — a stale "this token was good" is exactly what must not
survive — so retention would be a liability with no compensating use.

### [HISTORICAL] 4.2 Layer 0 — structural pre-validation, `web/api/app.py`

Insert before the network call. **This is input validation, not authentication**, and the
comment must say so, because a reader who mistakes it for authentication will eventually
"optimise" the GoTrue call away.

```diff
@@ web/api/app.py:544
         try:
             supabase = get_supabase()
-            response = supabase.auth.get_user(token)
+            # NOT authentication. A structural check that costs no network and
+            # can only ever say "this cannot possibly be live" — three
+            # segments, base64url-decodable, and an `exp` that has not already
+            # passed. A token that clears it is not thereby trusted; it still
+            # goes to GoTrue below, which remains the only authority.
+            #
+            # It is here because the one attack this plan's cache does NOT
+            # help with is a flood of DISTINCT invalid tokens: every one is a
+            # cache miss, and eight concurrent misses hold all eight threads
+            # for a network round trip each. Garbage is rejected in
+            # microseconds instead.
+            #
+            # The 60-second grace on `exp` is for OUR clock, not the token's:
+            # a VPS with drifting NTP must not start refusing valid
+            # credentials, and being 60 seconds generous about a bound GoTrue
+            # enforces itself costs nothing.
+            if not _is_structurally_live(token):
+                logger.warning("Malformed or expired token at %s.", request.endpoint)
+                return None, _handle_unauthorized(_is_page_request())
```

`_is_structurally_live` must swallow every parse error and answer `False`; it must never
raise into the auth path, and it must never be the _only_ thing between a request and an
identity.

### [HISTORICAL] 4.3 Layer 1 + 2 — the verification call, `web/api/app.py:548`

```diff
@@ web/api/app.py:546
-            response = supabase.auth.get_user(token)
-            # Robustly get the user object, which might be nested differently
-            user = getattr(response, "user", None) or getattr(
-                getattr(response, "data", None), "user", None
-            )
-
-            if not user:
-                logger.warning("Token validation failed for %s – no user found.", request.endpoint)
-                return None, _handle_unauthorized(_is_page_request())
-
-            # The user id is the stable identity; email can be changed by the
-            # account holder and is only a fallback for a provider that omits it.
-            user_id = str(getattr(user, "id", None) or user.email)
+            def _verify() -> VerifiedIdentity:
+                response = supabase.auth.get_user(token)
+                # Robustly get the user object, which might be nested differently
+                user = getattr(response, "user", None) or getattr(
+                    getattr(response, "data", None), "user", None
+                )
+                if not user:
+                    # Not a refusal and not an outage — a response in a shape
+                    # we do not understand. Raising a distinct type keeps it
+                    # out of BOTH classifiers, so it lands on the 500 branch
+                    # that already exists for our own faults rather than
+                    # telling the reader their credential is bad.
+                    raise _ProviderResponseUnusable(request.endpoint)
+                # The user id is the stable identity; email can be changed by
+                # the account holder and is only a fallback for a provider
+                # that omits it.
+                return VerifiedIdentity(
+                    user_id=str(getattr(user, "id", None) or user.email),
+                    email=getattr(user, "email", None),
+                    token_exp=_token_exp(token),
+                )
+
+            # Single-flight always; remembering only off the console. See the
+            # module docstring of token_verification_cache for why those are
+            # two decisions and not one.
+            is_console = request.blueprint == "admin"
+            verified = current_app.config["token_verification"].get_or_verify(
+                token, _verify, use_cache=not is_console
+            )
+            user_id = verified.user_id
```

and the flags call, which keeps its own independent `fresh` from the _same_ predicate:

```diff
             identity = resolve_identity_flags(
                 current_app.config["identity_flags"],
                 user_id,
-                user.email,
+                verified.email,
@@
-                fresh=(request.blueprint == "admin"),
+                # Same predicate as the token cache above, deliberately read
+                # from one variable rather than recomputed: two expressions
+                # that are meant to agree eventually will not.
+                fresh=is_console,
             )
```

Everything from `_bind_session_to_identity` onward
([`app.py:603-614`](../web/api/app.py)) is **unchanged and must stay reachable on a cache
hit** — a hit returns an identity, not permission to return early.

### [HISTORICAL] 4.4 Construction, `web/api/app.py:1625`

Beside the flags cache, mirroring how it is wired:

```diff
     app.config["identity_flags"] = IdentityFlagsCache()
+    # A SECOND, separate cache — see token_verification_cache's docstring for
+    # why merging it into the one above is not possible in the direction that
+    # matters. No refusal predicate: §4.1 removed negative caching entirely,
+    # so there is nothing here for one to gate.
+    app.config["token_verification"] = TokenVerificationCache(
+        ttl_seconds=config.get("server", "auth_token_cache", {}).get("ttl_seconds", 0),
+    )
```

`config.get(section, key, default)` is the real signature
([`web/utils/config_loader.py:76`](../web/utils/config_loader.py)).

### [HISTORICAL] 4.5 Configuration — `web/config.yaml`, under `server:` beside `rate_limit:`

`web/config.yaml`, **not** `.env` and **not** `app_settings`. `.env` is secrets only
([`config.yaml:4-6`](../web/config.yaml)); `app_settings` is a deliberately small runtime
override surface, and a security window that an operator can widen from a web console
without a deploy and without a review is the wrong shape for this particular dial.

```diff
@@ web/config.yaml, after the rate_limit block
+  # How long a successful GoTrue token verification may be reused, in seconds.
+  #
+  # THIS IS THE STATED REVOCATION WINDOW. Raising it lengthens the time a
+  # revoked reader session keeps working. It applies to reader routes only —
+  # /admin/* bypasses this cache entirely and is verified live on every
+  # request, because the console can disable accounts and end sessions. Every
+  # entry is additionally capped at the token's own `exp`, so this can shorten
+  # a credential's life and never extend it.
+  #
+  # 0 disables remembering entirely and restores per-request verification.
+  # Concurrent same-token requests are still collapsed into one round trip at
+  # any value, including 0 — that part is a concurrency control, not a cache,
+  # and it costs nothing in freshness.
+  #
+  # See docs/token-verification-plan.md §1 for the trade this represents.
+  auth_token_cache:
+    # 0 = OFF, and the shipped default. Single-flight still collapses concurrent
+    # same-token verification at any value; that part costs no freshness.
+    # Raising this above 0 takes the revocation trade in §1.4 and must not be
+    # done without the measurement and the TODO.md entry that section requires.
+    ttl_seconds: 0
```

### [HISTORICAL] 4.6 Invalidation call sites

**`admin.py:909`** — role/access change, beside the existing line:

```diff
     current_app.config["identity_flags"].invalidate(user_id)
+    # The flags cache above knows this reader was demoted; the token cache
+    # still holds "GoTrue said this credential is good", which is separately
+    # true and separately cached. A disable in particular must not wait out a
+    # TTL on a surface the operator is watching.
+    current_app.config["token_verification"].invalidate_user(user_id)
```

**`admin.py:565` `revoke_sessions`** — the sharpest one. Invalidate on success **and on an
ambiguous failure**, because the route's own docstring says a transport failure does not
prove the mutation failed:

```diff
     except AuthAdminRefused as refusal:
         outcome = "outcome_unknown" if refusal.ambiguous else "failed"
+        if refusal.ambiguous:
+            # GoTrue may already have committed the revocation. The route
+            # records that ambiguity in the audit log for exactly this reason;
+            # the cache must resolve it in the safe direction.
+            current_app.config["token_verification"].invalidate_user(user_id)
@@
         return jsonify({"error": refusal.code, "outcome_unknown": refusal.ambiguous}), status

+    current_app.config["token_verification"].invalidate_user(user_id)
     backend.append_audit(
```

**`admin.py:662` `change_email`** — same shape. The cached `email` feeds
`session["user_email"]`.

**`auth.py:424` `logout`** — read the token **before** `session.clear()`, since
`_get_token_from_request` falls back to the session:

```diff
 def logout():
+    # Read before the clear below: `_get_token_from_request` falls back to
+    # `session["supabase_access_token"]`, so clearing first would lose the
+    # only handle on the entry that needs dropping.
+    from web.api.app import _get_token_from_request
+
+    token = _get_token_from_request()
     purge_conversation_state()
     session.clear()
+    # Local and unconditional, deliberately before the GoTrue call below and
+    # outside its try: whether the provider is reachable has no bearing on
+    # whether this process should keep trusting this token.
+    if token:
+        current_app.config["token_verification"].invalidate_token(token)
```

**Not reachable from Flask — the real gap, enumerated.** Every credential-changing and
session-ending action a _reader_ can take is browser-direct through the Supabase JS client,
so the server never observes it and cannot evict anything:

| Action                                                              | Where                                                                                                                                                                                                          | Evictable?                                            |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| Change password                                                     | `supabase.auth.updateUser({ password })` ([`static/js/modules/services.js:442`](../static/js/modules/services.js), [`static/js/account/handlers.js:189`](../static/js/account/handlers.js))                    | **No**                                                |
| Sign out everywhere                                                 | `signOut({ scope: 'global' })` ([`services.js:496`](../static/js/modules/services.js))                                                                                                                         | **No**                                                |
| Sign out other sessions                                             | `signOut({ scope: 'others' })` ([`services.js:517`](../static/js/modules/services.js); called at [`account/handlers.js:219`](../static/js/account/handlers.js) and [`:255`](../static/js/account/handlers.js)) | **No**                                                |
| Complete a password recovery                                        | same browser-direct `updateUser` path                                                                                                                                                                          | **No**                                                |
| Admin "send password reset" ([`admin.py:442`](../web/api/admin.py)) | sends mail only; the credential changes later, browser-direct                                                                                                                                                  | **No** — and correctly evicts nothing at request time |

This is worse than "three residual gaps". `invalidate_token` can only reach the token in
_this_ Flask session; a reader signing out their other devices cannot cause eviction of
those devices' cached tokens, because the server was never told and does not hold them.

**It is also the strongest argument for shipping with `ttl_seconds: 0`.** The single most
security-relevant reader action in the product — "my account is compromised, change the
password and kill the other sessions" — is exactly the one this cache cannot honour. A
server-mediated endpoint for those actions would close it, and is out of scope here; until
one exists, the honest posture is not to cache.

---

## [HISTORICAL] 5. Concurrency and error handling

### [HISTORICAL] The two races, and why both need guarding

1. **Two threads miss on the same token.** Solved by single-flight: the first becomes the
   owner, the rest wait on an `Event`. Owner failure propagates to waiters — they do **not**
   retry, or N threads with one bad token become N sequential GoTrue calls on the path an
   attacker controls.
2. **A verification is in flight when the user is invalidated.** Solved by stamping
   `_user_invalidated_at[user_id]` / `_token_invalidated_at[key]` and comparing at publish
   time against when the flight _started_. This is the same hazard
   `IdentityFlagsCache.begin_fetch`/`put` exists to close
   ([`identity_cache.py:118-124`](../web/services/identity_cache.py)), and it is the single
   easiest thing to get wrong here: dropping stored entries alone does nothing to a call
   already on the wire, which then publishes the revoked session back with a fresh TTL.

**No lock is held across the network call**, and none across `Event.wait()`. The auth
timeout is 5 seconds ([`supabase_client.py:19`](../web/utils/supabase_client.py)) and there
are 8 threads; a cache lock held for that long stalls every thread regardless of which token
it carries — reproducing the outage this work exists to prevent.

`threading.Lock`, not `RLock`: no path re-enters, and an `RLock` would hide it if one ever
did.

### [HISTORICAL] Bounds

### [HISTORICAL] The single-worker coupling gets worse, and the warning must say so

Both caches are process-local and correct only under one worker. The existing check names
only `ConversationStore` ([`app.py:1941-1949`](../web/api/app.py)) — it already fails to
mention `IdentityFlagsCache`, and adding a second cache widens a gap rather than creating
one. Under two workers the failure is **not** degraded efficiency: an admin revocation
evicts on worker A and leaves worker B serving the revoked token for its full TTL, and
single-flight collapses only within each process.

Update that warning in this commit to name all three process-local structures and to say
that invalidation, not just context, is what breaks. With the positive cache defaulting to
0 this is latent rather than live — which is the right time to fix it.

| Structure                                       | Bound                                                                                                             | Why                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_data`                                         | 2000 LRU                                                                                                          | Matches `IdentityFlagsCache`'s existing bound. ~200 bytes/entry.                                                                                                                                                                                                                                                                                                                                                                                                    |
| `_flights`                                      | 64                                                                                                                | Past it, verify without single-flight rather than refuse.                                                                                                                                                                                                                                                                                                                                                                                                           |
| `_by_user`                                      | evicted with its entries                                                                                          | A reverse index that outlives its cache is a leak.                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `_user_invalidated_at`, `_token_invalidated_at` | **age-based only** — a stamp is dropped when it is older than the waiter ceiling, never because of cache pressure | **Not evictable with entries.** `_flights` is keyed by digest and does not know its user id until the verification returns, so LRU eviction cannot tell whether an older flight still needs a user stamp. Dropping one under pressure reopens the exact race the stamp closes: flight starts → `invalidate_user` stamps → pressure drops the stamp → flight publishes the revoked identity. Age is the safe bound because no flight can outlive the waiter ceiling. |

### [HISTORICAL] What may and may not be cached

| Outcome                                                            | Cached?                                                                                           |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| Verified user with a usable id                                     | **Yes**, `min(ttl, exp - now)`; not at all if `exp` has passed                                    |
| `_is_auth_refusal(e) is True` (a genuine 401)                      | **Never.** Nothing is remembered; the next request re-verifies.                                   |
| `httpx.TransportError`, `AuthRetryableError`, 5xx, 429             | **Never.** Still 503, session intact.                                                             |
| `AuthUnknownError`, refusal without a status, missing auth library | **Never.** Still 500, session intact.                                                             |
| Provider response with no user                                     | **Never.** 500.                                                                                   |
| `AuthError` with status 429 or 5xx                                 | **Never** — and note it satisfies `_is_auth_refusal`, so any future gate must test outage first.  |
| `TokenVerificationTimeout` (waiter gave up)                        | **Never.** Classified as an outage → 503, session intact. Must be added to `_is_upstream_outage`. |
| Any other exception                                                | **Never.**                                                                                        |

A cache hit can never _create_ a classification. It replays a previous outcome; when it
expires, the live path and its existing classifiers run again unchanged.

---

## [HISTORICAL] 6. Test verification matrix

Harness: `create_app(testing=True)` then `app.config["TESTING"] = False`, with
`monkeypatch.setattr("web.api.app.get_supabase", ...)` — the pattern
`test_auth_failure_modes.py:38-70` already establishes. **Never monkeypatch
`_authenticate_request`**; that file's own docstring records that doing so is how the
original timeout bug survived its test.

Every row must be seen to fail against current `main` before it is believed.

### [HISTORICAL] Unit — `web/tests/test_token_verification_cache.py` (new)

| Test                                                      | Asserts                                                                                 | Fails today because                  |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------ |
| `test_a_second_request_with_one_token_does_not_ask_again` | One counting verifier, two calls, one invocation                                        | No cache exists                      |
| `test_the_cache_key_is_a_digest_not_the_token`            | The raw token appears nowhere in `_data`/`_by_user`/`repr`                              | No cache exists                      |
| `test_an_entry_expires_at_the_ttl`                        | Injected monotonic clock; re-verifies after TTL                                         | No cache exists                      |
| `test_an_entry_never_outlives_the_token_exp`              | TTL 60, `exp` 2s away → expires at 2s                                                   | No `exp` ceiling                     |
| `test_an_already_expired_token_is_not_cached_at_all`      | `exp` in the past → no entry written                                                    | No cache exists                      |
| `test_eight_threads_on_one_token_make_one_call`           | Real threads + `Barrier`; verifier called once, all 8 get the identity                  | 8 calls today                        |
| `test_a_waiter_inherits_the_owners_failure`               | Owner raises; waiters see that exception; verifier called **once**                      | 8 calls today                        |
| `test_invalidation_during_a_flight_does_not_publish`      | Barrier holds the verifier; `invalidate_user` runs; on release no entry exists          | The race this closes                 |
| `test_invalidate_user_drops_every_token_for_that_user`    | Two digests, one user, both gone                                                        | No cache exists                      |
| `test_an_outage_is_never_remembered`                      | Transport error twice → verifier called twice                                           | Guards a future regression           |
| `test_a_refusal_is_never_remembered`                      | Refusal twice → verifier called **twice**                                               | Pins the removal of negative caching |
| `test_a_429_is_not_treated_as_a_refusal_by_the_cache`     | `AuthApiError(status=429)` leaves no entry of any kind                                  | The predicate trap in §5             |
| `test_the_cache_is_bounded`                               | 3000 tokens → ≤2000 entries, and `_by_user`/stamps shrink with them                     | No cache exists                      |
| `test_a_waiter_gives_up_bounded_and_does_not_call_gotrue` | Leader held past the ceiling; waiters raise the timeout, verifier still called **once** | No bound today                       |
| `test_a_waiter_timeout_is_a_503_not_a_401`                | Timeout classifies as outage; session intact                                            | The 503-never-401 invariant          |
| `test_use_cache_false_still_single_flights`               | 7 threads, `use_cache=False` → one call, nothing stored                                 | The admin property                   |

### [HISTORICAL] Integration — existing files

| Test                                                   | File                         | Asserts                                                                |
| ------------------------------------------------------ | ---------------------------- | ---------------------------------------------------------------------- |
| `test_a_reader_repeating_a_request_verifies_once`      | `test_auth_failure_modes.py` | Counting fake; two reader API calls, one `get_user`                    |
| `test_the_console_verifies_on_every_request`           | `test_auth_failure_modes.py` | Two sequential admin calls → two `get_user`                            |
| `test_a_console_burst_still_collapses`                 | `test_auth_failure_modes.py` | 7 concurrent admin requests → one `get_user`, nothing cached           |
| `test_a_timeout_is_still_a_503_after_a_cache_hit`      | `test_auth_failure_modes.py` | Hit, expire, then transport error → 503, session intact                |
| `test_a_refusal_after_a_hit_still_clears_the_session`  | `test_auth_failure_modes.py` | Hit, expire, refuse → 401, markers gone                                |
| `test_a_malformed_token_never_reaches_the_provider`    | `test_auth_failure_modes.py` | Layer 0: `get_user` not called, 401 returned                           |
| `test_a_clock_60s_ahead_does_not_reject_a_valid_token` | `test_auth_failure_modes.py` | Layer 0 leeway                                                         |
| `test_the_session_is_rebound_on_a_cache_hit`           | `test_identity_roles.py`     | `auth_identity`, `user_email`, `is_admin_hint` written on the hit path |
| `test_a_disabled_reader_is_still_403_on_a_cache_hit`   | `test_identity_roles.py`     | Existing 403 behaviour survives                                        |
| `test_a_role_change_invalidates_both_caches`           | `test_admin_users.py`        | Extends the existing test at line 320                                  |
| `test_revoking_sessions_drops_the_token_cache`         | `test_admin_users.py`        | Success **and** ambiguous-failure paths                                |
| `test_an_email_change_drops_the_token_cache`           | `test_admin_users.py`        | Stale `user_email`                                                     |
| `test_logout_drops_the_token_even_when_gotrue_fails`   | `test_auth_routes.py`        | Invalidation precedes and survives the provider call                   |
| `test_testing_mode_never_builds_a_client`              | `test_auth_failure_modes.py` | TESTING short-circuit intact                                           |

Concurrency tests use `threading.Barrier` and `Event`, never `sleep`.

---

## [HISTORICAL] 7. Documentation, rollout, and what to watch

### [HISTORICAL] Documents to update **in the same commit**

- **[`docs/ARCHITECTURE.md`](ARCHITECTURE.md) §"Authentication and the blueprint gate"
  (line 247)** — today it says only that identity is cached 30 seconds. Add: token
  verification is single-flighted on every route; results are remembered 30 seconds on reader
  routes and never on `/admin/*`; entries never outlive `exp`; outage/refusal classification
  is unchanged.
- **[`docs/ARCHITECTURE.md`](ARCHITECTURE.md) §"Rules that collide" (line 335)** — add row
  **9**. Row 7 already records the flags-cache-vs-account-page collision; the new one is:
  _"Two caches now sit on the auth path, keyed differently, with opposite outage postures —
  flags fails open, token verification fails closed."_ The table's own instruction is
  "append when you find a ninth."
- **[`docs/OPERATIONS.md`](OPERATIONS.md)** — new section after the registrations-pause one:
  what `auth_token_cache.ttl_seconds` means, that it is the stated revocation window, that
  `/admin/*` is exempt, that `0` restores per-request verification without losing the burst
  collapse, and that changing it needs a restart (single worker, in-process cache).
- **[`CLAUDE.md`](../CLAUDE.md) §"Architecture orientation"** — the "Identity is two layers"
  paragraph becomes three. No numbered rule in "The rules you will actually trip over"
  changes.
- **[`TODO.md`](../TODO.md)** — close the entry per the file's own procedure: move it to
  `docs/archive/TODO-resolved.md`, do not strike it in place. The replacement text must
  carry the revocation window verbatim from §1, the corrected fan-out count (6-7, not 4),
  and the three named gaps that remain outside the invalidation boundary.
- **Bump `ASSET_VERSION`** only if `static/js/` is touched. This plan touches no frontend
  file; if that changes, bump it.

### [HISTORICAL] Deterministic rollout order

Schema before code is not in play — there is no migration. The ordering that matters here is
that **nothing observable changes until the last step**.

1. **Ship the module and its unit tests alone.** Nothing imports it. Gates green.
2. **Wire construction and the call site with `ttl_seconds: 0` and
   the positive cache off by default.** Single-flight is live; nothing is remembered. This is the
   step that fixes worker starvation, and it carries **no revocation trade at all** — so it
   can be judged on its own before anything is given up.
3. **Ship Layer 0** (structural pre-validation). Still no trade.
4. **Ship the invalidation call sites** — `patch_user`, `revoke_sessions`, `change_email`,
   `logout` — while the TTL is still 0. They are no-ops against an empty cache, which is
   exactly when you want to find out they are wired wrong.
5. **Only now set `ttl_seconds: 30`.** This is the commit that takes the trade, and it is a
   one-line config change with the whole mechanism already proven in production.

Steps 2 and 5 being separate is the point. Do not collapse them.

### [HISTORICAL] Rollback

Set `ttl_seconds: 0` and restart the worker. Per-request
verification is restored; single-flight and Layer 0 remain, which are the parts with no
security cost. A full revert is a code revert of steps 1-4 and is not expected to be needed
independently.

### [HISTORICAL] Production-shaped verification drill

Metrics tell you the cache is working; only a drill tells you it is _correct_. Run this on
a `--workers 1 --threads 8` instance after step 5, and record the result in the commit that
closes the `TODO.md` entry.

| #   | Do this                                                                          | Expect                                                                                                                                                                                                                                                                                  |
| --- | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Open `/admin` with a network trace on the GoTrue side                            | **~3** verifications, not 6-7. Not 1: [`static/js/admin.js:69-80`](../static/js/admin.js) `await`s `services.identity()` **before** starting the tab initialisers, so that call cannot single-flight with them. Expect identity, then the collapsed tab wave, then notification history |
| 2   | Open `/admin`, wait for the TTL, click into an account                           | **2 more** verifications, not 0 — the admin bypass is intact. **If this shows 0, stop and roll back**: the console is silently taking a trade it was exempted from                                                                                                                      |
| 3   | As a reader, send two chat turns inside the TTL                                  | **2** verifications while `ttl_seconds: 0` (the shipped default); **1** only after the cache is deliberately enabled per §1.4                                                                                                                                                           |
| 4   | Admin → revoke sessions on that reader                                           | Reader's next request is refused **immediately**, not after the TTL — eviction fired                                                                                                                                                                                                    |
| 5   | Reader signs out, then replays the old token                                     | Refused immediately — logout eviction fired                                                                                                                                                                                                                                             |
| 6   | Admin → disable that reader                                                      | Console reflects it **immediately** (`fresh=True`); chat refuses within the flags TTL. Unchanged from today either way                                                                                                                                                                  |
| 7   | Revoke a session in the Supabase **dashboard** (not the console)                 | With the default 0: refused **immediately**. Only after enabling the cache does this become "up to the TTL" — and that is the drill that proves the stated window                                                                                                                       |
| 8   | Point the app at an unreachable GoTrue, cold cache, 8 concurrent reader requests | **1** attempted call, all 8 get **503**, sessions intact, no thread parked past the waiter ceiling                                                                                                                                                                                      |

Step 2 is the one to stop on. If it shows 0 verifications, the console is silently taking a
trade it was exempted from — roll back. Step 7 is what proves the stated window is real,
and is only meaningful once the cache is enabled.

### [HISTORICAL] What to watch after each deploy

- **`get_user` call volume** — should fall sharply at step 2 (burst collapse) and again at
  step 5. If it does not fall at step 2, single-flight is not engaging.
- **401 / 403 / 503 rates** — 503 should be unchanged; a _rise_ in 401 means Layer 0 is
  rejecting valid tokens, which points at clock skew. Check NTP before touching the leeway.
- **Admin `get_user` volume** — must stay proportional to console requests. If it drops
  after step 5, the admin bypass is broken and the console is silently taking a trade it
  was explicitly exempted from. **This is the single most important signal in the list.**
- **`len(cache)`** — should plateau well under 2000. Growth toward the bound means unique
  tokens are arriving, which is either a token-refresh storm or a probe.

---

## [HISTORICAL] 8. What would have to be true for local verification (Option B)

Recorded rather than discarded, because the reasoning cost a session to establish and the
answer changes the moment the first condition flips.

1. **Asymmetric signing keys enabled on the project.** JWKS is `{"keys":[]}` today. Until an
   ES256/RS256 key is in use, `get_claims()` falls through to a network `get_user()` and
   Option B is a no-op with extra code.
2. **A revocation story for `revoke-sessions`.** Supabase's own documented answer is to
   check the `session_id` claim against `auth.sessions`. This app is unusually well placed
   for that: it already pays a Postgres round trip for flags
   ([`admin_store.py:243`](../web/services/admin_store.py)), already caches it 30 seconds
   with correct invalidation, and already has a `fresh=True` bypass for the console. Folding
   a `session_id` liveness check into that lookup would give local verification **and**
   honest revocation for one round trip instead of two — strictly better than today. It
   needs a new `security definer` RPC and therefore a migration.
3. **Claim validation the SDK does not do.** `get_claims` validates `exp` only — no `iss`,
   no `aud`, no `nbf`, no leeway. A wrapper must add them.
4. **A `kid`-flood defence.** `_fetch_jwks` re-fetches the JWKS endpoint on any uncached
   `kid`, unlocked, with no negative cache — one outbound fetch per attacker-chosen `kid`.
   Worse than today. Needs a negative `kid` cache and a refetch rate limit.
5. **`pydantic.ValidationError` classified.** `JWTHeader.alg` is a `Literal`, so `alg: none`
   raises `ValidationError`, which neither `_is_upstream_outage` nor `_is_auth_refusal`
   recognises — a malformed credential would 500 instead of 401.
6. **PyJWT named in `requirements.txt`.** Already present transitively (2.13.0, with
   cryptography 48.0.0); the repo's own stated rule is that a transitive dependency the code
   imports by name is a direct dependency — see the `httpx` note in that file.

---

## [HISTORICAL] Provenance

Two independent agents were briefed on this problem and reported separately: a security
edge-case analysis and a read-only codebase audit with its own implementation plan. They
converged on Option A, single-flight, and a total admin bypass. They disagreed on the TTL
(5s vs 15s) and on negative caching (never vs 5s); this plan takes 5s and takes negative
caching, for the reasons given in §1 and §5.

Three things in this plan came from neither report and are the author's, verified directly:
the empty JWKS and what it does to `get_claims`; the corrected 6-7 console fan-out; and the
separation of single-flight from caching, which is what makes the admin bypass affordable —
both reports recommended the bypass while also crediting the cache with collapsing the
console burst, which the bypass prevents it from doing.

### [HISTORICAL] What came from where

The GLM plan contributed the single most valuable fact in this document and it changed a
decision: that **`get_user` is stateful**, and that PostgREST is not. That reframed the
trade from "how much revocation latency can we tolerate" to "what exactly is the one thing
that goes stale, and what is this app's real posture elsewhere" — and moved the TTL from 5
seconds to 30. It also caught a genuine defect: an unbounded `Event.wait()` in the waiter
path, which makes every waiter's liveness depend on the leader reaching its `set()`. Both
are adopted above.

Where this plan still departs from it:

- **The admin blueprint is exempt from caching here; GLM caches on every route.** GLM's
  argument is that the cache never answers for role or disabled state, so admin
  _authorization_ stays real-time — which is true, and §1's blast-radius table agrees. But
  it leaves a revoked operator session usable on the console for up to the TTL, and the
  console is where sessions get revoked during an incident. The exemption is close to free
  precisely because single-flight is separate: GLM's own 4→1 collapse comes from
  single-flight, not from caching, so exempting the console loses cross-request reuse on a
  surface whose requests are sparse after boot.
- **Layers 0 and 3.** GLM has no structural pre-validation, so a flood of _distinct_ invalid
  tokens still costs one round trip each — the one attack a token cache cannot help with.
  It also declines negative caching, which leaves the console's own retry-once-on-401
  behaviour ([`static/js/admin/services.js`](../static/js/admin/services.js)) doubling every
  doomed verification.
- **Configuration lives in `web/config.yaml`, not an env var.** GLM proposes
  `SUPABASE_TOKEN_CACHE_TTL`, and there is real precedent next door —
  `_auth_timeout` reads `SUPABASE_AUTH_TIMEOUT`
  ([`supabase_client.py:19`](../web/utils/supabase_client.py)). The rule in `CLAUDE.md` is
  that `.env` is secrets and `config.yaml` is behaviour, and this is behaviour. The stronger
  reason is reviewability: a stated security window should move in a diff somebody approves,
  not in an environment variable that leaves no trace of who widened it or when.
- **Expired entries are dropped, not retained.** GLM keeps them "for diagnostics", copying
  `IdentityFlagsCache`. That class retains them because `last_known()` genuinely needs a
  stale answer to keep a disabled account out during an outage. There is no equivalent here
  — a stale "this token was good" is exactly the thing that must not survive — so retention
  would be a liability with no compensating use.

Two corrections to GLM's own draft, offered rather than adopted: it repeats `TODO.md`'s
"four" console verifications (§2 shows 6-7), and its `_authenticate_request` diff keeps an
`if not user:` branch after the variable it tests has been removed.

### [HISTORICAL] The adversarial pass, and what it overturned

The synthesis above was then sent back to a fresh read-only agent with instructions to
attack it rather than summarise it. It found two blockers and one false claim in this
document, all verified against source before being accepted:

- **`_is_auth_refusal` is not a safe gate for a negative cache.** It returns True for any
  `AuthError` carrying an integer status, and `AuthApiError` is built with
  `status_code or 500` — so a 429 or a 500 satisfies it. The app is only correct because
  `_authenticate_request` tests for outage first. A negative cache calling the refusal
  predicate alone would have remembered outages as credential verdicts. **Negative caching
  was removed entirely**; the reasoning is preserved in the module sketch so it is not
  re-proposed.
- **The constructor sketch could not be built as written** — `refusal_predicate` was passed
  at construction and never accepted. Fixed, and moot now that the predicate is gone.
- **"0 seconds for role and disabled state" was false.** Reader routes resolve flags with
  `fresh=False` against a 30-second TTL; only the admin blueprint is fresh. The claim is
  corrected to "no _additional_ staleness", which is the true and much weaker statement.
- **The 30-second TTL was rationalised, not derived.** PostgREST's ~3600s window applies to
  `profiles`; chat, history and export are Flask-mediated. Existing exposure elsewhere is
  not a licence to widen this one. **The positive cache now ships off** (`ttl_seconds: 0`)
  and enabling it requires the measurement in §1.4.
- **Invalidation stamps cannot be LRU-evicted** alongside their entries, because `_flights`
  does not know its user id until the verification returns. Now age-bounded by the waiter
  ceiling.
- **The drill's expected counts were wrong.** `admin.js` awaits `identity()` before the tab
  initialisers, so the boot cannot collapse to 1. Corrected to ~3.

Two of its findings are recorded but not adopted as changes here: that lazy-loading the
console's tabs would remove most of the boot fan-out with no auth change at all (true, and
the better first move if the console is the only motivation — noted in §7 as a companion),
and that four layers are disproportionate for the measured problem (largely answered by
shipping the positive cache off).

Two defects in the audit's proposed implementation are corrected above: `invalidate_user`
that drops entries without stamping in-flight verifications (§5, race 2), and waiters that
retry on owner failure instead of inheriting it (§5, race 1).
