# OpenBench Product Roadmap — Sellable Features

This roadmap tracks the **features that help sell OpenBench** — concrete product
capabilities, grounded in what the code actually does today, organized by the
buyer story each one unlocks. The engineering/code-quality roadmap lives in
`roadmap_code.md`; pure infra/architecture work belongs in `ROADMAP.md`.

Every item carries a status tag drawn from a full codebase scan, so this file
doubles as an honest status board — what already demos, what's half-built, and
what we still need to build to close deals.

**Status legend (tag in _italics_ after each item):**
`[x] SHIPPED` · `[ ] PARTIAL` (works, needs polish/productizing) ·
`[ ] STUB` (placeholder/`NotImplementedError`) · `[ ] ABSENT` (not built yet).

## Product Thesis

- [ ] Sell OpenBench as a **controllable agent-workflow platform**: AI tools that
  are observable, governable, and safe to run in production — not just another chat UI.
- [ ] Make **General Chat** the primary product surface — the thing buyers see in a
  5-minute demo: ask, approve a tool call, see rich results, review the trail.
- [ ] Lead with the **trust layer** (permissions, redaction, encrypted secrets,
  observability) and back it with a **plug-into-your-stack** extensibility story.

## Differentiation

- [ ] One product combining workflow orchestration, General Chat, MCP tool
  management, permission gating, observability, templates, and self-hosting.
- [ ] User approval and tool transparency are first-class UX, not an afterthought.
- [ ] Framework-friendly, not framework-replacing: LangChain, CrewAI, AG2, Google
  ADK, E2B, MCP, and custom tools all plug in.
- [ ] Open-source core for developer adoption + paid team/enterprise self-host.

---

## 1. Trust & Governance — the deal-closer wedge

_Sells to: security/compliance-sensitive teams adopting MCP who fear silent tool
side effects, private-data exposure, and untracked actions. This is the wedge._

- [x] **MCP tool permission gating with risk labels.** Per-tool approval flow,
  risk classification (READ / WRITE / ARTIFACT_WRITE / EXTERNAL_NETWORK /
  DESTRUCTIVE), approve/deny/ambiguous decisions, decision caching. — _SHIPPED
  `mcp/permissions.py`, `mcp/policy.py`._ The headline trust demo: no tool runs without consent.
- [x] **Secret redaction at every surface.** Regex + key-name redaction of
  Authorization/api_key/token/secret/password in permission prompts, cache keys,
  and error messages. — _SHIPPED `mcp/policy.py` `redact_secrets`._
- [x] **Encrypted credential / secret store.** Fernet-encrypted provider creds
  (0600 file mode, `require_encryption` enforces-or-fails in prod). — _SHIPPED
  `core/providers.py`._
- [x] **Agent + tool observability.** Correlation-ID context, per-call timings and
  counters (`agent.execute`, `agent.llm_generate`, `agent.tool_execute`,
  `agent.total_ms`, `policy_denials_total`), optional OpenTelemetry spans. —
  _SHIPPED `mcp/observability.py` + `intelligence/base.py`, `intelligence/tool_executor.py`._
- [ ] **Persistent audit trail.** Today approvals + tool calls + metrics are
  logged but ephemeral. Persist who-approved-which-tool-when to a queryable store.
  — _PARTIAL._ Top enterprise ask; pairs with the permission gate to tell a complete control story.
- [ ] **RBAC roles** (admin / viewer / tool-caller). Today it's a flat email
  allowlist. — _ABSENT._ Required for team/enterprise tiers.
- [ ] **PII redaction** (emails / phones / names), not only secrets. — _ABSENT._
- [ ] **External secrets-manager adapters** (HashiCorp Vault, GCP / AWS Secret
  Manager) beyond the local encrypted file. — _ABSENT._ Removes a common security-review blocker.
- [ ] **Policy packs + approval-rule engine + compliance export** (CSV / SIEM).
  Denials are counted today but not exportable with request detail. — _PARTIAL / ABSENT._

## 2. Demo-Magic Product Surface (General Chat) — wins the eval

_Sells to: every evaluator in the first 5 minutes. Rich, interactive output is
what makes a prospect say "this feels like a product, not a script."_

- [x] **Rich in-chat rendering.** A2UI v0.10 surfaces: charts, tables, file cards,
  syntax-highlighted code, callouts, forms, media, tabs, modals (18 standard + 6
  custom components). — _SHIPPED `chat/` renderers + `studio/chat-ui` custom components._
- [x] **Voice input with live waveform.** ChatGPT-style recorder, Web-Audio
  waveform, swappable transcription. — _SHIPPED `studio/chat-ui/.../VoiceRecorder.tsx`, `ChatInput.tsx`._
- [x] **Multimodal upload.** Images, audio, video, PDF, and Office docs with inline
  preview + backend extraction. — _SHIPPED `ChatInput.tsx`, `AttachmentPreview.tsx`, `data/sources/`._
- [x] **MCP catalog UI + ToolHive.** Browse/add/remove/toggle MCP servers, inspect
  tool schemas, approve calls, JSON config import. — _SHIPPED `examples/general-chat/.../mcp-catalog`._
- [x] **Saved sessions + sidebar CRUD.** SQLite-backed session store, titles,
  previews, group-by-date. — _SHIPPED `chat/session_store.py`, `SessionSidebar.tsx`._
