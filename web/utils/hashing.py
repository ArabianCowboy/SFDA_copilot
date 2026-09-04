"""One digest function, so call sites cannot quietly drift apart.

`web/services/token_verification_cache.py`'s cache key needs to turn a bearer
token into something safe to key a dict by, without ever holding the raw
credential longer than necessary. Several places had reimplemented the identical
one-liner independently. A future change to the scheme (a pepper, a different
digest) now has exactly one place to make it.

The two rate-limit key functions that used to be listed here are gone: since
2026-09-03 the limiter keys on the ACCOUNT (`app.py`'s `_rate_key`), because a
per-session token hash gave one reader on two devices two budgets and let an
attacker holding stolen credentials mint a fresh bucket by signing in again.
"""

from __future__ import annotations

import hashlib


def sha256_hex(value: str) -> str:
    """The hex-encoded SHA-256 digest of a UTF-8 string.

    Not a general-purpose hashing utility — named and scoped for the one job
    every caller above actually has: a bearer token (or similar secret) as a
    dict key or rate-limit bucket, never as a security boundary on its own.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
