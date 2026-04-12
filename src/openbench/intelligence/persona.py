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

        Args:
            path: Directory containing persona markdown files.

        Returns:
            Persona with loaded content.

        Raises:
            FileNotFoundError: If directory does not exist.
            ValueError: If any persona file is a symlink.
        """
        d = Path(path)
        if not d.is_dir():
            raise FileNotFoundError(f"Persona directory not found: {d}")

        persona = cls(source=str(d.resolve()))

        _FILE_MAP = {
            "SOUL.md": "soul",
            "STYLE.md": "style",
            "AGENTS.md": "agents",
        }

        for filename, attr in _FILE_MAP.items():
            f = d / filename
            if f.exists():
                if f.is_symlink():
                    raise ValueError(
                        f"Persona file {filename} is a symlink — rejected for security. "
                        f"Use a regular file instead: {f}"
                    )
                setattr(persona, attr, f.read_text(encoding="utf-8").strip())

        return persona

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
