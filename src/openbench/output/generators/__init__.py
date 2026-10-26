"""Output format generators.

Provides concrete implementations of OutputGenerator for various formats:
- PDFGenerator: Generate PDF reports using ReportLab
- PowerPointGenerator: Generate PPTX presentations
- DashboardGenerator: Generate interactive dashboards
- AudioGenerator: Generate audio content from text
- MarkdownGenerator: Generate markdown files

Each generator lives in its own module; this package re-exports them so both
``from openbench.output.generators import PDFGenerator`` and
``from openbench.output import PDFGenerator`` keep working.
"""

from openbench.output.generators.audio import AudioGenerator
from openbench.output.generators.dashboard import DashboardGenerator
from openbench.output.generators.markdown import MarkdownGenerator
from openbench.output.generators.pdf import PDFGenerator
from openbench.output.generators.powerpoint import PowerPointGenerator

__all__ = [
    "PDFGenerator",
    "MarkdownGenerator",
    "PowerPointGenerator",
    "DashboardGenerator",
    "AudioGenerator",
]
