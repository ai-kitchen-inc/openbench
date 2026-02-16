"""Tests for workflow state management."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

from openbench.core.chainable import Chain, Chainable, RunnableConfig
from openbench.core.state import (
    LocalStateStore,
    StatefulChainable,
    StepRecord,
    WorkflowState,
    WorkflowStatus,
)

# ============================================================================
# WorkflowStatus
# ============================================================================


class TestWorkflowStatus(unittest.TestCase):
    """Test WorkflowStatus enum."""

    def test_all_statuses_exist(self):
        """All expected statuses should be defined."""
        self.assertEqual(WorkflowStatus.PENDING.value, "pending")
        self.assertEqual(WorkflowStatus.RUNNING.value, "running")
        self.assertEqual(WorkflowStatus.PAUSED.value, "paused")
        self.assertEqual(WorkflowStatus.COMPLETED.value, "completed")
        self.assertEqual(WorkflowStatus.FAILED.value, "failed")

    def test_from_value(self):
        """Should construct from string value."""
        self.assertEqual(WorkflowStatus("running"), WorkflowStatus.RUNNING)
        self.assertEqual(WorkflowStatus("completed"), WorkflowStatus.COMPLETED)


# ============================================================================
# StepRecord
# ============================================================================


class TestStepRecord(unittest.TestCase):
    """Test StepRecord dataclass and serialization."""

    def _make_record(self, **overrides) -> StepRecord:
        defaults = {
            "step_name": "step_a",
            "step_index": 0,
            "input_data": {"key": "value"},
            "output_data": "result",
            "started_at": datetime(2025, 1, 1, 12, 0, 0),
            "completed_at": datetime(2025, 1, 1, 12, 0, 5),
            "duration_seconds": 5.0,
            "status": "completed",
        }
        defaults.update(overrides)
        return StepRecord(**defaults)

    def test_create(self):
        """Should create with all required fields."""
        rec = self._make_record()
        self.assertEqual(rec.step_name, "step_a")
        self.assertEqual(rec.step_index, 0)
        self.assertEqual(rec.duration_seconds, 5.0)
        self.assertIsNone(rec.error)
        self.assertEqual(rec.metadata, {})

    def test_to_dict(self):
        """Should serialize to dict with ISO timestamps."""
        rec = self._make_record()
        data = rec.to_dict()

        self.assertEqual(data["step_name"], "step_a")
        self.assertEqual(data["started_at"], "2025-01-01T12:00:00")
        self.assertEqual(data["completed_at"], "2025-01-01T12:00:05")
        self.assertEqual(data["input_data"], {"key": "value"})
        self.assertEqual(data["output_data"], "result")

    def test_from_dict(self):
        """Should deserialize from dict."""
        rec = self._make_record()
        data = rec.to_dict()
        restored = StepRecord.from_dict(data)

        self.assertEqual(restored.step_name, rec.step_name)
        self.assertEqual(restored.started_at, rec.started_at)
        self.assertEqual(restored.completed_at, rec.completed_at)

    def test_roundtrip(self):
        """to_dict -> from_dict should be identity."""
        rec = self._make_record(
            error="something broke",
            metadata={"retry": 1},
        )
        restored = StepRecord.from_dict(rec.to_dict())
        self.assertEqual(restored.error, "something broke")
        self.assertEqual(restored.metadata, {"retry": 1})

    def test_serialize_data_with_to_dict(self):
        """Objects with to_dict() should serialize via that method."""
        obj = MagicMock()
        obj.to_dict.return_value = {"custom": True}
        result = StepRecord._serialize_data(obj)
        self.assertEqual(result, {"custom": True})

    def test_serialize_data_nested_list(self):
        """Lists should be recursively serialized."""
        result = StepRecord._serialize_data(["hello", 42, None])
        self.assertEqual(result, ["hello", 42, None])

    def test_serialize_data_nested_dict(self):
        """Dicts should be recursively serialized."""
        result = StepRecord._serialize_data({"a": 1, "b": "two"})
        self.assertEqual(result, {"a": 1, "b": "two"})

    def test_serialize_data_complex_object(self):
        """Complex objects without to_dict should store type info."""
        result = StepRecord._serialize_data({1, 2, 3})
        self.assertEqual(result["__type__"], "set")
        self.assertIn("__repr__", result)

    def test_serialize_data_none_input(self):
        """None input data should not be serialized."""
        rec = self._make_record(input_data=None, output_data=None)
        data = rec.to_dict()
        self.assertIsNone(data["input_data"])
        self.assertIsNone(data["output_data"])


# ============================================================================
# WorkflowState
# ============================================================================


class TestWorkflowState(unittest.TestCase):
    """Test WorkflowState container."""

    def _make_state(self, **overrides) -> WorkflowState:
        defaults = {
            "workflow_id": "wf-001",
            "workflow_name": "test_workflow",
        }
        defaults.update(overrides)
        return WorkflowState(**defaults)

    def test_create_defaults(self):
        """Should create with default values."""
        state = self._make_state()
        self.assertEqual(state.workflow_id, "wf-001")
        self.assertEqual(state.status, WorkflowStatus.PENDING)
        self.assertEqual(state.steps, [])
        self.assertEqual(state.current_step_index, 0)
        self.assertIsNone(state.completed_at)

    def test_checkpoint_records_step(self):
        """checkpoint() should append a StepRecord."""
        state = self._make_state()
        state.metadata["total_steps"] = 3

        now = datetime.now()
        state.checkpoint(
            step_name="loader",
            step_index=0,
            input_data="raw",
            output_data="parsed",
            started_at=now,
            completed_at=now + timedelta(seconds=2),
        )

        self.assertEqual(len(state.steps), 1)
        self.assertEqual(state.steps[0].step_name, "loader")
        self.assertEqual(state.steps[0].duration_seconds, 2.0)
        self.assertEqual(state.current_step_index, 1)

    def test_checkpoint_failed_sets_status(self):
        """checkpoint with failed status should set workflow to FAILED."""
        state = self._make_state()
        state.metadata["total_steps"] = 2

        now = datetime.now()
        state.checkpoint(
            step_name="processor",
            step_index=0,
            input_data=None,
            output_data=None,
            started_at=now,
            completed_at=now,
            status="failed",
            error="boom",
        )

        self.assertEqual(state.status, WorkflowStatus.FAILED)
        self.assertEqual(state.error, "boom")

    def test_checkpoint_last_step_completes(self):
        """Completing the last step should mark workflow COMPLETED."""
        state = self._make_state()
        state.metadata["total_steps"] = 1

        now = datetime.now()
        state.checkpoint(
            step_name="only_step",
            step_index=0,
            input_data=None,
            output_data="final",
            started_at=now,
            completed_at=now,
        )

        self.assertEqual(state.status, WorkflowStatus.COMPLETED)
        self.assertIsNotNone(state.completed_at)
        self.assertEqual(state.final_output, "final")

    def test_get_last_checkpoint(self):
        """Should return the last step."""
        state = self._make_state()
        now = datetime.now()
        state.checkpoint("a", 0, None, "out_a", now, now)
        state.checkpoint("b", 1, None, "out_b", now, now)

        last = state.get_last_checkpoint()
        self.assertEqual(last.step_name, "b")

    def test_get_last_checkpoint_empty(self):
        """Should return None when no steps."""
        state = self._make_state()
        self.assertIsNone(state.get_last_checkpoint())

    def test_get_step_found(self):
        """Should find step by index."""
        state = self._make_state()
        now = datetime.now()
        state.checkpoint("a", 0, None, "out", now, now)
        state.checkpoint("b", 1, None, "out", now, now)

        step = state.get_step(0)
        self.assertEqual(step.step_name, "a")

    def test_get_step_not_found(self):
        """Should return None for missing index."""
        state = self._make_state()
        self.assertIsNone(state.get_step(99))

    def test_can_resume_paused(self):
        """Paused workflows can resume."""
        state = self._make_state(status=WorkflowStatus.PAUSED)
        self.assertTrue(state.can_resume())

    def test_can_resume_failed(self):
        """Failed workflows can resume."""
        state = self._make_state(status=WorkflowStatus.FAILED)
        self.assertTrue(state.can_resume())

    def test_cannot_resume_completed(self):
        """Completed workflows cannot resume."""
        state = self._make_state(status=WorkflowStatus.COMPLETED)
        self.assertFalse(state.can_resume())

    def test_cannot_resume_running(self):
        """Running workflows cannot resume."""
        state = self._make_state(status=WorkflowStatus.RUNNING)
        self.assertFalse(state.can_resume())

    def test_get_resume_point(self):
        """Should return current_step_index for resumable workflows."""
        state = self._make_state(status=WorkflowStatus.PAUSED)
        state.current_step_index = 3
        self.assertEqual(state.get_resume_point(), 3)

    def test_get_resume_point_not_resumable(self):
        """Should return 0 for non-resumable workflows."""
        state = self._make_state(status=WorkflowStatus.COMPLETED)
        state.current_step_index = 5
        self.assertEqual(state.get_resume_point(), 0)

    def test_to_dict(self):
        """Should serialize to dict."""
        state = self._make_state()
        data = state.to_dict()

        self.assertEqual(data["workflow_id"], "wf-001")
        self.assertEqual(data["status"], "pending")
        self.assertIn("created_at", data)
        self.assertIsNone(data["completed_at"])
        self.assertEqual(data["steps"], [])

    def test_from_dict(self):
        """Should deserialize from dict."""
        state = self._make_state()
        now = datetime.now()
        state.checkpoint("step_a", 0, None, "out", now, now)
        data = state.to_dict()

        restored = WorkflowState.from_dict(data)
        self.assertEqual(restored.workflow_id, "wf-001")
        self.assertEqual(restored.status, WorkflowStatus.PENDING)
        self.assertEqual(len(restored.steps), 1)
        self.assertEqual(restored.steps[0].step_name, "step_a")

    def test_from_dict_with_completed_at(self):
        """Should handle non-None completed_at."""
        state = self._make_state()
        state.completed_at = datetime(2025, 6, 1)
        data = state.to_dict()

        restored = WorkflowState.from_dict(data)
        self.assertEqual(restored.completed_at, datetime(2025, 6, 1))


# ============================================================================
# LocalStateStore
# ============================================================================


class TestLocalStateStore(unittest.TestCase):
    """Test local file-based state store."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = LocalStateStore(base_path=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_state(self, wf_id: str = "wf-001") -> WorkflowState:
        return WorkflowState(
            workflow_id=wf_id,
            workflow_name="test",
        )

    def test_save_and_load(self):
        """Should save and load state."""
        state = self._make_state()
        self.store.save(state)

        loaded = self.store.load("wf-001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.workflow_id, "wf-001")
        self.assertEqual(loaded.workflow_name, "test")

    def test_load_missing(self):
        """Should return None for missing workflow."""
        self.assertIsNone(self.store.load("nonexistent"))

    def test_delete(self):
        """Should delete existing state."""
        state = self._make_state()
        self.store.save(state)

        self.assertTrue(self.store.delete("wf-001"))
        self.assertIsNone(self.store.load("wf-001"))

    def test_delete_missing(self):
        """Should return False for missing workflow."""
        self.assertFalse(self.store.delete("nonexistent"))

    def test_list_workflows(self):
        """Should list all workflows."""
        self.store.save(self._make_state("wf-001"))
        self.store.save(self._make_state("wf-002"))
        self.store.save(self._make_state("wf-003"))

        workflows = self.store.list_workflows()
        self.assertEqual(len(workflows), 3)

    def test_list_workflows_filter_by_status(self):
        """Should filter by status."""
        s1 = self._make_state("wf-001")
        s1.status = WorkflowStatus.COMPLETED
        s2 = self._make_state("wf-002")
        s2.status = WorkflowStatus.FAILED

        self.store.save(s1)
        self.store.save(s2)

        completed = self.store.list_workflows(status=WorkflowStatus.COMPLETED)
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].workflow_id, "wf-001")

    def test_list_workflows_limit(self):
        """Should respect limit."""
        for i in range(5):
            self.store.save(self._make_state(f"wf-{i:03d}"))

        workflows = self.store.list_workflows(limit=2)
        self.assertEqual(len(workflows), 2)

    def test_list_workflows_sorted_by_updated_at(self):
        """Should sort by updated_at descending."""
        s1 = self._make_state("wf-001")
        s1.updated_at = datetime(2025, 1, 1)
        s2 = self._make_state("wf-002")
        s2.updated_at = datetime(2025, 6, 1)

        self.store.save(s1)
        self.store.save(s2)

        workflows = self.store.list_workflows()
        self.assertEqual(workflows[0].workflow_id, "wf-002")
        self.assertEqual(workflows[1].workflow_id, "wf-001")

    def test_list_workflows_skips_corrupted(self):
        """Should skip corrupted JSON files."""
        self.store.save(self._make_state("wf-001"))
        # Write a corrupted file
        bad_path = os.path.join(self.tmpdir, "wf-bad.json")
        with open(bad_path, "w") as f:
            f.write("{invalid json")

        workflows = self.store.list_workflows()
        self.assertEqual(len(workflows), 1)

    def test_save_creates_json_file(self):
        """Save should create a .json file."""
        self.store.save(self._make_state("wf-test"))
        path = os.path.join(self.tmpdir, "wf-test.json")
        self.assertTrue(os.path.exists(path))

        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["workflow_id"], "wf-test")

    def test_save_overwrites_existing(self):
        """Save should overwrite existing state."""
        state = self._make_state("wf-001")
        self.store.save(state)

        state.status = WorkflowStatus.COMPLETED
        self.store.save(state)

        loaded = self.store.load("wf-001")
        self.assertEqual(loaded.status, WorkflowStatus.COMPLETED)


