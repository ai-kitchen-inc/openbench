"""Create a small sqlite database for exercising live dashboards locally.

Usage::

    python examples/general-chat/scripts/seed_live_demo_db.py [PATH] [--print-env] [--venv DIR]

Writes ``sales(day, region, revenue)`` with a few rows and prints the
``sqlite+aiosqlite:///...`` URL to put in ``MCP_DB_DATABASE_URL``. Re-running
appends one more row per call (handy for watching a dashboard refresh).

``--print-env`` prints every line ``examples/general-chat/.env`` needs so
``openbench demo run general-chat`` registers the sqlite ``db_server`` twin by
itself (see LIVE_DASHBOARD.md, "Local recipe").
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXAMPLE_ROOT.parents[1]
DEFAULT_PATH = EXAMPLE_ROOT / ".openbench" / "live-demo.db"
DEFAULT_VENV = REPO_ROOT / ".venv-dbserver"

_REGIONS = ("Jawa", "Sumatra", "Kalimantan", "Sulawesi")


def seed(path: Path) -> int:
    """Create the table on first run, append one row afterwards; return the row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sales ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, "
            "region TEXT NOT NULL, revenue REAL NOT NULL)"
        )
        (count,) = conn.execute("SELECT COUNT(*) FROM sales").fetchone()
        if count == 0:
            start = date.today() - timedelta(days=6)
            rows = [
                (
                    (start + timedelta(days=offset)).isoformat(),
                    region,
                    1000 + 250 * offset + 90 * index,
                )
                for offset in range(7)
                for index, region in enumerate(_REGIONS)
            ]
            conn.executemany("INSERT INTO sales (day, region, revenue) VALUES (?, ?, ?)", rows)
        else:
            conn.execute(
                "INSERT INTO sales (day, region, revenue) VALUES (?, ?, ?)",
                (date.today().isoformat(), _REGIONS[count % len(_REGIONS)], 500 + count),
            )
        conn.commit()
        (count,) = conn.execute("SELECT COUNT(*) FROM sales").fetchone()
        return int(count)
    finally:
        conn.close()


def venv_python(venv: Path, *, windows: bool | None = None) -> Path:
    """Interpreter path inside ``venv`` for this platform."""
    on_windows = os.name == "nt" if windows is None else windows
    return venv / ("Scripts/python.exe" if on_windows else "bin/python")


def print_env_lines(
    db_path: Path,
    venv: Path,
    *,
    example_root: Path = EXAMPLE_ROOT,
    windows: bool | None = None,
) -> list[str]:
    """The ``.env`` lines that make the sqlite db_server twin start with the app."""
    return [
        f"DB_SERVER_MCP_PYTHON={venv_python(venv, windows=windows).as_posix()}",
        f"MCP_DB_DATABASE_URL=sqlite+aiosqlite:///{db_path.resolve().as_posix()}",
        f"DB_SERVER_MCP_CWD={(example_root / 'mcp' / 'db-server').resolve().as_posix()}",
        "GENERAL_CHAT_SEED_MCP_CONFIGS=db-server-local.yaml",
    ]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("path", nargs="?", default=str(DEFAULT_PATH), help="sqlite file to seed")
    parser.add_argument(
        "--print-env",
        action="store_true",
        help="print the examples/general-chat/.env lines for the local db_server twin",
    )
    parser.add_argument(
        "--venv",
        default=str(DEFAULT_VENV),
        help="venv holding the db_server fork deps (default: <repo>/.venv-dbserver)",
    )
    args = parser.parse_args(argv[1:])

    path = Path(args.path).expanduser().resolve()
    count = seed(path)
    print(f"sales rows: {count}")
    if args.print_env:
        venv = Path(args.venv).expanduser()
        if not venv_python(venv).exists():
            print(
                f"note: {venv_python(venv)} does not exist yet; create the venv first "
                "(see LIVE_DASHBOARD.md)",
                file=sys.stderr,
            )
        print("\n# --- paste into examples/general-chat/.env ---")
        for line in print_env_lines(path, venv):
            print(line)
    else:
        print(f"MCP_DB_DATABASE_URL=sqlite+aiosqlite:///{path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
