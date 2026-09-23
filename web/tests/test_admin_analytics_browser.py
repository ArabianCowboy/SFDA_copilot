"""The saved-conversations analytics tab, in a browser.

The tab is the last one, and `#analytics-body` is its panel body: a lead zone
holding the period and language selects, the refresh button, the "counted at"
stamp and a polite live region, above `#analytics-results` — three zones that
each render `null` as "could not load" and `[]` as "nothing yet", and each fail
on their own (docs/admin-analytics-v1-plan.md §7.2-§7.7; the placement is
DESIGN.md). Every selector here scopes past the lead
zone rather than assuming it holds nothing but the controls, because a results
repaint must never touch it.

Two console helpers, because one cannot express both jobs. `_analytics_console`
serves canned payloads to the three requests and is what most tests want; it
mirrors `_overview_console` (`test_admin_browser.py:2196`) rather than calling
it, on purpose, since that helper does its own `page.goto` and registering the
analytics routes only after it returns would race the page's own fetches, which
fire the moment identity resolves. `_filtered_console` answers per window
instead, so the DOM says WHICH response it is showing, and can hold a route
open across a second choice — which is what the race and control tests need.
Both register every route before navigating, and both then click the tab,
because nothing is requested until it is opened.
"""

from __future__ import annotations

import contextlib
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import yaml
from playwright.sync_api import Page, expect

from web.tests.test_admin_browser import (
    ACCOUNTS,
    ADMIN_IDENTITY,
    AUDIT,
    SETTINGS,
    TIERS_RESPONSE,
    _json,
    _route_identity,
)

pytestmark = pytest.mark.browser

REPO_ROOT = Path(__file__).resolve().parents[2]


def _admin_catalogue(lang: str) -> dict:
    return yaml.safe_load(
        (REPO_ROOT / "web" / "i18n" / f"{lang}.yaml").read_text(encoding="utf-8")
    )["runtime"]["admin"]


def _analytics_strings(lang: str) -> dict:
    return _admin_catalogue(lang)["analytics"]


def _people_of(lang: str) -> str:
    return _admin_catalogue(lang)["people"]["of"]


def _citation_row(
    *,
    scope="total",
    bucket=None,
    turns=0,
    turns_uncited=0,
    turns_no_retrieval=0,
    cited_total=0,
    retrieved_total=0,
):
    return {
        "scope": scope,
        "bucket": bucket,
        "turns": turns,
        "turns_uncited": turns_uncited,
        "turns_no_retrieval": turns_no_retrieval,
        "cited_total": cited_total,
        "retrieved_total": retrieved_total,
    }


def _question_row(question, *, asks=2, uncited=0, askers=None, from_faq=False):
    return {
        "question": question,
        "asks": asks,
        "uncited": uncited,
        "askers": askers,
        "from_faq": from_faq,
    }


def _route_operational(page: Page) -> None:
    """Everything the console asks for at boot that is NOT this feature's: the
    four Overview reads `_overview_console` routes, plus `/admin/api/settings`.

    Settings is read by no assertion here and is routed anyway. `admin.js`
    boots every tab's loader, not just the active one, so an unrouted settings
    request reaches the live testing server, is refused 403 for the Playwright
    reader session, and toasts "Could not load settings." — and a test that
    asserts `#toast` stays hidden then fails on somebody else's request
    (`test_people_pager_out_of_order_responses_resolve_correctly` routes around
    the same trap).
    """
    _route_identity(page, status=200, body=ADMIN_IDENTITY)
    page.route("**/admin/api/tiers", lambda route: _json(route, TIERS_RESPONSE))
    page.route(
        "**/admin/api/registrations",
        lambda route: _json(route, {"signup_enabled": True, "default": True}),
    )
    page.route("**/admin/api/audit*", lambda route: _json(route, AUDIT))
    page.route(
        "**/admin/api/users?*",
        lambda route: _json(route, {"users": list(ACCOUNTS), "total": 1290}),
    )
    page.route("**/admin/api/settings", lambda route: _json(route, SETTINGS))


def _analytics_console(
    page: Page,
    *,
    citations=(),
    citations_status=200,
    questions=(),
    uncited=None,
    questions_status=200,
    uncited_status=None,
    lang="",
    delay_ms=None,
) -> None:
    """Open the console with the four operational routes `_overview_console`
    uses, PLUS the three analytics requests routed to canned payloads, then
    open the Analytics tab — which is what fires them.

    `uncited` defaults to mirroring `questions` — most tests do not care that
    the two `order=` calls can return different rows, and only the tests that
    do pass it explicitly. Distinguishing the two `questions` requests by the
    `order` query parameter is the wire contract (`impl-common.md`): the
    client sends the SAME path twice, ranked differently. `uncited_status`
    fails only the `order=uncited` one, which is how one of the two requests
    behind the same path can be shown to fail on its own.
    """
    _route_operational(page)

    uncited_rows = questions if uncited is None else uncited

    def citations_handler(route):
        if delay_ms:
            page.wait_for_timeout(delay_ms)
        route.fulfill(
            status=citations_status,
            content_type="application/json",
            body=json.dumps({"stats": list(citations)}),
        )

    def questions_handler(route):
        if delay_ms:
            page.wait_for_timeout(delay_ms)
        order = parse_qs(urlparse(route.request.url).query).get("order", ["asks"])[0]
        this_one = order == "uncited"
        rows = uncited_rows if this_one else questions
        route.fulfill(
            status=uncited_status if this_one and uncited_status else questions_status,
            content_type="application/json",
            body=json.dumps({"questions": list(rows)}),
        )

    page.route("**/admin/api/analytics/citations*", citations_handler)
    page.route("**/admin/api/analytics/questions*", questions_handler)

    page.goto(f"/admin?testing=true{lang}")
    expect(page.locator("#admin-console")).to_be_visible()
    page.locator("#tab-analytics").click()
    expect(page.locator("#panel-analytics")).to_be_visible()


def _zone(page: Page, index: int):
    """The Nth `<section class="admin-section">` direct child of
    `#analytics-results`: 0 = citation quality, 1 = recurring questions,
    2 = uncited (when present). Indexing by position rather than content is
    what lets a test find "the recurring-questions zone" whether it is
    rendering a notice, an unavailable line, or a table.
    """
    return page.locator("#analytics-results > .admin-section").nth(index)


# ── Zone 3 (recurring questions): the privacy floor is not a fault ──────────


def test_an_empty_question_list_reads_as_a_privacy_rule_not_a_fault(browser_page: Page):
    """`questions: []` is the two-account floor working, not an empty result
    that looks broken. It must read as a stated policy, and zone 4 (uncited
    questions) is omitted entirely rather than showing its own empty table
    under a notice that already explained why the list above it is empty.
    """
    strings = _analytics_strings("en")
    _analytics_console(
        browser_page,
        citations=[_citation_row(turns=12, turns_uncited=2, turns_no_retrieval=1)],
        questions=[],
    )

    expect(browser_page.locator("#analytics-results > .admin-section")).to_have_count(2)

    zone = _zone(browser_page, 1)
    notice = zone.locator(".admin-notice")
    expect(notice).to_be_visible()
    # The lead is the state and stays visible; the reason behind it is standing
    # context and sits in the lead's own closed popup.
    lead = notice.locator("strong")
    expect(lead).to_be_visible()
    expect(lead).to_have_text(strings["questions"]["floorEmpty"], use_inner_text=True)
    why = lead.locator(".admin-info-pop")
    expect(why).to_have_text(strings["questions"]["floorWhy"])
    expect(why).to_be_hidden()
    expect(zone.locator(".admin-empty")).to_have_count(0)


def test_a_failed_question_request_is_not_shown_as_the_privacy_floor(browser_page: Page):
    """A 500 must never be read as "nobody cleared the floor yet" — the two
    look nothing alike from the operator's side unless the code merges them.
    """
    unavailable = _admin_catalogue("en")["overview"]["unavailable"]
    _analytics_console(
        browser_page,
        citations=[_citation_row(turns=12, turns_uncited=2, turns_no_retrieval=1)],
        questions_status=500,
    )

    zone = _zone(browser_page, 1)
    expect(zone.locator(".admin-empty")).to_have_text(unavailable)
    expect(zone.locator(".admin-notice")).to_have_count(0)

    # Partial failure stands alone: the citation zone above it is unaffected.
    citation_zone = _zone(browser_page, 0)
    expect(citation_zone.locator(".admin-empty")).to_have_count(0)
    expect(citation_zone.locator(".admin-facts")).to_be_visible()


