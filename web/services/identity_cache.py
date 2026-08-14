"""Who a reader is, cached for the length of a page-load rather than a session.

Every authenticated request already costs one network round trip to Supabase
(``supabase.auth.get_user``). Reading the reader's role and disabled flag would
double that, on a path where a chat turn is already the slow thing. So the flags
are cached in process.

Scope
-----
PROCESS-LOCAL, exactly like ``ConversationStore`` and for the same deployment
reason: this app runs ``--workers 1 --threads 8`` because the FAISS index and
the sentence-transformers model live in RAM. A second worker would mean one
process serving a stale role for up to the TTL after a demotion.

**The cache is never the authority.** The database is. Two consequences that are
easy to get wrong:

* Every change made *through the console* calls :meth:`IdentityFlagsCache.invalidate`
  before it returns, so an operator never sees their own change lag. The TTL only
  bounds staleness for changes made outside the app — the SQL editor, the
  Supabase dashboard — where 30 seconds resolves long before anyone files a bug.
* A failed lookup is **not** cached. A transient Supabase blip must not pin a
  reader to ``role='user'`` for the next 30 seconds; the next request retries.
  A genuinely absent row *is* cached, because "this account has no profile" is a
  stable fact rather than a failure.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_TIER = "free"


@dataclass(frozen=True)
class IdentityFlags:
    """What the server knows about a reader beyond "they have a valid token".

    Frozen so a cached entry cannot be mutated by whoever reads it, and so a
    request that captured it keeps a coherent set of values even if the account
    changes mid-request.
    """

    user_id: str
    email: str | None
    role: str
    tier: str
    is_disabled: bool
    # False when these values are a guess rather than an answer — the lookup
    # failed, or there is no way to make one. "We do not know" and "we know they
    # are an ordinary enabled reader" used to be the same value, which meant a
    # Supabase outage silently readmitted every disabled account.
    is_resolved: bool = True

    @property
    def is_admin(self) -> bool:
        """Privilege requires an answer, not an absence of one.

        Unresolved is never admin: the only safe reading of "we could not check"
        is the unprivileged one.
        """
        return self.role == "admin" and self.is_resolved

    @classmethod
    def unprivileged(cls, user_id: str, email: str | None = None) -> "IdentityFlags":
        """A reader with no powers and no block — a real, resolved fact.

        For an account that genuinely has no profile row. Distinct from
        :meth:`unknown`, which is what a failed lookup produces.
        """
        return cls(
            user_id=user_id,
            email=email,
            role="user",
            tier=DEFAULT_TIER,
            is_disabled=False,
            is_resolved=True,
        )

    @classmethod
    def unknown(cls, user_id: str, email: str | None = None) -> "IdentityFlags":
        """We could not determine this reader's standing.

        Fails closed on privilege and open on access: no console, but the
        question still gets answered. A retrieval outage taking down a product
        whose whole job is answering one question quickly would be a worse
        failure than the one it is protecting against — and a caller that knows
        a *previous* disabled answer should prefer that to this.
        """
        return cls(
            user_id=user_id,
            email=email,
            role="user",
            tier=DEFAULT_TIER,
            is_disabled=False,
            is_resolved=False,
        )


class IdentityFlagsCache:
    """TTL + LRU bounded ``{user_id: IdentityFlags}``."""

    def __init__(self, ttl_seconds: float = 30.0, max_entries: int = 2000) -> None:
        self._data: OrderedDict[str, tuple[float, IdentityFlags]] = OrderedDict()
        self._ttl = ttl_seconds
        self._max = max_entries
        self._lock = threading.Lock()
        # When each user's entry was last invalidated. A fetch that began before
        # its user was invalidated must not publish: `invalidate()` alone cannot
        # stop a SELECT that is already in flight, and that request would
        # otherwise restore the very privilege the invalidation removed, with a
        # fresh TTL on top.
        self._invalidated_at: dict[str, float] = {}

    # Injected so tests can control time without patching module globals.
    @staticmethod
    def _now() -> float:
        import time
        return time.monotonic()

    def _evict(self) -> None:
        """Enforce the size bound only. Caller must hold the lock.

        Expiry is deliberately NOT eviction. An expired entry still answers
        "what did we last know about this reader", which is the difference
        between a disabled account staying out during an outage and walking
        back in. Deleting on expiry destroyed exactly the answer the fallback
        needs — so the TTL governs freshness, and LRU governs memory.
        """
        while len(self._data) > self._max:
            oldest, _ = self._data.popitem(last=False)
            self._invalidated_at.pop(oldest, None)

    def begin_fetch(self) -> float:
        """Stamp to take *before* a lookup, and hand back to :meth:`put`.

        Publication is ordered by when the fetch STARTED, not when it finished.
        Two concurrent misses can complete out of order — an older SELECT
        returning after a newer one — and without this the older, staler answer
        wins and is given a full fresh TTL.
        """
        return self._now()

    def get(self, user_id: str) -> IdentityFlags | None:
        """Fresh flags, or None when absent or past the TTL.

        An expired entry is retained rather than dropped — see :meth:`_evict`
        and :meth:`last_known`.
        """
        with self._lock:
            self._evict()
            entry = self._data.get(user_id)
            if entry is None or self._now() - entry[0] > self._ttl:
                return None
            self._data.move_to_end(user_id)
            return entry[1]

    def last_known(self, user_id: str) -> IdentityFlags | None:
        """The most recent answer for this reader, expired or not.

        For the one case where stale beats nothing: a lookup has just failed,
        and the choice is between an answer from a minute ago and admitting
        someone whose account may have been disabled. Expiry means "re-check",
        not "forget".
        """
        with self._lock:
            entry = self._data.get(user_id)
            return entry[1] if entry else None

    def put(self, flags: IdentityFlags, *, fetched_at: float | None = None) -> bool:
        """Publish a lookup result. Returns False if it was rejected as stale.

        Rejected when the entry was invalidated after this fetch began, or when
        a newer fetch has already published — the two races that would let a
        revoked privilege come back.
        """
        started = self._now() if fetched_at is None else fetched_at
        with self._lock:
            invalidated = self._invalidated_at.get(flags.user_id)
            if invalidated is not None and started <= invalidated:
                return False

            existing = self._data.get(flags.user_id)
            if existing is not None and existing[0] > started:
                return False

            self._data[flags.user_id] = (started, flags)
            self._data.move_to_end(flags.user_id)
            self._evict()
            return True

    def invalidate(self, user_id: str) -> None:
        """Drop one reader's entry. Call this before returning from a change."""
        with self._lock:
            self._data.pop(user_id, None)
            self._invalidated_at[user_id] = self._now()

    def invalidate_all(self) -> None:
        """Drop everything. For a change whose blast radius is every reader."""
        with self._lock:
            now = self._now()
            for user_id in list(self._data) + list(self._invalidated_at):
                self._invalidated_at[user_id] = now
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
