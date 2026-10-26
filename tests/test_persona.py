"""Tests for Persona class — file-based agent identity composition."""

import pytest

from openbench.intelligence.persona import Persona


class TestPersonaCompose:
    """Tests for Persona.compose()."""

    def test_compose_all_three_sections(self):
        persona = Persona(
            soul="WHO content",
            style="HOW content",
            agents="WHAT content",
        )
        result = persona.compose()
        assert result == "WHO content\n\nHOW content\n\nWHAT content"

    def test_compose_only_soul(self):
        persona = Persona(soul="Just identity")
        assert persona.compose() == "Just identity"

    def test_compose_only_agents(self):
        persona = Persona(agents="Just rules")
        assert persona.compose() == "Just rules"

    def test_compose_skips_empty_sections(self):
        persona = Persona(soul="WHO", agents="WHAT")  # no style
        assert persona.compose() == "WHO\n\nWHAT"

    def test_compose_empty_persona(self):
        assert Persona().compose() == ""

    def test_section_order_is_fixed(self):
        """soul -> style -> agents (identity before rules)."""
        persona = Persona(soul="A", style="B", agents="C")
        result = persona.compose()
        assert result.index("A") < result.index("B") < result.index("C")


class TestPersonaBool:
    """Tests for Persona.__bool__."""

    def test_empty_persona_is_falsy(self):
        assert bool(Persona()) is False

    def test_persona_with_soul_is_truthy(self):
        assert bool(Persona(soul="x")) is True

    def test_persona_with_style_is_truthy(self):
        assert bool(Persona(style="x")) is True

    def test_persona_with_agents_is_truthy(self):
        assert bool(Persona(agents="x")) is True


class TestPersonaSummary:
    """Tests for Persona.summary()."""

    def test_summary_returns_char_counts(self):
        persona = Persona(soul="abc", style="de", agents="fghi")
        summary = persona.summary()
        assert summary["soul_chars"] == 3
        assert summary["style_chars"] == 2
        assert summary["agents_chars"] == 4

    def test_summary_includes_total(self):
        persona = Persona(soul="abc", style="de", agents="fghi")
        summary = persona.summary()
        # total includes section content + 2x "\n\n" separators (4 chars)
        assert summary["total_chars"] == 3 + 2 + 4 + 4

    def test_summary_includes_source(self):
        persona = Persona(source="soul/")
        assert persona.summary()["source"] == "soul/"


class TestPersonaFromDir:
    """Tests for Persona.from_dir()."""

    def test_loads_all_three_files(self, tmp_path):
        (tmp_path / "SOUL.md").write_text("Identity content.")
        (tmp_path / "STYLE.md").write_text("Style content.")
        (tmp_path / "AGENTS.md").write_text("Rules content.")

        persona = Persona.from_dir(tmp_path)

        assert persona.soul == "Identity content."
        assert persona.style == "Style content."
        assert persona.agents == "Rules content."

    def test_missing_files_ok(self, tmp_path):
        """Missing files produce empty strings, no error."""
        (tmp_path / "AGENTS.md").write_text("Only rules.")

        persona = Persona.from_dir(tmp_path)

        assert persona.soul == ""
        assert persona.style == ""
        assert persona.agents == "Only rules."

    def test_empty_directory(self, tmp_path):
        """Empty directory produces empty persona."""
        persona = Persona.from_dir(tmp_path)
        assert persona.soul == ""
        assert persona.style == ""
        assert persona.agents == ""
        assert persona.compose() == ""
        assert bool(persona) is False

    def test_strips_whitespace(self, tmp_path):
        """File content is stripped of leading/trailing whitespace."""
        (tmp_path / "SOUL.md").write_text("\n\n  Identity  \n\n")
        persona = Persona.from_dir(tmp_path)
        assert persona.soul == "Identity"

    def test_unicode_content(self, tmp_path):
        """Bilingual content (Indonesian + English) loads correctly."""
        (tmp_path / "SOUL.md").write_text("Asisten LCA bilingual ID/EN")
        persona = Persona.from_dir(tmp_path)
        assert "bilingual" in persona.soul

    def test_directory_not_found(self):
        with pytest.raises(FileNotFoundError, match="Persona directory not found"):
            Persona.from_dir("/nonexistent/path/that/does/not/exist")

    def test_path_as_string_works(self, tmp_path):
        (tmp_path / "SOUL.md").write_text("X")
        persona = Persona.from_dir(str(tmp_path))
        assert persona.soul == "X"

    def test_source_recorded(self, tmp_path):
        (tmp_path / "SOUL.md").write_text("X")
        persona = Persona.from_dir(tmp_path)
        assert str(tmp_path) in persona.source

    def test_compose_after_from_dir(self, tmp_path):
        (tmp_path / "SOUL.md").write_text("WHO")
        (tmp_path / "AGENTS.md").write_text("WHAT")

        result = Persona.from_dir(tmp_path).compose()

        assert result == "WHO\n\nWHAT"
        assert "STYLE" not in result  # missing file excluded


