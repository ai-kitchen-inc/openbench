"""Load and wrap OpenBench function tools for MCP exposure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from openbench.intelligence.skill_registry import SkillRegistry
from openbench.mcp.policy import RiskLevel, classify_tool_risk
from openbench.mcp.schema import openbench_schema_to_mcp_tool

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from openbench.intelligence.skill import Skill


@dataclass
class OpenBenchMCPTool:
    """A callable OpenBench tool plus its MCP metadata."""

    name: str
    callable: Callable[..., Any]
    schema: dict[str, Any]
    source_skill: str | None = None
    risk: RiskLevel = RiskLevel.READ

    @property
    def mcp_tool(self) -> dict[str, Any]:
        return openbench_schema_to_mcp_tool(
            self.schema,
            fallback_name=self.name,
            source_skill=self.source_skill,
            risk=self.risk,
        )


def build_skill_registry(
    *,
    include_sdk_tools: bool = True,
    skills: Sequence[str | Path] | None = None,
    sdk_skills_dir: Path | None = None,
    user_skills_dir: Path | None = None,
) -> SkillRegistry:
    """Build a SkillRegistry for MCP serving."""
    registry = SkillRegistry(sdk_skills_dir=sdk_skills_dir, user_skills_dir=user_skills_dir)
    if include_sdk_tools:
        registry.load_sdk_skills()
    registry.load_user_skills()
    if skills:
        if include_sdk_tools:
            registry.load_skills(list(skills))
        else:
            registry.load_project_skills(list(skills))
    return registry


def collect_mcp_tools(registry: SkillRegistry) -> list[OpenBenchMCPTool]:
    """Collect tools with skill attribution."""
    tools: list[OpenBenchMCPTool] = []
    seen: dict[str, str] = {}
    for skill in registry.all():
        for name, fn, schema in skill.get_tools():
            if name in seen:
                raise ValueError(
                    f"Tool name collision: {name!r} from {skill.name!r} and {seen[name]!r}"
                )
            seen[name] = skill.name
            tools.append(
                OpenBenchMCPTool(
                    name=name,
                    callable=fn,
                    schema=schema,
                    source_skill=skill.name,
                    risk=classify_tool_risk(name),
                )
            )
    return tools


def loaded_skills(registry: SkillRegistry) -> list[Skill]:
    """Return loaded skills in stable order."""
    return sorted(registry.all(), key=lambda s: s.name)
