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
    (
        "border-top-left-radius",
        r"(?<![-\w])border-top-left-radius\s*:",
        "border-start-start-radius",
    ),
    (
        "border-top-right-radius",
        r"(?<![-\w])border-top-right-radius\s*:",
        "border-start-end-radius",
    ),
    (
        "border-bottom-left-radius",
        r"(?<![-\w])border-bottom-left-radius\s*:",
        "border-end-start-radius",
    ),
    (
        "border-bottom-right-radius",
        r"(?<![-\w])border-bottom-right-radius\s*:",
        "border-end-end-radius",
    ),
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


# ── Every class the console names has to exist ───────────────────────────────
#
# The Tiers tab and the daily-allowance card shipped referencing `admin-btn`,
# `admin-btn-quiet` and `admin-hint`, none of which any stylesheet defined. The
# browser does not complain about a class that matches no rule, so the console
# rendered raw user-agent buttons and full-size body text beside the styled
# controls it was meant to match, and 80 passing browser tests said nothing —
# they assert what is on the page, and an unstyled button is still on the page.
#
# Scoped to the `admin-` prefix on purpose: this repo owns every one of those
# names, so an unmatched one is always a typo or an invention, never a class
# from Bootstrap or a CDN.

JS_DIR = Path(__file__).resolve().parents[2] / "static" / "js" / "admin"
ADMIN_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "admin.html"

# `className = '…'`, `classList.add('…')`, and a template literal's static head.
_JS_CLASS_SITES = re.compile(
    r"""className\s*=\s*[`'"]([^`'"$]*)|classList\.(?:add|toggle|remove)\(([^)]*)\)"""
)
_HTML_CLASS_SITES = re.compile(r'class="([^"]*)"')
_ADMIN_CLASS = re.compile(r"\badmin-[a-z0-9-]+")


def _referenced_admin_classes() -> dict[str, set[str]]:
    """Every `admin-*` class named from a class attribute or assignment."""
    found: dict[str, set[str]] = {}
    for path in sorted(JS_DIR.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        names: set[str] = set()
        for head, listed in _JS_CLASS_SITES.findall(text):
            # A name cut short by an interpolation (`admin-status-${…}`) is a
            # fragment, not a class. Its concrete forms are checked when they
            # appear in the stylesheet, which is where they are written out.
            names.update(n for n in _ADMIN_CLASS.findall(f"{head} {listed}") if not n.endswith("-"))
        if names:
            found[path.name] = names
    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    names = set()
    for value in _HTML_CLASS_SITES.findall(template):
        names.update(_ADMIN_CLASS.findall(value))
    if names:
        found[ADMIN_TEMPLATE.name] = names
    return found


# Names that are hooks, not styling: a JS or test selector, or a semantic
# marker on an element the browser is already told what to do with. Each is
# listed with why it draws nothing, so the next unmatched class is read as the
# defect it almost always is rather than waved through as "probably another
# one of those".
STRUCTURAL_ONLY = {
    # Duplicates `#admin-console`, whose only behaviour is the `hidden`
    # attribute `ui.js` removes once identity comes back.
    "admin-console",
    # Every panel is laid out by `.admin-panel-body` inside it and shown or
    # hidden by `hidden`; the section itself needs no box of its own.
    "admin-panel",
    # Inherits the brand's own type. It exists so the wordmark can be found.
    "admin-brand-name",
}


def _defined_class_selectors() -> set[str]:
    body = "\n".join(p.read_text(encoding="utf-8") for p in CSS_DIR.glob("*.css"))
    body = BLOCK_COMMENTS.sub("", body)
    return set(re.findall(r"\.(admin-[a-z0-9-]+)", body))


def test_the_class_scan_finds_something_to_check():
    """A regex that matched nothing would pass the test below vacuously."""
    referenced = _referenced_admin_classes()
    assert referenced, "no admin-* classes found; the extraction is broken"
    assert len(_defined_class_selectors()) > 40


def test_every_admin_class_named_in_the_console_has_a_rule():
    defined = _defined_class_selectors()
    known = defined | STRUCTURAL_ONLY
    missing = {
        source: sorted(names - known)
        for source, names in _referenced_admin_classes().items()
        if names - known
    }
    assert not missing, (
        "these classes are applied but no stylesheet defines them, so they "
        "render as nothing at all:\n"
        + "\n".join(f"  {source}: {', '.join(names)}" for source, names in missing.items())
    )