# ============================================================================
# StatefulChainable
# ============================================================================


class IncrementChainable(Chainable):
    """Simple chainable that adds 1 to input."""

    def invoke(self, input: Any, config: RunnableConfig | None = None) -> int:
        return input + 1


class DoubleChainable(Chainable):
    """Simple chainable that doubles input."""

    def invoke(self, input: Any, config: RunnableConfig | None = None) -> int:
        return input * 2


class FailingChainable(Chainable):
    """Chainable that always raises."""

    def invoke(self, input: Any, config: RunnableConfig | None = None) -> Any:
        raise RuntimeError("step failed")


class TestStatefulChainable(unittest.TestCase):
    """Test StatefulChainable wrapper."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_store = LocalStateStore(base_path=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_invoke_single_step(self):
        """Should execute a single chainable with checkpointing."""
        step = IncrementChainable()
        stateful = StatefulChainable(
            chainable=step,
            state_store=self.state_store,
            workflow_name="single_step",
        )

        result = stateful.invoke(10)
        self.assertEqual(result, 11)

    def test_invoke_chain(self):
        """Should execute a chain with per-step checkpointing."""
        chain = Chain([IncrementChainable(), DoubleChainable()])
        stateful = StatefulChainable(
            chainable=chain,
            state_store=self.state_store,
            workflow_name="multi_step",
        )

        # 10 -> +1 -> 11 -> *2 -> 22
        result = stateful.invoke(10)
        self.assertEqual(result, 22)

    def test_invoke_creates_state(self):
        """Invoke should persist state to the store."""
        chain = Chain([IncrementChainable()])
        stateful = StatefulChainable(
            chainable=chain,
            state_store=self.state_store,
            workflow_name="persisted",
        )
        stateful.invoke(0)

        workflows = self.state_store.list_workflows()
        self.assertEqual(len(workflows), 1)
        self.assertEqual(workflows[0].status, WorkflowStatus.COMPLETED)

    def test_invoke_records_all_steps(self):
        """Should checkpoint every step."""
        chain = Chain([IncrementChainable(), DoubleChainable()])
        stateful = StatefulChainable(
            chainable=chain,
            state_store=self.state_store,
            workflow_name="tracked",
        )
        stateful.invoke(5)

        workflows = self.state_store.list_workflows()
        state = workflows[0]
        self.assertEqual(len(state.steps), 2)
        self.assertEqual(state.steps[0].status, "completed")
        self.assertEqual(state.steps[1].status, "completed")

    def test_invoke_failure_records_error(self):
        """Failed step should be checkpointed as failed."""
        chain = Chain([IncrementChainable(), FailingChainable()])
        stateful = StatefulChainable(
            chainable=chain,
            state_store=self.state_store,
            workflow_name="failing",
        )

        with self.assertRaises(RuntimeError):
            stateful.invoke(0)

        workflows = self.state_store.list_workflows()
        state = workflows[0]
        self.assertEqual(state.status, WorkflowStatus.FAILED)
        self.assertEqual(len(state.steps), 2)
        self.assertEqual(state.steps[1].status, "failed")
        self.assertEqual(state.steps[1].error, "step failed")

    def test_resume_from_failure(self):
        """Should resume from the last completed step."""
        # First run: step 0 succeeds, step 1 fails
        step_b = MagicMock(spec=Chainable)
        step_b.invoke = MagicMock(side_effect=[RuntimeError("temporary"), 42])

        chain = Chain([IncrementChainable(), step_b])
        stateful = StatefulChainable(
            chainable=chain,
            state_store=self.state_store,
            workflow_name="resumable",
        )

        with self.assertRaises(RuntimeError):
            stateful.invoke(10)

        # Get the workflow ID
        workflows = self.state_store.list_workflows()
        wf_id = workflows[0].workflow_id

        # Resume: step 1 now succeeds
        result = stateful.resume(wf_id)
        self.assertEqual(result, 42)

    def test_resume_not_found(self):
        """Should raise for unknown workflow ID."""
        chain = Chain([IncrementChainable()])
        stateful = StatefulChainable(
            chainable=chain,
            state_store=self.state_store,
            workflow_name="test",
        )

        with self.assertRaises(ValueError, msg="not found"):
            stateful.resume("nonexistent-id")

    def test_resume_not_resumable(self):
        """Should raise for non-resumable workflow."""
        chain = Chain([IncrementChainable()])
        stateful = StatefulChainable(
            chainable=chain,
            state_store=self.state_store,
            workflow_name="test",
        )
        stateful.invoke(0)

        workflows = self.state_store.list_workflows()
        wf_id = workflows[0].workflow_id

        with self.assertRaises(ValueError, msg="cannot be resumed"):
            stateful.resume(wf_id)

    def test_pause(self):
        """Should set workflow status to PAUSED."""
        chain = Chain([IncrementChainable()])
        stateful = StatefulChainable(
            chainable=chain,
            state_store=self.state_store,
            workflow_name="pausable",
        )
        stateful.invoke(0)

        workflows = self.state_store.list_workflows()
        wf_id = workflows[0].workflow_id

        stateful.pause(wf_id)

        state = stateful.get_state(wf_id)
        self.assertEqual(state.status, WorkflowStatus.PAUSED)

    def test_get_state(self):
        """Should return state for existing workflow."""
        chain = Chain([IncrementChainable()])
        stateful = StatefulChainable(
            chainable=chain,
            state_store=self.state_store,
            workflow_name="get_state",
        )
        stateful.invoke(0)

        workflows = self.state_store.list_workflows()
        wf_id = workflows[0].workflow_id

        state = stateful.get_state(wf_id)
        self.assertIsNotNone(state)
        self.assertEqual(state.workflow_name, "get_state")

    def test_get_state_missing(self):
        """Should return None for missing workflow."""
        chain = Chain([IncrementChainable()])
        stateful = StatefulChainable(
            chainable=chain,
            state_store=self.state_store,
            workflow_name="test",
        )
        self.assertIsNone(stateful.get_state("nonexistent"))

    def test_auto_checkpoint_disabled(self):
        """When auto_checkpoint=False, only failure/completion should save."""
        chain = Chain([IncrementChainable(), DoubleChainable()])
        stateful = StatefulChainable(
            chainable=chain,
            state_store=self.state_store,
            workflow_name="no_auto",
            auto_checkpoint=False,
        )
        result = stateful.invoke(5)
        self.assertEqual(result, 12)

        # Should still complete successfully
        workflows = self.state_store.list_workflows()
        self.assertEqual(len(workflows), 1)
        self.assertEqual(workflows[0].status, WorkflowStatus.COMPLETED)
        # No per-step checkpoints
        self.assertEqual(len(workflows[0].steps), 0)


if __name__ == "__main__":
    unittest.main()
