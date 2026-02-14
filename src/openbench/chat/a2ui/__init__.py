"""
A2UI v0.10 message types, builder, and catalog.

Public API:
    from openbench.chat.a2ui import A2UIMessageBuilder, A2UIComponent
    from openbench.chat.a2ui import OPENBENCH_CATALOG_ID
"""

from openbench.chat.a2ui.builder import A2UIMessageBuilder
from openbench.chat.a2ui.catalog import (
    ALL_COMPONENT_TYPES,
    OPENBENCH_CATALOG,
    OPENBENCH_CATALOG_ID,
    STANDARD_COMPONENTS,
    STANDARD_FUNCTIONS,
    is_custom_component,
    is_known_component,
    is_standard_component,
)
from openbench.chat.a2ui.schema import (
    A2UI_VERSION,
    A2UIComponent,
    A2UIMessage,
    CreateSurfaceMessage,
    DeleteSurfaceMessage,
    StepCompleteMessage,
    StepStartMessage,
    StreamMessage,
    StreamMessageType,
    UpdateComponentsMessage,
    UpdateDataModelMessage,
    parse_a2ui_message,
    validate_components,
)

__all__ = [
    # Builder
    "A2UIMessageBuilder",
    # Schema
    "A2UI_VERSION",
    "A2UIComponent",
    "A2UIMessage",
    "CreateSurfaceMessage",
    "UpdateComponentsMessage",
    "UpdateDataModelMessage",
    "DeleteSurfaceMessage",
    "StepStartMessage",
    "StepCompleteMessage",
    "StreamMessage",
    "StreamMessageType",
    "parse_a2ui_message",
    "validate_components",
    # Catalog
    "OPENBENCH_CATALOG_ID",
    "OPENBENCH_CATALOG",
    "STANDARD_COMPONENTS",
    "STANDARD_FUNCTIONS",
    "ALL_COMPONENT_TYPES",
    "is_standard_component",
    "is_custom_component",
    "is_known_component",
]
