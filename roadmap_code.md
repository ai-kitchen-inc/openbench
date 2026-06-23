# Code Quality Roadmap — OpenBench

Prioritized to-do list derived by cross-checking the attached senior-engineer
code-quality roadmap (`roadmap_product.md` checklist) against the actual
codebase. Every item is grounded in a concrete `file:line` finding and mapped
to the roadmap section it satisfies. Ordered by risk × reach.

**Legend:** P0 = security/correctness (do first) · P1 = reliability · P2 = testing · P3 = maintainability/architecture.

---

## P0 — Security & Correctness

Maps to roadmap "Red Flags" (§16): auth, secrets, input boundaries.

- [ ] **Enforce credential encryption by default.** `ProviderService` defaults
  `require_encryption=False` ([core/providers.py:228](src/openbench/core/providers.py)),
  and silently falls back to plaintext `~/.openbench/providers.json` when the
  `cryptography` extra is absent ([core/providers.py:67-71](src/openbench/core/providers.py)).
  → Make encryption default-on, or refuse loudly at startup in production.
  *(§2.6 Security, §8 Security To-Do)*

- [x] **Validate untrusted input at the chat transport boundary.**
  `await request.json()` is parsed with no schema, then fields are trusted
  directly ([chat/transport/agui.py:181](src/openbench/chat/transport/agui.py));
  action name and `session_id` are unvalidated
  ([chat/transport/agui_actions.py:110-119](src/openbench/chat/transport/agui_actions.py),
  [chat/transport/agui.py:253](src/openbench/chat/transport/agui.py)).
  → Add JSON-schema validation + length/format/type bounds at the HTTP/SSE edge.
  *(§2.6, §3.7 Security Design, §8)*

- [ ] **Add an authorization model to action handlers.** No RBAC — any
  registered handler is invocable by any request that knows the name
  ([chat/transport/agui_actions.py:126-129](src/openbench/chat/transport/agui_actions.py)).
  → Enforce per-action permission at the trusted boundary. *(§2.6, §3.7)*

- [ ] **Stop logging untrusted input and leaking exception internals.** Raw
  action name logged verbatim ([chat/transport/agui_actions.py:121](src/openbench/chat/transport/agui_actions.py));
  decrypt failure may surface ciphertext/algorithm detail
  ([core/providers.py:96-98](src/openbench/core/providers.py)); permission-provider
  exception text passed back to caller
  ([mcp/permissions.py:236-241](src/openbench/mcp/permissions.py)).
  → Redact at log sites; return generic errors externally. *(§2.6, §8)*

- [ ] **Harden the prompt-injection surface.** User query is f-string-embedded
  straight into an LLM prompt
  ([data/sources/grounded_search.py:285-287](src/openbench/data/sources/grounded_search.py));
  tool-call arguments from the model are parsed without schema validation
  ([intelligence/llm_providers.py:178-201](src/openbench/intelligence/llm_providers.py)).
  → Validate/escape user-controlled text; schema-check tool args before dispatch. *(§2.6)*

---

## P1 — Reliability & Error Handling

- [ ] **Broaden retry beyond rate-limit.** Retry triggers only on
  `429`/`RESOURCE_EXHAUSTED`
  ([intelligence/llm_providers.py:448-487](src/openbench/intelligence/llm_providers.py));
  Pinecone upsert has the same narrow guard
  ([data/stores/pinecone.py:417-440](src/openbench/data/stores/pinecone.py)).
  → Also retry 503 / network timeout / connection reset, with exponential
  backoff + jitter. *(§2.5 Reliability, §10 Reliability To-Do)*

- [ ] **Add explicit timeouts to all external calls.** Embedding APIs rely on
  SDK defaults ([intelligence/embeddings.py](src/openbench/intelligence/embeddings.py));
  Perplexity/OpenAI search call sets no timeout
  ([data/sources/grounded_search.py:306](src/openbench/data/sources/grounded_search.py),
  [grounded_search.py:313](src/openbench/data/sources/grounded_search.py)).
  → Configurable per-call timeouts. *(§10)*

- [ ] **Fix silent exception swallows (~15-20 broad `except Exception:`).**
  Log-and-continue hides the real cause: session load/save
  ([chat/transport/agui.py:114-137](src/openbench/chat/transport/agui.py)),
  Pinecone dimension validation `except: return`
  ([data/stores/pinecone.py:247-249](src/openbench/data/stores/pinecone.py)),
  tool-schema conversion ([intelligence/llm_providers.py:261-266](src/openbench/intelligence/llm_providers.py)).
  → Distinguish error classes; re-raise programmer errors; preserve context. *(§2.5, §4.5 Error Handling)*

- [ ] **Replace fixed-interval polling with backoff.** Pinecone index-ready
  wait polls at a fixed 1s for 60s
  ([data/stores/pinecone.py:268-280](src/openbench/data/stores/pinecone.py)).
  → Exponential backoff with a bounded ceiling. *(§10)*

---

## P2 — Testing Gaps

Snapshot today: **78 test files / 141 source files (~55% by count).** LLM and
embedding tests already mock cleanly via the `no_provider_env` fixture
(`tests/conftest.py`) — extend that discipline to the gaps below.

- [ ] **Test `intelligence/base.py` directly** — 1486 LOC, the critical path
  (BaseAgent reasoning loop, ToolExecutor) has only indirect coverage via
  `test_agents.py`. *(§5.1 Unit Tests)*

