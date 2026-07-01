-- Starter data for the db_server MCP's SQLite database.
--
-- The mcp-db-server is READ-ONLY: the chat agent can list_tables / describe /
-- query, but cannot write. Load data here instead, then apply it with:
--
--     bash deploy/deploy.sh seed-mcp-db deploy/mcp-db/seed.example.sql
--
-- Re-runnable: IF NOT EXISTS + a clean re-insert keep it idempotent. Copy this
-- file and edit the schema/rows for your own data.

CREATE TABLE IF NOT EXISTS products (
    id       INTEGER PRIMARY KEY,
    name     TEXT    NOT NULL,
    category TEXT    NOT NULL,
    price    REAL    NOT NULL,
    in_stock INTEGER NOT NULL DEFAULT 1
);

DELETE FROM products;
INSERT INTO products (id, name, category, price, in_stock) VALUES
    (1, 'Aeron Chair',      'furniture',   1395.00, 1),
    (2, 'Standing Desk',    'furniture',    699.00, 1),
    (3, 'Mechanical Keyboard', 'electronics', 129.99, 1),
    (4, '4K Monitor',       'electronics',  449.00, 0),
    (5, 'Desk Lamp',        'lighting',      59.50, 1);

CREATE TABLE IF NOT EXISTS orders (
    id         INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity   INTEGER NOT NULL,
    ordered_at TEXT    NOT NULL
);

DELETE FROM orders;
INSERT INTO orders (id, product_id, quantity, ordered_at) VALUES
    (1, 1, 2, '2026-06-01'),
    (2, 3, 5, '2026-06-03'),
    (3, 5, 1, '2026-06-07'),
    (4, 2, 1, '2026-06-09');
