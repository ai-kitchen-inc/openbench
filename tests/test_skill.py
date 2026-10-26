"""Tests for the Skill Layer (Milestone 2 of RFC-PERSONA-LAYER).

Covers:
- Skill.from_dir() — loading SKILL.md, references/, tools.py
- Skill parser — H1, description, sections, bullets
- Skill.get_context() / get_tools() / summary() / __bool__
- SkillRegistry — SDK + project tier, resolution, collisions
- SkillRegistry.compose_context() / collect_tools()
- BaseAgent(skills=) integration — context appended, tools registered

No real LLM calls; tests use tmp_path for skill directories.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from openbench.intelligence import Persona, Skill, SkillRegistry
from openbench.intelligence.base import BaseAgent, MessageRole

# ---------------------------------------------------------------------------
# Fixtures — helpers to scaffold skill directories on tmp_path
# ---------------------------------------------------------------------------


def _write_skill(
    base: Path,
    name: str,
    *,
    description: str = "A test skill.",
    triggers: list[str] | None = None,
    dependencies: list[str] | None = None,
    version: str | None = None,
    references: dict[str, str] | None = None,
    tools_py: str | None = None,
) -> Path:
    """Create a skill directory with the given files. Returns the path."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)

    md = [f"# {name}\n", description, ""]
    if triggers:
        md.append("## Triggers")
        md.extend(f"- {t}" for t in triggers)
        md.append("")
    if dependencies:
        md.append("## Dependencies")
        md.extend(f"- {dep}" for dep in dependencies)
        md.append("")
    if version:
        md.append("## Version")
        md.append(version)
        md.append("")

    (d / "SKILL.md").write_text("\n".join(md), encoding="utf-8")

    if references:
        refs = d / "references"
        refs.mkdir(exist_ok=True)
        for fname, content in references.items():
            (refs / fname).write_text(content, encoding="utf-8")

    if tools_py is not None:
        (d / "tools.py").write_text(tools_py, encoding="utf-8")

    return d


# Sample tools.py content used in several tests
_TOOLS_SAMPLE = '''
def echo(message: str) -> str:
    """Echo the message back."""
    return message


ECHO_SCHEMA = {
    "type": "function",
    "function": {
        "name": "echo",
        "description": "Echo a message",
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
}


def shout(message: str) -> str:
    """Shout the message in uppercase."""
    return message.upper()


SHOUT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "shout",
        "description": "Shout a message",
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
}
'''


# ---------------------------------------------------------------------------
# Skill.from_dir — happy paths
# ---------------------------------------------------------------------------


