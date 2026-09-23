"""The "i" popups across the whole console. The live rule is DESIGN.md's "Standing
context may hide; a state may not"; the § numbers below are from its rollout plan,
docs/archive/2026-09-23_info-popup-rollout.md, which holds the reasoning.

`TABS` is the plan's §4.1 table as data: per tab, what has to be on screen
before the tab can be read, then its triggers in DOM order as (text, topic)
catalogue keys. `KEPT` is the other half, the hints and notices §4.1 keeps
visible, and the states test asserts that the rendered set EQUALS it. A hint
that appears, migrates or vanishes then has to be classified before the suite
goes green; pinning one sample string per tab would pass vacuously.

One route answers every `/admin/api/*` request from `CANNED`, so every tab can
be opened on one page, which the console-wide tests need. The settings answer
names a different live model on purpose: `settings.notLive` is a kept state,
and a kept state that never renders makes its allowlist entry vacuous.

Chromium puts no `aria-expanded` on a `<button popovertarget>`; the expanded
state lives in the accessibility tree, so it is read over CDP (plan §1).
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml
from playwright.sync_api import Locator, Page, expect

from web.tests.test_admin_analytics_browser import _citation_row
from web.tests.test_admin_browser import (
    ACCOUNTS,
    ADMIN_IDENTITY,
    AUDIT,
    DETAILS,
    REGISTRATIONS,
    SETTINGS,
    TIERS_RESPONSE,
    _json,
)

pytestmark = pytest.mark.browser

REPO_ROOT = Path(__file__).resolve().parents[2]

CANNED = {
    "identity": ADMIN_IDENTITY,
    "settings": {**SETTINGS, "active": {"model": "gpt-4o"}},
    "registrations": REGISTRATIONS,
    "tiers": TIERS_RESPONSE,
    "audit": AUDIT,
    "users": {"users": ACCOUNTS, "total": len(ACCOUNTS), "limit": 50, "offset": 0},
    "deletions": {
        "deletions": [
            {
                "user_id": "test-user-id",
                "state": "pending",
                "requested_at": "2026-09-01T00:00:00+00:00",
                "grace_until": "2026-09-08T00:00:00+00:00",
                "attempt_count": 1,
                "last_error_code": None,
            }
        ]
    },
    "notifications/history": {"notifications": [], "total": 0, "limit": 20, "offset": 0},
    "notifications/purge-settings": {"purge_retention_days": 90},
    # Nine answers, so the small-sample line renders; no questions, so the
    # floor notice (and its "i") does.
    "analytics/citations": {
        "stats": [_citation_row(turns=9, turns_uncited=2, turns_no_retrieval=1, cited_total=9)]
    },
    "analytics/questions": {"questions": []},
}

# tab: (what proves it has rendered, its triggers in DOM order as (text, topic)).
# A tuple of text keys is joined with a space; a `page.` topic is a panel h1.
# "account" is the Users tab with an account open; "people" is its list.
TABS = {
    "overview": (("#overview-body .admin-fact",), ()),
    "settings": (
        ("#registrations-toggle", "#settings-not-live"),
        (
            ("registrations.hint", "registrations.heading"),
            ("settings.hint", "settings.heading"),
        ),
    ),
    "people": (
        (".admin-account-open",),
        (("people.moveHint", "page.admin.tabs.people"),),
    ),
    "account": (
        ("#account-no-password-hint",),
        (
            ("people.moveHint", "page.admin.tabs.people"),
            ("account.profileHint", "account.profileHeading"),
            ("account.quotaHint", "account.quotaHeading"),
        ),
    ),
    "tiers": (
        ("#tier-form",),
        (
            ("tiers.hint", "page.admin.tabs.tiers"),
            ("tiers.labelsHint", "tiers.addHeading"),
        ),
    ),
    "deletions": (("#deletions-table",), (("deletions.hint", "page.admin.tabs.deletions"),)),
    "audit": (("#audit-table",), (("audit.hint", "page.admin.tabs.audit"),)),
    "notifications": (("#notification-history-body .admin-empty",), ()),
    "analytics": (
        ("#analytics-results .admin-notice",),
        (
            (("analytics.source", "analytics.privacy"), "analytics.heading"),
            ("analytics.quality.scopeHint", "analytics.quality.heading"),
            ("analytics.questions.grouping", "analytics.questions.heading"),
            ("analytics.questions.floorWhy", "analytics.questions.floorEmpty"),
        ),
    ),
}

# The §4.1 "Keep" rows, per tab, as rendered by `CANNED`.
KEPT = {
    "overview": (),
    "settings": (("registrations.bypassHeading", "registrations.bypassNote"), "settings.notLive"),
    # Moved behind the Users panel "i" 2026-09-24 — a Move is reversible (move
    # back) and audited, and keeps personal allowances, so it is not a
    # destructive click that must stay read on the page.
    "people": (),
    "account": (
        "account.overrideHint",
        "account.overrideWindowHint",
        "account.quotaReasonHint",
        "account.noPasswordHint",
    ),
    "tiers": ("tiers.keyHint",),
    "deletions": (),
    "audit": (),
    # NOT a §4.1 row: the live audience count beside Send, which §9 #6 cites as
    # stating the targeting. A state, so it stays; listed here, not classified.
    "notifications": ("notifications.composer.audiencePreviewNone",),
    # Analytics' states from fd516a5. The "Counted at" stamp is not a §4.1 row.
    "analytics": (
        "analytics.countedAt",
        "analytics.quality.smallSample",
        "analytics.questions.floorEmpty",
    ),
}

HINTS = ".admin-form-hint, .admin-account-hint, .admin-notice"

FACTS_JS = """(buttons) => buttons.map((b) => {
  const pop = b.nextElementSibling;
  const target = b.getAttribute('popovertarget');
  return {
    label: b.getAttribute('aria-label'),
    target,
    resolves: !!pop && document.getElementById(target) === pop,
    popover: pop?.getAttribute('popover'),
    cls: pop?.className,
    text: pop?.textContent,
    shown: !!pop && (pop.matches(':popover-open') || pop.checkVisibility()),
    inside: b.closest('label, summary, td, th, h1, h2')?.tagName ?? null,
  };
})"""

OPEN_COUNT = "() => document.querySelectorAll(':popover-open').length"


@functools.cache
def _catalogue(lang: str) -> dict:
    return yaml.safe_load((REPO_ROOT / "web" / "i18n" / f"{lang}.yaml").read_text(encoding="utf-8"))


def _t(lang: str, keys) -> str:
    """One key or a tuple of them, joined. `page.` keys resolve from the
    catalogue root, everything else under `runtime.admin`."""
    parts = []
    for key in (keys,) if isinstance(keys, str) else keys:
        node = _catalogue(lang) if key.startswith("page.") else _catalogue(lang)["runtime"]["admin"]
        for part in key.split("."):
            node = node[part]
        parts.append(node)
    return " ".join(parts)


def _about(lang: str, topic_key: str) -> str:
    return _t(lang, "about").replace("{topic}", _t(lang, topic_key))


def _console(page: Page, *, lang: str = "en") -> None:
    def answer(route):
        path = urlparse(route.request.url).path.removeprefix("/admin/api/")
        if path.startswith("users/"):
            _json(route, {"user": DETAILS[path.split("/")[1]], "self_id": "test-admin-id"})
        elif path.startswith("tiers") or path in CANNED:
            _json(route, CANNED["tiers" if path.startswith("tiers") else path])
        else:
            route.fulfill(status=404, content_type="application/json", body="{}")

    page.route("**/admin/api/**", answer)
    page.goto(f"/admin?testing=true&lang={lang}")
    expect(page.locator("#admin-console")).to_be_visible()


def _open(page: Page, tab: str) -> Locator:
    """Activate `tab` and wait until it has rendered. Returns its panel."""
    panel = "people" if tab == "account" else tab
    page.locator(f"#tab-{panel}").click()
    if tab == "account":
        page.locator(".admin-account-open", has_text="test@example.com").click()
    for selector in TABS[tab][0]:
        expect(page.locator(selector).first).to_be_visible()
    return page.locator(f"#panel-{panel}")


def _popup(page: Page, button: Locator) -> Locator:
    return page.locator(f"#{button.get_attribute('popovertarget')}")


def _measure(page: Page, button: Locator) -> tuple[dict, dict]:
    """Open `button`'s popup, return both layout boxes, close it again."""
    pop = _popup(page, button)
    button.click()
    expect(pop).to_be_visible()
    b, p = button.bounding_box(), pop.bounding_box()
    page.keyboard.press("Escape")
    expect(pop).to_be_hidden()
    assert b and p, "no layout box"
    return b, p


