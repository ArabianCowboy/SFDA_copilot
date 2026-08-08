---
name: SFDA Copilot
description: A regulatory instrument that is pleasant to sit in front of — warm porcelain, aubergine ink, deep teal signal, marigold warmth, bilingual by construction.
colors:
  ink-900: "#241F2B"
  ink-700: "#463E52"
  ink-500: "#675D75"
  ink-300: "#857A94"
  paper-000: "#FFFFFF"
  paper-050: "#F4F2F0"
  paper-100: "#E9E5E1"
  rule-200: "#DCD7D1"
  rule-300: "#BFB8B0"
  teal-600: "#0F5E63"
  teal-700: "#0B4A4E"
  teal-100: "#DCECEC"
  gold-600: "#B87310"
  gold-700: "#94590A"
  gold-100: "#FAEEDA"
  alert-600: "#A8301F"
  warn-600: "#8A5A00"
typography:
  display:
    fontFamily: "Zain, Readex Pro, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "clamp(2.5rem, 7vw, 5rem)"
    fontWeight: 800
    lineHeight: 1.08
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Zain, Readex Pro, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "clamp(2rem, 3.2vw, 2.75rem)"
    fontWeight: 800
    lineHeight: 1.08
    letterSpacing: "-0.03em"
  title:
    fontFamily: "Zain, Readex Pro, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.012em"
  body:
    fontFamily: "Readex Pro, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.65
    letterSpacing: "0"
  label:
    fontFamily: "Readex Pro, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: "0.08em"
  mono:
    fontFamily: "Azeret Mono, ui-monospace, SFMono-Regular, Cascadia Mono, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0"
    fontFeature: "tabular-nums"
rounded:
  xs: "3px"
  sm: "6px"
  md: "10px"
  msg: "14px"
  lg: "16px"
  xl: "24px"
  pill: "999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "24px"
  "6": "32px"
  "7": "48px"
  "8": "64px"
  "9": "96px"
components:
  button-primary:
    backgroundColor: "{colors.teal-600}"
    textColor: "#FFFFFF"
    typography: "{typography.body}"
    rounded: "{rounded.pill}"
    padding: "16px 48px"
  button-primary-hover:
    backgroundColor: "{colors.teal-700}"
    textColor: "#FFFFFF"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-700}"
    rounded: "{rounded.sm}"
  icon-control:
    backgroundColor: "{colors.paper-000}"
    textColor: "{colors.ink-500}"
    rounded: "{rounded.pill}"
    height: "38px"
    width: "38px"
  badge-knowledge:
    backgroundColor: "{colors.gold-100}"
    textColor: "{colors.gold-700}"
    rounded: "{rounded.pill}"
    padding: "8px 16px"
  card-feature:
    backgroundColor: "{colors.paper-000}"
    textColor: "{colors.ink-700}"
    rounded: "{rounded.lg}"
    padding: "32px"
  card-feature-lead:
    backgroundColor: "{colors.gold-100}"
    textColor: "{colors.ink-700}"
    rounded: "{rounded.lg}"
    padding: "32px"
  input-text:
    backgroundColor: "{colors.paper-000}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.sm}"
    padding: "12px 16px"
  chip-suggested:
    backgroundColor: "{colors.paper-000}"
    textColor: "{colors.ink-700}"
    rounded: "{rounded.pill}"
    padding: "8px 12px"
  cite-marker:
    backgroundColor: "{colors.teal-100}"
    textColor: "{colors.teal-600}"
    typography: "{typography.mono}"
    rounded: "{rounded.xs}"
    padding: "0 0.3em"
---

# Design System: SFDA Copilot

## Overview

**Creative North Star: "The Warm Instrument"**

This is a regulatory instrument that is pleasant to sit in front of. The reader arrives mid-task with one question and a deadline, and the surface has to be sober enough to be defended to an auditor while being warm enough to spend an hour inside. The resolution of that tension is material, not decorative: a warm porcelain ground (`#F4F2F0`) under a cool radial signal-tint wash, aubergine ink instead of neutral grey so even body copy carries warmth, one deep teal that means *action* on the landing and *provenance* in the transcript, and a marigold that carries the product's character — the mascot, the lead card, the confidence marks.

