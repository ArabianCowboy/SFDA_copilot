STATUS: CURRENT AUTHORITY — how to set up, run, test and deploy this project.
Last verified against code 2026-08-23.

# SFDA Copilot

An AI-powered regulatory guidance system for Saudi pharmaceutical regulation, built with
Flask, Supabase and browser-native ES modules. It answers questions from the official SFDA
guideline corpus and shows its work: every claim carries a numbered citation that resolves
to a source document and page.

**Independent of the SFDA.** The name contains "SFDA"; the product is not affiliated with,
endorsed by, or operated by the Saudi Food and Drug Authority.

---

## Features

- **Streaming answers** — tokens arrive as the model writes them, over SSE, with visible
  retrieval stages rather than an undifferentiated spinner
- **Traceable citations** — every claim carries a numbered marker resolving to the source
  document, its page, and the hybrid relevance figures behind it
- **Hybrid retrieval** — FAISS semantic search fused 0.5/0.5 with TF-IDF lexical search,
  over four categories of official SFDA guidelines
- **Bilingual EN/AR** with structural RTL, including Arabic questions answered in Arabic
- **Durable conversations** — history persists per reader in Postgres; `/c/<uuid>` is the
  address of a conversation, shareable and per-tab by construction
- **Accounts** — a `/account` page for identity, preferences, password and email changes,
  "sign out everywhere else", conversation export and bulk deletion
- **Admin console** — `/admin`: a searchable, paged People list, per-account detail, and an
  audit log of every privileged action
- **FAQ rail** — categorized starter questions, sharing the sidebar with the conversation list
- **Light/dark theme** stored as a reader preference, with system-preference detection
- **Rate limiting** per endpoint, protecting a single-worker deployment

---

## Getting started

### Prerequisites

- **Python 3.12** — the version CI tests against (`.github/workflows/tests.yml`)
- A **Supabase** project
- An **OpenAI** API key (optional for local work — see the demo mode below)

**There is no Node.js requirement and no frontend build step.** `package.json` exists only
so `npm audit` covers the four libraries the browser loads from a CDN. There is no `build`
script; do not look for one.

### Install and run

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # then fill in real values

python web/api/app.py           # host and port come from web/config.yaml
```

Open <http://localhost:5001>.

### Without an API key

`?testing=true` serves the complete experience — streaming, sources, citations — against
mock services, with no OpenAI key and no built index:

```bash
FLASK_TESTING=true python web/api/app.py
# http://localhost:5001/?testing=true
# Arabic: http://localhost:5001/?lang=ar&testing=true
```

### Supabase

Apply the schema from `supabase/migrations/`. **Read
[`supabase/README.md`](supabase/README.md) first** — migrations are applied through the
Supabase MCP `apply_migration` tool, there is no CLI in this project, and the filename
convention is load-bearing.

For a deployment that sends signup or recovery mail, configure custom SMTP: the built-in
sender is capped at 2 emails/hour. See [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

---

## Running in production

Answers stream over Server-Sent Events, which imposes two requirements. Both are explained
in full in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

**One worker.** The in-RAM FAISS index and the sentence-transformers model require it, and
the prompt-window cache and in-flight-generation lock are process-local:

```bash
gunicorn --workers 1 --threads 8 --timeout 300 "web.api.app:create_app()"
```

The app logs a warning at startup if `WEB_CONCURRENCY` is not `1`.

**Do not buffer the stream.** nginx buffers proxied responses by default, which would hold
each answer until it completed. The app sends `X-Accel-Buffering: no`; set it explicitly too:

```nginx
location /api/chat/stream {
    proxy_pass http://127.0.0.1:5001;
    proxy_buffering off;
    proxy_read_timeout 300s;
    gzip off;
}
```

---

## Project structure

```
sfda-copilot/
├── README.md               # this file
├── CLAUDE.md               # working agreement: which doc wins, and the rules that bite
├── DESIGN.md               # the design system: tokens, components, the RTL contract
├── TODO.md                 # open bugs and planned work, each with the cost of fixing it
├── requirements.txt        # runtime dependencies
├── requirements-dev.txt    # test tooling
├── package.json            # npm audit surface only — no bundler, no node_modules
├── pytest.ini              # the only Python tool config; there is no linter configured
├── faq.yaml                # FAQ categories and starter questions
├── .env.example            # the required environment variables
├── docs/
│   ├── ARCHITECTURE.md     # the live system contract, and which document wins
│   ├── PRODUCT.md          # what the product is for, and the rules copy is judged against
│   ├── OPERATIONS.md       # state this repo cannot hold: DNS, SMTP, dashboard config
│   ├── citation-eval-judge-protocol.md
│   └── archive/            # finished plans, frozen — history, not instructions
├── static/
│   ├── css/                # tokens → base → components → robot → effects, + admin, account
│   └── js/
│       ├── app.js          # reader entry point (landing + chat shell)
│       ├── account.js      # /account entry point
│       ├── admin.js        # /admin entry point
│       ├── privacy.js      # /privacy entry point
│       ├── modules/        # shared reader layer (18 modules)
│       ├── account/        # ui, handlers
│       └── admin/          # services, ui, handlers
├── web/
│   ├── config.yaml         # runtime config: models, rate limits, search engine
│   ├── api/
│   │   ├── app.py          # app factory, auth middleware, chat/SSE routes
│   │   ├── auth.py         # signup / login / logout / recovery
│   │   ├── account.py      # /account page, export, bulk conversation deletion
│   │   └── admin.py        # console: people, account detail, audit, settings
│   ├── services/           # search, LLM, citations, chat store, admin store, audit, eval
│   ├── utils/              # config, i18n, icons, Supabase and embedding clients
│   ├── i18n/               # en.yaml / ar.yaml — both must stay in step
│   ├── templates/          # index, account, admin, privacy + partials/_sidebar.html
│   └── tests/              # 40+ files; the only place project rules are mechanically enforced
├── supabase/
│   ├── README.md           # migration rules, the RPC contract, current schema shape
│   └── migrations/         # one .sql per applied migration + 0000_baseline.md
├── scripts/                # eval_citations.py, eval_retrieval.py, smoke_real.py
└── data/                   # the guideline corpus, one directory per category
```

**Three separate JS module directories is a security boundary, not tidiness** — the landing
page inlines an import-map entry for every filename in its own directory, so a console
module placed beside the reader's would publish the operator surface to anonymous visitors.
`test_frontend_architecture.py` enforces the separation.

For architecture boundaries — the search engine's internal split, the embedding factory, the
frontend layering, the two database access patterns — see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Testing

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

```bash
# fast backend suite (what CI gates on)
python -m pytest -m "not browser and not integration"

