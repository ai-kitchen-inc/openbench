"""Tests for AG2Adapter."""

import unittest
from unittest.mock import MagicMock, patch

from openbench.core.abstractions import FrameworkAdapter


class TestAG2AdapterInit(unittest.TestCase):
    """Test AG2Adapter initialization."""

    @patch("openbench.adapters.ag2.UserProxyAgent", create=True)
    def test_init_stores_agent(self, mock_user_proxy_cls):
        """Test that agent is stored."""
        from openbench.adapters.ag2 import AG2Adapter

        mock_agent = MagicMock()
        mock_user_proxy = MagicMock()
        adapter = AG2Adapter(mock_agent, user_proxy=mock_user_proxy)

        self.assertEqual(adapter.agent, mock_agent)
        self.assertEqual(adapter.user_proxy, mock_user_proxy)

    @patch("openbench.adapters.ag2.UserProxyAgent", create=True)
    def test_is_framework_adapter(self, mock_user_proxy_cls):
        """Test that AG2Adapter is a FrameworkAdapter."""
        from openbench.adapters.ag2 import AG2Adapter

        adapter = AG2Adapter(MagicMock(), user_proxy=MagicMock())
        self.assertIsInstance(adapter, FrameworkAdapter)

    def test_init_without_user_proxy_requires_autogen(self):
        """Test that init without user_proxy tries to import autogen."""
        from openbench.adapters.ag2 import AG2Adapter

        with self.assertRaises(ImportError) as ctx:
            AG2Adapter(MagicMock())

        self.assertIn("AG2", str(ctx.exception))


class TestAG2AdapterProperties(unittest.TestCase):
    """Test AG2Adapter properties."""

    def test_framework_name(self):
        """Test framework_name property."""
        from openbench.adapters.ag2 import AG2Adapter

        adapter = AG2Adapter(MagicMock(), user_proxy=MagicMock())
        self.assertEqual(adapter.framework_name, "ag2")


class TestAG2AdapterInvoke(unittest.TestCase):
    """Test AG2Adapter invoke methods."""

    def test_invoke_initiates_chat(self):
        """Test invoke calls user_proxy.initiate_chat()."""
        from openbench.adapters.ag2 import AG2Adapter

        mock_agent = MagicMock()
        mock_user_proxy = MagicMock()
        mock_user_proxy.last_message.return_value = {"content": "agent response"}
        adapter = AG2Adapter(mock_agent, user_proxy=mock_user_proxy)

        result = adapter.invoke("analyze this data")

        mock_user_proxy.initiate_chat.assert_called_once_with(
            mock_agent, message="analyze this data"
        )
        self.assertEqual(result, "agent response")

    def test_invoke_converts_non_string_to_str(self):
        """Test invoke converts non-string input to string."""
        from openbench.adapters.ag2 import AG2Adapter

        mock_agent = MagicMock()
        mock_user_proxy = MagicMock()
        mock_user_proxy.last_message.return_value = {"content": "result"}
        adapter = AG2Adapter(mock_agent, user_proxy=mock_user_proxy)

        adapter.invoke({"key": "value"})

        # Should convert dict to string
        call_args = mock_user_proxy.initiate_chat.call_args
        self.assertIsInstance(call_args[1]["message"], str)

    def test_invoke_propagates_exception(self):
        """Test invoke propagates exceptions."""
        from openbench.adapters.ag2 import AG2Adapter

        mock_agent = MagicMock()
        mock_user_proxy = MagicMock()
        mock_user_proxy.initiate_chat.side_effect = RuntimeError("AG2 error")
        adapter = AG2Adapter(mock_agent, user_proxy=mock_user_proxy)

        with self.assertRaises(RuntimeError) as ctx:
            adapter.invoke("test")

        self.assertIn("AG2 error", str(ctx.exception))


class TestAG2AdapterComposition(unittest.TestCase):
    """Test AG2Adapter composition via Chainable inheritance."""

    def test_is_chainable(self):
        """Test that FrameworkAdapter inherits Chainable."""
        from openbench.adapters.ag2 import AG2Adapter
        from openbench.core.chainable import Chainable

        adapter = AG2Adapter(MagicMock(), user_proxy=MagicMock())
        self.assertIsInstance(adapter, Chainable)

    def test_pipe_operator(self):
        """Test | operator creates Chain."""
        from openbench.adapters.ag2 import AG2Adapter
        from openbench.core.chainable import Chain

        adapter1 = AG2Adapter(MagicMock(), user_proxy=MagicMock())
        adapter2 = AG2Adapter(MagicMock(), user_proxy=MagicMock())

        chain = adapter1 | adapter2

        self.assertIsInstance(chain, Chain)

    def test_parallel_operator(self):
        """Test & operator creates Parallel."""
        from openbench.adapters.ag2 import AG2Adapter
        from openbench.core.chainable import Parallel

        adapter1 = AG2Adapter(MagicMock(), user_proxy=MagicMock())
        adapter2 = AG2Adapter(MagicMock(), user_proxy=MagicMock())

        parallel = adapter1 & adapter2

        self.assertIsInstance(parallel, Parallel)


if __name__ == "__main__":
    unittest.main()
