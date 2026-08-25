"""The Notification Center in a real browser: reader push shapes, the inbox,
and the admin composer + history.

docs/notification-center-plan.md §8: scoped to REST and to the Realtime
*wiring* only, matching `browser_page`'s own mocking philosophy
(`test_admin_browser.py` mocks every `/admin/api/*` response rather than
exercising the live server, precisely so one browser test's state cannot
leak into the next via the session-scoped in-memory backend). Private-channel
AUTHORIZATION is not, and cannot be, covered here — `conftest.py`'s Supabase
double's `channel()` is a structural stub with no real RLS behind it, so it
can prove "a message triggers a refetch" but never "reader A is denied
reader B's topic". That property is proven server-side: directly against the
live project's RLS policy (see docs/notification-center-plan.md's own
"verified directly" note) and via
web/tests/test_notifications_api.py's targeting-isolation tests, which cover
the same recipient-eligibility logic the REST path and the Realtime
recipient list both share.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


ADMIN_IDENTITY = {
    "user_id": "test-admin-id",
    "email": "admin@example.com",
    "role": "admin",
    "tier": "internal",
    "is_admin": True,
}


def _sign_in(page: Page, email: str = "test@example.com") -> None:
    page.goto("/")
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill(email)
    page.locator("#login-password").fill("password123")
    page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#authenticated-view").wait_for(state="visible")


def _notification(**overrides):
    row = {
        "id": "11111111-1111-4111-8111-111111111111",
        "type": "toast",
        "severity": "info",
        "title": "Scheduled maintenance",
        "body": "The service will be briefly unavailable tonight.",
        "requires_ack": False,
        "created_at": "2026-08-23T20:00:00+00:00",
        "expires_at": None,
        "deactivated_at": None,
        "read_at": None,
        "dismissed_at": None,
        "acknowledged_at": None,
    }
    row.update(overrides)
    return row


def _route_active(page: Page, notifications) -> None:
    page.context.route(
        "**/api/notifications/active*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"notifications": notifications}),
        ),
    )


def _route_history(page: Page, notifications, next_cursor=None) -> None:
    page.context.route(
        "**/api/notifications/history*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"notifications": notifications, "next_cursor": next_cursor}),
        ),
    )


def _route_mark_read(page: Page, calls: list) -> None:
    def handle(route):
        calls.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True}),
        )

    page.context.route("**/api/notifications/mark-read", handle)


# ── Realtime wiring (not authorization — see this module's own docstring) ──


def test_a_realtime_broadcast_triggers_an_immediate_refetch(browser_page: Page):
    """Proves Services.notifications.subscribe's onMessage wiring, not the
    private-channel RLS boundary: the mock's channel() is a structural stub
    with no real authorization behind it (conftest.py's own comment on
    SUPABASE_BROWSER_MOCK.channel), so this only shows that a message
    arriving through it causes handlers.js to call /api/notifications/active
    again rather than waiting for the 45s poll tick — the actual "does
    reader A get reader B's messages" question is answered server-side.
    """
    active_calls = {"count": 0}
    served = [[]]  # mutable so the route can be updated mid-test

    def handle_active(route):
        active_calls["count"] += 1
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"notifications": served[0]}),
        )

    browser_page.context.route("**/api/notifications/active*", handle_active)

    _sign_in(browser_page)
    expect(browser_page.locator(".broadcast-toast")).to_have_count(0)
    first_count = active_calls["count"]
    assert first_count >= 1  # the initial poll tick + the SUBSCRIBED reconcile

    # A notification now exists server-side; simulate the push that tells
    # this tab to stop waiting for its next poll tick.
    served[0] = [_notification(id="z", title="Pushed notice")]
    browser_page.evaluate(
        "window.__supabaseState.notificationChannelBroadcastCallback"
        "({ payload: { notification_id: 'z', revision: '1' } })"
    )

    toast = browser_page.locator(".broadcast-toast")
    expect(toast).to_be_visible()
    expect(toast).to_contain_text("Pushed notice")
    assert active_calls["count"] > first_count


# ── Reader: toast ────────────────────────────────────────────────────────────


def test_an_active_toast_renders_and_dismiss_marks_it_read(browser_page: Page):
    _route_active(browser_page, [_notification()])
    calls: list = []
    _route_mark_read(browser_page, calls)

    _sign_in(browser_page)

    toast = browser_page.locator(".broadcast-toast")
    expect(toast).to_be_visible()
    expect(toast).to_contain_text("Scheduled maintenance")

    browser_page.locator(".broadcast-toast-dismiss").click()
    expect(toast).to_have_count(0)

    assert calls and calls[0]["action"] == "dismissed"
    assert calls[0]["notification_id"] == "11111111-1111-4111-8111-111111111111"


def test_the_bell_badge_reflects_unread_active_notifications(browser_page: Page):
    _route_active(
        browser_page,
        [
            _notification(id="a", type="toast"),
            _notification(id="b", type="banner"),
        ],
    )
    _sign_in(browser_page)

    badge = browser_page.locator("#notifications-unread-badge")
    expect(badge).to_have_text("2")
    expect(badge).to_be_visible()


# ── Reader: banner ───────────────────────────────────────────────────────────


def test_a_banner_notification_opens_without_stealing_focus(browser_page: Page):
    _route_active(browser_page, [_notification(id="c", type="banner", severity="warning")])
    _sign_in(browser_page)

    banner = browser_page.locator("#notifications-banner")
    expect(banner).to_have_class("broadcast-banner severity-warning is-open")
    # Focus never left the page's own input on arrival — the plan's own rule
    # that forced focus is reserved for the acknowledgement modal alone.
    expect(browser_page.locator("#query-input")).not_to_be_focused()


# ── Reader: acknowledgement modal ───────────────────────────────────────────


def test_a_modal_notification_opens_and_acknowledge_marks_it(browser_page: Page):
    _route_active(
        browser_page,
        [_notification(id="d", type="modal", requires_ack=True, severity="danger")],
    )
    calls: list = []
    _route_mark_read(browser_page, calls)

    _sign_in(browser_page)

    modal = browser_page.locator("#notifications-modal")
    expect(modal).to_be_visible()
    expect(modal.locator(".broadcast-modal-title")).to_contain_text("Scheduled maintenance")
    # Bootstrap's own fade-in transition (~300ms) must finish before hide()
    # is honoured — see dom.js's showModal, which now retries past this same
    # window, matching handlers.js's identical, pre-existing hideModal fix.
    browser_page.wait_for_timeout(400)

    # The mark-read POST fires from inside Bootstrap's hidden.bs.modal
    # handler — after the hide transition, not before — so it can still be
    # in flight the instant Playwright observes the element itself as
    # hidden. Wait for the request explicitly rather than racing it.
    with browser_page.expect_request("**/api/notifications/mark-read"):
        modal.locator(".broadcast-modal-acknowledge").click()
    expect(modal).to_be_hidden()

    assert calls and calls[0]["action"] == "acknowledged"


def test_escape_snoozes_the_modal_without_acknowledging(browser_page: Page):
    _route_active(browser_page, [_notification(id="e", type="modal", requires_ack=True)])
    calls: list = []
    _route_mark_read(browser_page, calls)

    _sign_in(browser_page)

    modal = browser_page.locator("#notifications-modal")
    expect(modal).to_be_visible()
    browser_page.wait_for_timeout(400)

    browser_page.keyboard.press("Escape")
    expect(modal).to_be_hidden()

    # Snoozed client-side only — never recorded as an acknowledgement.
    assert calls == []


# ── Reader: inbox ────────────────────────────────────────────────────────────


def test_opening_the_inbox_lists_history_and_marks_a_row_read(browser_page: Page):
    _route_active(browser_page, [])
    _route_history(
        browser_page,
        [
            _notification(id="f", title="First notice"),
            _notification(id="g", title="Second notice", read_at="2026-08-23T19:00:00+00:00"),
        ],
    )
    calls: list = []
    _route_mark_read(browser_page, calls)

    _sign_in(browser_page)

    browser_page.locator("#notifications-bell-button").click()
    inbox = browser_page.locator("#notifications-inbox-modal")
    expect(inbox).to_be_visible()

    rows = browser_page.locator(".notifications-inbox-item")
    expect(rows).to_have_count(2)
    expect(rows.first).to_contain_text("First notice")
    # The unread row carries the accent class; the already-read one does not.
    expect(rows.first).to_have_class("notifications-inbox-item severity-info is-unread")

    rows.first.click()
    assert calls and calls[0] == {"notification_id": "f", "action": "read"}


# ── Admin: composer + history ───────────────────────────────────────────────


def _route_identity(page: Page, *, status: int = 200, body: dict = ADMIN_IDENTITY) -> None:
    page.route(
        "**/admin/api/identity",
        lambda route: route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(body),
        ),
    )


def test_composer_submit_adds_a_row_to_the_history_table(browser_page: Page):
    _route_identity(browser_page)

    # Mutated by handle_create below and read fresh by every history fetch —
    # the composer reloads history after a successful send, and the row it
    # expects to see is the one that send actually produced.
    history_rows: list = []

    browser_page.route(
        "**/admin/api/notifications/history*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "notifications": history_rows,
                    "total": len(history_rows),
                    "limit": 20,
                    "offset": 0,
                }
            ),
        ),
    )

    sent = {}

    def handle_create(route):
        sent.update(json.loads(route.request.post_data))
        row = {
            "id": "aaaaaaaa-1111-4111-8111-111111111111",
            "type": sent["type"],
            "severity": sent["severity"],
            "target_kind": "all",
            "target_role": None,
            "target_tier": None,
            "target_count": 3,
            "served_count": 0,
            "read_count": 0,
            "dismissed_count": 0,
            "acknowledged_count": 0,
            "deactivated_at": None,
            "deleted_at": None,
        }
        history_rows.append(row)
        route.fulfill(
            status=201,
            content_type="application/json",
            body=json.dumps({"notification": row}),
        )

    browser_page.route("**/admin/api/notifications", handle_create)

    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()

    browser_page.locator("#tab-notifications").click()
    expect(browser_page.locator("#panel-notifications")).to_be_visible()

    browser_page.locator("#notif-title-en").fill("Maintenance window")
    browser_page.locator("#notif-title-ar").fill("نافذة صيانة")
    browser_page.locator("#notif-body-en").fill("Briefly unavailable tonight.")
    browser_page.locator("#notif-body-ar").fill("غير متاح لفترة وجيزة الليلة.")

    browser_page.locator("#notification-composer-form button[type=submit]").click()

    expect(browser_page.locator("#notification-history-table")).to_be_visible()
    expect(browser_page.locator("#notification-history-table")).to_contain_text("toast")

    assert sent["title_en"] == "Maintenance window"
    assert sent["target_kind"] == "all"
    assert "client_request_id" in sent


def test_history_status_filter_hides_deleted_notifications_by_default(browser_page: Page):
    """Regression test for the reported bug: a soft-deleted notification used
    to stay in this table forever because loadHistory() hardcoded status:'all'
    with no filter control. The Active default now hides it; "All" still
    reaches it.

    Unlike test_composer_submit_adds_a_row_to_the_history_table's mock, this
    one has to actually honor `status` — a prior version of this test's mock
    ignored it entirely, which would have let the bug through undetected.
    """
    _route_identity(browser_page)

    notif_id = "aaaaaaaa-1111-4111-8111-111111111111"
    history_rows = [
        {
            "id": notif_id,
            "type": "toast",
            "severity": "info",
            "target_kind": "all",
            "target_role": None,
            "target_tier": None,
            "target_count": 3,
            "served_count": 1,
            "read_count": 1,
            "dismissed_count": 0,
            "acknowledged_count": 0,
            "deactivated_at": None,
            "deleted_at": None,
        }
    ]

    def handle_history(route):
        status = parse_qs(urlparse(route.request.url).query).get("status", ["all"])[0]
        if status == "deleted":
            rows = [r for r in history_rows if r["deleted_at"]]
        elif status == "deactivated":
            rows = [r for r in history_rows if r["deactivated_at"] and not r["deleted_at"]]
        elif status == "active":
            rows = [r for r in history_rows if not r["deactivated_at"] and not r["deleted_at"]]
        else:
            rows = list(history_rows)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"notifications": rows, "total": len(rows), "limit": 20, "offset": 0}),
        )

    browser_page.route("**/admin/api/notifications/history*", handle_history)

    def handle_delete(route):
        history_rows[0]["deleted_at"] = "2026-08-24T00:00:00+00:00"
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))

    browser_page.route(f"**/admin/api/notifications/{notif_id}", handle_delete)

    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-notifications").click()
    expect(browser_page.locator("#panel-notifications")).to_be_visible()

    expect(browser_page.locator("#notification-history-status")).to_have_value("active")
    expect(browser_page.locator("#notification-history-table")).to_contain_text("toast")

    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.locator("[data-notif-delete]").click()
    expect(browser_page.locator("#toast")).to_contain_text("deleted", ignore_case=True)

    # The default (Active) filter now hides it — this is the bug's fix.
    expect(browser_page.locator("#notification-history-table")).to_have_count(0)
    expect(browser_page.locator("#notification-history-body .admin-empty")).to_be_visible()

    # "All" still reaches it, dimmed and marked Deleted.
    browser_page.locator("#notification-history-status").select_option("all")
    expect(browser_page.locator("#notification-history-table")).to_contain_text("toast")
    expect(browser_page.locator("tr.admin-notif-row--deleted")).to_have_count(1)


def test_the_notification_history_filter_is_translated(browser_page: Page):
    _route_identity(browser_page)
    browser_page.route(
        "**/admin/api/notifications/history*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"notifications": [], "total": 0, "limit": 20, "offset": 0}),
        ),
    )

    browser_page.goto("/admin?lang=ar&testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-notifications").click()
    expect(browser_page.locator("#panel-notifications")).to_be_visible()

    expect(browser_page.locator('label[for="notification-history-status"]')).to_have_text("الحالة")
    expect(
        browser_page.locator("#notification-history-status option", has_text="الكل")
    ).to_have_count(1)
    expect(browser_page.locator("#notification-history-body .admin-empty")).to_have_text(
        "لا توجد إشعارات نشطة."
    )


def _bulk_row(index: int, *, deleted: bool = False) -> dict:
    return {
        "id": f"{index:08d}-1111-4111-8111-111111111111",
        "type": "toast",
        "severity": "info",
        "target_kind": "all",
        "target_role": None,
        "target_tier": None,
        "target_count": 1,
        "served_count": 0,
        "read_count": 0,
        "dismissed_count": 0,
        "acknowledged_count": 0,
        "deactivated_at": None,
        "deleted_at": "2026-08-24T00:00:00+00:00" if deleted else None,
    }


def _route_bulk_history(page: Page, rows: list) -> list:
    """Wires a status-and-pagination-aware history mock plus a DELETE mock
    that flips `deleted_at` in place. Returns the list of every DELETE
    request's target id, in call order, for assertions."""
    deleted_ids: list = []

    def handle_history(route):
        params = parse_qs(urlparse(route.request.url).query)
        status = params.get("status", ["all"])[0]
        limit = int(params.get("limit", ["20"])[0])
        offset = int(params.get("offset", ["0"])[0])
        if status == "deleted":
            matching = [r for r in rows if r["deleted_at"]]
        elif status == "active":
            matching = [r for r in rows if not r["deactivated_at"] and not r["deleted_at"]]
        else:
            matching = list(rows)
        page_rows = matching[offset : offset + limit]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "notifications": page_rows,
                    "total": len(matching),
                    "limit": limit,
                    "offset": offset,
                }
            ),
        )

    page.route("**/admin/api/notifications/history*", handle_history)

    def handle_delete(route):
        # "**/admin/api/notifications/*" also structurally matches
        # ".../notifications/history" (one path segment). Routes registered
        # later win when patterns overlap, so this one — registered after
        # the history route above — must fall back to it for anything that
        # isn't actually a DELETE, or it would swallow the history GETs too.
        if route.request.method != "DELETE":
            route.fallback()
            return
        notif_id = route.request.url.rsplit("/", 1)[-1]
        deleted_ids.append(notif_id)
        for row in rows:
            if row["id"] == notif_id:
                row["deleted_at"] = "2026-08-24T00:00:00+00:00"
                break
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))

    page.route("**/admin/api/notifications/*", handle_delete)
    return deleted_ids


