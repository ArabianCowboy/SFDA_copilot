---
name: SFDA Copilot
description: A regulatory reference instrument — ink on paper, hairline structure, one seal reserved for traceable sources.
colors:
  ink-900: "#0C1A2B"
  ink-700: "#22364B"
  ink-500: "#4A5D74"
  ink-300: "#8195A9"
  paper-000: "#FFFFFF"
  paper-050: "#FAFBFC"
  paper-100: "#F2F5F8"
  rule-200: "#DDE3EA"
  rule-300: "#C4CDD8"
  seal-600: "#1B4DB1"
  seal-700: "#153C8C"
  seal-100: "#E7EDFA"
  verify-600: "#0E7C66"
  verify-700: "#0B6654"
  verify-100: "#E2F1ED"
  alert-600: "#B3261E"
  warn-600: "#8A5A00"
typography:
  display:
    fontFamily: "IBM Plex Sans, IBM Plex Sans Arabic, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "clamp(2.75rem, 6vw, 4rem)"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.022em"
  headline:
    fontFamily: "IBM Plex Sans, IBM Plex Sans Arabic, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "2rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  title:
    fontFamily: "IBM Plex Sans, IBM Plex Sans Arabic, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  body:
    fontFamily: "IBM Plex Sans, IBM Plex Sans Arabic, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.65
    letterSpacing: "0"
  body-small:
    fontFamily: "IBM Plex Sans, IBM Plex Sans Arabic, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.3
  meta:
    fontFamily: "IBM Plex Sans, IBM Plex Sans Arabic, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.3
  label:
    fontFamily: "IBM Plex Mono, ui-monospace, SFMono-Regular, Cascadia Mono, monospace"
    fontSize: "0.75rem"
    fontWeight: 500
    letterSpacing: "0.06em"
rounded:
  xs: "2px"
  sm: "4px"
  md: "6px"
  lg: "10px"
  xl: "14px"
  msg: "10px"
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
    backgroundColor: "{colors.seal-600}"
    textColor: "#FFFFFF"
    rounded: "{rounded.md}"
    padding: "12px 32px"
  button-primary-hover:
    backgroundColor: "{colors.seal-700}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-700}"
    rounded: "{rounded.md}"
    padding: "4px 12px"
  button-ghost-hover:
    backgroundColor: "{colors.paper-100}"
    textColor: "{colors.ink-900}"
  button-icon:
    backgroundColor: "{colors.paper-000}"
    textColor: "{colors.ink-500}"
    rounded: "{rounded.md}"
    size: "36px"
  input-field:
    backgroundColor: "{colors.paper-000}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.sm}"
  input-composer:
    backgroundColor: "{colors.paper-000}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
  card-feature:
    backgroundColor: "{colors.paper-000}"
    textColor: "{colors.ink-700}"
    rounded: "{rounded.lg}"
    padding: "24px"
  card-source:
    backgroundColor: "{colors.paper-000}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.sm}"
    padding: "12px"
  card-source-lit:
    backgroundColor: "{colors.seal-100}"
  message-bubble-bot:
    backgroundColor: "{colors.paper-000}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.msg}"
    padding: "16px 24px"
  message-bubble-user:
    backgroundColor: "{colors.seal-600}"
    textColor: "#FFFFFF"
    rounded: "{rounded.msg}"
    padding: "16px 24px"
  cite-marker:
    backgroundColor: "{colors.seal-100}"
    textColor: "{colors.seal-600}"
    rounded: "{rounded.xs}"
    padding: "0 0.3em"
  cite-marker-active:
    backgroundColor: "{colors.seal-600}"
    textColor: "#FFFFFF"
  chip-suggested:
    backgroundColor: "{colors.paper-000}"
    textColor: "{colors.ink-700}"
    rounded: "{rounded.pill}"
    padding: "8px 12px"
  faq-button:
    backgroundColor: "transparent"
    textColor: "{colors.ink-700}"
    rounded: "{rounded.sm}"
    padding: "8px 12px"
  faq-button-active:
    backgroundColor: "{colors.seal-600}"
    textColor: "#FFFFFF"
  badge-knowledge:
    backgroundColor: "{colors.paper-100}"
    textColor: "{colors.ink-500}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "4px 12px"
  toast:
    backgroundColor: "{colors.ink-900}"
    textColor: "{colors.paper-050}"
    rounded: "{rounded.md}"
    padding: "12px 24px"