The system is built in three layers and the layering is load-bearing, not organizational hygiene. Layer 1 is raw ramps (ink, paper, rule, teal, gold, status). Layer 2 is scales (spacing, type, radii, z-index, motion). Layer 3 is semantics — the only names a component is allowed to say. Dark mode overrides **primitives only**: there is not one dark-mode branch in any component file, and every Layer 3 name resolves correctly on both themes because the ramps beneath it flipped. The same discipline governs direction: the corpus is bilingual, so RTL is structural rather than a stylesheet variant, and a build test fails on any physical property that cannot mirror.

Bilingualism also chooses the type. Zain is an Arabic-first display family with a matching Latin — the right way round for a product whose corpus is written in Arabic — and Readex Pro is one variable family drawn across both scripts, so body text does not change designer between languages. Azeret Mono appears only where a machine reports a fact: page numbers, relevance scores, timestamps, citation indices. It is never a costume for "technical".

Both surfaces are now composed to this world. The landing was redesigned first; the authenticated chat app was composed against the same ramp in a following pass that did not touch the landing's composition. Two things changed in the chat that are worth stating here because they are rules, not details: an **answer is not a bubble** — a bordered card around a thousand words of prose containing its own tables and blockquotes is a box inside a box, so assistant messages sit on the page ground and only the reader's own short question stays a bubble; and **sources are one line in the transcript and a panel in the rail**, never opened unasked.

That second rule replaced an earlier one — "the source deck opens by default, because provenance is the product" — which was right about the goal and wrong about the mechanism. Sources were emitted before the model was called, so the deck could not know what the answer had done with them: a refusal arrived under eight expanded cards, each with a relevance bar, asserting evidence for an answer that had explicitly declined to give any. Opening by default turned out not to be a claim of transparency but a claim of support, made on the answer's behalf whether or not the answer made it. So: an answer's sources are the passages it actually **cited**, and an answer that cited none gets no source control at all. There was an intermediate version where a citation-free answer kept a muted "8 passages retrieved, not cited" line, on the reasoning that a reader auditing the answer still wants to see what search returned. It reads as a contradiction — the label disclaims the passages in the same breath as advertising eight of them — and under a refusal it is still evidence attached to an answer that has none. Retrieval candidates are a server-side diagnostic. The panel opens on request, which is also what keeps a two-line answer from being buried under its own provenance.

One consequence worth stating as a rule: **a source the reader cannot click is not offered**. The server decides which passages an answer is allowed to show; the browser decides which of their markers actually became buttons, and the panel shows the intersection. The two disagree in the corners of markdown — a marker inside a code span or swallowed by a link — and rather than trying to predict a parser from the server side, the surface simply never claims evidence it cannot let you check.

The relevance bar went with it. A bar whose width is `score × 100` reads as calibrated confidence in the answer; it is a weighted blend of two cosine similarities with a heuristic penalty applied, and a near-empty bar beside a passage the answer actually cited undermined a correct answer. The raw figures survive behind a collapsed disclosure labelled as ranking diagnostics — no bars, no percentages, no colour.

Iconography is inline SVG on a 16-unit grid, filled with `currentColor`, from a single registry in `web/utils/icons.py` that serves Jinja directly and the browser modules through an inlined `window.__ICONS` subset. There is no icon webfont and no emoji anywhere: a font glyph cannot be sized independently of its text and arrives as an empty box when a CDN is slow, and an emoji renders per-platform, ignores `currentColor` and cannot follow the theme.

`CATEGORY_ICONS` is the one mapping from a corpus category to its glyph. The four real categories — regulatory, pharmacovigilance, veterinary medicines, biological products — carry theirs in both places a category is named: the sidebar's FAQ headings and the composer's scope selector. The fifth entry, `all`, is a scope rather than a category and appears only in the selector, since there is no "All" FAQ group. `faq.yaml` deliberately carries **no** `icon:` field; the API derives it from the category key, because the same mapping written down twice is the same mapping drifting eventually.

**Key Characteristics:**
- Warm porcelain ground under a cool teal wash; warmth and coolness both present, neither dominant
- Aubergine ink ramp — no neutral grey anywhere in the text stack
- Soft radii (3/6/10/14/16/24px + pill) and warm-tinted shadows; the archival hairline-only world is retired
- One teal, two jobs split by surface: brand action on the landing, provenance inside the transcript
- Arabic-first display voice; one variable body family across both scripts
- Three token layers; dark mode touches only the bottom one
- Logical properties are enforced by a test, not by preference

## Colors

