"""Diagnostic extractor for PostgREST API errors and upstream transport faults.

Background & Incident Context
-----------------------------
During a privileged Supabase incident (2026-09-07), every service-role call failed
with HTTP 401 because an invalid key was configured. The installed ``postgrest``
SDK (2.30.1) declared its error model with four ``Optional[str]`` fields with no
defaults. Under pydantic v2, omitting defaults makes fields required. Because the
gateway returned only ``{"message": ..., "hint": ...}`` (no ``code`` or ``details``),
pydantic validation failed, and the SDK discarded the parsed body and substituted a
generic placeholder:

    APIError: {'message': 'JSON could not be generated', 'code': 401,
               'hint': 'Refer to full message for details',
               'details': 'b\'{"message":"Unregistered API key","hint":"Double check ..."}\''}

The true error message survived only as a repr'd byte string inside ``details``.
Calling ``str(exception)`` or ``exception.json()`` still yielded the uninformative
headline "JSON could not be generated", hiding the root cause behind a 30-line
traceback.

Design & Guarantees
-------------------
1. **Bounded:** Logs must never ingest unbounded response bodies. Output is capped
   at :data:`MAX_ERROR_DESCRIPTION_LENGTH` (~300 chars).
2. **Sanitized:** Any credential-shaped token (JWTs starting with ``eyJ...``,
   new-style Supabase keys starting with ``sb_secret_...`` or ``sb_publishable_...``,
   and ``apikey`` or ``Authorization`` header values) is replaced with ``<redacted>``.
3. **Recovers real message:** Detects the SDK's placeholder and unwraps the true
   message from ``details`` whether it is a Python repr of bytes, actual bytes,
   plain JSON text, or non-JSON text.
4. **Never raises:** Operates inside ``except`` handlers during outages; any internal
   failure degrades gracefully to a plain string representation.
5. **Universal call site:** Accepts any :class:`BaseException`, falling back to
   ``f"{type(exception).__name__}: {exception}"`` when the error is not an
   :class:`APIError`.
6. **Preserves HTTP code:** Prefixes the HTTP-ish status code (e.g. 401 vs 404)
   when available to disambiguate credential faults from schema/function errors.
"""

from __future__ import annotations

import ast
import contextlib
import json
import re
from typing import Any

# Maximum character length for any extracted error description.
# Keeps log entries on a single bounded line and prevents log buffer overflow
# or traceback truncation in cloud log aggregators.
MAX_ERROR_DESCRIPTION_LENGTH: int = 300

# The sentinel headline substituted by postgrest-py when pydantic validation fails.
_SDK_PLACEHOLDER: str = "JSON could not be generated"

# Imported defensively mirroring web/api/app.py's optional SDK symbol handling.
# A missing, renamed, or uninstalled postgrest package must not break app boot.
APIError: type[Exception] | None
try:
    from postgrest.exceptions import APIError
except ImportError:  # pragma: no cover - exercised when postgrest is uninstalled
    APIError = None

__all__ = ["MAX_ERROR_DESCRIPTION_LENGTH", "describe_api_error"]

# Credential patterns to sanitize from diagnostic strings.
# Must redact header values, new-style Supabase keys, and JWT tokens.
_CREDENTIAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Header values for apikey or authorization (with or without Bearer prefix, quoted/unquoted)
    (
        re.compile(
            r"""(?i)(['"`]?\b(?:apikey|authorization)\b['"`]?\s*[:=]\s*['"`]?(?:Bearer\s+)?)([^\s'"`',;]+)(['"`]?)"""
        ),
        r"\g<1><redacted>\g<3>",
    ),
    # Standalone Bearer token values
    (
        re.compile(r"(?i)\b(Bearer\s+)[^\s'\"`,;]+"),
        r"\g<1><redacted>",
    ),
    # New-style Supabase project keys: sb_secret_... and sb_publishable_...
    (
        re.compile(r"\bsb_(?:secret|publishable)_[A-Za-z0-9_-]+"),
        "<redacted>",
    ),
    # Standard JWT tokens: starts with eyJ, consists of base64url characters and optional dots
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*"),
        "<redacted>",
    ),
)


def _safe_getattr(obj: Any, attr: str) -> Any:
    """Read an attribute safely without allowing custom property exceptions to escape."""
    try:
        return getattr(obj, attr, None)
    except BaseException:
        return None


def _sanitize(text: str) -> str:
    """Replace credential-shaped strings (JWTs, Supabase keys, headers) with <redacted>."""
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        with contextlib.suppress(BaseException):
            text = pattern.sub(replacement, text)
    return text


