"""Tests for GeminiLLMProvider."""

import unittest
from unittest.mock import MagicMock, patch

from openbench.core.abstractions import LLMProvider, LLMResponse


class TestGeminiLLMProviderInit(unittest.TestCase):
    """Tests for GeminiLLMProvider constructor."""

    def test_default_init(self):
        """Test initialization with defaults."""
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        provider = GeminiLLMProvider(api_key="test-key")
        self.assertEqual(provider.api_key, "test-key")
        self.assertEqual(provider.model, "gemini-2.5-flash")
        self.assertEqual(provider.temperature, 0.7)
        self.assertEqual(provider.max_output_tokens, 8192)

    def test_custom_init(self):
        """Test initialization with custom values."""
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        provider = GeminiLLMProvider(
            api_key="custom-key",
            model="gemini-2.5-pro",
            temperature=0.3,
            max_output_tokens=4096,
        )
        self.assertEqual(provider.api_key, "custom-key")
        self.assertEqual(provider.model, "gemini-2.5-pro")
        self.assertEqual(provider.temperature, 0.3)
        self.assertEqual(provider.max_output_tokens, 4096)

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "env-key"})
    def test_api_key_from_env(self):
        """Test API key falls back to environment variable."""
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        provider = GeminiLLMProvider()
        self.assertEqual(provider.api_key, "env-key")

    def test_extra_kwargs_ignored(self):
        """Test extra kwargs from ProviderService don't break init."""
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        provider = GeminiLLMProvider(api_key="test", extra_param="ignored", another="also_ignored")
        self.assertEqual(provider.api_key, "test")

    def test_inherits_llm_provider(self):
        """Test GeminiLLMProvider is a proper LLMProvider subclass."""
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        self.assertTrue(issubclass(GeminiLLMProvider, LLMProvider))


class TestGeminiLLMProviderProperties(unittest.TestCase):
    """Tests for GeminiLLMProvider properties."""

    def test_provider_name(self):
        """Test provider_name returns 'gemini'."""
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        provider = GeminiLLMProvider(api_key="test")
        self.assertEqual(provider.provider_name, "gemini")


