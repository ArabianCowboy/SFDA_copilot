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
    # The message itself now comes from the i18n catalogue; the contract being
    # asserted is that handlers.js — not services.js — surfaces the failure.
    assert "ErrorHandler.showToast(I18n.t('chat.sendFailed')" in source


def test_ui_does_not_own_authentication_transitions():
    ui_source = (MODULES / "ui.js").read_text(encoding="utf-8")
    auth_view_source = (MODULES / "auth-view.js").read_text(encoding="utf-8")

    assert "updateAuthUI" not in ui_source
    assert "transitionToAuthenticatedView" in auth_view_source


def test_english_catalogue_preserves_test_asserted_strings():
    """The Playwright suite asserts these verbatim in the DOM.

    Translating the UI must not silently reword them — if one of these needs to
    change, the browser tests change with it, deliberately.
    """
    import yaml

    catalog = yaml.safe_load(
        (MODULES.parents[2] / "web" / "i18n" / "en.yaml").read_text(encoding="utf-8")
    )
    runtime = catalog["runtime"]

    assert runtime["robot"]["idle"] == "Ready to help"
    assert runtime["chat"]["sendFailed"] == "Failed to send message."
    assert runtime["chat"]["cancelled"] == "Chat request cancelled."
    assert runtime["chat"]["loginRequired"] == "Please log in to chat with the AI."
    assert runtime["chat"]["sessionUnverified"] == "Unable to verify your session. Please try again."
    assert runtime["chat"]["genericError"].startswith(
        "Sorry, I encountered an error while processing your request."
    )
    assert runtime["chat"]["sendAria"] == "Send message"
    assert runtime["chat"]["cancelAria"] == "Cancel message"
    assert runtime["auth"]["invalidCredentials"] == "Incorrect email or password."
    assert runtime["auth"]["loggedInAs"] == "Logged in as: {email}"
    assert runtime["theme"]["announced"] == "Theme changed to {mode} mode"


def test_arabic_catalogue_covers_every_runtime_key():
    """A missing runtime key would render as the raw key in the Arabic UI."""
    import yaml

    i18n_dir = MODULES.parents[2] / "web" / "i18n"
    en = yaml.safe_load((i18n_dir / "en.yaml").read_text(encoding="utf-8"))["runtime"]
    ar = yaml.safe_load((i18n_dir / "ar.yaml").read_text(encoding="utf-8"))["runtime"]

    def flatten(node, prefix=""):
        keys = set()
        for key, value in node.items():
            path = f"{prefix}{key}"
            keys |= flatten(value, f"{path}.") if isinstance(value, dict) else {path}
        return keys

    missing = flatten(en) - flatten(ar)
    assert not missing, f"Arabic catalogue is missing: {sorted(missing)}"
