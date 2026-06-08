"""Environment-driven configuration for the generic API MCP service."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


@dataclass(frozen=True)
class AppConfig:
    """Runtime settings for generic authenticated API access."""

    timeout_seconds: float = 30.0
    username: str | None = None
    password: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> AppConfig:
        """Build configuration from environment variables."""
        return cls(
            timeout_seconds=_env_float("GENERIC_API_TIMEOUT_SECONDS", 30.0),
            username=os.getenv("GENERIC_API_USERNAME") or None,
            password=os.getenv("GENERIC_API_PASSWORD") or None,
        )

    @property
    def auth(self) -> tuple[str, str] | None:
        """Return Basic Auth credentials when both optional env values are set."""
        if self.username and self.password:
            return (self.username, self.password)
        return None
