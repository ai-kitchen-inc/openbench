"""Markdown file generation."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from openbench.core.abstractions import GeneratedOutput, OutputGenerator

logger = logging.getLogger(__name__)


class MarkdownGenerator(OutputGenerator):
    """
    Generate Markdown files.

    Implements the OutputGenerator interface for Markdown output.

    Example:
        ```python
        generator = MarkdownGenerator(output_path="reports/analysis.md")
        result = generator.generate(
            content="# My Report\\n\\nThis is content...",
        )
        ```
    """

    def __init__(self, output_path: str = "output.md", add_toc: bool = False):
        """
        Initialize Markdown generator.

        Args:
            output_path: Default output file path
            add_toc: Whether to add table of contents
        """
        self.default_output_path = output_path
        self.add_toc = add_toc
        logger.debug(
            f"MarkdownGenerator initialized (output_path: {output_path}, add_toc: {add_toc})"
        )

    @property
    def output_format(self) -> str:
        """Output format identifier."""
        return "markdown"

    def validate(self, content: Any) -> bool:
        """Validate content can be rendered as Markdown."""
        if content is None:
            return False
        return isinstance(content, str | dict | list) or hasattr(content, "__str__")

    def _extract_content(self, content: Any) -> str:
        """Extract text content from various input formats."""
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            return "\n".join(f"- {item}" for item in content)

        if hasattr(content, "content"):
            return str(content.content)

        if not isinstance(content, dict):
            return str(content)

        # Handle dict inputs from various layers
        if "content" in content:
            return str(content["content"])

        if "intelligence_output" in content:
            output = content["intelligence_output"]
            if isinstance(output, dict) and "content" in output:
                return str(output["content"])
            return str(output)

        # Convert remaining dict keys to markdown sections
        parts = [
            f"## {key}\n\n{value}"
            for key, value in content.items()
            if key not in ("metadata", "tokens_used", "model")
        ]
        return "\n\n".join(parts) if parts else str(content)

    def generate(
        self,
        content: Any,
        template: str | None = None,
        output_path: str | None = None,
        title: str | None = None,
        **options,
    ) -> GeneratedOutput:
        """
        Generate Markdown file.

        Args:
            content: Content to render
            template: Template (unused for markdown)
            output_path: Output file path (uses default from constructor if None)
            title: Document title
            **options: Additional options

        Returns:
            GeneratedOutput with file path and metadata
        """
        output_path = output_path or self.default_output_path
        logger.info(f"Generating Markdown: {output_path}")

        text_content = self._extract_content(content)

        # Ensure output directory exists
        output_dir = Path(output_path).parent
        if output_dir and str(output_dir) != ".":
            output_dir.mkdir(parents=True, exist_ok=True)

        # Build markdown content
        md_content = ""

        if title:
            md_content += f"# {title}\n\n"
            md_content += f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n"
            md_content += "---\n\n"

        md_content += text_content

        # Write file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        size_bytes = os.path.getsize(output_path)
        logger.info(f"Markdown generated: {output_path} ({size_bytes} bytes)")

        return GeneratedOutput(
            file_path=output_path,
            format=self.output_format,
            size_bytes=size_bytes,
            metadata={
                "title": title,
                "content_length": len(text_content),
                **options,
            },
        )
