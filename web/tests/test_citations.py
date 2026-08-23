"""Tests for the citation payload and legacy-citation normalisation.

The numpy coercion tests are the important ones: ResultCombiner builds
SearchResult from pandas cells and numpy index arrays, so these fields arrive
as numpy scalars in production even though the dataclass annotates them as
plain Python types. Un-coerced, jsonify raises and the endpoint 500s.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from web.services.citations import (
    CitationDiagnostics,
    build_source_payload,
    extract_citation_diagnostics,
    extract_cited_indices,
    normalize_legacy_citations,
    strip_citation_markers,
)
from web.services.result_combiner import SearchResult


def result(**overrides):
    defaults = {
        "text": "Applications must be submitted within fifteen days of approval.",
        "score": 0.7143,
        "document": "Guidance_for_Submission.pdf",
        "category": "regulatory",
        "page": 14,
        "chunk_id": "guidance_p14_2",
        "metadata": {"semantic_score": 0.6312, "lexical_score": 0.7975},
    }
    defaults.update(overrides)
    return SearchResult(**defaults)


# ── Payload shape ───────────────────────────────────────────────────────────


def test_index_is_one_based_and_sequential():
    payload = build_source_payload([result(), result(), result()])
    assert [s["index"] for s in payload] == [1, 2, 3]


def test_payload_carries_the_fields_the_ui_needs():
    (source,) = build_source_payload([result()])
    assert source["document"] == "Guidance_for_Submission.pdf"
    assert source["page"] == 14
    assert source["category"] == "regulatory"
    assert source["score"] == 0.7143
    assert source["semantic_score"] == 0.6312
    assert source["lexical_score"] == 0.7975
    assert source["chunk_id"] == "guidance_p14_2"
    assert source["snippet"].startswith("Applications must be submitted")


def test_limit_keeps_sources_aligned_with_prompt_blocks():
    payload = build_source_payload([result() for _ in range(8)], limit=3)
    assert [s["index"] for s in payload] == [1, 2, 3]


# ── numpy / NaN coercion ────────────────────────────────────────────────────


def test_numpy_scalars_are_coerced_to_json_native_types():
    payload = build_source_payload(
        [
            result(
                page=np.int64(14),
                score=np.float32(0.5),
                metadata={"semantic_score": np.float64(0.31), "lexical_score": np.float32(0.62)},
            )
        ]
    )
    json.dumps(payload)  # would raise TypeError on numpy scalars

    (source,) = payload
    assert type(source["page"]) is int
    assert type(source["score"]) is float
    assert type(source["semantic_score"]) is float


def test_nan_becomes_none_rather_than_a_nan_literal():
    """json.dumps emits bare NaN for float('nan'), which is invalid JSON."""
    payload = build_source_payload([result(page=float("nan"), score=float("nan"))])
    (source,) = payload
    assert source["page"] is None
    assert source["score"] is None
    assert "NaN" not in json.dumps(payload)


def test_missing_metadata_scores_do_not_raise():
    (source,) = build_source_payload([result(metadata={})])
    assert source["semantic_score"] is None
    assert source["lexical_score"] is None


def test_missing_document_falls_back_to_a_label():
    (source,) = build_source_payload([result(document="")])
    assert source["document"] == "Unknown document"


def test_snippet_is_truncated_and_whitespace_collapsed():
    (source,) = build_source_payload([result(text="word  \n\n  spaced " + "x" * 500)])
    assert "\n" not in source["snippet"]
    assert source["snippet"].startswith("word spaced")
    assert len(source["snippet"]) <= 322


# ── Legacy citation normalisation ───────────────────────────────────────────


@pytest.fixture
def sources():
    return build_source_payload(
        [
            result(document="A.pdf", page=3),
            result(document="B.pdf", page=14),
        ]
    )


def test_prose_citation_becomes_a_numbered_marker(sources):
    text = "Submit within 15 days [Source: B.pdf, Page: 14]."
    assert normalize_legacy_citations(text, sources) == "Submit within 15 days [2]."


def test_matching_is_case_insensitive(sources):
    text = "See [source: a.pdf, page: 3]."
    assert normalize_legacy_citations(text, sources) == "See [1]."


def test_document_without_page_still_resolves(sources):
    assert normalize_legacy_citations("Text [Source: A.pdf].", sources) == "Text [1]."


def test_citation_naming_an_unretrieved_document_is_dropped(sources):
    """Better to lose the citation than to point it at the wrong source."""
    out = normalize_legacy_citations("Claim [Source: Hallucinated.pdf, Page: 9].", sources)
    assert "Hallucinated" not in out
    assert "[" not in out
    assert out == "Claim."


def test_existing_numbered_markers_are_untouched(sources):
    text = "Already numbered [1] and [2]."
    assert normalize_legacy_citations(text, sources) == text


def test_empty_sources_returns_text_unchanged():
    text = "Nothing [Source: A.pdf] here."
    assert normalize_legacy_citations(text, []) == text


def test_indented_code_survives_normalisation(sources):
    """Markdown is whitespace-sensitive; normalisation must not rewrite it.

    A global "collapse runs of spaces" pass used to run over every answer,
    whether or not a citation had been dropped. Four-space indentation is what
    makes this a code block, and flattening it turns the block into prose — at
    which point "[1]" stops being code and becomes a citation, on both sides,
    because the browser parses the markdown this function already rewrote.
    """
    text = "Example:\n\n    rows = data[1]\n    other = data[2]\n\nDone."
    assert normalize_legacy_citations(text, sources) == text

    # Note what is NOT asserted: extract_cited_indices still counts these two.
    # It matches regexes against markdown source and cannot tell an indented
    # code block from list continuation without a parser, and over-stripping
    # would silently drop real citations out of the list-heavy answers this
    # corpus produces. Harmless because bindCitations will not bind a marker
    # inside <pre>, and the client shows only what it bound — see the note on
    # _UNCITABLE. What matters here is that the markdown reached the browser
    # intact, so it still renders as code.
    assert "    rows = data[1]" in normalize_legacy_citations(text, sources)


def test_nested_list_indentation_survives_normalisation(sources):
    text = "- Parent\n  - Child\n    - Grandchild\n"
    assert normalize_legacy_citations(text, sources) == text


def test_a_dropped_citation_takes_its_own_spacing(sources):
    """The tidying is local, so it needs no pass over the rest of the text."""
    assert (
        normalize_legacy_citations("A claim [Source: Nope.pdf], and more.", sources)
        == "A claim, and more."
    )


def test_a_wrong_page_is_dropped_not_remapped(sources):
    """The document-only fallback used to be unconditional.

    "[Source: A.pdf, Page: 99]" against a retrieved A.pdf p.3 produced "[1]" —
    a citation the reader would open, find plausible, and never learn was for
    a different page. The fallback now applies only when the model gave no
    page at all.
    """
    out = normalize_legacy_citations("Claim [Source: A.pdf, Page: 99].", sources)
    assert out == "Claim."


# ── Which sources the answer actually cited ─────────────────────────────────


def test_markers_are_deduplicated_and_sorted(sources):
    assert extract_cited_indices("A [2]. B [1]. C [2] again.", sources) == [1, 2]


def test_a_refusal_cites_nothing(sources):
    """The reported bug, at its root.

    No prose is matched to reach this answer — the absence of markers is the
    whole signal, which is why it works identically in Arabic.
    """
    assert extract_cited_indices("I cannot answer based on the given information.", sources) == []
    assert extract_cited_indices("لا يمكنني الإجابة بناءً على المعلومات المتاحة.", sources) == []


def test_out_of_range_markers_are_ignored(sources):
    """[9] against 2 sources is a hallucination, not a citation."""
    assert extract_cited_indices("Claim [9].", sources) == []
    assert extract_cited_indices("Real [1] and invented [7].", sources) == [1]


def test_validation_is_by_membership_not_range():
    """Filtering makes indices sparse, so a `n <= len(sources)` test is wrong.

    With sources numbered 1 and 3, a range check would accept [2] — which is
    a passage the payload does not carry and the reader cannot open.
    """
    payload = build_source_payload(
        [
            result(document="A.pdf", page=3),
            result(document="B.pdf", page=14),
            result(document="C.pdf", page=20),
        ]
    )
    sparse = [payload[0], payload[2]]  # indices 1 and 3

    assert extract_cited_indices("Cites [1] and [3].", sparse) == [1, 3]
    assert extract_cited_indices("Cites [2].", sparse) == []


def test_three_digit_brackets_are_not_markers(sources):
    """Mirrors CITE_SCAN in citations.js, which is also \\d{1,2}."""
    assert extract_cited_indices("Reference [123] here.", sources) == []


def test_markers_survive_adjacent_punctuation(sources):
    assert extract_cited_indices("End of sentence [1].", sources) == [1]
    assert extract_cited_indices("Several [1][2] together.", sources) == [1, 2]


def test_empty_inputs_cite_nothing(sources):
    assert extract_cited_indices("", sources) == []
    assert extract_cited_indices("Text [1].", []) == []


# ── CitationDiagnostics — the split extract_cited_indices used to discard ──
#
# extract_cited_indices already computed cited/invalid/total internally and
# threw away everything but cited (invalid only ever reached a log line).
# extract_citation_diagnostics is that same single parsing pass, returning the
# full breakdown a hallucination-rate metric needs. extract_cited_indices is
# now a thin wrapper over it — these tests pin the wrapper relationship as
# well as the new function's own shape.


def test_diagnostics_reports_invalid_markers_separately_from_cited(sources):
    diagnostics = extract_citation_diagnostics("Real [1] and invented [7].", sources)
    assert diagnostics.cited == [1]
    assert diagnostics.invalid == [7]
    assert diagnostics.total_markers == 2


def test_diagnostics_counts_every_marker_including_duplicates(sources):
    """total_markers is the denominator for a rate, so duplicates must count."""
    diagnostics = extract_citation_diagnostics("A [9]. B [9]. C [1].", sources)
    assert diagnostics.cited == [1]
    assert diagnostics.invalid == [9, 9]
    assert diagnostics.total_markers == 3


def test_diagnostics_on_a_clean_answer_has_no_invalid_markers(sources):
    diagnostics = extract_citation_diagnostics("A [2]. B [1]. C [2] again.", sources)
    assert diagnostics.cited == [1, 2]
    assert diagnostics.invalid == []
    assert diagnostics.total_markers == 3


def test_diagnostics_on_empty_input_is_all_zero():
    assert extract_citation_diagnostics("", []) == CitationDiagnostics(
        cited=[], invalid=[], total_markers=0
    )


def test_extract_cited_indices_matches_diagnostics_cited(sources):
    """The wrapper's contract: identical to .cited, nothing more."""
    text = "Real [1] and invented [7]."
    assert extract_cited_indices(text, sources) == extract_citation_diagnostics(text, sources).cited


