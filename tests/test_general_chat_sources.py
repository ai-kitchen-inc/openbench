"""Tests for General Chat source-context injection."""

from __future__ import annotations

import json
import sys
import types
import unittest
import uuid
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

from openbench.chat import render_queue
from openbench.chat.engine import ChatEngine
from openbench.chat.files import StoredFile
from openbench.core.abstractions import (
    Agent,
    ExecutionContext,
    ExecutionResult,
    LLMProvider,
    LLMResponse,
    Tool,
)
from openbench.intelligence import BaseAgent
from openbench.intelligence.base import Message, MessageRole
from openbench.intelligence.memory import SQLiteMemoryStore

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.agent import _ImageSearchRenderTool, _mcp_registry_root  # noqa: E402
from general_chat.extractor import DoclingContentExtractor  # noqa: E402
from general_chat.server.app import _resolve_mime, _resolve_request_session_id  # noqa: E402
from general_chat.server.handler import GeneralChatHandler  # noqa: E402
from general_chat.sources import (  # noqa: E402
    SearchDiscoveryResponse,
    SearchDiscoveryResult,
    SearchProviderFailure,
    SearchProviderResponse,
    SourceParserRegistry,
    SourceRecord,
    SourceStore,
    TavilySearchDiscoveryProvider,
    clean_html_text,
    source_record_from_file,
    source_record_from_text,
    source_record_from_url,
    validate_file_source,
    validate_url,
)


class MockAgent(Agent):
    def __init__(self):
        self.context: ExecutionContext | None = None

    @property
    def agent_type(self) -> str:
        return "mock"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        self.context = context
        return ExecutionResult(output=context.goal, status="success", metadata={})

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0


class MockLLMProvider(LLMProvider):
    def __init__(self, response: str = "Mock response"):
        self.response = response
        self.prompts: list[object] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    def generate(self, prompt, model: str = "", **params) -> LLMResponse:
        self.prompts.append(prompt)
        return LLMResponse(text=self.response, model=model, tokens_used=0, cost=0.0)

    def generate_stream(self, prompt, model: str = "", **params):
        self.prompts.append(prompt)
        yield self.response


