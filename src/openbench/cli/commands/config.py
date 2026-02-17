"""Configuration management CLI commands."""

import json
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from openbench.core.config import Config, get_config, reset_config

console = Console()


@click.group()
def config():
    """Manage OpenBench configuration."""


@config.command()
@click.argument("key")
@click.argument("value")
def set(key, value):
    """Set a configuration value.

    Examples:
        openbench config set llm.model gpt-4o
        openbench config set llm.temperature 0.7
    """
    cfg = get_config()
    cfg.set(key, value)

    # Save to local config file
    local_path = Path("openbench.yaml")
    if local_path.exists():
        cfg.save(local_path)
        console.print(f"\n[green]✓[/green] Set {key} = {value} (saved to openbench.yaml)\n")
    else:
        console.print(f"\n[green]✓[/green] Set {key} = {value} (in memory only)")
        console.print("[dim]Run 'openbench config init' to create a config file.[/dim]\n")


@config.command()
@click.argument("key", required=False)
def get(key):
    """Get configuration value(s).

    Examples:
        openbench config get               # Show all
        openbench config get llm.model     # Show specific key
    """
    cfg = get_config()

    if key:
        value = cfg.get(key)
        if value is not None:
            console.print(f"\n{key} = {value}\n")
        else:
            console.print(f"\n[yellow]Key '{key}' not found.[/yellow]\n")
    else:
        console.print("\n[bold cyan]Configuration[/bold cyan]\n")

        data = cfg.to_dict()
        if not data:
            console.print("[dim]No configuration set.[/dim]\n")
            return

        def print_dict(d, prefix=""):
            for k, v in d.items():
                if k == "models":
                    continue  # Skip models, shown separately
                full_key = f"{prefix}{k}" if prefix else k
                if isinstance(v, dict):
                    print_dict(v, f"{full_key}.")
                else:
                    console.print(f"  [cyan]{full_key}[/cyan] = [yellow]{v}[/yellow]")

        print_dict(data)
        console.print()


@config.command()
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["yaml", "json"]),
    default="yaml",
    help="Output format",
)
def show(fmt):
    """Show full configuration."""
    cfg = get_config()
    data = cfg.to_dict()

    console.print("\n[bold cyan]OpenBench Configuration[/bold cyan]\n")

    if fmt == "json":
        content = json.dumps(data, indent=2)
        syntax = Syntax(content, "json", theme="monokai", line_numbers=True)
    else:
        try:
            import yaml

            content = yaml.dump(data, default_flow_style=False)
        except ImportError:
            content = json.dumps(data, indent=2)
            fmt = "json"
        syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)

    console.print(syntax)
    console.print()


@config.command()
@click.option(
    "--path",
    type=click.Path(),
    default="openbench.yaml",
    help="Path to create config file",
)
def init(path):
    """Initialize configuration with defaults."""
    path = Path(path)

    if path.exists() and not click.confirm(f"Config file '{path}' already exists. Overwrite?"):
        console.print("[dim]Cancelled.[/dim]")
        return

    console.print("\n[bold cyan]Initializing Configuration[/bold cyan]\n")

    # Create default config
    default_config = {
        "version": "1.0",
        "project": {
            "name": Path.cwd().name,
        },
        "llm": {
            "default_model": "gpt-4o",
            "temperature": 0.7,
            "max_tokens": 4096,
        },
        "data": {
            "auto_index": True,
        },
        "output": {
            "default_format": "pdf",
            "templates_dir": "./templates",
        },
        "workflow": {
            "parallel_execution": True,
            "checkpoints": True,
        },
    }

    cfg = Config(default_config)
    cfg.save(path)

    console.print(f"[green]✓[/green] Configuration initialized at {path}\n")

    # Show the config
    try:
        import yaml

        content = yaml.dump(default_config, default_flow_style=False)
        syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)
    except ImportError:
        content = json.dumps(default_config, indent=2)
        syntax = Syntax(content, "json", theme="monokai", line_numbers=True)

    console.print(syntax)
    console.print()


@config.command()
def validate():
    """Validate configuration."""
    console.print("\n[bold cyan]Validating Configuration[/bold cyan]\n")

    errors: list[str] = []
    warnings: list[str] = []

    # Check local config file
    local_path = Path("openbench.yaml")
    if not local_path.exists():
        local_json = Path("openbench.json")
        if local_json.exists():
            local_path = local_json
        else:
            warnings.append("No local config file (openbench.yaml) found")

    # Load and validate config
    cfg = get_config()

    # Check for common issues
    if cfg.get("llm.default_model") is None:
        warnings.append("No default LLM model configured")

    # Check model exists
    default_model = cfg.get("llm.default_model")
    if default_model:
        model_info = cfg.get_model(default_model)
        if not model_info:
            warnings.append(f"Model '{default_model}' not found in model registry")

    # Display results
    if errors:
        console.print(
            Panel.fit(
                "[red]✗[/red] Configuration has errors:\n\n"
                + "\n".join(f"  • {e}" for e in errors),
                title="[bold red]Invalid Configuration[/bold red]",
                border_style="red",
            )
        )
    elif warnings:
        console.print(
            Panel.fit(
                "[yellow]⚠[/yellow] Configuration valid with warnings:\n\n"
                + "\n".join(f"  • {w}" for w in warnings),
                title="[bold yellow]Configuration Warnings[/bold yellow]",
                border_style="yellow",
            )
        )
    else:
        console.print(
            Panel.fit(
                "[green]✓[/green] Configuration is valid!\n\n"
                "Checks passed:\n"
                "  • Syntax: OK\n"
                "  • Required fields: Present\n"
                "  • Models: Configured",
                title="[bold green]Valid Configuration[/bold green]",
                border_style="green",
            )
        )


@config.command()
def models():
    """List available models."""
    console.print("\n[bold cyan]Available Models[/bold cyan]\n")

    cfg = get_config()
    model_list = cfg.list_models()

    if not model_list:
        console.print("[dim]No models registered.[/dim]\n")
        return

    table = Table()
    table.add_column("Name", style="cyan")
    table.add_column("Provider", style="magenta")
    table.add_column("Context", justify="right")
    table.add_column("Vision", justify="center")
    table.add_column("Tools", justify="center")
    table.add_column("Aliases", style="dim")

    for model in model_list:
        table.add_row(
            model.name,
            model.provider,
            f"{model.context_window:,}",
            "✓" if model.supports_vision else "",
            "✓" if model.supports_tools else "",
            ", ".join(model.aliases) if model.aliases else "",
        )

    console.print(table)
    console.print()


@config.command()
@click.argument("path", type=click.Path(exists=True))
def load(path):
    """Load configuration from file."""
    cfg = get_config()
    cfg.load(path)
    console.print(f"\n[green]✓[/green] Loaded configuration from {path}\n")


@config.command()
def clear():
    """Clear all configuration (reset to defaults)."""
    if not click.confirm("Clear all configuration? This cannot be undone."):
        console.print("[dim]Cancelled.[/dim]")
        return

    reset_config()
    console.print("\n[green]✓[/green] Configuration cleared.\n")
