"""Small architecture contracts for the browser-facing modules."""

from pathlib import Path


MODULES = Path("static/js/modules")
ADMIN = Path("static/js/admin")
ACCOUNT = Path("static/js/account")


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
    # showProfileError moved with the #profileModal it existed for — see
    # test_account_flow_uses_the_i18n_catalogue_not_literals for its
    # replacement's own contract.
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


def test_account_flow_uses_the_i18n_catalogue_not_literals():
    """The profile-editing surface this guarded moved from the #profileModal
    (handlers.js/ui.js) to static/js/account/ when the modal was retired
    (docs/profile-refactor-plan.md §5) — the file changed, the discipline it
    pins did not: every reader-facing string on the account page draws from
    `runtime.profile.account.*`, none of it hardcoded English, which the
    catalogue-parity test alone cannot catch (both languages can carry a key
    that nothing uses).
    """
    source = (ACCOUNT / "ui.js").read_text(encoding="utf-8")

    assert "I18n.t('profile.account.identitySaved')" in source
    assert "I18n.t('profile.account.identitySaveFailed')" in source
    assert "I18n.t('profile.account.preferencesSaved')" in source
    assert "I18n.t('profile.account.preferencesSaveFailed')" in source
    assert "I18n.t('profile.account.loadFailed')" in source


def test_auth_flow_uses_the_i18n_catalogue_not_literals():
    """Three call sites on the login/signup submit path used to pass raw
    English literals to showAuthError/showToast — one of them an untranslated
    duplicate of `#user-status`'s own `runtime.auth.loggedInAs` text
    (auth-view.js writes that on every sign-in, from the auth-state listener,
    independently of this handler). This pins that each remaining site draws
    from the catalogue and that the duplicate toast is gone rather than
    translated, which the catalogue-parity test alone cannot catch (both
    languages can carry a key that nothing uses).
    """
    source = (MODULES / "handlers.js").read_text(encoding="utf-8")

    assert "I18n.t('auth.missingFields')" in source
    assert "I18n.t('auth.signupSent.heading')" in source
    assert "I18n.t('auth.signupSent.lead'" in source
    assert "I18n.t('auth.signupSent.spam')" in source

    # The literals this replaces, so a revert reintroduces hardcoded English
    # rather than silently passing.
    assert "Please fill in both email and password." not in source
    assert "Signup initiated! Please check your email to confirm." not in source
    # Deleted, not translated: stating the same fact twice, once untranslated.
    assert "Logged in as ${data.user.email}" not in source
    assert "Login successful!" not in source


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
    """A missing `runtime.*` key would render as the raw key in the Arabic UI.

    Also covers `page.*`: a missing key there does not render a raw key —
    `make_translator` (web/utils/i18n.py) deep-merges English as the base and
    falls back to it silently on a miss, so a lagging Arabic translation is
    invisible in the running app rather than loud. Both roots are checked
    here for the same reason: nothing else catches a language that quietly
    fell behind.
    """
    import yaml

    i18n_dir = MODULES.parents[2] / "web" / "i18n"
    en = yaml.safe_load((i18n_dir / "en.yaml").read_text(encoding="utf-8"))
    ar = yaml.safe_load((i18n_dir / "ar.yaml").read_text(encoding="utf-8"))

    def flatten(node, prefix=""):
        keys = set()
        for key, value in node.items():
            path = f"{prefix}{key}"
            keys |= flatten(value, f"{path}.") if isinstance(value, dict) else {path}
        return keys

    for root in ("runtime", "page"):
        missing = flatten(en[root]) - flatten(ar[root])
        assert not missing, f"Arabic catalogue['{root}'] is missing: {sorted(missing)}"
