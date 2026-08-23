---
name: SFDA Copilot
description: A regulatory instrument that is pleasant to sit in front of — warm porcelain, aubergine ink, deep teal signal, marigold warmth, bilingual by construction.
colors:
  ink-900: '#241F2B'
  ink-700: '#463E52'
  ink-500: '#675D75'
  ink-300: '#857A94'
  paper-000: '#FFFFFF'
  paper-050: '#F4F2F0'
  paper-100: '#E9E5E1'
  rule-200: '#DCD7D1'
  rule-300: '#BFB8B0'
  teal-600: '#0F5E63'
  teal-700: '#0B4A4E'
  teal-100: '#DCECEC'
  gold-600: '#B87310'
  gold-700: '#94590A'
  gold-100: '#FAEEDA'
  alert-600: '#A8301F'
  warn-600: '#8A5A00'
  scrim: 'rgb(36 31 43 / 0.38)'
typography:
  display:
    fontFamily: 'Zain, Readex Pro, -apple-system, BlinkMacSystemFont, sans-serif'
    fontSize: 'clamp(2.5rem, 7vw, 5rem)'
    fontWeight: 800
    lineHeight: 1.08
    letterSpacing: '-0.03em'
  headline:
    fontFamily: 'Zain, Readex Pro, -apple-system, BlinkMacSystemFont, sans-serif'
    fontSize: 'clamp(2rem, 3.2vw, 2.75rem)'
    fontWeight: 800
    lineHeight: 1.08
    letterSpacing: '-0.03em'
  title:
    fontFamily: 'Zain, Readex Pro, -apple-system, BlinkMacSystemFont, sans-serif'
    fontSize: '1.25rem'
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: '-0.012em'
  body:
    fontFamily: 'Readex Pro, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif'
    fontSize: '1.0625rem'
    fontWeight: 400
    lineHeight: 1.65
    letterSpacing: '0'
  label:
    fontFamily: 'Readex Pro, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif'
    fontSize: '0.75rem'
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: '0.08em'
  mono:
    fontFamily: 'Azeret Mono, ui-monospace, SFMono-Regular, Cascadia Mono, monospace'
    fontSize: '0.75rem'
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: '0'
    fontFeature: 'tabular-nums'
rounded:
  xs: '3px'
  sm: '6px'
  md: '10px'
  msg: '14px'
  lg: '16px'
  xl: '24px'
  pill: '999px'
spacing:
  '1': '4px'
  '2': '8px'
  '3': '12px'
  '4': '16px'
  '5': '24px'
  '6': '32px'
  '7': '48px'
  '8': '64px'
  '9': '96px'
components:
  button-primary:
    backgroundColor: '{colors.teal-600}'
    textColor: '#FFFFFF'
    typography: '{typography.body}'
    rounded: '{rounded.pill}'
    padding: '16px 48px'
  button-primary-hover:
    backgroundColor: '{colors.teal-700}'
    textColor: '#FFFFFF'
  button-ghost:
    backgroundColor: 'transparent'
    textColor: '{colors.ink-700}'
    rounded: '{rounded.sm}'
  icon-control:
    backgroundColor: '{colors.paper-000}'
    textColor: '{colors.ink-500}'
    rounded: '{rounded.pill}'
    height: '38px'
    width: '38px'
  badge-knowledge:
    backgroundColor: '{colors.gold-100}'
    textColor: '{colors.gold-700}'
    rounded: '{rounded.pill}'
    padding: '8px 16px'
  card-feature:
    backgroundColor: '{colors.paper-000}'
    textColor: '{colors.ink-700}'
    rounded: '{rounded.lg}'
    padding: '32px'
  card-feature-lead:
    backgroundColor: '{colors.gold-100}'
    textColor: '{colors.ink-700}'
    rounded: '{rounded.lg}'
    padding: '32px'
  input-text:
    backgroundColor: '{colors.paper-000}'
    textColor: '{colors.ink-900}'
    rounded: '{rounded.sm}'
    padding: '12px 16px'
  chip-suggested:
    backgroundColor: '{colors.paper-000}'
    textColor: '{colors.ink-700}'
    rounded: '{rounded.pill}'
    padding: '8px 12px'
  cite-marker:
    backgroundColor: '{colors.teal-100}'
    textColor: '{colors.teal-600}'
    typography: '{typography.mono}'
    rounded: '{rounded.xs}'
    padding: '0 0.3em'
  source-trigger:
    backgroundColor: 'transparent'
    textColor: '{colors.teal-600}'
    typography: '{typography.label}'
  source-panel:
    backgroundColor: '{colors.paper-000}'
    textColor: '{colors.ink-900}'
    padding: '16px 0'
  source-passage:
    backgroundColor: '{colors.paper-100}'
    textColor: '{colors.ink-700}'
    rounded: '{rounded.sm}'
    padding: '12px'
  source-passage-cited:
    backgroundColor: '{colors.paper-100}'
    textColor: '{colors.ink-700}'
    rounded: '{rounded.sm}'
---

