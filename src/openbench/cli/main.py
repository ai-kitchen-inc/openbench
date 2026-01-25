"""
OpenBench CLI - Main entry point
"""

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from openbench.cli import commands

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="openbench")
@click.pass_context
def cli(ctx):
    """
    🔥 OpenBench - The Open Source Agentic AI Workbench

    Build. Orchestrate. Export. Scale.
    """
    ctx.ensure_object(dict)


# Register command groups
cli.add_command(commands.init.init)
cli.add_command(commands.data.data)
cli.add_command(commands.agent.agent)
cli.add_command(commands.workflow.workflow)
cli.add_command(commands.generate.generate)
cli.add_command(commands.tools.tools)
cli.add_command(commands.models.models)
cli.add_command(commands.config.config)


def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
