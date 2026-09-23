# Hermes runtime for general-chat agents

Optional. An agent profile (Agen panel) can be answered by its **own Hermes
Agent profile** instead of the built-in OpenBench `BaseAgent`. Default
runtime is unchanged; nothing here runs unless an agent is switched to
`Runtime: Hermes`.

Hermes Agent = open-source self-hosted agent runtime by Nous Research
(`NousResearch/hermes-agent`, MIT). No Hermes/Nous account is needed; it runs
on the existing Gemini API key. Everything below was checked against the
source of release **v2026.9.14**.

## What Hermes loads by default (and what we turn off)

| Default | Cost / risk | How the generated profile removes it |
|---|---|---|
| `hermes-api-server` toolset = every core tool (terminal, process, read/write/patch files, browser_*, web, vision, image gen, skills, todo, memory, session search, execute_code, delegate_task, cronjob, HA) | dozens of tool schemas in every request; host access | `platform_toolsets.api_server` is an explicit allow-list (a saved list is authoritative in `_get_platform_tools`) **and** every unselected built-in toolset is listed in `agent.disabled_toolsets` (applied last, overrides everything) |
| Bundled skills seeded into every profile and re-synced by `hermes update`; all installed skills indexed in the prompt | skill index tokens; skills the agent was never given | `.no-bundled-skills` marker (Hermes then seeds only its essential skill); only the agent's own knowledge skills are copied into `skills/`; `skills` toolset stays off when the agent has none |
| Every enabled `mcp_servers` entry merged into the platform toolset, all tools + resources/prompts wrappers | tool schemas of servers the agent should not see | only this agent's servers are written; each has `tools.include` allow-list, `resources: false`, `prompts: false`, `sampling.enabled: false`; `no_mcp` sentinel when it has none |
| `memory.memory_enabled` + `user_profile_enabled` (MEMORY.md/USER.md injected, memory tool, nudges) | ~1.3k tokens + cross-session carry-over | both off unless `memory: true`; `nudge_interval: 0` |
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

## Local run

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

## Separate VM

```bash
python -m general_chat.hermes_profile hermes/agents.yaml --out hermes/profiles \
  --compose hermes/docker-compose.hermes.yml --bind-ip <VM private IP>
docker compose -f hermes/docker-compose.hermes.yml up -d --build
```

One container, one profile volume and one network per agent; no docker
socket; ports published on the private IP only. Restrict that IP/port range
to the SSS VM with a VPC firewall rule. The SSS side needs only the
`GENERAL_CHAT_HERMES_KEY_*` variables in `.env.gcp` and the agents' URLs.

## Tests

- `tests/test_hermes_adapter.py` — HTTP adapter (mocked).
- `tests/test_general_chat_hermes_runtime.py` — profile fields, per-agent key
  lookup, registry builds, 503 (never a fallback agent) when Hermes is unbuildable.
- `tests/test_general_chat_hermes_profile.py` — minimal defaults, MCP
  allow-lists, and cross-agent isolation of the rendered profiles/compose.
- `tests/test_general_chat_hermes_live_isolation.py` — against two running
  Hermes servers (skipped unless `HERMES_LIVE_*` env is set).

## Revert

Runtime switch: set the agent back to `Runtime: OpenBench` — next turn uses
`BaseAgent` again (registry is invalidated on save). Code: everything landed
after tag `pre-hermes-2026-09-21`; `git revert pre-hermes-2026-09-21..HEAD`
(or reset to the tag) removes it. Stored profiles keep working either way —
unknown `runtime`/`hermesUrl` keys are ignored by older code.
