"""Tests for FormRenderer."""

import unittest

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRendererRegistry
from openbench.chat.renderers.form import FormRenderer


class TestFormRendererRegistry(unittest.TestCase):
    """Tests for FormRenderer registration."""

    def test_registered(self):
        plugins = ContentRendererRegistry.list_plugins()
        self.assertTrue(any("form" in p for p in plugins))

    def test_create(self):
        renderer = ContentRendererRegistry.create("form", "default")
        self.assertIsInstance(renderer, FormRenderer)


class TestFormRenderer(unittest.TestCase):
    """Tests for FormRenderer."""

    def setUp(self):
        self.renderer = FormRenderer()

    def test_content_type(self):
        self.assertEqual(self.renderer.content_type, "form")

    # -- detect --

    def test_detect_valid_form(self):
        self.assertTrue(self.renderer.detect({"fields": [{"name": "email"}]}))

    def test_detect_empty_fields(self):
        self.assertFalse(self.renderer.detect({"fields": []}))

    def test_detect_missing_fields(self):
        self.assertFalse(self.renderer.detect({"title": "Form"}))

    def test_detect_not_dict(self):
        self.assertFalse(self.renderer.detect("form"))
        self.assertFalse(self.renderer.detect(None))

    # -- render text fields --

    def test_render_text_field(self):
        content = {"fields": [{"name": "username", "type": "text", "label": "Username"}]}
        components = self.renderer.render(content, surface_id="s1")
        # Should have 1 field + 1 submit button
        self.assertEqual(len(components), 2)
        field = components[0]
        self.assertEqual(field.component, "TextField")
        self.assertEqual(field.properties["label"], "Username")
        self.assertEqual(field.properties["value"], {"path": "/form/username"})

    def test_render_email_field(self):
        content = {"fields": [{"name": "email", "type": "email", "label": "Email"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        self.assertEqual(field.component, "TextField")
        self.assertEqual(field.properties["inputType"], "email")

    def test_render_password_field(self):
        content = {"fields": [{"name": "pass", "type": "password", "label": "Password"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        self.assertEqual(field.properties["inputType"], "password")

    def test_render_number_field(self):
        content = {"fields": [{"name": "age", "type": "number", "label": "Age"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        self.assertEqual(field.properties["inputType"], "number")

    def test_render_textarea_field(self):
        content = {"fields": [{"name": "bio", "type": "textarea", "label": "Bio"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        self.assertEqual(field.component, "TextField")
        self.assertTrue(field.properties["multiline"])

    # -- render other field types --

    def test_render_checkbox(self):
        content = {"fields": [{"name": "agree", "type": "checkbox", "label": "I agree"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        self.assertEqual(field.component, "CheckBox")
        self.assertEqual(field.properties["label"], "I agree")

    def test_render_select(self):
        content = {
            "fields": [{
                "name": "role", "type": "select", "label": "Role",
                "options": ["Admin", "User", "Guest"],
            }]
        }
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        self.assertEqual(field.component, "ChoicePicker")
        self.assertEqual(field.properties["options"], ["Admin", "User", "Guest"])

    def test_render_slider(self):
        content = {
            "fields": [{
                "name": "volume", "type": "slider", "label": "Volume",
                "min": 0, "max": 100, "step": 5,
            }]
        }
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        self.assertEqual(field.component, "Slider")
        self.assertEqual(field.properties["min"], 0)
        self.assertEqual(field.properties["max"], 100)
        self.assertEqual(field.properties["step"], 5)

    def test_render_date_field(self):
        content = {"fields": [{"name": "dob", "type": "date", "label": "Date of Birth"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        self.assertEqual(field.component, "DateTimeInput")
        self.assertEqual(field.properties["mode"], "date")

    def test_render_datetime_field(self):
        content = {"fields": [{"name": "ts", "type": "datetime", "label": "Timestamp"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        self.assertEqual(field.component, "DateTimeInput")
        self.assertEqual(field.properties["mode"], "datetime")

    # -- submit button --

    def test_submit_button(self):
        content = {"fields": [{"name": "x", "type": "text", "label": "X"}]}
        components = self.renderer.render(content, surface_id="s1")
        button = components[-1]
        self.assertEqual(button.component, "Button")
        self.assertEqual(button.properties["label"], "Submit")
        action = button.properties["action"]
        self.assertEqual(action["event"]["name"], "submit_form")

    def test_custom_submit_label(self):
        content = {
            "fields": [{"name": "x"}],
            "submitLabel": "Save",
            "submitAction": "save_profile",
        }
        components = self.renderer.render(content, surface_id="s1")
        button = components[-1]
        self.assertEqual(button.properties["label"], "Save")
        self.assertEqual(button.properties["action"]["event"]["name"], "save_profile")

    def test_submit_context_has_data_bindings(self):
        content = {
            "fields": [
                {"name": "email", "type": "email"},
                {"name": "name", "type": "text"},
            ]
        }
        components = self.renderer.render(content, surface_id="s1")
        button = components[-1]
        context = button.properties["action"]["event"]["context"]
        self.assertEqual(context["email"], {"path": "/form/email"})
        self.assertEqual(context["name"], {"path": "/form/name"})

    # -- validation checks --

    def test_required_check(self):
        content = {"fields": [{"name": "email", "type": "text", "label": "Email", "required": True}]}
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        self.assertTrue(len(field.properties["checks"]) >= 1)
        check = field.properties["checks"][0]
        self.assertEqual(check["condition"]["call"], "required")
        self.assertIn("required", check["message"].lower())

    def test_email_check(self):
        content = {"fields": [{"name": "email", "type": "email", "label": "Email"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        checks = field.properties["checks"]
        email_checks = [c for c in checks if c["condition"]["call"] == "email"]
        self.assertEqual(len(email_checks), 1)

    def test_numeric_check_with_min_max(self):
        content = {"fields": [{"name": "age", "type": "number", "label": "Age", "min": 0, "max": 150}]}
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        numeric_checks = [c for c in field.properties["checks"] if c["condition"]["call"] == "numeric"]
        self.assertEqual(len(numeric_checks), 1)
        args = numeric_checks[0]["condition"]["args"]
        self.assertEqual(args["min"], 0)
        self.assertEqual(args["max"], 150)

    def test_regex_check(self):
        content = {
            "fields": [{
                "name": "zip", "type": "text", "label": "ZIP",
                "pattern": r"^\d{5}$", "patternMessage": "Must be 5 digits",
            }]
        }
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        regex_checks = [c for c in field.properties["checks"] if c["condition"]["call"] == "regex"]
        self.assertEqual(len(regex_checks), 1)
        self.assertEqual(regex_checks[0]["message"], "Must be 5 digits")

    def test_no_checks_when_no_constraints(self):
        content = {"fields": [{"name": "notes", "type": "text", "label": "Notes"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = components[0]
        self.assertNotIn("checks", field.properties)

    # -- multiple fields --

    def test_multiple_fields(self):
        content = {
            "fields": [
                {"name": "name", "type": "text", "label": "Name"},
                {"name": "email", "type": "email", "label": "Email"},
                {"name": "agree", "type": "checkbox", "label": "Agree"},
            ]
        }
        components = self.renderer.render(content, surface_id="s1")
        # 3 fields + 1 button
        self.assertEqual(len(components), 4)
        self.assertEqual(components[0].component, "TextField")
        self.assertEqual(components[1].component, "TextField")
        self.assertEqual(components[2].component, "CheckBox")
        self.assertEqual(components[3].component, "Button")

    def test_unique_ids(self):
        content = {
            "fields": [
                {"name": "a", "type": "text"},
                {"name": "b", "type": "email"},
                {"name": "c", "type": "checkbox"},
            ]
        }
        components = self.renderer.render(content, surface_id="s1")
        ids = [c.id for c in components]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
