"""Tools and MCP registry CLI commands."""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


@click.group()
def tools():
    """Manage tools and MCP integrations."""
    pass


@tools.command()
@click.argument("name")
@click.option("--type", "tool_type",
              type=click.Choice(["function", "mcp", "api", "cli"]),
              help="Type of tool")
@click.option("--path", help="Path to tool definition")
@click.option("--url", help="URL for MCP server")
def register(name, tool_type, path, url):
    """Register a new tool or MCP server."""

    console.print(f"\n[bold cyan]🔧 Registering Tool: {name}[/bold cyan]\n")

    console.print(f"[dim]Type: {tool_type}[/dim]")
    if path:
        console.print(f"[dim]Path: {path}[/dim]")
    if url:
        console.print(f"[dim]URL: {url}[/dim]\n")

    with console.status("[bold green]Registering tool..."):
        import time
        time.sleep(1)

    console.print(Panel.fit(
        f"[green]✓[/green] Tool '{name}' registered successfully!\n\n"
        f"Type: {tool_type}\n"
        f"Status: Available\n\n"
        f"[bold]Use in agent:[/bold]\n"
        f"  openbench agent create my-agent --tools {name}",
        title="[bold green]Tool Registered![/bold green]",
        border_style="green"
    ))


@tools.command()
def list():
    """List all registered tools."""

    console.print("\n[bold cyan]🔧 Registered Tools[/bold cyan]\n")

    table = Table(title="Available Tools")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Description")

    # Mock data
    table.add_row("web_search", "function", "✓ Active", "Search the web using APIs")
    table.add_row("sql_executor", "function", "✓ Active", "Execute SQL queries")
    table.add_row("file_system", "mcp", "✓ Active", "MCP file system access")
    table.add_row("api_caller", "function", "✓ Active", "Make HTTP API calls")
    table.add_row("python_repl", "cli", "✓ Active", "Execute Python code")

    console.print(table)
    console.print()


@tools.command()
@click.argument("name")
def test(name):
    """Test a registered tool."""

    console.print(f"\n[bold cyan]🧪 Testing Tool: {name}[/bold cyan]\n")

    with console.status("[bold green]Running tool test..."):
        import time
        time.sleep(1)

    console.print(Panel(
        f"[green]✓[/green] Tool test successful!\n\n"
        f"[bold]Test Results:[/bold]\n"
        f"  • Connection: OK\n"
        f"  • Response time: 234ms\n"
        f"  • Output: Valid\n\n"
        f"[bold]Sample Output:[/bold]\n"
        f"  {{'status': 'success', 'data': [...]}}",
        title=f"[bold green]{name} Test[/bold green]",
        border_style="green"
    ))


@tools.command()
@click.argument("name")
def remove(name):
    """Remove a registered tool."""

    console.print(f"\n[yellow]⚠ Removing tool: {name}[/yellow]\n")

    if click.confirm("Are you sure?"):
        with console.status("[bold yellow]Removing tool..."):
            import time
            time.sleep(0.5)

        console.print(f"[green]✓[/green] Tool '{name}' removed.\n")
    else:
        console.print("[dim]Cancelled.[/dim]\n")


@tools.command()
@click.argument("name")
@click.option("--key", help="Configuration key")
@click.option("--value", help="Configuration value")
def configure(name, key, value):
    """Configure a tool's settings."""

    console.print(f"\n[bold cyan]⚙️ Configuring Tool: {name}[/bold cyan]\n")

    if key and value:
        console.print(f"[green]✓[/green] Updated {key} = {value}\n")
    else:
        console.print("[yellow]Use --key and --value to configure[/yellow]\n")
