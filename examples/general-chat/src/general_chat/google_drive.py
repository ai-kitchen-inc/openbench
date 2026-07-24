"""Google Drive share-link ingestion for chat sources.

Turns a pasted Drive / Docs / Sheets / Slides share link into a stored
file that flows through the existing ``SourceParserRegistry`` pipeline.
Two access paths:

- Anonymous: public "anyone with the link" files via the
  ``uc?export=download`` endpoint (binary files) or the Docs/Sheets/
  Slides ``export`` endpoints (Google-native files).
- Authenticated: when the requesting user connected their Google
  account (see :mod:`general_chat.server.drive_auth`), the Drive v3 API
  is used with their credentials so private files also work.

Google-native files are exported to Office formats (Docs -> .docx,
Slides -> .pptx, Sheets -> .xlsx) because those already route through
the Docling / spreadsheet parsers; exporting Sheets to csv would drop
every sheet but the first.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from general_chat.sources import SourceRecord, source_record_from_file

if TYPE_CHECKING:
    from openbench.chat.files import StoredFile

    from general_chat.sources import SourceParserRegistry

logger = logging.getLogger(__name__)

_USER_AGENT = "OpenBench-GeneralChat/0.1"
_DOWNLOAD_TIMEOUT = 30

_DRIVE_HOSTS = {"drive.google.com", "docs.google.com", "drive.usercontent.google.com"}
_FILE_ID_RE = re.compile(r"[A-Za-z0-9_-]{10,}")
_DOC_PATH_KINDS = {
    "document": "document",
    "spreadsheets": "spreadsheet",
    "presentation": "presentation",
}

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

# doc_kind -> (anonymous export URL template, filename extension, mime)
EXPORT_FORMATS: dict[str, tuple[str, str, str]] = {
    "document": (
        "https://docs.google.com/document/d/{file_id}/export?format=docx",
        ".docx",
        _DOCX_MIME,
    ),
    "spreadsheet": (
        "https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx",
        ".xlsx",
        _XLSX_MIME,
    ),
    "presentation": (
        "https://docs.google.com/presentation/d/{file_id}/export?format=pptx",
        ".pptx",
        _PPTX_MIME,
    ),
}

# Google-native mime -> (export mime, filename extension) for the API path.
GOOGLE_NATIVE_EXPORT_MIME: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (_DOCX_MIME, ".docx"),
    "application/vnd.google-apps.spreadsheet": (_XLSX_MIME, ".xlsx"),
    "application/vnd.google-apps.presentation": (_PPTX_MIME, ".pptx"),
}

_SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

# Google-native mime -> DriveLink.doc_kind for folder children.
_GOOGLE_NATIVE_DOC_KINDS = {
    "application/vnd.google-apps.document": "document",
    "application/vnd.google-apps.spreadsheet": "spreadsheet",
    "application/vnd.google-apps.presentation": "presentation",
}

# Cap on files ingested from a single folder link (no subfolder recursion).
MAX_FOLDER_FILES = 10

_DRIVE_FILES_LIST_URL = "https://www.googleapis.com/drive/v3/files"

MSG_NEEDS_AUTH = (
    "Berkas Google Drive ini tidak dapat diakses publik. "
    "Hubungkan Google Drive untuk mengakses berkas privat."
)
MSG_FOLDER_NEEDS_AUTH = (
    "Isi folder tidak dapat dibaca. Hubungkan Google Drive untuk folder "
    "privat, atau bagikan folder secara publik (anyone with the link)."
)
MSG_FOLDER_NO_ACCESS = (
    "Akun Google yang terhubung tidak memiliki akses ke folder ini."
)
MSG_FOLDER_EMPTY = "Folder kosong atau tidak berisi berkas yang didukung."
MSG_UNSUPPORTED = "Tipe tautan Google ini tidak didukung sebagai sumber."
MSG_NO_ACCESS = "Akun Google yang terhubung tidak memiliki akses ke berkas ini."
MSG_RECONNECT = (
    "Sambungan Google Drive kedaluwarsa. Putuskan lalu hubungkan ulang Google Drive."
)
MSG_MISSING_DEPS = (
    "Integrasi Google Drive membutuhkan dependensi tambahan. "
    "Jalankan: pip install openbench[gdrive]"
)


class DriveAccessError(Exception):
    """A Drive link cannot be turned into a source.

    ``needs_auth`` marks failures that connecting a Google account
    would likely fix (private file fetched anonymously).
    """

    def __init__(self, message: str, *, needs_auth: bool = False):
        super().__init__(message)
        self.needs_auth = needs_auth


@dataclass(frozen=True)
class DriveLink:
    """A parsed Google Drive / Docs share link."""

    file_id: str
    doc_kind: str  # "file" | "document" | "spreadsheet" | "presentation" | "folder"
    resource_key: str | None
    original_url: str


@dataclass(frozen=True)
class DriveDownload:
    """Bytes fetched from Drive, ready for the file-store."""

    filename: str
    content: bytes
    mime_type: str


def parse_drive_url(url: str) -> DriveLink | None:
    """Return a :class:`DriveLink` for Drive/Docs links, None otherwise.

    ``None`` means "not a Drive link" — callers fall through to the
    plain URL pipeline. Recognized-but-unsupported Google links
    (folders, Forms) raise :class:`DriveAccessError` instead so the
    user gets an actionable message rather than login-page soup.
    """
    value = (url or "").strip()
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in _DRIVE_HOSTS:
        return None

    query = parse_qs(parsed.query)
    resource_key = (query.get("resourcekey") or [None])[0]
    query_id = (query.get("id") or [None])[0]

    # Drop Google's account-picker segments ("/u/<n>/") wherever they occur.
    raw_segments = [segment for segment in parsed.path.split("/") if segment]
    segments: list[str] = []
    skip_next = False
    for segment in raw_segments:
        if skip_next:
            skip_next = False
            continue
        if segment == "u":
            skip_next = True
            continue
        segments.append(segment)

    def _link(file_id: str | None, doc_kind: str) -> DriveLink | None:
        if not file_id or not _FILE_ID_RE.fullmatch(file_id):
            return None
        return DriveLink(
            file_id=file_id,
            doc_kind=doc_kind,
            resource_key=resource_key,
            original_url=value,
        )

    if host == "drive.usercontent.google.com":
        if segments[:1] == ["download"]:
            return _link(query_id, "file")
        return None

    if host == "drive.google.com":
        if segments[:2] == ["drive", "folders"] and len(segments) >= 3:
            return _link(segments[2], "folder")
        if segments[:3] == ["drive", "mobile", "folders"] and len(segments) >= 4:
            return _link(segments[3], "folder")
        if segments[:2] == ["file", "d"] and len(segments) >= 3:
            return _link(segments[2], "file")
        if segments[:1] == ["open"]:
            return _link(query_id, "file")
        if segments[:1] == ["uc"]:
            return _link(query_id, "file")
        return None

    # docs.google.com
    if segments[:1] == ["forms"]:
        raise DriveAccessError(MSG_UNSUPPORTED)
    if len(segments) >= 3 and segments[0] in _DOC_PATH_KINDS and segments[1] == "d":
        # "Published to the web" links (/d/e/<pubid>/pub...) serve plain
        # public HTML — let the normal URL pipeline handle them.
        if segments[2] == "e":
            return None
        return _link(segments[2], _DOC_PATH_KINDS[segments[0]])
    return None


def _safe_filename(name: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", (name or "").strip()).strip(". ")
    return cleaned or fallback


def _filename_from_content_disposition(header: str | None) -> str | None:
    if not header:
        return None
    match = re.search(r"filename\*=(?:UTF-8''|utf-8'')([^;]+)", header)
    if match:
        from urllib.parse import unquote

        return unquote(match.group(1).strip().strip('"'))
    match = re.search(r'filename="?([^";]+)"?', header)
    if match:
        return match.group(1).strip()
    return None


def download_public_drive_file(link: DriveLink, *, max_bytes: int) -> DriveDownload:
    """Fetch a public Drive file anonymously.

    Raises:
        DriveAccessError: the file is not publicly reachable
            (``needs_auth=True``) — Google answers with a login /
            request-access HTML page or a 4xx status.
        ValueError: the download exceeds ``max_bytes``.
    """
    import requests

    if link.doc_kind == "file":
        url = f"https://drive.google.com/uc?export=download&id={link.file_id}"
        default_name = f"drive-{link.file_id}"
        default_mime = "application/octet-stream"
    else:
        template, ext, mime = EXPORT_FORMATS[link.doc_kind]
        url = template.format(file_id=link.file_id)
        default_name = f"drive-{link.file_id}{ext}"
        default_mime = mime
    if link.resource_key:
        url += f"&resourcekey={link.resource_key}"

    response = requests.get(
        url,
        timeout=_DOWNLOAD_TIMEOUT,
        headers={"User-Agent": _USER_AGENT},
        stream=True,
        allow_redirects=True,
    )
    try:
        if response.status_code in {401, 403, 404}:
            raise DriveAccessError(MSG_NEEDS_AUTH, needs_auth=True)
        response.raise_for_status()
        content_type = (
            response.headers.get("content-type", "").split(";")[0].strip().lower()
        )
        if content_type.startswith("text/html"):
            # Login page, request-access page, or the virus-scan
            # interstitial for large public binaries: either way the
            # authenticated API path is the reliable route.
            raise DriveAccessError(MSG_NEEDS_AUTH, needs_auth=True)

        chunks: list[bytes] = []
        received = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            received += len(chunk)
            if received > max_bytes:
                raise ValueError(
                    f"Berkas Google Drive melebihi batas {max_bytes} byte."
                )
            chunks.append(chunk)
        content = b"".join(chunks)
    finally:
        response.close()

    filename = _safe_filename(
        _filename_from_content_disposition(response.headers.get("content-disposition"))
        or default_name,
        default_name,
    )
    mime_type = content_type or default_mime
    if mime_type in {"", "application/octet-stream"}:
        mime_type = default_mime
    return DriveDownload(filename=filename, content=content, mime_type=mime_type)


def _apply_resource_key(request: Any, link: DriveLink) -> Any:
    if link.resource_key:
        try:
            request.headers["X-Goog-Drive-Resource-Keys"] = (
                f"{link.file_id}/{link.resource_key}"
            )
        except Exception:  # pragma: no cover — header injection is best-effort
            pass
    return request


def download_drive_file_with_credentials(
    link: DriveLink,
    credentials: Any,
    *,
    max_bytes: int,
) -> DriveDownload:
    """Fetch a Drive file via the Drive v3 API with user credentials.

    Raises:
        DriveAccessError: dependency missing, no access (403/404), or
            expired/revoked credentials.
        ValueError: the download exceeds ``max_bytes``.
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        logger.warning("Drive OAuth configured but googleapiclient missing: %s", exc)
        raise DriveAccessError(MSG_MISSING_DEPS) from exc
    try:
        from google.auth.exceptions import RefreshError
    except ImportError:  # pragma: no cover — google-auth ships with the client
        RefreshError = ()  # type: ignore[assignment]

    try:
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        file_id = link.file_id
        request = _apply_resource_key(
            service.files().get(
                fileId=file_id,
                fields="id,name,mimeType,size,shortcutDetails",
                supportsAllDrives=True,
            ),
            link,
        )
        meta = request.execute()
        mime_type = str(meta.get("mimeType") or "application/octet-stream")
        if mime_type == _SHORTCUT_MIME:
            target_id = (meta.get("shortcutDetails") or {}).get("targetId")
            if not target_id:
                raise DriveAccessError(MSG_NO_ACCESS)
            file_id = str(target_id)
            meta = (
                service.files()
                .get(
                    fileId=file_id,
                    fields="id,name,mimeType,size",
                    supportsAllDrives=True,
                )
                .execute()
            )
            mime_type = str(meta.get("mimeType") or "application/octet-stream")

        name = str(meta.get("name") or f"drive-{link.file_id}")
        if mime_type in GOOGLE_NATIVE_EXPORT_MIME:
            export_mime, ext = GOOGLE_NATIVE_EXPORT_MIME[mime_type]
            media_request = service.files().export_media(
                fileId=file_id, mimeType=export_mime
            )
            if not name.lower().endswith(ext):
                name += ext
            out_mime = export_mime
        else:
            declared_size = int(meta.get("size") or 0)
            if declared_size > max_bytes:
                raise ValueError(
                    f"Berkas Google Drive melebihi batas {max_bytes} byte."
                )
            media_request = service.files().get_media(
                fileId=file_id, supportsAllDrives=True
            )
            out_mime = mime_type
        _apply_resource_key(media_request, link)

        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, media_request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
            if buffer.tell() > max_bytes:
                raise ValueError(
                    f"Berkas Google Drive melebihi batas {max_bytes} byte."
                )
        content = buffer.getvalue()
    except HttpError as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        logger.info("Drive API error for %s: %s", link.file_id, exc)
        if status in {403, 404}:
            raise DriveAccessError(MSG_NO_ACCESS) from exc
        raise DriveAccessError(f"Google Drive mengembalikan kesalahan: {exc}") from exc
    except RefreshError as exc:
        raise DriveAccessError(MSG_RECONNECT) from exc

    filename = _safe_filename(name, f"drive-{link.file_id}")
    return DriveDownload(filename=filename, content=content, mime_type=out_mime)


