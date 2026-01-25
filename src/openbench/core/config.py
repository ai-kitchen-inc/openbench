"""
Centralized Configuration Management for OpenBench.

Provides single source of truth for all configuration:
- YAML/JSON file loading with environment variable overrides
- Model definitions and settings
- Validation and type coercion
- Hierarchical config with dot notation access
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TypeVar, Union
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in config values."""
    if isinstance(value, str):
        # Match ${VAR} or ${VAR:-default} patterns
        pattern = r"\$\{([^}:]+)(?::-([^}]*))?\}"

        def replace(match):
            var_name = match.group(1)
            default = match.group(2) or ""
            return os.environ.get(var_name, default)

        return re.sub(pattern, replace, value)

    elif isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}

    elif isinstance(value, list):
        return [_expand_env_vars(item) for item in value]

    return value


@dataclass
class ModelInfo:
    """Information about an AI model."""

    name: str
    provider: str
    context_window: int = 128000
    max_output_tokens: int = 4096
    supports_vision: bool = False
    supports_tools: bool = True
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    aliases: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "provider": self.provider,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "supports_vision": self.supports_vision,
            "supports_tools": self.supports_tools,
            "cost_per_1k_input": self.cost_per_1k_input,
            "cost_per_1k_output": self.cost_per_1k_output,
            "aliases": self.aliases,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelInfo":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            provider=data["provider"],
            context_window=data.get("context_window", 128000),
            max_output_tokens=data.get("max_output_tokens", 4096),
            supports_vision=data.get("supports_vision", False),
            supports_tools=data.get("supports_tools", True),
            cost_per_1k_input=data.get("cost_per_1k_input", 0.0),
            cost_per_1k_output=data.get("cost_per_1k_output", 0.0),
            aliases=data.get("aliases", []),
        )