# ── Zone 2 (citation quality): small-n honesty ───────────────────────────────


@pytest.mark.parametrize(("turns", "expect_percent"), [(9, False), (10, True)])
def test_percentages_are_withheld_below_ten_saved_answers(
    browser_page: Page, turns: int, expect_percent: bool
):
    strings = _analytics_strings("en")
    _analytics_console(
        browser_page,
        citations=[
            _citation_row(turns=turns, turns_uncited=2, turns_no_retrieval=1, cited_total=turns)
        ],
        questions=[],
    )

    citation_zone = _zone(browser_page, 0)
    expect(citation_zone.locator(".admin-fact-exact")).to_have_count(2 if expect_percent else 0)
    hint = citation_zone.locator(".admin-form-hint")
    if expect_percent:
        expect(hint).to_have_count(0)
    else:
        expect(hint).to_have_text(strings["quality"]["smallSample"])


def test_zero_saved_answers_is_an_empty_state_not_zero_percent(browser_page: Page):
    """`turns === 0` (here: no `total` row at all) is the empty state, never
    `0%`, `NaN` or `—` — a dash reads as FAILED everywhere else in this
    console, so it must not leak into a state that succeeded with nothing to
    report.
    """
    strings = _analytics_strings("en")
    _analytics_console(
        browser_page,
        citations=[],
        questions=[_question_row("Renew a licence", asks=2, uncited=0, askers=2)],
    )

    citation_zone = _zone(browser_page, 0)
    expect(citation_zone.locator(".admin-empty")).to_have_text(strings["quality"]["empty"])

    region_text = browser_page.locator("#analytics-results").inner_text()
    assert "%" not in region_text, region_text
    assert "NaN" not in region_text, region_text
    assert "—" not in region_text, region_text  # em dash: means FAILED, never "nothing yet"


def test_a_turn_split_shows_both_failure_kinds(browser_page: Page):
    """The five tiles, in order, with the numbers the plan's correction 3
    exists for: "found nothing" and "found something, cited none" are
    disjoint failures and must print as two different figures.
    """
    strings = _analytics_strings("en")
    quality = strings["quality"]
    total = _citation_row(
        turns=40, turns_uncited=5, turns_no_retrieval=3, cited_total=88, retrieved_total=100
    )
    _analytics_console(browser_page, citations=[total], questions=[])

    facts = _zone(browser_page, 0).locator(".admin-facts .admin-fact")
    expect(facts).to_have_count(5)

    expect(facts.nth(0).locator("dt")).to_have_text(quality["turns"])
    expect(facts.nth(0).locator("dd .admin-cell-machine")).to_have_text("40")

    expect(facts.nth(1).locator("dt")).to_have_text(quality["uncited"])
    dd1 = facts.nth(1).locator("dd")
    expect(dd1.locator(".admin-cell-machine").nth(0)).to_have_text("5")
    expect(dd1.locator(".admin-cell-machine").nth(1)).to_have_text("40")
    expect(dd1.locator(".admin-fact-exact")).to_have_text("13%")  # round(5/40*100)

    expect(facts.nth(2).locator("dt")).to_have_text(quality["noRetrieval"])
    dd2 = facts.nth(2).locator("dd")
    expect(dd2.locator(".admin-cell-machine").nth(0)).to_have_text("3")
    expect(dd2.locator(".admin-cell-machine").nth(1)).to_have_text("40")
    expect(dd2.locator(".admin-fact-exact")).to_have_text("8%")  # round(3/40*100)

    expect(facts.nth(3).locator("dt")).to_have_text(quality["citedPerAnswer"])
    expect(facts.nth(3).locator("dd .admin-cell-machine")).to_have_text("2.2")  # 88/40, toFixed(1)

    expect(facts.nth(4).locator("dt")).to_have_text(quality["retrievedPerAnswer"])
    expect(facts.nth(4).locator("dd .admin-cell-machine")).to_have_text("2.5")  # 100/40


def test_the_breakdown_table_groups_by_language_then_scope(browser_page: Page):
    """Two `<tbody>` groups, language first then scope; an unknown bucket
    prints raw rather than a missing catalogue key; a row whose `scope` is
    not `lang`/`category` (a future grouping-sets addition) is dropped
    entirely rather than crashing or printing a stray group.
    """
    strings = _analytics_strings("en")
    quality = strings["quality"]
    stats = [
        _citation_row(
            turns=40, turns_uncited=5, turns_no_retrieval=3, cited_total=88, retrieved_total=100
        ),
        _citation_row(
            scope="lang",
            bucket="en",
            turns=20,
            turns_uncited=2,
            turns_no_retrieval=1,
            cited_total=40,
            retrieved_total=45,
        ),
        _citation_row(
            scope="lang",
            bucket="ar",
            turns=15,
            turns_uncited=2,
            turns_no_retrieval=1,
            cited_total=30,
            retrieved_total=35,
        ),
        _citation_row(
            scope="lang",
            bucket="fr",
            turns=5,
            turns_uncited=1,
            turns_no_retrieval=1,
            cited_total=10,
            retrieved_total=12,
        ),
        _citation_row(
            scope="category",
            bucket="regulatory",
            turns=25,
            turns_uncited=3,
            turns_no_retrieval=2,
            cited_total=50,
            retrieved_total=55,
        ),
        _citation_row(
            scope="category",
            bucket="zzz-unknown",
            turns=5,
            turns_uncited=1,
            turns_no_retrieval=0,
            cited_total=10,
            retrieved_total=10,
        ),
        _citation_row(
            scope="day",
            bucket="2026-09-01",
            turns=999,
            turns_uncited=999,
            turns_no_retrieval=999,
            cited_total=999,
            retrieved_total=999,
        ),
    ]
    _analytics_console(browser_page, citations=stats, questions=[])

    table = _zone(browser_page, 0).locator("table.admin-table")
    expect(table).to_be_visible()

    tbodies = table.locator("tbody")
    expect(tbodies).to_have_count(2)

    lang_group = tbodies.nth(0)
    expect(lang_group.locator("tr").first.locator("th[scope='rowgroup']")).to_have_text(
        quality["byLanguage"]
    )
    expect(lang_group.locator("tr").first.locator("th[scope='rowgroup']")).to_have_attribute(
        "colspan", "6"
    )
    lang_rows = lang_group.locator("tr").locator("th[scope='row']")
    expect(lang_rows).to_have_count(3)
    expect(lang_rows.nth(0)).to_have_text(strings["languageEn"])
    expect(lang_rows.nth(1)).to_have_text(strings["languageAr"])
    expect(lang_rows.nth(2)).to_have_text("fr")  # unknown lang value: raw, not a lookup key

    category_group = tbodies.nth(1)
    expect(category_group.locator("tr").first.locator("th[scope='rowgroup']")).to_have_text(
        quality["byScope"]
    )
    category_rows = category_group.locator("tr").locator("th[scope='row']")
    expect(category_rows).to_have_count(2)
    expect(category_rows.nth(0)).to_have_text(strings["scope"]["regulatory"])
    expect(category_rows.nth(1)).to_have_text("zzz-unknown")  # unknown category: raw

    # The "day" row never formed a group at all.
    expect(table).not_to_contain_text("2026-09-01")
    expect(table).not_to_contain_text("999")

    weights = browser_page.evaluate(
        """() => {
          const t = document.querySelector('#analytics-results table.admin-table');
          const th = t.querySelector('tbody th[scope="row"]');
          const td = t.querySelector('tbody td');
          return { th: getComputedStyle(th).fontWeight, td: getComputedStyle(td).fontWeight };
        }"""
    )
    print(
        f"[report] en th[scope=row] font-weight={weights['th']} vs td font-weight={weights['td']}"
    )


# ── RTL and bidi correctness ─────────────────────────────────────────────────


