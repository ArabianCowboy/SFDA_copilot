"""Browser-level coverage for the main application flows."""

import re

from playwright.sync_api import Page, expect


def test_landing_page_layout(browser_page: Page):
    browser_page.goto("/")

    expect(browser_page.locator("h1", has_text="SFDA Copilot")).to_be_visible()
    expect(browser_page.locator("#auth-button-main")).to_be_visible()
    expect(browser_page.locator("#authModal")).to_be_hidden()

    browser_page.locator("#auth-button-main").click()
    expect(browser_page.locator("#authModal")).to_be_visible()
    expect(browser_page.locator("#login-email")).to_be_visible()
    expect(browser_page.locator("#login-password")).to_be_visible()


def test_login_and_logout_flow(authenticated_page: Page):
    expect(authenticated_page.locator("#user-status")).to_have_text(
        "Logged in as: test@example.com"
    )
    expect(authenticated_page.locator("#profile-button")).to_be_visible()
    expect(authenticated_page.locator("#logout-button")).to_be_visible()

    authenticated_page.locator("#logout-button").click()

    expect(authenticated_page.locator("#unauthenticated-view")).to_be_visible()
    expect(authenticated_page.locator("#auth-button-main")).to_be_visible()


def test_a_slow_identity_check_does_not_reveal_admin_after_logout(browser_page: Page):
    """The reader signs out while /api/identity is still in flight for the
    account they just left. Its eventual answer — even a true one — must not
    apply itself to the signed-out view that replaced the one that asked.

    The route handler never blocks: it stores the intercepted request and
    returns immediately, deferring `route.fulfill()` to be called later from
    the test's own control flow. Playwright's sync API runs route handlers
    through the same dispatcher that every other page call goes through, so a
    handler that blocks a thread waiting on a signal — the first version of
    this test did exactly that — stalls every subsequent Playwright call
    (`wait_for`, `click`, `expect`) until the handler returns, which defeats
    the point of holding the response open at all: everything else in the
    test queues up behind it instead of running concurrently with it. Not
    blocking inside the handler is the documented way to hold a response open
    (https://playwright.dev/python/docs/network#modify-requests), and it
    sidesteps the question of exactly how blocked handlers interact with the
    dispatcher rather than depending on the answer.
    """
    held_routes = []
    browser_page.route("**/api/identity", lambda route: held_routes.append(route))

    with browser_page.expect_request("**/api/identity"):
        browser_page.goto("/")
        browser_page.locator("#auth-button-main").click()
        browser_page.locator("#login-email").fill("test@example.com")
        browser_page.locator("#login-password").fill("password123")
        browser_page.locator("#login-form").evaluate("(form) => form.requestSubmit()")

    # The request has been observed and is being held, unfulfilled, in
    # `held_routes` — genuinely in flight, not resolved yet.
    expect(browser_page.locator("#logout-button")).to_be_visible()
    browser_page.locator("#logout-button").click()
    expect(browser_page.locator("#unauthenticated-view")).to_be_visible()

    # Only now let the stale check's answer arrive.
    assert held_routes, "no /api/identity request was intercepted"
    for route in held_routes:
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"user_id":"test-user-id","email":"test@example.com",'
            '"role":"admin","tier":"free","is_admin":true}',
        )

    # Polls until it matches or its own timeout, rather than a fixed sleep
    # guessing how long the now-unblocked response takes to be processed.
    # Checked on the element's own class rather than `to_be_hidden()`: the
    # sidebar it lives in is itself hidden once signed out, which would make
    # that assertion pass for the wrong reason — a bug that popped `d-none`
    # off #admin-button would go undetected as long as its ancestor view
    # stayed hidden too.
    expect(browser_page.locator("#admin-button")).to_have_class(
        re.compile(r"(?:^|\s)d-none(?:\s|$)")
    )


def test_login_failure_is_presented_by_handler(browser_page: Page):
    browser_page.goto("/")
    browser_page.locator("#auth-button-main").click()
    browser_page.locator("#login-email").fill("fail@example.com")
    browser_page.locator("#login-password").fill("password123")
    browser_page.locator("#login-form").evaluate("(form) => form.requestSubmit()")

    expect(browser_page.locator("#auth-error")).to_be_visible()
    expect(browser_page.locator("#auth-error")).to_contain_text(
        "Incorrect email or password."
    )


