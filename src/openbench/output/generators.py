"""Output format generators.

Provides concrete implementations of OutputGenerator for various formats:
- PDFGenerator: Generate PDF reports
- PowerPointGenerator: Generate PPTX presentations
- DashboardGenerator: Generate interactive dashboards
- AudioGenerator: Generate audio content from text
"""

import logging
import os
from typing import Any, Dict, List, Optional

from openbench.core.abstractions import GeneratedOutput, OutputGenerator

logger = logging.getLogger(__name__)


class PDFGenerator(OutputGenerator):
    """
    Generate PDF reports.

    Implements the OutputGenerator interface for PDF output.

    Example:
        >>> generator = PDFGenerator(template="report")
        >>> result = generator.generate(content=data, output_path="report.pdf")
        >>> print(result.file_path)
    """

    def __init__(self, template: str = "default", page_size: str = "letter"):
        """
        Initialize PDF generator.

        Args:
            template: Template name to use for layout
            page_size: Page size ('letter', 'a4', etc.)
        """
        self.template = template
        self.page_size = page_size
        logger.debug(f"PDFGenerator initialized (template: {template})")

    @property
    def output_format(self) -> str:
        """Output format identifier."""
        return "pdf"

    def validate(self, content: Any) -> bool:
        """
        Validate that content can be rendered as PDF.

        Args:
            content: Content to validate

        Returns:
            True if content can be rendered
        """
        if content is None:
            return False
        # Accept strings, dicts, or objects with __str__
        return isinstance(content, (str, dict, list)) or hasattr(content, "__str__")

    def generate(
        self,
        content: Any,
        template: Optional[str] = None,
        output_path: str = "report.pdf",
        **options,
    ) -> GeneratedOutput:
        """
        Generate PDF report.

        Args:
            content: Content to render into PDF
            template: Template override (uses instance template if None)
            output_path: Output file path
            **options: Additional PDF-specific options

        Returns:
            GeneratedOutput with file path and metadata
        """
        used_template = template or self.template
        logger.info(f"Generating PDF: {output_path}")

        # Placeholder for actual PDF generation logic
        # In a real implementation, this would use a library like reportlab or weasyprint
        size_bytes = len(str(content).encode("utf-8")) if content else 0

        return GeneratedOutput(
            file_path=output_path,
            format=self.output_format,
            size_bytes=size_bytes,
            metadata={
                "template": used_template,
                "page_size": self.page_size,
                **options,
            },
        )


class PowerPointGenerator(OutputGenerator):
    """
    Generate PowerPoint presentations.

    Implements the OutputGenerator interface for PPTX output.

    Example:
        >>> generator = PowerPointGenerator(template="corporate")
        >>> slides = [{"title": "Intro", "content": "..."}]
        >>> result = generator.generate(content=slides)
    """

    def __init__(self, template: str = "corporate"):
        """
        Initialize PowerPoint generator.

        Args:
            template: Template name for slide design
        """
        self.template = template
        logger.debug(f"PowerPointGenerator initialized (template: {template})")

    @property
    def output_format(self) -> str:
        """Output format identifier."""
        return "pptx"

    def validate(self, content: Any) -> bool:
        """
        Validate that content can be rendered as PowerPoint.

        Args:
            content: Content to validate (should be list of slide dicts)

        Returns:
            True if content is valid slide data
        """
        if content is None:
            return False
        # Accept list of dicts (slides) or dict with slides key
        if isinstance(content, list):
            return True
        if isinstance(content, dict):
            return "slides" in content or len(content) > 0
        return False

    def generate(
        self,
        content: Any,
        template: Optional[str] = None,
        output_path: str = "presentation.pptx",
        **options,
    ) -> GeneratedOutput:
        """
        Generate PowerPoint presentation.

        Args:
            content: Slide content (list of dicts or dict with slides key)
            template: Template override
            output_path: Output file path
            **options: Additional PPTX-specific options

        Returns:
            GeneratedOutput with file path and metadata
        """
        used_template = template or self.template

        # Normalize slides data
        if isinstance(content, list):
            slides = content
        elif isinstance(content, dict) and "slides" in content:
            slides = content["slides"]
        else:
            slides = [content] if content else []

        logger.info(f"Generating {len(slides)} slides: {output_path}")

        # Placeholder for actual PPTX generation
        size_bytes = len(str(slides).encode("utf-8"))

        return GeneratedOutput(
            file_path=output_path,
            format=self.output_format,
            size_bytes=size_bytes,
            metadata={
                "template": used_template,
                "slide_count": len(slides),
                **options,
            },
        )


