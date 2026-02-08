"""Tests for centralized provider service."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openbench.core.providers import (
    _ENCRYPTED_PREFIX,
    CredentialEncryption,
    ProviderConfig,
    ProviderService,
    ProviderType,
    get_credential_encryption,
    get_provider_service,
    reset_provider_service,
)


class TestCredentialEncryption(unittest.TestCase):
    """Test CredentialEncryption class."""

    def setUp(self):
        """Create a temporary key file for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.key_path = Path(self.temp_dir) / ".credentials_key"

    def test_encryption_creates_key_file(self):
        """Test that encryption creates key file if not exists."""
        encryption = CredentialEncryption(key_path=self.key_path)

        if encryption.is_available:
            self.assertTrue(self.key_path.exists())

    def test_encrypt_decrypt_roundtrip(self):
        """Test that encrypt followed by decrypt returns original value."""
        encryption = CredentialEncryption(key_path=self.key_path)

        if not encryption.is_available:
            self.skipTest("cryptography not installed")

        original = "my-secret-api-key-12345"
        encrypted = encryption.encrypt(original)
        decrypted = encryption.decrypt(encrypted)

        self.assertEqual(decrypted, original)
        self.assertNotEqual(encrypted, original)
        self.assertTrue(encrypted.startswith(_ENCRYPTED_PREFIX))

    def test_decrypt_plaintext_returns_unchanged(self):
        """Test that decrypting non-encrypted value returns it unchanged."""
        encryption = CredentialEncryption(key_path=self.key_path)

        plaintext = "plain-api-key"
        result = encryption.decrypt(plaintext)

        self.assertEqual(result, plaintext)

    def test_encrypt_dict(self):
        """Test encrypting all string values in a dict."""
        encryption = CredentialEncryption(key_path=self.key_path)

        if not encryption.is_available:
            self.skipTest("cryptography not installed")

        original = {
            "api_key": "sk-12345",
            "secret": "my-secret",
            "count": 42,
            "nested": {"token": "nested-token"},
        }

        encrypted = encryption.encrypt_dict(original)

        # String values should be encrypted
        self.assertTrue(encrypted["api_key"].startswith(_ENCRYPTED_PREFIX))
        self.assertTrue(encrypted["secret"].startswith(_ENCRYPTED_PREFIX))
        self.assertTrue(encrypted["nested"]["token"].startswith(_ENCRYPTED_PREFIX))

        # Non-string values should be unchanged
        self.assertEqual(encrypted["count"], 42)

    def test_decrypt_dict(self):
        """Test decrypting all encrypted values in a dict."""
        encryption = CredentialEncryption(key_path=self.key_path)

        if not encryption.is_available:
            self.skipTest("cryptography not installed")

        original = {
            "api_key": "sk-12345",
            "secret": "my-secret",
            "count": 42,
        }

        encrypted = encryption.encrypt_dict(original)
        decrypted = encryption.decrypt_dict(encrypted)

        self.assertEqual(decrypted["api_key"], "sk-12345")
        self.assertEqual(decrypted["secret"], "my-secret")
        self.assertEqual(decrypted["count"], 42)

    def test_key_persistence(self):
        """Test that the same key is used across instances."""
        encryption1 = CredentialEncryption(key_path=self.key_path)

        if not encryption1.is_available:
            self.skipTest("cryptography not installed")

        encrypted = encryption1.encrypt("test-value")

        # Create new instance with same key path
        encryption2 = CredentialEncryption(key_path=self.key_path)
        decrypted = encryption2.decrypt(encrypted)

        self.assertEqual(decrypted, "test-value")

    def test_fallback_when_crypto_unavailable(self):
        """Test graceful fallback when cryptography not available."""
        with patch.dict("sys.modules", {"cryptography": None, "cryptography.fernet": None}):
            # Force re-initialization without cryptography
            encryption = CredentialEncryption(key_path=self.key_path)
            encryption._available = False
            encryption._fernet = None

            original = "test-value"
            encrypted = encryption.encrypt(original)

            # Should return original value unchanged
            self.assertEqual(encrypted, original)


class TestProviderConfig(unittest.TestCase):
    """Test ProviderConfig dataclass."""

    def test_create_config(self):
        """Test creating a provider config."""
        config = ProviderConfig(
            name="test-llm",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
            credentials={"api_key": "test-key"},
            settings={"temperature": 0.7},
            is_default=True,
        )

        self.assertEqual(config.name, "test-llm")
        self.assertEqual(config.provider_type, ProviderType.LLM)
        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.credentials["api_key"], "test-key")
        self.assertTrue(config.is_default)
        self.assertTrue(config.enabled)

    def test_to_dict(self):
        """Test serialization to dict."""
        config = ProviderConfig(
            name="test-llm",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
        )

        data = config.to_dict()

        self.assertEqual(data["name"], "test-llm")
        self.assertEqual(data["provider_type"], "llm")
        self.assertEqual(data["provider"], "openai")

    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "name": "test-llm",
            "provider_type": "llm",
            "provider": "openai",
            "plugin_type": "chat",
            "credentials": {"api_key": "test"},
            "is_default": True,
        }

        config = ProviderConfig.from_dict(data)

        self.assertEqual(config.name, "test-llm")
        self.assertEqual(config.provider_type, ProviderType.LLM)
        self.assertTrue(config.is_default)