A warm porcelain-and-aubergine field holding two saturated voices — a deep teal that carries action and provenance, and a marigold that carries warmth and confidence.

### Primary
- **Deep Teal** (`teal-600`): The brand's action colour and the retrieval signal. On the landing it is the primary CTA fill, the feature-card icons, the link colour, the focus ring, the text selection, the caret and the scrollbar-adjacent chrome accents. Inside the chat transcript it is rationed to retrieval and citation state only — the numbered marker, the lit source card, the streaming caret, the user's own bubble, the stage dot. Its hover partner (`teal-700`) *darkens* in light mode and *lightens* in dark, because the ramp flips and the semantics do not.
- **Teal Wash** (`teal-100`): The landing's ground gradient (`radial-gradient(120% 70% at 50% -18%, …)` from the top edge), the resting fill of a citation marker, and the lit state of a source card.

### Secondary
- **Marigold** (`gold-600`): The product's warmth and its confidence signal. Sunny's eyes, mouth and antenna; the relevance bar; the knowledge-cutoff badge outline; the success toast rule; the mascot's ambient glow. `gold-700` is the variant to use when text sits on or beside a fill, including the badge's own label.
- **Marigold Tint** (`gold-100`): The lead feature card's fill and Sunny's cheeks. The only large tinted surface on the landing.

### Neutral
- **Aubergine Ink** (`ink-900` → `ink-300`): The full text ramp — primary copy and headings, secondary body, muted meta, faint labels. Warm-violet rather than grey, deliberately.
- **Warm Porcelain** (`paper-050`): The page ground.
- **Card White** (`paper-000`): Every raised surface — cards, modals, composer, sidebar, chrome buttons, status pills.
- **Sunken Porcelain** (`paper-100`): Recessed fills — the independence notice, code blocks, table headers, hover states, the cutoff notice.
- **Rule** (`rule-200`, `rule-300`): The hairline pair. `rule-200` is the default 1px border on cards, modals and dividers; `rule-300` is the stronger stroke used on input borders, blockquote rules, the paired-wordmark hairlines and the scrollbar thumb.

### Tertiary
- **Alert** (`alert-600`) and **Warn** (`warn-600`): Error text, the error toast rule, and Sunny's error face. Nothing else.

### Named Rules
**The Two Jobs Rule.** Teal is the brand's action colour on the landing (CTA and card icons) and is rationed to retrieval and citation state inside the chat transcript. A decorative teal in the transcript dilutes the one cue that says "this sentence came from a document"; a rationed teal on the landing leaves the page with no action colour. Which job applies is decided by surface, never by taste.

**The Primitives-Only Dark Rule.** Dark mode overrides Layer 1 primitives and nothing else. A `[data-bs-theme="dark"]` branch inside a component means the primitive ramp is wrong — fix the ramp. The teal ramp lifts to `#4FC2C8` in dark because `#0F5E63` on `#191420` is roughly 2.1:1 and unreadable; that is a ramp decision, not a component decision.

**The Semantic-Names-Only Rule.** Components reference Layer 3 names (`--bg-surface`, `--fg-muted`, `--signal`, `--confidence`, `--hairline`). Reaching for a primitive in a component file means the semantic layer is missing a name; add the name.

**The Warm Shadow Rule.** Shadows are tinted with the ink hue (`rgb(36 31 43 / …)`), never neutral grey. A grey shadow on a warm ground reads as dirt.

## Typography

**Display Font:** Zain (falling back to Readex Pro, then system sans)
**Body Font:** Readex Pro (variable, 200–700, drawn across Latin **and** Arabic)
**Label/Mono Font:** Azeret Mono (400/500)

**Character:** An Arabic-first display voice over a bilingual variable body — modern, open, unmistakably not the bookish serif that a "warm" palette usually invites. The mono is a reporting instrument, never a mood.

### Hierarchy
- **Display** (800, `clamp(2.5rem, 7vw, 5rem)`, 1.08, −0.03em): The wordmark only. The clamp floor is set by the *longer* script — the Arabic wordmark runs about 1.4× the inline length of the English one, so the minimum is tuned to keep it on one line at 390px.
- **Headline** (800, `clamp(2rem, 3.2vw, 2.75rem)`, 1.08, −0.03em): Section headings on the landing.
- **Title** (700, 1.25rem/1.5rem, 1.3, −0.012em): Card headings, modal titles, sidebar title. The lead card's heading steps up one rung (1.5rem) rather than getting its own token.
- **Body** (400, 1.0625rem/17px, 1.65): All prose. The reading measure is 68ch (`--measure`); the hero lead is tightened to 54ch and the independence notice to 70ch.
- **Label** (500, 0.75rem, +0.08em, uppercase): Section eyebrows inside the FAQ rail, table headers, stage lines, composer labels, source categories.
- **Mono** (400, 0.75rem, tabular figures): Machine-reported facts only — page numbers, relevance scores, timestamps, citation indices, stream notes.

