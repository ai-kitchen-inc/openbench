"""
Google ADK framework adapter for OpenBench.

Provides two modes of operation:
1. Wrap existing Google ADK agents (bring your own agent)
2. Direct Gemini API integration (model-based)

Supports Google Generative AI models: gemini-2.5-flash, gemini-2.5-pro, gemini-3-flash-preview
"""
from __future__ import annotations


import logging
import os
from collections.abc import Iterator
from typing import Any

from openbench.core import FrameworkAdapter

logger = logging.getLogger(__name__)


class GoogleADKAdapter(FrameworkAdapter):
    """
    Adapter for Google Generative AI / Google ADK.

    Supports two modes:
    1. Model mode: Direct Gemini API calls (default)
    2. Agent mode: Wrap existing Google ADK agent

    Example (Model mode):
        ```python
        from openbench.adapters import GoogleADKAdapter
        from openbench.data.sources import PDFSource
        from openbench.output.generators import PDFGenerator
        from openbench.core.layers import DataLayer, IntelligenceLayer, OutputLayer

        # Create adapter with model
        adapter = GoogleADKAdapter(
            model="gemini-2.5-flash",
            system_instruction="You are a document analyst."
        )

        # Use in workflow
        workflow = (
            DataLayer(sources=PDFSource("./doc.pdf"))
            | IntelligenceLayer(agents=adapter)
            | OutputLayer(generators=PDFGenerator())
        )

        result = workflow.invoke({"goal": "Summarize this document"})
        ```

    Example (Agent mode):
        ```python
        from google.adk import Agent

        # Your existing Google ADK agent
        my_agent = Agent(name="analyst", model="gemini-2.5-flash")

        # Wrap in adapter
        adapter = GoogleADKAdapter(agent=my_agent)
        ```
    """

    def __init__(
        self,
        model: str | None = None,
        agent: Any | None = None,
        api_key: str | None = None,
        system_instruction: str | None = None,
        generation_config: dict[str, Any] | None = None,
        safety_settings: list[dict[str, Any]] | None = None,
    ):
        """
        Initialize the Google ADK adapter.

        Args:
            model: Gemini model name (e.g., "gemini-2.5-flash", "gemini-2.5-pro").
                   Required if agent is not provided.
            agent: Existing Google ADK Agent instance (optional).
                   If provided, model parameter is ignored.
            api_key: Google API key. If not provided, reads from GOOGLE_API_KEY env.
            system_instruction: System prompt for the model.
            generation_config: Generation parameters (temperature, max_output_tokens, etc.)
            safety_settings: Content safety filter settings.

        Raises:
            ValueError: If neither model nor agent is provided.
        """
        if agent is None and model is None:
            raise ValueError("Either 'model' or 'agent' must be provided")

        self.agent = agent
        self.model_name = model
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.system_instruction = system_instruction
        self.generation_config = generation_config or {}
        self.safety_settings = safety_settings

        self._client = None
        self._model = None

        # Set default generation config
        if "temperature" not in self.generation_config:
            self.generation_config["temperature"] = 0.7
        if "max_output_tokens" not in self.generation_config:
            self.generation_config["max_output_tokens"] = 8192

        logger.debug(
            f"GoogleADKAdapter initialized (model={model}, agent_mode={agent is not None})"
        )

    @property
    def framework_name(self) -> str:
        """Return framework name."""
        return "google_adk"

    def _init_client(self) -> None:
        """Initialize Google Generative AI client."""
        if self._client is not None:
            return

        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "google-generativeai is required for GoogleADKAdapter. "
                "Install with: pip install google-generativeai"
            ) from None

        if not self.api_key:
            raise ValueError(
                "Google API key is required. Provide via 'api_key' parameter "
                "or set GOOGLE_API_KEY environment variable."
            )

        genai.configure(api_key=self.api_key)
        self._client = genai

        # Initialize model
        if self.model_name:
            self._model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=self.system_instruction,
                generation_config=self.generation_config,
                safety_settings=self.safety_settings,
            )

        logger.debug(f"Google GenAI client initialized (model={self.model_name})")

    def _extract_content(self, input: Any) -> str:
        """
        Extract text content from various input formats.

        Args:
            input: Input data (dict, RawData, ExecutionResult, str, etc.)

        Returns:
            Extracted text content
        """
        if isinstance(input, str):
            return input

        if hasattr(input, "content"):
            return str(input.content)

        if hasattr(input, "output"):
            return str(input.output)

        if not isinstance(input, dict):
            return str(input)

        # Handle dict inputs from various layers
        if "raw_data" in input:
            return self._extract_from_raw_data(input["raw_data"])

        if "intelligence_output" in input:
            return self._extract_from_output(input["intelligence_output"])

        if "goal" in input:
            goal = input["goal"]
            data = input.get("data", "")
            return f"{goal}\n\nData:\n{data}" if data else goal

        if "content" in input:
            return str(input["content"])

        return str(input)

    def _extract_from_raw_data(self, raw_data: Any) -> str:
        """Extract content from raw_data field."""
        if isinstance(raw_data, list):
            contents = [
                str(item.content) if hasattr(item, "content") else str(item) for item in raw_data
            ]
            return "\n\n".join(contents)

        if hasattr(raw_data, "content"):
            return str(raw_data.content)

        return str(raw_data)

    def _extract_from_output(self, output: Any) -> str:
        """Extract content from intelligence_output field."""
        if isinstance(output, dict) and "content" in output:
            return str(output["content"])

        if hasattr(output, "output"):
            return str(output.output)

        if hasattr(output, "content"):
            return str(output.content)

        return str(output)

    def _build_prompt(self, content: str, goal: str | None = None) -> str:
        """
        Build prompt from content and optional goal.

        Args:
            content: Main content
            goal: Optional task goal

        Returns:
            Formatted prompt
        """
        if goal:
            return f"""Task: {goal}

Content:
{content}

Please complete the task based on the content provided."""
        return content

    def invoke(self, input: Any, config: Any | None = None) -> dict[str, Any]:
        """
        Execute the Google ADK adapter.

        Args:
            input: Input data (dict from DataLayer, RawData, string, etc.)
            config: Optional configuration

        Returns:
            Dict containing:
                - content: Generated text
                - model: Model used
                - tokens_used: Token count (if available)
                - metadata: Additional metadata
        """
        # Agent mode: delegate to existing agent
        if self.agent is not None:
            return self._invoke_agent(input, config)

        # Model mode: direct Gemini API call
        return self._invoke_model(input, config)

    def _invoke_agent(self, input: Any, config: Any | None = None) -> dict[str, Any]:
        """
        Invoke existing Google ADK agent.

        Args:
            input: Input data
            config: Optional configuration

        Returns:
            Agent output wrapped in dict
        """
        logger.debug("Invoking Google ADK agent")

        # Try different agent interfaces
        if hasattr(self.agent, "run"):
            response = self.agent.run(input)
            output = response.output if hasattr(response, "output") else response
        elif hasattr(self.agent, "invoke"):
            output = self.agent.invoke(input)
        elif hasattr(self.agent, "generate"):
            output = self.agent.generate(input)
        elif callable(self.agent):
            output = self.agent(input)
        else:
            raise NotImplementedError(
                "Google ADK agent must have 'run()', 'invoke()', 'generate()' method or be callable"
            )

        return {
            "content": str(output),
            "model": "google_adk_agent",
            "tokens_used": None,
            "metadata": {"mode": "agent"},
        }

    def _invoke_model(self, input: Any, config: Any | None = None) -> dict[str, Any]:
        """
        Invoke Gemini model directly.

        Args:
            input: Input data
            config: Optional configuration (can override generation_config)

        Returns:
            Dict with generated content and metadata
        """
        self._init_client()

        # Extract content from input
        content = self._extract_content(input)

        # Extract goal if provided
        goal = None
        if isinstance(input, dict):
            goal = input.get("goal") or input.get("query") or input.get("task")

        # Build prompt
        prompt = self._build_prompt(content, goal)

        logger.debug(f"Invoking Gemini model: {self.model_name}")
        logger.debug(f"Prompt length: {len(prompt)} chars")

        try:
            # Apply config overrides if provided
            gen_config = self.generation_config.copy()
            if config and isinstance(config, dict):
                gen_config.update(config)

            # Generate response
            response = self._model.generate_content(
                prompt,
                generation_config=gen_config,
            )

            # Extract response text
            response_text = response.text

            # Extract token usage if available
            tokens_used = None
            if hasattr(response, "usage_metadata"):
                usage = response.usage_metadata
                tokens_used = {
                    "prompt_tokens": getattr(usage, "prompt_token_count", 0),
                    "completion_tokens": getattr(usage, "candidates_token_count", 0),
                    "total_tokens": getattr(usage, "total_token_count", 0),
                }

            logger.debug(f"Response generated: {len(response_text)} chars")

            return {
                "content": response_text,
                "model": self.model_name,
                "tokens_used": tokens_used,
                "metadata": {
                    "mode": "model",
                    "prompt_length": len(prompt),
                    "response_length": len(response_text),
                },
            }

        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise RuntimeError(f"Failed to generate content with Gemini: {e}") from e

    def stream(self, input: Any, config: Any | None = None) -> Iterator[str]:
        """
        Stream response from Gemini model.

        Args:
            input: Input data
            config: Optional configuration

        Yields:
            Response text chunks
        """
        if self.agent is not None:
            raise NotImplementedError("Streaming not supported in agent mode")

        self._init_client()

        content = self._extract_content(input)
        goal = None
        if isinstance(input, dict):
            goal = input.get("goal")

        prompt = self._build_prompt(content, goal)

        logger.debug(f"Streaming from Gemini model: {self.model_name}")

        response = self._model.generate_content(prompt, stream=True)

        for chunk in response:
            if chunk.text:
                yield chunk.text

    async def ainvoke(self, input: Any, config: Any | None = None) -> dict[str, Any]:
        """
        Async version of invoke.

        Args:
            input: Input data
            config: Optional configuration

        Returns:
            Dict with generated content and metadata
        """
        if self.agent is not None:
            # Check for async agent methods
            if hasattr(self.agent, "arun"):
                response = await self.agent.arun(input)
                output = response.output if hasattr(response, "output") else response
                return {
                    "content": str(output),
                    "model": "google_adk_agent",
                    "tokens_used": None,
                    "metadata": {"mode": "agent", "async": True},
                }
            elif hasattr(self.agent, "ainvoke"):
                output = await self.agent.ainvoke(input)
                return {
                    "content": str(output),
                    "model": "google_adk_agent",
                    "tokens_used": None,
                    "metadata": {"mode": "agent", "async": True},
                }
            # Fallback to sync
            return self._invoke_agent(input, config)

        # Model mode: use async API
        self._init_client()

        content = self._extract_content(input)
        goal = None
        if isinstance(input, dict):
            goal = input.get("goal")

        prompt = self._build_prompt(content, goal)

        logger.debug(f"Async invoking Gemini model: {self.model_name}")

        try:
            response = await self._model.generate_content_async(prompt)

            tokens_used = None
            if hasattr(response, "usage_metadata"):
                usage = response.usage_metadata
                tokens_used = {
                    "prompt_tokens": getattr(usage, "prompt_token_count", 0),
                    "completion_tokens": getattr(usage, "candidates_token_count", 0),
                    "total_tokens": getattr(usage, "total_token_count", 0),
                }

            return {
                "content": response.text,
                "model": self.model_name,
                "tokens_used": tokens_used,
                "metadata": {
                    "mode": "model",
                    "async": True,
                },
            }

        except Exception as e:
            logger.error(f"Gemini async API error: {e}")
            raise RuntimeError(f"Failed to generate content with Gemini: {e}") from e