def test_clearing_selected_notifications_deletes_only_those_checked(browser_page: Page):
    _route_identity(browser_page)
    rows = [_bulk_row(1), _bulk_row(2), _bulk_row(3)]
    deleted_ids = _route_bulk_history(browser_page, rows)

    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-notifications").click()
    expect(browser_page.locator("#notification-history-table")).to_be_visible()

    browser_page.locator(f'[data-notif-select="{rows[0]["id"]}"]').check()
    browser_page.locator(f'[data-notif-select="{rows[1]["id"]}"]').check()

    toolbar = browser_page.locator("#notification-history-bulk-toolbar")
    expect(toolbar).to_be_visible()
    expect(browser_page.locator("#notification-history-bulk-count")).to_have_text("2 selected")

    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.locator("#notification-history-clear-selected").click()

    expect(browser_page.locator("#toast")).to_contain_text("2 notifications deleted")
    expect(toolbar).to_be_hidden()

    # Only the two checked ids were sent to the delete endpoint — the third,
    # unchecked row was never touched.
    expect(browser_page.locator("#notification-history-table tbody tr")).to_have_count(1)
    assert sorted(deleted_ids) == sorted([rows[0]["id"], rows[1]["id"]])


def test_clearing_selected_excludes_an_already_deleted_row_from_a_mixed_selection(
    browser_page: Page,
):
    """Regression test: "Clear selected" used to send every checked id to
    deleteNotification with no filtering at all, so checking one active row
    and one already-Deleted row together (reachable from the "All" filter,
    where every row — deleted or not — now has a checkbox) would try to
    delete the already-deleted row too, drawing a needless partial-failure
    toast. It must only ever act on the non-deleted rows in the selection.
    """
    _route_identity(browser_page)
    active_row = _bulk_row(1)
    deleted_row = _bulk_row(2, deleted=True)
    rows = [active_row, deleted_row]
    deleted_ids = _route_bulk_history(browser_page, rows)

    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-notifications").click()

    browser_page.locator("#notification-history-status").select_option("all")
    expect(browser_page.locator("#notification-history-table tbody tr")).to_have_count(2)

    browser_page.locator(f'[data-notif-select="{active_row["id"]}"]').check()
    browser_page.locator(f'[data-notif-select="{deleted_row["id"]}"]').check()
    expect(browser_page.locator("#notification-history-bulk-count")).to_have_text("2 selected")

    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.locator("#notification-history-clear-selected").click()

    expect(browser_page.locator("#toast")).to_contain_text("1 notifications deleted")
    # Only the active row was ever sent to the delete endpoint.
    assert deleted_ids == [active_row["id"]]


