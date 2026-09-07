"""One rule for where configuration comes from, enforced everywhere at once.

Plan item P8 of docs/supabase-key-incident-fix-plan.md. `web/api/app.py` loaded
`.env` with `override=True` while `web/utils/config_loader.py` used the default,
so a systemd `EnvironmentFile=`, a container `-e`, or a key exported by a deploy
script was silently discarded in favour of whatever `.env` held on that host.
The documented way to fix a bad credential in production therefore did nothing.

This walks the tree and parses it rather than checking a list of known files. The
first version of this test pinned five paths by name, which fails OPEN in the one
way that matters: a sixth entrypoint added later with `override=True` would pass
a green suite and silently reinstate the bug. It also matched with a regex, whose
`[^)]*` stopped at the first `)` — so a call with a nested parenthesis, like
`load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)`, would
have had its arguments truncated before the `override` was ever seen.
"""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Vendored code, build output and historical records are not this repo's rules to
# enforce. `docs/archive` is history, per CLAUDE.md, not current behaviour.
_SKIP = {".venv", "venv", "node_modules", ".git", "__pycache__", "archive", "data"}


def _python_files():
    for path in PROJECT_ROOT.rglob("*.py"):
        if _SKIP.isdisjoint(part for part in path.parts):
            yield path


def _load_dotenv_calls():
    """Every `load_dotenv(...)` in the repo, as (path, lineno, override-keyword)."""
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - not ours to police
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name != "load_dotenv":
                continue
            override = next((kw for kw in node.keywords if kw.arg == "override"), None)
            yield path, node.lineno, override


def test_the_repo_contains_load_dotenv_calls_to_check():
    """A guard on the guard: if the parse silently stopped finding anything, the
    two tests below would pass vacuously forever."""
    assert list(_load_dotenv_calls()), "found no load_dotenv calls — this test has gone blind"


def test_nothing_anywhere_lets_dotenv_beat_the_real_environment():
    """`override=True` is the bug, wherever it appears — including in a file that
    did not exist when this test was written."""
    offenders = [
        f"{path.relative_to(PROJECT_ROOT)}:{lineno}"
        for path, lineno, override in _load_dotenv_calls()
        if override is not None
        and isinstance(override.value, ast.Constant)
        and override.value.value is True
    ]

    assert not offenders, (
        "These calls let .env override the real environment, which silently "
        "discards a deployment's own configuration:\n  " + "\n  ".join(offenders)
    )


def test_the_two_application_loaders_state_the_rule_explicitly():
    """The library default is already correct, but a deployment-visible decision
    should be readable at the call site rather than inferred — that inference is
    exactly how the two loaders came to disagree unnoticed. Scripts are one-shot
    developer tools and may take the default."""
    required = {
        PROJECT_ROOT / "web" / "api" / "app.py",
        PROJECT_ROOT / "web" / "utils" / "config_loader.py",
    }
    seen = set()

    for path, lineno, override in _load_dotenv_calls():
        if path not in required:
            continue
        seen.add(path)
        assert override is not None, (
            f"{path.relative_to(PROJECT_ROOT)}:{lineno} should say `override=False` explicitly"
        )
        assert isinstance(override.value, ast.Constant) and override.value.value is False, (
            f"{path.relative_to(PROJECT_ROOT)}:{lineno} must pass `override=False`"
        )

    missing = {p.relative_to(PROJECT_ROOT) for p in required - seen}
    assert not missing, f"these no longer load .env — update this test: {missing}"
