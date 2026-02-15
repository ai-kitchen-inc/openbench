"""Tests for task planning module."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from openbench.core.abstractions import LLMResponse
from openbench.intelligence.planning import TaskPlan, TaskPlanner


class TestTaskPlan(unittest.TestCase):
    """Test TaskPlan dataclass."""

    def test_create_plan(self):
        """Test creating a plan with all fields."""
        plan = TaskPlan(
            goal="Analyze sales data",
            steps=["Gather data", "Analyze trends", "Write report"],
            estimated_tools=["search", "calculate"],
            reasoning="Break into data collection, analysis, and reporting",
        )
        self.assertEqual(plan.goal, "Analyze sales data")
        self.assertEqual(len(plan.steps), 3)
        self.assertEqual(len(plan.estimated_tools), 2)
        self.assertIn("data collection", plan.reasoning)

    def test_create_plan_defaults(self):
        """Test plan with default values."""
        plan = TaskPlan(goal="Simple task", steps=["Do it"])
        self.assertEqual(plan.estimated_tools, [])
        self.assertEqual(plan.reasoning, "")

    def test_plan_with_empty_steps(self):
        """Test plan with empty steps list."""
        plan = TaskPlan(goal="Empty", steps=[])
        self.assertEqual(plan.steps, [])


class TestTaskPlanner(unittest.TestCase):
    """Test TaskPlanner class."""

    def _make_llm(self, response_text: str) -> MagicMock:
        """Create mock LLM provider returning given text."""
        llm = MagicMock()
        llm.generate.return_value = LLMResponse(
            text=response_text, model="test", tokens_used=100, cost=0.01
        )
        return llm

    def test_plan_valid_json(self):
        """Test planner parses valid JSON response."""
        response = json.dumps(
            {
                "steps": ["Search for revenue", "Calculate growth"],
                "estimated_tools": ["search"],
                "reasoning": "Two-phase approach",
            }
        )
        llm = self._make_llm(response)
        planner = TaskPlanner(llm, model="test-model")

        plan = planner.plan("Analyze revenue", ["search", "calculate"])

        self.assertEqual(plan.goal, "Analyze revenue")
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0], "Search for revenue")
        self.assertEqual(plan.estimated_tools, ["search"])
        self.assertEqual(plan.reasoning, "Two-phase approach")

    def test_plan_with_markdown_code_block(self):
        """Test planner handles markdown-wrapped JSON."""
        response = (
            '```json\n{"steps": ["Step 1"], "estimated_tools": [], "reasoning": "Simple"}\n```'
        )
        llm = self._make_llm(response)
        planner = TaskPlanner(llm)

        plan = planner.plan("Simple task")
        self.assertEqual(plan.steps, ["Step 1"])

    def test_plan_fallback_on_invalid_json(self):
        """Test planner falls back to single-step plan on parse error."""
        llm = self._make_llm("This is not JSON")
        planner = TaskPlanner(llm)

        plan = planner.plan("Do something")
        self.assertEqual(plan.steps, ["Do something"])
        self.assertIn("Planning failed", plan.reasoning)

    def test_plan_fallback_on_llm_error(self):
        """Test planner falls back when LLM raises exception."""
        llm = MagicMock()
        llm.generate.side_effect = RuntimeError("LLM unavailable")
        planner = TaskPlanner(llm)

        plan = planner.plan("Do something")
        self.assertEqual(plan.steps, ["Do something"])
        self.assertIn("Planning failed", plan.reasoning)

    def test_plan_passes_tools_in_prompt(self):
        """Test planner includes available tools in prompt."""
        llm = self._make_llm(
            json.dumps(
                {
                    "steps": ["Use search"],
                    "estimated_tools": ["search"],
                    "reasoning": "ok",
                }
            )
        )
        planner = TaskPlanner(llm, model="test")

        planner.plan("Find info", ["search", "calculate"])

        # Verify the prompt contains tool names
        call_args = llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
        self.assertIn("search", prompt)
        self.assertIn("calculate", prompt)

    def test_plan_no_tools(self):
        """Test planner works with no available tools."""
        llm = self._make_llm(
            json.dumps({"steps": ["Think"], "estimated_tools": [], "reasoning": "No tools"})
        )
        planner = TaskPlanner(llm)

        plan = planner.plan("Think about life", None)
        self.assertEqual(plan.steps, ["Think"])

    def test_format_plan_prompt(self):
        """Test formatting plan as prompt string."""
        planner = TaskPlanner(MagicMock())
        plan = TaskPlan(
            goal="Analyze",
            steps=["Gather data", "Run analysis", "Report findings"],
        )

        prompt = planner.format_plan_prompt(plan)
        self.assertIn("1. Gather data", prompt)
        self.assertIn("2. Run analysis", prompt)
        self.assertIn("3. Report findings", prompt)
        self.assertIn("Execute this plan", prompt)

    def test_plan_uses_low_temperature(self):
        """Test planner uses low temperature for deterministic planning."""
        llm = self._make_llm(
            json.dumps({"steps": ["Do it"], "estimated_tools": [], "reasoning": "ok"})
        )
        planner = TaskPlanner(llm, model="test")

        planner.plan("Task")

        call_kwargs = llm.generate.call_args.kwargs
        self.assertEqual(call_kwargs.get("temperature"), 0.3)


if __name__ == "__main__":
    unittest.main()
