"""Output Layer - Multi-Format Exports."""

# L2 Orchestrator (use this for workflow composition)
from openbench.core.layers import OutputLayer

# Output Generators
from openbench.output.generators import (
    AudioGenerator,
    DashboardGenerator,
    MarkdownGenerator,
    PDFGenerator,
    PowerPointGenerator,
)

# Output Factory (convenience class for generating outputs)
from openbench.output.layer import OutputFactory

__all__ = [
    # L2 Orchestrator
    "OutputLayer",
    # Factory
    "OutputFactory",
    # Generators
    "PDFGenerator",
    "PowerPointGenerator",
    "DashboardGenerator",
    "AudioGenerator",
    "MarkdownGenerator",
]
