"""LLM models registry CLI commands."""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from openbench.core.config import get_config, ModelInfo

console = Console()


@click.group()
def models():
    """Manage LLM models and configurations."""
    pass


@models.command()
@click.argument("name")
@click.option("--provider", required=True, type=click.Choice(["openai", "anthropic", "google", "local"]), help="Model provider")
@click.option("--context", type=int, default=128000, help="Context window size")
@click.option("--max-output", type=int, default=4096, help="Maximum output tokens")
@click.option("--vision/--no-vision", default=False, help="Supports vision input")
@click.option("--tools/--no-tools", default=True, help="Supports tool use")
@click.option("--alias", multiple=True, help="Model aliases")
def register(name, provider, context, max_output, vision, tools, alias):
    """Register a new LLM model.

    Example:
        openbench models register gpt-4-turbo --provider openai --context 128000 --vision
    """
    console.print(f"\n[bold cyan]Registering Model: {name}[/bold cyan]\n")

    config = get_config()

    model = ModelInfo(
        name=name,
        provider=provider,
        context_window=context,
        max_output_tokens=max_output,
        supports_vision=vision,
        supports_tools=tools,
        aliases=list(alias),
    )

    config.register_model(model)

    console.print(
        Panel.fit(
            f"[green]✓[/green] Model '{name}' registered successfully!\n\n"
            f"Provider: {provider}\n"
            f"Context: {context:,} tokens\n"
            f"Vision: {'Yes' if vision else 'No'}\n"
            f"Tools: {'Yes' if tools else 'No'}",
            title="[bold green]Model Registered[/bold green]",
            border_style="green",
        )
    )


@models.command("list")
@click.option("--provider", type=click.Choice(["openai", "anthropic", "google", "local"]), help="Filter by provider")
def list_models(provider):
    """List all registered models."""
    console.print("\n[bold cyan]Registered Models[/bold cyan]\n")

    config = get_config()
    model_list = config.list_models(provider=provider)

    if not model_list:
        console.print("[dim]No models registered.[/dim]")
        console.print("\nRegister a model with:")
        console.print("  openbench models register my-model --provider openai\n")
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


@models.command()
@click.argument("name")
def show(name):
    """Show details of a specific model."""
    config = get_config()
    model = config.get_model(name)

    if not model:
        console.print(f"\n[red]Model '{name}' not found.[/red]\n")
        return

    console.print(f"\n[bold cyan]Model: {model.name}[/bold cyan]\n")

    table = Table(show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="yellow")

    table.add_row("Provider", model.provider)
    table.add_row("Context Window", f"{model.context_window:,} tokens")
    table.add_row("Max Output Tokens", f"{model.max_output_tokens:,}")
    table.add_row("Supports Vision", "Yes" if model.supports_vision else "No")
    table.add_row("Supports Tools", "Yes" if model.supports_tools else "No")

    if model.cost_per_1k_input > 0:
        table.add_row("Cost (Input)", f"${model.cost_per_1k_input:.4f} / 1K tokens")
        table.add_row("Cost (Output)", f"${model.cost_per_1k_output:.4f} / 1K tokens")

    if model.aliases:
        table.add_row("Aliases", ", ".join(model.aliases))

    console.print(table)
    console.print()


@models.command()
@click.argument("name")
@click.option("--prompt", default="Hello! Please respond with a greeting.", help="Test prompt")
def test(name, prompt):
    """Test a registered model via configured provider.

    This tests the model through ProviderService integration.
    """
    from openbench.core.providers import get_provider_service, ProviderType

    config = get_config()
    model = config.get_model(name)

    if not model:
        console.print(f"\n[red]Model '{name}' not found.[/red]\n")
        console.print("Register it first with: openbench models register ...\n")
        return

    console.print(f"\n[bold cyan]Testing Model: {name}[/bold cyan]\n")
    console.print(f"[dim]Provider: {model.provider}[/dim]")
    console.print(f"[dim]Prompt: {prompt}[/dim]\n")

    # Check if provider is configured
    service = get_provider_service()
    provider_config = service.get_default(ProviderType.LLM)

    if not provider_config:
        console.print(
            Panel.fit(
                "[yellow]No LLM provider configured.[/yellow]\n\n"
                "Configure a provider first:\n"
                f"  openbench provider add my-{model.provider} \\\n"
                f"    --type llm \\\n"
                f"    --provider {model.provider} \\\n"
                "    --plugin chat \\\n"
                "    --api-key YOUR_API_KEY \\\n"
                "    --default",
                title="[bold yellow]Provider Not Configured[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    with console.status(f"[bold green]{name} is generating response..."):
        try:
            llm = service.resolve(ProviderType.LLM, model=name)
            response = llm.generate(prompt=prompt, model=name)

            console.print(
                Panel(
                    f"[bold]Model Response:[/bold]\n\n{response.text}\n\n"
                    f"[dim]Model: {name}[/dim]\n"
                    f"[dim]Tokens: {response.tokens_used}[/dim]\n"
                    f"[dim]Cost: ${response.cost:.4f}[/dim]",
                    title=f"[bold cyan]{name}[/bold cyan]",
                    border_style="cyan",
                )
            )
        except Exception as e:
            console.print(
                Panel.fit(
                    f"[red]✗[/red] Test failed\n\n{str(e)}",
                    title="[bold red]Error[/bold red]",
                    border_style="red",
                )
            )


@models.command()
def defaults():
    """Show default models for common tasks."""
    console.print("\n[bold cyan]Default Models[/bold cyan]\n")

    config = get_config()

    table = Table()
    table.add_column("Use Case", style="cyan")
    table.add_column("Model", style="yellow")
    table.add_column("Provider", style="magenta")

    # Check common model names
    common_models = [
        ("General", "gpt-4o"),
        ("Fast/Cheap", "gpt-4o-mini"),
        ("Long Context", "claude-3-5-sonnet-20241022"),
        ("Coding", "claude-3-5-sonnet-20241022"),
    ]

    for use_case, model_name in common_models:
        model = config.get_model(model_name)
        if model:
            table.add_row(use_case, model.name, model.provider)
        else:
            table.add_row(use_case, f"[dim]{model_name}[/dim]", "[dim]not found[/dim]")

    console.print(table)
    console.print("\nDefault model from config:", config.get("llm.default_model", "not set"))
    console.print()


@models.command()
def providers():
    """List available model providers."""
    console.print("\n[bold cyan]Model Providers[/bold cyan]\n")

    providers_info = [
        ("openai", "OpenAI", "GPT-4, GPT-4o, GPT-3.5", "https://platform.openai.com"),
        ("anthropic", "Anthropic", "Claude 3.5, Claude 3", "https://console.anthropic.com"),
        ("google", "Google", "Gemini Pro, Gemini Ultra", "https://ai.google.dev"),
        ("local", "Local", "Ollama, LM Studio", "localhost"),
    ]

    table = Table()
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="yellow")
    table.add_column("Models", style="magenta")
    table.add_column("API", style="dim")

    for pid, name, models, api in providers_info:
        table.add_row(pid, name, models, api)

    console.print(table)
    console.print()
