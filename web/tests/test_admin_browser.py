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

import contextlib
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
    "tier": "staff",
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


# The registrations block loads unconditionally alongside settings
# (docs/registrations-pause-plan.md §9 Step 12) — routed here by default so
# every existing `_admin_console`-based test keeps seeing a real answer
# instead of the load-failure toast this endpoint would otherwise produce on
# every admin page open.
REGISTRATIONS = {"signup_enabled": True, "default": True}


def _admin_console(
    page: Page, *, settings=SETTINGS, registrations=REGISTRATIONS, lang: str = ""
) -> None:
    _route_identity(page, status=200, body=ADMIN_IDENTITY)
    page.route(
        "**/admin/api/settings",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(settings)
        ),
    )
    # `registrations=None` opts out of this default route — a page-level
    # route takes priority over a context-level one regardless of add order,
    # so a caller that already installed its own stateful
    # `context.route("**/admin/api/registrations", ...)` needs this one
    # skipped, not merely overridden.
    if registrations is None:
        page.goto(f"/admin?testing=true{lang}")
        expect(page.locator("#admin-console")).to_be_visible()
        return
    page.route(
        "**/admin/api/registrations",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(registrations)
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
    expect(rows.filter(has=browser_page.locator(".admin-field-origin.is-override"))).to_have_count(
        1
    )
    expect(
        browser_page.locator('.admin-field[data-field="temperature"] .admin-field-origin')
    ).to_have_text("Changed here")


# ── Registrations ────────────────────────────────────────────────────────────


def test_an_operator_can_pause_and_resume_registrations(browser_page: Page):
    """docs/registrations-pause-plan.md §9 Step 12's own proof: click, expect
    the pill to flip, reload, expect it to persist."""
    state = {"signup_enabled": True, "default": True}

    def handle(route):
        if route.request.method == "PUT":
            state["signup_enabled"] = route.request.post_data_json["signup_enabled"]
        _json(route, state)

    browser_page.context.route("**/admin/api/registrations", handle)
    _admin_console(browser_page, registrations=None)
    browser_page.locator("#tab-settings").click()

    status = browser_page.locator("#registrations-state")
    toggle = browser_page.locator("#registrations-toggle")
    expect(status).to_have_text("Open")
    expect(toggle).to_have_text("Pause registrations")

    # Pausing is confirmed (this console's own asymmetry — see the i18n
    # comment beside admin.registrations.confirmPause); resuming, below, is
    # not, so only this click needs a dialog handler.
    browser_page.once("dialog", lambda dialog: dialog.accept())
    toggle.click()
    expect(status).to_have_text("Paused")
    expect(toggle).to_have_text("Resume registrations")
    expect(browser_page.locator("#toast")).to_contain_text("paused", ignore_case=True)

    # Persists — a reload reads the same server-side state back, not a
    # client-side flip that would vanish on refresh.
    browser_page.reload()
    browser_page.locator("#tab-settings").click()
    expect(browser_page.locator("#registrations-state")).to_have_text("Paused")

    browser_page.locator("#registrations-toggle").click()
    expect(browser_page.locator("#registrations-state")).to_have_text("Open")
    expect(browser_page.locator("#toast")).to_contain_text("resumed", ignore_case=True)


def test_a_failed_toggle_restores_the_button_rather_than_leaving_it_saving(browser_page: Page):
    browser_page.context.route(
        "**/admin/api/registrations",
        lambda route: (
            route.fulfill(status=503, content_type="application/json", body="{}")
            if route.request.method == "PUT"
            else _json(route, REGISTRATIONS)
        ),
    )
    _admin_console(browser_page, registrations=None)
    browser_page.locator("#tab-settings").click()
    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.locator("#registrations-toggle").click()

    expect(browser_page.locator("#toast")).to_contain_text("Could not save", ignore_case=True)
    toggle = browser_page.locator("#registrations-toggle")
    expect(toggle).to_be_enabled()
    expect(toggle).to_have_text("Pause registrations")


def test_a_rejected_save_puts_the_message_beside_its_field(browser_page: Page):
    """Not a pile of prose at the top of the form."""
    _admin_console(browser_page)
    browser_page.locator("#tab-settings").click()

    browser_page.route(
        "**/admin/api/settings",
        lambda route: route.fulfill(
            status=422,
            content_type="application/json",
            body=json.dumps(
                {
                    "error": "validation_failed",
                    "errors": [{"field": "max_tokens", "code": "above_ceiling", "limit": 16384}],
                }
            ),
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
            "id": 2,
            "occurred_at": "2026-08-14T03:20:00+00:00",
            "actor_email": "admin@example.com",
            "action": "settings.update",
            "target_type": "settings",
            "target_id": "app_settings",
            "before": {"model": "gpt-4o-mini"},
            "after": {"model": "gpt-4o"},
            "request_ip": "127.0.0.1",
            "note": None,
        },
    ],
    "limit": 50,
    "offset": 0,
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
            status=200,
            content_type="application/json",
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
    """Arrow-key travel from the first tab to Activity.

    The number of presses is DERIVED from the live tablist rather than hardcoded:
    it was `range(3)`, which silently became wrong the moment a sixth tab was
    inserted ahead of Activity. A test that has to be edited every time a tab is
    added is a test that will eventually be edited to whatever makes it pass.
    """
    _with_audit(browser_page)
    tab_ids = browser_page.eval_on_selector_all(".admin-tab", "els => els.map(el => el.id)")
    steps = tab_ids.index("tab-audit") - tab_ids.index("tab-overview")
    assert steps > 0, f"Activity should sit after Overview in the tablist: {tab_ids}"

    browser_page.locator("#tab-overview").focus()
    for _ in range(steps):
        browser_page.keyboard.press("ArrowRight")

    expect(browser_page.locator("#tab-audit")).to_be_focused()
    expect(browser_page.locator("#panel-audit")).to_be_visible()


# ── Reasoning models change which controls exist ─────────────────────────────

REASONING_SETTINGS = {
    "settings": {
        "model": "gpt-4o-mini",
        "temperature": 0.1,
        "max_tokens": 16384,
        "max_context_results": 8,
        "reasoning_effort": None,
    },
    "overrides": {},
    "allowed_models": [
        {"id": "gpt-4o-mini", "label": "GPT-4o mini", "max_output_tokens": 16384},
        {
            "id": "gpt-5.6-luna",
            "label": "GPT-5.6 Luna",
            "max_output_tokens": 128000,
            "token_param": "max_completion_tokens",
            "supports_temperature": False,
            "reasoning_efforts": ["none", "low", "medium", "high", "xhigh", "max"],
        },
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


# ── Switching AWAY from a reasoning model ────────────────────────────────────
#
# The instance this came from: a console showing Luna, a terminal showing
# gpt-4o-mini, and a Save button that did nothing and said nothing. Every save
# came back 422 `reasoning_effort: reasoning_not_supported`, because the stored
# override survived a switch to a model with no reasoning — and the refusal
# named a field the form had stopped drawing, so it was written to a DOM node
# that does not exist and dropped. The model could not be changed back from this
# console at all.

ON_A_REASONING_MODEL = {
    "settings": {
        "model": "gpt-5.6-luna",
        "temperature": 0.1,
        "max_tokens": 128000,
        "max_context_results": 8,
        "reasoning_effort": "xhigh",
    },
    "overrides": {
        "model": "gpt-5.6-luna",
        "temperature": 0.1,
        "max_tokens": 128000,
        "max_context_results": 8,
        "reasoning_effort": "xhigh",
    },
    "defaults": {
        "model": "gpt-4o-mini",
        "temperature": 0.1,
        "max_tokens": 16384,
        "max_context_results": 8,
        "reasoning_effort": None,
    },
    "allowed_models": REASONING_SETTINGS["allowed_models"],
}


def _capture_put(page: Page, settings: dict, *, response=None, status: int = 200):
    """Record the PUT body and answer it with `response`."""
    sent: list = []

    def handle(route):
        if route.request.method == "PUT":
            sent.append(route.request.post_data_json)
            route.fulfill(
                status=status,
                content_type="application/json",
                body=json.dumps(
                    response if response is not None else {**settings, "applied": True}
                ),
            )
        else:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(settings))

    page.route("**/admin/api/settings", handle)
    return sent


def test_leaving_a_reasoning_model_clears_the_effort_it_had(browser_page: Page):
    """Choosing a model without reasoning IS a decision about reasoning effort.

    Omitting the key left the old value in the stored document, the server
    validated the resulting pair and refused it, and the model could never be
    changed back. null is the honest patch: the override is removed.
    """
    _admin_console(browser_page, settings=ON_A_REASONING_MODEL)
    browser_page.locator("#tab-settings").click()
    sent = _capture_put(browser_page, ON_A_REASONING_MODEL)

    browser_page.locator("#setting-model").select_option("gpt-4o-mini")
    browser_page.locator("#setting-max_tokens").fill("16384")
    browser_page.locator("#settings-save").click()

    expect(browser_page.locator("#settings-save")).to_be_enabled()
    assert sent, "no PUT was sent"
    assert sent[0]["reasoning_effort"] is None
    assert sent[0]["model"] == "gpt-4o-mini"


def test_arriving_at_a_reasoning_model_clears_the_temperature_it_cannot_use(
    browser_page: Page,
):
    """The mirror image. Luna rejects `temperature` outright, so an override for
    it is a value nothing will ever read and no control will ever show."""
    _admin_console(browser_page, settings=REASONING_SETTINGS)
    browser_page.locator("#tab-settings").click()
    sent = _capture_put(browser_page, REASONING_SETTINGS)

    browser_page.locator("#setting-model").select_option("gpt-5.6-luna")
    browser_page.locator("#settings-save").click()

    expect(browser_page.locator("#settings-save")).to_be_enabled()
    assert sent and sent[0]["temperature"] is None


def test_a_value_survives_a_round_trip_through_a_model_that_hides_it(
    browser_page: Page,
):
    """Temperature has no control under Luna. Coming back to a model that has
    one used to show an empty box — the value only existed in the control that
    had just been removed — and an empty box is dropped from the patch, so the
    setting was abandoned without anyone touching it."""
    _admin_console(browser_page, settings=REASONING_SETTINGS)
    browser_page.locator("#tab-settings").click()

    browser_page.locator("#setting-model").select_option("gpt-5.6-luna")
    expect(browser_page.locator("#setting-temperature")).to_have_count(0)
    browser_page.locator("#setting-model").select_option("gpt-4o-mini")

    expect(browser_page.locator("#setting-temperature")).to_have_value("0.1")


def test_a_refusal_against_a_hidden_field_is_still_said_out_loud(browser_page: Page):
    """The silence is the bug. An error whose field this model does not draw has
    nowhere to sit in the form, and was written to a node that does not exist —
    leaving a re-enabled Save button as the only thing that happened."""
    _admin_console(browser_page, settings=ON_A_REASONING_MODEL)
    browser_page.locator("#tab-settings").click()
    _capture_put(
        browser_page,
        ON_A_REASONING_MODEL,
        status=422,
        response={
            "error": "validation_failed",
            "errors": [
                {"field": "reasoning_effort", "code": "reasoning_not_supported"},
            ],
        },
    )

    browser_page.locator("#setting-model").select_option("gpt-4o-mini")
    browser_page.locator("#settings-save").click()

    expect(browser_page.locator("#toast")).to_contain_text("reasoning", ignore_case=True)


def test_the_form_says_when_it_is_not_the_model_answering(browser_page: Page):
    """Configured is not the same fact as live, and the console used to report
    only the first — which is how it showed Luna while every answer came from
    gpt-4o-mini, with the disagreement visible only in the server's terminal."""
    _admin_console(
        browser_page,
        settings={
            **ON_A_REASONING_MODEL,
            "active": {"model": "gpt-4o-mini"},
        },
    )
    browser_page.locator("#tab-settings").click()

    expect(browser_page.locator("#settings-not-live")).to_contain_text("gpt-4o-mini")


def test_no_warning_when_the_live_model_is_the_configured_one(browser_page: Page):
    """A permanent notice is a notice nobody reads."""
    _admin_console(
        browser_page,
        settings={
            **ON_A_REASONING_MODEL,
            "active": {"model": "gpt-5.6-luna"},
        },
    )
    browser_page.locator("#tab-settings").click()

    expect(browser_page.locator("#setting-model")).to_be_visible()
    expect(browser_page.locator("#settings-not-live")).to_have_count(0)


def test_the_token_box_declares_the_selected_model_s_ceiling(browser_page: Page):
    """128000 is a fine answer length for Luna and an instant 400 for gpt-4o-mini.
    The box that holds it has to say which."""
    _admin_console(browser_page, settings=ON_A_REASONING_MODEL)
    browser_page.locator("#tab-settings").click()

    expect(browser_page.locator("#setting-max_tokens")).to_have_attribute("max", "128000")
    browser_page.locator("#setting-model").select_option("gpt-4o-mini")
    expect(browser_page.locator("#setting-max_tokens")).to_have_attribute("max", "16384")


# ── Reverting an override ─────────────────────────────────────────────────────

OVERRIDDEN = {
    "settings": {
        "model": "gpt-4o",
        "temperature": 0.9,
        "max_tokens": 16384,
        "max_context_results": 8,
        "reasoning_effort": None,
    },
    "overrides": {"temperature": 0.9},
    "defaults": {
        "model": "gpt-4o-mini",
        "temperature": 0.1,
        "max_tokens": 16384,
        "max_context_results": 8,
        "reasoning_effort": None,
    },
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
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({**OVERRIDDEN, "overrides": {}, "applied": True}),
            )
        else:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(OVERRIDDEN))

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
    {
        "id": "test-admin-id",
        "email": "admin@example.com",
        "role": "admin",
        "tier": "staff",
        "is_disabled": False,
        "last_sign_in_at": None,
    },
    # The only seeded account that has ever signed in. Every entry here used to
    # carry None, so the people table's date path was never rendered by a test
    # at all — which is how it shipped for a year formatting the cell with
    # `toLocaleDateString`, whose Arabic output the bidi algorithm mangles.
    {
        "id": "test-user-id",
        "email": "test@example.com",
        "role": "user",
        "tier": "free",
        "is_disabled": False,
        "last_sign_in_at": "2026-08-15T12:00:00+00:00",
    },
    {
        "id": "test-disabled-id",
        "email": "disabled@example.com",
        "role": "user",
        "tier": "free",
        "is_disabled": True,
        "last_sign_in_at": None,
    },
    {
        "id": "test-orphan-id",
        "email": "orphan@example.com",
        "role": "user",
        "tier": "free",
        "is_disabled": False,
        "last_sign_in_at": None,
    },
]

