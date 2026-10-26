"""Tests for the centralized default constants."""

from __future__ import annotations

import unittest

from openbench.core import constants


class TestConstants(unittest.TestCase):
    def test_timeouts_are_positive(self):
        for name in (
            "DEFAULT_TOOL_TIMEOUT_S",
            "DEFAULT_INDEX_READY_TIMEOUT_S",
            "DEFAULT_PORT_WAIT_TIMEOUT_S",
            "DEFAULT_HEALTH_WAIT_TIMEOUT_S",
            "DEFAULT_PROC_WAIT_TIMEOUT_S",
        ):
            with self.subTest(name=name):
                self.assertGreater(getattr(constants, name), 0)

    def test_batch_and_retry_defaults_are_positive_ints(self):
        self.assertIsInstance(constants.DEFAULT_EMBED_BATCH_SIZE, int)
        self.assertGreater(constants.DEFAULT_EMBED_BATCH_SIZE, 0)
        self.assertIsInstance(constants.DEFAULT_MAX_RETRIES, int)
        self.assertGreater(constants.DEFAULT_MAX_RETRIES, 0)

    def test_module_has_no_internal_dependencies(self):
        # The module docstring promises cycle-free importability; keep it
        # honest by checking it only pulls in __future__.
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(constants))
        imports = [
            node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        modules = {getattr(node, "module", None) or node.names[0].name for node in imports}
        self.assertEqual(modules, {"__future__"})


if __name__ == "__main__":
    unittest.main()
