import yaml
import os
from dotenv import load_dotenv
from typing import Any, Optional, Union

# Get project root directory (two levels up from this file)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env file from project root to get potential overrides like API keys
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

class ConfigLoader:
    """Loads configuration from config.yaml and provides access to settings."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        """Implement Singleton pattern to ensure only one config instance."""
        if not cls._instance:
            cls._instance = super(ConfigLoader, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_filename="config.yaml"):
        """Initialize the ConfigLoader, loading the YAML file relative to the 'web' directory."""
        if self._initialized:
            return

        # Construct the path relative to this file's parent directory ('web')
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # Should point to 'web' directory
        self.config_path = os.path.join(base_dir, config_filename)
        
        self.config = {}
        self._load_config()
        self._apply_env_overrides()
        self._initialized = True

    def _load_config(self):
        """Load the YAML configuration file."""
        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)
            if not isinstance(self.config, dict):
                print(f"Warning: Config file '{self.config_path}' is empty or invalid. Using defaults.")
                self.config = {}
        except FileNotFoundError:
            print(f"Warning: Config file '{self.config_path}' not found. Using defaults.")
            self.config = {}
        except yaml.YAMLError as e:
            print(f"Error parsing YAML file '{self.config_path}': {e}. Using defaults.")
            self.config = {}

    def _get_and_convert(self, section: str, key: str, default: Any, target_type: type, min_val: Optional[Union[int, float]] = None, max_val: Optional[Union[int, float]] = None) -> Any:
        """
        Safely retrieves a configuration value, converts it to the target type,
        and validates it against optional min/max values.
        Logs a warning and returns the default if conversion or validation fails.
        """
        env_var_name = key.upper() # Simple conversion for common env var naming
        
        # Get value from environment variable first, then from config, then use provided default
        value_from_env = os.getenv(env_var_name)
        value_from_config = self.config.get(section, {}).get(key)
        
        raw_value = value_from_env if value_from_env is not None else value_from_config
        
        if raw_value is None:
            return default # No value found, return default immediately

        try:
            converted_value = target_type(raw_value)
            
            # Apply validation if min_val or max_val are provided
            if min_val is not None and converted_value < min_val:
                print(f"Warning: Config '{section}.{key}' ({raw_value}) is below minimum allowed value ({min_val}). Using default: {default}")
                return default
            if max_val is not None and converted_value > max_val:
                print(f"Warning: Config '{section}.{key}' ({raw_value}) is above maximum allowed value ({max_val}). Using default: {default}")
                return default
                
            return converted_value
        except (ValueError, TypeError):
            print(f"Warning: Invalid type for config '{section}.{key}' ('{raw_value}'). Expected {target_type.__name__}. Using default: {default}")
            return default

    def _apply_env_overrides(self):
        """Override config values with environment variables if they exist, with safe conversion."""
        # OpenAI settings
        self.config.setdefault("openai", {})
        self.config["openai"]["api_key"] = os.getenv("OPENAI_API_KEY", self.config["openai"].get("api_key"))
        self.config["openai"]["model"] = os.getenv("OPENAI_MODEL", self.config["openai"].get("model", "gpt-4o-mini"))
        self.config["openai"]["max_tokens"] = self._get_and_convert("openai", "max_tokens", 10000, int, min_val=1)
        self.config["openai"]["temperature"] = self._get_and_convert("openai", "temperature", 0.7, float, min_val=0.0, max_val=2.0)

        # Search Engine settings
        self.config.setdefault("search_engine", {})
        self.config["search_engine"]["k"] = self._get_and_convert("search_engine", "k", 3, int, min_val=1)
        self.config["search_engine"]["semantic_multiplier"] = self._get_and_convert("search_engine", "semantic_multiplier", 2, int, min_val=1)
        self.config["search_engine"]["lexical_multiplier"] = self._get_and_convert("search_engine", "lexical_multiplier", 2, int, min_val=1)
        self.config["search_engine"]["embedding_model"] = os.getenv("EMBEDDING_MODEL", self.config["search_engine"].get("embedding_model", "text-embedding-ada-002"))
        self.config["search_engine"]["embedding_dimension"] = self._get_and_convert("search_engine", "embedding_dimension", 1536, int, min_val=1)
        self.config["search_engine"]["semantic_weight"] = self._get_and_convert("search_engine", "semantic_weight", 0.7, float, min_val=0.0, max_val=1.0)
        self.config["search_engine"]["lexical_weight"] = self._get_and_convert("search_engine", "lexical_weight", 0.3, float, min_val=0.0, max_val=1.0)

        # Data Processing settings
        self.config.setdefault("data_processing", {})
        self.config["data_processing"]["chunk_size"] = self._get_and_convert("data_processing", "chunk_size", 1000, int, min_val=1)
        self.config["data_processing"]["chunk_overlap"] = self._get_and_convert("data_processing", "chunk_overlap", 200, int, min_val=0)
        self.config["data_processing"]["embedding_batch_size"] = self._get_and_convert("data_processing", "embedding_batch_size", 100, int, min_val=1)

        # Server settings
        self.config.setdefault("server", {})
        self.config["server"]["port"] = self._get_and_convert("server", "port", 5000, int, min_val=1, max_val=65535)
        # For boolean, we still use the existing logic as it's robust for string to bool conversion
        self.config["server"]["debug"] = os.getenv("DEBUG", str(self.config["server"].get("debug", True))).lower() in ('true', '1', 't', 'yes', 'y')
        self.config["server"]["chat_history_length"] = self._get_and_convert("server", "chat_history_length", 5, int, min_val=1)
        self.config["server"]["allowed_origins"] = os.getenv("ALLOWED_ORIGINS", self.config["server"].get("allowed_origins", [])).split(',') if isinstance(os.getenv("ALLOWED_ORIGINS", self.config["server"].get("allowed_origins", [])), str) else self.config["server"].get("allowed_origins", [])
        self.config["server"]["rate_limit"] = {
            "per_day": self._get_and_convert("server", "rate_limit_per_day", 200, int, min_val=1),
            "per_hour": self._get_and_convert("server", "rate_limit_per_hour", 50, int, min_val=1),
            "per_minute": self._get_and_convert("server", "rate_limit_per_minute", 10, int, min_val=1),
            "chat_api": os.getenv("RATE_LIMIT_CHAT_API", self.config["server"].get("rate_limit", {}).get("chat_api", "10 per minute"))
        }

        # Supabase settings (ensure env vars override YAML placeholders)
        self.config.setdefault("supabase", {})
        self.config["supabase"]["url"] = os.getenv("SUPABASE_URL", self.config["supabase"].get("url"))
        self.config["supabase"]["key"] = os.getenv("SUPABASE_ANON_KEY", self.config["supabase"].get("key"))

        # Embedding configuration section - standardized for all embedding providers
        self.config.setdefault("embedding", {})
        self.config["embedding"]["dimensions"] = {
            "openai": 1536,
            "local": 768,
            "voyage": 1024,
            "cohere": 768
        }
        
        # Standardize embedding type key across the application
        self.config.setdefault("search_engine", {})
        self.config["search_engine"]["embedding_type"] = os.getenv(
            "EMBEDDING_TYPE",
            self.config["search_engine"].get("embedding_type", "local")
        )
        
        # Add validation schema configuration
        self.config.setdefault("validation", {})
        self.config["validation"]["strict_mode"] = os.getenv("STRICT_CONFIG", "false").lower() == "true"

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get a configuration value from a specific section."""
        return self.config.get(section, {}).get(key, default)

    def get_section(self, section, default=None):
        """Get an entire configuration section."""
        return self.config.get(section, default if default is not None else {})

# Create a single instance of the config loader for the application to use
config = ConfigLoader()

# Example usage (can be imported in other modules):
# from config_loader import config
# print(config.get("openai", "model"))
# print(config.get_section("search_engine"))