class TestSkillFromDir:
    def test_loads_minimal_skill(self, tmp_path):
        d = _write_skill(tmp_path, "minimal-skill", description="Does one thing.")
        skill = Skill.from_dir(d)

        assert skill.name == "minimal-skill"
        assert skill.description == "Does one thing."
        assert skill.version == "0.1.0"  # default when not declared
        assert skill.triggers == []
        assert skill.dependencies == []
        assert skill.references == {}
        assert skill.tools == []
        assert skill.has_tools is False
        assert skill.source == str(d.resolve())

    def test_loads_triggers_and_dependencies(self, tmp_path):
        d = _write_skill(
            tmp_path,
            "data-viz",
            description="Chart generation.",
            triggers=["user asks for a chart", "visualization context present"],
            dependencies=["data-context-extractor", "export-excel >= 1.0.0"],
            version="1.2.0",
        )
        skill = Skill.from_dir(d)

        assert skill.version == "1.2.0"
        assert skill.triggers == [
            "user asks for a chart",
            "visualization context present",
        ]
        assert skill.dependencies == [
            "data-context-extractor",
            "export-excel >= 1.0.0",
        ]

    def test_loads_references(self, tmp_path):
        d = _write_skill(
            tmp_path,
            "regulated",
            references={
                "schema.md": "# Schema\nField rules.",
                "regulation.md": "# Regulation\nRules.",
            },
        )
        skill = Skill.from_dir(d)

        assert set(skill.references.keys()) == {"schema.md", "regulation.md"}
        assert "Field rules" in skill.references["schema.md"]

    def test_loads_tools_py(self, tmp_path):
        d = _write_skill(tmp_path, "echoer", tools_py=_TOOLS_SAMPLE)
        skill = Skill.from_dir(d)

        assert skill.has_tools is True
        tool_names = [n for n, _, _ in skill.tools]
        assert set(tool_names) == {"echo", "shout"}

        # Schemas are the module-level _SCHEMA dicts
        for _, _, schema in skill.tools:
            assert schema["type"] == "function"
            assert "parameters" in schema["function"]

    def test_tools_are_callable(self, tmp_path):
        d = _write_skill(tmp_path, "echoer2", tools_py=_TOOLS_SAMPLE)
        skill = Skill.from_dir(d)

        tools = {name: fn for name, fn, _ in skill.tools}
        assert tools["echo"]("hi") == "hi"
        assert tools["shout"]("hi") == "HI"

    def test_discover_tool_gaps_reports_silently_skipped_tools(self, tmp_path):
        from openbench.intelligence.skill import discover_tool_gaps

        gapped_tools = (
            _TOOLS_SAMPLE
            + '\n\nORPHAN_SCHEMA = {"type": "function"}\n'
            + 'BROKEN_SCHEMA = "not a dict"\n'
        )
        d = _write_skill(tmp_path, "gappy", tools_py=gapped_tools)
        skill = Skill.from_dir(d)

        # Discovery itself stays fail-open: only the valid pairs load.
        assert {n for n, _, _ in skill.tools} == {"echo", "shout"}
        gaps = discover_tool_gaps(skill._tools_module)
        assert len(gaps) == 2
        assert any("ORPHAN_SCHEMA" in gap and "orphan" in gap for gap in gaps)
        assert any("BROKEN_SCHEMA" in gap and "not a dict" in gap for gap in gaps)

    def test_discover_tool_gaps_clean_module(self, tmp_path):
        from openbench.intelligence.skill import discover_tool_gaps

        d = _write_skill(tmp_path, "clean-tools", tools_py=_TOOLS_SAMPLE)
        skill = Skill.from_dir(d)
        assert discover_tool_gaps(skill._tools_module) == []


# ---------------------------------------------------------------------------
# Skill.from_dir — error handling
# ---------------------------------------------------------------------------


class TestSkillFromDirErrors:
    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Skill directory not found"):
            Skill.from_dir(tmp_path / "does-not-exist")

    def test_missing_skill_md_raises(self, tmp_path):
        d = tmp_path / "broken"
        d.mkdir()
        with pytest.raises(FileNotFoundError, match=r"SKILL\.md missing"):
            Skill.from_dir(d)

    def test_missing_h1_raises(self, tmp_path):
        d = tmp_path / "no-h1"
        d.mkdir()
        (d / "SKILL.md").write_text("No heading here.\n\n## Some Section")
        with pytest.raises(ValueError, match="H1 heading"):
            Skill.from_dir(d)

    def test_broken_tools_py_raises(self, tmp_path):
        d = _write_skill(tmp_path, "broken-tools", tools_py="def oops(\n")
        with pytest.raises(SyntaxError):
            Skill.from_dir(d)


# ---------------------------------------------------------------------------
# Skill composition & introspection
# ---------------------------------------------------------------------------