def test_a_ratio_reads_count_then_total_in_arabic(browser_page: Page):
    """Bounding boxes, not text: in RTL the count (first in the DOM) must sit
    visually to the RIGHT of the total, which is the only way "5 من 40"
    reads count-then-total to an Arabic reader instead of the reverse.
    """
    strings = _analytics_strings("ar")
    of_ar = _people_of("ar")
    browser_page.set_viewport_size({"width": 1280, "height": 900})
    _analytics_console(
        browser_page,
        citations=[
            _citation_row(
                turns=20, turns_uncited=5, turns_no_retrieval=2, cited_total=30, retrieved_total=40
            )
        ],
        questions=[],
        lang="&lang=ar",
    )

    tile = _zone(browser_page, 0).locator(".admin-facts .admin-fact").nth(1)
    expect(tile.locator("dt")).to_have_text(strings["quality"]["uncited"])
    expect(tile.locator("dd")).to_contain_text(of_ar)

    machines = tile.locator(".admin-cell-machine")
    expect(machines).to_have_count(2)
    for i in range(2):
        expect(machines.nth(i)).to_have_attribute("dir", "ltr")

    count_box = machines.nth(0).bounding_box()
    total_box = machines.nth(1).bounding_box()
    assert count_box and total_box, "ratio spans have no layout box"
    assert count_box["x"] > total_box["x"], (
        f"count span (x={count_box['x']}) is not right of the total span "
        f"(x={total_box['x']}) — RTL reading order should be count → "
        f"{of_ar} → total"
    )


def test_analytics_numbers_stay_latin_and_carry_no_bidi_marks_in_arabic(browser_page: Page):
    _analytics_console(
        browser_page,
        citations=[
            _citation_row(
                turns=20, turns_uncited=5, turns_no_retrieval=2, cited_total=30, retrieved_total=40
            ),
            _citation_row(
                scope="lang",
                bucket="ar",
                turns=20,
                turns_uncited=5,
                turns_no_retrieval=2,
                cited_total=30,
                retrieved_total=40,
            ),
        ],
        questions=[_question_row("ما هي المدة؟", asks=6, uncited=1, askers=None)],
        lang="&lang=ar",
    )

    machine_texts = browser_page.eval_on_selector_all(
        "#analytics-body .admin-cell-machine", "els => els.map(e => e.textContent)"
    )
    assert machine_texts, "no machine-value spans rendered — nothing to check"
    bidi_marks = "‎‏‪‫‬‭‮⁦⁧⁨⁩"
    for text in machine_texts:
        assert re.match(r"^[0-9–.: %-]+$", text), f"non-Latin machine value: {text!r}"
        assert not any(ch in bidi_marks for ch in text), f"bidi mark in machine value: {text!r}"

    region_text = browser_page.locator("#analytics-body").inner_text()
    arabic_indic_digits = [ch for ch in region_text if "٠" <= ch <= "٩" or "۰" <= ch <= "۹"]
    assert not arabic_indic_digits, (
        f"Arabic-Indic digits leaked into the region: {arabic_indic_digits!r}"
    )


def test_question_text_is_never_parsed_as_html(browser_page: Page):
    payload = '<img src=x onerror="window.__pwned=1">'
    _analytics_console(
        browser_page,
        citations=[
            _citation_row(
                turns=5, turns_uncited=1, turns_no_retrieval=1, cited_total=8, retrieved_total=9
            )
        ],
        questions=[_question_row(payload, asks=2, uncited=0, askers=2)],
    )

    region = browser_page.locator("#analytics-body")
    expect(region.locator("img")).to_have_count(0)
    assert browser_page.evaluate("() => window.__pwned") is None
    expect(region).to_contain_text(payload)


def test_a_long_question_collapses_into_details_without_splitting_a_grapheme(browser_page: Page):
    """Built with `chr`/`\\u` escapes, never typed through a shell — Arabic
    text arrives reversed from a terminal, and this string's correctness
    depends on its exact code points.

    `unit` is LAM + COMBINING SHADDA: one grapheme, two code points, the
    shape a naive `slice()` (UTF-16 code units) or a bare `Array.from`
    (code points, not grapheme clusters) can split. `emoji` is an astral
    character — a surrogate pair in UTF-16 — placed so the 160-grapheme cut
    falls right after it.
    """
    unit = "لّ"
    emoji = "\U0001f600"
    cut = 158
    tail_units = 7
    question = unit * cut + emoji + unit * tail_units  # 158 + 1 + 7 = 166 graphemes

    _analytics_console(
        browser_page,
        citations=[
            _citation_row(
                turns=5, turns_uncited=1, turns_no_retrieval=1, cited_total=8, retrieved_total=9
            )
        ],
        questions=[_question_row(question, asks=2, uncited=0, askers=2)],
    )

    details = browser_page.locator("#analytics-results details")
    expect(details).to_have_count(1)
    summary = details.locator("summary")
    summary_text = summary.text_content()
    assert summary_text is not None

    has_lone_surrogate = browser_page.evaluate(
        "(t) => /[\\uD800-\\uDBFF](?![\\uDC00-\\uDFFF])|(?<![\\uD800-\\uDBFF])[\\uDC00-\\uDFFF]/.test(t)",
        summary_text,
    )
    assert not has_lone_surrogate, f"summary carries a lone surrogate: {summary_text!r}"

    core = summary_text[:-1] if summary_text.endswith("…") else summary_text
    assert question.startswith(core), "summary is not a literal prefix of the question"
    if len(core) < len(question):
        next_char = question[len(core)]
        assert unicodedata.combining(next_char) == 0, (
            "the cut landed between a base character and its own combining mark"
        )

    summary.focus()
    browser_page.keyboard.press("Enter")
    expect(details).to_have_attribute("open", "")
    expect(browser_page.locator("#analytics-results")).to_contain_text(question)


# ── The recurring-questions table ────────────────────────────────────────────


def test_the_accounts_column_is_absent_until_a_row_has_an_exact_count(browser_page: Page):
    strings = _analytics_strings("en")
    _analytics_console(
        browser_page,
        citations=[_citation_row(turns=12, turns_uncited=2, turns_no_retrieval=1)],
        questions=[
            _question_row("Renew a licence", asks=3, uncited=0, askers=None),
            _question_row("Import permit steps", asks=2, uncited=1, askers=None),
        ],
    )

    table = _zone(browser_page, 1).locator("table.admin-table")
    headers = table.locator("thead th")
    expect(headers).to_have_count(3)
    for i in range(3):
        expect(headers.nth(i)).not_to_have_text(strings["questions"]["askers"])


def test_a_bucketed_row_reads_two_to_four_beside_an_exact_one(browser_page: Page):
    strings = _analytics_strings("en")
    _analytics_console(
        browser_page,
        citations=[_citation_row(turns=12, turns_uncited=2, turns_no_retrieval=1)],
        questions=[
            _question_row("Renew a licence", asks=5, uncited=1, askers=None),
            _question_row("Import permit steps", asks=9, uncited=0, askers=7),
        ],
    )

    table = _zone(browser_page, 1).locator("table.admin-table")
    expect(table.locator("thead th").nth(2)).to_have_text(strings["questions"]["askers"])
    rows = table.locator("tbody tr")
    # Columns: question(0), asks(1), askers(2), uncited(3).
    expect(rows.nth(0).locator("td").nth(2)).to_have_text("2–4")
    expect(rows.nth(1).locator("td").nth(2)).to_have_text("7")


def test_a_sidebar_question_carries_its_mark(browser_page: Page):
    strings = _analytics_strings("en")
    _analytics_console(
        browser_page,
        citations=[_citation_row(turns=12, turns_uncited=2, turns_no_retrieval=1)],
        questions=[
            _question_row("Renew a licence", asks=3, uncited=0, askers=2, from_faq=True),
            _question_row("Import permit steps", asks=2, uncited=1, askers=2, from_faq=False),
        ],
    )

    rows = _zone(browser_page, 1).locator("table.admin-table tbody tr")
    expect(rows.nth(0).locator("td").first.locator("span.admin-mark")).to_have_text(
        strings["questions"]["fromFaq"]
    )
    expect(rows.nth(1).locator("td").first.locator("span.admin-mark")).to_have_count(0)


