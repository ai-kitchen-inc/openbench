"""Tests for chat transport request-body validation."""

from __future__ import annotations

import unittest

from fastapi import HTTPException

from openbench.chat.transport.validation import (
    MAX_ATTACHMENTS,
    MAX_CONTENT_LENGTH,
    ChatTransportValidationError,
    raise_invalid_request,
    validate_action_request_body,
    validate_stream_request_body,
)


class TestStreamRequestValidation(unittest.TestCase):
    def test_valid_body_is_returned_unchanged(self):
        body = {
            "threadId": "thread-1",
            "runId": "run_1",
            "content": "hello",
            "messages": [{"role": "user", "content": "hello"}],
            "forwardedProps": {"sessionId": "session:1", "custom": True},
        }
        self.assertIs(validate_stream_request_body(body), body)

    def test_empty_object_is_valid(self):
        self.assertEqual(validate_stream_request_body({}), {})

    def test_non_object_is_rejected(self):
        for raw in (None, "text", [], 42):
            with self.subTest(raw=raw), self.assertRaises(ChatTransportValidationError):
                validate_stream_request_body(raw)

    def test_malformed_thread_id_is_rejected(self):
        with self.assertRaises(ChatTransportValidationError) as ctx:
            validate_stream_request_body({"threadId": "../../etc/passwd"})
        self.assertEqual(ctx.exception.code, "invalid_body")

    def test_leading_symbol_id_is_rejected(self):
        with self.assertRaises(ChatTransportValidationError):
            validate_stream_request_body({"threadId": "-starts-with-dash"})

    def test_oversized_content_is_rejected(self):
        with self.assertRaises(ChatTransportValidationError):
            validate_stream_request_body({"content": "x" * (MAX_CONTENT_LENGTH + 1)})

    def test_attachment_overflow_gets_specific_code(self):
        body = {"attachments": [{} for _ in range(MAX_ATTACHMENTS + 1)]}
        with self.assertRaises(ChatTransportValidationError) as ctx:
            validate_stream_request_body(body)
        self.assertEqual(ctx.exception.code, "too_many_attachments")
        self.assertEqual(ctx.exception.detail, {"max": MAX_ATTACHMENTS})

    def test_forwarded_props_attachment_overflow_gets_specific_code(self):
        body = {"forwardedProps": {"attachments": [{} for _ in range(MAX_ATTACHMENTS + 1)]}}
        with self.assertRaises(ChatTransportValidationError) as ctx:
            validate_stream_request_body(body)
        self.assertEqual(ctx.exception.code, "too_many_attachments")

    def test_mixed_errors_fall_back_to_generic_code(self):
        body = {
            "threadId": "bad id with spaces",
            "attachments": [{} for _ in range(MAX_ATTACHMENTS + 1)],
        }
        with self.assertRaises(ChatTransportValidationError) as ctx:
            validate_stream_request_body(body)
        self.assertEqual(ctx.exception.code, "invalid_body")


class TestActionRequestValidation(unittest.TestCase):
    def test_valid_body_is_returned_unchanged(self):
        body = {"name": "submit", "surfaceId": "surface-1", "context": {"a": 1}}
        self.assertIs(validate_action_request_body(body), body)

    def test_missing_name_is_rejected(self):
        with self.assertRaises(ChatTransportValidationError):
            validate_action_request_body({"surfaceId": "surface-1"})

    def test_malformed_surface_id_is_rejected(self):
        with self.assertRaises(ChatTransportValidationError):
            validate_action_request_body({"name": "submit", "surfaceId": "bad surface"})

    def test_optional_source_component_id_may_be_absent(self):
        body = {"name": "submit", "surfaceId": "s1", "threadId": "t1"}
        self.assertIs(validate_action_request_body(body), body)

    def test_non_object_is_rejected(self):
        with self.assertRaises(ChatTransportValidationError):
            validate_action_request_body("nope")


class TestRaiseInvalidRequest(unittest.TestCase):
    def test_generic_detail_by_default(self):
        with self.assertRaises(HTTPException) as ctx:
            raise_invalid_request()
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "Invalid request body")

    def test_generic_error_keeps_generic_detail(self):
        error = ChatTransportValidationError("nope")
        with self.assertRaises(HTTPException) as ctx:
            raise_invalid_request(error=error)
        self.assertEqual(ctx.exception.detail, "Invalid request body")

    def test_coded_error_becomes_structured_detail(self):
        error = ChatTransportValidationError(
            "too many", code="too_many_attachments", max=MAX_ATTACHMENTS
        )
        with self.assertRaises(HTTPException) as ctx:
            raise_invalid_request(status_code=413, error=error)
        self.assertEqual(ctx.exception.status_code, 413)
        self.assertEqual(
            ctx.exception.detail, {"code": "too_many_attachments", "max": MAX_ATTACHMENTS}
        )


if __name__ == "__main__":
    unittest.main()
