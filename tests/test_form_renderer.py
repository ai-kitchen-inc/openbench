"""Tests for FormRenderer."""

import unittest

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRendererRegistry
from openbench.chat.renderers.form import FormRenderer


def _find_by_type(components: list[A2UIComponent], comp_type: str) -> list[A2UIComponent]:
    """Find all components of a given type."""
    return [c for c in components if c.component == comp_type]


def _find_one(components: list[A2UIComponent], comp_type: str) -> A2UIComponent:
    """Find first component of a given type."""
    matches = _find_by_type(components, comp_type)
    assert matches, f"No {comp_type} found in {[c.component for c in components]}"
    return matches[0]


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

    # -- Card + Column wrapper --

    def test_card_wrapper(self):
        content = {"fields": [{"name": "x", "type": "text"}]}
        components = self.renderer.render(content, surface_id="s1")
        cards = _find_by_type(components, "Card")
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card.properties["elevation"], 0)
        self.assertEqual(card.properties["padding"], "24px")

    def test_column_wrapper(self):
        content = {"fields": [{"name": "x", "type": "text"}]}
        components = self.renderer.render(content, surface_id="s1")
        columns = _find_by_type(components, "Column")
        self.assertEqual(len(columns), 1)
        col = columns[0]
        self.assertEqual(col.properties["gap"], "16px")

    def test_card_contains_column(self):
        content = {"fields": [{"name": "x", "type": "text"}]}
        components = self.renderer.render(content, surface_id="s1")
        card = _find_one(components, "Card")
        col = _find_one(components, "Column")
        self.assertIn(col.id, card.properties["children"])

    def test_column_contains_field_and_button(self):
        content = {"fields": [{"name": "x", "type": "text"}]}
        components = self.renderer.render(content, surface_id="s1")
        col = _find_one(components, "Column")
        field = _find_one(components, "TextField")
        button = _find_one(components, "Button")
        self.assertIn(field.id, col.properties["children"])
        self.assertIn(button.id, col.properties["children"])

    # -- form title --

    def test_title(self):
        content = {"fields": [{"name": "x"}], "title": "User Profile"}
        components = self.renderer.render(content, surface_id="s1")
        titles = [
            c for c in components if c.component == "Text" and c.properties.get("variant") == "h4"
        ]
        self.assertEqual(len(titles), 1)
        self.assertEqual(titles[0].properties["text"], "User Profile")

    def test_title_with_divider(self):
        content = {"fields": [{"name": "x"}], "title": "Settings"}
        components = self.renderer.render(content, surface_id="s1")
        dividers = _find_by_type(components, "Divider")
        self.assertEqual(len(dividers), 1)

    def test_no_title(self):
        content = {"fields": [{"name": "x"}]}
        components = self.renderer.render(content, surface_id="s1")
        titles = [
            c for c in components if c.component == "Text" and c.properties.get("variant") == "h4"
        ]
        self.assertEqual(len(titles), 0)
        dividers = _find_by_type(components, "Divider")
        self.assertEqual(len(dividers), 0)

    # -- render text fields --

    def test_render_text_field(self):
        content = {"fields": [{"name": "username", "type": "text", "label": "Username"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
        self.assertEqual(field.properties["label"], "Username")
        self.assertEqual(field.properties["value"], {"path": "/form/username"})

    def test_render_email_field(self):
        content = {"fields": [{"name": "email", "type": "email", "label": "Email"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
        self.assertEqual(field.properties["inputType"], "email")

    def test_render_password_field(self):
        content = {"fields": [{"name": "pass", "type": "password", "label": "Password"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
        self.assertEqual(field.properties["inputType"], "password")

    def test_render_number_field(self):
        content = {"fields": [{"name": "age", "type": "number", "label": "Age"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
        self.assertEqual(field.properties["inputType"], "number")

    def test_render_textarea_field(self):
        content = {"fields": [{"name": "bio", "type": "textarea", "label": "Bio"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
        self.assertEqual(field.properties["inputType"], "textarea")

    # -- render other field types --

    def test_render_checkbox(self):
        content = {"fields": [{"name": "agree", "type": "checkbox", "label": "I agree"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "CheckBox")
        self.assertEqual(field.properties["label"], "I agree")
        # CheckBox uses "checked" for data binding, not "value"
        self.assertEqual(field.properties["checked"], {"path": "/form/agree"})
        self.assertNotIn("value", field.properties)

    def test_render_select(self):
        content = {
            "fields": [
                {
                    "name": "role",
                    "type": "select",
                    "label": "Role",
                    "options": ["Admin", "User", "Guest"],
                }
            ]
        }
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "ChoicePicker")
        # Options are converted to {label, value} objects for frontend
        expected = [
            {"label": "Admin", "value": "Admin"},
            {"label": "User", "value": "User"},
            {"label": "Guest", "value": "Guest"},
        ]
        self.assertEqual(field.properties["options"], expected)

    def test_render_slider(self):
        content = {
            "fields": [
                {
                    "name": "volume",
                    "type": "slider",
                    "label": "Volume",
                    "min": 0,
                    "max": 100,
                    "step": 5,
                }
            ]
        }
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "Slider")
        self.assertEqual(field.properties["min"], 0)
        self.assertEqual(field.properties["max"], 100)
        self.assertEqual(field.properties["step"], 5)

    def test_render_date_field(self):
        content = {"fields": [{"name": "dob", "type": "date", "label": "Date of Birth"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "DateTimeInput")
        self.assertEqual(field.properties["inputType"], "date")

    def test_render_datetime_field(self):
        content = {"fields": [{"name": "ts", "type": "datetime", "label": "Timestamp"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "DateTimeInput")
        self.assertEqual(field.properties["inputType"], "datetime")

    def test_render_time_field(self):
        content = {"fields": [{"name": "alarm", "type": "time", "label": "Alarm Time"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "DateTimeInput")
        self.assertEqual(field.properties["inputType"], "time")

    # -- required indicator --

    def test_required_prop(self):
        content = {
            "fields": [{"name": "email", "type": "email", "label": "Email", "required": True}]
        }
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
        self.assertEqual(field.properties["label"], "Email")
        self.assertTrue(field.properties["required"])

    def test_not_required_no_prop(self):
        content = {"fields": [{"name": "email", "type": "email", "label": "Email"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
        self.assertEqual(field.properties["label"], "Email")
        self.assertNotIn("required", field.properties)

    # -- placeholder --

    def test_placeholder(self):
        content = {
            "fields": [{"name": "email", "type": "email", "placeholder": "user@example.com"}]
        }
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
        self.assertEqual(field.properties["placeholder"], "user@example.com")

    def test_no_placeholder(self):
        content = {"fields": [{"name": "email", "type": "email"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
        self.assertNotIn("placeholder", field.properties)

    # -- description --

    def test_description(self):
        content = {
            "fields": [
                {
                    "name": "email",
                    "type": "email",
                    "label": "Email",
                    "description": "Your work email",
                }
            ]
        }
        components = self.renderer.render(content, surface_id="s1")
        captions = [
            c
            for c in components
            if c.component == "Text" and c.properties.get("variant") == "caption"
        ]
        self.assertEqual(len(captions), 1)
        self.assertEqual(captions[0].properties["text"], "Your work email")

    def test_no_description(self):
        content = {"fields": [{"name": "email", "type": "email"}]}
        components = self.renderer.render(content, surface_id="s1")
        captions = [
            c
            for c in components
            if c.component == "Text" and c.properties.get("variant") == "caption"
        ]
        self.assertEqual(len(captions), 0)

    # -- submit button --

    def test_submit_button(self):
        content = {"fields": [{"name": "x", "type": "text", "label": "X"}]}
        components = self.renderer.render(content, surface_id="s1")
        button = _find_one(components, "Button")
        self.assertEqual(button.properties["label"], "Submit")
        action = button.properties["action"]
        self.assertEqual(action["event"]["name"], "submit_form")

    def test_submit_button_full_width(self):
        content = {"fields": [{"name": "x"}]}
        components = self.renderer.render(content, surface_id="s1")
        button = _find_one(components, "Button")
        self.assertTrue(button.properties["fullWidth"])

    def test_custom_submit_label(self):
        content = {
            "fields": [{"name": "x"}],
            "submitLabel": "Save",
            "submitAction": "save_profile",
        }
        components = self.renderer.render(content, surface_id="s1")
        button = _find_one(components, "Button")
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
        button = _find_one(components, "Button")
        context = button.properties["action"]["event"]["context"]
        self.assertEqual(context["email"], {"path": "/form/email"})
        self.assertEqual(context["name"], {"path": "/form/name"})

    # -- validation checks --

    def test_required_check(self):
        content = {
            "fields": [{"name": "email", "type": "text", "label": "Email", "required": True}]
        }
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
        self.assertTrue(len(field.properties["checks"]) >= 1)
        check = field.properties["checks"][0]
        self.assertEqual(check["condition"]["call"], "required")
        self.assertIn("required", check["message"].lower())

    def test_email_check(self):
        content = {"fields": [{"name": "email", "type": "email", "label": "Email"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
        checks = field.properties["checks"]
        email_checks = [c for c in checks if c["condition"]["call"] == "email"]
        self.assertEqual(len(email_checks), 1)

    def test_numeric_check_with_min_max(self):
        content = {
            "fields": [{"name": "age", "type": "number", "label": "Age", "min": 0, "max": 150}]
        }
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
        numeric_checks = [
            c for c in field.properties["checks"] if c["condition"]["call"] == "numeric"
        ]
        self.assertEqual(len(numeric_checks), 1)
        args = numeric_checks[0]["condition"]["args"]
        self.assertEqual(args["min"], 0)
        self.assertEqual(args["max"], 150)

    def test_regex_check(self):
        content = {
            "fields": [
                {
                    "name": "zip",
                    "type": "text",
                    "label": "ZIP",
                    "pattern": r"^\d{5}$",
                    "patternMessage": "Must be 5 digits",
                }
            ]
        }
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
        regex_checks = [c for c in field.properties["checks"] if c["condition"]["call"] == "regex"]
        self.assertEqual(len(regex_checks), 1)
        self.assertEqual(regex_checks[0]["message"], "Must be 5 digits")

    def test_no_checks_when_no_constraints(self):
        content = {"fields": [{"name": "notes", "type": "text", "label": "Notes"}]}
        components = self.renderer.render(content, surface_id="s1")
        field = _find_one(components, "TextField")
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
        # 3 fields + 1 button + 1 Column + 1 Card = 6
        self.assertEqual(len(components), 6)
        self.assertEqual(len(_find_by_type(components, "TextField")), 2)
        self.assertEqual(len(_find_by_type(components, "CheckBox")), 1)
        self.assertEqual(len(_find_by_type(components, "Button")), 1)
        self.assertEqual(len(_find_by_type(components, "Column")), 1)
        self.assertEqual(len(_find_by_type(components, "Card")), 1)

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


class TestFormRendererDataModel(unittest.TestCase):
    """Tests for FormRenderer.get_data_model()."""

    def setUp(self):
        self.renderer = FormRenderer()

    def test_text_field_default_empty(self):
        content = {"fields": [{"name": "email", "type": "email"}]}
        dm = self.renderer.get_data_model(content)
        self.assertIsNotNone(dm)
        self.assertEqual(dm["/form/email"], "")

    def test_checkbox_default_false(self):
        content = {"fields": [{"name": "agree", "type": "checkbox"}]}
        dm = self.renderer.get_data_model(content)
        self.assertIsNotNone(dm)
        self.assertEqual(dm["/form/agree"], False)

    def test_slider_default_min(self):
        content = {"fields": [{"name": "vol", "type": "slider", "min": 10}]}
        dm = self.renderer.get_data_model(content)
        self.assertIsNotNone(dm)
        self.assertEqual(dm["/form/vol"], 10)

    def test_slider_default_zero_no_min(self):
        content = {"fields": [{"name": "val", "type": "slider"}]}
        dm = self.renderer.get_data_model(content)
        self.assertIsNotNone(dm)
        self.assertEqual(dm["/form/val"], 0)

    def test_custom_default_values(self):
        content = {
            "fields": [
                {"name": "name", "type": "text", "default": "John"},
                {"name": "agree", "type": "checkbox", "default": True},
                {"name": "vol", "type": "slider", "default": 50},
            ]
        }
        dm = self.renderer.get_data_model(content)
        self.assertIsNotNone(dm)
        self.assertEqual(dm["/form/name"], "John")
        self.assertEqual(dm["/form/agree"], True)
        self.assertEqual(dm["/form/vol"], 50)

    def test_multiple_fields(self):
        content = {
            "fields": [
                {"name": "email", "type": "email"},
                {"name": "name", "type": "text"},
                {"name": "agree", "type": "checkbox"},
            ]
        }
        dm = self.renderer.get_data_model(content)
        self.assertIsNotNone(dm)
        self.assertEqual(len(dm), 3)
        self.assertIn("/form/email", dm)
        self.assertIn("/form/name", dm)
        self.assertIn("/form/agree", dm)

    def test_returns_none_for_non_dict(self):
        self.assertIsNone(self.renderer.get_data_model("not a dict"))

    def test_returns_none_for_empty_fields(self):
        self.assertIsNone(self.renderer.get_data_model({"fields": []}))

    def test_returns_none_for_no_fields(self):
        self.assertIsNone(self.renderer.get_data_model({"title": "form"}))

    def test_range_type_uses_slider_default(self):
        content = {"fields": [{"name": "x", "type": "range", "min": 5}]}
        dm = self.renderer.get_data_model(content)
        self.assertIsNotNone(dm)
        self.assertEqual(dm["/form/x"], 5)


if __name__ == "__main__":
    unittest.main()
