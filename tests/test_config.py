"""Tests for centralized configuration management."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from openbench.core.config import (
    Config,
    ModelInfo,
    get_config,
    reset_config,
    _expand_env_vars,
    DEFAULT_MODELS,
)


class TestExpandEnvVars(unittest.TestCase):
    """Test environment variable expansion."""

    def test_simple_var(self):
        """Test simple variable expansion."""
        os.environ["TEST_VAR"] = "hello"
        result = _expand_env_vars("${TEST_VAR}")
        self.assertEqual(result, "hello")

    def test_var_with_default(self):
        """Test variable with default value."""
        result = _expand_env_vars("${NONEXISTENT:-default_value}")
        self.assertEqual(result, "default_value")

    def test_var_in_string(self):
        """Test variable embedded in string."""
        os.environ["TEST_HOST"] = "localhost"
        result = _expand_env_vars("http://${TEST_HOST}:8080")
        self.assertEqual(result, "http://localhost:8080")

    def test_nested_dict(self):
        """Test variable expansion in nested dict."""
        os.environ["TEST_KEY"] = "secret"
        data = {"credentials": {"api_key": "${TEST_KEY}"}}
        result = _expand_env_vars(data)
        self.assertEqual(result["credentials"]["api_key"], "secret")

    def test_list_expansion(self):
        """Test variable expansion in list."""
        os.environ["TEST_ITEM"] = "value"
        data = ["${TEST_ITEM}", "static"]
        result = _expand_env_vars(data)
        self.assertEqual(result, ["value", "static"])


class TestModelInfo(unittest.TestCase):
    """Test ModelInfo dataclass."""

    def test_create_model(self):
        """Test creating a model info."""
        model = ModelInfo(
            name="test-model",
            provider="test",
            context_window=4096,
            max_output_tokens=1024,
        )

        self.assertEqual(model.name, "test-model")
        self.assertEqual(model.provider, "test")
        self.assertEqual(model.context_window, 4096)

    def test_to_dict(self):
        """Test serialization to dict."""
        model = ModelInfo(
            name="test-model",
            provider="test",
            aliases=["alias1", "alias2"],
        )

        data = model.to_dict()

        self.assertEqual(data["name"], "test-model")
        self.assertEqual(data["aliases"], ["alias1", "alias2"])

    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "name": "test-model",
            "provider": "test",
            "context_window": 8192,
            "supports_vision": True,
        }

        model = ModelInfo.from_dict(data)

        self.assertEqual(model.name, "test-model")
        self.assertEqual(model.context_window, 8192)
        self.assertTrue(model.supports_vision)


class TestConfig(unittest.TestCase):
    """Test Config class."""

    def test_create_config(self):
        """Test creating an empty config."""
        config = Config()
        self.assertIsNotNone(config)

    def test_create_with_data(self):
        """Test creating config with initial data."""
        config = Config({"key": "value"})
        self.assertEqual(config.get("key"), "value")

    def test_get_dot_notation(self):
        """Test getting value with dot notation."""
        config = Config({"llm": {"model": "gpt-4", "temperature": 0.7}})

        self.assertEqual(config.get("llm.model"), "gpt-4")
        self.assertEqual(config.get("llm.temperature"), 0.7)

    def test_get_default(self):
        """Test getting value with default."""
        config = Config()

        result = config.get("nonexistent", "default")
        self.assertEqual(result, "default")

    def test_get_int(self):
        """Test getting integer value."""
        config = Config({"count": "42"})
        self.assertEqual(config.get_int("count"), 42)
        self.assertEqual(config.get_int("missing", 10), 10)

    def test_get_float(self):
        """Test getting float value."""
        config = Config({"temperature": "0.7"})
        self.assertEqual(config.get_float("temperature"), 0.7)

    def test_get_bool(self):
        """Test getting boolean value."""
        config = Config({
            "enabled": "true",
            "disabled": "false",
            "yes": "yes",
            "no": "no",
            "one": "1",
            "zero": "0",
        })

        self.assertTrue(config.get_bool("enabled"))
        self.assertFalse(config.get_bool("disabled"))
        self.assertTrue(config.get_bool("yes"))
        self.assertFalse(config.get_bool("no"))
        self.assertTrue(config.get_bool("one"))
        self.assertFalse(config.get_bool("zero"))

    def test_get_list(self):
        """Test getting list value."""
        config = Config({"items": [1, 2, 3], "single": "value"})

        self.assertEqual(config.get_list("items"), [1, 2, 3])
        self.assertEqual(config.get_list("single"), ["value"])
        self.assertEqual(config.get_list("missing"), [])

    def test_set(self):
        """Test setting value."""
        config = Config()

        config.set("key", "value")
        self.assertEqual(config.get("key"), "value")

    def test_set_nested(self):
        """Test setting nested value."""
        config = Config()

        config.set("llm.model", "gpt-4")
        self.assertEqual(config.get("llm.model"), "gpt-4")

    def test_contains(self):
        """Test key existence check."""
        config = Config({"existing": "value"})

        self.assertIn("existing", config)
        self.assertNotIn("missing", config)

    def test_load_json(self):
        """Test loading JSON config file."""
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump({"key": "value", "nested": {"inner": 42}}, f)
            path = f.name

        try:
            config = Config()
            config.load(path)

            self.assertEqual(config.get("key"), "value")
            self.assertEqual(config.get("nested.inner"), 42)
        finally:
            os.unlink(path)

    def test_load_with_env_expansion(self):
        """Test loading config with environment variable expansion."""
        os.environ["CONFIG_TEST_VALUE"] = "expanded"

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump({"key": "${CONFIG_TEST_VALUE}"}, f)
            path = f.name

        try:
            config = Config()
            config.load(path)

            self.assertEqual(config.get("key"), "expanded")
        finally:
            os.unlink(path)

    def test_load_nonexistent(self):
        """Test loading nonexistent file."""
        config = Config()
        config.load("/nonexistent/path.json")

        # Should not raise, just log warning
        self.assertEqual(len(config._data), 0)

    def test_load_env(self):
        """Test loading from environment variables."""
        os.environ["OPENBENCH_LLM_MODEL"] = "gpt-4"
        os.environ["OPENBENCH_DEBUG"] = "true"

        config = Config()
        config.load_env()

        self.assertEqual(config.get("llm.model"), "gpt-4")
        self.assertEqual(config.get("debug"), "true")

    def test_merge_configs(self):
        """Test merging multiple configs."""
        config = Config({"a": 1, "nested": {"x": 10}})

        # Load additional config
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump({"b": 2, "nested": {"y": 20}}, f)
            path = f.name

        try:
            config.load(path)

            self.assertEqual(config.get("a"), 1)
            self.assertEqual(config.get("b"), 2)
            self.assertEqual(config.get("nested.x"), 10)
            self.assertEqual(config.get("nested.y"), 20)
        finally:
            os.unlink(path)

    def test_register_model(self):
        """Test registering a model."""
        config = Config()
        model = ModelInfo(name="test-model", provider="test", aliases=["tm"])

        config.register_model(model)

        self.assertEqual(config.get_model("test-model"), model)
        self.assertEqual(config.get_model("tm"), model)

    def test_list_models(self):
        """Test listing models."""
        config = Config()
        model1 = ModelInfo(name="model1", provider="openai")
        model2 = ModelInfo(name="model2", provider="anthropic")

        config.register_model(model1)
        config.register_model(model2)

        all_models = config.list_models()
        self.assertEqual(len(all_models), 2)

        openai_models = config.list_models(provider="openai")
        self.assertEqual(len(openai_models), 1)
        self.assertEqual(openai_models[0].name, "model1")

    def test_to_dict(self):
        """Test exporting config as dict."""
        config = Config({"key": "value"})
        config.register_model(ModelInfo(name="test", provider="test"))

        data = config.to_dict()

        self.assertEqual(data["key"], "value")
        self.assertIn("models", data)

    def test_save_json(self):
        """Test saving config to JSON."""
        config = Config({"key": "value"})

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            config.save(path)

            self.assertTrue(path.exists())

            # Verify content
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["key"], "value")

    def test_repr(self):
        """Test string representation."""
        config = Config({"a": 1, "b": 2})
        repr_str = repr(config)

        self.assertIn("Config", repr_str)


class TestGlobalConfig(unittest.TestCase):
    """Test global config functions."""

    def setUp(self):
        """Reset global config before each test."""
        reset_config()

    def tearDown(self):
        """Clean up after each test."""
        reset_config()

    def test_get_config(self):
        """Test getting global config."""
        config1 = get_config()
        config2 = get_config()

        # Should return same instance
        self.assertIs(config1, config2)

    def test_default_models_loaded(self):
        """Test default models are loaded."""
        config = get_config()

        # Check some default models
        gpt4o = config.get_model("gpt-4o")
        self.assertIsNotNone(gpt4o)
        self.assertEqual(gpt4o.provider, "openai")

        # Check alias works
        sonnet = config.get_model("sonnet")
        self.assertIsNotNone(sonnet)
        self.assertEqual(sonnet.provider, "anthropic")

    def test_reset_config(self):
        """Test resetting global config."""
        config1 = get_config()
        reset_config()
        config2 = get_config()

        # Should be different instances
        self.assertIsNot(config1, config2)


class TestDefaultModels(unittest.TestCase):
    """Test default model definitions."""

    def test_default_models_exist(self):
        """Test that default models are defined."""
        self.assertGreater(len(DEFAULT_MODELS), 0)

    def test_default_models_have_required_fields(self):
        """Test default models have required fields."""
        for model in DEFAULT_MODELS:
            self.assertIsNotNone(model.name)
            self.assertIsNotNone(model.provider)
            self.assertGreater(model.context_window, 0)


if __name__ == "__main__":
    unittest.main()
