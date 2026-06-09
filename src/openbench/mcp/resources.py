"""MCP resource helpers for OpenBench skills."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openbench.intelligence.skill import Skill


@dataclass(frozen=True)
class MCPResource:
    """A static MCP resource exposed by OpenBench."""

    uri: str
    name: str
    mime_type: str
    text: str
    description: str = ""

    def to_mcp_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "mimeType": self.mime_type,
            "description": self.description,
        }


def resources_from_skills(skills: list[Skill]) -> dict[str, MCPResource]:
    """Build static resources for SKILL.md and references."""
    resources: dict[str, MCPResource] = {}
    for skill in skills:
        skill_uri = f"openbench://skills/{skill.name}/SKILL.md"
        resources[skill_uri] = MCPResource(
            uri=skill_uri,
            name=f"{skill.name}/SKILL.md",
            mime_type="text/markdown",
            text=skill.raw_skill_md,
            description=f"OpenBench skill instructions for {skill.name}",
        )
        for filename, content in skill.references.items():
            ref_uri = f"openbench://skills/{skill.name}/references/{filename}"
            resources[ref_uri] = MCPResource(
                uri=ref_uri,
                name=f"{skill.name}/references/{filename}",
                mime_type="text/markdown",
                text=content,
                description=f"Reference document for {skill.name}",
            )
    return resources
