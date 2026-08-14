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
