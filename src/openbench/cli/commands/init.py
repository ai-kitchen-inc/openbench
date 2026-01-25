"""Initialize OpenBench project."""

import click
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

console = Console()


@click.command()
@click.option("--name", help="Project name")
@click.option("--path", type=click.Path(), default=".", help="Project path")
@click.option("--template", type=click.Choice(["minimal", "standard", "enterprise"]),
              default="standard", help="Project template")
def init(name, path, template):
    """Initialize a new OpenBench project."""

    console.print("\n[bold cyan]🚀 OpenBench Project Initialization[/bold cyan]\n")

    # Interactive prompts if not provided
    if not name:
        name = Prompt.ask("Project name", default="my-openbench-project")

    project_path = Path(path) / name

    console.print(f"\n[dim]Creating project at: {project_path}[/dim]\n")

    # Create project structure
    _create_project_structure(project_path, template)

    console.print(Panel.fit(
        f"[green]✓[/green] Project '{name}' initialized successfully!\n\n"
        f"[bold]Next steps:[/bold]\n"
        f"  1. cd {name}\n"
        f"  2. openbench data add <source>\n"
        f"  3. openbench agent create <agent-name>\n"
        f"  4. openbench workflow run\n",
        title="[bold green]Success![/bold green]",
        border_style="green"
    ))


def _create_project_structure(project_path: Path, template: str):
    """Create the project directory structure."""

    # Create directories
    directories = [
        "data/sources",
        "data/processed",
        "agents",
        "workflows",
        "outputs",
        "config",
        "tools",
    ]

    for dir_name in directories:
        dir_path = project_path / dir_name
        dir_path.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created {dir_name}/")

    # Create config file
    config_content = f"""# OpenBench Configuration
version: "1.0"
project:
  name: "{project_path.name}"
  template: "{template}"

data:
  sources: []

intelligence:
  default_model: "gpt-4"
  agents: []

output:
  default_format: "pdf"
  templates: []
"""

    config_file = project_path / "config" / "openbench.yaml"
    config_file.write_text(config_content)
    console.print(f"[green]✓[/green] Created config/openbench.yaml")

    # Create .env template
    env_content = """# OpenBench Environment Variables

# API Keys
OPENAI_API_KEY=your-openai-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key

# Database
# DATABASE_URL=postgresql://user:pass@localhost:5432/db

# Optional Services
# PINECONE_API_KEY=your-pinecone-key
# ELEVENLABS_API_KEY=your-elevenlabs-key
"""

    env_file = project_path / ".env.example"
    env_file.write_text(env_content)
    console.print(f"[green]✓[/green] Created .env.example")

    # Create README
    readme_content = f"""# {project_path.name}

OpenBench project initialized with `{template}` template.

## Quick Start

```bash
# Add data sources
openbench data add ./documents --type pdf

# Create an agent
openbench agent create research-agent --type research

# Run a workflow
openbench workflow run sustainability-report

# Generate output
openbench generate report --format pdf
```

## Project Structure

- `data/` - Data sources and processed data
- `agents/` - Custom agent definitions
- `workflows/` - Workflow configurations
- `outputs/` - Generated outputs
- `config/` - Configuration files
- `tools/` - Custom tools and MCP integrations

## Documentation

See [OpenBench Documentation](https://github.com/ai-kitchen-inc/openbench/tree/main/docs) for more details.
"""

    readme_file = project_path / "README.md"
    readme_file.write_text(readme_content)
    console.print(f"[green]✓[/green] Created README.md")
