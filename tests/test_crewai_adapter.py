"""Tests for CrewAIAdapter."""

import unittest
from unittest.mock import MagicMock

from openbench.adapters.crewai import CrewAIAdapter
from openbench.core.abstractions import FrameworkAdapter


class TestCrewAIAdapterInit(unittest.TestCase):
    """Test CrewAIAdapter initialization."""

    def test_init_stores_crew(self):
        """Test that crew is stored."""
        mock_crew = MagicMock()
        adapter = CrewAIAdapter(mock_crew)
        self.assertEqual(adapter.crew, mock_crew)

    def test_is_framework_adapter(self):
        """Test that CrewAIAdapter is a FrameworkAdapter."""
        adapter = CrewAIAdapter(MagicMock())
        self.assertIsInstance(adapter, FrameworkAdapter)


class TestCrewAIAdapterProperties(unittest.TestCase):
    """Test CrewAIAdapter properties."""

    def test_framework_name(self):
        """Test framework_name property."""
        adapter = CrewAIAdapter(MagicMock())
        self.assertEqual(adapter.framework_name, "crewai")


class TestCrewAIAdapterInvoke(unittest.TestCase):
    """Test CrewAIAdapter invoke methods."""

    def test_invoke_calls_kickoff_with_dict(self):
        """Test invoke calls crew.kickoff() with dict inputs."""
        mock_crew = MagicMock()
        mock_crew.kickoff.return_value = "crew_result"
        adapter = CrewAIAdapter(mock_crew)

        result = adapter.invoke({"topic": "AI safety"})

        mock_crew.kickoff.assert_called_once_with(inputs={"topic": "AI safety"})
        self.assertEqual(result, "crew_result")

    def test_invoke_wraps_non_dict_input(self):
        """Test invoke wraps non-dict input in {'input': ...}."""
        mock_crew = MagicMock()
        mock_crew.kickoff.return_value = "result"
        adapter = CrewAIAdapter(mock_crew)

        adapter.invoke("raw string input")

        mock_crew.kickoff.assert_called_once_with(inputs={"input": "raw string input"})

    def test_invoke_wraps_list_input(self):
        """Test invoke wraps list input."""
        mock_crew = MagicMock()
        mock_crew.kickoff.return_value = "result"
        adapter = CrewAIAdapter(mock_crew)

        adapter.invoke([1, 2, 3])

        mock_crew.kickoff.assert_called_once_with(inputs={"input": [1, 2, 3]})

    def test_invoke_propagates_exception(self):
        """Test invoke propagates exceptions from crew."""
        mock_crew = MagicMock()
        mock_crew.kickoff.side_effect = RuntimeError("CrewAI error")
        adapter = CrewAIAdapter(mock_crew)

        with self.assertRaises(RuntimeError) as ctx:
            adapter.invoke({"topic": "test"})

        self.assertIn("CrewAI error", str(ctx.exception))

    def test_invoke_with_none_input(self):
        """Test invoke with None input wraps as {'input': None}."""
        mock_crew = MagicMock()
        mock_crew.kickoff.return_value = "result"
        adapter = CrewAIAdapter(mock_crew)

        adapter.invoke(None)

        mock_crew.kickoff.assert_called_once_with(inputs={"input": None})


class TestCrewAIAdapterComposition(unittest.TestCase):
    """Test CrewAIAdapter composition via Chainable inheritance."""

    def test_is_chainable(self):
        """Test that FrameworkAdapter inherits Chainable."""
        from openbench.core.chainable import Chainable

        adapter = CrewAIAdapter(MagicMock())
        self.assertIsInstance(adapter, Chainable)

    def test_pipe_operator(self):
        """Test | operator creates Chain."""
        from openbench.core.chainable import Chain

        adapter1 = CrewAIAdapter(MagicMock())
        adapter2 = CrewAIAdapter(MagicMock())

        chain = adapter1 | adapter2

        self.assertIsInstance(chain, Chain)

    def test_parallel_operator(self):
        """Test & operator creates Parallel."""
        from openbench.core.chainable import Parallel

        adapter1 = CrewAIAdapter(MagicMock())
        adapter2 = CrewAIAdapter(MagicMock())

        parallel = adapter1 & adapter2

        self.assertIsInstance(parallel, Parallel)


if __name__ == "__main__":
    unittest.main()