# ── Where a [n] is not a citation ───────────────────────────────────────────
#
# bindCitations in citations.js refuses to linkify inside `pre, code, a`. If
# the server counts a marker the browser will not turn into a button, the
# answer gets a source panel for a citation the reader cannot click.


def test_markers_inside_an_inline_code_span_are_not_citations(sources):
    assert extract_cited_indices("Use the `list[1]` accessor.", sources) == []


def test_markers_inside_a_fenced_code_block_are_not_citations(sources):
    text = "Example:\n\n```python\nrows = data[1]\nother = data[2]\n```\n\nDone."
    assert extract_cited_indices(text, sources) == []


def test_a_marker_outside_code_still_counts(sources):
    text = "Submit the form [1]. Example: `data[2]` is not a citation."
    assert extract_cited_indices(text, sources) == [1]


def test_markdown_link_targets_are_not_citations(sources):
    assert extract_cited_indices("See [the guidance](https://example.com/1).", sources) == []


def test_non_ascii_digits_are_not_markers(sources):
    """Python's \\d matches every Unicode decimal digit; JavaScript's does not.

    "[١]" in Arabic-Indic digits used to match here — int() parses it as 1 —
    while the browser saw no marker at all, so the answer gained a source with
    nothing on screen pointing at it. The Arabic language instruction asks the
    model to keep markers Latin, which is exactly the kind of rule this
    codebase does not rely on the model obeying.
    """
    assert extract_cited_indices("مصدر [١].", sources) == []
    assert extract_cited_indices("Source [۲].", sources) == []
    # The Latin form still works in an otherwise Arabic answer.
    assert extract_cited_indices("يجب تقديم الطلب [1].", sources) == [1]


