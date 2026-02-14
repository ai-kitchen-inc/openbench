"""Tests for A2UI v0.10 schema types and validation."""

import unittest

from openbench.chat.a2ui.schema import (
    A2UI_VERSION,
    A2UIComponent,
    CreateSurfaceMessage,
    DeleteSurfaceMessage,
    StreamMessage,
    StreamMessageType,
    UpdateComponentsMessage,
    UpdateDataModelMessage,
    parse_a2ui_message,
    validate_components,
)


class TestA2UIComponent(unittest.TestCase):
    """Tests for A2UIComponent."""

    def test_to_dict_flat(self):
        """Properties should be flat on the object, not nested."""
        comp = A2UIComponent(
            id="greeting",
            component="Text",
            properties={"text": "Hello!", "variant": "h1"},
        )
        d = comp.to_dict()
        self.assertEqual(d["id"], "greeting")
        self.assertEqual(d["component"], "Text")
        self.assertEqual(d["text"], "Hello!")
        self.assertEqual(d["variant"], "h1")
        # Properties should NOT be nested
        self.assertNotIn("properties", d)

    def test_to_dict_with_children(self):
        comp = A2UIComponent(
            id="root",
            component="Column",
            properties={"children": ["t1", "t2"]},
        )
        d = comp.to_dict()
        self.assertEqual(d["children"], ["t1", "t2"])

    def test_to_dict_empty_properties(self):
        comp = A2UIComponent(id="divider", component="Divider")
        d = comp.to_dict()
        self.assertEqual(d, {"id": "divider", "component": "Divider"})

    def test_from_dict(self):
        data = {
            "id": "btn",
            "component": "Button",
            "label": "Click me",
            "variant": "primary",
        }
        comp = A2UIComponent.from_dict(data)
        self.assertEqual(comp.id, "btn")
        self.assertEqual(comp.component, "Button")
        self.assertEqual(comp.properties["label"], "Click me")
        self.assertEqual(comp.properties["variant"], "primary")

    def test_roundtrip(self):
        original = A2UIComponent(
            id="chart-1",
            component="ObChart",
            properties={"chartType": "bar", "data": [1, 2, 3], "height": "300px"},
        )
        restored = A2UIComponent.from_dict(original.to_dict())
        self.assertEqual(restored.id, original.id)
        self.assertEqual(restored.component, original.component)
        self.assertEqual(restored.properties, original.properties)


class TestCreateSurfaceMessage(unittest.TestCase):
    """Tests for CreateSurfaceMessage."""

    def test_to_dict(self):
        msg = CreateSurfaceMessage(surface_id="s1", catalog_id="openbench:v1")
        d = msg.to_dict()
        self.assertEqual(d["version"], A2UI_VERSION)
        self.assertEqual(d["createSurface"]["surfaceId"], "s1")
        self.assertEqual(d["createSurface"]["catalogId"], "openbench:v1")
        self.assertNotIn("theme", d["createSurface"])
        self.assertNotIn("sendDataModel", d["createSurface"])

    def test_to_dict_with_theme(self):
        msg = CreateSurfaceMessage(
            surface_id="s1",
            catalog_id="cat",
            theme={"primaryColor": "#FF0000"},
        )
        d = msg.to_dict()
        self.assertEqual(d["createSurface"]["theme"]["primaryColor"], "#FF0000")

    def test_to_dict_with_send_data_model(self):
        msg = CreateSurfaceMessage(surface_id="s1", catalog_id="cat", send_data_model=True)
        d = msg.to_dict()
        self.assertTrue(d["createSurface"]["sendDataModel"])

    def test_roundtrip(self):
        original = CreateSurfaceMessage(
            surface_id="s1",
            catalog_id="cat",
            theme={"primaryColor": "#00FF00"},
            send_data_model=True,
        )
        restored = CreateSurfaceMessage.from_dict(original.to_dict())
        self.assertEqual(restored.surface_id, original.surface_id)
        self.assertEqual(restored.catalog_id, original.catalog_id)
        self.assertEqual(restored.theme, original.theme)
        self.assertEqual(restored.send_data_model, original.send_data_model)


class TestUpdateComponentsMessage(unittest.TestCase):
    """Tests for UpdateComponentsMessage."""

    def test_to_dict(self):
        components = [
            A2UIComponent(id="root", component="Column", properties={"children": ["t1"]}),
            A2UIComponent(id="t1", component="Text", properties={"text": "Hello"}),
        ]
        msg = UpdateComponentsMessage(surface_id="s1", components=components)
        d = msg.to_dict()
        self.assertEqual(d["version"], A2UI_VERSION)
        self.assertEqual(d["updateComponents"]["surfaceId"], "s1")
        self.assertEqual(len(d["updateComponents"]["components"]), 2)
        # Verify flat format
        self.assertEqual(d["updateComponents"]["components"][1]["text"], "Hello")

    def test_roundtrip(self):
        components = [A2UIComponent(id="root", component="Text", properties={"text": "Hi"})]
        original = UpdateComponentsMessage(surface_id="s1", components=components)
        restored = UpdateComponentsMessage.from_dict(original.to_dict())
        self.assertEqual(restored.surface_id, "s1")
        self.assertEqual(len(restored.components), 1)
        self.assertEqual(restored.components[0].properties["text"], "Hi")


