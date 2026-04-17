"""Agent persona composed from markdown files.

The Persona Layer separates agent identity into three orthogonal concerns:
- soul:   WHO the agent is (identity, worldview, domain knowledge, boundaries)
- style:  HOW the agent communicates (voice, language, format, anti-patterns)
- agents: WHAT orchestration rules it follows (pipeline, tool usage)

At compose() time, these are concatenated into a single string that becomes
the agent's system prompt. The separation exists for human maintainability
(non-developers can edit markdown files), not runtime behavior.

Example:
    persona = Persona.from_dir("soul/")
    agent = BaseAgent(goal="...", persona=persona)

    # Or pass path directly:
    agent = BaseAgent(goal="...", persona="soul/")

    # Or wrap existing prompt for backward compat:
    persona = Persona.from_prompt(LEGACY_SYSTEM_PROMPT)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbench.intelligence.persona_source import PersonaSource


@dataclass
class Persona:
    """Agent persona composed from markdown files.

    Attributes:
        soul:   Content of SOUL.md (identity, worldview, boundaries)
        style:  Content of STYLE.md (voice, language, formatting)
        agents: Content of AGENTS.md (operational rules, tool usage)
        source: Where this persona was loaded from (for introspection)
    """

    soul: str = ""
    style: str = ""
    agents: str = ""
    source: str = ""

    def compose(self) -> str:
        """Compose persona files into a single system prompt.

        Returns non-empty sections joined by double newlines.
        Order is fixed: soul -> style -> agents (identity before rules).

        Returns:
            Combined system prompt string. Empty string if all sections empty.
        """
        sections = [s for s in (self.soul, self.style, self.agents) if s]
        return "\n\n".join(sections)

    def __bool__(self) -> bool:
        """A persona is truthy if any section has content."""
        return bool(self.soul or self.style or self.agents)

    def summary(self) -> dict:
        """Return a debug summary for introspection.

        Returns:
            Dict with source path and char count per section.
        """
        return {
            "source": self.source,
            "soul_chars": len(self.soul),
            "style_chars": len(self.style),
            "agents_chars": len(self.agents),
            "total_chars": len(self.compose()),
        }

    @classmethod
    def from_dir(cls, path: str | Path) -> Persona:
        """Load persona from a directory containing markdown files.

        Reads SOUL.md, STYLE.md, AGENTS.md if they exist.
        Missing files are silently skipped (empty string).
        Symlinks are rejected to prevent path traversal attacks (§10.2).

        Internally this delegates to :class:`FilesystemPersonaSource`
        so the "directory of markdown files" policy has a single
        implementation shared with ``from_source``.

        Args:
            path: Directory containing persona markdown files.

        Returns:
            Persona with loaded content.

        Raises:
            FileNotFoundError: If directory does not exist.
            ValueError: If any persona file is a symlink.
        """
        from openbench.intelligence.persona_source import FilesystemPersonaSource

        source = FilesystemPersonaSource(path)
        persona = cls.from_source(source)
        # Preserve the legacy behavior of storing the resolved directory
        # path as ``source`` (not the backend class name) so callers that
        # read ``persona.source`` for debug output keep working.
        persona.source = str(Path(path).expanduser().resolve())
        return persona

    @classmethod
    def from_source(cls, source: PersonaSource) -> Persona:
        """Load persona content from any :class:`PersonaSource` backend.

        Calls ``source.fetch(key)`` for each canonical key (soul, style,
        agents) and stores the results on the returned persona.

        Args:
            source: The backend to fetch from.

        Returns:
            Persona populated with fetched content.
        """
        return cls(
            soul=source.fetch("soul"),
            style=source.fetch("style"),
            agents=source.fetch("agents"),
            source=type(source).__name__,
        )

    @classmethod
    def from_prompt(cls, prompt: str) -> Persona:
        """Wrap an existing system prompt string as a Persona.

        Backward compatibility helper: treats the entire prompt as the
        'agents' section (rules/behavior). Use this when migrating
        existing code from system_prompt= to persona=.

        Args:
            prompt: The legacy system prompt string.

        Returns:
            Persona wrapping the prompt as the agents section.
        """
        return cls(agents=prompt, source="inline")