def test_adjacent_markers_are_not_mistaken_for_a_reference_link(sources):
    """ "[1][2]" is the multi-citation form the system prompt asks for.

    An earlier version of the uncitable filter treated it as markdown
    reference-link syntax and dropped BOTH markers — so a sentence drawing on
    two passages lost its entire provenance. `marked` only builds a reference
    link when a "[2]: url" definition exists, which a model answer never
    contains, so the text stays literal and the browser linkifies both.
    """
    assert extract_cited_indices("Both apply [1][2].", sources) == [1, 2]


# ── Markers must not outlive their numbering ────────────────────────────────
#
# "[1]" is an index into ONE request's context blocks. Every request numbers
# its own passages from [1], so a marker replayed into a later turn points at
# whatever that turn happened to retrieve first.


def test_markers_are_stripped_with_their_spacing():
    assert (
        strip_citation_markers("Applications must be submitted within 15 days [1].")
        == "Applications must be submitted within 15 days."
    )


def test_every_marker_in_a_turn_is_stripped():
    assert strip_citation_markers("First [1]. Second [2][5]. Third [8].") == "First. Second. Third."


def test_stripping_leaves_ordinary_brackets_alone():
    text = "See annex [A] and the range [1-5] and note [123]."
    assert strip_citation_markers(text) == text


