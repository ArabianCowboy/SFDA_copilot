"""Small architecture contracts for the browser-facing modules."""

from pathlib import Path


MODULES = Path("static/js/modules")
ADMIN = Path("static/js/admin")


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

    # A key present in both catalogues but read by nothing is a failure mode
    # this repo has shipped twice, and the parity test cannot catch it — it
    # only proves the Arabic side has whatever the English side has. Both chat
    # paths surface a persistence failure, so both must reach the key.
    assert "'chat.notSaved'" in source
    assert source.count("'chat.notSaved'") >= 2, (
        "the streaming and blocking paths each report a failed history write"
    )

    # FIRST error wins. A stream can carry two error frames — a history write
    # that did not land, then a suggestions call that also failed — and the
    # second is always the less informative one. Assigning each in turn told a
    # reader whose answer merely went unsaved that their message failed to send.
    assert "failed = failed || d" in source, "a later error frame must not mask the first"

    # Suppressing showError() under a complete answer is only half the fix: the
    # failure branch returns before the happy path's returnToIdle(), so without
    # its own call the mascot animates forever.
    assert "RobotStateManager.returnToIdle(4000)" in source


def test_profile_flow_uses_the_i18n_catalogue_not_literals():
    """Five call sites in the profile flow used to pass raw English literals
    to showProfileError/showToast instead of a translation key, so an Arabic
    reader saw English on this one surface. `runtime.profile.*` existed in
    both catalogues the whole time and was read by nothing — this pins that
    each site now actually draws from it, which the catalogue-parity test
    alone cannot catch (both languages can carry a key that nothing uses).
    """
    source = (MODULES / "handlers.js").read_text(encoding="utf-8")

    assert "I18n.t('runtime.profile.sessionExpired')" in source
    assert "I18n.t('runtime.profile.saved')" in source
    assert "I18n.t('runtime.profile.saveFailed')" in source
    assert "I18n.t('runtime.profile.loginRequired')" in source
    assert "I18n.t('runtime.profile.loadFailed')" in source

    # The literals this replaces, so a revert reintroduces hardcoded English
    # rather than silently passing.
    assert "Your session seems to have expired" not in source
    assert "Profile saved successfully!" not in source
    assert "Failed to save: ${error.message}" not in source
    assert "Please log in to manage your profile." not in source
    assert "Could not load your profile." not in source


def test_ui_does_not_own_authentication_transitions():
    ui_source = (MODULES / "ui.js").read_text(encoding="utf-8")
    auth_view_source = (MODULES / "auth-view.js").read_text(encoding="utf-8")

    assert "updateAuthUI" not in ui_source
    assert "transitionToAuthenticatedView" in auth_view_source


def test_console_transport_has_no_view_or_state_dependencies():
    """The same contract as services.js, for the same reason.

    Transport that knows how to display a failure ends up deciding what a
    failure means, and the two answers then live in two places.
    """
    source = (ADMIN / "services.js").read_text(encoding="utf-8")

    assert "from '../modules/dom.js'" not in source
    assert "from '../modules/state.js'" not in source
    assert "from '../modules/ui.js'" not in source
    assert "ErrorHandler" not in source
    assert "DOMCache" not in source


def test_console_handlers_own_user_facing_failures():
    source = (ADMIN / "handlers.js").read_text(encoding="utf-8")

    assert "ErrorHandler.showToast" in source
    assert "I18n.t('admin.accessDenied')" in source


def test_the_console_does_not_import_the_chat_shell():
    """app.js, ui.js and handlers.js bind selectors that do not exist on /admin.

    Importing any of them would wire a composer, a transcript and a mascot into
    a console. The failure would not be subtle, but it would be at runtime and
    only for whoever opened the page — which is one administrator, possibly in
    production.
    """
    forbidden = ("modules/ui.js", "modules/handlers.js", "modules/app.js",
                 "modules/robot.js", "modules/source-panel.js")

    sources = list(ADMIN.glob("*.js")) + [Path("static/js/admin.js")]
    assert sources, "expected console modules to exist"

    for path in sources:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"{path.name} imports the chat shell ({name})"


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
    assert runtime["chat"]["cleared"] == "Conversation cleared"
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
