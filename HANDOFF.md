# Handoff — remaining work after the landing redesign

Paste the block below into a fresh Claude Code session. It is written to be
used verbatim.

Delete this file once the work it describes is done.

---

````markdown
/impeccable The landing page redesign is finished and committed. Do the three
pieces that were deliberately deferred, on the authenticated chat app.

## Read first
DESIGN.md was rewritten from the built landing and is current — it documents
the shipped world (warm porcelain, aubergine ink, deep teal signal, marigold
warmth, Zain + Readex Pro + Azeret Mono, soft radii). PRODUCT.md is current too.

## Do NOT
- Do not touch the landing page. It is done, reviewed, and committed (7ccb4cd,
  9b4a303, a099fd2). Its composition was pinned by the user after an earlier
  from-scratch redesign was rejected as cluttered and reverted wholesale.
- Do not run a concept tournament or rewrite DESIGN.md. The visual world is
  already committed; the chat app INHERITS it. This is composing an existing
  surface inside an established world, not an identity exercise.

## The work, in priority order
1. **Compose the chat app for the new world.** It currently inherits the new
   token ramp and works, but its composition was never re-examined — DESIGN.md
   records those sections as "inherited, not designed" and says so explicitly.
   Sidebar, FAQ list, composer, message bubbles, source deck / citation cards,
   modals, toast, mobile offcanvas.
2. **Replace the composer's emoji category icons** (🌐 📋 💊 🐾 🧬,
   web/templates/index.html around line 507). Emoji render per-platform, ignore
   currentColor, and cannot follow the theme. The documenter deliberately
   refused to canonise them so this surface would not inherit the pattern.
3. **Replace Bootstrap Icons glyphs with inline SVG.** The sidecar already
   specifies inline SVG; the build still ships the icon font.

## Mode
The chat is **Operate**, not Persuade. Scanability, task completion, and
native affordances outrank expression. The reader arrives mid-task with one
regulatory question and a deadline. Brand lives in precise details, not in
atmosphere. Answers stream and are read WHILE still being written.

## Hard constraints (all enforced, all will bite)
- `web/tests/test_css_contract.py` FAILS THE BUILD on physical CSS properties
  that cannot mirror under RTL. Currently 0 violations — keep it there. Use
  logical properties everywhere; `--flip` (1/-1) inside transforms where CSS
  has no logical equivalent.
- Three-layer tokens: components reference LAYER 3 semantic names only. Dark
  mode overrides PRIMITIVES ONLY — a dark-mode branch inside a component means
  the primitive ramp is wrong.
- Exactly three elements must carry class `theme-toggle-btn` (asserted).
- Several i18n strings are frozen and asserted verbatim — marked `# frozen` in
  web/i18n/en.yaml. Changing one is a test change, not just a copy change.
- Full EN/AR parity with true RTL. Negative letter-spacing shatters Arabic
  glyph joining; tracking tokens zero out under `[dir="rtl"]`.
- Bump `ASSET_VERSION` in web/api/app.py on ANY commit touching CSS or JS
  (currently "warm3"), or returning users get a stale stylesheet.
- No bundler, no node_modules. Bootstrap 5.3 + Google Fonts from CDN, browser-
  native ES modules.
- PRODUCT.md: never state a guideline count, never imply SFDA endorsement,
  never fabricate evidence.

## Testing note
Run targeted files, not the whole suite: `test_search.py` and
`test_embedding_factory.py` take ~54 minutes because they load the embedding
model against the real FAISS index. For UI work run test_css_contract,
test_frontend, test_theme_toggle, test_rtl, test_frontend_architecture.
`test_auth.py` fails with ConnectionError unless a server is running on
localhost:5000 — pre-existing and environmental, not your problem.

## Working style this user expects
They revert aggressively when a surface is dense. The last rejection was for
putting too much on one screen. Keep information minimal, let things breathe,
and show them a render before building further on top of it.
````

---

## Notes for whoever runs this

**Consider splitting it.** Item 1 is a substantial redesign; items 2–3 are
small mechanical cleanups. Doing the icons *first*, in their own session, is
cheaper and makes the chat work easier — the icon system will already be right
when the composition starts.

**Protect the mascot.** Sunny lives in the chat rail and its face is a real
progress indicator: eyes go signal while retrieving, confidence once passages
are in hand, antenna flashes once per retrieved passage. That is function, not
decoration, and it is easy to mistake for something to tidy away. It also binds
every fill to a semantic token, so a theme change and a state change are the
same operation — preserve that.

**Two known-good invariants worth not breaking:**
- The landing's card reveal arms its hidden state from JS at runtime
  (`.is-armed`), never in authored CSS, so a failed module cannot leave content
  permanently invisible. Verified with JS disabled and with the app module
  aborted. Any similar reveal in the chat should follow the same pattern.
- `.robot-exit` animates with `forwards`, so its final frame persists by
  design. Anything that returns to the landing must clear it —
  `RobotStateManager.transitionToUnauthenticatedView()` is the one place that
  does, and it exists because logout used to leave the mascot invisible.

## State at handoff

- Branch `main`, tree clean, nothing pushed.
- Full suite verified green against this build, including the slow search and
  embedding tests.
- `ASSET_VERSION = "warm3"`, `APP_VERSION = "3.0.0"`.
