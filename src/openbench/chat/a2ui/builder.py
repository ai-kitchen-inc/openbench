"""
A2UI v0.10 message builder.

Takes A2UIComponent definitions from content renderers and builds
A2UI v0.10 JSONL messages for streaming to clients.
"""

import json
import logging
from typing import Any

from openbench.chat.a2ui.catalog import OPENBENCH_CATALOG_ID
from openbench.chat.a2ui.schema import (
    A2UIComponent,
    CreateSurfaceMessage,
    DeleteSurfaceMessage,
    UpdateComponentsMessage,
    UpdateDataModelMessage,
    validate_components,
)

logger = logging.getLogger(__name__)


class A2UIMessageBuilder:
    """Builds A2UI v0.10 JSONL messages from component definitions.

    Usage:
        builder = A2UIMessageBuilder()
        messages = builder.build_surface("s1", components, data_model={"/chart": data})
        jsonl = builder.to_jsonl(messages)
    """

    def __init__(self, catalog_id: str = OPENBENCH_CATALOG_ID):
        self.catalog_id = catalog_id

    def build_surface(
        self,
        surface_id: str,
        components: list[A2UIComponent],
        data_model: dict[str, Any] | None = None,
        theme: dict[str, Any] | None = None,
        send_data_model: bool = False,
    ) -> list[dict[str, Any]]:
        """Build a complete surface: createSurface + updateComponents + optional updateDataModel.

        One component MUST have id="root" to serve as the tree root.

        Args:
            surface_id: Unique surface identifier.
            components: List of A2UI components (one must have id="root").
            data_model: Optional data model entries {path: value}.
            theme: Optional theme overrides (primaryColor, iconUrl, agentDisplayName).
            send_data_model: If True, client sends data model with actions.

        Returns:
            List of A2UI message dicts ready for JSONL serialization.

        Raises:
            ValueError: If components fail validation.
        """
        errors = validate_components(components)
        if errors:
            raise ValueError(f"Invalid components: {'; '.join(errors)}")

        messages: list[dict[str, Any]] = []

        # 1. createSurface
        messages.append(self.build_create_surface(surface_id, theme, send_data_model))

        # 2. updateComponents
        messages.append(self.build_update_components(surface_id, components))

        # 3. updateDataModel (one message per path)
        if data_model:
            for path, value in data_model.items():
                messages.append(self.build_update_data_model(surface_id, path, value))

        return messages

    def build_create_surface(
        self,
        surface_id: str,
        theme: dict[str, Any] | None = None,
        send_data_model: bool = False,
    ) -> dict[str, Any]:
        """Build a createSurface message."""
        return CreateSurfaceMessage(
            surface_id=surface_id,
            catalog_id=self.catalog_id,
            theme=theme,
            send_data_model=send_data_model,
        ).to_dict()

    def build_update_components(
        self,
        surface_id: str,
        components: list[A2UIComponent],
    ) -> dict[str, Any]:
        """Build an updateComponents message."""
        return UpdateComponentsMessage(
            surface_id=surface_id,
            components=components,
        ).to_dict()

    def build_update_data_model(
        self,
        surface_id: str,
        path: str | None = None,
        value: Any = None,
    ) -> dict[str, Any]:
        """Build an updateDataModel message."""
        return UpdateDataModelMessage(
            surface_id=surface_id,
            path=path,
            value=value,
        ).to_dict()

    def build_delete_surface(self, surface_id: str) -> dict[str, Any]:
        """Build a deleteSurface message."""
        return DeleteSurfaceMessage(surface_id=surface_id).to_dict()

    def to_jsonl(self, messages: list[dict[str, Any]]) -> str:
        """Serialize messages to JSONL string (one JSON object per line).

        Args:
            messages: List of A2UI message dicts.

        Returns:
            JSONL string with one JSON object per line.
        """
        lines = [json.dumps(msg, separators=(",", ":")) for msg in messages]
        return "\n".join(lines)
