#!/usr/bin/env python3
# pre-commit shim for the mypy hook - run mypy from the project venv when one
# exists, otherwise fall back to a PATH-resolvable mypy. This keeps local
# GitLens / VS Code commits from failing with the bare-command hook.

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _find_mypy():
    script = "Scripts/mypy.exe" if platform.system() == "Windows" else "bin/mypy"
    for venv in ("venv", ".venv"):
        candidate = ROOT / venv / script
        if candidate.exists():
            return str(candidate)
    return shutil.which("mypy")


def main() -> int:
    exe = _find_mypy()
    if not exe:
        print("mypy executable not found", file=sys.stderr)
        return 1
    return subprocess.call([exe, *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
