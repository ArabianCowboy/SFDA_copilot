---
authority: historical
status: superseded
do_not_implement: true
archived: 2026-08-23
supersedes_note: >
  This document is a finished plan. Parts of it were reversed before shipping.
  It is a record of what was decided and what it cost, not a specification.
live_authority:
  - docs/ARCHITECTURE.md
  - supabase/README.md
  - DESIGN.md
---

> [!CAUTION]
> **You are reading history, not a specification.** Do not implement anything found
> in this file without first confirming it against `docs/ARCHITECTURE.md` or the code.
> Every heading below is prefixed `[HISTORICAL]` so a search result cannot be mistaken
> for current design.

STATUS: HISTORICAL RECORD — archived 2026-08-23. Nothing here is an instruction.
Live rules: `docs/ARCHITECTURE.md`, `supabase/README.md`, `DESIGN.md`.

**The internal precedence chain is resolved. You do not need to know it to read this safely.**
As written, this document required you to know that §15 overrides §14, which overrides §0-§13;
that §17 supersedes §9; that §16 beats Appendix E and §14 beats Appendix D. Read top-down without
that key and you would have written a broken migration. The resolution is simply: **§14, §15, §16
and §17 are what happened. §0-§13 and the appendices are the drafts that got there**, and where
they disagree with the later sections, the later sections won — and then the code won over all of
them.

**What is still open** (see `TODO.md` for each):

- Bilingual GoTrue email templates (§14·D·26, §17 Step 5) — blocked in the Supabase dashboard.
- Account deletion (§16·4, Appendix E Spec 4, §17 Step 7) — blocked on an unclosed product
  question: is reader self-deletion permitted at all, given the audit log? Both migrations are
  written and unapplied.

**Step 6 (consent) shipped on 2026-08-23**, after this banner was first written. It was
unblocked by publishing `/privacy` as an openly-labelled draft rather than by waiting for a
reviewed policy — a deliberate product-owner call, recorded in `TODO.md`. What remains owed is
the legal review of that text, which has its own entry there.

**One known divergence from the code:** §4 specifies routes at `/api/account/*`. They shipped at
`/account/api/*`, following the convention `web/api/admin.py` already set. §17 records this; §4
was not updated.

# [HISTORICAL] Profile refactor — Design & Implementation Plan

**Status (corrected on archive, 2026-08-23):** built. Steps 0-5 and most of Step 7 shipped;
three items remain, each blocked on a decision or a document rather than on engineering, and
each now has its own entry in `TODO.md`. The sentence that stood here — *"approved plan, not
started, nothing here is built"* — was already false when the work landed and was never
updated. It is recorded rather than quietly deleted, because it is the clearest example in
this repository of the failure this archive exists to stop. The two blocking decisions were
settled by the owner on 2026-08-22 — see Decisions 1 and 5.

**Read §14 and §15 first, in that order.** Four later passes — an adversarial debate of this
document, an external review, a documentation check against current upstream sources, and a live
query of the applied database — found defects in §0–§13, including two that would ship an outage
and one that would let anyone break account creation.

- **§14 overrides §0–§13** wherever they disagree. Four items there are **P0 blockers**
  (§14·C·12, ·13, ·14, and §14·B·9).
- **§15 overrides everything**, because it is the only section written from the real database
  rather than from migration files. It cancels one migration step outright and confirms another
  reversal on the facts.

Read in that order, the plan is implementable. Read §0–§13 alone and you will write a broken
migration.

**To implement, work from §17.** It is the authoritative build order and supersedes §9's phases.
§16 carries the migration decisions, Appendix E the SQL. Step 1 depends on nothing and can start
immediately; everything from Step 2 touches schema.

**What this supersedes:** `TODO.md:1000` *"Refactor the profile page"*. That entry's two live bugs
were fixed on 2026-08-17. Its three open threads are now settled: **modal-vs-page** → a page at
`/account` (Decision 1); **identity-field restructuring** → `full_name` splits into `first_name` +
`family_name`, plus `age`, exactly as that entry asked (Decision 5); **signup capture** → those
three fields are captured at signup (§9, P0).

**How this was produced.** Four passes, deliberately from different angles, then reconciled
against the source by hand:

| Pass | Who | Question |
|---|---|---|
| Design direction | this session (frontend-design + impeccable, Operate mode) | What should this surface *be*? |
| Benchmark & gap | OpenCode · `openai/gpt-5.6-luna` @ xhigh, read-only | What do the 10 best chatbot account surfaces do, and where are we short? |
| Security | Antigravity · `gemini-3.7-flash-high`, read-only | What is exploitable now, and what does the expansion open? |
| UX critique | Claude Code · Sonnet, read-only | What mistakes does the community agree on, and which do we commit? |

Every claim below that names a `file:line` was re-read in this session before it was written down.
Where a delegate was wrong, §0.4 says so.

---

## [HISTORICAL] 0. Verified against the current source

### [HISTORICAL] 0.1 What the surface is today

One Bootstrap modal, `#profileModal`, at `web/templates/index.html:268-320`. Its whole content:

- three `form-floating` text inputs — `full_name`, `organization`, `specialization`
  (`index.html:283-297`)
- a two-radio theme group, Light / Dark (`index.html:298-310`)
- one full-width submit carrying a `spinner-border d-none` (`index.html:311-315`)
- one shared error region, `#profile-error` (`index.html:317`)

Entry is `#profile-button{{ suffix }}` in the sidebar account footer
(`web/templates/partials/_sidebar.html:117-120`), rendered twice — desktop aside and mobile
offcanvas.

That footer is the other half of the problem. `.sidebar-account`
(`_sidebar.html:113-141`) currently holds **five** controls: status text, auth button, profile
button, admin link, logout button, plus a language toggle. The macro's own comment says the block
is "chrome, not content… touched once a session" — and then gives it more controls than any other
region of the column.

### [HISTORICAL] 0.2 What the data path is

Reads and writes go **straight from the browser to Supabase**, under the anon key and RLS. Flask
is not in the path.

- `Services.getProfile` selects `id, full_name, organization, specialization, preferences`
  (`static/js/modules/services.js:665-675`)
- `Services.updateProfile` does `upsert({ id, ...updates }, { onConflict: 'id' })`
  (`services.js:677-684`)
- the payload is built at `static/js/modules/handlers.js:1514-1519`
- privilege columns `role` / `tier` / `is_disabled` are protected by a column-level `REVOKE` plus
  a `BEFORE UPDATE` trigger
  (`supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql:130-193`)

The routing model is **server-side Flask paths**. Flask serves `/` (`web/api/app.py:1833`) and
`/c/<uuid>` (`:1837`) and nothing else reader-facing. `static/js/modules/route.js` is a
*conversation pointer*, not a router — read its own docstring at `route.js:1-13`.

### [HISTORICAL] 0.3 The findings, re-verified

These are the ones I re-read the source to confirm, not the ones a delegate merely asserted.

**A. `preferences` is clobbered on every save.** `handlers.js:1518` sends
`preferences: { theme: … }` and `services.js:681` upserts it. The JSONB column is **replaced**,
not merged. Today there is exactly one key so nothing is lost — but the backfill in
`20260814005509…sql:118-127` seeds `{"theme": "system"}`, and the moment a second preference lands
(language, reduce-motion, density, newsletter) every save from any form that does not carry all of
them silently deletes the rest. This is the single most load-bearing structural fix in P0, because
every other preference in this plan sits on top of it.

**B. There are no length limits anywhere on the write path.** `profiles` carries exactly one
`CHECK` — `profiles_role_chk` (`20260814005509…sql:105-113`). `full_name`, `organization`,
`specialization` are unbounded `text`; `preferences` is unbounded `jsonb`; the inputs carry no
`maxlength` (`index.html:283-297`). Flask's admin path enforces 200 chars
(`web/api/admin.py:315`) — but Flask is not on the reader's write path. A reader can store
megabytes, and `admin_update_profile` copies the before/after rows into the append-only
`audit_log` (`20260814200342_admin_update_profile.sql:97-106`).

**C. A disabled account keeps full PostgREST access.** No RLS policy on `chat_sessions`,
`chat_messages`, or `chat_message_sources` checks `is_disabled`
(`20260820131914_chat_session_persistence.sql:177-195` — `using (owner_id = (select auth.uid()))`,
nothing more). `is_disabled` gates Flask only. A disabled reader holding a live JWT can still read
and **delete** their own transcripts directly. Independent of this refactor; in scope because this
page is where account standing gets shown.

**D. The privilege-guard trigger is `BEFORE UPDATE` only** and watches 3 of 7 administrative
columns (`20260814005509…sql:168-193`). Not exploitable while the column grants hold — Postgres
rejects an ungranted column at parse time — but the trigger exists precisely because that
migration's own comment (line 17) says Supabase re-grants table privileges on some schema
operations. A defence-in-depth layer with a hole in it is worth closing while we are here.

**E. The spinner is dead markup.** `spinner-border` appears in `index.html:312-313` and in the
signup form, and **zero times in `static/js`** (verified by grep across the tree). No code ever
removes `d-none`. Every save shows the reader nothing.

**F. Nothing guards the close.** No `dirty` tracking, no `hide.bs.modal` listener, no
`data-bs-backdrop` override on `#profileModal` (`index.html:271`). A backdrop click or Escape
discards typed edits silently. This is the only defect on the list that destroys the reader's work.

**G. Log out ends *every* session, everywhere, and nothing says so.**
`Services.logout` calls `signOut({ scope: 'global' })` (`services.js:426`). The comment there is
correct about why — OWASP asks for global revocation after a password change — but the button is
labelled plainly "Log out" (`_sidebar.html:129-131`) and a reader signing out on their phone also
loses their desktop. Right behaviour, absent disclosure.

**H. The modal shows a snapshot, not the account.** `loadProfileWithTimeout` fills
`AppState.userProfile` once at sign-in (`static/js/app.js:405-409`) and
`handleProfileButtonClick` reads the cache first (`handlers.js:1547-1555`). `TODO.md:1031-1039`
already records this.

**I. The modal never says whose profile it is.** No email, no identity line — only the static
heading (`index.html:274-280`). This codebase already treats the shared machine as a real threat
elsewhere; here it does not.

### [HISTORICAL] 0.4 Where a delegate was wrong

- **The UX pass called `route.js` "this app's hash router" and recommended `#/settings`.** It is
  not a hash router and it routes nothing but conversations (`route.js:15-32`). Corrected in
  Decision 1; the benchmark pass got this right independently.
- **The UX pass recommended keeping the modal "at the current scope."** That recommendation is
  sound *given the current three fields*, and it explicitly names its own trigger to move — "the
  day this surface gains a genuinely separate concern — account deletion, export, a session list."
  This plan adds all three, so the condition is met, not dodged.
- **The benchmark pass proposed `/settings`.** Renamed; see Decision 1.
- **The security pass rated the missing `frame-ancestors` as Low, mitigated by a default
  `X-Frame-Options`.** Accepted as written, and it stays on the P0 checklist because it costs one
  line.

---

## [HISTORICAL] 1. The design direction

### [HISTORICAL] 1.1 Mode and thesis

**Operate.** The reader arrives with a task — change a thing, check a thing, leave. Scanability
and native expectation outrank expression. The brand lives in precise detail, not in a gesture.

The thesis is one sentence: **this is not a form, it is a record.**

That is not decoration; it comes out of the product's own world. SFDA is a regulator, and the
design system already calls itself "a regulatory instrument that is pleasant to sit in front of"
(`DESIGN.md:3`). A regulator keeps a file on you, and the honest, useful thing an account page can
do is *show you your file*: what is on it, who can change what, and how to take it back. That
framing does real work — it is why role and tier appear (they are on the file and you cannot
change them), why the data section states what deletion does *not* remove, and why the page is a
scroll of ruled sections rather than a set of tabbed panels.

### [HISTORICAL] 1.2 The signature — the standing line

One memorable element, and everything else stays quiet.

Under the account name sits a single line set in `--font-mono`, the family this system reserves for
**machine-reported facts** (`tokens.css:110-113`) and never as a costume for "technical":

```
ROLE user  ·  TIER free  ·  SINCE 27 Apr 2026  ·  43 CONVERSATIONS  ·  ACTIVE
```

It earns its place because every value in it is a fact the *system* asserts about the reader and
the reader cannot edit — which is exactly what the mono voice already means here. It is also the
one place the product answers "what do you have on me" in a sentence, and it is the natural
in-page link into the data section. Marked with `--confidence` (marigold), the token the system
already assigns to "small active marks" (`tokens.css:47-49`).

`ACTIVE` becomes `DISABLED` with `--danger` when `is_disabled` is set, which is how account
standing reaches this page without a separate banner.

Everything else on the page is hairlines, labels, and controls. That is the Chanel edit: the
standing line is the accessory, so nothing else gets one.

### [HISTORICAL] 1.3 What this page is deliberately not

- **Not tabs.** Five sections, roughly fifteen controls. Tab chrome costs more height than the
  content it hides, and it makes "read my whole record" — the actual reason to open the page —
  a five-click job. Tabs earn their keep at twenty sections.
- **Not cards.** The sidebar already established this product's idiom for chrome: "a quiet footer
  under a hairline rather than a filled card" (`_sidebar.html:108-112`). Filled cards at page scale
  would contradict a decision this codebase already made and wrote down.
- **Not a dashboard.** No counters for their own sake, no charts. The one number on the page
  (conversation count) is there because it is the handle on the data section.
- **Not an avatar uploader.** See Decision 4.

### [HISTORICAL] 1.4 Layout

Single content column, capped near `--measure` for the prose and widening only for control rows.
On `≥lg`, a sticky section index on the inline-start edge; below that, the index collapses to a
horizontally scrolling chip row pinned under the header. Sections are `<section id="…">` separated
by `--hairline`, each with an `h2` and, where the section has a consequence, one line of plain
explanation under it.

Section anchors are real: `/account#security` is a URL you can put in an email.

---

## [HISTORICAL] 2. Decisions

### [HISTORICAL] Decision 1 — A server-rendered page, and it is `/account` — **DECIDED 2026-08-22**

Build `GET /account` as a Flask route with its own Jinja template. Retire `#profileModal`.
Confirmed by the owner; the path is settled before anything links to it.

**Why a page.** Three independent reasons, none of them aesthetic:

1. **The content does not fit a modal.** Identity + preferences + security + data + deletion is a
   scrolling document inside a scrim — the worst reading container in this app. Nested confirmation
   (delete-account inside the profile modal) needs modal stacking that Bootstrap 5 does not support
   without hacks.
2. **The URL has to be able to name it.** "Change your password" in an email must land on
   `/account#security`. A modal cannot be linked, bookmarked, refreshed, or reached with Back.
3. **The precedent already exists and works.** `admin.console` (`web/api/admin.py:101`) is a
   second server-rendered page in this app whose shell renders **nothing privileged** — the
   template's own comment says so — and hydrates over an authenticated fetch, because a document
   navigation cannot carry a bearer header. `/account` copies that shape exactly.

Impeccable's Operate guidance puts it more bluntly: *"Modal as first thought. Modals are usually
laziness. Exhaust inline / progressive alternatives first."* We have exhausted them; the surface
outgrew the container.

**Why `/account` and not `/settings`.** Two reasons. The product's vernacular is regulatory, and
this page is dominated by identity, standing, security and data rights — the *record* — rather than
by knobs. And `/settings` collides with `app_settings` and `/admin/api/settings`, which are the
operator's runtime configuration; two things called settings in one codebase is a naming debt we
would be choosing on purpose.

**What stays in the sidebar.** The five-control footer collapses to **one account button** that
opens a menu: the reader's name and email at the top, then Account, Admin (when applicable),
Language, Theme, Log out. The menu is the quick action; the page is the record. This un-crowds the
footer the macro's own comment already flagged as over-loud, and it is the pattern every product in
the benchmark set converged on.

### [HISTORICAL] Decision 2 — Save model split by reversibility, not by section

| Kind | Model | Why |
|---|---|---|
| View preferences (theme, language, reduce-motion, density) | **Apply instantly, save instantly**, inline "Saved" mark | The control *is* the preview. A Save button for a theme radio is the bug in §0.3-A's neighbourhood — you cannot preview a thing and also defer it. |
| Identity fields (name, organization, specialization) | **Explicit save**, per-section, button disabled until dirty, dismissal guarded | A half-typed name is not a fact you file. Autosave-on-blur fires redundant writes and leaves the reader unsure what "saved" covered. |
| Security actions (email, password, revoke sessions) | **One action per form**, re-authentication first, specific confirmation | Each is a separate consequence; a shared Save across them makes one failure roll back four. |
| Destructive (delete conversations, delete account) | **Its own flow**, typed confirmation, no shared Save anywhere near it | See Decision 9. |

The dirty guard is the highest-value single fix in this document (§0.3-F). Match the house style:
an inline confirm in place, as the conversation-row delete already does (`DESIGN.md:327`), not a
second modal.

### [HISTORICAL] Decision 3 — Theme gets exactly one source of truth

Today there are two controls that both "work" and can disagree — the instant `.theme-toggle-btn`
and the modal's radios — and `ui.js:835-844`'s own comment documents the divergence.

Resolution: **`profiles.preferences.theme` is the truth; `localStorage` is its mirror.**

- The account page offers a three-way segmented control: **Light / Dark / System**. Three, not two —
  the migration already seeds `{"theme": "system"}` (`20260814005509…sql:118-127`) and the UI has
  never offered the value it seeds.
- Selecting applies immediately and writes immediately.
- The header toggle stays as a quick flip and writes the same store when signed in.
- `localStorage` continues to feed the pre-paint FOUC script (`admin.html:41-46` shows the pattern);
  it is a cache, and the page says so nowhere because it does not need to — the two can no longer
  disagree.

The radio pair, and `UI.selectThemeRadio` with it, is deleted.

### [HISTORICAL] Decision 4 — Generated initials. No avatar upload. **Not now, and probably not ever.**

The monogram takes one initial from `first_name` and one from `family_name` — Decision 5 makes both
available, which is the one place that split pays a direct dividend on this page. It falls back to
the first grapheme of the generated `full_name` when only one is set, and to the email's first
character when neither is. It closes the identity-confirmation gap (§0.3-I) at zero engineering
cost.

Take initials by **grapheme, not by byte or by `charAt(0)`** — an Arabic given name's first
grapheme is a cluster, and slicing it produces a broken glyph.

Upload is declined on product grounds: this is a professional regulatory tool where people identify
by organization and specialization, not a social product where a photo carries signal. And the
security pass priced it out — an `avatars` bucket brings SVG-XSS, path-traversal overwrite,
decompression bombs, MIME allow-listing, magic-byte validation, size caps, storage CSP, and bucket
RLS, all of it for a decorative circle.

Declining it deletes an entire threat surface. That is the "remove one accessory" call in this
design, and it is the cheapest one available.

### [HISTORICAL] Decision 5 — Split `full_name` into `first_name` + `family_name`, and collect `age` — **DECIDED 2026-08-22**

**Owner decision, and it overrules this plan's first recommendation.** The draft argued against
both. The owner settled it the other way and supplied the missing piece of the case for `age`: it
is collected **for marketing**. `TODO.md:1021-1030` is therefore confirmed rather than superseded,
and the work below is scheduled rather than debated.

The dissent is kept as `TODO.md`-style history, not re-argued: Arabic naming (ism / nasab / laqab)
does not decompose cleanly into two boxes, and a stored `age` is wrong within twelve months of
being entered. Neither blocks the decision; both shape how it is built.

**How the split is built — a generated `full_name`, not a dropped one.**

The naive migration drops `full_name` and rewrites every reader of it. That is the expensive
version, and it is avoidable. Instead:

```sql
alter table public.profiles
  add column if not exists first_name  text,
  add column if not exists family_name text,
  add column if not exists age         smallint;
```

> **WITHDRAWN — do not run the automated backfill this section originally carried.** It used
> `split_part(trim(full_name), ' ', 1)` as the given name. §15.2 queried the live table: there are
> **four rows**, three names, and **two of them begin with `Dr.`** — a title. That backfill would
> file "Dr." as two readers' given name. The correct migration **hand-maps the three names as
> explicit literals** and records which values were mapped and why, per the repo's rule 7. A general
> algorithm for three instances is how the wrong data gets written confidently.

Then `full_name` is **rebuilt as a generated column** over the two new ones:

```
full_name generated always as (
  nullif(trim(coalesce(first_name,'') || ' ' || coalesce(family_name,'')), '')
) stored
```

Why this shape earns its keep: every *read* of `full_name` keeps working unchanged — the monogram,
the sidebar identity line, the admin People list, `admin_get_user`, and the
`SUPABASE_BROWSER_MOCK` `from('profiles')` chain in `web/tests/conftest.py` that pins today's
column set. Only the *write* path changes. That converts "rewrite every reader of the name" into
"stop writing one column and start writing two", which is a materially smaller and less risky
migration.

Consequences that must ship with it:

- `full_name` leaves the `INSERT`/`UPDATE` column grants — a generated column cannot be written,
  and PostgREST emits every payload column on upsert, so leaving it in the grant would break the
  save with a confusing error rather than a clear one.
- `first_name`, `family_name`, `age` join the grants in its place.
- `handle_new_user` reads `first_name` / `family_name` / `age` out of the signup metadata instead
  of `full_name`.
- `admin_update_profile` (`20260814200342…sql`) gains the three columns; its audit `before`/`after`
  records them.
- The account page shows two name fields; the monogram takes one initial from each.

**Age: the shape, and the one flaw to design around.**

```sql
alter table public.profiles
  add constraint profiles_age_chk check (age is null or age between 13 and 120);
```

`smallint`, nullable, optional. Nullable and optional are not softness — a required field here
would block the account page for every existing reader who has never seen it.

The flaw is decay: a stored age is a snapshot, and it is silently wrong a year later. Two honest
options, and this plan implements the first because it is what was asked for:

1. **Store `age` as decided**, and pair it with the `updated_at` the `on_profile_update` trigger
   already maintains, so any marketing read can at least tell how stale the number is.
2. *(alternative, one column different)* store `birth_year smallint` and derive age in the query.
   It never decays, and it is no more sensitive than the age it replaces. If marketing segments are
   ever built on age bands, this is the version that keeps working; say so before the first
   segment is cut, not after.

**What collecting age for marketing obliges.** Naming this once so it is not discovered later: age
gathered for marketing is personal data processed for a secondary purpose, in a product whose own
reader-facing disclosure tells people not to enter personal data (`en.yaml:66-72`). Three things
follow, and all three are cheap if done at build time:

- The field states its purpose where it is asked for — signup and the account page — in one plain
  line, in both languages.
- It stays optional, and blank stays a first-class answer.
- The Data section (§3) lists it among what is stored, and account deletion removes it.

**What this disturbs**, now scheduled rather than hypothetical: `handle_new_user`,
`admin_update_profile`, the admin account-detail view, `conftest.py`'s mock column set, the signup
form and `Services.signup`, and every i18n key that says "Full Name". All of it is listed in §8.

### [HISTORICAL] Decision 6 — `preferences` stops being clobbered

Two changes, both P0:

1. Writes merge rather than replace. Either read-modify-write against a fresh read, or — better,
   because it is atomic and cannot lose a concurrent write — a small `security definer` RPC doing
   `preferences = coalesce(preferences,'{}'::jsonb) || p_patch`.
2. A `CHECK` bounding `octet_length(preferences::text)`, per §0.3-B.

Without this, every preference added later is a bug waiting for a second form to save.

### [HISTORICAL] Decision 7 — Say that log out is global

Minimum, P0: the log-out control states its scope in one line — signing out ends the session on
every device. Once the session list ships (P1), it becomes a real choice: end this session, or end
all of them.

The behaviour is right (`services.js:419-425` explains why); only the silence is wrong.

### [HISTORICAL] Decision 8 — Reads stay on Supabase. Security actions go through Flask.

Profile reads and preference writes stay on the existing browser→PostgREST path — it works, it is
under RLS, and moving it would be a rewrite with no security gain once the column bounds of
Decision 6 land.

Everything in the Security and Data sections goes through **authenticated Flask routes**: email
change, password change, session revocation, export, deletion. Those need re-authentication, rate
limiting, service-role calls into GoTrue, and streaming — none of which a browser holding an anon
key can or should do. Flask already has the shape for it (`web/api/admin.py:318,432,519` do exactly
these operations for the operator).

**"Authenticated" is not specific enough, and the gap it leaves is one this codebase has already
written about.** `_get_token_from_request` (`web/api/app.py:269-273`) accepts a **cookie** and the
Flask session as well as a bearer header — which is right for the chat routes and wrong here.
`web/api/admin.py:16-20` says why, about its own API: *"a cookie-authenticated privileged mutation
is CSRF-shaped, and this app has no CSRF protection to answer it with."* On the default posture,
`DELETE /api/account` and `POST /api/account/password` are cross-site forgeable — a hostile page
could delete the account of anyone browsing with a live session.

So, precisely: **every `/api/account/*` route accepts a bearer header and nothing else, enforced by
a `before_request` gate on the blueprint** — not per-route decorators. That file gives the reason
for the gate too: *"A decorator can be forgotten on route nine, and the failure is silent."* This
costs nothing on the client side, because the account page hydrates over an authenticated fetch
exactly as `admin.console` does.

**And every limit on those routes keys on the authenticated user id, never the IP.** Flask-Limiter
defaults to remote address, and this repo already documents why that is wrong here:
`web/config.yaml:88-93` worries about "the 200/day budget an office behind one NAT shares." Three
email changes an hour *per building* is an outage, not a limit. `limiter.limit()` takes a
per-route `key_func` for exactly this.

Which surfaces the sharpest fact in this document: **today an administrator can reset your
password, revoke your sessions, and change your email — and you cannot do any of those to your own
account.**

### [HISTORICAL] Decision 9 — Deletion is named honestly, or not offered

Three different things get three different names and three different confirmations:

| Action | What it removes | What it does not |
|---|---|---|
| Delete a conversation | that transcript and its sources | nothing else |
| Delete all conversations | every transcript | the account, the profile, backups |
| Delete account | the account, the profile, every transcript | dormant `chat_archive` rows and provider backups |

The last row is not a footnote — `chat_sessions` deliberately carries **no FK to `auth.users`**
(`20260820131914…sql:38-42`), so deleting an account leaves orphaned transcripts unless a purge RPC
handles them explicitly. And `profiles.disabled_by` / `app_settings.updated_by` reference
`auth.users(id)` with no `ON DELETE SET NULL`, so deleting an *administrator* raises `23503` and
aborts. Both must be fixed before deletion is offered at all.

The copy states what is *not* removed. A deletion flow that overpromises is worse than none.

---

## [HISTORICAL] 3. The information architecture

```
/account
├── Header — brand mark → /, page title, back
├── Record
│     monogram (2 initials) · full name (generated) · email (bdi-isolated)
│     ROLE · TIER · SINCE · N CONVERSATIONS · STANDING     ← the standing line
├── § Identity                                   explicit save, dirty-guarded
│     first name · family name · age · organization · specialization
├── § Preferences                                instant apply, instant save
│     theme (Light/Dark/System) · language · reduce motion · text size
├── § Security                                   one action per form, reauth first
│     email + verification state · password · active sessions · end other sessions
├── § Your data                                  explicit request per action
│     what is stored and why · export conversations · delete all conversations
└── § Delete account                             typed confirmation, its own flow
```

**Identity row order and treatment.** First name and family name sit on one row at `≥sm` and stack
below it — never side-by-side on a phone, where two half-width text inputs are the classic
cramped-form failure. `age` is a short numeric input, not a slider and not a dropdown of 108
options, and it carries its purpose line ("used for audience segmentation — optional") directly
under it rather than in a tooltip. Organization and specialization keep full width.

**Per-section state contract.** Every section ships four states, distinctly — the conversation list
already states this principle for a different surface (`DESIGN.md:328`) and the reason is the same:
collapsing *empty* into *unavailable* tells the reader "you have nothing" when the truth is "we
could not check."

- **loading** — skeleton, not a spinner in the middle of content
- **empty** — teaches what would be here
- **error** — says what failed and offers retry, preserving any typed edits
- **saved** — inline and persistent, not only a 3s toast

---

## [HISTORICAL] 4. Server changes

1. **`GET /account`** in `web/api/app.py`, beside `/` and `/c/<uuid>`. Renders a shell with no
   privileged data, exactly as `admin.console` does. Add `X-Robots-Tag: noindex, nofollow`.
2. **A module import map for the page.** Follow `admin.console`'s pattern
   (`web/api/admin.py:110-125`): the account modules import the shared ones, so both directories go
   in the map or an unmapped import escapes the cache-buster.
3. **New authenticated API routes**, all rate-limited via the existing `limiter`:
   - `POST /api/account/email` — reauth + GoTrue secure email change
   - `POST /api/account/password` — reauth + `updateUser({password})` + global revocation
   - `GET /api/account/sessions` — opaque metadata only: created, last seen, truncated IP,
     UA description. Never a token or a token hash.
   - `POST /api/account/sessions/revoke` — one session, or all others
   - `GET /api/account/export` — **streamed** (`Response(stream_with_context(...))`, NDJSON), scoped
     by `owner_id = auth.uid()`, never by a client-supplied id
   - `DELETE /api/account` — the purge RPC of Decision 9, then GoTrue delete
4. **`frame-ancestors 'self'`** added explicitly to the CSP. One line; clickjacking an account form
   is a real path to a silent credential change.
5. **Signup carries the three new identity fields.** `web/api/auth.py`'s signup leg and
   `Services.signup` pass `first_name`, `family_name` and `age` as user metadata, and
   `handle_new_user` reads them out — so an account starts with real identity data instead of the
   empty strings the backfill writes today (`20260814005509…sql:118-127`). Age stays optional at
   signup; a required demographic field on a registration form is a conversion tax and a consent
   problem at once.

**Rate limits** (security pass, adopted): email change 3/hr, password change 5/hr, export 2/10min,
deletion 3/hr.

---

## [HISTORICAL] 5. Client changes

- **New:** `static/js/account/` — its own directory beside `static/js/admin/`, its own
  `account.css`. Add the filenames to the module tuple in `web/api/app.py:249-262`.
- **Deleted:** `#profileModal` (`index.html:268-320`); `handleProfileButtonClick` and
  `handleProfileFormSubmit` (`handlers.js:1494-1572`); `UI.populateProfileForm` and
  `UI.selectThemeRadio` (`ui.js:818-850`); the `PROFILE_*` selectors (`config.js:91-95`); the
  `profileModal` instance (`app.js:321-326`) and its `AppState` slot (`state.js:14`).
- **Changed:** `Services.getProfile` (`services.js:665-675`) selects `first_name, family_name, age,
  full_name` alongside the existing columns — `full_name` stays in the `select` because it is now
  generated and is what the display line and the fallback monogram read.
  `Services.updateProfile` (`services.js:677-684`) stops sending `full_name` at all (it is
  generated — sending it fails the write), sends the two name columns and `age` instead, and stops
  upserting a whole `preferences` object in favour of the merge RPC.
  `ErrorHandler.showProfileError` (`dom.js:237`) moves with the surface — note
  `test_frontend_architecture.py` currently pins it to `handlers.js`, so that test moves too.
- **Signup form:** `#signup-pane` (`index.html:227-258`) gains first name, family name, and an
  optional age, passed as user metadata by `Services.signup`.
- **Sidebar:** `.sidebar-account` (`_sidebar.html:113-141`) collapses to the account menu of
  Decision 1.
- **`maxlength`** on every text input, matching the new `CHECK` bounds — the client hint, not the
  enforcement. `age` gets `inputmode="numeric"` with `min`/`max` matching `profiles_age_chk`, and
  is validated client-side before the request rather than discovering the constraint as a generic
  save failure.
- **`autocomplete`** — `given-name`, `family-name`, `organization` — and `dir="auto"` on every
  reader-typed text field. Conversation titles already carry `dir="auto"` for exactly this reason
  (`DESIGN.md:325`); the rule did not get carried to the profile inputs. `age` is a number and
  takes neither.
- **Wire the spinner.** The markup already exists (§0.3-E) — toggle `d-none` and disable the button
  for the duration of the request.
- **`<fieldset>` / `<legend>`** around every radio group, and `.form-check-input` sized to ≥24×24 CSS
  px. Bootstrap 5.3's default is `1em`, under WCAG 2.2 Target Size (Minimum) AA, and no override
  exists in `components.css`.
- **Drop the hand-authored `role="dialog" aria-modal="true"`** where it duplicates Bootstrap's own
  runtime semantics.

---

## [HISTORICAL] 6. Database & security changes

Ordered by when they must land. Each is its own migration — the repo's rule 1 and rule 2
(`supabase/README.md`).

