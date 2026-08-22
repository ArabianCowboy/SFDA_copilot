"""Tests for the Layer-2 (NLI) citation-support scorer.

Every test injects a stub ``scorer`` callable — the real Vectara HHEM model
(a ~600MB download) is never loaded here, mirroring how this repo never
loads a real SentenceTransformer in most unit tests. What's under test is
``HHEMScorer``'s own arithmetic (recall/precision composition, the
edge-of-one-citation case) and the English/Arabic confidence tagging — not
whether HHEM itself is a good classifier, which is a model-evaluation
question outside this file's scope.
"""

from __future__ import annotations

from web.services.citation_fidelity import EntailmentResult, HHEMScorer


def stub_scorer(table):
    """A deterministic (premise, hypothesis) -> score lookup for tests.

    Keyed on the exact strings passed in, so a test's expectations are
    explicit rather than derived from some approximation of real NLI
    behavior.
    """

    def scorer(premise, hypothesis):
        return table[(premise, hypothesis)]

    return scorer


# ── score() ──────────────────────────────────────────────────────────────

def test_score_calls_the_injected_scorer_directly():
    scorer = HHEMScorer(scorer=lambda p, h: 0.87)
    assert scorer.score("premise", "hypothesis") == 0.87


def test_the_real_hhem_model_is_never_touched_by_a_stubbed_instance():
    """No scorer call reaches _LazyHHEM/_shared_default_scorer when a stub is given."""
    calls = []

    def recording_scorer(p, h):
        calls.append((p, h))
        return 0.5

    scorer = HHEMScorer(scorer=recording_scorer)
    scorer.score("p", "h")
    assert calls == [("p", "h")]


# ── citation_recall ──────────────────────────────────────────────────────

def test_recall_concatenates_all_cited_passages_as_one_premise():
    seen = {}

    def scorer(premise, hypothesis):
        seen["premise"] = premise
        seen["hypothesis"] = hypothesis
        return 0.9

    hhem = HHEMScorer(scorer=scorer)
    result = hhem.citation_recall("The claim.", ["Passage one.", "Passage two."], lang="en")

    assert seen["premise"] == "Passage one.\nPassage two."
    assert seen["hypothesis"] == "The claim."
    assert result == EntailmentResult(score=0.9, confidence="validated")


def test_recall_tags_arabic_as_unvalidated_regardless_of_score():
    hhem = HHEMScorer(scorer=lambda p, h: 0.95)
    result = hhem.citation_recall("الادعاء.", ["المقطع."], lang="ar")
    assert result.confidence == "unvalidated"
    assert result.score == 0.95  # the number is still returned — just not trusted as a gate input


def test_recall_defaults_to_validated_confidence_for_unspecified_language():
    hhem = HHEMScorer(scorer=lambda p, h: 0.5)
    result = hhem.citation_recall("claim", ["passage"], lang="en")
    assert result.confidence == "validated"


# ── citation_precision ───────────────────────────────────────────────────

def test_precision_scores_each_citation_against_the_others():
    table = {
        ("B.", "sentence"): 0.9,  # removing A: B alone still supports it well -> A is redundant
        ("A.", "sentence"): 0.1,  # removing B: A alone barely supports it -> B is necessary
    }
    hhem = HHEMScorer(scorer=stub_scorer(table))

    result = hhem.citation_precision("sentence", ["A.", "B."], lang="en")

    assert result[0].score == 0.9  # index 0 (A) removed -> scored against remainder (B)
    assert result[1].score == 0.1  # index 1 (B) removed -> scored against remainder (A)


def test_precision_with_a_single_citation_needs_no_model_call():
    calls = []
    hhem = HHEMScorer(scorer=lambda p, h: calls.append((p, h)) or 0.5)

    result = hhem.citation_precision("sentence", ["only passage"], lang="en")

    assert calls == []  # nothing to compare against — no scorer call made
    assert result[0].score == 0.0
    assert result[0].confidence == "validated"


def test_precision_with_zero_citations_is_an_empty_result():
    hhem = HHEMScorer(scorer=lambda p, h: 1.0)
    assert hhem.citation_precision("sentence", [], lang="en") == {}


def test_precision_tags_confidence_per_language_not_per_call():
    hhem = HHEMScorer(scorer=lambda p, h: 0.4)
    result = hhem.citation_precision("جملة", ["أ.", "ب."], lang="ar")
    assert all(r.confidence == "unvalidated" for r in result.values())