class TestPersonaFromPrompt:
    """Tests for Persona.from_prompt() — backward compat."""

    def test_wraps_prompt_as_agents_section(self):
        prompt = "You are a helpful assistant. Follow these rules."
        persona = Persona.from_prompt(prompt)
        assert persona.agents == prompt
        assert persona.soul == ""
        assert persona.style == ""

    def test_compose_returns_original_prompt(self):
        prompt = "Original system prompt content"
        persona = Persona.from_prompt(prompt)
        assert persona.compose() == prompt

    def test_source_marked_inline(self):
        persona = Persona.from_prompt("X")
        assert persona.source == "inline"

    def test_empty_prompt(self):
        persona = Persona.from_prompt("")
        assert persona.compose() == ""
        assert bool(persona) is False


class TestPersonaIntegration:
    """End-to-end scenarios."""

    def test_lci_ignite_x_style_persona(self, tmp_path):
        """Realistic LCI Ignite X persona structure."""
        (tmp_path / "SOUL.md").write_text(
            "# LCI Ignite X\n\n"
            "AI-powered LCA analyst for PROPER 2025 submissions.\n\n"
            "## Domain Knowledge\n"
            "- ISO 14040/44 standards\n"
            "- 17 LDI categories"
        )
        (tmp_path / "STYLE.md").write_text(
            "# Communication Style\n\n"
            "## Language\n"
            "- Bilingual: Indonesian for chat, English for technical terms"
        )
        (tmp_path / "AGENTS.md").write_text(
            "# Operating Rules\n\n"
            "## Pipeline\n"
            "1. parse_ldi_sheet\n"
            "2. aggregate_flows\n"
            "3. select_pareto_items"
        )

        persona = Persona.from_dir(tmp_path)
        composed = persona.compose()

        assert "LCI Ignite X" in composed
        assert "Bilingual" in composed
        assert "Pipeline" in composed
        # Section order
        assert composed.index("Domain Knowledge") < composed.index("Language")
        assert composed.index("Language") < composed.index("Pipeline")


class TestBaseAgentPersonaIntegration:
    """Tests for BaseAgent(persona=) parameter."""

    def test_persona_path_loaded(self, tmp_path):
        """Passing a path string loads persona from directory."""
        from openbench.intelligence.base import BaseAgent

        (tmp_path / "SOUL.md").write_text("You are an LCA analyst.")

        agent = BaseAgent(goal="test", persona=str(tmp_path))

        assert "LCA analyst" in agent._system_prompt
        assert agent._persona is not None
        assert agent._persona.soul == "You are an LCA analyst."

    def test_persona_object_passed(self, tmp_path):
        """Passing a Persona instance directly."""
        from openbench.intelligence.base import BaseAgent

        persona = Persona(soul="Identity", agents="Rules")
        agent = BaseAgent(goal="test", persona=persona)

        assert "Identity" in agent._system_prompt
        assert "Rules" in agent._system_prompt
        assert agent._persona is persona

    def test_persona_overrides_system_prompt_with_warning(self, tmp_path):
        """When both provided, persona wins and warning is emitted."""
        from openbench.intelligence.base import BaseAgent

        (tmp_path / "SOUL.md").write_text("Persona wins.")

        with pytest.warns(UserWarning, match="persona= takes precedence"):
            agent = BaseAgent(
                goal="test",
                persona=str(tmp_path),
                system_prompt="This is ignored.",
            )

        assert "Persona wins" in agent._system_prompt
        assert "ignored" not in agent._system_prompt

    def test_system_prompt_only_still_works(self):
        """Backward compat: system_prompt= without persona= unchanged."""
        from openbench.intelligence.base import BaseAgent

        agent = BaseAgent(goal="test", system_prompt="Legacy prompt")

        assert agent._system_prompt == "Legacy prompt"
        assert agent._persona is None

    def test_no_persona_no_system_prompt(self):
        """Backward compat: neither provided uses default system prompt."""
        from openbench.intelligence.base import BaseAgent

        agent = BaseAgent(goal="test")

        # Should use _default_system_prompt()
        assert agent._system_prompt  # not empty
        assert agent._persona is None

    def test_invalid_persona_type_raises(self):
        """Invalid type for persona= raises TypeError."""
        from openbench.intelligence.base import BaseAgent

        with pytest.raises(TypeError, match="persona must be str, Path, Persona"):
            BaseAgent(goal="test", persona=123)

    def test_persona_dir_not_found_raises(self):
        """Non-existent persona directory raises FileNotFoundError."""
        from openbench.intelligence.base import BaseAgent

        with pytest.raises(FileNotFoundError):
            BaseAgent(goal="test", persona="/nonexistent/path")


