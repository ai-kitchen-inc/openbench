"""Unit tests for LCIConfig."""

from __future__ import annotations

import os
from unittest.mock import patch

from lci_ignite.config import LCIConfig


class TestLCIConfigDefaults:
    def test_default_values(self):
        config = LCIConfig()
        assert config.model == "gemini-2.5-flash"
        assert config.temperature == 0.3
        assert config.google_api_key == ""
        assert config.pinecone_index_name == "lci-ignite"
        assert config.memory_db == "lci_memory.db"

    def test_custom_values(self):
        config = LCIConfig(
            google_api_key="test-key",
            model="gemini-2.5-pro",
            temperature=0.7,
        )
        assert config.google_api_key == "test-key"
        assert config.model == "gemini-2.5-pro"
        assert config.temperature == 0.7


class TestLCIConfigFromEnv:
    def test_from_env_with_vars(self):
        env = {
            "GOOGLE_API_KEY": "test-google-key",
            "LCI_MODEL": "gemini-2.5-pro",
            "LCI_TEMPERATURE": "0.5",
            "PINECONE_API_KEY": "test-pinecone-key",
        }
        with patch.dict(os.environ, env, clear=False):
            config = LCIConfig.from_env()
            assert config.google_api_key == "test-google-key"
            assert config.model == "gemini-2.5-pro"
            assert config.temperature == 0.5
            assert config.pinecone_api_key == "test-pinecone-key"

    def test_from_env_defaults(self):
        # Patch dotenv.load_dotenv to prevent it from loading .env files
        with patch.dict(os.environ, {}, clear=True), patch("dotenv.load_dotenv", return_value=None):
            config = LCIConfig.from_env()
            assert config.google_api_key == ""
            assert config.model == "gemini-2.5-flash"


class TestLCIConfigValidation:
    def test_validate_missing_api_key(self):
        config = LCIConfig()
        missing = config.validate()
        assert "GOOGLE_API_KEY" in missing

    def test_validate_all_present(self):
        config = LCIConfig(google_api_key="key")
        missing = config.validate()
        assert len(missing) == 0
