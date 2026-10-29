"""Upload latency guards for General Chat.

The production upload path was slow because (a) the forever-archive copy
was awaited before the response, (b) composer attachments stored to GCS on
the event loop, (c) the first upload after a restart also paid Docling's
model load, and (d) images ran the full PDF pipeline (table structure
included). These tests pin the fixes.
"""

from __future__ import annotations

import io
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat import extractor as extractor_mod  # noqa: E402
from general_chat import gcp_worker  # noqa: E402

pytestmark = pytest.mark.integration


class _SlowArchiver:
    def __init__(self, delay: float):
        self.delay = delay
        self.calls: list[str] = []
        self.done = threading.Event()

    def archive(self, filename, content, mime_type, *, user_id="default", session_id="default"):
        time.sleep(self.delay)
        self.calls.append(filename)
        self.done.set()
        return f"gs://archive/{filename}"


class TestArchiveDoesNotBlockUploads(unittest.TestCase):
    def _client(self, archiver: _SlowArchiver) -> TestClient:
        stack = ExitStack()
        self.addCleanup(stack.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmpdir = Path(tmp.name)
        stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(tmpdir / "storage"),
                    "GENERAL_CHAT_UPLOAD_DIR": str(tmpdir / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(tmpdir / "downloads"),
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                    "OPENBENCH_AUTH_DISABLED": "1",
                },
                clear=False,
            )
        )
        for name in ("GENERAL_CHAT_GCP_BUCKET", "GENERAL_CHAT_FIREBASE_PROJECT_ID"):
            environ.pop(name, None)
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
        stack.enter_context(
            patch("general_chat.server.app._build_attachment_archiver", return_value=archiver)
        )
        from general_chat.server.app import create_app

        # One portal for the whole test: a bare TestClient opens a new event
        # loop per request and shuts its default executor down on exit,
        # which would wait for the background archive and mask the fix.
        client = stack.enter_context(TestClient(create_app()))
        return client

    def test_source_upload_returns_before_archive_finishes(self):
        archiver = _SlowArchiver(delay=0.6)
        client = self._client(archiver)
        started = time.perf_counter()
        response = client.post(
            "/chat/upload",
            files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")},
            data={"sessionId": "s1"},
        )
        elapsed = time.perf_counter() - started
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "ready")
        self.assertLess(elapsed, 0.5, "upload waited for the archive copy")
        self.assertTrue(archiver.done.wait(3), "archive copy never ran")
        self.assertEqual(archiver.calls, ["note.txt"])

    def test_composer_attachment_returns_before_archive_finishes(self):
        archiver = _SlowArchiver(delay=0.6)
        client = self._client(archiver)
        started = time.perf_counter()
        response = client.post(
            "/chat/attachments/upload",
            files={"file": ("pic.png", io.BytesIO(b"png"), "image/png")},
            data={"sessionId": "s1"},
        )
        elapsed = time.perf_counter() - started
        self.assertEqual(response.status_code, 200, response.text)
        self.assertLess(elapsed, 0.5, "attachment waited for the archive copy")
        self.assertTrue(archiver.done.wait(3))
        self.assertEqual(archiver.calls, ["pic.png"])


def _fake_docling() -> dict[str, types.ModuleType]:
    """Minimal docling module tree capturing DocumentConverter kwargs."""
    pkg = types.ModuleType("docling")
    datamodel = types.ModuleType("docling.datamodel")
    base_models = types.ModuleType("docling.datamodel.base_models")
    pipeline_options = types.ModuleType("docling.datamodel.pipeline_options")
    document_converter = types.ModuleType("docling.document_converter")

    class InputFormat:
        PDF = "pdf"
        IMAGE = "image"

    class AcceleratorOptions:
        def __init__(self, num_threads=4):
            self.num_threads = num_threads

    class PdfPipelineOptions:
        def __init__(self, accelerator_options=None, do_ocr=True, do_table_structure=True):
            self.accelerator_options = accelerator_options
            self.do_ocr = do_ocr
            self.do_table_structure = do_table_structure

    class _FormatOption:
        def __init__(self, pipeline_options=None):
            self.pipeline_options = pipeline_options

    class DocumentConverter:
        instances: list = []

        def __init__(self, allowed_formats=None, format_options=None):
            self.format_options = format_options or {}
            self.initialized: list = []
            DocumentConverter.instances.append(self)

        def initialize_pipeline(self, input_format):
            self.initialized.append(input_format)

    base_models.InputFormat = InputFormat
    pipeline_options.AcceleratorOptions = AcceleratorOptions
    pipeline_options.PdfPipelineOptions = PdfPipelineOptions
    document_converter.DocumentConverter = DocumentConverter
    document_converter.PdfFormatOption = _FormatOption
    document_converter.ImageFormatOption = _FormatOption
    return {
        "docling": pkg,
        "docling.datamodel": datamodel,
        "docling.datamodel.base_models": base_models,
        "docling.datamodel.pipeline_options": pipeline_options,
        "docling.document_converter": document_converter,
    }


class TestConverterPipelineOptions(unittest.TestCase):
    def test_images_skip_table_structure_and_threads_match_cores(self):
        modules = _fake_docling()
        with (
            patch.dict(sys.modules, modules),
            patch.object(extractor_mod, "_converter", None),
            patch("os.cpu_count", return_value=6),
        ):
            converter = extractor_mod._get_converter()
        options = converter.format_options
        self.assertTrue(options["pdf"].pipeline_options.do_table_structure)
        self.assertFalse(options["image"].pipeline_options.do_table_structure)
        self.assertTrue(options["image"].pipeline_options.do_ocr)
        self.assertEqual(options["image"].pipeline_options.accelerator_options.num_threads, 6)
        self.assertEqual(options["pdf"].pipeline_options.accelerator_options.num_threads, 6)

    def test_warm_up_initializes_pdf_and_image_pipelines_once(self):
        modules = _fake_docling()
        with patch.dict(sys.modules, modules), patch.object(extractor_mod, "_converter", None):
            self.assertTrue(extractor_mod.warm_up_converter())
            converter = extractor_mod._get_converter()
            self.assertEqual(converter.initialized, ["pdf", "image"])
            # A second warm-up reuses the same converter.
            extractor_mod.warm_up_converter()
            self.assertIs(extractor_mod._get_converter(), converter)

    def test_warm_up_never_raises(self):
        with patch.object(extractor_mod, "_get_converter", side_effect=RuntimeError("no models")):
            self.assertFalse(extractor_mod.warm_up_converter())


class TestWorkerDefaults(unittest.TestCase):
    def test_default_in_flight_messages_follow_cpu_count(self):
        with patch("os.cpu_count", return_value=2):
            self.assertEqual(gcp_worker._default_max_messages(), 2)
        with patch("os.cpu_count", return_value=None):
            self.assertEqual(gcp_worker._default_max_messages(), 2)
        with patch("os.cpu_count", return_value=16):
            self.assertEqual(gcp_worker._default_max_messages(), 16)

    def test_warm_up_builds_parser_and_loads_models(self):
        with (
            patch.object(gcp_worker, "_source_parser", None),
            patch.object(gcp_worker, "warm_up_converter", return_value=True) as warm,
        ):
            gcp_worker._warm_up()
            self.assertIsNotNone(gcp_worker._source_parser)
        self.assertEqual(warm.call_count, 1)


if __name__ == "__main__":
    unittest.main()
