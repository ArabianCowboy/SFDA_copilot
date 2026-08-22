"""The durable-history notice: told once, per reader, and it stays told.

This is the disclosure the feature owed from the moment hydration shipped. Up to
step 6 the transcript died with the tab, so saying nothing was defensible;
afterwards a conversation follows the reader across a reload, a language toggle
and a different device, and silence became a claim that is no longer true.

Four properties are worth a test because none can be read off the code:

* it survives a `New chat`, which is the control a reader reaches for when they
  want the conversation gone — the exact moment the disclosure is most relevant
  and the moment a naive `clearTranscript` would delete it;
* dismissal is per READER, not per browser, because a shared machine is the
  ordinary case here;
* dismissal survives a reload, or the notice is nagware rather than a notice;
* and the copy names exactly the controls that exist — which in step 8 became
  an assertion that it DOES name the delete, having been an assertion that it
  did not. See that test for why the inversion is the promise being kept.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


NOTICE = "#history-notice"


def _sign_in(page: Page, email: str = "test@example.com") -> None:
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill(email)
    page.locator("#login-password").fill("password123")
    page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#authenticated-view").wait_for(state="visible")


def test_the_notice_appears_for_a_signed_in_reader(browser_page: Page):
    """The whole point of the step, in one assertion."""
    page = browser_page
    page.goto("/")
    _sign_in(page)

    expect(page.locator(NOTICE)).to_be_visible()
    expect(page.locator(NOTICE)).to_contain_text("saved to your account")


def test_the_notice_is_not_shown_before_anyone_signs_in(browser_page: Page):
    """It is about an account. Over the landing view it would be addressing
    nobody — and would still be on screen for whoever signs in next."""
    page = browser_page
    page.goto("/")
    page.locator("#auth-button-main").wait_for(state="visible")

    expect(page.locator(NOTICE)).to_have_count(0)


def test_dismissing_it_survives_a_reload(browser_page: Page):
    """Otherwise it is nagware, and a notice a reader learns to click away
    without reading is a notice that has stopped working."""
    page = browser_page
    page.goto("/")
    _sign_in(page)
    expect(page.locator(NOTICE)).to_be_visible()

    page.locator(".history-notice-dismiss").click()
    expect(page.locator(NOTICE)).to_have_count(0)

    # The Supabase double now persists its session the way the real client
    # does (`services.js:131-149`), so a reload comes back already signed in —
    # no `_sign_in` call here. That is what makes this a reload rather than a
    # second sign-in, and the dismissal key is `localStorage`-backed
    # (`ui.js:101-102`) so it never depended on re-authenticating anyway.
    page.reload()
    page.locator("#authenticated-view").wait_for(state="visible")

    expect(page.locator(NOTICE)).to_have_count(0)


def test_new_chat_does_not_wipe_the_notice(browser_page: Page):
    """The sharpest case, and the reason `isTranscriptTurn` exists.

    `clearTranscript` removes everything in `#messages` that is a turn. The
    notice lives there so it reads as a preface to the conversation rather than
    as chrome about the page — which means a predicate that forgets it deletes
    the disclosure at precisely the moment the reader is exercising the control
    it is telling them about: *New chat does not delete your saved chats.*
    """
    page = browser_page
    page.goto("/")
    _sign_in(page)
    expect(page.locator(NOTICE)).to_be_visible()

    page.locator("#query-input").fill("What must the PSSF contain?")
    page.locator("#send-button").click()
    expect(page.locator(".chatbot-message")).to_have_count(1)

    page.locator(".new-chat-btn").locator("visible=true").first.click()

    expect(page.locator(".chatbot-message")).to_have_count(0)
    expect(page.locator(NOTICE)).to_be_visible()


def test_a_second_reader_in_the_same_tab_sees_their_own_notice(browser_page: Page):
    """Dismissal is an acknowledgement by a person, not a browser setting.

    The app lives at "/" and `AuthView` only toggles `d-none`, so a sign-out
    followed by a sign-in reloads nothing. A notice keyed to the browser would
    treat reader A's dismissal as reader B having been told — on a shared
    workstation, which is the ordinary case for this product.
    """
    page = browser_page
    page.goto("/")
    _sign_in(page)
    page.locator(".history-notice-dismiss").click()
    expect(page.locator(NOTICE)).to_have_count(0)

    page.evaluate(
        "() => window.__supabaseState.authCallback"
        "  && window.__supabaseState.authCallback('SIGNED_OUT', null)"
    )
    page.evaluate(
        "() => {"
        "  const session = { access_token: 'fake_token',"
        "    user: { id: 'reader-b-id', email: 'reader-b@example.com' } };"
        "  window.__supabaseState.user = session.user;"
        "  window.__supabaseState.authCallback"
        "    && window.__supabaseState.authCallback('SIGNED_IN', session);"
        "}"
    )

    expect(page.locator(NOTICE)).to_be_visible()


def test_the_notice_names_the_delete_control_now_that_one_exists(
    browser_page: Page,
):
    """INVERTED IN STEP 8, and the inversion is the point.

    This test used to assert the notice offered NO way to delete a conversation.
    A draft of the copy said "start a new chat, or delete a conversation, to
    clear one" while the RLS DELETE grant existed and nothing called it — no
    route, no client code — so the sentence would have made the notice, written
    to stop the product misleading readers, into the product's newest false
    claim. It was forbidden until a control could honour it.

    Step 8 shipped that control: each sidebar row carries a delete that reaches
    `DELETE /api/chat/sessions/<id>`. So the claim flips, because a disclosure
    that omits the one control a reader would go looking for is misleading by
    omission in the same way the draft was misleading by invention.

    Still asserted on the RENDERED text rather than the catalogue: the notice is
    assembled in JS, and a copy change that never reaches the DOM is a change to
    a string nobody reads.
    """
    page = browser_page
    page.goto("/")
    _sign_in(page)

    notice = page.locator(NOTICE)
    expect(notice).to_be_visible()
    expect(notice).to_contain_text("neither does starting a new chat")
    expect(notice).to_contain_text("delete a conversation from the sidebar")

    # And the warning that is the substantive control.
    expect(notice).to_contain_text("Do not enter patient identifiers")
    expect(notice).to_contain_text("confidential or proprietary")
