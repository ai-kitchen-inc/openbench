"""Google Stitch dashboard rendering adapter."""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from typing import Any
from .adapter_base import BaseAdapter, DashboardRenderResult
from .default_adapter import DefaultGeneratorAdapter

_PROJECT_RE = re.compile(r"projects/([A-Za-z0-9_-]+)")
_SCREEN_RE = re.compile(r"screens/([A-Za-z0-9_-]+)")


class StitchAdapter(BaseAdapter):
    """Adapter for Stitch-backed dashboard generation.

    Stitch's public MCP endpoint speaks JSON-RPC, so ``https://stitch.googleapis.com/mcp``
    is not expected to return raw HTML from a single ``view_model`` POST. This adapter
    supports that MCP flow and still supports a direct HTML endpoint for private
    deployments that expose one.
    """

    name = "stitch"

    def __init__(
        self,
        *,
        output_path: str | Path,
        public_url: str | None = None,
        api_key: str | None = None,
        endpoint: str | None = None,
        timeout_seconds: float | None = None,
        fallback: BaseAdapter | None = None,
    ):
        super().__init__(output_path=output_path, public_url=public_url)
        self.api_key = api_key or os.environ.get("STITCH_API_KEY") or os.environ.get(
            "GOOGLE_STITCH_API_KEY"
        )
        self.endpoint = endpoint or os.environ.get("STITCH_API_URL")
        self.timeout_seconds = timeout_seconds or float(
            os.environ.get("STITCH_TIMEOUT_SECONDS", "180")
        )
        self.fallback = fallback or DefaultGeneratorAdapter(
            output_path=self.output_path,
            public_url=self.public_url,
        )

    def _download_html(self, url: str) -> str:
        try:
            import requests
        except ImportError as exc:
            raise ImportError("requests is required to download Stitch HTML.") from exc

        response = requests.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.text
    
    def render(self, view_model: dict[str, Any]) -> DashboardRenderResult:
        stitch = {"configured": bool(self.api_key), "used": False}
        if not self.api_key or not self.endpoint:
            if self.api_key and not self.endpoint:
                stitch["note"] = "STITCH_API_KEY is set, but STITCH_API_URL is not configured."
            return self._render_with_fallback(view_model, stitch)

        try:
            if self._mode() == "mcp":
                return self._render_with_mcp(view_model, stitch)
            return self._render_with_direct_html(view_model, stitch)
        except Exception as exc:
            stitch["error"] = str(exc)
            stitch["transport"] = self._mode()
            return self._render_with_fallback(view_model, stitch)

    def _mode(self) -> str:
        configured = os.environ.get("STITCH_API_MODE") or os.environ.get("STITCH_TRANSPORT")
        if configured:
            return configured.strip().lower()
        endpoint = str(self.endpoint or "").rstrip("/").lower()
        return "mcp" if endpoint.endswith("/mcp") else "direct"

    def _render_with_direct_html(
        self,
        view_model: dict[str, Any],
        stitch: dict[str, Any],
    ) -> DashboardRenderResult:
        payload = self._post_json({"view_model": view_model})
        html_text = _extract_html(payload)
        if not html_text:
            stitch["error"] = "Stitch direct response did not contain an HTML document."
            return self._render_with_fallback(view_model, stitch)

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(html_text, encoding="utf-8")
        stitch.update({"used": True, "endpoint": self.endpoint, "transport": "direct"})
        return DashboardRenderResult(
            file_path=str(self.output_path),
            size_bytes=self.output_path.stat().st_size,
            metadata={
                "adapter": {"name": self.name, "used": True, "transport": "direct"},
                "stitch": stitch,
            },
        )

    def _render_with_mcp(
        self,
        view_model: dict[str, Any],
        stitch: dict[str, Any],
    ) -> DashboardRenderResult:
        tools = self._mcp_request("tools/list", {}).get("result", {}).get("tools", [])
        tool_names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
        project_id = os.environ.get("STITCH_PROJECT_ID")
        title = str(view_model.get("title") or "OpenBench Dashboard")
        create_payload: dict[str, Any] | None = None

        if not project_id:
            if "create_project" not in tool_names:
                stitch["error"] = "Stitch MCP tools/list did not expose create_project."
                return self._render_with_fallback(view_model, stitch)
            create_payload = self._mcp_call_tool(
                "create_project",
                {"title": os.environ.get("STITCH_PROJECT_TITLE") or title},
            )
            project_id = _extract_project_id(create_payload)

        if not project_id:
            stitch["error"] = "Stitch MCP create_project did not return a project id."
            return self._render_with_fallback(view_model, stitch)

        generate_tool = os.environ.get("STITCH_MCP_GENERATE_TOOL") or "generate_screen_from_text"
        if generate_tool not in tool_names:
            stitch["error"] = f"Stitch MCP tools/list did not expose {generate_tool!r}."
            return self._render_with_fallback(view_model, stitch)

        args: dict[str, Any] = {
            "projectId": project_id,
            "prompt": _view_model_to_prompt(view_model),
            "deviceType": os.environ.get("STITCH_DEVICE_TYPE") or "DESKTOP",
            "modelId": os.environ.get("STITCH_MODEL_ID") or "GEMINI_3_FLASH",
        }
        design_system = os.environ.get("STITCH_DESIGN_SYSTEM")
        if design_system:
            args["designSystem"] = design_system

        screen_payload = self._mcp_call_tool(generate_tool, args)
        screen_id = _extract_screen_id(screen_payload)
        screen_detail_payload: dict[str, Any] | None = None
        if screen_id and "get_screen" in tool_names:
            try:
                screen_detail_payload = self._mcp_call_tool(
                    "get_screen",
                    {
                        "name": f"projects/{project_id}/screens/{screen_id}",
                        "projectId": project_id,
                        "screenId": screen_id,
                    },
                )
            except Exception as exc:
                stitch["get_screen_error"] = str(exc)

        resolved_payload = screen_detail_payload or screen_payload

        html_text = _extract_html(resolved_payload)

        html_download_url = _extract_html_download_url(resolved_payload)
        if not html_text and html_download_url:
            print("DEBUG: Downloading Stitch HTML:", html_download_url)
            html_text = self._download_html(html_download_url)
            if "<html" not in html_text.lower():
                raise ValueError("Downloaded Stitch file is not an HTML document.")

        if html_text:
            print("DEBUG: STITCH HTML USED TRUE")
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_text(html_text, encoding="utf-8")
        else:
            self._write_stitch_wrapper(view_model, create_payload, resolved_payload)

        tools_used = ["create_project" if create_payload else "existing_project", generate_tool]
        if screen_detail_payload:
            tools_used.append("get_screen")
        stitch.update(
            {
                "used": True,
                "endpoint": self.endpoint,
                "transport": "mcp",
                "project_id": project_id,
                "screen_id": screen_id,
                "url": _extract_url(screen_detail_payload)
                or _extract_url(screen_payload)
                or _extract_url(create_payload),
                "tools": tools_used,
            }
        )
        return DashboardRenderResult(
            file_path=str(self.output_path),
            size_bytes=self.output_path.stat().st_size,
            metadata={
                "adapter": {"name": self.name, "used": True, "transport": "mcp"},
                "stitch": stitch,
            },
        )

    def _mcp_call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._mcp_request("tools/call", {"name": name, "arguments": arguments})

    def _mcp_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        response = self._post_json(payload)
        if not isinstance(response, dict):
            raise ValueError(f"Stitch MCP {method} returned a non-object response.")
        if "error" in response:
            raise ValueError(f"Stitch MCP {method} error: {response['error']}")
        return response

    def _post_json(self, payload: dict[str, Any]) -> Any:
        try:
            import requests
        except ImportError as exc:
            raise ImportError("requests is required for Stitch HTTP generation.") from exc

        response = requests.post(
            self.endpoint,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "X-Goog-Api-Key": self.api_key,
            },
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            return response.text

    def _write_stitch_wrapper(
        self,
        view_model: dict[str, Any],
        create_payload: dict[str, Any] | None,
        screen_payload: dict[str, Any],
    ) -> None:
        title = html.escape(str(view_model.get("title") or "OpenBench Dashboard"))
        description = html.escape(str(view_model.get("description") or ""))
        stitch_url = _extract_url(screen_payload) or _extract_url(create_payload)
        link_html = (
            f'<a href="{html.escape(stitch_url)}" target="_blank" rel="noreferrer">Open in Stitch</a>'
            if stitch_url
            else "<span>No Stitch URL returned.</span>"
        )
        payload_preview = html.escape(
            json.dumps(_materialize_payload(screen_payload), indent=2, ensure_ascii=False)[:12000]
        )
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(
            f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    body {{ margin: 0; font-family: Inter, system-ui, sans-serif; color: #1f2933; background: #f8fafc; }}
    main {{ max-width: 960px; margin: 0 auto; padding: 32px; }}
    .panel {{ background: #fff; border: 1px solid rgba(15, 23, 42, 0.1); border-radius: 8px; padding: 20px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    p {{ color: #52606d; }}
    a {{ color: #2563eb; }}
    pre {{ overflow: auto; background: #111827; color: #e5e7eb; border-radius: 6px; padding: 16px; }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>{title}</h1>
      <p>{description}</p>
      <p>Stitch MCP generated a screen for this dashboard. The MCP response did not include embeddable HTML, so OpenBench saved this artifact with the Stitch reference.</p>
      <p>{link_html}</p>
    </section>
    <section class="panel" style="margin-top: 16px;">
      <h2>Stitch MCP Response</h2>
      <pre>{payload_preview}</pre>
    </section>
  </main>
</body>
</html>
""",
            encoding="utf-8",
        )

    def _render_with_fallback(
        self,
        view_model: dict[str, Any],
        stitch: dict[str, Any],
    ) -> DashboardRenderResult:
        fallback_result = self.fallback.render(view_model)
        return DashboardRenderResult(
            file_path=fallback_result.file_path,
            size_bytes=fallback_result.size_bytes,
            metadata={
                **fallback_result.metadata,
                "adapter": {
                    "name": self.name,
                    "used": False,
                    "fallback": getattr(self.fallback, "name", type(self.fallback).__name__),
                },
                "stitch": stitch,
            },
        )


def _view_model_to_prompt(view_model: dict[str, Any]) -> str:
    serialized = json.dumps(view_model, ensure_ascii=False, indent=2)
    if len(serialized) > 30000:
        serialized = serialized[:30000] + "\n...TRUNCATED..."
    return (
        "Create a polished desktop analytics dashboard screen from this declarative "
        "OpenBench ViewModel. Preserve the KPI labels, chart titles, datasets, and "
        "section hierarchy. Use a clean professional dashboard layout with visible "
        "charts and tables. Do not invent unrelated metrics.\n\n"
        f"ViewModel JSON:\n{serialized}"
    )


def _extract_html(payload: Any) -> str | None:
    payload = _materialize_payload(payload)
    for value in _walk(payload):
        if isinstance(value, str) and "<html" in value.lower():
            return value
    return None

def _extract_html_download_url(payload: Any) -> str | None:
    payload = _materialize_payload(payload)

    structured = payload.get("result", {}).get("structuredContent", {}) if isinstance(payload, dict) else {}
    html_code = structured.get("htmlCode", {}) if isinstance(structured, dict) else {}
    url = html_code.get("downloadUrl") if isinstance(html_code, dict) else None
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        return url

    for value in _walk(payload):
        if isinstance(value, dict):
            html_code = value.get("htmlCode")
            if isinstance(html_code, dict):
                url = html_code.get("downloadUrl")
                if isinstance(url, str) and url.startswith(("https://", "http://")):
                    return url

    return None

def _extract_project_id(payload: Any) -> str | None:
    payload = _materialize_payload(payload)
    for value in _walk(payload):
        if not isinstance(value, str):
            continue
        match = _PROJECT_RE.search(value)
        if match:
            return match.group(1)
        if value.isdigit() and len(value) >= 8:
            return value
    return None


def _extract_screen_id(payload: Any) -> str | None:
    payload = _materialize_payload(payload)
    for value in _walk(payload):
        if isinstance(value, str):
            match = _SCREEN_RE.search(value)
            if match:
                return match.group(1)
    return None


def _extract_url(payload: Any) -> str | None:
    payload = _materialize_payload(payload)
    for value in _walk(payload):
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            return value
    return None


def _materialize_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        stripped = payload.strip()
        if stripped.startswith(("{", "[")):
            try:
                return _materialize_payload(json.loads(stripped))
            except ValueError:
                return payload
        return payload
    if isinstance(payload, list):
        return [_materialize_payload(item) for item in payload]
    if isinstance(payload, dict):
        return {key: _materialize_payload(value) for key, value in payload.items()}
    return payload


def _walk(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)
    else:
        yield value
