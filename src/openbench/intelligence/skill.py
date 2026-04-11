"""Reusable capability package: knowledge + tools.

A Skill bundles three things agents need to gain a new capability:

1. **Knowledge** — ``SKILL.md`` describes the skill (who, what, when) and
   optional ``references/*.md`` files provide additional domain context.
2. **Tools** — an optional ``tools.py`` module exports Python callables
   paired with JSON schemas (``FOO_SCHEMA`` + ``foo()`` convention).
3. **Metadata** — name, version, triggers, and declared dependencies on
   other skills.

Skills are loaded from a directory structure::

    my-skill/
    ├── SKILL.md           # required
    ├── references/        # optional — reference docs
    │   ├── schema.md
    │   └── regulations.md
    └── tools.py           # optional — tool implementations

Skills with no ``tools.py`` are *knowledge-only* (``has_tools=False``) —
they contribute context to the system prompt without adding callables.

Example:
    skill = Skill.from_dir("src/openbench/skills/data-visualization")
    print(skill.name, skill.version)
    print(skill.get_context())   # composed context string
    for name, fn, schema in skill.get_tools():
        agent.tools.register(name, fn, schema=schema)
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["Skill"]


# ---------------------------------------------------------------------------
# SKILL.md parser — minimal, section-aware
# ---------------------------------------------------------------------------

_H1_RE = re.compile(r"^#\s+(.+?)\s*$")
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")


def _parse_skill_md(text: str) -> dict[str, Any]:
    """Parse SKILL.md into a structured dict.

    Returns:
        Dict with keys: name, description, version, triggers (list),
        dependencies (list), sections (dict of H2 title -> raw body text).

    Raises:
        ValueError: If no H1 heading is found (required).
    """
    lines = text.splitlines()
    name: str | None = None
    description: str = ""
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    desc_lines: list[str] = []
    in_description = False

    for raw in lines:
        # H1 — only the first one counts as the skill name
        h1 = _H1_RE.match(raw)
        if h1 and name is None:
            name = h1.group(1).strip()
            in_description = True
            continue

        # H2 — starts a new section, closes description collection
        h2 = _H2_RE.match(raw)
        if h2:
            in_description = False
            current_section = h2.group(1).strip()
            sections[current_section] = []
            continue

        if in_description:
            if raw.strip():
                desc_lines.append(raw.strip())
            elif desc_lines:
                # Blank line after description content ends the first paragraph
                in_description = False
            continue

        if current_section is not None:
            sections[current_section].append(raw)

    if name is None:
        raise ValueError("SKILL.md must start with an H1 heading (the skill name)")

    description = " ".join(desc_lines)

    def _bullets(section_name: str) -> list[str]:
        body = sections.get(section_name, [])
        return [m.group(1) for m in (_BULLET_RE.match(ln) for ln in body) if m]

    version = "0.1.0"
    version_body = sections.get("Version", [])
    for ln in version_body:
        stripped = ln.strip()
        if stripped:
            version = stripped
            break

    return {
        "name": name,
        "description": description,
        "version": version,
        "triggers": _bullets("Triggers"),
        "dependencies": _bullets("Dependencies"),
        "sections": {k: "\n".join(v).strip() for k, v in sections.items()},
    }


# ---------------------------------------------------------------------------
# tools.py loader — imports module and discovers tool callables by _SCHEMA
# ---------------------------------------------------------------------------


def _load_tools_module(tools_py: Path, skill_name: str) -> Any:
    """Import a skill's tools.py as a standalone module.

    Uses ``importlib.util`` so the file doesn't need to be on ``sys.path``.
    The module name is namespaced as ``openbench_skill_<skill>`` to avoid
    collisions with user code.
    """
    mod_name = f"openbench_skill_{skill_name.replace('-', '_').replace(' ', '_')}"
    spec = importlib.util.spec_from_file_location(mod_name, tools_py)
    if spec is None or spec.loader is None:  # pragma: no cover — defensive
        raise ImportError(f"Cannot load spec for {tools_py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _discover_tools(module: Any) -> list[tuple[str, Callable, dict]]:
    """Find (name, callable, schema) tuples in a tools module.

    Convention: for every ``FOO_SCHEMA`` dict, look for a lower-case
    callable ``foo`` in the same module. Both must be present for the
    tool to be discovered. This matches the pattern used throughout the
    existing OpenBench example code (see lci-ignite-x tools.py).
    """
    tools: list[tuple[str, Callable, dict]] = []
    for attr_name in dir(module):
        if not attr_name.endswith("_SCHEMA"):
            continue
        if attr_name.startswith("_"):
            continue
        schema = getattr(module, attr_name)
        if not isinstance(schema, dict):
            continue
        fn_name = attr_name[: -len("_SCHEMA")].lower()
        fn = getattr(module, fn_name, None)
        if fn is None or not callable(fn):
            continue
        tools.append((fn_name, fn, schema))
    return tools


# ---------------------------------------------------------------------------
# Skill dataclass
# ---------------------------------------------------------------------------


@dataclass
class Skill:
    """A reusable capability package: knowledge + tools.

    Attributes:
        name: Human-readable skill name parsed from SKILL.md H1.
        version: Semver string (defaults to "0.1.0" if not declared).
        description: First paragraph of SKILL.md (after the H1 heading).
        triggers: Bullet list from the "## Triggers" section.
        dependencies: Bullet list from the "## Dependencies" section.
        references: Map of reference filename -> markdown content.
        tools: List of (tool_name, callable, json_schema) tuples.
        has_tools: True if the skill includes a tools.py module.
        source: Absolute path to the skill directory (for introspection).
        raw_skill_md: Full contents of SKILL.md (for context composition).
    """

    name: str
    version: str = "0.1.0"
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    references: dict[str, str] = field(default_factory=dict)
    tools: list[tuple[str, Callable, dict]] = field(default_factory=list)
    has_tools: bool = False
    source: str = ""
    raw_skill_md: str = ""

    @classmethod
    def from_dir(cls, path: str | Path) -> Skill:
        """Load a skill from a directory containing SKILL.md.

        Args:
            path: Directory with SKILL.md (required), references/ (optional),
                tools.py (optional).

        Returns:
            Skill instance with all metadata, references, and tools loaded.

        Raises:
            FileNotFoundError: If directory or SKILL.md does not exist.
            ValueError: If SKILL.md is missing an H1 heading.
            ImportError: If tools.py has syntax or import errors.
        """
        d = Path(path)
        if not d.is_dir():
            raise FileNotFoundError(f"Skill directory not found: {d}")

        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            raise FileNotFoundError(f"SKILL.md missing in skill directory: {d}")

        raw = skill_md.read_text(encoding="utf-8")
        parsed = _parse_skill_md(raw)

        # Load references/ — markdown files only
        references: dict[str, str] = {}
        refs_dir = d / "references"
        if refs_dir.is_dir():
            for ref_file in sorted(refs_dir.glob("*.md")):
                references[ref_file.name] = ref_file.read_text(encoding="utf-8").strip()

        # Load tools.py if present
        tools: list[tuple[str, Callable, dict]] = []
        has_tools = False
        tools_py = d / "tools.py"
        if tools_py.exists():
            module = _load_tools_module(tools_py, parsed["name"])
            tools = _discover_tools(module)
            has_tools = True

        return cls(
            name=parsed["name"],
            version=parsed["version"],
            description=parsed["description"],
            triggers=parsed["triggers"],
            dependencies=parsed["dependencies"],
            references=references,
            tools=tools,
            has_tools=has_tools,
            source=str(d.resolve()),
            raw_skill_md=raw.strip(),
        )

    def get_context(self) -> str:
        """Compose SKILL.md + references into a single context string.

        The output is appended to the agent's system prompt by
        ``SkillRegistry.compose_context()``.
        """
        parts: list[str] = []
        if self.raw_skill_md:
            parts.append(self.raw_skill_md)
        for filename, content in self.references.items():
            parts.append(f"### Reference: {filename}\n\n{content}")
        return "\n\n".join(parts)

    def get_tools(self) -> list[tuple[str, Callable, dict]]:
        """Return tool tuples for registration with ``ToolExecutor``."""
        return list(self.tools)

    def summary(self) -> dict[str, Any]:
        """Return a debug summary for introspection.

        Used by ``BaseAgent`` debug logs and tests.
        """
        return {
            "name": self.name,
            "version": self.version,
            "source": self.source,
            "triggers": len(self.triggers),
            "dependencies": list(self.dependencies),
            "references": list(self.references.keys()),
            "tools": [name for name, _, _ in self.tools],
            "has_tools": self.has_tools,
            "context_chars": len(self.get_context()),
        }

    def __bool__(self) -> bool:
        """A skill is truthy if it has any context or tools to contribute."""
        return bool(self.raw_skill_md or self.references or self.tools)
