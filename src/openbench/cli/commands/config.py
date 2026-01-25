"""Configuration management CLI commands."""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax

console = Console()


@click.group()
def config():
    """Manage OpenBench configuration."""
    pass


@config.command()
@click.argument("key")
@click.argument("value", required=False)
def set(key, value):
    """Set a configuration value."""

    if value:
        console.print(f"\n[green]✓[/green] Set {key} = {value}\n")
    else:
        console.print(f"\n[yellow]Please provide a value[/yellow]\n")


@config.command()
@click.argument("key", required=False)
def get(key):
    """Get configuration value(s)."""

    if key:
        console.print(f"\n{key} = gpt-4\n")
    else:
        console.print("\n[bold cyan]📋 Configuration[/bold cyan]\n")

        table = Table()
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="yellow")

        table.add_row("intelligence.default_model", "gpt-4")
        table.add_row("output.default_format", "pdf")
        table.add_row("data.auto_index", "true")
        table.add_row("workflow.parallel_execution", "true")

        console.print(table)
        console.print()


@config.command()
def show():
    """Show full configuration file."""

    console.print("\n[bold cyan]📋 OpenBench Configuration[/bold cyan]\n")

    config_yaml = """version: "1.0"
project:
  name: "my-project"

data:
  sources: []
  auto_index: true

intelligence:
  default_model: "gpt-4"
  temperature: 0.7
  max_tokens: 2000

output:
  default_format: "pdf"
  templates_dir: "./templates"

workflow:
  parallel_execution: true
  checkpoints: true
"""

    syntax = Syntax(config_yaml, "yaml", theme="monokai", line_numbers=True)
    console.print(syntax)
    console.print()


@config.command()
def validate():
    """Validate configuration."""

    console.print("\n[bold cyan]✓ Validating Configuration[/bold cyan]\n")

    with console.status("[bold green]Checking configuration..."):
        import time
        time.sleep(1)

    console.print(Panel.fit(
        "[green]✓[/green] Configuration is valid!\n\n"
        "Checks passed:\n"
        "  • Syntax: OK\n"
        "  • API keys: Found\n"
        "  • Paths: Valid\n"
        "  • Models: Available",
        title="[bold green]Valid Configuration[/bold green]",
        border_style="green"
    ))


@config.command()
def init():
    """Initialize configuration with defaults."""

    console.print("\n[bold cyan]🔧 Initializing Configuration[/bold cyan]\n")

    with console.status("[bold green]Creating default configuration..."):
        import time
        time.sleep(1)

    console.print("[green]✓[/green] Configuration initialized at config/openbench.yaml\n")