# ── Zone 4: uncited questions ─────────────────────────────────────────────────


def test_the_uncited_zone_lists_only_rows_with_an_uncited_answer(browser_page: Page):
    """`order=uncited` re-ranks the same rows; the CLIENT filters to the ones
    that actually carry an uncited answer (the endpoint returns the full set,
    not a pre-filtered one — the client owns the filter per the DOM contract).
    """
    _analytics_console(
        browser_page,
        citations=[_citation_row(turns=12, turns_uncited=2, turns_no_retrieval=1)],
        questions=[_question_row("Renew a licence", asks=3, uncited=1, askers=2)],
        uncited=[
            _question_row("Renew a licence", asks=3, uncited=3, askers=2),
            _question_row("Fully cited question", asks=4, uncited=0, askers=2),
            _question_row("Import permit steps", asks=2, uncited=1, askers=2),
        ],
    )

    expect(browser_page.locator("#analytics-results > .admin-section")).to_have_count(3)
    rows = _zone(browser_page, 2).locator("table.admin-table tbody tr")
    expect(rows).to_have_count(2)
    expect(rows.nth(0)).to_contain_text("Renew a licence")
    expect(rows.nth(1)).to_contain_text("Import permit steps")
    expect(_zone(browser_page, 2)).not_to_contain_text("Fully cited question")


def test_the_uncited_zone_shows_its_own_empty_state_when_every_answer_was_cited(browser_page: Page):
    strings = _analytics_strings("en")
    _analytics_console(
        browser_page,
        citations=[_citation_row(turns=12, turns_uncited=2, turns_no_retrieval=1)],
        questions=[_question_row("Renew a licence", asks=3, uncited=1, askers=2)],
        uncited=[_question_row("Renew a licence", asks=3, uncited=0, askers=2)],
    )

    uncited_zone = _zone(browser_page, 2)
    expect(uncited_zone.locator(".admin-empty")).to_have_text(strings["uncitedQuestions"]["empty"])
    expect(uncited_zone.locator("table")).to_have_count(0)


# ── Timing and failure isolation ──────────────────────────────────────────────


def test_a_slow_analytics_request_holds_the_results_region_busy_until_it_lands(
    browser_page: Page,
):
    """The region says it is counting while it counts, and stops saying so the
    moment the figures land. That Overview never waits on this at all is
    `test_opening_the_console_on_overview_fires_no_analytics_request`'s claim.
    """
    strings = _analytics_strings("en")
    _analytics_console(
        browser_page,
        citations=[_citation_row(turns=12, turns_uncited=2, turns_no_retrieval=1)],
        questions=[_question_row("Renew a licence", asks=3, uncited=1, askers=2)],
        delay_ms=1500,
    )

    results = browser_page.locator("#analytics-results")
    expect(results).to_have_attribute("aria-busy", "true")
    expect(results).to_contain_text(strings["loading"])

    browser_page.wait_for_timeout(1700)
    expect(results).to_have_attribute("aria-busy", "false")
    expect(results).not_to_contain_text(strings["loading"])


def test_a_failed_analytics_request_raises_no_toast_and_no_page_error(browser_page: Page):
    errors = []
    browser_page.on("pageerror", lambda err: errors.append(str(err)))

    _analytics_console(
        browser_page,
        citations_status=500,
        questions_status=500,
    )
    browser_page.wait_for_timeout(300)

    expect(browser_page.locator("#toast")).to_have_class("toast-notification hidden")
    assert errors == [], f"page threw: {errors}"


def test_the_counted_at_stamp_is_a_machine_value(browser_page: Page):
    for lang, lang_param in [("en", ""), ("ar", "&lang=ar")]:
        strings = _analytics_strings(lang)
        _analytics_console(
            browser_page,
            citations=[
                _citation_row(
                    turns=12,
                    turns_uncited=1,
                    turns_no_retrieval=1,
                    cited_total=20,
                    retrieved_total=24,
                )
            ],
            questions=[_question_row("Renew a licence", asks=2, uncited=0, askers=2)],
            lang=lang_param,
        )

        stamp = browser_page.locator("#analytics-stamp")
        prefix = strings["countedAt"].split("{time}")[0]
        expect(stamp).to_contain_text(prefix)

        machine = stamp.locator("span.admin-cell-machine")
        expect(machine).to_have_attribute("dir", "ltr")
        text = machine.text_content()
        assert text is not None
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", text), text


def test_the_analytics_region_does_not_overflow_at_390px_in_arabic(browser_page: Page):
    browser_page.set_viewport_size({"width": 390, "height": 844})
    _analytics_console(
        browser_page,
        citations=[
            _citation_row(
                turns=40, turns_uncited=5, turns_no_retrieval=3, cited_total=88, retrieved_total=100
            ),
            _citation_row(
                scope="lang",
                bucket="en",
                turns=25,
                turns_uncited=3,
                turns_no_retrieval=2,
                cited_total=55,
                retrieved_total=60,
            ),
            _citation_row(
                scope="lang",
                bucket="ar",
                turns=15,
                turns_uncited=2,
                turns_no_retrieval=1,
                cited_total=33,
                retrieved_total=40,
            ),
            _citation_row(
                scope="category",
                bucket="regulatory",
                turns=20,
                turns_uncited=2,
                turns_no_retrieval=1,
                cited_total=44,
                retrieved_total=48,
            ),
            _citation_row(
                scope="category",
                bucket="all",
                turns=20,
                turns_uncited=3,
                turns_no_retrieval=2,
                cited_total=44,
                retrieved_total=52,
            ),
        ],
        questions=[
            _question_row("ما هي مدة الترخيص؟", asks=5, uncited=1, askers=None, from_faq=True),
            _question_row("هل يجوز الاستيراد بدون ترخيص؟", asks=9, uncited=0, askers=7),
        ],
        uncited=[_question_row("ما هي مدة الترخيص؟", asks=5, uncited=1, askers=None)],
        lang="&lang=ar",
    )

    overflows = browser_page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert not overflows, (
        f"scrollWidth={browser_page.evaluate('() => document.documentElement.scrollWidth')} "
        f"clientWidth={browser_page.evaluate('() => document.documentElement.clientWidth')}"
    )

    wrap = browser_page.evaluate(
        """() => {
          const ths = [...document.querySelectorAll('#analytics-body table thead th')];
          const th = ths[ths.length - 1];
          const rect = th.getBoundingClientRect();
          const cs = getComputedStyle(th);
          let lh = parseFloat(cs.lineHeight);
          if (Number.isNaN(lh)) lh = parseFloat(cs.fontSize) * 1.2;
          return { height: rect.height, lineHeight: lh, text: th.textContent };
        }"""
    )
    lines = round(wrap["height"] / wrap["lineHeight"]) if wrap["lineHeight"] else None
    # `wrap["text"]` is Arabic and not ASCII-safe on every console codepage
    # (Windows cp1252 raises on `print`), so only its length is reported here.
    print(
        f"[report] retrievedPerAnswer header wraps to ~{lines} line(s) at 390px Arabic "
        f"(height={wrap['height']:.1f}px, line-height={wrap['lineHeight']:.1f}px, "
        f"text_length={len(wrap['text'])})"
    )

    weights = browser_page.evaluate(
        """() => {
          const t = document.querySelector('#analytics-results table.admin-table');
          const th = t.querySelector('tbody th[scope="row"]');
          const td = t.querySelector('tbody td');
          return { th: getComputedStyle(th).fontWeight, td: getComputedStyle(td).fontWeight };
        }"""
    )
    print(
        f"[report] ar th[scope=row] font-weight={weights['th']} vs td font-weight={weights['td']}"
    )


