"""Tests for GoogleADKAdapter."""

import os
import unittest
from unittest.mock import MagicMock, patch

from openbench.adapters.google_adk import GoogleADKAdapter


class TestGoogleADKAdapterInit(unittest.TestCase):
    """Test GoogleADKAdapter initialization."""

    def test_init_with_model(self):
        """Test initialization with model name."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro")
        self.assertEqual(adapter.model_name, "gemini-1.5-pro")
        self.assertIsNone(adapter.agent)

    def test_init_with_agent(self):
        """Test initialization with existing agent."""
        mock_agent = MagicMock()
        adapter = GoogleADKAdapter(agent=mock_agent)
        self.assertEqual(adapter.agent, mock_agent)
        self.assertIsNone(adapter.model_name)

    def test_init_requires_model_or_agent(self):
        """Test that either model or agent must be provided."""
        with self.assertRaises(ValueError) as ctx:
            GoogleADKAdapter()
        self.assertIn("Either 'model' or 'agent' must be provided", str(ctx.exception))

    def test_init_with_api_key(self):
        """Test initialization with API key."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro", api_key="test-key")
        self.assertEqual(adapter.api_key, "test-key")

    def test_init_reads_env_api_key(self):
        """Test that API key is read from environment."""
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "env-key"}):
            adapter = GoogleADKAdapter(model="gemini-1.5-pro")
            self.assertEqual(adapter.api_key, "env-key")

    def test_init_with_system_instruction(self):
        """Test initialization with system instruction."""
        adapter = GoogleADKAdapter(
            model="gemini-1.5-pro", system_instruction="You are a helpful assistant."
        )
        self.assertEqual(adapter.system_instruction, "You are a helpful assistant.")

    def test_init_with_generation_config(self):
        """Test initialization with generation config."""
        config = {"temperature": 0.5, "max_output_tokens": 4096}
        adapter = GoogleADKAdapter(model="gemini-1.5-pro", generation_config=config)
        self.assertEqual(adapter.generation_config["temperature"], 0.5)
        self.assertEqual(adapter.generation_config["max_output_tokens"], 4096)

    def test_init_default_generation_config(self):
        """Test default generation config values."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro")
        self.assertEqual(adapter.generation_config["temperature"], 0.7)
        self.assertEqual(adapter.generation_config["max_output_tokens"], 8192)


class TestGoogleADKAdapterProperties(unittest.TestCase):
    """Test GoogleADKAdapter properties."""

    def test_framework_name(self):
        """Test framework_name property."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro")
        self.assertEqual(adapter.framework_name, "google_adk")