---

# Design System: SFDA Copilot

## Overview

**Creative North Star: "The Dossier"**

A dossier is a case file: paper, hairline rules, tabbed sources, and a seal that
means a specific thing. This system builds a regulatory answer the way a dossier
is built — the structure is drawn, not stacked; the evidence is filed beside the
claim; and exactly one colour is reserved for the mark that says *this came from a
document*. The product's whole promise is traceability, so the visual system spends
its scarcest resource on making provenance visible and spends almost nothing
anywhere else.

The mood is **sober, traceable, warm at the edges**. The core is disciplined:
cool archival paper (never cream), 1px rules doing the structural work shadows
would do elsewhere, tabular figures wherever a number carries meaning, and a
reading column set at 68ch in 17px type with 1.65 leading because answers are prose
that people actually read. The warmth is deliberate and lives at the perimeter —
the assistant says "Ready to help" rather than "Awaiting input", and a mascot may
occupy the rail. Neither is allowed to migrate into the answer surface, where
sobriety is the point.

This is a bilingual system by construction, not by translation. IBM Plex Sans,
Plex Sans Arabic, and Plex Mono are one family across three scripts, chosen because
the corpus is mixed AR/EN and body text must not change designer between languages.
Direction is handled structurally: every rule uses logical properties, tracking
tokens zero out under RTL because negative letter-spacing shatters Arabic glyph
joining, and a `--flip` multiplier mirrors the transforms that carry meaning.

**Key Characteristics:**

- Hairlines, not shadows, carry structure
- One signal colour, spent only on retrieval and citation
- Cool archival paper; squarer corners than a chat product
- 68ch reading measure, 17px body, 1.65 leading
- Bilingual by construction — logical properties throughout, RTL-aware tracking
- Motion marks a state change; nothing animates for atmosphere
- Dark mode flips primitives only; no component contains a theme branch

## Colors

A cool, archival palette: four ink weights on three paper weights, separated by two
hairline greys, with two carrier colours that are rationed rather than decorative.

### Primary

- **Seal Blue** (`seal-600`): the signal. Retrieval and citation state, and
  essentially nothing else — the citation marker, the lit source card, the
  streaming caret, the unread dot, the stage indicator, and the user's own message
  bubble. `seal-700` is its hover; `seal-100` is the tint behind a marker or a lit
  card.

### Secondary

- **Verified Green** (`verify-600`): confidence and relevance. The relevance bar
  under a source card, the mascot's eyes once passages are in hand, the success
  rule on a toast. `verify-700` is for white text on the fill; `verify-100` is its
  tint.

### Neutral

- **Ink** (`ink-900` → `ink-300`): the four text weights. `ink-900` is primary
  text and the inverted toast surface; `ink-700` is secondary prose; `ink-500` is
  muted labels and captions; `ink-300` is faint metadata that must recede.
- **Paper** (`paper-050`, `paper-000`, `paper-100`): page, raised surface, and
  sunken surface. Cool and archival — never cream, never warm.
- **Rule** (`rule-200`, `rule-300`): the hairline pair. `rule-200` is the default
  divider and border; `rule-300` is the emphasized one, used for input borders,
  blockquote rules, and hover states.

### Status

- **Alert** (`alert-600`): errors, the mascot's error face, the toast error rule.
- **Warn** (`warn-600`): cautions. Currently declared and reserved.

### Named Rules

**The One Seal Rule.** Seal Blue appears only where retrieval or citation state is
being reported. Using it for a generic button is a bug, not a preference: it
dilutes the single cue that tells a reader a sentence is traceable to a document.
When a new component wants emphasis, it gets a hairline, a weight change, or a
sunken background — not the seal.

**The Flip-the-Ramp Rule.** Dark mode overrides **primitives only**. Every semantic
name resolves correctly without a single dark-mode branch anywhere in a component.
If you find yourself writing `[data-bs-theme="dark"] .my-component`, the primitive
ramp is wrong, not the component. The ramp genuinely inverts rather than dimming:
Seal Blue lifts to `#6E9BF0` in dark and its *hover goes lighter* (`#9CBCF7`),
because `#1B4DB1` on the dark page measures roughly 1.7:1 and is unreadable.
Verified Green lifts the same way, to `#35C3A3`.

