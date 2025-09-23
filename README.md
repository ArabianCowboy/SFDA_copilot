# SFDA Copilot

An AI-powered regulatory guidance system for pharmaceutical regulations in Saudi Arabia, built with Flask, Supabase, and modern web technologies.

## 🌟 Features

- **AI-Powered Chat Interface**: Get intelligent answers about SFDA regulations
- **Comprehensive FAQ System**: Browse categorized regulatory guidelines
- **User Authentication**: Secure login/signup with Supabase
- **Profile Management**: User profiles with theme preferences
- **Dark/Light Theme**: Accessible theme toggle with system preference detection
- **Responsive Design**: Works seamlessly across desktop and mobile devices
- **Real-time Updates**: Live chat with typing indicators and suggested questions

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
    class="theme-toggle-btn btn btn-outline-secondary btn-sm ms-2"
    aria-label="Toggle theme between light and dark"
    title="Toggle theme between light and dark"
>
    <i class="bi bi-moon-fill"></i>
</button>

<!-- Sidebar theme toggle -->
<button
    id="sidebar-theme-toggle"
    class="theme-toggle-btn btn btn-outline-secondary btn-sm ms-2"
    aria-label="Toggle theme between light and dark"
    title="Toggle theme between light and dark"
>
    <i class="bi bi-moon-fill"></i>
</button>

<!-- Offcanvas theme toggle -->
<button
    id="offcanvas-theme-toggle"
    class="theme-toggle-btn btn btn-outline-secondary btn-sm ms-2"
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
   # Start Flask development server
   python web/app.py
   
   # Open your browser to http://localhost:5000
   ```

## 📁 Project Structure

```
sfda-copilot/
├── README.md                 # This file
├── requirements.txt          # Python dependencies
├── package.json             # Node.js dependencies
├── .env.example            # Environment variables template
├── faq.yaml                # FAQ data configuration
├── static/                 # Static frontend assets
│   ├── css/
│   │   └── style.css       # Custom CSS styles
│   ├── js/
│   │   └── app.js          # Main JavaScript application
│   └── images/             # Image assets
├── web/                    # Flask backend
│   ├── app.py             # Flask application entry point
│   ├── api/               # API endpoints
│   ├── services/          # Business logic services
│   ├── utils/             # Utility functions
│   ├── templates/         # HTML templates
│   │   └── index.html     # Main application template
│   └── tests/             # Test files
├── data/                  # Regulatory guideline data
│   ├── regulatory/
│   ├── pharmacovigilance/
│   ├── Veterinary_Medicines/
│   └── Biological_Products_and_Quality_Control/
└── memory-bank/           # Project documentation and notes
```

## 🧪 Testing

### Running Tests
```bash
# Run all tests
python -m pytest web/tests/

# Run specific test files
python -m pytest web/tests/test_theme_toggle.py
python -m pytest web/tests/test_profile_theme_integration.py

# Run with coverage
python -m pytest --cov=web web/tests/
```

### Test Coverage
- **Theme Toggle Tests**: Verify theme persistence, accessibility, and functionality
- **Profile Integration Tests**: Test theme preference synchronization with user profiles
- **Authentication Tests**: Test user authentication and session management
- **API Tests**: Test backend API endpoints

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
regulatory:
  title: "Regulatory Guidelines"
  icon: "bi-shield-check"
  questions:
    - short: "Drug Registration"
      text: "What are the requirements for drug registration in Saudi Arabia?"
```

## 📚 Documentation

### Component Documentation
- [SFDA Copilot Component Documentation](SFDA_Copilot_Component_Documentation.md)
- [SFDA Copilot Workflow Diagram](SFDA_Copilot_Workflow_Diagram.md)

### Theme Toggle Refactoring
- [Theme Toggle Refactoring Plan](THEME_TOGGLE_REFACTORING_PLAN.md)
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