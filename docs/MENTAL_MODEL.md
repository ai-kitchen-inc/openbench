# OpenBench Mental Model — The Four Pillars

A capability-routing mental model for OpenBench. Use this page to
decide *where a new feature belongs* before you write code. The L1 /
L2 / three-layer view in [ARCHITECTURE.md](ARCHITECTURE.md) covers
*how the runtime is assembled*; this page covers *what kind of thing
you are building and which surface it lives on*.

---

## TL;DR

OpenBench positions every user- or LLM-visible capability under one of
four pillars. Anything else is *plumbing* that supports a pillar.

| Pillar | Answers | Lives as |
|---|---|---|
| **MCP** | *How does the agent reach an external service?* | MCP server (process, any language) exposing tools over stdio/HTTP |
| **Skill** | *When and why should the agent do X?* | Markdown playbook + optional in-process tools |
| **Agentic** | *How does the agent reason, plan, remember, and act?* | `BaseAgent` + `Persona` + `AgentMemory` + `ToolExecutor` + `TaskPlanner` |
| **Output** | *What deliverable goes back to the user?* | `OutputLayer` generators + chat surfaces (ObChart, ObFileCard, ObTable, …) |

The capability decides the pillar. The pillar decides the layer.

---

## The four pillars

### MCP — external capability delivery

**Role.** Reach systems the agent does not own — Google Drive, Slack,
GitHub, calendars, internal HTTP APIs, search engines.

**Shape.** A separate process exposing tools via Model Context Protocol
over stdio or HTTP. The agent connects as an MCP client; the server
can be written in any language.

**Why MCP and not a Python class.** Process isolation, language
independence, lifecycle separation from the agent process, and a
shared protocol that 30+ agent ecosystems already speak. A bug in the
Drive integration cannot crash the agent; a community-published MCP
server drops in without code changes.

**OpenBench surface.** MCP clients are wrapped by a thin `Skill`
whose `tools.py` calls the server. The skill is the playbook;
the MCP server is the muscle.

### Skill — playbook and domain knowledge

**Role.** Tell the agent *when* to use a capability and *why* — domain
rules, workflow guidance, the protocol the agent should follow for a
particular kind of task.

**Shape.** A directory containing `SKILL.md` (required), optional
`references/*.md`, and an optional `tools.py` for in-process Python
helpers. Knowledge-only skills (no `tools.py`) are valid and useful.

**Why a markdown playbook and not Python.** Authors are domain experts,
not framework engineers. Markdown is the lowest-common-denominator
medium for capturing *"when the user asks X, follow protocol Y, watch
for failure mode Z"*. The same skill is reusable across agents and —
once the agentskills.io spec is adopted — across agent ecosystems.

**OpenBench surface.** `Skill` + `SkillRegistry` (two-tier: bundled
SDK skills override-able by project skills). See
[../src/openbench/skills/](../src/openbench/skills/) for the seven
shipped SDK skills.

### Agentic — reasoning, memory, planning, tool use

**Role.** The loop that turns a goal into actions. Picks tools, calls
them, remembers what happened, plans multi-step work, recovers from
errors.

**Shape.** `BaseAgent` orchestrates `Persona` (identity), `AgentMemory`
(per-turn history with atomic transactions), `ToolExecutor` (parallel
calls + schema registry), and optional `TaskPlanner` (decomposition).
`SimpleAgent` / `ResearchAgent` / `AnalysisAgent` / `ContentAgent` /
`ActionAgent` / `MetaAgent` are pre-built subclasses.

**Why Python and not configuration.** The reasoning loop has subtle
invariants (orphan-tool-call validation, transactional turn rollback,
streaming partial responses) that must be enforced in code, not config.
This is the framework's core competence.

**OpenBench surface.** [`src/openbench/intelligence/`](../src/openbench/intelligence/).

### Output — deliverables back to the user

**Role.** Everything the user actually receives — a PDF report, an
Excel workbook, a chart in the chat panel, an audio narration, a
dashboard URL.

**Shape.** Two complementary forms:

- **`OutputLayer` generators** for file artifacts (PDF, PPTX, audio,
  markdown). Each implements `OutputGenerator`. Composable in the L2
  pipeline: `data | intelligence | output`.
