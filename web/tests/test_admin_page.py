"""The console shell, and the line between what it renders and what it reveals.

The shell is deliberately reachable without a role, because a document
navigation cannot carry a bearer header and gating the page would turn away a
valid administrator who bookmarked it. That decision is only safe while the
page contains nothing worth reaching, so most of this file is about what is
*absent* from the HTML rather than what is present.
"""

from __future__ import annotations

import json
import re

import pytest

from web.api.app import ADMIN_MODULE_FILENAMES, ASSET_VERSION, create_app


AUTH = {"Authorization": "Bearer fake_token"}
ADMIN = {"Authorization": "Bearer fake_admin_token"}
DISABLED = {"Authorization": "Bearer fake_disabled_token"}


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


def _inline_config(html: str) -> dict:
    """The window.__I18N blob the page inlines."""
    match = re.search(r"window\.__I18N = (\{.*?\});", html, re.S)
    assert match, "the page must inline a runtime catalogue"
    return json.loads(match.group(1))


# ── The shell ─────────────────────────────────────────────────────────────────


def test_the_shell_renders_without_a_role(client):
    """Not a hole — the point. See the module docstring."""
    assert client.get("/admin").status_code == 200


def test_the_shell_reveals_nothing_privileged(client):
    """Everything an operator would want is fetched later, with a token."""
    html = client.get("/admin").get_data(as_text=True)

    for forbidden in ("service_role", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY"):
        assert forbidden not in html

    # The panels ship empty. A count, an email or a model name in the markup
    # would mean the server rendered privileged data for an unauthenticated GET.
    assert 'id="overview-body"' in html
    assert re.search(r'id="overview-body"[^>]*>\s*</div>', html), (
        "console panels must render empty"
    )


def test_the_service_key_value_is_absent_from_the_page(client, monkeypatch):
    """Asserting on the literal value, not on the word 'service'.

    Grepping for a name proves nothing: the key could be inlined under any
    label. This plants a known value and asserts that exact string never
    appears.
    """
    sentinel = "sb_secret_THIS_MUST_NEVER_REACH_THE_BROWSER"
    monkeypatch.setenv("SUPABASE_SECRET_KEY", sentinel)

    html = client.get("/admin").get_data(as_text=True)
    assert sentinel not in html


def test_the_shell_carries_the_independence_notice(client):
    """DESIGN.md requires it on every surface. A console is the surface where
    an implied official status would be most damaging."""
    html = client.get("/admin").get_data(as_text=True)
    assert "independent tool" in html.lower()


def test_the_console_has_exactly_one_theme_toggle(client):
    """The reader page asserts three. This is a different document and gets one —
    pinned here so neither count drifts unnoticed."""
    html = client.get("/admin").get_data(as_text=True)
    assert html.count('class="theme-toggle-btn') == 1


def test_every_static_url_carries_the_current_version(client):
    html = client.get("/admin").get_data(as_text=True)
    urls = re.findall(r'/static/(?:css|js)/[\w./-]+\?v=([\w.]+)', html)
    assert urls, "the page must reference versioned static assets"
    assert set(urls) == {ASSET_VERSION}


def test_the_import_map_versions_every_console_module(client):
    """An unmapped import resolves to a bare URL no cache-buster reaches."""
    html = client.get("/admin").get_data(as_text=True)
    match = re.search(r'<script type="importmap">(\{.*?\})</script>', html, re.S)
    assert match, "the console must ship an import map"
    imports = json.loads(match.group(1))["imports"]

    for name in ADMIN_MODULE_FILENAMES:
        key = f"/static/js/admin/{name}"
        assert key in imports, f"{name} is not in the import map"
        assert imports[key].endswith(f"v={ASSET_VERSION}")

    # The console's modules import the shared ones, so those must be mapped too.
    assert any("/static/js/modules/" in key for key in imports)


# ── The API ───────────────────────────────────────────────────────────────────


def test_the_api_requires_an_explicit_bearer_header(client):
    """Not the cookie, not the Flask session.

    `_get_token_from_request` honours both, which is right for chat and wrong
    here: a privileged endpoint reachable by ambient credentials is reachable by
    cross-site request forgery, and this app has no CSRF protection to answer
    that with.
    """
    response = client.get("/admin/api/identity")
    assert response.status_code == 401
    assert response.get_json() == {"error": "bearer_required"}


def test_the_api_answers_json_and_never_redirects(client):
    """A redirect here is worse than it looks.

    `_is_page_request` used to match the whole admin blueprint, so an invalid
    bearer on a JSON endpoint answered 302 to `/`. `fetch()` follows redirects
    by default, so the console received 200 OK and a page of HTML, parsed it as
    null, and carried on as though identity had been confirmed.
    """
    for path in ("/admin/api/identity", "/admin/api/settings"):
        response = client.get(path, headers={"Authorization": "Bearer wrong-token"})
        assert response.status_code in (401, 403), f"{path} answered {response.status_code}"
        assert response.is_json, f"{path} did not answer JSON"
        assert "text/html" not in response.content_type


def test_the_console_page_still_renders_rather_than_erroring(client):
    """The page is the one admin GET that is not an API call, so it keeps its
    own behaviour: a shell, for anyone, with nothing in it."""
    assert client.get("/admin").status_code == 200


def test_a_reader_is_refused_the_api(client):
    response = client.get("/admin/api/identity", headers=AUTH)
    assert response.status_code == 403
    assert response.get_json() == {"error": "forbidden"}


def test_a_disabled_account_is_refused_before_the_role_is_considered(client):
    """Disabled outranks admin. The check sits in _authenticate_request, which
    runs before the gate looks at the role at all."""
    response = client.get("/admin/api/identity", headers=DISABLED)
    assert response.status_code == 403
    assert response.get_json() == {"error": "account_disabled"}


def test_an_administrator_is_admitted(client):
    response = client.get("/admin/api/identity", headers=ADMIN)
    assert response.status_code == 200
    assert response.get_json()["is_admin"] is True


def test_every_admin_api_route_is_gated(app, client):
    """The gate is a before_request precisely so a route added later inherits it.

    This walks the url_map rather than naming endpoints, so a new console route
    is covered the moment it exists — which is the failure a per-route decorator
    invites, and it fails silently.
    """
    gated = [
        rule for rule in app.url_map.iter_rules()
        if rule.endpoint.startswith("admin.") and rule.endpoint != "admin.console"
    ]
    assert gated, "expected at least one gated console route"

    for rule in gated:
        if "GET" not in (rule.methods or set()):
            continue
        path = rule.rule.replace("<", "1").replace(">", "")
        assert client.get(path).status_code == 401, f"{rule.endpoint} is not gated"
        assert client.get(path, headers=AUTH).status_code == 403, (
            f"{rule.endpoint} admits a non-administrator"
        )


# ── What ships where ──────────────────────────────────────────────────────────


def test_the_console_catalogue_does_not_ship_to_the_landing_page(client):
    """runtime.admin enumerates the operator surface. The anonymous page cannot
    use those strings and should not advertise them."""
    assert "admin" not in _inline_config(client.get("/").get_data(as_text=True))
    assert "admin" in _inline_config(client.get("/admin").get_data(as_text=True))


def test_the_landing_catalogue_is_not_damaged_by_the_console_render(client):
    """load_catalog is lru_cached and hands back the same dict to every request.

    runtime_subset pops the admin block, so popping in place would strip it from
    the cached catalogue and every later /admin render would silently lose it.
    Rendering the console first, then the landing page, then the console again
    is the ordering that catches it.
    """
    assert "admin" in _inline_config(client.get("/admin").get_data(as_text=True))
    client.get("/")
    assert "admin" in _inline_config(client.get("/admin").get_data(as_text=True))


def test_page_strings_never_reach_the_browser(client):
    """test_rtl.py pins this for the reader page; the console gets the same rule.

    Asserted against the parsed catalogue rather than the raw HTML: a substring
    search for `"page"` matches `runtime.cite.page` ("Page {n}"), which is a
    legitimate runtime key. The claim is about the top-level block, so the check
    has to be about the top-level block.
    """
    config = _inline_config(client.get("/admin").get_data(as_text=True))

    assert "page" not in config, "the server-only page block must not be inlined"
    assert set(config) <= {
        "chat", "stage", "robot", "auth", "profile",
        "faq", "theme", "cite", "lang", "admin",
    }

    # A value that exists only under page.admin. If it appears, some page string
    # found its way into the runtime slice.
    assert "Back to chat" not in json.dumps(config, ensure_ascii=False)


def test_the_console_renders_in_arabic_and_mirrors(client):
    html = client.get("/admin?lang=ar").get_data(as_text=True)
    assert 'lang="ar"' in html
    assert 'dir="rtl"' in html
    assert "الإدارة" in html


# ── Icons ─────────────────────────────────────────────────────────────────────


def test_every_icon_the_console_js_draws_is_in_the_runtime_subset():
    """Server-side icon() raises on an unknown name; iconMarkup returns ''.

    That asymmetry means a glyph a module draws but nobody registered renders as
    a blank space and nothing says why. This is the only thing standing between
    a future `iconMarkup('gauge')` and a silently empty cell.
    """
    from pathlib import Path

    from web.utils.icons import ADMIN_RUNTIME_ICON_NAMES, RUNTIME_ICON_NAMES

    available = set(RUNTIME_ICON_NAMES) | set(ADMIN_RUNTIME_ICON_NAMES)
    admin_js = Path("static/js/admin")

    drawn: set[str] = set()
    for path in list(admin_js.glob("*.js")) + [Path("static/js/admin.js")]:
        drawn |= set(re.findall(r"iconMarkup\(\s*['\"]([\w-]+)['\"]", path.read_text(encoding="utf-8")))

    missing = drawn - available
    assert not missing, (
        f"console JS draws icon(s) absent from the runtime subset: {sorted(missing)}. "
        f"Add them to ADMIN_RUNTIME_ICON_NAMES in web/utils/icons.py."
    )
