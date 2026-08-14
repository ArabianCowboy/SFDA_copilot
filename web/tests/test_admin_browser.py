"""The console in a browser: what it shows before the server has answered.

The shell is served to anyone, so the whole safety argument rests on the
console staying hidden until `/admin/api/identity` succeeds. These tests drive
that ordering from the outside, which is the only place it is observable.

Marked here with `pytestmark` rather than by adding a filename to the tuple in
conftest's `pytest_collection_modifyitems`. That tuple works, but it means a new
browser file is only recognised if someone remembers to edit a list in another
file — and the failure mode is CI's backend job trying to run Playwright.
"""

from __future__ import annotations

import json
import re

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


def _route_identity(page: Page, *, status: int, body: dict) -> None:
    page.route(
        "**/admin/api/identity",
        lambda route: route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(body),
        ),
    )


def test_the_console_stays_hidden_without_a_session(browser_page: Page):
    """No token, no console. The gate explains; nothing else renders."""
    browser_page.goto("/admin")

    expect(browser_page.locator("#admin-console")).to_be_hidden()
    expect(browser_page.locator("#admin-gate")).to_be_visible()


def test_a_refused_reader_is_told_plainly_and_shown_nothing(browser_page: Page):
    """403 is not a fault. The reader did nothing wrong, so it reads as a
    statement in place rather than an error toast."""
    _route_identity(browser_page, status=403, body={"error": "forbidden"})
    browser_page.goto("/admin?testing=true")

    expect(browser_page.locator(".admin-gate-text")).to_have_text(
        "This console is for administrators."
    )
    expect(browser_page.locator("#admin-console")).to_be_hidden()
    expect(browser_page.locator("#toast")).to_have_class("toast-notification hidden")


def test_an_administrator_sees_the_console(browser_page: Page):
    _route_identity(browser_page, status=200, body=ADMIN_IDENTITY)
    browser_page.goto("/admin?testing=true")

    expect(browser_page.locator("#admin-console")).to_be_visible()
    expect(browser_page.locator("#admin-gate")).to_be_hidden()
    expect(browser_page.locator("#admin-whoami")).to_have_text("admin@example.com")


def test_the_tabs_switch_panels_and_carry_their_aria_state(browser_page: Page):
    _route_identity(browser_page, status=200, body=ADMIN_IDENTITY)
    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()

    expect(browser_page.locator("#panel-overview")).to_be_visible()
    expect(browser_page.locator("#panel-settings")).to_be_hidden()

    browser_page.locator("#tab-settings").click()

    expect(browser_page.locator("#panel-settings")).to_be_visible()
    expect(browser_page.locator("#panel-overview")).to_be_hidden()
    expect(browser_page.locator("#tab-settings")).to_have_attribute("aria-selected", "true")
    expect(browser_page.locator("#tab-overview")).to_have_attribute("aria-selected", "false")


def test_the_tablist_is_navigable_by_keyboard(browser_page: Page):
    """Arrow keys move and activate; only the selected tab is a tab stop."""
    _route_identity(browser_page, status=200, body=ADMIN_IDENTITY)
    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()

    browser_page.locator("#tab-overview").focus()
    browser_page.keyboard.press("ArrowRight")

    expect(browser_page.locator("#tab-settings")).to_be_focused()
    expect(browser_page.locator("#panel-settings")).to_be_visible()

    # Roving tabindex: the unselected tabs are removed from the tab order, so
    # Tab leaves the tablist rather than walking through it.
    expect(browser_page.locator("#tab-overview")).to_have_attribute("tabindex", "-1")
    expect(browser_page.locator("#tab-settings")).to_have_attribute("tabindex", "0")


def test_the_console_renders_in_arabic(browser_page: Page):
    _route_identity(browser_page, status=200, body=ADMIN_IDENTITY)
    browser_page.goto("/admin?lang=ar&testing=true")

    expect(browser_page.locator("html")).to_have_attribute("dir", "rtl")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    expect(browser_page.locator("#tab-overview")).to_contain_text("نظرة عامة")


def test_an_email_stays_left_to_right_inside_an_arabic_page(browser_page: Page):
    """Outer dir="rtl" is not enough for a machine identifier.

    Without an explicit dir the bidi algorithm reorders an address dropped into
    Arabic chrome, which turns a fact into a puzzle.
    """
    _route_identity(browser_page, status=200, body=ADMIN_IDENTITY)
    browser_page.goto("/admin?lang=ar&testing=true")

    expect(browser_page.locator("#admin-whoami")).to_have_attribute("dir", "ltr")


def test_the_console_has_exactly_one_theme_toggle(browser_page: Page):
    """The reader page asserts three; this document gets one."""
    browser_page.goto("/admin")
    expect(browser_page.locator(".theme-toggle-btn")).to_have_count(1)


# ── Settings ──────────────────────────────────────────────────────────────────

SETTINGS = {
    "settings": {
        "model": "gpt-4o-mini",
        "temperature": 0.1,
        "max_tokens": 16384,
        "max_context_results": 8,
    },
    "overrides": {"temperature": 0.1},
    "allowed_models": [
        {"id": "gpt-4o-mini", "label": "GPT-4o mini", "max_output_tokens": 16384},
        {"id": "gpt-4o", "label": "GPT-4o", "max_output_tokens": 16384},
    ],
}


