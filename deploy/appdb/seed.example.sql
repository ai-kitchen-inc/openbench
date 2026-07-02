-- Example of adding MORE data to appdata after init (the ".sql" data path).
-- Apply with:
--     bash deploy/deploy.sh seed-mcp-db deploy/appdb/seed.example.sql
--
-- Or edit rows directly in DBeaver over a local cloud-sql-proxy (see
-- deploy/DEPLOY.md). Idempotent: upserts so it can be re-run.

INSERT INTO products (id, name, category, price, in_stock) VALUES
    (6, 'Webcam 1080p', 'electronics', 89.00, true),
    (7, 'Notebook',     'stationery',   4.50, true)
ON CONFLICT (id) DO UPDATE
    SET name     = EXCLUDED.name,
        category = EXCLUDED.category,
        price    = EXCLUDED.price,
        in_stock = EXCLUDED.in_stock;

INSERT INTO orders (user_id, product_id, quantity, status, total_amount, ordered_at) VALUES
    (2, 6,  3, 'paid', 267.00, '2026-06-12'),
    (3, 7, 10, 'paid',  45.00, '2026-06-14');

GRANT SELECT ON ALL TABLES IN SCHEMA public TO mcp_app;
