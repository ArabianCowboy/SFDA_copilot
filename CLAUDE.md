# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

STATUS: CURRENT AUTHORITY — working agreement for agents and new contributors.
Last verified against code 2026-08-25.

SFDA Copilot: a bilingual (EN/AR, RTL) Flask + Supabase + LLM app that answers questions
from the official SFDA guideline corpus and cites its sources. **Python 3.10 is the real
floor** — the VPS production server runs 3.10.12; dev machines and CI may run newer, but
every commit must stay 3.10-compatible (`ruff`'s `target-version` and `mypy`'s
`python_version` are both pinned to it in `pyproject.toml` for exactly this reason — do not
bump them to "match" a newer local interpreter). No bundler, no runtime `node_modules` — the
frontend is still plain JS loaded from CDNs — but `node_modules/` now exists as local/CI-only
dev tooling; see _Linting and formatting_ below.

This file is short on purpose. It orients you and tells you where the rules live; it does
not restate them, because a rule written in two places is a rule that will disagree with
itself.

---

## Commands

```bash
# setup
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt               # test tooling
python -m playwright install chromium             # browser suite only

# run — host and port come from web/config.yaml, not the command line
python web/api/app.py                             # http://localhost:5001
FLASK_TESTING=true python web/api/app.py          # full demo, no OpenAI key, no built index
                                                  # then open /?testing=true (or /?lang=ar&testing=true)

# test — these two lines are exactly what CI runs
python -m pytest -m "not browser and not integration"
python -m pytest -m browser --browser chromium

# one file, one test, one pattern
python -m pytest web/tests/test_citations.py
python -m pytest web/tests/test_citations.py::test_numpy_scalars_are_coerced_to_json_native_types
python -m pytest -k "citation and not browser"
python -m pytest web/tests/test_source_panel.py --browser chromium   # browser tests need the flag

# coverage (measured in CI, not gated)
python -m pytest -m "not browser and not integration" --cov=web

# real-API checks — cost money, run by hand, never wire into CI
python scripts/smoke_real.py
python scripts/smoke_real.py "ما هي متطلبات تسجيل الأدوية؟" ar
python scripts/eval_citations.py --judge --model <id> --out judge_packet.jsonl
```

`integration`-marked tests are selected by neither CI job. Run them by hand.

