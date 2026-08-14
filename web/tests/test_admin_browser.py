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


# ── Reasoning models change which controls exist ─────────────────────────────

REASONING_SETTINGS = {
    "settings": {
        "model": "gpt-4o-mini", "temperature": 0.1,
        "max_tokens": 16384, "max_context_results": 8, "reasoning_effort": None,
    },
    "overrides": {},
    "allowed_models": [
        {"id": "gpt-4o-mini", "label": "GPT-4o mini", "max_output_tokens": 16384},
        {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna", "max_output_tokens": 128000,
         "token_param": "max_completion_tokens", "supports_temperature": False,
         "reasoning_efforts": ["none", "low", "medium", "high", "xhigh", "max"]},
    ],
}


def test_choosing_a_reasoning_model_swaps_the_controls(browser_page: Page):
    """A reasoning model rejects temperature and accepts an effort level; an
    ordinary one is the reverse. Showing a control the server would refuse is an
    invitation to a 422 nobody could have predicted from the form."""
    _admin_console(browser_page, settings=REASONING_SETTINGS)
    browser_page.locator("#tab-settings").click()

    expect(browser_page.locator("#setting-temperature")).to_be_visible()
    expect(browser_page.locator("#setting-reasoning_effort")).to_have_count(0)

    browser_page.locator("#setting-model").select_option("gpt-5.6-luna")

    expect(browser_page.locator("#setting-reasoning_effort")).to_be_visible()
    expect(browser_page.locator("#setting-temperature")).to_have_count(0)


def test_the_effort_levels_come_from_the_selected_model(browser_page: Page):
    """Luna offers `none`; Nano's floor is `minimal`. A shared list would offer
    a value the server then refuses."""
    _admin_console(browser_page, settings=REASONING_SETTINGS)
    browser_page.locator("#tab-settings").click()
    browser_page.locator("#setting-model").select_option("gpt-5.6-luna")

    options = browser_page.locator("#setting-reasoning_effort option")
    # Six levels plus the "model default" entry.
    expect(options).to_have_count(7)
    expect(options.nth(0)).to_have_text("Model default")
    expect(options.nth(1)).to_have_text("none")


def test_model_default_is_offered_as_a_distinct_choice(browser_page: Page):
    """Sending nothing lets the model apply its own documented default, which is
    not the same as picking medium on its behalf."""
    _admin_console(browser_page, settings=REASONING_SETTINGS)
    browser_page.locator("#tab-settings").click()
    browser_page.locator("#setting-model").select_option("gpt-5.6-luna")

    expect(browser_page.locator("#setting-reasoning_effort")).to_have_value("")


# ── Reverting an override ─────────────────────────────────────────────────────

OVERRIDDEN = {
    "settings": {"model": "gpt-4o", "temperature": 0.9, "max_tokens": 16384,
                 "max_context_results": 8, "reasoning_effort": None},
    "overrides": {"temperature": 0.9},
    "defaults": {"model": "gpt-4o-mini", "temperature": 0.1, "max_tokens": 16384,
                 "max_context_results": 8, "reasoning_effort": None},
    "allowed_models": [
        {"id": "gpt-4o-mini", "label": "GPT-4o mini", "max_output_tokens": 16384},
        {"id": "gpt-4o", "label": "GPT-4o", "max_output_tokens": 16384},
    ],
}


def test_only_an_overridden_field_offers_reversion(browser_page: Page):
    """A revert control on a field already inheriting the default would be a
    control that does nothing."""
    _admin_console(browser_page, settings=OVERRIDDEN)
    browser_page.locator("#tab-settings").click()

    expect(browser_page.locator(".admin-field-revert")).to_have_count(1)
    expect(
        browser_page.locator('.admin-field[data-field="temperature"] .admin-field-revert')
    ).to_be_visible()


def test_reverting_is_staged_rather_than_written_immediately(browser_page: Page):
    """The form submits whole. An immediate per-key write would discard whatever
    else was being edited — so the input shows what it will become, and Save
    sends it."""
    _admin_console(browser_page, settings=OVERRIDDEN)
    browser_page.locator("#tab-settings").click()

    browser_page.locator('.admin-field[data-field="temperature"] .admin-field-revert').click()

    # Shows the value it will revert TO, and stops claiming to be a choice.
    expect(browser_page.locator("#setting-temperature")).to_have_value("0.1")
    expect(
        browser_page.locator('.admin-field[data-field="temperature"] .admin-field-origin')
    ).to_have_text("Deployed default")
    # The control is gone: there is nothing left to revert.
    expect(browser_page.locator(".admin-field-revert")).to_have_count(0)


