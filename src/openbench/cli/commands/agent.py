"""Intelligence Layer - Agent CLI commands."""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt

console = Console()


@click.group()
def agent():
    """Manage AI agents and the Intelligence Layer."""
    pass


@agent.command()
@click.argument("name")
@click.option("--type", "agent_type",
              type=click.Choice(["research", "analysis", "content", "action", "meta"]),
              default="research",
              help="Type of agent to create")
@click.option("--model", default="gpt-4", help="LLM model to use")
@click.option("--tools", multiple=True, help="Tools available to the agent")
def create(name, agent_type, model, tools):
    """Create a new AI agent."""

    console.print(f"\n[bold cyan]🤖 Creating Agent: {name}[/bold cyan]\n")

    console.print(f"[dim]Type: {agent_type}[/dim]")
    console.print(f"[dim]Model: {model}[/dim]")
    console.print(f"[dim]Tools: {', '.join(tools) if tools else 'default'}[/dim]\n")

    # Simulate agent creation
    agent_config = f"""# Agent: {name}
type: {agent_type}
model: {model}

goal: |
  {_get_default_goal(agent_type)}

capabilities:
  - semantic_search
  - sql_query
{_format_tools(tools)}

memory:
  type: vector
  size: 10000

output:
  format: structured
"""

    with console.status("[bold green]Creating agent configuration..."):
        import time
        time.sleep(1)

    console.print(Panel.fit(
        f"[green]✓[/green] Agent '{name}' created successfully!\n\n"
        f"Type: {agent_type}\n"
        f"Model: {model}\n\n"
        f"[bold]Test your agent:[/bold]\n"
        f"  openbench agent test {name}\n\n"
        f"[bold]Use in workflow:[/bold]\n"
        f"  openbench workflow create --agent {name}",
        title="[bold green]Agent Created![/bold green]",
        border_style="green"
    ))


@agent.command()
def list():
    """List all configured agents."""

    console.print("\n[bold cyan]🤖 Configured Agents[/bold cyan]\n")

    table = Table(title="AI Agents")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Model", style="yellow")
    table.add_column("Status", style="green")

    # Mock data
    table.add_row("sustainability-analyst", "analysis", "gpt-4", "✓ Ready")
    table.add_row("report-writer", "content", "claude-opus", "✓ Ready")
    table.add_row("data-researcher", "research", "gpt-4", "✓ Ready")
    table.add_row("action-executor", "action", "gpt-3.5-turbo", "✓ Ready")

    console.print(table)
    console.print()


@agent.command()
@click.argument("name")
@click.option("--prompt", help="Test prompt for the agent")
@click.option("--data", help="Data source to use")
def test(name, prompt, data):
    """Test an agent with a sample prompt."""

    console.print(f"\n[bold cyan]🧪 Testing Agent: {name}[/bold cyan]\n")

    if not prompt:
        prompt = Prompt.ask("Enter test prompt")

    console.print(f"[dim]Prompt: {prompt}[/dim]")
    console.print(f"[dim]Data: {data or 'all sources'}[/dim]\n")

    with console.status("[bold green]Agent is thinking..."):
        import time
        time.sleep(2)

    # Simulate agent response
    console.print(Panel(
        "[bold]Agent Response:[/bold]\n\n"
        "Based on my analysis of the available data, I found the following insights:\n\n"
        "1. Carbon emissions have decreased by 15% year-over-year\n"
        "2. Renewable energy usage has increased to 45% of total consumption\n"
        "3. Water conservation efforts saved 2.3 million gallons\n\n"
        "[dim]Sources consulted: 12 documents, 3 databases[/dim]\n"
        "[dim]Confidence: 0.89[/dim]",
        title=f"[bold cyan]{name}[/bold cyan]",
        border_style="cyan"
    ))


@agent.command()
@click.argument("name")
@click.option("--key", help="Configuration key to update")
@click.option("--value", help="New value")
def configure(name, key, value):
    """Configure agent settings."""

    console.print(f"\n[bold cyan]⚙️ Configuring Agent: {name}[/bold cyan]\n")

    if key and value:
        console.print(f"[green]✓[/green] Updated {key} = {value}\n")
    else:
        console.print("[yellow]Interactive configuration mode...[/yellow]\n")
        console.print("Current settings:")
        console.print("  model: gpt-4")
        console.print("  temperature: 0.7")
        console.print("  max_tokens: 2000\n")


def _get_default_goal(agent_type: str) -> str:
    """Get default goal based on agent type."""
    goals = {
        "research": "Gather and synthesize information from multiple sources",
        "analysis": "Perform quantitative and qualitative analysis on data",
        "content": "Generate well-structured written content",
        "action": "Execute actions and integrate with external systems",
        "meta": "Coordinate multiple agents to solve complex problems"
    }
    return goals.get(agent_type, "Accomplish the given task")


def _format_tools(tools):
    """Format tools list for YAML."""
    if not tools:
        return ""
    return "\n".join(f"  - {tool}" for tool in tools)