DETAILS = {
    "test-user-id": {
        "id": "test-user-id",
        "email": "test@example.com",
        "has_profile": True,
        "role": "user",
        "tier": "free",
        "is_disabled": False,
        "created_at": "2026-02-01T00:00:00+00:00",
        "last_sign_in_at": None,
        "email_confirmed_at": "2026-02-01T00:00:00+00:00",
        # Non-null, because the profile form sends it back as the version it was
        # loaded at and a null one would let the assertion pass vacuously.
        "updated_at": "2026-05-01T09:00:00+00:00",
        "disabled_at": None,
        "disabled_by_email": None,
        "disabled_reason": None,
        "first_name": "Test",
        "family_name": "User",
        "age": None,
        "full_name": "Test User",
        "organization": "Test Organization",
        "specialization": "Regulatory Affairs",
        "last_seen_at": None,
    },
    "test-disabled-id": {
        "id": "test-disabled-id",
        "email": "disabled@example.com",
        "has_profile": True,
        "role": "user",
        "tier": "free",
        "is_disabled": True,
        "created_at": "2026-03-01T00:00:00+00:00",
        "last_sign_in_at": None,
        "email_confirmed_at": "2026-03-01T00:00:00+00:00",
        "updated_at": None,
        "disabled_at": "2026-06-01T00:00:00+00:00",
        "disabled_by_email": "admin@example.com",
        "disabled_reason": "Sharing an account with a colleague",
        "first_name": None,
        "family_name": None,
        "age": None,
        "full_name": None,
        "organization": None,
        "specialization": None,
        "last_seen_at": None,
    },
    "test-orphan-id": {
        "id": "test-orphan-id",
        "email": "orphan@example.com",
        "has_profile": False,
        "role": None,
        "tier": None,
        "is_disabled": None,
        "created_at": "2026-04-01T00:00:00+00:00",
        "last_sign_in_at": None,
        "email_confirmed_at": None,
        "updated_at": None,
        "disabled_at": None,
        "disabled_by_email": None,
        "disabled_reason": None,
        "first_name": None,
        "family_name": None,
        "age": None,
        "full_name": None,
        "organization": None,
        "specialization": None,
        "last_seen_at": None,
    },
}


