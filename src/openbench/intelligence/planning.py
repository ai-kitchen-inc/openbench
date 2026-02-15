"""Task planning for agent execution.

Provides:
- TaskPlan: Structured plan with steps and reasoning
- TaskPlanner: LLM-based task decomposition before execution

Used by BaseAgent when ``enable_planning=True`` to break complex goals
into step-by-step plans before the reasoning loop begins.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbench.core.abstractions import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class TaskPlan:
    """Structured plan for agent execution.

    Attributes:
        goal: The original goal to accomplish.
        steps: Ordered list of steps to execute.
        estimated_tools: Tools likely needed for execution.
        reasoning: LLM's reasoning about why this plan was chosen.
    """

    goal: str
    steps: list[str]
    estimated_tools: list[str] = field(default_factory=list)
    reasoning: str = ""


class TaskPlanner:
    """Decomposes complex goals into step-by-step plans.

    Uses an LLM to analyze the goal and available tools, then produces
    a structured plan that guides the agent's reasoning loop.

    Example:
        >>> planner = TaskPlanner(llm_provider)
        >>> plan = planner.plan("Analyze Q4 revenue trends", ["search", "calculate"])
        >>> plan.steps
        ['Search for Q4 revenue data', 'Calculate growth trends', 'Summarize findings']
    """

    def __init__(self, llm: LLMProvider, model: str | None = None):
        self.llm = llm
        self.model = model

    def plan(
        self,
        goal: str,
        available_tools: list[str] | None = None,
        conversation_context: str = "",
    ) -> TaskPlan:
        """Generate execution plan for the given goal.

        Args:
            goal: The task goal to plan for.
            available_tools: List of tool names available to the agent.
            conversation_context: Recent conversation history for follow-up awareness.

        Returns:
            TaskPlan with steps and reasoning.
            Falls back to a single-step plan on failure.
        """
        tools_str = ", ".join(available_tools) if available_tools else "none"
        prompt = "You are a task planner. Decompose this goal into clear, actionable steps.\n\n"
        if conversation_context:
            prompt += (
                "Recent conversation (use this context for follow-up requests):\n"
                f"{conversation_context}\n\n"
            )
        prompt += (
            f"Goal: {goal}\n"
            f"Available tools: {tools_str}\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"steps": ["step1", "step2", ...], '
            '"estimated_tools": ["tool1", ...], '
            '"reasoning": "brief explanation of approach"}'
        )

        try:
            response = self.llm.generate(prompt=prompt, model=self.model, temperature=0.3)
            text = response.text.strip()
            # Handle markdown code blocks
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            parsed = json.loads(text)
            return TaskPlan(
                goal=goal,
                steps=parsed.get("steps", [goal]),
                estimated_tools=parsed.get("estimated_tools", []),
                reasoning=parsed.get("reasoning", ""),
            )
        except Exception as e:
            logger.warning(f"Planning failed, using single-step fallback: {e}")
            return TaskPlan(
                goal=goal,
                steps=[goal],
                reasoning=f"Planning failed: {e}",
            )

    def format_plan_prompt(self, plan: TaskPlan) -> str:
        """Format a plan into a prompt string for injection into agent memory.

        Args:
            plan: The task plan to format.

        Returns:
            Formatted plan string.
        """
        steps_str = "\n".join(f"{i}. {step}" for i, step in enumerate(plan.steps, 1))
        return f"Execute this plan step by step:\n{steps_str}"
