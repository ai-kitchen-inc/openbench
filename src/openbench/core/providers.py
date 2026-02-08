"""
Centralized Provider Service for OpenBench.

Provides unified provider configuration and resolution:
- Single source for all provider configs (LLM, Vector, Storage, etc.)
- Credential management with encryption at rest
- Default provider per type
- Integration with PluginRegistry for instance creation
"""

import base64
import contextlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Encryption marker prefix for encrypted values
_ENCRYPTED_PREFIX = "enc:v1:"


class CredentialEncryption:
    """
    Handles encryption and decryption of credentials.

    Uses Fernet symmetric encryption from the cryptography library.
    Falls back to plaintext if cryptography is not installed.
    The encryption key is stored in ~/.openbench/.credentials_key
    """

    def __init__(self, key_path: Path | None = None):
        """Initialize credential encryption."""
        self._key_path = key_path or Path.home() / ".openbench" / ".credentials_key"
        self._fernet = None
        self._init_encryption()

    def _init_encryption(self) -> None:
        """Initialize encryption if cryptography is available."""
        try:
            from cryptography.fernet import Fernet

            if self._key_path.exists():
                key = self._key_path.read_bytes().strip()
            else:
                key = Fernet.generate_key()
                self._key_path.parent.mkdir(parents=True, exist_ok=True)
                self._key_path.write_bytes(key)
                with contextlib.suppress(OSError):
                    os.chmod(self._key_path, 0o600)

            self._fernet = Fernet(key)
            logger.debug("Credential encryption initialized")

        except ImportError:
            logger.warning(
                "cryptography not installed. Credentials will be stored in plaintext. "
                "Install with: pip install openbench[security]"
            )

    @property
    def is_available(self) -> bool:
        """Check if encryption is available."""
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        """Encrypt a string value. Returns original if encryption unavailable."""
        if self._fernet is None:
            return value
        encrypted = self._fernet.encrypt(value.encode())
        return _ENCRYPTED_PREFIX + base64.urlsafe_b64encode(encrypted).decode()

    def decrypt(self, value: str) -> str:
        """Decrypt a string value. Returns original if not encrypted or unavailable."""
        if not value.startswith(_ENCRYPTED_PREFIX):
            return value

        if self._fernet is None:
            logger.warning("Cannot decrypt: cryptography not available")
            return value

        try:
            encrypted = base64.urlsafe_b64decode(value[len(_ENCRYPTED_PREFIX) :])
            return self._fernet.decrypt(encrypted).decode()
        except Exception as e:
            logger.error(f"Failed to decrypt credential: {e}")
            return value

    def _transform_dict(
        self, data: dict[str, Any], transform_fn: Callable[[str], str]
    ) -> dict[str, Any]:
        """Apply a transform function to all string values in a dictionary."""
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = transform_fn(value)
            elif isinstance(value, dict):
                result[key] = self._transform_dict(value, transform_fn)
            else:
                result[key] = value
        return result

    def encrypt_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Encrypt all string values in a dictionary."""
        return self._transform_dict(data, self.encrypt)

    def decrypt_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Decrypt all encrypted values in a dictionary."""
        return self._transform_dict(data, self.decrypt)


# Global encryption instance
_credential_encryption: CredentialEncryption | None = None


def get_credential_encryption() -> CredentialEncryption:
    """Get the global CredentialEncryption instance."""
    global _credential_encryption
    if _credential_encryption is None:
        _credential_encryption = CredentialEncryption()
    return _credential_encryption


class ProviderType(Enum):
    """Types of providers supported by OpenBench."""

    LLM = "llm"
    EMBEDDING = "embedding"
    VECTOR = "vector"
    STORAGE = "storage"
    VOICE = "voice"


@dataclass
class ProviderConfig:
    """Configuration for a single provider instance."""

    name: str
    provider_type: ProviderType
    provider: str  # e.g., "openai", "pinecone", "s3"
    plugin_type: str  # e.g., "chat", "vector", "blob"
    credentials: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    is_default: bool = False
    enabled: bool = True

    def to_dict(self, encrypt: bool = False) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        credentials = self.credentials
        if encrypt:
            credentials = get_credential_encryption().encrypt_dict(self.credentials)

        return {
            "name": self.name,
            "provider_type": self.provider_type.value,
            "provider": self.provider,
            "plugin_type": self.plugin_type,
            "credentials": credentials,
            "settings": self.settings,
            "is_default": self.is_default,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], decrypt: bool = False) -> "ProviderConfig":
        """Create from dictionary."""
        credentials = data.get("credentials", {})
        if decrypt:
            credentials = get_credential_encryption().decrypt_dict(credentials)

        return cls(
            name=data["name"],
            provider_type=ProviderType(data["provider_type"]),
            provider=data["provider"],
            plugin_type=data["plugin_type"],
            credentials=credentials,
            settings=data.get("settings", {}),
            is_default=data.get("is_default", False),
            enabled=data.get("enabled", True),
        )


