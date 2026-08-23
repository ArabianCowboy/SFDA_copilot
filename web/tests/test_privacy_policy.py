"""/privacy — سياسة الاستخدام والخصوصية / Usage and Privacy Policy.

Public, ungated (docs/profile-refactor-plan.md §12.4, Step 6). Content is a
DRAFT — these tests pin structure and the draft disclosure, not the exact
prose, which is expected to change once reviewed."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


def test_the_page_loads_signed_out(browser_page: Page):
    browser_page.goto("/privacy")
    expect(browser_page.locator("#policy-heading")).to_be_visible()


def test_it_states_plainly_that_it_is_a_draft(browser_page: Page):
    browser_page.goto("/privacy")
    expect(browser_page.locator("#page-draft-notice")).to_be_visible()


def test_theme_and_language_toggle_work_on_this_page(browser_page: Page):
    browser_page.goto("/privacy")
    theme_button = browser_page.locator(".theme-toggle-btn")
    lang_button = browser_page.locator(".lang-toggle-btn")

    initial_theme = browser_page.evaluate("document.documentElement.getAttribute('data-bs-theme')")
    theme_button.click()
    assert (
        browser_page.evaluate("document.documentElement.getAttribute('data-bs-theme')")
        != initial_theme
    )

    lang_button.click()
    browser_page.wait_for_url("**/privacy*")
    expect(browser_page.locator("html")).to_have_attribute("lang", "ar")


def test_the_signup_terms_checkbox_links_here(browser_page: Page):
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#signup-tab").click()

    expect(browser_page.locator("#signup-form a[href='/privacy']")).to_have_count(1)
