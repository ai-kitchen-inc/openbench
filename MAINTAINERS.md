# Maintainers

This file lists the current maintainers of OpenBench. See
[GOVERNANCE.md](GOVERNANCE.md) for roles, responsibilities, and how to become a
maintainer.

## Current Maintainers

| Name           | GitHub                                            | Areas                         |
| -------------- | ------------------------------------------------- | ----------------------------- |
| OpenBench Team | [@ai-kitchen-inc](https://github.com/ai-kitchen-inc) | Project lead, all subsystems |

> Maintainers: replace the placeholder row above with individual entries
> (one per maintainer) and assign ownership areas that line up with
> [.github/CODEOWNERS](.github/CODEOWNERS).

## Areas of Ownership

Ownership maps to top-level packages under `src/openbench/`:

- **core** — abstractions, chainable composition, layers, registry, providers
- **data** — data sources and vector stores
- **intelligence** — agents, LLM providers, embeddings, memory, skills
- **chat** — chat engine, A2UI builder, renderers, transport
- **adapters** — LangChain, CrewAI, AG2, E2B, Google ADK
- **output** — PDF, PPTX, dashboard, audio, markdown generators
- **cli** — command-line interface
- **studio/chat-ui** — `@openbench/chat-ui` React SDK

## Contact

- General: [GitHub Discussions](https://github.com/ai-kitchen-inc/openbench/discussions)
- Security: see [SECURITY.md](SECURITY.md)
- Email: openbench2026@gmail.com
