"""Layer 2: NLI-based citation-support scoring (Vectara HHEM).

This is the module that actually touches grounding — Layer 1
(``citation_eval_metrics.py``) only proves a marker was emitted, never that
the passage it points to supports the sentence. ``HHEMScorer`` answers that
question with a small, purpose-built factual-consistency classifier instead
of an LLM judge: cheap and deterministic enough to run at eval-set scale,
unlike Layer 3 (a human, see ``docs/citation-eval-judge-protocol.md``).

**English only.** ``vectara/hallucination_evaluation_model``'s (HHEM-2.1-Open)
public model card documents it as an English-language model — Arabic
cross-lingual support is an advantage Vectara claims for the commercial
HHEM-2.3, not this open checkpoint. An earlier draft of this harness assumed
direct Arabic→Arabic scoring with no evidence behind that assumption; an
adversarial review of the design plan caught it before it shipped. Every
result carries a ``confidence`` of ``"validated"`` (English) or
``"unvalidated"`` (anything else) for exactly that reason — a caller must
never silently average an unvalidated score in with a validated one, and
``scripts/eval_citations.py`` does not gate on this module's Arabic output at
all; it's reported for visibility only until an Arabic-capable, actually
evidenced NLI scorer is identified and calibrated against manually labelled
Arabic claims.

**Never imported from the request path.** ``web/api/app.py`` and
``web/services/openai_app.py`` must not import this module — the real model
is a ~600MB download on first use and real per-call CPU inference cost,
neither of which a reader-facing request should pay for a metric only the
eval harness needs. Only ``scripts/eval_citations.py`` imports it.

**The real model never loads in tests.** Every ``HHEMScorer`` method routes
through an injectable scorer callable; the default lazily constructs the
real HHEM pipeline on first actual use, following the same
local-cache-first-then-download shape as
``web/utils/local_embedding_client.py``. ``web/tests/test_citation_fidelity.py``
always injects a stub.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

HHEM_MODEL_ID = "vectara/hallucination_evaluation_model"

# (premise, hypothesis) -> factual-consistency probability in [0, 1].
Scorer = Callable[[str, str], float]


class _LazyHHEM:
    """Loads the real HHEM model on first call, never at import time.

    Mirrors ``local_embedding_client.py``'s ``local_files_only=True`` ->
    ``LocalEntryNotFoundError`` -> fallback-download pattern: try the cached
    copy first, and only reach the network when it's genuinely missing.
    """

    def __init__(self) -> None:
        self._model: Any | None = None

    def __call__(self, premise: str, hypothesis: str) -> float:
        if self._model is None:
            self._model = self._load()
        # HHEM's predict() takes a list of (premise, hypothesis) pairs and
        # returns one factual-consistency probability per pair.
        return float(self._model.predict([(premise, hypothesis)])[0])

    @staticmethod
    def _load():
        from huggingface_hub.utils import LocalEntryNotFoundError
        from transformers import AutoModelForSequenceClassification

        logger.info(
            "Loading %s (first use — a ~600MB download if not already cached).", HHEM_MODEL_ID
        )
        try:
            return AutoModelForSequenceClassification.from_pretrained(
                HHEM_MODEL_ID,
                trust_remote_code=True,
                local_files_only=True,
            )
        except LocalEntryNotFoundError:
            logger.warning("%s is not cached locally; downloading now.", HHEM_MODEL_ID)
            return AutoModelForSequenceClassification.from_pretrained(
                HHEM_MODEL_ID,
                trust_remote_code=True,
            )


@dataclass(frozen=True)
class EntailmentResult:
    """One (premise, hypothesis) score, honestly labelled about its confidence.

    ``confidence`` is ``"validated"`` only for English — see the module
    docstring for why every other language, Arabic included, comes back
    ``"unvalidated"`` regardless of the numeric score.
    """

    score: float
    confidence: str  # "validated" | "unvalidated"


def _confidence(lang: str) -> str:
    return "validated" if (lang or "en").lower() == "en" else "unvalidated"


class HHEMScorer:
    """ALCE-style citation recall/precision, backed by HHEM (or a test stub).

    Args:
        scorer: Replaces the real, lazily-downloaded HHEM model when given —
            every unit test passes one. Defaults to a shared lazy singleton
            so the model, once loaded, is reused across calls within a run
            rather than reloaded per probe.
    """

    def __init__(self, scorer: Scorer | None = None) -> None:
        self._scorer = scorer or _shared_default_scorer()

    def score(self, premise: str, hypothesis: str) -> float:
        """Raw factual-consistency probability that *premise* entails *hypothesis*."""
        return float(self._scorer(premise, hypothesis))

    def citation_recall(
        self, sentence: str, cited_passages: list[str], *, lang: str
    ) -> EntailmentResult:
        """Does the CONCATENATION of every cited passage entail *sentence*?

        ALCE's citation-recall definition: "is every claim in the answer
        actually backed by what's cited" — a sentence citing nothing has no
        recall claim to make, so callers should exclude uncited sentences
        before calling this (mirrors ``citation_eval_metrics.marker_coverage``'s
        ``None``-for-nothing-to-measure handling, just enforced by the caller
        here rather than by this method, since "nothing cited" is the
        caller's ``cited_passages == []`` to notice).
        """
        premise = "\n".join(cited_passages)
        return EntailmentResult(score=self.score(premise, sentence), confidence=_confidence(lang))

    def citation_precision(
        self, sentence: str, cited_passages: list[str], *, lang: str
    ) -> dict[int, EntailmentResult]:
        """Per-citation necessity: would the sentence still be entailed without it?

        ALCE's citation-precision check, one result per index into
        *cited_passages* (0-based — the caller maps this back to ``[n]``
        marker numbers, which this module has no notion of). For index
        ``i``: score the sentence against every OTHER cited passage. A LOW
        score there means passage ``i`` was doing real work — removing it
        broke support, so it's a precise, non-redundant citation. A HIGH
        score means the remaining passages already supported the sentence on
        their own — passage ``i`` was redundant, ALCE's "citation-stuffing"
        signal, worth flagging even though it isn't wrong the way an invalid
        marker is.

        A sentence cited by exactly one passage has nothing to compare
        against; that passage is trivially non-redundant by definition. Its
        "support from the remainder" score is fixed at 0.0 (no other passage
        to lean on at all) without a model call — consistent with the rest
        of this method's scale, where LOW means necessary.
        """
        results: dict[int, EntailmentResult] = {}
        for index in range(len(cited_passages)):
            remainder = cited_passages[:index] + cited_passages[index + 1 :]
            if not remainder:
                results[index] = EntailmentResult(score=0.0, confidence=_confidence(lang))
                continue
            # Deliberately NOT self.citation_recall(...) — that would create
            # a second EntailmentResult with the SAME confidence tag for a
            # conceptually different question (support-without-this-one, not
            # support-from-everything), so it's inlined instead of reused,
            # to keep the "what does this score mean" question answerable
            # from this method alone.
            premise = "\n".join(remainder)
            results[index] = EntailmentResult(
                score=self.score(premise, sentence), confidence=_confidence(lang)
            )
        return results


_shared_lazy_hhem: _LazyHHEM | None = None


def _shared_default_scorer() -> _LazyHHEM:
    """One lazy HHEM instance shared across HHEMScorer() calls in a process.

    Constructing HHEMScorer() repeatedly (once per probe, say) must not
    re-download or re-load the ~600MB model each time — the singleton is
    created on first need and then reused, the same "loaded lazily, kept
    once loaded" shape ``ImprovedSearchEngine``'s own embedding client uses.
    """
    global _shared_lazy_hhem
    if _shared_lazy_hhem is None:
        _shared_lazy_hhem = _LazyHHEM()
    return _shared_lazy_hhem
