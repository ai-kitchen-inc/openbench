"""Async Cloud Storage source processing worker for General Chat.

Run on the GCE VM as a separate process:

    python -m general_chat.gcp_worker
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from general_chat.agent import get_persona_dir
from general_chat.extractor import DoclingContentExtractor
from general_chat.sources import (
    SourceParserRegistry,
    SourceRecord,
    build_source_store,
    kind_for_file,
    source_record_from_file,
)
from openbench.chat.files import StoredFile
from openbench.data.stores import ChunkingConfig, chunk_text
from openbench.integrations.gcp import GCSFileStore

logger = logging.getLogger(__name__)

_FILE_ID_RE = re.compile(r"/(file-[A-Za-z0-9_-]+)/")

# Reuse one parser/extractor across messages so the Docling converter (cached in
# extractor.py) is built once per process, not once per file.
_source_parser: SourceParserRegistry | None = None


def _get_source_parser() -> SourceParserRegistry:
    global _source_parser
    if _source_parser is None:
        _source_parser = SourceParserRegistry(document_extractor=DoclingContentExtractor())
    return _source_parser


@dataclass(frozen=True)
class GCSObjectEvent:
    bucket: str
    object_name: str
    generation: str | None = None


def process_gcs_object(
    event: GCSObjectEvent,
    *,
    source_store: Any | None = None,
    file_store: GCSFileStore | None = None,
    source_parser: SourceParserRegistry | None = None,
) -> SourceRecord | None:
    """Parse one finalized GCS object and update the matching source record."""
    if not _is_upload_object(event.object_name):
        logger.info("Skipping non-upload object: %s", event.object_name)
        return None

    file_id = _file_id_from_object(event.object_name)
    if not file_id:
        logger.warning("Skipping object without OpenBench file id: %s", event.object_name)
        return None

    user_id, session_id, filename = _path_parts(event.object_name)
    source_store = source_store or _default_source_store()
    file_store = file_store or _default_file_store(session_id=session_id)
    source_parser = source_parser or _get_source_parser()

    record = source_store.find_by_upload_file_id(file_id, session_id=session_id)
    if record is not None and _already_processed(record, event.generation):
        logger.info("Skipping already-processed upload: file_id=%s", file_id)
        return record

    # Address the blob by its exact object name (from the finalize event) to skip
    # the list_blobs scan in GCSFileStore._find_blob.
    stored = file_store.get_by_object(event.object_name)
    if stored is None:
        record = record or _placeholder_record(
            file_id=file_id,
            session_id=session_id,
            filename=filename,
            object_name=event.object_name,
            bucket=event.bucket,
        )
        record.status = "failed"
        record.error = "Cloud Storage object could not be verified."
        metadata = dict(record.metadata or {})
        metadata["parseStatus"] = "failed"
        record.metadata = metadata
        source_store.upsert(record)
        return record

    local_path = file_store.get_local_path_for_object(event.object_name, file_id)
    if local_path is None:
        record = record or _placeholder_record(
            file_id=file_id,
            session_id=session_id,
            filename=stored.name,
            object_name=event.object_name,
            bucket=event.bucket,
        )
        record.status = "failed"
        record.error = "Cloud Storage object could not be downloaded."
        metadata = dict(record.metadata or {})
        metadata["parseStatus"] = "failed"
        record.metadata = metadata
        source_store.upsert(record)
        return record

    parse_path = _mirror_upload_for_mcp(
        file_id=file_id,
        filename=stored.name,
        local_path=local_path,
    )
    stored_for_parse = StoredFile(
        id=stored.id,
        name=stored.name,
        path=parse_path,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        stored_at=stored.stored_at,
        web_view_link=stored.web_view_link,
    )
    parsed = source_record_from_file(
        session_id=session_id,
        stored_file=stored_for_parse,
        parser=source_parser,
        max_bytes=_max_source_bytes_for_worker(),
    )

    record = record or _placeholder_record(
        file_id=file_id,
        session_id=session_id,
        filename=stored.name,
        object_name=event.object_name,
        bucket=event.bucket,
    )
    record.name = parsed.name
    record.kind = parsed.kind
    record.mime_type = parsed.mime_type
    record.status = parsed.status
    record.error = parsed.error
    record.size_bytes = parsed.size_bytes
    record.url = parsed.url or stored.web_view_link or f"gs://{event.bucket}/{event.object_name}"
    record.text = parsed.text

    metadata = dict(record.metadata or {})
    metadata.update(parsed.metadata or {})
    metadata.update(
        {
            "fileId": file_id,
            "gcsBucket": event.bucket,
            "gcsObject": event.object_name,
            "gcsUserId": user_id,
            "uploadStatus": "uploaded",
            "parseStatus": "ready" if parsed.status == "ready" else "failed",
        }
    )
    if event.generation:
        metadata["processedGeneration"] = event.generation

    if parsed.status == "ready" and parsed.text.strip():
        chunks = chunk_text(
            parsed.text,
            ChunkingConfig(
                chunk_size=_env_int("GENERAL_CHAT_GCP_CHUNK_SIZE", 1000),
                chunk_overlap=_env_int("GENERAL_CHAT_GCP_CHUNK_OVERLAP", 200),
            ),
        )
        derived_object = file_store.object_name_for_derived(
            file_id=file_id,
            session_id=session_id,
            user_id=user_id,
            derived_prefix=os.getenv("GENERAL_CHAT_GCP_DERIVED_PREFIX", "derived"),
        )
        file_store.upload_text_object(
            object_name=derived_object,
            text=parsed.text,
            metadata={
                "openbench_file_id": file_id,
                "openbench_session_id": session_id,
                "openbench_source_id": record.id,
            },
        )
        metadata["derivedObject"] = derived_object
        metadata["chunkCount"] = str(len(chunks))

    record.metadata = metadata
    source_store.upsert(record)
    logger.info(
        "Processed GCS upload file_id=%s session=%s status=%s",
        file_id,
        session_id,
        record.status,
    )
    return record


def run_pubsub_worker() -> None:
    """Run a blocking Pub/Sub pull subscriber."""
    subscription = os.environ["GENERAL_CHAT_GCP_PUBSUB_SUBSCRIPTION"]
    try:
        from google.cloud import pubsub_v1
    except ImportError as exc:
        raise ImportError(
            "Pub/Sub worker requires google-cloud-pubsub. Install openbench[gcp]."
        ) from exc

    subscriber = pubsub_v1.SubscriberClient()
    stop = threading.Event()

    def _stop(_signum, _frame) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    def callback(message) -> None:
        try:
            event = event_from_pubsub_message(message)
            process_gcs_object(event)
        except Exception:
            logger.exception("Failed to process Pub/Sub message")
            message.nack()
            return
        message.ack()

    # Bound in-flight messages so the client's lease-extension threads are not
    # starved by long CPU callbacks, and so multiple files overlap on I/O.
    flow_control = pubsub_v1.types.FlowControl(
        max_messages=_env_int("GENERAL_CHAT_PUBSUB_MAX_MESSAGES", 8)
    )
    future = subscriber.subscribe(subscription, callback=callback, flow_control=flow_control)
    logger.info("Listening for GCS finalize events on %s", subscription)
    try:
        while not stop.is_set():
            stop.wait(1)
    finally:
        future.cancel()
        subscriber.close()


def event_from_pubsub_message(message: Any) -> GCSObjectEvent:
    attrs = getattr(message, "attributes", {}) or {}
    bucket = attrs.get("bucketId")
    object_name = attrs.get("objectId")
    generation = attrs.get("objectGeneration")
    if not bucket or not object_name:
        payload = json.loads(message.data.decode("utf-8")) if getattr(message, "data", None) else {}
        bucket = bucket or payload.get("bucket")
        object_name = object_name or payload.get("name")
        generation = generation or str(payload.get("generation") or "")
    if not bucket or not object_name:
        raise ValueError("Pub/Sub message does not include bucketId/objectId.")
    return GCSObjectEvent(bucket=str(bucket), object_name=str(object_name), generation=generation or None)


def _default_source_store():
    root = os.getenv(
        "GENERAL_CHAT_STORAGE_ROOT",
        str(get_persona_dir().parent / ".openbench"),
    )
    return build_source_store(root)


def _default_file_store(*, session_id: str) -> GCSFileStore:
    return GCSFileStore(
        os.environ["GENERAL_CHAT_GCP_BUCKET"],
        prefix=os.getenv("GENERAL_CHAT_GCP_UPLOADS_PREFIX", "uploads"),
        user_id=os.getenv("GENERAL_CHAT_GCP_USER_ID", "default"),
        session_id=session_id,
        cache_root=os.getenv("GENERAL_CHAT_GCP_CACHE_ROOT"),
    )


def _placeholder_record(
    *,
    file_id: str,
    session_id: str,
    filename: str,
    object_name: str,
    bucket: str,
) -> SourceRecord:
    # The worker has no request identity, so a fallback-created record gets
    # owner="" and is invisible to every user. In practice unreachable:
    # /chat/uploads/initiate pre-creates the owner-stamped record, and the
    # worker's unscoped upsert never overwrites an existing row's owner.
    return SourceRecord.create(
        session_id=session_id,
        name=Path(filename).name or "unnamed",
        kind=kind_for_file(filename, "application/octet-stream"),
        mime_type="application/octet-stream",
        size_bytes=0,
        url=f"gs://{bucket}/{object_name}",
        text="",
        status="processing",
        metadata={
            "fileId": file_id,
            "gcsBucket": bucket,
            "gcsObject": object_name,
            "uploadStatus": "uploaded",
            "parseStatus": "queued",
        },
    )


def _path_parts(object_name: str) -> tuple[str, str, str]:
    parts = object_name.split("/")
    if len(parts) >= 5:
        return parts[1], parts[2], parts[-1]
    return "default", "default", parts[-1] if parts else "unnamed"


def _file_id_from_object(object_name: str) -> str | None:
    match = _FILE_ID_RE.search(f"/{object_name}")
    return match.group(1) if match else None


def _is_upload_object(object_name: str) -> bool:
    prefix = os.getenv("GENERAL_CHAT_GCP_UPLOADS_PREFIX", "uploads").strip("/")
    return object_name.startswith(f"{prefix}/")


def _already_processed(record: SourceRecord, generation: str | None) -> bool:
    if record.status != "ready":
        return False
    if not generation:
        return True
    metadata = record.metadata or {}
    return metadata.get("processedGeneration") == generation


def _max_source_bytes_for_worker() -> int:
    return _env_int("GENERAL_CHAT_GCP_MAX_SOURCE_BYTES", 250 * 1024 * 1024)


def _mirror_upload_for_mcp(*, file_id: str, filename: str, local_path: str) -> str:
    upload_dir = os.getenv("GENERAL_CHAT_UPLOAD_DIR")
    if not upload_dir:
        return local_path
    destination = Path(upload_dir) / file_id / Path(filename).name
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = Path(local_path)
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
        return str(destination)
    except Exception as exc:
        logger.warning("Failed to mirror GCS upload for MCP file_id=%s error=%s", file_id, exc)
        return local_path


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    run_pubsub_worker()