def test_faq_and_chat_success(authenticated_page: Page):
    faq_button = authenticated_page.locator(".faq-button").first
    expect(faq_button).to_be_visible()
    faq_button.click()

    expect(authenticated_page.locator(".user-message")).to_have_count(1)
    expect(authenticated_page.get_by_text("Mock regulatory answer")).to_be_visible()
    expect(authenticated_page.get_by_text("Next question?")).to_be_visible()


def test_chat_failure_is_handled(authenticated_page: Page):
    # Both endpoints: the client prefers /api/chat/stream and falls back to
    # /api/chat, so overriding only one would leave the other succeeding.
    # A 503 arrives before the first frame, so it is a normal JSON error
    # response rather than an in-band `error` event.
    for pattern in ("**/api/chat/stream", "**/api/chat"):
        authenticated_page.route(
            pattern,
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body='{"error":"Search unavailable"}',
            ),
        )

    authenticated_page.locator("#query-input").fill("What is required?")
    authenticated_page.locator("#send-button").click()

    expect(
        authenticated_page.get_by_text(
            "Sorry, I encountered an error while processing your request."
        )
    ).to_be_visible()
    expect(authenticated_page.locator("#toast")).to_contain_text(
        "Failed to send message."
    )


def test_chat_cancellation_does_not_surface_as_failure(authenticated_page: Page):
    authenticated_page.evaluate(
        """
        window.__originalFetch = window.fetch;
        window.fetch = (url, options = {}) => {
          if (String(url).includes('/api/chat')) {
            return new Promise((resolve, reject) => {
              const abort = () => reject(
                new DOMException('The operation was aborted.', 'AbortError')
              );
              if (options.signal?.aborted) abort();
              else options.signal?.addEventListener('abort', abort, { once: true });
            });
          }
          return window.__originalFetch(url, options);
        };
        """
    )

    authenticated_page.locator("#query-input").fill("Cancel this request")
    authenticated_page.locator("#send-button").click()
    expect(authenticated_page.locator("#send-button")).to_have_attribute(
        "aria-label", "Cancel message"
    )
    authenticated_page.locator("#send-button").click()

    expect(authenticated_page.locator("#toast")).to_have_text(
        "Chat request cancelled."
    )
    expect(
        authenticated_page.get_by_text(
            "Sorry, I encountered an error while processing your request."
        )
    ).to_have_count(0)
    expect(authenticated_page.locator("#robot-status-text")).to_have_text(
        "Ready to help"
    )
    expect(authenticated_page.locator("#send-button")).to_have_attribute(
        "aria-label", "Send message"
    )


def test_missing_session_token_prompts_for_login(authenticated_page: Page):
    authenticated_page.evaluate("window.__supabaseState.user = null")
    authenticated_page.locator("#query-input").fill("Need authentication")
    authenticated_page.locator("#send-button").click()

    expect(authenticated_page.locator("#authModal")).to_be_visible()
    expect(authenticated_page.locator("#toast")).to_have_text(
        "Please log in to chat with the AI."
    )
    expect(
        authenticated_page.get_by_text(
            "Sorry, I encountered an error while processing your request."
        )
    ).to_have_count(0)


def test_session_lookup_error_is_not_presented_as_chat_failure(
    authenticated_page: Page,
):
    authenticated_page.evaluate(
        "window.__supabaseState.sessionError = 'Session service unavailable'"
    )
    authenticated_page.locator("#query-input").fill("Check my session")
    authenticated_page.locator("#send-button").click()

    expect(authenticated_page.locator("#authModal")).to_be_hidden()
    expect(authenticated_page.locator("#toast")).to_have_text(
        "Unable to verify your session. Please try again."
    )
    expect(
        authenticated_page.get_by_text(
            "Sorry, I encountered an error while processing your request."
        )
    ).to_have_count(0)
    expect(authenticated_page.locator("#robot-status-text")).to_have_text(
        "Ready to help"
    )


def test_testing_mode_bypasses_auth(browser_page: Page):
    browser_page.goto("/?testing=true")

    expect(browser_page.locator("#authenticated-view")).to_be_visible()
    expect(browser_page.locator("#user-status")).to_have_text(
        "Logged in as: test@example.com"
    )


def test_responsive_landing_layout(browser_page: Page):
    browser_page.set_viewport_size({"width": 375, "height": 667})
    browser_page.goto("/")

    expect(browser_page.locator("#auth-button-main")).to_be_visible()
    expect(browser_page.locator("#landing-robot")).to_be_visible()