STATUS: CURRENT AUTHORITY — the design system. Wins over every other document on
design, tokens and RTL presentation. Last verified against code 2026-08-23.
(The banner sits below the frontmatter, not above it: the YAML block has to be the
first thing in this file for the design tooling to parse it.)

# Design System: SFDA Copilot

## How to read a rule in this file

Every named rule below carries one of three tags. They exist because this file used to
state a build-breaking constraint and a matter of taste in the same voice, which made
the whole document read as a gate.

- **[GATE]** — a test fails. You cannot merge past it.
- **[CORRECTNESS]** — no test catches it, but breaking it breaks the product, usually
  for Arabic readers. Treat it as a gate that happens to be unautomated.
- **[TASTE]** — a considered judgement that gives the product its character. Depart from
  it deliberately and say why; nothing will stop you.

## Overview

**Creative North Star: "The Warm Instrument"**

This is a regulatory instrument that is pleasant to sit in front of. The reader arrives mid-task with one question and a deadline, and the surface has to be sober enough to be defended to an auditor while being warm enough to spend an hour inside. The resolution of that tension is material, not decorative: a warm porcelain ground (`#F4F2F0`) under a cool radial signal-tint wash, aubergine ink instead of neutral grey so even body copy carries warmth, one deep teal that means _action_ on the landing and _provenance_ in the transcript, and a marigold that carries the product's character — the mascot, the lead card, the confidence marks.

The system is built in three layers and the layering is load-bearing, not organizational hygiene. Layer 1 is raw ramps (ink, paper, rule, teal, gold, status). Layer 2 is scales (spacing, type, radii, z-index, motion). Layer 3 is semantics — the only names a component is allowed to say. Dark mode overrides **primitives only**: there is not one dark-mode branch in any component file, and every Layer 3 name resolves correctly on both themes because the ramps beneath it flipped. The same discipline governs direction: the corpus is bilingual, so RTL is structural rather than a stylesheet variant, and a build test fails on any physical property that cannot mirror.

Bilingualism also chooses the type. Zain is an Arabic-first display family with a matching Latin — the right way round for a product whose corpus is written in Arabic — and Readex Pro is one variable family drawn across both scripts, so body text does not change designer between languages. Azeret Mono appears only where a machine reports a fact: page numbers, relevance scores, timestamps, citation indices. It is never a costume for "technical".

Both surfaces are now composed to this world. The landing was redesigned first; the authenticated chat app was composed against the same ramp in a following pass that did not touch the landing's composition. Two things changed in the chat that are worth stating here because they are rules, not details: an **answer is not a bubble** — a bordered card around a thousand words of prose containing its own tables and blockquotes is a box inside a box, so assistant messages sit on the page ground and only the reader's own short question stays a bubble; and **sources are one line in the transcript and a panel in the rail**, never opened unasked.

Two rules govern how provenance is shown, and both are about not overclaiming. **An answer's sources are the passages it actually cited** — an answer that cited none gets no source control at all, because a control under a refusal is evidence attached to a claim nobody made. And **a source the reader cannot click is not offered**: the server decides which passages an answer is allowed to show, the browser decides which of their markers actually became buttons, and the panel shows the intersection. The two disagree in the corners of markdown — a marker inside a code span, or swallowed by a link — and rather than predict a parser from the server side, the surface never claims evidence it cannot let you check. Retrieval candidates that no answer used are a server-side diagnostic, not a surface.

Nothing reports a relevance score as a proportion. A bar whose width is `score × 100` reads as calibrated confidence in the answer; it is a weighted blend of two cosine similarities with a heuristic penalty applied, and a near-empty bar beside a passage the answer actually cited undermines a correct answer. The raw figures live behind a collapsed disclosure named for what they are — ranking diagnostics — with no bars, no percentages and no colour.

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

- **Deep Teal** (`teal-600`): The brand's action colour and the retrieval signal. On the landing it is the primary CTA fill, the feature-card icons, the link colour, the focus ring, the text selection, the caret and the scrollbar-adjacent chrome accents. Inside the chat transcript it is rationed to retrieval and citation state only — the numbered marker, the lit source card, the streaming caret, the user's own bubble, the stage dot. Its hover partner (`teal-700`) _darkens_ in light mode and _lightens_ in dark, because the ramp flips and the semantics do not.
- **Teal Wash** (`teal-100`): The landing's ground gradient (`radial-gradient(120% 70% at 50% -18%, …)` from the top edge), the resting fill of a citation marker, and the lit state of a source card.

### Secondary

- **Marigold** (`gold-600`): The product's warmth and its confidence signal. Sunny's eyes, mouth and antenna; the knowledge-cutoff badge outline; the success toast rule; the mascot's ambient glow. `gold-700` is the variant to use when text sits on or beside a fill, including the badge's own label.
- **Marigold Tint** (`gold-100`): The lead feature card's fill and Sunny's cheeks. The only large tinted surface on the landing.

### Neutral

