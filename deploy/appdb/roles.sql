-- Bootstrap the appdata database + mart schema + mcp_app role on Cloud SQL.
--
-- Run against a MAINTENANCE connection (the `postgres` db) — `deploy.sh
-- init-appdb` handles that and passes the role password as :mcp_password:
--
--     bash deploy/deploy.sh init-appdb
--
-- Idempotent: safe to re-run. Creating a database can't live in a txn, so this
-- uses psql \gexec / \connect meta-commands (apply with psql, not a driver).

-- 1. Create the appdata database if it does not exist.
SELECT 'CREATE DATABASE appdata'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'appdata')\gexec

-- 2. Create the read/materialize role if missing, then (re)set its password so
--    it always matches MCP_DB_DATABASE_URL.
SELECT 'CREATE ROLE mcp_app LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mcp_app')\gexec
ALTER ROLE mcp_app LOGIN PASSWORD :'mcp_password';

-- 3. Switch into appdata and set up schemas + grants.
\connect appdata

CREATE SCHEMA IF NOT EXISTS mart;

GRANT CONNECT ON DATABASE appdata TO mcp_app;
GRANT USAGE ON SCHEMA public, mart TO mcp_app;
GRANT CREATE ON SCHEMA mart TO mcp_app;

-- Read seeded business data (public); full control of materialized tables (mart).
GRANT SELECT ON ALL TABLES IN SCHEMA public TO mcp_app;
GRANT ALL    ON ALL TABLES IN SCHEMA mart   TO mcp_app;

-- Cover future tables too.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mcp_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA mart   GRANT ALL    ON TABLES TO mcp_app;
