"""Tests for the OpenAI-compatible chat transport."""

from __future__ import annotations

import asyncio
import unittest

from openbench.chat.session import Attachment
from openbench.chat.transport.openai_compat import (
    OpenAICompatHandler,
    _message_content_to_text,
    create_openai_compatible_router,
)


class FakeEngine:
    def _execute_agent(self, content, config, attachments=None, on_chunk=None, **kwargs):
        if on_chunk:
            on_chunk("hello ")
            on_chunk(content)
        attachment_names = [a.name for a in attachments or []]
        return {
            "output": f"hello {content}",
            "metadata": {
                "prompt_tokens": 2,
                "completion_tokens": 3,
                "attachments": attachment_names,
            },
        }

    @staticmethod
    def _extract_metadata(result):
        return result.get("metadata", {})

    @staticmethod
    def _result_failed(_result):
        return False, ""

    @staticmethod
    def _extract_output(result):
        return result.get("output")

    @staticmethod
    def _extract_text_content(output):
        return str(output or "")


class OpenAICompatTests(unittest.TestCase):
    def test_message_content_list_is_flattened(self):
        content = [
            {"type": "text", "text": "Summarize this"},
            {"type": "image_url", "image_url": {"url": "https://example.test/a.png"}},
        ]

        self.assertEqual(
            _message_content_to_text(content),
            "Summarize this\n\n[Image: https://example.test/a.png]",
        )

    def test_models_response_exposes_configured_model(self):
        handler = OpenAICompatHandler(
            engine=FakeEngine(),
            base_agent=object(),
            model_id="openbench-chat",
        )

        self.assertEqual(handler.models()["data"][0]["id"], "openbench-chat")

    def test_run_turn_uses_last_user_message(self):
        handler = OpenAICompatHandler(
            engine=FakeEngine(),
            base_agent=object(),
            model_id="openbench-chat",
        )

        text, metadata = handler._run_turn(
            {
                "messages": [
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "old answer"},
                    {"role": "user", "content": "latest"},
                ]
            },
            None,
        )

        self.assertEqual(text, "hello latest")
        self.assertEqual(metadata["prompt_tokens"], 2)

    def test_attachment_resolver_adds_session_sources(self):
        def resolve(_body, session_id):
            return [
                Attachment(
                    id=f"{session_id}-source",
                    type="file",
                    name="source.txt",
                    url="",
                    mime_type="text/plain",
                    extracted_text="source text",
                )
            ]

        handler = OpenAICompatHandler(
            engine=FakeEngine(),
            base_agent=object(),
            model_id="openbench-chat",
            attachment_resolver=resolve,
        )

        _, metadata = handler._run_turn(
            {
                "metadata": {"chat_id": "chat-1"},
                "messages": [{"role": "user", "content": "use source"}],
            },
            None,
        )

        self.assertEqual(metadata["attachments"], ["source.txt"])

    def test_stream_chat_emits_done(self):
        async def collect():
            handler = OpenAICompatHandler(
                engine=FakeEngine(),
                base_agent=object(),
                model_id="openbench-chat",
            )
            return [
                line
                async for line in handler._stream_chat(
                    {"stream": True, "messages": [{"role": "user", "content": "world"}]}
                )
            ]

        lines = asyncio.run(collect())
        self.assertTrue(any('"content": "hello "' in line for line in lines))
        self.assertEqual(lines[-1], "data: [DONE]\n\n")

    def test_router_chat_completions_accepts_json_body(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi is not installed")

        app = FastAPI()
        app.include_router(
            create_openai_compatible_router(
                engine=FakeEngine(),
                base_agent=object(),
                model_id="openbench-chat",
            ),
            prefix="/v1",
        )
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "openbench-chat",
                "messages": [{"role": "user", "content": "router"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["choices"][0]["message"]["content"], "hello router")


if __name__ == "__main__":
    unittest.main()
