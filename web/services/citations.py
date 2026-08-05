"""Turn SearchResult objects into a JSON-safe citation payload.

The search layer already computes everything a reader needs to judge an
answer — which document, which page, and how strongly it matched both
semantically and lexically — and the API used to throw all of it away. This
module is what carries it to the client.

Two things here are load-bearing:

1. **Type coercion.** ``ResultCombiner`` builds ``SearchResult`` from pandas
   cells and numpy index arrays, so ``page``/``chunk_id``/``score`` routinely
   arrive as ``np.int64`` / ``np.float32`` / ``NaN``. ``json.dumps`` raises
   ``TypeError: Object of type int64 is not JSON serializable`` on those, which
   surfaces as a bare 500. Every field is coerced, and the type hints on
   ``SearchResult`` are NOT trusted.

2. **Index alignment.** ``sources[i]["index"]`` must equal the ``[i]`` label the
   model saw in its prompt context, or a citation points at a card the model
   never read. Both are sliced with the same ``limit``.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Iterable

logger = logging.getLogger(__name__)

SNIPPET_CHARS = 320

# Matches the prose citation format the model used before numbered context
# blocks: "[Source: Guidance.pdf, Page: 14]", page optional.
LEGACY_CITATION = re.compile(
    r"\[\s*Source\s*:\s*(?P<doc>[^,\]]+?)\s*(?:,\s*Page\s*:\s*(?P<page>\d+)\s*)?\]",
    re.IGNORECASE,
)


def _to_float(value: Any) -> float | None:
    """Coerce numpy/pandas scalars to a plain float, mapping NaN to None."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else round(result, 4)


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return int(result)


def _to_str(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    try:
        if isinstance(value, float) and math.isnan(value):
            return fallback
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or fallback


def _snippet(text: Any) -> str:
    """First SNIPPET_CHARS of the retrieved chunk, whitespace collapsed."""
    collapsed = " ".join(_to_str(text).split())
    if len(collapsed) <= SNIPPET_CHARS:
        return collapsed
    return collapsed[:SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"


def build_source_payload(results: Iterable[Any], limit: int | None = None) -> list[dict[str, Any]]:
    """Serialise SearchResults into JSON-native citation cards.

    ``index`` is 1-based and matches the ``[n]`` label in the prompt context,
    so a marker in the answer resolves to exactly one card.
    """
    payload: list[dict[str, Any]] = []

    for position, result in enumerate(results, start=1):
        if limit is not None and position > limit:
            break

        metadata = getattr(result, "metadata", None) or {}

        payload.append(
            {
                "index": position,
                "document": _to_str(getattr(result, "document", None), "Unknown document"),
                "page": _to_int(getattr(result, "page", None)),
                "category": _to_str(getattr(result, "category", None), "uncategorised"),
                "score": _to_float(getattr(result, "score", None)),
                "semantic_score": _to_float(metadata.get("semantic_score")),
                "lexical_score": _to_float(metadata.get("lexical_score")),
                "chunk_id": _to_str(getattr(result, "chunk_id", None)) or None,
                "snippet": _snippet(getattr(result, "text", None)),
            }
        )

    return payload


def normalize_legacy_citations(text: str, sources: list[dict[str, Any]]) -> str:
    """Rewrite prose ``[Source: Doc, Page: N]`` citations into ``[n]`` markers.

    The model reverts to the old format occasionally — especially mid-migration,
    when the conversation history is full of examples of it. Matching on
    (document, page) is exact; a citation naming a document that is not in the
    retrieved set is dropped rather than mapped to the wrong card.
    """
    if not text or not sources:
        return text

    by_doc_page: dict[tuple[str, int | None], int] = {}
    by_doc: dict[str, int] = {}
    for source in sources:
        document = source["document"].casefold()
        by_doc_page.setdefault((document, source["page"]), source["index"])
        by_doc.setdefault(document, source["index"])

    dropped = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal dropped
        document = match.group("doc").strip().casefold()
        page = int(match.group("page")) if match.group("page") else None

        index = by_doc_page.get((document, page)) or by_doc.get(document)
        if index is None:
            dropped += 1
            return ""
        return f"[{index}]"

    result = LEGACY_CITATION.sub(replace, text)

    if dropped:
        logger.info("Dropped %d citation(s) naming documents outside the retrieved set.", dropped)

    # Collapse the whitespace left behind by dropped citations.
    return re.sub(r" +([.,;:])", r"\1", re.sub(r"[ \t]{2,}", " ", result)).strip()
