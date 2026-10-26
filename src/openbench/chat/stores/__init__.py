"""Concrete SessionStore implementations.

- :class:`SQLiteSessionStore` — SQLite-backed default.
"""

from __future__ import annotations

from openbench.chat.stores.sqlite import SQLiteSessionStore

__all__ = ["SQLiteSessionStore"]
