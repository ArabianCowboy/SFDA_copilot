"""The composer's category dropdown remembers the reader's last-used search
scope per device (docs/profile-refactor-plan.md §12.5) — not an account
field, so it carries no late-arrival hazard and needs no identity guard.
Default stays 'all': the safe direction on an unset or unrecognised value is
always the widest scope.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

TRIGGER = "#query-category"


def test_selecting_a_category_persists_it_for_next_visit(authenticated_page: Page):
    page = authenticated_page
    page.locator(TRIGGER).click()
    page.locator('.custom-dropdown-item[data-value="regulatory"]').click()
    expect(page.locator(TRIGGER)).to_have_attribute("data-value", "regulatory")

    assert page.evaluate("localStorage.getItem('sfda-search-scope')") == "regulatory"

    page.reload()
    page.locator("#authenticated-view").wait_for(state="visible")
    expect(page.locator(TRIGGER)).to_have_attribute("data-value", "regulatory")
    expect(page.locator(TRIGGER)).to_contain_text("Regulatory")


def test_selecting_all_categories_clears_the_saved_scope(authenticated_page: Page):
    """'all' is the absence of a scope, not a fourth stored value — the
    safe default must never need to be read back from storage."""
    page = authenticated_page
    page.locator(TRIGGER).click()
    page.locator('.custom-dropdown-item[data-value="regulatory"]').click()
    assert page.evaluate("localStorage.getItem('sfda-search-scope')") == "regulatory"

    page.locator(TRIGGER).click()
    page.locator('.custom-dropdown-item[data-value="all"]').click()
    assert page.evaluate("localStorage.getItem('sfda-search-scope')") is None


def test_keyboard_selection_also_persists(authenticated_page: Page):
    page = authenticated_page
    page.locator(TRIGGER).focus()
    page.keyboard.press("Enter")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")

    assert page.evaluate("localStorage.getItem('sfda-search-scope')") == "regulatory"


def test_an_unrecognised_saved_value_is_ignored_and_stays_on_all(
    authenticated_page: Page,
):
    """A failed or stale read must never silently narrow which corpus a
    question is answered from — the safe direction is always 'all'."""
    page = authenticated_page
    page.evaluate("localStorage.setItem('sfda-search-scope', 'not-a-real-category')")
    page.reload()
    page.locator("#authenticated-view").wait_for(state="visible")

    expect(page.locator(TRIGGER)).to_have_attribute("data-value", "all")
