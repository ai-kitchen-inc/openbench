from __future__ import annotations

import sys
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MCP_ROOT.parents[1]
SRC_ROOT = REPO_ROOT / "src"

for path in (SRC_ROOT, MCP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