class TestGeminiLLMProviderConvertMessages(unittest.TestCase):
    """Tests for OpenAI → Gemini message format conversion."""

    def setUp(self):
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        self.provider = GeminiLLMProvider(api_key="test")

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_system_message_extracted(self, mock_client):
        """Test system message becomes system_instruction."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        system, contents = self.provider._convert_messages(messages)
        self.assertEqual(system, "You are helpful.")
        self.assertEqual(len(contents), 1)

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_user_message_converted(self, mock_client):
        """Test user message becomes Content with role='user'."""
        messages = [{"role": "user", "content": "What is 2+2?"}]
        system, contents = self.provider._convert_messages(messages)
        self.assertIsNone(system)
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0].role, "user")

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_assistant_message_converted(self, mock_client):
        """Test assistant message becomes Content with role='model'."""
        messages = [{"role": "assistant", "content": "The answer is 4."}]
        _system, contents = self.provider._convert_messages(messages)
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0].role, "model")

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_tool_message_converted(self, mock_client):
        """Test tool result message becomes function_response."""
        messages = [
            {"role": "tool", "content": '{"result": "42"}', "name": "calc", "tool_call_id": "c0"},
        ]
        _system, contents = self.provider._convert_messages(messages)
        self.assertEqual(len(contents), 1)
        # Tool results go as user role in Gemini
        self.assertEqual(contents[0].role, "user")

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_assistant_with_tool_calls(self, mock_client):
        """Test assistant message with tool_calls produces function_call parts."""
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"name": "search", "arguments": {"query": "test"}},
                ],
            }
        ]
        _system, contents = self.provider._convert_messages(messages)
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0].role, "model")
        # Should have function_call part
        parts = contents[0].parts
        self.assertTrue(len(parts) >= 1)

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_full_conversation_flow(self, mock_client):
        """Test converting a full multi-turn conversation."""
        messages = [
            {"role": "system", "content": "You are an agent."},
            {"role": "user", "content": "Find info about X."},
            {
                "role": "assistant",
                "content": "I'll search for X.",
                "tool_calls": [
                    {"name": "search", "arguments": {"query": "X"}},
                ],
            },
            {
                "role": "tool",
                "content": '{"results": ["item1"]}',
                "name": "search",
                "tool_call_id": "call_0",
            },
            {"role": "assistant", "content": "Here is what I found about X."},
        ]
        system, contents = self.provider._convert_messages(messages)
        self.assertEqual(system, "You are an agent.")
        # user + assistant(tool_call) + tool_result + assistant
        self.assertEqual(len(contents), 4)

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_empty_assistant_no_content(self, mock_client):
        """Test assistant with empty content and no tool_calls is skipped."""
        messages = [{"role": "assistant", "content": ""}]
        _system, contents = self.provider._convert_messages(messages)
        # No parts → not added
        self.assertEqual(len(contents), 0)


class TestGeminiLLMProviderConvertTools(unittest.TestCase):
    """Tests for OpenAI → Gemini tool schema conversion."""

    def setUp(self):
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        self.provider = GeminiLLMProvider(api_key="test")

    def test_basic_tool_conversion(self):
        """Test converting a basic OpenAI tool schema."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search the web",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                        },
                        "required": ["query"],
                    },
                },
            }
        ]
        result = self.provider._convert_tools(tools)
        self.assertEqual(len(result), 1)  # One types.Tool
        # The Tool contains function_declarations
        self.assertTrue(hasattr(result[0], "function_declarations"))

    def test_multiple_tools(self):
        """Test converting multiple tools into a single types.Tool."""
        tools = [
            {"type": "function", "function": {"name": "search", "description": "Search"}},
            {"type": "function", "function": {"name": "calc", "description": "Calculate"}},
        ]
        result = self.provider._convert_tools(tools)
        self.assertEqual(len(result), 1)  # Wrapped in single Tool
        self.assertEqual(len(result[0].function_declarations), 2)

    def test_flat_tool_format(self):
        """Test converting tool dict without 'function' wrapper."""
        tools = [
            {"name": "search", "description": "Search", "parameters": None},
        ]
        result = self.provider._convert_tools(tools)
        self.assertEqual(len(result), 1)


class TestGeminiLLMProviderExtractToolCalls(unittest.TestCase):
    """Tests for extracting tool calls from Gemini response."""

    def setUp(self):
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        self.provider = GeminiLLMProvider(api_key="test")

    def test_no_candidates(self):
        """Test response with no candidates returns empty list."""
        mock_response = MagicMock()
        mock_response.candidates = []
        result = self.provider._extract_tool_calls(mock_response)
        self.assertEqual(result, [])

    def test_no_function_calls(self):
        """Test response with text-only parts returns empty list."""
        mock_part = MagicMock()
        mock_part.function_call = None
        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        result = self.provider._extract_tool_calls(mock_response)
        self.assertEqual(result, [])

    def test_single_function_call(self):
        """Test extracting a single function call."""
        mock_fc = MagicMock()
        mock_fc.name = "search"
        mock_fc.args = {"query": "test"}

        mock_part = MagicMock()
        mock_part.function_call = mock_fc

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]

        result = self.provider._extract_tool_calls(mock_response)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "search")
        self.assertEqual(result[0]["arguments"], {"query": "test"})
        self.assertEqual(result[0]["id"], "call_0")

    def test_multiple_function_calls(self):
        """Test extracting multiple function calls."""
        parts = []
        for i, name in enumerate(["search", "calc"]):
            mock_fc = MagicMock()
            mock_fc.name = name
            mock_fc.args = {"input": str(i)}
            mock_part = MagicMock()
            mock_part.function_call = mock_fc
            parts.append(mock_part)

        mock_candidate = MagicMock()
        mock_candidate.content.parts = parts
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]

        result = self.provider._extract_tool_calls(mock_response)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "search")
        self.assertEqual(result[1]["name"], "calc")


