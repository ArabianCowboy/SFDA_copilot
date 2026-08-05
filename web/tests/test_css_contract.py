"""Enforces that stylesheets use writing-mode-relative (logical) properties.

Arabic support means the whole UI has to mirror. Physical properties
(``padding-left``, ``border-right``, ``left:``) do not mirror; their logical
counterparts (``padding-inline-start``, ``border-inline-end``,
``inset-inline-start``) do. Converting once and then holding the line with a
test is far cheaper than re-auditing 1000 lines of CSS every time someone adds
a rule.

A declaration that genuinely must stay physical can opt out with a trailing
``/* physical-ok: <reason> */`` comment on the same line.

ENFORCED is flipped to True in Phase 2, once the sweep has landed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


ENFORCED = True

CSS_DIR = Path(__file__).resolve().parents[2] / "static" / "css"

ESCAPE_HATCH = re.compile(r"/\*\s*physical-ok")
BLOCK_COMMENTS = re.compile(r"/\*.*?\*/", re.DOTALL)

# (human-readable name, pattern, suggested replacement)
BANNED = [
    ("padding-left", r"(?<![-\w])padding-left\s*:", "padding-inline-start"),
    ("padding-right", r"(?<![-\w])padding-right\s*:", "padding-inline-end"),
    ("margin-left", r"(?<![-\w])margin-left\s*:", "margin-inline-start"),
    ("margin-right", r"(?<![-\w])margin-right\s*:", "margin-inline-end"),
    ("border-left", r"(?<![-\w])border-left(-color|-width|-style)?\s*:", "border-inline-start"),
    ("border-right", r"(?<![-\w])border-right(-color|-width|-style)?\s*:", "border-inline-end"),
    ("border-top-left-radius", r"(?<![-\w])border-top-left-radius\s*:", "border-start-start-radius"),
    ("border-top-right-radius", r"(?<![-\w])border-top-right-radius\s*:", "border-start-end-radius"),
    ("border-bottom-left-radius", r"(?<![-\w])border-bottom-left-radius\s*:", "border-end-start-radius"),
    ("border-bottom-right-radius", r"(?<![-\w])border-bottom-right-radius\s*:", "border-end-end-radius"),
    ("left offset", r"(?<![-\w])left\s*:", "inset-inline-start"),
    ("right offset", r"(?<![-\w])right\s*:", "inset-inline-end"),
    ("text-align: left", r"text-align\s*:\s*left", "text-align: start"),
    ("text-align: right", r"text-align\s*:\s*right", "text-align: end"),
    ("float: left", r"float\s*:\s*left", "float: inline-start"),
    ("float: right", r"float\s*:\s*right", "float: inline-end"),
    ("width", r"(?<![-\w])width\s*:", "inline-size"),
    ("height", r"(?<![-\w])height\s*:", "block-size"),
]

# `width`/`height` are logical-adjacent rather than truly directional: they do
# not break RTL. They are tracked separately so the core mirror-breaking set can
# be enforced without a 400-line rewrite of every sizing declaration.
MIRROR_BREAKING = {name for name, _, _ in BANNED} - {"width", "height"}


def css_files() -> list[Path]:
    return sorted(CSS_DIR.glob("*.css"))


def scan(path: Path) -> list[tuple[int, str, str]]:
    """Return (line_no, banned_name, suggestion) for each violation in a file."""
    source = BLOCK_COMMENTS.sub(
        lambda m: "\n" * m.group(0).count("\n"), path.read_text(encoding="utf-8")
    )
    violations = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        if ESCAPE_HATCH.search(line):
            continue
        for name, pattern, suggestion in BANNED:
            if name not in MIRROR_BREAKING:
                continue
            if re.search(pattern, line):
                violations.append((line_no, name, suggestion))
    return violations


def test_css_directory_is_discoverable():
    assert css_files(), f"no stylesheets found under {CSS_DIR}"


@pytest.mark.skipif(not ENFORCED, reason="logical-property sweep lands in Phase 2")
@pytest.mark.parametrize("path", css_files(), ids=lambda p: p.name)
def test_stylesheet_uses_logical_properties(path: Path):
    violations = scan(path)
    report = "\n".join(
        f"  {path.name}:{line} uses {name} — use {suggestion}"
        for line, name, suggestion in violations
    )
    assert not violations, (
        f"{len(violations)} physical propert(ies) block RTL mirroring:\n{report}\n"
        "Add '/* physical-ok: <reason> */' on the line if it is genuinely justified."
    )


def test_report_current_violation_count(capsys):
    """Always runs — prints the burn-down number so progress is visible."""
    total = {path.name: len(scan(path)) for path in css_files()}
    with capsys.disabled():
        print("\n  physical-property violations:")
        for name, count in total.items():
            print(f"    {name:<18} {count}")
        print(f"    {'TOTAL':<18} {sum(total.values())}")
