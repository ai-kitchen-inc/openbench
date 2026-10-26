# Hermes runtime for general-chat agents

Optional. An agent profile (Agen panel) can be answered by its **own Hermes
Agent profile** instead of the built-in OpenBench `BaseAgent`. Default
runtime is unchanged; nothing here runs unless an agent is switched to
`Runtime: Hermes`.

Two modes:

- **Managed (default, same host)** — leave the Hermes URL empty. SSS renders the
  agent's minimal Hermes profile from the panel fields, runs its gateway, and
  holds every key itself. Set up entirely from the Agen panel. Needs
  `GENERAL_CHAT_HERMES_BACKEND` on the server (`process` locally, `docker` on
  the VM).
- **Remote** — enter a Hermes URL. The profile is run elsewhere (see *Remote
  mode* below) and its key comes from `GENERAL_CHAT_HERMES_KEY_<AGENT_ID>`.

Hermes Agent = open-source self-hosted agent runtime by Nous Research
(`NousResearch/hermes-agent`, MIT). No Hermes/Nous account is needed; it runs
on the existing Gemini API key. Everything below was checked against the
source of release **v2026.9.14**.

## Measured (2026-09-21, v2026.9.14, gemini-3.5-flash, one-line question)

| Profile | Toolsets / tools | Prompt tokens per request |
|---|---|---|
| Stock Hermes defaults | 14 / 38 tools, 58 skills indexed | **12,379** |
| Minimal + Hermes `skills` toolset + memory | 2 / 4 | 8,784 |
| Minimal + Hermes `skills` toolset | 1 / 3 | 6,607 |
| **Minimal, own skill inlined in SOUL.md (generator default)** | 0 / 0 | **977** |
| Bare minimal (no skills) | 0 / 0 | 926 |

Generator default vs stock: **-92%** prompt tokens, with the agent's skill
still applied. The Hermes `skills` toolset alone costs ~5.7k tokens and
memory ~2.2k, so both are opt-in per agent (`inline_skills: false`,
`memory: true`). Each MCP tool an agent is given adds its own schema on top.

## What Hermes loads by default (and what we turn off)

| Default | Cost / risk | How the generated profile removes it |
|---|---|---|
| `hermes-api-server` toolset = every core tool (terminal, process, read/write/patch files, browser_*, web, vision, image gen, skills, todo, memory, session search, execute_code, delegate_task, cronjob, HA) | dozens of tool schemas in every request; host access | `platform_toolsets.api_server` is an explicit allow-list (a saved list is authoritative in `_get_platform_tools`) **and** every unselected built-in toolset is listed in `agent.disabled_toolsets` (applied last, overrides everything) |
| Bundled skills seeded into every profile and re-synced by `hermes update`; all installed skills indexed in the prompt | skill index tokens; skills the agent was never given | `.no-bundled-skills` marker (Hermes then seeds only its essential `hermes-agent` skill); the agent's own knowledge skills are inlined into `SOUL.md` and the `skills` toolset stays off (default), or copied into `skills/` with the toolset on when `inline_skills: false` |
| Every enabled `mcp_servers` entry merged into the platform toolset, all tools + resources/prompts wrappers | tool schemas of servers the agent should not see | only this agent's servers are written; each has `tools.include` allow-list, `resources: false`, `prompts: false`, `sampling.enabled: false`; `no_mcp` sentinel when it has none |
| `memory.memory_enabled` + `user_profile_enabled` (MEMORY.md/USER.md injected, memory tool, nudges) | ~2.2k tokens measured + cross-session carry-over | both off unless `memory: true`; `nudge_interval: 0` |
| Skill-creation nudge every 15 tool iterations | extra prompt text, self-written skills | `skills.creation_nudge_interval: 0` |
| Tool subprocess HOME = real user HOME | shared CLI credentials | `terminal.home_mode: profile` |
| Passive update checks, `max_turns: 500` | noise, runaway loops | `updates.check: false`, `max_turns: 30` |