- [ ] **Source / project workspace.** Source discovery + project-scoped sources
  exist inside the example; productize and lift into the SDK. — _PARTIAL._
- [ ] **Polished in-chat approval modal.** Approval works but is inline in the
  catalog panel; needs a first-class modal flow. — _PARTIAL._
- [ ] **Real-time collaboration / shared sessions.** — _ABSENT._

## 3. Embeddable @openbench/chat-ui SDK — OEM / white-label revenue

_Sells to: developer-tools and product teams who want to drop a governed agent
chat into their own app. A second revenue path beyond the hosted product._

- [x] **Publishable React SDK.** `ChatProvider`, `ChatPanel`, `MessageList`,
  `SessionSidebar`, hooks (`useChat`, `useA2UIProcessor`), AG-UI transport, A2UI
  renderer, prebuilt CSS. — _SHIPPED `studio/chat-ui/src/index.ts`._
- [x] **White-label theming.** A2UITheme (brand color, logo, agent name) + dark
  mode via `[data-theme]`, Notion-inspired monochrome design system. — _SHIPPED
  A2UITheme + `docs/DESIGN_SYSTEM.md`._
- [ ] **npm publish + versioned docs / Storybook.** Make `@openbench/chat-ui` a
  first-class, documented dependency. — _PARTIAL._
- [ ] **Drop-in embed snippet / iframe widget** for non-React hosts. — _ABSENT._

## 4. Orchestration & Extensibility Platform — the lock-in

_Sells to: AI platform + internal automation teams who want one control plane that
connects their existing stack instead of replacing it. Breadth here drives retention._

- [x] **DAG workflows.** `|` / `&` operators, conditional + router routing, named
  workflows, L2 layer composition. — _SHIPPED `core/chainable.py`, `workflows/workflow.py`._
- [x] **Five framework adapters** (LangChain, CrewAI, AG2, E2B, Google ADK). —
  _SHIPPED (ADK streaming still a stub)._ The "we connect, not replace, your stack" pitch.
- [x] **Skills system.** Two-tier SDK + project registry, 7 bundled skills,
  convention-based tool discovery, knowledge-only skills. — _SHIPPED `intelligence/skill_registry.py`._
- [x] **Personas** (SOUL / STYLE / AGENTS identity layer). — _SHIPPED `intelligence/persona.py`._
- [x] **RAG / data layer.** Pinecone + hybrid (vector + BM25) search, Google/OpenAI
  embeddings, chunking, grounded web search w/ citations, LangExtract entity
  extraction, PDF/EPUB sources, query rewriter, multi-hop RAG. — _SHIPPED `data/`, `intelligence/`._
- [ ] **Marketplace** for skills / agents / MCP servers (publish + install). The
  registry exists; no publishing/install UX yet. — _ABSENT._ A network-effect + monetization lever.
- [ ] **Workflow template gallery.** Productize `examples/` (research, RAG,
  spreadsheet analysis, report gen, codebase Q&A, MCP tool use). — _PARTIAL._ Cuts time-to-first-value.
- [ ] **Visual workflow builder / run inspector.** — _ABSENT._
- [ ] **Finish output generators: dashboard + audio/TTS.** PDF / Markdown / PPTX
  ship; dashboard and audio are `NotImplementedError`. — _STUB `output/generators/{dashboard,audio}.py`._
  Unlocks the "one run → report, deck, and podcast" upsell.
- [ ] **Multi-provider LLM: OpenAI + Anthropic providers.** Only Gemini is
  implemented today. — _ABSENT._ Provider-neutrality removes a hard lock-in objection.

## 5. Packaging & Monetization — code-backed

_Sells to: the economic buyer. Turns shipped capability into a priceable product._

- [x] **Self-hostable deployment.** GCP VM + Docker Compose + nginx/TLS, Firebase
  Hosting SPA, email-allowlist auth, one-command `deploy.sh`. — _SHIPPED `deploy/`._
- [x] **Provider flexibility + model cost registry.** Pluggable providers, per-model
  `cost_per_1k_input/output`. — _SHIPPED `core/config.py`, `core/providers.py`._
- [ ] **Usage metering** (runs / tool-calls / tokens / seats / provider spend)
  built off the existing metrics sink. — _PARTIAL: metrics exist, no meter/billing rollup._
- [ ] **Tiered packaging:** OSS core / paid team workspace / enterprise self-host. — _hypothesis._
- [ ] **Deployment templates:** one-file local Docker Compose, Helm/K8s, air-gapped. — _PARTIAL / ABSENT._
- [ ] **Procurement kit:** security overview, architecture diagram, pricing page,
  implementation guide, support policy. — _ABSENT._

---

## My TODOs: Custom Docker MCP And Secret Manager

- [x] Add a Secret Manager flow for custom Docker MCP setup.
- [x] When a user imports or asks to use a custom Docker MCP server, accept safe
  Docker env values from pasted JSON `env` blocks and manual key/value rows.
- [x] Let the user store Docker env values in a managed encrypted store instead
  of writing plaintext into MCP config.
- [x] Pass secrets into Docker MCP at runtime through env injection or
  Docker/ToolHive secret support.
- [ ] Show which secrets are required, optional, and missing before enabling the
  MCP server.
- [ ] Redact secrets in the UI, logs, registry files, permission prompts, audit
  records, and diagnostics.
- [x] Add a clear fallback for local development where users can keep secrets in
  their own environment variables without OpenBench storing them.