**P0, in this order.** The identity split goes *last* of the four, because bounding the columns and
merging preferences are prerequisites it would otherwise be written against twice.

**1 — Bound the reader-writable columns.** §0.3-B.

```sql
alter table public.profiles
  add constraint profiles_full_name_len_chk
    check (full_name is null or char_length(full_name) <= 200),
  add constraint profiles_organization_len_chk
    check (organization is null or char_length(organization) <= 200),
  add constraint profiles_specialization_len_chk
    check (specialization is null or char_length(specialization) <= 200),
  add constraint profiles_preferences_size_chk
    check (preferences is null or octet_length(preferences::text) <= 4096);
```

> **`profiles_full_name_len_chk` is dropped again in §6·5**, at the moment `full_name` becomes a
> generated column. It has to be: §6·5 bounds `first_name` and `family_name` to 100 characters
> *each*, and 100 + 1 + 100 is **201** — so two values that each pass their own check produce a
> generated value that fails this one, and the save dies naming a column the reader never touched.
> Do not paper over it with a combined budget. A generated column cannot be written; its only
> possible value is the concatenation of two already-bounded columns, so the check verifies nothing
> the schema does not already guarantee and the only thing it can do is reject a valid write.

**2 — Trigger to `BEFORE INSERT OR UPDATE`**, covering `disabled_at`, `disabled_by`,
`disabled_reason`, `last_seen_at` alongside `role` / `tier` / `is_disabled`. §0.3-D.

> **Corrected per §14·C·12 / T1, applied as `20260822224942`.** `old` is `NULL` on `INSERT`, so a
> diff-based check (`new.role is distinct from old.role`) rejects every new profile row — the
> column default `'user'` is always "distinct from" a nonexistent old row. The `INSERT` branch
> **asserts literal values instead of diffing against `old`.** See the applied migration for the
> exact SQL.

**3 — `public.is_active_account()`** — `stable`, `security definer`, `set search_path = ''`,
execute revoked from `anon`/`public` — added to the `using` clause of every reader-facing RLS
policy on `chat_sessions`, `chat_messages`, `chat_message_sources`. §0.3-C.

**4 — The `preferences` merge RPC.** Decision 6.

**5 — The identity split.** Decision 5, and it is **three migrations, not one**, because the
repo's rule 2 keeps a destructive step off the back of a safe one:

- `…_profile_identity_columns.sql` — add `first_name`, `family_name`, `age`; add
  `profiles_age_chk` and the two new length checks; backfill from `full_name`; index nothing (no
  FK, and no sort ships in P0).
- `…_profile_full_name_generated.sql` — **destructive, its own migration.** Drop `full_name`,
  re-add it `generated always as (…) stored`, move it out of the `INSERT`/`UPDATE` grants and put
  the three new columns in. Records the row count checked and the spot-check on the backfill, per
  the repo's rule 7. **Take a backup of `full_name` values first** — the split is lossy and this is
  the step that makes it irreversible.
- `…_profile_identity_rpcs.sql` — `handle_new_user` reads the three fields from signup metadata;
  `admin_update_profile` gains them in its parameter list and its audit `before`/`after`.

```sql
alter table public.profiles
  add constraint profiles_age_chk
    check (age is null or age between 13 and 120),
  add constraint profiles_first_name_len_chk
    check (first_name is null or char_length(first_name) <= 100),
  add constraint profiles_family_name_len_chk
    check (family_name is null or char_length(family_name) <= 100);
```

**Before deletion ships (P2):**

- `ON DELETE SET NULL` on `profiles.disabled_by` and `app_settings.updated_by`.
- `public.delete_user_account()` — one transaction: purge `chat_sessions` (cascading messages and
  sources) by `owner_id`, null the two back-references, delete the `profiles` row, then GoTrue
  delete. Explicitly **not** touching `chat_archive`, and the reader-facing copy says so.

**Not shipping:** the `avatars` bucket and its policies. Decision 4.

**Verification after each migration**, per `supabase/README.md`: `list_tables`, `list_migrations`,
`get_advisors security`, `get_advisors performance`. Anything not already on that file's table of
standing findings is a regression from the migration just applied.

---

## [HISTORICAL] 7. RTL and bilingual

Arabic is half the audience, so the page is laid out and reviewed in Arabic **first**.

**Already right, and must stay right.** Every `letter-spacing` in all five stylesheets is
`var(--track-*)`, never a literal — which is why the blanket `[dir=rtl] *` reset
(`tokens.css:281-282`) has nothing to catch. That reset is **not a safety net**: it is a single
class-specificity selector, so any later rule hardcoding tracking wins on a tie. New CSS uses the
tokens, always.

**Three specific traps this page introduces that the modal never had:**

1. **The standing line mixes scripts and machine values.** Isolate each value with an inline `<bdi>`
   — never `dir="ltr"` on a block box, which also flips that box's `text-align: start` to the wrong
   edge (`match-parent` is not supported in current Chrome).
2. **"Since" is a date.** Do not use `toLocaleDateString('ar')` — it embeds U+200F marks that bidi
   reorders even inside an isolate. Build the string from `Intl.DateTimeFormat.formatToParts`.
3. **The sticky section index and the save bar are positioned.** Logical properties only
   (`inset-inline-start`, never `left`) — `test_css_contract.py` enforces this and will fail the
   build, which is the intended outcome.

**Also:** the section index must not imply that danger sits on a physical side; reading order is
heading → explanation → label → field → error → actions in both directions; and do not reverse
button order in CSS alone, because the DOM order is what a screen reader follows.

**Review in Arabic before shipping:** longest section labels, validation messages, security
warnings, the delete-account confirmation, pending-email copy, and organization names that mix
Arabic and Latin in one field.

---

## [HISTORICAL] 8. What this disturbs

**Tests that will fail, by name.** Each is a real contract, not incidental:

| Test | Why it breaks | What to do |
|---|---|---|
| `test_frontend.py:25` | asserts `#profile-button` visible after sign-in | retarget to the account menu trigger |
| `test_profile_theme_integration.py` (3 browser tests) | drives `#profile-button` → `#profileModal`, and asserts the `getProfile`/`updateProfile` wire contract against the `SUPABASE_BROWSER_MOCK` chain in `conftest.py` | rewrite against `/account`; the mock's `from('profiles')` chain moves with the payload shape |
| `test_theme_toggle.py:10`, `test_rtl.py:191`, `test_password_recovery.py:167` | assert exactly **three** `.theme-toggle-btn` on the reader page | the account menu's theme entry must not be a fourth `.theme-toggle-btn` — the sidebar macro already documents this exact hazard (`_sidebar.html:13-16`) |
| `test_admin_page.py:90`, `test_admin_browser.py:133` | assert exactly one on the admin page | `/account` needs its own count assertion added, not inherited |
| `test_frontend_architecture.py` | pins `showProfileError` to `handlers.js`, and pins each profile call site to its i18n key | both move with the surface; update, do not delete |
| `test_css_contract.py` | logical properties, enforced | new CSS complies or the build fails |
| `conftest.py`'s `SUPABASE_BROWSER_MOCK` | its `from('profiles')` chain asserts the exact column set `{id, full_name, organization, specialization, preferences}` | add `first_name`, `family_name`, `age`; `full_name` stays (generated, still selected) but must disappear from every write payload |
| every test asserting a name value | `full_name` is no longer written | write the two columns, assert the generated one |
| `test_admin_audit.py`, `test_account_recovery.py` | `admin_update_profile`'s parameter list and its audit `before`/`after` gain three columns | extend the expected audit shape |

**Also required on every commit:**

- **Bump `ASSET_VERSION`** (`web/api/app.py:231`, currently `"warm39"`) on any CSS or JS change.
- **Both catalogues.** Every new `page.account.*` and `runtime.account.*` key ships in
  `web/i18n/en.yaml` **and** `web/i18n/ar.yaml` — `test_arabic_catalogue_covers_every_runtime_key`
  fails if Arabic lags. The existing `page.profile.*` (`en.yaml:536-545`) and `runtime.profile.*`
  (`en.yaml:186-191`) keys are renamed, not orphaned. `page.profile.fullName` (`en.yaml:539`) is
  **replaced** by `firstName`, `familyName` and `age` — plus `age`'s purpose line, which is new copy
  in both languages and needs a real Arabic translation, not a transliteration.
- **New module filenames** added to the tuples at `web/api/app.py:249-262`, or their imports escape
  the cache-buster.

---

## [HISTORICAL] 9. Phases

### [HISTORICAL] P0 — The record exists, and it tells the truth

Ship the page and make what already exists trustworthy. No new capability the reader can misuse.

**Schema first**, in the order §6 gives:

1. Column bounds + trigger hardening + `is_active_account()` in RLS (§0.3-B, -C, -D).
2. `preferences` merge RPC (Decision 6).
3. The identity split — three migrations, backup before the destructive one (Decision 5, §6·5).

**Then the surface:**

4. `GET /account` + template + `static/js/account/` + `account.css`.
5. Identity section with first name, family name, age, organization, specialization; monogram from
   the two initials; the email line and the standing line.
6. Theme becomes Light/Dark/System, one source of truth (Decision 3).
7. Dirty tracking + guarded dismissal + wired spinner + skeleton/empty/error/saved states.
8. `dir="auto"`, `maxlength`, `autocomplete`, `inputmode`, `fieldset`/`legend`, 24px targets.
9. Fresh read on open — never the sign-in snapshot (§0.3-H).
10. Signup captures first name, family name and optional age (§4·5).
11. Sidebar footer → account menu.
12. One line stating that log out is global (Decision 7).
13. `frame-ancestors 'self'`.

*Why this order:* items 1 and 2 are prerequisites, not polish — every later phase writes through
them, and item 3 would otherwise be authored twice. Item 3 is the only irreversible step in the
whole plan; it lands early, on its own, while the surface around it is still small enough to
verify by hand.

### [HISTORICAL] P1 — The reader can secure their own account

The phase that closes the "an admin can, you cannot" gap.

**Revised against the current Supabase docs — see §12·B. Two items in the original draft of this
phase were not buildable as written.**

- **Change password — via `reauthenticate()`, not a current-password check.** GoTrue has a
  first-class mechanism and it is not the one the security audit assumed: `supabase.auth
  .reauthenticate()` emails the reader a **nonce**, which is then passed inline to
  `updateUser({ nonce, password })`. There is no `verifyOtp()` step, and the client never handles
  the current password at all — which is strictly better than the "verify via `signInWithPassword`"
  design this plan previously carried. Note also the project setting *Require reauthentication when
  changing password*: with it on, a session created within the **last 24 hours** counts as recently
  logged in and skips the nonce; outside that window the nonce is required.
- **Change email — verify the project setting rather than schedule the work.** Dual confirmation is
  `mailer_secure_email_change_enabled` (`GOTRUE_MAILER_SECURE_EMAIL_CHANGE_ENABLED`), and **its
  default is `true`**, so this is probably already on: check before building anything. The desync
  `20260816215103…sql` records still applies — a GoTrue email change leaves `email_confirmed_at`
  intact while creating an unverified identity row, so the UI reads verification from the identity,
  not the timestamp. If custom bilingual templates are built (§12·C), note that dual confirmation
  sends **two different token pairs**: the current address gets `token` + `token_hash_new`, the new
  address gets `token_new` + `token_hash`.
- **There is no active-sessions list, and there cannot be one.** The GoTrue Auth OpenAPI spec
  defines exactly three admin paths — `/admin/generate_link`, `/admin/user/{user_id}`,
  `/admin/users`. **No endpoint enumerates a user's sessions.** Cut the list; ship the one action
  the API does support: **"Sign out everywhere else"**, which is `signOut({ scope: 'others' })`.
  This deletes a whole UI, its IDOR surface, and its "opaque metadata only" rule from the phase.
- **Log out becomes a real choice** — this device (`local`), or everywhere (`global`, today's
  behaviour). Scopes are `global` (the JS default), `local`, and `others`.
- **The copy must state that revocation is not instant.** Supabase is explicit: *"Access Tokens of
  revoked sessions remain valid until their expiry time, encoded in the `exp` claim. The user won't
  be immediately logged out."* A security control that reads as immediate and is not would be the
  plan's own "never claim what the product cannot honour" rule broken in the most costly place.
  This is also the second argument for `is_active_account()` in RLS (§0.3-C): revocation alone does
  not close the window, so the row policy has to.

### [HISTORICAL] P2 — Data rights

- Export conversations: streamed NDJSON, `owner_id` scoped server-side. If CSV is ever offered,
  neutralise leading `=`, `+`, `-`, `@`, tab and CR — spreadsheet formula injection.
- Delete all conversations, distinct in name and confirmation from account deletion.
- "What is stored, why, and what deletion does not remove" — plain prose, in both languages.
- Account deletion: the FK nullification, the purge RPC, typed confirmation, post-delete sign-out.
- Accessibility preferences: reduce motion (currently only read from the OS at
  `config.js:116-118`), text size, reading density.

**Explicitly not planned:** avatar upload (Decision 4); notification preferences until the product
actually sends more than one kind of notification.

---

## [HISTORICAL] 10. Decisions settled, and what is still open

**Settled 2026-08-22 by the owner:**

1. ~~Split `full_name` and collect `age`?~~ **Yes to both** — `first_name` + `family_name` + `age`,
   with `age` collected for marketing. Decision 5.
2. ~~`/account` as the path?~~ **Yes.** Decision 1.

**Still open — none of these block P0:**

3. **Does `age` decay, or does it become `birth_year`?** Decision 5 implements `age` as asked and
   names the flaw: the number is silently wrong a year after it is entered. If marketing ever cuts
   segments on age bands, `birth_year` is the version that keeps working. Worth answering *before*
   the first segment is built, not after.
4. Should signup also capture organization and specialization? First name, family name and age are
   settled (§4·5). These two are not — capturing them means two more fields on a registration form;
   not capturing them means new accounts start with empty strings, as they do today.
5. Where does the future Beehiiv newsletter opt-in live — `preferences.newsletter` synced by a
   server-side webhook, or synced at save? Carried forward unanswered from `TODO.md:1115-1117`.
   Decision 6 makes either safe; before it, neither is. Note this now sits next to `age`: an
   account holding a marketing-purpose age **and** a newsletter opt-in is a marketing dataset, and
   the consent copy should be written once, for both, rather than twice.
6. Is a reader allowed to delete their account at all, given this is a regulatory tool with an
   audit log? If retention wins, P2 offers deactivation rather than deletion — and says so plainly
   instead of hiding it.

---

## [HISTORICAL] 11. Sources

Design method: the `frontend-design` and `impeccable` skills (Operate mode, `reference/operate.md`
and `reference/shape.md`).

The three delegate reports are reproduced **verbatim and unedited** as Appendices A, B and C below,
so this file is the whole record and nothing has to be taken on trust from a summary. They are the
raw inputs, not conclusions: where §0.4 says a delegate was wrong, the appendix still contains the
wrong claim, deliberately.

| Appendix | Lane | Implementer | What it contains |
|---|---|---|---|
| **A** | Benchmark & gap | OpenCode · `openai/gpt-5.6-luna` @ xhigh, read-only (`plan` agent) | Ten surfaces — ChatGPT, Claude.ai, Gemini, Perplexity, Copilot, Notion, Linear, Slack, GitHub, Vercel — plus a 27-row gap table |
| **B** | Security | Antigravity · `gemini-3.7-flash-high`, read-only | Six findings (2 Medium, 2 Low, 2 Informational-and-secure) plus a six-component threat model for the expansion |
| **C** | UX critique | Claude Code · Sonnet, read-only | 23 mistakes across 11 categories, each marked committed-or-not against our source; contested ground; RTL failure modes |
| **D** | Adversarial debate | OpenCode · `openai/gpt-5.6-terra` @ xhigh, read-only | 17 findings against this plan, 2 Critical — briefed to attack rather than summarise. Carried into §14 |
| **E** | Migration SQL | OpenCode · `openai/gpt-5.6-sol` @ xhigh, read-only | Four production specs written against §15's verified live schema. Decisions in §16 |

None of the three touched the working tree. Every finding carried into §0–§9 was re-read against
the source before it was written down.

A fourth pass — an adversarial debate of this plan (OpenCode · `openai/gpt-5.6-terra` @ xhigh,
read-only) — plus an external human-directed review and a documentation check against current
upstream sources, are recorded in §14. **That section corrects things §0–§9 got wrong**, so read it
before implementing anything above.

---

## [HISTORICAL] 12. Signup capture, consent, and first-run

Settled with the owner on 2026-08-22, then revised on 2026-08-23 by the debate in §14.

### [HISTORICAL] 12.1 Two facts that shape everything here

**Signup does not sign you in.** Email confirmation was turned back on deliberately on 2026-08-14
(`TODO.md:436-450`); GoTrue refuses a session for an unconfirmed address. `Services.signup`
(`services.js:329-333`) sends `{ email, password }` straight to GoTrue with no `options.data`, and
`handleAuthFormSubmit` (`handlers.js:170-174`) does not even close the modal. The reader leaves the
site to click a link. **So there is no "step 2" after signup** — the second chance to ask lands at
first *confirmed* sign-in, in a later session.

**The metadata channel exists and has always shipped null.** `handle_new_user`
(`20260814005509…sql:51-70`) inserts `new.raw_user_meta_data ->> 'full_name'`, and because of the
point above that column has been `null` on **every account ever created by this form**. Adding
fields costs one argument, not a pipeline. *(Caveat per §14·D5: that is what the code path implies,
not a claim about the live table — nobody has queried it.)*

### [HISTORICAL] 12.2 What goes where

| Field | Where it is asked | Required |
|---|---|---|
| `first_name` | signup form | required **by this browser form only** — see §14·D4 |
| `family_name` | signup form | optional — requiring it forces a mononym reader to invent a name |
| marketing consent | signup form, unchecked | never required |
| `age` | revealed inline **only** when consent is ticked | never required |
| `organization` | `/account`, and the first-run strip | never |
| search scope | `/account` (see §12.5) | never |
| terms acceptance | deferred until the policy exists — §12.4 | required when it ships |

Two fields is the ceiling on the signup form. The auth modal is `modal-dialog-centered` with no
`modal-fullscreen-sm-down` (`index.html:130-131`); on a phone with the keyboard raised, a
five-input pane inside a centred modal is the cramped-modal failure.

### [HISTORICAL] 12.3 The consent checkbox is unchecked, and it gates the age field

**Not pre-checked.** A pre-ticked consent box fails twice over: it is a recognised dark pattern,
and under Saudi PDPL — and GDPR for any EU reader — consent must be an *affirmative act*, with
silence, inactivity and pre-ticked boxes excluded. It would produce a record that does not survive
being questioned. For a product positioned on traceability, whose name carries a regulator's
initials, that is a bad trade for a few points of opt-in.

**Gating is better than a standalone box** because it makes the ask self-explaining — you are asked
for age *because* you agreed to the purpose — and the personal question is never put to someone who
declined the purpose.

**Consent is a record, not a boolean.** But not the shape this plan first proposed — see §14·D3.
A single `marketing_consent_at` restamped in both directions records "last changed", losing the
grant time on withdrawal. Store instead: `marketing_consent`, `marketing_consent_granted_at`,
`marketing_consent_withdrawn_at`, and the policy version, language and surface the consent was
given on. Timestamps are set by trigger and excluded from the client grants; a browser that can
write its own consent timestamp can backdate a consent record. **Withdrawal is never rate-limited.**

**Withdrawal must be as easy as granting** — the same toggle on `/account`, and withdrawing offers
to clear the `age` collected under it. Do **not** add `check (marketing_consent or age is null)`:
that turns the offer into a mandate and fails every withdrawal where the reader declines the clear.

### [HISTORICAL] 12.4 The terms checkbox, and what blocks it

A **separate** required tick — never bundled with consent, because bundling is what invalidates it —
linking to a combined سياسة الاستخدام والخصوصية / Usage and Privacy Policy page in both languages.

**The document does not exist.** Verified: no privacy policy, no terms page, no legal route, no
link anywhere; the only matches for "policy" in the templates are a CSS comment and HTTP header
names. So this is not "wire a checkbox to a page" — it is "write a bilingual policy, publish it,
then wire a checkbox," and the writing is the larger half.

**It therefore blocks marketing collection, not the other way round** (§14·D2). The original
sequencing shipped the consent box before the disclosure it depends on. Corrected: no marketing
data is collected until the policy is approved and published.

Worth stating once: the product already collects personal data — email today — with no privacy
policy. That gap predates this feature and is not made acceptable by the feature being small.

**A copy trap.** `runtime.chat.historyNoticeWarning` (`en.yaml:71`) tells readers *"Do not enter
patient identifiers, clinical-trial subject data, personal information, or confidential or
proprietary material."* This feature then asks for their name and age. Reconcilable — one governs
the chat box, the other the account record — but only if the copy says so.

### [HISTORICAL] 12.5 Search scope, and the idea that did not survive review

The original proposal: `specialization` stops being free text, becomes a choice among the four
corpus categories, and sets the reader's default category in the composer.

**The taxonomy claim behind it was wrong** (§14·D1). PRODUCT.md's four audiences are not the four
corpus categories: clinical-trial sponsors map onto Regulatory (`faq.yaml:17-29` files clinical
trials there), pharmaceutical companies span all of them, and Veterinary Medicines and Biological
Products are *product domains, not job roles*. Two of four map, at best. A reader whose work spans
categories would get a default **narrower and worse than "All Categories"** — an active harm.

**Revised, and it is a better feature:**

- Model it as an explicit, reversible **search-scope preference**, stored separately, **not** as
  `specialization`. `specialization` keeps its free text; nothing is normalised and nothing is
  erased. (`conftest.py:48-54` already holds `"Regulatory Affairs"`, which the destructive
  normalisation would have thrown away.)
- **Default stays `all`.** On an unset, unreadable, or unrecognised value the safe direction is the
  *widest* scope — a failed profile read must never silently narrow which corpus a regulatory
  question is answered from.
- **Per-device last-used scope wins** for subsequent searches. It is the preference that actually
  reflects how someone works, needs no account field, and is reversible in one tap.
- If an account-level preferred category is offered at all, it is one optional setting on
  `/account`, applied **only before the first query interaction of that identity** — see below.

**The late-arrival hazard** (§14·D1). `loadProfileWithTimeout` is fire-and-forget (`app.js:405-409`),
so a saved preference can land *after* the reader has begun working. A `readerChose` flag guarding
only explicit listbox selection is not enough: a reader who has typed or submitted has also chosen,
implicitly. **Apply an account default only before the first query interaction for that identity;
after typing, sending, or focusing with content, stay on `all` until the reader picks.** And if
scope does change automatically, announce it properly — mutating `aria-label`
(`dropdown.js:67-70`) is not an announcement.

### [HISTORICAL] 12.6 First-run: one strip, queued rather than suppressed

Because of §12.1, "later" means first confirmed sign-in. Copy `.history-notice` exactly
(`ui.js:714-755`): reader-scoped `localStorage` key with a version constant, recorded **on
dismissal only** so an unread strip is not marked read, try/catch guarded so a storage failure
shows it again rather than never, and excluded from transcript sweeps.

**The arbitration rule and its bug.** A disclosure the product *owes* outranks a request it
*makes*, so the strip must not compete with `#history-notice`. But the first design — return early
if `#history-notice` is on screen — **hides the strip from exactly the new readers it targets**
(§14·D1): the history notice renders synchronously before the profile loads, and dismissing it
removes a node and writes `localStorage` without emitting anything that would re-run the completion
check. The reader would need a reload.

**Corrected: queue it.** One notice coordinator owns the slot for that identity; the history
notice's dismiss handler releases it and the queued prompt draws then. Two independent notices
inspecting each other's DOM is not a design.

**"Incomplete" means blank `first_name`** — and deliberately not `age` (blank is a first-class
answer, gated behind a consent that may have been declined), not `marketing_consent` (re-asking
for declined consent is nagware), not `family_name` (optional), not `organization`.

### [HISTORICAL] 12.7 Post-signup: the defect worth more than any field

The most important instruction in the funnel — "check your email" — is a **three-second toast in
hardcoded English** (`handlers.js:173`), after which the modal stays open showing a freshly-reset,
empty form. A reader who missed the toast sees *nothing happened*.

The fix already exists in the same modal: the recovery flow swaps its form for a persistent
`#reset-sent` panel with `role="status" aria-live="polite"` (`index.html:215-218`). Signup gets the
same, naming the address back so a typo is visible while it can still be fixed cheaply.

**Three strings on this path are hardcoded English** — `handlers.js:158`, `:168`, `:173` — against
a brand commitment of full EN/AR parity (`PRODUCT.md:129-130`). This is the class of defect
`TODO.md:1060-1071` recorded and fixed for the profile modal; the auth path was never swept.

**One of the three is deleted rather than translated.** `handlers.js:168` toasts
`` `Logged in as ${email}` `` while `auth-view.js:17` has already written "Logged in as: {email}"
into `#user-status` from the frozen key `runtime.auth.loggedInAs` — asserted verbatim at
`test_frontend.py:23` and `:287`. The product states the same fact twice, differing by a colon, one
untranslated. Drop the toast.

Ship this with a regression test mirroring
`test_frontend_architecture.py:50-72`, which asserts both that each key is read **and** that each
old literal is gone, so a revert fails loudly.

---

## [HISTORICAL] 13. Transitions between pages and floating surfaces

`/account` replaces a modal that faded in over the chat with a real document navigation. Done
naively that is a hard cut, and the first place the app would feel like a website rather than a
tool.

### [HISTORICAL] 13.1 The rule

**Local surfaces change elevation; document navigation changes context. A full page must not
pretend to be a larger popup.**

Dropdowns, modals, sheets and the offcanvas may use a short opacity/transform transition from their
trigger. A page navigation is a page navigation. And **no left/right travel for navigation** — it
carries no stable meaning under RTL.

This sits on top of what `effects.css` already says three times without generalising: turns "leave
the way they arrived" (`:149-154`), the mascot's return is "the inverse of the exit rather than a
generic fade" (`:233-235`), and the New chat glyph does not rotate because "a turning arrow reads
as *refresh*" (`:178-180`). Motion names what a thing is, never merely that it moved.

### [HISTORICAL] 13.2 Floating surfaces open from their trigger

The one place the app breaks its own rule today: Bootstrap modals fade in centred, from nowhere.
Measure the trigger, set two custom properties, animate `transform-origin`:

```js
const r = trigger.getBoundingClientRect();
dialog.style.setProperty('--from-x', `${r.left + r.width / 2}px`);
dialog.style.setProperty('--from-y', `${r.top + r.height / 2}px`);
```

It needs no `--flip`: a measured origin mirrors under RTL for free, which is the argument for
measuring rather than hardcoding an edge.

### [HISTORICAL] 13.3 `/account` is a plain link

The account-menu item is an ordinary `<a href="/account">`. No JS interception. It is
understandable on every browser, preserves Back, and needs nothing. Do not move focus to the `<h1>`
on ordinary arrival — only after an explicit in-page action.

### [HISTORICAL] 13.4 View transitions: progressive enhancement, scoped deliberately

```css
@view-transition { navigation: auto; }
.account-identity { view-transition-name: account-identity; }
```

**The shared element is the identity cluster** — the monogram plus name and email in the account
menu, becoming the account record's header. Not the whole sidebar, not the logo. The reader's own
initials travel up and become the header of their record, which animates *"this is you → here is
your file."*

Four constraints, all real:

1. **`_sidebar.html` renders twice** — desktop aside and mobile offcanvas (`index.html:547`,
   `:568`). `view-transition-name` must be unique among rendered elements, and a closed Bootstrap
   offcanvas is `visibility: hidden`, which still generates boxes. Assign the name by media query
   to the displayed copy only, or the transition silently does nothing.
2. **Availability is limited.** MDN currently labels `@view-transition` limited availability, and
   both documents must opt in. Treat it as enhancement; the fallback is today's navigation, which
   is the safest possible degradation. Verify support before relying on it.
3. **Do not enable it globally on the reader shell without deciding about `/` → `/c/<uuid>`.**
   That navigation would snapshot and animate a transcript, which may be sensitive.
4. **Reduced motion needs its own rule.** `base.css:347-355` collapses durations via a `*`
   selector, and `*` does not match pseudo-elements — view transitions are UA animations on
   `::view-transition-*` and would still play:

```css
@media (prefers-reduced-motion: reduce) {
  ::view-transition-group(*),
  ::view-transition-old(*),
  ::view-transition-new(*) { animation: none !important; }
}
```

### [HISTORICAL] 13.5 Sunny does not enter `/account`

`robotExit` already flies the mascot "upward, toward the chat" and `robotReturn` brings him back
"the way he left, with a settle" (`effects.css:226-241`). Keeping him out of the record page costs
nothing — he is simply not rendered — and earns two things: the record reads in a sober register
suited to security and deletion, and the return to chat gets a real moment for free from code that
already exists and is already correct. The restraint is what makes the return land.

Reuse the motion tokens (`tokens.css:143-158`), not `AuthView`'s mascot-coupled delayed fade
(`auth-view.js:62-79`).

### [HISTORICAL] 13.6 Two height reveals, no JS measurement

The signup → confirmation swap and the consent-gated age field are both height changes to `auto`:

```css
.reveal { display: grid; grid-template-rows: 0fr;
          transition: grid-template-rows var(--duration-s) var(--ease-out); }
.reveal.is-open { grid-template-rows: 1fr; }
.reveal > * { overflow: hidden; min-block-size: 0; }   /* min-block-size:0 is load-bearing */
```

**The signup swap must not cross-fade** — two things dissolving through each other reads as a
glitch. The form collapses while the panel expands into the same box, so the modal *settles* by the
height difference, which is what "completed" looks like. The recovery pane
(`index.html:202-217`) performs the identical swap today and gets it for free.

The age reveal must not move the submit button under a thumb mid-tap: reveal below the checkbox,
above the button.

### [HISTORICAL] 13.7 Where motion is refused

- **No page-load choreography on `/account`.** The ambient layer was deleted from this product once
  already, for this reason (`effects.css:5-8`).
- **No animation on the standing line's values.** Role, tier and standing are facts; animating a
  fact makes it look like a notification about a change that did not happen.
- **No motion on the consent checkbox.** A consent control that animates is one that persuades.
- **No transition on the delete-account confirmation.** Destructive confirmations should feel
  abrupt; softening them is confirmation theatre by another route.
- **Nothing during streaming.** The transcript is read while it is written.

---

## [HISTORICAL] 14. Review findings, and what they corrected

Three passes after the plan above was written: an adversarial debate (OpenCode ·
`openai/gpt-5.6-terra` @ xhigh, read-only), an external human-directed review, and a documentation
check against current upstream sources via `ctx7`. Each finding below was re-verified against this
repository or the upstream docs before being recorded.

**This section overrides §0–§13 wherever they disagree.**

### [HISTORICAL] 14·A — Corrections to claims this plan made

Owning these plainly, because the rest of the document's credibility rests on it.

1. **"A missing Arabic key renders the raw key" is false.** `load_catalog`
   (`web/utils/i18n.py:38-59`) deep-merges English as the base — *"Override wins, but missing keys
   keep the base (English) value"* — and `test_rtl.py:201-208` asserts it. A missing Arabic `page.*`
   key renders **English**, not `page.auth.signupSent.heading`. Still a real defect (an Arabic
   reader gets English, against a stated brand commitment) and still worth the `page.*` parity
   test, but silent-English, not visibly broken. Severity was overstated.
2. **"`specialization` is write-only" is overstated.** It is read back into the reader's own profile
   form (`ui.js:818-833`) and returned by the admin detail path
   (`20260814175551_account_detail.sql:56-59`). The accurate claim: **no downstream product
   decision uses these fields.** Same for `organization`.
3. **The `preferences` merge RPC is not a prerequisite for the consent or scope columns.** The
   upsert clobbers `preferences` because that column is a single JSON object; it does **not** erase
   omitted *top-level* columns. The merge RPC remains an important fix for future JSON preferences —
   it is simply not what unblocks these. Specify its `auth.uid()` binding, allowed patch keys,
   `authenticated` grant, and revoked `PUBLIC` before adding a `SECURITY DEFINER` write path.
4. **"`first_name` required" is a browser-form rule only.** The columns stay nullable for existing
   accounts, and a raw GoTrue client can omit the metadata entirely. It must be validated
   server-side or described accurately. Its justification was also circular — the monogram that
   would use it is unbuilt, so it cannot be cited as an existing dependency.
5. **"Every account has a null `full_name`" was not queried.** It is what the code path implies
   (`services.js:329-333` sends no metadata), not a fact about the live table. Query before
   asserting.
