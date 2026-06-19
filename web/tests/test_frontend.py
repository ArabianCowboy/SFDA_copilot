"""Browser-level coverage for the main application flows."""

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
    authenticated_page.route(
        "**/api/chat",
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
