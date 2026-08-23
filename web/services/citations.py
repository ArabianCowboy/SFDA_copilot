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
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

SNIPPET_CHARS = 320

# Matches the prose citation format the model used before numbered context
# blocks: "[Source: Guidance.pdf, Page: 14]", page optional.
#
# `lead` captures at most ONE space before the citation, so a dropped citation
# takes its own spacing with it — "a claim [Source: X], and" becomes "a claim,
# and" — without any pass over the rest of the answer. Deliberately not `[ \t]*`:
# a greedy version would eat the indentation of a line that happens to start
# with a citation, and indentation is load-bearing markdown.
LEGACY_CITATION = re.compile(
    r"(?P<lead> ?)"
    r"\[\s*Source\s*:\s*(?P<doc>[^,\]]+?)\s*(?:,\s*Page\s*:\s*(?P<page>\d+)\s*)?\]",
    re.IGNORECASE,
)

# The server-side twin of CITE_SCAN in static/js/modules/citations.js.
#
# `[0-9]` rather than `\d`, and the difference is not cosmetic: Python's `\d`
# matches every Unicode decimal digit, JavaScript's (without the `u` flag)
# matches ASCII only. So "[١]" in Arabic-Indic digits matched here — int()
# parses it happily as 1 — while the browser saw no marker at all, and the
# answer gained a source with nothing on screen pointing at it. The Arabic
# language instruction asks the model to keep markers in Latin form, which is
# exactly the kind of rule this codebase does not rely on the model obeying.
#
# `{1,2}` is deliberate and must NOT be relaxed to `+`: "[123]" matches on
# neither side.
CITATION_MARKER = re.compile(r"\[([0-9]{1,2})\]")


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

    The document-only fallback applies ONLY when the model supplied no page at
    all. It used to be an unconditional ``or``, so "[Source: Guidance.pdf,
    Page: 99]" against a retrieved Guidance.pdf p.14 silently produced a marker
    pointing at page 14 — a citation the reader would check, find plausible,
    and never learn was for a different page. A wrong page is now dropped.
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

        if page is None:
            index = by_doc_page.get((document, None)) or by_doc.get(document)
        else:
            index = by_doc_page.get((document, page))

        if index is None:
            dropped += 1
            # The captured leading space goes with it, so nothing downstream
            # has to tidy up after this.
            return ""
        return f"{match.group('lead')}[{index}]"

    result = LEGACY_CITATION.sub(replace, text)

    if dropped:
        logger.info("Dropped %d citation(s) naming documents outside the retrieved set.", dropped)

    # No global whitespace pass. There used to be one here — collapse every run
    # of two-or-more spaces to one, then close the gap before punctuation — to
    # tidy up after dropped citations. It ran over the WHOLE answer on every
    # turn, whether or not anything had been dropped, and markdown is
    # whitespace-sensitive: a four-space-indented code block became an ordinary
    # paragraph, and nested list indentation flattened.
    #
    # For citations specifically that was self-defeating. Indent this:
    #
    #     rows = data[1]
    #
    # and the collapse turns it into prose, so "[1]" stops being code and
    # starts being a citation — on BOTH sides, since the browser is reading the
    # markdown this function already rewrote. The intersection in
    # bindCitations cannot help, because the damage happened before rendering.
    #
    # The tidying is local now: LEGACY_CITATION captures the space in front of
    # a citation and a dropped one takes it along.
    return result


