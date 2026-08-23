"""The account page shell, and the line between what it renders and what it
reveals. Mirrors test_admin_page.py's own reasoning: the page is reachable
without a token (a document navigation cannot carry one), so this file is
mostly about what is *absent* from the markup.
"""

from __future__ import annotations

import re

import pytest

from web.api.app import ACCOUNT_MODULE_FILENAMES, create_app


AUTH = {"Authorization": "Bearer fake_token"}


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


def test_the_shell_renders_without_a_token(client):
    assert client.get("/account").status_code == 200


def test_the_shell_reveals_nothing_account_specific(client):
    html = client.get("/account").get_data(as_text=True)

    for forbidden in ("service_role", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY"):
        assert forbidden not in html

    # The record ships hidden and empty. A name or email in the markup would
    # mean the server rendered account data for an unauthenticated GET.
    assert 'id="account-record"' in html
    assert re.search(r'id="account-heading"[^>]*>\s*</h2>', html)


def test_the_page_is_not_indexed(client):
    response = client.get("/account")
    assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"


def test_account_modules_exist_and_are_mapped(client):
    """The same contract test_admin_page.py pins for the console's modules."""
    assert ACCOUNT_MODULE_FILENAMES, "expected at least one file in static/js/account/"

    html = client.get("/account").get_data(as_text=True)
    match = re.search(r'<script type="importmap">(\{.*?\})</script>', html, re.S)
    assert match, "the page must inline an import map"

    for name in ACCOUNT_MODULE_FILENAMES:
        assert f"js/account/{name}" in match.group(1)


def test_signed_in_reader_reaches_the_page(client):
    assert client.get("/account", headers=AUTH).status_code == 200
