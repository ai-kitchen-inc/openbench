"""Project management CLI commands."""

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from openbench.core.context import (
    get_project_registry,
)

console = Console()


@click.group()
def project():
    """Manage projects for multi-tenant data isolation."""


@project.command("create")
@click.option("--name", "-n", required=True, help="Project name")
@click.option("--description", "-d", default="", help="Project description")
@click.option("--user", "-u", default="", help="User ID for user-level isolation")
@click.option("--org", "-o", default=None, help="Organization ID")
def create(name, description, user, org):
    """Create a new project."""
    console.print(f"\n[bold cyan]Creating Project: {name}[/bold cyan]\n")

    registry = get_project_registry()

    # Check if name already exists
    existing = registry.get_by_name(name)
    if existing:
        console.print(f"[yellow]Warning: Project with name '{name}' already exists.[/yellow]")
        console.print(f"Existing project ID: {existing.project_id}\n")
        if not Confirm.ask("Create another project with the same name?"):
            console.print("[dim]Cancelled.[/dim]")
            return

    project = registry.create(
        name=name,
        description=description,
        user_id=user,
        organization_id=org,
    )

    console.print(
        Panel.fit(
            f"[green]✓[/green] Project created successfully!\n\n"
            f"[bold]Project ID:[/bold] {project.project_id}\n"
            f"[bold]Name:[/bold] {project.name}\n"
            f"[bold]Namespace:[/bold] {project.namespace}",
            title="[bold green]Project Created[/bold green]",
            border_style="green",
        )
    )
    console.print()


@project.command("list")
@click.option("--user", "-u", default=None, help="Filter by user ID")
@click.option("--org", "-o", default=None, help="Filter by organization ID")
def list_projects(user, org):
    """List all projects."""
    console.print("\n[bold cyan]Projects[/bold cyan]\n")

    registry = get_project_registry()
    projects = registry.list()

    # Apply filters
    if user:
        projects = [p for p in projects if p.user_id == user]
    if org:
        projects = [p for p in projects if p.organization_id == org]

    if not projects:
        console.print("[dim]No projects found.[/dim]")
        console.print("\nCreate a project with:")
        console.print("  openbench project create --name 'My Project'\n")
        return

    active_id = registry.active_project_id

    table = Table()
    table.add_column("Project ID", style="cyan")
    table.add_column("Name", style="yellow")
    table.add_column("User", style="blue")
    table.add_column("Org", style="magenta")
    table.add_column("Active", style="green")
    table.add_column("Created", style="dim")

    for p in projects:
        table.add_row(
            p.project_id,
            p.name,
            p.user_id or "-",
            p.organization_id or "-",
            "✓" if p.project_id == active_id else "",
            p.created_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)
    console.print()


@project.command("show")
@click.argument("project_id", required=False)
def show(project_id):
    """Show details of a project. Uses active project if ID not provided."""
    registry = get_project_registry()

    if project_id:
        proj = registry.get(project_id)
        if not proj:
            # Try by name
            proj = registry.get_by_name(project_id)
    else:
        proj = registry.get_active()

    if not proj:
        if project_id:
            console.print(f"\n[red]Project '{project_id}' not found.[/red]\n")
        else:
            console.print(
                "\n[red]No active project. Use 'openbench project use <id>' to set one.[/red]\n"
            )
        return

    console.print("\n[bold cyan]Project Details[/bold cyan]\n")

    table = Table(show_header=False)
    table.add_column("Key", style="cyan", width=16)
    table.add_column("Value", style="yellow")

    table.add_row("Project ID", proj.project_id)
    table.add_row("Name", proj.name)
    table.add_row("Namespace", proj.namespace)
    table.add_row("User ID", proj.user_id or "-")
    table.add_row("Organization", proj.organization_id or "-")
    table.add_row("Description", proj.description or "-")
    table.add_row("Created", proj.created_at.strftime("%Y-%m-%d %H:%M:%S"))
    table.add_row("Updated", proj.updated_at.strftime("%Y-%m-%d %H:%M:%S"))

    if proj.settings:
        table.add_row("Settings", str(proj.settings))

    is_active = proj.project_id == registry.active_project_id
    table.add_row("Active", "[green]Yes[/green]" if is_active else "No")

    console.print(table)
    console.print()


@project.command("use")
@click.argument("project_id")
def use(project_id):
    """Set the active project."""
    registry = get_project_registry()

    proj = registry.get(project_id)
    if not proj:
        # Try by name
        proj = registry.get_by_name(project_id)

    if not proj:
        console.print(f"\n[red]Project '{project_id}' not found.[/red]\n")
        return

    if registry.set_active(proj.project_id):
        console.print(
            f"\n[green]✓[/green] Active project set to: {proj.name} ({proj.project_id})\n"
        )
    else:
        console.print("\n[red]Failed to set active project.[/red]\n")


@project.command("update")
@click.argument("project_id")
@click.option("--name", "-n", default=None, help="New project name")
@click.option("--description", "-d", default=None, help="New description")
@click.option("--user", "-u", default=None, help="New user ID")
@click.option("--org", "-o", default=None, help="New organization ID")
def update(project_id, name, description, user, org):
    """Update a project."""
    registry = get_project_registry()

    proj = registry.get(project_id)
    if not proj:
        proj = registry.get_by_name(project_id)

    if not proj:
        console.print(f"\n[red]Project '{project_id}' not found.[/red]\n")
        return

    # Build update kwargs
    updates = {}
    if name is not None:
        updates["name"] = name
    if description is not None:
        updates["description"] = description
    if user is not None:
        updates["user_id"] = user
    if org is not None:
        updates["organization_id"] = org

    if not updates:
        console.print("\n[yellow]No updates specified.[/yellow]\n")
        return

    registry.update(proj.project_id, **updates)
    console.print(f"\n[green]✓[/green] Project '{proj.project_id}' updated.\n")


@project.command("delete")
@click.argument("project_id")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
def delete(project_id, force):
    """Delete a project."""
    registry = get_project_registry()

    proj = registry.get(project_id)
    if not proj:
        proj = registry.get_by_name(project_id)

    if not proj:
        console.print(f"\n[red]Project '{project_id}' not found.[/red]\n")
        return

    if not force and not Confirm.ask(f"Delete project '{proj.name}' ({proj.project_id})?"):
        console.print("[dim]Cancelled.[/dim]")
        return

    registry.delete(proj.project_id)
    console.print(f"\n[green]✓[/green] Project '{proj.name}' deleted.\n")


@project.command("active")
def active():
    """Show the currently active project."""
    registry = get_project_registry()
    proj = registry.get_active()

    if not proj:
        console.print("\n[yellow]No active project set.[/yellow]")
        console.print("\nSet an active project with:")
        console.print("  openbench project use <project_id>\n")
        return

    console.print("\n[bold cyan]Active Project[/bold cyan]\n")
    console.print(f"  [bold]ID:[/bold]   {proj.project_id}")
    console.print(f"  [bold]Name:[/bold] {proj.name}")
    console.print()