6. **The RTL guidance contradicted itself.** §7 says Bootstrap positions `form-floating` logically
   while T6 says `.form-check` is physical; both are true of *different* components, and the text
   must say which. `test_css_contract.py` scans **repository CSS only** — it validates nothing
   about the CDN Bootstrap stylesheet or the rendered layout. Use a bespoke logical `.consent-row`
   and test Arabic at mobile widths.

### [HISTORICAL] 14·B — Corrections from the upstream documentation (`ctx7`)

7. **Password change uses `reauthenticate()`, not a current-password check.** Recorded in §9, P1.
   The plan previously carried the security audit's "verify via `signInWithPassword`" design, which
   is not how GoTrue does it.
8. **Secure email change is a project setting defaulting to `true`.** Verify, do not build.
9. **There is no session-listing endpoint, and there cannot be a session list.** The GoTrue admin
   API exposes only `/admin/generate_link`, `/admin/user/{user_id}`, `/admin/users`. Ship
   `signOut({ scope: 'others' })` — "Sign out everywhere else" — instead of a list.
10. **Revocation is not immediate.** Access tokens of revoked sessions stay valid until their `exp`.
    The copy must say so, and it is the second argument for `is_active_account()` in RLS.

### [HISTORICAL] 14·C — Design defects found in this plan

11. **The two length constraints contradicted each other.** Fixed in §6·1 — drop
    `profiles_full_name_len_chk` when `full_name` becomes generated.