# ── §7.1 The contract, tab by tab and console-wide ──────────────────────────


@pytest.mark.parametrize("tab", TABS)
def test_each_trigger_names_its_topic_and_owns_the_popup_beside_it(browser_page: Page, tab):
    """Named `About {topic}`; `popovertarget` resolves to the NEXT SIBLING,
    which the VoiceOver read-out depends on (§5.1); the popup holds exactly
    the catalogue text and starts closed; and no trigger sits in a label,
    summary, cell or heading, where it would join that element's name."""
    _console(browser_page)
    buttons = _open(browser_page, tab).locator(".admin-info-btn")
    triggers = TABS[tab][1]
    expect(buttons).to_have_count(len(triggers))

    facts = buttons.evaluate_all(FACTS_JS)
    assert [f["label"] for f in facts] == [_about("en", topic) for _, topic in triggers]
    assert [f["text"] for f in facts] == [_t("en", text) for text, _ in triggers]
    for f in facts:
        assert f["resolves"], f"popovertarget is not the next sibling: {f}"
        assert (f["popover"], f["cls"]) == ("auto", "admin-info-pop"), f
        assert not f["shown"], f"open before anyone asked: {f}"
        assert f["inside"] is None, f"trigger inside <{f['inside']}>: {f}"


def test_the_console_has_thirteen_triggers_and_no_two_share_a_name(browser_page: Page):
    _console(browser_page)
    for tab in TABS:
        _open(browser_page, tab)

    labels = browser_page.locator("#admin-console .admin-info-btn").evaluate_all(
        "els => els.map((el) => el.getAttribute('aria-label'))"
    )
    # "people" and "account" are the same panel, so `people.moveHint`'s trigger
    # is the SAME DOM element under both — summing `TABS` counts that one
    # trigger twice (14), but the console-wide locator above sees it once: 13
    # distinct triggers.
    assert sum(len(triggers) for _, triggers in TABS.values()) == 14, labels
    assert len(labels) == 13, labels
    assert len(set(labels)) == len(labels), labels


