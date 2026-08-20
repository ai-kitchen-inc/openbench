"""Tests for GeminiLLMProvider."""

import json
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
        self.assertEqual(provider.max_output_tokens, 32768)

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

    def _raw_tool_content(self, name: str, args: dict):
        fc = MagicMock()
        fc.name = name
        fc.args = args
        part = MagicMock()
        part.function_call = fc
        raw_content = MagicMock()
        # Replayed assistant raw_content comes back from Gemini already tagged
        # as the model turn; the provider appends it verbatim, so the mock must
        # carry a real role string (not an auto-generated MagicMock attribute).
        raw_content.role = "model"
        raw_content.parts = [part]
        return raw_content

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
        """Test tool result message becomes function_response when paired
        with a preceding assistant tool_call (memory validator requires
        both sides of the pair)."""
        messages = [
            {
                "role": "assistant",
                "content": "",
                "raw_content": self._raw_tool_content("calc", {}),
                "tool_calls": [{"id": "c0", "name": "calc", "arguments": {}}],
            },
            {
                "role": "tool",
                "content": '{"result": "42"}',
                "name": "calc",
                "tool_call_id": "c0",
            },
        ]
        _system, contents = self.provider._convert_messages(messages)
        self.assertEqual(len(contents), 2)
        # Assistant with function_call
        self.assertEqual(contents[0].role, "model")
        # Tool result goes as user role in Gemini
        self.assertEqual(contents[1].role, "user")

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_assistant_with_tool_calls(self, mock_client):
        """Test assistant message with tool_calls produces function_call parts."""
        messages = [
            {
                "role": "assistant",
                "content": "",
                "raw_content": self._raw_tool_content("search", {"query": "test"}),
                "tool_calls": [
                    {"id": "call_0", "name": "search", "arguments": {"query": "test"}},
                ],
            },
            {
                "role": "tool",
                "content": '{"results": []}',
                "name": "search",
                "tool_call_id": "call_0",
            },
        ]
        _system, contents = self.provider._convert_messages(messages)
        self.assertEqual(len(contents), 2)
        self.assertEqual(contents[0].role, "model")
        # Should have function_call part
        parts = contents[0].parts
        self.assertTrue(len(parts) >= 1)

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_raw_content_match_normalizes_mapping_like_args(self, mock_client):
        """Gemini SDK arg containers should still match parsed tool_calls."""

        class ArgsContainer:
            def items(self):
                return {
                    "path": "C:/data/Coffe_sales.xlsx",
                    "sample_rows": 5,
                    "nested": {"columns": ("Tanggal", "Pendapatan")},
                }.items()

        raw_content = self._raw_tool_content(
            "dashboard_generator_extract_metadata",
            ArgsContainer(),
        )
        messages = [
            {
                "role": "assistant",
                "content": "",
                "raw_content": raw_content,
                "tool_calls": [
                    {
                        "id": "call_0",
                        "name": "dashboard_generator_extract_metadata",
                        "arguments": json.dumps(
                            {
                                "path": "C:/data/Coffe_sales.xlsx",
                                "sample_rows": 5,
                                "nested": {"columns": ["Tanggal", "Pendapatan"]},
                            }
                        ),
                    },
                ],
            },
            {
                "role": "tool",
                "content": '{"row_count": 3636}',
                "name": "dashboard_generator_extract_metadata",
                "tool_call_id": "call_0",
            },
        ]

        _system, contents = self.provider._convert_messages(messages)

        self.assertEqual(len(contents), 2)
        self.assertIs(contents[0], raw_content)

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_mismatched_raw_content_skips_tool_exchange(self, mock_client):
        """Partial raw Gemini content must not be replayed or reconstructed.

        Reconstructing function_call parts from generic persisted tool_calls
        drops Gemini thought_signature metadata and triggers intermittent 400s.
        """
        messages = [
            {
                "role": "assistant",
                "content": "",
                "raw_content": self._raw_tool_content("search", {"query": "test"}),
                "tool_calls": [
                    {"id": "call_0", "name": "search", "arguments": {"query": "test"}},
                    {"id": "call_1", "name": "calculate", "arguments": {"expr": "1+1"}},
                ],
            },
            {
                "role": "tool",
                "content": '{"results": []}',
                "name": "search",
                "tool_call_id": "call_0",
            },
            {
                "role": "tool",
                "content": '{"result": 2}',
                "name": "calculate",
                "tool_call_id": "call_1",
            },
        ]

        _system, contents = self.provider._convert_messages(messages)

        self.assertEqual(contents, [])

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_missing_raw_content_skips_tool_exchange(self, mock_client):
        """Persisted Gemini tool-call turns without raw_content are unsafe to replay."""
        messages = [
            {"role": "user", "content": "Find info about X."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_0", "name": "search", "arguments": {"query": "X"}},
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

        _system, contents = self.provider._convert_messages(messages)

        self.assertEqual(len(contents), 2)
        self.assertEqual(contents[0].role, "user")
        self.assertEqual(contents[1].role, "model")
        self.assertEqual(contents[1].parts[0].text, "Here is what I found about X.")

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_full_conversation_flow(self, mock_client):
        """Test converting a full multi-turn conversation."""
        raw_content = self._raw_tool_content("search", {"query": "X"})
        messages = [
            {"role": "system", "content": "You are an agent."},
            {"role": "user", "content": "Find info about X."},
            {
                "role": "assistant",
                "content": "I'll search for X.",
                "raw_content": raw_content,
                "tool_calls": [
                    {"id": "call_0", "name": "search", "arguments": {"query": "X"}},
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
        self.assertIs(contents[1], raw_content)

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
            {
                "type": "function",
                "function": {"name": "search", "description": "Search"},
            },
            {
                "type": "function",
                "function": {"name": "calc", "description": "Calculate"},
            },
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

    def test_playwright_schema_keywords_are_sanitized(self):
        """Playwright MCP schemas should not trip Gemini FunctionDeclaration validation."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "playwright_browser_drop",
                    "description": "Drop files or MIME-typed data",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string"},
                            "data": {
                                "type": "object",
                                "propertyNames": {"type": "string"},
                                "additionalProperties": {"type": "string"},
                            },
                        },
                        "required": ["target"],
                        "additionalProperties": False,
                    },
                },
            }
        ]

        result = self.provider._convert_tools(tools)

        self.assertEqual(len(result), 1)
        declaration = result[0].function_declarations[0]
        params = declaration.parameters.model_dump(by_alias=True, exclude_none=True)
        self.assertNotIn("propertyNames", params["properties"]["data"])
        self.assertNotIn("additionalProperties", params)
        self.assertNotIn("additionalProperties", params["properties"]["data"])
        self.assertNotIn("additional_properties", str(declaration.model_dump(exclude_none=True)))

    def test_playwright_additional_properties_are_not_serialized(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "playwright_browser_fill_form",
                    "description": "Fill multiple form fields",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "fields": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "target": {"type": "string"},
                                        "value": {
                                            "type": "object",
                                            "additionalProperties": {"type": "string"},
                                        },
                                    },
                                    "required": ["target"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["fields"],
                        "additionalProperties": False,
                    },
                },
            }
        ]

        result = self.provider._convert_tools(tools)

        declaration = result[0].function_declarations[0]
        serialized = declaration.model_dump(exclude_none=True)
        params = declaration.parameters.model_dump(by_alias=True, exclude_none=True)
        item_schema = params["properties"]["fields"]["items"]
        self.assertNotIn("additionalProperties", params)
        self.assertNotIn("additionalProperties", item_schema)
        self.assertNotIn("additionalProperties", item_schema["properties"]["value"])
        self.assertNotIn("additional_properties", str(serialized))

    def test_invalid_tool_schema_is_skipped_with_warning(self):
        tools = [
            {"type": "function", "function": {"name": "bad_tool", "parameters": {}}},
            {"type": "function", "function": {"name": "good_tool", "parameters": {}}},
        ]

        with (
            patch("google.genai.types.FunctionDeclaration") as declaration,
            patch("google.genai.types.Tool") as tool_cls,
            self.assertLogs("openbench.intelligence.llm_providers", level="WARNING") as logs,
        ):
            declaration.side_effect = [ValueError("bad schema"), "valid-declaration"]
            tool_cls.return_value = "tool"
            result = self.provider._convert_tools(tools)

        self.assertEqual(result, ["tool"])
        tool_cls.assert_called_once_with(function_declarations=["valid-declaration"])
        self.assertIn("bad_tool", "\n".join(logs.output))


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


class TestGeminiLLMProviderExtractText(unittest.TestCase):
    """Tests for _extract_text_from_parts (thought filtering)."""

    def setUp(self):
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        self.provider = GeminiLLMProvider(api_key="test")

    def _make_response(self, parts):
        """Build a mock Gemini response with given parts."""
        mock_candidate = MagicMock()
        mock_candidate.content.parts = parts
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        return mock_response

    def _make_part(self, text=None, thought=False, function_call=None):
        """Build a mock Part."""
        part = MagicMock()
        part.text = text
        part.thought = thought
        part.function_call = function_call
        return part

    def test_regular_text_extracted(self):
        """Text parts without thought=True are included."""
        parts = [self._make_part(text="Hello world")]
        result = self.provider._extract_text_from_parts(self._make_response(parts))
        self.assertEqual(result, "Hello world")

    def test_thought_parts_excluded(self):
        """Parts with thought=True are filtered out."""
        parts = [
            self._make_part(text="Let me think about this...", thought=True),
            self._make_part(text="Here is the answer."),
        ]
        result = self.provider._extract_text_from_parts(self._make_response(parts))
        self.assertEqual(result, "Here is the answer.")

    def test_only_thought_parts_returns_empty(self):
        """Response with only thought parts returns empty string."""
        parts = [
            self._make_part(text="Internal reasoning...", thought=True),
            self._make_part(text="More reasoning...", thought=True),
        ]
        result = self.provider._extract_text_from_parts(self._make_response(parts))
        self.assertEqual(result, "")

    def test_function_call_parts_excluded(self):
        """Parts with function_call are filtered out."""
        fc = MagicMock()
        fc.name = "search"
        parts = [
            self._make_part(text="Calling tool", function_call=fc),
            self._make_part(text="Result text"),
        ]
        result = self.provider._extract_text_from_parts(self._make_response(parts))
        self.assertEqual(result, "Result text")

    def test_empty_candidates(self):
        """Response with empty candidates returns empty string."""
        mock_response = MagicMock()
        mock_response.candidates = []
        result = self.provider._extract_text_from_parts(mock_response)
        self.assertEqual(result, "")

    def test_no_content(self):
        """Response with no content returns empty string."""
        mock_candidate = MagicMock()
        mock_candidate.content = None
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        result = self.provider._extract_text_from_parts(mock_response)
        self.assertEqual(result, "")

    def test_empty_parts(self):
        """Response with empty parts list returns empty string."""
        result = self.provider._extract_text_from_parts(self._make_response([]))
        self.assertEqual(result, "")

    def test_mixed_thought_text_function_call(self):
        """Mixed parts: only non-thought, non-function_call text extracted."""
        fc = MagicMock()
        parts = [
            self._make_part(text="Thinking...", thought=True),
            self._make_part(text="Calling tool", function_call=fc),
            self._make_part(text="Answer part 1"),
            self._make_part(text="Answer part 2"),
        ]
        result = self.provider._extract_text_from_parts(self._make_response(parts))
        self.assertEqual(result, "Answer part 1Answer part 2")


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


class TestGeminiLLMProviderGenerateStream(unittest.TestCase):
    """Tests for generate_stream() method."""

    def setUp(self):
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        self.provider = GeminiLLMProvider(api_key="test-key")

    def _make_chunk(self, text=None, thought=False, function_call=None, usage=None):
        """Build a mock streaming chunk."""
        parts = []
        if text is not None or thought or function_call:
            part = MagicMock()
            part.text = text
            part.thought = thought
            part.function_call = function_call
            parts.append(part)

        candidate = MagicMock()
        candidate.content.parts = parts

        chunk = MagicMock()
        chunk.candidates = [candidate]

        if usage:
            chunk.usage_metadata.prompt_token_count = usage.get("prompt", 0)
            chunk.usage_metadata.candidates_token_count = usage.get("completion", 0)
            chunk.usage_metadata.total_token_count = usage.get("total", 0)
        else:
            chunk.usage_metadata = None

        return chunk

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_stream_text_chunks(self, mock_get_client):
        """Text chunks are yielded as LLMResponse deltas."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        chunks = [
            self._make_chunk(text="Hello "),
            self._make_chunk(text="world!", usage={"prompt": 10, "completion": 5, "total": 15}),
        ]
        mock_client.models.generate_content_stream.return_value = iter(chunks)

        results = list(self.provider.generate_stream("test", model="gemini-2.5-flash"))
        texts = [r.text for r in results]
        # Text deltas plus a trailing usage-bearing final (empty text).
        self.assertEqual(texts, ["Hello ", "world!", ""])
        self.assertEqual(results[-1].tokens_used, 15)
        self.assertEqual(results[-1].metadata["prompt_tokens"], 10)
        self.assertEqual(results[-1].metadata["completion_tokens"], 5)

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_stream_filters_thought_parts(self, mock_get_client):
        """Thought parts are filtered out during streaming."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        chunks = [
            self._make_chunk(text="Let me think...", thought=True),
            self._make_chunk(text="More thinking...", thought=True),
            self._make_chunk(text="The answer is 42."),
            self._make_chunk(usage={"prompt": 10, "completion": 20, "total": 30}),
        ]
        # Last chunk has no text parts
        last = chunks[-1]
        last.candidates[0].content.parts = []
        mock_client.models.generate_content_stream.return_value = iter(chunks)

        results = list(self.provider.generate_stream("test", model="gemini-3-flash-preview"))
        texts = [r.text for r in results]
        self.assertEqual(texts, ["The answer is 42.", ""])
        self.assertEqual(results[-1].tokens_used, 30)

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_stream_text_only_ends_with_usage_response(self, mock_get_client):
        """A text-only stream must end with a usage-bearing final response.

        Without it, streamed turns meter as zero tokens (the deltas all
        carry tokens_used=0) — the final response is what usage metering
        and BaseAgent's per-turn accounting read.
        """
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        chunks = [
            self._make_chunk(text="Halo"),
            self._make_chunk(text=" dunia", usage={"prompt": 7, "completion": 3, "total": 10}),
        ]
        mock_client.models.generate_content_stream.return_value = iter(chunks)

        results = list(self.provider.generate_stream("test", model="gemini-3.5-flash"))

        final = results[-1]
        self.assertEqual(final.text, "")
        self.assertEqual(final.tokens_used, 10)
        self.assertEqual(final.metadata["prompt_tokens"], 7)
        self.assertEqual(final.metadata["completion_tokens"], 3)
        self.assertIsNone(getattr(final, "tool_calls", None))
        # Accumulated visible text is unchanged by the trailing response.
        self.assertEqual("".join(r.text for r in results), "Halo dunia")

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_stream_empty_response_yields_final(self, mock_get_client):
        """Empty response (Confidence Dropout) yields final with usage metadata."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Only thought parts, no actual text
        chunks = [
            self._make_chunk(text="Reasoning...", thought=True),
            self._make_chunk(
                text="Done thinking.",
                thought=True,
                usage={"prompt": 50, "completion": 100, "total": 150},
            ),
        ]
        mock_client.models.generate_content_stream.return_value = iter(chunks)

        results = list(self.provider.generate_stream("test", model="gemini-3-flash-preview"))

        # Should yield exactly one final response with usage metadata
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].text, "")
        self.assertEqual(results[0].tokens_used, 150)

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_stream_tool_calls(self, mock_get_client):
        """Tool calls in last chunk are yielded as final response."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        fc = MagicMock()
        fc.name = "search"
        fc.args = {"q": "test"}

        chunks = [
            self._make_chunk(function_call=fc, usage={"prompt": 5, "completion": 5, "total": 10}),
        ]
        mock_client.models.generate_content_stream.return_value = iter(chunks)

        results = list(self.provider.generate_stream("test", model="gemini-2.5-flash"))

        self.assertEqual(len(results), 1)
        self.assertTrue(hasattr(results[0], "tool_calls"))
        self.assertEqual(results[0].tool_calls[0]["name"], "search")

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_stream_tool_calls_in_earlier_chunk_not_last(self, mock_get_client):
        """Regression: function_call parts emitted in an EARLIER chunk must
        still be captured. Before the fix, generate_stream only looked at
        the last chunk, so function calls that arrived mid-stream silently
        vanished and the caller saw "Model returned no text output".
        """
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        fc = MagicMock()
        fc.name = "do_thing"
        fc.args = {"x": 1}

        chunks = [
            # Tool call arrives on the first chunk...
            self._make_chunk(function_call=fc),
            # ...but a later usage-only chunk is the LAST one.
            self._make_chunk(usage={"prompt": 11000, "completion": 24, "total": 11024}),
        ]
        # Ensure the last chunk has no parts at all
        chunks[-1].candidates[0].content.parts = []
        mock_client.models.generate_content_stream.return_value = iter(chunks)

        results = list(self.provider.generate_stream("test", model="gemini-3-flash-preview"))

        # Exactly one final response with the tool call attached
        self.assertEqual(len(results), 1)
        self.assertTrue(hasattr(results[0], "tool_calls"))
        self.assertEqual(len(results[0].tool_calls), 1)
        self.assertEqual(results[0].tool_calls[0]["name"], "do_thing")
        self.assertEqual(results[0].tool_calls[0]["arguments"], {"x": 1})
        # Usage from the last chunk still propagates
        self.assertEqual(results[0].tokens_used, 11024)

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_stream_multiple_tool_calls_across_chunks(self, mock_get_client):
        """Multiple function_call parts split across chunks are all captured
        with unique call ids and merged raw_content for Gemini replay."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        fc1 = MagicMock(name="fc1")
        fc1.name = "search"
        fc1.args = {"q": "a"}
        fc2 = MagicMock(name="fc2")
        fc2.name = "calculate"
        fc2.args = {"expr": "1+1"}

        chunks = [
            self._make_chunk(function_call=fc1),
            self._make_chunk(function_call=fc2),
            self._make_chunk(usage={"prompt": 10, "completion": 30, "total": 40}),
        ]
        chunks[-1].candidates[0].content.parts = []
        mock_client.models.generate_content_stream.return_value = iter(chunks)

        results = list(self.provider.generate_stream("test", model="gemini-2.5-flash"))

        self.assertEqual(len(results), 1)
        tool_calls = results[0].tool_calls
        self.assertEqual(len(tool_calls), 2)
        self.assertEqual({tc["name"] for tc in tool_calls}, {"search", "calculate"})
        # Unique ids (no collisions from restarting the counter per chunk)
        self.assertEqual(len({tc["id"] for tc in tool_calls}), 2)
        self.assertTrue(hasattr(results[0], "raw_content"))
        raw_parts = results[0].raw_content.parts
        self.assertEqual(len(raw_parts), 2)
        self.assertIs(raw_parts[0].function_call, fc1)
        self.assertIs(raw_parts[1].function_call, fc2)

    @patch("openbench.intelligence.llm_providers.GeminiLLMProvider._get_client")
    def test_stream_empty_response_includes_diagnostics(self, mock_get_client):
        """Empty response must surface diagnostics in metadata so the caller
        can see WHY the model returned nothing."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        chunks = [
            self._make_chunk(
                text="Internal reasoning…",
                thought=True,
                usage={"prompt": 11000, "completion": 14, "total": 11014},
            ),
        ]
        # Simulate finish_reason = "MAX_TOKENS" on the final chunk
        chunks[-1].candidates[0].finish_reason = "MAX_TOKENS"
        mock_client.models.generate_content_stream.return_value = iter(chunks)

        results = list(self.provider.generate_stream("test", model="gemini-3-flash-preview"))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].text, "")
        diagnostics = results[0].metadata.get("empty_response_diagnostics")
        self.assertIsNotNone(diagnostics, "metadata must carry diagnostics")
        self.assertEqual(diagnostics["finish_reason"], "MAX_TOKENS")
        self.assertEqual(diagnostics["part_types"]["thought"], 1)
        self.assertEqual(diagnostics["part_types"]["text"], 0)


class TestGeminiLLMProviderDescribeResponseParts(unittest.TestCase):
    """Tests for the _describe_response_parts diagnostic helper."""

    def setUp(self):
        from openbench.intelligence.llm_providers import GeminiLLMProvider

        self.provider = GeminiLLMProvider(api_key="test")

    def _make_part(
        self,
        text=None,
        thought=False,
        function_call=None,
        inline_data=None,
        thought_signature=None,
    ):
        part = MagicMock(
            spec=[
                "text",
                "thought",
                "function_call",
                "inline_data",
                "thought_signature",
                "executable_code",
            ]
        )
        part.text = text
        part.thought = thought
        part.function_call = function_call
        part.inline_data = inline_data
        part.thought_signature = thought_signature
        part.executable_code = None
        return part

    def _make_response(self, parts, finish_reason=None, block_reason=None):
        candidate = MagicMock()
        candidate.content.parts = parts
        candidate.finish_reason = finish_reason
        response = MagicMock()
        response.candidates = [candidate]
        if block_reason is not None:
            response.prompt_feedback.block_reason = block_reason
        else:
            response.prompt_feedback = None
        return response

    def test_counts_mixed_part_types(self):
        fc = MagicMock()
        fc.name = "x"
        parts = [
            self._make_part(text="Hello"),
            self._make_part(text="Thinking", thought=True),
            self._make_part(function_call=fc),
        ]
        result = self.provider._describe_response_parts(
            self._make_response(parts, finish_reason="STOP")
        )
        self.assertEqual(result["part_types"]["text"], 1)
        self.assertEqual(result["part_types"]["thought"], 1)
        self.assertEqual(result["part_types"]["function_call"], 1)
        self.assertEqual(result["finish_reason"], "STOP")

    def test_detects_thought_signature(self):
        parts = [
            self._make_part(text="Thinking", thought=True, thought_signature=b"sig"),
        ]
        result = self.provider._describe_response_parts(self._make_response(parts))
        self.assertTrue(result["has_thought_signature"])

    def test_surfaces_block_reason(self):
        result = self.provider._describe_response_parts(
            self._make_response([], block_reason="SAFETY")
        )
        self.assertEqual(result["block_reason"], "SAFETY")

    def test_empty_response_is_safe(self):
        response = MagicMock()
        response.candidates = []
        response.prompt_feedback = None
        result = self.provider._describe_response_parts(response)
        self.assertEqual(result["finish_reason"], None)
        self.assertEqual(result["part_types"]["text"], 0)


if __name__ == "__main__":
    unittest.main()
