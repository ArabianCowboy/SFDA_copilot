"""Inline SVG icon set — one source of truth for templates and the browser.

The build used to load the bootstrap-icons webfont from a CDN and write
``<i class="bi bi-x">`` everywhere. A font glyph cannot be given a stroke
weight, cannot be sized independently of the text it sits in, and — the
reason this exists — arrives as a separate network request whose failure
leaves empty boxes in the UI. Emoji were worse still: the composer's
category selector shipped 🌐 📋 💊 🐾 🧬, which render per-platform, ignore
``currentColor`` and cannot follow the theme.

Every path below is drawn on bootstrap-icons' 16-unit grid and filled with
``currentColor``, so an icon inherits the colour of whatever names it and
flips with the theme for free. Path data for the glyphs that already shipped
is bootstrap-icons' own (MIT, © 2019 The Bootstrap Authors); the five
category glyphs and a handful of others are drawn here to match its optical
weight.

Wiring mirrors i18n exactly:
  * ``icon()`` is a Jinja global, for server-rendered markup.
  * ``runtime_icons()`` is inlined as ``window.__ICONS`` for the modules that
    build DOM in the browser. No extra request, no CSP change.

Adding a glyph means adding it here once. If a name is missing at render
time the call raises rather than emitting an empty ``<svg>``, because a
silently blank icon is the failure mode this whole file exists to remove.
"""

from __future__ import annotations

from markupsafe import Markup

__all__ = ["ICONS", "CATEGORY_ICONS", "RUNTIME_ICON_NAMES", "icon", "runtime_icons"]


