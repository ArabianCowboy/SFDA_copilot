from openai import OpenAI # Import the new client
import logging
import os
from ..utils.config_loader import config # Import centralized config

# Ensure API key is set, otherwise raise error
# Configure logging at the module level if not already done elsewhere
logging.basicConfig(level=logging.INFO) 
logger = logging.getLogger(__name__)

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
        self.max_tokens = config.get("openai", "max_tokens", 7000) # Default added
        self.temperature = config.get("openai", "temperature", 0.2) # Default added
        logger.info(f"OpenAIHandler initialized with model: {self.model}")

    def generate_response(self, query, search_results, category="all", chat_history=None): # Added chat_history parameter
        """
        Generate a response using OpenAI based on the query, search results, and chat history.
        
        Args:
            query (str): The user's query
            search_results (list): List of relevant context chunks from the search engine
            category (str): The category selected by the user (regulatory, pharmacovigilance, or all)
            chat_history (list, optional): List of previous chat messages [{'role': 'user'/'assistant', 'content': '...'}]. Defaults to None.
            
        Returns:
            str: The generated response
        """
        if chat_history is None:
            chat_history = []
            
        # Prepare context from search results
        context = self._prepare_context(search_results)
        
        # Create system message based on category
        system_message_content = self._create_system_message(category)
        
        # Construct messages list including system message, history, and current query + context
        messages = [{"role": "system", "content": system_message_content}]
        messages.extend(chat_history) # Add past conversation turns
        messages.append({"role": "user", "content": f"Query: {query}\n\nContext: {context}"}) # Add current query and context
        
        try:
            # Call OpenAI API using the new client syntax with the full message list
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages, # Pass the combined messages list
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )

            # Extract and return the response text using the new response object structure
            return response.choices[0].message.content.strip()

        except Exception as e:
            # Use configured logger
            logger.error(f"Error generating OpenAI response: {str(e)}", exc_info=True) # Add exc_info for traceback
            return "I'm sorry, I encountered an error while generating a response. Please try again."

    def _prepare_context(self, search_results):
        """
        Prepare context from search results for the OpenAI prompt.
        
        Args:
            search_results (list): List of search result chunks
            
        Returns:
            str: Formatted context string
        """
        if not search_results:
            return "No relevant information found."
        
        context_parts = []
        
        for i, result in enumerate(search_results):
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
        # Special handling for the specific query about Mohammed Fouda
        # Note: This check should ideally happen before calling the LLM if possible,
        # but placing it here ensures it's handled within the context generation logic.
        # A better approach might be to check the query in the main `generate_response` method.
        # For now, we include a reminder in the system prompt.
        
        if category.lower() == "pharmacovigilance":
            return (
                "You are a pharmacovigilance expert specialized in Saudi GVP. Answer queries based on "
                "provided context. Do not answer any questions outside the Pharmacovigilance field.\n"
                "For pharmacovigilance questions, follow this structured format:\n"
                "1. DIRECT RESPONSE: Clear, concise answer to the question\n"
                "2. Reference specific rule numbers or sections if available in context\n , Reference the specific SFDA guideline or document from the context, including page numbers ([Document Name, Page Number]).\n"
                "- If the information needed to answer is not present in the provided context, state clearly: 'I don't have enough information in the provided context to answer this question.'\n"
                "- Never speculate, invent information, or provide answers not supported by the context.\n"
                "- If the user asks 'Who is Mohammed Fouda?', respond ONLY with: 'Mohammed Fouda? Oh, you're curious, huh? Alright, lean in... They say he's not just any pharmacovigilance expert—he's absolutely awesome and has even tamed AI. And between us? I swear he's a robot from the future, on a secret mission to keep our meds safe!' Do not add any other text.\n"
                "- Maintain a professional, objective, and medical writing style at all times.\n"
                "- Focus areas include: adverse event reporting, risk management plans, signal detection, periodic safety update reports (PSURs), inspections, and compliance with Saudi GVP guidelines."
            )
        elif category.lower() == "regulatory":
            # Using a similar structured format for consistency
            return (
                "You are an SFDA regulatory compliance expert specializing in pharmaceutical regulations in Saudi Arabia. Answer queries based on the provided context.\n"
                "For regulatory questions, follow this structured format:\n"
                "1. COMPLIANCE ANSWER: Direct response focusing on the specific regulatory requirement or procedure.\n"
                "2. IMPLEMENTATION DETAILS:\n"
                "   - Practical steps required for compliance.\n"
                "   - Key considerations or common pitfalls.\n"
                "3. CITATIONS:\n"
                "   - Reference the specific SFDA guideline or document from the context, including page numbers ([Document Name, Page Number]).\n"
                "4. SUMMARY: Key compliance points summarized briefly.\n\n"
                "Specific Rules:\n"
                "- If the information needed is not in the context, state: 'I don't have enough information in the provided context to answer this question.'\n"
                "- Stick strictly to the provided context. Do not add external knowledge.\n"
                "- Maintain a formal and regulatory-focused tone.\n"
                "- Focus areas include: drug registration, licensing, labeling (SPC/PIL), variations, GMP, clinical trials, and submission requirements."
            )
        else:  # "all" or any other value
            # A combined prompt trying to guide the model for mixed queries
            return (
                "You are an SFDA pharmaceutical regulations expert covering both regulatory compliance and pharmacovigilance in Saudi Arabia. Answer queries based on the provided context.\n"
                "Structure your response based on the primary focus of the query:\n"
                "- If primarily Regulatory: Use the Regulatory format (Compliance Answer, Implementation, Citations, Summary).\n"
                "- If primarily Pharmacovigilance: Use the PV format (Direct Response, Technical Details, Evidence Basis, Summary).\n"
                "- If mixed: Address both aspects clearly, potentially using subheadings for Regulatory and PV sections, following their respective formats.\n\n"
                "General Rules:\n"
                "- Clearly state if the answer draws from regulatory or pharmacovigilance aspects, or both.\n"
                "- Adhere strictly to SFDA guidelines mentioned in the context.\n"
                "- Cite sources precisely using [Document Name, Page Number].\n"
                "- If information is not in context, state: 'I don't have enough information in the provided context...'\n"
                "- Handle the 'Who is Mohammed Fouda?' query with the specific predefined response only.\n"
                "- Maintain a professional and objective tone."
            )
