# SFDA Copilot

An AI-powered regulatory guidance system for pharmaceutical regulations in Saudi Arabia, built with Flask, Supabase, and modern web technologies.

## 🌟 Features

- **Streaming answers**: tokens arrive as the model writes them, over SSE
- **Traceable citations**: every claim carries a numbered marker that resolves
  to the source document, page, and its hybrid relevance score — the
  semantic/lexical split included
- **Hybrid retrieval**: FAISS semantic search fused with TF-IDF lexical search
  over 112 official SFDA guidelines
- **Bilingual EN/AR** with full RTL, including Arabic queries and answers
- **Comprehensive FAQ System**: Browse categorized regulatory guidelines
- **User Authentication**: Secure login/signup with Supabase, plus self-service
  password recovery (email link, works across devices)
- **Profile Management**: User profiles with theme preferences
- **Admin Console**: a `/admin` surface for operators — a searchable People
  list, a per-account detail view (identity, profile, role, chat access,
  send-password-reset), and an audit log of every privileged action, global
  and per-account
- **Rate Limiting**: per-IP request quotas protect the single-worker
  deployment from being overwhelmed
- **Dark/Light Theme**: Accessible theme toggle with system preference detection
- **Responsive Design**: Works seamlessly across desktop and mobile devices

## 🎨 Theme Toggle System

The SFDA Copilot application uses an **HTML-first approach** for theme toggles, ensuring better accessibility and maintainability.

### Features
- ✅ Light/dark theme support
- ✅ System preference detection
- ✅ User preference persistence
- ✅ Accessible toggle buttons with ARIA labels
- ✅ Bootstrap 5 integration with `data-bs-theme`
- ✅ Keyboard navigation support
- ✅ Screen reader compatibility

### Implementation Details

#### HTML Structure
Theme toggle buttons are defined directly in the HTML with proper accessibility attributes:

```html
<!-- Landing page theme toggle -->
<button
    id="landing-theme-toggle"
    class="theme-toggle-btn btn btn-sm"
    aria-label="Toggle theme between light and dark"
    title="Toggle theme between light and dark"
>
    <i class="bi bi-moon-fill"></i>
</button>

<!-- Sidebar theme toggle -->
<button
    id="sidebar-theme-toggle"
    class="theme-toggle-btn btn btn-sm"
    aria-label="Toggle theme between light and dark"
    title="Toggle theme between light and dark"
>
    <i class="bi bi-moon-fill"></i>
</button>

<!-- Offcanvas theme toggle -->
<button
    id="offcanvas-theme-toggle"
    class="theme-toggle-btn btn btn-sm"
    aria-label="Toggle theme between light and dark"
    title="Toggle theme between light and dark"
>
    <i class="bi bi-moon-fill"></i>
</button>
```

#### JavaScript Implementation
The theme system uses event delegation and DOMCache for optimal performance:

```javascript
// Event delegation for better performance
document.addEventListener('click', (e) => {
    if (e.target.closest('.theme-toggle-btn')) {
        e.preventDefault();
        toggleTheme();
    }
});

// Keyboard navigation support
document.addEventListener('keydown', (e) => {
    if (e.target.closest('.theme-toggle-btn') && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault();
        toggleTheme();
    }
});
```

#### Theme Persistence
- Uses Bootstrap 5's native `data-bs-theme` attribute
- Stores preference in localStorage
- Respects system color scheme preference
- Synchronizes across all toggle buttons

### Accessibility Features
- **ARIA Labels**: Clear descriptions for screen readers
- **Keyboard Navigation**: Full keyboard accessibility with Enter and Space keys
- **Focus Management**: Proper focus handling during theme changes
- **Screen Reader Announcements**: Theme change notifications
- **High Contrast**: Maintains readability in both themes

## 🚀 Getting Started

