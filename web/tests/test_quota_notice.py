"""The daily-allowance notice actually renders.

It never did. `showQuotaNotice` passed `'history-notice quota-notice'` to
`DOMCache.createElement` as ONE class token, and `classList.add` throws on a
token containing a space — so on every 429 `quota_exhausted` the notice was
never drawn, and the throw escaped `processChatRequestInternal`'s catch before
the question went back into the composer. The reader's bubble was removed and
nothing said why. Server-side tests covered the refusal thoroughly; nothing in
the browser suite ever rendered the notice, which is how it shipped.
"""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser

EXHAUSTED = {
    "error": "quota_exhausted",
    "used": 200,
    "limit": 200,
    "remaining": 0,
    "resets_at": "2026-09-12T00:00:00Z",
}


def test_an_exhausted_allowance_is_explained_and_the_question_is_kept(authenticated_page: Page):
    page = authenticated_page
    page.context.route(
        "**/api/chat/stream",
        lambda route: route.fulfill(
            status=429, content_type="application/json", body=json.dumps(EXHAUSTED)
        ),
    )

    page.locator("#query-input").fill("What must the PSSF contain?")
    page.locator("#send-button").click()

    notice = page.locator("#quota-notice")
    expect(notice).to_be_visible()
    expect(notice).to_contain_text("Today's questions are used up.")
    expect(notice).to_contain_text("all 200 of today's questions")
    # The refused question is not left as an unanswered turn, and it is not lost.
    expect(page.locator(".user-message")).to_have_count(0)
    expect(page.locator("#query-input")).to_have_value("What must the PSSF contain?")
