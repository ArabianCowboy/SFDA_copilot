"""OpenAI request construction and response generation.

Both the blocking and the streaming paths build their prompt through
``_build_messages``, so the two can never drift apart — ``generate_response``
is literally ``"".join(stream_response(...))`` plus the suggestions call.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Iterator, List, Optional, Tuple, cast

import tiktoken
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from web.services.citations import strip_citation_markers
from web.utils.config_loader import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


EASTER_EGG_QUERY = "who is mohammed fouda?"
EASTER_EGG_RESPONSE = (
    "Mohammed Fouda? Oh, you're curious, huh? Alright, lean in... They say he's not just any "
    "pharmacovigilance expert—he's absolutely awesome and has even tamed AI. And between us? "
    "I swear he's a robot from the future, on a secret mission to keep our meds safe!"
)

BASE_SYSTEM_MESSAGE = (
    "You are an AI assistant specializing in Saudi Food and Drug Authority (SFDA) regulations and pharmacovigilance. "
    "Your primary goal is to provide accurate, concise, and relevant information based on the provided context from SFDA documents. "
    "Always prioritize information from the context over your general knowledge. "
    "If the answer is not found within the provided context, clearly state that you cannot answer based on the given information. "
    "Do not make up information or use external knowledge. "
    # Numbered markers rather than prose citations: the context blocks are
    # numbered, so "[2]" maps to a source by array index with no ambiguity and
    # survives being split across streaming token boundaries. Writing out
    # filenames instead would need fuzzy matching against the model's paraphrase.
    "Cite your sources using the bracketed number of the context block the statement came from, "
    "for example [1], or [2][5] when a sentence draws on several. "
    "Place the marker at the end of the sentence it supports. "
    "Use only numbers that appear in the provided context, and never invent a citation number. "
    "Do not write out document names or page numbers in prose — the numbered marker is sufficient. "
    # The citation markers are load-bearing: the API decides whether an answer
    # gets a source panel by counting them, so an uncited claim silently loses
    # its provenance and a cited refusal falsely gains some. Backend validation
    # is still authoritative — these rules only reduce how often it has to
    # correct the model.
    "Every factual claim you draw from the context must carry a citation marker. "
    "If you cannot answer from the context, say so and include NO citation markers at all. "
    "Do not cite a passage merely because it is on a related topic — cite it only if it "
    "supports the specific statement you just made. "
    "Ensure your responses are professional, objective, and directly address the user's query."
)

CATEGORY_SPECIFIC_INSTRUCTIONS = {
    "all": {
        "persona": "As a general SFDA expert, you provide comprehensive information across all regulatory and pharmacovigilance domains.",
        "format": "Provide a well-structured answer, starting with a direct response to the query, followed by supporting details and citations.",
        "focus_areas": "Focus on accuracy, completeness, and clarity, covering both regulatory and pharmacovigilance aspects as relevant.",
        "tone": "informative and authoritative",
    },
    "regulatory": {
        "persona": "As an SFDA Regulatory Affairs specialist, you provide precise guidance on product registration, compliance, and market authorization.",
        "format": "Structure your answer with a clear regulatory stance, detailing relevant guidelines, procedures, and requirements.",
        "focus_areas": "Emphasize legal frameworks, submission processes, and compliance standards.",
        "tone": "formal and precise",
    },
    "pharmacovigilance": {
        "persona": "As an SFDA Pharmacovigilance expert, you focus on drug safety, adverse event reporting, and risk management.",
        "format": "Present information with a focus on safety protocols, reporting mechanisms, and risk assessment strategies.",
        "focus_areas": "Highlight adverse drug reactions (ADRs), safety signals, and pharmacovigilance system requirements.",
        "tone": "cautious and safety-oriented",
    },
    # These two categories are selectable in the UI and have their own corpora,
    # but previously fell through to "all" — so a veterinary question got a
    # generic persona with no species or withdrawal-period framing.
    "veterinary": {
        "persona": "As an SFDA Veterinary Medicines specialist, you advise on veterinary drug registration, residues, and animal safety.",
        "format": "State the requirement, then the species and product scope it applies to, then the supporting detail.",
        "focus_areas": "Emphasize target species, withdrawal periods, maximum residue limits, and veterinary-specific labelling.",
        "tone": "formal and precise",
    },
    "biological": {
        "persona": "As an SFDA Biological Products and Quality Control specialist, you advise on biologics, vaccines, and batch release.",
        "format": "Lead with the quality or regulatory requirement, then the testing and documentation it implies.",
        "focus_areas": "Emphasize batch release, lot testing, cold-chain and stability, comparability, and biosimilarity.",
        "tone": "formal and precise",
    },
}

LANGUAGE_INSTRUCTIONS = {
    "ar": (
        "Respond in Arabic (Modern Standard Arabic), using correct SFDA regulatory terminology. "
        "Keep document names, page numbers and citation markers in their original Latin form."
    ),
}


def _history_without_stale_markers(
    chat_history: Optional[List[dict]],
) -> List[dict]:
    """Strip citation markers from replayed turns before they reach the model.

    Numbering is per-request: `_prepare_context` labels THIS request's passages
    [1], [2], [3], and nothing ties those numbers to the ones in an answer from
    three turns ago. Replaying old answers verbatim hands the model a worked
    example of citing [1] for a claim whose evidence is no longer source 1, and
    a model that restates the claim reuses the marker. The result is a citation
    that resolves — to the wrong document.

    Applied at prompt-assembly rather than when the turn is stored, so the
    conversation store keeps a faithful record of what was actually shown to
    the reader. The stripping belongs at the boundary where the numbering
    changes meaning, which is here.

    Both roles, not just the assistant's: a reader who writes "tell me more
    about [1]" is describing a number this request does not have either.
    """
    if not chat_history:
        return []

    return [
        {**message, "content": strip_citation_markers(message.get("content", ""))}
        for message in chat_history
    ]


class OpenAIHandler:
    """Handles interactions with the OpenAI API for generating responses."""

    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY environment variable not set.")
            raise ValueError("OPENAI_API_KEY environment variable not set.")

        logger.info("Initializing OpenAI client with key starting: %s...", api_key[:5])
        self.client = OpenAI(api_key=api_key)

        self.model = config.get("openai", "model", "gpt-4o-mini")
        self.max_tokens = config.get("openai", "max_tokens")
        self.temperature = config.get("openai", "temperature", 0.2)
        self.max_context_results = config.get("openai", "max_context_results", 5)

        # The citation scheme depends on prompt block [i] and sources[i] being
        # the same passage. They are today (both 8), but if someone lowers
        # max_context_results below the search engine's k, the model would cite
        # numbers for passages it never saw.
        # The section is "search_engine" (config.yaml). This read used to say
        # "search", which no config file has ever defined — so ConfigLoader.get
        # returned the default every time and the guard below was a permanent
        # no-op. It is live now.
        search_k = config.get("search_engine", "k", self.max_context_results)
        if search_k != self.max_context_results:
            logger.error(
                "max_context_results (%s) != search k (%s). Citation indices would point at "
                "passages the model never received. Clamping context to %s.",
                self.max_context_results, search_k, min(search_k, self.max_context_results),
            )
            self.max_context_results = min(search_k, self.max_context_results)

        logger.info(
            "OpenAIHandler initialized with model: %s, max_context_results: %s",
            self.model, self.max_context_results,
        )
        self.tokenizer = tiktoken.encoding_for_model(self.model)

    # ── Prompt construction ────────────────────────────────────────────────

    def _prepare_context(self, search_results: List[dict]) -> str:
        """Format retrieved passages as numbered blocks the model can cite.

        Block ``[i]`` here is ``sources[i]`` in the API payload. Keep them
        aligned — see the guard in __init__.
        """
        if not search_results:
            return "No relevant information found."

        parts = []
        for index, result in enumerate(search_results[: self.max_context_results], start=1):
            header = f"[{index}] Source: {result.get('document', 'Unknown document')}"
            page = result.get("page")
            if page is not None:
                header += f", Page: {page}"
            parts.append(f"{header}\n{result.get('text', '')}")

        return "\n\n".join(parts)

    def _create_system_message(self, category: str, lang: str = "en") -> str:
        info = CATEGORY_SPECIFIC_INSTRUCTIONS.get(
            (category or "all").lower(), CATEGORY_SPECIFIC_INSTRUCTIONS["all"]
        )

        message = (
            f"{info['persona']} {BASE_SYSTEM_MESSAGE}\n"
            f"{info['format']}\n"
            f"Maintain a {info['tone']} at all times.\n"
        )
        if info.get("focus_areas"):
            message += f"{info['focus_areas']}\n"

        language_instruction = LANGUAGE_INSTRUCTIONS.get((lang or "en").lower())
        if language_instruction:
            message += f"{language_instruction}\n"

        return message

    def _build_messages(
        self,
        query: str,
        search_results: List[dict],
        category: str = "all",
        chat_history: Optional[List[dict]] = None,
        lang: str = "en",
    ) -> List[dict]:
        """Single source of truth for the prompt, shared by both paths."""
        system_message = self._create_system_message(category, lang)
        context = self._prepare_context(search_results)
        user_message = f"Query: {query}\n\nContext:\n{context}"

        history = _history_without_stale_markers(chat_history)

        messages: List[dict] = [{"role": "system", "content": system_message}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        self._log_token_counts(system_message, history, user_message)
        return messages

    def _log_token_counts(self, system_message: str, chat_history: List[dict], user_message: str) -> None:
        system_tokens = len(self.tokenizer.encode(system_message))
        history_tokens = sum(len(self.tokenizer.encode(m["content"])) for m in chat_history)
        query_tokens = len(self.tokenizer.encode(user_message))

        logger.info("Token counts for current request:")
        logger.info("  System Message Tokens: %d", system_tokens)
        logger.info("  Chat History Tokens: %d", history_tokens)
        logger.info("  Current Query + Context Tokens: %d", query_tokens)
        logger.info("  Total Input Tokens: %d", system_tokens + history_tokens + query_tokens)
        logger.info("  Max Output Tokens (configured): %s", self.max_tokens)

    # ── Generation ─────────────────────────────────────────────────────────

    def stream_response(
        self,
        query: str,
        search_results: List[dict],
        category: str = "all",
        chat_history: Optional[List[dict]] = None,
        lang: str = "en",
    ) -> Iterator[str]:
        """Yield answer tokens as they arrive from the model."""
        if query.lower().strip() == EASTER_EGG_QUERY:
            yield EASTER_EGG_RESPONSE
            return

        messages = self._build_messages(query, search_results, category, chat_history, lang)

        # The context manager matters: on client disconnect the caller's
        # generator gets GeneratorExit, and closing the stream here releases
        # the upstream HTTP connection instead of leaking it.
        with self.client.chat.completions.create(
            model=self.model,
            messages=cast(List[ChatCompletionMessageParam], messages),
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            stream=True,
        ) as stream:
            for chunk in stream:
                if not chunk.choices:  # usage-only final chunk
                    continue
                content = chunk.choices[0].delta.content
                if content:
                    yield content

    def generate_response(
        self,
        query: str,
        search_results: List[dict],
        category: str = "all",
        chat_history: Optional[List[dict]] = None,
        lang: str = "en",
    ) -> Tuple[str, List[str]]:
        """Blocking variant: collect the stream, then generate follow-ups."""
        if query.lower().strip() == EASTER_EGG_QUERY:
            return EASTER_EGG_RESPONSE, []

        try:
            answer = "".join(
                self.stream_response(query, search_results, category, chat_history, lang)
            ).strip()
        except Exception:
            logger.error("Error generating OpenAI response", exc_info=True)
            return "I'm sorry, I encountered an error while generating a response. Please try again.", []

        if answer:
            logger.info("  Actual Output Tokens: %d", len(self.tokenizer.encode(answer)))

        return answer, self.generate_suggestions(query, answer, lang)

    def generate_suggestions(
        self, original_query: str, assistant_response: str, lang: str = "en"
    ) -> List[str]:
        """Generate 2-3 follow-up questions from the exchange."""
        language_note = (
            " Write the questions in Arabic." if (lang or "en").lower() == "ar" else ""
        )
        prompt = (
            "You are an AI assistant. Based on the user's original query and the assistant's response, "
            "generate 2-3 concise and relevant follow-up questions that a user might ask next. "
            "These questions should directly relate to the previous conversation and encourage further "
            "exploration of the topic. "
            f"Provide the questions as a JSON array of strings.{language_note}"
            f"\n\nOriginal Query: {original_query}"
            # Markers stripped: this prompt carries no numbered context, so a
            # "[1]" here is noise the model can copy into a suggested question,
            # where it would render as a citation the reader can neither
            # resolve nor click.
            f"\nAssistant's Response: {strip_citation_markers(assistant_response)}"
            "\n\nSuggested Questions:"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=cast(List[ChatCompletionMessageParam], [{"role": "user", "content": prompt}]),
                max_tokens=100,
                temperature=0.5,
            )
            content = response.choices[0].message.content
            if not content:
                return []

            fenced = re.search(r"```(?:json)?\n(.*)\n```", content, re.DOTALL)
            payload = fenced.group(1) if fenced else content

            try:
                suggestions = json.loads(payload)
            except json.JSONDecodeError:
                logger.warning("Suggestions were not valid JSON, falling back to comma split.")
                return [s.strip() for s in content.split(",") if s.strip()][:3]

            if isinstance(suggestions, list) and all(isinstance(s, str) for s in suggestions):
                return suggestions[:3]

            logger.warning("Suggestions JSON was not a list of strings: %r", content)
            return []

        except Exception:
            logger.error("Error generating suggested questions", exc_info=True)
            return []