def _admin_console(page: Page, *, settings=SETTINGS, lang: str = "") -> None:
    _route_identity(page, status=200, body=ADMIN_IDENTITY)
    page.route(
        "**/admin/api/settings",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(settings)
        ),
    )
    page.goto(f"/admin?testing=true{lang}")
    expect(page.locator("#admin-console")).to_be_visible()


def test_the_settings_form_renders_the_allowlist_and_current_values(browser_page: Page):
    _admin_console(browser_page)
    browser_page.locator("#tab-settings").click()

    expect(browser_page.locator("#setting-model")).to_have_value("gpt-4o-mini")
    expect(browser_page.locator("#setting-max_tokens")).to_have_value("16384")
    # Exactly the allowlist, so the console cannot offer what the server refuses.
    expect(browser_page.locator("#setting-model option")).to_have_count(2)


def test_a_changed_setting_is_marked_as_changed(browser_page: Page):
    """A value someone chose and a value that happens to equal the default look
    identical in the input, and revert differently."""
    _admin_console(browser_page)
    browser_page.locator("#tab-settings").click()

    rows = browser_page.locator(".admin-field")
    expect(rows.filter(has=browser_page.locator(".admin-field-origin.is-override"))).to_have_count(1)
    expect(
        browser_page.locator('.admin-field[data-field="temperature"] .admin-field-origin')
    ).to_have_text("Changed here")


def test_a_rejected_save_puts_the_message_beside_its_field(browser_page: Page):
    """Not a pile of prose at the top of the form."""
    _admin_console(browser_page)
    browser_page.locator("#tab-settings").click()

    browser_page.route(
        "**/admin/api/settings",
        lambda route: route.fulfill(
            status=422,
            content_type="application/json",
            body=json.dumps({
                "error": "validation_failed",
                "errors": [
                    {"field": "max_tokens", "code": "above_ceiling", "limit": 16384}
                ],
            }),
        ),
    )
    browser_page.locator("#settings-save").click()

    error = browser_page.locator("#error-max_tokens")
    expect(error).to_be_visible()
    expect(error).to_have_text("Too large. The most this allows is 16384.")
    expect(browser_page.locator('.admin-field[data-field="max_tokens"]')).to_have_class(
        re.compile(r"has-error")
    )


def test_the_settings_form_is_translated(browser_page: Page):
    _admin_console(browser_page, lang="&lang=ar")
    browser_page.locator("#tab-settings").click()

    expect(browser_page.locator('label[for="setting-model"]')).to_have_text("النموذج")
    # A number keeps its own direction inside an RTL page.
    expect(browser_page.locator("#setting-max_tokens")).to_have_attribute("dir", "ltr")


# ── Activity log ──────────────────────────────────────────────────────────────

AUDIT = {
    "entries": [
        {
            "id": 2, "occurred_at": "2026-08-14T03:20:00+00:00",
            "actor_email": "admin@example.com", "action": "settings.update",
            "target_type": "settings", "target_id": "app_settings",
            "before": {"model": "gpt-4o-mini"}, "after": {"model": "gpt-4o"},
            "request_ip": "127.0.0.1", "note": None,
        },
    ],
    "limit": 50, "offset": 0,
}


def _with_audit(page: Page, lang: str = "") -> None:
    page.route(
        "**/admin/api/audit*",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(AUDIT)
        ),
    )
    _admin_console(page, lang=lang)


def test_the_activity_log_renders_what_changed(browser_page: Page):
    _with_audit(browser_page)
    browser_page.locator("#tab-audit").click()

    expect(browser_page.locator("#audit-table")).to_be_visible()
    expect(browser_page.locator("#audit-table tbody tr")).to_have_count(1)
    expect(browser_page.locator("#audit-table")).to_contain_text("Changed settings")
    # The diff, not the whole document.
    expect(browser_page.locator("#audit-table")).to_contain_text("model: gpt-4o-mini → gpt-4o")


def test_an_empty_log_says_so_rather_than_rendering_an_empty_table(browser_page: Page):
    browser_page.route(
        "**/admin/api/audit*",
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"entries": [], "limit": 50, "offset": 0}),
        ),
    )
    _admin_console(browser_page)
    browser_page.locator("#tab-audit").click()

    expect(browser_page.locator("#panel-audit")).to_contain_text("No changes recorded yet.")
    expect(browser_page.locator("#audit-table")).to_have_count(0)


def test_machine_values_stay_left_to_right_in_arabic(browser_page: Page):
    """A timestamp, an email and a diff are machine-reported facts. Outer
    dir="rtl" would reorder the parts of a date and mangle an address."""
    _with_audit(browser_page, lang="&lang=ar")
    browser_page.locator("#tab-audit").click()

    expect(browser_page.locator("#audit-table")).to_be_visible()
    cells = browser_page.locator("#audit-table tbody td.admin-cell-machine")
    expect(cells).to_have_count(3)
    for index in range(3):
        expect(cells.nth(index)).to_have_attribute("dir", "ltr")


def test_the_activity_tab_is_reachable_by_keyboard(browser_page: Page):
    _with_audit(browser_page)
    browser_page.locator("#tab-overview").focus()
    for _ in range(3):
        browser_page.keyboard.press("ArrowRight")

    expect(browser_page.locator("#tab-audit")).to_be_focused()
    expect(browser_page.locator("#panel-audit")).to_be_visible()
