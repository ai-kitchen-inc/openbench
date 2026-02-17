"""
Output Layer - Factory and Helpers.

NOTE: For L2 workflow orchestration, use OutputLayer from openbench.core.layers.
This module provides factory functions for creating output generators.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openbench.core.abstractions import GeneratedOutput


class OutputFactory:
    """
    Factory for creating output generators and exporting data.

    Provides convenient methods for generating outputs in various formats.
    For L2 workflow orchestration, use OutputLayer from core.layers.

    Examples:
        >>> # Export to PDF
        >>> result = OutputFactory.export(
        ...     data,
        ...     format="pdf",
        ...     template="corporate",
        ...     output="report.pdf"
        ... )
        >>> print(result.file_path)
        >>>
        >>> # Generate slides
        >>> result = OutputFactory.slides(data, output="presentation.pptx")
    """

    @classmethod
    def export(
        cls,
        data: Any,
        format: str = "pdf",
        output: str | None = None,
        template: str | None = None,
        **kwargs,
    ) -> GeneratedOutput:
        """
        Export data to specified format.

        Args:
            data: Data to export (workflow result, DataFrame, dict, etc.)
            format: Output format (pdf, pptx, dashboard, audio, etc.)
            output: Output file path
            template: Template name to use
            **kwargs: Format-specific parameters

        Returns:
            GeneratedOutput with file path and metadata
        """
        from openbench.output.generators import (
            AudioGenerator,
            DashboardGenerator,
            PDFGenerator,
            PowerPointGenerator,
        )

        # Map format to generator class and constructor kwargs
        generator_config = {
            "pdf": {
                "class": PDFGenerator,
                "constructor_kwargs": ["page_size"],
                "default_output": "report.pdf",
            },
            "pptx": {
                "class": PowerPointGenerator,
                "constructor_kwargs": [],
                "default_output": "presentation.pptx",
            },
            "slides": {
                "class": PowerPointGenerator,
                "constructor_kwargs": [],
                "default_output": "presentation.pptx",
            },
            "dashboard": {
                "class": DashboardGenerator,
                "constructor_kwargs": ["framework"],
                "default_output": None,
            },
            "audio": {
                "class": AudioGenerator,
                "constructor_kwargs": ["provider", "voice"],
                "default_output": "audio.mp3",
            },
        }

        config: dict[str, Any] | None = generator_config.get(format)
        if config:
            generator_class = config["class"]

            # Split kwargs between constructor and generate()
            constructor_kwargs = {}
            generate_kwargs = {}

            for key, value in kwargs.items():
                if key in config["constructor_kwargs"]:
                    constructor_kwargs[key] = value
                else:
                    generate_kwargs[key] = value

            # Add template to constructor kwargs if it's a constructor param
            if template and "template" not in generate_kwargs:
                constructor_kwargs["template"] = template

            # Create generator instance
            generator = generator_class(**constructor_kwargs)

            # Determine output path
            output_path = output or config["default_output"]
            if output_path:
                generate_kwargs["output_path"] = output_path

            # Generate output
            return generator.generate(content=data, template=template, **generate_kwargs)

        # Fallback for unknown formats - return a placeholder GeneratedOutput
        output_path = output or f"outputs/export.{_get_extension(format)}"
        return GeneratedOutput(
            file_path=output_path,
            format=format,
            size_bytes=0,
            metadata={"warning": f"Unknown format '{format}', no generator available"},
        )

    @classmethod
    def pdf(
        cls,
        data: Any,
        template: str = "default",
        output: str | None = None,
        page_size: str = "letter",
        **kwargs,
    ) -> GeneratedOutput:
        """
        Generate a PDF report.

        Args:
            data: Content to render into PDF
            template: Template name for layout
            output: Output file path
            page_size: Page size ('letter', 'a4', etc.)
            **kwargs: Additional PDF options

        Returns:
            GeneratedOutput with file path and metadata
        """
        return cls.export(
            data,
            format="pdf",
            template=template,
            output=output,
            page_size=page_size,
            **kwargs,
        )

    @classmethod
    def slides(
        cls,
        data: Any,
        template: str = "corporate",
        output: str | None = None,
        **kwargs,
    ) -> GeneratedOutput:
        """
        Generate a slide presentation.

        Args:
            data: Slide content (list of dicts or dict with slides key)
            template: Template name for slide design
            output: Output file path
            **kwargs: Additional PPTX options

        Returns:
            GeneratedOutput with file path and metadata
        """
        return cls.export(data, format="pptx", template=template, output=output, **kwargs)

    @classmethod
    def dashboard(
        cls,
        data: Any,
        framework: str = "streamlit",
        port: int = 8501,
        **kwargs,
    ) -> GeneratedOutput:
        """
        Generate an interactive dashboard.

        Args:
            data: Data to visualize in dashboard
            framework: Dashboard framework ('streamlit', 'dash', 'gradio')
            port: Port to serve dashboard on
            **kwargs: Additional dashboard options

        Returns:
            GeneratedOutput with dashboard URL and metadata
        """
        return cls.export(data, format="dashboard", framework=framework, port=port, **kwargs)

    @classmethod
    def audio(
        cls,
        text: str,
        provider: str = "elevenlabs",
        voice: str = "professional_male",
        output: str | None = None,
        **kwargs,
    ) -> GeneratedOutput:
        """
        Generate audio from text (TTS).

        Args:
            text: Text to convert to speech
            provider: TTS provider ('elevenlabs', 'openai', 'google')
            voice: Voice ID or name
            output: Output file path
            **kwargs: Additional audio options

        Returns:
            GeneratedOutput with audio file path and metadata
        """
        return cls.export(
            text,
            format="audio",
            provider=provider,
            voice=voice,
            output=output,
            **kwargs,
        )

    @classmethod
    def batch(
        cls,
        data: Any,
        formats: list[str],
        output_dir: str = "outputs",
        **kwargs,
    ) -> dict[str, GeneratedOutput]:
        """
        Export to multiple formats simultaneously.

        Args:
            data: Data to export
            formats: List of output formats
            output_dir: Output directory
            **kwargs: Additional export parameters

        Returns:
            Dictionary mapping format to GeneratedOutput
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
