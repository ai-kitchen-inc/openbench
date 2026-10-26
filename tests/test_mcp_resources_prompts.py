"""Tests for MCP resource and prompt helpers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from openbench.mcp.prompts import DEFAULT_PROMPTS, MCPPrompt
from openbench.mcp.resources import MCPResource, resources_from_skills


class TestMCPResource(unittest.TestCase):
    def test_to_mcp_dict_excludes_text(self):
        resource = MCPResource(
            uri="openbench://skills/demo/SKILL.md",
            name="demo/SKILL.md",
            mime_type="text/markdown",
            text="# Demo",
            description="Demo skill",
        )
        payload = resource.to_mcp_dict()
        self.assertEqual(
            payload,
            {
                "uri": "openbench://skills/demo/SKILL.md",
                "name": "demo/SKILL.md",
                "mimeType": "text/markdown",
                "description": "Demo skill",
            },
        )
        # The body is served by a separate read call, never in the listing.
        self.assertNotIn("text", payload)


class TestResourcesFromSkills(unittest.TestCase):
    def _skill(self, name="demo", references=None):
        return SimpleNamespace(
            name=name,
            raw_skill_md=f"# {name}\nInstructions.",
            references=references or {},
        )

    def test_skill_md_becomes_resource(self):
        resources = resources_from_skills([self._skill()])
        uri = "openbench://skills/demo/SKILL.md"
        self.assertEqual(list(resources), [uri])
        self.assertEqual(resources[uri].text, "# demo\nInstructions.")
        self.assertEqual(resources[uri].mime_type, "text/markdown")

    def test_references_get_their_own_uris(self):
        skill = self._skill(references={"charts.md": "Chart rules", "api.md": "API notes"})
        resources = resources_from_skills([skill])
        self.assertEqual(len(resources), 3)
        ref_uri = "openbench://skills/demo/references/charts.md"
        self.assertIn(ref_uri, resources)
        self.assertEqual(resources[ref_uri].text, "Chart rules")
        self.assertEqual(resources[ref_uri].name, "demo/references/charts.md")

    def test_multiple_skills_do_not_collide(self):
        resources = resources_from_skills([self._skill("alpha"), self._skill("beta")])
        self.assertIn("openbench://skills/alpha/SKILL.md", resources)
        self.assertIn("openbench://skills/beta/SKILL.md", resources)

    def test_no_skills_yields_no_resources(self):
        self.assertEqual(resources_from_skills([]), {})


class TestMCPPrompt(unittest.TestCase):
    def test_render_substitutes_arguments(self):
        prompt = MCPPrompt(name="p", description="d", template="Read {path} about {topic}")
        self.assertEqual(
            prompt.render(path="/tmp/a.csv", topic="sales"), "Read /tmp/a.csv about sales"
        )

    def test_render_treats_none_as_empty(self):
        prompt = MCPPrompt(name="p", description="d", template="Focus: {focus}")
        self.assertEqual(prompt.render(focus=None), "Focus: ")

    def test_to_mcp_dict_excludes_template(self):
        prompt = MCPPrompt(name="p", description="d", arguments=[{"name": "x"}], template="{x}")
        self.assertEqual(
            prompt.to_mcp_dict(),
            {"name": "p", "description": "d", "arguments": [{"name": "x"}]},
        )


class TestDefaultPrompts(unittest.TestCase):
    def test_keys_match_prompt_names(self):
        for key, prompt in DEFAULT_PROMPTS.items():
            with self.subTest(prompt=key):
                self.assertEqual(key, prompt.name)

    def test_every_argument_is_described(self):
        for key, prompt in DEFAULT_PROMPTS.items():
            for argument in prompt.arguments:
                with self.subTest(prompt=key, argument=argument.get("name")):
                    self.assertTrue(argument.get("name"))
                    self.assertTrue(argument.get("description"))

    def test_templates_render_with_declared_arguments(self):
        for key, prompt in DEFAULT_PROMPTS.items():
            with self.subTest(prompt=key):
                kwargs = {argument["name"]: "value" for argument in prompt.arguments}
                rendered = prompt.render(**kwargs)
                self.assertTrue(rendered)
                self.assertNotIn("{", rendered)


if __name__ == "__main__":
    unittest.main()
