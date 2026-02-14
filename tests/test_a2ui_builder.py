"""Tests for A2UI v0.10 message builder."""

import json
import unittest

from openbench.chat.a2ui.builder import A2UIMessageBuilder
from openbench.chat.a2ui.catalog import OPENBENCH_CATALOG_ID
from openbench.chat.a2ui.schema import A2UI_VERSION, A2UIComponent


class TestA2UIMessageBuilder(unittest.TestCase):
    """Tests for A2UIMessageBuilder."""

    def setUp(self):
        self.builder = A2UIMessageBuilder()

    def test_default_catalog_id(self):
        self.assertEqual(self.builder.catalog_id, OPENBENCH_CATALOG_ID)

    def test_custom_catalog_id(self):
        builder = A2UIMessageBuilder(catalog_id="custom:v1")
        self.assertEqual(builder.catalog_id, "custom:v1")

    def test_build_create_surface(self):
        msg = self.builder.build_create_surface("s1")
        self.assertEqual(msg["version"], A2UI_VERSION)
        self.assertEqual(msg["createSurface"]["surfaceId"], "s1")
        self.assertEqual(msg["createSurface"]["catalogId"], OPENBENCH_CATALOG_ID)

    def test_build_create_surface_with_theme(self):
        msg = self.builder.build_create_surface(
            "s1",
            theme={"primaryColor": "#FF0000"},
        )
        self.assertEqual(msg["createSurface"]["theme"]["primaryColor"], "#FF0000")

    def test_build_update_components(self):
        components = [
            A2UIComponent(id="root", component="Column", properties={"children": ["t1"]}),
            A2UIComponent(id="t1", component="Text", properties={"text": "Hello"}),
        ]
        msg = self.builder.build_update_components("s1", components)
        self.assertEqual(msg["version"], A2UI_VERSION)
        self.assertEqual(msg["updateComponents"]["surfaceId"], "s1")
        self.assertEqual(len(msg["updateComponents"]["components"]), 2)

        # Verify flat component format
        text_comp = msg["updateComponents"]["components"][1]
        self.assertEqual(text_comp["id"], "t1")
        self.assertEqual(text_comp["component"], "Text")
        self.assertEqual(text_comp["text"], "Hello")
        self.assertNotIn("properties", text_comp)

    def test_build_update_data_model(self):
        msg = self.builder.build_update_data_model("s1", "/chart/data", [1, 2, 3])
        self.assertEqual(msg["version"], A2UI_VERSION)
        self.assertEqual(msg["updateDataModel"]["surfaceId"], "s1")
        self.assertEqual(msg["updateDataModel"]["path"], "/chart/data")
        self.assertEqual(msg["updateDataModel"]["value"], [1, 2, 3])

    def test_build_delete_surface(self):
        msg = self.builder.build_delete_surface("s1")
        self.assertEqual(msg["version"], A2UI_VERSION)
        self.assertEqual(msg["deleteSurface"]["surfaceId"], "s1")

    def test_build_surface_complete(self):
        """build_surface should produce createSurface + updateComponents + updateDataModel."""
        components = [
            A2UIComponent(id="root", component="Column", properties={"children": ["c1"]}),
            A2UIComponent(id="c1", component="ObChart", properties={"chartType": "bar"}),
        ]
        data_model = {"/chart/data": [{"name": "Q1", "value": 100}]}

        messages = self.builder.build_surface("s1", components, data_model=data_model)
        self.assertEqual(len(messages), 3)

        # Message 1: createSurface
        self.assertIn("createSurface", messages[0])
        self.assertEqual(messages[0]["createSurface"]["surfaceId"], "s1")

        # Message 2: updateComponents
        self.assertIn("updateComponents", messages[1])
        self.assertEqual(len(messages[1]["updateComponents"]["components"]), 2)

        # Message 3: updateDataModel
        self.assertIn("updateDataModel", messages[2])
        self.assertEqual(messages[2]["updateDataModel"]["path"], "/chart/data")

    def test_build_surface_without_data_model(self):
        components = [A2UIComponent(id="root", component="Text", properties={"text": "Hi"})]
        messages = self.builder.build_surface("s1", components)
        self.assertEqual(len(messages), 2)  # createSurface + updateComponents only

    def test_build_surface_multiple_data_paths(self):
        components = [A2UIComponent(id="root", component="Column")]
        data_model = {"/data/a": 1, "/data/b": 2}
        messages = self.builder.build_surface("s1", components, data_model=data_model)
        # createSurface + updateComponents + 2x updateDataModel
        self.assertEqual(len(messages), 4)

    def test_build_surface_validates_no_root(self):
        components = [A2UIComponent(id="t1", component="Text")]
        with self.assertRaises(ValueError) as ctx:
            self.builder.build_surface("s1", components)
        self.assertIn("root", str(ctx.exception))

    def test_build_surface_validates_empty(self):
        with self.assertRaises(ValueError):
            self.builder.build_surface("s1", [])

    def test_to_jsonl(self):
        messages = [
            {
                "version": "v0.10",
                "createSurface": {"surfaceId": "s1", "catalogId": "cat"},
            },
            {
                "version": "v0.10",
                "updateComponents": {"surfaceId": "s1", "components": []},
            },
        ]
        jsonl = self.builder.to_jsonl(messages)
        lines = jsonl.strip().split("\n")
        self.assertEqual(len(lines), 2)

        # Each line should be valid JSON
        for line in lines:
            parsed = json.loads(line)
            self.assertEqual(parsed["version"], "v0.10")

    def test_to_jsonl_empty(self):
        jsonl = self.builder.to_jsonl([])
        self.assertEqual(jsonl, "")

    def test_all_messages_have_version(self):
        """Every A2UI message must have version: v0.10."""
        components = [A2UIComponent(id="root", component="Text", properties={"text": "Hi"})]
        messages = self.builder.build_surface(
            "s1",
            components,
            data_model={"/x": 1},
        )
        messages.append(self.builder.build_delete_surface("s1"))

        for msg in messages:
            self.assertEqual(msg["version"], A2UI_VERSION, f"Missing version in {msg}")


if __name__ == "__main__":
    unittest.main()
