"""Detect "give me a file" requests in the user's own message.

General Chat users write in English and Bahasa Indonesia interchangeably,
and the model routinely satisfies a file request with an inline markdown
table instead of calling an export tool. This module recognises the
request so the handler can inject a per-turn instruction naming the exact
tool to call.

Two rules keep the detector honest:

1. **Only the user's own message is ever passed in.** Injected source
   text is full of words like "excel" and "unduh"; matching against it
   would fire the nudge on turns where the user asked nothing of the
   sort.
2. **A verb alone never fires.** In Indonesian "ekspor" also means trade
   export ("ekspor impor"), and "buatkan" (make me) is far too generic.
   A match needs a format token, or an export verb paired with a
   file-ish noun.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "ExportIntent",
    "detect_export_intent",
    "EXPORT_TOOL_BY_FORMAT",
]


# Format -> the tool the model should call. ``unknown`` means the user
# clearly wants a file but did not name a format; the instruction then
# lists the options and lets the model pick.
EXPORT_TOOL_BY_FORMAT: dict[str, str] = {
    "xlsx": "export_to_excel",
    "pdf": "generate_pdf",
    "md": "generate_markdown",
    "pdf_merge": "merge_pdfs",
    "pdf_split": "split_pdf",
}


# Verbs that on their own signal "produce something I can keep".
_STRONG_VERBS = (
    "export",
    "download",
    "save as",
    "save this as",
    "ekspor",
    "eksport",
    "unduh",
    "diunduh",
    "diekspor",
    "simpan sebagai",
)

# Verbs that only count when a format or file noun is also present.
_WEAK_VERBS = (
    "generate",
    "create",
    "make",
    "send me",
    "give me",
    "buatkan",
    "buat",
    "bikin",
    "kirim",
    "kirimkan",
)

# Nouns that mean "a file", without naming a format.
_FILE_NOUNS = (
    "file",
    "files",
    "document",
    "attachment",
    "berkas",
    "dokumen",
    "lampiran",
    "unduhan",
)

# Format tokens. Order matters only for readability — resolution order is
# handled explicitly in _detect_format.
_XLSX_TOKENS = (
    "excel",
    "xlsx",
    "xls",
    "spreadsheet",
    "workbook",
    "worksheet",
    "lembar kerja",
)
_PDF_TOKENS = ("pdf",)
_MD_TOKENS = ("markdown", "md")

# Format tokens strong enough to fire with no verb at all, because no
# other reading makes sense.
_STANDALONE_TOKENS = (
    "xlsx",
    "file excel",
    "berkas excel",
    "file pdf",
    "berkas pdf",
    "laporan pdf",
    "file markdown",
    "berkas markdown",
)

_MERGE_VERBS = ("merge", "combine", "join", "gabung", "gabungkan", "satukan")
_SPLIT_VERBS = ("split", "extract page", "extract pages", "pisah", "pisahkan", "ambil halaman")


@dataclass(frozen=True)
class ExportIntent:
    """A detected request for one or more downloadable files.

    A single turn can ask for several formats at once ("buatkan excel,
    pdf, dan markdown"), so ``formats`` carries every format found.

    Attributes:
        format: The primary format — first of ``formats``. One of
            ``EXPORT_TOOL_BY_FORMAT``'s keys, or ``"unknown"`` when the
            user asked for a file without naming a format.
        tool: The tool for ``format``, or ``None`` for ``"unknown"``.
        formats: Every format detected, in match order.
    """

    format: str
    tool: str | None = None
    formats: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.formats:
            object.__setattr__(self, "formats", (self.format,))

    @property
    def tools(self) -> tuple[str, ...]:
        """Every tool to call, in match order. Empty for ``unknown``."""
        return tuple(tool for tool in (EXPORT_TOOL_BY_FORMAT.get(f) for f in self.formats) if tool)


def _has(text: str, terms: tuple[str, ...]) -> bool:
    """Word-boundary match so 'xls' does not fire inside 'xlsxish' and
    'md' does not fire inside 'admin'."""
    return any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) for term in terms)


def _detect_formats(text: str) -> list[str]:
    """Every format named in the text, in a stable order.

    One turn often asks for several at once ("export to excel, pdf and
    markdown"), and naming only the first would leave the model with an
    instruction narrower than the request.
    """
    formats: list[str] = []
    if _has(text, _PDF_TOKENS):
        if _has(text, _MERGE_VERBS):
            formats.append("pdf_merge")
        elif _has(text, _SPLIT_VERBS):
            formats.append("pdf_split")
        else:
            formats.append("pdf")
    if _has(text, _XLSX_TOKENS):
        formats.append("xlsx")
    if _has(text, _MD_TOKENS) or ".md" in text:
        formats.append("md")
    return formats


def detect_export_intent(text: str | None) -> ExportIntent | None:
    """Return the file request in ``text``, or None when there isn't one.

    Args:
        text: The user's own message. Never pass injected source text.
    """
    if not text or not text.strip():
        return None
    lowered = text.lower()

    formats = _detect_formats(lowered)
    fmt = formats[0] if formats else None
    has_strong = _has(lowered, _STRONG_VERBS)
    has_weak = _has(lowered, _WEAK_VERBS)
    has_file_noun = _has(lowered, _FILE_NOUNS)

    def _intent() -> ExportIntent:
        return ExportIntent(
            format=fmt or "unknown",
            tool=EXPORT_TOOL_BY_FORMAT.get(fmt or ""),
            formats=tuple(formats),
        )

    if fmt in ("pdf_merge", "pdf_split"):
        # "merge these PDFs" / "gabungkan pdf" already names both the
        # operation and the format; no separate export verb needed.
        return _intent()

    if fmt is not None:
        # A named format plus any intent to produce/obtain something, or a
        # token that can only mean a file.
        if has_strong or has_weak or has_file_noun or _has(lowered, _STANDALONE_TOKENS):
            return _intent()
        return None

    # No format named — only fire on an unambiguous export verb aimed at a
    # file, so "ekspor impor Indonesia" and "buatkan laporan" stay quiet.
    if has_strong and has_file_noun:
        return ExportIntent(format="unknown", tool=None)
    return None
