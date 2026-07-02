# db-server (vendored fork of mcp-db-server)

Vendored fork of [`Souhar-dya/mcp-db-server`](https://github.com/Souhar-dya/mcp-db-server)
at **v1.3.1** (commit `29acf6b`), used as the general-chat `db_server` MCP.

It is a stdio MCP server (fastMCP) that exposes a SQL database to the agent. In
this deployment it points at the Cloud SQL Postgres **`appdata`** database via a
`cloud-sql-proxy` sidecar (see [deploy/DEPLOY.md](../../../../deploy/DEPLOY.md)).

## Why we vendor + build our own image

Upstream is published as `souhardyak/mcp-db-server:1.3.1`. We build our own image
(`…/openbench/mcp-db-server:1.3.1-ob<N>`) from this tree so we can:

- add a **`materialize_query`** tool — `CREATE TABLE mart.<name> AS <select>` so
  the agent can turn computed datasets into real Postgres tables that Superset
  charts live;
- make the **row cap configurable** via `MCP_MAX_ROWS` (upstream hard-codes 20/50);
- **gate all write tools** behind `MCP_ALLOW_WRITES` (default off).

Our changes are confined to `mcp_server.py` and `app/db.py`; everything else is
upstream. See the git history for the exact diff (the vendor commit is
unmodified upstream; the following commit adds our changes).

## Environment

| Var | Default | Meaning |
|-----|---------|---------|
| `DATABASE_URL` | sqlite (dev) | e.g. `postgresql://mcp_app:***@cloud-sql-proxy:5432/appdata` |
| `MCP_ALLOW_WRITES` | `0` | when set (`1`/`true`), enables write + materialize tools |
| `MCP_MAX_ROWS` | `1000` | max rows returned by read queries |
| `ENABLE_HF_MODEL` | `false` | keep off — rule-based NL→SQL, keeps the image light |

## License

Upstream is MIT (see [LICENSE](LICENSE)). This fork retains it.