### Prerequisites
- Python 3.12 (the version CI tests against — see `.github/workflows/tests.yml`)
- Node.js 16+
- Supabase account

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-username/sfda-copilot.git
   cd sfda-copilot
   ```

2. **Set up the backend**
   ```bash
   # Create virtual environment
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   
   # Install dependencies
   pip install -r requirements.txt
   
   # Set up environment variables
   cp .env.example .env
   # Edit .env with your Supabase credentials
   ```

3. **Set up the frontend**
   ```bash
   # Install Node.js dependencies
   npm install
   
   # Build frontend assets (if needed)
   npm run build
   ```

4. **Configure Supabase**
   - Create a new Supabase project
   - Apply the schema from `supabase/migrations/` (see `supabase/README.md`)
   - Get your project URL and anon key
   - Update `.env` with your credentials
   - For a deployment that sends signup email, configure custom SMTP —
     the built-in sender is capped at 2 emails/hour. See
     [docs/SMTP_CONFIGURATION.md](docs/SMTP_CONFIGURATION.md)

5. **Run the application**
   ```bash
   # Start Flask development server (host/port come from web/config.yaml)
   python web/api/app.py

   # Open your browser to http://localhost:5001
   ```

   Without an OpenAI key or a built index, `?testing=true` serves a full
   working demo — streaming, sources and citations — against mock services:
   ```bash
   FLASK_TESTING=true python web/api/app.py
   # then open http://localhost:5001/?testing=true
   # Arabic:   http://localhost:5001/?lang=ar&testing=true
   ```

### Running in production

Chat answers stream over Server-Sent Events, which imposes two requirements.

**Single worker.** Conversation history lives in a process-local
`ConversationStore` (it cannot live in the session cookie — Flask writes
`Set-Cookie` before the WSGI server iterates a streaming body, so a session
write inside the generator is silently discarded). The in-RAM FAISS index and
sentence-transformers model already require this:

```bash
gunicorn --workers 1 --threads 8 --timeout 300 "web.api.app:create_app()"
```

Running more than one worker splits conversations across them; the app logs a
warning at startup if `WEB_CONCURRENCY` is not `1`.

**Do not buffer the stream.** nginx buffers proxied responses by default, which
would hold each answer until it completed and defeat streaming entirely. The
app sends `X-Accel-Buffering: no`, but set it explicitly too:

```nginx
location /api/chat/stream {
    proxy_pass http://127.0.0.1:5001;
    proxy_buffering off;
    proxy_read_timeout 300s;
    gzip off;
}
```

## 📁 Project Structure

```
sfda-copilot/
├── README.md                 # This file
├── requirements.txt          # Python dependencies
├── package.json             # Node.js dependencies
├── .env.example            # Environment variables template — the source of truth
├── faq.yaml                # FAQ data configuration
├── static/                 # Static frontend assets (no bundler, ES modules)
│   ├── css/                # Layered: tokens -> base -> components -> robot -> effects
│   │   ├── tokens.css      # Design tokens: primitives, scales, semantics
│   │   ├── base.css        # Reset, typography, app shell
│   │   ├── components.css  # Buttons, chat, citations, composer
│   │   ├── robot.css       # Mascot states
│   │   └── effects.css     # Motion + shared keyframes
│   └── js/
│       ├── app.js          # Reader-facing entry point (chat shell)
│       ├── admin.js        # Admin console entry point
│       ├── modules/        # config, dom, state, services, ui, handlers,
│       │                   # citations, stream-render, i18n, robot, theme,
│       │                   # auth-view, source-panel, dropdown
│       └── admin/          # Admin console: services, ui, handlers
├── web/                    # Flask backend
│   ├── api/
│   │   ├── app.py          # App entry point, auth middleware, chat/SSE routes
│   │   ├── auth.py         # Signup / login / password-recovery routes
│   │   └── admin.py        # Admin console routes: people, account detail, audit
│   ├── i18n/              # en.yaml / ar.yaml UI catalogues
│   ├── services/          # Search, LLM, citations, SSE, conversation store,
│   │                       # admin store, audit log, account recovery
│   ├── utils/             # Config loader, i18n loader, Supabase client
│   ├── templates/
│   │   ├── index.html     # Reader-facing template (landing / chat / recovery views)
│   │   ├── admin.html     # Admin console template
│   │   └── partials/      # Jinja macros (sidebar)
│   └── tests/             # Test files
├── supabase/
│   ├── migrations/        # Schema, RLS policies, RPCs (SQL)
│   └── README.md          # Migration conventions
├── data/                  # Regulatory guideline data
│   ├── regulatory/
│   ├── pharmacovigilance/
│   ├── Veterinary_Medicines/
│   └── Biological_Products_and_Quality_Control/
└── memory-bank/           # Project documentation and notes
```

### Architecture Boundaries

- `SearchEngine` composes the index, query processor, semantic search,
  TF-IDF lexical search, and result combiner. Those search responsibilities
  remain separate by design.
- `web.utils.embedding_helpers` is the only embedding-provider factory.
  Provider initialization fails clearly rather than switching vector spaces
  behind an existing FAISS index.
- Frontend `Services` owns only Supabase and HTTP operations. Event handlers
  own user-facing recovery, `state.js` owns runtime state, and `auth-view.js`
  owns authenticated/unauthenticated view transitions.

## 🧪 Testing

### Install Development Test Tools

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

### Running Tests

```bash
# Fast backend suite
python -m pytest -m "not browser and not integration"

