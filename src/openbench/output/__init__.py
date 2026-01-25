"""Output Layer - Multi-Format Exports."""

# L2 Orchestrator (use this for workflow composition)
from openbench.core.layers import OutputLayer

# Output Factory (convenience class for generating outputs)
from openbench.output.layer import OutputFactory

# Output Generators
from openbench.output.generators import (
    PDFGenerator,
    PowerPointGenerator,
    DashboardGenerator,
    AudioGenerator,
)

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
]