def _json(route, body):
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def _open_people(page: Page, *, lang: str = "", accounts=None) -> None:
    _route_identity(page, status=200, body=ADMIN_IDENTITY)
    account_list = ACCOUNTS if accounts is None else accounts

    def users_or_detail(route):
        url = route.request.url
        match = re.search(r"/admin/api/users/([^?]+)", url)
        if match:
            account = DETAILS.get(match.group(1))
            if account is None:
                route.fulfill(
                    status=404,
                    content_type="application/json",
                    body=json.dumps({"error": "no_such_account"}),
                )
                return
            _json(route, {"user": account, "self_id": "test-admin-id"})
            return

        query_params = parse_qs(urlparse(url).query)
        needle = (query_params.get("q") or [""])[0].lower()
        limit = int((query_params.get("limit") or ["50"])[0])
        offset = int((query_params.get("offset") or ["0"])[0])
        rows = [a for a in account_list if needle in a["email"].lower()]
        sliced = rows[offset : offset + limit]
        _json(
            route,
            {
                "users": sliced,
                "total": len(rows),
                "limit": limit,
                "offset": offset,
                "self_id": "test-admin-id",
            },
        )

    page.route("**/admin/api/users*", users_or_detail)
    page.route("**/admin/api/users/*", users_or_detail)
    page.route(
        "**/admin/api/audit*", lambda route: _json(route, {"entries": [], "limit": 50, "offset": 0})
    )
    page.route("**/admin/api/settings*", lambda route: _json(route, SETTINGS))

    page.goto(f"/admin?testing=true{lang}")
    expect(page.locator("#admin-console")).to_be_visible()
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


def test_the_people_table_dates_survive_arabic(browser_page: Page):
    """Two failures met in this one column, and neither is visible in English.

    `toLocaleDateString('ar')` returns `15<U+200F>/8<U+200F>/2026` — RIGHT-TO-LEFT
    MARKs between the numeric fields. Those are strongly-RTL characters inside a
    run of digits, so the bidi algorithm reorders the fields even within the
    cell's own `dir="ltr"` isolate and the column rendered `152026/8/`: a date
    saying the wrong thing, not merely looking odd. `dir` cannot fix that; only
    not emitting the marks can, which is why the stamp is built from parts.

    Separately, `dir="ltr"` sets the direction of the BOX, so `text-align: start`
    resolved to physical LEFT and every machine cell hugged the edge opposite its
    own column heading.
    """
    _open_people(browser_page, lang="&lang=ar")

    expect(browser_page.locator("html")).to_have_attribute("dir", "rtl")
    row = browser_page.locator(".admin-table tbody tr", has_text="test@example.com")
    seen = row.locator("td.admin-cell-machine").nth(1)

    # Shape, not a fixed date: `dayStamp` reads local parts, so the day itself is
    # timezone-dependent. The mangling this guards against fails the shape.
    stamp = seen.inner_text().strip()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp), f"not an ISO stamp: {stamp!r}"
    assert not re.search(r"[‎‏؜⁦-⁩]", stamp), f"stamp carries bidi control characters: {stamp!r}"
    assert seen.evaluate("el => getComputedStyle(el).textAlign") == "end"


def test_the_detail_keeps_machine_values_left_to_right_in_arabic(browser_page: Page):
    _open_people(browser_page, lang="&lang=ar")
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    expect(browser_page.locator("html")).to_have_attribute("dir", "rtl")
    expect(browser_page.locator("#account-heading .admin-cell-machine")).to_have_attribute(
        "dir", "ltr"
    )


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


def test_the_detail_no_longer_lists_anything_as_missing(browser_page: Page):
    """Both actions this block used to name — ending sessions and changing an
    email — have shipped. The block hides itself entirely when it has nothing
    to say, rather than rendering empty scaffolding."""
    _open_people(browser_page)
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    expect(browser_page.locator("#account-absent")).to_have_count(0)


def test_sending_a_reset_asks_first_and_reports_the_outcome(browser_page: Page):
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/reset-password",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"accepted": True, "operation_id": "op-1"}),
        ),
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
            status=429,
            content_type="application/json",
            body=json.dumps({"error": "reset_quota_exhausted"}),
        ),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.locator("#account-send-reset").click()

    expect(browser_page.locator("#toast")).to_contain_text("allowance", ignore_case=True)


def test_the_detail_offers_to_end_sessions_and_change_email(browser_page: Page):
    _open_people(browser_page)
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    expect(browser_page.locator("#account-revoke-sessions")).to_be_visible()
    expect(browser_page.locator("#account-change-email")).to_be_visible()