# Browser suite (pytest starts an ephemeral Flask test server)
python -m pytest -m browser --browser chromium

# Integration tests requiring generated artifacts or external services
python -m pytest -m integration

# Backend coverage
python -m pytest -m "not browser and not integration" --cov=web
```

### Smoke check against the real stack

The suite mocks OpenAI and the search index, so it cannot tell you whether the
model still cites correctly against the real corpus. After changing retrieval,
the prompt, or the citation format, run:

```bash
python scripts/smoke_real.py
python scripts/smoke_real.py "ما هي متطلبات تسجيل الأدوية؟" ar
```

It makes real API calls (a few cents on gpt-4o-mini) and reports time to first
token, whether any citation index fell outside the retrieved set, and whether
the model reverted to the old prose citation format.

Playwright starts an ephemeral Flask test server from `web/tests/conftest.py`.
GitHub Actions installs Chromium and runs the browser suite as a separate
merge gate.

### Test Coverage
- **Chat API** (`test_chat_api.py`): the blocking `/api/chat` route end to end
- **Streaming** (`test_chat_stream.py`): SSE frame ordering, in-band errors,
  history persistence across a streamed response, and the conversation store
- **Citations** (`test_citations.py`): source payload coercion (numpy scalars
  and NaN would otherwise 500 the endpoint) and legacy-citation normalisation
- **CSS contract** (`test_css_contract.py`): fails on physical properties that
  cannot mirror under RTL
- **Architecture** (`test_frontend_architecture.py`): module boundaries, plus
  the frozen English strings the browser suite asserts verbatim
- **Theme / Profile / Frontend**: browser-level flows via Playwright

## 🔧 Configuration

### Environment Variables

[`.env.example`](.env.example) is the version-controlled, authoritative list —
copy it and fill in real values (`cp .env.example .env`). The variables the
code actually reads:

```env
# Required
OPENAI_API_KEY=sk-your-openai-api-key-here
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_ANON_KEY=your-supabase-anon-key
SUPABASE_PROJECT_REF=your-project-ref
FLASK_SECRET_KEY=generate-a-secure-random-string-here

# Required for password-recovery links to point at the right place
PUBLIC_BASE_URL=http://127.0.0.1:5001

# Optional — enables the /admin console. Without it every reader resolves as
# a non-administrator, which is a safe and supported way to deploy.
SUPABASE_SECRET_KEY=sb_secret_...   # legacy fallback: SUPABASE_SERVICE_ROLE_KEY

# Optional, sensible defaults
BEHIND_PROXY=false
DEBUG=false
LOG_LEVEL=INFO
WEB_CONCURRENCY=1
FLASK_TESTING=false
SUPABASE_AUTH_TIMEOUT=5
```

There is no `FLASK_ENV`, `FLASK_DEBUG`, plain `SECRET_KEY`, or `DATABASE_URL`
— none of those are read anywhere in the app. If an older `.env` in your
checkout has them, they're dead weight and safe to delete.

### FAQ Configuration
Edit `faq.yaml` to customize the FAQ categories and questions:

```yaml
en:
  regulatory:
    title: "Regulatory Guidelines"
    questions:
      - short: "Drug Registration"
        text: "What are the requirements for drug registration in Saudi Arabia?"
