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

-- 4. Optional SELECT-only role for the Grafana datasource. Created only when
--    `deploy.sh init-appdb` finds GRAFANA_RO_PASSWORD in the VM's .env.gcp
--    (it passes the value as :grafana_ro_password, empty otherwise). Point
--    Grafana at it with GRAFANA_PG_USER=grafana_ro and
--    GRAFANA_PG_PASSWORD=<same value>, then `deploy.sh grafana`. A Grafana
--    viewer can send its own SQL to the datasource, so the role it logs in
--    with must not be able to write.
SELECT (:'grafana_ro_password' <> '') AS has_grafana_ro \gset
\if :has_grafana_ro
  SELECT 'CREATE ROLE grafana_ro LOGIN'
  WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_ro')\gexec
  ALTER ROLE grafana_ro LOGIN PASSWORD :'grafana_ro_password';

  GRANT CONNECT ON DATABASE appdata TO grafana_ro;
  GRANT USAGE ON SCHEMA public, mart TO grafana_ro;
  GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro;
  GRANT SELECT ON ALL TABLES IN SCHEMA mart   TO grafana_ro;

  -- Future tables: public ones are created by the admin running this script;
  -- mart ones are created by mcp_app (materialize_query), so the default
  -- privilege has to be set for that role. The admin must be a member of
  -- mcp_app for the second statement (Cloud SQL admins are not superusers).
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO grafana_ro;
  GRANT mcp_app TO CURRENT_USER;
  ALTER DEFAULT PRIVILEGES FOR ROLE mcp_app IN SCHEMA mart GRANT SELECT ON TABLES TO grafana_ro;
\endif
