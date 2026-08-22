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
from typing import Any, Dict, Iterator, List, Optional, Tuple, cast

import tiktoken
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from web.services.citations import strip_citation_markers
from web.services.settings_service import model_spec
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
    # Those three rules are about the DOCUMENTS, but nothing said so, and the
    # prior turns arrive in the same prompt as ordinary messages with no
    # standing of their own. Read literally — which is how it was read — a
    # reader asking "what did I ask first?" is asking something the context
    # does not contain, so the honest response was a refusal, and the observed
    # one was worse: with history separately broken, the model had nothing to
    # refuse from and answered that the first question was the question being
    # asked right then.
    #
    # Repairing the store is therefore only half of it. History that reaches
    # the prompt but which the prompt forbids using is history the reader
    # still cannot get an answer out of. The carve-out is deliberately narrow:
    # it licenses answering ABOUT the conversation, never answering a
    # regulatory question from memory.
    "The conversation so far is also yours to draw on. A question about this conversation itself — "
    "what was asked earlier, what you already answered, or a request to revise, shorten or expand a "
    "previous answer — is answered from the conversation, and the rule about the provided context "
    "does not apply to it. Answer it directly rather than refusing. "
    "Such an answer carries no citation markers, because it comes from the conversation and not from "
    "a document. This is not licence to answer a regulatory question from memory: any claim about "
    "SFDA regulation still comes from the provided context or not at all. "
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

    def __init__(self, settings: Optional[Dict[str, Any]] = None) -> None:
        """Build a handler, optionally from runtime settings rather than the file.

        ``settings`` overrides the config.yaml values for this instance only.
        It is how the console changes the model: a *complete replacement*
        handler is constructed and swapped into ``app.config``, rather than the
        live one being mutated.

        That choice is the whole safety argument. Mutating four attributes on a
        shared instance can be observed half-applied by one of the eight
        threads — a new model against an old token ceiling — and the tokenizer
        below is bound to the model at construction, so a naive
        ``handler.model = x`` leaves the two disagreeing with nothing to say so.
        A handler is either wholly old or wholly new, and each request captures
        one reference at the top of the view and keeps it for its lifetime.

        ``settings["base_url"]``, ``settings["api_key_env"]`` and
        ``settings["model_contract"]`` exist ONLY for the citation-fidelity
        harness (``scripts/eval_citations.py``) to call a non-OpenAI provider
        through this same, real prompt-assembly path rather than a
        reimplementation that risks drifting from what production actually
        sends. No production caller sets any of the three — ``config.yaml``'s
        ``allowed_models`` has no such fields and ``settings_service.py``'s
        ``GENERATION_KEYS`` does not accept them from the console — so for
        every existing caller this constructor behaves exactly as it did
        before these three were added.
        """
        # Settings normalized BEFORE anything below reads from it — including
        # the client construction two lines down. An earlier draft of this
        # constructor built the client first and normalized `settings` after,
        # which meant a `base_url` read here would call `.get()` on `None`
        # whenever `OpenAIHandler()` is invoked with no settings argument —
        # i.e. every normal production construction (`app.py`'s
        # `OpenAIHandler()` at startup, `scripts/smoke_real.py`). An
        # adversarial review of this change caught it before it shipped.
        settings = settings or {}

        # `api_key_env` lets the harness point this handler at a
        # provider-specific key (e.g. `DEEPSEEK_API_KEY`) without touching
        # `OPENAI_API_KEY`. Absent — the only case any production caller
        # exercises — resolves to today's exact env var.
        api_key_env = settings.get("api_key_env") or "OPENAI_API_KEY"
        api_key = os.getenv(api_key_env)
        if not api_key:
            logger.error("%s environment variable not set.", api_key_env)
            raise ValueError(f"{api_key_env} environment variable not set.")

        logger.info("Initializing OpenAI client with key starting: %s...", api_key[:5])
        # `base_url=None` is the OpenAI SDK's own default (its public
        # endpoint), so an absent override is indistinguishable from today's
        # behavior at the request level, not just at the settings level.
        self.client = OpenAI(api_key=api_key, base_url=settings.get("base_url"))

        # The harness-only override for _request_kwargs's model-parameter
        # lookup — see that method for what it replaces and why. Kept as a
        # single attribute set at construction, same as everything else here,
        # rather than read from `settings` again later: a handler is either
        # wholly old or wholly new, and this field is part of that contract.
        self._model_contract_override = settings.get("model_contract")

        def setting(key: str, section_default):
            value = settings.get(key)
            return section_default if value is None else value

        self.model = setting("model", config.get("openai", "model", "gpt-4o-mini"))
        self.max_tokens = setting("max_tokens", config.get("openai", "max_tokens"))
        self.temperature = setting("temperature", config.get("openai", "temperature", 0.2))
        self.max_context_results = setting(
            "max_context_results", config.get("openai", "max_context_results", 5)
        )
        # None means "do not send it", which is correct both for a model that
        # has no such parameter and for a reasoning model whose own default we
        # have no reason to override.
        self.reasoning_effort = (settings or {}).get("reasoning_effort") or config.get(
            "openai", "reasoning_effort", None
        )

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

        # Bound to the model, here, at construction — which is precisely why a
        # model change builds a new handler instead of reassigning `self.model`
        # on the live one. The two must never disagree.
        #
        # `encoding_for_model` raises for a model tiktoken has no mapping for,
        # which includes models that are perfectly valid but newer than the
        # installed tiktoken. Refusing those would mean this app could not be
        # pointed at a new model until a dependency bump, so it falls back —
        # loudly, and with a flag rather than silently.
        #
        # The blast radius is small TODAY and that is the reason this is
        # tolerable: `_log_token_counts` is the only consumer and it only feeds
        # logger.info, so an approximate encoding costs a log line, not an
        # answer. `tokenizer_exact` exists so that when token counts start
        # feeding usage metering, that code can refuse to bill from an estimate
        # instead of inheriting this compromise unnoticed.
        try:
            self.tokenizer = tiktoken.encoding_for_model(self.model)
            self.tokenizer_exact = True
        except KeyError:
            logger.warning(
                "tiktoken has no encoding for %r; using o200k_base for token accounting "
                "only. Generation is unaffected; logged token counts are approximate.",
                self.model,
            )
            self.tokenizer = tiktoken.get_encoding("o200k_base")
            self.tokenizer_exact = False

    def _request_kwargs(self, token_budget: int, temperature: float) -> dict:
        """The parameters this model will actually accept.

        The OpenAI families do not share a request shape, and the differences
        are hard failures rather than degradations:

        * a reasoning model rejects ``max_tokens`` and needs
          ``max_completion_tokens`` — which also counts reasoning tokens, so
          the same number buys less visible output;
        * a reasoning model rejects ``temperature`` outright;
        * ``reasoning_effort`` is meaningless to everything else.

        Hardcoding the old shape is why adding one of these models would have
        400'd on every single request. The contract lives in config.yaml beside
        the model, because that is where someone deciding to allow a model can
        see what allowing it commits them to.

        ``self._model_contract_override``, when set, is used INSTEAD of the
        ``config.yaml`` lookup below — the harness-only escape hatch a
        candidate model needs. ``model_spec(self.model)`` only ever reads
        ``config.yaml``'s ``allowed_models``; a model that lives only in the
        harness's own candidate list (not yet promoted into that allowlist)
        would otherwise silently fall through to the conservative default
        contract instead of the one the harness actually declared for it —
        wrong for a reasoning model that rejects ``temperature``, for
        instance. Unset for every production caller, so the lookup below is
        unchanged for every model actually offered in the console.
        """
        spec = self._model_contract_override or model_spec(self.model)

        kwargs: dict = {
            "model": self.model,
            spec["token_param"]: token_budget,
        }
        if spec["supports_temperature"]:
            kwargs["temperature"] = temperature
        # Absent means "use the model's own default", which is the right thing
        # to send when nobody has chosen — not a guess at what medium means.
        if self.reasoning_effort and spec["reasoning_efforts"]:
            kwargs["reasoning_effort"] = self.reasoning_effort
        return kwargs

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
            messages=cast(List[ChatCompletionMessageParam], messages),
            stream=True,
            **self._request_kwargs(self.max_tokens, self.temperature),
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
                messages=cast(List[ChatCompletionMessageParam], [{"role": "user", "content": prompt}]),
                # Suggestions are three short questions, so they get their own
                # small budget rather than the answer's — but they go through
                # the same contract, because the model rejects the same
                # parameters here as anywhere else.
                **self._request_kwargs(100, 0.5),
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