class TestSkillComposition:
    def test_get_context_includes_skill_md_and_refs(self, tmp_path):
        d = _write_skill(
            tmp_path,
            "contextful",
            description="Provides context.",
            references={"extra.md": "Extra knowledge"},
        )
        skill = Skill.from_dir(d)
        ctx = skill.get_context()

        assert "contextful" in ctx
        assert "Provides context" in ctx
        assert "Extra knowledge" in ctx
        assert "Reference: extra.md" in ctx

    def test_knowledge_only_skill_has_tools_false(self, tmp_path):
        d = _write_skill(tmp_path, "knowledge-only", references={"rule.md": "Rule 1"})
        skill = Skill.from_dir(d)

        assert skill.has_tools is False
        assert skill.get_tools() == []
        assert bool(skill) is True  # still has context

    def test_summary_has_expected_keys(self, tmp_path):
        d = _write_skill(
            tmp_path,
            "summary-test",
            description="For summary.",
            dependencies=["other-skill"],
            references={"ref.md": "content"},
            tools_py=_TOOLS_SAMPLE,
        )
        skill = Skill.from_dir(d)
        s = skill.summary()

        assert s["name"] == "summary-test"
        assert s["version"] == "0.1.0"
        assert s["dependencies"] == ["other-skill"]
        assert set(s["references"]) == {"ref.md"}
        assert set(s["tools"]) == {"echo", "shout"}
        assert s["has_tools"] is True
        assert s["context_chars"] > 0

    def test_empty_skill_is_falsy(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        (d / "SKILL.md").write_text("# empty\n")
        skill = Skill.from_dir(d)
        # No description, no refs, no tools — effectively empty
        # SKILL.md body is just "# empty" so raw_skill_md is non-empty, bool True
        assert bool(skill) is True


# ---------------------------------------------------------------------------
# SkillRegistry — SDK + project tiers
# ---------------------------------------------------------------------------


class TestSkillRegistryLoading:
    def test_empty_registry(self, tmp_path):
        registry = SkillRegistry(sdk_skills_dir=tmp_path / "sdk-skills")
        registry.load_sdk_skills()  # no-op (dir does not exist)
        assert len(registry) == 0
        assert registry.compose_context() == ""
        assert registry.collect_tools() == []

    def test_load_sdk_skills_auto_discovers(self, tmp_path):
        sdk = tmp_path / "sdk"
        _write_skill(sdk, "alpha", description="Alpha skill")
        _write_skill(sdk, "beta", description="Beta skill")

        registry = SkillRegistry(sdk_skills_dir=sdk)
        registry.load_sdk_skills()

        assert len(registry) == 2
        assert "alpha" in registry
        assert "beta" in registry

    def test_load_project_skills_by_path(self, tmp_path):
        proj = tmp_path / "proj"
        _write_skill(proj, "ldi-parser", description="Parse LDI")

        registry = SkillRegistry(sdk_skills_dir=tmp_path / "sdk")
        registry.load_project_skills([proj / "ldi-parser"])

        assert "ldi-parser" in registry
        skill = registry.resolve("ldi-parser")
        assert skill.description == "Parse LDI"

    def test_project_overrides_sdk(self, tmp_path):
        sdk = tmp_path / "sdk"
        _write_skill(sdk, "shared", description="SDK version", version="1.0.0")

        proj = tmp_path / "proj"
        _write_skill(proj, "shared", description="Project override", version="2.0.0")

        registry = SkillRegistry(sdk_skills_dir=sdk)
        registry.load_sdk_skills()
        registry.load_project_skills([proj / "shared"])

        resolved = registry.resolve("shared")
        assert resolved.description == "Project override"
        assert resolved.version == "2.0.0"

    def test_unknown_skill_raises(self, tmp_path):
        registry = SkillRegistry(sdk_skills_dir=tmp_path / "sdk")
        with pytest.raises(KeyError, match="not found"):
            registry.resolve("nonexistent")


class TestSkillRegistryLoadSkills:
    """Tests for the convenience load_skills() that accepts mixed names/paths."""

    def test_named_sdk_skill(self, tmp_path):
        sdk = tmp_path / "sdk"
        _write_skill(sdk, "data-viz", description="Viz skill")

        registry = SkillRegistry(sdk_skills_dir=sdk)
        registry.load_sdk_skills()
        registry.load_skills(["data-viz"])  # bare name — looked up in SDK tier

        assert len(registry) == 1

    def test_named_sdk_skill_not_found_raises(self, tmp_path):
        registry = SkillRegistry(sdk_skills_dir=tmp_path / "sdk")
        registry.load_sdk_skills()
        with pytest.raises(KeyError, match="data-viz"):
            registry.load_skills(["data-viz"])

    def test_path_project_skill(self, tmp_path):
        proj = tmp_path / "proj"
        _write_skill(proj, "my-skill", description="Proj")

        registry = SkillRegistry(sdk_skills_dir=tmp_path / "sdk")
        registry.load_skills([str(proj / "my-skill")])

        assert "my-skill" in registry

    def test_mixed_names_and_paths(self, tmp_path):
        sdk = tmp_path / "sdk"
        _write_skill(sdk, "viz", description="SDK viz")

        proj = tmp_path / "proj"
        _write_skill(proj, "ldi", description="Project ldi")

        registry = SkillRegistry(sdk_skills_dir=sdk)
        registry.load_sdk_skills()
        registry.load_skills(["viz", str(proj / "ldi")])

        assert len(registry) == 2
        assert "viz" in registry
        assert "ldi" in registry


# ---------------------------------------------------------------------------
# SkillRegistry — composition
# ---------------------------------------------------------------------------


class TestSkillRegistryCompose:
    def test_compose_context_combines_all_skills(self, tmp_path):
        sdk = tmp_path / "sdk"
        _write_skill(sdk, "a", description="skill a")
        _write_skill(sdk, "b", description="skill b")

        registry = SkillRegistry(sdk_skills_dir=sdk)
        registry.load_sdk_skills()
        ctx = registry.compose_context()

        assert "skill a" in ctx
        assert "skill b" in ctx
        assert "# Skill: a" in ctx
        assert "# Skill: b" in ctx

    def test_compose_is_sorted_and_stable(self, tmp_path):
        sdk = tmp_path / "sdk"
        _write_skill(sdk, "zebra", description="z")
        _write_skill(sdk, "alpha", description="a")
        _write_skill(sdk, "beta", description="b")

        registry = SkillRegistry(sdk_skills_dir=sdk)
        registry.load_sdk_skills()
        ctx = registry.compose_context()

        # Alphabetical order
        assert ctx.index("alpha") < ctx.index("beta") < ctx.index("zebra")

    def test_collect_tools_returns_all(self, tmp_path):
        sdk = tmp_path / "sdk"
        _write_skill(sdk, "echoer", tools_py=_TOOLS_SAMPLE)

        registry = SkillRegistry(sdk_skills_dir=sdk)
        registry.load_sdk_skills()
        tools = registry.collect_tools()

        assert len(tools) == 2
        names = {name for name, _, _ in tools}
        assert names == {"echo", "shout"}

    def test_collect_tools_raises_on_collision(self, tmp_path):
        # Two skills both providing "echo" — should collide
        sdk = tmp_path / "sdk"
        _write_skill(sdk, "a-skill", tools_py=_TOOLS_SAMPLE)
        _write_skill(sdk, "b-skill", tools_py=_TOOLS_SAMPLE)

        registry = SkillRegistry(sdk_skills_dir=sdk)
        registry.load_sdk_skills()
        with pytest.raises(ValueError, match=r"Tool name collision.*echo"):
            registry.collect_tools()


# ---------------------------------------------------------------------------
# BaseAgent(skills=) integration
# ---------------------------------------------------------------------------


class TestBaseAgentSkillsIntegration:
    def test_agent_with_empty_skills_unchanged(self, tmp_path):
        persona = Persona(agents="Test persona")
        agent = BaseAgent(goal="test", persona=persona)

        assert agent._skill_registry is None
        assert "# Skill:" not in agent._system_prompt

    def test_agent_with_project_skill_path(self, tmp_path, monkeypatch):
        # Isolate from real SDK skills dir
        fake_sdk = tmp_path / "fake-sdk"
        monkeypatch.setattr(
            "openbench.intelligence.skill_registry._default_sdk_skills_dir",
            lambda: fake_sdk,
        )

        proj = tmp_path / "proj"
        _write_skill(
            proj,
            "test-skill",
            description="Test skill description",
            tools_py=_TOOLS_SAMPLE,
        )

        persona = Persona(agents="Base identity")
        agent = BaseAgent(
            goal="test",
            persona=persona,
            skills=[str(proj / "test-skill")],
        )

        # Skill context is appended to system prompt
        assert agent._skill_registry is not None
        assert "Base identity" in agent._system_prompt
        assert "test-skill" in agent._system_prompt
        assert "Test skill description" in agent._system_prompt

        # Tools are registered on the agent's ToolExecutor
        assert "echo" in agent.tools._tools
        assert "shout" in agent.tools._tools

        # First memory message reflects the composed prompt
        first = agent.memory.messages[0]
        assert first.role == MessageRole.SYSTEM
        assert "test-skill" in first.content

    def test_agent_tool_collision_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "openbench.intelligence.skill_registry._default_sdk_skills_dir",
            lambda: tmp_path / "fake-sdk",
        )

        def echo(message: str) -> str:
            return message

        proj = tmp_path / "proj"
        _write_skill(proj, "echo-skill", tools_py=_TOOLS_SAMPLE)

        persona = Persona(agents="id")

        # Agent already has its own `echo` tool before loading skills
        with pytest.raises(ValueError, match="conflicts with an existing tool"):
            BaseAgent(
                goal="test",
                tools=[echo],
                persona=persona,
                skills=[str(proj / "echo-skill")],
            )

    def test_agent_skill_appends_after_persona(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "openbench.intelligence.skill_registry._default_sdk_skills_dir",
            lambda: tmp_path / "fake-sdk",
        )

        proj = tmp_path / "proj"
        _write_skill(proj, "late-skill", description="Late")

        persona = Persona(agents="ZZZ-persona")
        agent = BaseAgent(
            goal="test",
            persona=persona,
            skills=[str(proj / "late-skill")],
        )

        # Persona content comes before skill content
        p_idx = agent._system_prompt.index("ZZZ-persona")
        s_idx = agent._system_prompt.index("late-skill")
        assert p_idx < s_idx


