"""Browser coverage for the source panel and the transcript's follow behaviour.

Every test here exists because a specific defect shipped without one:

* An answer's sources were emitted before the model was called, so they could
  not reflect what the answer did with them. A refusal — "I cannot answer based
  on the given information" — arrived with eight source cards expanded beneath
  it, which is the surface asserting evidence for an answer that has none.
* Those eight cards rendered inline, opened by default, and buried a two-line
  answer under them.
* The deck was a shrink-to-fit flex column holding a percentage-width list, so
  on wide screens every card rendered at zero by zero: in the DOM, invisible,
  on the surface whose whole premise is traceable answers.

The passages now live in a panel — the rail at >=1200px, a bottom sheet below
— and the transcript keeps one line naming them.
"""

import re

from playwright.sync_api import Page, expect

from .conftest import (
    SSE_DONE_FRAME,
    SSE_FINAL_FRAME,
    chat_history,
    route_chat_history,
    sse_delta,
    stored_answer,
)


WIDE = {"width": 1600, "height": 900}
NARROW = {"width": 900, "height": 800}


def _ask(page: Page, text: str = "What must the PSSF contain?") -> None:
    """Send a question and wait for that exchange to finish.

    Scoped to the newest answer rather than to the first match on the page:
    the suggestions of an EARLIER answer are already visible, so a global
    check returns instantly on the second call and the test races the stream.
    """
    before = page.locator(".chatbot-message").count()
    page.locator("#query-input").fill(text)
    page.locator("#send-button").click()
    expect(page.locator(".chatbot-message")).to_have_count(before + 1)
    # The suggestions frame is the last thing before `done`, so its arrival on
    # the new message means the whole exchange has been processed.
    expect(
        page.locator(".chatbot-message").last.locator(".suggested-question-enhanced").first
    ).to_be_visible()


def _settle_scroll(page: Page) -> None:
    """Wait for the closing smooth scroll to finish.

    Completing an answer scrolls the transcript with `behavior: 'smooth'`.
    Anything that reads or changes scroll position before that animation ends
    is racing it — a test scroll issued mid-flight gets overridden as the
    animation continues, which is what made the follow tests intermittent.
    """
    page.wait_for_function(
        """() => {
          const c = document.getElementById('messages');
          if (window.__settleTop === c.scrollTop) return true;
          window.__settleTop = c.scrollTop;
          return false;
        }""",
        timeout=5000,
    )
    page.evaluate("() => { delete window.__settleTop; }")


# ── What the transcript shows ───────────────────────────────────────────────

def test_a_cited_answer_gets_one_line_naming_its_documents(sourced_page: Page):
    """Three passages cited, drawn from two documents — and the count says so.

    The two numbers describe the same (cited) set, so they can never
    contradict each other the way a document count over a retrieved set could.
    """
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)

    trigger = sourced_page.locator(".source-trigger")
    expect(trigger).to_have_count(1)
    expect(trigger).to_be_visible()
    expect(trigger).to_have_text(re.compile(r"2 documents.*3 passages"))


def test_a_marker_free_answer_renders_no_source_control(uncited_page: Page):
    """The reported bug, in its production shape.

    Eight passages ARE retrieved — the relevance floor ships disabled, so
    "who is claude?" gets the least-bad eight — and the answer cites none of
    them. Nothing may render: not a deck, and not the muted "8 passages
    retrieved, not cited" line that replaced it, which disclaimed the passages
    while advertising eight of them and still put evidence under a refusal.
    """
    uncited_page.set_viewport_size(WIDE)
    _ask(uncited_page, "who is claude?")

    # The refusal itself is on screen...
    expect(uncited_page.locator(".chatbot-message").last).to_contain_text("cannot answer")
    # ...and nothing accompanies it.
    expect(uncited_page.locator(".source-trigger")).to_have_count(0)
    expect(uncited_page.locator("#source-panel")).to_be_hidden()
    expect(uncited_page.locator(".source-card")).to_have_count(0)


def test_nothing_retrieved_renders_no_source_control_at_all(no_sources_page: Page):
    """The same outcome by the other route: retrieval returned nothing at all.

    Reachable once a relevance floor is configured. Asserted separately from
    the case above because the two arrive at "no control" for different
    reasons, and a regression could break one without the other.
    """
    no_sources_page.set_viewport_size(WIDE)
    _ask(no_sources_page, "who is claude?")

    expect(no_sources_page.locator(".source-trigger")).to_have_count(0)
    expect(no_sources_page.locator("#source-panel")).to_be_hidden()


def test_the_trigger_does_not_push_the_answer_off_screen(sourced_page: Page):
    """What replaced eight open cards has to actually be small."""
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)

    box = sourced_page.locator(".source-trigger").bounding_box()
    assert box and box["height"] < 40, f"trigger is {box and box['height']}px tall"


def test_no_relevance_bar_is_rendered_anywhere(sourced_page: Page):
    """The bar read as calibrated confidence in the answer. It was a weighted
    blend of two cosine similarities with a heuristic penalty applied."""
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)
    sourced_page.locator(".source-trigger").click()

    expect(sourced_page.locator(".relevance")).to_have_count(0)
    expect(sourced_page.locator(".relevance-bar")).to_have_count(0)


