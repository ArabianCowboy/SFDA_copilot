"""Exercise the real CDN assets: matching version strings alone cannot verify SRI."""

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("path", ["/", "/admin", "/account", "/privacy"])
@pytest.mark.parametrize("lang", ["en", "ar"])
def test_bootstrap_cdn_assets_pass_browser_integrity_checks(browser_page: Page, path, lang):
    version = json.loads(Path("package.json").read_text(encoding="utf-8"))["dependencies"][
        "bootstrap"
    ]
    browser_page.goto(f"{path}?lang={lang}")
    stylesheet = browser_page.locator('link[href*="/bootstrap@"]')
    expect(stylesheet).to_have_attribute(
        "href", f"https://cdn.jsdelivr.net/npm/bootstrap@{version}/dist/css/bootstrap.min.css"
    )
    expect(stylesheet).to_have_attribute("integrity", re.compile(r"^sha384-[A-Za-z0-9+/]{64}$"))
    expect(stylesheet).to_have_attribute("crossorigin", "anonymous")
    assert stylesheet.evaluate("link => link.sheet !== null"), "Bootstrap CSS was blocked"

    if path == "/":
        script = browser_page.locator('script[src*="/bootstrap@"]')
        expect(script).to_have_attribute("integrity", re.compile(r"^sha384-[A-Za-z0-9+/]{64}$"))
        expect(script).to_have_attribute("crossorigin", "anonymous")
        assert browser_page.evaluate("window.bootstrap?.Modal.VERSION") == version
        assert browser_page.evaluate("window.bootstrap?.Offcanvas.VERSION") == version
        assert browser_page.evaluate("window.bootstrap?.Dropdown.VERSION") == version
