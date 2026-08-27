"""Flask test-client coverage for routes, auth, and chat failures."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from web.api.app import _initialize_services, create_app


@pytest.fixture
def app():
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    user = SimpleNamespace(
        id="123",
        email="test@example.com",
        created_at="2024-03-27T00:00:00Z",
    )
    session = SimpleNamespace(
        access_token="fake_token",
        refresh_token="fake_refresh_token",
    )
    client.auth.sign_up.return_value = SimpleNamespace(
        user=user,
        data=SimpleNamespace(user=user),
        error=None,
    )
    client.auth.sign_in_with_password.return_value = SimpleNamespace(
        user=user,
        session=session,
        data=SimpleNamespace(user=user, session=session),
        error=None,
    )
    client.auth.sign_out.return_value = SimpleNamespace(error=None)

    with patch("web.api.auth.get_supabase", return_value=client):
        yield client


def test_landing_page_contains_both_application_views(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b'id="unauthenticated-view"' in response.data
    assert b'id="authenticated-view"' in response.data
    assert b'id="login-form"' in response.data


def test_frequent_questions_endpoint(client):
    response = client.get("/api/frequent-questions")

    assert response.status_code == 200
    assert "regulatory" in response.get_json()


def test_chat_requires_test_token(client):
    response = client.post(
        "/api/chat",
        json={"query": "registration", "category": "regulatory"},
    )

    assert response.status_code == 401
    assert response.get_json() == {"error": "Invalid or missing test token"}


def test_chat_validates_payload(client):
    headers = {"Authorization": "Bearer fake_token"}

    empty = client.post(
        "/api/chat",
        json={"query": "", "category": "all"},
        headers=headers,
    )
    invalid_category = client.post(
        "/api/chat",
        json={"query": "question", "category": "unknown"},
        headers=headers,
    )

    assert empty.status_code == 400
    assert empty.get_json()["error"] == "Query cannot be empty"
    assert invalid_category.status_code == 400
    assert "Invalid category" in invalid_category.get_json()["error"]


def test_chat_success(client, app):
    search_result = SimpleNamespace(
        text="Relevant guidance",
        document="guide.pdf",
        category="regulatory",
        page=2,
    )
    app.config["search_engine"].search.return_value = [search_result]
    # The marker is load-bearing: `sources` is what the answer CITED, so an
    # answer with no markers ships an empty list by design.
    app.config["openai_handler"].generate_response.return_value = (
        "Mock answer [1]",
        ["Follow up?"],
    )

    response = client.post(
        "/api/chat",
        json={"query": "question", "category": "regulatory"},
        headers={"Authorization": "Bearer fake_token"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["response"] == "Mock answer [1]"
    assert body["suggested_questions"] == ["Follow up?"]
    # The response also carries the retrieval sources; their content is covered
    # by test_citations.py, so this only pins the contract.
    assert body["sources"][0]["document"] == "guide.pdf"
    assert body["sources"][0]["page"] == 2
    assert body["sources"][0]["index"] == 1


def test_chat_returns_503_when_search_engine_is_unavailable(client, app):
    app.config["search_engine"] = None

    response = client.post(
        "/api/chat",
        json={"query": "question", "category": "regulatory"},
        headers={"Authorization": "Bearer fake_token"},
    )

    assert response.status_code == 503
    assert response.get_json() == {"error": "Search service is currently unavailable."}


def test_search_engine_construction_failure_keeps_app_available():
    from flask import Flask

    app = Flask(__name__)
    openai_handler = MagicMock()

    with (
        patch("web.api.app.OpenAIHandler", return_value=openai_handler),
        patch(
            "web.api.app.ImprovedSearchEngine",
            side_effect=RuntimeError("embedding provider unavailable"),
        ),
    ):
        _initialize_services(app, testing=False)

    assert app.config["openai_handler"] is openai_handler
    assert app.config["search_engine"] is None


def test_logout_drops_the_token_even_when_gotrue_fails():
    """Invalidation is local and unconditional, and must run before the
    GoTrue call rather than depend on it succeeding — whether the provider is
    reachable has no bearing on whether this process should keep trusting the
    token that is being signed out of."""
    from web.services.token_verification_cache import VerifiedIdentity

    application = create_app(testing=True)
    application.config["TESTING"] = False
    test_client = application.test_client()

    cache = application.config["token_verification"]
    token = "the-readers-live-token"
    key = cache._key(token)
    identity = VerifiedIdentity(user_id="reader-1", email="reader@example.com", token_exp=None)
    with cache._lock:
        cache._data[key] = (cache._now() + 30, cache._now(), identity)
        cache._by_user.setdefault("reader-1", set()).add(key)
    assert len(cache) == 1

    with test_client.session_transaction() as session:
        session["supabase_access_token"] = token

    with patch("web.api.auth.get_supabase", side_effect=RuntimeError("GoTrue unreachable")):
        response = test_client.post("/auth/logout")

    assert len(cache) == 0
    # The route still answers the request; a downstream provider failure is
    # not the caller's problem once the local session state is gone.
    assert response.status_code in (200, 400)


def test_search_engine_initialization_failure_keeps_app_available():
    from flask import Flask

    app = Flask(__name__)
    search_engine = MagicMock()
    search_engine.is_initialized.return_value = False
    search_engine.initialize.side_effect = RuntimeError("index unavailable")

    with (
        patch("web.api.app.OpenAIHandler", return_value=MagicMock()),
        patch("web.api.app.ImprovedSearchEngine", return_value=search_engine),
    ):
        _initialize_services(app, testing=False)

    search_engine.initialize.assert_called_once_with()
    assert app.config["search_engine"] is None


def test_auth_api_endpoints(client, mock_supabase):
    signup = client.post(
        "/auth/signup",
        json={"email": "test@example.com", "password": "Password123!"},
    )
    login = client.post(
        "/auth/login",
        json={"email": "test@example.com", "password": "Password123!"},
    )
    logout = client.post("/auth/logout")

    assert signup.status_code == 201
    assert signup.get_json()["user"]["email"] == "test@example.com"
    assert login.status_code == 200
    assert login.get_json()["session"]["access_token"] == "fake_token"
    assert logout.status_code == 200
