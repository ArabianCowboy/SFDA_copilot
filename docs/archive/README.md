STATUS: HISTORICAL RECORD — index of finished work. Nothing in this directory is an instruction.
Last verified 2026-08-23.

# Archive

Finished planning documents and resolved `TODO.md` entries. **This directory is history.**
Several files record decisions that were later reversed, and a few describe mechanisms that
no longer exist. Never implement from anything here without checking the live documents
first — [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) is the system contract, and
[`supabase/README.md`](../../supabase/README.md) is the database one.

They are kept because this project writes a plan as *what we decided, what it cost, and what
we got wrong* — and the second and third parts stay useful long after the first stops being
true. Most of the value in here is in the corrections.

**If you landed here from a search, you almost certainly want one of these instead:**

| Question | Live authority |
|---|---|
| How does the system work now? | [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) |
| Migrations, RLS, RPC rules, schema | [`supabase/README.md`](../../supabase/README.md) |
| Design tokens, RTL, component rules | [`DESIGN.md`](../../DESIGN.md) |
| Copy, terminology, product claims | [`docs/PRODUCT.md`](../PRODUCT.md) |
| What is still open | [`TODO.md`](../../TODO.md) |

Three standing rules for this directory:

1. **Never cite a file here as current behaviour.** Confirm against a live authority above or
   against the code, and cite that instead.
2. **Never edit a file here to make it "correct".** These are frozen. Their value is that they
   show what was believed at the time, including what turned out to be wrong.
3. **Designs that were reversed before shipping** and that a confident passage here may still
   describe: a cookie-based conversation pointer, a `sessionStorage` per-tab pointer,
   browser-direct deletes, "only verified citations are openable", and `#profileModal`. None of
   those exist.

**Scan this table first.** It exists so you do not have to open a 4,800-line document to
find out whether it is the one you want.

| Archived | Subject | What it decided | What it reversed | Lines |
|---|---|---|---|---|
| [2026-08-17_pagination.md](2026-08-17_pagination.md) | Admin People pager | Offset pagination with a deterministic tie-break; page sizes 25/50/100/200 capped at 200; a sequence token, not network order, as the correctness guarantee | Nothing. Self-consistent and contradicts no live code — archived because it is finished, not because it went wrong. The one deviation it records, a deferred `pg_trgm` index, is still deferred. | 1,044 |
| [2026-08-20_chat-persistence.md](2026-08-20_chat-persistence.md) | Durable chat history | Two message rows per turn written by one statement; ordering by per-session `seq`, never a timestamp; every retrieved passage stored with a `cited` flag; write at `final` | **Four positions, listed in its banner.** The cookie-held `conv_id` and the whole resume subsystem; "only a verified citation is openable"; "step 8 calls the delete RPC browser-direct"; and all of §7, cut rather than deferred. | 1,131 |
| [2026-08-22_per-tab-deep-linking.md](2026-08-22_per-tab-deep-linking.md) | `/c/<uuid>` conversations | **The URL is the pointer** — no cookie, no `sessionStorage`, no per-tab state; `/c/<id>` unauthenticated with no existence oracle; Back replaces the undo toast | Its own §9 says `POST /api/conversation/reset` was "left alone deliberately"; the route was deleted entirely. Its §0.1/§0.3 also record a `SameSite` claim every earlier round had asserted and got wrong. | 1,193 |
| [2026-08-23_profile-refactor.md](2026-08-23_profile-refactor.md) | `/account`, identity, data rights | A server-rendered page, not a modal; `full_name` becomes a generated column over `first_name`/`family_name`/`age`; preferences merge rather than replace; no avatar upload, ever | **Its own header**, which said "not started, nothing here is built" while ~90% shipped. Also a name-splitting backfill, withdrawn twice, and the entire active-sessions list, cut because the API has no such endpoint. | 4,867 |
| [TODO-resolved.md](TODO-resolved.md) | 33 closed entries | — | Several carry a `(original entry)` heading: the first diagnosis, kept where a later one superseded it and the difference was worth recording. | 1,998 |

Two items from the profile refactor are still open and live in
[`TODO.md`](../../TODO.md), not here: bilingual security email templates and account
deletion. Open work is never left inside an archived plan. (A third, the consent section,
shipped on 2026-08-23 after this archive was written — what remains is a legal review of the
draft privacy policy, tracked as its own entry.)