- **Chat surfaces** for in-chat rendering — `ObChart`, `ObFileCard`,
  `ObCodeBlock`, `ObMarkdown`, `ObTable`, `ObCallout` (the six custom
  A2UI components) plus 18 standard A2UI components. Rendered by
  `@openbench/chat-ui` from A2UI v0.10 JSONL.

**Why two shapes.** File artifacts are downloads the user takes
elsewhere; chat surfaces are interactive, live in the conversation,
and link back to the source data.

**OpenBench surface.** [`src/openbench/output/`](../src/openbench/output/)
and [`src/openbench/chat/`](../src/openbench/chat/).

---

## What is NOT a pillar

Not everything in OpenBench is user- or LLM-visible. Plumbing layers
support the pillars without being one.

### Storage layer (plumbing under Agentic)

`StorageBackend` and its five slots — `SessionStore`, `MemoryStore`,
`ScratchpadStore`, `PersonaSource`, `FileStore` — are infrastructure
the Agentic pillar needs to persist state across turns and sessions.

The agent does not *decide* to use the storage layer; it always does.
The user never reasons about which `MemoryStore` is mounted; they just
expect the conversation to be there tomorrow.

**Stays as Protocol-based ABC, not MCP.** See [STORAGE.md](STORAGE.md)
and the decision matrix below.

### Data layer (plumbing under Agentic)

`DataSource`, `DataStore`, `EmbeddingProvider`, `LLMProvider` —
all the substrate the agent reasons over but does not choose. Same
pattern: Protocol-based, swappable, not user-facing.

---

## The decision matrix

When designing a new capability, route it through this table before
writing code.

| Capability | Pillar / layer | Why |
|---|---|---|
| External service the agent calls on demand (Drive search, Slack post, GitHub issue create) | **MCP** | Process isolation, language independence, ecosystem reuse |
| Domain workflow guidance, "when X then Y" protocol | **Skill** | Authored by domain experts in markdown; reusable across agents |
| Skill's small Python helper (parser, formatter, calculator) | Skill's local `tools.py` | Fast in-process call, no IPC overhead, lives next to the playbook that uses it |
| Reasoning loop primitive (planning, memory transaction, parallel tool call) | **Agentic** (`BaseAgent` extension) | Framework core; correctness invariants must live in code |
| File deliverable (PDF, PPTX, xlsx, audio) | **Output** (`OutputGenerator`) | User-facing artifact; pipeline-composable |
| In-chat rich rendering (chart, file card, table) | **Output** (A2UI component) | Live in conversation; declarative + interactive |
| Hot-path persistence (session, memory, scratchpad, file storage) | **Plumbing — Protocol ABC** (not MCP) | Per-turn latency budget; transactional semantics; typed contracts |
| LLM provider, embedding provider | **Plumbing — Protocol ABC** | Swappable per deployment; not user-reasoned |
| Vector store, BM25 index | **Plumbing — Protocol ABC** | Same — substrate for RAG, not a user concept |

When a capability seems to fit two cells, it usually plays *two
distinct roles* and lands in both places (see Drive below).

---

## Worked examples

### Google Drive — two roles, two surfaces

| Role | Pillar / layer | Implementation |
|---|---|---|
| "Save this session / memory / uploaded file persistently" | Storage plumbing | `GoogleDriveStorageBackend` + its five slot impls |
| "Search the user's Drive for Q1 reports, fetch one and summarize it" | **MCP** + thin **Skill** | MCP Drive server + `skills/drive-explorer/` playbook |

These do not compete. The storage backend is always-on and invisible
to the agent's reasoning. The MCP skill activates only when the user's
intent matches the skill description.

### Slack notifications

| Role | Pillar | Implementation |
|---|---|---|
| Agent posts a message when a workflow finishes | **MCP** + **Skill** | Slack MCP server + `skills/slack-notify/` ("when long-running task completes, post summary to user's preferred channel") |

There is no "Slack storage backend" — Slack is not where state lives.
Same logic as Drive role 1.

### LCI domain agent (lci-mini)

