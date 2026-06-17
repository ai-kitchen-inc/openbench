# OpenBench Business And Product Roadmap

This roadmap focuses on turning OpenBench into a product that teams can
understand, evaluate, trust, and pay for. The engineering roadmap belongs in
`ROADMAP.md`; this file tracks buyer value, packaging, monetization, adoption,
and product proof.

## Product Thesis

- [ ] Position OpenBench as a controllable agent workflow platform for teams
  that need AI tools to be observable, governable, and useful in production.
- [ ] Make General Chat the primary product surface for demos, onboarding, MCP
  tool approvals, source discovery, and day-to-day agent work.
- [ ] Sell the trust layer: MCP permissions, audit logs, policy controls,
  redaction, and self-hosting should be part of the core product story.
- [ ] Package workflow orchestration, reusable templates, source connectors, and
  provider flexibility as one platform rather than separate SDK features.

## Ideal Customers

- [ ] AI platform teams that need a shared control plane for internal agent
  tools and workflows.
- [ ] Developer tools teams building assistants over code, docs, tickets,
  files, and internal services.
- [ ] Internal automation teams replacing one-off scripts with auditable AI
  workflows.
- [ ] Compliance-sensitive teams adopting MCP but worried about unsafe tool
  execution, private data exposure, and untracked side effects.
- [ ] Startups and consulting teams that need repeatable AI workflow demos they
  can customize quickly for customers.

## Buyer Pain Points

- [ ] Agent prototypes are easy to build but hard to operate safely across a
  team.
- [ ] Tool calls can read private data, contact external services, or change
  state without enough user visibility.
- [ ] Teams lack observability for prompts, tools, approvals, failures, latency,
  and cost.
- [ ] MCP setup is powerful but still too technical for many users, especially
  when Docker, secrets, and custom servers are involved.
- [ ] Business leaders need repeatable ROI stories, not only framework
  flexibility.

## Differentiation

- [ ] Combine workflow orchestration, General Chat, MCP tool management,
  permission gating, auditability, templates, and self-hosting in one product.
- [ ] Treat user approval and tool transparency as first-class UX, not an
  afterthought.
- [ ] Support both open-source developer adoption and paid team/enterprise
  deployment.
- [ ] Make OpenBench framework-friendly instead of framework-replacing:
  LangChain, CrewAI, AG2, Google ADK, E2B, MCP, and custom tools can plug in.
- [ ] Build around buyer trust: visible controls, clear risk labels, redacted
  secrets, and deployable infrastructure.

## P0: Prove Buyer Value

- [ ] Create a polished 5-minute demo showing a user asking a question,
  approving an MCP tool call, seeing the result, and reviewing the audit trail.
- [ ] Write the core sales narrative: "OpenBench helps teams run AI workflows
  with human approval, observability, and control."
- [ ] Define 3 repeatable use cases with before-and-after ROI:
  document research, internal knowledge assistant, and MCP-enabled operations
  assistant.
- [ ] Build onboarding around time-to-first-value: connect provider, load sample
  data, enable one safe MCP tool, approve a tool call, and get a useful answer.
- [ ] Recruit 10 design partners and track their top blockers, requested
  integrations, security concerns, and willingness to pay.
- [ ] Create a buyer-facing trust page covering permissions, redaction,
  self-hosting, audit logs, and secret handling.

## P1: Package The Product

- [ ] Launch a hosted or locally runnable General Chat workspace with saved
  sessions, project sources, MCP catalog, tool approvals, and run history.
- [ ] Build a Workflow Template Gallery with productized examples for research,
  RAG, spreadsheet analysis, report generation, codebase Q&A, and MCP tool use.
- [ ] Add observability dashboards for run traces, tool calls, approvals,
  latency, token usage, cost estimates, errors, and retries.
- [ ] Add evals and benchmarks so teams can compare providers, prompts,
  workflows, cost, and quality before production use.
- [ ] Add team controls: users, roles, projects, shared sessions, source access,
  and admin-visible audit logs.
- [ ] Create packaging and pricing hypotheses:
  open-source core, paid team workspace, and enterprise self-hosted plan.

## P2: Monetize And Expand

- [ ] Add enterprise governance: policy packs, approval rules, data retention,
  audit exports, access controls, and redaction settings.
- [ ] Add deployment templates for Docker Compose, GCP, and eventually
  air-gapped environments.
- [ ] Add usage metering for runs, tool calls, tokens, storage, seats, and
  provider spend.
- [ ] Add marketplace packaging for reusable agents, MCP servers, source
  connectors, workflow templates, and output generators.
- [ ] Add procurement-ready materials: security overview, architecture diagram,
  pricing page, implementation guide, and support policy.
- [ ] Add customer expansion paths from single-user demo to team workspace to
  enterprise deployment.

## Business Validation Checklist

- [ ] Identify 10 design partners and record their team size, use case, current
  workaround, budget owner, and security requirements.
- [ ] Define 3 buyer personas: AI platform lead, developer tools lead, and
  internal automation owner.
- [ ] Build a demo script for each repeatable use case and keep screenshots or
  short recordings current.
- [ ] Track activation rate, time-to-first-value, tool approval rate, successful
  run rate, weekly retained usage, and design partner conversion.
- [ ] Interview users after failed runs to learn whether the blocker is setup,
  trust, quality, missing integrations, or unclear value.
- [ ] Create pricing tests for open-source support, team SaaS, and enterprise
  self-hosted licensing.

## My TODOs: Custom Docker MCP And Secret Manager

- [ ] Add a Secret Manager flow for custom Docker MCP setup.
- [ ] When a user imports or asks to use a custom Docker MCP server, detect
  secret-like env vars such as `API_KEY`, `TOKEN`, `SECRET`, `PASSWORD`, and
  `HF_TOKEN`.
- [ ] Let the user optionally store detected secret values in a managed secret
  store instead of writing plaintext into MCP config.
- [ ] Pass secrets into Docker MCP at runtime through env injection or
  Docker/ToolHive secret support.
- [ ] Show which secrets are required, optional, and missing before enabling the
  MCP server.
- [ ] Redact secrets in the UI, logs, registry files, permission prompts, audit
  records, and diagnostics.
- [ ] Add a clear fallback for local development where users can keep secrets in
  their own environment variables without OpenBench storing them.

## Product Assumptions

- [ ] OpenBench should be paid and self-hostable, with an open-source core that
  drives developer adoption.
- [ ] The primary buyer value is control over agent workflows, not just access
  to another chat UI.
- [ ] Permissioned MCP tool use, observability, and audit logs are the strongest
  trust wedge for the product.
- [ ] Product work should prioritize repeatable buyer outcomes before broad
  feature expansion.
