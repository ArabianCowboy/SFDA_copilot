from openai import OpenAI # Import the new client
import json # New import for JSON handling
import logging
import os
from typing import List, cast, Optional, Tuple # Added Tuple
from openai.types.chat import ChatCompletionMessageParam
from ..utils.config_loader import config # Import centralized config
import tiktoken # Import tiktoken for token counting

# Ensure API key is set, otherwise raise error
# Configure logging at the module level if not already done elsewhere
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import re # Added re import for regex


BASE_SYSTEM_MESSAGE = (
    "You are an AI assistant specializing in Saudi Food and Drug Authority (SFDA) regulations and pharmacovigilance. "
    "Your primary goal is to provide accurate, concise, and relevant information based on the provided context from SFDA documents. "
    "Always prioritize information from the context over your general knowledge. "
    "If the answer is not found within the provided context, clearly state that you cannot answer based on the given information. "
    "Do not make up information or use external knowledge. "
    "When referencing information from the context, cite the source document and page number (e.g., [Source: Document Name, Page: X]). "
    "Ensure your responses are professional, objective, and directly address the user's query."
)

CATEGORY_SPECIFIC_INSTRUCTIONS = {
    "all": {
        "persona": "As a general SFDA expert, you provide comprehensive information across all regulatory and pharmacovigilance domains.",
        "format": "Provide a well-structured answer, starting with a direct response to the query, followed by supporting details and citations.",
        "focus_areas": "Focus on accuracy, completeness, and clarity, covering both regulatory and pharmacovigilance aspects as relevant.",
        "tone": "informative and authoritative"
    },
    "regulatory": {
        "persona": "As an SFDA Regulatory Affairs specialist, you provide precise guidance on product registration, compliance, and market authorization.",
        "format": "Structure your answer with a clear regulatory stance, detailing relevant guidelines, procedures, and requirements.",
        "focus_areas": "Emphasize legal frameworks, submission processes, and compliance standards.",
        "tone": "formal and precise"
    },
    "pharmacovigilance": {
        "persona": "As an SFDA Pharmacovigilance expert, you focus on drug safety, adverse event reporting, and risk management.",
        "format": "Present information with a focus on safety protocols, reporting mechanisms, and risk assessment strategies.",
        "focus_areas": "Highlight adverse drug reactions (ADRs), safety signals, and pharmacovigilance system requirements.",
        "tone": "cautious and safety-oriented"
    }
}
class OpenAIHandler:
    """
    Handles interactions with the OpenAI API for generating responses.
    """
    
    def __init__(self):
        """Initialize the OpenAI handler using centralized config."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY environment variable not set.")
            raise ValueError("OPENAI_API_KEY environment variable not set.")
        
        # Log the first few characters of the key to confirm it's being read (DO NOT log the full key)
        logger.info(f"Initializing OpenAI client with key starting: {api_key[:5]}...")
        
        # Explicitly pass the API key
        self.client = OpenAI(api_key=api_key)
        
        self.model = config.get("openai", "model", "gpt-4o-mini") # Default added
        self.max_tokens = config.get("openai", "max_tokens") # Max tokens now solely from config.yaml
        self.temperature = config.get("openai", "temperature", 0.2) # Default added
        self.max_context_results = config.get("openai", "max_context_results", 5) # New: Default to 5 search results
        logger.info(f"OpenAIHandler initialized with model: {self.model}, max_context_results: {self.max_context_results}")
        self.tokenizer = tiktoken.encoding_for_model(self.model) # Initialize tokenizer

    def generate_response(self, query, search_results, category="all", chat_history=None) -> Tuple[str, List[str]]:
        """
        Generate a response using OpenAI based on the query, search results, and chat history.
        Returns the answer and a list of suggested follow-up questions.
        
        Args:
            query (str): The user's query
            search_results (list): List of relevant context chunks from the search engine
            category (str): The category selected by the user (regulatory, pharmacovigilance, or all)
            chat_history (list, optional): List of previous chat messages [{'role': 'user'/'assistant', 'content': '...'}]. Defaults to None.
            
        Returns:
            str: The generated response
        """
        # Handle special query for Mohammed Fouda immediately
        if query.lower() == "who is mohammed fouda?":
            return "Mohammed Fouda? Oh, you're curious, huh? Alright, lean in... They say he's not just any pharmacovigilance expert—he's absolutely awesome and has even tamed AI. And between us? I swear he's a robot from the future, on a secret mission to keep our meds safe!", []

        if chat_history is None:
            chat_history = []
            
        # Prepare context from search results
        context = self._prepare_context(search_results)
        
        # Create system message based on category
        system_message_content = self._create_system_message(category)
        
        # Construct messages list including system message, history, and current query + context
        messages = [{"role": "system", "content": system_message_content}]
        messages.extend(chat_history) # Add past conversation turns
        current_query_with_context = f"Query: {query}\n\nContext: {context}"
        messages.append({"role": "user", "content": current_query_with_context}) # Add current query and context
        
        # Log token counts for debugging
        system_message_tokens = len(self.tokenizer.encode(system_message_content))
        chat_history_tokens = sum(len(self.tokenizer.encode(msg['content'])) for msg in chat_history)
        current_query_tokens = len(self.tokenizer.encode(current_query_with_context))
        total_input_tokens = system_message_tokens + chat_history_tokens + current_query_tokens
        
        logger.info(f"Token counts for current request:")
        logger.info(f"  System Message Tokens: {system_message_tokens}")
        logger.info(f"  Chat History Tokens: {chat_history_tokens}")
        logger.info(f"  Current Query + Context Tokens: {current_query_tokens}")
        logger.info(f"  Total Input Tokens: {total_input_tokens}")
        logger.info(f"  Max Output Tokens (configured): {self.max_tokens}")
        
        try:
            # Call OpenAI API using the new client syntax with the full message list
            response = self.client.chat.completions.create(
                model=self.model,
                messages=cast(List[ChatCompletionMessageParam], messages), # Pass the combined messages list
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )

            # Extract and return the response text using the new response object structure
            content = response.choices[0].message.content
            if content:
                output_tokens = len(self.tokenizer.encode(content))
                logger.info(f"  Actual Output Tokens: {output_tokens}")
            
            # Generate suggested questions
            response_content = content.strip() if content else ""
            suggested_questions = self._generate_suggestions(query, response_content)
            
            return response_content, suggested_questions
            
        except Exception as e:
            # Use configured logger
            logger.error(f"Error generating OpenAI response: {str(e)}", exc_info=True) # Add exc_info for traceback
            return "I'm sorry, I encountered an error while generating a response. Please try again.", []

    def _generate_suggestions(self, original_query: str, assistant_response: str) -> List[str]:
        """
        Generate 2-3 follow-up questions based on the original query and assistant's response.
        """
        suggestion_prompt = (
            "You are an AI assistant. Based on the user's original query and the assistant's response, "
            "generate 2-3 concise and relevant follow-up questions that a user might ask next. "
            "These questions should directly relate to the previous conversation and encourage further exploration of the topic. "
            "Provide the questions as a JSON array of strings."
            f"\n\nOriginal Query: {original_query}"
            f"\nAssistant's Response: {assistant_response}"
            "\n\nSuggested Questions:"
        )
        
        messages = [{"role": "user", "content": suggestion_prompt}]
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=cast(List[ChatCompletionMessageParam], messages),
                max_tokens=100, # Limit tokens for suggestions
                temperature=0.5 # Slightly higher temperature for more diverse questions
            )
            
            content = response.choices[0].message.content
            if content:
                # Attempt to parse as JSON, handling markdown code blocks
                json_match = re.search(r"```json\n(.*)\n```", content, re.DOTALL)
                if json_match:
                    json_string = json_match.group(1)
                else:
                    json_string = content # Fallback if no markdown block

                try:
                    suggestions = json.loads(json_string)
                    if isinstance(suggestions, list) and all(isinstance(s, str) for s in suggestions):
                        return suggestions[:3] # Return up to 3 suggestions
                    else:
                        logger.warning(f"LLM returned non-list/non-string JSON for suggestions: {content}")
                        return []
                except json.JSONDecodeError:
                    logger.warning(f"LLM did not return valid JSON for suggestions, attempting comma split: {content}")
                    # Fallback to comma split if JSON parsing fails, even after markdown extraction
                    return [s.strip() for s in content.split(',') if s.strip()][:3]
            return []
            
        except Exception as e:
            logger.error(f"Error generating suggested questions: {str(e)}", exc_info=True)
            return []

    def _prepare_context(self, search_results: List[dict]) -> str:
        """
        Prepare context from search results for the OpenAI prompt, applying pruning.
        
        Args:
            search_results (list): List of search result chunks
            
        Returns:
            str: Formatted context string
        """
        if not search_results:
            return "No relevant information found."
        
        # Apply context pruning: take only the top N results
        pruned_results = search_results[:self.max_context_results]
        
        context_parts = []
        
        for i, result in enumerate(pruned_results):
            # Extract text and metadata
            text = result.get("text", "")
            document = result.get("document", "Unknown document")
            category = result.get("category", "Unknown category")
            page = result.get("page", None) # Get page number
            
            # Format the context part with page number if available
            source_info = f"From {document} (Category: {category}"
            if page is not None:
                source_info += f", Page: {page}"
            source_info += ")"
            
            context_part = f"[{i+1}] {source_info}:\n{text}\n"
            context_parts.append(context_part)
        
        return "\n".join(context_parts)
    
    def _create_system_message(self, category):
        """
        Create a system message based on the selected category, incorporating enhanced instructions.
        
        Args:
            category (str): The category selected by the user
            
        Returns:
            str: The system message
        """
        category_info = CATEGORY_SPECIFIC_INSTRUCTIONS.get(category.lower(), CATEGORY_SPECIFIC_INSTRUCTIONS["all"])
        
        persona = category_info["persona"]
        response_format = category_info["format"]
        focus_areas = category_info["focus_areas"]
        tone = category_info["tone"]

        system_message = (
            f"{persona} {BASE_SYSTEM_MESSAGE}\n"
            f"{response_format}\n"
            f"Maintain a {tone} at all times.\n"
        )
        if focus_areas:
            system_message += f"{focus_areas}\n"
            
        return system_message