# ── §7.2 States stay visible, exhaustively ──────────────────────────────────


def _pattern(keys) -> re.Pattern:
    """The kept string as a regex: whitespace collapsed, `{placeholders}` open."""
    parts = re.split(r"\{\w+\}", " ".join(_t("en", keys).split()))
    return re.compile(".+?".join(map(re.escape, parts)))


@pytest.mark.parametrize("tab", TABS)
def test_every_visible_hint_on_a_tab_is_a_state_it_keeps(browser_page: Page, tab):
    _console(browser_page)
    panel = _open(browser_page, tab)
    shown = [
        " ".join(text.split())
        for text in panel.locator(HINTS).evaluate_all(
            """(els) => els.filter((el) => {
                 const box = el.getBoundingClientRect();
                 return box.width > 0 && box.height > 0
                   && getComputedStyle(el).visibility !== 'hidden';
               }).map((el) => el.innerText)"""
        )
    ]
    kept = {keys: _pattern(keys) for keys in KEPT[tab]}
    found = [
        next((keys for keys, pattern in kept.items() if pattern.fullmatch(text)), text)
        for text in shown
    ]
    assert sorted(map(str, found)) == sorted(map(str, KEPT[tab])), (
        "a visible hint §4.1 does not keep, or a kept one missing"
    )

    # And what moved behind an "i" is not ALSO still on the page, in any class.
    visible = " ".join(panel.inner_text().split())
    for text, _ in TABS[tab][1]:
        assert " ".join(_t("en", text).split()) not in visible, f"{text} is still visible"