def _folder_child_link(file_id: str, mime_type: str) -> DriveLink | None:
    """Map a folder listing entry to an ingestible DriveLink, or None to skip."""
    if not file_id:
        return None
    if mime_type in _GOOGLE_NATIVE_DOC_KINDS:
        kind = _GOOGLE_NATIVE_DOC_KINDS[mime_type]
        path = {
            "document": "document",
            "spreadsheet": "spreadsheets",
            "presentation": "presentation",
        }[kind]
        url = f"https://docs.google.com/{path}/d/{file_id}/edit"
    elif mime_type.startswith("application/vnd.google-apps."):
        # Subfolders, forms, shortcuts, maps, ... — not ingestible here.
        return None
    else:
        kind = "file"
        url = f"https://drive.google.com/file/d/{file_id}/view"
    return DriveLink(file_id=file_id, doc_kind=kind, resource_key=None, original_url=url)


def list_drive_folder(
    link: DriveLink,
    *,
    credentials: Any | None = None,
    api_key: str | None = None,
) -> list[DriveLink]:
    """List a Drive folder's ingestible files (no subfolder recursion).

    Uses the Drive v3 API with the user's credentials when available
    (private + public folders); otherwise tries an anonymous API-key
    request, then Google's server-rendered ``embeddedfolderview`` page
    — the latter works for any "anyone with the link" folder with ZERO
    project configuration.

    Raises:
        DriveAccessError: folder not listable with the available access.
    """
    query = f"'{link.file_id}' in parents and trashed=false"
    fields = "files(id,name,mimeType)"
    page_size = MAX_FOLDER_FILES * 3  # headroom for skipped subfolders etc.

    if credentials is not None:
        try:
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            logger.warning("Drive OAuth configured but googleapiclient missing: %s", exc)
            raise DriveAccessError(MSG_MISSING_DEPS) from exc
        try:
            service = build("drive", "v3", credentials=credentials, cache_discovery=False)
            response = (
                service.files()
                .list(
                    q=query,
                    fields=fields,
                    pageSize=page_size,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            logger.info("Drive folder list error for %s: %s", link.file_id, exc)
            if status in {403, 404}:
                raise DriveAccessError(MSG_FOLDER_NO_ACCESS) from exc
            raise DriveAccessError(
                f"Google Drive mengembalikan kesalahan: {exc}"
            ) from exc
        return _children_from_listing(response)

    if api_key:
        import requests

        http_response = requests.get(
            _DRIVE_FILES_LIST_URL,
            params={
                "q": query,
                "key": api_key,
                "fields": fields,
                "pageSize": page_size,
            },
            timeout=_DOWNLOAD_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        )
        if http_response.status_code == 200:
            return _children_from_listing(http_response.json())
        logger.info(
            "Drive API-key folder listing failed (%s) for %s; trying embedded view",
            http_response.status_code,
            link.file_id,
        )
    return _list_folder_via_embedded_view(link)


def _children_from_listing(response: dict) -> list[DriveLink]:
    children: list[DriveLink] = []
    for item in response.get("files") or []:
        child = _folder_child_link(str(item.get("id") or ""), str(item.get("mimeType") or ""))
        if child is not None:
            children.append(child)
        if len(children) >= MAX_FOLDER_FILES:
            break
    return children


def _list_folder_via_embedded_view(link: DriveLink) -> list[DriveLink]:
    """Zero-configuration public-folder listing via ``embeddedfolderview``.

    Google still serves ``drive.google.com/embeddedfolderview?id=<id>``
    as plain server-rendered HTML for "anyone with the link" folders —
    no API key or OAuth required. Unofficial but long-stable; used only
    as the last fallback after the API paths.
    """
    import requests

    try:
        response = requests.get(
            f"https://drive.google.com/embeddedfolderview?id={link.file_id}",
            timeout=_DOWNLOAD_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        )
    except Exception as exc:
        raise DriveAccessError(MSG_FOLDER_NEEDS_AUTH, needs_auth=True) from exc
    if response.status_code != 200:
        raise DriveAccessError(MSG_FOLDER_NEEDS_AUTH, needs_auth=True)

    html_text = response.text
    children: list[DriveLink] = []
    seen: set[str] = set()
    pattern = (
        r"(?:drive\.google\.com/file/d/|"
        r"docs\.google\.com/(document|spreadsheets|presentation)/d/)"
        r"([A-Za-z0-9_-]{10,})"
    )
    for match in re.finditer(pattern, html_text):
        doc_path, file_id = match.group(1), match.group(2)
        if file_id in seen or file_id == link.file_id:
            continue
        seen.add(file_id)
        if doc_path:
            kind = {
                "document": "document",
                "spreadsheets": "spreadsheet",
                "presentation": "presentation",
            }[doc_path]
            url = f"https://docs.google.com/{doc_path}/d/{file_id}/edit"
        else:
            kind = "file"
            url = f"https://drive.google.com/file/d/{file_id}/view"
        children.append(
            DriveLink(file_id=file_id, doc_kind=kind, resource_key=None, original_url=url)
        )
        if len(children) >= MAX_FOLDER_FILES:
            break
    if not children:
        # Private folders serve a shell page with no file anchors.
        raise DriveAccessError(MSG_FOLDER_NEEDS_AUTH, needs_auth=True)
    return children


def drive_source_record(
    *,
    session_id: str,
    link: DriveLink,
    file_store: Any,
    parser: SourceParserRegistry,
    max_bytes: int,
    credentials: Any | None = None,
) -> tuple[SourceRecord, StoredFile | None]:
    """Download a Drive link and run it through the file-source pipeline.

    Returns ``(record, stored_file)``; ``stored_file`` is ``None`` when
    the download failed and the record carries ``status="failed"`` (the
    same failure shape as :func:`source_record_from_url`, so the UI
    renders it as-is).
    """
    if link.doc_kind == "folder":  # callers route folders to list_drive_folder
        return (
            SourceRecord.create(
                session_id=session_id,
                name=link.original_url,
                kind="url",
                mime_type="text/html",
                size_bytes=0,
                url=link.original_url,
                text="",
                status="failed",
                error=MSG_FOLDER_NEEDS_AUTH,
            ),
            None,
        )
    access = "public"
    try:
        if credentials is not None:
            try:
                download = download_drive_file_with_credentials(
                    link, credentials, max_bytes=max_bytes
                )
                access = "oauth"
            except DriveAccessError as exc:
                logger.info(
                    "Drive API download failed for %s (%s); trying public link",
                    link.file_id,
                    exc,
                )
                download = download_public_drive_file(link, max_bytes=max_bytes)
        else:
            download = download_public_drive_file(link, max_bytes=max_bytes)
    except Exception as exc:
        return (
            SourceRecord.create(
                session_id=session_id,
                name=link.original_url,
                kind="url",
                mime_type="text/html",
                size_bytes=0,
                url=link.original_url,
                text="",
                status="failed",
                error=str(exc),
            ),
            None,
        )

    stored = file_store.store(download.filename, download.content, download.mime_type)
    record = source_record_from_file(
        session_id=session_id,
        stored_file=stored,
        parser=parser,
        max_bytes=max_bytes,
    )
    metadata = dict(record.metadata or {})
    metadata.update(
        {
            "driveFileId": link.file_id,
            "driveUrl": link.original_url,
            "driveAccess": access,
        }
    )
    record.metadata = metadata
    return record, stored
