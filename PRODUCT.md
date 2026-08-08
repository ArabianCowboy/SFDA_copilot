# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

No single primary user. Four professional groups carry roughly equal weight — the
category selector exists precisely because the audience is plural:

- **Regulatory affairs professionals** — preparing registrations, submissions, and
  compliance checks.
- **Pharmacovigilance / drug safety teams** — adverse event reporting and ongoing
  safety obligations.
- **Clinical trial sponsors** — navigating trial approval and oversight requirements.
- **Pharmaceutical companies operating in Saudi Arabia** — the organizations the
  above roles work inside.

**A second, equally real audience:** people evaluating the builder's AI engineering
work — prospective clients, peers, recruiters. This product is simultaneously a
working tool and proof of capability, and future work must satisfy both without
diluting either. Do not treat the showcase reading as secondary, and do not let it
override task efficiency for the professional reading.

**Situation:** a user arrives mid-task with one specific regulatory question and
needs an answer they can defend to a colleague or an auditor. They are not browsing.
The corpus is mixed Arabic/English and so is the readership.

## Product Purpose

SFDA Copilot answers questions about Saudi pharmaceutical regulation from the
official SFDA guideline corpus, and shows its work. It exists because the
regulations are long, scattered across dozens of documents, and expensive to search
by hand; the product collapses that search into a question and an answer that
carries its sources with it.

Success is a professional getting a correct, attributable answer faster than they
could have found it themselves — and being able to verify it without leaving the
answer.

## Positioning

The differentiator is **traceable answers, not just fast ones**. Every claim carries
a numbered citation that resolves to the source document, its page, and its hybrid
relevance score — including the semantic/lexical split that produced it. A
general-purpose assistant answering the same question cannot show that provenance,
and a keyword search over the same PDFs cannot produce the answer.

Supporting mechanisms, all confirmed in the shipped product:

- **Hybrid retrieval** — FAISS semantic search fused with TF-IDF lexical search,
  weighted 0.5/0.5, over the SFDA corpus. Neither method alone.
- **Local embeddings** (`all-mpnet-base-v2`, 768d) rather than a hosted embedding
  API — a deliberate cost, domain-specificity, and privacy decision.
- **Genuinely bilingual** — EN/AR with full RTL, including Arabic queries answered
  in Arabic. Not a translated shell over an English product.
- **Streaming with visible retrieval stages** — the user sees searching → passages
  found → drafting, not an undifferentiated spinner.

## Operating Context

- Users log in before chatting; the chat is gated, the landing page is not. Two
  distinct surfaces live in one page — an unauthenticated landing view and an
  authenticated app view.
- A query is scoped by category before it is asked: All, Regulatory,
  Pharmacovigilance, Veterinary Medicines, Biological Products.
- FAQ entries in the sidebar seed common questions, so a first session often begins
  by clicking rather than typing.
- Answers stream token-by-token over SSE. Reading happens *while* the answer is
  still being written, and users scroll back mid-stream to re-read.
- Users check citations. Provenance is used, not decorative.
- Profiles carry full name, organization, specialization, and a theme preference —
  the product knows something about who is asking.
- Desktop and mobile are both real. The sidebar becomes an offcanvas drawer below
  the `lg` breakpoint; the mascot rail is hidden below `xl`.

## Capabilities and Constraints

**Confirmed capabilities:** streaming chat with cancel; numbered citations with
source, page, and relevance score; category-scoped hybrid search; EN/AR language
toggle with server-rendered strings; Supabase email/password auth; user profiles;
light/dark theme with system-preference detection; FAQ browser; a demo mode
(`?testing=true`) that runs the full experience against mock services without an
OpenAI key or a built index.

**Durable technical constraints:**

- **No bundler, no `node_modules`.** Browser-native ES modules; Bootstrap 5.3,
  DOMPurify, marked, and supabase-js load from jsDelivr at pinned versions.
  `package.json` exists so `npm audit` covers what users actually run, and its
  versions must stay in sync with the CDN URLs in the templates and JS modules.
  Icons are **not** a dependency: every glyph is inline SVG from
  `web/utils/icons.py`, so there is no icon webfont to download or to fail.
  Because static imports cannot carry a cache-buster, the page emits an
  `importmap` that versions every module URL from the same `ASSET_VERSION`.
- **Single worker in production.** Conversation history lives in a process-local
  store because Flask writes `Set-Cookie` before a streaming body iterates. More
  than one worker splits conversations.
- **The stream must not be buffered.** Any proxy in front of the app has to disable
  response buffering or streaming is defeated entirely.
