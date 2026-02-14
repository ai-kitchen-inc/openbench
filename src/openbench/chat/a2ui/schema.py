"""
A2UI v0.10 message types and validation.

Defines the four A2UI message types matching the Google A2UI v0.10 specification:
- CreateSurfaceMessage: Initialize a new surface
- UpdateComponentsMessage: Add/replace components
- UpdateDataModelMessage: Update data at a JSON Pointer path
- DeleteSurfaceMessage: Remove a surface

Reference: https://github.com/google/A2UI -- specification/v0_10/
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

A2UI_VERSION = "v0.10"


@dataclass
class A2UIComponent:
    """A component in the A2UI adjacency list.

    Components are flat objects: {id, component, ...properties}.
    Properties are NOT nested inside a 'properties' dict.
    """

    id: str
    component: str  # "Text", "Column", "ObChart", etc.
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to A2UI format: {id, component, ...properties}."""
        result: dict[str, Any] = {"id": self.id, "component": self.component}
        result.update(self.properties)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> A2UIComponent:
        """Deserialize from A2UI format."""
        component_id = data["id"]
        component_type = data["component"]
        properties = {k: v for k, v in data.items() if k not in ("id", "component")}
        return cls(id=component_id, component=component_type, properties=properties)


@dataclass
class CreateSurfaceMessage:
    """createSurface -- initialize a new surface with surfaceId + catalogId."""

    surface_id: str
    catalog_id: str
    theme: dict[str, Any] | None = None
    send_data_model: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to A2UI v0.10 wire format."""
        create_surface: dict[str, Any] = {
            "surfaceId": self.surface_id,
            "catalogId": self.catalog_id,
        }
        if self.theme:
            create_surface["theme"] = self.theme
        if self.send_data_model:
            create_surface["sendDataModel"] = True
        return {"version": A2UI_VERSION, "createSurface": create_surface}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CreateSurfaceMessage:
        """Deserialize from A2UI v0.10 wire format."""
        cs = data["createSurface"]
        return cls(
            surface_id=cs["surfaceId"],
            catalog_id=cs["catalogId"],
            theme=cs.get("theme"),
            send_data_model=cs.get("sendDataModel", False),
        )


@dataclass
class UpdateComponentsMessage:
    """updateComponents -- add/replace components in a surface."""

    surface_id: str
    components: list[A2UIComponent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to A2UI v0.10 wire format."""
        return {
            "version": A2UI_VERSION,
            "updateComponents": {
                "surfaceId": self.surface_id,
                "components": [c.to_dict() for c in self.components],
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UpdateComponentsMessage:
        """Deserialize from A2UI v0.10 wire format."""
        uc = data["updateComponents"]
        components = [A2UIComponent.from_dict(c) for c in uc["components"]]
        return cls(surface_id=uc["surfaceId"], components=components)


@dataclass
class UpdateDataModelMessage:
    """updateDataModel -- update data at a JSON Pointer path within a surface."""

    surface_id: str
    path: str | None = None  # RFC 6901 JSON Pointer; None means "/"
    value: Any = None  # None means remove key at path

    def to_dict(self) -> dict[str, Any]:
        """Serialize to A2UI v0.10 wire format."""
        update: dict[str, Any] = {"surfaceId": self.surface_id}
        if self.path is not None:
            update["path"] = self.path
        if self.value is not None:
            update["value"] = self.value
        return {"version": A2UI_VERSION, "updateDataModel": update}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UpdateDataModelMessage:
        """Deserialize from A2UI v0.10 wire format."""
        udm = data["updateDataModel"]
        return cls(
            surface_id=udm["surfaceId"],
            path=udm.get("path"),
            value=udm.get("value"),
        )


@dataclass
class DeleteSurfaceMessage:
    """deleteSurface -- remove a surface and all its components/data."""

    surface_id: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to A2UI v0.10 wire format."""
        return {
            "version": A2UI_VERSION,
            "deleteSurface": {"surfaceId": self.surface_id},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeleteSurfaceMessage:
        """Deserialize from A2UI v0.10 wire format."""
        ds = data["deleteSurface"]
        return cls(surface_id=ds["surfaceId"])


# Union type for all A2UI messages
A2UIMessage = (
    CreateSurfaceMessage | UpdateComponentsMessage | UpdateDataModelMessage | DeleteSurfaceMessage
)


class StreamMessageType(Enum):
    """Wire format types for the streaming envelope (outside A2UI spec)."""

    STREAM_START = "stream_start"
    STREAM_END = "stream_end"
    STEP_START = "step_start"
    STEP_COMPLETE = "step_complete"
    ERROR = "error"


@dataclass
class StepStartMessage:
    """step_start -- signals the beginning of a processing step."""

    step_id: str
    step_name: str
    message_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to wire format (camelCase)."""
        result: dict[str, Any] = {
            "type": "step_start",
            "stepId": self.step_id,
            "stepName": self.step_name,
        }
        if self.message_id:
            result["messageId"] = self.message_id
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepStartMessage:
        """Deserialize from wire format."""
        return cls(
            step_id=data["stepId"],
            step_name=data["stepName"],
            message_id=data.get("messageId"),
        )


@dataclass
class StepCompleteMessage:
    """step_complete -- signals the end of a processing step."""

    step_id: str
    message_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to wire format (camelCase)."""
        result: dict[str, Any] = {
            "type": "step_complete",
            "stepId": self.step_id,
        }
        if self.message_id:
            result["messageId"] = self.message_id
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepCompleteMessage:
        """Deserialize from wire format."""
        return cls(
            step_id=data["stepId"],
            message_id=data.get("messageId"),
        )


@dataclass
class StreamMessage:
    """Envelope message for stream lifecycle (not part of A2UI spec itself)."""

    type: StreamMessageType
    message_id: str
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to wire format."""
        result: dict[str, Any] = {
            "type": self.type.value,
            "messageId": self.message_id,
        }
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StreamMessage:
        """Deserialize from wire format."""
        return cls(
            type=StreamMessageType(data["type"]),
            message_id=data["messageId"],
            metadata=data.get("metadata"),
        )


def parse_a2ui_message(data: dict[str, Any]) -> A2UIMessage:
    """Parse a raw dict into the appropriate A2UI message type.

    Args:
        data: Raw dict from JSON parsing.

    Returns:
        The parsed A2UI message.

    Raises:
        ValueError: If the message type is unknown or version is wrong.
    """
    version = data.get("version")
    if version != A2UI_VERSION:
        raise ValueError(f"Unsupported A2UI version: {version!r} (expected {A2UI_VERSION!r})")

    if "createSurface" in data:
        return CreateSurfaceMessage.from_dict(data)
    elif "updateComponents" in data:
        return UpdateComponentsMessage.from_dict(data)
    elif "updateDataModel" in data:
        return UpdateDataModelMessage.from_dict(data)
    elif "deleteSurface" in data:
        return DeleteSurfaceMessage.from_dict(data)
    else:
        raise ValueError(f"Unknown A2UI message type. Keys: {list(data.keys())}")


def validate_components(components: list[A2UIComponent]) -> list[str]:
    """Validate a list of A2UI components.

    Returns:
        List of validation error strings (empty if valid).
    """
    errors: list[str] = []

    if not components:
        errors.append("Components list is empty")
        return errors

    ids = [c.id for c in components]
    if "root" not in ids:
        errors.append("No component with id='root' found; one is required")

    seen: set[str] = set()
    for c in components:
        if c.id in seen:
            errors.append(f"Duplicate component id: {c.id!r}")
        seen.add(c.id)

        if not c.component:
            errors.append(f"Component {c.id!r} has empty component type")

    return errors
