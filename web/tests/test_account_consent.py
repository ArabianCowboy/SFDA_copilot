"""Marketing consent on /account: instant-apply toggle, withdrawal as easy
as granting, never rate-limited (docs/profile-refactor-plan.md §12.3,
Step 6).

Every test grants then (where relevant) withdraws within ONE page session
rather than seeding a starting profile before navigation: the Supabase
mock's `state.profile` is module-scoped and re-seeded fresh on every
document load (conftest.py's `createClient()`), so a value written before
`goto()` does not survive the navigation — this suite works with that
architecture rather than fighting it.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


def test_granting_consent_sends_the_policy_context(authenticated_page: Page):
    page = authenticated_page
    page.goto("/account")

    expect(page.locator("#consent-marketing-toggle")).not_to_be_checked()
    page.locator("#consent-marketing-toggle").check()

    expect(page.locator("#consent-saved-note")).to_be_visible()
    sent = page.evaluate("window.__supabaseState.profile")
    assert sent["marketing_consent"] is True
    assert sent["marketing_consent_language"] == "en"
    assert sent["marketing_consent_surface"] == "account"
    # The exact draft string is app.py's own concern; this only proves SOME
    # version travelled, matching the guard trigger's own requirement.
    assert sent["marketing_consent_policy_version"]


def test_the_clear_age_offer_appears_only_once_granted(authenticated_page: Page):
    page = authenticated_page
    page.goto("/account")

    expect(page.locator("#consent-clear-age-row")).to_be_hidden()
    page.locator("#consent-marketing-toggle").check()
    expect(page.locator("#consent-saved-note")).to_be_visible()

    expect(page.locator("#consent-clear-age-row")).to_be_visible()


def test_withdrawing_consent_is_one_click_never_rate_limited(authenticated_page: Page):
    """No Flask route sits in front of this write — it is the same
    browser->Postgres path the Identity form's own fields use — so there is
    nothing to rate-limit and nothing to wait for."""
    page = authenticated_page
    page.goto("/account")
    page.locator("#consent-marketing-toggle").check()
    expect(page.locator("#consent-saved-note")).to_be_visible()

    page.locator("#consent-marketing-toggle").uncheck()

    expect(page.locator("#consent-saved-note")).to_be_visible()
    assert page.evaluate("window.__supabaseState.profile.marketing_consent") is False
    expect(page.locator("#consent-clear-age-row")).to_be_hidden()


def test_withdrawal_offers_to_clear_age_without_requiring_it(authenticated_page: Page):
    """T9: the offer must never become a mandate — declining the clear must
    still let withdrawal succeed and must not touch age at all."""
    page = authenticated_page
    page.goto("/account")
    page.locator("#consent-marketing-toggle").check()
    expect(page.locator("#consent-saved-note")).to_be_visible()

    # Decline the clear (the checkbox stays unticked).
    page.locator("#consent-marketing-toggle").uncheck()
    expect(page.locator("#consent-saved-note")).to_be_visible()

    assert page.evaluate("window.__supabaseState.profile.marketing_consent") is False
    last_update = page.evaluate("window.__supabaseState.lastProfileUpdate")
    assert "age" not in last_update


def test_withdrawal_can_also_clear_age_when_offered(authenticated_page: Page):
    page = authenticated_page
    page.goto("/account")
    page.locator("#consent-marketing-toggle").check()
    expect(page.locator("#consent-saved-note")).to_be_visible()

    page.locator("#consent-clear-age").check()
    page.locator("#consent-marketing-toggle").uncheck()
    expect(page.locator("#consent-saved-note")).to_be_visible()

    last_update = page.evaluate("window.__supabaseState.lastProfileUpdate")
    assert last_update["age"] is None
    # The offer's own checkbox resets, so a later re-grant/withdraw cycle
    # does not silently carry an old "also clear my age" choice forward.
    expect(page.locator("#consent-clear-age")).not_to_be_checked()


def test_a_failed_save_reverts_the_toggle_rather_than_showing_a_false_state(authenticated_page: Page):
    page = authenticated_page
    page.goto("/account")
    page.evaluate("window.__supabaseState.profileUpdateError = 'network down'")

    # .click(), not .check(): the app reverts the box synchronously on
    # failure, and .check() asserts the box ENDS UP checked, which this
    # case deliberately does not do.
    page.locator("#consent-marketing-toggle").click()

    expect(page.locator("#consent-error")).to_be_visible()
    expect(page.locator("#consent-marketing-toggle")).not_to_be_checked()