Host-reaching toolsets (`terminal`, `file`, `browser`, `code_execution`,
`delegation`, `cronjob`, `computer_use`) are **refused** by the generator
unless the agent entry sets `allow_host_access: true` — a Hermes profile is
not a sandbox.

## What is isolated per agent

| Thing | Where it lives | Shared with other agents? |
|---|---|---|
| config, persona (`SOUL.md`) | `profiles/<agent>/` | no |
| skills | `profiles/<agent>/skills/` | no |
| MCP servers + tool allow-list | `profiles/<agent>/config.yaml` | no |
| memory, sessions, `state.db` | `profiles/<agent>/{memories,sessions,state.db}` | no |
| LLM key, MCP secrets, `API_SERVER_KEY` | `profiles/<agent>/.env` | no (own key per agent) |
| process / port / network (VM) | one container + one network per agent | no |
| SSS → Hermes credential | `GENERAL_CHAT_HERMES_KEY_<AGENT_ID>` in the SSS server env | one env var per agent; never in the DB or admin API |

Hermes keeps the transcript per `X-Hermes-Session-Id`; SSS sends its chat
session id, so two SSS sessions never share a Hermes transcript, and an
agent's transcripts exist only in that agent's `state.db`.

Not carried over from the OpenBench runtime: tool-bearing OpenBench skills
(`tools.py`), agent sources (RAG) and A2UI rich output (charts/tables/files).
Expose those through an MCP server if a Hermes agent needs them; otherwise
keep that agent on the default runtime.

## Managed mode (same host) — set up from the Agen panel

Server, once:

```bash
# local dev: Hermes installed in a venv (official repo at the pinned tag)
export GENERAL_CHAT_HERMES_BACKEND=process
export GENERAL_CHAT_HERMES_BIN=/c/Users/Admin/hermes-spike/venv/Scripts/hermes.exe
# VM: GENERAL_CHAT_HERMES_BACKEND=docker in .env.gcp (see deploy/DEPLOY.md)
```

Then per agent, in the panel: **Runtime: Hermes**, leave URL empty, Simpan,
*Mulai Hermes* (or just chat — it starts on the first turn). What the panel
fields become:

| Panel field | Hermes profile |
|---|---|
| Persona (agent or global) + Guardrails | `SOUL.md` |
| Model | `model.default` (provider gemini) |
| Skills without `tools.py` (SDK or custom) | inlined into `SOUL.md` |
| Skills with `tools.py` | skipped, listed as a warning in the panel |
| MCP servers (enabled tools only) | `mcp_servers.<name>.tools.include`; secrets as env |
| Memori Hermes switch | `memory.memory_enabled` + `memory` toolset |
| Skill bawaan Hermes switch | no `.no-bundled-skills` marker (Hermes seeds its ~58 bundled skills) + `skills` toolset (+~5.7k tokens/request) |
| Toolset bawaan Hermes checklist | those toolsets in `platform_toolsets.api_server`, removed from `agent.disabled_toolsets` |
| Sumber agen, escalation, rich output | not available in Hermes |

The checklist offers `web, browser, vision, image_gen, terminal, file,
code_execution, todo, session_search, delegation` ("Aktifkan semua bawaan" ticks
all of them plus bundled skills; "Minimal" clears them). Host-reaching ones
(`terminal, file, browser, code_execution, delegation`) are accepted only on the
`docker` backend, where they run inside the agent's own container (cwd
`/opt/data/workspace`); the `process` backend refuses them (400 in the API, a
warning + skip in the plan). `web` works without a key through Hermes' keyless
free-tier fallback; `browser` uses the headless Chromium baked into the image.
See [cases/tokopedia.md](cases/tokopedia.md) for a worked example.

Profiles live in `<storage_root>/hermes/<agent>/`. `GOOGLE_API_KEY` and MCP
secrets are passed to the gateway as environment and never written there; the
per-agent `API_SERVER_KEY` is generated on first render, kept in that dir, and
never returned by the admin API. Saving a change in the panel restarts that
agent's gateway on its next turn; leaving the runtime stops it; deleting the
agent deletes its Hermes memories and sessions.

