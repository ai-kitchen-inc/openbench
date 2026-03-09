"""
LCI Ignite X — AI-powered LCA analysis platform.

Run:
    uvicorn server:app --port 8003 --reload
"""

import sys
from pathlib import Path

# Add src/ to path so lci_ignite package is importable
sys.path.insert(0, str(Path(__file__).parent / "src"))

from lci_ignite.server.app import create_app

app = create_app()