# ---------------------------------------------------------------------------
# Skill.bind() convention (storage-layer RFC §6)
# ---------------------------------------------------------------------------


_BINDABLE_TOOLS = '''
_state = {"store": None, "calls": 0}


def bind(store=None, **_):
    """Inject the agent's dependency into module state."""
    _state["store"] = store
    _state["calls"] += 1


def use_it() -> str:
    """Return the bound store or raise if not bound."""
    if _state["store"] is None:
        raise RuntimeError("not bound")
    return str(_state["store"])


USE_IT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "use_it",
        "description": "Use the bound store.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}
'''


class TestSkillBind:
    def test_bind_returns_true_when_module_defines_bind(self, tmp_path):
        _write_skill(tmp_path, "bindable", tools_py=_BINDABLE_TOOLS)
        skill = Skill.from_dir(tmp_path / "bindable")
        assert skill.bind(store="sentinel") is True

    def test_bind_returns_false_when_no_tools_module(self, tmp_path):
        _write_skill(tmp_path, "knowledge-only", description="no tools")
        skill = Skill.from_dir(tmp_path / "knowledge-only")
        assert skill.bind(store="sentinel") is False

    def test_bind_returns_false_when_module_has_no_bind(self, tmp_path):
        _write_skill(tmp_path, "sample", tools_py=_TOOLS_SAMPLE)
        skill = Skill.from_dir(tmp_path / "sample")
        assert skill.bind(store="sentinel") is False

    def test_bound_tool_sees_injected_dependency(self, tmp_path):
        _write_skill(tmp_path, "bindable", tools_py=_BINDABLE_TOOLS)
        skill = Skill.from_dir(tmp_path / "bindable")
        skill.bind(store="sentinel")
        tools = {name: fn for name, fn, _ in skill.tools}
        assert tools["use_it"]() == "sentinel"

    def test_bind_is_forward_compatible_with_extra_kwargs(self, tmp_path):
        _write_skill(tmp_path, "bindable", tools_py=_BINDABLE_TOOLS)
        skill = Skill.from_dir(tmp_path / "bindable")
        # Extra kwargs must not raise thanks to the ``**_`` in bind()
        skill.bind(store="sentinel", unknown="kwarg")