def test_a_staged_revert_is_sent_as_null(browser_page: Page):
    """null removes the override. Writing the default's current value instead
    would pin it against a future deploy — the distinction the whole
    overrides-only design exists to preserve."""
    sent = []
    _admin_console(browser_page, settings=OVERRIDDEN)
    browser_page.locator("#tab-settings").click()

    def capture(route):
        if route.request.method == "PUT":
            sent.append(route.request.post_data_json)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({**OVERRIDDEN, "overrides": {}, "applied": True}))
        else:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(OVERRIDDEN))

    browser_page.route("**/admin/api/settings", capture)
    browser_page.locator('.admin-field[data-field="temperature"] .admin-field-revert').click()
    browser_page.locator("#settings-save").click()

    expect(browser_page.locator("#settings-save")).to_be_enabled()
    assert sent and sent[0]["temperature"] is None


# ── Account detail ────────────────────────────────────────────────────────────


# Mirrors the shapes InMemoryAdminBackend seeds. Stubbed rather than served,
# following this file's convention: `?testing=true` authenticates as a plain
# reader, so every console endpoint 403s unless the test fulfils it. The server
# side of these routes is covered by test_admin_users.py.
ACCOUNTS = [
    {"id": "test-admin-id", "email": "admin@example.com", "role": "admin",
     "tier": "internal", "is_disabled": False, "last_sign_in_at": None},
    {"id": "test-user-id", "email": "test@example.com", "role": "user",
     "tier": "free", "is_disabled": False, "last_sign_in_at": None},
    {"id": "test-disabled-id", "email": "disabled@example.com", "role": "user",
     "tier": "free", "is_disabled": True, "last_sign_in_at": None},
    {"id": "test-orphan-id", "email": "orphan@example.com", "role": "user",
     "tier": "free", "is_disabled": False, "last_sign_in_at": None},
]

DETAILS = {
    "test-user-id": {
        "id": "test-user-id", "email": "test@example.com", "has_profile": True,
        "role": "user", "tier": "free", "is_disabled": False,
        "created_at": "2026-02-01T00:00:00+00:00", "last_sign_in_at": None,
        "email_confirmed_at": "2026-02-01T00:00:00+00:00", "updated_at": None,
        "disabled_at": None, "disabled_by_email": None, "disabled_reason": None,
        "full_name": "Test User", "organization": "Test Organization",
        "specialization": "Regulatory Affairs", "last_seen_at": None,
    },
    "test-orphan-id": {
        "id": "test-orphan-id", "email": "orphan@example.com", "has_profile": False,
        "role": None, "tier": None, "is_disabled": None,
        "created_at": "2026-04-01T00:00:00+00:00", "last_sign_in_at": None,
        "email_confirmed_at": None, "updated_at": None,
        "disabled_at": None, "disabled_by_email": None, "disabled_reason": None,
        "full_name": None, "organization": None, "specialization": None,
        "last_seen_at": None,
    },
}


def _json(route, body):
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def _open_people(page: Page, *, lang: str = "") -> None:
    _route_identity(page, status=200, body=ADMIN_IDENTITY)

    def users_or_detail(route):
        url = route.request.url
        match = re.search(r"/admin/api/users/([^?]+)", url)
        if match:
            account = DETAILS.get(match.group(1))
            if account is None:
                route.fulfill(status=404, content_type="application/json",
                              body=json.dumps({"error": "no_such_account"}))
                return
            _json(route, {"user": account, "self_id": "test-admin-id"})
            return

        needle = (parse_qs(urlparse(url).query).get("q") or [""])[0].lower()
        rows = [a for a in ACCOUNTS if needle in a["email"].lower()]
        _json(route, {"users": rows, "total": len(rows), "limit": 50,
                      "offset": 0, "self_id": "test-admin-id"})

    page.route("**/admin/api/users*", users_or_detail)
    page.route("**/admin/api/users/*", users_or_detail)
    page.route("**/admin/api/audit*",
               lambda route: _json(route, {"entries": [], "limit": 50, "offset": 0}))

    page.goto(f"/admin?testing=true{lang}")
    page.locator("#tab-people").click()


def test_opening_an_account_swaps_the_people_panel(browser_page: Page):
    """An in-panel swap, not a fifth tab — so People stays selected and the
    tablist's roving tabindex is untouched."""
    _open_people(browser_page)
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    expect(browser_page.locator("#people-detail")).to_be_visible()
    expect(browser_page.locator("#people-list")).to_be_hidden()
    expect(browser_page.locator("#account-heading")).to_contain_text("test@example.com")
    # The tab it belongs to stays selected, so aria-selected stays honest.
    expect(browser_page.locator("#tab-people")).to_have_attribute("aria-selected", "true")


def test_going_back_returns_to_the_list_and_restores_focus(browser_page: Page):
    _open_people(browser_page)
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()
    browser_page.locator("#account-back").click()

    expect(browser_page.locator("#people-list")).to_be_visible()
    expect(browser_page.locator("#people-detail")).to_be_hidden()
    expect(browser_page.locator(".admin-account-open").first).to_be_focused()


def test_an_account_with_no_profile_is_shown_as_broken(browser_page: Page):
    """The state the People table cannot express at all: `admin_list_users`
    coalesces the missing columns, so there it reads as an ordinary reader."""
    _open_people(browser_page)
    browser_page.locator(".admin-account-open", has_text="orphan@example.com").click()

    expect(browser_page.locator("#account-broken")).to_be_visible()