# ── The panel ───────────────────────────────────────────────────────────────

def test_the_panel_opens_in_the_rail_and_keeps_the_mascot(sourced_page: Page):
    """Sunny stays at the head of the shelf.

    He used to be hidden outright the moment sources opened — removing the
    mascot at exactly the moment the product does its most characteristic
    thing. The rail is one object changing state now, not two swapping places.
    """
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)

    expect(sourced_page.locator("#source-panel")).to_be_hidden()
    sourced_page.locator(".source-trigger").click()

    panel = sourced_page.locator("#source-panel")
    expect(panel).to_be_visible()
    expect(sourced_page.locator("#chat-rail")).to_contain_class("rail-shows-sources")
    expect(sourced_page.locator(".robot-companion")).to_be_visible()
    # A sibling region, not a dialog: the answer stays reachable beside it.
    expect(panel).not_to_have_attribute("aria-modal", "true")
    expect(sourced_page.locator(".source-panel-backdrop")).to_be_hidden()


def test_panel_passages_render_with_real_size(sourced_page: Page):
    """The 0x0 regression guard, at a wide viewport deliberately."""
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)
    sourced_page.locator(".source-trigger").click()

    tabs = sourced_page.locator("#source-panel .spine-tab")
    expect(tabs).to_have_count(3)

    spine = sourced_page.locator("#source-panel .shelf-spine").first.bounding_box()
    assert spine is not None, "spine has no layout box at all"
    assert spine["width"] > 40, f"spine collapsed to {spine['width']}px wide"
    assert spine["height"] > 80, f"spine collapsed to {spine['height']}px tall"


def test_passages_from_one_document_share_a_heading(sourced_page: Page):
    """Where the density comes from.

    Passages 1 and 5 come from the same document, so three cited passages sit
    under TWO headings rather than repeating a filename three times.
    """
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)
    sourced_page.locator(".source-trigger").click()

    # Three tabs across two spines: grouping is now a property of the form.
    expect(sourced_page.locator("#source-panel .spine-tab")).to_have_count(3)
    expect(sourced_page.locator("#source-panel .shelf-spine")).to_have_count(2)


def test_opening_sources_does_not_move_the_answer(sourced_page: Page):
    """The panel is a separate column, so the reading position is untouched."""
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)

    # The closing scroll is smooth. Sampling before it settles measures that
    # animation rather than anything the panel did.
    _settle_scroll(sourced_page)

    before = sourced_page.evaluate("() => document.getElementById('messages').scrollTop")
    sourced_page.locator(".source-trigger").click()
    expect(sourced_page.locator("#source-panel")).to_be_visible()
    sourced_page.wait_for_timeout(400)

    after = sourced_page.evaluate("() => document.getElementById('messages').scrollTop")
    assert abs(after - before) < 5, f"transcript moved {abs(after - before)}px"


def test_a_citation_marker_opens_the_panel_on_its_passage(sourced_page: Page):
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)

    sourced_page.locator(".cite-marker[data-cite='3']").first.click()

    panel = sourced_page.locator("#source-panel")
    expect(panel).to_be_visible()
    # On the shelf a marker OPENS its passage rather than merely lighting a
    # card the reader would still have to find.
    expect(panel.locator(".spine-tab[data-index='3']")).to_contain_class("is-open")
    expect(panel.locator(".passage-card")).to_be_visible()


def test_escape_closes_the_panel_and_restores_the_mascot(sourced_page: Page):
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)
    sourced_page.locator(".source-trigger").click()
    expect(sourced_page.locator("#source-panel")).to_be_visible()

    sourced_page.keyboard.press("Escape")

    expect(sourced_page.locator("#source-panel")).to_be_hidden()
    expect(sourced_page.locator(".robot-companion")).to_be_visible()
    # A trigger left claiming to be expanded over a hidden panel is a lie to
    # every assistive technology reading it.
    expect(sourced_page.locator(".source-trigger")).to_have_attribute(
        "aria-expanded", "false"
    )


def test_closing_returns_focus_to_the_trigger(sourced_page: Page):
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)
    sourced_page.locator(".source-trigger").click()

    sourced_page.keyboard.press("Escape")
    focused = sourced_page.evaluate("() => document.activeElement.className")
    assert "source-trigger" in focused, f"focus landed on {focused!r}"


def test_retrieval_diagnostics_stay_collapsed_until_asked_for(sourced_page: Page):
    """Raw scores are reachable, but never presented as accuracy."""
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)
    sourced_page.locator(".source-trigger").click()

    toggle = sourced_page.locator(".source-diag-toggle")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(sourced_page.locator(".source-diag-list")).to_be_hidden()

    toggle.click()
    expect(sourced_page.locator(".source-diag-list")).to_be_visible()
    expect(sourced_page.locator(".source-diag-row")).to_have_count(3)
    # Figures, not percentages — no "%" anywhere in the disclosure.
    assert "%" not in sourced_page.locator(".source-diag-list").inner_text()


# ── Bottom sheet ────────────────────────────────────────────────────────────

