"""Controlled Source Chat — admin-curated, strictly source-grounded chat demo.

Run:
    Linux/macOS:
        export GOOGLE_API_KEY=...
        uvicorn server:app --port 8006 --reload --reload-dir src

    Windows (PowerShell):
        $env:GOOGLE_API_KEY="..."
        uvicorn server:app --port 8006 --reload --reload-dir src

Or simply: ``openbench demo run controlled-source-chat``

Accounts (local auth, no cloud): admin/admin123 manages sources and MCP
servers from the control panel; guest/guest123 gets chat only. The agent
answers strictly from the admin-curated sources and cites them by name.
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

_EXAMPLE_ROOT = Path(__file__).resolve().parent
_GENERAL_CHAT_SRC = _EXAMPLE_ROOT.parent / "general-chat" / "src"

sys.path.insert(0, str(_EXAMPLE_ROOT / "src"))
sys.path.insert(0, str(_GENERAL_CHAT_SRC))

# .env first so it wins over the setdefault() baseline below.
load_dotenv(_EXAMPLE_ROOT / ".env")


def _drop_unreachable_cloudsql_url() -> None:
    """Local-dev guard for the Cloud SQL database URL.

    The gitignored .env keeps ``GENERAL_CHAT_DATABASE_URL`` (a Cloud SQL unix
    socket URL) as configuration for deploy.sh, but that socket only exists
    inside Cloud Run. When the socket directory is absent — i.e. running
    locally — drop the variable so the source store falls back to local file
    storage instead of crashing the server on startup.
    """
    url = os.getenv("GENERAL_CHAT_DATABASE_URL", "")
    marker = "/cloudsql/"
    if marker not in url:
        return
    socket_dir = url[url.index(marker) :].split("&", 1)[0].split(" ", 1)[0]
    if Path(socket_dir).exists():
        return
    logging.getLogger(__name__).warning(
        "GENERAL_CHAT_DATABASE_URL points at Cloud SQL socket %s which does not "
        "exist on this machine — ignoring it and using local file storage.",
        socket_dir,
    )
    os.environ.pop("GENERAL_CHAT_DATABASE_URL", None)


_drop_unreachable_cloudsql_url()

# API-key fallback: reuse the sibling general-chat example's .env so this
# demo runs without any manual `export GOOGLE_API_KEY=...`. Only the keys
# listed here are imported — inheriting general-chat's full .env could
# override this example's storage/persona isolation.
_FALLBACK_ENV_FILE = _EXAMPLE_ROOT.parent / "general-chat" / ".env"
_FALLBACK_API_KEYS = ("GOOGLE_API_KEY", "TAVILY_API_KEY")
if _FALLBACK_ENV_FILE.is_file():
    _fallback_values = dotenv_values(_FALLBACK_ENV_FILE)
    for _key in _FALLBACK_API_KEYS:
        _value = (_fallback_values.get(_key) or "").strip()
        if _value and not os.getenv(_key):
            os.environ[_key] = _value

_STRICT_GOAL = (
    "Answer the user's question strictly from the curated source context and "
    "enabled tool results, citing each claim with the exact source name. If "
    "the sources do not cover the question, refuse and list the available "
    "source names instead of answering from general knowledge."
)

_SOURCE_LABEL = (
    "Authoritative knowledge-base source curated by the administrator. Answers "
    "must come ONLY from these sources and cite them by their source name."
)

_DEFAULT_ENV = {
    # Local-first: no Firebase — the wrapper's own middleware is the gatekeeper.
    "OPENBENCH_AUTH_DISABLED": "1",
    # Strict persona + per-turn goal + source framing.
    "GENERAL_CHAT_SOUL_DIR": str(_EXAMPLE_ROOT / "soul"),
    "GENERAL_CHAT_AGENT_GOAL": _STRICT_GOAL,
    "GENERAL_CHAT_SOURCE_CONTEXT_LABEL": _SOURCE_LABEL,
    # Every chat turn grounds on the admin-curated thread.
    "GENERAL_CHAT_SHARED_SOURCES_OWNER": "admin",
    "GENERAL_CHAT_SHARED_SOURCES_THREAD": "controlled-sources",
    # Keep runtime data inside this example's directory.
    "GENERAL_CHAT_STORAGE_ROOT": str(_EXAMPLE_ROOT / ".openbench"),
    "GENERAL_CHAT_UPLOAD_DIR": str(_EXAMPLE_ROOT / "uploads"),
    "GENERAL_CHAT_DOWNLOAD_DIR": str(_EXAMPLE_ROOT / "downloads"),
    "GENERAL_CHAT_MEMORY_DB": str(_EXAMPLE_ROOT / "controlled_source_chat_memory.db"),
    # MCP: admin-managed registry mode only.
    "GENERAL_CHAT_MCP_ENABLED": "0",
    "GENERAL_CHAT_MCP_REGISTRY_ENABLED": "1",
}

for _name, _value in _DEFAULT_ENV.items():
    os.environ.setdefault(_name, _value)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)

from controlled_source_chat.app import build_app  # noqa: E402

app = build_app()
