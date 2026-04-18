# LCI Mini — Persona + Skill Layer Demo

A minimal **web chat** example showing how to build an OpenBench agent whose
identity and capabilities both live in files, not Python. Meet **Lici**, an
LCI/LCA consultant assistant for Indonesian LCA practitioners preparing
PROPER 2025 submissions.

## What this example demonstrates

- **`Persona.from_dir()`** — loading agent identity from `soul/SOUL.md`,
  `soul/STYLE.md`, and `soul/AGENTS.md`
- **`BaseAgent(persona=..., skills=[...])`** — wiring the composed persona
  and a bundled **Skill Layer** into the agent without hard-coding
  `system_prompt=` or tool registrations in Python
- **`xql` skill** — Excel-as-RDBMS with 14 SQL-like primitives (SELECT,
  WHERE, GROUP BY, PARETO, JOIN, UNION, PIVOT, BUILD_IO_TABLE, ...).
  Lives at `skills/xql/` with its own `SKILL.md`, `tools.py`, YAML config
  for aliases/units/LCI rules, and reference docs
- **Persistent memory** — each chat thread gets its own SQLite-backed session
- **React chat UI** — reuses `@openbench/chat-ui` and shows live Persona +
  Skills badges (character counts, loaded tools) in the sidebar

Unlike the full [LCI Ignite X](../lci-ignite-x/) app (which does real LDI
parsing, Pareto hotspot analysis, and Excel export), Lici is **knowledge
only** — she answers methodology questions, interprets PROPER criteria, and
coaches consultants on data interpretation.

## Directory layout

```
examples/lci-mini/
├── server.py                 # uvicorn entry point (port 8004)
├── soul/                     # --- Persona Layer ---
│   ├── SOUL.md               # WHO Lici is (identity, domain, boundaries)
│   ├── STYLE.md              # HOW she communicates (bilingual ID/EN, tone)
│   └── AGENTS.md             # WHAT modes she operates in (4 modes)
├── skills/                   # --- Skill Layer ---
│   └── xql/                  # Excel-as-RDBMS project skill
│       ├── SKILL.md          # orchestrator + natural language mapping
│       ├── tools.py          # 14 primitives (catalog, query, transform)
│       ├── config/           # aliases.yaml, units.yaml, lci_rules.yaml
│       └── references/       # grouping-rules.md
├── src/lci_mini/
│   ├── __init__.py
│   ├── agent.py              # create_lici_agent() — persona + skills
│   └── server/
│       ├── app.py            # FastAPI create_app() with /persona, /skills
│       └── handler.py        # LiciAGUIHandler (persistent memory)
├── frontend/                 # React + @openbench/chat-ui (port 5173)
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx           # ChatProvider + PersonaBadge + SkillBadge
│       ├── main.tsx
│       └── global.css
├── tests/
│   └── test_lci_mini.py      # persona + skill layer + XQL end-to-end
├── pyproject.toml
└── .env.example
```

## Prerequisites

- Python ≥ 3.10 with OpenBench installed (`pip install -e .` from repo root)
- Node ≥ 18
- `pnpm` (`npm install -g pnpm`)

## Run (via OpenBench CLI — recommended)

```bash
# 1. Set your API key
cp examples/lci-mini/.env.example examples/lci-mini/.env
# edit .env and set GOOGLE_API_KEY

# 2. Launch (auto-installs Python deps, builds chat-ui, starts backend + frontend)
openbench demo run lci-mini
```

You'll get:

| Service  | URL                   |
|----------|-----------------------|
| Backend  | http://localhost:8004 |
| Frontend | http://localhost:5173 |

Open the frontend URL in your browser and start chatting. The sidebar shows
a **"Persona loaded from soul/"** badge with character counts for each
markdown file so you can confirm what was wired into the agent.

### Backend only (no frontend)

```bash
openbench demo run lci-mini --no-frontend
```

Then POST chat requests to `http://localhost:8004/awp` using the AG-UI
protocol, or call `GET /persona` to inspect the loaded persona.

## Run (manual, without CLI)

```bash
# Backend
cd examples/lci-mini
pip install -e .
export GOOGLE_API_KEY=your-key-here
uvicorn server:app --port 8004 --reload

# Frontend (in another terminal)
cd examples/lci-mini/frontend
pnpm install
pnpm dev
```

## Sample questions

Lici handles four operating modes (see `soul/AGENTS.md`):

| Mode | Example question |
|------|------------------|
| Methodology guidance | *"Jelaskan perbedaan cradle-to-gate dan cradle-to-grave"* |
| PROPER 2025 interpretation | *"Apa saja yang dinilai untuk PROPER Emas?"* |
| Data interpretation coaching | *"Kenapa CO2 selalu jadi hotspot utama?"* |
| Uncertainty handling | *"Haruskah saya pakai GWP100 atau GWP20?"* |

## Tests

```bash
# From repo root
python -m pytest examples/lci-mini/tests/ -v
```

Tests verify (without making any real LLM calls):
- All three persona files exist and are non-empty
- `Persona.from_dir()` loads and composes them in the correct order
  (soul → style → agents)
- `create_lici_agent()` wires the composed prompt into the agent's
  system message and memory
- Lici's identity markers (`"Lici"`, `"PROPER"`) appear in the final prompt
- `create_app()` boots a FastAPI app with `/awp`, `/chat/action`,
  `/persona`, and `/health` routes
- `GET /persona` returns the composed persona contents

## Production deployment (Firebase Auth + Drive OAuth)

For a real deployment with sign-in, per-user storage, and rate-limited
Drive OAuth: see [`docs/AUTH_SETUP.md`](docs/AUTH_SETUP.md).

The short version:

1. Create a Firebase project, enable Email/Google sign-in.
2. Copy the web SDK config into `VITE_FIREBASE_*` env vars.
3. Deploy `firestore.rules` (`firebase deploy --only firestore:rules`).
4. Deploy backend to Cloud Run with `FIREBASE_PROJECT_ID` +
   (optionally) Drive OAuth env vars.
5. Deploy frontend to Firebase Hosting.

For localhost development, add `OPENBENCH_AUTH_DISABLED=1` to `.env`
and skip the rest.

## Editing Lici's identity

You don't need to touch Python to change how Lici behaves:

- Edit `soul/SOUL.md` to change her domain knowledge or boundaries
- Edit `soul/STYLE.md` to adjust tone, language, or formatting rules
- Edit `soul/AGENTS.md` to add or remove operating modes

Restart the server — persona is re-read from disk on startup.
