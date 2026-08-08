"""Browser coverage for the composer's scope selector.

It replaces a native ``<select>``, so it has to earn what a native select gives
away: keyboard operation, and never stranding focus. Closing the menu hides it
with ``visibility: hidden``, which does NOT move focus — so a click outside used
to leave keyboard and screen-reader users focused on an option inside an
invisible menu, with no way back except Tab.
"""

from playwright.sync_api import Page, expect


def test_scope_selector_opens_and_selects_with_the_keyboard(authenticated_page: Page):
    trigger = authenticated_page.locator("#query-category")
    trigger.focus()
    trigger.press("Enter")

    menu = authenticated_page.locator(".custom-dropdown-menu")
    expect(menu).to_be_visible()
    expect(trigger).to_have_attribute("aria-expanded", "true")

    # Focus lands on the selected option, so ArrowDown moves to the next one.
    authenticated_page.keyboard.press("ArrowDown")
    authenticated_page.keyboard.press("Enter")

    expect(menu).to_be_hidden()
    expect(trigger).to_have_attribute("data-value", "regulatory")
    expect(authenticated_page.locator("#query-category-hidden")).to_have_value(
        "regulatory"
    )
    # The hidden select is what the chat request reads, so the two must agree.
    expect(trigger.locator(".dropdown-text")).to_have_text("Regulatory")


def test_escape_returns_focus_to_the_trigger(authenticated_page: Page):
    """A keyboard close has no other landing place, so it must be explicit."""
    trigger = authenticated_page.locator("#query-category")
    trigger.focus()
    trigger.press("Enter")
    expect(authenticated_page.locator(".custom-dropdown-menu")).to_be_visible()

    authenticated_page.keyboard.press("Escape")
    expect(authenticated_page.locator(".custom-dropdown-menu")).to_be_hidden()
    expect(trigger).to_be_focused()


def test_keyboard_selection_returns_focus_to_the_trigger(authenticated_page: Page):
    trigger = authenticated_page.locator("#query-category")
    trigger.focus()
    trigger.press("Enter")
    authenticated_page.keyboard.press("ArrowDown")
    authenticated_page.keyboard.press("Enter")

    expect(authenticated_page.locator(".custom-dropdown-menu")).to_be_hidden()
    expect(trigger).to_be_focused()


def test_closing_never_strands_focus_inside_the_hidden_menu(authenticated_page: Page):
    """The invariant that matters.

    Deliberately NOT "focus returns to the trigger on click-outside": a click
    moves focus to what was clicked, and forcing it back to the trigger would
    fight the browser and land the reader somewhere they did not ask to be.
    What must never happen is focus left on an option inside a menu that is now
    `visibility: hidden`.
    """
    trigger = authenticated_page.locator("#query-category")
    trigger.focus()
    trigger.press("Enter")
    expect(authenticated_page.locator(".custom-dropdown-menu")).to_be_visible()

    authenticated_page.locator("#messages").click(position={"x": 5, "y": 5})
    expect(authenticated_page.locator(".custom-dropdown-menu")).to_be_hidden()

    stranded = authenticated_page.evaluate(
        "() => { const menu = document.querySelector('.custom-dropdown-menu');"
        "return menu.contains(document.activeElement); }"
    )
    assert not stranded, "focus was left inside the hidden scope menu"


def test_scope_selector_reports_its_value_to_assistive_tech(authenticated_page: Page):
    """The visible "Search in:" label moved into the accessible name when the
    control was welded into the composer; it must survive a selection."""
    trigger = authenticated_page.locator("#query-category")
    expect(trigger).to_have_attribute("aria-label", "Search in: All Categories")

    trigger.click()
    authenticated_page.locator('.custom-dropdown-item[data-value="veterinary"]').click()

    expect(trigger).to_have_attribute("aria-label", "Search in: Veterinary Medicines")
    expect(trigger).to_have_attribute("aria-expanded", "false")


def test_every_icon_is_inline_svg(authenticated_page: Page):
    """No icon webfont ships any more, so a leftover <i class="bi"> would render
    as nothing at all rather than as a wrong glyph."""
    counts = authenticated_page.evaluate(
        "() => ({ svg: document.querySelectorAll('svg.icon').length,"
        " font: document.querySelectorAll('i.bi, [class*=\" bi-\"]').length })"
    )
    assert counts["font"] == 0, "bootstrap-icons markup survived the migration"
    assert counts["svg"] > 10, f"expected inline icons, found {counts['svg']}"


def test_every_module_url_carries_the_current_version(authenticated_page: Page):
    """A static `import` cannot carry a cache-buster, so an import map supplies
    one. Without it a returning user can pair a fresh template with modules from
    a previous deploy.

    Compared against the server's own constant rather than a literal: a test
    that has to be edited on every asset bump is a test that gets deleted, and
    a bare `?v=` substring check would accept an empty or mixed version.
    """
    from web.api.app import ASSET_VERSION

    versions = authenticated_page.evaluate(
        """() => performance.getEntriesByType('resource')
             .map(e => e.name)
             .filter(n => n.includes('/static/js/'))
             .map(n => new URL(n).searchParams.get('v'))"""
    )
    assert versions, "no local module requests were recorded at all"
    assert set(versions) == {ASSET_VERSION}, (
        f"module URLs should all be {ASSET_VERSION!r}, got {sorted(set(versions), key=str)}"
    )