def test_ending_sessions_asks_first_and_reports_the_outcome(browser_page: Page):
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/revoke-sessions",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"accepted": True, "operation_id": "op-1"}),
        ),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.locator("#account-revoke-sessions").click()

    expect(browser_page.locator("#toast")).to_contain_text("ended", ignore_case=True)


def test_declining_the_session_end_confirmation_sends_nothing(browser_page: Page):
    sent = []
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/revoke-sessions",
        lambda route: (sent.append(1), route.fulfill(status=200, body="{}")),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    browser_page.once("dialog", lambda dialog: dialog.dismiss())
    browser_page.locator("#account-revoke-sessions").click()
    browser_page.wait_for_timeout(300)

    assert not sent, "a dismissed confirmation still sent the revocation"


def test_an_outage_on_a_session_end_is_not_retried(browser_page: Page):
    calls = []
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/revoke-sessions",
        lambda route: (
            calls.append(1),
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"error": "storage_unavailable"}),
            ),
        ),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()
    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.locator("#account-revoke-sessions").click()
    browser_page.wait_for_timeout(500)

    assert calls == [1], f"a 503 on a mutation was sent {len(calls)} times"


def _accept_email_change_dialogs(new_email: str, *, confirm: bool = True):
    """Two sequential native dialogs fire in one click here, unlike every
    other action on this page: a prompt for the new address, then a confirm.
    Playwright's `once("dialog", ...)` only ever handles the first one, so
    this needs `on(...)` with type branching instead."""

    def handle(dialog):
        if dialog.type == "prompt":
            dialog.accept(new_email)
        elif confirm:
            dialog.accept()
        else:
            dialog.dismiss()

    return handle


def test_changing_email_prompts_confirms_and_reports_the_outcome(browser_page: Page):
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/change-email",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"accepted": True, "operation_id": "op-1"}),
        ),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    browser_page.on("dialog", _accept_email_change_dialogs("new-address@example.com"))
    browser_page.locator("#account-change-email").click()

    expect(browser_page.locator("#toast")).to_contain_text("changed", ignore_case=True)


def test_declining_the_email_change_confirmation_sends_nothing(browser_page: Page):
    sent = []
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/change-email",
        lambda route: (sent.append(1), route.fulfill(status=200, body="{}")),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    browser_page.on(
        "dialog", _accept_email_change_dialogs("new-address@example.com", confirm=False)
    )
    browser_page.locator("#account-change-email").click()
    browser_page.wait_for_timeout(300)

    assert not sent, "a dismissed confirmation still sent the change"


def test_an_invalid_typed_email_is_rejected_before_any_request(browser_page: Page):
    """Only one dialog should fire here at all: the client-side check refuses
    before a confirm is ever shown, so a mistyped address never reaches a
    confirmation dialog that names it."""
    sent = []
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/change-email",
        lambda route: (sent.append(1), route.fulfill(status=200, body="{}")),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    browser_page.once("dialog", lambda dialog: dialog.accept("not-an-email"))
    browser_page.locator("#account-change-email").click()
    browser_page.wait_for_timeout(300)

    assert not sent, "an invalid typed address still reached the network"
    expect(browser_page.locator("#toast")).to_be_visible()


def test_a_duplicate_email_gets_its_own_sentence(browser_page: Page):
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/change-email",
        lambda route: route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps({"error": "email_already_registered"}),
        ),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    browser_page.on("dialog", _accept_email_change_dialogs("new-address@example.com"))
    browser_page.locator("#account-change-email").click()

    expect(browser_page.locator("#toast")).to_contain_text("already", ignore_case=True)


def test_an_outage_on_an_email_change_is_not_retried(browser_page: Page):
    calls = []
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/change-email",
        lambda route: (
            calls.append(1),
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"error": "storage_unavailable"}),
            ),
        ),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    browser_page.on("dialog", _accept_email_change_dialogs("new-address@example.com"))
    browser_page.locator("#account-change-email").click()
    browser_page.wait_for_timeout(500)

    assert calls == [1], f"a 503 on a mutation was sent {len(calls)} times"


# ── The account page is the one home for what is done to an account ──────────


def test_role_and_access_controls_live_only_on_the_account_page(browser_page: Page):
    """TODO.md asks for one home for everything done to an account.

    They used to be buttons on every list row AND on the detail view, which is
    two places to keep true and two places to get wrong — and it made the list
    unreadable across five columns of controls.
    """
    _open_people(browser_page)
    rows = browser_page.locator("#people-table")
    expect(rows.locator("[data-action='promote']")).to_have_count(0)
    expect(rows.locator("[data-action='disable']")).to_have_count(0)

    browser_page.locator(".admin-account-open", has_text="test@example.com").click()
    expect(browser_page.locator("#account-actions [data-action='promote']")).to_be_visible()
    expect(browser_page.locator("#account-actions [data-action='disable']")).to_be_visible()


def test_clicking_anywhere_in_a_row_opens_that_account(browser_page: Page):
    """The address stays a real button for the keyboard; the row answers too,
    because a five-column row where only the first cell responds is a target the
    eye has to aim at."""
    _open_people(browser_page)
    # The Role cell — not the address button, so this proves the row itself.
    browser_page.locator("#people-table tbody tr[data-user-id='test-user-id'] td").nth(1).click()

    expect(browser_page.locator("#account-heading")).to_contain_text("test@example.com")


def test_opening_an_account_takes_the_search_label_with_the_input(browser_page: Page):
    """The id used to be on the input alone, so opening an account hid the box
    and left "Search by email" stranded above the account page, labelling
    nothing."""
    _open_people(browser_page)
    expect(browser_page.locator("#people-search-field")).to_be_visible()

    browser_page.locator(".admin-account-open", has_text="test@example.com").click()
    expect(browser_page.locator("#people-search-field")).to_be_hidden()

    browser_page.locator("#account-back").click()
    expect(browser_page.locator("#people-search-field")).to_be_visible()


def test_a_disabled_account_states_its_standing_beside_its_address(browser_page: Page):
    """Standing was the fifth row of a definition list, at the same weight as
    "Created" — so whether this person can use the product at all took reading
    the page to find out."""
    _open_people(browser_page)
    browser_page.locator(".admin-account-open", has_text="disabled@example.com").click()

    head = browser_page.locator(".admin-account-head")
    expect(head).to_have_class(re.compile(r"is-off"))
    expect(head.locator(".admin-mark.is-off")).to_contain_text("Disabled")
    # Asking for a reason and then filing it out of sight is how a required
    # field becomes theatre.
    expect(browser_page.locator(".admin-account-reason")).to_contain_text("colleague")


# ── Outage handling in the transport ─────────────────────────────────────────


def test_opening_an_account_fetches_it_once(browser_page: Page):
    """The row and the address are both ways in; exactly one may fire.

    Every admin request costs a GoTrue token verification, so a double-open is
    not merely untidy — it doubles the load on the service whose timeout caused
    the incident this suite now covers.
    """
    calls = []
    _open_people(browser_page)

    def counted(route):
        calls.append(route.request.url)
        _json(route, {"user": DETAILS["test-user-id"], "self_id": "test-admin-id"})

    browser_page.route("**/admin/api/users/test-user-id", counted)
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()
    expect(browser_page.locator("#account-heading")).to_contain_text("test@example.com")
    browser_page.wait_for_timeout(400)

    assert len(calls) == 1, f"one click fetched the account {len(calls)} times"


