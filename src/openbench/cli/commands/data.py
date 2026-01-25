"""Data Layer CLI commands."""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


@click.group()
def data():
    """Manage data sources and the Data Layer."""
    pass


@data.command()
@click.argument("source")
@click.option("--type", "source_type",
              type=click.Choice(["pdf", "sql", "api", "csv", "video", "web"]),
              help="Type of data source")
@click.option("--name", help="Name for this data source")
@click.option("--index/--no-index", default=True, help="Index data for semantic search")
def add(source, source_type, name, index):
    """Add a new data source to the project."""

    console.print(f"\n[bold cyan]📊 Adding Data Source[/bold cyan]\n")

    # Simulate adding data source
    if not source_type:
        # Auto-detect type
        if source.endswith('.pdf'):
            source_type = 'pdf'
        elif source.endswith('.csv'):
            source_type = 'csv'
        elif source.startswith('http'):
            source_type = 'web'
        else:
            source_type = 'unknown'

    console.print(f"[dim]Source: {source}[/dim]")
    console.print(f"[dim]Type: {source_type}[/dim]")
    console.print(f"[dim]Indexing: {'Yes' if index else 'No'}[/dim]\n")

    with console.status("[bold green]Processing data source..."):
        # Simulate processing
        import time
        time.sleep(1)

    console.print(Panel.fit(
        f"[green]✓[/green] Data source added successfully!\n\n"
        f"Source: {source}\n"
        f"Type: {source_type}\n"
        f"Status: {'Indexed' if index else 'Added'}",
        title="[bold green]Success![/bold green]",
        border_style="green"
    ))


@data.command()
def list():
    """List all configured data sources."""

    console.print("\n[bold cyan]📊 Data Sources[/bold cyan]\n")

    # Simulate listing data sources
    table = Table(title="Configured Data Sources")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Records", justify="right")

    # Mock data
    table.add_row("sustainability-reports", "pdf", "✓ Indexed", "156")
    table.add_row("sales-database", "sql", "✓ Connected", "45,230")
    table.add_row("customer-feedback", "api", "✓ Synced", "8,942")

    console.print(table)
    console.print()


@data.command()
@click.argument("query")
@click.option("--sources", multiple=True, help="Specific sources to query")
@click.option("--limit", default=10, help="Number of results")
def search(query, sources, limit):
    """Search across data sources."""

    console.print(f"\n[bold cyan]🔍 Searching: '{query}'[/bold cyan]\n")

    with console.status("[bold green]Searching data sources..."):
        import time
        time.sleep(1)

    # Simulate search results
    console.print(f"[green]Found 3 results[/green]\n")

    for i in range(3):
        console.print(f"[bold]{i+1}. Sustainability Report Q{i+1} 2024[/bold]")
        console.print(f"   [dim]Source: sustainability-reports[/dim]")
        console.print(f"   [dim]Relevance: 0.{95-i*10}[/dim]")
        console.print(f"   The report shows carbon emissions decreased by 15%...\n")


@data.command()
@click.argument("source_name")
def remove(source_name):
    """Remove a data source."""

    console.print(f"\n[yellow]⚠ Removing data source: {source_name}[/yellow]\n")

    if click.confirm("Are you sure?"):
        with console.status("[bold yellow]Removing data source..."):
            import time
            time.sleep(0.5)

        console.print(f"[green]✓[/green] Data source '{source_name}' removed.\n")
    else:
        console.print("[dim]Cancelled.[/dim]\n")


@data.command()
@click.option("--source", help="Specific source to sync")
def sync(source):
    """Sync data sources with latest data."""

    console.print("\n[bold cyan]🔄 Syncing Data Sources[/bold cyan]\n")

    sources_to_sync = [source] if source else ["all sources"]

    with console.status(f"[bold green]Syncing {sources_to_sync[0]}..."):
        import time
        time.sleep(2)

    console.print(Panel.fit(
        "[green]✓[/green] Data sources synced successfully!\n\n"
        "Updates:\n"
        "  • 12 new documents indexed\n"
        "  • 1,450 new records added\n"
        "  • 3 sources refreshed",
        title="[bold green]Sync Complete![/bold green]",
        border_style="green"
    ))