def test_a_select_keeps_its_chevron_clearance_on_the_chevron_side_in_arabic(browser_page: Page):
    """`select.admin-input`'s base rule already gives the chevron 48px of
    clearance via `padding-inline-end`, which is logical and mirrors on its
    own under `[dir="rtl"]`. The old RTL override un-mirrored it back to a
    physical left/right split — 12px under the chevron (now sitting on the
    physical left) and 48px on the right where nothing is — so a long select
    label could run under the chevron. The clearance must stay on whichever
    physical side the chevron itself is on.
    """
    _analytics_console(
        browser_page,
        citations=[
            _citation_row(
                turns=40, turns_uncited=5, turns_no_retrieval=3, cited_total=88, retrieved_total=100
            )
        ],
        lang="&lang=ar",
    )
    expect(browser_page.locator("#analytics-window")).to_be_visible()

    styles = browser_page.evaluate(
        """() => {
          const select = document.getElementById('analytics-window');
          const cs = getComputedStyle(select);
          return {
            paddingInlineStart: cs.paddingInlineStart,
            paddingInlineEnd: cs.paddingInlineEnd,
            paddingLeft: cs.paddingLeft,
            backgroundPositionX: cs.backgroundPositionX,
          };
        }"""
    )
    inline_start = float(styles["paddingInlineStart"].rstrip("px"))
    inline_end = float(styles["paddingInlineEnd"].rstrip("px"))
    assert inline_end > inline_start, f"chevron clearance is not on the inline-end side: {styles}"

    padding_left = float(styles["paddingLeft"].rstrip("px"))
    assert padding_left == inline_end, (
        "paddingLeft does not match paddingInlineEnd — the clearance is not "
        f"on the chevron's physical side (left, in RTL): {styles}"
    )

    # The chevron itself must be on the left. Pinned right, as Bootstrap's LTR
    # build leaves it, Chromium reports `calc(100% - 12px)` per layer; pinned
    # left it reports a bare length. No token value is assumed.
    assert "%" not in styles["backgroundPositionX"], styles


# ── The period and language controls ─────────────────────────────────────────
#
# Every test below drives the two selects with REAL KEYS. `select_option()`
# sets a value without the user activation a browser gives a keypress, and two
# of these are about what happens to FOCUS across a repaint — which a synthetic
# value change cannot observe at all.

ANALYTICS_FILTERS_KEY = "sfda-admin-analytics-filters"


def _window_stats(days: str) -> dict:
    """One `total` row whose `turns` encodes the window that answered.

    The "Saved answers" tile then reads 3000 for thirty days and 9000 for
    ninety. Without a marker, an out-of-order test can only assert that the DOM
    did not change, which is also what a completely broken refetch looks like.
    """
    return {
        "stats": [
            _citation_row(
                turns=int(days) * 100,
                turns_uncited=3,
                turns_no_retrieval=2,
                cited_total=31,
                retrieved_total=112,
            )
        ]
    }


def _filtered_console(
    page: Page, *, calls, hold_days=None, hold_only=None, held=None, lang=""
) -> None:
    """The Analytics tab, opened, with its endpoints answering per window.

    `hold_days` leaves that window's routes unanswered in `held` — the
    hold-and-release shape `test_people_pager_out_of_order_responses_resolve_correctly`
    already uses (`test_admin_browser.py:1736`). A `wait_for_timeout` inside a
    sync route handler blocks the driver instead, which serialises the very
    race being tested; that was measured, not assumed.

    `hold_only` narrows the hold to one endpoint, which is what separates the
    two races the client guards against. Holding all three means every request
    is still on the wire when the next choice aborts them — the ABORT's case.
    Holding only `citations` lets the two `questions` requests RESOLVE first,
    so the abandoned window arrives half-answered — the case an abort cannot
    reach and the sequence token exists for.
    """
    _route_operational(page)

    def analytics(route):
        url = route.request.url
        calls.append(url)
        days = parse_qs(urlparse(url).query).get("days", [""])[0]
        if hold_days is not None and days == hold_days and (hold_only or "") in url:
            held.append(route)
            return
        _json(route, _window_stats(days) if "citations" in url else {"questions": []})

    page.route("**/admin/api/analytics/**", analytics)

    page.goto(f"/admin?testing=true{lang}")
    expect(page.locator("#admin-console")).to_be_visible()
    page.locator("#tab-analytics").click()
    expect(page.locator("#analytics-window")).to_be_visible()


def _windows_asked(calls) -> list:
    return [parse_qs(urlparse(url).query).get("days", [""])[0] for url in calls]


def _saved_answers(page: Page):
    """The first tile — "Saved answers" — which carries the window marker."""
    return _zone(page, 0).locator(".admin-facts .admin-fact").first.locator("dd")


def test_the_controls_are_one_labelled_group_that_does_not_sit_in_the_results(
    browser_page: Page,
):
    """The controls belong to the lead zone, which a results repaint never
    touches. A test that only checked they exist would still pass if they were
    rebuilt on every fetch — which is the bug this layout exists to prevent.
    """
    strings = _analytics_strings("en")
    calls = []
    _filtered_console(browser_page, calls=calls)

    controls = browser_page.locator("#analytics-body .admin-filters")
    expect(controls).to_have_attribute("role", "group")
    expect(controls).to_have_attribute("aria-label", strings["filtersLabel"])
    expect(controls).to_have_attribute("aria-controls", "analytics-results")
    expect(browser_page.locator("#analytics-results .admin-filters")).to_have_count(0)

    expect(browser_page.locator("#analytics-window")).to_have_value("30")
    expect(browser_page.locator("#analytics-lang")).to_have_value("")
    expect(browser_page.locator("#analytics-refresh")).to_have_text(strings["refresh"])
    assert _windows_asked(calls) == ["30", "30", "30"]


def test_changing_the_period_refetches_all_three_and_keeps_focus_on_the_select(
    browser_page: Page,
):
    """A repaint that drops focus makes the keyboard useless for the control an
    operator just used — which is the whole reason the results region is a
    separate element from the lead zone the selects live in."""
    calls = []
    _filtered_console(browser_page, calls=calls)
    expect(_saved_answers(browser_page)).to_have_text("3000")
    calls.clear()

    browser_page.locator("#analytics-window").focus()
    browser_page.keyboard.press("ArrowDown")  # 30 -> 90, a real key on a real select

    expect(_saved_answers(browser_page)).to_have_text("9000")
    assert _windows_asked(calls) == ["90", "90", "90"], "all three requests carry the new window"
    assert browser_page.evaluate("() => document.activeElement.id") == "analytics-window"
    # And the refetch announced itself, which the first load deliberately does not.
    expect(browser_page.locator("#analytics-status")).to_have_text(
        _analytics_strings("en")["updated"]
    )


def _watch_the_results_region(page: Page) -> None:
    """Record every state the region passes THROUGH, not only the one it
    settles in.

    Playwright's assertions retry, so `to_have_count(0)` on an unavailable
    line is satisfied by a region that showed one for 80ms and then replaced
    it — which is exactly the flash these two tests exist to forbid. An
    observer is the only way to assert on a state that is gone by the time a
    test can look.
    """
    page.evaluate(
        """() => {
          window.__tiles = [];
          window.__unavailable = 0;
          const region = document.getElementById('analytics-results');
          const record = () => {
            const dd = region.querySelector('.admin-fact dd');
            if (dd) window.__tiles.push(dd.textContent);
            window.__unavailable += region.querySelectorAll('.admin-empty').length;
          };
          new MutationObserver(record).observe(region, {
            childList: true, subtree: true, characterData: true,
          });
        }"""
    )


def test_out_of_order_analytics_responses_resolve_to_the_last_choice(browser_page: Page):
    """The race an abort CANNOT win.

    Only the citations request is held, so the abandoned window's two
    `questions` requests resolve normally before the next choice is made. The
    abort then reaches one request out of three, and what stops that
    half-answered window from painting is the sequence token alone.
    """
    calls, held = [], []
    _filtered_console(browser_page, calls=calls, hold_days="7", hold_only="citations", held=held)
    expect(_saved_answers(browser_page)).to_have_text("3000")
    _watch_the_results_region(browser_page)

    browser_page.locator("#analytics-window").focus()
    browser_page.keyboard.press("ArrowUp")  # 30 -> 7; its questions answer, citations held
    browser_page.wait_for_timeout(200)
    browser_page.keyboard.press("ArrowDown")  # back to 30, answers in full
    expect(browser_page.locator("#analytics-results")).to_have_attribute("aria-busy", "false")

    for route in held:  # the abandoned window answers LAST
        with contextlib.suppress(Exception):
            _json(route, _window_stats("7"))
    browser_page.wait_for_timeout(400)

    expect(_saved_answers(browser_page)).to_have_text("3000")
    seen = browser_page.evaluate("() => window.__tiles")
    assert "700" not in seen, f"the abandoned window reached the screen: {seen}"
    assert browser_page.evaluate("() => window.__unavailable") == 0, (
        "the half-answered window painted an unavailable zone before the current one landed"
    )