class TestGeminiLLMProviderCost(unittest.TestCase):
    """Tests for cost estimation."""

    def setUp(self):
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        self.provider = GeminiLLMProvider(api_key="test")

    def test_known_model_cost(self):
        """Test cost calculation for known model."""
        cost = self.provider._estimate_cost("gemini-2.5-flash", 1000, 500)
        # 1000 input * 0.15/1M + 500 output * 0.60/1M
        expected = (1000 / 1_000_000) * 0.15 + (500 / 1_000_000) * 0.60
        self.assertAlmostEqual(cost, expected, places=10)

    def test_unknown_model_cost_zero(self):
        """Test unknown model returns zero cost."""
        cost = self.provider._estimate_cost("unknown-model", 1000, 500)
        self.assertEqual(cost, 0.0)

    def test_zero_tokens_cost(self):
        """Test zero tokens returns zero cost."""
        cost = self.provider._estimate_cost("gemini-2.5-flash", 0, 0)
        self.assertEqual(cost, 0.0)


class TestGeminiLLMProviderGenerate(unittest.TestCase):
    """Tests for generate() method with mocked API."""

    def setUp(self):
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        self.provider = GeminiLLMProvider(api_key="test-key")

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_generate_with_string_prompt(self, mock_get_client):
        """Test generate with a simple string prompt."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock response
        mock_response = MagicMock()
        mock_response.text = "Hello! How can I help?"
        mock_response.candidates = []
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 20
        mock_response.usage_metadata.total_token_count = 30
        mock_client.models.generate_content.return_value = mock_response

        result = self.provider.generate("Say hello", model="gemini-2.5-flash")

        self.assertIsInstance(result, LLMResponse)
        self.assertEqual(result.text, "Hello! How can I help?")
        self.assertEqual(result.model, "gemini-2.5-flash")
        self.assertEqual(result.tokens_used, 30)
        mock_client.models.generate_content.assert_called_once()

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_generate_with_messages(self, mock_get_client):
        """Test generate with OpenAI-style message list (as BaseAgent sends)."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "The answer is 42."
        mock_response.candidates = []
        mock_response.usage_metadata.prompt_token_count = 50
        mock_response.usage_metadata.candidates_token_count = 10
        mock_response.usage_metadata.total_token_count = 60
        mock_client.models.generate_content.return_value = mock_response

        messages = [
            {"role": "system", "content": "You are a calculator."},
            {"role": "user", "content": "What is the meaning of life?"},
        ]

        result = self.provider.generate(messages, model="gemini-2.5-flash")

        self.assertEqual(result.text, "The answer is 42.")
        self.assertEqual(result.tokens_used, 60)

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_generate_uses_default_model(self, mock_get_client):
        """Test generate uses instance default model when none specified."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "response"
        mock_response.candidates = []
        mock_response.usage_metadata.prompt_token_count = 5
        mock_response.usage_metadata.candidates_token_count = 5
        mock_response.usage_metadata.total_token_count = 10
        mock_client.models.generate_content.return_value = mock_response

        result = self.provider.generate("test")

        self.assertEqual(result.model, "gemini-2.5-flash")

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_generate_passes_temperature(self, mock_get_client):
        """Test generate passes temperature to config."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "response"
        mock_response.candidates = []
        mock_response.usage_metadata = None
        mock_client.models.generate_content.return_value = mock_response

        self.provider.generate("test", temperature=0.1)

        call_kwargs = mock_client.models.generate_content.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        self.assertEqual(config.temperature, 0.1)


