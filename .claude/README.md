# Claude Code Configuration

This directory contains configuration for Claude Code when working with OpenBench.

## Structure

```
.claude/
├── settings.json           # Permissions and settings
├── README.md               # This file
├── commands/               # Slash commands (user-invocable)
│   ├── test.md            # /test - Run tests
│   ├── lint.md            # /lint - Run linting
│   └── example.md         # /example - Run examples
└── skills/                 # Auto-invoked skills (Claude can invoke)
    ├── composing-workflows/SKILL.md
    ├── creating-abstractions/SKILL.md
    ├── data-layer/SKILL.md
    └── testing-openbench/SKILL.md
```

## Commands (User-Invocable)

Commands use `disable-model-invocation: true` - only you can invoke them.

| Command | Description |
|---------|-------------|
| `/test [options]` | Run the test suite |
| `/lint [options]` | Run code formatting and linting |
| `/example [name]` | Run an example workflow |

## Skills (Auto-Invoked by Claude)

Skills are automatically loaded when Claude detects relevant context.

| Skill | Triggers |
|-------|----------|
| `composing-workflows` | Creating workflows, DAG patterns, L1/L2 composition |
| `creating-abstractions` | Implementing DataSource, Agent, OutputGenerator, DataStore, FrameworkAdapter |
| `data-layer` | PineconeStore, chunking, embeddings, RAG patterns, vector search |
| `testing-openbench` | Writing tests, test patterns |

## Frontmatter Reference

Skills and commands support YAML frontmatter:

```yaml
---
name: skill-name
description: What it does and when to use it
argument-hint: "[arg]"
disable-model-invocation: true  # Only user can invoke
user-invocable: false           # Only Claude can invoke
allowed-tools: Read, Grep       # Restrict tool access
context: fork                   # Run in subagent
---
```

## Examples Location

- `examples/core/` - Core abstractions and orchestration demos
- `examples/adapters/` - Framework adapter examples
- `examples/intelligence/` - Agent and LLM provider demos
- `examples/workflows/` - Complete E2E workflow examples
  - `workflows/pdf/` - PDF processing workflows
  - `workflows/entity/` - Entity extraction workflows
  - `workflows/research/` - Research agent workflows
  - `workflows/reports/` - End-to-end report generation

## More Information

See https://code.claude.com/docs/en/skills for full documentation.