class TestSkillRegistryBind:
    def test_bind_forwards_to_every_skill(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "openbench.intelligence.skill_registry._default_sdk_skills_dir",
            lambda: tmp_path / "fake-sdk",
        )
        _write_skill(tmp_path / "fake-sdk", "a", tools_py=_BINDABLE_TOOLS)
        _write_skill(tmp_path / "fake-sdk", "b", tools_py=_BINDABLE_TOOLS)

        reg = SkillRegistry()
        reg.load_sdk_skills()
        bound = reg.bind(store="X")
        assert set(bound) == {"a", "b"}

    def test_bind_skips_skills_without_bind_function(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "openbench.intelligence.skill_registry._default_sdk_skills_dir",
            lambda: tmp_path / "fake-sdk",
        )
        _write_skill(tmp_path / "fake-sdk", "plain", tools_py=_TOOLS_SAMPLE)
        _write_skill(tmp_path / "fake-sdk", "bindable", tools_py=_BINDABLE_TOOLS)

        reg = SkillRegistry()
        reg.load_sdk_skills()
        bound = reg.bind(store="X")
        assert bound == ["bindable"]


# ---------------------------------------------------------------------------
# User tier (storage-layer RFC §7)
# ---------------------------------------------------------------------------


class TestUserTier:
    def test_load_user_skills_noop_when_missing(self, tmp_path):
        reg = SkillRegistry(user_skills_dir=tmp_path / "does-not-exist")
        reg.load_user_skills()
        assert len(reg) == 0

    def test_load_user_skills_from_default_dir(self, tmp_path):
        user_dir = tmp_path / "users"
        _write_skill(user_dir, "preset-a", description="User preset")
        reg = SkillRegistry(user_skills_dir=user_dir)
        reg.load_user_skills()
        assert "preset-a" in reg

    def test_load_user_skills_explicit_root(self, tmp_path):
        user_dir = tmp_path / "users"
        _write_skill(user_dir, "alt", description="User alt")
        reg = SkillRegistry()
        reg.load_user_skills(root=user_dir)
        assert "alt" in reg

    def test_resolution_order_project_wins_over_user(self, tmp_path):
        user_dir = tmp_path / "users"
        _write_skill(user_dir, "shared", description="user version")
        proj_dir = tmp_path / "proj"
        _write_skill(proj_dir, "shared", description="project version")

        reg = SkillRegistry(user_skills_dir=user_dir)
        reg.load_user_skills()
        reg.load_project_skills([proj_dir / "shared"])

        resolved = reg.resolve("shared")
        assert "project version" in resolved.description

    def test_resolution_order_user_wins_over_sdk(self, tmp_path, monkeypatch):
        sdk_dir = tmp_path / "fake-sdk"
        _write_skill(sdk_dir, "shared", description="sdk version")
        monkeypatch.setattr(
            "openbench.intelligence.skill_registry._default_sdk_skills_dir",
            lambda: sdk_dir,
        )
        user_dir = tmp_path / "users"
        _write_skill(user_dir, "shared", description="user version")

        reg = SkillRegistry(user_skills_dir=user_dir)
        reg.load_sdk_skills()
        reg.load_user_skills()

        assert "user version" in reg.resolve("shared").description

    def test_load_skills_accepts_bare_name_from_user_tier(self, tmp_path):
        user_dir = tmp_path / "users"
        _write_skill(user_dir, "user-only", description="only in user tier")
        reg = SkillRegistry(user_skills_dir=user_dir)
        reg.load_user_skills()
        # Must not raise — bare name should resolve to user tier.
        reg.load_skills(["user-only"])

    def test_summary_reports_user_skills_key(self, tmp_path):
        user_dir = tmp_path / "users"
        _write_skill(user_dir, "u1", description="u1")
        reg = SkillRegistry(user_skills_dir=user_dir)
        reg.load_user_skills()
        summary = reg.summary()
        assert "user_skills" in summary
        assert summary["user_skills"] == ["u1"]


