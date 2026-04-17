"""Three-tier skill registry: SDK + user + project skills.

A ``SkillRegistry`` resolves skill names from three layers, in order of
increasing specificity:

1. **SDK tier** — skills that ship with OpenBench, auto-discovered from
   ``src/openbench/skills/*/SKILL.md``. Every project gets these for free.
2. **User tier** — personal skills the end user defines under
   ``~/.openbench/skills/``. Intended for "saved prompt" style presets
   the user wants across every agent on their machine.
3. **Project tier** — domain-specific skills loaded from explicit paths
   passed to ``load_project_skills()``. These override both SDK and
   user skills when names collide.

Resolution rule: ``resolve(name)`` checks project → user → SDK.

One registry instance is owned by each ``BaseAgent``. The registry is
**not** a global singleton — two agents in the same process can load
different skill sets without interfering with each other.

Example:
    registry = SkillRegistry()
    registry.load_sdk_skills()                       # bundled SDK skills
    registry.load_user_skills()                      # ~/.openbench/skills/
    registry.load_project_skills(["skills/ldi-parser"])
    skill = registry.resolve("ldi-parser")           # project wins
    context = registry.compose_context()             # for system prompt
    tools = registry.collect_tools()                 # for ToolExecutor
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from openbench.intelligence.skill import Skill

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

__all__ = ["SkillRegistry"]

logger = logging.getLogger("openbench.skills")


def _default_sdk_skills_dir() -> Path:
    """Return the directory that holds bundled SDK skills."""
    # skill_registry.py lives at src/openbench/intelligence/skill_registry.py
    # SDK skills live at        src/openbench/skills/
    return Path(__file__).resolve().parent.parent / "skills"


def _default_user_skills_dir() -> Path:
    """Return the default directory for user-defined skills."""
    return Path("~/.openbench/skills/").expanduser()


class SkillRegistry:
    """Three-tier skill resolver owned per-agent.

    Resolution rule: ``resolve(name)`` checks project → user → SDK.
    Overrides are logged at INFO level so they're visible to anyone
    debugging unexpected behavior.
    """

    def __init__(
        self,
        sdk_skills_dir: Path | None = None,
        user_skills_dir: Path | None = None,
    ):
        self._sdk_dir = sdk_skills_dir or _default_sdk_skills_dir()
        self._user_dir = user_skills_dir or _default_user_skills_dir()
        self._sdk: dict[str, Skill] = {}
        self._user: dict[str, Skill] = {}
        self._project: dict[str, Skill] = {}

    # ------------------------------------------------------------------ loading

    def load_sdk_skills(self) -> None:
        """Auto-discover SDK skills from ``src/openbench/skills/*/``.

        Silently no-ops if the SDK skills directory does not exist yet —
        this is the normal state before any SDK skills have been authored.
        """
        if not self._sdk_dir.is_dir():
            return

        for entry in sorted(self._sdk_dir.iterdir()):
            if not entry.is_dir():
                continue
            if not (entry / "SKILL.md").exists():
                continue
            skill = Skill.from_dir(entry)
            self._sdk[skill.name] = skill
            logger.info(
                "Loaded SDK skill: %s v%s (%d refs, %d tools)",
                skill.name,
                skill.version,
                len(skill.references),
                len(skill.tools),
            )

    def load_user_skills(self, root: str | Path | None = None) -> None:
        """Auto-discover user-defined skills from a root directory.

        Defaults to ``~/.openbench/skills/``. Each immediate subdirectory
        that contains a ``SKILL.md`` is loaded into the user tier.
        Silently no-ops if the directory does not exist — users without
        personal skills get no error.

        Args:
            root: Override the default user-skills root (tests, etc.).
        """
        root_path = Path(root).expanduser() if root is not None else self._user_dir
        if not root_path.is_dir():
            return

        for entry in sorted(root_path.iterdir()):
            if not entry.is_dir():
                continue
            if not (entry / "SKILL.md").exists():
                continue
            skill = Skill.from_dir(entry)
            if skill.name in self._sdk:
                logger.info(
                    "User skill '%s' overrides SDK skill of the same name",
                    skill.name,
                )
            self._user[skill.name] = skill
            logger.info(
                "Loaded user skill: %s v%s (%d refs, %d tools)",
                skill.name,
                skill.version,
                len(skill.references),
                len(skill.tools),
            )

    def load_project_skills(self, paths: list[str | Path]) -> None:
        """Load project skills from explicit directory paths.

        Each path must be a directory containing ``SKILL.md``. Project
        skills whose names collide with SDK skills replace the SDK version.

        Args:
            paths: List of skill directory paths.

        Raises:
            FileNotFoundError: If any path does not contain SKILL.md.
            ValueError: If any SKILL.md is malformed.
        """
        for path in paths:
            skill = Skill.from_dir(path)
            if skill.name in self._sdk:
                logger.info(
                    "Project skill '%s' overrides SDK skill of the same name",
                    skill.name,
                )
            self._project[skill.name] = skill
            logger.info(
                "Loaded project skill: %s v%s (%d refs, %d tools)",
                skill.name,
                skill.version,
                len(skill.references),
                len(skill.tools),
            )

    def load_skills(self, names_or_paths: list[str | Path]) -> None:
        """Load skills from mixed names (SDK) and paths (project).

        This is the convenience method used by ``BaseAgent(skills=...)``.
        Items are classified by heuristic:

        - Items that look like a path (contain ``/``, ``\\``, or end with
          an existing directory) are loaded as project skills.
        - Bare names are resolved against the SDK tier (requires
          ``load_sdk_skills()`` to have been called).

        Raises:
            KeyError: If a bare name is not found among loaded SDK skills.
            FileNotFoundError: If a path does not contain SKILL.md.
        """
        for item in names_or_paths:
            p = Path(str(item))
            if self._looks_like_path(item) or p.is_dir():
                self.load_project_skills([item])
            else:
                # Bare name — must already be loaded in the SDK or user tier.
                name = str(item)
                if name not in self._sdk and name not in self._user:
                    raise KeyError(
                        f"Skill {name!r} not found. "
                        f"SDK: {sorted(self._sdk.keys())}, "
                        f"user: {sorted(self._user.keys())}. "
                        f"Did you forget to call load_sdk_skills() / "
                        f"load_user_skills(), or pass a project skill path?"
                    )

    @staticmethod
    def _looks_like_path(item: str | Path) -> bool:
        """True if the item should be treated as a filesystem path."""
        if isinstance(item, Path):
            return True
        s = str(item)
        return "/" in s or "\\" in s or s.startswith(".")

    # ---------------------------------------------------------------- resolution

    def resolve(self, name: str) -> Skill:
        """Return a skill by name. Project > user > SDK on collision.

        Raises:
            KeyError: If the skill is not found in any tier.
        """
        if name in self._project:
            return self._project[name]
        if name in self._user:
            return self._user[name]
        if name in self._sdk:
            return self._sdk[name]
        raise KeyError(
            f"Skill {name!r} not found. "
            f"SDK: {sorted(self._sdk.keys())}, "
            f"user: {sorted(self._user.keys())}, "
            f"project: {sorted(self._project.keys())}"
        )

    def all(self) -> list[Skill]:
        """Return every loaded skill with tier overrides applied.

        Merge order matches ``resolve()``: SDK first, then user, then
        project, so later tiers override earlier ones on name collision.
        """
        merged: dict[str, Skill] = {**self._sdk, **self._user, **self._project}
        return list(merged.values())

    def __iter__(self) -> Iterator[Skill]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(set(self._sdk) | set(self._user) | set(self._project))

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        return name in self._sdk or name in self._user or name in self._project

    # --------------------------------------------------------------- composition

    def compose_context(self) -> str:
        """Compose all loaded skill contexts into a single prompt string.

        Used by ``BaseAgent`` to append skill context to the system prompt
        after the persona. Order is stable: loaded skills sorted by name.
        Empty if no skills loaded.
        """
        skills = sorted(self.all(), key=lambda s: s.name)
        parts: list[str] = []
        for skill in skills:
            ctx = skill.get_context()
            if not ctx:
                continue
            parts.append(f"# Skill: {skill.name}\n\n{ctx}")
        return "\n\n---\n\n".join(parts)

    def collect_tools(self) -> list[tuple[str, Callable, dict]]:
        """Collect (name, callable, schema) tuples from every loaded skill.

        Tool-name collisions across skills raise ``ValueError`` — the
        caller must rename or exclude one of the conflicting tools.
        """
        seen: dict[str, str] = {}  # tool_name -> skill_name
        collected: list[tuple[str, Callable, dict]] = []
        for skill in self.all():
            for tool_name, fn, schema in skill.get_tools():
                if tool_name in seen:
                    raise ValueError(
                        f"Tool name collision: '{tool_name}' is provided by "
                        f"both '{seen[tool_name]}' and '{skill.name}'. "
                        f"Rename one of the tools or exclude a skill."
                    )
                seen[tool_name] = skill.name
                collected.append((tool_name, fn, schema))
        return collected

    def bind(self, **kwargs: object) -> list[str]:
        """Broadcast ``kwargs`` to every loaded skill's ``tools.bind``.

        Skills with no ``bind`` function in their ``tools.py`` are
        silently skipped. This is the DI hook used by ``BaseAgent`` to
        pass agent-scoped state (e.g. a ``ScratchpadStore`` instance)
        into tools that need it.

        Args:
            **kwargs: Keyword arguments forwarded to every skill's bind().

        Returns:
            Names of the skills that accepted a ``bind`` call.
        """
        bound = [skill.name for skill in self.all() if skill.bind(**kwargs)]
        if bound:
            logger.info("Bound runtime state to %d skill(s): %s", len(bound), bound)
        return bound

    def summary(self) -> dict:
        """Debug summary for observability (Section 16 of the RFC)."""
        return {
            "sdk_skills": [s.name for s in self._sdk.values()],
            "user_skills": [s.name for s in self._user.values()],
            "project_skills": [s.name for s in self._project.values()],
            "total": len(self),
            "context_chars": len(self.compose_context()),
            "total_tools": sum(len(s.tools) for s in self.all()),
        }
