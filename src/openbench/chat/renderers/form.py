"""
Form content renderer.

Converts form field definitions to A2UI input components
(TextField, CheckBox, ChoicePicker, Slider, DateTimeInput)
with data binding and validation checks.
"""

import uuid
from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry

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

    def detect(self, content: Any) -> bool:
        """Detect if content is a form definition."""
        if not isinstance(content, dict):
            return False
        fields = content.get("fields")
        return isinstance(fields, list) and len(fields) > 0

    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert form definition to A2UI input components."""
        fields = content["fields"]
        submit_label = content.get("submitLabel", "Submit")
        submit_action = content.get("submitAction", "submit_form")

        components: list[A2UIComponent] = []
        child_ids: list[str] = []

        for field_def in fields:
            field_components = self._render_field(field_def)
            for comp in field_components:
                components.append(comp)
                child_ids.append(comp.id)

        # Submit button
        btn_id = _gen_id("btn")
        context: dict[str, Any] = {}
        for field_def in fields:
            name = field_def["name"]
            context[name] = {"path": f"/form/{name}"}

        components.append(A2UIComponent(
            id=btn_id,
            component="Button",
            properties={
                "label": submit_label,
                "action": {
                    "event": {
                        "name": submit_action,
                        "context": context,
                    }
                },
            },
        ))
        child_ids.append(btn_id)

        return components

    def _render_field(self, field_def: dict[str, Any]) -> list[A2UIComponent]:
        """Render a single form field to A2UI components."""
        field_type = field_def.get("type", "text")
        name = field_def["name"]
        label = field_def.get("label", name)
        component_type = FIELD_TYPE_MAP.get(field_type, "TextField")
        data_path = f"/form/{name}"

        comp_id = _gen_id(f"field-{name}")
        props: dict[str, Any] = {"label": label}

        # Data binding for value
        props["value"] = {"path": data_path}

        # Type-specific properties
        if component_type == "TextField":
            if field_type == "email":
                props["inputType"] = "email"
            elif field_type == "number":
                props["inputType"] = "number"
            elif field_type == "password":
                props["inputType"] = "password"
            elif field_type == "textarea":
                props["multiline"] = True

        elif component_type == "ChoicePicker":
            options = field_def.get("options", [])
            props["options"] = options

        elif component_type == "Slider":
            if "min" in field_def:
                props["min"] = field_def["min"]
            if "max" in field_def:
                props["max"] = field_def["max"]
            if "step" in field_def:
                props["step"] = field_def["step"]

        elif component_type == "DateTimeInput":
            if field_type == "date":
                props["mode"] = "date"
            elif field_type == "time":
                props["mode"] = "time"
            else:
                props["mode"] = "datetime"

        # Validation checks
        checks = self._build_checks(field_def, data_path)
        if checks:
            props["checks"] = checks

        return [A2UIComponent(id=comp_id, component=component_type, properties=props)]

    def _build_checks(
        self, field_def: dict[str, Any], data_path: str
    ) -> list[dict[str, Any]]:
        """Build A2UI check rules from field constraints."""
        checks: list[dict[str, Any]] = []
        field_type = field_def.get("type", "text")

        if field_def.get("required"):
            checks.append({
                "condition": {
                    "call": "required",
                    "args": {"value": {"path": data_path}},
                },
                "message": f"{field_def.get('label', field_def['name'])} is required",
            })

        if field_type == "email":
            checks.append({
                "condition": {
                    "call": "email",
                    "args": {"value": {"path": data_path}},
                },
                "message": "Invalid email address",
            })

        if field_type == "number":
            min_val = field_def.get("min")
            max_val = field_def.get("max")
            if min_val is not None or max_val is not None:
                args: dict[str, Any] = {"value": {"path": data_path}}
                if min_val is not None:
                    args["min"] = min_val
                if max_val is not None:
                    args["max"] = max_val
                checks.append({
                    "condition": {"call": "numeric", "args": args},
                    "message": f"Must be a valid number"
                    + (f" (min: {min_val})" if min_val is not None else "")
                    + (f" (max: {max_val})" if max_val is not None else ""),
                })

        pattern = field_def.get("pattern")
        if pattern:
            checks.append({
                "condition": {
                    "call": "regex",
                    "args": {"value": {"path": data_path}, "pattern": pattern},
                },
                "message": field_def.get("patternMessage", f"Must match pattern: {pattern}"),
            })

        return checks


def _gen_id(prefix: str) -> str:
    """Generate a short unique ID with prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
