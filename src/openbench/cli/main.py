"""
OpenBench CLI - Main entry point
"""

from importlib.metadata import PackageNotFoundError, version

import click
from rich.console import Console

from openbench.cli import commands

console = Console()

try:
    __version__ = version("openbench")
except PackageNotFoundError:  # package not installed (e.g. running from source tree)
    from openbench._version import __version__


@click.group()
@click.version_option(version=__version__, prog_name="openbench")
@click.pass_context
def cli(ctx):
    """
    OpenBench - The Open Source Agentic AI Workbench

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
cli.add_command(commands.mcp.mcp)
cli.add_command(commands.models.models)
cli.add_command(commands.config.config)
cli.add_command(commands.provider.provider)
cli.add_command(commands.project.project)
cli.add_command(commands.demo.demo)


def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
