"""Tests for bounded, sanitized PostgREST error extractor (web.utils.postgrest_errors).

Verifies recovery of the true gateway error from details when postgrest SDK
substitutes its 'JSON could not be generated' placeholder, length bounds,
credential sanitization (JWT, sb_secret_, sb_publishable_, headers), and
graceful non-raising behavior under pathological inputs.
"""

from __future__ import annotations

import pytest
from postgrest.exceptions import APIError

from web.utils.postgrest_errors import (
    MAX_ERROR_DESCRIPTION_LENGTH,
    describe_api_error,
)


def test_real_world_placeholder_recovers_unregistered_api_key():
    """Real-world incident shape: SDK pydantic failure hides true message in details repr."""
    # This exact shape was observed in the 2026-09-07 Supabase service-role incident:
    raw_error = {
        "message": "JSON could not be generated",
        "code": 401,
        "hint": "Refer to full message for details",
        "details": 'b\'{"message":"Unregistered API key","hint":"Double check that the API key you\'re using is active and matches the project."}\'',
    }
    exc = APIError(raw_error)

    # Prove why this helper is necessary: str(exc) and exc.json() still output
    # the useless headline and do NOT expose the clean true error.
    assert "JSON could not be generated" in str(exc)
    assert exc.json()["message"] == "JSON could not be generated"

    description = describe_api_error(exc)

    # The recovered description must highlight the true gateway message and HTTP code,
    # and MUST NOT contain the discarded pydantic validation headline.
    assert "Unregistered API key" in description
    assert "JSON could not be generated" not in description
    assert "401" in description
    assert description == "401 Unregistered API key"


def test_details_as_actual_bytes():
    """Unwraps true error message when details is passed as raw bytes."""
    raw_error = {
        "message": "JSON could not be generated",
        "code": 401,
        "hint": "Refer to full message for details",
        "details": b'{"message":"Unregistered API key","hint":"Check project"}',
    }
    exc = APIError(raw_error)

    description = describe_api_error(exc)
    assert "Unregistered API key" in description
    assert "JSON could not be generated" not in description
    assert "401" in description


def test_details_present_but_not_json():
    """Degrades to raw details text when gateway response is plain text (e.g. 502 HTML/text)."""
    raw_error = {
        "message": "JSON could not be generated",
        "code": 502,
        "hint": "Refer to full message for details",
        "details": "Bad Gateway: upstream connection failed",
    }
    exc = APIError(raw_error)

    description = describe_api_error(exc)
    assert "502 Bad Gateway: upstream connection failed" in description
    assert "JSON could not be generated" not in description


def test_details_missing_or_none():
    """Produces safe bounded description when details is None or absent."""
    raw_error = {
        "message": "JSON could not be generated",
        "code": 401,
        "hint": "Refer to full message for details",
        "details": None,
    }
    exc = APIError(raw_error)

    description = describe_api_error(exc)
    # When no details exist, the function falls back safely without raising
    assert "401" in description
    assert "JSON could not be generated" in description


def test_non_apierror_fallback():
    """General exceptions produce standard type: message format."""
    exc = ValueError("parameter 'limit' must be positive")
    description = describe_api_error(exc)
    assert description == "ValueError: parameter 'limit' must be positive"

    empty_exc = RuntimeError()
    assert describe_api_error(empty_exc) == "RuntimeError"


def test_length_cap_enforced():
    """Strictly enforces MAX_ERROR_DESCRIPTION_LENGTH and terminates with ellipsis."""
    huge_body = "A" * 1000
    exc = ValueError(huge_body)

    description = describe_api_error(exc)
    assert len(description) <= MAX_ERROR_DESCRIPTION_LENGTH
    assert description.endswith("...")


def test_credential_sanitization_jwt_and_supabase_keys():
    """Redacts JWTs, new-style Supabase keys, and authorization headers."""
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJl"
    sb_secret = "sb_secret_N2JmMWYyZjMtMmFiYi00ZDg4LTk3N2Ut_abc12345"
    sb_pub = "sb_publishable_N2JmMWYyZjMtMmFiYi00ZDg4LTk3N2Ut_abc12345"

    raw_error = {
        "message": "JSON could not be generated",
        "code": 401,
        "details": (
            f"Failed token {jwt} with secret {sb_secret} and pub {sb_pub} "
            f"headers: apikey={sb_secret}, Authorization: Bearer {jwt}"
        ),
    }
    exc = APIError(raw_error)

    description = describe_api_error(exc)

    assert jwt not in description
    assert sb_secret not in description
    assert sb_pub not in description
    assert "<redacted>" in description


def test_pathological_input_never_raises():
    """Guarantees describe_api_error never raises even with broken __str__ or __repr__."""

    class BrokenStrError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("broken __str__ implementation")

        def __repr__(self) -> str:
            raise RuntimeError("broken __repr__ implementation")

    class BrokenAttrError(Exception):
        @property
        def message(self) -> str:
            raise RuntimeError("broken message property")

        @property
        def details(self) -> str:
            raise RuntimeError("broken details property")

    # None of these may raise any exception
    desc1 = describe_api_error(BrokenStrError())
    assert "BrokenStrError" in desc1

    desc2 = describe_api_error(BrokenAttrError())
    assert isinstance(desc2, str)
    assert len(desc2) > 0


def test_normal_postgrest_error_without_placeholder():
    """Preserves standard Postgres/PostgREST errors when no placeholder was substituted."""
    raw_error = {
        "message": "relation 'profiles' does not exist",
        "code": "42P01",
        "details": None,
        "hint": None,
    }
    exc = APIError(raw_error)

    description = describe_api_error(exc)
    assert description == "42P01 relation 'profiles' does not exist"


def test_chat_store_list_sessions_raises_persistence_unavailable_with_described_error():
    """list_sessions wraps APIError into PersistenceUnavailable carrying the recovered description."""
    from unittest.mock import MagicMock

    from web.services.chat_store import PersistenceUnavailable, SupabaseChatBackend

    mock_client = MagicMock()
    raw_error = {
        "message": "JSON could not be generated",
        "code": 401,
        "hint": "Refer to full message for details",
        "details": 'b\'{"message":"Unregistered API key"}\'',
    }
    mock_client.rpc.return_value.execute.side_effect = APIError(raw_error)

    backend = SupabaseChatBackend(mock_client)
    with pytest.raises(PersistenceUnavailable) as exc_info:
        backend.list_sessions("usr_test_123")

    assert "401 Unregistered API key" in str(exc_info.value)
    assert "JSON could not be generated" not in str(exc_info.value)


def test_admin_store_identity_lookup_logs_described_error(caplog, monkeypatch):
    """resolve_identity_flags logs the described error instead of placeholder headline."""
    import logging
    from unittest.mock import MagicMock

    import web.services.admin_store as admin_store
    from web.services.identity_cache import IdentityFlagsCache

    mock_backend = MagicMock()
    raw_error = {
        "message": "JSON could not be generated",
        "code": 401,
        "hint": "Refer to full message for details",
        "details": 'b\'{"message":"Unregistered API key"}\'',
    }
    mock_backend.fetch_identity.side_effect = APIError(raw_error)
    monkeypatch.setattr(admin_store, "get_admin_backend", lambda: mock_backend)

    cache = IdentityFlagsCache()
    with caplog.at_level(logging.ERROR):
        admin_store.resolve_identity_flags(cache, "usr_admin_123", "admin@example.com")

    matching = [
        r
        for r in caplog.records
        if "usr_admin_123" in r.message and "401 Unregistered API key" in r.message
    ]
    assert len(matching) == 1
    assert "JSON could not be generated" not in matching[0].message
