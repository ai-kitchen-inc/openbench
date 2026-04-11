"""LCI Mini — Persona Layer demo server.

Run via OpenBench CLI (auto-installs deps + builds chat-ui):
    export GOOGLE_API_KEY=...
    openbench demo run lci-mini

Or directly:
    uvicorn server:app --port 8004 --reload
"""

import sys
from pathlib import Path

# Make the local src/ importable without an install step
sys.path.insert(0, str(Path(__file__).parent / "src"))

from lci_mini.server.app import create_app

app = create_app()
