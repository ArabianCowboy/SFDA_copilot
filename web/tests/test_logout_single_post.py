"""One sign-out from this tab posts `/auth/logout` exactly once.

`Services.logout` always posts first — before the testing-mode return and before
anything that can throw — so every path through the logout button and through
`endRecovery` has already posted by the time it continues. The `SIGNED_OUT`
listener posts only for a sign-out this tab did not start (a revocation, a
failed refresh, another tab), because on those paths nothing else ends the
Flask session. These tests count the requests per press.

Two event timings are covered on purpose. supabase-js 2.74.0 AWAITS every
subscriber inside `signOut()` (`_removeSession` -> `_notifyAllSubscribers`); the
conftest mock fires `SIGNED_OUT` on a microtask after `signOut()` returns. The
`__mockSignOutAwaitsSubscribers` knob switches the mock to the real ordering.

The settle after the signed-out view is deliberate: the listener's POST is not
awaited, so it can leave after the view has already changed.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

SETTLE_MS = 500
READER = '{"id":"test-user-id","email":"test@example.com"}'


@pytest.fixture(params=["production", "mock"])
def timing(request) -> str:
    """`production` awaits the listener inside signOut, as supabase-js does."""
    return request.param


def _record_logout_posts(page: Page) -> list[str]:
    posts: list[str] = []

    def record(request) -> None:
        if request.method == "POST" and urlparse(request.url).path == "/auth/logout":
            posts.append(request.url)

    page.on("request", record)
    return posts


def _set_timing(page: Page, timing: str) -> None:
    page.evaluate(
        f"() => {{ window.__mockSignOutAwaitsSubscribers = {str(timing == 'production').lower()}; }}"
    )


def _press_logout(page: Page) -> None:
    page.locator("#logout-button").locator("visible=true").first.click()
    expect(page.locator("#unauthenticated-view")).to_be_visible()
    page.wait_for_timeout(SETTLE_MS)


def _revoke(page: Page) -> None:
    """A SIGNED_OUT this tab did not cause, the pattern test_signed_out_route.py uses."""
    page.evaluate(
        "() => {"
        "  const s = window.__supabaseState;"
        "  s.user = null;"
        "  localStorage.removeItem('__mock_supabase_user');"
        "  return s.authCallback('SIGNED_OUT', null);"
        "}"
    )


def _sign_in(page: Page) -> None:
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill("test@example.com")
    page.locator("#login-password").fill("password123")
    page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#authenticated-view").wait_for(state="visible")
    page.locator("#authModal").wait_for(state="hidden")


def _open_live_recovery(page: Page, timing: str) -> None:
    """The recovery form over a real (mocked) recovery session, not the demo."""
    page.goto("/")
    page.evaluate(f"() => localStorage.setItem('__mock_supabase_user', '{READER}')")
    page.goto("/?recovery=1")
    expect(page.locator("#recovery-form")).to_be_visible()
    _set_timing(page, timing)


# ── The logout button ─────────────────────────────────────────────────────────


def test_logout_button_posts_once(authenticated_page: Page, timing: str) -> None:
    """Cases (a) and (b): the normal sign-out, under both event timings."""
    page = authenticated_page
    _set_timing(page, timing)
    posts = _record_logout_posts(page)
    _press_logout(page)
    assert len(posts) == 1


def test_logout_button_posts_once_in_the_demo(browser_page: Page) -> None:
    """Case (c): `?testing=true` returns before signOut, so no SIGNED_OUT arrives."""
    page = browser_page
    page.goto("/?testing=true")
    expect(page.locator("#authenticated-view")).to_be_visible()
    posts = _record_logout_posts(page)
    _press_logout(page)
    assert len(posts) == 1


def test_logout_button_posts_once_when_sign_out_fails(authenticated_page: Page) -> None:
    """Case (d): a failed revocation keeps the session and emits no SIGNED_OUT."""
    page = authenticated_page
    page.evaluate("() => { window.__supabaseState.signOutError = 'network down'; }")
    posts = _record_logout_posts(page)
    _press_logout(page)
    assert len(posts) == 1


@pytest.mark.parametrize(
    "setup",
    [
        # sessionMissing: the session is gone without an event having said so.
        "() => { window.__supabaseState.user = null; }",
        # getSession errors, so Services.logout throws before signOut.
        "() => { window.__supabaseState.sessionError = 'lock contention'; }",
        # No client at all, so Services.logout throws before getSession.
        "async () => {"
        "  const { Services } = await import('/static/js/modules/services.js');"
        "  Services.supabase = null;"
        "}",
    ],
    ids=["session-missing", "get-session-error", "no-client"],
)
def test_logout_button_posts_once_when_no_sign_out_event_arrives(
    authenticated_page: Page, setup: str
) -> None:
    """The remaining paths of invariant 1, each of which skips signOut."""
    page = authenticated_page
    page.evaluate(setup)
    posts = _record_logout_posts(page)
    _press_logout(page)
    assert len(posts) == 1


# ── endRecovery ───────────────────────────────────────────────────────────────


def test_recovery_cancel_posts_once(browser_page: Page, timing: str) -> None:
    """Case (e): cancel signs the recovery session out, and its SIGNED_OUT
    reaches the listener's recovery branch while endRecovery is still running."""
    page = browser_page
    _open_live_recovery(page, timing)
    posts = _record_logout_posts(page)
    page.locator("#recovery-cancel").click()
    expect(page.locator("#unauthenticated-view")).to_be_visible()
    page.wait_for_timeout(SETTLE_MS)
    assert len(posts) == 1


