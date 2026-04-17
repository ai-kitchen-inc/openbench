"""Google Drive / Docs integrations for OpenBench.

Optional — install via ``pip install openbench[gdrive]``.

Currently ships:

- :class:`GoogleDocPersonaSource` — backend for :class:`Persona` that
  reads SOUL/STYLE/AGENTS sections from a single Google Doc. Sections
  are identified by H1 headings (``# SOUL``, ``# STYLE``, ``# AGENTS``);
  if no H1 matches, the whole document becomes the ``agents`` section.
- :class:`GoogleDrivePersonaSource` — same shape, but reads three sibling
  markdown files (``SOUL.md`` / ``STYLE.md`` / ``AGENTS.md``) from a
  single Drive folder. Pick this when non-developer editors prefer
  one-file-per-section authoring.
"""

from __future__ import annotations

from openbench.integrations.gdrive.backend import GoogleDriveStorageBackend
from openbench.integrations.gdrive.drive_persona_source import GoogleDrivePersonaSource
from openbench.integrations.gdrive.persona_source import GoogleDocPersonaSource
from openbench.integrations.gdrive.scratchpad import GoogleDriveScratchpad
from openbench.integrations.gdrive.session_store import GoogleDriveSessionStore

__all__ = [
    "GoogleDocPersonaSource",
    "GoogleDrivePersonaSource",
    "GoogleDriveScratchpad",
    "GoogleDriveSessionStore",
    "GoogleDriveStorageBackend",
]
