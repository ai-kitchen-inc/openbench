"""Tests for Chainable composition."""

from __future__ import annotations

import unittest
from typing import Any

from openbench.core.chainable import (
    Chain,
    Chainable,
    Conditional,
    Lambda,
    Parallel,
    Passthrough,
    Router,
    RunnableConfig,
)


class SimpleChainable(Chainable):
    """Simple chainable for testing."""

    def __init__(self, value: str):
        self.value = value

    def invoke(self, input: Any, config: RunnableConfig | None = None) -> str:
        if input == "":
            return self.value
        elif input:
            return f"{input}_{self.value}"
        else:
            return self.value


class TestChainable(unittest.TestCase):
    """Test Chainable composition."""

    def test_pipe_operator(self):
        """Test pipe operator creates Chain."""
        a = SimpleChainable("a")
        b = SimpleChainable("b")

        chain = a | b

        self.assertIsInstance(chain, Chain)
        result = chain.invoke("")
        self.assertEqual(result, "a_b")

    def test_and_operator(self):
        """Test and operator creates Parallel."""
        a = SimpleChainable("a")
        b = SimpleChainable("b")

        parallel = a & b

        self.assertIsInstance(parallel, Parallel)
        result = parallel.invoke("")
        self.assertEqual(len(result), 2)
        self.assertIn("a", result)
        self.assertIn("b", result)

    def test_chain_sequential(self):
        """Test Chain executes sequentially."""
        a = SimpleChainable("a")
        b = SimpleChainable("b")
        c = SimpleChainable("c")

        chain = Chain([a, b, c])

        result = chain.invoke("")
        # Should be: "" → "a" → "a_b" → "a_b_c"
        self.assertEqual(result, "a_b_c")

    def test_chain_pipe_extension(self):
        """Test extending chain with pipe operator."""
        a = SimpleChainable("a")
        b = SimpleChainable("b")
        c = SimpleChainable("c")

        chain = a | b | c

        result = chain.invoke("")
        self.assertEqual(result, "a_b_c")

    def test_parallel_execution(self):
        """Test Parallel executes all branches."""
        a = SimpleChainable("a")
        b = SimpleChainable("b")
        c = SimpleChainable("c")

        parallel = Parallel([a, b, c])

        result = parallel.invoke("test")
        self.assertEqual(len(result), 3)
        self.assertIn("test_a", result)
        self.assertIn("test_b", result)
        self.assertIn("test_c", result)

    def test_parallel_and_extension(self):
        """Test extending parallel with and operator."""
        a = SimpleChainable("a")
        b = SimpleChainable("b")
        c = SimpleChainable("c")

        parallel = a & b & c

        result = parallel.invoke("test")
        self.assertEqual(len(result), 3)

    def test_conditional_true_branch(self):
        """Test Conditional executes true branch."""
        true_branch = SimpleChainable("true")
        false_branch = SimpleChainable("false")

        conditional = Conditional(
            condition=lambda x: x == "yes",
            true_branch=true_branch,
            false_branch=false_branch,
        )

        result = conditional.invoke("yes")
        self.assertEqual(result, "yes_true")

    def test_conditional_false_branch(self):
        """Test Conditional executes false branch."""
        true_branch = SimpleChainable("true")
        false_branch = SimpleChainable("false")

        conditional = Conditional(
            condition=lambda x: x == "yes",
            true_branch=true_branch,
            false_branch=false_branch,
        )

        result = conditional.invoke("no")
        self.assertEqual(result, "no_false")

    def test_conditional_passthrough(self):
        """Test Conditional with no false branch."""
        true_branch = SimpleChainable("true")

        conditional = Conditional(
            condition=lambda x: x == "yes", true_branch=true_branch, false_branch=None
        )

        # False condition with no false branch → passthrough
        result = conditional.invoke("no")
        self.assertEqual(result, "no")

    def test_router(self):
        """Test Router multi-way routing."""
        route_a = SimpleChainable("a")
        route_b = SimpleChainable("b")
        route_c = SimpleChainable("c")

        router = Router(
            routes={"a": route_a, "b": route_b, "c": route_c},
            router=lambda x: x["route"],
        )

        result_a = router.invoke({"route": "a"})
        self.assertIn("a", result_a)

        result_b = router.invoke({"route": "b"})
        self.assertIn("b", result_b)

    def test_router_with_default(self):
        """Test Router with default route."""
        route_a = SimpleChainable("a")
        default_route = SimpleChainable("default")

        router = Router(routes={"a": route_a}, router=lambda x: x["route"], default=default_route)

        result = router.invoke({"route": "unknown"})
        self.assertIn("default", result)

    def test_router_unknown_route_raises(self):
        """Test Router raises on unknown route without default."""
        router = Router(routes={"a": SimpleChainable("a")}, router=lambda x: x["route"])

        with self.assertRaises(ValueError):
            router.invoke({"route": "unknown"})

    def test_lambda_chainable(self):
        """Test Lambda wrapper."""
        double = Lambda(lambda x: x * 2)

        result = double.invoke(5)
        self.assertEqual(result, 10)

    def test_lambda_in_chain(self):
        """Test Lambda in Chain."""
        add_one = Lambda(lambda x: x + 1)
        double = Lambda(lambda x: x * 2)

        chain = add_one | double

        result = chain.invoke(3)
        # 3 → 4 → 8
        self.assertEqual(result, 8)

    def test_passthrough(self):
        """Test Passthrough chainable."""
        passthrough = Passthrough()

        result = passthrough.invoke({"key": "value"})
        self.assertEqual(result, {"key": "value"})

    def test_complex_composition(self):
        """Test complex composition: (A | B) & (C | D)."""
        a = SimpleChainable("a")
        b = SimpleChainable("b")
        c = SimpleChainable("c")
        d = SimpleChainable("d")

        # Create two sequential chains
        chain1 = a | b
        chain2 = c | d

        # Run them in parallel
        parallel = chain1 & chain2

        result = parallel.invoke("")
        self.assertEqual(len(result), 2)
        self.assertIn("a_b", result)
        self.assertIn("c_d", result)

    def test_dag_structure(self):
        """Test DAG: A → (B & C) → D."""
        a = SimpleChainable("a")
        b = SimpleChainable("b")
        c = SimpleChainable("c")
        SimpleChainable("d")

        # First process with a, then b & c in parallel, then d
        workflow = a | (b & c) | Lambda(lambda x: f"merged:{x}")

        result = workflow.invoke("start")
        self.assertIn("merged", result)

    def test_batch_processing(self):
        """Test batch processing."""
        double = Lambda(lambda x: x * 2)

        results = double.batch([1, 2, 3])
        self.assertEqual(results, [2, 4, 6])

    def test_config_passthrough(self):
        """Test config is passed through chain."""

        class ConfigCapture(Chainable):
            def __init__(self):
                self.captured_config = None

            def invoke(self, input: Any, config: RunnableConfig | None = None) -> Any:
                self.captured_config = config
                return input

        capture = ConfigCapture()
        config = RunnableConfig(tags=["test"], metadata={"key": "value"})

        capture.invoke("test", config)

        self.assertIsNotNone(capture.captured_config)
        self.assertEqual(capture.captured_config.tags, ["test"])
        self.assertEqual(capture.captured_config.metadata["key"], "value")


if __name__ == "__main__":
    unittest.main()
