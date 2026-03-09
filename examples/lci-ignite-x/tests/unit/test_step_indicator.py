"""Unit tests for StepIndicator."""

from __future__ import annotations

from lci_ignite.chat.step_indicator import (
    PipelineStep,
    StepIndicator,
    StepStatus,
    create_lca_step_indicator,
)


class TestPipelineStep:
    def test_default_status(self):
        step = PipelineStep(name="test", description="Test step")
        assert step.status == StepStatus.PENDING
        assert step.result is None
        assert step.error is None


class TestStepIndicator:
    def test_add_step(self):
        indicator = StepIndicator()
        step = indicator.add_step("parse", "Parsing CSV")
        assert step.name == "parse"
        assert len(indicator.steps) == 1

    def test_start_step(self):
        indicator = StepIndicator()
        indicator.add_step("parse", "Parsing CSV")
        indicator.start_step("parse")
        assert indicator.steps[0].status == StepStatus.RUNNING

    def test_complete_step(self):
        indicator = StepIndicator()
        indicator.add_step("parse", "Parsing CSV")
        indicator.complete_step("parse", result={"rows": 100})
        assert indicator.steps[0].status == StepStatus.COMPLETED
        assert indicator.steps[0].result == {"rows": 100}

    def test_fail_step(self):
        indicator = StepIndicator()
        indicator.add_step("parse", "Parsing CSV")
        indicator.fail_step("parse", "File not found")
        assert indicator.steps[0].status == StepStatus.FAILED
        assert indicator.steps[0].error == "File not found"

    def test_skip_step(self):
        indicator = StepIndicator()
        indicator.add_step("parse", "Parsing CSV")
        indicator.skip_step("parse")
        assert indicator.steps[0].status == StepStatus.SKIPPED

    def test_current_step(self):
        indicator = StepIndicator()
        indicator.add_step("a", "Step A")
        indicator.add_step("b", "Step B")
        indicator.start_step("b")
        assert indicator.current_step.name == "b"

    def test_current_step_none_when_no_running(self):
        indicator = StepIndicator()
        indicator.add_step("a", "Step A")
        assert indicator.current_step is None

    def test_is_complete(self):
        indicator = StepIndicator()
        indicator.add_step("a", "Step A")
        indicator.add_step("b", "Step B")
        indicator.complete_step("a")
        assert indicator.is_complete is False
        indicator.skip_step("b")
        assert indicator.is_complete is True

    def test_has_failures(self):
        indicator = StepIndicator()
        indicator.add_step("a", "Step A")
        assert indicator.has_failures is False
        indicator.fail_step("a", "error")
        assert indicator.has_failures is True

    def test_to_dict(self):
        indicator = StepIndicator()
        indicator.add_step("parse", "Parsing CSV")
        indicator.complete_step("parse")

        result = indicator.to_dict()
        assert len(result) == 1
        assert result[0]["name"] == "parse"
        assert result[0]["status"] == "completed"

    def test_find_nonexistent_step(self):
        indicator = StepIndicator()
        assert indicator.start_step("nonexistent") is None
        assert indicator.complete_step("nonexistent") is None


class TestCreateLCAStepIndicator:
    def test_creates_4_steps(self):
        indicator = create_lca_step_indicator()
        assert len(indicator.steps) == 4

    def test_step_names(self):
        indicator = create_lca_step_indicator()
        names = [s.name for s in indicator.steps]
        assert names == ["parse_csv", "io_table", "hotspot", "narrative"]

    def test_all_pending(self):
        indicator = create_lca_step_indicator()
        assert all(s.status == StepStatus.PENDING for s in indicator.steps)
