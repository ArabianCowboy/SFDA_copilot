"""Every mutating admin path refuses an actor who is not an enabled administrator.

The database enforces this in `public.admin_actor_email`, which the seven
mutating `admin_*` RPCs call before doing anything else. These tests pin the
same rule against the in-memory doubles, for one narrow and specific reason:
the doubles used to assert the OPPOSITE.

All four were written as some variation of "check the actor only if one was
supplied" —

    web/services/admin_store.py        if actor.user_id:            # then check
    web/services/admin_store.py        if actor.user_id:            # then check
    web/services/admin_store.py        (put_settings: no check at all)
    web/services/notification_store.py if not actor.user_id: return True

— faithfully mirroring the production functions, which guarded on
`if p_actor_id is not null then`. A null actor therefore performed the mutation
with no authorization check and wrote an audit row attributed to nobody, in the
table whose entire job is attribution. Now that the database refuses it, a
double that still accepts it is a green suite asserting something production
does not do.

What these tests do NOT prove: that Postgres raises AD004 or AN005. The doubles
never execute SQL, so they cannot. That belongs in the SQL suite under
`supabase/tests/`. The point here is narrower and still worth having — to stop
the doubles from drifting back to a behaviour the schema no longer has.
"""

from __future__ import annotations

import uuid

import pytest

from web.services.admin_store import AdminActionRefused, InMemoryAdminBackend
from web.services.audit import AuditActor
from web.services.notification_store import InMemoryNotificationBackend

# The four shapes the gate has to refuse. `None` and `""` are the absent case
# the old guards skipped; the other two are accounts that exist in some sense
# and are not entitled to act.
REFUSED_ACTORS = [
    pytest.param(AuditActor(None, None), id="no-actor-at-all"),
    pytest.param(AuditActor("", "nobody@example.com"), id="empty-actor-id"),
    pytest.param(AuditActor("someone-else", "ghost@example.com"), id="unknown-actor-id"),
    pytest.param(AuditActor("test-user-id", "test@example.com"), id="a-reader-not-an-admin"),
]

ADMIN = AuditActor("test-admin-id", "admin@example.com", "127.0.0.1", "pytest")


@pytest.fixture
def backend():
    return InMemoryAdminBackend()


@pytest.fixture
def notifications(backend):
    # A reference to the same seeded list, the sharing pattern the real
    # composer already uses — so a role change made through one is visible to
    # the other, exactly as it would be in one database.
    return InMemoryNotificationBackend(backend._users)


@pytest.mark.parametrize("actor", REFUSED_ACTORS)
def test_settings_cannot_be_written_without_an_enabled_administrator(backend, actor):
    with pytest.raises(AdminActionRefused) as refused:
        backend.put_settings({"model": "gpt-4o"}, actor=actor, before={}, after={})
    assert refused.value.code == "actor_no_longer_administrator"


@pytest.mark.parametrize("actor", REFUSED_ACTORS)
def test_a_profile_cannot_be_edited_without_an_enabled_administrator(backend, actor):
    with pytest.raises(AdminActionRefused) as refused:
        backend.update_profile(
            "test-user-id",
            first_name="Nadia",
            family_name="Al-Otaibi",
            age=34,
            organization=None,
            specialization=None,
            expected_updated_at=None,
            actor=actor,
        )
    assert refused.value.code == "actor_no_longer_administrator"


@pytest.mark.parametrize("actor", REFUSED_ACTORS)
def test_flags_cannot_be_changed_without_an_enabled_administrator(backend, actor):
    with pytest.raises(AdminActionRefused) as refused:
        backend.set_user_flags("test-disabled-id", role="admin", actor=actor)
    assert refused.value.code == "actor_no_longer_administrator"


@pytest.mark.parametrize("actor", REFUSED_ACTORS)
def test_a_notification_cannot_be_sent_without_an_enabled_administrator(notifications, actor):
    with pytest.raises(AdminActionRefused) as refused:
        notifications.create(
            type="toast",
            severity="info",
            title_en="t",
            title_ar="ت",
            body_en="b",
            body_ar="ب",
            target_kind="all",
            target_role=None,
            target_tier=None,
            target_user_id=None,
            expires_at=None,
            resend_of=None,
            client_request_id=str(uuid.uuid4()),
            actor=actor,
        )
    assert refused.value.code == "actor_no_longer_administrator"


def test_a_disabled_administrator_is_refused_too(backend):
    """The case the gate exists for, rather than the case it was written for.

    An absent actor is a programming mistake. An administrator disabled while
    their console tab was open is an operational event, and it is the one the
    revalidation actually catches.
    """
    backend.set_user_flags("test-user-id", role="admin", actor=ADMIN)
    backend.set_user_flags("test-user-id", is_disabled=True, actor=ADMIN)
    demoted = AuditActor("test-user-id", "test@example.com")

    with pytest.raises(AdminActionRefused) as refused:
        backend.put_settings({"model": "gpt-4o"}, actor=demoted, before={}, after={})
    assert refused.value.code == "actor_no_longer_administrator"


def test_an_enabled_administrator_is_still_allowed_through(backend, notifications):
    """The other half, or the tests above would pass against a gate that refuses
    everything."""
    assert backend.put_settings(
        {"model": "gpt-4o"}, actor=ADMIN, before={}, after={"model": "gpt-4o"}
    ) == {"model": "gpt-4o"}

    updated = backend.update_profile(
        "test-user-id",
        first_name="Nadia",
        family_name="Al-Otaibi",
        age=34,
        organization=None,
        specialization=None,
        expected_updated_at=None,
        actor=ADMIN,
    )
    assert updated["first_name"] == "Nadia"

    created = notifications.create(
        type="toast",
        severity="info",
        title_en="t",
        title_ar="ت",
        body_en="b",
        body_ar="ب",
        target_kind="all",
        target_role=None,
        target_tier=None,
        target_user_id=None,
        expires_at=None,
        resend_of=None,
        client_request_id=str(uuid.uuid4()),
        actor=ADMIN,
    )
    assert created["id"]
