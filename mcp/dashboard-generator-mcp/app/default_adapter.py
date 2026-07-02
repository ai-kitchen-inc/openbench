"""Built-in OpenBench dashboard rendering adapter."""

from __future__ import annotations

from typing import Any

from .adapter_base import BaseAdapter, DashboardRenderResult


class DefaultGeneratorAdapter(BaseAdapter):
    """Adapter for OpenBench's built-in ``DashboardGenerator``."""

    name = "default"

    def render(self, view_model: dict[str, Any]) -> DashboardRenderResult:
        from openbench.output.generators import DashboardGenerator

        generator = DashboardGenerator()
        result = generator.generate(
            view_model,
            output_path=str(self.output_path),
            public_url=self.public_url,
        )
        return DashboardRenderResult(
            file_path=result.file_path,
            size_bytes=result.size_bytes,
            metadata={
                **result.metadata,
                "adapter": {"name": self.name, "used": True},
                "stitch": {"configured": False, "used": False},
            },
        )
