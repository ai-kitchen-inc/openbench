"""Dashboard adapter registry.

Concrete adapter implementations live in separate modules so vendor-specific
code stays out of this registry and out of ``tools.py``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from .adapter_base import BaseAdapter, DashboardRenderResult
from .default_adapter import DefaultGeneratorAdapter
from .stitch_adapter import StitchAdapter


def create_dashboard_adapter(
    *,
    output_path: str | Path,
    public_url: str | None = None,
    adapter: Any | None = None,
    adapter_factory: Callable[..., Any] | None = None,
) -> Any:
    """Create the dashboard adapter selected by DI or environment."""
    if adapter_factory is not None:
        return adapter_factory(output_path=output_path, public_url=public_url)
    if adapter is not None:
        return _coerce_adapter(adapter, output_path=output_path, public_url=public_url)

    selected = (
        os.environ.get("DASHBOARD_RENDER_ADAPTER")
        or os.environ.get("OPENBENCH_DASHBOARD_RENDER_ADAPTER")
        or "auto"
    )
    return _adapter_from_name(selected, output_path=output_path, public_url=public_url)


def _coerce_adapter(adapter: Any, *, output_path: str | Path, public_url: str | None) -> Any:
    if isinstance(adapter, str):
        return _adapter_from_name(adapter, output_path=output_path, public_url=public_url)
    if isinstance(adapter, type) and issubclass(adapter, BaseAdapter):
        return adapter(output_path=output_path, public_url=public_url)
    if callable(adapter) and not hasattr(adapter, "render"):
        return adapter(output_path=output_path, public_url=public_url)
    return adapter


def _adapter_from_name(name: str, *, output_path: str | Path, public_url: str | None) -> BaseAdapter:
    normalized = str(name or "auto").strip().lower()
    if normalized in {"default", "local", "dashboard-generator", "dashboardgenerator"}:
        return DefaultGeneratorAdapter(output_path=output_path, public_url=public_url)
    if normalized in {"stitch", "google-stitch", "google_stitch"}:
        return StitchAdapter(output_path=output_path, public_url=public_url)
    if normalized == "auto":
        if os.environ.get("STITCH_API_KEY") or os.environ.get("GOOGLE_STITCH_API_KEY"):
            return StitchAdapter(output_path=output_path, public_url=public_url)
        return DefaultGeneratorAdapter(output_path=output_path, public_url=public_url)
    raise ValueError(f"Unknown dashboard adapter: {name!r}")


__all__ = [
    "BaseAdapter",
    "DashboardRenderResult",
    "DefaultGeneratorAdapter",
    "StitchAdapter",
    "create_dashboard_adapter",
]
