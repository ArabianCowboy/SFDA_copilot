"""Pin the RPC name and the exact argument dict every Supabase write sends.

Every route-level admin, notification and chat test runs against an
``InMemory*Backend`` double, which accepts any dict. PostgREST does not: it
resolves a function by its argument NAMES, so a missing or extra key is
``PGRST202 function not found`` in production only, and a value under the wrong
key resolves fine and writes the wrong data. So each case asserts full dict
equality against sentinel values, one per input and one per actor field.

Derived fields (the notification payload hash, a clamped chat title, the
archive opt-out) are computed through the same helpers the backend uses, so
these tests pin the payload rather than hashing or clamping internals.
"""

from __future__ import annotations

import pytest

from web.services.admin_store import SupabaseAdminBackend
from web.services.audit import AuditActor
from web.services.chat_store import SupabaseChatBackend, clamp_load_limit, clamp_title
from web.services.notification_store import SupabaseNotificationBackend, _payload_hash

ACTOR = AuditActor(
    user_id="actor-id", email="actor@example.test", request_ip="203.0.113.7", user_agent="agent/1"
)
USER_ID = "11111111-1111-4111-8111-111111111111"
NOTIFICATION_ID = "22222222-2222-4222-8222-222222222222"
OWNER_ID = "33333333-3333-4333-8333-333333333333"
SESSION_ID = "44444444-4444-4444-8444-444444444444"

WITH_EMAIL = {
    "p_actor_id": "actor-id",
    "p_actor_email": "actor@example.test",
    "p_request_ip": "203.0.113.7",
    "p_user_agent": "agent/1",
}
# The tier and quota functions resolve the email from the id they validate, so a
# caller-supplied address can never reach the audit trail (admin_store.py).
WITHOUT_EMAIL = {k: v for k, v in WITH_EMAIL.items() if k != "p_actor_email"}


class _Call:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return type("Response", (), {"data": self._data})()


