"""Standalone MCP protocol smoke tester for the image-search MCP server.

This script bypasses Codex's MCP auto-loader. It uses OpenBench's MCP client to
spawn either the Docker container or the local Python server over stdio, then
discovers tools and calls `list_index_stats`.
"""

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
    "image_search.search_similar_images",
    "image_search.index_images",
    "image_search.rebuild_index",
    "image_search.list_index_stats",
    "image_search.remove_image",
}


def _as_posix(path: Path) -> str:
    return path.resolve().as_posix()


def _host_huggingface_cache() -> Path | None:
    """Return the host Hugging Face cache directory when a login token exists."""
    candidates = [
        Path.home() / ".cache" / "huggingface",
        Path.home() / ".huggingface",
    ]
    for candidate in candidates:
        if (candidate / "token").exists():
            return candidate
    return None


def _docker_server(image: str) -> MCPServerConnectionConfig:
    data_path = _as_posix(EXAMPLE_ROOT / "data")
    models_path = _as_posix(EXAMPLE_ROOT / "models")
    hf_cache = _host_huggingface_cache()
    hf_args = []
    if hf_cache is not None:
        hf_args = [
            "-v",
            f"{_as_posix(hf_cache)}:/home/image-search/.cache/huggingface:ro",
            "-e",
            "HF_HOME=/home/image-search/.cache/huggingface",
        ]
    return MCPServerConnectionConfig(
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "-v",
            f"{data_path}:/data",
            "-v",
            f"{models_path}:/models",
            *hf_args,
            "-e",
            "DATA_PATH=/data",
            "-e",
            "INDEX_PATH=/data/index",
            "-e",
            "MODEL_CACHE_PATH=/models",
            "-e",
            "DEVICE=cpu",
            "-e",
            "HF_HUB_DISABLE_PROGRESS_BARS=1",
            "-e",
            "TRANSFORMERS_VERBOSITY=error",
            image,
        ],
        namespace="image_search",
        allowed=True,
        timeout_seconds=120.0,
        retries=0,
    )


def _local_server() -> MCPServerConnectionConfig:
    venv_python = EXAMPLE_ROOT / ".venv" / "Scripts" / "python.exe"
    command = str(venv_python if venv_python.exists() else Path(sys.executable))
    root = _as_posix(EXAMPLE_ROOT)
    return MCPServerConnectionConfig(
        command=command,
        args=["-m", "app.mcp_server", "--transport", "stdio"],
        env={
            "PYTHONPATH": root,
            "DATA_PATH": f"{root}/data",
            "INDEX_PATH": f"{root}/data/index",
            "MODEL_CACHE_PATH": f"{root}/models",
            "DEVICE": "cpu",
        },
        namespace="image_search",
        allowed=True,
        timeout_seconds=120.0,
        retries=0,
    )


def _format(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _assert_ok_tool_result(name: str, result: Any) -> None:
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(f"{name} returned an error: {result['error']}")


def run(
    mode: str,
    image: str,
    discovery_only: bool,
    real_index: bool,
    max_items: int,
    batch_size: int,
) -> int:
    server = _docker_server(image) if mode == "docker" else _local_server()
    client = MCPClient(
        MCPClientConfig(
            servers={"image_search": server},
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

        stats = client.call_tool_sync("image_search.list_index_stats", {})
        _assert_ok_tool_result("list_index_stats", stats)
        print("\nStats:")
        print(_format(stats))

        if real_index:
            print(f"\nIndexing {max_items} CIFAR-10 train images...")
            index_result = client.call_tool_sync(
                "image_search.index_images",
                {"max_items": max_items, "batch_size": batch_size},
                timeout_seconds=3600.0,
                approved=True,
            )
            _assert_ok_tool_result("index_images", index_result)
            print(_format(index_result))

            print("\nSearching with CIFAR-10 test image 0...")
            search_result = client.call_tool_sync(
                "image_search.search_similar_images",
                {"cifar10_test_index": 0, "top_k": 3},
                timeout_seconds=3600.0,
                approved=True,
            )
            _assert_ok_tool_result("search_similar_images", search_result)
            print(_format(search_result))

        print("\nPASS: MCP server discovery and tool call succeeded.")
        return 0
    finally:
        client.close_sync()


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the image-search MCP server.")
    parser.add_argument("--mode", choices=["docker", "local"], default="docker")
    parser.add_argument("--image", default="openbench/image-search-mcp:cpu")
    parser.add_argument(
        "--discovery-only",
        action="store_true",
        help="Only verify MCP initialize/tools/list. This avoids vector backend initialization.",
    )
    parser.add_argument(
        "--real-index",
        action="store_true",
        help="Also run index_images and search_similar_images. This may download CIFAR-10/model weights.",
    )
    parser.add_argument("--max-items", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args()

    try:
        return run(
            mode=args.mode,
            image=args.image,
            discovery_only=args.discovery_only,
            real_index=args.real_index,
            max_items=args.max_items,
            batch_size=args.batch_size,
        )
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