def test_an_aborted_refetch_is_not_shown_as_unavailable(browser_page: Page):
    """An abort is not a failure. The window it described is simply not the one
    on screen any more, and `admin.overview.unavailable` would report a fault
    where the operator merely changed their mind.

    All three requests are held here, so all three are aborted together — the
    case the AbortController owns, as opposed to the half-answered one above.
    """
    calls, held = [], []
    _filtered_console(browser_page, calls=calls, hold_days="7", held=held)
    expect(_saved_answers(browser_page)).to_have_text("3000")
    _watch_the_results_region(browser_page)

    browser_page.locator("#analytics-window").focus()
    browser_page.keyboard.press("ArrowUp")  # 30 -> 7, held, then abandoned
    browser_page.wait_for_timeout(200)
    browser_page.keyboard.press("ArrowDown")  # aborts the three held requests

    expect(_saved_answers(browser_page)).to_have_text("3000")
    expect(browser_page.locator("#analytics-results .admin-empty")).to_have_count(0)
    assert browser_page.evaluate("() => window.__unavailable") == 0, (
        "the abandoned window flashed an unavailable zone on its way out"
    )
    expect(browser_page.locator("#toast")).to_have_class("toast-notification hidden")


def test_old_figures_stay_visible_while_a_refetch_is_in_flight(browser_page: Page):
    """No skeleton and no emptying: the previous window's figures stay up,
    dimmed, until the next ones can replace them. The selects stay enabled —
    disabling the one an operator is holding drops their focus."""
    calls, held = [], []
    _filtered_console(browser_page, calls=calls, hold_days="7", held=held)
    expect(_saved_answers(browser_page)).to_have_text("3000")

    browser_page.locator("#analytics-window").focus()
    browser_page.keyboard.press("ArrowUp")  # 30 -> 7, held open

    results = browser_page.locator("#analytics-results")
    expect(results).to_have_attribute("aria-busy", "true")
    expect(_saved_answers(browser_page)).to_have_text("3000")
    # The visible dimming is deliberately late — 100ms — so a fast response
    # never flashes a grey region.
    expect(results).to_have_class("admin-panel-body is-busy-visual")
    expect(browser_page.locator("#analytics-window")).to_be_enabled()
    expect(browser_page.locator("#analytics-lang")).to_be_enabled()


def test_the_filter_choice_survives_the_language_toggle(browser_page: Page):
    """The toggle RELOADS the page, so without persistence every chosen period
    dies the moment an operator switches script."""
    calls = []
    _filtered_console(browser_page, calls=calls)
    expect(_saved_answers(browser_page)).to_have_text("3000")

    browser_page.locator("#analytics-window").focus()
    browser_page.keyboard.press("ArrowUp")  # 30 -> 7
    expect(_saved_answers(browser_page)).to_have_text("700")
    browser_page.locator("#analytics-lang").focus()
    browser_page.keyboard.press("ArrowDown")  # both languages -> English
    expect(browser_page.locator("#analytics-results")).to_have_attribute("aria-busy", "false")

    calls.clear()
    browser_page.goto("/admin?testing=true&lang=ar")
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-analytics").click()
    expect(browser_page.locator("#analytics-window")).to_have_value("7")
    expect(browser_page.locator("#analytics-lang")).to_have_value("en")

    asked = [parse_qs(urlparse(url).query) for url in calls]
    assert asked, "the restored window was never fetched"
    for query in asked:
        assert query["days"] == ["7"], query
        assert query["lang"] == ["en"], query


@pytest.mark.parametrize("stored", ['{"days": 1, "lang": "xx"}', "not json at all"])
def test_a_tampered_stored_filter_falls_back_to_the_defaults(browser_page: Page, stored: str):
    """`sessionStorage` is writable by anything on this origin and survives a
    deploy that changes what is valid, so the allow-list runs on the way OUT.
    Both failure shapes: a well-formed object holding values outside the lists
    (`days=1` would also defeat the RPC's seven-day floor), and text that is not
    JSON at all.
    """
    calls = []
    _filtered_console(browser_page, calls=calls)
    browser_page.evaluate(
        "([key, value]) => sessionStorage.setItem(key, value)",
        [ANALYTICS_FILTERS_KEY, stored],
    )

    calls.clear()
    browser_page.reload()
    expect(browser_page.locator("#admin-console")).to_be_visible()
    browser_page.locator("#tab-analytics").click()
    expect(browser_page.locator("#analytics-window")).to_have_value("30")
    expect(browser_page.locator("#analytics-lang")).to_have_value("")

    asked = [parse_qs(urlparse(url).query) for url in calls]
    assert asked, f"nothing was fetched after {stored!r}"
    for query in asked:
        assert query["days"] == ["30"], stored
        assert query.get("lang", [""]) == [""], stored


def test_refresh_refetches_with_the_current_choice(browser_page: Page):
    """Refresh is the retry this surface offers, and it must not quietly revert
    to the default window on the way."""
    calls = []
    _filtered_console(browser_page, calls=calls)
    browser_page.locator("#analytics-window").focus()
    browser_page.keyboard.press("ArrowDown")  # 30 -> 90
    expect(_saved_answers(browser_page)).to_have_text("9000")

    calls.clear()
    browser_page.locator("#analytics-refresh").click()
    expect(browser_page.locator("#analytics-results")).to_have_attribute("aria-busy", "false")
    assert _windows_asked(calls) == ["90", "90", "90"]
    expect(_saved_answers(browser_page)).to_have_text("9000")


# --- found in review ---


@pytest.mark.browser
def test_the_filter_selects_are_set_in_the_text_face_not_the_pager_mono(browser_page: Page):
    """`.admin-pager-select` is mono because a page size is a number. These two
    selects hold words, and the mono face has no Arabic: its fallback set
    "اللغتان" with every letter apart, in a console that otherwise joins them.
    The label beside each select is the reference for "the text face".
    """
    _filtered_console(browser_page, calls=[], lang="ar")

    for select_id in ("analytics-window", "analytics-lang"):
        faces = browser_page.evaluate(
            """(id) => {
              const select = document.getElementById(id);
              const label = document.querySelector(`label[for="${id}"]`);
              return [getComputedStyle(select).fontFamily, getComputedStyle(label).fontFamily];
            }""",
            select_id,
        )
        assert faces[0] == faces[1], (
            f"#{select_id} is set in {faces[0]!r}, its label in {faces[1]!r}"
        )


@pytest.mark.browser
def test_a_breakdown_row_header_is_no_heavier_than_the_figures_beside_it(browser_page: Page):
    """`th scope="row"` is the right element and takes the UA's bold. No other
    console table has row headers, so nothing had reset it, and a bold label in
    every row outshouts the group heading above it.
    """
    stats = [
        _citation_row(turns=12, retrieved_total=24, cited_total=12),
        _citation_row(scope="lang", bucket="en", turns=12, retrieved_total=24, cited_total=12),
    ]
    _analytics_console(browser_page, citations=stats)

    table = _zone(browser_page, 0).locator("table.admin-table")
    expect(table.locator("tbody th[scope=row]")).to_have_count(1)
    weights = table.evaluate(
        """(t) => [getComputedStyle(t.querySelector('tbody th[scope=row]')).fontWeight,
                   getComputedStyle(t.querySelector('tbody td')).fontWeight]"""
    )
    assert weights[0] == weights[1], weights


# --- found by the adversarial review (OpenCode, muse-spark-1.3) ---