class TestUpdateDataModelMessage(unittest.TestCase):
    """Tests for UpdateDataModelMessage."""

    def test_to_dict(self):
        msg = UpdateDataModelMessage(
            surface_id="s1",
            path="/chart/data",
            value=[1, 2, 3],
        )
        d = msg.to_dict()
        self.assertEqual(d["version"], A2UI_VERSION)
        self.assertEqual(d["updateDataModel"]["surfaceId"], "s1")
        self.assertEqual(d["updateDataModel"]["path"], "/chart/data")
        self.assertEqual(d["updateDataModel"]["value"], [1, 2, 3])

    def test_to_dict_no_path(self):
        msg = UpdateDataModelMessage(surface_id="s1", value={"key": "val"})
        d = msg.to_dict()
        self.assertNotIn("path", d["updateDataModel"])

    def test_to_dict_remove(self):
        """Value=None means remove the key at path."""
        msg = UpdateDataModelMessage(surface_id="s1", path="/old/key")
        d = msg.to_dict()
        self.assertNotIn("value", d["updateDataModel"])

    def test_roundtrip(self):
        original = UpdateDataModelMessage(surface_id="s1", path="/data", value={"x": 1})
        restored = UpdateDataModelMessage.from_dict(original.to_dict())
        self.assertEqual(restored.surface_id, "s1")
        self.assertEqual(restored.path, "/data")
        self.assertEqual(restored.value, {"x": 1})


class TestDeleteSurfaceMessage(unittest.TestCase):
    """Tests for DeleteSurfaceMessage."""

    def test_to_dict(self):
        msg = DeleteSurfaceMessage(surface_id="s1")
        d = msg.to_dict()
        self.assertEqual(d["version"], A2UI_VERSION)
        self.assertEqual(d["deleteSurface"]["surfaceId"], "s1")

    def test_roundtrip(self):
        original = DeleteSurfaceMessage(surface_id="s-abc")
        restored = DeleteSurfaceMessage.from_dict(original.to_dict())
        self.assertEqual(restored.surface_id, "s-abc")


class TestParseA2UIMessage(unittest.TestCase):
    """Tests for parse_a2ui_message."""

    def test_parse_create_surface(self):
        data = {
            "version": "v0.10",
            "createSurface": {"surfaceId": "s1", "catalogId": "cat"},
        }
        msg = parse_a2ui_message(data)
        self.assertIsInstance(msg, CreateSurfaceMessage)
        self.assertEqual(msg.surface_id, "s1")

    def test_parse_update_components(self):
        data = {
            "version": "v0.10",
            "updateComponents": {
                "surfaceId": "s1",
                "components": [{"id": "root", "component": "Text", "text": "Hi"}],
            },
        }
        msg = parse_a2ui_message(data)
        self.assertIsInstance(msg, UpdateComponentsMessage)
        self.assertEqual(len(msg.components), 1)

    def test_parse_update_data_model(self):
        data = {
            "version": "v0.10",
            "updateDataModel": {"surfaceId": "s1", "path": "/x", "value": 42},
        }
        msg = parse_a2ui_message(data)
        self.assertIsInstance(msg, UpdateDataModelMessage)
        self.assertEqual(msg.value, 42)

    def test_parse_delete_surface(self):
        data = {"version": "v0.10", "deleteSurface": {"surfaceId": "s1"}}
        msg = parse_a2ui_message(data)
        self.assertIsInstance(msg, DeleteSurfaceMessage)

    def test_parse_wrong_version(self):
        data = {
            "version": "v0.9",
            "createSurface": {"surfaceId": "s1", "catalogId": "cat"},
        }
        with self.assertRaises(ValueError) as ctx:
            parse_a2ui_message(data)
        self.assertIn("v0.9", str(ctx.exception))

    def test_parse_unknown_type(self):
        data = {"version": "v0.10", "unknownType": {}}
        with self.assertRaises(ValueError):
            parse_a2ui_message(data)


class TestValidateComponents(unittest.TestCase):
    """Tests for validate_components."""

    def test_valid(self):
        components = [
            A2UIComponent(id="root", component="Column"),
            A2UIComponent(id="t1", component="Text"),
        ]
        errors = validate_components(components)
        self.assertEqual(errors, [])

    def test_empty(self):
        errors = validate_components([])
        self.assertTrue(any("empty" in e.lower() for e in errors))

    def test_no_root(self):
        components = [A2UIComponent(id="t1", component="Text")]
        errors = validate_components(components)
        self.assertTrue(any("root" in e for e in errors))

    def test_duplicate_ids(self):
        components = [
            A2UIComponent(id="root", component="Column"),
            A2UIComponent(id="t1", component="Text"),
            A2UIComponent(id="t1", component="Text"),
        ]
        errors = validate_components(components)
        self.assertTrue(any("Duplicate" in e for e in errors))

    def test_empty_component_type(self):
        components = [A2UIComponent(id="root", component="")]
        errors = validate_components(components)
        self.assertTrue(any("empty" in e.lower() for e in errors))


class TestStreamMessage(unittest.TestCase):
    """Tests for StreamMessage."""

    def test_stream_start(self):
        msg = StreamMessage(
            type=StreamMessageType.STREAM_START,
            message_id="msg-1",
        )
        d = msg.to_dict()
        self.assertEqual(d["type"], "stream_start")
        self.assertEqual(d["messageId"], "msg-1")

    def test_stream_end_with_metadata(self):
        msg = StreamMessage(
            type=StreamMessageType.STREAM_END,
            message_id="msg-1",
            metadata={"tokensUsed": 450, "model": "gemini-2.5-flash"},
        )
        d = msg.to_dict()
        self.assertEqual(d["metadata"]["tokensUsed"], 450)

    def test_roundtrip(self):
        original = StreamMessage(
            type=StreamMessageType.ERROR,
            message_id="msg-2",
            metadata={"error": "timeout"},
        )
        restored = StreamMessage.from_dict(original.to_dict())
        self.assertEqual(restored.type, StreamMessageType.ERROR)
        self.assertEqual(restored.message_id, "msg-2")
        self.assertEqual(restored.metadata["error"], "timeout")


if __name__ == "__main__":
    unittest.main()