def test_a_double_click_does_not_open_an_account_twice(browser_page: Page):
    """Seen in the incident log: the same account fetched twice, one second
    apart. Two clicks, not a double-fire — but each open costs two requests and
    each request costs a GoTrue token verification, so an impatient operator
    spends four of them to draw one page against the service whose timeout
    started all this.
    """
    calls = []
    _open_people(browser_page)

    def slow(route):
        calls.append(1)
        _json(route, {"user": DETAILS["test-user-id"], "self_id": "test-admin-id"})

    browser_page.route("**/admin/api/users/test-user-id", slow)
    target = browser_page.locator(".admin-account-open", has_text="test@example.com")
    target.click(click_count=2, delay=10)

    expect(browser_page.locator("#account-heading")).to_contain_text("test@example.com")
    browser_page.wait_for_timeout(500)
    assert len(calls) == 1, f"a double-click fetched the account {len(calls)} times"


def test_an_account_can_be_reopened_after_going_back(browser_page: Page):
    """The guard above must not become a lock. Returning to the list abandons
    whatever was opening, so the same account opens again straight after."""
    _open_people(browser_page)
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()
    expect(browser_page.locator("#account-heading")).to_contain_text("test@example.com")

    browser_page.locator("#account-back").click()
    expect(browser_page.locator("#people-list")).to_be_visible()

    browser_page.locator(".admin-account-open", has_text="test@example.com").click()
    expect(browser_page.locator("#account-heading")).to_contain_text("test@example.com")


def test_a_failed_open_does_not_lock_the_account_shut(browser_page: Page):
    """The guard is released in `finally`. Released only on success, one failed
    load would make that account permanently unopenable for the session."""
    _open_people(browser_page)
    browser_page.route("**/admin/api/users/test-user-id", lambda route: route.fulfill(status=500))
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()
    expect(browser_page.locator("#account-error")).to_be_visible()

    # The route is now healthy again; the same account must still open.
    browser_page.unroute("**/admin/api/users/test-user-id")
    browser_page.locator("#account-back").click()
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()
    expect(browser_page.locator("#account-heading")).to_contain_text("test@example.com")


def test_a_transient_outage_on_a_read_is_retried_once(browser_page: Page):
    """The server answers 503 rather than 401 when it cannot reach the identity
    provider. That is truthful — and it would have turned a blip the old 401
    retry silently absorbed into a visible failure, so a GET is retried."""
    calls = []
    _open_people(browser_page)

    def flaky(route):
        calls.append(1)
        if len(calls) == 1:
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"error": "identity_unavailable"}),
            )
            return
        _json(route, {"user": DETAILS["test-user-id"], "self_id": "test-admin-id"})

    browser_page.route("**/admin/api/users/test-user-id", flaky)
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    expect(browser_page.locator("#account-heading")).to_contain_text("test@example.com")
    assert len(calls) == 2, "a transient 503 on a read should be retried exactly once"


def test_an_outage_on_a_mutation_is_not_retried(browser_page: Page):
    """A 401 provably precedes the route body; a 503 does not.

    `storage_unavailable` is returned by routes that have already begun work, so
    re-sending on one would be a second attempt at a mutation nobody asked for
    twice — and this console can put a recovery link in somebody's inbox.
    """
    calls = []
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/reset-password",
        lambda route: (
            calls.append(1),
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"error": "storage_unavailable"}),
            ),
        ),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()
    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.locator("#account-send-reset").click()
    browser_page.wait_for_timeout(500)

    assert calls == [1], f"a 503 on a mutation was sent {len(calls)} times"


# ── The profile is editable ──────────────────────────────────────────────────


def test_the_profile_can_be_edited_and_carries_the_version_it_was_loaded_at(
    browser_page: Page,
):
    """`PATCH …/profile` and `admin_update_profile` were built and tested with
    no caller at all, so this zone showed three values an operator could read
    and not correct.

    The version travels with the write: the RPC refuses a save whose expectation
    no longer matches rather than overwriting whatever somebody else stored
    while this form sat open.
    """
    sent = []
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/profile",
        lambda route: (
            sent.append(route.request.post_data),
            _json(route, {"profile": DETAILS["test-user-id"]}),
        ),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()

    expect(browser_page.locator("#account-organization")).to_have_value("Test Organization")
    browser_page.locator("#account-organization").fill("Ministry of Health")
    browser_page.locator("#account-specialization").fill("")
    browser_page.locator("#account-profile-save").click()

    expect(browser_page.locator("#toast")).to_contain_text("saved", ignore_case=True)
    body = json.loads(sent[0])
    assert body["organization"] == "Ministry of Health"
    # Cleared means null, not "". The column is nullable, and "never filled in"
    # is a different fact about a person than "set to the empty string".
    assert body["specialization"] is None
    assert body["expected_updated_at"] == "2026-05-01T09:00:00+00:00"


def test_a_stale_profile_save_is_refused_rather_than_overwriting(browser_page: Page):
    """A row lock protects execution time; this protects think time. Two
    operators with the same account open would otherwise have the later save
    silently discard the earlier one."""
    _open_people(browser_page)
    browser_page.route(
        "**/admin/api/users/*/profile",
        lambda route: route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps({"error": "profile_changed_since_loaded"}),
        ),
    )
    browser_page.locator(".admin-account-open", has_text="test@example.com").click()
    browser_page.locator("#account-first-name").fill("Somebody Else")
    browser_page.locator("#account-profile-save").click()

    expect(browser_page.locator("#toast")).to_contain_text("Reload", ignore_case=True)


def test_an_account_with_no_profile_offers_no_profile_form(browser_page: Page):
    """There is no row to write to. A form that cannot save is worse than an
    absent one, because it invites the attempt."""
    _open_people(browser_page)
    browser_page.locator(".admin-account-open", has_text="orphan@example.com").click()

    expect(browser_page.locator("#account-profile-form")).to_have_count(0)
    # But the reset link still works — it goes to an address, not to a profile.
    expect(browser_page.locator("#account-send-reset")).to_be_visible()


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


# ── People Pager ─────────────────────────────────────────────────────────────

MANY_ACCOUNTS = [
    {
        "id": f"test-user-{i}",
        "email": f"user{i:03d}@example.com",
        "role": "admin" if i == 1 else "user",
        "tier": "free",
        "is_disabled": False,
        "last_sign_in_at": None,
    }
    for i in range(1, 61)
]


def test_people_pager_one_page_result_disables_both_buttons(browser_page: Page):
    """One-page result: range shown (e.g. 1–4 of 4), both buttons disabled."""
    _open_people(browser_page)
    pager = browser_page.locator("#people-pager")
    expect(pager).to_be_visible()
    expect(pager).to_have_attribute("aria-controls", "people-table")
    expect(pager).to_have_attribute("aria-busy", "false")

    status = browser_page.locator("#people-range-status")
    expect(status).to_be_visible()
    bdis = status.locator("bdi")
    expect(bdis.nth(0)).to_have_text("1–4")
    expect(bdis.nth(1)).to_have_text("4")

    expect(browser_page.locator("#people-prev")).to_be_disabled()
    expect(browser_page.locator("#people-next")).to_be_disabled()