def test_stripping_leaves_code_verbatim():
    """History is replayed to the model, so mangling code teaches it to.

    Fenced blocks and inline spans are unambiguous and protected. Indented
    blocks are not — four spaces inside a list item is continuation, not code
    — and that is the safe direction to be wrong in here.
    """
    fenced = "Use:\n\n```python\nrows = data[1]\n```\n\nSubmit within 15 days [1]."
    assert strip_citation_markers(fenced) == (
        "Use:\n\n```python\nrows = data[1]\n```\n\nSubmit within 15 days."
    )

    inline = "Call `data[1]` to read it [2]."
    assert strip_citation_markers(inline) == "Call `data[1]` to read it."


def test_stripping_handles_empty_input():
    assert strip_citation_markers("") == ""
    assert strip_citation_markers(None) is None


def test_prompt_assembly_strips_markers_from_replayed_turns():
    """The seam that matters: where history becomes a prompt.

    Asserted against the real _build_messages rather than through a route,
    because the routes hand history to the handler untouched — the stripping
    belongs at prompt assembly, and a route test with a mocked handler would
    pass without the fix ever running.

    Built with __new__ to skip __init__, which wants an API key and a network
    round-trip for the tokenizer; _build_messages needs neither.
    """
    from web.services.openai_app import OpenAIHandler

    handler = OpenAIHandler.__new__(OpenAIHandler)
    handler.max_context_results = 8
    handler._log_token_counts = lambda *args, **kwargs: None

    messages = handler._build_messages(
        "What about variations?",
        [{"text": "passage", "document": "A.pdf", "category": "regulatory", "page": 1}],
        chat_history=[
            {"role": "user", "content": "What are the requirements?"},
            {"role": "assistant", "content": "Submit within 15 days [1]. See also [2]."},
        ],
    )

    replayed = [m["content"] for m in messages if m["role"] == "assistant"]
    assert replayed == ["Submit within 15 days. See also."]

    # The current turn's own context blocks keep their numbering — that is the
    # numbering the answer is supposed to cite against.
    assert "[1] Source: A.pdf" in messages[-1]["content"]