- [ ] **Test output generators.** Only PDF is tested; Markdown / PowerPoint /
  Dashboard / Audio are untested and partly stubbed
  ([output/generators.py:813](src/openbench/output/generators.py),
  [generators.py:886](src/openbench/output/generators.py)). *(§5.1)*

- [ ] **Test vector-store layer with mocked SDK** —
  `data/stores/base.py` (399 LOC) and `data/stores/pinecone.py` (623 LOC) have
  no dedicated tests. Also untested: `core/storage.py`,
  `intelligence/skill_registry.py`, `intelligence/layer.py`, and all CLI
  commands except `demo.py`. *(§5.1, §5.2 Integration Tests)*

---

## P3 — Maintainability, Architecture, Observability

- [x] **Split god-modules.** `intelligence/base.py` (1486 LOC, 5+
  responsibilities) → extract `ToolExecutor`, `AgentMemory`, `QueryRewriter`,
  `Message`/`MessageRole` into focused modules. `output/generators.py`
  (890 LOC, 5 formats) → one class per file. *(§7.2 Architecture Smells, §11 Maintainability)*
  *Done: `base.py` → `messages.py` + `agent_memory.py` + `tool_executor.py` +
  `query_rewriter.py` (base re-exports all for backward compat). `generators.py`
  → `output/generators/` package (pdf/markdown/powerpoint/dashboard/audio, one
  class per file; both import paths preserved).*

- [x] **Replace `print()` with structured logging.** ~20 files (CLI +
  others) write to stdout, bypassing log levels and structured capture.
  → Route through `logging.getLogger(__name__)`. *(§2.9 Observability)*
  *Done: the "~20 files" was a grep overcount — CLI uses `rich.Console`
  (intentional UX), the rest were docstring `>>>` examples or the e2b sandbox
  `python -c` string. Only genuine stdout violation was the chart-push
  diagnostics in `skills/data-visualization/tools.py` → now `logger`.*

- [x] **Add observability to the agent reasoning loop.** No correlation IDs or
  metrics around the loop ([intelligence/base.py:1140-1330](src/openbench/intelligence/base.py))
  or tool-execution timing. → Reuse the existing `mcp/observability.py`
  `correlation_id` contextvar + `MCPMetrics` sink. *(§2.9)*
  *Done: `BaseAgent.execute()` scopes a `correlation_context()` over the loop,
  times each LLM call (`agent.llm_generate`) and emits `agent.execute` /
  `agent.total_ms`; `ToolExecutor.execute()` times each dispatch
  (`agent.tool_execute`). All via lazy import to avoid an mcp↔intelligence cycle.*

- [ ] **Centralize scattered magic constants.** Timeouts (30s/5s/15s/60s),
  batch sizes (100), and `max_retries=3` are duplicated across `base.py`,
  `cli/commands/demo.py`, and `pinecone.py`; CLI hardcodes `gpt-4`
  ([cli/commands/agent.py:30](src/openbench/cli/commands/agent.py)) vs the
  `core/config.py` default. → Extract to `core/constants.py` / config. *(§4.2 Naming, §11)*

- [ ] **Provide a true async agent path.** `BaseAgent.execute()` is synchronous
  and blocks inside the async transport
  ([intelligence/base.py:1127-1329](src/openbench/intelligence/base.py)); no
  async LLM provider interface exists. → Add async variant or
  `asyncio.to_thread()` wrapper. *(scalability / §2.7 Performance)*

- [ ] **Resolve documented stubs (decide: implement or remove from public
  surface).** `NotImplementedError` in Google ADK streaming
  ([adapters/google_adk.py:285](src/openbench/adapters/google_adk.py),
  [google_adk.py:377](src/openbench/adapters/google_adk.py)), output generators
  (above), and OpenAI/Anthropic LLM provider TODOs
  ([intelligence/llm_providers.py:762](src/openbench/intelligence/llm_providers.py),
  [llm_providers.py:778](src/openbench/intelligence/llm_providers.py)). *(§11)*

- [ ] **Raise mypy strictness incrementally.** `disallow_untyped_defs = false`
  with 9 module overrides today (`pyproject.toml`). Type-hint coverage ~80%.
  → Tighten module-by-module. *(§4.4 Types and Contracts)*

---

## Already Strong — Do Not Disturb

These already satisfy the roadmap and need no work:

- **Clean public API + stability contracts** — narrow `__all__`
  ([__init__.py](src/openbench/__init__.py)); explicit additive-only ABC
  guarantees ([intelligence/memory.py:42-81](src/openbench/intelligence/memory.py)).
  *(§7.1, §3.4 API Design)*
- **Concurrency safety** — threading locks + `contextvars.copy_context()` for
  parallel tool execution; atomic memory turns. *(§4.6 State Management)*
- **Bounded reasoning loop** — `max_iterations` enforced
  ([intelligence/base.py](src/openbench/intelligence/base.py)). *(§2.7)*
- **Batching** — embedding and Pinecone upsert paths are batched, not N+1.
  *(§2.7, §9 Performance)*
- **Centralized config** — `core/config.py` single source of truth with env
  expansion. *(§11)*
- **No code-injection vectors** — no `eval`/`exec`/`os.system`/`shell=True` in
  library code; vector-store filters are type-sanitized. *(§8)*