class TestGeneralChatSources(unittest.TestCase):
    def test_resolve_request_session_id_prefers_forwarded_session(self):
        body = {
            "threadId": "transport-thread",
            "forwardedProps": {"sessionId": "chat-session"},
        }

        self.assertEqual(_resolve_request_session_id(body), "chat-session")

    def test_resolve_request_session_id_falls_back_to_thread_id(self):
        self.assertEqual(
            _resolve_request_session_id({"threadId": "transport-thread"}),
            "transport-thread",
        )

    def test_doc_context_becomes_structured_attachment_not_user_text(self):
        agent = MockAgent()
        engine = ChatEngine(agent=agent)
        handler = GeneralChatHandler(
            engine=engine,
            db_path=":memory:",
            doc_context="## milestones.docx\n\nMilestone A: ship the parser.",
        )

        content, attachments = handler._extract_content(
            {
                "messages": [
                    {
                        "id": "m1",
                        "role": "user",
                        "content": "summarise the milestones.docx",
                    }
                ],
                "forwardedProps": {"sessionId": "chat-session"},
            }
        )

        self.assertEqual(content, "summarise the milestones.docx")
        self.assertIsNotNone(attachments)
        assert attachments is not None
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].name, "milestones.docx")
        self.assertIn("## milestones.docx", attachments[0].extracted_text or "")

        engine._execute_agent(content, None, attachments=attachments)

        self.assertIsNotNone(agent.context)
        assert agent.context is not None
        self.assertEqual(agent.context.goal, "summarise the milestones.docx")
        self.assertIn("attachments", agent.context.data)
        self.assertEqual(agent.context.data["attachments"][0]["name"], "milestones.docx")
        self.assertIn("Milestone A", agent.context.data["attachments"][0]["content"])

    def test_source_records_become_structured_attachments(self):
        agent = MockAgent()
        engine = ChatEngine(agent=agent)
        source = SourceRecord.create(
            session_id="chat-session",
            name="notes.txt",
            kind="text",
            mime_type="text/plain",
            size_bytes=20,
            text="Alpha roadmap milestone.",
        )
        handler = GeneralChatHandler(
            engine=engine,
            db_path=":memory:",
            source_records=[source],
        )

        content, attachments = handler._extract_content(
            {
                "messages": [{"id": "m1", "role": "user", "content": "what is alpha?"}],
                "forwardedProps": {"sessionId": "chat-session"},
            }
        )

        self.assertEqual(content, "what is alpha?")
        self.assertIsNotNone(attachments)
        assert attachments is not None
        self.assertEqual(attachments[0].name, "notes.txt")
        self.assertIn("Alpha roadmap", attachments[0].extracted_text or "")

    def test_forwarded_draft_attachments_are_preserved_without_sources(self):
        agent = MockAgent()
        engine = ChatEngine(agent=agent)
        handler = GeneralChatHandler(engine=engine, db_path=":memory:", source_records=[])

        content, attachments = handler._extract_content(
            {
                "messages": [{"id": "m1", "role": "user", "content": "summarize this"}],
                "forwardedProps": {
                    "sessionId": "chat-session",
                    "attachments": [
                        {
                            "id": "draft-1",
                            "type": "file",
                            "name": "draft.txt",
                            "url": "/uploads/draft-1/draft.txt",
                            "mimeType": "text/plain",
                            "extractedText": "Draft attachment context.",
                        }
                    ],
                },
            }
        )

        self.assertEqual(content, "summarize this")
        self.assertIsNotNone(attachments)
        assert attachments is not None
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].name, "draft.txt")
        self.assertIn("Draft attachment context", attachments[0].extracted_text or "")

        engine._execute_agent(content, None, attachments=attachments)

        self.assertIsNotNone(agent.context)
        assert agent.context is not None
        self.assertEqual(agent.context.data["attachments"][0]["name"], "draft.txt")

    def test_forwarded_draft_image_attachment_includes_mcp_path(self):
        agent = MockAgent()
        engine = ChatEngine(agent=agent)
        handler = GeneralChatHandler(engine=engine, db_path=":memory:", source_records=[])

        content, attachments = handler._extract_content(
            {
                "messages": [{"id": "m1", "role": "user", "content": "count dogs"}],
                "forwardedProps": {
                    "sessionId": "chat-session",
                    "attachments": [
                        {
                            "id": "file-7",
                            "type": "image",
                            "name": "dogs.png",
                            "url": "/uploads/file-7/dogs.png",
                            "mimeType": "image/png",
                            "sizeBytes": 1234,
                        }
                    ],
                },
            }
        )

        self.assertEqual(content, "count dogs")
        self.assertIsNotNone(attachments)
        assert attachments is not None
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].type, "image")
        self.assertEqual(attachments[0].path, "/general-chat/uploads/file-7/dogs.png")
        self.assertIn(
            'image_path="/general-chat/uploads/file-7/dogs.png"',
            attachments[0].extracted_text or "",
        )
        self.assertIn(
            "sam_segmentation.count_objects_with_sam3",
            attachments[0].extracted_text or "",
        )
        self.assertNotIn("image_base64", attachments[0].extracted_text or "")

        engine._execute_agent(content, None, attachments=attachments)

        self.assertIsNotNone(agent.context)
        assert agent.context is not None
        self.assertEqual(
            agent.context.data["attachments"][0]["path"],
            "/general-chat/uploads/file-7/dogs.png",
        )

    def test_forwarded_draft_attachments_are_combined_with_source_records(self):
        agent = MockAgent()
        engine = ChatEngine(agent=agent)
        source = SourceRecord.create(
            session_id="chat-session",
            name="current.txt",
            kind="text",
            mime_type="text/plain",
            size_bytes=20,
            text="Current source only.",
        )
        handler = GeneralChatHandler(
            engine=engine,
            db_path=":memory:",
            source_records=[source],
        )

        _content, attachments = handler._extract_content(
            {
                "messages": [{"id": "m1", "role": "user", "content": "what is current?"}],
                "forwardedProps": {
                    "sessionId": "chat-session",
                    "attachments": [
                        {
                            "id": "draft",
                            "type": "file",
                            "name": "draft.txt",
                            "url": "/uploads/draft/draft.txt",
                            "mimeType": "text/plain",
                            "extractedText": "Draft source should be available.",
                        }
                    ],
                },
            }
        )

        self.assertIsNotNone(attachments)
        assert attachments is not None
        joined = "\n".join(attachment.extracted_text or "" for attachment in attachments)
        self.assertIn("Current source only", joined)
        self.assertIn("Draft source should be available", joined)

    def test_image_source_attachment_includes_mcp_path(self):
        agent = MockAgent()
        engine = ChatEngine(agent=agent)
        source = SourceRecord.create(
            session_id="chat-session",
            name="photo.jpg",
            kind="image",
            mime_type="image/jpeg",
            size_bytes=20,
            url="/uploads/file-1/photo.jpg",
            text="Image source: photo.jpg",
            metadata={"imageSearchPath": "/general-chat/uploads/file-1/photo.jpg"},
        )
        handler = GeneralChatHandler(
            engine=engine,
            db_path=":memory:",
            source_records=[source],
        )

        content, attachments = handler._extract_content(
            {
                "messages": [{"id": "m1", "role": "user", "content": "find similar images"}],
                "forwardedProps": {"sessionId": "chat-session"},
            }
        )

        self.assertEqual(content, "find similar images")
        self.assertIsNotNone(attachments)
        assert attachments is not None
        self.assertEqual(attachments[0].type, "image")
        self.assertEqual(attachments[0].path, "/general-chat/uploads/file-1/photo.jpg")
        self.assertIn("/general-chat/uploads/file-1/photo.jpg", attachments[0].extracted_text or "")

        engine._execute_agent(content, None, attachments=attachments)

        self.assertIsNotNone(agent.context)
        assert agent.context is not None
        self.assertEqual(
            agent.context.data["attachments"][0]["path"], "/general-chat/uploads/file-1/photo.jpg"
        )

    def test_similar_image_prompt_is_allowed_for_image_source(self):
        llm = MockLLMProvider("I will search similar images.")
        agent = BaseAgent(goal="General chat")
        agent._llm = llm
        source = SourceRecord.create(
            session_id="chat-session",
            name="photo.jpg",
            kind="image",
            mime_type="image/jpeg",
            size_bytes=20,
            url="/uploads/file-1/photo.jpg",
            text="Image source: photo.jpg",
            metadata={"imageSearchPath": "/general-chat/uploads/file-1/photo.jpg"},
        )
        engine = ChatEngine(agent=agent)
        handler = GeneralChatHandler(
            engine=engine,
            db_path=":memory:",
            source_records=[source],
        )
        content, attachments = handler._extract_content(
            {
                "messages": [{"id": "m1", "role": "user", "content": "top 10 similar images"}],
                "forwardedProps": {"sessionId": "chat-session"},
            }
        )
        request_agent = handler._create_request_agent()

        result = engine._execute_agent(content, None, attachments=attachments, agent=request_agent)

        self.assertEqual(result.output, "I will search similar images.")
        self.assertTrue(llm.prompts)

    def test_image_search_startup_script_exposes_query_only_tools(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "general-chat"
            / "scripts"
            / "run_with_image_search_mcp.ps1"
        )
        content = script.read_text(encoding="utf-8")

        allowlist_line = next(
            line for line in content.splitlines() if "GENERAL_CHAT_MCP_APPROVED_TOOLS" in line
        )
        self.assertIn("image_search.list_index_stats", allowlist_line)
        self.assertIn("image_search.search_similar_images", allowlist_line)
        self.assertNotIn("image_search.index_images", allowlist_line)
        self.assertNotIn("image_search.rebuild_index", allowlist_line)
        self.assertIn('GENERAL_CHAT_MCP_REGISTRY_ENABLED = "0"', content)

    def test_sam_segmentation_startup_script_exposes_count_tool_only(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "general-chat"
            / "scripts"
            / "run_with_sam_segmentation_mcp.ps1"
        )
        content = script.read_text(encoding="utf-8")

        allowlist_line = next(
            line for line in content.splitlines() if "GENERAL_CHAT_MCP_APPROVED_TOOLS" in line
        )
        self.assertIn("sam_segmentation.count_objects_with_sam3", allowlist_line)
        self.assertNotIn("sam_segmentation.service_info", allowlist_line)
        self.assertIn('GENERAL_CHAT_MCP_REGISTRY_ENABLED = "0"', content)
        self.assertIn("baked into openbench/sam-segmentation-mcp:cpu", content)
        self.assertNotIn("SAM_SEGMENTATION_MCP_MODELS_PATH", content)

    def test_sam_segmentation_build_script_uses_hf_cli_token(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "sam-segmentation-mcp"
            / "scripts"
            / "build_with_sam3.ps1"
        )
        content = script.read_text(encoding="utf-8")

        self.assertIn("hf auth token", content)
        self.assertIn("Docker build secret", content)
        self.assertIn("docker compose", content)

    def test_mcp_registry_root_can_be_disabled_for_dedicated_mcp_scripts(self):
        with patch.dict(
            environ,
            {
                "GENERAL_CHAT_MCP_REGISTRY_ROOT": "C:/tmp/openbench-registry",
                "GENERAL_CHAT_MCP_REGISTRY_ENABLED": "0",
            },
            clear=False,
        ):
            self.assertIsNone(_mcp_registry_root())

    def test_plain_text_source_success(self):
        parser = SourceParserRegistry()
        record = source_record_from_text(
            session_id="s1",
            name="Paste",
            text="Useful pasted source",
            parser=parser,
        )

        self.assertEqual(record.status, "ready")
        self.assertEqual(record.kind, "text")
        self.assertEqual(record.text, "Useful pasted source")

    def test_plain_text_source_empty_fails(self):
        parser = SourceParserRegistry()
        record = source_record_from_text(
            session_id="s1",
            name="Paste",
            text="   ",
            parser=parser,
        )

        self.assertEqual(record.status, "failed")
        self.assertIn("empty", record.error or "")

    def test_file_type_and_size_validation(self):
        validate_file_source("report.pdf", "application/pdf", 10, max_bytes=20)
        validate_file_source("photo.jpg", "image/jpeg", 10, max_bytes=20)
        validate_file_source("graphic.webp", "image/webp", 10, max_bytes=20)

        with self.assertRaisesRegex(ValueError, "Unsupported"):
            validate_file_source("archive.zip", "application/zip", 10, max_bytes=20)

        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_file_source("report.pdf", "application/pdf", 21, max_bytes=20)

    def test_parser_failure_creates_failed_file_record(self):
        parser = SourceParserRegistry()
        parser.parse_file = Mock(side_effect=ValueError("parse exploded"))
        stored = StoredFile(
            id="file-1",
            name="report.pdf",
            path="missing.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            stored_at="2026-01-01T00:00:00+00:00",
        )

        record = source_record_from_file(
            session_id="s1",
            stored_file=stored,
            parser=parser,
            max_bytes=100,
        )

        self.assertEqual(record.status, "failed")
        self.assertIn("parse exploded", record.error or "")

    def test_docling_document_types_route_to_document_extractor(self):
        extractor = Mock()
        extractor.extract.return_value = "Docling markdown"
        parser = SourceParserRegistry(document_extractor=extractor)
        stored = StoredFile(
            id="file-1",
            name="slides.pptx",
            path="slides.pptx",
            mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            size_bytes=10,
            stored_at="2026-01-01T00:00:00+00:00",
        )

        parsed = parser.parse_file(stored)
        self.assertEqual(parsed.text, "Docling markdown")
        extractor.extract.assert_called_once_with(stored)

    def test_pdf_falls_back_to_pypdf_when_docling_fails(self):
        extractor = DoclingContentExtractor()
        stored = StoredFile(
            id="file-1",
            name="report.pdf",
            path="report.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            stored_at="2026-01-01T00:00:00+00:00",
        )
        converter_instance = Mock()
        converter_instance.convert.side_effect = RuntimeError("docling failed")
        docling_module = types.ModuleType("docling.document_converter")
        docling_module.DocumentConverter = Mock(return_value=converter_instance)
        pypdf_module = types.ModuleType("pypdf")
        pypdf_module.PdfReader = Mock(
            return_value=types.SimpleNamespace(
                pages=[
                    types.SimpleNamespace(extract_text=Mock(return_value="Alpha page")),
                    types.SimpleNamespace(extract_text=Mock(return_value="Beta page")),
                ]
            )
        )

        with patch.dict(
            sys.modules,
            {
                "docling.document_converter": docling_module,
                "pypdf": pypdf_module,
            },
        ):
            text = extractor.extract(stored)

        self.assertIn("### Page 1", text)
        self.assertIn("Alpha page", text)
        self.assertIn("### Page 2", text)
        self.assertIn("Beta page", text)

    def test_xlsx_multi_sheet_extraction(self):
        try:
            import pandas as pd
        except ImportError:
            self.skipTest("pandas is not installed")

        tmpdir = Path("tests/.tmp") / f"xlsx-{uuid.uuid4().hex}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        path = tmpdir / "book.xlsx"
        try:
            with pd.ExcelWriter(path) as writer:
                pd.DataFrame({"Name": ["Ada", "Grace"], "Score": [10, 11]}).to_excel(
                    writer,
                    sheet_name="People",
                    index=False,
                )
                pd.DataFrame({"Item": ["Widget"]}).to_excel(
                    writer,
                    sheet_name="Inventory",
                    index=False,
                )
            stored = StoredFile(
                id="file-1",
                name="book.xlsx",
                path=str(path),
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                size_bytes=path.stat().st_size,
                stored_at="2026-01-01T00:00:00+00:00",
            )

            parsed = SourceParserRegistry().parse_file(stored)
        finally:
            if path.exists():
                path.unlink()
            if tmpdir.exists():
                tmpdir.rmdir()

        text = parsed.text
        self.assertIn("Sheet: People", text)
        self.assertIn("Ada", text)
        self.assertIn("Sheet: Inventory", text)
        self.assertIn("Widget", text)

    def test_png_ocr_success_creates_searchable_image_source(self):
        extractor = Mock()
        extractor.extract_image.return_value = {
            "description": "PNG image source diagram.png (640x480) with OCR-detected text.",
            "ocr_text": "Launch checklist",
            "search_text": "## diagram.png\n\n### Image summary\nPNG image source diagram.png (640x480) with OCR-detected text.\n\n### Detected text\nLaunch checklist",
            "metadata": {"format": "png", "width": 640, "height": 480},
        }
        parser = SourceParserRegistry(document_extractor=extractor)
        stored = StoredFile(
            id="file-2",
            name="diagram.png",
            path="diagram.png",
            mime_type="image/png",
            size_bytes=24,
            stored_at="2026-01-01T00:00:00+00:00",
        )

        record = source_record_from_file(
            session_id="s1",
            stored_file=stored,
            parser=parser,
            max_bytes=1024,
        )

        self.assertEqual(record.status, "ready")
        self.assertEqual(record.kind, "image")
        self.assertIn("Launch checklist", record.text)
        self.assertEqual(record.metadata["width"], 640)
        self.assertEqual(
            record.metadata["imageSearchPath"],
            "/general-chat/uploads/file-2/diagram.png",
        )
        self.assertEqual(
            record.metadata["samSegmentationPath"],
            "/general-chat/uploads/file-2/diagram.png",
        )
        self.assertEqual(record.metadata["imageSearchPreviewUrl"], "/uploads/file-2/diagram.png")
        self.assertIn("sam_segmentation.count_objects_with_sam3", record.text)
        self.assertIn("concept", record.text)
        self.assertIn("OCR-detected text", str(record.metadata["description"]))
        extractor.extract_image.assert_called_once_with(stored)

    def test_png_ocr_failure_still_creates_searchable_image_source(self):
        extractor = Mock()
        extractor.extract_image.side_effect = ValueError(
            "Image extraction failed: OCR pipeline unavailable"
        )
        parser = SourceParserRegistry(document_extractor=extractor)
        stored = StoredFile(
            id="file-3",
            name="scan.png",
            path="scan.png",
            mime_type="image/png",
            size_bytes=24,
            stored_at="2026-01-01T00:00:00+00:00",
        )

        record = source_record_from_file(
            session_id="s1",
            stored_file=stored,
            parser=parser,
            max_bytes=1024,
        )

        self.assertEqual(record.status, "ready")
        self.assertEqual(record.kind, "image")
        self.assertIsNone(record.error)
        self.assertIn("OCR pipeline unavailable", record.text)
        self.assertEqual(
            record.metadata["imageSearchPath"],
            "/general-chat/uploads/file-3/scan.png",
        )
        self.assertEqual(
            record.metadata["samSegmentationPath"],
            "/general-chat/uploads/file-3/scan.png",
        )
        self.assertEqual(record.metadata["imageSearchPreviewUrl"], "/uploads/file-3/scan.png")

    def test_jpeg_ocr_success_creates_searchable_image_source(self):
        extractor = Mock()
        extractor.extract_image.return_value = {
            "description": "JPEG image source photo.jpg (640x480) with OCR-detected text.",
            "ocr_text": "Roadmap draft",
            "search_text": "## photo.jpg\n\n### Image summary\nJPEG image source photo.jpg (640x480) with OCR-detected text.\n\n### Detected text\nRoadmap draft",
            "metadata": {"format": "jpeg", "width": 640, "height": 480},
        }
        parser = SourceParserRegistry(document_extractor=extractor)
        stored = StoredFile(
            id="file-4",
            name="photo.jpg",
            path="photo.jpg",
            mime_type="image/jpeg",
            size_bytes=24,
            stored_at="2026-01-01T00:00:00+00:00",
        )

        record = source_record_from_file(
            session_id="s1",
            stored_file=stored,
            parser=parser,
            max_bytes=1024,
        )

        self.assertEqual(record.status, "ready")
        self.assertEqual(record.kind, "image")
        self.assertIn("Roadmap draft", record.text)
        self.assertEqual(record.metadata["format"], "jpeg")
        extractor.extract_image.assert_called_once_with(stored)

    def test_webp_ocr_success_creates_searchable_image_source(self):
        extractor = Mock()
        extractor.extract_image.return_value = {
            "description": "WEBP image source poster.webp (1200x675) with OCR-detected text.",
            "ocr_text": "Q2 campaign",
            "search_text": "## poster.webp\n\n### Image summary\nWEBP image source poster.webp (1200x675) with OCR-detected text.\n\n### Detected text\nQ2 campaign",
            "metadata": {"format": "webp", "width": 1200, "height": 675},
        }
        parser = SourceParserRegistry(document_extractor=extractor)
        stored = StoredFile(
            id="file-5",
            name="poster.webp",
            path="poster.webp",
            mime_type="image/webp",
            size_bytes=24,
            stored_at="2026-01-01T00:00:00+00:00",
        )

        record = source_record_from_file(
            session_id="s1",
            stored_file=stored,
            parser=parser,
            max_bytes=1024,
        )

        self.assertEqual(record.status, "ready")
        self.assertEqual(record.kind, "image")
        self.assertIn("Q2 campaign", record.text)
        self.assertEqual(record.metadata["format"], "webp")
        extractor.extract_image.assert_called_once_with(stored)

    def test_invalid_image_type_is_rejected(self):
        parser = SourceParserRegistry()
        stored = StoredFile(
            id="file-6",
            name="animation.gif",
            path="animation.gif",
            mime_type="image/gif",
            size_bytes=24,
            stored_at="2026-01-01T00:00:00+00:00",
        )

        record = source_record_from_file(
            session_id="s1",
            stored_file=stored,
            parser=parser,
            max_bytes=1024,
        )

        self.assertEqual(record.status, "failed")
        self.assertIn("Unsupported", record.error or "")

    def test_resolve_mime_recognizes_supported_image_extensions(self):
        self.assertEqual(_resolve_mime("photo.jpg", "application/octet-stream"), "image/jpeg")
        self.assertEqual(_resolve_mime("photo.jpeg", "application/octet-stream"), "image/jpeg")
        self.assertEqual(_resolve_mime("poster.webp", "application/octet-stream"), "image/webp")

    def test_url_validation(self):
        self.assertEqual(validate_url("https://example.com/page"), "https://example.com/page")
        with self.assertRaisesRegex(ValueError, "http or https"):
            validate_url("ftp://example.com")
        with self.assertRaisesRegex(ValueError, "Local"):
            validate_url("http://localhost:8000")

    def test_website_ingestion_success_with_mocked_fetch(self):
        parser = SourceParserRegistry()
        html = "<html><head><title>Example Title</title></head><body><script>x()</script><p>Hello web source.</p></body></html>"
        with (
            patch.object(parser, "_parse_url_with_docling", side_effect=RuntimeError("skip")),
            patch("general_chat.sources.fetch_url_text", return_value=(html, "text/html")),
        ):
            record = source_record_from_url(
                session_id="s1",
                url="https://example.com",
                parser=parser,
                max_bytes=1000,
            )

        self.assertEqual(record.status, "ready")
        self.assertEqual(record.name, "Example Title")
        self.assertIn("Hello web source", record.text)

    def test_website_ingestion_failure_is_recorded(self):
        parser = SourceParserRegistry()
        record = source_record_from_url(
            session_id="s1",
            url="not-a-url",
            parser=parser,
            max_bytes=1000,
        )

        self.assertEqual(record.status, "failed")
        self.assertIn("valid http", record.error or "")

    def test_clean_html_text_skips_script_content(self):
        text = clean_html_text("<main><h1>Title</h1><script>bad()</script><p>Body text</p></main>")

        self.assertIn("Title", text)
        self.assertIn("Body text", text)
        self.assertNotIn("bad()", text)

    def test_source_store_list_delete_and_search(self):
        tmpdir = Path("tests/.tmp") / f"sources-{uuid.uuid4().hex}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            store = SourceStore(tmpdir)
            ready = SourceRecord.create(
                session_id="s1",
                name="alpha.txt",
                kind="text",
                mime_type="text/plain",
                size_bytes=10,
                text="Alpha beta gamma",
            )
            failed = SourceRecord.create(
                session_id="s1",
                name="failed.txt",
                kind="text",
                mime_type="text/plain",
                size_bytes=0,
                text="Alpha should not match",
                status="failed",
                error="nope",
            )

            store.add(ready)
            store.add(failed)
            self.assertEqual(len(store.list("s1")), 2)
            results = store.search("s1", "beta")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["name"], "alpha.txt")
            self.assertTrue(store.delete("s1", ready.id))
            self.assertEqual(len(store.list("s1")), 1)
        finally:
            source_path = tmpdir / "sources" / "s1.json"
            if source_path.exists():
                source_path.unlink()
            sources_dir = tmpdir / "sources"
            if sources_dir.exists():
                sources_dir.rmdir()
            if tmpdir.exists():
                tmpdir.rmdir()

    def test_discovery_endpoint_ignores_empty_query(self):
        client = self._build_test_client()
        response = client.get("/chat/sources/discover?q=   ")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"query": "", "results": []})

    def test_discovery_endpoint_normalizes_results(self):
        adapter = Mock()
        adapter.search.return_value = SearchDiscoveryResponse(
            query="test",
            results=[
                SearchDiscoveryResult(
                    id="discover-1",
                    title="Example result",
                    url="https://example.com/page",
                    domain="example.com",
                    snippet="Useful summary text",
                    favicon_url="https://example.com/favicon.ico",
                )
            ],
        )
        client = self._build_test_client(discovery_adapter=adapter)

        response = client.get("/chat/sources/discover?q=test")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["query"], "test")
        self.assertEqual(payload["results"][0]["title"], "Example result")
        self.assertEqual(payload["results"][0]["domain"], "example.com")
        self.assertEqual(
            payload["results"][0]["faviconUrl"],
            "https://example.com/favicon.ico",
        )
        adapter.search.assert_called_once_with("test", limit=8)

    def test_discovery_endpoint_handles_provider_errors_without_500(self):
        adapter = Mock()
        adapter.search.return_value = SearchDiscoveryResponse(
            query="test",
            results=[],
            warning="Discovery provider is temporarily unavailable. Try again later.",
        )
        client = self._build_test_client(discovery_adapter=adapter)

        response = client.get("/chat/sources/discover?q=test")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["query"], "test")
        self.assertEqual(payload["results"], [])
        self.assertIn("warning", payload)
        adapter.search.assert_called_once_with("test", limit=8)

    def test_tavily_provider_normalizes_successful_results(self):
        transport = Mock()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "results": [
                {
                    "title": "Top food in Indonesia",
                    "url": "https://example.com/foods",
                    "content": "A guide to Indonesian food.",
                }
            ]
        }
        transport.post.return_value = response
        provider = TavilySearchDiscoveryProvider(transport=transport, api_key="test-key")

        result = provider.search("top food indonesia", limit=5)

        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "tavily")
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].title, "Top food in Indonesia")
        self.assertEqual(result.results[0].domain, "example.com")
        self.assertIn("Indonesian food", result.results[0].snippet)

    def test_tavily_provider_missing_api_key_is_graceful(self):
        provider = TavilySearchDiscoveryProvider(transport=Mock(), api_key="")

        result = provider.search("top food indonesia")

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.category, "config")
        self.assertIn("TAVILY_API_KEY", result.failure.message)

    def test_tavily_provider_invalid_api_key_is_graceful(self):
        transport = Mock()
        response = Mock()
        response.status_code = 403
        transport.post.return_value = response
        provider = TavilySearchDiscoveryProvider(transport=transport, api_key="bad-key")

        result = provider.search("top food indonesia")

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.category, "auth")

    def test_tavily_provider_timeout_is_graceful(self):
        transport = Mock()
        transport.post.side_effect = requests.exceptions.Timeout("timed out")
        provider = TavilySearchDiscoveryProvider(transport=transport, api_key="test-key")

        result = provider.search("top food indonesia")

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.category, "timeout")

    def test_tavily_provider_rate_limit_is_graceful(self):
        transport = Mock()
        response = Mock()
        response.status_code = 429
        transport.post.return_value = response
        provider = TavilySearchDiscoveryProvider(transport=transport, api_key="test-key")

        result = provider.search("top food indonesia")

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.category, "rate_limit")

    def test_tavily_provider_empty_results_are_supported(self):
        transport = Mock()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"results": []}
        transport.post.return_value = response
        provider = TavilySearchDiscoveryProvider(transport=transport, api_key="test-key")

        result = provider.search("top food indonesia")

        self.assertTrue(result.ok)
        self.assertEqual(result.results, [])

    def test_tavily_provider_network_failure_is_graceful(self):
        transport = Mock()
        transport.post.side_effect = requests.exceptions.ConnectionError("offline")
        provider = TavilySearchDiscoveryProvider(transport=transport, api_key="test-key")

        result = provider.search("top food indonesia")

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.category, "network")

    def test_search_discovery_adapter_does_not_cache_failed_provider_fallback(self):
        primary = Mock()
        primary.provider_name = "tavily"
        primary.search.side_effect = [
            SearchProviderResponse(
                provider="tavily",
                results=[],
                failure=SearchProviderFailure(
                    provider="tavily",
                    category="network",
                    message="offline",
                    exception_class="ConnectionError",
                ),
            ),
            SearchProviderResponse(
                provider="tavily",
                results=[
                    SearchDiscoveryResult(
                        id="discover-2",
                        title="Recovered result",
                        url="https://example.com/recovered",
                        domain="example.com",
                        snippet="Recovered snippet",
                    )
                ],
            ),
        ]
        from general_chat.sources import SearchDiscoveryAdapter

        adapter = SearchDiscoveryAdapter(provider_name="tavily")
        adapter._providers = [primary]

        first = adapter.search("top food indonesia")
        second = adapter.search("top food indonesia")

        self.assertEqual(first.results, [])
        self.assertIsNotNone(first.warning)
        self.assertEqual(second.results[0].title, "Recovered result")
        self.assertEqual(primary.search.call_count, 2)

    def test_no_current_source_general_question_reaches_llm(self):
        llm = MockLLMProvider("Paris")
        agent = BaseAgent(goal="General chat")
        agent._llm = llm
        engine = ChatEngine(agent=agent)
        handler = GeneralChatHandler(engine=engine, db_path=":memory:", source_records=[])
        request_agent = handler._create_request_agent()

        result = request_agent.execute(ExecutionContext(goal="What is the capital of France?"))

        self.assertEqual(result.output, "Paris")
        self.assertTrue(llm.prompts)

    def test_unrelated_question_with_sources_reaches_llm(self):
        llm = MockLLMProvider("Paris")
        agent = BaseAgent(goal="General chat")
        agent._llm = llm
        source = SourceRecord.create(
            session_id="chat-session",
            name="roadmap.txt",
            kind="text",
            mime_type="text/plain",
            size_bytes=20,
            text="Alpha launch is planned for June.",
        )
        engine = ChatEngine(agent=agent)
        handler = GeneralChatHandler(
            engine=engine,
            db_path=":memory:",
            source_records=[source],
        )
        content, attachments = handler._extract_content(
            {
                "messages": [
                    {"id": "m1", "role": "user", "content": "What is the capital of France?"}
                ],
                "forwardedProps": {"sessionId": "chat-session"},
            }
        )
        request_agent = handler._create_request_agent()

        result = engine._execute_agent(content, None, attachments=attachments, agent=request_agent)

        self.assertEqual(result.output, "Paris")
        self.assertTrue(llm.prompts)
        self.assertIn("Alpha launch is planned for June.", json.dumps(llm.prompts[-1]))

    def test_no_missing_answer_instruction_is_injected_for_source_context(self):
        llm = MockLLMProvider("I can answer normally.")
        agent = BaseAgent(goal="General chat")
        agent._llm = llm
        source = SourceRecord.create(
            session_id="chat-session",
            name="acme.txt",
            kind="text",
            mime_type="text/plain",
            size_bytes=20,
            text="Acme revenue was 10 million dollars.",
        )
        engine = ChatEngine(agent=agent)
        handler = GeneralChatHandler(
            engine=engine,
            db_path=":memory:",
            source_records=[source],
        )
        content, attachments = handler._extract_content(
            {
                "messages": [{"id": "m1", "role": "user", "content": "What was Acme profit?"}],
                "forwardedProps": {"sessionId": "chat-session"},
            }
        )
        request_agent = handler._create_request_agent()

        result = engine._execute_agent(content, None, attachments=attachments, agent=request_agent)

        self.assertEqual(result.output, "I can answer normally.")
        self.assertTrue(llm.prompts)
        self.assertNotIn(
            "The answer is not in the provided document.",
            json.dumps(llm.prompts[-1]),
        )

    def test_removed_source_text_is_redacted_from_persistent_memory(self):
        tmpdir = Path("tests/.tmp") / f"memory-{uuid.uuid4().hex}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        db_path = tmpdir / "memory.db"
        try:
            store = SQLiteMemoryStore(str(db_path))
            store.save(
                "chat-session",
                [
                    Message(role=MessageRole.SYSTEM, content="system"),
                    Message(
                        role=MessageRole.USER,
                        content=(
                            "Goal: What is old?\n\nContext data:\n"
                            '{"attachments": [{"name": "removed.txt", '
                            '"content": "Removed source secret"}]}'
                        ),
                    ),
                    Message(role=MessageRole.ASSISTANT, content="Old answer"),
                ],
            )
            agent = BaseAgent(goal="General chat")
            agent._llm = MockLLMProvider("Current answer")
            engine = ChatEngine(agent=agent)
            current = SourceRecord.create(
                session_id="chat-session",
                name="current.txt",
                kind="text",
                mime_type="text/plain",
                size_bytes=20,
                text="Current source secret",
            )
            handler = GeneralChatHandler(
                engine=engine,
                db_path=str(db_path),
                source_records=[current],
            )
            handler._on_session_resolved("chat-session")

            request_agent = handler._create_request_agent()

            persisted = "\n".join(message.content for message in store.load("chat-session"))
            self.assertNotIn("Removed source secret", persisted)
            self.assertIn("previous General Chat source attachment content redacted", persisted)
            self.assertNotIn(
                "Removed source secret",
                "\n".join(message.content for message in request_agent.memory.messages),
            )
        finally:
            if db_path.exists():
                db_path.unlink()
            if tmpdir.exists():
                tmpdir.rmdir()

    def _build_test_client(
        self,
        discovery_adapter: Mock | None = None,
        agent: Mock | None = None,
    ) -> TestClient:
        tmpdir = Path("tests/.tmp") / f"app-{uuid.uuid4().hex}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.callback(self._cleanup_path_tree, tmpdir)
        stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(tmpdir / "storage"),
                    "GENERAL_CHAT_UPLOAD_DIR": str(tmpdir / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(tmpdir / "downloads"),
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                },
                clear=False,
            )
        )
        if agent is None:
            agent = Mock()
            agent.model = "mock-model"
            agent._persona = None
            agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
        if discovery_adapter is not None:
            stack.enter_context(
                patch(
                    "general_chat.server.app.SearchDiscoveryAdapter", return_value=discovery_adapter
                )
            )
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def test_create_agent_mcp_disabled_by_default(self):
        import general_chat.agent as agent_module

        with patch.dict(environ, {"GOOGLE_API_KEY": "test-key"}, clear=False):
            environ.pop("GENERAL_CHAT_MCP_ENABLED", None)
            with patch.object(agent_module, "configure_provider"):
                agent = agent_module.create_agent()

        self.assertFalse(agent._mcp_enabled)
        self.assertEqual(agent._mcp_tools, [])
        self.assertEqual(len(agent.tools), 0)

    def test_create_agent_mcp_enabled_loads_allowlisted_adapters(self):
        import general_chat.agent as agent_module

        with (
            patch.dict(
                environ,
                {
                    "GOOGLE_API_KEY": "test-key",
                    "GENERAL_CHAT_MCP_ENABLED": "1",
                    "GENERAL_CHAT_MCP_MODE": "local",
                    "GENERAL_CHAT_MCP_APPROVED_TOOLS": (
                        "openbench.filter_records,"
                        "openbench.distinct_values,"
                        "openbench.group_and_aggregate,"
                        "openbench.top_n_records"
                    ),
                },
                clear=False,
            ),
            patch.object(agent_module, "configure_provider"),
        ):
            agent = agent_module.create_agent()

        names = {tool.namespaced_name for tool in agent._mcp_tools}
        self.assertTrue(agent._mcp_enabled)
        self.assertEqual(
            names,
            {
                "openbench.filter_records",
                "openbench.distinct_values",
                "openbench.group_and_aggregate",
                "openbench.top_n_records",
            },
        )
        self.assertEqual(len(agent.tools), 4)

    def test_mcp_tools_endpoint_disabled_by_default(self):
        client = self._build_test_client()
        response = client.get("/mcp/tools")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["tool_count"], 0)
        self.assertEqual(payload["tools"], [])

    def test_mcp_tools_endpoint_reports_loaded_tools(self):
        tmpdir = Path("tests/.tmp") / f"mcp-app-{uuid.uuid4().hex}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.callback(self._cleanup_path_tree, tmpdir)
        stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(tmpdir / "storage"),
                    "GENERAL_CHAT_UPLOAD_DIR": str(tmpdir / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(tmpdir / "downloads"),
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                },
                clear=False,
            )
        )
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        agent._mcp_summary = {
            "enabled": True,
            "mode": "local",
            "tools": [
                {
                    "name": "openbench.filter_records",
                    "adapter_name": "openbench_filter_records",
                    "description": "Filter rows",
                }
            ],
            "approved_tools": ["openbench.filter_records"],
        }
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))

        from general_chat.server.app import create_app

        client = TestClient(create_app())
        response = client.get("/mcp/tools")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["tool_count"], 1)
        self.assertEqual(payload["namespaced_tool_names"], ["openbench.filter_records"])
        self.assertEqual(payload["provider_tool_names"], ["openbench_filter_records"])

    def test_image_search_render_tool_pushes_chat_render_items(self):
        class FakeImageSearchTool(Tool):
            namespaced_name = "image_search.search_similar_images"
            tool_schema = {"description": "Search similar images"}
            approved = True

            @property
            def name(self):
                return "image_search_search_similar_images"

            @property
            def description(self):
                return "Search similar images"

            def execute(self, **params):
                return {
                    "results": [
                        {
                            "rank": 1,
                            "image_id": "cifar10-train-00001",
                            "class_name": "automobile",
                            "similarity_score": 0.98765,
                            "preview_url": "/image-search/previews/train/cifar10-train-00001.png",
                            "preview_path": "C:/internal/path/should/not/render.png",
                        }
                    ]
                }

            def get_schema(self):
                return {"type": "function", "function": {"name": self.name}}

        render_queue.clear()
        self.addCleanup(render_queue.clear)

        result = _ImageSearchRenderTool(FakeImageSearchTool()).execute(top_k=10)

        items = render_queue.get_items()
        self.assertEqual(result["results"][0]["image_id"], "cifar10-train-00001")
        self.assertEqual(items[0]["headers"], ["Rank", "Label", "Score", "Image ID"])
        self.assertEqual(items[0]["rows"], [["1", "automobile", "0.9877", "cifar10-train-00001"]])
        self.assertEqual(items[1]["mediaType"], "image")
        self.assertEqual(
            items[1]["src"],
            "/image-search/previews/train/cifar10-train-00001.png",
        )
        self.assertNotIn("preview_path", items[1])

    def test_external_filesystem_mcp_example_config_and_sample_data(self):
        from openbench.mcp.config import MCPConfig

        example_root = Path(__file__).resolve().parents[1] / "examples" / "general-chat"
        sandbox = example_root / "mcp-sandbox"
        config_path = example_root / "mcp" / "filesystem-mcp.yaml"

        with patch.dict(environ, {"GENERAL_CHAT_MCP_SANDBOX": str(sandbox)}, clear=False):
            config = MCPConfig.from_file(config_path)

        server = config.client_config().servers["filesystem"]
        self.assertEqual(server.transport, "stdio")
        self.assertEqual(server.command, "npx")
        self.assertEqual(server.namespace, "filesystem")
        self.assertTrue(server.allowed)
        self.assertEqual(server.args[-1], str(sandbox))
        self.assertIn("@modelcontextprotocol/server-filesystem", server.args)

        customers = json.loads((sandbox / "customers.json").read_text(encoding="utf-8"))
        highest = max(customers, key=lambda item: item["arr"])
        self.assertEqual(highest["account"], "Borneo Analytics")
        self.assertEqual(highest["arr"], 220000)

    def test_sam_segmentation_mcp_example_config(self):
        from openbench.mcp.config import MCPConfig

        example_root = Path(__file__).resolve().parents[1] / "examples" / "general-chat"
        config_path = example_root / "mcp" / "sam-segmentation-docker.yaml"

        with patch.dict(
            environ,
            {
                "SAM_SEGMENTATION_MCP_MODELS_PATH": "C:/tmp/models",
                "SAM_SEGMENTATION_MCP_UPLOADS_PATH": "C:/tmp/uploads",
            },
            clear=False,
        ):
            config = MCPConfig.from_file(config_path)

        server = config.client_config().servers["sam_segmentation"]
        self.assertEqual(server.transport, "stdio")
        self.assertEqual(server.command, "docker")
        self.assertEqual(server.namespace, "sam_segmentation")
        self.assertTrue(server.allowed)
        self.assertEqual(server.discovery_timeout_seconds, 15)
        self.assertEqual(server.timeout_seconds, 3600)
        self.assertEqual(server.retries, 0)
        self.assertIn("openbench/sam-segmentation-mcp:cpu", server.args)
        self.assertNotIn("C:/tmp/models:/models:ro", server.args)
        self.assertIn("SAM3_MODEL_PATH=/models/sam3.pt", server.args)
        self.assertIn("SAM3_DEVICE=cpu", server.args)
        self.assertIn("IMAGE_INPUT_ROOTS=/general-chat/uploads", server.args)
        self.assertNotIn("SAM_MODEL=sam_b.pt", server.args)

    def _cleanup_path_tree(self, root: Path) -> None:
        if not root.exists():
            return
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()


