"""Provider management CLI commands."""

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from openbench.core.providers import (
    ProviderConfig,
    ProviderType,
    get_provider_service,
)

console = Console()


def get_provider_type_choice():
    """Get provider type from user."""
    choices = [pt.value for pt in ProviderType]
    return click.Choice(choices)


@click.group()
def provider():
    """Manage providers (LLM, Vector, Storage, etc.)."""


@provider.command("add")
@click.argument("name")
@click.option(
    "--type",
    "provider_type",
    type=get_provider_type_choice(),
    required=True,
    help="Provider type (llm, embedding, vector, storage, voice)",
)
@click.option(
    "--provider", "provider_name", required=True, help="Provider name (e.g., openai, pinecone)"
)
@click.option(
    "--plugin", "plugin_type", required=True, help="Plugin type (e.g., chat, vector, blob)"
)
@click.option("--api-key", help="API key for the provider")
@click.option("--default", is_flag=True, help="Set as default for this type")
@click.option("--setting", multiple=True, help="Additional settings (key=value)")
def add(name, provider_type, provider_name, plugin_type, api_key, default, setting):
    """Add a new provider configuration."""
    console.print(f"\n[bold cyan]Adding Provider: {name}[/bold cyan]\n")

    # Build credentials
    credentials = {}
    if api_key:
        credentials["api_key"] = api_key

    # Build settings from key=value pairs
    settings = {}
    for s in setting:
        if "=" in s:
            key, value = s.split("=", 1)
            # Try to parse as number
            try:
                if "." in value:
                    settings[key] = float(value)
                else:
                    settings[key] = int(value)
            except ValueError:
                settings[key] = value

    # Create config
    config = ProviderConfig(
        name=name,
        provider_type=ProviderType(provider_type),
        provider=provider_name,
        plugin_type=plugin_type,
        credentials=credentials,
        settings=settings,
        is_default=default,
    )

    # Save to service
    service = get_provider_service()
    service.configure(config)

    console.print(
        Panel.fit(
            f"[green]✓[/green] Provider '{name}' added successfully!\n\n"
            f"Type: {provider_type}\n"
            f"Provider: {provider_name}\n"
            f"Plugin: {plugin_type}\n"
            f"Default: {'Yes' if default else 'No'}",
            title="[bold green]Provider Added[/bold green]",
            border_style="green",
        )
    )


@provider.command("list")
@click.option("--type", "provider_type", type=get_provider_type_choice(), help="Filter by type")
@click.option("--enabled-only", is_flag=True, help="Show only enabled providers")
def list_providers(provider_type, enabled_only):
    """List all configured providers."""
    console.print("\n[bold cyan]Configured Providers[/bold cyan]\n")

    service = get_provider_service()

    pt = ProviderType(provider_type) if provider_type else None
    providers = service.list(provider_type=pt, enabled_only=enabled_only)

    if not providers:
        console.print("[dim]No providers configured.[/dim]")
        console.print("\nAdd a provider with:")
        console.print(
            "  openbench provider add my-llm --type llm --provider openai --plugin chat\n"
        )
        return

    table = Table()
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Provider", style="yellow")
    table.add_column("Plugin", style="blue")
    table.add_column("Default", style="green")
    table.add_column("Enabled", style="green")

    for p in providers:
        table.add_row(
            p.name,
            p.provider_type.value,
            p.provider,
            p.plugin_type,
            "✓" if p.is_default else "",
            "✓" if p.enabled else "✗",
        )

    console.print(table)
    console.print()


@provider.command("show")
@click.argument("name")
def show(name):
    """Show details of a specific provider."""
    service = get_provider_service()
    config = service.get(name)

    if not config:
        console.print(f"\n[red]Provider '{name}' not found.[/red]\n")
        return

    console.print(f"\n[bold cyan]Provider: {name}[/bold cyan]\n")

    table = Table(show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="yellow")

    table.add_row("Type", config.provider_type.value)
    table.add_row("Provider", config.provider)
    table.add_row("Plugin Type", config.plugin_type)
    table.add_row("Default", "Yes" if config.is_default else "No")
    table.add_row("Enabled", "Yes" if config.enabled else "No")

    if config.settings:
        table.add_row("Settings", str(config.settings))

    if config.credentials:
        # Mask sensitive values
        masked = {k: "***" if "key" in k.lower() else v for k, v in config.credentials.items()}
        table.add_row("Credentials", str(masked))

    console.print(table)
    console.print()


@provider.command("remove")
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
def remove(name, force):
    """Remove a provider configuration."""
    service = get_provider_service()

    if not service.get(name):
        console.print(f"\n[red]Provider '{name}' not found.[/red]\n")
        return

    if not force and not Confirm.ask(f"Remove provider '{name}'?"):
        console.print("[dim]Cancelled.[/dim]")
        return

    service.remove(name)
    console.print(f"\n[green]✓[/green] Provider '{name}' removed.\n")


@provider.command("set-default")
@click.argument("name")
def set_default(name):
    """Set a provider as the default for its type."""
    service = get_provider_service()

    config = service.get(name)
    if not config:
        console.print(f"\n[red]Provider '{name}' not found.[/red]\n")
        return

    if service.set_default(name):
        console.print(
            f"\n[green]✓[/green] '{name}' is now the default {config.provider_type.value} provider.\n"
        )
    else:
        console.print("\n[red]Failed to set default.[/red]\n")


@provider.command("test")
@click.argument("name")
def test(name):
    """Test connection to a provider."""
    service = get_provider_service()

    if not service.get(name):
        console.print(f"\n[red]Provider '{name}' not found.[/red]\n")
        return

    console.print(f"\n[bold cyan]Testing Provider: {name}[/bold cyan]\n")

    with console.status("[bold green]Testing connection..."):
        result = service.test_connection(name)

    if result["success"]:
        console.print(
            Panel.fit(
                f"[green]✓[/green] Connection successful!\n\n{result.get('message', '')}",
                title="[bold green]Test Passed[/bold green]",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel.fit(
                f"[red]✗[/red] Connection failed\n\n{result.get('error', 'Unknown error')}",
                title="[bold red]Test Failed[/bold red]",
                border_style="red",
            )
        )


@provider.command("enable")
@click.argument("name")
def enable(name):
    """Enable a provider."""
    service = get_provider_service()

    config = service.get(name)
    if not config:
        console.print(f"\n[red]Provider '{name}' not found.[/red]\n")
        return

    config.enabled = True
    service.configure(config)
    console.print(f"\n[green]✓[/green] Provider '{name}' enabled.\n")


@provider.command("disable")
@click.argument("name")
def disable(name):
    """Disable a provider."""
    service = get_provider_service()

    config = service.get(name)
    if not config:
        console.print(f"\n[red]Provider '{name}' not found.[/red]\n")
        return

    config.enabled = False
    service.configure(config)
    console.print(f"\n[yellow]✓[/yellow] Provider '{name}' disabled.\n")