def test_the_detail_keeps_machine_values_left_to_right_in_arabic(browser_page: Page):
    _open_people(browser_page, lang="&lang=ar")
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    expect(browser_page.locator("html")).to_have_attribute("dir", "rtl")
    expect(browser_page.locator("#account-heading .admin-cell-machine")).to_have_attribute("dir", "ltr")


def test_the_people_list_can_be_searched(browser_page: Page):
    """The detail view is reachable only from this list, and the list serves one
    page of 50 — the search box is what makes it reachable at all past that."""
    _open_people(browser_page)
    expect(browser_page.locator(".admin-account-open")).to_have_count(4)

    browser_page.locator("#people-search").fill("orphan")
    expect(browser_page.locator(".admin-account-open")).to_have_count(1)
    expect(browser_page.locator(".admin-account-open")).to_contain_text("orphan@example.com")


def test_an_activity_outage_is_not_shown_as_an_empty_history(browser_page: Page):
    """`null` is "we could not tell"; `[]` is "nothing happened".

    Collapsing them tells an operator an account has a clean record when the
    truth is that the log was unreachable — the same false absence the server
    answers with a 503 rather than an empty list.
    """
    _open_people(browser_page)
    # Added after the list route, so it wins: Playwright matches the most
    # recently registered handler first.
    browser_page.route("**/admin/api/audit*", lambda route: route.fulfill(status=503))
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    expect(browser_page.locator("#account-activity-failed")).to_be_visible()
    expect(browser_page.locator("#account-activity-empty")).to_have_count(0)
    # The account still loaded; a log outage must not take the page with it.
    expect(browser_page.locator("#account-heading")).to_contain_text("test@example.com")


def test_a_failed_account_load_says_so_instead_of_showing_nothing(browser_page: Page):
    """The failure message used to be written into a panel that was still
    hidden, because the swap only happened on a successful render."""
    _open_people(browser_page)
    browser_page.route("**/admin/api/users/*", lambda route: route.fulfill(status=503))
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    expect(browser_page.locator("#account-error")).to_be_visible()
    # And there is a way back out of the failure.
    expect(browser_page.locator("#account-back")).to_be_visible()


def test_a_pending_search_does_not_replace_an_open_account(browser_page: Page):
    """Type, then open a result inside the 300ms debounce: the queued list
    request used to resolve last and swap the detail back to the list."""
    _open_people(browser_page)
    browser_page.locator("#people-search").fill("test")
    # No wait — the debounce is still pending when this click lands.
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    expect(browser_page.locator("#account-heading")).to_contain_text("test@example.com")
    browser_page.wait_for_timeout(600)
    expect(browser_page.locator("#people-detail")).to_be_visible()
    expect(browser_page.locator("#people-list")).to_be_hidden()


# ── Account actions ───────────────────────────────────────────────────────────


def test_the_detail_says_a_password_can_never_be_set(browser_page: Page):
    """The design position on the surface, not only in a commit message.

    The support outcome people want from "set their password" is "get them back
    in", and a reset link delivers that without anyone learning a secret.
    """
    _open_people(browser_page)
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    expect(browser_page.locator("#account-no-password-hint")).to_be_visible()
    expect(browser_page.locator("#account-send-reset")).to_be_visible()


def test_the_detail_says_what_it_deliberately_cannot_do(browser_page: Page):
    """An operator mid-incident should not have to work out for themselves that
    the console cannot end a session — disabling chat does not sign anyone out."""
    _open_people(browser_page)
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    absent = browser_page.locator("#account-absent")
    expect(absent).to_be_visible()
    expect(absent).to_contain_text("session", ignore_case=True)


def test_sending_a_reset_asks_first_and_reports_the_outcome(browser_page: Page):
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/reset-password",
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"accepted": True, "operation_id": "op-1"})),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.locator("#account-send-reset").click()

    expect(browser_page.locator("#toast")).to_contain_text("accepted", ignore_case=True)


def test_a_rate_limited_reset_gets_its_own_sentence(browser_page: Page):
    """Distinct from the project-wide allowance: an operator who does not know a
    project ceiling exists will conclude the account is broken."""
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/reset-password",
        lambda route: route.fulfill(
            status=429, content_type="application/json",
            body=json.dumps({"error": "reset_quota_exhausted"})),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.locator("#account-send-reset").click()

    expect(browser_page.locator("#toast")).to_contain_text("allowance", ignore_case=True)


def test_declining_the_confirmation_sends_nothing(browser_page: Page):
    sent = []
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/reset-password",
        lambda route: (sent.append(1), route.fulfill(status=200, body="{}")),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    browser_page.once("dialog", lambda dialog: dialog.dismiss())
    browser_page.locator("#account-send-reset").click()
    browser_page.wait_for_timeout(300)

    assert not sent, "a dismissed confirmation still sent the reset"