**The Three-Layer Rule.** Primitives → scales → semantics, and components
reference **semantics only**. Reaching for a primitive inside a component means the
semantic layer is missing a name; add the name rather than the exception.

## Typography

**Display / Body Font:** IBM Plex Sans (with IBM Plex Sans Arabic, then system sans)
**Arabic Font:** IBM Plex Sans Arabic (substituted wholesale for `--font-sans`
under `[dir="rtl"]`)
**Label / Mono Font:** IBM Plex Mono

**Character:** One family, three scripts. Plex is the typeface of technical
documentation — engineered, legible at small sizes, and unglamorous in a way that
suits a regulatory instrument. Plex Sans Arabic is the actual reason for the
choice: it is the only high-quality free family with a genuine Arabic sibling, and
a bilingual corpus cannot afford body text that changes designer between languages.
Mono is not for code — it marks *machine-reported facts*: page numbers, relevance
scores, timestamps, stage labels, and the knowledge-cutoff badge.

### Hierarchy

- **Display** (600, `clamp(2.75rem, 6vw, 4rem)`, 1.15, -0.022em): the landing
  wordmark. One per page, at most.
- **Headline** (600, 2rem, 1.15, -0.01em): section headings on marketing surfaces.
- **Title** (600, 1.25rem, 1.3, -0.01em): card titles, modal titles, the sidebar
  wordmark. The workhorse heading.
- **Body** (400, 1.0625rem/17px, 1.65): answers and sustained prose. The size and
  leading are set for reading, not for UI density.
- **Body Small** (400, 0.9375rem, 1.3): secondary prose — feature card copy, FAQ
  entries, composer input, table cells.
- **Meta** (500, 0.8125rem): source titles, taglines, chips, form help.
- **Label** (mono, 500, 0.75rem, 0.06em, uppercase): the machine register —
  category headers, stage lines, scores, page numbers, timestamps, the cutoff
  badge.

### Named Rules

**The Arabic Tracking Rule.** Negative letter-spacing breaks Arabic glyph joining
and renders text as disconnected gibberish. Under `[dir="rtl"]` every tracking
token goes to zero, `letter-spacing: normal` is force-reset on all descendants, and
leading opens up (body 1.65 → 1.85, snug 1.3 → 1.45). Never hardcode
`letter-spacing` in a component; use the tokens so this override reaches it.

**The Tabular Rule.** Any number that carries meaning gets
`font-variant-numeric: tabular-nums` — page numbers, relevance scores, timestamps.
Digits must not jitter between frames while an answer streams.

**The Isolation Rule.** Numeric metadata sitting inside Arabic prose is marked
`dir="ltr"` with `unicode-bidi: isolate`, so bidi reordering cannot scramble a page
number or a score. Every number the reader might quote back is protected this way.

## Layout

A **reading measure and a rail**, not a chat column. The transcript centres on a
68ch measure (`--measure`) using
`padding-inline: max(var(--gutter), calc((100% - var(--measure)) / 2))` rather than
a wrapper element — JS appends straight into `#messages`, so it must stay the direct
parent of every message. The composer shares the same 68ch measure so the input
lines up with the text it produces.

The app shell is a fixed-height grid: `.chat-area` is
`grid-template-rows: minmax(0, 1fr) auto` so the composer stays pinned while the
transcript scrolls on its own. Above 1200px a second grid column opens
(`--rail-w: clamp(240px, 20vw, 320px)`) for the mascot and, at 1440px and above,
the promoted source deck. **The rail is a real grid column**, never a floating
overlay: the reading column is therefore never padded around a ghost, and the whole
arrangement mirrors under RTL for free. Below 1200px there is no rail and the
inline message avatars carry the mascot instead.

Spacing is a 4px scale (`--space-1` … `--space-9`, 4 → 96px). Gutters are fluid:
`--gutter: clamp(16px, 4vw, 48px)`. Card and surface padding sits at 24px, message
bubbles at 16px/24px, dense controls at 8px/12px.

Breakpoints follow Bootstrap 5.3: the sidebar becomes an offcanvas drawer below
`lg` (992px), the rail appears at `xl` (1200px), and the source deck promotes from
a collapsible summary into the rail at 1440px.

