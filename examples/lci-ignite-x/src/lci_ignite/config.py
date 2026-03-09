"""Configuration for LCI Ignite X."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LCIConfig:
    """Application configuration loaded from environment variables."""

    # Google Gemini
    google_api_key: str = ""
    model: str = "gemini-2.5-flash"
    temperature: float = 0.3

    # Pinecone
    pinecone_api_key: str = ""
    pinecone_index_name: str = "lci-ignite"
    pinecone_namespace: str = "proper-2025"

    # Storage
    memory_db: str = "lci_memory.db"
    upload_dir: str = "./uploads"

    # Embedding
    embedding_model: str = "text-embedding-004"

    @classmethod
    def from_env(cls, dotenv_path: str | Path | None = None) -> LCIConfig:
        """Load configuration from environment variables.

        Args:
            dotenv_path: Optional path to .env file. If None, tries to find
                .env in the current directory or parent directories.
        """
        try:
            from dotenv import load_dotenv

            if dotenv_path:
                load_dotenv(dotenv_path)
            else:
                load_dotenv()
        except ImportError:
            pass

        return cls(
            google_api_key=os.getenv("GOOGLE_API_KEY", ""),
            model=os.getenv("LCI_MODEL", "gemini-2.5-flash"),
            temperature=float(os.getenv("LCI_TEMPERATURE", "0.3")),
            pinecone_api_key=os.getenv("PINECONE_API_KEY", ""),
            pinecone_index_name=os.getenv("PINECONE_INDEX_NAME", "lci-ignite"),
            pinecone_namespace=os.getenv("PINECONE_NAMESPACE", "proper-2025"),
            memory_db=os.getenv("LCI_MEMORY_DB", "lci_memory.db"),
            upload_dir=os.getenv("LCI_UPLOAD_DIR", "./uploads"),
            embedding_model=os.getenv("LCI_EMBEDDING_MODEL", "text-embedding-004"),
        )

    def validate(self) -> list[str]:
        """Validate required configuration. Returns list of missing fields."""
        missing = []
        if not self.google_api_key:
            missing.append("GOOGLE_API_KEY")
        return missing