def test_below_the_rail_breakpoint_the_panel_is_a_modal_sheet(sourced_page: Page):
    """It covers the reading column here, so it really is modal."""
    sourced_page.set_viewport_size(NARROW)
    _ask(sourced_page)
    sourced_page.locator(".source-trigger").click()

    panel = sourced_page.locator("#source-panel")
    expect(panel).to_be_visible()
    expect(panel).to_contain_class("is-sheet")
    expect(panel).to_have_attribute("role", "dialog")
    expect(panel).to_have_attribute("aria-modal", "true")
    expect(sourced_page.locator(".source-panel-backdrop")).to_be_visible()


def test_the_sheet_closes_on_escape(sourced_page: Page):
    sourced_page.set_viewport_size(NARROW)
    _ask(sourced_page)
    sourced_page.locator(".source-trigger").click()
    expect(sourced_page.locator("#source-panel")).to_be_visible()

    sourced_page.keyboard.press("Escape")
    expect(sourced_page.locator("#source-panel")).to_be_hidden()
    expect(sourced_page.locator(".source-panel-backdrop")).to_be_hidden()


def test_the_sheet_does_not_overflow_a_phone_viewport(sourced_page: Page):
    sourced_page.set_viewport_size({"width": 390, "height": 780})
    _ask(sourced_page)
    sourced_page.locator(".source-trigger").click()
    expect(sourced_page.locator("#source-panel")).to_be_visible()

    overflow = sourced_page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0, f"page scrolls horizontally by {overflow}px"


# ── Follow behaviour ────────────────────────────────────────────────────────

def test_completing_an_answer_does_not_stop_the_transcript_following(sourced_page: Page):
    """The regression that made answers stream off-screen.

    The assertion is the END OF THE ANSWER, not the bottom of the scroller.
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
             ABOVE the top means completion jumped the reader past the answer.
             A one-sided `gap < 40` accepted the second. */
          return answerEnd <= box.bottom + 40 && answerEnd > box.top;
        }""",
        timeout=5000,
    )


def test_scrolling_up_hands_control_back_to_the_reader(sourced_page: Page):
    """The other direction: a real upward scroll must still stop the follow."""
    sourced_page.set_viewport_size({"width": 1280, "height": 700})
    _ask(sourced_page)
    _settle_scroll(sourced_page)

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
    page.evaluate("f => window.__chat.push(f)", SSE_FINAL_FRAME)
    page.evaluate("f => { window.__chat.push(f); window.__chat.close(); }", SSE_DONE_FRAME)

    # Long enough that a closing smooth scroll would have completed.
    page.wait_for_timeout(800)

    scroll_top = page.evaluate("() => document.getElementById('messages').scrollTop")
    assert scroll_top < 50, (
        f"completion pulled the reader from the top down to {round(scroll_top)}px — "
        "reaching the end of the stream is not a reason to take back control"
    )
    expect(page.locator("#jump-to-latest")).to_be_visible()


# ── Stream lifecycle ────────────────────────────────────────────────────────

def _open_stream(page: Page, question: str = "Who controls the scroll?") -> None:
    page.set_viewport_size(WIDE)
    page.locator("#query-input").fill(question)
    page.locator("#send-button").click()
    page.wait_for_function("() => window.__chat.controller")


def test_a_stream_that_ends_without_final_is_flagged_incomplete(streaming_page: Page):
    """A closed socket is not a finished answer.

    A proxy timeout or a killed worker ends the body cleanly. The tokens that
    arrived never went through citation normalization, so presenting them as a
    finished answer shows a truncated regulatory answer as authoritative.
    """
    page = streaming_page
    _open_stream(page)
    page.evaluate("f => window.__chat.push(f)", sse_delta("Registration requires "))
    page.evaluate("f => window.__chat.push(f)", sse_delta("a valid dossier "))
    # EOF with no `final` and no `done`.
    page.evaluate("() => window.__chat.close()")

    expect(page.locator(".chatbot-message.is-errored")).to_have_count(1)
    expect(page.locator(".stream-note")).to_be_visible()
    # A truncated answer must not claim sources either.
    expect(page.locator(".source-trigger")).to_have_count(0)


def test_a_stream_that_ends_without_done_keeps_the_canonical_answer(streaming_page: Page):
    """`final` arrived, `done` did not.

    The exchange is flagged — most likely the turn was never persisted — but
    the answer itself is whole and normalized, so it must be RENDERED from the
    canonical text rather than falling back to the raw deltas. Falling back
    would un-resolve the citations to punish a failure that happened after the
    answer was already complete.
    """
    page = streaming_page
    _open_stream(page)
    # A legacy prose citation the server rewrites into "[1]" in `final`.
    page.evaluate(
        "f => window.__chat.push(f)",
        sse_delta("Registration requires a dossier [Source: Doc_1.pdf, Page: 1]. "),
    )
    page.evaluate("f => window.__chat.push(f)", SSE_FINAL_FRAME)
    page.evaluate("() => window.__chat.close()")

    # Flagged...
    expect(page.locator(".chatbot-message.is-errored")).to_have_count(1)
    # ...but showing the canonical answer, not the raw delta text.
    answer = page.locator(".chatbot-message").last
    expect(answer).to_contain_text("Sentence number 1")
    expect(answer).not_to_contain_text("[Source:")
    # And its citations resolve, because the payload arrived with `final`.
    expect(page.locator(".source-trigger")).to_have_count(1)