# ── §7.3 Interaction, once per mechanism ────────────────────────────────────


def _expanded(page: Page):
    cdp = page.context.new_cdp_session(page)

    def expanded(name: str):
        for node in cdp.send("Accessibility.getFullAXTree")["nodes"]:
            if node.get("name", {}).get("value") == name:
                props = {p["name"]: p["value"]["value"] for p in node.get("properties", [])}
                return props.get("expanded")
        raise AssertionError(f"no accessibility node named {name!r}")

    return expanded


@pytest.mark.parametrize(
    ("tab", "holder"),
    [("settings", "admin-section-head"), ("tiers", "admin-heading-row")],
    ids=["section", "panelInfo"],
)
def test_a_trigger_opens_closes_and_gives_way_to_the_next(browser_page: Page, tab, holder):
    _console(browser_page)
    panel = _open(browser_page, tab)
    buttons = panel.locator(".admin-info-btn")
    first, second = buttons.nth(0), buttons.nth(1)
    expect(first.locator("xpath=..")).to_have_class(holder)
    first_pop, second_pop = _popup(browser_page, first), _popup(browser_page, second)
    name = first.get_attribute("aria-label")
    expanded = _expanded(browser_page)

    assert expanded(name) is False
    first.click()
    expect(first_pop).to_be_visible()
    assert expanded(name) is True

    browser_page.keyboard.press("Escape")
    expect(first_pop).to_be_hidden()
    expect(first).to_be_focused()
    assert expanded(name) is False

    first.click()
    second.click()
    expect(second_pop).to_be_visible()
    expect(first_pop).to_be_hidden()
    assert browser_page.evaluate(OPEN_COUNT) == 1

    panel.locator("h1").click()
    expect(second_pop).to_be_hidden()
    assert browser_page.evaluate(OPEN_COUNT) == 0


def test_the_panel_trigger_is_reached_before_the_panel_body(browser_page: Page):
    """§5.2: the explanation comes before the content it explains. The h1 is
    not a tab stop; the tabpanel is, so the order is panel → "i" → body."""
    _console(browser_page)
    panel = _open(browser_page, "tiers")
    panel.focus()
    browser_page.keyboard.press("Tab")
    expect(panel.locator(".admin-heading-row .admin-info-btn")).to_be_focused()
    browser_page.keyboard.press("Tab")
    assert browser_page.evaluate(
        "() => document.getElementById('tiers-body').contains(document.activeElement)"
    ), "the second Tab did not enter the panel body"


# ── §7.4 Geometry ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("lang", "width", "height"), [("ar", 390, 844), ("en", 390, 844), ("en", 1280, 900)]
)
def test_every_popup_opens_against_its_button_inside_the_viewport(
    browser_page: Page, lang, width, height
):
    """Every trigger on every tab, `deletions.hint` (the longest) included.
    Anchored, not centred: the popup shares an inline edge with its button —
    the start edge, or the end edge once `flip-inline` has moved it to the
    button's other side. It keeps the 16px gutter and is never narrower than
    12rem: before both rules, an "i" mid-row at 390px in English shrank its
    popup to 100px by 540px, flush with the viewport edge.
    """
    browser_page.set_viewport_size({"width": width, "height": height})
    _console(browser_page, lang=lang)

    for tab, (_, triggers) in TABS.items():
        if not triggers:
            continue
        buttons = _open(browser_page, tab).locator(".admin-info-btn")
        expect(buttons).to_have_count(len(triggers))
        for index in range(len(triggers)):
            button = buttons.nth(index)
            b, p = _measure(browser_page, button)
            where = f"{tab} #{index} {button.get_attribute('aria-label')!r}: button={b} popup={p}"
            assert p["x"] >= 15 and p["x"] + p["width"] <= width - 15, f"in the gutter: {where}"
            assert p["y"] >= 0 and p["y"] + p["height"] <= height, f"off the top/bottom: {where}"
            assert p["width"] >= 191, f"narrower than 12rem: {where}"
            left = abs(b["x"] - p["x"]) <= 1
            right = abs(b["x"] + b["width"] - p["x"] - p["width"]) <= 1
            assert left or right, f"on neither edge of its button: {where}"


