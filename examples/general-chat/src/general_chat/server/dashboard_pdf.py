"""Render a dashboard ViewModel to a PDF, charts included.

The standalone dashboard HTML produced by ``DashboardGenerator`` uses CSS grid
and inline SVG charts. To get a PDF that looks like the dashboard, we render
that HTML in headless Chromium (via Playwright) and use ``page.pdf()`` — the
same engine that renders the app, so layout and charts come through faithfully.

We use Playwright's **sync** API on a worker thread (``asyncio.to_thread``)
rather than the async API directly. The async API spawns Chromium with
``asyncio.create_subprocess_exec``, which raises ``NotImplementedError`` on
Windows when the server's running loop is a ``SelectorEventLoop`` (uvicorn's
default there). Running the sync API on a fresh thread sidesteps the server
loop entirely and works on Windows and Linux alike.

The PDF is forced to the light color scheme so charts render on a white page
regardless of the user's current UI theme.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from openbench.output.generators.dashboard import DashboardGenerator

# Module-level generator: stateless and cheap to reuse across requests.
_GENERATOR = DashboardGenerator()


def _render_sync(view_model: dict[str, Any]) -> bytes:
    """Blocking render — runs on a worker thread (no running asyncio loop)."""
    # Imported lazily so importing this module never fails when the optional
    # Playwright dependency / browser is absent — the error surfaces only on use.
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "dashboard.html"
        _GENERATOR.generate(content=view_model, output_path=str(html_path))

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=["--no-sandbox"])
            try:
                page = browser.new_page()
                # White page + chart colors that read on white, whatever the UI theme.
                page.emulate_media(color_scheme="light")
                page.goto(html_path.as_uri(), wait_until="networkidle")
                return page.pdf(
                    format="A4",
                    landscape=True,
                    print_background=True,
                    margin={
                        "top": "12mm",
                        "bottom": "12mm",
                        "left": "10mm",
                        "right": "10mm",
                    },
                )
            finally:
                browser.close()


async def render_dashboard_pdf(view_model: dict[str, Any]) -> bytes:
    """Render a dashboard ViewModel to PDF bytes (with charts).

    Args:
        view_model: The dashboard ViewModel to render.

    Returns:
        The generated PDF as raw bytes.

    Raises:
        ImportError: If Playwright (and its Chromium browser) is not installed.
    """
    return await asyncio.to_thread(_render_sync, view_model)