class TestDoclingImageExtractor(unittest.TestCase):
    def _mock_docling_module(self, markdown: str):
        converter_instance = Mock()
        converter_instance.convert.return_value = types.SimpleNamespace(
            document=types.SimpleNamespace(export_to_markdown=Mock(return_value=markdown))
        )
        converter_cls = Mock(return_value=converter_instance)
        module = types.ModuleType("docling.document_converter")
        module.DocumentConverter = converter_cls
        return module

    def test_extract_image_accepts_jpeg_extension_and_sets_format_metadata(self):
        extractor = DoclingContentExtractor()
        stored = StoredFile(
            id="file-jpeg",
            name="photo.jpg",
            path="photo.jpg",
            mime_type="application/octet-stream",
            size_bytes=123,
            stored_at="2026-01-01T00:00:00+00:00",
        )
        fake_docling = self._mock_docling_module("Detected text")
        with patch.dict(sys.modules, {"docling.document_converter": fake_docling}):
            payload = extractor.extract_image(stored)

        self.assertEqual(payload["metadata"]["format"], "jpeg")
        self.assertIn("Format: JPEG", payload["search_text"])
        self.assertIn("JPEG image source", payload["description"])

    def test_extract_image_accepts_webp_mime_and_sets_format_metadata(self):
        extractor = DoclingContentExtractor()
        stored = StoredFile(
            id="file-webp",
            name="poster.webp",
            path="poster.webp",
            mime_type="image/webp",
            size_bytes=123,
            stored_at="2026-01-01T00:00:00+00:00",
        )
        fake_docling = self._mock_docling_module("Campaign headline")
        with patch.dict(sys.modules, {"docling.document_converter": fake_docling}):
            payload = extractor.extract_image(stored)

        self.assertEqual(payload["metadata"]["format"], "webp")
        self.assertIn("Format: WEBP", payload["search_text"])
        self.assertIn("WEBP image source", payload["description"])


if __name__ == "__main__":
    unittest.main()
