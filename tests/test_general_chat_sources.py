"""Tests for General Chat source-context injection."""

from __future__ import annotations

import sys
import unittest
import uuid
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from openbench.chat.files import StoredFile
from openbench.chat.engine import ChatEngine
from openbench.core.abstractions import Agent, ExecutionContext, ExecutionResult
from fastapi.testclient import TestClient


GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.server.app import _resolve_request_session_id  # noqa: E402
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
        self.assertIn("OCR-detected text", str(record.metadata["description"]))
        extractor.extract_image.assert_called_once_with(stored)

    def test_png_ocr_failure_creates_failed_image_source(self):
        extractor = Mock()
        extractor.extract_image.side_effect = ValueError("Image extraction failed: OCR pipeline unavailable")
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

        self.assertEqual(record.status, "failed")
        self.assertIn("OCR pipeline unavailable", record.error or "")

    def test_invalid_image_type_is_rejected(self):
        parser = SourceParserRegistry()
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

        self.assertEqual(record.status, "failed")
        self.assertIn("Unsupported", record.error or "")

    def test_url_validation(self):
        self.assertEqual(validate_url("https://example.com/page"), "https://example.com/page")
        with self.assertRaisesRegex(ValueError, "http or https"):
            validate_url("ftp://example.com")
        with self.assertRaisesRegex(ValueError, "Local"):
            validate_url("http://localhost:8000")

    def test_website_ingestion_success_with_mocked_fetch(self):
        parser = SourceParserRegistry()
        html = "<html><head><title>Example Title</title></head><body><script>x()</script><p>Hello web source.</p></body></html>"
        with patch.object(parser, "_parse_url_with_docling", side_effect=RuntimeError("skip")):
            with patch("general_chat.sources.fetch_url_text", return_value=(html, "text/html")):
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

    def _build_test_client(self, discovery_adapter: Mock | None = None) -> TestClient:
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
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
        if discovery_adapter is not None:
            stack.enter_context(
                patch("general_chat.server.app.SearchDiscoveryAdapter", return_value=discovery_adapter)
            )
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def _cleanup_path_tree(self, root: Path) -> None:
        if not root.exists():
            return
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()


if __name__ == "__main__":
    unittest.main()