12. **`handle_new_user` reading client metadata can abort signup.** The migration's own comment
    (`20260814005509…sql:48-50`) warns that *"a raise in an AFTER INSERT trigger on `auth.users`
    rolls back the account creation itself"* — it defended one case, duplicates, with `on conflict
    do nothing`. Feeding CHECK-constrained columns from unvalidated `raw_user_meta_data` reopens the
    same door: anyone can POST GoTrue directly with `age: "abc"` and take down account creation with
    a constraint we added. **The trigger must coerce toward NULL and never raise** — truncate names,
    accept `age` only as an in-range integer, `marketing_consent` only as a real boolean. A null
    name is recoverable on the account page; a failed signup is not. **P0 blocker.**
13. **The identity cutover as sequenced creates an outage.** Making `full_name` generated *before*
    `handle_new_user` and `admin_update_profile` stop writing it breaks both — plus every
    already-open browser tab, which still sends `full_name` (`handlers.js:1514-1521`). The
    displayed generated-column definition also omits its `text` type. Make the destructive migration
    an **atomic cutover** of trigger, grants, admin RPC and deployed client, with a bounded
    old-client window, and test signup and both write paths against the live migration before
    converting. **Critical.**
14. **`/api/account/*` needs a pinned auth posture.** Fixed in Decision 8 — bearer-header-only via a
    blueprint `before_request` gate, limits keyed on user id.
15. **Account deletion cannot be transactional.** A Postgres purge and a GoTrue delete cannot share
    a transaction, and `web/api/admin.py:329-339` already recognises that outbound provider calls
    cannot. Design an idempotent deletion saga with durable pending/deleted states, retry and
    reconciliation, sign-out sequencing, and a truthful retention statement.
16. **`static/js/account/` cannot just join the existing modules tuple.** It needs its own filename
    map merged with the shared one, exactly as `admin.console` does (`web/api/admin.py:101-121`).
17. **Marketing data would be collected before identity verification, with no way to control it.**
    `handle_new_user` fires when `auth.users` is created — before confirmation — so a typo'd or
    abandoned account retains age and consent indefinitely, and the person cannot sign in to view,
    withdraw, or delete it. Collect only account-creation necessities pre-confirmation, define a
    purge for unconfirmed accounts, and document the recovery path.
18. **Language preference had no mechanism.** Language works by cookie plus navigation
    (`i18n.js:45-67`) and `/account` is Flask-rendered, so Jinja cannot read a Supabase preference
    at render time. Apply Decision 3's own resolution: `preferences.language` is the truth, the
    cookie its mirror, reconciled once at sign-in by the existing `__langfix` one-shot guard
    (`admin.html:47-60`).
19. **The standing line's sources were unnamed.** ROLE and TIER come from `/api/identity`
    (`app.py:1912-1934`); SINCE needs `created_at`, which `getProfile` does not select
    (`services.js:669`) — cheapest home is the identity response; N CONVERSATIONS needs a real
    count, reusing the `total` pattern the pager RPCs already use, not a per-view count; STANDING is
    `is_disabled`, already reaching the client (`app.js:458`).
20. **Consent has unaddressed data-rights consequences.** The admin surface neither returns nor
    displays consent, and append-only audit rows (`20260814032447_audit_log.sql:20-73`) could make
    age survive account deletion. Decide whether consent events are retained on deletion, keep
    marketing demographics out of general admin profile audit diffs, expose a read-only consent
    record to the subject, and include it in export.

### [HISTORICAL] 14·D — Smaller, all verified

21. Write `(select public.is_active_account())` in every policy, so Postgres evaluates it once per
    statement — the initplan idiom the repo already applies to `(select auth.uid())`.
22. `is_active_account()` returns false for an account with **no** `profiles` row, denying that
    reader their own data — while `admin_list_users` deliberately paints *healthy* defaults over a
    missing profile (`coalesce(p.is_disabled,false)`). The console would call such an account
    working while RLS calls it disabled. Make the two agree. (`TODO.md:558-571` records that the
    known instance was backfilled.)
23. Disabled accounts keep their **profile** write path; the standing check lands only on the chat
    tables. Probably intended — say so rather than implying a lockout.
24. `loadProfileWithTimeout` (`app.js:34-54`) is missing from §5's change list. Enumerate every
    reader of `AppState.userProfile` before deleting the slot.
25. **`app.js:407` writes the profile with no identity guard**, unlike `hydrateTranscript`
    (`app.js:248`). A slow read for one reader can land on the next. Live bug — owed its own
    `TODO.md` entry.
26. **Bilingual security emails.** Email change, revocation and deletion all send mail through
    GoTrue templates. A bilingual UI with English-only security email is not bilingual account
    management. Note that dual confirmation sends two different token pairs (§14·B·8).
27. **Arabic plurals.** `I18n.plural` knows two forms; Arabic has six. "43 CONVERSATIONS" and any
    session count both introduce counts.
28. **Signed-out `/account`** has no specified behaviour. Mirror `_handle_unauthorized`
    (`app.py:276-281`).
29. **When consent columns land they must join the privilege-guard deny list** — the grants
    allow-list will not protect them from a future bundle-grant, which is the scenario that guard
    exists for.
30. **`?testing=true` cannot exercise any of this.** Testing mode bypasses auth-state registration
    and returns before profile loading (`app.js:267-279`, `:338-351`), and the mock `signUp`
    ignores metadata (`conftest.py:96-100`). Add an explicit demo profile fixture, or accept that
    the shipping demo covers none of it.
31. **There is no way to know whether any of this worked.** No baseline, no event definition for
    signup abandonment, confirmation completion, consent rate, or scope override. "The majority
    never open `/account`" is an assumption, and `PRODUCT.md:158-160` forbids inventing user
    numbers. Define privacy-safe aggregate metrics **before** adding funnel friction, plus rollback
    criteria for any destructive migration and a support runbook for unconfirmed accounts.

### [HISTORICAL] 14·E — What the reviews did not shake

The modal retirement and its reasoning; `/account` as a server-rendered page following
`admin.console`'s shell pattern; the generated-column strategy for the name split (its *sequencing*
was wrong, not the strategy); the deletion taxonomy; the RTL treatment; and the decision to decline
avatar upload. All re-checked against source and standing.

---

## [HISTORICAL] 15. Verified against the live database — 2026-08-23

Everything in §0–§14 was read from migration *files*. This section is what the **applied database
actually contains**, queried through the Supabase MCP on 2026-08-23. It closes the last blocker
before implementation, and it changed three decisions.

Project `yjjuudnsnjzhyqllsqrd`, **Postgres 17.6**, `ACTIVE_HEALTHY`.

### [HISTORICAL] 15.1 The population is four rows, and that changes the migration strategy

```
public.profiles          4 rows
auth.users               4 rows
users without a profile  0
unconfirmed accounts     0
full_name is null        1
organization set         3
specialization set       3
longest full_name        22 characters
```

**The `TODO.md:558-571` backfill held** — every account has a profile, so
`is_active_account()` (§0.3-C) denies nobody today. §14·D·22's inconsistency is a class of bug to
prevent, not a live one.

### [HISTORICAL] 15.2 The actual rows — and why the automated name backfill is now cancelled

| `full_name` | `organization` | `specialization` |
|---|---|---|
| `Dr. Fouda` | `AI -Team` | `ML and Vibe` |
| `Mohammed Exam Tomorrow` | `SFDA` | `AI, ML. Super, fantastics` |
| *null* | `''` | `''` |
| `Dr. Fouda` | `PSAU` | `Student` |

Two findings, both of which overturn something written above.

**The `split_part` backfill in §6·5 must not run.** Two of the three real names begin with `Dr.` —
a **title**, not a given name — and one has three tokens. The proposed
`split_part(trim(full_name), ' ', 1)` would file "Dr." as two readers' given name.

**And hand-mapping the three rows is also wrong**, which was this document's first correction and
is now itself corrected (§16·1). Hand-mapping still requires someone to decide whether "Dr." is
part of the given name — and **nobody actually knows.** Deciding on a reader's behalf is the same
error as the regex, performed more slowly.

**The right migration invents nothing:** copy each legacy display name **verbatim** into
`first_name`, leave `family_name` explicitly `null` (unknown, not empty), and assert that the
generated `full_name` is byte-for-byte identical for every row before dropping the source column.
No existing reader sees their name change. The three subjects correct it themselves on the account
page, where the person who knows the answer is the one answering.

**§12.5's reversal is now empirically confirmed, not merely argued.** The three real
`specialization` values are `ML and Vibe`, `AI, ML. Super, fantastics`, and `Student`. **None
resembles a corpus category.** The normalisation this plan originally proposed — fold matching
values, blank the rest — would have **erased 100% of the real data in that column**. Terra's
objection (Appendix D, finding 6) is correct on the facts, not just in principle.

### [HISTORICAL] 15.3 Schema facts that correct the text above

- **`profiles` has no `created_at` column at all.** §14·C·19 said `getProfile` does not *select*
  it; the truth is stronger — it does not exist. The standing line's "SINCE" can only come from
  `auth.users.created_at`, so it must travel via `/api/identity` or a `security definer` RPC. It
  cannot come from the browser's PostgREST read of `profiles` under any change to that query.
- **Confirmed: the only constraint besides PK/FK is `profiles_role_chk`.** No length bounds
  anywhere. §0.3-B stands exactly as written.
- **Confirmed: both triggers are `BEFORE UPDATE` only** — `on_profile_update` and
  `profiles_guard_privilege_columns`. §0.3-D stands, and so does §14·C·12's warning about extending
  the guard to INSERT.
- **The FK picture for deletion (§14·C·15):**
  - `profiles.id` → `auth.users(id)` **ON DELETE CASCADE** — so deleting the auth user does remove
    the profile.
  - `profiles.disabled_by` → `auth.users(id)`, **no on-delete action**.
  - `app_settings.updated_by` → `auth.users(id)`, **no on-delete action**.
  - **No `chat_*` table has any FK to `auth.users`.** Confirmed by querying every FK in `public`
    that references it — the three above are the complete set. So transcripts do **not** cascade
    and would be orphaned by an auth-user delete. The deletion saga must purge them by `owner_id`
    explicitly.

### [HISTORICAL] 15.4 Advisors are clean

`get_advisors security` returns four `rls_enabled_no_policy` INFO notices — `app_settings`,
`audit_log`, `chat_archive`, `chatbot_settings` — and one `auth_leaked_password_protection` WARN.
**All five are already on `supabase/README.md`'s standing-findings table** (the WARN is
`TODO.md:481`). No regressions, so any new finding after a migration in this plan is caused by that
migration.

### [HISTORICAL] 15.5 Six migration filenames drift from what was applied

`supabase/README.md` states the rule: *"A migration's filename is exactly `<version>_<name>.sql`,
where both halves are what `list_migrations` reports."* Six do not:

| Repo filename | Actually applied as |
|---|---|
| `20260814032447_audit_log.sql` | `20260814032139` |
| `20260814100500_user_management.sql` | `20260814101408` |
| `20260814110200_app_settings_updated_at_trigger.sql` | `20260814105317` |
| `20260814113000_serialize_admin_membership_changes.sql` | `20260814110722` |
| `20260822090000_chat_session_exists.sql` | `20260822143317` |
| `20260822090100_chat_append_turn_allow_create.sql` | `20260822143411` |

The **relative order is unaffected** — the drifted timestamps preserve the same sequence — so
nothing is broken today. But it is exactly the drift that rule exists to prevent, and it means
`ls migrations/` and `list_migrations` can no longer be read side by side, which is the one
guarantee the directory was created to provide.

Fix it as its own commit, before this plan adds migrations of its own: rename the six files to the
applied versions. And when this plan's migrations are applied, **name the file after applying**,
from what `list_migrations` reports.

*(The 7 pre-directory migrations recorded in `0000_baseline.md` account exactly for the difference
between the 27 applied versions and the 20 files.)*

### [HISTORICAL] 15.6 What this section changes

1. **§6·5's backfill SQL is withdrawn.** Preserve names verbatim; see §15.2 and §16·1.
2. **§12.5 is confirmed** — `specialization` keeps its free text and is not normalised.
3. **The standing line's "SINCE" needs an RPC or the identity endpoint**, not a profile column.
4. **Rename six migration files** before adding any.
5. **§14·D·22 is downgraded** from a live inconsistency to a class of bug worth preventing.

### [HISTORICAL] 15.7 One unknown, resolved

`handle_profile_update()` predates this directory, so its body is not in the repository and §16·1
flagged it as must-inspect-before-migrating. Queried:

```sql
CREATE OR REPLACE FUNCTION public.handle_profile_update() RETURNS trigger
 LANGUAGE plpgsql SET search_path TO ''
AS $function$ BEGIN NEW.updated_at = now(); RETURN NEW; END; $function$
```

It sets `updated_at` and nothing else, and already pins `search_path`. It touches none of the
columns this plan adds and poses no hazard to the cutover.

---

## [HISTORICAL] 16. The four migration specs

Written against §15's verified live state. Full SQL in **Appendix E**; this section is the
decisions and the reasoning, which is what survives if the SQL is rewritten.

Each is authored in the house style of
`20260814005509_lock_profile_privileges_and_repair_signup.sql`: numbered sections, comment-before-
statement explaining *why*, a destructive-check record per the repo's rule 7, and **no explicit
`begin;`/`commit;`** — the runner owns the transaction, exactly as that file's lines 35-43 warn.

### [HISTORICAL] 16·1 — The atomic identity cutover (one migration, not three)

**It cannot be split.** Three writers send `full_name` today: `handle_new_user`
(`…5509.sql:58-67`), `admin_update_profile` (`20260814200342…sql:76-80`), and **the shipped
browser** (`handlers.js:1514-1521`, an upsert). A generated column rejects all three. Converting
the column before the writers are updated breaks signup and both save paths for the length of the
deployment. So the column conversion, both database writers, the function ACLs and the column
grants land as **one indivisible migration**.

**The backfill preserves rather than parses** — see §15.2. `first_name := full_name`,
`family_name := null`, then assert the generated value is unchanged for every row before dropping
the source.

**`profiles_full_name_len_chk` should not exist at all.** Two independently valid 100-character
names produce a 201-character generated value: a 200-char check rejects valid base data, and a
201-char check merely repeats what the base-column checks already prove. This supersedes §6·1's
note, which only said to drop it.

**The deployed-client window is real and must be stated.** An already-open tab still sends
`full_name` in its upsert after this runs, and will get a write error until it reloads. With four
accounts that is a non-event; the migration should say so rather than leave it discovered.

**Before approving, run and record:** `pg_get_functiondef` for the trigger functions, any index
mentioning `full_name`, and the row/length counts. §15.7 already did the first.

### [HISTORICAL] 16·2 — `handle_new_user` hardening (P0 blocker)

The trigger is `AFTER INSERT` on `auth.users` and its own comment warns that **a raise inside it
rolls back account creation** (`…5509.sql:48-50`). It is about to read `first_name`, `family_name`,
`age` and `marketing_consent` out of `raw_user_meta_data` — **client-supplied and unvalidated**.
Anyone can POST GoTrue directly with `age: "abc"`; under the new CHECKs that raises, and signup
fails. A denial-of-service on account creation, caused by our own constraints.

**The rule: coerce, never raise.** Truncate names to their bound. Accept `age` only when it cleanly
casts to an integer in range, else null. Accept `marketing_consent` only as a real boolean, else
false. A null name is recoverable on the account page; a failed signup is not.

### [HISTORICAL] 16·3 — The consent record: columns on `profiles`, not an event table

**Argued against this codebase's actual `audit_log`, not in the abstract.** That table records
*administrative actions*, is service-role-only, and **deliberately survives account deletion**
(`20260814032447…sql:20-73`). A subject cannot read it. Putting consent there would mingle a
subject's own choice with operator audit evidence and keep it after the subject left.

Consent is subject-owned profile data. It belongs on `profiles`, where the subject can read it and
where `profiles.id → auth.users ON DELETE CASCADE` (§15.3) removes it when they go.

Columns: state, `granted_at`, `withdrawn_at`, plus the **policy version, language and surface** the
consent was given on — because "a valid JWT sent a boolean" is not evidence of what was agreed to.
Plus `granted_while_unconfirmed`, which records terra's finding (§14·C·17) as data instead of
leaving it as a risk.

**Every constraint is conditional on the granted state**, so malformed legacy context can never
block a withdrawal. **No CHECK couples `age` to consent** — withdrawal offers to clear age and the
reader may decline.

**The honest limit, stated in the migration:** this records the *current* consent and its latest
transitions. It is **not immutable history.** If the legal requirement ever becomes "retain every
grant/withdrawal cycle," these columns are insufficient and an event table replaces them. Do not
describe the current design as an audit trail.

### [HISTORICAL] 16·4 — Account deletion: two migrations and a saga, never one RPC

`web/api/admin.py:329-339` already records the governing fact: a database transaction cannot
contain an outbound provider call. So deletion is a **durable, idempotent saga**, not an RPC.

**Migration A — the FK prerequisites**, destructive DDL in its own migration per rule 2.
`profiles.disabled_by` and `app_settings.updated_by` reference `auth.users(id)` with **no on-delete
action** (§15.3), so deleting an administrator raises `23503` and aborts. Both become
`ON DELETE SET NULL` — the row survives and honestly records that its auth principal is gone. The
FK indexes already exist and are unaffected.

**Migration B — the saga table**, which deliberately carries **no FK to `auth.users`**: it must
survive the provider deleting that user, or a crashed worker cannot tell *pending* from *done*.

**Transcripts must be purged explicitly by `owner_id`.** §15.3 confirmed no `chat_*` table has any
FK to `auth.users`, so nothing cascades — the deliberate choice at
`20260820131914…sql:38-42`. And `chat_archive` is **never** touched by a reader's deletion.

**The retention statement must be truthful:** deletion removes the account, the profile, and every
transcript; it does not remove dormant archive rows or provider backups.

---

## [HISTORICAL] 17. Build order — the authoritative sequence

**This supersedes §9's phases.** §9 was written before the reviews; where the two disagree, this
section wins. Each step names what it depends on, so nothing is started that a later correction
would force to be rewritten.

### [HISTORICAL] Step 0 — Housekeeping, no product change

- [x] **Rename six migration files** to their applied versions (§15.5). Its own commit. Nothing
      else in this plan may add a migration until `ls migrations/` and `list_migrations` agree
      again.
- [x] Open a `TODO.md` entry for **`app.js:407`'s missing identity guard** (§14·D·25) — a live bug,
      unrelated to this work, found while planning it.

### [HISTORICAL] Step 1 — The signup funnel fix *(no schema, no dependencies, ship it first)*

- [x] Persistent `#signup-sent` panel replacing the toast at `handlers.js:173`, modelled on
      `#reset-sent` (`index.html:215-218`). Names the address back to the reader.
- [x] `handlers.js:158` and `:173` onto `runtime.auth.*` keys, both catalogues.
- [x] **Delete** the `handlers.js:168` toast rather than translate it — `#user-status` already
      states the same fact from a frozen key (§12.7).
- [x] `test_auth_flow_uses_the_i18n_catalogue_not_literals`, mirroring
      `test_frontend_architecture.py:50-72` — asserts keys present **and** literals absent.
- [x] Extend the catalogue-parity test to cover `page.*`, not only `runtime.*` (§14·A·1 — note the
      real behaviour is a silent English fallback, not a raw key).
- [x] Bump `ASSET_VERSION`.

**This is the whole of what is safe to build today.** Everything below depends on a schema change.

### [HISTORICAL] Step 2 — Schema, in this order and no other

- [x] **2a. Column bounds** on `organization`, `specialization`, `preferences` (§6·1) — but **not**
      `full_name`, which never gets a length check (§16·1). Applied `20260822224844`.
- [x] **2b. Privilege-guard trigger** extended to `BEFORE INSERT OR UPDATE`, with the INSERT branch
      **asserting literals, not diffing against `old`** (§14·C·12 / T1). Getting this wrong rejects
      every new profile. Applied `20260822224942`; also widened to all 7 administered columns.
- [x] **2c. `is_active_account()`** in the chat-table RLS policies, written
      `(select public.is_active_account())` for the initplan (§14·D·21). Applied `20260822225054`.
      New `authenticated_security_definer_function_executable` advisor finding is expected and
      recorded in `supabase/README.md` — the RLS policies themselves must call it as `authenticated`.
- [x] **2d. `preferences` merge RPC** — with its `auth.uid()` binding, allowed patch keys,
      `authenticated` grant and revoked `PUBLIC` specified (§14·A·3). Note it is **not** a
      prerequisite for the top-level consent columns; that claim was wrong. Applied `20260822225239`
      as `public.update_own_preferences(jsonb)`, allow-listing `theme`/`language`/`search_scope`.
      No caller wired yet — lands with Step 3/4's first new preference key.
- [x] **2e. The atomic identity cutover** (§16·1, Appendix E Spec 1) — one migration, verbatim name
      preservation, generated `full_name`, both DB writers and all grants moved together. **The
      only irreversible step in this plan.** Take a backup first; run the pre-flight checks it
      names; verify signup and both save paths against the applied migration before moving on.
      Applied `20260822225415`. All 4 rows verified byte-for-byte preserved after the cutover (§15.2
      values reproduced exactly). `admin_get_user` extended separately (`20260822225623`) to expose
      `first_name`/`family_name`/`age` to the console's edit form. Application layer updated in the
      same pass: `web/api/admin.py` (`_PROFILE_STRING_FIELDS`, age validation),
      `web/services/admin_store.py` (Protocol + both backends), `static/js/admin/ui.js` (edit form),
      the reader-facing `#profileModal` (`index.html`, `ui.js`, `handlers.js`, `services.js`), and
      the affected tests (`test_admin_users.py`, `test_admin_browser.py`,
      `test_profile_theme_integration.py`, `conftest.py`'s `SUPABASE_BROWSER_MOCK`).
- [x] **2f. `handle_new_user` hardening** (§16·2, Spec 2) — coerce, never raise. Ships with 2e or
      immediately after, never before. Shipped inside `20260822225415` (identity-only version —
      does not read consent fields, since those columns do not exist until Step 6). Step 6 replaces
      this function again per Spec 3 once the consent columns land.

Verify after **each**: `list_tables`, `list_migrations`, `get_advisors security`,
`get_advisors performance`. §15.4 is the clean baseline — any new finding is caused by the
migration just applied. **Name each file after applying**, from what `list_migrations` reports.

### [HISTORICAL] Step 3 — `/account` exists and tells the truth

**Shipped 2026-08-23.** Identity and Preferences only — Security, Your data and Delete account are
Steps 5-7 and were deliberately not stubbed as placeholders (a section that cannot yet do anything
is worse than a section that does not exist yet).

- [x] `GET /account` + template + `static/js/account/` + `account.css`, following
      `admin.console`'s shell pattern — and note it needs **its own filename map merged with the
      shared one** (§14·C·16), not an addition to the existing tuple. `web/api/account.py`
      (new blueprint), `web/templates/account.html`, `static/js/account/{app,ui,handlers}.js`,
      `static/css/account.css`. `ACCOUNT_MODULE_FILENAMES` added beside `ADMIN_MODULE_FILENAMES`.
- [x] Bearer-header-only `before_request` gate on the blueprint; limits keyed on user id
      (Decision 8, as amended). No `/api/account/*` mutation exists yet to key a limit on — the gate
      itself is built and covers the page route by explicit exemption, ready for Step 5/7's routes.
- [x] Signed-out behaviour mirroring `_handle_unauthorized` (§14·D·28). Client-side: `#account-signed-out`
      state with a link back, since the page itself is ungated (a document navigation carries no
      bearer token — same reasoning as the console).
- [x] Identity section; monogram by grapheme (`Intl.Segmenter`, with a code-point fallback); the
      standing line — with **SINCE from `auth.users.created_at`** via a new
      `public.get_identity_flags(uuid)` RPC and a wider `/api/identity` response (also carries
      `is_disabled` and a `conversation_count`), because `profiles` has no such column (§15.3).
      Deliberately NOT folded into the cached, hot-path `IdentityFlags`/`identity_cache.py` — see
      that RPC's own migration header for why a conversation-count subquery does not belong there.
- [x] Theme Light/Dark/System, one source of truth (Decision 3). Language follows the same pattern
      (§14·C·18) — both instant-apply via `update_own_preferences`, "System" resolving to the OS
      preference once at selection time (the same resolution every page's own FOUC script already
      does on first visit, not a new, weaker mechanism).
- [x] Dirty tracking, guarded dismissal (`beforeunload` when the identity form is dirty — preferences
      carries no such guard; it never has unsaved state), wired spinner, and saved/error states.
      No skeleton/empty state built yet — the record loads fast enough in practice that a loading
      state beyond the existing gate text was not worth the added surface; revisit if that stops
      being true.
- [x] `dir="auto"`, `maxlength`, `autocomplete`, `inputmode`, `fieldset`/`legend`, 24px targets,
      and a bespoke logical `.consent-row`-equivalent (`.account-choice`) for the theme/language
      radios — **never bare `.form-check`**, which does not mirror under the LTR Bootstrap build
      (§14·A·6). The actual `.consent-row` ships with Step 6, once there is a consent checkbox to
      style.
- [x] Fresh read on open (no cache — the page has no `AppState` to be stale against in the first
      place). Sidebar footer: the profile button is now a plain link to `/account`, not yet
      collapsed into a full account-menu dropdown — deferred, see below. Log-out scope stated
      (`page.account.logoutScope`).
- [~] Transitions per §13: plain `<a href="/account">` — done. `@view-transition { navigation: auto }`
      and the reduced-motion `::view-transition-*` rule — done, in `account.html`. The
      identity-cluster shared element and its media-query-scoped `view-transition-name` — **not
      shipped**: `_sidebar.html`'s macro renders twice (desktop aside + mobile offcanvas) and a
      name must be unique among rendered elements; assigning it safely needs a media query scoping
      it to whichever copy is actually displayed, which this pass did not build. See the comment
      left in `_sidebar.html` at the profile-button link.

### [HISTORICAL] Step 4 — Signup capture and first-run

**Shipped 2026-08-23.**

- [x] `first_name` / `family_name` on the signup form, passed as `options.data`; described as
      required **by this form**, validated server-side (§14·A·4). `handle_new_user`'s server-side
      coercion already existed from Step 2 (2f) — this step only started the client actually
      sending the fields. Fixed alongside it: `app.js:407`'s profile-load `.then` gained the same
      identity guard `app.js:433-444` already had (TODO.md's "A late profile read has no identity
      guard" entry), because both the strip below and this signup work hang off that callback.
- [x] The completion strip, **queued through a notice coordinator** — not suppressed by inspecting
      `#history-notice`'s DOM, which hides it from the readers it targets (§12.6). `NoticeCoordinator`
      (`ui.js`) claims one slot per identity; the history notice's own dismiss handler releases it.
      `isTranscriptTurn` generalised from a hardcoded second id to a `data-non-turn` attribute, per
      T9's own prediction, rather than growing a third literal.
- [x] Search scope as a reversible preference defaulting to `all`, with last-used-per-device winning
      (`dropdown.js`, `localStorage` key `sfda-search-scope`) (§12.5). **Narrower than the plan
      allows, deliberately:** the optional account-level preferred-category default (§12.5's last
      bullet, "applied only before the first query interaction of that identity") was **not**
      built — the per-device memory alone answers the actual complaint (the composer opening on the
      wrong scope) without the late-arrival hazard an account-tied default would reintroduce.
      `CustomDropdown.setValue()`/`.reset()` exist as the T7-safe hook for that default if it is
      ever added, but nothing calls them yet.

### [HISTORICAL] Step 5 — Security, per what the API actually supports

**Shipped 2026-08-23, in `/account`'s new Security section — Step 3 deliberately did not build one,
since nothing in it existed yet.**

- [x] Password change via `reauthenticate()` + `updateUser({ nonce, password })` (§14·B·7).
      **Load-bearing verification made in this pass:** the pinned `@supabase/supabase-js@2.39.7`'s
      own `+esm` bundle does not contain `reauthenticate` at all — it re-exports from
      `@supabase/gotrue-js@2.62.2`, which *does* carry it (confirmed by reading that bundle
      directly; `supabase-js`'s own `+esm` shim is a 5KB re-export wrapper, not the implementation).
      Also confirmed by reading `gotrue-js@2.62.2`'s error class: `AuthApiError` at this version
      carries only `{message, status}` — **no `.code`.** The server's `error_code` field
      (`{code, error_code, msg, error_id}` per current GoTrue's own docs) is read into nothing by
      this client version. `classifyPasswordError` (`account/handlers.js`) therefore matches on
      `.message` text, the same defensive convention `ErrorHandler.formatAuthError` already uses —
      not a `.code` switch, which would silently never match on this SDK version.
      After a successful change, every *other* session is ended (`signOutOtherSessions()`, OWASP's
      own Change-Password guidance) — this device stays signed in, since the reader is using it to
      make the change.
- [x] **Verify** `mailer_secure_email_change_enabled` rather than build it — default is `true`
      (§14·B·8). **Not independently confirmed by this session's tooling** — the public
      `GET /auth/v1/settings` endpoint (checked with the project's own anon key) does not expose
      this flag, and no MCP tool here reads GoTrue's mailer configuration. Confirm in the Supabase
      dashboard (Authentication → Settings → Email) before relying on it.
- [x] **No session list** — it does not exist in the API. Ship "Sign out everywhere else"
      (`scope: 'others'`), with copy saying revocation takes effect when the token expires
      (§14·B·9, ·10). `page.account.signOutOthersHint` states this plainly rather than implying the
      other devices are gone the moment the button is clicked.
- [ ] **Bilingual GoTrue email templates (§14·D·26) — blocked, not attempted.** These are Supabase
      Auth's own transactional email templates (password recovery, email change, etc.), configured
      through the Supabase Dashboard or its Management API — not application code, and no MCP tool
      available in this session reads or writes them. Needs either dashboard access or a Management
      API credential this session does not have.

### [HISTORICAL] Step 6 — Consent

**Shipped 2026-08-23, by explicit direction from the product owner: write a generic bilingual
policy now, to unblock the engineering, and review/polish its actual content later.** §12.4's own
sequencing rule — "no marketing data is collected until the policy is approved and published" —
is therefore knowingly not fully honoured by this pass: the policy exists and is published, but is
a DRAFT, not yet approved as binding legal text. `/privacy`, the signup consent checkbox, and the
`/account` withdrawal toggle all say so explicitly (`page.policy.draftNotice`), and
`PRIVACY_POLICY_VERSION` (`web/api/app.py`) is a versioned string specifically so a real, reviewed
policy can replace the draft later without orphaning consent records already granted under it —
each grant records the exact version it was made under.

- [x] **The bilingual سياسة الاستخدام والخصوصية**, at `GET /privacy` — public, ungated, same
      "safe to open blind" reasoning `deep_link` already gives. Content: scope, what is collected,
      how it is used (with marketing singled out as consent-gated), sharing, retention, rights
      (access/export/delete/withdraw — linking to the already-shipped `/account` features),
      security, contact. Both languages, key-parity verified by hand (no `page.*` catalogue-parity
      test exists yet — T3's own gap, still open).
- [x] Consent columns + trigger (§16·3, Spec 3 — applied close to verbatim, with one adaptation:
      Spec 3's guard-trigger text predates this project's live INSERT-branch fix
      (`20260822224942_profile_privilege_guard_covers_insert.sql`), so the consent-column guard was
      merged into that existing INSERT/UPDATE structure rather than replacing it with Spec 3's
      UPDATE-only text). `marketing_consent`, `marketing_consent_granted_at`,
      `marketing_consent_withdrawn_at`, `marketing_consent_policy_version`,
      `marketing_consent_language`, `marketing_consent_surface`,
      `marketing_consent_granted_while_unconfirmed` — current state plus latest grant/withdrawal
      context, not an immutable event log (the migration's own comment says so explicitly).
      Verified live: a grant without policy/language/surface is rejected (`22023`); a client cannot
      write the three server-owned timestamp/flag columns (`42501`, both INSERT and UPDATE); a
      re-grant preserves the prior withdrawal time; a withdrawal preserves the prior grant context
      without validating it.
- [x] Signup: a separate, unticked marketing-consent checkbox that reveals the age field only when
      ticked (never bundled with the required terms tick, which is its own separate checkbox
      linking to `/privacy`). `handle_new_user` coerces malformed/missing consent metadata to a
      decline rather than raising — never turns arbitrary client metadata into a blocked signup,
      the same rule Step 4's version already established for `first_name`/`family_name`/`age`.
      `.consent-row`/`.consent-reveal` in `components.css`: bespoke, logical properties only, never
      bare `.form-check`, and the age reveal is a `grid-template-rows` height transition rather
      than JS measurement.
- [x] Withdrawal on `/account`, in the existing "Your data" section (Step 7) — the same
      instant-apply, browser→Postgres write the Identity form's own fields already use, so there is
      no Flask route to rate-limit and none was added. Offers to clear `age` on withdrawal without
      requiring it (T9) — declining the offer still lets withdrawal succeed and never touches age.
- [x] Admin visibility of the consent record (§14·C·20 does not resolve to real section content in
      this doc — read as "give an operator the same record the subject has"): `admin_get_user`
      extended with the same seven fields, surfaced read-only in the console's account-detail
      identity facts. **Not extended to Step 7's reader-facing export** — that surface is
      conversations only, matching its own shipped IA line ("export conversations"), and the
      consent record is already visible to the subject directly on `/account`; treating "export of
      the consent record" as "visible to the subject" rather than "bundled into the NDJSON
      download" was a deliberate scope call, not an oversight.

### [HISTORICAL] Step 7 — Data rights

**Export and bulk conversation deletion shipped 2026-08-23.** Account deletion (the saga) is
unbuilt — see below.

- [x] Export: streamed NDJSON (`GET /account/api/export` — see note on the path below),
      `owner_id` scoped from `g.identity`, never from anything the caller supplies. Two lines
      of new persistence-layer surface in `chat_store.py` do the actual work:
      `export_all_sessions`/`_export_session_messages` walk BOTH UI bounds to exhaustion —
      `list_sessions`' `MAX_LIST_LIMIT` (one sidebar page) and `load_session`'s `MAX_LOAD_LIMIT`
      (one hydration window) — rather than silently inheriting either as an export cap. One
      NDJSON line of `{export_version, generated_at, user_id}`, then one line per session with
      its full nested message/source history. A misconfigured deployment (persistence on,
      backend unreachable) is refused with 503 before the stream starts; a backend that fails
      PARTWAY through cannot get a status change any more (the 200 is already on the wire), so
      that failure is reported as a trailing NDJSON error line instead of a silently truncated
      file. Scope is conversations only, matching the shipped Data-section IA line ("what is
      stored and why · export conversations · delete all conversations") and Spec 5's own
      framing — not a full account/profile export, which stays reachable directly on the
      Identity section of `/account` itself. No CSV offered, so the security pass's CSV-formula-
      injection mitigation (§ "if CSV is ever offered") never had to be built.
- [x] Bulk conversation deletion, named distinctly from account deletion
      (`DELETE /account/api/conversations`). A new RPC, `chat_delete_all_sessions(p_owner_id)`
      — one round trip, `delete … returning id`, matching `chat_delete_session`'s grant posture
      exactly (service_role only). Returns the deleted ids, not a count, so Flask can clear its
      own per-conversation `ConversationStore` windows the same way the single-delete route
      already must (`chat_append_turn`'s `on conflict (id) do nothing` would otherwise
      resurrect a row a stray in-flight write lands on). Refused with 409 while ANY of the
      owner's conversations is mid-generation — `is_live_for_owner`, the bulk form of the
      single-delete route's own `is_live` check, added to `_InFlightGenerations` (app.py) for
      the identical reason that route already gives.
- [ ] Account deletion: **Migration A (FK fixes) then Migration B (saga)**, then the flow
      (§16·4, Spec 4). Not started — blocked on §10's open question, still genuinely open:
      whether self-deletion is permitted at all. Unlike export/bulk-delete, this is a large,
      hard-to-reverse piece (a background saga, a GoTrue admin-delete call) resting on an
      explicit product decision the plan itself never closed, and it was not attempted without
      it.

**Path note, not in the original plan text:** the two routes above live at `/account/api/export`
and `/account/api/conversations`, not `/api/account/*` as §4's prose says. `web/api/admin.py`
already established `<blueprint-prefix>/api/<thing>` as this app's actual convention
(`/admin/api/settings`, `/admin/api/users`, …) — `account.py` follows it for consistency with the
console rather than the plan's shorthand, which was never load-bearing on an exact path.

**Rate limits, keyed per reader rather than per IP (R4):** export 2/10min, matching the adopted
security-pass number; bulk delete 10/hour (not itemized in §4's own table, which covers email/
password/export/account-deletion specifically — set here by the same destructive-but-cheap
reasoning). Both use `web/api/app.py`'s `_account_rate_key`: a hash of the bearer token itself,
not the decoded identity — Flask-Limiter's own `before_request` hook runs BEFORE `account_bp`'s
`_gate`, so `g.identity` is not set yet when a rate key is computed, and re-authenticating there
would be a second `supabase.auth.get_user` round trip on top of the one `_gate` already makes.

### [HISTORICAL] Still open

Steps 6 and 7 both shipped without these being formally closed — none turned out to gate what was
actually built, but none should be read as decided either:

1. **Genuinely still blocking** — is reader self-deletion permitted, given the audit log? (§10·6 —
   P2 assumes yes; decide.) This is the one remaining piece of Step 7 (the deletion saga) and it
   has not been started.
2. `age` or `birth_year`? A stored age is wrong within twelve months (§12.2, Decision 5). Shipped
   as `age`, unresolved.
3. Does signup also capture `organization`? Shipped as no (§12.2's own table already said never) —
   this one is effectively answered by what was built, just never crossed off here.
4. Where does the Beehiiv opt-in live, and does its consent copy merge with §12.4's? Not addressed
   by Step 6 — the shipped consent checkbox covers this product's own marketing use only.
5. **How will anyone know whether this worked?** (§14·D·31.) No baseline exists, and
   `PRODUCT.md:158-160` forbids inventing numbers. Define privacy-safe aggregate metrics before
   adding funnel friction — Step 4 is the first step that adds any, and Step 6 added more.

---

## [HISTORICAL] Appendix A — Benchmark & gap analysis

**Implementer:** OpenCode CLI · `openai/gpt-5.6-luna`, reasoning effort **xhigh**, `plan` agent (read-only)
**Dispatched:** 2026-08-22 · **Working tree:** untouched

> Reproduced verbatim. Note §0.4: this report proposed the path `/settings`, which Decision 1 renamed to `/account`. Its reading of `route.js` as *not* a general router is correct and is what the plan adopts.

<!-- BEGIN VERBATIM — Appendix A -->

### [HISTORICAL] SFDA Copilot Account Experience Benchmark

This benchmark focuses on shipped product surfaces, not marketing pages. Exact labels and availability vary by plan, platform, authentication provider, and enterprise policy, especially for export, sessions, and account deletion.

#### [HISTORICAL] 1. The 10 Benchmarks

##### [HISTORICAL] 1. ChatGPT

**Surface:** Settings opened from the account menu, with nested sections for General, Personalization, Notifications, Data Controls, Security, and subscription/account management.

**Information architecture:**

- Identity and account: account email, plan, connected sign-in method.
- Personalization: custom instructions, personality, memory, response preferences.
- Data and privacy: chat history, model-improvement controls, data export.
- Security: password, MFA, active sessions or “log out all devices”.
- Danger zone: account deletion.

**One idea worth stealing:** Separate “how the assistant behaves” from “who I am”. Custom instructions, memory, and personality are not mixed with email, password, or deletion.

**Saving model:** Most preferences are immediate or autosaved. Larger text areas and custom-instruction forms may use explicit save depending on the current UI. Settings generally confirm with a transient success state rather than a persistent save bar.

**Hard parts:**

- Email and password are handled as account-security operations, not personality settings.
- Password reset and provider-based sign-in are distinct flows.
- Session invalidation is treated as a security action.
- Data export is explicit and separated from ordinary chat-history controls.
- Account deletion is isolated and confirmation-heavy.

**Why it works:** The surface models the user’s mental categories. “Make ChatGPT answer differently” is different from “secure or destroy my account”.

---

##### [HISTORICAL] 2. Claude.ai

**Surface:** Account/settings panel with profile, appearance, general preferences, privacy controls, and Styles or response-customization features.

**Information architecture:**

- Profile: name and account identity.
- Appearance: theme and visual preferences.
- Styles: reusable response style definitions and custom instructions.
- Privacy/data: conversation and model-training controls where available.
- Account security: login method, password or provider account.
- Danger zone: account deletion, usually under account management.

**One idea worth stealing:** Treat response styles as named reusable objects rather than one undifferentiated “custom instructions” text box.

**Saving model:** Simple preferences are generally immediate. Style creation and editing use an explicit save/create action because the user is editing a durable object.

**Hard parts:**

- Email and password depend partly on whether the account uses email/password or a federated provider.
- Session management is not always as rich as a dedicated security product; availability should not be assumed.
- Data controls are presented separately from style and appearance.
- Export and deletion are account-level operations rather than profile fields.

**Why it works:** It distinguishes durable assistant configuration from temporary conversation context. A professional can create a repeatable “regulatory reviewer” style without confusing it with personal identity.

---

##### [HISTORICAL] 3. Google Gemini

**Surface:** Gemini settings inside the product, combined with the broader Google Account and Google activity/privacy surfaces.

**Information architecture:**

- Gemini preferences: personalization, connected apps, response behavior.
- Google Account identity: name, email, profile image, sign-in methods.
- Activity and privacy: Gemini Apps Activity, retention, auto-delete, human review controls.
- Security: password, passkeys, MFA, devices, sessions.
- Danger zone: Google Account deletion.

**One idea worth stealing:** Make the boundary between product preferences and provider-level identity explicit.

**Saving model:** Most settings are immediate. Activity-retention and privacy controls confirm their new state visibly. Security changes use dedicated Google Account flows.

**Hard parts:**

- Email and password belong to Google Account, not the Gemini settings panel.
- Devices, sessions, passkeys, MFA, and recovery methods are handled centrally.
- Export is available through Google data export/privacy tooling rather than a Gemini-only form.
- Deleting Gemini activity is distinct from deleting the whole Google Account.
- Account deletion is therefore a much more consequential operation than deleting assistant history.

**Why it works:** It avoids pretending that one product owns all account identity. Gemini is a product inside a larger identity system, and the IA tells the truth about that.

---

##### [HISTORICAL] 4. Perplexity

**Surface:** Account/settings page or panel containing profile, subscription, appearance, language, search/answer preferences, and data controls.

**Information architecture:**

- Profile and identity.
- Appearance and language.
- Search and answer preferences.
- Subscription and billing.
- Privacy/data controls.
- Account deletion.

**One idea worth stealing:** Put language, appearance, and answer behavior near each other because they jointly affect the reading experience, while keeping billing and security separate.

**Saving model:** Most toggles and dropdowns are immediate. Profile edits and some account changes use an explicit save or submit action. Confirmation is usually a toast or inline state.

**Hard parts:**

- Email/password behavior depends on whether the user signed in with email, Google, Apple, or another provider.
- Session controls are less central and less consistently exposed than in GitHub or Google.
- Conversation deletion is usually easier to find than full-account deletion.
- Export and privacy controls may be plan- or product-version-dependent and should not be assumed to equal a complete account export.

**Why it works:** It is optimized for a research tool: language and answer behavior are first-class preferences, not buried behind generic profile fields.

---

##### [HISTORICAL] 5. Microsoft Copilot

**Surface:** Copilot settings and personalization controls, backed by Microsoft Account and Microsoft privacy/security surfaces.

**Information architecture:**

- Copilot behavior: personalization, memory, conversation history.
- Microsoft account identity: email, profile, family/work identity.
- Privacy: activity history and personalization controls.
- Security: password, MFA, devices, sessions, recovery methods.
- Danger zone: Microsoft Account deletion.

**One idea worth stealing:** Use plain-language scope labels for data controls: delete this conversation, clear Copilot history, stop personalization, or delete the Microsoft Account.

**Saving model:** Toggles are immediate and usually visibly reflected. Account security changes use explicit confirmation and often require reauthentication.

**Hard parts:**

- Email, password, sessions, devices, and MFA live in Microsoft Account.
- Copilot history and broader Microsoft account data are separate data sets.
- Export is handled through Microsoft privacy/data tooling rather than necessarily inside the Copilot panel.
- Deleting a Microsoft Account is intentionally separated from deleting Copilot history.

**Why it works:** It prevents destructive actions from being ambiguous. “Delete my Copilot data” must not silently mean “delete my Microsoft identity”.

---

##### [HISTORICAL] 6. Notion

**Surface:** Full settings area with a left navigation, personal settings, workspace settings, members, security, connections, notifications, billing, and imports/exports.

**Information architecture:**

- My account: name, avatar, email, password, connected accounts.
- Preferences: language, appearance, timezone, start page, notifications.
- Workspace: members, roles, permissions, integrations, billing.
- Data: workspace export, imports, connected services.
- Security: sessions, login methods, access.
- Danger zone: leave workspace, delete workspace, delete account.

**One idea worth stealing:** Separate personal account settings from workspace settings even when they are reached from the same settings entry point.

**Saving model:** Many controls autosave. Structured entities, integrations, and workspace changes use explicit actions. Destructive workspace actions require confirmation and often an additional typed phrase.

**Hard parts:**

- Email and password are personal account operations.
- Workspace membership and role are not identity fields.
- Export can operate at workspace scope, not just individual conversation scope.
- Deleting an account, leaving a workspace, and deleting a workspace are different actions.
- Sessions and connected integrations have their own security meaning.

**Why it works:** Notion is both a personal tool and a collaborative system. The IA makes ownership scope visible before a user changes or deletes something.

---

##### [HISTORICAL] 7. Linear

**Surface:** Full settings route with sections for account/profile, preferences, notifications, security and access, API keys, teams, workspaces, and billing.

**Information architecture:**

- Personal account: profile, email, authentication.
- Preferences: theme, language, timezone, keyboard behavior.
- Notifications: email, desktop, issue/project notifications.
- Security and access: password, MFA, sessions, connected accounts, API keys.
- Workspace/team: membership, roles, integrations, billing.
- Danger zone: leave team, delete workspace, delete account.

**One idea worth stealing:** Make keyboard shortcuts and command-driven navigation an account-level preference for a professional tool.

**Saving model:** Toggles are immediate. Forms and generated credentials use explicit save/create actions. API-key creation is a one-time confirmation flow with a clear “copy now” moment.

**Hard parts:**

- Email/password and MFA are separated from workspace membership.
- Sessions, API keys, and OAuth connections are security assets, not profile data.
- Workspace deletion is distinct from personal account deletion.
- Export is generally workspace/admin-oriented rather than a generic “download everything” button.

**Why it works:** Linear assumes frequent, expert use. It treats settings as operational controls, not decoration, and separates personal, workspace, and developer scopes.

---

##### [HISTORICAL] 8. Slack

**Surface:** Profile menu, profile editor, Preferences dialog, account settings, workspace settings, and session/device management.

**Information architecture:**

- Profile: display name, real name, title, avatar, pronouns, timezone.
- Preferences: language, theme, accessibility, notifications, sidebar behavior.
- Workspace: workspace identity, membership, roles, integrations.
- Security: email, password, MFA, sessions, sign-in logs.
- Data/privacy: exports, retention, workspace policies.
- Danger zone: deactivate account or leave workspace.

**One idea worth stealing:** Make the profile identity card useful in the collaboration context: avatar, display name, title, timezone, and presence are immediately meaningful to other people.

**Saving model:** Most preferences autosave or apply immediately. Profile edits use explicit save/update. Notification settings typically reflect changes instantly.

**Hard parts:**

- Email and password are account settings, not profile-card fields.
- Active sessions and sign-in security are separate from workspace membership.
- Export is usually governed by workspace/admin policy rather than only by the individual.
- Deactivation is often constrained by workspace ownership and admin roles.
- Deleting a personal account is not the same as deleting workspace content.

**Why it works:** Slack knows the account has two audiences: the account owner and the people they work with. Identity is therefore more than a private name field.

---

##### [HISTORICAL] 9. GitHub

**Surface:** Full `/settings` route with a stable left navigation and dedicated pages for Profile, Emails, Password and authentication, Sessions, SSH/GPG keys, Appearance, Accessibility, Notifications, Billing, and account deletion.

**Information architecture:**

- Profile: name, bio, avatar, location, company.
- Account identity: email addresses and primary email.
- Preferences: appearance, accessibility, notifications, language-related behavior.
- Security: password, passkeys, MFA, sessions, SSH/GPG keys, OAuth applications.
- Data: export/account data, repository and organization data.
- Danger zone: repository deletion, organization actions, account deletion.

**One idea worth stealing:** Give security assets their own navigation node. Do not force a user to find password, sessions, MFA, keys, and OAuth applications inside “Profile”.

**Saving model:** Explicit save for profile and many form pages. Toggles and selection controls may apply immediately. Dangerous operations require reauthentication, typed confirmation, or multiple explicit steps.

**Hard parts:**

- Email changes include verification and primary-email selection.
- Password change, passkeys, MFA, recovery codes, and sessions are separate but adjacent.
- Sessions can be inspected and revoked.
- Export and deletion are explicit account/data operations.
- API tokens, deploy keys, SSH keys, and OAuth applications are treated as security-sensitive resources.

**Why it works:** GitHub’s settings reflect the true risk model of a professional account. Identity, collaboration, credentials, and data destruction are not one form.

---

##### [HISTORICAL] 10. Vercel

**Surface:** Dashboard settings with account, team, authentication, tokens, billing, usage, domains, integrations, and project-level settings.

**Information architecture:**

- Personal account: profile, email, avatar.
- Team/workspace: members, roles, access, billing.
- Preferences: appearance and dashboard behavior.
- Security: password, MFA, sessions, personal access tokens, OAuth/integrations.
- Data and operational controls: projects, domains, deployments, logs, usage.
- Danger zone: remove project, leave team, delete team/account.

**One idea worth stealing:** Scope every setting by ownership: personal account, team, project, or deployment.

**Saving model:** Forms use explicit save. Token creation and deletion use explicit actions, show the token once, and require a deliberate confirmation. Small preferences may apply immediately.

**Hard parts:**

- Email/password and authentication are account-level.
- Sessions and tokens are separate security surfaces.
- Team membership and role are not editable from the personal profile form.
- Export and deletion are scoped by project/team/account, with different consequences.
- Billing is isolated from identity and security.

**Why it works:** Vercel makes scope visible. A user can tell whether they are changing themselves, a team, a project, or a production asset.

---

#### [HISTORICAL] 2. Cross-Cutting Patterns

##### [HISTORICAL] 1. Separate account identity from product preferences

This is the most important pattern.

Best-in-class products distinguish:

- Who the person is.
- How the product behaves.
- What data the product retains.
- How the account is secured.
- What belongs to a workspace, team, or organization.

The current SFDA Copilot form combines identity fields and theme preference in one small form. That is acceptable for a prototype, but it will not scale to email, password, sessions, privacy, export, or deletion.

##### [HISTORICAL] 2. Use a full settings information architecture once security appears

A modal works for three profile fields. It becomes the wrong container when the surface includes:

- Password change.
- Email verification.
- Active sessions.
- MFA.
- Data export.
- Account deletion.
- Role/tier information.
- Multiple preference categories.

The best surfaces use a full page or settings route with persistent navigation. The modal remains useful for a small quick-edit profile card, not as the entire account system.

##### [HISTORICAL] 3. Make scope explicit

Users need to know whether an action affects:

- This field.
- This conversation.
- All conversations.
- This browser session.
- All active sessions.
- The personal account.
- A team or organization.
- The entire service account.

Notion, Slack, Linear, GitHub, and Vercel are particularly strong here.

##### [HISTORICAL] 4. Separate reversible preferences from irreversible actions

Theme, language, font size, and notification toggles can be immediate.

Password changes, email changes, session revocation, data export, and deletion need:

- Clear descriptions.
- Security context.
- Explicit confirmation.
- A visible result.
- Failure handling.
- Reauthentication where appropriate.

##### [HISTORICAL] 5. Autosave only low-risk controls

Autosave is good for:

- Theme.
- Language.
- Notifications.
- Accessibility toggles.
- Sidebar density.

Explicit save is better for:

- Names.
- Organization.
- Specialization.
- Custom instructions.
- Multi-field identity changes.

A single page may use both, but the behavior must be visible.

##### [HISTORICAL] 6. Give the user a dirty-state model

For explicit-save forms, best-in-class surfaces generally do one of three things:

- Keep Save disabled until something changes.
- Show a sticky save bar only when dirty.
- Guard closing/navigation with an unsaved-changes confirmation.

A form that silently loses edits when a modal closes is unacceptable for account data.

##### [HISTORICAL] 7. Provide specific security operations

A generic “profile” page should not hide:

- Change email.
- Change password.
- Review sessions.
- Revoke sessions.
- Manage MFA/passkeys.
- Review connected apps/tokens.
- Download recovery codes.

GitHub is the clearest model here.

##### [HISTORICAL] 8. Treat data rights as first-class

Users increasingly expect:

- Export my data.
- Delete this conversation.
- Delete all conversations.
- Clear activity.
- Opt out of training or research retention.
- Delete my account.

These are not interchangeable. A product must state what each action deletes and what it does not delete.

##### [HISTORICAL] 9. Make loading, empty, saved, and failure states explicit

A settings surface should distinguish:

- Loading account data.
- No optional data configured.
- Data loaded successfully.
- Unsaved changes.
- Save in progress.
- Save succeeded.
- Save failed.
- Session expired.
- Account unavailable.
- Feature unavailable for this account.

SFDA Copilot already demonstrates this discipline in conversation history, where loading, empty, and unavailable states are deliberately distinct. The same standard should apply to profile settings.

##### [HISTORICAL] 10. Keep high-frequency preferences close to the user

Language, theme, notifications, accessibility, and assistant behavior should be easy to reach. They should not require navigating through security or billing.

##### [HISTORICAL] Common but wrong patterns

**One giant “Profile” form:** Common, but wrong once account security and data controls are added.

**Autosaving identity fields without feedback:** Convenient, but dangerous when network failure or stale data can overwrite a newer value.

**Putting Delete Account beside Save Changes:** Visually efficient, but creates an avoidable destructive-action hazard.

**Calling chat deletion “account deletion”:** Misleading. Conversation deletion, history clearing, archive withdrawal, and account deletion have different retention implications.

**Using an avatar as the primary identity cue without text:** Fails in Arabic, on low-bandwidth connections, for screen readers, and for users who do not upload an image.

**Hiding security under “Advanced”:** A common attempt to simplify settings that makes password, sessions, MFA, and connected-app risks harder to discover.

**Treating language as only a header toggle:** It is useful for quick switching, but it does not explain whether the preference is account-level, browser-level, or temporary.

**Showing an empty state after a failed request:** This is particularly wrong for history, export, and security data. “No data” is not the same as “data could not be loaded”.

---

#### [HISTORICAL] 3. Gap Analysis Against SFDA Copilot

| Capability | Best-in-class does | We currently do | Gap severity | Effort |
|---|---|---|---|---|
| Avatar and identity | Shows a recognizable identity card with avatar, display name, email, organization/context, and edit affordance. | The sidebar has a Profile button and auth status, but no avatar or identity summary. The profile form has only `full_name`, `organization`, and `specialization` (`web/templates/index.html:282-297`). | High | M |
| Structured identity | Separates display name components or clearly defines the meaning of one full-name field; supports organization and professional context. | One free-text full name plus organization and specialization. The product TODO explicitly identifies identity-field restructuring as still open (`TODO.md:1021-1030`, `1073-1075`). | Med | M |
| Email display and change | Shows current email, verification status, pending change, and a secure change flow requiring confirmation. | Email exists in Supabase Auth and is used by login, but is not displayed or editable in the profile modal. `getProfile` selects only profile-table fields, not email (`static/js/modules/services.js:665-675`). | Critical | L |
| Password management | Provides change-password and forgot-password flows, with current-password or reauthentication handling where appropriate. | Forgot-password recovery exists: the auth modal exposes the reset link (`web/templates/index.html:195-196`), and recovery uses `updateUser({ password })` (`static/js/modules/services.js:367-379`). There is no signed-in “change password” section in Profile. | High | M |
| Active sessions and devices | Lists recent sessions/devices and provides revoke-one or revoke-all controls. | Logout exists, and `Services.logout()` requests global sign-out (`static/js/modules/services.js:413-430`), but there is no session/device list or dedicated “end all other sessions” UI. | Critical | L |
| Language preference | Places language in settings while retaining a convenient global switch; clearly persists its scope. | Language is outside Profile: buttons appear in the landing utility and sidebar (`web/templates/index.html:329-344`, `web/templates/partials/_sidebar.html:132-139`). It persists in `localStorage` and a cookie, then reloads the page (`static/js/modules/i18n.js:45-67`). This works, but is browser/cookie-oriented rather than clearly account-oriented. | Med | S |
| Theme preference | Offers theme, system default, and sometimes separate high-contrast/reduced-motion choices; clearly shows saved versus current state. | Profile stores a theme preference inside `preferences` and applies it on save (`static/js/modules/handlers.js:1514-1525`). The global theme manager also persists immediately in `localStorage` and detects system preference (`static/js/modules/theme.js:12-41`). The two mechanisms have different scopes. | Med | S |
| Chat-history visibility | Shows durable history with clear retention language and lets users manage it in context. | Durable history is shipped. The product explains that chats restore across devices and that signing out/new chat do not delete them (`web/i18n/en.yaml:44-72`). The sidebar supports list, rename, and delete (`static/js/modules/handlers.js:451-519`, `704-779`). | Low | S |
| Bulk chat-history management | Provides select-all, delete-all, retention controls, or a dedicated data-management page. | Users can delete conversations individually from the sidebar. There is no bulk delete or account-level history management surface. The database supports per-session deletion and cascade (`supabase/migrations/20260821145319_chat_navigation_rpcs.sql:178-220`). | High | M |
| Chat export | Allows a user to download their own conversations in a readable, portable format. | No reader-facing export control or route was found. Chat history is readable through internal history/session APIs, but that is not an export feature (`web/api/app.py:2020-2130`, `2202-2379`). | High | M |
| Data/privacy controls | Explains what is stored, why, retention, model/provider use, and offers controls for history/training/analytics. | There is a strong disclosure warning not to enter patient, clinical-trial, personal, confidential, or proprietary data (`web/i18n/en.yaml:66-72`). There is no user-facing privacy-control panel. `chat_archive` is dormant and service-role-only (`supabase/README.md:79-97`), which is safer than exposing it but not a user control. | High | M |
| Account deletion | Provides a clearly labeled account-deletion flow with impact summary, reauthentication, confirmation, and post-delete sign-out. | Auth routes include signup, login, recovery, and logout (`web/api/auth.py:87-312`), but no reader-facing account deletion route or control. The client handles a `USER_DELETED` event defensively (`static/js/app.js:464-476`), which is not the same as offering deletion. | Critical | L |
| Accessibility preferences | Offers reduced motion, text size, contrast/theme, and sometimes keyboard/reading preferences. | Reduced motion is detected from the operating system via `prefersReducedMotion` (`static/js/modules/config.js:116-118`), and the design system has motion guidance. Profile has no accessibility controls, font-size control, contrast mode, or reading-density preference. | Med | M |
| Notification preferences | Separates product alerts, email notifications, security notices, and chat/history notifications. | No notification controls or notification preference keys are present in the Profile surface. The modal ends at theme preference and Save (`web/templates/index.html:298-315`); the profile service only reads/writes the existing profile shape (`static/js/modules/services.js:665-684`). | Med | M |
| Role and tier display | Shows role, plan/tier, access status, and explanatory read-only labels. | The backend identity response includes role and tier (`web/api/app.py:1931-1932`), and disabled accounts receive an early notice. The profile query deliberately excludes role and tier (`static/js/modules/services.js:665-670`), while profile save is restricted away from privilege columns (`handlers.js:1506-1518`; migration `20260814005509...sql:130-192`). | High | S |
| Disabled/access state | Clearly explains account standing and who to contact without presenting a broken form. | This is comparatively strong. The app distinguishes a disabled account and shows a notice before the user asks a question (`static/js/app.js:450-459`; `web/templates/index.html:572-584`). Profile does not yet show the same standing information. | Low | S |
| Keyboard access | Uses predictable tab order, visible focus, Escape behavior, and no hover-only controls; security actions are reachable without a pointer. | The global focus ring exists (`static/css/base.css:80-85`), and sidebar tabs have deliberate roving-tab behavior (`_sidebar.html:76-92`; `handlers.js:803-837`). The profile form uses native labels and buttons, but has no explicit dirty-state, focus-on-error, or close/escape policy of its own (`index.html:271-321`, `handlers.js:1494-1532`). | Med | S |
| Mobile layout | Uses a responsive full-page settings surface or bottom-sheet sections with clear back navigation and no cramped security forms. | Profile is a centered Bootstrap modal (`index.html:271-321`). It is likely usable for the current five controls, but there is no profile-specific mobile layout or plan for a much taller settings surface. The application already uses an offcanvas sidebar on mobile (`index.html:550-569`). | Med | M |
| Dirty-state handling | Shows unsaved state, disables Save when clean, confirms close/navigation when dirty, and avoids overwriting concurrent edits. | `handleProfileFormSubmit` submits whatever is present and immediately closes on success (`handlers.js:1494-1525`). There is no dirty tracking, save-disabled state, close guard, or version/conflict handling. | High | M |
| Validation | Validates field length, allowed values, required fields, and semantic formats inline before the network request. | The profile form is `novalidate` and the handler does not call `checkValidity()` or field-specific validation (`index.html:282`, `handlers.js:1494-1521`). It sends the three text values and theme as-is. | High | S |
| Error surfaces | Places errors beside the affected field, preserves edits, distinguishes expired session from server failure, and offers retry. | There is one generic `#profile-error` region (`index.html:317`) plus generic load/save messages. Load failure resets the form and shows a toast (`handlers.js:1551-1568`); save failure keeps the modal but does not identify a field (`handlers.js:1526-1532`). | High | S |
| Loading state | Shows skeleton or loading controls, prevents duplicate saves, and distinguishes loading from empty profile data. | Profile loading happens only when the modal is opened on a cache miss (`handlers.js:1535-1571`). There is no visible loading state in the modal. A missing profile resets the form; a failed load resets it too, which risks making “unavailable” look like “empty”. | High | S |
| Freshness/concurrency | Re-reads current data when opening or uses version checks to avoid stale overwrites. | The app loads a profile at sign-in and caches it (`static/js/app.js:405-409`). The profile button uses cached data when available (`handlers.js:1547-1555`). The TODO explicitly records that the modal can show the startup snapshot rather than a fresh read (`TODO.md:1031-1039`). | High | M |
| Save confirmation | Uses a sticky save bar or clear inline confirmation, with the saved value re-read where important. | Successful save shows a localized toast and closes the modal (`handlers.js:1521-1525`). There is no persistent saved state, no dirty indicator, and no confirmation that the server’s canonical values match the form. | Med | S |
| Privilege boundaries | Clearly labels role/tier/access as read-only and keeps privileged fields server-controlled. | This is strong at the schema level. Browser grants cover only profile-owned columns and a trigger rejects browser changes to `role`, `tier`, and `is_disabled` (`20260814005509...sql:130-192`). The missing piece is a user-facing read-only presentation. | Low | S |
| Account data ownership | Explains which data belongs to the user, which is retained for operations, and what deletion does not remove. | The history notice says chats are saved and individually deletable. The database documentation states that deleting reader sessions does not delete dormant archive rows or backups (`supabase/migrations/20260821145319_chat_navigation_rpcs.sql:187-191`). This distinction is not exposed as an account data-management UI. | High | M |

#### [HISTORICAL] 4. Recommendation

##### [HISTORICAL] Recommended shape

Build a dedicated server-rendered `/settings` route with a tabbed settings surface.

Do not keep the entire account experience as a modal.

A small profile quick-edit modal could remain later as a convenience, but it should become a shortcut into `/settings`, not the canonical account surface.

##### [HISTORICAL] Why not a larger modal?

The current modal is appropriate for its current contents:

- Three text inputs.
- Two theme radios.
- One Save button.
- One error region.

That surface is defined at `web/templates/index.html:271-321`.

It is not appropriate for the planned account scope. Adding email, password, sessions, export, privacy, notifications, accessibility, role/tier, and deletion would create a long scrollable dialog with nested security workflows and a destructive action inside a temporary context.

It would also make deep linking, browser Back, refresh, and mobile navigation worse.

##### [HISTORICAL] Why a full route fits the actual stack

The application does not have a client-side application router.

`static/js/modules/route.js` is specifically a conversation pointer:

- It recognizes `/c/<uuid>` (`route.js:15-40`).
- It pushes and replaces conversation URLs (`route.js:54-85`).
- It handles Back/Forward for conversation hydration (`route.js:122-142`).

It does not route profile/settings views.

The application’s actual navigation model is server-side Flask paths plus browser-native ES modules:

- Jinja templates are server-rendered.
- Flask currently serves the landing/chat shell and conversation paths.
- Bootstrap 5 already supplies modal, tab, offcanvas, and form primitives.
- There is no bundler or `node_modules`.
- Static modules are loaded through the existing import-map/cache-busting mechanism (`index.html:92-98`).

A `/settings` route would therefore be simpler and more honest than pretending `route.js` is a general SPA router.

##### [HISTORICAL] Suggested settings IA

Use a persistent settings shell:

- **Profile**
  - Avatar or initials.
  - Full name.
  - Organization.
  - Specialization.
  - Email summary.
  - Role, tier, and account standing as read-only metadata.
- **Preferences**
  - Language.
  - Theme: light, dark, system.
  - Reduced motion.
  - Text size.
  - Contrast/reading density.
- **Assistant**
  - Response language behavior.
  - Future assistant preferences.
  - Chat-history defaults if introduced.
- **Notifications**
  - Security notifications.
  - Product announcements.
  - Email notifications if they are eventually added.
- **Data & Privacy**
  - Saved conversations.
  - Export conversations.
  - Delete selected/all conversations.
  - Retention and archive disclosure.
- **Security**
  - Change email.
  - Change password.
  - Active sessions/devices.
  - Revoke other sessions.
  - MFA/passkeys if introduced.
- **Danger Zone**
  - Delete account.
  - Explicit explanation of chat history, archive, backups, and irreversible effects.

Use tabs or a vertical settings navigation visually, but keep each section independently addressable with normal anchors. For example:

- `/settings`
- `/settings#profile`
- `/settings#security`
- `/settings#data`
- `/settings#danger`

If the product later needs shareable deep links, Flask can add distinct server paths without introducing a JavaScript framework.

##### [HISTORICAL] Saving model

Use a hybrid model deliberately:

- Theme, language, reduced motion, text size, and notification toggles: immediate save with an inline confirmation.
- Identity fields: explicit Save button.
- Security actions: one action per form with specific confirmation.
- Export: explicit request/download action.
- Account deletion: separate flow, reauthentication, typed confirmation, and post-delete sign-out.

For identity fields, use a sticky save bar that appears only when the form is dirty:

> You have unsaved changes  
> `Discard` `Save changes`

On mobile, the save bar should remain visible at the bottom of the settings content rather than requiring the user to scroll back to the top.

##### [HISTORICAL] Phased plan

###### [HISTORICAL] P0: Trustworthy account foundation

**Goal:** Replace the fragile modal-only account model with a durable, accessible settings foundation.

- Add a server-rendered `/settings` Flask route and Jinja template.
- Add a settings shell with persistent section navigation.
- Move the existing profile fields into the Profile section.
- Add visible email, account standing, role, and tier as read-only information.
- Add language and theme controls with explicit scope:
  - Account/profile preference where appropriate.
  - Local/browser preference where that is the actual implementation.
- Add profile loading, saving, empty, expired-session, and error states.
- Add field-level validation and length limits.
- Add dirty-state tracking and a sticky save bar.
- Re-read the profile after save or use a version/updated-at check.
- Add full English and Arabic catalogue coverage before shipping the route.
- Preserve native Bootstrap modal focus behavior only for the quick-edit shortcut, if retained.
- Ensure all new CSS uses logical properties and existing semantic tokens.

**Why first:** The current surface has a small amount of functionality but weak state handling. P0 should make existing account data reliable before adding more settings.

###### [HISTORICAL] P1: Security and data rights

**Goal:** Address the highest-risk gaps.

- Add signed-in password change.
- Add secure email-change flow with verification and pending-state copy.
- Add “log out other sessions” or “end all sessions”.
- Add active session/device visibility if the auth provider supports it; otherwise expose the exact limitation.
- Add conversation export in a documented format such as JSON and human-readable HTML/Markdown.
- Add bulk conversation deletion.
- Add a Data & Privacy section explaining:
  - What is stored.
  - Why it is stored.
  - What individual chat deletion removes.
  - What account deletion removes.
  - What archive/backups may retain.
- Define and implement account deletion semantics.
- Require reauthentication for email change, session revocation, and account deletion.
- Ensure account deletion clears client state and signs out every relevant session.

**Why second:** Security and data ownership are more important than profile polish. Users can tolerate not having an avatar; they should not be unable to secure or delete their account.

###### [HISTORICAL] P2: Personalization and professional polish

**Goal:** Match the best assistant experiences without overloading the core flow.

- Add avatar upload or generated initials, with a text fallback.
- Consider structured first/family name only if there is a clear product use for it; do not collect demographic data without a regulatory/product justification.
- Add reduced-motion, text-size, contrast, and reading-density preferences.
- Add notification settings once the product actually sends multiple notification types.
- Add assistant behavior preferences only when the product has stable behavior worth configuring.
- Add keyboard-shortcut preferences if the chat surface gains a command system.
- Add connected-account or integration management only if integrations ship.
- Add account activity/security history if operational requirements justify it.
- Add a small profile quick-edit modal as a shortcut, linked to the full settings route.

**Why third:** These are valuable but should not delay secure identity, data, and deletion controls.

#### [HISTORICAL] 5. RTL and Bilingual Specifics

##### [HISTORICAL] What SFDA Copilot already does well

Arabic is structurally represented in the product:

- The document sets `lang` and `dir` server-side (`web/templates/index.html:4`).
- The product uses Arabic-first display typography and a shared bilingual body family (`index.html:20-29`).
- The design system explicitly treats RTL as structural, not as a theme variant (`DESIGN.md:155-159`).
- RTL resets tracking and increases line height to protect Arabic joining and readability (`static/css/tokens.css:260-282`).
- Logical CSS properties are mandatory, and the design system explicitly prohibits physical left/right layout assumptions (`DESIGN.md:236-244`).
- Sidebar tabs reverse arrow-key semantics under RTL (`static/js/modules/handlers.js:816-837`).
- The language switch reloads server-rendered content so `dir`, Jinja strings, and FAQ data are consistent (`static/js/modules/i18n.js:7-14`, `45-67`).
- The current profile runtime strings exist in both English and Arabic catalogues (`web/i18n/en.yaml:186-191`, `web/i18n/ar.yaml:122-127`).

These are strong foundations for a settings route.

##### [HISTORICAL] Arabic-first account design requirements

**Do not make Arabic a translated copy of an English settings layout.**

The settings architecture should be tested in Arabic first for:

- The longest section labels.
- Validation messages.
- Security warnings.
- Delete-account confirmation.
- Pending email-change copy.
- Export explanations.
- Session/device names containing Latin product names.
- Mixed Arabic and Latin organization names.

**Use logical placement, not visual mirroring by hand.**

- Use `margin-inline`, `padding-inline`, `inset-inline`, and `border-inline`.
- Avoid hardcoded “left column” and “right column” assumptions.
- The selected settings section should remain visually obvious in both directions.
- The danger-zone marker should follow the logical start/end conventions without implying that danger is inherently on one physical side.

**Keep controls in reading order.**

For Arabic:

- Section heading first.
- Explanation second.
- Field label and field third.
- Error/help text immediately after the field.
- Action buttons in the expected reading order.
- Destructive actions separated spatially and semantically from ordinary saves.

Do not simply reverse button order with CSS if the DOM order becomes confusing to screen readers.

**Treat mixed-direction data deliberately.**

Account settings will contain:

- Arabic names.
- English organization names.
- Email addresses.
- URLs.
- UUIDs.
- Session/device names.
- Export filenames.
- Dates and numeric limits.

Use `dir="auto"` for user-entered names and organization text. Use `direction: ltr; unicode-bidi: isolate` for emails, URLs, UUIDs, timestamps, and technical identifiers. Do not allow an Arabic paragraph to reorder an email address or verification code.

**Do not italicize Arabic.**

The design system correctly warns that synthetic italics can damage connected Arabic letterforms (`DESIGN.md:381-395`). Use weight, color, or a rule instead of italic emphasis for:

- “Current”.
- “Pending”.
- “Untitled”.
- “Optional”.
- “Danger zone” explanations.

**Do not uppercase Arabic labels.**

The current token system disables uppercase treatment and tracking under RTL (`static/css/tokens.css:268-287`). New settings section labels should preserve that rule.

**Give Arabic enough vertical space.**

Arabic copy is often taller than English copy, especially in:

- Delete-account warnings.
- Privacy disclosures.
- Password requirements.
- Session explanations.
- Field-level validation.
- Toasts and inline notices.

Avoid fixed-height notices and buttons that assume English line lengths.

**Do not make the language switch disappear inside settings.**

The global language switch is currently outside Profile, in the landing and sidebar chrome. That is good for discoverability, but the settings route should also show the current language and explain persistence. The global control should remain available so a user who lands in the wrong language does not need to understand the settings UI first.

**Localize security email copy outside the repository catalogue.**

The product already recognizes that recovery email templates are a special case. Any email-change, password-reset, session-revocation, or account-deletion email must be authored and tested in both languages. A bilingual web UI with English-only security emails is not bilingual account management.

**Handle Arabic plural forms correctly.**

Settings may introduce counts for:

- Active sessions.
- Conversations selected.
- Exported messages.
- Deleted chats.
- Days until deletion.
- Devices.

The existing runtime plural helper is intentionally limited, and the Arabic catalogue itself documents that exactly-two forms need special handling (`web/i18n/ar.yaml:143-148`). A settings surface should use Arabic-aware count messages rather than mechanically inserting numerals into English-shaped templates.

**Test keyboard directionality.**

For RTL settings:

- Arrow-key navigation between tabs must move according to the visible order.
- Tab order must follow the logical DOM order.
- Escape should close the current dialog or cancel the current inline edit, not both.
- Focus should move to the first invalid field after validation.
- Focus should return to the settings trigger after a modal shortcut closes.
- Delete confirmations should keep focus inside the confirmation region until the action is resolved.

**Preserve professional terminology.**

The product already has domain-specific Arabic terminology for regulatory work. Account settings should use formal, clear Modern Standard Arabic rather than literal machine translations. In particular, distinguish:

- الحساب from الملف الشخصي.
- الجلسات النشطة from الأجهزة الموثوقة if the system does not actually establish trust.
- حذف المحادثة from حذف الحساب.
- تصدير البيانات from تنزيل نسخة احتياطية.
- إيقاف الوصول from تعطيل الحساب.
- البريد الإلكتروني قيد التحقق from بريد إلكتروني غير صالح.

The central recommendation is therefore a **bilingual, RTL-native `/settings` surface with explicit personal, security, data, and danger sections**, rather than an ever-growing profile modal.

<!-- END VERBATIM — Appendix A -->

---

## [HISTORICAL] Appendix B — Security audit

**Implementer:** Google Antigravity CLI · `gemini-3.7-flash-high` (read-only)
**Dispatched:** 2026-08-22 · **Working tree:** untouched

> Reproduced verbatim. Findings 1 and 2 were independently re-verified against the migrations in this session and are carried into §0.3-B and §0.3-C. Its avatar-upload threat model is the reason Decision 4 declines uploads outright.

<!-- BEGIN VERBATIM — Appendix B -->

### [HISTORICAL] Security Audit: User-Profile Surface (Client → API → Supabase)

**Target:** SFDA Copilot (Regulatory Bilingual Chatbot)  
**Scope:** Client profile handling (`static/js/modules/*`, `static/js/admin/*`), API layer (`web/api/app.py`, `web/api/auth.py`, `web/api/admin.py`), and Database schema / RLS policies / triggers / RPCs (`supabase/migrations/*.sql`).  
**Audit Mode:** Read-only architectural and source code security assessment.

---

#### [HISTORICAL] Executive Summary

The SFDA Copilot user-profile and identity architecture demonstrates strong adherence to security principles in several critical areas:
1. **Administrative RPC isolation & concurrency:** Sensitive operations (`admin_set_user_flags`, `admin_update_profile`, `admin_write_settings`) run via `SECURITY DEFINER` functions with fixed `search_path = ''`, transactional re-validation of actor privileges (`AD004`), advisory locking against write-skew race conditions (`sfda.admin_membership`), and atomic audit logging.
2. **XSS Protection:** Profile text fields (`full_name`, `organization`, `specialization`, `disabled_reason`) are rendered via standard DOM properties (`textContent`, `input.value`) rather than `innerHTML`, preventing stored XSS across both client and administrative interfaces.
3. **Column-Level Revocations:** Table-level write privileges are revoked from `authenticated` and `anon` on `public.profiles`, granting only an explicit column allow-list.

However, the audit identified security weaknesses and architectural gaps that must be addressed, particularly as the surface prepares for expansion:
- **Unbounded client-side writes:** Unbounded `TEXT` and `JSONB` columns on `public.profiles` allow authenticated users writing directly via Supabase PostgREST to store multi-megabyte payloads, creating persistent resource exhaustion and DoS vectors for administrative views and audit logs.
- **RLS isolation gap for disabled accounts:** Disabling an account (`is_disabled = true`) blocks Flask API access but does not revoke Supabase tokens or restrict direct PostgREST reads/deletions under RLS.
- **Incomplete trigger defence-in-depth:** The `profiles_guard_privilege_columns` trigger only attaches to `UPDATE` (omitting `INSERT`) and monitors only 3 of the 7 sensitive columns.

---

#### [HISTORICAL] Severity-Ranked Summary Table

| # | Severity | Title | File:Line | Exploitable Today? |
|---|---|---|---|---|
| 1 | **Medium** | Unbounded Profile Field Lengths & Arbitrary JSON Payloads on Browser-Direct Writes | [`supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql#L84-L90`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql#L84-L90) | **Yes** |
| 2 | **Medium** | Disabled Accounts Retain Direct Supabase PostgREST Read and Delete Access Under RLS | [`supabase/migrations/20260820131914_chat_session_persistence.sql#L177-L201`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260820131914_chat_session_persistence.sql#L177-L201) | **Yes** |
| 3 | **Low** | Privilege Guard Trigger Omits `INSERT` and Leaves Auxiliary Administrative Columns Unchecked | [`supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql#L168-L193`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql#L168-L193) | No (Gated by column grant) |
| 4 | **Low** | Missing Explicit `frame-ancestors` in CSP and Conditional Omission of HSTS Headers Behind Proxy | [`web/api/app.py#L1244-L1280`](file:///E:/Documents/AI_Project/SFDA_copilot/web/api/app.py#L1244-L1280) | No (Mitigated by default `X-Frame-Options`) |
| 5 | **Informational** | Profile Field DOM Rendering Verification (Stored XSS Analysis) | [`static/js/modules/ui.js#L818-L833`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/modules/ui.js#L818-L833), [`static/js/admin/ui.js#L1154-L1160`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/admin/ui.js#L1154-L1160) | **Not Exploitable** (Secure) |
| 6 | **Informational** | `SECURITY DEFINER` Function Search Path and Privilege Isolation Verification | [`supabase/migrations/*.sql`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations) | **Not Exploitable** (Secure) |

---

#### [HISTORICAL] Detailed Findings

---

##### [HISTORICAL] Finding 1: Unbounded Profile Field Lengths & Arbitrary JSON Payloads on Browser-Direct Writes

- **Severity:** Medium
- **Location:**
  - Database: [`supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql#L84-L90`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql#L84-L90)
  - Client Form: [`web/templates/index.html#L284-L297`](file:///E:/Documents/AI_Project/SFDA_copilot/web/templates/index.html#L284-L297)
  - Client Handler: [`static/js/modules/handlers.js#L1514-L1521`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/modules/handlers.js#L1514-L1521)
  - Supabase Service: [`static/js/modules/services.js#L677-L684`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/modules/services.js#L677-L684)

###### [HISTORICAL] What is wrong
The reader-facing profile update flow communicates **directly from the browser to Supabase PostgREST** using the client-side Supabase JS SDK (`Services.updateProfile`), completely bypassing the Flask backend. 
While Flask's admin API strictly enforces `_PROFILE_MAX_LENGTH = 200` ([`web/api/admin.py:315`](file:///E:/Documents/AI_Project/SFDA_copilot/web/api/admin.py#L315)), there are **zero database-level `CHECK` constraints** on `public.profiles.full_name`, `organization`, or `specialization`. Furthermore, `preferences` is an unconstrained `JSONB` column, and the HTML input elements in [`web/templates/index.html`](file:///E:/Documents/AI_Project/SFDA_copilot/web/templates/index.html#L284-L297) lack `maxlength` attributes.

###### [HISTORICAL] Attack scenario
1. An authenticated reader crafts a PostgREST request using their anon key and session JWT:
   ```javascript
   const hugePayload = 'A'.repeat(5 * 1024 * 1024); // 5 MB string
   await supabase.from('profiles').update({
     full_name: hugePayload,
     organization: hugePayload,
     specialization: hugePayload,
     preferences: { deep_nesting: { data: hugePayload } }
   }).eq('id', myUserId);
   ```
2. Postgres accepts the write because `full_name`, `organization`, and `specialization` are unbounded `TEXT`, and `preferences` is valid `JSONB`.
3. When an administrator views the **People** list ([`static/js/admin/ui.js:589`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/admin/ui.js#L589)) or opens the account detail modal ([`static/js/admin/ui.js:1125`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/admin/ui.js#L1125)), `admin_get_user` transfers multiple megabytes of data, causing high memory usage, network latency, and potential browser rendering freezes (Client-side DoS).
4. If an administrator subsequently edits any field on the target account, `admin_update_profile` ([`supabase/migrations/20260814200342_admin_update_profile.sql:97-106`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260814200342_admin_update_profile.sql#L97-L106)) copies the entire multi-megabyte `before` and `after` records into `public.audit_log`, permanently bloating the append-only audit table.

###### [HISTORICAL] Why it works / why it fails
- **Exploitable today:** The direct PostgREST client endpoint is fully reachable by any authenticated user. The column-level grant allows `full_name`, `organization`, `specialization`, and `preferences` writes. Neither PostgREST nor PostgreSQL enforces string length or JSON size limits on this table.

###### [HISTORICAL] Fix
Add database-level `CHECK` constraints on `public.profiles` in a new migration, and add HTML `maxlength` bounds in `index.html`:

```sql
-- Migration: Add bounds to public.profiles reader-writable columns
alter table public.profiles
  add constraint profiles_full_name_len_chk
    check (full_name is null or char_length(full_name) <= 200),
  add constraint profiles_organization_len_chk
    check (organization is null or char_length(organization) <= 200),
  add constraint profiles_specialization_len_chk
    check (specialization is null or char_length(specialization) <= 200),
  add constraint profiles_preferences_size_chk
    check (preferences is null or octet_length(preferences::text) <= 4096);
```

---

##### [HISTORICAL] Finding 2: Disabled Accounts Retain Direct Supabase PostgREST Read and Delete Access Under RLS

- **Severity:** Medium
- **Location:**
  - Database RLS Policies: [`supabase/migrations/20260820131914_chat_session_persistence.sql#L177-L201`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260820131914_chat_session_persistence.sql#L177-L201)
  - Admin Disable Handler: [`web/api/admin.py#L676-L747`](file:///E:/Documents/AI_Project/SFDA_copilot/web/api/admin.py#L676-L747)
  - Baseline Profile Policies: [`supabase/migrations/0000_baseline.md#L12-L13`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/0000_baseline.md#L12-L13)

###### [HISTORICAL] What is wrong
When an administrator disables an account via `PATCH /admin/api/users/<user_id>` (`is_disabled = true`), the Flask backend immediately rejects subsequent chat requests with HTTP 403 `account_disabled` ([`web/api/app.py:384-398`](file:///E:/Documents/AI_Project/SFDA_copilot/web/api/app.py#L384-L398)).
However:
1. Setting `is_disabled = true` **does not invalidate existing Supabase JWT access tokens or refresh tokens in GoTrue** (as acknowledged in [`web/api/admin.py:680-683`](file:///E:/Documents/AI_Project/SFDA_copilot/web/api/admin.py#L680-L683)).
2. The RLS policies on `public.profiles`, `public.chat_sessions`, `public.chat_messages`, and `public.chat_message_sources` only check `owner_id = (select auth.uid())` or `id = auth.uid()`. **None of the RLS policies check `public.profiles.is_disabled`**.

###### [HISTORICAL] Attack scenario
1. An administrator disables a compromised or departing employee's account (`is_disabled = true`).
2. The user's browser client still holds a valid Supabase JWT session (valid for up to 1 hour, or indefinitely refreshed if the admin did not separately click "Revoke Sessions").
3. The user directly invokes the Supabase client:
   - `supabase.from('chat_sessions').select('*, chat_messages(*)')` — **Succeeds:** downloads confidential transcripts and regulatory research history directly under `chat_sessions_select_own` RLS.
   - `supabase.from('chat_sessions').delete().eq('id', sessionId)` — **Succeeds:** permanently erases conversation transcripts under `chat_sessions_delete_own` RLS.
   - `supabase.from('profiles').update({ ... })` — **Succeeds:** continues modifying profile data.

###### [HISTORICAL] Why it works / why it fails
- **Exploitable today:** Setting `is_disabled = true` only gates Flask endpoints (`@auth_required` / `_authenticate_request`). Because the browser communicates directly with Supabase PostgREST for RLS-governed tables, a disabled user with an active JWT bypasses Flask entirely.

###### [HISTORICAL] Fix
Update RLS policies on reader-accessible tables to explicitly require that the requesting user's profile is not disabled:

```sql
-- Helper function to check if active caller is enabled
create or replace function public.is_active_account()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.profiles
     where id = (select auth.uid())
       and is_disabled = false
  );
$$;

revoke execute on function public.is_active_account() from anon, public;
grant execute on function public.is_active_account() to authenticated;

-- Update RLS policies to check active standing
drop policy if exists chat_sessions_select_own on public.chat_sessions;
create policy chat_sessions_select_own on public.chat_sessions
  for select to authenticated
  using (owner_id = (select auth.uid()) and public.is_active_account());

drop policy if exists chat_sessions_delete_own on public.chat_sessions;
create policy chat_sessions_delete_own on public.chat_sessions
  for delete to authenticated
  using (owner_id = (select auth.uid()) and public.is_active_account());
```

---

##### [HISTORICAL] Finding 3: Privilege Guard Trigger Omits `INSERT` and Leaves Auxiliary Administrative Columns Unchecked

- **Severity:** Low (Defence-in-Depth)
- **Location:** [`supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql#L168-L193`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql#L168-L193)

###### [HISTORICAL] What is wrong
Migration `20260814005509` established two layers of defence against privilege escalation:
1. **Primary:** Column-level `REVOKE` and targeted `GRANT` ([lines 139–151](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql#L139-L151)).
2. **Secondary (Trigger):** `profiles_guard_privilege_columns` trigger ([lines 168–193](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql#L168-L193)), explicitly added because *"Supabase re-grants table privileges on some schema operations"* ([line 17](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql#L17)).

Two gaps exist in the trigger defence-in-depth layer:
1. **The trigger is `BEFORE UPDATE` only:** It does not trigger on `INSERT`. If table-level privileges are ever restored by Supabase tooling, a user performing a direct `INSERT` (e.g. if their profile was missing or deleted) can insert `role = 'admin'` without tripping the trigger.
2. **Unmonitored Administrative Columns:** The trigger checks only `role`, `tier`, and `is_disabled`. It does not monitor `disabled_at`, `disabled_by`, `disabled_reason`, or `last_seen_at`.

###### [HISTORICAL] Attack scenario
If table-level grants are restored by an administrative schema sync or dashboard action:
1. An attacker sends an `INSERT` with `role = 'admin'`. Because the trigger only listens for `BEFORE UPDATE`, the trigger does not execute, and the row lands with `role = 'admin'`.
2. An attacker sends an `UPDATE` with `disabled_by = '<victim_admin_uuid>'` or `disabled_reason = 'tampered'`. The trigger compares `new.role`, `new.tier`, and `new.is_disabled`, finds no change, and allows the write to complete.

###### [HISTORICAL] Why it works / why it fails
- **Currently Not Exploitable:** Postgres column-level permissions (`REVOKE INSERT, UPDATE ... GRANT INSERT (id, full_name, organization, specialization, preferences)`) reject PostgREST requests mentioning ungranted columns at the SQL parser stage. The vulnerability becomes active only if table-level write privileges are re-granted.

###### [HISTORICAL] Fix
Upgrade the trigger to cover `INSERT OR UPDATE` and guard all non-user-editable columns:

```sql
create or replace function public.profiles_guard_privilege_columns()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if current_user in ('authenticated', 'anon') then
    if TG_OP = 'INSERT' then
      if new.role is distinct from 'user'
         or new.tier is distinct from 'free'
         or new.is_disabled is distinct from false
         or new.disabled_at is not null
         or new.disabled_by is not null
         or new.disabled_reason is not null
         or new.last_seen_at is not null then
        raise exception 'administrative profile columns cannot be set on insert'
          using errcode = '42501';
      end if;
    elsif TG_OP = 'UPDATE' then
      if new.role is distinct from old.role
         or new.tier is distinct from old.tier
         or new.is_disabled is distinct from old.is_disabled
         or new.disabled_at is distinct from old.disabled_at
         or new.disabled_by is distinct from old.disabled_by
         or new.disabled_reason is distinct from old.disabled_reason
         or new.last_seen_at is distinct from old.last_seen_at then
        raise exception 'administrative profile columns are administered server-side'
          using errcode = '42501';
      end if;
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists profiles_guard_privilege_columns on public.profiles;
create trigger profiles_guard_privilege_columns
  before insert or update on public.profiles
  for each row execute function public.profiles_guard_privilege_columns();
```

---

##### [HISTORICAL] Finding 4: Missing Explicit `frame-ancestors` in CSP and Conditional Omission of HSTS Headers Behind Proxy

- **Severity:** Low
- **Location:** [`web/api/app.py#L1244-L1280`](file:///E:/Documents/AI_Project/SFDA_copilot/web/api/app.py#L1244-L1280)

###### [HISTORICAL] What is wrong
1. **CSP `frame-ancestors`:** The CSP dictionary in [`web/api/app.py`](file:///E:/Documents/AI_Project/SFDA_copilot/web/api/app.py#L1244-L1251) omits the `frame-ancestors` directive. While `flask-talisman` injects the legacy `X-Frame-Options: SAMEORIGIN` header by default, modern browsers prioritize CSP `frame-ancestors`.
2. **HSTS Header:** Line 1265 sets `should_force_https = not (is_debug_mode or testing or is_behind_proxy)`. When `is_behind_proxy` is `True`, `force_https` is disabled in `Talisman`. While `ProxyFix` correctly handles forwarded protocols, disabling `force_https` in Talisman causes it to skip injecting `Strict-Transport-Security` (HSTS) headers into the response, leaving HSTS enforcement entirely dependent on upstream proxy configuration.

###### [HISTORICAL] Attack scenario
If the application is embedded in a malicious iframe on a third-party domain that ignores legacy `X-Frame-Options` or exploits frame hierarchy edge cases, an attacker could attempt clickjacking on the profile modal form.

###### [HISTORICAL] Why it works / why it fails
- **Currently Mitigated:** Standard browsers still respect `X-Frame-Options: SAMEORIGIN`. However, modern defence standards require explicit CSP `frame-ancestors 'self'`.

###### [HISTORICAL] Fix
Add `frame-ancestors: "'self'"` to the CSP configuration in [`web/api/app.py`](file:///E:/Documents/AI_Project/SFDA_copilot/web/api/app.py#L1244-L1251):

```python
csp = {
    "default-src": ["'self'"],
    "frame-ancestors": ["'self'"],
    "script-src": ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://cdn.lordicon.com", "https://cdnjs.cloudflare.com"] + impeccable_live_dev,
    "style-src": ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com", "https://fonts.googleapis.com"],
    "img-src": ["'self'", "data:", "https:"],
    "font-src": ["'self'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com", "data:", "https://fonts.gstatic.com", "https://r2cdn.perplexity.ai"],
    "connect-src": connect_src + impeccable_live_dev,
}
```

---

##### [HISTORICAL] Finding 5: Profile Field DOM Rendering Verification (Stored XSS Analysis)

- **Severity:** Informational (Verified Secure)
- **Location:**
  - Client UI: [`static/js/modules/ui.js#L818-L833`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/modules/ui.js#L818-L833)
  - Client Error Presentation: [`static/js/modules/dom.js#L237-L243`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/modules/dom.js#L237-L243)
  - Admin Account Detail: [`static/js/admin/ui.js#L1154-L1160`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/admin/ui.js#L1154-L1160)
  - Admin People Table: [`static/js/admin/ui.js#L646-L680`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/admin/ui.js#L646-L680)
  - Admin Audit Table: [`static/js/admin/ui.js#L788-L799`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/admin/ui.js#L788-L799), [`static/js/admin/ui.js#L859-L870`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/admin/ui.js#L859-L870)

###### [HISTORICAL] What was analyzed
Stored XSS targeting administrators through user-controlled profile fields (`full_name`, `organization`, `specialization`, `preferences`) represents the highest-severity vector in profile architectures. Every sink rendering profile attributes was traced:
1. `populateProfileForm` ([`static/js/modules/ui.js:818`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/modules/ui.js#L818)) sets `fullNameInput.value = full_name` (safe, does not parse HTML).
2. `renderAccountDetail` ([`static/js/admin/ui.js:1154`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/admin/ui.js#L1154)) constructs `person = [account.full_name, account.organization].filter(Boolean).join(' · ')` and assigns it via `line.textContent = person` (safe, plain text node).
3. `profileForm` in Admin UI ([`static/js/admin/ui.js:1376`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/admin/ui.js#L1376)) assigns values via `input.value = account[name] || ''` (safe).
4. `describeChange` / `renderAudit` in Admin UI ([`static/js/admin/ui.js:796, 865`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/admin/ui.js#L796)) builds diff strings and assigns via `change.textContent = ...` (safe).
5. `user.disabled_reason` in People list ([`static/js/admin/ui.js:677`](file:///E:/Documents/AI_Project/SFDA_copilot/static/js/admin/ui.js#L677)) assigns via `why.textContent = user.disabled_reason` (safe).

###### [HISTORICAL] Verdict
**Not Exploitable.** The frontend and admin console consistently use standard DOM text-node creation and value assignment. No unsafe `innerHTML`, `eval()`, or unescaped template string interpolations exist in the profile rendering pipeline.

---

##### [HISTORICAL] Finding 6: `SECURITY DEFINER` Function Search Path and Privilege Isolation Verification

- **Severity:** Informational (Verified Secure)
- **Location:** [`supabase/migrations/*.sql`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations)

###### [HISTORICAL] What was analyzed
All 13 `SECURITY DEFINER` functions in the database were evaluated against privilege escalation and SQL injection vectors:
1. `handle_new_user` ([`20260814005509:51`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql#L51))
2. `admin_write_settings` ([`20260814032447:87`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260814032447_audit_log.sql#L87))
3. `admin_list_users` ([`20260817161427:20`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260817161427_people_pager_sort_tiebreaker_and_search_escape.sql#L20))
4. `admin_set_user_flags` ([`20260816121335:25`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260816121335_diff_based_admin_user_flags_audit.sql#L25))
5. `admin_get_user` ([`20260816215103:25`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260816215103_admin_get_user_email_verified.sql#L25))
6. `admin_update_profile` ([`20260814200342:22`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260814200342_admin_update_profile.sql#L22))
7. `chat_append_turn` ([`20260822090100:71`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260822090100_chat_append_turn_allow_create.sql#L71))
8. `chat_load_session` ([`20260821224534:48`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260821224534_chat_load_session_batch_sources_fix_join_form.sql#L48))
9. `chat_latest_session` ([`20260820131914:610`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260820131914_chat_session_persistence.sql#L610))
10. `chat_list_sessions` ([`20260821145319:60`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260821145319_chat_navigation_rpcs.sql#L60))
11. `chat_rename_session` ([`20260821145319:132`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260821145319_chat_navigation_rpcs.sql#L132))
12. `chat_delete_session` ([`20260821145319:192`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260821145319_chat_navigation_rpcs.sql#L192))
13. `chat_session_exists` ([`20260822090000:25`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260822090000_chat_session_exists.sql#L25))

###### [HISTORICAL] Verification results
- **Search Path:** Every function sets `set search_path = ''` and uses fully qualified table references (`public.*`, `auth.*`), satisfying project Rule 3.
- **Grants:** `EXECUTE` is explicitly revoked from `anon`, `authenticated`, and `public` across all functions, granting access solely to `service_role`.
- **Dynamic SQL:** Zero functions construct dynamic SQL via `format()` or `EXECUTE ... USING`.
- **Authorization Check:** Admin mutations (`admin_set_user_flags`, `admin_update_profile`) execute internal `SELECT ... FROM public.profiles WHERE id = p_actor_id` queries inside the active transaction to verify admin status (`AD004`), preventing authorization state bypasses.

---

#### [HISTORICAL] Threat Model & Vulnerability Analysis for Planned Profile Surface Expansion

The planned refactor aims to introduce **avatar uploads, email changes, password changes, active session management, chat history export, and account deletion**. The specific vulnerability classes and required controls for each are detailed below:

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                               PLANNED EXPANSION THREAT MODEL                             │
├──────────────────────────┬─────────────────────────────┬─────────────────────────────────┤
│ Surface Component        │ Vulnerability Class         │ Required Primary Control        │
├──────────────────────────┼─────────────────────────────┼─────────────────────────────────┤
│ 1. Avatar Upload         │ Stored XSS via SVG / Polyglot│ Magic byte inspection, raster   │
│    (Supabase Storage)    │ Storage Bucket Path Traversal│ re-encoding (PNG/WebP), bucket  │
│                          │ Storage Quota Exhaustion    │ RLS: (storage.foldername(name)) │
├──────────────────────────┼─────────────────────────────┼─────────────────────────────────┤
│ 2. Email Change          │ Unverified Account Takeover │ Double-confirmation flow        │
│                          │ Impersonation Primitive     │ (veto link to current address)  │
├──────────────────────────┼─────────────────────────────┼─────────────────────────────────┤
│ 3. Password Change       │ Session Hijack Persistence  │ Sudo-mode (current password),   │
│                          │ Credential Stuffing         │ Global session revocation       │
├──────────────────────────┼─────────────────────────────┼─────────────────────────────────┤
│ 4. Active Sessions List  │ IDOR / Token Leakage        │ Strict auth.uid() scope, opaque │
│                          │                             │ session metadata only           │
├──────────────────────────┼─────────────────────────────┼─────────────────────────────────┤
│ 5. Chat History Export   │ IDOR / Memory Exhaustion    │ Streaming NDJSON/JSON,          │
│                          │ CSV Formula Injection       │ CSV formula prefix escaping     │
├──────────────────────────┼─────────────────────────────┼─────────────────────────────────┤
│ 6. Account Deletion      │ Orphaned Unlinkable Data    │ Cascade purge of unlinked       │
│                          │ Foreign Key Cascade Locks   │ chat_sessions; SET NULL on FKs  │
└──────────────────────────┴─────────────────────────────┴─────────────────────────────────┘
```

##### [HISTORICAL] 1. Avatar Upload (Supabase Storage)
- **Vulnerabilities:**
  - **Stored SVG XSS:** Uploading an `.svg` file containing embedded JavaScript (`<svg onload="alert(1)">`). When rendered directly in another reader's browser or the admin console, the script executes under the application's origin or storage domain.
  - **Storage Path Traversal & Overwrite (IDOR):** Inadequate bucket RLS allowing User A to overwrite `avatars/user-b/avatar.png`.
  - **Decompression Bombs & Storage Exhaustion:** Uncapped image dimensions and file sizes exhausting storage quota or crashing image rendering pipelines.
- **Required Controls:**
  - **Bucket RLS:** Isolate storage paths strictly to the authenticated user ID:
    ```sql
    create policy "Users can upload own avatar"
      on storage.objects for insert to authenticated
      with check (bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text);
    create policy "Users can update own avatar"
      on storage.objects for update to authenticated
      using (bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text);
    create policy "Users can delete own avatar"
      on storage.objects for delete to authenticated
      using (bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text);
    ```
  - **MIME & Format Restrictions:** Restrict accepted formats strictly to raster images (`image/jpeg`, `image/png`, `image/webp`). **Completely reject `image/svg+xml` and `text/html`**.
  - **File Size Cap:** Enforce a strict 2 MB maximum upload limit both in client-side preflight and storage bucket configuration.
  - **Content-Disposition & CSP on Storage:** Ensure the avatar bucket serves images with `Content-Security-Policy: default-src 'none'` or serves downloads via `Content-Disposition: inline` with sanitized headers.

---

##### [HISTORICAL] 2. Self-Service Email Change
- **Vulnerabilities:**
  - **Single-Sided Email Takeover:** If Supabase GoTrue only confirms the *new* address, an attacker with temporary session access (e.g. an unlocked laptop) can initiate an email change to an attacker-controlled inbox and immediately take over the account without the victim receiving a notice or veto link.
  - **Stale Verification Desynchronization:** As identified in [`supabase/migrations/20260816215103_admin_get_user_email_verified.sql`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260816215103_admin_get_user_email_verified.sql), changing email in GoTrue leaves `auth.users.email_confirmed_at` intact while creating an unverified identity row in `auth.identities`.
- **Required Controls:**
  - **Double Confirmation:** Enable "Secure email change" in Supabase GoTrue settings (requiring confirmation from *both* the old and new email addresses before the change commits).
  - **Re-Authentication:** Require the user to re-enter their current password before initiating an email change request.
  - **Rate Limiting:** Enforce a strict rate limit (e.g., 3 requests / hour) on email change initiation endpoints.

---

##### [HISTORICAL] 3. Self-Service Password Change
- **Vulnerabilities:**
  - **Unauthenticated Session Takeover:** Changing a password without verifying the existing password allows any active session (e.g., from XSS or physical access) to lock out the legitimate account owner.
  - **Session Persistence:** Password changes that fail to revoke existing refresh tokens allow compromised sessions on other devices to remain active.
- **Required Controls:**
  - **Sudo Mode / Current Password Verification:** Require `current_password` and verify via GoTrue `signInWithPassword` before calling `updateUser({ password: new_password })`.
  - **Global Session Revocation:** Invalidate all active sessions upon password reset/change.
  - **Password Complexity:** Enforce server-side and database-aligned password entropy rules (minimum 8 characters, upper/lower/digits).

---

##### [HISTORICAL] 4. Active Sessions List & Session Revocation
- **Vulnerabilities:**
  - **Session IDOR:** An endpoint listing active sessions must strictly filter by `auth.uid() = session.user_id`.
  - **Token Leakage:** Exposing raw JWTs or refresh token hashes in the API response.
- **Required Controls:**
  - **Opaque Metadata Only:** Return only non-sensitive session metadata: creation timestamp, last active timestamp, truncated IP address, and User-Agent device description.
  - **Individual & Bulk Revocation:** Allow terminating individual session IDs or "Revoke all other sessions" via GoTrue admin API.

---

##### [HISTORICAL] 5. Chat History Export
- **Vulnerabilities:**
  - **IDOR / Unauthorized Data Exfiltration:** Allowing User A to request session exports for User B's conversation IDs.
  - **Memory Exhaustion (DoS):** Aggregating hundreds of long transcripts with full citation text into a single in-memory JSON object on a single web worker.
  - **CSV Formula Injection:** If exporting to CSV, cell content starting with `=`, `+`, `-`, `@`, `\t`, or `\r` can execute arbitrary commands when opened in Microsoft Excel or Google Sheets.
- **Required Controls:**
  - **Ownership Filtering:** Filter queries strictly by `owner_id = (select auth.uid())`.
  - **Streaming Export:** Stream export output as NDJSON (`application/x-ndjson`) or chunked JSON using Python generators / `Response(stream_with_context(...))` rather than buffering in RAM.
  - **CSV Sanitization:** If CSV export is provided, prepend a single quote `'` or space to any cell starting with `=`, `+`, `-`, `@`, `\t`, or `\r`.
  - **Export Rate Limiting:** Bound export requests to a maximum of 2 requests per 10 minutes per user.

---

##### [HISTORICAL] 6. Account Deletion
- **Vulnerabilities:**
  - **Orphaned Transcripts:** As documented in [`supabase/migrations/20260820131914_chat_session_persistence.sql:38-42`](file:///E:/Documents/AI_Project/SFDA_copilot/supabase/migrations/20260820131914_chat_session_persistence.sql#L38-L42), `public.chat_sessions` deliberately carries **no Foreign Key to `auth.users`** (to prevent accidental mass cascade). If an account is deleted from `auth.users`, its `chat_sessions`, `chat_messages`, and `chat_message_sources` remain orphaned in the database.
  - **Foreign Key Deletion Blocks:** 
    - `public.profiles.disabled_by` references `auth.users(id)` without `ON DELETE SET NULL`.
    - `public.app_settings.updated_by` references `auth.users(id)` without `ON DELETE SET NULL`.  
    Deleting an administrator's account from `auth.users` will raise a Postgres Foreign Key constraint violation (`23503`) and abort.
- **Required Controls:**
  - **Transactional Account Purge RPC:** Implement a dedicated `security definer` RPC (`delete_user_account`) that atomically:
    1. Deletes all `chat_sessions` (and cascaded messages/sources) where `owner_id = auth.uid()`.
    2. Deletes avatar files from Supabase Storage.
    3. Deletes `public.profiles` for `id = auth.uid()`.
    4. Sets `disabled_by = null` where `disabled_by = auth.uid()` on `profiles`.
    5. Sets `updated_by = null` where `updated_by = auth.uid()` on `app_settings`.
    6. Calls `auth.admin.delete_user(auth.uid())`.

---

#### [HISTORICAL] Controls That Must Ship Alongside the Profile Refactor

The following checklist specifies the mandatory security controls for the implementation team:

##### [HISTORICAL] Database & RLS
- [ ] **DB Column Constraints:** Add `CHECK` constraints on `public.profiles` limiting `full_name`, `organization`, and `specialization` to $\le 200$ characters, and `preferences` to $\le 4096$ bytes.
- [ ] **Trigger Hardening:** Update `profiles_guard_privilege_columns` to fire `BEFORE INSERT OR UPDATE` and validate `disabled_at`, `disabled_by`, `disabled_reason`, and `last_seen_at`.
- [ ] **Active Standing in RLS:** Update RLS policies on `chat_sessions` to require `public.is_active_account()` so disabled users cannot read/delete data via PostgREST.
- [ ] **FK Nullification on User Delete:** Add `ON DELETE SET NULL` clauses to `profiles.disabled_by` and `app_settings.updated_by`.

##### [HISTORICAL] Storage & Uploads
- [ ] **Storage Bucket RLS:** Create `avatars` bucket with strict folder ownership RLS (`(storage.foldername(name))[1] = auth.uid()::text`).
- [ ] **MIME Allow-List:** Disallow SVG, HTML, and executables; allow only JPEG, PNG, WebP with magic-byte validation and a 2 MB size cap.

##### [HISTORICAL] Authentication & Sessions
- [ ] **Double-Confirmation on Email Change:** Enable dual-email confirmation in Supabase GoTrue configuration.
- [ ] **Sudo Re-Authentication:** Require current password before modifying password or email.
- [ ] **Session Invalidation on Password Reset:** Invalidate all active refresh tokens on password change.

##### [HISTORICAL] API & Headers
- [ ] **CSP Hardening:** Add explicit `frame-ancestors 'self'` to Content Security Policy.
- [ ] **Export Streaming & Sanitization:** Implement streaming responses for chat export and neutralize CSV formula injection characters (`=`, `+`, `-`, `@`).
- [ ] **Rate Limiting:** Apply dedicated Flask-Limiter limits to email-change (3/hr), password-change (5/hr), and export (2/10min) routes.

<!-- END VERBATIM — Appendix B -->

---

## [HISTORICAL] Appendix C — UX critique — the community's worst and best profile-page practices

**Implementer:** Claude Code CLI · Sonnet (read-only, `plan` mode)
**Dispatched:** 2026-08-22 · **Working tree:** untouched

> Reproduced verbatim, including its opening note about a disabled Write tool and its incorrect description of `route.js` as "this app's hash router" — corrected in §0.4. Its recommendation to keep the modal is scoped to the *current* three fields and names its own trigger to move, which this plan meets. Its argument against splitting the name field was overruled by the owner; see Decision 5.

<!-- BEGIN VERBATIM — Appendix C -->

*(Note: the Write tool is disabled in this session, so I can't produce the plan file the harness expects — but this task is pure read-only research with the final message as the deliverable, so here it is directly.)*

### [HISTORICAL] Profile-page UI/UX: what the design community agrees on, and where our modal stands

Sources drawn on throughout: Nielsen Norman Group usability findings, WCAG 2.2, GOV.UK Design System, Material Design and Apple HIG, *Refactoring UI* (Wathan/Schoger), *Inclusive Components* (Heydon Pickering), and recurring patterns from design-critique communities. Where I'm recalling a principle rather than citing a specific named source, I say so — no invented citations or statistics.

Code read: `web/templates/index.html:268-321`, `web/templates/partials/_sidebar.html`, `static/js/modules/handlers.js:1494-1595,1674-1688`, `static/js/modules/ui.js:818-850`, `static/js/modules/dom.js:190-269`, `static/js/modules/config.js`, `DESIGN.md`, `static/css/tokens.css`, `static/css/components.css:340-384`, `web/i18n/en.yaml:186-192,536-545`, `web/i18n/ar.yaml:122-128,436-445`.

---

#### [HISTORICAL] Part 1 — The worst mistakes

##### [HISTORICAL] Information architecture

**1. Flat field dump with no grouping or hierarchy.**
- *Mistake:* Identity fields (name, organization, specialization) and a system preference (theme) sit in one undifferentiated list with no section headers or visual grouping.
- *Why it happens:* The form grew by appending the next field to the bottom; nobody stepped back to ask which fields are "who you are" versus "how the app behaves."
- *Cost:* The reader can't scan for the one thing they came to change; every field reads as equally important, so nothing is.
- *Fix:* Split into two visually distinct groups (identity / preferences) with a heading or at minimum a divider and spacing break.
- *Severity:* Medium.
- **Ours:** Committed. `index.html:283-310` — three text inputs and a radio group in one `<form>` with no section breaks.

**2. No identity confirmation in the surface itself.**
- *Mistake:* The modal never displays which account is being edited (no email, no avatar, no "You're signed in as...").
- *Why it happens:* The developer already knows `user.id` from the session; it doesn't occur to them the reader might want confirmation.
- *Cost:* On a shared machine — which this codebase already treats as a real threat (`handlers.js:1608`'s comment about a second reader seeing the first one's history) — nothing in the profile modal tells a reader whose profile they're about to overwrite.
- *Fix:* A one-line identity strip at the top of the modal body: email, sourced from the session object already fetched at `handlers.js:1538-1539`.
- *Severity:* High, specifically because this product has already identified shared-machine risk as real elsewhere.
- **Ours:** Committed. `index.html:274-280` shows only the static heading, never the session's email.

**3. Settings (theme) filed under "Profile" (identity) with no distinction.**
- *Mistake:* A device/session preference and durable identity data are asked for in the same form, same visual weight, same save action.
- *Cost:* Conflates "who I am" with "how this looks" — exactly the split GOV.UK and Apple HIG draw (see Part 3).
- *Fix:* See Part 3 recommendation — separate visually now, reconsider ownership later.
- *Severity:* Medium.
- **Ours:** Committed. `index.html:298-310`.

##### [HISTORICAL] Forms & input

**4. No signal for which fields are required versus optional.**
- *Mistake:* None of the three text fields nor the theme radios carry a required marker, an "optional" hint, or `aria-required`.
- *Cost:* A reader can't tell whether leaving organization blank will get flagged on submit.
- *Fix:* State it once plainly ("All fields are optional") rather than per-field asterisks.
- *Severity:* Low today; High the moment any field becomes required without this being added.
- **Ours:** Committed. `index.html:283-296`.

**5. No client-side validation despite an explicit validation opt-out.**
- *Mistake:* The form carries `novalidate` (`index.html:282`) but implements no custom validation to replace it — likely copied from the signup form pattern without its accompanying logic.
- *Cost:* Any server-side constraint is discovered only after a round trip, surfacing as the generic failure in Mistake #10.
- *Fix:* Drop `novalidate` or add real client checks.
- *Severity:* Medium.
- **Ours:** Committed. `index.html:282`.

**6. No `autocomplete` hints on identity fields.**
- *Mistake:* `profile-full-name` has no `autocomplete="name"`; organization/specialization have none.
- *Cost:* Small convenience loss — browser can't autofill from its own stored profile.
- *Fix:* `autocomplete="name"` / `"organization"`.
- *Severity:* Low.
- **Ours:** Committed. `index.html:284-296`.

##### [HISTORICAL] Save & state

**7. No dirty-state tracking; the modal discards silently.**
- *Mistake:* Nothing tracks unsaved edits, and nothing intercepts a close. Bootstrap's default gives dismiss-on-backdrop-click and dismiss-on-Escape for free, and it's easy to never revisit.
- *Cost:* A reader who edits fields and then clicks outside the modal, or hits Escape out of habit, loses the edit with zero warning — one of the best-documented sources of user frustration in form design.
- *Fix:* Track dirtiness; on an attempted dismiss while dirty, block it with a lightweight inline confirm (matching this codebase's own house style — see the inline-delete pattern at `DESIGN.md:327`, not a second modal) or set `data-bs-backdrop="static" data-bs-keyboard="false"` while dirty.
- *Severity:* High — silent data loss is the costliest category here.
- **Ours:** Committed. Confirmed by search: no `dirty`/`unsaved`/`beforeunload` handling anywhere; no `data-bs-backdrop` override on `#profileModal` (`index.html:271`); no `hide.bs.modal` listener anywhere in `static/js`.

**8. Two independent save paths for the same setting, and they can disagree.**
- *Mistake:* Theme has two controls that both "work": the three site-wide `.theme-toggle-btn` instant toggles, and the profile modal's radio pair that only takes effect on submit and persists to Supabase.
- *Cost:* Not hypothetical — `ui.js:836-847`'s own comment says the radio "can diverge" from the live theme "the moment a reader toggles the theme button without saving the profile form." A reader can open the profile modal and see a stale selection that doesn't match the screen they're looking at.
- *Fix:* One source of truth — either the instant toggle writes straight to Supabase and the radio goes away, or the radio drives the toggle and both read the same stored preference. See Part 3.
- *Severity:* High — self-documented as a reproducible inconsistency, not a theoretical risk.
- **Ours:** Committed. `ui.js:832-850`, `_sidebar.html:13-16,134-138`, `handlers.js:1518,1523`.

**9. Phantom loading state — spinner markup exists but nothing ever shows it.**
- *Mistake:* Both the profile and signup submit buttons carry a `spinner-border ... d-none` element (`index.html:254-256,312-313`), but no code anywhere in `static/js` ever removes that `d-none` class (confirmed by exhaustive search).
- *Cost:* During the real network round trip in `handleProfileFormSubmit` (`handlers.js:1494-1533`), the button shows nothing happening — a reader on a slow connection may click Save again or assume the click didn't register.
- *Fix:* Toggle the spinner and disable the button for the duration of the `try` block — five lines, reusing markup that already exists.
- *Severity:* Medium — dead code masquerading as a feature, with a realistic double-submit side effect.
- **Ours:** Committed.

##### [HISTORICAL] Feedback & errors

**10. One generic error banner for a three-field form — no field-level attribution.**
- *Mistake:* Every save failure surfaces as the same string, `runtime.profile.saveFailed`, in one shared `#profile-error` div (`index.html:317`).
- *Why it happens:* Deliberate — `handlers.js:1526-1530`'s comment explains the raw provider error is untranslatable and may leak technical detail.
- *Cost:* A defensible trade-off for the *message text*, but paired with zero field-level distinction: if the server rejects the payload because, say, organization exceeds a column length, the reader can't know which field to shorten.
- *Fix:* Keep the generic top-level message, but add server-side field-level error codes the client maps to a small translated set of per-field hints, without ever surfacing the raw driver error.
- *Severity:* Medium — a reasonable trade-off taken slightly too far.
- **Ours:** Committed, with that caveat.

**11. Success toast has a hard 3-second window with no recall.**
- *Mistake:* `runtime.profile.saved` is shown via the shared toast at `CONFIG.TOAST_DURATION = 3000` (`config.js:11`).
- *Cost:* Mitigated here — the toast is correctly `role="alert" aria-live="assertive"` (`index.html:691`) so screen readers get it regardless of the timer, and the modal itself closes on the same success path (`handlers.js:1525`) as corroborating visual feedback.
- *Fix:* None needed for this specific message; revisit the shared 3000ms constant only if a future toast needs to carry a longer message.
- *Severity:* Low.
- **Ours:** Technically present but effectively mitigated — not a priority.

**12. Silent busy gap between button click and modal appearing.**
- *Mistake:* `handleProfileButtonClick` (`handlers.js:1535-1572`) does an async session check and, on an uncached profile, an async fetch — `.show()` only fires at the very end (`handlers.js:1571`), with nothing indicating "loading" during the gap.
- *Cost:* On a cold session, a reader clicks "Profile" and nothing visibly happens until the network resolves — indistinguishable from a broken button.
- *Fix:* Disable the profile button and/or show the modal immediately in a loading state.
- *Severity:* Medium.
- **Ours:** Committed.

##### [HISTORICAL] Destructive actions

No destructive action exists in this modal today (no delete-account, no session revocation, no export) — so most of this category doesn't apply directly, but its *absence* is worth naming, and the two general mistakes below matter for whatever lands here next.

**13. Confirmation-dialog theatre.**
- *Mistake:* A generic "Are you sure?" modal worded identically regardless of stakes trains readers to click through without reading.
- *Fix:* Match confirmation weight to reversibility. This codebase already gets this right elsewhere — `DESIGN.md:327` describes conversation delete confirming inline, in the row, precisely because a modal for one row would be theatre. Any future account-level destructive action should earn a real interruption (type-to-confirm or a specific sentence), not the same reflexive dialog.
- *Severity:* Critical, if a delete-account lands without this distinction.
- **Ours:** Not committed today — the existing row-delete pattern is the right model to extend.

**14. No undo on anything destructive at the account level.**
- *Mistake:* Irreversible actions offered with only a confirmation, no grace-period undo.
- *Fix:* Reuse the toast's `has-action` undo countdown already built for this app (`DESIGN.md:279`, `CONFIG.UNDO_DURATION = 10000`, `config.js:15`) rather than inventing a bare confirm for the next destructive action.
- *Severity:* Critical, for whichever action lands here first.
- **Ours:** Not applicable today, flagged for the day one is added.

##### [HISTORICAL] Accessibility

**15. Redundant, hand-authored ARIA duplicating Bootstrap's own.**
- *Mistake:* `role="dialog" aria-modal="true"` manually written on `.modal#profileModal` (`index.html:271`) duplicates what Bootstrap 5.3's modal already manages at runtime.
- *Cost:* Harmless while values agree; a maintenance trap if they ever drift.
- *Fix:* Drop the manual attributes, trust Bootstrap's own semantics.
- *Severity:* Low.
- **Ours:** Committed.

**16. Radio group missing `<fieldset>`/`<legend>`.**
- *Mistake:* Theme preference is two `.form-check` radios under a plain `<label class="form-label">` (`index.html:298-310`), not a `<fieldset>`/`<legend>`, and carries no `role="radiogroup"`.
- *Cost:* Depending on screen reader/browser, a reader tabbing between "Light" and "Dark" may not reliably hear "Theme Preference" as group context — WCAG's recommended pattern for radio groups is exactly `fieldset`/`legend` for this reason.
- *Fix:* Wrap the two `.form-check` divs in `<fieldset><legend class="form-label">`.
- *Severity:* Medium.
- **Ours:** Committed.

**17. Native radio targets likely under the WCAG 2.2 minimum target size.**
- *Mistake:* Bootstrap 5.3's default `.form-check-input` renders at `1em` (~16px), and no override exists anywhere in `components.css` (confirmed by search).
- *Cost:* Below WCAG 2.2's Target Size (Minimum) AA criterion (24×24 CSS px) and well under Apple HIG/Material comfortable-touch guidance.
- *Fix:* Increase `.form-check-input` to ≥24×24px via a semantic-token override, or make the whole `.form-check` row the clickable target.
- *Severity:* Medium — a real, citable WCAG 2.2 gap.
- **Ours:** Committed (unverified in a live browser, but no CSS exists that would prevent it).

##### [HISTORICAL] Identity & personalization

**18. No avatar, no initials fallback, no visual identity at all.**
- *Mistake:* `_sidebar.html:113-141`'s account block is text-only.
- *Cost:* Low on its own, but it means Mistake #2 (no identity confirmation) has no cheap visual fix available.
- *Fix:* See Part 3 — generated initials.
- *Severity:* Low, but compounds #2.
- **Ours:** Committed by omission.

**19. Single free-text name field — correctly avoids the Western-name-shape trap.** *(Positive, stated because getting this right is rarer than getting it wrong.)* `profile-full-name` (`index.html:284-286`) is one field, not split first/last — correct for a bilingual product where name shapes genuinely differ. No pronoun field, no gendered copy anywhere in `page.profile.*` (`en.yaml:536-545`, `ar.yaml:436-445`). Protect this property explicitly in any redesign — don't split the name field.

##### [HISTORICAL] Privacy & trust

**20. No visible data-control surface at all.**
- *Mistake:* No way to see or export stored data, no account deletion, no link to a privacy policy.
- *Cost:* For a product already conscious of shared-machine and session-persistence risk elsewhere, the absence of a reader-facing "what do you have on me, and how do I leave" control is a trust gap, not just a feature gap.
- *Fix:* At minimum, a link out to a stated data/privacy policy; self-serve export/delete is a larger, separately-tracked project.
- *Severity:* Medium today, rising with adoption.
- **Ours:** Committed by omission.

**21. No dark pattern present — stated plainly for completeness.** No pre-ticked opt-ins, no confirm-shaming, no forced continuity. Theme radios reflect the reader's actual last saved choice (`ui.js:845-849`); the save button reads a plain "Save Changes" (`en.yaml:545`). This surface earns no entry in the mistakes list here.

##### [HISTORICAL] Visual & layout

**22. Every field the same visual weight.**
- *Mistake:* Three identical `form-floating` inputs followed by a same-weight radio group — nothing signals which field matters most.
- *Cost:* Refactoring UI's core argument applies directly: a form where everything looks equally important tells the reader nothing about what to prioritize.
- *Fix:* Larger/bolder treatment or top placement for whichever field is most consequential.
- *Severity:* Low, but cheap to fix alongside #1.
- **Ours:** Committed.

##### [HISTORICAL] Mobile & responsive

**23. Untested claim, flagged rather than asserted.** `#profileModal` uses `.modal-dialog-centered` with no `.modal-fullscreen-sm-down`. For a three-field form this is unlikely to be a real trap, unlike a long settings page — I did not verify this in a mobile viewport, so I'm naming a risk to check, not a confirmed defect.

##### [HISTORICAL] i18n & RTL

See Part 4 for the full treatment. Summary: **this modal does not currently trigger either of the two known codebase-wide RTL traps.**

---

#### [HISTORICAL] Part 2 — Best practices

**The save model that actually works.** Explicit save is right for this form — three unrelated fields plus a preference, edited in a burst and left alone. Autosave-on-blur is right for a *single* field edited in isolation with instant feedback (a display-name row on its own settings line) — it fails exactly where this form lives, because autosaving field 1 while the reader is still typing field 3 either fires redundant requests or leaves them unsure what "saved" covers. This form's real problem isn't the choice of explicit save — it's explicit save with no dirty-tracking and a dismissible-by-default modal (Mistake #7), which gets the worst of both worlds.

**The dangerous section, done well.** GOV.UK's and Material's converged pattern: destructive actions live in their own visually distinct area, each confirmation calibrated to actual reversibility, and anything genuinely destructive gets a grace-period undo rather than only a confirm. This codebase already has both pieces built for a different surface — inline row-delete confirmation and the toast undo countdown (`DESIGN.md:279,327`) — reuse those, don't invent a third pattern.

**Progressive disclosure that doesn't become hide-and-seek.** The test: can the reader find the thing by scanning, or do they have to remember it's there? This codebase's own source-panel disclosure (`DESIGN.md:163-165`, collapsed "ranking diagnostics," named for exactly what it is, one click away) is a good model of the honest version.

**Empty, loading, error, offline states.** The conversation-list component already states the principle for a different surface (`DESIGN.md:328`): three visually distinct states — loading / empty / unavailable-with-retry — because collapsing empty and unavailable tells the reader "you have nothing" when the truth is "we couldn't check." The profile form has none of these distinctly implemented (Mistakes #9, #12); bring the same discipline already proven elsewhere in this codebase here.

**What belongs in a profile versus settings.** Profile is *about the reader* (durable identity — name, organization, role); settings is *about the software* (theme, notifications, language). Theme sits closest to the line, which is why it's the first item in Part 3.

---

#### [HISTORICAL] Part 3 — Contested ground

**Modal vs. dedicated page vs. tabbed settings.**
- *A (modal):* preserves the reader's context; right for a short form.
- *B (dedicated page):* room to grow without an overloaded modal; supports deep-linking.
- *Recommendation:* Keep the modal at the current scope — it's genuinely short and context-preservation wins here. Move to a dedicated `#/settings` route (this app's hash router, `route.js`, already supports this) the day this surface gains a genuinely separate concern — account deletion, export, a session list — not before.

**Autosave vs. explicit save.**
- *Recommendation:* Explicit save, as now, paired with the dirty-state guard from Mistake #7. That combination beats both pure autosave and the current unguarded explicit save.

**Avatar upload vs. generated initials.**
- *Recommendation:* Generated initials, not upload. This is a professional regulatory tool where people identify by organization and specialization, not a social product where a photo carries social signal — upload's moderation/storage cost buys little here. An initials badge derived from `full_name` (already collected) would close Mistake #2's identity-confirmation gap at effectively no engineering cost.

**Whether theme preference belongs in a profile at all.**
- *Recommendation:* Given this codebase demonstrably has two disagreeing implementations of the same setting today (Mistake #8), remove the theme radio from the profile form and let the instant toggle write straight to the stored preference on every toggle. The instant toggle is the better UX (immediate feedback, no modal) and doesn't need a form it can't stay in sync with — this also resolves IA Mistake #3 for free.

**Whether "Danger Zone" as a pattern helps or decorates.**
- *Recommendation:* The label and visual separation help; the red-border theatre alone does not. What actually protects the reader is the confirmation/undo mechanics behind the button (#13, #14), not the section's paint job. This codebase's own stated restraint — "the system has no danger variant" for most controls, red reserved for genuine severity (`DESIGN.md:278`) — is the better model than importing a generic red-bordered card.

**Progressive disclosure vs. showing everything.**
- *Recommendation:* Show everything at the current three-field scope — disclosure would be over-engineering. Disclose only once a dangerous section or sessions list is added, behind a named, one-click-away control matching the ranking-diagnostics pattern already in this codebase.

---

#### [HISTORICAL] Part 4 — RTL & bilingual failure modes

Checked one by one against this surface:

- **Mirrored vs. non-mirrored icons.** The form's icons (`user`, `building`, `briefcase`, `palette`, `user-circle`) are all symmetric — none need mirroring, none are mirrored. Not an issue here.
- **`text-align: start` traps.** No physical `text-align` literal in this surface's styling (`components.css:340-384` uses logical properties and flex `gap` only), enforced globally by `test_css_contract.py` (`DESIGN.md:244,382`). Not an issue here.
- **Bidi-neutral characters in names/emails.** `#profile-full-name` has no `dir="auto"` (`index.html:284-286`) — unlike conversation-list titles, which explicitly carry `dir="auto"` because reader-typed strings mix scripts (`DESIGN.md:325`). A name field is the same category of input and currently lacks the same handling.
  - **Gap, ours:** `index.html:284-296` — no `dir="auto"` on any of the three text inputs. Cheap fix given the rule is already documented and applied elsewhere (`DESIGN.md:325,376`).
- **Dates/numbers inside RTL text.** No dates or numbers in this field set today — not applicable, but relevant the day a timestamp or numeric field is added; reuse the existing rule (`DESIGN.md:234`: `direction: ltr; unicode-bidi: isolate`, tabular-nums), don't invent a new one.
- **Form-floating labels.** Bootstrap 5.3's `form-floating` uses logical positioning by default; the one local override (`components.css:375-381`) only adds `display:flex` for the icon, doesn't touch positioning. Not visually verified in an RTL session — flagged unverified, not asserted broken.
- **Sticky bars / keyboard-eating footers.** Not present in this modal — not applicable.
- **Focus order.** Bootstrap manages the modal's focus trap and return automatically; DOM order matches visual order in both directions since nothing here uses absolute positioning to reorder. No issue found.
- **Mixed-direction content in a single field.** Same root cause as the bidi-neutral-names point — `dir="auto"` is the fix, currently missing.

**The two known codebase traps, checked directly:**
- *(a) Blanket `[dir=rtl] *` letter-spacing reset losing to hardcoded tracking (`tokens.css:281-282`, [[rtl-letter-spacing-reset-is-not-a-safety-net]]):* **Does not apply here.** Every `letter-spacing` in all five stylesheets — including the modal title at `components.css:352` — is `var(--track-*)`, never a literal (confirmed by exhaustive search). Since the token itself zeroes under `[dir="rtl"]` (`tokens.css:270-272`), the blanket reset is redundant here, not needed. Worth stating plainly: the memory flags a real codebase-wide risk this specific surface happens not to trigger.
- *(b) `dir="ltr"` on a block box flipping `text-align: start` ([[dir-ltr-on-a-block-box-flips-text-align-start]]):* **Does not apply here.** No machine values, no `dir="ltr"` isolation spans anywhere in this modal. Will become relevant the day a timestamp or numeric field is added — at that point isolate an inline element, not a block one, per that memory's finding.

---

#### [HISTORICAL] Part 5 — Verdict on our current profile modal

Ranked worst first:

1. **Silent, unguarded data loss on close** (`index.html:271`, no dirty-tracking anywhere) — the costliest defect: a reader can lose typed edits to a backdrop click or Escape with zero warning.
2. **Two theme controls that can disagree, self-documented as a known divergence** (`ui.js:836-849`, `handlers.js:1518-1523`, `_sidebar.html:13-16,134-138`) — not hypothetical, the code comments describe it directly.
3. **Dead spinner markup — no loading feedback during save** (`index.html:312-313`, confirmed unused in `static/js`) — cheap to fix, currently a broken promise in the DOM.
4. **No identity confirmation in the modal** (`index.html:274-280`) — compounds the shared-machine risk this codebase already takes seriously elsewhere.
5. **Generic error message with no field attribution** (`handlers.js:1526-1531`, `index.html:317`) — a defensible trade-off taken slightly too far.
6. **Radio group missing `<fieldset>`/`<legend>`** (`index.html:298-310`).
7. **Likely sub-24px radio targets** (no `.form-check-input` override in `components.css`) — unverified live, but nothing prevents it.
8. **No required/optional signaling, no client validation despite `novalidate`** (`index.html:282-296`).
9. **No `dir="auto"` on reader-typed name/organization/specialization fields** (`index.html:284-296`) — this exact problem is already solved elsewhere in this codebase (`DESIGN.md:325`) and wasn't carried here.
10. **Flat IA, no visual hierarchy, no avatar/initials** (`index.html:283-310`, `_sidebar.html:113-141`) — cosmetic relative to the above, but the cheapest fix (initials badge) would also resolve #4.

**If I could only change three things, in order:**

1. **Guard the close.** Add dirty-tracking; block backdrop/Escape dismissal while dirty, or add an inline "discard changes?" confirm matching this codebase's own style. The only item here causing actual, irreversible data loss.
2. **Collapse the theme setting to one source of truth.** Remove the profile-form radio (or make the instant toggle write straight to Supabase) so `ui.js:836-847`'s documented divergence becomes structurally impossible.
3. **Wire the spinner and add an identity line.** Two small, independent fixes addressing "the reader doesn't know what's happening": toggle the existing spinner markup during save, and show which account is being edited, reusing the session object already fetched in `handleProfileButtonClick`.

<!-- END VERBATIM — Appendix C -->

---

---

## [HISTORICAL] Appendix D — Adversarial debate of this plan

**Implementer:** OpenCode CLI · `openai/gpt-5.6-terra`, reasoning effort **xhigh**, `plan` agent (read-only)
**Dispatched:** 2026-08-23 · **Working tree:** untouched

> Reproduced verbatim. This pass was briefed to attack the plan rather than summarise it, and it
> succeeded: its findings 1, 2, 4, 6, 7, 8 and 16 are carried into §14, and finding 16 falsified a
> claim §14·A·1 now corrects. Where §14 disagrees with this appendix, §14 is the decision — several
> findings here were re-verified against source and partially upheld rather than adopted whole.

<!-- BEGIN VERBATIM — Appendix D -->

**Part 1 - Findings**

1. **Critical - S3's three-migration identity cutover creates an outage.** **What breaks:** the companion orders generated `full_name` before updating `handle_new_user` and `admin_update_profile`. Both still write `full_name`, as does every already-open chat tab. A generated column rejects those writes, so signups can roll back and profile/admin saves fail during the deployment window. The displayed generated-column definition also omits `full_name text`. **Evidence:** `docs/profile-refactor-plan.md:575-587`, `supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql:58-67`, `static/js/modules/handlers.js:1514-1521`, `supabase/migrations/20260814200342_admin_update_profile.sql:76-80`. **Instead:** make the destructive migration an atomic compatibility cutover for trigger, grants, admin RPC, and deployed client; retain a bounded old-client window or use a transitional non-generated column/trigger. Test signup and both write paths against the live migration before converting the column.

2. **Critical - S5 has no path to persist consent or age at signup.** **What breaks:** signup goes directly from browser to GoTrue, does not establish a session, and `handle_new_user` is the only server-side path that creates the profile. S5 says to add a checkbox and age field, but does not say to extend the GoTrue metadata payload and `handle_new_user` to accept, validate, and atomically persist `marketing_consent` and age. Adding client grants cannot help an unconfirmed reader who has no session. **Evidence:** `static/js/modules/services.js:329-333`, `static/js/modules/handlers.js:170-174`, `supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql:51-67`. **Instead:** either defer marketing consent and age until the first authenticated session, preferably through a server endpoint, or explicitly implement a validated metadata-to-profile trigger path and cover it with real GoTrue integration tests.

3. **High - The proposed consent record destroys the evidence it claims to preserve.** **What breaks:** a single `marketing_consent_at` updated on both `false -> true` and `true -> false` becomes “last state changed,” not “consent was granted.” It loses the original grant time on withdrawal. A browser-direct write also proves only that a valid JWT sent a boolean, not which disclosure, language, policy version, or collection surface was accepted. **Evidence:** profile writes are browser-direct upserts at `static/js/modules/services.js:677-683`; the existing profile grant model intentionally permits reader-owned columns at `supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql:139-151`. **Instead:** record immutable consent events or at minimum `marketing_consent_granted_at`, `marketing_consent_withdrawn_at`, policy/version, language, source surface, and the exact purpose. Do not rate-limit withdrawal; if grant events need abuse control, enforce it server-side.

4. **High - The plan collects marketing data before identity verification, then offers no way to control it.** **What breaks:** `handle_new_user` creates `profiles` when `auth.users` is created, while the plan correctly notes that signup does not sign the reader in. An unconfirmed typo or abandoned account can therefore retain age and consent metadata indefinitely, without the person being able to withdraw, view, or delete it. **Evidence:** `supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql:48-67`, `static/js/modules/handlers.js:170-174`. **Instead:** collect only account-creation necessities pre-confirmation. Ask for marketing consent and age after confirmed sign-in, define expiration/purge for unconfirmed accounts, and document a recovery/deletion path.

5. **High - S5 is sequenced before the document that its own rationale says it requires.** **What breaks:** D3 says policy acceptance must ship with a readable bilingual document; S5 says its value depends on that nonexistent document, then defers D3 until after S5. This makes marketing processing live before its stated disclosure/terms dependency exists. **Evidence:** the current reader shell has only the auth/profile surfaces, not a policy link or legal page: `web/templates/index.html:127-321`; current reader-facing routes are `/` and `/c/<uuid>`: `web/api/app.py:1833-1878`. **Instead:** block marketing collection on approved bilingual legal copy and a retention decision. Do not treat a future policy-version column as a substitute for the version accepted now.

6. **High - D6 rests on a false taxonomy mapping and discards real profile data.** **What breaks:** the four audience groups are not the four corpus categories. Clinical-trial sponsors map to Regulatory in the FAQ, while pharmaceutical companies span categories; Veterinary and Biological are product domains, not universal job specializations. A reader with cross-category work gets a narrower, potentially worse default than “All Categories.” The proposed normalization would also erase existing free text such as `"Regulatory Affairs"` rather than preserve it. **Evidence:** audiences are listed at `docs/PRODUCT.md:11-20`; categories are corpus scopes at `docs/PRODUCT.md:68-69`; clinical trials appear under Regulatory at `faq.yaml:17-29`; the current fixture already contains `"Regulatory Affairs"` at `web/tests/conftest.py:48-54`. **Instead:** model this as an explicit, reversible search preference, not `specialization`. Default to `all`; offer an optional single preferred category only if research supports it, and let per-device last-used scope win for subsequent searches. Preserve old specialization separately or retain it until a reader consciously replaces it.

7. **High - A late profile read can silently change search scope after the reader has started working.** **What breaks:** profile loading is fire-and-forget after auth rendering. A reader can type or submit a question while the category remains `all`; a late specialization then changes the next query's scope without a deliberate choice. `readerChose` protects only explicit listbox selection, not “the reader has begun a query/session.” **Evidence:** `static/js/app.js:388-409`; dropdown initialization only exposes a closure-local `select()` today at `static/js/modules/dropdown.js:60-82`; the selected hidden value is what the UI maintains at `static/js/modules/dropdown.js:72-80`. **Instead:** apply an account default only before the first query interaction for that identity. After typing, sending, or focusing with content, keep `all` until the reader selects scope. If automatic narrowing occurs, make it visibly and accessibly explicit; mutating `aria-label` is not an announcement (`static/js/modules/dropdown.js:67-70`, `static/js/modules/ui.js:762-773`).

8. **High - The history-notice arbitration makes the completion strip disappear for its target cohort.** **What breaks:** history notice is rendered synchronously before profile loading. If completion returns early because `#history-notice` exists, dismissal merely removes the node and writes localStorage; it emits no event that reruns completion logic. The reader must reload or receive a future auth event before the strip gets another chance. **Evidence:** `static/js/app.js:163-170`, `static/js/app.js:405-409`, `static/js/modules/ui.js:714-759`. **Instead:** queue the completion prompt for that identity, and show it from the history-dismiss handler or a dedicated notice coordinator. Do not model two independent notices as competing DOM inspections.

9. **High - “`first_name` required” is only a cosmetic browser rule, and its justification is circular.** **What breaks:** the proposed schema keeps name columns nullable for existing accounts, and raw GoTrue/API clients can omit metadata. There is no existing `first_name` reader; current code reads `full_name`. The monogram is a future companion feature, so it cannot justify signup friction as an existing product dependency. **Evidence:** proposed nullable columns at `docs/profile-refactor-plan.md:306-310`; current profile read at `static/js/modules/services.js:665-675`; current admin detail reads `full_name` at `supabase/migrations/20260814175551_account_detail.sql:31-59`. **Instead:** describe the field as required by this browser form only unless the server enforces it. Validate metadata server-side, retain a clear legacy/null state, and justify collection with an implemented reader benefit rather than an unbuilt monogram.

10. **Medium - S2 is misclassified as a prerequisite for D4 and D6.** **What breaks:** current upsert replaces only supplied top-level columns. It clobbers `preferences` because that one column is a JSON object, but it does not erase omitted `marketing_consent` or `specialization` columns. Calling it a hard dependency adds delay without protecting those fields. **Evidence:** `static/js/modules/services.js:677-683`, `static/js/modules/handlers.js:1514-1521`. **Instead:** keep the preferences merge RPC as its own important fix, but state accurately that it is required for future JSON preferences, not for these top-level columns. Specify the RPC's `auth.uid()` target binding, allowed patch keys/type, `authenticated` grant, and revoked `PUBLIC` access before introducing a `SECURITY DEFINER` write path.

11. **Medium - The `/account` dependency is not deployable as the companion currently describes it.** **What breaks:** adding `static/js/account/` filenames to the existing modules tuple cannot generate URLs for a sibling directory. The account page needs a third filename map and must merge shared plus account imports, just as admin merges shared plus admin imports. **Evidence:** `docs/profile-refactor-plan.md:506-510`, `web/api/app.py:249-262`, `web/api/admin.py:101-121`. **Instead:** make the account shell/import map work before making the completion strip route there.

12. **Medium - The plan omits the actual data-rights consequences of consent.** **What breaks:** the admin surface neither returns nor displays consent data, and the planned expansion of profile audit data can make age survive account deletion in append-only audit rows. Readers have no specified way to inspect the consent record, policy version, or withdrawal history. **Evidence:** admin detail returns only name/organization/specialization at `supabase/migrations/20260814175551_account_detail.sql:31-61`; its editable fields mirror that at `static/js/admin/ui.js:1114-1121`; audit rows are deliberately append-only at `supabase/migrations/20260814032447_audit_log.sql:20-73`. **Instead:** define whether consent events are retained on account deletion, exclude marketing demographics from general admin profile audit diffs unless necessary, expose a read-only consent record to the subject and administrators, and include it in export.

13. **Medium - The account-deletion plan inherited from the companion is not transactional.** **What breaks:** PostgreSQL purge and GoTrue deletion cannot be one transaction. Failure between them can leave an active auth identity with a purged profile/history, or a partially deleted account with no recovery state. **Evidence:** `docs/profile-refactor-plan.md:601-604`; the code explicitly recognizes that outbound provider calls cannot share a database transaction at `web/api/admin.py:329-339`. **Instead:** design an idempotent deletion saga with durable pending/deleted states, retry/reconciliation, sign-out/revocation sequencing, and a truthful retention statement.

14. **Medium - The `?testing=true` path cannot prove D5/D6.** **What breaks:** testing mode bypasses auth-state registration and returns before profile loading. The mock signup also ignores metadata. The plan exempts the strip from testing, but then has no shipping-demo coverage for profile defaults or signup capture. **Evidence:** `static/js/app.js:267-279`, `static/js/app.js:338-351`, `web/tests/conftest.py:96-100`. **Instead:** add an explicit test/demo profile fixture and test identity-scoped default behavior, while keeping the completion prompt hidden in demo mode if that is the desired product behavior.

15. **Medium - The verification plan measures code paths, not whether the product decision works.** **What breaks:** there is no baseline or event definition for signup abandonment, confirmation completion, consent acceptance/withdrawal, profile completion, category override, or scoped-search success. “The single most important conversion defect” and “majority never open `/account`” are unsupported assertions. The product explicitly has no user counts or similar evidence. **Evidence:** `docs/PRODUCT.md:158-160`. **Instead:** define privacy-safe aggregate metrics and success/failure thresholds before adding funnel friction; add migration rollback criteria for D6's destructive normalization and a support runbook for unconfirmed accounts.

16. **Low - Several factual claims are overstated or false.** **What breaks:** the plan says organization has only one reader and specialization has none, but both are read to populate the reader profile form and are returned to the admin detail/edit path. It also says missing Arabic `page.*` keys render raw keys; Arabic catalogues are deep-merged with English, so they render English fallback unless absent from both catalogues. “All accounts ever had null metadata” cannot be established from a trigger that merely reads metadata. **Evidence:** `static/js/modules/ui.js:818-833`, `supabase/migrations/20260814175551_account_detail.sql:56-59`, `web/utils/i18n.py:28-59`, `web/tests/test_rtl.py:201-212`, `supabase/migrations/20260814005509_lock_profile_privileges_and_repair_signup.sql:58-66`. **Instead:** say “no downstream product decision currently uses these fields,” retain the page-parity test proposal, and remove historical-data claims that have not been queried.

17. **Low - The RTL guidance contradicts itself.** **What breaks:** T6 correctly identifies the LTR Bootstrap stylesheet and physical `.form-check` behavior, while §7 later says Bootstrap positions it logically. Both cannot be true. The local CSS contract scans only repository CSS, not the CDN stylesheet or actual rendered layout. **Evidence:** `web/templates/index.html:31-37`, `web/tests/test_css_contract.py:24-95`. **Instead:** use a bespoke logical `.consent-row`, test Arabic at mobile widths, and do not claim the CSS contract validates Bootstrap RTL behavior.

**Part 2 - Surface And Motion Direction**

Use one rule: **local surfaces change elevation; document navigation changes context.** Dropdowns, modals, sheets, and offcanvas panels may use a short opacity/transform transition from their trigger. A full page must not pretend to be a larger popup. Do not use left/right travel for general navigation; it has no stable semantic meaning in RTL.

The existing system supports this direction: motion tokens are already defined in `static/css/tokens.css:143-158`; `effects.css` restricts motion to state changes at `static/css/effects.css:1-11`; reduced motion globally collapses CSS transitions at `static/css/base.css:347-354`. Reuse those, not `AuthView`'s mascot-coupled delayed fade (`static/js/modules/auth-view.js:62-79`).

1. **Chat to account:** make the account-menu item a normal `<a href="/account">`. On every browser it is an understandable document navigation, preserves Back, and needs no JavaScript interception. The account page should focus its `<h1>` on arrival only for an explicit in-page action, not for ordinary navigation.

2. **Shared element:** the meaningful shared element is the future account-menu identity cluster: monogram plus name/email, becoming the account record header. Do not animate the whole sidebar or decorative logo. The sidebar is rendered twice, desktop and offcanvas, so only the currently displayed instance may receive `view-transition-name: account-identity`; otherwise duplicate names are unsafe. **Evidence:** `web/templates/partials/_sidebar.html:1-4`, `web/templates/partials/_sidebar.html:113-141`.

3. **Cross-document View Transitions:** treat `@view-transition { navigation: auto; }` as progressive enhancement, not the primary solution. It requires same-origin current and destination documents, is opt-in on both, and MDN currently labels it “Limited availability.” It can produce a brief root fade plus a monogram/email morph where supported; unsupported browsers receive the normal navigation. Do not enable it globally on the reader shell without deciding whether `/` to `/c/<uuid>` should also snapshot and animate a possibly sensitive transcript. [MDN: `@view-transition`](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@view-transition).

```css
/* Shared only by documents deliberately opting into this navigation. */
@view-transition { navigation: auto; }