def test_an_error_after_final_keeps_the_canonical_answer(streaming_page: Page):
    """Suggestion generation and history persistence run AFTER `final`.

    If either fails the client gets an `error` frame — but the answer itself is
    complete and normalized by then. Discarding it to show raw partial deltas
    would throw away a good answer and its citations over a failure that never
    touched them.
    """
    page = streaming_page
    _open_stream(page)
    page.evaluate("f => window.__chat.push(f)", sse_delta("Registration requires a dossier [1]. "))
    page.evaluate("f => window.__chat.push(f)", SSE_FINAL_FRAME)
    page.evaluate(
        "f => { window.__chat.push(f); window.__chat.close(); }",
        'event: error\ndata: {"error":"boom","code":"internal"}\n\n',
    )

    # The answer is rendered properly, with its sources...
    expect(page.locator(".source-trigger")).to_have_count(1)
    expect(page.locator(".chatbot-message.is-errored")).to_have_count(0)
    # ...and the canonical text replaced the raw deltas.
    expect(page.locator(".chatbot-message").last).to_contain_text("Sentence number 1")


# ── Panel ownership ─────────────────────────────────────────────────────────

def test_only_one_trigger_ever_claims_to_be_expanded(sourced_page: Page):
    """Two answers, one panel.

    aria-expanded used to be set by whichever click handler fired, so opening
    answer B left answer A's trigger still claiming expanded — two controls
    describing one panel, one of them wrong.
    """
    page = sourced_page
    page.set_viewport_size(WIDE)
    _ask(page)
    _ask(page, "And what about variations?")

    triggers = page.locator(".source-trigger")
    expect(triggers).to_have_count(2)

    triggers.first.click()
    expect(page.locator('.source-trigger[aria-expanded="true"]')).to_have_count(1)

    triggers.last.click()
    expect(page.locator('.source-trigger[aria-expanded="true"]')).to_have_count(1)
    expect(triggers.last).to_have_attribute("aria-expanded", "true")
    expect(triggers.first).to_have_attribute("aria-expanded", "false")


def test_opening_via_a_marker_marks_that_answers_trigger_expanded(sourced_page: Page):
    """The panel is open; its trigger must not say otherwise."""
    page = sourced_page
    page.set_viewport_size(WIDE)
    _ask(page)

    page.locator(".cite-marker[data-cite='3']").first.click()
    expect(page.locator("#source-panel")).to_be_visible()
    expect(page.locator(".source-trigger")).to_have_attribute("aria-expanded", "true")


def test_asking_again_closes_a_panel_showing_the_previous_answer(sourced_page: Page):
    page = sourced_page
    page.set_viewport_size(WIDE)
    _ask(page)
    page.locator(".source-trigger").click()
    expect(page.locator("#source-panel")).to_be_visible()

    _ask(page, "And what about variations?")
    expect(page.locator("#source-panel")).to_be_hidden()


# ── Session isolation ───────────────────────────────────────────────────────

def test_logging_out_leaves_nothing_of_the_previous_reader(sourced_page: Page):
    """The tab is not reloaded on the way out.

    AuthView only toggles `d-none` and the app lives at "/", so the transcript,
    the source panel and the citation map all survive a logout unless they are
    explicitly cleared — and the next person to sign in on a shared machine
    would find the previous reader's questions, answers and evidence intact.
    """
    page = sourced_page
    page.set_viewport_size(WIDE)
    _ask(page)
    page.locator(".source-trigger").click()
    expect(page.locator("#source-panel")).to_be_visible()

    page.locator("#logout-button").locator("visible=true").first.click()
    expect(page.locator("#unauthenticated-view")).to_be_visible()

    expect(page.locator("#source-panel")).to_be_hidden()
    expect(page.locator(".chatbot-message")).to_have_count(0)
    expect(page.locator(".source-trigger")).to_have_count(0)
    assert page.evaluate("() => sessionStorage.getItem('sfda-transcript')") is None


def test_cancelling_after_final_keeps_the_canonical_answer(streaming_page: Page):
    """Pressing Stop a moment too late must not cost the answer.

    If `final` already arrived the answer is whole and normalized — the reader
    stopped a stream that had, unknown to them, already finished. Falling back
    to the raw deltas would discard a complete answer and un-resolve its
    citations as a penalty for the timing.
    """
    page = streaming_page
    _open_stream(page)
    page.evaluate(
        "f => window.__chat.push(f)",
        sse_delta("Registration requires a dossier [Source: Doc_1.pdf, Page: 1]. "),
    )
    page.evaluate("f => window.__chat.push(f)", SSE_FINAL_FRAME)
    # The reader hits Stop, which aborts the fetch.
    page.evaluate("() => window.__chat.controller.error(Object.assign("
                  "new Error('aborted'), {name: 'AbortError'}))")

    answer = page.locator(".chatbot-message").last
    expect(answer).to_contain_text("Sentence number 1")
    expect(answer).not_to_contain_text("[Source:")
    expect(page.locator(".chatbot-message.is-cancelled")).to_have_count(1)
    expect(page.locator(".source-trigger")).to_have_count(1)


