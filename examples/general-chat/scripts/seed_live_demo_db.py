"""Create a small sqlite database for exercising live dashboards locally.

Usage::

    python examples/general-chat/scripts/seed_live_demo_db.py [PATH]

Writes ``sales(day, region, revenue)`` with a few rows and prints the
``sqlite+aiosqlite:///...`` URL to put in ``MCP_DB_DATABASE_URL``. Re-running
appends one more row per call (handy for watching a dashboard refresh).
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / ".openbench" / "live-demo.db"

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


def main(argv: list[str]) -> int:
    path = Path(argv[1]).expanduser().resolve() if len(argv) > 1 else DEFAULT_PATH
    count = seed(path)
    print(f"sales rows: {count}")
    print(f"MCP_DB_DATABASE_URL=sqlite+aiosqlite:///{path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
