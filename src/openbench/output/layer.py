"""
Output Layer - Factory and Helpers.

NOTE: For L2 workflow orchestration, use OutputLayer from openbench.core.layers.
This module provides factory functions for creating output generators.
"""

from typing import Any, Dict, List, Optional
from pathlib import Path


class OutputFactory:
    """
    Factory for creating output generators and exporting data.

    Provides convenient methods for generating outputs in various formats.
    For L2 workflow orchestration, use OutputLayer from core.layers.

    Examples:
        >>> # Export to PDF
        >>> OutputFactory.export(
        ...     result,
        ...     format="pdf",
        ...     template="corporate",
        ...     output="report.pdf"
        ... )
        >>>
        >>> # Generate slides
        >>> OutputFactory.slides(result, output="presentation.pptx")
    """

    @classmethod
    def export(
        cls,
        data: Any,
        format: str = "pdf",
        output: Optional[str] = None,
        template: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Export data to specified format.

        Args:
            data: Data to export (workflow result, DataFrame, dict, etc.)
            format: Output format (pdf, pptx, dashboard, audio, etc.)
            output: Output file path
            template: Template name to use
            **kwargs: Format-specific parameters

        Returns:
            Path to generated output file
        """
        from openbench.output.generators import (
            PDFGenerator,
            PowerPointGenerator,
            DashboardGenerator,
            AudioGenerator,
        )

        generators = {
            "pdf": PDFGenerator,
            "pptx": PowerPointGenerator,
            "slides": PowerPointGenerator,
            "dashboard": DashboardGenerator,
            "audio": AudioGenerator,
        }

        generator_class = generators.get(format)
        if generator_class:
            generator = generator_class(**kwargs)
            result = generator.generate(content=data, template=template)
            return result.file_path

        # Fallback for unknown formats
        output_path = output or f"outputs/export.{_get_extension(format)}"
        return output_path

    @classmethod
    def pdf(
        cls,
        data: Any,
        template: str = "default",
        output: Optional[str] = None,
        **kwargs
    ) -> str:
        """Generate a PDF report."""
        return cls.export(data, format="pdf", template=template, output=output, **kwargs)

    @classmethod
    def slides(
        cls,
        data: Any,
        template: str = "corporate",
        output: Optional[str] = None,
        **kwargs
    ) -> str:
        """Generate a slide presentation."""
        return cls.export(data, format="pptx", template=template, output=output, **kwargs)

    @classmethod
    def dashboard(
        cls,
        data: Any,
        framework: str = "streamlit",
        port: int = 8501,
        **kwargs
    ) -> str:
        """Generate an interactive dashboard."""
        return cls.export(data, format="dashboard", framework=framework, port=port, **kwargs)

    @classmethod
    def audio(
        cls,
        text: str,
        voice: str = "professional_male",
        output: Optional[str] = None,
        **kwargs
    ) -> str:
        """Generate audio from text (TTS)."""
        return cls.export(text, format="audio", voice=voice, output=output, **kwargs)

    @classmethod
    def batch(
        cls,
        data: Any,
        formats: List[str],
        output_dir: str = "outputs",
        **kwargs
    ) -> Dict[str, str]:
        """
        Export to multiple formats simultaneously.

        Args:
            data: Data to export
            formats: List of output formats
            output_dir: Output directory
            **kwargs: Additional export parameters

        Returns:
            Dictionary mapping format to output path
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        results = {}
        for fmt in formats:
            output_path = f"{output_dir}/export.{_get_extension(fmt)}"
            results[fmt] = cls.export(data, format=fmt, output=output_path, **kwargs)

        return results


def _get_extension(format: str) -> str:
    """Get file extension for format."""
    extensions = {
        "pdf": "pdf",
        "pptx": "pptx",
        "slides": "pptx",
        "word": "docx",
        "excel": "xlsx",
        "audio": "mp3",
        "video": "mp4",
        "dashboard": "html",
        "infographic": "pdf",
    }
    return extensions.get(format, "pdf")