- **CSS must mirror.** A test fails the build on physical properties that cannot
  mirror under RTL; logical properties are mandatory, not preferred.
- **Frozen strings.** Several UI strings are asserted verbatim by the Playwright
  suite and marked `# frozen` in `web/i18n/en.yaml`. Changing their wording is a
  test change, not just a copy change.
- **Asset versioning.** `asset_version` in `app.py` must be bumped in any commit
  touching CSS or JS, or returning users get mismatched stylesheets.
- Rate limits: 15 chat requests per minute; 200/day, 50/hour, 10/minute globally.
- Model: `gpt-4o-mini`, temperature 0.1, up to 8 retrieved passages as context.

**Terminology:** the four corpus categories are named exactly as above.
"Guidelines" (not "documents" or "articles") is the product's word for its sources.
"Citation" refers to the numbered marker; "source" refers to what it resolves to.

**Explicitly undecided:** nothing about the corpus count may be stated as a figure
(see Evidence on Hand).

## Brand Commitments

**Binding:**

- **The name "SFDA Copilot" is fixed.** Renaming is off the table, including in
  light of the unaffiliated status below. This means copy carries a permanent
  obligation: the name may contain "SFDA", but no surface may imply endorsement,
  partnership, or official status.
- **Full EN/AR parity with true RTL mirroring.** Every surface ships bilingual.
  No English-only feature, no Arabic afterthought.
- **Author attribution stays.** The AI Fouda Hub and LinkedIn links remain on the
  landing page as the builder's byline.

**Present but not binding:**

- **The robot mascot.** It gives the page life and is welcome to keep doing so, but
  it is not mandatory and must never be a blocker or an obligation forced onto the
  app. Future work is free to reinterpret it, lighten its presence, or find a more
  creative expression of the same warmth. Treat it as an opportunity, not a fixture.

**Voice, as shipped:** direct and professional, occasionally warm — status text
reads "Ready to help" and "Here's what I found", not "Awaiting input". The warmth
lives in the assistant's voice; the regulatory content stays sober.

## Evidence on Hand

- **112 official SFDA guideline PDFs** in `data/` — 71 regulatory, 17 veterinary
  medicines, 13 biological products and quality control, 11 pharmacovigilance.
- **A live deployment** at `sfda-copilot.aifoudahub.com` (the sole allowed CORS
  origin in `web/config.yaml`).
- **A working demo path** — `?testing=true` renders the complete experience,
  streaming and citations included, with no API key. Real, showable proof.
- **Builder attribution** — Mohamed Fouda, lead developer and designer; AI Fouda
  Hub (`aifoudahub.com`) and a LinkedIn profile.
- **A stated knowledge cutoff** — guidelines current through August 2026, disclosed
  in-product with a pointer to the official SFDA site for anything newer.

**Do not fabricate.** There are no testimonials, no named customers, no user counts,
no benchmarks, no accuracy figures, no case studies, no press, and no pricing. None
of these may be invented, implied, or illustrated with placeholders that read as
real.

**Corrected claim — the guideline count.** The landing page currently claims "over
99 SFDA guidelines" while the corpus holds 112. **Future copy must not state a
number at all**: the corpus changes and any hard figure goes stale on the next
update. Describe coverage without a count. The existing "over 99" string is stale
and should be replaced when that surface is next touched.

## Product Principles

1. **Provenance is the product.** An answer without a resolvable source is a
   liability, not a feature. Anything that makes citations harder to reach, read,
   or trust is a regression regardless of how much cleaner it looks.
2. **Never imply an authority the product does not have.** Independent of the SFDA,
   permanently. Design and copy carry the burden of that honesty because the name
   does not.
3. **Arabic is not a translation layer.** Both languages are first-class, and RTL is
   a structural requirement rather than a stylesheet variant.
4. **The reader is mid-task, not browsing.** Optimize for a professional who has one
   question and a deadline — and who will scroll, re-read, and verify while the
   answer is still streaming.
5. **Two audiences, one artifact.** It must work for the regulatory professional and
   stand as evidence of craft for the person evaluating the builder. Neither reading
   gets sacrificed for the other.

## Accessibility & Inclusion

WCAG 2.1 AA is the **aim, not a gate** — design toward it and fix violations when
found, without blocking work on formal conformance.

Product-specific needs beyond that: bidirectional text is a genuine user need, not a
localization checkbox; answers stream into a live region, so screen reader behavior
during streaming is a real design surface; and theme choice is a stored user
preference, which means both themes are shipping surfaces held to the same bar.