- **Aubergine Ink** (`ink-900` → `ink-300`): The full text ramp — primary copy and headings, secondary body, muted meta, faint labels. Warm-violet rather than grey, deliberately.
- **Warm Porcelain** (`paper-050`): The page ground.
- **Card White** (`paper-000`): Every raised surface — cards, modals, composer, sidebar, chrome buttons, status pills.
- **Sunken Porcelain** (`paper-100`): Recessed fills — the independence notice, code blocks, table headers, hover states, the cutoff notice.
- **Rule** (`rule-200`, `rule-300`): The hairline pair. `rule-200` is the default 1px border on cards, modals and dividers; `rule-300` is the stronger stroke used on input borders, blockquote rules, the paired-wordmark hairlines and the scrollbar thumb.

- **Scrim** (`scrim`, `rgb(36 31 43 / .38)` light / `rgb(0 0 0 / .66)` dark): The dimming behind a modal surface — currently the source panel's bottom-sheet presentation. Warm ink for the same reason the shadows are: a neutral grey veil over a warm ground reads as dirt.

### Tertiary

- **Alert** (`alert-600`) and **Warn** (`warn-600`): Error text, the error toast rule, and Sunny's error face. Nothing else.

### Named Rules

**The Two Jobs Rule.** `[TASTE]` Teal is the brand's action colour on the landing (CTA and card icons) and is rationed to retrieval and citation state inside the chat transcript. A decorative teal in the transcript dilutes the one cue that says "this sentence came from a document"; a rationed teal on the landing leaves the page with no action colour. Which job applies is decided by surface, never by taste.

**The Primitives-Only Dark Rule.** `[CORRECTNESS]` Dark mode overrides Layer 1 primitives and nothing else. A `[data-bs-theme="dark"]` branch inside a component means the primitive ramp is wrong — fix the ramp. The teal ramp lifts to `#4FC2C8` in dark because `#0F5E63` on `#191420` is roughly 2.1:1 and unreadable; that is a ramp decision, not a component decision.

**The Semantic-Names-Only Rule.** `[TASTE]` Components reference Layer 3 names (`--bg-surface`, `--fg-muted`, `--signal`, `--confidence`, `--hairline`). Reaching for a primitive in a component file means the semantic layer is missing a name; add the name.

**The Warm Shadow Rule.** `[TASTE]` Shadows are tinted with the ink hue (`rgb(36 31 43 / …)`), never neutral grey. A grey shadow on a warm ground reads as dirt.

## Typography

**Display Font:** Zain (falling back to Readex Pro, then system sans)
**Body Font:** Readex Pro (variable, 200–700, drawn across Latin **and** Arabic)
**Label/Mono Font:** Azeret Mono (400/500)

**Character:** An Arabic-first display voice over a bilingual variable body — modern, open, unmistakably not the bookish serif that a "warm" palette usually invites. The mono is a reporting instrument, never a mood.

### Hierarchy

- **Display** (800, `clamp(2.5rem, 7vw, 5rem)`, 1.08, −0.03em): The wordmark only. The clamp floor is set by the _longer_ script — the Arabic wordmark runs about 1.4× the inline length of the English one, so the minimum is tuned to keep it on one line at 390px.
- **Headline** (800, `clamp(2rem, 3.2vw, 2.75rem)`, 1.08, −0.03em): Section headings on the landing.
- **Title** (700, 1.25rem/1.5rem, 1.3, −0.012em): Card headings, modal titles, sidebar title. The lead card's heading steps up one rung (1.5rem) rather than getting its own token.
- **Body** (400, 1.0625rem/17px, 1.65): All prose. The reading measure is 68ch (`--measure`); the hero lead is tightened to 54ch and the independence notice to 70ch.
- **Label** (500, 0.75rem, +0.08em, uppercase): Section eyebrows inside the FAQ rail, table headers, stage lines, composer labels, source categories.
- **Mono** (400, 0.75rem, tabular figures): Machine-reported facts only — page numbers, retrieval diagnostics, timestamps, citation indices, stream notes.

### Named Rules

**The Joined-Script Rule.** `[CORRECTNESS]` Negative letter-spacing shatters Arabic glyph joining. Every tracking token zeroes under `[dir="rtl"]`, a blanket `letter-spacing: normal` catches any hardcoded value, and the leading opens up (body 1.65 → 1.85, tight 1.08 → 1.25, snug 1.3 → 1.45). Uppercasing is also switched off in RTL: Arabic has no case, so the transform does nothing while the tracking that accompanies it breaks joins. Small labels keep their role through weight and colour instead.

**The Interpolate-Between-Tokens Rule.** `[TASTE]` Fluid type clamps interpolate between ramp tokens (`clamp(var(--fs-400), 1.5vw, var(--fs-500))`), never between literals. A clamp written with raw rem values is off the scale by construction.

**The Mono-Means-Measured Rule.** `[CORRECTNESS]` Azeret Mono marks a value a machine produced. Numbers that carry meaning also get `font-variant-numeric: tabular-nums` so digits do not jitter between streaming frames, and page numbers and scores are held `direction: ltr; unicode-bidi: isolate` so bidi cannot reorder them inside an Arabic answer.

## Layout

The landing is a single centred column capped at 1180px (`--page-max`), with a fluid page edge of `clamp(20px, 5vw, 56px)` and a shared `clamp(16px, 4vw, 48px)` gutter for app surfaces. The document scrolls; only the authenticated chat shell pins itself to 100vh so its composer stays put while the transcript scrolls.

