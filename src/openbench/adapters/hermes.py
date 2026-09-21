"""
Hermes Agent framework adapter for OpenBench.

Hermes Agent (Nous Research) is a self-hosted agent runtime. Each Hermes
*profile* is an isolated agent (own config, skills, MCP servers, memory,
sessions, credentials) that can expose an OpenAI-compatible API server.
This adapter talks to one such API server, so one adapter instance maps to
exactly one Hermes profile — the isolation boundary is the profile's own
base URL + API key.

Two entry points:

- :class:`HermesAdapter` — ``FrameworkAdapter`` for workflows
  (``source | HermesAdapter(...) | output``), with ``invoke`` and ``stream``.
- :class:`HermesAgent` — ``Agent`` wrapper for the chat pipeline, so
  ``ChatEngine`` streams tokens (``on_chunk``) and tool progress
  (``on_progress``) from Hermes like it does for ``BaseAgent``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import requests

from openbench.core import FrameworkAdapter
from openbench.core.abstractions import Agent, ExecutionContext, ExecutionResult
from openbench.intelligence.agent_config import ProgressEvent

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

DEFAULT_MODEL_NAME = "hermes-agent"
DEFAULT_TIMEOUT_SECONDS = 600.0
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
HEALTH_PATH = "/health"
SESSION_HEADER = "X-Hermes-Session-Id"
TOOL_PROGRESS_EVENT = "hermes.tool.progress"
_HISTORY_ROLES = ("user", "assistant")


class HermesError(RuntimeError):
    """Raised when the Hermes API server rejects or fails a request."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HermesAdapter(FrameworkAdapter):
    """Adapter for one Hermes Agent profile reached over its API server.

    Example:
        ```python
        from openbench.adapters.hermes import HermesAdapter

        hermes = HermesAdapter("http://127.0.0.1:8643", api_key=os.environ["HERMES_KEY"])
        print(hermes.invoke("Summarize today's tickets")["output"])
        ```

    Args:
        base_url: Root URL of the profile's API server (no ``/v1`` suffix).
        api_key: The profile's ``API_SERVER_KEY`` bearer token.
        model: Model id sent in the request. Hermes advertises the profile
            name; the value does not switch the underlying LLM.
        timeout: Read timeout in seconds (agent turns can run long).
        session: Optional ``requests.Session`` (connection reuse / tests).
    """

    @property
    def framework_name(self) -> str:
        return "hermes"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL_NAME,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url is required")
        if not api_key.strip():
            raise ValueError("api_key is required")
        self.base_url = base_url.strip().rstrip("/")
        self.model = model
        self.timeout = timeout
        self._api_key = api_key.strip()
        self._http = session or requests.Session()

    def __repr__(self) -> str:
        return f"HermesAdapter(base_url={self.base_url!r}, model={self.model!r})"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def invoke(self, input: Any, config: Any | None = None) -> dict[str, Any]:
        """Run one non-streaming turn.

        Args:
            input: User message (str), or a dict with ``input``/``goal``.
            config: Optional dict with ``session_id`` (Hermes transcript
                scope) and ``messages`` (prior ``{"role", "content"}`` turns).

        Returns:
            ``{"output": str, "metadata": {...}}`` — the shape ChatEngine's
            ``_extract_output`` / ``_extract_metadata`` understand.
        """
        payload = self._payload(input, config, stream=False)
        response = self._post(payload, config, stream=False)
        try:
            body = response.json()
        except ValueError as exc:
            raise HermesError("Hermes returned a non-JSON response") from exc
        choices = body.get("choices") or [{}]
        message = choices[0].get("message") or {}
        return {
            "output": str(message.get("content") or ""),
            "metadata": self._metadata(body.get("usage"), response),
        }

    def stream(
        self,
        input: Any,
        config: Any | None = None,
        *,
        on_progress: Callable[[str], None] | None = None,
        usage_sink: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        """Stream one turn, yielding text deltas.

        Args:
            input: Same as :meth:`invoke`.
            config: Same as :meth:`invoke`.
            on_progress: Called with a short label for each Hermes tool
                progress event.
            usage_sink: Optional dict filled with the final ``usage`` payload.
        """
        payload = self._payload(input, config, stream=True)
        response = self._post(payload, config, stream=True)
        try:
            event_name = ""
            for raw in response.iter_lines(decode_unicode=True):
                if raw is None:
                    continue
                line = raw.strip()
                if not line:
                    event_name = ""
                    continue
                if line.startswith("event:"):
                    event_name = line[len("event:") :].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                if event_name == TOOL_PROGRESS_EVENT:
                    if on_progress:
                        on_progress(_progress_label(chunk))
                    continue
                if usage_sink is not None and isinstance(chunk.get("usage"), dict):
                    usage_sink.update(chunk["usage"])
                for choice in chunk.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        yield str(delta)
        finally:
            response.close()

    def health(self) -> bool:
        """True when the profile's API server answers its liveness probe."""
        try:
            response = self._http.get(f"{self.base_url}{HEALTH_PATH}", timeout=5.0)
        except requests.RequestException:
            return False
        return response.status_code == 200

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _payload(self, input: Any, config: Any | None, *, stream: bool) -> dict[str, Any]:
        text = _input_text(input)
        if not text.strip():
            raise ValueError("HermesAdapter needs a non-empty input message")
        history = config.get("messages") if isinstance(config, dict) else None
        messages = [
            {"role": str(item["role"]), "content": str(item["content"])}
            for item in (history or [])
            if isinstance(item, dict)
            and item.get("role") in _HISTORY_ROLES
            and str(item.get("content") or "").strip()
        ]
        messages.append({"role": "user", "content": text})
        return {"model": self.model, "messages": messages, "stream": stream}

    def _post(
        self, payload: dict[str, Any], config: Any | None, *, stream: bool
    ) -> requests.Response:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        session_id = config.get("session_id") if isinstance(config, dict) else None
        if session_id:
            headers[SESSION_HEADER] = str(session_id)
        if stream:
            headers["Accept"] = "text/event-stream"
        try:
            response = self._http.post(
                f"{self.base_url}{CHAT_COMPLETIONS_PATH}",
                json=payload,
                headers=headers,
                timeout=(10.0, self.timeout),
                stream=stream,
            )
        except requests.RequestException as exc:
            raise HermesError(f"Hermes API server unreachable at {self.base_url}") from exc
        if response.status_code >= 400:
            detail = _error_detail(response)
            response.close()
            raise HermesError(
                f"Hermes API server returned {response.status_code}: {detail}",
                status_code=response.status_code,
            )
        return response

    def _metadata(self, usage: Any, response: requests.Response | None = None) -> dict[str, Any]:
        metadata: dict[str, Any] = {"framework": self.framework_name, "model": self.model}
        if isinstance(usage, dict):
            metadata["usage"] = dict(usage)
        if response is not None:
            session_id = response.headers.get(SESSION_HEADER)
            if session_id:
                metadata["hermes_session_id"] = session_id
        return metadata


class HermesAgent(Agent):
    """Chat-pipeline wrapper: one SSS/OpenBench agent backed by one Hermes profile.

    Conversation history comes from the chat session OpenBench already keeps
    (``context.data["session"]``); the chat session id doubles as the Hermes
    transcript scope, so two chat sessions never share a Hermes transcript.
    """

    def __init__(self, adapter: HermesAdapter) -> None:
        self.adapter = adapter

    @property
    def agent_type(self) -> str:
        return "hermes"

    @property
    def model(self) -> str:
        return self.adapter.model

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0

    def execute(
        self,
        context: ExecutionContext,
        on_chunk: Callable[[str], None] | None = None,
        on_progress: Callable[[ProgressEvent], None] | None = None,
    ) -> ExecutionResult:
        config = _config_from_context(context)
        usage: dict[str, Any] = {}

        def _progress(label: str) -> None:
            if on_progress:
                on_progress(ProgressEvent(phase=label))

        try:
            parts: list[str] = []
            for delta in self.adapter.stream(
                context.goal, config, on_progress=_progress, usage_sink=usage
            ):
                parts.append(delta)
                if on_chunk:
                    on_chunk(delta)
        except HermesError as exc:
            return ExecutionResult(
                output="",
                status="error",
                metadata={"framework": self.adapter.framework_name, "error": str(exc)},
            )
        total = usage.get("total_tokens")
        return ExecutionResult(
            output="".join(parts),
            status="success",
            metadata=self.adapter._metadata(usage or None),
            tokens_used=int(total) if isinstance(total, (int, float)) else None,
        )


def _input_text(input: Any) -> str:
    if isinstance(input, str):
        return input
    if isinstance(input, dict):
        for key in ("input", "goal", "content", "message"):
            value = input.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return str(input or "")


def _config_from_context(context: ExecutionContext) -> dict[str, Any]:
    """Pull Hermes session scope + prior turns out of the chat session dict."""
    data = context.data if isinstance(context.data, dict) else {}
    session = data.get("session") if isinstance(data.get("session"), dict) else {}
    messages = [m for m in session.get("messages") or [] if isinstance(m, dict)]
    # ChatEngine appends the current user message before executing the agent.
    if (
        messages
        and messages[-1].get("role") == "user"
        and messages[-1].get("content") == context.goal
    ):
        messages = messages[:-1]
    config: dict[str, Any] = {"messages": messages}
    if session.get("sessionId"):
        config["session_id"] = session["sessionId"]
    return config


def _progress_label(chunk: dict[str, Any]) -> str:
    for key in ("label", "message", "tool", "name"):
        value = chunk.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Hermes tool"


def _error_detail(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:200]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)[:200]
    return str(error or body)[:200]
