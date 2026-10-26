"""Dashboard Chat — dashboard-first chat demo.

Connect your own database (SQLAlchemy URL), let the agent read the
schema (never the rows), get a generated dashboard, then refine it by
chatting in the side pane.

Run:
    Linux/macOS:
        export GOOGLE_API_KEY=...
        uvicorn server:app --port 8007 --reload --reload-dir src

    Windows (PowerShell):
        $env:GOOGLE_API_KEY="..."
        uvicorn server:app --port 8007 --reload --reload-dir src

Or simply: ``openbench demo run dashboard-chat``

Accounts (local auth, no cloud): admin/admin123 and guest/guest123.
Each account owns its database connection, dashboard, and conversation.
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

_EXAMPLE_ROOT = Path(__file__).resolve().parent

sys.path.insert(0, str(_EXAMPLE_ROOT / "src"))

# .env first so it wins over the setdefault() baseline below.
load_dotenv(_EXAMPLE_ROOT / ".env")

# API-key fallback: reuse the sibling general-chat example's .env so this
# demo runs without any manual `export GOOGLE_API_KEY=...`. Only the API
# key is imported — inheriting the full .env could override this
# example's storage isolation.
_FALLBACK_ENV_FILE = _EXAMPLE_ROOT.parent / "general-chat" / ".env"
if _FALLBACK_ENV_FILE.is_file():
    _fallback_values = dotenv_values(_FALLBACK_ENV_FILE)
    _value = (_fallback_values.get("GOOGLE_API_KEY") or "").strip()
    if _value and not os.getenv("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = _value

_DEFAULT_ENV = {
    "DASHBOARD_CHAT_STORAGE_ROOT": str(_EXAMPLE_ROOT / ".openbench"),
    "DASHBOARD_CHAT_MEMORY_DB": str(_EXAMPLE_ROOT / ".openbench" / "memory.db"),
    "DASHBOARD_CHAT_SOUL_DIR": str(_EXAMPLE_ROOT / "soul"),
}

for _name, _value in _DEFAULT_ENV.items():
    os.environ.setdefault(_name, _value)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)

from dashboard_chat.app import create_app  # noqa: E402

app = create_app()