class TestGoogleADKAdapterExtractContent(unittest.TestCase):
    """Test content extraction methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.adapter = GoogleADKAdapter(model="gemini-1.5-pro")

    def test_extract_string_content(self):
        """Test extracting string content."""
        result = self.adapter._extract_content("Hello world")
        self.assertEqual(result, "Hello world")

    def test_extract_dict_with_content_key(self):
        """Test extracting content from dict with 'content' key."""
        input_data = {"content": "Test content", "metadata": {}}
        result = self.adapter._extract_content(input_data)
        self.assertEqual(result, "Test content")

    def test_extract_dict_with_raw_data(self):
        """Test extracting content from DataLayer output."""
        mock_raw_data = MagicMock()
        mock_raw_data.content = "PDF content here"
        input_data = {"raw_data": [mock_raw_data], "metadata": {}}
        result = self.adapter._extract_content(input_data)
        self.assertEqual(result, "PDF content here")

    def test_extract_dict_with_intelligence_output(self):
        """Test extracting content from IntelligenceLayer output."""
        input_data = {"intelligence_output": {"content": "AI generated content"}, "metadata": {}}
        result = self.adapter._extract_content(input_data)
        self.assertEqual(result, "AI generated content")

    def test_extract_dict_with_goal(self):
        """Test extracting content from dict with goal."""
        input_data = {"goal": "Summarize this", "data": "Some data"}
        result = self.adapter._extract_content(input_data)
        self.assertIn("Summarize this", result)
        self.assertIn("Some data", result)

    def test_extract_object_with_content_attr(self):
        """Test extracting content from object with content attribute."""
        mock_obj = MagicMock()
        mock_obj.content = "Object content"
        result = self.adapter._extract_content(mock_obj)
        self.assertEqual(result, "Object content")

    def test_extract_object_with_output_attr(self):
        """Test extracting content from object with output attribute."""
        mock_obj = MagicMock(spec=["output"])
        mock_obj.output = "Output content"
        # Remove content attribute
        del mock_obj.content
        result = self.adapter._extract_content(mock_obj)
        self.assertEqual(result, "Output content")


class TestGoogleADKAdapterBuildPrompt(unittest.TestCase):
    """Test prompt building."""

    def setUp(self):
        """Set up test fixtures."""
        self.adapter = GoogleADKAdapter(model="gemini-1.5-pro")

    def test_build_prompt_without_goal(self):
        """Test building prompt without goal."""
        result = self.adapter._build_prompt("Just content")
        self.assertEqual(result, "Just content")

    def test_build_prompt_with_goal(self):
        """Test building prompt with goal."""
        result = self.adapter._build_prompt("Document content", goal="Summarize")
        self.assertIn("Task: Summarize", result)
        self.assertIn("Document content", result)
        self.assertIn("Please complete the task", result)


class TestGoogleADKAdapterAgentMode(unittest.TestCase):
    """Test agent mode invocation."""

    def test_invoke_agent_with_run_method(self):
        """Test invoking agent with run() method."""
        mock_agent = MagicMock()
        mock_agent.run.return_value = MagicMock(output="Agent output")

        adapter = GoogleADKAdapter(agent=mock_agent)
        result = adapter.invoke({"input": "test"})

        mock_agent.run.assert_called_once()
        self.assertEqual(result["content"], "Agent output")
        self.assertEqual(result["metadata"]["mode"], "agent")

    def test_invoke_agent_with_invoke_method(self):
        """Test invoking agent with invoke() method."""
        mock_agent = MagicMock(spec=["invoke"])
        mock_agent.invoke.return_value = "Invoked output"

        adapter = GoogleADKAdapter(agent=mock_agent)
        result = adapter.invoke({"input": "test"})

        mock_agent.invoke.assert_called_once()
        self.assertEqual(result["content"], "Invoked output")

    def test_invoke_agent_with_generate_method(self):
        """Test invoking agent with generate() method."""
        mock_agent = MagicMock(spec=["generate"])
        mock_agent.generate.return_value = "Generated output"

        adapter = GoogleADKAdapter(agent=mock_agent)
        result = adapter.invoke({"input": "test"})

        mock_agent.generate.assert_called_once()
        self.assertEqual(result["content"], "Generated output")

    def test_invoke_callable_agent(self):
        """Test invoking callable agent."""
        mock_agent = MagicMock(spec=[])
        mock_agent.return_value = "Callable output"

        adapter = GoogleADKAdapter(agent=mock_agent)
        result = adapter.invoke({"input": "test"})

        mock_agent.assert_called_once()
        self.assertEqual(result["content"], "Callable output")


class TestGoogleADKAdapterModelMode(unittest.TestCase):
    """Test model mode invocation."""

    @patch("openbench.adapters.google_adk.GoogleADKAdapter._init_client")
    def test_invoke_model_initializes_client(self, mock_init):
        """Test that invoke initializes client."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro", api_key="test-key")
        adapter._model = MagicMock()
        adapter._model.generate_content.return_value = MagicMock(
            text="Generated text", usage_metadata=None
        )

        adapter.invoke("Test input")
        mock_init.assert_called_once()

    @patch("openbench.adapters.google_adk.GoogleADKAdapter._init_client")
    def test_invoke_model_returns_correct_format(self, mock_init):
        """Test that invoke returns correct output format."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro", api_key="test-key")
        adapter._model = MagicMock()
        adapter._model.generate_content.return_value = MagicMock(
            text="Generated response", usage_metadata=None
        )

        result = adapter.invoke("Test input")

        self.assertIn("content", result)
        self.assertIn("model", result)
        self.assertIn("tokens_used", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["content"], "Generated response")
        self.assertEqual(result["model"], "gemini-1.5-pro")
        self.assertEqual(result["metadata"]["mode"], "model")

    @patch("openbench.adapters.google_adk.GoogleADKAdapter._init_client")
    def test_invoke_model_extracts_token_usage(self, mock_init):
        """Test that token usage is extracted."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro", api_key="test-key")
        adapter._model = MagicMock()

        mock_usage = MagicMock()
        mock_usage.prompt_token_count = 100
        mock_usage.candidates_token_count = 50
        mock_usage.total_token_count = 150

        adapter._model.generate_content.return_value = MagicMock(
            text="Response", usage_metadata=mock_usage
        )

        result = adapter.invoke("Test")

        self.assertEqual(result["tokens_used"]["prompt_tokens"], 100)
        self.assertEqual(result["tokens_used"]["completion_tokens"], 50)
        self.assertEqual(result["tokens_used"]["total_tokens"], 150)


class TestGoogleADKAdapterClientInit(unittest.TestCase):
    """Test client initialization."""

    def test_init_client_requires_api_key(self):
        """Test that init_client raises error without API key."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro")
        adapter.api_key = None

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                adapter._init_client()
            self.assertIn("Google API key is required", str(ctx.exception))

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_init_client_configures_genai(self, mock_model, mock_configure):
        """Test that init_client configures google.generativeai."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro", api_key="test-key")
        adapter._init_client()

        mock_configure.assert_called_once_with(api_key="test-key")
        mock_model.assert_called_once()

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_init_client_only_once(self, mock_model, mock_configure):
        """Test that client is only initialized once."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro", api_key="test-key")
        adapter._init_client()
        adapter._init_client()

        # Should only be called once
        self.assertEqual(mock_configure.call_count, 1)


class TestGoogleADKAdapterIntegration(unittest.TestCase):
    """Integration tests for GoogleADKAdapter."""

    def test_workflow_input_format(self):
        """Test handling DataLayer output format."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro")

        # Simulate DataLayer output
        mock_raw_data = MagicMock()
        mock_raw_data.content = "Extracted PDF text content"

        input_data = {
            "raw_data": [mock_raw_data],
            "indexed_ids": ["id1"],
            "metadata": {"layer": "data"},
        }

        content = adapter._extract_content(input_data)
        self.assertEqual(content, "Extracted PDF text content")

    def test_chained_input_format(self):
        """Test handling chained IntelligenceLayer output."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro")

        # Simulate IntelligenceLayer output
        input_data = {
            "intelligence_output": {
                "content": "Previous agent output",
                "model": "other-model",
                "metadata": {},
            },
            "metadata": {"layer": "intelligence"},
        }

        content = adapter._extract_content(input_data)
        self.assertEqual(content, "Previous agent output")


if __name__ == "__main__":
    unittest.main()
