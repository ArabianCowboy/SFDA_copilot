"""The startup report on variables set in both the environment and `.env`.

It compares VALUES, not presence, and that distinction is the whole point.
Under systemd this service starts with `EnvironmentFile=.../.env`, so every
name in that file is already in `os.environ` before Python runs. A presence
test therefore flags the entire file on every boot and announces a conflict
between a file and itself — which it did until 2026-09-19, when a deploy
review asked why production warned about `FLASK_SECRET_KEY` and
`OPENAI_API_KEY` on a perfectly healthy box.

Every test below calls the real `classify_dotenv_shadowing`. An earlier draft
reimplemented the comparison inside the test file and would have passed against
the presence-only version it was written to catch.
"""

from __future__ import annotations

from web.api.app import classify_dotenv_shadowing


def test_the_same_value_from_both_sources_is_not_a_conflict():
    """The production case: systemd injected `.env`, so the values match.
    Nothing is overridden, so nothing may warn.

    Fails against the presence-only version, which reported both names.
    """
    overridden, duplicated = classify_dotenv_shadowing(
        {"SUPABASE_URL": "https://project.supabase.co", "FLASK_SECRET_KEY": "s3cret"},
        {"SUPABASE_URL": "https://project.supabase.co", "FLASK_SECRET_KEY": "s3cret"},
    )

    assert overridden == [], "identical values must not be reported as a conflict"
    assert duplicated == 2


def test_a_genuinely_different_value_still_warns():
    """The case the warning exists for: a stale `.env` losing to the real
    environment. This must keep firing, or the fix above would have traded a
    noisy warning for a silent one."""
    overridden, duplicated = classify_dotenv_shadowing(
        {"SUPABASE_URL": "https://stale.supabase.co"},
        {"SUPABASE_URL": "https://production.supabase.co"},
    )

    assert overridden == ["SUPABASE_URL"]
    assert duplicated == 0


def test_a_variable_only_in_dotenv_is_not_reported():
    """Nothing shadows it, so there is nothing to say about it."""
    overridden, duplicated = classify_dotenv_shadowing({"ONLY_IN_DOTENV": "value"}, {})

    assert overridden == []
    assert duplicated == 0


def test_a_mixed_deployment_separates_the_two():
    """One genuinely overridden name among several duplicated ones must still
    surface by name — that is the line somebody needs at 3am."""
    overridden, duplicated = classify_dotenv_shadowing(
        {"A": "same", "B": "stale", "C": "same"},
        {"A": "same", "B": "live", "C": "same"},
    )

    assert overridden == ["B"]
    assert duplicated == 2


def test_an_empty_string_is_a_value_not_an_absence():
    """`os.getenv` returning "" is a set variable. Treating it as unset would
    hide a real override behind a falsy check."""
    overridden, _ = classify_dotenv_shadowing({"FEATURE_FLAG": "on"}, {"FEATURE_FLAG": ""})

    assert overridden == ["FEATURE_FLAG"]


def test_the_module_computed_both_values_at_import():
    """The startup report reads these two names; a rename must not leave it
    silently reporting nothing."""
    import web.api.app as app_module

    assert isinstance(app_module._shadowed, list)
    assert isinstance(app_module._shadowed_but_identical, int)
