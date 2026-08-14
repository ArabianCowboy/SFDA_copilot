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

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @classmethod
    def unprivileged(cls, user_id: str, email: str | None = None) -> "IdentityFlags":
        """The safe default: a signed-in reader with no powers and no block.

        Used both for an account with no profile row and for a lookup that
        failed. Never grants anything; never withholds chat.
        """
        return cls(
            user_id=user_id,
            email=email,
            role="user",
            tier=DEFAULT_TIER,
            is_disabled=False,
        )


class IdentityFlagsCache:
    """TTL + LRU bounded ``{user_id: IdentityFlags}``."""

    def __init__(self, ttl_seconds: float = 30.0, max_entries: int = 2000) -> None:
        self._data: OrderedDict[str, tuple[float, IdentityFlags]] = OrderedDict()
        self._ttl = ttl_seconds
        self._max = max_entries
        self._lock = threading.Lock()

    # Injected so tests can control time without patching module globals.
    @staticmethod
    def _now() -> float:
        import time
        return time.monotonic()

    def _evict(self) -> None:
        """Caller must hold the lock."""
        now = self._now()
        expired = [k for k, (stamp, _) in self._data.items() if now - stamp > self._ttl]
        for key in expired:
            del self._data[key]
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def get(self, user_id: str) -> IdentityFlags | None:
        """Return cached flags, or None on a miss or an expired entry."""
        with self._lock:
            self._evict()
            entry = self._data.get(user_id)
            if entry is None:
                return None
            self._data.move_to_end(user_id)
            return entry[1]

    def put(self, flags: IdentityFlags) -> None:
        with self._lock:
            self._data[flags.user_id] = (self._now(), flags)
            self._data.move_to_end(flags.user_id)
            self._evict()

    def invalidate(self, user_id: str) -> None:
        """Drop one reader's entry. Call this before returning from a change."""
        with self._lock:
            self._data.pop(user_id, None)

    def invalidate_all(self) -> None:
        """Drop everything. For a change whose blast radius is every reader."""
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
