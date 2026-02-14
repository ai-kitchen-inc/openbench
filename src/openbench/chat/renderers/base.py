"""
Content renderer abstract base and registry.

ContentRenderer converts agent output (text, chart data, form definitions, files)
into A2UI v0.10 component definitions. Uses the same PluginRegistry pattern as
DataSourceRegistry, AgentRegistry, etc.
"""

from abc import ABC, abstractmethod
from typing import Any

from openbench.chat.a2ui.schema import A2UIComponent
from openbench.core.registry import PluginRegistry


class ContentRenderer(ABC):
    """Abstract base for converting agent output to A2UI components.

    Each renderer handles one content type (text, chart, form, file).
    Renderers detect whether they can handle given content, then render
    it into A2UI component definitions.
    """

    @property
    @abstractmethod
    def content_type(self) -> str:
        """Content type this renderer handles: 'text', 'chart', 'form', 'file'."""

    @abstractmethod
    def detect(self, content: Any) -> bool:
        """Check if this renderer can handle the given content.

        Args:
            content: Raw content from agent output.

        Returns:
            True if this renderer can handle the content.
        """

    @abstractmethod
    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert content to A2UI component definitions.

        Args:
            content: Raw content from agent output.
            surface_id: The surface ID these components belong to.

        Returns:
            List of A2UIComponent objects forming the rendered output.
            At least one component should be suitable as (or contain) a root.
        """


# Registry using the same PluginRegistry pattern as the rest of OpenBench
ContentRendererRegistry = PluginRegistry[ContentRenderer]("content_renderer")
