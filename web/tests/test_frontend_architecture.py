"""Small architecture contracts for the browser-facing modules."""

from pathlib import Path


MODULES = Path("static/js/modules")


def test_services_module_has_no_view_or_state_dependencies():
    source = (MODULES / "services.js").read_text(encoding="utf-8")

    assert "from './dom.js'" not in source
    assert "from './state.js'" not in source
    assert "from './ui.js'" not in source
    assert "ErrorHandler" not in source
    assert "DOMCache" not in source


def test_handlers_own_user_facing_service_failures():
    source = (MODULES / "handlers.js").read_text(encoding="utf-8")

    assert "ErrorHandler.showAuthError" in source
    assert "ErrorHandler.showProfileError" in source
    assert "ErrorHandler.showToast('Failed to send message.'" in source


def test_ui_does_not_own_authentication_transitions():
    ui_source = (MODULES / "ui.js").read_text(encoding="utf-8")
    auth_view_source = (MODULES / "auth-view.js").read_text(encoding="utf-8")

    assert "updateAuthUI" not in ui_source
    assert "transitionToAuthenticatedView" in auth_view_source