def test_people_pager_multi_page_navigation(browser_page: Page):
    """Multi-page result: Next requests page 2, Previous returns to page 1."""
    _open_people(browser_page, accounts=MANY_ACCOUNTS)

    # Initial page 1 (1–50 of 60)
    expect(browser_page.locator(".admin-account-open")).to_have_count(50)
    expect(browser_page.locator(".admin-account-open").first).to_have_text("user001@example.com")
    expect(browser_page.locator("#people-prev")).to_be_disabled()
    expect(browser_page.locator("#people-next")).to_be_enabled()

    bdis = browser_page.locator("#people-range-status bdi")
    expect(bdis.nth(0)).to_have_text("1–50")
    expect(bdis.nth(1)).to_have_text("60")

    # Click Next -> page 2 (51–60 of 60)
    browser_page.locator("#people-next").click()
    expect(browser_page.locator(".admin-account-open")).to_have_count(10)
    expect(browser_page.locator(".admin-account-open").first).to_have_text("user051@example.com")
    expect(browser_page.locator("#people-prev")).to_be_enabled()
    expect(browser_page.locator("#people-next")).to_be_disabled()
    expect(bdis.nth(0)).to_have_text("51–60")
    expect(bdis.nth(1)).to_have_text("60")

    # Click Prev -> page 1 (1–50 of 60)
    browser_page.locator("#people-prev").click()
    expect(browser_page.locator(".admin-account-open")).to_have_count(50)
    expect(browser_page.locator(".admin-account-open").first).to_have_text("user001@example.com")
    expect(browser_page.locator("#people-prev")).to_be_disabled()
    expect(browser_page.locator("#people-next")).to_be_enabled()
    expect(bdis.nth(0)).to_have_text("1–50")


def test_people_pager_page_size_change_resets_to_offset_0(browser_page: Page):
    """Changing page size resets offset to 0 and requests the new limit."""
    _open_people(browser_page, accounts=MANY_ACCOUNTS)

    # Go to page 2 first (offset 50)
    browser_page.locator("#people-next").click()
    expect(browser_page.locator("#people-range-status bdi").nth(0)).to_have_text("51–60")

    # Change page size to 25 -> resets to offset 0, limit 25
    browser_page.locator("#people-page-size").select_option("25")
    expect(browser_page.locator(".admin-account-open")).to_have_count(25)
    expect(browser_page.locator(".admin-account-open").first).to_have_text("user001@example.com")
    expect(browser_page.locator("#people-range-status bdi").nth(0)).to_have_text("1–25")
    expect(browser_page.locator("#people-prev")).to_be_disabled()
    expect(browser_page.locator("#people-next")).to_be_enabled()

    # Change page size to 100 -> all 60 fit on page 1, both buttons disabled
    browser_page.locator("#people-page-size").select_option("100")
    expect(browser_page.locator(".admin-account-open")).to_have_count(60)
    expect(browser_page.locator("#people-range-status bdi").nth(0)).to_have_text("1–60")
    expect(browser_page.locator("#people-prev")).to_be_disabled()
    expect(browser_page.locator("#people-next")).to_be_disabled()


def test_people_pager_search_while_on_page_2_resets_offset_to_0(browser_page: Page):
    """A search typed while on page 2 sends offset 0 and renders query results."""
    _open_people(browser_page, accounts=MANY_ACCOUNTS)

    # Go to page 2 (offset 50)
    browser_page.locator("#people-next").click()
    expect(browser_page.locator("#people-range-status bdi").nth(0)).to_have_text("51–60")

    # Search for "user00" which matches user001..user009 (9 accounts)
    browser_page.locator("#people-search").fill("user00")
    expect(browser_page.locator(".admin-account-open")).to_have_count(9)
    expect(browser_page.locator("#people-range-status bdi").nth(0)).to_have_text("1–9")
    expect(browser_page.locator("#people-range-status bdi").nth(1)).to_have_text("9")
    expect(browser_page.locator("#people-prev")).to_be_disabled()
    expect(browser_page.locator("#people-next")).to_be_disabled()


def test_people_pager_out_of_order_responses_resolve_correctly(browser_page: Page):
    """Hold an old response, resolve a newer one first, then release old.
    Assert the DOM shows newer query and aborted request does not surface error."""
    _route_identity(browser_page, status=200, body=ADMIN_IDENTITY)
    browser_page.route("**/admin/api/settings", lambda route: _json(route, SETTINGS))
    browser_page.route("**/admin/api/registrations", lambda route: _json(route, REGISTRATIONS))

    held_routes = []

    def custom_users(route):
        url = route.request.url
        query_params = parse_qs(urlparse(url).query)
        q = (query_params.get("q") or [""])[0]
        if q == "slow":
            held_routes.append(route)
            return
        rows = [a for a in ACCOUNTS if q in a["email"].lower()]
        _json(
            route,
            {
                "users": rows,
                "total": len(rows),
                "limit": 50,
                "offset": 0,
                "self_id": "test-admin-id",
            },
        )

    browser_page.route("**/admin/api/users*", custom_users)
    browser_page.route("**/admin/api/users/*", custom_users)
    browser_page.route(
        "**/admin/api/audit*", lambda route: _json(route, {"entries": [], "limit": 50, "offset": 0})
    )

    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-people").click()
    expect(browser_page.locator(".admin-account-open")).to_have_count(4)

    # Type "slow" to trigger the held request
    browser_page.locator("#people-search").fill("slow")
    browser_page.wait_for_timeout(350)

    # Now type "orphan" to trigger a second fast request
    browser_page.locator("#people-search").fill("orphan")
    expect(browser_page.locator(".admin-account-open")).to_have_count(1)
    expect(browser_page.locator(".admin-account-open")).to_contain_text("orphan@example.com")

    # Now fulfill the held slow route
    for r in held_routes:
        with contextlib.suppress(Exception):
            _json(
                r,
                {
                    "users": ACCOUNTS,
                    "total": 4,
                    "limit": 50,
                    "offset": 0,
                    "self_id": "test-admin-id",
                },
            )

    browser_page.wait_for_timeout(300)
    # DOM still shows "orphan" result, not overwritten by slow
    expect(browser_page.locator(".admin-account-open")).to_have_count(1)
    expect(browser_page.locator(".admin-account-open")).to_contain_text("orphan@example.com")
    expect(browser_page.locator("#toast")).to_have_class("toast-notification hidden")


