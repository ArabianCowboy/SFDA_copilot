"""Two tabs, one browser context: the collision this feature exists to remove.

docs/per-tab-conversation-deep-linking-plan.md §7.2. Two Playwright `Page`s in
one `BrowserContext` — cookies and `localStorage` shared, same signed-in
reader, while `sessionStorage` and the DOM are per-page — is a REAL second
tab. §7.1 built the fixture-level plumbing this file depends on:
`context.route(...)` mocks (conftest.py's `browser_page`) and a Supabase
double that persists its session in real `localStorage` rather than a
page-scoped object, so a second page opened in the context comes back already
signed in, exactly as a second real tab would.

Every test here signs in on the FIRST page only. The second is opened from
`tab_a.context.new_page()` and never touches the login form — if it needed
to, the fixture-level fix this file exists to exercise would not be proven.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from web.tests.conftest import chat_history, route_chat_history, stored_answer

pytestmark = pytest.mark.browser

CONV_A = "aaaaaaaa-0000-4000-8000-00000000000a"
CONV_B = "bbbbbbbb-0000-4000-8000-00000000000b"


def _stream_mock(conversation_id: str, response: str) -> str:
    """One canned exchange, tagged with a specific `conversation_id` — the
    default `SSE_CHAT_MOCK` always answers the same id, which is exactly
    wrong here: proving two tabs hold two conversations needs two different
    ones to tell apart.
    """
    return (
        f'event: meta\ndata: {{"conversation_id":"{conversation_id}","category":"all","lang":"en","model":"mock"}}\n\n'
        'event: stage\ndata: {"stage":"searching"}\n\n'
        'event: stage\ndata: {"stage":"retrieved","count":0}\n\n'
        'event: stage\ndata: {"stage":"drafting"}\n\n'
        f'event: delta\ndata: {{"t":"{response}"}}\n\n'
        'event: stage\ndata: {"stage":"finalizing"}\n\n'
        f'event: final\ndata: {{"response":"{response}","sources":[],"cited":[],"retrieved":0}}\n\n'
        'event: suggestions\ndata: {"suggested_questions":[]}\n\n'
        f'event: done\ndata: {{"finish_reason":"stop","chars":{len(response)}}}\n\n'
    )


def _route_stream(page: Page, conversation_id: str, response: str) -> None:
    """Page-level, not context-level — deliberately, so tab A and tab B can be
    given DIFFERENT canned conversation ids. Playwright checks page-level
    routes before context-level ones, so this wins over `browser_page`'s
    shared default without touching the sibling tab's own override.
    """
    page.route(
        "**/api/chat/stream",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=_stream_mock(conversation_id, response),
        ),
    )


def _ask(page: Page, text: str) -> None:
    before = page.locator(".chatbot-message").count()
    page.locator("#query-input").fill(text)
    page.locator("#send-button").click()
    expect(page.locator(".chatbot-message")).to_have_count(before + 1)


def _sign_in(page: Page) -> None:
    page.goto("/")
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill("test@example.com")
    page.locator("#login-password").fill("password123")
    page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#authenticated-view").wait_for(state="visible")


def test_two_tabs_hold_two_conversations(browser_page: Page):
    """TODO.md's symptom (:793-796), inverted: opening a second tab must NOT
    join whatever the first tab was doing, because there is no shared pointer
    left for it to inherit.
    """
    tab_a = browser_page
    _sign_in(tab_a)

    tab_b = tab_a.context.new_page()
    tab_b.goto("/")
    tab_b.locator("#authenticated-view").wait_for(state="visible")

    _route_stream(tab_a, CONV_A, "Answer in tab A")
    _route_stream(tab_b, CONV_B, "Answer in tab B")

    _ask(tab_a, "Question in tab A")
    _ask(tab_b, "Question in tab B")

    url_a = tab_a.evaluate("() => location.pathname")
    url_b = tab_b.evaluate("() => location.pathname")
    assert url_a != url_b, "both tabs settled on the same conversation"
    assert url_a == f"/c/{CONV_A}"
    assert url_b == f"/c/{CONV_B}"

    expect(tab_a.locator("#messages")).to_contain_text("Answer in tab A")
    expect(tab_a.locator("#messages")).not_to_contain_text("Answer in tab B")
    expect(tab_b.locator("#messages")).to_contain_text("Answer in tab B")
    expect(tab_b.locator("#messages")).not_to_contain_text("Answer in tab A")

    # The step the original report singles out: reload tab A and confirm its
    # own conversation survives, unaffected by whatever tab B is doing.
    route_chat_history(
        tab_a,
        chat_history(
            stored_answer("Question in tab A", "Answer in tab A"),
            conversation_id=CONV_A,
        ),
    )
    tab_a.reload()
    tab_a.wait_for_load_state("load")

    expect(tab_a.locator("#messages")).to_contain_text("Answer in tab A")
    assert tab_a.evaluate("() => location.pathname") == f"/c/{CONV_A}"


def test_a_duplicated_tab_is_a_second_view_of_one_conversation(browser_page: Page):
    """§1.2's claim, pinned as an assertion of intent: a duplicated tab IS a
    second view of the conversation it was duplicated from, because that is
    what the reader asked for by duplicating it — modelled here as a new page
    opened at the same URL, in the same context, Chromium's actual mechanism.

    A future `sessionStorage`-based pointer would fail this test: duplication
    clones `sessionStorage` verbatim, so a pointer stored there would name the
    SAME conversation for the wrong reason (a copied pointer, not a copied
    URL) — and would then diverge the moment either tab navigated, since nothing
    keeps two independent storage entries in sync. This test cannot tell that
    failure apart from success, which is exactly why §1.2 rejects
    `sessionStorage` and this suite has no fixture that could seed it: `browser_page`
    never writes it, and `BrowserContext.storage_state()` does not capture it.
    """
    tab_a = browser_page
    _sign_in(tab_a)

    _route_stream(tab_a, CONV_A, "Answer in the original tab")
    _ask(tab_a, "A question")
    original_url = tab_a.evaluate("() => location.pathname")

    duplicate = tab_a.context.new_page()
    route_chat_history(
        duplicate,
        chat_history(
            stored_answer("A question", "Answer in the original tab"),
            conversation_id=CONV_A,
        ),
    )
    duplicate.goto(original_url)
    duplicate.locator("#authenticated-view").wait_for(state="visible")

    assert duplicate.evaluate("() => location.pathname") == original_url
    expect(duplicate.locator("#messages")).to_contain_text("Answer in the original tab")


def test_a_second_tab_can_generate_while_the_first_is_streaming(browser_page: Page):
    """No 409 for two DIFFERENT conversations — `_InFlightGenerations` keys on
    `(owner, conversation)`, not on the owner alone, precisely so two tabs can
    each hold a legitimate generation at once. Modelled here at the client
    only (the mocks never reach the real hold), which is enough to prove the
    two tabs do not serialise on each other from the browser's side — the
    server-side guarantee is `test_a_second_reader_can_generate_while_the_first_is_streaming`-
    shaped and lives in test_chat_sessions.py.
    """
    tab_a = browser_page
    _sign_in(tab_a)

    tab_b = tab_a.context.new_page()
    tab_b.goto("/")
    tab_b.locator("#authenticated-view").wait_for(state="visible")

    _route_stream(tab_a, CONV_A, "Answer in tab A")
    _route_stream(tab_b, CONV_B, "Answer in tab B")

    tab_a.locator("#query-input").fill("Question in tab A")
    tab_a.locator("#send-button").click()
    tab_b.locator("#query-input").fill("Question in tab B")
    tab_b.locator("#send-button").click()

    expect(tab_a.locator(".chatbot-message")).to_have_count(1)
    expect(tab_b.locator(".chatbot-message")).to_have_count(1)
    expect(tab_a.locator("#toast")).not_to_contain_text("generation")
    expect(tab_b.locator("#toast")).not_to_contain_text("generation")