def test_clear_all_pages_through_every_row_in_the_filter_not_just_one_page(browser_page: Page):
    """Regression guard for fetchAllIdsForClear's pagination loop: the history
    endpoint caps `limit` at 200 server-side, so "Clear all" has to keep
    paging until a short page proves there's nothing left. 201 rows — one
    more than a single page — is the minimum size that actually exercises
    the loop; a test with <=200 rows would pass even if the loop stopped
    after the first page.
    """
    _route_identity(browser_page)
    rows = [_bulk_row(i) for i in range(201)]
    deleted_ids = _route_bulk_history(browser_page, rows)

    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-notifications").click()
    expect(browser_page.locator("#notification-history-table")).to_be_visible()

    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.locator("#notification-history-clear-all").click()

    expect(browser_page.locator("#notification-history-body .admin-empty")).to_be_visible(
        timeout=15000
    )
    assert len(deleted_ids) == 201
    assert set(deleted_ids) == {row["id"] for row in rows}


def test_audience_preview_updates_when_targeting_changes_to_role(browser_page: Page):
    _route_identity(browser_page)
    browser_page.route(
        "**/admin/api/notifications/history*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"notifications": [], "total": 0, "limit": 20, "offset": 0}),
        ),
    )
    browser_page.route(
        "**/admin/api/notifications/audience-preview",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"target_count": 7}),
        ),
    )

    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-notifications").click()

    browser_page.locator("#notif-target-kind").select_option("role")
    expect(browser_page.locator("#notif-target-role-row")).to_be_visible()

    expect(browser_page.locator("#notif-audience-preview")).to_contain_text("7")