.account-identity { view-transition-name: account-identity; }

::view-transition-old(root) {
  animation: account-out var(--duration-s) var(--ease-soft) both;
}
::view-transition-new(root) {
  animation: account-in var(--duration-s) var(--ease-soft) both;
}

@media (prefers-reduced-motion: reduce) {
  ::view-transition-group(*),
  ::view-transition-old(*),
  ::view-transition-new(*) { animation: none !important; }
}
```

4. **Account menu, category dropdown, source panel, offcanvas:** do not invent a unified “page transition” animation for them. They are temporary elevated surfaces. Use Bootstrap's existing modal/dropdown/offcanvas lifecycle where available; the reader shell already loads Bootstrap's bundle at `web/templates/index.html:693-697`. Keep the category control's immediate selection behavior because it updates hidden form state and ARIA together at `static/js/modules/dropdown.js:60-82`. Respect the design system's one-drawer rule for mobile at `DESIGN.md:305`.

5. **Signup to confirmation:** keep the modal shell, tab strip, and heading stable. Replace the signup form with confirmation in the same content region, moving the outgoing fields a few pixels toward block-start and bringing the status panel from block-end. This reads as “form submitted, now confirm,” not two surfaces flickering. Manage focus to the confirmation heading and use `role="status"`. Include a real “use a different email” recovery path; merely echoing a typo does not make it fixable.

6. **Age reveal without JS measurement:** toggle a wrapper from `grid-template-rows: 0fr` to `1fr`; its child uses `min-block-size: 0; overflow: clip`. Toggle the input's `disabled` state in the same checkbox handler, so a concealed age cannot reach `FormData`. Start after the checkbox click has completed, not on pointer-down. The submit button will move below the reveal, but not under the finger that activated the checkbox.

```css
.age-reveal {
  display: grid;
  grid-template-rows: 0fr;
  opacity: 0;
  transition: grid-template-rows var(--duration-m) var(--ease-soft),
              opacity var(--duration-s) var(--ease-soft);
}
.age-reveal > div { min-block-size: 0; overflow: clip; }
.signup-form[data-marketing-consent="true"] .age-reveal {
  grid-template-rows: 1fr;
  opacity: 1;
}
```

7. **Completion strip:** insert it synchronously after the chat intro, then give only that new node a one-time `opacity` plus small block-axis entrance. Do not use `document.startViewTransition()` for transcript insertion: this codebase deliberately removed that because deferred DOM work broke downstream layout/scroll behavior. **Evidence:** `static/js/modules/ui.js:198-205`. Never auto-scroll to the strip, never replay it on reload, and do not animate its removal on dismissal.

8. **Refuse motion:** do not animate validation errors, consent withdrawal, destructive confirmations, recovery/expired-link state, server outages, or streamed transcript content. Do not make a full-page account load “enter” on refresh or a deep link. These states need clarity and stable focus, not choreography.

<!-- END VERBATIM — Appendix D -->

---

## [HISTORICAL] Appendix E — Migration SQL specs

**Implementer:** OpenCode CLI · `openai/gpt-5.6-sol`, reasoning effort **xhigh**, `plan` agent (read-only)
**Dispatched:** 2026-08-23 · **Working tree:** untouched

> Reproduced verbatim. Briefed with §15's verified live state, so its SQL is written against the
> real four-row table rather than against the migration files. Its decisions are summarised in §16;
> where the two differ, §16 is the decision. Note it improved on this document twice: the verbatim
> name-preservation strategy (§15.2) and dropping `profiles_full_name_len_chk` entirely rather
> than merely at conversion time (§16·1).

<!-- BEGIN VERBATIM — Appendix E -->

I’ll inspect the governing migrations, current function definitions, grants/RLS patterns, and deletion-related schema before drafting SQL. I’ll keep the workspace strictly read-only and use the verified live-state facts as authoritative where migration history differs.The repository’s earlier plan already fixes the intended bounds at 100 characters per name and ages 13–120, but its three-migration cutover is unsafe against the writers the user identified. I’m treating the live four-row dataset as a manual data-mapping case, not accepting the earlier token-splitting proposal.**Spec 1: Atomic Identity Cutover**
This must be one migration. The generated-column conversion, database writers, function ACLs, and profile column ACLs are one indivisible concern. Splitting them would break signup and both profile-save paths, as shown by `20260814005509...:58-67`, `20260814200342...:76-80`, and `handlers.js:1514-1521`.

Before approval, record the output of these read-only checks in the migration header. The body of baseline-only `handle_profile_update()` is not in the repository, so it must be inspected rather than assumed.

```sql
select pg_get_functiondef('public.handle_profile_update()'::regprocedure);

