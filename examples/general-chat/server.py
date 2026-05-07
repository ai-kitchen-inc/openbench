"""General Chat — document-aware chat assistant demo.

Run:
    Linux/macOS:
        export GOOGLE_API_KEY=...
        uvicorn server:app --port 8005 --reload

    Windows (PowerShell):
        $env:GOOGLE_API_KEY="..."
        uvicorn server:app --port 8005 --reload
"""

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent / "src"))

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)

from general_chat.server.app import create_app  # noqa: E402

app = create_app()
