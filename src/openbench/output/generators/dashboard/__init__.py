"""Dashboard output generator.

This package was split out of the former single ``dashboard.py`` module. The
public surface is unchanged: ``from openbench.output.generators.dashboard import
DashboardGenerator`` keeps working via this re-export.
"""

from __future__ import annotations

from openbench.output.generators.dashboard.generator import DashboardGenerator

__all__ = ["DashboardGenerator"]
