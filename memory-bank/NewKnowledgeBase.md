# New Knowledge Base

1. The login form in the auth modal uses white text labels on a gradient background, which can cause visibility issues. Changing the label color to black and making them bolder significantly improves readability.

2. Tab transitions in the auth modal can cause content blinking when using transform animations. Simplifying to opacity-only transitions creates a smoother experience.

3. Placeholder text in form inputs needs explicit styling with the ::placeholder pseudo-element to ensure visibility.

4. Bootstrap's floating label implementation requires a placeholder attribute on inputs, but visible placeholder text can be distracting. Using a single space character as the placeholder value (" ") maintains the floating label functionality without showing visible placeholder text.

5. CSS transitions and animations can affect elements outside their intended scope. Scoping styles with more specific selectors (e.g., #authModal .tab-pane instead of just .tab-pane) prevents unintended side effects on other parts of the UI.

## 2025-04-26
1. When rendering a skeleton loader (typing indicator) in a chat UI, always insert it after the last message element (user or bot) to ensure it appears below the most recent message. This prevents visual confusion and maintains correct message flow, especially when using requestAnimationFrame for message rendering.
2.  **Configuration Management (Search):** Centralizing search parameters like `k`, weights (`semantic_weight`, `lexical_weight`), and candidate multipliers (`semantic_multiplier`, `lexical_multiplier`) in `web/config.yaml` makes the search behavior easily configurable without code changes.
2.  **Code Documentation (Docstrings & Type Hints):** Adding detailed docstrings explaining the purpose, arguments, and return values of functions/methods (like in `web/services/search_engine.py`), along with precise type hints (e.g., `-> Optional[np.ndarray]`, `-> List[SearchResult]`), significantly improves code readability, maintainability, and helps prevent type-related errors.
3.  **Score Handling Explanation:** Explicitly commenting on how scores are handled is important for clarity. For instance, noting that FAISS L2 distance is converted to similarity (`1 / (1 + distance)`) and that TF-IDF cosine similarity is already in a comparable range helps understand the basis for the weighted combination in `_combine_results`. Normalizing embeddings (`embedding / norm`) in `get_embedding` is also a key step for meaningful vector comparisons.
4.  **Identifying Unused Code:** Regularly searching the codebase for imports and usages of specific classes or modules (e.g., using `search_files` tool) can help identify components like `QuizGenerator` that are no longer integrated and can be safely removed.

## 2025-04-26
1.  **Hybrid Search Implementation:** Combining semantic (FAISS) and lexical (TF-IDF) search in `web/services/search_engine.py` provides more robust retrieval. Semantic search captures meaning, while lexical search matches keywords.
2.  **Weighted Combination:** Using configurable weights (`semantic_weight`, `lexical_weight`) allows tuning the balance between semantic and lexical contributions to the final score in `_combine_results`.
3.  **SearchResult Dataclass:** Defining a `SearchResult` dataclass standardizes the output format of the search engine, making it easier to consume in other parts of the application (like `web/api/app.py`). It includes essential fields like text, score, document source, and metadata.
4.  **Score Normalization/Conversion:** Semantic search (FAISS L2 distance) scores need conversion (e.g., `1 / (1 + distance)`) to represent similarity (higher is better), aligning them with lexical scores (TF-IDF cosine similarity) before weighted combination. Embedding normalization (`embedding / norm`) is also crucial for consistent FAISS results.
5.  **Candidate Fetching Multipliers:** Fetching more candidates initially from both semantic (`semantic_multiplier`) and lexical (`lexical_multiplier`) searches before combining provides a larger pool for the final ranking, potentially improving the quality of the top `k` results.
6.  **Robust Initialization & Error Handling:** Adding checks for file existence, dimension mismatches (FAISS index, TF-IDF matrix, DataFrame), and using `try...except` blocks with detailed logging (`logger.exception`) makes the search engine initialization and search process more resilient.
7.  **Data Structure Adaptation:** When integrating components, ensure data structures match. The `chat` function in `web/api/app.py` needed modification to convert the `List[SearchResult]` from the search engine into the `List[Dict]` expected by the `OpenAIHandler`.

## 2025-04-26
1.  **Query Expansion Implementation:** Adding a `preprocess_query` function in `web/api/app.py` with a dictionary of domain-specific terms (e.g., pharmacovigilance synonyms) enhances search recall by expanding user queries before they hit the search engine. This helps match user intent even with varied terminology.
2.  **Structured System Prompts:** Refining the `_create_system_message` method in `web/services/openai_app.py` to provide category-specific (PV, Regulatory, All) structured response formats and explicit rules (like handling specific questions or out-of-context scenarios) gives the LLM clearer instructions, leading to more consistent and domain-appropriate outputs.
3.  **Flask Session for Chat History:** Utilizing Flask's `session` object (requires setting `app.secret_key`) in `web/api/app.py` is an effective way to maintain conversation state. Storing user/assistant message pairs and implementing truncation logic (e.g., `MAX_CHAT_HISTORY_LENGTH`) keeps the context manageable.
4.  **Passing History to LLM:** Modifying the `generate_response` method in `web/services/openai_app.py` to accept the `chat_history` list and include it in the `messages` payload sent to the OpenAI API enables the model to generate contextually relevant responses in multi-turn dialogues.
5.  **Configuration Management:** Using `config.get()` from `web/utils/config_loader.py` allows centralizing settings like `MAX_CHAT_HISTORY_LENGTH`, making them easily adjustable.

## 2025-04-26
1. Implemented local sentence-transformers embeddings:
   - "all-mpnet-base-v2" model provides 768-dimensional embeddings
   - Runs locally without API calls
   - Requires ~420MB disk space for model
   - Better for domain-specific text than general OpenAI embeddings

## 2025-04-26
1. Learned that adaptive chunking significantly improves table content processing in PDFs:
   - Tables require larger chunks (3000 chars) to maintain structure
   - Regular text works better with smaller chunks (1000 chars)
   - Pattern matching can reliably detect most table formats

## UI Color Scheme
1. SFDA's official green (#2E8B57) provides a strong brand identity
2. Secondary blue (#1E5F8C) offers good contrast while staying professional
3. Pure white background (#FFFFFF) with dark gray text (#333333) ensures readability

## Modernization Techniques
1. Subtle hover animations improve interactivity
2. Light shadows (box-shadow) add depth while keeping interface clean
3. Increased border-radius (8px) creates softer, more modern look
4. Micro-interactions (like translateX on hover) enhance user experience
5. Layered shadows create visual hierarchy

## Accessibility Considerations
1. Maintained WCAG 2.1 AA contrast ratios
2. Ensured color-blind friendly palette
3. Used semantic HTML structure
4. Preserved keyboard navigability
1. Performance Optimizations in JavaScript:
   - Using requestAnimationFrame can significantly improve animation and rendering performance by syncing with the browser's refresh rate
   - Document fragments allow batching DOM operations to minimize reflows
   - Centralized event listener management helps prevent memory leaks and makes cleanup easier

1. The codebase uses a centralized OpenAIClientManager for all OpenAI operations, ensuring consistent API usage across services
2. The application requires both marked and DOMPurify libraries for rendering Markdown content in chat messages
3. Environment variables need to be loaded from the project root directory, not the web/ directory, requiring explicit path configuration in both app.py and config_loader.py
4. When using ES modules in the browser, bare module specifiers (e.g., 'marked') are not supported - imports must use full URLs (e.g., 'https://cdn.jsdelivr.net/npm/marked@12.0.0/+esm')
2. The search functionality combines both semantic (FAISS) and lexical (TF-IDF) search approaches
3. Data processing and search are intentionally separated into different services for better modularity
4. The project follows a clear separation between API routes, business logic services, and utility functions
5. Configuration is centralized through config.yaml and environment variables

1. The project uses Bootstrap 5.3 for frontend components and styling
2. Supabase is integrated for authentication with JWT token handling
3. OpenAI API is used for chat completions and embeddings
4. Key accessibility improvements implemented:
   - ARIA roles for navigation and forms
   - Proper form labeling and validation
   - Character counting for input fields
5. The frontend uses a combination of Bootstrap components and custom CSS

1.  The `ConfigLoader` in `web/utils/config_loader.py` loads settings from `config.yaml` but requires explicit `os.getenv()` calls within its `_apply_env_overrides` method to reliably override specific YAML placeholders (like `${VAR_NAME}`) with environment variables. Loading `.env` at the start doesn't automatically guarantee these specific overrides within the loader's logic.
2.  The `openai` library version 1.0.0 and later requires using the `OpenAI()` client instance. API calls must be updated from the old module-level functions (e.g., `openai.ChatCompletion.create`, `openai.Embedding.create`) to the new client methods (e.g., `client.chat.completions.create`, `client.embeddings.create`). Response structures have also changed.
3.  Loading environment variables from `.env` in Flask requires explicitly calling `load_dotenv()` from the `python-dotenv` library, preferably near the start of the main application script (`web/api/app.py`). Using `load_dotenv(override=True)` ensures that variables in `.env` take precedence over any existing system environment variables with the same name.
4.  Frontend authentication with Supabase involves:
    *   Including the Supabase JS client library (`supabase-js`).
    *   Initializing the client with the Supabase URL and Anon Key (ideally fetched securely, not hardcoded).
    *   Using `supabase.auth.signInWithPassword()`, `supabase.auth.signUp()`, and `supabase.auth.signOut()` for user actions.
    *   Using `supabase.auth.getSession()` to retrieve the current session and access token.
    *   Using `supabase.auth.onAuthStateChange()` to reactively update the UI based on login/logout events.
    *   Adding the retrieved access token to the `Authorization: Bearer <token>` header in `fetch` requests to protected backend endpoints.
5.  The `OpenAI` client (v1.x+) automatically attempts to load the `OPENAI_API_KEY` from environment variables upon initialization (`client = OpenAI()`). However, for debugging or to ensure the correct key is used when environment loading might be complex, the key can be explicitly passed during initialization: `client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))`. This was done in `web/services/openai_app.py`.
6.  Supabase JWT authentication: When using the Supabase Python client to validate user tokens, the backend must extract the raw JWT from the `Authorization` header (removing the "Bearer " prefix) before passing it to `supabase.auth.get_user(token)`. Passing the full header string will always result in authentication failure and 401 errors. This was fixed in `web/api/app.py`.
7.  The application's user-facing name is "SFDA Copilot", reflected in the HTML title, sidebar header, and initial welcome message within `web/templates/index.html`.
8.  API security is enhanced using `Flask-Talisman` in `web/api/app.py` to set crucial HTTP security headers (e.g., Content-Security-Policy, Strict-Transport-Security, X-Frame-Options). Configuration is conditional based on the application's debug mode status.
9.  Cross-Origin Resource Sharing (CORS) is managed by `Flask-Cors` in `web/api/app.py`. In debug mode, it allows all origins, while in production, it restricts access based on the `allowed_origins` list defined in the configuration (`config.yaml` or environment variables).
10. When configuring `Flask-Talisman`'s Content Security Policy (CSP), ensure that any dynamically added values (like URLs from environment variables) are handled correctly. If an environment variable might be missing, conditionally add it to the CSP list and filter out any `None` values from the final CSP dictionary before passing it to `Talisman` to prevent initialization errors. This was implemented in `web/api/app.py`.
11. During `Flask-Talisman` initialization, the correct keyword argument to control the HttpOnly flag for session cookies is `session_cookie_http_only`, not `session_cookie_httponly`. Using the incorrect name will result in a `TypeError`. This was corrected in `web/api/app.py`.
12. When implementing Content Security Policy (CSP) with `Flask-Talisman`, it's important to consider authentication services like Supabase. In development environments, it may be beneficial to disable CSP entirely (`content_security_policy=None`) to simplify debugging. In production, ensure that all necessary domains are included in the CSP, particularly for authentication services (e.g., `*.supabase.co`, `*.supabase.in`). Also, include appropriate directives like `connect-src` and `frame-src` to allow authentication flows to work correctly.
13. An unused utility file (`web/utils/utils.py`) existed, containing functions for API key validation, input sanitization, query logging, and Markdown-to-HTML formatting, which were not utilized elsewhere in the codebase.
14. Some frontend elements defined in `web/templates/index.html` (e.g., password visibility toggles, character counter) lacked corresponding JavaScript implementation in `static/js/app.js`, rendering them non-functional.
15. The test file `web/tests/test_search.py` is structured as a procedural script using `print` statements for verification, rather than utilizing `unittest` assertions like `web/tests/test_auth.py`. Relative imports were added for better path handling.
16. Numerous Windows-specific `desktop.ini` files were found across various project directories and subsequently removed.
17. The `execute_command` tool may interpret commands using PowerShell even if the default system shell is `cmd.exe`. For deleting potentially protected files like `desktop.ini`, the PowerShell command `Remove-Item -Path <filepath> -Force` proved effective.
18. The loading overlay feature, including its HTML element (`#loading-overlay`) and associated JavaScript logic in `web/templates/index.html`, was removed to simplify the initial page load process.
19. The sidebar structure in `web/templates/index.html` was corrected to include the main sidebar container (`<div class="col-lg-3 col-md-4 sidebar h-100">`), header, global category selector, and properly nested FAQ sections within `<nav>` elements. Stray tags were also removed.
20. The data processing script (`web/services/data_processing.py`), when run as a module (`python -m web.services.data_processing`), successfully generates embeddings using the local `all-mpnet-base-v2` model and creates the FAISS index (`web/processed_data/faiss_index.bin`). The significant processing time observed is expected for this task, especially on CPU.
21. RAG Prompt Complexity: Experimentation showed that overly complex prompt structures (e.g., detailed multi-section formats with strict instructions) can sometimes lead to worse performance or less desirable output compared to simpler, more direct prompts. Finding the right balance between guidance and complexity is crucial for optimal RAG performance.
22. Pharmacovigilance-Specific Prompts: For specialized domains like pharmacovigilance, structured prompts with clear response formats (DIRECT ANSWER, DETAILED ANALYSIS, SOURCES, SUMMARY) can improve response quality when:
   - Medical terminology is required
   - Citations are important
   - Standardized reporting formats are needed
   - The context contains technical regulatory content
23. Standard CSS Animations: Basic visual enhancements like fade-ins (`@keyframes fadeIn`) and hover effects (`transition`, `transform: scale()`, `transform: translateY()`, `box-shadow`) can be effectively implemented using standard CSS properties without requiring external animation libraries like Animate.css or GSAP, keeping dependencies minimal.
24. Skeleton Loaders for Chat: Instead of a simple typing indicator, a skeleton loader provides better visual feedback while waiting for a bot response. This involves:
    - **CSS:** Defining styles for skeleton elements (`.skeleton`, `.skeleton-avatar`, `.skeleton-line`) and a shimmer animation (`@keyframes shimmer`) using `background: linear-gradient`. Container styles (`.skeleton-message-container`) mimic the actual message bubble's appearance (padding, border-radius, shadow, background).
    - **JS:** Modifying the function that shows the loading state (`showTypingIndicator`) to dynamically create the HTML structure for the skeleton (e.g., divs for avatar and multiple lines of varying widths) and append it to the message container. The removal function (`hideTypingIndicator`) can remain the same if it targets the element by a consistent ID (`#typing-indicator`).
25. Modern Box Shadows: Achieving a softer, more modern shadow effect involves using lower opacity colors (e.g., `rgba(0, 0, 0, 0.06)` instead of `rgba(0, 0, 0, 0.1)`), slightly larger blur radius, and potentially a small spread radius in the `box-shadow` property. Applying these consistently across elements like containers, buttons, and pop-ups creates a cohesive, less harsh visual depth. Example: `box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);`
26. Sidebar Organization: Improving sidebar clarity involves:
    - **CSS:** Adding visual separators like `border-top` with subtle colors (`rgba(255, 255, 255, 0.15)`) between distinct sections (header, global category, FAQ groups). Adjusting `margin-bottom` and `padding-top` on section containers/headings enhances vertical spacing. Increasing `gap` in flex containers (like `.nav-pills`) improves spacing between items. Styling icons (`<h4> i`) placed next to headings.
    - **HTML:** Adding relevant icons (e.g., `<i class="bi bi-journal-text"></i>`) directly within heading tags (`<h4>`) for thematic representation.
27. Input Area Loading State: Providing feedback during asynchronous operations (like API calls) enhances UX:
    - **JS:** In the event handler (`sendQuery`), before the `fetch` call:
        - Store references to the button's icon and text content.
        - Create a spinner element (`<span class="spinner-border...">`).
        - Disable the input field (`queryInput.disabled = true`) and button (`sendButton.disabled = true`).
        - Replace the button's icon with the spinner (`button.replaceChild(spinner, icon)`).
        - Update the button's text content (`buttonTextNode.textContent = ' Sending...'`).
    - **JS:** Use a `finally` block attached to the `fetch` promise chain to ensure the UI state is always restored:
        - Re-enable the input and button.
        - Replace the spinner with the original icon.
        - Restore the original button text.
        - Clear the active request tracker (`activeRequest = null`).
28. Responsive Offcanvas Sidebar (Bootstrap): To make a sidebar collapsible on smaller screens:
    - **HTML:**
        - Add a mobile-only header (`<nav class="navbar d-lg-none">`) containing a toggle button (`<button class="navbar-toggler" data-bs-toggle="offcanvas" data-bs-target="#sidebarOffcanvas">`).
        - Wrap the sidebar content within Bootstrap's offcanvas structure (`<div class="offcanvas offcanvas-start d-lg-none" id="sidebarOffcanvas">...</div>`). Include `.offcanvas-header` and `.offcanvas-body`. Apply the original `.sidebar` class to the `.offcanvas-body` to inherit styles.
        - Add responsive display classes to the original sidebar container (`d-none d-lg-block`) to hide it below the `lg` breakpoint.
        - Adjust the main content area's column class to take full width below the breakpoint (e.g., `col-12 col-lg-9`).
        - **Note:** Duplicating the entire sidebar content within the offcanvas body is simpler initially but less maintainable than dynamically moving/styling a single sidebar element. If duplicating, ensure elements needing JS interaction have unique IDs or are selected carefully (e.g., using `querySelectorAll` and context).
    - **JS:**
        - Select duplicated elements in the offcanvas using their specific IDs (e.g., `#global-category-offcanvas`).
        - Update event handlers to listen to events on *both* the regular and offcanvas elements (e.g., attach the `handleGlobalCategoryChange` listener to both select elements).
        - Ensure functions like `updateAuthStatus` update the corresponding elements in both sidebars.
        - Add logic to hide the offcanvas when an action is taken within it (e.g., `sidebarOffcanvas.hide()` in `handleFaqClick` if the clicked button is inside the offcanvas).
    - **CSS:**
        - Style the mobile header (`.navbar.d-lg-none`) and its elements (toggler, brand).
        - Style the offcanvas container (`.offcanvas.offcanvas-start`) and header (`.offcanvas-header`) to match the desired theme (e.g., sidebar background color).
    - **Correction (Skeleton Order):** To prevent a race condition where the skeleton loader might appear before the user message (due to `addMessage` using `requestAnimationFrame`), wrap the DOM appending logic within `showTypingIndicator` also inside `requestAnimationFrame`. This ensures both updates are processed in the same rendering cycle, maintaining the correct visual order.
29. Enhancing Welcome Message: Instead of a full hero section, the initial welcome message can be made more engaging by adding relevant icons (e.g., `<i class="bi bi-question-circle me-2 text-primary"></i>`) directly within the list items (`<li>`) that describe the chatbot's capabilities in `web/templates/index.html`. Using Bootstrap text color classes (e.g., `text-primary`, `text-success`) adds visual distinction.
30. Polishing Sidebar Header: To improve the visual organization of the sidebar header:
    - **HTML:** Add an icon (e.g., `<i class="bi bi-shield-shaded me-2"></i>`) within the main title heading (`<h3>`). Wrap the authentication status elements (span, buttons) in a dedicated `div` (e.g., `<div class="auth-status-container mt-2">`).
    - **CSS:** Style the title icon (`.sidebar-header h3 i`). Adjust `margin-bottom` on the title (`h3`) and tagline (`p.text-muted`) for better spacing. Apply styling to the auth container (`.auth-status-container`) like a subtle `background-color` (`rgba(0, 0, 0, 0.1)`), `padding`, and `border-radius` to visually group the auth elements. Adjust text color within the auth container if needed (`.auth-status-container .small`).
    - **Animation:** Add a simple fade-in animation (`@keyframes headerFadeIn`) using `opacity` and `transform: translateY(-10px)`. Apply this animation to the `.sidebar-header` selector and set its initial `opacity` to `0` to ensure the animation is visible on load.
31. Glassmorphism Effect (CSS): Applying a "glass" effect to elements like modals involves combining several CSS properties:
    - `background`: Use `rgba()` for a semi-transparent background color (e.g., `rgba(255, 255, 255, 0.65)`).
    - `backdrop-filter`: Apply `blur()` (e.g., `blur(10px)`) to create the frosted glass look. Adding `saturate()` (e.g., `saturate(180%)`) can enhance the effect. Remember the `-webkit-backdrop-filter` prefix for Safari compatibility.
    - `border`: A subtle border (`1px solid rgba(209, 213, 219, 0.3)`) helps define the edges.
    - `box-shadow`: A soft shadow (`0 8px 32px 0 rgba(31, 38, 135, 0.15)`) adds depth.
    - `border-radius`: Rounded corners are typical for this style.
    - `overflow: hidden`: Necessary on the container if child elements might otherwise overflow the rounded corners.
32. CSS Transitions for Modals/Tabs: Smooth transitions enhance user experience:
    - **Modal Appearance:** Apply `transition: transform 0.3s ease-out;` to the `.modal-dialog` class.
    - **Tab Switching:**
        - Apply `transition` to `.nav-tabs .nav-link` for hover/active states.
        - Apply `transition: opacity 0.3s ease-in-out, transform 0.3s ease-in-out;` to the `.tab-pane` class.
        - Style inactive tabs (`.tab-pane:not(.active)`) with `opacity: 0`, `transform: translateX(10px)`, `position: absolute`, `width: calc(100% - padding)`, and `pointer-events: none` to create a fade/slide effect without layout shifts.
    - **Form Fields:** Apply `transition: border-color 0.3s ease, box-shadow 0.3s ease;` to `.form-control` for smooth focus effects.
33. Bootstrap Floating Labels: Implementing floating labels requires specific HTML structure and CSS:
    - **HTML:** Wrap the `<input>` and `<label>` within a `.form-floating` div. The `<input>` must have a `placeholder` attribute (even if empty) and must come *before* the `<label>`.
    - **CSS:** Bootstrap handles the basic floating behavior. Customizations involve styling the `.form-floating` container, adjusting padding on the `.form-control` (`padding-top`, `padding-bottom`), styling the `label` itself, and defining the transformed state (`:focus ~ label`, `:not(:placeholder-shown) ~ label`) using `transform: scale() translateY() translateX()`. Icons can be included within the label text. Standard `.form-text` elements don't work well visually and should be placed outside the `.form-floating` div if needed.
34. Enhancing Visual Hierarchy (Forms/Modals):
    - **Button Prominence:** Use Bootstrap sizing classes (`.btn-lg`) and utility classes (`.fw-bold`) on primary action buttons. Add custom CSS for subtle `letter-spacing`, `box-shadow`, and hover effects (`transform: translateY()`, increased `box-shadow`) to make them stand out more.
    - **Spacing:** Utilize Bootstrap margin utilities (e.g., `mb-4` instead of `mb-3`) on form elements (`.form-floating` or wrapper divs) to increase vertical space and improve readability.
    - **Tab Distinction:** Instead of background colors, use border properties for clearer active tab indication. Apply `border-bottom: 3px solid transparent` to all tab links, then change `border-bottom-color` to a contrasting color (e.g., `#FFFFFF`) only for the `.active` tab link. Dimming the text color (`rgba(255, 255, 255, 0.7)`) of inactive tabs further enhances the distinction.
35. Clearer Validation States (CSS): Beyond Bootstrap's default red border for `.is-invalid`, enhance clarity by:
    - Adding a subtle background color to the invalid input (e.g., `background-color: rgba(255, 220, 220, 0.7)`).
    - Customizing the focus state for invalid inputs (`.is-invalid:focus`) with a corresponding colored `box-shadow` (e.g., `rgba(220, 53, 69, 0.35)`).
    - Ensuring the `.invalid-feedback` text color is explicitly set and potentially increasing `font-weight` for emphasis.
36. HTML Comment Syntax: It's crucial to use the correct comment syntax in HTML files (`<!-- Comment text -->`). Using syntax from other languages or template engines (like `{/* Comment text */}` which might be valid in Jinja2 or React JSX) directly in an HTML file will cause the comment delimiters and text to be rendered literally by the browser, leading to unexpected visual output.
37. CSS Gradients & Contrast Adjustment: Applying a `linear-gradient` background (e.g., `linear-gradient(135deg, rgba(46, 139, 87, 0.75), rgba(30, 95, 140, 0.75))`) can create a visually appealing effect aligned with theme colors. When using gradients (especially semi-transparent ones with `backdrop-filter`), it's essential to adjust the colors of overlying elements (like text labels, input backgrounds, borders, validation messages) to ensure sufficient contrast and readability. This might involve making text white, adjusting input background opacity, or using different colors for validation states (e.g., using yellow for warnings instead of red if it contrasts better with the gradient).
38. CSS Nesting: Refactoring CSS using native nesting (e.g., `.parent { .child { ... } }`) improves code organization and readability by grouping related styles, reducing selector repetition, and mirroring the HTML structure. This is now widely supported in modern browsers.
39. CSS Scroll Snap: Applying `scroll-snap-type: y mandatory;` to a scrollable container (like `.messages`) and `scroll-snap-align: start;` to its children (`.message`) creates a smoother, more controlled scrolling experience where items snap into place, which is particularly effective for chat interfaces or item lists. `scroll-behavior: smooth;` enhances this effect.
40. Enhanced Hover Effects (CSS): Combining multiple CSS properties like `transform` (e.g., `perspective`, `rotateX`, `rotateY`, `scale`, `translateY`), `box-shadow`, and `transition` can create engaging micro-interactions. For example, a 3D tilt effect on FAQ buttons or a lift-and-scale effect on the send button provides clear visual feedback on hover. Using `will-change: transform, box-shadow;` can help optimize performance for these animations.
41. View Transitions API (Basic Implementation): The `document.startViewTransition(callback)` function allows wrapping DOM updates (like appending a new chat message) to create animated transitions between the old and new states. This requires adding `view-transition-name` CSS properties to the elements involved (e.g., `.message`).
42. View Transitions Compatibility: It's crucial to check for browser support using `if (document.startViewTransition)` before calling the function to ensure graceful degradation on unsupported browsers.
43. View Transitions with Libraries (Bootstrap Tabs): Integrating View Transitions with UI libraries that manage their own DOM updates (like Bootstrap tabs) involves listening for the library's events (e.g., `show.bs.tab`) and triggering `document.startViewTransition`. However, the visual effect might be limited unless the library allows fine-grained control over the DOM changes within the transition's callback, or if distinct `view-transition-name` properties are applied to elements that change state during the library's update.
44. Scroll-Driven Animations (CSS): CSS Scroll-Driven Animations (`@scroll-timeline`, `animation-timeline`, `animation-range`) allow linking an animation's progress directly to the scroll position of a container.
45. Defining Scroll Timelines: The `@scroll-timeline <name> { source: selector(<selector>); orientation: block | inline; }` rule defines a named timeline linked to the scroll progress of a specific element (`source`). `orientation: block` is used for vertical scrolling.
46. Applying Scroll-Driven Animations: An element's `animation` property defines the `@keyframes` to use, and `animation-timeline: <timeline-name>;` links it to the defined scroll timeline.
47. Animation Range: The `animation-range: <start> <end>;` property controls *when* the animation plays relative to the element's visibility within the scroll container (e.g., `entry 20% cover 50%` starts the animation when the element is 20% visible from the bottom and finishes when it's 50% covered by the top edge).
48. Scroll Animation Optimization: Using `will-change: transform, opacity;` on elements animated by scroll can help the browser optimize rendering performance. Browser support for this feature is still evolving.
49. Styling Bootstrap Dropdowns (Glassmorphism): Applying a glass effect to a standard Bootstrap `.form-select` involves setting `background-color` to an `rgba()` value, adding `backdrop-filter: blur()`, adjusting the `border`, and setting the text `color` (e.g., `#fff`) for contrast.
50. Custom Dropdown Arrow (SVG): When using transparent backgrounds on dropdowns, the default Bootstrap arrow might become invisible. It needs to be replaced using the `background-image` property with a custom SVG data URI, ensuring the `stroke` or `fill` color in the SVG matches the desired text color (e.g., `%23ffffff` for white). Alternatively, a simple CSS arrow can be created using borders on a pseudo-element or span.
51. Dropdown Transitions: Standard CSS `transition` can be applied to properties like `background-color`, `border-color`, and `box-shadow` on the `.form-select` element (or custom trigger) to create smooth hover and focus effects. For custom dropdown animations (open/close), transitions on `opacity`, `transform` (e.g., `scaleY`), and `visibility` are effective.
52. Styling `<option>` Elements: Directly styling `<option>` elements within a `<select>` has inconsistent browser support. Complex styling or animations require replacing the native element with a custom implementation.
53. Custom Dropdown Structure (HTML): To create a stylable and animatable dropdown, replace the native `<select>` with a structure like: `div.custom-select-wrapper` containing a visually hidden `<select class="original-select">`, a `div.custom-select-trigger` (displays selected value, clickable), and a `div.custom-select-options` (holds custom option elements, initially hidden).
54. Custom Dropdown Styling (CSS): Style the `.custom-select-trigger` to look like the desired input/button. Style `.custom-select-options` with `position: absolute`, `z-index`, desired background (e.g., Glassmorphism), `border-radius`, `box-shadow`, and set initial state for animation (e.g., `opacity: 0`, `visibility: hidden`, `transform: scaleY(0.9)`). Use a class like `.open` on the options container, toggled by JS, to apply styles for the visible/animated state (`opacity: 1`, `visibility: visible`, `transform: scaleY(1)`).
55. Custom Dropdown Logic (JS):
    - Populate `.custom-select-options` by iterating through the `.original-select` options.
    - Add click listener to `.custom-select-trigger` to toggle the `.open` class on the options container and update `aria-expanded`.
    - Add click listeners to custom option elements: update trigger text, update `.original-select.value`, remove `.open` class, and crucially, `originalSelect.dispatchEvent(new Event('change', { bubbles: true }))` to ensure other JS depending on the select's change event still works.
    - Add a document click listener to close the dropdown if a click occurs outside the wrapper.
    - Implement basic keyboard accessibility (Enter/Space/Escape on trigger).
56. Custom Dropdown UX Refinement (Hide Selected): To prevent the selected item from appearing redundantly in both the trigger and the top of the open options list, applying `display: none;` to the `.selected` class *within* the `.custom-select-options` container is the standard approach. (Reverted from applying a background color).
57. Custom Dropdown Contrast: Ensure the background color of the `.custom-select-options` container is sufficiently distinct from the `.custom-select-trigger` for clarity. Using a darker or more opaque version of a theme color for the options list often works well (e.g., `rgba(33, 99, 61, 0.9)`).

## 2025-06-21
1. Reviewed and documented the structure of the 'web/' folder, which includes the Flask backend for the SFDA Copilot. Key components noted are 'api/' for core application logic, 'services/' for modular functionalities like data processing and search, 'utils/' for helper functions and clients, and configuration files like 'config.yaml' detailing server settings, rate limiting, and embedding parameters.
