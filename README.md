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
- **User Authentication**: Secure login/signup with Supabase
- **Profile Management**: User profiles with theme preferences
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
- Python 3.8+
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
   - Set up the database schema (see `web/migrations/`)
   - Get your project URL and anon key
   - Update `.env` with your credentials

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
├── .env.example            # Environment variables template
├── faq.yaml                # FAQ data configuration
├── static/                 # Static frontend assets (no bundler, ES modules)
│   ├── css/                # Layered: tokens -> base -> components -> robot -> effects
│   │   ├── tokens.css      # Design tokens: primitives, scales, semantics
│   │   ├── base.css        # Reset, typography, app shell
│   │   ├── components.css  # Buttons, chat, citations, composer
│   │   ├── robot.css       # Mascot states
│   │   └── effects.css     # Motion + shared keyframes
│   ├── js/
│   │   ├── app.js          # Entry point
│   │   └── modules/        # config, dom, state, services, ui, handlers,
│   │                       # citations, stream-render, i18n, robot, theme
│   └── images/             # Image assets
├── web/                    # Flask backend
│   ├── api/app.py         # Flask application entry point
│   ├── i18n/              # en.yaml / ar.yaml UI catalogues
│   ├── services/          # Search, LLM, citations, SSE, conversation store
│   ├── utils/             # Config loader, i18n loader, Supabase client
│   ├── templates/         # HTML templates
│   │   ├── index.html     # Main application template
│   │   └── partials/      # Jinja macros (sidebar)
│   └── tests/             # Test files
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
```env
# Supabase Configuration
SUPABASE_URL=your_supabase_project_url
SUPABASE_ANON_KEY=your_supabase_anon_key

# Flask Configuration
FLASK_ENV=development
FLASK_DEBUG=True
SECRET_KEY=your_secret_key

# Database Configuration (if not using Supabase)
DATABASE_URL=your_database_url
```

### FAQ Configuration
Edit `faq.yaml` to customize the FAQ categories and questions:

```yaml
en:
  regulatory:
    title: "Regulatory Guidelines"
    icon: "bi-shield-check"
    questions:
      - short: "Drug Registration"
        text: "What are the requirements for drug registration in Saudi Arabia?"
ar:
  regulatory:
    title: "الأسئلة الشائعة — التنظيمية"
    icon: "bi-shield-check"
    questions:
      - short: "تسجيل الأدوية"
        text: "ما هي متطلبات تسجيل الأدوية في المملكة العربية السعودية؟"
```

## 📚 Documentation

### Component Documentation

### Theme Toggle Refactoring
- Detailed implementation plan and technical specifications

### API Documentation
API endpoints are documented in the code with OpenAPI/Swagger annotations.

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

### Recent Updates
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