select indexname, indexdef
  from pg_indexes
 where schemaname = 'public'
   and tablename = 'profiles'
   and indexdef ilike '%full_name%';

select count(*) as profile_rows,
       count(full_name) as nonnull_full_names,
       max(char_length(full_name)) as max_full_name_length
  from public.profiles;
```

The verified data rules out `split_part`. Treating `Dr.` as a given name would be knowingly wrong, while interpreting `Mohammed Exam Tomorrow` also requires human knowledge. The safe migration preserves each legacy display name verbatim in `first_name`, leaves `family_name` unknown, and proves that the generated value is identical before dropping the source column. The three named rows can then be corrected manually by the subjects or an operator.

`profiles_full_name_len_chk` should not exist. Two independently valid 100-character names produce a 201-character generated name. A 200-character check would reject valid base data, while a 201-character check would merely repeat what the base-column checks already prove.

```sql
-- Replace public.profiles.full_name with a stored generated display name and
-- move every database writer and privilege in the same atomic cutover.
--
-- WHY THIS CANNOT BE SPLIT
-- ------------------------
-- public.handle_new_user writes full_name
-- (20260814005509_lock_profile_privileges_and_repair_signup.sql:58-67),
-- public.admin_update_profile writes it
-- (20260814200342_admin_update_profile.sql:76-80), and the shipped browser
-- includes it in an upsert payload (static/js/modules/handlers.js:1514-1521).
-- A generated column rejects all three writes.
--
-- DESTRUCTIVE-CHECK RECORD, 2026-08-23
-- ------------------------------------
-- Verified live before writing this migration:
--   * public.profiles has 4 rows and auth.users has 4 rows.
--   * No auth user lacks a profile.
--   * 3 full_name values are non-null; the maximum length is 22.
--   * 2 of the 3 names begin with "Dr.", so token splitting was rejected.
--   * profiles_full_name_len_chk and every other name-length check are absent.
--   * The only profile triggers are on_profile_update and
--     profiles_guard_privilege_columns, both BEFORE UPDATE.
--   * The application grep found the database writers named above and the
--     browser writer at handlers.js:1514-1521.
-- Record the apply-time index and handle_profile_update() checks immediately
-- above this comment before approving the migration.
--
-- No explicit BEGIN/COMMIT: the migration runner wraps this file in its own
-- transaction. This follows the warning at
-- 20260814005509_lock_profile_privileges_and_repair_signup.sql:35-43.
-- If pasted into the SQL editor, wrap the entire file in one transaction.

