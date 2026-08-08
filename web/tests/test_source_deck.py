"""Browser coverage for the source deck and the transcript's follow behaviour.

Every test here exists because a specific defect shipped without one:

* The deck was a shrink-to-fit flex column holding a percentage-width list, so
  above 1440px — where a media query hid the only child giving it width — every
  source card rendered at zero by zero. The cards were in the DOM and invisible,
  on the surface whose whole premise is traceable answers.
* Sources arrive BEFORE the first token. When the deck opened by default, the
  height it added was read as "the reader scrolled away", so the answer streamed
  entirely below the fold while the reader looked at a jump pill.

Both were invisible to the suite because the only chat mock returned
``sources: []``. These use ``sourced_page``, which returns eight.
"""

import re

from playwright.sync_api import Page, expect

from .conftest import SSE_DONE_FRAME, SSE_SOURCES_FRAME, sse_delta


WIDE = {"width": 1600, "height": 900}


def _ask(page: Page, text: str = "What must the PSSF contain?") -> None:
    page.locator("#query-input").fill(text)
    page.locator("#send-button").click()
    # The suggestions frame is the last thing before `done`, so its arrival
    # means the whole exchange has been processed.
    expect(page.locator(".suggested-question-enhanced").first).to_be_visible()


def test_source_cards_render_with_real_size(sourced_page: Page):
    """The 0x0 regression guard. Asserted at a WIDE viewport deliberately."""
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)

    cards = sourced_page.locator(".source-card")
    expect(cards).to_have_count(8)

    first = cards.first
    expect(first).to_be_visible()
    box = first.bounding_box()
    assert box is not None, "source card has no layout box at all"
    assert box["width"] > 200, f"source card collapsed to {box['width']}px wide"
    assert box["height"] > 20, f"source card collapsed to {box['height']}px tall"

    # The deck must not be wider than the reading column it belongs to, and must
    # not be a sliver either.
    deck = sourced_page.locator(".source-deck").bounding_box()
    assert deck and deck["width"] > 400, f"deck is {deck and deck['width']}px wide"


def test_deck_opens_once_the_answer_is_complete(sourced_page: Page):
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)

    expect(sourced_page.locator(".source-deck")).to_have_class(re.compile(r"is-open"))
    expect(sourced_page.locator(".source-deck-summary")).to_have_attribute(
        "aria-expanded", "true"
    )


def test_arriving_sources_do_not_stop_the_transcript_following(sourced_page: Page):
    """The regression that made answers stream off-screen.

    Sources land before the first token and add real height. If that height is
    mistaken for the reader scrolling away, the jump pill goes up and the
    transcript stops following for the rest of the answer.

    The assertion is the END OF THE ANSWER, not the bottom of the scroller:
    the deck expands below the answer once it completes, and the reader is
    meant to be left looking at the last thing they were reading, with the
    sources waiting underneath.
    """
    sourced_page.set_viewport_size({"width": 1280, "height": 700})
    _ask(sourced_page)

    # Never raised: the pill only goes up when following has been given up.
    expect(sourced_page.locator("#jump-to-latest")).to_be_hidden()

    # The closing scroll is smooth, so wait for it to settle rather than
    # sampling mid-animation.
    sourced_page.wait_for_function(
        """() => {
          const c = document.getElementById('messages');
          const content = [...document.querySelectorAll('.chatbot-message .message-content')].pop();
          if (!content) return false;
          const box = c.getBoundingClientRect();
          const answerEnd = content.getBoundingClientRect().bottom;
          /* Two-sided on purpose. Below the fold means following gave up; far
             ABOVE the top means completion jumped the reader past the answer
             into the sources. A one-sided `gap < 40` accepted the second. */
          return answerEnd <= box.bottom + 40 && answerEnd > box.top;
        }""",
        timeout=5000,
    )


def test_scrolling_up_hands_control_back_to_the_reader(sourced_page: Page):
    """The other direction: a real upward scroll must still stop the follow."""
    sourced_page.set_viewport_size({"width": 1280, "height": 700})
    _ask(sourced_page)

    # 'auto', not the CSS smooth default: this is standing in for the reader's
    # own scroll, and the assertion should not race an animation.
    sourced_page.evaluate(
        "() => document.getElementById('messages')"
        ".scrollTo({top: 0, behavior: 'auto'})"
    )
    expect(sourced_page.locator("#jump-to-latest")).to_be_visible()

    sourced_page.locator("#jump-to-latest").click()
    expect(sourced_page.locator("#jump-to-latest")).to_be_hidden()