# Regions where a "[1]" is not a citation. `bindCitations` in citations.js
# refuses to linkify inside `pre, code, a`, so a marker counted here that the
# browser will not turn into a button is a source the reader cannot reach.
#
# This is a best-effort approximation and cannot be anything else: these are
# regexes over markdown SOURCE, while the browser walks the tree `marked`
# actually produced. Indented code blocks, unterminated fences, multi-line
# spans, nested link labels and raw HTML all diverge here, and chasing them
# case by case is how "[1][2]" — the multi-citation form the system prompt
# asks for — briefly got read as reference-link syntax and dropped.
#
# The divergence is made harmless downstream rather than eliminated here:
# bindCitations reports which markers it actually bound and the client shows
# only those, so anything this filter misses costs a passage its place in the
# panel, never the reader a source they cannot check. Keep this filter as an
# accuracy improvement for the `cited` telemetry, not as a correctness
# guarantee — that lives on the client.
#
# Fenced blocks and inline spans cover `pre`/`code`; inline link and image
# syntax covers `a`. These are the forms `marked` reliably converts.
#
# Reference-style links ("[label][1]") are deliberately NOT stripped. `marked`
# only builds one when a matching "[1]: url" definition exists, and a model
# answer never contains link definitions — so the text stays literal and
# bindCitations linkifies the marker. Stripping it would create the mismatch
# this function exists to prevent, in the other direction. It also collided
# with "[1][2]", the multi-citation form BASE_SYSTEM_MESSAGE explicitly asks
# for, silently dropping both markers.
_UNCITABLE = re.compile(
    r"```.*?```"  # fenced code block
    r"|~~~.*?~~~"  # the other fence
    r"|`[^`\n]*`"  # inline code span
    r"|!?\[[^\]\n]*\]\([^)\n]*\)",  # [text](url) / ![alt](src)
    re.S,
)


# Alternation order is the mechanism: a code or link region matches FIRST and
# is handed back untouched, so a marker inside one is never reached by the
# `marker` branch.
_MARKER_OUTSIDE_CODE = re.compile(
    _UNCITABLE.pattern + r"|(?P<marker> ?\[[0-9]{1,2}\])",
    re.S,
)


def strip_citation_markers(text: str) -> str:
    """Remove "[n]" markers, for text that is about to outlive its numbering.

    A citation number means nothing on its own — it is an index into the
    context blocks of ONE request. Every request numbers its own retrieved
    passages from [1], so a marker that survives into a later turn points at
    whatever that later turn happened to retrieve first.

    That is not hypothetical: completed answers go into the conversation
    history and are replayed to the model as prior context. An answer saying
    "submit within 15 days [1]" comes back on turn two, where [1] is now a
    different passage from a different document. A model that restates the
    claim carries the marker with it, and the answer ships a citation
    resolving to unrelated evidence — with a working link and a real passage
    behind it, which is exactly what makes it dangerous.

    Takes any single space in front of the marker with it, so "days [1]."
    becomes "days." rather than "days ." — the same local rule
    ``normalize_legacy_citations`` uses, and for the same reason: no pass over
    the surrounding text, because indentation is markdown.

    Code and links are left verbatim. An answer containing ``data[1]`` in a
    fenced block is replayed to the model as prior context, and quietly
    rewriting it to ``data`` would teach the model to produce broken code.
    Indented code blocks are NOT protected: four spaces inside a list item is
    continuation rather than code, and this cannot tell the two apart without a
    parser. That direction is the safe one to get wrong here — a stray marker
    surviving into history is inert, whereas mangling a list would not be.
    """
    if not text:
        return text
    return _MARKER_OUTSIDE_CODE.sub(
        lambda match: "" if match.group("marker") else match.group(0), text
    )


def _strip_uncitable(text: str) -> str:
    """Blank out code and link regions, preserving offsets elsewhere."""
    return _UNCITABLE.sub(lambda m: " " * len(m.group(0)), text)


@dataclass(frozen=True)
class CitationDiagnostics:
    """Every ``[n]`` marker in an answer, classified.

    ``extract_cited_indices`` used to compute this same breakdown and then
    throw away everything but ``cited`` — ``invalid`` was already being
    counted, just for a single ``logger.info`` line (see below) with no
    caller able to turn it into a rate. This is that breakdown made
    returnable, so a citation-fidelity harness can aggregate it instead of
    scraping log lines.

    Attributes:
        cited: Indices present in ``sources`` that the text actually cited —
            identical to what ``extract_cited_indices`` returns.
        invalid: Indices the text cited that are NOT in ``sources`` —
            hallucinated or prompt-drifted markers, in encounter order with
            duplicates kept (so a rate computed over ``total_markers``
            reflects how often this happens, not just which values occurred).
        total_markers: Every ``[n]`` matched, valid or not — the denominator
            for a hallucinated-marker rate.
    """

    cited: list[int]
    invalid: list[int]
    total_markers: int


