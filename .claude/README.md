# Claude Code Configuration

This directory contains configuration for Claude Code when working with OpenBench.

## Structure

```
.claude/
├── settings.json           # Permissions and settings
├── README.md               # This file
├── commands/               # Slash commands
│   ├── test.md            # /test - Run tests
│   ├── lint.md            # /lint - Run linting
│   └── example.md         # /example - Run examples
└── skills/                 # Auto-invoked skills
    ├── composing-workflows/SKILL.md
    ├── creating-abstractions/SKILL.md
    └── testing-openbench/SKILL.md
```

## Commands

| Command | Description |
|---------|-------------|
| `/test` | Run the test suite |
| `/lint` | Run code formatting and linting |
| `/example` | Run an example workflow |

## Examples Location

Examples are organized in subdirectories:
- `examples/core/` - Core abstractions and orchestration demos
- `examples/adapters/` - Framework adapter examples
- `examples/workflows/` - Complete E2E workflow examples

## Skills

Skills are auto-invoked based on context:

| Skill | Triggers |
|-------|----------|
| `composing-workflows` | Creating workflows, DAG patterns, L1/L2 composition |
| `creating-abstractions` | Implementing DataSource, Agent, OutputGenerator, FrameworkAdapter |
| `testing-openbench` | Writing tests, test patterns |