@pytest.mark.browser
@pytest.mark.parametrize(
    ("uncited", "turns", "shown"),
    [(3, 3000, "<1%"), (2997, 3000, ">99%"), (0, 3000, "0%"), (1500, 3000, "50%")],
)
def test_a_rounded_rate_never_contradicts_the_count_beside_it(
    browser_page: Page, uncited, turns, shown
):
    """`3 of 3000` rounded to `0%` reads as "none" next to a count that says
    three."""
    _analytics_console(browser_page, citations=[_citation_row(turns=turns, turns_uncited=uncited)])

    tile = _zone(browser_page, 0).locator("dl.admin-facts .admin-fact").nth(1)
    expect(tile.locator(".admin-fact-exact")).to_have_text(shown)


@pytest.mark.browser
def test_the_breakdown_rows_are_ordered_the_same_whatever_order_they_arrive_in(
    browser_page: Page,
):
    """The SQL function has no `order by`; the in-memory double sorts. The
    table is ordered in one place so the two cannot draw it differently — and a
    NULL bucket, which both columns allow, gets a name rather than an empty
    header cell."""
    unknown = _admin_catalogue("en")["account"]["emailVerifiedUnknown"]
    scope = _analytics_strings("en")["scope"]
    stats = [_citation_row(turns=12)] + [
        _citation_row(scope="category", bucket=bucket, turns=2)
        for bucket in (None, "zeta", "veterinary", "all", "regulatory")
    ]
    _analytics_console(browser_page, citations=stats)

    headers = _zone(browser_page, 0).locator("table.admin-table tbody th[scope=row]")
    expect(headers).to_have_text(
        [scope["all"], scope["regulatory"], scope["veterinary"], unknown, "zeta"]
    )


@pytest.mark.browser
def test_a_forged_option_cannot_put_an_unlisted_filter_on_the_wire(browser_page: Page):
    """The allow-list guards the value read out of storage; the value read off
    a change event has to pass the same gate, or an edited `<option>` sends
    `lang=xx`, earns a 422 and turns every zone to "could not load"."""
    calls = []
    _filtered_console(browser_page, calls=calls)
    expect(_saved_answers(browser_page)).to_have_text("3000")

    calls.clear()
    browser_page.evaluate(
        """() => {
          const select = document.getElementById('analytics-lang');
          select.options[1].value = 'xx';
          select.selectedIndex = 1;
          select.dispatchEvent(new Event('change', { bubbles: true }));
        }"""
    )
    expect(browser_page.locator("#analytics-results")).to_have_attribute("aria-busy", "false")

    assert calls, "the forged change did not refetch at all"
    assert {parse_qs(urlparse(url).query, keep_blank_values=True)["lang"][0] for url in calls} == {
        ""
    }


@pytest.mark.browser
def test_the_update_announcement_is_emptied_while_the_next_refetch_runs(browser_page: Page):
    """A polite live region set twice to the same sentence announces once. It
    is emptied when a refetch starts so the second "Figures updated." is a
    change."""
    updated = _analytics_strings("en")["updated"]
    calls, held = [], []
    _filtered_console(browser_page, calls=calls, hold_days="7", held=held)
    status = browser_page.locator("#analytics-status")

    browser_page.locator("#analytics-refresh").click()
    expect(status).to_have_text(updated)

    browser_page.locator("#analytics-window").focus()
    browser_page.keyboard.press("ArrowUp")  # 30 -> 7, held open
    expect(browser_page.locator("#analytics-results")).to_have_attribute("aria-busy", "true")
    expect(status).to_have_text("")


@pytest.mark.browser
def test_a_question_with_no_space_to_cut_at_still_fits_its_preview(browser_page: Page):
    """With nowhere to break, the preview used to keep all 160 graphemes and
    then add the ellipsis — 161."""
    _analytics_console(browser_page, questions=[_question_row("a" * 200)])

    summary = _zone(browser_page, 1).locator("td details summary")
    expect(summary).to_have_text("a" * 159 + "…")


# --- found by the external review of the analytics region ---


def test_a_failed_uncited_request_is_not_hidden_by_an_empty_question_list(browser_page: Page):
    """Zone 4 is omitted while the recurring list is policy-empty, which is
    right — but `questions: []` with the `order=uncited` request FAILED is not
    "nothing to show", it is a failure, and dropping the zone renders it as an
    absence. `null` = failed and `[]` = empty is this region's whole contract.
    """
    unavailable = _admin_catalogue("en")["overview"]["unavailable"]
    _analytics_console(
        browser_page,
        citations=[_citation_row(turns=12, turns_uncited=2, turns_no_retrieval=1)],
        questions=[],
        uncited_status=500,
    )

    expect(browser_page.locator("#analytics-results > .admin-section")).to_have_count(3)
    expect(_zone(browser_page, 2).locator(".admin-empty")).to_have_text(unavailable)
    # The floor notice above it is untouched: the two states coexist.
    expect(_zone(browser_page, 1).locator(".admin-notice")).to_be_visible()


def test_a_refetch_that_failed_outright_says_so_in_the_live_region(browser_page: Page):
    """`setAnalyticsLoading(true)` empties `#analytics-status` when a refetch
    starts. If all three then fail, nothing rewrites it — so an operator who
    pressed Refresh and reads by ear heard nothing at all, while the screen
    filled with three "could not load" lines.
    """
    unavailable = _admin_catalogue("en")["overview"]["unavailable"]
    _analytics_console(
        browser_page,
        citations_status=500,
        questions_status=500,
    )

    browser_page.locator("#analytics-refresh").click()
    expect(browser_page.locator("#analytics-status")).to_have_text(unavailable)
    expect(browser_page.locator("#analytics-results")).to_have_attribute("aria-busy", "false")


def test_both_question_tables_agree_on_whether_there_is_an_accounts_column(browser_page: Page):
    """Derived per table, the two stacked tables could disagree: the top one
    has a row that reached five accounts and gets the column, every row that
    survives the uncited filter is bucketed, and the `2–4` range vanishes from
    the table below — four columns above, three below, same header row twice.
    """
    strings = _analytics_strings("en")
    _analytics_console(
        browser_page,
        citations=[_citation_row(turns=12, turns_uncited=2, turns_no_retrieval=1)],
        questions=[
            _question_row("Import permit steps", asks=9, uncited=0, askers=7),
            _question_row("Renew a licence", asks=5, uncited=2, askers=None),
        ],
        uncited=[_question_row("Renew a licence", asks=5, uncited=2, askers=None)],
    )

    top = _zone(browser_page, 1).locator("table.admin-table")
    bottom = _zone(browser_page, 2).locator("table.admin-table")
    expect(top.locator("thead th")).to_have_count(4)
    expect(bottom.locator("thead th")).to_have_count(4)
    expect(bottom.locator("thead th").nth(2)).to_have_text(strings["questions"]["askers"])
    expect(bottom.locator("tbody tr").first.locator("td").nth(2)).to_have_text("2–4")


def test_a_render_that_throws_lands_as_could_not_load_not_as_a_blank_region(browser_page: Page):
    """`loadAnalytics()` is fire-and-forget at every call site, so anything
    thrown inside the renderers became an unhandled rejection and the region
    kept whatever half-state it was in. A `null` row in `stats` is the shortest
    real payload that reaches `row.scope` on nothing — the same class of
    malformed body the `value()` helper above already guards the loader
    against.
    """
    unavailable = _admin_catalogue("en")["overview"]["unavailable"]
    _analytics_console(
        browser_page,
        citations=[None],
        questions=[_question_row("Renew a licence", asks=3, uncited=1, askers=2)],
    )

    results = browser_page.locator("#analytics-results")
    expect(results.locator("> .admin-section")).to_have_count(3)
    expect(results.locator(".admin-empty")).to_have_text([unavailable] * 3)
    expect(results).to_have_attribute("aria-busy", "false")


# ── Its own tab (DESIGN.md) ──────────────────────────────────────────────────


def _console_with_analytics_recorded(page: Page, calls: list, *, abort=False, lang="") -> None:
    """The console open on its landing tab, every analytics request recorded
    in `calls` — and answered, or aborted outright when `abort` is set. The
    tab is deliberately NOT clicked: these tests are about when it loads.
    """
    _route_operational(page)

    def analytics(route):
        url = route.request.url
        calls.append(url)
        if abort:
            route.abort()
            return
        _json(route, _window_stats("30") if "citations" in url else {"questions": []})

    page.route("**/admin/api/analytics/**", analytics)
    page.goto(f"/admin?testing=true{lang}")
    expect(page.locator("#admin-console")).to_be_visible()


