"""Did GoTrue accept this bearer token? — asked once per burst, remembered briefly.

Deliberately NOT ``IdentityFlagsCache``, and the distinction is the whole
reason this module exists rather than a widened parameter over there. That
cache answers "what standing does this already-verified reader have", keyed by
``user_id``, backed by Postgres, and it fails **open** on an outage because a
retrieval blip must not take down a product whose job is answering one
question. This cache answers "is this credential good", keyed by a digest of
the credential, backed by GoTrue, and it fails **closed**, because the safe
reading of "we could not check a credential" is not "admit them".

Merging the two is not merely untidy, it is unimplementable in the direction
that matters: when a request arrives the server holds a token and does not yet
know the ``user_id``, so a ``user_id``-keyed cache cannot be consulted without
first making the call it exists to avoid.

Two mechanisms live here and they are priced separately, because conflating
them is how a small latency fix becomes an unexamined security change:

* **Single-flight** costs nothing in freshness. Concurrent requests bearing the
  same token wait on one in-flight verification instead of making N. Every
  burst still reaches the authority; nothing is remembered. This is what
  actually answers the worker-starvation problem, and it is why the admin
  blueprint uses this class at all despite taking none of the caching.
* **The positive cache** is the deliberate trade, bounded by a short TTL and by
  the token's own ``exp``, and applied to reader routes only. It ships with
  ``ttl_seconds=0`` — see docs/archive/2026-08-27_token-verification-cache.md §1.4 for why raising
  it is a separate, measured decision and not part of this change.

There is deliberately no negative (refusal) cache. An earlier draft had one,
gated on the app's own refusal classifier. It was removed after an
adversarial review found two independent defects, recorded in
``get_or_verify``'s docstring so the idea is not proposed again without first
reading why it failed.

PROCESS-LOCAL, exactly like ``ConversationStore`` and ``IdentityFlagsCache``,
and correct for the same stated deployment reason: this app runs
``--workers 1 --threads 8``.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from web.utils.hashing import sha256_hex


class TokenVerificationTimeout(Exception):
    """A waiter gave up rather than wait forever for the owner's answer.

    Classified as an outage, never a refusal: the credential in the reader's
    hands has not been judged bad, the process serving it has just failed to
    get an answer in time. See ``web.api.app._is_upstream_outage``.
    """

    def __init__(self, waited_seconds: float) -> None:
        super().__init__(
            f"Timed out after {waited_seconds}s waiting for another thread's token verification."
        )
        self.waited_seconds = waited_seconds


@dataclass(frozen=True)
class VerifiedIdentity:
    """What GoTrue confirmed, reduced to what the request path actually reads.

    Frozen, and deliberately not the provider's ``User`` object: caching a
    library type means a library upgrade can change what is cached without any
    line in this repository changing. ``token_exp`` is carried so the cache can
    refuse to outlive the credential it describes.
    """

    user_id: str
    email: str | None
    token_exp: float | None


class _Flight:
    """One in-flight verification, and the result or failure it produced."""

    __slots__ = ("done", "error", "identity", "started")

    def __init__(self, started: float) -> None:
        self.done = threading.Event()
        self.identity: VerifiedIdentity | None = None
        self.error: BaseException | None = None
        self.started = started


class TokenVerificationCache:
    """Single-flight always; a short positive memory only when asked for.

    Every public method takes and releases the lock quickly. No lock is ever
    held across a call to ``verify`` or across ``Event.wait()`` — see
    ``get_or_verify`` for why that matters under ``--workers 1 --threads 8``.
    """

    def __init__(
        self,
        # 0 = single-flight only, nothing remembered. THE DEFAULT. See
        # docs/archive/2026-08-27_token-verification-cache.md §1.4.
        ttl_seconds: float = 0.0,
        max_entries: int = 2000,
        max_in_flight: int = 64,
        # Fallback only. `web/api/app.py`'s construction derives the real
        # value from `supabase_client._auth_timeout()` plus a small grace, so
        # a change to `SUPABASE_AUTH_TIMEOUT` cannot silently drift away from
        # this ceiling. 5.5 (matching that timeout's own default of 5s) is
        # what a caller gets who constructs this class without threading that
        # through — every test in this repo does exactly that.
        wait_timeout_seconds: float = 5.5,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._max_in_flight = max_in_flight
        self._wait_timeout = wait_timeout_seconds
        self._lock = threading.Lock()
        # (expiry, started, identity) — `started` is kept alongside the
        # expiry so `_publish` can reject an out-of-order overwrite from a
        # slower, earlier-started verification finishing after a newer one
        # already published (see `_publish`'s docstring).
        self._data: OrderedDict[str, tuple[float, float, VerifiedIdentity]] = OrderedDict()
        self._flights: dict[str, _Flight] = {}
        # Reverse index so `invalidate_user` is a lookup rather than a scan of
        # every live token. Holds digests only — no plaintext token is ever
        # stored by this class, in either direction.
        self._by_user: dict[str, set[str]] = {}
        # When a token or a user was last invalidated. `invalidate_user`/
        # `invalidate_token` alone cannot stop a verification that is already
        # in flight, and that verification would otherwise publish after the
        # revocation and restore the very session that was just ended — with
        # a fresh TTL on top. Publication is therefore ordered by when a
        # flight STARTED, exactly as `IdentityFlagsCache.begin_fetch`/`put`
        # orders the flags lookup.
        #
        # ONE dict for both keyspaces, not two — token digests
        # (`_token_ns`) and user ids (`_user_ns`) are namespaced by a
        # one-character prefix so a token digest can never collide with a
        # user id, but every place that reasons about "was this stamped"
        # (`_prune_invalidation_stamps`, `invalidate_all`) has one map to
        # touch instead of two kept identically in step by hand.
        self._invalidated_at: dict[str, float] = {}
        # A global watermark for `invalidate_all`. Per-key/per-user stamps
        # cannot do that job: a verification already in flight when
        # `invalidate_all` runs has no entry in `_data`/`_by_user` yet to
        # stamp, and its user id is not known until it returns. One scalar,
        # checked alongside `_invalidated_at` above, rejects any flight that
        # started before the wipe regardless of which key or user it turns
        # out to belong to.
        self._invalidated_all_at: float | None = None

    # Injected as a staticmethod, matching IdentityFlagsCache, so tests can
    # monkeypatch time without patching a module global.
    @staticmethod
    def _now() -> float:
        return time.monotonic()

    @staticmethod
    def _key(token: str) -> str:
        """SHA-256, via the same `sha256_hex` the rest of this app uses
        for bearer material — one definition of "how a bearer
        token becomes a digest," not three independently written ones.

        A raw bearer token as a dict key is a bearer token in a heap dump, in a
        `repr()`, and in whatever a future debug endpoint decides to enumerate.
        The digest is just as unique and carries no credential.
        """
        return sha256_hex(token)

    @staticmethod
    def _token_ns(key: str) -> str:
        """`_invalidated_at`'s namespace for a token digest."""
        return f"tok:{key}"

    @staticmethod
    def _user_ns(user_id: str) -> str:
        """`_invalidated_at`'s namespace for a user id — distinguished from
        `_token_ns` above so a token digest (always 64 hex characters, but
        that is an accident of SHA-256, not a contract this should lean on)
        can never collide with a user id sharing the same raw string."""
        return f"usr:{user_id}"

    def _live_entry(self, key: str) -> VerifiedIdentity | None:
        """Caller holds the lock. Fresh entry, or None if absent/expired.

        An expired hit is removed here, not left for `_evict` to find later —
        `_evict` only enforces the LRU bound and never inspects the TTL, so
        without this an expired entry (and its `_by_user` membership) would
        sit in memory, unreachable but unfreed, until LRU pressure happened
        to reach it. That contradicts this class's own stated model: unlike
        `IdentityFlagsCache`, a stale "this token was good" has no
        compensating use, so nothing should retain one past its TTL.
        """
        entry = self._data.get(key)
        if entry is None:
            return None
        if self._now() > entry[0]:
            self._forget(key, entry[2])
            return None
        self._data.move_to_end(key)
        return entry[2]

    def _forget(self, key: str, identity: VerifiedIdentity) -> None:
        """Caller holds the lock. Remove one entry from `_data` and its
        `_by_user` membership together — the two must never drift apart."""
        self._data.pop(key, None)
        users = self._by_user.get(identity.user_id)
        if users is not None:
            users.discard(key)
            if not users:
                self._by_user.pop(identity.user_id, None)

    def _evict(self) -> None:
        """Enforce the size bound only. Caller must hold the lock.

        Unlike `IdentityFlagsCache`, an expired entry here is dropped
        immediately rather than retained — see the module docstring for why a
        stale "this token was good" has no compensating use the way a stale
        role does.
        """
        while len(self._data) > self._max:
            oldest_key, (_, _, oldest_identity) = self._data.popitem(last=False)
            users = self._by_user.get(oldest_identity.user_id)
            if users is not None:
                users.discard(oldest_key)
                if not users:
                    self._by_user.pop(oldest_identity.user_id, None)

    # `_evict` above pops directly rather than calling `_forget`: it already
    # has the popped `(key, identity)` pair from `popitem`, so a second
    # `_data.pop` would be a wasted lookup. `_forget` is for the two sites
    # below, which start from a key alone.

    def _prune_invalidation_stamps(self, now: float) -> None:
        """Caller holds the lock. Bound `_invalidated_at`.

        Unlike `_data`, it has no LRU cap — it exists only so a flight that
        started before an invalidation cannot publish after it (see
        `_publish`), and that guard is only needed while such a flight could
        still be running. `_wait_timeout` is derived from the auth client's
        own network timeout specifically so no flight is expected to run
        longer than it — but "expected" is a configured bound on a network
        call, not a proof, so the cutoff below is a wide multiple of it
        rather than the bound itself: cheap insurance against a slow GoTrue
        response outliving the ceiling in some edge case, at the cost of a
        few extra seconds of otherwise-harmless map growth.

        This is not a hygiene nicety. `invalidate_token` is reachable from
        `POST /auth/logout`, which is deliberately unauthenticated (a reader
        must be able to log out with an expired or garbage token) and stamps
        whatever token it is handed, valid or not. Without this bound, an
        anonymous caller sending distinct garbage bearer tokens to `/logout`
        forever would grow this map without limit — the exact
        memory-exhaustion primitive `_max_in_flight` exists to prevent one
        layer up.
        """
        cutoff = now - (self._wait_timeout * 4)
        for stale_key in [k for k, stamped in self._invalidated_at.items() if stamped < cutoff]:
            del self._invalidated_at[stale_key]

    def get_or_verify(
        self,
        token: str,
        verify: Callable[[], VerifiedIdentity],
        *,
        use_cache: bool = True,
    ) -> VerifiedIdentity:
        """One verification per token per burst; a short memory when allowed.

        ``use_cache=False`` (the admin blueprint) still single-flights — the
        console's own boot fires several concurrent requests on one token —
        but neither reads nor writes a remembered answer. Every console
        request therefore rests on a live answer from the authority, which is
        the property `fresh=True` protects one layer down.

        Raises whatever ``verify`` raised. This class never decides whether a
        failure was an outage or a refusal; `_is_upstream_outage` and
        `_is_auth_refusal` in app.py own that, and duplicating the judgement
        here would give the app two places to disagree with itself about
        whether to sign somebody out.

        NO negative (refusal) caching, on purpose. An earlier draft cached a
        refusal briefly, gated on the app's own `_is_auth_refusal`. Two
        independent defects killed it:

          1. `_is_auth_refusal` returns True for ANY `AuthError` carrying an
             integer status — and `AuthApiError` is constructed with
             `status_code or 500`. A 429 or a 500 from GoTrue is a refusal by
             that predicate, so caching it would have remembered an OUTAGE as
             a credential verdict. The app gets this right only because it
             tests for outage FIRST; a cache calling the refusal predicate
             alone inherits none of that ordering.
          2. "A rejected JWT never becomes valid again" is false. GoTrue
             returns 403 `user_banned`, and a ban can be lifted while the same
             unexpired token is still in the reader's hands.

        Its only real benefit was absorbing a client's retry-once-on-401 — and
        the one client that does that (the admin console) is exempt from this
        cache entirely, so that benefit never existed.
        """
        key = self._key(token)

        with self._lock:
            if use_cache and (hit := self._live_entry(key)) is not None:
                return hit

            flight = self._flights.get(key)
            if flight is None:
                # A bounded map. Unique invalid tokens are attacker-supplied,
                # so an unbounded one is a memory-growth primitive. Past the
                # bound, verify without single-flight rather than refuse: the
                # request is still answered correctly, just without the
                # collapse.
                #
                # `registered` tracks whether THIS flight is the one sitting
                # in `self._flights[key]`. An overflow flight never is. That
                # distinction matters below: without it, an overflow owner's
                # cleanup could `pop` a *different*, legitimately registered
                # flight for the same key that appeared after capacity freed
                # up — silently discarding it out from under whatever request
                # registered it, and reopening the very race this map exists
                # to close.
                if len(self._flights) >= self._max_in_flight:
                    owner, flight, registered = True, _Flight(self._now()), False
                else:
                    flight = _Flight(self._now())
                    self._flights[key] = flight
                    owner, registered = True, True
            else:
                owner, registered = False, True

        if not owner:
            # No lock held across the wait, and no lock held across the
            # network call below. A five-second auth timeout under a cache
            # lock would stall all eight threads on a cache that has nothing
            # to do with their tokens — turning a latency fix into the outage
            # it was written to prevent.
            #
            # BOUNDED, and the bound is not decoration. An unbounded wait
            # makes every waiter's liveness depend on the leader reaching its
            # `done.set()` — so any path that does not (a MemoryError between
            # the call and the publish, a thread killed mid-flight) parks the
            # remaining threads forever, which is a worse outage than the one
            # being fixed and is invisible until it happens. The ceiling is
            # derived from the auth timeout rather than chosen: a leader that
            # has not answered within its own 5s budget plus grace is not
            # going to.
            if not flight.done.wait(self._wait_timeout):
                # An outage, and it must classify as one upstream — 503,
                # session intact. The waiter does NOT fall through to its own
                # `verify()`: eight threads that each give up and start their
                # own GoTrue call is the stampede this whole mechanism exists
                # to prevent, arriving at the exact moment GoTrue is least
                # able to absorb it.
                raise TokenVerificationTimeout(self._wait_timeout)
            if flight.error is not None:
                # Waiters inherit the owner's failure rather than retrying.
                # Retrying here would make N threads presenting one bad token
                # produce N sequential GoTrue calls — a stampede on precisely
                # the path an attacker controls.
                raise flight.error
            assert flight.identity is not None
            return flight.identity

        try:
            identity = verify()
        except BaseException as exception:
            flight.error = exception
            with self._lock:
                # Only remove OUR flight, and only if it is still the one
                # registered — see the `registered` comment above. An
                # overflow (unregistered) flight was never in the map and
                # must never remove someone else's entry from it.
                if registered and self._flights.get(key) is flight:
                    self._flights.pop(key, None)
            flight.done.set()
            raise

        flight.identity = identity
        try:
            with self._lock:
                if registered and self._flights.get(key) is flight:
                    self._flights.pop(key, None)
                if use_cache:
                    self._publish(key, identity, started=flight.started)
        except BaseException as exception:
            # A bug in bookkeeping here (a broken `_publish`, a `MemoryError`
            # acquiring the lock) must not silently read as success to a
            # waiter — that is a *second*, worse bug hiding the first: a
            # waiter checks `flight.error is None` before trusting
            # `flight.identity`, and `flight.identity` was already set above.
            # It also must not leave a waiter blocked for the full
            # `_wait_timeout` before finding out something went wrong; that
            # would turn a rare bug into a slower, more confusing outage.
            flight.error = exception
            flight.done.set()
            raise

        flight.done.set()
        return identity

    def _publish(self, key: str, identity: VerifiedIdentity, *, started: float) -> None:
        """Store a result, unless something revoked it — or overtook it —
        while it was in flight.

        Caller holds the lock. Four rejections. The first three are the same
        bug seen from different directions: an answer that was true when the
        call started and is not true now must not be written down as if it
        were current. The fourth is a distinct race, same shape as
        `IdentityFlagsCache.put`'s `existing[0] > started` check: past
        `_max_in_flight`, two truly concurrent unregistered verifications for
        the same key can both run outside single-flight, and can complete out
        of order. Without this, an older call finishing after a newer one has
        already published would silently overwrite the fresher answer with a
        stale one.
        """
        if self._invalidated_all_at is not None and started <= self._invalidated_all_at:
            return
        invalidated = self._invalidated_at.get(self._token_ns(key))
        if invalidated is not None and started <= invalidated:
            return
        invalidated = self._invalidated_at.get(self._user_ns(identity.user_id))
        if invalidated is not None and started <= invalidated:
            return
        existing = self._data.get(key)
        if existing is not None and existing[1] > started:
            return

        ttl = self._ttl
        if identity.token_exp is not None:
            # The cache may shorten a token's life. It may never extend it.
            remaining = identity.token_exp - time.time()
            if remaining <= 0:
                return
            ttl = min(ttl, remaining)
        if ttl <= 0:
            return

        self._data[key] = (self._now() + ttl, started, identity)
        self._data.move_to_end(key)
        self._by_user.setdefault(identity.user_id, set()).add(key)
        self._evict()

    def invalidate_token(self, token: str) -> None:
        """Drop one token's entry — for logout, where the user id may not be
        in hand at the point the token is read.

        Reachable from an UNAUTHENTICATED caller: `POST /auth/logout` accepts
        and stamps whatever bearer token it is handed, valid or garbage, by
        design (a reader must be able to log out with an expired token). That
        is exactly why every call here also prunes — see
        `_prune_invalidation_stamps`.
        """
        key = self._key(token)
        with self._lock:
            now = self._now()
            self._invalidated_at[self._token_ns(key)] = now
            entry = self._data.get(key)
            if entry is not None:
                self._forget(key, entry[2])
            self._prune_invalidation_stamps(now)

    def invalidate_user(self, user_id: str) -> None:
        """Drop every live token for one reader, including one mid-verification.

        The stamp is not optional. Dropping the stored entries alone leaves any
        verification that started before this call free to finish and publish —
        which is the revoked session walking back in with a full fresh TTL,
        moments after an operator watched the console tell them it was gone.
        """
        with self._lock:
            now = self._now()
            self._invalidated_at[self._user_ns(user_id)] = now
            for key in self._by_user.pop(user_id, set()):
                self._data.pop(key, None)
                self._invalidated_at[self._token_ns(key)] = now
            self._prune_invalidation_stamps(now)

    def invalidate_all(self) -> None:
        """Drop everything, including a verification already in flight.

        A single watermark rather than a sweep of `_invalidated_at`: a flight
        that has not returned yet has no key in it to stamp, so that map
        alone cannot cover it.
        """
        with self._lock:
            now = self._now()
            self._invalidated_all_at = now
            self._data.clear()
            self._by_user.clear()
            # The watermark above already covers every flight regardless of
            # key or user, so the per-key/per-user stamps are redundant from
            # this point forward — safe to clear outright rather than merely
            # pruned by age.
            self._invalidated_at.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