### Named Rules

**The Logical Property Rule.** No physical direction properties. `inline-size`,
`block-size`, `padding-inline`, `border-inline-end`, `inset-block-start`,
`border-start-start-radius` — all of them, always. This is enforced:
`web/tests/test_css_contract.py` fails the build on physical properties that cannot
mirror. Where CSS has no logical equivalent (there is no logical `translate`), a
`--flip` multiplier (1 in LTR, -1 in RTL) is applied inside the transform:
`translateX(calc(-12px * var(--flip)))`.

**The Measure Rule.** Answers are prose. The transcript and the composer share one
68ch measure, and nothing widens it for the sake of filling a screen. Extra width
goes to the rail or stays empty.

## Elevation & Depth

**This system is flat by doctrine.** Structure is drawn with 1px hairlines and
separated by whitespace; tonal layering (`paper-100` sunken, `paper-000` raised,
`paper-050` page) does the rest. The shadow scale exists but is deliberately
under-used — four tokens, five total usages across the entire stylesheet.

A shadow appears only when an element *genuinely floats above the page* and needs
to read as detached: the modal, the dropdown menu, the toast, and the jump-to-latest
pill. Shadows are never used to make a card look important, to imply hierarchy
among peers, or to soften an edge.

### Shadow Vocabulary

- **`shadow-sm`** (`0 1px 2px rgb(12 26 43 / .06)`): the landing hero's barely-there
  lift. The lightest sanctioned use.
- **`shadow-md`** (`0 2px 8px rgb(12 26 43 / .08)`): the jump-to-latest pill, which
  overlays scrolling text and must separate from it.
- **`shadow-lg`** (`0 8px 24px rgb(12 26 43 / .10)`): the composer's category
  dropdown.
- **`shadow-xl`** (`0 20px 48px rgb(12 26 43 / .14)`): modals and the toast — the
  only genuinely overlaid surfaces.

In dark mode the shadow ramp switches to pure black at much higher alpha
(0.40 → 0.55), because a translucent ink shadow is invisible on a dark page.

### Named Rules

**The Hairline-First Rule.** Reach for a 1px rule before reaching for a shadow. If
a hairline and whitespace cannot express the separation, ask whether the separation
is real before adding depth.

## Shapes

**Squarer than a chat product, because documents have corners.** The radius scale
runs 2 / 4 / 6 / 10 / 14px plus a pill, and the small end carries most of the
weight: 2px on citation markers and source indices, 4px on source cards, form
fields, and FAQ entries, 6px on buttons, icon controls, and the composer.

10px is reserved for larger surfaces — feature cards, the hero image, modals,
message bubbles. 14px appears exactly once, on the landing hero stage. The pill
radius is used only for genuinely pill-shaped things: the jump-to-latest control,
suggested-question chips, mascot status labels, the relevance bar, and scrollbar
thumbs.

Borders are the primary form-giver. Nearly every surface is a 1px `rule-200` box on
`paper-000`; hover promotes the border to `rule-300` or `ink-300` rather than
adding fill or lift.

Border weight is a two-value system and nothing else: **1px means structure**
(every surface, divider, and cell) and **2px means meaning** — the active tab
indicator, the blockquote rule, the knowledge-cutoff rule, the toast's severity
rule, and the focus outline. There is no third weight. A component that wants more
emphasis than 2px is asking for the wrong tool.

### Named Rules

**The Corner-Points-Home Rule.** A message bubble squares the corner nearest its
speaker (4px against 10px elsewhere) — and does it with
`border-start-start-radius` for the assistant and `border-start-end-radius` for the
user, so the tail follows writing direction instead of a fixed side.

## Components

Character line, for every component in this system: **flat at rest, responsive on
contact.** Components are outlined shapes on paper, not objects floating above it.
Nothing is pre-emphasized; the visual change is earned by a state.

### Buttons

- **Shape:** subtly rounded (6px, `rounded.md`); icon controls are square 36px
  boxes at the same radius.
- **Primary:** Seal Blue fill, white text, 12px/32px padding, 600 weight. Hover
  darkens to `seal-700` (and *lightens* in dark mode). Active nudges 1px down.
  Reserved for the genuine primary action on a surface.