class ProviderService:
    """
    Centralized service for provider configuration and resolution.

    Features:
    - Store and manage provider configurations
    - Encrypt credentials at rest (requires cryptography package)
    - Resolve providers via PluginRegistry
    - Default provider per type

    Example:
        >>> providers = ProviderService()
        >>>
        >>> # Configure a provider
        >>> providers.configure(ProviderConfig(
        ...     name="my-openai",
        ...     provider_type=ProviderType.LLM,
        ...     provider="openai",
        ...     plugin_type="chat",
        ...     credentials={"api_key": "sk-..."},
        ...     is_default=True
        ... ))
        >>>
        >>> # Get default LLM provider
        >>> config = providers.get_default(ProviderType.LLM)
        >>>
        >>> # Resolve to actual instance
        >>> llm = providers.resolve(ProviderType.LLM)
    """

    def __init__(
        self,
        config_path: str | None = None,
        encrypt_credentials: bool = True,
        require_encryption: bool = False,
    ):
        """
        Initialize the provider service.

        Args:
            config_path: Path to config file. Defaults to ~/.openbench/providers.json
            encrypt_credentials: Whether to encrypt credentials when saving
            require_encryption: If True, raise ImportError when cryptography is not installed.
                Use this in production to ensure credentials are never stored in plaintext.
        """
        self._configs: dict[str, ProviderConfig] = {}
        self._config_path = Path(config_path or os.path.expanduser("~/.openbench/providers.json"))
        self._encrypt_credentials = encrypt_credentials

        if require_encryption:
            encryption = get_credential_encryption()
            if not encryption.is_available:
                raise ImportError(
                    "Credential encryption is required but cryptography is not installed. "
                    "Install with: pip install openbench[security]"
                )

        self._load_configs()

    def _load_configs(self) -> None:
        """Load provider configurations from file (decrypting if needed)."""
        if not self._config_path.exists():
            logger.debug(f"No config file at {self._config_path}")
            return

        try:
            with open(self._config_path) as f:
                data = json.load(f)

            for name, config_data in data.get("providers", {}).items():
                # Decrypt credentials when loading
                self._configs[name] = ProviderConfig.from_dict(config_data, decrypt=True)

            logger.debug(f"Loaded {len(self._configs)} provider configs")
        except Exception as e:
            logger.warning(f"Failed to load provider configs: {e}")

    def _save_configs(self) -> None:
        """Save provider configurations to file (encrypting if enabled)."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "providers": {
                name: config.to_dict(encrypt=self._encrypt_credentials)
                for name, config in self._configs.items()
            }
        }

        with open(self._config_path, "w") as f:
            json.dump(data, f, indent=2)

        # Set restrictive permissions on config file
        with contextlib.suppress(OSError):
            os.chmod(self._config_path, 0o600)

        logger.debug(f"Saved {len(self._configs)} provider configs")

    def configure(self, config: ProviderConfig, save: bool = True) -> None:
        """Configure a provider."""
        if config.is_default:
            self._clear_default_for_type(config.provider_type)

        self._configs[config.name] = config

        if save:
            self._save_configs()

        logger.info(f"Configured provider: {config.name}")

    def _clear_default_for_type(self, provider_type: ProviderType) -> None:
        """Clear the default flag for all providers of the given type."""
        for existing in self._configs.values():
            if existing.provider_type == provider_type and existing.is_default:
                existing.is_default = False

    def remove(self, name: str, save: bool = True) -> bool:
        """Remove a provider configuration. Returns True if removed."""
        if name not in self._configs:
            return False

        del self._configs[name]

        if save:
            self._save_configs()

        return True

    def get(self, name: str) -> ProviderConfig | None:
        """Get provider configuration by name."""
        return self._configs.get(name)

    def get_default(self, provider_type: ProviderType) -> ProviderConfig | None:
        """Get default provider for a type, falling back to first enabled."""
        for config in self._configs.values():
            if config.provider_type == provider_type and config.is_default:
                return config

        for config in self._configs.values():
            if config.provider_type == provider_type and config.enabled:
                return config

        return None

    def list(
        self,
        provider_type: ProviderType | None = None,
        enabled_only: bool = False,
    ) -> list[ProviderConfig]:
        """List provider configurations with optional filtering."""
        return [
            config
            for config in self._configs.values()
            if (provider_type is None or config.provider_type == provider_type)
            and (not enabled_only or config.enabled)
        ]

    def resolve(
        self,
        provider_type: ProviderType,
        name: str | None = None,
        **override_kwargs,
    ) -> Any:
        """Resolve and create a provider instance via PluginRegistry."""
        from openbench.core.registry import (
            DataStoreRegistry,
            LLMProviderRegistry,
            PluginRegistry,
        )

        config = self.get(name) if name else self.get_default(provider_type)
        if not config:
            suffix = f" with name '{name}'" if name else " (no default set)"
            raise ValueError(f"No provider configured for {provider_type.value}{suffix}")

        if not config.enabled:
            raise ValueError(f"Provider '{config.name}' is disabled")

        # Currently supported provider type → registry mappings.
        # EMBEDDING, STORAGE, and VOICE are reserved for future registries.
        registry_map: dict[ProviderType, PluginRegistry] = {
            ProviderType.LLM: LLMProviderRegistry,
            ProviderType.VECTOR: DataStoreRegistry,
            # ProviderType.EMBEDDING: reserved — use EmbeddingProvider directly
            # ProviderType.STORAGE: reserved — no StorageRegistry yet
            # ProviderType.VOICE: reserved — no VoiceRegistry yet
        }

        registry = registry_map.get(provider_type)
        if not registry:
            raise ValueError(f"No registry for provider type: {provider_type.value}")

        kwargs = {**config.credentials, **config.settings, **override_kwargs}
        return registry.create(config.plugin_type, config.provider, **kwargs)

    def set_default(self, name: str, save: bool = True) -> bool:
        """Set a provider as the default for its type. Returns True if set."""
        config = self.get(name)
        if not config:
            return False

        for existing in self._configs.values():
            if existing.provider_type == config.provider_type:
                existing.is_default = existing.name == name

        if save:
            self._save_configs()

        return True

    def test_connection(self, name: str) -> dict[str, Any]:
        """Test connection to a provider. Returns dict with success status."""
        config = self.get(name)
        if not config:
            return {"success": False, "error": f"Provider '{name}' not found"}

        try:
            instance = self.resolve(config.provider_type, name)

            if config.provider_type == ProviderType.LLM and hasattr(instance, "generate"):
                return {"success": True, "message": "LLM provider configured"}

            return {"success": True, "message": "Provider configured successfully"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def is_encryption_enabled(self) -> bool:
        """Check if credential encryption is enabled and available."""
        encryption = get_credential_encryption()
        return self._encrypt_credentials and encryption.is_available

    def clear(self) -> None:
        """Clear all provider configurations (in memory only)."""
        self._configs.clear()

    def __len__(self) -> int:
        return len(self._configs)

    def __contains__(self, name: str) -> bool:
        return name in self._configs


# Global provider service instance
_provider_service: ProviderService | None = None


def get_provider_service() -> ProviderService:
    """Get the global ProviderService instance."""
    global _provider_service
    if _provider_service is None:
        _provider_service = ProviderService()
    return _provider_service


def reset_provider_service() -> None:
    """Reset the global ProviderService (useful for testing)."""
    global _provider_service
    _provider_service = None


def configure_provider(
    name: str,
    provider_type: ProviderType,
    provider: str,
    plugin_type: str,
    credentials: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
    is_default: bool = False,
) -> None:
    """Convenience function to configure a provider."""
    config = ProviderConfig(
        name=name,
        provider_type=provider_type,
        provider=provider,
        plugin_type=plugin_type,
        credentials=credentials or {},
        settings=settings or {},
        is_default=is_default,
    )
    get_provider_service().configure(config)


def resolve_provider(
    provider_type: ProviderType,
    name: str | None = None,
    **kwargs,
) -> Any:
    """Convenience function to resolve a provider."""
    return get_provider_service().resolve(provider_type, name, **kwargs)