# browser suite — pytest starts an ephemeral Flask server from web/tests/conftest.py
python -m pytest -m browser --browser chromium

# tests needing generated artifacts or external services
python -m pytest -m integration

# coverage
python -m pytest -m "not browser and not integration" --cov=web
```

**This project has no linter.** No ruff, no eslint, no pre-commit. Every enforced rule is a
pytest assertion, and they are listed with their thresholds in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#what-is-mechanically-enforced). The ones most
likely to catch you:

| Test                            | What it will not let you do                                                         |
| ------------------------------- | ----------------------------------------------------------------------------------- |
| `test_css_contract.py`          | Author a physical CSS property that cannot mirror under RTL                         |
| `test_frontend_architecture.py` | Cross a module boundary, hardcode a UI string, or let Arabic lag English by one key |
| `test_composer.py`              | Ship an icon webfont, or a module URL without the current `ASSET_VERSION`           |
| `test_admin_page.py`            | Add a new top-level `runtime.*` string namespace                                    |
| `test_deep_link_contract.py`    | Make `/c/<uuid>` reveal whether a conversation exists                               |

**Bump `ASSET_VERSION` in `web/api/app.py` in any commit touching CSS or JS.**

### Smoke check against the real stack

The suite mocks OpenAI and the search index, so it cannot tell you whether the model still
cites correctly against the real corpus. After changing retrieval, the prompt, or the
citation format:

```bash
python scripts/smoke_real.py
python scripts/smoke_real.py "ما هي متطلبات تسجيل الأدوية؟" ar
```

It makes real API calls and reports time to first token, whether any citation index fell
outside the retrieved set, and whether the model reverted to the old prose citation format.

---

## Configuration

[`.env.example`](.env.example) is the version-controlled list of what a deployment must
provide:

```env
OPENAI_API_KEY=sk-...
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_PROJECT_REF=...
FLASK_SECRET_KEY=...
PUBLIC_BASE_URL=http://127.0.0.1:5001    # recovery links point here
BEHIND_PROXY=false
ARCHIVE_OWNER_SALT=                       # leave unset — see below
ARCHIVE_SESSION_SALT=                     # leave unset — see below
```

Also read, all optional:

| Variable                | Effect                                                                                                                                                                            |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SUPABASE_SECRET_KEY`   | Enables the `/admin` console. Without it every reader resolves as a non-administrator, which is a safe and supported way to deploy. Legacy fallback: `SUPABASE_SERVICE_ROLE_KEY`. |
| `DEBUG`, `LOG_LEVEL`    | Defaults `false`, `INFO`                                                                                                                                                          |
| `WEB_CONCURRENCY`       | Must be `1`; the app warns otherwise                                                                                                                                              |
| `FLASK_TESTING`         | Enables the mock-service demo path                                                                                                                                                |
| `SUPABASE_AUTH_TIMEOUT` | Seconds; default 5                                                                                                                                                                |

**The archive salts are deliberately unset.** Setting either turns on the training archive,
and `web/config.yaml`'s `archive_disclosed` guard logs a loud startup error if they are set
while the reader-facing notice still says nothing. Do not set them without reading that
guard.

