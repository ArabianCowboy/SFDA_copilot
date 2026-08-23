"""
SFDA Copilot - Configuration Loader
====================================
Simple configuration loader that:
1. Loads settings from config.yaml (single source of truth for app behavior)
2. Loads secrets from environment variables (API keys, database URLs)

Usage:
    from web.utils.config_loader import config

    port = config.get("server", "port", 5001)
    openai_key = config.get_secret("OPENAI_API_KEY")
"""

import logging
import os
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

# Setup paths - exported for use by other modules
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = Path(__file__).resolve().parents[1]

# Backward compatibility export (lowercase)
project_root = str(PROJECT_ROOT)

# Load .env file from project root
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


class ConfigLoader:
    """
    Loads configuration from config.yaml and environment variables.

    Responsibilities:
    - config.yaml: Application behavior (ports, timeouts, feature flags)
    - Environment variables: Secrets (API keys, database URLs)
    """

    _instance: Optional["ConfigLoader"] = None
    _initialized: bool

    def __new__(cls) -> "ConfigLoader":
        """Singleton pattern - only one config instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self.config_path = WEB_DIR / "config.yaml"
        self._config: dict[str, Any] = {}
        self._load_config()
        self._initialized = True

        logging.debug("ConfigLoader initialized from %s", self.config_path)

    def _load_config(self) -> None:
        """Load the YAML configuration file."""
        try:
            with open(self.config_path, encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            logging.warning("Config file not found: %s. Using defaults.", self.config_path)
            self._config = {}
        except yaml.YAMLError as e:
            logging.error("Error parsing config.yaml: %s", e)
            self._config = {}

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """
        Get a configuration value from config.yaml.

        Args:
            section: The config section (e.g., "server", "openai")
            key: The key within the section
            default: Default value if not found

        Returns:
            The configuration value or default
        """
        return self._config.get(section, {}).get(key, default)

    def get_section(self, section: str, default: dict | None = None) -> dict[str, Any]:
        """Get an entire configuration section."""
        return self._config.get(section, default or {})

    def get_secret(self, key: str, default: str | None = None) -> str | None:
        """
        Get a secret from environment variables.

        This is the ONLY way to access secrets - they should never be in config.yaml.

        Args:
            key: Environment variable name (e.g., "OPENAI_API_KEY")
            default: Default value if not found

        Returns:
            The secret value or default
        """
        return os.getenv(key, default)

    def is_debug(self) -> bool:
        """Check if debug mode is enabled."""
        # Environment variable takes precedence for quick local override
        env_debug = os.getenv("DEBUG", "").lower()
        if env_debug in ("true", "1", "yes"):
            return True
        if env_debug in ("false", "0", "no"):
            return False
        return self.get("server", "debug", False)

    def is_behind_proxy(self) -> bool:
        """Check if running behind a reverse proxy."""
        return os.getenv("BEHIND_PROXY", "false").lower() == "true"

    @property
    def openai_api_key(self) -> str | None:
        """Get OpenAI API key from environment."""
        return self.get_secret("OPENAI_API_KEY")

    @property
    def supabase_url(self) -> str | None:
        """Get Supabase URL from environment."""
        return self.get_secret("SUPABASE_URL")

    @property
    def supabase_anon_key(self) -> str | None:
        """Get Supabase anonymous key from environment."""
        return self.get_secret("SUPABASE_ANON_KEY")

    @property
    def flask_secret_key(self) -> str:
        """Get Flask secret key from environment."""
        return self.get_secret("FLASK_SECRET_KEY") or ""


# Singleton instance for application use
config = ConfigLoader()
