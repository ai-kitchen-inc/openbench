"""Business logic for the example MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ExampleService:
    """Small service object used by MCP tools and optional OpenBench skills."""

    prefix: str = "example"

    def echo(self, text: str, uppercase: bool = False) -> dict[str, str | int | bool]:
        """Return a compact echo payload."""
        normalized = text.strip()
        if not normalized:
            raise ValueError("text must not be empty")
        value = normalized.upper() if uppercase else normalized
        return {
            "prefix": self.prefix,
            "text": value,
            "uppercase": uppercase,
            "length": len(value),
        }


def get_service() -> ExampleService:
    """Build the service from environment configuration."""
    return ExampleService(prefix=os.getenv("EXAMPLE_MCP_PREFIX", "example"))
