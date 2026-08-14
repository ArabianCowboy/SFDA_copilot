"""Catalogue loading and language negotiation.

One YAML file per language, loaded once and cached. The ``runtime`` subtree is
handed to the browser as an inline JSON blob; the ``page`` subtree is rendered
server-side, so an Arabic reader never sees a flash of English while JS boots.

Missing Arabic keys fall back to English rather than rendering blank, so a
partial translation degrades to mixed language instead of a broken interface.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

I18N_DIR = Path(__file__).resolve().parents[1] / "i18n"
DEFAULT_LANG = "en"
SUPPORTED_LANGS = ("en", "ar")
RTL_LANGS = frozenset({"ar"})


def _deep_merge(base: dict, override: dict) -> dict:
    """Override wins, but missing keys keep the base (English) value."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=len(SUPPORTED_LANGS))
def _load_raw(lang: str) -> dict[str, Any]:
    path = I18N_DIR / f"{lang}.yaml"
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except FileNotFoundError:
        logger.error("Missing i18n catalogue: %s", path)
    except Exception:
        logger.error("Failed to parse i18n catalogue %s", path, exc_info=True)
    return {}


@lru_cache(maxsize=len(SUPPORTED_LANGS))
def load_catalog(lang: str) -> dict[str, Any]:
    """Return a complete catalogue, English-backfilled."""
    lang = normalize_lang(lang)
    english = _load_raw(DEFAULT_LANG)
    if lang == DEFAULT_LANG:
        return english
    return _deep_merge(english, _load_raw(lang))


def normalize_lang(lang: str | None) -> str:
    if not lang:
        return DEFAULT_LANG
    code = lang.strip().lower().replace("_", "-").split("-")[0]
    return code if code in SUPPORTED_LANGS else DEFAULT_LANG


def is_rtl(lang: str) -> bool:
    return normalize_lang(lang) in RTL_LANGS


def text_direction(lang: str) -> str:
    return "rtl" if is_rtl(lang) else "ltr"


def pick_lang(request) -> str:
    """Cookie, then Accept-Language, then English.

    An explicit ?lang= wins over both so a link can force a language.
    """
    requested = request.args.get("lang")
    if requested:
        return normalize_lang(requested)

    cookie = request.cookies.get("lang")
    if cookie:
        return normalize_lang(cookie)

    best = request.accept_languages.best_match(SUPPORTED_LANGS)
    return normalize_lang(best)


def make_translator(catalog: dict[str, Any]) -> Callable[..., str]:
    """Return ``t('page.landing.cta')`` with {placeholder} interpolation."""

    def t(key: str, **params: Any) -> str:
        node: Any = catalog
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                logger.warning("Missing i18n key: %s", key)
                return key
            node = node[part]

        if not isinstance(node, str):
            logger.warning("i18n key is not a string: %s", key)
            return key

        if not params:
            return node
        try:
            return node.format(**params)
        except (KeyError, IndexError):
            logger.warning("Unresolved placeholder in i18n key: %s", key)
            return node

    return t


def runtime_subset(catalog: dict[str, Any], *, include_admin: bool = False) -> dict[str, Any]:
    """The slice of the catalogue the browser needs.

    ``runtime.admin`` is withheld by default. It is the largest block in the
    file and it enumerates operator capabilities, so inlining it into the
    anonymous landing page would advertise the console's whole surface to
    anyone who views source — for strings that page can never use.

    The returned mapping is always a **copy**. ``load_catalog`` is
    ``lru_cache``d and hands back the same dict to every request, so popping
    from it in place would strip the admin block from the cached catalogue and
    every later render would silently lose it.
    """
    runtime = dict(catalog.get("runtime", {}))
    if not include_admin:
        runtime.pop("admin", None)
    return runtime
