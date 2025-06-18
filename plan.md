# Plan to Fix the FAQ Rendering Bug

## 1. Problem Analysis

The root cause of the bug is the unreliable method used to match FAQ data categories to their corresponding containers in the HTML. The JavaScript in `static/js/app.js` uses an attribute selector (`aria-label`) that doesn't consistently match the HTML in `web/templates/index.html` for all categories, specifically failing for "Veterinary" and "Biological" products.

## 2. Proposed Solution

I will refactor the code to use unique `id` attributes for each FAQ container. This will create a direct, unambiguous, and robust link between the JavaScript logic and the HTML elements, which is a standard best practice.

## 3. Implementation Steps

### Step 1: Modify `web/templates/index.html`

I will assign a unique `id` to each of the `<nav>` elements that act as containers for the FAQ buttons. This change will be applied to both the regular sidebar and the off-canvas mobile sidebar to ensure consistent behavior across all views.

**Example Change:**

*   **From:**
    ```html
    <nav class="nav nav-pills flex-column" aria-label="Veterinary Medicines FAQs"></nav>
    ```
*   **To:**
    ```html
    <nav class="nav nav-pills flex-column" id="veterinary-faq-container"></nav>
    ```

### Step 2: Modify `static/js/app.js`

I will update the `categorySelectorMap` in the JavaScript to use the new `id` selectors. This will allow the script to accurately find and populate each FAQ container with the correct buttons.

**Example Change:**

*   **From:**
    ```javascript
    categorySelectorMap: {
        regulatory: '[aria-label="Regulatory FAQs"]',
        pharmacovigilance: '[aria-label="Pharmacovigilance FAQs"]',
        veterinary: '[aria-label="Veterinary Medicines FAQs"]',
        biological: '[aria-label="Biological Products FAQs"]'
    },
    ```
*   **To:**
    ```javascript
    categorySelectorMap: {
        regulatory: '#regulatory-faq-container',
        pharmacovigilance: '#pharmacovigilance-faq-container',
        veterinary: '#veterinary-faq-container',
        biological: '#biological-faq-container'
    },
    ```

## 4. Benefits

*   **Robustness:** Using `id`s for selection is less prone to errors from changes in display text or other attributes.
*   **Clarity:** The code becomes more readable, and the intent is clearer.
*   **Performance:** Selecting elements by `id` is the most efficient method in modern browsers.