def _truncate(text: str, max_len: int = MAX_ERROR_DESCRIPTION_LENGTH) -> str:
    """Enforce a strict upper bound on string length."""
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3].rstrip() + "..."


def _extract_details_data(details: Any) -> Any:
    """Unpack error details whether passed as bytes, repr of bytes, JSON, or plain text."""
    if details is None:
        return None
    if isinstance(details, dict):
        return details
    if isinstance(details, (bytes, bytearray)):
        try:
            decoded = details.decode("utf-8", errors="replace")
        except BaseException:
            return None
        try:
            return json.loads(decoded)
        except BaseException:
            return decoded
    if isinstance(details, str):
        s = details.strip()
        if not s:
            return None
        # Handle Python repr of bytes: b'...' or b"..."
        if (s.startswith("b'") and s.endswith("'")) or (s.startswith('b"') and s.endswith('"')):
            try:
                evaluated = ast.literal_eval(s)
                if isinstance(evaluated, (bytes, bytearray)):
                    decoded = evaluated.decode("utf-8", errors="replace")
                    try:
                        return json.loads(decoded)
                    except BaseException:
                        return decoded
            except BaseException:
                # Fallback if literal_eval fails: slice off b' and '
                inner = s[2:-1]
                try:
                    fixed = inner.replace(r"\'", "'")
                    return json.loads(fixed)
                except BaseException:
                    return inner
        # Plain JSON text or plain error message
        try:
            return json.loads(s)
        except BaseException:
            return s
    try:
        return str(details)
    except BaseException:
        return None


def _is_api_error(exc: BaseException) -> bool:
    """Check if the exception is a postgrest APIError or duck-typed equivalent."""
    if APIError is not None and isinstance(exc, APIError):
        return True
    return type(exc).__name__ == "APIError"


def describe_api_error(exception: BaseException) -> str:
    """Turn a PostgREST APIError or general exception into a short, safe diagnostic string.

    Guaranteed never to raise. Bounded to :data:`MAX_ERROR_DESCRIPTION_LENGTH`.
    Redacts credentials and recovers the true gateway error from `details` when
    postgrest's "JSON could not be generated" placeholder is present.
    """
    try:
        return _describe_api_error_impl(exception)
    except BaseException:
        try:
            name = type(exception).__name__
            return _truncate(_sanitize(f"{name}: <unprintable exception>"))
        except BaseException:
            return "BaseException: <unprintable exception>"


def _describe_api_error_impl(exception: BaseException) -> str:
    """Internal implementation of error description extraction."""
    if not _is_api_error(exception):
        try:
            exc_text = str(exception).strip()
        except BaseException:
            exc_text = "<unprintable exception>"
        type_name = type(exception).__name__
        formatted = f"{type_name}: {exc_text}" if exc_text else type_name
        collapsed = " ".join(formatted.split())
        return _truncate(_sanitize(collapsed))

    code = _safe_getattr(exception, "code")
    message = _safe_getattr(exception, "message")
    details = _safe_getattr(exception, "details")
    raw_error = _safe_getattr(exception, "_raw_error")

    if isinstance(raw_error, dict):
        if code is None:
            code = raw_error.get("code")
        if message is None:
            message = raw_error.get("message")
        if details is None:
            details = raw_error.get("details")

    msg_str = str(message).strip() if message is not None else ""
    if not msg_str or _SDK_PLACEHOLDER in msg_str:
        unpacked = _extract_details_data(details)
        if isinstance(unpacked, dict):
            inner_msg = (
                unpacked.get("message")
                or unpacked.get("error")
                or unpacked.get("msg")
                or unpacked.get("hint")
            )
            if inner_msg:
                msg_str = str(inner_msg).strip()
            if code is None and unpacked.get("code") is not None:
                code = unpacked.get("code")
        elif isinstance(unpacked, str) and unpacked.strip():
            msg_str = unpacked.strip()

    code_str = str(code).strip() if code is not None else ""
    if code_str and msg_str:
        if msg_str.startswith(code_str) or msg_str.startswith(f"Error {code_str}"):
            formatted = msg_str
        else:
            formatted = f"{code_str} {msg_str}"
    elif code_str:
        formatted = f"Error {code_str}"
    elif msg_str:
        formatted = msg_str
    else:
        formatted = type(exception).__name__

    collapsed = " ".join(formatted.split())
    return _truncate(_sanitize(collapsed))
