"""One digest function, so three call sites cannot quietly drift apart.

`web/api/app.py`'s `_account_rate_key`, `web/api/admin.py`'s
`_admin_notification_rate_key`, and `web/services/token_verification_cache.py`'s
cache key each need the same thing: turn a bearer token into something safe to
key a dict or a rate-limit bucket by, without ever holding the raw credential
longer than necessary. All three had reimplemented the identical one-liner
independently. A future change to the scheme (a pepper, a different digest)
now has exactly one place to make it.
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