### Named Rules
**The Joined-Script Rule.** Negative letter-spacing shatters Arabic glyph joining. Every tracking token zeroes under `[dir="rtl"]`, a blanket `letter-spacing: normal` catches any hardcoded value, and the leading opens up (body 1.65 → 1.85, tight 1.08 → 1.25, snug 1.3 → 1.45). Uppercasing is also switched off in RTL: Arabic has no case, so the transform does nothing while the tracking that accompanies it breaks joins. Small labels keep their role through weight and colour instead.

**The Interpolate-Between-Tokens Rule.** Fluid type clamps interpolate between ramp tokens (`clamp(var(--fs-400), 1.5vw, var(--fs-500))`), never between literals. A clamp written with raw rem values is off the scale by construction.

**The Mono-Means-Measured Rule.** Azeret Mono marks a value a machine produced. Numbers that carry meaning also get `font-variant-numeric: tabular-nums` so digits do not jitter between streaming frames, and page numbers and scores are held `direction: ltr; unicode-bidi: isolate` so bidi cannot reorder them inside an Arabic answer.

## Layout

The landing is a single centred column capped at 1180px (`--page-max`), with a fluid page edge of `clamp(20px, 5vw, 56px)` and a shared `clamp(16px, 4vw, 48px)` gutter for app surfaces. The document scrolls; only the authenticated chat shell pins itself to 100vh so its composer stays put while the transcript scrolls.