def test_people_pager_repeated_rapid_clicks_only_issue_one_request(browser_page: Page):
    """Rapid clicks while request is pending do not issue duplicate requests."""
    calls = []
    _route_identity(browser_page, status=200, body=ADMIN_IDENTITY)
    browser_page.route("**/admin/api/settings", lambda route: _json(route, SETTINGS))
    browser_page.route("**/admin/api/registrations", lambda route: _json(route, REGISTRATIONS))

    def users_handler(route):
        url = route.request.url
        query_params = parse_qs(urlparse(url).query)
        offset = int((query_params.get("offset") or ["0"])[0])
        calls.append(offset)
        rows = MANY_ACCOUNTS[offset : offset + 50]
        _json(
            route,
            {
                "users": rows,
                "total": len(MANY_ACCOUNTS),
                "limit": 50,
                "offset": offset,
                "self_id": "test-admin-id",
            },
        )

    browser_page.route("**/admin/api/users*", users_handler)
    browser_page.route(
        "**/admin/api/audit*", lambda route: _json(route, {"entries": [], "limit": 50, "offset": 0})
    )

    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-people").click()
    expect(browser_page.locator(".admin-account-open")).to_have_count(50)
    assert calls == [0]

    # Rapid click next multiple times
    next_btn = browser_page.locator("#people-next")
    next_btn.click(click_count=3, delay=5)
    expect(browser_page.locator(".admin-account-open")).to_have_count(10)
    # Exactly one page 2 request (offset=50) was issued
    assert calls == [0, 50]


def test_people_pager_renders_in_arabic_with_ltr_bdi(browser_page: Page):
    """Arabic rendering: labels from catalogue, dir=rtl, bdi wrapping, no bidi marks."""
    _open_people(browser_page, lang="&lang=ar")

    expect(browser_page.locator("html")).to_have_attribute("dir", "rtl")
    pager = browser_page.locator("#people-pager")
    expect(pager).to_have_attribute("aria-label", "صفحات المستخدمين")

    expect(browser_page.locator("#people-prev")).to_contain_text("الصفحة السابقة")
    expect(browser_page.locator("#people-next")).to_contain_text("الصفحة التالية")

    status = browser_page.locator("#people-range-status")
    expect(status).to_contain_text("عرض")
    expect(status).to_contain_text("من")

    bdis = status.locator("bdi")
    expect(bdis.nth(0)).to_have_attribute("dir", "ltr")
    expect(bdis.nth(0)).to_have_text("1–4")
    expect(bdis.nth(1)).to_have_attribute("dir", "ltr")
    expect(bdis.nth(1)).to_have_text("4")

    # Assert no stray bidi control characters in the status text
    status_text = status.inner_text()
    assert not re.search(r"[‎‏؜⁦-⁩]", status_text), f"status carries bidi marks: {status_text!r}"

    expect(browser_page.locator('label[for="people-page-size"]')).to_have_text(
        "عدد الصفوف في الصفحة"
    )


def test_people_pager_loading_busy_visual_threshold(browser_page: Page):
    """Fast requests (<100ms) never show .is-busy-visual. Slow requests (>100ms) show it while in-flight."""
    _route_identity(browser_page, status=200, body=ADMIN_IDENTITY)
    browser_page.route("**/admin/api/settings", lambda route: _json(route, SETTINGS))
    browser_page.route("**/admin/api/registrations", lambda route: _json(route, REGISTRATIONS))

    # Fast initial load
    def fast_users(route):
        _json(
            route,
            {
                "users": MANY_ACCOUNTS[0:50],
                "total": 60,
                "limit": 50,
                "offset": 0,
                "self_id": "test-admin-id",
            },
        )

    browser_page.route("**/admin/api/users*", fast_users)
    browser_page.route(
        "**/admin/api/audit*", lambda route: _json(route, {"entries": [], "limit": 50, "offset": 0})
    )

    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-people").click()
    expect(browser_page.locator(".admin-account-open")).to_have_count(50)

    # .is-busy-visual was never added on fast request
    expect(browser_page.locator(".admin-table-wrapper")).not_to_have_class(
        re.compile(r"is-busy-visual")
    )

    # Now stub a slow request (>100ms)
    def slow_users(route):
        browser_page.wait_for_timeout(250)
        _json(
            route,
            {
                "users": MANY_ACCOUNTS[50:60],
                "total": 60,
                "limit": 50,
                "offset": 50,
                "self_id": "test-admin-id",
            },
        )

    browser_page.route("**/admin/api/users*", slow_users)
    browser_page.locator("#people-next").click()

    # Search and page size select remain non-disabled during request
    expect(browser_page.locator("#people-search")).to_be_enabled()
    expect(browser_page.locator("#people-page-size")).to_be_enabled()

    # After 150ms (past 100ms threshold), is-busy-visual should be present
    browser_page.wait_for_timeout(150)
    expect(browser_page.locator(".admin-table-wrapper")).to_have_class(
        re.compile(r"is-busy-visual")
    )

    # When request completes, is-busy-visual is cleared
    expect(browser_page.locator(".admin-account-open")).to_have_count(10)
    expect(browser_page.locator(".admin-table-wrapper")).not_to_have_class(
        re.compile(r"is-busy-visual")
    )


def test_people_pager_keyboard_focus_retention(browser_page: Page):
    """Keyboard focus retention: when next button becomes disabled, focus falls back to #people-range-status."""
    _open_people(browser_page, accounts=MANY_ACCOUNTS)

    # Focus next button and press Enter
    next_btn = browser_page.locator("#people-next")
    next_btn.focus()
    expect(next_btn).to_be_focused()
    browser_page.keyboard.press("Enter")

    # On page 2, next is disabled -> focus lands on #people-range-status
    expect(browser_page.locator(".admin-account-open")).to_have_count(10)
    expect(browser_page.locator("#people-next")).to_be_disabled()
    expect(browser_page.locator("#people-range-status")).to_be_focused()

    # Focus prev button and press Enter
    prev_btn = browser_page.locator("#people-prev")
    prev_btn.focus()
    expect(prev_btn).to_be_focused()
    browser_page.keyboard.press("Enter")

    # On page 1, prev is disabled -> focus lands on #people-range-status
    expect(browser_page.locator(".admin-account-open")).to_have_count(50)
    expect(browser_page.locator("#people-prev")).to_be_disabled()
    expect(browser_page.locator("#people-range-status")).to_be_focused()


def test_people_pager_aria_controls_resolves_to_people_table(browser_page: Page):
    """aria-controls on #people-pager points to the real table element id."""
    _open_people(browser_page)
    pager = browser_page.locator("#people-pager")
    expect(pager).to_have_attribute("aria-controls", "people-table")
    expect(browser_page.locator("#people-table")).to_be_visible()


