"""Google Drive / Docs integrations for OpenBench.

Optional — install via ``pip install openbench[gdrive]``.

Currently ships:

- :class:`GoogleDocPersonaSource` — backend for :class:`Persona` that
  reads SOUL/STYLE/AGENTS sections from a single Google Doc. Sections
  are identified by H1 headings (``# SOUL``, ``# STYLE``, ``# AGENTS``);
  if no H1 matches, the whole document becomes the ``agents`` section.
"""

from __future__ import annotations

from openbench.integrations.gdrive.persona_source import GoogleDocPersonaSource

__all__ = ["GoogleDocPersonaSource"]