# ── Restored transcripts ────────────────────────────────────────────────────

def test_a_transcript_is_not_restored_when_startup_finds_no_reader(sourced_page: Page):
    """The transcript belongs to whoever saved it.

    It used to be restored during init(), before authentication resolved — so
    when startup found no valid session the previous reader's conversation sat
    in the DOM behind the landing view, hidden rather than removed, waiting to
    be revealed to whoever signed in next.
    """
    page = sourced_page
    page.set_viewport_size(WIDE)
    _ask(page)
    expect(page.locator(".chatbot-message")).to_have_count(1)

    # Save the transcript the way a language switch does, then reload into a
    # tab whose session does not come back.
    page.evaluate("() => sessionStorage.setItem('sfda-transcript', JSON.stringify("
                  "{owner: 'someone-else', turns: '<div class=\"message chatbot-message\">"
                  "Previous reader\\'s answer</div>'}))")
    page.reload()
    page.wait_for_function("() => window.APP_INITIALIZED")

    # Nothing of theirs is on the page, and nothing is left waiting either.
    expect(page.locator(".chatbot-message")).to_have_count(0)
    assert page.evaluate("() => sessionStorage.getItem('sfda-transcript')") is None



SEED_SUPABASE_SESSION = (
    "window.__supabaseState = {"
    "  user: { id: 'test-user-id', email: 'test@example.com' },"
    "  profile: { id: 'test-user-id', full_name: 'Test User',"
    "             preferences: { theme: 'light' } },"
    "  authCallback: null, lastProfileUpdate: null,"
    "  sessionError: null, profileError: null, profileUpdateError: null };"
)

# One stored passage, deliberately unlike anything the live SSE mock returns, so
# a restored citation opening the WRONG answer's evidence is visible as text
# rather than inferable from a count.
STORED_SOURCE = {
    "index": 1,
    "cited": True,
    "document": "Archived Circular 7 — Stored Evidence",
    "page": 42,
    "category": "Regulatory",
    "score": 0.71,
    "semantic_score": 0.7,
    "lexical_score": 0.72,
    "chunk_id": "stored-chunk-1",
    "snippet": "The passage this stored answer was written from.",
}


def test_a_restored_answer_opens_its_own_stored_evidence(sourced_page: Page):
    """The payoff of hydration, and the wrong-evidence bug it must not reopen.

    Until step 6 this asserted the INVERSE: a restored answer kept its prose and
    had its citation controls stripped, because the transcript came back as
    markup from `sessionStorage` while the passages behind it lived only in
    module memory. A control that resolves to nothing is a worse lie than no
    control, so they were removed.

    The turns now come from durable rows, passages included, so the controls
    resolve — and the older hazard the previous test guarded is still live:
    message ids were once a per-load counter, so a restored answer and the next
    fresh answer could share an id and the old [1] would open the NEW answer's
    evidence. Both properties are asserted here.
    """
    page = sourced_page
    page.set_viewport_size(WIDE)
    _ask(page)
    expect(page.locator(".source-trigger")).to_have_count(1)

    # The Supabase double keeps its session in a page-scoped object, so a reload
    # would otherwise come back signed out and hydrate nothing.
    page.add_init_script(SEED_SUPABASE_SESSION)
    route_chat_history(
        page,
        chat_history(stored_answer(
            "What must the PSSF contain?",
            "The stored answer, citing [1].",
            sources=[STORED_SOURCE],
        )),
    )

    page.locator(".lang-toggle-btn").locator("visible=true").first.click()
    page.wait_for_load_state("load")
    expect(page.locator("#query-input")).to_be_visible()
    expect(page.locator(".chatbot-message")).to_have_count(1)

    # The restored answer arrived WITH its evidence.
    expect(page.locator(".source-trigger")).to_have_count(1)
    expect(page.locator(".cite-marker")).to_have_count(1)

    page.locator(".cite-marker").first.click()
    expect(page.locator("#source-panel")).to_be_visible()
    expect(page.locator(".source-panel-body")).to_contain_text("Archived Circular 7")

    # A NEW answer gets its own controls, resolving to its own sources — not to
    # the stored ones, and not the other way round.
    #
    # Asserted against `.source-panel-body`, which `_render` empties on every
    # open, rather than against the whole panel: `close()` hides the expanded
    # passage card without clearing it, so the panel's textContent still carries
    # the previous answer's passage as dead, invisible text. Scoping to the body
    # asks the question the test means — what is this panel listing NOW.
    page.keyboard.press("Escape")
    _ask(page, "ما الذي يجب أن يتضمنه الملف؟")
    expect(page.locator(".source-trigger")).to_have_count(2)

    page.locator(".chatbot-message").last.locator(".source-trigger").click()
    expect(page.locator("#source-panel")).to_be_visible()
    expect(page.locator(".source-panel-body")).to_contain_text("SFDA Guideline Document Number 1")
    expect(page.locator(".source-panel-body")).not_to_contain_text("Archived Circular 7")

    # And back again — the assertion that makes this test mean something.
    # Checking only that the NEW answer opens its own evidence would still pass
    # if the new answer had overwritten the restored one's entry under a
    # colliding message id, which is precisely the bug that made ids uuids
    # instead of a per-load counter. The restored answer has to still open its
    # own archived passage AFTER a second answer exists.
    page.keyboard.press("Escape")
    page.locator(".chatbot-message").first.locator(".cite-marker").first.click()
    expect(page.locator("#source-panel")).to_be_visible()
    expect(page.locator(".source-panel-body")).to_contain_text("Archived Circular 7")
    expect(page.locator(".source-panel-body")).not_to_contain_text(
        "SFDA Guideline Document Number 1"
    )