def test_recovery_cancel_posts_once_in_the_demo(browser_page: Page) -> None:
    page = browser_page
    page.goto("/?testing=true&recovery=1")
    expect(page.locator("#recovery-form")).to_be_visible()
    posts = _record_logout_posts(page)
    page.locator("#recovery-cancel").click()
    expect(page.locator("#unauthenticated-view")).to_be_visible()
    page.wait_for_timeout(SETTLE_MS)
    assert len(posts) == 1


def test_recovery_submit_posts_once(browser_page: Page, timing: str) -> None:
    """The other way into endRecovery: a saved password signs out globally."""
    page = browser_page
    _open_live_recovery(page, timing)
    posts = _record_logout_posts(page)
    page.locator("#recovery-password").fill("ValidPass1")
    page.locator("#recovery-password-confirm").fill("ValidPass1")
    page.locator("#recovery-form").evaluate("(f) => f.requestSubmit()")
    expect(page.locator("#authModal")).to_be_visible()
    page.wait_for_timeout(SETTLE_MS)
    assert page.evaluate("() => window.__supabaseState.lastUserUpdate?.password") == "ValidPass1"
    assert len(posts) == 1


# ── Sign-outs this tab did not cause ──────────────────────────────────────────


def test_a_revocation_posts_once_from_the_listener(authenticated_page: Page) -> None:
    """Case (f): nothing but the listener ends the Flask session here."""
    page = authenticated_page
    posts = _record_logout_posts(page)
    _revoke(page)
    expect(page.locator("#unauthenticated-view")).to_be_visible()
    page.wait_for_timeout(SETTLE_MS)
    assert len(posts) == 1


def test_a_revocation_during_recovery_posts_once(browser_page: Page) -> None:
    """The recovery branch's SIGNED_OUT, when endRecovery did not cause it."""
    page = browser_page
    _open_live_recovery(page, "mock")
    posts = _record_logout_posts(page)
    _revoke(page)
    expect(page.locator("#unauthenticated-view")).to_be_visible()
    page.wait_for_timeout(SETTLE_MS)
    assert len(posts) == 1


def test_the_suppression_does_not_outlive_its_sign_out(
    authenticated_page: Page, timing: str
) -> None:
    """Case (g): sign out, sign back in, get revoked — the revocation still posts."""
    page = authenticated_page
    _set_timing(page, timing)
    posts = _record_logout_posts(page)
    _press_logout(page)
    assert len(posts) == 1

    _sign_in(page)
    _revoke(page)
    expect(page.locator("#unauthenticated-view")).to_be_visible()
    page.wait_for_timeout(SETTLE_MS)
    assert len(posts) == 2


def test_the_suppression_does_not_outlive_a_sign_out_that_threw(
    authenticated_page: Page,
) -> None:
    """The throw path must clear it too: the session survived the failed
    sign-out, and its later revocation is a SIGNED_OUT nobody else posts for."""
    page = authenticated_page
    page.evaluate("() => { window.__supabaseState.signOutError = 'network down'; }")
    posts = _record_logout_posts(page)
    _press_logout(page)
    assert len(posts) == 1

    page.evaluate("() => { window.__supabaseState.signOutError = null; }")
    _revoke(page)
    page.wait_for_timeout(SETTLE_MS)
    assert len(posts) == 2