| Role | Pillar | Implementation |
|---|---|---|
| Identity — "you are Lici, an Indonesian LCA consultant" | **Agentic** (Persona) | `examples/lci-mini/soul/{SOUL,STYLE,AGENTS}.md` |
| Excel-as-RDBMS protocol — "call `xql_catalog` first, then map columns, then chain primitives" | **Skill** | `examples/lci-mini/skills/xql/SKILL.md` + 14 tools in `tools.py` |
| Save conversation across sessions | Storage plumbing | `LocalStorageBackend` (dev) or `GoogleDriveStorageBackend` (prod) |
| Return a chart for "tampilkan top 5 emisi CO2" | **Output** | `data-visualization` SDK skill returns ObChart-compatible dict |
| Return an xlsx for "ekspor hasil ke Excel" | **Output** | `export-excel` SDK skill returns ObFileCard pointing at the file |

Every box maps to exactly one pillar or one plumbing layer. No
overlap, no ambiguity.

---

## Common antipatterns

### "Put it behind MCP so it's modular"

Modular is not the same as remote. Use MCP when a capability is *truly
external* and the network/process boundary buys you something (language
independence, isolation, ecosystem reuse). Don't use it for in-process
plumbing — you pay the IPC cost on every call and lose typed contracts
and transactional semantics. Hot-path state (memory, session,
scratchpad) is the canonical *don't*.

### "Skill or MCP? — pick one"

False choice. Skills are the **knowledge layer on top of** MCP servers
(Anthropic's phrasing). The MCP server delivers the capability; the
skill tells the agent when to use it and how to chain it. Drive
integration looks like an MCP server *and* a `drive-explorer` skill —
that's correct, not redundant.

### "Move the storage backend to MCP to be modern"

The "modern" thing is the existing pattern. Every major agent platform
in 2026 — LangGraph, Google ADK, LlamaIndex, MS Agent Framework,
CrewAI, OpenAI Agents SDK — keeps persistence as Protocol-based ABCs
and uses MCP only for external integrations. OpenBench is aligned;
don't drift off.

### "Encode domain knowledge as Python helpers in the agent"

If the rule is *"when the user uploads an xlsx, call `xql_catalog`
first, never guess paths"*, that lives in a `Skill`, not in
`BaseAgent`. Code is for invariants the framework must enforce;
playbooks are for guidance the LLM should follow.

### "Ship a new file format by adding a method to BaseAgent"

New deliverable types are **Output**, not Agentic. Add an
`OutputGenerator` subclass, or — for in-chat rendering — a new A2UI
custom component plus its Python renderer.

---

## Adding a new capability — the routing checklist

Before opening the editor, answer these in order:

1. **Is the agent reaching an external service over the network?**
   → MCP server, wrapped by a Skill.

2. **Is this domain knowledge or workflow guidance?**
   → Skill (markdown + optional `tools.py`).

3. **Is this a reasoning-loop primitive that must be enforced?**
   → Agentic (extension of `BaseAgent` machinery).

4. **Is this a deliverable to the user?**
   → Output (new `OutputGenerator` for files; new A2UI component for
   chat surfaces).

5. **Is this internal state the agent persists but does not reason
   about?**
   → Plumbing — Protocol-based ABC. Implement a new
   `MemoryStore` / `SessionStore` / `FileStore`, or a new
   `StorageBackend` if you need a new deployment shape.

If your capability doesn't fit any cell, that is a signal — either
the capability is two things wearing one name, or the architecture
needs a real new concept. Either way, talk it through before writing
code.

---

## Cross-references

- [ARCHITECTURE.md](ARCHITECTURE.md) — L1 / L2 / three-layer runtime model
- [STORAGE.md](STORAGE.md) — the five stores and their backends
- [CUSTOM-BACKEND.md](CUSTOM-BACKEND.md) — implementing a `StorageBackend`
- [CHAT_UI_ARCHITECTURE.md](CHAT_UI_ARCHITECTURE.md) — A2UI v0.10 + chat surfaces (the Output pillar in chat)
- [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) — visual language for the chat surface

---

## Maintenance

When you propose a feature, cite the pillar (or plumbing layer) it
belongs to in the PR description. When reviewing, cross-check against
the decision matrix. When the matrix gains a new row, update this
page in the same change.