# Raw path data, keyed by the name the rest of the codebase uses. Values are
# the inner markup of a `viewBox="0 0 16 16"` svg — paths only, no wrapper.
ICONS: dict[str, str] = {
    # ── Chrome & navigation ──────────────────────────────────────────
    "shield": (
        '<path d="M8 .5a.5.5 0 0 1 .22.05l5.5 2.5A.5.5 0 0 1 14 3.5v4.4c0 '
        "3.2-2.1 6.1-5.84 7.57a.5.5 0 0 1-.32 0C4.1 14 2 11.1 2 7.9V3.5a.5.5 0 "
        '0 1 .28-.45l5.5-2.5A.5.5 0 0 1 8 .5m0 1.05L3 3.82V7.9c0 2.71 1.72 '
        '5.16 5 6.51 3.28-1.35 5-3.8 5-6.51V3.82z"/>'
        '<path d="M8 4.5a.5.5 0 0 1 .5.5v3.2l2.06 1.19a.5.5 0 1 1-.5.87l-2.31'
        '-1.34A.5.5 0 0 1 7.5 8.5V5a.5.5 0 0 1 .5-.5"/>'
    ),
    "shield-check": (
        '<path d="M8 .5a.5.5 0 0 1 .22.05l5.5 2.5A.5.5 0 0 1 14 3.5v4.4c0 '
        "3.2-2.1 6.1-5.84 7.57a.5.5 0 0 1-.32 0C4.1 14 2 11.1 2 7.9V3.5a.5.5 0 "
        '0 1 .28-.45l5.5-2.5A.5.5 0 0 1 8 .5m0 1.05L3 3.82V7.9c0 2.71 1.72 '
        '5.16 5 6.51 3.28-1.35 5-3.8 5-6.51V3.82z"/>'
        '<path d="M10.85 5.9a.5.5 0 0 1 .02.71l-3.2 3.4a.5.5 0 0 1-.72.01L5.16 '
        '8.2a.5.5 0 1 1 .7-.72l1.43 1.4 2.85-3.02a.5.5 0 0 1 .71-.02"/>'
    ),
    "menu": (
        '<path d="M2 4.5a.5.5 0 0 1 .5-.5h11a.5.5 0 0 1 0 1h-11a.5.5 0 0 1-.5'
        '-.5m0 3.5a.5.5 0 0 1 .5-.5h11a.5.5 0 0 1 0 1h-11A.5.5 0 0 1 2 8m0 '
        '3.5a.5.5 0 0 1 .5-.5h11a.5.5 0 0 1 0 1h-11a.5.5 0 0 1-.5-.5"/>'
    ),
    "close": (
        '<path d="M3.65 3.65a.5.5 0 0 1 .7 0L8 7.29l3.65-3.64a.5.5 0 1 1 .7 '
        '.7L8.71 8l3.64 3.65a.5.5 0 0 1-.7.7L8 8.71l-3.65 3.64a.5.5 0 0 '
        '1-.7-.7L7.29 8 3.65 4.35a.5.5 0 0 1 0-.7"/>'
    ),
    "moon": (
        '<path d="M6 .28a.77.77 0 0 1 .08.86 7.2 7.2 0 0 0-.88 3.46c0 4.02 '
        "3.28 7.28 7.32 7.28.53 0 1.04-.06 1.53-.16a.79.79 0 0 1 .81.31.73.73 "
        '0 0 1-.03.9A8.35 8.35 0 0 1 8.34 16C3.73 16 0 12.29 0 7.71 0 4.27 '
        '2.11 1.31 5.12.06A.75.75 0 0 1 6 .28"/>'
    ),
    "sun": (
        '<path d="M8 11a3 3 0 1 1 0-6 3 3 0 0 1 0 6m0 1a4 4 0 1 0 0-8 4 4 0 0 '
        "0 0 8M8 0a.5.5 0 0 1 .5.5v2a.5.5 0 0 1-1 0v-2A.5.5 0 0 1 8 0m0 "
        "13a.5.5 0 0 1 .5.5v2a.5.5 0 0 1-1 0v-2A.5.5 0 0 1 8 13m8-5a.5.5 0 0 "
        "1-.5.5h-2a.5.5 0 0 1 0-1h2a.5.5 0 0 1 .5.5M3 8a.5.5 0 0 1-.5.5h-2a.5"
        ".5 0 0 1 0-1h2A.5.5 0 0 1 3 8m10.66-5.66a.5.5 0 0 1 0 .71l-1.42 "
        "1.41a.5.5 0 1 1-.7-.7l1.41-1.42a.5.5 0 0 1 .71 0M4.46 11.54a.5.5 0 0 "
        "1 0 .7l-1.41 1.42a.5.5 0 0 1-.71-.71l1.41-1.41a.5.5 0 0 1 .71 "
        "0m9.2 1.41a.5.5 0 0 1-.71 0l-1.41-1.41a.5.5 0 0 1 .7-.71l1.42 "
        '1.41a.5.5 0 0 1 0 .71M4.46 4.46a.5.5 0 0 1-.71 0L2.34 3.05a.5.5 0 1 '
        '1 .71-.71l1.41 1.41a.5.5 0 0 1 0 .71"/>'
    ),
    "user-circle": (
        '<path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1M0 8a8 8 0 1 1 16 0A8 8 0 0 '
        '1 0 8"/>'
        '<path d="M8 8a2.25 2.25 0 1 0 0-4.5A2.25 2.25 0 0 0 8 8m0 1c-2.3 '
        "0-4.2 1.28-4.83 3.02a.5.5 0 0 0 .16.56 6.97 6.97 0 0 0 9.34 0 .5.5 0 "
        '0 0 .16-.56C12.2 10.28 10.3 9 8 9"/>'
    ),
    "user": (
        '<path d="M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6m0 1c-2.67 0-5 1.6-5 3.5V14a'
        '.5.5 0 0 0 .5.5h9a.5.5 0 0 0 .5-.5v-1.5C13 10.6 10.67 9 8 9"/>'
    ),
    "sign-in": (
        '<path d="M6 2.5a.5.5 0 0 1 .5-.5h5A1.5 1.5 0 0 1 13 3.5v9a1.5 1.5 0 0 '
        "1-1.5 1.5h-5a.5.5 0 0 1 0-1h5a.5.5 0 0 0 .5-.5v-9a.5.5 0 0 "
        '0-.5-.5h-5a.5.5 0 0 1-.5-.5"/>'
        '<path d="M8.15 7.5H3.5a.5.5 0 0 0 0 1h4.65L6.6 10.04a.5.5 0 0 0 .7 '
        '.72l2.4-2.4a.5.5 0 0 0 0-.72l-2.4-2.4a.5.5 0 1 0-.7.72z"/>'
    ),
    "user-plus": (
        '<path d="M7 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6m0 1c-2.67 0-5 1.6-5 3.5V14a'
        '.5.5 0 0 0 .5.5h9a.5.5 0 0 0 .5-.5v-1.5C12 10.6 9.67 9 7 9"/>'
        '<path d="M13 4.5a.5.5 0 0 1 .5.5v1h1a.5.5 0 0 1 0 1h-1v1a.5.5 0 0 '
        '1-1 0V7h-1a.5.5 0 0 1 0-1h1V5a.5.5 0 0 1 .5-.5"/>'
    ),
    "logout": (
        '<path d="M10 2.5a.5.5 0 0 0-.5-.5h-5A1.5 1.5 0 0 0 3 3.5v9A1.5 1.5 0 '
        "0 0 4.5 14h5a.5.5 0 0 0 0-1h-5a.5.5 0 0 1-.5-.5v-9a.5.5 0 0 1 "
        '.5-.5h5a.5.5 0 0 0 .5-.5"/>'
        '<path d="M12.15 7.5H7.5a.5.5 0 0 0 0 1h4.65l-1.55 1.54a.5.5 0 0 0 .7 '
        '.72l2.4-2.4a.5.5 0 0 0 0-.72l-2.4-2.4a.5.5 0 1 0-.7.72z"/>'
    ),
    "mail": (
        '<path d="M2 3.5h12A1.5 1.5 0 0 1 15.5 5v6a1.5 1.5 0 0 1-1.5 1.5H2A1.5 '
        "1.5 0 0 1 .5 11V5A1.5 1.5 0 0 1 2 3.5m0 1a.5.5 0 0 0-.5.5v.27l6.5 "
        "3.42 6.5-3.42V5a.5.5 0 0 0-.5-.5zm12.5 1.9L8.23 9.69a.5.5 0 0 "
        '1-.46 0L1.5 6.4V11a.5.5 0 0 0 .5.5h12a.5.5 0 0 0 .5-.5z"/>'
    ),
    "lock": (
        '<path d="M8 1a3 3 0 0 0-3 3v2h-.5A1.5 1.5 0 0 0 3 7.5v6A1.5 1.5 0 0 0 '
        "4.5 15h7a1.5 1.5 0 0 0 1.5-1.5v-6A1.5 1.5 0 0 0 11.5 6H11V4a3 3 0 0 "
        '0-3-3m2 5H6V4a2 2 0 1 1 4 0zM4.5 7h7a.5.5 0 0 1 .5.5v6a.5.5 0 0 '
        '1-.5.5h-7a.5.5 0 0 1-.5-.5v-6a.5.5 0 0 1 .5-.5"/>'
    ),
    "building": (
        '<path d="M3 1.5A1.5 1.5 0 0 1 4.5 0h7A1.5 1.5 0 0 1 13 1.5v13a.5.5 0 '
        "0 1-.5.5h-9a.5.5 0 0 1-.5-.5zm1.5-.5a.5.5 0 0 0-.5.5V14h8V1.5a.5.5 0 "
        '0 0-.5-.5z"/>'
        '<path d="M5.5 3h1v1h-1zm2 0h1v1h-1zm2 0h1v1h-1zm-4 2.5h1v1h-1zm2 '
        "0h1v1h-1zm2 0h1v1h-1zm-4 2.5h1v1h-1zm2 0h1v1h-1zm2 0h1v1h-1zM7 "
        '10.5h2V14H7z"/>'
    ),
    "briefcase": (
        '<path d="M6.5 1A1.5 1.5 0 0 0 5 2.5V4H2.5A1.5 1.5 0 0 0 1 5.5v7A1.5 '
        "1.5 0 0 0 2.5 14h11a1.5 1.5 0 0 0 1.5-1.5v-7A1.5 1.5 0 0 0 13.5 "
        "4H11V2.5A1.5 1.5 0 0 0 9.5 1zM6 2.5a.5.5 0 0 1 .5-.5h3a.5.5 0 0 1 .5 "
        '.5V4H6zM2.5 5h11a.5.5 0 0 1 .5.5v7a.5.5 0 0 1-.5.5h-11a.5.5 0 0 '
        '1-.5-.5v-7a.5.5 0 0 1 .5-.5"/>'
    ),
    "palette": (
        '<path d="M8 1a7 7 0 0 0 0 14c.83 0 1.5-.67 1.5-1.5 0-.39-.15-.74-.39'
        "-1-.24-.27-.39-.62-.39-1 0-.83.67-1.5 1.5-1.5H12a3 3 0 0 0 3-3c0-3.3"
        "-3.13-6-7-6m0 1c3.36 0 6 2.29 6 5a2 2 0 0 1-2 2h-1.78A2.5 2.5 0 0 0 "
        '7.72 11.5c0 .63.24 1.2.64 1.64a.5.5 0 0 1-.36.86A6 6 0 0 1 8 2"/>'
        '<path d="M4.75 7.5a1 1 0 1 0 0-2 1 1 0 0 0 0 2m2.5-2a1 1 0 1 0 0-2 1 '
        '1 0 0 0 0 2m3.5 0a1 1 0 1 0 0-2 1 1 0 0 0 0 2M4 10.5a1 1 0 1 0 0-2 1 '
        '1 0 0 0 0 2"/>'
    ),
    # ── Landing ──────────────────────────────────────────────────────
    "arrow-right": (
        '<path d="M8.65 3.15a.5.5 0 0 1 .7 0l4.5 4.5a.5.5 0 0 1 0 .7l-4.5 '
        '4.5a.5.5 0 0 1-.7-.7L12.29 8.5H2a.5.5 0 0 1 0-1h10.29L8.65 3.85a.5.5 '
        '0 0 1 0-.7"/>'
    ),
    "arrow-down": (
        '<path d="M8 2a.5.5 0 0 1 .5.5v10.29l3.65-3.64a.5.5 0 0 1 .7.7l-4.5 '
        '4.5a.5.5 0 0 1-.7 0l-4.5-4.5a.5.5 0 1 1 .7-.7l3.65 3.64V2.5A.5.5 0 0 '
        '1 8 2"/>'
    ),
    "calendar-check": (
        '<path d="M10.85 7.15a.5.5 0 0 1 0 .7l-3 3a.5.5 0 0 1-.7 0l-1.5-1.5a.5'
        '.5 0 1 1 .7-.7L7.5 9.79l2.65-2.64a.5.5 0 0 1 .7 0"/>'
        '<path d="M3.5 0a.5.5 0 0 1 .5.5V1h8V.5a.5.5 0 0 1 1 0V1h1a2 2 0 0 1 2 '
        "2v11a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2h1V.5a.5.5 0 0 1 "
        '.5-.5M1 4v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V4z"/>'
    ),
    "collection": (
        '<path d="M2.5 3.5a.5.5 0 0 1 .5-.5h10a.5.5 0 0 1 0 1H3a.5.5 0 0 '
        "1-.5-.5M1 5.5a.5.5 0 0 1 .5-.5h13a.5.5 0 0 1 0 1h-13a.5.5 0 0 1-.5"
        '-.5"/>'
        '<path d="M0 8a1.5 1.5 0 0 1 1.5-1.5h13A1.5 1.5 0 0 1 16 8v5a1.5 1.5 0 '
        '0 1-1.5 1.5h-13A1.5 1.5 0 0 1 0 13zm1.5-.5a.5.5 0 0 0-.5.5v5a.5.5 0 0 '
        '0 .5.5h13a.5.5 0 0 0 .5-.5V8a.5.5 0 0 0-.5-.5z"/>'
    ),
    "journal": (
        '<path d="M4 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V2a2 2 0 '
        '0 0-2-2zM3 2a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 '
        '1-1-1z"/>'
        '<path d="M5 3.5a.5.5 0 0 1 .5-.5h5a.5.5 0 0 1 0 1h-5a.5.5 0 0 1-.5-.5m'
        "0 2.5a.5.5 0 0 1 .5-.5h5a.5.5 0 0 1 0 1h-5A.5.5 0 0 1 5 6m0 2.5a.5.5 "
        '0 0 1 .5-.5h3a.5.5 0 0 1 0 1h-3a.5.5 0 0 1-.5-.5"/>'
    ),
    "translate": (
        '<path d="M2 1.5A.5.5 0 0 1 2.5 1h4a.5.5 0 0 1 0 1H5v1.06a5.9 5.9 0 0 '
        "1-1.02 3.3 5.6 5.6 0 0 0 1.3 1.22.5.5 0 1 1-.56.83A6.6 6.6 0 0 1 "
        "3.35 7.2a6.6 6.6 0 0 1-2.1 1.66.5.5 0 1 1-.44-.9 5.6 5.6 0 0 0 1.9"
        '-1.53A5.9 5.9 0 0 1 1.7 4.5a.5.5 0 1 1 .96-.28 4.9 4.9 0 0 0 .69 '
        '1.45A4.9 4.9 0 0 0 4 3.06V2H2.5a.5.5 0 0 1-.5-.5"/>'
        '<path d="M10.28 6.2a.5.5 0 0 0-.93 0l-3 8a.5.5 0 1 0 .94.34l.76-2.04h'
        '3.53l.76 2.04a.5.5 0 1 0 .94-.34zm-1.86 5.3 1.4-3.72 1.39 3.72z"/>'
    ),
    "search": (
        '<path d="M11.74 10.34a6 6 0 1 0-1.4 1.4l3.26 3.26a.5.5 0 0 0 .7-.7zM'
        '2 6.5a4.5 4.5 0 1 1 9 0 4.5 4.5 0 0 1-9 0"/>'
    ),
    # ── Chat ─────────────────────────────────────────────────────────
    "question": (
        '<path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1M0 8a8 8 0 1 1 16 0A8 8 0 0 '
        '1 0 8"/>'
        '<path d="M5.26 5.79a.24.24 0 0 0 .24.24h.82c.14 0 .25-.11.27-.25.09'
        "-.65.54-1.13 1.34-1.13.69 0 1.31.34 1.31 1.17 0 .63-.37.92-.96 "
        "1.37-.67.49-1.2 1.06-1.17 1.98v.22c0 .14.11.25.25.25h.81c.14 0 .25"
        "-.12.25-.25v-.11c0-.72.27-.93 1.01-1.49.61-.46 1.24-.98 1.24-2.05 0"
        '-1.51-1.27-2.24-2.67-2.24-1.26 0-2.65.59-2.74 2.29m1.55 5.76c0 .53.43'
        '.93 1.01.93.61 0 1.03-.4 1.03-.93 0-.55-.42-.94-1.03-.94-.58 0-1.01'
        '.39-1.01.94"/>'
    ),
    "filter": (
        '<path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1M0 8a8 8 0 1 1 16 0A8 8 0 0 '
        '1 0 8"/>'
        '<path d="M4.5 5.5a.5.5 0 0 1 .5-.5h6a.5.5 0 0 1 0 1H5a.5.5 0 0 1-.5'
        "-.5m1 2.5a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 0 1H6a.5.5 0 0 1-.5-.5m1 "
        '2.5a.5.5 0 0 1 .5-.5h2a.5.5 0 0 1 0 1H7a.5.5 0 0 1-.5-.5"/>'
    ),
    "pointer": (
        '<path d="M6.5 1.5a1.5 1.5 0 0 1 3 0v4.06c.2-.04.4-.06.6-.06a1.9 1.9 0 '
        "0 1 1.6.83A1.9 1.9 0 0 1 15 8v2.5a4.5 4.5 0 0 1-4.5 4.5H9a4 4 0 0 "
        "1-3.4-1.9L3.3 9.4a1.5 1.5 0 0 1 2.3-1.86l.9.9zm1.5-.5a.5.5 0 0 0-.5 "
        ".5v8.2a.5.5 0 0 1-.85.35L4.9 8.25a.5.5 0 0 0-.75.65l2.3 3.7A3 3 0 0 0 "
        '9 14h1.5A3.5 3.5 0 0 0 14 10.5V8a.9.9 0 0 0-1.8 0 .5.5 0 0 1-1 0 .9.9 '
        '0 0 0-1.8 0 .5.5 0 0 1-1 0V1.5a.5.5 0 0 0-.4-.5"/>'
    ),
    "info": (
        '<path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1M0 8a8 8 0 1 1 16 0A8 8 0 0 '
        '1 0 8"/>'
        '<path d="M8 6.5a.5.5 0 0 1 .5.5v4.5a.5.5 0 0 1-1 0V7a.5.5 0 0 1 .5-.5'
        'M8 5.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5"/>'
    ),
    "alert": (
        '<path d="M7.13 1.75a1 1 0 0 1 1.74 0l6 10.5A1 1 0 0 1 14 13.75H2a1 1 '
        "0 0 1-.87-1.5zM8 5a.5.5 0 0 0-.5.5v3.75a.5.5 0 0 0 1 0V5.5A.5.5 0 0 "
        '0 8 5m0 7a.75.75 0 1 0 0-1.5A.75.75 0 0 0 8 12"/>'
    ),
    "send": (
        '<path d="M15.3.72a.5.5 0 0 1 .12.54l-5.25 14a.5.5 0 0 1-.93.02L6.6 '
        "9.4 1.22 6.76a.5.5 0 0 1 .02-.91l14-5.25a.5.5 0 0 1 .54.12M7.4 "
        '8.86l2.15 4.62L13.7 2.3zm5.6-7.27L2.52 5.53l4.62 2.14z"/>'
    ),
    "stop": (
        '<path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1M0 8a8 8 0 1 1 16 0A8 8 0 0 '
        '1 0 8"/>'
        '<path d="M6 5.5A.5.5 0 0 1 6.5 5h3a.5.5 0 0 1 .5.5v5a.5.5 0 0 1-.5.5h'
        '-3a.5.5 0 0 1-.5-.5z"/>'
    ),
    "lightbulb": (
        '<path d="M8 1a4.5 4.5 0 0 0-2.62 8.16c.3.22.5.53.56.88l.12.71a.5.5 0 '
        "0 0 .5.42h2.88a.5.5 0 0 0 .5-.42l.12-.71c.06-.35.26-.66.56-.88A4.5 "
        '4.5 0 0 0 8 1"/>'
        '<path d="M6.2 12.25a.5.5 0 0 1 .5-.5h2.6a.5.5 0 0 1 0 1H6.7a.5.5 0 0 '
        '1-.5-.5m.6 1.75a.5.5 0 0 1 .5-.5h1.4a.5.5 0 0 1 0 1H7.3a.5.5 0 0 '
        '1-.5-.5"/>'
    ),
    "chevron-down": (
        '<path d="M3.65 5.65a.5.5 0 0 1 .7 0L8 9.29l3.65-3.64a.5.5 0 0 1 .7 '
        '.7l-4 4a.5.5 0 0 1-.7 0l-4-4a.5.5 0 0 1 0-.7"/>'
    ),
    "chevron-right": (
        '<path d="M5.65 3.65a.5.5 0 0 1 .7 0l4 4a.5.5 0 0 1 0 .7l-4 4a.5.5 0 0 '
        '1-.7-.7L9.29 8 5.65 4.35a.5.5 0 0 1 0-.7"/>'
    ),
    "check": (
        '<path d="M13.35 3.65a.5.5 0 0 1 0 .7l-7 7a.5.5 0 0 1-.7 0l-3-3a.5.5 0 '
        '1 1 .7-.7L6 10.29l6.65-6.64a.5.5 0 0 1 .7 0"/>'
    ),
    # ── Corpus categories ────────────────────────────────────────────
    # One glyph per category, used by BOTH the sidebar's FAQ group headings
    # and the composer's category selector, so the same mark always means the
    # same slice of the corpus. These five replace the emoji.
    "globe": (
        '<path d="M8 0a8 8 0 1 0 0 16A8 8 0 0 0 8 0M1.02 8.5h2.75c.06 1.53.3 '
        "2.94.68 4.1a7.02 7.02 0 0 1-3.43-4.1m2.75-1H1.02a7.02 7.02 0 0 1 "
        "3.43-4.1c-.37 1.16-.62 2.57-.68 4.1m1 0c.07-1.6.34-3 .72-4.05.2-.55.4"
        "3-.95.63-1.19.2-.23.34-.26.38-.26s.19.03.38.26c.2.24.44.64.63 1.19.38"
        " 1.04.65 2.46.72 4.05zm0 1h3.46c-.07 1.6-.34 3-.72 4.05-.2.55-.43.95"
        "-.63 1.19-.2.23-.34.26-.38.26s-.19-.03-.38-.26a3.3 3.3 0 0 1-.63-1.19"
        "c-.38-1.04-.65-2.46-.72-4.05m4.46 0h2.75a7.02 7.02 0 0 1-3.43 4.1c.37"
        '-1.16.62-2.57.68-4.1m0-1c-.06-1.53-.3-2.94-.68-4.1a7.02 7.02 0 0 1 '
        '3.43 4.1z"/>'
    ),
    "clipboard": (
        '<path d="M6.5 0A1.5 1.5 0 0 0 5 1.5h-.5A1.5 1.5 0 0 0 3 3v11.5A1.5 '
        "1.5 0 0 0 4.5 16h7a1.5 1.5 0 0 0 1.5-1.5V3a1.5 1.5 0 0 0-1.5-1.5H11A"
        "1.5 1.5 0 0 0 9.5 0zM6 1.5a.5.5 0 0 1 .5-.5h3a.5.5 0 0 1 .5.5V2a.5.5 "
        "0 0 1-.5.5h-3A.5.5 0 0 1 6 2zM4.5 2.5H5A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 "
        '0 0 0 11 2.5h.5a.5.5 0 0 1 .5.5v11.5a.5.5 0 0 1-.5.5h-7a.5.5 0 0 '
        '1-.5-.5V3a.5.5 0 0 1 .5-.5"/>'
        '<path d="M5.5 6.5a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 0 1H6a.5.5 0 0 1-.5'
        '-.5m0 2.5a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 0 1H6a.5.5 0 0 1-.5-.5m0 '
        '2.5a.5.5 0 0 1 .5-.5h2.5a.5.5 0 0 1 0 1H6a.5.5 0 0 1-.5-.5"/>'
    ),
    "capsule": (
        '<path d="M11.5 1a3.5 3.5 0 0 1 2.47 5.98l-7 7A3.5 3.5 0 1 1 2.03 '
        "9.03l7-7A3.5 3.5 0 0 1 11.5 1m0 1c-.66 0-1.3.26-1.76.73L6.65 "
        "5.82l3.53 3.53 3.09-3.09A2.5 2.5 0 0 0 11.5 2M9.47 10.06 5.94 "
        '6.53 2.74 9.74a2.5 2.5 0 0 0 3.52 3.52z"/>'
    ),
    # Ellipses rather than outlined paths: at the 14–15px these actually render
    # at, a paw drawn as five simple masses reads instantly, and one drawn with
    # detailed toe outlines turns to mush.
    "paw": (
        '<path d="M8 8.9c1.72 0 3.13.92 3.82 2.23.29.53.48 1.04.48 1.62A2.65 '
        "2.65 0 0 1 9.65 15.4c-.56 0-1.09-.18-1.65-.18s-1.09.18-1.65.18A2.65 "
        '2.65 0 0 1 3.7 12.75c0-.58.19-1.09.48-1.62C4.87 9.82 6.28 8.9 8 8.9"/>'
        '<ellipse cx="5.6" cy="4.7" rx="1.6" ry="2.25" transform="rotate(-12 5.6 4.7)"/>'
        '<ellipse cx="10.4" cy="4.7" rx="1.6" ry="2.25" transform="rotate(12 10.4 4.7)"/>'
        '<ellipse cx="2.6" cy="8.4" rx="1.45" ry="2" transform="rotate(-38 2.6 8.4)"/>'
        '<ellipse cx="13.4" cy="8.4" rx="1.45" ry="2" transform="rotate(38 13.4 8.4)"/>'
    ),
    # A droplet, not a double helix. The helix drawn here first was two crossing
    # strands and four rungs — legible at 32px and indistinguishable from noise
    # at the 15px the selector renders. This is also the mark the FAQ rail
    # already used for the category, so it is continuity rather than invention.
    "droplet": (
        '<path d="M8 .5a.5.5 0 0 1 .4.2 34 34 0 0 1 3.42 4.9c1.1 1.83 1.88 '
        "3.68 1.88 5.15a5.7 5.7 0 1 1-11.4 0c0-1.47.79-3.32 1.88-5.15A34 34 0 "
        '0 1 7.6.7.5.5 0 0 1 8 .5m0 1.35a35 35 0 0 0-2.96 4.28C3.98 7.9 3.3 '
        '9.53 3.3 10.75a4.7 4.7 0 0 0 9.4 0c0-1.22-.68-2.85-1.74-4.62A35 35 0 '
        '0 0 8 1.85"/>'
        '<path d="M8 13.4a2.65 2.65 0 0 1-2.65-2.65.5.5 0 0 1 1 0A1.65 1.65 0 '
        '0 0 8 12.4a.5.5 0 0 1 0 1"/>'
    ),
}


