"""Standalone MCP protocol smoke tester for the generic API MCP server.

This script uses OpenBench's MCP client to spawn either the Docker container or
the local Python server over stdio, then discovers tools. Pass `--call` to call
`fetch_generic_api_data` with a provided endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
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

EXPECTED_TOOLS = {"generic_api.fetch_generic_api_data"}


def _docker_server(image: str) -> MCPServerConnectionConfig:
    return MCPServerConnectionConfig(
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "-e",
            "GENERIC_API_USERNAME",
            "-e",
            "GENERIC_API_PASSWORD",
            "-e",
            "GENERIC_API_TIMEOUT_SECONDS",
            image,
        ],
        namespace="generic_api",
        allowed=True,
        timeout_seconds=30.0,
        retries=0,
    )


def _local_server() -> MCPServerConnectionConfig:
    venv_python = EXAMPLE_ROOT / ".venv" / "Scripts" / "python.exe"
    command = str(venv_python if venv_python.exists() else Path(sys.executable))
    root = EXAMPLE_ROOT.resolve().as_posix()
    env = {
        "PYTHONPATH": root,
        "GENERIC_API_USERNAME": os.getenv("GENERIC_API_USERNAME", ""),
        "GENERIC_API_PASSWORD": os.getenv("GENERIC_API_PASSWORD", ""),
        "GENERIC_API_TIMEOUT_SECONDS": os.getenv("GENERIC_API_TIMEOUT_SECONDS", "30"),
    }
    return MCPServerConnectionConfig(
        command=command,
        args=["-m", "app.mcp_server", "--transport", "stdio"],
        env=env,
        namespace="generic_api",
        allowed=True,
        timeout_seconds=30.0,
        retries=0,
    )


def _format(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def run(mode: str, image: str, call: bool, endpoint_url: str | None) -> int:
    server = _docker_server(image) if mode == "docker" else _local_server()
    client = MCPClient(
        MCPClientConfig(
            servers={"generic_api": server},
            policy=MCPPolicyConfig(max_timeout_seconds=30.0),
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

        if call:
            if not endpoint_url:
                print("\n--endpoint-url is required when using --call.")
                return 2
            result = client.call_tool_sync(
                "generic_api.fetch_generic_api_data",
                {"endpoint_url": endpoint_url},
            )
            print("\nfetch_generic_api_data result:")
            print(_format(result))

        print("\nPASS: MCP server discovery succeeded.")
        return 0
    finally:
        client.close_sync()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["local", "docker"], default="local")
    parser.add_argument("--image", default="openbench/generic-api-mcp:cpu")
    parser.add_argument("--endpoint-url")
    parser.add_argument("--call", action="store_true")
    args = parser.parse_args()
    return run(args.mode, args.image, args.call, args.endpoint_url)


if __name__ == "__main__":
    raise SystemExit(main())