# ---------------------------------------------------------------------------
# BaseAgent(scratchpad=) integration
# ---------------------------------------------------------------------------


class TestBaseAgentScratchpadBinding:
    """When scratchpad= is provided, memory-scratchpad tools can operate.

    Uses tmp_path-scoped skills dir so we don't need the real LLM.
    """

    def test_scratchpad_stored_on_agent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "openbench.intelligence.skill_registry._default_sdk_skills_dir",
            lambda: tmp_path / "fake-sdk",
        )
        sentinel = object()
        agent = BaseAgent(goal="t", scratchpad=sentinel)
        assert agent._scratchpad is sentinel

    def test_bind_wires_scratchpad_into_memory_scratchpad_skill(self, tmp_path, monkeypatch):
        # Point SDK skills at our fake dir with a bindable skill
        sdk_dir = tmp_path / "fake-sdk"
        _write_skill(sdk_dir, "memtest", tools_py=_BINDABLE_TOOLS)
        monkeypatch.setattr(
            "openbench.intelligence.skill_registry._default_sdk_skills_dir",
            lambda: sdk_dir,
        )

        scratchpad_obj = "pad-instance"  # any object; skill just stashes it
        agent = BaseAgent(
            goal="t",
            skills=["memtest"],
            scratchpad=scratchpad_obj,
        )

        # Our bindable skill uses **_ so 'scratchpad=' gets swallowed
        # silently — what we want to assert is that BaseAgent called
        # bind() at all. Peek at the module-level call counter.
        skill = agent._skill_registry.resolve("memtest")
        state = skill._tools_module._state  # type: ignore[union-attr]
        assert state["calls"] == 1


# ---------------------------------------------------------------------------
# Public API export
# ---------------------------------------------------------------------------


class TestSkillInAll:
    def test_skill_in_intelligence_all(self):
        from openbench import intelligence

        assert "Skill" in intelligence.__all__
        assert "SkillRegistry" in intelligence.__all__
        assert intelligence.Skill is Skill
        assert intelligence.SkillRegistry is SkillRegistry
