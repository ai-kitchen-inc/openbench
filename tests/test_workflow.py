"""Tests for Workflow class."""

import unittest
import tempfile
import shutil
from pathlib import Path

from openbench.core import (
    Chainable,
    Chain,
    StateStore,
    LocalStateStore,
    WorkflowState,
    WorkflowStatus,
)
from openbench.workflows import Workflow, workflow


class SimpleStep(Chainable):
    """Simple step for testing."""

    def __init__(self, name: str):
        self.step_name = name

    def invoke(self, input, config=None):
        # Handle list input from Parallel
        if isinstance(input, list):
            return {self.step_name: f"completed_{self.step_name}", "parallel_results": input}
        # Handle dict input
        elif isinstance(input, dict):
            return {**input, self.step_name: f"completed_{self.step_name}"}
        # Handle other input
        else:
            return {self.step_name: f"completed_{self.step_name}", "input": input}


class TestWorkflow(unittest.TestCase):
    """Test Workflow class."""

    def setUp(self):
        """Set up test fixtures."""
        # Create temporary directory for state
        self.temp_dir = tempfile.mkdtemp()
        self.state_store = LocalStateStore(base_path=self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        # Remove temporary directory
        shutil.rmtree(self.temp_dir)

    def test_workflow_creation(self):
        """Test basic workflow creation."""
        step1 = SimpleStep("step1")
        step2 = SimpleStep("step2")

        wf = Workflow(
            name="test-workflow",
            chain=step1 | step2,
            state_store=self.state_store,
            checkpoints=True
        )

        self.assertEqual(wf.name, "test-workflow")
        self.assertIsInstance(wf.chain, Chain)

    def test_workflow_run(self):
        """Test workflow execution."""
        step1 = SimpleStep("step1")
        step2 = SimpleStep("step2")

        wf = Workflow(
            name="test-workflow",
            chain=step1 | step2,
            state_store=self.state_store,
            checkpoints=False  # Disable for simpler test
        )

        result = wf.run({})

        self.assertIn("step1", result)
        self.assertIn("step2", result)
        self.assertEqual(result["step1"], "completed_step1")
        self.assertEqual(result["step2"], "completed_step2")

    def test_workflow_with_metadata(self):
        """Test workflow with metadata."""
        step = SimpleStep("step1")

        wf = Workflow(
            name="test-workflow",
            chain=step,
            state_store=self.state_store,
            checkpoints=False,
            metadata={"project": "test", "version": "1.0"}
        )

        self.assertEqual(wf.metadata["project"], "test")
        self.assertEqual(wf.metadata["version"], "1.0")

    def test_workflow_repr(self):
        """Test workflow string representation."""
        step = SimpleStep("step1")

        wf = Workflow(
            name="my-workflow",
            chain=step,
            state_store=self.state_store
        )

        self.assertEqual(repr(wf), "Workflow(name='my-workflow')")
        self.assertEqual(str(wf), "Workflow: my-workflow")

    def test_workflow_function_style(self):
        """Test function-style workflow creation."""
        step1 = SimpleStep("step1")
        step2 = SimpleStep("step2")

        wf = workflow("test-workflow", step1 | step2, state_store=self.state_store)

        self.assertIsInstance(wf, Workflow)
        self.assertEqual(wf.name, "test-workflow")

    def test_workflow_sequential(self):
        """Test sequential workflow execution."""
        steps = [SimpleStep(f"step{i}") for i in range(5)]

        wf = Workflow(
            name="sequential-workflow",
            chain=Chain(steps),
            state_store=self.state_store,
            checkpoints=False
        )

        result = wf.run({})

        # All steps should be in result
        for i in range(5):
            self.assertIn(f"step{i}", result)

    def test_workflow_with_checkpointing(self):
        """Test workflow with checkpointing enabled."""
        step1 = SimpleStep("step1")
        step2 = SimpleStep("step2")

        wf = Workflow(
            name="checkpoint-workflow",
            chain=step1 | step2,
            state_store=self.state_store,
            checkpoints=True  # Enable checkpointing
        )

        # Execute workflow
        result = wf.run({"initial": "data"})

        # Should have created state files
        state_files = list(Path(self.temp_dir).glob("*.json"))
        self.assertGreater(len(state_files), 0)

    def test_workflow_default_state_store(self):
        """Test workflow creates default state store."""
        step = SimpleStep("step1")

        wf = Workflow(
            name="default-store-workflow",
            chain=step,
            # No state_store provided
        )

        self.assertIsInstance(wf.state_store, LocalStateStore)

    def test_workflow_no_checkpoints(self):
        """Test workflow with checkpoints disabled."""
        step = SimpleStep("step1")

        wf = Workflow(
            name="no-checkpoint-workflow",
            chain=step,
            state_store=self.state_store,
            checkpoints=False
        )

        result = wf.run({})

        # Should still execute successfully
        self.assertIn("step1", result)


class TestWorkflowIntegration(unittest.TestCase):
    """Integration tests for workflows."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.state_store = LocalStateStore(base_path=self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)

    def test_complex_dag_workflow(self):
        """Test complex DAG workflow."""
        # Create a complex DAG: A → (B & C) → D
        a = SimpleStep("a")
        b = SimpleStep("b")
        c = SimpleStep("c")
        d = SimpleStep("d")

        # Build the DAG
        from openbench.core import Parallel
        dag = a | Parallel([b, c]) | d

        wf = Workflow(
            name="dag-workflow",
            chain=dag,
            state_store=self.state_store,
            checkpoints=False
        )

        result = wf.run({})

        # Final step should be present
        self.assertIn("d", result)
        # Parallel results should be captured
        self.assertIn("parallel_results", result)

    def test_workflow_with_conditional(self):
        """Test workflow with conditional branching."""
        from openbench.core import Conditional

        true_step = SimpleStep("true_path")
        false_step = SimpleStep("false_path")

        conditional = Conditional(
            condition=lambda x: x.get("condition") == True,
            true_branch=true_step,
            false_branch=false_step
        )

        wf = Workflow(
            name="conditional-workflow",
            chain=conditional,
            state_store=self.state_store,
            checkpoints=False
        )

        # Test true branch
        result_true = wf.run({"condition": True})
        self.assertIn("true_path", result_true)
        self.assertNotIn("false_path", result_true)

        # Test false branch
        result_false = wf.run({"condition": False})
        self.assertIn("false_path", result_false)
        self.assertNotIn("true_path", result_false)

    def test_workflow_with_router(self):
        """Test workflow with router."""
        from openbench.core import Router

        route_a = SimpleStep("route_a")
        route_b = SimpleStep("route_b")
        route_c = SimpleStep("route_c")

        router = Router(
            routes={
                "a": route_a,
                "b": route_b,
                "c": route_c
            },
            router=lambda x: x["route"]
        )

        wf = Workflow(
            name="router-workflow",
            chain=router,
            state_store=self.state_store,
            checkpoints=False
        )

        # Test different routes
        result_a = wf.run({"route": "a"})
        self.assertIn("route_a", result_a)

        result_b = wf.run({"route": "b"})
        self.assertIn("route_b", result_b)


if __name__ == "__main__":
    unittest.main()