There is no `FLASK_ENV`, `FLASK_DEBUG`, plain `SECRET_KEY`, or `DATABASE_URL` — none are read
anywhere. If an older `.env` has them, they are dead weight.

Everything else — models, rate limits, search engine parameters, CORS origins — lives in
`web/config.yaml`, with `app_settings` in Postgres able to override a subset at runtime.

### FAQ configuration

Edit `faq.yaml`:

```yaml
en:
  regulatory:
    title: 'Regulatory Guidelines'
    questions:
      - short: 'Drug Registration'
        text: 'What are the requirements for drug registration in Saudi Arabia?'
```

There is **no `icon:` field**. Each category's glyph is derived from its key by
`CATEGORY_ICONS` in `web/utils/icons.py`, which is also what the composer's scope selector
reads — so a category cannot wear one mark in the sidebar and a different one in the
composer. Adding a category means adding it there too.

---

## Documentation

Every document in this repository opens with a `STATUS:` line and a date. A file without one
is not finished; a file with an old date is one to check before you trust it.

`DESIGN.md` and `TODO.md` stay at the root — the design tooling reads `DESIGN.md` from
there, and `TODO.md` is the most actively edited file in the project.

| Document                                                                     | What it covers                                                                                                                                                                                 |
| ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [CLAUDE.md](CLAUDE.md)                                                       | The working agreement: where the rules live, the ones you will trip over, and how to write a `TODO.md` entry or archive a finished plan                                                        |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)                                 | The live system contract: the URL-as-pointer model, single worker, no bundler, the two database access patterns, what is mechanically enforced — **and which document wins when two disagree** |
| [DESIGN.md](DESIGN.md)                                                       | The design system. Every rule tagged `[GATE]`, `[CORRECTNESS]` or `[TASTE]`                                                                                                                    |
| [docs/PRODUCT.md](docs/PRODUCT.md)                                           | What the product is for, its terminology, and the brand commitments copy is held to                                                                                                            |
| [supabase/README.md](supabase/README.md)                                     | Migration rules, the RPC contract, and the current shape of `public`                                                                                                                           |
| [docs/OPERATIONS.md](docs/OPERATIONS.md)                                     | State this repository cannot hold — DNS, SMTP, dashboard configuration                                                                                                                         |
| [docs/citation-eval-judge-protocol.md](docs/citation-eval-judge-protocol.md) | The human-judge protocol gating a second model provider                                                                                                                                        |
| [TODO.md](TODO.md)                                                           | Open bugs and planned work, each with the cost of fixing it                                                                                                                                    |
| [docs/archive/README.md](docs/archive/README.md)                             | Index of finished plans and resolved TODO entries — what each decided and what it reversed. **History, not instructions**                                                                      |

**Before your first migration or your first RTL component**, read
[_Rules that collide_](docs/ARCHITECTURE.md#rules-that-collide) — eight places where two
individually correct rules meet badly, each of which has cost someone a session.

---

## Contributing

**Start with [`CLAUDE.md`](CLAUDE.md)** — the working agreement: which document is
authoritative for what, and the eight rules newcomers trip over. It is written for AI
agents and human contributors alike.

Branch, make the change, add tests for it, and make sure `python -m pytest` is as green as
you found it.

**Fix the documentation your change makes wrong, in the same commit.** Specifically:

- Closing a `TODO.md` entry means adding a dated closing note, moving the whole entry to
  `docs/archive/TODO-resolved.md`, and deleting its line from _Open now_ — not striking it
  through in place. The template and the full procedure are in
  [TODO.md → How this file works](TODO.md#how-this-file-works).
- Finishing a plan means archiving it with a `STATUS: HISTORICAL RECORD` banner, and
  lifting anything still open into `TODO.md` first so it is not buried in history.
- A new document gets a `STATUS:` line and a date on its first line, and lives in `docs/`.

---

## Troubleshooting

**Streaming stalls or arrives all at once** — a proxy is buffering. See _Running in
production_.

**Conversations appear to be shared between browser tabs** — that was the old cookie-based
pointer and it is gone; the URL is the pointer now. If you see it, the client is not
navigating. Check `static/js/modules/route.js`.

**Styles or scripts are stale after a deploy** — `ASSET_VERSION` was not bumped.

**Authentication fails** — verify the Supabase credentials in `.env` and that the project is
reachable. Note that a Supabase outage is deliberately reported as a 503 and must not sign
anyone out; a 401 means a genuinely rejected credential.

**Arabic layout looks wrong but the test suite is green** — `test_css_contract.py` only
scans this repository's CSS, and the templates load the LTR Bootstrap build. See the note
under _The Logical-Properties Rule_ in `DESIGN.md`.

---

## License

MIT — see [LICENSE](web/LICENSE).

## Credits

**Mohamed Fouda** — lead developer and designer.

Built on Bootstrap, Supabase and OpenAI. Guideline content is published by the Saudi Food
and Drug Authority, which is not affiliated with this project.
