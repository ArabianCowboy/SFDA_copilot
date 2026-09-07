"""One rule for where configuration comes from, pinned in both loaders.

Plan item P8 of docs/supabase-key-incident-fix-plan.md. `web/api/app.py` loaded
`.env` with `override=True` while `web/utils/config_loader.py` used the default,
so the effective precedence depended on which module an entrypoint imported
first — and in the app's own entrypoint the file beat the real environment. That
makes the documented way to fix a bad credential in production (set it in the
systemd unit, the container, the deploy script) silently do nothing.

This is a source-level contract test, in the same spirit as
`test_frontend_architecture.py`: the rule is not observable from a single import
because both calls run at module scope, and by the time a test could look, the
values are already merged.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Every place the project loads a .env, and whether an explicit override is
# required. The scripts are one-shot developer tools rather than deployments,
# so they are allowed the library default — but they must not ASK for the
# environment to lose, which is the failure this test exists to prevent.
_LOADERS = (
    PROJECT_ROOT / "web" / "api" / "app.py",
    PROJECT_ROOT / "web" / "utils" / "config_loader.py",
    PROJECT_ROOT / "scripts" / "smoke_real.py",
    PROJECT_ROOT / "scripts" / "eval_retrieval.py",
    PROJECT_ROOT / "scripts" / "eval_citations.py",
)

_LOAD_DOTENV_CALL = re.compile(r"load_dotenv\((?P<args>[^)]*)\)", re.DOTALL)


def test_no_loader_lets_dotenv_beat_the_real_environment():
    """`override=True` anywhere is the bug: it discards a deployment's own
    configuration in favour of a file that may be stale or absent from the
    deployment entirely."""
    offenders = []
    for path in _LOADERS:
        if not path.exists():
            continue
        for match in _LOAD_DOTENV_CALL.finditer(path.read_text(encoding="utf-8")):
            args = " ".join(match.group("args").split())
            if "override=True" in args.replace(" ", ""):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: load_dotenv({args})")

    assert not offenders, (
        "These loaders let .env override the real environment, which silently "
        "discards a deployment's own configuration:\n  " + "\n  ".join(offenders)
    )


def test_the_two_application_loaders_state_the_rule_explicitly():
    """The default is already correct, but a deployment-visible decision should
    be readable at the call site rather than inferred from library defaults —
    that inference is what let the two loaders disagree unnoticed."""
    for path in (
        PROJECT_ROOT / "web" / "api" / "app.py",
        PROJECT_ROOT / "web" / "utils" / "config_loader.py",
    ):
        source = path.read_text(encoding="utf-8")
        calls = [" ".join(m.group("args").split()) for m in _LOAD_DOTENV_CALL.finditer(source)]
        assert calls, f"{path.relative_to(PROJECT_ROOT)} no longer loads .env — update this test"
        assert all("override=False" in call.replace(" ", "") for call in calls), (
            f"{path.relative_to(PROJECT_ROOT)} should say `override=False` explicitly; found: {calls}"
        )