# ── Purge ────────────────────────────────────────────────────────────────────


def _route_purge(page: Page, rows: list, *, retention_days: int = 90) -> dict:
    """History (status-aware), an in-memory purge-settings GET/PUT, and a
    purge POST that actually removes the row from `rows` — unlike delete,
    which only flips `deleted_at`. Returns a mutable dict the test can
    inspect (`retention_days`, `purged_ids`)."""
    state = {"retention_days": retention_days, "purged_ids": []}

    def handle_history(route):
        status = parse_qs(urlparse(route.request.url).query).get("status", ["all"])[0]
        if status == "deleted":
            matching = [r for r in rows if r["deleted_at"]]
        elif status == "active":
            matching = [r for r in rows if not r["deactivated_at"] and not r["deleted_at"]]
        else:
            matching = list(rows)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"notifications": matching, "total": len(matching), "limit": 200, "offset": 0}
            ),
        )

    page.route("**/admin/api/notifications/history*", handle_history)

    def handle_purge_settings(route):
        if route.request.method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"purge_retention_days": state["retention_days"]}),
            )
            return
        body = json.loads(route.request.post_data or "{}")
        state["retention_days"] = body.get("purge_retention_days", state["retention_days"])
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"purge_retention_days": state["retention_days"]}),
        )

    page.route("**/admin/api/notifications/purge-settings", handle_purge_settings)

    def handle_purge(route):
        notif_id = route.request.url.split("/notifications/")[1].split("/purge")[0]
        rows[:] = [r for r in rows if r["id"] != notif_id]
        state["purged_ids"].append(notif_id)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"id": notif_id, "purged": True}),
        )

    page.route("**/admin/api/notifications/*/purge", handle_purge)

    return state


