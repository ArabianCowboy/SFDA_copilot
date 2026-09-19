"""Marketing consent on /account: instant-apply toggle, withdrawal as easy
as granting (docs/profile-refactor-plan.md §12.3, Step 6).

Granting goes through `POST /account/api/consent/grant`, which stamps the
policy version server-side — the browser sends no version at all. Withdrawing
goes browser-direct to the `update_own_marketing_consent` RPC, which stays
reachable for a disabled account. These tests drive the toggle and observe
both halves: the grant bodies intercepted at the network layer (the same
technique `test_signup_identity_capture.py`'s `signup_capture` uses), and
the withdrawal in `window.__supabaseState`.

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


@pytest.fixture
def grant_capture(authenticated_page: Page):
    """Every body POSTed to `/account/api/consent/grant` in this test,
    fulfilled as a deterministic success so the toggle's own success path
    still runs exactly as it does against the real route."""
    sent = []

    def capture(route):
        sent.append(route.request.post_data_json)
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"ok":true}',
        )

    authenticated_page.context.route("**/account/api/consent/grant", capture)
    return sent


def test_granting_consent_goes_through_the_server_route_without_a_version(
    authenticated_page: Page, grant_capture
):
    """The version is stamped server-side (PRIVACY_POLICY_VERSION), so the
    browser must not send one — and must not send a user id either, since
    the route derives the owner from the bearer token."""
    page = authenticated_page
    page.goto("/account")

    expect(page.locator("#consent-marketing-toggle")).not_to_be_checked()
    page.locator("#consent-marketing-toggle").check()

    expect(page.locator("#consent-saved-note")).to_be_visible()
    assert len(grant_capture) == 1
    sent = grant_capture[0]
    assert sent["language"] == "en"
    assert sent["surface"] == "account"
    assert "marketing_consent_policy_version" not in sent
    assert "user_id" not in sent
    assert "marketing_consent" not in sent


def test_a_failed_grant_reverts_the_toggle_rather_than_showing_a_false_state(
    authenticated_page: Page,
):
    page = authenticated_page
    page.context.route(
        "**/account/api/consent/grant",
        lambda route: route.fulfill(
            status=503, content_type="application/json", body='{"error":"consent_unavailable"}'
        ),
    )
    page.goto("/account")

    # .click(), not .check(): the app reverts the box synchronously on
    # failure, and .check() asserts the box ENDS UP checked, which this
    # case deliberately does not do.
    page.locator("#consent-marketing-toggle").click()

    expect(page.locator("#consent-error")).to_be_visible()
    expect(page.locator("#consent-marketing-toggle")).not_to_be_checked()


def test_the_clear_age_offer_appears_only_once_granted(authenticated_page: Page, grant_capture):
    page = authenticated_page
    page.goto("/account")

    expect(page.locator("#consent-clear-age-row")).to_be_hidden()
    page.locator("#consent-marketing-toggle").check()
    expect(page.locator("#consent-saved-note")).to_be_visible()

    expect(page.locator("#consent-clear-age-row")).to_be_visible()


def test_withdrawing_consent_calls_the_withdrawal_rpc_never_rate_limited(
    authenticated_page: Page, grant_capture
):
    """No Flask route sits in front of the withdrawal — it is a direct
    browser->Postgres RPC — so there is nothing to rate-limit and nothing
    to wait for."""
    page = authenticated_page
    page.goto("/account")
    page.locator("#consent-marketing-toggle").check()
    expect(page.locator("#consent-saved-note")).to_be_visible()

    page.locator("#consent-marketing-toggle").uncheck()

    expect(page.locator("#consent-saved-note")).to_be_visible()
    assert page.evaluate("window.__supabaseState.profile.marketing_consent") is False
    assert page.evaluate("window.__supabaseState.lastConsentWithdraw") == {"p_clear_age": False}
    expect(page.locator("#consent-clear-age-row")).to_be_hidden()


def test_withdrawal_offers_to_clear_age_without_requiring_it(
    authenticated_page: Page, grant_capture
):
    """T9: the offer must never become a mandate — declining the clear must
    still let withdrawal succeed and must not touch age at all."""
    page = authenticated_page
    page.goto("/account")
    page.locator("#consent-marketing-toggle").check()
    expect(page.locator("#consent-saved-note")).to_be_visible()

    # Give the account an age worth protecting, then decline the clear.
    page.evaluate("window.__supabaseState.profile.age = 34")
    page.locator("#consent-marketing-toggle").uncheck()
    expect(page.locator("#consent-saved-note")).to_be_visible()

    assert page.evaluate("window.__supabaseState.profile.marketing_consent") is False
    assert page.evaluate("window.__supabaseState.lastConsentWithdraw") == {"p_clear_age": False}
    assert page.evaluate("window.__supabaseState.profile.age") == 34


def test_withdrawal_can_also_clear_age_when_offered(authenticated_page: Page, grant_capture):
    page = authenticated_page
    page.goto("/account")
    page.locator("#consent-marketing-toggle").check()
    expect(page.locator("#consent-saved-note")).to_be_visible()

    page.locator("#consent-clear-age").check()
    page.locator("#consent-marketing-toggle").uncheck()
    expect(page.locator("#consent-saved-note")).to_be_visible()

    assert page.evaluate("window.__supabaseState.lastConsentWithdraw") == {"p_clear_age": True}
    assert page.evaluate("window.__supabaseState.profile.age") is None
    # The offer's own checkbox resets, so a later re-grant/withdraw cycle
    # does not silently carry an old "also clear my age" choice forward.
    expect(page.locator("#consent-clear-age")).not_to_be_checked()


def test_a_failed_withdrawal_reverts_the_toggle_rather_than_showing_a_false_state(
    authenticated_page: Page, grant_capture
):
    page = authenticated_page
    page.goto("/account")
    page.locator("#consent-marketing-toggle").check()
    expect(page.locator("#consent-saved-note")).to_be_visible()

    # Fail the RPC leg only: the grant above already succeeded.
    page.evaluate("window.__supabaseState.consentWithdrawError = 'network down'")
    page.locator("#consent-marketing-toggle").click()

    expect(page.locator("#consent-error")).to_be_visible()
    expect(page.locator("#consent-marketing-toggle")).to_be_checked()