class TestProviderService(unittest.TestCase):
    """Test ProviderService."""

    def setUp(self):
        """Create a temporary config file for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = Path(self.temp_dir) / "providers.json"
        self.service = ProviderService(config_path=str(self.config_path))

    def test_configure_provider(self):
        """Test configuring a provider."""
        config = ProviderConfig(
            name="my-openai",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
            credentials={"api_key": "sk-test"},
        )

        self.service.configure(config)

        self.assertIn("my-openai", self.service)
        self.assertEqual(len(self.service), 1)

    def test_get_provider(self):
        """Test getting a provider by name."""
        config = ProviderConfig(
            name="my-openai",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
        )
        self.service.configure(config)

        retrieved = self.service.get("my-openai")

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "my-openai")

    def test_get_nonexistent(self):
        """Test getting a nonexistent provider."""
        result = self.service.get("nonexistent")
        self.assertIsNone(result)

    def test_remove_provider(self):
        """Test removing a provider."""
        config = ProviderConfig(
            name="my-openai",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
        )
        self.service.configure(config)

        result = self.service.remove("my-openai")

        self.assertTrue(result)
        self.assertNotIn("my-openai", self.service)

    def test_remove_nonexistent(self):
        """Test removing a nonexistent provider."""
        result = self.service.remove("nonexistent")
        self.assertFalse(result)

    def test_default_provider(self):
        """Test setting and getting default provider."""
        config1 = ProviderConfig(
            name="openai-1",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
            is_default=True,
        )
        config2 = ProviderConfig(
            name="openai-2",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
        )

        self.service.configure(config1)
        self.service.configure(config2)

        default = self.service.get_default(ProviderType.LLM)

        self.assertIsNotNone(default)
        self.assertEqual(default.name, "openai-1")

    def test_set_default(self):
        """Test changing the default provider."""
        config1 = ProviderConfig(
            name="openai-1",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
            is_default=True,
        )
        config2 = ProviderConfig(
            name="openai-2",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
        )

        self.service.configure(config1)
        self.service.configure(config2)
        self.service.set_default("openai-2")

        default = self.service.get_default(ProviderType.LLM)

        self.assertEqual(default.name, "openai-2")
        self.assertFalse(self.service.get("openai-1").is_default)

    def test_only_one_default_per_type(self):
        """Test that only one provider can be default per type."""
        config1 = ProviderConfig(
            name="openai-1",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
            is_default=True,
        )
        config2 = ProviderConfig(
            name="openai-2",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
            is_default=True,  # This should unset openai-1
        )

        self.service.configure(config1)
        self.service.configure(config2)

        # Only openai-2 should be default
        self.assertFalse(self.service.get("openai-1").is_default)
        self.assertTrue(self.service.get("openai-2").is_default)

    def test_list_providers(self):
        """Test listing providers."""
        self.service.configure(
            ProviderConfig(
                name="llm-1",
                provider_type=ProviderType.LLM,
                provider="openai",
                plugin_type="chat",
            )
        )
        self.service.configure(
            ProviderConfig(
                name="vector-1",
                provider_type=ProviderType.VECTOR,
                provider="pinecone",
                plugin_type="vector",
            )
        )

        all_providers = self.service.list()
        llm_providers = self.service.list(provider_type=ProviderType.LLM)

        self.assertEqual(len(all_providers), 2)
        self.assertEqual(len(llm_providers), 1)
        self.assertEqual(llm_providers[0].name, "llm-1")

    def test_list_enabled_only(self):
        """Test listing only enabled providers."""
        self.service.configure(
            ProviderConfig(
                name="enabled",
                provider_type=ProviderType.LLM,
                provider="openai",
                plugin_type="chat",
                enabled=True,
            )
        )
        self.service.configure(
            ProviderConfig(
                name="disabled",
                provider_type=ProviderType.LLM,
                provider="openai",
                plugin_type="chat",
                enabled=False,
            )
        )

        enabled = self.service.list(enabled_only=True)

        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].name, "enabled")

    def test_persistence(self):
        """Test that configs are persisted to disk."""
        config = ProviderConfig(
            name="persistent",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
            credentials={"api_key": "test"},
        )
        self.service.configure(config)

        # Create new service instance with same path
        new_service = ProviderService(config_path=str(self.config_path))

        self.assertIn("persistent", new_service)
        self.assertEqual(new_service.get("persistent").credentials["api_key"], "test")

    def test_clear(self):
        """Test clearing all providers."""
        self.service.configure(
            ProviderConfig(
                name="test",
                provider_type=ProviderType.LLM,
                provider="openai",
                plugin_type="chat",
            )
        )

        self.service.clear()

        self.assertEqual(len(self.service), 0)

    def test_test_connection_not_found(self):
        """Test connection test for nonexistent provider."""
        result = self.service.test_connection("nonexistent")

        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    def test_is_encryption_enabled(self):
        """Test checking if encryption is enabled."""
        # Encryption should be enabled by default
        result = self.service.is_encryption_enabled()

        # Result depends on whether cryptography is installed
        encryption = get_credential_encryption()
        self.assertEqual(result, encryption.is_available)

    def test_encryption_disabled_option(self):
        """Test creating service with encryption disabled."""
        service = ProviderService(config_path=str(self.config_path), encrypt_credentials=False)

        self.assertFalse(service.is_encryption_enabled())


class TestProviderServiceEncryption(unittest.TestCase):
    """Test ProviderService encryption functionality."""

    def setUp(self):
        """Create temporary files for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = Path(self.temp_dir) / "providers.json"
        self.key_path = Path(self.temp_dir) / ".credentials_key"

    def test_credentials_encrypted_on_save(self):
        """Test that credentials are encrypted when saved to disk."""
        service = ProviderService(config_path=str(self.config_path), encrypt_credentials=True)

        config = ProviderConfig(
            name="test-provider",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
            credentials={"api_key": "sk-secret-key-12345"},
        )
        service.configure(config)

        # Read the raw JSON file
        with open(self.config_path) as f:
            raw_data = json.load(f)

        encryption = get_credential_encryption()
        if encryption.is_available:
            # API key should be encrypted in file
            stored_key = raw_data["providers"]["test-provider"]["credentials"]["api_key"]
            self.assertTrue(stored_key.startswith(_ENCRYPTED_PREFIX))
        else:
            # Without cryptography, stored as plaintext
            stored_key = raw_data["providers"]["test-provider"]["credentials"]["api_key"]
            self.assertEqual(stored_key, "sk-secret-key-12345")

    def test_credentials_decrypted_on_load(self):
        """Test that credentials are decrypted when loaded from disk."""
        # First, save with encryption
        service1 = ProviderService(config_path=str(self.config_path), encrypt_credentials=True)

        config = ProviderConfig(
            name="test-provider",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
            credentials={"api_key": "sk-secret-key-12345"},
        )
        service1.configure(config)

        # Create new service and load
        service2 = ProviderService(config_path=str(self.config_path), encrypt_credentials=True)

        loaded_config = service2.get("test-provider")

        # Credentials should be decrypted in memory
        self.assertEqual(loaded_config.credentials["api_key"], "sk-secret-key-12345")

    def test_no_encryption_when_disabled(self):
        """Test that credentials are stored as plaintext when encryption disabled."""
        service = ProviderService(config_path=str(self.config_path), encrypt_credentials=False)

        config = ProviderConfig(
            name="test-provider",
            provider_type=ProviderType.LLM,
            provider="openai",
            plugin_type="chat",
            credentials={"api_key": "sk-plaintext-key"},
        )
        service.configure(config)

        # Read the raw JSON file
        with open(self.config_path) as f:
            raw_data = json.load(f)

        # Should be stored as plaintext
        stored_key = raw_data["providers"]["test-provider"]["credentials"]["api_key"]
        self.assertEqual(stored_key, "sk-plaintext-key")