def test_completion_does_not_yank_a_reader_who_scrolled_up(streaming_page: Page):
    """The invariant: the reader controls the transcript, including at EOF.

    Every other test here drives a stream that Playwright delivers in one
    chunk, so the client drains the whole exchange before the page can be
    touched — none of them can scroll while tokens are arriving, which is the
    only moment this can be observed. This one holds the stream open and
    releases frames around a real mid-stream scroll.
    """
    page = streaming_page
    page.set_viewport_size({"width": 1280, "height": 700})
    page.locator("#query-input").fill("Who controls the scroll?")
    page.locator("#send-button").click()
    page.wait_for_function("() => window.__chat.controller")

    page.evaluate("f => window.__chat.push(f)", SSE_SOURCES_FRAME)
    for i in range(1, 26):
        page.evaluate(
            "f => window.__chat.push(f)",
            sse_delta(f"Sentence number {i} of the answer, long enough to add height. "),
        )

    # MarkdownStream commits on an animation frame, so the deltas above are all
    # drained before any of them is on screen. Wait for the flush, then release
    # one more: a real stream interleaves frames and tokens, and it is that
    # token's followStream() that scrolls with content actually present.
    page.wait_for_function(
        "() => { const c = document.getElementById('messages');"
        "return c.scrollHeight > c.clientHeight * 1.5; }"
    )
    page.evaluate("f => window.__chat.push(f)", sse_delta("One more sentence. "))

    # Following is working before the reader intervenes — otherwise the rest of
    # this test would be asserting against a transcript that never moved.
    page.wait_for_function(
        "() => document.getElementById('messages').scrollTop > 100"
    )

    # The reader takes control, mid-stream.
    page.evaluate("() => document.getElementById('messages').scrollTo({top: 0, behavior: 'auto'})")
    expect(page.locator("#jump-to-latest")).to_be_visible()

    # More of the answer arrives, and then it ends.
    for i in range(26, 31):
        page.evaluate(
            "f => window.__chat.push(f)",
            sse_delta(f"Sentence number {i} of the answer, long enough to add height. "),
        )
    page.evaluate("f => { window.__chat.push(f); window.__chat.close(); }", SSE_DONE_FRAME)

    # Long enough that a closing smooth scroll would have completed.
    page.wait_for_timeout(800)

    scroll_top = page.evaluate("() => document.getElementById('messages').scrollTop")
    assert scroll_top < 50, (
        f"completion pulled the reader from the top down to {round(scroll_top)}px — "
        "reaching the end of the stream is not a reason to take back control"
    )
    expect(page.locator("#jump-to-latest")).to_be_visible()


def test_collapsing_the_deck_does_not_raise_a_false_jump_pill(sourced_page: Page):
    """Shrinking the transcript makes the browser clamp scrollTop downward,
    which is indistinguishable from an upward scroll by delta alone — and told
    a reader already at the bottom to jump to the bottom."""
    sourced_page.set_viewport_size({"width": 1280, "height": 700})
    _ask(sourced_page)

    # Settle at the bottom first, the way a reader who followed the answer is.
    sourced_page.evaluate(
        "() => { const c = document.getElementById('messages');"
        "c.scrollTo({top: c.scrollHeight, behavior: 'auto'}); }"
    )
    expect(sourced_page.locator("#jump-to-latest")).to_be_hidden()

    # Collapse the open deck: the transcript shrinks under them.
    sourced_page.locator(".source-deck-summary").click()
    expect(sourced_page.locator(".source-card").first).to_be_hidden()

    sourced_page.wait_for_timeout(200)
    expect(sourced_page.locator("#jump-to-latest")).to_be_hidden()


def test_source_card_discloses_its_passage_and_retrieval_split(sourced_page: Page):
    """The card at rest answers "which document, which page, how strongly";
    opening it answers "and what did it actually say"."""
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)

    card = sourced_page.locator(".source-card").first
    expect(card).to_be_visible()
    expect(card.locator(".source-snippet")).to_be_hidden()

    card.locator(".source-card-head").click()
    expect(card.locator(".source-snippet")).to_be_visible()
    expect(card.locator(".score").first).to_be_visible()
    expect(card.locator(".source-card-head")).to_have_attribute("aria-expanded", "true")


def test_source_deck_renders_in_arabic_rtl(sourced_page: Page):
    """Arabic is not a translation layer, so the deck ships in both directions."""
    sourced_page.evaluate("() => localStorage.setItem('lang', 'ar')")
    sourced_page.goto("/?testing=true&lang=ar")
    expect(sourced_page.locator("html")).to_have_attribute("dir", "rtl")

    _ask(sourced_page, "ما الذي يجب أن يتضمنه الملف؟")

    cards = sourced_page.locator(".source-card")
    expect(cards).to_have_count(8)
    box = cards.first.bounding_box()
    assert box and box["width"] > 200, "source card collapsed under RTL"

    # Page numbers stay LTR-isolated so bidi cannot reorder them inside Arabic.
    expect(sourced_page.locator(".source-page").first).to_have_attribute("dir", "ltr")
