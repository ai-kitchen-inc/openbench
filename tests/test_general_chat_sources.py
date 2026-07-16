"""Tests for General Chat source-context injection."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import types
import unittest
import uuid
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
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
from openbench.intelligence.base import Message, MessageRole, ToolExecutor
from openbench.intelligence.memory import SQLiteMemoryStore

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.agent import (  # noqa: E402
    _DashboardGeneratorRenderTool,
    _DiagnosticMCPToolDescription,
    _ImageSearchRenderTool,
    _latest_dashboard_revision_note,
    _mcp_registry_root,
    _SamSegmentationCountTool,
)
from general_chat.extractor import DoclingContentExtractor  # noqa: E402
from general_chat.server.app import _resolve_mime, _resolve_request_session_id  # noqa: E402
from general_chat.server.handler import GeneralChatHandler, sanitize_messages  # noqa: E402
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
    mark_source_upload_deleted,
    source_record_from_file,
    source_record_from_text,
    source_record_from_url,
    upload_file_ids_for_source,
    validate_file_source,
    validate_url,
)

pytestmark = pytest.mark.integration


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
    def test_sanitize_messages_drops_unresolved_tool_exchange_before_new_user(self):
        messages = [
            Message(role=MessageRole.SYSTEM, content="system"),
            Message(role=MessageRole.USER, content="old request"),
            Message(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=[{"id": "call_0", "name": "generate_dashboard", "arguments": {}}],
            ),
            Message(
                role=MessageRole.TOOL,
                content='{"type": "dashboard"}',
                name="generate_dashboard",
                tool_call_id="call_0",
            ),
            Message(role=MessageRole.USER, content="new request"),
        ]

        sanitized = sanitize_messages(messages)

        self.assertEqual(
            [message.role for message in sanitized],
            [MessageRole.SYSTEM, MessageRole.USER],
        )
        self.assertEqual(sanitized[-1].content, "new request")

    def test_sanitize_messages_drops_completed_tool_exchange_without_raw_content(self):
        messages = [
            Message(role=MessageRole.SYSTEM, content="system"),
            Message(role=MessageRole.USER, content="old request"),
            Message(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=[{"id": "call_0", "name": "extract_metadata", "arguments": {}}],
            ),
            Message(
                role=MessageRole.TOOL,
                content='{"row_count": 10}',
                name="extract_metadata",
                tool_call_id="call_0",
            ),
            Message(role=MessageRole.ASSISTANT, content="Dashboard done"),
        ]

        sanitized = sanitize_messages(messages)

        self.assertEqual(
            [message.role for message in sanitized],
            [MessageRole.SYSTEM, MessageRole.USER, MessageRole.ASSISTANT],
        )
        self.assertEqual(sanitized[-1].content, "Dashboard done")
        self.assertFalse(any(message.tool_calls for message in sanitized))

    def test_sanitize_messages_keeps_completed_tool_exchange_with_raw_content(self):
        raw_content = object()
        messages = [
            Message(role=MessageRole.SYSTEM, content="system"),
            Message(role=MessageRole.USER, content="old request"),
            Message(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=[{"id": "call_0", "name": "extract_metadata", "arguments": {}}],
                raw_content=raw_content,
            ),
            Message(
                role=MessageRole.TOOL,
                content='{"row_count": 10}',
                name="extract_metadata",
                tool_call_id="call_0",
            ),
            Message(role=MessageRole.ASSISTANT, content="Dashboard done"),
        ]

        sanitized = sanitize_messages(messages)

        self.assertEqual(
            [message.role for message in sanitized],
            [
                MessageRole.SYSTEM,
                MessageRole.USER,
                MessageRole.ASSISTANT,
                MessageRole.TOOL,
                MessageRole.ASSISTANT,
            ],
        )
        self.assertIs(sanitized[2].raw_content, raw_content)

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

    def test_enriched_image_attachment_preserves_existing_file_mcp_path(self):
        agent = MockAgent()
        engine = ChatEngine(agent=agent)
        existing_text = (
            "Image source: images.jpeg\n"
            "Browser URL: /uploads/file-7a3e15e3/images.jpeg\n"
            "image_search MCP path: /general-chat/uploads/file-7a3e15e3/images.jpeg\n"
            "sam_segmentation MCP path: /general-chat/uploads/file-7a3e15e3/images.jpeg\n\n"
            "To count objects matching a text concept in this uploaded image, call "
            "sam_segmentation.count_objects_with_sam3 with "
            'image_path="/general-chat/uploads/file-7a3e15e3/images.jpeg".'
        )
        handler = GeneralChatHandler(engine=engine, db_path=":memory:", source_records=[])

        _content, attachments = handler._extract_content(
            {
                "messages": [{"id": "m1", "role": "user", "content": "count cars"}],
                "forwardedProps": {
                    "sessionId": "chat-session",
                    "attachments": [
                        {
                            "id": "source-9a9b15ad8b",
                            "type": "image",
                            "name": "images.jpeg",
                            "url": "/uploads/source-9a9b15ad8b/images.jpeg",
                            "mimeType": "image/jpeg",
                            "sizeBytes": 6781,
                            "extractedText": existing_text,
                        }
                    ],
                },
            }
        )

        self.assertIsNotNone(attachments)
        assert attachments is not None
        self.assertEqual(attachments[0].path, "/general-chat/uploads/file-7a3e15e3/images.jpeg")
        self.assertEqual(attachments[0].extracted_text, existing_text)
        self.assertNotIn(
            "/general-chat/uploads/source-9a9b15ad8b", attachments[0].extracted_text or ""
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

    def test_image_source_runs_vision_agent_when_local_path_available(self):
        class FakeVisionAgent:
            def __init__(self):
                self.context: ExecutionContext | None = None

            def execute(self, context: ExecutionContext) -> ExecutionResult:
                self.context = context
                return ExecutionResult(
                    output="The image shows a white car with plate B 1234 CD.",
                    status="completed",
                    metadata={"provider": "gemini", "model": "gemini-2.5-flash"},
                )

        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "plate.jpg"
            image_path.write_bytes(b"fake-image")
            vision_agent = FakeVisionAgent()
            agent = MockAgent()
            agent._vision_agent = vision_agent
            engine = ChatEngine(agent=agent)
            source = SourceRecord.create(
                session_id="chat-session",
                name="plate.jpg",
                kind="image",
                mime_type="image/jpeg",
                size_bytes=20,
                url="/uploads/file-1/plate.jpg",
                text="Image source: plate.jpg",
                metadata={
                    "imageSearchPath": "/general-chat/uploads/file-1/plate.jpg",
                    "localFilePath": str(image_path),
                },
            )
            handler = GeneralChatHandler(
                engine=engine,
                db_path=":memory:",
                source_records=[source],
            )

            content, attachments = handler._extract_content(
                {
                    "messages": [{"id": "m1", "role": "user", "content": "baca plat nomor"}],
                    "forwardedProps": {"sessionId": "chat-session"},
                }
            )

        self.assertIsNotNone(attachments)
        assert attachments is not None
        self.assertEqual(attachments[0].path, str(image_path))
        self.assertEqual(attachments[-1].name, "visual-observations.md")
        self.assertIn("B 1234 CD", attachments[-1].extracted_text or "")
        self.assertIsNotNone(vision_agent.context)
        assert vision_agent.context is not None
        self.assertEqual(
            vision_agent.context.data["attachments"][0]["path"],
            str(image_path),
        )

        engine._execute_agent(content, None, attachments=attachments)
        self.assertIsNotNone(agent.context)
        assert agent.context is not None
        contents = "\n".join(item["content"] for item in agent.context.data["attachments"])
        self.assertIn("Visual observation from the configured OpenBench VLM", contents)
        self.assertIn("B 1234 CD", contents)

    def test_spreadsheet_source_attachment_includes_dashboard_path(self):
        agent = MockAgent()
        engine = ChatEngine(agent=agent)
        source = SourceRecord.create(
            session_id="chat-session",
            name="sales.csv",
            kind="spreadsheet",
            mime_type="text/csv",
            size_bytes=20,
            url="/uploads/file-1/sales.csv",
            text="Spreadsheet source: sales.csv\n\n| raw_column |\n| should_not_enter_prompt |",
            metadata={"localFilePath": "C:/tmp/openbench/sales.csv"},
        )
        handler = GeneralChatHandler(
            engine=engine,
            db_path=":memory:",
            source_records=[source],
        )

        content, attachments = handler._extract_content(
            {
                "messages": [{"id": "m1", "role": "user", "content": "buatkan dashboard"}],
                "forwardedProps": {"sessionId": "chat-session"},
            }
        )

        self.assertEqual(content, "buatkan dashboard")
        self.assertIsNotNone(attachments)
        assert attachments is not None
        self.assertEqual(attachments[0].type, "file")
        self.assertEqual(attachments[0].path, "C:/tmp/openbench/sales.csv")
        self.assertIn("extract_metadata", attachments[0].extracted_text or "")
        self.assertIn("C:/tmp/openbench/sales.csv", attachments[0].extracted_text or "")
        self.assertNotIn("should_not_enter_prompt", attachments[0].extracted_text or "")

        engine._execute_agent(content, None, attachments=attachments)

        self.assertIsNotNone(agent.context)
        assert agent.context is not None
        self.assertEqual(agent.context.data["attachments"][0]["path"], "C:/tmp/openbench/sales.csv")

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
            / "mcp"
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

        self.assertEqual(parsed.text, "")
        self.assertEqual((parsed.metadata or {})["spreadsheetContextMode"], "metadata-first")

    def test_csv_source_becomes_dashboard_ready_spreadsheet(self):
        try:
            import pandas  # noqa: F401
        except ImportError:
            self.skipTest("pandas is not installed")

        tmpdir = Path("tests/.tmp") / f"csv-{uuid.uuid4().hex}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        path = tmpdir / "sales.csv"
        path.write_text("region,revenue\nEU,100\nUS,150\n", encoding="utf-8")
        try:
            stored = StoredFile(
                id="file-1",
                name="sales.csv",
                path=str(path),
                mime_type="text/csv",
                size_bytes=path.stat().st_size,
                stored_at="2026-01-01T00:00:00+00:00",
            )
            record = source_record_from_file(
                session_id="s1",
                stored_file=stored,
                parser=SourceParserRegistry(),
                max_bytes=1000,
            )
        finally:
            if path.exists():
                path.unlink()
            if tmpdir.exists():
                tmpdir.rmdir()

        self.assertEqual(record.status, "ready")
        self.assertEqual(record.kind, "spreadsheet")
        self.assertTrue((record.metadata or {})["dashboardSource"])
        self.assertIn("localFilePath", record.metadata or {})
        self.assertIn("extract_metadata", record.text)
        self.assertIn("Raw spreadsheet rows are not included", record.text)
        self.assertNotIn("| region", record.text)

    def test_design_md_source_becomes_dashboard_template(self):
        tmpdir = Path("tests/.tmp") / f"template-{uuid.uuid4().hex}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        path = tmpdir / "design.md"
        path.write_text("# Dashboard Design\n\n```css\n:root { --ob-accent: #0f766e; }\n```", encoding="utf-8")
        try:
            stored = StoredFile(
                id="file-template",
                name="design.md",
                path=str(path),
                mime_type="text/markdown",
                size_bytes=path.stat().st_size,
                stored_at="2026-01-01T00:00:00+00:00",
            )
            record = source_record_from_file(
                session_id="s1",
                stored_file=stored,
                parser=SourceParserRegistry(),
                max_bytes=1000,
            )
        finally:
            if path.exists():
                path.unlink()
            if tmpdir.exists():
                tmpdir.rmdir()

        self.assertEqual(record.status, "ready")
        self.assertEqual(record.kind, "dashboard_template")
        self.assertTrue((record.metadata or {})["dashboardTemplate"])
        self.assertEqual((record.metadata or {})["dashboardTemplateFormat"], "markdown")
        self.assertIn("Dashboard template path:", record.text)
        self.assertIn("generate_dashboard", record.text)

    def test_dashboard_template_source_attachment_includes_template_path(self):
        agent = MockAgent()
        engine = ChatEngine(agent=agent)
        source = SourceRecord.create(
            session_id="chat-session",
            name="template.html",
            kind="dashboard_template",
            mime_type="text/html",
            size_bytes=20,
            url="/uploads/file-template/template.html",
            text="Dashboard template source: template.html",
            metadata={
                "dashboardTemplate": True,
                "dashboardTemplatePath": "C:/tmp/template.html",
                "dashboardTemplateFormat": "html",
            },
        )
        handler = GeneralChatHandler(
            engine=engine,
            db_path=":memory:",
            source_records=[source],
        )

        content, attachments = handler._extract_content(
            {
                "messages": [
                    {
                        "id": "m1",
                        "role": "user",
                        "content": "buatkan dashboard pakai template ini",
                    }
                ],
                "forwardedProps": {"sessionId": "chat-session"},
            }
        )

        self.assertEqual(content, "buatkan dashboard pakai template ini")
        self.assertIsNotNone(attachments)
        assert attachments is not None
        self.assertEqual(attachments[0].path, "C:/tmp/template.html")
        self.assertIn("template_path", attachments[0].extracted_text or "")
        self.assertIn("C:/tmp/template.html", attachments[0].extracted_text or "")

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

    def test_invalid_source_type_is_rejected(self):
        parser = SourceParserRegistry()
        stored = StoredFile(
            id="file-6",
            name="firmware.bin",
            path="firmware.bin",
            mime_type="application/x-unknown",
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

    def test_source_store_for_owner_isolates_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = SourceStore(tmp)
            alice = base.for_owner("alice@example.com")
            bob = base.for_owner("bob@example.com")

            record = SourceRecord.create(
                session_id="thread-x",
                name="alpha.txt",
                kind="text",
                mime_type="text/plain",
                size_bytes=10,
                text="Alpha secret",
                metadata={"fileId": "file-alpha"},
            )
            alice.add(record)

            # Records land in a per-owner subdirectory and get stamped.
            owner_file = Path(tmp) / "sources" / "alice_example_com" / "thread-x.json"
            self.assertTrue(owner_file.exists())
            self.assertEqual(alice.list("thread-x")[0].owner, "alice@example.com")

            # The other owner sees nothing — list, search, and file-id lookup.
            self.assertEqual(bob.list("thread-x"), [])
            self.assertEqual(bob.search("thread-x", "Alpha"), [])
            self.assertIsNone(bob.find_by_upload_file_id("file-alpha"))
            self.assertIsNotNone(alice.find_by_upload_file_id("file-alpha"))

            # The unscoped store (worker path) still sees everything and
            # writes updates back to the record's owner file.
            found = base.find_by_upload_file_id("file-alpha")
            self.assertIsNotNone(found)
            found.status = "failed"
            base.upsert(found)
            self.assertEqual(alice.list("thread-x")[0].status, "failed")
            self.assertEqual(alice.list("thread-x")[0].owner, "alice@example.com")

    def test_source_record_owner_round_trips(self):
        record = SourceRecord.create(
            session_id="s1",
            name="a.txt",
            kind="text",
            mime_type="text/plain",
            size_bytes=1,
            text="x",
            owner="alice@example.com",
        )
        payload = record.to_dict(include_text=True)
        self.assertEqual(payload["owner"], "alice@example.com")
        restored = SourceRecord.from_dict(record.to_dict(include_text=True))
        self.assertEqual(restored.owner, "alice@example.com")

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

    def _upload_text_source(
        self,
        client: TestClient,
        *,
        session_id: str,
        filename: str = "notes.txt",
        content: bytes = b"Useful source text",
    ) -> tuple[dict, Path]:
        response = client.post(
            "/chat/upload",
            files={"file": (filename, content, "text/plain")},
            data={"sessionId": session_id},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        file_id = payload["url"].split("/")[2]
        return payload, Path(environ["GENERAL_CHAT_UPLOAD_DIR"]) / file_id

    def test_source_upload_cleanup_scrubs_mcp_paths_and_preserves_text(self):
        record = SourceRecord.create(
            session_id="s1",
            name="photo.png",
            kind="image",
            mime_type="image/png",
            size_bytes=10,
            url="/uploads/file-abc123/photo.png",
            text=(
                "Image source: photo.png\n"
                "Browser URL: /uploads/file-abc123/photo.png\n"
                "image_search MCP path: /general-chat/uploads/file-abc123/photo.png\n"
                "Extracted image context:\nA dog on grass."
            ),
            metadata={
                "imageSearchPath": "/general-chat/uploads/file-abc123/photo.png",
                "samSegmentationPath": "/general-chat/uploads/file-abc123/photo.png",
                "imageSearchPreviewUrl": "/uploads/file-abc123/photo.png",
                "description": "A dog on grass.",
            },
        )

        self.assertEqual(upload_file_ids_for_source(record), {"file-abc123"})

        mark_source_upload_deleted(record, deleted_at="2026-06-03T00:00:00+00:00")

        self.assertIsNone(record.url)
        self.assertNotIn("imageSearchPath", record.metadata or {})
        self.assertNotIn("samSegmentationPath", record.metadata or {})
        self.assertNotIn("imageSearchPreviewUrl", record.metadata or {})
        self.assertTrue((record.metadata or {})["uploadDeleted"])
        self.assertEqual(
            (record.metadata or {})["uploadDeletedAt"],
            "2026-06-03T00:00:00+00:00",
        )
        self.assertIn("A dog on grass.", record.text)
        self.assertNotIn("/uploads/file-abc123", record.text)
        self.assertNotIn("/general-chat/uploads/file-abc123", record.text)

    def test_awp_stream_deletes_used_upload_and_scrubs_source_record(self):
        client = self._build_test_client(agent=MockAgent())
        payload, file_dir = self._upload_text_source(client, session_id="s-clean")
        self.assertTrue(file_dir.exists())

        response = client.post(
            "/awp",
            json={
                "threadId": "s-clean",
                "messages": [{"role": "user", "content": "Use my source"}],
                "forwardedProps": {"sessionId": "s-clean"},
            },
            headers={"accept": "text/event-stream"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(file_dir.exists())
        sources = client.get("/chat/sources/s-clean").json()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["id"], payload["id"])
        self.assertIsNone(sources[0]["url"])
        self.assertTrue(sources[0]["metadata"]["uploadDeleted"])
        search = client.get("/chat/sources/s-clean/search?q=Useful").json()
        self.assertEqual(search["results"][0]["sourceId"], payload["id"])

    def test_awp_stream_preserves_spreadsheet_upload_for_dashboard_turns(self):
        try:
            import pandas  # noqa: F401
        except ImportError:
            self.skipTest("pandas is not installed")

        client = self._build_test_client(agent=MockAgent())
        response = client.post(
            "/chat/upload",
            files={"file": ("sales.csv", b"region,revenue\nEU,100\n", "text/csv")},
            data={"sessionId": "s-dashboard"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        file_id = payload["url"].split("/")[2]
        file_dir = Path(environ["GENERAL_CHAT_UPLOAD_DIR"]) / file_id
        self.assertEqual(payload["kind"], "spreadsheet")
        self.assertTrue(file_dir.exists())

        response = client.post(
            "/awp",
            json={
                "threadId": "s-dashboard",
                "messages": [{"role": "user", "content": "buatkan dashboard"}],
                "forwardedProps": {"sessionId": "s-dashboard"},
            },
            headers={"accept": "text/event-stream"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(file_dir.exists())
        sources = client.get("/chat/sources/s-dashboard").json()
        self.assertEqual(sources[0]["metadata"]["dashboardSource"], True)
        self.assertIn("localFilePath", sources[0]["metadata"])

    def test_delete_source_removes_referenced_upload_file(self):
        client = self._build_test_client()
        payload, file_dir = self._upload_text_source(client, session_id="s-delete")
        self.assertTrue(file_dir.exists())

        response = client.delete(f"/chat/sources/s-delete/{payload['id']}")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(file_dir.exists())
        self.assertEqual(client.get("/chat/sources/s-delete").json(), [])

    def test_clear_sources_removes_referenced_upload_files(self):
        client = self._build_test_client()
        _, first_dir = self._upload_text_source(client, session_id="s-clear", filename="a.txt")
        _, second_dir = self._upload_text_source(client, session_id="s-clear", filename="b.txt")
        self.assertTrue(first_dir.exists())
        self.assertTrue(second_dir.exists())

        response = client.delete("/chat/sources/s-clear")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(first_dir.exists())
        self.assertFalse(second_dir.exists())
        self.assertEqual(client.get("/chat/sources/s-clear").json(), [])

    def test_delete_session_removes_session_sources_and_upload_files(self):
        client = self._build_test_client()
        _, file_dir = self._upload_text_source(client, session_id="s-session")
        self.assertTrue(file_dir.exists())

        response = client.delete("/sessions/s-session")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(file_dir.exists())
        self.assertEqual(client.get("/chat/sources/s-session").json(), [])

    def test_create_agent_mcp_disabled_by_default(self):
        import general_chat.agent as agent_module

        with patch.dict(environ, {"GOOGLE_API_KEY": "test-key"}, clear=False):
            environ.pop("GENERAL_CHAT_MCP_ENABLED", None)
            with patch.object(agent_module, "_configure_general_chat_provider"):
                agent = agent_module.create_agent()

        self.assertFalse(agent._mcp_enabled)
        self.assertEqual(agent._mcp_tools, [])
        self.assertTrue(agent._vlm_summary["enabled"])
        self.assertEqual(agent._vlm_summary["model"], "gemini-2.5-flash")
        self.assertIsNotNone(agent._vision_agent)
        # File-export skills only — dashboard generation is MCP-only now.
        # export-excel(2) + pdf-tools(7) + export-markdown(1) = 10 skill tools
        self.assertEqual(len(agent.tools), 10)
        self.assertEqual(
            set(agent._dashboard_skill_tools),
            {
                "export_to_excel",
                "export_multi_sheet_excel",
                "pdf_metadata",
                "read_pdf",
                "read_pdf_page",
                "extract_pdf_tables",
                "merge_pdfs",
                "split_pdf",
                "generate_pdf",
                "generate_markdown",
            },
        )

    def test_dashboard_revision_note_is_extracted_from_latest_user_goal(self):
        agent = BaseAgent(goal="test")
        agent.memory.add_user("Goal: chart Revenue by Coffee Name diganti pie chart aja")

        self.assertEqual(
            _latest_dashboard_revision_note(agent),
            "chart Revenue by Coffee Name diganti pie chart aja",
        )

    def test_configure_general_chat_provider_does_not_persist_provider_state(self):
        import general_chat.agent as agent_module

        captured = {}

        class FakeProviderService:
            def configure(self, config, save=True):
                captured["config"] = config
                captured["save"] = save

        with patch.object(agent_module, "get_provider_service", return_value=FakeProviderService()):
            agent_module._configure_general_chat_provider("test-key", "test-model")

        config = captured["config"]
        self.assertFalse(captured["save"])
        self.assertEqual(config.name, "gemini-general-chat")
        self.assertEqual(config.provider_type.value, "llm")
        self.assertEqual(config.provider, "gemini")
        self.assertEqual(config.plugin_type, "chat")
        self.assertEqual(config.credentials, {"api_key": "test-key"})
        self.assertEqual(
            config.settings, {"model": "test-model", "max_output_tokens": 32768}
        )
        self.assertTrue(config.is_default)

    def test_configure_general_chat_vlm_provider_does_not_persist_provider_state(self):
        import general_chat.agent as agent_module

        captured = {}

        class FakeProviderService:
            def configure(self, config, save=True):
                captured["config"] = config
                captured["save"] = save

        with patch.object(agent_module, "get_provider_service", return_value=FakeProviderService()):
            agent_module._configure_general_chat_vlm_provider(
                api_key="test-key",
                provider="gemini",
                model="gemini-2.5-flash",
                temperature=0.2,
                max_output_tokens=2048,
            )

        config = captured["config"]
        self.assertFalse(captured["save"])
        self.assertEqual(config.name, "general-chat-vlm")
        self.assertEqual(config.provider_type.value, "vlm")
        self.assertEqual(config.provider, "gemini")
        self.assertEqual(config.plugin_type, "vision")
        self.assertEqual(config.credentials, {"api_key": "test-key"})
        self.assertEqual(
            config.settings,
            {"model": "gemini-2.5-flash", "temperature": 0.2, "max_output_tokens": 2048},
        )
        self.assertTrue(config.is_default)

    def test_gemma_vlm_model_resolves_to_ollama_provider(self):
        import general_chat.agent as agent_module

        with patch.dict(
            environ,
            {
                "GENERAL_CHAT_VLM_MODEL": "gemma-2b",
                "GENERAL_CHAT_VLM_BASE_URL": "http://localhost:11434/v1",
            },
            clear=False,
        ):
            environ.pop("GENERAL_CHAT_VLM_PROVIDER", None)
            environ.pop("OPENBENCH_VLM_PROVIDER", None)
            provider, model, requested = agent_module._resolve_vlm_selection()

        self.assertEqual(provider, "ollama")
        self.assertEqual(model, "gemma4:e2b")
        self.assertEqual(requested, "gemma-2b")

    def test_configure_ollama_vlm_uses_local_base_url(self):
        import general_chat.agent as agent_module

        captured = {}

        class FakeProviderService:
            def configure(self, config, save=True):
                captured["config"] = config
                captured["save"] = save

        with (
            patch.dict(
                environ,
                {"GENERAL_CHAT_VLM_BASE_URL": "http://localhost:11434/v1"},
                clear=False,
            ),
            patch.object(agent_module, "get_provider_service", return_value=FakeProviderService()),
        ):
            details = agent_module._configure_general_chat_vlm_provider(
                api_key="test-key",
                provider="gemma",
                model="gemma4:e2b",
                temperature=0.2,
                max_output_tokens=2048,
            )

        config = captured["config"]
        self.assertFalse(captured["save"])
        self.assertEqual(details["provider"], "ollama")
        self.assertEqual(details["base_url"], "http://localhost:11434/v1")
        self.assertEqual(config.provider, "ollama")
        self.assertEqual(config.settings["model"], "gemma4:e2b")
        self.assertEqual(config.settings["base_url"], "http://localhost:11434/v1")

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
            patch.object(agent_module, "_configure_general_chat_provider"),
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
        # 4 MCP query tools registered into chat + the 10 skill tools
        self.assertEqual(len(agent.tools), 14)

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
            timeout_seconds = 3600

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

        wrapped = _ImageSearchRenderTool(FakeImageSearchTool())
        result = wrapped.execute(top_k=10)

        items = render_queue.get_items()
        self.assertEqual(wrapped.timeout_seconds, 3600)
        self.assertEqual(result["results"][0]["image_id"], "cifar10-train-00001")
        self.assertEqual(items[0]["headers"], ["Rank", "Label", "Score", "Image ID"])
        self.assertEqual(items[0]["rows"], [["1", "automobile", "0.9877", "cifar10-train-00001"]])
        self.assertEqual(items[1]["mediaType"], "image")
        self.assertEqual(
            items[1]["src"],
            "/image-search/previews/train/cifar10-train-00001.png",
        )
        self.assertNotIn("preview_path", items[1])

    def test_dashboard_render_tool_returns_stub_and_queues_full_payload(self):
        class FakeDashboardTool(Tool):
            namespaced_name = "openbench.generate_dashboard"
            tool_schema = {"description": "Generate dashboard"}
            approved = True
            timeout_seconds = 600

            def __init__(self, warnings):
                self._warnings = warnings

            @property
            def name(self):
                return "openbench_generate_dashboard"

            @property
            def description(self):
                return "Generate dashboard"

            def execute(self, **params):
                return {
                    "type": "dashboard",
                    "title": "Coffee Sales Dashboard",
                    "description": "Sales overview",
                    "viewModel": {"title": "Coffee Sales Dashboard", "sections": []},
                    "datasets": {"sales": [{"region": "EU", "revenue": 1}]},
                    "kpis": [{"label": "Revenue", "value": 1}],
                    "sections": [{"title": "Revenue", "items": []}],
                    "name": "coffee.html",
                    "url": "/downloads/coffee.html",
                    "dashboardUrl": "/downloads/coffee.html",
                    "path": "C:/tmp/coffee.html",
                    "mimeType": "text/html",
                    "size": 9076,
                    "sectionCount": 1,
                    "kpiCount": 1,
                    "chartCount": 0,
                    "tableCount": 0,
                    "warnings": self._warnings,
                }

            def get_schema(self):
                return {"type": "function", "function": {"name": self.name}}

        render_queue.clear()
        self.addCleanup(render_queue.clear)

        wrapped = _DashboardGeneratorRenderTool(FakeDashboardTool(warnings=[]))
        result = wrapped.execute(view_model={"title": "Coffee Sales Dashboard"})

        # Full payload (viewModel + datasets) goes to the UI render queue.
        items = render_queue.get_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["viewModel"]["title"], "Coffee Sales Dashboard")
        self.assertIn("datasets", items[0])
        # The agent only sees a compact stub — echoing the full ViewModel
        # bloated the history window and drove regenerate loops.
        self.assertNotIn("viewModel", result)
        self.assertNotIn("datasets", result)
        self.assertNotIn("kpis", result)
        self.assertNotIn("sections", result)
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["url"], "/downloads/coffee.html")
        self.assertEqual(result["chartCount"], 0)
        self.assertIn("Do NOT call generate_dashboard again", result["final_answer_hint"])

    def test_dashboard_render_tool_surfaces_warnings_with_corrective_hint(self):
        render_queue.clear()
        self.addCleanup(render_queue.clear)

        warnings = ["section item must be a chart/table/kpi object, got int: 6"]

        class FakeDashboardTool(Tool):
            namespaced_name = "openbench.generate_dashboard"
            tool_schema = {"description": "Generate dashboard"}
            approved = True
            timeout_seconds = 600

            @property
            def name(self):
                return "openbench_generate_dashboard"

            @property
            def description(self):
                return "Generate dashboard"

            def execute(self, **params):
                return {
                    "type": "dashboard",
                    "title": "Coffee Sales Dashboard",
                    "viewModel": {"title": "Coffee Sales Dashboard"},
                    "url": "/downloads/coffee.html",
                    "chartCount": 0,
                    "warnings": warnings,
                }

            def get_schema(self):
                return {"type": "function", "function": {"name": self.name}}

        wrapped = _DashboardGeneratorRenderTool(FakeDashboardTool())
        result = wrapped.execute(view_model={"title": "Coffee Sales Dashboard"})

        self.assertEqual(result["warnings"], warnings)
        self.assertIn("invalid", result["final_answer_hint"])
        # The hint must NOT demand an unconditional retry (that drove the
        # 20x generate_dashboard loop); it tells the model not to repeat the
        # same ViewModel.
        self.assertIn(
            "Do NOT re-call generate_dashboard with the same ViewModel",
            result["final_answer_hint"],
        )

    def test_sam_segmentation_count_tool_defaults_and_caches_success(self):
        class FakeSamCountTool(Tool):
            namespaced_name = "sam_segmentation.count_objects_with_sam3"
            tool_schema = {"description": "Count objects with SAM 3"}
            approved = True
            timeout_seconds = 3600

            def __init__(self):
                self.calls = 0

            @property
            def name(self):
                return "sam_segmentation_count_objects_with_sam3"

            @property
            def description(self):
                return "Count objects with SAM 3"

            def execute(self, **params):
                self.calls += 1
                return {"count": 3, "received": params}

            def get_schema(self):
                return {
                    "type": "function",
                    "function": {
                        "name": self.name,
                        "description": self.description,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "image_path": {"type": "string"},
                                "concept": {"type": "string"},
                                "return_segments": {"type": "boolean", "default": True},
                                "return_overlay": {"type": "boolean", "default": True},
                            },
                        },
                    },
                }

        inner = FakeSamCountTool()
        wrapped = _SamSegmentationCountTool(inner)

        first = wrapped.execute(
            image_path="/general-chat/uploads/file-1/cats.jpg",
            concept="cat",
        )
        second = wrapped.execute(
            image_path="/general-chat/uploads/file-1/cats.jpg",
            concept="cat",
        )
        schema = wrapped.get_schema()
        properties = schema["function"]["parameters"]["properties"]

        self.assertEqual(wrapped.timeout_seconds, 3600)
        self.assertEqual(first["count"], 3)
        self.assertEqual(first["received"]["return_segments"], False)
        self.assertEqual(first["received"]["return_overlay"], False)
        self.assertIn("Use the returned count", first["final_answer_hint"])
        self.assertEqual(second["count"], 3)
        self.assertTrue(second["cached"])
        self.assertEqual(inner.calls, 1)
        self.assertIn("call this once", schema["function"]["description"])
        self.assertFalse(properties["return_segments"]["default"])
        self.assertFalse(properties["return_overlay"]["default"])

    def test_sam_segmentation_count_tool_coalesces_inflight_duplicates(self):
        class SlowSamCountTool(Tool):
            namespaced_name = "sam_segmentation.count_objects_with_sam3"
            tool_schema = {"description": "Count objects with SAM 3"}
            approved = True
            timeout_seconds = 3600

            def __init__(self):
                self.calls = 0
                self.started = threading.Event()
                self.lock = threading.Lock()

            @property
            def name(self):
                return "sam_segmentation_count_objects_with_sam3"

            @property
            def description(self):
                return "Count objects with SAM 3"

            def execute(self, **params):
                with self.lock:
                    self.calls += 1
                self.started.set()
                time.sleep(0.05)
                return {"count": 2, "received": params}

            def get_schema(self):
                return {"type": "function", "function": {"name": self.name}}

        inner = SlowSamCountTool()
        wrapped = _SamSegmentationCountTool(inner)
        results: list[dict[str, object]] = []
        errors: list[BaseException] = []

        def call_tool():
            try:
                results.append(
                    wrapped.execute(
                        image_path="/general-chat/uploads/file-1/cars.jpg",
                        concept="car",
                    )
                )
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=call_tool)
        first.start()
        self.assertTrue(inner.started.wait(timeout=1))
        second = threading.Thread(target=call_tool)
        second.start()
        first.join(timeout=1)
        second.join(timeout=1)

        self.assertFalse(errors)
        self.assertEqual(inner.calls, 1)
        self.assertEqual([item["count"] for item in results], [2, 2])
        self.assertTrue(any(item.get("cached") for item in results))

    def test_wrapped_sam_tool_timeout_is_visible_to_tool_executor(self):
        class SlowSamCountTool(Tool):
            namespaced_name = "sam_segmentation.count_objects_with_sam3"
            tool_schema = {"description": "Count objects with SAM 3"}
            approved = True
            timeout_seconds = 0.01

            @property
            def name(self):
                return "sam_segmentation_count_objects_with_sam3"

            @property
            def description(self):
                return "Count objects with SAM 3"

            def execute(self, **params):
                time.sleep(0.05)
                return {"count": 1}

            def get_schema(self):
                return {"type": "function", "function": {"name": self.name}}

        executor = ToolExecutor()
        wrapped = _SamSegmentationCountTool(SlowSamCountTool())
        executor.register(wrapped.name, wrapped)

        with self.assertRaisesRegex(TimeoutError, "0.01s timeout"):
            executor.execute(
                wrapped.name,
                image_path="/general-chat/uploads/file-1/cars.jpg",
                concept="car",
            )

    def test_diagnostic_mcp_tool_description_preserves_timeout(self):
        class FakeServiceInfoTool(Tool):
            namespaced_name = "sam_segmentation.service_info"
            tool_schema = {"description": "Service info"}
            approved = True
            timeout_seconds = 3600

            @property
            def name(self):
                return "sam_segmentation_service_info"

            @property
            def description(self):
                return "Service info"

            def execute(self, **params):
                return {"ok": True}

            def get_schema(self):
                return {"type": "function", "function": {"name": self.name}}

        self.assertEqual(
            _DiagnosticMCPToolDescription(FakeServiceInfoTool()).timeout_seconds,
            3600,
        )

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

    def test_docker_mcp_gateway_example_config(self):
        from openbench.mcp.config import MCPConfig

        example_root = Path(__file__).resolve().parents[1] / "examples" / "general-chat"
        config_path = example_root / "mcp" / "docker-mcp-gateway.yaml"

        config = MCPConfig.from_file(config_path)

        server = config.client_config().servers["docker"]
        self.assertEqual(server.transport, "stdio")
        self.assertEqual(server.command, "docker")
        self.assertEqual(server.namespace, "docker")
        self.assertTrue(server.allowed)
        self.assertEqual(server.discovery_timeout_seconds, 15)
        self.assertEqual(server.timeout_seconds, 3600)
        self.assertEqual(
            server.args,
            ["mcp", "gateway", "run", "--profile", "openbench"],
        )

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