def test_evidence_from_the_active_build_is_not_badged(sourced_page: Page):
    """`verified` says nothing. Warning about every answer is the same as
    warning about none."""
    page = sourced_page
    page.set_viewport_size(WIDE)
    page.add_init_script(SEED_SUPABASE_SESSION)
    route_chat_history(
        page,
        chat_history(stored_answer(
            "A question", "An answer citing [1].",
            sources=[STORED_SOURCE], evidence_state="verified",
        )),
    )
    page.reload()
    page.wait_for_load_state("load")

    expect(page.locator(".source-trigger")).to_have_count(1)
    expect(page.locator(".source-trigger-badge")).to_have_count(0)

    page.locator(".source-trigger").click()
    expect(page.locator(".source-panel-dated")).to_be_hidden()


def test_evidence_from_a_rebuilt_corpus_is_dated_but_still_opens(sourced_page: Page):
    """The design position this step reversed, pinned so it cannot drift back.

    An earlier plan had a stale citation render inert — markers reverted to
    plain text, trigger removed. That would have let one corpus rebuild deaden
    every citation in every stored conversation at once. The stored row IS what
    the model read, so it opens; what changes is that the reader is told the
    document set has moved since.
    """
    page = sourced_page
    page.set_viewport_size(WIDE)
    page.add_init_script(SEED_SUPABASE_SESSION)
    route_chat_history(
        page,
        chat_history(stored_answer(
            "A question", "An answer citing [1].",
            sources=[STORED_SOURCE], evidence_state="stale",
        )),
    )
    page.reload()
    page.wait_for_load_state("load")

    expect(page.locator(".source-trigger")).to_have_count(1)
    expect(page.locator(".source-trigger-badge")).to_have_count(1)

    page.locator(".cite-marker").first.click()
    expect(page.locator("#source-panel")).to_be_visible()
    expect(page.locator(".source-panel-dated")).to_be_visible()
    expect(page.locator(".source-panel-body")).to_contain_text("Archived Circular 7")


def test_unverifiable_evidence_is_dated_on_the_same_terms(sourced_page: Page):
    """Three states server-side, two on screen. `stale` and `unverifiable` mean
    the same thing to a reader — we cannot confirm this is still in the live
    corpus — and share one badge."""
    page = sourced_page
    page.set_viewport_size(WIDE)
    page.add_init_script(SEED_SUPABASE_SESSION)
    route_chat_history(
        page,
        chat_history(stored_answer(
            "A question", "An answer citing [1].",
            sources=[STORED_SOURCE], evidence_state="unverifiable",
        )),
    )
    page.reload()
    page.wait_for_load_state("load")

    expect(page.locator(".source-trigger-badge")).to_have_count(1)


def test_a_second_reader_in_the_same_tab_gets_their_own_transcript(browser_page: Page):
    """The failure the resume flag spent two steps waiting to avoid, arriving by
    a different door.

    The app lives at "/" and `AuthView` only toggles `d-none`, so a sign-out
    followed by a sign-in reloads nothing. A transcript guard keyed to the PAGE
    rather than to the READER is therefore already spent when the second reader
    arrives: their transcript is never drawn, while the server — finding no
    cookie — resumes their most recent conversation into the prompt window. A
    blank screen backed by a model that remembers, which is exactly the state
    `chat_resume_latest_session` was held off for until hydration existed.

    Two properties are asserted: the second reader's own turns appear, and the
    first reader's do not survive into their session.
    """
    page = browser_page
    route_chat_history(
        page, chat_history(stored_answer("Reader A question", "Reader A answer."))
    )
    page.goto("/")
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill("test@example.com")
    page.locator("#login-password").fill("password123")
    page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#authenticated-view").wait_for(state="visible")
    expect(page.locator(".chatbot-message")).to_have_count(1)
    expect(page.locator("#messages")).to_contain_text("Reader A answer.")

    # The second reader's history replaces the first's on the wire, exactly as
    # the server would answer once the identity behind the cookie changed.
    route_chat_history(
        page, chat_history(stored_answer("Reader B question", "Reader B answer."))
    )
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

    expect(page.locator("#messages")).to_contain_text("Reader B answer.")
    expect(page.locator("#messages")).not_to_contain_text("Reader A answer.")


