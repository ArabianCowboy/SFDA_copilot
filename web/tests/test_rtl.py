"""Language negotiation and RTL rendering.

Deliberately driven through app.test_client() rather than Playwright: these
assertions are about what the server renders, and the browser suite takes ~50
minutes to run. The genuinely visual RTL checks (mirrored sidebar, Arabic
letter-spacing) are covered by the CSS contract test plus manual QA.
"""

from __future__ import annotations

import pytest

from web.api.app import create_app
from web.utils.i18n import (
    is_rtl,
    load_catalog,
    make_translator,
    normalize_lang,
    runtime_subset,
    text_direction,
)


@pytest.fixture
def client():
    return create_app(testing=True).test_client()


def page(client, url="/"):
    response = client.get(url)
    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    return response.get_data(as_text=True)


# ── Language negotiation ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value,expected",
    [
        ("ar", "ar"), ("AR", "ar"), ("ar-SA", "ar"), ("ar_SA", "ar"),
        ("en", "en"), ("en-GB", "en"),
        ("klingon", "en"), ("", "en"), (None, "en"),
    ],
)
def test_language_codes_are_normalised(value, expected):
    assert normalize_lang(value) == expected


def test_direction_follows_language():
    assert text_direction("ar") == "rtl" and is_rtl("ar")
    assert text_direction("en") == "ltr" and not is_rtl("en")
    # An unsupported language must not leave the document without a direction.
    assert text_direction("klingon") == "ltr"


def test_query_string_selects_the_language():
    """A fresh client per language: ?lang= sets a cookie, and the test client
    persists it, so reusing one client would carry the choice over."""
    arabic = page(create_app(testing=True).test_client(), "/?lang=ar")
    assert 'lang="ar"' in arabic and 'dir="rtl"' in arabic

    english = page(create_app(testing=True).test_client(), "/")
    assert 'lang="en"' in english and 'dir="ltr"' in english


def test_explicit_language_is_persisted_to_a_cookie(client):
    response = client.get("/?lang=ar")
    assert "lang=ar" in response.headers.get("Set-Cookie", "")


def test_cookie_selects_the_language(client):
    client.set_cookie("lang", "ar")
    assert 'dir="rtl"' in page(client)


def test_accept_language_is_honoured_without_a_cookie(client):
    html = client.get("/", headers={"Accept-Language": "ar-SA,ar;q=0.9"}).get_data(as_text=True)
    assert 'lang="ar"' in html


def test_unsupported_accept_language_falls_back_to_english(client):
    html = client.get("/", headers={"Accept-Language": "fr-FR,fr;q=0.9"}).get_data(as_text=True)
    assert 'lang="en"' in html


# ── Rendered page ───────────────────────────────────────────────────────────

def test_arabic_page_renders_arabic_copy(client):
    html = page(client, "/?lang=ar")
    assert "مساعدك التنظيمي" in html            # sidebar tagline
    assert "ابدأ الآن" in html                   # hero CTA
    assert "Ask a question instead of searching" not in html   # English lead


def test_english_page_keeps_the_strings_the_browser_suite_asserts(client):
    html = page(client)
    assert "Ready to help" in html
    assert "Send message" in html


def test_runtime_catalogue_is_inlined_for_the_browser(client):
    html = page(client, "/?lang=ar")
    assert "window.__I18N" in html
    assert 'window.__LANG = "ar"' in html
    # page: strings are server-rendered only and must not be shipped to JS.
    assert "page.landing" not in html


def test_theme_toggle_count_is_stable_across_languages(client):
    """test_theme_toggle.py asserts exactly three. The language switcher uses
    its own class precisely so it cannot inflate this."""
    for url in ("/", "/?lang=ar"):
        assert page(client, url).count('class="theme-toggle-btn') == 3


def test_language_switcher_offers_the_other_language(client):
    assert 'data-lang="ar"' in page(client)
    assert 'data-lang="en"' in page(client, "/?lang=ar")


# ── Catalogue behaviour ─────────────────────────────────────────────────────

def test_missing_arabic_keys_fall_back_to_english():
    catalog = load_catalog("ar")
    t = make_translator(catalog)
    # Present in Arabic
    assert t("runtime.robot.idle") == "جاهز للمساعدة"
    # Every English key resolves to *something*, never a raw key.
    assert t("page.landing.cta") != "page.landing.cta"


def test_unknown_key_returns_the_key_rather_than_raising():
    t = make_translator(load_catalog("en"))
    assert t("page.does.not.exist") == "page.does.not.exist"


def test_placeholders_interpolate():
    t = make_translator(load_catalog("en"))
    assert t("runtime.auth.loggedInAs", email="a@b.co") == "Logged in as: a@b.co"


def test_runtime_subset_excludes_server_only_strings():
    runtime = runtime_subset(load_catalog("en"))
    assert "chat" in runtime and "robot" in runtime
    assert "landing" not in runtime and "features" not in runtime


# ── FAQ ─────────────────────────────────────────────────────────────────────

def test_faq_endpoint_returns_the_requested_language(client):
    arabic = client.get("/api/frequent-questions?lang=ar").get_json()
    english = client.get("/api/frequent-questions?lang=en").get_json()

    assert set(arabic) == set(english)  # same categories in both
    assert arabic["regulatory"]["questions"][0]["short"] == "تسجيل الأدوية"
    assert english["regulatory"]["questions"][0]["short"] == "Drug Registration"


def test_faq_shape_is_unchanged_so_the_client_needs_no_changes(client):
    data = client.get("/api/frequent-questions").get_json()
    category = data["regulatory"]
    assert set(category) == {"title", "icon", "questions"}
    assert set(category["questions"][0]) == {"text", "short"}


def test_faq_falls_back_to_english_for_an_unknown_language(client):
    data = client.get("/api/frequent-questions?lang=fr").get_json()
    assert data["regulatory"]["questions"][0]["short"] == "Drug Registration"


# ── Jump-to-latest pill ─────────────────────────────────────────────────────

def test_jump_to_latest_is_present_and_hidden_by_default(client):
    html = page(client)
    assert 'id="jump-to-latest"' in html
    # Hidden at rest: it only appears once the reader scrolls away.
    assert 'class="jump-to-latest" hidden' in html
    assert "Jump to latest" in html


def test_jump_to_latest_is_translated(client):
    html = page(client, "/?lang=ar")
    assert "الانتقال إلى الأحدث" in html
    assert "التمرير إلى أحدث رسالة" in html
    assert "Jump to latest" not in html