class TestGeminiLLMProviderToolCalling(unittest.TestCase):
    """Tests for generate() with tool calls in response."""

    def setUp(self):
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        self.provider = GeminiLLMProvider(api_key="test-key")

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_generate_with_tool_calls(self, mock_get_client):
        """Test generate returns tool_calls when Gemini calls functions."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Build mock response with function call
        mock_fc = MagicMock()
        mock_fc.name = "search"
        mock_fc.args = {"query": "latest news"}

        mock_part = MagicMock()
        mock_part.function_call = mock_fc

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata.prompt_token_count = 20
        mock_response.usage_metadata.candidates_token_count = 10
        mock_response.usage_metadata.total_token_count = 30
        mock_client.models.generate_content.return_value = mock_response

        result = self.provider.generate(
            [{"role": "user", "content": "Search for news"}],
            model="gemini-2.5-flash",
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "search",
                        "description": "Search the web",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                }
            ],
        )

        self.assertTrue(hasattr(result, "tool_calls"))
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0]["name"], "search")
        self.assertEqual(result.tool_calls[0]["arguments"], {"query": "latest news"})
        self.assertEqual(result.text, "")

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_generate_no_tool_calls_returns_text(self, mock_get_client):
        """Test generate returns text when no function calls."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.text = "Here is the answer."
        mock_response.candidates = []
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 15
        mock_response.usage_metadata.total_token_count = 25
        mock_client.models.generate_content.return_value = mock_response

        result = self.provider.generate(
            [{"role": "user", "content": "Hello"}],
            model="gemini-2.5-flash",
        )

        self.assertFalse(hasattr(result, "tool_calls"))
        self.assertEqual(result.text, "Here is the answer.")


class TestGeminiLLMProviderEmbed(unittest.TestCase):
    """Tests for embed() method."""

    def setUp(self):
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        self.provider = GeminiLLMProvider(api_key="test-key")

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_embed_returns_vector(self, mock_get_client):
        """Test embed returns list of floats."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_embedding = MagicMock()
        mock_embedding.values = [0.1, 0.2, 0.3, 0.4]
        mock_result = MagicMock()
        mock_result.embeddings = [mock_embedding]
        mock_client.models.embed_content.return_value = mock_result

        vector = self.provider.embed("Hello world")

        self.assertEqual(vector, [0.1, 0.2, 0.3, 0.4])
        mock_client.models.embed_content.assert_called_once()

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_embed_uses_default_model(self, mock_get_client):
        """Test embed defaults to text-embedding-004."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_embedding = MagicMock()
        mock_embedding.values = [0.1]
        mock_result = MagicMock()
        mock_result.embeddings = [mock_embedding]
        mock_client.models.embed_content.return_value = mock_result

        self.provider.embed("test")

        call_kwargs = mock_client.models.embed_content.call_args
        self.assertEqual(call_kwargs.kwargs.get("model"), "text-embedding-004")


class TestGeminiLLMProviderRegistration(unittest.TestCase):
    """Tests for LLMProviderRegistry registration."""

    def test_registered_in_registry(self):
        """Test GeminiLLMProvider is registered as chat:gemini."""
        # Import triggers registration
        import openbench.intelligence.llm_providers  # noqa: F401
        from openbench.core.registry import LLMProviderRegistry

        self.assertTrue(LLMProviderRegistry.is_registered("chat", "gemini"))

    def test_can_create_from_registry(self):
        """Test creating GeminiLLMProvider via registry."""
        import openbench.intelligence.llm_providers  # noqa: F401
        from openbench.core.registry import LLMProviderRegistry

        provider = LLMProviderRegistry.create("chat", "gemini", api_key="test")
        self.assertEqual(provider.provider_name, "gemini")
        self.assertIsInstance(provider, LLMProvider)

    def test_registry_lists_gemini(self):
        """Test gemini appears in registry plugin list."""
        import openbench.intelligence.llm_providers  # noqa: F401
        from openbench.core.registry import LLMProviderRegistry

        plugins = LLMProviderRegistry.list_plugins()
        self.assertIn("chat:gemini", plugins)


class TestGeminiLLMProviderClientInit(unittest.TestCase):
    """Tests for lazy client initialization."""

    def test_client_not_created_on_init(self):
        """Test client is not created during __init__."""
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        provider = GeminiLLMProvider(api_key="test")
        self.assertIsNone(provider._client)

    def test_no_api_key_raises_on_client(self):
        """Test missing API key raises ValueError on _get_client."""
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        provider = GeminiLLMProvider(api_key=None)
        provider.api_key = None  # Ensure no env fallback

        with (
            patch.dict("os.environ", {}, clear=True),
            # Mock the import so we don't need google-genai installed
            patch.dict("sys.modules", {"google": MagicMock(), "google.genai": MagicMock()}),
            self.assertRaises(ValueError),
        ):
            provider._get_client()


if __name__ == "__main__":
    unittest.main()
