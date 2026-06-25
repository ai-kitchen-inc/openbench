"""Render a dashboard ViewModel to a PDF, charts included.

The standalone dashboard HTML produced by ``DashboardGenerator`` uses CSS grid
and inline SVG charts. To get a PDF that looks like the dashboard, we render
that HTML in headless Chromium (via Playwright) and use ``page.pdf()`` — the
same engine that renders the app, so layout and charts come through faithfully.

The PDF is forced to the light color scheme so charts render on a white page
regardless of the user's current UI theme.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from openbench.output.generators.dashboard import DashboardGenerator

# Module-level generator: stateless and cheap to reuse across requests.
_GENERATOR = DashboardGenerator()


async def render_dashboard_pdf(view_model: dict[str, Any]) -> bytes:
    """Render a dashboard ViewModel to PDF bytes (with charts).

    Args:
        view_model: The dashboard ViewModel to render.

    Returns:
        The generated PDF as raw bytes.

    Raises:
        ImportError: If Playwright (and its Chromium browser) is not installed.
    """
    # Imported lazily so importing this module never fails when the optional
    # Playwright dependency / browser is absent — the error surfaces only on use.
    from playwright.async_api import async_playwright

    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "dashboard.html"
        _GENERATOR.generate(content=view_model, output_path=str(html_path))

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(args=["--no-sandbox"])
            try:
                page = await browser.new_page()
                # White page + chart colors that read on white, whatever the UI theme.
                await page.emulate_media(color_scheme="light")
                await page.goto(html_path.as_uri(), wait_until="networkidle")
                return await page.pdf(
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
                await browser.close()
