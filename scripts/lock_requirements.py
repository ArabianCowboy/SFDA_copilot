"""Regenerate requirements.lock from requirements.txt.

The lock is what production and CI install: every package pinned and hashed,
resolved for the VPS (CPython 3.14, x86_64 Linux) whatever machine runs this.
requirements.txt stays the human-edited list of what the app needs; the lock
is generated, never edited by hand.

    python scripts/lock_requirements.py                           # re-resolve, keeping current pins
    python scripts/lock_requirements.py --upgrade-package pandas  # move one package deliberately
    python scripts/lock_requirements.py --upgrade                 # move everything (review the diff)

uv keeps every pin already in the lock unless told to move it, so a plain run
after adding a dependency changes only what that dependency needs. Requires
`uv` on PATH.

Two things uv cannot emit on its own are added after it runs: the header, and
the PyTorch CPU index. `--torch-backend cpu` resolves torch to its `+cpu` build,
which lives only on download.pytorch.org, but uv writes just the PyPI index
URL — without the extra line, `pip install -r requirements.lock` cannot find
torch. The CPU build is the point: the VPS has no GPU, and the PyPI Linux
torch wheel pulls in the CUDA runtime packages.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements.lock"
PYPI = "--index-url https://pypi.org/simple\n"
TORCH_CPU = (
    "# CPU-only torch: the VPS has no GPU; see scripts/lock_requirements.py.\n"
    "--extra-index-url https://download.pytorch.org/whl/cpu\n"
)
HEADER = (
    "# requirements.lock: the exact, hash-pinned environment production and CI install.\n"
    "# Generated for CPython 3.14 on x86_64 Linux (the VPS) by scripts/lock_requirements.py;\n"
    "# regenerate it with that script, never edit it by hand.\n"
    "# Install: pip install --require-hashes -r requirements.lock\n"
)


def main(extra_args: list[str]) -> int:
    cmd = [
        "uv",
        "pip",
        "compile",
        "requirements.txt",
        "--python-version",
        "3.14",
        "--python-platform",
        "x86_64-manylinux_2_28",
        "--torch-backend",
        "cpu",
        "--generate-hashes",
        "--emit-index-url",
        "--no-header",
        "--output-file",
        "requirements.lock",
        *extra_args,
    ]
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode != 0:
        return result.returncode

    body = LOCK.read_text(encoding="utf-8")
    # uv echoes the old header back as plain comments on a re-run; drop them.
    header_lines = set(HEADER.splitlines(keepends=True))
    body = "".join(line for line in body.splitlines(keepends=True) if line not in header_lines)
    body = body.replace(TORCH_CPU, "")
    if PYPI not in body:
        print("uv output has no PyPI index line; refusing to guess where torch goes.")
        return 1
    LOCK.write_text(HEADER + body.replace(PYPI, PYPI + TORCH_CPU, 1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