- **Ghost:** transparent with a `rule-300` hairline and secondary ink. Hover fills
  with `paper-100` and promotes the border. This is the default for secondary
  actions — logout, profile, anything that is not *the* action.
- **Icon (theme / language / utility):** 36px square, `rule-200` hairline, muted
  ink on `paper-000`. Hover darkens the ink, sinks the background, promotes the
  border. Three of these live in the page chrome, plus the language toggle, which
  is deliberately a separate class from the theme toggle.
- **Focus:** every control takes the global `:focus-visible` treatment — a 2px
  Seal Blue outline at 2px offset. Never removed, never replaced with a colour
  change alone.

### Chips

- **Suggested question:** pill (999px), `rule-300` hairline, `paper-000`, meta
  type. Hover darkens the ink and promotes the border; its leading icon turns Seal
  Blue on hover — the one place the seal appears as pure affordance, because the
  chip *is* a query about to be traced.
- **Knowledge badge:** 4px radius, `paper-100` fill, `rule-300` hairline, mono
  uppercase label type. Reads as a stamp, not a button.

### Cards / Containers

- **Feature card:** 10px radius, `paper-000`, `rule-200` hairline, 24px padding,
  full-height. The only hover is a border promotion to `rule-300` — no lift, no
  shadow, no scale.
- **Source card:** 4px radius, `paper-000`, `rule-200`, 12px padding. Its lit
  state (`is-lit`, driven by hovering the matching citation marker) swaps the
  border to Seal Blue and the fill to `seal-100`. That pairing is the mechanism by
  which a claim connects to its evidence, and it is the most important state
  transition in the product.
- **Auth status / knowledge notice:** sunken `paper-100` panels with a hairline,
  used where a block is informational rather than interactive. The cutoff notice
  uses a 2px `rule-300` inline-start rule instead of a full border.

### Inputs / Fields

- **Modal fields:** `paper-000`, 4px radius, `rule-300` border, floating labels in
  muted ink.
- **Composer:** the input and send button are a single joined unit — 6px radius on
  the outer edges, squared where they meet, achieved with logical corner
  properties so the join mirrors under RTL. The input drops its inline-end border
  entirely.
- **Focus:** border shifts to Seal Blue plus a 3px `focus-ring-shadow` halo. The
  composer input suppresses the halo and raises its z-index instead, so the joined
  seam stays clean.

### Modal & Tabs

- **Shell:** 10px radius, `paper-000`, `rule-200` hairline, `overflow: hidden` so
  the header's fill meets the corner cleanly. Carries `shadow-xl` — a modal is one
  of the few things in this system that genuinely floats.
- **Header:** a sunken `paper-100` band closed by a hairline, with the title in
  title type (600, 1.25rem, tight tracking) behind a Seal Blue shield icon. The
  close button keeps a dark rendering (`filter: none`, 60% opacity) rather than
  Bootstrap's inverted white variant — on a near-white band, a white glyph would
  disappear.
- **Tabs (Login / Signup):** full-width, borderless, muted ink at 500 weight, each
  carrying a 2px transparent `border-block-end` that turns Seal Blue when active
  while the label darkens to primary ink. The background never fills. This is the
  system's only moving-indicator pattern, and it is a hairline — consistent with
  everything else here being drawn rather than filled.

### Category Dropdown

The composer's scope selector: a custom listbox with a visually hidden `<select>`
kept in sync beneath it, so the control can be styled without losing form
semantics.

- **Trigger:** 4px radius, `rule-300` hairline, meta type at 500 weight on
  `paper-000`, with a leading category glyph and a chevron that rotates 180° on
  open. Hover promotes the border to `ink-300`.
- **Known inconsistency:** the category glyphs are emoji (🌐 📋 💊 🐾 🧬) while the
  rest of the product draws its icons from Bootstrap Icons at a consistent stroke.
  Emoji render per-platform, ignore `currentColor`, and cannot follow the theme.
  This is the one place the icon system breaks; a new surface should not copy it.
- **Menu:** **opens upward** (`inset-block-end: calc(100% + 8px)`), because the
  composer is pinned to the bottom of the viewport and a downward menu would open
  off-screen. 6px radius, `rule-200` hairline, `shadow-lg`, 220px minimum width.
