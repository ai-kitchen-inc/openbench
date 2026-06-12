"""Standalone MCP protocol smoke tester for the SAM segmentation MCP server."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXAMPLE_ROOT.parents[1]
SRC_ROOT = REPO_ROOT / "src"

for path in (SRC_ROOT, EXAMPLE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from openbench.mcp.client import MCPClient  # noqa: E402
from openbench.mcp.config import (  # noqa: E402
    MCPClientConfig,
    MCPPolicyConfig,
    MCPServerConnectionConfig,
)

EXPECTED_TOOLS = {
    "sam_segmentation.count_objects_with_sam3",
    "sam_segmentation.service_info",
}


def _as_posix(path: Path) -> str:
    return path.resolve().as_posix()


def _docker_server(image: str) -> MCPServerConnectionConfig:
    data_path = _as_posix(EXAMPLE_ROOT / "data")
    uploads_path = _as_posix(REPO_ROOT / "examples" / "general-chat" / "uploads")
    return MCPServerConnectionConfig(
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "-v",
            f"{data_path}:/data",
            "-v",
            f"{uploads_path}:/general-chat/uploads:ro",
            "-e",
            "SAM3_MODEL_PATH=/models/sam3.pt",
            "-e",
            "SAM3_DEVICE=cpu",
            "-e",
            "SAM3_CONF=0.25",
            "-e",
            "IMAGE_INPUT_ROOTS=/general-chat/uploads,/data",
            image,
        ],
        namespace="sam_segmentation",
        allowed=True,
        timeout_seconds=180.0,
        retries=0,
    )


def _local_server() -> MCPServerConnectionConfig:
    venv_python = EXAMPLE_ROOT / ".venv" / "Scripts" / "python.exe"
    command = str(venv_python if venv_python.exists() else Path(sys.executable))
    root = _as_posix(EXAMPLE_ROOT)
    uploads_path = _as_posix(REPO_ROOT / "examples" / "general-chat" / "uploads")
    return MCPServerConnectionConfig(
        command=command,
        args=["-m", "app.mcp_server", "--transport", "stdio"],
        env={
            "PYTHONPATH": root,
            "SAM3_MODEL_PATH": f"{root}/models/sam3.pt",
            "SAM3_DEVICE": "cpu",
            "SAM3_CONF": "0.25",
            "IMAGE_INPUT_ROOTS": f"{root}/data,{uploads_path}",
        },
        namespace="sam_segmentation",
        allowed=True,
        timeout_seconds=180.0,
        retries=0,
    )


def _format(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _assert_ok_tool_result(name: str, result: Any) -> None:
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(f"{name} returned an error: {result['error']}")


def run(mode: str, image: str, discovery_only: bool) -> int:
    server = _docker_server(image) if mode == "docker" else _local_server()
    client = MCPClient(
        MCPClientConfig(
            servers={"sam_segmentation": server},
            policy=MCPPolicyConfig(max_timeout_seconds=3600.0),
        )
    )
    try:
        discovered = client.discover_sync(refresh=True)
        tools = set(discovered.list_namespaced_tools())
        missing = sorted(EXPECTED_TOOLS - tools)
        print(f"Mode: {mode}")
        print("Tools:")
        for tool in sorted(tools):
            print(f"- {tool}")
        if missing:
            print("\nMissing expected tools:")
            for tool in missing:
                print(f"- {tool}")
            return 2

        if discovery_only:
            print("\nPASS: MCP server discovery succeeded.")
            return 0

        info = client.call_tool_sync("sam_segmentation.service_info", {})
        _assert_ok_tool_result("service_info", info)
        print("\nService info:")
        print(_format(info))

        print("\nPASS: MCP server discovery and tool call succeeded.")
        return 0
    finally:
        client.close_sync()


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the SAM segmentation MCP server.")
    parser.add_argument("--mode", choices=["docker", "local"], default="docker")
    parser.add_argument("--image", default="openbench/sam-segmentation-mcp:cpu")
    parser.add_argument("--discovery-only", action="store_true")
    args = parser.parse_args()

    try:
        return run(mode=args.mode, image=args.image, discovery_only=args.discovery_only)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