ar:
  regulatory:
    title: "الأسئلة الشائعة — التنظيمية"
    questions:
      - short: "تسجيل الأدوية"
        text: "ما هي متطلبات تسجيل الأدوية في المملكة العربية السعودية؟"
```

There is no `icon:` field. Each category's glyph is derived from its key by
`CATEGORY_ICONS` in `web/utils/icons.py`, which is also what the composer's
scope selector reads — so a category cannot wear one mark in the sidebar and a
different one in the composer. Adding a category means adding it there too.

## 📚 Documentation

Design intent and product principles live at the repository root; anything under
`docs/` records **state that this repository cannot tell you** — configuration
that lives in a third-party dashboard, in DNS, or in the Supabase project.

| Document | What it covers |
|---|---|
| [PRODUCT.md](PRODUCT.md) | What the product is for, and the principles a change is judged against |
| [DESIGN.md](DESIGN.md) | The design system: tokens, components, and the RTL contract |
| [TODO.md](TODO.md) | Known bugs and planned work, each with the cost of fixing it |
| [supabase/README.md](supabase/README.md) | Migration conventions and how schema changes are applied |
| [docs/SMTP_CONFIGURATION.md](docs/SMTP_CONFIGURATION.md) | Transactional email: why the built-in sender failed, the Resend SMTP and DNS setup, and how to verify delivery |

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass (`python -m pytest`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

### Development Guidelines
- Follow the existing code style and patterns
- Write comprehensive tests for new features
- Update documentation for significant changes
- Ensure accessibility compliance
- Test across different browsers and devices

## 📝 Changelog

### Recent Updates (2026-08)
- **Admin Console**: a searchable People list, a per-account detail view
  (identity, profile, role, chat access, send-password-reset), and an audit
  log — global and per-account — for every privileged action
- **Password Recovery**: self-service reader-facing reset and an
  admin-triggered "send reset" action, both landing on the same recovery view
- **Auth Hardening**: a Supabase/GoTrue outage is now reported as a 503
  rather than mistaken for a bad credential, and no longer signs an
  administrator out of a valid session
- **Bilingual Error Messages**: signup rate-limit and recovery errors reach
  readers in their own language instead of raw English

See [TODO.md](TODO.md) for what's still open, and the cost of fixing it.

### Earlier Updates
- **Theme Toggle Refactoring**: Implemented HTML-first approach with improved accessibility
- **Profile Integration**: Enhanced theme preference synchronization with user profiles
- **Testing Suite**: Added comprehensive tests for theme toggle functionality
- **Documentation**: Updated all documentation with new implementation details

### Version History
- **v2.0.0**: Complete theme toggle refactoring with accessibility improvements
- **v1.0.0**: Initial release with basic functionality

## 🐛 Troubleshooting

### Common Issues

**Theme Toggle Not Working**
- Check that JavaScript is enabled in your browser
- Clear browser cache and localStorage
- Verify that all theme toggle buttons have the correct `class="theme-toggle-btn"` attribute
- Check browser console for JavaScript errors

**Authentication Issues**
- Verify Supabase credentials in `.env` file
- Ensure Supabase project is properly configured
- Check network connectivity to Supabase services

**Mobile Responsiveness**
- Test on actual devices, not just browser dev tools
- Check viewport meta tag settings
- Verify CSS media queries are working correctly

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](web/LICENSE) file for details.

## 👥 Team

- **Mohamed Fouda** - Lead Developer & Designer
- **SFDA Copilot Team** - Development & Testing

## 🙏 Acknowledgments

- Saudi Food and Drug Authority (SFDA) for regulatory guidelines
- Bootstrap team for the excellent UI framework
- Supabase team for the backend-as-a-service platform
- OpenAI for AI capabilities

## 📞 Support

For support, please open an issue in the GitHub repository or contact the development team.

---

**Note**: This is a documentation file for the SFDA Copilot project. For the most up-to-date information, please refer to the project's GitHub repository and the latest code commits.