class TestPersonaWithPersistentMemory:
    """Tests for persona= combined with PersistentMemory (session resume)."""

    def test_persona_with_new_persistent_memory(self, tmp_path):
        """New session: persona system prompt added to PersistentMemory."""
        from openbench.intelligence.base import BaseAgent
        from openbench.intelligence.memory import SQLiteMemoryStore

        (tmp_path / "SOUL.md").write_text("You are an LCA analyst.")
        db_path = tmp_path / "memory.db"
        store = SQLiteMemoryStore(db_path=str(db_path))

        agent = BaseAgent(
            goal="test",
            persona=str(tmp_path),
            memory_store=store,
            session_id="session-1",
        )

        # System message should be present in memory
        assert agent.memory.messages[0].content.startswith("You are an LCA analyst")

    def test_persona_replaces_old_system_on_resume(self, tmp_path):
        """Resumed session: persona= replaces existing system message."""
        from openbench.intelligence.base import BaseAgent
        from openbench.intelligence.memory import SQLiteMemoryStore

        # Session 1: persona v1
        (tmp_path / "SOUL.md").write_text("Original identity v1.")
        db_path = tmp_path / "memory.db"
        store = SQLiteMemoryStore(db_path=str(db_path))

        agent1 = BaseAgent(
            goal="test",
            persona=str(tmp_path),
            memory_store=store,
            session_id="session-1",
        )
        assert "v1" in agent1.memory.messages[0].content

        # Edit persona file (simulating user edit between sessions)
        (tmp_path / "SOUL.md").write_text("Updated identity v2.")

        # Session 2: resume with same session_id, new persona content
        store2 = SQLiteMemoryStore(db_path=str(db_path))
        agent2 = BaseAgent(
            goal="test",
            persona=str(tmp_path),
            memory_store=store2,
            session_id="session-1",
        )

        # Critical: agent2 should use v2, NOT v1 from the persisted session
        assert "v2" in agent2.memory.messages[0].content
        assert "v1" not in agent2.memory.messages[0].content

    def test_legacy_system_prompt_preserved_on_resume(self, tmp_path):
        """Backward compat: system_prompt= without persona= preserves resumed session."""
        from openbench.intelligence.base import BaseAgent
        from openbench.intelligence.memory import SQLiteMemoryStore

        db_path = tmp_path / "memory.db"
        store = SQLiteMemoryStore(db_path=str(db_path))

        # Session 1: original prompt
        agent1 = BaseAgent(
            goal="test",
            system_prompt="Original prompt",
            memory_store=store,
            session_id="session-x",
        )
        assert agent1.memory.messages[0].content == "Original prompt"

        # Session 2: different prompt — should NOT replace (legacy behavior)
        store2 = SQLiteMemoryStore(db_path=str(db_path))
        agent2 = BaseAgent(
            goal="test",
            system_prompt="New prompt",
            memory_store=store2,
            session_id="session-x",
        )
        # Legacy behavior: keeps original prompt from session
        assert agent2.memory.messages[0].content == "Original prompt"


class TestPersonaEmptyDirectory:
    """Tests for Fix #2: empty persona directory should not silently fall back."""

    def test_empty_persona_dir_uses_empty_prompt(self, tmp_path):
        """Empty persona dir = empty system prompt (no fallback to default)."""
        from openbench.intelligence.base import BaseAgent

        # Empty directory — no SOUL/STYLE/AGENTS files
        agent = BaseAgent(goal="test", persona=str(tmp_path))

        # System prompt should be empty (or just empty), NOT _default_system_prompt
        assert agent._system_prompt == ""

    def test_no_persona_no_system_prompt_uses_default(self):
        """Without persona= AND without system_prompt=, fall back to default."""
        from openbench.intelligence.base import BaseAgent

        agent = BaseAgent(goal="test")

        # No persona, no system_prompt → default kicks in
        assert agent._system_prompt != ""  # default is non-empty


class TestPersonaSourceDefault:
    """Tests for Fix #3: source default should be empty string, not 'inline'."""

    def test_bare_persona_has_empty_source(self):
        """Persona() constructed inline has empty source, not 'inline'."""
        persona = Persona()
        assert persona.source == ""

    def test_from_prompt_has_inline_source(self):
        """from_prompt() explicitly sets source='inline'."""
        persona = Persona.from_prompt("X")
        assert persona.source == "inline"

    def test_from_dir_has_path_source(self, tmp_path):
        (tmp_path / "SOUL.md").write_text("X")
        persona = Persona.from_dir(tmp_path)
        assert persona.source == str(tmp_path.resolve())


class TestPersonaInAll:
    """Test that Persona is properly exported."""

    def test_persona_in_all(self):
        from openbench import intelligence

        assert "Persona" in intelligence.__all__

    def test_persona_importable_from_package(self):
        from openbench.intelligence import Persona

        assert Persona is not None