def test_purge_button_only_appears_on_deleted_rows_and_erases_them(browser_page: Page):
    _route_identity(browser_page)
    active_row = _bulk_row(1, deleted=False)
    deleted_row = _bulk_row(2, deleted=True)
    deleted_id = deleted_row["id"]
    rows = [active_row, deleted_row]
    state = _route_purge(browser_page, rows)

    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-notifications").click()

    browser_page.locator("#notification-history-status").select_option("all")
    expect(browser_page.locator("#notification-history-table tbody tr")).to_have_count(2)

    # Purge is offered only on the already-Deleted row.
    expect(browser_page.locator(f'[data-notif-purge="{deleted_id}"]')).to_have_count(1)
    expect(browser_page.locator(f'[data-notif-purge="{active_row["id"]}"]')).to_have_count(0)

    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.locator(f'[data-notif-purge="{deleted_id}"]').click()

    expect(browser_page.locator("#toast")).to_contain_text("purge", ignore_case=True)
    # Gone even under "All" — this is what distinguishes purge from delete.
    expect(browser_page.locator("#notification-history-table tbody tr")).to_have_count(1)
    assert state["purged_ids"] == [deleted_id]


def test_purge_eligible_only_purges_rows_past_the_retention_window(browser_page: Page):
    """The strict "<" comparison itself (found in review: the original code
    used "<=", which would purge a row deleted exactly on the retention
    boundary despite the confirm dialog promising "more than {days} days")
    is verified by reading handlers.js directly rather than by a timed
    browser assertion — real network/page-load jitter between this
    timestamp being computed here and the browser's own Date.now() at click
    time makes an exact-boundary row an inherently flaky thing to assert on
    in an end-to-end test. This test instead proves the general direction
    with a wide margin on both sides.
    """
    now = datetime.now(timezone.utc)
    old_row = _bulk_row(1, deleted=True)
    old_row["deleted_at"] = (now - timedelta(days=100)).isoformat()
    recent_row = _bulk_row(2, deleted=True)
    recent_row["deleted_at"] = (now - timedelta(days=10)).isoformat()
    old_id = old_row["id"]
    rows = [old_row, recent_row]

    _route_identity(browser_page)
    state = _route_purge(browser_page, rows, retention_days=90)

    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-notifications").click()

    browser_page.locator("#notification-history-status").select_option("deleted")
    expect(browser_page.locator("#notification-history-table tbody tr")).to_have_count(2)
    expect(browser_page.locator("#notification-purge-retention-days")).to_have_value("90")

    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.locator("#notification-purge-eligible").click()

    # Only the row deleted 100 days ago clears a 90-day window; the one
    # deleted 10 days ago must survive.
    expect(browser_page.locator("#notification-history-table tbody tr")).to_have_count(1)
    assert state["purged_ids"] == [old_id]


def test_purge_retention_days_can_be_saved(browser_page: Page):
    _route_identity(browser_page)
    state = _route_purge(browser_page, [], retention_days=90)

    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-notifications").click()
    browser_page.locator("#notification-history-status").select_option("deleted")

    expect(browser_page.locator("#notification-purge-retention-days")).to_have_value("90")
    browser_page.locator("#notification-purge-retention-days").fill("45")
    browser_page.locator("#notification-purge-retention-save").click()

    expect(browser_page.locator("#toast")).to_contain_text("saved", ignore_case=True)
    assert state["retention_days"] == 45