class RecordingClient:
    """Records every ``rpc(name, args)``. ``data=None`` survives both ``or {}`` and ``or []``."""

    def __init__(self, data=None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._data = data

    def rpc(self, name, args):
        self.calls.append((name, dict(args)))
        return _Call(self._data)


def _only_call(client: RecordingClient) -> tuple[str, dict]:
    assert len(client.calls) == 1, client.calls
    return client.calls[0]


# ── admin ────────────────────────────────────────────────────────────────────

ADMIN_CASES = [
    pytest.param(
        lambda b: b.put_settings({"s": 1}, actor=ACTOR, before={"b": 1}, after={"a": 1}),
        "admin_write_settings",
        {"p_settings": {"s": 1}, "p_before": {"b": 1}, "p_after": {"a": 1}, **WITH_EMAIL},
        id="put_settings",
    ),
    pytest.param(
        lambda b: b.update_profile(
            USER_ID,
            first_name="first",
            family_name="family",
            age=41,
            organization="org",
            specialization="spec",
            expected_updated_at="2026-01-01T00:00:00Z",
            actor=ACTOR,
        ),
        "admin_update_profile",
        {
            "p_user_id": USER_ID,
            "p_first_name": "first",
            "p_family_name": "family",
            "p_age": 41,
            "p_organization": "org",
            "p_specialization": "spec",
            "p_expected_updated_at": "2026-01-01T00:00:00Z",
            **WITH_EMAIL,
        },
        id="update_profile",
    ),
    pytest.param(
        lambda b: b.set_user_flags(
            USER_ID, role="admin", is_disabled=True, reason="r", actor=ACTOR
        ),
        "admin_set_user_flags",
        {
            "p_user_id": USER_ID,
            "p_role": "admin",
            "p_is_disabled": True,
            "p_reason": "r",
            **WITH_EMAIL,
        },
        id="set_user_flags",
    ),
    pytest.param(
        lambda b: b.create_tier(
            key="k", label_en="en", label_ar="ar", daily_message_limit=7, ordering=3, actor=ACTOR
        ),
        "admin_create_tier",
        {
            "p_key": "k",
            "p_label_en": "en",
            "p_label_ar": "ar",
            "p_daily_message_limit": 7,
            "p_ordering": 3,
            **WITHOUT_EMAIL,
        },
        id="create_tier",
    ),
    pytest.param(
        lambda b: b.update_tier(
            "k", label_en="en", label_ar="ar", daily_message_limit=7, ordering=3, actor=ACTOR
        ),
        "admin_update_tier",
        {
            "p_key": "k",
            "p_label_en": "en",
            "p_label_ar": "ar",
            "p_daily_message_limit": 7,
            "p_ordering": 3,
            **WITHOUT_EMAIL,
        },
        id="update_tier",
    ),
    pytest.param(
        lambda b: b.delete_tier("k", actor=ACTOR),
        "admin_delete_tier",
        {"p_key": "k", **WITHOUT_EMAIL},
        id="delete_tier",
    ),
    pytest.param(
        lambda b: b.set_users_tier([USER_ID], tier="staff", reason="move week", actor=ACTOR),
        "admin_set_users_tier",
        {"p_user_ids": [USER_ID], "p_tier": "staff", "p_reason": "move week", **WITHOUT_EMAIL},
        id="set_users_tier",
    ),
    pytest.param(
        lambda b: b.set_reader_quota(
            USER_ID,
            tier="pro",
            override=9,
            starts_at="2026-01-01",
            expires_at="2026-02-01",
            reason="r",
            actor=ACTOR,
        ),
        "admin_set_reader_quota",
        {
            "p_user_id": USER_ID,
            "p_tier": "pro",
            "p_daily_message_limit_override": 9,
            "p_reason": "r",
            "p_override_starts_at": "2026-01-01",
            "p_override_expires_at": "2026-02-01",
            **WITHOUT_EMAIL,
        },
        id="set_reader_quota",
    ),
]


@pytest.mark.parametrize(("invoke", "name", "args"), ADMIN_CASES)
def test_admin_writes_send_exactly_these_arguments(invoke, name, args):
    client = RecordingClient()
    invoke(SupabaseAdminBackend(client))
    assert _only_call(client) == (name, args)


def test_list_users_omits_p_tier_when_not_filtering():
    """Unfiltered, the call names only the three original arguments, so People
    keeps working against the 3-argument function a schema-first rollback
    would restore."""
    client = RecordingClient(data=[])
    SupabaseAdminBackend(client).list_users(limit=10, offset=0, search=None)
    assert _only_call(client) == (
        "admin_list_users",
        {"p_limit": 10, "p_offset": 0, "p_search": None},
    )


def test_list_users_sends_the_tier_key_when_filtering():
    client = RecordingClient(data=[])
    SupabaseAdminBackend(client).list_users(limit=10, offset=0, search=None, tier="staff")
    assert _only_call(client) == (
        "admin_list_users",
        {"p_limit": 10, "p_offset": 0, "p_search": None, "p_tier": "staff"},
    )


def test_set_users_tier_sends_every_id_even_when_none_is_a_uuid():
    """The RPC takes text and reports a non-uuid as missing itself, after its
    actor and tier checks. Short-circuiting here would skip those refusals."""
    client = RecordingClient(data={"moved_ids": [], "unchanged": 0, "missing": ["not-a-uuid"]})
    SupabaseAdminBackend(client).set_users_tier(
        ["not-a-uuid"], tier="staff", reason=None, actor=ACTOR
    )
    name, args = _only_call(client)
    assert name == "admin_set_users_tier"
    assert args["p_user_ids"] == ["not-a-uuid"]


@pytest.mark.parametrize(
    "value",
    [
        "urn:uuid:12345678-1234-1234-1234-123456789abc",
        "{12345678-1234-1234-1234-123456789abc}",
        "+12345678-1234-1234-1234-123456789abc",
        "123456781234123412341234567890ab",
        "\u0661" * 8 + "-1234-1234-1234-123456789abc",
    ],
)
def test_is_uuid_accepts_only_the_form_postgres_accepts(value):
    """uuid.UUID alone takes every one of these; Postgres's uuid input fails
    them with 22P02, which surfaces as a 500."""
    from web.services.admin_store import _is_uuid

    assert _is_uuid(value) is False
    assert _is_uuid("12345678-1234-1234-1234-123456789ABC") is True


# ── notifications ────────────────────────────────────────────────────────────

_CREATE_FIELDS = {
    "type": "banner",
    "severity": "info",
    "title_en": "title en",
    "title_ar": "title ar",
    "body_en": "body en",
    "body_ar": "body ar",
    "target_kind": "user",
    "target_role": "role",
    "target_tier": "tier",
    "target_user_id": USER_ID,
    "expires_at": "2026-03-01T00:00:00Z",
}


def _lifecycle_case(method: str, rpc: str):
    return pytest.param(
        lambda b: getattr(b, method)(NOTIFICATION_ID, actor=ACTOR),
        rpc,
        {"p_notification_id": NOTIFICATION_ID, **WITH_EMAIL},
        id=method,
    )


NOTIFICATION_CASES = [
    pytest.param(
        lambda b: b.create(
            **_CREATE_FIELDS, resend_of="resend-id", client_request_id="req-id", actor=ACTOR
        ),
        "admin_create_notification",
        {
            **{f"p_{key}": value for key, value in _CREATE_FIELDS.items()},
            "p_resend_of": "resend-id",
            "p_client_request_id": "req-id",
            "p_request_payload_hash": _payload_hash(*_CREATE_FIELDS.values()),
            **WITH_EMAIL,
        },
        id="create",
    ),
    _lifecycle_case("deactivate", "admin_deactivate_notification"),
    _lifecycle_case("delete", "admin_delete_notification"),
    _lifecycle_case("purge", "admin_purge_notification"),
    pytest.param(
        lambda b: b.mark_read(NOTIFICATION_ID, USER_ID, "dismissed"),
        "notifications_mark_read",
        {"p_notification_id": NOTIFICATION_ID, "p_user_id": USER_ID, "p_action": "dismissed"},
        id="mark_read",
    ),
    pytest.param(
        lambda b: b.mark_all_read(USER_ID),
        "notifications_mark_all_read",
        {"p_user_id": USER_ID},
        id="mark_all_read",
    ),
]


@pytest.mark.parametrize(("invoke", "name", "args"), NOTIFICATION_CASES)
def test_notification_writes_send_exactly_these_arguments(invoke, name, args):
    client = RecordingClient()
    invoke(SupabaseNotificationBackend(client))
    assert _only_call(client) == (name, args)


# ── chat ─────────────────────────────────────────────────────────────────────

_TITLE = "  A  question\nwith   gaps " + "x" * 130
_SOURCES = [{"document": "doc.pdf", "source_index": 1}]

# (id, invocation, rpc name, expected args). Shared with test_postgrest_errors.py,
# which drives the same seven invocations through a failing client.
CHAT_CALLS = [
    (
        "append_turn",
        lambda b: b.append_turn(
            owner_id=OWNER_ID,
            session_id=SESSION_ID,
            client_request_id="req-id",
            question="q",
            answer="a",
            sources=_SOURCES,
            lang="ar",
            category="drugs",
            model="model-x",
            corpus_revision="rev-1",
            owner_key="owner-key",
            session_key=None,
            archive_opted_out=False,
            title=_TITLE,
            allow_create=False,
        ),
        "chat_append_turn",
        {
            "p_title": clamp_title(_TITLE),
            "p_owner_id": OWNER_ID,
            "p_session_id": SESSION_ID,
            "p_client_request_id": "req-id",
            "p_question": "q",
            "p_answer": "a",
            "p_sources": _SOURCES,
            "p_lang": "ar",
            "p_category": "drugs",
            "p_model": "model-x",
            "p_corpus_revision": "rev-1",
            "p_owner_key": "owner-key",
            "p_session_key": None,
            # A missing session key opts the archive row out (chat_store.py).
            "p_archive_opted_out": True,
            "p_allow_create": False,
        },
    ),
    (
        "session_exists",
        lambda b: b.session_exists(OWNER_ID, SESSION_ID),
        "chat_session_exists",
        {"p_owner_id": OWNER_ID, "p_session_id": SESSION_ID},
    ),
    (
        "load_session",
        lambda b: b.load_session(OWNER_ID, SESSION_ID, limit=9999, before_seq=17),
        "chat_load_session",
        {
            "p_owner_id": OWNER_ID,
            "p_session_id": SESSION_ID,
            "p_limit": clamp_load_limit(9999),
            "p_before_seq": 17,
        },
    ),
    (
        "list_sessions",
        lambda b: b.list_sessions(OWNER_ID, limit=12, cursor=("2026-01-01T00:00:00Z", SESSION_ID)),
        "chat_list_sessions",
        {
            "p_owner_id": OWNER_ID,
            "p_limit": 12,
            "p_cursor_updated_at": "2026-01-01T00:00:00Z",
            "p_cursor_id": SESSION_ID,
        },
    ),
    (
        "rename_session",
        lambda b: b.rename_session(OWNER_ID, SESSION_ID, _TITLE),
        "chat_rename_session",
        {"p_owner_id": OWNER_ID, "p_session_id": SESSION_ID, "p_title": clamp_title(_TITLE)},
    ),
    (
        "delete_session",
        lambda b: b.delete_session(OWNER_ID, SESSION_ID),
        "chat_delete_session",
        {"p_owner_id": OWNER_ID, "p_session_id": SESSION_ID},
    ),
    (
        "delete_all_sessions",
        lambda b: b.delete_all_sessions(OWNER_ID),
        "chat_delete_all_sessions",
        {"p_owner_id": OWNER_ID},
    ),
]


@pytest.mark.parametrize(
    ("invoke", "name", "args"),
    [pytest.param(invoke, name, args, id=case_id) for case_id, invoke, name, args in CHAT_CALLS],
)
def test_chat_calls_send_exactly_these_arguments(invoke, name, args):
    client = RecordingClient()
    invoke(SupabaseChatBackend(client))
    assert _only_call(client) == (name, args)