def test_opening_the_console_on_overview_fires_no_analytics_request(browser_page: Page):
    """Overview's contract is cheap reads only (DESIGN.md). Three aggregates
    over saved turns used to ride along on its first activation, un-awaited,
    for a tab the operator had not asked for.
    """
    calls = []
    _console_with_analytics_recorded(browser_page, calls)

    # Something positive first: the landing figures did render, so the boot
    # sequence this asserts about actually ran.
    expect(browser_page.locator("#overview-body .admin-facts .admin-fact")).to_have_count(3)
    browser_page.wait_for_timeout(300)
    assert calls == [], f"Overview fired analytics requests on boot: {calls}"


def test_the_analytics_tab_is_last_and_loads_on_first_activation_only(browser_page: Page):
    calls = []
    _console_with_analytics_recorded(browser_page, calls)

    tab_ids = browser_page.eval_on_selector_all(".admin-tab", "els => els.map(el => el.id)")
    assert tab_ids[-1] == "tab-analytics", tab_ids
    expect(browser_page.locator("#panel-analytics")).to_be_hidden()

    browser_page.locator("#tab-analytics").click()
    expect(browser_page.locator("#panel-analytics")).to_be_visible()
    expect(_saved_answers(browser_page)).to_have_text("3000")
    assert _windows_asked(calls) == ["30", "30", "30"], calls

    browser_page.locator("#tab-overview").click()
    browser_page.locator("#tab-analytics").click()
    expect(_saved_answers(browser_page)).to_have_text("3000")
    browser_page.wait_for_timeout(300)
    assert len(calls) == 3, f"a second activation fetched again: {calls}"


def test_a_total_failure_is_retried_on_the_next_activation_and_the_lead_survives(
    browser_page: Page,
):
    """`DESIGN.md`: clear the load-once flag when every request failed so the
    next activation can retry. And the lead zone — both selects, the stamp,
    the live region — is drawn once at init, so a retry repaints the results
    region and nothing else: a rebuild would drop the operator's focus and
    their chosen period with it.
    """
    unavailable = _admin_catalogue("en")["overview"]["unavailable"]
    calls = []
    _console_with_analytics_recorded(browser_page, calls, abort=True)

    browser_page.locator("#tab-analytics").click()
    results = browser_page.locator("#analytics-results")
    expect(results.locator(".admin-empty")).to_have_text([unavailable] * 3)
    expect(results).to_have_attribute("aria-busy", "false")
    assert len(calls) == 3, calls

    # A mark on the live nodes: a rebuild replaces them, a repaint does not.
    browser_page.evaluate(
        "() => { document.getElementById('analytics-window').dataset.mark = 'one'; }"
    )

    browser_page.locator("#tab-overview").click()
    browser_page.locator("#tab-analytics").click()
    browser_page.wait_for_timeout(400)
    assert len(calls) == 6, f"the second activation did not retry all three: {calls}"
    expect(results.locator(".admin-empty")).to_have_text([unavailable] * 3)
    mark = browser_page.evaluate("() => document.getElementById('analytics-window')?.dataset.mark")
    assert mark == "one", f"the lead zone was rebuilt: {mark!r}"


def _info_triggers(page: Page):
    return page.locator("#analytics-body .admin-info-btn")


def test_explanations_are_popups_and_states_are_not(browser_page: Page):
    """Standing context — where the numbers come from, how the data is handled,
    what a scope is, how questions are grouped, why the floor exists — hides
    behind an "i". A state never does: the small-sample line and the floor
    notice's lead stay on the page. Toggling, Esc and focus return are the
    browser's, and are asserted once so a regression in the wiring shows.
    """
    strings = _analytics_strings("en")
    _analytics_console(
        browser_page,
        citations=[_citation_row(turns=9, turns_uncited=2, turns_no_retrieval=1, cited_total=9)],
        questions=[],
    )

    triggers = _info_triggers(browser_page)
    expect(triggers).to_have_count(4)
    names = browser_page.eval_on_selector_all(
        "#analytics-body .admin-info-btn", "els => els.map((el) => el.getAttribute('aria-label'))"
    )
    targets = browser_page.eval_on_selector_all(
        "#analytics-body .admin-info-btn",
        "els => els.map((el) => el.getAttribute('popovertarget'))",
    )
    assert len(set(names)) == 4, names
    assert len(set(targets)) == 4, targets
    about = _admin_catalogue("en")["about"]
    assert about.replace("{topic}", strings["heading"]) in names, names
    assert about.replace("{topic}", strings["questions"]["floorEmpty"]) in names, names

    expected = [
        f"{strings['source']} {strings['privacy']}",
        strings["quality"]["scopeHint"],
        strings["questions"]["grouping"],
        strings["questions"]["floorWhy"],
    ]
    for target, text in zip(targets, expected, strict=True):
        pop = browser_page.locator(f"#{target}")
        expect(pop).to_have_class("admin-info-pop")
        expect(pop).to_have_attribute("popover", "auto")
        expect(pop).to_have_text(text)
        expect(pop).to_be_hidden()

    # States stay visible.
    citation_zone = _zone(browser_page, 0)
    expect(citation_zone.locator(".admin-form-hint")).to_have_text(
        strings["quality"]["smallSample"]
    )
    expect(citation_zone.locator(".admin-form-hint")).to_be_visible()
    lead = _zone(browser_page, 1).locator(".admin-notice strong")
    expect(lead).to_be_visible()
    expect(lead).to_have_text(strings["questions"]["floorEmpty"], use_inner_text=True)

    # Click opens, Esc closes, focus is back on the trigger.
    first = triggers.first
    first_pop = browser_page.locator(f"#{targets[0]}")
    first.click()
    expect(first_pop).to_be_visible()
    assert browser_page.evaluate("() => document.querySelectorAll(':popover-open').length") == 1
    browser_page.keyboard.press("Escape")
    expect(first_pop).to_be_hidden()
    focused = browser_page.evaluate("() => document.activeElement.getAttribute('aria-label')")
    assert focused == names[0], f"focus did not return to the trigger: {focused!r}"


@pytest.mark.parametrize(
    ("question", "preview"),
    [(" " + "a" * 300, "a" * 158), ("a " + "b" * 300, "a " + "b" * 157)],
)
def test_an_early_space_does_not_collapse_the_preview_to_an_ellipsis(
    browser_page: Page, question: str, preview: str
):
    """The walk-back stopped at the FIRST usable whitespace however early it
    was, so a leading space in front of a long unbroken token left `…` and
    nothing else, and one short word left `a…`. A cut that keeps less than half
    the budget is not a preview.
    """
    _analytics_console(browser_page, questions=[_question_row(question)])

    summary = _zone(browser_page, 1).locator("td details summary").text_content()
    assert summary is not None
    assert summary.strip() == preview + "…", summary


def test_the_fallback_walk_never_cuts_a_letter_off_its_shadda(browser_page: Page):
    """No `Intl.Segmenter`: the fallback iterates CODE POINTS, so the cut can
    land between a base letter and its own combining mark — the case the
    constant's comment names. Built with `chr` in Python: Arabic typed through
    a terminal arrives reversed, and this string's correctness is its exact
    code points.

    LAM + COMBINING SHADDA is two code points, so code point 159 — where a
    question with no whitespace anywhere is cut — is always a shadda.
    """
    lam, shadda = chr(0x0644), chr(0x0651)
    question = (lam + shadda) * 200

    browser_page.add_init_script("delete Intl.Segmenter;")
    _analytics_console(browser_page, questions=[_question_row(question)])

    assert browser_page.evaluate("() => typeof Intl.Segmenter") == "undefined"
    summary = _zone(browser_page, 1).locator("td details summary").text_content()
    assert summary is not None
    core = summary[:-1] if summary.endswith("…") else summary
    assert question.startswith(core), f"summary is not a prefix of the question: {len(core)}"
    assert unicodedata.combining(question[len(core)]) == 0, (
        f"the cut orphaned a combining mark: kept {len(core)} code points"
    )