def test_people_pager_boundary_drift_resets_to_offset_0(browser_page: Page):
    """Out-of-bounds offset returning {users: [], total: 0} resets to offset 0 and refetches."""
    _route_identity(browser_page, status=200, body=ADMIN_IDENTITY)
    browser_page.route("**/admin/api/settings", lambda route: _json(route, SETTINGS))
    browser_page.route("**/admin/api/registrations", lambda route: _json(route, REGISTRATIONS))
    requested_offsets = []
    call_count = [0]

    def drift_flow(route):
        query_params = parse_qs(urlparse(route.request.url).query)
        offset = int((query_params.get("offset") or ["0"])[0])
        requested_offsets.append(offset)
        call_count[0] += 1

        if call_count[0] == 1:
            # First load: page 1 of 60
            _json(
                route,
                {
                    "users": MANY_ACCOUNTS[0:50],
                    "total": 60,
                    "limit": 50,
                    "offset": 0,
                    "self_id": "test-admin-id",
                },
            )
        elif offset == 50:
            # Second load (Next clicked): boundary drift! users: [], total: 0
            _json(
                route,
                {"users": [], "total": 0, "limit": 50, "offset": 50, "self_id": "test-admin-id"},
            )
        else:
            # Third load (auto refetch on offset 0): return surviving accounts
            _json(
                route,
                {
                    "users": ACCOUNTS,
                    "total": 4,
                    "limit": 50,
                    "offset": 0,
                    "self_id": "test-admin-id",
                },
            )

    browser_page.route("**/admin/api/users*", drift_flow)
    browser_page.route(
        "**/admin/api/audit*", lambda route: _json(route, {"entries": [], "limit": 50, "offset": 0})
    )

    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-people").click()

    expect(browser_page.locator(".admin-account-open")).to_have_count(50)
    expect(browser_page.locator("#people-next")).to_be_enabled()

    # Click Next -> hits offset 50 -> gets {users: [], total: 0} -> resets to offset 0 -> renders 4 accounts
    browser_page.locator("#people-next").click()
    expect(browser_page.locator(".admin-account-open")).to_have_count(4)
    expect(browser_page.locator("#people-range-status bdi").nth(0)).to_have_text("1–4")
    assert 50 in requested_offsets
    assert requested_offsets[-1] == 0


def test_every_tab_actually_opens_its_panel(browser_page: Page):
    """Click EVERY tab and assert its panel appears.

    The Tiers tab shipped broken because no browser test ever clicked it: the
    template had six buttons and `ui.js`'s TABS list had five entries, so
    `selectTab('tab-tiers')` hid every panel it knew about and unhid nothing.
    The console went completely blank — heading, hint and all — which reads as a
    broken page rather than a missing list entry.

    Walking the tablist rather than naming tabs one by one is the point: a
    seventh tab added later is covered the moment it exists.
    """
    _route_identity(browser_page, status=200, body=ADMIN_IDENTITY)
    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()

    tab_ids = browser_page.eval_on_selector_all(".admin-tab", "els => els.map(el => el.id)")
    assert len(tab_ids) >= 6, f"expected the full tablist, saw {tab_ids}"

    for tab_id in tab_ids:
        panel_id = browser_page.locator(f"#{tab_id}").get_attribute("aria-controls")
        browser_page.locator(f"#{tab_id}").click()
        expect(browser_page.locator(f"#{panel_id}")).to_be_visible()
        expect(browser_page.locator(f"#{tab_id}")).to_have_attribute("aria-selected", "true")
        # The panel must have real content, not just be un-hidden: a heading is
        # server-rendered into every one of them.
        expect(browser_page.locator(f"#{panel_id} .admin-heading")).to_be_visible()


TIERS_RESPONSE = {
    "tiers": [
        {
            "key": "free",
            "label_en": "Free",
            "label_ar": "مجاني",
            "daily_message_limit": 200,
            "ordering": 0,
            "member_count": 4,
        },
        {
            "key": "staff",
            "label_en": "Staff",
            "label_ar": "الإداريين",
            "daily_message_limit": 200,
            "ordering": 10,
            "member_count": 1,
        },
    ]
}


def test_the_tiers_tab_lists_the_shipped_tiers(browser_page: Page):
    """The tab loads on ACTIVATION, so the table only exists after the click.

    The page authenticates as an ordinary reader (the console's own gate is
    mocked by `_route_identity`), so the data route is fulfilled here rather
    than reaching Flask — the same shape every other panel's browser test uses.
    """
    _route_identity(browser_page, status=200, body=ADMIN_IDENTITY)
    browser_page.route(
        "**/admin/api/tiers",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(TIERS_RESPONSE)
        ),
    )
    browser_page.goto("/admin?testing=true")
    expect(browser_page.locator("#admin-console")).to_be_visible()

    browser_page.locator("#tab-tiers").click()
    expect(browser_page.locator("#panel-tiers")).to_be_visible()

    body = browser_page.locator("#tiers-body")
    expect(body.locator("table")).to_be_visible()
    expect(body.locator("tbody tr")).to_have_count(2)
    expect(body).to_contain_text("free")
    expect(body).to_contain_text("staff")

    # `free` is structural: no delete control at all, rather than a disabled one.
    free_row = body.locator("tr[data-tier-key='free']")
    expect(free_row.locator("[data-tier-action='delete']")).to_have_count(0)
    expect(free_row.locator("[data-tier-action='edit']")).to_have_count(1)
    staff_row = body.locator("tr[data-tier-key='staff']")
    expect(staff_row.locator("[data-tier-action='delete']")).to_have_count(1)

    # The create form ships with the table, not behind another click.
    expect(body.locator("#tier-form")).to_be_visible()


def _tiers_console(page: Page, *, lang: str = "") -> None:
    """The console open on the Tiers tab, with the catalogue route fulfilled."""
    _route_identity(page, status=200, body=ADMIN_IDENTITY)
    page.route(
        "**/admin/api/tiers",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(TIERS_RESPONSE)
        ),
    )
    page.goto(f"/admin?testing=true{lang}")
    expect(page.locator("#admin-console")).to_be_visible()
    page.locator("#tab-tiers").click()
    expect(page.locator("#panel-tiers")).to_be_visible()


def test_the_tiers_table_shows_only_the_console_language(browser_page: Page):
    """One label column, not two.

    The table shipped with `Label (English)` AND `Label (Arabic)` side by side,
    so an operator who had toggled the console to English still read Arabic in
    it — the only surface in the product that ignored the toggle. Every other
    place a tier label is printed (`populateComposerTiers`, the allowance
    card's select) already picks one. Both labels are still STORED and still
    edited, in the form below the table; what is resolved here is only what a
    reader of the table is shown.
    """
    _tiers_console(browser_page)

    body = browser_page.locator("#tiers-body")
    expect(body.locator("table")).to_be_visible()
    rows = body.locator("tbody")
    expect(rows).to_contain_text("Free")
    expect(rows).not_to_contain_text("\u0645\u062c\u0627\u0646\u064a")

    # One label column: key, label, limit, members, order, actions.
    expect(body.locator("thead th")).to_have_count(6)


def test_the_tiers_table_shows_the_arabic_label_in_arabic(browser_page: Page):
    """The same table, the other way round. Neither language sees the other."""
    _tiers_console(browser_page, lang="&lang=ar")

    rows = browser_page.locator("#tiers-body tbody")
    expect(rows).to_contain_text("\u0645\u062c\u0627\u0646\u064a")
    expect(rows).not_to_contain_text("Free")
    # The KEY is not a label and stays as it is in both: it is what the
    # database and the notification composer both name.
    expect(rows).to_contain_text("free")


def test_the_tier_form_still_edits_both_labels(browser_page: Page):
    """Resolving the TABLE must not have removed either stored label."""
    _tiers_console(browser_page)
    browser_page.locator("tr[data-tier-key='free'] [data-tier-action='edit']").click()

    expect(browser_page.locator("#tier-label_en")).to_have_value("Free")
    expect(browser_page.locator("#tier-label_ar")).to_have_value("\u0645\u062c\u0627\u0646\u064a")
    # The key is permanent, and has to look it rather than merely behave it.
    expect(browser_page.locator("#tier-key")).to_have_attribute("readonly", "")