def test_a_popup_at_the_bottom_edge_flips_above_its_button(browser_page: Page):
    browser_page.set_viewport_size({"width": 390, "height": 844})
    _console(browser_page, lang="ar")
    buttons = _open(browser_page, "account").locator(".admin-info-btn")
    expect(buttons).to_have_count(3)
    button = buttons.last  # Allowance: low on a long page, so it CAN reach the edge.

    button.evaluate("(el) => el.scrollIntoView({ block: 'end' })")
    b, p = _measure(browser_page, button)
    assert b["y"] + b["height"] >= 844 - 2, f"the button is not at the bottom edge: {b}"
    assert p["y"] >= 0 and p["y"] + p["height"] <= b["y"] + 1, (
        f"the popup did not flip above its button (button={b}, popup={p})"
    )


# ── §7.5 No duplicate trigger ───────────────────────────────────────────────


def test_a_repaint_or_a_second_reveal_adds_no_second_panel_trigger(browser_page: Page):
    """Repaints clear only the panel body, and `panelInfo` returns early on a
    row that already holds a trigger. The second `revealConsole` is imported
    through the page's own import map, so it is the SAME module instance the
    console booted from (no second fetch of ui.js), not a fresh copy."""
    _console(browser_page)
    panel = _open(browser_page, "tiers")
    rows = browser_page.locator("#admin-console .admin-heading-row")
    expect(rows).to_have_count(4)

    # Two repaints: Edit redraws the body in place, Save reloads it.
    panel.locator("tr[data-tier-key='staff'] [data-tier-action='edit']").click()
    expect(panel.locator(".admin-section-head .admin-info-btn")).to_have_attribute(
        "aria-label", _about("en", "tiers.editHeading")
    )
    panel.locator("#tier-form [type='submit']").click()
    expect(browser_page.locator("#toast")).to_contain_text(_t("en", "tiers.saved"))
    expect(panel.locator(".admin-section-head .admin-info-btn")).to_have_attribute(
        "aria-label", _about("en", "tiers.addHeading")
    )

    fetches = browser_page.evaluate(
        """async () => {
          const imports = JSON.parse(
            document.querySelector('script[type="importmap"]').textContent).imports;
          const key = Object.keys(imports).find((k) => k.endsWith('/js/admin/ui.js'));
          (await import(key)).revealConsole({ email: 'admin@example.com' });
          return performance.getEntriesByType('resource')
            .filter((e) => e.name.includes('/js/admin/ui.js')).length;
        }"""
    )
    assert fetches == 1, f"ui.js was fetched {fetches} times: a second module instance"

    for index in range(4):
        expect(rows.nth(index).locator(".admin-info-btn")).to_have_count(1)
        expect(rows.nth(index).locator(".admin-info-pop")).to_have_count(1)
    expect(panel.locator(".admin-info-btn")).to_have_count(2)


# ── §7.6 The consequence moved into the confirm ─────────────────────────────


@pytest.mark.parametrize("lang", ["en", "ar"])
def test_disabling_states_the_consequence_before_asking_why(browser_page: Page, lang):
    """The deleted `people.hint` carried what disabling does. It now sits in
    the confirm, read at the moment it matters, and the confirm still comes
    before the reason prompt."""
    _console(browser_page, lang=lang)
    _open(browser_page, "account")
    dialogs = []

    def answer(dialog):
        dialogs.append((dialog.type, dialog.message))
        if dialog.type == "confirm":
            dialog.accept()
        else:
            dialog.dismiss()

    browser_page.on("dialog", answer)
    browser_page.locator("#account-actions [data-action='disable']").click()

    confirm = _t(lang, "people.confirmDisable").replace("{email}", "test@example.com")
    assert dialogs == [("confirm", confirm), ("prompt", _t(lang, "people.reasonPrompt"))]
    assert re.search(r"[?\u061f]\s+\S", confirm), f"the confirm asks and stops: {confirm!r}"
