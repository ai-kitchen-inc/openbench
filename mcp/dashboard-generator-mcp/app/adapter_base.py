"""Base dashboard adapter contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DashboardRenderResult:
    """Normalized artifact result returned by all dashboard adapters."""

    file_path: str
    size_bytes: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "size_bytes": self.size_bytes,
            **self.metadata,
        }


class BaseAdapter(ABC):
    """Abstract dashboard presentation adapter."""

    name = "base"

    def __init__(
        self,
        *,
        output_path: str | Path,
        public_url: str | None = None,
        dashboard_template: dict[str, Any] | None = None,
    ):
        self.output_path = Path(output_path)
        self.public_url = public_url
        self.dashboard_template = dashboard_template

    @abstractmethod
    def render(self, view_model: dict[str, Any]) -> DashboardRenderResult:
        """Render ``view_model`` into ``self.output_path``."""
        raise NotImplementedError