class Config:
    """
    Centralized configuration management.

    Features:
    - Load from YAML/JSON files
    - Environment variable expansion: ${VAR} or ${VAR:-default}
    - Dot notation access: config.get("llm.default_model")
    - Type-safe getters with defaults

    Example:
        >>> config = Config()
        >>> config.load("config.yaml")
        >>> model = config.get("llm.default_model", "gpt-4")
        >>> api_key = config.get("credentials.openai.api_key")
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """
        Initialize config.

        Args:
            data: Initial configuration data
        """
        self._data: Dict[str, Any] = data or {}
        self._models: Dict[str, ModelInfo] = {}

    def load(self, path: Union[str, Path]) -> "Config":
        """
        Load configuration from file.

        Supports YAML and JSON formats.
        Environment variables are expanded automatically.

        Args:
            path: Path to config file

        Returns:
            Self for chaining
        """
        path = Path(path)

        if not path.exists():
            logger.warning(f"Config file not found: {path}")
            return self

        content = path.read_text()

        if path.suffix in (".yaml", ".yml"):
            try:
                import yaml

                data = yaml.safe_load(content)
            except ImportError:
                raise ImportError("PyYAML required for YAML config files: pip install pyyaml")
        elif path.suffix == ".json":
            data = json.loads(content)
        else:
            raise ValueError(f"Unsupported config format: {path.suffix}")

        # Expand environment variables
        data = _expand_env_vars(data)

        # Merge with existing data
        self._merge(self._data, data)

        # Load models if present
        if "models" in data:
            for model_data in data["models"]:
                model = ModelInfo.from_dict(model_data)
                self._models[model.name] = model
                for alias in model.aliases:
                    self._models[alias] = model

        logger.debug(f"Loaded config from {path}")
        return self

    def load_env(self, prefix: str = "OPENBENCH_") -> "Config":
        """
        Load configuration from environment variables.

        Converts OPENBENCH_LLM_MODEL to llm.model.

        Args:
            prefix: Environment variable prefix

        Returns:
            Self for chaining
        """
        for key, value in os.environ.items():
            if key.startswith(prefix):
                # Convert OPENBENCH_LLM_MODEL to llm.model
                config_key = key[len(prefix) :].lower().replace("_", ".")
                self.set(config_key, value)

        return self

    def _merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> None:
        """Deep merge override into base."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge(base[key], value)
            else:
                base[key] = value

    def get(self, key: str, default: T = None) -> Union[Any, T]:
        """
        Get config value by dot-notation key.

        Args:
            key: Dot-separated key (e.g., "llm.default_model")
            default: Default value if not found

        Returns:
            Config value or default
        """
        parts = key.split(".")
        value = self._data

        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default

        return value

    def get_int(self, key: str, default: int = 0) -> int:
        """Get config value as integer."""
        value = self.get(key)
        if value is None:
            return default
        return int(value)

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get config value as float."""
        value = self.get(key)
        if value is None:
            return default
        return float(value)

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get config value as boolean."""
        value = self.get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    def get_list(self, key: str, default: Optional[List] = None) -> List:
        """Get config value as list."""
        value = self.get(key)
        if value is None:
            return default or []
        if isinstance(value, list):
            return value
        return [value]

    def set(self, key: str, value: Any) -> None:
        """
        Set config value by dot-notation key.

        Args:
            key: Dot-separated key
            value: Value to set
        """
        parts = key.split(".")
        data = self._data

        for part in parts[:-1]:
            if part not in data:
                data[part] = {}
            data = data[part]

        data[parts[-1]] = value

    def get_model(self, name: str) -> Optional[ModelInfo]:
        """
        Get model info by name or alias.

        Args:
            name: Model name or alias

        Returns:
            ModelInfo or None
        """
        return self._models.get(name)

    def register_model(self, model: ModelInfo) -> None:
        """
        Register a model.

        Args:
            model: Model info to register
        """
        self._models[model.name] = model
        for alias in model.aliases:
            self._models[alias] = model

    def list_models(self, provider: Optional[str] = None) -> List[ModelInfo]:
        """
        List registered models.

        Args:
            provider: Filter by provider

        Returns:
            List of unique models
        """
        # Use dict to dedupe by name
        unique = {m.name: m for m in self._models.values()}
        models = list(unique.values())

        if provider:
            models = [m for m in models if m.provider == provider]

        return models

    def to_dict(self) -> Dict[str, Any]:
        """Export config as dictionary."""
        data = dict(self._data)
        if self._models:
            # Only include unique models (not aliases)
            unique = {m.name: m for m in self._models.values()}
            data["models"] = [m.to_dict() for m in unique.values()]
        return data

    def save(self, path: Union[str, Path]) -> None:
        """
        Save configuration to file.

        Args:
            path: Output file path
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = self.to_dict()

        if path.suffix in (".yaml", ".yml"):
            try:
                import yaml

                content = yaml.dump(data, default_flow_style=False)
            except ImportError:
                raise ImportError("PyYAML required for YAML config files: pip install pyyaml")
        else:
            content = json.dumps(data, indent=2)

        path.write_text(content)
        logger.debug(f"Saved config to {path}")

    def __contains__(self, key: str) -> bool:
        """Check if key exists."""
        return self.get(key) is not None

    def __repr__(self) -> str:
        return f"Config(keys={list(self._data.keys())}, models={len(self._models)})"


# Default models registry
DEFAULT_MODELS = [
    ModelInfo(
        name="gpt-4o",
        provider="openai",
        context_window=128000,
        max_output_tokens=16384,
        supports_vision=True,
        supports_tools=True,
        cost_per_1k_input=0.0025,
        cost_per_1k_output=0.01,
        aliases=["gpt4o", "4o"],
    ),
    ModelInfo(
        name="gpt-4o-mini",
        provider="openai",
        context_window=128000,
        max_output_tokens=16384,
        supports_vision=True,
        supports_tools=True,
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
        aliases=["gpt4o-mini", "4o-mini"],
    ),
    ModelInfo(
        name="claude-3-5-sonnet-20241022",
        provider="anthropic",
        context_window=200000,
        max_output_tokens=8192,
        supports_vision=True,
        supports_tools=True,
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
        aliases=["claude-sonnet", "sonnet"],
    ),
    ModelInfo(
        name="claude-3-5-haiku-20241022",
        provider="anthropic",
        context_window=200000,
        max_output_tokens=8192,
        supports_vision=True,
        supports_tools=True,
        cost_per_1k_input=0.0008,
        cost_per_1k_output=0.004,
        aliases=["claude-haiku", "haiku"],
    ),
]


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """
    Get the global Config instance.

    Automatically loads:
    1. Default models
    2. ~/.openbench/config.yaml (if exists)
    3. ./openbench.yaml (if exists)
    4. Environment variables with OPENBENCH_ prefix

    Returns:
        Global Config instance
    """
    global _config
    if _config is None:
        _config = Config()

        # Register default models
        for model in DEFAULT_MODELS:
            _config.register_model(model)

        # Load config files
        home_config = Path.home() / ".openbench" / "config.yaml"
        if home_config.exists():
            _config.load(home_config)

        local_config = Path("openbench.yaml")
        if local_config.exists():
            _config.load(local_config)

        # Load environment overrides
        _config.load_env()

    return _config


def reset_config() -> None:
    """Reset global config (useful for testing)."""
    global _config
    _config = None