Spacing is a 4px base scale (4/8/12/16/24/32/48/64/96). No raw pixel margins are authored anywhere in the landing; the only literal lengths in the stylesheets are optical constants (hairline widths, dot sizes, blur radii, the mascot's sizing clamps).

The feature grid is one column by default, two at 640px, three at 1000px — and at three columns the coverage card spans two, because it carries the corpus claim and a row of five identical boxes says nothing about which one matters. The chat shell adds a 240–320px rail as a real grid column at 1200px. The rail carries the mascot until an answer's sources are opened, then the source panel takes the column and the mascot steps aside; below 1200px the same panel becomes a modal bottom sheet, because there is no second column to put it in and it would otherwise cover the answer without saying so. Breakpoints are content-driven values, not a framework's named tiers.

**The Logical-Properties Rule.** `[GATE]` Physical properties that cannot mirror (`margin-left`, `padding-right`, `left`, `text-align: left`, `border-left`) are banned and `web/tests/test_css_contract.py` fails the build on them; the five shipped stylesheets currently carry zero violations. Where CSS has no logical equivalent — `translateX` inside a keyframe — the direction multiplier `--flip` (1 in LTR, −1 in RTL) goes inside the transform: `translateX(calc(-12px * var(--flip)))`. Overlays are placed in a shared grid cell with `align-self`, not with absolute offsets, so they mirror for free.

**The test does not cover everything that mirrors, and the gap has a name.** `test_css_contract.py`
scans **this repository's CSS only**. All three templates load the **LTR** Bootstrap build
(`bootstrap.min.css`, not `bootstrap.rtl.min.css`), so any Bootstrap component whose own stylesheet
uses physical properties is outside the gate entirely — the suite will be green and the Arabic
layout will still be wrong. `.form-check` is the known case, and the reason `/account` uses a
bespoke `.account-choice` class instead. **When you reach for a Bootstrap component, check it in
Arabic at a mobile width before you trust it.** A green build is evidence about our stylesheets, not
about the page. (Switching to the RTL build is not a one-line change — the repository's overrides
were written against the LTR cascade — and is tracked as a follow-up rather than assumed.)
This is collision #5 in
[`docs/ARCHITECTURE.md` → _Rules that collide_](docs/ARCHITECTURE.md#rules-that-collide),
which lists the other seven.

## Elevation & Depth

Hybrid, and deliberately so. Structure at rest is carried by hairlines and tonal layering — porcelain page, white surface, sunken fill, 1px rule — and shadow is spent on things that are genuinely lifted or genuinely responding: modals, dropdown menus, toasts, the floating jump pill, a card under the cursor. The landing's own ground is a cool radial wash from the top edge rather than a flat fill, which gives the page depth before any element casts anything.

### Shadow Vocabulary

- **Resting whisper** (`0 1px 2px rgb(36 31 43 / .05)`): Small floating chrome that must read as detached but not lifted — the mascot's status pill.
- **Hover lift** (`0 4px 14px rgb(36 31 43 / .07)`): A card responding to the cursor, and the jump-to-latest pill.
- **Menu** (`0 12px 32px rgb(36 31 43 / .10)`): Dropdown surfaces.
- **Overlay** (`0 24px 60px rgb(36 31 43 / .16)`): Modals and toasts.
- **Coloured CTA lift** (`0 6px 18px rgb(var(--signal-rgb) / .22)`, `0 10px 26px / .28` on hover): The primary action only. It is the one element on the landing allowed to look inviting.
- **Sheet** (`0 -12px 32px rgb(36 31 43 / .16)`): The bottom-sheet presentation of the source panel, and the only shadow in the set that points **up** — a sheet is lit from the page it rises over. That is why it is its own name rather than the overlay shadow used sideways.
- **Scrim** (`rgb(36 31 43 / .38)`): Not a shadow but the same job — the dimming behind the sheet, at modal z-index so nothing floats over a surface claiming `aria-modal`.
- **Dark mode** replaces the ink tint with black at much higher alpha (.40 / .45 / .50 / .60), because a tinted shadow disappears on a dark ground.

### Named Rules

**The Earned-Shadow Rule.** `[TASTE]` Surfaces are flat at rest and lift on state. A shadow on a static element that is not floating over content is decoration; use a hairline and a tonal step instead.

## Shapes

Radii are soft and stepped: 3px on inline chips and dropdown items, 6px on inputs, small cards and quiet buttons, 10px on composer fields and menus, 14px on message bubbles, 16px on feature cards and modals, 24px reserved for the largest surfaces, and a full pill (999px) on every control that reads as a _control_ — the primary CTA, the 38px icon buttons, badges, suggested-question chips, and the jump pill. A tool you sit in front of all day does not need to be sharp.

Two silhouettes recur. The **pill** marks anything actionable or status-bearing. The **flagged corner** marks speech: a message bubble is 14px on three corners and 6px on the corner that points back at its speaker, expressed logically (`border-start-start-radius` for the assistant, `border-start-end-radius` for the user) so it follows writing direction instead of a fixed side.

Borders are 1px hairlines by default. 2px is the system's one _meaningful_ rule weight — the active tab indicator, blockquote rules, the cutoff notice, the toast's status edge — and it never appears as decoration. A **meter** is not a rule and is not held to that weight: a rule marks a boundary, a meter reports a quantity that is changing while you look at it, so it is sized to be legible instead. The meter is 4px. **It currently has no instance:** the undo countdown that defined it was retired when Back became undo, so the weight is reserved rather than in use. It stays in the vocabulary because the vocabulary is what stops the next coloured edge being invented at 3px.

## Components

### Buttons

- **Shape:** Full pill for the primary landing action and all icon chrome (999px); 6px for quiet list buttons; 10px on the composer's send button, squared on its inner edge so it welds to the input.
- **Primary (`.unified-button`):** Teal fill, white label, `--fw-display` (700) at 17px, 16px/48px padding, a coloured lift shadow, and a trailing arrow. Hover darkens the fill, raises the button 1px, deepens the shadow, and nudges the arrow 3px _toward the reading direction_ (`translateX(calc(3px * var(--flip)))`) so it points onward in both scripts.
- **Ghost:** Transparent with a `rule-300` hairline; fills to sunken porcelain and darkens its text on hover.
- **Icon controls:** 38×38 circles, white fill, `rule-200` hairline, muted glyph; the border and glyph both go teal on hover. Language and theme toggles share this base.
- **New chat (`.new-chat-btn`):** A 38px pill with a plus glyph and a label, at the head of the sidebar body. It carries the **citation marker's resting treatment at control size** — `signal-tint` fill, `signal` hairline, `signal` label — because white-on-white in a column of white-on-white left the one actionable control indistinguishable from the labels around it. Not a destructive red: the system has no danger variant, and logout, the one genuinely irreversible control in the app, is a quiet ghost. **Its hover deepens to `signal-hover`; it does not invert to a solid fill the way `.cite-marker` does,** because `#send-button` is already solid teal at the same size and weight, and inverting would put a visual twin of Send in the sidebar — one that clears your work. Solid teal stays the primary action's alone. It is _labelled_ because it sits among interchangeable 38px circles. **Hidden, not disabled, until there is a conversation to end:** on a first visit the FAQ rail is what the column is for. Server-rendered `hidden`, revealed by `ui.js` — a dead module leaves no button, which is honest, because a dead module leaves no chat either. It animates in on the hidden→visible transition only, and explicitly **not** on an undo, which should read as the clear never having happened.
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
- **Sidebar tabs (`.sidebar-tabs`):** A two-segment pill — Chats | FAQ — sharing the sidebar column between the conversation list and the FAQ rail. A track at sunken porcelain with the selected segment lifted out of it in surface white, **not** an underline and **not** a teal fill. An underline reads as navigation to another page, and this switches what a panel contains without leaving anything; teal in this app means retrieval, so spending it on a view switch would put the loudest colour in the system on the least consequential control in the column, beside a New chat button that has earned a tint and a citation badge that has earned the solid fill. **The selected segment carries an inset 1px hairline ring alongside its shadow, and that ring is not decoration:** in light mode surface sits above sunken and the segment reads as raised, but the ramp inverts in dark — sunken becomes the lighter of the two and `--shadow-sm` is a 5%-opacity warm shadow that is invisible against a dark ground — which would leave text colour as the only cue. An inset ring defines the chip's edge in both directions and costs no layout, which a real border would. One tab stop for the pair (`tabindex="-1"` on the unselected one), arrow keys move between them, and ArrowRight advances to the _previous_ tab under `[dir="rtl"]` because the segments are laid out from the other end.
- **Footer:** A top hairline, the independence notice on a sunken fill at 70ch, then the builder's colophon links in secondary ink going teal on hover.

**The One Drawer Rule.** `[CORRECTNESS]` Navigation never spawns a second drawer. Below 992px the whole sidebar is one Bootstrap offcanvas, and switching between the conversation list and the FAQ rail swaps the panel's contents **in place** rather than sliding a second surface over it. Two offcanvases on a phone means two backdrops, two focus traps, and an Escape key whose meaning depends on which one won — a reader's only way out is a reload. Selecting a conversation dismisses the drawer rather than layering anything on top of it.

### Notices

Two dismissible in-transcript disclosures, sharing one shape: a sunken-porcelain fill, a `rule-200` hairline on all four sides, 3px radius, muted ink, and **an inset 2px pill on the inline-start edge** — marigold on the resumed notice, the warn ramp on the durable-history notice. That pill is the same mark the active FAQ button and the active conversation row carry, and it is a pseudo-element rather than a border for a reason worth stating: this stylesheet has three rule weights and each means something — 1px is a hairline, 2px is a mark that carries meaning, 4px is a meter — so the 3px `border-inline-start` these notices originally carried was off that vocabulary, an unclassified weight doing a job the system already had a signature for. Three components now share one mark for "this edge is telling you something".

They sit _in_ `#messages` rather than above it, so they scroll with the conversation they are about, and both are excluded from `isTranscriptTurn` so a clear, an undo or a New chat cannot sweep them into the transcript fragment. The history notice is the sharper case: it is meant to outlive a New chat, so a predicate that forgot it would delete the disclosure at exactly the moment the reader is exercising the control it describes.

They are notices, not decisions — dismissible, non-blocking, and never modal. The history notice is scoped to the **reader**, not the browser: a shared machine is the ordinary case here, and one colleague dismissing it must not mark it read for the next person to sign in.

### Conversation list (signature component)

The reader's own work, listed in the column the FAQ rail used to own alone. It shares that rail's scroll behaviour, its group-heading treatment and its active-row marker deliberately: two lists in one column that looked like two systems would make the tab switch feel like a page change.

- **The row is a grid, not a flex line,** and the middle column is why: `grid-template-columns: auto minmax(0, 1fr) auto`. A flex child defaults to `min-width: auto`, so the title would refuse to shrink below its content and shove the actions off the end of the column instead of ellipsing — the single most common way this component is built wrong.
- **The actions reserve their space at rest.** Rename and delete are `opacity: 0` until hover or focus-within, but they still occupy their grid cell, so a row does not reflow under the cursor. That costs the title ~56px of width permanently and buys no layout shift in a scrolling list, which is the right side of that trade.
- **Never hover-only.** `:focus-within` reveals them for keyboard readers, the active row shows them always, and `@media (hover: none)` pins them to 0.65 opacity — a touch device has no hover state at all and would otherwise be left with two controls it can never reach.
- **The active row takes the FAQ button's exact treatment:** `signal-tint` fill, `signal` label, and a 2px pill on the inline-start edge. Not a solid teal slab — eight of those down a scrolling column read as a navigation bar rather than as one current item, and teal here means retrieval.
- **Group headings are sticky, and opaque for that reason.** Today / Yesterday / Previous 7 days / Previous 30 days / Older, in the FAQ rail's uppercase label voice. The answer to "when was this" has to survive scrolling past its own heading, which is the whole point of grouping by day; a transparent heading lets rows scroll visibly through the text.
- **Buckets are calendar days, never elapsed hours.** An answer at 23:50 and one at 00:10 are twenty minutes apart and belong under different headings, because that is what a reader means by "yesterday". A future timestamp from clock skew is treated as today rather than dropped into Older, where a conversation the reader just had would sit at the bottom of their list.
- **Titles carry `dir="auto"` per row.** They are reader input and routinely mix scripts — an Arabic question naming an English guideline code, or the reverse. Without per-row direction detection the bidi algorithm reorders the Latin run and puts the truncation ellipsis on the wrong end. The full name and the exact timestamp live in the `title` attribute, since the visible line truncates and the heading only says which day.
- **Rename happens in the row**, as an inline field with a teal border, committed with Enter and abandoned with Escape — and that Escape is stopped from bubbling, so it does not also close the offcanvas. A reader abandoning a rename means "undo this edit", not "leave the sidebar", and having one key mean both in an order they cannot predict is the ambiguity a nested dismissible surface always brings.
- **Delete confirms inline too**, in the row's own grid: a question, a bordered danger button, and a quiet keep. A modal for one row out of a list needs neither interruption nor protected focus and would take the reader out of the column to answer a question about something in it. **The bin is the one destructive control in this column and it earns the danger colour on hover only** — a row of red bins down a scrolling list reads as a list of errors.
- **Three states, kept visually distinct:** loading, empty ("No saved conversations yet"), and unavailable-with-retry. Collapsing any two is how a sidebar ends up telling a reader they have no conversations while the store is unreachable — a claim about _them_, made on the strength of a failed request. An error with no retry is a dead end, so the retry is part of the state rather than a nicety.
- **The untitled fallback is colour only, never italic.** Arabic has no italic form, so a browser asked for one synthesises an oblique by shearing the glyphs — which breaks the connected letterforms and reads as a rendering fault rather than as emphasis. The fallback already says "Untitled conversation" in words; `--fg-faint` is the whole cue it needs, and it means the same thing in both scripts.
- **The open control is `display: contents`,** so the row's icon and title read as one target while the two action buttons stay outside it — nesting a button inside a button is invalid and leaves the inner one unreachable by keyboard. That removes the box the global focus ring would draw on, so the ring moves to the row via `:has(.history-open:focus-visible)`.
- **Not virtualised, deliberately.** A bounded 30-row page with an explicit "Load more" and a keyset cursor. The rows are short titles, and this panel is already a scroll port inside the offcanvas body, which is another one; a virtual window would unmount rows while focus and `aria-labelledby` still point at them and would fight the drawer's focus trap. `overscroll-behavior: contain` stops the wheel chaining into the drawer and then the page behind it.

**The Untitled-Is-A-State Rule.** `[CORRECTNESS]` A conversation with no name renders a localised fallback, never a blank line and never a title invented on the client. Clearing a name is a reachable action that returns the row to that state, so "untitled" has to look deliberate rather than broken.

### Source shelf (signature component)

The evidence behind one answer, read as a shelf seen edge-on. It is the product's central claim made operable, so its rules are stricter than the rest of the system's.

- **In the transcript:** one line, and only when the answer cited something. `Sources · 2 documents · 3 passages`, set as a label (12px, +0.08em, uppercase) in teal, with a chevron that mirrors on `--flip`. Both numbers count the same (cited) set, so they cannot contradict each other.
- **The shelf:** one **spine** per cited document, one **tab** per cited passage, standing on a 2px floor rule. Grouping stops being a rule imposed on a list and becomes a property of the form — a reader sees how many documents an answer rests on before reading a word of it. Sunny keeps the head of the shelf at 56px; he used to be hidden outright the moment sources opened, which removed the mascot at exactly the moment the product does its most characteristic thing.
- **Tabs are spaced evenly, never proportionally.** The i-th of n sits at `(i+1)/(n+1)` of the spine face, with the page printed on it. Proportional placement would claim a document length the payload does not carry; the payload knows which page a passage came from, not how many pages the guideline has. Ordered by page, so the sequence is still true.
- **Spine labels** are vertical (`writing-mode: vertical-rl`), `direction: ltr; unicode-bidi: isolate`, and are the cleaned document name — the ISO date prefix and `.pdf` stripped, underscores spaced — before any truncation. Every document in the corpus begins with a date, so truncating the raw filename yields `2010-08-31_Gui` for several different guidelines and the shelf becomes worse than the list it replaced. The full name lives in the passage card and the `title`.
- **The passage** opens over the shelf with its spine still visible behind it, so a passage stays attached to the document it came from. A `[n]` marker in the prose opens its tab directly.
- **Page digits are Latin, always,** isolated `direction: ltr`. The model is instructed to keep markers and pages in Latin form, the citation markers already are, and Azeret Mono carries no tabular figures for Arabic-Indic digits — a page in one script beside a marker in the other on the same tab is incoherent.
- **`page: null`** keeps its tab and its number; only the page is absent, and the card says "No page cited" rather than leaving a blank where a number belongs.
- **Below 1200px** the sheet keeps the grouped list. The shelf is a rail form: it reads vertically and needs the column's height, and the breakpoint where a rotated shelf reads worst is the one where it would have to be validated.
- **Never opens itself,** in any state. It closes when a new question is asked, and on logout it is emptied rather than hidden — one reader's evidence must not sit in the DOM while the next signs in.

### Sunny (signature component)

The mascot is a generated SVG, not an asset. Every fill in it references a `--sunny-*` variable that resolves to a semantic token: teal shell (`--signal`), aubergine visor, marigold eyes, mouth and antenna (`--confidence`), marigold-tint cheeks, white core. Because of that, **a theme change and a state change are the same operation** — searching reassigns `--sunny-eye` to `--signal`, retrieved returns it to `--confidence`, error reassigns eye and mouth to `--danger`, and dark mode needs no rule at all. Sunny's face is the retrieval progress indicator: the antenna carries the retrieval signal, the eyes carry confidence.

On the landing Sunny is the page's only image, sized `clamp(150px, 24vw, 232px)`, floating on a 6s loop above a **warm** blurred glow (marigold, not teal — the glow is atmosphere around a character, and teal is spoken for). He mirrors under RTL (`scaleX(-1)`) so he still faces into the text; he carries no glyph children, so nothing needs un-mirroring. Motion is CSS keyframes rather than SVG SMIL, specifically so the global `prefers-reduced-motion` rule can reach it.

**The JS-Arms-The-Hidden-State Rule.** `[CORRECTNESS]` The card reveal's hidden state (`.animate-card.is-armed`) is applied by `effects.js` at runtime and is never authored in the HTML or triggered by CSS alone. If the module fails to load or the observer never attaches, the cards are simply visible. Verified with JS disabled and with the app module aborted. Any future scroll-reveal follows the same shape: no content is hidden by a stylesheet on the promise that a script will unhide it.

## Do's and Don'ts

### Do

- **Do** put every new colour in a Layer 1 ramp, give it a Layer 3 semantic name, and let components reference only the semantic name.
- **Do** flip primitives — and only primitives — for dark mode; if a component needs a dark branch, the ramp is wrong.
- **Do** use logical properties for everything, and reach for `calc(x * var(--flip))` when the property has no logical form.
- **Do** spend teal on the primary action and card icons on the landing, and ration it to retrieval and citation state inside the transcript.
- **Do** write fluid type as clamps between ramp tokens (`clamp(var(--fs-400), 1.5vw, var(--fs-500))`).
- **Do** set the display clamp's floor by the longer script — the Arabic wordmark, not the English one.
- **Do** use Azeret Mono with tabular figures for machine-reported values, and isolate them `direction: ltr` when they sit inside Arabic prose.
- **Do** tint shadows with the ink hue in light mode and swap to black at high alpha in dark.
- **Do** arm scroll-reveal hidden states from JS at runtime, so a dead module leaves content visible.
- **Do** stagger a multi-element exit newest-first and cap the total delay — the transcript clear caps at 140ms — so motion marks the state change without metering it. Wait on the _last_ element to finish, and keep a timeout backstop: `animationend` never fires for an interrupted animation, and a transcript that fails to detach is worse than one that detaches a frame early.
- **Do** bump `ASSET_VERSION` in `web/api/app.py` in any commit touching CSS or JS.
- **Do** suppress an entrance _permanently_ on an element that is being put back rather than added, and put the suppression **on the entrance declaration** — `.chatbot-message:where(:not(.anim-suppressed))`, not a blanket `animation: none` elsewhere. A re-appended node replays its entrance from the start, and lifting the suppression after a frame is not a fix: an entrance restarts whenever `animation-name` goes from `none` back to a name, so a suppression you let go of is only a delay. Scoping it to the declaration means it can only ever prevent an entrance — a restored turn a later feature wants to pulse or flag still animates — and `:where()` contributes no specificity, so the exit rule still wins on specificity rather than on source order.
- **Do** answer `prefers-reduced-motion` by making a _time-carrying_ animation discrete rather than deleting it — full duration, `steps(n)`. The reader still learns how long is left, and there is no continuous travel to track. Deleting it removes information; exempting it outright overrides a stated preference. Neither is the answer. (The undo countdown was the one worked example and has been retired; the principle is kept because the next timed affordance will need it.)
- **Do** add a new glyph to `web/utils/icons.py` once, and to `RUNTIME_ICON_NAMES` as well if a browser module draws it.
- **Do** carry the independence notice on every surface; the landing footer holds it.
- **Do** give a hover-revealed control a `:focus-within` sibling and a `@media (hover: none)` resting opacity in the same rule. A control that only appears under a cursor does not exist for a touch device or a keyboard reader.
- **Do** reserve a revealed control's space at rest, so a row does not reflow under the cursor in a scrolling list.
- **Do** set `dir="auto"` on any string a reader typed. Titles, questions and names mix scripts, and a fixed direction puts the ellipsis on the wrong end.
- **Do** suffix every id a twice-rendered macro generates, including the ones `aria-controls` and `aria-labelledby` point at — those resolve against the whole document, so an unsuffixed pair silently wires the mobile control to the desktop panel, and only for readers using a screen reader.
- **Do** put `overscroll-behavior: contain` on a scroll port nested inside another one.
- **Do** move the focus ring to the parent with `:has()` when an interactive element is `display: contents` — it has no box for the global outline to draw on.

### Don't

- **Don't** author a physical property that cannot mirror. `test_css_contract.py` fails the build; the five stylesheets are at zero violations and stay there.
- **Don't** apply negative letter-spacing or `text-transform: uppercase` under `[dir="rtl"]` — both break Arabic glyph joining or do nothing while breaking it.
- **Don't** reach for a primitive token inside a component file; add the missing semantic name instead.
- **Don't** state a guideline count, or any corpus figure, anywhere in copy. The corpus changes; the number goes stale on the next update.
- **Don't** wrap a card icon in a rounded-square tile, or repeat the same idea as both a mascot and a stock illustration on one page.
- **Don't** put a neutral grey shadow on the warm ground, or a shadow on anything that is flat and not responding to state.
- **Don't** use the 2px rule weight decoratively — it is reserved for marks that carry meaning.
- **Don't** invent a rule weight outside the vocabulary. 1px is a hairline, 2px is a mark that carries meaning, 4px is a meter, and there is nothing else. A coloured edge that wants to be noticed is the inset 2px pill the active row and both notices use — not a thickened `border-inline-start`, which is an unclassified weight wearing a border's clothing.
- **Don't** hide content in CSS on the assumption a script will reveal it.
- **Don't** reach for an emoji, a webfont glyph, or a second icon style. Every glyph is a filled 16-unit path in `icons.py`, and a set that mixes stroke weights or sources reads as assembled rather than drawn.
- **Don't** put a bordered card around an assistant answer, or give a shrink-to-fit flex parent a `inline-size: 100%` child — a percentage width contributes nothing to intrinsic sizing, which is exactly how the source deck once resolved to zero by zero on wide screens. The rule outlived the deck: the source panel nests groups inside lists inside a flex column, so it is the same shape of mistake waiting to be made again, and `test_source_panel.py` asserts a real bounding box for a passage at 1600px for that reason.
- **Don't** revive ambient decoration on every surface at once (drifting orbs, conic rings, canvas particle fields, per-element parallax). Motion marks a state change; that is its whole job.
- **Don't** set `font-style: italic` on anything that can hold Arabic. The script has no italic form, so the browser shears the glyphs into a synthesised oblique that breaks their joining and reads as a rendering fault. Carry the same emphasis with weight or colour.
- **Don't** open a second drawer from inside the first. Swap the panel's contents in place — see The One Drawer Rule.
- **Don't** let a flex row hold a truncating label. `min-width: auto` stops it shrinking below its content, so the label pushes its siblings out of the row instead of ellipsing; use a grid with `minmax(0, 1fr)`.
- **Don't** render an empty list when a request failed. "You have nothing" is a claim about the reader; make it only when the store answered.
- **Don't** build a relative timestamp out of `Intl.RelativeTimeFormat` or hand-rolled plurals on a bilingual surface. Arabic has six plural forms where the runtime helper knows two, `Intl` emits bidi control characters that reorder inside an RTL column, and the language toggle reloads the page — so a cached relative string is stale by construction. Fixed day buckets from the catalogue say the same thing and stay grammatical.
