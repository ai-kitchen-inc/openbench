"""
Form content renderer.

Converts form field definitions to A2UI input components
(TextField, CheckBox, ChoicePicker, Slider, DateTimeInput)
with data binding and validation checks.
"""

from __future__ import annotations

from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry, gen_id

# Maps form field types to A2UI component types
FIELD_TYPE_MAP = {
    "text": "TextField",
    "email": "TextField",
    "password": "TextField",
    "number": "TextField",
    "textarea": "TextField",
    "date": "DateTimeInput",
    "datetime": "DateTimeInput",
    "time": "DateTimeInput",
    "checkbox": "CheckBox",
    "select": "ChoicePicker",
    "choice": "ChoicePicker",
    "slider": "Slider",
    "range": "Slider",
}


@ContentRendererRegistry.register("form", "default", description="Dynamic form renderer")
class FormRenderer(ContentRenderer):
    """Renders form definitions to A2UI input components with data binding.

    Expected input format:
        {
            "fields": [
                {"name": "email", "type": "email", "label": "Email", "required": True},
                {"name": "age", "type": "number", "label": "Age", "min": 0, "max": 150},
                {"name": "agree", "type": "checkbox", "label": "I agree"},
                {"name": "role", "type": "select", "label": "Role",
                 "options": ["Admin", "User", "Guest"]},
            ],
            "submitLabel": "Submit",
            "submitAction": "submit_form"
        }

    Each field generates:
    - An input component with data binding to /form/<field_name>
    - Validation checks based on field constraints (required, email, etc.)
    """

    @property
    def content_type(self) -> str:
        return "form"

    def get_data_model(self, content: Any) -> dict[str, Any] | None:
        """Return initial data model values for form fields."""
        if not isinstance(content, dict):
            return None
        fields = content.get("fields")
        if not isinstance(fields, list) or not fields:
            return None
        data: dict[str, Any] = {}
        for f in fields:
            if not isinstance(f, dict) or "name" not in f:
                continue
            name = f["name"]
            ftype = f.get("type", "text")
            path = f"/form/{name}"
            if ftype == "checkbox":
                data[path] = f.get("default", False)
            elif ftype in ("slider", "range"):
                data[path] = f.get("default", f.get("min", 0))
            else:
                data[path] = f.get("default", "")
        return data if data else None

    def detect(self, content: Any) -> bool:
        """Detect if content is a form definition."""
        if not isinstance(content, dict):
            return False
        fields = content.get("fields")
        return isinstance(fields, list) and len(fields) > 0

    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert form definition to A2UI input components.

        Wraps all fields in a Card → Column structure with optional title.
        """
        fields = content["fields"]
        title = content.get("title", "")
        submit_label = content.get("submitLabel", "Submit")
        submit_action = content.get("submitAction", "submit_form")

        components: list[A2UIComponent] = []
        col_child_ids: list[str] = []

        # Form title
        if title:
            title_id = gen_id("form-title")
            components.append(
                A2UIComponent(
                    id=title_id,
                    component="Text",
                    properties={"text": title, "variant": "h4"},
                )
            )
            col_child_ids.append(title_id)

            # Divider after title
            divider_id = gen_id("form-divider")
            components.append(
                A2UIComponent(
                    id=divider_id,
                    component="Divider",
                    properties={},
                )
            )
            col_child_ids.append(divider_id)

        # Render fields
        for field_def in fields:
            field_components = self._render_field(field_def)
            for comp in field_components:
                components.append(comp)
                col_child_ids.append(comp.id)

        # Submit button (full-width)
        btn_id = gen_id("btn")
        context: dict[str, Any] = {}
        for field_def in fields:
            name = field_def["name"]
            context[name] = {"path": f"/form/{name}"}

        components.append(
            A2UIComponent(
                id=btn_id,
                component="Button",
                properties={
                    "label": submit_label,
                    "fullWidth": True,
                    "action": {
                        "event": {
                            "name": submit_action,
                            "context": context,
                        }
                    },
                },
            )
        )
        col_child_ids.append(btn_id)

        # Wrap in Column
        col_id = gen_id("form-col")
        components.append(
            A2UIComponent(
                id=col_id,
                component="Column",
                properties={"children": col_child_ids, "gap": "16px"},
            )
        )

        # Wrap in Card
        card_id = gen_id("form-card")
        components.append(
            A2UIComponent(
                id=card_id,
                component="Card",
                properties={"children": [col_id], "elevation": 0, "padding": "24px"},
            )
        )

        return components

    def _render_field(self, field_def: dict[str, Any]) -> list[A2UIComponent]:
        """Render a single form field to A2UI components."""
        field_type = field_def.get("type", "text")
        name = field_def["name"]
        label = field_def.get("label", name)
        component_type = FIELD_TYPE_MAP.get(field_type, "TextField")
        data_path = f"/form/{name}"

        comp_id = gen_id(f"field-{name}")
        props: dict[str, Any] = {"label": label}

        # Required indicator as separate prop (frontend renders red *)
        if field_def.get("required"):
            props["required"] = True

        # Data binding for value
        props["value"] = {"path": data_path}

        # Placeholder support
        if "placeholder" in field_def:
            props["placeholder"] = field_def["placeholder"]

        # Type-specific properties
        if component_type == "TextField":
            if field_type == "email":
                props["inputType"] = "email"
            elif field_type == "number":
                props["inputType"] = "number"
            elif field_type == "password":
                props["inputType"] = "password"
            elif field_type == "textarea":
                props["inputType"] = "textarea"

        elif component_type == "CheckBox":
            # CheckBox uses "checked" for data binding, not "value"
            props.pop("value", None)
            props["checked"] = {"path": data_path}

        elif component_type == "ChoicePicker":
            # Frontend expects [{label, value}] objects, not plain strings
            raw_options = field_def.get("options", [])
            props["options"] = [
                {"label": opt, "value": opt} if isinstance(opt, str) else opt for opt in raw_options
            ]

        elif component_type == "Slider":
            if "min" in field_def:
                props["min"] = field_def["min"]
            if "max" in field_def:
                props["max"] = field_def["max"]
            if "step" in field_def:
                props["step"] = field_def["step"]

        elif component_type == "DateTimeInput":
            # Frontend reads "inputType", not "mode"
            if field_type == "date":
                props["inputType"] = "date"
            elif field_type == "time":
                props["inputType"] = "time"
            else:
                props["inputType"] = "datetime"

        # Validation checks
        checks = self._build_checks(field_def, data_path)
        if checks:
            props["checks"] = checks

        result = [A2UIComponent(id=comp_id, component=component_type, properties=props)]

        # Description/help text
        description = field_def.get("description")
        if description:
            desc_id = gen_id(f"desc-{name}")
            result.append(
                A2UIComponent(
                    id=desc_id,
                    component="Text",
                    properties={"text": description, "variant": "caption"},
                )
            )

        return result

    def _build_checks(self, field_def: dict[str, Any], data_path: str) -> list[dict[str, Any]]:
        """Build A2UI check rules from field constraints."""
        checks: list[dict[str, Any]] = []
        field_type = field_def.get("type", "text")

        if field_def.get("required"):
            checks.append(
                {
                    "condition": {
                        "call": "required",
                        "args": {"value": {"path": data_path}},
                    },
                    "message": f"{field_def.get('label', field_def['name'])} is required",
                }
            )

        if field_type == "email":
            checks.append(
                {
                    "condition": {
                        "call": "email",
                        "args": {"value": {"path": data_path}},
                    },
                    "message": "Invalid email address",
                }
            )

        if field_type == "number":
            min_val = field_def.get("min")
            max_val = field_def.get("max")
            if min_val is not None or max_val is not None:
                args: dict[str, Any] = {"value": {"path": data_path}}
                if min_val is not None:
                    args["min"] = min_val
                if max_val is not None:
                    args["max"] = max_val
                checks.append(
                    {
                        "condition": {"call": "numeric", "args": args},
                        "message": "Must be a valid number"
                        + (f" (min: {min_val})" if min_val is not None else "")
                        + (f" (max: {max_val})" if max_val is not None else ""),
                    }
                )

        pattern = field_def.get("pattern")
        if pattern:
            checks.append(
                {
                    "condition": {
                        "call": "regex",
                        "args": {"value": {"path": data_path}, "pattern": pattern},
                    },
                    "message": field_def.get("patternMessage", f"Must match pattern: {pattern}"),
                }
            )

        return checks