# The composer's selector and the FAQ rail read from the same map, so a
# category's mark never drifts between the two places it appears.
CATEGORY_ICONS: dict[str, str] = {
    "all": "globe",
    "regulatory": "clipboard",
    "pharmacovigilance": "capsule",
    "veterinary": "paw",
    "biological": "droplet",
}


# Only these reach the browser — the modules in static/js build DOM for them.
# Shipping the whole set would inline roughly 8 KB of unused path data on
# every page load.
RUNTIME_ICON_NAMES: tuple[str, ...] = (
    "sun",
    "moon",
    "send",
    "stop",
    "lightbulb",
    "chevron-right",
    "alert",
    "question",
    *CATEGORY_ICONS.values(),
)


def icon(name: str, size: int = 16, cls: str = "", title: str = "") -> Markup:
    """Render one icon as inline SVG.

    ``size`` is in px and sets both axes. ``cls`` is appended to the base
    ``.icon`` class. A ``title`` makes the icon a labelled ``img`` for
    assistive tech; without one it is hidden, which is right for the common
    case where adjacent text already names the thing.
    """
    try:
        paths = ICONS[name]
    except KeyError:  # pragma: no cover - a typo should fail loudly, not blank
        raise KeyError(
            f"unknown icon {name!r}; add it to web/utils/icons.py"
        ) from None

    classes = f"icon {cls}".strip()
    if title:
        label = f'role="img" aria-label="{title}"'
    else:
        label = 'aria-hidden="true" focusable="false"'

    return Markup(
        f'<svg class="{classes}" width="{size}" height="{size}" '
        f'viewBox="0 0 16 16" fill="currentColor" {label}>{paths}</svg>'
    )


def runtime_icons() -> dict[str, str]:
    """The path-data subset inlined as ``window.__ICONS``."""
    return {name: ICONS[name] for name in RUNTIME_ICON_NAMES}
