"""
Output Layer - Multi-Format Export Engine
"""

from typing import Any, Dict, List, Optional, Union
from pathlib import Path


class OutputLayer:
    """
    The Output Layer transforms results into various output formats.

    Examples:
        >>> # Export to PDF
        >>> OutputLayer.export(
        ...     result,
        ...     format="pdf",
        ...     template="corporate",
        ...     output="report.pdf"
        ... )
        >>>
        >>> # Generate slides
        >>> OutputLayer.export(
        ...     result,
        ...     format="slides",
        ...     output="presentation.pptx"
        ... )
        >>>
        >>> # Create dashboard
        >>> OutputLayer.export(
        ...     result,
        ...     format="dashboard",
        ...     framework="streamlit"
        ... )
    """

    def __init__(self, default_format: str = "pdf", templates_dir: Optional[str] = None):
        """
        Initialize the Output Layer.

        Args:
            default_format: Default output format
            templates_dir: Directory containing output templates
        """
        self.default_format = default_format
        self.templates_dir = templates_dir
        print(f"📤 OutputLayer initialized (default format: {default_format})")

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
        print(f"\n📤 Exporting to {format.upper()}")
        print(f"   Template: {template or 'default'}")
        print(f"   Output: {output or 'auto-generated'}")

        # Mock export logic
        import time
        time.sleep(1)

        output_path = output or f"outputs/export.{_get_extension(format)}"

        print(f"   ✓ Export complete: {output_path}\n")
        return output_path

    @classmethod
    def generate_report(
        cls,
        data: Any,
        format: str = "pdf",
        template: str = "default",
        output: Optional[str] = None,
        **kwargs
    ) -> str:
        """Generate a report in specified format."""
        return cls.export(data, format=format, template=template, output=output, **kwargs)

    @classmethod
    def generate_slides(
        cls,
        data: Any,
        template: str = "corporate",
        output: Optional[str] = None,
        **kwargs
    ) -> str:
        """Generate a slide presentation."""
        return cls.export(data, format="pptx", template=template, output=output, **kwargs)

    @classmethod
    def generate_dashboard(
        cls,
        data: Any,
        framework: str = "streamlit",
        port: int = 8501,
        **kwargs
    ) -> str:
        """Generate an interactive dashboard."""
        print(f"\n📊 Creating {framework} dashboard")
        print(f"   Port: {port}")
        print("   ✓ Dashboard created\n")
        return f"http://localhost:{port}"

    @classmethod
    def generate_audio(
        cls,
        text: str,
        voice: str = "professional_male",
        output: Optional[str] = None,
        **kwargs
    ) -> str:
        """Generate audio from text (TTS)."""
        return cls.export(
            text,
            format="audio",
            voice=voice,
            output=output or "outputs/audio.mp3",
            **kwargs
        )

    @classmethod
    def generate_infographic(
        cls,
        data: Any,
        style: str = "modern",
        output: Optional[str] = None,
        **kwargs
    ) -> str:
        """Generate an infographic."""
        return cls.export(
            data,
            format="infographic",
            style=style,
            output=output or "outputs/infographic.pdf",
            **kwargs
        )

    @classmethod
    def batch_export(
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
        print(f"\n📦 Batch export to {len(formats)} format(s)")

        results = {}
        for fmt in formats:
            output_path = f"{output_dir}/export.{_get_extension(fmt)}"
            results[fmt] = cls.export(data, format=fmt, output=output_path, **kwargs)

        print(f"   ✓ Batch export complete\n")
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
