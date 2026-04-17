"""Persona backend backed by a Google Doc.

A single Google Doc holds all three persona sections. Sections are
identified by H1 headings whose text, case-insensitive and stripped of
surrounding whitespace, matches one of ``SOUL``, ``STYLE``, or
``AGENTS``. The body text between one matching H1 and the next is the
content of that section.

If the document has no matching H1 at all, the entire body falls back to
the ``agents`` section — treating the whole doc as the agent's rulebook.

Authentication goes through a Google service account (recommended for
server-side deployments). Share the Doc with the service account's
email so the API can read it.

Example:
    >>> from openbench.integrations.gdrive import GoogleDocPersonaSource
    >>> from openbench.intelligence.persona import Persona
    >>> source = GoogleDocPersonaSource(
    ...     doc_id="1ABCdef...",
    ...     service_account_file="/secrets/persona-reader.json",
    ... )
    >>> persona = Persona.from_source(source)
    >>> persona.compose()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from openbench.intelligence.persona_source import PersonaSource

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["GoogleDocPersonaSource"]

# Read-only scope is sufficient for pulling persona content.
_DOCS_READONLY_SCOPES = ("https://www.googleapis.com/auth/documents.readonly",)

_SECTION_ALIASES: dict[str, str] = {
    "SOUL": "soul",
    "STYLE": "style",
    "AGENTS": "agents",
}


def _missing_dep_message() -> str:
    return (
        "GoogleDocPersonaSource requires the 'gdrive' extras. Install with:\n"
        "    pip install openbench[gdrive]\n"
        "which pulls google-api-python-client and google-auth."
    )


class GoogleDocPersonaSource(PersonaSource):
    """Fetch a Persona's sections from a single Google Doc.

    Constructor authentication options (one must be provided):

    - ``service_account_file``: path to a service-account JSON key.
    - ``credentials``: a pre-built ``google.auth.credentials.Credentials``
      object (useful for ADC or custom auth flows).

    Attributes:
        doc_id: The Google Doc document id.
        cache_ttl: Seconds to cache fetched content (process-local).
            Set to ``0`` to disable caching.
        source: The literal string ``"GoogleDocPersonaSource"`` (used by
            :class:`~openbench.intelligence.persona.Persona` for debug).
    """

    def __init__(
        self,
        doc_id: str,
        *,
        service_account_file: str | Path | None = None,
        credentials: Any | None = None,
        cache_ttl: float = 300.0,
    ):
        if not doc_id:
            raise ValueError("doc_id must be a non-empty string")
        if service_account_file is None and credentials is None:
            raise ValueError("Either service_account_file= or credentials= must be provided.")

        self.doc_id = doc_id
        self._service_account_file = (
            str(service_account_file) if service_account_file is not None else None
        )
        self._explicit_credentials = credentials
        self.cache_ttl = max(0.0, float(cache_ttl))
        # Lazy init — no network on construction.
        self._service: Any = None
        self._service_lock = threading.Lock()
        # Cached, fully-split sections.
        self._cache: dict[str, str] | None = None
        self._cache_expires_at: float = 0.0
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------ PersonaSource

    def fetch(self, key: str) -> str:
        """Return the content for ``key`` (``soul``/``style``/``agents``).

        Unknown keys return an empty string.
        """
        if key not in PersonaSource.KEYS:
            return ""
        sections = self._get_sections()
        return sections.get(key, "")

    def refresh(self) -> None:
        """Drop the in-memory cache so the next ``fetch`` hits the Doc API."""
        with self._cache_lock:
            self._cache = None
            self._cache_expires_at = 0.0

    def __repr__(self) -> str:
        return f"GoogleDocPersonaSource(doc_id={self.doc_id!r})"

    # ---------------------------------------------------------------- internals

    def _get_sections(self) -> dict[str, str]:
        """Return the parsed sections dict, fetching via the API if needed."""
        now = time.monotonic()
        with self._cache_lock:
            if self._cache is not None and self.cache_ttl > 0.0 and now < self._cache_expires_at:
                return self._cache

        # Outside the lock — fetch + parse.
        doc = self._fetch_doc()
        sections = _parse_sections(doc)

        with self._cache_lock:
            self._cache = sections
            self._cache_expires_at = now + self.cache_ttl
        return sections

    def _fetch_doc(self) -> dict[str, Any]:
        """Call the Docs API to retrieve the full document JSON."""
        service = self._get_service()
        # ``.documents().get(documentId=...)`` is the read-only fetch.
        return service.documents().get(documentId=self.doc_id).execute()  # type: ignore[no-any-return]

    def _get_service(self) -> Any:
        """Build (or reuse) a ``docs`` API client."""
        if self._service is not None:
            return self._service
        with self._service_lock:
            if self._service is None:
                self._service = self._build_service()
            return self._service

    def _build_service(self) -> Any:
        """Lazy-import googleapiclient and build the service.

        Lazy so plain tests that don't touch this class don't require
        the optional deps, and tests that do can patch the imports.
        """
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ImportError(_missing_dep_message()) from exc

        creds = self._explicit_credentials
        if creds is None:
            # Build credentials from the service account file.
            try:
                from google.oauth2 import service_account
            except ImportError as exc:
                raise ImportError(_missing_dep_message()) from exc
            assert self._service_account_file is not None
            creds = service_account.Credentials.from_service_account_file(
                self._service_account_file,
                scopes=list(_DOCS_READONLY_SCOPES),
            )

        return build("docs", "v1", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------------
# Pure-Python document → section parser
# ---------------------------------------------------------------------------


def _parse_sections(doc: dict[str, Any]) -> dict[str, str]:
    """Walk the Docs API response and split body into persona sections.

    Returns a dict with keys ``soul``, ``style``, ``agents``. Missing
    sections resolve to empty strings. If no H1 heading matches the
    three canonical names, the whole document body is returned as the
    ``agents`` section.
    """
    body = doc.get("body", {})
    content = body.get("content") or []

    buckets: dict[str, list[str]] = {"soul": [], "style": [], "agents": []}
    # When no H1 has been seen yet, we collect text into "preamble" and
    # fall it back to ``agents`` at the end if no section was detected.
    preamble: list[str] = []
    current: str | None = None

    for element in content:
        paragraph = element.get("paragraph")
        if paragraph is None:
            # Tables, section breaks, etc. — ignored for now.
            continue
        text = _paragraph_text(paragraph)
        style = (paragraph.get("paragraphStyle") or {}).get("namedStyleType", "")

        if style == "HEADING_1":
            header = text.strip().upper()
            # Strip punctuation/extra formatting that sometimes leaks
            # from Google Docs (e.g. trailing colons).
            header = header.rstrip(":").strip()
            matched = _SECTION_ALIASES.get(header)
            if matched is not None:
                current = matched
                continue
            # Non-matching H1 inside a recognized section belongs to the
            # section's content; keep it verbatim as markdown.
            if current is not None:
                buckets[current].append(f"# {text.strip()}")
            else:
                preamble.append(f"# {text.strip()}")
            continue

        if not text:
            continue

        rendered = _render_paragraph(paragraph, text, style)
        if current is None:
            preamble.append(rendered)
        else:
            buckets[current].append(rendered)

    sections = {k: _join(v).strip() for k, v in buckets.items()}

    # Fallback: no recognized H1 → treat entire doc as ``agents``.
    if all(not v for v in sections.values()):
        sections["agents"] = _join(preamble).strip()

    return sections


def _paragraph_text(paragraph: dict[str, Any]) -> str:
    """Concatenate all textRun content in a paragraph."""
    parts: list[str] = []
    for el in paragraph.get("elements") or []:
        run = el.get("textRun")
        if run and "content" in run:
            parts.append(run["content"])
    return "".join(parts).rstrip("\n")


def _render_paragraph(paragraph: dict[str, Any], text: str, style: str) -> str:
    """Render a paragraph back to markdown-ish text.

    Keeps it simple — heading levels and bullets are the only special
    cases we bother with. Anything fancier round-trips as plain text.
    """
    stripped = text.rstrip("\n")
    if style == "HEADING_2":
        return f"## {stripped}"
    if style == "HEADING_3":
        return f"### {stripped}"
    if style == "HEADING_4":
        return f"#### {stripped}"
    bullet = paragraph.get("bullet")
    if bullet:
        return f"- {stripped}"
    return stripped


def _join(parts: list[str]) -> str:
    """Join non-empty parts with single newlines, inserting blanks around headings."""
    return "\n".join(p for p in parts if p)
