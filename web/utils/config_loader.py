import yaml
import os
from dotenv import load_dotenv

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

    def _apply_env_overrides(self):
        """Override config values with environment variables if they exist."""
        # Example: OPENAI_API_KEY overrides openai.api_key (if it were in YAML)
        # Note: Sensitive keys like API keys should ideally *only* come from .env
        self.config.setdefault("openai", {})
        self.config["openai"]["api_key"] = os.getenv("OPENAI_API_KEY", self.config["openai"].get("api_key"))

        # Override other values if corresponding env vars are set
        # OpenAI settings
        self.config["openai"]["model"] = os.getenv("OPENAI_MODEL", self.config["openai"].get("model", "gpt-4o-mini"))
        self.config["openai"]["max_tokens"] = int(os.getenv("MAX_TOKENS", self.config["openai"].get("max_tokens", 1000)))
        self.config["openai"]["temperature"] = float(os.getenv("TEMPERATURE", self.config["openai"].get("temperature", 0.7)))

        # Search Engine settings
        self.config.setdefault("search_engine", {})
        self.config["search_engine"]["k"] = int(os.getenv("SEARCH_K", self.config["search_engine"].get("k", 3)))
        self.config["search_engine"]["semantic_multiplier"] = int(os.getenv("SEMANTIC_MULTIPLIER", self.config["search_engine"].get("semantic_multiplier", 2)))
        self.config["search_engine"]["lexical_multiplier"] = int(os.getenv("LEXICAL_MULTIPLIER", self.config["search_engine"].get("lexical_multiplier", 2)))
        self.config["search_engine"]["embedding_model"] = os.getenv("EMBEDDING_MODEL", self.config["search_engine"].get("embedding_model", "text-embedding-ada-002"))
        self.config["search_engine"]["embedding_dimension"] = int(os.getenv("EMBEDDING_DIMENSION", self.config["search_engine"].get("embedding_dimension", 1536)))

        # Data Processing settings
        self.config.setdefault("data_processing", {})
        self.config["data_processing"]["chunk_size"] = int(os.getenv("CHUNK_SIZE", self.config["data_processing"].get("chunk_size", 1000)))
        self.config["data_processing"]["chunk_overlap"] = int(os.getenv("CHUNK_OVERLAP", self.config["data_processing"].get("chunk_overlap", 200)))
        self.config["data_processing"]["embedding_batch_size"] = int(os.getenv("EMBEDDING_BATCH_SIZE", self.config["data_processing"].get("embedding_batch_size", 100)))

        # Server settings
        self.config.setdefault("server", {})
        self.config["server"]["port"] = int(os.getenv("PORT", self.config["server"].get("port", 5000)))
        self.config["server"]["debug"] = os.getenv("DEBUG", str(self.config["server"].get("debug", True))).lower() in ('true', '1', 't', 'yes', 'y')

        # Supabase settings (ensure env vars override YAML placeholders)
        self.config.setdefault("supabase", {})
        self.config["supabase"]["url"] = os.getenv("SUPABASE_URL", self.config["supabase"].get("url"))
        self.config["supabase"]["key"] = os.getenv("SUPABASE_KEY", self.config["supabase"].get("key"))


    def get(self, section, key, default=None):
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