# Holds `/api/chat/history` open until the test releases it, so "the transcript
# arrives late" is a state the test enters deliberately rather than one it hopes
# for. Same idea as CONTROLLABLE_CHAT_STREAM in conftest: no timing, no sleeps —
# the test is the clock. Installed via add_init_script so it wraps fetch before
# any application module runs.
CONTROLLABLE_HISTORY = """
window.__history = {};
window.__history.ready = new Promise((resolve) => { window.__history.release = resolve; });
const __origFetch = window.fetch;
window.fetch = async (input, init) => {
  const url = typeof input === 'string' ? input : input.url;
  if (url && url.includes('/api/chat/history')) {
    const body = await window.__history.ready;
    return new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }
  return __origFetch(input, init);
};
"""


def test_history_arriving_late_is_filed_above_the_live_exchange(browser_page: Page):
    """Hydration is not awaited, so it can land after a new answer is on screen.

    A reader who signs in and asks straight away gets their question rendered
    while the transcript fetch is still in flight. Appending then would file
    their stored conversation UNDERNEATH the question they just asked — a
    transcript that reads backwards, on the surface whose whole job is to show
    what was said and in what order.

    Stored turns are older than anything this tab has done, so they belong above
    it however late they arrive.
    """
    page = browser_page
    page.add_init_script(CONTROLLABLE_HISTORY)
    page.goto("/")
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill("test@example.com")
    page.locator("#login-password").fill("password123")
    page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#authenticated-view").wait_for(state="visible")

    # The transcript is still in flight, so the reader asks into an empty screen.
    expect(page.locator("#messages")).not_to_contain_text("Older stored answer.")
    _ask(page, "A brand new question")

    # Only now does the stored conversation arrive.
    body = chat_history(stored_answer("Older question", "Older stored answer."))
    page.evaluate("(body) => window.__history.release(body)", body)
    expect(page.locator("#messages")).to_contain_text("Older stored answer.")

    order = page.evaluate(
        "() => [...document.querySelectorAll('#messages .message')]"
        "        .map(el => el.textContent)"
    )
    stored_at = next(i for i, t in enumerate(order) if "Older stored answer." in t)
    fresh_at = next(i for i, t in enumerate(order) if "A brand new question" in t)
    assert stored_at < fresh_at, (
        f"stored history was filed below the live exchange: {order}"
    )


def test_late_history_cannot_resurrect_a_conversation_the_reader_ended(browser_page: Page):
    """New chat must mean New chat, including against a fetch already in flight.

    The server-side rule is careful about this: a cookie that names a
    conversation is honoured as-is, precisely so a reset is not undone by the
    resume fallback. But hydration opens a second door the server cannot close —
    the transcript request is dispatched at sign-in and not awaited, so a reader
    who presses New chat while it is still travelling would have the ended
    conversation drawn back onto the screen when it lands.

    Identity alone does not catch this: it is the same reader who pressed the
    button. The transcript epoch does.
    """
    page = browser_page
    page.add_init_script(CONTROLLABLE_HISTORY)
    page.goto("/")
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill("test@example.com")
    page.locator("#login-password").fill("password123")
    page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#authenticated-view").wait_for(state="visible")

    # A turn exists, so New chat is offered at all.
    _ask(page, "A question in this tab")
    expect(page.locator(".chatbot-message")).to_have_count(1)

    page.locator(".new-chat-btn").locator("visible=true").first.click()
    expect(page.locator(".chatbot-message")).to_have_count(0)

    # Only now does the transcript request — dispatched back at sign-in —
    # finally arrive, carrying a conversation the reader has since ended.
    body = chat_history(
        stored_answer("Ended question", "Ended stored answer."), resumed=True
    )
    page.evaluate("(body) => window.__history.release(body)", body)

    expect(page.locator("#messages")).not_to_contain_text("Ended stored answer.")
    expect(page.locator("#resumed-notice")).to_have_count(0)
    expect(page.locator(".chatbot-message")).to_have_count(0)


# ── Arabic ──────────────────────────────────────────────────────────────────

def test_the_panel_renders_in_arabic_rtl(sourced_page: Page):
    """Arabic is not a translation layer, so this ships in both directions."""
    sourced_page.set_viewport_size(WIDE)
    sourced_page.evaluate("() => localStorage.setItem('lang', 'ar')")
    sourced_page.goto("/?testing=true&lang=ar")
    expect(sourced_page.locator("html")).to_have_attribute("dir", "rtl")

    _ask(sourced_page, "ما الذي يجب أن يتضمنه الملف؟")
    sourced_page.locator(".source-trigger").click()

    tabs = sourced_page.locator("#source-panel .spine-tab")
    expect(tabs).to_have_count(3)
    spine = sourced_page.locator("#source-panel .shelf-spine").first.bounding_box()
    assert spine and spine["width"] > 40, "spine collapsed under RTL"

    # Page numbers stay LTR-isolated so bidi cannot reorder them inside Arabic.
    expect(sourced_page.locator("#source-panel .tab-page").first).to_have_attribute(
        "dir", "ltr"
    )


def test_a_marker_free_answer_renders_no_control_in_arabic_either(uncited_page: Page):
    """This case fires more often in Arabic: the language instruction adds a
    second rule about citation markers for the model to drop, so an otherwise
    good Arabic answer loses its markers more readily than an English one."""
    uncited_page.set_viewport_size(WIDE)
    uncited_page.evaluate("() => localStorage.setItem('lang', 'ar')")
    uncited_page.goto("/?testing=true&lang=ar")

    _ask(uncited_page, "ما الذي يجب أن يتضمنه الملف؟")

    expect(uncited_page.locator(".source-trigger")).to_have_count(0)
    expect(uncited_page.locator("#source-panel")).to_be_hidden()


