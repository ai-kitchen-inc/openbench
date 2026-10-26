"""LCI Mini — Persona Layer demo server.

Run via OpenBench CLI (auto-installs deps + builds chat-ui):
    export GOOGLE_API_KEY=...
    openbench demo run lci-mini

Or directly:
    uvicorn server:app --port 8004 --reload
"""

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Make the local src/ importable without an install step
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Load .env from this directory BEFORE create_app() reads env vars.
# create_app() is kept env-pure so tests can monkeypatch freely.
load_dotenv(Path(__file__).parent / ".env")

# Ensure openbench + lci_mini module loggers are visible in the console.
# Without this, uvicorn's root handler swallows ``logger.info/warning``
# from application code, making silent failures hard to diagnose.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)

from lci_mini.server.app import create_app  # noqa: E402  — after load_dotenv

app = create_app()