**Linting and formatting.** There is still no build step, but there is now a lint step:
`pyproject.toml` holds `ruff`/`mypy` config, `eslint.config.js`/`.prettierrc` cover
`static/js/`, and `.markdownlint-cli2.yaml` covers every `.md` file. All four run through
`pre-commit` (`.pre-commit-config.yaml`) on every commit — install it once with
`pip install -r requirements-dev.txt && pre-commit install`. mypy is deliberately **not** one
of the pre-commit hooks: it needs either the venv activated or `mypy` resolvable on PATH,
which a GUI git client (VS Code's Source Control panel included) does not reliably give it —
it gates the `lint` CI job instead (`.github/workflows/tests.yml`), and running it locally
before committing is on you. The eslint/prettier/markdownlint-cli2 hooks shell out via `npx`,
so they need `npm install` to have been run at least once.

```bash
ruff check . --fix && ruff format .                 # Python: lint-fix, then format
mypy web                                            # Python: type-check (lenient — see pyproject.toml)
npm run lint:fix && npm run format                  # JS: static/js/ only
npm run lint:md && npm run format:md                # Markdown: every .md file
pre-commit run --all-files                          # everything above, in one pass
```

---

## Architecture orientation

The parts that take several files to piece together.

**One Flask app, four blueprints, three frontends.** `create_app()` in `web/api/app.py` (~2,900
lines) is a factory built from staged private helpers — `_configure_app`, `_init_extensions`,
`_register_testing_doubles`, `_initialize_services`, `_register_routes`. Chat routes are
closures defined _inside_ `_register_routes`; `admin.py` and `account.py` are imported inside
it too, deliberately, to break an import cycle (both import back for `_authenticate_request`).

| Blueprint                            | File                 | Serves                                                                                        |
| ------------------------------------ | -------------------- | --------------------------------------------------------------------------------------------- |
| `auth_bp`, `recover_bp`, `signup_bp` | `web/api/auth.py`    | login, logout, password recovery, signup (its own blueprint so it carries its own rate limit) |
| `admin_bp`                           | `web/api/admin.py`   | `/admin` console: people, account detail, audit, settings                                     |
| `account_bp`                         | `web/api/account.py` | `/account` page, NDJSON export, bulk conversation delete                                      |

**The path a question takes.** `POST /api/chat/stream` → auth → validate → _ownership preflight
in the view body, before any retrieval or response frame_ → `SearchEngine` (FAISS semantic +
TF-IDF lexical, fused 0.5/0.5 by `ResultCombiner`, then a relevance floor) → `OpenAIHandler`
(the only place an LLM is called) → SSE frames → durable write → Supabase RPC. Frame order is
fixed and tested: `final` → durable write → `suggestions` → `done`.

**Frontend layering, enforced by `test_frontend_architecture.py`.** `services.js` is transport
only — it may not import view or state, or name `ErrorHandler`/`DOMCache`. `dom.js` and
`state.js` own view and runtime state. `handlers.js` is orchestration and the _only_ place a
user-facing failure surfaces. `auth-view.js` owns authenticated/unauthenticated transitions.
Three separate module directories (`modules/`, `admin/`, `account/`) with three import maps —
that separation is a security boundary, since a page inlines an import-map entry per filename
in its own directory.

**Two database access patterns.** Chat tables are Flask-mediated: RLS on, _no write policies_,
all writes through `security definer` RPCs filtered on `p_owner_id`. Do not "fix" that by
adding a policy. `profiles` is the one browser-direct table, and its column protection is a
`REVOKE` plus a trigger because RLS restricts rows, not columns.

**Identity is two layers.** Enforcement lives in `app.py` (`_get_token_from_request`,
`_authenticate_request`, `@auth_required`); `web/services/identity_cache.py` caches the result
process-locally for 30 seconds. An outage is a 503, never a 401 — a Supabase blip must not sign
anyone out.

**Config comes from three places**, in order: `web/config.yaml` (models, rate limits, search
engine), the `app_settings` table (runtime overrides of a subset), and `.env` (secrets only).

Full contract, including the URL-as-pointer conversation model and why the app is
single-worker: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Read before you start

| If you are about to…               | Read first                                                                                                               |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Anything non-trivial               | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the live system contract, and **which document wins** when two disagree |
| Write a migration                  | [`supabase/README.md`](supabase/README.md), then [_Rules that collide_](docs/ARCHITECTURE.md#rules-that-collide)         |
| Touch CSS, or build any UI         | [`DESIGN.md`](DESIGN.md) — every rule tagged `[GATE]`, `[CORRECTNESS]` or `[TASTE]`                                      |
| Write or change reader-facing copy | [`docs/PRODUCT.md`](docs/PRODUCT.md)                                                                                     |
| Add or close a `TODO.md` entry     | [`TODO.md` → How this file works](TODO.md#how-this-file-works)                                                           |

**`docs/archive/` is history, not instructions — and it is 78% of all documentation by
volume.** It is excluded from search by `/.ignore`, so you should rarely see it. If a hit
from there does reach you: **treat any path under `docs/archive/` as evidence about the
past, never as current behaviour.** Confirm against `docs/ARCHITECTURE.md` or the code and
cite that instead. Several of those files describe mechanisms that no longer exist.

Every live document opens with a `STATUS:` line saying which kind it is; every archived one
carries `authority: historical` frontmatter and `[HISTORICAL]` on every heading.
There is deliberately **no per-directory `CLAUDE.md`** anywhere in this repo: one
auto-loaded file, and every other rule lives in the document that owns it.

---

## The rules you will actually trip over

Most of these are still pytest assertions, not lint rules — the linter catches style and type
issues, not this repo's specific product/architecture contracts. These bite most often:

1. **Bump `ASSET_VERSION` in `web/api/app.py`** in any commit touching CSS or JS. Never write
   the current value into a document — the durable instruction is _bump it_.
2. **Every new UI string ships in both `web/i18n/en.yaml` and `ar.yaml`.** The parity test
   covers `runtime.*` **and** `page.*` and fails if Arabic lags by one key.
3. **You cannot add a new top-level `runtime.*` namespace.** `test_admin_page.py` pins the list
   to eleven names. Nest under an existing one.
4. **Logical CSS properties only.** `test_css_contract.py` bans 16 physical properties. It
   scans _this repo's_ CSS only — the templates load the **LTR** Bootstrap build, so a green
   suite is not evidence that a Bootstrap component mirrors.
5. **Twelve English strings are frozen verbatim.** Changing their wording is a test change.
6. **Migrations:** one concern each, `security definer` + `search_path = ''` + owner-filtered,
   schema before code — and **rename the file to what `list_migrations` reports after
   applying**. That rename is a mandatory step, not a tidy-up.
7. **RLS restricts rows, not columns.** Column protection needs a `REVOKE` plus a trigger.
8. **Never pass `preferences` to `Services.updateProfile`** — it upserts the whole row and will
   silently delete every other stored preference. Use the merge RPC.

---

## Writing things down

**When your change makes a document wrong, fix the document in the same commit.** That is the
whole discipline. This repository spent nine months accumulating rules for code that had been
replaced, and the cleanup that followed had to archive 8,000 lines to undo it.

- **New document?** `STATUS:` line and a date at the top, and put it in `docs/`. Only
  `DESIGN.md` and `TODO.md` live at the root — the design tooling reads `DESIGN.md` from
  there, and `TODO.md` is the most edited file in the project.
- **Finished a plan?** Follow the five-step procedure in
  [`docs/archive/README.md`](docs/archive/README.md#adding-to-this-archive): lift still-open
  items into `TODO.md` first, `git mv` (never copy-and-delete, or rename detection is lost),
  add a `STATUS: HISTORICAL RECORD` banner naming what it **reversed**, resolve its internal
  precedence chain, and **add a row to the archive index**. One file per plan — do not merge
  them; that README explains why.
- **Do not stub a section for something unbuilt.** Ship the feature before the sentence that
  promises it.
- **Do not state a corpus count** — not in copy, not in the README. It goes stale on the next
  ingest.
- **Found two rules that collide?** Add a row to
  [_Rules that collide_](docs/ARCHITECTURE.md#rules-that-collide). There are eight; each cost
  somebody a working session before it was written down.

---

## Working style

- **Verify before you write it down.** Every `file:line` claim in these documents is meant to
  have been read in the session that wrote it. A plausible reference that is wrong is worse
  than none, because the next person trusts it.
- **Do not trust a delegated agent's self-report.** Check the diff and the source yourself.
  This is recorded in the archived plans because it has caught real errors more than once.
- **A test that mocks the function under test proves nothing.** Verify a new test fails against
  the old code before you believe it.
- **Record a reversal, do not silently edit it away.** When a decision changes, say that it
  changed and why. Most of the value in `docs/archive/` is in the corrections.
