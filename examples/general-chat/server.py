"""General Chat general-purpose chat assistant demo.

Run:
    Linux/macOS:
        export GOOGLE_API_KEY=...
        uvicorn server:app --port 8005 --reload --reload-dir src

    Windows (PowerShell):
        $env:GOOGLE_API_KEY="..."
        uvicorn server:app --port 8005 --reload --reload-dir src

``--reload-dir src`` keeps the reloader off the ``.openbench/`` storage tree —
without it, saving a custom function (which writes ``<name>.py`` under
``.openbench/``) restarts the server mid-request. Trade-off: edits to this
bootstrap file itself need a manual restart.
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
