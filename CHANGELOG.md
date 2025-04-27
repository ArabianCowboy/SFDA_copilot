# Changelog

## [2025-04-26]
- Fixed skeleton (typing indicator) message so it always appears below the latest user or bot message in the chat, ensuring correct message flow and improved UX. Updated showTypingIndicator() in static/js/app.js for optimized DOM insertion.
- Fixed login form visibility issues:
  - Changed input label color from white to black for better visibility
  - Made labels bolder (font-weight: 600)
  - Improved placeholder text visibility with dark gray color (#666)
  - Removed visible placeholder text from login/signup forms
- Fixed UI blinking issues when switching between sign-in tabs:
  - Simplified tab transitions to use only opacity fade
  - Removed transform animations that caused content shifting
  - Scoped tab transition styles to auth modal only to prevent affecting sidebar buttons
- Enhanced password error messaging:
  - Added specific error messages for wrong credentials
  - Display errors with warning icons
  - Highlight invalid input fields

## [2025-04-26]
- Security and Error Handling Improvements:
  - Added List type import for type hints in web/api/app.py
  - Added SearchResult import from search_engine for proper type hints
  - Updated Talisman security configuration to use frame_options='DENY' in debug mode
  - Added error handling for search engine initialization with proper logging
  - Standardized logging usage throughout the application
  - Removed unused `QuizGenerator` service (`web/services/quiz_generator.py`).

## [2025-04-26]
- Implemented Medium Priority Improvements:
  - Added search engine parameters (`k`, `semantic_weight`, `lexical_weight`, `semantic_multiplier`, `lexical_multiplier`) to `web/config.yaml`.
  - Enhanced docstrings and type hints in `web/services/search_engine.py` for clarity and maintainability.
  - Added comments explaining score handling (FAISS distance conversion, normalization) in `web/services/search_engine.py`.
- Implemented Phase 4: Hybrid Search:
  - Updated `web/services/search_engine.py` to combine semantic (FAISS) and lexical (TF-IDF) search results using weighted scoring (configurable via `semantic_weight`, `lexical_weight`).
  - Added `SearchResult` dataclass to standardize search result structure.
  - Enhanced logging and error handling throughout the search process.
  - Added embedding normalization in `get_embedding`.
  - Improved category filtering logic in both semantic and lexical search.
  - Refined result combination logic (`_combine_results`) to handle duplicates and calculate weighted scores.
  - Updated `web/api/app.py` to handle the `List[SearchResult]` returned by the search engine and convert it to the format expected by the `OpenAIHandler`.
- Implemented Phase 3: Conversation History Management:
  - Added session configuration (secret key, history length) to `web/api/app.py`.
  - Imported `session` from Flask in `web/api/app.py`.
  - Modified `chat` endpoint in `web/api/app.py` to retrieve, update, and truncate chat history in the session.
  - Updated `OpenAIHandler.generate_response` in `web/services/openai_app.py` to accept and use `chat_history`.
- Implemented Phase 2: Query Expansion:
  - Added `preprocess_query` function with pharmaceutical term dictionary to `web/api/app.py`.
  - Modified `chat` endpoint in `web/api/app.py` to call `preprocess_query` before search.
- Implemented Phase 1: Enhanced System Messages & Response Formatting:
  - Updated `_create_system_message` in `web/services/openai_app.py` with structured formats for PV/Regulatory/All categories and special query handling.

## [2025-04-26]
- Implemented Phase 4: Hybrid Search:
  - Updated `web/services/search_engine.py` to combine semantic (FAISS) and lexical (TF-IDF) search results using weighted scoring (configurable via `semantic_weight`, `lexical_weight`).
  - Added `SearchResult` dataclass to standardize search result structure.
  - Enhanced logging and error handling throughout the search process.
  - Added embedding normalization in `get_embedding`.
  - Improved category filtering logic in both semantic and lexical search.
  - Refined result combination logic (`_combine_results`) to handle duplicates and calculate weighted scores.
  - Updated `web/api/app.py` to handle the `List[SearchResult]` returned by the search engine and convert it to the format expected by the `OpenAIHandler`.
- Implemented Phase 3: Conversation History Management:
  - Added session configuration (secret key, history length) to `web/api/app.py`.
  - Imported `session` from Flask in `web/api/app.py`.
  - Modified `chat` endpoint in `web/api/app.py` to retrieve, update, and truncate chat history in the session.
  - Updated `OpenAIHandler.generate_response` in `web/services/openai_app.py` to accept and use `chat_history`.
- Implemented Phase 2: Query Expansion:
  - Added `preprocess_query` function with pharmaceutical term dictionary to `web/api/app.py`.
  - Modified `chat` endpoint in `web/api/app.py` to call `preprocess_query` before search.
- Implemented Phase 1: Enhanced System Messages & Response Formatting:
  - Updated `_create_system_message` in `web/services/openai_app.py` with structured formats for PV/Regulatory/All categories and special query handling.

## [2025-04-26]
- Implemented Phase 3: Conversation History Management:
  - Added session configuration (secret key, history length) to `web/api/app.py`.
  - Imported `session` from Flask in `web/api/app.py`.
  - Modified `chat` endpoint in `web/api/app.py` to retrieve, update, and truncate chat history in the session.
  - Updated `OpenAIHandler.generate_response` in `web/services/openai_app.py` to accept and use `chat_history`.
- Implemented Phase 2: Query Expansion:
  - Added `preprocess_query` function with pharmaceutical term dictionary to `web/api/app.py`.
  - Modified `chat` endpoint in `web/api/app.py` to call `preprocess_query` before search.
- Implemented Phase 1: Enhanced System Messages & Response Formatting:
  - Updated `_create_system_message` in `web/services/openai_app.py` with structured formats for PV/Regulatory/All categories and special query handling.

## [2025-04-26]
- Implemented enhanced pharmacovigilance-specific RAG prompt with structured response format in `web/services/openai_app.py`
- Reverted RAG prompt changes in `web/services/openai_app.py` back to the previous version due to negative impact on response quality.

## [2025-04-26]
### Added
- Switched to local sentence-transformers "all-mpnet-base-v2" embeddings
- Adaptive chunking in data processing with:
  - Table detection using pattern matching
  - Larger chunk sizes (3000/600) for table content
  - Default sizes (1000/200) for regular text
  - Chunk type metadata in output
- Verified data processing pipeline (`web/services/data_processing.py`) successfully generates FAISS index (`web/processed_data/faiss_index.bin`) using local sentence-transformer embeddings (`all-mpnet-base-v2`).

## [2025-04-26]
- Updated color scheme to match SFDA branding:
  - Primary green: #2E8B57
  - Secondary blue: #1E5F8C
  - White background: #FFFFFF  
- Modernized UI elements:
  - Added subtle animations and hover effects
  - Improved button styling with better contrast
  - Enhanced message bubbles with shadows
  - Refined input area styling:
    * Added gradient background
    * Improved focus states
    * Enhanced send button with hover effects
    * Increased padding and border radius
- Improved accessibility throughout

## [2025-04-26]
- Added performance optimizations to static/js/app.js:
  - Implemented requestAnimationFrame for smoother message rendering
  - Added document fragments to batch DOM operations
  - Introduced event listener tracking and cleanup system
  - Optimized FAQ button and category selector event handling
- Fixed "marked is not defined" error by adding marked and DOMPurify libraries to package.json and importing them in static/js/app.js
- Fixed module import error by using proper URL-based imports for marked and DOMPurify libraries
- Updated app.py and config_loader.py to explicitly load .env file from project root directory, ensuring environment variables are properly loaded
- Consolidated OpenAI client functionality into shared OpenAIClientManager utility
- Updated search_engine.py and data_processing.py to use shared OpenAIClientManager
- Reduced code duplication and improved consistency in OpenAI API usage
- Renamed application to "SFDA Copilot" and updated related UI elements (title, sidebar header, tagline, welcome message) in `web/templates/index.html`.
- Enhanced API security by adding `Flask-Talisman` for security headers (CSP, HSTS, etc.) and `Flask-Cors` for CORS configuration in `web/api/app.py`.
- Updated `web/requirements.txt` to include `Flask-Talisman` and `Flask-Cors`.
- Fixed traceback error during `Talisman` initialization in `web/api/app.py` by filtering `None` values from the Content Security Policy (CSP) dictionary before passing it.
- Corrected `TypeError` during `Talisman` initialization by changing the keyword argument `session_cookie_httponly` to the correct `session_cookie_http_only` in `web/api/app.py`.
- Fixed authentication issues by modifying `Talisman` configuration to disable CSP in development mode and add proper Supabase domains to CSP in production mode.
- Removed duplicate search engine initialization check in `web/api/app.py`.
- Removed unused imports from `web/api/auth.py`, `web/services/data_processing.py`, `web/services/search_engine.py`, `web/utils/supabase_client.py`, and `web/tests/test_auth.py`.
- Corrected variable reference in error message within `web/services/data_processing.py`.
- Removed unused function `getCurrentTime` from `static/js/app.js`.
- Removed unused HTML elements (password toggles, char count, input error) from `web/templates/index.html`.
- Removed unused utility file `web/utils/utils.py`.
- Removed `desktop.ini` files from project directories (x12).
- Updated imports in `web/tests/test_search.py` to use relative paths for robustness.
  - Removed loading overlay feature (HTML and JS).
  - Fixed broken HTML structure in `web/templates/index.html` by restoring the sidebar container and correctly nesting FAQ buttons within `<nav>` elements.
  - Added subtle CSS animations/transitions for improved UI feedback (message fade-in, button hover effects) in `static/css/style.css`.
  - Replaced the three-dot typing indicator with a skeleton loader placeholder (shimmering avatar and text lines) for better visual feedback during bot response loading in `static/css/style.css` and `static/js/app.js`.
  - Refined `box-shadow` styles throughout `static/css/style.css` for a softer, more modern appearance on elements like sidebar, message bubbles, input area, buttons, and toast notifications.
  - Polished sidebar organization in `static/css/style.css` and `web/templates/index.html` by adding separators, adjusting spacing, and including icons for FAQ categories.
  - Enhanced input area feedback in `static/js/app.js` by adding a loading spinner to the Send button, changing its text to "Sending...", and disabling the button/input field during API requests.
  - Implemented responsive design for the sidebar using Bootstrap's offcanvas component in `web/templates/index.html`, `static/js/app.js`, and `static/css/style.css`. The sidebar now collapses into an offcanvas menu on screens smaller than the large breakpoint (lg).
  - Corrected skeleton loader display order in `static/js/app.js` by wrapping DOM addition in `showTypingIndicator` with `requestAnimationFrame` to synchronize with `addMessage`.
  - Enhanced the initial welcome message in `web/templates/index.html` by adding relevant Bootstrap icons to the list of capabilities for better visual guidance.
  - Polished the sidebar header (`.sidebar-header`) by adding an icon next to the title, adjusting spacing/fonts, and adding a background to the auth status area for better visual organization (`web/templates/index.html`, `static/css/style.css`).
  - Added a subtle fade-in animation (`@keyframes headerFadeIn`) to the sidebar header on load in `static/css/style.css`.
  - Applied Glassmorphism design (blur, transparency, border, shadow) to the auth modal (`static/css/style.css`).
  - Added smooth transitions for modal appearance, tab switching, and form field focus in the auth modal (`static/css/style.css`).
  - Styled loading spinners within auth buttons using brand colors (`static/css/style.css`).
  - Enhanced auth modal visual hierarchy: made call-to-action buttons larger and bolder (`btn-lg`, `fw-bold`), increased spacing between form elements (`mb-4`), and added clearer visual distinction for active tabs (white underline) (`web/templates/index.html`, `static/css/style.css`).
  - Implemented floating labels for email and password fields in the auth modal using Bootstrap's `.form-floating` class (`web/templates/index.html`, `static/css/style.css`).
  - Improved form field focus states with adjusted brand color shadow and background (`static/css/style.css`).
  - Added clearer visual styling for input validation states (`.is-invalid`) with background color and focus shadow (`static/css/style.css`).
  - Fixed incorrectly rendered comments in both Login and Signup tabs of the auth modal by removing non-standard comment syntax (`web/templates/index.html`) (x2).
  - Applied a theme-aligned gradient background (green-to-blue) to the auth modal content (`static/css/style.css`).
  - Adjusted modal header, input fields, labels, and validation state colors for better contrast and consistency with the new gradient background (`static/css/style.css`).
  - Refactored `static/css/style.css` to use CSS Nesting for improved organization.
  - Added CSS scroll-snap (`scroll-snap-type: y mandatory`) to the chat message container (`.messages`) for smoother scrolling behavior.
  - Enhanced hover effects in `static/css/style.css`:
    * Added 3D tilt effect (`transform: perspective(...) rotateX(...) rotateY(...) scale(...)`) to FAQ buttons (`.nav-pills .nav-link`).
    * Improved send button (`#send-button`) hover effect with combined lift and scale (`transform: translateY(-2px) scale(1.03)`).
  - Implemented View Transitions API in `static/js/app.js`:
    * Wrapped message appending in `addMessage` function with `document.startViewTransition` for smoother message appearance.
    * Added event listener for Bootstrap tab `show.bs.tab` event on auth modal tabs to trigger `document.startViewTransition`, enabling transitions between login/signup panes.
    * Added compatibility check (`if (document.startViewTransition)`) for browsers that don't support the API.
  - Added `view-transition-name` CSS property to relevant elements (`.faq-section`, `.message`) in `static/css/style.css` to identify them for the View Transitions API.
  - Implemented scroll-driven animations for FAQ items in `static/css/style.css`:
    * Defined `@keyframes faqItemFadeIn` for a fade-in/slide-up effect.
    * Defined `@scroll-timeline faq-scroll-timeline` linked to the sidebar scroll container (`#sidebarContentRegular`).
    * Applied the animation (`animation: faqItemFadeIn linear forwards`), timeline (`animation-timeline: faq-scroll-timeline`), and range (`animation-range: entry 20% cover 50%`) to FAQ links (`.faq-section .nav-link`).
    * Optimized animation with `will-change: transform, opacity`.
  - Applied Glassmorphism styling to the global category selector dropdown in the sidebar (`static/css/style.css`):
    * Added semi-transparent background (`rgba`), `backdrop-filter: blur()`, subtle border, and white text color.
    * Styled hover and focus states with adjusted background/border and focus ring (`box-shadow`).
    * Replaced default dropdown arrow with a white SVG arrow for better visibility.
    * Added CSS transitions for smooth hover/focus effects.
  - Replaced native global category `<select>` dropdowns with custom interactive dropdowns (`web/templates/index.html`, `static/css/style.css`, `static/js/app.js`):
    * **HTML:** Introduced `.custom-select-wrapper`, `.original-select` (hidden), `.custom-select-trigger`, and `.custom-select-options` structure for both regular and offcanvas sidebars.
    * **CSS:** Styled the custom trigger with Glassmorphism, added a CSS arrow, styled the options container (absolute positioning, Glassmorphism background, scroll), and implemented open/close animations using `transform: scaleY()` and `opacity`.
    * **JS:** Created `setupCustomSelect` function to populate custom options from the original select, handle trigger clicks (toggle open/close), handle option clicks (update value, update display, close dropdown, dispatch 'change' event on original select), and added basic keyboard/outside-click handling. Called this function for both dropdown instances on `DOMContentLoaded`.
  - Refined custom dropdown appearance based on feedback (`static/css/style.css`):
    * Reverted styling for the selected item within the options list back to `display: none;` (`.custom-select-wrapper .custom-select-options > div.selected`) to address visual duplication issue.
    * Changed the background color of the options list (`.custom-select-options`) to a darker, more opaque green (`rgba(33, 99, 61, 0.9)`) for better visual distinction from the trigger button.
  - Added visual separator (`<hr class="separator">`) between the custom dropdown and FAQ section in both regular and offcanvas sidebars to help identify any layout issues causing text duplication.
  - Added debug element with red background between the dropdown and separator to further isolate the source of text duplication.
  - Added CSS rule to hide any direct text nodes that appear after the custom dropdown wrapper in the sidebar (`.sidebar > .custom-select-wrapper + :not(div):not(hr):not(h4):not(nav)`) to address the text duplication issue.

## [2025-04-25]
- Fixed `TypeError` in `web/api/app.py` by correcting the arguments passed to `config.get()` for rate limiting settings.
- Upgraded UX with major accessibility improvements:
  - Navigation converted from buttons to Bootstrap nav-pills with ARIA roles
  - All forms enhanced with proper labels, help text and validation
  - Chat input added character counter and validation error display
- Updated `web/utils/config_loader.py` to explicitly load `SUPABASE_URL` and `SUPABASE_KEY` from environment variables, ensuring they override YAML placeholders.
- Temporarily disabled `@auth_required` decorator on `/api/chat` in `web/api/app.py` for testing purposes.
- Updated OpenAI API calls in `web/services/openai_app.py` (chat completions) and `web/services/search_engine.py` (embeddings) to use the new v1.x client syntax.
- Added `load_dotenv(override=True)` to `web/api/app.py` to ensure `.env` variables are loaded correctly, resolving OpenAI API key issues.
- Re-enabled `@auth_required` decorator on `/api/chat` in `web/api/app.py`.
- Added HTML elements for login/signup modal and auth status display to `web/templates/index.html`.
- Added Supabase JS client initialization and authentication logic (login, signup, logout, session handling, token sending) to `static/js/app.js`.
- Debugged "invalid API" error for OpenAI integration by modifying `web/services/openai_app.py` to explicitly pass the API key to the `OpenAI()` client and adding logging.
- Fixed Supabase authentication bug by extracting the JWT token from the Bearer Authorization header in `web/api/app.py`, resolving 401 errors on `/api/chat`.
