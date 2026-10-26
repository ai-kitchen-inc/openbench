"""Request-body validation for chat transport endpoints."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, field_validator

MAX_ID_LENGTH = 128
MAX_CONTENT_LENGTH = 200_000
MAX_MESSAGES = 100
MAX_ATTACHMENTS = 50

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class ChatTransportValidationError(ValueError):
    """Raised when a chat transport request body fails validation.

    ``code`` lets a caller distinguish the cases worth explaining to the
    user (currently: too many attachments) from the generic rejection,
    without leaking payload details into the response.
    """

    def __init__(self, message: str, *, code: str = "invalid_body", **detail: Any) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


def _validate_safe_id(value: str | None, *, field_name: str, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if len(value) == 0:
        if required:
            raise ValueError(f"{field_name} is required")
        return value
    if len(value) > MAX_ID_LENGTH or not _SAFE_ID_RE.fullmatch(value):
        raise ValueError(f"{field_name} has an invalid format")
    return value


class _ForwardedPropsModel(BaseModel):
    """Validated subset of forwardedProps; unknown keys remain allowed."""

    model_config = ConfigDict(extra="allow")

    sessionId: StrictStr | None = None
    attachments: list[dict[str, Any]] | None = Field(default=None, max_length=MAX_ATTACHMENTS)

    @field_validator("sessionId")
    @classmethod
    def _validate_session_id(cls, value: str | None) -> str | None:
        return _validate_safe_id(value, field_name="forwardedProps.sessionId")


class _AGUIMessageModel(BaseModel):
    """Validated AG-UI message shape used by the transport."""

    model_config = ConfigDict(extra="allow")

    role: StrictStr = Field(min_length=1, max_length=64)
    content: StrictStr = Field(max_length=MAX_CONTENT_LENGTH)


class _AGUIStreamRequestModel(BaseModel):
    """Validated AG-UI/OpenBench streaming request body."""

    model_config = ConfigDict(extra="allow")

    threadId: StrictStr | None = None
    runId: StrictStr | None = None
    content: StrictStr | None = Field(default=None, max_length=MAX_CONTENT_LENGTH)
    messages: list[_AGUIMessageModel] | None = Field(default=None, max_length=MAX_MESSAGES)
    forwardedProps: _ForwardedPropsModel | None = None
    attachments: list[dict[str, Any]] | None = Field(default=None, max_length=MAX_ATTACHMENTS)

    @field_validator("threadId")
    @classmethod
    def _validate_thread_id(cls, value: str | None) -> str | None:
        return _validate_safe_id(value, field_name="threadId")

    @field_validator("runId")
    @classmethod
    def _validate_run_id(cls, value: str | None) -> str | None:
        return _validate_safe_id(value, field_name="runId")


class _ActionRequestModel(BaseModel):
    """Validated REST action request body."""

    model_config = ConfigDict(extra="allow")

    name: StrictStr
    surfaceId: StrictStr
    sourceComponentId: StrictStr | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    dataModel: dict[str, Any] | None = None
    threadId: StrictStr | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _validate_safe_id(value, field_name="name", required=True) or value

    @field_validator("surfaceId")
    @classmethod
    def _validate_surface_id(cls, value: str) -> str:
        return _validate_safe_id(value, field_name="surfaceId", required=True) or value

    @field_validator("sourceComponentId")
    @classmethod
    def _validate_source_component_id(cls, value: str | None) -> str | None:
        return _validate_safe_id(value, field_name="sourceComponentId")

    @field_validator("threadId")
    @classmethod
    def _validate_thread_id(cls, value: str | None) -> str | None:
        return _validate_safe_id(value, field_name="threadId")


def _ensure_object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ChatTransportValidationError("Request body must be a JSON object")
    return raw


def validate_stream_request_body(raw: Any) -> dict[str, Any]:
    """Validate a streaming chat request body and return the original object."""

    body = _ensure_object(raw)
    try:
        _AGUIStreamRequestModel.model_validate(body)
    except ValidationError as exc:
        if _is_attachment_overflow(exc):
            raise ChatTransportValidationError(
                "Too many attachments",
                code="too_many_attachments",
                max=MAX_ATTACHMENTS,
            ) from exc
        raise ChatTransportValidationError("Invalid chat request body") from exc
    return body


def _is_attachment_overflow(exc: ValidationError) -> bool:
    """True when the only problem is an over-long attachments list."""
    errors = exc.errors()
    return bool(errors) and all(
        err.get("type") == "too_long" and "attachments" in err.get("loc", ()) for err in errors
    )


def validate_action_request_body(raw: Any) -> dict[str, Any]:
    """Validate an A2UI action request body and return the original object."""

    body = _ensure_object(raw)
    try:
        _ActionRequestModel.model_validate(body)
    except ValidationError as exc:
        raise ChatTransportValidationError("Invalid action request body") from exc
    return body


def raise_invalid_request(
    status_code: int = 422, error: ChatTransportValidationError | None = None
) -> None:
    """Raise a FastAPI validation error without leaking payload details.

    With no ``error`` the detail stays the generic string every existing
    caller expects. When the validation error carries a specific ``code``,
    the detail becomes a small structured object the client can translate
    — the count limit is not a secret, and "Invalid request body" gives a
    user with 60 files nothing to act on.
    """

    from fastapi import HTTPException

    if error is not None and error.code != "invalid_body":
        raise HTTPException(
            status_code=status_code,
            detail={"code": error.code, **error.detail},
        )
    raise HTTPException(status_code=status_code, detail="Invalid request body")
