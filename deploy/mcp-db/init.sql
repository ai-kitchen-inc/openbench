-- Mock data for the db_server MCP's SQLite database.
-- SQLite translation of mock-db/init.sql (Postgres: SERIAL -> INTEGER PRIMARY KEY
-- AUTOINCREMENT, NOW() -> CURRENT_TIMESTAMP). Apply with:
--   bash deploy/deploy.sh seed-mcp-db deploy/mcp-db/init.sql
-- Idempotent: drops the tables first so re-seeding is clean.

DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id),
  status TEXT NOT NULL,
  total_amount NUMERIC(10, 2) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO users (name, email) VALUES
  ('Alice Tan', 'alice@example.com'),
  ('Budi Santoso', 'budi@example.com'),
  ('Carla Wijaya', 'carla@example.com');

INSERT INTO orders (user_id, status, total_amount) VALUES
  (1, 'paid', 120.50),
  (1, 'pending', 75.00),
  (2, 'paid', 220.00),
  (3, 'cancelled', 40.00);
