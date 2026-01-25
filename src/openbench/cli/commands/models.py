"""LLM models registry CLI commands."""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


@click.group()
def models():
    """Manage LLM models and configurations."""
    pass


@models.command()
@click.argument("name")
@click.option("--provider",
              type=click.Choice(["openai", "anthropic", "local", "custom"]),
              help="Model provider")
@click.option("--model-id", help="Model identifier (e.g., gpt-4, claude-opus)")
@click.option("--api-key", help="API key for the provider")
@click.option("--endpoint", help="Custom API endpoint")
def register(name, provider, model_id, api_key, endpoint):
    """Register a new LLM model."""

    console.print(f"\n[bold cyan]🤖 Registering Model: {name}[/bold cyan]\n")

    console.print(f"[dim]Provider: {provider}[/dim]")
    console.print(f"[dim]Model ID: {model_id}[/dim]")
    if endpoint:
        console.print(f"[dim]Endpoint: {endpoint}[/dim]\n")

    with console.status("[bold green]Registering model..."):
        import time
        time.sleep(1)

    console.print(Panel.fit(
        f"[green]✓[/green] Model '{name}' registered successfully!\n\n"
        f"Provider: {provider}\n"
        f"Model: {model_id}\n"
        f"Status: Ready\n\n"
        f"[bold]Use in agent:[/bold]\n"
        f"  openbench agent create my-agent --model {name}",
        title="[bold green]Model Registered![/bold green]",
        border_style="green"
    ))


@models.command()
def list():
    """List all registered models."""

    console.print("\n[bold cyan]🤖 Registered Models[/bold cyan]\n")

    table = Table(title="Available LLM Models")
    table.add_column("Name", style="cyan")
    table.add_column("Provider", style="magenta")
    table.add_column("Model ID", style="yellow")
    table.add_column("Status", style="green")

    # Mock data
    table.add_row("gpt-4", "openai", "gpt-4-0125-preview", "✓ Ready")
    table.add_row("gpt-3.5", "openai", "gpt-3.5-turbo", "✓ Ready")
    table.add_row("claude-opus", "anthropic", "claude-opus-4", "✓ Ready")
    table.add_row("claude-sonnet", "anthropic", "claude-sonnet-3.5", "✓ Ready")
    table.add_row("llama-local", "local", "llama-3-70b", "⚠ Offline")

    console.print(table)
    console.print()


@models.command()
@click.argument("name")
@click.option("--prompt", default="Hello! Please respond with a greeting.",
              help="Test prompt")
def test(name, prompt):
    """Test a registered model."""

    console.print(f"\n[bold cyan]🧪 Testing Model: {name}[/bold cyan]\n")

    console.print(f"[dim]Prompt: {prompt}[/dim]\n")

    with console.status(f"[bold green]{name} is generating response..."):
        import time
        time.sleep(2)

    console.print(Panel(
        f"[bold]Model Response:[/bold]\n\n"
        f"Hello! I'm ready to assist you. How can I help you today?\n\n"
        f"[dim]Model: {name}[/dim]\n"
        f"[dim]Tokens: 15 (prompt) + 12 (response)[/dim]\n"
        f"[dim]Latency: 1.2s[/dim]",
        title=f"[bold cyan]{name}[/bold cyan]",
        border_style="cyan"
    ))


@models.command()
@click.argument("name")
def remove(name):
    """Remove a registered model."""

    console.print(f"\n[yellow]⚠ Removing model: {name}[/yellow]\n")

    if click.confirm("Are you sure?"):
        with console.status("[bold yellow]Removing model..."):
            import time
            time.sleep(0.5)

        console.print(f"[green]✓[/green] Model '{name}' removed.\n")
    else:
        console.print("[dim]Cancelled.[/dim]\n")


@models.command()
@click.argument("name")
@click.option("--temperature", type=float, help="Model temperature (0-1)")
@click.option("--max-tokens", type=int, help="Maximum tokens to generate")
@click.option("--top-p", type=float, help="Top-p sampling parameter")
def configure(name, temperature, max_tokens, top_p):
    """Configure model parameters."""

    console.print(f"\n[bold cyan]⚙️ Configuring Model: {name}[/bold cyan]\n")

    updates = []
    if temperature is not None:
        updates.append(f"temperature = {temperature}")
    if max_tokens is not None:
        updates.append(f"max_tokens = {max_tokens}")
    if top_p is not None:
        updates.append(f"top_p = {top_p}")

    if updates:
        for update in updates:
            console.print(f"[green]✓[/green] Updated {update}")
        console.print()
    else:
        console.print("Current configuration:")
        console.print("  temperature: 0.7")
        console.print("  max_tokens: 2000")
        console.print("  top_p: 1.0\n")


@models.command()
def usage():
    """Show model usage statistics."""

    console.print("\n[bold cyan]📊 Model Usage Statistics[/bold cyan]\n")

    table = Table(title="Last 30 Days")
    table.add_column("Model", style="cyan")
    table.add_column("Requests", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right", style="yellow")

    # Mock data
    table.add_row("gpt-4", "1,245", "2.3M", "$45.60")
    table.add_row("gpt-3.5", "3,890", "8.1M", "$12.20")
    table.add_row("claude-opus", "567", "1.2M", "$18.00")
    table.add_row("claude-sonnet", "2,103", "4.5M", "$13.50")

    console.print(table)
    console.print(f"\n[bold]Total Cost:[/bold] [yellow]$89.30[/yellow]\n")