class TestProviderType(unittest.TestCase):
    """Test ProviderType enum."""

    def test_all_types_exist(self):
        """Test that all expected provider types exist."""
        self.assertEqual(ProviderType.LLM.value, "llm")
        self.assertEqual(ProviderType.EMBEDDING.value, "embedding")
        self.assertEqual(ProviderType.VECTOR.value, "vector")
        self.assertEqual(ProviderType.STORAGE.value, "storage")
        self.assertEqual(ProviderType.VOICE.value, "voice")


class TestConvenienceFunctions(unittest.TestCase):
    """Test convenience functions."""

    def test_get_provider_service(self):
        """Test getting global provider service."""
        service1 = get_provider_service()
        service2 = get_provider_service()

        # Should return same instance
        self.assertIs(service1, service2)

    def test_reset_provider_service(self):
        """Test resetting global provider service."""
        service1 = get_provider_service()
        reset_provider_service()
        service2 = get_provider_service()

        # Should be different instances after reset
        self.assertIsNot(service1, service2)

    def test_get_credential_encryption(self):
        """Test getting global credential encryption instance."""
        encryption1 = get_credential_encryption()
        encryption2 = get_credential_encryption()

        # Should return same instance
        self.assertIs(encryption1, encryption2)


if __name__ == "__main__":
    unittest.main()
