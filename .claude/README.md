# Claude Code Configuration

This directory contains configuration for Claude Code when working with OpenBench.

## Structure

```
.claude/
├── settings.json           # Permissions and settings
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

## Skills

Skills are auto-invoked based on context:

| Skill | Triggers |
|-------|----------|
| `composing-workflows` | Creating workflows, DAG patterns, L1/L2 composition |
| `creating-abstractions` | Implementing DataSource, Agent, OutputGenerator |
| `testing-openbench` | Writing tests, test patterns |