Verified live (2026-09-21, process backend): two managed agents started by SSS
in ~5 s each, each answering from its own persona over `/agents/<id>/awp`; LLM
key absent from both profile dirs; persona edit picked up on the next turn;
runtime switch stopped the gateway; delete removed the profile. One gateway
uses ~180–200 MB RSS. The `docker` backend is unit-tested only (container
flags, no socket, secrets by name) — not yet run against a real daemon.

## Remote mode — local run

```bash
# 1. describe the agents
cp hermes/agents.example.yaml hermes/agents.yaml        # then edit

# 2. render one isolated profile per agent (safe to re-run)
python -m general_chat.hermes_profile hermes/agents.yaml --out hermes/profiles

# 3. fill the empty keys the command lists (GOOGLE_API_KEY, MCP secrets)
#    in hermes/profiles/<agent>/.env  — do this yourself, never commit them

# 4. start one Hermes gateway per agent (Hermes installed separately)
HERMES_HOME=hermes/profiles/<agent> hermes gateway run

# 5. give SSS that agent's key, then in the Agen panel set
#    Runtime: Hermes and URL http://127.0.0.1:<port>
export GENERAL_CHAT_HERMES_KEY_<AGENT_ID>=<API_SERVER_KEY from that .env>
```

`<AGENT_ID>` = agent id upper-cased with every non-alphanumeric as `_`
(`analis-keuangan` → `GENERAL_CHAT_HERMES_KEY_ANALIS_KEUANGAN`).

## Remote mode — separate VM

```bash
python -m general_chat.hermes_profile hermes/agents.yaml --out hermes/profiles \
  --compose hermes/docker-compose.hermes.yml --bind-ip <VM private IP>
docker compose -f hermes/docker-compose.hermes.yml up -d --build
```

One container, one profile volume and one network per agent; no docker
socket; ports published on the private IP only. Restrict that IP/port range
to the SSS VM with a VPC firewall rule. The SSS side needs only the
`GENERAL_CHAT_HERMES_KEY_*` variables in `.env.gcp` and the agents' URLs.

## Verified live (local, two gateways)

All 7 checks of `tests/test_general_chat_hermes_live_isolation.py` pass:
A's key is rejected by B (401) and vice versa on chat, toolsets and
sessions; only the selected toolsets are enabled; skills/MCP/profile dirs
and `.env` credentials do not overlap; a secret told to A in a session is
absent from B's session list, B's transcript for the same session id, and
B's answer when asked to recall it. Through `HermesAgent`: streaming chunks,
token usage, and turn-2 recall from Hermes' own session store all work.

Known upstream issue in v2026.9.14: `GET /v1/skills` answers 500
(`_find_all_skills() got an unexpected keyword argument`); the probe falls
back to scanning the profile's `skills/` dir. Not yet exercised: the
docker-compose file (Docker was not running) and MCP servers against a real
MCP endpoint.

## Tests

- `tests/test_hermes_adapter.py` — HTTP adapter (mocked).
- `tests/test_general_chat_hermes_runtime.py` — profile fields, per-agent key
  lookup, registry builds, 503 (never a fallback agent) when Hermes is unbuildable.
- `tests/test_general_chat_hermes_supervisor.py` — managed mode: supervisor
  lifecycle (process + docker backends), panel-fields → profile plan, status/start
  endpoints, stop on runtime switch, remove on delete.
- `tests/test_general_chat_hermes_profile.py` — minimal defaults, MCP
  allow-lists, and cross-agent isolation of the rendered profiles/compose.
- `tests/test_general_chat_hermes_live_isolation.py` — against two running
  Hermes servers (skipped unless `HERMES_LIVE_*` env is set).

## Revert

Runtime switch: set the agent back to `Runtime: OpenBench` — next turn uses
`BaseAgent` again (registry is invalidated on save). Code: everything landed
after commit `a768178`; `git revert --no-edit a768178..HEAD`
(or reset to that commit) removes it. Stored profiles keep working either way —
unknown `runtime`/`hermesUrl` keys are ignored by older code.