- **Items:** 2px radius, body-small type, secondary ink. Hover sinks to
  `paper-100`; the selected item takes a full Seal Blue fill — the same licence the
  active FAQ entry has, because choosing a category is scoping a retrieval.
- **Transition:** opacity, a 4px translate, and `visibility` together, so a closed
  menu is genuinely non-interactive rather than transparent and still clickable.

### Navigation

- **Sidebar:** sticky full-height `paper-000` panel with a `rule-200` inline-end
  border, entering with a 16px direction-aware slide. Its header is a hairline-
  separated block: wordmark in title type with a Seal Blue shield icon, tagline in
  muted meta, language toggle, and a sunken auth-status panel.
- **FAQ list:** category headers in mono uppercase label type, separated by
  `border-block-start` hairlines. Entries are transparent 4px boxes that fill with
  `paper-100` on hover; the active entry takes a full Seal Blue fill — legitimate,
  because selecting a FAQ *is* initiating a retrieval.
- **Mobile:** below 992px the sidebar becomes an offcanvas drawer and a `paper-000`
  navbar appears with a hairline underline and a token-driven toggler icon that
  recolours per theme.

### Citation System (signature)

The reason the palette is rationed. An answer's prose carries inline
`.cite-marker` buttons — mono, 0.7em, 2px radius, Seal Blue on `seal-100`, raised
on the baseline — which resolve to a `.source-deck` beneath the message. Below
1440px the deck is a collapsible summary with a rotating chevron; at 1440px and
above the summary disappears and the list is always open in the rail.

Each source card carries: a mono index box, the document title (`dir="auto"`), a
page number (`dir="ltr"`, tabular), an uppercase category, a 4px relevance bar
filled in Verified Green to a `--pct` custom property, the SEM/LEX score split in
mono, and an expandable snippet behind a hairline. Hovering a marker lights its
card; hovering the card is not required — the connection is offered from the text,
where the reader already is.

### Answer Body

The rendered Markdown inside an assistant bubble — the reading surface, styled as a
document rather than as chat.

- **Tables:** a regulatory answer is often a table, so it gets real structure
  rather than being an afterthought: collapsed borders, a `rule-300` outer border
  at 4px radius with `overflow: hidden` so the radius actually clips, `rule-200`
  cell borders, 8px/12px cells, `text-align: start`, and top-aligned cells. The
  header row is a sunken band in the label register — uppercase, 0.06em tracking,
  meta size, 600 weight. Inside a user bubble the cell borders switch to
  `rgb(255 255 255 / .3)` so they stay visible against the Seal Blue fill.
- **Headings:** promoted to title size with 24px above and 8px below — more space
  above than below, so a heading binds to the text it introduces rather than
  floating between two blocks.
- **Blockquote:** a 2px `rule-300` inline-start rule at 16px inset, secondary ink.
  No fill, no italic, no quotation glyph.
- **Code:** blocks sit on sunken `paper-100` behind a `rule-200` hairline at 4px
  radius, mono at meta size, scrolling horizontally rather than wrapping. Inline
  code is the same treatment at 2px radius and 0.875em. This is the one place mono
  means code; everywhere else it means measurement.
- **Lists:** 1.25em inline-start padding, 4px between items. The padding is inline,
  not left, so Arabic lists indent from the correct edge.

### Streaming States

Listed in the order a request passes through them.

- **Typing indicator:** three 6px `ink-300` dots on a 1.2s bounce staggered 0.15s
  apart. The only pre-token state; the caret takes over the moment text arrives.
- **Stage line:** mono uppercase label type with a Seal Blue dot, naming the actual
  stage — searching, N passages found, drafting, finishing. Honest progress, not a
  generic spinner.
- **Caret:** a 2px Seal Blue block on the pending tail, blinking on a
  `steps(2, start)` timer, so a stalled stream reads as "still writing" rather than
  "finished". It is removed on cancel and on error.
- **Stream note:** mono uppercase label in faint ink for terminal states the reader
  must notice without alarm — "Stopped", "Answer incomplete". Turns Alert red on
  error. It appends below the answer and never replaces it: a partial answer stays
  on screen, because a partial regulatory answer still has value and the reader
  decides what it is worth.
