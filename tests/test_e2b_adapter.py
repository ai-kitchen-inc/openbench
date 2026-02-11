"""Tests for E2BAdapter."""

import unittest
from unittest.mock import patch

from openbench.adapters.e2b import E2BAdapter
from openbench.core.abstractions import FrameworkAdapter


class TestE2BAdapterInit(unittest.TestCase):
    """Test E2BAdapter initialization."""

    def test_init_stores_code(self):
        """Test that code is stored."""
        adapter = E2BAdapter(code="result = input_data")
        self.assertEqual(adapter.code, "result = input_data")

    def test_init_default_template(self):
        """Test default template."""
        adapter = E2BAdapter(code="result = 1")
        self.assertEqual(adapter.template, "python-data-science")

    def test_init_custom_template(self):
        """Test custom template."""
        adapter = E2BAdapter(code="result = 1", template="custom-template")
        self.assertEqual(adapter.template, "custom-template")

    def test_init_default_packages(self):
        """Test default packages is empty list."""
        adapter = E2BAdapter(code="result = 1")
        self.assertEqual(adapter.packages, [])

    def test_init_with_packages(self):
        """Test initialization with packages."""
        adapter = E2BAdapter(code="result = 1", packages=["pandas", "numpy"])
        self.assertEqual(adapter.packages, ["pandas", "numpy"])

    def test_is_framework_adapter(self):
        """Test that E2BAdapter is a FrameworkAdapter."""
        adapter = E2BAdapter(code="result = 1")
        self.assertIsInstance(adapter, FrameworkAdapter)


class TestE2BAdapterProperties(unittest.TestCase):
    """Test E2BAdapter properties."""

    def test_framework_name(self):
        """Test framework_name property."""
        adapter = E2BAdapter(code="result = 1")
        self.assertEqual(adapter.framework_name, "e2b")


class TestE2BAdapterInvoke(unittest.TestCase):
    """Test E2BAdapter invoke methods."""

    def test_invoke_requires_e2b_package(self):
        """Test invoke raises ImportError when e2b not installed."""
        adapter = E2BAdapter(code="result = input_data")

        with patch.dict("sys.modules", {"e2b": None}):
            with self.assertRaises(ImportError) as ctx:
                adapter.invoke({"key": "value"})

            self.assertIn("E2B", str(ctx.exception))

    def test_invoke_stores_correct_template(self):
        """Test adapter stores correct template for sandbox creation."""
        adapter = E2BAdapter(code="result = input_data", template="custom-env")
        self.assertEqual(adapter.template, "custom-env")

    def test_invoke_propagates_import_error(self):
        """Test invoke raises clear ImportError when e2b missing."""
        adapter = E2BAdapter(code="result = 1")

        with self.assertRaises(ImportError) as ctx:
            adapter.invoke("test")

        self.assertIn("e2b", str(ctx.exception).lower())


class TestE2BAdapterComposition(unittest.TestCase):
    """Test E2BAdapter composition via Chainable inheritance."""

    def test_is_chainable(self):
        """Test that FrameworkAdapter inherits Chainable."""
        from openbench.core.chainable import Chainable

        adapter = E2BAdapter(code="result = input_data")
        self.assertIsInstance(adapter, Chainable)

    def test_pipe_operator(self):
        """Test | operator creates Chain."""
        from openbench.core.chainable import Chain

        adapter1 = E2BAdapter(code="result = input_data")
        adapter2 = E2BAdapter(code="result = input_data")

        chain = adapter1 | adapter2

        self.assertIsInstance(chain, Chain)

    def test_parallel_operator(self):
        """Test & operator creates Parallel."""
        from openbench.core.chainable import Parallel

        adapter1 = E2BAdapter(code="result = input_data")
        adapter2 = E2BAdapter(code="result = input_data")

        parallel = adapter1 & adapter2

        self.assertIsInstance(parallel, Parallel)


if __name__ == "__main__":
    unittest.main()
