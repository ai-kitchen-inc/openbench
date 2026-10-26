"""Tests for LangChainAdapter."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from openbench.adapters.langchain import LangChainAdapter
from openbench.core.abstractions import FrameworkAdapter


class TestLangChainAdapterInit(unittest.TestCase):
    """Test LangChainAdapter initialization."""

    def test_init_stores_runnable(self):
        """Test that runnable is stored."""
        mock_runnable = MagicMock()
        adapter = LangChainAdapter(mock_runnable)
        self.assertEqual(adapter.runnable, mock_runnable)

    def test_is_framework_adapter(self):
        """Test that LangChainAdapter is a FrameworkAdapter."""
        mock_runnable = MagicMock()
        adapter = LangChainAdapter(mock_runnable)
        self.assertIsInstance(adapter, FrameworkAdapter)


class TestLangChainAdapterProperties(unittest.TestCase):
    """Test LangChainAdapter properties."""

    def test_framework_name(self):
        """Test framework_name property."""
        adapter = LangChainAdapter(MagicMock())
        self.assertEqual(adapter.framework_name, "langchain")


class TestLangChainAdapterInvoke(unittest.TestCase):
    """Test LangChainAdapter invoke methods."""

    def test_invoke_calls_runnable(self):
        """Test invoke delegates to runnable.invoke()."""
        mock_runnable = MagicMock()
        mock_runnable.invoke.return_value = {"output": "result"}
        adapter = LangChainAdapter(mock_runnable)

        result = adapter.invoke({"input": "test"})

        mock_runnable.invoke.assert_called_once_with({"input": "test"}, config=None)
        self.assertEqual(result, {"output": "result"})

    def test_invoke_passes_config(self):
        """Test invoke passes config to runnable."""
        mock_runnable = MagicMock()
        mock_runnable.invoke.return_value = "ok"
        adapter = LangChainAdapter(mock_runnable)
        config = {"callbacks": []}

        adapter.invoke("input", config=config)

        mock_runnable.invoke.assert_called_once_with("input", config=config)

    def test_invoke_with_string_input(self):
        """Test invoke with string input."""
        mock_runnable = MagicMock()
        mock_runnable.invoke.return_value = "response"
        adapter = LangChainAdapter(mock_runnable)

        result = adapter.invoke("hello")

        self.assertEqual(result, "response")

    def test_invoke_propagates_exception(self):
        """Test invoke propagates exceptions from runnable."""
        mock_runnable = MagicMock()
        mock_runnable.invoke.side_effect = RuntimeError("LangChain error")
        adapter = LangChainAdapter(mock_runnable)

        with self.assertRaises(RuntimeError) as ctx:
            adapter.invoke("test")

        self.assertIn("LangChain error", str(ctx.exception))

    def test_ainvoke_calls_runnable(self):
        """Test ainvoke delegates to runnable.ainvoke()."""
        mock_runnable = MagicMock()
        mock_runnable.ainvoke = AsyncMock(return_value={"output": "async_result"})
        adapter = LangChainAdapter(mock_runnable)

        result = asyncio.run(adapter.ainvoke({"input": "test"}))

        mock_runnable.ainvoke.assert_called_once_with({"input": "test"}, config=None)
        self.assertEqual(result, {"output": "async_result"})


class TestLangChainAdapterComposition(unittest.TestCase):
    """Test LangChainAdapter composition via Chainable inheritance."""

    def test_is_chainable(self):
        """Test that FrameworkAdapter inherits Chainable."""
        from openbench.core.chainable import Chainable

        adapter = LangChainAdapter(MagicMock())
        self.assertIsInstance(adapter, Chainable)

    def test_pipe_operator(self):
        """Test | operator creates Chain."""
        from openbench.core.chainable import Chain

        adapter1 = LangChainAdapter(MagicMock())
        adapter2 = LangChainAdapter(MagicMock())

        chain = adapter1 | adapter2

        self.assertIsInstance(chain, Chain)

    def test_parallel_operator(self):
        """Test & operator creates Parallel."""
        from openbench.core.chainable import Parallel

        adapter1 = LangChainAdapter(MagicMock())
        adapter2 = LangChainAdapter(MagicMock())

        parallel = adapter1 & adapter2

        self.assertIsInstance(parallel, Parallel)

    def test_chain_execution(self):
        """Test adapter works in a chain."""
        mock1 = MagicMock()
        mock1.invoke.return_value = "step1_output"
        mock2 = MagicMock()
        mock2.invoke.return_value = "final_output"

        chain = LangChainAdapter(mock1) | LangChainAdapter(mock2)
        result = chain.invoke("initial_input")

        mock1.invoke.assert_called_once()
        mock2.invoke.assert_called_once()
        self.assertEqual(result, "final_output")


if __name__ == "__main__":
    unittest.main()