---

## Why these are separate files and not one

The question comes up, so here is the answer on the record.

Merging ~10,000 lines into a single archive file would trade a solved problem for a new one:

- **Search loses its most useful field.** `rg "conversation_id" docs/archive/` currently tells
  you *which plan* every hit belongs to. In one file every hit reports the same filename and
  a line number, and you have to scroll to find out what you are reading.
- **Git history breaks.** All four plans moved here with `git mv` and were recorded as renames
  at 97–99% similarity, so `git log --follow` walks back through every revision of the
  original. A concatenation preserves that for at most one of them.
- **Document boundaries carry meaning.** A paragraph's file tells you its date, its subject
  and its author's state of knowledge. Merged, that context has to be reconstructed by
  scrolling upward.
- **An archive nobody can navigate is a deleted archive**, with the added cost of polluting
  every repository-wide search.

The real gap was never file count — it was that there was no single place to look. That is
what this table is for.

This matches standard practice: one artifact per decision, in a directory, with a curated
index — the shape used by Architecture Decision Records, the Rust and Python RFC processes,
and the IETF RFC Index.

---

## How this directory is quarantined

The reader this archive most endangers is not a human — it is an AI agent. A human who opens
a file sees the banner at the top. An agent that runs `rg "chat_append_turn" docs/` gets
line 3,204 with no banner anywhere near it, and detailed historical prose reads exactly like
a specification.

The scale of the hazard, measured: this directory is **78% of all documentation in the
repository**, and before quarantine a search for `conv_id` — a mechanism that was *deleted* —
returned **34 hits, 33 of them here**.

Four layers, in order of how much work they actually do — layer 1 does nearly all of it,
and the others exist for the cases it misses:

1. **Excluded from search.** `/.ignore` at the repository root hides this directory from
   ripgrep and every tool built on it, including Claude Code's own search. This is the
   defence that does almost all the work. To search here deliberately:
   `rg --no-ignore "term" docs/archive/`.
2. **`[HISTORICAL]` on every heading** (319 of them). A backstop for fragment retrieval, and
   an honest one: median heading spacing here is 14-39 lines, so a match near a heading
   carries the marker — but long prose runs reach 889 lines from the nearest heading, and a
   three-line grep context in the middle of one of those will show no marker at all. This
   layer helps; it does not guarantee.
3. **Machine-readable frontmatter** — `authority: historical`, `do_not_implement: true`, and
   the live documents that supersede it.
4. **This index**, whose first screen states the rule and routes you to the live authority.

A per-directory `CLAUDE.md` was tried here and removed. It bought one thing — Claude Code
auto-loads a subdirectory's `CLAUDE.md` when it reads files there — at the cost of a second
copy of rules that already live in this file, readable by one vendor's tool and no other. A
duplicated rule that drifts is the failure this whole archive exists to document. Layer 1 is
vendor-neutral and does the work.

## Adding to this archive

When a plan is finished:

1. **Lift anything still open into [`TODO.md`](../../TODO.md) as its own entry, first.** Open
   work buried inside a document marked as history is work nobody will find.
2. `git mv` it here — do not copy and delete, or the rename detection that preserves history
   is lost. Name it `YYYY-MM-DD_short-subject.md`, using the date it was finished, so the
   directory sorts chronologically.
3. **Add the frontmatter block and the `> [!CAUTION]` banner**, copying the shape of any
   existing file here. Name what it superseded and, specifically, **what it reversed** — the
   part a future reader most needs and is least able to reconstruct.
4. **Prefix every heading with `[HISTORICAL]`.** Skip headings inside fenced code blocks.
5. **Resolve its internal precedence chain.** If the document requires you to know that §15
   overrides §14 to read it safely, state the final position at the top instead. A frozen
   document you must read in a special order has not been frozen.
6. **Add a row to the table above.** An index that lags the directory is worse than no index.

Do not retroactively rewrite the plans already here to be shorter. They are verbose because
implementation plans are mostly execution scaffold — that is a reason to summarise the *next*
one as you write it, not to spend hours editing finished history.

Year subdirectories are not needed yet. Introduce them when this listing outgrows a single
screen, at roughly fifty files.