-- ---------------------------------------------------------------------------
-- 1. Add the writable identity components.
-- ---------------------------------------------------------------------------
alter table public.profiles
  add column first_name  text,
  add column family_name text,
  add column age         smallint;

-- Preserve legacy display names without pretending that titles and multi-token
-- names can be decomposed mechanically. The generated value remains byte-for-
-- byte equal; family_name remains explicitly unknown.
update public.profiles
   set first_name = full_name,
       family_name = null
 where full_name is not null;

-- Names are normalised at the storage boundary. NULL means unknown; an empty or
-- whitespace-only string does not become a second spelling of unknown.
alter table public.profiles
  add constraint profiles_first_name_chk
    check (
      first_name is null
      or (
        first_name = btrim(first_name)
        and char_length(first_name) between 1 and 100
      )
    ),
  add constraint profiles_family_name_chk
    check (
      family_name is null
      or (
        family_name = btrim(family_name)
        and char_length(family_name) between 1 and 100
      )
    ),
  add constraint profiles_age_chk
    check (age is null or age between 13 and 120);

-- Abort before the destructive statement if the conservative backfill failed
-- to preserve even one legacy display value.
do $$
begin
  if exists (
    select 1
      from public.profiles p
     where p.full_name is distinct from
       case
         when p.first_name is null and p.family_name is null then null::text
         when p.first_name is null then p.family_name
         when p.family_name is null then p.first_name
         else p.first_name || ' ' || p.family_name
       end
  ) then
    raise exception 'identity backfill does not preserve every full_name';
  end if;
end
$$;

-- ---------------------------------------------------------------------------
-- 2. Signup writer: stop naming full_name before it becomes generated.
-- ---------------------------------------------------------------------------
-- pg_input_is_valid() prevents malformed and out-of-range integer input from
-- ever reaching a cast. A bad metadata value degrades to NULL rather than
-- rolling back auth.users creation, the failure warned about at
-- 20260814005509_lock_profile_privileges_and_repair_signup.sql:48-50.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_meta        jsonb := coalesce(new.raw_user_meta_data, '{}'::jsonb);
  v_age_text    text;
  v_age         integer;
  v_first_name  text;
  v_family_name text;
begin
  v_first_name :=
    nullif(left(btrim(v_meta ->> 'first_name'), 100), '');
  v_family_name :=
    nullif(left(btrim(v_meta ->> 'family_name'), 100), '');

  v_age_text := v_meta ->> 'age';
  if pg_catalog.pg_input_is_valid(v_age_text, 'integer') then
    v_age := v_age_text::integer;
  end if;

  if v_age is not null and v_age not between 13 and 120 then
    v_age := null;
  end if;

  insert into public.profiles (
    id, first_name, family_name, age, role,
    organization, specialization, preferences
  )
  values (
    new.id, v_first_name, v_family_name, v_age, 'user',
    '', '', '{"theme": "system"}'::jsonb
  )
  on conflict (id) do nothing;

  return new;
end;
$$;

revoke execute on function public.handle_new_user()
  from anon, authenticated, public;

-- ---------------------------------------------------------------------------
-- 3. Administrative writer: replace the old signature, not overload it.
-- ---------------------------------------------------------------------------
-- CREATE OR REPLACE with different arguments would leave the old RPC callable.
-- Dropping that overload ensures no service path still accepts p_full_name.
drop function public.admin_update_profile(
  uuid, text, text, text, timestamptz, uuid, text, text, text
);

