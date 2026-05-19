from __future__ import annotations

from pathlib import Path

from openbench.intelligence.skill import Skill


def test_openbench_skill_exposes_expected_tools():
    skill_dir = Path(__file__).resolve().parents[1] / "openbench-skill"
    skill = Skill.from_dir(skill_dir)

    assert skill.name == "image-search-mcp"
    assert {name for name, _, _ in skill.tools} == {
        "search_similar_images",
        "index_images",
        "rebuild_index",
        "list_index_stats",
        "remove_image",
    }