# ── The sparse case ─────────────────────────────────────────────────────────
#
# One passage from one document is the state most likely to read as a bug
# rather than a deliberate answer, so it is designed and asserted rather than
# left to fall out of the layout.

def test_a_single_source_presents_as_one_exhibit(sparse_page: Page):
    """One spine, full width, presented rather than stranded."""
    sparse_page.set_viewport_size(WIDE)
    _ask(sparse_page)

    expect(sparse_page.locator(".source-trigger")).to_have_text(
        re.compile(r"1 document.*1 passage")
    )
    sparse_page.locator(".source-trigger").click()

    spines = sparse_page.locator("#source-panel .shelf-spine")
    expect(spines).to_have_count(1)
    expect(sparse_page.locator("#source-panel .spine-tab")).to_have_count(1)

    # The lone spine takes the shelf's width instead of sitting as a sliver.
    shelf = sparse_page.locator("#source-panel .source-shelf").bounding_box()
    spine = spines.first.bounding_box()
    assert spine and shelf, "sparse shelf has no layout box"
    assert spine["width"] > shelf["width"] * 0.6, (
        f"lone spine is {spine['width']}px of a {shelf['width']}px shelf — "
        "the sparse case reads as stranded rather than presented"
    )


def test_a_passage_with_no_page_still_reads_as_intentional(sparse_page: Page):
    """`page: null` is a real payload state, not a rendering accident.

    The tab keeps its notch and its citation number; only the page is absent,
    and the card says so in words rather than leaving a blank where a number
    should be.
    """
    sparse_page.set_viewport_size(WIDE)
    _ask(sparse_page)
    sparse_page.locator(".source-trigger").click()

    tab = sparse_page.locator("#source-panel .spine-tab").first
    expect(tab).to_be_visible()
    expect(tab.locator(".tab-index")).to_have_text("1")
    expect(tab.locator(".tab-page")).to_have_text("")

    tab.click()
    expect(sparse_page.locator(".passage-card .passage-page")).to_have_text("No page cited")


def test_a_spine_label_is_not_the_date_every_filename_starts_with(sourced_page: Page):
    """All 111 corpus documents begin with an ISO date.

    Truncating the raw filename gives "2010-08-31_Gui" for both the allergenics
    guideline and the antisera one — three spines carrying the same label,
    which is worse than the list the shelf replaced. The date and extension are
    stripped before anything is truncated.
    """
    sourced_page.set_viewport_size(WIDE)
    _ask(sourced_page)
    sourced_page.locator(".source-trigger").click()

    labels = sourced_page.locator("#source-panel .spine-label")
    expect(labels.first).not_to_have_text(re.compile(r"^\d{4}-\d{2}-\d{2}"))
    expect(labels.first).not_to_have_text(re.compile(r"\.pdf"))
    # Distinct documents must produce distinct labels.
    texts = labels.all_inner_texts()
    assert len(set(texts)) == len(texts), f"spine labels collide: {texts}"


# ── The mascot reports what the reader is looking at ────────────────────────

def test_the_mascot_carries_provenance_while_sources_are_open(sourced_page: Page):
    """Teal means "this came from a document" everywhere else in the
    transcript, so Sunny's eyes take it for as long as the evidence is on
    screen. His face reports the reader's state rather than decorating it.
    """
    page = sourced_page
    page.set_viewport_size(WIDE)
    _ask(page)

    companion = page.locator(".robot-companion-body")
    eye = lambda: page.evaluate(
        "() => getComputedStyle(document.querySelector('.robot-companion-body .sunny-svg'))"
        ".getPropertyValue('--sunny-eye').trim()"
    )
    signal = page.evaluate(
        "() => getComputedStyle(document.documentElement).getPropertyValue('--signal').trim()"
    )

    page.locator(".source-trigger").click()
    expect(companion).to_contain_class("robot-presenting")
    assert eye() == signal, "the mascot did not take the provenance colour"

    page.locator(".source-trigger").click()
    expect(companion).not_to_contain_class("robot-presenting")
    assert eye() != signal, "the mascot kept the provenance colour after closing"


def test_the_present_gesture_is_one_shot_and_repeatable(sourced_page: Page):
    """The nod plays on every open, not only the first.

    It is applied as its own class and removed again, so the idle breathe on
    the same element resumes rather than being left overridden forever — and
    so a second answer's sources get the gesture too.
    """
    page = sourced_page
    page.set_viewport_size(WIDE)
    _ask(page)
    companion = page.locator(".robot-companion-body")

    page.locator(".source-trigger").click()
    expect(companion).to_contain_class("robot-presents")
    # One-shot: gone once it has played.
    expect(companion).not_to_contain_class("robot-presents", timeout=3000)

    page.locator(".source-trigger").click()   # close
    page.locator(".source-trigger").click()   # and open again
    expect(companion).to_contain_class("robot-presents")
