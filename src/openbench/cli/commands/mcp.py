"""MCP server/client commands."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from openbench.mcp.config import MCPConfig, MCPServerConfig
from openbench.mcp.server import OpenBenchMCPServer

console = Console()


@click.group()
def mcp() -> None:
    """Serve and inspect OpenBench MCP integrations."""


def _load_config(path: str | None) -> MCPConfig:
    if path:
        return MCPConfig.from_file(Path(path))
    return MCPConfig()


@mcp.command()
@click.option("--config", "config_path", help="Path to OpenBench MCP YAML/JSON config.")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "streamable-http", "sse"]),
    help="Override configured transport.",
)
@click.option("--host", help="Host for Streamable HTTP transport.")
@click.option("--port", type=int, help="Port for Streamable HTTP transport.")
def serve(
    config_path: str | None,
    transport: str | None,
    host: str | None,
    port: int | None,
) -> None:
    """Run the OpenBench MCP server."""
    config = _load_config(config_path)
    server_config = config.server.model_copy()
    if transport:
        server_config.transport = transport  # type: ignore[assignment]
    if host:
        server_config.host = host
    if port is not None:
        server_config.port = port
    server = OpenBenchMCPServer(server_config)
    server.run(transport=server_config.transport, host=server_config.host, port=server_config.port)


@mcp.command("list-tools")
@click.option("--config", "config_path", help="Path to OpenBench MCP YAML/JSON config.")
@click.option("--json-output", is_flag=True, help="Print JSON instead of a table.")
def list_tools(config_path: str | None, json_output: bool) -> None:
    """List tools exposed by the configured OpenBench MCP server."""
    config = _load_config(config_path)
    server = OpenBenchMCPServer(config.server)
    tools = server.list_tools()
    if json_output:
        console.print(json.dumps(tools, indent=2))
        return

    table = Table(title=f"MCP Tools: {config.server.name}")
    table.add_column("Name", style="cyan")
    table.add_column("Risk", style="magenta")
    table.add_column("Skill", style="green")
    table.add_column("Description")
    for tool in tools:
        meta = tool.get("_meta", {})
        table.add_row(
            tool["name"],
            meta.get("dev.openbench/risk", ""),
            meta.get("dev.openbench/sourceSkill", ""),
            tool.get("description", "")[:90],
        )
    console.print(table)


@mcp.command()
@click.option("--config", "config_path", help="Path to OpenBench MCP YAML/JSON config.")
def inspect(config_path: str | None) -> None:
    """Inspect configured server resources, prompts, tools, and policy."""
    config = _load_config(config_path)
    server = OpenBenchMCPServer(config.server)
    payload = {
        "server": config.server.model_dump(mode="json"),
        "tool_count": len(server.list_tools()),
        "resource_count": len(server.list_resources()),
        "prompt_count": len(server.list_prompts()),
        "tools": [tool["name"] for tool in server.list_tools()],
        "resources": [resource["uri"] for resource in server.list_resources()],
        "prompts": [prompt["name"] for prompt in server.list_prompts()],
    }
    console.print(json.dumps(payload, indent=2))


@mcp.command("init-config")
@click.argument("path", required=False)
def init_config(path: str | None) -> None:
    """Write an example MCP config."""
    target = Path(path or "openbench.mcp.yaml")
    if target.exists() and not click.confirm(f"{target} exists. Overwrite?"):
        return
    config = MCPConfig(server=MCPServerConfig())
    text = (
        "mcp:\n"
        f"  server:\n"
        f"    name: {config.server.name}\n"
        "    include_sdk_tools: true\n"
        "    transport: stdio\n"
        "    host: 127.0.0.1\n"
        "    port: 8000\n"
        "    policy:\n"
        "      allowed_servers: [openbench]\n"
        "      require_approval_for_risks: [write, artifact_write, external_network, destructive]\n"
    )
    target.write_text(text, encoding="utf-8")
    console.print(f"[green]Wrote[/green] {target}")