- **Jump-to-latest:** a pill in the same grid cell as the transcript with
  `align-self: end`, so it overlays without absolute positioning and mirrors under
  RTL. Its unread dot is Seal Blue, because something traceable arrived below the
  fold. It enters via keyframe rather than a class toggled on rAF — rAF is
  throttled in a background tab, which would leave the pill hit-testable but
  invisible.

### Mascot ("Sunny") — optional expressive layer

**This layer is not mandatory.** No surface is obliged to carry it, no future
design is blocked on preserving it, and it may be reinterpreted, lightened, or
replaced. What follows is the discipline it observes *when present* — and any
successor should inherit that discipline even if it inherits nothing else.

- **It binds to the token system, never to its own palette.** Every fill in the
  generated SVG references a token: shell = Seal Blue, eyes = Verified Green,
  visor = ink, chrome = `rule-300`, error = Alert. Theme changes and state changes
  are therefore the same operation — a token override.
- **Its face is the progress indicator.** Eyes go Seal Blue while retrieving and
  Verified Green once passages are in hand; the antenna flashes once per retrieved
  passage. It reports real work rather than performing activity.
- **It mirrors under RTL** (`scaleX(-1)`) so it faces into the text it is
  commenting on, and it carries no glyph-bearing children that would need
  un-mirroring.
- **Its animation is CSS keyframes, not SVG SMIL** — SMIL ignores
  `prefers-reduced-motion`; CSS keyframes are caught by the global reduced-motion
  reset.
- **It lives in the rail**, sticky to the bottom, never floating over the
  transcript. The earlier floating treatment forced a 168px gutter through the
  reading column; that is the failure mode to avoid.

### Named Rules

**The Motion-Marks-State Rule.** Motion exists to mark a state change: a message
arriving, a panel revealing, a stream pending, a retrieval landing. Durations are
short (150 / 250 / 400 / 600ms) on two easings — `ease-out` for entrances,
`ease-soft` for state transitions. The mascot's idle float and glow are the single
sanctioned exception, and they are confined to the rail. Everything is caught by a
global `prefers-reduced-motion` reset that flattens animation and transition
duration to 0.001ms.

## Do's and Don'ts

### Do:

- **Do** reference Layer 3 semantic names (`--fg-primary`, `--signal`,
  `--hairline`) in components. If you need a primitive, the semantic layer is
  missing a name — add the name.
- **Do** spend Seal Blue only on retrieval and citation state. Everything else gets
  a hairline, a weight, or a sunken background.
- **Do** use logical properties for every direction, size, and corner. The build
  fails on physical ones.
- **Do** mark meaningful numbers `tabular-nums`, and isolate them with `dir="ltr"`
  and `unicode-bidi: isolate` when they can appear inside Arabic prose.
- **Do** give every interactive element the global focus ring — 2px Seal Blue
  outline at 2px offset.
- **Do** bump `asset_version` in `web/api/app.py` in any commit that touches CSS or
  JS. Returning users otherwise get a stale `components.css` against a fresh
  `tokens.css`.
- **Do** keep the reading measure at 68ch for both the transcript and the composer.

### Don't:

- **Don't** add a decorative layer that animates independently of state.
  Specifically rejected and removed from this project: spinning conic-gradient
  rings, blurred orb fields, lens flares, and canvas particle fields. A future
  ambient idea is not forbidden as a category, but it must earn its place against
  this rejection — it animated behind every screen at once, so nothing read as the
  hero.
- **Don't** write a dark-mode branch inside a component. Fix the primitive ramp
  instead.
- **Don't** use `--signal` for a generic button, a decorative accent, or a hover
  colour on something unrelated to sources.
- **Don't** hardcode `letter-spacing`; the RTL override must be able to reach it.
- **Don't** express structure or hierarchy with a shadow. Shadows are only for
  elements that genuinely float — modal, dropdown, toast, jump pill.
- **Don't** introduce a third border weight. 1px is structure, 2px is meaning, and
  there is nothing above 2px anywhere in this system.
- **Don't** clip a gradient to the wordmark glyphs. The wordmark is set in solid
  ink with display tracking; the gradient treatment was tried and removed.
- **Don't** float the mascot over the transcript. If it appears, it belongs in the
  rail.
- **Don't** reintroduce a compatibility alias layer over the token ramp. The
  previous "Clinical Blue" shim is gone; every component references a semantic name
  directly.
