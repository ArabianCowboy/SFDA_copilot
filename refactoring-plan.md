# Refactoring Plan: Data-Driven FAQ Section

This document outlines the plan to refactor the FAQ section of the SFDA Copilot application to be fully data-driven.

## 1. Centralize Category Data

The category-specific information (titles and icons) will be moved from `static/js/app.js` to `faq.yaml`. This will make `faq.yaml` the single source of truth for all FAQ-related content and presentation.

## 2. Update `faq.yaml` Structure

The `faq.yaml` file will be restructured as follows:

```yaml
# Proposed faq.yaml structure
regulatory:
  title: "Regulatory FAQs"
  icon: "bi-journal-text"
  questions:
    - text: "What are the requirements for drug registration in Saudi Arabia?"
      short: "Drug Registration"
    # ... other questions

pharmacovigilance:
  title: "Pharmacovigilance FAQs"
  icon: "bi-shield-check"
  questions:
    - text: "What are the adverse event reporting requirements in Saudi Arabia?"
      short: "Adverse Event Reporting"
    # ... other questions

veterinary:
  title: "Veterinary Medicines FAQs"
  icon: "bi-box-seam"
  questions:
    - text: "What are the data requirements for veterinary products?"
      short: "Veterinary Data Requirements"
    # ... other questions

biological:
  title: "Biological Products FAQs"
  icon: "bi-droplet"
  questions:
    - text: "What are the guidelines for biosimilar products?"
      short: "Biosimilar Guidelines"
    # ... other questions
```

## 3. Modify Frontend Logic

The `renderFaqButtons` function in `static/js/app.js` will be updated to read the `title` and `icon` from the FAQ data it receives from the API, instead of using the hard-coded objects. This will make the rendering logic completely dynamic.