class DashboardGenerator(OutputGenerator):
    """
    Generate interactive dashboards.

    Implements the OutputGenerator interface for dashboard output.

    Example:
        >>> generator = DashboardGenerator(framework="streamlit")
        >>> result = generator.generate(content=data, port=8501)
    """

    def __init__(self, framework: str = "streamlit"):
        """
        Initialize dashboard generator.

        Args:
            framework: Dashboard framework ('streamlit', 'dash', 'gradio')
        """
        self.framework = framework
        logger.debug(f"DashboardGenerator initialized (framework: {framework})")

    @property
    def output_format(self) -> str:
        """Output format identifier."""
        return "dashboard"

    def validate(self, content: Any) -> bool:
        """
        Validate that content can be rendered as dashboard.

        Args:
            content: Content to validate

        Returns:
            True if content is valid dashboard data
        """
        if content is None:
            return False
        # Accept dicts, lists, or dataframe-like objects
        return isinstance(content, (dict, list)) or hasattr(content, "to_dict")

    def generate(
        self,
        content: Any,
        template: Optional[str] = None,
        port: int = 8501,
        output_path: Optional[str] = None,
        **options,
    ) -> GeneratedOutput:
        """
        Generate interactive dashboard.

        Args:
            content: Data to visualize in dashboard
            template: Dashboard template/layout
            port: Port to serve dashboard on
            output_path: Path for generated dashboard files
            **options: Additional dashboard-specific options

        Returns:
            GeneratedOutput with dashboard URL and metadata
        """
        dashboard_url = f"http://localhost:{port}"
        file_path = output_path or f"dashboard_{port}"

        logger.info(f"Creating {self.framework} dashboard on port {port}")

        return GeneratedOutput(
            file_path=file_path,
            format=self.output_format,
            size_bytes=0,  # Dashboards are served, not static files
            metadata={
                "framework": self.framework,
                "url": dashboard_url,
                "port": port,
                "template": template,
                **options,
            },
        )


class AudioGenerator(OutputGenerator):
    """
    Generate audio content from text.

    Implements the OutputGenerator interface for audio output.

    Example:
        >>> generator = AudioGenerator(provider="elevenlabs", voice="professional_male")
        >>> result = generator.generate(content="Hello world", output_path="greeting.mp3")
    """

    def __init__(self, provider: str = "elevenlabs", voice: str = "professional_male"):
        """
        Initialize audio generator.

        Args:
            provider: TTS provider ('elevenlabs', 'openai', 'google')
            voice: Voice ID or name to use
        """
        self.provider = provider
        self.voice = voice
        logger.debug(f"AudioGenerator initialized (provider: {provider}, voice: {voice})")

    @property
    def output_format(self) -> str:
        """Output format identifier."""
        return "audio"

    def validate(self, content: Any) -> bool:
        """
        Validate that content can be rendered as audio.

        Args:
            content: Content to validate (should be text or SSML)

        Returns:
            True if content is valid for TTS
        """
        if content is None:
            return False
        # Accept strings or objects with text property
        if isinstance(content, str):
            return len(content.strip()) > 0
        if hasattr(content, "text"):
            return len(str(content.text).strip()) > 0
        return False

    def generate(
        self,
        content: Any,
        template: Optional[str] = None,
        output_path: str = "audio.mp3",
        **options,
    ) -> GeneratedOutput:
        """
        Generate audio from text.

        Args:
            content: Text to convert to speech
            template: Audio style/template (unused, for interface compatibility)
            output_path: Output file path
            **options: Additional audio-specific options (speed, pitch, etc.)

        Returns:
            GeneratedOutput with audio file path and metadata
        """
        # Extract text from content
        if isinstance(content, str):
            text = content
        elif hasattr(content, "text"):
            text = str(content.text)
        else:
            text = str(content)

        logger.info(f"Generating audio: {output_path}")

        # Placeholder for actual TTS generation
        # Estimate size based on text length (rough MP3 estimate)
        estimated_duration_secs = len(text.split()) / 2.5  # ~150 words per minute
        estimated_size = int(estimated_duration_secs * 16000)  # ~128kbps MP3

        return GeneratedOutput(
            file_path=output_path,
            format=self.output_format,
            size_bytes=estimated_size,
            metadata={
                "provider": self.provider,
                "voice": self.voice,
                "text_length": len(text),
                "estimated_duration_secs": estimated_duration_secs,
                **options,
            },
        )
