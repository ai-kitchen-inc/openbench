"""Standalone MCP protocol smoke tester for dashboard-generator-mcp."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

MCP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MCP_ROOT.parents[1]
SRC_ROOT = REPO_ROOT / "src"

for path in (SRC_ROOT, MCP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from openbench.mcp.client import MCPClient  # noqa: E402
from openbench.mcp.config import (  # noqa: E402
    MCPClientConfig,
    MCPPolicyConfig,
    MCPServerConnectionConfig,
)

EXPECTED_TOOLS = {
    "dashboard_generator.generate_dashboard",
    "dashboard_generator.load_dashboard",
    "dashboard_generator.search_dashboards",
}


def _local_server() -> MCPServerConnectionConfig:
    return MCPServerConnectionConfig(
        command=sys.executable,
        args=["-m", "app.mcp_server", "--transport", "stdio"],
        cwd=str(MCP_ROOT),
        env={
            "PYTHONPATH": os.pathsep.join([str(SRC_ROOT), str(MCP_ROOT)]),
            "OPENBENCH_EXPORT_DIR": os.getenv(
                "OPENBENCH_EXPORT_DIR",
                str(MCP_ROOT / "outputs"),
            ),
            "OPENBENCH_EXPORT_URL_BASE": os.getenv("OPENBENCH_EXPORT_URL_BASE", "/outputs"),
            "OPENBENCH_DASHBOARD_STATE_PATH": os.getenv(
                "OPENBENCH_DASHBOARD_STATE_PATH",
                str(MCP_ROOT / ".openbench" / "dashboard_generator_state.json"),
            ),
            "DASHBOARD_RENDER_ADAPTER": os.getenv("DASHBOARD_RENDER_ADAPTER", "default"),
        },
        namespace="dashboard_generator",
        allowed=True,
        timeout_seconds=60.0,
        retries=0,
    )


def _docker_server(image: str) -> MCPServerConnectionConfig:
    return MCPServerConnectionConfig(
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "-e",
            "OPENBENCH_EXPORT_DIR=/outputs",
            "-e",
            "OPENBENCH_EXPORT_URL_BASE=/outputs",
            "-e",
            "OPENBENCH_DASHBOARD_STATE_PATH=/outputs/dashboard_generator_state.json",
            "-e",
            f"DASHBOARD_RENDER_ADAPTER={os.getenv('DASHBOARD_RENDER_ADAPTER', 'default')}",
            image,
        ],
        namespace="dashboard_generator",
        allowed=True,
        timeout_seconds=60.0,
        retries=0,
    )


def _format(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def run(mode: str, image: str) -> int:
    server = _docker_server(image) if mode == "docker" else _local_server()
    client = MCPClient(
        MCPClientConfig(
            servers={"dashboard_generator": server},
            policy=MCPPolicyConfig(max_timeout_seconds=60.0),
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

        print("\nPASS: MCP server discovery succeeded.")
        return 0
    finally:
        client.close_sync()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["local", "docker"], default="local")
    parser.add_argument("--image", default="openbench/dashboard-generator-mcp:cpu")
    args = parser.parse_args()
    return run(args.mode, args.image)


if __name__ == "__main__":
    raise SystemExit(main())
