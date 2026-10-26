# Dashboard Chat

Dashboard-first chat demo: connect your own database, get an AI-generated dashboard from its schema, then refine it by chatting in the side pane.

## What it does

1. **Sign in** with a local account (no cloud auth).
2. **Connect a database** with a single SQLAlchemy URL (SQLite, PostgreSQL, MySQL).
3. The backend **introspects the schema only** — tables, columns, types, keys. Row data never reaches the LLM.
4. The agent **generates a dashboard** (KPIs, charts, tables) and persists it per user.
5. **Chat in the side pane** to change it — add panels, switch chart types, refine queries. The canvas updates after every turn, and the conversation is remembered across logins.

Strict data rule: every panel carries a SQL `SELECT`; the backend executes it (read-only guard, row cap, statement timeout) and streams rows straight to the frontend charts. The LLM only ever sees the schema plus `LIMIT 0` validation feedback (column names or the driver error).

## Run it

```bash
# 1. Create the bundled sample database (coffee-shop dataset)
python scripts/create_sample_db.py

# 2. Set your Gemini key (or put it in .env — falls back to ../general-chat/.env)
export GOOGLE_API_KEY=...

# 3. Start everything
openbench demo run dashboard-chat
```

Manual start:

```bash
pip install -e .
uvicorn server:app --port 8007 --reload --reload-dir src
# in another terminal
cd frontend && pnpm install --ignore-workspace && pnpm dev
```

Open http://localhost:5173, sign in with `admin/admin123` (or `guest/guest123`), and connect `sqlite:///sample.db`. The first dashboard generates automatically.

## Accounts

Local username/password auth (PBKDF2 + stateless HMAC bearer tokens). Built-in accounts `admin` and `guest` (passwords via `DASHBOARD_CHAT_ADMIN_PASSWORD` / `DASHBOARD_CHAT_GUEST_PASSWORD`, defaults `admin123` / `guest123`). Admin can add users via `POST /admin/users`. Every account owns its **own** database connection, dashboard, and conversation.

## Other databases

SQLite works out of the box. For PostgreSQL, a bare `postgresql://user:pass@host:5432/db` URL automatically uses whichever driver is installed (psycopg v3 — already an openbench dependency in most setups — or psycopg2). Bare `mysql://` URLs fall back to pymysql the same way. If neither driver exists:

```bash
pip install psycopg2-binary   # PostgreSQL
pip install pymysql           # MySQL
```

## Security notes (local-dev scope)

- Database URLs (including passwords) are stored **in plaintext** in `.openbench/db-connections.json`. Do not use this example as-is with production credentials.
- Chart SQL is stored server-side and referenced by panel id — the client never submits SQL.
- All SQL execution is guarded: single-statement `SELECT`/`WITH` only, `LIMIT` cap (`DASHBOARD_CHAT_MAX_ROWS`, default 5000), best-effort statement timeout, and passwords redacted in every API response.

## Layout

```
server.py                  # uvicorn entry (port 8007)
src/dashboard_chat/
  app.py                   # FastAPI app: auth middleware + all routes
  auth.py / users.py       # local auth (HMAC tokens, PBKDF2 user store)
  connections.py           # per-user DB connections + schema introspection
  sqlguard.py              # read-only SQL guard + LIMIT-0 validation
  dashboards.py            # per-user dashboard spec store (versioned)
  tools.py                 # owner-scoped agent tools (4)
  agent.py / handler.py    # shared Gemini agent + per-user AG-UI handler
soul/                      # persona (SOUL / STYLE / AGENTS)
scripts/create_sample_db.py
frontend/                  # React 19 + Vite: dashboard canvas + chat side pane
```

Tests live at the repo root: `tests/test_dashboard_chat_*.py`.
