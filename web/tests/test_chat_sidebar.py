"""The conversation sidebar in a real browser.

Step 8's client half. The server tests in `test_chat_sessions.py` prove what
reaches the database; these prove what the reader can actually see and do — and
in three cases they are the ONLY place the property is observable, because it
lives entirely in the DOM:

* **One state, two rendered copies.** The sidebar macro produces a desktop aside
  and an offcanvas, so every id it generates is suffixed and every listener is
  delegated. Built any other way, clicking the visible mobile row targets the
  hidden desktop one and one action fires twice.
* **A switch has to move several things together** — transcript, source panel,
  citation map, URL, active row. A version that cleared only the transcript
  leaves the previous conversation's passages open in the panel beside the
  new one's answers, which on this product means evidence attributed to the
  wrong question.
* **Sidebar controls are refused while an answer is streaming.** The server
  refuses them too (409), but a reader who is only told by a failed request has
  already lost the conversation they clicked.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import Page, expect

from web.tests.conftest import (
    SSE_CHAT_MOCK_WITH_SOURCES,
    chat_history,
    chat_sessions,
    route_chat_history,
    route_chat_sessions,
    stored_answer,
    stored_session,
)

# datetime.UTC is Python 3.11+; the VPS production floor is 3.10.
UTC = timezone.utc

pytestmark = pytest.mark.browser


CHATS_TAB = '[data-sidebar-tab="chats"]'
EXPLORE_TAB = '[data-sidebar-tab="explore"]'
HISTORY = "#history-sidebar-section"
FAQ = "#faq-sidebar-section"
ROW = f"{HISTORY} .history-item"


def days_ago(count: int) -> str:
    return (datetime.now(UTC) - timedelta(days=count)).isoformat()


def _sign_in(page: Page) -> None:
    page.locator("#auth-button-main").click()
    page.locator("#login-email").fill("test@example.com")
    page.locator("#login-password").fill("password123")
    page.locator("#login-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#authenticated-view").wait_for(state="visible")


def _with_sessions(page: Page, sessions, **kwargs) -> Page:
    """Sign in with a canned conversation list.

    Routed BEFORE the sign-in, because the list is fetched by `settleTranscript`
    the moment identity resolves — a route added afterwards would lose the race
    it is meant to control.
    """
    route_chat_sessions(page, chat_sessions(sessions, **kwargs))
    page.goto("/")
    _sign_in(page)
    return page


# ── The list ─────────────────────────────────────────────────────────────────


def test_conversations_are_listed_with_their_titles(browser_page: Page):
    page = _with_sessions(
        browser_page,
        [
            stored_session("11111111-1111-4111-8111-111111111111", "Bioequivalence waivers"),
            stored_session("22222222-2222-4222-8222-222222222222", "eCTD module 3"),
        ],
    )

    expect(page.locator(ROW)).to_have_count(2)
    expect(page.locator(ROW).first).to_contain_text("Bioequivalence waivers")


def test_conversations_are_grouped_by_day(browser_page: Page):
    """Fixed buckets from the catalogue, not `Intl.RelativeTimeFormat`.

    Arabic has six plural forms where `I18n.plural` knows two, `Intl` emits bidi
    control characters that reorder inside an RTL column, and the language
    toggle reloads the page — so a cached relative string is stale by
    construction. Five headings have none of those problems.
    """
    page = _with_sessions(
        browser_page,
        [
            stored_session("11111111-1111-4111-8111-111111111111", "Asked today"),
            stored_session(
                "22222222-2222-4222-8222-222222222222", "Asked yesterday", updated_at=days_ago(1)
            ),
            stored_session(
                "33333333-3333-4333-8333-333333333333", "Asked last week", updated_at=days_ago(4)
            ),
            stored_session(
                "44444444-4444-4444-8444-444444444444", "Asked last year", updated_at=days_ago(400)
            ),
        ],
    )

    headings = page.locator(f"{HISTORY} .history-group")
    expect(headings).to_have_count(4)
    expect(headings.nth(0)).to_have_text("Today")
    expect(headings.nth(1)).to_have_text("Yesterday")
    expect(headings.nth(2)).to_have_text("Previous 7 days")
    expect(headings.nth(3)).to_have_text("Older")


def test_an_untitled_conversation_gets_a_localised_fallback(browser_page: Page):
    """`title` is null for sessions written before first-turn titling shipped.
    The fallback is rendered client-side rather than substituted on the server,
    which would put English in an Arabic sidebar."""
    page = _with_sessions(
        browser_page,
        [
            stored_session("11111111-1111-4111-8111-111111111111", None),
        ],
    )

    expect(page.locator(ROW).first).to_contain_text("Untitled conversation")


def test_a_reader_with_no_conversations_sees_the_questions_instead(browser_page: Page):
    """THE DEFAULT TAB IS DECIDED FROM THE DATA, once.

    A first-time reader lands on the FAQ rail, which is what this column was
    originally for — a first session usually starts by clicking a question. A
    returning reader lands on their own work. Nobody pays a click for the state
    they were already in.
    """
    page = _with_sessions(browser_page, [])

    expect(page.locator(FAQ)).to_be_visible()
    expect(page.locator(HISTORY)).to_be_hidden()
    expect(page.locator(f"{CHATS_TAB}").first).to_have_attribute("aria-selected", "false")


def test_a_reader_with_conversations_lands_on_them(browser_page: Page):
    page = _with_sessions(
        browser_page,
        [
            stored_session("11111111-1111-4111-8111-111111111111", "Previous work"),
        ],
    )

    expect(page.locator(HISTORY)).to_be_visible()
    expect(page.locator(FAQ)).to_be_hidden()


def test_the_tabs_switch_the_column_without_losing_either_list(browser_page: Page):
    """Both panels stay in the DOM. Rendering only the active one would throw
    away the other's scroll position on every switch, and would make the FAQ rail
    — filled once, on sign-in — need refetching each time."""
    page = _with_sessions(
        browser_page,
        [
            stored_session("11111111-1111-4111-8111-111111111111", "Previous work"),
        ],
    )

    page.locator(EXPLORE_TAB).first.click()
    expect(page.locator(FAQ)).to_be_visible()
    expect(page.locator(".faq-button").first).to_be_visible()

    page.locator(CHATS_TAB).first.click()
    expect(page.locator(HISTORY)).to_be_visible()
    expect(page.locator(ROW)).to_have_count(1)


def test_an_unreachable_store_says_so_rather_than_showing_an_empty_list(browser_page: Page):
    """ "You have no saved conversations" is a claim about the READER. Making it
    because the store was unreachable is the quiet untruth `/api/chat/history`
    answers 503 rather than [] to avoid, and the sidebar inherits the rule."""
    page = browser_page
    page.route(
        "**/api/chat/sessions",
        lambda route: route.fulfill(
            status=503,
            content_type="application/json",
            body='{"error":"nope","code":"history_unavailable"}',
        ),
    )
    page.goto("/")
    _sign_in(page)

    page.locator(CHATS_TAB).first.click()
    status = page.locator(f"{HISTORY} .history-status")
    expect(status).to_be_visible()
    expect(status).to_contain_text("could not be loaded")
    # And a way out. An error with no retry is a dead end.
    expect(page.locator(f"{HISTORY} .history-retry")).to_be_visible()


def test_load_more_appears_only_when_the_server_offers_a_cursor(browser_page: Page):
    page = _with_sessions(
        browser_page,
        [stored_session("11111111-1111-4111-8111-111111111111", "One")],
        next_cursor={"updated_at": days_ago(1), "id": "22222222-2222-4222-8222-222222222222"},
    )
    expect(page.locator(f"{HISTORY} .history-more")).to_be_visible()


def test_no_load_more_without_a_cursor(browser_page: Page):
    page = _with_sessions(
        browser_page,
        [
            stored_session("11111111-1111-4111-8111-111111111111", "One"),
        ],
    )
    expect(page.locator(f"{HISTORY} .history-more")).to_have_count(0)


# ── Switching ────────────────────────────────────────────────────────────────


def test_opening_a_conversation_draws_its_transcript(browser_page: Page):
    page = browser_page
    session_id = "11111111-1111-4111-8111-111111111111"
    route_chat_sessions(
        page,
        chat_sessions(
            [
                stored_session(session_id, "Stored conversation"),
            ]
        ),
    )
    route_chat_history(page, chat_history(stored_answer("A stored question", "A stored answer")))

    page.goto("/")
    _sign_in(page)
    page.locator(f'{ROW} [data-history-action="open"]').first.click()

    expect(page.locator("#messages")).to_contain_text("A stored question")
    expect(page.locator("#messages")).to_contain_text("A stored answer")


def test_the_open_conversation_is_marked_active(browser_page: Page):
    """The highlight is a claim about which conversation the reader's NEXT
    question joins. It comes from the URL now (§5.3 of
    docs/per-tab-conversation-deep-linking-plan.md) rather than the server's
    signed-cookie `active` field: that field is per-BROWSER, and per-tab
    conversations mean it is routinely wrong for every tab but one — "worse
    than one that highlights none", by its own former rationale. The client
    knows which conversation this tab is in from its own route, which a
    shared cookie field cannot represent per-tab at all."""
    session_id = "11111111-1111-4111-8111-111111111111"
    route_chat_sessions(
        browser_page,
        chat_sessions(
            [
                stored_session(session_id, "The current one"),
                stored_session("22222222-2222-4222-8222-222222222222", "Another"),
            ]
        ),
    )
    route_chat_history(
        browser_page, chat_history(stored_answer("A stored question", "A stored answer"))
    )

    browser_page.goto(f"/c/{session_id}")
    _sign_in(browser_page)

    expect(browser_page.locator(f'{ROW}[data-session-id="{session_id}"]')).to_have_class(
        re.compile(r"is-active")
    )


def test_switching_clears_the_previous_conversations_evidence(browser_page: Page):
    """SIX THINGS MOVE TOGETHER, and this is the one whose absence is worst.

    Leaving the source panel open across a switch puts conversation A's passages
    beside conversation B's answers, in the one column the reader consults to
    check where an answer came from. On a regulatory product that is evidence
    attributed to the wrong question.

    Everything is routed before sign-in rather than using `sourced_page`,
    because the sidebar is fetched the instant identity resolves and a route
    added after login would lose that race.
    """
    page = browser_page
    session_id = "11111111-1111-4111-8111-111111111111"

    route_chat_sessions(page, chat_sessions([stored_session(session_id, "Elsewhere")]))
    page.route(
        "**/api/chat/stream",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=SSE_CHAT_MOCK_WITH_SOURCES,
        ),
    )
    route_chat_history(
        page, chat_history(stored_answer("A different question", "A different answer"))
    )

    page.goto("/")
    _sign_in(page)

    # An answer with sources, and its panel open.
    page.locator("#query-input").fill("A question with evidence")
    page.locator("#send-button").click()
    page.locator(".source-trigger").first.wait_for(state="visible", timeout=15000)
    page.locator(".source-trigger").first.click()
    expect(page.locator("#source-panel")).to_be_visible()

    page.locator(CHATS_TAB).first.click()
    page.locator(f'{ROW} [data-history-action="open"]').first.click()

    expect(page.locator("#source-panel")).to_be_hidden()
    expect(page.locator(".source-trigger")).to_have_count(0)
    expect(page.locator("#messages")).to_contain_text("A different question")
    expect(page.locator("#messages")).not_to_contain_text("A question with evidence")


# ── Renaming ─────────────────────────────────────────────────────────────────


def test_renaming_happens_in_the_row_rather_than_in_a_dialog(browser_page: Page):
    """A modal for this would take the reader out of the column to answer a
    question about something in it, and needs neither interruption nor protected
    focus."""
    session_id = "11111111-1111-4111-8111-111111111111"
    page = _with_sessions(browser_page, [stored_session(session_id, "Original name")])

    page.locator(f'{ROW} [data-history-action="rename"]').first.click()

    field = page.locator(f"{HISTORY} [data-rename-input]")
    expect(field).to_be_visible()
    expect(field).to_be_focused()
    expect(field).to_have_value("Original name")
    # The column's own bound, enforced before the round trip that would truncate.
    expect(field).to_have_attribute("maxlength", "120")


def test_a_rename_shows_what_the_server_stored(browser_page: Page):
    """The SERVER's clamped title, never the reader's raw input. Echoing what was
    typed would show an untruncated name until the next reload — a row quietly
    disagreeing with the database."""
    session_id = "11111111-1111-4111-8111-111111111111"
    page = browser_page
    route_chat_sessions(page, chat_sessions([stored_session(session_id, "Original")]))
    page.route(
        f"**/api/chat/sessions/{session_id}",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "id": session_id, "title": "Trimmed by the server"}),
        ),
    )
    page.goto("/")
    _sign_in(page)

    page.locator(f'{ROW} [data-history-action="rename"]').first.click()
    field = page.locator(f"{HISTORY} [data-rename-input]")
    expect(field).to_be_focused()
    field.fill("   spaced   out   ")

    # Waiting on the PATCH itself rather than on the repaint that follows it.
    # Asserting straight on the row makes the test a race between Playwright's
    # expect poll and a round trip — the shape that passes alone and fails under
    # a loaded suite, which is exactly how this one first went red.
    with page.expect_response(
        lambda response: (
            "/api/chat/sessions/" in response.url and response.request.method == "PATCH"
        )
    ):
        page.locator(f'{HISTORY} [data-history-action="rename-save"]').first.click()

    expect(page.locator(f'{ROW}[data-session-id="{session_id}"]')).to_contain_text(
        "Trimmed by the server"
    )


def test_escape_abandons_a_rename_without_closing_the_sidebar(browser_page: Page):
    """One key, two plausible meanings. A reader pressing Escape mid-rename means
    "undo this edit", not "leave the sidebar" — so the event is stopped, and the
    ambiguity a nested dismissible surface always brings is decided rather than
    left to bubbling order."""
    session_id = "11111111-1111-4111-8111-111111111111"
    page = _with_sessions(browser_page, [stored_session(session_id, "Original name")])

    page.locator(f'{ROW} [data-history-action="rename"]').first.click()
    page.locator(f"{HISTORY} [data-rename-input]").fill("Half-typed")
    page.locator(f"{HISTORY} [data-rename-input]").press("Escape")

    expect(page.locator(f"{HISTORY} [data-rename-input]")).to_have_count(0)
    expect(page.locator(ROW).first).to_contain_text("Original name")
    expect(page.locator(HISTORY)).to_be_visible()


# ── Deleting ─────────────────────────────────────────────────────────────────


def test_deleting_asks_first_and_can_be_declined(browser_page: Page):
    session_id = "11111111-1111-4111-8111-111111111111"
    page = _with_sessions(browser_page, [stored_session(session_id, "Keep me")])

    page.locator(f'{ROW} [data-history-action="delete"]').first.click()
    expect(page.locator(f"{HISTORY} .history-confirm")).to_contain_text("Delete this conversation?")

    page.locator(f'{HISTORY} [data-history-action="delete-cancel"]').first.click()
    expect(page.locator(f"{HISTORY} .history-confirm")).to_have_count(0)
    expect(page.locator(ROW)).to_have_count(1)


def test_confirming_removes_the_row(browser_page: Page):
    session_id = "11111111-1111-4111-8111-111111111111"
    page = browser_page
    route_chat_sessions(
        page,
        chat_sessions(
            [
                stored_session(session_id, "Doomed"),
                stored_session("22222222-2222-4222-8222-222222222222", "Survivor"),
            ]
        ),
    )
    page.route(
        f"**/api/chat/sessions/{session_id}",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "id": session_id}),
        ),
    )
    page.goto("/")
    _sign_in(page)

    page.locator(f'{ROW} [data-history-action="delete"]').first.click()
    page.locator(f'{HISTORY} [data-history-action="delete-confirm"]').first.click()

    expect(page.locator(ROW)).to_have_count(1)
    expect(page.locator(ROW).first).to_contain_text("Survivor")


# ── The in-flight refusal ────────────────────────────────────────────────────


def test_sidebar_actions_are_refused_while_an_answer_is_streaming(browser_page: Page):
    """THE AFFORDANCE HALF of the race the server also refuses with 409.

    Deleting a conversation whose answer is still in flight lets the late
    `chat_append_turn` recreate it — `insert … on conflict (id) do nothing`
    finds no row and makes one, carrying the answer the reader discarded. A
    reader who learns that only from a failed request has already clicked.

    The toast names the two ways out, because a control that simply does nothing
    is indistinguishable from a broken one.
    """
    session_id = "11111111-1111-4111-8111-111111111111"
    page = browser_page
    route_chat_sessions(page, chat_sessions([stored_session(session_id, "A conversation")]))
    # A stream that never finishes, so the request stays in flight.
    page.route("**/api/chat/stream", lambda route: None)

    page.goto("/")
    _sign_in(page)
    page.locator("#query-input").fill("A question that hangs")
    page.locator("#send-button").click()

    page.locator(CHATS_TAB).first.click()
    page.locator(f'{ROW} [data-history-action="delete"]').first.click()

    expect(page.locator("#toast")).to_contain_text("Wait for the answer to finish")
    expect(page.locator(f"{HISTORY} .history-confirm")).to_have_count(0)


# ── Two rendered copies, one state ───────────────────────────────────────────


def test_the_sidebar_renders_twice_without_duplicating_an_id(browser_page: Page):
    """`_sidebar.html` renders as the desktop aside AND inside the offcanvas.

    Every id it generates carries the macro's suffix, INCLUDING the ones ARIA
    points at: `aria-controls` and `aria-labelledby` resolve against the whole
    document, so an unsuffixed pair would make the offcanvas tab drive the
    desktop panel — silently, and only for readers using a screen reader.
    """
    page = _with_sessions(
        browser_page,
        [
            stored_session("11111111-1111-4111-8111-111111111111", "A conversation"),
        ],
    )

    duplicates = page.evaluate("""() => {
      const seen = new Map();
      document.querySelectorAll('[id]').forEach(el => {
        seen.set(el.id, (seen.get(el.id) || 0) + 1);
      });
      return [...seen.entries()].filter(([, n]) => n > 1).map(([id]) => id);
    }""")
    assert duplicates == [], f"duplicated element ids: {duplicates}"


def test_every_aria_reference_in_the_sidebar_resolves(browser_page: Page):
    page = _with_sessions(
        browser_page,
        [
            stored_session("11111111-1111-4111-8111-111111111111", "A conversation"),
        ],
    )

    unresolved = page.evaluate("""() => {
      const bad = [];
      document.querySelectorAll('[aria-controls], [aria-labelledby]').forEach(el => {
        ['aria-controls', 'aria-labelledby'].forEach(attr => {
          const value = el.getAttribute(attr);
          if (!value) return;
          value.split(/\\s+/).forEach(id => {
            if (id && !document.getElementById(id)) bad.push(`${attr}=${id}`);
          });
        });
      });
      return bad;
    }""")
    assert unresolved == [], f"dangling ARIA references: {unresolved}"


def test_both_sidebars_switch_tabs_together(browser_page: Page):
    """Tracked separately, the desktop aside and the offcanvas end up on
    different tabs — which a reader only discovers by resizing."""
    page = _with_sessions(
        browser_page,
        [
            stored_session("11111111-1111-4111-8111-111111111111", "A conversation"),
        ],
    )

    page.locator(EXPLORE_TAB).first.click()

    selected = page.evaluate("""() => [...document.querySelectorAll('.sidebar-tab')]
      .map(t => `${t.dataset.sidebarTab}:${t.getAttribute('aria-selected')}`)""")
    assert selected == [
        "chats:false",
        "explore:true",
        "chats:false",
        "explore:true",
    ], selected


def test_the_tablist_is_one_tab_stop(browser_page: Page):
    """The ARIA authoring practice: only the selected tab is reachable with Tab,
    and the arrow keys move between them. Leaving both at 0 costs a keyboard
    reader an extra stop on every visit to this column."""
    page = _with_sessions(
        browser_page,
        [
            stored_session("11111111-1111-4111-8111-111111111111", "A conversation"),
        ],
    )

    indexes = page.evaluate("""() => [...document.querySelectorAll('#sidebar-tabs .sidebar-tab')]
      .map(t => t.tabIndex)""")
    assert sorted(indexes) == [-1, 0], indexes


# ── Bidirectional text ───────────────────────────────────────────────────────


def test_a_title_carries_dir_auto_so_bidi_cannot_reorder_it(browser_page: Page):
    """Titles are reader input and routinely mix scripts — an Arabic question
    naming an English guideline code, or the reverse.

    Without per-row direction detection the Unicode bidi algorithm reorders the
    Latin run and puts the truncation ellipsis on the wrong end, which this
    codebase has already paid for once with an en-US time rendering as
    "AM 3:17:18" inside an Arabic transcript.
    """
    page = _with_sessions(
        browser_page,
        [
            stored_session(
                "11111111-1111-4111-8111-111111111111", "متطلبات التسجيل وفق دليل SFDA-MDS-REQ"
            ),
        ],
    )

    title = page.locator(f"{HISTORY} .history-item-title").first
    expect(title).to_have_attribute("dir", "auto")


def test_the_sidebar_mirrors_in_arabic(browser_page: Page):
    page = browser_page
    route_chat_sessions(
        page,
        chat_sessions(
            [
                stored_session("11111111-1111-4111-8111-111111111111", "محادثة سابقة"),
            ]
        ),
    )
    page.goto("/?lang=ar")
    _sign_in(page)

    expect(page.locator(CHATS_TAB).first).to_have_text("المحادثات")
    expect(page.locator(f"{HISTORY} .history-group").first).to_have_text("اليوم")

    # The row's actions sit on the trailing edge in BOTH directions, which is
    # what logical properties buy. Asserted geometrically rather than by reading
    # the stylesheet, because `margin-inline-start` in a rule that never applies
    # is still a passing grep.
    box = page.evaluate("""() => {
      const row = document.querySelector('#history-sidebar-section .history-item');
      const actions = row.querySelector('.history-item-actions');
      return {
        row: row.getBoundingClientRect().left,
        actions: actions.getBoundingClientRect().left,
      };
    }""")
    assert box["actions"] < box["row"] + 60, (
        "in RTL the row actions must sit on the LEFT (the trailing edge)"
    )