Spacing is a 4px base scale (4/8/12/16/24/32/48/64/96). No raw pixel margins are authored anywhere in the landing; the only literal lengths in the stylesheets are optical constants (hairline widths, dot sizes, blur radii, the mascot's sizing clamps).

The feature grid is one column by default, two at 640px, three at 1000px — and at three columns the coverage card spans two, because it carries the corpus claim and a row of five identical boxes says nothing about which one matters. The chat shell adds a 240–320px rail as a real grid column at 1200px. The rail carries the mascot until an answer's sources are opened, then the source panel takes the column and the mascot steps aside; below 1200px the same panel becomes a modal bottom sheet, because there is no second column to put it in and it would otherwise cover the answer without saying so. Breakpoints are content-driven values, not a framework's named tiers.

**The Logical-Properties Rule.** Physical properties that cannot mirror (`margin-left`, `padding-right`, `left`, `text-align: left`, `border-left`) are banned and `web/tests/test_css_contract.py` fails the build on them; the five shipped stylesheets currently carry zero violations. Where CSS has no logical equivalent — `translateX` inside a keyframe — the direction multiplier `--flip` (1 in LTR, −1 in RTL) goes inside the transform: `translateX(calc(-12px * var(--flip)))`. Overlays are placed in a shared grid cell with `align-self`, not with absolute offsets, so they mirror for free.

## Elevation & Depth

Hybrid, and deliberately so. Structure at rest is carried by hairlines and tonal layering — porcelain page, white surface, sunken fill, 1px rule — and shadow is spent on things that are genuinely lifted or genuinely responding: modals, dropdown menus, toasts, the floating jump pill, a card under the cursor. The landing's own ground is a cool radial wash from the top edge rather than a flat fill, which gives the page depth before any element casts anything.

### Shadow Vocabulary
- **Resting whisper** (`0 1px 2px rgb(36 31 43 / .05)`): Small floating chrome that must read as detached but not lifted — the mascot's status pill.
- **Hover lift** (`0 4px 14px rgb(36 31 43 / .07)`): A card responding to the cursor, and the jump-to-latest pill.
- **Menu** (`0 12px 32px rgb(36 31 43 / .10)`): Dropdown surfaces.
- **Overlay** (`0 24px 60px rgb(36 31 43 / .16)`): Modals and toasts.
- **Coloured CTA lift** (`0 6px 18px rgb(var(--signal-rgb) / .22)`, `0 10px 26px / .28` on hover): The primary action only. It is the one element on the landing allowed to look inviting.
- **Dark mode** replaces the ink tint with black at much higher alpha (.40 / .45 / .50 / .60), because a tinted shadow disappears on a dark ground.

### Named Rules
**The Earned-Shadow Rule.** Surfaces are flat at rest and lift on state. A shadow on a static element that is not floating over content is decoration; use a hairline and a tonal step instead.

## Shapes

Radii are soft and stepped: 3px on inline chips and dropdown items, 6px on inputs, small cards and quiet buttons, 10px on composer fields and menus, 14px on message bubbles, 16px on feature cards and modals, 24px reserved for the largest surfaces, and a full pill (999px) on every control that reads as a *control* — the primary CTA, the 38px icon buttons, badges, suggested-question chips, the jump pill, the relevance bar. A tool you sit in front of all day does not need to be sharp.

Two silhouettes recur. The **pill** marks anything actionable or status-bearing. The **flagged corner** marks speech: a message bubble is 14px on three corners and 6px on the corner that points back at its speaker, expressed logically (`border-start-start-radius` for the assistant, `border-start-end-radius` for the user) so it follows writing direction instead of a fixed side.

Borders are 1px hairlines by default. 2px is the system's one *meaningful* rule weight — the active tab indicator, blockquote rules, the cutoff notice, the toast's status edge — and it never appears as decoration.

## Components

### Buttons
- **Shape:** Full pill for the primary landing action and all icon chrome (999px); 6px for quiet list buttons; 10px on the composer's send button, squared on its inner edge so it welds to the input.
- **Primary (`.unified-button`):** Teal fill, white label, `--fw-display` (700) at 17px, 16px/48px padding, a coloured lift shadow, and a trailing arrow. Hover darkens the fill, raises the button 1px, deepens the shadow, and nudges the arrow 3px *toward the reading direction* (`translateX(calc(3px * var(--flip)))`) so it points onward in both scripts.
- **Ghost:** Transparent with a `rule-300` hairline; fills to sunken porcelain and darkens its text on hover.
- **Icon controls:** 38×38 circles, white fill, `rule-200` hairline, muted glyph; the border and glyph both go teal on hover. Language and theme toggles share this base.
- **Focus:** Global — `2px solid var(--focus-ring)` at 2px offset. Fields instead take a teal border plus a 3px `rgb(15 94 99 / .28)` ring.

### Chips
- **Suggested question:** Pill, white fill, `rule-300` hairline, 13px medium, muted leading glyph; hover fills to sunken porcelain, darkens the text and turns the glyph teal.
- **Knowledge badge:** Pill, marigold-tint fill with a full-strength marigold hairline and `gold-700` label. It sits beside the CTA as the second half of the hero action row.

### Cards / Containers
- **Corner Style:** 16px.
- **Background:** White on the porcelain ground; the lead card takes the marigold tint.
- **Shadow Strategy:** Flat at rest, hover lift on cursor with a 3px rise and a hairline that strengthens.
- **Border:** 1px `rule-200`. The lead card keeps the same neutral hairline rather than a gold one — full-strength gold there was the loudest line on the dark page and pulled the eye before the CTA. The fill alone carries the lead.
- **Internal Padding:** 32px.
- **Icons:** Set in the card's own colour at 1.5rem, on the card's own ground. No rounded-square icon tile — it is the most template-looking element a card can carry.

### Inputs / Fields
- **Style:** White fill, 1px `rule-300`, 6px radius (10px on the composer, welded to the send button).
- **Focus:** Teal border plus a 3px translucent teal ring; the base Bootstrap shadow is cleared first.
- **Error:** Bootstrap's invalid feedback, with the alert ramp.

### Navigation
- **Landing chrome:** A static end-aligned utility row (language toggle, theme toggle) inside the same 1180px measure as the content — deliberately in flow rather than absolutely positioned, because the page scrolls.
- **Tabs (auth modal):** Borderless links in muted ink; the active tab takes primary ink and a 2px teal underline.
- **Footer:** A top hairline, the independence notice on a sunken fill at 70ch, then the builder's colophon links in secondary ink going teal on hover.

### Sunny (signature component)
The mascot is a generated SVG, not an asset. Every fill in it references a `--sunny-*` variable that resolves to a semantic token: teal shell (`--signal`), aubergine visor, marigold eyes, mouth and antenna (`--confidence`), marigold-tint cheeks, white core. Because of that, **a theme change and a state change are the same operation** — searching reassigns `--sunny-eye` to `--signal`, retrieved returns it to `--confidence`, error reassigns eye and mouth to `--danger`, and dark mode needs no rule at all. Sunny's face is the retrieval progress indicator: the antenna carries the retrieval signal, the eyes carry confidence.

On the landing Sunny is the page's only image, sized `clamp(150px, 24vw, 232px)`, floating on a 6s loop above a **warm** blurred glow (marigold, not teal — the glow is atmosphere around a character, and teal is spoken for). He mirrors under RTL (`scaleX(-1)`) so he still faces into the text; he carries no glyph children, so nothing needs un-mirroring. Motion is CSS keyframes rather than SVG SMIL, specifically so the global `prefers-reduced-motion` rule can reach it.

**The JS-Arms-The-Hidden-State Rule.** The card reveal's hidden state (`.animate-card.is-armed`) is applied by `effects.js` at runtime and is never authored in the HTML or triggered by CSS alone. If the module fails to load or the observer never attaches, the cards are simply visible. Verified with JS disabled and with the app module aborted. Any future scroll-reveal follows the same shape: no content is hidden by a stylesheet on the promise that a script will unhide it.

## Do's and Don'ts

### Do:
- **Do** put every new colour in a Layer 1 ramp, give it a Layer 3 semantic name, and let components reference only the semantic name.
- **Do** flip primitives — and only primitives — for dark mode; if a component needs a dark branch, the ramp is wrong.
- **Do** use logical properties for everything, and reach for `calc(x * var(--flip))` when the property has no logical form.
- **Do** spend teal on the primary action and card icons on the landing, and ration it to retrieval and citation state inside the transcript.
- **Do** write fluid type as clamps between ramp tokens (`clamp(var(--fs-400), 1.5vw, var(--fs-500))`).
- **Do** set the display clamp's floor by the longer script — the Arabic wordmark, not the English one.
- **Do** use Azeret Mono with tabular figures for machine-reported values, and isolate them `direction: ltr` when they sit inside Arabic prose.
- **Do** tint shadows with the ink hue in light mode and swap to black at high alpha in dark.
- **Do** arm scroll-reveal hidden states from JS at runtime, so a dead module leaves content visible.
- **Do** bump `asset_version` in `web/api/app.py` (currently `"warm5"`) in any commit touching CSS or JS.
- **Do** add a new glyph to `web/utils/icons.py` once, and to `RUNTIME_ICON_NAMES` as well if a browser module draws it.
- **Do** carry the independence notice on every surface; the landing footer holds it.

### Don't:
- **Don't** author a physical property that cannot mirror. `test_css_contract.py` fails the build; the five stylesheets are at zero violations and stay there.
- **Don't** apply negative letter-spacing or `text-transform: uppercase` under `[dir="rtl"]` — both break Arabic glyph joining or do nothing while breaking it.
- **Don't** reach for a primitive token inside a component file; add the missing semantic name instead.
- **Don't** state a guideline count, or any corpus figure, anywhere in copy. The corpus changes; the number goes stale on the next update.
- **Don't** wrap a card icon in a rounded-square tile, or repeat the same idea as both a mascot and a stock illustration on one page.
- **Don't** put a neutral grey shadow on the warm ground, or a shadow on anything that is flat and not responding to state.
- **Don't** use the 2px rule weight decoratively — it is reserved for marks that carry meaning.
- **Don't** hide content in CSS on the assumption a script will reveal it.
- **Don't** reach for an emoji, a webfont glyph, or a second icon style. Every glyph is a filled 16-unit path in `icons.py`, and a set that mixes stroke weights or sources reads as assembled rather than drawn.
- **Don't** put a bordered card around an assistant answer, or give a shrink-to-fit flex parent a `inline-size: 100%` child — a percentage width contributes nothing to intrinsic sizing, which is exactly how the source deck once resolved to zero by zero on wide screens. The rule outlived the deck: the source panel nests groups inside lists inside a flex column, so it is the same shape of mistake waiting to be made again, and `test_source_panel.py` asserts a real bounding box for a passage at 1600px for that reason.
- **Don't** revive ambient decoration on every surface at once (drifting orbs, conic rings, canvas particle fields, per-element parallax). Motion marks a state change; that is its whole job.