def extract_citation_diagnostics(text: str, sources: list[dict[str, Any]]) -> CitationDiagnostics:
    """Classify every ``[n]`` marker in *text* against *sources*.

    The single parsing pass behind both this function and
    ``extract_cited_indices`` — see that function's docstring for the
    membership-vs-range rule, the refusal-detection rationale, and what this
    is and is not evidence of. ``extract_cited_indices`` is a thin wrapper
    around this that returns only ``.cited``, kept for its existing callers
    and the citation-panel contract; anything that also wants the
    hallucinated-marker count should call this directly rather than
    re-deriving it from a second regex pass (as ``scripts/smoke_real.py`` used
    to).

    Args:
        text: The answer, AFTER ``normalize_legacy_citations`` — the same
            string the reader is shown.
        sources: The source payload, as built by ``build_source_payload``.

    Returns:
        A ``CitationDiagnostics`` with empty/zero fields when *text* or
        *sources* is empty.
    """
    if not text or not sources:
        return CitationDiagnostics(cited=[], invalid=[], total_markers=0)

    valid = {source["index"] for source in sources}
    cited: set[int] = set()
    invalid: list[int] = []
    total = 0

    for match in CITATION_MARKER.finditer(_strip_uncitable(text)):
        index = int(match.group(1))
        total += 1
        if index in valid:
            cited.add(index)
        else:
            invalid.append(index)

    if invalid:
        # Prompt drift and hallucinated citations both surface here. This is
        # the telemetry behind the decision to keep showing retrieval
        # candidates when an answer cites nothing.
        logger.info(
            "Ignored %d citation marker(s) outside the source set %s: %s",
            len(invalid),
            sorted(valid),
            sorted(set(invalid)),
        )

    return CitationDiagnostics(cited=sorted(cited), invalid=invalid, total_markers=total)


def extract_cited_indices(text: str, sources: list[dict[str, Any]]) -> list[int]:
    """The source indices *text* actually cites, sorted and deduplicated.

    This is the signal that decides whether an answer gets a source panel. It
    replaces the previous arrangement, where sources were emitted before the
    model was even called and so could not reflect what the answer did with
    them — a refusal shipped with eight source cards attached.

    Deliberately NOT a check for refusal wording. The refusal is an
    instruction the model paraphrases (``BASE_SYSTEM_MESSAGE``), and no Arabic
    refusal string exists anywhere — the Arabic wording is entirely
    model-generated. Counting markers is language-agnostic and needs no list
    of phrases to keep current.

    Validated against the ``index`` values actually present in *sources*, not
    against ``1..len(sources)``: once the payload is filtered to cited
    passages the indices are sparse (1, 3, 7), and a range check would then
    accept ``[2]`` for a passage that is not in the payload.

    A marker outside that set is dropped, matching ``bindCitations`` in
    ``static/js/modules/citations.js``, which leaves an out-of-range marker as
    literal text rather than linking it to nothing. A model citing ``[9]``
    against 8 sources is hallucinating, and counting that as evidence would be
    worse than counting nothing.

    Note what this does and does not prove: that the model *emitted* ``[2]``,
    not that passage 2 supports the claim. It is a citation signal, not a
    grounding one.

    Args:
        text: The answer, AFTER ``normalize_legacy_citations`` — the same
            string the reader is shown. Running this on pre-normalization text
            reports citations the browser never rendered.
        sources: The source payload, as built by ``build_source_payload``.

    Returns:
        Sorted unique indices, or ``[]`` when nothing valid was cited.
    """
    return extract_citation_diagnostics(text, sources).cited