create function public.admin_update_profile(
  p_user_id             uuid,
  p_first_name          text,
  p_family_name         text,
  p_age                 smallint,
  p_organization        text,
  p_specialization      text,
  p_expected_updated_at timestamptz,
  p_actor_id            uuid,
  p_actor_email         text,
  p_request_ip          text,
  p_user_agent          text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_before     jsonb;
  v_after      jsonb;
  v_actor_ok   boolean;
  v_updated_at timestamptz;
begin
  select (pr.role = 'admin' and pr.is_disabled = false)
    into v_actor_ok
    from public.profiles pr
   where pr.id = p_actor_id;

  if p_actor_id is not null and coalesce(v_actor_ok, false) = false then
    raise exception 'actor is no longer an administrator'
      using errcode = 'AD004';
  end if;

  select to_jsonb(t), t.updated_at
    into v_before, v_updated_at
    from (
      select p.first_name, p.family_name, p.full_name, p.age,
             p.organization, p.specialization, p.updated_at
        from public.profiles p
       where p.id = p_user_id
       for update
    ) t;

  if v_before is null then
    raise exception 'no such account' using errcode = 'AD003';
  end if;

  if p_expected_updated_at is not null
     and v_updated_at is distinct from p_expected_updated_at then
    raise exception 'profile changed since it was loaded'
      using errcode = 'AD005';
  end if;

  update public.profiles
     set first_name     = p_first_name,
         family_name    = p_family_name,
         age            = p_age,
         organization   = p_organization,
         specialization = p_specialization
   where id = p_user_id;

  -- on_profile_update remains the sole owner of updated_at.
  select to_jsonb(t)
    into v_after
    from (
      select p.first_name, p.family_name, p.full_name, p.age,
             p.organization, p.specialization
        from public.profiles p
       where p.id = p_user_id
    ) t;

  if v_before - 'updated_at' = v_after then
    return v_after;
  end if;

  insert into public.audit_log (
    actor_id, actor_email, action, target_type, target_id,
    before, after, request_ip, user_agent
  )
  values (
    p_actor_id, p_actor_email, 'user.profile_change',
    'user', p_user_id::text,
    v_before - 'updated_at', v_after,
    nullif(p_request_ip, '')::inet, p_user_agent
  );

  return v_after;
end;
$$;

revoke execute on function public.admin_update_profile(
  uuid, text, text, smallint, text, text,
  timestamptz, uuid, text, text, text
) from anon, authenticated, public;

grant execute on function public.admin_update_profile(
  uuid, text, text, smallint, text, text,
  timestamptz, uuid, text, text, text
) to service_role;

-- ---------------------------------------------------------------------------
-- 4. Destructive conversion.
-- ---------------------------------------------------------------------------
-- No CASCADE. An unrecorded dependent object must abort the migration rather
-- than be silently dropped with the source column.
alter table public.profiles
  drop column full_name,
  add column full_name text
    generated always as (
      case
        when first_name is null and family_name is null then null::text
        when first_name is null then family_name
        when family_name is null then first_name
        else first_name || ' ' || family_name
      end
    ) stored;

-- ---------------------------------------------------------------------------
-- 5. Column ACL cutover.
-- ---------------------------------------------------------------------------
-- Table-level grants would override every column decision, so withdraw them
-- first. The newly-created generated column has no write grant; the explicit
-- revoke documents that this is intentional rather than an omission.
revoke insert, update on public.profiles from authenticated, anon;
revoke insert (full_name), update (full_name)
  on public.profiles from authenticated, anon;

grant insert (
  id, first_name, family_name, age,
  organization, specialization, preferences
) on public.profiles to authenticated;

-- id remains writable because PostgREST's upsert emits it in the conflict
-- update set, as documented at 20260814005509:144-149.
grant update (
  id, first_name, family_name, age,
  organization, specialization, preferences
) on public.profiles to authenticated;
```

The application release must change:

```text
Browser upsert:
  remove full_name
  add first_name, family_name, age

Admin RPC call:
  remove p_full_name
  add p_first_name, p_family_name, p_age
```

An already-open old tab sends `full_name`. PostgREST attempts an `INSERT ... ON CONFLICT` containing the generated column, and PostgreSQL rejects the statement with SQLSTATE `428C9`; no profile fields are saved. The current handler logs the technical error and shows the generic bilingual `runtime.profile.saveFailed` message.

No SQL grant or trigger can make an explicitly supplied value writable to a generated column. The deployment must therefore use a bounded maintenance window, bump `ASSET_VERSION`, and force stale clients to reload. If uninterrupted old-client compatibility is mandatory, the generated conversion must be postponed and replaced temporarily by an ordinary `full_name` plus synchronisation trigger. That would be a different, multi-release design.

**Spec 2: Signup Hardening**
This is the final `handle_new_user()` definition once the consent columns from Spec 3 exist. It must be installed in the same transaction that first makes those columns available.

`pg_input_is_valid(text, text)` is the PostgreSQL 17 safe-cast primitive. Unlike a regex, it also rejects values such as an integer-shaped string outside the `integer` range.

“Never raise” means never raise because of arbitrary metadata. It must not be implemented as `EXCEPTION WHEN OTHERS THEN RETURN NEW`; swallowing an infrastructure or schema failure would commit an auth account with no profile and hide the violated invariant.

```sql
-- Client-supplied GoTrue metadata must never turn an AFTER INSERT trigger into
-- an account-creation denial. Every constrained value is normalised before the
-- INSERT; malformed values become NULL or false.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_meta           jsonb := coalesce(new.raw_user_meta_data, '{}'::jsonb);
  v_age_text       text;
  v_age            integer;
  v_first_name     text;
  v_family_name    text;
  v_consent        boolean := false;
  v_policy_version text;
  v_language       text;
begin
  -- left() applies the database bound even if a caller submits megabytes.
  -- btrim() and nullif() give blank input the same representation as omission.
  v_first_name :=
    nullif(left(btrim(v_meta ->> 'first_name'), 100), '');
  v_family_name :=
    nullif(left(btrim(v_meta ->> 'family_name'), 100), '');

  -- PostgreSQL 17 validates the full integer input, including overflow, before
  -- the cast is evaluated. "abc" and "999999999999999999" both become NULL.
  v_age_text := v_meta ->> 'age';
  if pg_catalog.pg_input_is_valid(v_age_text, 'integer') then
    v_age := v_age_text::integer;
  end if;

  if v_age is not null and v_age not between 13 and 120 then
    v_age := null;
  end if;

  -- JSON strings such as "true", numbers, arrays and objects are not consent.
  -- Only an actual JSON boolean is accepted.
  if jsonb_typeof(v_meta -> 'marketing_consent') = 'boolean' then
    v_consent := (v_meta ->> 'marketing_consent')::boolean;
  end if;

  v_policy_version :=
    nullif(left(btrim(v_meta ->> 'marketing_consent_policy_version'), 64), '');

  v_language :=
    case v_meta ->> 'marketing_consent_language'
      when 'en' then 'en'
      when 'ar' then 'ar'
      else null
    end;

  -- A boolean without the disclosure version and language is not an adequate
  -- consent record. Coerce it to a decline rather than aborting signup.
  if v_consent
     and (v_policy_version is null or v_language is null) then
    v_consent := false;
  end if;

  -- The signup UI gates age behind consent. A direct GoTrue caller cannot
  -- bypass that collection rule by submitting age with consent=false.
  if not v_consent then
    v_age := null;
  end if;

  insert into public.profiles (
    id, first_name, family_name, age, role,
    organization, specialization, preferences,
    marketing_consent,
    marketing_consent_policy_version,
    marketing_consent_language,
    marketing_consent_surface
  )
  values (
    new.id, v_first_name, v_family_name, v_age, 'user',
    '', '', '{"theme": "system"}'::jsonb,
    v_consent,
    case when v_consent then v_policy_version end,
    case when v_consent then v_language end,
    case when v_consent then 'signup' end
  )
  on conflict (id) do nothing;

  return new;
end;
$$;

revoke execute on function public.handle_new_user()
  from anon, authenticated, public;
```

This function deliberately does not accept a client timestamp. Spec 3’s profile trigger stamps the grant using the database clock.

**Spec 3: Consent Record**
Use columns on `profiles`, not `audit_log` and not a separate append-only event table.

`audit_log` is specifically an append-only record of administrative actions, service-role-only and intentionally disconnected from account deletion (`20260814032447_audit_log.sql:20-73`). A subject cannot read it directly, its actor/target identifiers survive account deletion by design, and using it for consent would mingle subject choices with operator audit evidence.

The settled requirement asks for current state, latest grant time, latest withdrawal time, and the context of the current/latest grant. Profile columns provide that record and disappear with the existing `profiles.id -> auth.users ON DELETE CASCADE`. If the legal requirement later becomes “retain every grant/withdrawal cycle,” these columns are insufficient and an event table should replace them. Do not call the current design immutable history.

The migration can land before the UI, but marketing collection must remain disabled until an approved bilingual policy and its real version identifier exist.

```sql
-- Store the reader's current marketing-consent record on public.profiles.
--
-- WHY NOT public.audit_log
-- ------------------------
-- audit_log records administrative actions and deliberately survives account
-- deletion (20260814032447_audit_log.sql:20-73). Consent is subject-owned
-- profile data, must be readable by the subject, and should leave with the
-- profile when auth.users cascades it.
--
-- No explicit BEGIN/COMMIT: the migration runner owns the transaction.

-- ---------------------------------------------------------------------------
-- 1. Consent record columns.
-- ---------------------------------------------------------------------------
alter table public.profiles
  add column marketing_consent boolean not null default false,
  add column marketing_consent_granted_at timestamptz,
  add column marketing_consent_withdrawn_at timestamptz,
  add column marketing_consent_policy_version text,
  add column marketing_consent_language text,
  add column marketing_consent_surface text,
  add column marketing_consent_granted_while_unconfirmed boolean;

-- Every constraint is conditional on the GRANTED state. Withdrawal changes the
-- state to false first, so malformed legacy context can never prevent it.
-- There is intentionally no CHECK coupling age to marketing_consent:
-- withdrawal offers to clear age but does not require it.
alter table public.profiles
  add constraint profiles_marketing_consent_grant_chk
    check (
      not marketing_consent
      or (
        marketing_consent_granted_at is not null
        and marketing_consent_policy_version is not null
        and marketing_consent_policy_version =
              btrim(marketing_consent_policy_version)
        and char_length(marketing_consent_policy_version) between 1 and 64
        and marketing_consent_language in ('en', 'ar')
        and marketing_consent_surface is not null
        and marketing_consent_surface = btrim(marketing_consent_surface)
        and char_length(marketing_consent_surface) between 1 and 32
        and marketing_consent_granted_while_unconfirmed is not null
      )
    );

-- ---------------------------------------------------------------------------
-- 2. Server-owned timestamps and grant context.
-- ---------------------------------------------------------------------------
create or replace function public.profiles_set_marketing_consent_record()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_unconfirmed boolean;
begin
  new.marketing_consent := coalesce(new.marketing_consent, false);

  if tg_op = 'INSERT' then
    if new.marketing_consent then
      if new.marketing_consent_policy_version is null
         or new.marketing_consent_policy_version
              is distinct from btrim(new.marketing_consent_policy_version)
         or char_length(new.marketing_consent_policy_version)
              not between 1 and 64
         or new.marketing_consent_language not in ('en', 'ar')
         or new.marketing_consent_surface is null
         or new.marketing_consent_surface
              is distinct from btrim(new.marketing_consent_surface)
         or char_length(new.marketing_consent_surface)
              not between 1 and 32 then
        raise exception 'marketing consent requires valid policy, language and surface'
          using errcode = '22023';
      end if;

      select (u.email_confirmed_at is null)
        into v_unconfirmed
        from auth.users u
       where u.id = new.id;

      new.marketing_consent_granted_at := statement_timestamp();
      new.marketing_consent_withdrawn_at := null;
      new.marketing_consent_granted_while_unconfirmed :=
        coalesce(v_unconfirmed, true);
    else
      -- An unticked signup is an absence of grant, not a withdrawal event.
      new.marketing_consent_granted_at := null;
      new.marketing_consent_withdrawn_at := null;
      new.marketing_consent_policy_version := null;
      new.marketing_consent_language := null;
      new.marketing_consent_surface := null;
      new.marketing_consent_granted_while_unconfirmed := null;
    end if;

    return new;
  end if;

  if new.marketing_consent is not distinct from old.marketing_consent then
    -- A no-op cannot restamp time or rewrite the disclosure under which an
    -- existing grant was captured.
    new.marketing_consent_granted_at :=
      old.marketing_consent_granted_at;
    new.marketing_consent_withdrawn_at :=
      old.marketing_consent_withdrawn_at;
    new.marketing_consent_policy_version :=
      old.marketing_consent_policy_version;
    new.marketing_consent_language :=
      old.marketing_consent_language;
    new.marketing_consent_surface :=
      old.marketing_consent_surface;
    new.marketing_consent_granted_while_unconfirmed :=
      old.marketing_consent_granted_while_unconfirmed;

  elsif new.marketing_consent then
    -- This is a grant or re-grant. The previous withdrawal time remains visible;
    -- state=true disambiguates it from the current grant.
    if new.marketing_consent_policy_version is null
       or new.marketing_consent_policy_version
            is distinct from btrim(new.marketing_consent_policy_version)
       or char_length(new.marketing_consent_policy_version)
            not between 1 and 64
       or new.marketing_consent_language not in ('en', 'ar')
       or new.marketing_consent_surface is null
       or new.marketing_consent_surface
            is distinct from btrim(new.marketing_consent_surface)
       or char_length(new.marketing_consent_surface)
            not between 1 and 32 then
      raise exception 'marketing consent requires valid policy, language and surface'
        using errcode = '22023';
    end if;

    select (u.email_confirmed_at is null)
      into v_unconfirmed
      from auth.users u
     where u.id = new.id;

    new.marketing_consent_granted_at := statement_timestamp();
    new.marketing_consent_withdrawn_at :=
      old.marketing_consent_withdrawn_at;
    new.marketing_consent_granted_while_unconfirmed :=
      coalesce(v_unconfirmed, true);

  else
    -- Withdrawal never validates or clears age and never examines grant context.
    -- It therefore cannot be blocked by stale context or by declining the offer
    -- to erase age.
    new.marketing_consent_granted_at :=
      old.marketing_consent_granted_at;
    new.marketing_consent_withdrawn_at := statement_timestamp();
    new.marketing_consent_policy_version :=
      old.marketing_consent_policy_version;
    new.marketing_consent_language :=
      old.marketing_consent_language;
    new.marketing_consent_surface :=
      old.marketing_consent_surface;
    new.marketing_consent_granted_while_unconfirmed :=
      old.marketing_consent_granted_while_unconfirmed;
  end if;

  return new;
end;
$$;

revoke execute on function public.profiles_set_marketing_consent_record()
  from anon, authenticated, public;

drop trigger if exists profiles_set_marketing_consent_record
  on public.profiles;

create trigger profiles_set_marketing_consent_record
  before insert or update on public.profiles
  for each row
  execute function public.profiles_set_marketing_consent_record();

-- ---------------------------------------------------------------------------
-- 3. Defence in depth for the server-owned evidence fields.
-- ---------------------------------------------------------------------------
create or replace function public.profiles_guard_privilege_columns()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if current_user in ('authenticated', 'anon') and (
       new.role        is distinct from old.role
    or new.tier        is distinct from old.tier
    or new.is_disabled is distinct from old.is_disabled
    or new.marketing_consent_granted_at
         is distinct from old.marketing_consent_granted_at
    or new.marketing_consent_withdrawn_at
         is distinct from old.marketing_consent_withdrawn_at
    or new.marketing_consent_granted_while_unconfirmed
         is distinct from old.marketing_consent_granted_while_unconfirmed
  ) then
    raise exception
      'administered profile columns and consent timestamps are server-owned'
      using errcode = '42501';
  end if;

  return new;
end;
$$;

revoke execute on function public.profiles_guard_privilege_columns()
  from anon, authenticated, public;

-- BEFORE ROW triggers of the same kind fire by trigger name. On UPDATE:
--
--   on_profile_update
--   profiles_guard_privilege_columns
--   profiles_set_marketing_consent_record
--
-- The guard therefore rejects a caller-supplied timestamp before the setter
-- runs. A legitimate toggle omits those columns, passes the guard, and the
-- later setter writes the server timestamps.

-- ---------------------------------------------------------------------------
-- 4. Column grants.
-- ---------------------------------------------------------------------------
-- The state and grant context are reader-supplied. The timestamps and the
-- pre-confirmation fact are not granted and therefore cannot appear in a
-- PostgREST write payload.
grant insert (
  marketing_consent,
  marketing_consent_policy_version,
  marketing_consent_language,
  marketing_consent_surface
) on public.profiles to authenticated;

grant update (
  marketing_consent,
  marketing_consent_policy_version,
  marketing_consent_language,
  marketing_consent_surface
) on public.profiles to authenticated;

revoke insert (
  marketing_consent_granted_at,
  marketing_consent_withdrawn_at,
  marketing_consent_granted_while_unconfirmed
), update (
  marketing_consent_granted_at,
  marketing_consent_withdrawn_at,
  marketing_consent_granted_while_unconfirmed
) on public.profiles from authenticated, anon;

-- ---------------------------------------------------------------------------
-- 5. Signup capture.
-- ---------------------------------------------------------------------------
-- Install the hardened function only after the columns and timestamp trigger
-- exist in this same transaction.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_meta           jsonb := coalesce(new.raw_user_meta_data, '{}'::jsonb);
  v_age_text       text;
  v_age            integer;
  v_first_name     text;
  v_family_name    text;
  v_consent        boolean := false;
  v_policy_version text;
  v_language       text;
begin
  v_first_name :=
    nullif(left(btrim(v_meta ->> 'first_name'), 100), '');
  v_family_name :=
    nullif(left(btrim(v_meta ->> 'family_name'), 100), '');

  v_age_text := v_meta ->> 'age';
  if pg_catalog.pg_input_is_valid(v_age_text, 'integer') then
    v_age := v_age_text::integer;
  end if;

  if v_age is not null and v_age not between 13 and 120 then
    v_age := null;
  end if;

  if jsonb_typeof(v_meta -> 'marketing_consent') = 'boolean' then
    v_consent := (v_meta ->> 'marketing_consent')::boolean;
  end if;

  v_policy_version :=
    nullif(left(btrim(v_meta ->> 'marketing_consent_policy_version'), 64), '');

  v_language :=
    case v_meta ->> 'marketing_consent_language'
      when 'en' then 'en'
      when 'ar' then 'ar'
      else null
    end;

  if v_consent
     and (v_policy_version is null or v_language is null) then
    v_consent := false;
  end if;

  if not v_consent then
    v_age := null;
  end if;

  insert into public.profiles (
    id, first_name, family_name, age, role,
    organization, specialization, preferences,
    marketing_consent,
    marketing_consent_policy_version,
    marketing_consent_language,
    marketing_consent_surface
  )
  values (
    new.id, v_first_name, v_family_name, v_age, 'user',
    '', '', '{"theme": "system"}'::jsonb,
    v_consent,
    case when v_consent then v_policy_version end,
    case when v_consent then v_language end,
    case when v_consent then 'signup' end
  )
  on conflict (id) do nothing;

  return new;
end;
$$;

revoke execute on function public.handle_new_user()
  from anon, authenticated, public;
```

Because `handle_new_user` fires before confirmation, `marketing_consent_granted_while_unconfirmed = true` means only that the newly created, still-unverified account submitted the grant. It is not evidence that the owner of the email address did so. The fact should be recorded as above, exposed in subject export, and paired with an explicit retention/purge policy for abandoned unconfirmed accounts. The verified live count is currently zero, but that is not a future retention policy.

Withdrawal must bypass application rate limiting as well as database constraints.

**Spec 4: Account Deletion**
A single deletion RPC is the wrong design. `web/api/admin.py:329-339` already states the governing fact: a database transaction cannot include an outbound provider call.

Use two migrations. The FK-action replacement is destructive DDL and lands first. The saga schema then lands separately.

**Migration A: FK prerequisites**

```sql
-- Make administrator attribution non-blocking when the referenced auth account
-- is permanently deleted.
--
-- DESTRUCTIVE-CHECK RECORD, 2026-08-23
-- ------------------------------------
-- Verified live:
--   * profiles.disabled_by -> auth.users(id) has NO ACTION.
--   * app_settings.updated_by -> auth.users(id) has NO ACTION.
--   * profiles.id -> auth.users(id) already has ON DELETE CASCADE.
--   * No chat_* table has an FK to auth.users.
--   * profiles_disabled_by_idx and app_settings_updated_by_idx already exist
--     from the migrations that created these FKs; replacing the FK actions does
--     not remove either index.
--
-- The two NO ACTION constraints currently make deleting a referenced
-- administrator fail with SQLSTATE 23503. SET NULL preserves the affected
-- profile/settings row while honestly recording that its auth principal is gone.

alter table public.profiles
  drop constraint profiles_disabled_by_fkey,
  add constraint profiles_disabled_by_fkey
    foreign key (disabled_by)
    references auth.users(id)
    on delete set null;

alter table public.app_settings
  drop constraint app_settings_updated_by_fkey,
  add constraint app_settings_updated_by_fkey
    foreign key (updated_by)
    references auth.users(id)
    on delete set null;
```

**Migration B: durable saga**

```sql
-- Durable, idempotent account-deletion coordination.
--
-- The row deliberately has NO FK to auth.users: it must survive the provider
-- deleting that user so a crashed worker can distinguish pending from deleted.
--
-- Reader-facing chats are purged explicitly by owner_id because
-- 20260820131914_chat_session_persistence.sql:38-42 deliberately created no
-- auth.users FK. public.chat_archive is never touched.

-- ---------------------------------------------------------------------------
-- 1. Durable state.
-- ---------------------------------------------------------------------------
create table public.account_deletions (
  user_id       uuid primary key,
  operation_id  uuid not null default gen_random_uuid() unique,

  state text not null default 'pending'
    check (
      state in (
        'pending',
        'purged',
        'auth_delete_requested',
        'auth_delete_unknown',
        'deleted'
      )
    ),

  requested_at                 timestamptz not null default now(),
  session_revoke_last_attempt_at timestamptz,
  sessions_revoked_at          timestamptz,
  reader_data_purged_at        timestamptz,
  auth_delete_last_attempt_at  timestamptz,
  deleted_at                   timestamptz,

  attempt_count  integer not null default 0 check (attempt_count >= 0),
  next_attempt_at timestamptz not null default now(),
  last_error text
    check (last_error is null or char_length(last_error) <= 1000)
);

create index account_deletions_retry_idx
  on public.account_deletions (next_attempt_at, requested_at)
  where state <> 'deleted';

alter table public.account_deletions enable row level security;

-- RLS has zero policies deliberately. This is an internal coordinator table,
-- not a subject-editable profile surface. The service role may inspect state;
-- all mutations go through the functions below.
revoke all on public.account_deletions
  from anon, authenticated, service_role;
grant select on public.account_deletions to service_role;

comment on table public.account_deletions is
  'Internal account-deletion saga state. No auth.users FK so completion '
  'survives deletion; RLS enabled with no browser policies.';

-- ---------------------------------------------------------------------------
-- 2. Immediate pending-state enforcement for direct chat access.
-- ---------------------------------------------------------------------------
-- Refresh-token revocation does not invalidate an already-issued access token
-- until exp. This helper makes pending deletion effective in the known chat RLS
-- policies immediately rather than trusting token expiry.
create or replace function public.account_deletion_is_pending()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
      from public.account_deletions d
     where d.user_id = (select auth.uid())
       and d.state <> 'deleted'
  );
$$;

revoke execute on function public.account_deletion_is_pending()
  from anon, public;
grant execute on function public.account_deletion_is_pending()
  to authenticated;

drop policy if exists chat_sessions_select_own
  on public.chat_sessions;
create policy chat_sessions_select_own
  on public.chat_sessions
  for select to authenticated
  using (
    owner_id = (select auth.uid())
    and not (select public.account_deletion_is_pending())
  );

drop policy if exists chat_sessions_delete_own
  on public.chat_sessions;
create policy chat_sessions_delete_own
  on public.chat_sessions
  for delete to authenticated
  using (
    owner_id = (select auth.uid())
    and not (select public.account_deletion_is_pending())
  );

drop policy if exists chat_messages_select_own
  on public.chat_messages;
create policy chat_messages_select_own
  on public.chat_messages
  for select to authenticated
  using (
    owner_id = (select auth.uid())
    and not (select public.account_deletion_is_pending())
  );

drop policy if exists chat_message_sources_select_own
  on public.chat_message_sources;
create policy chat_message_sources_select_own
  on public.chat_message_sources
  for select to authenticated
  using (
    not (select public.account_deletion_is_pending())
    and exists (
      select 1
        from public.chat_messages m
       where m.id = chat_message_sources.message_id
         and m.owner_id = (select auth.uid())
    )
  );

-- ---------------------------------------------------------------------------
-- 3. Persist the request before any outbound call.
-- ---------------------------------------------------------------------------
create or replace function public.account_deletion_request(p_user_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_is_enabled_admin boolean;
  v_enabled_admins   integer;
  v_result           jsonb;
begin
  if not exists (
    select 1 from auth.users u where u.id = p_user_id
  ) then
    select to_jsonb(d)
      into v_result
      from public.account_deletions d
     where d.user_id = p_user_id
       and d.state = 'deleted';

    if v_result is not null then
      return v_result;
    end if;

    raise exception 'no such account' using errcode = 'AD003';
  end if;

  -- Deleting an administrator is a membership change. Share the existing
  -- serialization key so deletion cannot race the last-admin guard.
  perform pg_advisory_xact_lock(
    pg_catalog.hashtext('sfda.admin_membership')
  );

  select (p.role = 'admin' and not p.is_disabled)
    into v_is_enabled_admin
    from public.profiles p
   where p.id = p_user_id;

  if coalesce(v_is_enabled_admin, false) then
    select count(*)
      into v_enabled_admins
      from public.profiles p
     where p.role = 'admin'
       and not p.is_disabled;

    if v_enabled_admins <= 1 then
      raise exception 'this would leave no enabled administrator'
        using errcode = 'AD002';
    end if;
  end if;

  insert into public.account_deletions (user_id)
  values (p_user_id)
  on conflict (user_id) do nothing;

  -- Keep the profile until GoTrue deletion. Its existing cascade then removes
  -- names, age and consent atomically with the auth identity. Disabling now
  -- stops supported application use while the external steps are pending.
  update public.profiles
     set is_disabled = true,
         disabled_at = coalesce(disabled_at, statement_timestamp()),
         disabled_reason =
           coalesce(disabled_reason, 'account deletion pending')
   where id = p_user_id;

  select jsonb_build_object(
           'operation_id', d.operation_id,
           'state', d.state,
           'requested_at', d.requested_at
         )
    into v_result
    from public.account_deletions d
   where d.user_id = p_user_id;

  return v_result;
end;
$$;

revoke execute on function public.account_deletion_request(uuid)
  from anon, authenticated, public;
grant execute on function public.account_deletion_request(uuid)
  to service_role;

-- ---------------------------------------------------------------------------
-- 4. Record session-revocation outcome.
-- ---------------------------------------------------------------------------
-- accepted means GoTrue accepted the revocation operation. A timeout is
-- outcome_unknown, not failure; retrying revocation is safe.
create or replace function public.account_deletion_record_revocation(
  p_user_id uuid,
  p_outcome text,
  p_error   text default null
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_outcome not in ('accepted', 'rejected', 'unknown') then
    raise exception 'invalid revocation outcome'
      using errcode = '22023';
  end if;

  update public.account_deletions d
     set session_revoke_last_attempt_at = statement_timestamp(),
         sessions_revoked_at =
           case
             when p_outcome = 'accepted'
             then coalesce(d.sessions_revoked_at, statement_timestamp())
             else d.sessions_revoked_at
           end,
         attempt_count = d.attempt_count + 1,
         next_attempt_at =
           case
             when p_outcome = 'accepted' then statement_timestamp()
             else statement_timestamp() + interval '5 minutes'
           end,
         last_error =
           case
             when p_outcome = 'accepted' then null
             else left(p_error, 1000)
           end
   where d.user_id = p_user_id
     and d.state <> 'deleted';

  if not found then
    if exists (
      select 1
        from public.account_deletions d
       where d.user_id = p_user_id
         and d.state = 'deleted'
    ) then
      return;
    end if;

    raise exception 'no deletion request for account'
      using errcode = 'AD003';
  end if;
end;
$$;

revoke execute on function public.account_deletion_record_revocation(
  uuid, text, text
) from anon, authenticated, public;
grant execute on function public.account_deletion_record_revocation(
  uuid, text, text
) to service_role;

-- ---------------------------------------------------------------------------
-- 5. Purge reader-facing database data.
-- ---------------------------------------------------------------------------
create or replace function public.account_deletion_purge_reader_data(
  p_user_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_state       text;
  v_revoked_at  timestamptz;
  v_deleted     integer;
  v_auth_exists boolean;
begin
  select d.state, d.sessions_revoked_at
    into v_state, v_revoked_at
    from public.account_deletions d
   where d.user_id = p_user_id
   for update;

  if not found then
    raise exception 'no deletion request for account'
      using errcode = 'AD003';
  end if;

  if v_state = 'deleted' then
    return jsonb_build_object('state', 'deleted', 'sessions_deleted', 0);
  end if;

  select exists (
    select 1 from auth.users u where u.id = p_user_id
  ) into v_auth_exists;

  -- If auth already disappeared, revocation is moot and reconciliation must
  -- still purge the FK-less transcript rows.
  if v_auth_exists and v_revoked_at is null then
    raise exception 'sessions must be revoked before reader data is purged'
      using errcode = 'AD006';
  end if;

  -- The cascade removes chat_messages and chat_message_sources. There is no
  -- DELETE against chat_archive: its HMAC-keyed training lifetime is separate.
  delete from public.chat_sessions s
   where s.owner_id = p_user_id;

  get diagnostics v_deleted = row_count;

  if v_auth_exists then
    update public.account_deletions
       set state = 'purged',
           reader_data_purged_at =
             coalesce(reader_data_purged_at, statement_timestamp()),
           next_attempt_at = statement_timestamp(),
           last_error = null
     where user_id = p_user_id;
  else
    update public.account_deletions
       set state = 'deleted',
           reader_data_purged_at =
             coalesce(reader_data_purged_at, statement_timestamp()),
           deleted_at = coalesce(deleted_at, statement_timestamp()),
           next_attempt_at = statement_timestamp(),
           last_error = null
     where user_id = p_user_id;
  end if;

  return jsonb_build_object(
    'state', case when v_auth_exists then 'purged' else 'deleted' end,
    'sessions_deleted', v_deleted
  );
end;
$$;

revoke execute on function public.account_deletion_purge_reader_data(uuid)
  from anon, authenticated, public;
grant execute on function public.account_deletion_purge_reader_data(uuid)
  to service_role;

-- ---------------------------------------------------------------------------
-- 6. Record intent immediately before the GoTrue delete call.
-- ---------------------------------------------------------------------------
create or replace function public.account_deletion_begin_auth_delete(
  p_user_id uuid
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_state        text;
  v_operation_id uuid;
begin
  select d.state, d.operation_id
    into v_state, v_operation_id
    from public.account_deletions d
   where d.user_id = p_user_id
   for update;

  if not found then
    raise exception 'no deletion request for account'
      using errcode = 'AD003';
  end if;

  if v_state = 'deleted' then
    return v_operation_id;
  end if;

  if v_state not in ('purged', 'auth_delete_unknown', 'auth_delete_requested') then
    raise exception 'reader data has not been purged'
      using errcode = 'AD006';
  end if;

  if not exists (
    select 1 from auth.users u where u.id = p_user_id
  ) then
    update public.account_deletions
       set state = 'deleted',
           deleted_at = coalesce(deleted_at, statement_timestamp()),
           last_error = null
     where user_id = p_user_id;

    return v_operation_id;
  end if;

  update public.account_deletions
     set state = 'auth_delete_requested',
         auth_delete_last_attempt_at = statement_timestamp(),
         attempt_count = attempt_count + 1,
         next_attempt_at = statement_timestamp() + interval '5 minutes',
         last_error = null
   where user_id = p_user_id;

  return v_operation_id;
end;
$$;

revoke execute on function public.account_deletion_begin_auth_delete(uuid)
  from anon, authenticated, public;
grant execute on function public.account_deletion_begin_auth_delete(uuid)
  to service_role;

-- ---------------------------------------------------------------------------
-- 7. Reconcile the non-transactional GoTrue outcome.
-- ---------------------------------------------------------------------------
create or replace function public.account_deletion_record_auth_outcome(
  p_user_id uuid,
  p_outcome text,
  p_error   text default null
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_state text;
begin
  if p_outcome not in ('accepted', 'rejected', 'unknown') then
    raise exception 'invalid auth deletion outcome'
      using errcode = '22023';
  end if;

  select d.state
    into v_state
    from public.account_deletions d
   where d.user_id = p_user_id
   for update;

  if not found then
    raise exception 'no deletion request for account'
      using errcode = 'AD003';
  end if;

  if v_state = 'deleted' then
    return;
  end if;

  -- Database truth wins over the transport outcome. If auth.users is absent,
  -- GoTrue committed the deletion even if the caller observed a timeout.
  if not exists (
    select 1 from auth.users u where u.id = p_user_id
  ) then
    -- Idempotent safety purge for a worker that died between provider deletion
    -- and the earlier transcript purge/final state write.
    delete from public.chat_sessions s
     where s.owner_id = p_user_id;

    if exists (
      select 1 from public.profiles p where p.id = p_user_id
    ) then
      raise exception 'auth user is absent but cascading profile deletion failed';
    end if;

    update public.account_deletions
       set state = 'deleted',
           reader_data_purged_at =
             coalesce(reader_data_purged_at, statement_timestamp()),
           deleted_at = coalesce(deleted_at, statement_timestamp()),
           next_attempt_at = statement_timestamp(),
           last_error = null
     where user_id = p_user_id;

    return;
  end if;

  update public.account_deletions
     set state =
           case
             when p_outcome = 'rejected' then 'purged'
             else 'auth_delete_unknown'
           end,
         next_attempt_at = statement_timestamp() + interval '5 minutes',
         last_error = left(p_error, 1000)
   where user_id = p_user_id;
end;
$$;

revoke execute on function public.account_deletion_record_auth_outcome(
  uuid, text, text
) from anon, authenticated, public;
grant execute on function public.account_deletion_record_auth_outcome(
  uuid, text, text
) to service_role;
```

The server-side orchestration is:

1. Derive `p_user_id` from the verified bearer token, never the request body.
2. Call `account_deletion_request()`. Only after it commits may the browser clear its local session.
3. Revoke all refresh sessions through the existing GoTrue administrative mechanism. Record `accepted`, `rejected`, or `unknown`.
4. Call `account_deletion_purge_reader_data()`.
5. Call `account_deletion_begin_auth_delete()` before the outbound request.
6. Permanently delete the user through the GoTrue Admin API. Do not issue `DELETE FROM auth.users`.
7. Treat GoTrue “not found” as idempotent success and call `account_deletion_record_auth_outcome()`.
8. Run a scheduled reconciler over non-`deleted` rows whose `next_attempt_at <= now()`.

Failure behavior is deterministic:

- Request transaction fails: nothing is disabled or queued.
- Revocation fails or times out: state remains `pending`; no reader data has been destroyed; retry.
- Database purge fails: its transaction rolls back; retry.
- GoTrue definitively rejects deletion: state returns to `purged`; profile/auth remain disabled; retry or alert.
- GoTrue outcome is unknown: state becomes `auth_delete_unknown`; query/retry.
- GoTrue commits and the process dies before recording it: reconciliation sees `auth.users` absent, repeats the chat purge, and marks `deleted`.
- Missing FK prerequisite: GoTrue deletion fails with `23503`; do not mark deleted.

A truthful reader-facing retention statement would say:

> Account deletion removes your login identity, profile information including name, age and consent record, and reader-facing chat history. Administrative audit records and the deletion-operation ledger may be retained for security and accountability. Separately retained HMAC-pseudonymised training archive records are not deleted with your account. The archive is currently dormant, but its separate retention applies if enabled. Deleted data may also remain in backups until the documented backup-retention period expires.

No backup period is present in the supplied facts, so the product must not claim a number of days until that policy is queried and documented.

<!-- END VERBATIM — Appendix E -->
